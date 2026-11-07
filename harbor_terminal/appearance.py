"""Desktop palettes, original toolbar icons and local display preferences."""
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QRectF
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QPainter,
                          QPainterPath, QPen, QPixmap, QPalette)


SCHEMES = {
    'classic': ('经典黑底', '#000000', '#d4d4d4'),
    'paper': ('浅色终端', '#ffffff', '#202020'),
    'navy': ('深蓝终端', '#002b49', '#eeeeee'),
}


def interface_font():
    families = QFontDatabase.families()
    preferred = ('Segoe UI', 'Microsoft YaHei UI', 'Noto Sans CJK SC', 'Noto Sans', 'DejaVu Sans')
    font = QFont(next((name for name in preferred if name in families), 'Sans Serif'), 9)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def terminal_font(family='', size=11):
    available = QFontDatabase.families()
    preferred = ('Consolas', 'Cascadia Mono', 'Liberation Mono', 'DejaVu Sans Mono')
    chosen = family if family in available and QFontDatabase.isFixedPitch(family) else next((f for f in preferred if f in available), 'monospace')
    font = QFont()
    font.setFamilies([chosen, 'Noto Sans Mono CJK SC', 'Microsoft YaHei', 'monospace'])
    font.setPointSizeF(min(28, max(8, float(size))))
    font.setFixedPitch(True)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    font.setKerning(False)
    return font


class Preferences:
    """Separate from session data: four display fields, no connection data."""
    def __init__(self, profile_path):
        self.settings = QSettings(str(Path(profile_path).with_name('appearance.ini')), QSettings.Format.IniFormat)
        self.theme = self.settings.value('display/theme', 'light')
        if self.theme not in ('light', 'dark'): self.theme = 'light'
        self.scheme = self.settings.value('display/scheme', 'classic')
        if not isinstance(self.scheme, str) or self.scheme not in SCHEMES: self.scheme = 'classic'
        family = self.settings.value('display/font', '')
        self.family = family if isinstance(family, str) and len(family) <= 128 else ''
        try: self.size = min(28, max(8, float(self.settings.value('display/size', 11))))
        except (TypeError, ValueError): self.size = 11

    def save(self):
        for key in ('theme', 'scheme', 'family', 'size'):
            self.settings.setValue('display/' + ('font' if key == 'family' else key), getattr(self, key))
        self.settings.sync()
        return self.settings.status() == QSettings.Status.NoError


