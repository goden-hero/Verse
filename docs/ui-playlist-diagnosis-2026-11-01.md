# Verse UI performance and playlist-loading diagnosis

Investigation date: 2026-11-01. Inspected revision: `a0282bc` (persistent sessions). No application code was changed. All diagnostic database writes used SQLite backups in `/tmp/verse-diagnosis-f7cWoO/`; the live library and playlists were not edited. The pre-existing deleted MP3 in the worktree was left untouched.

## Outcome and confidence

There are several distinct defects, not one animation-duration problem:

1. **Confirmed, P0:** thread-local database sessions are reused by overlapping FastAPI requests. A controlled concurrent run reproduced session-state failures and SQLite errors. An in-memory diagnostic change to allocate a fresh Session per scope eliminated those failures in the same workload.
2. **Confirmed, P0:** nonempty Recently Played results fail response validation because the service returns `song_count` while the API requires `songs_count`. This is separate from the sidebar failure.
3. **Confirmed, P1:** failures leave the sidebar without recovery, and old requests can overwrite new results or navigate the user back to a stale playlist.
4. **Confirmed, P1:** metadata and cover endpoints do hundreds of lazy SQL queries and unnecessarily read artwork blobs. Rendering also rebuilds large DOM subtrees on routine playback actions.
5. **Likely contributors, P2:** eager artwork loading, panel relayout on every mouse event, animated layout properties, and large backdrop blurs. Their exact contribution to on-device dropped frames needs a deployment browser trace.

The concurrency reproduction establishes an application defect and a credible mechanism for the reported intermittent failure. It does not establish which exception occurred in any particular historical deployment incident; the available application log does not contain the corresponding request tracebacks.

## 1. Architecture and request flows

No `AGENTS.md` was present in the repository, its `.agents`/`.codex` directories, or the checked ancestor directories. The README describes a PySide6 desktop application but omits much of the current web architecture. Source code confirms that the reported web interface uses **plain JavaScript and CSS, without React/Vue or a frontend build framework**.

| Layer | Current implementation |
| --- | --- |
| Web entry | `app/web/index.html:1018` loads `index.js`; desktop and mobile DOM structures coexist. |
| Client state/routing | `app/web/index.js:4`, `:394`: global state, class-based view switching, direct DOM manipulation, browser HTML audio. |
| HTTP server | `app/api/server.py:14`, `:34`, `:38`, `:48`: FastAPI, identity middleware, synchronous route functions, static web mount. Uvicorn CLI entry is `app/main.py:225`. |
| Authentication | `app/identity/dependencies.py:13`, `:38`: cookie lookup dispatched to a worker thread, ContextVar identity, then the route. `app/auth/sessions.py:36` performs session/user reads; resolving a session does not update a last-seen timestamp or write on every request. |
| Route DB scope | `app/api/dependencies.py:7` delegates to `app/database/connection.py:68`. Factory uses thread-local `scoped_session`, with `check_same_thread=False`, commit/rollback/final close. |
| Storage/services | SQLAlchemy ORM over file-backed SQLite; playlist memberships and playback sessions are lazy relationships. Metadata, progress and cover work use the same engine. |
| Artwork | PIL composites, process-local dictionary cache, byte `Response` endpoints. No explicit HTTP image cache validators or thumbnail variants. |

Observed fixture: **434 songs, 75 pyro-owned playlists, 745 memberships, 78 playback sessions globally**, approximately 53.9 MB of stored song artwork. SQLite journal mode is `delete`; connection busy timeout is 5,000 ms. Effective SQLAlchemy pool is QueuePool, size 5, overflow 10, checkout timeout 30 seconds. These are observations of this checkout, not assumptions about another deployment.

### Initial load

`DOMContentLoaded` (`index.js:2668`) initializes handlers once, then checks `/api/v1/auth/me` (`:203`). On success, `showAuthenticatedApp()` (`:168`) calls `loadAuthenticatedAppData()` (`:365`), starting five data requests:

