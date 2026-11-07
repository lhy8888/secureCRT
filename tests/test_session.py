import asyncio
import pytest
from harbor_terminal.session import Worker


class FlowTransport:
    def __init__(self):
        self.connected=asyncio.Event(); self.written=asyncio.Event(); self.closed=False
        self.writes=[]; self.sizes=[]
    async def connect(self, **options): self.connected.set()
    async def read(self): return b'x'*16384
    async def write(self, data): self.writes.append(data);self.written.set()
    async def resize(self, *size): self.sizes.append(size)
    async def close(self): self.closed=True


async def test_full_receive_buffer_cannot_starve_ctrl_c_or_resize():
    transport=FlowTransport()
    worker=Worker('SSH',{},transport_factory=lambda:transport)
    task=asyncio.create_task(worker.session())
    try:
        await asyncio.wait_for(transport.connected.wait(),1)
        async with asyncio.timeout(1):
            while len(worker.incoming)<262144: await asyncio.sleep(.01)
        assert worker.send(b'\x03')
        worker.resize(81,29)
        await asyncio.wait_for(transport.written.wait(),1)
        async with asyncio.timeout(1):
            while (81,29) not in transport.sizes: await asyncio.sleep(.01)
        assert transport.writes==[b'\x03']
        assert len(worker.incoming)==262144
    finally:
        worker.stop_event.set();await asyncio.wait_for(task,1)
    assert transport.closed and worker.status=='Disconnected'
    assert not worker.send(b'cannot-replay')


async def test_stop_cancels_pending_connect_without_waiting_for_login_timeout():
    class Stalled(FlowTransport):
        cancelled=False
        async def connect(self,**options):
            self.connected.set()
            try: await asyncio.Event().wait()
            except asyncio.CancelledError: self.cancelled=True; raise
    transport=Stalled()
    worker=Worker('SSH',{'password':'test-only'},transport_factory=lambda:transport)
    task=asyncio.create_task(worker.session())
    await asyncio.wait_for(transport.connected.wait(),1)
    assert not worker.send(b'must-not-be-sent-after-login')
    worker.stop_event.set()
    await asyncio.wait_for(task,.5)
    assert transport.cancelled and transport.closed
    assert 'password' not in worker.options
    assert not worker.outgoing


async def test_partial_serial_write_observation_contains_only_reported_bytes():
    from harbor_terminal.transport import IncompleteWriteError
    class Partial:
        calls=0
        async def write(self,data):
            self.calls+=1
            raise IncompleteWriteError(2)
    worker=Worker('Serial',{});worker._set_state('Connected')
    worker.trace.configure(True,True)
    assert worker.send(b'ABCD')
    transport=Partial()
    with pytest.raises(IncompleteWriteError):await worker._writer(transport)
    value=worker.trace.snapshot()
    assert b''.join(x['data'] for x in value['records'])==b'AB'
    assert transport.calls==1 and not worker.outgoing
