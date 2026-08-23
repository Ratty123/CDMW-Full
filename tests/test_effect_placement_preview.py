"""The effect placement preview: the anchor mesh, the scale delta, the tinted package, the dialog's numbers."""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.effect_placement_preview import (
    ANCHOR_TINT,
    BODY_TINT,
    EFFECT_ANCHOR_MATERIAL,
    EFFECT_ANCHOR_RADIUS,
    EFFECT_AXIS_MATERIALS,
    EFFECT_AXIS_TINTS,
    EFFECT_BODY_MATERIAL,
    EFFECT_REACH_MATERIAL,
    REACH_TINT,
    _tint_anchor_material,
    anchor_axis_triad,
    anchor_mesh,
    build_effect_placement_package,
    next_scale,
)


def _blade() -> ParsedMesh:
    vertices = [(-0.02, 0.0, -0.9), (0.02, 0.0, -0.9), (0.02, 0.0, 0.2), (-0.02, 0.0, 0.2)]
    faces = [(0, 1, 2), (0, 2, 3)]
    submesh = SubMesh(name="blade", material="steel", vertices=vertices, uvs=[(0.0, 0.0)] * 4, normals=[(0.0, 1.0, 0.0)] * 4, faces=faces, vertex_count=4, face_count=2)
    return ParsedMesh(path="blade.pac", format="pac", submeshes=[submesh], bbox_min=(-0.02, 0.0, -0.9), bbox_max=(0.02, 0.0, 0.2), total_vertices=4, total_faces=2, has_uvs=True)


