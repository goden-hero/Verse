# External discovery and song requests

Implemented on `feat/external-song-requests`. Initial development did not change
the running instance. Verse-test was subsequently activated and live-verified;
see the [2026-11-03 activation report](external-song-requests-activation-2026-11-03.md).
The later [recording-resolution fix and Fly Away live check](request-resolution-2026-11-03.md)
adds metadata fallback and version selection without a database migration.

## Configuration and activation

The inspected environment has spotDL **4.6.0**, ffmpeg, and ffprobe installed in/
for Verse's virtual environment. No custom Spotify credentials or
`~/.spotdl/config.json` were present. The initial checkout database was at
Alembic revision `5f2b3c4d6e7f`; activation advanced Verse-test to `6a7b8c9d0e1f`.

Set these server-side variables in the same environment/`.env` used by **both**
the API and worker, replacing the examples with real values:

```dotenv
VERSE_MUSIC_DIR=/absolute/path/to/your/music
VERSE_CATALOGUE=auto
VERSE_CATALOGUE_CONTACT=https://your-real-contact-page.example
```

`VERSE_MUSIC_DIR` is required for requests; there is no guessed download location.
The worker and API should run as the same OS account with access to the database,
music directory and any spotDL cookie/config files. `DATABASE_URL` must be identical
for both processes. Restart the API after changing its environment.

`auto` selects official Spotify discovery when both credentials below exist,
otherwise MusicBrainz:

```dotenv
VERSE_SPOTIFY_CLIENT_ID=your-own-spotify-client-id
VERSE_SPOTIFY_CLIENT_SECRET=your-own-spotify-client-secret
```

`SPOTIPY_CLIENT_ID` / `SPOTIPY_CLIENT_SECRET` are also accepted. Secrets and tokens
remain server-side; neither is included in search responses, request records or
browser code. Tokens are obtained with client credentials and cached in memory.
Do not use spotDL's bundled defaults as your official catalogue credentials.

