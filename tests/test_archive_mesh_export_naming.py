import unittest
import tempfile
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.core.archive_modding import (
    _build_export_mtl_texture_overrides,
    export_archive_mesh,
    _mesh_export_basename,
    _rewrite_export_mtl_map_kd,
)
from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.core.archive_mesh_types import MeshExportResult
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.ui.archive_browser.mesh_launch_flow import ArchiveMeshLaunchFlowMixin
from cdmw.ui.archive_browser.mesh_patch_flow import ArchiveMeshPatchFlowMixin


class _ArchiveMeshPresetFlowShell(ArchiveMeshLaunchFlowMixin, ArchiveMeshPatchFlowMixin):
    def __init__(self, settings_file_path: Path) -> None:
        self.settings_file_path = settings_file_path
        self.texconv_path_edit = SimpleNamespace(text=lambda: "")
        self.archive_entries_by_normalized_path = {}
        self.archive_entries_by_basename = {}
        self.mesh_editor_tab = SimpleNamespace(builder_host=lambda: None)
        self.opened: list[dict[str, object]] = []
        self.static_prompts: list[dict[str, object]] = []
        self.utility_tasks: list[dict[str, object]] = []

    def _open_mesh_editor_for_entry(self, entry: ArchiveEntry, **kwargs: object) -> object:
        self.opened.append({"entry": entry, **kwargs})
        return object()

    def _prompt_archive_static_replacement_options(self, entry: ArchiveEntry, scene_path: Path, **kwargs: object) -> None:
        self.static_prompts.append({"entry": entry, "scene_path": scene_path, **kwargs})
        callback = kwargs.get("continue_build_callback") or kwargs.get("on_accept")
        if callable(callback):
            callback(None, output_mode="patch") if kwargs.get("continue_build_callback") is callback else callback(None)

    def _run_utility_task(self, **kwargs: object) -> None:
        self.utility_tasks.append(kwargs)

    def append_archive_log(self, message: str) -> None:
        return

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        return


