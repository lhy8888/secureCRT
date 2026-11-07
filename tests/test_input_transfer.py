import asyncio
import os
import time

import pytest

from harbor_terminal.input_policy import InputPolicy
from harbor_terminal.keyboard import prepare_paste
from harbor_terminal.session import Worker
from harbor_terminal.text_files import prepare_file,TextCapture
from harbor_terminal.transport import SerialTransport


async def until(predicate,seconds=5):
    async with asyncio.timeout(seconds):
        while not predicate():await asyncio.sleep(.005)


class Echo:
    def __init__(self):self.queue=asyncio.Queue();self.writes=[];self.closed=False
    async def connect(self,**options):pass
    async def read(self):return await self.queue.get()
    async def resize(self,*size):pass
    async def write(self,data):self.writes.append((time.monotonic(),data));await self.queue.put(data)
    async def close(self):self.closed=True


@pytest.mark.parametrize('field,value',[
    ('send_char_delay_ms','1001'),('send_line_delay_ms','30001'),('send_char_delay_ms','-1'),
    ('send_char_delay_ms','１'),('send_line_delay_ms',True),('paste_newline','unknown'),
    ('paste_quote','cmd'),('remote_clear_history','false'),('alt_meta','unsafe')])
def test_invalid_input_policies_rejected(field,value):
    with pytest.raises(ValueError):InputPolicy.parse({field:value})


def test_text_encoding_newlines_control_guard_and_quotes():
    raw='世界\r\nnext\rfinal'.encode('utf-16')
    assert prepare_file(raw,'utf-16','gb18030','crlf')=='世界\r\nnext\r\nfinal'.encode('gb18030')
    assert prepare_file(b'\xef\xbb\xbfline','utf-8-sig','utf-8','keep')==b'line'
    for data in (b'a\x1b[201~',b'a\0',b'a'*65537,b'a'*1048577,b'\xff'):
        with pytest.raises((ValueError,UnicodeError)):prepare_file(data,'utf-8','utf-8','cr')
    assert prepare_paste("a'b\r\nnext",newline='crlf',quote='posix')==b"'a'\"'\"'b\r\nnext'"
    assert prepare_paste("a'b",quote='powershell',bracketed=True)==b"\x1b[200~'a''b'\x1b[201~"


@pytest.mark.parametrize('step',[1,2,7,1000])
def test_plain_receive_capture_handles_fragmented_unicode_control_sequences_and_crlf(tmp_path,step):
    path=tmp_path/'receive.txt';capture=TextCapture(path,source_encoding='gb18030',output_encoding='utf-8',newline='crlf')
    payload='你好\r\n\x1b[31mred\x1b[0m\r\x1b]2;untrusted-title\x07end'.encode('gb18030')
    capture.start()
    for i in range(0,len(payload),step):assert capture.record(payload[i:i+step])
    assert capture.close(5) and capture.snapshot()['state']=='closed'
    assert path.read_bytes()=='你好\r\nred\r\nend'.encode()
    assert capture.snapshot()['accepted']==len(payload) and capture.snapshot()['queued']==0


def test_receive_capture_never_overwrites_and_reports_decode_size_and_queue_failures(tmp_path):
    existing=tmp_path/'existing';existing.write_bytes(b'keep')
    capture=TextCapture(existing);capture.start();assert capture.close(5)
    assert capture.snapshot()['state']=='error' and existing.read_bytes()==b'keep'
    capture=TextCapture(tmp_path/'malformed');capture.start();capture.record(b'prefix\xe4');assert capture.close(5)
    assert capture.snapshot()['state']=='error' and (tmp_path/'malformed').read_bytes()==b'prefix'
    capture=TextCapture(tmp_path/'quota',max_bytes=1024);capture.start();capture.record(b'A'*512);capture.record(b'B'*700);assert capture.close(5)
    assert capture.snapshot()['state']=='error' and (tmp_path/'quota').read_bytes()==b'A'*512
    capture=TextCapture(tmp_path/'queue',capacity=1)
    assert not capture.record(b'AB') and capture.snapshot()['state']=='error'


