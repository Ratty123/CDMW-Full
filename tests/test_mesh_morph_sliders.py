from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
