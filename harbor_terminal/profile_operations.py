"""Pure, reviewable session import/edit plans; no connections or credential data."""
from copy import deepcopy
import csv
from dataclasses import dataclass
import io
import json
import xml.etree.ElementTree as ET

from . import profiles


IMPORT_LIMIT = 2*1024*1024
STRATEGIES = ('add-only', 'replace', 'merge', 'copy')
ALIASES = {'session':'name', 'session name':'name', 'sessionname':'name', '名称':'name',
           '会话名称':'name','hostname':'host','address':'host','ip':'host','主机':'host',
           'protocol':'mode','协议':'mode','user':'username','用户名':'username',
           'baudrate':'port','端口':'port'}


@dataclass
class ImportResult:
    sessions: dict
    ignored_columns: tuple = ()


def csv_headers(text, delimiter=','):
    if delimiter not in (',','\t'): raise ValueError('Unsupported delimiter')
    if len(text.encode('utf-8'))>IMPORT_LIMIT: raise ValueError('Import exceeds 2 MiB')
    reader=csv.reader(io.StringIO(text.lstrip('\ufeff'), newline=''),delimiter=delimiter,strict=True)
    try:header=next(reader,None)
    except csv.Error:raise ValueError('Malformed delimited header') from None
    if (not header or len(header)>40 or any(not key or len(key)>128 or any(ord(c)<32 for c in key) for key in header)
            or len(set(header))!=len(header)): raise ValueError('Invalid or duplicate column names')
    return header


def default_mapping(header):
    allowed=profiles.FIELDS|{'name'}
    return {key:(normalized if normalized in allowed else None)
            for key in header for normalized in [ALIASES.get(key.strip().casefold(),key.strip().casefold())]}


def parse_import(text, kind, *, mapping=None):
    if not isinstance(text,str) or len(text.encode('utf-8'))>IMPORT_LIMIT: raise ValueError('Import exceeds 2 MiB')
    if kind=='json': return ImportResult(profiles.decode(text.encode('utf-8')))
    if kind in ('csv','tsv'):
        delimiter=',' if kind=='csv' else '\t';header=csv_headers(text,delimiter)
        mapping=default_mapping(header) if mapping is None else dict(mapping)
        if set(mapping)!=set(header): raise ValueError('Map each source column or explicitly ignore it')
        mapped=[field for field in mapping.values() if field is not None]
        if (set(mapped)-(profiles.FIELDS|{'name'}) or len(mapped)!=len(set(mapped))
                or 'name' not in mapped or 'host' not in mapped): raise ValueError('Name and host require unique column mappings')
        sessions={};reader=csv.reader(io.StringIO(text.lstrip('\ufeff'),newline=''),delimiter=delimiter,strict=True)
        next(reader)
        try:
            for cells in reader:
                if not cells: continue
                if len(cells)!=len(header) or any(len(cell)>4096 for cell in cells): raise ValueError('Invalid CSV row')
                record={mapping[column]:cell.strip() for column,cell in zip(header,cells) if mapping[column] is not None}
                name=record.pop('name')
                if 'mode' in record:
                    mode=record['mode'].casefold()
                    if mode not in ('ssh','ssh2','serial','串口'): raise ValueError('Only SSH and serial profiles are supported')
                    record['mode']='Serial' if mode in ('serial','串口') else 'SSH'
                if name in sessions: raise ValueError('Duplicate imported session name')
                if not record.get('host'): raise ValueError('Imported destination is empty')
                sessions[name]=record
                if len(sessions)>500: raise ValueError('At most 500 sessions')
        except csv.Error: raise ValueError('Malformed delimited input') from None
        profiles.validate(sessions)
        return ImportResult(sessions,tuple(column for column in header if mapping[column] is None))
    if kind!='xml': raise ValueError('Unsupported import format')
    # Native Harbor XML only. Do not guess proprietary configuration meanings.
    upper=text.upper()
    if '<!DOCTYPE' in upper or '<!ENTITY' in upper: raise ValueError('DTD/entities are not accepted')
    try:
        parser=ET.XMLPullParser(events=('start','end'));root=None;depth=nodes=0
        for offset in range(0,len(text),8192):
            parser.feed(text[offset:offset+8192])
            for event,element in parser.read_events():
                if event=='start':
                    if root is None:root=element
                    depth+=1;nodes+=1
                    if depth>3 or nodes>1+500*(1+len(profiles.FIELDS)):raise ValueError('XML structure exceeds session limits')
                else:depth-=1
        parser.close()
    except ET.ParseError: raise ValueError('Malformed XML') from None
    if root is None or root.tag!='harbor-sessions' or root.attrib not in ({'version':'4'},{'version':'5'},{'version':'6'}) or (root.text or '').strip():
        raise ValueError('Expected Harbor session XML version 4, 5 or 6')
    sessions={}
    for item in root:
        if item.tag!='session' or set(item.attrib)!={'name'} or (item.text or '').strip(): raise ValueError('Invalid XML session')
        name=item.attrib['name'];record={}
        if name in sessions: raise ValueError('Duplicate session name')
        for field in item:
            if (field.tag!='field' or set(field.attrib)!={'name'} or len(field) or (field.tail or '').strip()
                    or field.attrib['name'] not in profiles.FIELDS or field.attrib['name'] in record):
                raise ValueError('Invalid or sensitive XML field')
            record[field.attrib['name']]=field.text or ''
        if (item.tail or '').strip(): raise ValueError('Unexpected XML text')
        sessions[name]=record
        if len(sessions)>500: raise ValueError('At most 500 sessions')
    profiles.validate(sessions,version=int(root.attrib['version']))
    return ImportResult(sessions)


