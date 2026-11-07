"""Versioned atomic session storage. Credentials are never accepted or persisted."""
import json

from .serial_config import SerialSettings
from .terminal_model import ENCODINGS
from .storage import DocumentStore, ANY_REVISION

V1_FIELDS = frozenset(('mode', 'host', 'port', 'username', 'known_hosts'))
V2_FIELDS = V1_FIELDS | {'bytesize', 'parity', 'stopbits', 'flow_control',
                      'encoding', 'backspace', 'private_key'}
V3_FIELDS = V2_FIELDS | {'jump_profile'}
FIELDS = V3_FIELDS | {'auth_method','ssh_mode'}


def validate(sessions, *, version=4):
    if version not in (1,2,3,4): raise ValueError('Unsupported session version')
    if not isinstance(sessions, dict) or len(sessions) > 500:
        raise ValueError('Invalid session collection')
    allowed = V1_FIELDS if version == 1 else V2_FIELDS if version == 2 else V3_FIELDS if version == 3 else FIELDS
    for name, profile in sessions.items():
        if (not isinstance(name, str) or not name.strip() or len(name) > 256
                or any(ord(c)<32 or ord(c)==127 for c in name)):
            raise ValueError('Invalid session name')
        try:name.encode('utf-8')
        except UnicodeError:raise ValueError('Invalid Unicode session name') from None
        if len(name.split('/')) > 16 or any(not part.strip() for part in name.split('/')):
            raise ValueError('Invalid session folder path')
        if not isinstance(profile, dict) or set(profile) - allowed:
            raise ValueError('Credentials and unrecognized fields cannot be saved')
        if any(not isinstance(v, str) or len(v) > 4096 or '\0' in v for v in profile.values()):
            raise ValueError('Invalid session values')
        try:
            for value in profile.values():value.encode('utf-8')
        except UnicodeError:raise ValueError('Invalid Unicode session values') from None
        mode = profile.get('mode', 'SSH')
        if mode not in ('SSH', 'Serial'):
            raise ValueError('Invalid protocol')
        if profile.get('encoding', 'utf-8') not in ENCODINGS:
            raise ValueError('Invalid encoding')
        if profile.get('backspace', 'del') not in ('bs', 'del'):
            raise ValueError('Invalid backspace setting')
        if len(profile.get('jump_profile', '')) > 256:
            raise ValueError('Invalid jump profile reference')
        if profile.get('auth_method','auto') not in ('auto','password-first','interactive-first','publickey-only','interactive-only'):
            raise ValueError('Invalid authentication method')
        if profile.get('ssh_mode','shell') not in ('shell','channels'):raise ValueError('Invalid SSH shell mode')
        if mode == 'Serial':
            SerialSettings(int(profile.get('port', '115200')),
                           int(profile.get('bytesize', '8')), profile.get('parity', 'N'),
                           float(profile.get('stopbits', '1')), profile.get('flow_control', 'none'))
        elif 'port' in profile and not 1 <= int(profile['port']) <= 65535:
            raise ValueError('Invalid SSH port')


def reject_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate configuration key')
        result[key]=value
    return result


def decode(raw):
    if raw is None: return {}
    try:data = json.loads(raw.decode('utf-8-sig'),object_pairs_hook=reject_duplicates)
    except RecursionError:raise ValueError('Session document nesting exceeds parser limits') from None
    if (not isinstance(data, dict) or type(data.get('version')) is not int
            or data['version'] not in (1, 2, 3, 4) or not isinstance(data.get('sessions'), dict)
            or set(data)-{'version','sessions'}):
        raise ValueError('Unsupported session file')
    result = data['sessions']
    validate(result, version=data['version'])
    return result


def encode(sessions):
    validate(sessions)
    payload = json.dumps({'version': 4, 'sessions': sessions}, ensure_ascii=False, indent=2)
    if len(payload.encode('utf-8')) > 1048576:
        raise ValueError('Session file exceeds 1 MiB')
    return payload.encode('utf-8')


def store(path):
    return DocumentStore(path, decode, encode)


def load(path):
    return store(path).read().value


def save(path, sessions, *, expected_revision=ANY_REVISION):
    return store(path).save(sessions, expected_revision=expected_revision)
