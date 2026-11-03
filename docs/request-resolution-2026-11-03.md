# Recording resolution fix: Fly Away — Darpan

Implemented and activated on Verse-test, `feat/external-song-requests`, 2026-11-03
UTC. No migration, new dependency, backfill, permission redesign or production
service change was needed. Existing unrelated working changes were retained.

## Diagnosis from the actual failed request

The operator confirmed the screenshot refers to **Fly Away — Darpan**:

- Existing job: `1edde8a9-ea19-49f1-9f53-9a6a55b3bc24`
- MusicBrainz recording: `2cfe7d3c-76e3-49ad-8585-daecbb314819`
- Selected release: `0851eb7e-1c24-44ce-9368-9180849c8b4d` (**Fly away**)
- Duration: **333.266 seconds**; no recording disambiguation.

The resolver **already fetched full MusicBrainz details**, not just search hits:
`inc=artist-credits+releases+isrcs+url-rels`. The live full response contained
`isrcs: []` and `relations: []`. Identifiers genuinely were absent for this
recording; the defect was stopping there rather than discovering candidates by
metadata. A precise live MusicBrainz search,
`recording:"Fly Away" AND artist:"Darpan"`, returned exactly this one recording.
Broad top-ten queries for the title/artist did not necessarily include it; no
different title-only result was silently treated as the selected recording.

The confusing status had two code-supported mechanisms: retry claims retained
the previous attempt's error while setting `state=resolving`, and old external
search responses unconditionally replaced newer polled job state. Both are fixed;
the exact browser timing of the original screenshot was not captured.

## Implementation

- [`catalogue.py`](../app/discovery/catalogue.py) retains full recording lookups,
  preserves individual artist credits, and keeps recording-only identities stable
  when a full lookup unexpectedly includes releases.
- [`acquisition.py`](../app/discovery/acquisition.py) retains identifier priority
  and adds bounded metadata discovery, without passing MBIDs to spotDL or taking
  the first fuzzy title hit. Direct URL relationships, exact ISRCs, ISRC-query plus
  metadata, metadata matches and user selections have distinct provenance.
- [`spotdl_bridge.py`](../app/discovery/spotdl_bridge.py) uses supported installed
  Python APIs, with an argument-array subprocess and a 90-second timeout. Installed
  **spotDL 4.6.0** exposes `SpotifyClient.init(..., use_official_api=False)` and its
  actual **SpotipyFree** backend supports `search(query, type='track', ...)`.
  Real calls were inspected. A spotDL config exists now, with `youtube-music` as
  audio provider and official API disabled; no custom Verse Spotify credentials,
  auth token or cookie file is configured. Text discovery still depends on
  Spotify metadata availability, but not paid discovery credentials here.
- [`resolution.py`](../app/discovery/resolution.py) ranks at most 30 discovered
  tracks. Scoring weights are title 35, artist credits 30, duration 20, album 10,
  version 5. Auto-accept requires an exact normalized title (including compatible
  disambiguation-qualified titles), credits and album, represented
  disambiguation, close known duration, score >=95, and margin >=8. Known
  artist/live/remix/remaster/etc. conflicts are excluded. Weaker matches require
  explicit selection; a score of 100 is **not 100% identity certainty**.
- [`jobs.py`](../app/discovery/jobs.py) persists up to five choices in the existing
  JSON column; no new table is needed. Choice submission validates the saved
  candidate, uses a state/snapshot-guarded update, and repeats idempotently on the
  same job. No client-supplied replacement metadata/URL is accepted.
- An empty identifier search cannot get stuck repeatedly consuming its rate slot
  before metadata fallback: the background resolver waits once for the short local
  slot instead of restarting the whole job. An ISRC search whose returned track
  lacks ISRC data must meet metadata-confidence/margin rules, not be treated as
  verified identity. Credit comparison respects individual names rather than
  join punctuation/order; explicit live-version disambiguation remains distinct
  from an original or remix.
- [`worker.py`](../app/discovery/worker.py) clears old errors when claiming work,
  parks ambiguity in `awaiting_choice`, fails no-match cases immediately, and
  preserves choices across restart. Metadata mappings are kept on the job rather
  than asserted as exact MusicBrainz aliases. Canonical sources and content hashes
  still prevent duplicate downloads/index entries.
- [`index.js`](../app/web/index.js) renders a touch-friendly inline Choose version
  picker, useful Retry/Search again actions and terminal labels. UTC update-time
  guards cover search, polling and mutation results. Failed/awaiting jobs stop
  active polling. Local rows, unrelated request rows, library nodes and audio stay
  intact. New assets have a cache-version bump.

