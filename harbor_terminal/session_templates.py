"""Independent protocol templates; applying them never edits existing sessions."""
import json

from . import profiles
from .storage import DocumentStore


BASE_OPTIONS = dict(bytesize='8',parity='N',stopbits='1',flow_control='none',encoding='utf-8',
                    backspace='del',private_key='',jump_profile='',auth_method='auto',ssh_mode='shell')
BUILTIN = {
    'SSH':dict(port='22',username='',known_hosts='',encoding='utf-8',backspace='del',
               private_key='',auth_method='auto',ssh_mode='shell'),
    'Serial':dict(port='115200',bytesize='8',parity='N',stopbits='1',flow_control='none',
                  encoding='utf-8',backspace='del')}


def validate(templates):
    if not isinstance(templates,dict) or set(templates)!=set(BUILTIN): raise ValueError('Invalid template collection')
    for mode,settings in templates.items():
        if not isinstance(settings,dict) or set(settings)-set(BUILTIN[mode]): raise ValueError('Invalid protocol template fields')
        profiles.validate({'template':dict(BUILTIN[mode],**settings,mode=mode)})


def decode(raw):
    if raw is None: return {mode:{} for mode in BUILTIN}
    data=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=profiles.reject_duplicates)
    if not isinstance(data,dict) or set(data)!={'version','templates'} or type(data['version']) is not int or data['version']!=1:
        raise ValueError('Unsupported template file')
    validate(data['templates']);return data['templates']


def encode(templates):
    validate(templates)
    return json.dumps(dict(version=1,templates=templates),ensure_ascii=False,indent=2).encode('utf-8')


def store(profile_path):
    return DocumentStore(profile_path.with_name('defaults.json'),decode,encode,limit=65536)


def settings(templates,mode):
    if mode not in BUILTIN: raise ValueError('Invalid protocol')
    return dict(BUILTIN[mode],**templates.get(mode,{}))
