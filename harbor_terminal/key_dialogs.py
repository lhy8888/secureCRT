"""Explicit host trust reviews and background identity generation."""
from pathlib import Path
import threading

from PySide6.QtCore import Qt,QThread,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,
    QPlainTextEdit,QCheckBox,QComboBox,QPushButton,QTreeWidget,QTreeWidgetItem,
    QDialogButtonBox,QFileDialog,QAbstractItemView)

from . import host_keys
from .key_tools import ALGORITHMS,generate_identity,public_info,GenerationCancelled
from .ssh_dialogs import plain
from .storage import StorageConflict,CommitUncertain


class TrustReview(QDialog):
    def __init__(self,text,parent,*,deleting=False):
        super().__init__(parent);self.setWindowTitle('确认删除主机信任' if deleting else '核对主机公钥指纹');self.resize(850,480)
        layout=QVBoxLayout(self);layout.addWidget(plain('检查固定的主机模式与SHA-256指纹。CA标记信任其签发且主机名/有效期合格的证书；吊销标记会拒绝该密钥。'))
        tree=QTreeWidget();tree.setHeaderLabels(['主机模式 / 别名','标记','公钥格式','SHA-256指纹']);layout.addWidget(tree,1)
        for entry in host_keys.entries(text):tree.addTopLevelItem(QTreeWidgetItem([entry.patterns,entry.marker or '主机',entry.algorithm,entry.fingerprint]))
        for i in range(3):tree.resizeColumnToContents(i)
        self.verified=QCheckBox('我已核实这些删除目标' if deleting else '我已通过独立可信渠道核对这些指纹和信任范围')
        layout.addWidget(self.verified);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.ok=buttons.button(QDialogButtonBox.StandardButton.Ok);self.ok.setText('确认删除' if deleting else '保存信任');self.ok.setEnabled(False)
        self.verified.toggled.connect(self.ok.setEnabled);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def accept(self):
        if self.verified.isChecked():super().accept()


class AddHostKey(QDialog):
    def __init__(self,parent,host=''):
        super().__init__(parent);self.setWindowTitle('添加主机公钥或CA / 吊销项');self.resize(720,420);self.result_text=None
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.pattern=QLineEdit(host);form.addRow('主机模式（可逗号分隔）：',self.pattern)
        self.marker=QComboBox()
        for label,value in (('主机公钥',''),('主机证书CA','@cert-authority'),('吊销密钥','@revoked')):self.marker.addItem(label,value)
        form.addRow('用途：',self.marker)
        layout.addWidget(plain('非22端口用[host]:port。粘贴公钥文本，不能粘贴私钥；程序不主动扫描或自动信任网络主机。'))
        self.public=QPlainTextEdit();self.public.setPlaceholderText('ssh-ed25519 AAAA…');layout.addWidget(self.public,1)
        self.status=plain('');layout.addWidget(self.status)
        self.public.textChanged.connect(self.reject_private_paste)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('预览指纹');buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def reject_private_paste(self):
        first=self.public.toPlainText().strip().splitlines()[:1]
        if first and ('PRIVATE KEY' in first[0] or first[0].startswith('PuTTY-User-Key-File')):
            self.public.clear();self.status.setText('已清除私钥内容，请使用对应的.pub公钥。')

    def accept(self):
        try:self.result_text=host_keys.make_entry(self.pattern.text().strip(),self.public.toPlainText(),self.marker.currentData())
        except (ValueError,TypeError):self.status.setText('主机模式或公钥无效，没有保存。');return
        super().accept()


class HostKeysDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.store=None;self.snapshot=None;self.setWindowTitle('主机密钥管理');self.resize(940,610)
        layout=QVBoxLayout(self);self.path=QLineEdit();self.path.setReadOnly(True);row=QHBoxLayout();row.addWidget(self.path,1)
        choose=QPushButton('选择 / 新建known_hosts…');choose.clicked.connect(self.choose);row.addWidget(choose);layout.addLayout(row)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['主机模式','标记','公钥格式','SHA-256指纹']);self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);layout.addWidget(self.tree,1)
        row=QHBoxLayout();layout.addLayout(row)
        for title,callback in (('添加公钥…',self.add),('导入公钥库…',self.import_file),('删除选中…',self.delete),('导出公钥库…',self.export),('重新载入',self.reload),('用于快速连接',self.use)):
            button=QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        row=QHBoxLayout();self.lookup=QLineEdit();self.lookup.setPlaceholderText('主机 / 别名');self.port=QLineEdit('22');self.port.setMaximumWidth(90)
        lookup=QPushButton('检查本地匹配');lookup.clicked.connect(self.match);row.addWidget(self.lookup,1);row.addWidget(self.port);row.addWidget(lookup);layout.addLayout(row)
        self.status=plain('');layout.addWidget(self.status)
        default=owner.known.text().strip() or str(Path.home()/'.ssh/known_hosts');self.load(default)

    def load(self,path):
        try:store=host_keys.store(path);snapshot=store.read()
        except (ValueError,OSError):self.status.setText('无法读取该公钥库，原文件未改写。');return False
        self.store,self.snapshot=store,snapshot;self.path.setText(str(store.path));self.render();return True

    def render(self):
        self.tree.clear()
        for entry in host_keys.entries(self.snapshot.value):
            item=QTreeWidgetItem([entry.patterns,entry.marker or '主机',entry.algorithm,entry.fingerprint]);item.setData(0,Qt.ItemDataRole.UserRole,entry.line);self.tree.addTopLevelItem(item)
        for i in range(3):self.tree.resizeColumnToContents(i)
        self.status.setText(f'已读取{self.tree.topLevelItemCount()}项；信任变更只在核对后保存。')

    def choose(self):
        path,_=QFileDialog.getSaveFileName(self,'选择或新建OpenSSH known_hosts',self.path.text(),'所有文件 (*)')
        if path:self.load(path)

    def reload(self):
        if self.store:self.load(self.store.path)

    def commit(self,plan,review,*,deleting=False):
        if self.store is None or self.snapshot is None:return False
        store=self.store;revision=self.snapshot.revision;preview=TrustReview(review,self,deleting=deleting)
        try:
            if preview.exec()!=QDialog.DialogCode.Accepted:return False
        finally:preview.deleteLater()
        try:snapshot=store.save(plan,expected_revision=revision)
        except StorageConflict:self.status.setText('公钥库已被其他窗口修改，请重新载入并核对。');return False
        except CommitUncertain:self.status.setText('保存结果待确认，请重新载入核对。');return False
        except (ValueError,OSError):self.status.setText('保存失败；检查文件权限与公钥格式。');return False
        self.store,self.snapshot=store,snapshot;self.render();return True

    def add(self):
        if self.snapshot is None:return
        dialog=AddHostKey(self,self.owner.host.text().strip())
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            incoming=dialog.result_text
        finally:dialog.deleteLater()
        self.commit(host_keys.append_entries(self.snapshot.value,incoming),incoming)

    def import_file(self):
        if self.snapshot is None:return
        path,_=QFileDialog.getOpenFileName(self,'导入已有OpenSSH主机公钥库')
        if not path:return
        try:
            incoming=host_keys.store(path).read().value;plan=host_keys.append_entries(self.snapshot.value,incoming)
        except (ValueError,OSError):self.status.setText('公钥库无效或包含不支持的行，没有保存。');return
        self.commit(plan,incoming)

    def delete(self):
        if self.snapshot is None:return
        selected={item.data(0,Qt.ItemDataRole.UserRole) for item in self.tree.selectedItems()}
        if not selected:self.status.setText('请选择要删除的信任项。');return
        lines=self.snapshot.value.splitlines(keepends=True);review=''.join(lines[i] for i in sorted(selected))
        self.commit(host_keys.remove_entries(self.snapshot.value,selected),review,deleting=True)

    def export(self):
        if self.snapshot is None:return
        path,_=QFileDialog.getSaveFileName(self,'导出主机公钥库','','所有文件 (*)')
        if not path:return
        try:
            if Path(path).resolve()==self.store.path.resolve():raise ValueError()
            if Path(path).exists():raise FileExistsError()
            host_keys.store(path).save(self.snapshot.value,expected_revision=None);self.status.setText('已导出公共信任信息。')
        except (ValueError,OSError,StorageConflict):self.status.setText('导出失败，请选择新的文件名。')

    def match(self):
        if self.snapshot is None:return
        try:
            result=host_keys.match(self.snapshot.value,self.lookup.text().strip(),int(self.port.text()))
            self.status.setText('本地匹配：'+str(result)+'；没有连接网络。')
        except ValueError:self.status.setText('请输入有效主机与端口。')

    def use(self):
        if self.store is not None:self.owner.known.setText(str(self.store.path));self.status.setText('已填入快速连接；没有发起连接。')


