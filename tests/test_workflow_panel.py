import asyncio
import json

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from harbor_terminal.app import Window


async def until(app,predicate):
    async with asyncio.timeout(6):
        while not predicate():app.processEvents();await asyncio.sleep(.01)


@pytest.fixture
async def pair(sftp_endpoint,tmp_path):
    app=QApplication.instance() or QApplication([])
    window=Window(profile_path=tmp_path/'sessions.json');window.show();views=[]
    for name in ('first','second'):
        window.host.setText('127.0.0.1');window.port.setText(str(sftp_endpoint.port));window.user.setText('tester')
        window.password.setText('test-only');window.known.setText(str(sftp_endpoint.known));window.connect_session()
        view=window.tabs.currentWidget();view.session_label=name;views.append(view)
        await until(app,lambda:view.worker.status=='Connected')
        view.worker.trace.configure(True,True)
    window.tabs.setCurrentWidget(views[0]);window.open_command_panel();app.processEvents()
    yield app,window,window.command_panel,views
    for worker in window.workers:worker.stop_event.set()
    await until(app,lambda:all(not worker.isRunning() for worker in window.workers))
    window.close();app.processEvents()


def transmitted(worker):
    return b''.join(record['data'] for record in worker.trace.snapshot()['records'] if record['direction']=='TX')


async def test_command_preview_freezes_target_even_if_active_tab_changes(pair,monkeypatch):
    app,window,panel,views=pair;seen=[]
    def edit(text,names,parent,**kwargs):
        seen.extend(names);window.tabs.setCurrentWidget(views[1]);return 'edited#\n'
    monkeypatch.setattr('harbor_terminal.workflow_panel.preview',edit)
    panel.edit.setPlainText('original');panel.send_commands()
    await until(app,lambda:bool(transmitted(views[0].worker)))
    assert seen==['first'] and transmitted(views[0].worker)==b'edited#\r'
    assert not transmitted(views[1].worker)
    assert panel.history==['edited#\n'] and not panel.path.exists()


async def test_actual_preview_edits_are_revalidated_before_any_send(pair):
    app,window,panel,views=pair;edited=[]
    def inject():
        modal=app.activeModalWidget()
        if modal:
            editor=modal.findChild(QPlainTextEdit);editor.setPlainText('bad\x1b[31m');edited.append(True);modal.accept()
    QTimer.singleShot(30,inject)
    panel.edit.setPlainText('original');panel.send_commands()
    assert edited==[True] and not transmitted(views[0].worker) and not panel.history
    assert '控制字符' in panel.status.text()


async def test_pinned_button_uses_current_session_and_never_inherits_broadcast_targets(pair,monkeypatch):
    app,window,panel,views=pair;seen=[]
    panel.persist_library({'Probe':dict(text='pinned#',pinned=True)})
    for index in range(panel.targets.topLevelItemCount()):panel.targets.topLevelItem(index).setCheckState(0,Qt.CheckState.Checked)
    window.tabs.setCurrentWidget(views[1])
    def accept(text,names,parent,**kwargs):seen.extend(names);return text
    monkeypatch.setattr('harbor_terminal.workflow_panel.preview',accept)
    window.command_buttons.actions()[0].trigger()
    await until(app,lambda:bool(transmitted(views[1].worker)))
    assert seen==['second'] and transmitted(views[1].worker)==b'pinned#\r'
    assert not transmitted(views[0].worker)
    assert json.loads(panel.path.read_text(encoding='utf-8'))['commands']['Probe']['pinned'] is True


async def test_multiple_flows_cancel_without_sending_later_commands(pair,monkeypatch):
    app,window,panel,views=pair
    for index in range(panel.targets.topLevelItemCount()):panel.targets.topLevelItem(index).setCheckState(0,Qt.CheckState.Checked)
    monkeypatch.setattr('harbor_terminal.workflow_panel.preview',lambda text,*args,**kwargs:text)
    panel.flow_edit.setPlainText(json.dumps(dict(version=1,steps=[
        dict(action='wait',patterns=['not-present'],timeout=3),dict(action='send',text='never-send')])))
    panel.start_flows();assert len(panel.pending)==2
    await until(app,lambda:all(view.worker.flow_progress().get('step')==1 for view in views))
    panel.cancel_flows();await until(app,lambda:not panel.pending)
    assert all(not transmitted(view.worker) for view in views)
    assert all(view.worker.status=='Connected' for view in views)
