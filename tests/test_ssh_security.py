import asyncio
from contextlib import asynccontextmanager
import struct
import time
from types import SimpleNamespace

import asyncssh
import pytest

from harbor_terminal.transport import SSHTransport
from harbor_terminal.ssh_policy import SSHPolicy,SecurityPolicyError
from harbor_terminal.authentication import InteractiveClient


@asynccontextmanager
async def peer(tmp_path,*,host_key=None,host_certificate=None,host_ca=None,user_ca=None,**kwargs):
    controls=SimpleNamespace(passwords=0,auth_started=0,connections=set())
    host_key=host_key or asyncssh.generate_private_key('ssh-ed25519')
    class Server(asyncssh.SSHServer):
        def connection_made(self,connection):self.connection=connection;controls.connections.add(connection)
        def connection_lost(self,exc):controls.connections.discard(self.connection)
        def begin_auth(self,username):controls.auth_started+=1;return True
        def password_auth_supported(self):return user_ca is None
        def validate_password(self,username,password):controls.passwords+=1;return username=='tester' and password=='fixture-only'
        def public_key_auth_supported(self):return user_ca is not None
        def validate_ca_key(self,username,key):return username=='tester' and key.public_data==user_ca.public_data
        def validate_public_key(self,username,key):return False
    async def echo(process):
        while True:
            try:data=await process.stdin.read(65536)
            except asyncssh.TerminalSizeChanged:continue
            if not data:break
            process.stdout.write(data)
    keys=[(host_key,host_certificate)] if host_certificate else [host_key]
    server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=keys,
        process_factory=echo,encoding=None,line_editor=False,**kwargs)
    known=tmp_path/'known-hosts'
    known.write_bytes((b'@cert-authority ' if host_ca else b'')+f'[127.0.0.1]:{server.get_port()} '.encode()+(host_ca or host_key).export_public_key())
    options=dict(host='127.0.0.1',port=server.get_port(),username='tester',known_hosts=str(known),password='fixture-only',client_keys=[])
    try:yield SimpleNamespace(server=server,known=known,key=host_key,controls=controls,options=options)
    finally:
        server.close()
        active=list(controls.connections)
        for connection in active:connection.close()
        await asyncio.gather(*(connection.wait_closed() for connection in active),return_exceptions=True)
        await server.wait_closed()


async def roundtrip(client,payload):
    await client.write(payload);received=bytearray()
    async with asyncio.timeout(8):
        while len(received)<len(payload):
            data=await client.read()
            if not data:raise ConnectionError('Fixture closed')
            received.extend(data)
    assert bytes(received)==payload


async def test_selected_order_and_rsa_sha2_are_observed_in_actual_negotiation(tmp_path):
    key=asyncssh.generate_private_key('ssh-rsa',key_size=3072)
    async with peer(tmp_path,host_key=key) as endpoint:
        client=SSHTransport()
        await client.connect(**endpoint.options,security=dict(ssh_kex='curve25519-sha256',
            ssh_ciphers='aes128-ctr,aes256-ctr',ssh_macs='hmac-sha2-256-etm@openssh.com',ssh_hostkey_algs='rsa-sha2-256'))
        try:
            info=client.diagnostics()
            assert info['strict_kex'] is True and info['metadata_adapter'] is True
            assert info['kex']=='curve25519-sha256' and info['send_cipher']=='aes128-ctr'
            assert info['host_public_key_format']=='ssh-rsa' and info['hostkey_signature']=='rsa-sha2-256'
            assert info['host_fingerprint']==key.get_fingerprint('sha256')
            assert 'fixture-only' not in str(info)
            await roundtrip(client,b'policy-verified')
        finally:await client.close()


async def test_strict_requirement_rejects_peer_before_credentials_and_explicit_prefer_can_connect(tmp_path,monkeypatch):
    from asyncssh.connection import SSHServerConnection
    original=SSHServerConnection._get_extra_kex_algs
    monkeypatch.setattr(SSHServerConnection,'_get_extra_kex_algs',lambda self:[v for v in original(self) if not v.startswith(b'kex-strict-')])
    # Emulate a genuinely old peer: it ignores the client's extension too.
    # Removing only the advertisement leaves AsyncSSH's seqnum reset enabled.
    send_keys=SSHServerConnection.send_newkeys
    def old_keys(self,k,h):self._strict_kex=False;return send_keys(self,k,h)
    monkeypatch.setattr(SSHServerConnection,'send_newkeys',old_keys)
    async with peer(tmp_path) as endpoint:
        with pytest.raises(SecurityPolicyError):await SSHTransport().connect(**endpoint.options)
        assert endpoint.controls.passwords==endpoint.controls.auth_started==0
        client=SSHTransport();await client.connect(**endpoint.options,security=dict(ssh_strict_kex='prefer'))
        assert client.diagnostics()['strict_kex'] is False
        assert endpoint.controls.passwords==1
        await client.close()


