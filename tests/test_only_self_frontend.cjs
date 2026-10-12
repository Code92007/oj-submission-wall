const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
function node() { return {children: [], innerHTML: '', classList: {toggle() {}}, append(...children) { this.children.push(...children); }, appendChild(child) { this.children.push(child); }}; }
const context = vm.createContext({document: {querySelector(selector) { if (!elements.has(selector)) elements.set(selector,node()); return elements.get(selector); },createElement: node},console});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../web/app.js'),'utf8').replace(/\ninit\(\);\s*$/, ''),context);
vm.runInContext(`
state.user={type:'user',id:'1'};
state.overview={today:'2026-10-08',members:[
 {ownerType:'user',ownerId:'1',displayName:'Me',isCurrent:true,stats:{accepted:1}},
 {ownerType:'user',ownerId:'2',displayName:'Other',isCurrent:false,stats:{accepted:2}}
]};
renderTeamOverview = members => ({ids:members.map(memberKey)});
renderMemberDirectory = members => ({ids:members.map(memberKey)});
state.onlySelf=true;renderMembers();
`,context);
assert.deepEqual(Array.from(elements.get('#members').children.at(-1).ids),['user:1']);
assert.equal(elements.get('#onlySelfCheckbox').checked,true);
vm.runInContext('state.onlySelf=false;renderMembers();',context);
assert.equal(elements.get('#members').children.at(-1).ids.length,2);
vm.runInContext('state.onlySelf=true;state.user=null;renderMembers();',context);
assert.equal(elements.get('#members').children.at(-1).ids.length,2);
assert.equal(elements.get('#onlySelfCheckbox').disabled,true);
console.log('Only-self filter: current account, toggle off and signed-out state passed');