def export_sessions(sessions, kind):
    profiles.validate(sessions)
    if kind=='json': return profiles.encode(sessions)
    if kind!='xml': raise ValueError('Use lossless native JSON or XML export')
    for name,profile in sessions.items():
        if any(any(ord(c)<32 and c not in '\t\r\n' for c in value) for value in [name,*profile.values()]):
            raise ValueError('XML cannot represent control characters in this configuration')
    root=ET.Element('harbor-sessions',version='6')
    for name,profile in sorted(sessions.items()):
        item=ET.SubElement(root,'session',name=name)
        for key,value in sorted(profile.items()): ET.SubElement(item,'field',name=key).text=value
    ET.indent(root)
    raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    if len(raw)>IMPORT_LIMIT: raise ValueError('Export exceeds 2 MiB')
    return raw


def plan_import(existing,incoming,strategy):
    if strategy not in STRATEGIES: raise ValueError('Unknown conflict policy')
    profiles.validate(existing);profiles.validate(incoming)
    if len({name.casefold() for name in incoming})!=len(incoming):raise ValueError('Imported case variants are ambiguous')
    result=deepcopy(existing);folded={}
    for name in existing: folded.setdefault(name.casefold(),[]).append(name)
    resolved={};used={name.casefold() for name in existing};skip=set()
    for name in incoming:
        collisions=folded.get(name.casefold(),[])
        if len(collisions)>1: raise ValueError('Existing case variants make this import ambiguous')
        if collisions and strategy=='add-only': resolved[name]=collisions[0];skip.add(name);continue
        if collisions and strategy!='copy': target=collisions[0]
        else:
            target=name;index=2
            while target.casefold() in used:
                suffix=f' ({index})';target=name[:256-len(suffix)]+suffix;index+=1
        used.add(target.casefold());resolved[name]=target
    for name,profile in incoming.items():
        if name in skip: continue
        target=resolved[name];updated=deepcopy(profile)
        reference=updated.get('jump_profile')
        if reference in resolved: updated['jump_profile']=resolved[reference]
        if strategy=='merge': result[target]=dict(result.get(target,{}),**updated)
        else: result[target]=updated
    profiles.validate(result)
    return result


def patch_sessions(existing,names,changes):
    if not changes or not isinstance(changes,dict) or set(changes)-profiles.FIELDS: raise ValueError('Select explicit non-secret changes')
    if not names or any(name not in existing for name in names): raise ValueError('Selected session no longer exists')
    result=deepcopy(existing)
    for name in names: result[name].update(changes)
    profiles.validate(result)
    return result


def rename_path(existing,old,new):
    if old==new: return deepcopy(existing)
    if not old or not new: raise ValueError('Empty session path')
    mapping={name:new+name[len(old):] for name in existing if name==old or name.startswith(old+'/')}
    if not mapping: raise ValueError('No sessions under this path')
    other={name.casefold() for name in existing if name not in mapping}
    if len(set(n.casefold() for n in mapping.values()))!=len(mapping) or any(n.casefold() in other for n in mapping.values()):
        raise ValueError('Rename would overwrite another session')
    result={mapping.get(name,name):dict(profile) for name,profile in existing.items()}
    for profile in result.values():
        reference=profile.get('jump_profile')
        if reference in mapping: profile['jump_profile']=mapping[reference]
    profiles.validate(result)
    return result


def delete_sessions(existing,names):
    if not names or any(name not in existing for name in names): raise ValueError('Invalid deletion selection')
    result={name:dict(profile) for name,profile in existing.items() if name not in names}
    if any(profile.get('jump_profile') in names for profile in result.values()):
        raise ValueError('Other sessions still reference a selected jump; select dependents too')
    profiles.validate(result)
    return result


def describe_changes(before,after):
    rows=[]
    for name in sorted(before.keys()|after.keys()):
        if name not in before: rows.append((name,'新增',', '.join(sorted(after[name]))))
        elif name not in after: rows.append((name,'删除',''))
        else:
            keys=[key for key in before[name].keys()|after[name].keys() if before[name].get(key)!=after[name].get(key)]
            if keys: rows.append((name,'修改',', '.join(sorted(keys))))
    return rows
