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
  memberGroupFilter: "",
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
  $("#refreshBtn").textContent = value ? "同步中..." : "刷新同步";
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

async function loadOverview() {
  const data = await api("/api/overview?days=365");
  state.overview = data;
  state.user = data.user;
  if (data.platforms) state.platforms = data.platforms;
  const validRanges = ["all", ...(data.availableYears || []).map(String)];
  if (!state.wallRange || !validRanges.includes(String(state.wallRange))) {
    state.wallRange = String(data.availableYears?.[0] || new Date().getFullYear());
  }
  renderAll();
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
  $("#memberCount").textContent = members.length;
  $("#todayCount").textContent = todayAccepted;
  $("#feedCount").textContent = overview.feed?.length || 0;
  $("#contestCount").textContent = contestTotal;
  const mirror = overview.mirror || {};
  const generatedAt = mirror.generatedAt || overview.now;
  const asOf = mirror.asOf;
  if (mirror.fallback) {
    $("#lastUpdated").textContent = `本地镜像 · 数据截至 ${asOf ? formatDateTime(asOf) : "未知"} · 读取于 ${formatDateTime(mirror.servedAt || generatedAt)}`;
  } else if (asOf) {
    $("#lastUpdated").textContent = `更新于 ${formatDateTime(generatedAt)} · 数据截至 ${formatDateTime(asOf)}`;
  } else {
    $("#lastUpdated").textContent = generatedAt ? `更新于 ${formatDateTime(generatedAt)}` : "等待同步";
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
    const row = el("div", "handle-item");
    const main = el("div", "handle-main");
    const title = document.createElement("strong");
    title.textContent = `${item.platformLabel} / ${item.handle}`;
    const meta = document.createElement("span");
    meta.textContent = item.lastError
      ? `同步异常：${item.lastError}`
      : item.lastSyncAt
        ? `上次同步 ${formatDateTime(item.lastSyncAt)}`
        : "尚未同步";
    main.append(title, meta);

    const remove = el("button", "button ghost danger");
    remove.type = "button";
    remove.textContent = "移除";
    remove.dataset.handleId = item.id;
    row.append(main, remove);
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
    if (!selected) state.selectedMemberKey = "";
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

function memberTeam(member) {
  return member.teamName || (member.ownerType === "guest" ? "游客" : "未分组");
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
      ? member.handles.map((handle) => `${handle.platformLabel}:${handle.handle}`).join(" / ")
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
    `${member.handles?.length || 0} 个 OJ 账号`,
  ].filter(Boolean).join(" · ");
  title.append(h3, meta);

  bar.append(back, title);
  detail.append(bar, renderMemberCard(member), renderMemberSubmissions(member));
  return detail;
}

function renderMemberSubmissions(member) {
  const section = el("section", "member-submissions");
  const rows = (state.overview?.feed || [])
    .filter((item) => item.ownerType === member.ownerType && String(item.ownerId) === String(member.ownerId))
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
    empty.textContent = "这个成员还没有提交记录";
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

function renderMemberCard(member) {
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
      const pill = el("span", `platform-pill${handle.lastError ? " error" : ""}`);
      pill.title = handle.lastError || handle.handle;
      pill.textContent = `${handle.platformLabel}:${handle.handle}`;
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
  wallWrap.appendChild(renderWall(member.days || {}, state.wallRange, state.overview.today, state.overview.dateRange));
  card.append(
    head,
    wallWrap,
    renderActivityStats(member.days || {}, member.stats || {}, state.wallRange),
    renderContestStats(member.contests || {}, state.wallRange),
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
  const start = new Date(lower);
  start.setUTCDate(start.getUTCDate() - start.getUTCDay());
  const weekCount = Math.ceil(((upper - start) / 86400000 + 1) / 7);
  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  let lastMonth = -1;

  months.style.gridTemplateColumns = `repeat(${weekCount}, var(--wall-cell))`;
  for (let week = 0; week < weekCount; week += 1) {
    for (let day = 0; day < 7; day += 1) {
      const date = new Date(start);
      date.setUTCDate(start.getUTCDate() + week * 7 + day);
      if (date < lower || date > upper) continue;
      if (date.getUTCMonth() !== lastMonth && date.getUTCDate() <= 7) {
        const label = document.createElement("span");
        label.textContent = monthNames[date.getUTCMonth()];
        label.style.gridColumn = String(week + 1);
        months.appendChild(label);
        lastMonth = date.getUTCMonth();
        break;
      }
    }
  }

  for (const label of ["", "Mon", "", "Wed", "", "Fri", ""]) {
    const item = document.createElement("span");
    item.textContent = label;
    weekdays.appendChild(item);
  }

  for (let i = 0; i < weekCount * 7; i += 1) {
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
      const haystack = `${item.displayName || ""} ${realName} ${item.handle || ""} ${item.ownerId || ""}`.toLowerCase();
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
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
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
    await loadOverview();
    const errors = (data.sync || []).filter((item) => item.error);
    const cached = (data.sync || []).filter((item) => item.cached);
    if (errors.length) {
      showMessage(`${errors.length} 个绑定已保存，但同步提交记录失败；错误原因会显示在绑定列表里。`, "error");
    } else if (cached.length) {
      const oldest = cached
        .map((item) => item.cacheAsOf)
        .filter(Boolean)
        .sort()[0];
      showMessage(`绑定已保存，当前使用本地缓存，缓存时间 ${oldest ? formatDateTime(oldest) : "未知"}。`, "error");
    }
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
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
    state.overview = data;
    state.user = data.user;
    renderAll();
    const errors = (data.results || []).filter((item) => item.error);
    const cached = (data.results || []).filter((item) => item.cached);
    if (errors.length) {
      showMessage(`${errors.length} 个绑定同步失败，成员卡片里能看到错误原因。`, "error");
    } else if (cached.length) {
      const oldest = cached
        .map((item) => item.cacheAsOf)
        .filter(Boolean)
        .sort()[0];
      showMessage(`${cached.length} 个绑定使用了本地缓存，缓存时间 ${oldest ? formatDateTime(oldest) : "未知"}。`, "error");
    }
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
  try {
    await api(`/api/handles?id=${encodeURIComponent(id)}`, { method: "DELETE" });
    await loadOverview();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

function bindEvents() {
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
      renderMembers();
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
      state.selectedMemberKey = row.dataset.memberKey;
      renderMembers();
    }
  });
  $("#members").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("[data-member-key]");
    if (!row) return;
    event.preventDefault();
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
    const button = event.target.closest("button[data-handle-id]");
    if (button) removeHandle(button.dataset.handleId);
  });
}

async function init() {
  bindEvents();
  try {
    await loadSession();
    await loadOverview();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

init();
