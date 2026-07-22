from fastapi.testclient import TestClient

from packages.api import main
from packages.engine.models import Asset, SilenceEvent, Timeline
from packages.engine.project import new_project, save_project


def _configure_projects_root(tmp_path, monkeypatch):
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    monkeypatch.setattr(main, "PROJECTS_DIR", projects_root)
    return projects_root


def _asset(asset_id: str, name: str, duration: float = 12.0) -> Asset:
    return Asset(
        id=asset_id,
        name=name,
        path=f"assets/{asset_id}_original.wav",
        hash="sha256:test",
        duration_seconds=duration,
        format="wav",
    )


def test_get_project_migrates_v1_assets_to_song_layer(tmp_path, monkeypatch):
    _configure_projects_root(tmp_path, monkeypatch)
    project_id = "legacy-project"
    project_dir = main._project_dir(project_id)
    main._ensure_project_dirs(project_dir)

    legacy = new_project("Legacy")
    legacy.assets = [_asset("song-a", "song_a")]
    save_project(legacy, str(project_dir / "project.cnc"))

    client = TestClient(main.app)
    response = client.get(f"/api/projects/{project_id}")

    assert response.status_code == 200
    data = response.json()
    assert len(data["song_assets"]) == 1
    assert data["song_assets"][0]["id"] == "song-a"
    assert data["sound_assets"] == []


