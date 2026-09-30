from __future__ import annotations

import copy
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from cdmw.domain.cancellation import RunCancelled
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services import mesh_rust_authoring as owner
from tests.test_mesh_dotnet_material_compiler import _mesh_with_layer_graph


def _mesh(root: Path, count: int = 4) -> ParsedMesh:
    parts = []
    for index in range(count):
        folder = root / f"input-{index}"
        folder.mkdir()
        part = _mesh_with_layer_graph(folder).submeshes[0]
        for image_path in folder.glob("*.png"):
            with Image.open(image_path) as image:
                image.resize((32, 32)).save(image_path.with_suffix(".dds"))
        part.name = part.material = f"Material-{index}"
        part.submesh_index = index
        part.material_slot_index = index
        part.preview_material_texture_inputs = tuple(
            replace(value, source_dds_path=str(Path(value.source_dds_path).with_suffix(".dds")),
                    **({"owner_slot_index": index} if value.owner_slot_index >= 0 else {}))
            for value in part.preview_material_texture_inputs
        )
        parts.append(part)
    return ParsedMesh(path="synthetic/parallel.pac", format="pac", submeshes=parts)


def _run(function, mesh, root, **kwargs):
    root.mkdir()
    state = owner._RustMaterialSynthesisState()
    result = function(mesh, root, expected_root_identity=owner._session_root_identity(root),
                      stop_event=kwargs.pop("stop_event", threading.Event()), synthesis_state=state, **kwargs)
    return {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in result.items()}, state


def test_parallel_preparation_preserves_bytes_lod_owners_protection_and_source(tmp_path):
    mesh = _mesh(tmp_path)
    mesh.lod_levels = [mesh.submeshes[:2], mesh.submeshes[2:]]
    original = copy.deepcopy(mesh)
    protected = frozenset({(1, 1, "base_color")})
    serial, serial_state = _run(owner._mesh_synthesized_texture_overrides_serial,
                                mesh, tmp_path / "serial", protected_keys=protected)
    parallel, parallel_state = _run(owner._mesh_synthesized_texture_overrides,
                                    mesh, tmp_path / "parallel", protected_keys=protected)
    assert len(parallel) == 3
    assert parallel == serial
    assert parallel_state == serial_state
    assert mesh == original
    assert (1, 1, "base_color") not in parallel


def test_parallel_preparation_retains_binding_owner_without_explicit_material_slot(tmp_path):
    mesh = _mesh(tmp_path, 2)
    for part in mesh.submeshes:
        del part.material_slot_index
    serial, serial_state = _run(owner._mesh_synthesized_texture_overrides_serial, mesh, tmp_path / "serial")
    parallel, parallel_state = _run(owner._mesh_synthesized_texture_overrides, mesh, tmp_path / "parallel")
    assert parallel == serial
    assert not serial_state.diagnostics
    assert parallel_state == serial_state


