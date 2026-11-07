import pytest
from harbor_terminal.profiles import load, save


def test_profiles_round_trip(tmp_path):
    path = tmp_path / 'sessions.json'
    data = {'实验室': {'mode': 'SSH', 'host': 'example.invalid', 'port': '22'}}
    save(path, data)
    assert load(path) == data
    save(path, data)
    assert load(path) == data


def test_credentials_never_saved(tmp_path):
    path = tmp_path / 'sessions.json'
    save(path, {})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save(path, {'test': {'password': 'test-only-password'}})
    assert path.read_bytes() == before


def test_corrupt_file_not_silently_reset(tmp_path):
    path = tmp_path / 'sessions.json'
    path.write_text('{broken')
    with pytest.raises(ValueError):
        load(path)


@pytest.mark.parametrize('payload', ['[]', 'null', '1', '"text"'])
def test_wrong_root_type_rejected(tmp_path, payload):
    path = tmp_path / 'sessions.json'
    path.write_text(payload)
    with pytest.raises(ValueError):
        load(path)


def test_v1_is_readable_and_new_serial_settings_round_trip_as_v4(tmp_path):
    import json
    path=tmp_path/'sessions.json'
    old={'console':{'mode':'Serial','host':'COM3','port':'115200'}}
    path.write_text(json.dumps({'version':1,'sessions':old}))
    assert load(path)==old
    old['console'].update(bytesize='7',parity='E',stopbits='2',flow_control='rtscts',encoding='gb18030')
    save(path,old)
    assert load(path)==old
    assert json.loads(path.read_text())['version']==4


@pytest.mark.parametrize('field',['password','passphrase','private_key_content'])
def test_authentication_secrets_cannot_be_persisted_in_v2(tmp_path,field):
    with pytest.raises(ValueError):save(tmp_path/'sessions.json',{'test':{field:'test-only'}})


def test_v2_profiles_remain_readable_and_jump_reference_is_only_metadata(tmp_path):
    import json
    path=tmp_path/'sessions.json'
    sessions={'jump':{'mode':'SSH','host':'example.invalid','port':'22'},
              'target':{'mode':'SSH','host':'192.0.2.1','port':'22','encoding':'utf-8'}}
    path.write_text(json.dumps({'version':2,'sessions':sessions}))
    assert load(path)==sessions
    sessions['target']['jump_profile']='jump'
    save(path,sessions);assert load(path)==sessions
    for field in ('jump_password','jump_passphrase'):
        sessions['target'][field]='test-only'
        with pytest.raises(ValueError):save(path,sessions)
        del sessions['target'][field]
