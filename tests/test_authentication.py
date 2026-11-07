import asyncio
from types import SimpleNamespace

import asyncssh
import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit

from harbor_terminal.authentication import (AuthenticationBroker, AuthenticationCancelled,
    AuthenticationTimeout, AuthenticationLimit)
from harbor_terminal.transport import SSHTransport
from harbor_terminal.app import Window


@pytest.fixture
async def mfa_endpoint(tmp_path):
    controls=SimpleNamespace(responses=[],passwords=0,challenge_count=0,too_many=False,
        loop=False,allow_password=False,allowed_destinations=set())
    class Server(asyncssh.SSHServer):
        def begin_auth(self,username):return True
        def kbdint_auth_supported(self):return True
        def password_auth_supported(self):return True
        def validate_password(self,username,password):
            controls.passwords+=1
            return controls.allow_password and password=='fallback-test-only'
        def get_kbdint_challenge(self,username,lang,submethods):
            controls.challenge_count+=1
            self.round=0
            prompts=[('Visible name\nSecond line:',True),('Password:',False)]
            if controls.too_many:prompts=[('prompt',False)]*17
            return '<b>Authentication</b>','First line\nSecond line','',prompts
        def validate_kbdint_response(self,username,responses):
            controls.responses.append(list(responses));self.round+=1
            if controls.loop:return 'Next','More','',[('Again:',False)]
            if self.round==1 and responses==['visible-test','password-test-only']:
                return 'OTP','Enter code\nDo not reuse','',[('One-time code:',False)]
            return self.round==2 and responses==['987654']
        def connection_requested(self,host,port,*_):return (host,port) in controls.allowed_destinations
    async def shell(process):
        while True:
            try:data=await process.stdin.read(4096)
            except asyncssh.TerminalSizeChanged:continue
            if not data:break
            process.stdout.write(data)
    key=asyncssh.generate_private_key('ssh-ed25519')
    server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],
        process_factory=shell,encoding=None,line_editor=False)
    known=tmp_path/'mfa_known_hosts'
    known.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode()+key.export_public_key())
    yield SimpleNamespace(server=server,controls=controls,port=server.get_port(),known=known,
        options=dict(host='127.0.0.1',port=server.get_port(),username='mfa',known_hosts=str(known),
                     client_keys=[],auth_method='interactive-only'))
    server.close();await server.wait_closed()


async def answer(event):
    return ['visible-test','password-test-only'] if len(event['prompts'])==2 else ['987654']


async def test_multiround_echo_flags_and_newlines_exceed_handshake_budget_safely(mfa_endpoint):
    observed=[]
    async def delayed(event):
        observed.append(event);await asyncio.sleep(.08);return await answer(event)
    client=SSHTransport()
    await client.connect(**mfa_endpoint.options,auth_prompt=delayed,timeout=.07,auth_timeout=2)
    try:
        assert len(observed)==2
        assert observed[0]['prompts'][0]==('Visible name\nSecond line:',True)
        assert observed[0]['prompts'][1][1] is False
        assert observed[0]['instructions']=='First line\nSecond line'
        assert all(event['stage']=='target' and event['port']==mfa_endpoint.port for event in observed)
        await client.write(b'after-mfa\n')
        assert await asyncio.wait_for(client.read(),2)==b'after-mfa\n'
    finally:await client.close()


async def test_cancel_does_not_fall_back_to_a_valid_password(mfa_endpoint):
    mfa_endpoint.controls.allow_password=True
    options=dict(mfa_endpoint.options,auth_method='interactive-first',password='fallback-test-only')
    async def cancel(event):raise AuthenticationCancelled()
    with pytest.raises(AuthenticationCancelled):await SSHTransport().connect(**options,auth_prompt=cancel)
    assert mfa_endpoint.controls.passwords==0 and not mfa_endpoint.controls.responses


async def test_untrusted_host_never_receives_or_displays_authentication(mfa_endpoint,tmp_path):
    unknown=tmp_path/'unknown';unknown.write_text('')
    options=dict(mfa_endpoint.options,known_hosts=str(unknown));observed=[]
    async def should_not_run(event):observed.append(event);return await answer(event)
    with pytest.raises(asyncssh.HostKeyNotVerifiable):await SSHTransport().connect(**options,auth_prompt=should_not_run)
    assert not observed and mfa_endpoint.controls.challenge_count==0


@pytest.mark.parametrize('mode',['prompts','rounds'])
async def test_challenge_resource_limits_close_connection(mfa_endpoint,mode):
    mfa_endpoint.controls.too_many=mode=='prompts';mfa_endpoint.controls.loop=mode=='rounds'
    seen=[]
    async def respond(event):seen.append(event);return ['x']*len(event['prompts'])
    with pytest.raises(AuthenticationLimit):await SSHTransport().connect(**mfa_endpoint.options,auth_prompt=respond)
    assert len(seen)==(0 if mode=='prompts' else 8)


async def test_password_first_mode_skips_unneeded_challenges(mfa_endpoint):
    mfa_endpoint.controls.allow_password=True
    options=dict(mfa_endpoint.options,auth_method='password-first',password='fallback-test-only')
    client=SSHTransport();await client.connect(**options,auth_prompt=answer)
    await client.close()
    assert mfa_endpoint.controls.passwords==1 and mfa_endpoint.controls.challenge_count==0


