"""Exercise the bundled desktop on the OS executing it, then exit."""
from importlib.metadata import version
from pathlib import Path
import platform
import tempfile

from PySide6.QtCore import QTimer, Qt, qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QFontDialog

from .reports import atomic_json


async def protocol_probe(root):
    """Run packaged crypto/SSH/SFTP/MFA/tunnel/batch code on loopback only."""
    import asyncio
    import os
    import asyncssh
    from .transport import SSHTransport
    from .sftp import SFTPService, FileRequest
    from .forwarding import ForwardManager, ForwardSpec
    from .startup import argument_parser
    from .batch import run_batch
    from .key_tools import generate_identity,public_info
    from . import host_keys
    checks={};remote=root/'remote';remote.mkdir()
    private=root/'encrypted-key'
    generated=await asyncio.to_thread(generate_identity,private,'Ed25519','local-fixture-only')
    inspected=await asyncio.to_thread(public_info,private,'local-fixture-only')
    checks['identity_tool_encrypted_roundtrip']=generated['fingerprint']==inspected['fingerprint']
    key=asyncssh.read_private_key(private,passphrase='local-fixture-only');host_key=asyncssh.generate_private_key('ssh-ed25519')
    ca=asyncssh.generate_private_key('ssh-ed25519')
    plain=root/'batch-key';plain.write_bytes(key.export_private_key());plain.chmod(0o600)
    async def tcp_echo(reader,writer):
        try:
            while data:=await reader.read(65536):writer.write(data);await writer.drain()
        finally:writer.close();await writer.wait_closed()
    tcp=await asyncio.start_server(tcp_echo,'127.0.0.1',0);tcp_port=tcp.sockets[0].getsockname()[1]
    class Server(asyncssh.SSHServer):
        def begin_auth(self,username):return True
        def public_key_auth_supported(self):return True
        def validate_public_key(self,username,pub):return username=='smoke' and pub.get_fingerprint()==key.get_fingerprint()
        def validate_ca_key(self,username,pub):return username=='smoke' and pub.public_data==ca.public_data
        def kbdint_auth_supported(self):return True
        def get_kbdint_challenge(self,username,lang,methods):
            return ('Local test','Line one\nLine two','',[('OTP:',False)]) if username=='smoke-mfa' else False
        def validate_kbdint_response(self,username,answers):return username=='smoke-mfa' and answers==['fixture-code']
        def connection_requested(self,host,port,*_):return host=='127.0.0.1' and port==tcp_port
    async def shell(process):
        while True:
            try:data=await process.stdin.read(4096)
            except asyncssh.TerminalSizeChanged:continue
            if not data:break
            process.stdout.write(data)
    host_certificate=ca.generate_host_certificate(host_key,'packaged-host',principals=['127.0.0.1'])
    server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[(host_key,host_certificate)],process_factory=shell,
        encoding=None,line_editor=False,sftp_factory=lambda channel:asyncssh.SFTPServer(channel,chroot=os.fsencode(remote)))
    known=root/'known_hosts';trust=host_keys.make_entry(f'[127.0.0.1]:{server.get_port()}',ca.export_public_key(),'@cert-authority')
    store=host_keys.store(known);store.save(trust,expected_revision=None)
    checks['host_ca_local_matching']=host_keys.match(trust,'127.0.0.1',server.get_port())['certificate_authorities']==[ca.get_fingerprint('sha256')]
    options=dict(host='127.0.0.1',username='smoke',port=server.get_port(),known_hosts=str(known),
                 client_keys=[str(private)],passphrase='local-fixture-only',auth_method='publickey-only',
                 security=dict(ssh_kex='curve25519-sha256',ssh_ciphers='aes128-ctr',
                               ssh_macs='hmac-sha2-256-etm@openssh.com',ssh_compression='delayed'))
    client=SSHTransport();manager=None
    try:
        await client.connect(**options);await client.write(b'packaged-ssh#')
        received=bytearray()
        async with asyncio.timeout(5):
            while len(received)<13:received.extend(await client.read())
        checks['encrypted_key_and_ssh']=bytes(received)==b'packaged-ssh#'
        metadata=client.diagnostics()
        atomic_json(root/'negotiated.json',metadata)
        checks['strict_kex_and_algorithm_policy']=(metadata['strict_kex'] is True and metadata['metadata_adapter'] is True
            and metadata['kex']=='curve25519-sha256' and metadata['send_cipher']=='aes128-ctr'
            and metadata['send_mac']=='hmac-sha2-256-etm@openssh.com')
        checks['authenticated_compression']=metadata['send_compression']=='zlib@openssh.com'
        cert=root/'user-cert.pub';cert.write_bytes(ca.generate_user_certificate(key,'packaged-user',principals=['smoke']).export_certificate())
        certified=SSHTransport()
        try:
            await certified.connect(**dict(options,client_certs=[str(cert)]))
            checks['separate_user_certificate_and_host_ca']=not certified.connection.is_closed()
        finally:await certified.close()
        source=root/'payload.bin';source.write_bytes(bytes(range(256))*4)
        service=SFTPService(client.connection)
        await service.execute(FileRequest('upload','/payload.bin',str(source)))
        target=root/'download.bin';await service.execute(FileRequest('download','/payload.bin',str(target)))
        checks['sftp_binary_roundtrip']=target.read_bytes()==source.read_bytes()
        manager=ForwardManager(client.connection)
        entry=await manager.start(ForwardSpec('local',0,'127.0.0.1',tcp_port))
        reader,writer=await asyncio.open_connection('127.0.0.1',entry['listen_port'])
        writer.write(b'\0\xffbundle');await writer.drain()
        checks['tcp_forward']=await asyncio.wait_for(reader.readexactly(8),5)==b'\0\xffbundle'
        writer.close();await writer.wait_closed();await manager.stop(entry['id'])
        unknown=root/'unknown';unknown.write_text('')
        rejected=SSHTransport()
        try:await rejected.connect(**dict(options,known_hosts=str(unknown)))
        except asyncssh.HostKeyNotVerifiable:checks['untrusted_host_rejected']=True
        else:checks['untrusted_host_rejected']=False
        finally:await rejected.close()
        mfa=SSHTransport();seen=[]
        async def response(event):seen.append(event['prompts']);return ['fixture-code']
        await mfa.connect('127.0.0.1','smoke-mfa',port=server.get_port(),known_hosts=str(known),
                          client_keys=[],auth_method='interactive-only',auth_prompt=response)
        await mfa.close();checks['keyboard_interactive']=seen==[[('OTP:',False)]]
        flow=root/'flow.json';batch_result=root/'batch.json'
        import json
        flow.write_text(json.dumps(dict(version=1,steps=[dict(action='send',text='bundle-batch#'),
                                                       dict(action='wait',patterns=['#'])])))
        args=argument_parser().parse_args([f'smoke@127.0.0.1:{server.get_port()}',
            '--identity-file',str(plain),'--known-hosts',str(known),'--run-flow',str(flow),'--output',str(batch_result)])
        checks['batch_flow']=await run_batch(args)==0
    finally:
        if manager:await manager.close_all()
        await client.close();server.close();await server.wait_closed();tcp.close();await tcp.wait_closed()
    return checks


