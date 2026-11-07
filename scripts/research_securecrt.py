"""Index the official release archive without assuming that HTTP 200 means success.

Raw third-party documents stay outside the project. Exported indexes contain source
locations, hashes and classifications, not copies of the release-note paragraphs.
Topic labels are mechanical navigation aids, not conclusions about root causes.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

BASE = 'https://www.vandyke.com'
DOCS = {
    'previous': '/download/prevreleases.html',
    'features': '/products/securecrt/features.html',
    'faq': '/products/securecrt/faq/index.html',
    'windows': '/products/securecrt/windows.html',
    'scripting': '/support/securecrt/scripting_faq.html',
    'python-examples': '/support/securecrt/python_examples.html',
    'tips': '/support/tips/index.php?pid=all',
    'new97': '/products/securecrt/new-in.html',
    'scripting-guide': '/support/tips/scripting/index.html',
}
TOPICS = {
    'authentication': r'authenticat|password|passphrase|keyboard.interactive|GSSAPI|Kerberos',
    'keys-certificates-agent': r'public.key|private.key|certificate|PKCS|smart.card|agent|PIV|CAC|FIDO',
    'host-trust': r'host.key|fingerprint|known.host|trusted|trust ',
    'crypto-negotiation': r'cipher|key.exchange|encrypt|decrypt|algorithm|MACs?\b|diffie|AES|RSA|FIPS|compress|zlib',
    'ssh-transport': r'SSH[12]?|packet|keep.?alive|rekey|re.key|banner',
    'serial-modem': r'serial|COM port|baud|parity|flow.control|RTS|DTR|TAPI|modem|named.pipe',
    'legacy-protocols': r'telnet|rlogin|SSL|TLS|SSH1',
    'tunnels-proxies': r'forward|SOCKS|proxy|firewall|jump.host|dependent.session|tunnel|X11',
    'terminal-emulation': r'emulat|VT\d|Xterm|ANSI|cursor|scroll|screen|escape.sequence|alternate|DECR|TN3270|Wyse',
    'colors-highlighting': r'colou?r|highlight|SGR|rendition|bold|underline|blink|reverse.video',
    'encoding-i18n': r'Unicode|UTF|DBCS|multibyte|multi.byte|character.set|encoding|combining|CJK|Chinese|Japanese|Korean|bidirectional|right.to.left',
    'keyboard-mouse': r'keyboard|key.map|keymap|hot.?key|shortcut|mouse|AltGr|function.key|keypad|accelerator|Ctrl|Alt\+',
    'layout-workspaces': r'tab|tile|tiling|cascad|snapshot|window|monitor|DPI|scal|fullscreen|full.screen',
    'sessions-config': r'session|configur|\.ini|import|export|folder|database|default',
    'credential-storage': r'credential|cache|cachin|personal.data|sensitive|vault|master.password',
    'automation-scripting': r'script|Python|VBScript|ActiveX|API\b|WaitFor|ReadString|SendString|synchronous|CRT\.',
    'commands-clipboard': r'command|button.bar|paste|clipboard|copy|send.ascii|delay|anti.idle',
    'logging-tracing': r'log\b|logging|log.file|trace|timestamp|rotation',
    'file-transfer': r'SFTP|SCP|VCP|Zmodem|Xmodem|Ymodem|Kermit|TFTP|transfer|download|upload',
    'local-integration': r'local.shell|PowerShell|CMD|ConPTY|RDP|scratchpad|browser|URL|printing|printer|print ',
    'ui-accessibility': r'dialog|menu|toolbar|tooltip|focus|accessib|screen.reader|508|drag|drop|font',
    'lifecycle-performance': r'crash|hang|deadlock|leak|memory|CPU|performance|slow|disconnect|reconnect|cancel|close|shutdown|resume|sleep|suspend|hung|unresponsive|long.time.to.start|did.not.start|freeze',
    'installation-updates': r'install|updat|license|registration|portable|MSI|registry|compatib|evaluation|Help\b',
    'network-addressing': r'DNS|IPv[46]|host.?name|winsock|WebDav|network|remote.host|connection',
    'other-input-behavior': r'NUM.?LOCK|NUNMLOCK|selection|double.click|triple.click|backspac|IME|Input.Method|\bkeys?\b',
    'display-application-behavior': r'status|theme|sorting|margin|pixels|list.controls|title.bar|line.drawing|line.length|columns|rows|hexadecimal|Raw.protocol|<esc>|vttest',
    'command-client-behavior': r'VSH|send.strings?|Receive.ASCII|ASCII|pause|completion|matches|Expect/Send|automating.logins|pasting|CRLF',
    'archive-platform-context': r'Ubuntu|Red.Hat|linux.version|DLL|Upgrading|Auto.?save|\boptions?\b',
    'archive-ui-context': r'Activator|Explorer|tray|Find\b|foreground|maximized|Connect.bar|Search.Filter|Resize|terminal.view|launch.an.application',
    'archive-network-file-context': r'file.specification|wild.cards|\bhosts?\b',
}
FAULTS = {
    'crash': r'crash|access.violation|segmentation|terminate.unexpected',
    'hang-blocking': r'\bhang|deadlock|unresponsive|freeze|froze|lock.up|not.respond',
    'memory-resource': r'memory|leak|handle|resource|buffer.overflow|stack.overflow',
    'security-validation': r'malicious|vulnerab|security|malformed|invalid.packet|verify|verification|fingerprint|host.key|password.*log',
    'corruption-loss': r'corrupt|lost|loss|truncat|incorrect|missing|overwrite|overwrit|duplicat',
    'performance': r'performance|slow|CPU|excessive|delay',
}


def decode(raw):
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('cp1252', errors='replace')


def read_document(cache, name, url, refresh=False):
    path = cache / name
    if refresh or not path.exists():
        with urlopen(url, timeout=30) as response:
            raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError('Document exceeds 5 MiB')
        path.write_bytes(raw)
    raw = path.read_bytes()
    return decode(raw), {'url': url, 'cache_file': str(path), 'bytes': len(raw),
                         'sha256': hashlib.sha256(raw).hexdigest(),
                         'cached_at_utc': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def parse_history(text, family, source):
    release = section = None
    entries, releases = [], []
    entry = None
    parent = None
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r'^Changes in SecureCRT\s+(.+?)(?:\s+--\s+(.+))?\s*$', line)
        if match:
            release = {'family': family, 'release': match[1], 'date': match[2],
                       'line': number, 'source': source}
            releases.append(release)
            section = 'unspecified'
            parent = None
            entry = None
            continue
        if release is None:
            continue
        stripped = line.strip()
        if stripped == 'All inquiries should be directed to:':
            break
        if re.match(r'^(New Features?|Features?|Changes?|Bugs? Fix(?:es)?|Fix(?:es)?|Vulnerabilit(?:y|ies)(?: Fix(?:es)?| addressed)?):$', stripped, re.I):
            label = stripped[:-1].lower()
            if label.startswith('vulnerab'):
                section = 'security-notes'
            elif label.startswith('bug') or label.startswith('fix'):
                section = 'bug-fixes'
            elif label.startswith('change'):
                section = 'changes'
            else:
                section = 'new-features'
            entry = None
            parent = None
            continue
        bullet = re.match(r'^\s+-\s+(.*)', line)
        if bullet:
            entry = dict(release, section=section, line=number, text=bullet[1])
            entry['indent'] = len(line) - len(line.lstrip())
            entry['parent_id'] = parent['id'] if entry['indent'] > 2 and parent else None
            entry['id'] = hashlib.sha256(f'{source}:{number}'.encode()).hexdigest()[:12]
            entries.append(entry)
            if entry['indent'] <= 2:
                parent = entry
        elif entry and stripped and not set(stripped) <= {'-'}:
            entry['text'] += ' ' + stripped
    for item in entries:
        item['topics'] = [name for name, pattern in TOPICS.items() if re.search(pattern, item['text'], re.I)]
        item['failure_tags'] = [name for name, pattern in FAULTS.items() if re.search(pattern, item['text'], re.I)]
    return releases, entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, default=Path('/workspace/securecrt-research-cache'))
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'docs' / 'research')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, path in DOCS.items():
        text, metadata = read_document(args.cache, name+'.html', BASE+path, args.refresh)
        if 'VanDyke Software - Redirection' in text or 'Page Not Found' in text:
            raise ValueError(f'{path} is a redirect or error document')
        manifest.append(dict(metadata, kind='reference'))
    _, metadata = read_document(args.cache, 'scripting_essentials.pdf', BASE+'/support/tips/scripting/scripting_essentials.pdf', args.refresh)
    if not (args.cache/'scripting_essentials.pdf').read_bytes().startswith(b'%PDF-'):
        raise ValueError('Scripting guide response is not a PDF')
    manifest.append(dict(metadata, kind='reference', note='122-page scripting guide, copyright 2009-2010; not the complete 9.7.4 API reference'))
    previous = decode((args.cache/'previous.html').read_bytes())
    families = set(re.findall(r'/download/securecrt/(\d+\.\d+)/index\.html', previous))
    families.update(re.findall(r'product=securecrt(?:&|&amp;)ver=(\d+\.\d+)', previous))
    families.add('9.7')
    families = sorted(families, key=lambda x: tuple(map(int,x.split('.'))))
    def fetch(family):
        url = BASE + ('/products/securecrt/history.txt' if family == '9.7' else f'/download/securecrt/{family}/history.txt')
        text, metadata = read_document(args.cache, f'history-{family}.txt', url, args.refresh)
        if '<html' in text.lower() or not re.search(r'^Changes in SecureCRT', text, re.M):
            raise ValueError(f'{url} is not a release history, even if HTTP returned 200')
        releases, entries = parse_history(text, family, url)
        return releases, entries, dict(metadata, family=family, kind='history', releases=len(releases), entries=len(entries))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, families))
    all_releases, all_entries = [], []
    for releases, entries, meta in results:
        all_releases.extend(releases); all_entries.extend(entries); manifest.append(meta)
    # Full normalized records remain in the local research cache only.
    (args.cache/'normalized-changes.json').write_text(json.dumps(all_entries, ensure_ascii=False, indent=2))
    columns = ['id','parent_id','indent','family','release','date','section','source','line','topics','failure_tags']
    with (args.out/'change-index.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, columns); writer.writeheader()
        for item in all_entries:
            row = {key:item.get(key) for key in columns}
            row['topics'] = ';'.join(row['topics']); row['failure_tags'] = ';'.join(row['failure_tags'])
            writer.writerow(row)
    counts = Counter(item['section'] for item in all_entries)
    summary = {'baseline':'9.7.4', 'retrieved_on':datetime.now(timezone.utc).date().isoformat(),
               'families':len(families),'release_sections':len(all_releases),'change_entries':len(all_entries),
               'sections':dict(counts), 'nested_bullet_entries':sum(x['parent_id'] is not None for x in all_entries), 'unclassified_entries':sum(not x['topics'] for x in all_entries),
               'scope':'All SecureCRT families linked from the official Previous Releases page, plus current 9.7; this does not prove there were no earlier or unlisted releases.',
               'classification':'Keyword navigation labels; overlapping; no claim of semantic equivalence, exploitability or fixes in Harbor.',
               'sources':manifest}
    (args.out/'source-manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    lines=['# 历代版本覆盖索引','',
           '范围：官方 Previous Releases 页面列出的全部 SecureCRT 分支，加当前 9.7 分支。不是只读取最新补丁；正式版、补丁与 Beta 分节均保留。',
           '',f'共 **{len(families)} 个系列、{len(all_releases)} 个发布分节、{len(all_entries)} 条变更**。',
           '','按原文 bullet 逐条索引，包含缩进子条目；CSV 保留 parent_id 和缩进，不把它们等同独立功能。分类由脚本按原有章节统计，主题标签仅用于检索。原始文档和完整逐条记录保存在 `/workspace/securecrt-research-cache`；CSV 包含每条记录的来源、行号、版本和分类，不转载整段说明。',
           '','| 系列 | 发布分节 | 新增 | 变更 | 修复 | 安全说明 | 其他 | 来源 |','|---|---:|---:|---:|---:|---:|---:|---|']
    for releases, entries, meta in results:
        c=Counter(item['section'] for item in entries)
        new=c['new-features']+c['features']; changed=c['changes']; fixes=c['bug-fixes']+c['fixes']
        security=c['security-notes']
        other=len(entries)-new-changed-fixes-security
        lines.append(f"| {meta['family']} | {len(releases)} | {new} | {changed} | {fixes} | {security} | {other} | [官方历史]({meta['url']}) |")
    lines += ['', '## 所有发布分节','', '| 系列 | 发布版本/阶段 | 原文日期 | 条目数 |','|---|---|---|---:|']
    for release in all_releases:
        count=sum(x['family']==release['family'] and x['release']==release['release'] and x['date']==release['date'] for x in all_entries)
        lines.append(f"| {release['family']} | {release['release']} | {release['date'] or '原文未列'} | {count} |")
    lines += ['', '## 边界', '',
              '未列出的更早版本不作已覆盖声明。没有安装或运行商业客户端；历史记录不是复现脚本，也不揭示所有内部实现。',
              '功能表是当前网站内容，不能独立证明某项功能在历史时间点的默认值；9.7.4 前后的差异需要结合对应历史与目标安装包核实。',
              '完整性指归档范围内的逐条索引，不表示每条历史故障都已复现、每项特性都已实现或已完成等价性验证。']
    (args.out/'release-coverage.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({key:value for key,value in summary.items() if key!='sources'},ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
