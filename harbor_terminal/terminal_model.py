"""Bounded main/alternate grids, separate from widgets and network I/O."""
import codecs
from collections import defaultdict
import unicodedata

import pyte

from .terminal_stream import SafeTerminalStream

MAX_COLUMNS = 512
MAX_ROWS = 200
HISTORY_LINES = 2000
ENCODINGS = ('utf-8', 'gb18030', 'big5', 'shift_jis', 'latin-1')


class Grid(pyte.HistoryScreen):
    def __init__(self, columns, lines, response, history=HISTORY_LINES):
        self.response = response
        super().__init__(columns, lines, history=history)

    def save_cursor(self):
        # Repeated ESC 7 from an untrusted peer must not grow a stack forever.
        if len(self.savepoints) >= 16:
            del self.savepoints[0]
        super().save_cursor()

    def resize(self, lines=None, columns=None):
        rows = min(MAX_ROWS, max(1, lines or self.lines))
        cols = min(MAX_COLUMNS, max(1, columns or self.columns))
        if (rows, cols) == (self.lines, self.columns):
            return
        old_columns = self.columns
        # Keep the prompt and existing top rows when they fit. Only scroll when
        # shrinking would put the current cursor below the new bottom edge.
        shift = max(0, self.cursor.y - rows + 1)
        if shift:
            for y in range(shift):
                self.history.top.append(self.buffer[y])
        retained = defaultdict(self.buffer.default_factory)
        for y, line in self.buffer.items():
            new_y = y - shift
            if 0 <= new_y < rows:
                if cols < old_columns:
                    for x in list(line):
                        if x >= cols:
                            del line[x]
                retained[new_y] = line
        self.buffer = retained
        self.cursor.y = min(rows - 1, max(0, self.cursor.y - shift))
        self.cursor.x = min(cols - 1, self.cursor.x)
        if cols > old_columns:
            self.tabstops.update(range(((old_columns + 7) // 8) * 8, cols, 8))
        self.lines, self.columns = rows, cols
        self.dirty.update(range(rows))
        self.set_margins()

    def index(self):
        if self.margins and self.margins != (0, self.lines - 1):
            pyte.Screen.index(self)
        else:
            super().index()

    def write_process_input(self, text):
        if self.response:
            self.response(text.encode('ascii'))


class ScreenMux:
    """Dispatch each parser event to the current grid, even after a screen swap."""
    def __init__(self, columns=100, lines=30, response=None,clear_history='allow'):
        if clear_history not in ('allow','preserve'):raise ValueError('Invalid remote history policy')
        self.clear_history=clear_history
        self.main = Grid(columns, lines, response)
        self.alternate = Grid(columns, lines, response, history=0)
        self.active = self.main
        self.input_modes = set()
        self.saved_for_alt = False
        self.last_character = ' '
        self.operation_budget = None

    def __getattr__(self, name):
        value = getattr(self.active, name)
        if callable(value):
            def dispatch(*args, **kwargs):
                if name in ('erase_in_display', 'insert_lines', 'delete_lines'):
                    self._charge(self.columns * self.lines)
                elif name in ('erase_in_line', 'erase_characters', 'insert_characters', 'delete_characters'):
                    self._charge(self.columns)
                return getattr(self.active, name)(*args, **kwargs)
            return dispatch
        return value

    @property
    def is_alternate(self):
        return self.active is self.alternate

    def _enter_alternate(self, mode):
        if self.is_alternate:
            return
        if mode == 1049:
            self.main.save_cursor()
            self.saved_for_alt = True
        if mode in (1047, 1049):
            self.alternate.reset()
        self.active = self.alternate

    def _leave_alternate(self):
        if not self.is_alternate:
            return
        self.active = self.main
        if self.saved_for_alt:
            self.main.restore_cursor()
            self.saved_for_alt = False

    def set_mode(self, *modes, **kwargs):
        normal = []
        for mode in modes:
            if kwargs.get('private') and mode in (47, 1047, 1049):
                self._enter_alternate(mode)
            elif kwargs.get('private') and mode == 1048:
                self.active.save_cursor()
            else:
                normal.append(mode)
            if kwargs.get('private') and mode in (1, 66, 2004):
                self.input_modes.add(mode)
        self.active.set_mode(*normal, **kwargs)

    def reset_mode(self, *modes, **kwargs):
        normal = []
        for mode in modes:
            if kwargs.get('private') and mode in (47, 1047, 1049):
                self._leave_alternate()
            elif kwargs.get('private') and mode == 1048:
                self.active.restore_cursor()
            else:
                normal.append(mode)
            if kwargs.get('private'):
                self.input_modes.discard(mode)
        self.active.reset_mode(*normal, **kwargs)

    def reset(self):
        retained=list(self.main.history.top) if self.clear_history=='preserve' else []
        self.main.reset()
        self.alternate.reset()
        self.active = self.main
        self.input_modes.clear()
        self.saved_for_alt = False
        self.last_character = ' '
        self.main.history.top.extend(retained)

    def erase_in_display(self,how=0,*args,**kwargs):
        if how==3 and self.clear_history=='preserve':return
        self._charge(self.columns*self.lines)
        self.active.erase_in_display(how,*args,**kwargs)

    def clear_local(self,history=False):
        if history:
            for grid in (self.main,self.alternate):grid._reset_history()
        else:self.active.erase_in_display(2)

    def set_application_keypad(self):
        self.input_modes.add(66)

    def reset_application_keypad(self):
        self.input_modes.discard(66)

    def draw(self, text):
        self._charge(len(text))
        if not any(unicodedata.combining(c) for c in text):
            self.active.draw(text)
        else:
            pending = []
            for char in text:
                if unicodedata.combining(char):
                    if pending:
                        self.active.draw(''.join(pending))
                        pending.clear()
                    cell = self._previous_cell()
                    if cell and len(cell.data) < 32:
                        self.active.draw(char)
                else:
                    pending.append(char)
            if pending:
                self.active.draw(''.join(pending))
        cell = self._previous_cell()
        if cell:
            self.last_character = cell.data or ' '

    def _previous_cell(self):
        x, y = min(self.cursor.x - 1, self.columns - 1), self.cursor.y
        if x < 0:
            if y == 0:
                return None
            x, y = self.columns - 1, y - 1
        line = self.buffer[y]
        if not line[x].data and x:
            x -= 1
        return line[x]

    def _charge(self, amount):
        if self.operation_budget is not None:
            self.operation_budget -= amount
            if self.operation_budget < 0:
                raise ValueError('Terminal operation budget exceeded')

    def repeat_character(self, count=1):
        # A bounded extension, not an unlimited amplification primitive.
        self.draw(self.last_character * min(max(1, count), self.columns))

    def resize(self, columns, lines):
        columns = min(MAX_COLUMNS, max(1, int(columns)))
        lines = min(MAX_ROWS, max(1, int(lines)))
        for grid in (self.main, self.alternate):
            grid.resize(columns=columns, lines=lines)
            grid.ensure_hbounds()
            grid.ensure_vbounds()


class TerminalModel:
    def __init__(self, columns=100, lines=30, encoding='utf-8', response=None,clear_history='allow'):
        if encoding not in ENCODINGS:
            raise ValueError('Unsupported encoding')
        self.screen = ScreenMux(columns, lines, response,clear_history)
        self.stream = SafeTerminalStream(self.screen)
        self.decoder = codecs.getincrementaldecoder(encoding)(errors='replace')
        self.encoding = encoding

    def feed(self, data):
        self.screen.operation_budget = 200_000
        try:
            self.stream.feed(self.decoder.decode(data))
        finally:
            self.screen.operation_budget = None

    def resize(self, columns, lines):
        self.screen.resize(columns, lines)

    @property
    def history(self):
        return list(self.screen.history.top)

    def line(self, index):
        history = self.screen.history.top
        if index < len(history):
            return history[index]
        return self.screen.buffer[index - len(history)]

    def line_text(self, index):
        line = self.line(index)
        return ''.join(line[x].data for x in range(self.screen.columns)).rstrip()

    def text(self):
        return '\n'.join(self.line_text(i) for i in range(len(self.screen.history.top) + self.screen.lines))
