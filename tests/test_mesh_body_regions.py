from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import dump_body_region_map

from cdmw.domain.mesh.body_regions import (
    DEFAULT_BODY_REGION_RULES,
    BodyRegionRule,
    body_region_local_basis,
    body_region_morph_selection,
    bone_side,
    build_body_region_map,
    classify_bone,
    dominant_region_by_vertex,
    sided_region_id,
)
from cdmw.domain.mesh.morph import (
    MeshMorphDefinition,
    MeshMorphRule,
    generate_procedural_morph_fields,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


class FakeBone:
    def __init__(self, index: int, name: str, parent_index: int = -1, position=(0.0, 0.0, 0.0)) -> None:
        self.index = index
        self.name = name
        self.parent_index = parent_index
        self.position = position
        self.bind_matrix = (
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            position[0], position[1], position[2], 1.0,
        )


class FakeSkeleton:
    def __init__(self, bones) -> None:
        self.bones = list(bones)
        self.bone_count = len(self.bones)
        self.path = "fake.pab"


def _leg_skeleton() -> FakeSkeleton:
    return FakeSkeleton(
        [
            FakeBone(0, "Bip01_Pelvis", -1, (0.0, 1.0, 0.0)),
            FakeBone(1, "Bip01_L_Thigh", 0, (0.1, 1.0, 0.0)),
            FakeBone(2, "Bip01_L_Calf", 1, (0.1, 0.5, 0.0)),
            FakeBone(3, "Bip01_L_Foot", 2, (0.1, 0.1, 0.0)),
            FakeBone(4, "Bip01_R_Thigh", 0, (-0.1, 1.0, 0.0)),
            FakeBone(5, "Bip01_R_Calf", 4, (-0.1, 0.5, 0.0)),
        ]
    )


def _mesh_with_weights(rows) -> ParsedMesh:
    """rows = [((bone indices), (bone weights))] — one entry per vertex."""

    submesh = SubMesh(name="body")
    for index, (indices, weights) in enumerate(rows):
        submesh.vertices.append((float(index), 0.0, 0.0))
        submesh.bone_indices.append(tuple(indices))
        submesh.bone_weights.append(tuple(weights))
    submesh.vertex_count = len(submesh.vertices)
    for start in range(0, max(0, len(rows) - 2)):
        submesh.faces.append((start, start + 1, start + 2))
    submesh.face_count = len(submesh.faces)
    mesh = ParsedMesh(format="pac", submeshes=[submesh], has_bones=True)
    mesh.total_vertices = submesh.vertex_count
    mesh.total_faces = submesh.face_count
    return mesh


class BoneClassificationTests(unittest.TestCase):
    def test_side_uses_whole_tokens_only(self) -> None:
        self.assertEqual(bone_side("Bip01_L_Thigh"), "left")
        self.assertEqual(bone_side("Bip01_R_Calf"), "right")
        self.assertEqual(bone_side("Left_Hand"), "left")
        # A leading 'r'/'l' inside a word must not be read as a side.
        self.assertEqual(bone_side("Ribcage"), "center")
        self.assertEqual(bone_side("Bip01_Spine1"), "center")

    def test_longest_pattern_wins_over_shorter_overlap(self) -> None:
        forearm, _pattern = classify_bone("Bip01_L_Forearm")
        self.assertIsNotNone(forearm)
        self.assertEqual(forearm.region_id, "forearm")
        upper, _pattern = classify_bone("Bip01_L_UpperArm")
        self.assertEqual(upper.region_id, "upper_arm")
        # "spine1" must outrank "spine".
        upper_torso, _pattern = classify_bone("Spine1_B")
        self.assertEqual(upper_torso.region_id, "spine_upper")
        lower_torso, _pattern = classify_bone("Spine0_B")
        self.assertEqual(lower_torso.region_id, "spine_lower")

    def test_priority_outranks_pattern_length(self) -> None:
        # "breast" would otherwise be shadowed by a longer torso pattern.
        rules = (
            BodyRegionRule("spine_upper", "Upper Torso", "Torso", ("l_breastbone",), sided=False),
            BodyRegionRule("breast", "Breast", "Torso", ("breast",), priority=10),
        )
        rule, _pattern = classify_bone("L_Breastbone", rules)
        self.assertEqual(rule.region_id, "breast")

    def test_unknown_bone_matches_nothing(self) -> None:
        rule, pattern = classify_bone("Prop_Attach_07")
        self.assertIsNone(rule)
        self.assertEqual(pattern, "")


class RegionMapTests(unittest.TestCase):
    def test_weights_split_across_regions_and_normalize(self) -> None:
        # Vertex 0 sits fully on the thigh, vertex 1 straddles the knee, and
        # the raw weights deliberately do not sum to 1 so normalization shows.
        mesh = _mesh_with_weights(
            [
                ((1,), (0.5,)),
                ((1, 2), (0.25, 0.25)),
                ((2,), (0.8,)),
            ]
        )
        region_map = build_body_region_map(mesh, _leg_skeleton(), primary_influence_only=False)

        thigh = region_map.region("thigh_l")
        calf = region_map.region("calf_l")
        self.assertIsNotNone(thigh)
        self.assertIsNotNone(calf)
        self.assertEqual(thigh.parts[0].vertex_indices, (0, 1))
        self.assertAlmostEqual(thigh.parts[0].weights[0], 1.0)
        self.assertAlmostEqual(thigh.parts[0].weights[1], 0.5)
        self.assertEqual(calf.parts[0].vertex_indices, (1, 2))
        self.assertAlmostEqual(calf.parts[0].weights[0], 0.5)
        self.assertAlmostEqual(calf.parts[0].weights[1], 1.0)

    def test_region_weights_are_a_partition_of_unity(self) -> None:
        mesh = _mesh_with_weights(
            [
                ((1, 2), (0.7, 0.3)),
                ((0, 1), (0.4, 0.6)),
                ((2, 3), (0.5, 0.5)),
            ]
        )
        region_map = build_body_region_map(mesh, _leg_skeleton(), primary_influence_only=False)
        totals: dict[int, float] = {}
        for region in region_map.regions:
            for part in region.parts:
                for vertex_index, weight in zip(part.vertex_indices, part.weights):
                    totals[vertex_index] = totals.get(vertex_index, 0.0) + weight
        self.assertEqual(sorted(totals), [0, 1, 2])
        for vertex_index, total in totals.items():
            self.assertAlmostEqual(total, 1.0, msg=f"vertex {vertex_index} does not sum to 1")

    def test_sides_are_separated_into_distinct_regions(self) -> None:
        mesh = _mesh_with_weights([((1,), (1.0,)), ((4,), (1.0,))])
        region_map = build_body_region_map(mesh, _leg_skeleton())
        left = region_map.region("thigh_l")
        right = region_map.region("thigh_r")
        self.assertEqual(left.parts[0].vertex_indices, (0,))
        self.assertEqual(right.parts[0].vertex_indices, (1,))
        self.assertEqual(left.side, "left")
        self.assertEqual(right.side, "right")

    def test_unskinned_and_unmapped_are_reported_not_dropped(self) -> None:
        skeleton = FakeSkeleton([FakeBone(0, "Prop_Attach_07"), FakeBone(1, "Bip01_L_Thigh")])
        mesh = _mesh_with_weights([((0,), (1.0,)), ((), ()), ((1,), (1.0,))])
        region_map = build_body_region_map(mesh, skeleton, primary_influence_only=False)

        self.assertEqual(region_map.unskinned_vertex_count, 1)
        self.assertEqual(region_map.skinned_vertex_count, 2)
        self.assertIn("Prop_Attach_07", region_map.unmapped_bone_names)
        # One of two skinned vertices rides an unmapped bone.
        self.assertAlmostEqual(region_map.unmapped_weight_fraction, 0.5)
        self.assertTrue(region_map.diagnostics)

    def test_missing_skeleton_reports_instead_of_raising(self) -> None:
        mesh = _mesh_with_weights([((1,), (1.0,))])
        region_map = build_body_region_map(mesh, None)
        self.assertEqual(region_map.populated_regions, ())
        self.assertTrue(any("skeleton" in message.lower() for message in region_map.diagnostics))

    def test_axis_points_down_the_bone_chain(self) -> None:
        mesh = _mesh_with_weights([((1,), (1.0,)), ((2,), (1.0,))])
        region_map = build_body_region_map(mesh, _leg_skeleton())
        thigh = region_map.region("thigh_l")
        # Thigh runs from its own joint toward the knee, i.e. straight down -Y.
        self.assertEqual(thigh.axis.source, "child_joint")
        self.assertAlmostEqual(thigh.axis.direction[1], -1.0, places=6)
        self.assertAlmostEqual(thigh.axis.length, 0.5, places=6)
        self.assertAlmostEqual(thigh.axis.origin[0], 0.1, places=6)

    def test_dominant_region_resolves_each_vertex_once(self) -> None:
        mesh = _mesh_with_weights([((1, 2), (0.9, 0.1)), ((1, 2), (0.1, 0.9))])
        region_map = build_body_region_map(mesh, _leg_skeleton(), primary_influence_only=False)
        dominant = dominant_region_by_vertex(region_map)
        self.assertEqual(dominant[(0, 0)], "thigh_l")
        self.assertEqual(dominant[(0, 1)], "calf_l")

    def test_minimum_weight_drops_negligible_influence(self) -> None:
        mesh = _mesh_with_weights([((1, 2), (0.999, 0.001))])
        region_map = build_body_region_map(
            mesh, _leg_skeleton(), minimum_weight=0.01, primary_influence_only=False
        )
        self.assertEqual(region_map.region("thigh_l").vertex_count, 1)
        self.assertEqual(region_map.region("calf_l").vertex_count, 0)

    def test_topology_fingerprint_is_stable_across_positions(self) -> None:
        rows = [((1,), (1.0,)), ((1,), (1.0,)), ((2,), (1.0,))]
        first = build_body_region_map(_mesh_with_weights(rows), _leg_skeleton())
        moved = _mesh_with_weights(rows)
        moved.submeshes[0].vertices[0] = (99.0, 99.0, 99.0)
        second = build_body_region_map(moved, _leg_skeleton())
        self.assertEqual(first.topology_fingerprint, second.topology_fingerprint)


class PaletteAndPrimaryInfluenceTests(unittest.TestCase):
    def test_palette_maps_slots_onto_bones(self) -> None:
        # Slots 0/1 are per-mesh tokens; the palette says they mean bones 4/2,
        # so the vertices must land on the right thigh and left calf.
        mesh = _mesh_with_weights([((0,), (1.0,)), ((1,), (1.0,))])
        region_map = build_body_region_map(mesh, _leg_skeleton(), bone_palette=(4, 2))
        self.assertEqual(region_map.region("thigh_r").parts[0].vertex_indices, (0,))
        self.assertEqual(region_map.region("calf_l").parts[0].vertex_indices, (1,))
        # Without the palette the same slots would read as bones 0 and 1.
        direct = build_body_region_map(mesh, _leg_skeleton())
        self.assertEqual(direct.region("pelvis").parts[0].vertex_indices, (0,))

    def test_unresolved_palette_claims_nothing(self) -> None:
        """An empty palette means unresolved, which must not fall through.

        Treating the slots as bone indices instead would label real anatomy
        with whatever bone happened to share the number.
        """

        mesh = _mesh_with_weights([((1,), (1.0,)), ((2,), (1.0,))])
        region_map = build_body_region_map(mesh, _leg_skeleton(), bone_palette=())
        self.assertEqual(region_map.populated_regions, ())
        self.assertTrue(any("palette" in message.lower() for message in region_map.diagnostics))

    def test_primary_influence_only_keeps_the_heaviest(self) -> None:
        mesh = _mesh_with_weights([((1, 2), (0.8, 0.2)), ((1, 2), (0.2, 0.8))])
        region_map = build_body_region_map(mesh, _leg_skeleton())
        thigh = region_map.region("thigh_l")
        calf = region_map.region("calf_l")
        self.assertEqual(thigh.parts[0].vertex_indices, (0,))
        self.assertEqual(calf.parts[0].vertex_indices, (1,))
        # Each vertex belongs to exactly one region, at full strength.
        self.assertAlmostEqual(thigh.parts[0].weights[0], 1.0)
        self.assertAlmostEqual(calf.parts[0].weights[0], 1.0)
        self.assertTrue(any("falloff" in message for message in region_map.diagnostics))


class BipedNamingTests(unittest.TestCase):
    """The rule table against the real Crimson Desert Biped bone names."""

    def test_real_bone_names_land_in_the_expected_regions(self) -> None:
        expected = {
            "Bip01 L Thigh": "thigh_l",
            "Bip01 R Calf_Sub": "calf_r",
            "Bip01 L Toe_Sub": "toe_l",
            "Bip01 R Foot": "foot_r",
            "Bip01 L ThighTwist": "thigh_l",
            "Bip01 R ForeTwist01": "forearm_r",
            "Bip01 L UpArmTwist1": "upper_arm_l",
            "Bip01 R UpperFMuscle_sub": "upper_arm_r",
            "Bip01 L Elbow": "forearm_l",
            "Bip01 R Hip": "hip_r",
            "Bip01 Pelvis_Sub": "pelvis",
            "Bip01 Spine_Sub": "spine_lower",
            "Bip01 Spine2_Sub": "spine_upper",
            "Bip01 L Clavicle_Back2": "clavicle_l",
            "Bip01 R Finger22": "hand_r",
            "Bip01 Neck_Twist": "neck",
            "B_Ear_01_R": "ear_r",
            "B_Forehead_02_L": "head_l",
            "B_Gluteusmaximus_L_02": "glute_l",
        }
        for name, region_id in expected.items():
            rule, _pattern = classify_bone(name)
            self.assertIsNotNone(rule, f"{name} matched no rule")
            side = bone_side(name) if rule.sided else "center"
            self.assertEqual(sided_region_id(rule, side), region_id, f"{name} misrouted")

    def test_sided_chest_bones_are_breasts_not_torso(self) -> None:
        # Biped drives the breasts from "Chest" bones; routing them to the
        # upper torso would merge them into one unusable region.
        for name in ("Bip01 L Chest", "Bip01 R Chest_Muscle", "Bip01 R Chest Side"):
            rule, _pattern = classify_bone(name)
            self.assertEqual(rule.region_id, "breast", name)
        self.assertEqual(classify_bone("Bip01 Spine2")[0].region_id, "spine_upper")


class LocalBasisTests(unittest.TestCase):
    def _assert_orthonormal(self, basis) -> None:
        for axis in basis:
            self.assertAlmostEqual(sum(component * component for component in axis), 1.0, places=6)
        for first in range(3):
            for second in range(first + 1, 3):
                dot = sum(a * b for a, b in zip(basis[first], basis[second]))
                self.assertAlmostEqual(dot, 0.0, places=6)

    def test_basis_is_orthonormal_for_a_vertical_limb(self) -> None:
        region = build_body_region_map(
            _mesh_with_weights([((1,), (1.0,))]), _leg_skeleton()
        ).region("thigh_l")
        basis = body_region_local_basis(region)
        self._assert_orthonormal(basis)
        # The bone axis has to land on Y so a rule with axis="y" runs along it.
        self.assertAlmostEqual(basis[1][1], -1.0, places=6)

    def test_basis_stays_orthonormal_when_the_axis_is_near_x(self) -> None:
        # Exercises the helper-vector swap that avoids a degenerate cross product.
        skeleton = FakeSkeleton(
            [
                FakeBone(0, "Bip01_Pelvis", -1, (0.0, 1.0, 0.0)),
                FakeBone(1, "Bip01_L_Thigh", 0, (0.0, 1.0, 0.0)),
                FakeBone(2, "Bip01_L_Calf", 1, (1.0, 1.0, 0.0)),
            ]
        )
        region = build_body_region_map(
            _mesh_with_weights([((1,), (1.0,))]), skeleton
        ).region("thigh_l")
        self.assertAlmostEqual(region.axis.direction[0], 1.0, places=6)
        self._assert_orthonormal(body_region_local_basis(region))


class RegionDumpToolTests(unittest.TestCase):
    def test_obj_dump_colours_vertices_and_keeps_faces(self) -> None:
        mesh = _mesh_with_weights([((1,), (1.0,)), ((1,), (1.0,)), ((2,), (1.0,))])
        region_map = build_body_region_map(mesh, _leg_skeleton())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "regions.obj"
            dump_body_region_map._write_region_obj(target, mesh, region_map)
            text = target.read_text(encoding="utf-8")

        vertex_lines = [line for line in text.splitlines() if line.startswith("v ")]
        face_lines = [line for line in text.splitlines() if line.startswith("f ")]
        self.assertEqual(len(vertex_lines), 3)
        self.assertEqual(len(face_lines), len(mesh.submeshes[0].faces))
        # x y z r g b
        self.assertEqual(len(vertex_lines[0].split()), 7)
        # Thigh and calf vertices must not share a colour.
        self.assertNotEqual(vertex_lines[0].split()[4:], vertex_lines[2].split()[4:])

    def test_report_names_unmapped_bones(self) -> None:
        skeleton = FakeSkeleton([FakeBone(0, "Prop_Attach_07"), FakeBone(1, "Bip01_L_Thigh")])
        mesh = _mesh_with_weights([((0,), (1.0,)), ((1,), (1.0,))])
        report = "\n".join(
            dump_body_region_map._report_lines(build_body_region_map(mesh, skeleton))
        )
        self.assertIn("Prop_Attach_07", report)
        self.assertIn("thigh_l", report)


class MorphBridgeTests(unittest.TestCase):
    def test_region_feeds_a_procedural_morph_definition(self) -> None:
        mesh = _mesh_with_weights([((1,), (1.0,)), ((1, 2), (0.5, 0.5)), ((2,), (1.0,))])
        region_map = build_body_region_map(mesh, _leg_skeleton(), primary_influence_only=False)
        thigh = region_map.region("thigh_l")

        definition = MeshMorphDefinition(
            definition_id="thigh_l_size",
            label="Thigh Size (Left)",
            category=thigh.group,
            vertices=body_region_morph_selection(thigh),
            pivot=thigh.axis.origin,
            local_basis=body_region_local_basis(thigh),
            rule=MeshMorphRule(kind="volume", axis="y", amount=0.1),
        )
        fields = generate_procedural_morph_fields(mesh, definition)

        self.assertTrue(fields)
        moved = {index for sparse in fields for index in sparse.vertex_indices}
        # Vertex 2 belongs to the calf only, so the thigh slider must not move it.
        self.assertNotIn(2, moved)
        self.assertIn(0, moved)
