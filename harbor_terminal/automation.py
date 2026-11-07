"""Bounded literal receive cursors and declarative send/wait workflows."""
import asyncio
import codecs
from dataclasses import dataclass
import math
import threading
import time

from .keyboard import prepare_paste


class StreamOverflow(RuntimeError): pass
class CaptureLimit(RuntimeError): pass


class PlainReceiveFilter:
    """Strip control sequences incrementally; this is not a screen emulator."""
    def __init__(self): self.state='text'
    def feed(self, data):
        output=bytearray()
        for byte in data:
            if self.state=='text':
                if byte==27:self.state='escape'
                elif byte>=32 and byte!=127 or byte in (9,10,13):output.append(byte)
            elif self.state=='escape':
                if byte==ord('['):self.state='csi'
                elif byte in b']PX^_':self.state='string'
                elif byte in b'()*+-./#':self.state='one'
                elif byte!=27:self.state='text'
            elif self.state=='one':self.state='text'
            elif self.state=='csi':
                if 0x40<=byte<=0x7e:self.state='text'
                elif byte==27:self.state='escape'
            elif self.state=='string':
                if byte==7:self.state='text'
                elif byte==27:self.state='string-escape'
            elif self.state=='string-escape':
                self.state='text' if byte==ord('\\') else 'string'
        return bytes(output)


@dataclass
class ReceiveCursor:
    position: int


class ReceiveStream:
    def __init__(self, encoding='utf-8', capacity=131072):
        self.lock=threading.Lock(); self.capacity=capacity
        self.text=''; self.base=0; self.closed=False; self.waiters=set()
        self.decoder=codecs.getincrementaldecoder(encoding)(errors='replace')
        self.filter=PlainReceiveFilter()

    def configure(self, encoding):
        with self.lock:
            if self.text or self.base or self.waiters:raise RuntimeError('Configure receive encoding before connection')
            self.decoder=codecs.getincrementaldecoder(encoding)(errors='replace')

    @staticmethod
    def wake(waiters):
        for loop,future in waiters:
            def ready(target=future):
                if not target.done():target.set_result(None)
            try:loop.call_soon_threadsafe(ready)
            except RuntimeError:pass

    def append(self, data):
        with self.lock:
            if self.closed:return
            decoded=self.decoder.decode(self.filter.feed(data))
            self.text+=decoded
            if len(self.text)>self.capacity:
                removed=len(self.text)-self.capacity;self.text=self.text[removed:];self.base+=removed
            waiters=list(self.waiters)
        self.wake(waiters)

    def cursor(self):
        with self.lock:return ReceiveCursor(self.base+len(self.text))

    def close(self):
        with self.lock:self.closed=True;waiters=list(self.waiters)
        self.wake(waiters)

    async def read_until(self,cursor,patterns,timeout):
        deadline=time.monotonic()+timeout
        while True:
            loop=asyncio.get_running_loop();future=loop.create_future()
            with self.lock:
                if cursor.position<self.base:raise StreamOverflow('Receive cursor was overtaken')
                text=self.text[cursor.position-self.base:]
                matches=[(position,index) for index,pattern in enumerate(patterns)
                         if (position:=text.find(pattern))>=0]
                if matches:
                    position,index=min(matches)
                    cursor.position+=position+len(patterns[index])
                    return dict(text=text[:position],pattern=patterns[index],match_index=index+1)
                if self.closed:raise ConnectionError('Connection closed before prompt')
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Prompt deadline')
                entry=(loop,future);self.waiters.add(entry)
            try:await asyncio.wait_for(future,remaining)
            finally:
                with self.lock:self.waiters.discard(entry)


def validate_steps(steps):
    if not isinstance(steps,list) or not 1<=len(steps)<=64:raise ValueError('A flow needs 1–64 steps')
    result=[]
    for raw in steps:
        if not isinstance(raw,dict):raise ValueError('Invalid flow step')
        step=dict(raw);action=step.get('action')
        allowed=dict(send={'action','text','newline'},wait={'action','patterns','timeout'},delay={'action','seconds'})
        if not isinstance(action,str) or action not in allowed or set(step)-allowed[action]:raise ValueError('Unsupported flow action or fields')
        if action=='send':
            text=step.get('text')
            if not isinstance(text,str) or not text or len(text)>4096:raise ValueError('Send text needs 1–4096 characters')
            if type(step.get('newline',True)) is not bool:raise ValueError('Invalid newline option')
            prepare_paste(text)
            step['newline']=step.get('newline',True)
        elif action=='wait':
            patterns=step.get('patterns');timeout=step.get('timeout',10)
            if (not isinstance(patterns,list) or not 1<=len(patterns)<=16
                    or any(not isinstance(p,str) or not p or len(p)>1024 for p in patterns)):
                raise ValueError('Wait needs 1–16 nonempty literal patterns')
            if type(timeout) not in (int,float) or not math.isfinite(timeout) or not .05<=timeout<=120:
                raise ValueError('Wait timeout must be 0.05–120 seconds')
            step['patterns']=list(patterns);step['timeout']=timeout
        else:
            seconds=step.get('seconds')
            if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<=seconds<=30:
                raise ValueError('Delay must be 0–30 seconds')
        result.append(step)
    return result


async def run_flow(stream,cursor,steps,send,*,encoding='utf-8',progress=lambda value:None):
    steps=validate_steps(steps);captures=[];captured=0;sent=0
    async with asyncio.timeout(600):
        for index,step in enumerate(steps):
            progress(dict(step=index+1,total=len(steps),action=step['action'],sends_queued=sent))
            if step['action']=='send':
                text=step['text']
                if step['newline'] and not text.endswith(('\r','\n')):text+='\n'
                data=prepare_paste(text,encoding=encoding)
                if not send(data):raise BufferError('Send queue unavailable; no replay')
                sent+=1
            elif step['action']=='wait':
                match=await stream.read_until(cursor,step['patterns'],step['timeout'])
                captured+=len(match['text'].encode('utf-8'))
                if captured>65536:raise CaptureLimit('Captured output exceeded 64 KiB')
                captures.append(dict(step=index+1,**match))
            else:await asyncio.sleep(step['seconds'])
    return dict(steps=len(steps),sends_queued=sent,captures=captures)
