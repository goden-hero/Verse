"""Actual offscreen Chromium DOM; synthetic API/audio, no live data or network."""
import json
import os
from pathlib import Path
import re
import sys

os.environ.setdefault('QT_LOGGING_RULES', '*.debug=false')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--no-sandbox --disable-gpu --disable-dev-shm-usage'
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

root = Path(__file__).resolve().parents[1] / 'app/web'
html = root.joinpath('index.html').read_text()
html = re.sub(r'<link[^>]+(?:fonts\.googleapis|fonts\.gstatic)[^>]*>', '', html)
html = re.sub(r'<link rel="stylesheet" href="index.css[^\"]*">', lambda _: '<style>' + root.joinpath('index.css').read_text() + '</style>', html)
shim = r'''
window.manualApi = {
  songs: Array.from({length:500},(_,i)=>({id:i+1,title:`Song ${String(i+1).padStart(3,'0')}`,artist:`Artist ${(i+1)%5}`,album:`Album ${i+1}`,duration:180,artwork_available:false})),
  playlists: [{id:11,name:'Evening Mix',ids:[1,2]},{id:12,name:'Rainy Day',ids:[]}],
  calls: [], failLists:false, delayedSearch:null, delayAppend:false, pendingAppend:null,
  playCalls:0, pauseCalls:0
};
const reply=(data,status=200)=>({ok:status>=200&&status<300,status,json:async()=>data});
const info=p=>({...p,songs_count:p.ids.length,total_duration:p.ids.length*180,generated_by:'User',strategy:'custom',created_at:'2026-11-02T00:00:00',updated_at:'2026-11-02T00:00:00',songs:p.ids.map(id=>manualApi.songs[id-1])});
window.fetch=async function(url,options={}) {
  const api=manualApi,u=new URL(url,'http://fixture/'),path=u.pathname,method=options.method||'GET';
  api.calls.push({path,url:String(url),method,body:options.body&&JSON.parse(options.body)});
  if(path.endsWith('/auth/me'))return reply({id:1,username:'fixture',display_name:'Fixture'});
  if(path.endsWith('/auth/first-run'))return reply({first_run:false});
  if(path.endsWith('/songs')&&method==='GET'&&!path.includes('/playlists/')) {
    const page=Number(u.searchParams.get('page')||1),size=Number(u.searchParams.get('page_size')||100);
    return reply({songs:api.songs.slice((page-1)*size,page*size),total_count:500,page,page_size:size});
  }
  if(path.endsWith('/search')) {
    if(api.searchFailure==='network')throw new Error('Search network failure');
    if(api.searchFailure==='json')return {ok:true,status:200,json:async()=>{throw new SyntaxError('Invalid search JSON');}};
    if(api.searchFailure==='shape')return reply({unexpected:'shape'});
    if(api.searchFailure==='http')return reply({detail:'Search unavailable'},503);
    const q=u.searchParams.get('q').toLowerCase();
    if(q==='slow old')return new Promise(resolve=>{api.delayedSearch=resolve;});
    return reply(api.songs.filter(s=>[s.title,s.artist,s.album].some(v=>v.toLowerCase().includes(q))));
  }
  if(path.endsWith('/continue-listening'))return reply([]);
  if(path.endsWith('/playlists')&&method==='GET') {
    if(api.failLists)return reply({detail:'Temporary playlist failure'},503);
    const offset=Number(u.searchParams.get('offset')||0),limit=Number(u.searchParams.get('limit')||50);
    return reply(api.playlists.slice(offset,offset+limit).map(info));
  }
  if(path.endsWith('/playlists')&&method==='POST') {
    const payload=JSON.parse(options.body),p={id:Math.max(...api.playlists.map(x=>x.id))+1,name:payload.name,description:payload.description,ids:[...new Set(payload.song_ids)]};
    api.playlists.unshift(p);
    return reply({id:p.id,name:p.name,added_count:p.ids.length,skipped_count:payload.song_ids.length-p.ids.length,songs_count:p.ids.length},201);
  }
  const append=path.match(/\/playlists\/(\d+)\/songs$/);
  if(append&&method==='POST') {
    if(api.appendFailure==='network')throw new Error('Add network failure');
    if(api.appendFailure==='json')return {ok:true,status:200,json:async()=>{throw new SyntaxError('Invalid JSON');}};
    if(api.appendFailure==='shape')return reply({unexpected:'shape'});
    if(api.delayAppend) {api.delayAppend=false;return new Promise(resolve=>{api.pendingAppend=resolve;});}
    const p=api.playlists.find(x=>x.id===Number(append[1])),ids=JSON.parse(options.body).song_ids;
    const additions=[...new Set(ids)].filter(id=>!p.ids.includes(id));p.ids.push(...additions);
    return reply({playlist_id:p.id,added_count:additions.length,skipped_count:ids.length-additions.length,songs_count:p.ids.length});
  }
  const detail=path.match(/\/playlists\/(\d+)$/);
  if(detail)return reply(info(api.playlists.find(x=>x.id===Number(detail[1]))));
  if(path.endsWith('/recommend'))return reply([]);
  return reply({});
};
'''
if '--discovery' in sys.argv:
    shim += Path(__file__).with_name('browser_discovery_fixture.js').read_text()
