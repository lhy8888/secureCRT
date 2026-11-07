"""Explicit per-session SSH algorithms and bounded, non-secret negotiation data."""
from dataclasses import dataclass
import struct

import asyncssh
from asyncssh.kex import get_kex_algs
from asyncssh.encryption import get_encryption_algs
from asyncssh.mac import get_mac_algs


DEFAULT_POLICY = dict(ssh_kex='',ssh_ciphers='',ssh_macs='',ssh_hostkey_algs='',ssh_signature_algs='',
    ssh_compression='none',ssh_rekey_bytes='1073741824',ssh_rekey_seconds='3600',
    ssh_strict_kex='require',ssh_allow_legacy='false')
POLICY_FIELDS=frozenset(DEFAULT_POLICY)
MODERN = {
 'ssh_kex':('mlkem768x25519-sha256','curve25519-sha256','curve25519-sha256@libssh.org',
     'curve448-sha512','ecdh-sha2-nistp256','ecdh-sha2-nistp384','ecdh-sha2-nistp521',
     'diffie-hellman-group14-sha256','diffie-hellman-group16-sha512','diffie-hellman-group18-sha512'),
 'ssh_ciphers':('chacha20-poly1305@openssh.com','aes256-gcm@openssh.com','aes128-gcm@openssh.com',
     'aes256-ctr','aes192-ctr','aes128-ctr'),
 'ssh_macs':('hmac-sha2-256-etm@openssh.com','hmac-sha2-512-etm@openssh.com','hmac-sha2-256','hmac-sha2-512'),
 'ssh_hostkey_algs':('ssh-ed25519-cert-v01@openssh.com','ecdsa-sha2-nistp256-cert-v01@openssh.com',
     'ecdsa-sha2-nistp384-cert-v01@openssh.com','ecdsa-sha2-nistp521-cert-v01@openssh.com',
     'rsa-sha2-512-cert-v01@openssh.com','rsa-sha2-256-cert-v01@openssh.com',
     'ssh-ed25519','ecdsa-sha2-nistp256','ecdsa-sha2-nistp384','ecdsa-sha2-nistp521','rsa-sha2-512','rsa-sha2-256'),
 'ssh_signature_algs':('ssh-ed25519','ecdsa-sha2-nistp256','ecdsa-sha2-nistp384','ecdsa-sha2-nistp521','rsa-sha2-512','rsa-sha2-256')}
LEGACY = dict(ssh_kex=('diffie-hellman-group14-sha1',),ssh_ciphers=('aes256-cbc','aes128-cbc'),
    ssh_macs=('hmac-sha1',),ssh_hostkey_algs=('ssh-rsa',),ssh_signature_algs=('ssh-rsa',))


class SecurityPolicyError(asyncssh.DisconnectError):
    def __init__(self):super().__init__(asyncssh.DISC_BY_APPLICATION,'Required strict key exchange was not verified before authentication')


def catalog(field,legacy=False):
    values=MODERN[field]+(LEGACY[field] if legacy else ())
    supported={'ssh_kex':get_kex_algs,'ssh_ciphers':get_encryption_algs,'ssh_macs':get_mac_algs}.get(field)
    available={value.decode('ascii') for value in supported()} if supported else set(values)
    return tuple(value for value in values if value in available)


@dataclass(frozen=True)
class SSHPolicy:
    values: dict

    @classmethod
    def parse(cls,values=None):
        if values is None:values={}
        if not isinstance(values,dict) or set(values)-POLICY_FIELDS:raise ValueError('Unknown SSH policy fields')
        result=dict(DEFAULT_POLICY,**values)
        if any(not isinstance(v,str) or len(v)>4096 for v in result.values()):raise ValueError('Invalid SSH policy values')
        if result['ssh_allow_legacy'] not in ('true','false') or result['ssh_strict_kex'] not in ('require','prefer'):
            raise ValueError('Invalid SSH security switches')
        if result['ssh_compression'] not in ('none','delayed'):raise ValueError('Only authenticated compression is supported')
        for field in MODERN:
            if result[field]:
                selected=result[field].split(',')
                if (len(selected)>32 or len(selected)!=len(set(selected))
                        or any(value not in catalog(field,result['ssh_allow_legacy']=='true') for value in selected)):
                    raise ValueError('Unsupported or unapproved SSH algorithms')
        for field,minimum,maximum in (('ssh_rekey_bytes',1024,64*1024**3),('ssh_rekey_seconds',1,86400)):
            if not result[field].isascii() or not result[field].isdigit() or not minimum<=int(result[field])<=maximum:
                raise ValueError('Invalid rekey limit')
        return cls(result)

    def options(self):
        mapped=dict(ssh_kex='kex_algs',ssh_ciphers='encryption_algs',ssh_macs='mac_algs',
                    ssh_hostkey_algs='server_host_key_algs',ssh_signature_algs='signature_algs')
        # Legacy permission alone never adds legacy algorithms to a proposal.
        options={destination:(self.values[field].split(',') if self.values[field] else list(catalog(field)))
                 for field,destination in mapped.items()}
        options.update(compression_algs=['zlib@openssh.com','none'] if self.values['ssh_compression']=='delayed' else ['none'],
            rekey_bytes=int(self.values['ssh_rekey_bytes']),rekey_seconds=int(self.values['ssh_rekey_seconds']))
        return options


def _kex_lists(raw):
    """Version-pinned metadata adapter: KEXINIT contains public proposals only."""
    if not isinstance(raw,bytes) or not 21<=len(raw)<=65536 or raw[0]!=20:raise ValueError('Unavailable KEX metadata')
    offset=17;lists=[]
    for _ in range(2):
        size=struct.unpack_from('>I',raw,offset)[0];offset+=4
        if size>8192 or offset+size>len(raw):raise ValueError('Invalid KEX metadata')
        items=raw[offset:offset+size].decode('ascii').split(',');offset+=size
        if any(len(item)>256 for item in items):raise ValueError('Invalid algorithm name')
        lists.append(items)
    return lists


def negotiated(connection):
    result={key:connection.get_extra_info(key) for key in ('client_version','server_version','send_cipher','recv_cipher',
        'send_mac','recv_mac','send_compression','recv_compression')}
    result.update(strict_kex=None,kex=None,hostkey_signature=None,metadata_adapter=False)
    # AsyncSSH has no public Strict-KEX/KEX-name accessor. Fail closed when
    # requiring Strict KEX on an unvalidated library, rather than guessing.
    if asyncssh.__version__=='2.24.1':
        strict=getattr(connection,'_strict_kex',None)
        if type(strict) is bool:result['strict_kex']=strict
        try:
            client=_kex_lists(connection._client_kexinit);server=_kex_lists(connection._server_kexinit)
            for index,name in ((0,'kex'),(1,'hostkey_signature')):
                result[name]=next((value for value in client[index] if value in server[index]
                    and not value.startswith(('ext-info-','kex-strict-'))),None)
            result['metadata_adapter']=True
        except (ValueError,AttributeError,struct.error,UnicodeError):pass
    key=connection.get_server_host_key()
    if key is not None:result.update(host_public_key_format=key.get_algorithm(),host_fingerprint=key.get_fingerprint('sha256'))
    return {key:value[:1024] if isinstance(value,str) else value for key,value in result.items()}
