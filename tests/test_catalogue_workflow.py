"""Catalogue-only typing and durable download/playlist intent contracts."""
import asyncio
import json
import httpx
from sqlalchemy import event
from test_discovery_requests import environment, track, mb_selection, make_audio, FakeAdapter, response, MBID, RELEASE
from app.api.server import app
from app.auth.sessions import SESSION_COOKIE
from app.database.models import Song, SongRequest, SongRequestPlaylist, PlaylistSong
from app.discovery import catalogue
from app.discovery.catalogue import Catalogue, cache_put, identity
from app.discovery.acquisition import SpotDLAdapter
from app.discovery.worker import RequestWorker, recover_interrupted
from app.discovery.playlist_intents import fulfill_ready_intents
from app.indexing.single_file import index_single_file


def selected(env, **changes):
    item = mb_selection(**changes)
    cache_put('selection:' + item['key'], item, 3600)
    return item


def request(env, playlist_id=None, item=None):
    item = item or selected(env)
    payload = {k:item[k] for k in ('provider','recording_id','release_id')}
    if playlist_id is not None: payload['playlist_id'] = playlist_id
    result = env.client.post('/api/v1/song-requests', json=payload)
    assert result.status_code == 202, result.text
    return result.json()


def playlist(env):
    result = env.client.post('/api/v1/playlists', json={'name':'Evening mix'})
    assert result.status_code == 201
    return result.json()['id']


def test_typing_search_forces_musicbrainz_without_any_local_availability_queries(environment, monkeypatch):
    env=environment; monkeypatch.setenv('VERSE_CATALOGUE','spotify')
    monkeypatch.setenv('VERSE_SPOTIFY_CLIENT_ID','present'); monkeypatch.setenv('VERSE_SPOTIFY_CLIENT_SECRET','present')
    seen=[]; sql=[]
    def search(self, query):
        seen.append((self.config.catalogue, query)); return [mb_selection()]
    monkeypatch.setattr(Catalogue,'search',search)
    event.listen(env.engine,'before_cursor_execute',lambda conn,cursor,statement,*args:sql.append(statement.lower()))
    result=env.client.get('/api/v1/search/external?q=Selected')
    assert result.status_code==200 and result.json()['provider']=='musicbrainz'
    assert seen==[('musicbrainz','Selected')]
    assert 'song' not in result.json()['results'][0] and 'job' not in result.json()['results'][0]
    assert not any('from songs' in s or 'from song_sources' in s or 'from song_requests' in s for s in sql)


def test_catalogue_deduplicates_recording_mbid_not_titles_or_versions(environment,monkeypatch):
    record={'id':MBID,'title':'Same title','artist-credit':[{'name':'Artist'}],'length':200000,
            'releases':[{'id':RELEASE,'title':'Album'}]}
    other={**record,'id':'33333333-3333-3333-3333-333333333333','disambiguation':'live'}
    monkeypatch.setattr(catalogue.requests,'get',lambda *a,**k:response({'recordings':[record,record,other]}))
    results=Catalogue(environment.config).search('Same title')
    assert len(results)==2 and results[1]['version']=='live'


def test_musicbrainz_error_does_not_suggest_spotify_configuration(environment,monkeypatch):
    monkeypatch.setattr(catalogue.requests,'get',lambda *a,**k:response({},403))
    result=environment.client.get('/api/v1/search/external?q=Denied')
    assert result.status_code==503 and 'MusicBrainz' in result.json()['detail']
    assert 'Spotify' not in result.json()['detail']


