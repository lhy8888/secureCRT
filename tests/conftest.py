"""Local-only SSH/SFTP service for client integration and failure injection."""
import asyncio
import os
from pathlib import Path
import inspect
from types import SimpleNamespace

import asyncssh
import pytest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
if os.name == 'nt':
    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)


@pytest.fixture
async def sftp_endpoint(tmp_path):
    root=tmp_path/'remote';root.mkdir()
    controls=SimpleNamespace(corrupt_reads=False,deny_atomic=False,stall_commit=False,
                             write_delay=0,authentications=0,allowed_destinations=set(),
                             tiny_reads=False,read_cutoff=None,processes=0,received=bytearray())
    class Server(asyncssh.SSHServer):
        def begin_auth(self,username):return True
        def password_auth_supported(self):return True
        def validate_password(self,username,password):
            controls.authentications+=1
            return username=='tester' and password=='test-only'
        def connection_requested(self,dest_host,dest_port,orig_host,orig_port):
            return (dest_host,dest_port) in controls.allowed_destinations
        def server_requested(self,listen_host,listen_port):
            return listen_host=='127.0.0.1'
    class Files(asyncssh.SFTPServer):
        async def read(self,file_obj,offset,size):
            if controls.read_cutoff is not None:
                if offset>=controls.read_cutoff:raise asyncssh.SFTPEOFError('test-only premature EOF')
                size=min(size,controls.read_cutoff-offset)
            if controls.tiny_reads:size=min(size,1+offset%3)
            value=super().read(file_obj,offset,size)
            if inspect.isawaitable(value):value=await value
            if controls.corrupt_reads and value:
                value=bytes([value[0]^1])+value[1:]
            return value
        async def write(self,file_obj,offset,data):
            if controls.write_delay:await asyncio.sleep(controls.write_delay)
            value=super().write(file_obj,offset,data)
            return await value if inspect.isawaitable(value) else value
        async def link(self,oldpath,newpath):
            if controls.deny_atomic:raise asyncssh.SFTPOpUnsupported('test-only unsupported atomic publication')
            value=super().link(oldpath,newpath)
            if inspect.isawaitable(value):await value
            if controls.stall_commit:await asyncio.sleep(30)
        async def posix_rename(self,oldpath,newpath):
            if controls.deny_atomic:raise asyncssh.SFTPOpUnsupported('test-only unsupported atomic publication')
            value=super().posix_rename(oldpath,newpath)
            return await value if inspect.isawaitable(value) else value
    async def shell(process):
        controls.processes+=1
        while True:
            try:data=await process.stdin.read(1024)
            except asyncssh.TerminalSizeChanged:continue
            if not data:break
            controls.received.extend(data)
            process.stdout.write(data)
    key=asyncssh.generate_private_key('ssh-ed25519')
    server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],
        process_factory=shell,encoding=None,line_editor=False,
        sftp_factory=lambda channel:Files(channel,chroot=os.fsencode(root)))
    known=tmp_path/'known_hosts'
    known.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode()+key.export_public_key())
    yield SimpleNamespace(root=root,controls=controls,port=server.get_port(),known=known,
        options=dict(host='127.0.0.1',port=server.get_port(),username='tester',
                     password='test-only',known_hosts=str(known),client_keys=[]))
    server.close();await server.wait_closed()
