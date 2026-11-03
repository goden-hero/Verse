// Installed before the application: simulated server state survives UI navigation.
const oldFixtureFetch = window.fetch;
const externalTrack = id => ({key:'spotify:'+id,provider:'spotify',recording_id:id,release_id:'C'.repeat(22),
  title:'Requested recording',artist:'Requested artist',album:'Studio album',version:'',duration:180,artwork_url:null});
window.discoveryApi = {calls:[], jobs:[], pending:[], hold:false, failExternal:false, failPoll:false, loseRequest:false,failChoice:false,clock:Date.parse('2026-11-03T12:00:00Z')};
const requestTick=()=>new Date(++discoveryApi.clock).toISOString();
const savedTrack = externalTrack('B'.repeat(22));
discoveryApi.jobs.push({id:'prior-request',key:savedTrack.key,track:savedTrack,state:'failed',error:'Earlier source failure',attempts:3,
  created_at:'2026-11-01T12:00:00',updated_at:'2026-11-01T12:00:00',next_attempt_at:'2026-11-01T12:00:00',song:null});
const cloneReply = (data,status=200)=>reply(JSON.parse(JSON.stringify(data)),status);
window.fetch = async (url,options={}) => {
  const path=new URL(url,'http://fixture').pathname, method=options.method||'GET',api=discoveryApi;
  if(!path.includes('/song-requests')&&!path.endsWith('/search/external'))return oldFixtureFetch(url,options);
  api.calls.push({url,path,method,body:options.body&&JSON.parse(options.body)});
  if(path.endsWith('/search/external')) {
    if(api.failExternal)return cloneReply({detail:'Catalogue temporarily unavailable'},503);
    if(api.hold)return new Promise(resolve=>api.pending.push({url,resolve}));
    const track=externalTrack('A'.repeat(22));
    const job=api.jobs.find(job=>job.key===track.key);
    return cloneReply({provider:'spotify',can_request:true,results:[{...track,job}]});
  }
  if(method==='GET') {
    if(api.failPoll)throw new Error('Temporary request status network failure');
    return cloneReply(path.endsWith('/song-requests')?api.jobs:api.jobs.find(job=>path.endsWith(job.id)));
  }
  if(path.endsWith('/retry')) {
    const index=api.jobs.findIndex(job=>path.includes(job.id));
    api.jobs[index]={...api.jobs[index],state:'queued',attempts:0,error:null,updated_at:requestTick(),candidates:[]};
    return cloneReply(api.jobs[index]);
  }
  if(path.endsWith('/choose-version')) {
    if(api.failChoice)return cloneReply({detail:'Selection temporarily unavailable'},503);
    const index=api.jobs.findIndex(job=>path.includes(job.id));
    api.jobs[index]={...api.jobs[index],state:'queued',error:null,updated_at:requestTick(),candidates:[]};
    return cloneReply(api.jobs[index],202);
  }
  const payload=JSON.parse(options.body),key='spotify:'+payload.recording_id;
  let job=api.jobs.find(job=>job.key===key);
  if(!job) {
    job={id:'new-request',key,track:externalTrack(payload.recording_id),state:'queued',attempts:0,error:null,
      created_at:'2026-11-02T12:00:00',updated_at:'2026-11-02T12:00:00',next_attempt_at:'2026-11-02T12:00:00',song:null};
    api.jobs.push(job);
  }
  if(api.loseRequest){api.loseRequest=false;throw new Error('Response lost after server queued the request');}
  return cloneReply(job,202);
};
