import base64
import json
from pathlib import Path
import stat

from harbor_terminal.journal import SessionJournal


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_raw_logging_is_exact_and_tx_is_excluded_by_default(tmp_path):
    path=tmp_path/'capture.jsonl'
    journal=SessionJournal(path,mode='raw')
    journal.start()
    assert journal.record('RX',b'\x00\xff\x1b\r\n')
    assert not journal.record('TX',b'test-only-password')
    assert journal.event('disconnected')
    assert journal.close(2)
    rows=records(path)
    captured=[base64.b64decode(x['base64']) for x in rows if x['event']=='RX']
    assert b''.join(captured)==b'\x00\xff\x1b\r\n'
    assert not any(x['event']=='TX' for x in rows)
    assert 'test-only-password' not in path.read_text()
    assert sum(x['event']=='disconnected' for x in rows)==1
    assert rows[0]['event']=='log-start' and rows[-1]['event']=='log-stop'
    assert not journal.snapshot()['error']


def test_text_fragments_pause_resume_and_control_characters_are_explicit(tmp_path):
    path=tmp_path/'text.jsonl'
    journal=SessionJournal(path,mode='text',capture_tx=True)
    journal.start()
    raw='中文'.encode()
    for byte in raw:assert journal.record('RX',bytes([byte]))
    assert journal.pause(True)
    assert not journal.record('RX',b'must-not-appear')
    assert journal.pause(False)
    assert journal.record('RX',b'\x1b[31mred')
    assert journal.record('TX',b'test-command')
    assert journal.close(2)
    rows=records(path)
    assert ''.join(r.get('text','') for r in rows if r['event']=='RX')=='中文\x1b[31mred'
    assert [r['event'] for r in rows if r['event'] in ('pause','resume')]==['pause','resume']
    assert '\x1b' not in path.read_text()
    assert 'must-not-appear' not in path.read_text()
    assert any(r['event']=='TX' for r in rows)
    assert journal.snapshot()['files']==1


def test_decoder_does_not_join_bytes_across_an_intentional_gap(tmp_path):
    path=tmp_path/'pause.jsonl'
    journal=SessionJournal(path)
    journal.start();journal.record('RX',b'\xe4')
    journal.pause(True);journal.record('RX',b'\xb8\xad')
    journal.pause(False);journal.record('RX',b'ok')
    assert journal.close(2)
    rows=records(path)
    pause=next(r for r in rows if r['event']=='pause')
    assert pause['text_tails']['RX']=='\ufffd'
    assert rows[-2]['text']=='ok'
    assert '中' not in ''.join(r.get('text','') for r in rows)


def test_rotation_preserves_accepted_sequence_and_never_exceeds_limit(tmp_path):
    path=tmp_path/'rotating.jsonl'
    journal=SessionJournal(path,mode='raw',max_bytes=1024,max_files=20)
    journal.start()
    for i in range(30):assert journal.record('RX',bytes([i])*50)
    assert journal.close(2)
    segments=sorted(tmp_path.glob('rotating.jsonl*'))
    assert len(segments)>1
    assert all(p.stat().st_size<=1024 for p in segments)
    rows=[row for p in segments for row in records(p) if row['event']=='RX']
    assert [r['sequence'] for r in rows]==list(range(1,31))
    assert b''.join(base64.b64decode(r['base64']) for r in rows)==b''.join(bytes([i])*50 for i in range(30))
    assert not journal.snapshot()['error']


def test_capacity_failure_is_visible_and_existing_log_is_untouched(tmp_path):
    path=tmp_path/'existing';path.write_bytes(b'existing-user-file')
    journal=SessionJournal(path);journal.start()
    assert journal.close(2)
    assert path.read_bytes()==b'existing-user-file'
    assert journal.snapshot()['state']=='error'
    limited=SessionJournal(tmp_path/'limited',max_bytes=1024,max_files=1)
    for _ in range(20):limited.record('RX',b'x'*50)
    limited.start();assert limited.close(2)
    assert limited.snapshot()['state']=='error'
    assert (tmp_path/'limited').stat().st_size<=1024


def test_full_queue_and_unwritable_target_stop_logging_without_waiting(tmp_path):
    journal=SessionJournal(tmp_path/'queue',queue_bytes=200)
    assert not journal.record('RX',b'x'*300)
    assert journal.snapshot()['state']=='error'
    journal.start();assert journal.close(2)
    bad=SessionJournal(tmp_path)  # a directory cannot be opened as a new file
    bad.start();assert bad.close(2)
    assert bad.snapshot()['state']=='error'


def test_log_close_is_idempotent_and_final_partial_text_is_preserved(tmp_path):
    path=tmp_path/'final.jsonl'
    journal=SessionJournal(path);journal.start();journal.record('RX',b'\xe4')
    assert journal.close(2) and journal.close(2)
    assert records(path)[-1]['text_tails']['RX']=='\ufffd'
