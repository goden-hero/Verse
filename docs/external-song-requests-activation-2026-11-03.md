# Verse-test external requests: activation and live verification

Date: 2026-11-03 UTC. Checkout: `/home/pyro/apps/Verse-test`, branch
`feat/external-song-requests`. Existing unrelated working changes were retained;
activation did not change production services, tunnels, existing playlists or
original songs. Separate concurrent live-client edits are noted below.

## Configuration and persistent services

The API and worker both run as `pyro`, with the Verse-test working directory and
its `.venv`. Their database resolves to
`/home/pyro/apps/Verse-test/data/music_rec.db`. The existing 434 indexed files were
verified to exist below `/home/pyro/Music`; this is now `VERSE_MUSIC_DIR`.

`.env` contains `VERSE_CATALOGUE=musicbrainz` and the real contact supplied by the
operator in `VERSE_CATALOGUE_CONTACT`. The contact is intentionally not reproduced
here. Existing configuration was preserved. No custom Spotify catalogue secrets
or spotDL config file were present or required for this successful request.

- `verse-test.service`: existing **system** API service, enabled and active;
  restarted with the shared configuration, listening on port 8001.
- `verse-test-request-worker.service`: **user** service, installed at
  `/home/pyro/.config/systemd/user/verse-test-request-worker.service`, enabled and
  active. The installed unit matches
  [the checked-in activation unit](../deploy/verse-test-request-worker.service).
- User lingering is enabled, so logout does not stop the worker and the user
  manager can start it at boot. No actual host reboot was performed.
- Exactly one acquisition worker was observed, holding the database-specific
  advisory lock. No identity backfill runs during ordinary service startup.
- Worker PATH explicitly includes the Verse venv and `/usr/local/bin:/usr/bin:/bin`.
  The old API service's venv-only PATH did not expose system audio tools; the
  acquisition service must not copy that restriction.

Installed spotDL 4.6.0, yt-dlp 2026.10.26, ffmpeg, ffprobe, mutagen, and SQLAlchemy
were checked in this account/environment; `pip check` passed. No dependency
installation was needed. systemd unit verification passed.

Operator commands for this installation:

```bash
systemctl --user status verse-test-request-worker.service
journalctl --user -u verse-test-request-worker.service -f
systemctl --user restart verse-test-request-worker.service
systemctl status verse-test.service
sudo -n /usr/bin/systemctl restart verse-test
```

Review/redact logs before sharing them. The contact and credential values are not
part of API responses or this report.

## Backup, migration and one-time backfill

Before migration, SQLite's online backup API copied the active database to:

`/home/pyro/apps/Verse-test/data/backups/requests-activation-20261103T031831Z-791681/music_rec.db`

The backup file has mode `0600`, its directory `0700`; integrity checks returned
`ok` both before and after activation. This was an active-safe SQLite backup, not
a potentially inconsistent copy of only the main file while writes continued.

The reviewed additive migration advanced `5f2b3c4d6e7f` to `6a7b8c9d0e1f`, adding
only `song_requests`, `song_sources`, `discovery_cache`, and `catalogue_budgets`.
It was explicitly applied to the absolute Verse-test database URL.

With no pending jobs and no other worker running, the one-time command was:

```bash
PATH=/home/pyro/apps/Verse-test/.venv/bin:/usr/local/bin:/usr/bin:/bin \
  .venv/bin/python -m app.main request-worker --once --backfill-identities
```

It read source tags from 434 existing files and inserted 433 unique identities.
One pre-existing duplicate Spotify source tag belongs to songs 144 and 413; its
unique mapping retains song 144. Neither file nor row was merged or deleted.
Do not repeat the backfill at every service restart.

Comparison against the backup after acquisition, before concurrent live-client
playlist edits:

| Data | Before | After | Verification |
| --- | ---: | ---: | --- |
| Existing song rows | 434 | 434 unchanged | All original columns compared, including artwork |
| Total songs | 434 | 435 | Exactly one newly indexed song |
| Playlists | 95 | 95 | Every row unchanged |
| Playlist memberships | 987 | 987 | Every row and position unchanged |
| Request jobs | 0 | 1 | Same job reused on retry and duplicate submission |
| Source identities | 0 | 435 | 433 legacy + MusicBrainz/Spotify aliases for the new song |

Playlist-row SHA-256:
`cef8cd34c2b34fe42230d1bd9761c6db93497e8ba8ba0968ecd47dcfc379ba20`.
Membership-row SHA-256:
`fd5243e35f7a9e8601420fab9c7d460b4d55bbcf0bedde951e1ebcaa34f9d7c6`.

During the final audit, the counts changed to **93 playlists / 988 memberships**.
The API journal confirms separate remote-client writes at 04:20:21 and 04:20:26
UTC deleting playlists 106 and 105, and at 04:20:46 adding song 209 to playlist
104. These were not local verification requests; the browser probe blocks all
HTTP mutations and never submits its picker. The deleted playlists were empty;
no previous memberships were removed. These concurrent edits were preserved,
not restored from backup. The row hashes above describe the verified earlier
checkpoint, not the database after those legitimate live writes.

## Actual provider request and acquisition

A real MusicBrainz search was made through `/api/v1/search/external`. The selected
missing recording was **Lianne La Havas — Weird Fishes**, from **Lianne La Havas**:

