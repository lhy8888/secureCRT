"""Bound-session text transfer, serial outputs and input policy controls."""
from pathlib import Path

from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,
    QComboBox,QPushButton,QPlainTextEdit,QTreeWidget,QTreeWidgetItem,QTabWidget,QSpinBox,QMessageBox,QFileDialog)

from .input_policy import DEFAULT_INPUT,InputPolicy,display_text
from .terminal_model import ENCODINGS
from .text_files import prepare_file,MAX_TEXT_BYTES
from .ssh_dialogs import plain

NEWLINES=(('保持原样','keep'),('CR','cr'),('LF','lf'),('CRLF','crlf'))


def choices(items,current):
    combo=QComboBox()
    for label,value in items:combo.addItem(label,value)
    combo.setCurrentIndex(max(0,combo.findData(current)));return combo


class InputPolicyEditor(QWidget):
    def __init__(self,values,parent=None):
        super().__init__(parent);form=QFormLayout(self);self.fields={}
        for field,title in (('send_char_delay_ms','字节间隔（毫秒）'),('send_line_delay_ms','行间隔（毫秒）')):
            edit=QLineEdit(values.get(field,DEFAULT_INPUT[field]));self.fields[field]=edit;form.addRow(title,edit)
        for field,title,items in (
            ('paste_newline','粘贴换行',[('自动（普通CR / bracketed LF）','auto'),*NEWLINES]),
            ('paste_quote','粘贴引用',[('不加引用','none'),('POSIX单引号','posix'),('PowerShell单引号','powershell')]),
            ('alt_meta','Alt Meta',[('ESC前缀 / xterm修饰键','escape'),('只发送布局产生的文本','text')]),
            ('remote_clear_history','远端清历史',[('允许ED3 / RIS清历史','allow'),('保留历史，仍允许清屏','preserve')])):
            combo=choices(items,values.get(field,DEFAULT_INPUT[field]));self.fields[field]=combo;form.addRow(title,combo)
        self.status=plain('字节间隔0–1000ms，行间隔0–30000ms，CRLF按一行。只节流输入，协议应答优先；ASCII可逐行等待字面提示。AltGr和输入法提交保留文本。')
        form.addRow(self.status)

    def values(self):
        return InputPolicy.parse({key:widget.currentData() if isinstance(widget,QComboBox) else widget.text()
                                  for key,widget in self.fields.items()}).values


