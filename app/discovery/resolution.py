"""Bounded, explainable recording matching; a score is not a verified identity."""
from difflib import SequenceMatcher
import math
import re
import unicodedata

from .catalogue import DiscoveryError, identity


def normalized(value):
    return re.sub(r'[^\w]+', ' ', unicodedata.normalize('NFKC', value or '').casefold()).strip()


class NoSuitableRecording(DiscoveryError):
    retryable = False


class ChooseRecording(DiscoveryError):
    def __init__(self, selected, candidates, method):
        super().__init__('Several versions remain plausible; choose a version to continue this request.')
        self.options = dict(selection_required=True, selected=selected, candidates=candidates[:5], method=method)


def artist_names(track):
    credits = track.get('artist_credits') or []
    if credits:
        return {normalized(c['name']) for c in credits if c.get('name')}
    return {normalized(name) for name in re.split(r'\s*(?:,|;|&|\bfeat\.?|\bft\.?)\s*', track['artist']) if name}


VARIANTS = {
    'live': r'\blive\b|\bconcert\b', 'remix': r'\bremix\w*\b', 'remaster': r'\bremaster\w*\b',
    'acoustic': r'\bacoustic\b|\bunplugged\b', 'instrumental': r'\binstrumental\b',
    'karaoke': r'\bkaraoke\b', 'demo': r'\bdemo\b', 'edit': r'\bradio edit\b|\bsingle edit\b',
    'speed': r'\bsped up\b|\bslowed\b|\bnightcore\b', 'cover': r'\bcover\b|\btribute\b',
    'rerecording': r'\bre recorded\b|\brerecord\w*\b|\btaylor s version\b',
    'extended': r'\bextended\b', 'mono': r'\bmono\b', 'stereo': r'\bstereo\b',
}


def variants(track):
    text = normalized(' '.join(track.get(key, '') for key in ('title', 'album', 'version')))
    return {name for name, pattern in VARIANTS.items() if re.search(pattern, text)}


def rank_candidates(selected, candidates):
    """Return plausible versions only. Known artist/version/duration conflicts veto.

    Points: title 35, artist credits 30, duration 20, album 10, version 5.
    Automatic metadata matching additionally requires exact title/credits/album,
    close known duration, represented disambiguation, score >=95 and margin >=8.
    """
    ranked = {}
    for candidate in candidates[:30]:
        try:
            if candidate['key'] != identity('spotify', candidate['recording_id']): continue
            if selected.get('isrcs') and candidate.get('isrcs') and not set(selected['isrcs']) & set(candidate['isrcs']):
                continue
            title = normalized(selected['title'])
            other = normalized(candidate['title'])
            qualified = normalized(title + ' ' + (selected.get('version') or ''))
            title_exact = other in (title, qualified)
            similarity = max(SequenceMatcher(None, title, other).ratio(), SequenceMatcher(None, qualified, other).ratio())
            names, others = artist_names(selected), artist_names(candidate)
            credit_similarity = len(names & others) / len(names | others) if names and others else 0
            if similarity < .88 or credit_similarity < .5 or variants(selected) != variants(candidate): continue
            duration, other_duration = float(selected.get('duration') or 0), float(candidate['duration'])
            if not math.isfinite(other_duration) or other_duration <= 0: continue
            delta = abs(duration - other_duration) if duration else None
            close_duration = delta is not None and delta <= max(2, duration * .01)
            if delta is not None and delta > max(8, duration * .05): continue
            album = normalized(selected.get('album'))
            album_exact = bool(album) and album == normalized(candidate.get('album'))
            disambiguation = normalized(selected.get('version'))
            version_supported = not disambiguation or disambiguation in normalized(' '.join(
                candidate.get(key, '') for key in ('title', 'album', 'version')))
            duration_points = 20 if close_duration else (10 if delta is not None else 0)
            score = round(35 * similarity + 30 * credit_similarity + duration_points + 10 * album_exact + 5 * version_supported, 2)
            if score < 70: continue
            evidence = dict(title_exact=title_exact, artist_credits_exact=names == others,
                duration_delta_seconds=round(delta, 3) if delta is not None else None,
                duration_close=close_duration, album_exact=album_exact, version_supported=version_supported)
            ranked[candidate['key']] = {**candidate, 'match_score': score, 'match_evidence': evidence}
        except (KeyError, TypeError, ValueError, DiscoveryError):
            continue  # One malformed provider hit must not poison every candidate.
    return sorted(ranked.values(), key=lambda track: (-track['match_score'], track['key']))


def resolved_candidate(selected, candidate, method, *, verified_identity=False, user_selected=False):
    return {**candidate, 'resolution': dict(method=method, verified_identity=verified_identity,
        user_selected=user_selected, selected_key=selected['key'], score=candidate.get('match_score'),
        evidence=candidate.get('match_evidence', {}))}


def select_metadata_candidate(selected, candidates, method='metadata'):
    ranked = rank_candidates(selected, candidates)
    if not ranked:
        raise NoSuitableRecording('No suitable recording matched the selected artist, title, duration and version. '
            'Retry discovery or search again and select a specific release; no alternative recording was downloaded.')
    best = ranked[0]
    evidence = best['match_evidence']
    if (best['match_score'] >= 95 and all(evidence[key] for key in
            ('title_exact', 'artist_credits_exact', 'duration_close', 'album_exact', 'version_supported'))
            and (len(ranked) == 1 or best['match_score'] - ranked[1]['match_score'] >= 8)):
        return resolved_candidate(selected, best, method)
    raise ChooseRecording(selected, ranked, method)
