"""Conservative audio-source lookup; never accept an unverified video fallback."""
import re

from .acquisition import normalized, same_recording


def source_candidates(selected, client):
    """Inspect song/album metadata, not spotDL's fuzzy video ranking.

    YouTube Music's song listing alone can prefer a single over the selected
    album. A bounded exact-album lookup handles that without collapsing releases.
    The caller still requires one unique matching source before downloading.
    """
    def candidate(row, album=None):
        video_id = row.get('videoId', '')
        artists = row.get('artists') or []
        release = row.get('album') or album or ''
        if isinstance(release, dict): release = release.get('name', '')
        duration = row.get('duration_seconds')
        if duration is None:
            parts = str(row.get('duration', '')).split(':')
            if not parts or not all(part.isdigit() for part in parts): return None
            duration = 0
            for part in parts: duration = duration * 60 + int(part)
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id) or not artists: return None
        result = dict(title=row.get('title', ''), artist=', '.join(a['name'] for a in artists),
                      album=release, duration=duration, url='https://music.youtube.com/watch?v=' + video_id)
        return result if same_recording(selected, result) else None

    songs = client.search(selected['artist'] + ' ' + selected['title'], filter='songs', limit=20)
    matches = [match for row in songs if row.get('resultType') == 'song'
               and (match := candidate(row))]
    if matches: return matches
    if not selected.get('album'): return []
    albums = client.search(selected['artist'] + ' ' + selected['album'], filter='albums', limit=10)
    exact = [row for row in albums if normalized(row.get('title', '')) == normalized(selected['album'])
             and normalized(', '.join(a['name'] for a in row.get('artists', []))) == normalized(selected['artist'])]
    for row in exact[:3]:
        browse_id = row.get('browseId', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', browse_id): continue
        album = client.get_album(browse_id)
        if normalized(album.get('title', '')) != normalized(selected['album']): continue
        matches.extend(match for track in album.get('tracks', [])
                       if (match := candidate(track, album['title'])))
    return matches
