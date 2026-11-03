"""Offscreen Chromium DOM measurements; stubbed transport, no production writes."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import re
os.environ.setdefault('QT_LOGGING_RULES', '*.debug=false')
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS']='--no-sandbox --disable-gpu --disable-dev-shm-usage'
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

root=Path(__file__).resolve().parents[1] / 'app/web'
baseline = '--baseline' in sys.argv
def read_web(name):
    if baseline:
        return subprocess.check_output(['git','show','a0282bc:app/web/'+name], cwd=root, text=True)
    return root.joinpath(name).read_text()
db=sqlite3.connect('file:' + str(root.parents[1] / 'data/music_rec.db') + '?mode=ro',uri=True)
db.row_factory=sqlite3.Row
songs=[dict(row) for row in db.execute('select id,title,artist,album,duration,original_genre as genre,cover_art is not null as artwork_available from songs order by title')]
playlists=[dict(row) for row in db.execute('select p.id,p.name,p.created_at,(select count(*) from playlist_songs ps where ps.playlist_id=p.id) as songs_count from playlists p where user_id=2 order by updated_at desc limit 50')]
shim='''window.fixture=FIXTURE;
window.fetch=async function(url){const u=String(url);let data=[];
if(u.includes('/auth/me'))data={id:2,username:'pyro',display_name:'Hisham'};
else if(u.includes('/songs?page='))data={songs:fixture.songs.slice(0,100),total_count:fixture.songs.length,page:1,page_size:100};
else if(u.includes('/continue-listening'))data=[];
else if(u.includes('/playlists'))data=u.includes('limit=6')?fixture.playlists.slice(0,6):u.includes('limit=4')?fixture.playlists.slice(0,4):fixture.playlists;
return {ok:true,status:200,json:async()=>data};};
'''.replace('FIXTURE',json.dumps(dict(songs=songs,playlists=playlists)))
html=read_web('index.html')
html=html.replace('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">','')
html=re.sub(r'<link rel="stylesheet" href="index.css[^\"]*">',lambda _: '<style>'+read_web('index.css')+'</style>',html)
html=re.sub(r'<script src="index.js[^\"]*"></script>',lambda _: '<script>'+shim+'</script><script>'+read_web('index.js')+'</script>',html)
app=QApplication([])
view=QWebEngineView()
view.resize(1440,900)

js=r'''JSON.stringify((()=>{
 const results={songs:fixture.songs.length};
 function measure(name,fn){const samples=[];for(let i=0;i<10;i++){const t=performance.now();fn(i);document.body.offsetHeight;samples.push(performance.now()-t);}results[name]=samples.map(x=>Math.round(x*100)/100);}
 results.initialNodes=document.querySelectorAll('*').length;
 measure('render100_ms',()=>renderSongsTable());
 currentState.queue=fixture.songs.slice(0,100);currentState.queueIndex=0;
 measure('queue99_bothDOMs_ms',()=>renderQueueList());
 currentPlaylistData={created_at:'2026-11-01'};
 measure('detail25_ms',()=>renderPlaylistDetailTable(fixture.songs.slice(0,25)));
 measure('track_change100_ms',i=>{currentState.queueIndex=i%2;currentState.currentPlayingSong=fixture.songs[i%2];updatePlaybackUI();updateRightSidebarNowPlaying(fixture.songs[i%2]);renderQueueList();if(typeof updatePlayingRows === 'function') updatePlayingRows();else renderSongsTable();});
 const stableRow=document.querySelector('#songs-table-body tr:nth-child(10)');
 measure('like_dom_ms',i=>{const id=fixture.songs[i%2].id;currentState.likedSongIds.add(id);if(typeof updateLikeButtons === 'function') updateLikeButtons(id);else {updatePlaybackUI();renderSongsTable();}});
 results.unrelatedRowPreserved=stableRow===document.querySelector('#songs-table-body tr:nth-child(10)');
 const art=document.querySelector('#np-large-art img');updatePlaybackUI();results.artworkPreserved=art===document.querySelector('#np-large-art img');
 if(typeof queueViews !== 'undefined') {
   const list=document.getElementById('np-queue-list');
   results.desktopQueueRows=list.querySelectorAll('[data-queue-idx]').length;
   results.hiddenMobileQueueRows=document.querySelectorAll('#mobile-full-queue-list [data-queue-idx]').length;
 }
 const left=document.querySelector('.sidebar-left'), handle=document.getElementById('resizer-left');
 let writes=0;const originalWidth=left.style.width;
 // MutationObserver counts actual width mutations after a burst of mouse events.
 window.resizeObserver=new MutationObserver(records=>window.resizeMutations=(window.resizeMutations||0)+records.length);
 window.resizeObserver.observe(left,{attributes:true,attributeFilter:['style']});
 handle.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,clientX:260}));
 for(let x=261;x<361;x++) document.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientX:x}));
 document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
 results.resizeBurstImmediateWidth=left.style.width;
 currentState.queue=fixture.songs;currentState.queueIndex=0;
 measure('queue433_bothDOMs_ms',()=>renderQueueList());
 currentPlaylistData={created_at:'2026-11-01'};
 measure('detail434_ms',()=>renderPlaylistDetailTable(fixture.songs));
 results.nodesAfter=document.querySelectorAll('*').length;
 results.queueRows=document.querySelectorAll('.sidebar-track-item').length;
 results.imageElements=document.querySelectorAll('img').length;
 results.queueImages=document.querySelectorAll('#np-queue-list img,#mobile-full-queue-list img').length;
 if(typeof queueViews !== 'undefined') {
   const list=document.getElementById('np-queue-list');
   const queue=currentState.queue, length=queue.length, index=currentState.queueIndex;
   list.querySelector('[data-queue-page="1"]').click();
   results.queuePagingCorrect=Number(list.querySelector('[data-queue-idx]').dataset.queueIdx)===index+41 && currentState.queue===queue && queue.length===length && currentState.queueIndex===index;
 }
 return results;
})())'''

ui_checks=r'''
(async()=>{
 const check=(value,message)=>{if(!value)throw new Error(message)};
 const response=data=>({ok:true,status:200,json:async()=>data});
 const originalFetch=window.fetch;
 const row=document.querySelector('#songs-table-body tr:nth-child(10)');
 elements.audio.play=()=>Promise.resolve();
 await playSong(fixture.songs[0],fixture.songs.slice(0,100));
 check(row===document.querySelector('#songs-table-body tr:nth-child(10)'),'playSong rebuilt unrelated rows');
 const art=document.querySelector('#np-large-art img');
 await toggleLikeSong(fixture.songs[0].id);
 check(row===document.querySelector('#songs-table-body tr:nth-child(10)'),'like rebuilt unrelated rows');
 updatePlaybackUI(); check(art===document.querySelector('#np-large-art img'),'artwork replaced for unchanged song');
 const sidebar=document.getElementById('sidebar-playlists'), first=sidebar.firstElementChild;
 window.fetch=async url=>String(url).startsWith('/api/v1/playlists?limit=100')?{ok:false,status:503}:originalFetch(url);
 await loadPlaylists({force:true});
 check(sidebar.firstElementChild===first,'failure cleared successful sidebar');
 check(document.querySelector('#load-error-playlists button'),'missing Retry action');
 window.fetch=originalFetch;
 await document.querySelector('#load-error-playlists button').onclick();
 check(!document.getElementById('load-error-playlists'),'Retry did not recover');
 check(!document.getElementById('load-error-playlists-mobile'),'mobile Retry error persisted');
 check(sidebar.firstElementChild===first,'identical refresh recreated sidebar');
 const waiting={};
 window.fetch=(url,options)=>{
   const match=String(url).match(/^\/api\/v1\/playlists\/(69|70|71)$/);
   return match?new Promise(resolve=>waiting[match[1]]=resolve):originalFetch(url,options);
 };
 const a=openPlaylistDetail(69),b=openPlaylistDetail(70);
 waiting[70](response({id:70,name:'Latest B',created_at:'2026-11-01',songs_count:25,total_duration:60,songs:fixture.songs.slice(0,25)}));await b;
 waiting[69](response({id:69,name:'Stale A',created_at:'2026-11-01',songs:[]}));await a;
 check(currentPlaylistData.id===70,'stale detail replaced newer view');
 const c=openPlaylistDetail(71);elements.navHome.click();
 waiting[71](response({id:71,name:'Stale C',songs:[]}));await c;
 check(currentState.activeTab==='view-home','delayed detail reopened after Home');
 const calls=[]; window.fetch=(...args)=>{calls.push(args[0]);return originalFetch(...args)};
 elements.navHome.click(); await Promise.resolve();
 check(calls.length===0,'active Home unnecessarily reloaded');
 window.fetch=originalFetch;
 window.uiRegressionResult=JSON.stringify({passed:true,checks:['playback nodes','like nodes','artwork reuse','503 content retention','Retry recovery','A-B navigation','Home cancellation','active-view deduplication']});
})().catch(error=>window.uiRegressionResult=JSON.stringify({passed:false,error:error.message}));
'''

captured=[]
def poll_checks():
    def received(value):
        if value:
            captured.append(value);print(value,flush=True);app.quit()
        else: QTimer.singleShot(50,poll_checks)
    view.page().runJavaScript("window.uiRegressionResult || ''",received)

def resize_result(data):
    print(data,flush=True)
    if baseline: app.quit()
    else:
        captured.append(data)
        view.page().runJavaScript(ui_checks)
        QTimer.singleShot(50,poll_checks)

def finish(result):
    captured.append(result)
    print(result,flush=True)
    QTimer.singleShot(250, lambda:view.page().runJavaScript("JSON.stringify({resizeMutations:window.resizeMutations,finalWidth:document.querySelector('.sidebar-left').style.width})", resize_result))
def run(ok):
    if not ok:
        print('HTML load failed',flush=True)
        app.quit()
    else:
        QTimer.singleShot(1000,lambda:view.page().runJavaScript(js,finish))
view.loadFinished.connect(run)
QTimer.singleShot(20000,app.quit)
# All requests are fixture responses; no API mutation or deployment connection.
view.setHtml(html,QUrl.fromLocalFile(str(root)+'/'))
view.show()
app.exec()
assert captured and captured[0], 'Browser script did not complete'
result=json.loads(captured[0])
if not baseline:
    assert result['unrelatedRowPreserved'] and result['artworkPreserved']
    assert result['desktopQueueRows'] <= 40 and result['hiddenMobileQueueRows'] == 0
    assert result['queuePagingCorrect']
    assert json.loads(captured[1])['resizeMutations'] == 1
    assert len(captured) == 3 and json.loads(captured[2])['passed'], captured
