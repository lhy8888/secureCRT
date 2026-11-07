"""Generate a standalone, offline research browser from the audited JSON/CSV files."""
import csv
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'docs' / 'research'
requirements = json.loads((root / 'requirements.json').read_text())
manifest = json.loads((root / 'source-manifest.json').read_text())

# requirements.json is the canonical implementation/status ledger.
def render_matrix():
    from collections import Counter
    counts = Counter(row['status'] for row in requirements['rows'])
    lines = ['# SecureCRT 9.7.4 累积功能基线与实现矩阵', '',
             '目标平台：Windows 10/11。当前实现版本：' + requirements.get('implementation_version', '0.1.0') + '。', '',
             '结合完整官方历史、功能表、FAQ 和脚本资料。“已验证子集”只表示列出的平台/场景证据，不能扩大为全部Windows设备或与SecureCRT等价。验收条件保持为目标规格，旁列实际实现与限制。', '',
             '[调研总览](README.md) · [历史覆盖](release-coverage.md) · [可靠性场景](reliability-regressions.md) · [0.5 交付记录](../releases/0.5.md)', '',
             '183 项能力中，未实现 ' + str(counts['未实现']) + ' 项；没有整体产品等价性验收。']
    domains = list(dict.fromkeys(row['domain'] for row in requirements['rows']))
    for index, domain in enumerate(domains, 1):
        rows = [row for row in requirements['rows'] if row['domain'] == domain]
        sources = list(dict.fromkeys(url for row in rows for url in row['sources']))
        lines += ['', f'## {index}. {domain}', '',
                  '官方来源：' + '、'.join(f'[来源 {i+1}]({url})' for i,url in enumerate(sources)), '',
                  '| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |',
                  '|---|---|---|---|---|']
        for row in rows:
            note = row.get('implementation_note', '尚无新增实现/验证记录；不得据依赖能力推断完成。')
            validation = row.get('validation', '')
            if validation:
                note += '<br>证据：' + '; '.join(f'[{ref}](../../{ref.split("::")[0]})' for ref in validation.split('; '))
            lines.append('| ' + ' | '.join([row['id'], row['capability'], row['status'], note, row['acceptance']]) + ' |')
    lines += ['', '## 状态统计', ''] + [f'- {key}：{value} 项。' for key,value in counts.items()]
    lines += ['', '原始0.1调研时为163项未实现。0.2补终端/串口，0.3补SFTP/日志/Hex，0.4补单级跳板/转发，0.4.1重做界面/字体，0.5补MFA/命令与JSON流程及原生Windows包；仍不能据子集测试宣称完整模块已经完成。', '',
              '后续仍包括证书/凭据库、完整脚本对象、传输/日志高级功能、多级跳板/代理、布局快照/配置迁移、Windows 10/11实机、实体硬件及长期对照。',
              '百万行历史、横向重排、完整仿真/鼠标协议、原生Windows IME/DPI仍未验收。历史中的弱协议/命令行秘密/自动信任不会作为安全默认值。']
    (root / 'feature-matrix.md').write_text('\n'.join(lines) + '\n')

render_matrix()

regressions = json.loads((root / 'reliability-regressions.json').read_text())
# Keep the existing research explanation and quantity requirements, while the
# JSON ledger owns the current evidence column in both exported views.
regression_path = root / 'reliability-regressions.md'
original = regression_path.read_text()
intro = original.split('| ID |', 1)[0]
tail = original.split('\n## 所有历史修复的处理方式', 1)[1]
table = ['| ID | 历史问题 | 公开证据 | 应执行的回归 | Harbor 证据/缺口 |',
         '|---|---|---|---|---|']
for row in regressions:
    evidence = row['evidence']
    citation = f"[{evidence['release']}]({evidence['source']}) L{evidence['line']} / `{evidence['id']}`"
    table.append('| ' + ' | '.join((row['id'], row['issue'], citation, row['check'], row['status'])) + ' |')
regression_path.write_text(intro + '\n'.join(table) + '\n\n## 所有历史修复的处理方式' + tail)
with (root / 'change-index.csv').open(encoding='utf-8-sig') as stream:
    changes = list(csv.DictReader(stream))
