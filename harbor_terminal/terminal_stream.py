"""Bound escape-state memory before sending untrusted terminal output to pyte.

OSC/DCS/APC/PM/SOS are deliberately unsupported and discarded, including clipboard,
window-title and graphics payloads. CSI parameters are limited to 128 characters.
State persists across network chunks, without storing discarded payloads.
"""
import pyte


class ExtendedStream(pyte.Stream):
    csi = dict(pyte.Stream.csi, b='repeat_character')
    escape = dict(pyte.Stream.escape, **{'=':'set_application_keypad', '>':'reset_application_keypad'})
    events = pyte.Stream.events | {'repeat_character', 'set_application_keypad', 'reset_application_keypad'}


class SafeTerminalStream:
    def __init__(self, screen):
        # Plain pyte screens are still supported by parser-security tests.
        self.stream = ExtendedStream(screen) if hasattr(screen, 'repeat_character') else pyte.Stream(screen)
        self.state = 'text'
        self.pending = ''

    def feed(self, text):
        output = []
        for char in text:
            if self.state == 'string':
                if char in ('\x07', '\x9c'):
                    self.state = 'text'
                elif char == '\x1b':
                    self.state = 'string_escape'
            elif self.state == 'string_escape':
                if char in ('\\', '\x07', '\x9c'):
                    self.state = 'text'
                elif char != '\x1b':
                    self.state = 'string'
            elif self.state == 'escape':
                if char == '[':
                    self.pending = '\x1b['
                    self.state = 'csi'
                elif char in ']PX^_':
                    self.pending = ''
                    self.state = 'string'
                elif char in '()#%':
                    self.pending = '\x1b' + char
                    self.state = 'intermediate'
                elif char == '\x1b':
                    self.pending = '\x1b'
                else:
                    output.append('\x1b' + char)
                    self.pending = ''
                    self.state = 'text'
            elif self.state in ('csi', 'discard_csi'):
                if char == '\x1b':
                    self.pending = '\x1b'
                    self.state = 'escape'
                elif char in ('\x18', '\x1a'):
                    self.pending = ''
                    self.state = 'text'
                elif '\x40' <= char <= '\x7e':
                    if self.state == 'csi':
                        output.append(self.pending + char)
                    self.pending = ''
                    self.state = 'text'
                elif self.state == 'csi':
                    if not '\x20' <= char <= '\x3f':
                        self.pending = ''
                        self.state = 'discard_csi'
                    elif len(self.pending) >= 128:
                        self.pending = ''
                        self.state = 'discard_csi'
                    else:
                        self.pending += char
            elif self.state == 'intermediate':
                output.append(self.pending + char)
                self.pending = ''
                self.state = 'text'
            elif char == '\x1b':
                self.state = 'escape'
                self.pending = '\x1b'
            elif char == '\x9b':
                self.state = 'csi'
                self.pending = '\x1b['
            elif char in ('\x90', '\x98', '\x9d', '\x9e', '\x9f'):
                self.state = 'string'
            else:
                output.append(char)
        if output:
            self.stream.feed(''.join(output))
