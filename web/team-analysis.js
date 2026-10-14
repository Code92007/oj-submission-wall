"use strict";
const $ta = (id) => document.getElementById(id);
const escapeTa = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const colors = ["#4b79d1", "#bb8c41", "#9a73bd", "#308663"];
let optionsTa = null, dataTa = null, requestTa = 0;
let radarSelected = new Set();
let categorySelected = new Set();
let onsiteBoardTa = "all";
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
    categorySelected=new Set((data.categories||[]).map(t=>t.key));
    renderTa(); $ta("analysisResult").hidden=false;
    setStatusTa(`训练快照 · ${new Date(data.generatedAt).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai"})} · ${data.modelVersion}`);
  } catch(error) { if(id===requestTa) setStatusTa(error.message,true); }
  finally { if(id===requestTa) $ta("analyze").disabled=false; }
}
function chipTa(row) { return `<span class="ta-chip ${escapeTa(row.status)}">${escapeTa(row.coverageLabel)}</span>`; }
function memberSummaryTa(member,i) {
  const m=member.overall, trend=m.momentum;
  return `<article class="ta-stat"><span class="ta-name"><i class="ta-dot player-${i}"></i>${escapeTa(member.displayName)}</span><strong>${numberTa(m.rating)}</strong><p>综合能力估计 · ${m.ratingSource==="cf-training-hybrid"?"官方历史 + 近期训练":m.ratingSource==="multi-source-training"?"含洛谷的近期训练代理":m.ratingSource==="recent-training"?"近期训练代理":"训练代理"}</p>${m.officialRating!=null?`<p>官方最新 ${m.officialRating} · 历史峰值 ${m.peakRating}</p>`:""}${trend?.recent20Count?`<p>CF Recent 20 AC 均值 ${trend.recent20Mean} · ${trend.recent20Count} 题</p><p>近半年移动均值 ${numberTa(trend.monthsWeightedMean)}</p>`:""}${m.luoguMomentum?.recent20Count?`<p>洛谷近 20 AC 换算均值 ${numberTa(m.luoguMomentum.recent20Mean)} · ${m.luoguMomentum.recent20Count} 题<small>近半年移动均值 ${numberTa(m.luoguMomentum.monthsWeightedMean)} · 近似换算，半权重</small></p>`:""}<p>${m.solved} 题 AC · ${member.coverage.usable}/${member.coverage.problems} 题支持标签分析</p><p>${m.wa} 次首过前 WA · ${m.reliable?"样本可用":"样本偏少"}</p></article>`;
}
function renderTa() {
  const d=dataTa, usable=d.members.reduce((s,m)=>s+m.coverage.usable,0);
  $ta("summary").innerHTML=`<article class="ta-stat"><span class="ta-name">团队综合估计</span><strong>${numberTa(d.overall.rating)}</strong><p>参考线 ${d.target} · ${d.families.filter(t=>t.status==="covered").length}/12 维双人覆盖</p><p>${usable} 道有评级且有标签的个人练习</p><p>按综合能力估计推演，区别于官方 Rating。</p></article>`+d.members.map(memberSummaryTa).join("");
  $ta("radarLegend").replaceChildren();
  [...d.members.map(m=>m.displayName),"团队"].forEach((name,i)=>{
    const label=document.createElement("label"), box=document.createElement("input"), dot=document.createElement("i");
    box.type="checkbox";box.checked=shownPlayers.has(i);box.addEventListener("change",()=>{box.checked?shownPlayers.add(i):shownPlayers.delete(i);renderRadarTa();});
    dot.className="ta-dot";dot.style.background=colors[i];label.append(box,dot,document.createTextNode(name));$ta("radarLegend").append(label);
  });
  $ta("radarTags").replaceChildren();
  d.tags.forEach(t=>{
    const label=document.createElement("label"),box=document.createElement("input");box.type="checkbox";box.checked=radarSelected.has(t.key);
    box.addEventListener("change",()=>{if(box.checked && radarSelected.size>=12){box.checked=false;setStatusTa("细分标签雷达最多选择 12 个维度。",true);return;}box.checked?radarSelected.add(t.key):radarSelected.delete(t.key);renderRadarTa();});
    label.append(box,document.createTextNode(t.label));$ta("radarTags").append(label);
  });
  $ta("radarCategories").replaceChildren();
  (d.categories||[]).forEach(t=>{
    const label=document.createElement("label"),box=document.createElement("input");box.type="checkbox";box.checked=categorySelected.has(t.key);
    box.addEventListener("change",()=>{box.checked?categorySelected.add(t.key):categorySelected.delete(t.key);renderRadarTa();});
    label.title="包含："+(t.sourceLabels||t.sourceTags).join("、")+(t.sourceNote?"。"+t.sourceNote:"");label.append(box,document.createTextNode(t.label+(t.key==="counting"?"（动态规划 / 组合数学）":"")+(t.members.some(m=>m.practiced)?"":" · 暂无明确标签")));$ta("radarCategories").append(label);
  });
  $ta("radarCategorySources").innerHTML=`<ul>${(d.categories||[]).map(t=>`<li><strong>${escapeTa(t.label)}</strong>：${(t.sourceLabels||t.sourceTags).map(escapeTa).join("、")}${t.sourceNote?`。${escapeTa(t.sourceNote)}`:""}</li>`).join("")}</ul>`;
  renderTeamAccountsTa();renderOnsiteReferenceTa();renderRadarTa();renderTableTa();renderRetriesTa();renderForecastTa();renderBacktestTa();
  $ta("coverage").innerHTML=`<h3>本次数据覆盖</h3><ul>${d.members.map(m=>`<li>${escapeTa(m.displayName)}：${m.coverage.problems} 道个人练习，${m.coverage.unrated} 道缺兼容评级、${m.coverage.untagged} 道缺标签（两者可重叠），${m.coverage.approximate||0} 道采用洛谷颜色换算。<br>${Object.entries(m.coverage.byPlatform||{}).map(([p,c])=>`${escapeTa(({codeforces:"CF",luogu:"洛谷",nowcoder:"牛客"})[p]||p)}：练 ${c.problems} / 支持标签 ${c.usable}`).join("；")}。可见提交从 ${dateTa(m.coverage.firstSubmission)} 至 ${dateTa(m.coverage.lastSubmission)}，只代表已同步范围。</li>`).join("")}</ul><p>区域赛评级快照：${escapeTa(d.ratingRelease.method)} · ${d.ratingRelease.problems} 题 · ${escapeTa(d.ratingRelease.revision)}。标签缺失时不猜测题型。分来源题量各自去重、可重叠；个人总题量已跨来源去重。</p>${d.luoguCalibration?`<details><summary>洛谷颜色 → CF 近似区间</summary><p>来源：${escapeTa(d.luoguCalibration.source.file)} · ${escapeTa(d.luoguCalibration.source.sheet)}。下表为样本难度的 10%–90% 分布，不是逐题官方评级或统计置信区间。未知难度不换算，缺标签不猜测。</p><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>洛谷难度</th><th>换算均值 / 区间</th><th>样本数</th></tr></thead><tbody>${d.luoguCalibration.bands.map(b=>`<tr><td>${escapeTa(b.label)}</td><td>${b.mean} / ${b.range.join("–")}</td><td>${b.samples}</td></tr>`).join("")}</tbody></table></div></details>`:""}`;
  $ta("modelNotes").innerHTML=`<ul>${d.notes.map(s=>`<li>${escapeTa(s)}</li>`).join("")}</ul>`;
}
function renderTeamAccountsTa() {
  const accounts=dataTa.teamAccounts||[], section=$ta("teamAccounts");section.hidden=!accounts.length;
  section.innerHTML=accounts.length?`<p class="ta-eyebrow">TEAM ACCOUNT EVIDENCE</p><h2>队伍账号 · 去重记录</h2><p class="ta-muted ta-small">共享牛客号和已标记的队伍号单独列示。相同提交与题目合并后只计一份，不重复归到个人，也不据此判断双人覆盖。战力与预测使用上方三位成员的个人训练。</p><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>队伍账号</th><th>当前选中绑定成员</th><th>去重提交 / 练习 / AC</th><th>首过前 WA</th><th>当前来源</th></tr></thead><tbody>${accounts.map(a=>`<tr><td>${escapeTa(a.platform==="nowcoder"?"牛客":a.platform)} · ${escapeTa(a.handle)}<small>${a.shared?"共享账号":"已标记团队账号"}</small></td><td>${a.members.map(escapeTa).join(" / ")}</td><td>${a.coverage.submissions} / ${a.coverage.problems} / ${a.solved}</td><td>${a.wa}</td><td>${a.inSelectedSource?"队伍证据单列":"不在当前训练来源内"}</td></tr>`).join("")}</tbody></table></div>`:"";
}
function svgTa(tag, attributes={}, text="") { const node=document.createElementNS("http://www.w3.org/2000/svg",tag);Object.entries(attributes).forEach(([k,v])=>node.setAttribute(k,v));if(text)node.textContent=text;return node; }
function renderOnsiteReferenceTa() {
  const ref=dataTa.onsiteReference, section=$ta("onsiteReference");
  if(!ref){section.hidden=true;return;}
  section.hidden=false;
  const title=`<p class="ta-eyebrow">ONSITE EVIDENCE · Hei-MaoM</p><h2>现场赛十三维参考</h2>`;
  if(!["ready","stale"].includes(ref.status)){section.innerHTML=title+`<p class="ta-muted">${escapeTa(ref.message)}</p>`;return;}
  const panel=ref.panels[onsiteBoardTa], member=dataTa.members.find(m=>m.key===ref.owner);
  const modes=`<label class="ta-compact">参赛口径<select id="onsiteBoard" aria-label="现场参考参赛口径"><option value="all" ${onsiteBoardTa==="all"?"selected":""}>全部参赛（含打星）</option><option value="official" ${onsiteBoardTa==="official"?"selected":""}>仅正式参赛</option></select></label>`;
  const evidence={missing:"暂无证据",exploratory:"探索样本",provisional:"暂定估计",established:"积累充分",legacy:"旧版数据"};
  section.innerHTML=`<div class="ta-heading"><div>${title}<p class="ta-muted">${escapeTa(member?.displayName||"本人")} · <a href="${escapeTa(ref.url)}" target="_blank" rel="noopener noreferrer">查看公开档案</a></p></div>${modes}</div><p class="ta-muted ta-small">${escapeTa(ref.message)} 数据是所在历史队伍共同完成的表现，不代表每道题均由本人独立完成，也不重复算作三份战力。</p><p class="ta-muted ta-small">来源更新 ${dateTa(Date.parse(ref.generatedAt)/1000)} · 本站核对 ${dateTa(ref.checkedAt)}${ref.status==="stale"?" · 当前显示上次成功缓存，正在重试更新":""}</p>${panel?`<p>${panel.contests} 场参赛 · 总体 ${panel.uniqueProblems} 道题 · 标签证据覆盖 ${panel.coverage==null?"未知":(panel.coverage*100).toFixed(1)+"%"}</p><div class="ta-chart-layout"><div id="onsiteReferenceRadar"></div><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>题型</th><th>现场评分 / 同级前</th><th>题量 / 可信程度</th></tr></thead><tbody>${panel.axes.map(a=>`<tr><td>${escapeTa(a.label)}</td><td>${a.score==null?"暂无数据":a.score.toFixed(1)}<small>${a.topPercent==null?"":`同级前 ${a.topPercent.toFixed(1)}% · ${escapeTa(a.grade||"")}`}</small></td><td>${a.uniqueProblems} 题<small>${escapeTa(evidence[a.evidenceLevel]||"暂无证据")}${a.confidence==null?"":` · ${a.confidence>0&&a.confidence<.01?"&lt;1":Math.round(a.confidence*100)}%`}</small></td></tr>`).join("")}</tbody></table></div></div><p class="ta-muted ta-small">此雷达采用来源站 ${panel.scoreScale==="rating"?"独立评级":panel.scoreScale==="percent"?"百分比":"原始"} 刻度；空心点表示无数据。低覆盖或少样本维度需要结合训练记录复核。</p>`:`<p class="ta-muted">该参赛口径尚无十三维题型数据。</p>`}<details><summary class="ta-method-title">历史现场表现 · ${ref.history.filter(h=>onsiteBoardTa==="all"||h.official===true).length} 场</summary><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>比赛 / 日期</th><th>参赛性质</th><th>队伍通过 / 排名</th><th>首题 AC / 错误提交</th></tr></thead><tbody>${ref.history.filter(h=>onsiteBoardTa==="all"||h.official===true).map(h=>`<tr><td>${escapeTa(h.title)}<small>${escapeTa(h.date.slice(0,10))}</small></td><td>${h.official===true?"正式":h.official===false?"打星 / 非正式":"未标记"}</td><td>${numberTa(h.solved)} 题 · ${numberTa(h.rank)}/${numberTa(h.teamCount)}</td><td>${numberTa(h.firstAcMinutes)} 分钟 / ${numberTa(h.wrongAttempts)} 次</td></tr>`).join("")}</tbody></table></div></details>`;
  $ta("onsiteBoard").addEventListener("change",e=>{onsiteBoardTa=e.target.value;renderOnsiteReferenceTa();});
  if(!panel)return;
  const svg=svgTa("svg",{viewBox:"0 0 540 520",role:"img","aria-label":"本人历史现场赛十三维雷达，使用来源独立刻度"}),cx=270,cy=255,r=175,max=panel.scoreScale==="percent"?100:Math.max(2000,Math.ceil(Math.max(0,...panel.axes.map(a=>a.score||0))/500)*500);
  const point=(i,v,extra=0)=>{const angle=-Math.PI/2+2*Math.PI*i/13;return [cx+Math.cos(angle)*(r*Math.max(0,Math.min(max,v))/max+extra),cy+Math.sin(angle)*(r*Math.max(0,Math.min(max,v))/max+extra)];};
  for(let ring=1;ring<=4;ring++)svg.append(svgTa("polygon",{points:panel.axes.map((a,i)=>point(i,max*ring/4).join(",")).join(" "),class:"ta-radar-grid"}));
  panel.axes.forEach((a,i)=>{const [x,y]=point(i,max),[tx,ty]=point(i,max,28);svg.append(svgTa("line",{x1:cx,y1:cy,x2:x,y2:y,class:"ta-radar-axis"}),svgTa("text",{x:tx,y:ty,"text-anchor":tx<cx-20?"end":tx>cx+20?"start":"middle","dominant-baseline":"middle",class:"ta-radar-label"},a.label));});
  svg.append(svgTa("polygon",{points:panel.axes.map((a,i)=>point(i,a.score||0).join(",")).join(" "),fill:"#308663", "fill-opacity":.13,stroke:"#308663","stroke-width":2}));
  panel.axes.forEach((a,i)=>{const [x,y]=point(i,a.score||0);svg.append(svgTa("circle",{cx:x,cy:y,r:4,fill:a.score==null?"white":"#308663",stroke:"#308663"}));});
  svg.append(svgTa("text",{x:cx+7,y:cy-r-7,class:"ta-radar-scale"},`0–${max} · 独立刻度`));
  $ta("onsiteReferenceRadar").append(svg);
}
function radarValueTa(axis,series) {
  if(series===3)return {value:axis.rating??axis.referenceRating??null,tentative:axis.rating==null && axis.referenceRating!=null};
  const member=axis.members[series];return {value:member.rating,tentative:member.rating!=null && !member.reliable};
}
function radarEvidenceTa(axes) {
  const pending=axes.filter(t=>shownPlayers.has(3) && t.rating==null);
  const tentativePeople=axes.filter(t=>[...shownPlayers].some(i=>i<3 && t.members[i].rating!=null && !t.members[i].reliable));
  $ta("radarEvidence").innerHTML=pending.map(t=>{
    const ref=t.referenceMember==null?null:dataTa.members[t.referenceMember];
    return `<p><strong>${escapeTa(t.label)}：${ref?`${escapeTa(ref.displayName)} 单人参考 ${t.referenceRating}`:"暂无团队估计"}</strong><br>${escapeTa(t.evidenceReason||"训练证据不足。")}${t.sourceNote?` ${escapeTa(t.sourceNote)}`:""}<br>${t.members.map((m,i)=>`${escapeTa(dataTa.members[i].displayName)}：评级 AC ${m.ratedSolved}，有效样本 ${m.effectiveSolved}，${m.reliable?"个人估计可用":"样本偏少"}`).join("；")}。${ref?"单人参考用于展示已有能力线索，不作稳定团队评级或预测输入。":""}</p>`;
  }).join("")+(tentativePeople.length?`<p>个人少样本暂估：${tentativePeople.map(t=>escapeTa(t.label)).join("、")}。对应曲线使用空心点和虚线，不表示已有稳定训练证据。</p>`:"");
}
function renderRadarTa() {
  if(!dataTa) return;
  const mode=$ta("radarMode").value;
  $ta("radarTags").hidden=mode!=="tags";$ta("radarCategories").hidden=mode!=="categories";$ta("radarCategoryHelp").hidden=mode==="tags";$ta("radarCategoryMap").hidden=mode==="tags";
  const axes=mode==="tags"?dataTa.tags.filter(t=>radarSelected.has(t.key)):mode==="categories"?(dataTa.categories||[]).filter(t=>categorySelected.has(t.key)):dataTa.families;
  const wrap=$ta("radar");wrap.replaceChildren();radarEvidenceTa(axes);renderRecommendationsTa(axes);
  const full=$ta("radarScale").value==="full",min=full?0:1000,max=full?4000:3000,step=full?500:200;
  $ta("radarScaleNote").textContent=`${full?"完整刻度":"聚焦刻度"} ${min}–${max}，每 ${step} 分一格，中心为 ${min}。灰色虚线是训练参考线；彩色虚线与空心点表示少样本暂估或单人参考，问号表示暂无可用估计。实心点也只是模型估计。各维度按题去重。`;
  const clipped=[];
  [...shownPlayers].forEach(series=>axes.forEach(axis=>{const {value}=radarValueTa(axis,series);if(value!=null && (value<min || value>max))clipped.push(`${series===3?"团队":dataTa.members[series].displayName} · ${axis.label}：${value}（${value<min?"低于下限":"高于上限"}，标在边界）`);}));
  if(dataTa.target<min || dataTa.target>max)clipped.push(`训练参考线 ${dataTa.target} 在当前刻度之外，切换完整刻度查看。`);
  $ta("radarScaleStatus").textContent=clipped.join("；");$ta("radarScaleStatus").hidden=!clipped.length;
  if(axes.length<3) {wrap.innerHTML='<p class="ta-empty">请选择至少 3 个维度查看雷达图。</p>';return;}
  const svg=svgTa("svg",{viewBox:"0 0 600 500",role:"img","aria-label":`团队及个人标签能力雷达图，刻度 ${min} 至 ${max}，中心为 ${min}；空心点为暂估，证据说明见图下方`});
  const cx=300,cy=245,r=165;
  const point=(i,value,extra=0)=>{const a=-Math.PI/2+i*Math.PI*2/axes.length,radius=r*(Math.max(min,Math.min(max,value))-min)/(max-min)+extra;return [cx+Math.cos(a)*radius,cy+Math.sin(a)*radius];};
  const points=(values)=>values.map((v,i)=>point(i,v).join(",")).join(" ");
  svg.append(svgTa("text",{x:cx+6,y:cy-3,class:"ta-radar-scale"},String(min)));
  for(let value=min+step;value<=max;value+=step) {svg.append(svgTa("polygon",{points:points(axes.map(()=>value)),class:"ta-radar-grid"}));svg.append(svgTa("text",{x:cx+6,y:cy-r*(value-min)/(max-min)-3,class:"ta-radar-scale"},String(value)));}
  axes.forEach((t,i)=>{const [x,y]=point(i,max);svg.append(svgTa("line",{x1:cx,y1:cy,x2:x,y2:y,class:"ta-radar-axis"}));const [lx,ly]=point(i,max,22);const label=svgTa("text",{x:lx,y:ly+4,"text-anchor":Math.abs(lx-cx)<12?"middle":lx>cx?"start":"end",class:"ta-radar-label"},t.label.length>23?t.label.slice(0,21)+"…":t.label);label.append(svgTa("title",{},`${t.label} · 团队 ${numberTa(t.rating)} · ${t.coverageLabel}${t.referenceRating!=null?` · 单人参考 ${t.referenceRating}`:""}`));svg.append(label);});
  if(dataTa.target>=min && dataTa.target<=max)svg.append(svgTa("polygon",{points:points(axes.map(()=>dataTa.target)),class:"ta-radar-target"}));
  [...shownPlayers].sort().forEach(series=>{
    const entries=axes.map(t=>radarValueTa(t,series));
    if(entries.every(p=>p.value!=null && !p.tentative)) svg.append(svgTa("polygon",{points:points(entries.map(p=>Math.min(max,p.value))),fill:colors[series],"fill-opacity":series===3?.1:.025,stroke:colors[series],"stroke-width":series===3?2.5:1.5}));
    else axes.forEach((t,i)=>{const j=(i+1)%axes.length,a=entries[i],b=entries[j];if(a.value!=null && b.value!=null){const [x1,y1]=point(i,Math.min(max,a.value)),[x2,y2]=point(j,Math.min(max,b.value));svg.append(svgTa("line",{x1,y1,x2,y2,stroke:colors[series],"stroke-width":2,...(a.tentative||b.tentative?{"stroke-dasharray":"5 4"}:{})}));}});
    entries.forEach(({value,tentative},i)=>{
      const name=series===3?"团队":dataTa.members[series].displayName;
      if(value==null){const [x,y]=point(i,max,10);const missing=svgTa("text",{x,y:y+4,"text-anchor":"middle",fill:colors[series],"font-size":13},"?");missing.append(svgTa("title",{},`${axes[i].label} · ${name}：暂无可用估计`));svg.append(missing);return;}
      const [x,y]=point(i,Math.min(max,value)),circle=svgTa("circle",{cx:x,cy:y,r:tentative?4:3,fill:tentative?"white":colors[series],stroke:colors[series],"stroke-width":1.5});
      circle.append(svgTa("title",{},`${axes[i].label} · ${name}：${value}${tentative?series===3?"（单人参考，非稳定团队评级）":"（少样本暂估）":""}${value<min||value>max?`（超出 ${min}–${max} 显示范围，标在边界）`:""}`));svg.append(circle);
    });
  });
  wrap.append(svg);
}
function renderRecommendationsTa(axes=dataTa.families) {
  const rows=axes, order={weak:0,specialist:1,unknown:2,developing:3,covered:4};
  const chosen=[...rows].sort((a,b)=>order[a.status]-order[b.status] || (a.rating??0)-(b.rating??0)).slice(0,5);
  $ta("recommendations").innerHTML=chosen.map(t=>{
    const ranked=t.members.map((m,i)=>({...m,name:dataTa.members[i].displayName})).sort((a,b)=>(b.rating??0)-(a.rating??0));
    let advice=t.status==="unknown"?"先补齐个人训练或同步记录，再判断是否短板。建议用 5–8 道有评级的相关题建立基线。":t.status==="specialist"?`${ranked[0].name} 可以主攻；安排另一位队员练习目标附近题目，降低单点依赖。`:t.status==="covered"?"至少两位队员达到目标，可保持训练，把更多时间留给覆盖薄弱的维度。":`优先让第二位队员练习 ${Math.max(800,Math.min(dataTa.target-200,Math.floor((t.rating||dataTa.target-300)/100)*100))}–${dataTa.target} 的相关题，复盘首过前 WA，再逐步提高难度。`;
    return `<article class="ta-advice"><h3>${escapeTa(t.label)} <span class="ta-muted">${numberTa(t.rating)}</span></h3>${chipTa(t)}<p>${escapeTa(advice)}</p></article>`;
  }).join("");
}
function detailTa(m) {
  const dist=Object.entries(m.distribution).sort((a,b)=>Number(a[0])-Number(b[0])), max=Math.max(1,...dist.map(([,v])=>v));
  return `<details><summary>${numberTa(m.rating)} <span class="ta-muted">· AC ${m.solved} / 练 ${m.practiced}</span></summary><div class="ta-member-detail"><p>评级 AC ${m.ratedSolved} · 有效样本 ${m.effectiveSolved} · 置信度 ${Math.round(m.confidence*100)}%${m.reliable?"":" · 样本偏少"}</p>${m.approximateSolved?`<p>含洛谷颜色换算 AC ${m.approximateSolved} 题 · 半权重<br>换算不确定度参考 ±${m.calibrationUncertainty} 分</p>`:""}<p>WA ${m.wa} · 首过前错误 ${m.errors}<br>未过 ${m.unresolved} · 平均尝试 ${numberTa(m.averageTries)}</p><p>最近练习 ${dateTa(m.lastPractice)}<br>${m.ratingSource==="training-anchored-tags"?`能力基线 ${m.abilityBaseline} · 相对调整 ${m.relativeAdjustment==null?"证据不足":m.relativeAdjustment>0?"+"+m.relativeAdjustment:m.relativeAdjustment}`:`错误扣分 ${m.errorPenalty} · 衰减扣分 ${m.memoryPenalty}`}</p>${dist.length?`<div class="ta-mini-hist" aria-label="过题评级分布">${dist.map(([bucket,n])=>`<span style="height:${Math.max(4,n/max*100)}%" title="${bucket}–${Number(bucket)+199}：${n} 题"></span>`).join("")}</div><p>${dist.map(([bucket,n])=>`${bucket}–${Number(bucket)+199}: ${n}`).join(" · ")}</p>`:""}</div></details>`;
}
function renderTableTa() {
  if(!dataTa)return;
  const query=$ta("tagSearch").value.toLowerCase().trim(), evidence=$ta("tagEvidence").value, sort=$ta("tagSort").value;
  const categories=dataTa.categories||dataTa.families;
  const minInput=$ta("tagRatingMin"), maxInput=$ta("tagRatingMax");
  const min=minInput.value===""?null:minInput.valueAsNumber, max=maxInput.value===""?null:maxInput.valueAsNumber;
  const invalid=!minInput.checkValidity() || !maxInput.checkValidity() || (min!=null && max!=null && min>max);
  const compare=(a,b)=>{
    if(sort!=="name") {
      if(a.rating==null && b.rating!=null)return 1;
      if(b.rating==null && a.rating!=null)return -1;
      if(a.rating!=null && b.rating!=null && a.rating!==b.rating)return sort==="rating-asc"?a.rating-b.rating:b.rating-a.rating;
    }
    return a.label.localeCompare(b.label,"zh-CN") || a.key.localeCompare(b.key);
  };
  const rows=invalid?[]:dataTa.tags.filter(t=>
    (`${t.label} ${t.key}`.toLowerCase().includes(query) || categories.some(c=>c.sourceTags.includes(t.key) && `${c.label} ${c.key}`.toLowerCase().includes(query))) &&
    (evidence==="all" || t.status!=="unknown") &&
    (min==null || (t.rating!=null && t.rating>=min)) &&
    (max==null || (t.rating!=null && t.rating<=max))
  ).sort(compare);
  $ta("tagFilterStatus").textContent=invalid?"请输入 0–4000 的有效评级，最低值不能高于最高值。":`显示 ${rows.length} / ${dataTa.tags.length} 个标签。按团队估计评级筛选，区间包含边界；限定区间时不包含暂无团队评级的标签。`;
  const empty=invalid?"请调整评级区间。":"没有匹配的标签，请调整筛选条件。";
  if($ta("tagView").value==="flat") {$ta("tagTable").innerHTML=evidenceTableTa(rows,empty);return;}
  const openGroups=new Set([...$ta("tagTable").querySelectorAll("details[data-evidence-group][open]")].map(el=>el.dataset.evidenceGroup));
  const classified=new Set(categories.flatMap(c=>c.sourceTags));
  const groups=categories.map(c=>({...c,children:rows.filter(t=>c.sourceTags.includes(t.key))}));
  const other=rows.filter(t=>!classified.has(t.key));
  if(other.length)groups.push({key:"unclassified",label:"其他 / 未归类标签",rating:null,children:other});
  const filtering=query!=="" || evidence!=="all" || min!=null || max!=null;
  const visible=invalid?[]:groups.filter(g=>!filtering || g.children.length);
  if(sort!=="name")visible.sort(compare);
  $ta("tagTable").innerHTML=visible.map(g=>`<details class="ta-evidence-group" data-evidence-group="${escapeTa(g.key)}"${openGroups.has(g.key)?" open":""}><summary><span><strong>${escapeTa(g.label)}${g.key==="counting"?"（动态规划 / 组合数学）":""}</strong><small>${g.children.length} 个子标签${g.members?` · ${g.members.map((m,i)=>`${escapeTa(dataTa.members[i].displayName)} AC ${m.ratedSolved}`).join(" / ")}`:""}</small></span><span class="ta-group-rating">${g.coverageLabel?`${numberTa(g.rating)} ${chipTa(g)}`:"未合成大类评级"}</span></summary><p class="ta-muted ta-small">${g.members?"大类汇总按题去重；以下筛选与排序作用于子标签，不重算大类评级。":"这些标签尚未归入标准 12 类，保留原始训练证据。"}${g.sourceNote?` ${escapeTa(g.sourceNote)}`:""}</p><div class="ta-table-wrap">${evidenceTableTa(g.children,"暂无匹配的子标签。")}</div></details>`).join("")||`<p class="ta-empty">${empty}</p>`;
}
function evidenceTableTa(rows,empty) {
  return `<table class="ta-table"><thead><tr><th scope="col">标签</th><th scope="col">团队估计评级 / 覆盖</th>${dataTa.members.map(m=>`<th scope="col">${escapeTa(m.displayName)}</th>`).join("")}</tr></thead><tbody>${rows.map(t=>`<tr><td title="${escapeTa(t.key)}">${escapeTa(t.label)}</td><td><strong>${numberTa(t.rating)}</strong> ${chipTa(t)}${t.referenceRating!=null?`<small>${escapeTa(dataTa.members[t.referenceMember].displayName)} 单人参考 ${t.referenceRating}</small>`:""}${t.evidenceReason?`<small>${escapeTa(t.evidenceReason)}</small>`:""}<small>双人通路 ${numberTa(t.consensusRating)}<br>专长通路 ${numberTa(t.specialistRating)}</small></td>${t.members.map(m=>`<td>${detailTa(m)}</td>`).join("")}</tr>`).join("")||`<tr><td colspan="${dataTa.members.length+2}">${empty}</td></tr>`}</tbody></table>`;
}
function renderRetriesTa() {
  const rows=dataTa.tags.map(t=>{const solved=t.members.reduce((s,m)=>s+m.solved,0);return {...t,solved,avg:t.members.reduce((s,m)=>s+(m.averageTries||0)*m.solved,0)/Math.max(1,solved)};}).filter(t=>t.solved>=3).sort((a,b)=>b.avg-a.avg).slice(0,16),max=Math.max(1,...rows.map(t=>t.avg));
  $ta("retryBars").innerHTML=rows.map(t=>`<div class="ta-retry-row"><span>${escapeTa(t.label)}</span><div class="ta-retry-track"><div class="ta-retry-fill" style="width:${t.avg/max*100}%"></div></div><span>${t.avg.toFixed(1)} <span class="ta-retry-meta">· ${t.solved} 题</span></span></div>`).join("")||'<p class="ta-empty">暂无至少 3 道已通过题的标签数据。</p>';
}
function probabilityTa(row) {return row.probability==null?"—":`${Math.round(row.probability*100)}% <small>范围 ${Math.round(row.probabilityRange[0]*100)}–${Math.round(row.probabilityRange[1]*100)}%</small>`;}
function timeTa(row) {return row.conditionalMinutes==null?"—":`${row.conditionalMinutes} 分钟<small>${row.timeRangeMinutes[0]}–${row.timeRangeMinutes[1]} 分钟 · 解出时</small>`;}
function renderForecastTa() {
  const f=dataTa.forecast, peak=dataTa.peakForecast;$ta("forecastTitle").textContent=`${f.name} · ${f.budgetMinutes} 分钟推演`;
  $ta("forecast").innerHTML=`<div class="ta-metrics"><div class="ta-metric">综合能力推演<strong>${f.expectedSolves} 题</strong></div><div class="ta-metric">敏感性范围<strong>${f.expectedSolvesRange.join("–")} 题</strong></div><div class="ta-metric">可预测题目<strong>${f.predictedProblems}/${f.problems.length}</strong></div><div class="ta-metric">时间基准<strong>${f.timing.source==="heuristic"?"经验先验":"个人历史"} · ${f.timing.samples} 个样本</strong></div></div>${peak?`<p class="ta-muted ta-small">历史峰值参考情景：预计 ${peak.expectedSolves} 题，敏感性范围 ${peak.expectedSolvesRange.join("–")} 题。表示三人恢复各自历史峰值水平；下表使用官方历史与近期训练综合估计。</p>`:""}<div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>题目 / 标签</th><th>经验评级</th><th>限时内通过倾向</th><th>首过条件期望 / 区间</th><th>含失败风险的预算期望</th></tr></thead><tbody>${f.problems.map(p=>`<tr><td>${escapeTa(p.index)} · ${escapeTa(p.name)}<small>${escapeTa((p.tagLabels||p.tags).join(" / ")||"缺少标签 · 使用综合基线")}</small></td><td>${numberTa(p.rating)}<small>${p.ratingRange?p.ratingRange.join("–"):""}</small></td><td>${probabilityTa(p)}<small>${p.probability==null?escapeTa(p.reason):p.tagged?"标签战力":"综合基线"}</small></td><td>${timeTa(p)}</td><td>${p.budgetedMinutes==null?"—":`${p.budgetedMinutes} 分钟`}<small>未解出按 ${f.budgetMinutes} 分钟计</small></td></tr>`).join("")}</tbody></table></div><ul class="ta-muted ta-small">${f.notes.map(n=>`<li>${escapeTa(n)}</li>`).join("")}</ul>`;
}
function renderBacktestTa() {
  const b=dataTa.backtest;$ta("backtestStatus").textContent=b.message;
  $ta("backtest").innerHTML=`${b.metrics.count?`<div class="ta-metrics"><div class="ta-metric">评级题样本<strong>${b.metrics.count}</strong></div><div class="ta-metric">整体 Brier<strong>${numberTa(b.metrics.brier)}</strong></div><div class="ta-metric">有标签题 Brier<strong>${numberTa(b.tagMetricsSummary.brier)}</strong></div><div class="ta-metric">同题综合基线 Brier<strong>${numberTa(b.baselineMetrics.brier)}</strong></div><div class="ta-metric">时间 MAE<strong>${numberTa(b.timeMetrics.maeMinutes)} 分钟 · ${b.timeMetrics.count} 题</strong></div><div class="ta-metric">时间区间命中率<strong>${b.timeMetrics.intervalCoverage==null?"—":Math.round(b.timeMetrics.intervalCoverage*100)+"%"}</strong></div></div><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>比赛 / 日期</th><th>历史阵容</th><th>预计通过 / 实际通过</th><th>回测范围</th><th>Brier</th></tr></thead><tbody>${b.contests.map(c=>`<tr><td>${escapeTa(c.name)}<small>${escapeTa(c.date)}</small></td><td>${c.sameLineup?"当前三人":"当年真实队伍"}</td><td>${c.predictedSolves} / ${c.actualSolves}<details><summary>逐题概率与时间对照</summary>${c.problems.map(p=>`<small>${escapeTa(p.index)} · ${p.rating} · ${p.accepted?"通过":"未通过"} · 倾向 ${Math.round(p.probability*100)}% [${p.probabilityRange.map(v=>Math.round(v*100)).join("–")}%]<br>预计首过 ${p.conditionalMinutes} 分钟 [${p.timeRangeMinutes.join("–")}] · 实际 ${p.actualMinutes==null?"无可靠时间":p.actualMinutes.toFixed(1)+" 分钟"}</small>`).join("")}</details></td><td>评级 ${c.ratedProblems}/${c.totalProblems} 题<small>有标签 ${c.taggedProblems} 题 · ${c.durationMinutes} 分钟赛制</small><small>截断 ${escapeTa(c.date)} 00:00 UTC+8</small></td><td>${c.brier}</td></tr>`).join("")}</tbody></table></div>`:""}
    ${b.probabilityCalibration.some(r=>r.count)?`<h3>概率分桶回测</h3><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>预测概率桶</th><th>样本</th><th>平均预测 / 实际通过率</th><th>敏感性范围</th></tr></thead><tbody>${b.probabilityCalibration.map(r=>`<tr><td>${r.range.map(v=>Math.round(v*100)).join("–")}%</td><td>${r.count}</td><td>${r.count?`${Math.round(r.meanPrediction*100)}% / ${Math.round(r.actualRate*100)}%`:"—"}</td><td>${r.predictedRange?r.predictedRange.map(v=>Math.round(v*100)).join("–")+"%":"—"}</td></tr>`).join("")}</tbody></table></div>`:""}
    ${b.ratingCohorts.length?`<h3>相近战力的历史通过与时间</h3><p class="ta-muted ta-small">仅本人的可回测历史队伍，按当时战力和题目评级分桶；小样本只作观察。实际平均时间只针对有首过时间的 AC。</p><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>队伍战力区间</th><th>题目评级区间</th><th>样本</th><th>预测 / 实际通过率</th><th>预计 / 实际平均首过</th></tr></thead><tbody>${b.ratingCohorts.map(r=>`<tr><td>${r.abilityRange.join("–")}</td><td>${r.difficultyRange.join("–")}</td><td>${r.count}</td><td>${Math.round(r.meanPrediction*100)}% / ${Math.round(r.actualRate*100)}%</td><td>${r.predictedMeanMinutes} / ${numberTa(r.actualMeanMinutes)} 分钟<small>实测 ${r.timedSolves} 题</small></td></tr>`).join("")}</tbody></table></div><p class="ta-muted ta-small">含未解出、按比赛时长截尾的预算期望 MAE：${numberTa(b.timeMetrics.budgetedMaeMinutes)} 分钟。</p>`:""}
    ${b.tagMetrics.length?`<h3>雷达维度诊断</h3><div class="ta-table-wrap"><table class="ta-table"><thead><tr><th>标签</th><th>样本</th><th>标签模型 Brier</th><th>综合基线 Brier</th><th>预测 / 实际通过率</th></tr></thead><tbody>${b.tagMetrics.map(t=>`<tr><td>${escapeTa(t.label||t.tag)}</td><td>${t.count}</td><td>${t.brier}</td><td>${t.baselineBrier}</td><td>${Math.round(t.meanPrediction*100)}% / ${Math.round(t.actualRate*100)}%</td></tr>`).join("")}</tbody></table></div>`:""}
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
$ta("radarScale").addEventListener("change",renderRadarTa);
for(const id of ["tagSearch","tagRatingMin","tagRatingMax"]) $ta(id).addEventListener("input",renderTableTa);
for(const id of ["tagEvidence","tagSort","tagView"]) $ta(id).addEventListener("change",renderTableTa);
$ta("tagReset").addEventListener("click",()=>{
  for(const id of ["tagSearch","tagRatingMin","tagRatingMax"]) $ta(id).value="";
  $ta("tagEvidence").value="all";$ta("tagSort").value="name";renderTableTa();
});
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
