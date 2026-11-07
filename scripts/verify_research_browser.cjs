// Exercise the offline browser's own filter/pagination code with a small DOM harness.
// This does not claim Chromium/Windows visual validation.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../docs/research/coverage.html'), 'utf8');
const payload = html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const code = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const elements = new Map();
function get(id) {
  if (!elements.has(id)) elements.set(id, {
    value:'', innerHTML:'', textContent:'', disabled:false,
    querySelectorAll() {
      return [...this.innerHTML.matchAll(/data-view="([^"]+)"/g)].map(m=>({dataset:{view:m[1]}}));
    }
  });
  return elements.get(id);
}
get('data').textContent = payload;
vm.runInNewContext(code, {document:{getElementById:get}}, {timeout:2000});
assert.equal((get('body').innerHTML.match(/<tr>/g)||[]).length, 75);
assert.match(get('count').textContent, /183/);
get('state').value='未实现'; get('state').onchange();
assert.ok(get('count').textContent.includes(String(JSON.parse(payload).requirements.rows.filter(x=>x.status==='未实现').length)));
get('query').value='串口'; get('query').oninput();
assert.ok(get('body').innerHTML.includes('串口'));
get('query').value=''; get('state').value='';
vm.runInNewContext('1+1', {});
// Re-enter with a harness that retains the navigation elements so events can run.
for (const el of elements.values()) el.querySelectorAll=function() {
  this.children=[...this.innerHTML.matchAll(/data-view="([^"]+)"/g)].map(m=>({dataset:{view:m[1]}}));
  return this.children;
};
// Isolated second page context reproduces initialization and event wiring.
vm.runInNewContext(code, {document:{getElementById:get}}, {timeout:2000});
get('nav').children.find(b=>b.dataset.view==='history').onclick();
assert.match(get('count').textContent, /4294/);
get('next').onclick(); assert.match(get('page').textContent, /^2 \/ /);
get('domain').value='9.7'; get('domain').onchange();
const expected=JSON.parse(payload).changes.filter(x=>x.family==='9.7').length;
assert.ok(get('count').textContent.includes(String(expected)));
get('nav').children.find(b=>b.dataset.view==='regressions').onclick();
assert.match(get('count').textContent, /36/);
get('nav').children.find(b=>b.dataset.view==='families').onclick();
assert.match(get('count').textContent, /32/);
assert.equal((get('body').innerHTML.match(/<tr>/g)||[]).length,32);
console.log('Research browser: requirement/status/text filters, history/family filters, navigation and pagination passed.');
