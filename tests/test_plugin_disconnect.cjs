const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
async function run(platform, failRevoke = false, duringSync = false) {
  const nodes = [];
  const store = new Map();
  const site = 'https://oj-train-wall.wannafly.cn';
  const key = platform === 'qoj' ? `ojwall:qoj:${site}` : `ojwall:${site}`;
  store.set(key, {uid: '123', token: 'secret'});
  store.set(`${key}:last`, 12345);
  let request, message;
  const context = vm.createContext({
    URL, AbortController, setTimeout,
    fetch: (url, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted')))),
    document: {body: {append() {}}, createElement(type) {
      const element = {type,style: {},textContent: '',disabled: false,setAttribute() {},append() {}};
      nodes.push(element); return element;
    }},
    window: {addEventListener(type, callback) { message = callback; }},
    GM_getValue: (name, fallback) => store.has(name) ? store.get(name) : fallback,
    GM_setValue: (name, value) => { if (value === null) throw Error('null unsupported'); store.set(name, value); },
    GM_deleteValue: name => store.delete(name),
    GM_xmlhttpRequest: options => { request = options; queueMicrotask(() => failRevoke ? options.onerror() : options.onload({status: 200,responseText: '{"ok":true}'})); }
  });
  const source = fs.readFileSync(path.join(__dirname, `../web/${platform}-sync.user.js`),'utf8').replace('__SITE_JSON__', JSON.stringify(site)).replace('  const panel =', '  currentUid = () => \"123\";\n  const panel =');
  vm.runInContext(source, context);
  const disconnect = nodes.find(node => node.textContent === '断开');
  const sync = nodes.find(node => node.textContent === '同步');
  const status = nodes.find(node => node.type === 'p');
  assert.equal(sync.disabled, false);
  const pendingSync = duringSync ? sync.onclick() : null;
  await disconnect.onclick();
  if (pendingSync) await pendingSync;
  assert.equal(store.has(key), false);
  assert.equal(store.has(`${key}:last`), false);
  assert.equal(sync.disabled, true);
  assert.equal(disconnect.disabled, true);
  assert.equal(request.url, `${site}/api/${platform}-plugin/revoke`);
  assert.equal(request.headers.Authorization, 'Bearer secret');
  assert.match(status.textContent, failRevoke ? /本机已断开.*撤销失败/ : /已断开.*授权已撤销/);
  assert.equal(disconnect.type, 'button');
  return context;
}
(async()=>{for(const platform of ['luogu','qoj']) {await run(platform);await run(platform,true);await run(platform,false,true);} console.log('Disconnect: both platforms clear storage, revoke remotely, disable sync and report network failure');})().catch(error=>{console.error(error);process.exitCode=1});
