from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.services.modify_original_workspace_service import (
    ModifyOriginalWorkspacePreparationRequest,
    prepare_modify_original_workspace,
)


def _entry() -> ArchiveEntry:
    return ArchiveEntry(
        path="character/model/test/cd_test_sword_0001.pac",
        pamt_path=Path("C:/game/0009/0.pamt"),
        paz_file=Path("C:/game/0009/0.paz"),
        offset=4,
        comp_size=8,
        orig_size=12,
        flags=0,
        paz_index=0,
    )


def _request(tmp_path: Path, **overrides: object) -> ModifyOriginalWorkspacePreparationRequest:
    values: dict[str, object] = {
        "entry": _entry(),
        "workspace_dir": tmp_path / "session",
        "create_workspace": False,
        "include_family_files": False,
        "open_workspace_after_create": False,
        "cleanup_stale_sessions": True,
        "archive_entries_by_normalized_path": {},
        "archive_entries_by_basename": {},
        "model_texture_references": ("pac-graph",),
        "asset_family_graph": {"source": "cached-preview"},
    }
    values.update(overrides)
    return ModifyOriginalWorkspacePreparationRequest(**values)


def test_modify_original_preparation_service_is_the_exact_cancellable_clone_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cdmw.services.modify_original_workspace_service as service

    captured: dict[str, object] = {}
    obj_path = tmp_path / "session" / "clone.obj"
    scene_result = SimpleNamespace(mesh="imported-clone")
    original_mesh = SimpleNamespace(submeshes=("original",))

    def fake_export(entry: ArchiveEntry, output: Path, export_kind: str, **kwargs: object) -> object:
        captured.update(entry=entry, output=output, export_kind=export_kind, kwargs=kwargs)
        output.mkdir(parents=True, exist_ok=True)
        obj_path.write_text("o clone\n", encoding="utf-8")
        return SimpleNamespace(output_paths=(obj_path,), summary_lines=("clone exported",))

    monkeypatch.setattr(service, "export_archive_mesh", fake_export)
    monkeypatch.setattr(service, "import_scene_mesh_with_report", lambda path, stop_event: scene_result)
    monkeypatch.setattr(
        service,
        "read_archive_entry_baseline_data",
        lambda entry, read_entry_data: SimpleNamespace(data=b"mesh"),
    )
    monkeypatch.setattr(service, "parse_mesh", lambda data, path: original_mesh)
    cleanup_logs: list[object] = []
    progress: list[tuple[int, int, str]] = []

    result = prepare_modify_original_workspace(
        _request(tmp_path),
        log=lambda message: cleanup_logs.append(message),
        progress=lambda current, total, detail: progress.append((current, total, detail)),
        cleanup_stale_sessions=lambda emit: cleanup_logs.append(emit),
        collect_supplemental_files=lambda root, stop: (root / "clone.obj.meta.json",),
    )

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert captured["entry"] == _entry()
    assert captured["output"] == (tmp_path / "session").resolve()
    assert captured["export_kind"] == "obj"
    assert kwargs["resolve_skeleton_for_obj"] is False
    assert kwargs["model_texture_references"] == ("pac-graph",)
    assert kwargs["asset_family_graph"] == {"source": "cached-preview"}
    assert kwargs["build_preview_context"] is False
    assert result["scene_import_result"] is scene_result
    assert result["original_mesh"] is original_mesh
    assert result["supplemental_files"] == (
        (tmp_path / "session" / "clone.obj.meta.json").resolve(),
    )
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["workspace_mode"] == "internal_app_session"
    assert manifest["policy"] == "safe_clone_workspace_imports_through_mesh_replacement_geometry_path"
    assert progress[0][0] == 1 and progress[-1][0] == 5


def test_modify_original_preparation_service_honors_prestart_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cdmw.services.modify_original_workspace_service as service

    called = False

    def fake_export(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("cancelled preparation must not export")

    monkeypatch.setattr(service, "export_archive_mesh", fake_export)
    stop = threading.Event()
    stop.set()

    with pytest.raises(RunCancelled, match="Modify Original preparation cancelled"):
        prepare_modify_original_workspace(_request(tmp_path), stop_event=stop)
    assert called is False
