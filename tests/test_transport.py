import asyncio
import os
import asyncssh
import pytest
from harbor_terminal.transport import SSHTransport, SerialTransport


class Server(asyncssh.SSHServer):
    def begin_auth(self, username): return True
    def password_auth_supported(self): return True
    def validate_password(self, username, password):
        return username == 'tester' and password == 'test-only-password'


async def echo(process):
    async for data in process.stdin:
        process.stdout.write(data)


@pytest.fixture
async def ssh_server(tmp_path):
    key = asyncssh.generate_private_key('ssh-ed25519')
    server = await asyncssh.create_server(Server, '127.0.0.1', 0,
        server_host_keys=[key], process_factory=echo, encoding=None)
    port = server.get_port()
    known = tmp_path / 'known_hosts'
    known.write_bytes(f'[127.0.0.1]:{port} '.encode() + key.export_public_key())
    yield port, known
    server.close()
    await server.wait_closed()


async def test_ssh_real_encrypted_echo_and_cleanup(ssh_server):
    port, known = ssh_server
    client = SSHTransport()
    await client.connect('127.0.0.1', 'tester', port=port,
        password='test-only-password', known_hosts=known)
    try:
        await client.write('你好 secure terminal\n'.encode())
        assert await asyncio.wait_for(client.read(), 3) == '你好 secure terminal\n'.encode()
    finally:
        await client.close()
    assert client.connection is None
    await client.close()


async def test_unknown_host_rejected(ssh_server, tmp_path):
    port, _ = ssh_server
    known = tmp_path / 'empty'; known.write_text('')
    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        await SSHTransport().connect('127.0.0.1', 'tester', port=port,
            password='test-only-password', known_hosts=known)


async def test_changed_key_rejected(ssh_server, tmp_path):
    port, _ = ssh_server
    known = tmp_path / 'wrong'
    key = asyncssh.generate_private_key('ssh-ed25519')
    known.write_bytes(f'[127.0.0.1]:{port} '.encode() + key.export_public_key())
    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        await SSHTransport().connect('127.0.0.1', 'tester', port=port,
            password='test-only-password', known_hosts=known)


async def test_bad_password_rejected(ssh_server):
    port, known = ssh_server
    with pytest.raises(asyncssh.PermissionDenied):
        await SSHTransport().connect('127.0.0.1', 'tester', port=port,
            password='wrong', known_hosts=known, client_keys=[])


async def test_stalled_server_has_deadline(tmp_path):
    writers = []
    async def stalled(reader, writer):
        writers.append(writer)
        await reader.read()
    server = await asyncio.start_server(stalled, '127.0.0.1', 0)
    known = tmp_path / 'known'; known.write_text('')
    try:
        with pytest.raises((TimeoutError, asyncssh.ConnectionLost)):
            await SSHTransport().connect('127.0.0.1', 'tester',
                port=server.sockets[0].getsockname()[1], known_hosts=known, timeout=.15)
    finally:
        for writer in writers:
            writer.close(); await writer.wait_closed()
        server.close(); await server.wait_closed()


@pytest.mark.skipif(os.name == "nt", reason="PTY smoke test requires Unix; hardware Windows COM test remains required")
async def test_serial_real_pty_bidirectional_and_close():
    import pty
    master, slave = pty.openpty()
    client = SerialTransport()
    try:
        await client.connect(os.ttyname(slave))
        os.write(master, b'router console\r\n')
        received = bytearray()
        async with asyncio.timeout(2):
            while len(received) < len(b'router console\r\n'):
                received.extend(await client.read())
        assert received == b'router console\r\n'
        await client.write(b'show version\r')
        assert await asyncio.wait_for(asyncio.to_thread(os.read, master, 100), 2) == b'show version\r'
    finally:
        await client.close(); os.close(master); os.close(slave)
    assert client.port is None
    await client.close()


async def test_parallel_sessions_and_reconnect_cycles(ssh_server):
    port, known = ssh_server
    async def cycle(identifier):
        client = SSHTransport()
        try:
            await client.connect('127.0.0.1', 'tester', port=port,
                password='test-only-password', known_hosts=known)
            payload = (f'session-{identifier}:' + 'x' * 2048 + '\n').encode()
            await client.write(payload)
            received = bytearray()
            async with asyncio.timeout(5):
                while len(received) < len(payload):
                    part = await client.read()
                    assert part
                    received.extend(part)
            assert received == payload
        finally:
            await client.close()
    for _ in range(3):
        await asyncio.gather(*(cycle(i) for i in range(8)))


async def test_missing_known_hosts_has_actionable_error(tmp_path):
    with pytest.raises(ValueError, match='independently verified'):
        await SSHTransport().connect('example.invalid', 'tester', known_hosts=tmp_path / 'missing')


async def test_serial_partial_write_fails_explicitly():
    class PartialPort:
        def write(self, data): return len(data) - 1
    client = SerialTransport()
    client.port = PartialPort()
    with pytest.raises(IOError, match='Incomplete'):
        await client.write(b'command\r')


async def test_real_ssh_terminal_size_changes_reach_server(tmp_path):
    processes=[]
    async def capture(process):
        processes.append(process)
        while True:
            try:
                data = await process.stdin.readline()
            except asyncssh.TerminalSizeChanged:
                # AsyncSSH delivers PTY resize as a stream control event.
                continue
            if not data:
                break
            process.stdout.write(data)
    key=asyncssh.generate_private_key('ssh-ed25519')
    server=await asyncssh.create_server(Server,'127.0.0.1',0,
        server_host_keys=[key],process_factory=capture,encoding=None)
    port=server.get_port(); known=tmp_path/'hosts'
    known.write_bytes(f'[127.0.0.1]:{port} '.encode()+key.export_public_key())
    client=SSHTransport()
    try:
        await client.connect('127.0.0.1','tester',port=port,password='test-only-password',
                             known_hosts=known,term_size=(110,35))
        assert processes[0].term_size[:2]==(110,35)
        await client.resize(81,27)
        async with asyncio.timeout(2):
            while processes[0].term_size[:2]!=(81,27): await asyncio.sleep(.01)
        await client.write(b'still-interactive\n')
        assert await asyncio.wait_for(client.read(),2)==b'still-interactive\n'
    finally:
        await client.close();server.close();await server.wait_closed()


async def test_encrypted_openssh_private_key_authentication(tmp_path):
    user_key=asyncssh.generate_private_key('ssh-ed25519')
    class KeyServer(asyncssh.SSHServer):
        def begin_auth(self,username): return True
        def public_key_auth_supported(self): return True
        def validate_public_key(self,username,key):
            return username=='tester' and key.export_public_key()==user_key.export_public_key()
    host_key=asyncssh.generate_private_key('ssh-ed25519')
    server=await asyncssh.create_server(KeyServer,'127.0.0.1',0,
        server_host_keys=[host_key],process_factory=echo,encoding=None)
    port=server.get_port();known=tmp_path/'hosts';identity=tmp_path/'id_test'
    known.write_bytes(f'[127.0.0.1]:{port} '.encode()+host_key.export_public_key())
    identity.write_bytes(user_key.export_private_key('openssh',passphrase='test-only-key-passphrase'))
    client=SSHTransport()
    try:
        await client.connect('127.0.0.1','tester',port=port,known_hosts=known,
            client_keys=[str(identity)],passphrase='test-only-key-passphrase')
        await client.write(b'key-authenticated\n')
        assert await asyncio.wait_for(client.read(),2)==b'key-authenticated\n'
    finally:
        await client.close();server.close();await server.wait_closed()
