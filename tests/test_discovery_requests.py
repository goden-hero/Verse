"""Real SQLite queue/API/indexing; all external catalogue/download I/O mocked."""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import wave
import fcntl
import os
import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient
from mutagen.id3 import COMM, TALB, TIT2, TPE1, WOAS
from mutagen.wave import WAVE
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import sessionmaker

from app.api.server import app
from app.auth.sessions import SESSION_COOKIE, SessionService
from app.database import connection
from app.database.models import Base, CatalogueBudget, Song, SongRequest, SongSource, User
from app.discovery import catalogue
from app.discovery.acquisition import SpotDLAdapter, same_recording
from app.discovery.catalogue import Catalogue, DiscoveryError, cache_put, identity, musicbrainz_track
from app.discovery.config import DiscoveryConfig
from app.discovery.jobs import request_song
from app.discovery.worker import RequestWorker, checkpoint, recover_interrupted
from app.discovery.resolution import ChooseRecording, NoSuitableRecording, select_metadata_candidate
from app.indexing.single_file import index_single_file, verify_audio_file

SPOTIFY_ID = 'A' * 22
MBID = '11111111-1111-1111-1111-111111111111'
RELEASE = '22222222-2222-2222-2222-222222222222'


def track(track_id=SPOTIFY_ID):
    return dict(key='spotify:' + track_id, provider='spotify', recording_id=track_id, release_id='B'*22,
                title='Selected Song', artist='Selected Artist', album='Selected Album', duration=1.0,
                version='', artwork_url=None, isrcs=['USABC2500001'])


def audio_source():
    return {**{key:track()[key] for key in ('title','artist','album','duration')},
            'url':'https://music.youtube.com/watch?v=ABCDEFGHIJK'}


def response(data, status=200, headers=None):
    return SimpleNamespace(ok=200 <= status < 300, status_code=status, headers=headers or {}, json=lambda: data)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'requests.db'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(connection, 'SessionFactory', factory)
    monkeypatch.setenv('VERSE_MUSIC_DIR', str(tmp_path / 'music'))
    monkeypatch.setenv('VERSE_CATALOGUE_CONTACT', 'tests@example.invalid')
    monkeypatch.setenv('VERSE_CATALOGUE', 'musicbrainz')
    # Any accidental live catalogue/network access makes the tests fail.
    monkeypatch.setattr(catalogue.requests, 'get', lambda *a, **k: pytest.fail('Unexpected external GET'))
    monkeypatch.setattr(catalogue.requests, 'post', lambda *a, **k: pytest.fail('Unexpected external POST'))
    with factory() as db:
        user = db.get(User, 1)
        user.password_hash = 'fixture-password-hash'
        db.commit(); token = SessionService.create(user, db)
    cache_put('selection:' + track()['key'], track(), 3600)
    assert not app.dependency_overrides
    try:
        with TestClient(app) as client:
            client.cookies.set(SESSION_COOKIE, token)
            yield SimpleNamespace(client=client, factory=factory, config=DiscoveryConfig.load(), engine=engine)
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def make_audio(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000); audio.writeframes(b'\0\0' * 8000)
    tagged = WAVE(path); tagged.add_tags()
    tagged.tags.add(TIT2(encoding=3, text='Selected Song'))
    tagged.tags.add(TPE1(encoding=3, text='Selected Artist'))
    tagged.tags.add(TALB(encoding=3, text='Selected Album'))
    tagged.tags.add(WOAS(url='https://open.spotify.com/track/' + SPOTIFY_ID))
    tagged.save()
    return path


class FakeAdapter(SpotDLAdapter):
    def __init__(self, config, fail=0):
        super().__init__(config)
        self.downloads = 0; self.resolutions = 0; self.fail = fail
    def resolve(self, selected):
        self.resolutions += 1
        return track()
    def download(self, resolved):
        self.downloads += 1
        if self.fail:
            self.fail -= 1
            raise DiscoveryError('Mock source unavailable')
        return make_audio(self.config.music_dir / '.verse-requests' / SPOTIFY_ID / 'track.wav')
    def publish(self, path, resolved):
        verify_audio_file(path, resolved)
        return path


def enqueue(env):
    result = env.client.post('/api/v1/song-requests', json={'provider':'spotify','recording_id':SPOTIFY_ID})
    assert result.status_code == 202, result.text
    return result.json()['id']


def due(env, job_id):
    with env.factory() as db:
        db.execute(update(SongRequest).where(SongRequest.id == job_id).values(next_attempt_at=datetime.utcnow()-timedelta(seconds=1)))
        db.commit()


def test_successful_request_indexes_one_file_and_is_playable(environment):
    env = environment
    job_id = enqueue(env)
    adapter = FakeAdapter(env.config)
    assert RequestWorker(env.config, adapter).run_once()
    result = env.client.get('/api/v1/song-requests/' + job_id)
    assert result.status_code == 200
    job = result.json()
    assert job['state'] == 'ready' and job['song']['title'] == 'Selected Song'
    song_id = job['song']['id']
    stream = env.client.get(f'/api/v1/songs/{song_id}/stream')
    assert stream.status_code == 200 and stream.content.startswith(b'RIFF')
    assert env.client.get('/api/v1/search?q=Selected').json()[0]['id'] == song_id
    playlist = env.client.post('/api/v1/playlists', json={'name':'Requested music'}).json()['id']
    assert env.client.post(f'/api/v1/playlists/{playlist}/songs', json={'song_ids':[song_id]}).json()['added_count'] == 1
    assert enqueue(env) == job_id
    with env.factory() as db:
        assert db.query(Song).count() == 1
        assert db.get(SongSource, track()['key']).song_id == song_id
    assert adapter.downloads == 1


