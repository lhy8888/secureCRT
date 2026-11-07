import asyncio
import hashlib
from pathlib import Path

import asyncssh
import pytest

from harbor_terminal.sftp import (SFTPService,FileRequest,VerificationError,
                                 SourceChangedError,CommitUncertainError)
from harbor_terminal.transport import SSHTransport


@pytest.fixture
async def connected(sftp_endpoint):
    client=SSHTransport();await client.connect(**sftp_endpoint.options)
    yield client,SFTPService(client.connection),sftp_endpoint
    await client.close()


async def test_upload_download_binary_unicode_paths_and_hash_readback(connected,tmp_path):
    client,service,endpoint=connected
    payload=bytes(range(256))*700
    source=tmp_path/'上传.bin';source.write_bytes(payload)
    report=await service.execute(FileRequest('upload','/固件.bin',str(source)))
    assert report['size']==len(payload)
    assert report['sha256']==hashlib.sha256(payload).hexdigest()
    assert (endpoint.root/'固件.bin').read_bytes()==payload
    destination=tmp_path/'下载.bin'
    downloaded=await service.execute(FileRequest('download','/固件.bin',str(destination)))
    assert destination.read_bytes()==payload and downloaded['sha256']==report['sha256']
    assert not list(endpoint.root.glob('.harbor-*'))
    assert not list(tmp_path.glob('.harbor-download-*'))
    assert not report['cleanup_warning'] and not downloaded['cleanup_warning']
    assert endpoint.controls.authentications==1
    await client.write(b'shell-still-open\n')
    assert await asyncio.wait_for(client.read(),2)==b'shell-still-open\n'


async def test_existing_destinations_preserved_until_explicit_overwrite(connected,tmp_path):
    _,service,endpoint=connected
    remote=endpoint.root/'target';remote.write_bytes(b'original-remote')
    local=tmp_path/'source';local.write_bytes(b'new-content')
    with pytest.raises(asyncssh.SFTPError):
        await service.execute(FileRequest('upload','/target',str(local)))
    assert remote.read_bytes()==b'original-remote'
    destination=tmp_path/'destination';destination.write_bytes(b'original-local')
    with pytest.raises(FileExistsError):
        await service.execute(FileRequest('download','/target',str(destination)))
    assert destination.read_bytes()==b'original-local'
    await service.execute(FileRequest('upload','/target',str(local),overwrite=True))
    assert remote.read_bytes()==b'new-content'
    await service.execute(FileRequest('download','/target',str(destination),overwrite=True))
    assert destination.read_bytes()==b'new-content'


async def test_cancel_before_commit_cleans_staging_and_preserves_old_file(connected,tmp_path):
    _,service,endpoint=connected
    (endpoint.root/'target').write_bytes(b'original')
    source=tmp_path/'source';source.write_bytes(b'x'*200000)
    def cancel(phase,current,total):
        if phase=='transferring':raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.execute(FileRequest('upload','/target',str(source),overwrite=True),cancel)
    assert (endpoint.root/'target').read_bytes()==b'original'
    assert not list(endpoint.root.glob('.harbor-*'))


async def test_download_cancel_cleans_local_temp_and_preserves_old_file(connected,tmp_path):
    _,service,endpoint=connected
    (endpoint.root/'source').write_bytes(b'x'*200000)
    destination=tmp_path/'target';destination.write_bytes(b'original')
    def cancel(phase,current,total):
        if phase=='transferring':raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.execute(FileRequest('download','/source',str(destination),overwrite=True),cancel)
    assert destination.read_bytes()==b'original'
    assert not list(tmp_path.glob('.harbor-download-*'))


async def test_upload_readback_failure_never_replaces_target(connected,tmp_path):
    _,service,endpoint=connected
    endpoint.controls.corrupt_reads=True
    (endpoint.root/'target').write_bytes(b'original')
    source=tmp_path/'source';source.write_bytes(b'payload')
    with pytest.raises(VerificationError):
        await service.execute(FileRequest('upload','/target',str(source),overwrite=True))
    assert (endpoint.root/'target').read_bytes()==b'original'
    assert not list(endpoint.root.glob('.harbor-*'))


async def test_source_changed_during_upload_is_not_committed(connected,tmp_path):
    _,service,endpoint=connected
    source=tmp_path/'source';source.write_bytes(b'x'*200000)
    def change(phase,current,total):
        if phase=='transferring' and current==65536:
            source.write_bytes(b'y'*300000)
    with pytest.raises(SourceChangedError):
        await service.execute(FileRequest('upload','/target',str(source)),change)
    assert not (endpoint.root/'target').exists()
    assert not list(endpoint.root.glob('.harbor-*'))


async def test_unsupported_atomic_operation_fails_without_unsafe_fallback(connected,tmp_path):
    client,service,endpoint=connected
    endpoint.controls.deny_atomic=True
    source=tmp_path/'source';source.write_bytes(b'payload')
    with pytest.raises(asyncssh.SFTPOpUnsupported):
        await service.execute(FileRequest('upload','/target',str(source)))
    assert not (endpoint.root/'target').exists()
    assert not list(endpoint.root.glob('.harbor-*'))
    await client.write(b'still-connected\n')
    assert await asyncio.wait_for(client.read(),2)==b'still-connected\n'


