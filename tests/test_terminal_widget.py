import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from harbor_terminal.app import Window
from harbor_terminal.session import Worker
from harbor_terminal.terminal import Terminal


def terminal():
    app=QApplication.instance() or QApplication([])
    worker=Worker('Serial',{});worker._set_state('Connected')
    view=Terminal(worker);view.resize(800,480);view.show();app.processEvents()
    return app,worker,view


def test_grid_paints_truecolor_background_and_resizes():
    app,worker,view=terminal()
    try:
        worker.incoming.extend(b'\x1b[48;2;20;60;90m \x1b[0m')
        view.refresh();app.processEvents()
        image=view.viewport().grab().toImage()
        color=image.pixelColor(int(view.cell_width//2),view.cell_height//2)
        assert (color.red(),color.green(),color.blue())==(20,60,90)
        QTest.qWait(130);app.processEvents()
        assert view.screen.columns==view.viewport().width()//view.cell_width
        assert worker._size==(view.screen.columns,view.screen.lines)
    finally: view.close()


def test_ctrl_c_arrows_function_keys_and_ime_commit():
    app,worker,view=terminal()
    try:
        QTest.keyClick(view,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
        view.model.feed(b'\x1b[?1h')
        QTest.keyClick(view,Qt.Key.Key_Up)
        QTest.keyClick(view,Qt.Key.Key_F5)
        preedit=QInputMethodEvent('拼',[]);QApplication.sendEvent(view,preedit)
        assert worker.outgoing==b'\x03\x1bOA\x1b[15~'
        commit=QInputMethodEvent();commit.setCommitString('你好')
        QApplication.sendEvent(view,commit)
        assert worker.outgoing==b'\x03\x1bOA\x1b[15~'+'你好'.encode()
        assert view.preedit==''
    finally:view.close()


def test_wide_character_copy_and_literal_search_do_not_rewrite_output():
    app,worker,view=terminal()
    try:
        worker.incoming.extend('你好 router#\r\nsecond router#'.encode());view.refresh()
        before=view.toPlainText()
        view.selection=((0,1),(0,2))
        assert view.selected_text()=='你'
        assert view.find('router#') and view._last_match[0]==0
        assert view.find('router#') and view._last_match[0]==1
        assert view.find('router#',backwards=True) and view._last_match[0]==0
        assert view.toPlainText()==before
    finally:view.close()


def test_saved_session_tree_filters_nested_profiles(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=Window(profile_path=tmp_path/'sessions.json')
    window.profiles={'lab/switch':{'host':'192.0.2.1','mode':'SSH','port':'22'},
                     'other':{'host':'example.invalid','mode':'SSH','port':'22'}}
    window.update_profiles()
    assert window.tree.topLevelItemCount()==2
    window.session_filter.setText('192.0.2')
    assert window.tree.topLevelItemCount()==1
    assert window.tree.topLevelItem(0).text(0)=='lab'
    assert window.tree.topLevelItem(0).child(0).text(0)=='switch'
    window.close()


def test_window_close_cancels_connect_and_finishes_without_second_click(tmp_path,monkeypatch):
    import asyncio,time
    import harbor_terminal.app as shell
    class Stalled:
        async def connect(self,**options):await asyncio.Event().wait()
        async def close(self):pass
    actual=Worker
    monkeypatch.setattr(shell,'Worker',lambda mode,options,**kwargs:actual(mode,options,transport_factory=Stalled,**kwargs))
    app=QApplication.instance() or QApplication([])
    window=Window(profile_path=tmp_path/'sessions.json');window.show()
    window.host.setText('example.invalid');window.user.setText('test-only')
    window.connect_session();worker=window.workers[0]
    deadline=time.monotonic()+2
    try:
        while worker.status!='Connecting' and time.monotonic()<deadline:
            app.processEvents();QTest.qWait(10)
        assert worker.status=='Connecting'
        window.close()
        while window.isVisible() and time.monotonic()<deadline:
            app.processEvents();QTest.qWait(10)
        assert not window.isVisible()
        assert not worker.isRunning()
    finally:
        worker.stop_event.set();worker.wait(2000);window.close()


def test_edited_paste_is_revalidated_and_remote_bracket_mode_is_honored(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    app,worker,view=terminal()
    try:
        view.model.feed(b'\x1b[?2004h')
        QApplication.clipboard().setText('first\nsecond')
        monkeypatch.setattr(view,'confirm_multiline',lambda text:'edited\ncommands')
        view.paste_confirmed()
        assert worker.outgoing==b'\x1b[200~edited\ncommands\x1b[201~'
        worker.outgoing.clear()
        monkeypatch.setattr(view,'confirm_multiline',lambda text:'edited\x1b[201~')
        monkeypatch.setattr(QMessageBox,'warning',lambda *args:QMessageBox.StandardButton.Ok)
        view.paste_confirmed()
        assert not worker.outgoing
    finally:QApplication.clipboard().clear();view.close()