def test_layered_parameters_are_saved_per_layer(tmp_path, monkeypatch):
    _configure_projects_root(tmp_path, monkeypatch)
    main._ensure_project_dirs(main._project_dir("layered-params"))
    project = new_project("Layered Params")
    main._set_song_assets(project, [_asset("song-a", "song_a")])
    main._set_sound_assets(project, [_asset("sound-a", "sound_a")])
    main._set_render_settings(
        project,
        {
            "target_duration_seconds": 12.0,
            "song_gain_db": 0.0,
            "sound_gain_db": 0.0,
            "render_gain_db": 0.0,
            "normalize_output": True,
        },
    )
    main._save("layered-params", project)

    client = TestClient(main.app)
    response = client.put(
        "/api/projects/layered-params/parameters",
        json={
            "render_settings": {
                "target_duration_seconds": 8,
                "song_gain_db": 2.5,
                "sound_gain_db": -3.0,
                "render_gain_db": 1.0,
                "normalize_output": False,
            },
            "song_parameters": {
                "clip_duration_min": 1.0,
                "clip_duration_max": 4.0,
                "distribution": "uniform",
                "chaos": 1.0,
            },
            "sound_parameters": {
                "clip_duration_min": 0.5,
                "clip_duration_max": 2.0,
                "distribution": "weighted",
                "chaos": 0.7,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["render_settings"]["target_duration_seconds"] == 8
    assert data["render_settings"]["song_gain_db"] == 2.5
    assert data["render_settings"]["sound_gain_db"] == -3.0
    assert data["render_settings"]["render_gain_db"] == 1.0
    assert data["render_settings"]["normalize_output"] is False
    assert data["song_parameters"]["clip_duration"]["min_seconds"] == 1.0
    assert data["sound_parameters"]["clip_duration"]["max_seconds"] == 2.0


def test_generate_reports_song_and_sound_clip_counts(tmp_path, monkeypatch):
    _configure_projects_root(tmp_path, monkeypatch)
    main._ensure_project_dirs(main._project_dir("layered-generate"))
    project = new_project("Layered Generate")
    main._set_song_assets(project, [_asset("song-a", "song_a")])
    main._set_sound_assets(project, [_asset("sound-a", "sound_a")])
    main._set_render_settings(
        project,
        {
            "target_duration_seconds": 6.0,
            "song_gain_db": 0.0,
            "sound_gain_db": 0.0,
            "render_gain_db": 0.0,
            "normalize_output": True,
        },
    )
    song_params = main._get_song_parameters(project)
    song_params.target_duration_seconds = 6.0
    song_params.clip_duration.min_seconds = 1.0
    song_params.clip_duration.max_seconds = 2.0
    main._set_song_parameters(project, song_params)
    sound_params = main._get_sound_parameters(project)
    sound_params.target_duration_seconds = 6.0
    sound_params.clip_duration.min_seconds = 0.5
    sound_params.clip_duration.max_seconds = 1.5
    main._set_sound_parameters(project, sound_params)
    main._save("layered-generate", project)

    client = TestClient(main.app)
    response = client.post("/api/projects/layered-generate/generate")

    assert response.status_code == 200
    data = response.json()
    assert data["song_clip_count"] > 0
    assert data["sound_clip_count"] > 0
    assert data["clip_count"] >= data["song_clip_count"] + data["sound_clip_count"]


def test_sound_overlay_does_not_require_filling_entire_target(tmp_path, monkeypatch):
    _configure_projects_root(tmp_path, monkeypatch)
    main._ensure_project_dirs(main._project_dir("overlay-feasibility"))
    project = new_project("Overlay Feasibility")
    main._set_song_assets(project, [_asset("song-a", "song_a", duration=20.0)])
    main._set_sound_assets(project, [_asset("sound-a", "sound_a", duration=1.2)])
    main._set_render_settings(
        project,
        {
            "target_duration_seconds": 18.0,
            "song_gain_db": 0.0,
            "sound_gain_db": 0.0,
            "render_gain_db": 0.0,
            "normalize_output": True,
        },
    )
    song_params = main._get_song_parameters(project)
    song_params.clip_duration.min_seconds = 4.0
    song_params.clip_duration.max_seconds = 6.0
    main._set_song_parameters(project, song_params)
    sound_params = main._get_sound_parameters(project)
    sound_params.clip_duration.min_seconds = 0.5
    sound_params.clip_duration.max_seconds = 1.0
    main._set_sound_parameters(project, sound_params)
    main._save("overlay-feasibility", project)

    client = TestClient(main.app)
    response = client.get("/api/projects/overlay-feasibility/feasibility")

    assert response.status_code == 200
    assert response.json()["feasible"] is True


def test_generate_merges_adjacent_silence_events(tmp_path, monkeypatch):
    _configure_projects_root(tmp_path, monkeypatch)
    main._ensure_project_dirs(main._project_dir("silence-merge"))
    project = new_project("Silence Merge")
    main._set_song_assets(project, [_asset("song-a", "song_a", duration=10.0)])
    main._set_sound_assets(project, [_asset("sound-a", "sound_a", duration=1.2)])
    main._set_render_settings(
        project,
        {
            "target_duration_seconds": 8.0,
            "song_gain_db": 0.0,
            "sound_gain_db": 0.0,
            "render_gain_db": 0.0,
            "normalize_output": True,
        },
    )
    song_params = main._get_song_parameters(project)
    song_params.clip_duration.min_seconds = 4.0
    song_params.clip_duration.max_seconds = 4.0
    song_params.crossfade.enabled = False
    song_params.silence.enabled = False
    song_params.duration_rule = "pad_silence"
    main._set_song_parameters(project, song_params)
    sound_params = main._get_sound_parameters(project)
    sound_params.clip_duration.min_seconds = 0.5
    sound_params.clip_duration.max_seconds = 1.0
    sound_params.duration_rule = "trim_last"
    main._set_sound_parameters(project, sound_params)
    main._save("silence-merge", project)

    client = TestClient(main.app)
    response = client.post("/api/projects/silence-merge/generate")

    assert response.status_code == 200
    timeline = client.get("/api/projects/silence-merge").json()["timeline"]["events"]
    for idx in range(1, len(timeline)):
        assert not (timeline[idx - 1]["type"] == "silence" and timeline[idx]["type"] == "silence")


def test_parameter_updates_only_invalidate_when_inputs_change(tmp_path, monkeypatch):
    _configure_projects_root(tmp_path, monkeypatch)
    project_id = "invalidation-test"
    project_dir = main._project_dir(project_id)
    main._ensure_project_dirs(project_dir)
    project = new_project("Invalidation Test")
    project.timeline = Timeline(
        events=[SilenceEvent(type="silence", position_seconds=0.0, duration_seconds=60.0)],
        total_duration_seconds=60.0,
    )
    main._save(project_id, project)
    (project_dir / "renders" / "latest.wav").write_bytes(b"render")
    client = TestClient(main.app)

    layer = {
        "clip_duration_min": 2.0,
        "clip_duration_max": 10.0,
        "distribution": "uniform",
        "chaos": 1.0,
    }
    unchanged = client.put(
        f"/api/projects/{project_id}/parameters",
        json={
            "render_settings": {
                "target_duration_seconds": 60.0,
                "song_gain_db": 0.0,
                "sound_gain_db": 0.0,
                "render_gain_db": 0.0,
                "normalize_output": True,
                "master_fade_in_seconds": 0.0,
                "master_fade_out_seconds": 0.0,
            },
            "song_parameters": layer,
            "sound_parameters": layer,
        },
    )

    assert unchanged.status_code == 200
    assert "timeline" in unchanged.json()
    assert unchanged.json()["has_render"] is True

    changed_layer = {**layer, "clip_duration_max": 9.0}
    changed = client.put(
        f"/api/projects/{project_id}/parameters",
        json={
            "render_settings": {
                "target_duration_seconds": 60.0,
                "song_gain_db": 0.0,
                "sound_gain_db": 0.0,
                "render_gain_db": 0.0,
                "normalize_output": True,
                "master_fade_in_seconds": 0.0,
                "master_fade_out_seconds": 0.0,
            },
            "song_parameters": changed_layer,
            "sound_parameters": layer,
        },
    )

    assert changed.status_code == 200
    assert "timeline" not in changed.json()
    assert changed.json()["has_render"] is False
