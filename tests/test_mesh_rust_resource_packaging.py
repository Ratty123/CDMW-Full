from __future__ import annotations

import copy
import hashlib
import json
import threading
from pathlib import Path

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services import mesh_rust_authoring as authoring
from cdmw.services import mesh_rust_preview_package as preview
from tests.test_rust_preview_production_cutover import _write_schema8_preview_core_fixture


def _geometry_source(tmp_path):
    source, geometry, identity, _ = _write_schema8_preview_core_fixture(tmp_path)
    manifest = json.loads((source / "manifest.json").read_text())
    batches = []
    for index in (4, 1, 9, 7, 2, 8, 3, 6, 5):
        batch = copy.deepcopy(manifest["batches"][0])
        batch["index"] = index
        batch["vertex_file"] = f"geometry-{index}.bin"
        batch["editor_identity"]["identity_file"] = f"identity-{index}.bin"
        (source / batch["vertex_file"]).write_bytes(geometry)
        (source / batch["editor_identity"]["identity_file"]).write_bytes(identity)
        batches.append(batch)
    manifest["batches"] = batches
    (source / "manifest.json").write_text(json.dumps(manifest))
    return source, batches, geometry, identity


def _texture_sources(tmp_path):
    sources, bindings = {}, {}
    for index in range(9):
        path = tmp_path / f"input-{index}.dds"
        path.write_bytes(b"DDS " + bytes([index]) * 128)
        sources[str(path)] = path
        bindings[(str(path), "base_color")] = [{index}, {0}]
    bindings[(str(next(iter(sources.values()))), "normal")] = [{1}, set()]
    return sources, bindings


