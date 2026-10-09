"use strict";
const el=id=>document.getElementById(id);
const escapeCpc=s=>String(s??"").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let cpcData=null;
async function cpcRequest(path,body){
  const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'请求失败');return data;
}
function cpcRender(){
  const identity=cpcData.identity;
  const statuses={approved:'已认证',pending:'待管理员审核',rejected:'申请已拒绝',revoked:'认证已撤销',unverified:'尚未认证'};
  el('cpcIdentity').textContent=(statuses[identity.status]||identity.status)+(identity.status==='approved'&&identity.verified_until*1000<Date.now()?' · 核验暂时过期，等待恢复同步':'');
  el('cpcClaim').hidden=['approved','pending'].includes(identity.status);
  const selectedMember=el('cpcMember').value;
  el('cpcMember').innerHTML='<option value="">选择成员</option>'+cpcData.members.map(m=>`<option value="${escapeCpc(m.id)}">${escapeCpc(m.name)} · ${escapeCpc(m.school)}</option>`).join('');
  el('cpcMember').value=selectedMember;
  el('cpcHandles').innerHTML=cpcData.handles.map(h=>`<p>${escapeCpc(h.platform)} · ${escapeCpc(h.handle)} <select data-handle="${h.id}"><option value="personal" ${h.kind==='personal'?'selected':''}>个人</option><option value="team" ${h.kind==='team'?'selected':''}>团队</option></select></p>`).join('');
  cpcWall();
}
function cpcWall(){
  const contests=cpcData.contests.filter(c=>String(c.year)===el('cpcYear').value);
  const max=Math.max(1,...contests.map(c=>c.problems.length));let done=0,total=0;
  el('cpcHead').innerHTML='<tr><th>比赛</th><th>进度</th>'+Array.from({length:max},(_,i)=>`<th>${String.fromCharCode(65+i)}</th>`).join('')+'</tr>';
  el('cpcRows').innerHTML=contests.map(c=>{
    let solved=0;const cells=c.problems.map(p=>{
      const s=cpcData.problems[p.id]||{},ok=s.personal||s.onsite||(el('cpcTeams').checked&&s.team);solved+=Number(Boolean(ok));
      const mark=[s.personal?'个':'',s.team?'团':'',s.onsite?'现':''].filter(Boolean).join('');
      const sources=(s.evidence||[]).map(e=>e.team+' · '+e.source).join('\n');
      return `<td style="background:${ok?'#cef0d7':'transparent'}" title="${escapeCpc(p.name+'\n'+sources)}">${escapeCpc(p.index)}${mark?'<br>'+escapeCpc(mark):''}</td>`;
    }).join('');done+=solved;total+=c.problems.length;
    return `<tr><th>${escapeCpc(c.name)}</th><td>${solved}/${c.problems.length}</td>${cells}${'<td></td>'.repeat(max-c.problems.length)}</tr>`;
  }).join('');
  el('cpcSummary').textContent=`确认完成 ${done}/${total} · 名单更新 ${cpcData.roster_checked?new Date(cpcData.roster_checked*1000).toLocaleString():'尚未同步'} · ${cpcData.unmapped_count} 个通过题号待映射`;
}
async function loadCpc(){
  cpcData=await cpcRequest('/api/cpc/me');
  const old=el('cpcYear').value,years=[...new Set(cpcData.contests.map(c=>c.year))].sort((a,b)=>b-a);
  el('cpcYear').innerHTML=years.map(y=>`<option>${y}</option>`).join('');if(years.includes(Number(old)))el('cpcYear').value=old;cpcRender();
}
async function cpcRun(fn){try{await fn();}catch(e){el('cpcMessage').textContent=e.message;}}
document.addEventListener('DOMContentLoaded',()=>{
  cpcRun(loadCpc);
  el('cpcYear').onchange=cpcWall;el('cpcTeams').onchange=cpcWall;
  el('cpcClaim').onsubmit=e=>{e.preventDefault();cpcRun(async()=>{await cpcRequest('/api/cpc/claim',{person:el('cpcMember').value,note:el('cpcNote').value});el('cpcMessage').textContent='申请已提交，等待管理员核验。';await loadCpc();});};
  el('cpcRefresh').onclick=()=>cpcRun(async()=>{await cpcRequest('/api/cpc/refresh',{});await loadCpc();el('cpcMessage').textContent='已安排后台更新，稍后自动显示。';});
  el('cpcToken').onclick=()=>cpcRun(async()=>{const data=await cpcRequest('/api/cpc/token',{});el('cpcCode').value=data.token;el('cpcCode').hidden=false;el('cpcCode').select();});
  el('cpcRevoke').onclick=()=>cpcRun(async()=>{await cpcRequest('/api/cpc/token/revoke',{});el('cpcCode').value='';el('cpcCode').hidden=true;el('cpcMessage').textContent='连接码已撤销。';});
  el('cpcHandles').onchange=e=>{const id=e.target.dataset.handle;if(id)cpcRun(async()=>{await cpcRequest('/api/cpc/handle-kind',{id:Number(id),kind:e.target.value});await loadCpc();});};
  setInterval(()=>{if(!document.hidden)cpcRun(loadCpc);},30000);
});
