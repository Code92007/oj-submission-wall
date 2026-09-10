const state = {
  user: null,
  platforms: [],
  overview: null,
  busy: false,
  feedFilters: {
    platform: "",
    user: "",
    language: "",
    verdict: "",
    from: "",
    to: "",
  },
  feedPage: 1,
  feedPageSize: 25,
  wallRange: "",
  selectedMemberKey: "",
  selectedHandleKeys: new Set(),
  memberGroupFilter: "",
  binding: false,
  handleBusy: new Set(),
  overviewPollTimer: null,
  mainView: "overview",
  battleLeftKey: "",
  battleRightKey: "",
  battleRange: "365",
  battle: null,
  battleLoading: false,
  battleError: "",
  battleRequestId: 0,
};

const $ = (selector) => document.querySelector(selector);
const el = (tag, className) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

const CONTEST_PLATFORM_ORDER = ["codeforces", "atcoder", "nowcoder", "luogu", "vjudge", "loj", "qoj", "other"];
const CONTEST_CATEGORY_ORDER = [
  "codeforces.div1",
  "codeforces.div1_2",
  "codeforces.div2",
  "codeforces.div3",
  "codeforces.div4",
  "codeforces.educational",
  "codeforces.global",
  "codeforces.gym",
  "codeforces.special",
  "codeforces.other",
  "atcoder.abc",
  "atcoder.arc",
  "atcoder.agc",
  "atcoder.ahc",
  "atcoder.other",
  "nowcoder.multi_school",
  "nowcoder.weekly",
  "nowcoder.monthly",
  "nowcoder.newbie_monthly",
  "nowcoder.icpc_ccpc",
  "nowcoder.school",
  "nowcoder.seasonal",
  "nowcoder.practice",
  "nowcoder.challenge",
  "nowcoder.other",
  "luogu.monthly",
  "luogu.weekly",
  "luogu.beginner",
  "luogu.other",
  "vjudge.ucup",
  "vjudge.contest",
  "qoj.ucup",
  "qoj.contest",
  "other",
];
const CONTEST_PLATFORM_RANK = new Map(CONTEST_PLATFORM_ORDER.map((key, index) => [key, index]));
const CONTEST_CATEGORY_RANK = new Map(CONTEST_CATEGORY_ORDER.map((key, index) => [key, index]));
const DISPLAY_TIME_ZONE = "Asia/Shanghai";
const OVERVIEW_BROWSER_CACHE_KEY = "ojwall.overview.v3";
const OVERVIEW_BROWSER_CACHE_MAX_AGE_MS = 6 * 60 * 60 * 1000;
const OVERVIEW_BROWSER_CACHE_FEED_LIMIT = 500;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const init = {
    credentials: "same-origin",
    headers: {},
    ...options,
  };
  if (options.body && typeof options.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `请求失败：${response.status}`);
  }
  return data;
}

function showMessage(text, type = "info", link) {
  const box = $("#message");
  box.classList.remove("hidden", "error");
  if (type === "error") box.classList.add("error");
  box.textContent = text;
  if (link) {
    const anchor = document.createElement("a");
    anchor.href = link;
    anchor.textContent = " 打开验证链接";
    anchor.target = "_blank";
    anchor.rel = "noreferrer";
    box.appendChild(anchor);
  }
}

function clearMessage() {
  $("#message").classList.add("hidden");
  $("#message").textContent = "";
}

function setBusy(value) {
  state.busy = value;
  $("#refreshBtn").disabled = value;
  $("#refreshBtn").textContent = value ? "提交中..." : "刷新同步";
}

function setHandleBusy(id, value) {
  const key = String(id);
  if (value) state.handleBusy.add(key);
  else state.handleBusy.delete(key);
  renderMyHandles();
}

function switchAuthTab(name) {
  clearMessage();
  for (const tab of ["guest", "login", "register"]) {
    $(`#${tab}Tab`).classList.toggle("active", tab === name);
    $(`#${tab}Form`).classList.toggle("hidden", tab !== name);
  }
}

