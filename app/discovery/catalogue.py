"""Official catalogue clients. Shared SQLite TTL cache and cross-process budgets."""
import hashlib
import json
import math
import re
import threading
import time
from email.utils import parsedate_to_datetime

import requests
from sqlalchemy.dialects.sqlite import insert
from app.database.connection import get_session
from app.database.models import CatalogueBudget, DiscoveryCache
from .config import DiscoveryConfig


class DiscoveryError(Exception):
    def __init__(self, message, retry_after=0, status_code=503):
        super().__init__(message)
        self.retry_after = retry_after
        self.status_code = status_code


def identity(provider, recording_id, release_id=""):
    if provider == "spotify" and re.fullmatch(r"[A-Za-z0-9]{22}", recording_id):
        return f"spotify:{recording_id}"
    uuid = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
    if provider == "musicbrainz" and re.fullmatch(uuid, recording_id) and (not release_id or re.fullmatch(uuid, release_id)):
        return f"musicbrainz:{recording_id}:{release_id}"
    raise DiscoveryError("Invalid catalogue recording identifier.", status_code=422)


def cache_get(key):
    with get_session() as db:
        row = db.get(DiscoveryCache, key)
        return json.loads(row.payload) if row and row.expires_at > time.time() else None


def cache_put(key, payload, ttl):
    with get_session() as db:
        now = time.time()
        db.query(DiscoveryCache).filter(DiscoveryCache.expires_at < now).delete()
        statement = insert(DiscoveryCache).values(key=key, payload=json.dumps(payload), expires_at=now + ttl)
        db.execute(statement.on_conflict_do_update(index_elements=[DiscoveryCache.key], set_={
            "payload": statement.excluded.payload, "expires_at": statement.excluded.expires_at}))


def reserve(provider, interval):
    now = time.time()
    with get_session() as db:
        statement = insert(CatalogueBudget).values(provider=provider, next_allowed_at=now + interval)
        result = db.execute(statement.on_conflict_do_update(index_elements=[CatalogueBudget.provider],
            set_={"next_allowed_at": now + interval}, where=CatalogueBudget.next_allowed_at <= now).returning(CatalogueBudget.provider)).first()
        if not result:
            delay = max(1, math.ceil(db.get(CatalogueBudget, provider).next_allowed_at - now))
            raise DiscoveryError("Catalogue is rate limited. Try again shortly.", delay)


def postpone(provider, delay):
    with get_session() as db:
        statement = insert(CatalogueBudget).values(provider=provider, next_allowed_at=time.time() + delay)
        db.execute(statement.on_conflict_do_update(index_elements=[CatalogueBudget.provider],
            set_={"next_allowed_at": statement.excluded.next_allowed_at},
            where=CatalogueBudget.next_allowed_at < statement.excluded.next_allowed_at))


def check_response(response, provider):
    if response.status_code == 429 or response.status_code == 503:
        value = response.headers.get("Retry-After", "5")
        try:
            delay = float(value)
        except ValueError:
            try: delay = parsedate_to_datetime(value).timestamp() - time.time()
            except (ValueError, TypeError): delay = 5
        delay = max(1, min(3600, math.ceil(delay)))
        postpone(provider, delay)
        raise DiscoveryError(f"{provider.title()} is temporarily rate limited or unavailable.", delay)
    if response.status_code in (401, 403):
        raise DiscoveryError("Catalogue access denied. Check Spotify credentials, app eligibility and permissions.")
    if not response.ok:
        raise DiscoveryError(f"Catalogue request failed (HTTP {response.status_code}).")
    try:
        return response.json()
    except ValueError as error:
        raise DiscoveryError("Catalogue returned invalid JSON.") from error


def spotify_track(item):
    track_id = item["id"]
    key = identity("spotify", track_id)
    album = item.get("album") or {}
    duration = item.get("duration_ms", 0) / 1000
    if not item.get("name") or not item.get("artists") or not math.isfinite(duration) or duration <= 0:
        raise DiscoveryError("Catalogue track has incomplete playback metadata.")
    images = album.get("images") or []
    return {"key": key, "provider": "spotify", "recording_id": track_id, "release_id": album.get("id", ""),
        "title": item["name"], "artist": ", ".join(a["name"] for a in item["artists"]), "album": album.get("name", ""),
        "version": "", "artist_credits": [{"name": a['name'], "id": a.get('id')} for a in item['artists']],
        "duration": duration, "artwork_url": images[-1].get("url") if images else None,
        "isrcs": [item["external_ids"]["isrc"]] if (item.get("external_ids") or {}).get("isrc") else [],
        "url": f"https://open.spotify.com/track/{track_id}"}


