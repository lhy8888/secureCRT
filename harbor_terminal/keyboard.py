"""Xterm key encoding and paste validation without a widget dependency."""

ARROWS = dict(Up='A', Down='B', Right='C', Left='D', Home='H', End='F')
TILDE = dict(Insert=2, Delete=3, PageUp=5, PageDown=6,
             F5=15, F6=17, F7=18, F8=19, F9=20, F10=21, F11=23, F12=24)
FUNCTION = dict(F1='P', F2='Q', F3='R', F4='S')


def encode_key(name, text='', *, shift=False, control=False, alt=False,
               application_cursor=False, application_keypad=False, keypad=False,
               encoding='utf-8', backspace='del', newline_mode=False):
    modifier = 1 + int(shift) + 2 * int(alt) + 4 * int(control)
    if keypad and application_keypad:
        suffix = dict(zip('0123456789', 'pqrstuvwxy')) | dict(
            Period='n', Comma='l', Slash='o', Asterisk='j', Minus='m',
            Plus='k', Equal='X', Enter='M', Return='M')
        if name in suffix:
            return ('\x1bO' + suffix[name]).encode('ascii')
    if name in ARROWS or name in FUNCTION:
        suffix = (ARROWS | FUNCTION)[name]
        if modifier != 1:
            return f'\x1b[1;{modifier}{suffix}'.encode('ascii')
        prefix = '\x1bO' if name in FUNCTION or application_cursor else '\x1b['
        return (prefix + suffix).encode('ascii')
    if name in TILDE:
        part = f';{modifier}' if modifier != 1 else ''
        return f'\x1b[{TILDE[name]}{part}~'.encode('ascii')
    if name in ('Tab', 'Backtab'):
        return b'\x1b[Z' if shift or name == 'Backtab' else b'\t'
    if name in ('Return', 'Enter'):
        return b'\r\n' if newline_mode else b'\r'
    if name == 'Backspace':
        return b'\x08' if backspace == 'bs' else b'\x7f'
    if name == 'Escape':
        return b'\x1b'
    # AltGr often appears as Ctrl+Alt; preserve printable text from the IME/layout.
    if control and alt and text and text.isprintable():
        return text.encode(encoding)
    if control:
        char = dict(BracketLeft='[', BracketRight=']', Backslash='\\',
                    AsciiCircum='^', Underscore='_', At='@').get(name, name.upper())
        if len(char) == 1 and '@' <= char <= '_':
            return (b'\x1b' if alt else b'') + bytes([ord(char) & 31])
        if name == 'Space':
            return b'\0'
        return b''
    return (b'\x1b' if alt and text else b'') + text.encode(encoding)


def prepare_paste(text, *, encoding='utf-8', bracketed=False):
    if any((ord(c) < 32 and c not in '\r\n\t') or 127 <= ord(c) < 160 for c in text):
        raise ValueError('Clipboard contains terminal control characters')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if not bracketed:
        text = text.replace('\n', '\r')
    payload = text.encode(encoding)
    if bracketed:
        payload = b'\x1b[200~' + payload + b'\x1b[201~'
    if len(payload) > 65536:
        raise ValueError('Paste exceeds 64 KiB')
    return payload
