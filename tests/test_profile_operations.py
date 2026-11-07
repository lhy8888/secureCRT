from copy import deepcopy
import pytest

from harbor_terminal import profiles
from harbor_terminal.profile_operations import (parse_import,export_sessions,plan_import,
    patch_sessions,rename_path,delete_sessions,default_mapping,csv_headers)


def test_csv_unicode_quoted_fields_ignore_secrets_and_merge_only_provided_values():
    text='Name,Host,Username,Password\r\n"实验室/交换机,甲",example.invalid,operator,fixture-sensitive\r\n'
    imported=parse_import(text,'csv')
    assert imported.ignored_columns==('Password',)
    assert 'fixture-sensitive' not in profiles.encode(imported.sessions).decode()
    name='实验室/交换机,甲';existing={name:dict(mode='SSH',host='old.invalid',port='2222',encoding='gb18030')}
    result=plan_import(existing,imported.sessions,'merge')
    assert result[name]['port']=='2222' and result[name]['encoding']=='gb18030'
    assert result[name]['host']=='example.invalid' and result[name]['username']=='operator'
    assert existing[name]['host']=='old.invalid'


def test_tsv_custom_mapping_and_serial_validation():
    text='Label\tDevice\tSpeed\tType\n控制台\tCOM8\t57600\tSerial\n'
    mapping=dict(Label='name',Device='host',Speed='port',Type='mode')
    result=parse_import(text,'tsv',mapping=mapping)
    assert result.sessions['控制台']==dict(host='COM8',port='57600',mode='Serial')
    with pytest.raises(ValueError):parse_import(text.replace('57600','0'),'tsv',mapping=mapping)


@pytest.mark.parametrize('kind',['xml','json'])
def test_native_export_roundtrip_preserves_unicode_paths_references_and_escaping(kind):
    data={'实验室/跳板<&>':dict(host='jump.invalid',username='user<&>'),
          '实验室/终端':dict(host='host.invalid',jump_profile='实验室/跳板<&>',port='2222')}
    raw=export_sessions(data,kind)
    assert parse_import(raw.decode(),kind).sessions==data
    assert export_sessions(data,kind)==raw


@pytest.mark.parametrize('text,kind',[
    ('Name,Host\na,one\na,two\n','csv'),('Name,Host\na,one,extra\n','csv'),
    ('Name,Host\na,\n','csv'),('Name,Host,Port\na,one,70000\n','csv'),
    ('Name,Host,Mode\na,one,Telnet\n','csv'),('Name,Name\na,b\n','csv'),
    ('<!DOCTYPE harbor-sessions [<!ENTITY x "expanded">]><harbor-sessions version="4"/>','xml'),
    ('<harbor-sessions version="4"><session name="a"><field name="password">fixture</field></session></harbor-sessions>','xml'),
    ('<harbor-sessions version="4"><session name="a"><field name="host"><nested/></field></session></harbor-sessions>','xml'),
    ('<VanDyke version="3.0"/>','xml'),
    ('{"version":4,"sessions":{"a":{"password":"fixture"}}}','json'),
    ('['*3000+']'*3000,'json'),
    ('<harbor-sessions version="4">'+'<x>'*3000+'</x>'*3000+'</harbor-sessions>','xml'),
    ('{"version":4,"sessions":{"a":{"host":"\\ud800"}}}','json')])
def test_malformed_unsupported_or_sensitive_import_rejected(text,kind):
    with pytest.raises(ValueError):parse_import(text,kind)


def test_duplicate_json_session_names_are_rejected_before_overwriting_rows():
    with pytest.raises(ValueError):parse_import('{"version":4,"sessions":{"a":{"host":"one"},"a":{"host":"two"}}}','json')


def test_conflict_policies_have_distinct_results_and_copies_rewrite_jump_references():
    existing={'jump':dict(host='old-jump.invalid',port='2200'),'target':dict(host='old-target.invalid')}
    incoming={'jump':dict(host='new-jump.invalid'),'target':dict(host='new-target.invalid',jump_profile='jump')}
    assert plan_import(existing,incoming,'add-only')==existing
    assert 'port' not in plan_import(existing,incoming,'replace')['jump']
    assert plan_import(existing,incoming,'merge')['jump']['port']=='2200'
    copied=plan_import(existing,incoming,'copy')
    assert copied['target (2)']['jump_profile']=='jump (2)' and copied['jump']==existing['jump']
    with pytest.raises(ValueError):plan_import({}, {'A':{},'a':{}}, 'copy')


def test_case_only_folder_rename_updates_dependents_and_rejects_collisions():
    original={'Folder/Jump':dict(host='jump.invalid'),'Folder/Target':dict(host='target.invalid',jump_profile='Folder/Jump')}
    renamed=rename_path(original,'Folder','folder')
    assert renamed['folder/Target']['jump_profile']=='folder/Jump'
    assert 'Folder/Target' in original
    with pytest.raises(ValueError):rename_path(dict(original,other={}), 'Folder/Jump','OTHER')
    with pytest.raises(ValueError):delete_sessions(original,('Folder/Jump',))
    assert delete_sessions(original,tuple(original))=={}


def test_batch_changes_are_atomic_and_unselected_fields_and_profiles_are_preserved():
    existing={'ssh':dict(mode='SSH',host='ssh.invalid',port='22',private_key='key-path'),
              'serial':dict(mode='Serial',host='COM3',port='115200',parity='E')}
    before=deepcopy(existing)
    with pytest.raises(ValueError):patch_sessions(existing,tuple(existing),dict(port='1'))
    assert existing==before
    updated=patch_sessions(existing,('ssh',),dict(username='operator',known_hosts=''))
    assert updated['ssh']['private_key']=='key-path' and updated['serial']==existing['serial']
    assert 'username' not in existing['ssh']


def test_header_mapper_never_maps_passwords_or_private_key_contents():
    mapping=default_mapping(csv_headers('Name,Hostname,Password,private_key_content\n'))
    assert mapping==dict(Name='name',Hostname='host',Password=None,private_key_content=None)
