import os
from pathlib import Path
import subprocess
import sys

import pytest

from harbor_terminal import profiles
from harbor_terminal.storage import document_lock,StorageConflict,CommitUncertain


def test_stale_revision_never_overwrites_another_edit_and_backup_restores_damage(tmp_path):
    path=tmp_path/'sessions.json';store=profiles.store(path)
    first=store.read();second=store.read()
    saved=store.save({'甲':{'host':'first.invalid'}},expected_revision=first.revision)
    with pytest.raises(StorageConflict):store.save({'乙':{'host':'lost.invalid'}},expected_revision=second.revision)
    assert profiles.load(path)==saved.value
    current=store.save({'甲':{'host':'updated.invalid'}},expected_revision=saved.revision)
    assert profiles.load(str(path)+'.bak')==saved.value
    path.write_text('{broken')
    recovered=store.restore_backup(expected_revision=store.revision())
    assert recovered.value==saved.value and profiles.load(path)==saved.value
    assert next(tmp_path.glob('sessions.json.damaged-*')).read_text()=='{broken'
    with pytest.raises(StorageConflict):store.save({},expected_revision=current.revision)


def test_lock_excludes_another_process_and_is_released_after_a_crash(tmp_path):
    path=tmp_path/'sessions.json'
    probe="""import sys,os
from harbor_terminal.storage import document_lock,StorageBusy
try:
    with document_lock(sys.argv[1]):
        os._exit(0)
except StorageBusy: sys.exit(17)
"""
    def child():return subprocess.run([sys.executable,'-c',probe,str(path)],timeout=10,capture_output=True)
    with document_lock(path):assert child().returncode==17
    assert child().returncode==0
    # The crashed child did not unlink the lock; the OS released it.
    assert Path(str(path)+'.lock').exists()
    profiles.save(path,{'after-crash':{'host':'example.invalid'}})
    assert 'after-crash' in profiles.load(path)


def test_failed_replacement_preserves_original_and_valid_backup(tmp_path,monkeypatch):
    import harbor_terminal.storage as storage
    path=tmp_path/'sessions.json';profiles.save(path,{'first':{'host':'first.invalid'}});original=path.read_bytes()
    replace=storage.os.replace
    def fail_commit(source,destination):
        if Path(destination)==path:raise OSError('fixture failure before replacement')
        return replace(source,destination)
    monkeypatch.setattr(storage.os,'replace',fail_commit)
    with pytest.raises(OSError):profiles.save(path,{'next':{'host':'next.invalid'}})
    assert path.read_bytes()==original and Path(str(path)+'.bak').read_bytes()==original
    assert not list(tmp_path.glob('.sessions.json-*'))


@pytest.mark.skipif(os.name=='nt',reason='Directory fsync durability reporting is a POSIX path')
def test_post_replacement_durability_failure_is_reported_as_uncertain(tmp_path,monkeypatch):
    import harbor_terminal.storage as storage
    import stat
    path=tmp_path/'sessions.json';real=storage.os.fsync
    def fail_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):raise OSError('fixture directory sync failure')
        real(descriptor)
    monkeypatch.setattr(storage.os,'fsync',fail_directory)
    with pytest.raises(CommitUncertain):profiles.save(path,{'new':{'host':'written.invalid'}})
    assert profiles.load(path)=={'new':{'host':'written.invalid'}}


def test_credentials_or_unsupported_document_cannot_be_silently_rewritten(tmp_path):
    path=tmp_path/'sessions.json';raw=b'{"version":4,"sessions":{},"password":"fixture-only"}'
    path.write_bytes(raw)
    with pytest.raises(ValueError):profiles.load(path)
    with pytest.raises(ValueError):profiles.save(path,{})
    assert path.read_bytes()==raw
