"""Placement imports retain lazy archive lookups and report backend work."""

import pytest

from cdmw.core.archive_mesh_import_preview import build_mesh_import_preview
from cdmw.core.archive_resident_index import ResidentArchiveIndex
from cdmw.models import ArchiveEntry
from cdmw.modding.static_mesh_replacer import StaticMeshReplacementOptions, StaticReplacementTransform
from tests.archive_resident_index_fixtures import write_resident_index
from tests.test_mesh_import_paired_lod import _static_payload


def test_mesh_import_resolves_dependencies_without_enumerating_catalogue(tmp_path, monkeypatch):
    pamt = tmp_path / "0.pamt"
    pamt.write_bytes(b"owned fixture")
    entries = []
    for name, payload in (
        ("target.pam", _static_payload(lod=False)),
        ("target.pamlod", _static_payload(lod=True)),
        ("target.pami", b"<PAMI />"),
        ("unrelated.pam", _static_payload(lod=False)),
    ):
        paz = tmp_path / (name + ".paz")
        paz.write_bytes(payload)
        entries.append(ArchiveEntry("object/" + name, pamt, paz, 0, len(payload), len(payload), 0, 0))
    source = tmp_path / "replacement.obj"
    source.write_text("o stone\nv .25 0 0\nv 1.25 0 0\nv .25 1 0\nf 1 2 3\n", encoding="utf-8")
    sidecar = tmp_path / "target.pami"
    sidecar.write_bytes(b"<PAMI />")
    index = ResidentArchiveIndex(write_resident_index(tmp_path, entries, tmp_path / "catalogue"))

    # The material pipeline already knows which source texture is being converted.
    # Exercise its callback through the real import stages, without native encoding.
    texture = tmp_path / "stone_basecolor.png"
    texture.write_bytes(b"texture pipeline fixture")

    def material_payloads(*, on_log, **_kwargs):
        on_log("Converting stone_basecolor.png (BC7_UNORM, 4x4, 3 mip levels)")
        return [], None

    monkeypatch.setattr("cdmw.core.archive_mesh_import_preview.build_texture_replacement_payloads", material_payloads)

    def no_catalogue_enumeration(*_args, **_kwargs):
        raise AssertionError("Import must query dependencies without copying the entire catalogue")

    monkeypatch.setattr(index, "_keys", no_catalogue_enumeration)
    logs, progress = [], []
    result = build_mesh_import_preview(
        entries[0], source, import_mode="static_replacement",
        static_replacement_options=StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
        ),
        archive_entries_by_normalized_path=index.by_path,
        texture_entries_by_normalized_path=index.by_path,
        texture_entries_by_basename=index.by_basename,
        supplemental_files=(sidecar, texture),
        on_log=logs.append,
        on_progress=lambda *event: progress.append(event),
    )
    assert result.parsed_mesh.total_faces == 1
    assert result.paired_lod_path == "object/target.pamlod"
    assert result.paired_lod_data
    assert any(spec.target_path == "object/target.pami" for spec in result.supplemental_file_specs)
    assert any("stone_basecolor" in ref.reference_name for ref in result.texture_references)
    assert any("Finding companion files for target.pam" in line for line in logs)
    assert any("Reference " in line and "stone_basecolor" in line for line in logs)
    assert any("archive lookup missing" in line for line in logs)
    assert any("Converting stone_basecolor.png" in line for line in logs)
    for _current, _total, phase in progress[:-1]:
        assert f"{phase}: starting..." in logs
        assert any(line.startswith(f"{phase}: finished in ") for line in logs)
    assert progress[-1] == (10, 10, "Ready")


def test_mesh_import_failure_reports_phase_without_claiming_completion(tmp_path):
    logs, progress = [], []
    entry = ArchiveEntry("object/target.pam", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 1, 1, 0, 0)
    with pytest.raises((OSError, ValueError)):
        build_mesh_import_preview(
            entry, tmp_path / "missing.obj", on_log=logs.append,
            on_progress=lambda *event: progress.append(event),
        )
    assert logs[0] == "Read source: starting..."
    assert any(line.startswith("Read source: stopped after ") for line in logs)
    assert not any("finished in" in line for line in logs)
    assert progress == [(0, 10, "Read source")]
