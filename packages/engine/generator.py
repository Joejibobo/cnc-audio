"""Deterministic, seeded timeline generator."""
import hashlib
import random
from typing import Dict, List, Optional, Tuple

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
    used_ranges_by_asset: Dict[str, List[Tuple[float, float]]],
    min_required_seconds: Optional[float] = None,
) -> Optional[Asset]:
    """Select the next clip, enforcing hard constraints and scoring soft preferences."""
    max_per = params.repetition.max_per_clip
    min_required = (
        params.clip_duration.min_seconds
        if min_required_seconds is None
        else min_required_seconds
    )

    candidates = [
        a for a in assets
        if a.duration_seconds >= min_required
        and (max_per is None or use_counts.get(a.id, 0) < max_per)
        and (
            not params.repetition.no_repeat_sections
            or _max_available_span(a.duration_seconds, used_ranges_by_asset.get(a.id, [])) >= min_required
        )
    ]

    if not candidates:
        return None

    if not params.repetition.allow_consecutive and last_clip_id is not None:
        no_consec = [a for a in candidates if a.id != last_clip_id]
        if no_consec:
            candidates = no_consec

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

    if dist == "uniform":
        weights = [1.0] * len(candidates)
    else:  # weighted
        weights = [max(0.0, a.weight) for a in candidates]

    if params.repetition.repeat_decay > 0:
        decay = params.repetition.repeat_decay
        for i, a in enumerate(candidates):
            count = use_counts.get(a.id, 0)
            if count > 0:
                weights[i] *= max(0.01, (1.0 - decay) ** count)

    min_gap = params.repetition.min_gap_clips
    chaos = params.selection.chaos
    if min_gap > 0 and chaos < 1.0 and recent_ids:
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


