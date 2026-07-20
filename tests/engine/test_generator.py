import pytest
from packages.engine.generator import generate_timeline
from packages.engine.models import (
    ClipDuration, ClipEvent, CrossfadeParams, Parameters,
    RepetitionParams, SelectionParams, SilenceEvent, SilenceParams,
)
from tests.engine.fixtures import make_asset, three_clips, basic_params


TEST_SEED = "cnc-audio-test-seed"


class TestDeterminism:
    def test_same_seed_produces_same_timeline(self):
        clips = three_clips()
        params = basic_params()
        t1 = generate_timeline(clips, params, TEST_SEED)
        t2 = generate_timeline(clips, params, TEST_SEED)
        assert len(t1.events) == len(t2.events)
        for e1, e2 in zip(t1.events, t2.events):
            assert e1.type == e2.type
            assert e1.position_seconds == e2.position_seconds
            if e1.type == "clip":
                assert e1.asset_id == e2.asset_id
                assert e1.source_start_seconds == e2.source_start_seconds

    def test_different_seeds_produce_different_timelines(self):
        clips = three_clips()
        params = basic_params(target=60.0)
        t1 = generate_timeline(clips, params, "seed-one")
        t2 = generate_timeline(clips, params, "seed-two")
        ids1 = [e.asset_id for e in t1.events if e.type == "clip"]
        ids2 = [e.asset_id for e in t2.events if e.type == "clip"]
        # With 3 clips and 60s, almost certainly different ordering
        assert ids1 != ids2 or t1.events[0].source_start_seconds != t2.events[0].source_start_seconds


class TestDuration:
    def test_trim_last_hits_exact_target(self):
        clips = three_clips()
        params = basic_params(target=30.0, duration_rule="trim_last")
        tl = generate_timeline(clips, params, TEST_SEED)
        assert abs(tl.total_duration_seconds - 30.0) < 0.001

    def test_fade_last_hits_exact_target(self):
        clips = three_clips()
        params = basic_params(target=30.0, duration_rule="fade_last")
        tl = generate_timeline(clips, params, TEST_SEED)
        assert abs(tl.total_duration_seconds - 30.0) < 0.001

    def test_events_are_ordered_by_position(self):
        clips = three_clips()
        params = basic_params(target=30.0)
        tl = generate_timeline(clips, params, TEST_SEED)
        positions = [e.position_seconds for e in tl.events]
        assert positions == sorted(positions)

    def test_clip_durations_within_bounds(self):
        clips = three_clips()
        params = basic_params(min_clip=2.0, max_clip=5.0, duration_rule="trim_last")
        tl = generate_timeline(clips, params, TEST_SEED)
        clip_events = [e for e in tl.events if e.type == "clip"]
        for e in clip_events[:-1]:  # all but last (last may be trimmed)
            dur = e.source_end_seconds - e.source_start_seconds
            assert dur >= 2.0 - 0.001
            assert dur <= 5.0 + 0.001


class TestRepetition:
    def test_max_per_clip_respected(self):
        clips = three_clips()
        params = basic_params(target=60.0, max_per_clip=2)
        tl = generate_timeline(clips, params, TEST_SEED)
        from collections import Counter
        counts = Counter(e.asset_id for e in tl.events if e.type == "clip")
        for asset_id, count in counts.items():
            assert count <= 2, f"{asset_id} used {count} times, max is 2"

    def test_no_consecutive_by_default(self):
        clips = three_clips()
        params = basic_params(target=60.0)
        params.repetition = RepetitionParams(allow_consecutive=False)
        tl = generate_timeline(clips, params, TEST_SEED)
        clip_ids = [e.asset_id for e in tl.events if e.type == "clip"]
        for i in range(len(clip_ids) - 1):
            assert clip_ids[i] != clip_ids[i + 1], "Consecutive clips detected"


class TestCrossfade:
    def test_crossfade_creates_overlapping_events(self):
        clips = three_clips()
        params = basic_params(target=30.0, crossfade=True, duration_rule="trim_last")
        params.crossfade = CrossfadeParams(enabled=True, min_seconds=0.5, max_seconds=1.0, probability=1.0)
        tl = generate_timeline(clips, params, TEST_SEED)
        clip_events = [e for e in tl.events if e.type == "clip"]
        if len(clip_events) >= 2:
            for i in range(len(clip_events) - 1):
                prev = clip_events[i]
                curr = clip_events[i + 1]
                prev_end = prev.position_seconds + (prev.source_end_seconds - prev.source_start_seconds)
                # Current clip starts before previous ends (overlap)
                assert curr.position_seconds < prev_end, "Expected overlap for crossfade"
                # fade_in on current should match fade_out on previous
                assert abs(curr.fade_in_seconds - prev.fade_out_seconds) < 0.001

    def test_no_crossfade_when_disabled(self):
        clips = three_clips()
        params = basic_params(target=30.0, crossfade=False, duration_rule="trim_last")
        tl = generate_timeline(clips, params, TEST_SEED)
        for e in tl.events:
            if e.type == "clip":
                assert e.fade_in_seconds == 0.0


class TestSilence:
    def test_silence_events_inserted(self):
        clips = three_clips()
        params = basic_params(target=30.0, silence=True, crossfade=False)
        params.silence = SilenceParams(enabled=True, probability=1.0, min_seconds=0.3, max_seconds=0.8)
        tl = generate_timeline(clips, params, TEST_SEED)
        silence_events = [e for e in tl.events if e.type == "silence"]
        assert len(silence_events) > 0

    def test_silence_durations_within_bounds(self):
        clips = three_clips()
        params = basic_params(target=30.0, silence=True, crossfade=False)
        params.silence = SilenceParams(enabled=True, probability=1.0, min_seconds=0.3, max_seconds=0.8)
        tl = generate_timeline(clips, params, TEST_SEED)
        for e in tl.events:
            if e.type == "silence":
                assert e.duration_seconds >= 0.3 - 0.001
                assert e.duration_seconds <= 0.8 + 0.001


class TestSequential:
    def test_sequential_respects_asset_order(self):
        clips = three_clips()  # a, b, c
        params = basic_params(target=30.0)
        params.selection = SelectionParams(distribution="sequential")
        tl = generate_timeline(clips, params, TEST_SEED)
        clip_ids = [e.asset_id for e in tl.events if e.type == "clip"]
        # Should cycle through a, b, c in order
        expected_cycle = ["a", "b", "c"]
        for i, asset_id in enumerate(clip_ids):
            assert asset_id == expected_cycle[i % 3], f"Expected {expected_cycle[i%3]} at position {i}, got {asset_id}"


class TestSourceRegion:
    def test_source_region_within_asset(self):
        clips = three_clips()
        params = basic_params(target=30.0)
        tl = generate_timeline(clips, params, TEST_SEED)
        asset_map = {a.id: a for a in clips}
        for e in tl.events:
            if e.type == "clip":
                asset = asset_map[e.asset_id]
                assert e.source_start_seconds >= 0.0
                assert e.source_end_seconds <= asset.duration_seconds + 0.001
                assert e.source_end_seconds > e.source_start_seconds
