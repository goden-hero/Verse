"""Read-only real Verse-test UI probe. Opens but never submits playlist picker.

Uses a temporary normal session, actual API and actual HTML/JS. Blocks all browser
HTTP mutations and external requests. Offscreen Chromium is not Safari/iPhone.
"""
import argparse
import json
import os
from pathlib import Path
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--no-sandbox --disable-gpu --disable-dev-shm-usage'
os.environ.setdefault('QT_LOGGING_RULES', '*.debug=false')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from scripts.verify_live_song_requests import api_session, call, output
from app.auth.sessions import SESSION_COOKIE

parser = argparse.ArgumentParser()
parser.add_argument('--job', default='d99cbb10-ee7d-41ec-890a-89e43cf8788c')
args = parser.parse_args()
checks = r'''(async()=>{
 const expected=__EXPECTED__;
 const wait=async fn=>{for(let i=0;i<300;i++){if(fn())return;await new Promise(r=>setTimeout(r,50));}throw Error('Live UI wait timed out');};
 const check=(v,m)=>{if(!v)throw Error(m);};
 try {
  await wait(()=>currentState.auth.authenticated && discoveryState.jobs.get(expected.id)?.state===expected.state);
  const calls=[],originalFetch=window.fetch;
  window.fetch=(url,...args)=>{calls.push(new URL(url,location.href).pathname);return originalFetch(url,...args);};
  showSearchOverlay(expected.track.artist);
  await wait(()=>document.getElementById('catalogue-search-results').getAttribute('aria-busy')==='false');
  check(catalogueState.results.length>0,'Live MusicBrainz catalogue returned no results');
  check(!calls.some(path=>path.endsWith('/search')||path.includes('/catalogue/recordings/')),'Typing queried local search/availability');
  const list=document.getElementById('catalogue-search-results'),query=document.getElementById('catalogue-search-input').value;
  check(!list.querySelector('button, input'),'Song actions present before selection');
  list.scrollTop=80;const scroll=list.scrollTop;
  const listed=list.querySelector(`[data-recording-id="${expected.track.recording_id}"]`);
  if(listed)listed.click();else openSelectedSong(expected.track);
  await wait(()=>selectedSongState.data&&!selectedSongState.loading);
  const row=document.getElementById('song-action-panel');
  check(selectedSongState.track.recording_id===expected.track.recording_id,'Selected recording mismatch');
  if(expected.state==='ready') {
   check(row.querySelector('[data-discovery-action="play"]'),'Ready Play action absent');
   row.querySelector('[data-discovery-action="add"]').click();
   await wait(()=>manualPlaylistState.open && manualPlaylistState.playlists.length===EXPECTED_PLAYLISTS);
   check(JSON.stringify(manualPlaylistState.songIds)===JSON.stringify([expected.song]),'Wrong playlist song selection');
   const rect=document.getElementById('manual-playlist-dialog').getBoundingClientRect();
   check(rect.left>=0 && rect.right<=innerWidth && rect.top>=0 && rect.bottom<=innerHeight,'Picker outside viewport');
   closeManualPlaylistDialog();
  } else if(expected.state==='failed') {
   check(row.textContent.includes('Failed'),'Terminal failure not shown');
   check(!row.textContent.includes('Resolving recording'),'Failed recording still shown as resolving');
   check(row.querySelector('.external-result-error').textContent,'Failure detail absent');
   check(row.querySelector('[data-discovery-action="retry"]'),'Retry action absent');
  } else {
   check(row.querySelectorAll('[data-discovery-action="choose-version"]').length===expected.options,'Version choices absent');
  }
  closeSelectedSongPanel();
  check(list.scrollTop===scroll&&document.getElementById('catalogue-search-input').value===query,'Return lost query/scroll');
  window.liveProbe={passed:true,width:innerWidth,state:expected.state,song:expected.song,
   catalogue_results:catalogueState.results.length,selected_recording_in_results:Boolean(listed),typing_local_queries:0,
   playlist_choices:EXPECTED_PLAYLISTS,mutations:false,playback_started:false};
 } catch(error) {window.liveProbe={passed:false,error:error.message,
   authenticated:currentState.auth.authenticated,jobs:[...discoveryState.jobs.values()].map(j=>({id:j.id,state:j.state})),
   status:document.getElementById('song-requests-status')?.textContent,
   picker_open:manualPlaylistState.open,playlist_choices:manualPlaylistState.playlists.length};}
})();'''


class ReadOnlyLocal(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        if info.requestUrl().scheme() in ('http', 'https'):
            if info.requestUrl().host() != '127.0.0.1' or bytes(info.requestMethod()) not in (b'GET', b'HEAD'):
                info.block(True)


application = QApplication([])
results = []
with api_session() as client:
    job = call(client, 'GET', '/song-requests/' + args.job)
    assert job['state'] in ('ready', 'failed', 'awaiting_choice'), 'Wait for resolution first.'
    expected = dict(id=job['id'], state=job['state'], title=job['track']['title'],track=job['track'],
                    song=job['song']['id'] if job['song'] else None, options=len(job.get('candidates', [])))
    visible_playlists = call(client, 'GET', '/playlists?limit=100')
    live_checks = checks.replace('__EXPECTED__', json.dumps(expected)).replace('EXPECTED_PLAYLISTS', str(len(visible_playlists)))
    profile = QWebEngineProfile()  # off-the-record; no durable browser cookies
    interceptor = ReadOnlyLocal()
    profile.setUrlRequestInterceptor(interceptor)
    cookie = QNetworkCookie(SESSION_COOKIE.encode(), client.cookies.get(SESSION_COOKIE).encode())
    cookie.setPath('/')
    cookie.setHttpOnly(True)
    profile.cookieStore().setCookie(cookie, QUrl('http://127.0.0.1:8001/'))
    view = QWebEngineView()
    view.setPage(QWebEnginePage(profile, view))
    view.resize(1440, 900)

    def got_result(value):
        if not value:
            QTimer.singleShot(100, poll)
            return
        result = json.loads(value)
        results.append(result)
        output(result)
        if result.get('passed') and len(results) == 1:
            view.resize(390, 844)
            view.reload()
        else:
            application.quit()

    def poll():
        view.page().runJavaScript('window.liveProbe ? JSON.stringify(window.liveProbe) : null', got_result)

    def loaded(ok):
        if not ok:
            application.quit()
            return
        view.page().runJavaScript(live_checks)
        QTimer.singleShot(100, poll)

    view.loadFinished.connect(loaded)
    QTimer.singleShot(45000, application.quit)
    QTimer.singleShot(300, lambda:view.load(QUrl('http://127.0.0.1:8001/')))
    view.show()
    application.exec()
    view.setPage(QWebEnginePage(view))
    profile.deleteLater()
assert len(results) == 2 and all(item.get('passed') for item in results), results
