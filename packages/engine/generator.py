"""Deterministic, seeded timeline generator.

Given a list of assets, generation parameters, and a seed string, produces a
validated Timeline. The same seed + assets + parameters always produces the
same result.
"""
import hashlib
import random
from typing import List, Optional

from .models import Asset, ClipEvent, Parameters, SilenceEvent, Timeline


def _make_rng(seed: str) -> random.Random:
    """Create a deterministic RNG from a seed string."""
    seed_int = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % (2 ** 32)
    return random.Random(seed_int)


def _select_clip(
    assets: List[Asset],
    params: Parameters,
    rng: random.Random,
    use_counts: dict,
    recent_ids: List[str],
    sequential_idx: List[int],
    last_clip_id: Optional[str],
) -> Optional[Asset]:
    """Select the next clip, enforcing hard constraints and scoring soft preferences."""
    max_per = params.repetition.max_per_clip

    # Hard filter: clips that are usable and haven't hit their repeat ceiling
    candidates = [
        a for a in assets
        if a.duration_seconds >= params.clip_duration.min_seconds
        and (max_per is None or use_counts.get(a.id, 0) < max_per)
    ]

    if not candidates:
        return None

    # Hard filter: no back-to-back repeats
    if not params.repetition.allow_consecutive and last_clip_id is not None:
        no_consec = [a for a in candidates if a.id != last_clip_id]
        if no_consec:
            candidates = no_consec
        # If no_consec is empty we relax this constraint rather than fail

    if not candidates:
        return None

    dist = params.selection.distribution

    if dist == "sequential":
        candidate_ids = {a.id for a in candidates}
        start = sequential_idx[0]
        for i in range(len(assets)):
            asset = assets[(start + i) % len(assets)]
            if asset.id in candidate_ids:
                sequential_idx[0] = (start + i + 1) % len(assets)
                return asset
        return None

    # Compute base weights
    if dist == "uniform":
        weights = [1.0] * len(candidates)
    else:  # weighted
        weights = [max(0.0, a.weight) for a in candidates]

    # Soft preference: penalize recently used clips based on gap and chaos
    min_gap = params.repetition.min_gap_clips
    chaos = params.selection.chaos
    if min_gap > 0 and chaos < 1.0 and len(recent_ids) > 0:
        recent_window = recent_ids[-min_gap:]
        penalty_strength = (1.0 - chaos) * 0.85
        for i, a in enumerate(candidates):
            if a.id in recent_window:
                weights[i] *= (1.0 - penalty_strength)

    total = sum(weights)
    if total <= 0:
        return rng.choice(candidates)

    return rng.choices(candidates, weights=weights, k=1)[0]


def _clip_gain_db(asset: Asset, params: Parameters, rng: random.Random) -> float:
    """Compute a non-destructive gain adjustment (dB) for one clip instance."""
    gain = 0.0

    if (
        params.gain.normalize
        and asset.analysis is not None
        and asset.analysis.lufs is not None
    ):
        needed = params.gain.target_lufs - asset.analysis.lufs
        gain = max(-params.gain.max_gain_db, min(params.gain.max_gain_db, needed))

    if params.gain.random_variation_db > 0:
        gain += rng.uniform(
            -params.gain.random_variation_db, params.gain.random_variation_db
        )

    return round(gain, 3)