def test_concurrent_duplicate_requests_share_one_persistent_job(environment):
    env = environment
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', cookies={SESSION_COOKIE:env.client.cookies.get(SESSION_COOKIE)}) as client:
            responses = await asyncio.gather(*(client.post('/api/v1/song-requests', json={'provider':'spotify','recording_id':SPOTIFY_ID}) for _ in range(5)))
            assert all(r.status_code == 202 for r in responses)
            assert len({r.json()['id'] for r in responses}) == 1
    asyncio.run(run())
    with env.factory() as db: assert db.query(SongRequest).count() == 1


def test_exact_existing_source_reuses_library_entry(environment):
    env = environment
    path = make_audio(env.config.music_dir / 'existing.wav')
    with env.factory() as db:
        song_id = index_single_file(path, track(), [track()['key']], db); db.commit()
    job_id = enqueue(env)
    assert env.client.get('/api/v1/song-requests/' + job_id).json()['song']['id'] == song_id
    assert not RequestWorker(env.config, FakeAdapter(env.config)).run_once()


def test_failed_download_retries_are_bounded_and_retry_is_persistent(environment):
    env = environment; job_id = enqueue(env)
    adapter = FakeAdapter(env.config, fail=5); worker = RequestWorker(env.config, adapter)
    for _ in range(env.config.attempts): worker.run_once(); due(env, job_id)
    job = env.client.get('/api/v1/song-requests/' + job_id).json()
    assert job['state'] == 'failed' and job['attempts'] == env.config.attempts
    assert 'Mock source unavailable' in job['error']
    assert not worker.run_once()
    with env.factory() as db: assert db.query(Song).count() == 0
    assert env.client.post('/api/v1/song-requests/' + job_id + '/retry').json()['state'] == 'queued'


def test_indexing_failure_retains_download_for_retry(environment):
    env = environment; job_id = enqueue(env); adapter = FakeAdapter(env.config)
    calls = []
    def fails_once(*args):
        calls.append(1)
        if len(calls) == 1: raise RuntimeError('Injected indexing failure')
        return index_single_file(*args)
    worker = RequestWorker(env.config, adapter, fails_once)
    worker.run_once()
    with env.factory() as db:
        job = db.get(SongRequest, job_id)
        assert job.state == 'queued' and job.downloaded_path
        assert db.query(Song).count() == 0
    due(env, job_id); worker.run_once()
    assert adapter.downloads == 1
    assert env.client.get('/api/v1/song-requests/' + job_id).json()['state'] == 'ready'


@pytest.mark.parametrize('phase', ['resolving','downloading','indexing'])
def test_restart_resumes_completed_file_without_download(environment, phase):
    env = environment; job_id = enqueue(env); adapter = FakeAdapter(env.config)
    path = adapter.download(track())
    checkpoint(job_id, state=phase, attempts=1, resolved_json=json.dumps(track()), downloaded_path=str(path))
    recover_interrupted(); RequestWorker(env.config, adapter).run_once()
    assert adapter.downloads == 1 and adapter.resolutions == 0
    assert env.client.get('/api/v1/song-requests/' + job_id).json()['state'] == 'ready'


def test_partial_file_is_never_inserted_into_library(environment):
    env = environment; job_id = enqueue(env); adapter = FakeAdapter(env.config)
    path = env.config.music_dir / '.verse-requests' / 'broken.wav'
    path.parent.mkdir(parents=True); path.write_bytes(b'incomplete')
    adapter.download = lambda _: path
    RequestWorker(env.config, adapter).run_once()
    with env.factory() as db:
        assert db.query(Song).count() == 0
        assert db.get(SongRequest, job_id).state == 'queued'


def test_musicbrainz_selection_does_not_pass_mbid_to_spotdl(environment, monkeypatch):
    selected = {**track(), 'key':identity('musicbrainz', MBID, RELEASE), 'provider':'musicbrainz','recording_id':MBID,'release_id':RELEASE}
    monkeypatch.setattr(Catalogue, 'lookup', lambda *_: selected)
    adapter = SpotDLAdapter(environment.config)
    seen = []
    def candidates(**kwargs): seen.append(kwargs); return [track()]
    monkeypatch.setattr(adapter, 'candidates', candidates)
    assert adapter.resolve(selected)['recording_id'] == SPOTIFY_ID
    assert seen == [{'isrc':'USABC2500001'}]
    monkeypatch.setattr(adapter, 'candidates', lambda **_: [track(), track('C'*22)])
    with pytest.raises(ChooseRecording): adapter.resolve(selected)
    assert not same_recording(selected, {**track(), 'title':'Selected Song (Live)'})
    assert not same_recording(selected, {**track(), 'album':'Selected Album Remastered'})


def test_no_title_only_matching_when_mb_has_no_mapping(environment, monkeypatch):
    selected = {**track(), 'provider':'musicbrainz','recording_id':MBID,'release_id':RELEASE,'isrcs':[]}
    monkeypatch.setattr(Catalogue, 'lookup', lambda *_: selected)
    adapter=SpotDLAdapter(environment.config)
    monkeypatch.setattr(adapter,'candidates',lambda **_:[{**track(),'artist':'A completely different artist'}])
    with pytest.raises(NoSuitableRecording):adapter.resolve(selected)


