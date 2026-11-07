import asyncio
from copy import deepcopy

import pytest
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication,QDialog

from harbor_terminal.app import Window
from harbor_terminal import profiles
from harbor_terminal.session_manager import SessionManager,ImportDialog,ChangePreview,BatchEditor,TemplateDialog


async def until(app,predicate):
    async with asyncio.timeout(8):
        while not predicate():app.processEvents();await asyncio.sleep(.01)


@pytest.fixture
async def desktop(tmp_path):
    app=QApplication.instance() or QApplication([]);windows=[]
    def make(path=None):
        window=Window(profile_path=path or tmp_path/'sessions.json');windows.append(window);window.show();app.processEvents();return app,window
    yield make
    for window in windows:
        for worker in window.workers:worker.stop_event.set()
    await until(app,lambda:all(not worker.isRunning() for window in windows for worker in window.workers)
                and all(not window._probe or not window._probe.isRunning() for window in windows))
    for window in windows:window.close();window.deleteLater()
    app.processEvents()


async def test_two_windows_require_reload_before_merging_changes(desktop):
    app,one=desktop();_,two=desktop(one.profile_path)
    assert one.commit_profiles({'甲':dict(host='one.invalid')})
    assert not two.commit_profiles({'乙':dict(host='two.invalid')})
    assert profiles.load(one.profile_path)==one.profiles
    assert '另一个窗口' in two.status.text()
    assert two.reload_profiles()
    assert two.commit_profiles(dict(two.profiles,乙=dict(host='two.invalid')))
    assert set(profiles.load(one.profile_path))=={'甲','乙'}


async def test_preview_cancel_and_same_window_revision_change_cannot_overwrite(desktop):
    app,window=desktop();assert window.commit_profiles({'甲':dict(host='one.invalid')})
    manager=SessionManager(window);before=window.profile_path.read_bytes()
    QTimer.singleShot(20,lambda:app.activeModalWidget().reject())
    assert not manager.commit({'甲':dict(host='cancelled.invalid')})
    assert window.profile_path.read_bytes()==before
    def concurrent():
        window.commit_profiles({'甲':dict(host='another-save.invalid')})
        app.activeModalWidget().accept()
    QTimer.singleShot(20,concurrent)
    assert not manager.commit({'甲':dict(host='stale-preview.invalid')})
    assert profiles.load(window.profile_path)['甲']['host']=='another-save.invalid'
    manager.close()


async def test_import_uses_actual_mapping_row_selection_and_commit_preview(desktop,tmp_path,monkeypatch):
    app,window=desktop();source=tmp_path/'sessions.csv'
    source.write_text('Name,Host,Port,Password\n实验室/甲,one.invalid,2222,fixture-sensitive\n实验室/乙,two.invalid,22,other-secret\n',encoding='utf-8')
    monkeypatch.setattr('harbor_terminal.session_manager.QFileDialog.getOpenFileName',lambda *args:(str(source),''))
    manager=SessionManager(window);seen=[]
    def advance():
        modal=app.activeModalWidget()
        if isinstance(modal,ImportDialog):
            modal.read_rows();seen.append(('rows',modal.rows.topLevelItemCount()))
            modal.rows.topLevelItem(1).setCheckState(0,Qt.CheckState.Unchecked)
            modal.accept();QTimer.singleShot(20,advance)
        elif isinstance(modal,ChangePreview):
            seen.append(('preview',modal.tree.topLevelItemCount()));modal.accept()
        elif modal:modal.reject()
    QTimer.singleShot(20,advance)
    manager.import_file()
    assert seen==[('rows',2),('preview',1)]
    assert set(window.profiles)=={'实验室/甲'} and window.profiles['实验室/甲']['port']=='2222'
    assert 'fixture-sensitive' not in window.profile_path.read_text() and not window.workers
    manager.close()


@pytest.mark.parametrize('encoding,kind,text',[
    ('gb18030','csv','Name,Host,Port\n实验室/控制台,example.invalid,22\n'),
    ('utf-16','tsv','Name\tHost\tPort\n实验室/控制台\texample.invalid\t22\n')])
async def test_import_dialog_reads_explicit_non_utf8_encodings(desktop,encoding,kind,text):
    app,window=desktop();dialog=ImportDialog(text.encode(encoding),kind,window)
    dialog.encoding.setCurrentText(encoding);dialog.read_rows()
    assert '实验室/控制台' in dialog.incoming
    dialog.close()


