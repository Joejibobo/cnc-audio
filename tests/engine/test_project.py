import json
import os
import tempfile
import pytest
from packages.engine.project import load_project, new_project, save_project
from packages.engine.models import (
    ClipDuration, ClipEvent, ExportSettings, Parameters,
    SilenceEvent, Timeline,
)
from tests.engine.fixtures import make_asset, three_clips, basic_params


class TestNewProject:
    def test_new_project_has_defaults(self):
        p = new_project("Test Project")
        assert p.project["name"] == "Test Project"
        assert p.version == "1.0.0"
        assert p.seed == "default"
        assert p.assets == []
        assert p.timeline is None

    def test_new_project_has_valid_parameters(self):
        p = new_project("Test")
        assert p.parameters.target_duration_seconds == 60.0
        assert p.parameters.clip_duration.min_seconds == 2.0
        assert p.parameters.clip_duration.max_seconds == 10.0


class TestSaveLoad:
    def _roundtrip(self, project):
        with tempfile.NamedTemporaryFile(suffix=".cnc", delete=False, mode="w") as f:
            path = f.name
        try:
            save_project(project, path)
            return load_project(path)
        finally:
            os.unlink(path)

    def test_roundtrip_empty_project(self):
        p = new_project("Roundtrip Test")
        loaded = self._roundtrip(p)
        assert loaded.project["name"] == "Roundtrip Test"
        assert loaded.version == p.version
        assert loaded.seed == p.seed

    def test_roundtrip_with_assets(self):
        p = new_project("Asset Test")
        p.assets = three_clips()
        loaded = self._roundtrip(p)
        assert len(loaded.assets) == 3
        assert loaded.assets[0].id == "a"
        assert loaded.assets[1].name == "clip_b"
        assert loaded.assets[2].duration_seconds == 8.0

    def test_roundtrip_with_timeline(self):
        p = new_project("Timeline Test")
        p.timeline = Timeline(
            events=[
                ClipEvent(
                    type="clip",
                    asset_id="a",
                    position_seconds=0.0,
                    source_start_seconds=1.0,
                    source_end_seconds=5.0,
                    gain_db=-2.0,
                    fade_in_seconds=0.5,
                    fade_out_seconds=0.5,
                ),
                SilenceEvent(
                    type="silence",
                    position_seconds=4.0,
                    duration_seconds=1.0,
                ),
            ],
            total_duration_seconds=5.0,
        )
        loaded = self._roundtrip(p)
        assert loaded.timeline is not None
        assert len(loaded.timeline.events) == 2
        clip = loaded.timeline.events[0]
        assert clip.type == "clip"
        assert clip.asset_id == "a"
        assert clip.gain_db == -2.0
        silence = loaded.timeline.events[1]
        assert silence.type == "silence"
        assert silence.duration_seconds == 1.0

    def test_roundtrip_parameters(self):
        p = new_project("Params Test")
        p.parameters = basic_params(target=120.0, min_clip=3.0, max_clip=8.0)
        p.seed = "my-custom-seed"
        loaded = self._roundtrip(p)
        assert loaded.parameters.target_duration_seconds == 120.0
        assert loaded.parameters.clip_duration.min_seconds == 3.0
        assert loaded.parameters.clip_duration.max_seconds == 8.0
        assert loaded.seed == "my-custom-seed"

    def test_saved_file_is_valid_json(self):
        p = new_project("JSON Test")
        with tempfile.NamedTemporaryFile(suffix=".cnc", delete=False, mode="w") as f:
            path = f.name
        try:
            save_project(p, path)
            with open(path, "r") as f:
                data = json.load(f)  # Should not raise
            assert data["version"] == "1.0.0"
        finally:
            os.unlink(path)
