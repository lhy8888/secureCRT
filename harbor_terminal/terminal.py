"""Cell-based Qt terminal: paint only visible rows, preserve character attributes."""
import math

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (QColor, QFont, QFontMetricsF,
                          QPainter, QKeySequence)
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QDialog,
                              QDialogButtonBox, QMenu, QMessageBox,
                              QPlainTextEdit, QVBoxLayout, QLabel)

from .keyboard import encode_key, prepare_paste
from .terminal_model import TerminalModel, MAX_COLUMNS, MAX_ROWS
from .appearance import SCHEMES, terminal_font
from .input_policy import InputPolicy,display_text

PALETTE = dict(zip(
    ('black', 'red', 'green', 'brown', 'blue', 'magenta', 'cyan', 'white',
     'brightblack', 'brightred', 'brightgreen', 'brightbrown', 'brightblue',
     'brightmagenta', 'brightcyan', 'brightwhite'),
    ('#000000', '#cd0000', '#00cd00', '#cdcd00', '#0000ee', '#cd00cd', '#00cdcd', '#c0c0c0',
     '#7f7f7f', '#ff5555', '#55ff55', '#ffff55', '#5c5cff', '#ff55ff', '#55ffff', '#ffffff')))
BG = QColor('#000000')
FG = QColor('#d4d4d4')


def cell_colors(cell, default_fg=FG, default_bg=BG):
    def color(value, default):
        if value == 'default':
            return default
        if value in PALETTE:
            return QColor(PALETTE[value])
        if len(value) == 6 and all(c in '0123456789abcdefABCDEF' for c in value):
            return QColor('#' + value)
        return default
    foreground, background = color(cell.fg, default_fg), color(cell.bg, default_bg)
    return (background, foreground) if cell.reverse else (foreground, background)