html = re.sub(r'<script src="index.js[^\"]*"></script>', lambda _: '<script>' + shim + '</script><script>' + root.joinpath('index.js').read_text() + '</script>', html)

checks = r'''
(async()=>{
 const check=(value,message)=>{if(!value)throw new Error(message);};
 const wait=async(fn)=>{for(let i=0;i<400;i++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw new Error('Wait timed out: '+String(fn));};
 const el=id=>document.getElementById(id);
 const search=async query=>{el('search-overlay-input').value=query;el('search-overlay-input').dispatchEvent(new Event('input',{bubbles:true}));await wait(()=>searchState.query===query&&el('search-overlay-results').getAttribute('aria-busy')==='false');};
 const select=id=>{const box=document.querySelector(`.search-result-item[data-song-id="${id}"] input`);check(box,'missing search row '+id);box.click();};
 const openPicker=async()=>{
   el('btn-add-selection').click();await wait(()=>manualPlaylistState.playlists.length||!el('btn-retry-playlist-picker').hidden);
   const rect=el('manual-playlist-dialog').getBoundingClientRect();
   check(rect.left>=0&&rect.right<=innerWidth&&rect.top>=0&&rect.bottom<=innerHeight,'picker outside viewport');
   check(el('btn-confirm-playlist-add').getBoundingClientRect().height>=44,'picker touch target too small');
 };
 const audio=el('main-audio-element');let paused=true;
 Object.defineProperty(audio,'paused',{get:()=>paused});
 audio.play=async()=>{manualApi.playCalls++;paused=false;audio.dispatchEvent(new Event('play'));audio.dispatchEvent(new Event('playing'));};
 audio.pause=()=>{manualApi.pauseCalls++;paused=true;audio.dispatchEvent(new Event('pause'));};
 await wait(()=>currentState.songs.length===100);
 const originalRow=el('songs-table-body').querySelector('tr'),originalAudio=audio;

 if(innerWidth<=767) {
   el('mobile-btn-drawer').click();
   check(el('mobile-drawer-overlay').classList.contains('active'),'mobile drawer did not open');
   el('mobile-drawer-overlay').querySelector('[data-create-manual-playlist]').click();
   check(!el('mobile-drawer-overlay').classList.contains('active'),'mobile drawer masks the new playlist');
 } else document.querySelector('[data-create-manual-playlist]').click();
 check(el('manual-playlist-dialog').open,'creation dialog not open');
 el('manual-playlist-name').value='   ';el('manual-playlist-form').requestSubmit();
 check(el('manual-playlist-error').textContent.includes('blank'),'blank name not rejected');
 check(!manualApi.calls.some(c=>c.method==='POST'&&c.path.endsWith('/playlists')),'blank name posted');
 el('manual-playlist-name').value='Empty Manual';el('manual-playlist-description').value='A description';
 el('manual-playlist-form').requestSubmit();
 await wait(()=>currentPlaylistData?.name==='Empty Manual');
 const emptyId=currentPlaylistData.id;
 check(currentPlaylistData.songs.length===0,'empty playlist changed');
 check(el('btn-playlist-play-all').disabled&&!el('btn-playlist-add-songs').disabled,'empty playlist controls wrong');
 check(el('sidebar-playlists').querySelector(`[data-playlist-id="${emptyId}"]`),'new playlist missing from sidebar');
 check(currentPlaylistData.description==='A description','description lost');
 el('btn-playlist-add-songs').click();
 await search('Album 499');
 check(!currentState.songs.some(s=>s.id===499),'test song is already on loaded library page');
 select(499);check(searchState.selectedSongs.size===1&&manualApi.playCalls===0,'selection starts playback');
 await search('Album 250');select(250);
 check(searchState.selectedSongs.size===2,'changing query discarded selection');
 const searchRow=el('search-overlay-results').firstElementChild;
 searchRow.querySelector('[data-search-play]').click();
 check(manualApi.playCalls===1,'explicit Play unavailable');
 const playingSrc=audio.getAttribute('src');
 await search('Song');
 const untouched=document.querySelector('.search-result-item[data-song-id="250"]');
 select(13);
 check(untouched===document.querySelector('.search-result-item[data-song-id="250"]'),'selection rebuilt unrelated search rows');
 check(originalRow===el('songs-table-body').querySelector('tr'),'selection rebuilt library');
 check(el('search-selection-count').textContent==='3 selected','wrong selection count');
 el('search-overlay-input').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
 el('search-overlay-input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
 check(searchState.selectedSongs.size===4&&manualApi.playCalls===1,'keyboard selection starts playback');
 el('search-overlay-input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
 check(untouched===document.querySelector('.search-result-item[data-song-id="250"]'),'keyboard highlighting rebuilt rows');
 await openPicker();
 el('playlist-picker-search').value='evening';el('playlist-picker-search').dispatchEvent(new Event('input'));
 check(el('playlist-picker-list').querySelectorAll('input').length===1,'playlist name filtering broken');
 el('playlist-picker-list').querySelector('input').click();
 manualApi.delayAppend=true;
 const posts=()=>manualApi.calls.filter(c=>c.method==='POST'&&c.path.endsWith('/songs')).length;
 const before=posts();el('btn-confirm-playlist-add').click();el('btn-confirm-playlist-add').click();
 await wait(()=>manualApi.pendingAppend);
 check(el('btn-confirm-playlist-add').disabled&&posts()===before+1,'duplicate submission was sent');
 check(!closeManualPlaylistDialog(),'pending close unexpectedly returned a result');
 check(manualPlaylistState.open,'pending operation closed');
 manualApi.pendingAppend(reply({detail:'Temporary failure'},503));manualApi.pendingAppend=null;
 await wait(()=>!manualPlaylistState.pending);
 check(manualPlaylistState.open&&searchState.selectedSongs.size===3,'failure lost selection/dialog');
 check(el('manual-playlist-error').textContent.includes('Temporary failure'),'failure not shown');
 check(!el('btn-confirm-playlist-add').disabled,'retry disabled after failure');
 for(const failure of ['network','json','shape']) {
   manualApi.appendFailure=failure;el('btn-confirm-playlist-add').click();
   await wait(()=>!manualPlaylistState.pending);
   check(manualPlaylistState.open&&searchState.selectedSongs.size===3&&!el('manual-playlist-error').hidden,'malformed/failed append lost recovery');
 }
 manualApi.appendFailure=null;
 el('btn-confirm-playlist-add').click();await wait(()=>!manualPlaylistState.open);
 check(JSON.stringify(manualApi.playlists.find(p=>p.id===11).ids)==='[1,2,499,250,13]','append order or existing contents broken');
 check(searchState.selectedSongs.size===0,'successful addition did not clear submitted selection');
 check(el('playlist-notice').textContent.includes('Added 3 songs to Evening Mix'),'confirmation missing');
 await wait(()=>el('sidebar-playlists').querySelector('[data-playlist-id="11"] .playlist-sidebar-count')?.textContent==='5');
 check(audio===originalAudio&&audio.getAttribute('src')===playingSrc&&manualApi.playCalls===1&&manualApi.pauseCalls===0,'search/add interrupted playback');

 // Refresh the currently open destination as well as the sidebar, without navigation.
 hideSearchOverlay();await openPlaylistDetail(11);
 el('btn-playlist-add-songs').click();await search('Album 400');select(400);
 await openPicker();check(manualPlaylistState.destinationId===11,'Add songs did not preselect its playlist');
 el('btn-confirm-playlist-add').click();await wait(()=>currentPlaylistData?.songs.length===6);
 check(currentState.activeTab==='view-playlist-detail','mutation changed navigation');
 await search('Album 499');select(499); // existing track: report skip accurately
 await openPicker();el('btn-confirm-playlist-add').click();await wait(()=>!manualPlaylistState.open);
 check(el('playlist-notice').textContent.includes('Added 0 songs')&&el('playlist-notice').textContent.includes('1 already present'),'skip confirmation incorrect');

 // Create inside the picker and atomically populate it.
 await search('Album 498');select(498);await search('Album 497');select(497);
 await openPicker();el('btn-picker-create').click();
 el('manual-playlist-name').value='Fresh Drives';el('manual-playlist-description').value='Hand picked';
 el('manual-playlist-form').requestSubmit();await wait(()=>!manualPlaylistState.open);
 const fresh=manualApi.playlists.find(p=>p.name==='Fresh Drives');
 check(fresh&&JSON.stringify(fresh.ids)==='[498,497]'&&fresh.description==='Hand picked','create-and-add failed');
 check(searchState.selectedSongs.size===0,'create-and-add kept submitted selection');

 // List loading failures can recover without losing selected songs.
 manualApi.playlists.push(...Array.from({length:110},(_,i)=>({id:1000+i,name:i===109?'Beyond first page':`Archived ${i}`,ids:[]})));
 await search('Album 496');select(496);cancelResource('playlists');manualApi.failLists=true;
 await openPicker();check(!el('btn-retry-playlist-picker').hidden&&searchState.selectedSongs.size===1,'picker failure lost recovery/selection');
 manualApi.failLists=false;el('btn-retry-playlist-picker').click();
 await wait(()=>manualPlaylistState.playlists.length>0);
 check(manualPlaylistState.playlists.length===manualApi.playlists.length,'picker did not load all playlist pages');
 el('playlist-picker-search').value='Beyond first page';el('playlist-picker-search').dispatchEvent(new Event('input'));
 check(el('playlist-picker-list').querySelector('input')?.value==='1109','picker cannot find playlist beyond first page');
 el('btn-close-playlist-dialog').click();check(searchState.selectedSongs.size===1,'cancel discarded selection');
 for(const failure of ['http','network','json','shape']) {
   manualApi.searchFailure=failure;
   el('search-overlay-input').value='Album 495';el('search-overlay-input').dispatchEvent(new Event('input'));
   await wait(()=>!el('btn-retry-song-search').hidden);
   check(searchState.selectedSongs.size===1,'failed search discarded selection');
   manualApi.searchFailure=null;el('btn-retry-song-search').click();
   await wait(()=>searchState.results[0]?.id===495&&el('search-overlay-results').getAttribute('aria-busy')==='false');
   check(el('btn-retry-song-search').hidden,'successful search retry stayed in error state');
 }
 el('btn-clear-song-selection').click();check(searchState.selectedSongs.size===0,'Clear selection failed');

 // Transport ignores abort; changing input invalidates the old request immediately,
 // including the debounce window before the new request starts.
 el('search-overlay-input').value='slow old';el('search-overlay-input').dispatchEvent(new Event('input'));
 await wait(()=>manualApi.delayedSearch);
 const oldResults=searchState.results;
 el('search-overlay-input').value='Album 490';el('search-overlay-input').dispatchEvent(new Event('input'));
 manualApi.delayedSearch(reply([manualApi.songs[0]]));manualApi.delayedSearch=null;
 await new Promise(r=>setTimeout(r,20));check(searchState.results===oldResults,'stale response applied during debounce');
 await wait(()=>searchState.query==='Album 490'&&searchState.results[0]?.id===490);
 check(el('btn-retry-song-search').hidden,'cancellation showed an error');
 await search('no such song');check(el('search-overlay-results').textContent.includes('No matching'),'empty state missing');
 check(originalRow===el('songs-table-body').querySelector('tr')&&audio===el('main-audio-element'),'unrelated library/audio nodes replaced');
 check(el('playlist-generator-form'),'existing generator missing');
 window.manualPlaylistResult={passed:true,width:innerWidth,checks:['empty create/description','blank name','whole-library/album search','persistent selection','explicit play','node preservation','keyboard selection','picker search/viewport/touch targets','pending deduplication','HTTP/network/JSON/shape failure retry','append order/counts','detail/sidebar refresh','duplicate skips','create-and-add','picker retry','search failures/retry','stale/debounced responses','empty search','playback continuity']};
})().catch(error=>{window.manualPlaylistResult={passed:false,error:error.stack||String(error)};});
'''

