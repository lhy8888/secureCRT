"""Session algorithm controls and read-only, redacted SSH diagnostics."""
from pathlib import Path

from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QLineEdit,QComboBox,QCheckBox,QPushButton,QListWidget,QListWidgetItem,QDialogButtonBox,
    QTreeWidget,QTreeWidgetItem,QFileDialog)

from .ssh_policy import DEFAULT_POLICY,MODERN,LEGACY,SSHPolicy,catalog
from .reports import atomic_json


POLICY_LABELS=dict(ssh_kex='密钥交换顺序',ssh_ciphers='加密算法顺序',ssh_macs='MAC顺序',
    ssh_hostkey_algs='主机密钥签名顺序',ssh_signature_algs='用户认证签名顺序')


def plain(text):
    widget=QLabel(text);widget.setWordWrap(True);widget.setTextFormat(Qt.TextFormat.PlainText);return widget


def confirm_compatibility(options,parent):
    peers=[peer for peer in (options,options.get('jump',{})) if peer.get('security',{}).get('ssh_allow_legacy')=='true'
        or peer.get('security',{}).get('ssh_strict_kex')=='prefer']
    if not peers:return True
    dialog=QDialog(parent);dialog.setWindowTitle('确认本次SSH兼容策略');layout=QVBoxLayout(dialog)
    layout.addWidget(plain('以下目标或跳板启用了旧算法许可或非强制Strict KEX。确认这些兼容设置适用于本次连接。'))
    for peer in peers:
        policy=peer['security'];layout.addWidget(plain(str(peer['host'])+':'+str(peer.get('port',22))+'\n'+
            'Strict KEX：'+policy.get('ssh_strict_kex','require')+'；旧算法许可：'+policy.get('ssh_allow_legacy','false')))
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    ok=buttons.button(QDialogButtonBox.StandardButton.Ok);cancel=buttons.button(QDialogButtonBox.StandardButton.Cancel)
    ok.setAutoDefault(False);ok.setDefault(False);cancel.setAutoDefault(False);cancel.setDefault(True)
    buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
    cancel.setFocus(Qt.FocusReason.OtherFocusReason)
    try:return dialog.exec()==QDialog.DialogCode.Accepted
    finally:dialog.deleteLater()


class AlgorithmChooser(QDialog):
    def __init__(self,field,current,legacy,parent):
        super().__init__(parent);self.setWindowTitle(POLICY_LABELS[field]);self.resize(650,480)
        layout=QVBoxLayout(self);layout.addWidget(plain('勾选允许的算法，按上/下调整优先顺序。没有共同算法时连接失败，不会自动加入未选算法。'))
        self.list=QListWidget();layout.addWidget(self.list,1)
        selected=current.split(',') if current else list(catalog(field))
        for value in selected+[value for value in catalog(field,legacy) if value not in selected]:
            item=QListWidgetItem(value+('  [旧算法]' if value in LEGACY[field] else ''));item.setData(Qt.ItemDataRole.UserRole,value)
            item.setCheckState(Qt.CheckState.Checked if value in selected else Qt.CheckState.Unchecked);self.list.addItem(item)
        row=QHBoxLayout();layout.addLayout(row)
        for title,direction in (('上移',-1),('下移',1)):
            button=QPushButton(title);button.clicked.connect(lambda checked=False,offset=direction:self.move(offset));row.addWidget(button)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def move(self,offset):
        index=self.list.currentRow();target=index+offset
        if 0<=index<self.list.count() and 0<=target<self.list.count():
            item=self.list.takeItem(index);self.list.insertItem(target,item);self.list.setCurrentRow(target)

    def value(self):
        return ','.join(self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                        if self.list.item(i).checkState()==Qt.CheckState.Checked)