def _sorted_intervals(intervals: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    return sorted(intervals, key=lambda x: x[0])


def _available_windows(
    total_duration: float, used_intervals: List[Tuple[float, float]]
) -> List[Tuple[float, float]]:
    windows: List[Tuple[float, float]] = []
    cursor = 0.0
    for start, end in _sorted_intervals(used_intervals):
        start = max(0.0, min(total_duration, start))
        end = max(0.0, min(total_duration, end))
        if end <= start:
            continue
        if start > cursor:
            windows.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total_duration:
        windows.append((cursor, total_duration))
    return windows


def _max_available_span(
    total_duration: float, used_intervals: List[Tuple[float, float]]
) -> float:
    windows = _available_windows(total_duration, used_intervals)
    if not windows:
        return 0.0
    return max(end - start for start, end in windows)


def _pick_source_region(
    asset_duration: float,
    used_intervals: List[Tuple[float, float]],
    dur: float,
    rng: random.Random,
) -> Optional[Tuple[float, float]]:
    if dur <= 0:
        return None
    windows = _available_windows(asset_duration, used_intervals)
    valid_windows = [(start, end) for start, end in windows if (end - start) >= dur]
    if not valid_windows:
        return None

    capacities = [(end - start) - dur for start, end in valid_windows]
    weights = [cap + 1e-6 for cap in capacities]
    chosen = rng.choices(valid_windows, weights=weights, k=1)[0]
    start, end = chosen
    source_start = rng.uniform(start, end - dur)
    return source_start, source_start + dur


def _register_used_range(
    used_ranges_by_asset: Dict[str, List[Tuple[float, float]]],
    asset_id: str,
    start: float,
    end: float,
) -> None:
    if end <= start:
        return
    used_ranges_by_asset.setdefault(asset_id, []).append((start, end))


def _fill_remaining_with_random_clip(
    events: List,
    assets: List[Asset],
    params: Parameters,
    rng: random.Random,
    use_counts: dict,
    recent_ids: List[str],
    sequential_idx: List[int],
    last_clip_id: Optional[str],
    used_ranges_by_asset: Dict[str, List[Tuple[float, float]]],
    position: float,
    target: float,
) -> float:
    """Fill the final remaining gap with one additional random clip segment."""
    remaining = target - position
    if remaining <= 0:
        return position

    clip = _select_clip(
        assets,
        params,
        rng,
        use_counts,
        recent_ids,
        sequential_idx,
        last_clip_id,
        used_ranges_by_asset,
        min_required_seconds=0.001,
    )
    if clip is None:
        return position

    max_available = _max_available_span(
        clip.duration_seconds, used_ranges_by_asset.get(clip.id, [])
    )
    dur = min(remaining, max_available)
    if dur <= 0:
        return position

    used_for_region = used_ranges_by_asset.get(clip.id, []) if params.repetition.no_repeat_sections else []
    region = _pick_source_region(
        clip.duration_seconds,
        used_for_region,
        dur,
        rng,
    )
    if region is None:
        return position
    source_start, source_end = region

    events.append(
        ClipEvent(
            type="clip",
            asset_id=clip.id,
            position_seconds=round(position, 4),
            source_start_seconds=round(source_start, 4),
            source_end_seconds=round(source_end, 4),
            gain_db=_clip_gain_db(clip, params, rng),
            fade_in_seconds=0.0,
            fade_out_seconds=0.0,
        )
    )
    _register_used_range(used_ranges_by_asset, clip.id, source_start, source_end)

    return position + dur


def _extend_last_clip(
    last_clip_event: Optional[ClipEvent],
    assets_by_id: dict,
    used_ranges_by_asset: Dict[str, List[Tuple[float, float]]],
    position: float,
    target: float,
) -> float:
    """Extend the last clip event to reduce the final remaining gap."""
    if last_clip_event is None:
        return position

    asset = assets_by_id.get(last_clip_event.asset_id)
    if asset is None:
        return position

    remaining = target - position
    if remaining <= 0:
        return position

    used_intervals = list(used_ranges_by_asset.get(last_clip_event.asset_id, []))
    original_start = last_clip_event.source_start_seconds
    original_end = last_clip_event.source_end_seconds
    other_intervals = [
        (s, e) for (s, e) in used_intervals
        if not (abs(s - original_start) < 1e-6 and abs(e - original_end) < 1e-6)
    ]

    next_start = asset.duration_seconds
    prev_end = 0.0
    for start, end in _sorted_intervals(other_intervals):
        if end <= original_start:
            prev_end = max(prev_end, end)
            continue
        if start >= original_end:
            next_start = min(next_start, start)
            break

    current_dur = (
        last_clip_event.source_end_seconds - last_clip_event.source_start_seconds
    )
    max_dur = asset.duration_seconds
    new_dur = min(max_dur, current_dur + remaining)
    if new_dur <= current_dur:
        return position

    need_more = new_dur - current_dur
    room_at_end = max(0.0, next_start - last_clip_event.source_end_seconds)
    add_at_end = min(room_at_end, need_more)
    last_clip_event.source_end_seconds = round(
        last_clip_event.source_end_seconds + add_at_end, 4
    )
    need_more -= add_at_end
    if need_more > 0:
        room_at_start = max(0.0, last_clip_event.source_start_seconds - prev_end)
        last_clip_event.source_start_seconds = round(
            max(prev_end, last_clip_event.source_start_seconds - min(need_more, room_at_start)),
            4,
        )

    adjusted_dur = (
        last_clip_event.source_end_seconds - last_clip_event.source_start_seconds
    )
    added = max(0.0, adjusted_dur - current_dur)
    if added > 0:
        used_ranges_by_asset[last_clip_event.asset_id] = other_intervals + [(
            last_clip_event.source_start_seconds,
            last_clip_event.source_end_seconds,
        )]
    return position + added


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
    assets_by_id = {a.id: a for a in assets}
    used_ranges_by_asset: Dict[str, List[Tuple[float, float]]] = {}

    while True:
        remaining = target - position

        if remaining < params.clip_duration.min_seconds:
            break

        clip = _select_clip(
            assets,
            params,
            rng,
            use_counts,
            recent_ids,
            sequential_idx,
            last_clip_id,
            used_ranges_by_asset,
        )
        if clip is None:
            break

        available_max = _max_available_span(
            clip.duration_seconds,
            used_ranges_by_asset.get(clip.id, []) if params.repetition.no_repeat_sections else [],
        )
        usable_max = min(params.clip_duration.max_seconds, available_max)
        usable_min = params.clip_duration.min_seconds

        if params.duration_rule != "pad_silence":
            usable_max = min(usable_max, remaining)

        if usable_max < usable_min:
            break

        dur = rng.uniform(usable_min, usable_max)

        used_for_region = used_ranges_by_asset.get(clip.id, []) if params.repetition.no_repeat_sections else []
        region = _pick_source_region(
            clip.duration_seconds,
            used_for_region,
            dur,
            rng,
        )
        if region is None:
            break
        source_start, source_end = region

        # Crossfade with the previous clip
        fade_in = 0.0
        if (
            last_clip_event is not None
            and params.crossfade.enabled
            and rng.random() < params.crossfade.probability
        ):
            prev_dur = last_clip_event.source_end_seconds - last_clip_event.source_start_seconds
            xfade_limit = min(
                params.crossfade.max_seconds,
                dur * 0.45,
                prev_dur * 0.45,
            )
            xfade_min = min(params.crossfade.min_seconds, xfade_limit)
            if xfade_min <= xfade_limit and xfade_limit > 0:
                xfade = rng.uniform(xfade_min, xfade_limit)
                last_clip_event.fade_out_seconds = round(xfade, 4)
                fade_in = xfade
                position -= xfade

        gain_db = _clip_gain_db(clip, params, rng)

        is_last = position + dur >= target
        fade_out = 0.0

        if is_last and params.duration_rule in ("trim_last", "fade_last"):
            dur = target - position
            source_end = source_start + dur
            if params.duration_rule == "fade_last" and dur > 0:
                fade_out = round(min(2.0, dur * 0.30), 4)

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
        _register_used_range(used_ranges_by_asset, clip.id, source_start, source_end)

        use_counts[clip.id] = use_counts.get(clip.id, 0) + 1
        recent_ids.append(clip.id)
        last_clip_id = clip.id
        max_recent = max(params.repetition.min_gap_clips + 1, 20)
        if len(recent_ids) > max_recent:
            recent_ids = recent_ids[-max_recent:]

        if is_last:
            break

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

    # Fill any remaining gap (e.g. from crossfade math)
    if position < target:
        if params.duration_rule == "fill_random_clip":
            position = _fill_remaining_with_random_clip(
                events=events,
                assets=assets,
                params=params,
                rng=rng,
                use_counts=use_counts,
                recent_ids=recent_ids,
                sequential_idx=sequential_idx,
                last_clip_id=last_clip_id,
                used_ranges_by_asset=used_ranges_by_asset,
                position=position,
                target=target,
            )
        elif params.duration_rule == "extend_last_clip":
            position = _extend_last_clip(
                last_clip_event=last_clip_event,
                assets_by_id=assets_by_id,
                used_ranges_by_asset=used_ranges_by_asset,
                position=position,
                target=target,
            )

        gap = round(target - position, 4)
        if gap > 0.001:
            events.append(
                SilenceEvent(
                    type="silence",
                    position_seconds=round(position, 4),
                    duration_seconds=gap,
                )
            )
            position = target

    return Timeline(
        events=events,
        total_duration_seconds=round(position, 4),
    )
