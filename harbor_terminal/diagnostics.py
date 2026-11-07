"""Exercise the bundled desktop on the OS executing it, then exit."""
from importlib.metadata import version
from pathlib import Path
import platform
import tempfile

from PySide6.QtCore import QTimer, Qt, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QFontDialog

from .reports import atomic_json


async def protocol_probe(root):
    """Run packaged crypto/SSH/SFTP/MFA/tunnel/batch code on loopback only."""
    import asyncio
    import os
    import asyncssh
    from .transport import SSHTransport
    from .sftp import SFTPService, FileRequest
    from .forwarding import ForwardManager, ForwardSpec
    from .startup import argument_parser
    from .batch import run_batch
    checks={};remote=root/'remote';remote.mkdir()
    key=asyncssh.generate_private_key('ssh-ed25519');host_key=asyncssh.generate_private_key('ssh-ed25519')
    private=root/'encrypted-key';private.write_bytes(key.export_private_key(passphrase='local-fixture-only'));private.chmod(0o600)
    plain=root/'batch-key';plain.write_bytes(key.export_private_key());plain.chmod(0o600)
    async def tcp_echo(reader,writer):
        try:
            while data:=await reader.read(65536):writer.write(data);await writer.drain()
        finally:writer.close();await writer.wait_closed()
    tcp=await asyncio.start_server(tcp_echo,'127.0.0.1',0);tcp_port=tcp.sockets[0].getsockname()[1]
    class Server(asyncssh.SSHServer):
        def begin_auth(self,username):return True
        def public_key_auth_supported(self):return True
        def validate_public_key(self,username,pub):return username=='smoke' and pub.get_fingerprint()==key.get_fingerprint()
        def kbdint_auth_supported(self):return True
        def get_kbdint_challenge(self,username,lang,methods):
            return ('Local test','Line one\nLine two','',[('OTP:',False)]) if username=='smoke-mfa' else False
        def validate_kbdint_response(self,username,answers):return username=='smoke-mfa' and answers==['fixture-code']
        def connection_requested(self,host,port,*_):return host=='127.0.0.1' and port==tcp_port
    async def shell(process):
        while True:
            try:data=await process.stdin.read(4096)
            except asyncssh.TerminalSizeChanged:continue
            if not data:break
            process.stdout.write(data)
    server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[host_key],process_factory=shell,
        encoding=None,line_editor=False,sftp_factory=lambda channel:asyncssh.SFTPServer(channel,chroot=os.fsencode(remote)))
    known=root/'known_hosts';known.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode()+host_key.export_public_key())
    options=dict(host='127.0.0.1',username='smoke',port=server.get_port(),known_hosts=str(known),
                 client_keys=[str(private)],passphrase='local-fixture-only',auth_method='publickey-only')
    client=SSHTransport();manager=None
    try:
        await client.connect(**options);await client.write(b'packaged-ssh#')
        received=bytearray()
        async with asyncio.timeout(5):
            while len(received)<13:received.extend(await client.read())
        checks['encrypted_key_and_ssh']=bytes(received)==b'packaged-ssh#'
        source=root/'payload.bin';source.write_bytes(bytes(range(256))*4)
        service=SFTPService(client.connection)
        await service.execute(FileRequest('upload','/payload.bin',str(source)))
        target=root/'download.bin';await service.execute(FileRequest('download','/payload.bin',str(target)))
        checks['sftp_binary_roundtrip']=target.read_bytes()==source.read_bytes()
        manager=ForwardManager(client.connection)
        entry=await manager.start(ForwardSpec('local',0,'127.0.0.1',tcp_port))
        reader,writer=await asyncio.open_connection('127.0.0.1',entry['listen_port'])
        writer.write(b'\0\xffbundle');await writer.drain()
        checks['tcp_forward']=await asyncio.wait_for(reader.readexactly(8),5)==b'\0\xffbundle'
        writer.close();await writer.wait_closed();await manager.stop(entry['id'])
        unknown=root/'unknown';unknown.write_text('')
        rejected=SSHTransport()
        try:await rejected.connect(**dict(options,known_hosts=str(unknown)))
        except asyncssh.HostKeyNotVerifiable:checks['untrusted_host_rejected']=True
        else:checks['untrusted_host_rejected']=False
        finally:await rejected.close()
        mfa=SSHTransport();seen=[]
        async def response(event):seen.append(event['prompts']);return ['fixture-code']
        await mfa.connect('127.0.0.1','smoke-mfa',port=server.get_port(),known_hosts=str(known),
                          client_keys=[],auth_method='interactive-only',auth_prompt=response)
        await mfa.close();checks['keyboard_interactive']=seen==[[('OTP:',False)]]
        flow=root/'flow.json';batch_result=root/'batch.json'
        import json
        flow.write_text(json.dumps(dict(version=1,steps=[dict(action='send',text='bundle-batch#'),
                                                       dict(action='wait',patterns=['#'])])))
        args=argument_parser().parse_args([f'smoke@127.0.0.1:{server.get_port()}',
            '--identity-file',str(plain),'--known-hosts',str(known),'--run-flow',str(flow),'--output',str(batch_result)])
        checks['batch_flow']=await run_batch(args)==0
    finally:
        if manager:await manager.close_all()
        await client.close();server.close();await server.wait_closed();tcp.close();await tcp.wait_closed()
    return checks


def desktop_smoke(app, report_path):
    from .app import Window, ConnectionOptions
    from .appearance import terminal_font
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    report_path = Path(report_path).resolve()
    if report_path.exists(): raise FileExistsError('Choose a new report path')
    result = dict(status='running', version=version('harbor-terminal'), platform=platform.platform(),
                  python=platform.python_version(), qt=qVersion(), checks={})
    atomic_json(report_path, result)
    with tempfile.TemporaryDirectory(prefix='harbor-smoke-') as temporary:
        window = Window(profile_path=Path(temporary)/'sessions.json')
        try:
            window.show(); app.processEvents()
            result['ui_font'] = QFontInfo(window.font()).family()
            result['terminal_font'] = QFontInfo(terminal_font()).family()
            screen = window.screen()
            result['display'] = dict(dpr=window.devicePixelRatioF(), dpi=screen.logicalDotsPerInch(),
                                      width=window.width(), height=window.height())
            result['checks']['mainwindow'] = window.isVisible() and bool(window.menuBar().actions())
            import asyncio
            result['checks'].update(asyncio.run(protocol_probe(Path(temporary))))
            window.quick_action.trigger(); app.processEvents()
            result['checks']['quick_connect'] = window.quick_dialog.isVisible()
            def dismiss_options():
                modal = app.activeModalWidget()
                result['checks']['nested_options'] = isinstance(modal, ConnectionOptions) and modal.parentWidget() is window.quick_dialog
                if modal: modal.reject()
            QTimer.singleShot(50, dismiss_options); window.edit_options()
            window.quick_dialog.reject(); app.processEvents()
            def dismiss_font():
                modal = app.activeModalWidget()
                result['checks']['font_dialog'] = isinstance(modal, QFontDialog)
                if modal: modal.reject()
            QTimer.singleShot(50, dismiss_font); window.choose_terminal_font()
            result['checks']['no_connection_side_effect'] = not window.workers
            result['checks']['screenshot'] = window.grab().save(str(report_path.with_suffix('.png')))
            result['status'] = 'passed' if all(result['checks'].values()) else 'failed'
        except Exception as exc:
            result['status'] = 'failed'; result['error_type'] = type(exc).__name__
        finally:
            window.close(); app.processEvents()
    atomic_json(report_path, result)
    return 0 if result['status'] == 'passed' else 1
