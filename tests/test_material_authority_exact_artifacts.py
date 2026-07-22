from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.core.archive_mesh_import_build_state import MeshImportBuildState
from cdmw.core.archive_mesh_import_materials import (
    build_static_texture_payloads,
    configure_mesh_import_materials,
)
from cdmw.modding.static_mesh_replacer import StaticMeshReplacementOptions
from cdmw.services.material_authority_build_artifacts import (
    synchronize_material_authority_build_payloads,
)
from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompileRequest,
    _resident_payload_from_manifest,
)
from cdmw.ui.archive_browser.static_replacement_dialog_material_authority_callbacks import (
    _merge_material_resource_bindings,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_build_payload_uses_acknowledged_dds_bytes_exactly(tmp_path: Path) -> None:
    exact = b"DDS exact material authority artifact"
    generated = b"DDS separately regenerated artifact"
    source = tmp_path / "exact.dds"
    source.write_bytes(exact)
    payload = SimpleNamespace(
        target_path="textures/weapon_ma.dds",
        payload_data=generated,
        kind="texture_generated",
        source_path=tmp_path / "generated.dds",
        note="generated",
    )
    report = SimpleNamespace(
        slot_mappings=(
            SimpleNamespace(
                source_material_name="Blade",
                target_material_name="Weapon",
                slot_kind="material_mask",
                output_texture_path="textures/weapon_ma.dds",
            ),
        )
    )
    records = synchronize_material_authority_build_payloads(
        (payload,),
        report,
        (
            {
                "material_name": "Blade",
                "channel": "material",
                "source_dds_path": str(source),
                "content_sha256": _sha256(exact),
            },
        ),
        fingerprint="resolved-fingerprint",
    )

    assert payload.payload_data == exact
    assert payload.source_path == source
    assert records == (
        {
            "target_path": "textures/weapon_ma.dds",
            "material_name": "Blade",
            "channel": "material_mask",
            "content_sha256": _sha256(exact),
            "byte_count": len(exact),
            "fingerprint": "resolved-fingerprint",
        },
    )


def test_build_payload_fails_closed_on_hash_or_route_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "exact.dds"
    source.write_bytes(b"DDS artifact")
    payload = SimpleNamespace(
        target_path="textures/weapon_base.dds",
        payload_data=b"generated",
        kind="texture_generated",
        source_path=tmp_path / "generated.dds",
        note="",
    )
    report = SimpleNamespace(
        slot_mappings=(
            SimpleNamespace(
                source_material_name="Blade",
                target_material_name="Weapon",
                slot_kind="base",
                output_texture_path="textures/weapon_base.dds",
            ),
        )
    )

    with pytest.raises(ValueError, match="hash changed"):
        synchronize_material_authority_build_payloads(
            (payload,),
            report,
            ({"material_name": "Blade", "channel": "base", "path": source, "content_sha256": "0" * 64},),
            fingerprint="fingerprint",
        )
    with pytest.raises(ValueError, match="no Build Mod target"):
        synchronize_material_authority_build_payloads(
            (payload,),
            report,
            (
                {
                    "material_name": "Blade",
                    "channel": "emissive",
                    "path": source,
                    "content_sha256": _sha256(source.read_bytes()),
                },
            ),
            fingerprint="fingerprint",
        )


def test_compiled_material_state_carries_final_parameters_and_fingerprint(tmp_path: Path) -> None:
    request = MeshDotNetMaterialCompileRequest(
        session_id="session",
        edit_revision=3,
        generation=9,
        role="replacement",
        mesh_snapshot=SimpleNamespace(),
        affected_submeshes=(0,),
        parameter_groups=(
            {"source_submesh_indices": [0], "texture_brightness": 1.0, "emissive_intensity": 4.0},
        ),
        material_authority_fingerprint="fingerprint",
        material_authority_revision=12,
    )
    payload = _resident_payload_from_manifest(
        request,
        {
            "resources": (),
            "submeshes": (
                {
                    "submesh_index": 0,
                    "resource_channels": {},
                    "binding_conservation": {"conserved": True},
                },
            ),
            "compiler": {},
            "material_signature": "signature",
        },
        tmp_path,
        cache_hit=False,
    )

    assert payload["submeshes"][0]["parameters"] == {
        "texture_brightness": 1.0,
        "emissive_intensity": 4.0,
    }
    assert payload["material_authority_parameter_groups"] == list(request.parameter_groups)
    assert payload["material_authority_fingerprint"] == "fingerprint"
    assert payload["material_authority_revision"] == 12


def test_partial_resource_refresh_retains_other_acknowledged_channels() -> None:
    merged = _merge_material_resource_bindings(
        (
            {"resource_id": "0-base", "channel": "base", "content_sha256": "old-base"},
            {"resource_id": "0-mask", "channel": "material", "content_sha256": "old-mask"},
        ),
        (
            {"resource_id": "0-base", "channel": "base", "content_sha256": "new-base"},
        ),
    )

    assert {(row["resource_id"], row["content_sha256"]) for row in merged} == {
        ("0-base", "new-base"),
        ("0-mask", "old-mask"),
    }


def test_build_sidecar_uses_and_reads_back_canonical_residual_parameters(tmp_path: Path) -> None:
    exact = b"DDS exact emissive artifact"
    source = tmp_path / "exact.dds"
    source.write_bytes(exact)
    texture_payload = SimpleNamespace(
        target_path="textures/weapon_em.dds",
        payload_data=b"generated",
        kind="texture_generated",
        source_path=tmp_path / "generated.dds",
        note="generated",
    )
    sidecar_payload = SimpleNamespace(
        target_path="models/weapon.pac.xml",
        payload_data=(
            '<MeshMaterialWrapper _subMeshName="Weapon"><Vector>'
            '<MaterialParameterColor _name="_emissiveColor" _value="#FF0000FF"/>'
            '<MaterialParameterFloat _name="_emissiveIntensity" _value="0.250000"/>'
            '<MaterialParameterFloat _name="_screenSpaceDisplacementScale" _value="0.100000"/>'
            "</Vector></MeshMaterialWrapper>"
        ).encode("utf-8"),
        kind="sidecar_generated",
        source_path=tmp_path / "weapon.pac.xml",
        note="generated sidecar",
    )
    report = SimpleNamespace(
        slot_mappings=(
            SimpleNamespace(
                source_material_name="Blade",
                target_material_name="Weapon",
                slot_kind="emissive",
                output_texture_path="textures/weapon_em.dds",
            ),
        )
    )

    records = synchronize_material_authority_build_payloads(
        (texture_payload, sidecar_payload),
        report,
        (
            {
                "material_name": "Blade",
                "affected_submeshes": (2,),
                "channel": "emissive",
                "source_dds_path": str(source),
                "content_sha256": _sha256(exact),
            },
        ),
        fingerprint="resolved-fingerprint",
        parameter_groups=(
            {
                "source_submesh_indices": [2],
                "material_role": "emissive",
                "emissive_color": [1.0, 1.0, 1.0],
                "emissive_intensity": 3.25,
                "height_scale": 0.4,
            },
        ),
    )

    sidecar = bytes(sidecar_payload.payload_data).decode("utf-8")
    assert '_emissiveColor" _value="#FFFFFFFF"' in sidecar
    assert '_emissiveIntensity" _value="3.250000"' in sidecar
    assert '_screenSpaceDisplacementScale" _value="0.400000"' in sidecar
    assert records[-1]["kind"] == "sidecar_parameters"
    assert records[-1]["content_sha256"] == _sha256(bytes(sidecar_payload.payload_data))


def test_build_sidecar_fails_closed_when_height_parameter_cannot_be_represented(tmp_path: Path) -> None:
    exact = b"DDS exact height artifact"
    source = tmp_path / "exact.dds"
    source.write_bytes(exact)
    texture_payload = SimpleNamespace(
        target_path="textures/weapon_height.dds",
        payload_data=b"generated",
        kind="texture_generated",
        source_path=tmp_path / "generated.dds",
        note="generated",
    )
    sidecar_payload = SimpleNamespace(
        target_path="models/weapon.pac.xml",
        payload_data=(
            '<MeshMaterialWrapper _subMeshName="Weapon"><Vector>'
            '<MaterialParameterFloat _name="_brightness" _value="1.000000"/>'
            "</Vector></MeshMaterialWrapper>"
        ).encode("utf-8"),
        kind="sidecar_generated",
        source_path=tmp_path / "weapon.pac.xml",
        note="generated sidecar",
    )
    report = SimpleNamespace(
        slot_mappings=(
            SimpleNamespace(
                source_material_name="Blade",
                target_material_name="Weapon",
                slot_kind="height",
                output_texture_path="textures/weapon_height.dds",
            ),
        )
    )

    with pytest.raises(ValueError, match="cannot represent Weapon: height_scale"):
        synchronize_material_authority_build_payloads(
            (texture_payload, sidecar_payload),
            report,
            (
                {
                    "material_name": "Blade",
                    "affected_submeshes": (0,),
                    "channel": "height",
                    "source_dds_path": str(source),
                    "content_sha256": _sha256(exact),
                },
            ),
            fingerprint="resolved-fingerprint",
            parameter_groups=(
                {"source_submesh_indices": [0], "height_scale": 0.5},
            ),
        )


def test_static_build_pipeline_reuses_exact_dds_and_reads_canonical_sidecar(tmp_path: Path) -> None:
    exact = b"DDS acknowledged by resident preview"
    source = tmp_path / "acknowledged.dds"
    source.write_bytes(exact)
    texture_payload = SimpleNamespace(
        target_path="textures/weapon_em.dds",
        payload_data=b"independently regenerated",
        kind="texture_generated",
        source_path=tmp_path / "generated.dds",
        note="generated",
    )
    sidecar_payload = SimpleNamespace(
        target_path="models/weapon.pac.xml",
        payload_data=(
            '<MeshMaterialWrapper _subMeshName="Weapon"><Vector>'
            '<MaterialParameterColor _name="_emissiveColor" _value="#00FF00FF"/>'
            '<MaterialParameterFloat _name="_emissiveIntensity" _value="1.000000"/>'
            "</Vector></MeshMaterialWrapper>"
        ).encode("utf-8"),
        kind="sidecar_generated",
        source_path=tmp_path / "generated.pac.xml",
        note="generated",
    )
    report = SimpleNamespace(
        slot_mappings=(
            SimpleNamespace(
                source_material_name="Blade",
                target_material_name="Weapon",
                slot_kind="emissive",
                output_texture_path="textures/weapon_em.dds",
            ),
        )
    )
    options = StaticMeshReplacementOptions(
        complete_external_material_reset=True,
        source_material_texture_overrides=[SimpleNamespace()],
        material_authority_fingerprint="resident-fingerprint",
        material_authority_revision=17,
        material_authority_resolved_bindings=[
            {
                "material_name": "Blade",
                "affected_submeshes": (0,),
                "channel": "emissive",
                "source_dds_path": str(source),
                "content_sha256": _sha256(exact),
            }
        ],
        material_authority_residual_parameter_groups=[
            {
                "source_submesh_indices": [0],
                "material_role": "emissive",
                "emissive_color": [1.0, 1.0, 1.0],
                "emissive_intensity": 4.5,
            }
        ],
    )
    state = MeshImportBuildState(
        entry=SimpleNamespace(path="models/weapon.pac"),
        obj_path=tmp_path / "weapon.obj",
        import_mode="static_replacement",
        static_replacement_options=options,
        scene_import_result=None,
        source_display_label="weapon",
        archive_entries_by_normalized_path=None,
        texture_entries_by_normalized_path={},
        texture_entries_by_basename={},
        visible_texture_mode="mesh_base_first",
        supplemental_files=(),
        stop_event=None,
    )
    state.normalized_import_mode = "static_replacement"
    state.effective_static_source_mesh = SimpleNamespace()
    state.parsed_mesh = SimpleNamespace()
    state.original_mesh = SimpleNamespace(submeshes=())
    state.static_report = SimpleNamespace(output_draw_sections=())
    configure_mesh_import_materials(state)

    with patch(
        "cdmw.core.archive_mesh_import_preview.build_texture_replacement_payloads",
        return_value=([texture_payload, sidecar_payload], report),
    ):
        payloads, returned_report = build_static_texture_payloads(state, ("<PAM/>",))

    assert returned_report is report
    assert payloads[0].payload_data == exact
    assert _sha256(bytes(payloads[0].payload_data)) == _sha256(exact)
    sidecar = bytes(payloads[1].payload_data).decode("utf-8")
    assert '_emissiveColor" _value="#FFFFFFFF"' in sidecar
    assert '_emissiveIntensity" _value="4.500000"' in sidecar
    assert state.material_authority_settings["status"] == "exact"
    assert state.material_authority_settings["fingerprint"] == "resident-fingerprint"
    assert len(state.material_authority_settings["exact_artifacts"]) == 2
