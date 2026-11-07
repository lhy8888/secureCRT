"""Local SSH/SFTP/TCP/PTY continuous validation with explicit elapsed evidence.

This is a Harbor transport/model soak, not physical COM or a vendor comparison.
The program never connects to external systems or executes received commands.
"""
import argparse
import asyncio
from collections import deque
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import signal
import socket
import tempfile
import time

import asyncssh

from harbor_terminal.forwarding import ForwardManager, ForwardSpec
from harbor_terminal.reports import atomic_json, resources
from harbor_terminal.sftp import FileRequest, SFTPService
from harbor_terminal.terminal_model import TerminalModel
from harbor_terminal.transport import SSHTransport, SerialTransport
from harbor_terminal.automation import ReceiveStream, run_flow


async def soak(report_path, duration, interval):
    if not 1 <= duration <= 604800 or not .02 <= interval <= 60: raise ValueError('Invalid soak duration or interval')
    if report_path.exists(): raise FileExistsError('Choose a new report path')
    started = time.monotonic(); stop = asyncio.Event(); loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(name, stop.set)
        except NotImplementedError: pass
    result = dict(status='running', pid=os.getpid(), version=version('harbor-terminal'),
        started=datetime.now(timezone.utc).isoformat(), requested_seconds=duration, elapsed_seconds=0,
        scope='Local SSH/SFTP/TCP/Unix PTY/model; not GUI, physical COM, or SecureCRT comparison',
        cycles=0, errors=0, ssh_bytes=0, serial_bytes=0, sftp_transfers=0, tunnel_roundtrips=0,
        planned_reconnects=0, automation_flows=0, samples=[], source_hashes={})
    import harbor_terminal.transport as transport_module
    package = Path(transport_module.__file__).parent
    for source in sorted(package.glob('*.py')):
        result['source_hashes'][source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
    latencies = deque(maxlen=4096); samples = report_path.with_suffix('.samples.jsonl')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if samples.exists(): raise FileExistsError('Choose a new samples file')
    sample_file = samples.open('x', encoding='utf-8')
    client = SSHTransport(); serial = SerialTransport(); manager = None
    descriptors = []; listeners = []; baseline = None
    temporary = tempfile.TemporaryDirectory(prefix='harbor-soak-')
    try:
        # Keep fixtures until all open SSH/SFTP handles are closed, including on Windows.
        root = Path(temporary.name); remote = root/'remote'; remote.mkdir()
        async def echo(reader, writer):
            try:
                while data := await reader.read(65536): writer.write(data); await writer.drain()
            finally: writer.close(); await writer.wait_closed()
        tcp = await asyncio.start_server(echo, '127.0.0.1', 0); listeners.append(tcp)
        echo_port = tcp.sockets[0].getsockname()[1]
        class Server(asyncssh.SSHServer):
            def begin_auth(self, username): return True
            def password_auth_supported(self): return True
            def validate_password(self, username, password): return username=='soak' and password=='local-soak-only'
            def connection_requested(self, host, port, *_): return host=='127.0.0.1' and port==echo_port
            def server_requested(self, host, port): return host=='127.0.0.1'
        async def shell(process):
            while True:
                try: data = await process.stdin.read(65536)
                except asyncssh.TerminalSizeChanged: continue
                if not data: break
                process.stdout.write(data)
        key = asyncssh.generate_private_key('ssh-ed25519')
        server = await asyncssh.create_server(Server, '127.0.0.1', 0, server_host_keys=[key],
            process_factory=shell, encoding=None, line_editor=False,
            sftp_factory=lambda channel: asyncssh.SFTPServer(channel, chroot=os.fsencode(remote)))
        listeners.append(server)
        known = root/'known_hosts'
        known.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode()+key.export_public_key())
        options = dict(host='127.0.0.1', username='soak', password='local-soak-only',
            port=server.get_port(), known_hosts=str(known), client_keys=[])
        await client.connect(**options); manager = ForwardManager(client.connection)
        model = TerminalModel()
        if os.name != 'nt':
            import pty
            master, slave = pty.openpty(); descriptors.extend((master, slave))
            await serial.connect(os.ttyname(slave))
        result['serial_scope'] = 'Unix PTY' if serial.port else 'not run'
        last_report = started-10
        atomic_json(report_path, result)
        print('Soak started:', report_path, 'requested seconds:', duration, flush=True)
        while time.monotonic()-started < duration and not stop.is_set():
            index = result['cycles']; payload = b'HARBOR-SOAK-'+index.to_bytes(8,'big')+bytes(range(256))
            before = time.monotonic(); await client.write(payload); received = bytearray()
            async with asyncio.timeout(3):
                while len(received)<len(payload):
                    data = await client.read()
                    if not data: raise IOError('SSH closed during roundtrip')
                    received.extend(data)
            if bytes(received)!=payload: raise IOError('SSH byte mismatch')
            latencies.append((time.monotonic()-before)*1000); result['ssh_bytes'] += len(payload)
            model.feed(f'\x1b[32mcycle {index} 世界\x1b[0m\r\n'.encode())
            if index % 5 == 0:
                model.feed(b'\x1b[?1049h\x1b[2Jalternate\x1b[?1049l')
            if index % 100 == 0:
                stream = ReceiveStream(); cursor = stream.cursor()
                async def receive_flow():
                    while data := await client.read(): stream.append(data)
                receiver = asyncio.create_task(receive_flow())
                async def send_flow(data): await client.write(data); return True
                text = f'soak-flow-{index}#'
                try:
                    flow = await run_flow(stream,cursor,[dict(action='send',text=text),
                        dict(action='wait',patterns=['#'],timeout=3)],send_flow)
                    if flow['captures'][0]['text'] != text[:-1]:raise IOError('Flow capture mismatch')
                    result['automation_flows'] += 1
                finally:
                    stream.close();receiver.cancel();await asyncio.gather(receiver,return_exceptions=True)
            if serial.port:
                os.write(master, payload); received = bytearray()
                async with asyncio.timeout(3):
                    while len(received)<len(payload): received.extend(await serial.read())
                if bytes(received)!=payload: raise IOError('PTY receive mismatch')
                await serial.write(payload)
                reflected = await asyncio.wait_for(asyncio.to_thread(os.read, master, len(payload)), 3)
                if reflected!=payload: raise IOError('PTY send mismatch')
                result['serial_bytes'] += len(payload)*2
            if index % 20 == 0:
                source = root/'upload.bin'; source.write_bytes(payload*4)
                service = SFTPService(client.connection)
                await service.execute(FileRequest('upload','/payload.bin',str(source),overwrite=True))
                target = root/'download.bin'
                await service.execute(FileRequest('download','/payload.bin',str(target),overwrite=True))
                if target.read_bytes()!=source.read_bytes(): raise IOError('SFTP mismatch')
                result['sftp_transfers'] += 2
            if index % 25 == 0:
                kind = ('local','remote','socks')[(index//25)%3]
                entry = await manager.start(ForwardSpec(kind,0,'127.0.0.1',echo_port))
                reader, writer = await asyncio.open_connection('127.0.0.1',entry['listen_port'])
                try:
                    if kind=='socks':
                        writer.write(b'\x05\x01\x00'); await writer.drain()
                        if await asyncio.wait_for(reader.readexactly(2),3)!=b'\x05\x00': raise IOError('SOCKS negotiation')
                        writer.write(b'\x05\x01\x00\x01'+socket.inet_aton('127.0.0.1')+echo_port.to_bytes(2,'big'))
                        await writer.drain(); reply = await asyncio.wait_for(reader.readexactly(10),3)
                        if reply[:2]!=b'\x05\x00': raise IOError('SOCKS routing')
                    writer.write(payload); await writer.drain()
                    if await asyncio.wait_for(reader.readexactly(len(payload)),3)!=payload: raise IOError('Tunnel mismatch')
                finally: writer.close(); await writer.wait_closed()
                await manager.stop(entry['id']); result['tunnel_roundtrips'] += 1
                try: reader, writer = await asyncio.open_connection('127.0.0.1',entry['listen_port'])
                except OSError: pass
                else: writer.close(); await writer.wait_closed(); raise IOError('Listener remained open')
            if index and index % 200 == 0:
                await manager.close_all(); await client.close(); await client.connect(**options)
                manager = ForwardManager(client.connection); result['planned_reconnects'] += 1
            result['cycles'] += 1
            now = time.monotonic()
            if now-last_report>=10:
                sample = resources(); sample['elapsed_seconds'] = now-started; sample['cycles'] = result['cycles']
                if baseline is None and index>=20: baseline = sample
                if baseline:
                    if sample.get('handles',0)>baseline.get('handles',0)+64: raise IOError('Handle budget exceeded')
                    if sample.get('rss_bytes',0)>baseline.get('rss_bytes',0)+128*1024*1024: raise IOError('Memory budget exceeded')
                result['samples'] = (result['samples']+[sample])[-360:]
                sample_file.write(json.dumps(sample)+'\n'); sample_file.flush(); os.fsync(sample_file.fileno())
                result['elapsed_seconds'] = now-started; result['resources'] = sample
                atomic_json(report_path,result); last_report = now
            await asyncio.sleep(interval)
        result['status'] = 'interrupted' if stop.is_set() else 'passed'
    except Exception as exc:
        result['status'] = 'failed'; result['errors'] += 1; result['error_type'] = type(exc).__name__
    finally:
        if manager: await manager.close_all()
        await client.close(); await serial.close()
        for listener in listeners: listener.close()
        await asyncio.gather(*(listener.wait_closed() for listener in listeners), return_exceptions=True)
        for descriptor in descriptors: os.close(descriptor)
        temporary.cleanup()
        sample_file.close()
        result['elapsed_seconds'] = time.monotonic()-started; result['final_resources'] = resources()
        if latencies:
            values = sorted(latencies)
            result['ssh_latency_ms'] = dict(recent_samples=len(values),p50=values[len(values)//2],
                p95=values[min(len(values)-1,int(len(values)*.95))],maximum=values[-1])
        atomic_json(report_path,result)
        print('Soak result:',result['status'],'cycles:',result['cycles'],'elapsed:',round(result['elapsed_seconds'],2),flush=True)
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--duration',type=float,default=259200)
    parser.add_argument('--interval',type=float,default=.2)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(soak(args.out,args.duration,args.interval)))
