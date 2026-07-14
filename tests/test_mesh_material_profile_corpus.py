from __future__ import annotations

from pathlib import Path
import struct
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.core.archive_model_references import _ArchiveModelSidecarTextureBinding
from cdmw.models import ArchiveEntry, PreviewMaterialParameterInput
from cdmw.modding.material_profiles import complete_swap_material_runtime_profiles
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_texture_sources import MeshTextureSourceResolution
from tools.build_mesh_material_profile_corpus import _REPRESENTATIVE_REAL_PACS
from tools.mesh_harness.archive_provenance import _hydrate_real_archive_mesh_materials
from tools.mesh_harness.material_profile_corpus import (
    material_asset_contract_row,
    material_profile_corpus_report,
    supported_material_profile_contracts,
    synthetic_material_failure_contracts,
)


def _mesh(texture: Path) -> ParsedMesh:
    submesh = SubMesh(
        name="Blade",
        material="Steel",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
        texture=str(texture),
    )
    submesh.cdmw_material_authority_profile = "material_authority_true_source"
    submesh.preview_material_texture_inputs = (
        SimpleNamespace(semantic_type="base", source_path=str(texture)),
    )
    submesh.preview_material_parameters = (
        SimpleNamespace(parameter_name="_roughnessFactor", numeric_value=0.4),
    )
    submesh.preview_color = (0.8, 0.7, 0.6)
    return ParsedMesh(path="synthetic.pac", format="pac", submeshes=[submesh])


def test_real_material_hydration_uses_sidecar_contract_and_local_dds(tmp_path: Path) -> None:
    source_dds = tmp_path / "body.dds"
    source_dds.write_bytes(b"DDS production texture")
    model_entry = ArchiveEntry(
        path="character/model/body.pac",
        pamt_path=tmp_path / "0.pamt",
        paz_file=tmp_path / "0.paz",
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )
    texture_entry = ArchiveEntry(
        path="character/texture/body.dds",
        pamt_path=tmp_path / "0.pamt",
        paz_file=tmp_path / "0.paz",
        offset=1,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )
    mesh = ParsedMesh(
        path=model_entry.path,
        format="pac",
        submeshes=[
            SubMesh(
                name="Body",
                material="Body",
                texture="Body",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
            )
        ],
    )
    binding = _ArchiveModelSidecarTextureBinding(
        texture_path=texture_entry.path,
        parameter_name="_baseColorTexture",
        submesh_name="Body",
        sidecar_kind="pac_xml",
        shader_family="Skin",
        material_parameters=(
            PreviewMaterialParameterInput(
                parameter_kind="uint",
                parameter_name="AlphaTest",
                value="1",
                numeric_value=1.0,
            ),
        ),
    )
    resolution = MeshTextureSourceResolution(
        source_path=source_dds,
        archive_entry=texture_entry,
        archive_path=texture_entry.path,
        status="archive",
    )
    entries_by_path = {texture_entry.path: (texture_entry,)}
    entries_by_basename = {"body.dds": (texture_entry,)}

    with (
        patch(
            "tools.mesh_harness.archive_provenance.extract_archive_model_sidecar_texture_references",
            return_value=((binding,), ("character/modelproperty/body.pac_xml",), {}, {}),
        ),
        patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            return_value="preview://body.dds",
        ),
        patch(
            "tools.mesh_harness.archive_provenance.resolve_mesh_texture_source",
            return_value=resolution,
        ),
    ):
        rows, diagnostics = _hydrate_real_archive_mesh_materials(
            mesh,
            model_entry,
            entries_by_path,
            entries_by_basename,
        )

    submesh = mesh.submeshes[0]
    assert submesh.preview_sidecar_shader_family == "Skin"
    assert submesh.preview_alpha_mode == "cutout"
    assert submesh.preview_material_parameters == binding.material_parameters
    assert submesh.preview_material_texture_inputs[0].source_dds_path == str(source_dds.resolve())
    assert any(row["material_authority"] == "sidecar" for row in rows)
    assert any("sidecar" in line.casefold() for line in diagnostics)


def test_supported_profile_corpus_records_every_deterministic_contract_dimension() -> None:
    rows = supported_material_profile_contracts()
    assert len(rows) == len(complete_swap_material_runtime_profiles())
    assert len({str(row["profile"]) for row in rows}) == len(rows)
    assert all(row["expected_channels"] for row in rows)
    assert all(row["resource_policy"] for row in rows)
    assert all(row["scalar_rules"] for row in rows)
    assert all(row["tint_rules"] for row in rows)
    assert all(row["normal_y_policy"] for row in rows)
    assert all(row["layer_behavior"] for row in rows)
    assert all(len(str(row["contract_fingerprint"])) == 64 for row in rows)
    assert rows == supported_material_profile_contracts()


def test_asset_row_uses_content_fingerprints_not_temporary_paths(tmp_path: Path) -> None:
    first = tmp_path / "first" / "base.png"
    second = tmp_path / "second" / "base.png"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"same-texture-content")
    second.write_bytes(b"same-texture-content")
    first_row = material_asset_contract_row(
        _mesh(first),
        asset_kind="external_catalogue",
        source_identity={"sha256": "asset"},
        profile_assignment="material_authority_true_source",
    )
    second_row = material_asset_contract_row(
        _mesh(second),
        asset_kind="external_catalogue",
        source_identity={"sha256": "asset"},
        profile_assignment="material_authority_true_source",
    )
    assert first_row == second_row
    assert first_row["expected_channels"] == ["base"]
    assert first_row["resources"][0]["criticality"] == "required"
    assert first_row["resources"][0]["profile"] == "material_authority_true_source"
    assert first_row["submeshes"][0]["parameters"]["tint_color"] == [0.8, 0.7, 0.6]
    assert first_row["submeshes"][0]["shader_family_source"] == "unresolved"
    assert first_row["submeshes"][0]["shader_family_reason"]
    assert first_row["submeshes"][0]["alpha_authority"] == "guess"
    assert first_row["submeshes"][0]["alpha_reason"]


