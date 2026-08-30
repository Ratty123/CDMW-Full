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
    ASSET_AUTHORING_SCENE_IMPORT_SCHEMA,
    ASSET_AUTHORING_TANGENT_REPORT_SCHEMA,
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
        self.assertNotIn("optimize-json", report["helpers"]["cdmw_mesh_core"]["capabilities"])
        self.assertNotIn("import-scene-json", report["helpers"]["cdmw_mesh_core"]["capabilities"])
        self.assertEqual("not_checked", report["helpers"]["cdmw_mesh_core"]["version_status"])
        self.assertEqual("configured_missing", report["helpers"]["xatlas"]["status"])
        self.assertFalse(report["helpers"]["xatlas"]["package_safe"])
        self.assertEqual({"cdmw_mesh_core", "xatlas", "openimageio"}, set(report["helpers"]))
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

    def test_discovery_report_marks_bundled_mesh_backends_available_through_mesh_core(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_core = Path(temp_dir) / "cdmw-mesh-core.exe"
            mesh_core.write_text("", encoding="utf-8")
            with mock.patch("cdmw.services.asset_authoring_service.find_native_mesh_core_binary", return_value=mesh_core):
                report = AssetAuthoringService().discovery_report()

        for key in ("xatlas",):
            helper = report["helpers"][key]
            self.assertEqual("available", helper["status"])
            self.assertEqual("cdmw_mesh_core", helper["source"])
            self.assertEqual("bundled", helper["version_status"])
            self.assertEqual("bundled in CDMW Mesh Core", helper["version"])
            self.assertEqual(str(mesh_core), helper["path"])

    def test_discovery_report_can_probe_configured_helper_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            helper = Path(temp_dir) / "oiiotool.exe"
            helper.write_text("", encoding="utf-8")
            with mock.patch("cdmw.services.asset_authoring_service.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=0, stdout="OpenImageIO 3.0.6\n", stderr="")
                report = AssetAuthoringService().discovery_report(
                    {"openimageio": helper},
                    include_versions=True,
                )

        openimageio = report["helpers"]["openimageio"]
        self.assertEqual("ok", openimageio["version_status"])
        self.assertEqual("OpenImageIO 3.0.6", openimageio["version"])
        self.assertEqual([str(helper), "--version"], openimageio["version_argv"])
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