Provider references: [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API)
and [spotDL usage](https://spotdl.github.io/spotify-downloader/usage/). In particular,
the pinned `YouTubeURL|SpotifyURL` acquisition form is documented; no invented CLI
flag bypasses Spotify or the recording-matching safeguards.

## Live result, separated by stage

The exact existing job was retried through the normal signed-in request API after
restarting only `verse-test.service` and the single user service
`verse-test-request-worker.service`. No different recording/job was substituted.

| Stage | Result |
| --- | --- |
| Full MusicBrainz lookup | Success; no ISRCs or URL relationships |
| Candidate discovery/resolution | Success: Spotify `2mVlgKKpCJzQlPicYV2zzZ`, Darpan / Fly Away / Fly Away / 333.266 seconds |
| Resolution provenance | `method=metadata`, `score=100`, `verified_identity=false`, `user_selected=false` |
| Audio-source lookup | Unique song/album match: YouTube Music `Vs7e4fSEHKY`, duration 334 seconds |
| Download | Success, pinned source via spotDL; actual MP3 duration 333.312 seconds, 48 kHz |
| Single-file indexing | Success: **song 436**, Ready at **04:51:12 UTC**, first corrected attempt |
| Playback verification | HTTP **206**, `audio/mpeg`, requested **4096 bytes**; full ffmpeg decode passed |
| Repeated request | Same Ready job/song; no additional MP3 file or song row |

Final file:
`/home/pyro/Music/Requests/2mVlgKKpCJzQlPicYV2zzZ.mp3`.
The actual source-comment ID was verified against the pinned audio source.
No ISRC was fabricated, and no approximate MusicBrainz alias was inserted into
`song_sources`. This is MP3, not lossless or acoustic-fingerprint verification.

The active-safe pre-rollout SQLite backup is:
`/home/pyro/apps/Verse-test/data/backups/request-resolution-20261103T044842Z-2/music_rec.db`.
SQLite online backup and integrity checks passed. It predates this retry and
preserves the original failed request for inspection.

At the post-Fly-Away audit, all **435 original song rows**, **93 playlists**, and
**988 membership rows/positions** matched that backup exactly; only song 436 was
new. Another existing request subsequently reached Ready through normal live
client use (song 437); it was not submitted by this verification. Concurrent user
activity is preserved, not reverted to force a fixed final count.
The final audit observed 438 total songs, with the same 435 pre-rollout song rows
and all 93 playlists/988 memberships still unchanged. Fly Away remained Ready as
song 436 after the final API/worker restart, and its stream/duplicate check passed
again without acquisition.

## Regression and UI verification

**154 tests passed**, 996 framework/datetime deprecation warnings, **38.82 seconds**.
The full command is in [the feature documentation](external-song-requests.md).
This includes **55 discovery checks**. All automated external downloads
are mocked; the actual live result above is separate evidence.

Added coverage includes identifiers appearing only after full lookup; multiple
ISRCs; one strong metadata candidate; wrong artists, live/remix/remastered versions
and large duration differences; ambiguous versions surviving restart; invalid,
repeated and five concurrent choices; canonical reuse without false exact aliases;
terminal no-match and retry; old error cleanup; terminal frontend labels; stale
status rejection; choice submission failure/recovery; and unchanged playback/DOM.

Synthetic-service offscreen Chromium exercised version selection at **1440×900**
and **390×844**. Separate **real API/HTML/JS**, read-only probes at those two sizes
verified song 436's Ready Play/Add actions and picker, plus an existing failed
request's terminal label/error/Retry rather than Resolving. The account saw 76
playlist choices; none were submitted. Probes block browser mutations/external
networking, create temporary sessions and revoke them on exit; they neither start
playback nor alter existing device sessions.

Both Verse-test services are enabled/active, exactly one acquisition worker was
observed, and it had no automatic restart failures. Existing failed unrelated
jobs were not bulk retried. Original songs/playlists and service configuration
were retained.

## Remaining limits

Metadata matching is deliberately conservative, not proof of mastering identity.
Unknown or ambiguous versions can still need a choice; unavailable providers or
audio sources can still fail with actionable terminal errors. SpotipyFree/source
availability is an external dependency, not guaranteed future access.

No physical iPhone/Safari test was available. Reload Verse once to load the new
frontend assets, then test failure/Retry, Choose version, navigation/reopening,
and selecting/adding/playing Fly Away while another track is playing. Offscreen
Chromium does not verify iOS background playback or Lock Screen presentation.