- `/songs?page=1&page_size=100` → `LibraryService.get_songs_paginated()` → 100-row home table.
- `/playlists` → `PlaylistService.get_playlists()` → sidebar and mobile drawer, default maximum 50 results.
- `/playlists/continue-listening?limit=4` → `PlaybackSessionService.get_continue_listening()` → Continue cards.
- `/playlists?section=recently_played&limit=4` → recently played service → PlaylistResponse validation → cards.
- `/playlists?section=recently_added&limit=6` → playlist service → cards.

Cards/table rows then create separate song artwork and playlist cover requests. Each cookie-bearing request, including artwork/static requests, also traverses identity middleware. Metadata responses omit image bytes from JSON, but the ORM has already read those bytes from SQLite.

### Navigation, detail and playback

- Home navigation immediately toggles views, replaces the song table with a loader, and launches four more data requests (`index.js:430`). It does **not** reload the sidebar.
- Selecting a playlist awaits `/playlists/{id}` **before** showing its view (`:1203`). The service materializes memberships, songs, seed and stats (`playlist.py:571`). A timestamped cover URL is assigned, the entire table is replaced, and row handlers are attached.
- Clicking a track in a saved playlist first POSTs `/playlists/{id}/play`, then GETs `/playlists/{id}/songs`, then starts the audio stream (`index.js:1485`). The start route unnecessarily fetches full playlist details before starting the session (`routes/playlists.py:365`). The songs route re-fetches each song after the service has already materialized the playlist (`:333`).
- Track changes rebuild playback artwork, both queue trees and the 100-row home table; they request recommendations and post play history (`index.js:1597`). Audio `timeupdate` posts progress at most once every four seconds (`:1549`, `:1983`). It does **not** rebuild the whole UI on each timeupdate.
- Saving/deleting playlists can issue overlapping sidebar/home reloads. Delete explicitly calls `loadHomePageSections()` and then clicks Home, which calls it again (`:1315` and `:430`).

## 2. Prioritized findings

### P0 — Shared Session lifecycle breaks concurrent requests [confirmed]

Sources: [connection.py:35](/home/pyro/apps/Verse-test/app/database/connection.py:35), [connection.py:42](/home/pyro/apps/Verse-test/app/database/connection.py:42), [connection.py:68](/home/pyro/apps/Verse-test/app/database/connection.py:68), [dependencies.py:7](/home/pyro/apps/Verse-test/app/api/dependencies.py:7), [identity/dependencies.py:13](/home/pyro/apps/Verse-test/app/identity/dependencies.py:13).

`scoped_session` defaults to thread-local scope, not HTTP request scope. A synchronous dependency can yield a Session and return its worker thread to the pool while the request continues. Another dependency or auth lookup on that worker can obtain the same object. The route and finalizer can run on other workers. `.close()` resets a Session but does not remove it from the thread-local registry. `check_same_thread=False` permits SQLite connection access across threads; it does not make SQLAlchemy Sessions safe for concurrent use.

A deterministic scope probe confirmed that two overlapping scopes entered on one worker receive the same Session, and that closing/re-entering reuses it. More importantly, the actual ASGI app reproduced sharing under concurrent HTTP requests.

| Controlled workload | Existing handling | Fresh Session per scope, diagnostic control only |
| --- | ---: | ---: |
| Two batches of 24 concurrent requests | 25 / 48 HTTP 500 | 8 / 48 HTTP 500 |
| Detected overlapping Session ownership | 13 | 0 |
| Elapsed per batch | 6.46 s / 6.05 s | 1.93 s / 1.76 s |

The eight control failures were all the separately confirmed Recently Played response contract defect. Existing handling also produced `This session is provisioning a new connection; concurrent operations are not permitted`, `IllegalStateChangeError` on close, invalidated identity maps, detached objects, closed database/result errors and `database is locked`.

The workload used a valid cookie, real routes and services, the copied representative library, metadata reads, cover reads and progress PUTs. The only control change was replacing `connection.SessionLocal` with `SessionFactory` **inside the diagnostic process**, before importing the API dependencies. No source fix was applied. Scheduling makes the exact failure count variable; these are measured runs, not a universal failure rate.

**Impact:** sidebar, home sections, details, covers and playback writes can all fail, depending on which requests overlap. This explains why a new page load can appear to repair things temporarily. Adding retries or a larger pool would not repair Session isolation.