def mb_selection(**values):
    return {**track(), 'key':identity('musicbrainz',MBID,RELEASE), 'provider':'musicbrainz',
            'recording_id':MBID,'release_id':RELEASE,'isrcs':[],'spotify_urls':[],**values}


@pytest.mark.parametrize('with_isrc',[True,False])
def test_identifiers_discovered_only_in_full_recording_lookup(environment,monkeypatch,with_isrc):
    selected=mb_selection()
    calls=[]
    item={'id':MBID,'title':selected['title'],'length':1000,'artist-credit':[{'name':selected['artist']}],
          'releases':[{'id':RELEASE,'title':selected['album']}],'isrcs':['USABC2500001'] if with_isrc else [],
          'relations':[] if with_isrc else [{'target-type':'url','url':{'resource':'https://open.spotify.com/track/'+SPOTIFY_ID}}]}
    def get(url,**kwargs):
        calls.append((url,kwargs['params']));return response(item)
    monkeypatch.setattr(catalogue.requests,'get',get)
    adapter=SpotDLAdapter(environment.config);queries=[]
    def candidates(**kwargs):queries.append(kwargs);return [track()]
    monkeypatch.setattr(adapter,'candidates',candidates)
    result=adapter.resolve(selected)
    assert calls[0][0].endswith('/recording/'+MBID)
    assert calls[0][1]['inc']=='artist-credits+releases+isrcs+url-rels'
    assert queries==[{'isrc':'USABC2500001'}] if with_isrc else queries==[{'track_id':SPOTIFY_ID}]
    assert result['resolution']['verified_identity']
    assert result['resolution']['method']==('isrc' if with_isrc else 'spotify_url')
    assert selected['isrcs']==[]  # Do not invent identifiers on the selected result.


def test_recording_only_lookup_preserves_identity_when_releases_appear(environment,monkeypatch):
    selected=mb_selection(key=identity('musicbrainz',MBID),release_id='')
    item={'id':MBID,'title':selected['title'],'artist-credit':[{'name':selected['artist']}],
          'releases':[{'id':RELEASE,'title':'An album'}]}
    monkeypatch.setattr(Catalogue,'_get',lambda *a,**k:item)
    assert Catalogue(environment.config).lookup(selected)['key']==selected['key']


def test_metadata_fallback_ranks_multiple_attributes_and_records_honest_method(environment,monkeypatch):
    selected=mb_selection()
    monkeypatch.setattr(Catalogue,'lookup',lambda *_:selected)
    adapter=SpotDLAdapter(environment.config);seen=[]
    def candidates(**kwargs):
        seen.append(kwargs)
        return [{**track('C'*22),'artist':'Another artist'},track()]
    monkeypatch.setattr(adapter,'candidates',candidates)
    resolved=adapter.resolve(selected)
    assert seen==[{'metadata':selected}]
    assert resolved['recording_id']==SPOTIFY_ID
    assert resolved['resolution']['method']=='metadata'
    assert resolved['resolution']['score']==100
    assert not resolved['resolution']['verified_identity']
    assert resolved['resolution']['evidence']['duration_delta_seconds']==0


def test_multiple_isrcs_are_tried_before_metadata_fallback(environment,monkeypatch):
    selected=mb_selection(isrcs=['USABC2500001','USABC2500002'])
    monkeypatch.setattr(Catalogue,'lookup',lambda *_:selected)
    adapter=SpotDLAdapter(environment.config);calls=[]
    def candidates(**kwargs):calls.append(kwargs);return [{**track(),'isrcs':['USABC2500002']}]
    monkeypatch.setattr(adapter,'candidates',candidates)
    resolved=adapter.resolve(selected)
    assert calls==[{'isrcs':selected['isrcs']}]
    assert resolved['resolution']['method']=='isrc' and resolved['resolution']['verified_identity']


def test_isrc_query_without_returned_identifier_requires_strong_metadata(environment,monkeypatch):
    selected=mb_selection(album='',isrcs=['USABC2500001'])
    monkeypatch.setattr(Catalogue,'lookup',lambda *_:selected)
    adapter=SpotDLAdapter(environment.config)
    monkeypatch.setattr(adapter,'candidates',lambda **kwargs:[{**track(),'isrcs':[]}])
    with pytest.raises(ChooseRecording) as ambiguous:adapter.resolve(selected)
    assert ambiguous.value.options['method']=='isrc_metadata'
    selected['album']='Selected Album'
    resolved=adapter.resolve(selected)
    assert resolved['resolution']['method']=='isrc_metadata' and not resolved['resolution']['verified_identity']


def test_disambiguation_can_qualify_a_matching_version_title_without_becoming_an_original():
    selected=mb_selection(version='live',album='Stage Recording')
    candidate={**track(),'title':'Selected Song (Live)','album':'Stage Recording','isrcs':[]}
    resolved=select_metadata_candidate(selected,[candidate])
    assert resolved['recording_id']==SPOTIFY_ID and resolved['resolution']['score']==100
    with pytest.raises(NoSuitableRecording):select_metadata_candidate(selected,[{**candidate,'title':'Selected Song (Remix)'}])


