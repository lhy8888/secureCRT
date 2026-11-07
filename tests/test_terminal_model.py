from harbor_terminal.terminal_model import TerminalModel, MAX_COLUMNS, MAX_ROWS


def test_alternate_screen_does_not_pollute_main_or_grow_cursor_stack():
    model = TerminalModel(columns=40,lines=5)
    model.feed(b'router# ')
    model.feed(b'\x1b[?1049h\x1b[2J\x1b[Hfull-screen TUI')
    assert model.screen.is_alternate
    assert model.text().startswith('full-screen TUI')
    model.feed(b'\x1b[?1049h'*100)
    assert len(model.screen.main.savepoints)==1
    model.feed(b'\x1b[?1049l')
    assert model.text().startswith('router#')
    assert model.screen.buffer[0][7].data == ' '
    assert 'full-screen' not in model.text()
    assert model.screen.cursor.x==8
    assert not model.screen.is_alternate


def test_truecolor_256_color_and_character_attributes():
    model = TerminalModel()
    model.feed(b'\x1b[1;3;4;9;38;2;18;52;86;48;5;196mX\x1b[0mY')
    cell=model.screen.buffer[0][0]
    assert cell.fg=='123456' and cell.bg=='ff0000'
    assert cell.bold and cell.italics and cell.underscore and cell.strikethrough
    assert model.screen.buffer[0][1].fg=='default'


def test_unicode_fragments_wide_stubs_and_combining_marks():
    model = TerminalModel()
    text='你好e\u0301'.encode()
    for byte in text: model.feed(bytes([byte]))
    assert model.screen.buffer[0][0].data=='你'
    assert model.screen.buffer[0][1].data==''
    assert model.screen.cursor.x==5
    assert model.text().startswith('你好é')


def test_resize_updates_both_grids_and_bounds_cursor():
    model=TerminalModel(columns=100,lines=30)
    model.feed(b'\x1b[30;100H\x1b[?1049h')
    model.resize(48,12)
    model.feed(b'\x1b[?1049l')
    assert (model.screen.main.columns,model.screen.alternate.columns)==(48,48)
    assert (model.screen.lines,model.screen.columns)==(12,48)
    assert model.screen.cursor.x<48 and model.screen.cursor.y<12
    model.resize(1_000_000,1_000_000)
    assert model.screen.columns==MAX_COLUMNS and model.screen.lines==MAX_ROWS


def test_cursor_report_is_returned_to_transport_and_rep_is_bounded():
    responses=[]
    model=TerminalModel(columns=20,lines=5,response=responses.append)
    model.feed(b'abc\x1b[6n')
    assert responses==[b'\x1b[1;4R']
    model.feed(b'\x1b[2b')
    assert model.text().startswith('abccc')
    model.feed(b'\x1b[9999b')
    assert len(model.text())<200


def test_history_and_saved_cursor_memory_are_bounded():
    model=TerminalModel(columns=20,lines=3)
    for i in range(2200): model.feed(f'line-{i}\r\n'.encode())
    assert len(model.screen.history.top)==2000
    assert 'line-2199' in model.text()
    model.feed(b'\x1b7'*1000)
    assert len(model.screen.savepoints)==16


def test_application_keypad_mode_switches_from_escape_sequences():
    model=TerminalModel()
    model.feed(b'\x1b=')
    assert 66 in model.screen.input_modes
    model.feed(b'\x1b>')
    assert 66 not in model.screen.input_modes


def test_shrinking_height_preserves_visible_prompt_and_retains_scrolled_rows():
    model=TerminalModel(columns=40,lines=30)
    for i in range(10):model.feed(f'line-{i}\r\n'.encode())
    model.resize(40,20)
    assert model.text().startswith('line-0\nline-1')
    assert model.screen.cursor.y==10
    assert not model.screen.history.top
    smaller=TerminalModel(columns=20,lines=5)
    smaller.feed(b'0\r\n1\r\n2\r\n3\r\n4')
    smaller.resize(20,3)
    assert smaller.text()=='0\n1\n2\n3\n4'
    assert len(smaller.screen.history.top)==2
    assert smaller.screen.cursor.y==2


def test_combining_cell_length_is_bounded_even_after_cursor_moves():
    model=TerminalModel()
    model.feed(b'x')
    for _ in range(100):
        model.feed('\u0301'.encode()*100)
        model.feed(b'\x1b[2;1Hy\x1b[1;2H')
    assert len(model.screen.buffer[0][0].data)<=32


def test_repeated_expensive_control_sequences_have_a_per_feed_budget():
    import pytest
    model=TerminalModel(columns=100,lines=30)
    with pytest.raises(ValueError,match='budget'):
        model.feed(b'\x1b[2J'*1000)
