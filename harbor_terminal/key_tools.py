"""Encrypted identity generation with no-clobber publication of key pairs."""
import os
from pathlib import Path
import tempfile
import base64
import struct

import asyncssh


ALGORITHMS={'Ed25519':('ssh-ed25519',{}),'RSA 3072':('ssh-rsa',{'key_size':3072}),
    'RSA 4096':('ssh-rsa',{'key_size':4096}),'ECDSA P-256':('ecdsa-sha2-nistp256',{}),
    'ECDSA P-384':('ecdsa-sha2-nistp384',{})}


class GenerationCancelled(Exception):pass


def identity_bytes(path):
    """Bound explicit key input before entering a potentially expensive KDF."""
    with Path(path).open('rb') as stream:raw=stream.read(1048577)
    if len(raw)>1048576:raise ValueError('Key file exceeds 1 MiB')
    if raw.lstrip().startswith(b'-----BEGIN OPENSSH PRIVATE KEY-----'):
        try:
            data=base64.b64decode(b''.join(raw.strip().splitlines()[1:-1]),validate=True)
            magic=b'openssh-key-v1\0'
            if not data.startswith(magic):raise ValueError()
            position=len(magic)
            def string(limit):
                nonlocal position
                length=struct.unpack_from('>I',data,position)[0];position+=4
                if length>limit or position+length>len(data):raise ValueError()
                value=data[position:position+length];position+=length;return value
            cipher=string(128);kdf=string(128);options=string(1024)
            if kdf==b'bcrypt':
                salt_size=struct.unpack_from('>I',options,0)[0]
                if not 16<=salt_size<=64 or len(options)!=salt_size+8:raise ValueError()
                rounds=struct.unpack_from('>I',options,4+salt_size)[0]
                if not 1<=rounds<=1024:raise ValueError()
            elif kdf!=b'none' or cipher!=b'none':raise ValueError()
        except (ValueError,struct.error):raise ValueError('Malformed or excessive OpenSSH KDF parameters') from None
    return raw


def public_info(path,passphrase=None):
    path=Path(path)
    raw=identity_bytes(path)
    key=asyncssh.import_private_key(raw,passphrase)
    return dict(algorithm=key.get_algorithm(),fingerprint=key.get_fingerprint('sha256'),
                public_key=key.export_public_key().decode('utf-8'))


def generate_identity(path,algorithm,passphrase,*,unencrypted=False,cancel=None):
    if algorithm not in ALGORITHMS:raise ValueError('Unsupported key algorithm')
    if not isinstance(passphrase,str) or len(passphrase)>8192:raise ValueError('Invalid passphrase')
    if passphrase and len(passphrase)<12:raise ValueError('New encrypted identities require at least 12 passphrase characters')
    if not passphrase and not unencrypted:raise ValueError('Explicit unencrypted export selection is required')
    destination=Path(path);public=Path(str(destination)+'.pub')
    if destination.exists() or public.exists():raise FileExistsError('Choose a new key file name')
    if not destination.parent.is_dir():raise ValueError('Choose an existing destination directory')
    name,arguments=ALGORITHMS[algorithm];key=asyncssh.generate_private_key(name,**arguments)
    if cancel and cancel.is_set():raise GenerationCancelled()
    private_bytes=key.export_private_key(passphrase=passphrase or None,cipher_name='aes256-ctr',rounds=128)
    temporary=[];published=[]
    try:
        for target,data in ((destination,private_bytes),(public,key.export_public_key())):
            if cancel and cancel.is_set():raise GenerationCancelled()
            descriptor,name=tempfile.mkstemp(prefix='.harbor-key-',dir=target.parent);source=Path(name);temporary.append(source)
            with os.fdopen(descriptor,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
            # An atomic no-replace link is required. Do not fall back to
            # overwriting, or claim cross-file atomicity on unsupported FS.
            os.link(source,target);published.append((source,target))
        if os.name!='nt':
            descriptor=os.open(destination.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
        return dict(algorithm=key.get_algorithm(),fingerprint=key.get_fingerprint('sha256'),
                    private_path=str(destination),public_path=str(public))
    except BaseException:
        for source,target in published:
            try:
                if os.path.samefile(source,target):target.unlink()
            except OSError:pass
        raise
    finally:
        for source in temporary:
            try:source.unlink()
            except FileNotFoundError:pass
