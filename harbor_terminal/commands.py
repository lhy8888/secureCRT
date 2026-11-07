"""Explicitly saved command definitions, separate from authentication data."""
import json
from pathlib import Path

from .automation import validate_steps
from .keyboard import prepare_paste
from .reports import atomic_json


def validate_library(commands):
    if not isinstance(commands,dict) or len(commands)>200:raise ValueError('At most 200 saved commands')
    for name,item in commands.items():
        if not isinstance(name,str) or not name.strip() or len(name)>128 or any(ord(c)<32 or ord(c)==127 for c in name):
            raise ValueError('Invalid command name')
        if not isinstance(item,dict) or set(item)-{'text','pinned'}:raise ValueError('Unknown command fields')
        text=item.get('text')
        if not isinstance(text,str) or not text.strip() or len(text)>4096:raise ValueError('Invalid command text')
        if type(item.get('pinned',False)) is not bool:raise ValueError('Invalid pin option')
        prepare_paste(text)


def load_library(path):
    path=Path(path)
    if not path.exists():return {}
    if path.stat().st_size>1048576:raise ValueError('Command library exceeds 1 MiB')
    payload=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload,dict) or type(payload.get('version')) is not int or payload['version']!=1 or set(payload)-{'version','commands'}:
        raise ValueError('Invalid command library')
    validate_library(payload.get('commands'));return payload['commands']


def save_library(path,commands):
    validate_library(commands)
    payload=dict(version=1,commands=commands)
    if len(json.dumps(payload,ensure_ascii=False,indent=2).encode('utf-8'))+1>1048576:raise ValueError('Command library exceeds 1 MiB')
    atomic_json(path,payload)


def parse_flow(text):
    if len(text.encode('utf-8'))>262144:raise ValueError('Flow file exceeds 256 KiB')
    payload=json.loads(text)
    if not isinstance(payload,dict) or set(payload)-{'version','steps'} or type(payload.get('version')) is not int or payload['version']!=1:
        raise ValueError('Invalid flow definition')
    return validate_steps(payload['steps'])
