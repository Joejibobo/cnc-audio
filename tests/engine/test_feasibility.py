import pytest
from packages.engine.feasibility import check_feasibility
from packages.engine.models import ClipDuration, Parameters, RepetitionParams, SelectionParams
from tests.engine.fixtures import make_asset, three_clips, basic_params


class TestFeasibilityErrors:
    def test_no_assets(self):
        result = check_feasibility([], basic_params())
        assert not result.feasible
        assert any("No assets" in e for e in result.errors)

    def test_min_greater_than_max(self):
        params = basic_params(min_clip=5.0, max_clip=2.0)
        result = check_feasibility(three_clips(), params)
        assert not result.feasible
        assert any("min_seconds" in e and "max_seconds" in e for e in result.errors)

    def test_all_clips_too_short(self):
        clips = [make_asset("a", "short", duration=1.0)]
        params = basic_params(min_clip=2.0)
        result = check_feasibility(clips, params)
        assert not result.feasible
        assert any("minimum clip duration" in e for e in result.errors)

    def test_cannot_fill_target_with_max_per_clip(self):
        clips = [make_asset("a", "clip", duration=5.0)]
        params = basic_params(target=60.0, max_clip=5.0, max_per_clip=1, crossfade=False)
        result = check_feasibility(clips, params)
        assert not result.feasible
        assert any("Cannot fill" in e for e in result.errors)

    def test_sequential_max_per_clip_1_too_short(self):
        clips = [make_asset("a", "clip_a", duration=5.0)]
        params = Parameters(
            target_duration_seconds=60.0,
            clip_duration=ClipDuration(min_seconds=2.0, max_seconds=5.0),
            repetition=RepetitionParams(max_per_clip=1),
            selection=SelectionParams(distribution="sequential"),
        )
        result = check_feasibility(clips, params)
        assert not result.feasible


class TestFeasibilityWarnings:
    def test_some_clips_too_short_warns(self):
        clips = [
            make_asset("a", "long", duration=10.0),
            make_asset("b", "short", duration=0.5),
        ]
        result = check_feasibility(clips, basic_params(target=8.0, min_clip=2.0))
        assert result.feasible
        assert any("shorter than min_clip_duration" in w for w in result.warnings)

    def test_tight_headroom_warns(self):
        clips = [make_asset("a", "clip", duration=5.0)]
        params = basic_params(target=5.0, min_clip=4.0, max_clip=5.0, max_per_clip=1, crossfade=False)
        result = check_feasibility(clips, params)
        assert result.feasible
        assert any("tight" in w.lower() for w in result.warnings)

    def test_gap_exceeds_clip_count_warns(self):
        clips = [make_asset("a", "clip_a", duration=10.0), make_asset("b", "clip_b", duration=10.0)]
        params = basic_params(target=15.0)
        params.repetition = RepetitionParams(min_gap_clips=5)
        result = check_feasibility(clips, params)
        assert result.feasible
        assert any("gap" in w.lower() for w in result.warnings)


class TestFeasibilitySuccess:
    def test_basic_success(self):
        result = check_feasibility(three_clips(), basic_params(target=20.0))
        assert result.feasible
        assert result.errors == []

    def test_total_unique_duration_caps_feasibility(self):
        clips = [make_asset("a", "clip", duration=3.0)]
        params = basic_params(target=3600.0, max_per_clip=None)
        result = check_feasibility(clips, params)
        assert not result.feasible