if '--discovery' in sys.argv:
    checks = Path(__file__).with_name('browser_discovery_checks.js').read_text()


class BlockNetwork(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        if info.requestUrl().scheme() in ('http', 'https'):
            info.block(True)


application = QApplication([])
view = QWebEngineView()
view.resize(1440, 900)
interceptor = BlockNetwork()
view.page().profile().setUrlRequestInterceptor(interceptor)
results = []
mobile_run = False


def poll_result(result):
    global mobile_run
    if not result:
        QTimer.singleShot(100, poll)
        return
    parsed = json.loads(result)
    results.append(parsed)
    print(json.dumps(parsed), flush=True)
    if parsed.get('passed') and not mobile_run:
        mobile_run = True
        view.resize(390, 844)
        view.setHtml(html, QUrl.fromLocalFile(str(root) + '/'))
    else:
        application.quit()


def poll():
    view.page().runJavaScript('window.manualPlaylistResult ? JSON.stringify(window.manualPlaylistResult) : null', poll_result)


def loaded(ok):
    if not ok:
        application.quit()
        return
    view.page().runJavaScript(checks)
    QTimer.singleShot(100, poll)


view.loadFinished.connect(loaded)
QTimer.singleShot(45000, application.quit)
view.setHtml(html, QUrl.fromLocalFile(str(root) + '/'))
view.show()
application.exec()
assert len(results) == 2 and all(r.get('passed') for r in results), results
