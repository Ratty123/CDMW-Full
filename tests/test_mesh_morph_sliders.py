from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.modding import mesh_native_core
import cdmw.modding.mesh_morph_sliders as morph_sliders
from cdmw.modding.mesh_morph_sliders import (
    apply_morph_slider_values,
    build_morph_delta,
    build_region_volume_delta,
    create_region_volume_slider_profile,
    import_body_slider_profile,
    load_morph_slider_delta,
    load_morph_slider_profiles,
    validate_morph_target,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.static_mesh_replacer import (
    StaticMeshReplacementOptions,
    effective_static_replacement_source_mesh,
)


class CountingSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = list(values)
        self.iterations = 0

    def __bool__(self) -> bool:
        return bool(self._values)

    def __iter__(self):
        self.iterations += 1
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index: int) -> object:
        return self._values[index]


def _submesh(
    *,
    name: str = "part",
    vertices: list[tuple[float, float, float]] | None = None,
    faces: list[tuple[int, int, int]] | None = None,
) -> SubMesh:
    resolved_vertices = vertices or [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    ]
    resolved_faces = faces or [(0, 1, 2)]
    return SubMesh(
        name=name,
        material=name,
        vertices=list(resolved_vertices),
        faces=list(resolved_faces),
        vertex_count=len(resolved_vertices),
        face_count=len(resolved_faces),
    )


def _mesh(
    vertices: list[tuple[float, float, float]] | None = None,
    *,
    name: str = "part",
    faces: list[tuple[int, int, int]] | None = None,
    submeshes: list[SubMesh] | None = None,
) -> ParsedMesh:
    resolved_submeshes = submeshes or [_submesh(name=name, vertices=vertices, faces=faces)]
    return ParsedMesh(
        path="character/model/test.pac",
        format="pac",
        submeshes=resolved_submeshes,
        total_vertices=sum(len(submesh.vertices) for submesh in resolved_submeshes),
        total_faces=sum(len(submesh.faces) for submesh in resolved_submeshes),
    )


