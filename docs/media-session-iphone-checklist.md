# Web Now Playing integration — 2026-11-01

## Implementation and scope

Verse is a vanilla-JavaScript SPA served by FastAPI. Its one `#main-audio-element`
already survives navigation. Library, search, playlists, assistant previews,
recommendations, queue, next/previous, and automatic advancement converge on
`playSong` in `app/web/index.js`. The integration lives there and in the existing
audio event initialization; it does not create another player, change the queue
order, add a dependency, or change the interface.

- New metadata is published synchronously on song selection, before awaiting
  `audio.play()`. Partial song payloads can hydrate album/artwork tags through the
  existing single-song metadata endpoint. Cancellation plus a playback-generation
  check prevents late lookups from restoring an older track's tags. Missing tags
  start empty/with current-track defaults, never the previous song's values.
- Play/pause/previous/next and seek handlers call the same playback helpers as
  Verse's controls. Previous retains the existing restart-after-three-seconds
  behavior; the end of the queue remains the end of the queue. Seek offsets
  default to ten seconds and clamp to the actual finite audio duration. Optional
  `fastSeek` falls back to setting `currentTime`.
- `play`, `playing`, `pause`, `ended`, and `error` events update playing state and
  controls from the audio element. All `play()` calls now share rejection handling.
  A rejected start leaves playback state accurate and allows a later user-initiated
  play; an obsolete rejection cannot update a newer track. Successful logout clears
  metadata, position, and playback state, and invalidates pending metadata work.
- Position state is cleared on a source change and is not published until
  `loadedmetadata`. Finite positive duration/rate and clamped position are required.
  Routine `timeupdate` publications are capped at one per second; explicit seek,
  rate, duration, and playback changes can update immediately. No polling timer
  is needed for Now Playing.
- Media Session, MediaMetadata, individual actions, position state, and fast seek
  are independently guarded. Unsupported actions/methods do not stop playback.
  Audio event initialization is idempotent.

## Artwork and cookies

Metadata artwork URLs are absolute HTTP(S) URLs on the current origin; no bearer
tokens, public proxy, cross-origin service, or blob URL is introduced. The original
cover's dimensions and type are omitted because they vary. The default cover is
the existing Verse cover design rendered as a real **512×512 PNG**, so only that
descriptor declares dimensions and MIME type.

`GET /api/v1/songs/{id}/artwork?fallback=true` validates decoding, preserves JPEG
and PNG bytes, converts other valid Pillow-readable formats to PNG, and supplies
the default cover for absent/corrupt images. A bounded 32-entry content-keyed cache
avoids repeated decoding; changing image bytes invalidates its result naturally.
`GET /api/v1/artwork/default` serves the default PNG. Ordinary artwork requests
retain missing-image 404 behavior, but now report their actual image MIME type
instead of always claiming JPEG. Stored covers and playlist data are not rewritten.
Image responses retain private caching and ETag revalidation.

