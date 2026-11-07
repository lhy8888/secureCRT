"""Exercise the bundled desktop on the OS executing it, then exit."""
from importlib.metadata import version
from pathlib import Path
import platform
import tempfile

from PySide6.QtCore import QTimer, Qt, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QFontDialog

from .reports import atomic_json


def desktop_smoke(app, report_path):
    from .app import Window, ConnectionOptions
    from .appearance import terminal_font
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    report_path = Path(report_path).resolve()
    if report_path.exists(): raise FileExistsError('Choose a new report path')
    result = dict(status='running', version=version('harbor-terminal'), platform=platform.platform(),
                  python=platform.python_version(), qt=qVersion(), checks={})
    atomic_json(report_path, result)
    with tempfile.TemporaryDirectory(prefix='harbor-smoke-') as temporary:
        window = Window(profile_path=Path(temporary)/'sessions.json')
        try:
            window.show(); app.processEvents()
            result['ui_font'] = QFontInfo(window.font()).family()
            result['terminal_font'] = QFontInfo(terminal_font()).family()
            screen = window.screen()
            result['display'] = dict(dpr=window.devicePixelRatioF(), dpi=screen.logicalDotsPerInch(),
                                      width=window.width(), height=window.height())
            result['checks']['mainwindow'] = window.isVisible() and bool(window.menuBar().actions())
            window.quick_action.trigger(); app.processEvents()
            result['checks']['quick_connect'] = window.quick_dialog.isVisible()
            def dismiss_options():
                modal = app.activeModalWidget()
                result['checks']['nested_options'] = isinstance(modal, ConnectionOptions) and modal.parentWidget() is window.quick_dialog
                if modal: modal.reject()
            QTimer.singleShot(50, dismiss_options); window.edit_options()
            window.quick_dialog.reject(); app.processEvents()
            def dismiss_font():
                modal = app.activeModalWidget()
                result['checks']['font_dialog'] = isinstance(modal, QFontDialog)
                if modal: modal.reject()
            QTimer.singleShot(50, dismiss_font); window.choose_terminal_font()
            result['checks']['no_connection_side_effect'] = not window.workers
            result['checks']['screenshot'] = window.grab().save(str(report_path.with_suffix('.png')))
            result['status'] = 'passed' if all(result['checks'].values()) else 'failed'
        except Exception as exc:
            result['status'] = 'failed'; result['error_type'] = type(exc).__name__
        finally:
            window.close(); app.processEvents()
    atomic_json(report_path, result)
    return 0 if result['status'] == 'passed' else 1
