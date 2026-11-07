"""Parse SSH destinations without shell expansion or URL passwords."""
from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit, unquote


@dataclass(frozen=True)
class Endpoint:
    host: str
    username: str
    port: int = 22


def parse_destination(value, *, username='', port=22):
    if not isinstance(value,str) or not value or len(value)>2048 or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('Invalid SSH destination')
    if type(port) is not int or not 1<=port<=65535:raise ValueError('Invalid SSH port')
    host=value
    if '://' in value:
        parsed=urlsplit(value)
        if parsed.scheme!='ssh' or parsed.password is not None or parsed.path not in ('','/') or parsed.query or parsed.fragment:
            raise ValueError('Only SSH destinations without URL passwords are accepted')
        host=unquote(parsed.hostname or '')
        if parsed.username=='':raise ValueError('An explicit SSH username cannot be empty')
        username=unquote(parsed.username) if parsed.username is not None else username
        port=parsed.port if parsed.port is not None else port
    else:
        if '@' in host:
            username,host=host.rsplit('@',1)
            if not username:raise ValueError('An explicit SSH username cannot be empty')
        if host.startswith('['):
            end=host.find(']')
            if end<0:raise ValueError('Invalid bracketed address')
            suffix=host[end+1:];host=host[1:end]
            if suffix:
                if not suffix.startswith(':') or not suffix[1:].isdigit():raise ValueError('Invalid destination port')
                port=int(suffix[1:])
        elif host.count(':')==1:
            host,number=host.rsplit(':',1)
            if not number.isascii() or not number.isdigit():raise ValueError('Invalid destination port')
            port=int(number)
    if not host or not 1<=port<=65535:raise ValueError('Invalid SSH host or port')
    try:
        ipaddress.ip_address(host)
        if '%' in host and not re.fullmatch(r'[A-Za-z0-9_.-]+',host.rsplit('%',1)[1]):raise ValueError('Invalid IPv6 zone')
    except ValueError:
        if ':' in host:raise ValueError('IPv6 addresses with ports need brackets') from None
        host=host.encode('idna').decode('ascii').lower()
        if len(host)>253 or not re.fullmatch(r'[A-Za-z0-9_.-]+',host):raise ValueError('Invalid host name')
        if any(not label or len(label)>63 or label.startswith('-') or label.endswith('-') for label in host.rstrip('.').split('.')):
            raise ValueError('Invalid DNS labels')
    if (not isinstance(username,str) or len(username)>256 or ':' in username
            or any(ord(c)<33 or ord(c)==127 or c in '\u202a\u202b\u202d\u202e\u2066\u2067\u2068\u2069' for c in username)):
        raise ValueError('Invalid SSH username; passwords are not accepted in destinations')
    return Endpoint(host,username,port)