class ArchiveMeshExportNamingTests(unittest.TestCase):
    def test_mesh_export_result_accepts_keyword_fields(self) -> None:
        result = MeshExportResult(output_paths=[Path("mesh.obj")], summary_lines=["ok"])

        self.assertEqual([Path("mesh.obj")], result.output_paths)
        self.assertEqual(["ok"], result.summary_lines)
        self.assertFalse(result.requires_confirmation)

    def test_archive_mesh_export_basename_uses_original_filename_stem(self) -> None:
        entry = ArchiveEntry(
            path="character/model/1_pc/10_pgw/nude/cd_pgw_00_nude_00_0001.pac",
            pamt_path=Path("0009/0.pamt"),
            paz_file=Path("0009/0.paz"),
            offset=0,
            comp_size=1,
            orig_size=1,
            flags=0,
            paz_index=0,
        )

        self.assertEqual("cd_pgw_00_nude_00_0001", _mesh_export_basename(entry))

    def test_archive_mesh_export_basename_sanitizes_filename_only(self) -> None:
        entry = ArchiveEntry(
            path="object/model/folder/weird:name?.pam",
            pamt_path=Path("0001/0.pamt"),
            paz_file=Path("0001/0.paz"),
            offset=0,
            comp_size=1,
            orig_size=1,
            flags=0,
            paz_index=0,
        )

        self.assertEqual("weird_name", _mesh_export_basename(entry))

    def test_obj_mtl_overrides_use_resolved_sidecar_base_texture(self) -> None:
        parsed_mesh = ParsedMesh(
            submeshes=[
                SubMesh(
                    name="CD_PHM_02_Sword_Guard_0015",
                    material="CD_PHM_02_Guard_0013",
                    texture="CD_PHM_02_Guard_0013",
                )
            ]
        )
        references = (
            ArchiveModelTextureReference(
                reference_name="character/texture/cd_phm_02_guard_0013_n.dds",
                material_name="cd_phm_02_sword_guard_0015",
                semantic_label="Normal Texture",
                semantic_hint="_normalTexture",
                sidecar_parameter_name="_normalTexture",
                resolved_archive_path="character/texture/cd_phm_02_guard_0013_n.dds",
                resolution_status="resolved",
                relation_confidence="exact_path",
                relation_group="Textures",
            ),
            ArchiveModelTextureReference(
                reference_name="character/texture/cd_texturelayer_003_0006.dds",
                material_name="cd_phm_02_sword_guard_0015",
                semantic_label="Base / diffuse",
                semantic_hint="_detailDiffuseMaskG",
                sidecar_parameter_name="_detailDiffuseMaskG",
                resolved_archive_path="character/texture/cd_texturelayer_003_0006.dds",
                resolution_status="resolved",
                relation_confidence="exact_path",
                relation_group="Textures",
            ),
        )

        overrides = _build_export_mtl_texture_overrides(parsed_mesh, references)

        self.assertEqual(
            {"CD_PHM_02_Guard_0013": "character/texture/cd_texturelayer_003_0006.dds"},
            overrides,
        )

    def test_obj_mtl_rewrite_points_to_copied_referenced_texture(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            texture_path = root / "referenced_files" / "character" / "texture" / "cd_texturelayer_003_0006.dds"
            texture_path.parent.mkdir(parents=True, exist_ok=True)
            texture_path.write_bytes(b"DDS ")
            mtl_path = root / "sword.mtl"
            mtl_path.write_text(
                "\n".join(
                    [
                        "# Crimson Desert Materials",
                        "",
                        "newmtl CD_PHM_02_Guard_0013",
                        "Ka 1.000 1.000 1.000",
                        "map_Kd CD_PHM_02_Guard_0013.dds",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            changed = _rewrite_export_mtl_map_kd(
                mtl_path,
                {"CD_PHM_02_Guard_0013": "character/texture/cd_texturelayer_003_0006.dds"},
                root,
            )

            self.assertEqual(1, changed)
            self.assertIn(
                "map_Kd referenced_files/character/texture/cd_texturelayer_003_0006.dds",
                mtl_path.read_text(encoding="utf-8"),
            )

    def test_internal_modify_original_export_skips_preview_context_rebuild(self) -> None:
        entry = ArchiveEntry(
            path="character/model/body.pac",
            pamt_path=Path("0009/0.pamt"),
            paz_file=Path("0009/0.paz"),
            offset=0,
            comp_size=1,
            orig_size=1,
            flags=0,
            paz_index=0,
        )
        parsed_mesh = ParsedMesh(
            path=entry.path,
            format="pac",
            submeshes=[
                SubMesh(
                    name="Body",
                    material="BodyMat",
                    texture="BodyTex",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    faces=[(0, 1, 2)],
                    bone_indices=[(0,), (1,), (0, 1)],
                    bone_weights=[(1.0,), (1.0,), (0.5, 0.5)],
                    source_index_count=6,
                )
            ],
            total_vertices=3,
            total_faces=1,
            has_uvs=True,
            has_bones=True,
        )
        setattr(parsed_mesh, "_cdmw_original_data", b"source pac bytes")

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            with patch("cdmw.core.archive_mesh_export._parse_archive_mesh", return_value=parsed_mesh), patch(
                "cdmw.core.archive_preview_result_builder.build_archive_preview_result",
                side_effect=AssertionError("preview context rebuild should be skipped"),
            ):
                result = export_archive_mesh(
                    entry,
                    root,
                    "obj",
                    resolve_skeleton_for_obj=False,
                    build_preview_context=False,
                )

            sidecar_path = next(path for path in result.output_paths if path.name.endswith(".obj.meta.json"))
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))

        self.assertEqual("mesh_roundtrip_manifest_v2", payload["format"])
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("cdmw_mesh_roundtrip_manifest_v2", payload["tool_version"])
        self.assertEqual("character/model/body.pac", payload["source_archive_path"])
        self.assertEqual(hashlib.sha256(b"source pac bytes").hexdigest(), payload["source_asset_hash"])
        self.assertEqual(len(b"source pac bytes"), payload["source_asset_size"])
        self.assertEqual("body", payload["asset_id"])
        self.assertIn("replace_positions_same_count", payload["allowed_edit_operations"])
        self.assertFalse(payload["import_rules"]["allow_topology_change"])
        self.assertEqual("lod0_submesh0", payload["lods"][0]["submeshes"][0]["stable_id"])
        self.assertEqual(3, payload["lods"][0]["submeshes"][0]["original_vertex_count"])
        self.assertEqual(6, payload["lods"][0]["submeshes"][0]["original_index_count"])
        self.assertEqual(3, payload["lods"][0]["submeshes"][0]["exported_index_count"])
        self.assertEqual([0, 1, 2, 3, 4, 5], payload["lods"][0]["submeshes"][0]["source_index_map"])
        self.assertTrue(payload["skeleton_info"]["skinned"])
        self.assertEqual(2, payload["skeleton_info"]["inferred_bone_count"])
        self.assertEqual(2, payload["skeleton_info"]["parts"][0]["max_influences"])
        self.assertTrue(payload["import_rules"]["preserve_bone_weights"])
        self.assertNotIn("family_graph", payload)
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "schemas" / "mesh" / "mesh.cdmeta.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("mesh_roundtrip_manifest_v2", schema["properties"]["format"]["const"])
        self.assertEqual(1, schema["properties"]["schema_version"]["const"])
        for key in schema["required"]:
            self.assertIn(key, payload)
        for key in schema["$defs"]["lod"]["required"]:
            self.assertIn(key, payload["lods"][0])
        for key in schema["$defs"]["submesh"]["required"]:
            self.assertIn(key, payload["lods"][0]["submeshes"][0])

    def test_rebuilt_asset_preset_flows_open_mesh_editor_and_schedule_preview_and_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            rebuilt_path = root / "rebuilt.pac"
            rebuilt_path.write_bytes(b"pac")
            entry = ArchiveEntry(
                path="character/model/body.pac",
                pamt_path=root / "0.pamt",
                paz_file=root / "0.paz",
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            setup = MeshImportSetupSelection(
                scene_path=rebuilt_path,
                import_mode="static_replacement",
                source_label="Rebuilt asset: rebuilt.pac",
                placement_review_title="Preview rebuilt asset",
                placement_context_note="Preview through existing archive workflow.",
            )

            preview_shell = _ArchiveMeshPresetFlowShell(root / "preview.ini")
            preview_shell._start_archive_mesh_import_preview(entry, preset_setup=setup)
            patch_shell = _ArchiveMeshPresetFlowShell(root / "patch.ini")
            patch_shell._start_archive_mesh_patch(entry, preset_setup=setup)

        self.assertEqual(
            {
                "entry": entry,
                "mode": "external_import",
                "source_path": rebuilt_path,
                "source_skeleton": None,
                "supplemental_files": (),
                "scene_import_result": None,
                "activate": True,
            },
            preview_shell.opened[0],
        )
        self.assertEqual(rebuilt_path, preview_shell.static_prompts[0]["scene_path"])
        self.assertEqual(rebuilt_path, patch_shell.static_prompts[0]["scene_path"])
        self.assertEqual("Preview rebuilt asset", patch_shell.static_prompts[0]["dialog_title"])
        self.assertEqual(1, len(preview_shell.utility_tasks))
        self.assertEqual(1, len(patch_shell.utility_tasks))
        self.assertIn("Rebuilding mesh preview for body.pac", str(patch_shell.utility_tasks[0]["status_message"]))
        self.assertEqual(rebuilt_path, patch_shell.opened[0]["source_path"])

    def test_modify_original_preset_opens_mesh_editor_in_modify_original_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            clone_path = root / "modify-original.obj"
            clone_path.write_text("o clone\n", encoding="utf-8")
            entry = ArchiveEntry(
                path="character/model/body.pac",
                pamt_path=root / "0.pamt",
                paz_file=root / "0.paz",
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            setup = MeshImportSetupSelection(
                scene_path=clone_path,
                import_mode="static_replacement",
                source_label="Modify Original in-app clone: modify-original.obj",
                placement_review_title="Modify Original Geometry",
            )
            shell = _ArchiveMeshPresetFlowShell(root / "settings.ini")

            shell._start_archive_mesh_patch(entry, preset_setup=setup)

        self.assertEqual("modify_original", shell.opened[0]["mode"])
        self.assertEqual(clone_path, shell.opened[0]["source_path"])
        self.assertTrue(shell.opened[0]["activate"])


if __name__ == "__main__":
    unittest.main()
