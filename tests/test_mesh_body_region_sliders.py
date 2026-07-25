from __future__ import annotations

import math
import unittest

from cdmw.domain.mesh.body_region_falloff import smooth_body_region_weights
from cdmw.domain.mesh.body_region_sliders import (
    DEFAULT_BODY_REGION_SLIDER_TEMPLATES,
    BodyRegionSliderTemplate,
    build_region_slider_definitions,
    build_region_slider_profile,
)
from cdmw.domain.mesh.body_regions import build_body_region_map
from cdmw.domain.mesh.morph import (
    MESH_MORPH_RULES,
    MeshMorphRule,
    generate_procedural_morph_fields,
    mesh_morph_driver_topology_fingerprint,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

from tests.test_mesh_body_regions import FakeBone, FakeSkeleton


def _limb_mesh() -> ParsedMesh:
    """A tube down -Y: thigh on top, calf below, so the axis runs down the limb."""

    submesh = SubMesh(name="limb")
    rings = 8
    for ring in range(rings):
        height = 1.0 - (ring * 0.1)
        for step in range(4):
            angle = step * math.pi / 2.0
            submesh.vertices.append((0.05 * math.cos(angle), height, 0.05 * math.sin(angle)))
            submesh.bone_indices.append((1 if ring < 4 else 2,))
            submesh.bone_weights.append((1.0,))
    for ring in range(rings - 1):
        for step in range(4):
            a = ring * 4 + step
            b = ring * 4 + ((step + 1) % 4)
            submesh.faces.append((a, b, a + 4))
            submesh.faces.append((b, b + 4, a + 4))
    submesh.vertex_count = len(submesh.vertices)
    submesh.face_count = len(submesh.faces)
    mesh = ParsedMesh(format="pac", submeshes=[submesh], has_bones=True)
    mesh.total_vertices = submesh.vertex_count
    mesh.total_faces = submesh.face_count
    return mesh


def _limb_skeleton() -> FakeSkeleton:
    return FakeSkeleton(
        [
            FakeBone(0, "Bip01_Pelvis", -1, (0.0, 1.1, 0.0)),
            FakeBone(1, "Bip01_L_Thigh", 0, (0.0, 1.0, 0.0)),
            FakeBone(2, "Bip01_L_Calf", 1, (0.0, 0.6, 0.0)),
            FakeBone(3, "Bip01_L_Foot", 2, (0.0, 0.3, 0.0)),
        ]
    )


def _region_map(mesh: ParsedMesh):
    return build_body_region_map(mesh, _limb_skeleton())


def _peak(mesh, definition) -> float:
    fields = generate_procedural_morph_fields(mesh, definition)
    return max(
        (math.sqrt(sum(component * component for component in delta)) for field in fields for delta in field.deltas),
        default=0.0,
    )


class RadiusRuleTests(unittest.TestCase):
    def test_radius_is_a_registered_rule(self) -> None:
        self.assertIn("radius", MESH_MORPH_RULES)
        MeshMorphRule(kind="radius", axis="y", amount=0.1)

    def test_radius_scales_with_distance_from_the_axis_but_volume_does_not(self) -> None:
        """The reason `radius` exists.

        `volume` pushes every vertex the same absolute distance, so a wide part
        and a narrow part grow by the same millimetres. `radius` grows both by
        the same proportion, which is what a Size slider should mean.
        """

        mesh = _limb_mesh()
        # Widen the top ring so the limb has two different radii.
        for index in range(4):
            x, y, z = mesh.submeshes[0].vertices[index]
            mesh.submeshes[0].vertices[index] = (x * 3.0, y, z * 3.0)
        region = _region_map(mesh).region("thigh_l")

        radius_delta = _delta_by_vertex(mesh, region, "radius")
        volume_delta = _delta_by_vertex(mesh, region, "volume")
        wide, narrow = radius_delta[0], radius_delta[12]
        self.assertGreater(wide, narrow * 2.0)
        self.assertAlmostEqual(volume_delta[0], volume_delta[12], places=6)


def _delta_by_vertex(mesh, region, rule_kind: str) -> dict[int, float]:
    definition = build_region_slider_definitions(
        region,
        (BodyRegionSliderTemplate("probe", "Probe", rule_kind, "y", 0.5),),
    )[0]
    lengths: dict[int, float] = {}
    for field in generate_procedural_morph_fields(mesh, definition):
        for vertex_index, delta in zip(field.vertex_indices, field.deltas):
            lengths[vertex_index] = math.sqrt(sum(component * component for component in delta))
    return lengths


class RegionSliderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mesh = _limb_mesh()
        self.region_map = _region_map(self.mesh)

    def test_every_template_becomes_a_slider(self) -> None:
        region = self.region_map.region("thigh_l")
        definitions = build_region_slider_definitions(region)
        self.assertEqual(len(definitions), len(DEFAULT_BODY_REGION_SLIDER_TEMPLATES))
        self.assertEqual(definitions[0].definition_id, "thigh_l_size")
        self.assertEqual(definitions[0].label, "Thigh (Left) Size")
        self.assertEqual(definitions[0].category, "Legs")

    def test_sliders_inherit_the_region_pivot_and_axis(self) -> None:
        region = self.region_map.region("thigh_l")
        definition = build_region_slider_definitions(region)[0]
        self.assertEqual(definition.pivot, region.axis.origin)
        # Y of the basis is the bone axis, which runs down the limb.
        self.assertLess(definition.local_basis[1][1], -0.5)

    def test_sliders_only_move_their_own_region(self) -> None:
        region = self.region_map.region("thigh_l")
        thigh_vertices = {
            vertex_index for part in region.parts for vertex_index in part.vertex_indices
        }
        definition = build_region_slider_definitions(region)[0]
        moved = {
            vertex_index
            for field in generate_procedural_morph_fields(self.mesh, definition)
            for vertex_index in field.vertex_indices
        }
        self.assertTrue(moved)
        self.assertTrue(moved <= thigh_vertices)

    def test_falloff_carries_into_the_slider(self) -> None:
        """A feathered region must produce a feathered deformation."""

        soft = smooth_body_region_weights(self.mesh, self.region_map, band=0.15)
        definition = build_region_slider_definitions(soft.region("thigh_l"))[0]
        lengths = [
            math.sqrt(sum(component * component for component in delta))
            for field in generate_procedural_morph_fields(self.mesh, definition)
            for delta in field.deltas
        ]
        hard = build_region_slider_definitions(self.region_map.region("thigh_l"))[0]
        hard_lengths = [
            math.sqrt(sum(component * component for component in delta))
            for field in generate_procedural_morph_fields(self.mesh, hard)
            for delta in field.deltas
        ]
        # Feathering reaches more vertices, and the extra ones move less.
        self.assertGreater(len(lengths), len(hard_lengths))
        self.assertGreater(max(lengths), min(lengths) * 2.0)

    def test_profile_fingerprint_matches_what_activation_checks(self) -> None:
        """The service validates against the definitions' submeshes only.

        Carrying the whole map's fingerprint instead would make every
        region-scoped profile fail to activate.
        """

        profile = build_region_slider_profile(self.mesh, self.region_map)
        self.assertEqual(
            profile.topology_fingerprint,
            mesh_morph_driver_topology_fingerprint(self.mesh, profile.definitions),
        )
        scoped = build_region_slider_profile(self.mesh, self.region_map, region_ids=("thigh_l",))
        self.assertEqual(
            scoped.topology_fingerprint,
            mesh_morph_driver_topology_fingerprint(self.mesh, scoped.definitions),
        )
        expected = len(self.region_map.populated_regions) * len(DEFAULT_BODY_REGION_SLIDER_TEMPLATES)
        self.assertEqual(len(profile.definitions), expected)
        identifiers = [definition.definition_id for definition in profile.definitions]
        self.assertEqual(len(set(identifiers)), len(identifiers))

    def test_profile_can_be_scoped_to_one_region(self) -> None:
        profile = build_region_slider_profile(self.mesh, self.region_map, region_ids=("thigh_l",))
        self.assertTrue(
            all(definition.definition_id.startswith("thigh_l_") for definition in profile.definitions)
        )
        self.assertIn("thigh_l", profile.profile_id)

    def test_profile_ids_differ_between_bodies(self) -> None:
        other = _limb_mesh()
        other.submeshes[0].faces.pop()
        other.submeshes[0].face_count = len(other.submeshes[0].faces)
        self.assertNotEqual(
            build_region_slider_profile(self.mesh, self.region_map).profile_id,
            build_region_slider_profile(other, _region_map(other)).profile_id,
        )

    def test_empty_region_yields_no_sliders(self) -> None:
        empty = self.region_map.region("foot_l")
        if empty is not None:
            self.assertEqual(build_region_slider_definitions(empty), ())

    def test_template_rejects_an_unknown_rule(self) -> None:
        with self.assertRaises(ValueError):
            BodyRegionSliderTemplate("bad", "Bad", "not_a_rule")
        with self.assertRaises(ValueError):
            BodyRegionSliderTemplate("bad", "Bad", "radius", axis="w")