def test_identifier_matching_uses_individual_artist_credits_not_join_punctuation(environment,monkeypatch):
    selected=mb_selection(isrcs=['USABC2500001'],artist='Artist One & Artist Two',
        artist_credits=[{'name':'Artist One'},{'name':'Artist Two'}])
    candidate={**track(),'artist':'Artist Two, Artist One',
        'artist_credits':[{'name':'Artist Two'},{'name':'Artist One'}]}
    monkeypatch.setattr(Catalogue,'lookup',lambda *_:selected)
    adapter=SpotDLAdapter(environment.config)
    monkeypatch.setattr(adapter,'candidates',lambda **kwargs:[candidate])
    assert adapter.resolve(selected)['resolution']['verified_identity']


def test_empty_identifier_search_can_reach_metadata_fallback_without_rate_livelock(environment,monkeypatch):
    from app.discovery import acquisition
    selected=mb_selection(isrcs=['USABC2500001'])
    monkeypatch.setattr(Catalogue,'lookup',lambda *_:selected)
    adapter=SpotDLAdapter(environment.config);calls=[];waits=[]
    def run(args,cwd,timeout,payload=None):
        calls.append(payload);return json.dumps([track()] if payload.get('operation')=='metadata-search' else [])
    def sleep(seconds):
        waits.append(seconds)
        with environment.factory() as db:db.query(CatalogueBudget).delete();db.commit()
    monkeypatch.setattr(adapter,'run',run)
    monkeypatch.setattr(acquisition.time,'sleep',sleep)
    resolved=adapter.resolve(selected)
    assert resolved['resolution']['method']=='metadata' and len(calls)==2
    assert calls[0]['isrc']=='USABC2500001' and calls[1]['operation']=='metadata-search'
    assert len(waits)==1 and 0<waits[0]<=2


def test_automatic_metadata_resolution_deduplicates_canonical_song_without_asserting_mb_identity(environment):
    env=environment;adapter=FakeAdapter(env.config)
    adapter.resolve=lambda selected:select_metadata_candidate(selected,[track()])
    worker=RequestWorker(env.config,adapter);ids=[]
    for recording_id in (MBID,'33333333-3333-3333-3333-333333333333'):
        selected=mb_selection(key=identity('musicbrainz',recording_id,RELEASE),recording_id=recording_id)
        cache_put('selection:'+selected['key'],selected,3600)
        job=env.client.post('/api/v1/song-requests',json={'provider':'musicbrainz','recording_id':recording_id,'release_id':RELEASE}).json()
        assert worker.run_once()
        ready=env.client.get('/api/v1/song-requests/'+job['id']).json()
        assert ready['state']=='ready' and ready['resolution']['method']=='metadata'
        assert not ready['resolution']['verified_identity']
        ids.append(ready['song']['id'])
        assert env.client.post('/api/v1/song-requests',json={'provider':'musicbrainz','recording_id':recording_id,'release_id':RELEASE}).json()['id']==job['id']
        with env.factory() as db:assert db.get(SongSource,selected['key']) is None
    assert ids[0]==ids[1] and adapter.downloads==1
    with env.factory() as db:assert db.query(Song).count()==1


@pytest.mark.parametrize('changes',[{'title':'Selected Song (Live)'},{'artist':'A cover artist'},
    {'title':'Selected Song (Remix)'},{'album':'Selected Album Remastered'},{'duration':90}])
def test_metadata_fallback_never_accepts_conflicting_versions_or_covers(changes):
    with pytest.raises(NoSuitableRecording):select_metadata_candidate(mb_selection(),[{**track(),**changes}])


def test_ambiguous_versions_persist_choose_and_resume_same_job(environment,monkeypatch):
    env=environment;selected=mb_selection(album='')
    cache_put('selection:'+selected['key'],selected,3600)
    created=env.client.post('/api/v1/song-requests',json={'provider':'musicbrainz','recording_id':MBID,'release_id':RELEASE}).json()
    job_id=created['id'];adapter=FakeAdapter(env.config)
    def ambiguous(_):return select_metadata_candidate(selected,[track(),{**track('C'*22),'album':'Other Release'}])
    adapter.resolve=ambiguous
    worker=RequestWorker(env.config,adapter);assert worker.run_once()
    job=env.client.get('/api/v1/song-requests/'+job_id).json()
    assert job['state']=='awaiting_choice' and len(job['candidates'])==2 and job['error'] is None
    assert adapter.downloads==0
    recover_interrupted();assert not worker.run_once()
    assert env.client.post('/api/v1/song-requests',json={'provider':'musicbrainz','recording_id':MBID,'release_id':RELEASE}).json()['id']==job_id
    url='/api/v1/song-requests/'+job_id+'/choose-version'
    assert env.client.post(url,json={'candidate_key':'spotify:'+'Z'*22}).status_code==422
    choice=env.client.post(url,json={'candidate_key':track()['key']})
    assert choice.status_code==202 and choice.json()['id']==job_id and choice.json()['state']=='queued'
    assert choice.json()['resolution']['method']=='user_selected_metadata'
    assert env.client.post(url,json={'candidate_key':track()['key']}).status_code==202
    assert env.client.post(url,json={'candidate_key':'spotify:'+'C'*22}).status_code==409
    adapter.resolve=lambda _:pytest.fail('Choice must not be resolved again')
    assert worker.run_once()
    done=env.client.get('/api/v1/song-requests/'+job_id).json()
    assert done['state']=='ready' and done['resolution']['user_selected']
    with env.factory() as db:
        assert db.query(SongRequest).count()==1 and db.query(Song).count()==1
        assert db.get(SongSource,selected['key']) is None  # Similarity is not exact MB identity.
        assert db.get(SongSource,track()['key']) is not None


