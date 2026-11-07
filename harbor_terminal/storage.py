"""Bounded atomic documents with OS locks, revisions and last-good backups."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
import uuid


ANY_REVISION = object()


class StorageConflict(RuntimeError):
    """The document changed after it was read; the caller must reload."""


class StorageBusy(OSError):
    """Another process is committing this document."""


class CommitUncertain(OSError):
    """Replacement happened, but its durability could not be confirmed."""


@dataclass(frozen=True)
class Snapshot:
    value: object
    revision: str | None


def digest(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def atomic_bytes(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            try:
                directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                try: os.fsync(directory)
                finally: os.close(directory)
            except OSError:raise CommitUncertain('Replacement completed; reload to confirm saved contents') from None
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


@contextmanager
def document_lock(path):
    """Never unlink lock files: waiters must keep locking the same inode."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(str(path)+'.lock', flags, 0o600)
    acquired = False
    try:
        if os.name == 'nt':
            import msvcrt
            try: msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError: raise StorageBusy('Document is being saved by another process') from None
        else:
            import fcntl
            try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise StorageBusy('Document is being saved by another process') from None
        acquired = True
        if os.fstat(descriptor).st_size == 0: os.write(descriptor, b'\0')
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                import msvcrt
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


class DocumentStore:
    def __init__(self, path, decode, encode, *, limit=1048576):
        self.path = Path(path); self.decode = decode; self.encode = encode; self.limit = limit

    def _read_raw(self, path=None):
        try:
            with Path(path or self.path).open('rb') as stream: raw = stream.read(self.limit+1)
        except FileNotFoundError: return None
        if len(raw)>self.limit: raise ValueError('Document exceeds its size limit')
        return raw

    def revision(self):
        return digest(self._read_raw())

    def read(self):
        raw = self._read_raw()
        return Snapshot(self.decode(raw), digest(raw))

    def save(self, value, *, expected_revision=ANY_REVISION):
        raw = self.encode(value)
        if len(raw)>self.limit: raise ValueError('Document exceeds its size limit')
        with document_lock(self.path):
            previous = self._read_raw()
            if expected_revision is not ANY_REVISION and digest(previous)!=expected_revision:
                raise StorageConflict('Document changed; reload before saving')
            if previous is not None:
                self.decode(previous)  # Do not replace a damaged/unsupported document.
                atomic_bytes(str(self.path)+'.bak', previous)
            atomic_bytes(self.path, raw)
        return Snapshot(self.decode(raw), digest(raw))

    def restore_backup(self, *, expected_revision, expected_backup_revision=ANY_REVISION):
        with document_lock(self.path):
            current = self._read_raw()
            if digest(current)!=expected_revision: raise StorageConflict('Document changed before recovery')
            backup = self._read_raw(str(self.path)+'.bak')
            if backup is None: raise FileNotFoundError('No last-good backup exists')
            if expected_backup_revision is not ANY_REVISION and digest(backup)!=expected_backup_revision:
                raise StorageConflict('Backup changed after recovery preview')
            value = self.decode(backup)
            if current is not None:
                atomic_bytes(str(self.path)+'.damaged-'+uuid.uuid4().hex, current)
            atomic_bytes(self.path, backup)
        return Snapshot(value, digest(backup))