### P0 — Recently Played returns the wrong required field [confirmed]

Sources: [playback_session.py:187](/home/pyro/apps/Verse-test/app/services/playback_session.py:187), [schemas.py:41](/home/pyro/apps/Verse-test/app/api/schemas.py:41), [routes/playlists.py:241](/home/pyro/apps/Verse-test/app/api/routes/playlists.py:241).

The service returns `song_count`; `PlaylistResponse` requires `songs_count`. An empty list validates, but a nonempty one raises `ResponseValidationError` after the route returns. The route's service-level `try/except` does not catch this later response-validation stage. Serial HTTP testing returned 500 and four `songs_count: Field required` errors for four items.

**Impact:** Recently Played fails independently. The frontend's `songs_count || song_count` fallback cannot help because no successful JSON response reaches it. This mismatch alone does not produce the sidebar's literal error message, which belongs to another request.

### P1 — Stale responses and missing recovery make failures persistent [confirmed]

Sources: [index.js:977](/home/pyro/apps/Verse-test/app/web/index.js:977), [index.js:1042](/home/pyro/apps/Verse-test/app/web/index.js:1042), [index.js:1203](/home/pyro/apps/Verse-test/app/web/index.js:1203), [index.js:639](/home/pyro/apps/Verse-test/app/web/index.js:639), [index.js:430](/home/pyro/apps/Verse-test/app/web/index.js:430).

The sidebar collapses HTTP errors into one generic exception, does not validate JSON shape, and catches network, JSON and DOM errors together. Its catch replaces only the desktop sidebar with static error text; it neither preserves useful data nor exposes retry/recovery. Mobile can retain older successful content. Returning Home refreshes the home sections, not this sidebar, so the error remains until another sidebar-load trigger such as refresh or save.

There are no request-generation guards, abort controllers or account/view identity guards in these loading paths. Delayed responses can replace newer state. The frontend probe executed the original functions with controlled promises and confirmed:

- An older 503 overwrites a newer successful sidebar response.
- Network rejection, invalid JSON and a 200 object instead of an array all produce the same static sidebar error.
- Selecting A then B can finish with A displayed if A resolves later.
- Returning Home while detail A is pending is undone by A's eventual response.
- Old search results overwrite newer results; the existing 100 ms debounce does not prevent response races.

No app-level request deadline exists here, so a stalled response can remain pending until browser/network behavior ends it. Continue Listening hides on error; the two Recent sections only log errors and can leave placeholders or stale content. These sections have independent requests and catches, while sharing the defective DB scope and underlying resource pressure.

### P1 — Metadata endpoints perform large N+1 reads including artwork [confirmed]

Sources: [playlist.py:543](/home/pyro/apps/Verse-test/app/services/playlist.py:543), [playback_session.py:202](/home/pyro/apps/Verse-test/app/services/playback_session.py:202), [playback_session.py:138](/home/pyro/apps/Verse-test/app/services/playback_session.py:138), [library.py:32](/home/pyro/apps/Verse-test/app/services/library.py:32), [models.py:284](/home/pyro/apps/Verse-test/app/database/models.py:284).

The list loop loads each playlist's memberships and Song objects, then runs three stats queries per playlist: ownership lookup, COUNT and MAX. Default Song loads include `cover_art`. List serialization subsequently discards many computed fields because the response schema only declares basic metadata.

Measured sequential service calls on the copied library, with a new Session per measurement:

| Operation | SQL statements | Artwork bytes materialized | First / second call |
| --- | ---: | ---: | ---: |
| All playlists, limit 50 | 610 | 50,157,375 | 306 / 242 ms |
| Recently Added, limit 6 | 105 | 9,415,079 | 43 / 42 ms |
| Recently Played, limit 4 | 47 | 6,031,177 | 23 / 20 ms |
| Continue Listening, limit 4 | 37 | 3,892,105 | 18 / 16 ms |
| Song page, 100 tracks | 2 | 12,725,222 | 96 ms, single sample |
| Detail, 15-track playlist | 20 | 2,246,963 | 9 ms, single sample |

