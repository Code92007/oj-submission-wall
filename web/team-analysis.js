"use strict";
const $ta = (id) => document.getElementById(id);
const escapeTa = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const colors = ["#4b79d1", "#bb8c41", "#9a73bd", "#308663"];
let optionsTa = null, dataTa = null, requestTa = 0;
let radarSelected = new Set();
const shownPlayers = new Set([3]);
const numberTa = (n) => n == null ? "—" : n;
const dateTa = (seconds) => seconds ? new Intl.DateTimeFormat("zh-CN", {timeZone:"Asia/Shanghai"}).format(new Date(seconds*1000)) : "暂无";
function setStatusTa(message, error=false) { $ta("analysisStatus").textContent=message; $ta("analysisStatus").classList.toggle("error",error); }
async function apiTa(path) { const response=await fetch(path); const data=await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || "请求失败"); return data; }
function memberOptionsTa() {
  const query=$ta("memberSearch").value.trim().toLowerCase();
  const chosen=[0,1,2].map(i=>$ta(`member${i}`).value);
  for (let i=0;i<3;i++) {
    const select=$ta(`member${i}`); select.replaceChildren(new Option("选择成员", ""));
    for (const m of optionsTa.members) {
      if (m.key!==chosen[i] && !`${m.displayName} ${m.teamName}`.toLowerCase().includes(query)) continue;
      const option=new Option(`${m.displayName} · ${m.teamName}`, m.key);
      option.disabled=chosen.includes(m.key) && m.key!==chosen[i]; select.add(option);
    }
    select.value=chosen[i];
  }
}
async function analyzeTa(event) {
  event?.preventDefault();
  const keys=[0,1,2].map(i=>$ta(`member${i}`).value);
  if (keys.some(k=>!k) || new Set(keys).size!==3) { setStatusTa("请选择三位不同成员。",true); return; }
  const id=++requestTa;
  if(!$ta("forecastBudget").checkValidity()){setStatusTa("预测限时应为 30–600 分钟。",true);return;}
  if(!$ta("target").value)$ta("target").value="1900";
  const params=new URLSearchParams({platform:$ta("platform").value,target:$ta("target").value,contest:$ta("forecastContest").value,budget:$ta("forecastBudget").value});
  keys.forEach(k=>params.append("member",k));
  $ta("analyze").disabled=true; $ta("analysisResult").hidden=true;
  setStatusTa("正在汇总训练证据与历史比赛…");
  try {
    const data=await apiTa(`/api/team-analysis?${params}`); if (id!==requestTa) return;
    dataTa=data; history.replaceState(null,"",`/team-analysis?${params}`);
    radarSelected=new Set(data.tags.filter(t=>t.members.some(m=>m.practiced)).sort((a,b)=>b.members.reduce((s,m)=>s+m.practiced,0)-a.members.reduce((s,m)=>s+m.practiced,0)).slice(0,10).map(t=>t.key));
    renderTa(); $ta("analysisResult").hidden=false;
    setStatusTa(`训练快照 · ${new Date(data.generatedAt).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai"})} · ${data.modelVersion}`);
  } catch(error) { if(id===requestTa) setStatusTa(error.message,true); }
  finally { if(id===requestTa) $ta("analyze").disabled=false; }
}
function chipTa(row) { return `<span class="ta-chip ${escapeTa(row.status)}">${escapeTa(row.coverageLabel)}</span>`; }
function renderTa() {
  const d=dataTa, usable=d.members.reduce((s,m)=>s+m.coverage.usable,0);
  $ta("summary").innerHTML=`<article class="ta-stat"><span class="ta-name">团队综合估计</span><strong>${numberTa(d.overall.rating)}</strong><p>参考线 ${d.target} · ${d.families.filter(t=>t.status==="covered").length}/12 维双人覆盖</p><p>${usable} 道有评级且有标签的个人练习</p></article>`+d.members.map((m,i)=>`<article class="ta-stat"><span class="ta-name"><i class="ta-dot player-${i}"></i>${escapeTa(m.displayName)}</span><strong>${numberTa(m.overall.rating)}</strong><p>${m.overall.solved} 题 AC · ${m.coverage.usable}/${m.coverage.problems} 题支持 tag 分析</p><p>${m.overall.wa} 次首过前 WA · ${m.overall.reliable?"样本可用":"样本偏少"}</p></article>`).join("");
  $ta("radarLegend").replaceChildren();
  [...d.members.map(m=>m.displayName),"团队"].forEach((name,i)=>{
    const label=document.createElement("label"), box=document.createElement("input"), dot=document.createElement("i");
    box.type="checkbox";box.checked=shownPlayers.has(i);box.addEventListener("change",()=>{box.checked?shownPlayers.add(i):shownPlayers.delete(i);renderRadarTa();});
    dot.className="ta-dot";dot.style.background=colors[i];label.append(box,dot,document.createTextNode(name));$ta("radarLegend").append(label);
  });
  $ta("radarTags").replaceChildren();
  d.tags.forEach(t=>{
    const label=document.createElement("label"),box=document.createElement("input");box.type="checkbox";box.checked=radarSelected.has(t.key);
    box.addEventListener("change",()=>{if(box.checked && radarSelected.size>=12){box.checked=false;setStatusTa("原始 tag 雷达最多选择 12 个维度。",true);return;}box.checked?radarSelected.add(t.key):radarSelected.delete(t.key);renderRadarTa();});
    label.append(box,document.createTextNode(t.label));$ta("radarTags").append(label);
  });
  renderTeamAccountsTa();renderRadarTa();renderRecommendationsTa();renderTableTa();renderRetriesTa();renderForecastTa();renderBacktestTa();
  $ta("coverage").innerHTML=`<h3>本次数据覆盖</h3><ul>${d.members.map(m=>`<li>${escapeTa(m.displayName)}：${m.coverage.problems} 道个人练习，${m.coverage.unrated} 道缺兼容评级、${m.coverage.untagged} 道缺标签（两者可重叠）。可见提交从 ${dateTa(m.coverage.firstSubmission)} 至 ${dateTa(m.coverage.lastSubmission)}，只代表已同步范围。</li>`).join("")}</ul><p>区域赛评级快照：${escapeTa(d.ratingRelease.method)} · ${d.ratingRelease.problems} 题 · ${escapeTa(d.ratingRelease.revision)}。标签缺失时不猜测题型。</p>`;
  $ta("modelNotes").innerHTML=`<ul>${d.notes.map(s=>`<li>${escapeTa(s)}</li>`).join("")}</ul>`;
}
function renderTeamAccountsTa() {
  const accounts=dataTa.teamAccounts||[], section=$ta("teamAccounts");section.hidden=!accounts.length;
  section.innerHTML=accounts.length?`<p class="ta-eyebrow">TEAM ACCOUNT EVIDENCE</p><h2>队伍账号 · 去重记录</h2><p class="ta-muted ta-small">共享牛客号和已标记的队伍号单独列示。相同提交与题目合并后只计一份，不重复归到个人，也不据此判断双人覆盖。战力与预测使用上方三位成员的个人训练。</p><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>队伍账号</th><th>当前选中绑定成员</th><th>去重提交 / 练习 / AC</th><th>首过前 WA</th><th>当前来源</th></tr></thead><tbody>${accounts.map(a=>`<tr><td>${escapeTa(a.platform==="nowcoder"?"牛客":a.platform)} · ${escapeTa(a.handle)}<small>${a.shared?"共享账号":"已标记团队账号"}</small></td><td>${a.members.map(escapeTa).join(" / ")}</td><td>${a.coverage.submissions} / ${a.coverage.problems} / ${a.solved}</td><td>${a.wa}</td><td>${a.inSelectedSource?"队伍证据单列":"不在当前训练来源内"}</td></tr>`).join("")}</tbody></table></div>`:"";
}
function svgTa(tag, attributes={}, text="") { const node=document.createElementNS("http://www.w3.org/2000/svg",tag);Object.entries(attributes).forEach(([k,v])=>node.setAttribute(k,v));if(text)node.textContent=text;return node; }
function renderRadarTa() {
  if(!dataTa) return;
  const raw=$ta("radarMode").value==="tags";$ta("radarTags").hidden=!raw;
  const axes=raw?dataTa.tags.filter(t=>radarSelected.has(t.key)):dataTa.families;
  const wrap=$ta("radar");wrap.replaceChildren();
  if(axes.length<3) {wrap.innerHTML='<p class="ta-empty">请选择至少 3 个 tag 查看雷达图。</p>';return;}
  const svg=svgTa("svg",{viewBox:"0 0 600 500",role:"img","aria-label":"团队及个人 tag 能力雷达图，具体数值见下方训练明细"});
  const cx=300,cy=245,r=165,max=3500;
  const point=(i,value)=>{const a=-Math.PI/2+i*Math.PI*2/axes.length;return [cx+Math.cos(a)*r*value/max,cy+Math.sin(a)*r*value/max];};
  const points=(values)=>values.map((v,i)=>point(i,v).join(",")).join(" ");
  for(const value of [700,1400,2100,2800,3500]) {svg.append(svgTa("polygon",{points:points(axes.map(()=>value)),class:"ta-radar-grid"}));svg.append(svgTa("text",{x:cx+6,y:cy-r*value/max-3,class:"ta-radar-scale"},String(value)));}
  axes.forEach((t,i)=>{const [x,y]=point(i,max);svg.append(svgTa("line",{x1:cx,y1:cy,x2:x,y2:y,class:"ta-radar-axis"}));const [lx,ly]=point(i,max+430);const label=svgTa("text",{x:lx,y:ly+4,"text-anchor":Math.abs(lx-cx)<12?"middle":lx>cx?"start":"end",class:"ta-radar-label"},t.label.length>23?t.label.slice(0,21)+"…":t.label);label.append(svgTa("title",{},`${t.label} · 团队 ${numberTa(t.rating)} · ${t.coverageLabel}`));svg.append(label);});
  svg.append(svgTa("polygon",{points:points(axes.map(()=>dataTa.target)),class:"ta-radar-target"}));
  [...shownPlayers].sort().forEach(series=>{
    const values=axes.map(t=>series===3?t.rating:t.members[series].rating);
    // A missing estimate breaks the line; it never creates a spurious zero-valued polygon.
    if(values.every(v=>v!=null)) svg.append(svgTa("polygon",{points:points(values.map(v=>Math.min(max,v))),fill:colors[series],"fill-opacity":series===3?.1:.025,stroke:colors[series],"stroke-width":series===3?2.5:1.5}));
    else axes.forEach((t,i)=>{const j=(i+1)%axes.length;if(values[i]!=null && values[j]!=null){const a=point(i,Math.min(max,values[i])),b=point(j,Math.min(max,values[j]));svg.append(svgTa("line",{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:colors[series],"stroke-width":2}));}});
    values.forEach((value,i)=>{const [x,y]=point(i,value==null?max:Math.min(max,value));const circle=svgTa("circle",{cx:x,cy:y,r:value==null?4:3,fill:value==null?"white":colors[series],stroke:colors[series],"stroke-width":1.5});circle.append(svgTa("title",{},`${axes[i].label} · ${series===3?"团队":dataTa.members[series].displayName}：${value==null?"证据不足":value}`));svg.append(circle);});
  });
  wrap.append(svg);
}
function renderRecommendationsTa() {
  const rows=dataTa.families, order={weak:0,specialist:1,unknown:2,developing:3,covered:4};
  const chosen=[...rows].sort((a,b)=>order[a.status]-order[b.status] || (a.rating??0)-(b.rating??0)).slice(0,5);
  $ta("recommendations").innerHTML=chosen.map(t=>{
    const ranked=t.members.map((m,i)=>({...m,name:dataTa.members[i].displayName})).sort((a,b)=>(b.rating??0)-(a.rating??0));
    let advice=t.status==="unknown"?"先补齐个人训练或同步记录，再判断是否短板。建议用 5–8 道有评级的相关题建立基线。":t.status==="specialist"?`${ranked[0].name} 可以主攻；安排另一位队员练习目标附近题目，降低单点依赖。`:t.status==="covered"?"至少两位队员达到目标，可保持训练，把更多时间留给覆盖薄弱的维度。":`优先让第二位队员练习 ${Math.max(800,Math.min(dataTa.target-200,Math.floor((t.rating||dataTa.target-300)/100)*100))}–${dataTa.target} 的相关题，复盘首过前 WA，再逐步提高难度。`;
    return `<article class="ta-advice"><h3>${escapeTa(t.label)} <span class="ta-muted">${numberTa(t.rating)}</span></h3>${chipTa(t)}<p>${escapeTa(advice)}</p></article>`;
  }).join("");
}
function detailTa(m) {
  const dist=Object.entries(m.distribution).sort((a,b)=>Number(a[0])-Number(b[0])), max=Math.max(1,...dist.map(([,v])=>v));
  return `<details><summary>${numberTa(m.rating)} <span class="ta-muted">· AC ${m.solved} / 练 ${m.practiced}</span></summary><div class="ta-member-detail"><p>评级 AC ${m.ratedSolved} · 置信度 ${Math.round(m.confidence*100)}%${m.reliable?"":" · 样本偏少"}</p><p>WA ${m.wa} · 首过前错误 ${m.errors}<br>未过 ${m.unresolved} · 平均尝试 ${numberTa(m.averageTries)}</p><p>最近练习 ${dateTa(m.lastPractice)}<br>错误扣分 ${m.errorPenalty} · 衰减扣分 ${m.memoryPenalty}</p>${dist.length?`<div class="ta-mini-hist" aria-label="过题评级分布">${dist.map(([bucket,n])=>`<span style="height:${Math.max(4,n/max*100)}%" title="${bucket}–${Number(bucket)+199}：${n} 题"></span>`).join("")}</div><p>${dist.map(([bucket,n])=>`${bucket}–${Number(bucket)+199}: ${n}`).join(" · ")}</p>`:""}</div></details>`;
}
function renderTableTa() {
  if(!dataTa)return;const query=$ta("tagSearch").value.toLowerCase().trim();
  const rows=dataTa.tags.filter(t=>t.label.toLowerCase().includes(query));
  $ta("tagTable").innerHTML=`<table class="ta-table"><thead><tr><th scope="col">Tag</th><th scope="col">团队评级 / 覆盖</th>${dataTa.members.map(m=>`<th scope="col">${escapeTa(m.displayName)}</th>`).join("")}</tr></thead><tbody>${rows.map(t=>`<tr><td>${escapeTa(t.label)}</td><td><strong>${numberTa(t.rating)}</strong> ${chipTa(t)}<small>双人通路 ${numberTa(t.consensusRating)}<br>专长通路 ${numberTa(t.specialistRating)}</small></td>${t.members.map(m=>`<td>${detailTa(m)}</td>`).join("")}</tr>`).join("")||'<tr><td colspan="5">没有匹配的 tag</td></tr>'}</tbody></table>`;
}
function renderRetriesTa() {
  const rows=dataTa.tags.map(t=>{const solved=t.members.reduce((s,m)=>s+m.solved,0);return {...t,solved,avg:t.members.reduce((s,m)=>s+(m.averageTries||0)*m.solved,0)/Math.max(1,solved)};}).filter(t=>t.solved>=3).sort((a,b)=>b.avg-a.avg).slice(0,16),max=Math.max(1,...rows.map(t=>t.avg));
  $ta("retryBars").innerHTML=rows.map(t=>`<div class="ta-retry-row"><span>${escapeTa(t.label)}</span><div class="ta-retry-track"><div class="ta-retry-fill" style="width:${t.avg/max*100}%"></div></div><span>${t.avg.toFixed(1)} <span class="ta-retry-meta">· ${t.solved} 题</span></span></div>`).join("")||'<p class="ta-empty">暂无至少 3 道已通过题的 tag 数据。</p>';
}
function probabilityTa(row) {return row.probability==null?"—":`${Math.round(row.probability*100)}% <small>范围 ${Math.round(row.probabilityRange[0]*100)}–${Math.round(row.probabilityRange[1]*100)}%</small>`;}
function timeTa(row) {return row.conditionalMinutes==null?"—":`${row.conditionalMinutes} 分钟<small>${row.timeRangeMinutes[0]}–${row.timeRangeMinutes[1]} 分钟 · 解出时</small>`;}
function renderForecastTa() {
  const f=dataTa.forecast;$ta("forecastTitle").textContent=`${f.name} · ${f.budgetMinutes} 分钟推演`;
  $ta("forecast").innerHTML=`<div class="ta-metrics"><div class="ta-metric">预计通过<strong>${f.expectedSolves} 题</strong></div><div class="ta-metric">敏感性范围<strong>${f.expectedSolvesRange.join("–")} 题</strong></div><div class="ta-metric">可预测题目<strong>${f.predictedProblems}/${f.problems.length}</strong></div><div class="ta-metric">时间基准<strong>${f.timing.source==="heuristic"?"经验先验":"个人历史"} · ${f.timing.samples} 个样本</strong></div></div><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>题目 / tags</th><th>经验评级</th><th>限时内通过倾向</th><th>首过条件期望 / 区间</th><th>含失败风险的预算期望</th></tr></thead><tbody>${f.problems.map(p=>`<tr><td>${escapeTa(p.index)} · ${escapeTa(p.name)}<small>${escapeTa(p.tags.join(" / ")||"缺少标签 · 使用综合基线")}</small></td><td>${numberTa(p.rating)}<small>${p.ratingRange?p.ratingRange.join("–"):""}</small></td><td>${probabilityTa(p)}<small>${p.probability==null?escapeTa(p.reason):p.tagged?"tag 战力":"综合基线"}</small></td><td>${timeTa(p)}</td><td>${p.budgetedMinutes==null?"—":`${p.budgetedMinutes} 分钟`}<small>未解出按 ${f.budgetMinutes} 分钟计</small></td></tr>`).join("")}</tbody></table></div><ul class="ta-muted ta-small">${f.notes.map(n=>`<li>${escapeTa(n)}</li>`).join("")}</ul>`;
}
function renderBacktestTa() {
  const b=dataTa.backtest;$ta("backtestStatus").textContent=b.message;
  $ta("backtest").innerHTML=`${b.metrics.count?`<div class="ta-metrics"><div class="ta-metric">评级题样本<strong>${b.metrics.count}</strong></div><div class="ta-metric">整体 Brier<strong>${numberTa(b.metrics.brier)}</strong></div><div class="ta-metric">有标签题 Brier<strong>${numberTa(b.tagMetricsSummary.brier)}</strong></div><div class="ta-metric">同题综合基线 Brier<strong>${numberTa(b.baselineMetrics.brier)}</strong></div><div class="ta-metric">时间 MAE<strong>${numberTa(b.timeMetrics.maeMinutes)} 分钟 · ${b.timeMetrics.count} 题</strong></div><div class="ta-metric">时间区间命中率<strong>${b.timeMetrics.intervalCoverage==null?"—":Math.round(b.timeMetrics.intervalCoverage*100)+"%"}</strong></div></div><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>比赛 / 日期</th><th>历史阵容</th><th>预计通过 / 实际通过</th><th>回测范围</th><th>Brier</th></tr></thead><tbody>${b.contests.map(c=>`<tr><td>${escapeTa(c.name)}<small>${escapeTa(c.date)}</small></td><td>${c.sameLineup?"当前三人":"当年真实队伍"}</td><td>${c.predictedSolves} / ${c.actualSolves}<details><summary>逐题概率与时间对照</summary>${c.problems.map(p=>`<small>${escapeTa(p.index)} · ${p.rating} · ${p.accepted?"通过":"未通过"} · 倾向 ${Math.round(p.probability*100)}% [${p.probabilityRange.map(v=>Math.round(v*100)).join("–")}%]<br>预计首过 ${p.conditionalMinutes} 分钟 [${p.timeRangeMinutes.join("–")}] · 实际 ${p.actualMinutes==null?"无可靠时间":p.actualMinutes.toFixed(1)+" 分钟"}</small>`).join("")}</details></td><td>评级 ${c.ratedProblems}/${c.totalProblems} 题<small>tag ${c.taggedProblems} 题 · ${c.durationMinutes} 分钟赛制</small><small>截断 ${escapeTa(c.date)} 00:00 UTC+8</small></td><td>${c.brier}</td></tr>`).join("")}</tbody></table></div>`:""}
    ${b.probabilityCalibration.some(r=>r.count)?`<h3>概率分桶回测</h3><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>预测概率桶</th><th>样本</th><th>平均预测 / 实际通过率</th><th>敏感性范围</th></tr></thead><tbody>${b.probabilityCalibration.map(r=>`<tr><td>${r.range.map(v=>Math.round(v*100)).join("–")}%</td><td>${r.count}</td><td>${r.count?`${Math.round(r.meanPrediction*100)}% / ${Math.round(r.actualRate*100)}%`:"—"}</td><td>${r.predictedRange?r.predictedRange.map(v=>Math.round(v*100)).join("–")+"%":"—"}</td></tr>`).join("")}</tbody></table></div>`:""}
    ${b.ratingCohorts.length?`<h3>相近战力的历史通过与时间</h3><p class="ta-muted ta-small">仅本人的可回测历史队伍，按当时战力和题目评级分桶；小样本只作观察。实际平均时间只针对有首过时间的 AC。</p><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>队伍战力区间</th><th>题目评级区间</th><th>样本</th><th>预测 / 实际通过率</th><th>预计 / 实际平均首过</th></tr></thead><tbody>${b.ratingCohorts.map(r=>`<tr><td>${r.abilityRange.join("–")}</td><td>${r.difficultyRange.join("–")}</td><td>${r.count}</td><td>${Math.round(r.meanPrediction*100)}% / ${Math.round(r.actualRate*100)}%</td><td>${r.predictedMeanMinutes} / ${numberTa(r.actualMeanMinutes)} 分钟<small>实测 ${r.timedSolves} 题</small></td></tr>`).join("")}</tbody></table></div><p class="ta-muted ta-small">含未解出、按比赛时长截尾的预算期望 MAE：${numberTa(b.timeMetrics.budgetedMaeMinutes)} 分钟。</p>`:""}
    ${b.tagMetrics.length?`<h3>雷达维度诊断</h3><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>tag</th><th>样本</th><th>tag Brier</th><th>综合基线 Brier</th><th>预测 / 实际通过率</th></tr></thead><tbody>${b.tagMetrics.map(t=>`<tr><td>${escapeTa(t.tag)}</td><td>${t.count}</td><td>${t.brier}</td><td>${t.baselineBrier}</td><td>${Math.round(t.meanPrediction*100)}% / ${Math.round(t.actualRate*100)}%</td></tr>`).join("")}</tbody></table></div>`:""}
    ${b.ratingReview.length?`<details><summary class="ta-method-title">CF Bot 题目评级诊断 · ${b.ratingReview.length} 题</summary><p class="ta-muted ta-small">实际通过率高于预测，可能提示评级偏高；反之可能偏低。至少 5 支不同真实队伍的正式成绩才标记可复核，否则显示样本不足。不自动改分。</p><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>题目</th><th>CF Bot 评级</th><th>队伍样本</th><th>预测 / 实际通过率</th><th>诊断</th></tr></thead><tbody>${b.ratingReview.map(r=>`<tr><td>${escapeTa(r.problemId)}</td><td>${r.rating}</td><td>${r.count}</td><td>${Math.round(r.meanPrediction*100)}% / ${Math.round(r.actualRate*100)}%</td><td>${r.signal}</td></tr>`).join("")}</tbody></table></div></details>`:""}
    ${b.skipped.length?`<details><summary class="ta-method-title">${b.skipped.length} 场暂不能回测</summary><ul class="ta-muted ta-small">${b.skipped.map(c=>`<li>${escapeTa(c.name)} · ${escapeTa(c.date)}：${escapeTa(c.reason)}</li>`).join("")}</ul></details>`:""}
    <ul class="ta-muted ta-small">${b.notes.map(n=>`<li>${escapeTa(n)}</li>`).join("")}</ul>`;
}
$ta("analysisForm").addEventListener("submit",analyzeTa);
$ta("memberSearch").addEventListener("input",()=>{if(optionsTa)memberOptionsTa();});
for(let i=0;i<3;i++) $ta(`member${i}`).addEventListener("change",()=>{memberOptionsTa();++requestTa;$ta("analyze").disabled=false;$ta("analysisResult").hidden=true;setStatusTa("成员已更新，点击分析队伍生成结果。");});
for(const id of ["platform","target","forecastContest","forecastBudget"]) $ta(id).addEventListener("change",()=>{++requestTa;$ta("analyze").disabled=false;$ta("analysisResult").hidden=true;setStatusTa("分析条件已更新，点击分析队伍生成结果。");});
document.querySelectorAll("[data-radar-mode]").forEach(button=>button.addEventListener("click",()=>{
  $ta("radarMode").value=button.dataset.radarMode;
  $ta("radarModeLabel").textContent=button.textContent;
  document.querySelectorAll("[data-radar-mode]").forEach(choice=>choice.setAttribute("aria-pressed",String(choice===button)));
  $ta("radarModePicker").open=false;renderRadarTa();
}));
$ta("radarModePicker").addEventListener("keydown",event=>{if(event.key==="Escape"){$ta("radarModePicker").open=false;$ta("radarModePicker").querySelector("summary").focus();}});
document.addEventListener("click",event=>{if(!$ta("radarModePicker").contains(event.target))$ta("radarModePicker").open=false;});
$ta("tagSearch").addEventListener("input",renderTableTa);
async function initTa() {
  try {
    optionsTa=await apiTa("/api/team-analysis/options");memberOptionsTa();
    optionsTa.contests.forEach(c=>$ta("forecastContest").add(new Option(c.name,c.id)));
    const params=new URLSearchParams(location.search),keys=params.getAll("member");
    if(optionsTa.contests.some(c=>c.id===params.get("contest")))$ta("forecastContest").value=params.get("contest");
    if(/^\d+$/.test(params.get("budget")||""))$ta("forecastBudget").value=params.get("budget");
    if(keys.length===3) keys.forEach((key,i)=>{if(optionsTa.members.some(m=>m.key===key))$ta(`member${i}`).value=key;});
    else {const current=optionsTa.members.find(m=>m.isCurrent);if(current)$ta("member0").value=current.key;}
    memberOptionsTa();if(["codeforces","all"].includes(params.get("platform")))$ta("platform").value=params.get("platform");
    if(/^\d+$/.test(params.get("target")||""))$ta("target").value=params.get("target");
    setStatusTa(optionsTa.members.length<3?"至少需要三位训练墙成员。请先注册或绑定账号。":"选择三位成员，查看团队的能力覆盖。");
    if(keys.length===3 && [0,1,2].every(i=>$ta(`member${i}`).value) && $ta("analysisForm").checkValidity()) await analyzeTa();
  } catch(error) {setStatusTa(error.message,true);}
}
initTa();
