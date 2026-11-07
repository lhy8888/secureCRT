"""Bounded, opt-in, session-local byte observation. Never decodes binary data."""
from collections import deque
from datetime import datetime, timezone
import threading
import time


class ByteTrace:
    def __init__(self, max_bytes=32768, max_records=256):
        self.max_bytes, self.max_records = max_bytes, max_records
        self.lock = threading.Lock()
        self.enabled = False
        self.capture_tx = False
        self.records = deque()
        self.bytes = self.dropped = self.sequence = 0
        self.offsets = dict(RX=0, TX=0)

    def configure(self, enabled, capture_tx=False):
        with self.lock:
            self.enabled, self.capture_tx = bool(enabled), bool(capture_tx)
            if not enabled:
                self.records.clear()
                self.bytes = 0

    def append(self, direction, data):
        if not data:
            return
        with self.lock:
            if not self.enabled or (direction == 'TX' and not self.capture_tx):
                return
            if direction not in self.offsets:
                raise ValueError('Invalid direction')
            for index in range(0, len(data), 1024):
                chunk = bytes(data[index:index + 1024])
                self.sequence += 1
                self.records.append(dict(id=self.sequence, time=time.time(), direction=direction,
                                         offset=self.offsets[direction], data=chunk))
                self.offsets[direction] += len(chunk)
                self.bytes += len(chunk)
                while self.bytes > self.max_bytes or len(self.records) > self.max_records:
                    old = self.records.popleft()
                    self.bytes -= len(old['data'])
                    self.dropped += len(old['data'])

    def snapshot(self, after=0):
        with self.lock:
            return dict(records=[dict(x) for x in self.records if x['id'] > after],
                        dropped=self.dropped, bytes=self.bytes)

    def clear(self):
        with self.lock:
            self.records.clear()
            self.bytes = self.dropped = 0
            self.offsets = dict(RX=0, TX=0)
            return self.sequence


def parse_hex(text):
    if len(text) > 12288:
        raise ValueError('Hex input is limited to 4096 bytes')
    # Permit separators, not arbitrary Python or escape expressions.
    compact = ''.join(text.split())
    if not compact or len(compact) % 2 or any(c not in '0123456789abcdefABCDEF' for c in compact):
        raise ValueError('Enter complete hexadecimal byte pairs, e.g. 00 FF 0D 0A')
    data = bytes.fromhex(compact)
    if len(data) > 4096:
        raise ValueError('Hex input is limited to 4096 bytes')
    return data


def format_record(record):
    timestamp = datetime.fromtimestamp(record['time'], timezone.utc).strftime('%H:%M:%S.%f')[:-3]
    data = record['data']
    lines = []
    for start in range(0, len(data), 16):
        part = data[start:start + 16]
        hexadecimal = ' '.join(f'{byte:02X}' for byte in part)
        ascii_text = ''.join(chr(byte) if 32 <= byte < 127 else '.' for byte in part)
        lines.append(f"{timestamp} {record['direction']} {record['offset']+start:08X}  {hexadecimal:<47}  |{ascii_text}|")
    return '\n'.join(lines)
