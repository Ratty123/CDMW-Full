from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.domain.mesh import MeshObjectTransformState
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.models import (
    ArchiveEntry,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.services import mesh_rust_authoring as rust_authoring_module
from cdmw.services.mesh_rust_authoring import (
    RUST_MESH_AUTHORING_PACKAGE,
    RUST_MESH_CANDIDATE,
    RUST_MESH_EDIT_BACKEND,
    RUST_MESH_EDITOR_PROTOCOL,
    RUST_MESH_RENDERER,
    RustMeshAuthoringSession,
    RustMeshCancellationError,
    RustMeshProtocolError,
    RustMeshValidationError,
    read_owned_payload_reference,
    resolve_rust_mesh_editor,
)
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_CONTROL_CONTRACT_FILE,
    RUST_MESH_CONTROL_CONTRACT_SCHEMA,
    RUST_MESH_PROVENANCE_FILE,
    RUST_MESH_PROVENANCE_SCHEMA,
    RUST_MESH_REQUIRED_CAPABILITIES,
    RUST_PREVIEW_BACKEND,
    RUST_PREVIEW_PACKAGE,
    RUST_PREVIEW_PROTOCOL,
    RUST_PREVIEW_REQUIRED_CAPABILITIES,
    RustMeshExecutableResolution,
    rust_mesh_editor_file_signature,
    validate_rust_mesh_editor_package,
)
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_state import _MeshGeometryLayer
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_service_editing import _quad_mesh
from tests.test_mesh_morph_service import _author_command
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


class _Settings:
    def __init__(self, path: Path) -> None:
        self.path = path

    def fileName(self) -> str:  # noqa: N802 - QSettings-compatible test double
        return str(self.path)


def _prepared_dds_entry(
    root: Path,
    virtual_path: str,
    payload: bytes,
) -> ArchiveEntry:
    prepared = root / Path(virtual_path.replace("\\", "/")).name
    prepared.write_bytes(payload)
    return ArchiveEntry(
        path=virtual_path,
        pamt_path=root / "source.pamt",
        paz_file=root / "source.paz",
        offset=0,
        comp_size=len(payload),
        orig_size=len(payload),
        flags=0,
        paz_index=0,
        prepared_path=prepared,
        prepared_sha256=hashlib.sha256(payload).hexdigest(),
        prepared_note="owned Rust texture fixture",
    )


def _request(session: RustMeshAuthoringSession, event: str, request_id: int) -> dict[str, object]:
    return {
        "event": event,
        "protocol": RUST_MESH_EDITOR_PROTOCOL,
        "session_id": session.session_id,
        "request_id": request_id,
        "base_revision": session.shadow_service.session_view(session.shadow_session_id).revision,
        "process_generation": session.process_generation,
    }


def _acknowledge_test_profile_tree(session: RustMeshAuthoringSession) -> None:
    session.acknowledged_morph_profile_fingerprint = (
        rust_authoring_module._directory_fingerprint(
            session.root / "mesh_slider_profiles"
        )
    )


def _with_resolvable_bone_palette(source: bytes, hashes: tuple[int, ...]) -> bytes:
    """Append a valid owned palette table to section 0 and shift section data."""

    payload = bytearray(source)
    section_0_offset = 0x50
    section_0_size = struct.unpack_from("<I", payload, 0x14)[0]
    insertion = section_0_offset + section_0_size
    palette = struct.pack("<H", len(hashes)) + struct.pack(
        f"<{len(hashes)}I", *hashes
    )
    delta = len(palette)
    lod_count = payload[section_0_offset + 4]
    for table in range(2):
        table_offset = section_0_offset + 5 + table * lod_count * 4
        for lod_index in range(lod_count):
            value = struct.unpack_from("<I", payload, table_offset + lod_index * 4)[0]
            struct.pack_into("<I", payload, table_offset + lod_index * 4, value + delta)
    struct.pack_into("<I", payload, 0x14, section_0_size + delta)
    payload[insertion:insertion] = palette
    return bytes(payload)