def test_no_suitable_match_is_terminal_and_retry_clears_previous_error(environment):
    env=environment;job_id=enqueue(env);adapter=FakeAdapter(env.config)
    def no_match(_):
        with env.factory() as db:
            job=db.get(SongRequest,job_id)
            assert job.state=='resolving' and job.error is None
        return select_metadata_candidate(mb_selection(),[])
    adapter.resolve=no_match;worker=RequestWorker(env.config,adapter);assert worker.run_once()
    failed=env.client.get('/api/v1/song-requests/'+job_id).json()
    assert failed['state']=='failed' and failed['attempts']==1 and 'No suitable recording' in failed['error']
    assert not worker.run_once() and adapter.downloads==0
    retry=env.client.post('/api/v1/song-requests/'+job_id+'/retry').json()
    assert retry['state']=='queued' and retry['error'] is None
    assert worker.run_once()


def test_concurrent_version_submissions_share_the_same_choice(environment):
    env=environment;job_id=enqueue(env)
    options=ChooseRecording(mb_selection(),[track(),track('C'*22)],'metadata').options
    checkpoint(job_id,state='awaiting_choice',resolved_json=json.dumps(options))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',cookies={SESSION_COOKIE:env.client.cookies.get(SESSION_COOKIE)}) as client:
            responses=await asyncio.gather(*(client.post('/api/v1/song-requests/'+job_id+'/choose-version',json={'candidate_key':track()['key']}) for _ in range(5)))
            assert all(r.status_code==202 and r.json()['id']==job_id for r in responses)
    asyncio.run(run())
    with env.factory() as db:assert db.query(SongRequest).count()==1


def test_version_rediscovery_discards_options_not_completed_audio(environment):
    env=environment;job_id=enqueue(env)
    options=ChooseRecording(mb_selection(),[track(),track('C'*22)],'metadata').options
    checkpoint(job_id,state='awaiting_choice',resolved_json=json.dumps(options))
    retry=env.client.post('/api/v1/song-requests/'+job_id+'/retry').json()
    assert retry['state']=='queued' and retry['candidates']==[]
    with env.factory() as db:assert db.get(SongRequest,job_id).resolved_json is None
    env.client.cookies.clear()
    assert env.client.post('/api/v1/song-requests/'+job_id+'/choose-version',json={'candidate_key':track()['key']}).status_code==401


def test_provider_failure_does_not_break_local_search(environment, monkeypatch):
    def unavailable(*_): raise DiscoveryError('Catalogue temporarily unavailable')
    monkeypatch.setattr(Catalogue, 'search', unavailable)
    assert environment.client.get('/api/v1/search/external?q=Song').status_code == 503
    assert environment.client.get('/api/v1/search?q=Song').status_code == 200


def test_catalogue_cache_rate_limit_and_retry_after(environment, monkeypatch):
    calls=[]
    item={'id':MBID,'title':'Song','length':None,'artist-credit':[{'name':'Artist'}],'releases':[{'id':RELEASE,'title':'Album'}]}
    def get(*args, **kwargs): calls.append(kwargs); return response({'recordings':[item]})
    monkeypatch.setattr(catalogue.requests,'get',get)
    provider=Catalogue(environment.config)
    first=provider.search('Song'); second=provider.search('Song')
    assert first==second and len(calls)==1 and first[0]['duration']==0
    assert 'tests@example.invalid' in calls[0]['headers']['User-Agent']
    with pytest.raises(DiscoveryError, match='rate limited'): provider.search('Different')
    with environment.factory() as db: db.query(CatalogueBudget).delete(); db.commit()
    monkeypatch.setattr(catalogue.requests,'get',lambda *a,**k:response({},429,{'Retry-After':'30'}))
    with pytest.raises(DiscoveryError) as limited: provider.search('Other')
    assert limited.value.retry_after==30


def test_spotify_client_credentials_search_uses_current_limit(environment, monkeypatch):
    monkeypatch.setenv('VERSE_CATALOGUE','auto')
    monkeypatch.setenv('VERSE_SPOTIFY_CLIENT_ID','test-id');monkeypatch.setenv('VERSE_SPOTIFY_CLIENT_SECRET','test-secret')
    calls=[]
    monkeypatch.setattr(catalogue.requests,'post',lambda *a,**k:response({'access_token':'test-token','expires_in':3600}))
    def get(*a,**k):
        calls.append(k)
        return response({'tracks':{'items':[{'id':SPOTIFY_ID,'name':'Song','duration_ms':1000,'artists':[{'name':'Artist'}],
            'album':{'id':'B'*22,'name':'Album','images':[]},'external_ids':{'isrc':'USABC2500001'}}]}})
    monkeypatch.setattr(catalogue.requests,'get',get)
    result=environment.client.get('/api/v1/search/external?q=Spotify')
    assert result.status_code==200 and result.json()['provider']=='spotify'
    assert calls[0]['params']['limit']==10
    assert 'test-secret' not in result.text and 'test-token' not in result.text


