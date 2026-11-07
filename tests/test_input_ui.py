import asyncio
import json

import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QKeyEvent,QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QPlainTextEdit,QMessageBox

from harbor_terminal.app import Window
from harbor_terminal.desktop import ConnectionOptions
from harbor_terminal.input_dialogs import TextFilesDialog,SerialLinesDialog
from harbor_terminal.terminal import Terminal
from harbor_terminal.terminal_model import TerminalModel
from harbor_terminal.session import Worker
from harbor_terminal import profiles
from harbor_terminal.profile_operations import export_sessions,parse_import


@pytest.fixture
def desktop(tmp_path):
    app=QApplication.instance() or QApplication([]);window=Window(profile_path=tmp_path/'sessions.json');window.show();app.processEvents()
    yield app,window
    window.close();window.deleteLater();app.processEvents()


def test_input_settings_and_v5_migration_preserve_new_per_session_values(desktop,tmp_path):
    app,window=desktop;path=tmp_path/'profiles.json';old={'SSH':dict(mode='SSH',host='example.invalid',port='22',ssh_strict_kex='require')}
    path.write_text(json.dumps(dict(version=5,sessions=old)))
    assert profiles.load(path)==old
    dialog=ConnectionOptions(window.options,window);dialog.input_policy.fields['send_char_delay_ms'].setText('1001');dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.categories.currentRow()==5
    dialog.input_policy.fields['send_char_delay_ms'].setText('25');dialog.input_policy.fields['paste_newline'].setCurrentIndex(4)
    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted
    old['SSH'].update(dialog.values());profiles.save(path,old)
    assert json.loads(path.read_text())['version']==6 and parse_import(export_sessions(profiles.load(path),'xml').decode(),'xml').sessions==old
    assert profiles.load(path)['SSH']['send_char_delay_ms']=='25'
    dialog.deleteLater()


@pytest.mark.parametrize('mode,expected',[('escape',b'\x1bx'),('text',b'x')])
def test_alt_meta_altgr_and_ime_are_distinct(desktop,mode,expected):
    app,window=desktop;worker=Worker('Serial',{});worker._set_state('Connected');terminal=Terminal(worker,input_policy={'alt_meta':mode});terminal.show();app.processEvents()
    try:
        event=QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_X,Qt.KeyboardModifier.AltModifier,'x');QApplication.sendEvent(terminal,event)
        assert bytes(worker.outgoing)==expected;worker.outgoing.clear()
        event=QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_At,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.AltModifier,'@');QApplication.sendEvent(terminal,event)
        event=QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_At,Qt.KeyboardModifier.GroupSwitchModifier,'€');QApplication.sendEvent(terminal,event)
        commit=QInputMethodEvent();commit.setCommitString('你好');QApplication.sendEvent(terminal,commit)
        assert bytes(worker.outgoing)=='@€你好'.encode()
    finally:terminal.close();terminal.deleteLater()


def test_paste_preview_preserves_unedited_crlf_and_quotes_paths_without_local_execution(desktop,monkeypatch):
    app,window=desktop;worker=Worker('Serial',{});worker._set_state('Connected')
    terminal=Terminal(worker,input_policy=dict(paste_newline='keep',paste_quote='powershell'));terminal.show();seen=[]
    def approve():
        modal=app.activeModalWidget();editors=modal.findChildren(QPlainTextEdit)
        preview=next(edit for edit in editors if edit.isReadOnly()).toPlainText()
        seen.append('␍␊' in preview and "a''b" in preview);modal.accept()
    QTimer.singleShot(20,approve);terminal.paste_confirmed("a'b\r\nnext")
    assert seen==[True] and bytes(worker.outgoing)==b"'a''b\r\nnext'";worker.outgoing.clear()
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args:('C:/space and quote/a\'b.ps1',''))
    QTimer.singleShot(20,lambda:app.activeModalWidget().reject());terminal.paste_path()
    assert not worker.outgoing
    terminal.close();terminal.deleteLater()


@pytest.mark.parametrize('policy',['allow','preserve'])
def test_remote_history_clear_and_reset_are_separate_from_local_clear(policy):
    model=TerminalModel(columns=20,lines=3,clear_history=policy)
    model.feed(b'old-history\r\nsecond\r\nthird\r\nfourth\r\nfifth')
    original=model.history;assert original
    model.feed(b'\x1b[2J');assert model.history==original
    model.feed(b'\x1b[3J')
    assert bool(model.history)==(policy=='preserve')
    model.feed(b'new\r\none\r\ntwo\r\nthree');before=model.history;assert before
    model.feed(b'\x1bc')
    assert model.history==before if policy=='preserve' else not model.history
    model.screen.clear_local(True);assert not model.history


def test_text_preview_is_frozen_across_file_change_and_bound_to_original_worker(desktop,tmp_path):
    app,window=desktop;worker=Worker('SSH',{});worker._set_state('Connected');other=Worker('SSH',{});other._set_state('Connected')
    dialog=TextFilesDialog(worker,'first','utf-8',window);source=tmp_path/'source.txt';source.write_text('first\nsecond',encoding='utf-8')
    dialog.path.setText(str(source));dialog.load();assert dialog.payload==b'first\rsecond'
    source.write_text('changed-must-not-send',encoding='utf-8');dialog.send()
    assert dialog.pending and worker._flow_job['payload']==b'first\rsecond' and other._flow_job is None
    dialog.close();assert worker._flow_job['cancel'].is_set() and not worker.outgoing;dialog.deleteLater()


def test_serial_output_confirmation_cancels_on_return_and_flow_control_disables_managed_pin(desktop):
    app,window=desktop;worker=Worker('Serial',{});worker._set_state('Connected')
    worker._serial_snapshot=dict(dtr=True,rts=True,cts=None,flow_control='none')
    dialog=SerialLinesDialog(worker,'fixture',window);seen=[]
    def cancel():
        modal=app.activeModalWidget();seen.append(isinstance(modal,QMessageBox));QTest.keyClick(modal,Qt.Key.Key_Return)
        seen.append(not modal.isVisible())
        if modal.isVisible():modal.reject()
    QTimer.singleShot(20,cancel);dialog.change()
    assert seen==[True,True] and not worker._controls
    worker._serial_snapshot['flow_control']='dsrdtr';dialog.poll();assert not dialog.apply.isEnabled()
    assert dialog.tree.topLevelItem(2).text(1)=='不支持 / 未知'
    dialog.close();dialog.deleteLater()
