const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const bot = process.env.CPC_BOT_CHECKOUT || path.join(root, '../qq-cf-bot');
for (const source of [path.join(root, 'web/regionals.js'), path.join(bot, 'src/qq_cf_bot/web/regionals.js')]) {
  const context = vm.createContext({document:{addEventListener(){}}});
  vm.runInContext(fs.readFileSync(source,'utf8'), context);
  const contest = {id:'c',problems:['A','B','C','D'].map(index=>({id:index,index}))};
  const difficulty = {A:{rating:2500},B:{rating:800},C:{rating:1800},D:{rating:1200}};
  const stats = {medal_boundaries:{gold:{last_solved:3,last_penalty_minutes:600},silver:{last_solved:2,last_penalty_minutes:400},bronze:{last_solved:1,last_penalty_minutes:100}},medal_safety:{gold:{safe_solved:4},silver:{safe_solved:3},bronze:{safe_solved:1}}};
  const render = () => context.regionalMedalReference(contest,{contests:{c:stats}},difficulty);
  assert.match(render(), /3题 · 1800/);
  assert.match(render(), /4题 · 2500/);
  assert.match(render(), /末位罚时 600/);
  assert.match(render(), /非任意一道题达标即可获牌/);
  const before = render();
  contest.problems.reverse();
  assert.equal(render(), before, 'Reference must not depend on displayed problem order');
  stats.medal_safety.gold.safe_solved=5;
  assert.match(render(), /题数不可达/);
  delete difficulty.A;
  assert.match(render(), /未评级/);
  assert.doesNotMatch(render(), /NaN|undefined|3题 · 1800/);
  assert.match(context.regionalMedalReference(contest,{unrated_contests:{c:'<missing>'}},difficulty), /&lt;missing&gt;/);
  assert.match(context.regionalMedalReference(contest,undefined,undefined), /奖牌线待核验/);
  stats.medal_reference_groups=[{...stats,label:'本科'},{...stats,label:'专科'}];
  assert.match(render(), /本科组[\s\S]*专科组/);
  delete stats.medal_reference_groups;
  difficulty.A={rating:2500};
  stats.medal_safety.bronze.safe_solved=3;
  assert.match(render(), /无独立稳铜档，达到该题数已稳银/);
  assert.match(render(), />—<\/span>/);
  stats.medal_safety.gold.safe_solved=3;
  assert.match(render(), /无独立稳银档，达到该题数已稳金/);
  assert.match(render(), /无独立稳铜档，达到该题数已稳金/);
  stats.medal_reference_groups=[{...stats,label:'本科'},
    {...stats,label:'专科',medal_safety:{gold:{safe_solved:4},silver:{safe_solved:3},bronze:{safe_solved:2}}}];
  const groups=render().split('<small class="medal-group">专科组</small>');
  assert.match(groups[0], /无独立稳铜档/);
  assert.doesNotMatch(groups[1], /无独立稳铜档/);
  const catalog=JSON.parse(fs.readFileSync(path.join(root,'catalog/regionals.json'),'utf8'));
  const release=JSON.parse(fs.readFileSync(path.join(root,'catalog/regional_ratings.json'),'utf8'));
  for(const c of catalog.contests){
    const s=release.contests[c.id];
    if(!s)continue;
    const references=s.medal_reference_groups?.length>1?s.medal_reference_groups:[s];
    const grids=context.regionalMedalReference(c,release,release.problems).match(/<div class="medal-grid">.*?<\/div>/g);
    assert.equal(grids.length,references.length,c.id);
    const ratings=c.problems.map(p=>release.problems[p.id].rating).sort((a,b)=>a-b);
    references.forEach((g,j)=>{
      const cells=[...grids[j].matchAll(/<span title="[^"]*">([^<]*)<\/span>/g)].map(m=>m[1]);
      ['gold','silver','bronze'].forEach((m,i)=>{
        const count=g.medal_safety[m].safe_solved;
        const absent=['gold','silver','bronze'].slice(0,i).some(h=>count>=g.medal_safety[h].safe_solved);
        const expected=absent?'—':count>ratings.length?'题数不可达':`${count}题 · ${ratings[count-1]}`;
        assert.equal(cells[i*2+1],expected,`${c.id}/${g.label||'正式队'}/${m}`);
      });
    });
  }
}
console.log('Both walls: current-rating order statistics, safe bounds, missing data, grouping and escaping passed');