The Media Session artwork fetch algorithm includes credentials. These same-origin
URLs use Verse's existing session cookie and middleware; no access-control redesign
was made. Automated HTTP tests verify image access with a valid cookie, not that
every iOS build's system artwork fetcher forwards it correctly. That last point
requires the device checks below. [Media Session specification](https://www.w3.org/TR/mediasession/)

## Verified automatically

The focused and relevant existing suite passed **37 tests**:

```bash
.venv/bin/python -m pytest -q \
  tests/test_media_session.py tests/test_api.py tests/test_web_api.py \
  tests/test_playlist_api_routes.py tests/test_auth_sessions.py \
  tests/test_web_loading.py tests/test_web_frontend_auth.py \
  tests/test_web_frontend_seed.py tests/test_playlist_read_performance.py
```

The whole-application Node harness covers metadata replacement, correct absolute
artwork descriptors, missing-cover defaults, partial tags, cancellation/stale
lookups, lookup HTTP/network/JSON/shape failures, rejected and obsolete play
promises, audio-event state, valid/clamped/throttled position, all registered
actions, unsupported API combinations, playlist start/resume, queue advancement,
looping, duplicate initialization, logout, and one persistent audio element.
Existing loop tests run through pytest as well.

The HTTP test uses a temporary file-backed SQLite database, the production session
dependencies and cookie middleware, and real decodable JPEG, PNG, BMP, absent,
and corrupt cover fixtures. It checks MIME types, dimensions, successful decoding,
conditional GETs, changed cover bytes, ordinary missing-cover behavior, and that
the cookie remains valid. No live database or deployment is written.

The existing offscreen Chromium UI probe also passed its node-preservation,
artwork reuse, queue pagination, resize, loading-error/retry, and navigation-race
checks with the 434-song read-only metadata fixture and mocked transport. This is
not a Safari, real-device smoothness, background-audio, or system-UI test.

## Physical iPhone checklist — not yet verified

Record the iPhone model, iOS version, Verse URL, audio output (speaker/Bluetooth),
and test results. Use the normal served Verse URL, preferably HTTPS, not a local
HTML file. Prepare three tracks with visibly different titles/albums and covers,
plus a track without artwork, in a known queue. Begin with an explicit tap to play.
Test both launch modes independently; sign in in each if prompted, and stop other
music apps/tabs so another media session is not being mistaken for Verse.

Run the complete checklist **once in a Safari tab**, then **again in the app opened
from Add to Home Screen**:

- [ ] Play a covered track from the library. Open Control Center and lock the
  phone. Verify the current title, artist, and artwork; check album where iOS
  chooses to display it. Check that play/pause status agrees with audible playback.
- [ ] Pause/resume from the Lock Screen and Control Center. Repeat after a longer
  pause. Confirm Verse's own controls agree when returning to the app.
- [ ] Use next/previous wherever exposed. Confirm queue order; previous after more
  than three seconds restarts the current track, and another early press goes
  back. Verify queue boundaries and the existing repeat behavior.
- [ ] Test seek/scrubbing or skip-forward/backward controls **if iOS exposes them**.
  Confirm elapsed time, audible position, and Verse's slider agree. Check near
  zero/end; paused seeking should remain paused. Record unavailable controls as
  not exposed, not as a passing implementation test.
- [ ] Background Verse, then manually change tracks using system controls. Verify
  title/artist/cover all change together; no previous album/cover remains.
- [ ] Let a track end naturally while locked/backgrounded. Verify the next queued
  song begins and updates metadata. Check the final track and repeat mode too.
- [ ] Switch to the artwork-less track while playing, both manually and by queue
  advancement. Verify the Verse fallback replaces the previous cover. Switch back
  to a covered track and verify its real cover returns.
- [ ] Start playback from playlist start/resume, search, recommendations, assistant
  preview, and the queue. Verify the same metadata behavior, including album tags
  for payloads that initially contain only a title/artist. Navigate Home/Library/
  playlists while playing; sound must not restart and no second player appears.
- [ ] On a Dynamic Island model, leave Verse in the background and observe any
  compact presentation, then touch and hold to inspect available expanded
  playback controls. Record which title/artwork/controls iOS actually presents.
- [ ] Briefly interrupt the network, attempt a new track, restore connectivity,
  and explicitly play again. Confirm no false playing state or stale metadata.
  Also check an audio interruption (e.g. another app taking audio focus) and
  resuming Verse. Log out and confirm Verse stops and its metadata clears.

If artwork fails, use Safari's remote Web Inspector and server access logs to
check the exact published absolute URL, status (200/304), Content-Type, image
decoding, `verse_session` handling, redirects, and any reverse-proxy behavior.
Compare `/artwork/default` and the current song's `artwork?fallback=true`. Never
paste session tokens into bug reports. For background advancement failures,
record whether `ended`, the next stream request, and a rejected `play()` occurred;
distinguish a suspended/killed page or expired login from a queue regression.

## iOS-controlled limits

Safari uses Media Session information for Now Playing, including the Lock Screen
and Control Center. [Apple's Safari media playback explanation](https://developer.apple.com/videos/play/wwdc2021/10189/)

Verse supplies metadata and supported handlers, not the system's layout. iOS
chooses which controls/fields are exposed and when they appear. Publishing an
album or seek handler does not require iOS to show that field/control. Dynamic
Island availability depends on the phone and system presentation; compact and
expanded layouts need not show all metadata. This is browser Now Playing, **not**
a native ActivityKit Live Activity or a promise of a custom Dynamic Island UI.
Apple documents the system-managed compact/expanded interaction on supported
models. [Apple's Dynamic Island guide](https://support.apple.com/en-gb/guide/iphone/iph28f50d10d/ios)

Media Session does not grant background execution, bypass autoplay policy, keep a
force-quit/suspended page alive, enable offline streaming, or override another
app's audio focus. The precise background and system-UI results remain unverified
until the checklist is run on the actual iPhone in both launch modes.
