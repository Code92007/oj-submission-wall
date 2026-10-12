// ==UserScript==
// @name         OJ Wall QOJ手动同步
// @namespace    ojwall-qoj
// @version      1.0.4
// @downloadURL  __SCRIPT_URL__
// @updateURL    __SCRIPT_URL__
// @description  在浏览器中授权并手动同步本人的QOJ提交记录
// @match        https://qoj.ac/*
// @grant        GM_getValue
// @grant        GM_deleteValue
// @grant        GM_setValue
// @grant        GM_xmlhttpRequest
// @connect      __CONNECT_HOST__
// @run-at       document-idle
// ==/UserScript==
(() => {
  'use strict';
  const site = __SITE_JSON__;
  const key = `ojwall:qoj:${site}`;
  function currentUid(doc = document) {
    const profile = doc.querySelector('a.dropdown-item[href*="/user/profile/"]') ||
      doc.querySelector('.navbar .dropdown-menu a[href*="/user/profile/"]');
    if (!profile) throw new Error('请先登录 QOJ；无法识别导航栏中的当前账号');
    const match = new URL(profile.getAttribute('href'), 'https://qoj.ac').pathname.match(/^\/user\/profile\/([^/]+)\/?$/);
    if (!match) throw new Error('QOJ 当前账号格式无法识别');
    return decodeURIComponent(match[1]);
  }
  function submissionUsername(cell) {
    const usernames = new Set();
    for (const link of cell.querySelectorAll('a[href]')) {
      const url = new URL(link.getAttribute('href'), 'https://qoj.ac/');
      if (url.origin !== 'https://qoj.ac') continue;
      const profile = url.pathname.match(/^\/user\/profile\/([^/]+)\/?$/);
      const name = profile ? decodeURIComponent(profile[1]) :
        url.pathname === '/submissions' ? url.searchParams.get('submitter') : null;
      if (name && /^[A-Za-z0-9_-]{1,64}$/.test(name)) usernames.add(name);
    }
    if (usernames.size > 1) throw new Error('QOJ 提交者栏包含不同账号的链接，已停止');
    if (usernames.size === 1) return [...usernames][0];
    // A separate "#" filter/control is presentation, not part of a username.
    const copy = cell.cloneNode(true);
    for (const node of copy.querySelectorAll('a, button, sup, .badge, .glyphicon')) {
      if (/^[#＃]$/.test(node.textContent.trim())) node.remove();
    }
    const plain = copy.textContent.trim();
    return /^[A-Za-z0-9_-]{1,64}$/.test(plain) ? plain : '';
  }
  function parsePage(text, uid, page) {
    const doc = new DOMParser().parseFromString(text, 'text/html');
    if (doc.querySelector('input[type="password"]')) throw new Error('QOJ 登录失效，请重新登录');
    if (currentUid(doc) !== uid) throw new Error('QOJ 登录账号已变化，请重新连接');
    const bodies = [...doc.querySelectorAll('table tbody')];
    const tbody = bodies.find(body => body.querySelector('a[href*="/submission/"]')) ||
      bodies.find(body => [...body.querySelectorAll('tr')].some(row => row.cells.length >= 9 && /^#?\s*\d+$/.test(row.cells[0].textContent.trim()))) ||
      bodies.find(body => body.querySelector('td[colspan="233"]'));
    if (!tbody) throw new Error('QOJ 提交表格式改变或需要验证，请打开提交列表检查');
    const rows = [...tbody.querySelectorAll('tr')];
    if (rows.length === 1 && rows[0].cells.length === 1 && /^(None|无)$/i.test(rows[0].textContent.trim())) {
      return {list: [], hasNext: false};
    }
    const timezone = doc.body.textContent.match(/UTC([+-])(\d{1,2})(?::(\d{2}))?/);
    const offset = timezone ? (timezone[1] === '-' ? -1 : 1) * (+timezone[2] * 60 + +(timezone[3] || 0)) : 480;
    const list = rows.map(row => {
      const cells = [...row.cells];
      if (cells.length < 9) throw new Error('QOJ 提交表列数变化，已停止');
      const submission = cells[0].querySelector('a[href*="/submission/"]');
      const problem = cells[1].querySelector('a[href*="/problem/"]');
      const id = submission?.getAttribute('href').match(/\/submission\/(\d+)(?:[/?#]|$)/)?.[1] || cells[0].textContent.trim().match(/^#?\s*(\d+)$/)?.[1];
      const problemId = problem?.getAttribute('href').match(/\/problem\/(\d+)(?:[/?#]|$)/)?.[1] || cells[1].textContent.trim().match(/^#(\d+)(?:[.\s]|$)/)?.[1];
      const submitter = submissionUsername(cells[2]);
      if (!id) throw new Error(`QOJ 第 ${page} 页无法识别提交编号：${cells[0].textContent.trim().slice(0, 40)}`);
      if (!problemId) throw new Error(`QOJ 提交 #${id} 无法识别题号：${cells[1].textContent.trim().slice(0, 60)}`);
      if (submitter !== uid) throw new Error(`QOJ 提交 #${id} 的账号为「${submitter || cells[2].textContent.trim().slice(0, 80) || '未显示'}」，授权账号为「${uid}」，已停止`);
      const time = cells[8].textContent.trim().match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/);
      if (!time) throw new Error('QOJ 提交时间格式变化，已停止');
      const [, year, month, day, hour, minute, second] = time.map(Number);
      const submittedAt = Math.floor((Date.UTC(year, month - 1, day, hour, minute, second) - offset * 60000) / 1000);
      return {id, problemId, submitter, submittedAt, problemTitle: (problem || cells[1]).textContent.trim(),
        verdict: cells[3].textContent.trim(), language: cells[6].textContent.trim()};
    });
    const hasNext = [...doc.querySelectorAll('a[href]')].some(link => {
      const url = new URL(link.getAttribute('href'), 'https://qoj.ac/submissions');
      return url.origin === 'https://qoj.ac' && url.pathname === '/submissions' &&
        url.searchParams.get('page') === String(page + 1) &&
        (!url.searchParams.has('submitter') || url.searchParams.get('submitter') === uid);
    });
    return {list, hasNext};
  }
  const panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:99999;background:#fff;color:#222;padding:16px;border:1px solid #888;border-radius:12px;box-shadow:0 3px 15px #0003;max-width:280px;font:14px sans-serif';
  const title = document.createElement('strong'); title.textContent = 'OJ Wall 同步';
  const status = document.createElement('p'); status.textContent = '连接后手动同步本人的提交记录'; status.setAttribute('aria-live', 'polite');
  const connect = document.createElement('button'); connect.textContent = '连接 / 重新授权';
  const sync = document.createElement('button'); sync.textContent = '同步';
  const fullSync = document.createElement('button'); fullSync.textContent = '全量同步';
  fullSync.title = '重新扫描全部历史提交，用于补历史或更新较早的重判结果';
  const disconnect = document.createElement('button'); disconnect.textContent = '断开';
  for (const button of [connect, sync, fullSync, disconnect]) button.type = "button";
  panel.append(title, status, connect, sync, fullSync, disconnect); document.body.append(panel);
  let popup, nonce, pendingUid;
  let generation = 0, activeController;
  function updateButtons() {
    const connected = Boolean(GM_getValue(key, null)?.token);
    sync.disabled = fullSync.disabled = !connected;
    disconnect.disabled = !connected;
  }
  updateButtons();
  if (GM_getValue(key, null)?.token) status.textContent = '已连接，可以同步或断开';

  connect.onclick = () => {
    try {
      generation++;
      pendingUid = currentUid();
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(pendingUid)) throw new Error('请先登录QOJ');
      nonce = crypto.randomUUID();
      popup = window.open(`${site}/?qojAuthorize=1&uid=${encodeURIComponent(pendingUid)}&nonce=${nonce}`, '_blank');
      if (!popup) throw new Error('请允许打开授权窗口');
      status.textContent = '请在本站确认账号并授权';
    } catch (e) { status.textContent = e.message; }
  };
  window.addEventListener('message', event => {
    if (event.origin !== new URL(site).origin || event.source !== popup || !nonce) return;
    const data = event.data;
    if (data?.type !== 'ojwall-qoj-authorized' || data.nonce !== nonce || data.uid !== pendingUid || typeof data.token !== 'string') return;
    GM_setValue(key, {uid: data.uid, token: data.token}); nonce = null;
    updateButtons();
    status.textContent = `已连接账号 ${data.uid}，可以同步`;
  });
  function upload(auth, records) {
    return new Promise((resolve, reject) => GM_xmlhttpRequest({
      method: 'POST', url: `${site}/api/qoj-plugin/import`, anonymous: true, timeout: 30000,
      headers: {'Content-Type': 'application/json', Authorization: `Bearer ${auth.token}`},
      data: JSON.stringify({uid: auth.uid, records}),
      onload: response => {
        try { const data = JSON.parse(response.responseText); if (!data.ok) throw new Error(data.error || '导入失败'); resolve(data); }
        catch (e) { reject(e); }
      }, onerror: () => reject(new Error('本站连接失败，请稍后重试')),
      ontimeout: () => reject(new Error('上传超时，请稍后重试'))
    }));
  }
  disconnect.onclick = async () => {
    const auth = GM_getValue(key, null);
    const disconnectedGeneration = ++generation;
    nonce = null; popup = null;
    activeController?.abort();
    try {
      GM_deleteValue(key);
      GM_deleteValue(`${key}:last`);
    } catch (error) {
      status.textContent = `清除本机连接失败：${error.message}`;
      return;
    }
    updateButtons(); connect.disabled = false;
    status.textContent = '本机已断开，正在撤销本站授权…';
    if (!auth?.token) { status.textContent = '已断开'; return; }
    try {
      await new Promise((resolve, reject) => GM_xmlhttpRequest({
        method: 'POST', url: `${site}/api/qoj-plugin/revoke`, anonymous: true, timeout: 15000,
        headers: {'Content-Type': 'application/json', Authorization: `Bearer ${auth.token}`}, data: '{}',
        onload: response => {
          try {
            const result = JSON.parse(response.responseText);
            if (response.status >= 400 || !result.ok) throw new Error(result.error || '撤销失败');
            resolve();
          } catch (error) { reject(error); }
        },
        onerror: () => reject(new Error('连接失败')), ontimeout: () => reject(new Error('请求超时'))
      }));
      if (generation === disconnectedGeneration) status.textContent = '已断开，本站授权已撤销；已导入记录保留';
    } catch (error) {
      if (generation === disconnectedGeneration) status.textContent = `本机已断开；本站授权撤销失败（${error.message}），可在本站解绑账号撤销`;
    }
  };
  async function runSync(full = false) {
    const run = ++generation;
    const controller = new AbortController();
    activeController = controller;
    const checkActive = () => { if (run !== generation) throw new Error('同步已取消'); };
    sync.disabled = fullSync.disabled = connect.disabled = true;
    try {
      const auth = GM_getValue(key, null);
      if (!auth || currentUid() !== auth.uid) throw new Error('请登录已授权的QOJ账号并连接本站');
      const last = GM_getValue(`${key}:last`, 0);
      if (Date.now() - last < 120000) throw new Error('请间隔至少两分钟再同步');
      GM_setValue(`${key}:last`, Date.now());
      const checkpointKey = `${key}:checkpoint`;
      const saved = GM_getValue(checkpointKey, null);
      // A checkpoint belongs to this authorization, never a different wall account.
      const checkpoint = !full && saved?.uid === auth.uid && saved?.token === auth.token && /^\d+$/.test(saved?.newestId || '') ? saved : null;
      const boundary = checkpoint ? BigInt(checkpoint.newestId) : null;
      let newestId = boundary || 0n;
      let previousId = null, ordered = true, overlapPages = 0, completed = false, incrementalStop = false;
      let page = 1, total = 0;
      const seen = new Set();
      for (; page <= 1000; page++) {
        checkActive();
        status.textContent = `${checkpoint ? "增量" : "全量"}同步第 ${page} 页，已处理 ${total} 条，请保持页面开启`;
        const response = await fetch(`/submissions?submitter=${encodeURIComponent(auth.uid)}&page=${page}`, {credentials: 'same-origin', signal: controller.signal});
        checkActive();
        if (!response.ok) throw new Error(`QOJ HTTP ${response.status}，请稍后重试`);
        if (new URL(response.url).pathname === '/login') throw new Error('QOJ 登录失效，请重新登录');
        const {list, hasNext} = parsePage(await response.text(), auth.uid, page);
        if (!list.length) { completed = true; break; }
        const ids = list.map(record => {
          if (!/^\d+$/.test(String(record.id))) throw new Error('提交编号无效，已停止');
          return BigInt(record.id);
        });
        for (const id of ids) {
          if (previousId !== null && id > previousId) ordered = false;
          previousId = id;
          if (id > newestId) newestId = id;
        }
        for (const record of list) {
          if (seen.has(record.id)) throw new Error('QOJ 返回重复分页，已停止；稍后可重试');
          seen.add(record.id);
        }
        checkActive();
        for (let i = 0; i < list.length; i += 20) {
          checkActive();
          await upload(auth, list.slice(i, i + 20)); total += Math.min(20, list.length - i);
        }
        if (checkpoint && ordered && ids.every(id => id <= boundary)) overlapPages++;
        else overlapPages = 0;
        if (overlapPages >= 2) { completed = true; incrementalStop = true; break; }
        if (!hasNext) { completed = true; break; }
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
      checkActive();
      if (completed) {
        GM_setValue(checkpointKey, {uid: auth.uid, token: auth.token, newestId: String(newestId), completedAt: Date.now()});
      }
      status.textContent = !completed ? `已处理 ${total} 条，达到单次页数上限；未更新完成标记，下次继续全量检查` :
        incrementalStop ? `增量同步完成，处理 ${total} 条；已到上次同步范围并更新两页旧记录，自动停止` :
        `同步完成，处理 ${total} 条；下次将自动增量同步`;
    } catch (e) { if (run === generation) status.textContent = `${e.message}；已导入的数据会保留`; }
    finally { if (run === generation) { activeController = null; connect.disabled = false; updateButtons(); } }
  }
  sync.onclick = () => runSync(false);
  fullSync.onclick = () => runSync(true);
})();