class TextFilesDialog(QDialog):
    def __init__(self,worker,label,encoding,parent):
        super().__init__(parent);self.worker=worker;self.encoding=encoding;self.payload=None;self.pending=None
        self.setWindowTitle('ASCII / 文本文件收发 · '+label);self.resize(800,640)
        layout=QVBoxLayout(self);layout.addWidget(plain('固定绑定当前会话；文本发送会占用手动输入与流程。取消只停止未发送数据，不自动重试；文件内容可能执行远端命令，请先预览。'))
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1);send=QWidget();self.tabs.addTab(send,'发送文本');form=QFormLayout(send)
        self.path=QLineEdit();row=QHBoxLayout();row.addWidget(self.path,1);choose=QPushButton('选择文件…');self.source_button=choose;row.addWidget(choose);form.addRow('源文件：',row);choose.clicked.connect(self.choose_source)
        self.source=choices([(s,s) for s in ('utf-8-sig',*ENCODINGS,'ascii','utf-16')],'utf-8-sig')
        self.target=choices([(s,s) for s in (*ENCODINGS,'ascii')],encoding);self.newline=choices(NEWLINES,'cr')
        form.addRow('文件编码：',self.source);form.addRow('发送编码：',self.target);form.addRow('发送换行：',self.newline)
        self.prompt=QLineEdit();self.prompt.setPlaceholderText('可选；每行写完后等待新收到的字面提示，不用正则')
        self.timeout=QSpinBox();self.timeout.setRange(1,120);self.timeout.setValue(30);form.addRow('逐行提示：',self.prompt);form.addRow('每行等待秒数：',self.timeout)
        row=QHBoxLayout();self.load_button=QPushButton('读取并冻结预览');self.send_button=QPushButton('发送预览内容');self.cancel_button=QPushButton('取消发送')
        for button in (self.load_button,self.send_button,self.cancel_button):row.addWidget(button)
        form.addRow(row);self.preview=QPlainTextEdit();self.preview.setReadOnly(True);form.addRow(self.preview)
        self.load_button.clicked.connect(self.load);self.send_button.clicked.connect(self.send);self.cancel_button.clicked.connect(self.cancel)
        for field in (self.path,self.source,self.target,self.newline):
            (field.textChanged if isinstance(field,QLineEdit) else field.currentIndexChanged).connect(self.invalidate)
        receive=QWidget();self.tabs.addTab(receive,'接收为文本');form=QFormLayout(receive)
        self.receive_path=QLineEdit();row=QHBoxLayout();row.addWidget(self.receive_path,1);choose=QPushButton('新文件…');self.destination_button=choose;row.addWidget(choose);choose.clicked.connect(self.choose_destination);form.addRow('保存为：',row)
        self.receive_encoding=choices([(s,s) for s in (*ENCODINGS,'ascii')],'utf-8');form.addRow('文件编码：',self.receive_encoding)
        self.receive_newline=choices(NEWLINES,'keep');form.addRow('文件换行：',self.receive_newline)
        form.addRow(plain('只保存开始后的RX文本，过滤终端控制序列；按当前终端编码严格解码。已有文件不覆盖，最多8MiB。手动停止只是结束本地采集，不表示对端传输完整；错误/断开可能留下部分文件。'))
        row=QHBoxLayout();self.receive_start=QPushButton('开始接收');self.receive_stop=QPushButton('停止并落盘');row.addWidget(self.receive_start);row.addWidget(self.receive_stop);form.addRow(row)
        self.receive_start.clicked.connect(self.start_capture);self.receive_stop.clicked.connect(self.worker.stop_text_capture)
        self.receive_status=plain('未开始');form.addRow(self.receive_status)
        self.status=plain('最多1MiB输入/输出，每行64KiB；不隐式追加末尾换行。全文件最长运行1小时。');layout.addWidget(self.status)
        self.worker.flow_result.connect(self.finished_request);self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.poll);self.timer.start();self.poll()

    def invalidate(self,*_):
        self.payload=None;self.preview.clear();self.status.setText('设置已变化，请重新读取并核对预览。');self.poll()

    def choose_source(self):
        path,_=QFileDialog.getOpenFileName(self,'选择文本文件')
        if path:self.path.setText(path);self.load()

    def choose_destination(self):
        from PySide6.QtWidgets import QFileDialog
        path,_=QFileDialog.getSaveFileName(self,'选择新的接收文件')
        if path:self.receive_path.setText(path)

    def load(self):
        try:
            with Path(self.path.text()).open('rb') as stream:raw=stream.read(MAX_TEXT_BYTES+1)
            self.payload=prepare_file(raw,self.source.currentData(),self.target.currentData(),self.newline.currentData())
            self.preview.setPlainText(display_text(self.payload[:8192].decode(self.target.currentData(),errors='replace')))
            self.status.setText(f'冻结{len(self.payload)}字节；预览最多8192字节，发送不再读取源文件。请核对编码、换行和内容。')
        except (OSError,ValueError,UnicodeError):self.payload=None;self.preview.clear();self.status.setText('读取失败：检查大小、编码、控制字符和行长。')
        self.poll()

    def send(self):
        if self.payload is None or self.pending:return
        try:self.pending=self.worker.submit_text(self.payload,encoding=self.target.currentData(),prompt=self.prompt.text(),timeout=self.timeout.value())
        except ValueError:self.status.setText('文本或提示无效，没有发送。');return
        self.status.setText('发送中；已发送内容不能撤回。' if self.pending else '当前会话未连接、输入已锁定或存在发送任务。');self.poll()

    def cancel(self):
        if self.pending:self.worker.cancel_flow(self.pending)

    def finished_request(self,event):
        if event.get('id')!=self.pending:return
        self.pending=None
        self.status.setText(str(event['status'])+'；本机确认写入至少'+str(event.get('bytes_sent',event.get('result',{}).get('bytes_sent',0)))+
            '字节；'+('存在结果待确认的写入；' if event.get('write_uncertain') else '')+'不自动重试。')
        self.poll()

    def start_capture(self):
        if not self.receive_path.text().strip():self.status.setText('选择新的接收文件。');return
        try:accepted=self.worker.start_text_capture(self.receive_path.text(),source_encoding=self.encoding,
            output_encoding=self.receive_encoding.currentData(),newline=self.receive_newline.currentData())
        except ValueError:accepted=False
        self.status.setText('正在打开接收文件…' if accepted else '会话不可用或接收正在运行。');self.poll()

    def poll(self):
        connected=self.worker.status=='Connected' and not self.worker.stop_event.is_set() and self.worker.interactive
        self.send_button.setEnabled(connected and self.payload is not None and not self.pending)
        self.load_button.setEnabled(not self.pending);self.cancel_button.setEnabled(bool(self.pending))
        for widget in (self.path,self.source_button,self.source,self.target,self.newline,self.prompt,self.timeout):widget.setEnabled(not self.pending)
        if self.pending:
            progress=self.worker.flow_progress();self.status.setText(f"发送进度{progress.get('current',0)}/{progress.get('total',0)}字节；{progress.get('phase','')}，可取消")
        capture=self.worker.text_capture;snapshot=capture.snapshot() if capture else {};alive=snapshot.get('alive',False)
        self.receive_start.setEnabled(connected and not alive);self.receive_stop.setEnabled(alive)
        for widget in (self.receive_path,self.destination_button,self.receive_encoding,self.receive_newline):widget.setEnabled(not alive)
        if snapshot:self.receive_status.setText(f"{snapshot['state']}；写入{snapshot['written']}字节；"+snapshot['error'])

    def closeEvent(self,event):self.cancel();self.worker.stop_text_capture();self.timer.stop();event.accept()
    def showEvent(self,event):super().showEvent(event);self.timer.start();self.poll()