async function loadSession() {
  const data = await api("/api/session");
  state.user = data.user;
  state.platforms = data.platforms || [];
  renderSession();
  renderPlatformSelect();
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function sanitizedOverviewForBrowserCache(data) {
  const copy = cloneJson(data);
  if (copy.user) copy.user.realName = "";
  if (copy.mirror) delete copy.mirror.sync;
  for (const member of copy.members || []) {
    member.realName = "";
    member.realNameVisible = false;
    for (const handle of member.handles || []) {
      handle.syncStatus = "";
    }
  }
  return copy;
}

function saveOverviewBrowserCache(data) {
  if (!data || !Array.isArray(data.members)) return;
  const snapshot = sanitizedOverviewForBrowserCache(data);
  const payload = {
    savedAt: Date.now(),
    data: snapshot,
  };
  try {
    localStorage.setItem(OVERVIEW_BROWSER_CACHE_KEY, JSON.stringify(payload));
    return;
  } catch (_) {
    // Large teams can exceed localStorage. Keep enough feed rows for first paint.
  }

  try {
    const slim = snapshot;
    if (Array.isArray(slim.feed) && slim.feed.length > OVERVIEW_BROWSER_CACHE_FEED_LIMIT) {
      slim.mirror = slim.mirror || {};
      slim.mirror.browserPartial = true;
      slim.mirror.fullFeedCount = slim.feed.length;
      slim.feed = slim.feed.slice(0, OVERVIEW_BROWSER_CACHE_FEED_LIMIT);
    }
    localStorage.setItem(OVERVIEW_BROWSER_CACHE_KEY, JSON.stringify({ savedAt: Date.now(), data: slim }));
  } catch (_) {
    localStorage.removeItem(OVERVIEW_BROWSER_CACHE_KEY);
  }
}

function readOverviewBrowserCache() {
  try {
    const raw = localStorage.getItem(OVERVIEW_BROWSER_CACHE_KEY);
    if (!raw) return null;
    const payload = JSON.parse(raw);
    if (!payload?.data || Date.now() - Number(payload.savedAt || 0) > OVERVIEW_BROWSER_CACHE_MAX_AGE_MS) {
      localStorage.removeItem(OVERVIEW_BROWSER_CACHE_KEY);
      return null;
    }
    const data = cloneJson(payload.data);
    data.mirror = data.mirror || {};
    data.mirror.browserCache = true;
    data.mirror.servedAt = new Date(Number(payload.savedAt || Date.now())).toISOString();
    return data;
  } catch (_) {
    localStorage.removeItem(OVERVIEW_BROWSER_CACHE_KEY);
    return null;
  }
}

function updateWallRange(data) {
  const validRanges = ["all", ...(data.availableYears || []).map(String)];
  if (!state.wallRange || !validRanges.includes(String(state.wallRange))) {
    state.wallRange = String(data.availableYears?.[0] || new Date().getFullYear());
  }
}

function applyOverviewData(data, options = {}) {
  state.overview = data;
  state.user = data.user;
  if (data.platforms) state.platforms = data.platforms;
  updateWallRange(data);
  renderAll();
  if (options.save !== false) saveOverviewBrowserCache(data);
  if (state.mainView === "battle" && state.battleLeftKey && state.battleRightKey) {
    loadBattle();
  }
}

function hasActiveSync(data = state.overview) {
  const sync = data?.mirror?.sync || {};
  return Boolean(sync.running || Number(sync.pending || 0) > 0);
}

function scheduleOverviewPoll(delay = 1600, remaining = 8) {
  if (state.overviewPollTimer) clearTimeout(state.overviewPollTimer);
  if (remaining <= 0) return;
  state.overviewPollTimer = setTimeout(async () => {
    try {
      await loadOverview();
    } catch (_) {
      return;
    }
    if (hasActiveSync()) {
      scheduleOverviewPoll(Math.min(Math.round(delay * 1.5), 8000), remaining - 1);
    }
  }, delay);
}

function hydrateOverviewFromBrowserCache() {
  const cached = readOverviewBrowserCache();
  if (!cached) return false;
  applyOverviewData(cached, { save: false });
  return true;
}

async function loadOverview() {
  const data = await api("/api/overview?days=3650");
  applyOverviewData(data);
  if (data.mirror?.fallback) {
    const asOf = data.mirror.asOf ? formatDateTime(data.mirror.asOf) : "未知时间";
    showMessage(`当前显示本地镜像，数据截至 ${asOf}。`, "error");
  }
}

function renderSession() {
  const badge = $("#sessionBadge");
  const bindPanel = $("#bindPanel");
  const authPanel = $("#authPanel");
  const logoutBtn = $("#logoutBtn");

  if (!state.user) {
    badge.textContent = "未登录";
    bindPanel.classList.add("hidden");
    authPanel.classList.remove("hidden");
    logoutBtn.classList.add("hidden");
    return;
  }

  const prefix = state.user.type === "guest" ? "游客" : "账号";
  badge.textContent = `${prefix}：${state.user.displayName}`;
  bindPanel.classList.remove("hidden");
  authPanel.classList.add("hidden");
  logoutBtn.classList.remove("hidden");
}

function renderPlatformSelect() {
  const select = $("#platformSelect");
  select.innerHTML = "";
  for (const platform of state.platforms) {
    const option = document.createElement("option");
    option.value = platform.key;
    option.textContent = platform.label;
    option.dataset.hint = platform.hint;
    select.appendChild(option);
  }
  updateHandleHint();
}

function updateHandleHint() {
  const select = $("#platformSelect");
  const option = select.options[select.selectedIndex];
  $("#handleInput").placeholder = option?.dataset?.hint || "填写 OJ 账号";
}

function renderAll() {
  renderSession();
  renderPlatformSelect();
  renderWallYearSelect();
  renderStats();
  renderProfileForm();
  renderMyHandles();
  renderMembers();
  renderFeed();
  renderMainView();
}

function renderProfileForm() {
  const fields = [
    ["#profileDisplayNameInput", state.user?.displayName || ""],
    ["#profileRealNameInput", state.user?.realName || ""],
    ["#profileTeamInput", state.user?.teamName || ""],
  ];
  for (const [selector, value] of fields) {
    const input = $(selector);
    if (!input || document.activeElement === input) continue;
    input.value = value;
  }
}

function renderWallYearSelect() {
  const select = $("#wallYearSelect");
  const years = state.overview?.availableYears || [String(new Date().getFullYear())];
  select.innerHTML = "";
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = "近 10 年";
  select.appendChild(all);
  for (const year of years) {
    const option = document.createElement("option");
    option.value = String(year);
    option.textContent = `${year} 年`;
    select.appendChild(option);
  }
  select.value = ["all", ...years.map(String)].includes(String(state.wallRange)) ? String(state.wallRange) : String(years[0]);
  state.wallRange = select.value;
}

function renderStats() {
  const overview = state.overview;
  if (!overview) return;
  const members = overview.members || [];
  const today = overview.today;
  const todayAccepted = members.reduce((sum, member) => {
    return sum + (member.days?.[today]?.accepted || 0);
  }, 0);
  const contestTotal = members.reduce((sum, member) => sum + (member.contests?.total || 0), 0);
  const mirror = overview.mirror || {};
  $("#memberCount").textContent = members.length;
  $("#todayCount").textContent = todayAccepted;
  $("#feedCount").textContent = mirror.fullFeedCount || overview.feed?.length || 0;
  $("#contestCount").textContent = contestTotal;
  const generatedAt = mirror.generatedAt || overview.now;
  const asOf = mirror.asOf;
  const sync = mirror.sync || {};
  const syncText = sync.running
    ? "后台同步中"
    : Number(sync.pending || 0) > 0
      ? `${Number(sync.pending || 0)} 个同步任务排队`
      : "";
  const syncSuffix = syncText ? ` · ${syncText}` : "";
  if (mirror.browserCache) {
    $("#lastUpdated").textContent = `本地缓存 · ${generatedAt ? `更新于 ${formatDateTime(generatedAt)} · ` : ""}正在更新${syncSuffix}`;
  } else if (mirror.fallback) {
    $("#lastUpdated").textContent = `本地镜像 · 数据截至 ${asOf ? formatDateTime(asOf) : "未知"} · 读取于 ${formatDateTime(mirror.servedAt || generatedAt)}${syncSuffix}`;
  } else if (asOf) {
    $("#lastUpdated").textContent = `更新于 ${formatDateTime(generatedAt)} · 数据截至 ${formatDateTime(asOf)}${syncSuffix}`;
  } else {
    $("#lastUpdated").textContent = generatedAt ? `更新于 ${formatDateTime(generatedAt)}${syncSuffix}` : `等待同步${syncSuffix}`;
  }
}

function renderMyHandles() {
  const list = $("#myHandles");
  list.innerHTML = "";
  if (!state.user || !state.overview) return;
  const current = (state.overview.members || []).find((member) => member.isCurrent);
  const handles = current?.handles || [];
  if (!handles.length) {
    const empty = el("div", "muted");
    empty.textContent = "还没有绑定 OJ 账号";
    list.appendChild(empty);
    return;
  }

  for (const item of handles) {
    const syncStatus = item.syncStatus || "";
    const busy = state.handleBusy.has(String(item.id)) || syncStatus === "queued" || syncStatus === "running";
    const row = el("div", "handle-item");
    const main = el("div", "handle-main");
    const title = document.createElement("strong");
    title.textContent = `${item.platformLabel} / ${item.displayHandle || item.handle}`;
    const meta = document.createElement("span");
    if (syncStatus === "running") {
      meta.textContent = "正在后台同步";
    } else if (syncStatus === "queued") {
      meta.textContent = "等待后台同步";
    } else {
      meta.textContent = item.lastError
        ? `同步异常：${item.lastError}`
        : item.lastSyncAt
          ? `上次同步 ${formatDateTime(item.lastSyncAt)}`
          : "尚未同步";
    }
    main.append(title, meta);

    const actions = el("div", "handle-actions");
    if (item.lastError) {
      const retry = el("button", "button ghost");
      retry.type = "button";
      retry.textContent = busy ? "重试中..." : "重试";
      retry.disabled = busy;
      retry.dataset.retryHandleId = item.id;
      actions.appendChild(retry);
    }

    const remove = el("button", "button ghost danger");
    remove.type = "button";
    remove.textContent = busy ? "处理中..." : "移除";
    remove.disabled = busy;
    remove.dataset.handleId = item.id;
    actions.appendChild(remove);
    row.append(main, actions);
    list.appendChild(row);
  }
}

function renderMembers() {
  const container = $("#members");
  container.innerHTML = "";
  const members = sortedMembers([...(state.overview?.members || [])]);
  if (!members.length) {
    const empty = el("div", "empty-state");
    empty.textContent = "还没有成员。可以先注册或用游客模式绑定账号看效果。";
    container.appendChild(empty);
    return;
  }

  let selected = null;
  if (state.selectedMemberKey) {
    selected = members.find((member) => memberKey(member) === state.selectedMemberKey);
    if (!selected) {
      state.selectedMemberKey = "";
      state.selectedHandleKeys.clear();
    }
  }
  container.classList.toggle("member-detail-mode", Boolean(selected));
  if (selected) {
    container.appendChild(renderMemberDetail(selected));
    return;
  }

  container.append(renderTeamOverview(members), renderMemberDirectory(members));
}

function sortedMembers(members) {
  members.sort((a, b) => {
    const today = state.overview.today;
    const aToday = a.days?.[today]?.accepted || 0;
    const bToday = b.days?.[today]?.accepted || 0;
    return bToday - aToday || b.stats.accepted - a.stats.accepted || a.displayName.localeCompare(b.displayName);
  });
  return members;
}

function memberKey(member) {
  return `${member.ownerType}:${member.ownerId}`;
}

function battleMemberLabel(member) {
  const current = member.isCurrent ? "（我）" : "";
  return `${member.displayName}${current} · ${memberTeam(member)}`;
}

function ensureBattlePlayers() {
  const members = sortedMembers([...(state.overview?.members || [])]);
  const keys = new Set(members.map(memberKey));
  if (!keys.has(state.battleLeftKey)) {
    const preferred = members.find((member) => member.isCurrent) || members[0];
    state.battleLeftKey = preferred ? memberKey(preferred) : "";
  }
  if (!keys.has(state.battleRightKey) || state.battleRightKey === state.battleLeftKey) {
    const opponent = members.find((member) => memberKey(member) !== state.battleLeftKey);
    state.battleRightKey = opponent ? memberKey(opponent) : "";
  }
  return members;
}

function renderBattleSelect(select, members, selectedKey) {
  select.innerHTML = "";
  if (!members.length) {
    const option = document.createElement("option");
    option.textContent = "暂无成员";
    select.appendChild(option);
    select.disabled = true;
    return;
  }
  for (const member of members) {
    const option = document.createElement("option");
    option.value = memberKey(member);
    option.textContent = battleMemberLabel(member);
    select.appendChild(option);
  }
  select.value = selectedKey;
  select.disabled = members.length < 2;
}

function renderBattleControls() {
  const members = ensureBattlePlayers();
  renderBattleSelect($("#battleLeftSelect"), members, state.battleLeftKey);
  renderBattleSelect($("#battleRightSelect"), members, state.battleRightKey);
  $("#battleRangeSelect").value = state.battleRange;
  $("#battleSwapBtn").disabled = members.length < 2;
}

function battleSignature() {
  return `${state.battleLeftKey}|${state.battleRightKey}|${state.battleRange}`;
}

function renderMainView() {
  const battleActive = state.mainView === "battle";
  $("#overviewTab").classList.toggle("active", !battleActive);
  $("#overviewTab").setAttribute("aria-selected", battleActive ? "false" : "true");
  $("#overviewTab").tabIndex = battleActive ? -1 : 0;
  $("#battleTab").classList.toggle("active", battleActive);
  $("#battleTab").setAttribute("aria-selected", battleActive ? "true" : "false");
  $("#battleTab").tabIndex = battleActive ? 0 : -1;
  $("#overviewView").classList.toggle("hidden", battleActive);
  $("#battleView").classList.toggle("hidden", !battleActive);
  $("#feedPanel").classList.toggle("hidden", battleActive);
  if (battleActive) {
    renderBattleControls();
    renderBattleContent();
  }
}

function switchMainView(view) {
  state.mainView = view === "battle" ? "battle" : "overview";
  clearMessage();
  renderMainView();
  if (state.mainView === "battle" && state.battleLeftKey && state.battleRightKey) {
    loadBattle();
  }
}

function selectBattlePlayer(side, value) {
  const otherSide = side === "left" ? "right" : "left";
  const ownKey = side === "left" ? "battleLeftKey" : "battleRightKey";
  const otherKey = otherSide === "left" ? "battleLeftKey" : "battleRightKey";
  const previous = state[ownKey];
  state[ownKey] = value;
  if (state[ownKey] === state[otherKey]) {
    state[otherKey] = previous;
  }
  state.battle = null;
  loadBattle();
}

function swapBattlePlayers() {
  [state.battleLeftKey, state.battleRightKey] = [state.battleRightKey, state.battleLeftKey];
  state.battle = null;
  loadBattle();
}

async function loadBattle() {
  renderBattleControls();
  if (!state.battleLeftKey || !state.battleRightKey || state.battleLeftKey === state.battleRightKey) {
    state.battle = null;
    renderBattleContent();
    return;
  }

  const requestId = ++state.battleRequestId;
  const signature = battleSignature();
  state.battleLoading = true;
  state.battleError = "";
  renderBattleContent();
  const params = new URLSearchParams({
    left: state.battleLeftKey,
    right: state.battleRightKey,
    range: state.battleRange,
  });
  try {
    const data = await api(`/api/battle?${params}`);
    if (requestId !== state.battleRequestId) return;
    data.signature = signature;
    state.battle = data;
  } catch (error) {
    if (requestId !== state.battleRequestId) return;
    state.battle = null;
    state.battleError = error.message;
  } finally {
    if (requestId === state.battleRequestId) {
      state.battleLoading = false;
      renderBattleContent();
    }
  }
}

function battleEmpty(text, error = false) {
  const empty = el("div", `empty-state battle-empty${error ? " error" : ""}`);
  empty.textContent = text;
  return empty;
}

function renderBattleContent() {
  const container = $("#battleContent");
  container.innerHTML = "";
  const members = state.overview?.members || [];
  if (members.length < 2) {
    container.appendChild(battleEmpty("至少需要两名成员才能开始对战"));
    return;
  }
  if (state.battleLoading) {
    container.appendChild(battleEmpty("正在生成对战数据..."));
    return;
  }
  if (state.battleError) {
    container.appendChild(battleEmpty(state.battleError, true));
    return;
  }
  if (!state.battle || state.battle.signature !== battleSignature()) {
    container.appendChild(battleEmpty("选择两名成员后开始对战"));
    return;
  }

  const data = state.battle;
  container.append(
    renderBattleScoreboard(data),
    renderBattleMetrics(data),
    renderBattleTimeline(data),
    renderBattlePlatforms(data),
    renderSharedContests(data),
  );
}

function playerInitials(name) {
  return Array.from(String(name || "?"))
    .filter((character) => character.trim())
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function renderBattlePlayer(player, side, leading) {
  const panel = el("div", `battle-player ${side}${leading ? " leading" : ""}`);
  const avatar = el("div", "battle-avatar");
  avatar.textContent = playerInitials(player.displayName);
  avatar.setAttribute("aria-hidden", "true");
  const identity = el("div", "battle-player-identity");
  const name = document.createElement("h3");
  name.textContent = player.displayName;
  const meta = document.createElement("p");
  meta.textContent = [player.realName || "", player.teamName || "未分组"].filter(Boolean).join(" · ");
  const handles = el("div", "battle-handles");
  if (player.handles?.length) {
    for (const handle of player.handles) {
      const pill = el("span", "platform-pill");
      pill.textContent = `${handle.platformLabel}:${handle.displayHandle || handle.handle}`;
      handles.appendChild(pill);
    }
  } else {
    const pill = el("span", "platform-pill");
    pill.textContent = "未绑定 OJ";
    handles.appendChild(pill);
  }
  identity.append(name, meta, handles);
  panel.append(avatar, identity);
  return panel;
}

function renderBattleScoreboard(data) {
  const [left, right] = data.players;
  const score = data.headToHead;
  const leftLeading = score.leftWins > score.rightWins;
  const rightLeading = score.rightWins > score.leftWins;
  const section = el("section", "battle-scoreboard");
  const scoreCenter = el("div", "battle-score-center");
  const label = document.createElement("span");
  label.textContent = "共同比赛胜场";
  const value = document.createElement("strong");
  value.textContent = `${score.leftWins} : ${score.rightWins}`;
  const summary = document.createElement("p");
  if (!score.sharedContests) {
    summary.textContent = "当前范围内暂无共同参赛";
  } else if (!score.rankedContests) {
    summary.textContent = `${score.sharedContests} 场共同参赛 · 暂无双方名次`;
  } else if (leftLeading) {
    summary.textContent = `${left.displayName} 领先 · ${score.rankedContests} 场可判胜`;
  } else if (rightLeading) {
    summary.textContent = `${right.displayName} 领先 · ${score.rankedContests} 场可判胜`;
  } else {
    summary.textContent = `暂时打平 · ${score.rankedContests} 场可判胜`;
  }
  scoreCenter.append(label, value, summary);
  section.append(
    renderBattlePlayer(left, "left", leftLeading),
    scoreCenter,
    renderBattlePlayer(right, "right", rightLeading),
  );
  return section;
}

function comparisonValue(value, suffix) {
  return `${Number(value || 0)}${suffix}`;
}

function renderBattleMetricRow(label, leftValue, rightValue, suffix = "") {
  const row = el("div", "battle-metric-row");
  const left = el("div", `battle-metric-value${leftValue > rightValue ? " leading" : ""}`);
  const leftStrong = document.createElement("strong");
  leftStrong.textContent = comparisonValue(leftValue, suffix);
  left.appendChild(leftStrong);
  if (leftValue > rightValue) {
    const mark = document.createElement("span");
    mark.textContent = "领先";
    left.appendChild(mark);
  }
  const name = document.createElement("span");
  name.className = "battle-metric-label";
  name.textContent = label;
  const right = el("div", `battle-metric-value right${rightValue > leftValue ? " leading" : ""}`);
  const rightStrong = document.createElement("strong");
  rightStrong.textContent = comparisonValue(rightValue, suffix);
  right.appendChild(rightStrong);
  if (rightValue > leftValue) {
    const mark = document.createElement("span");
    mark.textContent = "领先";
    right.appendChild(mark);
  }
  row.append(left, name, right);
  return row;
}

function battleSectionHead(titleText, metaText) {
  const head = el("div", "section-head");
  const title = document.createElement("h3");
  title.textContent = titleText;
  const meta = document.createElement("span");
  meta.textContent = metaText;
  head.append(title, meta);
  return head;
}

function renderBattleMetrics(data) {
  const [left, right] = data.players;
  const score = data.headToHead;
  const section = el("section", "battle-section battle-metrics");
  section.appendChild(battleSectionHead("核心数据", data.range.label));
  const grid = el("div", "battle-metric-grid");
  grid.append(
    renderBattleMetricRow("范围内参赛", left.stats.contests, right.stats.contests, " 场"),
    renderBattleMetricRow("Rated 参赛", left.stats.ratedContests, right.stats.ratedContests, " 场"),
    renderBattleMetricRow("共同赛胜场", score.leftWins, score.rightWins, " 场"),
    renderBattleMetricRow("比赛内抢先", score.leftSpeedWins, score.rightSpeedWins, " 题"),
    renderBattleMetricRow("对战指数", left.stats.duelRating, right.stats.duelRating),
  );
  section.appendChild(grid);
  const note = el("p", "battle-data-note");
  note.textContent = "全部指标仅统计比赛记录；Codeforces VP / 场外参赛按比赛表现换算名次，赛后 PRACTICE 补题不参与比较。";
  section.appendChild(note);
  return section;
}

function renderBattlePlatforms(data) {
  const platforms = data.byPlatform || [];
  const section = el("section", "battle-section battle-platforms");
  section.appendChild(battleSectionHead("分平台战绩", `${platforms.length} 个共同参赛平台`));
  if (!platforms.length) {
    section.appendChild(battleEmpty("当前范围内还没有共同参赛平台"));
    return section;
  }
  const max = Math.max(1, ...platforms.flatMap((item) => [item.leftWins, item.rightWins]));
  const rows = el("div", "battle-platform-rows");
  for (const item of platforms) {
    const leftCount = Number(item.leftWins || 0);
    const rightCount = Number(item.rightWins || 0);
    const row = el("div", "battle-platform-row");
    const leftBar = el("div", "battle-bar-side left");
    const leftNumber = document.createElement("strong");
    leftNumber.textContent = leftCount;
    const leftTrack = el("span", "battle-bar-track");
    const leftFill = el("i", "battle-bar-fill");
    leftFill.style.width = `${(leftCount / max) * 100}%`;
    leftTrack.appendChild(leftFill);
    leftBar.append(leftNumber, leftTrack);
    const platform = document.createElement("span");
    platform.className = "battle-platform-label";
    platform.textContent = `${item.platformLabel} · ${item.ranked}/${item.shared} 场可判胜`;
    const rightBar = el("div", "battle-bar-side right");
    const rightTrack = el("span", "battle-bar-track");
    const rightFill = el("i", "battle-bar-fill");
    rightFill.style.width = `${(rightCount / max) * 100}%`;
    rightTrack.appendChild(rightFill);
    const rightNumber = document.createElement("strong");
    rightNumber.textContent = rightCount;
    rightBar.append(rightTrack, rightNumber);
    row.append(leftBar, platform, rightBar);
    rows.appendChild(row);
  }
  section.appendChild(rows);
  return section;
}

function battleSvgElement(name, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function renderBattleTimeline(data) {
  const [left, right] = data.players;
  const timeline = data.timeline || {};
  const points = timeline.points || [];
  const section = el("section", "battle-section battle-timeline-section");
  section.appendChild(battleSectionHead("对战指数趋势", `${points.length} 场按有效名次更新 · K=${timeline.kFactor || 32}`));
  if (!points.length) {
    section.appendChild(battleEmpty("还没有双方都具备官方名次的共同比赛"));
    return section;
  }

  const legend = el("div", "battle-chart-legend");
  for (const [side, player, rating] of [
    ["left", left, timeline.leftRating],
    ["right", right, timeline.rightRating],
  ]) {
    const item = el("span", side);
    const swatch = el("i", "");
    const label = document.createElement("strong");
    label.textContent = `${player.displayName} ${rating}`;
    item.append(swatch, label);
    legend.appendChild(item);
  }

  const width = 840;
  const height = 286;
  const plot = { left: 54, right: 20, top: 24, bottom: 42 };
  const samples = [
    { leftRating: timeline.initialRating || 1500, rightRating: timeline.initialRating || 1500, participatedDate: "起点", contestName: "对战指数起点" },
    ...points,
  ];
  const ratings = samples.flatMap((point) => [point.leftRating, point.rightRating]);
  const minRating = Math.floor((Math.min(...ratings) - 20) / 25) * 25;
  const maxRating = Math.ceil((Math.max(...ratings) + 20) / 25) * 25;
  const range = Math.max(50, maxRating - minRating);
  const x = (index) => plot.left + (index / Math.max(1, samples.length - 1)) * (width - plot.left - plot.right);
  const y = (rating) => plot.top + ((maxRating - rating) / range) * (height - plot.top - plot.bottom);
  const svg = battleSvgElement("svg", {
    class: "battle-chart",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": `${left.displayName} 与 ${right.displayName} 的共同比赛对战指数折线图`,
  });

  for (let index = 0; index <= 4; index += 1) {
    const rating = Math.round(maxRating - (range * index) / 4);
    const lineY = y(rating);
    svg.appendChild(battleSvgElement("line", { class: "battle-chart-grid", x1: plot.left, x2: width - plot.right, y1: lineY, y2: lineY }));
    const label = battleSvgElement("text", { class: "battle-chart-axis", x: plot.left - 10, y: lineY + 4, "text-anchor": "end" });
    label.textContent = rating;
    svg.appendChild(label);
  }

  const linePoints = (key) => samples.map((point, index) => `${x(index)},${y(point[key])}`).join(" ");
  svg.append(
    battleSvgElement("polyline", { class: "battle-chart-line left", points: linePoints("leftRating") }),
    battleSvgElement("polyline", { class: "battle-chart-line right", points: linePoints("rightRating") }),
  );
  for (const [side, key] of [["left", "leftRating"], ["right", "rightRating"]]) {
    samples.forEach((point, index) => {
      const circle = battleSvgElement("circle", { class: `battle-chart-point ${side}`, cx: x(index), cy: y(point[key]), r: 4 });
      const title = battleSvgElement("title");
      title.textContent = `${point.participatedDate} · ${point.contestName} · ${point[key]}`;
      circle.appendChild(title);
      svg.appendChild(circle);
    });
  }
  const labelIndexes = [...new Set([0, Math.floor((samples.length - 1) / 2), samples.length - 1])];
  for (const index of labelIndexes) {
    const label = battleSvgElement("text", { class: "battle-chart-axis date", x: x(index), y: height - 12, "text-anchor": index === 0 ? "start" : index === samples.length - 1 ? "end" : "middle" });
    label.textContent = samples[index].participatedDate;
    svg.appendChild(label);
  }
  const chartWrap = el("div", "battle-chart-wrap");
  chartWrap.appendChild(svg);
  section.append(legend, chartWrap);
  const note = el("p", "battle-data-note");
  note.textContent = "双方从 1500 起步，每场按正式或 VP 等价名次判定胜负并更新指数；它表示这两人之间的交锋走势，不等同于各平台官方 Rating。";
  section.appendChild(note);
  return section;
}

function formatContestElapsed(seconds) {
  if (seconds == null) return "-";
  const value = Math.max(0, Math.floor(Number(seconds)));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}` : `${minutes}:${String(secs).padStart(2, "0")}`;
}

function renderContestResult(result) {
  const cell = el("div", "battle-rank-result");
  const rank = document.createElement("strong");
  const isVirtual = result?.rankKind === "virtual-equivalent";
  rank.textContent = result?.rank != null ? `${isVirtual ? "VP 等价 " : ""}#${result.rank}` : "暂无名次";
  if (isVirtual) rank.title = "根据本次 VP 的得分、罚时和公开正式榜单换算的等价名次";
  cell.appendChild(rank);
  const details = [];
  if (result?.solved != null) details.push(`${result.solved} 题`);
  if (result?.score != null) details.push(`${result.score} 分`);
  if (result?.performance != null) details.push(`表现 ${result.performance}`);
  if (result?.ratingAfter != null && result?.rated) {
    const delta = Number(result.ratingDelta || 0);
    details.push(`Rating ${result.ratingAfter} (${delta >= 0 ? "+" : ""}${delta})`);
  }
  if (details.length) {
    const meta = document.createElement("span");
    meta.textContent = details.join(" · ");
    cell.appendChild(meta);
  }
  return cell;
}

function renderContestSpeed(item, leftName, rightName) {
  const cell = el("div", "battle-speed-result");
  if (!item.speed?.problems) {
    cell.textContent = "暂无比赛内提交时间";
    return cell;
  }
  const score = document.createElement("strong");
  score.textContent = `${item.speed.leftWins} : ${item.speed.rightWins}`;
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = `${item.speed.problems} 题详情`;
  const list = el("div", "battle-problem-duels");
  for (const duel of item.problemDuels || []) {
    const row = el("div", `battle-problem-duel ${duel.winner || ""}`);
    const name = document.createElement("span");
    name.textContent = duel.problemId || duel.problemName || duel.key;
    const times = document.createElement("span");
    times.textContent = `${formatContestElapsed(duel.left?.elapsedSeconds)} / ${formatContestElapsed(duel.right?.elapsedSeconds)}`;
    times.title = `${leftName} / ${rightName}`;
    row.append(name, times);
    list.appendChild(row);
  }
  details.append(summary, list);
  cell.append(score, details);
  return cell;
}

function renderSharedContests(data) {
  const [left, right] = data.players;
  const total = data.headToHead.sharedContests;
  const shown = data.sharedContests?.length || 0;
  const limited = shown < total ? ` · 显示最近 ${shown} 场` : "";
  const section = el("section", "battle-section");
  section.appendChild(battleSectionHead("逐场交锋", `${data.headToHead.rankedContests} 场可判胜 · ${data.headToHead.unrankedContests} 场缺名次${limited}`));
  if (!shown) {
    section.appendChild(battleEmpty("当前范围内暂无共同正式参赛记录"));
    return section;
  }
  const wrap = el("div", "battle-table-wrap shared-contest-table-wrap");
  const table = el("table", "battle-table shared-contest-table");
  const head = document.createElement("thead");
  head.innerHTML = `
    <tr>
      <th class="battle-platform-column">平台</th>
      <th>比赛</th>
      <th class="battle-rank-column">${escapeHtml(left.displayName)} 名次</th>
      <th class="battle-rank-column">${escapeHtml(right.displayName)} 名次</th>
      <th class="battle-speed-column">比赛内抢先</th>
      <th class="battle-result-column">胜负</th>
    </tr>
  `;
  const body = document.createElement("tbody");
  for (const item of data.sharedContests) {
    const row = document.createElement("tr");
    const platform = el("td", "battle-platform-column");
    const badge = el("span", "platform-badge");
    badge.textContent = item.platformLabel || item.platform;
    platform.appendChild(badge);
    const contest = el("td", "problem-cell");
    const link = document.createElement(item.url ? "a" : "span");
    link.className = "submission-link";
    link.textContent = item.contestName || "未命名比赛";
    link.title = link.textContent;
    if (item.url) {
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noreferrer";
    }
    contest.appendChild(link);
    const contestDate = document.createElement("span");
    contestDate.className = "battle-contest-date";
    contestDate.textContent = item.participatedDate || "-";
    contest.appendChild(contestDate);
    const leftRank = el("td", "battle-rank-column");
    leftRank.appendChild(renderContestResult(item.leftResult));
    const rightRank = el("td", "battle-rank-column");
    rightRank.appendChild(renderContestResult(item.rightResult));
    const speed = el("td", "battle-speed-column");
    speed.appendChild(renderContestSpeed(item, left.displayName, right.displayName));
    const result = el("td", "battle-result-column");
    const resultPill = el("span", `battle-result-pill ${item.winner || "unranked"}`);
    if (item.winner === "left") resultPill.textContent = left.displayName;
    else if (item.winner === "right") resultPill.textContent = right.displayName;
    else if (item.winner === "tie") resultPill.textContent = "名次相同";
    else resultPill.textContent = "不计比分";
    result.appendChild(resultPill);
    row.append(platform, contest, leftRank, rightRank, speed, result);
    body.appendChild(row);
  }
  table.append(head, body);
  wrap.appendChild(table);
  const mobileList = el("div", "battle-contest-mobile-list");
  for (const item of data.sharedContests) {
    const match = el("article", "battle-contest-mobile-item");
    const heading = el("div", "battle-contest-mobile-head");
    const badge = el("span", "platform-badge");
    badge.textContent = item.platformLabel || item.platform;
    const title = document.createElement(item.url ? "a" : "span");
    title.textContent = item.contestName || "未命名比赛";
    if (item.url) {
      title.href = item.url;
      title.target = "_blank";
      title.rel = "noreferrer";
    }
    const date = document.createElement("span");
    date.className = "battle-contest-date";
    date.textContent = item.participatedDate || "-";
    heading.append(badge, title, date);

    const comparison = el("div", "battle-contest-mobile-comparison");
    const leftResult = el("div", "left");
    const leftName = document.createElement("span");
    leftName.textContent = left.displayName;
    leftResult.append(leftName, renderContestResult(item.leftResult));
    const outcome = el("div", "outcome");
    const resultPill = el("span", `battle-result-pill ${item.winner || "unranked"}`);
    resultPill.textContent = item.winner === "left" ? left.displayName : item.winner === "right" ? right.displayName : item.winner === "tie" ? "名次相同" : "不计比分";
    outcome.appendChild(resultPill);
    const rightResult = el("div", "right");
    const rightName = document.createElement("span");
    rightName.textContent = right.displayName;
    rightResult.append(rightName, renderContestResult(item.rightResult));
    comparison.append(leftResult, outcome, rightResult);

    const speed = el("div", "battle-contest-mobile-speed");
    const speedLabel = document.createElement("span");
    speedLabel.textContent = "比赛内抢先";
    speed.append(speedLabel, renderContestSpeed(item, left.displayName, right.displayName));
    match.append(heading, comparison, speed);
    mobileList.appendChild(match);
  }
  section.append(wrap, mobileList);
  return section;
}

function memberTeam(member) {
  return member.teamName || (member.ownerType === "guest" ? "游客" : "未分组");
}

function handleSelectionKey(handle) {
  return handleKeyFromParts(handle?.platform, handle?.handle);
}

function handleKeyFromParts(platform, handle) {
  return `${platform || ""}\u001f${handle || ""}`;
}

function selectedHandleKeySetFor(member) {
  const validKeys = new Set((member.handles || []).map(handleSelectionKey));
  for (const key of [...state.selectedHandleKeys]) {
    if (!validKeys.has(key)) state.selectedHandleKeys.delete(key);
  }
  return new Set(state.selectedHandleKeys);
}

function memberActivityView(member) {
  const selectedKeys = selectedHandleKeySetFor(member);
  const selectedHandles = (member.handles || []).filter((handle) => selectedKeys.has(handleSelectionKey(handle)));
  if (!selectedHandles.length) {
    return {
      filtered: false,
      selectedHandleKeys: selectedKeys,
      selectedHandles: [],
      days: member.days || {},
      stats: member.stats || {},
      contests: member.contests || {},
    };
  }

  const activities = selectedHandles.map((handle) => handle.activity || {}).filter(Boolean);
  const days = mergeActivityDays(activities.map((activity) => activity.days || {}));
  return {
    filtered: true,
    selectedHandleKeys: selectedKeys,
    selectedHandles,
    days,
    stats: mergeActivityStats(activities, days),
    contests: {
      items: activities.flatMap((activity) => activity.contests?.items || []),
    },
  };
}

function mergeActivityDays(dayMaps) {
  const merged = {};
  for (const days of dayMaps) {
    for (const [dateKey, counts] of Object.entries(days || {})) {
      const item = merged[dateKey] || { accepted: 0, total: 0 };
      item.accepted += Number(counts.accepted || 0);
      item.total += Number(counts.total || 0);
      merged[dateKey] = item;
    }
  }
  return merged;
}

function mergeActivityStats(activities, days) {
  const activeDates = Object.entries(days || {})
    .filter(([, counts]) => Number(counts.accepted || 0) > 0)
    .map(([dateKey]) => dateKey);
  return {
    accepted: activities.reduce((sum, activity) => sum + Number(activity.stats?.accepted || 0), 0),
    total: activities.reduce((sum, activity) => sum + Number(activity.stats?.total || 0), 0),
    activeDays: activeDates.length,
    streak: currentDateStreak(days, state.overview?.today),
    allTimeAccepted: activities.reduce((sum, activity) => sum + Number(activity.stats?.allTimeAccepted || 0), 0),
    maxStreakAllTime: maxDateStreak(activeDates),
    contests: activities.reduce((sum, activity) => sum + Number(activity.stats?.contests || 0), 0),
  };
}

function currentDateStreak(days, todayString) {
  if (!todayString) return 0;
  let streak = 0;
  const cursor = parseUtcDate(todayString);
  while (true) {
    const key = toDateKey(cursor);
    if (Number(days?.[key]?.accepted || 0) <= 0) return streak;
    streak += 1;
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
}

function toggleMemberHandleFilter(key) {
  if (!key) return;
  if (state.selectedHandleKeys.has(key)) {
    state.selectedHandleKeys.delete(key);
  } else {
    state.selectedHandleKeys.add(key);
  }
  renderMembers();
}

function renderTeamOverview(members) {
  const section = el("section", "team-overview");
  const groups = summarizeTeams(members);
  const selectedGroup = groups.some((group) => group.name === state.memberGroupFilter) ? state.memberGroupFilter : "";
  state.memberGroupFilter = selectedGroup;

  const head = el("div", "section-head");
  const title = document.createElement("h3");
  title.textContent = "分组";
  const meta = document.createElement("span");
  meta.textContent = `${groups.length} 组 · ${members.length} 人`;
  head.append(title, meta);

  const filters = el("div", "team-filters");
  filters.appendChild(teamFilterButton("全部", "", selectedGroup === ""));
  for (const group of groups) {
    filters.appendChild(teamFilterButton(`${group.name} ${group.memberCount}`, group.name, selectedGroup === group.name));
  }

  const grid = el("div", "team-grid");
  for (const group of groups) {
    const card = el("button", `team-card${selectedGroup === group.name ? " active" : ""}`);
    card.type = "button";
    card.dataset.teamFilter = group.name;

    const name = document.createElement("strong");
    name.textContent = group.name;
    const stats = el("div", "team-card-stats");
    stats.innerHTML = `
      <span><b>${group.memberCount}</b> 人</span>
      <span><b>${group.accepted}</b> 历史解题</span>
      <span><b>${group.rangeAccepted}</b> 当前范围解题</span>
      <span><b>${group.contests}</b> 参赛</span>
    `;
    card.append(name, stats);
    grid.appendChild(card);
  }

  section.append(head, filters, grid);
  return section;
}

function teamFilterButton(label, value, active) {
  const button = el("button", `team-filter${active ? " active" : ""}`);
  button.type = "button";
  button.dataset.teamFilter = value;
  button.textContent = label;
  return button;
}

function summarizeTeams(members) {
  const groups = new Map();
  for (const member of members) {
    const name = memberTeam(member);
    const entry = groups.get(name) || {
      name,
      memberCount: 0,
      accepted: 0,
      rangeAccepted: 0,
      contests: 0,
    };
    const periodStats = statsForRange(member.days || {}, state.wallRange, state.overview.today, state.overview.dateRange);
    entry.memberCount += 1;
    entry.accepted += member.stats?.allTimeAccepted ?? member.stats?.accepted ?? 0;
    entry.rangeAccepted += periodStats.accepted;
    entry.contests += contestItemsForRange(member.contests?.items || [], state.wallRange).length;
    groups.set(name, entry);
  }
  return [...groups.values()].sort((a, b) => {
    if (a.name === "未分组") return 1;
    if (b.name === "未分组") return -1;
    if (a.name === "游客") return 1;
    if (b.name === "游客") return -1;
    return b.accepted - a.accepted || a.name.localeCompare(b.name, "zh-CN");
  });
}

function renderMemberDirectory(members) {
  const section = el("section", "member-directory");
  const filteredMembers = state.memberGroupFilter
    ? members.filter((member) => memberTeam(member) === state.memberGroupFilter)
    : members;
  const rangeLabel = state.wallRange === "all" ? "近 10 年" : `${state.wallRange} 年`;

  const head = el("div", "section-head");
  const title = document.createElement("h3");
  title.textContent = "人员列表";
  const meta = document.createElement("span");
  meta.textContent = `${filteredMembers.length} / ${members.length} 人`;
  head.append(title, meta);
  section.appendChild(head);

  if (!filteredMembers.length) {
    const empty = el("div", "empty-state compact");
    empty.textContent = "这个分组里还没有成员";
    section.appendChild(empty);
    return section;
  }

  const wrap = el("div", "member-table-wrap");
  const table = el("table", "member-table");
  const thead = document.createElement("thead");
  thead.innerHTML = `
    <tr>
      <th>成员</th>
      <th>分组</th>
      <th>OJ 账号</th>
      <th>历史解题</th>
      <th>${escapeHtml(rangeLabel)} 解题</th>
      <th>今日</th>
      <th>连续</th>
      <th>参赛</th>
      <th></th>
    </tr>
  `;
  const tbody = document.createElement("tbody");
  const today = state.overview.today;
  for (const member of filteredMembers) {
    const row = document.createElement("tr");
    row.dataset.memberKey = memberKey(member);
    row.tabIndex = 0;

    const name = el("td", "member-cell");
    const nameWrap = el("div", "member-cell-name");
    const strong = document.createElement("strong");
    strong.textContent = member.displayName;
    nameWrap.appendChild(strong);
    if (member.isCurrent) {
      const current = el("span", "current-pill");
      current.textContent = "当前";
      nameWrap.appendChild(current);
    }
    name.appendChild(nameWrap);
    if (member.realName) {
      const realName = el("span", "member-real-name");
      realName.textContent = member.realName;
      name.appendChild(realName);
    }

    const team = document.createElement("td");
    const teamPill = el("span", "team-pill");
    teamPill.textContent = memberTeam(member);
    team.appendChild(teamPill);

    const handles = el("td", "member-handles-cell");
    handles.textContent = member.handles?.length
      ? member.handles.map((handle) => `${handle.platformLabel}:${handle.displayHandle || handle.handle}`).join(" / ")
      : "未绑定";
    handles.title = handles.textContent;

    const periodStats = statsForRange(member.days || {}, state.wallRange, state.overview.today, state.overview.dateRange);
    const contestCount = contestItemsForRange(member.contests?.items || [], state.wallRange).length;
    const values = [
      member.stats?.allTimeAccepted ?? member.stats?.accepted ?? 0,
      periodStats.accepted,
      member.days?.[today]?.accepted || 0,
      `${member.stats?.streak ?? 0} 天`,
      contestCount,
    ].map((value) => {
      const td = el("td", "metric-cell");
      td.textContent = value;
      return td;
    });

    const action = el("td", "member-action-cell");
    const actionText = el("span", "detail-link");
    actionText.textContent = "查看";
    action.appendChild(actionText);

    row.append(name, team, handles, ...values, action);
    tbody.appendChild(row);
  }
  table.append(thead, tbody);
  wrap.appendChild(table);
  section.appendChild(wrap);
  return section;
}

function renderMemberDetail(member) {
  const view = memberActivityView(member);
  const detail = el("div", "member-detail-view");
  const bar = el("div", "member-detail-bar");
  const back = el("button", "button ghost");
  back.type = "button";
  back.dataset.backMembers = "true";
  back.textContent = "返回列表";

  const title = el("div", "member-detail-title");
  const h3 = document.createElement("h3");
  h3.textContent = member.displayName;
  const meta = document.createElement("span");
  meta.textContent = [
    member.realName ? `姓名：${member.realName}` : "",
    memberTeam(member),
    view.filtered ? `${view.selectedHandles.length}/${member.handles?.length || 0} 个 OJ 账号` : `${member.handles?.length || 0} 个 OJ 账号`,
  ].filter(Boolean).join(" · ");
  title.append(h3, meta);

  bar.append(back, title);
  detail.append(bar, renderMemberCard(member, view), renderMemberSubmissions(member, view));
  return detail;
}

function renderMemberSubmissions(member, view = memberActivityView(member)) {
  const section = el("section", "member-submissions");
  const rows = (state.overview?.feed || [])
    .filter((item) => item.ownerType === member.ownerType && String(item.ownerId) === String(member.ownerId))
    .filter((item) => !view.filtered || view.selectedHandleKeys.has(handleKeyFromParts(item.platform, item.handle)))
    .slice(0, 50);

  const head = el("div", "section-head");
  const title = document.createElement("h3");
  title.textContent = "该成员最近提交";
  const meta = document.createElement("span");
  meta.textContent = rows.length ? `最近 ${rows.length} 条` : "暂无记录";
  head.append(title, meta);
  section.appendChild(head);

  if (!rows.length) {
    const empty = el("div", "empty-state compact");
    empty.textContent = view.filtered ? "选中的账号还没有最近提交记录" : "这个成员还没有提交记录";
    section.appendChild(empty);
    return section;
  }

  const wrap = el("div", "member-feed-wrap");
  const table = el("table", "feed-table member-feed-table");
  const thead = document.createElement("thead");
  thead.innerHTML = `
    <tr>
      <th class="feed-time">提交时间</th>
      <th class="feed-platform">平台</th>
      <th class="feed-account">账户</th>
      <th>题目</th>
      <th class="feed-language">语言</th>
      <th class="feed-result">结果</th>
    </tr>
  `;
  const tbody = document.createElement("tbody");
  for (const item of rows) {
    const row = document.createElement("tr");

    const time = el("td", "feed-time");
    time.textContent = formatFullDateTime(item.submittedAt);

    const platform = el("td", "feed-platform");
    const platformLabel = el("span", "platform-badge");
    platformLabel.textContent = item.platformLabel || item.platform;
    platform.appendChild(platformLabel);

    const account = el("td", "feed-account account-cell");
    account.textContent = item.handle || member.displayName || "";
    account.title = account.textContent;

    const problem = el("td", "problem-cell");
    const problemLink = document.createElement(item.url ? "a" : "span");
    problemLink.className = "submission-link";
    problemLink.textContent = item.problemName || item.problemId || "未知题目";
    problemLink.title = problemLink.textContent;
    if (item.url) {
      problemLink.href = item.url;
      problemLink.target = "_blank";
      problemLink.rel = "noreferrer";
    }
    problem.appendChild(problemLink);

    const language = el("td", "feed-language account-cell");
    language.textContent = item.language || "-";
    language.title = item.language || "";

    const result = el("td", "feed-result");
    const verdict = el("span", `verdict ${verdictClass(item.verdict)}`);
    verdict.textContent = verdictLabel(item.verdict);
    verdict.title = item.verdict || "UNKNOWN";
    result.appendChild(verdict);

    row.append(time, platform, account, problem, language, result);
    tbody.appendChild(row);
  }
  table.append(thead, tbody);
  wrap.appendChild(table);
  section.appendChild(wrap);
  return section;
}

function renderMemberCard(member, view = memberActivityView(member)) {
  const card = el("article", "member-card");
  const head = el("div", "member-head");
  const identity = el("div");
  const name = el("div", "member-name");
  const h3 = document.createElement("h3");
  h3.textContent = member.displayName;
  name.appendChild(h3);
  if (member.isCurrent) {
    const pill = el("span", "current-pill");
    pill.textContent = "当前";
    name.appendChild(pill);
  }
  identity.appendChild(name);
  if (member.realName) {
    const realName = el("div", "member-card-real-name");
    realName.textContent = `姓名：${member.realName}`;
    identity.appendChild(realName);
  }

  const handles = el("div", "member-handles");
  if (member.handles?.length) {
    for (const handle of member.handles) {
      const selected = view.selectedHandleKeys.has(handleSelectionKey(handle));
      const pill = el(
        "button",
        `platform-pill handle-filter-pill${selected ? " active" : ""}${view.filtered && !selected ? " inactive" : ""}${handle.lastError ? " error" : ""}`,
      );
      pill.type = "button";
      pill.dataset.memberHandleKey = handleSelectionKey(handle);
      pill.setAttribute("aria-pressed", selected ? "true" : "false");
      pill.title = handle.lastError || `${handle.platformLabel}:${handle.displayHandle || handle.handle}`;
      pill.textContent = `${handle.platformLabel}:${handle.displayHandle || handle.handle}`;
      handles.appendChild(pill);
    }
  } else {
    const pill = el("span", "platform-pill");
    pill.textContent = "未绑定";
    handles.appendChild(pill);
  }
  identity.appendChild(handles);

  head.appendChild(identity);
  const wallWrap = el("div", "wall-wrap");
  wallWrap.appendChild(renderWall(view.days || {}, state.wallRange, state.overview.today, state.overview.dateRange));
  card.append(
    head,
    wallWrap,
    renderActivityStats(view.days || {}, view.stats || {}, state.wallRange),
    renderContestStats(view.contests || {}, state.wallRange),
  );
  return card;
}

function renderWall(days, range, todayString, dateRange) {
  const activity = el("div", "activity-wall");
  const months = el("div", "wall-months");
  const body = el("div", "wall-body");
  const weekdays = el("div", "wall-weekdays");
  const wall = el("div", "wall");
  const today = parseUtcDate(todayString);
  const bounds = wallBounds(range, today, dateRange);
  const lower = bounds.lower;
  const upper = bounds.upper;
  const visibleUpper = bounds.visibleUpper;
  const shape = wallShape(range);
  const start = new Date(lower);
  if (!shape.compact) {
    start.setUTCDate(start.getUTCDate() - start.getUTCDay());
  }
  const columnCount = Math.ceil(((upper - start) / 86400000 + 1) / shape.rows);
  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  let lastMonth = -1;
  let lastYear = -1;

  activity.classList.toggle("compact-wall", shape.compact);
  months.style.gridTemplateColumns = `repeat(${columnCount}, var(--wall-cell))`;
  weekdays.style.gridTemplateRows = `repeat(${shape.rows}, var(--wall-cell))`;
  wall.style.gridTemplateRows = `repeat(${shape.rows}, var(--wall-cell))`;

  for (let column = 0; column < columnCount; column += 1) {
    if (shape.compact) {
      const date = new Date(start);
      date.setUTCDate(start.getUTCDate() + column * shape.rows);
      if (date <= upper && (column === 0 || date.getUTCFullYear() !== lastYear)) {
        const label = document.createElement("span");
        label.textContent = String(date.getUTCFullYear());
        label.style.gridColumn = String(column + 1);
        months.appendChild(label);
        lastYear = date.getUTCFullYear();
      }
      continue;
    }
    for (let day = 0; day < shape.rows; day += 1) {
      const date = new Date(start);
      date.setUTCDate(start.getUTCDate() + column * shape.rows + day);
      if (date < lower || date > upper) continue;
      if (date.getUTCMonth() !== lastMonth && date.getUTCDate() <= 7) {
        const label = document.createElement("span");
        label.textContent = monthNames[date.getUTCMonth()];
        label.style.gridColumn = String(column + 1);
        months.appendChild(label);
        lastMonth = date.getUTCMonth();
        break;
      }
    }
  }

  const weekdayLabels = shape.compact
    ? Array.from({ length: shape.rows }, (_, index) => ({ 0: "1", 6: "7", 13: "14", 20: "21", 27: "28" }[index] || ""))
    : ["", "Mon", "", "Wed", "", "Fri", ""];
  for (const label of weekdayLabels) {
    const item = document.createElement("span");
    item.textContent = label;
    weekdays.appendChild(item);
  }

  for (let i = 0; i < columnCount * shape.rows; i += 1) {
    const date = new Date(start);
    date.setUTCDate(start.getUTCDate() + i);
    const key = toDateKey(date);
    const counts = days[key] || { accepted: 0, total: 0 };
    const cell = el("div", `day-cell level-${levelFor(counts.accepted)}`);
    if (date < lower || date > visibleUpper) {
      cell.style.visibility = "hidden";
    }
    cell.title = `${key}：解题 ${counts.accepted || 0}，提交 ${counts.total || 0}`;
    wall.appendChild(cell);
  }

  body.append(weekdays, wall);
  activity.append(months, body);
  return activity;
}

function wallShape(range) {
  if (range === "all") {
    return { rows: 28, compact: true };
  }
  return { rows: 7, compact: false };
}

function renderActivityStats(days, stats, range) {
  const panel = el("div", "activity-stats");
  const periodStats = statsForRange(days, range, state.overview?.today, state.overview?.dateRange);
  const periodLabel = range === "all" ? "近 10 年" : `${range}`;
  const items = [
    [stats.allTimeAccepted ?? stats.accepted ?? 0, "历史解题"],
    [periodStats.accepted, `${periodLabel} 解题`],
    [periodStats.total, `${periodLabel} 提交`],
    [`${periodStats.activeDays} 天`, `${periodLabel} 活跃`],
    [`${periodStats.maxStreak} 天`, `${periodLabel} 最长连续`],
    [`${stats.streak ?? 0} 天`, "当前连续"],
  ];
  for (const [value, label] of items) {
    const item = document.createElement("div");
    const strong = document.createElement("strong");
    const span = document.createElement("span");
    strong.textContent = value;
    span.textContent = label;
    item.append(strong, span);
    panel.appendChild(item);
  }
  return panel;
}

function renderContestStats(contests, range) {
  const section = el("div", "contest-stats");
  const items = contestItemsForRange(contests.items || [], range);
  const summary = summarizeContestItems(items);
  const periodLabel = range === "all" ? "近 10 年" : `${range} 年`;

  const head = el("div", "contest-stats-head");
  const title = document.createElement("strong");
  title.textContent = "比赛统计";
  const meta = document.createElement("span");
  meta.textContent = `${periodLabel} ${summary.total} 场`;
  head.append(title, meta);
  section.appendChild(head);

  if (!summary.total) {
    const empty = el("div", "contest-empty");
    empty.textContent = "这个范围暂无比赛记录";
    section.appendChild(empty);
    return section;
  }

  const groups = el("div", "contest-platform-groups");
  for (const platform of summary.byPlatform) {
    const group = el("section", "contest-platform-group");
    const groupHead = el("div", "contest-platform-group-head");
    const name = document.createElement("strong");
    const count = document.createElement("span");
    name.textContent = platform.platformLabel;
    count.textContent = `${platform.count} 场`;
    groupHead.append(name, count);

    const grid = el("div", "contest-category-grid");
    for (const item of platform.categories) {
      const node = el("div", "contest-category");
      const categoryCount = document.createElement("strong");
      const label = document.createElement("span");
      categoryCount.textContent = item.count;
      label.textContent = item.label;
      node.append(categoryCount, label);
      grid.appendChild(node);
    }
    group.append(groupHead, grid);
    groups.appendChild(group);
  }
  section.appendChild(groups);
  return section;
}

function contestItemsForRange(items, range) {
  const today = parseUtcDate(state.overview?.today);
  const bounds = wallBounds(range, today, state.overview?.dateRange);
  return items.filter((item) => {
    if (!item.participatedDate) return false;
    const date = parseUtcDate(item.participatedDate);
    return date >= bounds.lower && date <= bounds.visibleUpper;
  });
}

function summarizeContestItems(items) {
  const byPlatform = new Map();
  for (const item of items) {
    const platform = item.platform || "other";
    const platformEntry = byPlatform.get(platform) || {
      platform,
      platformLabel: item.platformLabel || platform,
      count: 0,
      categories: new Map(),
    };
    platformEntry.count += 1;

    const category = item.category || "other";
    const categoryEntry = platformEntry.categories.get(category) || {
      category,
      label: item.categoryLabel || category,
      count: 0,
    };
    categoryEntry.count += 1;
    platformEntry.categories.set(category, categoryEntry);
    byPlatform.set(platform, platformEntry);
  }
  const platforms = [...byPlatform.values()].map((platform) => ({
    ...platform,
    categories: [...platform.categories.values()].sort(compareContestCategories),
  }));
  return {
    total: items.length,
    byPlatform: platforms.sort(compareContestPlatforms),
  };
}

function compareContestPlatforms(a, b) {
  const rankA = CONTEST_PLATFORM_RANK.get(a.platform) ?? 999;
  const rankB = CONTEST_PLATFORM_RANK.get(b.platform) ?? 999;
  return rankA - rankB || a.platformLabel.localeCompare(b.platformLabel, "zh-CN");
}

function compareContestCategories(a, b) {
  const rankA = CONTEST_CATEGORY_RANK.get(a.category) ?? 999;
  const rankB = CONTEST_CATEGORY_RANK.get(b.category) ?? 999;
  return rankA - rankB || b.count - a.count || a.label.localeCompare(b.label, "zh-CN");
}

function wallBounds(range, today, dateRange) {
  if (range === "all") {
    return {
      lower: new Date(Date.UTC(today.getUTCFullYear() - 9, 0, 1)),
      upper: new Date(Date.UTC(today.getUTCFullYear(), 11, 31)),
      visibleUpper: today,
    };
  }
  const year = Number(range) || today.getUTCFullYear();
  const upper = new Date(Date.UTC(year, 11, 31));
  return {
    lower: new Date(Date.UTC(year, 0, 1)),
    upper,
    visibleUpper: year === today.getUTCFullYear() ? today : upper,
  };
}

function statsForRange(days, range, todayString, dateRange) {
  const today = parseUtcDate(todayString);
  const bounds = wallBounds(range, today, dateRange);
  let accepted = 0;
  let total = 0;
  const activeDates = [];
  for (const [dateKey, counts] of Object.entries(days || {})) {
    const date = parseUtcDate(dateKey);
    if (date < bounds.lower || date > bounds.visibleUpper) continue;
    accepted += counts.accepted || 0;
    total += counts.total || 0;
    if ((counts.accepted || 0) > 0) activeDates.push(dateKey);
  }
  return {
    accepted,
    total,
    activeDays: activeDates.length,
    maxStreak: maxDateStreak(activeDates),
  };
}

function maxDateStreak(dateKeys) {
  const dates = dateKeys
    .map((key) => parseUtcDate(key))
    .sort((a, b) => a - b);
  let longest = 0;
  let streak = 0;
  let previous = null;
  for (const date of dates) {
    if (previous && Math.round((date - previous) / 86400000) === 1) {
      streak += 1;
    } else {
      streak = 1;
    }
    longest = Math.max(longest, streak);
    previous = date;
  }
  return longest;
}

function levelFor(count) {
  if (!count) return 0;
  if (count === 1) return 1;
  if (count <= 3) return 2;
  if (count <= 6) return 3;
  return 4;
}

function renderFeed() {
  renderFeedControls();
  const feed = $("#feed");
  feed.innerHTML = "";
  const rows = filteredFeedRows();
  const pageSize = state.feedPageSize;
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  state.feedPage = Math.min(Math.max(1, state.feedPage), totalPages);
  const startIndex = (state.feedPage - 1) * pageSize;
  const pageRows = rows.slice(startIndex, startIndex + pageSize);
  renderFeedPagination(rows.length, totalPages, startIndex, pageRows.length);

  if (!rows.length) {
    const empty = el("div", "empty-state");
    empty.textContent = "没有符合筛选条件的提交";
    feed.appendChild(empty);
    return;
  }

  const table = el("table", "feed-table");
  const head = document.createElement("thead");
  head.innerHTML = `
    <tr>
      <th class="feed-time">提交时间</th>
      <th class="feed-platform">平台</th>
      <th class="feed-user">用户</th>
      <th class="feed-account">账户</th>
      <th>题目</th>
      <th class="feed-language">语言</th>
      <th class="feed-result">结果</th>
    </tr>
  `;
  const body = document.createElement("tbody");

  for (const item of pageRows) {
    const row = document.createElement("tr");

    const time = el("td", "feed-time");
    time.textContent = formatFullDateTime(item.submittedAt);

    const platform = el("td", "feed-platform");
    const platformLabel = el("span", "platform-badge");
    platformLabel.textContent = item.platformLabel || item.platform;
    platform.appendChild(platformLabel);

    const user = el("td", "feed-user account-cell");
    user.textContent = item.displayName || "";
    user.title = user.textContent;

    const account = el("td", "feed-account account-cell");
    account.textContent = item.handle || item.displayName || "";
    account.title = account.textContent;

    const problem = el("td", "problem-cell");
    const title = document.createElement(item.url ? "a" : "span");
    title.className = "submission-link";
    title.textContent = item.problemName || item.problemId || "未知题目";
    title.title = title.textContent;
    if (item.url) {
      title.href = item.url;
      title.target = "_blank";
      title.rel = "noreferrer";
    }
    problem.appendChild(title);

    const language = el("td", "feed-language account-cell");
    language.textContent = item.language || "-";
    language.title = item.language || "";

    const result = el("td", "feed-result");
    const verdict = el("span", `verdict ${verdictClass(item.verdict)}`);
    verdict.textContent = verdictLabel(item.verdict);
    verdict.title = item.verdict || "UNKNOWN";
    result.appendChild(verdict);

    row.append(time, platform, user, account, problem, language, result);
    body.appendChild(row);
  }

  table.append(head, body);
  feed.appendChild(table);
}

function renderFeedControls() {
  const rows = state.overview?.feed || [];
  populateSelect(
    $("#feedPlatformFilter"),
    uniqueOptions(rows, (item) => item.platform, (item) => item.platformLabel || item.platform),
    "全部平台",
    state.feedFilters.platform,
  );
  populateSelect(
    $("#feedLanguageFilter"),
    uniqueOptions(rows, (item) => item.language || "", (item) => item.language || "未知语言"),
    "全部语言",
    state.feedFilters.language,
  );
  populateSelect(
    $("#feedVerdictFilter"),
    uniqueOptions(rows, (item) => verdictFilterKey(item.verdict), (item) => verdictFilterKey(item.verdict)),
    "全部状态",
    state.feedFilters.verdict,
  );
  $("#feedUserFilter").value = state.feedFilters.user;
  const range = state.overview?.dateRange || {};
  for (const input of [$("#feedDateFrom"), $("#feedDateTo")]) {
    input.min = range.min || "";
    input.max = range.max || "";
  }
  $("#feedDateFrom").value = state.feedFilters.from || "";
  $("#feedDateTo").value = state.feedFilters.to || "";
  $("#feedPageSize").value = String(state.feedPageSize);
}

function uniqueOptions(rows, valueGetter, labelGetter) {
  const seen = new Map();
  for (const item of rows) {
    const value = String(valueGetter(item) || "").trim();
    if (!value || seen.has(value)) continue;
    seen.set(value, String(labelGetter(item) || value));
  }
  return [...seen.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
}

function populateSelect(select, options, allLabel, selectedValue) {
  const value = options.some((option) => option.value === selectedValue) ? selectedValue : "";
  select.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = allLabel;
  select.appendChild(all);
  for (const option of options) {
    const node = document.createElement("option");
    node.value = option.value;
    node.textContent = option.label;
    select.appendChild(node);
  }
  select.value = value;
  if (selectedValue && !value) {
    const keys = {
      feedPlatformFilter: "platform",
      feedLanguageFilter: "language",
      feedVerdictFilter: "verdict",
    };
    const key = keys[select.id];
    if (!key) return;
    state.feedFilters[key] = "";
  }
}

function filteredFeedRows() {
  const filters = state.feedFilters;
  const userQuery = filters.user.trim().toLowerCase();
  const visibleNames = new Map((state.overview?.members || []).map((member) => [memberKey(member), member.realName || ""]));
  return (state.overview?.feed || []).filter((item) => {
    if (filters.platform && item.platform !== filters.platform) return false;
    if (filters.language && item.language !== filters.language) return false;
    if (filters.verdict && verdictFilterKey(item.verdict) !== filters.verdict) return false;
    if (filters.from && item.submittedDate < filters.from) return false;
    if (filters.to && item.submittedDate > filters.to) return false;
    if (userQuery) {
      const realName = visibleNames.get(`${item.ownerType}:${item.ownerId}`) || "";
      const haystack = `${item.displayName || ""} ${realName} ${item.handle || ""} ${item.displayHandle || ""} ${item.ownerId || ""}`.toLowerCase();
      if (!haystack.includes(userQuery)) return false;
    }
    return true;
  });
}

function renderFeedPagination(totalRows, totalPages, startIndex, pageCount) {
  const from = totalRows ? startIndex + 1 : 0;
  const to = totalRows ? startIndex + pageCount : 0;
  $("#feedSummary").textContent = `${from}-${to} / ${totalRows} 条`;
  $("#feedPageInput").value = String(state.feedPage);
  $("#feedPageInput").max = String(totalPages);
  $("#feedPageTotal").textContent = `/ ${totalPages} 页`;
  $("#feedPrevPage").disabled = state.feedPage <= 1;
  $("#feedNextPage").disabled = state.feedPage >= totalPages;
}

function updateFeedFilter(key, value) {
  state.feedFilters[key] = value;
  state.feedPage = 1;
  renderFeed();
}

function setFeedPage(page) {
  const rows = filteredFeedRows();
  const totalPages = Math.max(1, Math.ceil(rows.length / state.feedPageSize));
  state.feedPage = Math.min(Math.max(1, page), totalPages);
  renderFeed();
}

function resetFeedFilters() {
  state.feedFilters = {
    platform: "",
    user: "",
    language: "",
    verdict: "",
    from: "",
    to: "",
  };
  state.feedPage = 1;
  renderFeed();
}

function verdictLabel(verdict) {
  const value = String(verdict || "").toUpperCase();
  const aliases = {
    WRONG_ANSWER: "WA",
    RUNTIME_ERROR: "RE",
    COMPILATION_ERROR: "CE",
    TIME_LIMIT_EXCEEDED: "TLE",
    MEMORY_LIMIT_EXCEEDED: "MLE",
    PRESENTATION_ERROR: "PE",
    OUTPUT_LIMIT_EXCEEDED: "OLE",
    答案错误: "WA",
    编译错误: "CE",
    运行错误: "RE",
    超时: "TLE",
    部分正确: "部分正确",
    SUBMITTED: "提交",
  };
  return aliases[value] || value || "UNKNOWN";
}

function verdictFilterKey(verdict) {
  return verdictLabel(verdict);
}

function verdictClass(verdict) {
  const value = verdictFilterKey(verdict);
  if (value === "AC") return "ac";
  if (
    value === "WA" ||
    value === "RE" ||
    value === "CE" ||
    value.includes("WRONG") ||
    value.includes("ERROR") ||
    value.includes("TLE") ||
    value.includes("MLE") ||
    value.includes("答案错误")
  ) {
    return "bad";
  }
  return "";
}

function parseUtcDate(value) {
  return new Date(`${value}T00:00:00Z`);
}

function toDateKey(date) {
  return date.toISOString().slice(0, 10);
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: DISPLAY_TIME_ZONE,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatFullDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: DISPLAY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date).replaceAll("/", "-");
}

async function submitGuest(event) {
  event.preventDefault();
  clearMessage();
  const form = new FormData(event.currentTarget);
  try {
    await api("/api/guest", {
      method: "POST",
      body: {
        displayName: form.get("displayName"),
        realName: form.get("realName"),
        teamName: form.get("teamName"),
      },
    });
    await loadOverview();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

async function submitLogin(event) {
  event.preventDefault();
  clearMessage();
  const form = new FormData(event.currentTarget);
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: {
        username: form.get("username"),
        password: form.get("password"),
      },
    });
    await loadOverview();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

async function submitRegister(event) {
  event.preventDefault();
  clearMessage();
  const form = new FormData(event.currentTarget);
  try {
    const data = await api("/api/auth/register", {
      method: "POST",
      body: {
        username: form.get("username"),
        displayName: form.get("displayName"),
        realName: form.get("realName"),
        teamName: form.get("teamName"),
        password: form.get("password"),
      },
    });
    await loadOverview();
    showMessage(data.message || "注册成功，已登录。");
  } catch (error) {
    showMessage(error.message, "error");
  }
}

async function submitProfile(event) {
  event.preventDefault();
  clearMessage();
  const form = new FormData(event.currentTarget);
  try {
    const data = await api("/api/me/profile", {
      method: "POST",
      body: {
        displayName: form.get("displayName"),
        realName: form.get("realName"),
        teamName: form.get("teamName"),
      },
    });
    state.user = data.user;
    await loadOverview();
    showMessage("资料已更新。");
  } catch (error) {
    showMessage(error.message, "error");
  }
}

async function submitHandle(event) {
  event.preventDefault();
  clearMessage();
  if (state.binding) return;
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const submitButton = formElement.querySelector('button[type="submit"]');
  const originalText = submitButton ? submitButton.textContent : "";
  state.binding = true;
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.textContent = "保存中...";
  }
  showMessage("正在保存绑定，提交记录会在后台同步。");
  setBusy(true);
  try {
    const data = await api("/api/handles", {
      method: "POST",
      body: {
        platform: form.get("platform"),
        handle: form.get("handle"),
      },
    });
    formElement.reset();
    updateHandleHint();
    applyOverviewData(data);
    showMessage("绑定已保存，已加入后台同步队列。");
    scheduleOverviewPoll();
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    state.binding = false;
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = originalText || "绑定账号";
    }
    setBusy(false);
  }
}

async function refreshSync() {
  clearMessage();
  if (!state.user) {
    showMessage("请先登录或用游客模式进入，再触发同步。", "error");
    return;
  }
  setBusy(true);
  try {
    const data = await api("/api/sync", {
      method: "POST",
      body: { force: true },
    });
    applyOverviewData(data);
    const queued = (data.results || []).some((item) => item.queued || item.alreadyQueued);
    showMessage(queued ? "已加入后台同步队列。" : "后台同步请求已提交。");
    scheduleOverviewPoll();
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function logout() {
  clearMessage();
  await api("/api/auth/logout", { method: "POST", body: {} }).catch(() => {});
  state.user = null;
  await loadOverview();
}

async function removeHandle(id) {
  clearMessage();
  if (state.handleBusy.has(String(id))) return;
  setHandleBusy(id, true);
  try {
    await api(`/api/handles/${encodeURIComponent(id)}`, { method: "DELETE" });
    await loadOverview();
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    setHandleBusy(id, false);
  }
}

async function retryHandle(id) {
  clearMessage();
  if (state.handleBusy.has(String(id))) return;
  setHandleBusy(id, true);
  try {
    const data = await api(`/api/handles/${encodeURIComponent(id)}/sync`, {
      method: "POST",
      body: {},
    });
    applyOverviewData(data);
    const result = data.result || {};
    showMessage(result.alreadyQueued ? "这个账号已经在同步队列里。" : "已加入后台同步队列。");
    scheduleOverviewPoll();
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    setHandleBusy(id, false);
  }
}

function bindEvents() {
  $("#overviewTab").addEventListener("click", () => switchMainView("overview"));
  $("#battleTab").addEventListener("click", () => switchMainView("battle"));
  $(".main-view-tabs").addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const nextView = state.mainView === "overview" ? "battle" : "overview";
    switchMainView(nextView);
    $(`#${nextView}Tab`).focus();
  });
  $("#battleLeftSelect").addEventListener("change", (event) => selectBattlePlayer("left", event.currentTarget.value));
  $("#battleRightSelect").addEventListener("change", (event) => selectBattlePlayer("right", event.currentTarget.value));
  $("#battleSwapBtn").addEventListener("click", swapBattlePlayers);
  $("#battleRangeSelect").addEventListener("change", (event) => {
    state.battleRange = event.currentTarget.value;
    state.battle = null;
    loadBattle();
  });
  $("#guestTab").addEventListener("click", () => switchAuthTab("guest"));
  $("#loginTab").addEventListener("click", () => switchAuthTab("login"));
  $("#registerTab").addEventListener("click", () => switchAuthTab("register"));
  $("#guestForm").addEventListener("submit", submitGuest);
  $("#loginForm").addEventListener("submit", submitLogin);
  $("#registerForm").addEventListener("submit", submitRegister);
  $("#profileForm").addEventListener("submit", submitProfile);
  $("#handleForm").addEventListener("submit", submitHandle);
  $("#platformSelect").addEventListener("change", updateHandleHint);
  $("#refreshBtn").addEventListener("click", refreshSync);
  $("#logoutBtn").addEventListener("click", logout);
  $("#wallYearSelect").addEventListener("change", (event) => {
    state.wallRange = event.currentTarget.value;
    renderMembers();
  });
  $("#members").addEventListener("click", (event) => {
    const back = event.target.closest("[data-back-members]");
    if (back) {
      state.selectedMemberKey = "";
      state.selectedHandleKeys.clear();
      renderMembers();
      return;
    }
    const handle = event.target.closest("[data-member-handle-key]");
    if (handle) {
      toggleMemberHandleFilter(handle.dataset.memberHandleKey);
      return;
    }
    const team = event.target.closest("[data-team-filter]");
    if (team) {
      state.memberGroupFilter = team.dataset.teamFilter || "";
      renderMembers();
      return;
    }
    const row = event.target.closest("[data-member-key]");
    if (row) {
      if (state.selectedMemberKey !== row.dataset.memberKey) state.selectedHandleKeys.clear();
      state.selectedMemberKey = row.dataset.memberKey;
      renderMembers();
    }
  });
  $("#members").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("[data-member-key]");
    if (!row) return;
    event.preventDefault();
    if (state.selectedMemberKey !== row.dataset.memberKey) state.selectedHandleKeys.clear();
    state.selectedMemberKey = row.dataset.memberKey;
    renderMembers();
  });
  $("#feedPlatformFilter").addEventListener("change", (event) => updateFeedFilter("platform", event.currentTarget.value));
  $("#feedUserFilter").addEventListener("input", (event) => updateFeedFilter("user", event.currentTarget.value));
  $("#feedLanguageFilter").addEventListener("change", (event) => updateFeedFilter("language", event.currentTarget.value));
  $("#feedVerdictFilter").addEventListener("change", (event) => updateFeedFilter("verdict", event.currentTarget.value));
  $("#feedDateFrom").addEventListener("change", (event) => updateFeedFilter("from", event.currentTarget.value));
  $("#feedDateTo").addEventListener("change", (event) => updateFeedFilter("to", event.currentTarget.value));
  $("#feedResetFilters").addEventListener("click", resetFeedFilters);
  $("#feedPrevPage").addEventListener("click", () => setFeedPage(state.feedPage - 1));
  $("#feedNextPage").addEventListener("click", () => setFeedPage(state.feedPage + 1));
  $("#feedJumpPage").addEventListener("click", () => setFeedPage(Number($("#feedPageInput").value) || 1));
  $("#feedPageInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      setFeedPage(Number(event.currentTarget.value) || 1);
    }
  });
  $("#feedPageSize").addEventListener("change", (event) => {
    state.feedPageSize = Number(event.currentTarget.value) || 25;
    state.feedPage = 1;
    renderFeed();
  });
  $("#myHandles").addEventListener("click", (event) => {
    const retry = event.target.closest("button[data-retry-handle-id]");
    if (retry) {
      retryHandle(retry.dataset.retryHandleId);
      return;
    }
    const button = event.target.closest("button[data-handle-id]");
    if (button) removeHandle(button.dataset.handleId);
  });
}

async function init() {
  bindEvents();
  hydrateOverviewFromBrowserCache();
  try {
    await loadSession();
    await loadOverview();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

init();
