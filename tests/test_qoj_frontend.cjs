const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try {
 const page=await browser.newPage();
 const source=fs.readFileSync(require('path').join(__dirname,'../web/qoj-sync.user.js'),'utf8')
   .replace('__SITE_JSON__','"https://oj-train-wall.wannafly.cn"')
   .replace("  const panel = document.createElement('div');", '  globalThis.qojTest = {parsePage,currentUid}; return;\n  const panel = document.createElement(\'div\');');
 await page.addScriptTag({content:source});
 const results=await page.evaluate(()=>{
   const header='<nav class="navbar"><a class="dropdown-item" href="/user/profile/ucup-team123">Profile</a></nav>';
   const row='<tr><td><a href="/submission/123">#123</a></td><td><a href="/problem/42">#42. Test</a></td><td><a href="/user/profile/ucup-team123">ucup-team123</a></td><td>100 ✓</td><td>10 ms</td><td>1 MB</td><td>C++20</td><td>1 KB</td><td>2026-10-08 12:00:00</td></tr>';
   const html=header+'<table><tbody>'+row+'</tbody></table><a href="/submissions?submitter=ucup-team123&amp;page=2">2</a><footer>Server Time: 2026-10-08 12:00:00 (UTC+8)</footer>';
   const parsed=qojTest.parsePage(html,'ucup-team123',1);
   if(parsed.list.length!==1 || parsed.list[0].problemId!=='42' || !parsed.hasNext || parsed.list[0].submittedAt!==Date.parse('2026-10-08T04:00:00Z')/1000) throw Error('row/time/pagination');
   const plainID=html.replace('<a href="/submission/123">#123</a>','#123');
   if(qojTest.parsePage(plainID,'ucup-team123',1).list[0].id!=='123') throw Error('plain submission ID');
   const plainUser=plainID.replace('<td><a href="/user/profile/ucup-team123">ucup-team123</a></td>','<td>ucup-team123</td>');
   if(qojTest.parsePage(plainUser,'ucup-team123',1).list[0].submitter!=='ucup-team123') throw Error('plain submitter');
   const markedUser=plainID.replace('<td><a href="/user/profile/ucup-team123">ucup-team123</a></td>', '<td><a href="user/profile/ucup-team123">ucup-team123</a><a href="/submissions?submitter=ucup-team123">#</a></td>');
   if(qojTest.parsePage(markedUser,'ucup-team123',1).list[0].submitter!=='ucup-team123') throw Error('relative profile plus filter marker');
   const plainMarked=plainUser.replace('<td>ucup-team123</td>','<td>ucup-team123<a href="#">#</a></td>');
   if(qojTest.parsePage(plainMarked,'ucup-team123',1).list[0].submitter!=='ucup-team123') throw Error('separate decorative marker');
   const filterOnly=plainID.replace('<td><a href="/user/profile/ucup-team123">ucup-team123</a></td>', '<td>ucup-team123<a href="/submissions?submitter=ucup-team123">#</a></td>');
   if(qojTest.parsePage(filterOnly,'ucup-team123',1).list[0].submitter!=='ucup-team123') throw Error('filter-link username');
   const literalHash=plainUser.replace('<td>ucup-team123</td>','<td>ucup-team123#</td>');
   let literalRejected=false;try{qojTest.parsePage(literalHash,'ucup-team123',1)}catch(_){literalRejected=true;}
   if(!literalRejected)throw Error('literal malformed username was stripped');
   const otherMarked=markedUser.replaceAll('user/profile/ucup-team123','user/profile/other').replace('/submissions?submitter=ucup-team123">#','/submissions?submitter=other">#');
   let otherRejected=false;try{qojTest.parsePage(otherMarked,'ucup-team123',1)}catch(_){otherRejected=true;}
   if(!otherRejected)throw Error('other decorated account accepted');
   const contest=plainID.replace('/problem/42','/contest/888/problem/42');
   if(qojTest.parsePage(contest,'ucup-team123',1).list[0].problemId!=='42') throw Error('contest problem');
   const noProblemLink=plainID.replace('<a href="/problem/42">#42. Test</a>','#42. Test');
   if(qojTest.parsePage(noProblemLink,'ucup-team123',1).list[0].problemId!=='42') throw Error('plain numbered problem');
   const wrongUser=plainUser.replace('<td>ucup-team123</td>','<td>other</td>');
   let accountError='';try{qojTest.parsePage(wrongUser,'ucup-team123',1)}catch(e){accountError=e.message;}
   if(!accountError.includes('other') || !accountError.includes('ucup-team123')) throw Error('account mismatch detail');
   const empty=qojTest.parsePage(header+'<table><tbody><tr><td colspan="233">None</td></tr></tbody></table>','ucup-team123',1);
   if(empty.list.length || empty.hasNext) throw Error('empty');
   for(const broken of [html.replaceAll('ucup-team123','other'),html.replace('/problem/42','/bad/42').replace('#42. Test','Hidden problem'),'<input type="password">',header+'<div>Cloudflare challenge</div>']) {
     let failed=false;try{qojTest.parsePage(broken,'ucup-team123',1);}catch(_){failed=true;}if(!failed)throw Error('invalid accepted');
   }
   return 'QOJ DOM parsing: rows, UTC+8, pagination, empty state, account mismatch, login and malformed page passed';
 });
 console.log(results);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
