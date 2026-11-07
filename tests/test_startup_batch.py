import asyncio
import json
import os
from types import SimpleNamespace

import asyncssh
import pytest

from harbor_terminal.endpoint import parse_destination
from harbor_terminal.startup import argument_parser
from harbor_terminal.batch import run_batch
from harbor_terminal.transport import SSHTransport
from harbor_terminal.sftp import SFTPService, FileRequest


@pytest.mark.parametrize('text,expected',[
    ('admin@example.invalid:2200',('example.invalid','admin',2200)),
    ('[2001:db8::1]:2222',('2001:db8::1','',2222)),
    ('ssh://user@host.invalid:2022',('host.invalid','user',2022)),
    ('用户@例子.测试',('xn--fsqu00a.xn--0zwm56d','用户',22)),
    ('2001:db8::1',('2001:db8::1','',22)),
    ('name@realm@host.invalid',('host.invalid','name@realm',22))])
def test_destination_parser_addresses_users_and_idna(text,expected):
    endpoint=parse_destination(text)
    assert (endpoint.host,endpoint.username,endpoint.port)==expected


@pytest.mark.parametrize('text',['ssh://user:secret@host','user:secret@host','https://host',
    'host:0','host:65536','host:abc','bad host','host\nother','[::1]:','host/path','ssh://host?command=bad',
    '@host','ssh://@host'])
def test_destination_rejects_secrets_invalid_ports_and_extra_semantics(text):
    with pytest.raises(ValueError):parse_destination(text)


def test_rejected_cli_secret_is_never_echoed_to_stderr(capsys):
    with pytest.raises(SystemExit):argument_parser().parse_args(['--password','test-only-sensitive'])
    assert 'test-only-sensitive' not in capsys.readouterr().err


@pytest.fixture
async def key_server(tmp_path):
    client_key=asyncssh.generate_private_key('ssh-ed25519')
    key_path=tmp_path/'client_key';key_path.write_bytes(client_key.export_private_key());key_path.chmod(0o600)
    controls=SimpleNamespace(authentications=0)
    class Server(asyncssh.SSHServer):
        def begin_auth(self,username):return True
        def public_key_auth_supported(self):return True
        def validate_public_key(self,username,key):
            controls.authentications+=1
            return username=='runner' and key.get_fingerprint()==client_key.get_fingerprint()
    async def shell(process):
        process.stdout.write(b'ready#')
        while True:
            try:data=await process.stdin.read(4096)
            except asyncssh.TerminalSizeChanged:continue
            if not data:break
            process.stdout.write(b'output:'+data+b'ready#')
    host_key=asyncssh.generate_private_key('ssh-ed25519')
    server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[host_key],
        process_factory=shell,encoding=None,line_editor=False)
    known=tmp_path/'known_hosts'
    known.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode()+host_key.export_public_key())
    yield SimpleNamespace(server=server,key=key_path,known=known,controls=controls)
    server.close();await server.wait_closed()


async def test_headless_flow_authenticates_with_key_and_captures_real_ssh_output(key_server,tmp_path):
    flow=tmp_path/'flow.json';report=tmp_path/'report.json'
    flow.write_text(json.dumps(dict(version=1,steps=[dict(action='wait',patterns=['ready#']),
        dict(action='send',text='probe'),dict(action='wait',patterns=['ready#'])])))
    args=argument_parser().parse_args([f'runner@127.0.0.1:{key_server.server.get_port()}',
        '--identity-file',str(key_server.key),'--known-hosts',str(key_server.known),
        '--run-flow',str(flow),'--output',str(report)])
    assert await run_batch(args)==0
    data=json.loads(report.read_text(encoding='utf-8'))
    assert data['status']=='success' and data['result']['sends_queued']==1
    assert 'output:probe' in data['result']['captures'][1]['text']
    assert key_server.controls.authentications>=1


async def test_headless_flow_rejects_unknown_identity_before_any_commands(key_server,tmp_path):
    flow=tmp_path/'flow.json';report=tmp_path/'report.json';unknown=tmp_path/'unknown';unknown.write_text('')
    flow.write_text(json.dumps(dict(version=1,steps=[dict(action='send',text='must-not-send')])))
    args=argument_parser().parse_args([f'runner@127.0.0.1:{key_server.server.get_port()}',
        '--identity-file',str(key_server.key),'--known-hosts',str(unknown),
        '--run-flow',str(flow),'--output',str(report)])
    assert await run_batch(args)==1
    data=json.loads(report.read_text())
    assert data['error_type']=='HostKeyNotVerifiable' and not data['result']
    assert key_server.controls.authentications==0


