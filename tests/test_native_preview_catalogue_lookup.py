"""Executable shared-default lookup through the existing Full catalogue files."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct

import pytest

from cdmw.models import ModelPreviewRenderSettings
from cdmw.rendering import native_preview_core as core
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker
from tests.archive_resident_index_fixtures import write_resident_index
from tests.test_native_preview_long_paths import _prepared_entry, native_helper


def _basename_hash(value: str) -> int:
    result = 14695981039346656037
    for byte in value.lower().encode("utf-8"):
        result = ((result ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return result


def _catalogue(tmp_path: Path, *, legacy=False, distractors=24):
    entry = _prepared_entry(tmp_path / "prepared" / "grid.pac")
    sidecar_bytes = (
        '<ModelProperty Index="0"><SkinnedMeshMaterialWrapper _subMeshName="grid">'
        '<Material _materialName="Standard_Ver2">'
        '<MaterialParameterTexture Name="_baseColorTexture" Value="texture/missing.dds"/>'
        '</Material></SkinnedMeshMaterialWrapper></ModelProperty>'
    ).encode()
    dds = bytearray(136)
    dds[:4] = b"DDS "
    struct.pack_into("<7I", dds, 4, 124, 0x81007, 4, 4, 8, 0, 1)
    struct.pack_into("<II4s", dds, 76, 32, 4, b"DXT1")
    struct.pack_into("<I", dds, 108, 0x1000)
    struct.pack_into("<HHI", dds, 128, 0xFFFF, 0, 0)
    payloads = [
        (entry.path, entry.prepared_path.read_bytes()),
        ("fixture/grid.pac_xml", sidecar_bytes),
        ("material/dist/standard_ver2.material", b'<Material><ParameterGroup Name="StandardParameters"/></Material>'),
        ("material/dist/sharedparameters.xml", b'<Parameters><ParameterGroup Name="StandardParameters"><Parameter Name="_baseColorTexture" Type="Texture" DefaultValue="texture/neutral.dds" sRGB="true"/></ParameterGroup></Parameters>'),
        ("texture/neutral.dds", bytes(dds)),
        *[(f"material/dist/unrelated_{i:04d}.material", b'<Material><Parameter Name="_baseColorTexture" Type="Texture" DefaultValue="texture/wrong.dds"/></Material>') for i in range(distractors)],
    ]
    rows = []
    # Game shader definitions live in a different archive from model sidecars.
    for number, archive_payloads in (("0009", payloads[:2]), ("0002", payloads[2:])):
        archive_pamt = tmp_path / number / "0.pamt"
        paz = archive_pamt.with_suffix(".paz")
        archive_pamt.parent.mkdir()
        archive_rows, data, names, offsets = [], bytearray(), bytearray(), []
        for path, payload in archive_payloads:
            offsets.append(len(names))
            raw_path = path.encode()
            names.extend(struct.pack("<IB", 0xFFFFFFFF, len(raw_path)) + raw_path)
            archive_rows.append(replace(
                entry, path=path, pamt_path=archive_pamt, paz_file=paz, offset=len(data),
                comp_size=len(payload), orig_size=len(payload), flags=0, paz_index=0,
                prepared_path=None, prepared_size=-1, prepared_sha256="",
            ))
            data.extend(payload)
        paz.write_bytes(data)
        records = b"".join(struct.pack("<4I2H", name, row.offset, row.comp_size, row.orig_size, 0, 0)
                           for name, row in zip(offsets, archive_rows))
        archive_pamt.write_bytes(struct.pack("<7I", 0, 1, 0, 0, 0, 0, 0)
                                 + struct.pack("<I", len(names)) + names
                                 + struct.pack("<II", 0, len(archive_rows)) + records)
        rows.extend(archive_rows)
    entry = replace(rows[0], prepared_path=entry.prepared_path, prepared_size=entry.prepared_size,
                    prepared_sha256=entry.prepared_sha256)
    sidecar_path = tmp_path / "prepared" / "grid.pac_xml"
    sidecar_path.write_bytes(sidecar_bytes)
    sidecar = replace(rows[1], prepared_path=sidecar_path, prepared_size=len(sidecar_bytes),
                      prepared_sha256=hashlib.sha256(sidecar_bytes).hexdigest())
    rows.sort(key=lambda row: row.path.lower())
    if legacy:
        rows.reverse()  # The older format does not promise sorted paths.
    source = write_resident_index(tmp_path, rows, tmp_path / "catalogue")
    index = Path(source.index_path)
    count, size = len(rows), index.stat().st_size
    basename_rows = sorted((_basename_hash(Path(row.path).name), i) for i, row in enumerate(rows))
    basename_bytes = b"".join(struct.pack("<QQ", *row) for row in basename_rows)
    if legacy:
        ali = bytearray(index.read_bytes())
        ali[:8] = b"CDMWALI1"
        struct.pack_into("<I", ali, 8, 1)
        index.write_bytes(ali)
        header = struct.pack("<8sII4Q", b"CDMWABI1", 1, 16, count, 64, count, size).ljust(64, b"\0")
        dependency = header + basename_bytes
    else:
        header = struct.pack("<8sII8Q", b"CDMWADI1", 1, 16, count, 80, 80 + 16 * count,
                             80 + 32 * count, 2, count, size, 0)
        dependency = header + basename_bytes + basename_bytes + b"{}"
    index.with_name("archive.adi").write_bytes(dependency)
    return entry, sidecar, index


def _run(tmp_path, entry, sidecar, index, *, additional_dependencies=()):
    worker = ArchivePreviewWorker(
        1, entry, sidecar, {}, {}, {}, {}, (),
        render_settings=ModelPreviewRenderSettings(use_textures_by_default=True),
        native_preview_core_enabled=True, native_preview_core_cache_root=tmp_path / "cache",
        native_preview_core_package_root=tmp_path,
        native_preview_dependency_entries=(entry, sidecar, *additional_dependencies),
        native_preview_dependency_entries_complete=True, native_preview_archive_index_path=index,
    )
    return worker._run_native_preview_core_with_presentation(
        output_root=tmp_path / "package", dds_cache_max_bytes=1024 * 1024,
        dds_cache_target_bytes=512 * 1024,
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_worker_resolves_shared_default_without_scanning_other_materials(native_helper, tmp_path, legacy):
    entry, sidecar, index = _catalogue(tmp_path, legacy=legacy)
    attempt = _run(tmp_path, entry, sidecar, index)
    assert attempt.succeeded, attempt.fallback_reason
    diagnostics = attempt.diagnostics
    assert diagnostics["archive_lookup_error"] == ""
    assert diagnostics["native_pamt_index_resident_before_release"] == 0
    used = {row["path"] for row in diagnostics["cache_dependency_entries"]}
    assert "texture/neutral.dds" in used
    assert "material/dist/standard_ver2.material" in used
    assert not any("unrelated_" in path for path in used)
    manifest = json.loads((Path(attempt.package_path) / "manifest.json").read_text())
    resolved = [row for row in manifest["material_conservation"]["parameters"]
                if row.get("source_resolution") == "technique_default_after_missing_declared_source"]
    assert resolved
    assert {row["resolved_archive_path"] for row in resolved} == {"texture/neutral.dds"}
    assert all(row["declared_source_missing"] for row in resolved)


def test_prepared_family_definition_keeps_its_named_group(native_helper, tmp_path):
    entry, sidecar, index = _catalogue(tmp_path)
    paz = tmp_path / "0002" / "0.paz"
    paz.write_bytes(paz.read_bytes().replace(
        b'<Parameters><ParameterGroup Name="StandardParameters">',
        b'<Parameters><ParameterGroup Name="OverrideParameters">',
    ))
    cached_miss = _run(tmp_path, entry, sidecar, index)
    assert cached_miss.diagnostics.get("texture_preparation_error")
    prepared = tmp_path / "prepared" / "standard_ver2.material"
    payload = b'<Material><ParameterGroup Name="OverrideParameters"/></Material>'
    prepared.write_bytes(payload)
    family = replace(
        entry, path="material/dist/standard_ver2.material", pamt_path=paz.with_suffix(".pamt"),
        paz_file=paz, offset=0, comp_size=len(payload), orig_size=len(payload),
        prepared_path=prepared, prepared_size=len(payload),
        prepared_sha256=hashlib.sha256(payload).hexdigest(),
    )
    attempt = _run(tmp_path, entry, sidecar, index, additional_dependencies=(family,))
    assert attempt.succeeded, attempt.fallback_reason
    assert not attempt.diagnostics.get("texture_preparation_error")
    manifest = json.loads((Path(attempt.package_path) / "manifest.json").read_text())
    assert any(row.get("resolved_archive_path") == "texture/neutral.dds"
               and "parameter_group:overrideparameters" in row.get("source_resolution_detail", "")
               for row in manifest["material_conservation"]["parameters"])


@pytest.mark.parametrize("damage", ["missing", "source_size", "stem_offset", "order"])
def test_unavailable_catalogue_keeps_the_existing_default_lookup(native_helper, tmp_path, damage):
    entry, sidecar, index = _catalogue(tmp_path)
    dependency = index.with_name("archive.adi")
    if damage == "missing":
        dependency.unlink()
    else:
        data = bytearray(dependency.read_bytes())
        if damage == "source_size":
            struct.pack_into("<Q", data, 64, index.stat().st_size + 1)
        elif damage == "stem_offset":
            struct.pack_into("<Q", data, 32, 80)
        else:
            data[80:96], data[96:112] = data[96:112], data[80:96]
        dependency.write_bytes(data)
    attempt = _run(tmp_path, entry, sidecar, index)
    assert attempt.succeeded, attempt.fallback_reason
    assert attempt.diagnostics["archive_lookup_error"]
    assert attempt.diagnostics["native_pamt_index_resident_before_release"] > 0
    manifest = json.loads((Path(attempt.package_path) / "manifest.json").read_text())
    assert any(row.get("resolved_archive_path") == "texture/neutral.dds"
               for row in manifest["material_conservation"]["parameters"])
