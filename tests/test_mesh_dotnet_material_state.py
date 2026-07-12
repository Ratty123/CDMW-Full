from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cdmw.modding.mesh_parser import SubMesh
from cdmw.services import mesh_dotnet_experiment
from cdmw.services.mesh_dotnet_experiment import (
    build_mesh_dotnet_experiment_package,
    mesh_dotnet_material_input_signature,
    mesh_dotnet_material_state_payload,
)
from tests.test_mesh_dotnet_experiment import _mesh


def test_dotnet_material_signature_changes_only_with_material_inputs(tmp_path: Path) -> None:
    mesh = _mesh()
    texture = tmp_path / "skin.png"
    texture.write_bytes(b"first")
    mesh.submeshes[0].preview_texture_path = str(texture)

    first = mesh_dotnet_material_input_signature(mesh)
    mesh.submeshes[0].vertices[0] = (9.0, 8.0, 7.0)
    assert mesh_dotnet_material_input_signature(mesh) == first

    texture.write_bytes(b"changed-content")
    assert mesh_dotnet_material_input_signature(mesh) != first


def test_dotnet_material_state_payload_is_deterministic_and_does_not_build_package(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base = tmp_path / "skin.dds"
    normal = tmp_path / "skin_n.dds"
    base.write_bytes(b"base")
    normal.write_bytes(b"normal")
    mesh = _mesh()
    body = mesh.submeshes[0]
    body.submesh_index = 3
    body.material_slot_index = 7
    body.preview_texture_path = str(base)
    body.preview_normal_texture_path = str(normal)
    eyes = SubMesh(name="eyes", material="eye", texture=r"missing\eyes.dds")
    eyes.submesh_index = 8
    eyes.material_slot_index = 4
    mesh.submeshes.append(eyes)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("material snapshot must not build or copy a package")

    monkeypatch.setattr(mesh_dotnet_experiment, "export_obj", forbidden)
    monkeypatch.setattr(mesh_dotnet_experiment, "_copy_dotnet_texture_channel_resources", forbidden)
    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="session-1",
        edit_revision=9,
        generation=12,
        affected_submeshes=[8, 8, 99],
    )

    assert payload["schema"] == "cdmw_mesh_material_state_v2"
    assert payload["version"] == 2
    assert payload["event"] == "material_state_update"
    assert payload["session_id"] == "session-1"
    assert payload["edit_revision"] == 9
    assert payload["generation"] == 12
    assert payload["material_signature"] == mesh_dotnet_material_input_signature(mesh)
    assert payload["affected_submeshes"] == [8]
    assert [item["submesh_index"] for item in payload["submeshes"]] == [3, 8]
    assert payload["submeshes"][0]["material_slot_index"] == 7
    assert payload["submeshes"][0]["material"] == "skin"

    resources = {item["path"]: item for item in payload["resources"]}
    base_stat = base.stat()
    base_identity = f"{base.resolve().as_posix().casefold()}|size:{base_stat.st_size}|mtime_ns:{base_stat.st_mtime_ns}"
    expected_base_fingerprint = hashlib.sha256(base_identity.encode("utf-8")).hexdigest()
    assert resources[base.resolve().as_posix()]["fingerprint"] == expected_base_fingerprint
    assert resources["missing/eyes.dds"]["fingerprint"] == hashlib.sha256(
        b"raw:missing/eyes.dds"
    ).hexdigest()
    body_channels = payload["submeshes"][0]["channels"]
    assert body_channels["base"] == body_channels["albedo"] == body_channels["diffuse"]
    assert body_channels["base"] == f"texture:{expected_base_fingerprint}"
    assert len(payload["resources"]) == 3
    assert payload["resources"] == sorted(payload["resources"], key=lambda item: item["resource_id"])

    repeat = mesh_dotnet_material_state_payload(
        mesh,
        session_id="session-1",
        edit_revision=9,
        generation=12,
    )
    assert repeat["affected_submeshes"] == [3, 8]
    assert repeat | {"affected_submeshes": [8]} == payload


def test_initial_manifest_and_resident_update_share_resource_fingerprint(tmp_path: Path) -> None:
    texture = tmp_path / "skin.dds"
    texture.write_bytes(b"same-resource")
    mesh = _mesh()
    mesh.submeshes[0].preview_texture_path = str(texture)

    package = build_mesh_dotnet_experiment_package(mesh, output_root=tmp_path / "packages")
    manifest = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    resident = mesh_dotnet_material_state_payload(mesh, session_id="s", edit_revision=1, generation=1)

    initial_resource = manifest["resources"][0]
    resident_resource = resident["resources"][0]
    assert initial_resource["resource_id"] == resident_resource["resource_id"]
    assert initial_resource["fingerprint"] == resident_resource["fingerprint"]
    assert (package.package_dir / initial_resource["path"]).is_file()
    assert manifest["submeshes"][0]["resource_channels"]["base"] == initial_resource["resource_id"]


def test_gltf_packed_channels_and_source_factors_survive_resident_snapshot(tmp_path: Path) -> None:
    base = tmp_path / "blade_base.png"
    material = tmp_path / "blade_metallicRoughness.png"
    base.write_bytes(b"base")
    material.write_bytes(b"packed")
    mesh = _mesh()
    blade = mesh.submeshes[0]
    blade.preview_texture_path = str(base)
    blade.preview_material_texture_path = str(material)
    blade.preview_material_texture_subtype = "metallic_roughness"
    blade.preview_material_texture_packed_channels = ("roughness", "metallic")
    blade.preview_color = (0.75, 0.5, 0.25)
    blade.preview_native_material_overrides = {
        "roughness": 0.8,
        "metalness": 0.6,
        "emissive_color": "#ff4000",
        "emissive_intensity": 2.0,
    }

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="gltf",
        edit_revision=1,
        generation=1,
    )
    binding = payload["submeshes"][0]

    assert binding["channels"]["roughness"] == binding["channels"]["metallic"]
    assert "specular" not in binding["channels"]
    assert binding["channel_components"] == {"roughness": "g", "metallic": "b"}
    assert binding["parameters"] == {
        "tint_color": [0.75, 0.5, 0.25],
        "roughness_scale": 0.8,
        "metalness_scale": 0.6,
        "emissive_color": [1.0, 64 / 255.0, 0.0],
        "emissive_intensity": 2.0,
    }

    signature = mesh_dotnet_material_input_signature(mesh)
    blade.preview_color = (0.5, 0.5, 0.5)
    assert mesh_dotnet_material_input_signature(mesh) != signature


def test_color_only_gltf_material_preserves_surface_and_emissive_factors(tmp_path: Path) -> None:
    mesh = _mesh()
    gem = mesh.submeshes[0]
    gem.texture = ""
    gem.preview_color = (0.0, 1.0, 0.7911)
    gem.preview_native_material_overrides = {
        "roughness": 0.920748,
        "emissive_color": "#ff0000",
        "emissive_intensity": 10.0,
    }

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="gem",
        edit_revision=1,
        generation=1,
    )

    assert payload["submeshes"][0]["parameters"] == {
        "tint_color": [0.0, 1.0, 0.7911],
        "roughness": 0.920748,
        "emissive_color": [1.0, 0.0, 0.0],
        "emissive_intensity": 10.0,
    }