- MusicBrainz recording: `cc0ba5c0-0e52-4fca-8240-5f8eccb341d8`
- Selected release: `d0f570d6-bee8-4be2-9929-0a28327754d5`
- ISRC: `GBAHT2000178`
- Verified canonical Spotify ID: `5ygk8Hkp4WCCk7GXWEUP9V`
- Persistent job: `d99cbb10-ee7d-41ec-890a-89e43cf8788c`
- Result: **ready**, local song **435**, no remaining job error.

The normal signed-in API accepted the job promptly with HTTP 202. Its worker
resolved the ISRC and checked title/artist/album/duration against the unique
Spotify candidate. No MusicBrainz ID was handed directly to spotDL.

Live testing exposed two defects that mocked downloads had missed:

1. spotDL treats a literal `track.mp3` output path as a **directory**, appends an
   artist/title filename, and strips leading dots from absolute path components.
   It had downloaded outside the intended hidden staging path and subsequent
   attempts silently skipped the existing duplicate. Fixed with relative
   `track.{output-ext}` in the validated staging cwd, plus useful redacted
   diagnostics when spotDL exits zero but produces no expected file.
2. spotDL's fuzzy source ranking chose a **Glastonbury 2022 live performance**
   despite correct studio Spotify tags. The source URL's real metadata exposed
   this before indexing. The unindexed file was quarantined, not accepted as the
   requested studio recording. New acquisitions require a unique song/album
   source match and pin that URL; the downloaded source comment is also checked.

The rejected file is retained only for diagnostics at
`/home/pyro/Music/.verse-requests/5ygk8Hkp4WCCk7GXWEUP9V/rejected-live-glastonbury-8m-dNdXt1KA.mp3`.
It was task-created, never indexed, and moved without changing its bytes. The
scanner excludes this hidden directory. No original library audio was removed.

The verified studio audio source was the exact album-listed YouTube Music song
`uegfE22dmSY`: public source metadata independently reported title **Weird Fishes**,
artist **Lianne La Havas**, album **Lianne La Havas**, duration **355 seconds**.
The same persistent request was retried through the API after the corrections;
it was not replaced with another recording or another job.

The corrected attempt finished at **04:09:08 UTC**. Validation and single-file
indexing produced:

`/home/pyro/Music/Requests/5ygk8Hkp4WCCk7GXWEUP9V.mp3`

Actual duration **354.576 seconds**, MP3, 48,000 Hz. Essential indexing only ran
for this file, not the full library. No expensive optional enrichment was needed
to reach Ready. This is **not lossless audio**, and metadata/source checks are
not acoustic fingerprint verification or proof of bit-identical mastering.

## Verification results

- Real authenticated `GET /songs/435` returns the expected studio metadata.
- A range request to its actual stream returned **206**, `audio/mpeg`, and the
  requested **4,096 bytes**. Full ffmpeg decoding completed with no errors.
- Normal local search now finds song 435.
- Authenticated artwork returned **200**, `image/jpeg`; actual image dimensions
  are **640×640** and image validation passed.
- Reposting the exact selected identity returned the **same Ready job and song**.
  Song count, request count and the set of MP3 files did not increase.
- These API/duplicate checks passed again after restarting the API. Ready state
  survives API restart and browser reload.
- A read-only actual-UI offscreen Chromium probe passed at **1440×900** and
  **390×844**. It used the real HTML/JS/API, saw the Ready song's Play/Add actions,
  clicked Add, and confirmed song 435 opens the existing picker with all **78
  playlists visible to the existing signed-in account**. It never submitted a
  playlist change. Browser HTTP mutations and external network requests were
  blocked. The global count was 95 at the preservation checkpoint; the later
  remote-client edits described above reduced it to 93.
- **135 relevant automated tests passed** (42.74 seconds), with 923 existing
  framework/datetime deprecation warnings. Tests use temporary databases and
  mocked acquisition, except the separate live checks above. The suite/command is
  listed in [the feature documentation](external-song-requests.md).
- New regressions exercise the installed spotDL formatter, fixed argument/output
  handling, strict source selection, live-version rejection, quarantining
  unverified staging files, verified-file reuse without network/download, and
  rejecting a different source carrying otherwise matching Spotify tags.

The operator probes are
[`verify_live_song_requests.py`](../scripts/verify_live_song_requests.py) and
[`verify_live_song_requests_browser.py`](../scripts/verify_live_song_requests_browser.py).
They use temporary, short-lived sessions for the existing account and revoke
them on exit; they do not alter passwords or sign out existing devices. Browser
probes open but never submit the playlist picker.

## Remaining checks and provider limits

The completed live request establishes that this host/account can resolve,
acquire, index and serve this exact recording. It does not establish universal
MusicBrainz mappings, availability of every recording, official Spotify developer
API eligibility, or future downloader/source availability. Ambiguous/unmatched
releases intentionally fail; they must not fall back to a different recording.
Use sources you are authorized to obtain and observe provider terms.

No physical iPhone or public-network audio playback was available here. Check
**Safari and the Home Screen app separately**:

1. Search and confirm the local song, artwork and Play/Add actions appear.
2. Play song 435; verify audio output and normal playlist/queue behavior.
3. While another track plays, search/request a recording; ensure playback is not
   interrupted and request status survives closing/reopening the app.
4. Exercise failure/Retry and a pending request while backgrounded; server work
   should continue even though iOS may suspend the page.
5. Check Lock Screen metadata/artwork and supported play/pause/skip controls.
   Dynamic Island layout and availability remain controlled by iOS.

Server streaming/decoding and offscreen Chromium UI checks do not verify physical
iPhone playback, Safari background behavior or system-media presentation.