def _write_obj(path: Path, vertices: list[tuple[float, float, float]], *, name: str = "part") -> None:
    lines = [f"o {name}"]
    lines.extend(f"v {x} {y} {z}" for x, y, z in vertices)
    lines.append("f 1 2 3")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class MeshMorphSliderTests(unittest.TestCase):
    def test_validate_morph_target_accepts_matching_topology(self) -> None:
        validate_morph_target(
            _mesh(),
            _mesh([(0.0, 0.0, 0.5), (1.0, 0.0, 0.5), (0.0, 1.0, 0.5)]),
        )

    def test_validate_morph_target_uses_vertex_lengths_without_tuple_copy(self) -> None:
        base_vertices = CountingSequence([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        target_vertices = CountingSequence([(0.0, 0.0, 0.5), (1.0, 0.0, 0.5), (0.0, 1.0, 0.5)])
        base = _mesh(submeshes=[SubMesh(name="part", vertices=base_vertices, faces=[(0, 1, 2)])])  # type: ignore[arg-type]
        target = _mesh(submeshes=[SubMesh(name="part", vertices=target_vertices, faces=[(0, 1, 2)])])  # type: ignore[arg-type]

        validate_morph_target(base, target)

        self.assertEqual(0, base_vertices.iterations)
        self.assertEqual(0, target_vertices.iterations)

    def test_topology_signature_reuses_topology_faces_once(self) -> None:
        vertices = CountingSequence([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        faces = CountingSequence([(0, 1, 2)])
        mesh = _mesh(submeshes=[SubMesh(name="part", vertices=vertices, faces=faces)])  # type: ignore[arg-type]

        payload = morph_sliders._topology_signature_payload(mesh)  # type: ignore[attr-defined]

        self.assertEqual(3, payload["submeshes"][0]["vertex_count"])  # type: ignore[index]
        self.assertEqual(1, payload["submeshes"][0]["face_count"])  # type: ignore[index]
        self.assertEqual(0, vertices.iterations)
        self.assertEqual(1, faces.iterations)

    def test_validate_morph_target_rejects_vertex_count_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "vertex count mismatch"):
            validate_morph_target(
                _mesh(),
                _mesh([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]),
            )

    def test_validate_morph_target_rejects_submesh_count_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "submesh count mismatch"):
            validate_morph_target(
                _mesh(),
                _mesh(submeshes=[_submesh(name="part"), _submesh(name="extra")]),
            )

    def test_validate_morph_target_rejects_name_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "name mismatch"):
            validate_morph_target(_mesh(name="body"), _mesh(name="head"))

    def test_validate_morph_target_rejects_face_topology_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "face topology mismatch"):
            validate_morph_target(_mesh(faces=[(0, 1, 2)]), _mesh(faces=[(0, 2, 1)]))

    def test_apply_morph_slider_values_blends_one_negative_multiple_reset_and_post_delta(self) -> None:
        base = _mesh()
        x_target = _mesh([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)])
        y_target = _mesh([(0.0, 2.0, 0.0), (1.0, 2.0, 0.0), (0.0, 3.0, 0.0)])
        x_delta = build_morph_delta(base, x_target, "x")
        y_delta = build_morph_delta(base, y_target, "y")

        one = apply_morph_slider_values(base, [x_delta], {"x": 100.0})
        self.assertEqual((1.0, 0.0, 0.0), one.submeshes[0].vertices[0])

        negative = apply_morph_slider_values(base, [x_delta], {"x": -50.0})
        self.assertEqual((-0.5, 0.0, 0.0), negative.submeshes[0].vertices[0])

        combined = apply_morph_slider_values(base, [x_delta, y_delta], {"x": 50.0, "y": 25.0})
        self.assertEqual((0.5, 0.5, 0.0), combined.submeshes[0].vertices[0])

        reset = apply_morph_slider_values(base, [x_delta], {"x": 0.0})
        self.assertEqual(base.submeshes[0].vertices, reset.submeshes[0].vertices)

        post = apply_morph_slider_values(
            base,
            [x_delta],
            {"x": 100.0},
            post_edit_deltas=[[(0.0, 0.0, 0.25), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]],
        )
        self.assertEqual((1.0, 0.0, 0.25), post.submeshes[0].vertices[0])

    def test_apply_morph_slider_values_returns_native_result_before_python_loop(self) -> None:
        base = _mesh()
        native_result = _mesh([(9.0, 9.0, 9.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        x_delta = build_morph_delta(base, _mesh([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)]), "x")
        calls: list[object] = []
        original = morph_sliders._apply_native_morph_slider_values

        def fake_native(base_mesh: ParsedMesh, deltas: object, values: object, post_edit_deltas: object) -> ParsedMesh:
            calls.append((base_mesh, deltas, values, post_edit_deltas))
            return native_result

        try:
            morph_sliders._apply_native_morph_slider_values = fake_native  # type: ignore[assignment]
            result = apply_morph_slider_values(base, [x_delta], {"x": 100.0})
        finally:
            morph_sliders._apply_native_morph_slider_values = original  # type: ignore[assignment]

        self.assertIs(native_result, result)
        self.assertEqual(1, len(calls))

    def test_build_morph_delta_returns_native_result_before_python_loop(self) -> None:
        base = _mesh()
        target = _mesh([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)])
        native_deltas = (((1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 0.0)),)
        calls: list[object] = []
        original_native = morph_sliders._build_native_morph_delta
        original_validate = morph_sliders.validate_morph_target

        def fake_native(base_mesh: ParsedMesh, target_mesh: ParsedMesh) -> tuple[tuple[tuple[float, float, float], ...], ...]:
            calls.append((base_mesh, target_mesh))
            return native_deltas

        def fail_validate(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("python morph target validation should stay fallback-only on native success")

        try:
            morph_sliders._build_native_morph_delta = fake_native  # type: ignore[assignment]
            morph_sliders.validate_morph_target = fail_validate  # type: ignore[assignment]
            delta = build_morph_delta(base, target, "native")
        finally:
            morph_sliders._build_native_morph_delta = original_native  # type: ignore[assignment]
            morph_sliders.validate_morph_target = original_validate  # type: ignore[assignment]

        self.assertEqual(native_deltas, delta.deltas)
        self.assertEqual(1, len(calls))

    def test_native_morph_post_edit_delta_bridge_uses_mesh_core_binary_payloads(self) -> None:
        working = _mesh([(2.0, 3.0, 4.0), (5.0, 6.0, 7.0), (0.0, 0.0, 1.0)])
        slider = _mesh([(1.0, 1.0, 1.0), (3.0, 2.0, 1.0), (0.0, 0.0, 0.0)])
        expected = [(1.0, 2.0, 3.0), (2.0, 4.0, 6.0), (0.0, 0.0, 1.0)]

        def native_job(_binary: Path, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            self.assertEqual("morph-post-edit-delta-json", command)
            items = payload["submeshes"]
            self.assertIsInstance(items, list)
            item = items[0]  # type: ignore[index]
            self.assertIn("working_vertices_binary", item)
            self.assertIn("slider_vertices_binary", item)
            self.assertNotIn("working_vertices", item)
            self.assertNotIn("slider_vertices", item)
            descriptor = mesh_native_core._write_vec3_binary_payload(  # type: ignore[attr-defined]
                Path(str(item["deltas_output_path"])),
                expected,
            )
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "morph_post_edit_delta",
                "submeshes": [{"index": 0, "vertex_count": 3, "deltas_binary": descriptor}],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            result = mesh_native_core.build_native_morph_post_edit_deltas(working, slider)

        self.assertEqual([expected], result)

    def test_native_morph_post_edit_delta_bridge_preserves_compact_zero_report(self) -> None:
        working = _mesh([(1.0, 1.0, 1.0), (2.0, 2.0, 2.0)])
        slider = _mesh([(1.0, 1.0, 1.0), (2.0, 2.0, 2.0)])

        def native_job(_binary: Path, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            self.assertEqual("morph-post-edit-delta-json", command)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "morph_post_edit_delta",
                "submeshes": [{"index": 0, "vertex_count": 2, "zero_delta": True, "deltas_binary": None}],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            result = mesh_native_core.build_native_morph_post_edit_deltas(working, slider)

        self.assertEqual([[]], result)

    def test_native_morph_post_edit_delta_bridge_streams_vertex_sidecars_without_tuple_copy(self) -> None:
        working_vertices = CountingSequence([(2.0, 3.0, 4.0), (5.0, 6.0, 7.0), (0.0, 0.0, 1.0)])
        slider_vertices = CountingSequence([(1.0, 1.0, 1.0), (3.0, 2.0, 1.0), (0.0, 0.0, 0.0)])
        working = _mesh(submeshes=[SubMesh(vertices=working_vertices, faces=[(0, 1, 2)])])  # type: ignore[arg-type]
        slider = _mesh(submeshes=[SubMesh(vertices=slider_vertices, faces=[(0, 1, 2)])])  # type: ignore[arg-type]
        expected = [(1.0, 2.0, 3.0), (2.0, 4.0, 6.0), (0.0, 0.0, 1.0)]

        def native_job(_binary: Path, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            self.assertEqual("morph-post-edit-delta-json", command)
            items = payload["submeshes"]
            self.assertIsInstance(items, list)
            item = items[0]  # type: ignore[index]
            self.assertEqual(3, item["working_vertices_binary"]["count"])  # type: ignore[index]
            self.assertEqual(3, item["slider_vertices_binary"]["count"])  # type: ignore[index]
            self.assertEqual(1, working_vertices.iterations)
            self.assertEqual(1, slider_vertices.iterations)
            descriptor = mesh_native_core._write_vec3_binary_payload(  # type: ignore[attr-defined]
                Path(str(item["deltas_output_path"])),
                expected,
            )
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "morph_post_edit_delta",
                "submeshes": [{"index": 0, "vertex_count": 3, "deltas_binary": descriptor}],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            result = mesh_native_core.build_native_morph_post_edit_deltas(working, slider)

        self.assertEqual([expected], result)
        self.assertEqual(1, working_vertices.iterations)
        self.assertEqual(1, slider_vertices.iterations)

    def test_native_morph_target_delta_bridge_uses_mesh_core_binary_payloads(self) -> None:
        base = _mesh()
        target = _mesh([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)])
        expected = [(1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 0.0)]

        def native_job(_binary: Path, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            self.assertEqual("morph-target-delta-json", command)
            items = payload["submeshes"]
            self.assertIsInstance(items, list)
            item = items[0]  # type: ignore[index]
            for key in ("base_vertices_binary", "target_vertices_binary", "base_faces_binary", "target_faces_binary"):
                self.assertIn(key, item)
            self.assertNotIn("base_vertices", item)
            self.assertNotIn("target_vertices", item)
            descriptor = mesh_native_core._write_vec3_binary_payload(  # type: ignore[attr-defined]
                Path(str(item["deltas_output_path"])),
                expected,
            )
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "morph_target_delta",
                "submeshes": [{"index": 0, "vertex_count": 3, "deltas_binary": descriptor}],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            result = mesh_native_core.build_native_morph_target_delta(base, target)

        self.assertEqual((tuple(expected),), result)

    def test_import_body_slider_profile_reads_target_mesh_and_language_label(self) -> None:
        base = _mesh()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pack = root / "Body Slider Pro"
            target_dir = pack / "target_mesh" / "damiane"
            target_dir.mkdir(parents=True)
            language_dir = pack / "language"
            language_dir.mkdir()
            (language_dir / "en.json").write_text('{"slider_wide_body": "Wide Body"}', encoding="utf-8")
            _write_obj(
                target_dir / "wide_body.obj",
                [(0.5, 0.0, 0.0), (1.5, 0.0, 0.0), (0.5, 1.0, 0.0)],
            )
            output_root = root / "profiles"

            profile = import_body_slider_profile(pack, base, "character/model/test.pac", output_root)
            loaded = load_morph_slider_profiles(output_root, base, "character/model/test.pac")
            copied_target_exists = (loaded[0].root_path / loaded[0].sliders[0].target_path).is_file()

        self.assertEqual("Body Slider Pro - damiane", profile.name)
        self.assertEqual(1, len(loaded))
        self.assertEqual("Wide Body", loaded[0].sliders[0].label)
        self.assertTrue(copied_target_exists)

    def test_region_volume_delta_supports_positive_negative_zero_feather_and_multi_submesh(self) -> None:
        base = _mesh(
            submeshes=[
                _submesh(
                    name="body",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                ),
                _submesh(
                    name="extra",
                    vertices=[(0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0)],
                    faces=[(0, 1, 2)],
                ),
            ]
        )

        delta = build_region_volume_delta(base, {0: {0}, 1: {1}}, 0.25, 1, slider_id="volume")

        grown = apply_morph_slider_values(base, [delta], {"volume": 100.0})
        self.assertAlmostEqual(0.25, grown.submeshes[0].vertices[0][2])
        self.assertAlmostEqual(0.125, grown.submeshes[0].vertices[1][2])
        self.assertAlmostEqual(1.25, grown.submeshes[1].vertices[1][2])

        shrunk = apply_morph_slider_values(base, [delta], {"volume": -100.0})
        self.assertAlmostEqual(-0.25, shrunk.submeshes[0].vertices[0][2])

        reset = apply_morph_slider_values(base, [delta], {"volume": 0.0})
        self.assertEqual(base.submeshes[0].vertices, reset.submeshes[0].vertices)

    def test_region_volume_delta_returns_native_result_before_python_loop(self) -> None:
        base = _mesh()
        native_deltas = (
            (
                (0.0, 0.0, 0.5),
                (0.0, 0.0, 0.25),
                (0.0, 0.0, 0.0),
            ),
        )
        calls: list[object] = []
        original_native = morph_sliders._build_native_region_volume_delta
        original_feather = morph_sliders._feathered_selection_weights

        def fake_native(base_mesh: ParsedMesh, selection: object, amount: object, feather: object) -> tuple[tuple[tuple[float, float, float], ...], ...]:
            calls.append((base_mesh, selection, amount, feather))
            return native_deltas

        def fail_python_weights(*_args: object, **_kwargs: object) -> dict[int, float]:
            raise AssertionError("python region-volume weights should stay fallback-only")

        try:
            morph_sliders._build_native_region_volume_delta = fake_native  # type: ignore[assignment]
            morph_sliders._feathered_selection_weights = fail_python_weights  # type: ignore[assignment]
            delta = build_region_volume_delta(base, {0: {0, 1}}, 0.5, 2, slider_id="volume")
        finally:
            morph_sliders._build_native_region_volume_delta = original_native  # type: ignore[assignment]
            morph_sliders._feathered_selection_weights = original_feather  # type: ignore[assignment]

        self.assertEqual(native_deltas, delta.deltas)
        self.assertEqual("volume", delta.slider_id)
        self.assertEqual(1, len(calls))

    def test_region_volume_python_fallback_does_not_clone_full_mesh_for_normals(self) -> None:
        base = _mesh()
        with (
            patch.dict(os.environ, {"CDMW_DISABLE_NATIVE_MESH_CORE": "1"}),
            patch.object(morph_sliders, "_build_native_region_volume_delta", return_value=None),
            patch.object(morph_sliders, "clone_mesh_for_editing", side_effect=AssertionError("clone blocked")),
        ):
            delta = build_region_volume_delta(base, {0: {0, 1}}, 0.5, 1, slider_id="volume")

        self.assertEqual("volume", delta.slider_id)
        self.assertEqual(1, len(delta.deltas))

    def test_native_morph_fallback_blocks_python_hot_paths(self) -> None:
        base = _mesh()
        target = _mesh([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)])
        delta = morph_sliders.MeshMorphSliderDelta(
            slider_id="x",
            label="X",
            deltas=(((1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 0.0)),),
        )

        with patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True):
            mesh_native_core.clear_native_mesh_core_fallback_counts()
            with (
                patch.object(morph_sliders, "_apply_native_morph_slider_values", return_value=None),
                patch.object(morph_sliders, "clone_mesh_for_editing", side_effect=AssertionError("clone blocked")),
            ):
                with self.assertRaisesRegex(RuntimeError, "Python morph fallback was blocked"):
                    apply_morph_slider_values(base, [delta], {"x": 100.0})
            self.assertEqual("morph_apply.blocked", mesh_native_core.native_mesh_core_fallback_events()[-1]["operation"])

            mesh_native_core.clear_native_mesh_core_fallback_counts()
            with (
                patch.object(morph_sliders, "_build_native_morph_delta", return_value=None),
                patch.object(morph_sliders, "validate_morph_target", side_effect=AssertionError("validate blocked")),
            ):
                with self.assertRaisesRegex(RuntimeError, "Python morph fallback was blocked"):
                    build_morph_delta(base, target, "x")
            self.assertEqual(
                "morph_target_delta.blocked",
                mesh_native_core.native_mesh_core_fallback_events()[-1]["operation"],
            )

            mesh_native_core.clear_native_mesh_core_fallback_counts()
            with (
                patch.object(morph_sliders, "_build_native_region_volume_delta", return_value=None),
                patch.object(morph_sliders, "clone_mesh_for_editing", side_effect=AssertionError("clone blocked")),
            ):
                with self.assertRaisesRegex(RuntimeError, "Python morph fallback was blocked"):
                    build_region_volume_delta(base, {0: {0, 1}}, 0.5, 1, slider_id="volume")
            self.assertEqual(
                "region_volume_delta.blocked",
                mesh_native_core.native_mesh_core_fallback_events()[-1]["operation"],
            )
        mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_region_volume_profile_saves_loads_and_applies(self) -> None:
        base = _mesh()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "profiles"
            profile = create_region_volume_slider_profile(
                base,
                "character/model/test.pac",
                output_root,
                {0: {0, 1, 2}},
                name="thicker",
                amount=0.5,
                feather=0,
            )
            loaded = load_morph_slider_profiles(output_root, base, "character/model/test.pac")
            delta = load_morph_slider_delta(base, loaded[0], loaded[0].sliders[0])
            morphed = apply_morph_slider_values(base, [delta], {"thicker": 100.0})

        self.assertEqual(profile.name, loaded[0].name)
        self.assertEqual("region_volume", loaded[0].sliders[0].slider_type)
        self.assertAlmostEqual(0.5, morphed.submeshes[0].vertices[0][2])

    def test_slider_modified_mesh_flows_through_edited_source_mesh_option(self) -> None:
        original = _mesh()
        replacement = _mesh()
        target = _mesh([(0.25, 0.0, 0.0), (1.25, 0.0, 0.0), (0.25, 1.0, 0.0)])
        delta = build_morph_delta(replacement, target, "offset")
        edited = apply_morph_slider_values(replacement, [delta], {"offset": 100.0})

        effective = effective_static_replacement_source_mesh(
            original,
            replacement,
            StaticMeshReplacementOptions(edited_source_mesh=edited),
        )

        self.assertEqual(target.submeshes[0].vertices, effective.submeshes[0].vertices)


if __name__ == "__main__":
    unittest.main()