async def test_paced_text_writes_have_real_gaps_and_crlf_has_one_line_delay():
    transport=Echo();worker=Worker('SSH',{},transport_factory=lambda:transport,
        input_policy=dict(send_char_delay_ms='20',send_line_delay_ms='60'))
    events=[];worker.flow_result.connect(events.append);task=asyncio.create_task(worker.session())
    try:
        await until(lambda:worker.status=='Connected')
        identifier=worker.submit_text(b'A\r\nB',encoding='utf-8');assert identifier
        await until(lambda:events)
        assert events[0]['status']=='success' and events[0]['bytes_sent']==4
        assert [value for _,value in transport.writes]==[b'A',b'\r',b'\n',b'B']
        gaps=[b[0]-a[0] for a,b in zip(transport.writes,transport.writes[1:])]
        assert gaps[0]>=.015 and gaps[1]>=.015 and gaps[2]>=.075
    finally:worker.stop_event.set();await asyncio.wait_for(task,3)


async def test_cancelled_text_never_sends_owned_tail_and_protocol_reply_bypasses_line_pause():
    transport=Echo();worker=Worker('SSH',{},transport_factory=lambda:transport,input_policy=dict(send_line_delay_ms='1000'))
    events=[];worker.flow_result.connect(events.append);task=asyncio.create_task(worker.session())
    try:
        await until(lambda:worker.status=='Connected');identifier=worker.submit_text(b'first\rsecond\r')
        await until(lambda:transport.writes)
        assert not worker.send(b'must-not-interleave') and worker.respond(b'\x1b[1;1R')
        await until(lambda:len(transport.writes)>=2,seconds=.5)
        assert transport.writes[1][1]==b'\x1b[1;1R'
        assert worker.cancel_flow(identifier);await until(lambda:events)
        assert events[0]['status']=='cancelled' and events[0]['bytes_sent']==6
        assert b''.join(data for _,data in transport.writes)==b'first\r\x1b[1;1R'
        assert not worker.outgoing
    finally:worker.stop_event.set();await asyncio.wait_for(task,3)


async def test_cancellation_waits_for_inflight_write_before_reporting_confirmed_byte_count():
    class Held(Echo):
        def __init__(self):super().__init__();self.entered=asyncio.Event();self.release=asyncio.Event()
        async def write(self,data):self.entered.set();await self.release.wait();await super().write(data)
    transport=Held();worker=Worker('SSH',{},transport_factory=lambda:transport);events=[];worker.flow_result.connect(events.append)
    task=asyncio.create_task(worker.session())
    try:
        await until(lambda:worker.status=='Connected');identifier=worker.submit_text(b'first\rnever\r')
        await transport.entered.wait();assert worker.cancel_flow(identifier);await asyncio.sleep(.05)
        assert not events and worker.submit_flow([dict(action='send',text='other')]) is None
        transport.release.set();await until(lambda:events)
        assert events[0]['status']=='cancelled' and events[0]['bytes_sent']==6 and not events[0]['write_uncertain']
        assert b''.join(data for _,data in transport.writes)==b'first\r'
    finally:transport.release.set();worker.stop_event.set();await asyncio.wait_for(task,3)


async def test_per_line_prompt_uses_fresh_receive_data_and_stops_on_deadline():
    transport=Echo();worker=Worker('SSH',{},transport_factory=lambda:transport);events=[];worker.flow_result.connect(events.append)
    task=asyncio.create_task(worker.session())
    try:
        await until(lambda:worker.status=='Connected');worker.receive_stream.append(b'old-ready#')
        identifier=worker.submit_text(b'first\rsecond\r',prompt='ready#',timeout=.15);assert identifier
        await until(lambda:events)
        assert events[0]['status']=='error' and events[0]['code']=='TimeoutError' and events[0]['bytes_sent']==6
        assert b''.join(data for _,data in transport.writes)==b'first\r'
    finally:worker.stop_event.set();await asyncio.wait_for(task,3)


