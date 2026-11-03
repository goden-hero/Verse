# MusicBrainz-only search and selected-song actions

Implemented on `feat/musicbrainz-search-panel`, based on `9d51561`. Activated on
Verse-test with the operator's explicit approval on 2026-11-03. No framework or
dependency was added; the existing appearance, persistent player, acquisition
worker, generated playlists and library bulk-selection tools are retained.

## Interaction and request boundaries

| Interaction | Work performed |
| --- | --- |
| Typing | Debounced `GET /api/v1/search/external`, forced to MusicBrainz; persistent catalogue cache/rate budget only |
| Opening a result | `GET /api/v1/catalogue/recordings/{mbid}?release_id=…`; check source identities/saved requests, then existing ranked resolver if needed |
| Play | Existing playback function and persistent audio element; never triggered by row selection |
| Download | Reuse/create the existing persistent request; unchanged acquisition/single-file indexing pipeline |
| Missing song → Add | Persist playlist destination with the request, then append transactionally after Ready |

The typing endpoint does not query songs, source mappings or request jobs, and does
not enrich each result with local availability. Optional Spotify credentials do
not change this endpoint's catalogue. Post-selection resolution may still use the
existing Spotify metadata adapter internally; MusicBrainz-only browsing does not
remove those existing acquisition dependencies.

The overlay is one input, Close, a compact status/retry area and one scrollable
list. Rows contain artwork/fallback, truncated title/artist and optional duration,
with no checkboxes, provider sections or song-action buttons. Results remain
visible during replacement loads/errors. Recording MBIDs are deduplicated; distinct
MBIDs/versions remain separate. Lazy artwork nodes are reused for retained rows;
no server-side artwork lookup is run for each result.

Selecting a row opens a compact desktop dialog or mobile bottom sheet. Query,
results and scroll position stay underneath; late availability/search responses
cannot replace a newer selection or request state. The panel shows Play/Add for
local songs, Download/Add for missing recordings, and progress/Retry/version
selection for existing requests. Selecting/closing a panel never queues, starts
playback or cancels an acquisition.

Arrow keys highlight results; Enter opens a recording; Escape closes the topmost
dialog before the search. Focus is restored without scrolling the list. Nested
playlist pickers use existing components. Bulk local search, multi-selection,
keyboard selection and manual creation remain available through **Select library
songs** in the library and **Add songs** inside a playlist, separately from the
catalogue overlay.

## Durable playlist intent

Migration `7b8c9d0e1f2a` adds only `song_request_playlists`. It retains request ID,
destination ID/name/creation timestamp, the existing caller identity, pending/
added/failed state, counts, error and timestamps. No existing playlist/song schema
or ownership model is redesigned.

The request API accepts optional positive `playlist_id`, validates it with the
existing playlist owner scope, and saves the destination in the same transaction
as the request. Repeated/concurrent requests for the same recording reuse its job,
including across releases of that MBID. Different recording MBIDs are not merged
by title. The `(request_id, playlist_id)` constraint deduplicates append intents.

The worker processes Ready/pending intents on startup and during ordinary work.
It uses the append-only playlist service, not the legacy replacement helper.
Memberships and completed intent state commit together. Original positions remain
unchanged, new songs follow the highest existing position, and existing memberships
are skipped. A crash/failed append can retry without downloading/indexing again.

Download failures retain destinations. A missing destination marks only the append
intent failed: the song stays Ready/playable. Its creation timestamp also guards
against SQLite reusing a deleted playlist's ID for an unrelated replacement.
Renamed destinations remain valid. Ready pending intents keep lightweight polling
alive; progress updates patch the selected panel/history rather than the search
list, library table or audio element. Closed panels receive concise completion/
failure notifications. Retry clears the previous attempt's visible error.

## Automated verification

The relevant combined suite passed **167 tests**, with 1127 existing framework/
datetime deprecation warnings, in **74.24 seconds**. `git diff --check` and both
JavaScript syntax checks passed.

```bash
PATH=/home/pyro/apps/Verse-test/.venv/bin:/usr/local/bin:/usr/bin:/bin \
  .venv/bin/python -m pytest -q -o addopts='' --disable-warnings \
  tests/test_catalogue_workflow.py tests/test_discovery_requests.py \
  tests/test_manual_playlists.py tests/test_media_session.py \
  tests/test_playlist_read_performance.py tests/test_playlist_services.py \
  tests/test_playlist_api_routes.py tests/test_auth_sessions.py \
  tests/test_service_user_ownership.py tests/test_api.py tests/test_web_api.py \
  tests/test_web_loading.py tests/test_web_frontend_auth.py \
  tests/test_web_frontend_seed.py tests/test_cli_scan.py tests/test_scanner.py \
  tests/test_metadata.py tests/test_technical.py tests/test_database.py tests/test_search.py
```

