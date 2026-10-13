const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag){this.tag=tag;this.attributes={};this.children=[];this.textContent='';this.hidden=false;this.value='';}
  setAttribute(key,value){this.attributes[key]=String(value);}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
  querySelectorAll(){return [];}
  checkValidity(){return this.valid!==false;}
}
const elements = new Map();
const document = {getElementById(id){if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},createElementNS(ns,tag){return new Element(tag);}};
const context = vm.createContext({document,Intl,Date});
const source = fs.readFileSync(require('node:path').join(__dirname,'../web/team-analysis.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf('$ta("analysisForm").addEventListener')),context);
const person=(rating,reliable)=>({rating,reliable,ratedSolved:reliable?14:3,effectiveSolved:reliable?4.26:.96,distribution:{},confidence:.5});
const axes = Array.from({length:4},(_,i)=>({key:'axis'+i,label:'维度'+i,rating:2100,coverageLabel:'双人覆盖',members:[person(2000,true),person(1900,true),person(2200,true)]}));
axes[1]={...axes[1],label:'几何',rating:null,referenceRating:2004,referenceMember:2,evidenceReason:'仅一人有可靠估计',members:[person(1898,false),person(1717,false),person(2004,true)]};
context.fixture={members:[{displayName:'甲'},{displayName:'乙'},{displayName:'丙'}],target:1900,families:axes,categories:axes,tags:axes};
vm.runInContext('dataTa=fixture;document.getElementById("radarMode").value="families";renderRadarTa()',context);
let svg=elements.get('radar').children[0];
let circles=svg.children.filter(x=>x.tag==='circle');
let reference=circles.find(c=>c.children[0].textContent.includes('单人参考'));
assert(reference,'single-person reference must remain visible');
assert.equal(reference.attributes.fill,'white');
assert(Math.abs(Number(reference.attributes.cx)-(300+165*2004/3500))<1e-8,'reference must be at 2004, not the outer 3500 ring');
assert.equal(svg.children.filter(x=>x.tag==='line' && x.attributes['stroke-dasharray']).length,2,'both adjacent uncertain edges must be dashed');
assert(elements.get('radarEvidence').innerHTML.includes('丙 单人参考 2004'));
vm.runInContext('shownPlayers.clear();shownPlayers.add(0);renderRadarTa()',context);
svg=elements.get('radar').children[0];
reference=svg.children.find(c=>c.tag==='circle' && c.children[0].textContent.includes('少样本暂估'));
assert(reference && reference.attributes.fill==='white','a sparse individual estimate must not look fully supported');
axes[1].referenceRating=null;axes[1].referenceMember=null;
vm.runInContext('shownPlayers.clear();shownPlayers.add(3);renderRadarTa()',context);
svg=elements.get('radar').children[0];
assert.equal(svg.children.filter(x=>x.tag==='circle').length,3,'missing team estimate must have no numerical marker');
assert(svg.children.some(x=>x.tag==='text' && x.textContent==='?'));
vm.runInContext('categorySelected=new Set(["axis0","axis1","axis2"]);document.getElementById("radarMode").value="categories";renderRadarTa()',context);
assert.equal(elements.get('radarCategories').hidden,false);
assert(!elements.get('recommendations').innerHTML.includes('维度3'),'recommendations must follow the selected axes');
assert.equal(elements.get('radarTags').hidden,true);
assert.equal(elements.get('radarCategoryMap').hidden,false);
vm.runInContext('categorySelected.clear();renderRadarTa()',context);
assert(elements.get('radar').innerHTML.includes('至少 3 个维度'));
const tag=(key,label,rating)=>({...axes[0],key,label,rating,status:rating==null?'unknown':'covered'});
context.evidenceFixture={...context.fixture,
  categories:[{...axes[0],key:'counting',label:'计数',sourceTags:['dp','combinatorics']},{...axes[0],key:'number-theory',label:'数论',sourceTags:['number theory','chinese remainder theorem']}],
  tags:[tag('dp','动态规划',2200),tag('combinatorics','组合数学',1800),tag('chinese remainder theorem','中国剩余定理',2100),tag('number theory','数论',null),tag('*special','特殊题目',1700)]};
vm.runInContext('dataTa=evidenceFixture;document.getElementById("tagEvidence").value="all";document.getElementById("tagSort").value="name";document.getElementById("tagView").value="groups";renderTableTa()',context);
let table=elements.get('tagTable').innerHTML;
assert(table.includes('data-evidence-group="counting"') && table.includes('data-evidence-group="number-theory"'));
assert(table.includes('其他 / 未归类标签'),'unclassified evidence must remain visible');
assert(table.includes('计数（动态规划 / 组合数学）'));
assert(table.includes('中国剩余定理'),'CRT must appear under number theory');
assert(!table.includes(' open'),'groups must start collapsed');
elements.get('tagSort').value='rating-desc';
vm.runInContext('renderTableTa()',context);
table=elements.get('tagTable').innerHTML;
assert(table.indexOf('title="dp"')<table.indexOf('title="combinatorics"'),'child tags must follow descending rating');
elements.get('tagSearch').value='数论';
vm.runInContext('renderTableTa()',context);
table=elements.get('tagTable').innerHTML;
assert(!table.includes('data-evidence-group="counting"') && table.includes('中国剩余定理'),'searching a category must include its child tags');
elements.get('tagSearch').value='';elements.get('tagRatingMin').value='2100';elements.get('tagRatingMin').valueAsNumber=2100;
elements.get('tagRatingMax').value='2200';elements.get('tagRatingMax').valueAsNumber=2200;
vm.runInContext('renderTableTa()',context);
table=elements.get('tagTable').innerHTML;
assert(table.includes('title="dp"') && table.includes('title="chinese remainder theorem"'),'inclusive rating bounds must retain boundary tags');
assert(!table.includes('title="number theory"') && !table.includes('title="combinatorics"'));
elements.get('tagRatingMin').value='';elements.get('tagRatingMax').value='';elements.get('tagEvidence').value='reliable';
vm.runInContext('renderTableTa()',context);
assert(!elements.get('tagTable').innerHTML.includes('title="number theory"'),'evidence filter must still work in grouped view');
elements.get('tagEvidence').value='all';elements.get('tagView').value='flat';
vm.runInContext('renderTableTa()',context);
assert(!elements.get('tagTable').innerHTML.includes('data-evidence-group'));
assert(elements.get('tagTable').innerHTML.includes('title="number theory"'),'flat view must retain unknown evidence in view-all mode');
elements.get('tagRatingMin').valid=false;
vm.runInContext('renderTableTa()',context);
assert(elements.get('tagTable').innerHTML.includes('请调整评级区间'));
console.log('Radar and grouped evidence regression passed: reference position, uncertainty, category subsets, grouping, search, sorting and filters.');
