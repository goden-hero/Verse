# Manual playlists

## Using the feature

1. Choose **Create playlist** beside Playlists, in the mobile library drawer,
   or beside Recently Added. The existing Create Playlist page also has a manual
   option; the recommendation generator is unchanged.
2. Enter a name and optional description. Empty playlists open normally with an
   **Add songs** action. Playback buttons are disabled while the playlist is empty.
3. Use **Select library songs** beside the library filters, or **Add songs** in an
   open playlist, for bulk selection. This is separate from the main MusicBrainz
   catalogue search. Search by title, artist, or album. The bulk tool queries the entire database, not the
   current 100-song library page. Click a row or checkbox to select; use the
   separate **Play** button to listen without losing selections.
4. Selection persists across queries and closing/reopening search. The selection
   count and **Clear selection** remain available. Arrow keys highlight results;
   Enter selects/deselects. Keyboard navigation and selection patch existing rows.
5. **Add to playlist** opens a name-filterable destination picker. It loads all
   playlist metadata pages. **Create new playlist** creates and populates a playlist
   in one transaction. Add songs from an open playlist preselects that destination.
6. On success, the notice reports added/skipped songs, submitted selections clear,
   sidebar counts update immediately, and affected metadata/details revalidate.
   A background detail refresh preserves its search/sort controls. Failures retain
   selections and form values; retry without refreshing the page.

## Append semantics

The primary search is now a MusicBrainz-only catalogue. Opening a recording reveals
its Play/Download/Add actions; missing-song additions retain a destination and
append after indexing. That flow is separate from this full-library bulk tool;
see the [search redesign report](musicbrainz-search-redesign-2026-11-03.md).

`POST /api/v1/playlists/{playlist_id}/songs` accepts a nonempty `song_ids` array
of positive integers. New songs append in first-selection/request order after the
highest existing position. Existing memberships and their positions are untouched.
Already-present songs and repeated IDs in the request are skipped.

Response fields: `playlist_id`, `added_count`, `skipped_count`, `songs_count`.
`added_count + skipped_count` equals the number of submitted ID occurrences;
`songs_count` is the final number of unique playlist memberships. A repeat of an
already committed append adds zero songs, including after a lost response.

The append service's first SQL statement locks the destination using a no-op
UPDATE, before reading memberships. Concurrent SQLite appenders serialize their
position allocation and duplicate checks; each batch keeps its internal order.
All IDs are validated before insertions. Missing playlists return 404; invalid
or missing songs return 422 without a partial write. Failures roll back. Successful
additions update the timestamp and invalidate the cover cache after commit; a
duplicate-only no-op retains the timestamp. Existing membership primary keys
provide an additional uniqueness constraint. No migration or dependency is added.

The misleadingly named legacy `add_songs_to_playlist` **replaces** memberships.
It remains in use for initial generated-playlist persistence and explicit reorder/
replacement editing. The new manual append endpoint never uses it. Creating an
empty/manual playlist extends the existing create route with an optional
description and default empty `song_ids`, preserving previous callers.

Searching, selecting, and updating playlists do not replace or restart the
persistent audio element, rebuild the library table, or replace the active queue.
The existing owner filter and authentication behavior are unchanged. No live
data or deployment was modified during development.

## Regression checks

The relevant combined suite passed **77 tests** (including 21 manual-playlist
tests). It covers creation/blank names, descriptions, empty destinations, single/
multiple additions, existing ordering and gaps, duplicate counts/repeated requests,
invalid IDs, rollback/retry, concurrent identical/disjoint batches, and full-library
title/artist/album searches beyond the first page. Temporary file-backed SQLite
databases retain the production request and cookie dependencies.

```bash
.venv/bin/python -m pytest -q \
  tests/test_manual_playlists.py tests/test_playlist_services.py \
  tests/test_playlist_api_routes.py tests/test_service_user_ownership.py \
  tests/test_auth_sessions.py tests/test_web_api.py tests/test_api.py \
  tests/test_search.py tests/test_web_loading.py tests/test_web_frontend_auth.py \
  tests/test_web_frontend_seed.py tests/test_media_session.py \
  tests/test_playlist_read_performance.py
```

`tests/browser_manual_playlist_probe.py` exercises the real HTML/CSS/JavaScript in
offscreen Chromium at **1440×900 and 390×844**, with 500 synthetic songs, mocked
transport/audio, and external requests blocked. It checks the complete create/
select/pick/append flows, retained selections, explicit playback, keyboard behavior,
viewport/touch-target sizes, duplicate submission suppression, HTTP/network/invalid
JSON/unexpected-shape failures and retry, stale search responses during debounce,
sidebar/detail updates, and preservation of unrelated library/audio nodes.

These checks do not verify physical iPhone Safari/Home Screen keyboard, VoiceOver,
or actual background audio. On the device, smoke-test creating from the library
drawer, entering a description with the keyboard open, selecting across searches,
filtering/scrolling the picker, creating from it, retrying after a temporary failure,
and confirming music keeps playing throughout.
