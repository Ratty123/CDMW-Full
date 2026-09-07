"""Regressions for archive conversion fidelity and complete selected output."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core import archive_mesh_export
from cdmw.core.archive_extraction import count_existing_archive_targets, extract_archive_entries
from cdmw.core.character_appearance_bundle import load_character_appearance_bundle_index
from cdmw.core.common import RunCancelled
from cdmw.domain.archives.mesh_contracts import MeshExportResult
from cdmw.domain.archives.relationships import CharacterDependencyPlan
from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_pamlod
from cdmw.ui.archive_browser.character_dependency_export import ArchiveCharacterDependencyExportMixin


def _entry(root: Path, path: str, payload: bytes = b"payload", group: str = "0009") -> ArchiveEntry:
    source = root / "source" / group
    source.mkdir(parents=True, exist_ok=True)
    paz = source / (Path(path).name + ".paz")
    paz.write_bytes(payload)
    return ArchiveEntry(
        path=path, pamt_path=source / "0.pamt", paz_file=paz,
        offset=0, comp_size=len(payload), orig_size=len(payload), flags=0, paz_index=0,
    )


@pytest.fixture
def mesh() -> ParsedMesh:
    part = SubMesh(
        name="surface", material="stone", texture="stone.dds",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], faces=[(0, 1, 2)],
        vertex_count=3, face_count=1,
    )
    result = ParsedMesh(
        path="object/mesh.pam", format="pam", submeshes=[part],
        total_vertices=3, total_faces=1, has_uvs=True,
    )
    result._cdmw_original_data = b"original mesh bytes"
    return result


@pytest.mark.parametrize("export_format", ["obj", "fbx"])
def test_partial_archive_mesh_is_rejected_before_parsing(tmp_path, monkeypatch, export_format):
    entry = _entry(tmp_path, "object/partial.pam")
    monkeypatch.setattr(
        "cdmw.core.archive_extraction.read_archive_entry_data",
        lambda *args, **kwargs: (b"incomplete", False, "PartialRaw"),
    )
    monkeypatch.setattr(archive_mesh_export, "parse_mesh", lambda *args: pytest.fail("partial mesh parsed"))
    output = tmp_path / "export"
    output.mkdir()
    previous = output / ("partial." + export_format)
    previous.write_bytes(b"previous export")
    with pytest.raises(ValueError, match="incomplete mesh data.*PartialRaw"):
        archive_mesh_export.export_archive_mesh(entry, output, export_format)
    assert previous.read_bytes() == b"previous export"
    assert list(output.iterdir()) == [previous]


def test_pamlod_retains_each_material_and_local_triangle_indices():
    table = 0x50
    record_size = 0x210
    geometry = table + 2 * record_size
    data = bytearray(geometry + 6 * 6 + 6 * 2)
    struct.pack_into("<II", data, 0, 1, geometry)
    struct.pack_into("<ffffff", data, 0x10, 0, 0, 0, 1, 1, 1)
    for index, name in enumerate((b"stone", b"wood")):
        record = table + index * record_size
        struct.pack_into("<IIII", data, record, 3, 3, index * 3, index * 3)
        texture = name + b".dds\0"
        data[record + 16:record + 16 + len(texture)] = texture
        data[record + 0x110:record + 0x110 + len(name)] = name
        for vertex, xyz in enumerate(((0, 0, index * 65535), (65535, 0, 0), (0, 65535, 0))):
            struct.pack_into("<HHH", data, geometry + (index * 3 + vertex) * 6, *xyz)
    struct.pack_into("<HHHHHH", data, geometry + 36, 0, 1, 2, 2, 1, 0)

    parsed = parse_pamlod(bytes(data), "object/two_materials.pamlod")

    assert [part.material for part in parsed.submeshes] == ["stone", "wood"]
    assert [part.texture for part in parsed.submeshes] == ["stone.dds", "wood.dds"]
    assert [part.faces for part in parsed.submeshes] == [[(0, 1, 2)], [(2, 1, 0)]]
    assert parsed.total_vertices == 6 and parsed.total_faces == 2
    assert parsed.lod_levels == [parsed.submeshes]
    assert parsed.submeshes[1].source_vertex_offsets == [geometry + 18, geometry + 24, geometry + 30]


@pytest.mark.parametrize("resolve_appearance", [True, False])
def test_character_obj_uses_neutral_appearance_but_internal_edit_keeps_source(
    tmp_path, monkeypatch, mesh, resolve_appearance,
):
    entry = _entry(tmp_path, "character/model/head.pac")
    mesh.path, mesh.format = entry.path, "pac"
    corrected = copy.deepcopy(mesh)
    corrected.submeshes[0].vertices[0] = (0.0, 0.0, 0.25)
    monkeypatch.setattr(archive_mesh_export, "_parse_archive_mesh", lambda *args, **kwargs: mesh)
    monkeypatch.setattr(archive_mesh_export, "_find_matching_skeleton_entry", lambda *args, **kwargs: (None, "", (), None))
    applied = []

    def appearance(*args, **kwargs):
        applied.append(True)
        return corrected, ("Applied test appearance",)

    monkeypatch.setattr("cdmw.core.archive_mesh_appearance.apply_archive_mesh_appearance", appearance)
    output = tmp_path / "export"
    result = archive_mesh_export.export_archive_mesh(
        entry, output, "obj", resolve_skeleton_for_obj=resolve_appearance, build_preview_context=False,
    )
    obj = output / "head.obj"
    vertices = [tuple(map(float, row.split()[1:])) for row in obj.read_text().splitlines() if row.startswith("v ")]
    assert vertices == (corrected if resolve_appearance else mesh).submeshes[0].vertices
    assert bool(applied) == resolve_appearance
    assert mesh.submeshes[0].vertices[0] == (0.0, 0.0, 0.0)
    manifest = json.loads(obj.with_suffix(".obj.meta.json").read_text())
    assert bool(manifest["allowed_edit_operations"]) != resolve_appearance
    assert manifest["import_rules"]["allow_position_edit"] != resolve_appearance
    assert all(path.is_file() and path.parent == output for path in result.output_paths)
    if resolve_appearance:
        with pytest.raises(ValueError, match="not allowed|not permitted|disallow"):
            import_obj(str(obj))
    else:
        assert import_obj(str(obj)).total_vertices == 3


@pytest.mark.parametrize("failure_stage", ["companion", "manifest", "cancel"])
def test_failed_export_preserves_previous_output(tmp_path, monkeypatch, mesh, failure_stage):
    entry = _entry(tmp_path, "object/mesh.pam")
    companion = _entry(tmp_path, "object/mesh.pamlod")
    output = tmp_path / "export"
    output.mkdir()
    for name in ("mesh.obj", "mesh.mtl", "mesh.obj.meta.json"):
        (output / name).write_bytes(b"previous " + name.encode())
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    stop_event = threading.Event()
    monkeypatch.setattr(archive_mesh_export, "_parse_archive_mesh", lambda *args, **kwargs: mesh)

    if failure_stage == "companion":
        def fail_copy(*args, **kwargs):
            raise OSError("selected companion unavailable")
        monkeypatch.setattr("cdmw.core.archive_extraction.extract_archive_entry", fail_copy)
    elif failure_stage == "manifest":
        def fail_manifest(*args, **kwargs):
            raise OSError("manifest unavailable")
        monkeypatch.setattr(archive_mesh_export, "write_roundtrip_manifest", fail_manifest)
    else:
        write_manifest = archive_mesh_export.write_roundtrip_manifest

        def cancel_before_publication(*args, **kwargs):
            result = write_manifest(*args, **kwargs)
            stop_event.set()
            return result
        monkeypatch.setattr(archive_mesh_export, "write_roundtrip_manifest", cancel_before_publication)

    expected_error = RunCancelled if failure_stage == "cancel" else RuntimeError
    with pytest.raises(expected_error):
        archive_mesh_export.export_archive_mesh(
            entry, output, "obj", related_entries=(companion,), build_preview_context=False,
            stop_event=stop_event,
        )
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_successful_export_publishes_every_selected_companion(tmp_path, monkeypatch, mesh):
    entry = _entry(tmp_path, "object/mesh.pam")
    companion = _entry(tmp_path, "object/mesh.pamlod", b"complete companion")
    monkeypatch.setattr(archive_mesh_export, "_parse_archive_mesh", lambda *args, **kwargs: mesh)
    output = tmp_path / "export"
    result = archive_mesh_export.export_archive_mesh(
        entry, output, "obj", related_entries=(companion,), build_preview_context=False,
    )
    copied = output / "referenced_files" / companion.path
    assert copied.read_bytes() == b"complete companion"
    assert copied in result.output_paths
    manifest = json.loads((output / "mesh.obj.meta.json").read_text())
    assert manifest["selected_companion_files"] == [companion.path]
    assert set(result.output_paths) == {path for path in output.rglob("*") if path.is_file()}
    assert not any(".cdmw-mesh-export-" in str(path) for path in result.output_paths)


def test_character_dependency_worker_writes_reusable_virtual_path_bundle(tmp_path, monkeypatch):
    model = _entry(tmp_path, "character/model/head.pac", b"model bytes")
    skeleton = _entry(tmp_path, "character/model/body.pab", b"skeleton bytes", group="0010")
    output = tmp_path / "bundle"
    prompts, results = [], []

    def prompt(*args, **kwargs):
        prompts.append(kwargs)
        return False, "overwrite"

    def run_task(**kwargs):
        results.append(kwargs["task"](lambda text: None, lambda *args: None, threading.Event()))

    def export_fbx(entry, root, *args, **kwargs):
        root.mkdir(parents=True, exist_ok=True)
        fbx = root / "head.fbx"
        fbx.write_bytes(b"fbx test output")
        return MeshExportResult(output_paths=[fbx], summary_lines=[])

    shell = SimpleNamespace(_suggest_archive_extract_root=lambda: output, _run_utility_task=run_task)
    host = SimpleNamespace(shell=shell, _prompt_archive_extract_options=prompt)
    monkeypatch.setattr("cdmw.ui.archive_browser.character_dependency_export.export_archive_mesh", export_fbx)
    ArchiveCharacterDependencyExportMixin._run_character_dependency_package_export(
        host, model, CharacterDependencyPlan(body_path=model.path, entries=(model, skeleton)),
    )
    assert prompts == [{"include_package_directory": False}]
    assert results[0]["stats"]["extracted"] == 2
    assert results[0]["stats"]["failed"] == 0
    assert not results[0]["manifest_error"]
    index, _basenames, hashes, manifest = load_character_appearance_bundle_index(output, stop_event=None)
    assert manifest == Path(results[0]["manifest_path"])
    for entry in (model, skeleton):
        assert index[entry.path] == output / entry.path
        assert hashes[entry.path] == hashlib.sha256(entry.paz_file.read_bytes()).hexdigest()
    assert count_existing_archive_targets((model, skeleton), output, include_package_directory=False) == 2
    assert count_existing_archive_targets((model, skeleton), output) == 0
    ordinary = tmp_path / "ordinary"
    extract_archive_entries((model,), ordinary)
    assert (ordinary / "0009" / model.path).read_bytes() == b"model bytes"