class Terminal(QAbstractScrollArea):
    def __init__(self, worker, *, encoding='utf-8', backspace='del',input_policy=None):
        super().__init__()
        self.worker = worker
        self.input_policy=InputPolicy.parse(input_policy).values
        self.model = TerminalModel(encoding=encoding, response=self._respond,clear_history=self.input_policy['remote_clear_history'])
        self.screen, self.stream = self.model.screen, self.model.stream
        self.encoding, self.backspace = encoding, backspace
        self.selection = None
        self.preedit = ''
        self.search_text = ''
        self._last_match = None
        self._error_text = ''
        self.notice = ''
        self._last_alternate = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.viewport().setMouseTracking(True)
        self.background, self.foreground = QColor(BG), QColor(FG)
        self.setFont(terminal_font())
        self._metrics()
        self.setStyleSheet('QAbstractScrollArea {background:#000000;border:0;}')
        self.verticalScrollBar().valueChanged.connect(lambda _: self.viewport().update())
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self._resize_grid)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(30)

    def _metrics(self):
        metrics = QFontMetricsF(self.font())
        # Preserve the font's actual advance. Rounding every cell up adds
        # visible tracking and makes a monospace font look widely spaced.
        self.cell_width = max(1.0, metrics.horizontalAdvance('M'))
        self.cell_height = max(1, math.ceil(metrics.height()) + 2)
        self.ascent = metrics.ascent() + (self.cell_height - metrics.height()) / 2

    def set_appearance(self, scheme, font=None):
        _, background, foreground = SCHEMES.get(scheme, SCHEMES['classic'])
        self.background, self.foreground = QColor(background), QColor(foreground)
        self.setStyleSheet(f'QAbstractScrollArea {{background:{background};border:0;}}')
        if font is not None:
            self.setFont(font); self._metrics(); self.resize_timer.start(100)
        self.viewport().update()

    def _respond(self, data):
        if not self.worker.respond(data):
            self.worker.stop_event.set()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_timer.start(100)

    def _resize_grid(self):
        columns = min(MAX_COLUMNS, max(8, int(self.viewport().width() // self.cell_width)))
        lines = min(MAX_ROWS, max(2, self.viewport().height() // self.cell_height))
        self.model.resize(columns, lines)
        self.worker.resize(columns, lines)
        self.selection = None
        self._sync_scroll(True)
        self.viewport().update()

    def _sync_scroll(self, follow):
        scrollbar = self.verticalScrollBar()
        history = len(self.screen.history.top)
        scrollbar.setRange(0, history)
        scrollbar.setPageStep(self.screen.lines)
        if follow:
            scrollbar.setValue(history)

    def refresh(self):
        data = self.worker.take()
        if not data:
            return
        follow = self.verticalScrollBar().value() == self.verticalScrollBar().maximum()
        before = len(self.screen.history.top)
        try:
            self.model.feed(data)
        except Exception:
            self.worker.stop_event.set()
            self.timer.stop()
            self._error_text = '终端解析失败，已停止会话以避免继续处理异常数据。'
            self.viewport().update()
            return
        if self.screen.is_alternate != self._last_alternate:
            self.selection = None
            self._last_match = None
            self._last_alternate = self.screen.is_alternate
            follow = True
        if before == self.screen.history.top.maxlen and before and data:
            # History eviction can invalidate selection row indices. Fail closed.
            self.selection = None
        if len(self.screen.history.top)<before:self.selection=None;self._last_match=None
        self._sync_scroll(follow)
        self.viewport().update()
        QApplication.inputMethod().update(Qt.InputMethodQuery.ImCursorRectangle)

    def toPlainText(self):
        return self._error_text or self.notice or self.model.text()

    def _selected(self, row, column):
        if not self.selection:
            return False
        start, end = sorted(self.selection)
        return start <= (row, column) < end

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), self.background)
        painter.setFont(self.font())
        if self._error_text or self.notice:
            painter.setPen(self.foreground)
            painter.drawText(self.viewport().rect().adjusted(8,8,-8,-8), Qt.TextFlag.TextWordWrap, self._error_text or self.notice)
            return
        first = self.verticalScrollBar().value()
        visible = min(self.screen.lines, math.ceil(self.viewport().height() / self.cell_height))
        for y in range(visible):
            row = first + y
            line = self.model.line(row)
            text = self.model.line_text(row)
            # Search is literal. User-supplied regex never runs on the UI thread.
            matches = []
            if self.search_text:
                offset = 0
                while len(matches) < 1000:
                    offset = text.find(self.search_text, offset)
                    if offset < 0:
                        break
                    matches.append((offset, offset + len(self.search_text)))
                    offset += max(1, len(self.search_text))
            text_offset = 0
            glyphs = []
            previous_style = (self.foreground, self.background)
            for x in range(self.screen.columns):
                cell = line[x]
                foreground, background = cell_colors(cell, self.foreground, self.background)
                width = 2 if cell.data and x + 1 < self.screen.columns and line[x + 1].data == '' else 1
                if not cell.data and x:
                    foreground, background = previous_style
                elif self._selected(row, x) or (width == 2 and self._selected(row, x + 1)):
                    background = QColor('#30536f')
                elif cell.data and any(a <= text_offset < b for a, b in matches):
                    background, foreground = QColor('#d4aa43'), QColor('#101923')
                rect = QRectF(x * self.cell_width, y * self.cell_height, self.cell_width, self.cell_height)
                painter.fillRect(rect, background)
                previous_style = (foreground, background)
                if cell.data:
                    glyphs.append((cell, foreground, rect, width))
                    text_offset += len(cell.data)
            # Paint backgrounds first: a wide glyph's stub must not erase its right half.
            for cell, foreground, rect, width in glyphs:
                if cell.data != ' ' or cell.underscore or cell.strikethrough:
                    font = QFont(self.font())
                    font.setBold(cell.bold)
                    font.setItalic(cell.italics)
                    font.setUnderline(cell.underscore)
                    font.setStrikeOut(cell.strikethrough)
                    painter.setFont(font)
                    painter.setPen(foreground)
                    painter.save()
                    painter.setClipRect(QRectF(rect.x(), rect.y(), width * self.cell_width, self.cell_height))
                    painter.drawText(QPointF(rect.x(), rect.y() + self.ascent), cell.data)
                    painter.restore()
        cursor_row = len(self.screen.history.top) + self.screen.cursor.y - first
        if 0 <= cursor_row < visible and not self.screen.cursor.hidden:
            column = min(self.screen.cursor.x, self.screen.columns - 1)
            line = self.screen.buffer[self.screen.cursor.y]
            cell = line[column]
            width = 2 if cell.data and column + 1 < self.screen.columns and line[column + 1].data == '' else 1
            x = column * self.cell_width
            y = cursor_row * self.cell_height
            rectangle = QRectF(x, y, self.cell_width * width, self.cell_height)
            painter.setPen(self.foreground)
            if self.hasFocus() and not self.preedit:
                painter.fillRect(rectangle, self.foreground)
                painter.setFont(self.font()); painter.setPen(self.background)
                painter.drawText(QPointF(x, y + self.ascent), cell.data)
            else:
                painter.drawRect(rectangle.adjusted(0, 0, -1, -1))
            if self.preedit:
                painter.setFont(self.font()); painter.setPen(self.foreground)
                painter.drawText(QPointF(x, y + self.ascent), self.preedit)
                painter.drawLine(QPointF(x, y + self.cell_height - 2),
                                 QPointF(x + self.cell_width * len(self.preedit), y + self.cell_height - 2))

    def _point(self, position):
        return (self.verticalScrollBar().value() + min(self.screen.lines - 1, max(0, int(position.y()) // self.cell_height)),
                min(self.screen.columns, max(0, int(position.x() // self.cell_width))))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            point = self._point(event.position())
            self.selection = (point, point)
            self.viewport().update()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.selection:
            self.selection = (self.selection[0], self._point(event.position()))
            self.viewport().update()

    def selected_text(self):
        if not self.selection:
            return ''
        (start_row, start_column), (end_row, end_column) = sorted(self.selection)
        result = []
        for row in range(start_row, end_row + 1):
            a = start_column if row == start_row else 0
            b = end_column if row == end_row else self.screen.columns
            line = self.model.line(row)
            # Include the leading cell of a wide glyph selected via its stub.
            if a and a < self.screen.columns and line[a].data == '':
                a -= 1
            result.append(''.join(line[x].data for x in range(a, b)).rstrip())
        return '\n'.join(result)

    def copy(self):
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def find(self, text, *, backwards=False):
        self.search_text = text
        if not text:
            self._last_match = None
            self.viewport().update()
            return False
        matches = []
        for row in range(len(self.screen.history.top) + self.screen.lines):
            line = self.model.line_text(row)
            offset = 0
            while len(matches) < 1000:
                offset = line.find(text, offset)
                if offset < 0:
                    break
                matches.append((row, offset))
                offset += max(1, len(text))
            if len(matches) >= 1000:
                break
        if not matches:
            self._last_match = None
            self.viewport().update()
            return False
        previous = self._last_match
        candidates = [m for m in matches if previous is None or (m < previous if backwards else m > previous)]
        chosen = candidates[-1] if backwards and candidates else candidates[0] if candidates else matches[-1 if backwards else 0]
        self._last_match = chosen
        self.verticalScrollBar().setValue(chosen[0])
        self.viewport().update()
        return True

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if control and shift and event.key() == Qt.Key.Key_C:
            self.copy()
            return
        if (control and shift and event.key() == Qt.Key.Key_V) or event.matches(QKeySequence.StandardKey.Paste):
            self.paste_confirmed()
            return
        if event.matches(QKeySequence.StandardKey.Copy) and self.selected_text():
            self.copy()
            return
        key = event.key()
        alt=bool(modifiers & Qt.KeyboardModifier.AltModifier)
        altgr=bool(modifiers & Qt.KeyboardModifier.GroupSwitchModifier) or control and alt and event.text() and event.text().isprintable()
        if altgr:control=False;alt=False
        elif self.input_policy['alt_meta']=='text':alt=False
        name = Qt.Key(key).name.removeprefix('Key_') if key in Qt.Key._value2member_map_ else ''
        try:
            data = encode_key(name, event.text(), shift=shift, control=control,
                              alt=alt,
                              application_cursor=1 in self.screen.input_modes,
                              application_keypad=66 in self.screen.input_modes,
                              keypad=bool(modifiers & Qt.KeyboardModifier.KeypadModifier),
                              newline_mode=20 in self.screen.mode,
                              encoding=self.encoding, backspace=self.backspace)
        except UnicodeEncodeError:
            QApplication.beep()
            return
        if data and not self.worker.send(data):
            QApplication.beep()

    def inputMethodEvent(self, event):
        self.preedit = event.preeditString()[:256]
        if event.commitString():
            try:
                data = event.commitString().encode(self.encoding)
                if not self.worker.send(data):
                    QApplication.beep()
            except UnicodeEncodeError:
                QApplication.beep()
        self.viewport().update()
        event.accept()

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            y = len(self.screen.history.top) + self.screen.cursor.y - self.verticalScrollBar().value()
            return QRectF(min(self.screen.cursor.x, self.screen.columns - 1) * self.cell_width,
                          y * self.cell_height, self.cell_width, self.cell_height)
        if query == Qt.InputMethodQuery.ImEnabled:
            return True
        if query == Qt.InputMethodQuery.ImSurroundingText:
            return ''  # Never expose remote screen contents as editable local input.
        return super().inputMethodQuery(query)

    def confirm_multiline(self, text):
        dialog = QDialog(self)
        dialog.setWindowTitle('确认粘贴内容')
        dialog.resize(700, 500)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('请检查或编辑内容；多行粘贴可能执行远端命令。'))
        edit = QPlainTextEdit(text)
        edit.document().setModified(False)
        layout.addWidget(edit)
        label=QLabel('发送预览：␍表示CR，␊表示LF；只按当前会话编码/换行/引用设置发送文本。');label.setWordWrap(True);layout.addWidget(label)
        preview=QPlainTextEdit();preview.setReadOnly(True);layout.addWidget(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        def refresh_preview():
            try:
                content=edit.toPlainText() if edit.document().isModified() else text
                raw=prepare_paste(content,encoding=self.encoding,bracketed=2004 in self.screen.input_modes,
                    newline=self.input_policy['paste_newline'],quote=self.input_policy['paste_quote'])
                shown=display_text(raw.decode(self.encoding))
                preview.setPlainText(shown);buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            except (ValueError,UnicodeError):
                preview.setPlainText('内容包含控制字符、不能用当前编码表示或超过64KiB。');buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        edit.textChanged.connect(refresh_preview);refresh_preview()
        result = (edit.toPlainText() if edit.document().isModified() else text) if dialog.exec() == QDialog.DialogCode.Accepted else None
        edit.clear()
        dialog.deleteLater()
        return result

    def paste_confirmed(self,text=None,*,review=False):
        text = QApplication.clipboard().text() if text is None else text
        try:
            prepare_paste(text, encoding=self.encoding)
            if review or '\n' in text or '\r' in text or self.input_policy['paste_quote']!='none':
                text = self.confirm_multiline(text)
                if text is None:
                    return
            # Revalidate after editing; bracket terminators are prohibited in input.
            data = prepare_paste(text, encoding=self.encoding, bracketed=2004 in self.screen.input_modes,
                                 newline=self.input_policy['paste_newline'],quote=self.input_policy['paste_quote'])
        except (ValueError, UnicodeEncodeError) as exc:
            QMessageBox.warning(self, '无法粘贴', str(exc))
            return
        if data and not self.worker.send(data):
            QApplication.beep()

    def paste_path(self):
        from PySide6.QtWidgets import QFileDialog
        path,_=QFileDialog.getOpenFileName(self,'选择要粘贴为文本的路径（不读取或执行文件）')
        if path:self.paste_confirmed(path,review=True)

    def clear_local(self,history=False):
        self.model.screen.clear_local(history);self.selection=None;self._last_match=None
        self._sync_scroll(True);self.viewport().update()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            font = QFont(self.font())
            font.setPointSize(min(28, max(8, font.pointSize() + (1 if event.angleDelta().y() > 0 else -1))))
            self.setFont(font)
            self._metrics()
            self.resize_timer.start(100)
            self.viewport().update()
            event.accept()
        else:
            super().wheelEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('复制  Ctrl+Shift+C', self.copy)
        menu.addAction('粘贴（检查） Ctrl+Shift+V', lambda:self.paste_confirmed())
        menu.addAction('粘贴文件路径…',self.paste_path)
        menu.addSeparator();menu.addAction('清除当前屏幕（本地）',self.clear_local)
        menu.addAction('清除历史（本地）',lambda:self.clear_local(True))
        menu.exec(event.globalPos())
