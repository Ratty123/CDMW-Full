from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cdmw.core import texture_editor_project_io as project_io
from cdmw.models import (
    TextureEditorDocument,
    TextureEditorFloatingSelection,
    TextureEditorLayer,
    TextureEditorSourceBinding,
)


def _pixels(value: int) -> np.ndarray:
    return np.full((2, 3, 4), value, dtype=np.uint8)


def _layer(layer_id: str, name: str, *, mask_layer_id: str = "") -> TextureEditorLayer:
    return TextureEditorLayer(layer_id, name, "unused.png", mask_layer_id=mask_layer_id)


def _document(*layers: TextureEditorLayer, title: str = "Project") -> TextureEditorDocument:
    return TextureEditorDocument(
        title,
        3,
        2,
        active_layer_id=layers[0].layer_id,
        layers=layers,
    )


def _saved_bytes(project_path: Path) -> tuple[bytes, dict[str, bytes]]:
    assets_dir = project_io._texture_editor_assets_dir(project_path)
    return project_path.read_bytes(), {
        path.relative_to(assets_dir).as_posix(): path.read_bytes()
        for path in assets_dir.rglob("*")
        if path.is_file()
    }


def _assert_no_transaction_paths(project_path: Path) -> None:
    assets_dir = project_io._texture_editor_assets_dir(project_path)
    assert not list(project_path.parent.glob(f".{project_path.name}.*"))
    assert not list(project_path.parent.glob(f".{assets_dir.name}.*"))


def test_save_replaces_complete_project_and_removes_stale_assets(tmp_path: Path) -> None:
    project_path = tmp_path / "project.ctfedit.json"
    base = _layer("base", "Base", mask_layer_id="mask")
    stale = _layer("stale", "Stale")
    first = _document(base, stale)
    first.floating_selection = TextureEditorFloatingSelection(source_layer_id="base", bounds=(0, 0, 1, 1))
    project_io.save_texture_editor_project(
        first,
        {"base": _pixels(10), "mask": _pixels(20), "stale": _pixels(30)},
        project_path,
        floating_pixels=_pixels(40),
    )

    current = _layer("current", "Current")
    saved = project_io.save_texture_editor_project(
        _document(current, title="Current Project"),
        {"current": _pixels(90)},
        project_path,
    )

    loaded, loaded_pixels, floating_pixels = project_io.load_texture_editor_project(project_path)
    assets = _saved_bytes(project_path)[1]
    assert saved.project_path == project_path.resolve()
    assert loaded.title == "Current Project"
    assert [layer.layer_id for layer in loaded.layers] == ["current"]
    np.testing.assert_array_equal(loaded_pixels["current"], _pixels(90))
    assert floating_pixels is None
    assert len(assets) == 1
    assert next(iter(assets)).startswith("layers/")
    _assert_no_transaction_paths(project_path)


def test_staging_write_failure_leaves_previous_project_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "project.ctfedit.json"
    old = _layer("old", "Old")
    project_io.save_texture_editor_project(_document(old), {"old": _pixels(7)}, project_path)
    before = _saved_bytes(project_path)
    real_save_png = project_io.save_rgba_array_png
    calls = 0

    def fail_second_png(pixels: np.ndarray, output_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected PNG write failure")
        real_save_png(pixels, output_path)

    monkeypatch.setattr(project_io, "save_rgba_array_png", fail_second_png)
    first = _layer("first", "First")
    second = _layer("second", "Second")
    with pytest.raises(OSError, match="injected PNG write failure"):
        project_io.save_texture_editor_project(
            _document(first, second),
            {"first": _pixels(11), "second": _pixels(12)},
            project_path,
        )

    assert _saved_bytes(project_path) == before
    loaded, loaded_pixels, _floating = project_io.load_texture_editor_project(project_path)
    assert [layer.layer_id for layer in loaded.layers] == ["old"]
    np.testing.assert_array_equal(loaded_pixels["old"], _pixels(7))
    _assert_no_transaction_paths(project_path)


def test_publish_interruption_rolls_back_to_previous_readable_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "project.ctfedit.json"
    old = _layer("old", "Old")
    project_io.save_texture_editor_project(_document(old), {"old": _pixels(17)}, project_path)
    before = _saved_bytes(project_path)
    real_replace = project_io._replace_path
    interrupted = False

    def interrupt_after_project_publish(source: Path, destination: Path) -> None:
        nonlocal interrupted
        real_replace(source, destination)
        if not interrupted and destination == project_path.resolve() and source.name.endswith(".tmp.json"):
            interrupted = True
            raise KeyboardInterrupt("injected publish interruption")

    monkeypatch.setattr(project_io, "_replace_path", interrupt_after_project_publish)
    new = _layer("new", "New")
    with pytest.raises(KeyboardInterrupt, match="injected publish interruption"):
        project_io.save_texture_editor_project(_document(new), {"new": _pixels(99)}, project_path)

    assert interrupted
    assert _saved_bytes(project_path) == before
    loaded, loaded_pixels, _floating = project_io.load_texture_editor_project(project_path)
    assert [layer.layer_id for layer in loaded.layers] == ["old"]
    np.testing.assert_array_equal(loaded_pixels["old"], _pixels(17))
    _assert_no_transaction_paths(project_path)


def test_project_round_trip_preserves_typed_mesh_source_binding(tmp_path: Path) -> None:
    project_path = tmp_path / "linked.ctfedit.json"
    layer = _layer("base", "Base")
    document = _document(layer)
    document.source_binding = TextureEditorSourceBinding(
        launch_origin="mesh_editor",
        source_identity_path="session:2:body.dds",
        mesh_session_id="session",
        mesh_resource_id="body_base",
        mesh_submesh_indices=(2, 4),
        mesh_channel="base",
        mesh_commit_mode="preview",
    )

    project_io.save_texture_editor_project(document, {"base": _pixels(23)}, project_path)
    loaded, _pixels_by_layer, _floating = project_io.load_texture_editor_project(project_path)

    assert loaded.source_binding.mesh_session_id == "session"
    assert loaded.source_binding.mesh_resource_id == "body_base"
    assert loaded.source_binding.mesh_submesh_indices == (2, 4)
    assert loaded.source_binding.mesh_channel == "base"
    assert loaded.source_binding.mesh_commit_mode == "preview"