def test_selection_checks_identifiers_after_click_and_does_not_queue(environment,monkeypatch):
    env=environment;item=selected(env)
    path=make_audio(env.config.music_dir/'old.wav')
    with env.factory() as db:
        song_id=index_single_file(path,track(),[track()['key']],db);db.commit()
    calls=[]
    def resolve(self, selection):calls.append(selection['recording_id']);return track()
    monkeypatch.setattr(SpotDLAdapter,'resolve',resolve)
    url=f'/api/v1/catalogue/recordings/{MBID}?release_id={RELEASE}'
    result=env.client.get(url)
    assert result.status_code==200 and result.json()['song']['id']==song_id
    assert calls==[MBID]
    with env.factory() as db:assert db.query(SongRequest).count()==0
    assert env.client.get(url).json()['song']['id']==song_id and calls==[MBID]  # cached resolution


def test_download_then_add_is_persistent_ordered_and_idempotent(environment):
    env=environment;pid=playlist(env)
    old=make_audio(env.config.music_dir/'older.wav')
    with env.factory() as db:
        old_id=index_single_file(old,track(),[],db);db.add(PlaylistSong(playlist_id=pid,song_id=old_id,position=7));db.commit()
    # Different hash/tag fixture so the new indexed song is not content-deduped.
    old.write_bytes(old.read_bytes()+b'original file trailer')
    with env.factory() as db:db.get(Song,old_id).hash='original-hash';db.commit()
    job=request(env,pid)
    assert job['playlist_intents'][0]['state']=='pending'
    recover_interrupted()
    worker=RequestWorker(env.config,FakeAdapter(env.config));worker.run_once()
    ready=env.client.get('/api/v1/song-requests/'+job['id']).json()
    assert ready['state']=='ready' and ready['playlist_intents'][0]['state']=='added'
    sid=ready['song']['id'];assert sid!=old_id
    with env.factory() as db:
        assert db.query(PlaylistSong.song_id,PlaylistSong.position).filter_by(playlist_id=pid).order_by(PlaylistSong.position).all()==[(old_id,7),(sid,8)]
    again=request(env,pid)
    assert again['id']==job['id'] and again['playlist_intents'][0]['state']=='added'
    assert not fulfill_ready_intents()
    with env.factory() as db:assert db.query(SongRequestPlaylist).count()==1


def test_failed_download_retains_destination_and_retry_adds_once(environment):
    env=environment;pid=playlist(env);job=request(env,pid);adapter=FakeAdapter(env.config,fail=1)
    worker=RequestWorker(env.config,adapter);worker.run_once()
    with env.factory() as db:
        stored=db.get(SongRequest,job['id']);stored.state='failed';db.commit()
    failed=env.client.get('/api/v1/song-requests/'+job['id']).json()
    assert failed['playlist_intents'][0]['playlist_id']==pid
    retry=env.client.post('/api/v1/song-requests/'+job['id']+'/retry').json()
    assert retry['error'] is None and retry['playlist_intents'][0]['state']=='pending'
    worker.run_once()
    ready=env.client.get('/api/v1/song-requests/'+job['id']).json()
    assert ready['state']=='ready' and ready['playlist_intents'][0]['state']=='added'


def test_deleted_destination_does_not_lose_ready_song_or_acquisition_state(environment):
    env=environment;pid=playlist(env);job=request(env,pid)
    assert env.client.delete(f'/api/v1/playlists/{pid}').status_code==204
    adapter=FakeAdapter(env.config);RequestWorker(env.config,adapter).run_once()
    ready=env.client.get('/api/v1/song-requests/'+job['id']).json()
    assert ready['state']=='ready' and ready['song'] and ready['error'] is None
    intent=ready['playlist_intents'][0]
    assert intent['playlist_id']==pid and intent['state']=='failed' and 'no longer available' in intent['error']
    stream=env.client.get(f'/api/v1/songs/{ready["song"]["id"]}/stream');assert stream.status_code==200
    assert adapter.downloads==1


