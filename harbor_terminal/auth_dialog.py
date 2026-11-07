"""Non-blocking SSH challenge dialog, fixed to its worker and endpoint."""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPlainTextEdit,
    QFormLayout, QWidget, QScrollArea, QLineEdit, QDialogButtonBox)


def visible_prompt(text):
    return ''.join(f'\\u{ord(char):04x}' if (ord(char)<32 and char not in '\n\t')
        or char in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' else char for char in text)


class AuthenticationDialog(QDialog):
    def __init__(self, worker, event, parent=None):
        super().__init__(parent)
        self.worker, self.challenge, self.completed = worker, event, False
        self.deadline = time.monotonic()+event['timeout']
        self.setWindowTitle('SSH 交互认证'); self.resize(620, 440)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QVBoxLayout(self)
        stage = '跳板' if event['stage']=='jump' else '目标'
        header = QLabel(f"{stage} · {event['username']}@{event['host']}:{event['port']}")
        header.setTextFormat(Qt.TextFormat.PlainText); header.setWordWrap(True); layout.addWidget(header)
        details = QPlainTextEdit(visible_prompt(event['name']+'\n'+event['instructions']))
        details.setReadOnly(True); details.setMaximumHeight(130); layout.addWidget(details)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); layout.addWidget(scroll, 1)
        pane = QWidget(); form = QFormLayout(pane)
        self.fields = []
        for prompt, echo in event['prompts']:
            label = QLabel(visible_prompt(prompt)); label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True); label.setMaximumWidth(240)
            field = QLineEdit(); field.setMaxLength(8192)
            field.setEchoMode(QLineEdit.EchoMode.Normal if echo else QLineEdit.EchoMode.Password)
            form.addRow(label, field); self.fields.append(field)
        scroll.setWidget(pane)
        self.status = QLabel(); self.status.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('提交')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消连接')
        buttons.accepted.connect(self.submit); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.timer = QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.countdown)
        self.timer.start(); self.countdown()
        if self.fields: self.fields[0].setFocus()

    def countdown(self):
        left = max(0, int(self.deadline-time.monotonic()))
        self.status.setText(f'第{self.challenge["round"]}轮 · 剩余{left}秒 · 响应只用于本次认证')

    def clear_fields(self):
        for field in self.fields: field.clear()
        self.timer.stop()

    def submit(self):
        if self.completed: return
        answers = [field.text() for field in self.fields]
        if not self.worker.reply_auth(self.challenge['id'], answers):
            self.finish_without_reply(); return
        self.completed = True; answers.clear(); self.clear_fields(); self.accept()

    def reject(self):
        if not self.completed:
            self.completed = True; self.worker.reply_auth(self.challenge['id'], None)
        self.clear_fields(); super().reject()

    def finish_without_reply(self):
        self.completed = True; self.reject()
