"""One cancellable owner per connection; reads and writes have independent tasks."""
import asyncio
from collections import deque
import threading
import uuid

import asyncssh
import serial

from PySide6.QtCore import QThread, Signal

from .serial_config import discover_ports
from .transport import SSHTransport, SerialTransport, IncompleteWriteError
from .sftp import FileRequest, SFTPService, file_error, CommitUncertainError
from .trace import ByteTrace
from .journal import SessionJournal
from .forwarding import ForwardSpec, ForwardManager
from .authentication import AuthenticationBroker, AuthenticationCancelled, AuthenticationTimeout, AuthenticationLimit
from .automation import ReceiveStream, run_flow, validate_steps
from .ssh_policy import SecurityPolicyError
from .input_policy import InputPolicy
from .text_files import TextCapture,prepare_file


class Worker(QThread):
    failed = Signal(str)
    state = Signal(str)
    file_result = Signal(dict)
    forward_result = Signal(dict)
    auth_requested = Signal(dict)
    flow_result = Signal(dict)
    control_result = Signal(dict)

    def __init__(self, mode, options, *, transport_factory=None,input_policy=None):
        super().__init__()
        self.mode, self.options = mode, dict(options)
        self.session_id = uuid.uuid4().hex
        self.interactive = mode!='SSH' or self.options.get('shell',True)
        self.input_locked = False
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.incoming, self.outgoing = bytearray(), bytearray()
        self._protocol_outgoing = bytearray()
        self._ssh_diagnostics = {}
        self.input_policy=InputPolicy.parse(input_policy);self._writing=False;self._writing_job=None
        self.text_capture=None;self._serial_snapshot={}
        self.status = 'Disconnected'
        self._size = (100, 30)
        self._resize = True
        self._controls = deque(maxlen=16)
        self._factory = transport_factory or (SSHTransport if mode == 'SSH' else SerialTransport)
        self.trace = ByteTrace()
        self.journal = None
        self._file_job = None
        self._file_progress = {}
        self._forward_jobs = deque()
        self._forward_snapshot = []
        self.authentication = AuthenticationBroker(self.auth_requested.emit)
        self.receive_stream = ReceiveStream()
        self._flow_job = None; self._flow_progress = {}; self._outgoing_owner = None

    def reply_auth(self, identifier, answers):
        accepted = self.authentication.reply(identifier, answers)
        if accepted and answers is None: self.stop_event.set()
        return accepted

    def ssh_diagnostics(self):
        with self.lock:return dict(self._ssh_diagnostics)

    def _set_state(self, state):
        with self.lock:
            self.status = state
        self.state.emit(state)

    def submit_file(self, action, **options):
        request = FileRequest(action, **options)
        with self.lock:
            if self.mode != 'SSH' or self.status != 'Connected' or self.stop_event.is_set() or self._file_job:
                return None
            self._file_job = dict(request=request, cancel=threading.Event(), started=False)
            self._file_progress = dict(id=request.id, phase='starting', current=0, total=0)
        return request.id

    def cancel_file(self, request_id):
        with self.lock:
            if self._file_job and self._file_job['request'].id == request_id:
                self._file_job['cancel'].set()
                return True
        return False

    def file_progress(self):
        with self.lock:
            return dict(self._file_progress)

    def start_log(self, path, **options):
        with self.lock:
            if self.status != 'Connected' or self.stop_event.is_set():
                return False
            if self.journal and self.journal.snapshot()['alive']:
                return False
            journal = SessionJournal(path, **options)
            self.journal = journal
            journal.start()
        return True

    def _observe(self, direction, data):
        if direction == 'RX': self.receive_stream.append(data)
        if direction=='RX' and self.text_capture:self.text_capture.record(data)
        self.trace.append(direction, data)
        if self.journal:
            self.journal.record(direction, data)

    def start_text_capture(self,path,**options):
        with self.lock:
            if self.status!='Connected' or self.stop_event.is_set() or not self.interactive:return False
            if self.text_capture and self.text_capture.snapshot()['alive']:return False
            self.text_capture=TextCapture(path,**options);self.text_capture.start();return True

    def stop_text_capture(self):
        with self.lock:
            if self.text_capture:self.text_capture.close()

    def serial_snapshot(self):
        with self.lock:return dict(self._serial_snapshot)

    def set_serial_line(self,name,value):
        if name not in ('dtr','rts') or type(value) is not bool:raise ValueError('Invalid serial line operation')
        with self.lock:
            if self.mode!='Serial' or self.status!='Connected' or self.stop_event.is_set() or self.input_locked or len(self._controls)>=16:return None
            identifier=uuid.uuid4().hex;self._controls.append(('line',(identifier,name,value)));return identifier

    def submit_forward(self, action, **options):
        if action == 'start':
            spec = ForwardSpec(**options)
        elif action == 'stop' and isinstance(options.get('id'), str):
            spec = options['id']
        else:
            raise ValueError('Invalid forwarding operation')
        identifier = uuid.uuid4().hex
        with self.lock:
            if (self.mode != 'SSH' or self.status != 'Connected' or self.stop_event.is_set()
                    or len(self._forward_jobs) >= 8):
                return None
            self._forward_jobs.append((identifier, action, spec))
        return identifier

    def forwards(self):
        with self.lock:
            return [dict(item) for item in self._forward_snapshot]

    def send(self, data, *, owner=None):
        with self.lock:
            if self.status != 'Connected' or self.stop_event.is_set() or not self.interactive:
                return False
            if self.input_locked and owner is None:return False
            job = self._flow_job
            if job:
                if owner != job['id']:
                    if data != b'\x03': return False
                    job['cancel'].set()
                    if self._outgoing_owner == job['id']: self.outgoing.clear()
                elif job['cancel'].is_set(): return False
            if len(self.outgoing) + len(data) > 65536:
                return False
            self.outgoing.extend(data)
            self._outgoing_owner = owner
        return True

    def set_input_locked(self,locked):
        with self.lock:self.input_locked=bool(locked)

    def respond(self,data):
        # Terminal protocol replies are independent of manual input and jobs.
        with self.lock:
            if (self.status!='Connected' or self.stop_event.is_set() or not self.interactive
                    or not data or len(data)>1024 or len(self._protocol_outgoing)+len(data)>4096):return False
            self._protocol_outgoing.extend(data);return True

    def submit_flow(self, steps, encoding='utf-8'):
        steps = validate_steps(steps)
        for step in steps:
            if step['action']=='send': step['text'].encode(encoding)
        with self.lock:
            if self.status!='Connected' or self.stop_event.is_set() or not self.interactive or self.input_locked or self._flow_job or self.outgoing or self._writing: return None
            identifier = uuid.uuid4().hex
            self._flow_job = dict(id=identifier,steps=steps,cursor=self.receive_stream.cursor(),
                encoding=encoding,cancel=threading.Event())
            self._flow_progress = dict(id=identifier,phase='starting',step=0,total=len(steps))
            return identifier

    def submit_text(self,payload,*,encoding='utf-8',prompt='',timeout=30):
        payload=prepare_file(payload,encoding,encoding,'keep')
        if not isinstance(prompt,str) or len(prompt)>1024 or any(ord(c)<32 for c in prompt):raise ValueError('Invalid literal prompt')
        if type(timeout) not in (int,float) or not .1<=timeout<=120:raise ValueError('Invalid prompt deadline')
        with self.lock:
            if self.status!='Connected' or self.stop_event.is_set() or not self.interactive or self.input_locked or self._flow_job or self.outgoing or self._writing:return None
            identifier=uuid.uuid4().hex
            self._flow_job=dict(id=identifier,kind='text',payload=payload,prompt=prompt,timeout=timeout,sent=0,queued=0,
                                encoding=encoding,cancel=threading.Event())
            self._flow_progress=dict(id=identifier,phase='starting',current=0,total=len(payload))
            return identifier

    def cancel_flow(self, identifier):
        with self.lock:
            if not self._flow_job or self._flow_job['id']!=identifier:return False
            self._flow_job['cancel'].set()
            if self._outgoing_owner==identifier:self.outgoing.clear();self._outgoing_owner=None
            return True

    def flow_progress(self):
        with self.lock:return dict(self._flow_progress)

    def resize(self, columns, rows):
        with self.lock:
            self._size = (max(1, min(512, columns)), max(1, min(200, rows)))
            self._resize = True

    def send_break(self):
        with self.lock:
            if self.status != 'Connected' or self.stop_event.is_set() or not self.interactive or self.input_locked or len(self._controls) >= 16:
                return False
            self._controls.append(('break', 0.25))
        return True

    def take(self):
        with self.lock:
            result = bytes(self.incoming[:16384])
            del self.incoming[:16384]
        return result

    async def _wait_stop(self):
        while not self.stop_event.is_set():
            await asyncio.sleep(.01)

    async def _reader(self, transport):
        while True:
            data = await transport.read()
            if not data and self.mode == 'SSH':
                return
            self._observe('RX', data)
            while data:
                with self.lock:
                    available = 262144 - len(self.incoming)
                    self.incoming.extend(data[:available])
                data = data[available:]
                if data:
                    await asyncio.sleep(.01)

    async def _writer(self, transport):
        while True:
            with self.lock:
                if self.stop_event.is_set():
                    self.outgoing.clear()
                    self._protocol_outgoing.clear()
                    return
                protocol = bytes(self._protocol_outgoing)
                self._protocol_outgoing.clear()
                outgoing = bytes(self.outgoing)
                owner = self._outgoing_owner
                owned_job = self._flow_job if self._flow_job and self._flow_job['id']==owner else None
                self.outgoing.clear()
                self._outgoing_owner = None
                self._writing=bool(outgoing)
                self._writing_job=owned_job if outgoing else None
            if protocol or outgoing:
                try:
                    if protocol:await self._write_piece(transport,protocol)
                    for payload,delay in self.input_policy.chunks(outgoing):
                        if self.stop_event.is_set() or owned_job and owned_job['cancel'].is_set():break
                        if payload:await self._write_piece(transport,payload,owned_job)
                        if delay and not await self._pause_input(transport,delay,owned_job):break
                finally:
                    with self.lock:self._writing=False;self._writing_job=None
            else:
                await asyncio.sleep(.01)

    async def _write_piece(self,transport,payload,job=None):
        sent=0
        try:
            await asyncio.wait_for(transport.write(payload),5);sent=len(payload)
        except IncompleteWriteError as exc:
            sent=exc.sent
            if job and job.get('kind')=='text':job['write_error']=type(exc).__name__
            raise
        except asyncio.CancelledError:
            if job and job.get('kind')=='text':job['write_uncertain']=True
            raise
        except Exception as exc:
            if job and job.get('kind')=='text':job.update(write_uncertain=True,write_error=type(exc).__name__)
            raise
        finally:
            if sent:self._observe('TX',payload[:sent])
            if job and job.get('kind')=='text':
                with self.lock:
                    job['sent']+=sent;self._flow_progress=dict(self._flow_progress,current=job['sent'])

    async def _pause_input(self,transport,seconds,job):
        deadline=asyncio.get_running_loop().time()+seconds
        while True:
            if self.stop_event.is_set() or job and job['cancel'].is_set():return False
            with self.lock:protocol=bytes(self._protocol_outgoing);self._protocol_outgoing.clear()
            if protocol:await self._write_piece(transport,protocol)
            remaining=deadline-asyncio.get_running_loop().time()
            if remaining<=0:return True
            await asyncio.sleep(min(.01,remaining))

    async def _control(self, transport):
        last_diagnostics=0;last_serial=0
        while True:
            with self.lock:
                if self.stop_event.is_set():
                    self._controls.clear()
                    return
                size = self._size if self._resize else None
                self._resize = False
                control = self._controls.popleft() if self._controls else None
            if size and self.mode == 'SSH':
                await transport.resize(*size)
            if control:
                if control[0]=='break':await asyncio.wait_for(transport.send_break(control[1]), 3)
                else:
                    identifier,name,value=control[1];event=dict(id=identifier,status='success',line=name)
                    try:await transport.set_line(name,value)
                    except Exception as exc:event.update(status='error',code=type(exc).__name__)
                    self.control_result.emit(event)
            now=asyncio.get_running_loop().time()
            if self.mode=='SSH' and hasattr(transport,'diagnostics') and now-last_diagnostics>=1:
                snapshot=transport.diagnostics()
                with self.lock:self._ssh_diagnostics=snapshot
                last_diagnostics=now
            if self.mode=='Serial' and hasattr(transport,'modem_status') and now-last_serial>=.5:
                snapshot=await transport.modem_status()
                with self.lock:self._serial_snapshot=snapshot
                last_serial=now
            await asyncio.sleep(.025)

    async def _file_operations(self, transport):
        while True:
            with self.lock:
                job = self._file_job
                if job:
                    job['started'] = True
            if not job:
                await asyncio.sleep(.025)
                continue
            request = job['request']
            service = SFTPService(getattr(transport, 'connection', None))
            def progress(phase, current, total):
                with self.lock:
                    self._file_progress = dict(id=request.id, phase=phase, current=current, total=total)
            async def cancelled():
                while not job['cancel'].is_set():
                    await asyncio.sleep(.025)
            operation = asyncio.create_task(service.execute(request, progress))
            monitor = asyncio.create_task(cancelled())
            event = dict(id=request.id, action=request.action, status='cancelled', result={})
            try:
                done, _ = await asyncio.wait((operation, monitor), return_when=asyncio.FIRST_COMPLETED)
                if monitor in done and not operation.done():
                    operation.cancel()
                # Owner cancellation is handled below, once, so a concurrent
                # disconnect cannot interrupt the child's resource cleanup twice.
                event['result'] = await asyncio.shield(operation)
                event['status'] = 'success'
            except asyncio.CancelledError:
                if not operation.done() and not operation.cancelling():
                    operation.cancel()
                result = (await asyncio.gather(operation, return_exceptions=True))[0]
                if isinstance(result, dict):
                    event['result'], event['status'] = result, 'success'
                elif isinstance(result, CommitUncertainError):
                    event['code'], event['message'] = file_error(result)
                    event['status'] = 'uncertain'
                elif isinstance(result, Exception):
                    event['code'], event['message'] = file_error(result)
                    event['status'] = 'error'
                # Do not swallow cancellation of the owner task during disconnect.
                if asyncio.current_task().cancelling():
                    raise
            except Exception as exc:
                event['code'], event['message'] = file_error(exc)
                event['status'] = 'uncertain' if isinstance(exc, CommitUncertainError) else 'error'
            finally:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
                event['cleanup_warning'] = service.cleanup_failed
                with self.lock:
                    if self._file_job is job:
                        self._file_job = None
                    self._file_progress = dict(id=request.id, phase=event['status'], current=0, total=0)
                self.file_result.emit(event)

    async def _forward_operations(self, transport):
        manager = ForwardManager(getattr(transport, 'connection', None))
        try:
            while True:
                with self.lock:
                    job = self._forward_jobs.popleft() if self._forward_jobs else None
                if not job:
                    await asyncio.sleep(.025)
                    continue
                identifier, action, spec = job
                event = dict(id=identifier, action=action, status='error')
                try:
                    if action == 'start':
                        event['result'] = await manager.start(spec)
                    else:
                        await manager.stop(spec)
                    event['status'] = 'success'
                except asyncio.CancelledError:
                    event['status'] = 'cancelled'
                    raise
                except Exception as exc:
                    event['message'] = type(exc).__name__ + ': 转发操作失败，请检查端口占用、目标与服务端转发权限'
                finally:
                    with self.lock:
                        self._forward_snapshot = manager.snapshot()
                    self.forward_result.emit(event)
        finally:
            failures = await manager.close_all()
            with self.lock:
                self._forward_snapshot = []
                pending = list(self._forward_jobs)
                self._forward_jobs.clear()
            for identifier, action, _ in pending:
                self.forward_result.emit(dict(id=identifier, action=action, status='cancelled'))
            if failures:
                self.failed.emit('部分转发监听未确认关闭；SSH连接关闭将继续释放资源')

    async def _workflow_operations(self, transport):
        while True:
            with self.lock: job = self._flow_job
            if not job:
                await asyncio.sleep(.02); continue
            identifier = job['id']
            def progress(value):
                with self.lock:self._flow_progress = dict(id=identifier,phase='running',**value)
            operation = asyncio.create_task(self._send_text(job) if job.get('kind')=='text' else
                run_flow(self.receive_stream,job['cursor'],job['steps'],
                    lambda data:self.send(data,owner=identifier),encoding=job['encoding'],progress=progress))
            async def cancellation():
                while not job['cancel'].is_set():await asyncio.sleep(.02)
            monitor = asyncio.create_task(cancellation())
            event = dict(id=identifier,status='cancelled',result={})
            try:
                done,_ = await asyncio.wait((operation,monitor),return_when=asyncio.FIRST_COMPLETED)
                if job['cancel'].is_set():
                    operation.cancel();await asyncio.gather(operation,return_exceptions=True)
                else:
                    event['result'] = await asyncio.shield(operation); event['status'] = 'success'
            except asyncio.CancelledError:
                operation.cancel(); await asyncio.gather(operation,return_exceptions=True)
                if asyncio.current_task().cancelling():raise
            except Exception as exc:
                event['status']='error';event['code']=type(exc).__name__
                event['message']=type(exc).__name__+'：流程停止；已发送内容无法撤回，不会自动重试'
            finally:
                monitor.cancel();await asyncio.gather(monitor,return_exceptions=True)
                if job.get('kind')=='text' and event['status']!='success':
                    job['cancel'].set()
                    with self.lock:
                        if self._outgoing_owner==identifier:self.outgoing.clear();self._outgoing_owner=None
                    while True:
                        with self.lock:writing=self._writing_job is job
                        if not writing:break
                        await asyncio.sleep(.01)
                with self.lock:
                    if event['status']!='success':job['cancel'].set()
                    if job.get('kind')=='text':event.update(bytes_sent=job['sent'],write_uncertain=job.get('write_uncertain',False))
                    event['sends_queued']=event['result'].get('sends_queued',self._flow_progress.get('sends_queued',0))
                    if job.get('kind')=='text':
                        event['sends_queued']=job['queued']
                        if job.get('write_error'):event.update(status='error',code=job['write_error'])
                    if self._flow_job is job:self._flow_job=None
                    if self._outgoing_owner==identifier and event['status']!='success':
                        self.outgoing.clear();self._outgoing_owner=None
                    self._flow_progress=dict(self._flow_progress,phase=event['status'])
                self.flow_result.emit(event)

    async def _send_text(self,job):
        lines=job['payload'].splitlines(keepends=True)
        async with asyncio.timeout(3600):
            for index,line in enumerate(lines):
                cursor=self.receive_stream.cursor()
                if job['cancel'].is_set():raise asyncio.CancelledError()
                if not self.send(line,owner=job['id']):raise RuntimeError('Text send queue unavailable')
                job['queued']+=1
                while True:
                    if job['cancel'].is_set():raise asyncio.CancelledError()
                    with self.lock:pending=bool(self.outgoing) or self._writing
                    if not pending:break
                    await asyncio.sleep(.01)
                if job['prompt']:await self.receive_stream.read_until(cursor,[job['prompt']],job['timeout'])
                with self.lock:self._flow_progress=dict(self._flow_progress,line=index+1,lines=len(lines),current=job['sent'])
        return dict(sends_queued=job['queued'],bytes_sent=job['sent'])

    async def session(self):
        transport = self._factory()
        tasks = []
        try:
            if self.stop_event.is_set():
                return
            self._set_state('Connecting')
            options = dict(self.options)
            if self.mode == 'SSH':
                with self.lock:
                    options['term_size'] = self._size
                options['status'] = self._set_state
                options['auth_prompt'] = self.authentication.ask
            connect = asyncio.create_task(transport.connect(**options))
            stop = asyncio.create_task(self._wait_stop())
            tasks.extend((connect, stop))
            done, _ = await asyncio.wait((connect, stop), return_when=asyncio.FIRST_COMPLETED)
            if stop in done:
                return
            await connect
            if self.mode=='SSH' and hasattr(transport,'diagnostics'):
                with self.lock:self._ssh_diagnostics=transport.diagnostics()
            options.clear()
            self.options.pop('password', None)
            self.options.pop('passphrase', None)
            self.options.pop('jump', None)
            self._set_state('Connected')
            running = [asyncio.create_task(operation(transport)) for operation in
                       (self._reader, self._writer, self._control, self._workflow_operations)]
            if self.mode == 'SSH':
                running.append(asyncio.create_task(self._file_operations(transport)))
                running.append(asyncio.create_task(self._forward_operations(transport)))
            tasks.extend(running)
            done, _ = await asyncio.wait([*running, stop], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        except Exception as exc:
            # Type is diagnostic; arbitrary exception text may contain secrets.
            if isinstance(exc, SecurityPolicyError):
                message = '服务器未通过必需的Strict KEX核验，已在发送认证凭据前停止'
            elif isinstance(exc, AuthenticationCancelled):
                message = '认证已取消'
            elif isinstance(exc, AuthenticationTimeout):
                message = '等待认证输入超时，连接已停止'
            elif isinstance(exc, AuthenticationLimit):
                message = '认证提示超过大小或轮数限制，连接已停止'
            elif isinstance(exc, asyncssh.HostKeyNotVerifiable):
                message = '主机密钥未知或已变更，请独立核验；不会跳过校验'
            elif isinstance(exc, asyncssh.PermissionDenied):
                message = '认证被拒绝，请检查用户名、密码或密钥'
            elif isinstance(exc, serial.SerialException):
                message = '串口不可用、已被占用或设备已断开'
            elif isinstance(exc, IncompleteWriteError):
                message = '串口写入不完整，可能有部分字节已发送；不会自动重发'
            elif isinstance(exc, TimeoutError):
                message = '连接或写入超时，已停止会话'
            else:
                message = '连接失败，请检查主机信任、认证或设备权限'
            if self.status == 'ConnectingJump':
                message = '跳板连接：' + message
            elif self.status == 'ConnectingTarget':
                message = '目标连接：' + message
            self.failed.emit(type(exc).__name__ + ': ' + message)
        finally:
            self._set_state('Closing')
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            with self.lock:
                pending = self._file_job
                self._file_job = None
                pending_flow = self._flow_job
                self._flow_job = None
            self.receive_stream.close()
            if pending_flow:
                self.flow_result.emit(dict(id=pending_flow['id'],status='cancelled',result={}))
            if pending:
                self.file_result.emit(dict(id=pending['request'].id, action=pending['request'].action,
                                          status='cancelled', result={}, cleanup_warning=False))
            self.options.pop('password', None)
            self.options.pop('passphrase', None)
            self.options.pop('jump', None)
            with self.lock:
                self.outgoing.clear()
                self._protocol_outgoing.clear()
                self._controls.clear()
            try:
                await transport.close()
            except Exception:
                self.failed.emit('Connection cleanup failed')
            if self.journal:
                self.journal.event('disconnected')
                if not await asyncio.to_thread(self.journal.close, 5):
                    self.failed.emit('日志未能在5秒内关闭，文件可能未完全写入')
            if self.text_capture:
                if not await asyncio.to_thread(self.text_capture.close,5):self.failed.emit('文本接收文件未能在5秒内关闭，请核对部分输出')
            self._set_state('Disconnected')

    def run(self):
        asyncio.run(self.session())


class PortProbe(QThread):
    ports_ready = Signal(list)
    failed = Signal(str)

    def run(self):
        try:
            self.ports_ready.emit(discover_ports())
        except Exception:
            self.failed.emit('无法枚举串口；仍可手动输入设备名')
