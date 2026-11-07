"""Archive GLB exports through real PAC/PAB parsing and the shared writer."""
import io
import json
import struct
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from cdmw.core.archive_mesh_export import export_archive_mesh
from cdmw.core.archive_mesh_import_preview import build_mesh_import_preview
from cdmw.models import ArchiveModelTextureReference
from cdmw.modding.mesh_glb_interchange import import_glb_with_sidecar
from cdmw.modding.mesh_pac_builder import _pack_pac_normal
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.archive_mesh_batch_export import BatchMeshExportRequest, export_batch_mesh_item
from tests.test_archive_mesh_export_fidelity import _entry
from tests.test_mesh_interchange_authoring import glb_document
from tests.test_pab_skeleton_writer import IDENTITY, pab
from tests.test_pac_cloth_guide_builder import PALETTE, guide_free_pac


def rigged_archive(root):
    raw = bytearray(guide_free_pac())
    parsed = parse_pac(bytes(raw), "body.pac")
    for level in parsed.lod_levels:
        for part in level:
            for offset in part.source_vertex_offsets:
                old = struct.unpack_from("<I", raw, offset + 16)[0]
                struct.pack_into("<I", raw, offset + 16, _pack_pac_normal((0, 0, 1), old))
    raw = bytes(raw)
    model = _entry(root, "character/model/owned/body.pac", raw)
    bones = [(f"Bone{i}", -1 if i == 0 else 0, IDENTITY, IDENTITY, IDENTITY, IDENTITY,
              (0., 0., 0., 1.), (0., 0., 0.)) for i in range(8)]
    skeleton = _entry(root, "character/model/owned/body.pab", pab(0, bones=bones, hashes=PALETTE))
    image = io.BytesIO()
    Image.new("RGBA", (4, 4), (200, 120, 60, 255)).save(image, format="DDS")
    texture = _entry(root, "character/model/owned/guide0.dds", image.getvalue())
    entries = (model, skeleton, texture)
    options = {
        "archive_entries_by_normalized_path": {entry.path: (entry,) for entry in entries},
        "archive_entries_by_basename": {entry.basename: (entry,) for entry in entries},
    }
    return model, skeleton, texture, raw, options


def test_archive_glb_preserves_rig_texture_companions_and_no_edit_bytes(tmp_path):
    model, skeleton, texture, raw, options = rigged_archive(tmp_path)
    reference = ArchiveModelTextureReference(
        reference_name="guide0.dds", material_name="guide0", part_name="guide0",
        resolved_archive_path=texture.path, resolved_entry=texture,
        resolution_status="resolved", semantic_label="Base color",
    )
    result = export_archive_mesh(model, tmp_path / "out", "glb", **options,
                                 related_entries=(texture,), model_texture_references=(reference,),
                                 build_preview_context=False)
    assert not result.requires_confirmation
    path = tmp_path / "out/body.glb"
    document = glb_document(path)
    assert len(document["skins"][0]["joints"]) == 8
    attributes = document["meshes"][0]["primitives"][0]["attributes"]
    assert {"JOINTS_0", "WEIGHTS_0", "_CDMW_VERTEX_ID", "TEXCOORD_0"} <= attributes.keys()
    assert document["images"] and document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]
    manifest = json.loads(Path(str(path) + ".meta.json").read_text())
    assert manifest["source_archive_path"] == model.path
    assert manifest["skeleton_identity"] == skeleton.path
    assert "replace_skin_weights_same_count" in manifest["allowed_edit_operations"]
    assert manifest["interchange_joint_slots"]
    assert not manifest["interchange_report"]["missing_textures"]
    assert (path.parent / "referenced_files" / texture.path).read_bytes() == texture.paz_file.read_bytes()
    assert set(result.output_paths) == {file for file in path.parent.rglob("*") if file.is_file()}
    restored = import_glb_with_sidecar(path)
    original = parse_pac(raw, model.path)
    for got, wanted in zip(restored.submeshes[0].bone_weights, original.submeshes[0].bone_weights, strict=True):
        assert got == pytest.approx(wanted)
    assert build_mesh_import_preview(model, path, import_mode="roundtrip").rebuilt_data == raw
    assert model.paz_file.read_bytes() == raw


def test_glb_missing_skeleton_requires_explicit_mesh_only_choice(tmp_path):
    model, _skeleton, _texture, raw, _options = rigged_archive(tmp_path)
    options = {"archive_entries_by_normalized_path": {}, "archive_entries_by_basename": {},
               "build_preview_context": False}
    result = export_archive_mesh(model, tmp_path / "out", "glb", **options)
    assert result.requires_confirmation and "GLB" in result.confirmation_title
    assert not result.output_paths and not list((tmp_path / "out").iterdir())
    result = export_archive_mesh(model, tmp_path / "out", "glb", **options, allow_missing_skeleton=True)
    assert result.output_paths
    assert not glb_document(tmp_path / "out/body.glb").get("skins")
    assert model.paz_file.read_bytes() == raw


