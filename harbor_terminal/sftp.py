"""Bounded SFTP operations on an already authenticated SSH connection.

Transfers stage into exclusive temporary files. Downloads verify their local
readback; uploads verify a remote readback. Publishing never uses delete-then-
rename. Unknown commit outcomes are reported, never automatically retried.
"""
import asyncio
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import posixpath
import stat
import tempfile
import uuid

import asyncssh

BLOCK_SIZE = 65536
MAX_ENTRIES = 2000
MAX_FILE_SIZE = 1 << 40


class VerificationError(IOError):
    pass


class SourceChangedError(IOError):
    pass


class CommitUncertainError(IOError):
    pass


@dataclass(frozen=True)
class FileRequest:
    action: str
    remote_path: str = '.'
    local_path: str = ''
    overwrite: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self):
        if self.action not in ('list', 'upload', 'download') or type(self.overwrite) is not bool:
            raise ValueError('Invalid file operation')
        if not isinstance(self.remote_path, str) or not self.remote_path or len(self.remote_path) > 4096:
            raise ValueError('Invalid remote path')
        if any(ord(c) < 32 or ord(c) == 127 for c in self.remote_path):
            raise ValueError('Control characters in remote path')
        if self.action != 'list' and (not isinstance(self.local_path, str) or not self.local_path
                                      or '\0' in self.local_path or len(self.local_path) > 32768):
            raise ValueError('Invalid local path')


