"""Owned SSH forwarding listeners. All listeners bind loopback by policy."""
import asyncio
from dataclasses import dataclass
import uuid


@dataclass(frozen=True)
class ForwardSpec:
    kind: str
    listen_port: int = 0
    destination_host: str = '127.0.0.1'
    destination_port: int = 0

    def __post_init__(self):
        if self.kind not in ('local', 'remote', 'socks'):
            raise ValueError('Invalid forward direction')
        if type(self.listen_port) is not int or not 0 <= self.listen_port <= 65535:
            raise ValueError('Invalid listening port')
        if self.kind != 'socks':
            if type(self.destination_port) is not int or not 1 <= self.destination_port <= 65535:
                raise ValueError('Invalid destination port')
            if (not isinstance(self.destination_host, str) or not self.destination_host.strip()
                    or len(self.destination_host) > 1024
                    or any(ord(c) < 33 for c in self.destination_host)):
                raise ValueError('Invalid destination host')


class ForwardManager:
    def __init__(self, connection):
        self.connection = connection
        self.listeners = {}

    async def start(self, spec):
        if len(self.listeners) >= 16:
            raise ValueError('At most 16 forwarding listeners per session')
        if spec.kind == 'local':
            operation = self.connection.forward_local_port('127.0.0.1', spec.listen_port,
                spec.destination_host, spec.destination_port)
        elif spec.kind == 'remote':
            operation = self.connection.forward_remote_port('127.0.0.1', spec.listen_port,
                spec.destination_host, spec.destination_port)
        else:
            operation = self.connection.forward_socks('127.0.0.1', spec.listen_port)
        listener = await asyncio.wait_for(operation, 15)
        identifier = uuid.uuid4().hex
        entry = dict(id=identifier, kind=spec.kind, listen_host='127.0.0.1',
                     listen_port=listener.get_port(), destination_host=spec.destination_host,
                     destination_port=spec.destination_port, state='listening')
        self.listeners[identifier] = (listener, entry)
        return dict(entry)

    def snapshot(self):
        return [dict(entry) for _, entry in self.listeners.values()]

    async def stop(self, identifier):
        listener, entry = self.listeners[identifier]
        listener.close()
        try:
            await asyncio.wait_for(listener.wait_closed(), 3)
        except Exception:
            entry['state'] = 'unknown'
            raise
        del self.listeners[identifier]

    async def close_all(self):
        identifiers = list(self.listeners)
        results = await asyncio.gather(*(self.stop(key) for key in identifiers), return_exceptions=True)
        return sum(isinstance(result, BaseException) for result in results)
