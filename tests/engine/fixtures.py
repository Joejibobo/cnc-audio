"""Shared test fixtures for engine tests."""
from packages.engine.models import (
    Asset, ClipDuration, CrossfadeParams, Parameters,
    RepetitionParams, SelectionParams, SilenceParams,
)


def make_asset(id: str, name: str, duration: float, weight: float = 1.0) -> Asset:
    return Asset(
        id=id,
        name=name,
        path=f"assets/{name}.wav",
        hash=f"sha256:{'0' * 64}",
        duration_seconds=duration,
        weight=weight,
    )


def three_clips() -> list:
    """Three clips of varying lengths."""
    return [
        make_asset("a", "clip_a", duration=10.0),
        make_asset("b", "clip_b", duration=6.0),
        make_asset("c", "clip_c", duration=8.0),
    ]


def basic_params(
    target: float = 30.0,
    min_clip: float = 2.0,
    max_clip: float = 6.0,
    crossfade: bool = False,
    silence: bool = False,
    max_per_clip: int = None,
    duration_rule: str = "trim_last",
) -> Parameters:
    return Parameters(
        target_duration_seconds=target,
        clip_duration=ClipDuration(min_seconds=min_clip, max_seconds=max_clip),
        crossfade=CrossfadeParams(enabled=crossfade, probability=1.0),
        silence=SilenceParams(enabled=silence, probability=1.0),
        repetition=RepetitionParams(max_per_clip=max_per_clip),
        selection=SelectionParams(distribution="uniform", chaos=0.5),
        duration_rule=duration_rule,
    )
