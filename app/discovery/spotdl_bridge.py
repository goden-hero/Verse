"""Small subprocess protocol around the installed spotDL catalogue client.

Spotify identity resolution uses ISRC queries or exact URLs. Metadata fallback
uses bounded search through the installed client (still Spotify-dependent, but
not dependent on paid official discovery credentials). Audio-source lookup
independently verifies song/album metadata and never chooses a fuzzy video hit.
Keeping this out of FastAPI bounds the third-party clients' runtime.
"""
import json
import sys
from contextlib import redirect_stdout
from .config import DiscoveryConfig
from .catalogue import spotify_track


def main():
    output = sys.stdout
    payload = json.loads(sys.stdin.read())
    # Third-party diagnostic output must not corrupt the JSON subprocess protocol.
    with redirect_stdout(sys.stderr):
        if payload.get('operation') == 'audio-source':
            from ytmusicapi import YTMusic
            from .audio_source import source_candidates
            result = source_candidates(payload['selected'], YTMusic())
            json.dump(result, output)
            return
        from spotdl.utils.config import DEFAULT_CONFIG, get_config, get_config_file
        from spotdl.utils.spotify import SpotifyClient
        config = DiscoveryConfig.load()
        defaults = {**DEFAULT_CONFIG, **(get_config() if get_config_file().is_file() else {})}
        SpotifyClient.init(client_id=config.client_id or defaults["client_id"],
            client_secret=config.client_secret or defaults["client_secret"], headless=True,
            no_cache=True, max_retries=0, use_official_api=bool(config.client_id and config.client_secret))
        client = SpotifyClient()
        if payload.get('operation') == 'metadata-search':
            selected = payload['selected']
            # Positional query is supported by both Spotipy and SpotipyFree.
            # Retrieve candidates, never the CLI's first fuzzy download match.
            queries = [selected['title'] + ' ' + selected['artist']]
            if selected.get('version'):
                queries[0] += ' ' + selected['version']
            if selected.get('album'):
                queries.append(queries[0] + ' ' + selected['album'])
            items = []
            for query in dict.fromkeys(queries):
                items.extend(client.search(query[:400], type='track', limit=10)['tracks']['items'][:10])
        elif payload.get('track_ids'):
            items = [client.track(track_id) for track_id in payload['track_ids'][:3]]
        elif payload.get("track_id"):
            items = [client.track(payload["track_id"])]
        else:
            # Positional query supports both Spotipy and spotDL's SpotipyFree.
            items = []
            for isrc in (payload.get('isrcs') or [payload['isrc']])[:3]:
                items.extend(client.search("isrc:" + isrc, type="track", limit=10)["tracks"]["items"][:10])
        result = []
        for item in items[:30]:
            try: result.append(spotify_track(item))
            except (KeyError, TypeError, ValueError): continue
    json.dump(result, output)


if __name__ == "__main__":
    main()