def test_geometry_copies_overlap_and_preserve_bytes_order_and_owners(tmp_path, monkeypatch):
    source, batches, geometry, identity = _geometry_source(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    gate = threading.Barrier(4, timeout=5)
    original = preview._copy_preview_core_binary

    def copy_resource(*args, **kwargs):
        if kwargs["kind"] == "geometry" and kwargs["file_index"] < 4:
            gate.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(preview, "_copy_preview_core_binary", copy_resource)
    prepared, direct, parts = preview._copy_preview_core_geometry(
        batches, source, output, authoring._session_root_identity(output), None,
    )
    assert [row[0]["index"] for row in prepared] == [row["index"] for row in batches]
    assert [row["index"] for row in direct] == [row["index"] for row in batches]
    assert [row["scene_submesh_index"] for row in parts] == list(range(9))
    for row in direct:
        for role, data in (("vertices", geometry), ("identity", identity)):
            reference = row[role]
            assert (output / reference["path"]).read_bytes() == data
            assert reference["sha256"] == hashlib.sha256(data).hexdigest().upper()
    assert not list(output.glob("*.tmp"))


@pytest.mark.parametrize("failure", ("cancel", "copy"))
def test_geometry_failure_joins_workers_before_atomic_cleanup(tmp_path, monkeypatch, failure):
    source, *_ = _geometry_source(tmp_path)
    original = preview._copy_preview_core_binary
    gate = threading.Barrier(4, timeout=5)
    active = set()
    lock = threading.Lock()
    stop = threading.Event()

    def copy_resource(*args, **kwargs):
        if kwargs["kind"] != "geometry":
            return original(*args, **kwargs)
        index = kwargs["file_index"]
        with lock:
            active.add(index)
        try:
            gate.wait()
            if index == 0:
                if failure == "cancel":
                    stop.set()
                    raise RunCancelled("cancelled copy")
                raise OSError("failed copy")
            return original(*args, **kwargs)
        finally:
            with lock:
                active.remove(index)

    monkeypatch.setattr(preview, "_copy_preview_core_binary", copy_resource)
    destination = tmp_path / "failed-output"
    with pytest.raises(RunCancelled if failure == "cancel" else OSError):
        preview.build_rust_preview_package_from_preview_core(
            source, output_package_dir=destination, cancelled=stop.is_set,
        )
    assert not active
    assert not destination.exists()
    assert not list(tmp_path.glob(".rust-preview-*"))


def test_texture_copies_overlap_and_preserve_resources_lods_and_source(tmp_path, monkeypatch):
    sources, bindings = _texture_sources(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    original = authoring._atomic_copy_texture_payload
    gate = threading.Barrier(4, timeout=5)

    def copy_resource(*args, **kwargs):
        if args[2] < 4:
            gate.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(authoring, "_atomic_copy_texture_payload", copy_resource)
    resources = authoring._publish_rust_texture_resources(
        output, bindings, sources, None, authoring._session_root_identity(output),
    )
    assert len(resources) == 10
    assert len(list(output.glob("*.dds"))) == 9
    for resource, ((path_text, role), owners) in zip(
        resources, sorted(bindings.items(), key=lambda item: (item[0][1], item[0][0].casefold())),
    ):
        data = sources[path_text].read_bytes()
        assert (output / resource["file"]["path"]).read_bytes() == data
        assert resource["file"]["sha256"] == hashlib.sha256(data).hexdigest().upper()
        assert resource["role"] == role
        assert resource["material_indices_by_lod"] == [sorted(row) for row in owners]


def test_texture_batch_reserves_all_bytes_before_copying(tmp_path, monkeypatch):
    sources, bindings = _texture_sources(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(authoring, "_SESSION_MAX_TOTAL_BYTES", 9 * 132 - 1)

    def no_copy(*args, **kwargs):
        pytest.fail("Over-budget batches must fail before starting copy workers")

    monkeypatch.setattr(authoring, "_atomic_copy_texture_payload", no_copy)
    with pytest.raises(authoring.RustMeshProtocolError, match="aggregate limit"):
        authoring._publish_rust_texture_resources(
            output, bindings, sources, None, authoring._session_root_identity(output),
        )
    assert not list(output.iterdir())


@pytest.mark.parametrize("failure", ("cancel", "copy"))
def test_texture_failure_joins_workers_and_stops_later_batches(tmp_path, monkeypatch, failure):
    sources, bindings = _texture_sources(tmp_path)
    original_bytes = {path: path.read_bytes() for path in sources.values()}
    output = tmp_path / "output"
    output.mkdir()
    original = authoring._atomic_copy_texture_payload
    gate = threading.Barrier(4, timeout=5)
    active, started = set(), set()
    lock = threading.Lock()
    stop = threading.Event()

    def copy_resource(*args, **kwargs):
        index = args[2]
        with lock:
            active.add(index)
            started.add(index)
        try:
            gate.wait()
            if index == 0:
                if failure == "cancel":
                    stop.set()
                    raise authoring.RustMeshCancellationError("cancelled copy")
                raise OSError("failed copy")
            return original(*args, **kwargs)
        finally:
            with lock:
                active.remove(index)

    monkeypatch.setattr(authoring, "_atomic_copy_texture_payload", copy_resource)
    error = authoring.RustMeshCancellationError if failure == "cancel" else OSError
    with pytest.raises(error):
        authoring._publish_rust_texture_resources(
            output, bindings, sources, stop, authoring._session_root_identity(output),
        )
    assert not active
    assert started == set(range(4))
    assert not list(output.glob("*.tmp"))
    assert {path: path.read_bytes() for path in sources.values()} == original_bytes


def test_texture_source_changed_after_admission_is_rejected(tmp_path):
    source = tmp_path / "input.dds"
    source.write_bytes(b"DDS original")
    stat = source.stat()
    identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    source.write_bytes(b"DDS changed and larger")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(authoring.RustMeshProtocolError, match="texture changed"):
        authoring._atomic_copy_texture_payload(
            output, source, 0, expected_root_identity=authoring._session_root_identity(output),
            expected_source_identity=identity,
        )
    assert not list(output.iterdir())


def test_texture_growth_during_copy_cannot_write_beyond_reserved_bytes(tmp_path, monkeypatch):
    source = tmp_path / "input.dds"
    source.write_bytes(b"DDS " + b"X" * (1024 * 1024 - 4))
    stat = source.stat()
    identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    output = tmp_path / "output"
    output.mkdir()
    original_open = Path.open
    written = 0

    class TrackedStream:
        def __init__(self, stream):
            self.stream = stream
            self.grown = False

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size):
            data = self.stream.read(size)
            if not self.grown:
                with original_open(source, "ab") as appender:
                    appender.write(b"X")
                self.grown = True
            return data

        def write(self, data):
            nonlocal written
            written += len(data)
            assert written <= identity[2], "Copy wrote beyond reserved source bytes"
            return self.stream.write(data)

    def tracked_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return TrackedStream(stream) if path == source or path.parent == output else stream

    monkeypatch.setattr(Path, "open", tracked_open)
    with pytest.raises(authoring.RustMeshProtocolError, match="texture changed"):
        authoring._atomic_copy_texture_payload(
            output, source, 0, expected_root_identity=authoring._session_root_identity(output),
            expected_source_identity=identity,
        )
    assert written == identity[2]
    assert not list(output.iterdir())