async def test_strict_kex_rejects_injected_pre_kex_packet_before_auth(tmp_path,monkeypatch):
    from asyncssh.connection import SSHServerConnection
    original=SSHServerConnection._get_extra_kex_algs
    def inject(self):
        if not self._session_id:
            payload=b'\x02'+struct.pack('>I',4)+b'test'
            padding=8-((5+len(payload))%8)
            if padding<4:padding+=8
            self._transport.write(struct.pack('>I',len(payload)+padding+1)+bytes([padding])+payload+b'\0'*padding)
        return original(self)
    monkeypatch.setattr(SSHServerConnection,'_get_extra_kex_algs',inject)
    async with peer(tmp_path) as endpoint:
        with pytest.raises(asyncssh.ProtocolError):await SSHTransport().connect(**endpoint.options)
        assert endpoint.controls.passwords==0


@pytest.mark.parametrize('trigger',['bytes','seconds'])
async def test_rekey_threshold_exchanges_keys_again_without_losing_binary_data(tmp_path,monkeypatch,trigger):
    from asyncssh.connection import SSHConnection
    original=SSHConnection.send_newkeys;keys=[]
    def count(self,k,h):
        if self.is_client():keys.append(True)
        return original(self,k,h)
    monkeypatch.setattr(SSHConnection,'send_newkeys',count)
    async with peer(tmp_path) as endpoint:
        security=dict(ssh_rekey_bytes='4096') if trigger=='bytes' else dict(ssh_rekey_seconds='1')
        client=SSHTransport();await client.connect(**endpoint.options,security=security)
        try:
            if trigger=='seconds':await asyncio.sleep(1.1)
            await roundtrip(client,bytes(range(256))*2048)
            assert len(keys)>=2
        finally:await client.close()


async def test_delayed_compression_is_negotiated_but_not_active_before_auth(tmp_path,monkeypatch):
    before=[];original=InteractiveClient.begin_auth
    def observe(self,username):
        before.append((self.connection._auth_complete,self.connection._compress_after_auth))
        return original(self,username)
    monkeypatch.setattr(InteractiveClient,'begin_auth',observe)
    async with peer(tmp_path,compression_algs=['zlib@openssh.com','none']) as endpoint:
        client=SSHTransport();await client.connect(**endpoint.options,security=dict(ssh_compression='delayed'))
        try:
            assert before==[(False,True)]
            assert client.diagnostics()['send_compression']=='zlib@openssh.com'
            await roundtrip(client,b'compress-after-auth-'*8000)
        finally:await client.close()


@pytest.mark.parametrize('field,value',[('ssh_ciphers','aes128-cbc'),('ssh_kex','diffie-hellman-group14-sha1'),
    ('ssh_signature_algs','ssh-rsa'),('ssh_kex','+curve25519-sha256'),('ssh_macs','hmac-md5'),
    ('ssh_rekey_bytes','0'),('ssh_rekey_seconds','999999'),('ssh_compression','zlib'),('ssh_strict_kex','false')])
def test_unapproved_or_unbounded_policy_rejected(field,value):
    with pytest.raises(ValueError):SSHPolicy.parse({field:value})


def test_legacy_permission_does_not_change_default_proposals_and_runtime_adapter_fails_closed():
    assert SSHPolicy.parse(dict(ssh_allow_legacy='true')).options()==SSHPolicy.parse().options()
    assert SSHPolicy.parse(dict(ssh_allow_legacy='true',ssh_ciphers='aes128-cbc')).options()['encryption_algs']==['aes128-cbc']


async def test_unvalidated_runtime_does_not_claim_verified_strict_kex(tmp_path,monkeypatch):
    monkeypatch.setattr(asyncssh,'__version__','unvalidated-runtime')
    async with peer(tmp_path) as endpoint:
        with pytest.raises(SecurityPolicyError):await SSHTransport().connect(**endpoint.options)
        assert endpoint.controls.passwords==0