def test_distinct_versions_get_distinct_request_jobs(environment):
    env=environment
    alternate={**track('C'*22),'title':'Selected Song - Live'}
    cache_put('selection:'+alternate['key'],alternate,3600)
    original=enqueue(env)
    other=env.client.post('/api/v1/song-requests',json={'provider':'spotify','recording_id':'C'*22})
    assert other.status_code==202 and other.json()['id']!=original


def test_request_requires_sign_in_and_config(environment, monkeypatch):
    client=environment.client
    client.cookies.clear()
    assert client.post('/api/v1/song-requests',json={'provider':'spotify','recording_id':SPOTIFY_ID}).status_code==401
    monkeypatch.delenv('VERSE_MUSIC_DIR')
    with pytest.raises(DiscoveryError,match='VERSE_MUSIC_DIR'): request_song(track()['key'])


def test_path_boundaries_and_subprocess_argument_array(environment, monkeypatch):
    adapter=SpotDLAdapter(environment.config)
    monkeypatch.setattr(adapter,'audio_source',lambda selected:audio_source())
    with pytest.raises(DiscoveryError,match='outside'): adapter.bounded_path(environment.config.music_dir.parent/'outside.mp3')
    calls=[]
    def fake_run(arguments,cwd,timeout,payload=None):
        calls.append(arguments)
        template=arguments[arguments.index('--output')+1]
        (Path(cwd)/template.replace('{output-ext}','mp3')).write_bytes(b'mock complete download')
    monkeypatch.setattr(adapter,'run',fake_run)
    result=adapter.download(track())
    assert result.is_relative_to(environment.config.music_dir)
    assert calls[0][calls[0].index('download')+1]==audio_source()['url']+'|https://open.spotify.com/track/'+SPOTIFY_ID
    assert '--threads' in calls[0] and '--save-file' in calls[0]
    assert calls[0][calls[0].index('--output')+1]=='track.{output-ext}'


def test_real_spotdl_formatter_keeps_output_inside_hidden_staging(environment,monkeypatch):
    pytest.importorskip('spotdl')
    from spotdl.utils.formatter import create_file_name
    from spotdl.types.song import Song as SpotSong
    song=SpotSong(name='Selected Song',artists=['Selected Artist'],artist='Selected Artist',genres=[],
        disc_number=1,disc_count=1,album_name='Selected Album',album_artist='Selected Artist',duration=1,
        year=2026,date='2026-01-01',track_number=1,tracks_count=1,song_id=SPOTIFY_ID,explicit=False,
        publisher='',url='https://open.spotify.com/track/'+SPOTIFY_ID,isrc=None,cover_url=None,copyright_text=None)
    adapter=SpotDLAdapter(environment.config)
    monkeypatch.setattr(adapter,'audio_source',lambda selected:audio_source())
    def actual_formatter(arguments,cwd,timeout,payload=None):
        template=arguments[arguments.index('--output')+1]
        formatted=create_file_name(song,template,'mp3')
        assert formatted==Path('track.mp3') and not formatted.is_absolute()
        target=Path(cwd)/formatted
        assert target==environment.config.music_dir/'.verse-requests'/SPOTIFY_ID/'track.mp3'
        target.write_bytes(b'complete acquisition fixture')
    monkeypatch.setattr(adapter,'run',actual_formatter)
    assert adapter.download(track()).is_file()


def test_audio_source_rejects_live_video_and_uses_exact_album():
    from app.discovery.audio_source import source_candidates
    selected={**track(),'duration':355}
    song={'resultType':'song','videoId':'ABCDEFGHIJK','title':'Selected Song','artists':[{'name':'Selected Artist'}],
          'album':{'name':'Another Release'},'duration':'5:55'}
    video={**song,'resultType':'video','title':'Selected Song (Glastonbury 2022)',
           'album':{'name':'Selected Album'},'duration':'5:49'}
    album={'title':'Selected Album','artists':[{'name':'Selected Artist'}],'browseId':'MPRE_Exact'}
    client=SimpleNamespace(search=lambda query,filter,limit:[song,video] if filter=='songs' else [album],
        get_album=lambda browse_id:{'title':'Selected Album','tracks':[{**song,'album':'Selected Album'}]})
    assert source_candidates(selected,client)==[{'title':'Selected Song','artist':'Selected Artist',
        'album':'Selected Album','duration':355,'url':audio_source()['url']}]
    client.get_album=lambda browse_id:{'title':'Selected Album','tracks':[video]}
    assert source_candidates(selected,client)==[]


def test_audio_source_requires_unique_version_verified_match(environment,monkeypatch):
    adapter=SpotDLAdapter(environment.config)
    monkeypatch.setattr(adapter,'run',lambda *a,**k:json.dumps([audio_source(),
        {**audio_source(),'url':'https://music.youtube.com/watch?v=LMNOPQRSTUV'}]))
    with pytest.raises(DiscoveryError,match='No unique'):adapter.audio_source(track())


