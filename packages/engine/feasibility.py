"""Pre-generation feasibility checks."""
from dataclasses import dataclass, field
from typing import List

from .models import Asset, Parameters


@dataclass
class FeasibilityResult:
    feasible: bool
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def check_feasibility(assets: List[Asset], params: Parameters) -> FeasibilityResult:
    """Check whether the given assets and parameters can produce a valid track."""
    warnings: List[str] = []
    errors: List[str] = []

    target = params.target_duration_seconds
    min_dur = params.clip_duration.min_seconds
    max_dur = params.clip_duration.max_seconds

    if target <= 0:
        errors.append(f"target_duration_seconds must be > 0 (got {target}).")

    if min_dur <= 0:
        errors.append(f"clip_duration.min_seconds must be > 0 (got {min_dur}).")

    if max_dur <= 0:
        errors.append(f"clip_duration.max_seconds must be > 0 (got {max_dur}).")

    if min_dur > max_dur:
        errors.append(
            f"clip_duration.min_seconds ({min_dur}s) > clip_duration.max_seconds ({max_dur}s)."
        )
        return FeasibilityResult(feasible=False, warnings=warnings, errors=errors)

    if not assets:
        errors.append("No assets registered. Import at least one audio clip.")
        return FeasibilityResult(feasible=False, warnings=warnings, errors=errors)

    usable = [a for a in assets if a.duration_seconds >= min_dur]
    unusable = [a for a in assets if a.duration_seconds < min_dur]

    if not usable:
        shortest = min(a.duration_seconds for a in assets)
        errors.append(
            f"No assets meet the minimum clip duration of {min_dur}s. "
            f"Shortest asset is {shortest:.2f}s. "
            f"Lower clip_duration.min_seconds or import longer clips."
        )
        return FeasibilityResult(feasible=False, warnings=warnings, errors=errors)

    if unusable:
        warnings.append(
            f"{len(unusable)} asset(s) are shorter than min_clip_duration ({min_dur}s) "
            f"and will never be selected: {', '.join(a.name for a in unusable)}."
        )

    max_per = params.repetition.max_per_clip
    no_repeat_sec = params.repetition.no_repeat_sections

    # When clips can repeat AND source sections can repeat, content is effectively
    # unlimited — any clip can be played as many times as needed.
    # When no_repeat_sections=True, each clip can only contribute its unique duration.
    # When max_per is set, each clip contributes at most max_per * max_dur.
    if max_per is None and not no_repeat_sec:
        max_fillable = float('inf')
    else:
        max_fillable = 0.0
        for asset in usable:
            if no_repeat_sec:
                # Unique source sections can contribute at most the asset's
                # duration, regardless of how many selections are allowed.
                asset_cap = asset.duration_seconds
                if max_per is not None:
                    asset_cap = min(asset_cap, max_per * max_dur)
            else:
                # Reusing source sections permits the same playable span on
                # each allowed selection.
                per_use = min(asset.duration_seconds, max_dur)
                asset_cap = max_per * per_use
            max_fillable += asset_cap

    effective_target = target

    if max_fillable < effective_target:
        errors.append(
            f"Cannot fill a {target}s track: maximum achievable content is "
            f"~{max_fillable:.0f}s with {len(usable)} usable clip(s). "
            f"Try: enable 'Allow Repeats', disable 'No Repeat Sections', add more clips, or reduce target duration."
        )
    elif max_fillable != float('inf') and max_fillable < effective_target * 1.25:
        warnings.append(
            f"Content headroom is tight (~{max_fillable:.0f}s available for a {target}s track). "
            f"There will be limited variety. Consider adding more clips or increasing max_per_clip."
        )

    if params.selection.distribution == "sequential" and params.repetition.max_per_clip == 1:
        unique_content = sum(min(a.duration_seconds, max_dur) for a in usable)
        if unique_content < target:
            errors.append(
                f"Sequential distribution with max_per_clip=1 can only produce "
                f"~{unique_content:.0f}s but target is {target}s. "
                f"Either allow repeats or add more clips."
            )

    min_gap = params.repetition.min_gap_clips
    if min_gap > 0 and len(usable) <= min_gap:
        warnings.append(
            f"min_gap_clips={min_gap} but only {len(usable)} usable clip(s). "
            f"The gap preference cannot always be satisfied and will be relaxed automatically."
        )

    return FeasibilityResult(feasible=len(errors) == 0, warnings=warnings, errors=errors)