class AnchorAndScaleTests(unittest.TestCase):
    def test_anchor_mesh_is_a_small_closed_octahedron_at_the_origin(self) -> None:
        mesh = anchor_mesh()
        self.assertEqual(len(mesh.submeshes), 1)
        anchor = mesh.submeshes[0]
        self.assertEqual(anchor.material, EFFECT_ANCHOR_MATERIAL)
        self.assertEqual(len(anchor.faces), 8)
        self.assertEqual(len(anchor.vertices), 24)
        self.assertEqual(len(anchor.normals), 24)
        r = EFFECT_ANCHOR_RADIUS
        self.assertEqual(mesh.bbox_min, (-r, -r, -r))
        self.assertEqual(mesh.bbox_max, (r, r, r))
        self.assertLess(r, 0.05, "a marker, not a box the size of the effect")
        # every face is a real triangle whose normal points away from the origin
        for face, normal in zip(anchor.faces, anchor.normals[::3]):
            self.assertEqual(len(set(face)), 3)
            a, b, c = (anchor.vertices[i] for i in face)
            centre = tuple((a[i] + b[i] + c[i]) / 3.0 for i in range(3))
            self.assertGreater(sum(normal[i] * centre[i] for i in range(3)), 0.0)
        self.assertEqual(anchor_mesh(0.0).bbox_max, (0.001, 0.001, 0.001), "a floor on the radius")

    def test_the_axis_triad_is_three_bars_along_the_positive_axes(self) -> None:
        """An octahedron is the same shape from every side, so without the triad a
        rotation is invisible on the anchor itself."""

        triad = anchor_axis_triad(0.02)
        self.assertEqual([bar.material for bar in triad], list(EFFECT_AXIS_MATERIALS))
        for axis, bar in enumerate(triad):
            self.assertTrue(bar.vertices, bar.material)
            far = max(vertex[axis] for vertex in bar.vertices)
            self.assertAlmostEqual(far, 0.02 * 3.2, places=3, msg="the bar runs out along its own axis")
            near = min(vertex[axis] for vertex in bar.vertices)
            self.assertGreaterEqual(near, -0.005, "and only the positive way, so + reads as +")
            for other in range(3):
                if other != axis:
                    self.assertLess(max(abs(vertex[other]) for vertex in bar.vertices), 0.02, "thin across")

    def test_next_scale_is_the_mean_delta_clamped(self) -> None:
        self.assertAlmostEqual(next_scale(0.5, (0.1, 0.1, 0.1)), 0.6)
        self.assertAlmostEqual(next_scale(0.5, (0.3, 0.0, 0.0)), 0.6)
        self.assertEqual(next_scale(0.5, (-2.0, -2.0, -2.0)), 0.01)
        self.assertEqual(next_scale(9.0, (5.0, 5.0, 5.0)), 10.0)
        self.assertEqual(next_scale(1.0, ()), 1.0)

    def test_the_anchor_material_becomes_opaque_orange(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "net_materials.json"
            path.write_text(json.dumps({"submeshes": [
                {"submesh_index": 0, "material": EFFECT_ANCHOR_MATERIAL, "alpha_mode": "blend", "opacity_factor": 0.2, "parameters": {"roughness": 0.5}},
                {"submesh_index": 1, "material": "steel", "alpha_mode": "opaque", "opacity_factor": 1.0, "parameters": {}},
            ]}), encoding="utf-8")
            _tint_anchor_material(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            anchor, steel = payload["submeshes"]
            self.assertEqual(anchor["alpha_mode"], "opaque")
            self.assertEqual(anchor["opacity_factor"], 1.0)
            self.assertTrue(anchor["double_sided"])
            self.assertEqual(anchor["parameters"]["base_tint_color"], [1.0, 0.45, 0.1])
            self.assertEqual(
                steel,
                {"submesh_index": 1, "material": "steel", "alpha_mode": "opaque", "opacity_factor": 1.0, "parameters": {}},
                "the item's canonical material row is byte-semantic authority",
            )
            # a missing file is left alone
            _tint_anchor_material(Path(folder) / "missing.json")


class PackageTests(unittest.TestCase):
    def test_the_item_is_drawn_as_itself_rather_than_as_the_overlay_wire(self) -> None:
        """Overlay comparison exists so a replacement can be read against the original, so
        the renderer skips the reference in the solid pass and draws it as a wire ghost.
        Here the reference is the item the effect is being placed on, so that convention
        left a sword nobody could see: the scene asks for it solid, and its materials
        carry a tint because the package builder leaves them without a base colour, which
        the renderer draws as a black body on a dark background."""

        if os.environ.get("CDMW_SKIP_DOTNET_PACKAGE_TESTS") == "1":
            self.skipTest("dotnet package tests skipped by request")
        with tempfile.TemporaryDirectory() as folder:
            preview = build_effect_placement_package(_blade(), (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), output_root=Path(folder))
            scene = json.loads((preview.package_dir / "dotnet_scene.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(scene["comparison_mode"], "overlay")
            self.assertEqual(scene["reference_draw"], "solid")
            materials = json.loads((preview.package_dir / "net_materials.json").read_text(encoding="utf-8"))
            tints = {
                str(item.get("material")): tuple(item.get("parameters", {}).get("base_tint_color", ()))
                for item in materials["submeshes"]
            }
            self.assertEqual(tints.get(EFFECT_ANCHOR_MATERIAL), ANCHOR_TINT)
            self.assertEqual(tints.get(EFFECT_REACH_MATERIAL), REACH_TINT)
            self.assertEqual(tints.get(EFFECT_BODY_MATERIAL), BODY_TINT)
            for material, tint in zip(EFFECT_AXIS_MATERIALS, EFFECT_AXIS_TINTS):
                self.assertEqual(tints.get(material), tint, f"{material} is one of the gizmo's own axis colours")
            item_materials = [
                name for name in tints
                if name not in (EFFECT_ANCHOR_MATERIAL, EFFECT_REACH_MATERIAL, EFFECT_BODY_MATERIAL) + EFFECT_AXIS_MATERIALS
            ]
            self.assertTrue(item_materials, "the item's own materials are in the package")
            for name in item_materials:
                self.assertEqual(tints[name], (), f"{name} must keep the canonical material contract")

    def test_the_package_puts_the_anchor_first_and_the_item_as_reference(self) -> None:
        if os.environ.get("CDMW_SKIP_DOTNET_PACKAGE_TESTS") == "1":
            self.skipTest("dotnet package tests skipped by request")
        with tempfile.TemporaryDirectory() as folder:
            preview = build_effect_placement_package(_blade(), (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), output_root=Path(folder))
            self.assertEqual(preview.box_submesh_index, 0)
            self.assertEqual(preview.item_submesh_count, 1)
            self.assertEqual((preview.box_min, preview.box_max), ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)), "the reach travels as numbers")
            scene = json.loads((preview.package_dir / "dotnet_scene.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(scene["comparison_mode"], "overlay")
            self.assertEqual(scene["interaction_mode"], "placement")
            self.assertEqual(scene["roles"]["replacement"], [0, 1, 2, 3, 4], "the anchor, the reach cage and the axis triad move together")
            self.assertEqual(preview.reach_submesh_index, 1, "the cage keeps the index the dialog hides by")
            self.assertEqual(scene["roles"]["original_reference"], [5, 6], "the item and the character follow the anchor's five")
            self.assertEqual(preview.body_submesh_index, 6)
            self.assertTrue(scene["gizmo"]["visible"])
            materials = json.loads((preview.package_dir / "net_materials.json").read_text(encoding="utf-8"))
            anchor = next(item for item in materials["submeshes"] if item["material"] == EFFECT_ANCHOR_MATERIAL)
            self.assertEqual(anchor["alpha_mode"], "opaque")
            # the scene frames the item, not the anchor: the anchor is tiny inside the item's bounds
            bounds = scene["bounds"]
            self.assertLess(bounds["min"][2], -0.8)

    def test_the_character_can_be_left_out(self) -> None:
        if os.environ.get("CDMW_SKIP_DOTNET_PACKAGE_TESTS") == "1":
            self.skipTest("dotnet package tests skipped by request")
        with tempfile.TemporaryDirectory() as folder:
            preview = build_effect_placement_package(
                _blade(), (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), output_root=Path(folder), include_body=False,
            )
            scene = json.loads((preview.package_dir / "dotnet_scene.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(scene["roles"]["original_reference"], [5])
            self.assertEqual(preview.body_submesh_index, -1)

    def test_a_reach_of_twenty_metres_does_not_become_the_size_of_the_world(self) -> None:
        """The builder frames on everything it is given, and the reach cage is one of the
        things it is given. An effect made for a boss reaches tens of metres, and the
        viewport reads the scene's extent as the size of the world: the camera opened on
        an empty box, the ground grid drew squares two metres wide, and the placement
        gizmo -- a fifth of the scene across -- put its handles off the edges of the view.
        The item and the character standing behind it are the subject whatever the effect
        does around them."""

        if os.environ.get("CDMW_SKIP_DOTNET_PACKAGE_TESTS") == "1":
            self.skipTest("dotnet package tests skipped by request")
        with tempfile.TemporaryDirectory() as folder:
            preview = build_effect_placement_package(
                _blade(), (-11.0, -10.0, -11.0), (11.0, 17.0, 11.0), output_root=Path(folder),
            )
            scene = json.loads((preview.package_dir / "dotnet_scene.json").read_text(encoding="utf-8-sig"))
            bounds = scene["bounds"]
            extent = max(bounds["max"][axis] - bounds["min"][axis] for axis in range(3))
            self.assertLess(extent, 3.0, "the frame holds the character and the item, not the reach")
            self.assertGreater(extent, 1.0, "the character is 1.75 m tall and stands in frame")
            self.assertAlmostEqual(scene["framing"]["extent"], extent, places=5)
            self.assertAlmostEqual(scene["grid"]["spacing"], extent / 10.0, places=5)
            # the reach itself still travels, as the numbers the dialog reads
            self.assertEqual(preview.box_max, (11.0, 17.0, 11.0))


def _fire_preview():
    from cdmw.core.effect_binary import decode_effect_binary
    from cdmw.core.effect_edit import emitter_layout_of
    from cdmw.services.effect_preview_model import build_effect_preview

    fixtures = Path(__file__).parent / "fixtures" / "effects"
    trail_path = "effect/binary__/emitter/cdem_last_fire_circle_trail_001a.paem"
    trail = decode_effect_binary((fixtures / "cdem_last_fire_circle_trail_001a.paem").read_bytes())
    effect = decode_effect_binary((fixtures / "fx_hit_common_fire_attach_a_loop.pae").read_bytes())
    return build_effect_preview("fx_hit_common_fire_attach_a_loop", effect, emitter_documents={trail_path: trail}, layouts={trail_path: emitter_layout_of(trail)})


class EffectPreviewInPackageTests(unittest.TestCase):
    def test_the_description_and_its_textures_are_written_beside_the_mesh(self) -> None:
        from cdmw.services.effect_placement_preview import EFFECT_PREVIEW_FILE, EFFECT_TEXTURE_DIR, write_effect_preview

        preview = _fire_preview()
        with tempfile.TemporaryDirectory() as folder:
            target, missing = write_effect_preview(Path(folder), preview, texture_reader=lambda path: b"DDS fake" if path.endswith("pafx_fire_003a_kjd.dds") else None)
            self.assertEqual(target.name, EFFECT_PREVIEW_FILE)
            self.assertEqual(missing, ())
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], 1)
            self.assertEqual(payload["texture_files"], {"effect/texture/pafx_fire_003a_kjd.dds": f"{EFFECT_TEXTURE_DIR}/pafx_fire_003a_kjd.dds"})
            self.assertEqual((Path(folder) / EFFECT_TEXTURE_DIR / "pafx_fire_003a_kjd.dds").read_bytes(), b"DDS fake")
            self.assertEqual(len(payload["emitters"]), 2)
            # no reader: the JSON is still written, the texture is said to be missing
            target, missing = write_effect_preview(Path(folder), preview)
            self.assertEqual(missing, ("effect/texture/pafx_fire_003a_kjd.dds",))
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["texture_files"], {})

    def test_the_dialog_describes_the_emitters(self) -> None:
        from cdmw.ui.new_item.effect_placement_dialog import describe_effect_preview

        text = describe_effect_preview(_fire_preview())
        lines = text.split("\n")
        self.assertTrue(lines[0].startswith("cdem_last_fire_circle_trail_001a: billboard, "), lines[0])
        self.assertIn("loops", lines[0])
        self.assertIn("pafx_fire_003a_kjd.dds", lines[0])
        self.assertIn("#", lines[0])
        self.assertTrue(lines[1].startswith("cdem_material_firefly_alpha_uberstandard: billboard, "), lines[1])
        # its emitter file is missing, and a missing one is stood in for as looping
        self.assertIn("loops", lines[1])
        self.assertTrue(any("is not in the archives" in line for line in lines[2:]), "the missing firefly file is a note")
        self.assertEqual(describe_effect_preview(None), "")


class TextureNamingTests(unittest.TestCase):
    """Whether an item draws with its own textures in the effect viewport turns on this,
    and it read only the field a `.pac` family uses. An imported model binds its files
    through the preview attributes instead, so the check found nothing and the item was
    painted flat grey -- the thing the reader asked about twice."""

    def test_every_place_a_submesh_can_name_a_texture_counts(self) -> None:
        from types import SimpleNamespace

        from cdmw.services.effect_placement_preview import mesh_names_textures

        def mesh(**attributes):
            return SimpleNamespace(submeshes=(SimpleNamespace(**attributes),))

        self.assertFalse(mesh_names_textures(mesh(texture="")))
        self.assertFalse(mesh_names_textures(SimpleNamespace(submeshes=())))
        self.assertTrue(mesh_names_textures(mesh(texture="cd_phm_01_sword_0001_base")), "a .pac family's own name")
        self.assertTrue(
            mesh_names_textures(mesh(texture="", preview_texture_path="/imports/axe_baseColor.png")),
            "an imported model binds a file, and leaves the name empty",
        )
        self.assertTrue(mesh_names_textures(mesh(texture="", preview_texture_dds_path="axe.dds")))
        self.assertFalse(mesh_names_textures(mesh(texture="   ", preview_texture_path="  ")), "blank is not a name")

    def test_the_character_frame_rotation_keeps_imported_texture_bindings(self) -> None:
        """The placement scene turns the weapon into the character's hand frame before
        packaging it. Those bindings are runtime SubMesh attributes, so a dataclass-only
        copy used to discard them and leave a neutral weapon in the effect viewport."""

        from cdmw.services.effect_character_reference import rotate_mesh

        blade = _blade()
        blade.submeshes[0].preview_texture_path = "C:/imports/axe_baseColor.png"
        blade.submeshes[0].preview_texture_dds_path = "C:/imports/axe_baseColor.dds"
        turned = rotate_mesh(
            blade,
            (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0),
        )

        self.assertEqual(turned.submeshes[0].preview_texture_path, "C:/imports/axe_baseColor.png")
        self.assertEqual(turned.submeshes[0].preview_texture_dds_path, "C:/imports/axe_baseColor.dds")


class ViewerParticleLayerContractTests(unittest.TestCase):
    """The resident .NET viewer's particle layer, as source: it reads what the package writes."""

    ROOT = Path(__file__).resolve().parents[1] / "tools" / "dotnet_mesh_editor_experiment"

    def test_the_viewer_reads_the_description_and_announces_the_capability(self) -> None:
        reader = (self.ROOT / "EffectParticlePreview.cs").read_text(encoding="utf-8")
        renderer = (self.ROOT / "D3D11MaterialViewport.EffectParticles.cs").read_text(encoding="utf-8")
        shaders = (self.ROOT / "D3D11MaterialShaders.hlsl").read_text(encoding="utf-8")
        provenance = (self.ROOT / "HelperBuildProvenance.cs").read_text(encoding="utf-8")
        package_protocol = (self.ROOT / "ExperimentForm.PackageProtocol.cs").read_text(encoding="utf-8")
        from cdmw.services.effect_placement_preview import EFFECT_PREVIEW_FILE

        self.assertIn(f'FileName = "{EFFECT_PREVIEW_FILE}"', reader)
        for key in ("bursts_per_second", "life", "spawn", "spread", "points", "force", "damping", "speed_limit", "scale", "rotation",
                    "scale_over_life", "alpha_over_life", "color_over_life", "emissive_color", "beam_width", "beam_length", "beam_axis",
                    "mass", "simulation_speed", "sequence", "velocity_stretch", "texture_files"):
            self.assertIn(f'"{key}"', reader, key)
        self.assertIn("class EffectEmitterSimulation", reader)
        self.assertIn("AppendBeamVertices", reader)
        self.assertIn("LoadEffectParticlePreview", renderer)
        self.assertIn("DrawEffectParticles", renderer)
        self.assertIn("VSParticle", shaders)
        self.assertIn("PSParticle", shaders)
        self.assertIn('"effect_particle_preview_v1"', provenance)
        self.assertIn("LoadEffectParticlePreview(prepared.PackagePath)", package_protocol)
        self.assertIn('["effect_preview"]', package_protocol)

    def test_a_particle_quad_knows_where_its_own_edge_is(self) -> None:
        """A sprite's UV is its flipbook cell's, not the quad's, so the shader had no way
        to know where the quad ended and faded nothing: an opaque smoke sheet drew as a
        grey diamond with a knife edge, over the item it was being placed on. The corner
        coordinate is that missing fact, and it has to travel the whole way."""

        reader = (self.ROOT / "EffectParticlePreview.cs").read_text(encoding="utf-8")
        renderer = (self.ROOT / "D3D11MaterialViewport.EffectParticles.cs").read_text(encoding="utf-8")
        shaders = (self.ROOT / "D3D11MaterialShaders.hlsl").read_text(encoding="utf-8")

        self.assertIn("Vector2 TexCoord, Vector2 Corner)", reader, "the CPU vertex carries it")
        self.assertIn("Vector2 TexCoord, Vector2 Corner)", renderer, "and so does the GPU one")
        self.assertIn('new InputElementDescription("TEXCOORD", 1, Format.R32G32_Float, 36, 0)', renderer)
        self.assertIn("float2 Corner : TEXCOORD1;", shaders)
        self.assertIn("output.Corner = input.Corner;", shaders)
        # the border fade, and the sprite's own alpha taken at its word
        self.assertIn("smoothstep(0.74f, 1.0f, max(fromCentre.x, fromCentre.y))", shaders)
        self.assertIn("step(0.999f, sample.a)", shaders)
        self.assertNotIn("max(sample.a, dot(sample.rgb", shaders, "luminance no longer overrides a real alpha channel")

    def test_the_simulation_can_be_held_where_it_is(self) -> None:
        """Pausing is not hiding: the particles stay drawn and stop moving, which is the
        only way to read where one of them actually is."""

        renderer = (self.ROOT / "D3D11MaterialViewport.EffectParticles.cs").read_text(encoding="utf-8")
        presentation = (self.ROOT / "MeshViewport.Presentation.cs").read_text(encoding="utf-8")

        self.assertIn("public void SetEffectParticlesPaused(bool paused)", renderer)
        self.assertIn("simulation.Step(_effectParticlesPaused ? 0.0f : deltaSeconds);", renderer)
        # resuming picks up from now rather than stepping the whole pause at once
        self.assertIn("_effectParticleLastTimestamp = Stopwatch.GetTimestamp();", renderer)
        self.assertIn('JsonBool(display, "effect_particles_paused"', presentation)
        self.assertIn("SetEffectParticlesPaused(particlesPaused)", presentation)
        self.assertIn('["effect_particles_paused"] = _presentationEffectParticlesPaused,', presentation)

    def test_a_viewport_backdrop_is_an_override_not_a_quality_field(self) -> None:
        """The host sets a colour override from the reader's remembered preference before
        its first frame, and `_backgroundColorOverride ?? settings.BackgroundColor` means
        that override wins. A backdrop sent in the quality payload changed nothing at all;
        it has to arrive as an override too."""

        presentation = (self.ROOT / "MeshViewport.Presentation.cs").read_text(encoding="utf-8")
        settings = (self.ROOT / "MeshViewport.PresentationSettings.cs").read_text(encoding="utf-8")
        gate = (self.ROOT / "EditMeshLayoutSmoke.cs").read_text(encoding="utf-8")

        self.assertIn('JsonString(display, "viewport_background_color"', presentation)
        self.assertIn("SetViewportBackgroundOverride(backdropColor)", presentation)
        self.assertIn("internal void SetViewportBackgroundOverride(", settings)
        self.assertIn("_backgroundColorOverride ?? _residentPresentationSettings.BackgroundColor", settings)
        # and the headless gate proves it at the clear colour rather than at a field
        self.assertIn("RequireViewportBackdropOverrideContract", gate)
        self.assertIn("The backdrop did not reach the clear colour", gate)

        from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame

        source = inspect.getsource(DotNetPreviewHostFrame.set_viewport_backdrop)
        self.assertIn('display["viewport_background_color"]', source)
        self.assertNotIn("d3d11_background_color", source, "the quality field is the one that did nothing")

    def test_the_particles_sample_with_a_clamp_of_their_own(self) -> None:
        """The mesh pass's sampler wraps, which lets one flipbook cell bleed into the next
        at the seam; particles clamp instead, and filter linearly so a sprite blown up over
        a sword is not a grid of texels."""

        renderer = (self.ROOT / "D3D11MaterialViewport.EffectParticles.cs").read_text(encoding="utf-8")
        self.assertIn("_effectParticleSamplerState", renderer)
        self.assertIn("Filter.MinMagMipLinear, TextureAddressMode.Clamp", renderer)
        self.assertIn("_effectParticleSamplerState?.Dispose();", renderer)


class HostPlacementMatrixTests(unittest.TestCase):
    """The host's placement numbers reach the helper as the editable role's model matrix."""

    def test_the_placement_composes_the_editable_model_matrix_and_bounds(self) -> None:
        from cdmw.ui.preview.dotnet_host import _apply_placement_to_editable_role, _placement_matrix

        matrix = _placement_matrix((1.0, 2.0, 3.0), (0.0, 0.0, 0.0), (0.2, 0.2, 0.2))
        self.assertEqual([round(v, 6) for v in matrix], [0.2, 0, 0, 0, 0, 0.2, 0, 0, 0, 0, 0.2, 0, 1.0, 2.0, 3.0, 1.0])
        scene = {"roles": {"editable": {"model_matrix": [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0], "world_bounds": {"min": [-1, -1, -1], "max": [1, 1, 1]}}}}
        _apply_placement_to_editable_role(scene, {"translation": (0.0, 0.0, 0.5), "rotation_degrees": (0.0, 0.0, 0.0), "scale": (0.5, 0.5, 0.5)})
        editable = scene["roles"]["editable"]
        self.assertEqual([round(v, 6) for v in editable["model_matrix"]][12:15], [0.0, 0.0, 0.5])
        self.assertEqual([round(v, 6) for v in editable["world_bounds"]["min"]], [-0.5, -0.5, 0.0])
        self.assertEqual([round(v, 6) for v in editable["world_bounds"]["max"]], [0.5, 0.5, 1.0])
        # a second placement starts from the remembered local bounds, not the moved ones
        _apply_placement_to_editable_role(scene, {"translation": (0.0, 0.0, 0.0), "rotation_degrees": (0.0, 0.0, 0.0), "scale": (1.0, 1.0, 1.0)})
        self.assertEqual([round(v, 6) for v in scene["roles"]["editable"]["world_bounds"]["max"]], [1.0, 1.0, 1.0])
        # a scene without the role is left alone
        _apply_placement_to_editable_role({}, {"translation": (0, 0, 0), "rotation_degrees": (0, 0, 0), "scale": (1, 1, 1)})


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_a_reach_that_dwarfs_the_item_starts_hidden(self) -> None:
        """A frame around a one-metre sword helps; a frame twenty metres across is a pair
        of columns crossing the view with the item a speck between them. Effects built for
        bosses reach that far, so their frame starts hidden and the label says why."""

        from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementDialog

        near = EffectPlacementDialog(
            None, item_mesh=_blade(), box_min=(-0.5, -0.5, -0.5), box_max=(0.5, 0.5, 0.5),
            scale=1.0, effect_label="fx_small", host_factory=lambda parent: None,
        )
        try:
            self.assertTrue(near.show_reach.isChecked(), "a sword-sized reach is worth drawing")
            self.assertNotIn("starts hidden", near.size_label.text())
        finally:
            near.close()
        far = EffectPlacementDialog(
            None, item_mesh=_blade(), box_min=(-10.8, -9.6, -10.8), box_max=(9.8, 17.0, 10.4),
            scale=1.0, effect_label="fx_boss", host_factory=lambda parent: None,
        )
        try:
            self.assertFalse(far.show_reach.isChecked())
            self.assertIn("24.2x the item", far.size_label.text())
            self.assertIn("starts hidden", far.size_label.text())
        finally:
            far.close()

    def test_without_a_viewport_the_numbers_and_deltas_still_work(self) -> None:
        from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementDialog

        dialog = EffectPlacementDialog(
            None, item_mesh=_blade(), box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
            offset=(0.0, 0.0, 0.1), scale=0.5, effect_label="fx_test", host_factory=lambda parent: None,
            effect_preview=_fire_preview(),
        )
        try:
            self.assertIsNone(dialog.host)
            self.assertTrue(dialog.emitters_toggle.isVisibleTo(dialog), "the emitters are folded under a toggle")
            self.assertIn("cdem_last_fire_circle_trail_001a: billboard", dialog.emitters_label.text())
            # short by design: the panel carried four lines of this above the controls
            self.assertIn("Reach at 0.50: 1.0 x 1.0 x 1.0 m", dialog.size_label.text())
            self.assertIn("the item", dialog.size_label.text(), "the reach is told against the item's own length")
            self.assertIn("The effect's own reach is 2.00 x 2.00 x 2.00 m", dialog.size_label.toolTip())
            dialog.apply_deltas((0.0, 0.0, 0.2))
            self.assertEqual(dialog.offset, (0.0, 0.0, 0.3))
            dialog.apply_deltas((0.0, 0.0, 0.0), (0.1, 0.1, 0.1))
            self.assertAlmostEqual(dialog.scale, 0.6)
            self.assertIn("Reach at 0.60: 1.2 x 1.2 x 1.2 m", dialog.size_label.text())
            dialog.scale_spin.setValue(0.25)
            dialog.offset_spins[1].setValue(-0.05)
            self.assertEqual(dialog.scale, 0.25)
            self.assertEqual(dialog.offset, (0.0, -0.05, 0.3))
        finally:
            dialog.done(0)


if __name__ == "__main__":
    unittest.main()
