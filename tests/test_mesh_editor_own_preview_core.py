"""The Mesh Editor builds its own Preview Core package when Browse hands it none.

Without one, the editor's resolver fed every tiled fabric layer to the CPU bake, which
flattened a part's damask and lace into one 256 px map (Demenissian Council Robes,
2026-11-23).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.ui.mesh_editor.tab_archive_material_context import (
    MeshEditorArchiveMaterialContextMixin,
)
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveMaterialContextWorker
from tests.test_mesh_rust_archive_texture_launch import (
    _canonical_rust_package,
    _entry,
    _Lease,
)


def _conserved(native: Path) -> Path:
    """Give the fixture package what a drawable Preview Core graph declares."""
    path = native / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(schema_version=8, material_graph_version=5, material_semantics_version=10,
                    material_conservation={"conserved": True}, normalization_center=[0.0, 0.0, 0.0],
                    normalization_scale=1.0, format="pac")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return native


def _dependencies(entry):
    return SimpleNamespace(selected_entry=entry, remote=True, entries=(entry,),
                           entry_matching=lambda selected: entry if selected is entry else None)


def _run(worker, *, job, python_route=None):
    contexts, errors = [], []
    worker.context_resolved.connect(lambda _request, context: contexts.append(context))
    worker.error.connect(lambda _request, message: errors.append(message))
    lease = _Lease()
    with patch("cdmw.services.mesh_preview_material_source.run_preview_core_job_for_context", side_effect=job), patch(
        "cdmw.workers.mesh_editor_aux_workers.build_archive_preview_result",
        side_effect=python_route or AssertionError("the archive resolver must not run"),
    ), patch("cdmw.workers.mesh_editor_aux_workers.acquire_dotnet_preview_package_cache_lease_for_path",
             return_value=lease):
        worker.run()
    return contexts, errors, lease


def test_without_browses_package_the_editor_builds_its_own_preview_core_package(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    _rust, native = _canonical_rust_package(tmp_path, entry)
    _conserved(native)
    jobs = []

    def job(selected, context, cache_root, stop_event):
        jobs.append((selected, cache_root))
        return SimpleNamespace(succeeded=True, package_path=str(native))

    worker = MeshArchiveMaterialContextWorker(7, entry, native_dependencies=_dependencies(entry),
                                              native_cache_root=tmp_path / "native")
    contexts, errors, lease = _run(worker, job=job)
    assert errors == [] and jobs == [(entry, tmp_path / "native")]
    assert len(contexts) == 1 and contexts[0].material_package_path == str(native)
    assert contexts[0].material_package_lease is lease
    contexts[0].release()
    assert not lease.active


@pytest.mark.parametrize("outcome", ["failed", "unconserved", "raised"])
def test_a_build_that_cannot_be_drawn_falls_back_to_the_archive_resolver(tmp_path: Path, outcome: str) -> None:
    entry = _entry(tmp_path)
    _rust, native = _canonical_rust_package(tmp_path, entry)
    if outcome != "unconserved":
        _conserved(native)

    def job(*_args):
        if outcome == "raised":
            raise RuntimeError("helper crashed")
        return SimpleNamespace(succeeded=outcome != "failed", package_path=str(native))

    worker = MeshArchiveMaterialContextWorker(7, entry, native_dependencies=_dependencies(entry),
                                              native_cache_root=tmp_path / "native")
    contexts, errors, _lease = _run(worker, job=job, python_route=RuntimeError("archive resolver ran"))
    # The old route runs (here it fails loudly, which proves it was reached).
    assert contexts == [] and errors == ["RuntimeError: archive resolver ran"]
    assert worker.material_package_path is None


def test_without_the_opens_dependencies_no_build_runs(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    worker = MeshArchiveMaterialContextWorker(7, entry)  # attach_archive_refit_materials builds it like this
    contexts, errors, _lease = _run(worker, job=AssertionError("no build without dependencies"),
                                    python_route=RuntimeError("archive resolver ran"))
    assert contexts == [] and errors == ["RuntimeError: archive resolver ran"]


def test_a_stop_during_the_build_publishes_nothing(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    _rust, native = _canonical_rust_package(tmp_path, entry)
    _conserved(native)
    worker = MeshArchiveMaterialContextWorker(7, entry, native_dependencies=_dependencies(entry),
                                              native_cache_root=tmp_path / "native")

    def job(*_args):
        worker.stop()
        return SimpleNamespace(succeeded=True, package_path=str(native))

    contexts, errors, _lease = _run(worker, job=job)
    assert contexts == [] and errors == []


@pytest.mark.parametrize("case", ["single_file", "item_set", "not_remote", "other_entry", "no_context"])
def test_the_tab_asks_for_a_build_only_for_a_single_file_catalogue_open(tmp_path: Path, case: str) -> None:
    entry = _entry(tmp_path)
    sessions = tmp_path / "cache" / "mesh_editor_sessions"
    dependencies = _dependencies(_entry(tmp_path, "other.pac", offset=8) if case == "other_entry" else entry)
    if case == "not_remote":
        dependencies.remote = False
    tab = SimpleNamespace(
        archive_session_dependencies=None if case == "no_context" else dependencies,
        item_set_contexts=(dependencies,) if case == "item_set" else (),
        standalone_rust_owned_root=sessions,
    )
    found, cache_root = MeshEditorArchiveMaterialContextMixin._own_preview_core_build_inputs(tab, entry)
    if case == "single_file":
        assert found is dependencies and cache_root == sessions / "item-set-native-cache"
    else:
        assert found is None and cache_root is None


@pytest.mark.parametrize("megabytes, maps", [(10, True), (17, False)])
def test_a_large_set_piece_manifest_still_maps_its_rust_preview_to_the_package(tmp_path: Path, megabytes: int,
                                                                               maps: bool) -> None:
    """The robe's Preview Core manifest is 10.3 MB. Capped at 8 MiB, the Rust preview never
    led back to it, so set opens never got Browse's set package (2026-11-23)."""
    from cdmw.services.mesh_rust_preview_cache import (
        native_material_package_for_rust_preview,
    )

    entry = _entry(tmp_path)
    rust, native = _canonical_rust_package(tmp_path, entry)
    path = native / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["padding"] = "x" * (megabytes * 1024 * 1024)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert native_material_package_for_rust_preview(rust) == (native.resolve() if maps else None)


