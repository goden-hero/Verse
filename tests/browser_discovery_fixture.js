// Synthetic services, real HTML/JS; probe blocks all external network access.
const oldFixtureFetch=window.fetch;
const catalogueTrack=n=>({provider:'musicbrainz',recording_id:`00000000-0000-0000-0000-${String(n).padStart(12,'0')}`,release_id:'22222222-2222-2222-2222-222222222222',title:`Catalogue Song ${n}`,artist:`Catalogue Artist ${n}`,album:`Studio album ${n}`,version:n===4?'live':'',duration:180,artwork_url:null,key:`musicbrainz:00000000-0000-0000-0000-${String(n).padStart(12,'0')}:22222222-2222-2222-2222-222222222222`});
window.discoveryApi={calls:[],jobs:[],pending:[],pendingSelections:[],hold:false,holdSelection:false,failExternal:false,failSelection:false,failRequest:false,loseRequest:false,failChoice:false,clock:Date.parse('2026-11-03T12:00:00Z')};
const requestTick=()=>new Date(++discoveryApi.clock).toISOString();
const cloneReply=(data,status=200)=>reply(JSON.parse(JSON.stringify(data)),status);
const catalogueReply=()=>({provider:'musicbrainz',can_request:true,results:[catalogueTrack(1),catalogueTrack(1),...Array.from({length:29},(_,i)=>catalogueTrack(i+2))]});
function completeFixtureJob(job){
 const song={id:501,title:job.track.title,artist:job.track.artist,album:job.track.album,duration:180,artwork_available:false};
 if(!manualApi.songs.some(s=>s.id===501))manualApi.songs.push(song);
 Object.assign(job,{song,state:'ready',error:null,updated_at:requestTick()});
 for(const intent of job.playlist_intents){const p=manualApi.playlists.find(p=>p.id===intent.playlist_id);if(!p){intent.state='failed';intent.error='Destination no longer available; song is ready.';continue;}if(!p.ids.includes(song.id))p.ids.push(song.id);Object.assign(intent,{state:'added',added_count:1,updated_at:requestTick()});}
}
window.fetch=async(url,options={})=>{
 const api=discoveryApi,u=new URL(url,'http://fixture'),path=u.pathname,method=options.method||'GET';api.calls.push({url:String(url),path,method,body:options.body&&JSON.parse(options.body)});
 if(path.endsWith('/search/external')){
  if(api.failExternal==='network')throw Error('Catalogue network interrupted');
  if(api.failExternal==='json')return {ok:true,json:async()=>{throw SyntaxError('Bad JSON');}};
  if(api.failExternal==='shape')return cloneReply({unexpected:true});
  if(api.failExternal)return cloneReply({detail:'Catalogue temporarily unavailable'},503);
  if(api.hold)return new Promise(resolve=>api.pending.push({url,resolve}));
  return cloneReply(u.searchParams.get('q')==='empty'?{provider:'musicbrainz',can_request:true,results:[]}:catalogueReply());
 }
 if(path.includes('/catalogue/recordings/')){
  const id=path.split('/').pop(),n=Number(id.split('-').pop()),track=catalogueTrack(n),job=api.jobs.find(j=>j.track.recording_id===id);
  const result={track,song:job?.song||(n===1?manualApi.songs[0]:null),job:job||null,can_request:true};
  if(api.failSelection)return cloneReply({detail:'Library check unavailable'},503);
  if(api.holdSelection)return new Promise(resolve=>api.pendingSelections.push({result,resolve}));return cloneReply(result);
 }
 if(!path.includes('/song-requests'))return oldFixtureFetch(url,options);
 if(method==='GET')return cloneReply(path.endsWith('/song-requests')?api.jobs:api.jobs.find(j=>path.endsWith(j.id)));
 if(path.endsWith('/retry')||path.endsWith('/choose-version')){if(api.failChoice)return cloneReply({detail:'Selection temporarily unavailable'},503);const job=api.jobs.find(j=>path.includes(j.id));Object.assign(job,{state:'queued',error:null,updated_at:requestTick(),candidates:[]});return cloneReply(job,202);}
 if(api.failRequest)return cloneReply({detail:'Request temporarily unavailable'},503);
 const payload=JSON.parse(options.body),n=Number(payload.recording_id.split('-').pop()),track=catalogueTrack(n);let job=api.jobs.find(j=>j.track.recording_id===payload.recording_id);
 if(!job){job={id:'request-'+n,key:track.key,track,state:'queued',attempts:0,error:null,song:null,candidates:[],playlist_intents:[],created_at:requestTick(),updated_at:requestTick()};api.jobs.push(job);}
 if(payload.playlist_id&&!job.playlist_intents.some(i=>i.playlist_id===payload.playlist_id)){const p=manualApi.playlists.find(p=>p.id===payload.playlist_id);if(!p)return cloneReply({detail:'Destination playlist no longer exists'},404);job.playlist_intents.push({id:p.id,playlist_id:p.id,playlist_name:p.name,state:'pending',error:null,added_count:0,skipped_count:0,updated_at:requestTick()});job.updated_at=requestTick();}
 if(job.state==='ready')completeFixtureJob(job);
 if(api.loseRequest){api.loseRequest=false;throw Error('Response lost after queueing');}return cloneReply(job,202);
};
