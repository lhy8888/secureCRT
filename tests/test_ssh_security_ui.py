import asyncio
import json

import asyncssh
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QDialog

from harbor_terminal.app import Window
from harbor_terminal.desktop import ConnectionOptions
from harbor_terminal.key_dialogs import HostKeysDialog,TrustReview,AddHostKey,KeyToolsDialog
from harbor_terminal.ssh_dialogs import DiagnosticsDialog
from harbor_terminal.ssh_dialogs import confirm_compatibility
from harbor_terminal.session import Worker
from harbor_terminal import host_keys
from test_ssh_security import peer
from harbor_terminal.transport import SSHTransport


async def until(app,predicate):
    async with asyncio.timeout(10):
        while not predicate():app.processEvents();await asyncio.sleep(.01)


@pytest.fixture
async def desktop(tmp_path):
    app=QApplication.instance() or QApplication([]);window=Window(profile_path=tmp_path/'sessions.json')
    window.known.setText(str(tmp_path/'known_hosts'));window.show();app.processEvents()
    yield app,window
    window.close()
    await until(app,lambda:not window.key_job_running() and not window.isVisible())
    window.deleteLater();app.processEvents()


async def test_host_trust_requires_actual_fingerprint_acknowledgement_and_stale_write_is_rejected(desktop):
    app,window=desktop;dialog=HostKeysDialog(window)
    key=asyncssh.generate_private_key('ssh-ed25519');line=host_keys.make_entry('fixture.invalid',key.export_public_key())
    observed=[]
    def approve():
        modal=app.activeModalWidget();observed.append(isinstance(modal,TrustReview) and not modal.ok.isEnabled())
        modal.accept();observed.append(modal.isVisible());modal.verified.setChecked(True);modal.accept()
    QTimer.singleShot(20,approve)
    assert dialog.commit(line,line)
    assert observed==[True,True] and dialog.store.path.read_text()==line
    before=dialog.store.path.read_bytes();QTimer.singleShot(20,lambda:app.activeModalWidget().reject())
    assert not dialog.commit('',line,deleting=True) and dialog.store.path.read_bytes()==before
    other=host_keys.make_entry('second.invalid',key.export_public_key())
    def concurrent():
        dialog.store.save(other,expected_revision=dialog.snapshot.revision)
        modal=app.activeModalWidget();modal.verified.setChecked(True);modal.accept()
    QTimer.singleShot(20,concurrent)
    assert not dialog.commit('',line,deleting=True) and dialog.store.path.read_text()==other
    assert '其他窗口' in dialog.status.text();dialog.close()


async def test_add_host_key_rejects_private_material_and_does_not_connect(desktop):
    app,window=desktop;dialog=AddHostKey(window,'fixture.invalid');key=asyncssh.generate_private_key('ssh-ed25519')
    dialog.public.setPlainText(key.export_private_key().decode());dialog.accept()
    assert dialog.result_text is None and dialog.result()!=QDialog.DialogCode.Accepted
    dialog.public.setPlainText(key.export_public_key().decode());dialog.marker.setCurrentIndex(1);dialog.accept()
    assert host_keys.entries(dialog.result_text)[0].marker=='@cert-authority'
    assert not window.workers;dialog.close()


async def test_jump_compatibility_is_shown_in_plain_text_and_defaults_to_cancel(desktop):
    from PySide6.QtWidgets import QLabel,QDialogButtonBox
    from PySide6.QtCore import Qt
    app,window=desktop;seen=[]
    def cancel():
        modal=app.activeModalWidget();labels=modal.findChildren(QLabel)
        seen.append(any('<b>jump.invalid</b>' in label.text() and label.textFormat()==Qt.TextFormat.PlainText for label in labels))
        seen.append(modal.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).isDefault())
        modal.reject()
    QTimer.singleShot(20,cancel)
    assert not confirm_compatibility(dict(host='target.invalid',security={},
        jump=dict(host='<b>jump.invalid</b>',security=dict(ssh_strict_kex='prefer'))),window)
    assert seen==[True,True] and not window.workers


async def test_policy_dialog_rejects_implicit_legacy_and_saves_explicit_order(desktop):
    app,window=desktop;dialog=ConnectionOptions(window.options,window)
    dialog.policy.fields['ssh_ciphers'].setText('aes128-cbc');dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted
    dialog.policy.legacy.setChecked(True);dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted
    values=dialog.values();assert values['ssh_ciphers']=='aes128-cbc' and values['ssh_allow_legacy']=='true'
    assert not window.workers;dialog.close()


async def test_background_key_generation_clears_entry_and_never_displays_private_material(desktop,tmp_path):
    app,window=desktop;dialog=KeyToolsDialog(window);window.key_dialog=dialog;dialog.show()
    dialog.path.setText(str(tmp_path/'identity'));dialog.password.setText('fixture-passphrase-only');dialog.start(False)
    assert not dialog.password.text() and not dialog.generate.isEnabled()
    await until(app,lambda:dialog.last_result is not None and not dialog.job.isRunning())
    assert (tmp_path/'identity.pub').exists() and 'SHA256:' in dialog.output.toPlainText()
    assert 'PRIVATE KEY' not in dialog.output.toPlainText() and not dialog.job.arguments
    dialog.close()


async def test_window_waits_for_key_job_before_destroying_threads(desktop,tmp_path):
    app,window=desktop;window.open_key_tools();dialog=window.key_dialog
    dialog.path.setText(str(tmp_path/'identity'));dialog.password.setText('fixture-passphrase-only');dialog.start(False)
    window.close();await until(app,lambda:not window.key_job_running() and not window.isVisible())
    assert not dialog.job.isRunning()
    if (tmp_path/'identity').exists():assert (tmp_path/'identity.pub').exists()


async def test_diagnostic_view_and_export_show_actual_metadata_without_secrets(desktop,tmp_path,monkeypatch):
    app,window=desktop
    async with peer(tmp_path) as endpoint:
        transport=SSHTransport();await transport.connect(**endpoint.options)
        try:
            worker=Worker('SSH',{});worker._set_state('Connected');worker._ssh_diagnostics=transport.diagnostics()
            dialog=DiagnosticsDialog(worker,'generated fixture',window);output=tmp_path/'negotiated.json'
            monkeypatch.setattr('harbor_terminal.ssh_dialogs.QFileDialog.getSaveFileName',lambda *args:(str(output),''))
            dialog.export();data=json.loads(output.read_text())
            assert data['strict_kex'] is True and data['kex']
            assert 'fixture-only' not in output.read_text()
            dialog.close()
        finally:await transport.close()
