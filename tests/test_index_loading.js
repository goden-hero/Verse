const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app/web/index.js'), 'utf8');
const calls = [];
const context = vm.createContext({
  console, AbortController, setTimeout, clearTimeout,
  document: {getElementById:()=>null, querySelectorAll:()=>[], querySelector:()=>null,
    createElement:()=>({}), head:{appendChild(){}}, addEventListener(){}},
  window: {fetch: (...args)=>context.fetch(...args), addEventListener(){}, removeEventListener(){}},
  fetch(url, options) {
    let resolve, reject;
    const promise = new Promise((yes,no)=>{resolve=yes;reject=no;});
    calls.push({url,options,resolve,reject});
    return promise;
  }
});
vm.runInContext(source, context);
const run = expression => vm.runInContext(expression, context);
const response = data => ({ok:true,status:200,json:async()=>data});

async function main() {
  let a=run("requestJSON('list','/list',isSongList)"), b=run("requestJSON('list','/list',isSongList)");
  assert.equal(calls.length,1);
  calls[0].resolve(response([{id:1,title:'One'}]));
  assert.equal((await a)[0].id,1); assert.equal((await b)[0].id,1);
  await run("requestJSON('list','/list',isSongList)"); assert.equal(calls.length,1);
  a=run("requestJSON('search','/old',isSongList)"); b=run("requestJSON('search','/new',isSongList)");
  assert(calls[1].options.signal.aborted);
  calls[2].resolve(response([{id:2}])); assert.equal((await b)[0].id,2);
  calls[1].resolve(response([{id:1}])); assert.equal(await a,null);
  a=run("requestJSON('search','/failure',isSongList)"); b=run("requestJSON('search','/success',isSongList)");
  calls[4].resolve(response([{id:4}])); await b;
  calls[3].reject(new Error('offline')); assert.equal(await a,null);
  for (const [url, body] of [['/503',{ok:false,status:503}],['/bad-json',{ok:true,json:async()=>{throw new SyntaxError('JSON')}}],['/shape',response({detail:'wrong'})]]) {
    const promise=run(`requestJSON('failure', '${url}', isSongList)`);
    calls.at(-1).resolve(body); await assert.rejects(promise);
    const retry=run(`requestJSON('failure', '${url}', isSongList, {force:true})`);
    calls.at(-1).resolve(response([{id:9}])); assert.equal((await retry)[0].id,9);
  }
  // Exercise the real detail loader: cancellation alone is insufficient because
  // a transport/cache may still resolve the old response.
  run("currentState.auth.authenticated=true");
  a=run('openPlaylistDetail(69)'); b=run('openPlaylistDetail(70)');
  const first=calls.at(-2), second=calls.at(-1);
  second.resolve(response({id:70,name:'B',songs:[],created_at:'2026-11-01'})); await b;
  first.resolve(response({id:69,name:'A',songs:[],created_at:'2026-11-01'})); await a;
  assert.equal(run('currentPlaylistData.id'),70);
  a=run('openPlaylistDetail(71)');
  run("navigationGeneration++; currentState.activeTab='view-home'; cancelResource('detail')");
  calls.at(-1).resolve(response({id:71,name:'C',songs:[]})); await a;
  assert.equal(run('currentState.activeTab'),'view-home');
  console.log('Loading regressions passed: deduplication, stale successes/errors, malformed responses, retry, navigation cancellation.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