The new backend regressions trace SQL to assert no songs/sources/jobs are queried
by typing, force MusicBrainz even with Spotify credentials, verify MBID deduplication,
post-selection identity matching/caching without enqueueing, five concurrent
requests/release variants, durable destinations, append order/duplicates, failed
download recovery, transaction rollback, deleted/reused destination IDs and restart
recovery without reacquisition. Real generated WAV files and ffprobe exercise
essential indexing; external acquisition is mocked in automated tests.

Real HTML/CSS/JS runs in offscreen Chromium at **1440×900** and **390×844**, with
synthetic services/audio. Checks cover debounce, no pre-selection actions/local
queries, retained results on failures, selection/picker failure and lost-response
retry, version choices, stale responses, query/scroll/focus restoration, mobile
sheet bounds/touch targets, completion notifications and unchanged playback/DOM.
The separate existing bulk-playlist probe passes at both sizes as well.

## Activation and actual live checks

The actual API/worker configuration was inspected: both use the Verse-test cwd,
venv and SQLite database; music remains `/home/pyro/Music`, the configured provider
is MusicBrainz, and the real contact remains configured server-side. No secrets
were changed or printed.

With the worker stopped, SQLite's online backup API safely backed up the active
database to:

`/home/pyro/apps/Verse-test/data/backups/catalogue-redesign-20261103T064320Z/music_rec.db`

The backup file/directory were created with modes 0600/0700, and integrity checks
passed. The additive migration advanced `6a7b8c9d0e1f` to `7b8c9d0e1f2a`. Only
the system API `verse-test.service` and user worker
`verse-test-request-worker.service` were restarted; both are enabled/running,
exactly one worker is present, and no identity backfill was repeated.

A real **Darpan** catalogue search returned **25 unique MusicBrainz recordings**,
including Fly Away, with no `song`/`job` availability fields. Only after selecting
Fly Away did the new endpoint return existing song **436** and its Ready job.

The updated read-only live UI probe passed at both viewport sizes. It used the
actual API/HTML/JS, recorded **zero local-search/availability calls while typing**,
found the selected MBID in the actual results, then checked Play/Add and all **76
playlist choices** visible to the signed-in account. Query/scroll restoration
passed. No playback, request submission or playlist append was performed by this
probe: browser mutations and external networking are blocked, and temporary
verification sessions are revoked on exit.

All **438 original songs**, **93 playlists**, **988 memberships/positions**, and
the **six pre-existing request rows** matched the backup exactly after activation.
A seventh request came from a separate remote client during verification (the API
journal confirms its POST). It failed the existing audio-duration validation and
was not indexed; this is not reported as a successful external download. Validation
was not relaxed, and the separate user's request was preserved. No live playlist
intent was submitted by the verification; download-then-add end-to-end coverage
uses isolated databases/mocked acquisition, not modifications to live playlists.
The separate failed request (**Dreamer’s Song — Regina Song**) was also checked
through the real UI at both viewport sizes: its selected panel shows a terminal
failure/error and Retry rather than Resolving, with no retry/download triggered by
the probe. Offscreen graphics-backend warnings are not physical-device results.

## Physical-iPhone checklist and limits

Offscreen Chromium is not Safari, a touchscreen, VoiceOver, or real background
audio. Test Safari and the Home Screen app separately after reloading the new
assets:

1. Type titles/artists; verify keyboard sizing, scrolling and truncated labels.
2. Open a result with the keyboard visible; check the bottom sheet, safe areas,
   close control and return to the same query/list position.
3. Play a local recording explicitly; open/close the playlist picker and ensure
   music continues throughout.
4. Download a missing recording and choose a playlist; close/reopen the app while
   queued. Verify Ready and one appended membership without a refresh.
5. Exercise provider/selection/download failures, Retry and Choose version; verify
   old errors clear, destinations survive, and deleted destinations leave the
   song playable with an explicit append error.

Provider mappings/audio availability can still fail. The server's recording and
duration checks remain in force; a redesigned search is not a guarantee that
every MusicBrainz recording can be acquired, nor a lossless-audio upgrade.
