import asyncio
import socket
import asyncssh
import pytest

from harbor_terminal.transport import SSHTransport
from harbor_terminal.forwarding import ForwardManager,ForwardSpec


@pytest.fixture
async def forwarded(sftp_endpoint):
    client=SSHTransport();await client.connect(**sftp_endpoint.options)
    async def echo(reader,writer):
        try:
            while data:=await reader.read(65536):
                writer.write(data);await writer.drain()
        finally:
            writer.close();await writer.wait_closed()
    echo_server=await asyncio.start_server(echo,'127.0.0.1',0)
    port=echo_server.sockets[0].getsockname()[1]
    sftp_endpoint.controls.allowed_destinations.add(('127.0.0.1',port))
    manager=ForwardManager(client.connection)
    yield client,manager,port
    await manager.close_all();await client.close()
    echo_server.close();await echo_server.wait_closed()


async def roundtrip(port,expected=b'\x00\xffthrough-ssh\r\n'):
    reader,writer=await asyncio.open_connection('127.0.0.1',port)
    try:
        writer.write(expected);await writer.drain()
        assert await asyncio.wait_for(reader.readexactly(len(expected)),2)==expected
    finally:writer.close();await writer.wait_closed()


@pytest.mark.parametrize('kind',['local','remote'])
async def test_real_forward_roundtrip_and_stop_releases_listening_port(forwarded,kind):
    client,manager,port=forwarded
    entry=await manager.start(ForwardSpec(kind,0,'127.0.0.1',port))
    assert entry['listen_host']=='127.0.0.1' and entry['listen_port']>0
    await roundtrip(entry['listen_port'])
    await manager.stop(entry['id'])
    assert not manager.snapshot()
    with pytest.raises(OSError):await asyncio.open_connection('127.0.0.1',entry['listen_port'])
    await client.write(b'interactive-survives\n')
    assert await asyncio.wait_for(client.read(),2)==b'interactive-survives\n'


async def test_socks5_handshake_routes_actual_binary_payload(forwarded):
    _,manager,port=forwarded
    entry=await manager.start(ForwardSpec('socks'))
    reader,writer=await asyncio.open_connection('127.0.0.1',entry['listen_port'])
    try:
        writer.write(b'\x05\x01\x00');await writer.drain()
        assert await asyncio.wait_for(reader.readexactly(2),2)==b'\x05\x00'
        writer.write(b'\x05\x01\x00\x01'+socket.inet_aton('127.0.0.1')+port.to_bytes(2,'big'))
        await writer.drain()
        response=await asyncio.wait_for(reader.readexactly(10),2)
        assert response[:2]==b'\x05\x00'
        writer.write(b'\x00\xffsocks');await writer.drain()
        assert await asyncio.wait_for(reader.readexactly(7),2)==b'\x00\xffsocks'
    finally:writer.close();await writer.wait_closed()


async def test_bind_conflict_preserves_first_listener_and_owner_close_releases_all(forwarded):
    client,manager,port=forwarded
    first=await manager.start(ForwardSpec('local',0,'127.0.0.1',port))
    with pytest.raises(OSError):
        await manager.start(ForwardSpec('local',first['listen_port'],'127.0.0.1',port))
    assert len(manager.snapshot())==1
    await roundtrip(first['listen_port'])
    await client.close()
    with pytest.raises(OSError):await asyncio.open_connection('127.0.0.1',first['listen_port'])


@pytest.mark.parametrize('options',[
    dict(kind='bad'),dict(kind='local',listen_port=-1,destination_port=22),
    dict(kind='local',destination_port=0),dict(kind='local',destination_host='a\nb',destination_port=22),
    dict(kind='remote',listen_port=True,destination_port=22)])
def test_invalid_forward_specs_are_rejected(options):
    with pytest.raises(ValueError):ForwardSpec(**options)


async def test_listener_capacity_is_bounded_and_all_owned_ports_are_released(forwarded):
    _,manager,port=forwarded
    entries=[]
    for _ in range(16):entries.append(await manager.start(ForwardSpec('local',0,'127.0.0.1',port)))
    with pytest.raises(ValueError):await manager.start(ForwardSpec('socks'))
    assert len(manager.snapshot())==16
    assert await manager.close_all()==0
    for entry in entries:
        with pytest.raises(OSError):await asyncio.open_connection('127.0.0.1',entry['listen_port'])


async def test_socks_domain_route_and_unsupported_auth_do_not_end_ssh(forwarded,sftp_endpoint):
    client,manager,port=forwarded
    sftp_endpoint.controls.allowed_destinations.add(('localhost',port))
    entry=await manager.start(ForwardSpec('socks'))
    reader,writer=await asyncio.open_connection('127.0.0.1',entry['listen_port'])
    writer.write(b'\x05\x01\x02');await writer.drain()
    assert await asyncio.wait_for(reader.readexactly(2),2)==b'\x05\xff'
    writer.close();await writer.wait_closed()
    reader,writer=await asyncio.open_connection('127.0.0.1',entry['listen_port'])
    try:
        writer.write(b'\x05\x01\x00');await writer.drain()
        assert await reader.readexactly(2)==b'\x05\x00'
        writer.write(b'\x05\x01\x00\x03\x09localhost'+port.to_bytes(2,'big'));await writer.drain()
        assert (await asyncio.wait_for(reader.readexactly(10),3))[:2]==b'\x05\x00'
        writer.write(b'domain-route');await writer.drain()
        assert await asyncio.wait_for(reader.readexactly(12),2)==b'domain-route'
    finally:writer.close();await writer.wait_closed()
    await client.write(b'still-open\n')
    assert await asyncio.wait_for(client.read(),2)==b'still-open\n'


async def test_owner_close_releases_partial_socks_handshake_and_budget(forwarded):
    client,manager,_=forwarded
    entry=await manager.start(ForwardSpec('socks'))
    reader,writer=await asyncio.open_connection('127.0.0.1',entry['listen_port'])
    writer.write(b'\x05');await writer.drain()
    await asyncio.sleep(.02)
    assert manager.budget.active==1
    await client.close()
    assert await asyncio.wait_for(reader.read(),2)==b''
    assert manager.budget.active==0
    writer.close();await writer.wait_closed()


async def test_local_forward_preserves_half_close_and_final_response(forwarded,sftp_endpoint):
    _,manager,_=forwarded
    async def respond_after_eof(reader,writer):
        data=await reader.read()
        writer.write(data[::-1]);await writer.drain();writer.close();await writer.wait_closed()
    server=await asyncio.start_server(respond_after_eof,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    sftp_endpoint.controls.allowed_destinations.add(('127.0.0.1',port))
    try:
        entry=await manager.start(ForwardSpec('local',0,'127.0.0.1',port))
        reader,writer=await asyncio.open_connection('127.0.0.1',entry['listen_port'])
        writer.write(b'half-close');await writer.drain();writer.write_eof()
        assert await asyncio.wait_for(reader.read(),3)==b'esolc-flah'
        writer.close();await writer.wait_closed()
    finally:server.close();await server.wait_closed()
