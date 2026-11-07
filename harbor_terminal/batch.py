"""Explicit headless flow execution. Authentication secrets are not CLI flags."""
import asyncio
from datetime import datetime, timezone
import getpass
from importlib.metadata import version
from pathlib import Path
import time

from .automation import ReceiveStream, run_flow
from .commands import parse_flow
from .endpoint import parse_destination
from .profiles import load
from .reports import atomic_json
from .serial_config import SerialSettings
from .transport import SSHTransport, SerialTransport
from .ssh_policy import POLICY_FIELDS


async def run_batch(args):
    if args.output is None:raise ValueError('Batch execution requires an explicit output report')
    output=Path(args.output)
    if output.exists():raise FileExistsError('Choose a new batch report path')
    flow_path=Path(args.run_flow)
    if flow_path.stat().st_size>262144:raise ValueError('Flow definition exceeds 256 KiB')
    steps=parse_flow(flow_path.read_text(encoding='utf-8'))
    profile={}
    if args.profile:
        if args.sessions is None:raise ValueError('Batch profiles require --sessions')
        profile=load(args.sessions).get(args.profile)
        if profile is None:raise ValueError('Unknown profile')
    if args.destination and (args.serial_port or profile.get('mode')=='Serial'):
        raise ValueError('SSH and serial targets cannot be mixed')
    if args.serial_port and profile.get('mode','Serial')!='Serial':raise ValueError('Conflicting profile protocol')
    serial=bool(args.serial_port or profile.get('mode')=='Serial')
    if serial:
        if args.identity_file or args.certificate_file or args.known_hosts or args.auth_method or args.channels_only:
            raise ValueError('SSH authentication options cannot be combined with serial flows')
        settings=SerialSettings(args.baudrate if args.baudrate is not None else int(profile.get('port',115200)),int(profile.get('bytesize','8')),
            profile.get('parity','N'),float(profile.get('stopbits','1')),profile.get('flow_control','none'))
        device=args.serial_port or profile.get('host')
        if not device:raise ValueError('Serial batch execution needs an explicit device')
        transport=SerialTransport()
        # Port options use the pyserial spelling, while the transport takes the
        # validated single flow-control selection.
        options=dict(device=device,baudrate=settings.baudrate,bytesize=settings.bytesize,
            parity=settings.parity,stopbits=settings.stopbits,flow_control=settings.flow_control)
        identity=dict(protocol='Serial',device=device,baudrate=settings.baudrate)
    else:
        if args.channels_only or profile.get('ssh_mode')=='channels':raise ValueError('Flows need an interactive shell')
        endpoint=parse_destination(args.destination or profile.get('host',''),
            username=args.username if args.username is not None else profile.get('username') or getpass.getuser(),
            port=args.port if args.port is not None else int(profile.get('port','22')))
        transport=SSHTransport()
        options=dict(host=endpoint.host,username=endpoint.username,port=endpoint.port,
            known_hosts=args.known_hosts or profile.get('known_hosts'),
            auth_method=args.auth_method or profile.get('auth_method','auto'))
        key=args.identity_file or profile.get('private_key')
        if key:options['client_keys']=[str(key)]
        options['security']={field:profile[field] for field in POLICY_FIELDS if field in profile}
        certificate=args.certificate_file or profile.get('client_certificate')
        if certificate:options['client_certs']=[str(certificate)]
        reference=profile.get('jump_profile')
        if reference:
            jump=load(args.sessions).get(reference)
            if not jump or jump.get('mode','SSH')!='SSH' or jump.get('jump_profile'):raise ValueError('Invalid single-hop jump profile')
            options['jump']=dict(host=jump.get('host',''),username=jump.get('username',''),
                port=int(jump.get('port','22')),known_hosts=jump.get('known_hosts'),auth_method=jump.get('auth_method','auto'))
            if jump.get('private_key'):options['jump']['client_keys']=[jump['private_key']]
            options['jump']['security']={field:jump[field] for field in POLICY_FIELDS if field in jump}
            if jump.get('client_certificate'):options['jump']['client_certs']=[jump['client_certificate']]
        for peer in (options,options.get('jump',{})):
            policy=peer.get('security',{})
            if (policy.get('ssh_allow_legacy')=='true' or policy.get('ssh_strict_kex')=='prefer') and not args.allow_legacy_ssh:
                raise ValueError('Compatibility profiles require explicit --allow-legacy-ssh')
        identity=dict(protocol='SSH2',host=endpoint.host,username=endpoint.username,port=endpoint.port)
    stream=ReceiveStream(profile.get('encoding','utf-8'));cursor=stream.cursor();reader=None
    result=dict(status='running',version=version('harbor-terminal'),target=identity,
        started=datetime.now(timezone.utc).isoformat(),result={},progress={})
    started=time.monotonic();atomic_json(output,result)
    try:
        await transport.connect(**options)
        async def receive():
            try:
                while True:
                    data=await transport.read()
                    if not data and not serial:break
                    stream.append(data)
            finally:stream.close()
        reader=asyncio.create_task(receive())
        async def send(data):await asyncio.wait_for(transport.write(data),5);return True
        result['result']=await run_flow(stream,cursor,steps,send,encoding=profile.get('encoding','utf-8'),
            progress=lambda value:result.update(progress=value))
        result['status']='success'
    except (asyncio.CancelledError,KeyboardInterrupt):result['status']='interrupted'
    except Exception as exc:result['status']='error';result['error_type']=type(exc).__name__
    finally:
        stream.close()
        if reader:
            reader.cancel();await asyncio.gather(reader,return_exceptions=True)
        try:await transport.close()
        except Exception:result['cleanup_error']=True;result['status']='error'
        result['elapsed_seconds']=time.monotonic()-started;atomic_json(output,result)
    return 0 if result['status']=='success' else 130 if result['status']=='interrupted' else 1