@pytest.mark.parametrize('partial',[True,False])
async def test_failed_ascii_write_reports_known_prefix_or_uncertainty_and_never_retries(partial):
    from harbor_terminal.transport import IncompleteWriteError
    class Failed(Echo):
        calls=0
        async def write(self,data):
            self.calls+=1
            raise IncompleteWriteError(2) if partial else ConnectionResetError('fixture')
    transport=Failed();worker=Worker('SSH',{},transport_factory=lambda:transport);events=[];worker.flow_result.connect(events.append)
    task=asyncio.create_task(worker.session())
    await until(lambda:worker.status=='Connected');assert worker.submit_text(b'first\rnever\r')
    await asyncio.wait_for(task,3)
    assert transport.calls==1 and transport.closed and events
    assert events[0]['status']=='error' and events[0]['bytes_sent']==(2 if partial else 0)
    assert events[0]['write_uncertain'] is (not partial) and not worker.outgoing


async def test_actual_ssh_text_send_and_receive_capture(tmp_path):
    from test_ssh_security import peer
    async with peer(tmp_path) as endpoint:
        worker=Worker('SSH',endpoint.options,input_policy=dict(send_char_delay_ms='1'))
        events=[];worker.flow_result.connect(events.append);task=asyncio.create_task(worker.session())
        payload='第一行\r\nsecond\r\n'.encode();path=tmp_path/'captured.txt'
        try:
            await until(lambda:worker.status=='Connected')
            assert worker.start_text_capture(path,source_encoding='utf-8',output_encoding='gb18030',newline='lf')
            assert worker.submit_text(payload)
            await until(lambda:events and len(worker.receive_stream.text)>=len(payload.decode()))
            worker.stop_text_capture();await until(lambda:not worker.text_capture.snapshot()['alive'])
            assert events[0]['status']=='success' and path.read_bytes()=='第一行\nsecond\n'.encode('gb18030')
        finally:worker.stop_event.set();await asyncio.wait_for(task,3)


@pytest.mark.skipif(os.name=='nt',reason='Unix PTY; physical Windows COM remains a user-run check')
async def test_actual_serial_text_send_and_modem_status_unknown_on_unsupported_pty(tmp_path):
    import pty
    master,slave=pty.openpty();worker=Worker('Serial',dict(device=os.ttyname(slave)),input_policy=dict(send_char_delay_ms='1'))
    events=[];worker.flow_result.connect(events.append);task=asyncio.create_task(worker.session())
    try:
        await until(lambda:worker.status=='Connected')
        assert worker.submit_text(b'one\r\ntwo\r')
        await until(lambda:events)
        received=await asyncio.wait_for(asyncio.to_thread(os.read,master,1024),2)
        assert received==b'one\r\ntwo\r' and events[0]['bytes_sent']==len(received)
        await until(lambda:bool(worker.serial_snapshot()))
        assert worker.serial_snapshot()['cts'] is None and 'cts' in worker.serial_snapshot()['errors']
    finally:worker.stop_event.set();await asyncio.wait_for(task,3);os.close(master);os.close(slave)


async def test_serial_line_outputs_are_explicit_and_respect_automatic_flow_control():
    class Port:
        dtr=True;rts=False;cts=True;dsr=False;ri=False;cd=True
    transport=SerialTransport();transport.port=Port()
    assert (await transport.modem_status())['cts'] is True
    await transport.set_line('dtr',False);assert transport.port.dtr is False
    transport._flow_control='rtscts'
    with pytest.raises(ValueError):await transport.set_line('rts',True)
    assert transport.port.rts is False
    transport._flow_control='dsrdtr'
    with pytest.raises(ValueError):await transport.set_line('dtr',True)
    assert transport.port.dtr is False