def apply_desktop_style(window, theme):
    dark = theme == 'dark'
    colors = dict(window='#252525' if dark else '#f0f0f0',
                  base='#1e1e1e' if dark else '#ffffff',
                  text='#e8e8e8' if dark else '#202020',
                  border='#505050' if dark else '#b8b8b8',
                  muted='#a0a0a0' if dark else '#707070',
                  hover='#3c3c3c' if dark else '#e4eff9',
                  selected='#373737' if dark else '#ffffff')
    palette = QPalette(window.palette())
    for role, value in ((QPalette.ColorRole.Window, colors['window']),
                        (QPalette.ColorRole.WindowText, colors['text']),
                        (QPalette.ColorRole.Base, colors['base']),
                        (QPalette.ColorRole.Text, colors['text']),
                        (QPalette.ColorRole.Button, colors['window']),
                        (QPalette.ColorRole.ButtonText, colors['text']),
                        (QPalette.ColorRole.Highlight, '#0078d7'),
                        (QPalette.ColorRole.HighlightedText, '#ffffff'),
                        (QPalette.ColorRole.ToolTipBase, colors['base']),
                        (QPalette.ColorRole.ToolTipText, colors['text'])):
        palette.setColor(role, QColor(value))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(colors['muted']))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(colors['muted']))
    window.setPalette(palette)
    window.setFont(interface_font())
    window.setStyleSheet('''
        QWidget { color: %(text)s; }
        QMainWindow, QDialog { background: %(window)s; color: %(text)s; }
        QMenuBar { background: %(window)s; color: %(text)s; border-bottom: 1px solid %(border)s; }
        QMenuBar::item { padding: 3px 8px; background: transparent; }
        QMenuBar::item:selected, QMenu::item:selected { background: #0078d7; color: white; }
        QMenu { background: %(base)s; color: %(text)s; border: 1px solid %(border)s; padding: 3px; }
        QMenu::item { padding: 5px 24px 5px 23px; }
        QMenu::separator { height: 1px; background: %(border)s; margin: 4px 6px; }
        QToolBar { background: %(window)s; border: 0; border-bottom: 1px solid %(border)s; spacing: 2px; padding: 2px 4px; }
        QToolBar::separator { width: 1px; background: %(border)s; margin: 3px 5px; }
        QToolButton { color: %(text)s; border: 1px solid transparent; border-radius: 0; padding: 3px; }
        QToolButton:hover, QToolButton:checked { border: 1px solid #8cb6d9; background: %(hover)s; }
        QToolButton:disabled { color: %(muted)s; }
        QLineEdit, QComboBox, QSpinBox { background: %(base)s; color: %(text)s; border: 1px solid %(border)s; border-radius: 0; padding: 2px 5px; min-height: 18px; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #0078d7; }
        QPushButton { color: %(text)s; background: %(window)s; border: 1px solid %(border)s; border-radius: 1px; padding: 4px 12px; min-height: 18px; }
        QPushButton:hover { background: %(hover)s; border-color: #7fa6c7; }
        QPushButton:default { border: 1px solid #0078d7; }
        QPushButton:disabled { color: %(muted)s; }
        QTreeWidget, QListWidget { background: %(base)s; color: %(text)s; border: 1px solid %(border)s; outline: 0; }
        QTreeWidget::item, QListWidget::item { min-height: 22px; padding: 0 2px; }
        QTreeWidget::item:selected, QListWidget::item:selected { background: #0078d7; color: white; }
        QHeaderView::section { background: %(window)s; color: %(text)s; border: 0; border-right: 1px solid %(border)s; border-bottom: 1px solid %(border)s; padding: 3px 5px; }
        QDockWidget::title { background: %(window)s; color: %(text)s; padding: 4px 5px; border-bottom: 1px solid %(border)s; }
        QMainWindow::separator { background: %(window)s; width: 4px; height: 4px; }
        QTabWidget::pane { border: 1px solid %(border)s; top: -1px; }
        QTabBar::tab { background: %(window)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px 8px; margin-right: -1px; min-width: 58px; }
        QTabBar::tab:selected { background: %(selected)s; border-top: 2px solid #0078d7; padding-top: 3px; }
        QTabBar::tab:!selected { color: %(muted)s; }
        QTabBar::tab:left, QTabBar::tab:right { min-width:22px; max-width:22px; min-height:100px; max-height:100px; padding:0px; margin-right:0px; }
        QTabBar::close-button { width: 12px; height: 12px; }
        QStatusBar { background: %(window)s; color: %(text)s; border-top: 1px solid %(border)s; }
        QStatusBar::item { border: 0; border-left: 1px solid %(border)s; }
        QGroupBox { border: 1px solid %(border)s; margin-top: 10px; padding: 12px 10px 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        QPlainTextEdit { background: %(base)s; color: %(text)s; border: 1px solid %(border)s; }
        QScrollBar:vertical { width: 15px; }
    ''' % colors)


