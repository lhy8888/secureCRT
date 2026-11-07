"""Capture live Qt tools against disposable loopback SSH/SFTP and Unix PTY.

All keys, credentials, files and output are generated test fixtures. This is
Linux/offscreen evidence, not Windows, physical COM or SecureCRT comparison.
"""
import argparse
import asyncio
import os
import json
from pathlib import Path
import sys
import tempfile
from importlib.metadata import version

import asyncssh
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from harbor_terminal.app import Window, ConnectionOptions


async def until(app, predicate, seconds=10):
    async with asyncio.timeout(seconds):
        while not predicate():
            app.processEvents()
            await asyncio.sleep(.01)
    app.processEvents()


async def capture(output):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='harbor-services-') as directory:
        temporary = Path(directory)
        root = temporary / 'remote'
        root.mkdir()
        (root / 'configs').mkdir()
        (root / 'README-test.txt').write_text('Generated local test data. No real devices.\n')
        (root / '中文路径.txt').write_text('本地 SSH/SFTP 验证数据\n', encoding='utf-8')
        source = temporary / 'payload.bin'
        source.write_bytes(bytes(range(256)) * 1024)

        async def echo(reader, writer):
            try:
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        echo_server = await asyncio.start_server(echo, '127.0.0.1', 0)
        echo_port = echo_server.sockets[0].getsockname()[1]

        class Target(asyncssh.SSHServer):
            def begin_auth(self, username): return True
            def password_auth_supported(self): return True
            def validate_password(self, username, password):
                return username == 'test-user' and password == 'local-test-only'
            def connection_requested(self, host, port, *_):
                return host == '127.0.0.1' and port == echo_port
            def server_requested(self, host, port): return host == '127.0.0.1'

        async def shell(process):
            process.stdout.write((
                '\x1b[2J\x1b[HLOCAL SSH LAB / generated test data / 非真实设备\r\n'
                'Connected through a local SSH jump host.\r\n\r\n'
                'lab-core-01# show interfaces status\r\n'
                'Port       Name                  Status        Vlan    Duplex  Speed\r\n'
                'Gi1/0/1    uplink-to-edge         \x1b[32mconnected\x1b[0m     trunk   full    1000\r\n'
                'Gi1/0/2    access-02              \x1b[32mconnected\x1b[0m     10      full    1000\r\n'
                'Gi1/0/3    access-03              \x1b[32mconnected\x1b[0m     20      full    1000\r\n'
                'Gi1/0/4    spare                  \x1b[33mnotconnect\x1b[0m    1       auto    auto\r\n'
                'Gi1/0/5    management            \x1b[32mconnected\x1b[0m     99      full    1000\r\n\r\n'
                'lab-core-01# show ip route summary\r\n'
                'Route Source    Networks    Subnets    Memory (bytes)\r\n'
                'connected       4           0          416\r\n'
                'static          1           0          104\r\n'
                'Total           5           0          520\r\n\r\n'
                'lab-core-01# show system\r\n'
                'Session         SSH2 / local test fixture\r\n'
                'Host keys       Jump and target independently verified\r\n'
                'Terminal        UTF-8 / xterm-256color\r\n'
                'Description     本地回归实验室 · 核心交换机示例\r\n\r\n'
                'lab-core-01# '
            ).encode())
            while True:
                try:
                    data = await process.stdin.read(4096)
                except asyncssh.TerminalSizeChanged:
                    continue
                if not data:
                    break
                process.stdout.write(data)

        async def server(factory, name, **options):
            key = asyncssh.generate_private_key('ssh-ed25519')
            listener = await asyncssh.create_server(factory, '127.0.0.1', 0,
                server_host_keys=[key], **options)
            known = temporary / (name + '_known_hosts')
            known.write_bytes(f'[127.0.0.1]:{listener.get_port()} '.encode() + key.export_public_key())
            return listener, known

        target, target_known = await server(Target, 'target', process_factory=shell,
            encoding=None, line_editor=False,
            sftp_factory=lambda channel: asyncssh.SFTPServer(channel, chroot=os.fsencode(root)))

        class Jump(asyncssh.SSHServer):
            def begin_auth(self, username): return True
            def password_auth_supported(self): return True
            def validate_password(self, username, password):
                return username == 'jump-user' and password == 'jump-test-only'
            def connection_requested(self, host, port, *_):
                return host == '127.0.0.1' and port == target.get_port()

        jump, jump_known = await server(Jump, 'jump')
        window = Window(profile_path=temporary / 'sessions.json')
        descriptors = []

        def save(widget, name):
            path = output / ('harbor-' + version('harbor-terminal') + '-' + name + '.png')
            if not widget.grab().save(str(path)):
                raise RuntimeError('Screenshot save failed')
            print(path)

        try:
            window.profiles = {
                '本地实验室/SSH 跳板': dict(mode='SSH', host='127.0.0.1',
                    port=str(jump.get_port()), username='jump-user', known_hosts=str(jump_known)),
                '本地实验室/核心交换机': dict(mode='SSH', host='127.0.0.1',
                    port=str(target.get_port()), username='test-user', known_hosts=str(target_known),
                    jump_profile='本地实验室/SSH 跳板'),
                '本地实验室/边缘路由器': dict(mode='SSH', host='127.0.0.1',
                    port=str(target.get_port()), username='test-user', known_hosts=str(target_known))}
            window.update_profiles()
            window.show()
            window.load_profile('本地实验室/核心交换机')
            window.password.setText('local-test-only')
            window.jump_password = 'jump-test-only'
            window.connect_session()
            terminal = window.tabs.currentWidget()
            worker = terminal.worker
            await until(app, lambda: worker.status == 'Connected' and 'lab-core-01#' in terminal.toPlainText())
            await until(app, lambda: not terminal.resize_timer.isActive())
            window.session_state(worker, 'Connected')

            window.open_sftp()
            files = window.service_panels[(worker, 'sftp')]
            await until(app, lambda: files.pending is None)
            files.submit('upload', remote_path='/verified-payload.bin', local_path=str(source))
            await until(app, lambda: files.pending is None and 'SHA-256' in files.result_text.text())
            assert (root / 'verified-payload.bin').read_bytes() == source.read_bytes()
            save(files, 'sftp')
            files.close()

            window.open_forwards()
            tunnels = window.service_panels[(worker, 'forward')]
            tunnels.port.setValue(echo_port)
            for index in range(3):
                tunnels.kind.setCurrentIndex(index)
                tunnels.start_button.click()
                await until(app, lambda: tunnels.pending is None and len(worker.forwards()) == index + 1)
            entry = next(item for item in worker.forwards() if item['kind'] == 'local')
            reader, writer = await asyncio.open_connection('127.0.0.1', entry['listen_port'])
            writer.write(b'capture-verification')
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(20), 3) == b'capture-verification'
            writer.close()
            await writer.wait_closed()
            tunnels.refresh()
            for column in range(4): tunnels.tree.resizeColumnToContents(column)
            save(tunnels, 'tunnels')
            tunnels.close()

            window.open_log()
            log = window.service_panels[(worker, 'log')]
            log.path.setText(str(temporary / 'generated-test-log.jsonl'))
            log.start_button.click()
            await until(app, lambda: worker.journal.snapshot()['state'] == 'running')
            worker.send(b'capture: generated test data\r\n')
            await until(app, lambda: worker.journal.snapshot()['written'] > 0)
            log.poll()
            save(log, 'log')
            log.close()
            await until(app, lambda: not worker.journal.snapshot()['alive'])
            await until(app, lambda: 'capture: generated test data' in terminal.toPlainText())
            window.update_activity()
            window.load_profile('本地实验室/边缘路由器')
            window.password.setText('local-test-only'); window.connect_session()
            second = window.tabs.currentWidget()
            await until(app, lambda: second.worker.status == 'Connected' and 'lab-core-01#' in second.toPlainText())

            if os.name != 'nt':
                import pty
                master, slave = pty.openpty()
                descriptors.extend((master, slave))
                window.mode.setCurrentText('Serial')
                window.host.setText(os.ttyname(slave))
                window.connect_session()
                serial = window.tabs.currentWidget().worker
                window.tabs.currentWidget().session_label = '串口控制台'
                await until(app, lambda: serial.status == 'Connected')
                panel = window.service_panel('hex')
                panel.setWindowTitle('LOCAL PTY TEST / 原始字节 / 非实体COM')
                panel.tx.setChecked(True)
                os.write(master, b'LOCAL PTY TEST\r\n\x00\xff\x1b[31m\x7f\x80')
                await until(app, lambda: 'RX' in panel.view.toPlainText())
                panel.input.setText('00 FF 1B 0D 0A')
                panel.send_button.click()
                received = await asyncio.wait_for(asyncio.to_thread(os.read, master, 5), 3)
                assert received == b'\x00\xff\x1b\r\n'
                await until(app, lambda: 'TX' in panel.view.toPlainText())
                save(panel, 'hex')
                panel.close()
                window.session_state(serial, 'Connected')
                window.profiles['本地实验室/串口控制台'] = dict(mode='Serial', host=os.ttyname(slave), port='115200')
            window.update_profiles(); window.tabs.setCurrentWidget(terminal)
            window.session_state(worker, 'Connected'); window.update_activity()
            await until(app, lambda: not terminal.resize_timer.isActive())
            save(window, 'terminal')
            window.set_desktop_theme('dark'); app.processEvents(); save(window, 'terminal-dark')
            window.set_desktop_theme('light'); app.processEvents()
            window.load_profile('本地实验室/核心交换机'); window.show_quick_connect()
            app.processEvents(); save(window.quick_dialog, 'quick-connect'); window.quick_dialog.reject()
            settings = ConnectionOptions(window.options, window, profiles=window.profiles)
            settings.show(); app.processEvents(); save(settings, 'options')
            settings.categories.setCurrentRow(4);app.processEvents();save(settings,'ssh-policy')
            settings.categories.setCurrentRow(5);app.processEvents();save(settings,'input-policy')
            settings.close(); settings.deleteLater()
            from harbor_terminal.key_dialogs import HostKeysDialog,TrustReview
            keys=HostKeysDialog(window);keys.show();app.processEvents();save(keys,'host-keys')
            review=TrustReview(keys.snapshot.value,keys);review.show();app.processEvents();save(review,'host-trust-review')
            assert not review.ok.isEnabled();review.reject();review.deleteLater();keys.close();keys.deleteLater()
            window.open_key_tools();identity=window.key_dialog
            identity.path.setText(str(temporary/'generated-identity'));identity.password.setText('generated-fixture-only');identity.start(False)
            await until(app,lambda:identity.last_result is not None and not identity.job.isRunning(),seconds=15)
            assert not identity.password.text() and 'PRIVATE KEY' not in identity.output.toPlainText()
            save(identity,'identity-tool');identity.close()
            window.open_diagnostics();diagnostic=window.service_panels[(worker,'diagnostics')]
            await until(app,lambda:worker.ssh_diagnostics().get('strict_kex') is True)
            diagnostic.refresh();app.processEvents();save(diagnostic,'ssh-diagnostics');diagnostic.close()
            window.open_text_files();text_files=window.service_panels[(worker,'text')]
            text_source=temporary/'text-source.txt';text_source.write_text('capture: text-file-first\ncapture: text-file-second\n',encoding='utf-8')
            text_files.path.setText(str(text_source));text_files.load();app.processEvents();save(text_files,'text-send')
            capture_path=temporary/'received-plain.txt';text_files.receive_path.setText(str(capture_path));text_files.start_capture()
            await until(app,lambda:worker.text_capture.snapshot()['state']=='running')
            text_files.send();await until(app,lambda:text_files.pending is None)
            await until(app,lambda:'text-file-second' in worker.receive_stream.text)
            worker.stop_text_capture();await until(app,lambda:not worker.text_capture.snapshot()['alive'])
            assert 'text-file-second' in capture_path.read_text()
            text_files.tabs.setCurrentIndex(1);text_files.poll();app.processEvents();save(text_files,'text-receive');text_files.close()
            if os.name!='nt':
                from harbor_terminal.input_dialogs import SerialLinesDialog
                serial_lines=SerialLinesDialog(serial,'LOCAL PTY / 非实体COM',window)
                serial_lines.show();app.processEvents();save(serial_lines,'serial-lines');serial_lines.close();serial_lines.deleteLater()
            window.open_command_panel();panel=window.command_panel
            panel.persist_library({'生成测试命令':dict(text='capture-command',pinned=True)})
            panel.edit.setPlainText('capture-command')
            panel.flow_edit.setPlainText(json.dumps(dict(version=1,steps=[
                dict(action='send',text='capture-flow'),
                dict(action='wait',patterns=['capture-flow'],timeout=5)]),ensure_ascii=False,indent=2))
            panel.tabs.setCurrentIndex(1)
            def confirm_fixture():
                modal=app.activeModalWidget()
                if modal:modal.accept()
            QTimer.singleShot(50,confirm_fixture);panel.start_flows()
            await until(app,lambda:not panel.pending and '流程完成' in panel.results.toPlainText())
            assert worker.flow_progress()['phase']=='success'
            save(window,'workflow')
            from harbor_terminal.session_manager import SessionManager,BatchEditor,ChangePreview,ImportDialog,TemplateDialog
            if not window.commit_profiles(window.profiles):raise RuntimeError('Fixture profile commit failed')
            selected=('本地实验室/核心交换机','本地实验室/边缘路由器')
            manager=SessionManager(window,selected);manager.show();app.processEvents();save(manager,'session-manager')
            batch=BatchEditor(window.profiles,selected,window.templates,manager)
            batch.editor.inputs['port'].setText('2222');batch.editor.checks['port'].setChecked(True)
            batch.show();app.processEvents();save(batch,'batch-edit');batch.accept()
            preview=ChangePreview(window.profiles,batch.plan,manager);preview.show();app.processEvents();save(preview,'session-preview')
            imported=ImportDialog('Name,Host,Port,Password\n实验室/控制台,example.invalid,22,generated-fixture-only\n'.encode(),'csv',manager)
            imported.read_rows();imported.show();app.processEvents();save(imported,'session-import')
            template=TemplateDialog(window);template.show();app.processEvents();save(template,'defaults')
            for dialog in (template,imported,preview,batch,manager):dialog.close();dialog.deleteLater()
            app.processEvents()
        finally:
            for worker in window.workers: worker.stop_event.set()
            await until(app, lambda: all(not worker.isRunning() for worker in window.workers), seconds=15)
            window.close()
            app.processEvents()
            for descriptor in descriptors: os.close(descriptor)
            for listener in (jump, target, echo_server): listener.close()
            await asyncio.gather(*(listener.wait_closed() for listener in (jump, target, echo_server)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('artifacts'))
    asyncio.run(capture(parser.parse_args().out))