These are SQL event counts, ORM-loaded artwork byte totals and wall-clock service times, **not JSON sizes, peak RSS, network latency or an OS-cold disk benchmark**. The second calls benefit from warm system caches but repeat all the listed queries and blob reads.

**Impact:** read latency, allocations, worker occupancy, and a larger window for concurrency problems. SQLite DELETE-mode contention and a 15-connection pool can amplify pressure, but a larger pool is not the first remedy. The contention test does not isolate journal mode as a necessary cause: lock errors disappeared in the fresh-session control even without WAL.

### P1 — Warm covers still traverse entire playlists [confirmed]

Sources: [playlist_artwork.py:83](/home/pyro/apps/Verse-test/app/services/playlist_artwork.py:83), [playlist_artwork.py:174](/home/pyro/apps/Verse-test/app/services/playlist_artwork.py:174), [routes/playlists.py:467](/home/pyro/apps/Verse-test/app/api/routes/playlists.py:467), [index.js:1228](/home/pyro/apps/Verse-test/app/web/index.js:1228).

The cache key is built after materializing every playlist song. A 25-track cover did **27 queries and loaded 2,751,264 artwork bytes on both cold and warm cache calls**. PIL work made the first call about 53 ms; the cached second call was about 11 ms but still did the DB work. Only four images are actually used to compose the output.

The dictionary has no size bound despite its cache-size comment. Responses have no explicit ETag/cache policy, and detail opening appends `?t=Date.now()`, forcing a different image URL on each open. Artist/source artwork changes are not part of the cache key. Several simultaneous cold calls can repeat the same work because no in-flight sharing exists.

**Impact:** additional backend load and image work; **a failed cover request alone does not trigger the sidebar error** because images are separate requests.

### P1 — Routine playback rebuilds DOM, including the hidden mobile queue [confirmed]

Sources: [index.js:492](/home/pyro/apps/Verse-test/app/web/index.js:492), [index.js:1631](/home/pyro/apps/Verse-test/app/web/index.js:1631), [index.js:1689](/home/pyro/apps/Verse-test/app/web/index.js:1689), [index.js:1726](/home/pyro/apps/Verse-test/app/web/index.js:1726), [index.js:1866](/home/pyro/apps/Verse-test/app/web/index.js:1866), [index.js:1333](/home/pyro/apps/Verse-test/app/web/index.js:1333).

Track changes replace the 100-row library table and both full remaining-queue lists. Like actions also replace the full home table. Play/pause replaces artwork elements even when the track did not change. Detail filtering sorts/copies and rebuilds every row on each input. Handlers are attached to recreated nodes, producing allocation churn. Setup runs once and old DOM nodes are discarded; **there is no evidence here of accumulating duplicate listeners on the same persistent nodes**.

Offscreen Chromium using the real HTML/CSS/JS, 434-song metadata fixtures, mocked successful fetches and 10 samples per operation measured the following synchronous mutation plus forced-layout costs:

| Operation | First sample | Subsequent sample range |
| --- | ---: | ---: |
| Rebuild 100 library rows | 49.0 ms | 44.3–47.4 ms |
| Rebuild a 99-song queue into both DOMs | 22.9 ms | 12.5–13.1 ms |
| Render a typical 25-track detail table | 17.4 ms | 2.1–2.4 ms |
| Track-change DOM work, 100-song queue | 65.2 ms | 59.3–62.5 ms |
| Rebuild full-library 433-song remaining queue twice | 98.0 ms | 70.3–72.9 ms |
| Render 434 detail rows, stress case | 38.3 ms | 38.1–40.1 ms |

The stress fixture grew from 4,161 to 18,896 DOM elements, with 866 queue rows and 866 queue `<img>` elements. These are element counts, **not 866 guaranteed distinct HTTP downloads**; browser caching/coalescing can reduce requests. None of these image elements use lazy loading or explicit async decoding. Raw, full-size embedded artwork is served even for tiny table thumbnails.

**Limits:** this is a software/offscreen browser, with external font fetching removed and image endpoints unavailable. Timings include a deliberate layout flush for measurement. They are not GPU frame-time, image-decoding or production INP measurements. The 25-track table is relatively cheap when warm; it should not be treated as equally problematic as full-library queues or routine track-change rebuilds.

