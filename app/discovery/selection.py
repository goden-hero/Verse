"""Local identity checks happen here, after selection, never during typing."""
from app.database.connection import get_session
from app.services.library import LibraryService
from .catalogue import DiscoveryError, cache_get, cache_put
from .jobs import find_recording_job, job_dict, source_song
from .config import DiscoveryConfig
from .acquisition import SpotDLAdapter
from .resolution import ChooseRecording, NoSuitableRecording


def selected_recording(key):
    selected = cache_get('selection:' + key)
    with get_session() as db:
        job = find_recording_job(db, key)
        if not selected and job:
            import json
            selected = json.loads(job.metadata_json)
        if not selected: raise DiscoveryError('This result expired. Search again.', status_code=409)
        saved = job_dict(job, db) if job else None
        song_id = source_song(db, key)
        song = saved.get('song') if saved else None
        if song_id: song = LibraryService.get_song_by_id(song_id, db)
        if saved or song:
            return dict(track=selected, song=song, job=saved, resolution=saved.get('resolution') if saved else None,
                can_request=DiscoveryConfig.load().music_dir is not None)
    prepared = cache_get('resolved-selection:' + key)
    if not prepared:
        try: prepared = SpotDLAdapter().resolve(selected)
        except ChooseRecording as choice: prepared = choice.options
        except NoSuitableRecording as error:
            return dict(track=selected, song=None, job=None, resolution=None,
                message=str(error), can_request=DiscoveryConfig.load().music_dir is not None)
        cache_put('resolved-selection:' + key, prepared, 3600)
    song = None
    if prepared.get('key'):
        with get_session() as db:
            song_id = source_song(db, prepared['key'])
            if song_id: song = LibraryService.get_song_by_id(song_id, db)
    return dict(track=selected, song=song, job=None, resolution=prepared.get('resolution'),
        can_request=DiscoveryConfig.load().music_dir is not None)
