"""Session-bound SFTP, logging and binary inspection windows."""
from datetime import datetime, timezone
from pathlib import Path
import posixpath

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QProgressBar,
    QFileDialog, QInputDialog, QCheckBox, QComboBox, QSpinBox, QPlainTextEdit,
    QMessageBox)

from .trace import parse_hex, format_record
from .appearance import terminal_font


def plain_label(text=''):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class SFTPDialog(QDialog):
    def __init__(self, worker, label, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.pending = None
        self.setWindowTitle('SFTP · ' + label)
        self.resize(860, 580)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label('复用当前SSH认证连接 · 单文件传输 · 校验后提交。上传以0600创建；覆盖会替换目标及其元数据。'))
        row = QHBoxLayout(); layout.addLayout(row)
        self.path = QLineEdit('.')
        self.path.returnPressed.connect(self.refresh_directory)
        self.up = QPushButton('上级'); self.up.clicked.connect(self.parent_directory)
        self.refresh = QPushButton('刷新'); self.refresh.clicked.connect(self.refresh_directory)
        row.addWidget(self.path, 1); row.addWidget(self.up); row.addWidget(self.refresh)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['名称', '类型', '字节', '修改时间 UTC'])
        self.tree.setRootIsDecorated(False)
        self.tree.itemDoubleClicked.connect(self.open_directory)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout(); layout.addLayout(row)
        self.upload = QPushButton('上传文件'); self.upload.clicked.connect(self.choose_upload)
        self.download = QPushButton('下载选中文件'); self.download.clicked.connect(self.choose_download)
        self.overwrite = QCheckBox('本次允许覆盖目标')
        self.cancel = QPushButton('取消操作'); self.cancel.clicked.connect(self.cancel_operation)
        for widget in (self.upload, self.download, self.overwrite, self.cancel):
            row.addWidget(widget)
        self.progress = QProgressBar(); self.progress.setRange(0, 1000)
        layout.addWidget(self.progress)
        self.status = plain_label('就绪；默认不覆盖。服务器须支持hardlink或POSIX rename安全提交。')
        self.result_text = plain_label()
        layout.addWidget(self.status); layout.addWidget(self.result_text)
        self.timer = QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self.poll)
        worker.file_result.connect(self.operation_finished)
        worker.state.connect(self.connection_state)
        self.set_busy(False)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()

    def set_busy(self, busy):
        connected = self.worker.status == 'Connected' and not self.worker.stop_event.is_set()
        for widget in (self.upload, self.download, self.path, self.up, self.refresh, self.overwrite):
            widget.setEnabled(connected and not busy)
        self.cancel.setEnabled(bool(busy))

    @Slot(str)
    def connection_state(self, state):
        self.set_busy(bool(self.pending))
        if state != 'Connected':
            self.status.setText('连接已关闭或正在关闭；此窗口不会重连或重发文件')

    def submit(self, action, **options):
        try:
            identifier = self.worker.submit_file(action, **options)
        except ValueError:
            self.status.setText('路径无效或包含不支持的控制字符')
            return None
        if not identifier:
            self.status.setText('当前连接不可用，或已有文件操作尚未结束')
            return None
        self.pending = identifier
        if action != 'list':
            self.result_text.clear()
        self.set_busy(True)
        self.status.setText('请求已提交，可取消；提交阶段中断时可能需要核实目标状态')
        return identifier

    def refresh_directory(self):
        return self.submit('list', remote_path=self.path.text() or '.')

    def parent_directory(self):
        self.path.setText(posixpath.dirname(self.path.text().rstrip('/')) or '/')
        self.refresh_directory()

    def open_directory(self, item, _):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data['kind'] == 'directory':
            self.path.setText(posixpath.join(self.path.text(), data['name']))
            self.refresh_directory()

    def choose_upload(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择上传文件')
        if not path:
            return
        remote, ok = QInputDialog.getText(self, '上传目标', '远端文件路径',
            text=posixpath.join(self.path.text(), Path(path).name))
        if not ok:
            return
        overwrite = self.overwrite.isChecked(); self.overwrite.setChecked(False)
        self.submit('upload', local_path=path, remote_path=remote, overwrite=overwrite)

    def choose_download(self):
        item = self.tree.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not data or data['kind'] != 'file':
            self.status.setText('请选择普通文件；当前版本不做目录递归或自动跟随符号链接')
            return
        # Never use an untrusted remote filename as a local directory/path.
        local, _ = QFileDialog.getSaveFileName(self, '保存到明确选定的本地文件', '',
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not local:
            return
        overwrite = self.overwrite.isChecked(); self.overwrite.setChecked(False)
        self.submit('download', local_path=local,
                    remote_path=posixpath.join(self.path.text(), data['name']), overwrite=overwrite)

    def cancel_operation(self):
        if self.pending:
            self.worker.cancel_file(self.pending)
            self.status.setText('正在取消并清理临时文件；提交结果不确定时会单独提示')

    def poll(self):
        value = self.worker.file_progress()
        if value.get('id') != self.pending:
            return
        phase = value.get('phase')
        total = value.get('total', 0)
        self.progress.setRange(0, 1000 if total else 0)
        if total:
            self.progress.setValue(min(1000, int(value.get('current', 0) * 1000 / total)))
        labels = dict(starting='连接SFTP', transferring='传输', verifying='回读校验', committing='提交')
        if phase in labels:
            self.status.setText(f"{labels[phase]} · {value.get('current',0)} / {total} 字节")

    @Slot(dict)
    def operation_finished(self, event):
        if event.get('id') != self.pending:
            return
        self.pending = None
        self.set_busy(False)
        self.progress.setRange(0, 1000)
        if event['status'] == 'success':
            result = event['result']
            if event['action'] == 'list':
                self.path.setText(result['path'])
                self.tree.clear()
                for entry in sorted(result['entries'], key=lambda e:(e['kind'] != 'directory',e['name'])):
                    try:
                        date = datetime.fromtimestamp(entry['mtime'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if entry['mtime'] is not None else '—'
                    except (ValueError, OSError, OverflowError):
                        date = '—'
                    kind = dict(file='文件', directory='目录', link='链接', other='其他').get(entry['kind'], entry['kind'])
                    item = QTreeWidgetItem([entry['name'], kind, str(entry['size']) if entry['size'] is not None else '—', date])
                    item.setData(0, Qt.ItemDataRole.UserRole, entry)
                    self.tree.addTopLevelItem(item)
                self.status.setText(f"{len(result['entries'])} 项" + (' · 已截断：最多2000项/2MiB名称，请使用明确路径' if result['truncated'] else ''))
                self.tree.resizeColumnToContents(0)
            else:
                self.result_text.setText(f"上次传输完成 {result['size']} 字节 · SHA-256 {result['sha256']}")
                self.status.setText('文件已提交')
                if self.isVisible():
                    self.refresh_directory()
            self.progress.setValue(1000)
        elif event['status'] == 'cancelled':
            self.status.setText('已取消；不会自动重试')
        else:
            self.status.setText(event.get('message', '文件操作失败'))
        if event.get('cleanup_warning'):
            self.result_text.setText('临时文件或SFTP通道未确认清理完成，请检查远端与本地临时文件')

    def closeEvent(self, event):
        self.cancel_operation()
        self.timer.stop()
        event.accept()


class LogDialog(QDialog):
    def __init__(self, worker, label, encoding='utf-8', parent=None):
        super().__init__(parent)
        self.worker, self.encoding = worker, encoding
        self.setWindowTitle('会话日志 · ' + label); self.resize(650, 310)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label('显式开启本地日志；远端输出也可能包含敏感数据。关闭此窗口会停止日志。'))
        row = QHBoxLayout(); layout.addLayout(row)
        self.path = QLineEdit(); self.path.setPlaceholderText('选择新的JSONL文件，已存在的文件不会被覆盖')
        browse = QPushButton('选择文件'); browse.clicked.connect(self.choose_path)
        row.addWidget(self.path, 1); row.addWidget(browse)
        row = QHBoxLayout(); layout.addLayout(row)
        self.mode = QComboBox(); self.mode.addItem('接收文本分块 JSONL', 'text'); self.mode.addItem('原始字节 base64 JSONL', 'raw')
        self.size = QComboBox()
        for mb in (10, 50, 100): self.size.addItem(f'单文件{mb}MiB', mb * 1024 * 1024)
        self.files = QSpinBox(); self.files.setRange(1, 20); self.files.setValue(5); self.files.setSuffix('段上限')
        for widget in (self.mode, self.size, self.files): row.addWidget(widget)
        self.tx = QCheckBox('同时记录发送内容（可能包含口令）'); layout.addWidget(self.tx)
        row = QHBoxLayout(); layout.addLayout(row)
        self.start_button = QPushButton('开始'); self.start_button.clicked.connect(self.start_log)
        self.pause_button = QPushButton('暂停 / 继续'); self.pause_button.clicked.connect(self.pause_log)
        self.stop_button = QPushButton('停止并关闭文件'); self.stop_button.clicked.connect(self.stop_log)
        for widget in (self.start_button, self.pause_button, self.stop_button): row.addWidget(widget)
        self.status = plain_label('默认不记录发送内容；暂停/继续保留同一文件，达到段数上限会停止日志。')
        layout.addWidget(self.status)
        self.timer = QTimer(self); self.timer.setInterval(150); self.timer.timeout.connect(self.poll)

    def showEvent(self, event):
        super().showEvent(event); self.timer.start(); self.poll()

    def choose_path(self):
        path, _ = QFileDialog.getSaveFileName(self, '选择新的日志文件', '',
            'JSONL (*.jsonl)', options=QFileDialog.Option.DontConfirmOverwrite)
        if path: self.path.setText(path)

    def start_log(self):
        if not self.path.text():
            self.status.setText('请先选择新的日志文件'); return
        try:
            ok = self.worker.start_log(self.path.text(), mode=self.mode.currentData(), encoding=self.encoding,
                capture_tx=self.tx.isChecked(), max_bytes=self.size.currentData(), max_files=self.files.value())
        except (ValueError, OSError):
            ok = False
        if not ok: self.status.setText('会话未连接或上一个日志尚未关闭')
        self.poll()

    def pause_log(self):
        if self.worker.journal:
            self.worker.journal.pause(not self.worker.journal.snapshot()['paused'])
            self.poll()

    def stop_log(self):
        if self.worker.journal: self.worker.journal.close()
        self.poll()

    def poll(self):
        journal = self.worker.journal
        value = journal.snapshot() if journal else None
        busy = bool(value and value['alive'])
        self.start_button.setEnabled(not busy and self.worker.status == 'Connected')
        for widget in (self.path, self.mode, self.tx, self.size, self.files): widget.setEnabled(not busy)
        self.pause_button.setEnabled(busy and value['state'] in ('opening','running'))
        self.stop_button.setEnabled(busy)
        if value:
            state = dict(opening='准备', running='记录中', closing='关闭中', closed='已停止', error='错误').get(value['state'], value['state'])
            self.status.setText(value['error'] or f"{state}{' · 暂停' if value['paused'] else ''} · {value['written']} 字节 · {value['files']} 段 · 队列 {value['queued']} 字节")

    def closeEvent(self, event):
        self.stop_log(); self.timer.stop(); event.accept()


class HexDialog(QDialog):
    def __init__(self, worker, label, parent=None):
        super().__init__(parent)
        self.worker = worker; self.after = 0
        self.setWindowTitle('串口 Hex · ' + label); self.resize(920, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label('原始字节观察，不解码或执行转义。最多保留32KiB/256条记录；TX可能包含口令。'))
        self.view = QPlainTextEdit(); self.view.setReadOnly(True); self.view.setMaximumBlockCount(3000)
        self.view.setFont(terminal_font(size=10))
        layout.addWidget(self.view, 1)
        row = QHBoxLayout(); layout.addLayout(row)
        self.tx = QCheckBox('采集TX'); self.tx.toggled.connect(self.configure)
        clear = QPushButton('清空缓冲'); clear.clicked.connect(self.clear)
        row.addWidget(self.tx); row.addWidget(clear)
        row = QHBoxLayout(); layout.addLayout(row)
        self.input = QLineEdit(); self.input.setMaxLength(12288); self.input.setPlaceholderText('00 FF 1B 0D 0A · 原始发送，不自动追加换行，最多4096字节')
        self.send_button = QPushButton('发送Hex'); self.send_button.clicked.connect(self.send_hex)
        row.addWidget(self.input, 1); row.addWidget(self.send_button)
        self.status = plain_label(); layout.addWidget(self.status)
        self.result_text = plain_label(); layout.addWidget(self.result_text)
        self.timer = QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self.poll)
        worker.state.connect(self.connection_state)

    def showEvent(self, event):
        super().showEvent(event); self.configure(); self.timer.start(); self.poll()

    def configure(self, *_):
        self.worker.trace.configure(True, self.tx.isChecked())

    @Slot(str)
    def connection_state(self, _):
        self.send_button.setEnabled(self.worker.status == 'Connected' and not self.worker.stop_event.is_set())

    def clear(self):
        self.after = self.worker.trace.clear()
        self.view.clear()

    def poll(self):
        value = self.worker.trace.snapshot(self.after)
        records = value['records']
        if records:
            self.view.appendPlainText('\n'.join(format_record(record) for record in records))
            self.after = records[-1]['id']
        self.status.setText(f"缓冲 {value['bytes']} 字节 · 累计丢弃旧数据 {value['dropped']} 字节 · TX表示本地写入报告，不代表设备执行确认")
        self.connection_state('')

    def send_hex(self):
        try:
            data = parse_hex(self.input.text())
        except ValueError as exc:
            self.result_text.setText(str(exc)); return
        if not self.worker.send(data):
            self.result_text.setText('会话未连接或发送缓冲已满，没有自动重试')
        else:
            self.result_text.setText(f'{len(data)} 字节已入发送队列；未追加换行')

    def closeEvent(self, event):
        self.worker.trace.configure(False); self.timer.stop(); event.accept()


class ForwardDialog(QDialog):
    def __init__(self, worker, label, parent=None):
        super().__init__(parent)
        self.worker = worker; self.pending = None
        self.setWindowTitle('SSH 隧道 · ' + label); self.resize(820, 430)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label('监听请求固定为127.0.0.1。关闭此窗口不停止监听；断开SSH会话会释放转发。'))
        row = QHBoxLayout(); layout.addLayout(row)
        self.kind = QComboBox()
        for text, value in [('本地转发 L','local'),('远程转发 R','remote'),('本地SOCKS代理','socks')]:
            self.kind.addItem(text,value)
        self.listen = QSpinBox(); self.listen.setRange(0,65535); self.listen.setSpecialValueText('自动分配监听端口')
        self.host = QLineEdit('127.0.0.1'); self.host.setPlaceholderText('目标主机')
        self.port = QSpinBox(); self.port.setRange(1,65535); self.port.setValue(22)
        self.start_button = QPushButton('建立监听'); self.start_button.clicked.connect(self.start_forward)
        for widget in (self.kind,self.listen,self.host,self.port,self.start_button):row.addWidget(widget)
        self.kind.currentIndexChanged.connect(self.update_controls)
        self.tree = QTreeWidget(); self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels(['类型','监听位置','目标','状态'])
        layout.addWidget(self.tree,1)
        self.stop_button = QPushButton('停止选中监听（已有连接可能继续）')
        self.stop_button.clicked.connect(self.stop_forward);layout.addWidget(self.stop_button)
        self.status = plain_label('L：目标从SSH服务端访问；R：目标从本机访问；SOCKS：经SSH服务端访问。')
        layout.addWidget(self.status)
        self.timer = QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.refresh)
        worker.forward_result.connect(self.finished_request)
        worker.state.connect(self.connection_state)
        self.update_controls()

    def showEvent(self,event):
        super().showEvent(event);self.timer.start();self.refresh()

    @Slot(str)
    def connection_state(self,_):
        self.update_controls()

    def update_controls(self,*_):
        connected = self.worker.status=='Connected' and not self.worker.stop_event.is_set()
        ready = connected and not self.pending
        for widget in (self.kind,self.listen,self.start_button,self.stop_button):widget.setEnabled(ready)
        for widget in (self.host,self.port):widget.setEnabled(ready and self.kind.currentData()!='socks')

    def start_forward(self):
        try:
            identifier = self.worker.submit_forward('start',kind=self.kind.currentData(),
                listen_port=self.listen.value(),destination_host=self.host.text().strip(),
                destination_port=self.port.value())
        except ValueError:
            self.status.setText('转发参数无效');return
        if not identifier:
            self.status.setText('会话不可用或请求队列已满');return
        self.pending=identifier;self.update_controls();self.status.setText('正在建立监听…')

    def stop_forward(self):
        item=self.tree.currentItem()
        identifier=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        if identifier:
            self.pending=self.worker.submit_forward('stop',id=identifier)
            self.update_controls()

    def refresh(self):
        selected=self.tree.currentItem()
        chosen=selected.data(0,Qt.ItemDataRole.UserRole) if selected else None
        self.tree.clear()
        for item in self.worker.forwards():
            target='按SOCKS请求选择' if item['kind']=='socks' else f"{item['destination_host']}:{item['destination_port']}"
            location=('远端 ' if item['kind']=='remote' else '本机 ')+f"{item['listen_host']}:{item['listen_port']}"
            state = dict(listening='正在监听', unknown='状态未确认').get(item['state'], item['state'])
            row=QTreeWidgetItem([item['kind'],location,target,state])
            row.setData(0,Qt.ItemDataRole.UserRole,item['id']);self.tree.addTopLevelItem(row)
            if item['id']==chosen:self.tree.setCurrentItem(row)
        self.update_controls()

    @Slot(dict)
    def finished_request(self,event):
        if event.get('id')!=self.pending:return
        self.pending=None
        self.status.setText('监听操作完成' if event['status']=='success' else event.get('message','已取消'))
        self.refresh()

    def closeEvent(self,event):
        self.timer.stop();event.accept()
