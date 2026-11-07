"""Explicit targets, editable previews, saved commands and cancellable flows."""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (QDockWidget, QWidget, QHBoxLayout, QVBoxLayout,
    QPlainTextEdit, QLabel, QTreeWidget, QTreeWidgetItem, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QTabWidget, QDialog, QDialogButtonBox,
    QInputDialog, QMessageBox, QFileDialog)

from .commands import load_library, save_library, parse_flow
from .keyboard import prepare_paste
from .reports import atomic_json
from .appearance import terminal_font


def preview(text, names, parent, *, flow=False):
    dialog=QDialog(parent);dialog.setWindowTitle('确认流程' if flow else '确认发送命令');dialog.resize(700,480)
    layout=QVBoxLayout(dialog)
    targets=QLabel('固定目标：'+' · '.join(names));targets.setTextFormat(Qt.TextFormat.PlainText)
    targets.setWordWrap(True);layout.addWidget(targets)
    layout.addWidget(QLabel('检查或编辑内容。发送后无法撤回；不会自动重试。'))
    edit=QPlainTextEdit(text);edit.setFont(terminal_font(size=10));layout.addWidget(edit,1)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText('运行流程' if flow else '发送')
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
    buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
    result=edit.toPlainText() if dialog.exec()==QDialog.DialogCode.Accepted else None
    edit.clear();dialog.deleteLater();return result


