# Performance and reliability implementation results

Branch: `fix/smooth-playlist-loading`. Baseline: `a0282bc` / original HEAD. No deployment, migration, permission redesign, new dependency, or live playlist edit was performed. The pre-existing deleted MP3 and untracked diagnosis document were preserved.

## Implemented

- Independent `SessionFactory()` scopes for HTTP dependencies and authentication resolution; commit/rollback/final close retained. No WAL/pool changes were necessary. Audio streaming obtains only the file path and releases its database dependency before sending the stream.
- Shared aggregate projections for playlist metadata, duration/count and playback statistics, including empty playlists. The Recently Played API now supplies the required `songs_count`; the internal `song_count` alias remains for compatibility. Detail, song-page and ranked-search reads select lightweight columns and boolean artwork availability, not image blobs.
- Playlist song reads no longer load the songs twice. Start/resume checks fetch only the playlist ID. Playlist metadata and membership edits commit together.
- Covers check a bounded, thread-safe, revision-aware cache after a small four-row metadata query, before loading artwork. Cold covers fetch only the first four images. Service content changes invalidate covers; rescanned hashes/playlist timestamps participate in cache keys. Local ORM artwork replacements invalidate cached covers, including same-length replacements. Song artwork and covers provide private conditional ETag responses. Existing composite layout and JPEG output were retained.
- Request coordinator shares equivalent pending reads, caches successful reads briefly, cancels superseded reads, and rejects stale successes and errors. Detail navigation has a separate navigation-generation guard, so a late response cannot navigate away from Home. Reads have deadlines and shape validation. Intentional cancellation is silent.
- Retry actions preserve the previous successful content; errors are independent per section. Returning Home recovers failed sidebar/home resources. Selecting the current view avoids redundant reloads. Identical background refresh results do not recreate DOM. Creation/deletion invalidates affected reads, and editing uses revision-aware backend data/cache invalidation. Sidebar loading pages beyond the old 50-playlist truncation.
- Track changes update previous/current active rows instead of rebuilding the library table. Like changes patch matching buttons optimistically, with rollback/retry on failure. Same-song artwork elements are reused; unchanged controls/text are skipped. Library/detail rows and queue entries use delegated listeners rather than binding each recreated row.
- The active queue view reconciles a maximum 40-row page. The complete playback queue remains intact and accessible through Next/Previous queue pages; hidden mobile queues are not rebuilt on desktop. Queue order, repeat, shuffle and resume behavior remain available.
- Panel resize events schedule at most one width write per animation frame. Dividers no longer animate layout width. Equalizer bars and mobile progress use transforms. Broad transitions were narrowed, common timings shortened, and reduced-motion preferences respected. Blur/shadow intensities were not reduced without target-GPU evidence.
- Progress writes are serialized/coalesced by playback session, with handled HTTP/network errors. Playback starts are generation-guarded; the already-loaded playlist's song projection is reused where available.

## Comparable backend measurements

Dataset/environment: the same 434-song, 75-pyro-playlist, 745-membership library and installed Python/SQLAlchemy/FastAPI environment used in the diagnosis. SQLite backups in `/tmp` isolated all diagnostic writes. Service timing includes query execution/projection; it excludes transport/rendering. First calls include query compilation and warm calls benefit from system caches; these are not OS-cold disk benchmarks.

| Read | Before SQL | After SQL | Before first / warm | After first / warm |
| --- | ---: | ---: | ---: | ---: |
| Sidebar, 50 playlists | 610 | 1 | 307.7 / 243.7 ms | 46.6 / 3.3 ms |
| Recently Added, 6 | 105 | 1 | 42.8 / 41.8 ms | 4.6 / 2.2 ms |
| Recently Played, 4 | 47 | 1 | 22.3 / 21.6 ms | 5.5 / 2.8 ms |
| Continue Listening, 4 | 37 | 1 | 18.1 / 16.8 ms | 5.1 / 2.2 ms |
| Songs, 100 | 2 | 2 | 111.0 ms | 12.0 ms |
| Detail, 15 songs including seed lookup | 20 | 3 | 9.0 ms | 7.4 ms |
| Cover, 25 songs, cold | 27 | 2 | 54.6 ms | 48.5 ms |
| Cover, warm | 27 | 1 | 11.1 ms | 1.2 ms |

Metadata artwork materialization fell from 50,157,375 bytes for the sidebar (12,725,222 bytes for the song page) to **zero**. Cold cover reads intentionally fetch image bytes for at most four songs; warm cover reads select only revision metadata. The old probe's ORM byte counter does not count raw row bytes, so its zero cold-cover counter must not be interpreted as zero cold image loading.

The same actual ASGI mixed workload of 48 requests (two batches of 24, metadata/cover/progress) produced **24 HTTP 500s and 14 overlapping session scopes before**, and **48 HTTP 200s with zero overlap/errors after**. Baseline batch times were 11.64 / 5.94 seconds; after times were 224 / 171 ms. Baseline exception counts/timings are scheduling-dependent. The baseline included Recently Played validation failures as well as session/SQLite failures; all five serial endpoint checks returned 200 afterward.

## Comparable offscreen UI measurements