class SerialLinesDialog(QDialog):
    def __init__(self,worker,label,parent):
        super().__init__(parent);self.worker=worker;self.pending=None;self.setWindowTitle('串口线路 · '+label);self.resize(650,420)
        layout=QVBoxLayout(self);layout.addWidget(plain('DTR/RTS改变可能复位设备。显示的是驱动报告的输入/输出设定，不能代替实体电压测试；RTS/CTS或DSR/DTR流控占用的输出不能手动改动。'))
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['线路','驱动报告']);self.tree.setColumnWidth(0,200);layout.addWidget(self.tree,1)
        row=QHBoxLayout();self.line=choices([('DTR','dtr'),('RTS','rts')],'dtr');self.value=choices([('设为有效','true'),('设为无效','false')],'true')
        self.apply=QPushButton('确认后设置…');row.addWidget(self.line);row.addWidget(self.value);row.addWidget(self.apply);layout.addLayout(row)
        self.apply.clicked.connect(self.change);self.status=plain('未知状态不会显示为正常。');layout.addWidget(self.status)
        self.worker.control_result.connect(self.result_event);self.timer=QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.poll);self.timer.start();self.poll()

    def change(self):
        line=self.line.currentData();value=self.value.currentData()=='true'
        box=QMessageBox(QMessageBox.Icon.Warning,'确认串口输出变化',f'{line.upper()} → {value}；可能复位设备。',
                        QMessageBox.StandardButton.Ok|QMessageBox.StandardButton.Cancel,self)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec()!=QMessageBox.StandardButton.Ok:return
        self.pending=self.worker.set_serial_line(line,value);self.poll()

    def result_event(self,event):
        if event.get('id')!=self.pending:return
        self.pending=None;self.status.setText('设置完成，以后续状态为准' if event['status']=='success' else '设置失败或流控占用：'+event.get('code',''));self.poll()

    def poll(self):
        snapshot=self.worker.serial_snapshot();self.tree.clear()
        for name in ('dtr','rts','cts','dsr','ri','cd'):
            value=snapshot.get(name);shown='有效' if value is True else '无效' if value is False else '不支持 / 未知'
            self.tree.addTopLevelItem(QTreeWidgetItem([name.upper()+(' 输出设定' if name in ('dtr','rts') else ' 输入'),shown]))
        flow=snapshot.get('flow_control');line=self.line.currentData();managed=line=='rts' and flow=='rtscts' or line=='dtr' and flow=='dsrdtr'
        self.apply.setEnabled(self.worker.status=='Connected' and not self.worker.stop_event.is_set() and not self.worker.input_locked and not self.pending and not managed)

    def closeEvent(self,event):self.timer.stop();event.accept()
    def showEvent(self,event):super().showEvent(event);self.timer.start();self.poll()