def _candidate_reference(
    session: RustMeshAuthoringSession,
    *,
    request_id: int,
    first_x: float,
    sha256: str | None = None,
) -> dict[str, object]:
    mesh = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
    submeshes: list[dict[str, object]] = []
    for submesh_index, submesh in enumerate(mesh.submeshes):
        positions = [list(row) for row in submesh.vertices]
        if submesh_index == 0:
            positions[0][0] = first_x
        submeshes.append(
            {
                "positions": positions,
                "normals": [list(row) for row in submesh.normals],
                "uvs": [list(row) for row in submesh.uvs],
                "indices": [value for face in submesh.faces for value in face],
            }
        )
    payload = {
        "schema": RUST_MESH_CANDIDATE,
        "session_id": session.session_id,
        "submeshes": submeshes,
        "selection": {
            "vertices_by_submesh": {"0": [0]},
            "edges_by_submesh": {},
            "faces_by_submesh": {},
            "source_indices": [0],
        },
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    name = f"candidate-{request_id}-test.json"
    (session.root / name).write_bytes(data)
    return {
        "path": name,
        "data_type": "mesh_candidate_json",
        "count": len(submeshes),
        "byte_length": len(data),
        "sha256": sha256 or hashlib.sha256(data).hexdigest().upper(),
        "content_type": "application/json",
    }


class RustMeshAuthoringTests(unittest.TestCase):
    def _create(
        self,
        root: Path,
        *,
        force_zero_index_offset: bool = False,
        strip_optional_channels: bool = False,
        skeleton: object | None = None,
        skinned_source: bool = True,
        base_texture_path: Path | None = None,
        preview_material_model: object | None = None,
        material_package_path: Path | None = None,
        material_unavailable_reason: str = "",
        texture_name: str = "",
        material_name: str = "",
        target_entry: ArchiveEntry | None = None,
        texture_entries_by_basename: dict[str, tuple[ArchiveEntry, ...]] | None = None,
    ) -> tuple[MeshService, RustMeshAuthoringSession]:
        authoritative = MeshService(settings=_Settings(root.parent / "settings.ini"))
        source = _pac_fixture(skinned=skinned_source)
        if skeleton is not None:
            palette_hashes = tuple(
                int(getattr(bone, "name_hash", 0) or 0)
                for bone in tuple(getattr(skeleton, "bones", ()) or ())
            )
            if (
                len(palette_hashes) >= 8
                and len(set(palette_hashes)) == len(palette_hashes)
                and all(value >= 0x10000 for value in palette_hashes)
            ):
                source = _with_resolvable_bone_palette(source, palette_hashes)
        mesh = parse_pac(source, "owned-rust-authoring.pac")
        setattr(mesh, "_cdmw_original_data", source)
        setattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", 8)
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        if force_zero_index_offset:
            # Keep the zero-value serialization regression independent of the
            # exact writer's real source index offset.
            mesh.submeshes[0].source_index_offset = 0
        if strip_optional_channels:
            for level in ([mesh.submeshes] + list(mesh.lod_levels or [])):
                for submesh in level:
                    submesh.normals = []
                    submesh.uvs = []
        if base_texture_path is not None:
            for level in ([mesh.submeshes] + list(mesh.lod_levels or [])):
                if level:
                    level[0].preview_texture_dds_path = str(base_texture_path)
        if texture_name:
            mesh.submeshes[0].texture = texture_name
        if material_name:
            mesh.submeshes[0].material = material_name
        view = authoritative.open_edit_session(
            mesh,
            session_id="authoritative-rust-test",
            mode="edit",
        )
        if skeleton is not None:
            authoritative.attach_skeleton(
                view.session_id,
                skeleton,
                source_path=str(getattr(skeleton, "path", "") or ""),
            )
        controller = SimpleNamespace(
            mesh_service=authoritative,
            active_session_id=view.session_id,
        )
        rust_authoring_module.prime_rust_mesh_preview_context(
            controller,
            preview_material_model,
            material_package_path=material_package_path,
            unavailable_reason=material_unavailable_reason,
            target_entry=target_entry,
            entries_by_basename=texture_entries_by_basename,
        )
        session = RustMeshAuthoringSession.create(
            controller,
            root,
            process_generation=7,
            theme={"density": "compact", "scale": 1.25},
        )
        return authoritative, session

    def test_package_contains_full_channel_and_owned_reference_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "session"
            authoritative, session = self._create(
                root,
                force_zero_index_offset=True,
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(RUST_MESH_AUTHORING_PACKAGE, manifest["schema"])
                self.assertEqual(RUST_MESH_EDITOR_PROTOCOL, manifest["protocol"])
                self.assertEqual(RUST_MESH_RENDERER, manifest["renderer"])
                self.assertEqual(RUST_MESH_EDIT_BACKEND, manifest["edit_backend"])
                self.assertEqual("mesh_document_json", manifest["document"]["data_type"])
                self.assertGreater(manifest["document"]["count"], 0)
                self.assertEqual(
                    "mesh_channels_compact_json",
                    manifest["channels"]["data_type"],
                )
                channels = read_owned_payload_reference(root, manifest["channels"])
                channel = channels["lods"][0]["submeshes"][0]
                self.assertEqual(
                    {
                        "path": "document.json",
                        "channels": ["positions", "normals", "uv0", "indices"],
                    },
                    channels["geometry_source"],
                )
                self.assertEqual(
                    {"lod_index": 0, "submesh_index": 0},
                    channel["document_submesh"],
                )
                self.assertNotIn("positions", channel)
                self.assertNotIn("normals", channel)
                self.assertIn("tangents", channel)
                self.assertNotIn("uv0", channel)
                self.assertIn("uv1", channel)
                self.assertNotIn("indices", channel)
                self.assertIn("bone_indices", channel)
                self.assertIn("bone_weights", channel)
                self.assertIn("source_vertex_map", channel)
                self.assertIn("source_face_map", channel)
                self.assertIn("topology_provenance", channel)
                self.assertEqual(0, channel["source_index_offset"])
                self.assertNotEqual(
                    False,
                    session.state_payload(include_document=False)["morph_refit"].get(
                        "available",
                        True,
                    ),
                )
                self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            finally:
                session.cancel()

    def test_package_reuses_canonical_material_presentation_for_each_lod_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "session"
            preview_material = SimpleNamespace(
                source_submesh_index=0,
                material="body",
                preview_sidecar_shader_family="SkinnedMeshStandard_Ver2",
                preview_normal_y_policy="invert_green_for_directx",
                preview_alpha_mode="cutout",
                preview_double_sided=True,
                preview_native_material_overrides={
                    "material_category": "metal",
                    "material_category_confidence": 0.92,
                    "roughness": 0.22,
                    "metalness": 0.81,
                    "specular": 0.73,
                    "emissive_color": [0.1, 0.2, 0.3],
                    "emissive_intensity": 2.5,
                    "height_scale": 0.08,
                    "alpha_cutoff": 0.17,
                },
            )
            authoritative, session = self._create(
                root,
                preview_material_model=SimpleNamespace(
                    path="owned-rust-authoring.pac",
                    meshes=[preview_material],
                ),
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                rows = manifest["material_presentations"]
                shadow_mesh = session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=False,
                )
                self.assertEqual(
                    sum(
                        len(level)
                        for level in rust_authoring_module._mesh_lods(shadow_mesh)
                    ),
                    len(rows),
                )
                row = next(
                    item
                    for item in rows
                    if item["lod_index"] == 0 and item["material_index"] == 0
                )
                self.assertEqual("metal", row["material_category"])
                self.assertEqual(1, row["category_code"])
                self.assertAlmostEqual(0.92, row["category_confidence"])
                self.assertEqual("standard_v2", row["shader_family"])
                self.assertEqual("invert_green_for_directx", row["normal_y_policy"])
                self.assertTrue(row["normal_y_inverted"])
                self.assertEqual("cutout", row["alpha_mode"])
                self.assertTrue(row["double_sided"])
                self.assertAlmostEqual(0.17, row["alpha_cutoff"])
                self.assertAlmostEqual(0.22, row["roughness"])
                self.assertAlmostEqual(0.81, row["metalness"])
                self.assertAlmostEqual(0.73, row["specular"])
                self.assertEqual([0.1, 0.2, 0.3], row["emissive_color"])
                self.assertAlmostEqual(2.5, row["emissive_intensity"])
                self.assertAlmostEqual(0.08, row["height_scale"])
                self.assertFalse(row["hair_anisotropy"])
            finally:
                session.cancel()
                authoritative.close_edit_session(
                    "authoritative-rust-test",
                    force_without_saving=True,
                )

    def test_exact_owner_height_scale_outranks_flattened_native_amount(self) -> None:
        exact_scale = PreviewMaterialParameterInput(
            parameter_kind="float",
            parameter_name="_screenSpaceDisplacementScale",
            numeric_value=0.216,
        )
        source = SimpleNamespace(
            preview_pac_material_owner_slot_index=0,
            preview_material_texture_inputs=(
                PreviewMaterialTextureInput(
                    parameter_name="_heightTexture",
                    semantic_type="height",
                    owner_slot_index=-1,
                    binding_authority="authoritative",
                    binding_disposition="recorded",
                    material_parameters=(
                        replace(exact_scale, numeric_value=0.9),
                    ),
                ),
                PreviewMaterialTextureInput(
                    parameter_name="_heightTexture",
                    semantic_type="height",
                    owner_slot_index=0,
                    binding_authority="authoritative",
                    binding_disposition="recorded",
                    material_parameters=(exact_scale,),
                ),
            ),
            preview_material_parameters=(),
            preview_native_material_overrides={"height_amount": 0.04},
        )
        mesh = SimpleNamespace(
            path="character/weapon/authored_height.pac",
            lod_levels=[],
            submeshes=[source],
        )
        with patch.object(
            rust_authoring_module,
            "mesh_dotnet_material_state_payload",
            return_value={
                "submeshes": [
                    {
                        "submesh_index": 0,
                        "material_slot_index": 0,
                        "parameters": {"height_amount": 0.04},
                    }
                ]
            },
        ):
            presentation = rust_authoring_module._mesh_material_presentations(mesh)[0]

        self.assertAlmostEqual(0.216, presentation["height_scale"])

    def test_surface_scales_are_not_reinterpreted_as_rust_scalar_targets(self) -> None:
        scale_only = {
            "roughness_scale": 0.2,
            "metalness_scale": 0.3,
        }
        mesh = SimpleNamespace(
            path="character/weapon/scaled_surface.pac",
            lod_levels=[],
            submeshes=[
                SimpleNamespace(
                    preview_native_material_overrides=dict(scale_only),
                )
            ],
        )
        with patch.object(
            rust_authoring_module,
            "mesh_dotnet_material_state_payload",
            return_value={
                "submeshes": [
                    {
                        "submesh_index": 0,
                        "material_slot_index": 0,
                        "parameters": dict(scale_only),
                    }
                ]
            },
        ):
            presentation = rust_authoring_module._mesh_material_presentations(mesh)[0]
        self.assertIsNone(presentation["roughness"])
        self.assertIsNone(presentation["metalness"])

    def test_generated_hair_tint_reaches_rust_without_changing_cutout(self) -> None:
        tint = [0.176471, 0.015686, 0.015686]
        generated = rust_authoring_module._rust_generated_presentation_overrides(
            {
                "alpha_mode": "cutout",
                "alpha_cutoff": 0.21,
                "double_sided": True,
                "parameters": {
                    "texture_tint": tint,
                    "base_tint_strength": 0.85,
                },
            },
            {"base_color"},
        )
        mesh = SimpleNamespace(
            path="character/armor/helmet_feather.pac",
            lod_levels=[],
            submeshes=[SimpleNamespace(preview_native_material_overrides={})],
        )
        with patch.object(
            rust_authoring_module,
            "mesh_dotnet_material_state_payload",
            return_value={
                "submeshes": [
                    {
                        "submesh_index": 0,
                        "material_slot_index": 0,
                        "parameters": {},
                    }
                ]
            },
        ):
            presentation = rust_authoring_module._mesh_material_presentations(
                mesh,
                generated_overrides={(0, 0): generated},
            )[0]

        self.assertEqual(tint, presentation["texture_tint"])
        self.assertAlmostEqual(0.85, presentation["base_tint_strength"])
        self.assertEqual("cutout", presentation["alpha_mode"])
        self.assertAlmostEqual(0.21, presentation["alpha_cutoff"])
        self.assertTrue(presentation["double_sided"])

    def test_real_skin_detail_bindings_keep_exact_roles_scale_and_opacity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = 0
            mask = root / "body_m.dds"
            normal = root / "skin_detail_n.dds"
            material = root / "skin_detail_sp.dds"
            for path, marker in ((mask, b"M"), (normal, b"N"), (material, b"S")):
                path.write_bytes(b"DDS " + marker * 64)
            parameters = (
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_skinDetailScale",
                    value="0.020000",
                    numeric_value=0.02,
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_skinDetailOpacity",
                    value="1.000000",
                    numeric_value=1.0,
                ),
            )
            skin_inputs = (
                PreviewMaterialTextureInput(
                    parameter_name="_skinDetailMaskTexture",
                    source_dds_path=str(mask),
                    layer_role="detail",
                    layer_channel="r",
                    binding_authority="authoritative",
                    owner_slot_index=owner,
                    material_parameters=parameters,
                ),
                PreviewMaterialTextureInput(
                    parameter_name="_skinDetailNormalTexture",
                    source_dds_path=str(normal),
                    layer_role="detail",
                    binding_authority="authoritative",
                    owner_slot_index=owner,
                    material_parameters=parameters,
                ),
                PreviewMaterialTextureInput(
                    parameter_name="_skinDetailMaterialTexture",
                    source_dds_path=str(material),
                    layer_role="detail",
                    binding_authority="authoritative",
                    owner_slot_index=owner,
                    material_parameters=parameters,
                ),
            )
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=owner,
                preview_material_texture_inputs=skin_inputs,
                preview_native_material_overrides={
                    "material_category": "skin",
                    "material_category_confidence": 0.95,
                },
            )
            mesh = SimpleNamespace(
                path="character/model/skin.pac",
                lod_levels=[],
                submeshes=[submesh],
            )
            session_root = root / "session"
            session_root.mkdir()
            resources = rust_authoring_module._mesh_texture_payloads(
                session_root,
                mesh,
                expected_root_identity=rust_authoring_module._session_root_identity(
                    session_root
                ),
            )
            self.assertEqual(
                {
                    "skin_detail_mask",
                    "skin_detail_normal",
                    "skin_detail_material",
                },
                {row["role"] for row in resources},
            )
            self.assertTrue(
                all(row["material_indices_by_lod"] == [[0]] for row in resources)
            )

            with patch.object(
                rust_authoring_module,
                "mesh_dotnet_material_state_payload",
                return_value={
                    "submeshes": [
                        {
                            "submesh_index": 0,
                            "material_slot_index": 0,
                            "material_category": "skin",
                            "material_category_confidence": 0.95,
                            "shader_family": "skin",
                        }
                    ]
                },
            ):
                presentation = rust_authoring_module._mesh_material_presentations(mesh)[0]
            self.assertAlmostEqual(0.02, presentation["skin_detail_scale"])
            self.assertAlmostEqual(1.0, presentation["skin_detail_opacity"])

    def test_exact_pac_skin_graph_promotes_generic_package_category(self) -> None:
        owner = 2

        def skin_input(
            parameter_name: str,
            *,
            source_kind: str,
        ) -> PreviewMaterialTextureInput:
            return PreviewMaterialTextureInput(
                parameter_name=parameter_name,
                shader_family="SkinnedMeshSkin",
                binding_authority="authoritative",
                owner_slot_index=owner,
                source_kind=source_kind,
            )

        submesh = SimpleNamespace(
            preview_pac_material_owner_slot_index=owner,
            preview_material_texture_inputs=(
                skin_input(
                    "_materialTexture",
                    source_kind="crimson_skin_material_response",
                ),
                skin_input(
                    "_skinDetailMaskTexture",
                    source_kind="crimson_skin_detail_mask",
                ),
                skin_input(
                    "_skinDetailNormalTexture",
                    source_kind="crimson_layer_normal",
                ),
                skin_input(
                    "_skinDetailMaterialTexture",
                    source_kind="crimson_skin_material_response",
                ),
            ),
        )
        mesh = SimpleNamespace(
            path="character/model/skin.pac",
            lod_levels=[],
            submeshes=[submesh],
        )
        generic_state = {
            "submeshes": [
                {
                    "submesh_index": 0,
                    "material_slot_index": owner,
                    "material_category": "generic",
                    "material_category_confidence": 0.70,
                    "shader_family": "skin",
                }
            ]
        }

        with patch.object(
            rust_authoring_module,
            "mesh_dotnet_material_state_payload",
            return_value=generic_state,
        ):
            presentation = rust_authoring_module._mesh_material_presentations(mesh)[0]

        self.assertEqual("skin", presentation["material_category"])
        self.assertEqual(5, presentation["category_code"])
        self.assertEqual(0.95, presentation["category_confidence"])

        submesh.preview_pac_material_owner_slot_index = -1
        self.assertFalse(
            rust_authoring_module._rust_has_exact_skin_category_evidence(
                submesh,
                "skin",
            )
        )
        submesh.preview_pac_material_owner_slot_index = owner

        submesh.preview_material_texture_inputs = tuple(
            replace(item, owner_slot_index=-1)
            if item.parameter_name == "_skinDetailMaskTexture"
            else item
            for item in submesh.preview_material_texture_inputs
        )
        self.assertFalse(
            rust_authoring_module._rust_has_exact_skin_category_evidence(
                submesh,
                "skin",
            )
        )
        submesh.preview_material_texture_inputs = tuple(
            replace(item, owner_slot_index=owner)
            if item.parameter_name == "_skinDetailMaskTexture"
            else item
            for item in submesh.preview_material_texture_inputs
        )

        submesh.preview_material_texture_inputs = tuple(
            replace(item, owner_slot_index=7)
            if item.parameter_name == "_skinDetailNormalTexture"
            else item
            for item in submesh.preview_material_texture_inputs
        )
        self.assertFalse(
            rust_authoring_module._rust_has_exact_skin_category_evidence(
                submesh,
                "skin",
            )
        )

    def test_native_skin_detail_support_layer_carries_real_scale_and_weight(self) -> None:
        owner = 3
        skin_inputs = tuple(
            PreviewMaterialTextureInput(
                parameter_name=parameter_name,
                binding_authority="authoritative",
                owner_slot_index=owner,
            )
            for parameter_name in (
                "_skinDetailMaskTexture",
                "_skinDetailNormalTexture",
                "_skinDetailMaterialTexture",
            )
        )
        foreign_skin_detail = PreviewMaterialTextureInput(
            parameter_name="_skinDetailMaskTexture",
            binding_authority="authoritative",
            owner_slot_index=9,
            material_parameters=(
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_skinDetailScale",
                    numeric_value=0.42,
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_skinDetailOpacity",
                    numeric_value=0.25,
                ),
            ),
        )
        source = SimpleNamespace(
            preview_pac_material_owner_slot_index=owner,
            preview_material_texture_inputs=(foreign_skin_detail, *skin_inputs),
            preview_native_material_overrides={
                "material_layers": [
                    {
                        "layer_role": "skin_detail",
                        "source_parameter": "_skinDetailMaskTexture",
                        "mask_parameter": "_skinDetailMaskTexture",
                        "detail_scale": 0.05,
                        "weight": 1.0,
                    }
                ]
            },
        )
        self.assertEqual(
            (0.05, 1.0),
            rust_authoring_module._rust_skin_detail_factors(source),
        )

        source.preview_native_material_overrides["material_layers"][0].update(
            {
                "layer_role": "detail",
                "source_parameter": "_detailMaskTexture",
                "mask_parameter": "_detailMaskTexture",
            }
        )
        self.assertEqual(
            (None, None),
            rust_authoring_module._rust_skin_detail_factors(source),
        )

    def test_package_copies_resolved_dds_textures_into_hashed_owned_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            source_texture = temporary_root / "body_base.dds"
            source_bytes = b"DDS " + bytes(range(128))
            source_texture.write_bytes(source_bytes)
            session_root = temporary_root / "session"
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=AssertionError(
                    "a simple direct DDS must not enter material synthesis"
                ),
            ):
                _authoritative, session = self._create(
                    session_root,
                    base_texture_path=source_texture,
                )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                resources = manifest["textures"]
                self.assertEqual(1, len(resources))
                resource = resources[0]
                self.assertEqual("base_color", resource["role"])
                self.assertEqual([[0]], resource["material_indices_by_lod"])
                reference = resource["file"]
                self.assertRegex(reference["path"], r"^texture-0000-[0-9a-f]{12}\.dds$")
                copied = session_root / reference["path"]
                self.assertEqual(source_bytes, copied.read_bytes())
                self.assertEqual(
                    hashlib.sha256(source_bytes).hexdigest().upper(),
                    reference["sha256"],
                )
                self.assertNotEqual(source_texture.resolve(), copied.resolve())
                rust_authoring_module._validate_owned_session_tree(
                    session_root,
                    session.root_identity,
                )
            finally:
                session.cancel()

    def test_layered_material_prefers_owner_conserved_composite_base(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            direct_texture = temporary_root / "sword_base.dds"
            direct_bytes = b"DDS direct-neutral-base"
            direct_texture.write_bytes(direct_bytes)
            generated_dds = {
                "base": b"DDS authoritative-layered-colour",
                "normal": b"DDS authoritative-layered-normal",
            }
            compiler_roots: list[Path] = []

            preview_material = SimpleNamespace(
                source_submesh_index=0,
                material="layered_sword",
                texture="sword_base",
                preview_texture_dds_path="",
                preview_normal_texture_dds_path=str(direct_texture),
                preview_normal_y_policy="invert_green_for_directx",
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="base",
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(direct_texture),
                        preview_texture_path=str(direct_texture),
                        semantic_type="albedo",
                        semantic_subtype="base_color",
                        shader_family="Standard_Ver2",
                    ),
                    PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_detailColorTexture",
                        source_dds_path=str(direct_texture),
                        preview_texture_path=str(direct_texture),
                        semantic_type="color",
                        semantic_subtype="detail_diffuse",
                        shader_family="Standard_Ver2",
                        layer_role="detail",
                        layer_channel="g",
                        visualized=True,
                    ),
                ),
            )

            def compile_material(mesh, **kwargs):
                package_dir = Path(kwargs["package_dir"])
                compiler_roots.append(package_dir.parent)
                rows: list[dict[str, object]] = []
                for index, submesh in enumerate(tuple(mesh.submeshes)):
                    if tuple(
                        getattr(submesh, "preview_material_texture_inputs", ()) or ()
                    ):
                        generated = (
                            package_dir
                            / "material_synthesis"
                            / f"submesh_{index:03d}"
                            / "base.png"
                        )
                        generated.parent.mkdir(parents=True, exist_ok=True)
                        generated.write_bytes(b"authoritative generated image")
                        generated_normal = generated.with_name("normal.png")
                        generated_normal.write_bytes(
                            b"authoritative generated normal image"
                        )
                        rows.append(
                            {
                                "resolved_channels": {
                                    "base": str(generated),
                                    "albedo": str(generated),
                                    "diffuse": str(generated),
                                    "normal": str(generated_normal),
                                },
                                "normal_y_policy": "preserve",
                                "alpha_mode": "cutout",
                                "alpha_cutoff": 0.23,
                                "double_sided": True,
                                "binding_conservation": {
                                    "conserved": True,
                                    "cross_owner_bindings": [],
                                    "layer_as_base_bindings": [],
                                },
                                "material_synthesis": {
                                    "succeeded": True,
                                    "generated_channels": [
                                        "base",
                                        "albedo",
                                        "diffuse",
                                        "normal",
                                    ],
                                },
                            }
                        )
                    else:
                        rows.append(
                            {
                                "resolved_channels": {},
                                "material_synthesis": {
                                    "succeeded": False,
                                    "generated_channels": [],
                                },
                            }
                        )
                return {"submeshes": rows}

            encoded_policies: dict[str, str] = {}

            def encode_material(
                source,
                target,
                channel,
                stop_event,
                *,
                source_color_policy="auto",
                preview_uncompressed_max_bytes=0,
            ):
                self.assertIn(channel, {"base", "normal"})
                self.assertTrue(Path(source).is_file())
                self.assertFalse(stop_event.is_set())
                encoded_policies[channel] = source_color_policy
                self.assertGreater(preview_uncompressed_max_bytes, 0)
                Path(target).write_bytes(generated_dds[channel])
                return {
                    "content_sha256": hashlib.sha256(
                        generated_dds[channel]
                    ).hexdigest(),
                    "byte_count": len(generated_dds[channel]),
                }

            session_root = temporary_root / "session"
            pin_root = rust_authoring_module._pinned_session_root
            guard_metrics = {
                "direct_mean_luma": 0.25,
                "generated_mean_luma": 0.75,
                "capped_mean_luma": 0.30,
                "rgb_scale": 0.40,
                "sampling_basis": "surface_uv0_repeat_linear",
                "sample_count": 7,
            }
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ) as compiler, patch.object(
                rust_authoring_module,
                "_encode_owned_dds",
                side_effect=encode_material,
            ) as encoder, patch.object(
                rust_authoring_module,
                "_guard_synthesized_base_against_direct",
                side_effect=lambda source, *_args, **_kwargs: (
                    source,
                    guard_metrics,
                ),
            ) as luminance_guard, patch.object(
                rust_authoring_module,
                "_pinned_session_root",
                wraps=pin_root,
            ) as pinned_root:
                _authoritative, session = self._create(
                    session_root,
                    preview_material_model=SimpleNamespace(
                        path="character/weapon/layered_sword.pac",
                        meshes=[preview_material],
                    ),
                )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                resources_by_role = {
                    resource["role"]: resource for resource in manifest["textures"]
                }
                base_resources = [resources_by_role["base_color"]]
                self.assertEqual(1, len(base_resources))
                packaged = session_root / base_resources[0]["file"]["path"]
                self.assertEqual(generated_dds["base"], packaged.read_bytes())
                packaged_normal = (
                    session_root / resources_by_role["normal"]["file"]["path"]
                )
                self.assertEqual(direct_bytes, packaged_normal.read_bytes())
                presentation = manifest["material_presentations"][0]
                self.assertEqual(
                    "invert_green_for_directx",
                    presentation["normal_y_policy"],
                )
                self.assertTrue(presentation["normal_y_inverted"])
                synthesis_status = manifest["texture_status"]["material_synthesis"]
                self.assertTrue(synthesis_status["attempted"])
                self.assertEqual(1, synthesis_status["generated_binding_count"])
                self.assertFalse(synthesis_status["degraded"])
                self.assertEqual([], synthesis_status["warnings"])
                guard_status = synthesis_status["base_luminance_guard"]
                self.assertTrue(guard_status["applied"])
                self.assertEqual(1, guard_status["adjusted_owner_count"])
                self.assertEqual(
                    [
                        {
                            **guard_metrics,
                            "code": "generated_base_luminance_capped",
                            "lod_index": 0,
                            "submesh_index": 0,
                        }
                    ],
                    guard_status["adjustments"],
                )
                self.assertEqual(0, guard_status["dropped_adjustment_count"])
                self.assertEqual(direct_bytes, direct_texture.read_bytes())
                self.assertGreaterEqual(compiler.call_count, 1)
                self.assertEqual(1, encoder.call_count)
                self.assertEqual({"base": "assume_srgb"}, encoded_policies)
                self.assertEqual(1, luminance_guard.call_count)
                self.assertTrue(
                    any(
                        Path(call.args[0]).name.startswith(
                            "cdmw-rust-material-synthesis-"
                        )
                        for call in pinned_root.call_args_list
                    ),
                    "the disposable compiler/encoder tree must remain pinned",
                )
                self.assertTrue(compiler_roots)
                self.assertTrue(all(not root.exists() for root in compiler_roots))
                rust_authoring_module._validate_owned_session_tree(
                    session_root,
                    session.root_identity,
                )
            finally:
                session.cancel()

    def test_equipment_publishes_conserved_scalar_surface_maps_as_linear_roles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            packed_surface = temporary_root / "sword_sp.dds"
            packed_surface_bytes = b"DDS exact packed equipment surface"
            packed_surface.write_bytes(packed_surface_bytes)
            preview_material = SimpleNamespace(
                source_submesh_index=0,
                preview_pac_material_owner_slot_index=0,
                material="layered_sword",
                preview_material_texture_dds_path=str(packed_surface),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_materialTexture",
                        source_dds_path=str(packed_surface),
                        preview_texture_path=str(packed_surface),
                        semantic_type="material",
                        shader_family="SkinnedMeshStandard_Ver2",
                        owner_slot_index=0,
                        binding_authority="authoritative",
                        binding_disposition="promoted",
                    ),
                ),
            )

            generated_payloads = {
                "roughness": b"canonical roughness",
                "metallic": b"canonical metalness",
                "occlusion": b"canonical occlusion",
                "specular": b"canonical specular",
            }

            def compile_material(_mesh, **kwargs):
                generated_root = (
                    Path(kwargs["package_dir"])
                    / "material_synthesis"
                    / "submesh_000"
                )
                generated_root.mkdir(parents=True, exist_ok=True)
                resolved_channels: dict[str, str] = {}
                for channel, payload in generated_payloads.items():
                    generated = generated_root / f"{channel}.png"
                    generated.write_bytes(payload)
                    resolved_channels[channel] = str(generated)
                return {
                    "submeshes": [
                        {
                            "shader_family": "standard_v2",
                            "resolved_channels": resolved_channels,
                            "binding_conservation": {
                                "conserved": True,
                                "cross_owner_bindings": [],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "attempted": True,
                                "succeeded": True,
                                "generated_channels": list(generated_payloads),
                            },
                        }
                    ]
                }

            encoded_policies: dict[str, str] = {}

            def encode_surface(
                source,
                target,
                channel,
                _stop_event,
                *,
                source_color_policy="auto",
                preview_uncompressed_max_bytes=0,
            ):
                source_payload = Path(source).read_bytes()
                expected_source_channel = (
                    "metallic" if channel == "metalness" else channel
                )
                self.assertEqual(
                    generated_payloads[expected_source_channel],
                    source_payload,
                )
                self.assertEqual("ignore_srgb_metadata", source_color_policy)
                encoded_policies[channel] = source_color_policy
                self.assertGreater(preview_uncompressed_max_bytes, 0)
                payload = b"DDS generated " + channel.encode("ascii")
                Path(target).write_bytes(payload)
                return {
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_count": len(payload),
                }

            session_root = temporary_root / "session"
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ), patch.object(
                rust_authoring_module,
                "_encode_owned_dds",
                side_effect=encode_surface,
            ):
                _authoritative, session = self._create(
                    session_root,
                    preview_material_model=SimpleNamespace(
                        path="character/weapon/layered_sword.pac",
                        meshes=[preview_material],
                    ),
                    material_name="layered_sword",
                )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                resources = {row["role"]: row for row in manifest["textures"]}
                self.assertTrue(
                    {
                        "material",
                        "roughness",
                        "metalness",
                        "occlusion",
                        "specular",
                    }.issubset(resources)
                )
                self.assertEqual(
                    packed_surface_bytes,
                    (session_root / resources["material"]["file"]["path"]).read_bytes(),
                )
                for role in ("roughness", "metalness", "occlusion", "specular"):
                    self.assertEqual([[0]], resources[role]["material_indices_by_lod"])
                    self.assertEqual(
                        b"DDS generated " + role.encode("ascii"),
                        (session_root / resources[role]["file"]["path"]).read_bytes(),
                    )
                self.assertEqual(
                    {
                        "roughness": "ignore_srgb_metadata",
                        "metalness": "ignore_srgb_metadata",
                        "occlusion": "ignore_srgb_metadata",
                        "specular": "ignore_srgb_metadata",
                    },
                    encoded_policies,
                )
                synthesis_status = manifest["texture_status"]["material_synthesis"]
                self.assertEqual(4, synthesis_status["generated_binding_count"])
                self.assertFalse(synthesis_status["degraded"])
            finally:
                session.cancel()

    def test_skin_keeps_exact_packed_sp_instead_of_generated_scalar_maps(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            skin_response = temporary_root / "skin_sp.dds"
            skin_response_bytes = b"DDS exact skin R-subsurface G-roughness"
            skin_response.write_bytes(skin_response_bytes)
            preview_material = SimpleNamespace(
                source_submesh_index=0,
                preview_pac_material_owner_slot_index=0,
                material="skin",
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_materialTexture",
                        source_dds_path=str(skin_response),
                        preview_texture_path=str(skin_response),
                        semantic_type="material",
                        source_kind="crimson_skin_material_response",
                        shader_family="SkinnedMeshSkin",
                        owner_slot_index=0,
                        binding_authority="authoritative",
                        binding_disposition="promoted",
                    ),
                ),
            )

            def compile_material(_mesh, **kwargs):
                generated_root = (
                    Path(kwargs["package_dir"])
                    / "material_synthesis"
                    / "submesh_000"
                )
                generated_root.mkdir(parents=True, exist_ok=True)
                roughness = generated_root / "roughness.png"
                specular = generated_root / "specular.png"
                roughness.write_bytes(b"compiler scalar roughness")
                specular.write_bytes(b"compiler scalar specular")
                return {
                    "submeshes": [
                        {
                            "shader_family": "skin",
                            "resolved_channels": {
                                "roughness": str(roughness),
                                "specular": str(specular),
                            },
                            "binding_conservation": {
                                "conserved": True,
                                "cross_owner_bindings": [],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "attempted": True,
                                "succeeded": True,
                                "generated_channels": ["roughness", "specular"],
                            },
                        }
                    ]
                }

            session_root = temporary_root / "session"
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ), patch.object(
                rust_authoring_module,
                "_encode_owned_dds",
            ) as encoder:
                _authoritative, session = self._create(
                    session_root,
                    preview_material_model=SimpleNamespace(
                        path="character/model/skin.pac",
                        meshes=[preview_material],
                    ),
                    material_name="skin",
                )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                resources = {row["role"]: row for row in manifest["textures"]}
                self.assertEqual({"specular"}, set(resources))
                self.assertEqual(
                    skin_response_bytes,
                    (session_root / resources["specular"]["file"]["path"]).read_bytes(),
                )
                self.assertEqual([[0]], resources["specular"]["material_indices_by_lod"])
                self.assertEqual(
                    0,
                    manifest["texture_status"]["material_synthesis"][
                        "generated_binding_count"
                    ],
                )
                encoder.assert_not_called()
            finally:
                session.cancel()

    def test_proven_layered_normal_replaces_direct_normal_at_2048_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            synthesis_root = root / "synthesis"
            synthesis_root.mkdir()
            direct_normal = root / "direct_normal.dds"
            direct_normal.write_bytes(b"DDS direct normal")
            submesh = SimpleNamespace(
                preview_normal_texture_dds_path=str(direct_normal),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="normal",
                        parameter_name="_normalTexture",
                        source_dds_path=str(direct_normal),
                    ),
                    PreviewMaterialTextureInput(
                        slot_kind="normal",
                        parameter_name="_detailNormalMaskR",
                        source_dds_path=str(direct_normal),
                        layer_role="detail",
                        layer_channel="r",
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/armor/layered_cloth.pac",
                lod_levels=[],
                submeshes=[submesh],
            )

            def compile_material(_mesh, **kwargs):
                self.assertEqual(2048, kwargs["support_map_max_dimension"])
                generated = (
                    Path(kwargs["package_dir"])
                    / "material_synthesis"
                    / "submesh_000"
                    / "normal.png"
                )
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"masked whiteout normal")
                return {
                    "submeshes": [
                        {
                            "resolved_channels": {"normal": str(generated)},
                            "binding_conservation": {
                                "conserved": True,
                                "cross_owner_bindings": [],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "attempted": True,
                                "succeeded": True,
                                "generated_channels": ["normal"],
                                "notes": ["normal layers synthesized:detail:r"],
                            },
                        }
                    ]
                }

            def encode_normal(source, target, channel, _stop_event, **_options):
                self.assertEqual("normal", channel)
                self.assertEqual(b"masked whiteout normal", Path(source).read_bytes())
                Path(target).write_bytes(b"DDS layered normal")
                return {"byte_count": 18, "content_sha256": "0" * 64}

            state = rust_authoring_module._RustMaterialSynthesisState()
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ), patch.object(
                rust_authoring_module,
                "_encode_owned_dds",
                side_effect=encode_normal,
            ):
                overrides = rust_authoring_module._mesh_synthesized_texture_overrides(
                    mesh,
                    synthesis_root,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        synthesis_root
                    ),
                    stop_event=None,
                    synthesis_state=state,
                )

            self.assertEqual({(0, 0, "normal")}, set(overrides))
            self.assertEqual(
                b"DDS layered normal",
                overrides[(0, 0, "normal")].read_bytes(),
            )
            self.assertEqual(1, state.generated_binding_count)

    def test_conserved_generated_base_replaces_exact_overlay_ingredient(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            synthesis_root = root / "synthesis"
            synthesis_root.mkdir()
            overlay = root / "overlay.dds"
            flat_selector = root / "selector_mg.dds"
            overlay.write_bytes(b"DDS overlay ingredient")
            flat_selector.write_bytes(b"DDS selector")
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=4,
                preview_texture_dds_path=str(flat_selector),
                texture=str(flat_selector),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="base",
                        parameter_name="_overlayColorTexture",
                        source_dds_path=str(overlay),
                        owner_slot_index=4,
                        binding_authority="authoritative",
                        binding_disposition="promoted",
                        source_kind="crimson_overlay_color",
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/weapon/layered_sword.pac",
                lod_levels=[],
                submeshes=[submesh],
            )

            def compile_material(_mesh, **kwargs):
                generated = (
                    Path(kwargs["package_dir"])
                    / "material_synthesis"
                    / "submesh_000"
                    / "albedo.png"
                )
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"complete PAC albedo composite")
                return {
                    "submeshes": [
                        {
                            "resolved_channels": {"base": str(generated)},
                            "binding_conservation": {
                                "conserved": True,
                                "cross_owner_bindings": [],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "attempted": True,
                                "succeeded": True,
                                "generated_channels": ["base"],
                            },
                        }
                    ]
                }

            def encode_base(source, target, channel, _stop_event, **options):
                self.assertEqual("base", channel)
                self.assertEqual("assume_srgb", options["source_color_policy"])
                self.assertEqual(
                    b"complete PAC albedo composite",
                    Path(source).read_bytes(),
                )
                Path(target).write_bytes(b"DDS complete PAC albedo")
                return {"byte_count": 23, "content_sha256": "0" * 64}

            state = rust_authoring_module._RustMaterialSynthesisState()
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ), patch.object(
                rust_authoring_module,
                "_encode_owned_dds",
                side_effect=encode_base,
            ), patch.object(
                rust_authoring_module,
                "_guard_synthesized_base_against_direct",
                side_effect=lambda source, *_args, **_kwargs: (source, None),
            ):
                overrides = rust_authoring_module._mesh_synthesized_texture_overrides(
                    mesh,
                    synthesis_root,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        synthesis_root
                    ),
                    stop_event=None,
                    synthesis_state=state,
                )

            self.assertEqual({(0, 0, "base_color")}, set(overrides))
            self.assertEqual(
                b"DDS complete PAC albedo",
                overrides[(0, 0, "base_color")].read_bytes(),
            )
            self.assertEqual(1, state.generated_binding_count)

    def test_material_synthesis_noop_is_not_reported_as_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            synthesis_root = root / "synthesis"
            synthesis_root.mkdir()
            direct_base = root / "direct_base.dds"
            direct_base.write_bytes(b"DDS direct base")
            submesh = SimpleNamespace(
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="base",
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(direct_base),
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/armor/direct_only_leather.pac",
                lod_levels=[],
                submeshes=[submesh],
            )

            def compile_material(_mesh, **_kwargs):
                return {
                    "submeshes": [
                        {
                            "resolved_channels": {},
                            "material_synthesis": {
                                "attempted": True,
                                "succeeded": False,
                                "generated_channels": [],
                            },
                        }
                    ]
                }

            state = rust_authoring_module._RustMaterialSynthesisState()
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ):
                overrides = rust_authoring_module._mesh_synthesized_texture_overrides(
                    mesh,
                    synthesis_root,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        synthesis_root
                    ),
                    stop_event=None,
                    synthesis_state=state,
                )

            self.assertEqual({}, overrides)
            self.assertTrue(state.attempted)
            self.assertEqual([], state.diagnostics)
            self.assertEqual(0, state.dropped_diagnostic_count)

    def test_exact_material_texture_outranks_layer_selector_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selector_mask = root / "armor_m.dds"
            packed_surface = root / "armor_sp.dds"
            selector_mask.write_bytes(b"DDS selector mask")
            packed_surface.write_bytes(b"DDS packed surface")
            source = SimpleNamespace(
                preview_material_texture_dds_path=str(selector_mask),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_maskTexture",
                        source_dds_path=str(selector_mask),
                    ),
                    PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_materialTexture",
                        source_dds_path=str(packed_surface),
                    ),
                ),
            )
            material_attributes = next(
                attributes
                for role, attributes in rust_authoring_module._TEXTURE_RESOURCE_SPECS
                if role == "material"
            )

            resolved = rust_authoring_module._first_texture_resource_dds_path(
                source,
                "material",
                material_attributes,
            )

            self.assertEqual(packed_surface.resolve(), resolved)

    def test_exact_material_inputs_suppress_selector_and_family_material_guesses(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selector_mask = root / "armor_m.dds"
            selector_mask.write_bytes(b"DDS selector mask")
            source = SimpleNamespace(
                preview_material_texture_dds_path=str(selector_mask),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_maskTexture",
                        texture_name="authored_selector_m.dds",
                        source_dds_path=str(selector_mask),
                        semantic_type="material",
                    ),
                ),
            )
            material_attributes = next(
                attributes
                for role, attributes in rust_authoring_module._TEXTURE_RESOURCE_SPECS
                if role == "material"
            )

            self.assertIsNone(
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "material",
                    material_attributes,
                )
            )
            candidates = rust_authoring_module._rust_texture_candidate_basenames(
                (("armor", "armor"),),
                exact_basenames=("authored_selector_m.dds",),
            )
            self.assertIn("authored_selector_m.dds", candidates)
            self.assertNotIn("armor_m.dds", candidates)
            self.assertNotIn("armor_sp.dds", candidates)

    def test_exact_parameter_semantics_preserve_skin_specular_response(self) -> None:
        self.assertEqual(
            "material",
            rust_authoring_module._material_input_texture_role(
                PreviewMaterialTextureInput(
                    parameter_name="_materialTexture",
                    semantic_type="roughness",
                    shader_family="standard",
                )
            ),
        )
        self.assertEqual(
            "specular",
            rust_authoring_module._material_input_texture_role(
                PreviewMaterialTextureInput(
                    parameter_name="_materialTexture",
                    semantic_type="material",
                    source_kind="crimson_skin_material_response",
                    shader_family="skin",
                )
            ),
        )
        self.assertEqual(
            "material",
            rust_authoring_module._material_input_texture_role(
                PreviewMaterialTextureInput(
                    parameter_name="_materialTexture",
                    semantic_type="specular",
                    shader_family="standard",
                )
            ),
        )
        self.assertEqual(
            "layer_mask",
            rust_authoring_module._material_input_texture_role(
                PreviewMaterialTextureInput(
                    parameter_name="_maskTexture",
                    semantic_type="material",
                )
            ),
        )
        self.assertEqual(
            "emissive",
            rust_authoring_module._material_input_texture_role(
                PreviewMaterialTextureInput(
                    parameter_name="_emissiveIntensityTexture",
                    semantic_type="material",
                )
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skin_response = root / "skin_sp.dds"
            skin_response.write_bytes(b"DDS skin response")
            skin_input = PreviewMaterialTextureInput(
                parameter_name="_materialTexture",
                source_dds_path=str(skin_response),
                semantic_type="material",
                source_kind="crimson_skin_material_response",
                shader_family="skin",
            )
            source = SimpleNamespace(
                preview_material_texture_dds_path=str(skin_response),
                preview_material_texture_inputs=(skin_input,),
            )
            material_attributes = next(
                attributes
                for role, attributes in rust_authoring_module._TEXTURE_RESOURCE_SPECS
                if role == "material"
            )
            self.assertIsNone(
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "material",
                    material_attributes,
                )
            )

    def test_leased_material_package_restores_exact_owner_category(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary).resolve()
            (package_root / "net_materials.json").write_text(
                json.dumps(
                    {
                        "submeshes": [
                            {
                                "submesh_index": 0,
                                "material": "Aeron Plate",
                                "material_category": "metal",
                                "material_category_confidence": 0.88,
                                "shader_family": "standard",
                                "normal_y_policy": "preserve",
                                "alpha_mode": "opaque",
                                "alpha_cutoff": 0.5,
                                "double_sided": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            mesh = SimpleNamespace(
                path="character/armor/aeron_plate.pac",
                active_lod_index=0,
                lod_levels=[],
                submeshes=[SimpleNamespace(material="Aeron Plate")],
            )

            overrides = (
                rust_authoring_module._rust_material_package_presentation_overrides(
                    mesh,
                    package_root,
                    stop_event=None,
                )
            )

            self.assertEqual("metal", overrides[(0, 0)]["material_category"])
            self.assertEqual(
                0.88,
                overrides[(0, 0)]["material_category_confidence"],
            )

    def test_generated_normal_rejects_cross_owner_material_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            synthesis_root = root / "synthesis"
            synthesis_root.mkdir()
            direct_normal = root / "direct_normal.dds"
            direct_normal.write_bytes(b"DDS direct normal")
            submesh = SimpleNamespace(
                preview_normal_texture_dds_path=str(direct_normal),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="normal",
                        parameter_name="_normalTexture",
                        source_dds_path=str(direct_normal),
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/weapon/duplicate_owner.pac",
                lod_levels=[],
                submeshes=[submesh],
            )

            def compile_material(_mesh, **kwargs):
                generated = Path(kwargs["package_dir"]) / "normal.png"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"cross-owner normal")
                return {
                    "submeshes": [
                        {
                            "resolved_channels": {"normal": str(generated)},
                            "binding_conservation": {
                                "conserved": False,
                                "cross_owner_bindings": [{"owner": 4}],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "succeeded": True,
                                "generated_channels": ["normal"],
                                "notes": ["normal layers synthesized:detail:r"],
                            },
                        }
                    ]
                }

            state = rust_authoring_module._RustMaterialSynthesisState()
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ), patch.object(rust_authoring_module, "_encode_owned_dds") as encoder:
                overrides = rust_authoring_module._mesh_synthesized_texture_overrides(
                    mesh,
                    synthesis_root,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        synthesis_root
                    ),
                    stop_event=None,
                    synthesis_state=state,
                )

            self.assertEqual({}, overrides)
            encoder.assert_not_called()
            self.assertEqual(
                "compiler_owner_conservation_failed",
                state.diagnostics[0]["code"],
            )

    def test_exact_owner_direct_fallbacks_fill_only_missing_compositor_group(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            paths = {
                role: root / f"owner7_{role}.dds"
                for role in ("base_color", "normal", "material", "height")
            }
            for role, path in paths.items():
                path.write_bytes(b"DDS " + role.encode("ascii"))
            parameters = {
                "base_color": ("_baseColorTexture", "color", "promoted"),
                "normal": ("_normalTexture", "normal", "promoted"),
                "material": (
                    "_materialTexture",
                    "packed_material",
                    "layer_material_response",
                ),
                "height": ("_heightTexture", "height", "recorded"),
            }
            inputs = tuple(
                PreviewMaterialTextureInput(
                    slot_kind=role,
                    parameter_name=parameter_name,
                    source_dds_path=str(paths[role]),
                    semantic_type=semantic,
                    owner_slot_index=7,
                    binding_authority="exact",
                    binding_disposition=disposition,
                )
                for role, (parameter_name, semantic, disposition) in parameters.items()
            )
            source = SimpleNamespace(
                preview_pac_material_owner_slot_index=7,
                preview_material_texture_inputs=inputs,
            )
            row = {
                "direct_fallback_channels": {
                    role: {
                        "path": str(paths[role]),
                        "owner_slot_index": 7,
                        "owner_attribution": "source_submesh_index",
                        "parameter_name": parameter_name,
                        "binding_authority": "exact",
                        "binding_disposition": disposition,
                        "semantic": semantic,
                    }
                    for role, (parameter_name, semantic, disposition) in parameters.items()
                }
            }

            def fallback_roles(applied_roles: set[str]) -> set[str]:
                return {
                    key[2]
                    for key in rust_authoring_module._rust_exact_direct_fallback_overrides(
                        row,
                        source,
                        lod_index=0,
                        submesh_index=0,
                        protected_keys=frozenset(),
                        applied_roles=applied_roles,
                    )
                }

            self.assertEqual(
                {"base_color", "normal", "material", "height"},
                fallback_roles(set()),
            )
            self.assertEqual(
                {"base_color", "normal", "height"},
                fallback_roles({"roughness"}),
            )
            self.assertEqual(
                {"normal", "material", "height"},
                fallback_roles({"base_color"}),
            )
            self.assertEqual(
                {"normal", "height"},
                fallback_roles({"base_color", "roughness"}),
            )
            self.assertEqual(
                {"normal", "height"},
                fallback_roles(
                    {"base_color", "occlusion", "roughness", "specular"}
                ),
            )
            self.assertEqual(
                set(),
                fallback_roles(
                    {
                        "base_color",
                        "normal",
                        "roughness",
                        "height",
                    }
                ),
            )

            cross_owner = copy.deepcopy(row)
            for entry in cross_owner["direct_fallback_channels"].values():
                entry["owner_slot_index"] = 8
            self.assertEqual(
                {},
                rust_authoring_module._rust_exact_direct_fallback_overrides(
                    cross_owner,
                    source,
                    lod_index=0,
                    submesh_index=0,
                    protected_keys=frozenset(),
                    applied_roles=set(),
                ),
            )

    def test_nonconserved_generated_owner_uses_exact_direct_source_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            synthesis_root = root / "synthesis"
            synthesis_root.mkdir()
            paths = {
                role: root / f"owner5_{role}.dds"
                for role in ("base_color", "normal", "material", "height")
            }
            for role, path in paths.items():
                path.write_bytes(b"DDS " + role.encode("ascii"))
            parameters = {
                "base_color": ("_baseColorTexture", "color", "promoted"),
                "normal": ("_normalTexture", "normal", "promoted"),
                "material": (
                    "_materialTexture",
                    "packed_material",
                    "layer_material_response",
                ),
                "height": ("_heightTexture", "height", "recorded"),
            }
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=5,
                preview_material_texture_inputs=tuple(
                    PreviewMaterialTextureInput(
                        slot_kind=role,
                        parameter_name=parameter_name,
                        source_dds_path=str(paths[role]),
                        semantic_type=semantic,
                        owner_slot_index=5,
                        binding_authority="exact",
                        binding_disposition=disposition,
                    )
                    for role, (parameter_name, semantic, disposition) in parameters.items()
                ),
            )
            mesh = SimpleNamespace(
                path="character/armor/nonconserved-owner.pac",
                lod_levels=[],
                submeshes=[submesh],
            )

            def compile_material(_mesh, **kwargs):
                generated = Path(kwargs["package_dir"]) / "base.png"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"cross-owner base")
                return {
                    "submeshes": [
                        {
                            "resolved_channels": {"base": str(generated)},
                            "direct_fallback_channels": {
                                role: {
                                    "path": str(paths[role]),
                                    "owner_slot_index": 5,
                                    "owner_attribution": "source_submesh_index",
                                    "parameter_name": parameter_name,
                                    "binding_authority": "exact",
                                    "binding_disposition": disposition,
                                    "semantic": semantic,
                                }
                                for role, (
                                    parameter_name,
                                    semantic,
                                    disposition,
                                ) in parameters.items()
                            },
                            "binding_conservation": {
                                "conserved": False,
                                "cross_owner_bindings": [{"owner": 4}],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "succeeded": True,
                                "generated_channels": ["base"],
                                "notes": [],
                            },
                        }
                    ]
                }

            state = rust_authoring_module._RustMaterialSynthesisState()
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ), patch.object(rust_authoring_module, "_encode_owned_dds") as encoder:
                overrides = rust_authoring_module._mesh_synthesized_texture_overrides(
                    mesh,
                    synthesis_root,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        synthesis_root
                    ),
                    stop_event=None,
                    synthesis_state=state,
                )

            self.assertEqual(
                {
                    (0, 0, role): path
                    for role, path in paths.items()
                },
                overrides,
            )
            encoder.assert_not_called()
            self.assertEqual(0, state.generated_binding_count)
            self.assertEqual(
                "compiler_owner_conservation_failed",
                state.diagnostics[0]["code"],
            )

    def test_skin_detail_normal_remains_runtime_tiled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            synthesis_root = root / "synthesis"
            synthesis_root.mkdir()
            direct_normal = root / "body_n.dds"
            detail_normal = root / "skin_detail_n.dds"
            direct_normal.write_bytes(b"DDS body normal")
            detail_normal.write_bytes(b"DDS skin detail")
            owner = 0
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=owner,
                preview_normal_texture_dds_path=str(direct_normal),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="normal",
                        parameter_name="_normalTexture",
                        source_dds_path=str(direct_normal),
                        binding_authority="authoritative",
                        owner_slot_index=owner,
                    ),
                    *tuple(
                        PreviewMaterialTextureInput(
                            slot_kind="normal",
                            parameter_name=parameter_name,
                            source_dds_path=str(detail_normal),
                            binding_authority="authoritative",
                            owner_slot_index=owner,
                        )
                        for parameter_name in (
                            "_skinDetailMaskTexture",
                            "_skinDetailNormalTexture",
                            "_skinDetailMaterialTexture",
                        )
                    ),
                ),
            )
            mesh = SimpleNamespace(path="character/body.pac", lod_levels=[], submeshes=[submesh])

            def compile_material(_mesh, **kwargs):
                generated = Path(kwargs["package_dir"]) / "normal.png"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"incorrect baked pores")
                return {
                    "submeshes": [
                        {
                            "resolved_channels": {"normal": str(generated)},
                            "binding_conservation": {
                                "conserved": True,
                                "cross_owner_bindings": [],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "succeeded": True,
                                "generated_channels": ["normal"],
                                "notes": ["normal layers synthesized:skin_detail:r"],
                            },
                        }
                    ]
                }

            state = rust_authoring_module._RustMaterialSynthesisState()
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ), patch.object(rust_authoring_module, "_encode_owned_dds") as encoder:
                overrides = rust_authoring_module._mesh_synthesized_texture_overrides(
                    mesh,
                    synthesis_root,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        synthesis_root
                    ),
                    stop_event=None,
                    synthesis_state=state,
                )

            self.assertEqual({}, overrides)
            encoder.assert_not_called()

    def test_foreign_skin_rows_do_not_suppress_generated_standard_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            synthesis_root = root / "synthesis"
            synthesis_root.mkdir()
            foreign_detail = root / "foreign_skin_detail.dds"
            foreign_detail.write_bytes(b"DDS foreign skin detail")
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=0,
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="normal",
                        parameter_name="_skinDetailNormalTexture",
                        source_dds_path=str(foreign_detail),
                        shader_family="SkinnedMeshSkin",
                        binding_authority="authoritative",
                        owner_slot_index=7,
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/armor/standard_surface.pac",
                lod_levels=[],
                submeshes=[submesh],
            )

            def compile_material(_mesh, **kwargs):
                generated_root = Path(kwargs["package_dir"]) / "material_synthesis"
                generated_root.mkdir(parents=True, exist_ok=True)
                normal = generated_root / "normal.png"
                roughness = generated_root / "roughness.png"
                normal.write_bytes(b"generated standard normal")
                roughness.write_bytes(b"generated standard roughness")
                return {
                    "submeshes": [
                        {
                            "shader_family": "standard_v2",
                            "resolved_channels": {
                                "normal": str(normal),
                                "roughness": str(roughness),
                            },
                            "binding_conservation": {
                                "conserved": True,
                                "cross_owner_bindings": [],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "attempted": True,
                                "succeeded": True,
                                "generated_channels": ["normal", "roughness"],
                                "notes": ["normal layers synthesized:detail:r"],
                            },
                        }
                    ]
                }

            def encode(source, target, channel, _stop_event, **_options):
                Path(target).write_bytes(b"DDS generated " + channel.encode("ascii"))
                return {"byte_count": Path(target).stat().st_size, "content_sha256": "0" * 64}

            state = rust_authoring_module._RustMaterialSynthesisState()
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ), patch.object(
                rust_authoring_module,
                "_encode_owned_dds",
                side_effect=encode,
            ):
                overrides = rust_authoring_module._mesh_synthesized_texture_overrides(
                    mesh,
                    synthesis_root,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        synthesis_root
                    ),
                    stop_event=None,
                    synthesis_state=state,
                )

            self.assertEqual(
                {(0, 0, "normal"), (0, 0, "roughness")},
                set(overrides),
            )
            self.assertEqual(2, state.generated_binding_count)

    def test_missing_skin_detail_dds_does_not_suppress_generated_normal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            synthesis_root = root / "synthesis"
            synthesis_root.mkdir()
            available_detail = root / "available_skin_detail.dds"
            available_detail.write_bytes(b"DDS available skin detail")
            missing_detail = root / "missing_skin_detail_n.dds"
            owner = 0
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=owner,
                preview_material_texture_inputs=tuple(
                    PreviewMaterialTextureInput(
                        slot_kind="normal",
                        parameter_name=parameter_name,
                        source_dds_path=str(
                            missing_detail
                            if parameter_name == "_skinDetailNormalTexture"
                            else available_detail
                        ),
                        binding_authority="authoritative",
                        owner_slot_index=owner,
                    )
                    for parameter_name in (
                        "_skinDetailMaskTexture",
                        "_skinDetailNormalTexture",
                        "_skinDetailMaterialTexture",
                    )
                ),
            )
            self.assertTrue(
                rust_authoring_module._rust_has_exact_runtime_skin_detail(submesh)
            )
            self.assertFalse(
                rust_authoring_module._rust_has_available_runtime_skin_detail(submesh)
            )
            mesh = SimpleNamespace(
                path="character/body/missing_detail.pac",
                lod_levels=[],
                submeshes=[submesh],
            )

            def compile_material(_mesh, **kwargs):
                generated = Path(kwargs["package_dir"]) / "normal.png"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"generated fallback normal")
                return {
                    "submeshes": [
                        {
                            "shader_family": "standard_v2",
                            "resolved_channels": {"normal": str(generated)},
                            "binding_conservation": {
                                "conserved": True,
                                "cross_owner_bindings": [],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "attempted": True,
                                "succeeded": True,
                                "generated_channels": ["normal"],
                                "notes": ["normal layers synthesized:detail:r"],
                            },
                        }
                    ]
                }

            def encode(source, target, channel, _stop_event, **_options):
                self.assertEqual("normal", channel)
                self.assertEqual(b"generated fallback normal", Path(source).read_bytes())
                Path(target).write_bytes(b"DDS generated normal")
                return {"byte_count": 20, "content_sha256": "0" * 64}

            state = rust_authoring_module._RustMaterialSynthesisState()
            with patch.object(
                rust_authoring_module,
                "compile_mesh_dotnet_material_manifest",
                side_effect=compile_material,
            ), patch.object(
                rust_authoring_module,
                "_encode_owned_dds",
                side_effect=encode,
            ):
                overrides = rust_authoring_module._mesh_synthesized_texture_overrides(
                    mesh,
                    synthesis_root,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        synthesis_root
                    ),
                    stop_event=None,
                    synthesis_state=state,
                )

            self.assertEqual({(0, 0, "normal")}, set(overrides))
            self.assertEqual(1, state.generated_binding_count)

    def test_pac_material_graph_replaces_raw_base_and_surface_per_owner_without_vortice(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "archive-preview-package"
            package_root.mkdir()
            (package_root / "net_materials.json").write_text(
                '{"schema":"owned-layer-test"}',
                encoding="utf-8",
            )
            direct_base = package_root / "direct_base.dds"
            direct_normal = package_root / "direct_normal.dds"
            raw_material = package_root / "raw_layer_mask.dds"
            direct_base.write_bytes(b"DDS raw-base-must-not-win")
            direct_normal_bytes = b"DDS native-normal"
            direct_normal.write_bytes(direct_normal_bytes)
            raw_material.write_bytes(b"DDS raw-mask-must-not-be-surface")
            preview_material = SimpleNamespace(
                source_submesh_index=0,
                material="layered_sword",
                preview_normal_y_policy="preserve",
                preview_texture_dds_path=str(direct_base),
                preview_normal_texture_dds_path=str(direct_normal),
                preview_material_texture_dds_path=str(raw_material),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="base",
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(direct_base),
                        preview_texture_path=str(direct_base),
                        semantic_type="albedo",
                        semantic_subtype="base_color",
                    ),
                    PreviewMaterialTextureInput(
                        slot_kind="roughness",
                        parameter_name="_roughnessTexture",
                        source_dds_path=str(raw_material),
                        preview_texture_path=str(raw_material),
                        semantic_type="roughness",
                    ),
                    PreviewMaterialTextureInput(
                        slot_kind="metalness",
                        parameter_name="_metallicTexture",
                        source_dds_path=str(raw_material),
                        preview_texture_path=str(raw_material),
                        semantic_type="metalness",
                    ),
                ),
            )
            def compile_pac_graph(_mesh, synthesis_root, **kwargs):
                self.assertEqual(frozenset(), kwargs["protected_keys"])
                kwargs["synthesis_state"].attempted = True
                base = synthesis_root / "pac_graph_base.dds"
                surface = synthesis_root / "pac_graph_surface.dds"
                base.write_bytes(b"DDS exact-authored-gold")
                surface.write_bytes(b"DDS exact-packed-surface")
                return {
                    (0, 0, "base_color"): base,
                    (0, 0, "material"): surface,
                }

            session_root = temporary_root / "session"
            with patch.object(
                rust_authoring_module,
                "resolve_mesh_dotnet_experiment_editor",
                side_effect=AssertionError("Vortice resolver must not be called"),
                create=True,
            ), patch.object(
                rust_authoring_module,
                "run_process_with_cancellation",
                side_effect=AssertionError("Vortice process must not be launched"),
                create=True,
            ), patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                side_effect=AssertionError("Vortice compositor must not be called"),
                create=True,
            ), patch.object(
                rust_authoring_module,
                "_mesh_synthesized_texture_overrides",
                side_effect=compile_pac_graph,
            ):
                _authoritative, session = self._create(
                    session_root,
                    preview_material_model=SimpleNamespace(
                        path="character/weapon/layered_sword.pac",
                        meshes=[preview_material],
                    ),
                    material_package_path=package_root,
                    material_name="layered_sword",
                )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                resources = {row["role"]: row for row in manifest["textures"]}
                self.assertEqual(
                    b"DDS exact-authored-gold",
                    (session_root / resources["base_color"]["file"]["path"]).read_bytes(),
                )
                self.assertEqual(
                    b"DDS exact-packed-surface",
                    (session_root / resources["material"]["file"]["path"]).read_bytes(),
                )
                self.assertEqual(
                    direct_normal_bytes,
                    (session_root / resources["normal"]["file"]["path"]).read_bytes(),
                )
                presentation = manifest["material_presentations"][0]
                self.assertEqual(
                    "preserve",
                    presentation["normal_y_policy"],
                )
                self.assertFalse(presentation["normal_y_inverted"])
                self.assertNotIn(
                    raw_material.read_bytes(),
                    [
                        (session_root / row["file"]["path"]).read_bytes()
                        for row in manifest["textures"]
                    ],
                )
                self.assertNotIn("roughness", resources)
                self.assertNotIn("metalness", resources)
                status = manifest["texture_status"]["material_synthesis"]
                self.assertTrue(status["attempted"])
                self.assertEqual(2, status["generated_binding_count"])
                self.assertFalse(status["degraded"])
                self.assertEqual([], status["warnings"])
            finally:
                session.cancel()

    def test_full_pac_graph_base_is_published_without_vortice_compositor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            session_root = root / "session"
            session_root.mkdir()
            package_root = root / "archive-preview-package"
            package_root.mkdir()
            (package_root / "net_materials.json").write_text(
                "{}",
                encoding="utf-8",
            )
            mesh = SimpleNamespace(
                path="character/armor/layered_helmet.pac",
                lod_levels=[],
                submeshes=[SimpleNamespace(preview_material_texture_inputs=())],
            )

            def canonical(_mesh, synthesis_root, **kwargs):
                self.assertEqual(frozenset(), kwargs["protected_keys"])
                path = synthesis_root / "pac-graph-gold.dds"
                path.write_bytes(b"DDS PAC graph gold")
                return {(0, 0, "base_color"): path}

            state = rust_authoring_module._RustMaterialSynthesisState()
            with patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                side_effect=AssertionError("Vortice compositor must not be called"),
                create=True,
            ), patch.object(
                rust_authoring_module,
                "_mesh_synthesized_texture_overrides",
                side_effect=canonical,
            ):
                resources = rust_authoring_module._mesh_texture_payloads(
                    session_root,
                    mesh,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        session_root
                    ),
                    synthesis_state=state,
                    material_package_path=package_root,
                )

            by_role = {row["role"]: row for row in resources}
            self.assertEqual({"base_color"}, set(by_role))
            published = session_root / by_role["base_color"]["file"]["path"]
            self.assertEqual(b"DDS PAC graph gold", published.read_bytes())
            self.assertEqual(1, state.generated_binding_count)

    def test_rust_material_preparation_never_resolves_or_runs_vortice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "archive-preview-package"
            package_root.mkdir()
            (package_root / "net_materials.json").write_text("{}", encoding="utf-8")
            direct_base = package_root / "direct_base.dds"
            direct_base.write_bytes(b"DDS direct")
            preview_material = SimpleNamespace(
                source_submesh_index=0,
                material="layered_sword",
                preview_texture_dds_path=str(direct_base),
            )
            session_root = temporary_root / "session"
            with patch.object(
                rust_authoring_module,
                "resolve_mesh_dotnet_experiment_editor",
                side_effect=AssertionError("Vortice resolver must not be called"),
                create=True,
            ) as resolver, patch.object(
                rust_authoring_module,
                "run_process_with_cancellation",
                side_effect=AssertionError("Vortice process must not be launched"),
                create=True,
            ) as process_runner:
                _authoritative, session = self._create(
                    session_root,
                    preview_material_model=SimpleNamespace(
                        path="character/weapon/layered_sword.pac",
                        meshes=[preview_material],
                    ),
                    material_package_path=package_root,
                    material_name="layered_sword",
                )
            try:
                resolver.assert_not_called()
                process_runner.assert_not_called()
                self.assertTrue(session_root.is_dir())
            finally:
                session.cancel()

    def test_texture_resource_lookup_prefers_exact_input_over_flat_selector(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            top_level = root / "top-level.dds"
            material_input = root / "material-input.dds"
            top_level.write_bytes(b"DDS top-level")
            material_input.write_bytes(b"DDS material-input")
            source = SimpleNamespace(
                preview_texture_dds_path=str(top_level),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="base",
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(material_input),
                        semantic_type="albedo",
                        semantic_subtype="base_color",
                    ),
                ),
            )

            self.assertEqual(
                material_input.resolve(),
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "base_color",
                    ("preview_texture_dds_path",),
                ),
            )
            source.preview_texture_dds_path = ""
            self.assertEqual(
                material_input.resolve(),
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "base_color",
                    ("preview_texture_dds_path",),
                ),
            )

    def test_texture_resource_lookup_rejects_mismatched_and_ambiguous_owner_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            flat_selector = root / "flat_mg.dds"
            owner_base = root / "owner_base.dds"
            other_base = root / "other_base.dds"
            for path in (flat_selector, owner_base, other_base):
                path.write_bytes(b"DDS payload")
            source = SimpleNamespace(
                preview_pac_material_owner_slot_index=7,
                preview_texture_dds_path=str(flat_selector),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(other_base),
                        owner_slot_index=8,
                        binding_authority="authoritative",
                    ),
                ),
            )

            self.assertIsNone(
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "base_color",
                    ("preview_texture_dds_path",),
                )
            )
            source.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    parameter_name="_baseColorTexture",
                    source_dds_path=str(owner_base),
                    owner_slot_index=7,
                    binding_authority="authoritative",
                ),
                PreviewMaterialTextureInput(
                    parameter_name="_overlayColorTexture",
                    source_dds_path=str(other_base),
                    owner_slot_index=7,
                    binding_authority="authoritative",
                ),
            )
            self.assertIsNone(
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "base_color",
                    ("preview_texture_dds_path",),
                )
            )

    def test_global_material_excludes_layer_response_when_synthesized_outputs_exist(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            session_root = root / "session"
            session_root.mkdir()
            layered_material = root / "leather_sp.dds"
            synthesized_base = root / "leather_base.dds"
            synthesized_roughness = root / "leather_roughness.dds"
            layered_material.write_bytes(b"DDS layer material response")
            synthesized_base.write_bytes(b"DDS synthesized base")
            synthesized_roughness.write_bytes(b"DDS synthesized roughness")
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=4,
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        parameter_name="_materialTextureB",
                        source_dds_path=str(layered_material),
                        owner_slot_index=4,
                        binding_authority="authoritative",
                        binding_disposition="layer_material_response",
                        source_kind="crimson_layer_material_response",
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/armor/leather.pac",
                lod_levels=[],
                submeshes=[submesh],
            )
            with patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                side_effect=AssertionError("Vortice compositor must not be called"),
                create=True,
            ), patch.object(
                rust_authoring_module,
                "_mesh_synthesized_texture_overrides",
                return_value={
                    (0, 0, "base_color"): synthesized_base,
                    (0, 0, "roughness"): synthesized_roughness,
                },
            ):
                resources = rust_authoring_module._mesh_texture_payloads(
                    session_root,
                    mesh,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        session_root
                    ),
                )

            self.assertEqual(
                {"base_color", "roughness"},
                {row["role"] for row in resources},
            )
            self.assertNotIn(
                layered_material.name,
                {row["label"] for row in resources},
            )

    def test_global_height_excludes_diagnostic_guess(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            session_root = root / "session"
            session_root.mkdir()
            guessed_height = root / "guessed_height.dds"
            guessed_height.write_bytes(b"DDS guessed height")
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=5,
                preview_height_texture_dds_path=str(guessed_height),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        parameter_name="_heightTexture",
                        source_dds_path=str(guessed_height),
                        binding_authority="guess",
                        binding_disposition="diagnostic_only",
                        source_kind="unknown_crimson_texture",
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/weapon/diagnostic-height.pac",
                lod_levels=[],
                submeshes=[submesh],
            )
            with patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                return_value={},
                create=True,
            ), patch.object(
                rust_authoring_module,
                "_mesh_synthesized_texture_overrides",
                return_value={},
            ):
                resources = rust_authoring_module._mesh_texture_payloads(
                    session_root,
                    mesh,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        session_root
                    ),
                )

            self.assertEqual([], resources)

    def test_exact_promoted_and_recorded_global_inputs_remain_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            session_root = root / "session"
            session_root.mkdir()
            exact_base = root / "exact_base.dds"
            exact_height = root / "exact_height.dds"
            exact_material = root / "exact_material.dds"
            exact_base.write_bytes(b"DDS exact promoted base")
            exact_height.write_bytes(b"DDS exact recorded height")
            exact_material.write_bytes(b"DDS exact whole-surface material")
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=7,
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(exact_base),
                        owner_slot_index=7,
                        binding_authority="authoritative",
                        binding_disposition="promoted",
                        source_kind="crimson_base_color",
                    ),
                    PreviewMaterialTextureInput(
                        parameter_name="_heightTexture",
                        source_dds_path=str(exact_height),
                        owner_slot_index=7,
                        binding_authority="exact",
                        binding_disposition="recorded",
                        source_kind="crimson_height",
                    ),
                    PreviewMaterialTextureInput(
                        parameter_name="_materialTexture",
                        source_dds_path=str(exact_material),
                        owner_slot_index=7,
                        binding_authority="authoritative",
                        binding_disposition="layer_material_response",
                        source_kind="crimson_layer_material_response",
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/weapon/exact-inputs.pac",
                lod_levels=[],
                submeshes=[submesh],
            )
            with patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                return_value={},
                create=True,
            ), patch.object(
                rust_authoring_module,
                "_mesh_synthesized_texture_overrides",
                return_value={},
            ):
                resources = rust_authoring_module._mesh_texture_payloads(
                    session_root,
                    mesh,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        session_root
                    ),
                )

            by_role = {row["role"]: row for row in resources}
            self.assertEqual({"base_color", "height", "material"}, set(by_role))
            self.assertEqual(exact_base.name, by_role["base_color"]["label"])
            self.assertEqual(exact_height.name, by_role["height"]["label"])
            self.assertEqual(exact_material.name, by_role["material"]["label"])

    def test_exact_skin_base_outranks_sibling_and_layers_stay_dedicated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            session_root = root / "session"
            session_root.mkdir()
            exact_base = root / "skin_head_base.dds"
            sibling_base = root / "skin_body_base.dds"
            scar_material = root / "skin_scar_sp.dds"
            detail_mask = root / "skin_detail_mask.dds"
            detail_material = root / "skin_detail_sp.dds"
            for path in (
                exact_base,
                sibling_base,
                scar_material,
                detail_mask,
                detail_material,
            ):
                path.write_bytes(b"DDS " + path.name.encode("ascii"))
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=2,
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(exact_base),
                        owner_slot_index=2,
                        binding_authority="authoritative",
                        binding_disposition="promoted",
                        source_kind="crimson_base_color",
                    ),
                    PreviewMaterialTextureInput(
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(sibling_base),
                        owner_slot_index=3,
                        binding_authority="authoritative",
                        binding_disposition="promoted",
                        source_kind="crimson_base_color",
                    ),
                    PreviewMaterialTextureInput(
                        parameter_name="_materialTextureB",
                        source_dds_path=str(scar_material),
                        owner_slot_index=2,
                        binding_authority="authoritative",
                        binding_disposition="layer_material_response",
                        source_kind="crimson_layer_material_response",
                    ),
                    PreviewMaterialTextureInput(
                        parameter_name="_skinDetailMaskTexture",
                        source_dds_path=str(detail_mask),
                        owner_slot_index=2,
                        binding_authority="authoritative",
                        binding_disposition="layer_only",
                        source_kind="crimson_skin_detail_mask",
                    ),
                    PreviewMaterialTextureInput(
                        parameter_name="_skinDetailMaterialTexture",
                        source_dds_path=str(detail_material),
                        owner_slot_index=2,
                        binding_authority="authoritative",
                        binding_disposition="layer_material_response",
                        source_kind="crimson_skin_material_response",
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/model/skin-head.pac",
                lod_levels=[],
                submeshes=[submesh],
            )
            with patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                return_value={},
                create=True,
            ), patch.object(
                rust_authoring_module,
                "_mesh_synthesized_texture_overrides",
                return_value={},
            ):
                resources = rust_authoring_module._mesh_texture_payloads(
                    session_root,
                    mesh,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        session_root
                    ),
                )

            by_role = {row["role"]: row for row in resources}
            self.assertEqual(
                {"base_color", "skin_detail_mask", "skin_detail_material"},
                set(by_role),
            )
            self.assertEqual(exact_base.name, by_role["base_color"]["label"])
            self.assertNotIn(sibling_base.name, {row["label"] for row in resources})
            self.assertNotIn(scar_material.name, {row["label"] for row in resources})

    def test_diagnostic_direct_top_level_base_remains_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            session_root = root / "session"
            session_root.mkdir()
            direct_base = root / "owner5_direct_base.dds"
            direct_base.write_bytes(b"DDS owner5 direct base")
            submesh = SimpleNamespace(
                preview_pac_material_owner_slot_index=5,
                preview_texture_dds_path=str(direct_base),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(direct_base),
                        owner_slot_index=5,
                        binding_authority="guess",
                        binding_disposition="diagnostic_only",
                        source_kind="unknown_crimson_texture",
                    ),
                ),
            )
            mesh = SimpleNamespace(
                path="character/weapon/owner5.pac",
                lod_levels=[],
                submeshes=[submesh],
            )
            with patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                return_value={},
                create=True,
            ), patch.object(
                rust_authoring_module,
                "_mesh_synthesized_texture_overrides",
                return_value={},
            ):
                resources = rust_authoring_module._mesh_texture_payloads(
                    session_root,
                    mesh,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        session_root
                    ),
                )

            self.assertEqual(1, len(resources))
            self.assertEqual("base_color", resources[0]["role"])
            self.assertEqual(direct_base.name, resources[0]["label"])

    def test_exact_hair_flow_publishes_one_shared_owner_safe_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            session_root = root / "session"
            session_root.mkdir()
            shared_flow = root / "cd_hair_shared_flow.dds"
            shared_bytes = b"DDS exact shared hair flow"
            shared_flow.write_bytes(shared_bytes)

            def flow_input(
                owner: int,
                *,
                authority: str = "authoritative",
                parameter_name: str = "_flowTexture",
                disposition: str = "layer_flow",
                source_kind: str = "crimson_flow_vector",
                layer_role: str = "",
                layer_channel: str = "",
            ) -> PreviewMaterialTextureInput:
                return PreviewMaterialTextureInput(
                    parameter_name=parameter_name,
                    source_dds_path=str(shared_flow),
                    texture_name=shared_flow.name,
                    semantic_type="vector",
                    semantic_subtype="flow",
                    owner_slot_index=owner,
                    binding_authority=authority,
                    binding_disposition=disposition,
                    source_kind=source_kind,
                    layer_role=layer_role,
                    layer_channel=layer_channel,
                )

            owner_zero = SimpleNamespace(
                preview_pac_material_owner_slot_index=0,
                preview_material_texture_inputs=(
                    flow_input(1),  # Foreign owner's otherwise exact binding.
                    flow_input(0, parameter_name="_directionTexture"),
                    flow_input(0, disposition="layer_direction"),
                    flow_input(0, source_kind="crimson_hair_direction"),
                    flow_input(0, layer_role="direction"),
                    flow_input(0, layer_channel="r"),
                ),
            )
            owner_one = SimpleNamespace(
                preview_pac_material_owner_slot_index=1,
                preview_material_texture_inputs=(
                    flow_input(1, authority="exact", layer_role="vector"),
                ),
            )
            owner_two = SimpleNamespace(
                preview_pac_material_owner_slot_index=2,
                preview_material_texture_inputs=(
                    flow_input(2, layer_role="flow"),
                ),
            )
            mesh = SimpleNamespace(
                path="character/model/hair/exact-flow.pac",
                lod_levels=[],
                submeshes=[owner_zero, owner_one, owner_two],
            )

            with patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                return_value={},
                create=True,
            ), patch.object(
                rust_authoring_module,
                "_mesh_synthesized_texture_overrides",
                return_value={},
            ):
                resources = rust_authoring_module._mesh_texture_payloads(
                    session_root,
                    mesh,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        session_root
                    ),
                )

            self.assertEqual(1, len(resources))
            resource = resources[0]
            self.assertEqual("flow", resource["role"])
            self.assertEqual(shared_flow.name, resource["label"])
            self.assertEqual([[1, 2]], resource["material_indices_by_lod"])
            owned_path = session_root / resource["file"]["path"]
            self.assertRegex(owned_path.name, r"^texture-0000-[0-9a-f]{12}\.dds$")
            self.assertEqual(shared_bytes, owned_path.read_bytes())
            self.assertEqual([owned_path], list(session_root.glob("texture-*.dds")))

    def test_global_role_filter_rejects_layer_control_dispositions_and_guesses(
        self,
    ) -> None:
        source = SimpleNamespace(preview_pac_material_owner_slot_index=9)
        for disposition in (
            "layer_only",
            "layer_material_response",
            "layer_direction",
            "layer_flow",
            "diagnostic_only",
        ):
            with self.subTest(disposition=disposition):
                item = PreviewMaterialTextureInput(
                    parameter_name="_normalTexture",
                    owner_slot_index=9,
                    binding_authority="authoritative",
                    binding_disposition=disposition,
                )
                self.assertFalse(
                    rust_authoring_module._material_input_is_renderer_role_eligible(
                        source,
                        item,
                        "normal",
                    )
                )

        self.assertFalse(
            rust_authoring_module._material_input_is_renderer_role_eligible(
                source,
                PreviewMaterialTextureInput(
                    parameter_name="_normalTexture",
                    owner_slot_index=9,
                    binding_authority="guess",
                    binding_disposition="promoted",
                ),
                "normal",
            )
        )
        self.assertTrue(
            rust_authoring_module._material_input_is_renderer_role_eligible(
                SimpleNamespace(),
                PreviewMaterialTextureInput(parameter_name="_normalTexture"),
                "normal",
            )
        )

    def test_rejected_guess_declaration_blocks_flattened_top_level_role(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            guessed_normal = root / "guessed_normal.dds"
            guessed_normal.write_bytes(b"DDS guessed normal")
            source = SimpleNamespace(
                preview_pac_material_owner_slot_index=6,
                preview_normal_texture_dds_path=str(guessed_normal),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        parameter_name="_normalTexture",
                        source_dds_path=str(guessed_normal),
                        binding_authority="guess",
                        binding_disposition="diagnostic_only",
                        source_kind="unknown_crimson_texture",
                    ),
                ),
            )

            self.assertIsNone(
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "normal",
                    ("preview_normal_texture_dds_path",),
                )
            )

    def test_exact_base_declaration_blocks_direct_base_diagnostic_exception(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            direct_guess = root / "direct_guess.dds"
            direct_guess.write_bytes(b"DDS diagnostic direct base")
            source = SimpleNamespace(
                preview_pac_material_owner_slot_index=3,
                preview_texture_dds_path=str(direct_guess),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(root / "missing_exact_base.dds"),
                        owner_slot_index=3,
                        binding_authority="authoritative",
                        binding_disposition="promoted",
                        source_kind="crimson_base_color",
                    ),
                    PreviewMaterialTextureInput(
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(direct_guess),
                        owner_slot_index=3,
                        binding_authority="guess",
                        binding_disposition="diagnostic_only",
                        source_kind="unknown_crimson_texture",
                    ),
                ),
            )

            self.assertIsNone(
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "base_color",
                    ("preview_texture_dds_path",),
                )
            )

    def test_layer_only_color_declarations_do_not_block_direct_owner_base(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            direct_base = root / "direct_owner_base.dds"
            layer_color = root / "grime_layer.dds"
            direct_base.write_bytes(b"DDS direct owner base")
            layer_color.write_bytes(b"DDS layer color")
            source = SimpleNamespace(
                preview_pac_material_owner_slot_index="",
                preview_texture_dds_path=str(direct_base),
            )
            direct_input = PreviewMaterialTextureInput(
                source_dds_path=str(direct_base),
                semantic_type="color",
                semantic_subtype="albedo",
                binding_authority="guess",
                binding_disposition="diagnostic_only",
                source_kind="unknown_crimson_texture",
            )
            source.preview_material_texture_inputs = (
                direct_input,
                PreviewMaterialTextureInput(
                    parameter_name="_grimeDiffuseTextureR",
                    source_dds_path=str(layer_color),
                    semantic_type="color",
                    semantic_subtype="diffuse",
                    owner_slot_index=5,
                    binding_authority="authoritative",
                    binding_disposition="layer_only",
                    source_kind="crimson_layer_color",
                    layer_role="grime",
                    layer_channel="r",
                ),
            )

            self.assertEqual(
                direct_base,
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "base_color",
                    ("preview_texture_dds_path",),
                ),
            )

    def test_hair_aging_color_never_becomes_global_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            aging_color = root / "hair_aging.dds"
            aging_color.write_bytes(b"DDS hair aging layer")
            item = PreviewMaterialTextureInput(
                parameter_name="_baseColorTexture",
                source_dds_path=str(aging_color),
                owner_slot_index=8,
                binding_authority="authoritative",
                binding_disposition="recorded",
                source_kind="crimson_hair_aging_color",
            )
            source = SimpleNamespace(
                preview_pac_material_owner_slot_index=8,
                preview_texture_dds_path=str(aging_color),
                preview_material_texture_inputs=(item,),
            )

            self.assertFalse(
                rust_authoring_module._material_input_is_renderer_role_eligible(
                    source,
                    item,
                    "base_color",
                )
            )
            self.assertIsNone(
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "base_color",
                    ("preview_texture_dds_path",),
                )
            )

    def test_skinned_mesh_skin_material_texture_uses_specular_role(self) -> None:
        self.assertEqual(
            "specular",
            rust_authoring_module._material_input_texture_role(
                PreviewMaterialTextureInput(
                    parameter_name="_materialTexture",
                    shader_family="SkinnedMeshSkin",
                )
            ),
        )

    def test_primary_material_texture_exception_rejects_layer_metadata(self) -> None:
        source = SimpleNamespace(preview_pac_material_owner_slot_index=12)
        cases = (
            ("layer_only", "crimson_layer_material_response", "", ""),
            ("layer_material_response", "unknown_crimson_texture", "", ""),
            (
                "layer_material_response",
                "crimson_layer_material_response",
                "detail",
                "",
            ),
            (
                "layer_material_response",
                "crimson_layer_material_response",
                "",
                "r",
            ),
        )
        for disposition, source_kind, layer_role, layer_channel in cases:
            with self.subTest(
                disposition=disposition,
                source_kind=source_kind,
                layer_role=layer_role,
                layer_channel=layer_channel,
            ):
                item = PreviewMaterialTextureInput(
                    parameter_name="_materialTexture",
                    owner_slot_index=12,
                    binding_authority="authoritative",
                    binding_disposition=disposition,
                    source_kind=source_kind,
                    layer_role=layer_role,
                    layer_channel=layer_channel,
                )
                self.assertFalse(
                    rust_authoring_module._material_input_is_renderer_role_eligible(
                        source,
                        item,
                        "material",
                    )
                )

    def test_legacy_inputs_without_owner_contract_keep_direct_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            direct_base = root / "legacy_base.dds"
            direct_normal = root / "legacy_normal.dds"
            direct_emissive = root / "legacy_emissive.dds"
            for path in (direct_base, direct_normal, direct_emissive):
                path.write_bytes(b"DDS " + path.name.encode("ascii"))
            source = SimpleNamespace(
                preview_pac_material_owner_slot_index=13,
                preview_texture_dds_path=str(direct_base),
                preview_normal_texture_dds_path=str(direct_normal),
                preview_emissive_texture_dds_path=str(direct_emissive),
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        parameter_name="_baseColorTexture",
                        source_dds_path=str(direct_base),
                    ),
                ),
            )

            for role, attributes, expected in (
                ("base_color", ("preview_texture_dds_path",), direct_base),
                ("normal", ("preview_normal_texture_dds_path",), direct_normal),
                (
                    "emissive",
                    ("preview_emissive_texture_dds_path",),
                    direct_emissive,
                ),
            ):
                with self.subTest(role=role):
                    self.assertEqual(
                        expected,
                        rust_authoring_module._first_texture_resource_dds_path(
                            source,
                            role,
                            attributes,
                        ),
                    )

    def test_ownerless_legacy_duplicate_cannot_override_modern_owner_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            exact_base = root / "exact_base.dds"
            guessed_height = root / "undeclared_disp.dds"
            exact_base.write_bytes(b"DDS exact base")
            guessed_height.write_bytes(b"DDS undeclared height")
            exact_input = PreviewMaterialTextureInput(
                parameter_name="_baseColorTexture",
                source_dds_path=str(exact_base),
                owner_slot_index=0,
                binding_authority="authoritative",
                binding_disposition="promoted",
                source_kind="crimson_base_color",
            )
            legacy_height = PreviewMaterialTextureInput(
                source_dds_path=str(guessed_height),
                semantic_type="height",
                semantic_subtype="displacement",
            )
            source = SimpleNamespace(
                preview_pac_material_owner_slot_index="",
                preview_height_texture_dds_path=str(guessed_height),
                preview_material_texture_inputs=(exact_input, legacy_height),
            )

            self.assertFalse(
                rust_authoring_module._material_input_is_renderer_role_eligible(
                    source,
                    legacy_height,
                    "height",
                )
            )
            self.assertIsNone(
                rust_authoring_module._first_texture_resource_dds_path(
                    source,
                    "height",
                    ("preview_height_texture_dds_path",),
                )
            )

    def test_generated_base_luminance_guard_preserves_hue_detail_and_alpha(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            generated = root / "generated.png"
            direct = root / "direct.png"
            guarded = root / "guarded.png"
            generated_pixels = [
                (240, 120, 60, 17),
                (180, 90, 45, 231),
                (120, 60, 30, 255),
                (60, 30, 15, 0),
            ]
            image = Image.new("RGBA", (4, 1))
            image.putdata(generated_pixels)
            image.save(generated)
            Image.new("RGBA", (4, 1), (60, 40, 20, 255)).save(direct)
            direct_before = direct.read_bytes()

            metrics = rust_authoring_module._guard_generated_base_luminance(
                generated,
                direct,
                guarded,
                alpha_mode="cutout",
                owned_root=root,
                expected_root_identity=rust_authoring_module._session_root_identity(root),
                stop_event=None,
            )

            self.assertIsNotNone(metrics)
            assert metrics is not None
            self.assertGreater(
                metrics["generated_mean_luma"],
                metrics["capped_mean_luma"],
            )
            self.assertLess(metrics["rgb_scale"], 1.0)
            self.assertEqual(
                "whole_image_alpha_weighted",
                metrics["sampling_basis"],
            )
            self.assertGreater(metrics["sample_count"], 0)
            with Image.open(guarded) as output:
                rgba_output = output.convert("RGBA")
                output_pixels = list(
                    rgba_output.get_flattened_data()
                    if hasattr(rgba_output, "get_flattened_data")
                    else rgba_output.getdata()
                )
            self.assertEqual(
                [pixel[3] for pixel in generated_pixels],
                [pixel[3] for pixel in output_pixels],
            )
            scale = metrics["rgb_scale"]
            for source_pixel, output_pixel in zip(
                generated_pixels,
                output_pixels,
                strict=True,
            ):
                self.assertEqual(
                    tuple(round(channel * scale) for channel in source_pixel[:3]),
                    output_pixel[:3],
                )
            self.assertEqual(direct_before, direct.read_bytes())

    def test_surface_uv_luminance_ignores_bright_unused_atlas_area(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            generated = root / "generated.png"
            direct = root / "direct.png"
            guarded = root / "guarded.png"
            generated_image = Image.new("RGBA", (4, 4), (255, 255, 255, 255))
            generated_image.putpixel((0, 0), (16, 16, 16, 255))
            generated_image.save(generated)
            Image.new("RGBA", (4, 4), (64, 64, 64, 255)).save(direct)

            metrics = rust_authoring_module._guard_generated_base_luminance(
                generated,
                direct,
                guarded,
                alpha_mode="opaque",
                surface_uv_samples=((0.125, 0.125, 1.0),),
                owned_root=root,
                expected_root_identity=rust_authoring_module._session_root_identity(root),
                stop_event=None,
            )

            self.assertIsNone(metrics)
            self.assertFalse(guarded.exists())

    def test_surface_uv_luminance_caps_bright_used_blade_region(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            generated = root / "generated.png"
            direct = root / "direct.png"
            guarded = root / "guarded.png"
            generated_image = Image.new("RGBA", (4, 4), (8, 8, 8, 255))
            generated_image.putpixel((0, 0), (255, 255, 255, 37))
            generated_image.save(generated)
            Image.new("RGBA", (4, 4), (64, 64, 64, 255)).save(direct)

            metrics = rust_authoring_module._guard_generated_base_luminance(
                generated,
                direct,
                guarded,
                alpha_mode="opaque",
                surface_uv_samples=((0.125, 0.125, 1.0),),
                owned_root=root,
                expected_root_identity=rust_authoring_module._session_root_identity(root),
                stop_event=None,
            )

            self.assertIsNotNone(metrics)
            assert metrics is not None
            self.assertEqual("surface_uv0_repeat_linear", metrics["sampling_basis"])
            self.assertEqual(1, metrics["sample_count"])
            self.assertAlmostEqual(1.0, metrics["generated_mean_luma"])
            self.assertTrue(guarded.is_file())
            with Image.open(guarded) as output:
                self.assertEqual(37, output.convert("RGBA").getpixel((0, 0))[3])

    def test_surface_uv_luminance_uses_repeat_addressing(self) -> None:
        from PIL import Image

        image = Image.new("RGBA", (2, 2), (0, 0, 0, 255))
        image.putpixel((0, 0), (192, 96, 48, 255))
        inside = rust_authoring_module._sampled_surface_uv_mean_luma(
            image,
            ((0.25, 0.25, 1.0),),
            alpha_mode="opaque",
            stop_event=None,
        )
        repeated = rust_authoring_module._sampled_surface_uv_mean_luma(
            image,
            ((1.25, -0.75, 1.0),),
            alpha_mode="opaque",
            stop_event=None,
        )

        self.assertIsNotNone(inside)
        self.assertEqual(inside, repeated)

    def test_surface_uv_sample_builder_is_bounded_deterministic_and_cancellable(
        self,
    ) -> None:
        submesh = SimpleNamespace(
            vertices=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            uvs=((0.0, 0.0), (2.0, 0.0), (0.0, -2.0)),
            faces=((0, 1, 2),)
            * (rust_authoring_module._RUST_MATERIAL_LUMINANCE_GUARD_MAX_SURFACE_FACES + 257),
        )

        first = rust_authoring_module._rust_surface_uv_luminance_samples(
            submesh,
            None,
        )
        second = rust_authoring_module._rust_surface_uv_luminance_samples(
            submesh,
            None,
        )
        self.assertEqual(first, second)
        self.assertEqual(
            rust_authoring_module._RUST_MATERIAL_LUMINANCE_GUARD_MAX_SURFACE_SAMPLES,
            len(first),
        )
        self.assertAlmostEqual(1.0, sum(sample[2] for sample in first))
        stop_event = threading.Event()
        stop_event.set()
        with self.assertRaises(RustMeshCancellationError):
            rust_authoring_module._rust_surface_uv_luminance_samples(
                submesh,
                stop_event,
            )

    def test_generated_base_luminance_guard_opaque_counts_rgb_under_zero_alpha(
        self,
    ) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            generated = root / "generated.png"
            direct = root / "direct.png"
            opaque_guarded = root / "opaque-guarded.png"
            cutout_guarded = root / "cutout-guarded.png"
            image = Image.new("RGBA", (2, 1))
            image.putdata(
                [
                    (255, 255, 255, 0),
                    (20, 20, 20, 255),
                ]
            )
            image.save(generated)
            Image.new("RGBA", (2, 1), (64, 64, 64, 255)).save(direct)

            opaque_metrics = rust_authoring_module._guard_generated_base_luminance(
                generated,
                direct,
                opaque_guarded,
                alpha_mode="opaque",
                owned_root=root,
                expected_root_identity=rust_authoring_module._session_root_identity(root),
                stop_event=None,
            )
            cutout_metrics = rust_authoring_module._guard_generated_base_luminance(
                generated,
                direct,
                cutout_guarded,
                alpha_mode="cutout",
                owned_root=root,
                expected_root_identity=rust_authoring_module._session_root_identity(root),
                stop_event=None,
            )

            self.assertIsNotNone(opaque_metrics)
            assert opaque_metrics is not None
            self.assertGreater(
                opaque_metrics["generated_mean_luma"],
                opaque_metrics["capped_mean_luma"],
            )
            self.assertTrue(opaque_guarded.is_file())
            self.assertIsNone(cutout_metrics)
            self.assertFalse(cutout_guarded.exists())
            with Image.open(opaque_guarded) as output:
                rgba_output = output.convert("RGBA")
                output_pixels = list(
                    rgba_output.get_flattened_data()
                    if hasattr(rgba_output, "get_flattened_data")
                    else rgba_output.getdata()
                )
                self.assertEqual(
                    [0, 255],
                    [alpha for *_rgb, alpha in output_pixels],
                )

    def test_generated_base_luminance_guard_leaves_nearby_or_darker_base_alone(
        self,
    ) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            generated = root / "generated.png"
            direct = root / "direct.png"
            guarded = root / "guarded.png"
            Image.new("RGBA", (2, 2), (135, 120, 105, 91)).save(generated)
            Image.new("RGBA", (2, 2), (130, 115, 100, 255)).save(direct)

            metrics = rust_authoring_module._guard_generated_base_luminance(
                generated,
                direct,
                guarded,
                alpha_mode="cutout",
                owned_root=root,
                expected_root_identity=rust_authoring_module._session_root_identity(root),
                stop_event=None,
            )

            self.assertIsNone(metrics)
            self.assertFalse(guarded.exists())

    def test_material_synthesis_failures_keep_usable_direct_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            direct_texture = temporary_root / "layered_direct.dds"
            direct_bytes = b"DDS usable-direct-fallback"
            direct_texture.write_bytes(direct_bytes)

            def preview_model():
                return SimpleNamespace(
                    path="character/weapon/layered_fallback.pac",
                    meshes=[
                        SimpleNamespace(
                            source_submesh_index=0,
                            material="layered_fallback",
                            texture="layered_direct",
                            preview_texture_dds_path=str(direct_texture),
                            preview_normal_texture_dds_path=str(direct_texture),
                            preview_material_texture_inputs=(
                                PreviewMaterialTextureInput(
                                    slot_kind="material",
                                    parameter_name="_detailColorTexture",
                                    source_dds_path=str(direct_texture),
                                    preview_texture_path=str(direct_texture),
                                    semantic_type="color",
                                    semantic_subtype="detail_diffuse",
                                    shader_family="Standard_Ver2",
                                    layer_role="detail",
                                    layer_channel="g",
                                    visualized=True,
                                ),
                                PreviewMaterialTextureInput(
                                    slot_kind="normal",
                                    parameter_name="_normalTexture",
                                    source_dds_path=str(direct_texture),
                                ),
                                PreviewMaterialTextureInput(
                                    slot_kind="normal",
                                    parameter_name="_detailNormalMaskR",
                                    source_dds_path=str(direct_texture),
                                    layer_role="detail",
                                    layer_channel="r",
                                ),
                            ),
                        )
                    ],
                )

            synthesis_roots: list[Path] = []

            def generated_manifest(mesh, **kwargs):
                package_dir = Path(kwargs["package_dir"])
                synthesis_roots.append(package_dir.parent)
                generated = (
                    package_dir
                    / "material_synthesis"
                    / "submesh_000"
                    / "normal.png"
                )
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"generated image")
                return {
                    "submeshes": [
                        {
                            "resolved_channels": {"normal": str(generated)},
                            "binding_conservation": {
                                "conserved": True,
                                "cross_owner_bindings": [],
                                "layer_as_base_bindings": [],
                            },
                            "material_synthesis": {
                                "succeeded": True,
                                "generated_channels": ["normal"],
                                "notes": ["normal layers synthesized:detail:r"],
                            },
                        }
                        for _submesh in tuple(mesh.submeshes)
                    ]
                }

            for mode in ("compiler", "encoder"):
                with self.subTest(mode=mode):
                    session_root = temporary_root / f"session-{mode}"
                    compiler_side_effect = (
                        RuntimeError("synthetic canonical compiler failure")
                        if mode == "compiler"
                        else generated_manifest
                    )
                    with patch.object(
                        rust_authoring_module,
                        "compile_mesh_dotnet_material_manifest",
                        side_effect=compiler_side_effect,
                    ), patch.object(
                        rust_authoring_module,
                        "_encode_owned_dds",
                        side_effect=RuntimeError("synthetic DirectXTex failure"),
                    ):
                        _authoritative, session = self._create(
                            session_root,
                            preview_material_model=preview_model(),
                        )
                    try:
                        manifest = json.loads(
                            session.manifest_path.read_text(encoding="utf-8")
                        )
                        base_resources = [
                            resource
                            for resource in manifest["textures"]
                            if resource["role"] == "base_color"
                        ]
                        self.assertEqual(1, len(base_resources))
                        packaged = session_root / base_resources[0]["file"]["path"]
                        self.assertEqual(direct_bytes, packaged.read_bytes())
                        self.assertEqual(direct_bytes, direct_texture.read_bytes())
                        synthesis_status = manifest["texture_status"][
                            "material_synthesis"
                        ]
                        self.assertTrue(synthesis_status["attempted"])
                        self.assertTrue(synthesis_status["degraded"])
                        self.assertEqual(1, synthesis_status["fallback_count"])
                        self.assertEqual(0, synthesis_status["generated_binding_count"])
                        self.assertEqual(1, len(synthesis_status["warnings"]))
                        self.assertEqual(
                            (
                                "compiler_failed"
                                if mode == "compiler"
                                else "generated_channel_encode_failed"
                            ),
                            synthesis_status["warnings"][0]["code"],
                        )
                        rust_authoring_module._validate_owned_session_tree(
                            session_root,
                            session.root_identity,
                        )
                    finally:
                        session.cancel()

            self.assertTrue(synthesis_roots)
            self.assertTrue(
                all(root.parent == temporary_root.resolve() for root in synthesis_roots)
            )
            self.assertTrue(all(not root.exists() for root in synthesis_roots))

    def test_material_synthesis_diagnostics_are_bounded_and_single_line(self) -> None:
        state = rust_authoring_module._RustMaterialSynthesisState()
        for index in range(
            rust_authoring_module._RUST_MATERIAL_SYNTHESIS_DIAGNOSTIC_LIMIT + 7
        ):
            rust_authoring_module._record_rust_material_synthesis_diagnostic(
                state,
                "encoder_failed",
                lod_index=0,
                submesh_index=index,
                detail="first line\n" + "x" * 1_000,
            )

        self.assertEqual(
            rust_authoring_module._RUST_MATERIAL_SYNTHESIS_DIAGNOSTIC_LIMIT,
            len(state.diagnostics),
        )
        self.assertEqual(7, state.dropped_diagnostic_count)
        self.assertNotIn("\n", state.diagnostics[0]["detail"])
        self.assertLessEqual(
            len(state.diagnostics[0]["detail"]),
            rust_authoring_module._RUST_MATERIAL_SYNTHESIS_DIAGNOSTIC_TEXT_LIMIT,
        )

    def test_material_luminance_guard_diagnostics_are_bounded(self) -> None:
        state = rust_authoring_module._RustMaterialSynthesisState()
        limit = rust_authoring_module._RUST_MATERIAL_SYNTHESIS_DIAGNOSTIC_LIMIT
        for index in range(limit + 7):
            rust_authoring_module._record_rust_material_luminance_guard(
                state,
                lod_index=0,
                submesh_index=index,
                direct_mean_luma=0.25,
                generated_mean_luma=0.75,
                capped_mean_luma=0.30,
                rgb_scale=0.40,
            )

        self.assertEqual(limit + 7, state.luminance_guard_count)
        self.assertEqual(limit, len(state.luminance_guard_adjustments))
        self.assertEqual(7, state.dropped_luminance_guard_count)
        self.assertEqual(
            "generated_base_luminance_capped",
            state.luminance_guard_adjustments[0]["code"],
        )

    def test_texture_packaging_validates_the_session_tree_a_constant_number_of_times(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            session_root = temporary_root / "session"
            session_root.mkdir()
            mesh = _quad_mesh()
            template = mesh.submeshes[0]
            mesh.submeshes = []
            for index in range(16):
                source = temporary_root / f"texture-{index:02d}.dds"
                source.write_bytes(b"DDS " + bytes([index]) * 64)
                submesh = copy.deepcopy(template)
                submesh.preview_texture_dds_path = str(source)
                mesh.submeshes.append(submesh)

            validate_tree = rust_authoring_module._validate_owned_session_tree
            with patch.object(
                rust_authoring_module,
                "_validate_owned_session_tree",
                wraps=validate_tree,
            ) as validate_tree_mock:
                resources = rust_authoring_module._mesh_texture_payloads(
                    session_root,
                    mesh,
                    expected_root_identity=rust_authoring_module._session_root_identity(
                        session_root
                    ),
                )

            self.assertEqual(16, len(resources))
            self.assertEqual(2, validate_tree_mock.call_count)

    def test_preview_material_context_is_bounded_and_detached_from_preview_geometry(
        self,
    ) -> None:
        material_source = SimpleNamespace(
            source_submesh_index=0,
            material="body",
            texture="body_base",
            preview_texture_dds_path="textures/body_base.dds",
            vertices=[(1.0, 2.0, 3.0)] * 10_000,
            preview_image=b"not retained" * 10_000,
        )
        preview_model = SimpleNamespace(
            path="character/body.pac",
            meshes=[material_source],
            vertices=[(4.0, 5.0, 6.0)] * 10_000,
        )
        controller = SimpleNamespace()

        binding_count = rust_authoring_module.prime_rust_mesh_preview_context(
            controller,
            preview_model,
        )
        material_source.preview_texture_dds_path = "textures/mutated.dds"
        material_source.material = "mutated"

        self.assertEqual(1, binding_count)
        context = getattr(
            controller,
            rust_authoring_module._RUST_PREVIEW_MATERIAL_CONTEXT_ATTR,
        )
        snapshot_source = context.preview_model.submeshes[0]
        self.assertEqual("body", snapshot_source.material)
        self.assertEqual(
            "textures/body_base.dds",
            snapshot_source.preview_texture_dds_path,
        )
        self.assertFalse(hasattr(snapshot_source, "vertices"))
        self.assertFalse(hasattr(snapshot_source, "preview_image"))
        self.assertFalse(hasattr(context.preview_model, "vertices"))

    def test_preview_material_context_deduplicates_exact_input_parameter_tables(
        self,
    ) -> None:
        shared_parameters = tuple(
            PreviewMaterialParameterInput(
                parameter_kind="float",
                parameter_name=f"_parameter{index}",
                numeric_value=float(index),
            )
            for index in range(12)
        )
        distinct_parameters = (
            PreviewMaterialParameterInput(
                parameter_kind="float",
                parameter_name="_inputOnly",
                numeric_value=0.5,
            ),
        )
        repeated_input = PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_materialTexture",
            source_dds_path="textures/weapon_sp.dds",
            material_parameters=shared_parameters,
        )
        distinct_input = PreviewMaterialTextureInput(
            slot_kind="detail",
            parameter_name="_detailDiffuseR",
            source_dds_path="textures/detail.dds",
            material_parameters=distinct_parameters,
        )
        source = SimpleNamespace(
            source_submesh_index=0,
            material="weapon",
            texture="weapon_base",
            preview_material_parameters=shared_parameters,
            preview_material_texture_inputs=(repeated_input, distinct_input),
        )
        controller = SimpleNamespace()

        binding_count = rust_authoring_module.prime_rust_mesh_preview_context(
            controller,
            SimpleNamespace(path="character/weapon.pac", meshes=[source]),
        )

        self.assertEqual(1, binding_count)
        context = getattr(
            controller,
            rust_authoring_module._RUST_PREVIEW_MATERIAL_CONTEXT_ATTR,
        )
        snapshot_source = context.preview_model.submeshes[0]
        snapshot_inputs = snapshot_source.preview_material_texture_inputs
        self.assertEqual(shared_parameters, snapshot_source.preview_material_parameters)
        self.assertEqual((), snapshot_inputs[0].material_parameters)
        self.assertEqual(distinct_parameters, snapshot_inputs[1].material_parameters)
        self.assertEqual(shared_parameters, repeated_input.material_parameters)

    def test_preview_material_context_preserves_same_dds_rgb_parameter_bindings(
        self,
    ) -> None:
        texture_path = "character/texture/cd_texturelayer_003_0001.dds"
        shared_parameters = tuple(
            PreviewMaterialParameterInput(
                parameter_kind="texture",
                parameter_name=f"_detailDiffuseMask{channel}",
                texture_path=texture_path,
            )
            for channel in "RGB"
        )
        first_channel = PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_detailDiffuseMaskR",
            source_texture_path=texture_path,
            source_dds_path="textures/cd_texturelayer_003_0001.dds",
            texture_name="cd_texturelayer_003_0001.dds",
            semantic_type="albedo",
            semantic_subtype="base_color",
            material_name="cd_phm_00_hel_0350",
            shader_family="SkinnedMeshStandard_Ver2",
            sidecar_kind=".pac_xml",
            layer_role="detail",
            layer_channel="r",
            owner_slot_index=4,
            owner_wrapper_item_id="331",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            material_parameters=shared_parameters,
        )
        source = SimpleNamespace(
            source_submesh_index=0,
            material="cd_phm_00_hel_0350",
            texture="cd_texturelayer_003_0101",
            preview_pac_material_owner_slot_index=4,
            preview_material_parameters=shared_parameters,
            preview_material_texture_inputs=(first_channel,),
        )
        controller = SimpleNamespace()

        binding_count = rust_authoring_module.prime_rust_mesh_preview_context(
            controller,
            SimpleNamespace(path="character/model/helmet.pac", meshes=[source]),
        )

        self.assertEqual(1, binding_count)
        context = getattr(
            controller,
            rust_authoring_module._RUST_PREVIEW_MATERIAL_CONTEXT_ATTR,
        )
        snapshot_inputs = (
            context.preview_model.submeshes[0].preview_material_texture_inputs
        )
        self.assertEqual(
            [
                "_detailDiffuseMaskR",
                "_detailDiffuseMaskG",
                "_detailDiffuseMaskB",
            ],
            [item.parameter_name for item in snapshot_inputs],
        )
        self.assertEqual(
            ["r", "g", "b"],
            [item.layer_channel for item in snapshot_inputs],
        )
        self.assertEqual(
            {"textures/cd_texturelayer_003_0001.dds"},
            {item.source_dds_path for item in snapshot_inputs},
        )
        self.assertTrue(
            all(item.owner_slot_index == 4 for item in snapshot_inputs)
        )
        self.assertTrue(
            all(item.material_parameters == () for item in snapshot_inputs)
        )
        self.assertEqual(
            (first_channel,),
            source.preview_material_texture_inputs,
        )

    def test_preview_material_context_rejects_unbounded_source_count(self) -> None:
        class _OversizedSources:
            iterated = False

            def __len__(self) -> int:
                return rust_authoring_module._RUST_PREVIEW_MATERIAL_SOURCE_LIMIT + 1

            def __iter__(self):
                self.iterated = True
                raise AssertionError("oversized material sources must not be iterated")

        oversized_sources = _OversizedSources()
        preview_model = SimpleNamespace(
            meshes=oversized_sources,
        )
        controller = SimpleNamespace()

        with self.assertRaisesRegex(
            rust_authoring_module.RustMeshAuthoringError,
            "too many material sources",
        ):
            rust_authoring_module.prime_rust_mesh_preview_context(
                controller,
                preview_model,
            )
        self.assertFalse(
            hasattr(controller, rust_authoring_module._RUST_PREVIEW_MATERIAL_CONTEXT_ATTR)
        )
        self.assertFalse(oversized_sources.iterated)

    def test_package_rebases_archive_browser_relative_textures_without_mutating_authoritative(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "archive-preview-package"
            source_texture = package_root / "textures" / "body_base.dds"
            source_texture.parent.mkdir(parents=True)
            source_bytes = b"DDS " + bytes(range(128))
            source_texture.write_bytes(source_bytes)
            preview_model = SimpleNamespace(
                path="character/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_dds_path="textures/body_base.dds",
                    )
                ],
            )

            authoritative, session = self._create(
                temporary_root / "session",
                preview_material_model=preview_model,
                material_package_path=package_root,
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(1, len(manifest["textures"]))
                self.assertTrue(manifest["texture_status"]["available"])
                self.assertEqual("", manifest["texture_status"]["reason"])
                copied = session.root / manifest["textures"][0]["file"]["path"]
                self.assertEqual(source_bytes, copied.read_bytes())
                live_mesh = authoritative.working_mesh(
                    "authoritative-rust-test",
                    clone=False,
                )
                self.assertEqual(
                    "",
                    str(
                        getattr(
                            live_mesh.submeshes[0],
                            "preview_texture_dds_path",
                            "",
                        )
                        or ""
                    ),
                )
            finally:
                session.cancel()

    def test_archive_dds_fallback_resolves_the_screenshot_identity_variants(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            base_payload = b"DDS " + bytes(range(128))
            normal_payload = b"DDS " + bytes(reversed(range(128)))
            base_entry = _prepared_dds_entry(
                temporary_root,
                "character/texture/cd_pgm_00_head_0001.dds",
                base_payload,
            )
            normal_entry = _prepared_dds_entry(
                temporary_root,
                "character/texture/cd_pgm_00_head_0001_n.dds",
                normal_payload,
            )
            target_entry = ArchiveEntry(
                path="character/model/1_pc/9_pgm/nude/cd_pgm_00_nude_00_0001.pac",
                pamt_path=base_entry.pamt_path,
                paz_file=base_entry.paz_file,
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            basename_index = {
                base_entry.basename.casefold(): (base_entry,),
                normal_entry.basename.casefold(): (normal_entry,),
            }

            authoritative, session = self._create(
                temporary_root / "session",
                texture_name="CD_PGM_00_Head_00_0001_01",
                material_name="CD_PHM_00_Head_0001_01",
                target_entry=target_entry,
                texture_entries_by_basename=basename_index,
                material_unavailable_reason=(
                    "Recovered material details.\n"
                    "3 embedded material base names had no direct visible DDS match.\n"
                    "Texture Slot Mapping\n- many diagnostic rows"
                ),
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                resources = {row["role"]: row for row in manifest["textures"]}
                self.assertEqual({"base_color", "normal"}, set(resources))
                self.assertEqual("", manifest["texture_status"]["reason"])
                self.assertTrue(manifest["texture_status"]["available"])
                self.assertEqual(
                    base_payload,
                    (session.root / resources["base_color"]["file"]["path"]).read_bytes(),
                )
                self.assertEqual(
                    normal_payload,
                    (session.root / resources["normal"]["file"]["path"]).read_bytes(),
                )
                live_part = authoritative.working_mesh(
                    "authoritative-rust-test",
                    clone=False,
                ).submeshes[0]
                self.assertEqual(
                    "",
                    str(getattr(live_part, "preview_texture_dds_path", "") or ""),
                )
            finally:
                session.cancel()

    def test_archive_dds_fallback_combines_material_family_with_wrapper_identity(
        self,
    ) -> None:
        candidates = rust_authoring_module._rust_texture_identity_candidates(
            "CD_PGM_00_Nude_00_0001_Hand",
            "CD_PHM_00_Nude_0001_hand",
        )
        self.assertIn("cd_phm_00_nude_00_0001_hand.dds", candidates)
        self.assertIn("cd_phm_00_nude_0001_hand.dds", candidates)
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            payload = b"DDS " + bytes(range(128))
            texture_entry = _prepared_dds_entry(
                temporary_root,
                "character/texture/cd_phm_00_nude_00_0001_hand.dds",
                payload,
            )
            target_entry = ArchiveEntry(
                path="character/model/1_pc/9_pgm/nude/cd_pgm_00_nude_00_0001.pac",
                pamt_path=texture_entry.pamt_path,
                paz_file=texture_entry.paz_file,
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            _authoritative, session = self._create(
                temporary_root / "session",
                texture_name="CD_PGM_00_Nude_00_0001_Hand",
                material_name="CD_PHM_00_Nude_0001_hand",
                target_entry=target_entry,
                texture_entries_by_basename={
                    texture_entry.basename.casefold(): (texture_entry,)
                },
            )
            try:
                manifest = json.loads(
                    session.manifest_path.read_text(encoding="utf-8")
                )
                base_resource = next(
                    row
                    for row in manifest["textures"]
                    if row["role"] == "base_color"
                )
                self.assertEqual(
                    payload,
                    (session.root / base_resource["file"]["path"]).read_bytes(),
                )
            finally:
                session.cancel()

    def test_texture_candidate_basenames_stop_at_the_snapshot_limit(self) -> None:
        identity_pairs = tuple((f"texture-{index}", "") for index in range(256))

        def candidates(texture_name: object, _material_name: object) -> tuple[str, ...]:
            return tuple(f"{texture_name}-{index}.dds" for index in range(32))

        with patch.object(
            rust_authoring_module,
            "_rust_texture_identity_candidates",
            side_effect=candidates,
        ) as candidate_mock:
            basenames = rust_authoring_module._rust_texture_candidate_basenames(
                identity_pairs
            )

        self.assertEqual(512, len(basenames))
        self.assertEqual(512, len(set(basenames)))
        self.assertEqual(6, candidate_mock.call_count)

    def test_exact_material_input_basenames_precede_family_candidates(self) -> None:
        basenames = rust_authoring_module._rust_texture_candidate_basenames(
            (("cd_phm_02_blade_0014", "blade"),),
            exact_basenames=(
                "cd_phm_02_blade_0014_emi.dds",
                "cd_phm_02_blade_0014_ma.dds",
            ),
        )

        self.assertEqual(
            (
                "cd_phm_02_blade_0014_emi.dds",
                "cd_phm_02_blade_0014_ma.dds",
            ),
            basenames[:2],
        )

    def test_archive_fallback_restores_exact_emissive_and_layer_mask_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            emissive_name = "cd_phm_02_blade_0014_emi.dds"
            mask_name = "cd_phm_02_blade_0014_ma.dds"
            height_name = "cd_phm_02_blade_0014_height.dds"
            emissive_payload = b"DDS " + b"E" * 128
            mask_payload = b"DDS " + b"M" * 128
            height_payload = b"DDS " + b"H" * 128
            emissive_entry = _prepared_dds_entry(
                temporary_root,
                f"character/texture/{emissive_name}",
                emissive_payload,
            )
            mask_entry = _prepared_dds_entry(
                temporary_root,
                f"character/texture/{mask_name}",
                mask_payload,
            )
            height_entry = _prepared_dds_entry(
                temporary_root,
                f"character/texture/{height_name}",
                height_payload,
            )
            target_entry = ArchiveEntry(
                path="character/model/weapon.pac",
                pamt_path=emissive_entry.pamt_path,
                paz_file=temporary_root / "source.paz",
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )

            def texture_input(
                *,
                parameter_name: str,
                texture_name: str,
                semantic_type: str,
            ) -> PreviewMaterialTextureInput:
                return PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name=parameter_name,
                    texture_name=texture_name,
                    source_texture_path=f"character/texture/{texture_name}",
                    source_dds_path=str(temporary_root / "expired" / texture_name),
                    preview_texture_path=str(
                        temporary_root / "expired" / f"{texture_name}.png"
                    ),
                    semantic_type=semantic_type,
                    material_name="blade",
                )

            preview_material = SimpleNamespace(
                source_submesh_index=0,
                material="blade",
                texture="cd_phm_02_blade_0014",
                preview_material_texture_inputs=(
                    texture_input(
                        parameter_name="_emissiveIntensityTexture",
                        texture_name=emissive_name,
                        semantic_type="emissive",
                    ),
                    texture_input(
                        parameter_name="_colorBlendingMaskTexture",
                        texture_name=mask_name,
                        semantic_type="layer_mask",
                    ),
                    texture_input(
                        parameter_name="_heightTexture",
                        texture_name=height_name,
                        semantic_type="height",
                    ),
                ),
            )
            _authoritative, session = self._create(
                temporary_root / "session",
                preview_material_model=SimpleNamespace(
                    path="character/model/weapon.pac",
                    meshes=[preview_material],
                ),
                texture_name="cd_phm_02_blade_0014",
                material_name="blade",
                target_entry=target_entry,
                texture_entries_by_basename={
                    emissive_name: (emissive_entry,),
                    mask_name: (mask_entry,),
                    height_name: (height_entry,),
                },
            )
            try:
                manifest = json.loads(
                    session.manifest_path.read_text(encoding="utf-8")
                )
                resources = {
                    (row["role"], row["label"]): (
                        session.root / row["file"]["path"]
                    ).read_bytes()
                    for row in manifest["textures"]
                }
                self.assertEqual(
                    emissive_payload,
                    resources[("emissive", emissive_name)],
                )
                self.assertEqual(
                    mask_payload,
                    resources[("layer_mask", mask_name)],
                )
                self.assertEqual(
                    height_payload,
                    resources[("height", height_name)],
                )
            finally:
                session.cancel()

    def test_generic_family_candidates_do_not_invent_height_or_emissive(self) -> None:
        candidates = rust_authoring_module._rust_texture_candidate_basenames(
            (("cd_phm_00_head_0001", "skin"),)
        )

        self.assertNotIn("cd_phm_00_head_0001_disp.dds", candidates)
        self.assertNotIn("cd_phm_00_head_0001_e.dds", candidates)
        self.assertNotIn("cd_phm_00_head_0001_emi.dds", candidates)

    def test_single_archive_candidate_must_match_all_supplied_owner_proof(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            basename = "surface_sp.dds"
            candidate = _prepared_dds_entry(
                root,
                f"overlay/texture/{basename}",
                b"DDS " + b"S" * 128,
            )
            matching_target = ArchiveEntry(
                path="character/model/weapon.pac",
                pamt_path=candidate.pamt_path,
                paz_file=candidate.paz_file,
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            wrong_target = copy.deepcopy(matching_target)
            wrong_target.pamt_path = root / "other.pamt"

            self.assertEqual(
                (),
                rust_authoring_module._unambiguous_rust_texture_entries(
                    basename,
                    (candidate,),
                    target_entry=matching_target,
                    exact_path_hints=(f"character/texture/{basename}",),
                ),
            )
            self.assertEqual(
                (),
                rust_authoring_module._unambiguous_rust_texture_entries(
                    basename,
                    (candidate,),
                    target_entry=wrong_target,
                    exact_path_hints=(f"overlay/texture/{basename}",),
                ),
            )
            self.assertEqual(
                (candidate,),
                rust_authoring_module._unambiguous_rust_texture_entries(
                    basename,
                    (candidate,),
                    target_entry=matching_target,
                    exact_path_hints=(f"overlay/texture/{basename}",),
                ),
            )

    def test_proven_archive_entry_cannot_be_shadowed_by_local_same_name_dds(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_root = root / "archive"
            local_root = root / "local"
            archive_root.mkdir()
            local_root.mkdir()
            basename = "owned_surface.dds"
            archive_payload = b"DDS " + b"A" * 128
            local_payload = b"DDS " + b"L" * 128
            archive_entry = _prepared_dds_entry(
                archive_root,
                f"character/texture/{basename}",
                archive_payload,
            )
            (local_root / basename).write_bytes(local_payload)
            target_entry = ArchiveEntry(
                path="character/model/weapon.pac",
                pamt_path=archive_entry.pamt_path,
                paz_file=archive_entry.paz_file,
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            previous_cwd = Path.cwd()
            session = None
            try:
                os.chdir(local_root)
                _authoritative, session = self._create(
                    root / "session",
                    texture_name=basename,
                    target_entry=target_entry,
                    texture_entries_by_basename={basename: (archive_entry,)},
                )
                manifest = json.loads(
                    session.manifest_path.read_text(encoding="utf-8")
                )
                resource = next(
                    row for row in manifest["textures"] if row["role"] == "base_color"
                )
                self.assertEqual(
                    archive_payload,
                    (session.root / resource["file"]["path"]).read_bytes(),
                )
            finally:
                os.chdir(previous_cwd)
                if session is not None:
                    session.cancel()

    def test_archive_fallback_restores_direct_exact_height_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            basename = "authored_hand_height.dds"
            payload = b"DDS " + b"H" * 128
            height_entry = _prepared_dds_entry(
                root,
                f"character/texture/{basename}",
                payload,
            )
            target_entry = ArchiveEntry(
                path="character/model/hand.pac",
                pamt_path=height_entry.pamt_path,
                paz_file=height_entry.paz_file,
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            preview_material = SimpleNamespace(
                source_submesh_index=0,
                material="hand",
                texture="hand",
                preview_height_texture_dds_path=str(
                    root / "expired" / basename
                ),
            )
            _authoritative, session = self._create(
                root / "session",
                preview_material_model=SimpleNamespace(
                    path="character/model/hand.pac",
                    meshes=[preview_material],
                ),
                texture_name="hand",
                material_name="hand",
                target_entry=target_entry,
                texture_entries_by_basename={basename: (height_entry,)},
            )
            try:
                manifest = json.loads(
                    session.manifest_path.read_text(encoding="utf-8")
                )
                resource = next(
                    row for row in manifest["textures"] if row["role"] == "height"
                )
                self.assertEqual(
                    payload,
                    (session.root / resource["file"]["path"]).read_bytes(),
                )
            finally:
                session.cancel()

    def test_texture_identity_capture_stops_at_its_256_pair_limit(self) -> None:
        class _CountingSources(list[object]):
            yielded = 0

            def __iter__(self):
                for item in super().__iter__():
                    self.yielded += 1
                    yield item

        sources = _CountingSources(
            SimpleNamespace(texture=f"texture-{index}", material="material")
            for index in range(4_096)
        )
        pairs = rust_authoring_module._rust_controller_texture_identities(
            SimpleNamespace(mesh_service=None, active_session_id=""),
            SimpleNamespace(submeshes=sources),
        )

        self.assertEqual(256, len(pairs))
        self.assertEqual(256, sources.yielded)

    def test_material_snapshot_accepts_bounded_multi_owner_armor_graph(self) -> None:
        per_owner_overrides = tuple(range(2_000))
        preview_model = SimpleNamespace(
            path="character/model/layered-armor.pac",
            submeshes=tuple(
                SimpleNamespace(
                    source_submesh_index=owner_index,
                    preview_native_material_overrides=per_owner_overrides,
                )
                for owner_index in range(35)
            ),
        )

        snapshot = rust_authoring_module._snapshot_rust_preview_model(preview_model)

        self.assertEqual(35, len(snapshot.submeshes))
        self.assertEqual(
            per_owner_overrides,
            snapshot.submeshes[-1].preview_native_material_overrides,
        )

    def test_material_snapshot_still_rejects_graph_above_raised_budget(self) -> None:
        per_owner_overrides = tuple(range(2_000))
        preview_model = SimpleNamespace(
            path="character/model/oversized-layered-armor.pac",
            submeshes=tuple(
                SimpleNamespace(
                    source_submesh_index=owner_index,
                    preview_native_material_overrides=per_owner_overrides,
                )
                for owner_index in range(70)
            ),
        )

        with self.assertRaisesRegex(
            rust_authoring_module.RustMeshAuthoringError,
            "safe snapshot limit",
        ):
            rust_authoring_module._snapshot_rust_preview_model(preview_model)

    def test_archive_dds_fallback_rejects_unowned_same_basename_ambiguity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            first_root = temporary_root / "first-overlay"
            second_root = temporary_root / "second-overlay"
            first_root.mkdir()
            second_root.mkdir()
            basename = "cd_pgm_00_head_0001.dds"
            first = _prepared_dds_entry(
                first_root,
                f"character/texture/{basename}",
                b"DDS " + b"A" * 128,
            )
            second = _prepared_dds_entry(
                second_root,
                f"overlay/texture/{basename}",
                b"DDS " + b"B" * 128,
            )
            target_entry = ArchiveEntry(
                path="character/model/body.pac",
                pamt_path=temporary_root / "target.pamt",
                paz_file=temporary_root / "target.paz",
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                texture_name="CD_PGM_00_Head_00_0001_01",
                target_entry=target_entry,
                texture_entries_by_basename={basename: (first, second)},
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual([], manifest["textures"])
                self.assertFalse(manifest["texture_status"]["available"])
            finally:
                session.cancel()

    def test_texture_snapshot_never_truncates_an_ambiguous_basename_bucket(
        self,
    ) -> None:
        filler_name = "filler.dds"
        target_name = "target.dds"

        def entry(virtual_path: str, offset: int) -> ArchiveEntry:
            return ArchiveEntry(
                path=virtual_path,
                pamt_path=Path(f"archive-{offset}.pamt"),
                paz_file=Path(f"archive-{offset}.paz"),
                offset=offset,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=offset,
            )

        fillers = (
            entry(f"first/{filler_name}", 1),
            entry(f"second/{filler_name}", 2),
        )
        ambiguous = (
            entry(f"first/{target_name}", 3),
            entry(f"second/{target_name}", 4),
        )
        with patch.object(rust_authoring_module, "_RUST_TEXTURE_SNAPSHOT_LIMIT", 3):
            captured = rust_authoring_module._snapshot_rust_texture_entries(
                (filler_name, target_name),
                {
                    filler_name: fillers,
                    target_name: ambiguous,
                },
            )

        self.assertEqual(
            tuple(entry.identity for entry in fillers),
            tuple(entry.identity for entry in captured),
        )
        self.assertFalse(any(entry.basename == target_name for entry in captured))

    def test_texture_snapshot_stops_before_copying_an_oversized_bucket(self) -> None:
        target_name = "target.dds"

        class _CountingEntries(list[ArchiveEntry]):
            yielded = 0

            def __iter__(self):
                for item in super().__iter__():
                    self.yielded += 1
                    yield item

        entries = _CountingEntries(
            ArchiveEntry(
                path=f"overlay-{index}/{target_name}",
                pamt_path=Path(f"archive-{index}.pamt"),
                paz_file=Path(f"archive-{index}.paz"),
                offset=index,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=index,
            )
            for index in range(100)
        )
        original_deepcopy = copy.deepcopy
        with (
            patch.object(rust_authoring_module, "_RUST_TEXTURE_SNAPSHOT_LIMIT", 3),
            patch.object(
                rust_authoring_module.copy,
                "deepcopy",
                wraps=original_deepcopy,
            ) as deepcopy_mock,
        ):
            captured = rust_authoring_module._snapshot_rust_texture_entries(
                (target_name,),
                {target_name: entries},
            )

        self.assertEqual((), captured)
        self.assertEqual(0, entries.yielded)
        deepcopy_mock.assert_not_called()

    def test_archive_dds_fallback_prefers_unique_exact_target_archive_owner(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            target_root = temporary_root / "target-archive"
            overlay_root = temporary_root / "overlay-archive"
            target_root.mkdir()
            overlay_root.mkdir()
            basename = "cd_pgm_00_head_0001.dds"
            target_payload = b"DDS " + b"T" * 128
            target_owned = _prepared_dds_entry(
                target_root,
                f"character/texture/{basename}",
                target_payload,
            )
            unrelated = _prepared_dds_entry(
                overlay_root,
                f"zzzz/texture/{basename}",
                b"DDS " + b"Z" * 128,
            )
            target_entry = ArchiveEntry(
                path="character/model/body.pac",
                pamt_path=target_owned.pamt_path,
                paz_file=target_root / "source.paz",
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                texture_name="CD_PGM_00_Head_00_0001_01",
                target_entry=target_entry,
                texture_entries_by_basename={
                    basename: (unrelated, target_owned),
                },
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                resource = next(
                    row for row in manifest["textures"] if row["role"] == "base_color"
                )
                self.assertEqual(
                    target_payload,
                    (session.root / resource["file"]["path"]).read_bytes(),
                )
            finally:
                session.cancel()

    def test_archive_dds_fallback_prefers_unique_exact_virtual_path_owner(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            exact_root = temporary_root / "exact"
            overlay_root = temporary_root / "overlay"
            exact_root.mkdir()
            overlay_root.mkdir()
            basename = "cd_pgm_00_head_0001.dds"
            exact_payload = b"DDS " + b"E" * 128
            exact = _prepared_dds_entry(
                exact_root,
                f"character/texture/{basename}",
                exact_payload,
            )
            overlay = _prepared_dds_entry(
                overlay_root,
                f"overlay/texture/{basename}",
                b"DDS " + b"O" * 128,
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                texture_name=f"character/texture/{basename}",
                texture_entries_by_basename={basename: (overlay, exact)},
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                resource = next(
                    row for row in manifest["textures"] if row["role"] == "base_color"
                )
                self.assertEqual(
                    exact_payload,
                    (session.root / resource["file"]["path"]).read_bytes(),
                )
            finally:
                session.cancel()

    def test_texture_copy_cancellation_removes_mid_copy_staging_file(self) -> None:
        class _CancelAfterFirstChunk:
            def __init__(self) -> None:
                self.checks = 0

            def is_set(self) -> bool:
                self.checks += 1
                return self.checks >= 5

        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            session_root = temporary_root / "session"
            session_root.mkdir()
            root_identity = rust_authoring_module._session_root_identity(session_root)
            source = temporary_root / "large.dds"
            source.write_bytes(b"DDS " + b"X" * (2 * 1024 * 1024))

            with self.assertRaisesRegex(
                RustMeshCancellationError,
                "texture preparation was cancelled",
            ):
                rust_authoring_module._atomic_copy_texture_payload(
                    session_root,
                    source,
                    0,
                    expected_root_identity=root_identity,
                    stop_event=_CancelAfterFirstChunk(),  # type: ignore[arg-type]
                )

            self.assertEqual([], list(session_root.iterdir()))

    def test_texture_copy_rejects_aggregate_growth_before_writing_beyond_limit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            session_root = temporary_root / "session"
            session_root.mkdir()
            root_identity = rust_authoring_module._session_root_identity(session_root)
            source = temporary_root / "growing.dds"
            source.write_bytes(b"DDS " + b"G" * (2 * 1024 * 1024))
            limit = 1_500_000
            original_stat = Path.stat
            original_open = Path.open
            maximum_written = 0

            def underreported_source_stat(
                path: Path,
                *args: object,
                **kwargs: object,
            ) -> object:
                if path == source:
                    return SimpleNamespace(st_size=4)
                return original_stat(path, *args, **kwargs)

            class _TrackedWriter:
                def __init__(self, stream: object) -> None:
                    self.stream = stream

                def __enter__(self) -> "_TrackedWriter":
                    self.stream.__enter__()
                    return self

                def __exit__(self, *args: object) -> object:
                    return self.stream.__exit__(*args)

                def write(self, data: bytes) -> int:
                    nonlocal maximum_written
                    written = self.stream.write(data)
                    maximum_written += int(written)
                    if maximum_written > limit:
                        raise AssertionError("texture copy wrote beyond aggregate limit")
                    return int(written)

                def __getattr__(self, name: str) -> object:
                    return getattr(self.stream, name)

            def tracked_open(
                path: Path,
                *args: object,
                **kwargs: object,
            ) -> object:
                stream = original_open(path, *args, **kwargs)
                if path.parent == session_root and "x" in str(args[0] if args else ""):
                    return _TrackedWriter(stream)
                return stream

            with (
                patch.object(Path, "stat", underreported_source_stat),
                patch.object(Path, "open", tracked_open),
                patch(
                    "cdmw.services.mesh_rust_authoring._SESSION_MAX_TOTAL_BYTES",
                    limit,
                ),
                self.assertRaisesRegex(RustMeshProtocolError, "aggregate limit"),
            ):
                rust_authoring_module._atomic_copy_texture_payload(
                    session_root,
                    source,
                    0,
                    expected_root_identity=root_identity,
                )

            self.assertGreater(maximum_written, 0)
            self.assertLessEqual(maximum_written, limit)
            self.assertEqual([], list(session_root.iterdir()))

    def test_pre_cancelled_texture_preparation_creates_no_session_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            authoritative = MeshService(
                settings=_Settings(temporary_root / "settings.ini")
            )
            mesh = parse_pac(_pac_fixture(), "cancelled-rust-authoring.pac")
            view = authoritative.open_edit_session(
                mesh,
                session_id="cancelled-rust-test",
                mode="edit",
            )
            controller = SimpleNamespace(
                mesh_service=authoritative,
                active_session_id=view.session_id,
            )
            stop_event = threading.Event()
            stop_event.set()
            root = temporary_root / "cancelled-session"

            with self.assertRaises(RustMeshCancellationError):
                RustMeshAuthoringSession.create(
                    controller,
                    root,
                    process_generation=1,
                    stop_event=stop_event,
                )
            self.assertFalse(root.exists())

    def test_package_rejects_absolute_texture_outside_archive_browser_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "archive-preview-package"
            package_root.mkdir()
            outside_texture = temporary_root / "outside.dds"
            outside_texture.write_bytes(b"DDS " + bytes(range(64)))
            preview_model = SimpleNamespace(
                path="character/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_dds_path=str(outside_texture),
                    )
                ],
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                preview_material_model=preview_model,
                material_package_path=package_root,
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual([], manifest["textures"])
                self.assertFalse(manifest["texture_status"]["available"])
                self.assertIn(
                    "outside the leased package",
                    manifest["texture_status"]["reason"],
                )
            finally:
                session.cancel()

    def test_full_resolver_absolute_texture_is_accepted_without_stale_package_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            resolved_texture = temporary_root / "resolved-from-archive.dds"
            source_bytes = b"DDS " + bytes(range(96))
            resolved_texture.write_bytes(source_bytes)
            preview_model = SimpleNamespace(
                path="character/model/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_dds_path=str(resolved_texture),
                    )
                ],
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                preview_material_model=preview_model,
                material_package_path=None,
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertTrue(manifest["texture_status"]["available"])
                resources = [
                    row
                    for row in manifest["textures"]
                    if row["role"] == "base_color"
                ]
                self.assertEqual(1, len(resources))
                self.assertEqual(
                    source_bytes,
                    (session.root / resources[0]["file"]["path"]).read_bytes(),
                )
            finally:
                session.cancel()

    def test_package_accepts_manifest_declared_preview_cache_dds(self) -> None:
        """Mirror Archive Browser's models/package + native/dds cache layout."""

        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            preview_root = temporary_root / "cache" / "preview"
            package_root = (
                preview_root
                / "models"
                / "packages"
                / "active-cache-key"
                / "package"
            )
            dds_root = preview_root / "native" / "dds"
            package_root.mkdir(parents=True)
            dds_root.mkdir(parents=True)
            source_texture = dds_root / "5f18c99a01d9629c_body_base.dds"
            source_bytes = b"DDS " + bytes(range(128))
            source_texture.write_bytes(source_bytes)
            (package_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 8,
                        "use_textures": True,
                        "batches": [
                            {
                                "dds_textures": {
                                    "base": {
                                        "source_path": str(source_texture),
                                        "archive_path": "character/texture/body_base.dds",
                                        "available": True,
                                        "direct_upload_candidate": True,
                                    }
                                }
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            preview_model = SimpleNamespace(
                path="character/model/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_path=str(source_texture),
                        preview_texture_dds_path=str(source_texture),
                    )
                ],
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                preview_material_model=preview_model,
                material_package_path=package_root,
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertTrue(manifest["texture_status"]["available"])
                self.assertEqual("", manifest["texture_status"]["reason"])
                resources = [
                    item
                    for item in manifest["textures"]
                    if item["role"] == "base_color"
                ]
                self.assertEqual(1, len(resources))
                self.assertEqual(
                    source_bytes,
                    (session.root / resources[0]["file"]["path"]).read_bytes(),
                )
            finally:
                session.cancel()

    def test_package_accepts_package_relative_declared_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "archive-preview-package"
            texture_root = package_root / "textures"
            texture_root.mkdir(parents=True)
            source_texture = texture_root / "body_base.dds"
            source_bytes = b"DDS " + bytes(range(96))
            source_texture.write_bytes(source_bytes)
            (package_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "batches": [
                            {
                                "dds_textures": {
                                    "base": {
                                        "source_path": "textures/body_base.dds",
                                        "available": True,
                                        "direct_upload_candidate": True,
                                    }
                                }
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            preview_model = SimpleNamespace(
                path="character/model/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_dds_path="textures/body_base.dds",
                    )
                ],
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                preview_material_model=preview_model,
                material_package_path=package_root,
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertTrue(manifest["texture_status"]["available"])
                resource = next(
                    item
                    for item in manifest["textures"]
                    if item["role"] == "base_color"
                )
                self.assertEqual(
                    source_bytes,
                    (session.root / resource["file"]["path"]).read_bytes(),
                )
            finally:
                session.cancel()

    def test_package_rejects_manifest_declared_dds_outside_preview_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "archive-preview-package"
            package_root.mkdir()
            outside_texture = temporary_root / "outside.dds"
            outside_texture.write_bytes(b"DDS " + bytes(range(64)))
            (package_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "batches": [
                            {
                                "dds_textures": {
                                    "base": {
                                        "source_path": str(outside_texture),
                                        "available": True,
                                        "direct_upload_candidate": True,
                                    }
                                }
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            preview_model = SimpleNamespace(
                path="character/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_dds_path=str(outside_texture),
                    )
                ],
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                preview_material_model=preview_model,
                material_package_path=package_root,
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual([], manifest["textures"])
                self.assertFalse(manifest["texture_status"]["available"])
                self.assertIn(
                    "outside the leased package",
                    manifest["texture_status"]["reason"],
                )
            finally:
                session.cancel()

    def test_dotnet_package_rebases_absolute_cache_source_to_owned_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "dotnet-preview-package"
            texture_root = package_root / "textures"
            texture_root.mkdir(parents=True)
            outside_texture = temporary_root / "native-cache-base.dds"
            outside_texture.write_bytes(b"DDS outside-cache-must-not-be-copied")
            owned_bytes = b"DDS " + b"package-owned-exact-texture" * 4
            owned_texture = texture_root / "base_owned.dds"
            owned_texture.write_bytes(owned_bytes)
            duplicate_owned_texture = texture_root / "albedo_owned.dds"
            duplicate_owned_texture.write_bytes(owned_bytes)
            (package_root / "net_materials.json").write_text(
                json.dumps(
                    {
                        "resources": [
                            {
                                "path": "textures/base_owned.dds",
                                "source_reference": str(outside_texture),
                                "fingerprint": hashlib.sha256(owned_bytes).hexdigest(),
                            },
                            {
                                "path": "textures/albedo_owned.dds",
                                "source_reference": str(outside_texture),
                                "fingerprint": hashlib.sha256(owned_bytes).hexdigest(),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            preview_model = SimpleNamespace(
                path="character/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_dds_path=str(outside_texture),
                    )
                ],
            )

            with patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                return_value={},
                create=True,
            ):
                _authoritative, session = self._create(
                    temporary_root / "session",
                    preview_material_model=preview_model,
                    material_package_path=package_root,
                )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                resource = next(
                    item
                    for item in manifest["textures"]
                    if item["role"] == "base_color"
                )
                packaged = session.root / resource["file"]["path"]
                self.assertEqual(owned_bytes, packaged.read_bytes())
                self.assertNotEqual(outside_texture.read_bytes(), packaged.read_bytes())
                self.assertTrue(manifest["texture_status"]["available"])
            finally:
                session.cancel()

    def test_dotnet_package_rejects_owned_dds_with_mismatched_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "dotnet-preview-package"
            texture_root = package_root / "textures"
            texture_root.mkdir(parents=True)
            outside_texture = temporary_root / "native-cache-base.dds"
            outside_texture.write_bytes(b"DDS outside-cache")
            owned_texture = texture_root / "base_owned.dds"
            owned_texture.write_bytes(b"DDS package-owned")
            (package_root / "net_materials.json").write_text(
                json.dumps(
                    {
                        "resources": [
                            {
                                "path": "textures/base_owned.dds",
                                "source_reference": str(outside_texture),
                                "fingerprint": "0" * 64,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            preview_model = SimpleNamespace(
                path="character/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_dds_path=str(outside_texture),
                    )
                ],
            )

            with patch.object(
                rust_authoring_module,
                "_vortice_material_layer_overrides",
                return_value={},
                create=True,
            ):
                _authoritative, session = self._create(
                    temporary_root / "session",
                    preview_material_model=preview_model,
                    material_package_path=package_root,
                )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual([], manifest["textures"])
                self.assertFalse(manifest["texture_status"]["available"])
                self.assertIn(
                    "outside the leased package",
                    manifest["texture_status"]["reason"],
                )
            finally:
                session.cancel()

    def test_package_rejects_undeclared_dds_inside_preview_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            preview_root = temporary_root / "cache" / "preview"
            package_root = (
                preview_root
                / "models"
                / "packages"
                / "active-cache-key"
                / "package"
            )
            dds_root = preview_root / "native" / "dds"
            package_root.mkdir(parents=True)
            dds_root.mkdir(parents=True)
            declared_texture = dds_root / "declared.dds"
            undeclared_texture = dds_root / "undeclared.dds"
            declared_texture.write_bytes(b"DDS " + b"D" * 64)
            undeclared_texture.write_bytes(b"DDS " + b"U" * 64)
            (package_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "batches": [
                            {
                                "dds_textures": {
                                    "base": {
                                        "source_path": str(declared_texture),
                                        "available": True,
                                        "direct_upload_candidate": True,
                                    }
                                }
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            preview_model = SimpleNamespace(
                path="character/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_dds_path=str(undeclared_texture),
                    )
                ],
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                preview_material_model=preview_model,
                material_package_path=package_root,
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual([], manifest["textures"])
                self.assertFalse(manifest["texture_status"]["available"])
                self.assertIn(
                    "outside the leased package",
                    manifest["texture_status"]["reason"],
                )
            finally:
                session.cancel()

    def test_relative_texture_without_package_root_never_uses_process_cwd(self) -> None:
        self.assertEqual(
            "",
            rust_authoring_module._package_resolved_texture_path(
                "textures/body_base.dds",
                None,
            ),
        )

    def test_package_reports_an_explicit_reason_for_unusable_resolved_textures(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "archive-preview-package"
            package_root.mkdir()
            (temporary_root / "outside.dds").write_bytes(b"DDS " + bytes(range(64)))
            preview_model = SimpleNamespace(
                path="character/body.pac",
                meshes=[
                    SimpleNamespace(
                        source_submesh_index=0,
                        preview_texture_dds_path="../outside.dds",
                    )
                ],
            )

            _authoritative, session = self._create(
                temporary_root / "session",
                preview_material_model=preview_model,
                material_package_path=package_root,
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual([], manifest["textures"])
                self.assertFalse(manifest["texture_status"]["available"])
                self.assertIn(
                    "outside the leased package",
                    manifest["texture_status"]["reason"],
                )
            finally:
                session.cancel()

    def test_state_carries_a_bounded_shadow_skeleton_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bone_limit = rust_authoring_module._SKELETON_STATE_MAX_BONES
            skeleton = Skeleton(
                path="character/model/owned-body.pab",
                bones=[
                    Bone(index=index, name=f"Bone {index}", parent_index=-1)
                    for index in range(bone_limit + 3)
                ],
                bone_count=bone_limit + 3,
            )
            _authoritative, session = self._create(
                Path(temporary) / "session",
                skeleton=skeleton,
            )
            try:
                state = session.state_payload(include_document=False)
                summary = state["skeleton"]

                self.assertTrue(summary["available"])
                self.assertTrue(summary["source_weights_available"])
                self.assertEqual("character/model/owned-body.pab", summary["skeleton_source"])
                self.assertEqual(bone_limit + 3, summary["bone_count"])
                self.assertTrue(summary["bones_truncated"])
                self.assertEqual(bone_limit, len(summary["bones"]))
                self.assertEqual("Bone 0", summary["bones"][0]["name"])
                self.assertFalse(summary["weight_edit_capability"]["enabled"])
            finally:
                session.cancel()

    def test_unresolved_pac_slots_are_not_reported_as_skeleton_bone_indices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = Skeleton(
                path="character/model/unresolved-body.pab",
                bones=[Bone(index=index, name=f"Bone {index}") for index in range(8)],
                bone_count=8,
            )
            _authoritative, session = self._create(
                Path(temporary) / "session",
                skeleton=skeleton,
            )
            select = _request(session, "command_request", 1)
            select.update(
                command="select",
                arguments={
                    "selection": {
                        "vertices_by_submesh": {"0": [0]},
                        "edges_by_submesh": {},
                        "faces_by_submesh": {},
                        "source_indices": [],
                    },
                    "operation": "replace",
                },
            )
            selected = session.run_command(select)["state"]["skeleton"]
            row = selected["selected_vertex_weights"][0]

            self.assertFalse(selected["weight_edit_capability"]["enabled"])
            self.assertFalse(row["influences_resolved"])
            self.assertEqual([], row["influences"])
            self.assertEqual([[3, 200.0 / 255.0], [7, 55.0 / 255.0]], row["influence_slots"])
            self.assertEqual("Slot 3", row["influence_labels"][0][0])
            session.cancel()

    def test_source_weight_capability_uses_immutable_base_when_working_weights_are_absent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _authoritative, session = self._create(Path(temporary) / "session")
            try:
                shadow = session.shadow_service._session(session.shadow_session_id)
                with shadow.export_lock:
                    self.assertTrue(
                        any(submesh.bone_weights for submesh in shadow.base_mesh.submeshes)
                    )
                    for submesh in shadow.working_mesh.submeshes:
                        submesh.bone_indices = []
                        submesh.bone_weights = []
                    shadow.working_mesh.has_bones = False

                skeleton = session.state_payload(include_document=False)["skeleton"]

                self.assertFalse(skeleton["skinned"])
                self.assertTrue(skeleton["source_weights_available"])
            finally:
                session.cancel()

    def test_source_weight_capability_does_not_follow_working_mesh_weights(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _authoritative, session = self._create(
                Path(temporary) / "session",
                skinned_source=False,
            )
            try:
                shadow = session.shadow_service._session(session.shadow_session_id)
                with shadow.export_lock:
                    for submesh in shadow.working_mesh.submeshes:
                        vertex_count = len(submesh.vertices)
                        submesh.bone_indices = [(3,)] * vertex_count
                        submesh.bone_weights = [(1.0,)] * vertex_count
                    shadow.working_mesh.has_bones = True

                skeleton = session.state_payload(include_document=False)["skeleton"]

                self.assertTrue(skeleton["skinned"])
                self.assertFalse(skeleton["source_weights_available"])
            finally:
                session.cancel()

    def test_mesh_action_is_allowlisted_policy_checked_and_undoable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _authoritative, session = self._create(root / "session")
            selection = {
                "vertices_by_submesh": {},
                "edges_by_submesh": {},
                "faces_by_submesh": {"0": [0]},
                "source_indices": [],
            }
            blocked = _request(session, "command_request", 1)
            blocked.update(
                command="mesh_action",
                arguments={
                    "action": "mirror",
                    "selection": selection,
                    "params": {"axis": "x"},
                },
            )

            with self.assertRaisesRegex(
                RustMeshValidationError,
                "Mirror has no exact writeback route",
            ):
                session.run_command(blocked)
            self.assertEqual(
                0,
                session.shadow_service.session_view(session.shadow_session_id).revision,
            )

            configure = _request(session, "command_request", 2)
            configure.update(
                command="configure_output_policy",
                arguments={
                    "policy": "free_edit_rebuild",
                    "destination": str(root / "free-edit"),
                },
            )
            session.run_command(configure)
            mirror = _request(session, "command_request", 3)
            mirror.update(
                command="mesh_action",
                arguments={
                    "action": "mirror",
                    "selection": selection,
                    "params": {"axis": "x"},
                    "label": "Mirror X",
                },
            )

            response = session.run_command(mirror)

            view = session.shadow_service.session_view(session.shadow_session_id)
            self.assertGreater(view.revision, 1)
            self.assertEqual(1, view.undo_count)
            self.assertEqual("mirror", response["result"]["action"])
            self.assertEqual("Mirror X", view.history_entries[-1].label)
            stale_revision = view.revision
            unsupported = _request(session, "command_request", 4)
            unsupported.update(
                command="mesh_action",
                arguments={
                    "action": "mirror",
                    "selection": selection,
                    "params": {"axis": "x", "arbitrary": True},
                },
            )
            with self.assertRaisesRegex(
                RustMeshProtocolError,
                "unsupported params: arbitrary",
            ):
                session.run_command(unsupported)
            self.assertEqual(
                stale_revision,
                session.shadow_service.session_view(session.shadow_session_id).revision,
            )
            session.cancel()

    def test_direct_topology_request_cannot_bypass_exact_output_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _authoritative, session = self._create(Path(temporary) / "session")
            try:
                before_view = session.shadow_service.session_view(
                    session.shadow_session_id
                )
                before_mesh = session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=True,
                )
                request = _request(session, "command_request", 1)
                request.update(
                    command="topology",
                    arguments={
                        "action": "extrude",
                        "selection": {
                            "vertices_by_submesh": {},
                            "edges_by_submesh": {},
                            "faces_by_submesh": {"0": [0]},
                            "source_indices": [],
                        },
                        "params": {"offset": [0.0, 0.0, 0.25]},
                    },
                )

                with self.assertRaisesRegex(
                    RustMeshValidationError,
                    "Extrude has no exact writeback route",
                ):
                    session.run_command(request)

                after_view = session.shadow_service.session_view(
                    session.shadow_session_id
                )
                after_mesh = session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=False,
                )
                self.assertEqual(before_view.revision, after_view.revision)
                self.assertEqual(before_view.undo_count, after_view.undo_count)
                self.assertEqual(
                    before_mesh.submeshes[0].vertices,
                    after_mesh.submeshes[0].vertices,
                )
                self.assertEqual(
                    before_mesh.submeshes[0].faces,
                    after_mesh.submeshes[0].faces,
                )
            finally:
                session.cancel()

    def test_integrated_rust_ui_host_action_contract_is_complete(self) -> None:
        self.assertEqual(
            {
                "delete",
                "subdivide",
                "refine_smooth",
                "duplicate",
                "extrude",
                "inset",
                "loop_cut",
                "edge_split",
                "split",
                "dissolve",
                "bridge",
                "fill",
                "merge",
                "weld",
                "separate",
            },
            set(rust_authoring_module._HOST_TOPOLOGY_ACTIONS),
        )
        self.assertEqual(
            {
                "mirror",
                "remove_doubles",
                "delete_loose_vertices",
                "compact_orphans",
                "fix_winding",
                "fill_holes",
                "recalculate_normals",
                "generate_tangents",
                "flip_normals",
                "sharpen_normals",
                "soften_normals",
                "weighted_normals",
                "copy_normals",
                "uv_transform",
            },
            set(rust_authoring_module._HOST_MESH_ACTION_PARAMS),
        )

    def test_topology_requests_reject_out_of_contract_params_and_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _authoritative, session = self._create(root / "session")
            try:
                configure = _request(session, "command_request", 1)
                configure.update(
                    command="configure_output_policy",
                    arguments={
                        "policy": "free_edit_rebuild",
                        "destination": str(root / "free-edit"),
                    },
                )
                session.run_command(configure)
                before = session.shadow_service.session_view(
                    session.shadow_session_id
                )
                unsupported = _request(session, "command_request", 2)
                unsupported.update(
                    command="topology",
                    arguments={
                        "action": "extrude",
                        "selection": {
                            "vertices_by_submesh": {},
                            "edges_by_submesh": {},
                            "faces_by_submesh": {"0": [0]},
                            "source_indices": [],
                        },
                        "params": {"offset": [0.0, 0.0, 0.25], "arbitrary": True},
                    },
                )
                with self.assertRaisesRegex(
                    RustMeshProtocolError,
                    "unsupported params: arbitrary",
                ):
                    session.run_command(unsupported)
                invalid_selection = _request(session, "command_request", 3)
                invalid_selection.update(
                    command="topology",
                    arguments={
                        "action": "subdivide",
                        "selection": {
                            "vertices_by_submesh": {},
                            "edges_by_submesh": {},
                            "faces_by_submesh": {"0": [999]},
                            "source_indices": [],
                        },
                        "params": {},
                    },
                )
                with self.assertRaisesRegex(
                    RustMeshProtocolError,
                    "selection contains invalid mesh elements",
                ):
                    session.run_command(invalid_selection)
                delete_only_part = _request(session, "command_request", 4)
                delete_only_part.update(
                    command="topology",
                    arguments={
                        "action": "delete",
                        "selection": {
                            "vertices_by_submesh": {},
                            "edges_by_submesh": {},
                            "faces_by_submesh": {},
                            "source_indices": [0],
                        },
                        "params": {"delete_parts": True},
                    },
                )
                with self.assertRaisesRegex(
                    RustMeshValidationError,
                    "cannot remove every Part",
                ):
                    session.run_command(delete_only_part)
                after = session.shadow_service.session_view(
                    session.shadow_session_id
                )
                self.assertEqual(before.revision, after.revision)
                self.assertEqual(before.undo_count, after.undo_count)
            finally:
                session.cancel()

    def test_mesh_action_routes_normals_and_uv_through_shadow_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _authoritative, session = self._create(Path(temporary) / "session")
            face_selection = {
                "vertices_by_submesh": {},
                "edges_by_submesh": {},
                "faces_by_submesh": {"0": [0]},
                "source_indices": [],
            }
            flip = _request(session, "command_request", 1)
            flip.update(
                command="mesh_action",
                arguments={
                    "action": "flip_normals",
                    "selection": face_selection,
                    "params": {},
                },
            )
            first = session.run_command(flip)
            uv_before = tuple(
                session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=False,
                ).submeshes[0].uvs
            )
            uv = _request(session, "command_request", 2)
            uv.update(
                command="mesh_action",
                arguments={
                    "action": "uv_transform",
                    "selection": {
                        "vertices_by_submesh": {"0": [0]},
                        "edges_by_submesh": {},
                        "faces_by_submesh": {},
                        "source_indices": [],
                    },
                    "params": {"offset": [0.125, 0.0]},
                },
            )

            second = session.run_command(uv)

            view = session.shadow_service.session_view(session.shadow_session_id)
            uv_after = session.shadow_service.working_mesh(
                session.shadow_session_id,
                clone=False,
            ).submeshes[0].uvs
            self.assertEqual("flip_normals", first["result"]["action"])
            self.assertEqual("uv_transform", second["result"]["action"])
            self.assertEqual(2, view.undo_count)
            self.assertAlmostEqual(uv_before[0][0] + 0.125, uv_after[0][0])
            session.cancel()

    def test_rig_commands_use_explicit_selection_and_shadow_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = Skeleton(
                path="character/model/owned-rig.pab",
                bones=[
                    Bone(
                        index=100 + index,
                        name=f"Bone {index}",
                        name_hash=0xA1000000 + index,
                        parent_index=-1,
                    )
                    for index in range(8)
                ],
                bone_count=8,
            )
            _authoritative, session = self._create(
                Path(temporary) / "session",
                skeleton=skeleton,
            )
            select_bone = _request(session, "command_request", 1)
            select_bone.update(
                command="rig_select_bone",
                arguments={"bone_index": 107},
            )
            selected = session.run_command(select_bone)
            explicit_selection = {
                "vertices_by_submesh": {"0": [0]},
                "edges_by_submesh": {},
                "faces_by_submesh": {},
                "source_indices": [],
            }
            normalize = _request(session, "command_request", 2)
            normalize.update(
                command="rig_normalize_weights",
                arguments={"selection": explicit_selection},
            )
            normalized = session.run_command(normalize)
            adjust = _request(session, "command_request", 3)
            adjust.update(
                command="rig_adjust_weight",
                arguments={"selection": explicit_selection, "delta": 0.1},
            )
            adjusted = session.run_command(adjust)
            transfer = _request(session, "command_request", 4)
            transfer.update(
                command="rig_transfer_weights",
                arguments={"selection": explicit_selection},
            )
            transferred = session.run_command(transfer)

            view = session.shadow_service.session_view(session.shadow_session_id)
            final_weights = session.shadow_service.working_mesh(
                session.shadow_session_id,
                clone=False,
            ).submeshes[0].bone_weights[0]
            self.assertEqual(107, selected["state"]["skeleton"]["selected_bone_index"])
            self.assertEqual(
                [103, 107],
                [
                    influence[0]
                    for influence in normalized["state"]["skeleton"][
                        "selected_vertex_weights"
                    ][0]["influences"]
                ],
            )
            self.assertEqual(1, len(normalized["state"]["skeleton"]["selected_vertex_weights"]))
            self.assertGreater(
                adjusted["state"]["skeleton"]["selected_vertex_weights"][0][
                    "selected_bone_weight"
                ],
                normalized["state"]["skeleton"]["selected_vertex_weights"][0][
                    "selected_bone_weight"
                ],
            )
            self.assertAlmostEqual(1.0, sum(final_weights), places=6)
            self.assertAlmostEqual(0.2156862745, final_weights[1], places=6)
            self.assertEqual(2, view.undo_count)
            self.assertEqual(4, transferred["state"]["base_revision"])
            self.assertTrue(
                transferred["state"]["skeleton"]["weight_edit_capability"][
                    "enabled"
                ]
            )
            skin_operations = [
                operation
                for operation in session.shadow_service._session(
                    session.shadow_session_id
                ).edit_operations
                if operation["operation"] == "replace_skin_weights_same_count"
            ]
            self.assertEqual(2, len(skin_operations))
            self.assertEqual(
                {"rig_adjust_weight", "rig_transfer_weights"},
                {
                    operation["metadata"]["service_action"]
                    for operation in skin_operations
                },
            )
            undo = _request(session, "command_request", 5)
            undo.update(command="undo", arguments={})
            session.run_command(undo)
            self.assertEqual(
                1,
                len(
                    [
                        operation
                        for operation in session.shadow_service._session(
                            session.shadow_session_id
                        ).edit_operations
                        if operation["operation"]
                        == "replace_skin_weights_same_count"
                    ]
                ),
            )
            redo = _request(session, "command_request", 6)
            redo.update(command="redo", arguments={})
            session.run_command(redo)
            self.assertEqual(
                2,
                len(
                    [
                        operation
                        for operation in session.shadow_service._session(
                            session.shadow_session_id
                        ).edit_operations
                        if operation["operation"]
                        == "replace_skin_weights_same_count"
                    ]
                ),
            )
            session.cancel()

    def test_free_edit_disables_rig_weight_mutation_without_changing_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skeleton = Skeleton(
                path="character/model/owned-rig.pab",
                bones=[
                    Bone(
                        index=index,
                        name=f"Bone {index}",
                        name_hash=0xA3000000 + index,
                    )
                    for index in range(8)
                ],
                bone_count=8,
            )
            _authoritative, session = self._create(
                root / "session",
                skeleton=skeleton,
            )
            select_bone = _request(session, "command_request", 1)
            select_bone.update(command="rig_select_bone", arguments={"bone_index": 7})
            session.run_command(select_bone)
            configure = _request(session, "command_request", 2)
            configure.update(
                command="configure_output_policy",
                arguments={
                    "policy": "free_edit_rebuild",
                    "destination": str(root / "new-free-edit-output"),
                },
            )
            configured = session.run_command(configure)
            before = copy.deepcopy(
                session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=False,
                ).submeshes[0].bone_weights
            )
            before_revision = session.shadow_service.session_view(
                session.shadow_session_id
            ).revision
            adjust = _request(session, "command_request", 3)
            adjust.update(
                command="rig_adjust_weight",
                arguments={
                    "selection": {
                        "vertices_by_submesh": {"0": [0]},
                        "edges_by_submesh": {},
                        "faces_by_submesh": {},
                        "source_indices": [],
                    },
                    "delta": 0.1,
                },
            )

            with self.assertRaisesRegex(RustMeshValidationError, "Free Edit OBJ"):
                session.run_command(adjust)

            self.assertFalse(
                configured["state"]["skeleton"]["weight_edit_capability"][
                    "enabled"
                ]
            )
            self.assertEqual(
                before,
                session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=False,
                ).submeshes[0].bone_weights,
            )
            self.assertEqual(
                before_revision,
                session.shadow_service.session_view(
                    session.shadow_session_id
                ).revision,
            )
            session.cancel()

    def test_candidate_changes_only_shadow_until_finish_then_commits_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            request = _request(session, "transaction_request", 1)
            request["candidate"] = _candidate_reference(session, request_id=1, first_x=0.75)
            request["label"] = "Move"

            state = session.apply_candidate(request)

            self.assertEqual(
                (0.0, 0.0, 0.0),
                authoritative.working_mesh("authoritative-rust-test", clone=False)
                .submeshes[0]
                .vertices[0],
            )
            self.assertEqual(
                (0.75, 0.0, 0.0),
                session.shadow_service.working_mesh(session.shadow_session_id, clone=False)
                .submeshes[0]
                .vertices[0],
            )
            self.assertGreaterEqual(state["base_revision"], 1)
            self.assertEqual(1, state["base_revision"])
            self.assertEqual(
                1,
                session.shadow_service.session_view(session.shadow_session_id).undo_count,
            )

            finish = session.finish(_request(session, "finish_request", 2))

            self.assertEqual("accepted", finish["status"])
            self.assertEqual(1, finish["authoritative_revision"])
            self.assertEqual(
                (0.75, 0.0, 0.0),
                authoritative.working_mesh("authoritative-rust-test", clone=False)
                .submeshes[0]
                .vertices[0],
            )
            view = authoritative.session_view("authoritative-rust-test")
            self.assertEqual(1, view.undo_count)
            self.assertEqual("Rust Edit Session", view.history_entries[-1].label)
            with self.assertRaises(KeyError):
                session.shadow_service.session_view(session.shadow_session_id)

    def test_candidate_vertex_edit_invalidates_tangents_and_reports_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _authoritative, session = self._create(Path(temporary) / "session")
            try:
                shadow = session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=False,
                )
                vertex_count = len(shadow.submeshes[0].vertices)
                shadow.submeshes[0].tangents = [(1.0, 0.0, 0.0)] * vertex_count
                shadow.submeshes[0].tangent_signs = [1.0] * vertex_count

                request = _request(session, "transaction_request", 1)
                request["candidate"] = _candidate_reference(
                    session,
                    request_id=1,
                    first_x=0.75,
                )
                request["label"] = "Move"

                state = session.apply_candidate(request)

                edited = session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=False,
                )
                self.assertEqual([], edited.submeshes[0].tangents)
                self.assertEqual([], getattr(edited.submeshes[0], "tangent_signs", []))
                feedback = state["operation_feedback"]
                self.assertEqual("ok", feedback["status"])
                self.assertEqual(1, len(feedback["diagnostics"]))
                self.assertIn("Invalidated tangents for 1 part", feedback["diagnostics"][0])
                self.assertIn("Generate Tangents", feedback["diagnostics"][0])
            finally:
                session.cancel()

    def test_missing_optional_channels_remain_absent_in_document_and_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(
                Path(temporary) / "session",
                strip_optional_channels=True,
            )
            manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
            document = read_owned_payload_reference(session.root, manifest["document"])
            encoded = document["lods"][0]["submeshes"][0]
            self.assertEqual([], encoded["normals"])
            self.assertEqual([], encoded["uvs"])
            request = _request(session, "transaction_request", 1)
            request["candidate"] = _candidate_reference(
                session,
                request_id=1,
                first_x=0.5,
            )

            with self.assertRaisesRegex(RustMeshValidationError, "UV count"):
                session.apply_candidate(request)

            shadow = session.shadow_service.working_mesh(
                session.shadow_session_id,
                clone=False,
            )
            self.assertEqual([], shadow.submeshes[0].normals)
            self.assertEqual([], shadow.submeshes[0].uvs)
            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            session.cancel()

    def test_active_lod_is_recorded_in_rust_transaction_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative = MeshService(settings=_Settings(root / "settings.ini"))
            mesh = _quad_mesh()
            mesh.format = "pamlod"
            lod0 = _quad_mesh().submeshes
            lod0[0].vertices[0] = (10.0, 0.0, 0.0)
            lod1 = _quad_mesh().submeshes
            mesh.lod_levels = [lod0, lod1]
            mesh.submeshes = mesh.lod_levels[1]
            mesh.active_lod_index = 1
            lod0_before = copy.deepcopy(mesh.lod_levels[0])
            with patch(
                "cdmw.services.mesh_service_native_clone._allow_python_service_clone_fallback",
                return_value=True,
            ), patch(
                "cdmw.services.mesh_service._allow_python_history_snapshot_fallback",
                return_value=True,
            ):
                view = authoritative.open_edit_session(
                    mesh,
                    session_id="authoritative-lod1-rust-test",
                    mode="edit",
                )
                session = RustMeshAuthoringSession.create(
                    SimpleNamespace(
                        mesh_service=authoritative,
                        active_session_id=view.session_id,
                    ),
                    root / "session",
                    process_generation=3,
                )
            with patch(
                "cdmw.services.mesh_service_native_clone._allow_python_service_clone_fallback",
                return_value=True,
            ), patch(
                "cdmw.services.mesh_service._allow_python_history_snapshot_fallback",
                return_value=True,
            ):
                configure = _request(session, "command_request", 1)
                configure.update(
                    command="configure_output_policy",
                    arguments={
                        "policy": "free_edit_rebuild",
                        "destination": str(root / "free-edit"),
                    },
                )
                session.run_command(configure)
                request = _request(session, "transaction_request", 2)
                request["candidate"] = _candidate_reference(
                    session,
                    request_id=2,
                    first_x=0.5,
                )

                session.apply_candidate(request)

                shadow = session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=False,
                )
                operations = tuple(getattr(shadow, "_cdmw_edit_operations", ()) or ())
                self.assertEqual(1, operations[-1]["lod_index"])
                result = session.finish(_request(session, "finish_request", 3))
                self.assertEqual("accepted", result["status"])
                authoritative_mesh = authoritative.working_mesh(
                    "authoritative-lod1-rust-test",
                    clone=False,
                )
                self.assertEqual(lod0_before, authoritative_mesh.lod_levels[0])
                self.assertEqual(
                    0.5,
                    authoritative_mesh.lod_levels[1][0].vertices[0][0],
                )
                self.assertIs(
                    authoritative_mesh.submeshes,
                    authoritative_mesh.lod_levels[1],
                )
                self.assertEqual(0.5, authoritative_mesh.submeshes[0].vertices[0][0])
                committed_operations = tuple(
                    getattr(authoritative_mesh, "_cdmw_edit_operations", ()) or ()
                )
                self.assertEqual(1, committed_operations[-1]["lod_index"])

    def test_geometry_layers_seed_from_memory_without_copying_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative = MeshService(settings=_Settings(root / "settings.ini"))
            with patch(
                "cdmw.services.mesh_service_native_clone._allow_python_service_clone_fallback",
                return_value=True,
            ), patch(
                "cdmw.services.mesh_service._allow_python_history_snapshot_fallback",
                return_value=True,
            ):
                view = authoritative.open_edit_session(
                    _quad_mesh(two_parts=True),
                    session_id="authoritative-layer-rust-test",
                    mode="edit",
                )
                authoritative_session = authoritative._session(view.session_id)
                authoritative_session.geometry_layers = (
                    _MeshGeometryLayer("base", "Base mesh", (0,), visible=True, base=True),
                    _MeshGeometryLayer("detail", "Detail", (1,), visible=True),
                )
                authoritative_session.active_geometry_layer_id = "detail"
                authoritative_session.geometry_layer_copy_counter = 7
                authoritative_session.geometry_layer_revision = 4
                authoritative_session.object_transform = MeshObjectTransformState(
                    location=(1.0, 2.0, 3.0),
                    rotation_degrees=(4.0, 5.0, 6.0),
                    scale=(1.25, 1.25, 1.25),
                    pivot=(0.5, 0.5, 0.0),
                )
                stale_project = root / "authoritative-only-mesh-layers.json"
                stale_project.write_text("{}", encoding="utf-8")
                setattr(
                    authoritative_session.working_mesh,
                    "_cdmw_mesh_layer_project_path",
                    str(stale_project),
                )
                session = RustMeshAuthoringSession.create(
                    SimpleNamespace(
                        mesh_service=authoritative,
                        active_session_id=view.session_id,
                    ),
                    root / "session",
                    process_generation=5,
                )

                shadow_session = session.shadow_service._session(session.shadow_session_id)
                self.assertEqual(
                    ("Base mesh", "Detail"),
                    tuple(layer.name for layer in shadow_session.geometry_layers),
                )
                self.assertEqual("detail", shadow_session.active_geometry_layer_id)
                self.assertEqual(7, shadow_session.geometry_layer_copy_counter)
                self.assertEqual(4, shadow_session.geometry_layer_revision)
                self.assertEqual(
                    (1.0, 2.0, 3.0),
                    shadow_session.object_transform.location,
                )
                self.assertIsNone(shadow_session.mesh_layer_project_path)
                self.assertIsNone(shadow_session.mesh_layer_workspace_manifest_path)
                self.assertFalse((session.root / "shadow-mesh-layers.json").exists())

                configure = _request(session, "command_request", 1)
                configure.update(
                    command="configure_output_policy",
                    arguments={
                        "policy": "free_edit_rebuild",
                        "destination": str(root / "free-edit"),
                    },
                )
                session.run_command(configure)
                rename = _request(session, "command_request", 2)
                rename.update(
                    command="layer_rename",
                    arguments={"layer_id": "detail", "name": "Rust Detail"},
                )
                session.run_command(rename)
                transaction = _request(session, "transaction_request", 3)
                transaction["candidate"] = _candidate_reference(
                    session,
                    request_id=3,
                    first_x=0.5,
                )
                session.apply_candidate(transaction)
                result = session.finish(_request(session, "finish_request", 4))

                self.assertEqual("accepted", result["status"])
                committed_session = authoritative._session(view.session_id)
                self.assertEqual(
                    ("Base mesh", "Rust Detail"),
                    tuple(layer.name for layer in committed_session.geometry_layers),
                )
                self.assertEqual(
                    (1.0, 2.0, 3.0),
                    committed_session.object_transform.location,
                )
                authoritative.undo(view.session_id)
                self.assertEqual(
                    ("Base mesh", "Detail"),
                    tuple(
                        layer.name
                        for layer in authoritative._session(view.session_id).geometry_layers
                    ),
                )
                authoritative.redo(view.session_id)
                self.assertEqual(
                    ("Base mesh", "Rust Detail"),
                    tuple(
                        layer.name
                        for layer in authoritative._session(view.session_id).geometry_layers
                    ),
                )

    def test_morph_refit_runtime_survives_finish_undo_and_redo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative = MeshService(settings=_Settings(root / "settings.ini"))
            mesh = _driver_garment_mesh()
            for submesh in mesh.submeshes:
                submesh.bone_indices = []
                submesh.bone_weights = []
            mesh.has_bones = False
            view = authoritative.open_edit_session(
                mesh,
                session_id="authoritative-rust-morph-test",
                mode="edit",
            )
            try:
                self.assertTrue(
                    authoritative.apply_command(view.session_id, _author_command()).ok
                )
                self.assertTrue(
                    authoritative.set_refit_driver(view.session_id, (0, 1))[0].ok
                )
                self.assertTrue(authoritative.bind_refit(view.session_id, (2,))[0].ok)
                self.assertTrue(
                    authoritative.configure_refit(
                        view.session_id,
                        (2,),
                        enabled=True,
                        intensity_percent=125.0,
                        mode="rigid",
                        clearance_percent=1.0,
                    )[0].ok
                )
                self.assertTrue(
                    authoritative.set_morph_value(
                        view.session_id,
                        "volume",
                        75.0,
                        phase="end",
                        change_id="authoritative-before-rust",
                    )[0].ok
                )
                before_mesh = authoritative.working_mesh(view.session_id, clone=True)

                session = RustMeshAuthoringSession.create(
                    SimpleNamespace(
                        mesh_service=authoritative,
                        active_session_id=view.session_id,
                    ),
                    root / "session",
                    process_generation=9,
                )
                shadow_state = session.shadow_service.morph_state(
                    session.shadow_session_id
                )
                self.assertEqual("resident-body", shadow_state.profile_id)
                self.assertEqual((("volume", 75.0)), shadow_state.values[0])
                self.assertEqual((0, 1), shadow_state.refit.driver_submesh_indices)
                self.assertEqual((2,), shadow_state.refit.garment_submesh_indices)

                configure = _request(session, "command_request", 1)
                configure.update(
                    command="configure_output_policy",
                    arguments={
                        "policy": "free_edit_rebuild",
                        "destination": str(root / "free-edit"),
                    },
                )
                session.run_command(configure)
                morph = _request(session, "command_request", 2)
                morph.update(
                    command="morph_set_value",
                    arguments={
                        "definition_id": "volume",
                        "value": 50.0,
                        "phase": "end",
                        "change_id": "rust-shadow-change",
                    },
                )
                session.run_command(morph)
                rust_mesh = session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=True,
                )

                result = session.finish(_request(session, "finish_request", 3))
                self.assertEqual("accepted", result["status"])
                committed_state = authoritative.morph_state(view.session_id)
                self.assertEqual((("volume", 50.0)), committed_state.values[0])
                self.assertEqual((0, 1), committed_state.refit.driver_submesh_indices)
                self.assertEqual((2,), committed_state.refit.garment_submesh_indices)
                self.assertEqual(
                    tuple(part.vertices for part in rust_mesh.submeshes),
                    tuple(
                        part.vertices
                        for part in authoritative.working_mesh(
                            view.session_id,
                            clone=True,
                        ).submeshes
                    ),
                )

                authoritative.undo(view.session_id)
                undone_state = authoritative.morph_state(view.session_id)
                self.assertEqual((("volume", 75.0)), undone_state.values[0])
                self.assertEqual(
                    tuple(part.vertices for part in before_mesh.submeshes),
                    tuple(
                        part.vertices
                        for part in authoritative.working_mesh(
                            view.session_id,
                            clone=True,
                        ).submeshes
                    ),
                )

                authoritative.redo(view.session_id)
                redone_state = authoritative.morph_state(view.session_id)
                self.assertEqual((("volume", 50.0)), redone_state.values[0])
                self.assertEqual(
                    tuple(part.vertices for part in rust_mesh.submeshes),
                    tuple(
                        part.vertices
                        for part in authoritative.working_mesh(
                            view.session_id,
                            clone=True,
                        ).submeshes
                    ),
                )
            finally:
                authoritative.close_edit_session(
                    view.session_id,
                    force_without_saving=True,
                )

    def test_finish_rejects_authoritative_geometry_layer_race(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            authoritative_session = authoritative._session("authoritative-rust-test")
            authoritative_session.geometry_layers = (
                _MeshGeometryLayer("base", "Base mesh", (0,), visible=True, base=True),
                _MeshGeometryLayer("detail", "Detail", (), visible=True),
            )
            authoritative_session.geometry_layer_revision = (
                session.base_geometry_layer_revision
            )
            shadow_session = session.shadow_service._session(session.shadow_session_id)
            shadow_session.geometry_layers = (
                _MeshGeometryLayer("base", "Base mesh", (0,), visible=True, base=True),
                _MeshGeometryLayer("detail", "Rust Detail", (), visible=True),
            )

            authoritative.rename_geometry_layer(
                "authoritative-rust-test",
                "detail",
                "Authoritative Detail",
            )

            with self.assertRaisesRegex(
                RustMeshValidationError,
                "geometry layers changed while Rust Edit Mesh",
            ):
                session.finish(_request(session, "finish_request", 1))

            current = authoritative._session("authoritative-rust-test")
            self.assertEqual(0, current.revision)
            self.assertEqual(0, len(current.undo_stack))
            self.assertEqual(
                ("Base mesh", "Authoritative Detail"),
                tuple(layer.name for layer in current.geometry_layers),
            )
            session.cancel()

    def test_finish_commit_lock_rejects_late_geometry_layer_race(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            authoritative_session = authoritative._session("authoritative-rust-test")
            authoritative_session.geometry_layers = (
                _MeshGeometryLayer("base", "Base mesh", (0,), visible=True, base=True),
                _MeshGeometryLayer("detail", "Detail", (), visible=True),
            )
            authoritative_session.geometry_layer_revision = (
                session.base_geometry_layer_revision
            )
            shadow_session = session.shadow_service._session(session.shadow_session_id)
            shadow_session.geometry_layers = (
                _MeshGeometryLayer("base", "Base mesh", (0,), visible=True, base=True),
                _MeshGeometryLayer("detail", "Rust Detail", (), visible=True),
            )
            original_prepare = authoritative.prepare_working_mesh_replacement

            def prepare_then_change_authoritative_layers(*args, **kwargs):
                prepared = original_prepare(*args, **kwargs)
                authoritative.rename_geometry_layer(
                    "authoritative-rust-test",
                    "detail",
                    "Authoritative Detail",
                )
                return prepared

            with patch.object(
                authoritative,
                "prepare_working_mesh_replacement",
                side_effect=prepare_then_change_authoritative_layers,
            ), self.assertRaisesRegex(RuntimeError, "geometry layers are stale"):
                session.finish(_request(session, "finish_request", 1))

            current = authoritative._session("authoritative-rust-test")
            self.assertEqual(0, current.revision)
            self.assertEqual(0, len(current.undo_stack))
            self.assertEqual(
                ("Base mesh", "Authoritative Detail"),
                tuple(layer.name for layer in current.geometry_layers),
            )
            self.assertFalse(session.closed)
            session.cancel()

    def test_finish_rejects_when_reversible_history_cannot_fit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            authoritative.max_history_bytes = 1

            with self.assertRaisesRegex(RuntimeError, "reversible history snapshot"):
                session.finish(_request(session, "finish_request", 1))

            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            self.assertFalse(session.closed)
            session.cancel()

    def test_cancel_discards_shadow_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            request = _request(session, "transaction_request", 1)
            request["candidate"] = _candidate_reference(session, request_id=1, first_x=0.5)
            session.apply_candidate(request)

            session.cancel()

            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            self.assertEqual(
                (0.0, 0.0, 0.0),
                authoritative.working_mesh("authoritative-rust-test", clone=False)
                .submeshes[0]
                .vertices[0],
            )

    def test_finish_rejects_authoritative_base_revision_race(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            newer = _quad_mesh()
            newer.submeshes[0].vertices[0] = (0.25, 0.0, 0.0)
            authoritative.replace_working_mesh("authoritative-rust-test", newer)

            with self.assertRaisesRegex(RustMeshValidationError, "changed while Rust Edit Mesh"):
                session.finish(_request(session, "finish_request", 1))

            self.assertEqual(
                (0.25, 0.0, 0.0),
                authoritative.working_mesh("authoritative-rust-test", clone=False)
                .submeshes[0]
                .vertices[0],
            )
            session.cancel()

    def test_finish_revalidates_free_edit_destination_is_still_new(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative, session = self._create(root / "session")
            destination = root / "free-edit-output"
            configure = _request(session, "command_request", 1)
            configure.update(
                command="configure_output_policy",
                arguments={
                    "policy": "free_edit_rebuild",
                    "destination": str(destination),
                },
            )
            session.run_command(configure)
            destination.mkdir()

            with self.assertRaisesRegex(
                RustMeshValidationError,
                "selected destination now exists",
            ):
                session.finish(_request(session, "finish_request", 2))

            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").undo_count)
            self.assertFalse(session.closed)
            session.cancel()

    def test_finish_revalidates_free_edit_destination_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative, session = self._create(root / "session")
            output_parent = root / "exports"
            output_parent.mkdir()
            destination = output_parent / "free-edit-output"
            configure = _request(session, "command_request", 1)
            configure.update(
                command="configure_output_policy",
                arguments={
                    "policy": "free_edit_rebuild",
                    "destination": str(destination),
                },
            )
            session.run_command(configure)
            output_parent.rmdir()

            with self.assertRaisesRegex(
                RustMeshValidationError,
                "parent folder no longer exists",
            ):
                session.finish(_request(session, "finish_request", 2))

            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").undo_count)
            self.assertFalse(session.closed)
            session.cancel()

    def test_finish_revalidates_free_edit_destination_does_not_match_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative, session = self._create(root / "session")
            destination = root / "free-edit-output"
            configure = _request(session, "command_request", 1)
            configure.update(
                command="configure_output_policy",
                arguments={
                    "policy": "free_edit_rebuild",
                    "destination": str(destination),
                },
            )
            session.run_command(configure)
            shadow_session = session.shadow_service._session(session.shadow_session_id)
            with shadow_session.export_lock:
                shadow_session.base_mesh.path = str(destination)

            with self.assertRaisesRegex(
                RustMeshValidationError,
                "must not overwrite the source asset",
            ):
                session.finish(_request(session, "finish_request", 2))

            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").undo_count)
            self.assertFalse(session.closed)
            session.cancel()

    def test_stale_revision_and_candidate_hash_are_rejected_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            stale = _request(session, "transaction_request", 1)
            stale["base_revision"] = 99
            stale["candidate"] = _candidate_reference(session, request_id=1, first_x=0.5)
            with self.assertRaisesRegex(RustMeshProtocolError, "request is stale"):
                session.apply_candidate(stale)

            bad_hash = _request(session, "transaction_request", 2)
            bad_hash["candidate"] = _candidate_reference(
                session,
                request_id=2,
                first_x=0.5,
                sha256="0" * 64,
            )
            with self.assertRaisesRegex(RustMeshProtocolError, "SHA-256"):
                session.apply_candidate(bad_hash)

            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            self.assertEqual(0, session.shadow_service.session_view(session.shadow_session_id).revision)
            session.cancel()

    def test_candidate_declared_type_and_count_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _authoritative, session = self._create(Path(temporary) / "session")
            wrong_type = _request(session, "transaction_request", 1)
            wrong_type["candidate"] = _candidate_reference(
                session,
                request_id=1,
                first_x=0.5,
            )
            wrong_type["candidate"]["data_type"] = "opaque_bytes"  # type: ignore[index]
            with self.assertRaisesRegex(RustMeshProtocolError, "data type"):
                session.apply_candidate(wrong_type)

            wrong_count = _request(session, "transaction_request", 2)
            wrong_count["candidate"] = _candidate_reference(
                session,
                request_id=2,
                first_x=0.5,
            )
            wrong_count["candidate"]["count"] = 99  # type: ignore[index]
            with self.assertRaisesRegex(RustMeshProtocolError, "element count"):
                session.apply_candidate(wrong_count)

            self.assertEqual(
                0,
                session.shadow_service.session_view(session.shadow_session_id).revision,
            )
            session.cancel()

    def test_payload_paths_and_candidate_names_cannot_escape_owned_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "owned.json"
            payload.write_text("{}", encoding="utf-8")
            reference = {
                "path": "../owned.json",
                "data_type": "json",
                "count": 1,
                "byte_length": payload.stat().st_size,
                "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                "content_type": "application/json",
            }
            with self.assertRaisesRegex(RustMeshProtocolError, "one owned JSON filename"):
                read_owned_payload_reference(root, reference)

            reference["path"] = "owned.json"
            with self.assertRaisesRegex(RustMeshProtocolError, "candidate filename"):
                read_owned_payload_reference(root, reference, candidate_only=True)

            with (
                patch(
                    "cdmw.services.mesh_rust_authoring.RUST_MESH_MAX_PAYLOAD_BYTES",
                    1,
                ),
                self.assertRaisesRegex(RustMeshProtocolError, "512 MiB session limit"),
            ):
                read_owned_payload_reference(root, reference)

    def test_unexpected_runtime_session_entries_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            (session.root / "unexpected.bin").write_bytes(b"not owned protocol data")
            request = _request(session, "transaction_request", 1)
            request["candidate"] = _candidate_reference(
                session,
                request_id=1,
                first_x=0.5,
            )

            with self.assertRaisesRegex(
                RustMeshProtocolError,
                "Unexpected Rust Mesh session entry",
            ):
                session.apply_candidate(request)

            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            (session.root / "unexpected.bin").unlink()
            session.cancel()

    def test_runtime_payloads_are_consumed_pruned_and_aggregate_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            request = _request(session, "transaction_request", 1)
            candidate_reference = _candidate_reference(
                session,
                request_id=1,
                first_x=0.5,
            )
            request["candidate"] = candidate_reference
            candidate_path = session.root / str(candidate_reference["path"])

            session.apply_candidate(request)

            self.assertFalse(candidate_path.exists())
            first_state = session.state_payload(include_document=True)
            first_path = session.root / str(first_state["document"]["path"])
            self.assertTrue(first_path.is_file())
            second_state = session.state_payload(include_document=True)
            second_path = session.root / str(second_state["document"]["path"])
            self.assertFalse(first_path.exists())
            self.assertTrue(second_path.is_file())
            aggregate_bytes = sum(
                item.stat().st_size
                for item in session.root.rglob("*")
                if item.is_file()
            )
            with patch(
                "cdmw.services.mesh_rust_authoring._SESSION_MAX_TOTAL_BYTES",
                aggregate_bytes - 1,
            ), self.assertRaisesRegex(RustMeshProtocolError, "aggregate limit"):
                rust_authoring_module._validate_owned_session_tree(session.root)

            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            session.cancel()

    def test_locked_obsolete_state_does_not_fail_completed_mesh_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _authoritative, session = self._create(root / "session")
            configure = _request(session, "command_request", 1)
            configure.update(
                command="configure_output_policy",
                arguments={
                    "policy": "free_edit_rebuild",
                    "destination": str(root / "free-edit"),
                },
            )
            session.run_command(configure)
            recovery_state = session.state_payload(include_document=True)
            recovery_path = session.root / str(recovery_state["document"]["path"])
            request = _request(session, "command_request", 2)
            request.update(
                command="topology",
                arguments={
                    "action": "subdivide",
                    "selection": {
                        "vertices_by_submesh": {},
                        "edges_by_submesh": {},
                        "faces_by_submesh": {"0": [0]},
                        "source_indices": [],
                    },
                },
            )
            original_unlink = Path.unlink

            def unlink_with_locked_recovery(path: Path, *args: object, **kwargs: object) -> None:
                if path == recovery_path:
                    raise PermissionError("state document is locked")
                original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", unlink_with_locked_recovery):
                response = session.run_command(request)

            self.assertEqual(
                2,
                session.shadow_service.session_view(session.shadow_session_id).revision,
            )
            self.assertEqual(2, response["state"]["base_revision"])
            published_reference = response["state"]["document"]
            published_path = session.root / str(published_reference["path"])
            self.assertTrue(recovery_path.is_file())
            self.assertTrue(published_path.is_file())
            read_owned_payload_reference(session.root, published_reference)

            aggregate_bytes = sum(
                item.stat().st_size
                for item in session.root.rglob("*")
                if item.is_file()
            )
            with (
                patch(
                    "cdmw.services.mesh_rust_authoring._SESSION_MAX_TOTAL_BYTES",
                    aggregate_bytes,
                ),
                self.assertRaisesRegex(RustMeshProtocolError, "aggregate limit"),
            ):
                session.state_payload(include_document=True)

            self.assertEqual(
                {recovery_path, published_path},
                {
                    item
                    for item in session.root.iterdir()
                    if rust_authoring_module._STATE_FILE_RE.fullmatch(item.name) is not None
                },
            )
            session.cancel()

    def test_oversized_mutating_command_is_rejected_before_shadow_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative, session = self._create(root / "session")
            configure = _request(session, "command_request", 1)
            configure.update(
                command="configure_output_policy",
                arguments={
                    "policy": "free_edit_rebuild",
                    "destination": str(root / "free-edit"),
                },
            )
            session.run_command(configure)
            recovery_state = session.state_payload(include_document=True)
            recovery_path = session.root / str(recovery_state["document"]["path"])
            before_view = session.shadow_service.session_view(session.shadow_session_id)
            before_mesh = session.shadow_service.working_mesh(
                session.shadow_session_id,
                clone=True,
            )
            request = _request(session, "command_request", 2)
            request.update(
                command="topology",
                arguments={
                    "action": "subdivide",
                    "selection": {
                        "vertices_by_submesh": {},
                        "edges_by_submesh": {},
                        "faces_by_submesh": {"0": [0]},
                        "source_indices": [],
                    },
                },
            )

            with patch(
                "cdmw.services.mesh_rust_authoring.RUST_MESH_MAX_PAYLOAD_BYTES",
                max(1, session.max_state_document_bytes - 1),
            ), self.assertRaisesRegex(RustMeshProtocolError, "state payload limit"):
                session.run_command(request)

            after_view = session.shadow_service.session_view(session.shadow_session_id)
            after_mesh = session.shadow_service.working_mesh(
                session.shadow_session_id,
                clone=True,
            )
            self.assertEqual(before_view.revision, after_view.revision)
            self.assertEqual(before_view.undo_count, after_view.undo_count)
            self.assertEqual(before_view.redo_count, after_view.redo_count)
            self.assertEqual(before_mesh.submeshes, after_mesh.submeshes)
            self.assertTrue(recovery_path.is_file())
            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)

            state_request = _request(session, "command_request", 3)
            state_request.update(command="state", arguments={})
            recovered = session.run_command(state_request)
            self.assertIn("document", recovered["state"])
            finished = session.finish(_request(session, "finish_request", 4))
            self.assertEqual("accepted", finished["status"])

    def test_same_size_mesh_action_executes_the_kernel_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _authoritative, session = self._create(Path(temporary) / "session")
            request = _request(session, "command_request", 1)
            request.update(
                command="mesh_action",
                arguments={
                    "action": "recalculate_normals",
                    "selection": {
                        "vertices_by_submesh": {},
                        "edges_by_submesh": {},
                        "faces_by_submesh": {},
                        "source_indices": [0],
                    },
                    "params": {},
                    "label": "Recalculate normals",
                },
            )
            original_apply = MeshService.apply_command
            calls: list[tuple[str, str]] = []

            def counted_apply(
                service: MeshService,
                session_id: str,
                command: object,
            ) -> object:
                calls.append((session_id, str(getattr(command, "action", ""))))
                return original_apply(service, session_id, command)  # type: ignore[arg-type]

            try:
                with patch.object(MeshService, "apply_command", new=counted_apply):
                    response = session.run_command(request)
                self.assertEqual(1, response["state"]["base_revision"])
                self.assertEqual(
                    [(session.shadow_session_id, "recalculate_normals")],
                    calls,
                )
            finally:
                session.cancel()

    def test_exact_generate_tangents_rejects_a_preflight_vertex_split(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _authoritative, session = self._create(Path(temporary) / "session")
            before_view = session.shadow_service.session_view(session.shadow_session_id)
            before_mesh = session.shadow_service.working_mesh(
                session.shadow_session_id,
                clone=True,
            )
            request = _request(session, "command_request", 1)
            request.update(
                command="mesh_action",
                arguments={
                    "action": "generate_tangents",
                    "selection": {
                        "vertices_by_submesh": {},
                        "edges_by_submesh": {},
                        "faces_by_submesh": {},
                        "source_indices": [0],
                    },
                    "params": {},
                    "label": "Generate tangents",
                },
            )
            original_apply = MeshService.apply_command
            actual_shadow_calls = 0

            def split_preflight(
                service: MeshService,
                session_id: str,
                command: object,
            ) -> object:
                nonlocal actual_shadow_calls
                if ":topology-preflight:" in session_id:
                    candidate = service.working_mesh(session_id, clone=False)
                    candidate.submeshes[0].vertices.append((0.0, 0.0, 0.0))
                    return SimpleNamespace(ok=True)
                actual_shadow_calls += 1
                return original_apply(service, session_id, command)  # type: ignore[arg-type]

            try:
                with (
                    patch.object(MeshService, "apply_command", new=split_preflight),
                    self.assertRaisesRegex(
                        RustMeshValidationError,
                        "Generate Tangents.*Free Edit",
                    ),
                ):
                    session.run_command(request)
                after_view = session.shadow_service.session_view(session.shadow_session_id)
                after_mesh = session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=True,
                )
                self.assertEqual(0, actual_shadow_calls)
                self.assertEqual(before_view.revision, after_view.revision)
                self.assertEqual(before_view.undo_count, after_view.undo_count)
                self.assertEqual(before_mesh.submeshes, after_mesh.submeshes)
            finally:
                session.cancel()

    def test_morph_delete_definition_routes_to_the_shadow_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _authoritative, session = self._create(Path(temporary) / "session")
            try:
                created = session.shadow_service.apply_command(
                    session.shadow_session_id,
                    _author_command(),
                )
                self.assertTrue(created.ok)
                self.assertEqual(
                    ("volume",),
                    tuple(
                        row.definition_id
                        for row in session.shadow_service.morph_state(
                            session.shadow_session_id
                        ).definitions
                    ),
                )
                request = _request(session, "command_request", 1)
                request.update(
                    command="morph_delete_definition",
                    arguments={"definition_id": "volume"},
                )

                response = session.run_command(request)

                self.assertEqual([], response["state"]["morph_refit"]["definitions"])
                self.assertEqual(
                    (),
                    session.shadow_service.morph_state(
                        session.shadow_session_id
                    ).definitions,
                )
            finally:
                session.cancel()

    def test_unexpected_morph_profile_entries_cannot_be_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            profile_root = session.root / "mesh_slider_profiles"
            profile_root.mkdir()
            (profile_root / "payload.bin").write_bytes(b"not a profile")

            with self.assertRaisesRegex(
                RustMeshProtocolError,
                "morph profiles contain an unexpected entry",
            ):
                session.finish(_request(session, "finish_request", 1))

            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            session.cancel()

    def test_executable_resolution_is_explicit_and_never_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "cdmw_mesh_lab.exe"
            executable.write_bytes(b"rust")
            with patch(
                "cdmw.services.mesh_rust_contract.rust_mesh_editor_candidate_paths",
                return_value=(("configured", executable),),
            ):
                resolution = resolve_rust_mesh_editor(executable)
            self.assertTrue(resolution.is_file)
            self.assertEqual("configured", resolution.source)

            missing = Path(temporary) / "missing.exe"
            with patch(
                "cdmw.services.mesh_rust_contract.rust_mesh_editor_candidate_paths",
                return_value=(("configured", missing),),
            ):
                resolution = resolve_rust_mesh_editor(missing)
            self.assertFalse(resolution.is_file)
            self.assertEqual("missing", resolution.source)

    def test_every_integrated_executable_source_requires_matching_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "cdmw_mesh_lab.exe"
            executable.write_bytes(b"pinned-rust-helper")
            sources = (
                "configured",
                "environment",
                "source_release",
                "source_debug",
                "native_release",
                "frozen",
                "frozen_internal",
                "executable",
                "executable_internal",
            )
            resolutions = tuple(
                RustMeshExecutableResolution(
                    resolved_path=str(executable),
                    source=source,
                    exists=True,
                    is_file=True,
                )
                for source in sources
            )
            for resolution in resolutions:
                with self.subTest(source=resolution.source):
                    self.assertIn(
                        "manifest is missing",
                        validate_rust_mesh_editor_package(resolution),
                    )
            manifest = {
                "schema": RUST_MESH_PROVENANCE_SCHEMA,
                "renderer": RUST_MESH_RENDERER,
                "edit_backend": RUST_MESH_EDIT_BACKEND,
                "protocol": RUST_MESH_EDITOR_PROTOCOL,
                "authoring_package": RUST_MESH_AUTHORING_PACKAGE,
                "preview_protocol": RUST_PREVIEW_PROTOCOL,
                "preview_package": RUST_PREVIEW_PACKAGE,
                "preview_backend": RUST_PREVIEW_BACKEND,
                "control_contract": RUST_MESH_CONTROL_CONTRACT_FILE,
                "control_contract_schema": RUST_MESH_CONTROL_CONTRACT_SCHEMA,
                "capabilities": list(RUST_MESH_REQUIRED_CAPABILITIES),
                "preview_capabilities": list(RUST_PREVIEW_REQUIRED_CAPABILITIES),
                "locked_dependencies": True,
                "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }
            control_contract = {
                "schema": RUST_MESH_CONTROL_CONTRACT_SCHEMA,
                "ok": True,
                "rows": [],
            }
            control_contract_bytes = json.dumps(control_contract).encode("utf-8")
            executable.with_name(RUST_MESH_CONTROL_CONTRACT_FILE).write_bytes(
                control_contract_bytes
            )
            manifest["control_contract_sha256"] = hashlib.sha256(
                control_contract_bytes
            ).hexdigest()
            executable.with_name(RUST_MESH_PROVENANCE_FILE).write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            for resolution in resolutions:
                with self.subTest(source=resolution.source):
                    self.assertEqual("", validate_rust_mesh_editor_package(resolution))
            executable.write_bytes(b"tampered")
            self.assertIn(
                "hash does not match",
                validate_rust_mesh_editor_package(resolutions[0]),
            )

    def test_executable_cache_signature_covers_the_provenance_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "cdmw_mesh_lab.exe"
            executable.write_bytes(b"pinned-rust-helper")
            resolution = RustMeshExecutableResolution(
                resolved_path=str(executable),
                source="configured",
                exists=True,
                is_file=True,
            )

            without_manifest = rust_mesh_editor_file_signature(resolution)
            manifest_path = executable.with_name(RUST_MESH_PROVENANCE_FILE)
            manifest_path.write_text("{}", encoding="utf-8")
            with_manifest = rust_mesh_editor_file_signature(resolution)
            manifest_path.write_text('{"changed":true}', encoding="utf-8")
            changed_manifest = rust_mesh_editor_file_signature(resolution)

            self.assertNotEqual(without_manifest, with_manifest)
            self.assertNotEqual(with_manifest, changed_manifest)

    def test_cancel_linearizes_before_finish_commit_and_keeps_authoritative_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            entered = threading.Event()
            release = threading.Event()
            original_prepare = authoritative.prepare_working_mesh_replacement
            outcome: list[object] = []

            def slow_prepare(
                session_id: str,
                mesh: object,
                **kwargs: object,
            ) -> object:
                prepared = original_prepare(  # type: ignore[arg-type]
                    session_id,
                    mesh,
                    **kwargs,
                )
                entered.set()
                release.wait(timeout=5)
                return prepared

            def run_finish() -> None:
                try:
                    outcome.append(session.finish(_request(session, "finish_request", 1)))
                except Exception as exc:  # asserted below
                    outcome.append(exc)

            with patch.object(authoritative, "prepare_working_mesh_replacement", slow_prepare):
                thread = threading.Thread(target=run_finish)
                thread.start()
                self.assertTrue(entered.wait(timeout=5))
                self.assertTrue(session.request_cancel())
                release.set()
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertEqual(1, len(outcome))
            self.assertIsInstance(outcome[0], RustMeshCancellationError)
            self.assertEqual(0, authoritative.session_view("authoritative-rust-test").revision)
            session.cancel()

    def test_cancel_reports_commit_owned_once_atomic_publication_has_started(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            entered = threading.Event()
            release = threading.Event()
            original_commit = authoritative.commit_prepared_working_mesh_replacement
            outcome: list[object] = []

            def slow_commit(prepared: object, **kwargs: object) -> object:
                entered.set()
                release.wait(timeout=5)
                return original_commit(prepared, **kwargs)  # type: ignore[arg-type]

            def run_finish() -> None:
                try:
                    outcome.append(session.finish(_request(session, "finish_request", 1)))
                except Exception as exc:  # pragma: no cover - asserted as failure below
                    outcome.append(exc)

            with patch.object(authoritative, "commit_prepared_working_mesh_replacement", slow_commit):
                thread = threading.Thread(target=run_finish)
                thread.start()
                self.assertTrue(entered.wait(timeout=5))
                self.assertFalse(session.request_cancel())
                release.set()
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertIsInstance(outcome[0], dict)
            self.assertEqual("accepted", outcome[0]["status"])
            self.assertEqual(1, authoritative.session_view("authoritative-rust-test").revision)

    def test_read_only_lod_rejects_geometry_and_finish_until_free_edit_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative = MeshService(settings=_Settings(root / "settings.ini"))
            mesh = _quad_mesh()
            mesh.active_lod_index = 1
            view = authoritative.open_edit_session(
                mesh,
                session_id="authoritative-read-only-rust-test",
                mode="edit",
            )
            controller = SimpleNamespace(
                mesh_service=authoritative,
                active_session_id=view.session_id,
            )
            session = RustMeshAuthoringSession.create(
                controller,
                root / "session",
                process_generation=2,
            )
            request = _request(session, "transaction_request", 1)
            request["candidate"] = _candidate_reference(
                session,
                request_id=1,
                first_x=0.5,
            )
            with self.assertRaises(RustMeshValidationError):
                session.apply_candidate(request)
            with self.assertRaises(RustMeshValidationError):
                session.finish(_request(session, "finish_request", 2))
            self.assertEqual(0, authoritative.session_view(view.session_id).revision)

            destination = root / "new-free-edit-package"
            command = _request(session, "command_request", 3)
            command.update(
                command="configure_output_policy",
                arguments={
                    "policy": "free_edit_rebuild",
                    "destination": str(destination),
                },
            )
            session.run_command(command)
            self.assertTrue(
                session.shadow_service.session_view(
                    session.shadow_session_id
                ).authoring_enabled
            )
            session.cancel()

    def test_import_editable_package_replaces_only_the_shadow_mesh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            package = Path(temporary) / "editable-package"
            package.mkdir()
            (package / "mesh.obj").write_text(
                "\n".join(
                    (
                        "v 2.0 0.0 0.0",
                        "v 3.0 0.0 0.0",
                        "v 2.0 1.0 0.0",
                        "f 1 2 3",
                    )
                ),
                encoding="utf-8",
            )
            (package / "mesh.cdmeta.json").write_text("{}", encoding="utf-8")
            adjacent_alias = package / "mesh.obj.meta.json"
            self.assertFalse(adjacent_alias.exists())
            command = _request(session, "command_request", 1)
            command.update(
                command="import_editable_package",
                arguments={"path": str(package)},
            )

            result = session.run_command(command)

            self.assertEqual(
                (2.0, 0.0, 0.0),
                session.shadow_service.working_mesh(
                    session.shadow_session_id,
                    clone=False,
                ).submeshes[0].vertices[0],
            )
            self.assertEqual(
                (0.0, 0.0, 0.0),
                authoritative.working_mesh(
                    "authoritative-rust-test",
                    clone=False,
                ).submeshes[0].vertices[0],
            )
            self.assertGreater(result["state"]["base_revision"], 0)
            self.assertFalse(adjacent_alias.exists())
            session.cancel()

    def test_finish_morph_profile_publication_is_reversible_with_session_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_profile = root / "mesh_slider_profiles" / "definitions" / "original.json"
            original_profile.parent.mkdir(parents=True)
            original_profile.write_text('{"name":"Original"}', encoding="utf-8")
            authoritative, session = self._create(root / "session")
            authoritative_profiles = root / "mesh_slider_profiles"
            shadow_profile = session.root / "mesh_slider_profiles" / "definitions" / "rust.json"
            (session.root / "mesh_slider_profiles" / "definitions" / "original.json").unlink()
            shadow_profile.write_text('{"name":"Rust"}', encoding="utf-8")
            _acknowledge_test_profile_tree(session)

            result = session.finish(_request(session, "finish_request", 1))

            self.assertEqual("accepted", result["status"])
            self.assertEqual(
                '{"name":"Rust"}',
                (authoritative_profiles / "definitions" / "rust.json").read_text(
                    encoding="utf-8"
                ),
            )
            authoritative.undo("authoritative-rust-test")
            self.assertEqual(
                '{"name":"Original"}',
                original_profile.read_text(encoding="utf-8"),
            )
            self.assertFalse((authoritative_profiles / "definitions" / "rust.json").exists())
            authoritative.redo("authoritative-rust-test")
            self.assertFalse(original_profile.exists())
            self.assertEqual(
                '{"name":"Rust"}',
                (authoritative_profiles / "definitions" / "rust.json").read_text(
                    encoding="utf-8"
                ),
            )

    def test_protocol_requests_are_serialized_before_shadow_revision_cas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "session"
            authoritative, session = self._create(root)
            entered_first_mutation = threading.Event()
            release_first_mutation = threading.Event()
            second_started = threading.Event()
            first_errors: list[BaseException] = []
            second_errors: list[BaseException] = []
            real_apply = session.shadow_service.apply_command

            def blocking_apply(session_id, command):
                entered_first_mutation.set()
                if not release_first_mutation.wait(timeout=5.0):
                    raise RuntimeError("timed out waiting to release the first request")
                return real_apply(session_id, command)

            first = _request(session, "command_request", 1)
            first.update(
                command="select",
                arguments={
                    "operation": "replace",
                    "selection": {
                        "vertices_by_submesh": {"0": [0]},
                        "edges_by_submesh": {},
                        "faces_by_submesh": {},
                        "source_indices": [],
                    },
                },
            )
            second = _request(session, "command_request", 2)
            second.update(command="state", arguments={})

            def run_first() -> None:
                try:
                    session.run_command(first)
                except BaseException as exc:  # pragma: no cover - asserted below
                    first_errors.append(exc)

            def run_second() -> None:
                second_started.set()
                try:
                    session.run_command(second)
                except BaseException as exc:  # pragma: no cover - asserted below
                    second_errors.append(exc)

            first_thread = threading.Thread(target=run_first)
            second_thread = threading.Thread(target=run_second)
            try:
                with patch.object(
                    session.shadow_service,
                    "apply_command",
                    side_effect=blocking_apply,
                ):
                    first_thread.start()
                    self.assertTrue(entered_first_mutation.wait(timeout=5.0))
                    second_thread.start()
                    self.assertTrue(second_started.wait(timeout=5.0))
                    self.assertTrue(second_thread.is_alive())
                    release_first_mutation.set()
                    first_thread.join(timeout=10.0)
                    second_thread.join(timeout=10.0)

                self.assertFalse(first_thread.is_alive())
                self.assertFalse(second_thread.is_alive())
                self.assertEqual([], first_errors)
                self.assertEqual(1, len(second_errors))
                self.assertIsInstance(second_errors[0], RustMeshProtocolError)
                self.assertIn("request is stale", str(second_errors[0]))
            finally:
                release_first_mutation.set()
                first_thread.join(timeout=5.0)
                second_thread.join(timeout=5.0)
                if not session.closed:
                    session.cancel()
                authoritative.close_edit_session(
                    "authoritative-rust-test",
                    force_without_saving=True,
                )

    def test_morph_profile_history_refuses_to_overwrite_external_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative, session = self._create(root / "session")
            authoritative_profile = root / "mesh_slider_profiles" / "definitions" / "rust.json"
            shadow_profile = session.root / "mesh_slider_profiles" / "definitions" / "rust.json"
            shadow_profile.parent.mkdir(parents=True)
            shadow_profile.write_text('{"name":"Rust"}', encoding="utf-8")
            _acknowledge_test_profile_tree(session)
            session.finish(_request(session, "finish_request", 1))
            authoritative_profile.write_text('{"name":"External"}', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "changed outside Mesh Editor"):
                authoritative.undo("authoritative-rust-test")

            self.assertEqual(
                '{"name":"External"}',
                authoritative_profile.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                1,
                authoritative.session_view("authoritative-rust-test").undo_count,
            )


if __name__ == "__main__":
    unittest.main()
