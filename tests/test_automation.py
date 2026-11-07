import asyncio
import json

import pytest

from harbor_terminal.automation import ReceiveStream, StreamOverflow, run_flow, validate_steps
from harbor_terminal.commands import load_library, save_library, parse_flow
from harbor_terminal.session import Worker


async def test_cancelled_flow_is_not_written_after_an_awaited_protocol_reply():
    worker=Worker('SSH',{});worker._set_state('Connected')
    identifier=worker.submit_flow([dict(action='delay',seconds=1)])
    assert worker.send(b'must-not-send',owner=identifier) and worker.respond(b'protocol-reply')
    started=asyncio.Event();release=asyncio.Event();received=[]
    class Transport:
        async def write(self,data):
            received.append(data)
            if data==b'protocol-reply':started.set();await release.wait()
    writer=asyncio.create_task(worker._writer(Transport()))
    try:
        await asyncio.wait_for(started.wait(),1)
        worker.cancel_flow(identifier)
        with worker.lock:worker._flow_job=None
        release.set();await asyncio.sleep(.03)
        assert received==[b'protocol-reply']
    finally:
        worker.stop_event.set();release.set();await asyncio.wait_for(writer,1)


async def test_receive_cursor_matches_fragmented_unicode_and_ansi_and_retains_tail():
    stream=ReceiveStream();cursor=stream.cursor()
    encoded='before 你\x1b[31m好\x1b[0m# next$'.encode()
    for byte in encoded:stream.append(bytes([byte]))
    first=await stream.read_until(cursor,['你好#','before'],.1)
    assert first['match_index']==2 and first['text']==''
    second=await stream.read_until(cursor,['你好#'],.1)
    assert second['text']==' ' and second['match_index']==1
    third=await stream.read_until(cursor,['$'],.1)
    assert third['text']==' next'


async def test_receive_cursor_reports_overflow_close_and_wait_cancellation():
    stream=ReceiveStream(capacity=8);cursor=stream.cursor();stream.append(b'0123456789')
    with pytest.raises(StreamOverflow):await stream.read_until(cursor,['9'],.1)
    cursor=stream.cursor();task=asyncio.create_task(stream.read_until(cursor,['not-yet'],10))
    await asyncio.sleep(0);assert stream.waiters
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert not stream.waiters
    stream.close()
    with pytest.raises(ConnectionError):await stream.read_until(cursor,['missing'],.1)


async def test_subscription_before_send_catches_immediate_reply_and_returns_match_index():
    stream=ReceiveStream();cursor=stream.cursor();sent=[]
    def send(data):sent.append(data);stream.append(b'command-output\x1b[32mready#\x1b[0m');return True
    result=await run_flow(stream,cursor,[dict(action='send',text='probe'),dict(action='wait',patterns=['$','ready#'],timeout=.1)],send)
    assert sent==[b'probe\r']
    assert result['captures'][0]['text']=='command-output' and result['captures'][0]['match_index']==2


async def test_wait_timeout_never_sends_later_steps():
    stream=ReceiveStream();sent=[]
    with pytest.raises(TimeoutError):
        await run_flow(stream,stream.cursor(),[dict(action='wait',patterns=['missing'],timeout=.05),
            dict(action='send',text='must-not-send')],lambda data:sent.append(data) or True)
    assert not sent and not stream.waiters


@pytest.mark.parametrize('steps',[
    [],[dict(action='python',text='print(1)')],[dict(action=['send'])],
    [dict(action='send',text='bad\x1b[31m')],[dict(action='send',text='x',password='secret')],
    [dict(action='wait',patterns=['x'],timeout=True)],[dict(action='delay',seconds=31)],
    [dict(action='wait',patterns=['']*17)]])
def test_flow_rejects_invalid_unbounded_or_executable_actions(steps):
    with pytest.raises(ValueError):validate_steps(steps)


def test_command_library_atomic_validation_and_unknown_secret_fields(tmp_path):
    path=tmp_path/'commands.json';commands={'查询':dict(text='show version',pinned=True)}
    save_library(path,commands);before=path.read_bytes();assert load_library(path)==commands
    with pytest.raises(ValueError):save_library(path,{'bad':dict(text='x',password='test-only')})
    assert path.read_bytes()==before
    with pytest.raises(ValueError):parse_flow('{"version":true,"steps":[]}')


async def wait(predicate):
    async with asyncio.timeout(5):
        while not predicate():await asyncio.sleep(.01)


@pytest.fixture
async def worker_connection(sftp_endpoint):
    worker=Worker('SSH',sftp_endpoint.options);events=[];worker.flow_result.connect(events.append)
    task=asyncio.create_task(worker.session())
    await wait(lambda:worker.status=='Connected')
    yield worker,events
    worker.stop_event.set();await asyncio.wait_for(task,5)


async def test_real_worker_flow_has_receive_cursor_independent_of_gui_consumer(worker_connection):
    worker,events=worker_connection
    request=worker.submit_flow([dict(action='send',text='first#'),dict(action='wait',patterns=['#']),
        dict(action='send',text='第二$'),dict(action='wait',patterns=['$'])])
    async with asyncio.timeout(5):
        while not events:worker.take();await asyncio.sleep(.005)
    assert events[0]['id']==request and events[0]['status']=='success'
    assert events[0]['sends_queued']==2
    assert len(events[0]['result']['captures'])==2
    assert '第二' in events[0]['result']['captures'][1]['text']
    assert worker.status=='Connected'


async def test_ctrl_c_cancels_flow_without_replaying_or_losing_interrupt(worker_connection):
    worker,events=worker_connection;worker.trace.configure(True,True)
    request=worker.submit_flow([dict(action='send',text='first'),dict(action='wait',patterns=['never'],timeout=2),
        dict(action='send',text='must-not-send')])
    await wait(lambda:worker.flow_progress().get('step')==2)
    assert not worker.send(b'manual-must-not-mix')
    assert worker.send(b'\x03')
    await wait(lambda:bool(events))
    await wait(lambda:any(record['direction']=='TX' and b'\x03' in record['data'] for record in worker.trace.snapshot()['records']))
    sent=b''.join(record['data'] for record in worker.trace.snapshot()['records'] if record['direction']=='TX')
    assert b'must-not-send' not in sent and b'manual-must-not-mix' not in sent
    assert events[0]['status']=='cancelled' and worker.status=='Connected'
    assert not worker.cancel_flow(request)