def icon(name, dark=False):
    """Original 16-DIP glyphs, rendered at 1x/2x. No vendor assets."""
    result = QIcon()
    ink = QColor('#d0d0d0' if dark else '#50555a')
    for scale in (1, 2):
        pixmap = QPixmap(16 * scale, 16 * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(scale)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(ink, 1.3))
        if name == 'folder':
            painter.setBrush(QColor('#f3c354')); painter.setPen(QPen(QColor('#b18a32'), .7))
            path = QPainterPath(); path.moveTo(1, 4); path.lineTo(6, 4); path.lineTo(8, 6)
            path.lineTo(15, 6); path.lineTo(14, 14); path.lineTo(1, 14); path.closeSubpath()
            painter.drawPath(path)
        elif name in ('connected', 'disconnected', 'pending'):
            if name == 'connected':
                painter.setPen(QPen(QColor('#24a148'), 2.5)); painter.drawLine(2, 8, 6, 12); painter.drawLine(6, 12, 14, 3)
            else:
                painter.setBrush(QColor('#df493e' if name == 'disconnected' else '#dfad38'))
                painter.setPen(Qt.PenStyle.NoPen); painter.drawEllipse(QRectF(2, 2, 12, 12))
                painter.setPen(QPen(QColor('white'), 1.6)); painter.drawLine(5, 8, 11, 8)
        elif name in ('terminal', 'quick', 'connect'):
            painter.drawRect(QRectF(1.5, 2.5, 13, 10)); painter.drawLine(4, 6, 6, 8)
            painter.drawLine(6, 8, 4, 10); painter.drawLine(8, 10, 11, 10)
            if name == 'quick':
                painter.setPen(QPen(QColor('#2489b8'), 1.8)); painter.drawLine(11, 1, 8, 7); painter.drawLine(8, 7, 13, 7)
        elif name == 'save':
            painter.drawRect(QRectF(2, 1.5, 12, 13)); painter.drawRect(QRectF(5, 2, 6, 4))
            painter.drawRect(QRectF(5, 9, 6, 5))
        elif name == 'log':
            painter.drawRect(QRectF(3, 1.5, 10, 13))
            for y in (5, 8, 11): painter.drawLine(5, y, 11, y)
        elif name == 'font':
            painter.drawLine(3, 13, 8, 2); painter.drawLine(8, 2, 13, 13)
            painter.drawLine(5, 9, 11, 9)
        elif name in ('copy', 'paste'):
            painter.drawRect(QRectF(5, 5, 9, 9)); painter.drawLine(2, 11, 2, 2)
            painter.drawLine(2, 2, 11, 2)
        elif name == 'search':
            painter.drawEllipse(QRectF(2, 1, 9, 9)); painter.drawLine(10, 10, 15, 15)
        elif name == 'settings':
            painter.drawEllipse(QRectF(3, 3, 10, 10)); painter.drawEllipse(QRectF(6, 6, 4, 4))
            for x, y, x2, y2 in ((8,0,8,3),(8,13,8,16),(0,8,3,8),(13,8,16,8),(2,2,4,4),(12,12,14,14),(2,14,4,12),(12,4,14,2)):
                painter.drawLine(x,y,x2,y2)
        elif name == 'sftp':
            painter.setBrush(QColor('#f3c354')); painter.setPen(QPen(QColor('#b18a32'), .7))
            painter.drawRect(QRectF(1, 3, 7, 3)); painter.drawRect(QRectF(1, 5, 13, 8))
            painter.setPen(QPen(QColor('#23734b'), 1.5)); painter.drawLine(8, 14, 8, 7)
            painter.drawLine(8, 7, 5, 10); painter.drawLine(8, 7, 11, 10)
        elif name == 'forward':
            painter.drawLine(1, 5, 14, 5); painter.drawLine(14, 5, 11, 2); painter.drawLine(14, 5, 11, 8)
            painter.drawLine(15, 11, 2, 11); painter.drawLine(2, 11, 5, 8); painter.drawLine(2, 11, 5, 14)
        elif name == 'close':
            painter.drawLine(4, 4, 12, 12); painter.drawLine(12, 4, 4, 12)
        elif name in ('up', 'down'):
            y, other = (10, 5) if name == 'up' else (5, 10)
            painter.drawLine(3, y, 8, other); painter.drawLine(8, other, 13, y)
        else:
            painter.drawRect(QRectF(2, 2, 12, 12)); painter.drawLine(5, 6, 11, 6); painter.drawLine(5, 10, 11, 10)
        painter.end()
        result.addPixmap(pixmap)
    return result
