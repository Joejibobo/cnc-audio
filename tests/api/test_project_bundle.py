import io
import zipfile

from fastapi.testclient import TestClient

from packages.api import main
from packages.engine.models import Asset
from packages.engine.project import new_project


def _configure_projects_root(tmp_path, monkeypatch):
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    monkeypatch.setattr(main, "PROJECTS_DIR", projects_root)
    return projects_root


def _build_source_project(project_id: str):
    project_dir = main._project_dir(project_id)
    main._ensure_project_dirs(project_dir)

    project = new_project("Bundle Test")
    project.assets = [
        Asset(
            id="asset-a",
            name="clip_a",
            path="assets/asset-a_original.wav",
            hash="sha256:test",
            duration_seconds=1.25,
            format="wav",
        )
    ]
    main._save(project_id, project)

    (project_dir / "assets" / "asset-a_original.wav").write_bytes(b"original-audio")
    (project_dir / "assets" / "asset-a.wav").write_bytes(b"converted-wav")
    (project_dir / "renders" / "latest.wav").write_bytes(b"latest-render")
    (project_dir / "downloads" / "Bundle Test.wav").write_bytes(b"named-download")


def test_export_project_bundle_includes_project_assets_and_renders(tmp_path, monkeypatch):
    _configure_projects_root(tmp_path, monkeypatch)
    _build_source_project("source-project")
    client = TestClient(main.app)

    response = client.get("/api/projects/source-project/export")

    assert response.status_code == 200
    assert "Bundle%20Test.cncaudio.zip" in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        members = set(archive.namelist())

    assert "project.cnc" in members
    assert "assets/asset-a_original.wav" in members
    assert "assets/asset-a.wav" in members
    assert "renders/latest.wav" in members
    assert "downloads/Bundle Test.wav" in members


def test_import_project_bundle_restores_project_state(tmp_path, monkeypatch):
    _configure_projects_root(tmp_path, monkeypatch)
    _build_source_project("source-project")
    client = TestClient(main.app)

    export_response = client.get("/api/projects/source-project/export")
    import_response = client.post(
        "/api/projects/import",
        files={"file": ("Bundle Test.cncaudio.zip", export_response.content, "application/zip")},
    )

    assert import_response.status_code == 200
    data = import_response.json()
    assert data["project"]["name"] == "Bundle Test"
    assert len(data["assets"]) == 1
    assert data["has_render"] is True

    imported_id = data["id"]
    imported_dir = main._project_dir(imported_id)
    assert (imported_dir / "project.cnc").exists()
    assert (imported_dir / "assets" / "asset-a_original.wav").exists()
    assert (imported_dir / "assets" / "asset-a.wav").exists()
    assert (imported_dir / "renders" / "latest.wav").exists()
    assert (imported_dir / "downloads" / "Bundle Test.wav").exists()


def test_import_project_bundle_requires_project_file(tmp_path, monkeypatch):
    _configure_projects_root(tmp_path, monkeypatch)
    client = TestClient(main.app)

    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("assets/clip.wav", b"wav-data")

    response = client.post(
        "/api/projects/import",
        files={"file": ("broken.cncaudio.zip", bundle.getvalue(), "application/zip")},
    )

    assert response.status_code == 422
    assert "project.cnc" in response.json()["detail"]
