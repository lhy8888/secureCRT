"""Exercise the new connection path and display changes with real Qt/SSH."""
import asyncio

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetricsF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFontDialog
import pytest

from harbor_terminal.app import Window
from harbor_terminal.appearance import Preferences, terminal_font


async def until(app, predicate):
    async with asyncio.timeout(6):
        while not predicate():
            app.processEvents(); await asyncio.sleep(.01)


async def test_quick_connect_dialog_reaches_ssh_and_preserves_control_keys(sftp_endpoint, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window(profile_path=tmp_path/'sessions.json'); window.show()
    try:
        window.quick_action.trigger(); app.processEvents()
        assert window.quick_dialog.isVisible()
        window.connect_button.click()
        assert not window.workers and window.quick_dialog.error.text()
        window.host.setText('127.0.0.1'); window.port.setText(str(sftp_endpoint.port))
        window.user.setText('tester'); window.password.setText('test-only')
        window.known.setText(str(sftp_endpoint.known))
        window.connect_button.click()
        terminal = window.tabs.currentWidget(); worker = terminal.worker
        await until(app, lambda: worker.status == 'Connected')
        assert not window.quick_dialog.isVisible() and not window.password.text()
        assert sftp_endpoint.controls.authentications == 1
        worker.trace.configure(True, True)
        terminal.setFocus(); app.processEvents()
        for key in (Qt.Key.Key_C, Qt.Key.Key_D, Qt.Key.Key_S):
            QTest.keyClick(terminal, key, Qt.KeyboardModifier.ControlModifier)
        await until(app, lambda: b'\x03\x04\x13' in b''.join(
            record['data'] for record in worker.trace.snapshot()['records'] if record['direction'] == 'RX'))
        assert worker.status == 'Connected'  # Ctrl+D must not disconnect locally.
        QApplication.clipboard().setText('local-input-must-not-reach-ssh')
        window.quick_host.setFocus(); app.processEvents()
        QTest.keyClick(window.quick_host, Qt.Key.Key_V,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        for _ in range(6):
            app.processEvents(); await asyncio.sleep(.01)
        sent = b''.join(record['data'] for record in worker.trace.snapshot()['records'] if record['direction'] == 'TX')
        assert b'local-input-must-not-reach-ssh' not in sent
        window.find_action.trigger(); app.processEvents()
        assert window.find_bar.isVisible() and window.search.hasFocus()
        window.hide_find_bar(); app.processEvents()
        assert not window.find_bar.isVisible() and terminal.hasFocus()
    finally:
        for worker in window.workers: worker.stop_event.set()
        await until(app, lambda: all(not worker.isRunning() for worker in window.workers))
        QApplication.clipboard().clear()
        window.close(); app.processEvents()


def test_cancelling_quick_connect_clears_all_ephemeral_credentials(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window(profile_path=tmp_path/'sessions.json'); window.show()
    window.show_quick_connect()
    window.password.setText('test-only')
    window.passphrase = window.jump_password = window.jump_passphrase = 'test-only'
    window.quick_dialog.reject(); app.processEvents()
    assert not window.password.text()
    assert window.passphrase is window.jump_password is window.jump_passphrase is None
    assert not window.workers
    assert not window.profile_path.exists()
    window.close(); app.processEvents()


async def test_font_and_color_changes_preserve_screen_and_resize_real_ssh(sftp_endpoint, tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path/'sessions.json'
    window = Window(profile_path=path); window.show()
    window.host.setText('127.0.0.1'); window.port.setText(str(sftp_endpoint.port))
    window.user.setText('tester'); window.password.setText('test-only')
    window.known.setText(str(sftp_endpoint.known)); window.connect_session()
    terminal = window.tabs.currentWidget(); worker = terminal.worker
    try:
        await until(app, lambda: worker.status == 'Connected')
        assert worker.send('font-test 你好\r\n'.encode())
        await until(app, lambda: 'font-test 你好' in terminal.toPlainText() and not terminal.resize_timer.isActive())
        old_width = terminal.cell_width
        old_columns = terminal.screen.columns
        chosen = terminal_font(size=16)
        picked = []
        def select_font():
            modal = app.activeModalWidget()
            picked.append(isinstance(modal, QFontDialog))
            if isinstance(modal, QFontDialog):
                modal.setCurrentFont(chosen); QTimer.singleShot(50, modal.accept)
            elif modal: modal.reject()
        QTimer.singleShot(30, select_font)
        window.choose_terminal_font(); window.set_terminal_scheme('paper')
        assert picked == [True]
        assert window.preferences.size == 16, (window.preferences.family, window.preferences.size, chosen.toString())
        assert terminal.cell_width > old_width, (terminal.font().toString(), terminal.cell_width, old_width)
        await until(app, lambda: not terminal.resize_timer.isActive() and terminal.screen.columns < old_columns)
        assert terminal.cell_width > old_width
        assert terminal.cell_width == pytest.approx(QFontMetricsF(terminal.font()).horizontalAdvance('M'))
        assert 'font-test 你好' in terminal.toPlainText()
        assert worker._size == (terminal.screen.columns, terminal.screen.lines)
        image = terminal.viewport().grab().toImage()
        assert image.pixelColor(20, image.height()-3).name() == '#ffffff'
        settings = Preferences(path)
        assert settings.scheme == 'paper' and settings.size == 16
        assert settings.family == chosen.family()
        assert not path.exists()  # Display preferences never create a session/credential file.
        assert worker.status == 'Connected'
    finally:
        worker.stop_event.set(); await until(app, lambda: not worker.isRunning())
        window.close(); app.processEvents()


def test_font_dialog_cancel_preserves_display_preferences(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window(profile_path=tmp_path/'sessions.json'); window.show()
    original = (window.preferences.family, window.preferences.size, window.preferences.scheme)
    dismissed = []
    def cancel_font():
        modal = app.activeModalWidget()
        dismissed.append(isinstance(modal, QFontDialog))
        if modal: modal.reject()
    QTimer.singleShot(30, cancel_font)
    try:
        window.choose_terminal_font()
        assert dismissed == [True]
        assert (window.preferences.family, window.preferences.size, window.preferences.scheme) == original
        assert not (tmp_path/'appearance.ini').exists()
    finally:
        window.close(); app.processEvents()
