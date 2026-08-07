from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from cdmw.models import ArchiveEntry
from cdmw.services import modify_original_workspace_service as workspace_service
from cdmw.services.modify_original_workspace_service import (
    ModifyOriginalWorkspacePreparationRequest,
    discover_modify_original_drafts,
    prepare_modify_original_workspace,
)


def _entry() -> ArchiveEntry:
    return ArchiveEntry(
        path="character/model/test/source.pac",
        pamt_path=Path("0009/0.pamt"),
        paz_file=Path("0009/0.paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def _draft(
    root: Path,
    name: str,
    source_hash: str,
    *,
    mode: str = "persistent_app_draft",
    updated_at: float = 1.0,
) -> Path:
    workspace = root / name
    workspace.mkdir(parents=True)
    obj_path = workspace / "editable.obj"
    obj_path.write_text("# synthetic draft\n", encoding="utf-8")
    project_path = workspace / "mesh_layers" / "mesh_layer_project.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text('{"format":"mesh_layer_project_v1"}', encoding="utf-8")
    manifest_path = workspace / "modify_original_workspace.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "cdmw_modify_original_workspace_v1",
                "workspace_mode": mode,
                "source_asset_sha256": source_hash,
                "editable_obj": str(obj_path),
                "mesh_layer_project": str(project_path),
                "updated_at": updated_at,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_draft_discovery_requires_exact_fingerprint_and_defaults_newest(tmp_path: Path) -> None:
    source_hash = "a" * 64
    older = _draft(tmp_path, "older", source_hash, updated_at=10.0)
    newest = _draft(tmp_path, "newest", source_hash, updated_at=20.0)
    _draft(tmp_path, "wrong-source", "b" * 64, updated_at=30.0)
    _draft(tmp_path, "temporary", source_hash, mode="internal_app_session", updated_at=40.0)

    drafts = discover_modify_original_drafts(tmp_path, source_hash)

    assert [item.manifest_path for item in drafts] == [newest.resolve(), older.resolve()]
    assert all(item.source_asset_sha256 == source_hash for item in drafts)


def test_resume_uses_existing_draft_without_reexport_or_manifest_rewrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_data = b"exact synthetic source asset"
    source_hash = hashlib.sha256(source_data).hexdigest()
    manifest_path = _draft(tmp_path, "resume-me", source_hash, updated_at=20.0)
    manifest_before = manifest_path.read_bytes()
    scene_result = object()
    original_mesh = object()
    monkeypatch.setattr(workspace_service, "import_scene_mesh_with_report", lambda *_a, **_k: scene_result)
    monkeypatch.setattr(workspace_service, "parse_mesh", lambda *_a, **_k: original_mesh)
    monkeypatch.setattr(
        workspace_service,
        "export_archive_mesh",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("resume must not re-export")),
    )
    request = ModifyOriginalWorkspacePreparationRequest(
        entry=_entry(),
        workspace_dir=manifest_path.parent,
        create_workspace=False,
        include_family_files=False,
        open_workspace_after_create=False,
        cleanup_stale_sessions=False,
        archive_entries_by_normalized_path={},
        archive_entries_by_basename={},
        source_asset_data=source_data,
        source_asset_sha256=source_hash,
        resume_manifest_path=manifest_path,
    )

    result = prepare_modify_original_workspace(
        request,
        stop_event=threading.Event(),
    )

    assert result["resumed_draft"] is True
    assert result["scene_import_result"] is scene_result
    assert result["original_mesh"] is original_mesh
    assert result["mesh_layer_project_path"] == manifest_path.parent / "mesh_layers" / "mesh_layer_project.json"
    assert result["readme_path"] is None
    assert manifest_path.read_bytes() == manifest_before


def test_resume_rejects_incompatible_source_without_touching_draft(tmp_path: Path) -> None:
    source_data = b"different exact source"
    source_hash = hashlib.sha256(source_data).hexdigest()
    manifest_path = _draft(tmp_path, "incompatible", "c" * 64)
    before = manifest_path.read_bytes()
    request = ModifyOriginalWorkspacePreparationRequest(
        entry=_entry(),
        workspace_dir=manifest_path.parent,
        create_workspace=False,
        include_family_files=False,
        open_workspace_after_create=False,
        cleanup_stale_sessions=False,
        archive_entries_by_normalized_path={},
        archive_entries_by_basename={},
        source_asset_data=source_data,
        source_asset_sha256=source_hash,
        resume_manifest_path=manifest_path,
    )

    try:
        prepare_modify_original_workspace(request)
    except ValueError as exc:
        assert "different source asset" in str(exc)
    else:
        raise AssertionError("incompatible draft was accepted")
    assert manifest_path.read_bytes() == before