def desktop_smoke(app, report_path):
    from .app import Window, ConnectionOptions
    from .appearance import terminal_font
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    report_path = Path(report_path).resolve()
    if report_path.exists(): raise FileExistsError('Choose a new report path')
    result = dict(status='running', version=version('harbor-terminal'), platform=platform.platform(),
                  python=platform.python_version(), qt=qVersion(), checks={})
    atomic_json(report_path, result)
    with tempfile.TemporaryDirectory(prefix='harbor-smoke-') as temporary:
        window = Window(profile_path=Path(temporary)/'sessions.json')
        try:
            window.show(); app.processEvents()
            result['ui_font'] = QFontInfo(window.font()).family()
            result['terminal_font'] = QFontInfo(terminal_font()).family()
            screen = window.screen()
            result['display'] = dict(dpr=window.devicePixelRatioF(), dpi=screen.logicalDotsPerInch(),
                                      width=window.width(), height=window.height())
            result['checks']['mainwindow'] = window.isVisible() and bool(window.menuBar().actions())
            import asyncio
            result['checks'].update(asyncio.run(protocol_probe(Path(temporary))))
            from .key_dialogs import HostKeysDialog,TrustReview,KeyToolsDialog
            from .ssh_dialogs import DiagnosticsDialog
            from .session import Worker
            import json
            diagnostic_worker=Worker('SSH',{})
            diagnostic_worker._ssh_diagnostics=json.loads((Path(temporary)/'negotiated.json').read_text())
            diagnostic=DiagnosticsDialog(diagnostic_worker,'local packaged fixture',window);diagnostic.show();app.processEvents()
            result['checks']['ssh_diagnostics_dialog']=diagnostic.tree.topLevelItemCount()>=12
            diagnostic.close();diagnostic.deleteLater()
            window.known.setText(str(Path(temporary)/'known_hosts'))
            hosts=HostKeysDialog(window);hosts.show();app.processEvents()
            result['checks']['host_key_manager']=hosts.tree.topLevelItemCount()==1
            review=TrustReview(hosts.snapshot.value,hosts);review.show();app.processEvents();review.accept()
            result['checks']['trust_requires_acknowledgement']=review.isVisible() and not review.ok.isEnabled()
            review.reject();review.deleteLater();hosts.close();hosts.deleteLater()
            key_tools=KeyToolsDialog(window);window.key_dialog=key_tools;key_tools.show()
            key_tools.path.setText(str(Path(temporary)/'encrypted-key'));key_tools.password.setText('local-fixture-only');key_tools.start(True)
            import time
            deadline=time.monotonic()+30
            while key_tools.job.isRunning() and time.monotonic()<deadline:
                app.processEvents();key_tools.job.wait(10)
            if key_tools.job.isRunning():raise TimeoutError('Identity inspection did not finish')
            app.processEvents()
            result['checks']['background_identity_inspection']=bool(key_tools.last_result) and not key_tools.password.text() and 'PRIVATE KEY' not in key_tools.output.toPlainText()
            key_tools.close()
            from .session_manager import SessionManager,ImportDialog,TemplateDialog
            from .profile_operations import plan_import,export_sessions,parse_import
            from .storage import StorageConflict
            from . import profiles
            imported=ImportDialog(b'Name,Host,Port,Password\nfixture,fixture.invalid,2222,fixture-only\n','csv',window)
            imported.read_rows()
            result['checks']['import_secret_columns_ignored']=bool(imported.incoming) and 'fixture-only' not in profiles.encode(imported.incoming).decode()
            manager=SessionManager(window);manager.show();app.processEvents()
            stale=window.profile_store.read()
            QTimer.singleShot(50,lambda:app.activeModalWidget().accept())
            result['checks']['session_import_preview_commit']=manager.commit(plan_import(window.profiles,imported.incoming,'add-only'))
            try:window.profile_store.save({},expected_revision=stale.revision)
            except StorageConflict:result['checks']['stale_configuration_rejected']=True
            else:result['checks']['stale_configuration_rejected']=False
            result['checks']['native_xml_roundtrip']=parse_import(export_sessions(window.profiles,'xml').decode(),'xml').sessions==window.profiles
            template=TemplateDialog(window);template.show();app.processEvents()
            template.editors['Serial'].inputs['port'].setText('57600');template.accept()
            result['checks']['protocol_template_dialog']=window.templates['Serial'].get('port')=='57600'
            for dialog in (template,imported,manager):dialog.close();dialog.deleteLater()
            app.processEvents()
            window.quick_action.trigger(); app.processEvents()
            result['checks']['quick_connect'] = window.quick_dialog.isVisible()
            def dismiss_options():
                modal = app.activeModalWidget()
                result['checks']['nested_options'] = isinstance(modal, ConnectionOptions) and modal.parentWidget() is window.quick_dialog
                result['checks']['ssh_policy_options'] = isinstance(modal, ConnectionOptions) and modal.policy.values()['ssh_strict_kex']=='require'
                if modal: modal.reject()
            QTimer.singleShot(50, dismiss_options); window.edit_options()
            window.quick_dialog.reject(); app.processEvents()
            def dismiss_font():
                modal = app.activeModalWidget()
                result['checks']['font_dialog'] = isinstance(modal, QFontDialog)
                if modal: modal.reject()
            QTimer.singleShot(50, dismiss_font); window.choose_terminal_font()
            result['checks']['no_connection_side_effect'] = not window.workers
            result['checks']['screenshot'] = window.grab().save(str(report_path.with_suffix('.png')))
            result['status'] = 'passed' if all(result['checks'].values()) else 'failed'
        except Exception as exc:
            result['status'] = 'failed'; result['error_type'] = type(exc).__name__
        finally:
            window.close(); app.processEvents()
    atomic_json(report_path, result)
    return 0 if result['status'] == 'passed' else 1