### P2 — Layout/paint pressure and perceived delay [mixed confidence]

- **Confirmed mechanism, impact unprofiled:** `index.js:2031` writes sidebar widths for every mousemove without animation-frame coalescing, triggering flex/table relayout. It does not contain a repeated geometry read/write loop, so calling this proven layout thrashing would be inaccurate. The resizer itself animates width from 1px to 4px (`index.css:1814`).
- **Confirmed mechanism, impact unprofiled:** equalizer bars animate height (`index.css:2931`); mobile progress animates width (`:3421`). Use transform-based visual changes where equivalent.
- **Likely paint cost:** 25px sidebar backdrop blurs (`index.css:190`, `:999`), several overlay/player blurs, broad `transition: all`, and animated hover shadows (`:2360`) may cost frames on the user's GPU. Measure layer/paint traces before altering the appearance.
- **Perceived latency, confirmed code:** detail navigation waits for HTTP before changing view (`index.js:1205`), and playlist track playback waits on two serial metadata requests. Neither has immediate localized pending feedback. The existing 400 ms view fade (`index.css:512`) adds intentional visual duration, but shortening it will not eliminate 60 ms rendering tasks or backend waits.
- **Secondary pressure:** every track change asks for recommendations (`index.js:1818`). `recommendation.py:22` clears a vector index reference; `content.py:39` loads models/index per call. This is server work rather than synchronous browser work. Its deployment impact was not benchmarked here.
- **Secondary synchronous layout:** chat rendering replaces its history then reads `scrollHeight` (`index.js:2456`), forcing a layout flush; not evidence for ordinary home scrolling jitter.
- **Potential pool retention:** audio stream routes read a Song via the request-scoped DB dependency and return streaming responses (`routes/songs.py:59`). The installed FastAPI yield-dependency default is request scope, so cleanup can wait for streaming completion. Long or stalled streams may retain checkouts. This was not included in the load test; verify checkout lifetime before changing stream dependency scope.
- **Separate usability defect:** 75 user playlists exist but the sidebar asks for only the default first 50 with no pagination (`index.js:979`, `routes/playlists.py:244`). This explains missing older playlists, not intermittent HTTP failures.

## 3. Reproduction and verification

Temporary probes are available for this session:

```text
/tmp/verse-diagnosis-f7cWoO/backend_probe.py
/tmp/verse-diagnosis-f7cWoO/contracts_probe.py
/tmp/verse-diagnosis-f7cWoO/frontend_probe.js
/tmp/verse-diagnosis-f7cWoO/browser_probe.py
```

The backend probe uses `sqlite3.backup()` from a read-only source connection, valid cookie authentication against the copy, the actual FastAPI ASGI application and HTTPX transport. It records query counts, artwork materialization, statuses and Session overlap. Run default and `--fresh` in separate processes. The current fixture IDs and username are encoded intentionally; adapt them for another library. The fresh flag is a diagnostic control, not an implemented fix.

The frontend probe runs original function bodies in Node with controlled fetch promises. Resolve B before A, or return an old 503 after a newer 200. It tests behavior deterministically without claiming browser frame data. For manual deployment reproduction, use DevTools request interception/throttling, rapidly open two playlists, navigate Home while details are pending, and briefly fail the `/playlists` request. Restore normal responses and observe whether the sidebar recovers without refresh.

Existing relevant tests were run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_playlist_services.py tests/test_playlist_api_routes.py \
  tests/test_service_user_ownership.py tests/test_auth_sessions.py \
  tests/test_web_frontend_auth.py tests/test_web_frontend_seed.py