async def test_directory_inventory_is_bounded_and_contains_types(connected,monkeypatch):
    _,service,endpoint=connected
    (endpoint.root/'folder').mkdir()
    for i in range(5):(endpoint.root/f'file-{i}').write_bytes(b'x')
    normal=await service.execute(FileRequest('list','/'))
    assert len(normal['entries'])==6
    assert any(x['name']=='folder' and x['kind']=='directory' for x in normal['entries'])
    monkeypatch.setattr('harbor_terminal.sftp.MAX_ENTRIES',3)
    limited=await service.execute(FileRequest('list','/'))
    assert len(limited['entries'])==3 and limited['truncated']


async def test_sftp_transfer_and_interactive_channel_make_progress_together(connected,tmp_path):
    client,service,endpoint=connected
    endpoint.controls.write_delay=.02
    source=tmp_path/'source';source.write_bytes(b'x'*1000000)
    started=asyncio.Event()
    def progress(phase,current,total):
        if phase=='transferring':started.set()
    task=asyncio.create_task(service.execute(FileRequest('upload','/target',str(source)),progress))
    try:
        await asyncio.wait_for(started.wait(),2)
        assert not task.done()
        await client.write(b'ctrl-channel\n')
        assert await asyncio.wait_for(client.read(),1)==b'ctrl-channel\n'
        assert not task.done()
        await asyncio.wait_for(task,5)
    finally:
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)


async def test_empty_file_roundtrip(connected,tmp_path):
    _,service,endpoint=connected
    source=tmp_path/'empty';source.write_bytes(b'')
    uploaded=await service.execute(FileRequest('upload','/empty',str(source)))
    destination=tmp_path/'download'
    downloaded=await service.execute(FileRequest('download','/empty',str(destination)))
    assert destination.read_bytes()==b''
    assert uploaded['sha256']==downloaded['sha256']==hashlib.sha256(b'').hexdigest()


async def test_one_to_three_byte_sftp_responses_do_not_end_transfers_early(connected,tmp_path):
    _,service,endpoint=connected
    endpoint.controls.tiny_reads=True
    payload=bytes(range(256))*4+'短读取回归'.encode()
    source=tmp_path/'source';source.write_bytes(payload)
    uploaded=await service.execute(FileRequest('upload','/fragmented.bin',str(source)))
    destination=tmp_path/'download'
    downloaded=await service.execute(FileRequest('download','/fragmented.bin',str(destination)))
    assert destination.read_bytes()==(endpoint.root/'fragmented.bin').read_bytes()==payload
    assert uploaded['size']==downloaded['size']==len(payload)
    assert uploaded['sha256']==downloaded['sha256']==hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize('action',['upload','download'])
async def test_premature_remote_eof_preserves_original_and_cleans_temp(connected,tmp_path,action):
    _,service,endpoint=connected
    endpoint.controls.read_cutoff=13
    source=tmp_path/'source';source.write_bytes(bytes(range(256)))
    if action=='upload':
        target=endpoint.root/'target';target.write_bytes(b'original')
        request=FileRequest('upload','/target',str(source),overwrite=True)
    else:
        (endpoint.root/'source').write_bytes(source.read_bytes())
        target=tmp_path/'target';target.write_bytes(b'original')
        request=FileRequest('download','/source',str(target),overwrite=True)
    with pytest.raises(SourceChangedError):await service.execute(request)
    assert target.read_bytes()==b'original'
    assert not list(endpoint.root.glob('.harbor-*'))
    assert not list(tmp_path.glob('.harbor-download-*'))


@pytest.mark.parametrize('path',['','\x00','/name\nnext'])
def test_invalid_remote_paths_are_rejected(path):
    with pytest.raises(ValueError):FileRequest('list',path)


async def test_lost_commit_reply_is_reported_as_uncertain_not_retried(connected,tmp_path):
    _,service,endpoint=connected
    endpoint.controls.stall_commit=True
    service.timeout=.05
    source=tmp_path/'source';source.write_bytes(b'commit-once')
    with pytest.raises(CommitUncertainError):
        await service.execute(FileRequest('upload','/target',str(source)))
    # The server applied the link but did not acknowledge it. A timeout must not
    # be reported as an ordinary pre-commit cancellation or trigger a replay.
    assert (endpoint.root/'target').read_bytes()==b'commit-once'


@pytest.mark.parametrize('action',['upload','download'])
async def test_late_cancel_after_acknowledged_commit_preserves_success(connected,tmp_path,action):
    _,service,endpoint=connected
    source=tmp_path/'source';source.write_bytes(b'complete-once')
    if action=='upload':
        request=FileRequest('upload','/target',str(source))
        target=endpoint.root/'target'
    else:
        (endpoint.root/'source').write_bytes(b'complete-once')
        target=tmp_path/'target'
        request=FileRequest('download','/source',str(target))
    def cancel_after_commit(phase,current,total):
        if phase=='complete':asyncio.current_task().cancel()
    task=asyncio.create_task(service.execute(request,cancel_after_commit))
    report=await task
    assert not task.cancelled()
    assert target.read_bytes()==b'complete-once'
    assert report['sha256']==hashlib.sha256(b'complete-once').hexdigest()
    assert not list(endpoint.root.glob('.harbor-*'))
    assert not list(tmp_path.glob('.harbor-download-*'))
