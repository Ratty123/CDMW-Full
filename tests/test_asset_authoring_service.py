from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock


# Mirrors the payload selection in CrimsonDesertModWorkbench.spec.
_BUNDLED_OPENIMAGEIO_SKIPPED = {"idiff.exe", "maketx.exe"}


def _installed_openimageio_bin() -> Path | None:
    try:
        module_spec = importlib.util.find_spec("OpenImageIO")
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if module_spec is None:
        return None
    for location in tuple(getattr(module_spec, "submodule_search_locations", ()) or ()):
        if not str(location or "").strip():
            continue
        candidate = Path(location) / "bin"
        if (candidate / "oiiotool.exe").is_file():
            return candidate
    return None

from cdmw.services import bundled_helper_availability
from cdmw.services.bundled_helper_availability import find_bundled_openimageio_binary
from cdmw.services.asset_authoring_service import (
    ASSET_AUTHORING_DISCOVERY_SCHEMA,
    ASSET_AUTHORING_MESH_HEALTH_SCHEMA,
    ASSET_AUTHORING_MESH_OPTIMIZATION_SCHEMA,
    ASSET_AUTHORING_SCENE_IMPORT_SCHEMA,
    ASSET_AUTHORING_TANGENT_REPORT_SCHEMA,
    ASSET_AUTHORING_TEXTURE_SET_SCHEMA,
    ASSET_AUTHORING_UV_REPORT_SCHEMA,
    AssetAuthoringService,
    asset_authoring_discovery_report,
    asset_authoring_fixture_manifest,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.scene_import_result_ops import SceneImportResult
from cdmw.services.service_container import ServiceContainer
from tools.mesh_editor_dev_harness import run_scenario


class AssetAuthoringServiceTests(unittest.TestCase):
    def test_discovery_report_marks_missing_helpers_unavailable(self) -> None:
        with mock.patch("cdmw.services.asset_authoring_service.find_native_mesh_core_binary", return_value=None):
            report = AssetAuthoringService().discovery_report(
                {"xatlas": Path("Z:/definitely/missing/xatlas.exe")}
            )

        self.assertEqual(ASSET_AUTHORING_DISCOVERY_SCHEMA, report["schema"])
        self.assertEqual("ok", report["status"])
        self.assertEqual("unavailable", report["helpers"]["cdmw_mesh_core"]["status"])
        self.assertIn("auto-uv-json", report["helpers"]["cdmw_mesh_core"]["capabilities"])
        self.assertIn("generate-tangents-json", report["helpers"]["cdmw_mesh_core"]["capabilities"])
        self.assertIn("cleanup-json", report["helpers"]["cdmw_mesh_core"]["capabilities"])
        self.assertIn("optimize-json", report["helpers"]["cdmw_mesh_core"]["capabilities"])
        self.assertIn("import-scene-json", report["helpers"]["cdmw_mesh_core"]["capabilities"])
        self.assertEqual("not_checked", report["helpers"]["cdmw_mesh_core"]["version_status"])
        self.assertEqual("configured_missing", report["helpers"]["xatlas"]["status"])
        self.assertFalse(report["helpers"]["xatlas"]["package_safe"])
        json.dumps(report)

    def test_bundled_openimageio_resolves_beside_the_frozen_executable(self) -> None:
        """The frozen app must find oiiotool without the installed package.

        A frozen build has no importable OpenImageIO, so a resolver that only
        consulted the module would report the helper unavailable in exactly the
        shipped configuration this payload exists to fix.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            bundled = app_root / "openimageio" / "oiiotool.exe"
            bundled.parent.mkdir(parents=True)
            bundled.write_text("", encoding="utf-8")

            with mock.patch.object(
                bundled_helper_availability.sys, "frozen", True, create=True
            ), mock.patch.object(
                bundled_helper_availability.sys, "executable", str(app_root / "CrimsonDesertModWorkbench.exe")
            ), mock.patch.object(
                bundled_helper_availability.importlib.util, "find_spec", return_value=None
            ):
                self.assertEqual(bundled, find_bundled_openimageio_binary())

    def test_bundled_openimageio_is_preferred_over_an_arbitrary_path_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled = Path(temp_dir) / "oiiotool.exe"
            bundled.write_text("", encoding="utf-8")

            with mock.patch.dict(
                bundled_helper_availability.BUNDLED_HELPER_FINDERS,
                {"openimageio": lambda: bundled},
            ), mock.patch(
                "cdmw.services.asset_authoring_service.shutil.which",
                return_value="Z:/somewhere/else/oiiotool.exe",
            ):
                helper = AssetAuthoringService().discovery_report()["helpers"]["openimageio"]

        self.assertEqual("available", helper["status"])
        self.assertEqual("bundled_lookup", helper["source"])
        self.assertEqual(str(bundled), helper["path"])
        self.assertTrue(helper["bundled"])
        self.assertTrue(helper["package_safe"])

    def test_configured_openimageio_path_still_overrides_the_bundled_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = Path(temp_dir) / "custom-oiiotool.exe"
            configured.write_text("", encoding="utf-8")
            bundled = Path(temp_dir) / "oiiotool.exe"
            bundled.write_text("", encoding="utf-8")

            with mock.patch.dict(
                bundled_helper_availability.BUNDLED_HELPER_FINDERS,
                {"openimageio": lambda: bundled},
            ):
                report = AssetAuthoringService().discovery_report({"openimageio": configured})

        helper = report["helpers"]["openimageio"]
        self.assertEqual("configured", helper["source"])
        self.assertEqual(str(configured), helper["path"])

    def test_bundled_openimageio_payload_runs_with_nothing_else_present(self) -> None:
        """The bundled DLL closure has to be complete on its own.

        oiiotool resolves its DLLs from its own directory, so a payload missing
        one still passes every test run from the venv and fails only in the
        packaged app -- the exact failure this bundle exists to remove. Staging
        the spec's selection into an empty directory is what proves it.
        """

        source_bin = _installed_openimageio_bin()
        if source_bin is None:
            self.skipTest("openimageio package is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            staged = Path(temp_dir) / "openimageio"
            staged.mkdir()
            for path in sorted(source_bin.iterdir()):
                if not path.is_file() or path.suffix.lower() not in {".dll", ".exe"}:
                    continue
                if path.name.casefold() in {name.casefold() for name in _BUNDLED_OPENIMAGEIO_SKIPPED}:
                    continue
                shutil.copy2(path, staged / path.name)

            self.assertFalse((staged / "maketx.exe").exists())
            completed = subprocess.run(
                [str(staged / "oiiotool.exe"), "--version"],
                capture_output=True,
                text=True,
                timeout=60,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(completed.stdout.strip())

    def test_packaging_spec_bundles_openimageio_and_fails_closed_in_release(self) -> None:
        spec_source = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")

        self.assertIn('binaries.append((str(runtime_file), "openimageio"))', spec_source)
        self.assertIn("_openimageio_package_root()", spec_source)
        # The console script in Scripts/ is a launcher shim, not the tool.
        self.assertIn('(root / "bin" / "oiiotool.exe").is_file()', spec_source)
        self.assertIn('elif PROFILE == "release":', spec_source)
        # Following oiiotool.exe's imports makes PyInstaller re-collect the same
        # DLLs at their package-relative path -- 15 MB in the built bundle that
        # nothing can load, since the OpenImageIO Python module is not bundled
        # and oiiotool reads its own directory.
        self.assertIn('"OpenImageIO\\\\bin\\\\",', spec_source)
        for skipped in _BUNDLED_OPENIMAGEIO_SKIPPED:
            self.assertIn(skipped, spec_source)
        for notice in ("LICENSE.md", "THIRD-PARTY.md"):
            self.assertIn(notice, spec_source)

    def test_discovery_report_accepts_configured_helper_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            helper = Path(temp_dir) / "material_maker.exe"
            helper.write_text("", encoding="utf-8")
            report = AssetAuthoringService().discovery_report({"material_maker": helper})

        material_maker = report["helpers"]["material_maker"]
        self.assertEqual("available", material_maker["status"])
        self.assertEqual("configured", material_maker["source"])
        self.assertIn("export_texture_set", material_maker["capabilities"])

    def test_discovery_report_marks_bundled_mesh_backends_available_through_mesh_core(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_core = Path(temp_dir) / "cdmw-mesh-core.exe"
            mesh_core.write_text("", encoding="utf-8")
            with mock.patch("cdmw.services.asset_authoring_service.find_native_mesh_core_binary", return_value=mesh_core):
                report = AssetAuthoringService().discovery_report()

        for key in ("xatlas", "ufbx", "meshoptimizer"):
            helper = report["helpers"][key]
            self.assertEqual("available", helper["status"])
            self.assertEqual("cdmw_mesh_core", helper["source"])
            self.assertEqual("bundled", helper["version_status"])
            self.assertEqual("bundled in CDMW Mesh Core", helper["version"])
            self.assertEqual(str(mesh_core), helper["path"])

    def test_discovery_report_can_probe_configured_helper_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            helper = Path(temp_dir) / "material_maker.exe"
            helper.write_text("", encoding="utf-8")
            with mock.patch("cdmw.services.asset_authoring_service.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=0, stdout="Material Maker 1.4.0\n", stderr="")
                report = AssetAuthoringService().discovery_report(
                    {"material_maker": helper},
                    include_versions=True,
                )

        material_maker = report["helpers"]["material_maker"]
        self.assertEqual("ok", material_maker["version_status"])
        self.assertEqual("Material Maker 1.4.0", material_maker["version"])
        self.assertEqual([str(helper), "--version"], material_maker["version_argv"])
        self.assertIn((str(helper), "--version"), [call.args[0] for call in run_mock.call_args_list])

    def test_discovery_report_marks_version_probe_failures_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            helper = Path(temp_dir) / "oiiotool.exe"
            helper.write_text("", encoding="utf-8")
            with mock.patch("cdmw.services.asset_authoring_service.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=2, stdout="", stderr="bad version")
                report = asset_authoring_discovery_report(
                    configured_paths={"openimageio": helper},
                    include_versions=True,
                )

        openimageio = report["helpers"]["openimageio"]
        self.assertEqual("available", openimageio["status"])
        self.assertEqual("failed", openimageio["version_status"])
        self.assertEqual("bad version", openimageio["version"])
        self.assertEqual(2, openimageio["version_returncode"])

    def test_discovery_report_finds_openimageio_console_script_beside_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts = Path(temp_dir) / "Scripts"
            scripts.mkdir()
            python = scripts / "python.exe"
            helper = scripts / "oiiotool.exe"
            python.write_text("", encoding="utf-8")
            helper.write_text("", encoding="utf-8")
            module_spec = mock.Mock(origin=str(Path(temp_dir) / "site-packages" / "OpenImageIO.cp314-win_amd64.pyd"))
            module_spec.submodule_search_locations = ()
            with (
                mock.patch("cdmw.services.asset_authoring_service.sys.executable", str(python)),
                mock.patch("cdmw.services.asset_authoring_service.shutil.which", return_value=None),
                mock.patch("cdmw.services.asset_authoring_service.importlib.util.find_spec", return_value=module_spec),
            ):
                report = AssetAuthoringService().discovery_report()

        openimageio = report["helpers"]["openimageio"]
        self.assertEqual("available", openimageio["status"])
        self.assertEqual("python_module_script", openimageio["source"])
        self.assertEqual(str(helper), openimageio["path"])

    def test_fixture_manifest_points_at_repeatable_mesh_and_texture(self) -> None:
        manifest = asset_authoring_fixture_manifest()

        self.assertTrue(Path(manifest["mesh"]).is_file())
        self.assertTrue(Path(manifest["texture"]).is_file())
        self.assertEqual(3, manifest["expected"]["mesh_vertices"])
        self.assertEqual((2, 2), tuple(manifest["expected"]["texture_size"]))

    def test_service_container_binds_asset_authoring_settings(self) -> None:
        container = ServiceContainer.create_default(settings="old")
        self.assertIsNotNone(container.asset_authoring)

        container.bind_settings("new")

        self.assertEqual("new", container.asset_authoring.settings)

    def test_harness_asset_authoring_discovery_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario("asset-authoring-discovery", Path(temp_dir))
            report_path = Path(result["asset_authoring"]["report_path"])
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(ASSET_AUTHORING_DISCOVERY_SCHEMA, report["schema"])
        self.assertIn("xatlas", report["helpers"])

    def test_material_maker_project_command_uses_configured_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper = root / "material_maker.exe"
            project = root / "wood.material"
            helper.write_text("", encoding="utf-8")
            project.write_text("", encoding="utf-8")

            command = AssetAuthoringService().material_maker_project_command(
                project,
                {"material_maker": helper},
            )

        self.assertEqual("ready", command["status"])
        self.assertTrue(command["can_launch"])
        self.assertEqual([str(helper), str(project)], command["argv"])

    def test_material_maker_export_command_requires_configured_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            helper = Path(temp_dir) / "material_maker.exe"
            helper.write_text("", encoding="utf-8")
            command = AssetAuthoringService().material_maker_export_command(
                Path(temp_dir) / "wood.material",
                Path(temp_dir) / "exports",
                {"material_maker": helper},
            )

        self.assertEqual("cli_export_unconfigured", command["status"])
        self.assertFalse(command["can_run"])

    def test_material_maker_export_command_expands_json_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper = root / "material_maker.exe"
            project = root / "wood.material"
            output = root / "exports"
            helper.write_text("", encoding="utf-8")
            command = AssetAuthoringService().material_maker_export_command(
                project,
                output,
                {
                    "material_maker": helper,
                    "material_maker_export_template": '["{exe}","--export","{project}","--output","{output}"]',
                },
            )

        self.assertEqual("ready", command["status"])
        self.assertTrue(command["can_run"])
        self.assertEqual([str(helper), "--export", str(project), "--output", str(output)], command["argv"])

    def test_run_material_maker_export_uses_configured_command_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper = root / "material_maker.exe"
            project = root / "wood.material"
            output = root / "exports"
            helper.write_text("", encoding="utf-8")
            with mock.patch("cdmw.services.asset_authoring_service.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=0, stdout="done", stderr="")
                result = AssetAuthoringService().run_material_maker_export(
                    project,
                    output,
                    {
                        "material_maker": helper,
                        "material_maker_export_template": ["{exe}", "--export", "{project}", "--output", "{output}"],
                    },
                )

        self.assertEqual("ok", result["status"])
        run_mock.assert_called_once()
        argv = run_mock.call_args.args[0]
        self.assertEqual((str(helper), "--export", str(project), "--output", str(output)), argv)

    def test_ingest_exported_texture_set_maps_material_maker_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "Oak_BaseColor.png",
                "Oak_Normal.tga",
                "Oak_Roughness.png",
                "Oak_Metallic.png",
                "Oak_AO.png",
                "Oak_Height.exr",
                "Oak_Recolor_Mask.png",
                "Oak_Notes.txt",
            ):
                (root / name).write_bytes(b"source")

            report = AssetAuthoringService().ingest_exported_texture_set(root, material_name="Oak")

        self.assertEqual(ASSET_AUTHORING_TEXTURE_SET_SCHEMA, report["schema"])
        self.assertEqual("ok", report["status"])
        self.assertEqual("cdmw_directxtex", report["dds_authority"])
        self.assertEqual(
            {"base_color", "normal", "roughness", "metallic", "ao", "height", "recolor"},
            set(report["channels"]),
        )
        self.assertEqual("review_intermediate", report["channels"]["base_color"]["source_role"])
        self.assertEqual("normal_bc5", report["channels"]["normal"]["profile_hint"])
        self.assertEqual("mask", report["channels"]["metallic"]["texture_type"])
        self.assertEqual([], report["unmapped"])

    def test_ingest_exported_texture_set_supports_overrides_and_duplicate_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Oak_Custom.png").write_bytes(b"source")
            (root / "Oak_Albedo.png").write_bytes(b"source")
            (root / "Oak_BaseColor.png").write_bytes(b"source")

            report = AssetAuthoringService().ingest_exported_texture_set(
                root,
                channel_overrides={"Oak_Custom.png": "ao"},
            )

        self.assertIn("ao", report["channels"])
        self.assertIn("base_color", report["channels"])
        self.assertEqual("Oak_Albedo.png", Path(report["channels"]["base_color"]["path"]).name)
        self.assertTrue(any("Duplicate base_color map skipped" in warning for warning in report["warnings"]))

    def test_ingest_exported_texture_set_reports_missing_export_folder(self) -> None:
        report = AssetAuthoringService().ingest_exported_texture_set(Path("Z:/definitely/missing/material-maker"))

        self.assertEqual(ASSET_AUTHORING_TEXTURE_SET_SCHEMA, report["schema"])
        self.assertEqual("missing_export_dir", report["status"])
        self.assertEqual({}, report["channels"])

    def test_scene_import_report_wraps_obj_as_unmapped_structured_result(self) -> None:
        mesh_path = Path(asset_authoring_fixture_manifest()["mesh"])

        report = AssetAuthoringService().scene_import_report(mesh_path)

        self.assertEqual(ASSET_AUTHORING_SCENE_IMPORT_SCHEMA, report["schema"])
        self.assertEqual("ok", report["status"])
        self.assertEqual("cdmw_scene_importer", report["backend"])
        self.assertEqual("unmapped", report["crimson_compatibility"])
        self.assertEqual("obj", report["source_format"])
        self.assertEqual(1, report["mesh"]["submesh_count"])
        self.assertEqual(3, report["mesh"]["vertex_count"])
        self.assertEqual(1, report["mesh"]["face_count"])
        self.assertFalse(report["skeleton_hints"]["has_skinning"])
        json.dumps(report)

    def test_scene_import_report_reports_fbx_as_unsupported_when_native_ufbx_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "rigged.fbx"
            helper = root / "cdmw-mesh-core.exe"
            source.write_bytes(b"fbx")
            helper.write_bytes(b"")

            with mock.patch("cdmw.modding.mesh_native_core.native_scene_import_report", return_value=None):
                report = AssetAuthoringService().scene_import_report(source, {"cdmw_mesh_core": helper})

        self.assertEqual(ASSET_AUTHORING_SCENE_IMPORT_SCHEMA, report["schema"])
        self.assertEqual("unsupported", report["status"])
        self.assertEqual("ufbx_unavailable", report["backend"])
        self.assertEqual("available", report["helper"]["status"])
        self.assertIn("fbx_animation_import_unavailable", report["unsupported"])
        json.dumps(report)

    def test_scene_import_report_wraps_native_ufbx_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "rigged.fbx"
            source.write_bytes(b"fbx")
            native_report = {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "import_scene",
                "import_backend": "ufbx",
                "source_path": str(source),
                "source_format": "fbx",
                "crimson_compatibility": "unmapped",
                "mesh": {"part_count": 1, "vertex_count": 4, "face_count": 2, "triangle_count": 2},
                "materials": {"count": 1, "names": ["body"]},
                "texture_hints": {"count": 1, "files": ["body_d.dds"]},
                "skeleton_hints": {
                    "has_skinning": True,
                    "bone_count": 3,
                    "skin_deformer_count": 1,
                    "skin_cluster_count": 3,
                    "rig_status": "reported_unsupported_until_crimson_mapping",
                    "animation_status": "reported_unsupported_until_crimson_mapping",
                },
                "animations": {"count": 1, "names": ["idle"]},
                "unsupported": ["fbx_rig_mapping_report_only", "fbx_animation_report_only"],
                "diagnostics": ["FBX parsed with ufbx."],
            }

            with mock.patch("cdmw.modding.mesh_native_core.native_scene_import_report", return_value=native_report):
                report = AssetAuthoringService().scene_import_report(source)

        self.assertEqual(ASSET_AUTHORING_SCENE_IMPORT_SCHEMA, report["schema"])
        self.assertEqual("ok", report["status"])
        self.assertEqual("ufbx", report["backend"])
        self.assertEqual(native_report, report["native_import"])
        self.assertEqual(4, report["mesh"]["vertex_count"])
        self.assertEqual([{"name": "body", "source": "ufbx"}], report["materials"])
        self.assertEqual([{"kind": "referenced", "path": "body_d.dds", "source": "ufbx"}], report["texture_hints"])
        self.assertTrue(report["skeleton_hints"]["has_skinning"])
        self.assertIn("fbx_animation_report_only", report["unsupported"])
        json.dumps(report)

    def test_scene_import_report_marks_skinned_source_as_target_mapping_required(self) -> None:
        submesh = SubMesh(
            name="rigged",
            material="body",
            vertices=[(0.0, 0.0, 0.0)],
            uvs=[(0.0, 0.0)],
            normals=[(0.0, 1.0, 0.0)],
            faces=[],
            bone_indices=[(0,)],
            bone_weights=[(1.0,)],
        )
        mesh = ParsedMesh(path="rigged.obj", format="obj", submeshes=[submesh], total_vertices=1, has_bones=True)
        with mock.patch(
            "cdmw.modding.scene_importer.import_scene_mesh_with_report",
            return_value=SceneImportResult(mesh=mesh),
        ):
            report = AssetAuthoringService().scene_import_report(Path("rigged.obj"))

        self.assertEqual("ok", report["status"])
        self.assertTrue(report["skeleton_hints"]["has_skinning"])
        self.assertEqual("skinning_detected_target_mapping_required", report["skeleton_hints"]["rig_status"])
        self.assertIn("skeleton_binding_requires_target_mapping", report["unsupported"])
        json.dumps(report)

    def test_mesh_health_report_counts_bad_duplicate_and_loose_geometry_without_mutating(self) -> None:
        submesh = SubMesh(
            name="cleanup",
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (2.0, 2.0, 2.0),
                (float("nan"), 0.0, 0.0),
            ],
            faces=[
                (0, 1, 3),
                (3, 1, 0),
                (0, 0, 1),
                (0, 1, 99),
                ("bad", 1, 2),  # type: ignore[list-item]
            ],
        )
        mesh = ParsedMesh(path="cleanup.obj", format="obj", submeshes=[submesh])
        vertices_before = list(submesh.vertices)
        faces_before = list(submesh.faces)

        report = AssetAuthoringService().mesh_health_report(mesh)

        self.assertEqual(ASSET_AUTHORING_MESH_HEALTH_SCHEMA, report["schema"])
        self.assertEqual("issues_found", report["status"])
        self.assertFalse(report["mutates"])
        self.assertEqual(1, report["totals"]["invalid_vertices"])
        self.assertEqual(1, report["totals"]["invalid_faces"])
        self.assertEqual(1, report["totals"]["invalid_indices"])
        self.assertEqual(1, report["totals"]["degenerate_faces"])
        self.assertEqual(1, report["totals"]["duplicate_vertex_groups"])
        self.assertEqual(1, report["totals"]["duplicate_vertices"])
        self.assertEqual(1, report["totals"]["duplicate_faces"])
        self.assertEqual(3, report["totals"]["loose_vertices"])
        self.assertEqual(vertices_before, submesh.vertices)
        self.assertEqual(faces_before, submesh.faces)
        json.dumps(report)

    def test_mesh_health_report_accepts_watertight_mesh_with_consistent_winding(self) -> None:
        submesh = SubMesh(
            name="tetrahedron",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
            faces=[(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)],
        )
        mesh = ParsedMesh(path="tetrahedron.obj", format="obj", submeshes=[submesh])

        report = AssetAuthoringService().mesh_health_report(mesh)

        self.assertEqual("ok", report["status"])
        self.assertEqual([], report["warnings"])
        self.assertEqual(0, report["totals"]["boundary_edges"])
        self.assertEqual(0, report["totals"]["non_manifold_edges"])
        self.assertEqual(0, report["totals"]["inconsistent_winding_edges"])
        self.assertEqual(0, report["totals"]["bowtie_vertices"])
        json.dumps(report)

    def test_mesh_health_report_counts_bowtie_non_manifold_and_flipped_winding(self) -> None:
        bowtie = SubMesh(
            name="bowtie",
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (-1.0, 0.0, 0.0),
                (-1.0, 1.0, 0.0),
            ],
            faces=[(0, 1, 2), (0, 3, 4)],
        )
        seam = SubMesh(
            name="seam",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0)],
            faces=[(0, 1, 2), (1, 2, 3), (1, 2, 4)],
        )
        mesh = ParsedMesh(path="connectivity.obj", format="obj", submeshes=[bowtie, seam])

        report = AssetAuthoringService().mesh_health_report(mesh)

        self.assertEqual("issues_found", report["status"])
        self.assertFalse(report["mutates"])
        self.assertEqual(1, report["parts"][0]["bowtie_vertices"])
        self.assertEqual(0, report["parts"][0]["non_manifold_edges"])
        self.assertEqual(1, report["parts"][1]["non_manifold_edges"])
        self.assertEqual(1, report["totals"]["bowtie_vertices"])
        self.assertEqual(1, report["totals"]["non_manifold_edges"])
        self.assertTrue(any("bowtie" in warning for warning in report["warnings"]))
        self.assertTrue(any("non-manifold" in warning for warning in report["warnings"]))
        json.dumps(report)

    def test_mesh_health_report_flags_edges_whose_neighbours_disagree_on_winding(self) -> None:
        submesh = SubMesh(
            name="flipped",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
            faces=[(0, 1, 2), (1, 2, 3)],
        )
        mesh = ParsedMesh(path="flipped.obj", format="obj", submeshes=[submesh])

        report = AssetAuthoringService().mesh_health_report(mesh)

        self.assertEqual("issues_found", report["status"])
        self.assertEqual(1, report["totals"]["inconsistent_winding_edges"])
        self.assertEqual(0, report["totals"]["non_manifold_edges"])
        self.assertEqual(0, report["totals"]["bowtie_vertices"])
        self.assertTrue(any("winding" in warning for warning in report["warnings"]))
        json.dumps(report)

    def test_mesh_health_report_does_not_warn_on_open_boundary_edges(self) -> None:
        submesh = SubMesh(
            name="cloth",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
            faces=[(0, 1, 2), (2, 1, 3)],
        )
        mesh = ParsedMesh(path="cloth.obj", format="obj", submeshes=[submesh])

        report = AssetAuthoringService().mesh_health_report(mesh)

        self.assertEqual("ok", report["status"])
        self.assertEqual(4, report["totals"]["boundary_edges"])
        self.assertEqual([], report["warnings"])
        json.dumps(report)

    def test_mesh_health_report_flags_topology_delta_against_original_mesh(self) -> None:
        original = ParsedMesh(
            path="before.obj",
            format="obj",
            submeshes=[
                SubMesh(
                    name="part",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        edited = ParsedMesh(
            path="after.obj",
            format="obj",
            submeshes=[
                SubMesh(
                    name="part",
                    vertices=[
                        (0.0, 0.0, 0.0),
                        (1.0, 0.0, 0.0),
                        (0.0, 1.0, 0.0),
                        (0.0, 0.0, 1.0),
                    ],
                    faces=[(0, 1, 2), (0, 2, 3)],
                )
            ],
        )

        report = AssetAuthoringService().mesh_health_report(edited, original_mesh=original)

        self.assertTrue(report["topology"]["topology_changed"])
        self.assertEqual(["vertex_count", "face_count", "index_count"], report["topology"]["changed_fields"])
        self.assertTrue(any("Topology changed" in warning for warning in report["warnings"]))
        json.dumps(report)

    def test_mesh_optimization_report_wraps_native_meshoptimizer_evidence(self) -> None:
        mesh = ParsedMesh(
            path="optimize.obj",
            format="obj",
            submeshes=[
                SubMesh(
                    name="part",
                    vertices=[
                        (0.0, 0.0, 0.0),
                        (1.0, 0.0, 0.0),
                        (0.0, 1.0, 0.0),
                        (1.0, 1.0, 0.0),
                    ],
                    faces=[(0, 1, 2), (1, 3, 2)],
                )
            ],
        )
        native_report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "optimize",
            "optimization_backend": "meshoptimizer",
            "topology_changed": True,
            "totals": {
                "input_vertex_count": 4,
                "referenced_vertex_count": 3,
                "input_index_count": 6,
                "output_index_count": 3,
                "input_triangle_count": 2,
                "output_triangle_count": 1,
            },
            "submeshes": [
                {
                    "index": 0,
                    "optimization_backend": "meshoptimizer",
                    "input_vertex_count": 4,
                    "referenced_vertex_count": 3,
                    "input_index_count": 6,
                    "output_index_count": 3,
                    "input_triangle_count": 2,
                    "output_triangle_count": 1,
                    "target_ratio": 0.5,
                    "target_error": 0.02,
                    "result_error": 0.01,
                    "simplified": True,
                    "topology_changed": True,
                    "before": {"cache_acmr": 2.0, "cache_atvr": 1.0, "overdraw": 1.2, "overfetch": 1.0},
                    "after": {"cache_acmr": 1.0, "cache_atvr": 0.75, "overdraw": 1.0, "overfetch": 0.75},
                    "faces": [[0, 1, 2]],
                }
            ],
        }
        with mock.patch("cdmw.modding.mesh_native_core.native_mesh_optimization_report", return_value=native_report):
            report = AssetAuthoringService().mesh_optimization_report(mesh, simplify_ratio=0.5, target_error=0.02)

        self.assertEqual(ASSET_AUTHORING_MESH_OPTIMIZATION_SCHEMA, report["schema"])
        self.assertEqual("issues_found", report["status"])
        self.assertFalse(report["mutates"])
        self.assertTrue(report["simplification"]["opt_in"])
        self.assertEqual(native_report, report["native_optimization"])
        self.assertIn("Native simplification changes index topology", report["warnings"][0])
        json.dumps(report)

    def test_uv_authoring_report_surfaces_islands_bounds_and_topology_delta(self) -> None:
        original = ParsedMesh(
            path="before.obj",
            format="obj",
            submeshes=[
                SubMesh(
                    name="part",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        edited = ParsedMesh(
            path="after.obj",
            format="obj",
            submeshes=[
                SubMesh(
                    name="uv_islands",
                    vertices=[
                        (0.0, 0.0, 0.0),
                        (1.0, 0.0, 0.0),
                        (0.0, 1.0, 0.0),
                        (2.0, 2.0, 0.0),
                        (3.0, 2.0, 0.0),
                        (2.0, 3.0, 0.0),
                    ],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (2.0, 2.0), (3.0, 2.0), (2.0, 3.0)],
                    faces=[(0, 1, 2), (3, 4, 5)],
                ),
                SubMesh(name="missing_uv", vertices=[(0.0, 0.0, 0.0)], uvs=[], faces=[]),
            ],
        )

        report = AssetAuthoringService().uv_authoring_report(edited, original_mesh=original, atlas_size=(1024, 1024))

        self.assertEqual(ASSET_AUTHORING_UV_REPORT_SCHEMA, report["schema"])
        self.assertEqual("issues_found", report["status"])
        self.assertEqual(2, report["island_count"])
        self.assertEqual((1024, 1024), tuple(report["atlas_size"]))
        self.assertEqual((0.0, 0.0), tuple(report["uv_bounds"]["uv_min"]))
        self.assertEqual((3.0, 3.0), tuple(report["uv_bounds"]["uv_max"]))
        self.assertEqual(1, len(report["missing_uv_parts"]))
        self.assertTrue(report["topology"]["topology_changed"])
        self.assertTrue(any("UV remap safety" in warning for warning in report["warnings"]))
        json.dumps(report)

    def test_uv_authoring_report_can_include_native_xatlas_unwrap_evidence(self) -> None:
        mesh = ParsedMesh(
            path="uv.obj",
            format="obj",
            submeshes=[
                SubMesh(
                    name="part",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        native_report = {
            "status": "ok",
            "operation": "auto_uv",
            "unwrap_backend": "xatlas",
            "topology_changed": False,
            "submeshes": [{"index": 0, "chart_count": 1, "output_vertex_count": 3}],
        }

        with mock.patch("cdmw.modding.mesh_native_core.native_mesh_auto_uv_report", return_value=native_report) as unwrap:
            report = AssetAuthoringService().uv_authoring_report(mesh, atlas_size=(512, 512), include_native_unwrap=True)

        unwrap.assert_called_once()
        self.assertEqual(native_report, report["native_unwrap"])
        self.assertEqual("xatlas", report["native_unwrap"]["unwrap_backend"])
        json.dumps(report)

    def test_tangent_authoring_report_surfaces_missing_and_complete_coverage(self) -> None:
        mesh = ParsedMesh(
            path="tangent.obj",
            format="obj",
            submeshes=[
                SubMesh(
                    name="ready",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    tangents=[],
                    faces=[(0, 1, 2)],
                ),
                SubMesh(
                    name="generated",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    tangents=[(1.0, 0.0, 0.0)] * 3,
                    faces=[(0, 1, 2)],
                ),
            ],
        )

        report = AssetAuthoringService().tangent_authoring_report(mesh)

        self.assertEqual(ASSET_AUTHORING_TANGENT_REPORT_SCHEMA, report["schema"])
        self.assertEqual("issues_found", report["status"])
        self.assertFalse(report["mutates"])
        self.assertEqual(1, report["totals"]["missing_tangent_parts"])
        self.assertEqual(1, report["totals"]["complete_tangent_parts"])
        self.assertEqual(2, report["totals"]["generatable_parts"])
        self.assertEqual("missing", report["parts"][0]["tangent_coverage"])
        self.assertEqual("complete", report["parts"][1]["tangent_coverage"])
        json.dumps(report)

if __name__ == "__main__":
    unittest.main()