class PolicyEditor(QWidget):
    def __init__(self,values,parent=None):
        super().__init__(parent);form=QFormLayout(self);self.fields={}
        self.legacy=QCheckBox('仅本会话允许显式选择旧算法（不会自动加入）')
        self.legacy.setChecked(values.get('ssh_allow_legacy','false')=='true');form.addRow(self.legacy)
        for field,title in POLICY_LABELS.items():
            edit=QLineEdit(values.get(field,''));edit.setPlaceholderText('留空使用推荐顺序；逗号分隔')
            choose=QPushButton('选择…');choose.clicked.connect(lambda checked=False,key=field:self.choose(key))
            row=QHBoxLayout();row.addWidget(edit,1);row.addWidget(choose);form.addRow(title+'：',row);self.fields[field]=edit
        self.strict=QComboBox();self.strict.addItem('必须核验Strict KEX，认证前拒绝不支持的服务器','require')
        self.strict.addItem('兼容：尽量协商，允许不支持的服务器','prefer')
        self.strict.setCurrentIndex(max(0,self.strict.findData(values.get('ssh_strict_kex','require'))));form.addRow('Strict KEX：',self.strict)
        self.compression=QComboBox();self.compression.addItem('关闭','none');self.compression.addItem('仅认证后启用zlib@openssh.com','delayed')
        self.compression.setCurrentIndex(max(0,self.compression.findData(values.get('ssh_compression','none'))));form.addRow('压缩：',self.compression)
        for field,title in (('ssh_rekey_bytes','重协商字节阈值'),('ssh_rekey_seconds','重协商秒数')):
            edit=QLineEdit(values.get(field,DEFAULT_POLICY[field]));form.addRow(title+'：',edit);self.fields[field]=edit
        self.status=plain('兼容设置会在连接前再次提示。协议认证压缩之外不允许提前压缩。');form.addRow(self.status)

    def choose(self,field):
        dialog=AlgorithmChooser(field,self.fields[field].text(),self.legacy.isChecked(),self)
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:
                value=dialog.value()
                if not value:self.status.setText('至少选择一种算法；原顺序保留。');return
                self.fields[field].setText(value)
        finally:dialog.deleteLater()

    def values(self):
        values={key:edit.text().strip() for key,edit in self.fields.items()}
        values.update(ssh_allow_legacy='true' if self.legacy.isChecked() else 'false',
                      ssh_strict_kex=self.strict.currentData(),ssh_compression=self.compression.currentData())
        return SSHPolicy.parse(values).values


class DiagnosticsDialog(QDialog):
    def __init__(self,worker,label,parent):
        super().__init__(parent);self.worker=worker;self.setWindowTitle('SSH协商诊断 · '+label);self.resize(800,530)
        layout=QVBoxLayout(self);layout.addWidget(plain('只展示协商元数据，不输出密码、私钥、认证回答或原始数据包。主机公钥格式与协商签名算法分别列出。'))
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['字段','值']);layout.addWidget(self.tree,1)
        export=QPushButton('导出元数据JSON…');export.clicked.connect(self.export);layout.addWidget(export)
        self.status=plain('');layout.addWidget(self.status)
        self.timer=QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.refresh)
        self.refresh();self.timer.start()

    def refresh(self):
        value=self.worker.ssh_diagnostics();self.tree.clear()
        for key,item in value.items():
            shown=str(item)
            shown=''.join(f'\\u{ord(c):04x}' if ord(c)<32 or 127<=ord(c)<160 or c in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' else c for c in shown)
            self.tree.addTopLevelItem(QTreeWidgetItem([key,shown]))
        self.tree.resizeColumnToContents(0);self.status.setText('当前状态：'+self.worker.status+'；未提供的协商信息不推断为通过。')

    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'导出SSH诊断元数据','','JSON (*.json)')
        if not path:return
        try:atomic_json(Path(path),self.worker.ssh_diagnostics());self.status.setText('元数据已保存。')
        except OSError:self.status.setText('无法保存诊断文件。')

    def closeEvent(self,event):self.timer.stop();event.accept()

    def showEvent(self,event):super().showEvent(event);self.timer.start()
