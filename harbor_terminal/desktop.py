"""Compact desktop shell: menu, toolbar, session docks and connection dialogs."""
from PySide6.QtCore import Qt, QSize
from importlib.metadata import version
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel, QTabWidget, QDialog,
    QDialogButtonBox, QGroupBox, QFileDialog, QDockWidget, QTreeWidget,
    QTreeWidgetItem, QToolBar, QToolButton, QStackedWidget, QListWidget,
    QMenu, QMessageBox, QFontDialog)

from .appearance import Preferences, SCHEMES, apply_desktop_style, icon, terminal_font
from .terminal_model import ENCODINGS
from .authentication import AUTH_METHODS


class ConnectionOptions(QDialog):
    def __init__(self, options, parent=None, profiles=None):
        super().__init__(parent)
        self.setWindowTitle('会话选项')
        self.resize(650, 430)
        outer = QVBoxLayout(self)
        row = QHBoxLayout(); outer.addLayout(row, 1)
        categories = QListWidget(); categories.setFixedWidth(145)
        categories.addItems(['终端 / 编码', 'SSH / 身份', 'SSH / 跳板', '串口'])
        pages = QStackedWidget(); row.addWidget(categories); row.addWidget(pages, 1)

        def page(title):
            pane = QWidget(); layout = QVBoxLayout(pane)
            group = QGroupBox(title); form = QFormLayout(group)
            form.setSpacing(12); layout.addWidget(group); layout.addStretch()
            pages.addWidget(pane)
            return form

        form = page('终端设置')
        self.encoding = QComboBox(); self.encoding.addItems(ENCODINGS)
        self.encoding.setCurrentText(options['encoding'])
        self.backspace = QComboBox(); self.backspace.addItems(['del', 'bs'])
        self.backspace.setCurrentText(options['backspace'])
        form.addRow('字符编码：', self.encoding); form.addRow('Backspace：', self.backspace)
        note = QLabel('字体与配色可在主窗口的“选项”菜单中设置。'); note.setWordWrap(True)
        form.addRow(note)

        form = page('SSH 身份验证')
        self.auth_method = QComboBox()
        for label, value in (('自动（密钥、密码、交互）','auto'),('密码优先','password-first'),('交互优先','interactive-first'),
                            ('仅公钥','publickey-only'),('仅交互 / MFA','interactive-only')):
            self.auth_method.addItem(label, value)
        self.auth_method.setCurrentIndex(max(0, self.auth_method.findData(options.get('auth_method','auto'))))
        form.addRow('认证方式：', self.auth_method)
        self.private_key = QLineEdit(options['private_key'])
        key_row = QHBoxLayout(); key_row.addWidget(self.private_key, 1)
        choose = QPushButton('浏览…'); choose.clicked.connect(self.choose_key); key_row.addWidget(choose)
        self.passphrase = QLineEdit(); self.passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('私钥文件：', key_row); form.addRow('本次私钥口令：', self.passphrase)
        note = QLabel('密码和私钥口令仅用于本次连接，不保存到会话配置。'); note.setWordWrap(True)
        form.addRow(note)

        form = page('单级 SSH 跳板')
        self.jump_profile = QComboBox(); self.jump_profile.addItem('不使用跳板', '')
        for name, profile in sorted((profiles or {}).items()):
            if profile.get('mode', 'SSH') == 'SSH': self.jump_profile.addItem(name, name)
        reference = options.get('jump_profile', '')
        index = self.jump_profile.findData(reference)
        if index < 0:
            self.jump_profile.addItem('缺失会话：' + reference, reference)
            index = self.jump_profile.count() - 1
        self.jump_profile.setCurrentIndex(index)
        self.jump_password = QLineEdit(); self.jump_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.jump_passphrase = QLineEdit(); self.jump_passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('已保存的跳板：', self.jump_profile)
        form.addRow('跳板本次密码：', self.jump_password); form.addRow('跳板私钥口令：', self.jump_passphrase)
        note = QLabel('跳板和目标分别校验自己的主机密钥。'); note.setWordWrap(True); form.addRow(note)

        form = page('串口参数')
        self.serial_fields = {}
        choices = dict(bytesize=['5','6','7','8'], parity=['N','E','O','M','S'],
                       stopbits=['1','1.5','2'], flow_control=['none','rtscts','dsrdtr','xonxoff'])
        labels = dict(bytesize='数据位：', parity='校验位：', stopbits='停止位：', flow_control='流控：')
        for key, values in choices.items():
            field = QComboBox(); field.addItems(values); field.setCurrentText(options[key])
            self.serial_fields[key] = field; form.addRow(labels[key], field)
        form.addRow(QLabel('设备和波特率在“快速连接”中设置。'))
        categories.currentRowChanged.connect(pages.setCurrentIndex); categories.setCurrentRow(0)
        outer.addWidget(QLabel('连接参数在下次连接时生效。'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('确定')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def choose_key(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择私钥文件')
        if path: self.private_key.setText(path)

    def values(self):
        return dict(encoding=self.encoding.currentText(), backspace=self.backspace.currentText(),
                    private_key=self.private_key.text().strip(), jump_profile=self.jump_profile.currentData(),
                    auth_method=self.auth_method.currentData(),
                    **{key: field.currentText() for key, field in self.serial_fields.items()})


class QuickConnectDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle('快速连接')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(560, 435)
        layout = QVBoxLayout(self); layout.setSpacing(12)
        form = QFormLayout(); form.setSpacing(10); layout.addLayout(form)
        owner.saved = QComboBox(); owner.saved.textActivated.connect(owner.load_profile)
        owner.mode = QComboBox(); owner.mode.addItems(['SSH', 'Serial'])
        owner.host = QLineEdit(); owner.host.setPlaceholderText('主机名、IP 地址或 COM3')
        owner.port = QLineEdit('22'); owner.port.setMaximumWidth(100)
        host_row = QHBoxLayout(); host_row.addWidget(owner.host, 1)
        host_row.addWidget(QLabel('端口 / 波特率：')); host_row.addWidget(owner.port)
        owner.user = QLineEdit()
        owner.password = QLineEdit(); owner.password.setEchoMode(QLineEdit.EchoMode.Password)
        owner.password.setPlaceholderText('本次密码；留空使用密钥')
        form.addRow('已保存会话：', owner.saved); form.addRow('协议：', owner.mode)
        form.addRow('主机 / 设备：', host_row); form.addRow('用户名：', owner.user)
        form.addRow('密码：', owner.password)
        owner.serial_row = QWidget(); serial_layout = QHBoxLayout(owner.serial_row)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        owner.devices = QComboBox(); owner.devices.addItem('选择串口，或在上方手动输入', '')
        owner.devices.activated.connect(owner.pick_port)
        owner.refresh_ports = QPushButton('刷新'); owner.refresh_ports.clicked.connect(owner.scan_ports)
        serial_layout.addWidget(owner.devices, 1); serial_layout.addWidget(owner.refresh_ports)
        form.addRow('', owner.serial_row); owner.serial_row.hide()
        trust = QGroupBox('主机密钥')
        owner.trust_group = trust
        trust_layout = QVBoxLayout(trust)
        owner.known = QLineEdit(); owner.known.setPlaceholderText('默认 ~/.ssh/known_hosts')
        row = QHBoxLayout(); row.addWidget(owner.known, 1)
        browse = QPushButton('浏览…'); browse.clicked.connect(owner.choose_known_hosts); row.addWidget(browse)
        trust_layout.addLayout(row)
        hint = QLabel('使用已独立核验的 known_hosts；未知或变更的主机密钥将被拒绝。')
        hint.setWordWrap(True); trust_layout.addWidget(hint); layout.addWidget(trust)
        self.error = QLabel(); self.error.setWordWrap(True); self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error); layout.addStretch()
        row = QHBoxLayout(); layout.addLayout(row)
        owner.settings_button = QPushButton('会话选项…'); owner.settings_button.clicked.connect(owner.edit_options)
        row.addWidget(owner.settings_button); row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        owner.connect_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        owner.connect_button.setText('连接'); owner.connect_button.setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.connect_requested); buttons.rejected.connect(self.reject); row.addWidget(buttons)

    def connect_requested(self):
        if not self.owner.host.text().strip() or (self.owner.mode.currentText() == 'SSH' and not self.owner.user.text().strip()):
            self.error.setText('请填写主机 / 设备；SSH 还需要用户名。')
            return
        before = len(self.owner.workers)
        self.owner.connect_session()
        if len(self.owner.workers) == before: self.error.setText(self.owner.status.text())

    def reject(self):
        self.owner.password.clear(); self.owner.passphrase = None
        self.owner.jump_password = self.owner.jump_passphrase = None
        super().reject()


class DesktopShell:
    def build_desktop(self):
        self.preferences = Preferences(self.profile_path)
        apply_desktop_style(self, self.preferences.theme)
        self._loaded_profile = None
        self.quick_dialog = QuickConnectDialog(self)
        self.status = QLabel('就绪'); self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setMinimumWidth(80)
        self.statusBar().setSizeGripEnabled(True); self.statusBar().addWidget(self.status, 1)
        self.activity = QLabel(); self.activity.setTextFormat(Qt.TextFormat.PlainText)
        self.dimensions = QLabel(); self.dimensions.setMinimumWidth(95)
        self.connection_info = QLabel('未连接'); self.connection_info.setMinimumWidth(120)
        for widget in (self.activity, self.connection_info, self.dimensions):
            widget.setContentsMargins(7, 1, 7, 1); self.statusBar().addPermanentWidget(widget)
        root = QWidget(); layout = QVBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        self.setCentralWidget(root)
        self.workspace = QStackedWidget(); layout.addWidget(self.workspace, 1)
        empty = QWidget(); empty.setStyleSheet('background:#000000;')
        empty_layout = QVBoxLayout(empty)
        hint = QLabel('双击会话开始连接，或按 Alt+Q 快速连接。')
        hint.setStyleSheet('color:#a0a0a0;background:transparent;'); hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(hint); self.workspace.addWidget(empty)
        self.tabs = QTabWidget(); self.tabs.setDocumentMode(True); self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True); self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabCloseRequested.connect(self.close_tab); self.tabs.currentChanged.connect(self.current_changed)
        self.workspace.addWidget(self.tabs)
        self._build_actions(); self._build_manager(); self._build_toolbar(); self._build_menus()
        self.find_bar = QToolBar('查找', self); self.find_bar.setObjectName('findBar'); self.find_bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self.find_bar)
        self.search = QLineEdit(); self.search.setPlaceholderText('查找当前终端中的文本'); self.search.setMinimumWidth(240)
        self.search.returnPressed.connect(self.find_next)
        self.find_bar.addWidget(QLabel(' 查找：')); self.find_bar.addWidget(self.search)
        self.find_bar.addAction(icon('up'), '上一处', lambda: self.find_next(True))
        self.find_bar.addAction(icon('down'), '下一处', self.find_next)
        self.find_bar.addAction(icon('close'), '关闭查找', self.hide_find_bar); self.find_bar.hide()
        self.command_buttons = QToolBar('按钮栏', self); self.command_buttons.setObjectName('commandButtons')
        self.command_buttons.setMovable(False); self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self.command_buttons)
        self.command_panel = None; self.refresh_command_buttons()
        QShortcut(QKeySequence('Alt+R'), self, activated=self.quick_host.setFocus)
        QShortcut(QKeySequence('Alt+K'), self, activated=self.focus_session_filter)
        self.update_profiles()
        self.mode.currentTextChanged.connect(self.mode_changed)

    def _action(self, name, text, callback, shortcut=None):
        action = QAction(icon(name, self.preferences.theme == 'dark'), text, self)
        if shortcut: action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        action.setToolTip(text.replace('&','') + (f' ({shortcut})' if shortcut else ''))
        return action

    def _build_actions(self):
        self.quick_action = self._action('quick', '快速连接…', lambda: self.show_quick_connect(), 'Alt+Q')
        self.disconnect_action = self._action('disconnected', '断开当前会话', self.disconnect, 'Ctrl+Shift+D')
        self.save_action = self._action('save', '保存会话…', self.save_profile, 'Alt+S')
        self.close_action = self._action('close', '关闭当前标签', lambda: self.close_tab(self.tabs.currentIndex()), 'Ctrl+Shift+W')
        # Terminal owns these keys. A window-wide paste shortcut could send
        # clipboard text to SSH while the user is editing a local input field.
        self.copy_action = self._action('copy', '复制\tCtrl+Shift+C', lambda: self.terminal_action('copy'))
        self.paste_action = self._action('paste', '粘贴…\tCtrl+Shift+V', lambda: self.terminal_action('paste_confirmed'))
        self.copy_action.setToolTip('复制 (Ctrl+Shift+C)')
        self.paste_action.setToolTip('粘贴 (Ctrl+Shift+V)')
        self.find_action = self._action('search', '查找…', self.show_find_bar, 'Ctrl+F')
        self.options_action = self._action('settings', '会话选项…', self.edit_options)
        self.font_action = self._action('font', '终端字体…', self.choose_terminal_font)
        self.sftp_button = self._action('sftp', 'SFTP 文件', self.open_sftp)
        self.log_button = self._action('log', '会话日志', self.open_log)
        self.hex_button = self._action('terminal', '串口 Hex', self.open_hex)
        self.forward_button = self._action('forward', 'SSH 隧道', self.open_forwards)
        self.break_button = self._action('terminal', '发送 BREAK', self.send_break)
        self.command_action = self._action('terminal', '命令与流程…', self.open_command_panel, 'Alt+M')

    def _build_toolbar(self):
        self.toolbar = QToolBar('标准工具栏', self); self.toolbar.setObjectName('standardToolbar')
        self.toolbar.setMovable(False); self.toolbar.setIconSize(QSize(16,16))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(self.toolbar)
        for action in (self.quick_action, self.disconnect_action, self.save_action): self.toolbar.addAction(action)
        self.toolbar.addSeparator()
        self.quick_host = QLineEdit(); self.quick_host.setFixedWidth(195)
        self.quick_host.setPlaceholderText('输入主机  <Alt+R>'); self.quick_host.setClearButtonEnabled(True)
        self.quick_host.returnPressed.connect(lambda: self.show_quick_connect(self.quick_host.text()))
        self.toolbar.addWidget(self.quick_host); self.toolbar.addSeparator()
        for action in (self.copy_action, self.paste_action, self.find_action): self.toolbar.addAction(action)
        self.toolbar.addSeparator()
        for action in (self.options_action, self.font_action): self.toolbar.addAction(action)
        self.toolbar.addSeparator()
        for action in (self.sftp_button, self.log_button, self.forward_button, self.hex_button, self.command_action): self.toolbar.addAction(action)

    def _build_menus(self):
        bar = self.menuBar(); bar.setNativeMenuBar(False)
        file = bar.addMenu('文件(&F)')
        file.addActions([self.quick_action, self.save_action]); file.addSeparator()
        file.addActions([self.disconnect_action, self.close_action]); file.addSeparator()
        file.addAction('退出', self.close, QKeySequence('Alt+F4'))
        edit = bar.addMenu('编辑(&E)'); edit.addActions([self.copy_action, self.paste_action]); edit.addSeparator(); edit.addAction(self.find_action)
        view = bar.addMenu('查看(&V)')
        view.addAction(self.session_dock.toggleViewAction()); view.addAction(self.active_dock.toggleViewAction())
        view.addSeparator(); view.addAction(self.toolbar.toggleViewAction())
        self.view_menu = view
        theme = view.addMenu('界面主题'); group = QActionGroup(self)
        for value, label in (('light','经典浅色'),('dark','深色')):
            action = theme.addAction(label); action.setCheckable(True); action.setChecked(self.preferences.theme == value)
            group.addAction(action); action.triggered.connect(lambda checked, key=value: self.set_desktop_theme(key))
        options = bar.addMenu('选项(&O)'); options.addActions([self.options_action, self.font_action])
        colors = options.addMenu('终端配色'); group = QActionGroup(self)
        for key, (label, _, _) in SCHEMES.items():
            action = colors.addAction(label); action.setCheckable(True); action.setChecked(self.preferences.scheme == key)
            group.addAction(action); action.triggered.connect(lambda checked, value=key: self.set_terminal_scheme(value))
        transfer = bar.addMenu('传输(&T)'); transfer.addAction(self.sftp_button)
        tools = bar.addMenu('工具(&U)'); tools.addActions([self.log_button, self.hex_button, self.forward_button, self.break_button])
        tools.addAction(self.command_action)
        self.windows_menu = bar.addMenu('窗口(&W)'); self.windows_menu.aboutToShow.connect(self.populate_windows_menu)
        help_menu = bar.addMenu('帮助(&H)')
        help_menu.addAction('快捷键', lambda: QMessageBox.information(self, '快捷键',
            'Alt+Q  快速连接\nAlt+R  聚焦主机输入\nAlt+K  会话筛选\nCtrl+F  查找\nCtrl+Shift+C / V  复制 / 粘贴\nCtrl+滚轮  缩放终端字体'))
        help_menu.addAction('关于 Harbor Terminal', lambda: QMessageBox.about(self, 'Harbor Terminal', 'Harbor Terminal ' + version('harbor-terminal') + '\nSSH / 串口终端'))

    def _build_session_docks(self):
        self.setDockOptions(self.dockOptions() | self.DockOption.VerticalTabs)
        self.setTabPosition(Qt.DockWidgetArea.LeftDockWidgetArea, QTabWidget.TabPosition.West)
        self.session_dock = QDockWidget('会话管理器', self); self.session_dock.setObjectName('sessionsDock')
        panel = QWidget(); layout = QVBoxLayout(panel); layout.setContentsMargins(4,4,4,4); layout.setSpacing(4)
        self.session_filter = QLineEdit(); self.session_filter.setPlaceholderText('筛选名称  <Alt+K>')
        self.session_filter.setClearButtonEnabled(True); self.session_filter.textChanged.connect(self.update_profiles)
        layout.addWidget(self.session_filter)
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True); self.tree.itemDoubleClicked.connect(self.connect_profile)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.session_context_menu)
        layout.addWidget(self.tree, 1); self.session_dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.session_dock)
        self.active_dock = QDockWidget('活动会话', self); self.active_dock.setObjectName('activeDock')
        self.active_tree = QTreeWidget(); self.active_tree.setHeaderLabels(['会话', '状态'])
        self.active_tree.setUniformRowHeights(True); self.active_tree.setRootIsDecorated(False)
        self.active_tree.itemDoubleClicked.connect(self.activate_session_item)
        self.active_dock.setWidget(self.active_tree); self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.active_dock)
        self.tabifyDockWidget(self.session_dock, self.active_dock); self.session_dock.raise_()
        self.resizeDocks([self.session_dock], [224], Qt.Orientation.Horizontal)

    def show_quick_connect(self, host=None):
        if self._closing: return
        if isinstance(host, str) and host.strip():
            self.mode.setCurrentText('SSH'); self.host.setText(host.strip()); self._loaded_profile = None
        self.quick_dialog.error.clear(); self.quick_dialog.show(); self.quick_dialog.raise_()
        self.quick_dialog.activateWindow()
        (self.password if self.host.text().strip() and self.user.text().strip() else self.host).setFocus()

    def focus_session_filter(self):
        self.session_dock.show(); self.session_dock.raise_(); self.session_filter.setFocus()

    def terminal_action(self, method):
        terminal = self.tabs.currentWidget()
        if terminal: getattr(terminal, method)()

    def show_find_bar(self):
        self.find_bar.show(); self.activateWindow(); self.search.setFocus(); self.search.selectAll()

    def hide_find_bar(self):
        self.find_bar.hide()
        terminal = self.tabs.currentWidget()
        if terminal: terminal.find(''); terminal.setFocus()

    def session_context_menu(self, position):
        item = self.tree.itemAt(position)
        name = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        menu = QMenu(self)
        if name:
            menu.addAction('连接…', lambda: self.connect_profile(item, 0))
            menu.addAction('载入会话设置', lambda: self.load_profile(name)); menu.addSeparator()
        menu.addAction(self.quick_action); menu.addAction(self.save_action)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def rebuild_active_sessions(self):
        self.active_tree.clear()
        for worker, terminal in self.sessions.items():
            from .app import STATES
            item = QTreeWidgetItem([terminal.session_label, STATES.get(worker.status, worker.status)])
            item.setData(0, Qt.ItemDataRole.UserRole, worker.session_id)
            item.setIcon(0, icon('connected' if worker.status == 'Connected' else 'disconnected' if worker.status == 'Disconnected' else 'pending'))
            self.active_tree.addTopLevelItem(item)
        self.active_tree.resizeColumnToContents(0)

    def activate_session_item(self, item, _column):
        identifier = item.data(0, Qt.ItemDataRole.UserRole)
        for worker, terminal in self.sessions.items():
            if worker.session_id == identifier: self.tabs.setCurrentWidget(terminal); break

    def open_command_panel(self):
        if self.command_panel is None:
            from .workflow_panel import WorkflowPanel
            self.command_panel = WorkflowPanel(self)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.command_panel)
            self.resizeDocks([self.command_panel],[310],Qt.Orientation.Vertical)
            self.view_menu.addAction(self.command_panel.toggleViewAction())
            self.view_menu.addAction(self.command_buttons.toggleViewAction())
        self.command_panel.refresh_targets();self.command_panel.show();self.command_panel.raise_()
        self.command_panel.edit.setFocus()

    def refresh_command_buttons(self):
        from .commands import load_library
        self.command_buttons.clear()
        try:
            commands=self.command_panel.library if self.command_panel else load_library(self.profile_path.with_name('commands.json'))
        except (OSError,ValueError,KeyError):commands={}
        for name,item in commands.items():
            if not item.get('pinned'):continue
            action=self.command_buttons.addAction(name)
            action.setToolTip(name+'（预览后发送到当前会话）')
            action.triggered.connect(lambda checked, key=name:self.preview_command_button(key))
        self.command_buttons.setVisible(bool(self.command_buttons.actions()))

    def preview_command_button(self,name):
        terminal=self.tabs.currentWidget()
        self.open_command_panel()
        definition=self.command_panel.library.get(name)
        if not terminal or not definition:return
        self.command_panel.send_commands([(terminal.worker,terminal.session_label,terminal.encoding)],definition['text'])

    def populate_windows_menu(self):
        self.windows_menu.clear()
        if not self.sessions:
            self.windows_menu.addAction('无活动标签').setEnabled(False); return
        for index in range(self.tabs.count()):
            terminal = self.tabs.widget(index)
            action = self.windows_menu.addAction(terminal.session_label)
            action.setCheckable(True); action.setChecked(self.tabs.currentWidget() is terminal)
            action.triggered.connect(lambda checked, view=terminal: self.tabs.setCurrentWidget(view))

    def choose_terminal_font(self):
        terminal = self.tabs.currentWidget()
        initial = terminal.font() if terminal else terminal_font(self.preferences.family, self.preferences.size)
        accepted, font = QFontDialog.getFont(initial, self, '终端字体（所有标签）', QFontDialog.FontDialogOption.MonospacedFonts)
        if accepted:
            self.preferences.family = font.family(); self.preferences.size = min(28, max(8, font.pointSizeF()))
            self.persist_display(); self.apply_terminal_appearance()

    def set_terminal_scheme(self, key):
        if key not in SCHEMES: return
        self.preferences.scheme = key; self.persist_display(); self.apply_terminal_appearance()

    def set_desktop_theme(self, key):
        if key not in ('light', 'dark'): return
        self.preferences.theme = key; apply_desktop_style(self, key); self.persist_display()
        for action, name in ((self.quick_action,'quick'),(self.disconnect_action,'disconnected'),
            (self.save_action,'save'),(self.copy_action,'copy'),(self.paste_action,'paste'),
            (self.find_action,'search'),(self.options_action,'settings'),(self.font_action,'font'),
            (self.sftp_button,'sftp'),(self.log_button,'log'),(self.forward_button,'forward'),(self.hex_button,'terminal')):
            action.setIcon(icon(name, key == 'dark'))
        self.update_profiles()

    def persist_display(self):
        if not self.preferences.save(): self.status.setText('显示设置保存失败；本次设置仍然有效')

    def apply_terminal_appearance(self):
        for terminal in self.sessions.values():
            terminal.set_appearance(self.preferences.scheme, terminal_font(self.preferences.family, self.preferences.size))
