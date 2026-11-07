"""Bounded text sending and opt-in plain-text receive capture; no auto retry."""
import codecs
import os
from pathlib import Path
import queue
import threading

from .automation import PlainReceiveFilter
from .input_policy import convert_newlines
from .terminal_model import ENCODINGS

MAX_TEXT_BYTES=1048576


def prepare_file(raw,source_encoding,target_encoding,newline):
    if not isinstance(raw,bytes) or len(raw)>MAX_TEXT_BYTES:raise ValueError('Text input exceeds 1 MiB')
    if source_encoding not in (*ENCODINGS,'utf-8-sig','ascii','utf-16') or target_encoding not in (*ENCODINGS,'ascii'):
        raise ValueError('Unsupported text encoding')
    text=raw.decode(source_encoding)
    if any(ord(c)<32 and c not in '\r\n\t' or 127<=ord(c)<160 for c in text):
        raise ValueError('Text files cannot contain terminal control characters')
    payload=convert_newlines(text,newline).encode(target_encoding)
    if not payload or len(payload)>MAX_TEXT_BYTES:raise ValueError('Text output needs 1 byte–1 MiB')
    if any(len(line)>65536 for line in payload.splitlines(keepends=True)):raise ValueError('Text line exceeds 64 KiB')
    return payload


class NewlineFilter:
    def __init__(self,style):
        convert_newlines('',style);self.style=style;self.pending=''

    def feed(self,text,final=False):
        if self.style=='keep':return text
        text=self.pending+text;self.pending=''
        if text.endswith('\r') and not final:self.pending='\r';text=text[:-1]
        return convert_newlines(text,self.style)


class TextCapture:
    def __init__(self,path,*,source_encoding='utf-8',output_encoding='utf-8',newline='keep',max_bytes=8*1048576,capacity=1048576):
        if source_encoding not in ENCODINGS or output_encoding not in (*ENCODINGS,'ascii'):raise ValueError('Unsupported text encoding')
        if type(max_bytes) is not int or not 1024<=max_bytes<=64*1048576 or type(capacity) is not int or not 1<=capacity<=1048576:
            raise ValueError('Invalid capture limit')
        self.newlines=NewlineFilter(newline);self.path=Path(path);self.source_encoding=source_encoding;self.output_encoding=output_encoding
        self.max_bytes=max_bytes;self.capacity=capacity;self.lock=threading.Lock();self.queue=queue.Queue(maxsize=256)
        self.stop=threading.Event();self.state='opening';self.error='';self.queued=self.written=self.accepted=0
        self.thread=threading.Thread(target=self._run,name='HarborTextCapture',daemon=True)

    def start(self):self.thread.start()

    def record(self,data):
        if not data:return False
        with self.lock:
            if self.state not in ('opening','running'):return False
            if self.queued+len(data)>self.capacity or self.queue.full():
                self.state='error';self.error='Receive queue full; capture stopped, file may be partial';self.stop.set();return False
            self.queue.put_nowait(bytes(data));self.queued+=len(data);self.accepted+=len(data);return True

    def snapshot(self):
        with self.lock:return dict(state=self.state,error=self.error,queued=self.queued,written=self.written,
                                   accepted=self.accepted,path=str(self.path),alive=self.thread.is_alive())

    def close(self,timeout=0):
        with self.lock:
            if self.state in ('opening','running'):self.state='closing'
        self.stop.set()
        if timeout:self.thread.join(timeout)
        return not self.thread.is_alive()

    def _run(self):
        file=None;decoder=codecs.getincrementaldecoder(self.source_encoding)(errors='strict')
        encoder=codecs.getincrementalencoder(self.output_encoding)(errors='strict');plain=PlainReceiveFilter()
        def write(text,final=False):
            payload=encoder.encode(self.newlines.feed(text,final),final=final)
            if self.written+len(payload)>self.max_bytes:raise ValueError('Text capture size limit')
            if file.write(payload)!=len(payload):raise OSError('Incomplete text capture write')
            with self.lock:self.written+=len(payload)
        try:
            descriptor=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:file=os.fdopen(descriptor,'wb')
            except BaseException:os.close(descriptor);raise
            with self.lock:
                if self.state=='opening':self.state='running'
            while not self.stop.is_set() or not self.queue.empty():
                try:data=self.queue.get(timeout=.05)
                except queue.Empty:continue
                with self.lock:self.queued-=len(data)
                write(decoder.decode(plain.feed(data)))
            write(decoder.decode(b'',final=True),final=True);file.flush();os.fsync(file.fileno())
        except Exception as exc:
            with self.lock:self.state='error';self.error=type(exc).__name__+': capture stopped; inspect partial output'
            self.stop.set()
        finally:
            if file:
                try:file.close()
                except OSError:
                    with self.lock:self.state='error';self.error='Capture close failed; inspect partial output'
            with self.lock:
                if self.state!='error':self.state='closed'
                while not self.queue.empty():self.queue.get_nowait()
                self.queued=0
