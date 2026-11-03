"""Bounded spotDL adapter with verified recording resolution and fixed output paths."""
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from app.indexing.single_file import verify_audio_file, spotify_id_from_file, audio_source_url_from_file
from .catalogue import Catalogue, DiscoveryError, identity, reserve
from .config import DiscoveryConfig
from .resolution import ChooseRecording, NoSuitableRecording, normalized, rank_candidates, resolved_candidate, select_metadata_candidate

logger = logging.getLogger('music_rec.acquisition')


def same_recording(selected, candidate):
    # Deliberately conservative: remixes/live/remasters and release variants are
    # not silently collapsed merely because their titles look similar.
    title = normalized(selected["title"])
    candidate_title = normalized(candidate["title"])
    version = normalized(selected.get("version", ""))
    if title != candidate_title and normalized(title + " " + version) != candidate_title: return False
    if version and version not in normalized(candidate["title"] + " " + candidate.get("album", "")): return False
    if normalized(selected["artist"]) != normalized(candidate["artist"]): return False
    if selected.get("album") and normalized(selected["album"]) != normalized(candidate.get("album", "")): return False
    duration = selected.get("duration", 0)
    return not duration or abs(duration - candidate["duration"]) <= max(2, duration * .01)


class SpotDLAdapter:
    def __init__(self, config=None, lock_fd=None):
        self.config = config or DiscoveryConfig.load()
        self.lock_fd = lock_fd
        self.last_diagnostic = ''

    def run(self, arguments, cwd, timeout, payload=None):
        # Inheriting the worker lock prevents a replacement worker from launching
        # another download if its parent is SIGKILLed while this child still runs.
        process = subprocess.Popen(arguments, cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
            pass_fds=(() if self.lock_fd is None else (self.lock_fd,)))
        try:
            stdout, stderr = process.communicate(json.dumps(payload) if payload is not None else None, timeout=timeout)
        except BaseException:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.communicate()
            raise
        diagnostic = '\n'.join(part for part in (stderr, stdout) if part)[-8000:]
        for secret in (self.config.client_secret, self.config.client_id, self.config.contact):
            if secret: diagnostic = diagnostic.replace(secret, '[redacted]')
        self.last_diagnostic = diagnostic
        if process.returncode:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            logger.error('spotDL subprocess exited %s: %s', process.returncode, diagnostic)
            raise DiscoveryError("spotDL could not complete this operation. Check worker logs, installation, source availability and authentication.")
        return stdout

    def candidates(self, *, track_id=None, isrc=None, isrcs=None, track_ids=None, metadata=None):
        if track_id: identity("spotify", track_id)
        elif track_ids:
            for value in track_ids: identity('spotify', value)
        elif metadata:
            if not metadata.get('title') or not metadata.get('artist'):
                raise NoSuitableRecording('Selected recording has no usable title or artist credits. Search again.')
        elif isrcs:
            if any(not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{3}[0-9]{7}', value) for value in isrcs):
                raise DiscoveryError('Recording has an invalid ISRC.')
        elif not isrc or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}[0-9]{7}", isrc):
            raise DiscoveryError("Recording has no usable ISRC or verified Spotify link.")
        try:
            reserve('spotify-resolution', 1.05)
        except DiscoveryError as limited:
            # An empty identifier search can finish faster than our local slot
            # interval. Wait once in this background worker, rather than retrying
            # the entire job/identifier search forever before reaching fallback.
            if not 0 < limited.retry_after <= 2: raise
            time.sleep(limited.retry_after)
            reserve('spotify-resolution', 1.05)
        try:
            payload = ({'operation':'metadata-search', 'selected':metadata} if metadata else
                       {'track_ids':track_ids} if track_ids else {'isrcs':isrcs[:3]} if isrcs else {"track_id": track_id, "isrc": isrc})
            raw = self.run([sys.executable, "-m", "app.discovery.spotdl_bridge"],
                str(Path(__file__).resolve().parents[2]), 90, payload)
            data = json.loads(raw)
            if not isinstance(data, list): raise ValueError()
            return data
        except (ValueError, subprocess.TimeoutExpired) as error:
            raise DiscoveryError("Could not resolve Spotify metadata within the allowed time.") from error

    def resolve(self, selected):
        authoritative = Catalogue(self.config).lookup(selected)
        if authoritative["provider"] == "spotify":
            return resolved_candidate(authoritative, authoritative, 'spotify_id', verified_identity=True)
        candidates = []
        linked_ids = set()
        for url in authoritative.get("spotify_urls", []):
            match = re.fullmatch(r"https://open\.spotify\.com/(?:intl-[a-z]+/)?track/([A-Za-z0-9]{22})(?:\?[^\s]*)?", url)
            if match:
                linked_ids.add(match[1])
        if linked_ids:
            candidates = (self.candidates(track_id=next(iter(linked_ids))) if len(linked_ids) == 1 else
                          self.candidates(track_ids=sorted(linked_ids)[:3]))
        method = 'spotify_url' if candidates else 'isrc_metadata'
        isrcs = authoritative.get('isrcs') or []
        if not candidates:
            if isrcs:
                found = self.candidates(isrc=isrcs[0]) if len(isrcs) == 1 else self.candidates(isrcs=isrcs[:3])
                candidates = [track for track in found
                    if not track.get('isrcs') or set(track['isrcs']) & set(isrcs)]
        if candidates:
            matches = rank_candidates(authoritative, candidates)
            def strict_match(track):
                evidence = track['match_evidence']
                return (evidence['title_exact'] and evidence['artist_credits_exact'] and evidence['version_supported']
                    and (not authoritative.get('album') or evidence['album_exact'])
                    and (not authoritative.get('duration') or evidence['duration_close']))
            strict = [track for track in matches if strict_match(track)]
            if len(strict) == 1:
                candidate = strict[0]
                shared_isrc = bool(set(candidate.get('isrcs', [])) & set(isrcs))
                if method == 'spotify_url' or shared_isrc:
                    return resolved_candidate(authoritative, candidate, 'isrc' if shared_isrc else method, verified_identity=True)
                # A query containing an ISRC is not proof that the backend
                # verified it. Require the same multi-attribute confidence/margin
                # as metadata discovery if returned identifiers are absent.
                return select_metadata_candidate(authoritative, matches, method='isrc_metadata')
            if matches: raise ChooseRecording(authoritative, matches, method)
            raise NoSuitableRecording('Identifier candidates conflicted with the selected artist, duration or version. '
                'Search again and choose another release; no substitute was downloaded.')
        return select_metadata_candidate(authoritative, self.candidates(metadata=authoritative))

    def bounded_path(self, path):
        root = self.config.music_dir
        if root is None: raise DiscoveryError("Set VERSE_MUSIC_DIR before requesting songs.")
        result = Path(path).resolve()
        if not result.is_relative_to(root.resolve()): raise DiscoveryError("Download path is outside VERSE_MUSIC_DIR.")
        return result

    def audio_source(self, resolved):
        reserve('youtube-source', 1.05)
        try:
            data = json.loads(self.run([sys.executable, '-m', 'app.discovery.spotdl_bridge'],
                str(Path(__file__).resolve().parents[2]), 90, {'operation': 'audio-source', 'selected': resolved}))
            matches = {row['url']: row for row in data if same_recording(resolved, row)
                       and re.fullmatch(r'https://music\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}', row['url'])}
        except (ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            raise DiscoveryError('Could not verify audio-source metadata within the allowed time.') from error
        if len(matches) != 1:
            raise DiscoveryError('No unique song/album-verified audio source was found. No alternative recording was downloaded.')
        return next(iter(matches.values()))

    def download(self, resolved):
        track_id = resolved["recording_id"]
        identity("spotify", track_id)
        root = self.config.music_dir
        if root is None: raise DiscoveryError("Set VERSE_MUSIC_DIR before requesting songs.")
        staging = self.bounded_path(root / ".verse-requests" / track_id)
        final = self.bounded_path(root / "Requests" / (track_id + ".mp3"))
        staging.mkdir(parents=True, exist_ok=True); final.parent.mkdir(parents=True, exist_ok=True)
        candidate = self.bounded_path(staging / "track.mp3")
        source_file = self.bounded_path(staging / 'audio-source.json')
        source = resolved.get('audio_source')
        if not source and source_file.is_file():
            try: source = json.loads(source_file.read_text())
            except (ValueError, OSError): pass
        if not source or not same_recording(resolved, source) or not re.fullmatch(
                r'https://music\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}', source.get('url', '')):
            source = self.audio_source(resolved)
        source_file.write_text(json.dumps(source))
        resolved['audio_source'] = source
        # A crash after spotDL/rename but before the DB checkpoint must not cause
        # another download. Incomplete/invalid leftovers are kept for diagnostics.
        for existing in (final, candidate):
            if existing.exists():
                actual_source = audio_source_url_from_file(existing)
                if (spotify_id_from_file(existing) == track_id and actual_source
                        and actual_source.rsplit('v=', 1)[-1] == source['url'].rsplit('v=', 1)[-1]):
                    return existing
                if existing == final:
                    raise DiscoveryError('Existing acquired file has unverified audio provenance; it will not be overwritten.')
                quarantine = staging / ("incomplete-" + str(existing.stat().st_mtime_ns) + ".mp3")
                existing.replace(quarantine)
        executable = [self.config.spotdl_executable] if self.config.spotdl_executable else [sys.executable, "-m", "spotdl"]
        arguments = executable + ["download", source['url'] + f"|https://open.spotify.com/track/{track_id}",
            # A literal path is interpreted as a DIRECTORY by spotDL. Its path
            # sanitizer also strips leading dots, including .verse-requests.
            # A relative template plus our validated cwd avoids both behaviors.
            "--output", "track.{output-ext}", "--format", "mp3", "--threads", "1", "--max-retries", "1",
            "--overwrite", "skip", "--save-file", str(staging / "selection.spotdl")]
        # Preserve an operator's normal spotDL provider/cookie configuration while
        # always overriding its output directory and single-file execution limits.
        if (Path.home() / ".spotdl" / "config.json").is_file(): arguments.append("--config")
        try:
            self.run(arguments, str(staging), self.config.timeout)
        except subprocess.TimeoutExpired as error:
            raise DiscoveryError("Download timed out. A bounded retry will be attempted.") from error
        if not candidate.is_file():
            # spotDL may report provider/download failures while exiting zero.
            # Preserve that diagnostic instead of hiding the actual failure.
            logger.error('spotDL returned success without audio: %s', self.last_diagnostic)
            raise DiscoveryError("spotDL finished without producing audio. Check worker logs for the source error.")
        return candidate

    def publish(self, path, resolved):
        """Validate during indexing, then atomically publish; never expose .part files."""
        path = self.bounded_path(path)
        verify_audio_file(path, resolved)
        final = self.bounded_path(self.config.music_dir / "Requests" / (resolved["recording_id"] + ".mp3"))
        if path != final:
            if final.exists(): raise ValueError("A destination file already exists; it will not be overwritten.")
            final.parent.mkdir(parents=True, exist_ok=True)
            path.replace(final)
        return final
