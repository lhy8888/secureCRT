import json
import os
import threading

import pytest

from harbor_terminal.hardware import serial_diagnostic


def test_loopback_requires_explicit_selection_before_opening_a_port(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('Device must not open without loopback selection')
    monkeypatch.setattr('harbor_terminal.hardware.serial.Serial', forbidden)
    with pytest.raises(ValueError):
        serial_diagnostic(tmp_path/'report.json', mode='loopback', port='COM3')
    assert not (tmp_path/'report.json').exists()


@pytest.mark.skipif(os.name=='nt', reason='Local Unix PTY; physical Windows loopback is separate')
def test_loopback_verifies_real_pty_frames_and_closes_the_handle(tmp_path):
    import pty
    import select
    master, slave = pty.openpty()
    stop = threading.Event()
    def echo():
        while not stop.is_set():
            if select.select([master], [], [], .05)[0]:
                data = os.read(master, 65536)
                if data: os.write(master, data)
    thread = threading.Thread(target=echo); thread.start()
    try:
        report = tmp_path/'loopback.json'
        assert serial_diagnostic(report, mode='loopback', port=os.ttyname(slave), seconds=1, loopback_only=True) == 0
        data = json.loads(report.read_text())
        assert data['status']=='passed' and data['frames']>1 and data['errors']==0
        assert data['bytes']==data['frames']*(10+8+256+16)
        assert data['elapsed_seconds']>=1 and data['latency_ms']['sample_size']>0
    finally:
        stop.set(); thread.join(2); assert not thread.is_alive()
        os.close(master); os.close(slave)


def test_hotplug_observes_removal_and_follows_serial_identity_to_new_port(tmp_path, monkeypatch):
    first = dict(device='COM3', serial_number='test-only-serial', hwid='test-fixture')
    returned = dict(first, device='COM9')
    observations = iter(([first], [], [returned]))
    monkeypatch.setattr('harbor_terminal.hardware.discover_ports', lambda: next(observations))
    report = tmp_path/'hotplug.json'
    assert serial_diagnostic(report, mode='hotplug', port='COM3', seconds=3) == 0
    data = json.loads(report.read_text())
    assert [e['event'] for e in data['events']]==['removed','returned']
    assert data['events'][1]['device']=='COM9' and data['identity_scope']=='serial_number'


def test_packaged_desktop_smoke_exercises_real_dialogs_and_writes_report(tmp_path):
    from PySide6.QtWidgets import QApplication
    from harbor_terminal.diagnostics import desktop_smoke
    app = QApplication.instance() or QApplication([])
    report = tmp_path/'desktop.json'
    assert desktop_smoke(app, report) == 0
    data = json.loads(report.read_text())
    assert data['status']=='passed' and all(data['checks'].values())
    assert data['checks']['nested_options'] and data['checks']['font_dialog']
    assert report.with_suffix('.png').is_file()


def test_hotplug_refuses_duplicate_serial_numbers_instead_of_false_identity_match(tmp_path,monkeypatch):
    monkeypatch.setattr('harbor_terminal.hardware.discover_ports',lambda:[
        dict(device='COM3',serial_number='duplicate'),dict(device='COM9',serial_number='duplicate')])
    report=tmp_path/'ambiguous.json'
    assert serial_diagnostic(report,mode='hotplug',port='COM3',seconds=1)==1
    data=json.loads(report.read_text())
    assert data['status']=='failed' and data['error_type']=='ValueError'