def test_deleted_playlist_id_reuse_is_not_a_valid_original_destination(environment):
    env=environment;pid=playlist(env);job=request(env,pid)
    env.client.delete(f'/api/v1/playlists/{pid}')
    replacement=env.client.post('/api/v1/playlists',json={'name':'Unrelated replacement'}).json()['id']
    assert replacement==pid  # SQLite rowid reuse, not identity continuity.
    RequestWorker(env.config,FakeAdapter(env.config)).run_once()
    ready=env.client.get('/api/v1/song-requests/'+job['id']).json()
    assert ready['state']=='ready' and ready['playlist_intents'][0]['state']=='failed'
    assert env.client.get(f'/api/v1/playlists/{replacement}').json()['songs']==[]


def test_failed_append_rolls_back_membership_and_can_retry_without_reacquisition(environment,monkeypatch):
    from app.services.playlist import PlaylistService
    env=environment;pid=playlist(env);job=request(env,pid);original=PlaylistService.append_songs_to_playlist
    def fail_after_append(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('Injected interruption before intent completion')
    adapter=FakeAdapter(env.config)
    with monkeypatch.context() as patch:
        patch.setattr(PlaylistService,'append_songs_to_playlist',fail_after_append)
        RequestWorker(env.config,adapter).run_once()
    ready=env.client.get('/api/v1/song-requests/'+job['id']).json()
    assert ready['state']=='ready' and ready['playlist_intents'][0]['state']=='failed'
    with env.factory() as db:assert db.query(PlaylistSong).filter_by(playlist_id=pid).count()==0
    retried=request(env,pid)
    assert retried['playlist_intents'][0]['state']=='added' and adapter.downloads==1


def test_missing_ready_song_does_not_spin_pending_intent_worker(environment):
    env=environment;pid=playlist(env);job=request(env,pid)
    with env.factory() as db:
        row=db.get(SongRequest,job['id']);row.state='ready';row.song_id=None;db.commit()
    assert fulfill_ready_intents()
    assert not fulfill_ready_intents()
    with env.factory() as db:
        assert db.get(SongRequest,job['id']).state=='failed'
        assert db.query(SongRequestPlaylist).one().state=='pending'


def test_ready_pending_intent_recovers_after_restart_without_download(environment):
    env=environment;job=request(env);adapter=FakeAdapter(env.config);worker=RequestWorker(env.config,adapter);worker.run_once()
    pid=playlist(env)
    # Simulate interruption after persisting the destination, before append.
    from app.discovery.playlist_intents import attach_intent
    from app.identity import CurrentUser
    with env.factory() as db:attach_intent(db,db.get(SongRequest,job['id']),pid,CurrentUser(1,'fixture'));db.commit()
    recover_interrupted();worker.run_once()
    assert adapter.downloads==1
    assert env.client.get('/api/v1/song-requests/'+job['id']).json()['playlist_intents'][0]['state']=='added'


def test_concurrent_request_intents_and_release_variants_reuse_job(environment):
    env=environment;pid=playlist(env);first=selected(env)
    rid='44444444-4444-4444-4444-444444444444'
    alternate=selected(env,key=identity('musicbrainz',MBID,rid),release_id=rid)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',cookies={SESSION_COOKIE:env.client.cookies.get(SESSION_COOKIE)}) as client:
            results=await asyncio.gather(*(client.post('/api/v1/song-requests',json={
                'provider':'musicbrainz','recording_id':MBID,'release_id':item['release_id'],'playlist_id':pid}) for item in [first,alternate,first,alternate,first]))
            assert all(r.status_code==202 for r in results)
            assert len({r.json()['id'] for r in results})==1
    asyncio.run(run())
    with env.factory() as db:assert db.query(SongRequest).count()==1 and db.query(SongRequestPlaylist).count()==1


def test_invalid_destination_does_not_create_request(environment):
    env=environment;item=selected(env)
    payload={k:item[k] for k in ('provider','recording_id','release_id')}
    assert env.client.post('/api/v1/song-requests',json={**payload,'playlist_id':999999}).status_code==404
    assert env.client.post('/api/v1/song-requests',json={**payload,'playlist_id':-1}).status_code==422
    with env.factory() as db:assert db.query(SongRequest).count()==0 and db.query(SongRequestPlaylist).count()==0
