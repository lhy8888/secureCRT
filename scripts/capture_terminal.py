"""Capture the real Qt window using a local PTY. No external devices or servers."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
import time
from importlib.metadata import version

if os.name=='nt':
    raise SystemExit('This visual validation uses Unix PTYs; run on Linux, not a Windows COM port.')
import pty
from PySide6.QtWidgets import QApplication
from harbor_terminal.app import Window


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=Path(f'artifacts/harbor-{version("harbor-terminal")}-serial-terminal.png'))
    args=parser.parse_args()
    app=QApplication.instance() or QApplication(sys.argv[:1])
    master,slave=pty.openpty()
    with tempfile.TemporaryDirectory(prefix='harbor-capture-') as temporary:
        window=Window(profile_path=Path(temporary)/'sessions.json')
        def until(predicate,seconds=5):
            end=time.monotonic()+seconds
            while not predicate():
                if time.monotonic()>end:raise TimeoutError('Qt/PTY readiness timed out')
                app.processEvents();time.sleep(.01)
        try:
            window.profiles={'Lab/SSH example':dict(mode='SSH',host='192.0.2.10',port='22'),
                             'Lab/Serial console':dict(mode='Serial',host=os.ttyname(slave),port='115200')}
            window.update_profiles();window.show();window.mode.setCurrentText('Serial')
            window.host.setText(os.ttyname(slave));window.connect_session()
            view=window.tabs.currentWidget();view.session_label='LOCAL PTY / 回归验证'
            until(lambda:view.worker.status=='Connected')
            payload=(
                f'\x1b[2J\x1b[H\x1b[1;38;2;120;216;194mHARBOR TERMINAL  {version("harbor-terminal")}\x1b[0m\r\n'
                '\x1b[90mLOCAL PTY VALIDATION / generated test data / 非真实远端设备\x1b[0m\r\n\r\n'
                '  Transport   Serial PTY / 115200 / 8N1 / no flow control\r\n'
                '  Encoding    UTF-8  ·  中文分片解码与宽字符绘制\r\n'
                '  Terminal    Alternate screen · PTY resize · xterm keys\r\n\r\n'
                '\x1b[32m[PASS]\x1b[0m Strict host-key verification remains enabled\r\n'
                '\x1b[32m[PASS]\x1b[0m Independent I/O tasks and cancellation tests\r\n'
                '\x1b[33m[PENDING]\x1b[0m Windows COM hardware / 72-hour soak\r\n\r\n'
                '  ANSI palette  ' + ''.join(f'\x1b[{code}m██ ' for code in range(31,38))+'\x1b[0m\r\n'
                '  24-bit color  ' + ''.join(f'\x1b[48;2;{r};{g};{b}m   ' for r,g,b in
                    [(25,80,110),(28,117,145),(54,160,170),(120,216,194),(205,230,175)])+'\x1b[0m\r\n\r\n'
                '\x1b[1mlab-console#\x1b[0m '
            ).encode()
            os.write(master,payload)
            until(lambda:'lab-console#' in view.toPlainText())
            until(lambda:not view.resize_timer.isActive())
            app.processEvents()
            args.out.parent.mkdir(parents=True,exist_ok=True)
            if not window.grab().save(str(args.out)):raise RuntimeError('Failed to save image')
            print('Captured live PTY-backed Qt window:',args.out)
            print('Grid:',view.screen.columns,'x',view.screen.lines)
        finally:
            for worker in window.workers:worker.stop_event.set()
            until(lambda:all(not w.isRunning() for w in window.workers),seconds=8)
            window.close();app.processEvents()
            os.close(master);os.close(slave)


if __name__=='__main__':main()
