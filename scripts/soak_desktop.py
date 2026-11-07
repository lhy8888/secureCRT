"""Continuous actual Qt/Worker/SSH/flow/storage validation on local fixtures.

This does not exercise physical COM or compare SecureCRT. Use a new report for
each process/version; running or interrupted is never a completed duration.
"""
import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import signal
import tempfile
import time

import asyncssh
from PySide6.QtWidgets import QApplication

from harbor_terminal.app import Window
from harbor_terminal.reports import atomic_json,resources


async def soak(output,duration,interval):
    if not 1<=duration<=604800 or not .002<=interval<=60:raise ValueError('Invalid duration or interval')
    if output.exists():raise FileExistsError('Choose a new report path')
    output.parent.mkdir(parents=True,exist_ok=True)
    samples=output.with_suffix('.samples.jsonl').open('x',encoding='utf-8')
    app=QApplication.instance() or QApplication([])
    stop=asyncio.Event();loop=asyncio.get_running_loop();started=time.monotonic()
    for name in (signal.SIGINT,signal.SIGTERM):
        try:loop.add_signal_handler(name,stop.set)
        except NotImplementedError:pass
    report=dict(status='running',pid=os.getpid(),version=version('harbor-terminal'),
        platform=app.platformName(),started=datetime.now(timezone.utc).isoformat(),requested_seconds=duration,
        elapsed_seconds=0,cycles=0,errors=0,protocol_queries=0,protocol_replies=0,configuration_commits=0,text_sends=0,
        scope='Actual Qt + Worker + loopback SSH + paced flows/text sends + text capture + input lock + protocol replies + profile transactions; no physical COM or vendor comparison',
        samples=[],source_hashes={})
    import harbor_terminal
    package=Path(harbor_terminal.__file__).parent
    for source in sorted(package.glob('*.py')):report['source_hashes'][source.name]=hashlib.sha256(source.read_bytes()).hexdigest()
    temporary=tempfile.TemporaryDirectory(prefix='harbor-desktop-soak-')
    window=None;server=None;baseline=None

    async def until(predicate,seconds=5):
        async with asyncio.timeout(seconds):
            while not predicate():app.processEvents();await asyncio.sleep(.005)
        app.processEvents()

    try:
        root=Path(temporary.name)
        class Server(asyncssh.SSHServer):
            def begin_auth(self,username):return True
            def password_auth_supported(self):return True
            def validate_password(self,username,password):return username=='gui-soak' and password=='local-gui-fixture-only'
        async def shell(process):
            buffer=bytearray()
            while True:
                try:data=await process.stdin.read(4096)
                except asyncssh.TerminalSizeChanged:continue
                if not data:break
                buffer.extend(data)
                replies=list(re.finditer(rb'\x1b\[[0-9]+;[0-9]+R',buffer))
                report['protocol_replies']+=len(replies)
                if replies:buffer=bytearray(re.sub(rb'\x1b\[[0-9]+;[0-9]+R',b'',buffer))
                while any(byte in buffer for byte in (10,13)):
                    end=min(index for index,byte in enumerate(buffer) if byte in (10,13))
                    line=bytes(buffer[:end]);buffer=buffer[end+1:]
                    if not line:continue
                    if not line.startswith(b'gui-'):raise ValueError('Unexpected application input')
                    if report['cycles']%25==0:
                        process.stdout.write(b'\x1b[6n');report['protocol_queries']+=1
                    process.stdout.write(b'\x1b[32m'+line+b'\x1b[0m\r\n')
                if len(buffer)>8192:raise ValueError('Fixture input exceeded budget')
        key=asyncssh.generate_private_key('ssh-ed25519')
        server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],
            process_factory=shell,encoding=None,line_editor=False)
        known=root/'known_hosts';known.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode()+key.export_public_key())
        window=Window(profile_path=root/'sessions.json');window.show();app.processEvents()
        window.host.setText('127.0.0.1');window.port.setText(str(server.get_port()))
        window.user.setText('gui-soak');window.password.setText('local-gui-fixture-only');window.known.setText(str(known))
        window.options.update(send_char_delay_ms='1',send_line_delay_ms='10')
        window.connect_session();terminal=window.tabs.currentWidget();worker=terminal.worker
        await until(lambda:worker.status in ('Connected','Disconnected') and (worker.status=='Connected' or not worker.isRunning()))
        if worker.status!='Connected':raise ConnectionError('Local GUI fixture did not connect')
        if not worker.start_text_capture(root/'text-capture.txt',max_bytes=64*1048576):raise RuntimeError('Text capture did not start')
        await until(lambda:worker.text_capture.snapshot()['state']=='running')
        atomic_json(output,report);print('Desktop soak started:',output,flush=True)
        last_sample=started-10
        while time.monotonic()-started<duration and not stop.is_set():
            index=report['cycles'];marker=f'gui-{index:08d}-世界#'
            if index%100==0:
                identifier=worker.submit_text((marker+'\r').encode(),prompt=marker,timeout=3);report['text_sends']+=1
            else:identifier=worker.submit_flow([dict(action='send',text=marker),dict(action='wait',patterns=[marker],timeout=3)])
            if not identifier:raise RuntimeError('Flow not accepted')
            worker.set_input_locked(True)
            await until(lambda:worker.flow_progress().get('phase') in ('success','error','cancelled'))
            if worker.flow_progress().get('phase')!='success':
                report['last_flow']=worker.flow_progress();raise RuntimeError('Flow did not complete')
            if worker.send(b'unexpected-manual-input'):raise RuntimeError('Input lock failed')
            await until(lambda:marker in terminal.toPlainText())
            if index%25==0:await until(lambda:report['protocol_replies']==report['protocol_queries'])
            if worker.stop_event.is_set():raise ConnectionError('Terminal response interrupted the connection')
            capture=worker.text_capture.snapshot()
            if capture['state']!='running':raise RuntimeError('Text capture stopped unexpectedly')
            worker.set_input_locked(False)
            if index%250==0:
                if not window.commit_profiles({'fixture':dict(terminal.connection_profile)}):raise RuntimeError('Profile commit failed')
                report['configuration_commits']+=1
            report['cycles']+=1;now=time.monotonic()
            if now-last_sample>=10:
                sample=resources();sample.update(elapsed_seconds=now-started,cycles=report['cycles'])
                if baseline is None and now-started>=60:baseline=sample
                if baseline:
                    if sample.get('handles',0)>baseline.get('handles',0)+64:raise RuntimeError('Handle budget exceeded')
                    if sample.get('rss_bytes',0)>baseline.get('rss_bytes',0)+128*1024*1024:raise RuntimeError('Memory budget exceeded')
                report['samples']=(report['samples']+[sample])[-360:]
                report.update(elapsed_seconds=now-started,resources=sample,text_capture=capture)
                samples.write(json.dumps(sample)+'\n');samples.flush();os.fsync(samples.fileno())
                atomic_json(output,report);last_sample=now
            deadline=min(time.monotonic()+interval,started+duration)
            while time.monotonic()<deadline and not stop.is_set():app.processEvents();await asyncio.sleep(.005)
        report['status']='interrupted' if stop.is_set() else 'passed'
    except (KeyboardInterrupt,asyncio.CancelledError):report['status']='interrupted'
    except Exception as exc:report['status']='failed';report['errors']+=1;report['error_type']=type(exc).__name__
    finally:
        if window:
            for worker in window.workers:worker.stop_event.set()
            try:await until(lambda:all(not worker.isRunning() for worker in window.workers),8)
            except TimeoutError:report['status']='failed';report['cleanup_timeout']=True
            window.close();app.processEvents()
        if server:
            server.close()
            try:await asyncio.wait_for(server.wait_closed(),5)
            except TimeoutError:report['status']='failed';report['server_cleanup_timeout']=True
        samples.close();temporary.cleanup()
        report.update(elapsed_seconds=time.monotonic()-started,final_resources=resources())
        atomic_json(output,report)
        print('Desktop soak result:',report['status'],'cycles:',report['cycles'],'seconds:',round(report['elapsed_seconds'],2),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--duration',type=float,default=259200)
    parser.add_argument('--interval',type=float,default=.2);args=parser.parse_args()
    raise SystemExit(asyncio.run(soak(args.out,args.duration,args.interval)))
