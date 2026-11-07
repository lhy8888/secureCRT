"""Harbor desktop shell. Terminal state and connection ownership live in modules."""
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QStandardPaths, Slot
from PySide6.QtWidgets import (QApplication, QMainWindow, QMessageBox,
    QInputDialog, QDialog, QFileDialog, QTreeWidgetItem)

from . import profiles
from .session import Worker, PortProbe
from .terminal import Terminal
from .terminal_model import ENCODINGS
from .serial_config import SerialSettings
from .panels import SFTPDialog, LogDialog, HexDialog, ForwardDialog
from .desktop import DesktopShell, ConnectionOptions
from .appearance import icon, terminal_font
from .auth_dialog import AuthenticationDialog
from . import session_templates
from .storage import StorageConflict, CommitUncertain, ANY_REVISION
from .ssh_policy import POLICY_FIELDS

DEFAULTS = session_templates.BASE_OPTIONS
STATES = dict(Connecting='连接中', ConnectingJump='连接跳板中', ConnectingTarget='连接目标中',
              AuthenticatingJump='跳板交互认证', AuthenticatingTarget='目标交互认证',
              Connected='已连接', Closing='关闭中', Disconnected='已断开')


class Window(QMainWindow, DesktopShell):
    def __init__(self, *, profile_path=None):
        super().__init__()
        self.setWindowTitle('Harbor Terminal')
        self.resize(1280, 800)
        self.workers = []
        self.sessions = {}
        self._closing_tabs = set()
        self._closing = False
        self._probe = None
        self.service_panels = {}
        self.auth_dialogs = {}
        self.key_dialog = None
        self.options = dict(DEFAULTS)
        self.passphrase = None
        self.jump_password = self.jump_passphrase = None
        self.profile_path = Path(profile_path) if profile_path else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)) / 'HarborTerminal' / 'sessions.json'
        self.profiles = {}
        self.profile_error = None
        self.profile_store = profiles.store(self.profile_path)
        self.profile_revision = None
        try:
            snapshot = self.profile_store.read()
            self.profiles, self.profile_revision = snapshot.value, snapshot.revision
        except (OSError, ValueError, TypeError) as exc:
            self.profile_error = type(exc).__name__
            try: self.profile_revision = self.profile_store.revision()
            except (OSError, ValueError): pass
        self.template_store = session_templates.store(self.profile_path)
        self.templates = {mode:{} for mode in session_templates.BUILTIN}
        self.template_revision = None; self.template_error = None
        try:
            snapshot = self.template_store.read()
            self.templates, self.template_revision = snapshot.value, snapshot.revision
        except (OSError, ValueError, TypeError) as exc:
            self.template_error = type(exc).__name__
        self.build_desktop()
        self.apply_protocol_defaults(self.mode.currentText())
        self.close_timer = QTimer(self); self.close_timer.timeout.connect(self.finish_close)
        self.service_timer = QTimer(self); self.service_timer.setInterval(200)
        self.service_timer.timeout.connect(self.update_activity); self.service_timer.start()
        if self.profile_error:
            self.status.setText('会话文件无法读取，已禁用保存以保护原文件：'+self.profile_error)

    def _build_manager(self):
        self._build_session_docks()

    def update_profiles(self, *_):
        self.saved.clear(); self.saved.addItem('选择已保存会话'); self.saved.addItems(sorted(self.profiles))
        self.tree.clear(); folders = {}
        query = self.session_filter.text().casefold()
        for name,profile in sorted(self.profiles.items()):
            if query and query not in (' '.join((name,profile.get('host',''),profile.get('username','')))).casefold():
                continue
            parts = name.split('/'); parent = None
            for i,part in enumerate(parts[:-1]):
                key = '/'.join(parts[:i+1])
                if key not in folders:
                    item = QTreeWidgetItem([part]); folders[key] = item
                    item.setIcon(0, icon('folder'))
                    (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))
                parent = folders[key]
            item = QTreeWidgetItem([parts[-1]])
            item.setIcon(0, icon('terminal', self.preferences.theme == 'dark'))
            item.setData(0,Qt.ItemDataRole.UserRole,name)
            item.setToolTip(0,f"{profile.get('mode','SSH')} · {profile.get('host','')}")
            (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))
        self.tree.expandAll()

    def connect_profile(self, item, _column):
        name = item.data(0,Qt.ItemDataRole.UserRole)
        if name: self.load_profile(name); self.show_quick_connect()

    def mode_changed(self, mode):
        serial = mode == 'Serial'
        self.apply_protocol_defaults(mode)
        self.host.clear(); self._loaded_profile = None; self._pending_label = None
        self.serial_row.setVisible(serial)
        self.trust_group.setVisible(not serial)
        self.user.setEnabled(not serial); self.password.setEnabled(not serial)
        self.known.setEnabled(not serial)
        self.password.clear()
        if serial: self.scan_ports()

    def apply_protocol_defaults(self, mode):
        settings = session_templates.settings(self.templates, mode)
        self.options = {key:settings.get(key,value) for key,value in DEFAULTS.items()}
        self.port.setText(settings['port'])
        self.user.setText(settings.get('username','')); self.known.setText(settings.get('known_hosts',''))
        self.password.clear(); self.passphrase = None
        self.jump_password = self.jump_passphrase = None

    def new_session(self):
        self.apply_protocol_defaults(self.mode.currentText()); self.host.clear()
        self._loaded_profile = None; self._pending_label = None; self.show_quick_connect()

    def edit_defaults(self):
        from .session_manager import TemplateDialog
        dialog=TemplateDialog(self)
        try: dialog.exec()
        finally: dialog.deleteLater()

    def open_session_manager(self, selected=None):
        from .session_manager import SessionManager
        if selected is None or isinstance(selected,bool):
            selected=tuple(item.data(0,Qt.ItemDataRole.UserRole) for item in self.tree.selectedItems()
                           if item.data(0,Qt.ItemDataRole.UserRole))
        dialog=SessionManager(self, selected)
        try: dialog.exec()
        finally: dialog.deleteLater()

    def commit_profiles(self, updated, *, expected_revision=...):
        if self.profile_error:
            self.status.setText('会话文件无法读取，已禁用保存以保护原文件'); return False
        try:
            snapshot=self.profile_store.save(updated,expected_revision=self.profile_revision if expected_revision is ... else expected_revision)
        except StorageConflict:
            self.status.setText('另一个窗口已修改会话配置；原文件保留，请先在会话管理中重新载入。');return False
        except CommitUncertain:
            self.status.setText('保存结果待确认，磁盘可能已有更新；请重新载入并核对。');return False
        except (OSError,ValueError):
            self.status.setText('保存失败，请检查字段、文件权限或其他窗口的保存操作；原文件保留。');return False
        self.profiles,self.profile_revision=snapshot.value,snapshot.revision
        self.update_profiles();return True

    def reload_profiles(self):
        try:snapshot=self.profile_store.read()
        except (OSError,ValueError,TypeError):self.status.setText('磁盘会话文件无法读取；保留当前窗口内容。');return False
        self.profiles,self.profile_revision=snapshot.value,snapshot.revision;self.profile_error=None
        self.update_profiles();return True

    def restore_profile_backup(self, *, expected_revision=..., expected_backup_revision=ANY_REVISION):
        try:snapshot=self.profile_store.restore_backup(expected_revision=self.profile_revision if expected_revision is ... else expected_revision,
                                                       expected_backup_revision=expected_backup_revision)
        except StorageConflict:self.status.setText('文件在恢复前已变化；请重新载入后检查。');return False
        except CommitUncertain:self.status.setText('恢复结果待确认，请重新载入磁盘文件并核对。');return False
        except (OSError,ValueError):self.status.setText('有效备份无法恢复；当前文件保留。');return False
        self.profiles,self.profile_revision=snapshot.value,snapshot.revision;self.profile_error=None
        self.update_profiles();return True

    def scan_ports(self):
        if self._probe and self._probe.isRunning(): return
        self.refresh_ports.setEnabled(False)
        probe = PortProbe(); self._probe = probe
        probe.ports_ready.connect(self.ports_ready)
        probe.failed.connect(self.status.setText)
        probe.finished.connect(self.port_probe_finished)
        probe.start()

    @Slot()
    def port_probe_finished(self):
        if self.sender() is self._probe:
            self.refresh_ports.setEnabled(True)

    @Slot(list)
    def ports_ready(self, ports):
        self.devices.clear(); self.devices.addItem('选择串口，或手动输入设备名','')
        for port in ports:
            self.devices.addItem(f"{port['device']} · {port['description']}",port['device'])
            self.devices.setItemData(self.devices.count()-1,port['hwid'],Qt.ItemDataRole.ToolTipRole)
        if not ports: self.status.setText('未发现串口，仍可手动填写设备名称。')

    def pick_port(self, index):
        device = self.devices.itemData(index)
        if device: self.host.setText(device)

    def choose_known_hosts(self):
        path,_ = QFileDialog.getOpenFileName(self,'选择已核验的 known_hosts')
        if path: self.known.setText(path)

    def edit_options(self):
        parent = self.quick_dialog if self.quick_dialog.isVisible() else self
        dialog = ConnectionOptions(self.options,parent,profiles=self.profiles)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.options = dialog.values(); self.passphrase = dialog.passphrase.text() or None
                self.jump_password = dialog.jump_password.text() or None
                self.jump_passphrase = dialog.jump_passphrase.text() or None
        finally:
            dialog.passphrase.clear()
            dialog.jump_password.clear(); dialog.jump_passphrase.clear()
            dialog.deleteLater()

    def load_profile(self, name):
        profile = self.profiles.get(name)
        if not profile: return
        self.populate_profile(profile, name=name)

    def populate_profile(self, profile, *, name=None):
        self.mode.setCurrentText(profile.get('mode','SSH'))
        for widget,key in ((self.host,'host'),(self.port,'port'),(self.user,'username'),(self.known,'known_hosts')):
            widget.setText(profile.get(key,('115200' if self.mode.currentText()=='Serial' else '22') if key=='port' else ''))
        self.options = {key:profile.get(key,value) for key,value in DEFAULTS.items()}
        self._loaded_profile = name
        self._pending_label = None
        if name:self.saved.setCurrentText(name)
        self.quick_host.setText(profile.get('host','') if profile.get('mode','SSH') == 'SSH' else '')
        self.password.clear(); self.passphrase = None
        self.jump_password = self.jump_passphrase = None

    def save_profile(self):
        if self.profile_error:
            self.status.setText('请先备份并修复损坏的会话文件'); return
        name,ok = QInputDialog.getText(self,'保存会话','名称，支持 文件夹/会话')
        if not ok or not name.strip(): return
        name = name.strip()
        if name in self.profiles and QMessageBox.question(self,'替换会话','覆盖同名会话？') != QMessageBox.StandardButton.Yes:
            return
        updated = dict(self.profiles)
        updated[name] = dict(mode=self.mode.currentText(),host=self.host.text().strip(),port=self.port.text(),
                             username=self.user.text().strip(),known_hosts=self.known.text().strip(),**self.options)
        if not self.commit_profiles(updated): return
        self._loaded_profile=name
        self.status.setText('会话已保存，密码和私钥口令不写入磁盘')

    def connect_session(self):
        if self._closing or self.tabs.count() >= 16:
            self.status.setText('最多打开 16 个会话，请关闭旧标签'); return
        try:
            number = int(self.port.text())
            if self.options['encoding'] not in ENCODINGS: raise ValueError('encoding')
            if self.mode.currentText() == 'Serial':
                settings = SerialSettings(number,int(self.options['bytesize']),self.options['parity'],
                                          float(self.options['stopbits']),self.options['flow_control'])
                options = dict(device=self.host.text().strip(),baudrate=settings.baudrate,
                               bytesize=settings.bytesize,parity=settings.parity,
                               stopbits=settings.stopbits,flow_control=settings.flow_control)
            else:
                if not 1 <= number <= 65535: raise ValueError('port')
                options = dict(host=self.host.text().strip(),username=self.user.text().strip(),
                               port=number,password=self.password.text() or None,
                               passphrase=self.passphrase,known_hosts=self.known.text().strip() or None,
                               auth_method=self.options['auth_method'],shell=self.options.get('ssh_mode','shell')=='shell',
                               security={key:self.options[key] for key in POLICY_FIELDS})
                if self.options.get('client_certificate'):options['client_certs']=[self.options['client_certificate']]
                if self.options['private_key']: options['client_keys'] = [self.options['private_key']]
                reference = self.options.get('jump_profile')
                if reference:
                    jump = self.profiles.get(reference)
                    if not jump or jump.get('mode','SSH') != 'SSH' or jump.get('jump_profile'):
                        raise ValueError('Missing, recursive or multi-hop jump profile')
                    options['jump'] = dict(host=jump.get('host',''), username=jump.get('username',''),
                        port=int(jump.get('port','22')), known_hosts=jump.get('known_hosts') or None,
                        password=self.jump_password, passphrase=self.jump_passphrase)
                    options['jump']['auth_method'] = jump.get('auth_method','auto')
                    options['jump']['security']={key:jump[key] for key in POLICY_FIELDS if key in jump}
                    if jump.get('client_certificate'):options['jump']['client_certs']=[jump['client_certificate']]
                    if jump.get('private_key'): options['jump']['client_keys'] = [jump['private_key']]
        except (ValueError,TypeError):
            self.status.setText('连接参数无效，请检查端口、编码、串口或跳板引用；当前仅支持单级跳板'); return
        if self.mode.currentText()=='SSH':
            from .ssh_dialogs import confirm_compatibility
            if not confirm_compatibility(options,self.quick_dialog if self.quick_dialog.isVisible() else self):
                self.status.setText('已取消本次兼容连接');return
        self.password.clear(); self.passphrase = None
        self.jump_password = self.jump_passphrase = None
        worker = Worker(self.mode.currentText(),options)
        worker.receive_stream.configure(self.options['encoding'])
        terminal = Terminal(worker,encoding=self.options['encoding'],backspace=self.options['backspace'])
        terminal.set_appearance(self.preferences.scheme, terminal_font(self.preferences.family, self.preferences.size))
        terminal.connection_profile = dict(mode=self.mode.currentText(),host=self.host.text().strip(),port=self.port.text(),
            username=self.user.text().strip(),known_hosts=self.known.text().strip(),**self.options)
        loaded = self.profiles.get(self._loaded_profile, {})
        terminal.session_label = (self._loaded_profile.split('/')[-1] if loaded and loaded.get('host') == self.host.text().strip()
                                  else self.host.text().strip()[:40] or '会话')
        pending=getattr(self,'_pending_label',None)
        if pending and pending[1]==self.host.text().strip():terminal.session_label=pending[0]
        self.sessions[worker] = terminal; self.workers.append(worker)
        self.tabs.setCurrentIndex(self.tabs.addTab(terminal,terminal.session_label))
        self.tabs.setTabIcon(self.tabs.indexOf(terminal), icon('pending'))
        worker.state.connect(self.on_worker_state)
        worker.failed.connect(self.on_worker_error)
        worker.finished.connect(self.on_worker_finished)
        worker.file_result.connect(self.on_file_result)
        worker.forward_result.connect(self.on_forward_result)
        worker.auth_requested.connect(self.on_auth_requested)
        worker.start(); self.quick_dialog.accept(); self.activateWindow(); terminal.setFocus()

    def clone_session(self):
        terminal=self.tabs.currentWidget()
        if not terminal:return
        self.populate_profile(dict(terminal.connection_profile))
        self._pending_label=(terminal.session_label,self.host.text().strip())
        self.show_quick_connect()
        self.quick_dialog.error.setText('已载入该连接的非秘密参数；请重新提供本次凭据。确认后建立独立连接。')

    def rename_tab(self):
        terminal=self.tabs.currentWidget()
        if not terminal:return
        name,ok=QInputDialog.getText(self,'临时标签名称','仅修改当前标签，不改保存的会话：',text=terminal.session_label)
        if not ok:return
        if not name.strip() or len(name)>128 or any(ord(c)<32 or ord(c)==127 for c in name):
            self.status.setText('标签名称无效');return
        terminal.session_label=name.strip();self.session_state(terminal.worker,terminal.worker.status);self.current_changed(self.tabs.currentIndex())

    def toggle_input_lock(self,checked=False):
        terminal=self.tabs.currentWidget()
        if terminal:terminal.worker.set_input_locked(checked);self.update_activity()

    @Slot(str)
    def on_worker_state(self, state):
        worker = self.sender()
        if state in ('Closing', 'Disconnected'):
            dialog = self.auth_dialogs.pop(worker, None)
            if dialog: dialog.finish_without_reply()
        self.session_state(worker, state)

    @Slot(dict)
    def on_auth_requested(self, event):
        worker = self.sender()
        if worker not in self.sessions or self._closing or worker.stop_event.is_set():
            if worker: worker.reply_auth(event['id'], None)
            return
        previous = self.auth_dialogs.pop(worker, None)
        if previous: previous.finish_without_reply()
        dialog = AuthenticationDialog(worker, event, self); self.auth_dialogs[worker] = dialog
        def released(_result):
            if self.auth_dialogs.get(worker) is dialog: self.auth_dialogs.pop(worker, None)
            dialog.deleteLater()
        dialog.finished.connect(released); dialog.open()

    @Slot(str)
    def on_worker_error(self, message):
        self.session_error(self.sender(), message)

    @Slot()
    def on_worker_finished(self):
        self.worker_finished(self.sender())

    @Slot(dict)
    def on_file_result(self, event):
        terminal = self.sessions.get(self.sender())
        if terminal and (event['status'] in ('error', 'uncertain') or event.get('cleanup_warning')):
            terminal.last_file_error = event.get('message', '临时文件或SFTP通道清理未确认，请检查')
            if self.tabs.currentWidget() is terminal:
                self.status.setText(terminal.last_file_error)

    @Slot(dict)
    def on_forward_result(self, event):
        terminal = self.sessions.get(self.sender())
        if terminal and event['status'] == 'error' and self.tabs.currentWidget() is terminal:
            self.status.setText(event.get('message','转发失败'))

    def service_panel(self, kind):
        terminal = self.tabs.currentWidget()
        if not terminal:
            self.status.setText('请先选择会话'); return None
        worker = terminal.worker
        if kind in ('sftp', 'forward','diagnostics') and worker.mode != 'SSH':
            self.status.setText('此工具仅用于当前SSH会话'); return None
        if kind == 'hex' and worker.mode != 'Serial':
            self.status.setText('当前Hex视图用于串口原始字节'); return None
        key = (worker, kind)
        if key not in self.service_panels:
            if kind == 'sftp':
                panel = SFTPDialog(worker, terminal.session_label, self)
            elif kind == 'forward':
                panel = ForwardDialog(worker, terminal.session_label, self)
            elif kind == 'hex':
                panel = HexDialog(worker, terminal.session_label, self)
            elif kind=='diagnostics':
                from .ssh_dialogs import DiagnosticsDialog
                panel=DiagnosticsDialog(worker,terminal.session_label,self)
            else:
                panel = LogDialog(worker, terminal.session_label, terminal.encoding, self)
            self.service_panels[key] = panel
        panel = self.service_panels[key]
        panel.show(); panel.raise_(); panel.activateWindow()
        return panel

    def open_sftp(self):
        panel = self.service_panel('sftp')
        if panel and not panel.pending:
            panel.refresh_directory()

    def open_log(self):
        self.service_panel('log')

    def open_hex(self):
        self.service_panel('hex')

    def open_forwards(self):
        self.service_panel('forward')

    def open_diagnostics(self):self.service_panel('diagnostics')

    def open_host_keys(self):
        from .key_dialogs import HostKeysDialog
        dialog=HostKeysDialog(self)
        try:dialog.exec()
        finally:dialog.deleteLater()

    def open_key_tools(self):
        from .key_dialogs import KeyToolsDialog
        if self.key_dialog is None:self.key_dialog=KeyToolsDialog(self)
        self.key_dialog.show();self.key_dialog.raise_();self.key_dialog.activateWindow()

    def key_job_running(self):return bool(self.key_dialog and self.key_dialog.job and self.key_dialog.job.isRunning())

    def update_activity(self):
        terminal = self.tabs.currentWidget()
        connected = bool(terminal and terminal.worker.status == 'Connected' and not terminal.worker.stop_event.is_set())
        self.diagnostics_action.setEnabled(bool(terminal and terminal.worker.mode=='SSH'))
        for action in (self.clone_action,self.rename_tab_action,self.input_lock_action):action.setEnabled(bool(terminal))
        self.reconnect_action.setEnabled(bool(terminal and terminal.worker.status=='Disconnected'))
        self.input_lock_action.setChecked(bool(terminal and terminal.worker.input_locked))
        self.disconnect_action.setEnabled(bool(terminal and terminal.worker.status != 'Disconnected'))
        for action in (self.copy_action, self.paste_action, self.find_action, self.close_action): action.setEnabled(bool(terminal))
        for action in (self.sftp_button, self.forward_button): action.setEnabled(connected and terminal.worker.mode == 'SSH')
        self.hex_button.setEnabled(connected and terminal.worker.mode == 'Serial')
        self.log_button.setEnabled(connected); self.break_button.setEnabled(connected and terminal.worker.interactive and not terminal.worker.input_locked)
        if not terminal:
            self.activity.clear(); self.dimensions.clear(); self.connection_info.setText('未连接'); return
        worker = terminal.worker
        notes = []
        if worker.input_locked:notes.append('输入已锁定（已启动流程仍可继续）')
        if worker.journal:
            value = worker.journal.snapshot()
            label = dict(opening='准备', running='记录中', closing='关闭中', closed='已停止', error='错误')
            notes.append('日志：' + (value['error'] or ('暂停' if value['paused'] and value['alive'] else label.get(value['state'], value['state']))))
        progress = worker.file_progress()
        if progress.get('phase') in ('starting','transferring','verifying','committing'):
            notes.append('SFTP：' + progress['phase'])
        forwards = worker.forwards()
        if forwards: notes.append(f'转发监听：{len(forwards)}')
        flow = worker.flow_progress()
        if flow.get('phase') in ('starting','running'):notes.append(f"流程：{flow.get('step',0)}/{flow.get('total',0)}")
        self.activity.setText(' · '.join(notes))
        self.dimensions.setText(f'{terminal.screen.lines} 行 × {terminal.screen.columns} 列' if worker.interactive else '')
        protocol = 'SSH2' if worker.mode == 'SSH' else 'Serial'
        self.connection_info.setText((f'{protocol} · {terminal.encoding.upper()}' if worker.interactive else 'SSH2 · 仅SFTP/隧道') if connected else STATES.get(worker.status, worker.status))

    def session_state(self, worker, state):
        terminal = self.sessions.get(worker)
        if not terminal: return
        index = self.tabs.indexOf(terminal)
        if index >= 0:
            self.tabs.setTabText(index,terminal.session_label)
            self.tabs.setTabToolTip(index,terminal.session_label+' · '+STATES.get(state,state))
            self.tabs.setTabIcon(index,icon('connected' if state == 'Connected' else 'disconnected' if state == 'Disconnected' else 'pending'))
        if self.tabs.currentWidget() is terminal:
            self.status.setText(terminal.session_label+' · '+STATES.get(state,state))
        if not worker.interactive:
            terminal.notice='仅 SFTP / SSH 隧道 · '+STATES.get(state,state)+'\n此连接不打开远程 Shell。'
            terminal.viewport().update()
        self.rebuild_active_sessions(); self.update_activity()

    def session_error(self, worker, message):
        terminal = self.sessions.get(worker)
        if terminal:
            terminal.connection_error = message
            index = self.tabs.indexOf(terminal)
            if index >= 0: self.tabs.setTabToolTip(index,message)
            if self.tabs.currentWidget() is terminal:
                self.status.setText(terminal.session_label+' · '+message)

    def current_changed(self, _):
        terminal = self.tabs.currentWidget()
        self.workspace.setCurrentIndex(1 if terminal else 0)
        self.setWindowTitle((terminal.session_label+' — ' if terminal else '')+'Harbor Terminal')
        if terminal:
            self.status.setText(terminal.session_label+' · '+getattr(terminal,'connection_error',STATES.get(terminal.worker.status,terminal.worker.status)))
            terminal.setFocus()
        else: self.status.setText('就绪')
        self.rebuild_active_sessions(); self.update_activity()

    def disconnect(self):
        terminal = self.tabs.currentWidget()
        if terminal: terminal.worker.stop_event.set()

    def send_break(self):
        terminal = self.tabs.currentWidget()
        if terminal and not terminal.worker.send_break(): self.status.setText('当前会话未连接，无法发送 BREAK')

    def find_next(self, backwards=False):
        terminal = self.tabs.currentWidget()
        if terminal and not terminal.find(self.search.text(),backwards=bool(backwards)):
            self.status.setText('当前终端未找到匹配；查找按字面文本进行')

    def close_tab(self, index):
        terminal = self.tabs.widget(index)
        if not terminal: return
        worker = terminal.worker
        if worker.isRunning():
            self._closing_tabs.add(worker); worker.stop_event.set()
            return
        self.remove_session(worker)

    def remove_session(self, worker):
        dialog = self.auth_dialogs.pop(worker, None)
        if dialog: dialog.finish_without_reply()
        terminal = self.sessions.pop(worker,None)
        if terminal:
            if self.command_panel:self.command_panel.remove_worker(worker)
            for key in [key for key in self.service_panels if key[0] is worker]:
                panel = self.service_panels.pop(key)
                panel.close(); panel.deleteLater()
            self.tabs.removeTab(self.tabs.indexOf(terminal)); terminal.timer.stop()
            terminal.deleteLater(); self.workers.remove(worker)
            self._closing_tabs.discard(worker); worker.deleteLater()
            self.rebuild_active_sessions()

    def worker_finished(self, worker):
        terminal = self.sessions.get(worker)
        if terminal and getattr(terminal,'connection_error',None):
            self.current_changed(self.tabs.currentIndex())
        if worker in self._closing_tabs: self.remove_session(worker)

    def finish_close(self):
        busy = any(w.isRunning() for w in self.workers) or (self._probe and self._probe.isRunning()) or self.key_job_running()
        if not busy:
            self.close_timer.stop(); self.close()

    def closeEvent(self, event):
        self._closing = True; self.connect_button.setEnabled(False)
        if self.key_dialog:self.key_dialog.reject()
        self.quick_action.setEnabled(False); self.quick_dialog.reject()
        if self.command_panel:self.command_panel.cancel_flows()
        for dialog in list(self.auth_dialogs.values()): dialog.finish_without_reply()
        for worker in self.workers: worker.stop_event.set()
        busy = any(w.isRunning() for w in self.workers) or (self._probe and self._probe.isRunning()) or self.key_job_running()
        if busy:
            self.status.setText('正在取消任务并关闭连接…'); self.close_timer.start(50)
            event.ignore(); return
        for terminal in self.sessions.values(): terminal.timer.stop()
        for panel in self.service_panels.values(): panel.close()
        self.service_timer.stop()
        self.password.clear(); self.passphrase = None
        self.jump_password = self.jump_passphrase = None
        event.accept()


def main():
    from .startup import argument_parser, populate_window
    parser=argument_parser()
    args = parser.parse_args()
    if args.run_flow:
        import asyncio
        from .batch import run_batch
        try:status=asyncio.run(run_batch(args))
        except (OSError,ValueError,KeyError):parser.error('Invalid batch configuration')
        sys.exit(status)
    if args.serial_report:
        from .hardware import serial_diagnostic
        try:status=serial_diagnostic(args.serial_report, mode=args.serial_mode, port=args.serial_port,
            baudrate=args.baudrate if args.baudrate is not None else 115200, seconds=args.seconds, loopback_only=args.loopback_only)
        except (OSError,ValueError):parser.error('Invalid serial diagnostic configuration')
        sys.exit(status)
    app = QApplication(sys.argv)
    if args.smoke_test_report:
        from .diagnostics import desktop_smoke
        sys.exit(desktop_smoke(app, args.smoke_test_report))
    window = Window(profile_path=args.sessions)
    try:open_connect=populate_window(window,args)
    except (ValueError,OSError):window.close();parser.error('Invalid destination configuration')
    window.show()
    if open_connect:window.show_quick_connect()
    sys.exit(app.exec())


if __name__ == '__main__': main()