def test_synthetic_failure_rows_cover_required_optional_and_symbolic_cases() -> None:
    rows = {str(row["case"]): row for row in synthetic_material_failure_contracts()}
    assert rows["required_base_missing"]["ready_allowed_after_failure"] is False
    assert rows["required_base_missing"]["fallback_policy"] == "block_ready"
    assert rows["optional_normal_missing"]["ready_allowed_after_failure"] is True
    assert rows["optional_normal_missing"]["fallback_policy"] == "flat_normal"
    assert rows["unresolved_symbolic_base"]["ready_allowed_after_failure"] is True


def test_corpus_fingerprint_changes_with_asset_contract(tmp_path: Path) -> None:
    texture = tmp_path / "base.png"
    texture.write_bytes(b"texture")
    asset = material_asset_contract_row(
        _mesh(texture),
        asset_kind="external_catalogue",
        source_identity={"sha256": "asset"},
    )
    empty = material_profile_corpus_report()
    populated = material_profile_corpus_report(asset_rows=[asset])
    assert len(str(populated["corpus_fingerprint"])) == 64
    assert empty["corpus_fingerprint"] != populated["corpus_fingerprint"]
    assert "visible renderer parity" in str(populated["claim_scope"])
    assert populated["actual_profile_coverage"] == ["material_authority_true_source"]
    assert populated["coverage_limitations"]


def test_asset_row_records_source_dds_format_dimensions_mips_and_color_space(tmp_path: Path) -> None:
    texture = tmp_path / "bounded_source.dds"
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<I", header, 12, 64)
    struct.pack_into("<I", header, 16, 128)
    struct.pack_into("<I", header, 28, 8)
    struct.pack_into("<I", header, 76, 32)
    struct.pack_into("<I", header, 80, 0x4)
    header[84:88] = b"DXT1"
    texture.write_bytes(bytes(header) + bytes(4096))

    row = material_asset_contract_row(
        _mesh(texture),
        asset_kind="bounded_dds",
        source_identity={"sha256": "asset"},
        profile_assignment="material_authority_true_source",
    )
    resource = row["resources"][0]

    assert resource["dds_header_status"] == "valid"
    assert resource["source_format"] == "DXT1"
    assert resource["source_width"] == 128
    assert resource["source_height"] == 64
    assert resource["source_mip_count"] == 8
    assert resource["native_2d_candidate"] is True
    assert resource["semantic"] == "base"
    assert resource["color_space"] == "srgb"


def test_asset_row_records_cached_openimageio_channel_statistics(tmp_path: Path) -> None:
    texture = tmp_path / "hair.dds"
    texture.write_bytes(b"same-texture")
    calls: list[Path] = []
    cache: dict[str, object] = {}

    def probe(path: Path) -> dict[str, object]:
        calls.append(path)
        return {
            "status": "ok",
            "metadata": {
                "width": 1024,
                "height": 1024,
                "channel_count": 4,
                "bit_depth": "8-bit",
                "color_space": "",
                "channel_names": ["R", "G", "B", "A"],
                "channel_stats": {
                    "A": {"minimum": 0.0, "maximum": 255.0, "average": 40.0},
                },
                "has_alpha_channel": True,
                "alpha_varies": True,
                "alpha_has_transparency": True,
            },
        }

    first = material_asset_contract_row(
        _mesh(texture),
        asset_kind="oiio_hair",
        source_identity={"sha256": "asset"},
        texture_probe=probe,
        texture_probe_cache=cache,  # type: ignore[arg-type]
    )
    second = material_asset_contract_row(
        _mesh(texture),
        asset_kind="oiio_hair",
        source_identity={"sha256": "asset"},
        texture_probe=probe,
        texture_probe_cache=cache,  # type: ignore[arg-type]
    )

    assert calls == [texture]
    assert first == second
    evidence = first["resources"][0]["openimageio"]
    assert evidence["status"] == "ok"
    assert evidence["channel_names"] == ["R", "G", "B", "A"]
    assert evidence["alpha_varies"] is True
    assert evidence["alpha_has_transparency"] is True
    assert "OpenImageIO channel statistics" in first["claim_scope"]


def test_representative_hair_sample_uses_verified_dds_backed_pac() -> None:
    assert _REPRESENTATIVE_REAL_PACS["hair"] == (
        "character/model/1_pc/14_ptm/head/hair/cd_ptm_00_hair_00_0003.pac"
    )
    source = (Path(__file__).resolve().parents[1] / "tools" / "build_mesh_material_profile_corpus.py").read_text(
        encoding="utf-8"
    )
    assert 'category == "hair" and not textures' in source


def test_representative_emissive_weapon_matches_reported_real_target() -> None:
    assert _REPRESENTATIVE_REAL_PACS["emissive_weapon"] == (
        "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0014.pac"
    )