async def disk_call(function, *args):
    """Join a disk operation before its file descriptor can be closed or reused."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def acquire_resource(function, dispose):
    task = asyncio.create_task(asyncio.to_thread(function))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        resource = await task
        await disk_call(dispose, resource)
        raise


class SFTPService:
    def __init__(self, connection, *, timeout=10):
        self.connection = connection
        self.timeout = timeout
        self.cleanup_failed = False

    async def rpc(self, operation):
        return await asyncio.wait_for(operation, self.timeout)

    async def cleanup(self, operation, *, missing_ok=False):
        """Finish bounded cleanup without rewriting a known commit as cancelled."""
        task = asyncio.create_task(operation)
        try:
            try:
                await asyncio.wait_for(asyncio.shield(task), 2)
            except asyncio.CancelledError:
                # A late cancellation cannot undo an acknowledged publication.
                await asyncio.wait_for(task, 2)
        except asyncssh.SFTPNoSuchFile:
            if not missing_ok:
                self.cleanup_failed = True
        except (Exception, asyncio.CancelledError):
            self.cleanup_failed = True
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def cancellation_checkpoint():
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError()

    async def execute(self, request, progress=lambda *_: None):
        self.cleanup_failed = False
        client = await self.rpc(self.connection.start_sftp_client())
        result = None
        try:
            if request.action == 'list':
                result = await self.list_directory(client, request.remote_path)
            elif request.action == 'upload':
                result = await self.upload(client, request, progress)
            else:
                result = await self.download(client, request, progress)
            return result
        finally:
            client.exit()
            await self.cleanup(client.wait_closed())
            if result is not None:
                result['cleanup_warning'] = self.cleanup_failed

    async def list_directory(self, client, path):
        path = await self.rpc(client.realpath(path))
        entries = []
        truncated = False
        name_bytes = 0
        if not isinstance(path, str) or len(path) > 4096:
            raise ValueError('Remote directory path is too long')
        iterator = client.scandir(path)
        try:
            while True:
                try:
                    item = await self.rpc(anext(iterator))
                except StopAsyncIteration:
                    break
                if item.filename in ('.', '..'):
                    continue
                name_bytes += len(item.filename.encode('utf-8'))
                if len(entries) == MAX_ENTRIES or len(item.filename) > 4096 or name_bytes > 2 * 1024 * 1024:
                    truncated = True
                    break
                permissions = item.attrs.permissions or 0
                kind = ('directory' if stat.S_ISDIR(permissions) else 'link'
                        if stat.S_ISLNK(permissions) else 'file' if stat.S_ISREG(permissions) else 'other')
                entries.append(dict(name=item.filename, kind=kind, size=item.attrs.size,
                                    mtime=item.attrs.mtime))
        finally:
            await self.cleanup(iterator.aclose())
        return dict(path=path, entries=entries, truncated=truncated)

    @staticmethod
    def file_size(attrs):
        size = attrs.size
        if size is None or not 0 <= size <= MAX_FILE_SIZE:
            raise ValueError('Unsupported file size')
        if attrs.permissions and not stat.S_ISREG(attrs.permissions):
            raise ValueError('Only regular files are supported')
        return size

    async def remote_hash(self, client, path, expected_size, progress):
        handle = await self.rpc(client.open(path, 'rb', encoding=None))
        digest = hashlib.sha256()
        count = 0
        try:
            while True:
                data = await self.rpc(handle.read(min(BLOCK_SIZE, expected_size - count + 1)))
                if not data:
                    break
                count += len(data)
                if count > expected_size:
                    raise SourceChangedError('Remote file size changed')
                digest.update(data)
                progress('verifying', count, expected_size)
        finally:
            await self.cleanup(handle.close())
        if count != expected_size:
            raise SourceChangedError('Remote file size changed')
        return digest.hexdigest()

    async def upload(self, client, request, progress):
        path = Path(request.local_path)
        local = await acquire_resource(lambda: path.open('rb'), lambda file: file.close())
        temporary = posixpath.join(posixpath.dirname(request.remote_path) or '.',
                                   '.harbor-upload-' + uuid.uuid4().hex + '.part')
        remote = None
        created = False
        committing = False
        try:
            before = await disk_call(os.fstat, local.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_SIZE:
                raise ValueError('Only regular files up to 1 TiB are supported')
            if not request.overwrite:
                try:
                    await self.rpc(client.lstat(request.remote_path))
                except asyncssh.SFTPNoSuchFile:
                    pass
                else:
                    raise asyncssh.SFTPFileAlreadyExists('Destination already exists')
            remote = await self.rpc(client.open(temporary, 'xb', encoding=None,
                attrs=asyncssh.SFTPAttrs(permissions=0o600)))
            created = True
            count = 0
            digest = hashlib.sha256()
            while True:
                data = await disk_call(local.read, BLOCK_SIZE)
                if not data:
                    break
                count += len(data)
                if count > before.st_size:
                    raise SourceChangedError('Local file grew')
                written = await self.rpc(remote.write(data))
                if written != len(data):
                    raise IOError('Incomplete SFTP write')
                digest.update(data)
                progress('transferring', count, before.st_size)
            await self.rpc(remote.close())
            remote = None
            after = await disk_call(os.fstat, local.fileno())
            if count != before.st_size or after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
                raise SourceChangedError('Local file changed')
            observed = await self.remote_hash(client, temporary, count, progress)
            if observed != digest.hexdigest():
                raise VerificationError('Remote readback mismatch')
            self.cancellation_checkpoint()
            progress('committing', count, count)
            committing = True
            if request.overwrite:
                await self.rpc(client.posix_rename(temporary, request.remote_path))
            else:
                # A hard link creates the destination without a check/rename race.
                # Servers without this extension fail safely; no unsafe fallback.
                await self.rpc(client.link(temporary, request.remote_path))
            committing = False
            progress('complete', count, count)
            return dict(size=count, sha256=observed, path=request.remote_path)
        except (asyncio.CancelledError, TimeoutError, asyncssh.ConnectionLost, asyncssh.SFTPConnectionLost) as exc:
            if committing:
                raise CommitUncertainError('Commit result unknown; inspect destination before retrying') from exc
            if not created:
                self.cleanup_failed = True  # An exclusive OPEN reply may have been lost.
            raise
        finally:
            if remote:
                await self.cleanup(remote.close())
            await self.cleanup(disk_call(local.close))
            if created:
                await self.cleanup(client.remove(temporary), missing_ok=True)

    async def download(self, client, request, progress):
        destination = Path(request.local_path)
        if not request.overwrite and await disk_call(destination.exists):
            raise FileExistsError('Local destination exists')
        remote = await self.rpc(client.open(request.remote_path, 'rb', encoding=None))
        local = temporary = None
        committing = False
        try:
            expected = self.file_size(await self.rpc(remote.stat()))
            def make_temp():
                fd, name = tempfile.mkstemp(prefix='.harbor-download-', suffix='.part', dir=destination.parent)
                return os.fdopen(fd, 'w+b'), Path(name)
            def dispose(resource):
                file, name = resource
                file.close()
                name.unlink(missing_ok=True)
            local, temporary = await acquire_resource(make_temp, dispose)
            count = 0
            digest = hashlib.sha256()
            while True:
                data = await self.rpc(remote.read(min(BLOCK_SIZE, expected - count + 1)))
                if not data:
                    break
                count += len(data)
                if count > expected:
                    raise SourceChangedError('Remote file grew')
                if await disk_call(local.write, data) != len(data):
                    raise IOError('Incomplete local write')
                digest.update(data)
                progress('transferring', count, expected)
            if count != expected:
                raise SourceChangedError('Remote file changed')
            await disk_call(local.flush)
            await disk_call(os.fsync, local.fileno())
            await disk_call(local.seek, 0)
            readback = hashlib.sha256()
            checked = 0
            while True:
                data = await disk_call(local.read, BLOCK_SIZE)
                if not data:
                    break
                readback.update(data)
                checked += len(data)
                progress('verifying', checked, expected)
            if readback.digest() != digest.digest():
                raise VerificationError('Local readback mismatch')
            await disk_call(local.close)
            local = None
            self.cancellation_checkpoint()
            progress('committing', count, count)
            committing = True
            if request.overwrite:
                await disk_call(os.replace, temporary, destination)
            else:
                await disk_call(os.link, temporary, destination)
            committing = False
            progress('complete', count, count)
            return dict(size=count, sha256=digest.hexdigest(), path=str(destination))
        except (asyncio.CancelledError, TimeoutError) as exc:
            if committing:
                raise CommitUncertainError('Local commit result unknown; inspect destination') from exc
            raise
        finally:
            await self.cleanup(remote.close())
            if local:
                await self.cleanup(disk_call(local.close))
            if temporary:
                await self.cleanup(disk_call(lambda: temporary.unlink(missing_ok=True)))


def file_error(exc):
    """Stable UI codes; server-provided error descriptions are not trusted UI."""
    if isinstance(exc, CommitUncertainError):
        return 'uncertain', '提交结果未知，请检查目标文件后再决定是否重试；不会自动重发'
    if isinstance(exc, (FileExistsError, asyncssh.SFTPFileAlreadyExists)):
        return 'exists', '目标已存在，本次没有授权覆盖'
    if isinstance(exc, asyncssh.SFTPOpUnsupported):
        return 'unsupported', '服务器不支持所需的安全提交或SFTP操作，没有进行不安全降级'
    if isinstance(exc, (PermissionError, asyncssh.SFTPPermissionDenied)):
        return 'permission', '文件或目录权限不足'
    if isinstance(exc, (FileNotFoundError, asyncssh.SFTPNoSuchFile)):
        return 'missing', '文件或目录不存在'
    if isinstance(exc, (VerificationError, SourceChangedError)):
        return 'verification', '校验失败或源文件发生变化，目标未提交'
    if isinstance(exc, TimeoutError):
        return 'timeout', 'SFTP操作超时'
    return type(exc).__name__, 'SFTP操作失败，请检查连接、路径、磁盘空间和服务端能力'