Spotify currently requires an eligible developer application; Development Mode
requires the app owner's Premium subscription. Verse requests at most ten tracks
per search, matching the revised API limit. Keys alone do not prove the app has
working access: 401/403 responses remain visible configuration errors, with local
search unaffected. Use `VERSE_CATALOGUE=musicbrainz` explicitly if needed.
[Spotify's current migration requirements](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)

MusicBrainz discovery needs no API secret, but requires the real contact URL/email
above for its identifying User-Agent. A shared SQLite budget admits at most one
MusicBrainz call per 1.05 seconds across the API and worker, and honors Retry-After.
Busy callers receive a useful error/Retry action instead of overwhelming the
provider. Coordinate any other MusicBrainz tools on the same IP too.
[MusicBrainz rate-limit guidance](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)

After backing up the configured database and reviewing the migration:

```bash
.venv/bin/alembic current
.venv/bin/alembic upgrade head
.venv/bin/python -m app.main request-worker --once --backfill-identities
```

These are operator instructions for another installation; Verse-test's actual
backup and migration are recorded in the activation report. The
migration adds four tables only: requests, exact source identities, catalogue
cache, and provider budgets. An automated migration test preserves an existing
playlist's name, track, and position. Legacy databases without an Alembic baseline
need schema review; do not blindly stamp a version over an unknown schema.

`--backfill-identities` imports exact Spotify source tags from already indexed
files. Run it once with the normal worker stopped; do not put it in the persistent
service's startup command. `--once` can also process one queued job, so run the
initial backfill before accepting requests. It reads tags, not an entire audio-analysis pipeline, and
does not change songs/playlists. This permits reuse of older spotDL downloads.
Untagged tracks are intentionally **not** matched by title alone.

Run exactly one acquisition worker per SQLite database on one Linux host. The
worker takes an advisory lock beside the database, inherited by acquisition
subprocesses. A second worker exits; unrelated API processes remain available.
`--once` processes at most one due job for diagnostics. It does not wait for jobs
whose retry time is in the future.

For systemd, customize [the service example](../deploy/verse-request-worker.service.example)
and install/enable it only when ready. The example uses `Restart=on-failure` and
`KillMode=control-group`, so service restarts stop downloader/ffmpeg children too.
Useful operator commands after a system-level installation are `systemctl status
verse-request-worker` and `journalctl -u verse-request-worker -f`. Verse-test uses
the enabled user service `verse-test-request-worker.service` instead; use
`systemctl --user` and `journalctl --user` for that service. User lingering is
enabled so the worker remains available after logout and at boot.

After replacing the example's account and paths, an operator can install it with:

```bash
sudo cp deploy/verse-request-worker.service.example /etc/systemd/system/verse-request-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now verse-request-worker.service
```

spotDL is an optional acquisition dependency (`pip install -e '.[acquisition]'`
if it is absent); the inspected virtual environment already has it. The resolver
needs the spotDL Python library in Verse's environment. Downloads default to
`sys.executable -m spotdl`; `VERSE_SPOTDL_EXECUTABLE` can specify an alternative
**executable path**, not a shell command. Existing spotDL config is honored when
present, but the output, single-thread setting, format and retry limits are
overridden. Configure provider authentication/cookies as for your working manual
spotDL command, under the worker's account. No user input is interpolated into a
shell command. [spotDL usage](https://spotdl.github.io/spotify-downloader/usage/)

## Recording resolution, processing, recovery

The same search overlay contains separate **In your library** and **Available to
request** sections. Local results do not wait for external calls. External searches
are debounced, have cancellation/generation guards, and use a persistent TTL cache
(five minutes for hits, thirty seconds for empty results). Selected-result snapshots
last 24 hours and survive API restarts. Requests use these server-side snapshots,
not arbitrary client-supplied URLs/metadata. Previously created jobs remain usable
after snapshot expiry.

Spotify track IDs are exact identities. MusicBrainz identities include both the
recording MBID and selected release MBID, preserving release/version distinctions.
ISRCs are retained where supplied, but are **not** treated as a universal dedupe
key. The worker refreshes selected metadata before first acquisition.

MusicBrainz MBIDs are never passed to spotDL. Before deciding identifiers are
absent, the worker fetches the full recording with
`artist-credits+releases+isrcs+url-rels`. Spotify URL and ISRC resolution retain
priority; up to three identifier candidates/ISRC queries are bounded within the
resolver subprocess. Conflicting returned ISRCs are rejected. A recording-only
selection keeps its original identity even when the full lookup includes releases.

If usable identifiers/matches are unavailable, two bounded metadata queries use
the installed spotDL Spotify client. On this installation it is **SpotipyFree**,
not paid official Spotify discovery. This still depends on Spotify metadata access;
text search is not a way to remove all Spotify dependencies. No unsupported CLI
options or first-title-match download shortcut are used.

Candidates are ranked using title, individual artist credits, duration, album,
and version/disambiguation. Known artist/version conflicts are rejected. Automatic
metadata continuation requires an exact normalized title (optionally qualified by
the selected disambiguation), credits and album, close known
duration, represented disambiguation, a heuristic score of at least 95/100 and a
margin of at least eight points over the next plausible candidate. The score is
**not** a probability or a verified identity. Full thresholds and evidence are in
[`resolution.py`](../app/discovery/resolution.py).

Uncertain/ambiguous candidates persist in `resolved_json`; the job enters
`awaiting_choice`. A small inline **Choose version** interface shows up to five
versions with artist/title/album/duration/version and a Use this version action.
`POST /song-requests/{id}/choose-version` accepts only a saved server candidate,
atomically queues the same job, and is idempotent for repeated identical choices.
Options survive restart; the worker never silently chooses one on startup.

No suitable recording is a terminal `failed` state, not an automatic search loop.
Retry discovery and Search again remain available. Network/provider failures keep
the existing bounded retry behavior. Starting another attempt clears the previous
error; older poll/search responses cannot overwrite a newer failure, choice or
success. Inactive/awaiting-choice jobs do not keep active polling alive; opening
search, returning to the page, and explicit Refresh recover current shared state.

Resolution provenance is stored/returned as `resolution`: method, score/evidence,
`user_selected`, and `verified_identity`. Metadata or user-selected approximate
mappings do **not** get inserted as exact MusicBrainz aliases in `song_sources`.
The canonical Spotify source still deduplicates acquisition, and the original
request identity still deduplicates the job; Ready results remain Play/Add capable.

`POST /api/v1/song-requests` performs only local database/cache work and returns
HTTP 202 with a persistent UUID. The unique identity constraint makes concurrent
requests reuse the job. Exact provenance already in the library is reused. Once
resolved, cross-catalogue requests can also reuse the canonical Spotify source.
There is no title-only merge or multi-user ownership redesign; the small shared
library and request history remain shared.

States are `queued → resolving → downloading → indexing → ready`, or `failed`;
ambiguity pauses at `awaiting_choice → queued` after a user choice.
Attempts, errors, retry times, selected/resolved identities, completed-file path,
and resulting song ID are durable. Defaults: three attempts, exponential bounded
backoff, 90 seconds for the resolver, 600 seconds for a download; environment
overrides are `VERSE_REQUEST_ATTEMPTS` (1–5) and `VERSE_DOWNLOAD_TIMEOUT` (30–1800).
Timeouts terminate the downloader's process group. An explicit Retry can restart
a failed job without creating another request.

Before acquisition, a separate song-only audio-source lookup must uniquely match
the selected title, artist, album/version and duration. If song search only returns
a different release, at most three exact-album listings are inspected. No fuzzy
video/live-performance fallback is accepted. The verified source is checkpointed
in staging, passed to spotDL as `YouTubeURL|SpotifyURL`, and checked against the
download's source comment before publishing. Ambiguous/unavailable sources fail
explicitly rather than substituting another version. This narrows compatibility
deliberately; metadata verification is still not acoustic fingerprinting.

Downloads go to hidden `.verse-requests/<spotify-id>/` under `VERSE_MUSIC_DIR`.
The output is the relative spotDL template `track.{output-ext}` with that directory
as cwd: literal filenames are treated as directories by spotDL 4.6, and its
absolute-path sanitizer removes leading dots. This template avoids both pitfalls.
The worker checkpoints completed output before indexing. It verifies tags/source
ID, finite positive duration, codec, channels and sample rate, then atomically
publishes `Requests/<spotify-id>.mp3` under that same root. Partial files are never
inserted as songs. Invalid staging output is quarantined rather than served;
existing final files are not silently overwritten.

Essential indexing reuses the scanner's content hash, mutagen extractor and
ffprobe extractor for **one file**, then commits Song/TechnicalMetadata/source
aliases and ready status together. Interrupted stages return to queued on worker
startup. A saved completed file or valid leftover is reused; ordinary indexing,
database and missing-tool failures do not cause another download. Byte-identical
content also reuses the existing Song row.

Optional MIR/features/embeddings are separate from readiness:

```bash
.venv/bin/python -m app.main request-enrich LOCAL_SONG_ID
```

This analyzes only that audio file and refreshes numeric indexes from stored
features. It does not rescan library audio. Run optional index-maintenance commands
one at a time, separately from acquisition. Semantic AI enrichment remains the
existing `enrich-semantic` maintenance command. Neither is required to play or add
the newly indexed song to a playlist, and neither is automatically run inline.

The app polls active requests every three seconds without overlapping polls;
terminal and awaiting-choice history refreshes on opening search, visibility or an
explicit Refresh. State rehydrates after reload/sign-in; failed polls
retain previous content and expose Refresh. Ready results become normal Play/Add
actions using the existing persistent audio player and playlist picker. Request
updates patch their own rows, not the library table or playback queue.

API endpoints: `GET /search/external`, `POST /song-requests`, `GET /song-requests`,
`GET /song-requests/{id}`, `POST /song-requests/{id}/retry`, and
`POST /song-requests/{id}/choose-version`, all under `/api/v1`.
Submitting/retrying requests requires the existing signed-in session.

## Validation and remaining limits

The combined relevant regression suite passed **154 tests** after the resolution fix. Existing datetime/
framework deprecation warnings remain. The test command was:

```bash
.venv/bin/python -m pytest -q \
  tests/test_discovery_requests.py tests/test_manual_playlists.py \
  tests/test_media_session.py tests/test_playlist_read_performance.py \
  tests/test_playlist_services.py tests/test_playlist_api_routes.py \
  tests/test_auth_sessions.py tests/test_service_user_ownership.py \
  tests/test_api.py tests/test_web_api.py tests/test_web_loading.py \
  tests/test_web_frontend_auth.py tests/test_web_frontend_seed.py \
  tests/test_cli_scan.py tests/test_scanner.py tests/test_metadata.py \
  tests/test_technical.py tests/test_database.py tests/test_search.py
```

Automated checks use temporary SQLite databases, production cookie/session
dependencies, mocked catalogue/download operations, real generated WAV files and
ffprobe, and a migration preserving pre-existing playlist data. They cover local/
external independence, current Spotify limits, cache/rate budgets, duplicates under
five concurrent requests, version separation, failed download/indexing recovery,
interrupted stages, transaction rollback, subprocess timeout/group cleanup, path
containment, single-worker locking, and essential indexing through playback and
playlist addition.

The offscreen Chromium probe runs the real HTML/CSS/JS at 1440×900 and 390×844 with
synthetic services/audio and blocked external networking. It covers independent
search, stale errors, lost responses and deduplicated retry, persisted status
bootstrap/rehydration, state changes, ready Play/Add, failed-job retry, and unchanged
unrelated library/audio nodes. This is not a physical Safari/iPhone audio test.

Verse-test's real MusicBrainz search, exact ISRC resolution, acquisition, indexing,
playback streaming and duplicate reuse passed for one recording; see the activation
report. That does not establish official Spotify catalogue eligibility or universal
ISRC/source coverage. Other installations still need an operator smoke test with
a recording they are authorized to obtain. Missing identifiers now permit a
conservative metadata match or explicit version choice; no suitable match still
fails without substitution and does not require paid discovery as its only
recovery option. Legacy files without stable source tags cannot be reliably
recognized without additional identity/fingerprint work, so they are not guessed.

spotDL obtains audio from its supported sources, **not Spotify's lossless masters**.
An MP3 request is not lossless; this change does not upgrade your existing MP3s.
Catalogue identity/tags/duration checks are not an acoustic fingerprint or proof of
bit-identical mastering. Use only sources/recordings you have rights to acquire and
review the providers' applicable terms.

On the physical iPhone, check both Safari and Home Screen launches: local search
while the provider is unavailable, requesting while another song plays, closing/
reopening the app with a pending job, worker restart, failure/Retry, and using Play/
Add when ready. The feature does not grant iOS background execution or offline
downloads; processing happens on the server.
