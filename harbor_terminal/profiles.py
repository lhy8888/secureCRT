"""Versioned atomic session storage. Credentials are never accepted or persisted."""
import json
import os
from pathlib import Path
import tempfile

from .serial_config import SerialSettings
from .terminal_model import ENCODINGS

V1_FIELDS = frozenset(('mode', 'host', 'port', 'username', 'known_hosts'))
V2_FIELDS = V1_FIELDS | {'bytesize', 'parity', 'stopbits', 'flow_control',
                      'encoding', 'backspace', 'private_key'}
FIELDS = V2_FIELDS | {'jump_profile'}


def validate(sessions, *, version=3):
    if not isinstance(sessions, dict) or len(sessions) > 500:
        raise ValueError('Invalid session collection')
    allowed = V1_FIELDS if version == 1 else V2_FIELDS if version == 2 else FIELDS
    for name, profile in sessions.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 256:
            raise ValueError('Invalid session name')
        if len(name.split('/')) > 16 or any(not part.strip() for part in name.split('/')):
            raise ValueError('Invalid session folder path')
        if not isinstance(profile, dict) or set(profile) - allowed:
            raise ValueError('Credentials and unrecognized fields cannot be saved')
        if any(not isinstance(v, str) or len(v) > 4096 or '\0' in v for v in profile.values()):
            raise ValueError('Invalid session values')
        mode = profile.get('mode', 'SSH')
        if mode not in ('SSH', 'Serial'):
            raise ValueError('Invalid protocol')
        if profile.get('encoding', 'utf-8') not in ENCODINGS:
            raise ValueError('Invalid encoding')
        if profile.get('backspace', 'del') not in ('bs', 'del'):
            raise ValueError('Invalid backspace setting')
        if len(profile.get('jump_profile', '')) > 256:
            raise ValueError('Invalid jump profile reference')
        if mode == 'Serial':
            SerialSettings(int(profile.get('port', '115200')),
                           int(profile.get('bytesize', '8')), profile.get('parity', 'N'),
                           float(profile.get('stopbits', '1')), profile.get('flow_control', 'none'))
        elif 'port' in profile and not 1 <= int(profile['port']) <= 65535:
            raise ValueError('Invalid SSH port')


def load(path):
    path = Path(path)
    if not path.exists():
        return {}
    if path.stat().st_size > 1048576:
        raise ValueError('Session file exceeds 1 MiB')
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or type(data.get('version')) is not int
            or data['version'] not in (1, 2, 3) or not isinstance(data.get('sessions'), dict)):
        raise ValueError('Unsupported session file')
    result = data['sessions']
    validate(result, version=data['version'])
    return result


def save(path, sessions):
    # Validate exactly the bytes we will persist before touching an existing file.
    validate(sessions)
    payload = json.dumps({'version': 3, 'sessions': sessions}, ensure_ascii=False, indent=2)
    if len(payload.encode('utf-8')) > 1048576:
        raise ValueError('Session file exceeds 1 MiB')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.sessions-', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
