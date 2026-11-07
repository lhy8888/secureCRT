import asyncio,os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import asyncssh
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from harbor_terminal.app import Window


async def test_real_ssh_widget_interaction_resize_and_window_close(tmp_path):
    app=QApplication.instance() or QApplication([])
    processes=[];received=bytearray()
    class Server(asyncssh.SSHServer):
        def begin_auth(self,username):return True
        def password_auth_supported(self):return True
        def validate_password(self,username,password):return username=='tester' and password=='test-only'
    async def shell(process):
        processes.append(process)
        process.stdout.write(b'\x1b[32mready#\x1b[0m ')
        while True:
            try:data=await process.stdin.read(1)
            except asyncssh.TerminalSizeChanged:continue
            if not data:break
            received.extend(data);process.stdout.write(data)
    key=asyncssh.generate_private_key('ssh-ed25519')
    server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],
        process_factory=shell,encoding=None,line_editor=False)
    port=server.get_port();known=tmp_path/'hosts'
    known.write_bytes(f'[127.0.0.1]:{port} '.encode()+key.export_public_key())
    window=Window(profile_path=tmp_path/'sessions.json');window.show()
    window.host.setText('127.0.0.1');window.port.setText(str(port));window.user.setText('tester')
    window.password.setText('test-only');window.known.setText(str(known));window.connect_session()
    terminal=window.tabs.currentWidget();worker=terminal.worker
    async def until(predicate):
        async with asyncio.timeout(5):
            while not predicate():app.processEvents();await asyncio.sleep(.01)
    try:
        await until(lambda:'ready#' in terminal.toPlainText())
        assert worker.status=='Connected'
        assert terminal.screen.buffer[0][0].fg=='green'
        QTest.keyClick(terminal,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
        await until(lambda:b'\x03' in received)
        old_size=(terminal.screen.columns,terminal.screen.lines)
        window.resize(1000,720);app.processEvents()
        expected=(terminal.viewport().width()//terminal.cell_width,
                  terminal.viewport().height()//terminal.cell_height)
        assert expected!=old_size
        await until(lambda:(terminal.screen.columns,terminal.screen.lines)==expected
                    and processes[0].term_size[:2]==expected)
        assert terminal.screen.columns>8 and terminal.screen.lines>2
        window.close()
        await until(lambda:not worker.isRunning())
        await until(lambda:not window.isVisible())
    finally:
        worker.stop_event.set()
        await until(lambda:not worker.isRunning())
        window.close();server.close();await server.wait_closed()