async def test_mfa_jump_identity_is_separate_from_target(sftp_endpoint,mfa_endpoint):
    mfa_endpoint.controls.allowed_destinations.add(('127.0.0.1',sftp_endpoint.port));seen=[]
    async def respond(event):seen.append(event);return await answer(event)
    client=SSHTransport()
    await client.connect(**sftp_endpoint.options,jump=mfa_endpoint.options,auth_prompt=respond)
    try:
        assert len(seen)==2 and all(event['stage']=='jump' and event['username']=='mfa' for event in seen)
        await client.write(b'target-after-jump-mfa\n')
        assert await asyncio.wait_for(client.read(),2)==b'target-after-jump-mfa\n'
        assert mfa_endpoint.controls.passwords==0 and sftp_endpoint.controls.authentications==1
    finally:await client.close()


async def test_broker_rejects_stale_duplicate_and_malformed_replies():
    events=[];broker=AuthenticationBroker(events.append,timeout=1)
    task=asyncio.create_task(broker.ask(dict(name='n',instructions='i',prompts=[('OTP',False)])))
    await asyncio.sleep(0)
    identifier=events[0]['id']
    assert not broker.reply('old', ['wrong']) and not broker.reply(identifier, [])
    assert broker.reply(identifier, ['test-only'])
    assert not broker.reply(identifier, ['duplicate'])
    assert await task==['test-only'] and broker.pending is None
    assert not broker.reply(identifier, ['late'])


async def test_broker_timeout_and_cancellation_release_pending_request():
    broker=AuthenticationBroker(lambda event:None,timeout=.01)
    with pytest.raises(AuthenticationTimeout):await broker.ask(dict(name='',instructions='',prompts=[('OTP',False)]))
    assert broker.pending is None
    broker.timeout=1
    task=asyncio.create_task(broker.ask(dict(name='',instructions='',prompts=[('OTP',False)])))
    await asyncio.sleep(0);task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert broker.pending is None


async def qt_until(app,predicate):
    async with asyncio.timeout(5):
        while not predicate():app.processEvents();await asyncio.sleep(.01)


async def test_actual_qt_mfa_dialog_masks_secrets_and_keeps_responses_out_of_logs(mfa_endpoint,tmp_path):
    app=QApplication.instance() or QApplication([])
    window=Window(profile_path=tmp_path/'sessions.json');window.show()
    window.host.setText('127.0.0.1');window.port.setText(str(mfa_endpoint.port));window.user.setText('mfa')
    window.known.setText(str(mfa_endpoint.known));window.options['auth_method']='interactive-only'
    window.connect_session();terminal=window.tabs.currentWidget();worker=terminal.worker
    worker.trace.configure(True,True)
    try:
        await qt_until(app,lambda:worker in window.auth_dialogs)
        first=window.auth_dialogs[worker]
        assert first.fields[0].echoMode()==QLineEdit.EchoMode.Normal
        assert first.fields[1].echoMode()==QLineEdit.EchoMode.Password
        assert '<b>Authentication</b>' in first.findChild(QPlainTextEdit).toPlainText()
        assert not worker.start_log(tmp_path/'not-allowed.jsonl')
        first.fields[0].setText('visible-test');first.fields[1].setText('password-test-only');first.submit()
        await qt_until(app,lambda:worker in window.auth_dialogs and window.auth_dialogs[worker] is not first)
        second=window.auth_dialogs[worker];second.fields[0].setText('987654');second.submit()
        await qt_until(app,lambda:worker.status=='Connected')
        assert not window.auth_dialogs and not worker.trace.snapshot()['records']
        assert 'password' not in worker.options
        assert not window.profile_path.exists()
        assert worker.send(b'shell-works\n')
        await qt_until(app,lambda:'shell-works' in terminal.toPlainText())
    finally:
        worker.stop_event.set();await qt_until(app,lambda:not worker.isRunning())
        window.close();app.processEvents()


@pytest.mark.parametrize('reason',['cancel','timeout'])
async def test_qt_prompt_cancel_or_deadline_stops_worker_without_password_fallback(mfa_endpoint,tmp_path,reason):
    app=QApplication.instance() or QApplication([])
    window=Window(profile_path=tmp_path/'sessions.json');window.show()
    window.host.setText('127.0.0.1');window.port.setText(str(mfa_endpoint.port));window.user.setText('mfa')
    window.known.setText(str(mfa_endpoint.known));window.connect_session()
    worker=window.tabs.currentWidget().worker
    if reason=='timeout':worker.authentication.timeout=.15
    try:
        await qt_until(app,lambda:worker in window.auth_dialogs)
        if reason=='cancel':window.auth_dialogs[worker].reject()
        await qt_until(app,lambda:not worker.isRunning())
        app.processEvents()
        assert worker.status=='Disconnected' and worker.authentication.pending is None
        assert not window.auth_dialogs and mfa_endpoint.controls.passwords==0
    finally:
        worker.stop_event.set();await qt_until(app,lambda:not worker.isRunning())
        window.close();app.processEvents()
