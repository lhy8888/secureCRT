"""Validated OpenSSH trust documents. No scanning or automatic trust decisions."""
from dataclasses import dataclass
import base64
import hashlib

import asyncssh

from .storage import DocumentStore


@dataclass(frozen=True)
class HostEntry:
    line: int
    patterns: str
    marker: str
    algorithm: str
    fingerprint: str
    public: bytes


def entries(text):
    if not isinstance(text,str) or len(text.encode('utf-8'))>1048576:raise ValueError('Host key file exceeds 1 MiB')
    result=[]
    for number,line in enumerate(text.splitlines()):
        if not line.strip() or line.lstrip().startswith('#'):continue
        if len(line)>16384 or any(ord(c)<32 and c!='\t' for c in line):raise ValueError('Invalid host key line')
        fields=line.split();marker=''
        if fields[0].startswith('@'):
            marker=fields.pop(0)
            if marker not in ('@cert-authority','@revoked'):raise ValueError('Unsupported host key marker')
        if len(fields)<3:raise ValueError('Missing host patterns or public key')
        pattern,algorithm,encoded=fields[:3]
        if len(pattern)>4096 or any(c in pattern for c in '<>\\"\''):raise ValueError('Invalid host patterns')
        if pattern.startswith('|'):
            parts=pattern.split('|')
            try:
                if len(parts)!=4 or parts[:2]!=['','1'] or any(len(base64.b64decode(p,validate=True))!=20 for p in parts[2:]):raise ValueError()
            except (ValueError,TypeError):raise ValueError('Invalid hashed host pattern') from None
        elif any(not part or len(part)>512 for part in pattern.split(',')):raise ValueError('Invalid host pattern list')
        try:key=asyncssh.import_public_key(algorithm+' '+encoded)
        except (ValueError,asyncssh.KeyImportError):raise ValueError('Expected a public host key, not private key material') from None
        result.append(HostEntry(number,pattern,marker,key.get_algorithm(),key.get_fingerprint('sha256'),key.public_data))
        if len(result)>5000:raise ValueError('Too many host keys')
    # Validate actual OpenSSH matching syntax as well as the displayed keys.
    asyncssh.import_known_hosts(text)
    return result


def decode(raw):
    text='' if raw is None else raw.decode('utf-8-sig');entries(text);return text


def encode(text):entries(text);return text.encode('utf-8')


def store(path):return DocumentStore(path,decode,encode)


def make_entry(patterns,public_key,marker=''):
    if marker not in ('','@cert-authority','@revoked'):raise ValueError('Invalid trust marker')
    if any(c.isspace() for c in patterns):raise ValueError('Host patterns cannot contain whitespace')
    text=public_key.decode('utf-8') if isinstance(public_key,bytes) else public_key
    if not isinstance(text,str):raise ValueError('Expected public key text')
    header=text.strip().splitlines()[0] if text.strip() else ''
    if not (header.startswith(('ssh-','ecdsa-','sk-')) or header in (
            '-----BEGIN PUBLIC KEY-----','-----BEGIN RSA PUBLIC KEY-----','---- BEGIN SSH2 PUBLIC KEY ----')):
        raise ValueError('Private key input is not accepted')
    try:key=asyncssh.import_public_key(text)
    except (ValueError,asyncssh.KeyImportError):raise ValueError('Expected a public key') from None
    key.set_comment(None)
    line=(marker+' ' if marker else '')+patterns+' '+key.export_public_key().decode('ascii').strip()+'\n'
    if len(entries(line))!=1:raise ValueError('A single public key is required')
    return line


def append_entries(current,incoming):
    previous={(e.patterns,e.marker,e.public) for e in entries(current)};lines=incoming.splitlines();additions=[]
    for item in entries(incoming):
        identity=(item.patterns,item.marker,item.public)
        if identity not in previous:additions.append(lines[item.line]);previous.add(identity)
    result=current+('\n' if current and not current.endswith('\n') else '')
    return result+''.join(line+'\n' for line in additions)


def remove_entries(current,line_numbers):
    available={entry.line for entry in entries(current)}
    if not line_numbers or not set(line_numbers)<=available:raise ValueError('Selected key no longer exists')
    return ''.join(line for i,line in enumerate(current.splitlines(keepends=True)) if i not in line_numbers)


def match(text,host,port=22):
    if not host or any(c.isspace() for c in host) or not 1<=int(port)<=65535:raise ValueError('Invalid lookup endpoint')
    groups=asyncssh.match_known_hosts(text.encode('utf-8'),host,'',None if int(port)==22 else int(port))
    return dict(trusted=[key.get_fingerprint('sha256') for key in groups[0]],
                certificate_authorities=[key.get_fingerprint('sha256') for key in groups[1]],
                revoked=[key.get_fingerprint('sha256') for key in groups[2]])
