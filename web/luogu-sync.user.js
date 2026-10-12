// ==UserScript==
// @name         OJ Wall 洛谷手动同步
// @namespace    ojwall-luogu
// @version      1.0.2
// @downloadURL  __SCRIPT_URL__
// @updateURL    __SCRIPT_URL__
// @description  在浏览器中授权并手动同步本人的洛谷提交记录
// @match        https://www.luogu.com.cn/*
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
  const key = `ojwall:${site}`;
  function parse(text) {
    try { return JSON.parse(text); } catch (_) { /* HTML response */ }
    const encoded = text.match(/JSON\.parse\(decodeURIComponent\("([^"\n]+)"\)\)/);
    if (encoded) return JSON.parse(decodeURIComponent(encoded[1]));
    const node = new DOMParser().parseFromString(text, 'text/html').querySelector('#lentille-context');
    if (node) return JSON.parse(node.textContent);
    throw new Error('洛谷页面格式改变或需要验证，请在洛谷完成验证后重试');
  }
  function currentUid() {
    const data = parse(document.documentElement.outerHTML);
    return String(data.currentUser?.uid || data.user?.uid || data.currentData?.currentUser?.uid || '');
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
      if (!/^\d+$/.test(pendingUid) || pendingUid === '0') throw new Error('请先登录洛谷');
      nonce = crypto.randomUUID();
      popup = window.open(`${site}/?luoguAuthorize=1&uid=${pendingUid}&nonce=${nonce}`, '_blank');
      if (!popup) throw new Error('请允许打开授权窗口');
      status.textContent = '请在本站确认账号并授权';
    } catch (e) { status.textContent = e.message; }
  };
  window.addEventListener('message', event => {
    if (event.origin !== new URL(site).origin || event.source !== popup || !nonce) return;
    const data = event.data;
    if (data?.type !== 'ojwall-luogu-authorized' || data.nonce !== nonce || data.uid !== pendingUid || typeof data.token !== 'string') return;
    GM_setValue(key, {uid: data.uid, token: data.token}); nonce = null;
    updateButtons();
    status.textContent = `已连接 UID ${data.uid}，可以同步`;
  });
  function upload(auth, records) {
    return new Promise((resolve, reject) => GM_xmlhttpRequest({
      method: 'POST', url: `${site}/api/luogu-plugin/import`, anonymous: true, timeout: 30000,
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
        method: 'POST', url: `${site}/api/luogu-plugin/revoke`, anonymous: true, timeout: 15000,
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
      if (!auth || currentUid() !== auth.uid) throw new Error('请登录已授权的洛谷账号并连接本站');
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
      for (; page <= 1000; page++) {
        checkActive();
        status.textContent = `${checkpoint ? "增量" : "全量"}同步第 ${page} 页，已处理 ${total} 条，请保持页面开启`;
        const response = await fetch(`/record/list?user=${auth.uid}&page=${page}&_contentOnly=1`, {credentials: 'same-origin', signal: controller.signal});
        checkActive();
        if (!response.ok) throw new Error(`洛谷 HTTP ${response.status}，请稍后重试`);
        const payload = parse(await response.text());
        const records = (payload.currentData || payload.data || payload).records;
        const list = Array.isArray(records) ? records : records?.result;
        if (!Array.isArray(list)) throw new Error('洛谷未返回提交记录，请检查登录状态或完成验证');
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
        if (list.some(record => String(record.user?.uid) !== auth.uid)) throw new Error('返回的记录与当前账号不匹配，已停止');
        checkActive();
        for (let i = 0; i < list.length; i += 20) {
          checkActive();
          const safe = list.slice(i, i + 20).map(record => ({
            id: record.id, submitTime: record.submitTime, status: record.status, score: record.score,
            language: record.language, user: {uid: record.user.uid},
            problem: {pid: record.problem?.pid, title: record.problem?.title, type: record.problem?.type, fullScore: record.problem?.fullScore}
          }));
          await upload(auth, safe); total += safe.length;
        }
        if (checkpoint && ordered && ids.every(id => id <= boundary)) overlapPages++;
        else overlapPages = 0;
        if (overlapPages >= 2) { completed = true; incrementalStop = true; break; }
        if (records.count != null && page * (records.perPage || list.length) >= records.count) { completed = true; break; }
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