@pytest.mark.parametrize("asked, expected", [(2048, 2048), (0, 0)], ids=["editor_tab", "archive_refit"])
def test_the_resolver_prepares_support_maps_at_the_size_it_was_given(tmp_path: Path, asked: int,
                                                                    expected: int) -> None:
    """The editor tab asks for its synthesis size (at the shared 256 px every part came out as
    one 256 px map); Archive Refit's use of the same worker keeps the shared size (0)."""
    entry = _entry(tmp_path)
    calls = []

    def builder(*_args, **kwargs):
        calls.append(kwargs.get("support_texture_max_dimension"))
        raise RuntimeError("stop after the call")

    worker = MeshArchiveMaterialContextWorker(7, entry, support_texture_max_dimension=asked)
    with patch("cdmw.workers.mesh_editor_aux_workers.build_archive_preview_result", side_effect=builder):
        worker.run()
    assert calls == [expected]


def test_the_editor_tab_asks_for_its_synthesis_size() -> None:
    from cdmw.services.mesh_rust_authoring import _synthesis_max_dimension
    from cdmw.ui.mesh_editor.tab_archive_material_context import (
        _editor_support_map_dimension,
    )

    assert _editor_support_map_dimension() == _synthesis_max_dimension() > 256


def test_the_support_size_override_falls_back_to_the_shared_setting() -> None:
    from cdmw.core import archive_model_texture_config as config
    from cdmw.core.archive_model_texture_support_attach import _support_dimension

    assert _support_dimension(SimpleNamespace(support_max_dimension=2048)) == 2048
    assert _support_dimension(SimpleNamespace(support_max_dimension=0)) == int(
        config.MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)