class WorkflowPanel(QDockWidget):
    def __init__(self, owner):
        super().__init__('命令与流程',owner)
        self.owner=owner;self.setObjectName('workflowDock');self.pending={};self.connected_workers=set()
        self.path=owner.profile_path.with_name('commands.json');self.library_error=False
        try:self.library=load_library(self.path)
        except (OSError,ValueError,KeyError):self.library={};self.library_error=True
        self.refreshed=False;self.history=[]
        widget=QWidget();self.setWidget(widget);outer=QVBoxLayout(widget)
        outer.setContentsMargins(5,5,5,5);row=QHBoxLayout();outer.addLayout(row,1)
        left=QVBoxLayout();row.addLayout(left)
        self.filter=QLineEdit();self.filter.setPlaceholderText('筛选保存的命令');self.filter.textChanged.connect(self.render_library)
        left.addWidget(self.filter)
        self.library_tree=QTreeWidget();self.library_tree.setHeaderLabels(['保存的命令'])
        self.library_tree.setFixedWidth(205);self.library_tree.setRootIsDecorated(False)
        self.library_tree.itemDoubleClicked.connect(self.load_selected);left.addWidget(self.library_tree,1)
        buttons=QHBoxLayout();left.addLayout(buttons)
        save=QPushButton('保存…');save.clicked.connect(self.save_current)
        delete=QPushButton('删除');delete.clicked.connect(self.delete_selected)
        buttons.addWidget(save);buttons.addWidget(delete)
        self.pin=QCheckBox('显示在按钮栏');left.addWidget(self.pin)
        self.tabs=QTabWidget();row.addWidget(self.tabs,1)
        command=QWidget();layout=QVBoxLayout(command);layout.setContentsMargins(2,2,2,2)
        self.edit=QPlainTextEdit();self.edit.setFont(terminal_font(size=10));self.edit.setPlaceholderText('输入命令；发送前会显示可编辑预览')
        layout.addWidget(self.edit,1)
        controls=QHBoxLayout();layout.addLayout(controls)
        self.history_box=QComboBox();self.history_box.addItem('本次窗口的发送历史')
        self.history_box.activated.connect(self.load_history)
        self.newline=QCheckBox('末尾加回车');self.newline.setChecked(True)
        send=QPushButton('预览并发送…');send.clicked.connect(self.send_commands)
        controls.addWidget(self.history_box,1);controls.addWidget(self.newline);controls.addWidget(send)
        self.tabs.addTab(command,'命令窗口')
        flow=QWidget();layout=QVBoxLayout(flow);layout.setContentsMargins(2,2,2,2)
        self.flow_edit=QPlainTextEdit();self.flow_edit.setFont(terminal_font(size=10))
        self.flow_edit.setPlaceholderText('{"version":1,"steps":[{"action":"send","text":"show version"},{"action":"wait","patterns":["#"],"timeout":10}]}')
        layout.addWidget(self.flow_edit,1);controls=QHBoxLayout();layout.addLayout(controls)
        load=QPushButton('导入JSON…');load.clicked.connect(self.import_flow)
        export=QPushButton('导出JSON…');export.clicked.connect(self.export_flow)
        run=QPushButton('预览并运行…');run.clicked.connect(self.start_flows)
        cancel=QPushButton('取消本窗口流程');cancel.clicked.connect(self.cancel_flows)
        for item in (load,export,run,cancel):controls.addWidget(item)
        self.tabs.addTab(flow,'等待 / 发送流程')
        right=QVBoxLayout();row.addLayout(right)
        right.addWidget(QLabel('明确勾选发送目标'))
        self.targets=QTreeWidget();self.targets.setHeaderLabels(['会话','协议']);self.targets.setFixedWidth(205)
        self.targets.setRootIsDecorated(False);right.addWidget(self.targets,1)
        refresh=QPushButton('刷新会话列表');refresh.clicked.connect(self.refresh_targets);right.addWidget(refresh)
        note=QLabel('保存的命令和导出流程为本机明文文件，请勿加入密码或令牌。历史只保留在内存。')
        note.setWordWrap(True);outer.addWidget(note)
        self.status=QLabel();self.status.setTextFormat(Qt.TextFormat.PlainText);outer.addWidget(self.status)
        self.results=QPlainTextEdit();self.results.setReadOnly(True);self.results.setMaximumHeight(105)
        self.results.setMaximumBlockCount(2000);outer.addWidget(self.results)
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.poll)
        self.render_library();self.refresh_targets()
        if self.library_error:self.status.setText('命令文件损坏，保存已禁用以保护原文件')

    def showEvent(self,event):
        super().showEvent(event);self.timer.start()

    def closeEvent(self,event):
        self.cancel_flows();self.timer.stop();event.accept()

    def selected_targets(self):
        result=[]
        for index in range(self.targets.topLevelItemCount()):
            item=self.targets.topLevelItem(index)
            if item.checkState(0)!=Qt.CheckState.Checked:continue
            identifier=item.data(0,Qt.ItemDataRole.UserRole)
            for worker,terminal in self.owner.sessions.items():
                if worker.session_id==identifier:result.append((worker,terminal.session_label,terminal.encoding));break
        return result

    def refresh_targets(self):
        selected={worker.session_id for worker,_,_ in self.selected_targets()}
        current=self.owner.tabs.currentWidget();self.targets.clear()
        for worker,terminal in self.owner.sessions.items():
            if worker.status!='Connected' or worker.stop_event.is_set():continue
            item=QTreeWidgetItem([terminal.session_label,worker.mode]);item.setData(0,Qt.ItemDataRole.UserRole,worker.session_id)
            checked=worker.session_id in selected if self.refreshed else terminal is current
            item.setCheckState(0,Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.targets.addTopLevelItem(item)
            if worker not in self.connected_workers:
                worker.flow_result.connect(self.finished_flow);self.connected_workers.add(worker)
        self.refreshed=True;self.targets.resizeColumnToContents(0)

    def append_result(self,text):
        self.results.appendPlainText(text)
        value=self.results.toPlainText()
        if len(value)>131072:self.results.setPlainText('（只显示最近128Ki字符）\n'+value[-131072:])

    def remove_worker(self,worker):
        self.pending.pop(worker,None)
        if worker in self.connected_workers:
            try:worker.flow_result.disconnect(self.finished_flow)
            except (RuntimeError,TypeError):pass
            self.connected_workers.discard(worker)
        self.refresh_targets()

    def send_commands(self,targets=None,text=None):
        if isinstance(targets,bool):targets=None
        targets=list(targets) if targets is not None else self.selected_targets()
        text=self.edit.toPlainText() if text is None else text
        try:
            if not targets or not text.strip() or len(text)>4096:raise ValueError()
            prepare_paste(text)
            if self.newline.isChecked() and not text.endswith(('\r','\n')):text+='\n'
            accepted=preview(text,[name for _,name,_ in targets],self)
            if accepted is None:return
            if not accepted.strip() or len(accepted)>4096:raise ValueError()
            payloads=[prepare_paste(accepted,encoding=encoding) for _,_,encoding in targets]
        except (ValueError,UnicodeError):self.status.setText('请选择目标，检查内容长度、编码和控制字符');return
        for (worker,name,_),payload in zip(targets,payloads):
            queued=worker.send(payload)
            self.append_result(name+('：已入发送队列；执行结果见终端' if queued else '：拒绝发送，连接、流程或缓冲状态已变化'))
        self.history=[accepted]+[item for item in self.history if item!=accepted][:49]
        self.history_box.clear();self.history_box.addItem('本次窗口的发送历史')
        for item in self.history:self.history_box.addItem(item.splitlines()[0][:60],item)
        self.status.setText('每个目标的入队结果已列出；不会自动重试')

    def load_history(self,index):
        if index:self.edit.setPlainText(self.history_box.itemData(index))

    def render_library(self):
        self.library_tree.clear();query=self.filter.text().casefold()
        for name,item in sorted(self.library.items()):
            if query and query not in (name+' '+item['text']).casefold():continue
            row=QTreeWidgetItem([name]);row.setData(0,Qt.ItemDataRole.UserRole,name);self.library_tree.addTopLevelItem(row)

    def load_selected(self,item,_column):
        name=item.data(0,Qt.ItemDataRole.UserRole);definition=self.library.get(name)
        if definition:self.edit.setPlainText(definition['text']);self.pin.setChecked(definition.get('pinned',False));self.tabs.setCurrentIndex(0)

    def save_current(self):
        if self.library_error:self.status.setText('请先修复或备份损坏的命令文件');return
        name,accepted=QInputDialog.getText(self,'保存命令','名称（内容以明文保存）：')
        if not accepted:return
        name=name.strip()
        if name in self.library and QMessageBox.question(self,'替换命令','覆盖同名命令？')!=QMessageBox.StandardButton.Yes:return
        updated=dict(self.library);updated[name]=dict(text=self.edit.toPlainText(),pinned=self.pin.isChecked())
        self.persist_library(updated)

    def delete_selected(self):
        item=self.library_tree.currentItem()
        if not item:return
        name=item.data(0,Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self,'删除命令','删除选中的保存命令？')!=QMessageBox.StandardButton.Yes:return
        updated=dict(self.library);updated.pop(name,None);self.persist_library(updated)

    def persist_library(self,updated):
        if self.library_error:return
        try:save_library(self.path,updated)
        except (OSError,ValueError):self.status.setText('保存失败，原命令文件已保留');return
        self.library=updated;self.render_library();self.owner.refresh_command_buttons()
        self.status.setText('命令库已保存；没有发送到任何会话')

    def start_flows(self):
        targets=list(self.selected_targets())
        if not targets:self.status.setText('请明确选择流程目标');return
        try:
            steps=parse_flow(self.flow_edit.toPlainText())
            canonical=json.dumps(dict(version=1,steps=steps),ensure_ascii=False,indent=2)
            accepted=preview(canonical,[name for _,name,_ in targets],self,flow=True)
            if accepted is None:return
            steps=parse_flow(accepted)
        except (ValueError,KeyError):self.status.setText('流程JSON无效：仅支持有界send / wait / delay');return
        for worker,name,encoding in targets:
            try:identifier=worker.submit_flow(steps,encoding)
            except (ValueError,UnicodeError):identifier=None
            if identifier:self.pending[worker]=(identifier,name)
            self.append_result(name+('：流程已启动' if identifier else '：流程未启动，连接、编码或发送队列不可用'))
        self.status.setText('流程期间暂停手动输入；Ctrl+C可取消并发送中断，匹配提示不代表命令执行成功')

    def cancel_flows(self):
        for worker,(identifier,_) in list(self.pending.items()):
            try:worker.cancel_flow(identifier)
            except RuntimeError:self.pending.pop(worker,None)

    @Slot(dict)
    def finished_flow(self,event):
        worker=self.sender();pending=self.pending.get(worker)
        if not pending or pending[0]!=event['id']:return
        _,name=self.pending.pop(worker)
        label=dict(success='流程完成（入队 / 提示匹配）',cancelled='已取消；已发送内容无法撤回',error='流程停止')
        self.append_result(name+'：'+label.get(event['status'],event['status']))
        if event.get('message'):self.append_result(event['message'])
        for match in event.get('result',{}).get('captures',[]):
            self.append_result(f"步骤{match['step']} 命中候选{match['match_index']}：\n"+match['text'])
        if not self.pending:self.status.setText('流程已结束；结果见下方，已发送内容无法撤回')

    def poll(self):
        notes=[]
        for worker,(_,name) in list(self.pending.items()):
            value=worker.flow_progress();notes.append(f"{name} {value.get('step',0)}/{value.get('total',0)}")
        if notes:self.status.setText(' · '.join(notes))

    def import_flow(self):
        path,_=QFileDialog.getOpenFileName(self,'导入流程','','JSON (*.json)')
        if not path:return
        try:
            if Path(path).stat().st_size>262144:raise ValueError()
            steps=parse_flow(Path(path).read_text(encoding='utf-8'))
            self.flow_edit.setPlainText(json.dumps(dict(version=1,steps=steps),ensure_ascii=False,indent=2))
        except (OSError,ValueError,KeyError):self.status.setText('流程文件无效或超过256KiB')

    def export_flow(self):
        try:steps=parse_flow(self.flow_edit.toPlainText())
        except (ValueError,KeyError):self.status.setText('请先填写有效流程');return
        path,_=QFileDialog.getSaveFileName(self,'导出流程','','JSON (*.json)')
        if not path:return
        try:atomic_json(path,dict(version=1,steps=steps))
        except OSError:self.status.setText('导出失败，目标文件未确认保存')