def test_unverified_staging_source_is_quarantined_not_indexed(environment,monkeypatch):
    adapter=SpotDLAdapter(environment.config)
    monkeypatch.setattr(adapter,'audio_source',lambda selected:audio_source())
    candidate=environment.config.music_dir/'.verse-requests'/SPOTIFY_ID/'track.mp3'
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b'unverified audio from an earlier attempt')
    monkeypatch.setattr(adapter,'run',lambda *a,**k:None)
    with pytest.raises(DiscoveryError,match='without producing audio'):adapter.download(track())
    assert not candidate.exists()
    assert len(list(candidate.parent.glob('incomplete-*.mp3')))==1
    with environment.factory() as db:assert db.query(Song).count()==0


def test_verified_staging_is_reused_without_network_or_download(environment,monkeypatch):
    adapter=SpotDLAdapter(environment.config)
    monkeypatch.setattr(adapter,'audio_source',lambda selected:audio_source())
    candidate=make_audio(environment.config.music_dir/'.verse-requests'/SPOTIFY_ID/'track.mp3')
    tagged=WAVE(candidate);tagged.tags.add(COMM(encoding=3,lang='eng',desc='',text=[audio_source()['url']]));tagged.save()
    (candidate.parent/'audio-source.json').write_text(json.dumps(audio_source()))
    monkeypatch.setattr(adapter,'audio_source',lambda selected:pytest.fail('Should reuse verified source snapshot'))
    monkeypatch.setattr(adapter,'run',lambda *a,**k:pytest.fail('Should not download again'))
    resolved=track()
    assert adapter.download(resolved)==candidate
    assert resolved['audio_source']==audio_source()


def test_audio_verification_rejects_retagged_different_source(environment):
    path=make_audio(environment.config.music_dir/'retagged.wav')
    tagged=WAVE(path);tagged.tags.add(COMM(encoding=3,lang='eng',desc='',text=['https://www.youtube.com/watch?v=LMNOPQRSTUV']));tagged.save()
    with pytest.raises(ValueError,match='audio source'):verify_audio_file(path,{**track(),'audio_source':audio_source()})


def test_index_transaction_rolls_back_song_and_ready_state_together(environment):
    env=environment;job_id=enqueue(env);adapter=FakeAdapter(env.config)
    def fail_after_insert(*args):
        index_single_file(*args)
        raise RuntimeError('Fail after song/source inserts')
    RequestWorker(env.config,adapter,fail_after_insert).run_once()
    with env.factory() as db:
        assert db.query(Song).count()==0 and db.query(SongSource).count()==0
        assert db.get(SongRequest,job_id).state=='queued'
    due(env,job_id);RequestWorker(env.config,adapter).run_once()
    assert adapter.downloads==1
    assert env.client.get('/api/v1/song-requests/'+job_id).json()['state']=='ready'


def test_bridge_supports_no_config_and_spotipyfree_query_signature(environment,monkeypatch,capsys,tmp_path):
    from app.discovery.spotdl_bridge import main
    calls=[]
    class Client:
        def search(self,query,type='track',limit=10):
            calls.append(query)
            return {'tracks':{'items':[{'id':SPOTIFY_ID,'name':'Song','duration_ms':1000,'artists':[{'name':'Artist'}],'album':{}}]}}
    fake=SimpleNamespace(init=lambda **kw:None)
    fake.__call__=lambda:Client()
    class Facade:
        init=staticmethod(lambda **kw:None)
        def __new__(cls):return Client()
    monkeypatch.setitem(sys.modules,'spotdl.utils.config',SimpleNamespace(DEFAULT_CONFIG={'client_id':'default','client_secret':'default'},
        get_config=lambda:pytest.fail('No config exists'),get_config_file=lambda:tmp_path/'absent.json'))
    monkeypatch.setitem(sys.modules,'spotdl.utils.spotify',SimpleNamespace(SpotifyClient=Facade))
    monkeypatch.setattr(sys,'stdin',__import__('io').StringIO(json.dumps({'isrc':'USABC2500001'})))
    main()
    assert calls==['isrc:USABC2500001']
    assert json.loads(capsys.readouterr().out)[0]['recording_id']==SPOTIFY_ID


def test_worker_lock_is_exclusive_and_released(environment,monkeypatch):
    from app.discovery import worker
    lockpath=Path(environment.engine.url.database+'.requests.lock')
    class StubWorker:
        def __init__(self,*args):pass
        def run_once(self):
            with open(lockpath,'a') as handle:
                with pytest.raises(BlockingIOError):fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return False
    monkeypatch.setattr(worker,'RequestWorker',StubWorker)
    worker.run_worker(once=True)
    with open(lockpath,'a') as handle:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)


def test_subprocess_timeout_kills_group_and_inherits_worker_lock(environment,monkeypatch):
    from app.discovery import acquisition
    calls=[]
    class Process:
        pid=12345;returncode=0
        count=0
        def communicate(self,*args,**kwargs):
            self.count+=1
            if self.count==1:raise subprocess.TimeoutExpired('test',1)
            return ('','')
    def popen(*args,**kwargs):calls.append(kwargs);return Process()
    monkeypatch.setattr(acquisition.subprocess,'Popen',popen)
    monkeypatch.setattr(acquisition.os,'killpg',lambda *args:calls.append(args))
    adapter=SpotDLAdapter(environment.config,lock_fd=7)
    with pytest.raises(subprocess.TimeoutExpired):adapter.run(['test'],str(environment.config.music_dir),1)
    assert calls[0]['start_new_session'] and calls[0]['pass_fds']==(7,)
    assert calls[1][0]==12345


