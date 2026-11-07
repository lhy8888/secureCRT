import asyncio
import base64
import json
import os
import time

import pytest
from PySide6.QtCore import Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from harbor_terminal.app import Window
from harbor_terminal.panels import SFTPDialog,LogDialog,HexDialog
from harbor_terminal.session import Worker


async def qt_until(app,predicate,seconds=6):
    async with asyncio.timeout(seconds):
        while not predicate():
            app.processEvents();await asyncio.sleep(.01)


@pytest.fixture
async def ssh_window(sftp_endpoint,tmp_path):
    app=QApplication.instance() or QApplication([])
    window=Window(profile_path=tmp_path/'sessions.json');window.show()
    window.host.setText('127.0.0.1');window.port.setText(str(sftp_endpoint.port))
    window.user.setText('tester');window.password.setText('test-only')
    window.known.setText(str(sftp_endpoint.known));window.connect_session()
    terminal=window.tabs.currentWidget();worker=terminal.worker
    await qt_until(app,lambda:worker.status=='Connected')
    yield app,window,terminal,worker,sftp_endpoint
    worker.stop_event.set()
    await qt_until(app,lambda:not worker.isRunning(),seconds=10)
    window.close();app.processEvents()


async def test_sftp_panel_reuses_auth_and_byte_transfers_while_terminal_operates(ssh_window,tmp_path):
    app,window,terminal,worker,endpoint=ssh_window
    (endpoint.root/'remote.bin').write_bytes(b'\0\xff'+b'firmware'*100)
    window.open_sftp();panel=window.service_panels[(worker,'sftp')]
    await qt_until(app,lambda:panel.pending is None)
    assert panel.tree.topLevelItemCount()==1
    assert panel.tree.topLevelItem(0).text(0)=='remote.bin'
    assert endpoint.controls.authentications==1
    local=tmp_path/'download.bin'
    identifier=panel.submit('download',remote_path='/remote.bin',local_path=str(local))
    assert identifier
    QTest.keyClick(terminal,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
    await qt_until(app,lambda:panel.pending is None)
    assert local.read_bytes()==(endpoint.root/'remote.bin').read_bytes()
    assert 'SHA-256' in panel.result_text.text()
    assert worker.status=='Connected'
    assert endpoint.controls.authentications==1
    assert terminal.screen.cursor.x>=0
    panel.close()


async def test_panel_cancel_keeps_original_and_terminal_connected(ssh_window,tmp_path):
    app,window,terminal,worker,endpoint=ssh_window
    endpoint.controls.write_delay=.03
    (endpoint.root/'target').write_bytes(b'original')
    source=tmp_path/'large';source.write_bytes(b'x'*3000000)
    window.open_sftp();panel=window.service_panels[(worker,'sftp')]
    await qt_until(app,lambda:panel.pending is None)
    panel.submit('upload',remote_path='/target',local_path=str(source),overwrite=True)
    await qt_until(app,lambda:worker.file_progress().get('current',0)>0)
    panel.cancel_operation()
    await qt_until(app,lambda:panel.pending is None)
    assert '已取消' in panel.status.text()
    assert (endpoint.root/'target').read_bytes()==b'original'
    assert not list(endpoint.root.glob('.harbor-*'))
    assert worker.status=='Connected'
    panel.close()


async def test_disconnect_cancels_transfer_and_flushes_exactly_one_disconnect_log(ssh_window,tmp_path):
    app,window,terminal,worker,endpoint=ssh_window
    endpoint.controls.write_delay=.03
    source=tmp_path/'large';source.write_bytes(b'x'*3000000)
    log=tmp_path/'session.jsonl';assert worker.start_log(log,mode='raw')
    events=[];worker.file_result.connect(events.append)
    request_id=worker.submit_file('upload',remote_path='/target',local_path=str(source))
    await qt_until(app,lambda:worker.file_progress().get('current',0)>0)
    worker.stop_event.set()
    await qt_until(app,lambda:not worker.isRunning(),seconds=10)
    await qt_until(app,lambda:bool(events))
    assert events[-1]['id']==request_id and events[-1]['status']=='cancelled'
    assert not (endpoint.root/'target').exists()
    assert not list(endpoint.root.glob('.harbor-*'))
    rows=[json.loads(line) for line in log.read_text().splitlines()]
    assert sum(x['event']=='disconnected' for x in rows)==1
    assert rows[-1]['event']=='log-stop'
    assert not worker.journal.snapshot()['alive']


async def test_file_error_does_not_end_ssh_and_window_callbacks_use_gui_thread(ssh_window):
    app,window,terminal,worker,endpoint=ssh_window
    observed=[]
    original=window.session_state
    def observe(owner,state):
        observed.append(QThread.currentThread()==window.thread());original(owner,state)
    window.session_state=observe
    events=[];worker.file_result.connect(events.append)
    identifier=worker.submit_file('list',remote_path='/missing')
    await qt_until(app,lambda:bool(events))
    assert events[0]['id']==identifier and events[0]['status']=='error'
    assert worker.status=='Connected'
    assert worker.send(b'after-file-error')
    await qt_until(app,lambda:'after-file-error' in terminal.toPlainText())
    worker.stop_event.set();await qt_until(app,lambda:not worker.isRunning())
    app.processEvents();assert observed and all(observed)


@pytest.mark.skipif(os.name=='nt',reason='Physical Windows COM validation remains required')
async def test_real_pty_hex_is_exact_and_session_bound_and_log_failure_isolated(tmp_path):
    import pty
    app=QApplication.instance() or QApplication([])
    master,slave=pty.openpty()
    window=Window(profile_path=tmp_path/'sessions.json');window.show()
    window.mode.setCurrentText('Serial');window.host.setText(os.ttyname(slave));window.connect_session()
    terminal=window.tabs.currentWidget();worker=terminal.worker
    try:
        await qt_until(app,lambda:worker.status=='Connected')
        window.open_hex();panel=window.service_panels[(worker,'hex')]
        panel.tx.setChecked(True)
        payload=b'\x00\xff\x1b[Araw'
        os.write(master,payload)
        def captured():
            return b''.join(r['data'] for r in worker.trace.snapshot()['records'] if r['direction']=='RX')
        await qt_until(app,lambda:captured()==payload)
        await qt_until(app,lambda:'RX' in panel.view.toPlainText() and 'FF' in panel.view.toPlainText())
        assert '\x1b' not in panel.view.toPlainText()
        # Opening another tab does not retarget the existing Hex tool.
        from harbor_terminal.terminal import Terminal
        other=Worker('Serial',{});other._set_state('Connected')
        other_view=Terminal(other);other_view.session_label='other-session'
        window.sessions[other]=other_view;window.workers.append(other)
        window.tabs.setCurrentIndex(window.tabs.addTab(other_view,'other-session'))
        panel.input.setText('00 ff 0d 0a');panel.send_hex()
        received=await asyncio.wait_for(asyncio.to_thread(os.read,master,4),2)
        assert received==b'\x00\xff\r\n'
        assert not other.outgoing
        await qt_until(app,lambda:'TX' in panel.view.toPlainText())
        assert worker.start_log(tmp_path)  # invalid: existing directory, real I/O failure
        await qt_until(app,lambda:worker.journal.snapshot()['state']=='error')
        assert worker.send(b'ok')
        assert await asyncio.wait_for(asyncio.to_thread(os.read,master,2),2)==b'ok'
        assert worker.status=='Connected'
        panel.close();assert not worker.trace.enabled
    finally:
        worker.stop_event.set();await qt_until(app,lambda:not worker.isRunning())
        window.close();app.processEvents();os.close(master);os.close(slave)


@pytest.mark.skipif(os.name=='nt',reason='Uses Unix PTY')
async def test_log_dialog_pause_resume_does_not_reopen_or_capture_tx(tmp_path):
    import pty
    app=QApplication.instance() or QApplication([])
    master,slave=pty.openpty()
    worker=Worker('Serial',dict(device=os.ttyname(slave)))
    worker.start()
    panel=LogDialog(worker,'test-only')
    try:
        await qt_until(app,lambda:worker.status=='Connected')
        path=tmp_path/'capture.jsonl';panel.path.setText(str(path))
        panel.mode.setCurrentIndex(1);panel.show();panel.start_log()
        await qt_until(app,lambda:worker.journal.snapshot()['state']=='running')
        os.write(master,b'first')
        await qt_until(app,lambda:worker.journal.snapshot()['written']>=5)
        panel.pause_log();assert worker.journal.snapshot()['paused']
        os.write(master,b'skipped')
        await qt_until(app,lambda:b'skipped' in worker.incoming)
        panel.pause_log();os.write(master,b'last')
        await qt_until(app,lambda:worker.journal.snapshot()['written']>=9)
        panel.close();await qt_until(app,lambda:not worker.journal.snapshot()['alive'])
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        assert b''.join(base64.b64decode(row['base64']) for row in rows if row['event']=='RX')==b'firstlast'
        assert not any(row['event']=='TX' for row in rows)
        assert not path.with_name(path.name+'.001').exists()
    finally:
        worker.stop_event.set();await qt_until(app,lambda:not worker.isRunning())
        panel.close();os.close(master);os.close(slave)


async def test_one_sftp_job_per_session_and_disconnect_does_not_duplicate_outcome(ssh_window,tmp_path):
    app,window,terminal,worker,endpoint=ssh_window
    endpoint.controls.write_delay=.03
    source=tmp_path/'large';source.write_bytes(b'x'*1000000)
    events=[];worker.file_result.connect(events.append)
    request=worker.submit_file('upload',remote_path='/target',local_path=str(source))
    assert request
    assert worker.submit_file('list',remote_path='/') is None
    assert not worker.cancel_file('different-request')
    await qt_until(app,lambda:worker.file_progress().get('current',0)>0)
    assert worker.cancel_file(request)
    worker.stop_event.set()
    await qt_until(app,lambda:not worker.isRunning(),seconds=10)
    await qt_until(app,lambda:bool(events))
    assert len(events)==1 and events[0]['id']==request
    assert events[0]['status']=='cancelled'
    assert not (endpoint.root/'target').exists()


async def test_forward_dialog_operates_real_tcp_and_disconnect_releases_listener(ssh_window):
    app,window,terminal,worker,endpoint=ssh_window
    async def echo(reader,writer):
        try:
            while data:=await reader.read(4096):writer.write(data);await writer.drain()
        finally:writer.close();await writer.wait_closed()
    echo_server=await asyncio.start_server(echo,'127.0.0.1',0)
    port=echo_server.sockets[0].getsockname()[1]
    endpoint.controls.allowed_destinations.add(('127.0.0.1',port))
    try:
        window.open_forwards();panel=window.service_panels[(worker,'forward')]
        panel.port.setValue(port);panel.start_button.click()
        await qt_until(app,lambda:panel.pending is None and len(worker.forwards())==1)
        entry=worker.forwards()[0]
        reader,writer=await asyncio.open_connection('127.0.0.1',entry['listen_port'])
        writer.write(b'panel-tunnel');await writer.drain()
        assert await asyncio.wait_for(reader.readexactly(12),2)==b'panel-tunnel'
        writer.close();await writer.wait_closed()
        assert panel.tree.topLevelItemCount()==1
        panel.tree.setCurrentItem(panel.tree.topLevelItem(0));panel.stop_button.click()
        await qt_until(app,lambda:panel.pending is None and not worker.forwards())
        with pytest.raises(OSError):await asyncio.open_connection('127.0.0.1',entry['listen_port'])
        panel.start_button.click()
        await qt_until(app,lambda:panel.pending is None and len(worker.forwards())==1)
        last=worker.forwards()[0]
        panel.close()  # hiding the manager does not silently drop active tunnels
        assert worker.forwards()
        worker.stop_event.set();await qt_until(app,lambda:not worker.isRunning())
        assert not worker.forwards()
        with pytest.raises(OSError):await asyncio.open_connection('127.0.0.1',last['listen_port'])
    finally:echo_server.close();await echo_server.wait_closed()