`tests/browser_responsiveness_probe.py --baseline` reads the original HTML/CSS/JS from `a0282bc`; without the flag it reads working-tree code. Both runs use the same real 434-song metadata fixture, 1440×900 offscreen Qt/Chromium, mocked transport and unavailable image endpoints. External font loading is removed. Each metric includes 10 synchronous DOM operations plus a deliberate layout flush. No GPU/on-device FPS or production INP claim is made.

| Operation | Before | After |
| --- | ---: | ---: |
| Routine track-change DOM work, 100-song queue | 59.9–67.2 ms | 6.8–11.6 ms |
| Like DOM update | 44.6–48.4 ms | 0.1–1.9 ms |
| Build full-library remaining queue | 109.2 ms first, 68.5–76.3 ms repeated | 4.4 ms first page; ≤0.1 ms unchanged |
| Queue rows / image elements, full-library case | 866 / 866 across both views | 40 / 40 in active view; hidden mobile 0 |
| Width mutations in a 100-mousemove burst | 100 | 1; same final width |
| Typical 25-track table render, warm | 2.1–2.6 ms | 2.1–2.4 ms |
| Forced full 100-row library rebuild | 46.2–50.1 ms | 65.0–66.9 ms |
| Forced full 434-row detail rebuild, stress case | 36.8–39.2 ms | 57.2–58.4 ms |

Routine changes preserve unrelated row nodes and same-song artwork, and fit the measured 16 ms target. **Initial/full table creation has not improved in this offscreen measurement**, and its forced-layout results are slower. It remains outside a single-frame budget. These paths are no longer invoked for track/like updates or identical background refreshes; initial metadata delivery is substantially faster. A further narrowly scoped improvement would chunk initial very large table construction after target-device profiling. The browser measurement does not isolate the cause of the full-render difference, so no unmeasured paint-effect reduction was made to conceal it.

## Verification

The combined relevant suite passed **53 tests in 26.18 seconds**, with existing datetime deprecation warnings:

```bash
.venv/bin/python -m pytest -q \
  tests/test_playlist_read_performance.py tests/test_playlist_services.py \
  tests/test_playlist_api_routes.py tests/test_service_user_ownership.py \
  tests/test_auth_sessions.py tests/test_web_api.py tests/test_api.py \
  tests/test_search.py tests/test_web_loading.py \
  tests/test_web_frontend_auth.py tests/test_web_frontend_seed.py
```

Focused additions:

- File-backed SQLite tests replace only the database factory, retaining the production `get_db`, `get_session`, middleware and response validation. One and five simulated clients make 372 authenticated HTTP requests in total, including overlapping progress writes, nonempty Recently Played reads and conditional cover requests. They assert no session sharing and no remaining checked-out connections.
- Query-count tests grow playlist counts and assert one list/section query, accurate counts/durations/statistics, empty-playlist behavior and no materialized Song entities. Cover tests check cold/warm work and membership invalidation.
- Node tests execute original client functions against controlled delayed promises. They verify shared reads, cache use, superseded successes/failures, malformed JSON, wrong shapes, server errors, Retry and navigation cancellation.
- Offscreen checks exercise actual `playSong` and `toggleLikeSong` DOM paths, artwork reuse, preserved sidebar content on a temporary 503, desktop/mobile error clearing through Retry, A→B races, Home cancellation, active-view deduplication, full queue availability/paging and frame-coalesced resizing.
- The existing six-case Node loop/playback test passes. JavaScript syntax, Python compilation and `git diff --check` pass.
- A final focused audio-stream API test passed after the early read-transaction release. Offscreen and Node loading checks were repeated after the identical-refresh/mobile-Retry refinement and passed.

Run the offscreen checks with:

```bash
.venv/bin/python tests/browser_responsiveness_probe.py --baseline
.venv/bin/python tests/browser_responsiveness_probe.py
node tests/test_index_loading.js
node tests/test_loop_playback.js
```

The sandbox blocks asyncio/Chromium sockets, so HTTP and offscreen checks were run outside that restriction. This does not involve deployment access. The browser emits OpenGL warnings and uses offscreen/software behavior; functional assertions still complete successfully.

## Preservation and remaining limits

- No live service restart, deployment or database migration. No live playlist/songs were added, removed or reordered. The before/after SHA-256 over ordered live `playlists` and `playlist_songs` rows is unchanged: `49ad823f745642b0f058afd6cf1032c57d9bc1da8ea2fe0f422ef452ad021a5d`.
- Permission and ownership architecture is unchanged. Existing ownership tests were run to check compatibility, not to introduce a redesign.
- Real-device scrolling, GPU compositing, mobile touch interaction and real audio/network latency still need deployment/browser testing. Blur and shadow character is preserved.
- First/full table rebuilds remain a measured limitation. Routine updates are materially improved; the report deliberately does not claim that every rendering path fits 16 ms.
- Streaming explicitly ends its read-only transaction after obtaining the file path, retaining compatibility with the declared FastAPI dependency range. No new package was installed.
- Queue paging limits DOM size; it does not truncate the playback queue. Cache validation still checks source metadata; conditional 304 responses save transfer, not every database operation.
