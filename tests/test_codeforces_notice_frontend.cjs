const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const elements = new Map();
function node() {
  return {
    children: [], dataset: {}, textContent: '',
    set innerHTML(value) { this.children = []; },
    append(...children) { this.children.push(...children); },
    appendChild(child) { this.children.push(child); },
  };
}
const context = vm.createContext({
  document: {
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, node());
      return elements.get(selector);
    },
    createElement: node,
  },
  console,
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8').replace(/\ninit\(\);\s*$/, ''), context);
vm.runInContext(`
  state.user = {id: '3'};
  state.overview = {members: [{isCurrent: true, handles: [{
    id: 3, platform: 'codeforces', platformLabel: 'Codeforces', handle: 'Yzm007',
    lastSyncAt: '2026-11-17T12:00:00Z', syncNotice: '1 场历史 Gym 补题暂不可用',
  }]}]};
  renderMyHandles();
`, context);
let row = elements.get('#myHandles').children[0];
assert.match(row.children[0].children[1].textContent, /上次同步.*1 场历史 Gym/);
assert.equal(row.children[1].children.length, 1, 'An optional Coach notice does not request account retry');
vm.runInContext(`state.overview.members[0].handles[0].lastError = 'Codeforces 授权读取失败'; renderMyHandles();`, context);
row = elements.get('#myHandles').children[0];
assert.match(row.children[0].children[1].textContent, /^同步异常：Codeforces 授权读取失败$/);
assert.equal(row.children[1].children[0].textContent, '重试');
console.log('CF Coach notice and account failure display checks passed.');
