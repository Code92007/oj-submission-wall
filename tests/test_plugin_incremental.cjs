const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
async function scenario(platform, {baseline='100', full=false, failPage=0, differentToken=false, disorder=false} = {}) {
  const site='https://oj-train-wall.wannafly.cn';
  const key=platform==='qoj'?`ojwall:qoj:${site}`:`ojwall:${site}`;
  const store=new Map([[key,{uid:'123',token:'secret'}]]);
  if(baseline!==null)store.set(`${key}:checkpoint`,{uid:'123',token:differentToken?'other':'secret',newestId:baseline});
  const batches=disorder?[[140,130],[90,80],[120,110],[70,60]]:[[130,129],[100,99],[98,97],[96,95]];
  let pages=0,uploads=0;
  const nodes=[];
  const context=vm.createContext({URL,AbortController,setTimeout:callback=>callback(),
    document:{body:{append(){}},createElement(type){const node={type,textContent:'',style:{},setAttribute(){},append(){}};nodes.push(node);return node;}},
    window:{addEventListener(){}},
    GM_getValue:(name,fallback)=>store.has(name)?store.get(name):fallback,
    GM_setValue:(name,value)=>store.set(name,value),GM_deleteValue:name=>store.delete(name),
    GM_xmlhttpRequest:options=>{uploads+=JSON.parse(options.data).records.length;options.onload({status:200,responseText:'{"ok":true}'});},
    fetch:async(url)=>{
      const page=Number(new URL(url,'https://qoj.ac').searchParams.get('page'));pages++;
      if(page===failPage)throw Error('simulated network failure');
      const records=(batches[page-1]||[]).map(id=>({id,submitTime:1000+id,submittedAt:1000+id,user:{uid:123},problem:{pid:'P1000'}}));
      const payload=platform==='qoj'?{list:records,hasNext:page<batches.length}:{currentData:{records:{result:records,count:8,perPage:2}}};
      return{ok:true,url:'https://qoj.ac/submissions',text:async()=>JSON.stringify(payload)};
    }
  });
  let source=fs.readFileSync(path.join(__dirname,`../web/${platform}-sync.user.js`),'utf8').replace('__SITE_JSON__',JSON.stringify(site));
  source=source.replace('  const panel =',`  currentUid = () => '123'; ${platform==='qoj'?'parsePage = text => JSON.parse(text);':'parse = text => JSON.parse(text);'}\n  const panel =`);
  vm.runInContext(source,context);
  await nodes.find(node=>node.textContent===(full?'全量同步':'同步')).onclick();
  return{pages,uploads,checkpoint:store.get(`${key}:checkpoint`),status:nodes.find(node=>node.type==='p').textContent};
}
(async()=>{
  for(const platform of ['qoj','luogu']) {
    let result=await scenario(platform);
    assert.equal(result.pages,3,'stops after two old pages');assert.equal(result.uploads,6);assert.equal(result.checkpoint.newestId,'130');assert.match(result.status,/增量同步完成/);
    result=await scenario(platform,{baseline:null});assert.equal(result.pages,4,'first sync completes history');assert.equal(result.checkpoint.newestId,'130');
    result=await scenario(platform,{full:true});assert.equal(result.pages,4,'full button scans all history');
    result=await scenario(platform,{failPage:2});assert.equal(result.checkpoint.newestId,'100','failed run does not advance checkpoint');
    result=await scenario(platform,{baseline:null,failPage:2});assert.equal(result.checkpoint,undefined,'failed initial sync has no checkpoint');
    result=await scenario(platform,{differentToken:true});assert.equal(result.pages,4,'different authorization cannot reuse baseline');
    result=await scenario(platform,{disorder:true});assert.equal(result.pages,4,'non descending records disable early stop');
  }
  console.log('Incremental sync: two-page overlap, initial history, full override, failure safety, authorization isolation and ordering passed for both platforms');
})().catch(error=>{console.error(error);process.exitCode=1});
