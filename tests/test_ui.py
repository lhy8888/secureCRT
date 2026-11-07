import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from harbor_terminal.app import Window, Worker, Terminal


def test_window_and_terminal_escape_handling():
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.show()
    app.processEvents()
    worker = Worker('Serial', {})
    worker._set_state('Connected')
    terminal = Terminal(worker)
    # Fragmented UTF-8 and ANSI clear/redraw, with a malicious OSC clipboard sequence.
    data = '你好'.encode()
    worker.incoming.extend(data[:2]); terminal.refresh()
    worker.incoming.extend(data[2:] + b'\x1b[2J\x1b[Hrouter#\x1b]52;c;YXR0YWNr\x07')
    terminal.refresh()
    assert terminal.toPlainText().startswith('router#')
    assert QApplication.clipboard().text() != 'attack'
    assert worker.send(b'a' * 65536)
    assert not worker.send(b'b')
    assert len(worker.outgoing) == 65536
    window.close()
    terminal.close()


def test_serial_worker_reaches_terminal_and_stops():
    import time
    import pytest
    if os.name == 'nt':
        pytest.skip('Requires Unix PTY; Windows needs COM hardware validation')
    import pty
    app = QApplication.instance() or QApplication([])
    master, slave = pty.openpty()
    worker = Worker('Serial', {'device': os.ttyname(slave), 'baudrate': 115200})
    terminal = Terminal(worker)
    states = []
    worker.state.connect(states.append)
    try:
        worker.start()
        deadline = time.monotonic() + 3
        while 'Connected' not in states and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        assert 'Connected' in states
        os.write(master, b'router-ready#')
        while 'router-ready#' not in terminal.toPlainText() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        assert 'router-ready#' in terminal.toPlainText()
    finally:
        worker.stop_event.set()
        assert worker.wait(5000)
        app.processEvents()
        terminal.close()
        os.close(master); os.close(slave)
    assert 'Disconnected' in states


def test_paste_guards_do_not_send_control_or_unconfirmed_commands(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    app = QApplication.instance() or QApplication([])
    worker = Worker('Serial', {})
    worker._set_state('Connected')
    terminal = Terminal(worker)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    monkeypatch.setattr(terminal, 'confirm_multiline', lambda text: None)
    QApplication.clipboard().setText('safe\x1b[31m')
    terminal.paste_confirmed()
    assert not worker.outgoing
    QApplication.clipboard().setText('command1\ncommand2\n')
    terminal.paste_confirmed()
    assert not worker.outgoing
    QApplication.clipboard().setText('show version')
    terminal.paste_confirmed()
    assert worker.outgoing == b'show version'
    QApplication.clipboard().clear()
    terminal.close()


def test_unexpected_parser_failure_disconnects_session(monkeypatch):
    app = QApplication.instance() or QApplication([])
    worker = Worker('Serial', {})
    terminal = Terminal(worker)
    def fail(_):
        raise ValueError('synthetic parser failure')
    monkeypatch.setattr(terminal.stream, 'feed', fail)
    worker.incoming.extend(b'hostile')
    terminal.refresh()
    assert worker.stop_event.is_set()
    assert not terminal.timer.isActive()
    assert 'hostile' not in terminal.toPlainText()
    terminal.close()