@pytest.mark.parametrize('packet',[struct.pack('>I',0xffffffff)+b'\0'*4,struct.pack('>I',1000)+b'\x04\0\0\0'])
async def test_oversized_or_truncated_ssh_packet_fails_without_hanging(tmp_path,packet):
    async def malformed(reader,writer):
        try:
            await reader.readline();writer.write(b'SSH-2.0-local-fault-fixture\r\n'+packet);await writer.drain()
        finally:writer.close();await writer.wait_closed()
    server=await asyncio.start_server(malformed,'127.0.0.1',0)
    known=tmp_path/'known';known.write_text('')
    try:
        async with asyncio.timeout(3):
            client=SSHTransport()
            with pytest.raises((asyncssh.Error,ConnectionResetError)):
                await client.connect('127.0.0.1','tester',port=server.sockets[0].getsockname()[1],
                    known_hosts=known,password='never-send-this-fixture')
            assert client.connection is None and client.process is None
    finally:server.close();await server.wait_closed()


@pytest.mark.parametrize('variant',['valid','wrong-principal','expired','revoked','revoked-host','unknown-ca'])
async def test_host_ca_certificate_principal_validity_and_revocation(tmp_path,variant):
    ca=asyncssh.generate_private_key('ssh-ed25519');host=asyncssh.generate_private_key('ssh-ed25519')
    certificate=ca.generate_host_certificate(host,'host-fixture',principals=['other.invalid'] if variant=='wrong-principal' else ['127.0.0.1'],
        valid_after=0,valid_before=time.time()-1 if variant=='expired' else time.time()+3600)
    async with peer(tmp_path,host_key=host,host_certificate=certificate,host_ca=ca) as endpoint:
        if variant in ('revoked','revoked-host'):
            with endpoint.known.open('ab') as stream:stream.write(f'@revoked [127.0.0.1]:{endpoint.server.get_port()} '.encode()+(ca if variant=='revoked' else host).export_public_key())
        if variant=='unknown-ca':endpoint.known.write_bytes(f'@cert-authority [127.0.0.1]:{endpoint.server.get_port()} '.encode()+asyncssh.generate_private_key('ssh-ed25519').export_public_key())
        client=SSHTransport()
        if variant=='valid':
            await client.connect(**endpoint.options)
            await roundtrip(client,b'ca-verified');await client.close()
        else:
            with pytest.raises(asyncssh.HostKeyNotVerifiable):await client.connect(**endpoint.options)
            assert endpoint.controls.passwords==0


async def test_legacy_server_requires_explicit_named_algorithms_without_automatic_fallback(tmp_path):
    key=asyncssh.generate_private_key('ssh-rsa',key_size=3072)
    async with peer(tmp_path,host_key=key,kex_algs=['diffie-hellman-group14-sha1'],
                    encryption_algs=['aes128-cbc'],mac_algs=['hmac-sha1']) as endpoint:
        with pytest.raises(asyncssh.KeyExchangeFailed):await SSHTransport().connect(**endpoint.options)
        assert endpoint.controls.passwords==0
        client=SSHTransport();await client.connect(**endpoint.options,security=dict(ssh_allow_legacy='true',
            ssh_kex='diffie-hellman-group14-sha1',ssh_ciphers='aes128-cbc',ssh_macs='hmac-sha1',ssh_hostkey_algs='ssh-rsa'))
        try:
            assert client.diagnostics()['hostkey_signature']=='ssh-rsa'
            assert client.diagnostics()['send_cipher']=='aes128-cbc'
            await roundtrip(client,b'explicit-compatibility')
        finally:await client.close()


@pytest.mark.parametrize('variant',['valid','wrong-key','expired','wrong-principal'])
async def test_user_certificate_is_separate_matches_identity_and_is_not_silently_dropped(tmp_path,variant):
    ca=asyncssh.generate_private_key('ssh-ed25519');identity=asyncssh.generate_private_key('ssh-ed25519')
    certificate=ca.generate_user_certificate(identity,'user-fixture',principals=['other'] if variant=='wrong-principal' else ['tester'],
        valid_after=0,valid_before=time.time()-1 if variant=='expired' else time.time()+3600)
    path=tmp_path/'identity';path.write_bytes((asyncssh.generate_private_key('ssh-ed25519') if variant=='wrong-key' else identity).export_private_key())
    cert=tmp_path/'certificate.pub';cert.write_bytes(certificate.export_certificate())
    async with peer(tmp_path,user_ca=ca) as endpoint:
        options=dict(endpoint.options,client_keys=[str(path)],client_certs=[str(cert)],password=None,auth_method='publickey-only')
        client=SSHTransport()
        if variant=='valid':
            await client.connect(**options);await roundtrip(client,b'user-cert');await client.close()
        else:
            with pytest.raises((ValueError,asyncssh.PermissionDenied)):await client.connect(**options)
