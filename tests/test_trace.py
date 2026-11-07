import pytest
from harbor_terminal.trace import ByteTrace,parse_hex,format_record


def test_trace_is_opt_in_bounded_and_directional():
    trace=ByteTrace(max_bytes=2048,max_records=3)
    trace.append('RX',b'hidden')
    assert not trace.snapshot()['records']
    trace.configure(True)
    trace.append('TX',b'not-captured')
    assert not trace.snapshot()['records']
    trace.append('RX',bytes(range(256))*20)
    value=trace.snapshot()
    assert value['bytes']<=2048 and len(value['records'])<=3
    assert value['dropped']==3072
    assert value['records'][-1]['offset']==4096
    last=value['records'][-1]['id']
    assert not trace.snapshot(last)['records']
    trace.configure(True,True);trace.append('TX',b'\x00\xff')
    assert trace.snapshot(last)['records'][-1]['data']==b'\x00\xff'
    trace.configure(False)
    assert trace.snapshot()['bytes']==0


def test_hex_format_never_interprets_escape_codes_and_offsets_match_bytes():
    record=dict(id=1,time=0,direction='RX',offset=32,data=b'\x00\xff\x1b[Atext\r\n')
    text=format_record(record)
    assert 'RX 00000020' in text
    assert '00 FF 1B 5B 41' in text
    assert '\x1b' not in text
    assert '|...[Atext..|' in text
    assert parse_hex('00 ff 1b 0d 0a')==b'\x00\xff\x1b\r\n'


@pytest.mark.parametrize('value',['','0','0x01','GG','00;FF','00'*4097])
def test_hex_rejects_ambiguous_or_oversized_input(value):
    with pytest.raises(ValueError):parse_hex(value)
