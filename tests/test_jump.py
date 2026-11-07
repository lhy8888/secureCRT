import asyncio
from types import SimpleNamespace
import asyncssh
import pytest

from harbor_terminal.transport import SSHTransport
from harbor_terminal.sftp import SFTPService,FileRequest


@pytest.fixture
async def jump_endpoint(sftp_endpoint,tmp_path):
    controls=SimpleNamespace(authentications=0,connections=[],target_port=sftp_endpoint.port)
    class Jump(asyncssh.SSHServer):
        def connection_made(self,connection):controls.connections.append(connection)
        def begin_auth(self,username):return True
        def password_auth_supported(self):return True
        def validate_password(self,username,password):
            controls.authentications+=1
            return username=='jumper' and password=='jump-test-only'
        def connection_requested(self,dest_host,dest_port,orig_host,orig_port):
            return dest_host=='127.0.0.1' and dest_port==controls.target_port
    key=asyncssh.generate_private_key('ssh-ed25519')
    server=await asyncssh.create_server(Jump,'127.0.0.1',0,server_host_keys=[key])
    known=tmp_path/'jump_known_hosts'
    known.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode()+key.export_public_key())
    yield SimpleNamespace(controls=controls,server=server,known=known,options=dict(
        host='127.0.0.1',port=server.get_port(),username='jumper',password='jump-test-only',
        known_hosts=str(known),client_keys=[]))
    server.close();await server.wait_closed()


async def test_jump_authenticates_each_host_and_carries_interactive_and_sftp(sftp_endpoint,jump_endpoint):
    client=SSHTransport();phases=[]
    await client.connect(**sftp_endpoint.options,jump=jump_endpoint.options,status=phases.append)
    target,hop=client.connection,client._jump_connection
    try:
        assert phases==['ConnectingJump','ConnectingTarget']
        assert jump_endpoint.controls.authentications==1 and sftp_endpoint.controls.authentications==1
        await client.write(b'via-jump\n')
        assert await asyncio.wait_for(client.read(),2)==b'via-jump\n'
        (sftp_endpoint.root/'target').write_bytes(b'test')
        inventory=await SFTPService(client.connection).execute(FileRequest('list','/'))
        assert any(e['name']=='target' for e in inventory['entries'])
        assert jump_endpoint.controls.authentications==1 and sftp_endpoint.controls.authentications==1
    finally:await client.close()
    assert target.is_closed() and hop.is_closed()


@pytest.mark.parametrize('side',['jump','target'])
async def test_untrusted_key_on_either_hop_is_rejected(sftp_endpoint,jump_endpoint,tmp_path,side):
    unknown=tmp_path/'unknown';unknown.write_text('')
    target=dict(sftp_endpoint.options);jump=dict(jump_endpoint.options)
    if side=='jump':jump['known_hosts']=str(unknown)
    else:target['known_hosts']=str(unknown)
    client=SSHTransport()
    with pytest.raises(asyncssh.HostKeyNotVerifiable):await client.connect(**target,jump=jump)
    assert client.connection is None and client._jump_connection is None
    assert sftp_endpoint.controls.authentications==0


async def test_jump_and_target_passwords_are_independent(sftp_endpoint,jump_endpoint):
    target=dict(sftp_endpoint.options);jump=dict(jump_endpoint.options)
    jump['password']='test-only'  # correct for target, incorrect for jump
    with pytest.raises(asyncssh.PermissionDenied):await SSHTransport().connect(**target,jump=jump)
    assert sftp_endpoint.controls.authentications==0


async def test_cancelling_pending_target_handshake_closes_jump_and_drops_secrets(sftp_endpoint,jump_endpoint):
    from harbor_terminal.session import Worker
    arrived=asyncio.Event();writers=[]
    async def stalled(reader,writer):
        writers.append(writer);arrived.set()
        try:await reader.read()
        finally:writer.close();await writer.wait_closed()
    trap=await asyncio.start_server(stalled,'127.0.0.1',0)
    port=trap.sockets[0].getsockname()[1]
    jump_endpoint.controls.target_port=port
    options=dict(sftp_endpoint.options,port=port,jump=jump_endpoint.options)
    worker=Worker('SSH',options)
    task=asyncio.create_task(worker.session())
    try:
        await asyncio.wait_for(arrived.wait(),2)
        assert worker.status=='ConnectingTarget'
        worker.stop_event.set()
        await asyncio.wait_for(task,2)
        assert worker.status=='Disconnected'
        assert 'jump' not in worker.options and 'password' not in worker.options
        async with asyncio.timeout(2):
            while not all(c.is_closed() for c in jump_endpoint.controls.connections):await asyncio.sleep(.01)
    finally:
        worker.stop_event.set()
        await asyncio.wait_for(task,3)
        for writer in writers:writer.close()
        trap.close();await trap.wait_closed()
