"""Bounded asynchronous transports. Never trust unknown SSH host keys implicitly."""
import asyncio
from pathlib import Path
import asyncssh
import serial

from .serial_config import SerialSettings


class IncompleteWriteError(IOError):
    def __init__(self, sent):
        super().__init__('Incomplete serial write')
        self.sent = sent if isinstance(sent, int) and sent >= 0 else 0


class SSHTransport:
    def __init__(self):
        self.connection = None
        self.process = None
        self._jump_connection = None

    async def connect(self, host, username, *, port=22, password=None,
                      known_hosts=None, client_keys=None, passphrase=None,
                      term_size=(100, 30), timeout=15, jump=None, status=None):
        if self.connection is not None:
            raise RuntimeError("Already connected")
        connection = hop = None
        try:
            if jump:
                allowed = {'host','username','port','password','known_hosts','client_keys','passphrase'}
                if not isinstance(jump, dict) or set(jump) - allowed:
                    raise ValueError('Only one explicitly configured SSH jump is supported')
                if status: status('ConnectingJump')
                hop = await self._open_ssh(**jump, timeout=timeout)
            if status: status('ConnectingTarget')
            connection = await self._open_ssh(host, username, port=port, password=password,
                known_hosts=known_hosts, client_keys=client_keys, passphrase=passphrase,
                timeout=timeout, tunnel=hop)
            process = await asyncio.wait_for(connection.create_process(
                term_type='xterm-256color', term_size=term_size, encoding=None, stderr=asyncssh.STDOUT), timeout)
        except BaseException:
            await asyncio.gather(*(self._close_connection(item) for item in (connection,hop) if item),
                                 return_exceptions=True)
            raise
        self.connection, self.process = connection, process
        self._jump_connection = hop

    @staticmethod
    async def _open_ssh(host, username, *, port=22, password=None, known_hosts=None,
                        client_keys=None, passphrase=None, timeout=15, tunnel=None):
        if not host or not username or not 1 <= int(port) <= 65535:
            raise ValueError('Invalid host, username, or port')
        # Both hops independently verify their own endpoint identity.
        path = Path(known_hosts) if known_hosts else Path.home() / '.ssh' / 'known_hosts'
        if not path.is_file():
            raise ValueError('Create a known_hosts file using an independently verified host fingerprint first')
        return await asyncio.wait_for(asyncssh.connect(host, port=int(port), username=username,
            password=password, known_hosts=str(path), client_keys=client_keys, passphrase=passphrase,
            tunnel=tunnel, connect_timeout=timeout, login_timeout=timeout,
            keepalive_interval=15, keepalive_count_max=3, agent_forwarding=False), timeout=timeout)

    async def read(self):
        return await self.process.stdout.read(16384)

    async def write(self, data):
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def resize(self, columns, rows):
        if self.process:
            self.process.change_terminal_size(columns, rows)

    async def send_break(self, duration=0.25):
        if not 0 < duration <= 2:
            raise ValueError('BREAK duration must be at most two seconds')
        self.process.channel.send_break(int(duration * 1000))

    async def close(self):
        connection, self.connection = self.connection, None
        hop, self._jump_connection = self._jump_connection, None
        self.process = None
        try:
            if connection:
                await self._close_connection(connection)
        finally:
            if hop:
                await self._close_connection(hop)

    @staticmethod
    async def _close_connection(connection):
        connection.close()
        try:
            await asyncio.wait_for(connection.wait_closed(), 5)
        except TimeoutError:
            connection.abort()
            await asyncio.wait_for(connection.wait_closed(), 1)


class SerialTransport:
    def __init__(self):
        self.port = None

    async def connect(self, device, baudrate=115200, bytesize=8, parity='N',
                      stopbits=1, flow_control='none'):
        if self.port:
            raise RuntimeError("Already connected")
        settings = SerialSettings(int(baudrate), int(bytesize), parity,
                                  float(stopbits), flow_control)
        # Cancellation must close a port opened by the worker after cancellation.
        task = asyncio.create_task(asyncio.to_thread(serial.Serial, device,
            timeout=0.1, write_timeout=2, **settings.port_options()))
        try:
            self.port = await asyncio.shield(task)
        except asyncio.CancelledError:
            port = await task
            port.close()
            raise

    async def read(self):
        port = self.port
        task = asyncio.create_task(asyncio.to_thread(
            port.read, min(max(port.in_waiting, 1), 16384)))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if hasattr(port, 'cancel_read'):
                port.cancel_read()
            await task
            raise

    async def write(self, data):
        port = self.port
        task = asyncio.create_task(asyncio.to_thread(port.write, data))
        try:
            count = await asyncio.shield(task)
        except asyncio.CancelledError:
            # Join the bounded write before closing/reusing the OS handle.
            await task
            raise
        if count != len(data):
            raise IncompleteWriteError(count)

    async def send_break(self, duration=0.25):
        if not 0 < duration <= 2:
            raise ValueError('BREAK duration must be at most two seconds')
        port = self.port
        task = asyncio.create_task(asyncio.to_thread(port.send_break, duration))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def close(self):
        port, self.port = self.port, None
        if port:
            await asyncio.to_thread(port.close)
