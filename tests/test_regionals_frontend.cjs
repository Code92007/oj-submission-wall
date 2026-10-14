const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const catalog = JSON.parse(fs.readFileSync(path.join(root, 'catalog/regionals.json'), 'utf8'));
const release = JSON.parse(fs.readFileSync(path.join(root, 'catalog/regional_ratings.json'), 'utf8'));
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {value: '', checked: false, innerHTML: '', textContent: ''});
  return nodes.get(id);
}
const context = vm.createContext({document: {getElementById: element, addEventListener() {}}, catalog, release});
vm.runInContext(fs.readFileSync(path.join(root, 'web/regionals.js'), 'utf8'), context);
vm.runInContext(`cpcData={contests:catalog.contests,difficulty:release.problems,ratingRelease:release,problems:{
  'ccpc-2025-Final:A':{personal:true},'icpc-2025-ECFinal:B':{team:true},
  'icpc-2025-ECFinal:A':{onsite:true}
},unmapped_count:0};`, context);
element('cpcYear').value = '2025';
vm.runInContext('cpcWall()', context);
assert.match(element('cpcSummary').textContent, /13 场比赛 · 2\/167 题完成/);
assert.match(element('cpcRatingCoverage').textContent, /167\/167.*CF Bot/);
assert.match(element('cpcRows').innerHTML, /difficulty-red is-done[^>]*title="[^"]*难度 3300[^"]*已完成/);
assert.match(element('cpcRows').innerHTML, /difficulty-purple is-done[^>]*title="[^"]*难度 2200[^"]*已完成/);
const numbers = Array.from(element('cpcRows').innerHTML.matchAll(/class="cpc-rating" aria-hidden="true">(\d+)<\/span>/g), m => Number(m[1]));
assert.deepEqual(numbers, catalog.contests.filter(c => c.year === 2025).flatMap(c => c.problems.map(p => release.problems[p.id].rating)));
element('cpcTeams').checked = true;
vm.runInContext('cpcWall()', context);
assert.match(element('cpcSummary').textContent, /3\/167 题完成/);
element('cpcYear').value = '2019';
vm.runInContext('cpcWall()', context);
assert.match(element('cpcRows').innerHTML, /difficulty-unknown[^>]*title="[^"]*难度未评级/);
assert.match(element('cpcRows').innerHTML, /class="cpc-rating" aria-hidden="true">—<\/span>/);
assert.doesNotMatch(element('cpcRows').innerHTML, /class="cpc-rating" aria-hidden="true">(?:0|undefined|null)<\/span>/);
assert.match(element('cpcRatingCoverage').textContent, /— 表示暂未评级/);
vm.runInContext('delete cpcData.difficulty; delete cpcData.ratingRelease; cpcWall();', context);
assert.match(element('cpcRatingCoverage').textContent, /0\/149/);
console.log('Regional ratings: released scores, Final colors, AC union, year selection and unrated fallback passed');
