"""Session management dialogs with frozen previews and explicit field changes."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QDialogButtonBox,QTreeWidget,QTreeWidgetItem,QLineEdit,QComboBox,QCheckBox,
    QFormLayout,QWidget,QScrollArea,QTabWidget,QFileDialog,QInputDialog,QAbstractItemView)

from . import profiles,session_templates
from .authentication import AUTH_METHODS
from .profile_operations import (csv_headers,default_mapping,parse_import,plan_import,
    export_sessions,patch_sessions,rename_path,delete_sessions,describe_changes,IMPORT_LIMIT)
from .storage import atomic_bytes,StorageConflict,CommitUncertain
from .terminal_model import ENCODINGS
from .ssh_dialogs import POLICY_LABELS


LABELS=dict(mode='协议',port='端口 / 波特率',username='用户名',known_hosts='已验证known_hosts路径',
    private_key='私钥路径',auth_method='认证顺序',ssh_mode='SSH通道模式',encoding='编码',backspace='退格键',
    bytesize='数据位',parity='校验位',stopbits='停止位',flow_control='流控',jump_profile='跳板会话引用',host='主机 / 设备')
CHOICES=dict(mode=('SSH','Serial'),auth_method=tuple(AUTH_METHODS),ssh_mode=('shell','channels'),
    encoding=tuple(ENCODINGS),backspace=('del','bs'),bytesize=('5','6','7','8'),
    parity=('N','E','O','M','S'),stopbits=('1','1.5','2'),flow_control=('none','rtscts','dsrdtr','xonxoff'))
CHOICE_LABELS={'auto':'自动（公钥优先）','password-first':'密码优先','interactive-first':'交互认证优先',
    'publickey-only':'仅公钥','interactive-only':'仅交互认证','shell':'交互Shell','channels':'仅SFTP / 隧道',
    'del':'DEL (0x7F)','bs':'BS (0x08)','none':'无','rtscts':'RTS/CTS','dsrdtr':'DSR/DTR','xonxoff':'XON/XOFF'}
LABELS.update(POLICY_LABELS,client_certificate='OpenSSH用户证书路径',ssh_compression='SSH压缩',
    ssh_strict_kex='Strict KEX',ssh_allow_legacy='本会话旧算法许可',ssh_rekey_bytes='重协商字节阈值',ssh_rekey_seconds='重协商秒数')
CHOICES.update(ssh_compression=('none','delayed'),ssh_strict_kex=('require','prefer'),ssh_allow_legacy=('false','true'))
CHOICE_LABELS.update(delayed='仅认证后压缩',require='必须核验',prefer='兼容协商',false='不允许',true='明确允许')
LABELS.update(send_char_delay_ms='字节间隔(ms)',send_line_delay_ms='行间隔(ms)',paste_newline='粘贴换行',
    paste_quote='粘贴引用',alt_meta='Alt Meta',remote_clear_history='远端清历史')
CHOICES.update(paste_newline=('auto','keep','cr','lf','crlf'),paste_quote=('none','posix','powershell'),
    alt_meta=('escape','text'),remote_clear_history=('allow','preserve'))
STRATEGIES=(('仅新增，冲突跳过','add-only'),('替换同名会话','replace'),('合并已提供字段','merge'),('创建副本','copy'))


def label(text):
    widget=QLabel(text);widget.setTextFormat(Qt.TextFormat.PlainText);widget.setWordWrap(True);return widget


def buttons(dialog,layout,ok='确定'):
    box=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Ok).setText(ok)
    box.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
    box.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
    box.accepted.connect(dialog.accept);box.rejected.connect(dialog.reject);layout.addWidget(box);return box


class ChangePreview(QDialog):
    def __init__(self,before,after,parent,*,title='预览会话更改',notice=''):
        super().__init__(parent);self.setWindowTitle(title);self.resize(940,590)
        layout=QVBoxLayout(self)
        rows=describe_changes(before,after)
        layout.addWidget(label(f'新增{sum(r[1]=="新增" for r in rows)} · 修改{sum(r[1]=="修改" for r in rows)} · 删除{sum(r[1]=="删除" for r in rows)}。确认后只保存配置，不会连接或发送命令。\n'+notice))
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['会话','操作 / 字段','原值','新值'])
        self.tree.setUniformRowHeights(True);layout.addWidget(self.tree,1)
        for name,action,_ in rows:
            top=QTreeWidgetItem([name,action]);self.tree.addTopLevelItem(top)
            for field in sorted(before.get(name,{}).keys()|after.get(name,{}).keys()):
                previous=before.get(name,{}).get(field);current=after.get(name,{}).get(field)
                if previous!=current:top.addChild(QTreeWidgetItem(['',LABELS.get(field,field),previous or '',current or '']))
        self.tree.expandAll();self.tree.setColumnWidth(0,230);self.tree.setColumnWidth(1,170)
        buttons(self,layout,'确认保存')


class FieldEditor(QWidget):
    def __init__(self,fields,values,*,checkable=False):
        super().__init__();self.inputs={};self.checks={};form=QFormLayout(self)
        for field in fields:
            if field in CHOICES:
                edit=QComboBox()
                for value in CHOICES[field]:
                    title='自动（普通CR / Bracketed LF）' if field=='paste_newline' and value=='auto' else CHOICE_LABELS.get(value,value)
                    edit.addItem(title,value)
                edit.setCurrentIndex(max(0,edit.findData(values.get(field,''))))
            else:edit=QLineEdit(values.get(field,''))
            self.inputs[field]=edit
            if checkable:
                check=QCheckBox(LABELS.get(field,field));self.checks[field]=check;edit.setEnabled(False)
                check.toggled.connect(edit.setEnabled);form.addRow(check,edit)
            else:form.addRow(LABELS.get(field,field)+'：',edit)

    def values(self):
        return {field:(edit.currentData() if isinstance(edit,QComboBox) else edit.text().strip())
                for field,edit in self.inputs.items() if not self.checks or self.checks[field].isChecked()}

    def populate(self,values):
        for field,value in values.items():
            edit=self.inputs.get(field)
            if edit is not None:
                if isinstance(edit,QComboBox):edit.setCurrentIndex(max(0,edit.findData(value)))
                else:edit.setText(value)


class BatchEditor(QDialog):
    def __init__(self,existing,names,templates,parent):
        super().__init__(parent);self.setWindowTitle('批量编辑会话');self.resize(710,650)
        self.existing=deepcopy(existing);self.names=tuple(names);self.plan=None
        layout=QVBoxLayout(self);layout.addWidget(label('固定范围：'+'、'.join(names)))
        layout.addWidget(label('只修改明确勾选的字段。未勾选的值保留；空值也必须勾选。协议切换不删除其他字段。'))
        row=QHBoxLayout();self.template=QComboBox();self.template.addItems(['SSH','Serial']);row.addWidget(self.template)
        fill=QPushButton('填入该协议默认值');row.addWidget(fill);layout.addLayout(row)
        fields=('mode','port','username','known_hosts','private_key','auth_method','ssh_mode','jump_profile',
                'encoding','backspace','bytesize','parity','stopbits','flow_control')
        fields+=tuple(sorted(profiles.FIELDS-set(fields)-{'host'}))
        defaults=dict(session_templates.BASE_OPTIONS,mode='SSH',port='22',username='',known_hosts='')
        self.editor=FieldEditor(fields,defaults,checkable=True)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.editor);layout.addWidget(scroll,1)
        fill.clicked.connect(lambda:self.editor.populate(session_templates.settings(templates,self.template.currentText())))
        self.status=label('填入模板仅改变编辑框；仍需勾选要应用的字段。');layout.addWidget(self.status);buttons(self,layout,'预览更改')

    def accept(self):
        try:self.plan=patch_sessions(self.existing,self.names,self.editor.values())
        except (ValueError,TypeError):self.status.setText('更改无效：检查已勾选字段、端口、串口范围和编码；没有保存。');return
        super().accept()


class ImportDialog(QDialog):
    def __init__(self,raw,kind,parent):
        super().__init__(parent);self.raw=raw;self.incoming=None;self.notice='';self.setWindowTitle('导入会话：格式与列映射');self.resize(820,650)
        if len(raw)>IMPORT_LIMIT:raise ValueError('Import exceeds 2 MiB')
        layout=QVBoxLayout(self);layout.addWidget(label('只导入非秘密字段。未知列（包括密码列）默认忽略，不导入密码、私钥内容或主机信任库。XML仅接受Harbor原生格式。'))
        row=QHBoxLayout();self.kind=QComboBox();self.kind.addItems(['csv','tsv','xml','json']);self.kind.setCurrentText(kind)
        self.encoding=QComboBox();self.encoding.addItems(['utf-8-sig','gb18030','utf-16'])
        row.addWidget(label('格式：'));row.addWidget(self.kind);row.addWidget(label('编码：'));row.addWidget(self.encoding)
        parse=QPushButton('读取并预览行');row.addWidget(parse);layout.addLayout(row)
        self.mapping=QTreeWidget();self.mapping.setHeaderLabels(['来源列名','映射为']);layout.addWidget(self.mapping)
        self.rows=QTreeWidget();self.rows.setHeaderLabels(['选择会话','协议','目标','端口']);layout.addWidget(self.rows,1)
        row=QHBoxLayout();row.addWidget(label('同名冲突：'));self.strategy=QComboBox()
        for title,value in STRATEGIES:self.strategy.addItem(title,value)
        row.addWidget(self.strategy);layout.addLayout(row)
        self.status=label('');layout.addWidget(self.status);buttons(self,layout,'预览所选会话的变更')
        self.kind.currentTextChanged.connect(self.reset_mapping);self.encoding.currentTextChanged.connect(self.reset_mapping)
        parse.clicked.connect(self.read_rows);self.reset_mapping()

    def text(self):return self.raw.decode(self.encoding.currentText())

    def reset_mapping(self,*_):
        self.incoming=None;self.rows.clear();self.mapping.clear();self.columns={}
        try:
            if self.kind.currentText() not in ('csv','tsv'):self.mapping.hide();return
            self.mapping.show();header=csv_headers(self.text(),',' if self.kind.currentText()=='csv' else '\t')
            automatic=default_mapping(header)
            for source in header:
                item=QTreeWidgetItem([source]);self.mapping.addTopLevelItem(item);choice=QComboBox();choice.addItem('忽略此列',None)
                for field in ['name']+sorted(profiles.FIELDS):choice.addItem('会话名称' if field=='name' else LABELS.get(field,field),field)
                if automatic[source]:choice.setCurrentIndex(choice.findData(automatic[source]))
                choice.currentIndexChanged.connect(self.invalidate_rows)
                self.mapping.setItemWidget(item,1,choice);self.columns[source]=choice
            self.mapping.resizeColumnToContents(0)
            self.status.setText('检查列映射后读取；未映射的列不会保存。')
        except (ValueError,UnicodeError):self.status.setText('无法读取表头，请检查格式和编码。')

    def invalidate_rows(self,*_):self.incoming=None;self.rows.clear()

    def read_rows(self):
        self.invalidate_rows()
        try:
            result=parse_import(self.text(),self.kind.currentText(),mapping={key:edit.currentData() for key,edit in self.columns.items()})
            self.incoming=result.sessions;self.notice='忽略列：'+'、'.join(result.ignored_columns) if result.ignored_columns else ''
            for name,profile in self.incoming.items():
                item=QTreeWidgetItem([name,profile.get('mode','SSH'),profile.get('host',''),profile.get('port','')]);item.setCheckState(0,Qt.CheckState.Checked)
                self.rows.addTopLevelItem(item)
            self.rows.resizeColumnToContents(0);self.status.setText(f'已读取{len(self.incoming)}项。'+self.notice)
        except (ValueError,TypeError,UnicodeError):self.status.setText('导入失败：检查编码、映射、重复名称和字段值；原配置没有更改。')

    def accept(self):
        if self.incoming is None:self.status.setText('先读取并检查会话行。');return
        selected={self.rows.topLevelItem(i).text(0) for i in range(self.rows.topLevelItemCount())
                  if self.rows.topLevelItem(i).checkState(0)==Qt.CheckState.Checked}
        if not selected:self.status.setText('至少选择一个导入会话。');return
        self.incoming={name:profile for name,profile in self.incoming.items() if name in selected};super().accept()


class TemplateDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.setWindowTitle('按协议保存默认会话模板');self.resize(730,650)
        self.revision=owner.template_revision;layout=QVBoxLayout(self)
        layout.addWidget(label('只影响新建连接。不会改写已有会话，也不保存主机、设备、密码或跳板引用。批量应用需在会话管理中选择范围和字段。'))
        tabs=QTabWidget();layout.addWidget(tabs,1);self.editors={}
        for mode in ('SSH','Serial'):
            settings=session_templates.settings(owner.templates,mode);editor=FieldEditor(settings.keys(),settings)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(editor);tabs.addTab(scroll,mode);self.editors[mode]=editor
        self.status=label('');layout.addWidget(self.status);buttons(self,layout,'保存默认模板')
        if owner.template_error:self.status.setText('默认模板文件损坏，保存已禁用；请先备份并修复defaults.json。')

    def accept(self):
        if self.owner.template_error:return
        templates={mode:editor.values() for mode,editor in self.editors.items()}
        try:snapshot=self.owner.template_store.save(templates,expected_revision=self.revision)
        except StorageConflict:self.status.setText('另一个窗口已修改模板，请关闭并重新打开后编辑。');return
        except CommitUncertain:self.status.setText('模板保存结果待确认；请重新载入应用后核对。');return
        except (ValueError,OSError):self.status.setText('保存失败，请检查字段与文件权限。');return
        self.owner.templates=snapshot.value;self.owner.template_revision=snapshot.revision;super().accept()


class SessionManager(QDialog):
    def __init__(self,owner,selected=()):
        super().__init__(owner);self.owner=owner;self.setWindowTitle('会话管理');self.resize(950,650)
        layout=QVBoxLayout(self);self.filter=QLineEdit();self.filter.setPlaceholderText('筛选名称、主机、用户名');layout.addWidget(self.filter)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['会话','协议','目标','端口']);self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(True);layout.addWidget(self.tree,1);self.tree.itemDoubleClicked.connect(lambda *_:self.load_selected())
        for actions in ((('载入 / 连接…',self.load_selected),('批量编辑…',self.edit_selected),('重命名路径…',self.rename_selected),('删除…',self.delete_selected)),
                        (('导入CSV / TSV / XML / JSON…',self.import_file),('导出所选…',self.export_selected),('重新载入',self.reload),('恢复上次有效备份…',self.restore))):
            row=QHBoxLayout()
            for title,callback in actions:
                button=QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
            layout.addLayout(row)
        self.status=label('按Ctrl或Shift选择多个会话。所有写入先预览，切换活动终端不会改变范围。');layout.addWidget(self.status)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);close.rejected.connect(self.reject);layout.addWidget(close)
        self.filter.textChanged.connect(self.render);self.render(selected)

    def names(self):return tuple(item.text(0) for item in self.tree.selectedItems())

    def render(self,selected=None):
        selected=set(selected) if isinstance(selected,(tuple,list,set)) else set(self.names())
        query=self.filter.text().casefold();self.tree.clear()
        for name,profile in sorted(self.owner.profiles.items()):
            if query and query not in (' '.join((name,profile.get('host',''),profile.get('username','')))).casefold():continue
            item=QTreeWidgetItem([name,profile.get('mode','SSH'),profile.get('host',''),profile.get('port','')]);self.tree.addTopLevelItem(item);item.setSelected(name in selected)
        self.tree.resizeColumnToContents(0)

    def commit(self,plan,*,title='预览会话更改',notice=''):
        if self.owner.profile_error:self.status.setText('原会话文件无法读取，已禁用保存；可恢复有效备份。');return False
        if not describe_changes(self.owner.profiles,plan):self.status.setText('没有需要保存的变化。');return False
        frozen=deepcopy(plan);revision=self.owner.profile_revision
        unresolved=[name for name,item in frozen.items() if item.get('jump_profile') and item['jump_profile'] not in frozen]
        if unresolved:notice+='\n以下会话的跳板引用尚未找到，连接前需要补齐：'+'、'.join(unresolved)
        preview=ChangePreview(self.owner.profiles,frozen,self,title=title,notice=notice)
        try:
            if preview.exec()!=QDialog.DialogCode.Accepted:return False
        finally:preview.deleteLater()
        if not self.owner.commit_profiles(frozen,expected_revision=revision):self.status.setText(self.owner.status.text());return False
        self.render();self.status.setText('已保存；已有连接未被修改，也没有自动连接。');return True

    def load_selected(self):
        names=self.names()
        if len(names)!=1:self.status.setText('选择一个会话载入；批量修改可多选。');return
        self.accept();self.owner.load_profile(names[0]);self.owner.show_quick_connect()

    def edit_selected(self):
        names=self.names()
        if not names:self.status.setText('先选择要修改的会话。');return
        dialog=BatchEditor(self.owner.profiles,names,self.owner.templates,self)
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:self.commit(dialog.plan)
        finally:dialog.deleteLater()

    def rename_selected(self):
        names=self.names()
        if len(names)!=1:self.status.setText('选择一个会话，再输入会话或文件夹路径。');return
        old,ok=QInputDialog.getText(self,'重命名路径','原会话或文件夹路径：',text=names[0])
        if not ok:return
        new,ok=QInputDialog.getText(self,'重命名路径','新路径：',text=old)
        if not ok:return
        try:plan=rename_path(self.owner.profiles,old.strip(),new.strip())
        except ValueError:self.status.setText('路径无效、范围为空或目标冲突；没有保存。');return
        self.commit(plan,title='预览重命名及跳板引用更新')

    def delete_selected(self):
        try:plan=delete_sessions(self.owner.profiles,self.names())
        except ValueError:self.status.setText('选择要删除的会话；若有其他会话引用其跳板，需要一并选择依赖会话。');return
        self.commit(plan,title='预览删除会话')

    def import_file(self):
        path,_=QFileDialog.getOpenFileName(self,'导入非秘密会话配置','','会话配置 (*.csv *.tsv *.xml *.json)')
        if not path:return
        try:
            with Path(path).open('rb') as stream:raw=stream.read(IMPORT_LIMIT+1)
            dialog=ImportDialog(raw,Path(path).suffix.lstrip('.').lower(),self)
            try:
                if dialog.exec()!=QDialog.DialogCode.Accepted:return
                plan=plan_import(self.owner.profiles,dialog.incoming,dialog.strategy.currentData())
                notice=dialog.notice
            finally:dialog.deleteLater()
            self.commit(plan,title='预览会话导入',notice=notice)
        except (OSError,ValueError):self.status.setText('导入失败：检查格式、大小、字段和名称冲突；原配置保留。')

    def export_selected(self):
        names=self.names()
        if not names:self.status.setText('先明确选择导出的会话。');return
        path,chosen=QFileDialog.getSaveFileName(self,'导出所选非秘密会话','','Harbor XML (*.xml);;Harbor JSON (*.json)')
        if not path:return
        try:
            destination=Path(path).resolve();root=self.owner.profile_path.parent.resolve()
            if destination.parent==root and (destination.name.casefold() in ('sessions.json','defaults.json','commands.json','appearance.ini')
                or destination.name.casefold().startswith(self.owner.profile_path.name.casefold())):
                raise ValueError('Do not overwrite managed configuration files')
            kind='json' if destination.suffix.lower()=='.json' or 'JSON' in chosen else 'xml'
            atomic_bytes(destination,export_sessions({name:self.owner.profiles[name] for name in names},kind))
            self.status.setText(f'已导出{len(names)}项；不包含密码、私钥内容或主机公钥库。')
        except (ValueError,OSError):self.status.setText('导出失败：检查路径，不能覆盖应用管理的配置文件。')

    def reload(self):
        if self.owner.reload_profiles():self.render();self.status.setText('已读取磁盘上的会话；可重新编辑。')
        else:self.status.setText(self.owner.status.text())

    def restore(self):
        try:
            backup=profiles.store(str(self.owner.profile_path)+'.bak').read()
            if backup.revision is None:raise FileNotFoundError()
            revision=self.owner.profile_store.revision()
            try:before=self.owner.profile_store.read().value;notice=''
            except ValueError:before={};notice='当前磁盘文件无法解析。'
        except (ValueError,OSError):self.status.setText('没有可读取的有效备份。');return
        preview=ChangePreview(before,backup.value,self,title='恢复上次有效会话备份',notice=notice+'当前文件将另存为damaged副本；恢复不会自动连接。')
        try:
            if preview.exec()!=QDialog.DialogCode.Accepted:return
        finally:preview.deleteLater()
        if self.owner.restore_profile_backup(expected_revision=revision,expected_backup_revision=backup.revision):self.render();self.status.setText('已恢复有效备份；原文件保存在damaged副本。')
        else:self.status.setText(self.owner.status.text())
