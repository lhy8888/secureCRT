import pyte
import pytest
from harbor_terminal.terminal_stream import SafeTerminalStream


@pytest.mark.parametrize('prefix,terminator', [
    ('\x1b]', '\x07'), ('\x1bP', '\x1b\\'), ('\x9d', '\x9c'),
    ('\x1b_', '\x1b\\'), ('\x1b^', '\x1b\\'), ('\x1bX', '\x1b\\')])
def test_unterminated_control_strings_never_accumulate(prefix, terminator):
    screen = pyte.Screen(100, 30)
    stream = SafeTerminalStream(screen)
    stream.feed(prefix)
    for _ in range(100):
        stream.feed('x' * 10000)
        assert len(stream.pending) <= 128
    for char in terminator:
        stream.feed(char)
    stream.feed('router#')
    assert screen.display[0].startswith('router#')
    assert screen.title == ''


def test_huge_csi_dropped_without_integer_conversion_or_memory_growth():
    screen = pyte.Screen(100, 30)
    stream = SafeTerminalStream(screen)
    stream.feed('\x1b[')
    for _ in range(100):
        stream.feed('9;' * 5000)
        assert len(stream.pending) <= 128
    stream.feed('mready')
    assert screen.display[0].startswith('ready')


def test_fragmented_normal_csi_and_utf8_text_still_render():
    screen = pyte.Screen(100, 30)
    stream = SafeTerminalStream(screen)
    for char in 'old\x1b[2J\x1b[H你好\x1b[31mred':
        stream.feed(char)
    assert screen.display[0].startswith('你好red')
    assert screen.buffer[0][4].fg == 'red'


def test_non_ascii_csi_digits_are_rejected():
    screen = pyte.Screen(100, 30)
    stream = SafeTerminalStream(screen)
    stream.feed('\x1b[²mstill-running')
    assert screen.display[0].startswith('still-running')