async def test_batch_editor_changes_only_checked_fields_and_frozen_selection(desktop):
    app,window=desktop();original={'甲':dict(host='one.invalid',port='22',username='original'),
        '乙':dict(host='two.invalid',port='2200',username='other')}
    assert window.commit_profiles(original)
    editor=BatchEditor(window.profiles,('甲',),window.templates,window)
    editor.editor.inputs['port'].setText('2222');editor.editor.checks['port'].setChecked(True)
    editor.editor.inputs['username'].setText('must-stay-unchecked');editor.accept()
    assert editor.result()==QDialog.DialogCode.Accepted
    assert editor.plan['甲']==dict(original['甲'],port='2222') and editor.plan['乙']==original['乙']
    assert window.profiles==original
    editor.close()


async def test_protocol_templates_do_not_rewrite_existing_sessions_and_detect_conflicts(desktop):
    app,one=desktop();_,two=desktop(one.profile_path)
    assert one.commit_profiles({'old-serial':dict(mode='Serial',host='COM3',port='115200')})
    before=one.profile_path.read_bytes();first=TemplateDialog(one);stale=TemplateDialog(two)
    first.editors['SSH'].inputs['port'].setText('2222')
    first.editors['Serial'].inputs['port'].setText('57600');first.accept()
    assert first.result()==QDialog.DialogCode.Accepted and one.profile_path.read_bytes()==before
    stale.accept();assert stale.result()!=QDialog.DialogCode.Accepted and '另一个窗口' in stale.status.text()
    one.new_session();assert one.port.text()=='2222';one.quick_dialog.reject()
    one.mode.setCurrentText('Serial');assert one.port.text()=='57600'
    one.load_profile('old-serial');assert one.port.text()=='115200'
    assert one.profile_path.read_bytes()==before
    first.close();stale.close()


async def test_recovery_previews_exact_backup_and_preserves_damaged_original(desktop):
    app,window=desktop();assert window.commit_profiles({'first':dict(host='first.invalid')})
    assert window.commit_profiles({'second':dict(host='second.invalid')})
    window.profile_path.write_text('{damaged-external-file')
    manager=SessionManager(window)
    QTimer.singleShot(20,lambda:app.activeModalWidget().accept());manager.restore()
    assert window.profiles=={'first':dict(host='first.invalid')}
    assert next(window.profile_path.parent.glob('sessions.json.damaged-*')).read_text()=='{damaged-external-file'
    manager.close()


async def test_clone_is_independent_and_requires_fresh_credentials_and_lock_guards_input(sftp_endpoint,desktop):
    app,window=desktop();window.host.setText('127.0.0.1');window.port.setText(str(sftp_endpoint.port))
    window.user.setText('tester');window.password.setText('test-only');window.known.setText(str(sftp_endpoint.known))
    window.connect_session();first=window.tabs.currentWidget();worker=first.worker
    await until(app,lambda:worker.status=='Connected')
    captured=deepcopy(first.connection_profile)
    assert 'password' not in captured and 'passphrase' not in captured
    window.clone_session();assert not window.password.text() and len(window.workers)==1
    window.password.setText('test-only');window.connect_session();second=window.tabs.currentWidget()
    await until(app,lambda:second.worker.status=='Connected')
    assert second.worker is not worker and first.connection_profile==captured
    window.rebuild_active_sessions()
    for index in range(window.active_tree.topLevelItemCount()):
        item=window.active_tree.topLevelItem(index)
        item.setSelected(item.data(0,Qt.ItemDataRole.UserRole)==second.worker.session_id)
    window.rebuild_active_sessions()
    assert len(window.active_tree.selectedItems())==1
    QTimer.singleShot(20,lambda:app.activeModalWidget().accept());window.active_sessions_action('lock')
    assert second.worker.input_locked and not worker.input_locked
    window.active_filter.setText('no matching session');assert window.active_tree.topLevelItemCount()==0
    window.active_filter.clear();assert window.active_tree.topLevelItemCount()==2
    identifier=worker.submit_flow([dict(action='delay',seconds=.1),dict(action='send',text='owned-flow#',newline=False),dict(action='wait',patterns=['#'],timeout=3)])
    assert identifier;worker.set_input_locked(True)
    first.model.feed(b'\x1b[6n')
    assert not worker.stop_event.is_set()
    assert not worker.send(b'blocked-manual') and not worker.send_break()
    assert worker.submit_flow([dict(action='send',text='blocked-flow')]) is None
    await until(app,lambda:worker.flow_progress().get('phase')=='success')
    await until(app,lambda:'owned-flow#' in first.toPlainText())
    import re
    assert re.search(rb'\x1b\[[0-9]+;[0-9]+R',sftp_endpoint.controls.received)
    window.close_tab(window.tabs.indexOf(second))
    await until(app,lambda:second.worker not in window.sessions)
    assert worker.status=='Connected'
    worker.set_input_locked(False);assert worker.send(b'unlocked#')
    await until(app,lambda:'unlocked#' in first.toPlainText())