def test_parallel_work_keeps_one_ordered_preview_budget(tmp_path, monkeypatch):
    mesh = _mesh(tmp_path)
    order = []
    compile_ready = threading.Barrier(4, timeout=5)

    def serial(snapshot, root, *, synthesis_state, stop_event, **kwargs):
        index = int(snapshot.submeshes[0].name.rsplit("-", 1)[1])
        compile_ready.wait()
        synthesis_state.attempted = True
        owner._encode_rust_preview_dds(Path(str(index)), root / "result.dds", "base",
                                       stop_event, synthesis_state)
        return {}

    def encode(source, target, channel, stop_event, **kwargs):
        order.append((int(str(source)), kwargs["preview_uncompressed_max_bytes"]))
        return {"preview_uncompressed": kwargs["preview_uncompressed_max_bytes"] >= 4, "byte_count": 4}

    monkeypatch.setattr(owner, "_mesh_synthesized_texture_overrides_serial", serial)
    monkeypatch.setattr(owner, "_encode_owned_dds", encode)
    monkeypatch.setattr(owner.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(owner, "_RUST_FAST_PREVIEW_TEXTURE_BUDGET_BYTES", 12)
    _, state = _run(owner._mesh_synthesized_texture_overrides, mesh, tmp_path / "parallel")
    assert order == [(0, 12), (1, 8), (2, 4), (3, 0)]
    assert state.fast_preview_texture_bytes == 12


def test_cancel_wakes_encoding_waiter_and_joins_all_preparation(tmp_path, monkeypatch):
    mesh = _mesh(tmp_path, 2)
    stop = threading.Event()
    entered = threading.Event()
    finished = []

    def serial(snapshot, root, *, synthesis_state, stop_event, **kwargs):
        index = int(snapshot.submeshes[0].name.rsplit("-", 1)[1])
        try:
            if index == 0:
                assert entered.wait(5)
                stop.set()
                raise RunCancelled("cancel first")
            entered.set()
            owner._encode_rust_preview_dds(Path("source"), root / "result.dds", "base",
                                           stop_event, synthesis_state)
            pytest.fail("cancelled waiter reached encoding")
        finally:
            finished.append(index)

    monkeypatch.setattr(owner, "_mesh_synthesized_texture_overrides_serial", serial)
    monkeypatch.setattr(owner.os, "cpu_count", lambda: 4)
    with pytest.raises(owner.RustMeshCancellationError, match="cancelled"):
        _run(owner._mesh_synthesized_texture_overrides, mesh, tmp_path / "parallel", stop_event=stop)
    assert sorted(finished) == [0, 1]


def test_compiler_failure_discards_partial_results_and_joins_waiters(tmp_path, monkeypatch):
    mesh = _mesh(tmp_path, 2)
    finished = []
    ready = threading.Barrier(2, timeout=5)

    def serial(snapshot, root, *, synthesis_state, stop_event, **kwargs):
        index = int(snapshot.submeshes[0].name.rsplit("-", 1)[1])
        try:
            ready.wait()
            if index == 0:
                owner._record_rust_material_synthesis_diagnostic(synthesis_state, "compiler_failed",
                                                                lod_index=0, detail="test failure")
                return {}
            synthesis_state.generated_binding_count = 1
            synthesis_state.presentation_overrides[(0, 0)] = {"alpha_mode": "opaque"}
            return {(0, 0, "base_color"): root / "unused.dds"}
        finally:
            finished.append(index)

    monkeypatch.setattr(owner, "_mesh_synthesized_texture_overrides_serial", serial)
    monkeypatch.setattr(owner.os, "cpu_count", lambda: 4)
    outputs, state = _run(owner._mesh_synthesized_texture_overrides, mesh, tmp_path / "parallel")
    assert outputs == {}
    assert state.generated_binding_count == 0
    assert state.presentation_overrides == {}
    assert state.diagnostics[0]["code"] == "compiler_failed"
    assert sorted(finished) == [0, 1]


def test_large_sources_are_admitted_one_at_a_time(tmp_path, monkeypatch):
    mesh = _mesh(tmp_path)
    active = 0
    max_active = 0
    lock = threading.Lock()

    def serial(snapshot, root, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        threading.Event().wait(0.005)
        with lock:
            active -= 1
        return {}

    monkeypatch.setattr(owner, "_mesh_synthesized_texture_overrides_serial", serial)
    monkeypatch.setattr(owner, "_material_synthesis_working_bytes",
                        lambda _: owner._RUST_SYNTHESIS_WORKING_BYTES)
    _run(owner._mesh_synthesized_texture_overrides, mesh, tmp_path / "parallel")
    assert max_active == 1


def test_encoding_wait_cancellation_does_not_require_previous_owner_to_finish():
    stop = threading.Event()
    batch = owner._RustMaterialSynthesisBatch(owner._RustMaterialSynthesisState(), stop)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(batch.wait_for_encoding, 1)
        stop.set()
        with pytest.raises(RunCancelled):
            future.result(timeout=2)


def test_invalid_compiler_row_keeps_direct_fallback(tmp_path, monkeypatch):
    mesh = _mesh(tmp_path, 1)
    monkeypatch.setattr(owner, "compile_mesh_dotnet_material_manifest",
                        lambda *args, **kwargs: {"submeshes": [None]})
    outputs, state = _run(owner._mesh_synthesized_texture_overrides, mesh, tmp_path / "invalid")
    assert outputs == {}
    assert state.generated_binding_count == 0
    assert state.diagnostics[0]["code"] == "compiler_manifest_invalid"
