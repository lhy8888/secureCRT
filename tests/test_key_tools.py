import asyncio
import os
from pathlib import Path
import threading

import asyncssh
import pytest

from harbor_terminal import host_keys
from harbor_terminal.key_tools import generate_identity,public_info,GenerationCancelled,identity_bytes
from harbor_terminal.storage import StorageConflict
from harbor_terminal.transport import SSHTransport


@pytest.mark.parametrize('algorithm',['Ed25519','RSA 3072','ECDSA P-256'])
async def test_generated_encrypted_identities_authenticate_to_actual_ssh(algorithm,tmp_path,monkeypatch):
    path=tmp_path/'identity';password='fixture-passphrase-only'
    info=generate_identity(path,algorithm,password)
    assert info['fingerprint']==public_info(path,password)['fingerprint']
    public=asyncssh.read_public_key(str(path)+'.pub')
    signatures=[];sign=type(public).sign
    def observe(self,data,sig_algorithm):
        if self.public_data==public.public_data:signatures.append(sig_algorithm)
        return sign(self,data,sig_algorithm)
    monkeypatch.setattr(type(public),'sign',observe)
    assert public.get_fingerprint('sha256')==info['fingerprint']
    with pytest.raises(asyncssh.KeyEncryptionError):public_info(path,'wrong-fixture-passphrase')
    class Server(asyncssh.SSHServer):
        def begin_auth(self,username):return True
        def public_key_auth_supported(self):return True
        def validate_public_key(self,username,key):return username=='tester' and key.public_data==public.public_data
    async def echo(process):
        data=await process.stdin.read(1024);process.stdout.write(data)
    host=asyncssh.generate_private_key('ssh-ed25519')
    server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[host],process_factory=echo,encoding=None,line_editor=False,
        signature_algs=['rsa-sha2-256','ssh-ed25519','ecdsa-sha2-nistp256'])
    known=tmp_path/'known';known.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode()+host.export_public_key())
    client=SSHTransport()
    try:
        await client.connect('127.0.0.1','tester',port=server.get_port(),known_hosts=known,client_keys=[str(path)],
            passphrase=password,auth_method='publickey-only')
        await client.write(b'generated-key#');assert await asyncio.wait_for(client.read(),3)==b'generated-key#'
        if algorithm=='RSA 3072':assert signatures==[b'rsa-sha2-256']
    finally:await client.close();server.close();await server.wait_closed()
    if os.name!='nt':assert path.stat().st_mode&0o777==0o600


def test_generation_refuses_weak_or_implicit_unencrypted_export_and_existing_files(tmp_path):
    path=tmp_path/'identity'
    for password in ('','short'):
        with pytest.raises(ValueError):generate_identity(path,'Ed25519',password)
    assert not path.exists()
    generate_identity(path,'Ed25519','',unencrypted=True);before=path.read_bytes()
    with pytest.raises(FileExistsError):generate_identity(path,'Ed25519','another-long-passphrase')
    assert path.read_bytes()==before


def test_second_file_race_preserves_foreign_file_and_rolls_back_own_output(tmp_path,monkeypatch):
    import harbor_terminal.key_tools as module
    path=tmp_path/'identity';public=Path(str(path)+'.pub');link=module.os.link
    def race(source,destination):
        if Path(destination)==public:public.write_text('foreign file created concurrently')
        return link(source,destination)
    monkeypatch.setattr(module.os,'link',race)
    with pytest.raises(FileExistsError):generate_identity(path,'Ed25519','',unencrypted=True)
    assert not path.exists() and public.read_text()=='foreign file created concurrently'
    assert not list(tmp_path.glob('.harbor-key-*'))


def test_cancelled_generation_does_not_publish_key_material(tmp_path):
    cancel=threading.Event();cancel.set();path=tmp_path/'identity'
    with pytest.raises(GenerationCancelled):generate_identity(path,'Ed25519','',unencrypted=True,cancel=cancel)
    assert not list(tmp_path.iterdir())


def test_known_host_aliases_markers_hashes_and_stale_revision_are_preserved(tmp_path):
    import base64,hashlib,hmac
    key=asyncssh.generate_private_key('ssh-ed25519');line=host_keys.make_entry('primary.invalid,alias.invalid',key.export_public_key())
    assert host_keys.match(line,'alias.invalid')['trusted']==[key.get_fingerprint('sha256')]
    salt=b'1'*20;hashed='|1|'+base64.b64encode(salt).decode()+'|'+base64.b64encode(hmac.new(salt,b'hidden.invalid',hashlib.sha1).digest()).decode()
    combined=host_keys.append_entries(line,host_keys.make_entry(hashed,key.export_public_key(),'@revoked'))
    assert host_keys.match(combined,'hidden.invalid')['revoked']==[key.get_fingerprint('sha256')]
    path=tmp_path/'known_hosts';store=host_keys.store(path);snapshot=store.save(combined,expected_revision=None)
    other=store.read();store.save(line,expected_revision=snapshot.revision)
    with pytest.raises(StorageConflict):store.save('',expected_revision=other.revision)
    assert path.read_text()==line
    assert host_keys.append_entries(line,line)==line
    assert host_keys.remove_entries('# comment\n'+line,{1})=='# comment\n'


def test_private_key_material_cannot_be_imported_as_host_trust(tmp_path):
    key=asyncssh.generate_private_key('ssh-ed25519')
    with pytest.raises(ValueError):host_keys.entries(key.export_private_key().decode())
    with pytest.raises(ValueError):host_keys.entries('@unknown host '+key.export_public_key().decode())
    assert not list(tmp_path.iterdir())


def test_excessive_openssh_kdf_is_rejected_before_decryption(tmp_path,monkeypatch):
    import base64,struct
    def string(value):return struct.pack('>I',len(value))+value
    options=string(b's'*16)+struct.pack('>I',0xffffffff)
    raw=b'openssh-key-v1\0'+string(b'aes256-ctr')+string(b'bcrypt')+string(options)
    path=tmp_path/'malformed-key';path.write_bytes(b'-----BEGIN OPENSSH PRIVATE KEY-----\n'+base64.b64encode(raw)+b'\n-----END OPENSSH PRIVATE KEY-----\n')
    def forbidden(*args,**kwargs):raise AssertionError('Do not enter the KDF')
    monkeypatch.setattr(asyncssh,'import_private_key',forbidden)
    with pytest.raises(ValueError):public_info(path,'fixture-passphrase-only')