```

**Result: 23 passed in 7.73 s**, with datetime deprecation warnings. A separate selected services/auth/identity/frontend subset also passed. Existing tests mainly override the DB dependency with controlled fixtures and do not exercise the production Session lifecycle under concurrency; the passing suite does not disprove the new reproductions. The playlist API test is sequential and does not assert nonempty Recently Played validation.

Sandboxed asyncio worker wakeups and Chromium socket creation initially failed/hung, including a minimal `asyncio.to_thread()` check. The actual ASGI workload, browser probe and HTTP tests completed outside that restriction. No live server was restarted and no port, reverse proxy or user's browser was used. No production HAR, network interruption trace, GPU profile, true OS-cold benchmark, or streaming/pool-saturation measurement was collected.

## 4. Focused implementation plan

### A. Fix correctness first

1. Add regression cases reproducing Session overlap and nonempty Recently Played validation before editing behavior. Use file-backed temporary SQLite, real production dependencies and concurrent cookie-authenticated reads/progress writes; do not override away the scope defect.
2. Allocate a fresh SQLAlchemy Session for each `get_session()` scope from `SessionFactory`, including authentication resolution. Preserve clear commit/rollback/final close ownership. Merely adding `.remove()` to a potentially different finalizer thread is insufficient. Check desktop/CLI callers for compatibility. Keep `check_same_thread=False` for valid sequential cross-thread use without sharing a Session concurrently.
3. Normalize list/stat field names to `songs_count` across service and response schema, retaining separate documented names only where actually required. Test the API response after FastAPI validation, not just the service dictionary.
4. Measure the corrected lifecycle under current DELETE journal mode first. Then consider WAL and an explicit busy timeout for the supported local deployment if contention remains. Keep write transactions short and atomic; do not use bigger pools, longer timeouts, or request retries to conceal session misuse. Inspect streaming checkout lifetime and materialize necessary file metadata before returning a long-lived stream.

### B. Bound database and artwork work

1. Fetch playlist count/duration and playback COUNT/MAX through grouped SQL subqueries, joined to the user-filtered playlist page. Avoid joining raw membership and session rows together and accidentally multiplying counts. Preserve empty playlists, ordering, isolation and existing response fields. Lists should not materialize Song entities or artwork.
2. Load detail songs/memberships in bounded queries with explicit lightweight columns; return `cover_art IS NOT NULL` as a boolean without selecting the blob. Reuse the detail/song projection instead of fetching full details for ownership checks or fetching songs twice. Apply the same projection to the 100-song library page and metadata search.
3. Give covers a revision-aware, size-aware bounded cache; obtain only the first four ordered songs/artwork. A warm cache lookup should not enumerate the full playlist. Add ETag/conditional HTTP handling and deliberate cache policy; replace timestamp cache busting with a content revision. Maintain invalidation when membership/artwork changes. Keep visual composites unchanged. Avoid duplicate work for simultaneous identical cover requests.
4. Add measured thumbnail variants for table/queue sizes using existing PIL, preserving original artwork for large views. Use lazy images and async decode where suitable, and limit offscreen queue construction. Existing dependencies suffice.

### C. Make loading state and recovery explicit

1. Use one small request/state utility in existing JavaScript: coalesce identical in-flight reads; assign request generations keyed by account/resource; abort superseded safe reads and discard all stale completions including stale errors. Apply to playlist details, sidebar, home sections, pagination, search and recommendations. Keep independent home-section failure states.
2. Move to the selected detail view immediately with a stable, accessible skeleton and cancelable pending state. Preserve the latest valid sidebar/cards while refreshing. Show distinct empty, loading and error states with a working Retry action. Handle HTTP status, JSON shape/parse errors, timeout and offline conditions with useful messages and diagnostic context; aborts must not show errors. Account changes must invalidate caches and pending requests.
3. Restore unavailable resources on explicit retry and appropriate Home/reconnect/focus triggers, with bounded/coalesced requests. Optional limited backoff may help transient failures only after root causes are fixed; no retry loop for validation/auth errors. Avoid clearing useful content on every Home click.
4. Remove the duplicate Home refresh after delete, and invalidate/refetch only affected sections after save/delete. Check HTTP status for delete and progress updates. Progress requests need an awaited or `.catch()`-handled promise: the current synchronous `try` cannot catch asynchronous fetch rejection. Coalesce progress to the latest session/index/position so a slow older write cannot supersede newer progress.
5. Make sidebar pagination explicit so all user playlists are reachable; do not silently truncate at 50.

### D. Keep interactions within a frame budget

1. Patch the old/new active song rows and the changed heart/play controls rather than rebuilding the library. Update artwork only when song/artwork revision changes. Refresh playlist-detail active indicators too, preserving scroll, selection and focus.
2. Reconcile queue changes using stable song IDs/positions. Render a bounded visible slice or incrementally render long queues with access to the remainder. Populate the mobile queue when relevant rather than rebuilding both complete lists on desktop. Use delegated row handlers to avoid rebinding every row after updates.
3. Keep filtering local and cancellation-safe. Batch larger initial tables/search results into frame-sized work if profiling warrants it; typical 25-track detail rendering is not the first optimization target.
4. Coalesce resize writes to one `requestAnimationFrame` per frame, preserve existing min/max widths and resizing features, and stop scheduling on release/cancel. Avoid animating the divider's layout width. Replace equalizer height animation with transform scaling while maintaining appearance.
5. Profile paint/layers on target desktop/mobile hardware. Narrow `transition: all` to the properties actually animated. Preserve current visual design; change blur/shadow rendering only when a trace demonstrates cost. Treat fade timing and reduced-motion behavior separately from dropped-frame fixes.

### E. Add focused observability

Record request ID, path, status, elapsed time, query count, DB checkout/hold time and full server exception traceback, with privacy-conscious logs. Do not log session tokens. On the frontend retain request resource/generation, status, timing and parse/network error category. Collect real browser Performance traces and HARs around the two reported problems; backend wall-clock and JS execution are separate parts of latency.

## 5. Regression checks and proposed acceptance criteria

These are implementation targets, **not claims already achieved**. Establish the same reference machine/browser and fixture before comparing.

| Area | Required verification / target |
| --- | --- |
| Session reliability | At least 1,000 mixed metadata/cover/progress requests with up to 24 concurrent requests, plus normal five-request bootstrap waves: zero unexpected 5xx, session overlap, closed-session errors or cross-user results. Repeat with separate users and new browser sessions. |
| Response contracts | Nonempty/empty Recently Played, Continue Listening, list and details all validate through the actual HTTP API; counts, durations and ordering match reference data. |
| Recovery/races | With 1–3 s delays, one injected 503, malformed JSON, offline/reconnect and rapid A→B→Home navigation: latest intent always wins; old errors never remove newer valid data; Retry restores state without page refresh; no request storms or unhandled promise rejections. |
| DB work | Playlist metadata page ≤4 SQL statements independent of playlist/song count and zero Song artwork bytes materialized. Detail/library/search queries bounded rather than per-row. Warm cover ≤2 small queries and no full-playlist blob reads; cold cover reads at most four artwork blobs. |
| API latency | On this 434-song/75-playlist fixture after warm-up, target metadata p95 <150 ms and app/cache-cold p95 <300 ms on the agreed reference machine; separately record transport and image timing. Re-baseline these budgets on deployment hardware. |
| Interaction | Cached navigation shows immediate feedback within 100 ms; p95 interaction latency <200 ms on target devices; routine like/play/track-change DOM work fits ≤16 ms at 60 Hz, with no >50 ms interaction long tasks. Larger initial renders are chunked rather than blocking. |
| Scrolling/resizing | Target-device traces under concurrent loading show p95 frame interval ≤20 ms at 60 Hz and no >50 ms main-thread stall caused by queue/table work. Resize applies at most one width update per animation frame. Verify actual GPU behavior; offscreen timings are insufficient. |
| Resource use | One artwork element update per actual track/art revision, bounded queue DOM, no hidden full queue copy on desktop, stable listener counts, conditional image requests after warm loads, bounded cover-cache memory. |
| Features/appearance | Screenshot/layout comparisons at desktop/mobile widths; keyboard search/navigation, focus, likes, playback queue order, shuffle/repeat/resume, cover composites, playlist CRUD and all older playlists remain usable. Preserve existing styling and no framework migration/new runtime dependency. |

Before closing the investigation on the user's deployment, collect: a failed sidebar request's HTTP status/body and request ID, correlated backend traceback, worker/proxy configuration, DB filesystem/journal/pool settings, and a desktop/mobile browser Performance recording covering Home → playlist → play → resize/scroll. The existing logs cannot identify the original user's exact failed request or quantify GPU paint cost.