async def test_shellless_ssh_retains_sftp_and_never_opens_a_process(sftp_endpoint):
    client=SSHTransport();await client.connect(**sftp_endpoint.options,shell=False)
    try:
        assert client.process is None and sftp_endpoint.controls.processes==0
        result=await SFTPService(client.connection).execute(FileRequest('list','/'))
        assert result['path']=='/'
        with pytest.raises(RuntimeError):await client.write(b'not-a-shell')
        assert not client.connection.is_closed()
    finally:await client.close()


async def test_no_explicit_key_selection_does_not_disable_default_public_keys(key_server,monkeypatch):
    loaded=[]
    def defaults(*args,**kwargs):
        loaded.append(True);return asyncssh.load_keypairs([str(key_server.key)])
    monkeypatch.setattr('asyncssh.connection.load_default_keypairs',defaults)
    client=SSHTransport()
    await client.connect('127.0.0.1','runner',port=key_server.server.get_port(),
        known_hosts=str(key_server.known),auth_method='publickey-only')
    await client.close();assert loaded and key_server.controls.authentications>=1


@pytest.mark.skipif(os.name=='nt',reason='Unix PTY; real Windows COM is user-run')
async def test_headless_serial_flow_uses_explicit_device_and_byte_stream(tmp_path):
    import pty,select,threading
    master,slave=pty.openpty();stop=threading.Event()
    def echo():
        while not stop.is_set():
            if select.select([master],[],[],.05)[0]:
                data=os.read(master,4096)
                if data:os.write(master,data)
    thread=threading.Thread(target=echo);thread.start()
    flow=tmp_path/'serial-flow.json';report=tmp_path/'serial-result.json'
    flow.write_text(json.dumps(dict(version=1,steps=[dict(action='send',text='serial-probe#'),
        dict(action='wait',patterns=['#'])])))
    args=argument_parser().parse_args(['--serial-port',os.ttyname(slave),'--run-flow',str(flow),'--output',str(report)])
    try:
        assert await run_batch(args)==0
        data=json.loads(report.read_text())
        assert data['target']['protocol']=='Serial' and data['result']['captures'][0]['text']=='serial-probe'
    finally:
        stop.set();thread.join(2);os.close(master);os.close(slave)
        assert not thread.is_alive()


def test_v3_session_remains_readable_and_v4_authentication_options_roundtrip(tmp_path):
    from harbor_terminal.profiles import load,save
    path=tmp_path/'sessions.json';sessions={'target':dict(mode='SSH',host='example.invalid',port='22',jump_profile='')}
    path.write_text(json.dumps(dict(version=3,sessions=sessions)))
    assert load(path)==sessions
    sessions['target'].update(auth_method='interactive-first',ssh_mode='channels')
    save(path,sessions)
    assert load(path)==sessions and json.loads(path.read_text())['version']==5


@pytest.mark.parametrize('jump_compatibility',[False,True])
async def test_batch_compatibility_requires_explicit_consent_for_target_or_jump(key_server,tmp_path,jump_compatibility):
    from harbor_terminal.profiles import save
    endpoint=dict(mode='SSH',host='127.0.0.1',port=str(key_server.server.get_port()),username='runner',
                  private_key=str(key_server.key),known_hosts=str(key_server.known))
    sessions={'target':dict(endpoint)}
    if jump_compatibility:
        sessions['target']['jump_profile']='jump'
        sessions['jump']=dict(endpoint,ssh_strict_kex='prefer')
    else:sessions['target']['ssh_strict_kex']='prefer'
    path=tmp_path/'sessions.json';save(path,sessions)
    flow=tmp_path/'flow.json';flow.write_text(json.dumps(dict(version=1,steps=[dict(action='send',text='probe')])))
    report=tmp_path/'result.json'
    args=argument_parser().parse_args(['--sessions',str(path),'--profile','target','--run-flow',str(flow),'--output',str(report)])
    with pytest.raises(ValueError,match='--allow-legacy-ssh'):await run_batch(args)
    assert key_server.controls.authentications==0 and not report.exists()
    if not jump_compatibility:
        args.allow_legacy_ssh=True
        assert await run_batch(args)==0 and key_server.controls.authentications>0


async def test_serial_flow_rejects_ssh_certificate_before_opening_any_device(tmp_path):
    flow=tmp_path/'flow.json';flow.write_text(json.dumps(dict(version=1,steps=[dict(action='send',text='probe')])))
    report=tmp_path/'result.json'
    args=argument_parser().parse_args(['--serial-port','COM-DO-NOT-OPEN','--certificate-file','cert.pub',
                                     '--run-flow',str(flow),'--output',str(report)])
    with pytest.raises(ValueError,match='SSH authentication'):await run_batch(args)
    assert not report.exists()
