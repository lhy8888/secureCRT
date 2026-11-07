import pytest
from harbor_terminal.keyboard import encode_key, prepare_paste


@pytest.mark.parametrize('name,options,expected', [
    ('Up', {}, b'\x1b[A'), ('Up', {'application_cursor':True}, b'\x1bOA'),
    ('End', {'control':True}, b'\x1b[1;5F'),
    ('F1', {}, b'\x1bOP'), ('F5', {'shift':True}, b'\x1b[15;2~'),
    ('F12', {}, b'\x1b[24~'), ('Delete', {'alt':True}, b'\x1b[3;3~'),
    ('Backtab', {}, b'\x1b[Z'), ('C', {'control':True}, b'\x03'),
    ('Space', {'control':True}, b'\0'), ('Backspace', {'backspace':'bs'}, b'\x08'),
])
def test_xterm_key_modes_and_modifiers(name, options, expected):
    assert encode_key(name, **options) == expected


def test_altgr_printable_text_and_non_utf8():
    assert encode_key('Q','@',control=True,alt=True) == b'@'
    assert encode_key('A','a',alt=True) == b'\x1ba'
    assert encode_key('', '中文', encoding='gb18030') == '中文'.encode('gb18030')


def test_bracketed_paste_and_eol():
    assert prepare_paste('a\r\nb\nc') == b'a\rb\rc'
    assert prepare_paste('a\nb',bracketed=True) == b'\x1b[200~a\nb\x1b[201~'
    with pytest.raises(ValueError): prepare_paste('x'*65536,bracketed=True)


@pytest.mark.parametrize('text',['\x1b[201~rm anything','\x9b201~','\x00','\x7f'])
def test_clipboard_cannot_escape_bracketed_paste(text):
    with pytest.raises(ValueError): prepare_paste(text,bracketed=True)


def test_keypad_control_punctuation_and_newline_modes():
    assert encode_key('1',keypad=True,application_keypad=True)==b'\x1bOq'
    assert encode_key('Enter',keypad=True,application_keypad=True)==b'\x1bOM'
    assert encode_key('BracketLeft',control=True)==b'\x1b'
    assert encode_key('Return',newline_mode=True)==b'\r\n'