def generate_timeline(assets: List[Asset], params: Parameters, seed: str) -> Timeline:
    """
    Generate a deterministic timeline.

    Returns a Timeline containing ClipEvent and SilenceEvent objects ordered
    by position_seconds. The same (assets, params, seed) triple always produces
    the same timeline.

    Does NOT read or modify any audio files.
    """
    rng = _make_rng(seed)
    events: List = []
    position = 0.0
    target = params.target_duration_seconds
    use_counts: dict = {}
    recent_ids: List[str] = []
    sequential_idx = [0]
    last_clip_id: Optional[str] = None
    last_clip_event: Optional[ClipEvent] = None

    while True:
        remaining = target - position

        # Stop if we can't fit another minimum-length clip
        if remaining < params.clip_duration.min_seconds:
            break

        # --- Select clip ---
        clip = _select_clip(
            assets, params, rng, use_counts, recent_ids, sequential_idx, last_clip_id
        )
        if clip is None:
            break  # Exhausted available clips

        # --- Determine how much of this clip to use ---
        usable_max = min(params.clip_duration.max_seconds, clip.duration_seconds)
        usable_min = params.clip_duration.min_seconds

        if params.duration_rule != "pad_silence":
            usable_max = min(usable_max, remaining)

        if usable_max < usable_min:
            break

        dur = rng.uniform(usable_min, usable_max)

        # --- Pick a random region within the source asset ---
        max_source_start = max(0.0, clip.duration_seconds - dur)
        source_start = rng.uniform(0.0, max_source_start)
        source_end = source_start + dur

        # --- Crossfade with previous clip ---
        fade_in = 0.0
        if (
            last_clip_event is not None
            and params.crossfade.enabled
            and rng.random() < params.crossfade.probability
        ):
            prev_dur = last_clip_event.source_end_seconds - last_clip_event.source_start_seconds
            xfade_limit = min(
                params.crossfade.max_seconds,
                dur * 0.45,        # Don't crossfade more than 45% of the new clip
                prev_dur * 0.45,   # Don't crossfade more than 45% of the previous clip
            )
            xfade_min = min(params.crossfade.min_seconds, xfade_limit)
            if xfade_min <= xfade_limit and xfade_limit > 0:
                xfade = rng.uniform(xfade_min, xfade_limit)
                last_clip_event.fade_out_seconds = round(xfade, 4)
                fade_in = xfade
                position -= xfade

        # --- Compute gain ---
        gain_db = _clip_gain_db(clip, params, rng)

        # --- Check if this is the final clip ---
        is_last = position + dur >= target
        fade_out = 0.0

        if is_last and params.duration_rule in ("trim_last", "fade_last"):
            dur = target - position
            source_end = source_start + dur
            if params.duration_rule == "fade_last" and dur > 0:
                fade_out = round(min(2.0, dur * 0.30), 4)

        # --- Create event ---
        event = ClipEvent(
            type="clip",
            asset_id=clip.id,
            position_seconds=round(position, 4),
            source_start_seconds=round(source_start, 4),
            source_end_seconds=round(source_end, 4),
            gain_db=gain_db,
            fade_in_seconds=round(fade_in, 4),
            fade_out_seconds=fade_out,
        )
        events.append(event)
        last_clip_event = event
        position += dur

        # --- Update tracking ---
        use_counts[clip.id] = use_counts.get(clip.id, 0) + 1
        recent_ids.append(clip.id)
        last_clip_id = clip.id
        max_recent = max(params.repetition.min_gap_clips + 1, 20)
        if len(recent_ids) > max_recent:
            recent_ids = recent_ids[-max_recent:]

        if is_last:
            break

        # --- Maybe insert silence gap ---
        if params.silence.enabled and rng.random() < params.silence.probability:
            after_silence = target - position
            sil_max = min(params.silence.max_seconds, after_silence - params.clip_duration.min_seconds)
            sil_min = params.silence.min_seconds
            if sil_min <= sil_max and sil_max > 0:
                sil_dur = rng.uniform(sil_min, sil_max)
                events.append(SilenceEvent(
                    type="silence",
                    position_seconds=round(position, 4),
                    duration_seconds=round(sil_dur, 4),
                ))
                position += sil_dur

    # --- Fill any remaining gap (e.g. from crossfade math or silence overshoot) ---
    if position < target:
        gap = round(target - position, 4)
        if gap > 0.001:  # ignore sub-millisecond floating point noise
            events.append(SilenceEvent(
                type="silence",
                position_seconds=round(position, 4),
                duration_seconds=gap,
            ))
        position = target

    return Timeline(
        events=events,
        total_duration_seconds=round(position, 4),
    )