def test_invalid_and_expired_selection_ids(environment):
    client=environment.client
    assert client.post('/api/v1/song-requests',json={'provider':'spotify','recording_id':'../../escape'}).status_code==422
    assert client.post('/api/v1/song-requests',json={'provider':'spotify','recording_id':'Z'*22}).status_code==409


def test_migration_preserves_existing_playlist_data(tmp_path):
    database=tmp_path/'migration.db'
    env={**os.environ,'DATABASE_URL':'sqlite:///'+str(database)}
    for revision in ['5f2b3c4d6e7f','head']:
        result=subprocess.run([sys.executable,'-m','alembic','upgrade',revision],env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        if revision=='5f2b3c4d6e7f':
            import sqlite3
            with sqlite3.connect(database) as db:
                db.execute("INSERT INTO songs(id,path,hash,title) VALUES(1,'/old.mp3','old-hash','Old song')")
                db.execute("INSERT INTO playlists(id,user_id,name,generated_by,created_at,updated_at) VALUES(1,1,'Keep me','User',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
                db.execute('INSERT INTO playlist_songs(playlist_id,song_id,position) VALUES(1,1,7)')
    import sqlite3
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT name FROM playlists WHERE id=1').fetchone()==('Keep me',)
        assert db.execute('SELECT song_id,position FROM playlist_songs').fetchall()==[(1,7)]
        assert db.execute('SELECT COUNT(*) FROM song_requests').fetchone()==(0,)


def test_discovery_browser_flow():
    pytest.importorskip('PySide6.QtWebEngineWidgets')
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('browser_manual_playlist_probe.py')),'--discovery'],
        capture_output=True,text=True,timeout=55)
    assert result.returncode==0,result.stdout+result.stderr


def test_source_backfill_satisfies_queued_job_without_provider_or_download(environment):
    from app.discovery.worker import backfill_identities
    env=environment;job_id=enqueue(env)
    path=make_audio(env.config.music_dir/'legacy.wav')
    with env.factory() as db:
        song_id=index_single_file(path,track(),[],db);db.commit()
    assert backfill_identities()==1
    adapter=FakeAdapter(env.config);RequestWorker(env.config,adapter).run_once()
    assert adapter.resolutions==0 and adapter.downloads==0
    assert env.client.get('/api/v1/song-requests/'+job_id).json()['song']['id']==song_id


def test_missing_audio_tool_retains_completed_file_for_index_retry(environment,monkeypatch):
    from app.indexing import single_file
    env=environment;job_id=enqueue(env);adapter=FakeAdapter(env.config)
    with monkeypatch.context() as patch:
        def absent(*_):raise FileNotFoundError('ffprobe')
        patch.setattr(single_file,'extract_technical_metadata',absent)
        RequestWorker(env.config,adapter).run_once()
    due(env,job_id);RequestWorker(env.config,adapter).run_once()
    assert adapter.downloads==1
    assert env.client.get('/api/v1/song-requests/'+job_id).json()['state']=='ready'


@pytest.mark.parametrize('command,argument,module,function',[
    ('request-worker','--once','app.discovery.worker','run_worker'),
    ('request-enrich','42','app.indexing.enrich_file','enrich_single_song')])
def test_new_cli_commands_dispatch_without_starting_services(monkeypatch,command,argument,module,function):
    from unittest.mock import patch
    from app.main import main
    monkeypatch.setattr(sys,'argv',['app.main',command,argument])
    with patch(module+'.'+function) as runner:
        main()
        runner.assert_called_once()


def test_optional_enrichment_is_single_file_and_separate(environment,monkeypatch,tmp_path):
    from unittest.mock import MagicMock
    from app.features.extractor import AudioFeaturesInfo
    from app.indexing.enrich_file import enrich_single_song
    from app.database.models import AudioFeatures, Embeddings
    path=make_audio(environment.config.music_dir/'ready.wav')
    with environment.factory() as db:
        song_id=index_single_file(path,track(),[],db);db.commit()
    seen=[]
    monkeypatch.setattr('app.features.extractor.extract_features',lambda p:(seen.append(p),AudioFeaturesInfo(bpm=100))[1])
    monkeypatch.setattr('app.embeddings.generator.generate_embedding',lambda *a:[0.0]*512)
    monkeypatch.setattr('app.search.index.FAISSIndex',MagicMock())
    monkeypatch.setattr('app.recommendations.content_pipeline.rebuild_content_pipeline',MagicMock())
    enrich_single_song(song_id,tmp_path/'numeric-index.bin')
    assert seen==[path]
    with environment.factory() as db:
        assert db.get(AudioFeatures,song_id).bpm==100
        assert db.get(Embeddings,song_id).vector


def test_removed_library_entry_does_not_break_status_and_can_reindex(environment):
    env=environment;job_id=enqueue(env);adapter=FakeAdapter(env.config);worker=RequestWorker(env.config,adapter)
    worker.run_once()
    ready=env.client.get('/api/v1/song-requests/'+job_id).json()
    with env.factory() as db:
        db.delete(db.get(Song,ready['song']['id']));db.commit()
    status=env.client.get('/api/v1/song-requests')
    assert status.status_code==200 and status.json()[0]['state']=='failed'
    env.client.post('/api/v1/song-requests/'+job_id+'/retry')
    worker.run_once()
    assert env.client.get('/api/v1/song-requests/'+job_id).json()['state']=='ready'
    assert adapter.downloads==1