payload = json.dumps(dict(requirements=requirements, manifest=manifest, regressions=regressions, changes=changes), ensure_ascii=False).replace('<', '\\u003c')
html = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>SecureCRT 9.7.4 累积功能审计</title>
<style>
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#dce7f2;background:#101822;color-scheme:dark}body{margin:0}main{max-width:1450px;padding:32px;margin:auto}h1{font-size:30px;margin:8px 0}p{line-height:1.7;color:#afc1d4}a{color:#7ec8ff}a:hover{color:white}.eyebrow{color:#78d8c2;font-size:13px;letter-spacing:.12em}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:24px 0}.card{padding:20px;background:#192635;border:1px solid #2c4057;border-radius:10px}.card strong{font-size:30px;display:block}.card span{font-size:13px;color:#afc1d4}.warning{border-left:4px solid #e6b95a;padding:14px 18px;background:#2c291f;line-height:1.7}.controls{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0}input,select,button{font:inherit;border-radius:6px;padding:10px;background:#1a2b3d;color:#dce7f2;border:1px solid #3b526c}input{min-width:280px;flex:1}button{cursor:pointer}.selected{border-color:#78d8c2;color:#78d8c2}.count{font-size:13px;color:#a7bbcf;margin:12px 0}.scroll{overflow:auto;border:1px solid #2b3e53;border-radius:8px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:12px;text-align:left;border-bottom:1px solid #2b3e53;vertical-align:top;line-height:1.6}th{color:#78d8c2;background:#192635;position:sticky;top:0}td:first-child{white-space:nowrap;color:#88a8c9}.tag{border-radius:4px;background:#29394b;padding:3px 6px;white-space:nowrap}nav{display:flex;gap:10px;flex-wrap:wrap}.pager{display:flex;gap:10px;align-items:center;margin:15px 0}.bar{display:flex;min-width:240px;height:15px;gap:1px}.bar i{display:block;background:#5283b4}.muted{color:#a7bbcf;font-size:12px}footer{margin:30px 0;color:#a7bbcf;font-size:13px}h2{font-size:20px}
</style></head><body><main>
<div class="eyebrow">HARBOR TERMINAL · PUBLIC EVIDENCE AUDIT · WINDOWS 10/11</div>
<h1>SecureCRT 9.7.4 累积功能基线</h1>
<p>覆盖官方旧版本入口列出的历史系列及当前 9.7，包含正式版、补丁版和 Beta。将公开需求与 Harbor 的实际实现状态逐项区分。</p>
<div class="cards" id="cards"></div>
<div class="warning">当前 Harbor 是开发版本。历史索引不是功能实现，关键词分类不是根因分析，“子集已测”不是与 SecureCRT 等价。已有Windows原生CI与实际EXE启动证据；商业客户端内置帮助、用户Windows 10/11实机、实体 COM 与长期对照仍待完成。</div>
<p><a href="README.md">研究说明</a> · <a href="feature-matrix.md">完整需求矩阵</a> · <a href="reliability-regressions.md">历史回归</a> · <a href="release-coverage.md">发布覆盖</a> · <a href="change-index.csv">下载逐条索引 CSV</a></p>
<nav id="nav"></nav>
<div class="controls"><input id="query" aria-label="检索" placeholder="搜索能力、验收、版本或主题标签"><select id="domain" aria-label="领域"></select><select id="state" aria-label="状态"></select></div>
<div class="count" id="count"></div><div class="scroll"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<div class="pager"><button id="prev">上一页</button><span id="page"></span><button id="next">下一页</button></div>
<footer>来源检索日期 2026-11-07。原文保留在本地研究缓存；此文件不转载完整变更正文。HTML 可离线打开，不使用外部资源或分析跟踪。</footer>
</main><script id="data" type="application/json">__DATA__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const link=(url,label)=>'<a target="_blank" rel="noopener noreferrer" href="'+esc(url)+'">'+esc(label)+'</a>';
let view='requirements',page=0;const size=75;
const views={requirements:'183 项功能要求',regressions:'36 项回归场景',history:'4294 条变更位置',families:'32 个系列覆盖'};
$('cards').innerHTML=[[data.manifest.families,'历史系列'],[data.manifest.release_sections,'发布分节'],[data.manifest.change_entries,'历史变更'],[data.requirements.rows.length,'功能/验收条目'],[data.requirements.counts['未实现'],'明确未实现']].map(([n,s])=>'<div class="card"><strong>'+n+'</strong><span>'+s+'</span></div>').join('');
function nav(){ $('nav').innerHTML=Object.entries(views).map(([k,v])=>'<button data-view="'+k+'" class="'+(k===view?'selected':'')+'">'+v+'</button>').join('');$('nav').querySelectorAll('button').forEach(b=>b.onclick=()=>{view=b.dataset.view;page=0;nav();filters();render();}); }
function options(id,label,values){$(id).innerHTML='<option value="">'+label+'</option>'+[...new Set(values)].sort().map(s=>'<option>'+esc(s)+'</option>').join('');}
function filters(){
 if(view==='requirements'){options('domain','全部领域',data.requirements.rows.map(x=>x.domain));options('state','全部状态',data.requirements.rows.map(x=>x.status));}
 else if(view==='history'){options('domain','全部系列',data.changes.map(x=>x.family));options('state','全部章节',data.changes.map(x=>x.section));}
 else{options('domain','全部',[]);options('state','全部',[]);}
}
function render(){
 const q=$('query').value.trim().toLowerCase(),d=$('domain').value,s=$('state').value;
 let rows,headers,format;
 if(view==='requirements'){
  rows=data.requirements.rows.filter(x=>(!d||x.domain===d)&&(!s||x.status===s));headers=['ID / 领域','能力','Harbor 状态','验收条件','来源'];
  format=x=>['<span>'+esc(x.id)+'</span><br>'+esc(x.domain),esc(x.capability),'<span class="tag">'+esc(x.status)+'</span><div class="muted">'+esc(x.implementation_note||'')+'</div>',esc(x.acceptance),x.sources.map((u,i)=>link(u,'来源 '+(i+1))).join('<br>')];
 }else if(view==='regressions'){
  rows=data.regressions;headers=['ID','历史问题','回归要求','当前证据/缺口','来源'];
  format=x=>[esc(x.id),esc(x.issue),esc(x.check),esc(x.status),link(x.evidence.source,x.evidence.release)+'<br>L'+x.evidence.line+' / '+esc(x.evidence.id)];
 }else if(view==='history'){
  rows=data.changes.filter(x=>(!d||x.family===d)&&(!s||x.section===s));headers=['记录 ID','发布分节','章节','主题 / 故障标签','原文位置'];
  format=x=>[esc(x.id),esc(x.release)+'<br>'+esc(x.date),esc(x.section),esc(x.topics)+'<br><span class="muted">'+esc(x.failure_tags)+'</span>',link(x.source,'官方原文')+' L'+x.line];
 }else{
  rows=data.manifest.sources.filter(x=>x.kind==='history');headers=['系列','发布分节','记录数','相对数量','原文'];
  const maximum=Math.max(...rows.map(x=>x.entries));format=x=>[esc(x.family),x.releases,x.entries,'<div class="bar"><i style="width:'+Math.round(x.entries/maximum*100)+'%"></i></div>',link(x.url,'官方历史')];
 }
 if(q)rows=rows.filter(x=>JSON.stringify(x).toLowerCase().includes(q));
 const pages=Math.max(1,Math.ceil(rows.length/size));page=Math.min(page,pages-1);
 $('head').innerHTML='<tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr>';
 $('body').innerHTML=rows.slice(page*size,(page+1)*size).map(x=>'<tr>'+format(x).map(y=>'<td>'+y+'</td>').join('')+'</tr>').join('');
 $('count').textContent='符合条件 '+rows.length+' 项'+(view==='history'?'；按原文位置索引，主题为机械检索标签。':'');
 $('page').textContent=(page+1)+' / '+pages;$('prev').disabled=page===0;$('next').disabled=page===pages-1;
}
$('query').oninput=()=>{page=0;render();};$('domain').onchange=$('state').onchange=()=>{page=0;render();};$('prev').onclick=()=>{page--;render();};$('next').onclick=()=>{page++;render();};nav();filters();render();
</script></body></html>'''
(root / 'coverage.html').write_text(html.replace('__DATA__',payload))
print(root / 'coverage.html')