def musicbrainz_track(item, release_id=None):
    releases = item.get("releases") or []
    release = (next((r for r in releases if r["id"] == release_id), None) if release_id else {}) if release_id is not None else (releases[0] if releases else {})
    if release is None:
        raise DiscoveryError("Selected release is no longer linked to this recording; search again.")
    release = release or {}
    credits = item.get("artist-credit") or []
    artist = "".join((c.get("name") or c.get("artist", {}).get("name", "")) + c.get("joinphrase", "") for c in credits if isinstance(c, dict))
    rid = release.get("id", "")
    return {"key": identity("musicbrainz", item["id"], rid), "provider": "musicbrainz", "recording_id": item["id"],
        "release_id": rid, "title": item["title"], "artist": artist, "album": release.get("title", ""),
        "version": item.get("disambiguation", ""), "duration": (item.get("length") or 0) / 1000,
        "artist_credits": [{"name": c.get('name') or c.get('artist', {}).get('name', ''),
                            "id": c.get('artist', {}).get('id')} for c in credits if isinstance(c, dict)],
        "artwork_url": f"https://coverartarchive.org/release/{rid}/front-250" if rid else None,
        "isrcs": item.get("isrcs", []), "url": f'https://musicbrainz.org/recording/{item["id"]}',
        "spotify_urls": [r.get("url", {}).get("resource", "") for r in item.get("relations", []) if r.get("target-type") == "url"]}


class Catalogue:
    _token_lock = threading.Lock()
    _tokens = {}

    def __init__(self, config=None):
        self.config = config or DiscoveryConfig.load()

    def _get(self, path, params=None, provider=None):
        provider = provider or self.config.catalogue
        reserve(provider, 1.05 if provider == "musicbrainz" else .3)
        headers = {"User-Agent": f"Verse/0.1 ({self.config.contact})"}
        if provider == "spotify":
            headers["Authorization"] = "Bearer " + self._token()
        elif not self.config.contact:
            raise DiscoveryError("External discovery needs VERSE_CATALOGUE_CONTACT (a contact email or URL) for MusicBrainz.")
        base = "https://api.spotify.com/v1/" if provider == "spotify" else "https://musicbrainz.org/ws/2/"
        try:
            return check_response(requests.get(base + path, params=params, headers=headers, timeout=(3, 8)), provider)
        except requests.RequestException as error:
            raise DiscoveryError("External catalogue network request failed. Local search is still available.") from error

    def _token(self):
        if not self.config.client_id or not self.config.client_secret:
            raise DiscoveryError("Set VERSE_SPOTIFY_CLIENT_ID and VERSE_SPOTIFY_CLIENT_SECRET for Spotify discovery.")
        key = (self.config.client_id, self.config.client_secret)
        with self._token_lock:
            token = self._tokens.get(key)
            if token and token[1] > time.time(): return token[0]
            try:
                result = requests.post("https://accounts.spotify.com/api/token", data={"grant_type": "client_credentials"},
                    auth=key, timeout=(3, 8))
                data = check_response(result, "spotify")
                self._tokens[key] = (data["access_token"], time.time() + int(data["expires_in"]) - 30)
                return data["access_token"]
            except (requests.RequestException, KeyError, ValueError) as error:
                raise DiscoveryError("Unable to authenticate the Spotify catalogue. Check server configuration.") from error

    def search(self, query):
        provider = self.config.catalogue
        if provider not in ("spotify", "musicbrainz"):
            raise DiscoveryError("VERSE_CATALOGUE must be auto, spotify, or musicbrainz.")
        key = "query:" + provider + ":" + hashlib.sha256(query.strip().casefold().encode()).hexdigest()
        cached = cache_get(key)
        if cached is not None: return cached
        try:
            if provider == "spotify":
                data = self._get("search", {"q": query, "type": "track", "limit": 10})
                tracks = [spotify_track(item) for item in data["tracks"]["items"]]
            else:
                escaped = query.replace('\\', '\\\\').replace('"', '\\"')
                data = self._get("recording/", {"query": f'recording:"{escaped}" OR artist:"{escaped}" OR release:"{escaped}"', "fmt": "json", "limit": 10})
                tracks = [musicbrainz_track(item) for item in data["recordings"]]
        except (KeyError, TypeError, ValueError) as error:
            raise DiscoveryError("External catalogue returned an unexpected track response.") from error
        for track in tracks: cache_put("selection:" + track["key"], track, 86400)
        cache_put(key, tracks, 300 if tracks else 30)
        return tracks

    def lookup(self, selected):
        if selected["provider"] == "spotify":
            track = spotify_track(self._get("tracks/" + selected["recording_id"], provider="spotify"))
        else:
            item = self._get("recording/" + selected["recording_id"], {"inc": "artist-credits+releases+isrcs+url-rels", "fmt": "json"}, provider="musicbrainz")
            # An empty release is an intentional recording-only selection. Do
            # not silently replace its identity with the first returned release.
            track = musicbrainz_track(item, selected.get("release_id", ""))
        if track["key"] != selected["key"]:
            raise DiscoveryError("Catalogue returned a different recording identity.")
        return track
