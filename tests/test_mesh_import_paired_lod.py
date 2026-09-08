"""Owned PAM/PAMLOD fixtures exercise companion preparation and loose export."""

from __future__ import annotations

import hashlib
import struct
import threading
from pathlib import Path

import pytest

from cdmw.core import archive_mesh_import_preview as preview_api
from cdmw.core.archive_loose_export import export_archive_mesh_payloads_to_mod_ready_loose
from cdmw.core.common import RunCancelled
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.modding.mesh_parser import parse_pam, parse_pamlod
from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions, StaticReplacementTransform
from cdmw.ui.archive_browser.mesh_patch_flow import _loose_mesh_patch_requests


def _static_payload(*, lod: bool) -> bytes:
    table, record_size = (0x50, 0x210) if lod else (0x410, 0x218)
    geometry = table + record_size
    data = bytearray(geometry + 3 * 6 + 3 * 2)
    if lod:
        struct.pack_into("<II", data, 0, 1, geometry)
        bounds = 0x10
    else:
        data[:4] = b"PAR "
        struct.pack_into("<I", data, 0x10, 1)
        struct.pack_into("<I", data, 0x3C, geometry)
        bounds = 0x14
    struct.pack_into("<ffffff", data, bounds, 0, 0, 0, 1, 1, 1)
    struct.pack_into("<IIII", data, table, 3, 3, 0, 0)
    data[table + 0x10:table + 0x10 + 10] = b"stone.dds\0"
    data[table + 0x110:table + 0x110 + 6] = b"stone\0"
    for index, position in enumerate(((0, 0, 0), (65535, 0, 0), (0, 65535, 0))):
        struct.pack_into("<HHH", data, geometry + index * 6, *position)
    struct.pack_into("<HHH", data, geometry + 18, 0, 1, 2)
    return bytes(data)


@pytest.fixture
def paired_import(tmp_path):
    entries = []
    pamt = tmp_path / "0.pamt"
    pamt.write_bytes(b"owned synthetic index")
    for lod in (False, True):
        suffix = ".pamlod" if lod else ".pam"
        payload = _static_payload(lod=lod)
        paz = tmp_path / ("target" + suffix + ".paz")
        paz.write_bytes(payload)
        entries.append(ArchiveEntry(
            "object/target" + suffix, pamt, paz, 0, len(payload), len(payload), 0, 0,
        ))
    source = tmp_path / "replacement.obj"
    source.write_text("o stone\nv .25 0 0\nv 1.25 0 0\nv .25 1 0\nf 1 2 3\n", encoding="utf-8")
    stop_event = threading.Event()
    paths = (pamt, *(entry.paz_file for entry in entries), source)
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    def build():
        return preview_api.build_mesh_import_preview(
            entries[0], source, import_mode="static_replacement",
            static_replacement_options=StaticMeshReplacementOptions(
                transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            ),
            archive_entries_by_normalized_path={entry.path.casefold(): (entry,) for entry in entries},
            stop_event=stop_event,
        )

    yield entries, source, stop_event, build
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before


def test_pam_replacement_exports_reparseable_mesh_and_required_companion(paired_import, tmp_path):
    entries, source, _stop_event, build = paired_import
    preview = build()
    assert preview.paired_lod_path == entries[1].path
    assert preview.paired_lod_data
    requests = _loose_mesh_patch_requests(
        entries[0], entries[1], preview, writes_geometry=True, on_log=lambda _message: None,
    )
    assert [request.entry for request in requests] == entries
    output = export_archive_mesh_payloads_to_mod_ready_loose(
        requests, primary_entry=entries[0], preview_result=preview, source_obj_path=source,
        parent_root=tmp_path / "output", package_info=ModPackageInfo(title="Paired replacement"),
        related_entries_to_include=(),
    )
    for entry, parser in zip(entries, (parse_pam, parse_pamlod)):
        paths = list(output.package_root.rglob(entry.basename))
        assert len(paths) == 1
        rebuilt = parser(paths[0].read_bytes(), entry.path)
        assert rebuilt.total_faces == 1
        for actual, expected in zip(rebuilt.submeshes[0].vertices, ((.25, 0, 0), (1.25, 0, 0), (.25, 1, 0))):
            assert actual == pytest.approx(expected, abs=5e-5)


@pytest.mark.parametrize("failure_stage", ["transfer", "serialize"])
def test_companion_failure_aborts_import_before_package_output(paired_import, tmp_path, monkeypatch, failure_stage):
    entries, _source, _stop_event, build = paired_import
    name = "transfer_pam_edit_to_pamlod_mesh" if failure_stage == "transfer" else "build_mesh"

    def fail(*_args, **_kwargs):
        raise RuntimeError("controlled companion failure")

    monkeypatch.setattr(preview_api, name, fail)
    with pytest.raises(ValueError, match="required companion.*could not be rebuilt") as error:
        build()
    assert entries[1].path in str(error.value)
    assert "controlled companion failure" in str(error.value)
    assert isinstance(error.value.__cause__, RuntimeError)
    assert not (tmp_path / "output").exists()


def test_companion_cancellation_remains_cancellation(paired_import, monkeypatch):
    _entries, _source, stop_event, build = paired_import

    def cancel(*_args):
        stop_event.set()
        raise RuntimeError("cancelled during transfer")

    monkeypatch.setattr(preview_api, "transfer_pam_edit_to_pamlod_mesh", cancel)
    with pytest.raises(RunCancelled):
        build()