class KeyJob(QThread):
    completed=Signal(dict);failed=Signal(str)
    def __init__(self,arguments,*,inspect=False,parent=None):
        super().__init__(parent);self.arguments=arguments;self.inspect=inspect;self.cancel=threading.Event()
    def run(self):
        try:
            result=public_info(**self.arguments) if self.inspect else generate_identity(**self.arguments,cancel=self.cancel)
            self.completed.emit(result)
        except GenerationCancelled:self.failed.emit('已取消，未完成的自有输出已清理。')
        except Exception as exc:self.failed.emit(type(exc).__name__+'：密钥操作失败；不会覆盖现有密钥。')
        finally:self.arguments.clear()


class KeyToolsDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.setWindowTitle('SSH身份密钥工具');self.resize(730,480);self.job=None;self.pending_close=False;self.last_result=None
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.algorithm=QComboBox();self.algorithm.addItems(ALGORITHMS);form.addRow('生成算法：',self.algorithm)
        self.path=QLineEdit();row=QHBoxLayout();row.addWidget(self.path,1);choose=QPushButton('文件…');choose.clicked.connect(self.choose);row.addWidget(choose);form.addRow('私钥路径：',row)
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.EchoMode.Password);form.addRow('本次密钥口令：',self.password)
        self.unencrypted=QCheckBox('明确生成未加密私钥（默认不允许）');layout.addWidget(self.unencrypted)
        layout.addWidget(plain('默认生成bcrypt KDF加密的OpenSSH私钥及.pub公钥。现有文件不覆盖；保存位置必须支持安全的同卷硬链接。Windows文件权限继承目录ACL，不等同DPAPI或凭据库。'))
        row=QHBoxLayout();self.generate=QPushButton('生成新密钥');self.inspect=QPushButton('检查已有私钥指纹');row.addWidget(self.generate);row.addWidget(self.inspect);layout.addLayout(row)
        self.generate.clicked.connect(lambda:self.start(False));self.inspect.clicked.connect(lambda:self.start(True))
        self.output=QPlainTextEdit();self.output.setReadOnly(True);layout.addWidget(self.output,1);self.status=plain('口令只用于当前操作，不写入配置或诊断。');layout.addWidget(self.status)
        close=QPushButton('关闭 / 取消');close.clicked.connect(self.reject);layout.addWidget(close)

    def choose(self):
        path,_=QFileDialog.getSaveFileName(self,'选择新的私钥文件名（或输入已有文件以检查）')
        if path:self.path.setText(path)

    def start(self,inspect):
        if self.job and self.job.isRunning():return
        if not self.path.text().strip():self.status.setText('选择私钥路径。');return
        if not inspect and not self.password.text() and not self.unencrypted.isChecked():self.status.setText('请输入加密口令，或明确选择未加密导出。');return
        if not inspect and self.password.text() and len(self.password.text())<12:self.status.setText('新密钥的加密口令至少12个字符。');return
        arguments=dict(path=self.path.text().strip(),passphrase=self.password.text())
        if not inspect:arguments.update(algorithm=self.algorithm.currentText(),unencrypted=self.unencrypted.isChecked())
        self.password.clear();self.last_result=None;self.pending_close=False
        self.job=KeyJob(arguments,inspect=inspect,parent=self);self.job.completed.connect(self.done_key);self.job.failed.connect(self.status.setText)
        self.job.finished.connect(self.finished_job);self.generate.setEnabled(False);self.inspect.setEnabled(False);self.status.setText('正在处理密钥…');self.job.start()

    def done_key(self,result):
        self.last_result=result;self.output.setPlainText('\n'.join(key+'：'+value for key,value in result.items()));self.status.setText('密钥操作完成；不会自动发送或替换会话身份。')

    def finished_job(self):
        self.generate.setEnabled(True);self.inspect.setEnabled(True)
        if self.pending_close and self.last_result is None:super().reject()

    def reject(self):
        self.password.clear()
        if self.job and self.job.isRunning():self.pending_close=True;self.job.cancel.set();self.status.setText('正在等待当前操作结束后关闭…');return
        super().reject()

    def closeEvent(self,event):
        if self.job and self.job.isRunning():self.reject();event.ignore()
        else:self.password.clear();event.accept()
