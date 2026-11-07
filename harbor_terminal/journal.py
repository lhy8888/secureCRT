"""Opt-in bounded JSONL receive logging on a dedicated disk writer thread.

No authentication packets or credential options enter this component. Sending
data is excluded unless the user explicitly enables TX. Raw records use base64;
text records JSON-escape control characters. A failed log stops itself, not I/O.
"""
import base64
import codecs
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import threading
import time


class SessionJournal:
    def __init__(self, path, *, mode='text', encoding='utf-8', capture_tx=False,
                 max_bytes=10 * 1024 * 1024, max_files=5, queue_bytes=1024 * 1024):
        if (mode not in ('text', 'raw') or type(max_bytes) is not int
                or not 1024 <= max_bytes <= 100 * 1024 * 1024 or type(capture_tx) is not bool):
            raise ValueError('Invalid log format or file limit')
        if type(max_files) is not int or type(queue_bytes) is not int or not 1 <= max_files <= 20 or queue_bytes < 1:
            raise ValueError('Invalid log capacity')
        codecs.lookup(encoding)
        self.path = Path(path)
        self.mode, self.encoding = mode, encoding
        self.capture_tx = capture_tx
        self.max_bytes, self.max_files, self.capacity = max_bytes, max_files, queue_bytes
        self.lock = threading.Lock()
        self.queue = queue.Queue(maxsize=256)
        self.stop = threading.Event()
        self.paused = False
        self.state, self.error = 'opening', ''
        self.queued = self.written = self.file_count = self.accepted = 0
        self.thread = threading.Thread(target=self._run, name='HarborLog', daemon=True)
        self.started_at = time.time()

    @staticmethod
    def _create(path):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            return os.fdopen(descriptor, 'wb')
        except Exception:
            os.close(descriptor)
            raise

    def start(self):
        self.thread.start()

    def _enqueue(self, kind, data=b''):
        with self.lock:
            if self.state not in ('opening', 'running'):
                return False
            if kind in ('RX', 'TX'):
                if self.paused or (kind == 'TX' and not self.capture_tx):
                    return False
            return self._put_locked(kind, data)

    def _put_locked(self, kind, data=b''):
        cost = len(data) + 128
        if self.queued + cost > self.capacity or self.queue.full():
            self.state, self.error = 'error', '日志队列已满，已停止日志；终端继续运行'
            self.stop.set()
            return False
        self.accepted += 1
        self.queue.put_nowait((self.accepted, time.time(), kind, bytes(data), cost))
        self.queued += cost
        return True

    def record(self, direction, data):
        if direction not in ('RX', 'TX'):
            raise ValueError('Invalid log direction')
        return self._enqueue(direction, data) if data else False

    def event(self, name):
        if name not in ('connected', 'disconnected'):
            raise ValueError('Invalid lifecycle event')
        return self._enqueue(name)

    def pause(self, paused):
        with self.lock:
            if self.state not in ('opening', 'running'):
                return False
            if self.paused == bool(paused):
                return True
            accepted = self._put_locked('pause' if paused else 'resume')
            self.paused = bool(paused)
            return accepted

    def close(self, timeout=None):
        with self.lock:
            if self.state in ('opening', 'running'):
                self.state = 'closing'
        self.stop.set()
        if timeout is not None:
            self.thread.join(timeout)
            return not self.thread.is_alive()
        return True

    def snapshot(self):
        with self.lock:
            return dict(state=self.state, error=self.error, paused=self.paused,
                        written=self.written, files=self.file_count, queued=self.queued,
                        alive=self.thread.is_alive(), mode=self.mode, capture_tx=self.capture_tx)

    def _run(self):
        file = None
        size = 0
        decoders = {d:codecs.getincrementaldecoder(self.encoding)(errors='replace') for d in ('RX','TX')}
        def finish_decoders():
            tails = {direction:decoder.decode(b'', final=True) for direction,decoder in decoders.items()}
            for direction in decoders:
                decoders[direction] = codecs.getincrementaldecoder(self.encoding)(errors='replace')
            return {direction:value for direction,value in tails.items() if value}
        def write_record(record):
            nonlocal file, size
            payload = json.dumps(record, ensure_ascii=True).encode() + b'\n'
            if size + len(payload) > self.max_bytes:
                if self.file_count >= self.max_files:
                    raise OSError('Log capacity reached')
                file.flush(); os.fsync(file.fileno()); file.close()
                file = self._create(self.path.with_name(self.path.name + f'.{self.file_count:03d}'))
                with self.lock:
                    self.file_count += 1
                file.write(header)
                size = len(header)
            if size + len(payload) > self.max_bytes:
                raise OSError('Record exceeds log segment limit')
            if file.write(payload) != len(payload):
                raise OSError('Incomplete log write')
            size += len(payload)
            file.flush()
        try:
            # Exclusive creation: a stale or existing log is never truncated.
            file = self._create(self.path)
            with self.lock:
                self.file_count = 1
                if self.state == 'opening':
                    self.state = 'running'
            header = json.dumps(dict(version=1, event='log-start', format=self.mode,
                time=datetime.fromtimestamp(self.started_at, timezone.utc).isoformat(timespec='milliseconds'),
                encoding=self.encoding, capture_tx=self.capture_tx), ensure_ascii=True).encode() + b'\n'
            file.write(header)
            size += len(header)
            while not self.stop.is_set() or not self.queue.empty():
                try:
                    sequence, timestamp, kind, data, cost = self.queue.get(timeout=.05)
                except queue.Empty:
                    continue
                with self.lock:
                    self.queued -= cost
                record = dict(sequence=sequence,
                    time=datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec='milliseconds'),
                    event=kind)
                if kind in decoders:
                    record['bytes'] = len(data)
                    if self.mode == 'raw':
                        record['base64'] = base64.b64encode(data).decode('ascii')
                    else:
                        record['text'] = decoders[kind].decode(data)
                elif kind in ('pause', 'resume') and self.mode == 'text':
                    record['text_tails'] = finish_decoders()
                write_record(record)
                with self.lock:
                    self.written += len(data)
            write_record(dict(event='log-stop',
                time=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                text_tails=finish_decoders() if self.mode == 'text' else {}))
            file.flush()
            os.fsync(file.fileno())
        except Exception as exc:
            with self.lock:
                self.state = 'error'
                if not self.error:
                    self.error = type(exc).__name__ + ': 日志无法继续写入，终端仍可使用'
            self.stop.set()
        finally:
            if file:
                try:
                    file.close()
                except OSError:
                    with self.lock:
                        self.state, self.error = 'error', '日志关闭失败'
            with self.lock:
                if self.state != 'error':
                    self.state = 'closed'
            while True:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break
            with self.lock:
                self.queued = 0
