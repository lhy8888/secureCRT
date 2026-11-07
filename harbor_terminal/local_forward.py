"""Owned loopback TCP/SOCKS5 listeners with exclusive Windows binding."""
import asyncio
import os
import socket
import weakref


_owned = weakref.WeakKeyDictionary()


async def close_owned_listeners(connection):
    listeners = list(_owned.get(connection, ()))
    await asyncio.gather(*(listener.shutdown() for listener in listeners), return_exceptions=True)


class FlowBudget:
    def __init__(self, maximum=64): self.active, self.maximum = 0, maximum
    def acquire(self):
        if self.active >= self.maximum: return False
        self.active += 1; return True
    def release(self): self.active -= 1


class LocalListener:
    def __init__(self, connection, spec, budget):
        self.connection, self.spec, self.budget = connection, spec, budget
        self.server = None; self.monitor = None; self.flows = set(); self.closing_connection = False
        self.port = 0

    @classmethod
    async def create(cls, connection, spec, budget):
        listener = cls(connection, spec, budget)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # SO_REUSEADDR on Windows allows another listener to share/hijack
            # this address. Set exclusivity before bind, never after listen.
            if os.name == 'nt':
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', spec.listen_port)); sock.setblocking(False)
            listener.port = sock.getsockname()[1]
            listener.server = await asyncio.start_server(listener.handle, sock=sock, backlog=32)
            _owned.setdefault(connection, weakref.WeakSet()).add(listener)
            listener.monitor = asyncio.create_task(listener.watch_connection())
            return listener
        except BaseException:
            sock.close()
            if listener.server: listener.server.close(); await listener.server.wait_closed()
            raise

    def get_port(self): return self.port
    def close(self): self.server.close()

    async def wait_closed(self):
        await self.server.wait_closed()
        if not self.flows and self.monitor and not self.closing_connection:
            self.monitor.cancel(); await asyncio.gather(self.monitor, return_exceptions=True)

    async def shutdown(self):
        self.closing_connection = True; self.server.close()
        tasks = list(self.flows)
        for task in tasks: task.cancel()
        if self.monitor and self.monitor is not asyncio.current_task():
            self.monitor.cancel(); tasks.append(self.monitor)
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        await self.server.wait_closed()

    async def watch_connection(self):
        try:
            await self.connection.wait_closed()
            self.closing_connection = True; self.server.close()
            tasks = list(self.flows)
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    @staticmethod
    async def socks_target(reader, writer):
        version, methods = await reader.readexactly(2)
        offered = await reader.readexactly(methods)
        if version != 5 or 0 not in offered:
            writer.write(b'\x05\xff'); await writer.drain(); raise ValueError('SOCKS5 no-auth is required')
        writer.write(b'\x05\x00'); await writer.drain()
        version, command, reserved, address_type = await reader.readexactly(4)
        if version != 5 or reserved or command != 1:
            writer.write(b'\x05\x07\x00\x01'+b'\0'*6); await writer.drain()
            raise ValueError('Only SOCKS5 TCP CONNECT is supported')
        if address_type == 1:
            host = socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
        elif address_type == 4:
            host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
        elif address_type == 3:
            length = (await reader.readexactly(1))[0]
            if not length: raise ValueError('Empty SOCKS domain')
            host = (await reader.readexactly(length)).decode('ascii')
            if any(ord(c)<33 or ord(c)==127 for c in host): raise ValueError('Invalid SOCKS domain')
        else:
            writer.write(b'\x05\x08\x00\x01'+b'\0'*6); await writer.drain()
            raise ValueError('Unsupported SOCKS address')
        port = int.from_bytes(await reader.readexactly(2), 'big')
        if not port: raise ValueError('Invalid SOCKS destination port')
        return host, port

    async def handle(self, reader, writer):
        if not self.budget.acquire():
            writer.close(); await writer.wait_closed(); return
        task = asyncio.current_task(); self.flows.add(task)
        remote = None; pumps = []
        try:
            host, port = self.spec.destination_host, self.spec.destination_port
            if self.spec.kind == 'socks':
                host, port = await asyncio.wait_for(self.socks_target(reader, writer), 10)
            peer = writer.get_extra_info('peername') or ('127.0.0.1', 0)
            try:
                upstream, remote = await asyncio.wait_for(self.connection.open_connection(
                    host, port, orig_host=peer[0], orig_port=peer[1]), 15)
            except Exception:
                if self.spec.kind == 'socks':
                    writer.write(b'\x05\x05\x00\x01'+b'\0'*6); await writer.drain()
                return
            if self.spec.kind == 'socks':
                writer.write(b'\x05\x00\x00\x01'+b'\0'*6); await writer.drain()
            async def pump(source, target):
                while data := await source.read(65536):
                    target.write(data); await target.drain()
                if hasattr(target, 'can_write_eof') and not target.can_write_eof(): return
                target.write_eof()
            pumps = [asyncio.create_task(pump(reader, remote)), asyncio.create_task(pump(upstream, writer))]
            await asyncio.gather(*pumps)
        except (Exception, asyncio.CancelledError):
            pass  # Per-flow refusal/cancellation never tears down the SSH owner.
        finally:
            for pump in pumps: pump.cancel()
            if pumps: await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (remote, writer):
                if stream:
                    stream.close()
                    try: await asyncio.wait_for(stream.wait_closed(), 2)
                    except Exception: pass
            self.flows.discard(task); self.budget.release()
            if (not self.flows and not self.server.is_serving() and self.monitor
                    and not self.closing_connection):
                self.monitor.cancel()
