"""Explicit local serial inventory, loopback and re-enumeration diagnostics."""
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import platform
import time
import uuid

import serial

from .reports import atomic_json, resources
from .serial_config import discover_ports


def serial_diagnostic(report_path, *, mode='inventory', port=None, baudrate=115200,
                      seconds=60, loopback_only=False):
    report_path = Path(report_path)
    if report_path.exists(): raise FileExistsError('Choose a new report path')
    if mode not in ('inventory', 'loopback', 'hotplug'): raise ValueError('Invalid diagnostic mode')
    if not 1 <= seconds <= 604800: raise ValueError('Duration must be 1 second to 7 days')
    if mode != 'inventory' and not port: raise ValueError('Choose an explicit serial port')
    if mode == 'loopback' and not loopback_only:
        raise ValueError('Loopback wiring confirmation is required before sending bytes')
    if type(baudrate) is not int or not 50 <= baudrate <= 4000000: raise ValueError('Invalid baud rate')
    started = time.monotonic()
    result = dict(status='running', mode=mode, platform=platform.platform(),
        started=datetime.now(timezone.utc).isoformat(), requested_seconds=seconds,
        elapsed_seconds=0, port=port, baudrate=baudrate, frames=0, bytes=0,
        errors=0, inventory=discover_ports(), samples=[], resources=resources())
    atomic_json(report_path, result)
    device = None
    latencies = deque(maxlen=2048)
    try:
        if mode == 'inventory':
            result['status'] = 'passed'
        elif mode == 'hotplug':
            original = next((p for p in result['inventory'] if p['device'].casefold() == port.casefold()), None)
            if original is None: raise ValueError('Port is not present in the initial inventory')
            removed = False; returned = False
            events = []
            while time.monotonic() - started < seconds:
                inventory = discover_ports()
                identity = original.get('serial_number')
                match = next((p for p in inventory if (identity and p.get('serial_number') == identity)
                    or (not identity and p['device'].casefold() == port.casefold())), None)
                if not match and not removed:
                    removed = True; events.append(dict(event='removed', elapsed=time.monotonic()-started))
                if match and removed:
                    returned = True; events.append(dict(event='returned', device=match['device'], elapsed=time.monotonic()-started)); break
                result.update(elapsed_seconds=time.monotonic()-started, events=events, resources=resources())
                atomic_json(report_path, result); time.sleep(.5)
            result['status'] = 'passed' if removed and returned else 'incomplete'
            result['events'] = events
            result['identity_scope'] = 'serial_number' if original.get('serial_number') else 'port_name_only'
        else:
            # Open only after explicit loopback selection. Do not toggle control
            # lines during the test, replay writes or reconnect after a failure.
            device = serial.Serial()
            device.port = port; device.baudrate = baudrate
            device.timeout = .2; device.write_timeout = 2
            device.xonxoff = device.rtscts = device.dsrdtr = False
            device.dtr = False; device.rts = False
            device.open()
            if os.name == 'nt':
                try:
                    other = serial.Serial(port, baudrate, timeout=.1)
                except serial.SerialException: result['exclusive_open'] = 'passed'
                else:
                    other.close(); result['exclusive_open'] = 'failed'; raise RuntimeError('Port was not exclusive')
            else: result['exclusive_open'] = 'not_validated_on_this_platform'
            result['loopback_only'] = True
            sequence = 0; last_report = started
            while time.monotonic() - started < seconds:
                # Includes all byte values; flow control is deliberately off.
                frame = b'HARBOR-LB-' + sequence.to_bytes(8, 'big') + bytes(range(256)) + uuid.uuid4().bytes
                before = time.monotonic()
                if device.write(frame) != len(frame): raise IOError('Incomplete serial write; no replay')
                incoming = bytearray()
                while len(incoming) < len(frame) and time.monotonic() - before < 3:
                    data = device.read(len(frame)-len(incoming))
                    if not data: continue
                    incoming.extend(data)
                if bytes(incoming) != frame: raise IOError('Loopback byte mismatch or timeout')
                latencies.append((time.monotonic()-before)*1000)
                result['frames'] += 1; result['bytes'] += len(frame); sequence += 1
                now = time.monotonic()
                if now-last_report >= 5:
                    snapshot = resources(); snapshot['elapsed'] = now-started
                    result['samples'] = (result['samples']+[snapshot])[-4096:]
                    result.update(elapsed_seconds=now-started, resources=snapshot)
                    atomic_json(report_path, result); last_report = now
                time.sleep(.01)
            if not result['frames']: raise IOError('No frames were verified')
            result['status'] = 'passed'
    except KeyboardInterrupt:
        result['status'] = 'interrupted'
    except Exception as exc:
        result['status'] = 'failed'; result['error_type'] = type(exc).__name__; result['errors'] += 1
    finally:
        if device:
            try: device.close()
            except Exception: result['close_error'] = True; result['status'] = 'failed'
        result['elapsed_seconds'] = time.monotonic()-started
        result['resources'] = resources()
        if latencies:
            ordered = sorted(latencies)
            result['latency_ms'] = dict(sample_size=len(ordered), p50=ordered[len(ordered)//2],
                p95=ordered[min(len(ordered)-1,int(len(ordered)*.95))], maximum=ordered[-1])
        atomic_json(report_path, result)
    return 0 if result['status'] == 'passed' else 1