def test_glb_unresolved_palette_does_not_invent_skin_weights(tmp_path, monkeypatch):
    model, _skeleton, _texture, raw, options = rigged_archive(tmp_path)
    monkeypatch.setattr("cdmw.modding.mesh_parser.resolve_pac_bone_palette", lambda *_args: [])
    result = export_archive_mesh(model, tmp_path / "out", "glb", **options,
                                 build_preview_context=False)
    assert any("GLB retains source coordinates without skin weights" in line
               for line in result.summary_lines)
    path = tmp_path / "out/body.glb"
    document = glb_document(path)
    assert all("skin" not in node for node in document["nodes"])
    manifest = json.loads(Path(f"{path}.meta.json").read_text())
    assert not any(manifest["interchange_joint_slots"])
    assert "replace_skin_weights_same_count" not in manifest["allowed_edit_operations"]
    assert model.paz_file.read_bytes() == raw


def test_batch_glb_resolves_rig_and_preserves_missing_rig_policy(tmp_path):
    model, _skeleton, _texture, raw, options = rigged_archive(tmp_path)
    request = BatchMeshExportRequest(1, model, tmp_path / "batch", "glb",
        options["archive_entries_by_normalized_path"], options["archive_entries_by_basename"])
    result = export_batch_mesh_item(request, stop_event=threading.Event())
    assert result.status == "exported", result.details
    assert glb_document(result.output_directory / "body.glb")["skins"]
    missing = replace(request, entries_by_path={}, entries_by_basename={})
    refused = export_batch_mesh_item(missing, stop_event=threading.Event())
    assert refused.status == "failed" and "Mesh-only export was not enabled" in "\n".join(refused.details)
    permitted = export_batch_mesh_item(replace(missing, allow_missing_skeleton=True), stop_event=threading.Event())
    assert permitted.status == "exported", permitted.details
    assert not glb_document(permitted.output_directory / "body.glb").get("skins")
    assert model.paz_file.read_bytes() == raw


def test_single_export_keeps_an_edit_saved_over_an_earlier_export(tmp_path):
    # The user edits body.glb in place, then exports the same-named model again
    # into the same folder: the edit must not be replaced without a word.
    model, _skeleton, texture, _raw, options = rigged_archive(tmp_path)
    out = tmp_path / "out"
    first = export_archive_mesh(model, out, "glb", **options, related_entries=(texture,),
                                build_preview_context=False, keep_changed_files=True)
    again = export_archive_mesh(model, out, "glb", **options, related_entries=(texture,),
                                build_preview_context=False, keep_changed_files=True)
    assert sorted(again.output_paths) == sorted(first.output_paths), "an identical export is published again"
    edited = out / "body.glb"
    edited.write_bytes(edited.read_bytes() + b"\0")
    with pytest.raises(ValueError, match="body.glb already exists"):
        export_archive_mesh(model, out, "glb", **options, related_entries=(texture,),
                            build_preview_context=False, keep_changed_files=True)
    assert edited.read_bytes().endswith(b"\0")
    assert not [path for path in out.iterdir() if path.name.startswith(".cdmw-mesh-export-")]


def test_a_texture_left_out_of_the_export_is_named_in_its_summary(tmp_path):
    # Unchecking a texture in the referenced-files prompt leaves the GLB untextured.
    model, _skeleton, texture, _raw, options = rigged_archive(tmp_path)
    reference = ArchiveModelTextureReference(
        reference_name="guide0.dds", material_name="guide0", part_name="guide0",
        resolved_archive_path=texture.path, resolved_entry=texture,
        resolution_status="resolved", semantic_label="Base color",
    )
    kept = export_archive_mesh(model, tmp_path / "kept", "glb", **options, related_entries=(texture,),
                               model_texture_references=(reference,), build_preview_context=False)
    assert not [line for line in kept.summary_lines if "texture" in line.casefold()]
    left_out = export_archive_mesh(model, tmp_path / "left-out", "glb", **options,
                                   model_texture_references=(reference,), build_preview_context=False)
    report = json.loads((tmp_path / "left-out/body.glb.meta.json").read_text())["interchange_report"]
    assert report["missing_textures"]
    assert any(line.startswith("Textures not included: ") for line in left_out.summary_lines)
    assert [line for line in left_out.summary_lines if line.startswith("Missing texture: ")] == [
        f"Missing texture: {row}" for row in report["missing_textures"]]
