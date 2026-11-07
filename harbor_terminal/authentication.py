"""Bounded keyboard-interactive authentication and thread-safe UI replies."""
import asyncio
import threading
import uuid

import asyncssh


AUTH_METHODS = {
    'auto': ('publickey', 'password', 'keyboard-interactive'),
    'interactive-first': ('keyboard-interactive', 'publickey', 'password'),
    'password-first': ('password', 'publickey', 'keyboard-interactive'),
    'publickey-only': ('publickey',),
    'interactive-only': ('keyboard-interactive',),
}


class AuthenticationCancelled(asyncssh.DisconnectError):
    def __init__(self): super().__init__(asyncssh.DISC_AUTH_CANCELLED_BY_USER, 'Authentication cancelled')


class AuthenticationTimeout(asyncssh.DisconnectError):
    def __init__(self): super().__init__(asyncssh.DISC_BY_APPLICATION, 'Authentication prompt timed out')


class AuthenticationLimit(asyncssh.DisconnectError):
    def __init__(self): super().__init__(asyncssh.DISC_BY_APPLICATION, 'Authentication challenge exceeds limits')


def validate_challenge(name, instructions, prompts):
    if not isinstance(name, str) or not isinstance(instructions, str): raise AuthenticationLimit()
    if len(name)>4096 or len(instructions)>8192 or not isinstance(prompts, (list, tuple)) or len(prompts)>16:
        raise AuthenticationLimit()
    size = len(name.encode('utf-8')) + len(instructions.encode('utf-8'))
    for item in prompts:
        if not isinstance(item, (list, tuple)) or len(item)!=2: raise AuthenticationLimit()
        text, echo = item
        if not isinstance(text, str) or len(text)>4096 or type(echo) is not bool: raise AuthenticationLimit()
        size += len(text.encode('utf-8'))
    if size>32768: raise AuthenticationLimit()


class InteractiveClient(asyncssh.SSHClient):
    def __init__(self, ask, context, started, status=None):
        self.ask, self.context, self.started, self.status = ask, context, started, status
        self.rounds = 0

    def kbdint_auth_requested(self): return ''

    async def kbdint_challenge_received(self, name, instructions, lang, prompts):
        self.rounds += 1
        if self.rounds>8: raise AuthenticationLimit()
        validate_challenge(name, instructions, prompts)
        if not prompts: return []
        self.started.set()
        suffix = 'Jump' if self.context['stage']=='jump' else 'Target'
        if self.status: self.status('Authenticating'+suffix)
        try:
            return await self.ask(dict(self.context, name=name, instructions=instructions,
                                      prompts=list(prompts), round=self.rounds))
        finally:
            if self.status: self.status('Connecting'+suffix)


class AuthenticationBroker:
    def __init__(self, emit, timeout=90):
        self.emit, self.timeout = emit, timeout
        self.lock = threading.Lock(); self.pending = None

    async def ask(self, event):
        validate_challenge(event['name'], event['instructions'], event['prompts'])
        identifier = uuid.uuid4().hex; loop = asyncio.get_running_loop(); future = loop.create_future()
        with self.lock:
            if self.pending is not None: raise AuthenticationLimit()
            pending = dict(id=identifier, loop=loop, future=future, count=len(event['prompts']), replied=False)
            self.pending = pending
        try:
            self.emit(dict(event, id=identifier, timeout=self.timeout))
            try: return await asyncio.wait_for(future, self.timeout)
            except TimeoutError: raise AuthenticationTimeout() from None
        finally:
            with self.lock:
                if self.pending is pending: self.pending = None

    def reply(self, identifier, answers):
        with self.lock:
            pending = self.pending
            if not pending or pending['id'] != identifier or pending['future'].done() or pending['replied']: return False
            if answers is not None:
                if (not isinstance(answers, list) or len(answers)!=pending['count']
                        or any(not isinstance(value, str) or len(value)>8192 for value in answers)
                        or sum(len(value.encode('utf-8')) for value in answers)>32768):
                    return False
                answers = list(answers)
            def deliver():
                if pending['future'].done(): return
                if answers is None: pending['future'].set_exception(AuthenticationCancelled())
                else: pending['future'].set_result(answers)
            pending['replied'] = True
            try: pending['loop'].call_soon_threadsafe(deliver)
            except RuntimeError: return False
            return True
