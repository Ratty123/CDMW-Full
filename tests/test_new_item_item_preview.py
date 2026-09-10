"""The New Item Studio's inline item preview: what it builds a package from, and when."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ItemPreviewPackageTests(unittest.TestCase):
    def test_preview_model_adapter_keeps_complete_canonical_material_bindings(self) -> None:
        from cdmw.models import ModelPreviewData, ModelPreviewMesh
        from cdmw.modding.mesh_deformer import _EXTRA_SUBMESH_ATTRS
        from cdmw.services.mesh_dotnet_material_bindings import _DOTNET_PREVIEW_MATERIAL_ATTRS
        from cdmw.services.mesh_rust_preview_cache import parsed_mesh_from_model_preview

        self.assertEqual(set(_DOTNET_PREVIEW_MATERIAL_ATTRS) - set(_EXTRA_SUBMESH_ATTRS), set())

        source = ModelPreviewMesh(
            material_name="handle",
            texture_name="handle_base",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            indices=[0, 1, 2],
            source_submesh_index=0,
            preview_texture_path="handle_base.png",
            preview_texture_dds_path="handle_base.dds",
            preview_normal_texture_default_path="handle_normal.dds",
            preview_normal_texture_default_name="handle_normal.dds",
            preview_normal_texture_default_strength=0.8,
            preview_material_texture_default_path="handle_material.dds",
            preview_material_texture_default_name="handle_material.dds",
            preview_material_texture_default_type="material",
            preview_material_texture_default_subtype="standard_v2_material",
            preview_material_texture_default_packed_channels=("ao", "roughness", "metalness"),
            preview_height_texture_default_path="handle_height.dds",
            preview_height_texture_default_name="handle_height.dds",
            preview_emissive_texture_default_path="handle_emissive.dds",
            preview_emissive_texture_default_name="handle_emissive.dds",
        )
        model = ModelPreviewData(path="character/weapon/handle.pac", format="pac", meshes=[source])

        converted = parsed_mesh_from_model_preview(model).submeshes[0]

        self.assertEqual(converted.preview_normal_texture_default_path, "handle_normal.dds")
        self.assertEqual(converted.preview_normal_texture_default_strength, 0.8)
        self.assertEqual(converted.preview_material_texture_default_subtype, "standard_v2_material")
        self.assertEqual(
            converted.preview_material_texture_default_packed_channels,
            ("ao", "roughness", "metalness"),
        )
        self.assertEqual(converted.preview_height_texture_default_path, "handle_height.dds")
        self.assertEqual(converted.preview_emissive_texture_default_path, "handle_emissive.dds")
        self.assertEqual(converted.preview_source_asset_path, "character/weapon/handle.pac")

    def test_preview_model_is_prepared_once_without_an_earlier_material_combine(self) -> None:
        from cdmw.models import ModelPreviewData, ModelPreviewMesh, ModelPreviewRenderSettings
        from cdmw.ui.new_item import item_preview

        root = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_prepare_"))
        source = ModelPreviewData(meshes=[ModelPreviewMesh()])
        prepared = SimpleNamespace(meshes=[object()])
        settings = ModelPreviewRenderSettings(d3d11_tone_gamma=1.17)
        stop_event = threading.Event()
        seen = {}

        def fake_from_model(model, **_kwargs):
            seen["model"] = model
            return SimpleNamespace(package_dir=root / "prepared" / "package")

        with patch(
            "cdmw.services.preview_rendering_service.prepare_model_preview",
            return_value=(prepared, None),
        ) as prepare, patch(
            "cdmw.services.mesh_rust_preview_cache.build_or_lookup_rust_preview_package_from_model",
            fake_from_model,
        ):
            result = item_preview.build_item_preview_package(
                source,
                token="prepared",
                output_root=root,
                stop_event=stop_event,
                render_settings=settings,
            )

        self.assertEqual(result, root / "prepared" / "package")
        self.assertIs(seen["model"], prepared)
        prepare.assert_called_once_with(
            source,
            render_settings=settings,
            stop_event=stop_event,
            enable_material_combiner=False,
        )

    def test_imported_preview_forwards_the_direct_texture_callback(self) -> None:
        from cdmw.models import ModelPreviewData, ModelPreviewMesh
        from cdmw.ui.new_item import item_preview

        root = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_direct_"))
        source = ModelPreviewData(meshes=[ModelPreviewMesh()])
        direct = SimpleNamespace(package_dir=root / "direct")
        full = SimpleNamespace(package_dir=root / "full")
        ready = []

        def fake_from_model(_model, **kwargs):
            kwargs["fast_package_ready"](direct)
            return full

        with patch(
            "cdmw.services.mesh_rust_preview_cache.build_or_lookup_rust_preview_package_from_model",
            side_effect=fake_from_model,
        ):
            result = item_preview.build_item_preview_package(
                source,
                token="imported",
                output_root=root,
                stop_event=threading.Event(),
                fast_package_ready=ready.append,
            )

        self.assertEqual(ready, [direct])
        self.assertEqual(result, full.package_dir)

    def test_external_placement_does_not_build_a_duplicate_full_material_package(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item import item_preview
        from cdmw.ui.new_item.model_import import ModelPlacement

        root = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_external_direct_"))
        model = ParsedMesh(
            path="diagonal.gltf",
            format="gltf",
            submeshes=[SubMesh(name="model", vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[(0, 1, 2)])],
        )
        template = ParsedMesh(
            path="template.pac",
            format="pac",
            submeshes=[SubMesh(name="template", vertices=[(0, 0, 0), (0, 1, 0), (0, 0, 1)], faces=[(0, 1, 2)])],
        )
        calls = []

        def fake_build(_mesh, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(package_dir=root / "direct")

        with patch("cdmw.services.mesh_rust_preview_package.build_rust_preview_package", fake_build):
            result = item_preview.build_item_preview_package(
                item_preview.PlacementScene(template=template, model=model, placement=ModelPlacement()),
                token="external-placement",
                output_root=root,
                stop_event=threading.Event(),
                fast_package_ready=lambda _package: self.fail("one final direct package needs no interim reload"),
            )

        self.assertEqual(result, root / "direct")
        self.assertEqual([call["material_quality"] for call in calls], ["direct"])

    def test_comparison_reference_also_receives_its_full_material_tier(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item import item_preview

        root = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_reference_full_"))
        model = ParsedMesh(path="import.gltf", format="gltf", submeshes=[SubMesh(
            name="model", vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[(0, 1, 2)],
        )])
        reference = ParsedMesh(path="template.pac", format="pac", submeshes=[SubMesh(
            name="template", vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[(0, 1, 2)],
        )])
        reference.submeshes[0].preview_material_texture_inputs = (
            SimpleNamespace(confidence="native"),
        )
        qualities, ready = [], []

        def build(_mesh, **kwargs):
            quality = kwargs["material_quality"]
            qualities.append(quality)
            self.assertIs(kwargs["reference_mesh"], reference)
            return SimpleNamespace(package_dir=root / quality)

        with patch("cdmw.services.mesh_rust_preview_package.build_rust_preview_package", build):
            result = item_preview.build_item_preview_package(
                item_preview.PlacementScene(template=reference, model=model),
                token="comparison-materials", output_root=root,
                stop_event=threading.Event(), fast_package_ready=ready.append,
            )
        self.assertEqual(qualities, ["direct", "full"])
        self.assertEqual(len(ready), 1)
        self.assertEqual(result, root / "full")

    def test_a_preview_model_goes_the_textured_route_and_a_mesh_the_bare_one(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item import item_preview

        root = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_"))
        seen = {}

        def fake_from_model(model, **kwargs):
            seen["model"] = (model, kwargs)
            return SimpleNamespace(package_dir=root / "cdmw_rust_preview_x" / "package")

        def fake_from_mesh(mesh, **kwargs):
            seen["mesh"] = (mesh, kwargs)
            seen.setdefault("mesh_calls", []).append((mesh, kwargs))
            return SimpleNamespace(package_dir=root / "mesh_pkg")

        model = SimpleNamespace(meshes=[object()])
        mesh = ParsedMesh(
            path="b",
            format="pac",
            submeshes=[
                SubMesh(
                    name="b",
                    vertices=[(0, 0, 0), (0, 1, 0), (1, 0, 0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        character = ParsedMesh(
            path="character",
            format="pac",
            submeshes=[SubMesh(
                name="effect_character_0",
                material="effect_character_body",
                vertices=[(0, 0, 0), (0, 1, 0), (1, 0, 0)],
                faces=[(0, 1, 2)],
            )],
        )
        with patch("cdmw.services.mesh_rust_preview_cache.build_or_lookup_rust_preview_package_from_model", fake_from_model), patch("cdmw.services.mesh_rust_preview_package.build_rust_preview_package", fake_from_mesh):
            out = item_preview.build_item_preview_package(lambda _stop: model, token=("t", 1), output_root=root, stop_event=threading.Event())
            self.assertEqual(out, root / "cdmw_rust_preview_x" / "package")
            self.assertIs(seen["model"][0], model)
            self.assertEqual(seen["model"][1]["cache_mode"], "off", "a transient build, the frame removes it")
            self.assertEqual(seen["model"][1]["cache_root"], root)
            out = item_preview.build_item_preview_package(mesh, token=2, output_root=root, stop_event=threading.Event())
            self.assertEqual(out, root / "mesh_pkg")
            self.assertIs(seen["mesh"][0], mesh)
            with self.assertRaises(ValueError):
                item_preview.build_item_preview_package(lambda _stop: None, token=3, output_root=root, stop_event=threading.Event())
            # a placement scene: the model is the editable role, the template the reference, the
            # placement baked into the scene frame as the pipeline's own transform
            from cdmw.ui.new_item.model_import import ModelPlacement

            scene = item_preview.PlacementScene(
                template=mesh,
                model=mesh,
                placement=ModelPlacement(offset=(0.0, 0.0, -0.3), rotation=(90.0, 0.0, 0.0), scale=(2.0, 2.0, 2.0)),
                model_origin=(0.0, 1.7, 0.0),
                character=character,
            )
            item_preview.build_item_preview_package(scene, token=4, output_root=root, stop_event=threading.Event())
            _mesh, kwargs = seen["mesh_calls"][-1]
            reference = kwargs["reference_mesh"]
            self.assertIsNot(reference, mesh)
            self.assertEqual(len(reference.submeshes), 2, "template and character share the non-editable role")
            self.assertEqual(reference.submeshes[1].material, "effect_character_body")
            self.assertEqual(len(_mesh.submeshes), 1, "only the item remains editable")
            self.assertEqual(kwargs["comparison_mode"], "overlay")
            self.assertEqual(kwargs["interaction_mode"], "placement")
            self.assertEqual(kwargs["reference_draw"], "wire")
            self.assertEqual(kwargs["grid_normal_axis"], "z")
            transform = kwargs["scene_transform"]
            self.assertEqual(transform.alignment_mode, "manual")
            self.assertEqual(transform.offset_xyz, (0.0, 0.0, -0.3))
            self.assertEqual(transform.rotate_xyz_degrees, (90.0, 0.0, 0.0))
            self.assertEqual(transform.scale_xyz, (2.0, 2.0, 2.0))
            self.assertEqual(transform.source_anchor, (0.0, 1.7, 0.0))
            self.assertEqual(transform.target_anchor, (0.0, 1.7, 0.0))
        # cleanup removes the transient parent for the model route, the package itself otherwise
        self.assertEqual(item_preview.package_cleanup_root(root / "cdmw_rust_preview_x" / "package", root), root / "cdmw_rust_preview_x")
        self.assertEqual(item_preview.package_cleanup_root(root / "mesh_pkg", root), root / "mesh_pkg")
        self.assertEqual(item_preview.package_cleanup_root(root / "other" / "package", root), root / "other" / "package")

    def test_single_template_packages_keep_the_initial_model_in_its_frame(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.item_preview import build_item_preview_package

        mesh = ParsedMesh(
            path="template.pac",
            format="pac",
            submeshes=[SubMesh(
                name="template",
                vertices=[(3.0, 1.0, 0.0), (3.0, 3.0, 0.0), (3.2, 1.0, 0.0)],
                faces=[(0, 1, 2)],
            )],
        )
        with tempfile.TemporaryDirectory(prefix="cdmw_template_framing_") as temporary:
            for materials in (False, True):
                with self.subTest(include_material_resources=materials):
                    package = build_item_preview_package(
                        mesh, token="template", output_root=Path(temporary),
                        stop_event=threading.Event(), include_material_resources=materials,
                    )
                    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
                    scene = manifest["state"]["preview_scene"]
                    # The host uses replacement_only. A side-by-side package aims
                    # the opening camera at a displaced model before host replay.
                    self.assertEqual(scene["comparison_mode"], "replacement_only")
                    self.assertEqual(scene["roles"]["reference"]["submesh_indices"], [])
                    self.assertEqual(scene["roles"]["editable"]["submesh_indices"], [0])
                    self.assertEqual(scene["framing"]["bounds"]["center"], [3.1, 2.0, 0.0])
                    self.assertEqual(
                        scene["framing"]["initial_view"]["fit_bounds"],
                        [[3.0, 1.0, 0.0], [3.2, 3.0, 0.0]],
                    )

    def test_a_cached_template_package_is_built_once(self) -> None:
        from cdmw.models import ModelPreviewData, ModelPreviewMesh
        from cdmw.services import mesh_rust_preview_cache as package_service
        from cdmw.ui.new_item.item_preview import build_item_preview_package

        model = ModelPreviewData(
            path="character/model/template.pac",
            format="pac",
            meshes=[ModelPreviewMesh(
                material_name="template",
                positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                indices=[0, 1, 2],
                source_submesh_index=0,
            )],
        )
        token = ("template", 17, "template.pac", "0.pamt", "0.paz", 12, 34)
        with tempfile.TemporaryDirectory(prefix="cdmw_item_preview_cache_") as temporary:
            root = Path(temporary)
            source_calls = 0

            def source(_stop_event):
                nonlocal source_calls
                source_calls += 1
                return model

            original = package_service.build_rust_preview_package
            with patch.object(
                package_service,
                "build_rust_preview_package",
                wraps=original,
            ) as build:
                first = build_item_preview_package(
                    source,
                    token=token,
                    output_root=root,
                    stop_event=threading.Event(),
                    cache_mode="balanced",
                )
                second = build_item_preview_package(
                    source,
                    token=token,
                    output_root=root,
                    stop_event=threading.Event(),
                    cache_mode="balanced",
                )
                self.assertEqual(source_calls, 1, "a durable hit must not decode or prepare the template again")
                revised = build_item_preview_package(
                    source,
                    token=(*token[:-1], 35),
                    output_root=root,
                    stop_event=threading.Event(),
                    cache_mode="balanced",
                )
            self.assertEqual(build.call_count, 2)
            self.assertEqual(source_calls, 2)
            self.assertEqual(first, second)
            self.assertNotEqual(first, revised, "a changed archive revision must not reuse the old package")
            self.assertTrue(second.is_dir())


class PlacementConventionTests(unittest.TestCase):
    def test_the_host_matrix_is_the_pipeline_transform_and_the_pivot_follows(self) -> None:
        """One convention: the host's fallback matrix (what the helper draws and what its
        own gizmo drag rebuilds) equals the static replacement pipeline's transform for the
        same numbers, and the placement pivot (where the gizmo sits) is the source anchor
        under the placement, so it rides along with the model."""

        import random

        from cdmw.modding.static_mesh_geometry import _rotate_xyz
        from cdmw.ui.new_item.model_import import ModelPlacement
        from cdmw.ui.preview.dotnet_host import _apply_placement_to_editable_role

        random.seed(7)
        for _ in range(50):
            rotation = tuple(random.uniform(-180.0, 180.0) for _ in range(3))
            placement = ModelPlacement(offset=(0.3, -0.2, 1.1), rotation=rotation, scale=(0.5, 2.0, 1.5))
            point = tuple(random.uniform(-2.0, 2.0) for _ in range(3))
            shown = placement.apply(point)
            rotated = _rotate_xyz((point[0] * 0.5, point[1] * 2.0, point[2] * 1.5), rotation)
            built = (rotated[0] + 0.3, rotated[1] - 0.2, rotated[2] + 1.1)
            for axis in range(3):
                self.assertAlmostEqual(shown[axis], built[axis], places=9)
        # the build transform carries the numbers as they are
        transform = ModelPlacement(offset=(1, 2, 3), rotation=(10, 20, 30), scale=(2, 2, 2)).build_transform()
        self.assertEqual(transform.rotate_xyz_degrees, (10.0, 20.0, 30.0))
        self.assertEqual(transform.offset_xyz, (1.0, 2.0, 3.0))
        self.assertEqual(transform.scale_xyz, (2.0, 2.0, 2.0))
        self.assertEqual(transform.alignment_mode, "manual")
        # the pivot: the anchor under the placement (the model's origin with no anchor)
        state = {"roles": {"editable": {"model_matrix": [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0], "world_bounds": {"min": [0, 0, 0], "max": [1, 1, 1]}}}}
        _apply_placement_to_editable_role(state, {"translation": (0.25, 0.0, -0.4), "rotation_degrees": (0.0, 90.0, 0.0), "scale": (2.0, 2.0, 2.0)})
        self.assertEqual([round(v, 6) for v in state["placement_pivot"]], [0.25, 0.0, -0.4])
        state["automatic_alignment"] = {"source_anchor": [0.0, 0.0, 1.0]}
        _apply_placement_to_editable_role(state, {"translation": (0.25, 0.0, -0.4), "rotation_degrees": (0.0, 90.0, 0.0), "scale": (2.0, 2.0, 2.0)})
        # (0, 0, 1) scaled by 2 and turned 90 degrees about y lands on +x: (2, 0, 0), then the offset
        self.assertEqual([round(v, 6) for v in state["placement_pivot"]], [2.25, 0.0, -0.4])
        self.assertEqual([round(v, 6) for v in state["roles"]["editable"]["world_bounds"]["min"]], [0.25, 0.0, -2.4])

        # A first fit can bake a helmet up to the character's head while the placement
        # numbers still start at zero. The full authoritative alignment keeps that baked
        # origin under the gizmo and rotates/scales around it instead of world zero.
        identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        origin = (0.0, 1.7, 0.0)
        state = {
            "automatic_alignment": {"model_matrix": identity, "source_anchor": list(origin), "target_anchor": list(origin)},
            "roles": {"editable": {"model_matrix": identity, "world_bounds": {"min": [-0.2, 1.5, -0.2], "max": [0.2, 1.9, 0.2]}}},
        }
        _apply_placement_to_editable_role(
            state,
            {"translation": (0.25, 0.0, -0.4), "rotation_degrees": (90.0, 0.0, 0.0), "scale": (2.0, 2.0, 2.0)},
        )
        matrix = state["roles"]["editable"]["model_matrix"]
        moved_origin = (
            origin[0] * matrix[0] + origin[1] * matrix[4] + origin[2] * matrix[8] + matrix[12],
            origin[0] * matrix[1] + origin[1] * matrix[5] + origin[2] * matrix[9] + matrix[13],
            origin[0] * matrix[2] + origin[1] * matrix[6] + origin[2] * matrix[10] + matrix[14],
        )
        self.assertEqual([round(value, 6) for value in state["placement_pivot"]], [0.25, 1.7, -0.4])
        self.assertEqual([round(value, 6) for value in moved_origin], [0.25, 1.7, -0.4])

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.modding.static_mesh_scene_frame import build_authoritative_static_scene_frame

        mesh = ParsedMesh(
            path="helmet",
            format="dae",
            submeshes=[SubMesh(name="helmet", vertices=[(-0.2, 1.5, -0.2), (0.2, 1.9, 0.2)], faces=[])],
        )
        placement = ModelPlacement(offset=(0.25, 0.0, -0.4), rotation=(90.0, 0.0, 0.0), scale=(2.0, 2.0, 2.0))
        frame = build_authoritative_static_scene_frame(
            mesh,
            mesh,
            placement.build_transform(origin=origin),
        )
        built_origin = frame.transform.transform_point(origin)
        self.assertEqual([round(value, 6) for value in frame.placement_pivot], [0.25, 1.7, -0.4])
        self.assertEqual([round(value, 6) for value in built_origin], [0.25, 1.7, -0.4])


class ModelImportBuildTests(unittest.TestCase):
    def test_build_preserves_source_colour_without_automatic_tone_adjustment(self) -> None:
        from PIL import Image

        from cdmw.modding.material_profiles import apply_true_source_basic_controls_to_profile, get_complete_swap_material_profile
        from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot
        from cdmw.modding.material_source_driven import _source_driven_slots
        from cdmw.modding.material_texture_payloads import _source_slot_png_with_base_color_factor_path
        from cdmw.modding.mesh_parser import ParsedMesh
        from cdmw.modding.scene_import_result_ops import SceneImportResult
        from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement, build_placed_import

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            colour = root / "base.png"
            pixels = [(34, 38, 38, 255), (31, 26, 23, 255), (160, 172, 190, 255), (255, 255, 255, 255)]
            original = Image.new("RGBA", (4, 1))
            original.putdata(pixels)
            original.save(colour)
            texture_set = ReplacementTextureSet("blade", slots={"base": ReplacementTextureSlot("blade", "base", colour)})
            source = ModelImportSource(
                root / "a.gltf", root / "a.gltf", SceneImportResult(mesh=ParsedMesh()), None, None,
            )

            def build(_entry, _path, **kwargs):
                options = kwargs["static_replacement_options"]
                profile = apply_true_source_basic_controls_to_profile(
                    get_complete_swap_material_profile(options.complete_swap_material_profile),
                    auto_brightness_balance=options.auto_brightness_balance,
                    dark_detail_lift=options.dark_detail_lift,
                    tone_contrast=options.tone_contrast,
                )
                slot = next(slot for slot in _source_driven_slots(texture_set, material_profile=profile) if slot.slot_kind == "base")
                prepared = _source_slot_png_with_base_color_factor_path(slot, output_root=root)
                with Image.open(prepared) as image:
                    return image.convert("RGBA").tobytes()

            with patch("cdmw.services.preview_workflow_service.build_mesh_import_preview", build):
                actual = build_placed_import(SimpleNamespace(path="x.pac"), source, ModelPlacement())
            self.assertEqual(actual, original.tobytes(), "New Item must retain the source's dark detail and highlights")

    def test_model_import_temp_roots_are_owned_and_cleaned(self) -> None:
        from cdmw.ui.new_item.model_import import ModelImportSource, load_model_import_source

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            generated = base / "generated"

            def make_root(**_kwargs):
                generated.mkdir()
                return str(generated)

            with patch("cdmw.ui.new_item.model_import.tempfile.mkdtemp", make_root), patch(
                "cdmw.services.model_library_service.ModelLibraryService.resolve_importable_model",
                side_effect=ValueError("bad model"),
            ):
                with self.assertRaisesRegex(ValueError, "bad model"):
                    load_model_import_source(base / "bad.obj")
            self.assertFalse(generated.exists(), "a failed import removes the temp directory it created")

            caller_root = base / "caller"
            caller_root.mkdir()
            source = ModelImportSource(
                chosen_path=base / "a.obj",
                model_path=base / "a.obj",
                scene=None,
                preview_model=None,
                bounds=None,
                extract_root=caller_root,
                owns_extract_root=False,
            )
            source.cleanup()
            self.assertTrue(caller_root.is_dir(), "a caller-provided extraction root remains caller-owned")

            owned = base / "owned"
            owned.mkdir()
            source.extract_root = owned
            source.owns_extract_root = True
            source.cleanup()
            source.cleanup()
            self.assertFalse(owned.exists(), "owned cleanup is idempotent")

    def test_a_scene_source_flips_v_and_the_build_carries_it(self) -> None:
        """glTF, GLB, OBJ and DAE put V's origin at the bottom while the game samples from
        the top, so the studio reads those sources with the flip on and the build applies
        it per material -- the Builder's own Flip V, which these mods needed by hand."""

        from types import SimpleNamespace

        from cdmw.core.model_preview_orientation import scene_import_normalizes_texture_v
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement, build_placed_import, flip_v_transforms

        self.assertTrue(scene_import_normalizes_texture_v("gltf", "a.gltf"))
        self.assertFalse(scene_import_normalizes_texture_v("pac", "a.pac"))
        mesh = ParsedMesh(path="a.gltf", format="gltf", submeshes=[
            SubMesh(name="part_0", material="lambert1", vertices=[(0, 0, 0)] * 3, faces=[(0, 1, 2)]),
            SubMesh(name="part_1", material="lambert1", vertices=[(0, 0, 0)] * 3, faces=[(0, 1, 2)]),
        ])
        transforms = flip_v_transforms(mesh)
        self.assertEqual({t.source_material_name for t in transforms}, {"lambert1", "part_0", "part_1"})
        self.assertTrue(all(t.flip_v and not t.flip_u for t in transforms))
        from cdmw.modding.scene_import_result_ops import SceneImportResult

        source = ModelImportSource(
            chosen_path=Path("a.gltf"), model_path=Path("a.gltf"), scene=SceneImportResult(mesh=mesh),
            preview_model=None, bounds=((0, 0, 0), (1, 1, 1)), flip_texture_v=True,
        )
        source.set_bake(ModelPlacement(offset=(0.0, 1.7, 0.0)))
        seen = {}

        def fake_build(entry, obj_path, **kwargs):
            seen.update(kwargs)
            return "result"

        with patch("cdmw.services.preview_workflow_service.build_mesh_import_preview", fake_build):
            self.assertEqual(build_placed_import(SimpleNamespace(path="x.pac"), source, ModelPlacement()), "result")
        options = seen["static_replacement_options"]
        self.assertIs(
            seen["scene_import_result"].mesh,
            source.baked_scene_mesh(),
            "the Builder receives the same cached fit mesh that the preview uses",
        )
        self.assertTrue(options.texture_uv_transforms, "the flip goes into the build")
        self.assertTrue(all(t.flip_v for t in options.texture_uv_transforms))
        self.assertTrue(options.full_import_model_replacement, "the imported model owns the materials")
        self.assertEqual(options.transform.source_anchor, (0.0, 1.7, 0.0))
        self.assertEqual(options.transform.target_anchor, (0.0, 1.7, 0.0))
        # off: no UV transforms at all
        source.flip_texture_v = False
        seen.clear()
        with patch("cdmw.services.preview_workflow_service.build_mesh_import_preview", fake_build):
            build_placed_import(SimpleNamespace(path="x.pac"), source, ModelPlacement())
        self.assertEqual(list(seen["static_replacement_options"].texture_uv_transforms), [])


class ItemPreviewFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        from PySide6.QtCore import QEventLoop
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        frames = [widget for widget in self.app.allWidgets() if isinstance(widget, ItemPreviewFrame)]
        for frame in frames:
            frame.request_shutdown()
        deadline = time.monotonic() + 3
        while any(frame.iter_shutdown_workers() for frame in frames) and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertFalse(any(frame.iter_shutdown_workers() for frame in frames))

    @staticmethod
    def _fake_host_class():
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QWidget

        class Signals(QObject):
            state_changed = Signal(str, str)
            capture_completed = Signal(object)

        class FakeController:
            def __init__(self):
                self._signals = Signals()
                self.state_changed = self._signals.state_changed
                self.capture_completed = self._signals.capture_completed

            def shutdown(self):
                pass

        class FakeHost(QWidget):
            alignment_drag_started = Signal()
            alignment_drag_changed = Signal(float, float, float)
            alignment_drag_finished = Signal(float, float, float)
            alignment_rotation_changed = Signal(float, float, float)
            alignment_rotation_finished = Signal(float, float, float)
            alignment_scale_changed = Signal(float, float, float)
            alignment_scale_finished = Signal(float, float, float)

            def __init__(self, parent):
                super().__init__(parent)
                self.controller = FakeController()
                self.calls = []

            def __getattr__(self, name):
                if name.startswith("set_") or name in {"load_package", "capture_replacement_icon", "reset_view", "remember_editable_local_bounds"}:
                    def record(*args, **kwargs):
                        self.calls.append((name, args, kwargs))
                        return True

                    return record
                raise AttributeError(name)

        return FakeHost

    def test_shared_render_settings_apply_when_the_host_starts_and_change_live(self) -> None:
        from cdmw.models import ModelPreviewRenderSettings
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        frame = ItemPreviewFrame(
            output_root=Path(tempfile.mkdtemp(prefix="cdmw_item_preview_settings_")),
            host_factory=self._fake_host_class(),
        )
        first = ModelPreviewRenderSettings(d3d11_tone_gamma=1.17, d3d11_ao_strength=0.7)
        second = ModelPreviewRenderSettings(d3d11_tone_gamma=0.91, d3d11_ao_strength=0.4)

        frame.set_render_settings(first)
        frame._ensure_host()
        frame.set_render_settings(second)
        frame.set_lighting_preset("showcase")

        tuning = [call for call in frame.host.calls if call[0] == "set_render_tuning"]
        self.assertEqual(len(tuning), 2)
        self.assertAlmostEqual(tuning[0][1][0].d3d11_tone_gamma, 1.17)
        self.assertAlmostEqual(tuning[0][1][0].d3d11_ao_strength, 0.7)
        self.assertAlmostEqual(tuning[1][1][0].d3d11_tone_gamma, 0.91)
        self.assertAlmostEqual(tuning[1][1][0].d3d11_ao_strength, 0.4)
        lighting = [call for call in frame.host.calls if call[0] == "set_lighting_preset"]
        self.assertEqual([call[1][0] for call in lighting], ["neutral_studio", "showcase"])
        self.assertFalse(
            any(call[0] == "load_package" for call in frame.host.calls),
            "a lighting-only change must not rebuild or replace the resident package",
        )
        frame.shutdown()

    def test_shutdown_keeps_a_durable_cached_package(self) -> None:
        from cdmw.services.preview_rendering_service import dotnet_preview_package_derived_cache_root
        from cdmw.services.mesh_rust_preview_cache import rust_preview_package_cache_root
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        with tempfile.TemporaryDirectory(prefix="cdmw_item_preview_cache_shutdown_") as temporary:
            root = Path(temporary)
            packages = (
                dotnet_preview_package_derived_cache_root(root)
                / "packages"
                / "cache-key"
                / "package",
                rust_preview_package_cache_root(root)
                / "packages"
                / "rust-cache-key"
                / "package",
            )
            for package in packages:
                package.mkdir(parents=True)
                frame = ItemPreviewFrame(output_root=root, host_factory=self._fake_host_class())
                frame._package_dir = package
                frame.shutdown()
                self.assertTrue(
                    package.is_dir(),
                    "closing the frame must not delete a durable cache entry",
                )

    def test_a_placement_scene_takes_the_gizmo_and_the_numbers(self) -> None:
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame, PlacementScene
        from cdmw.ui.new_item.model_import import ModelPlacement

        FakeHost = self._fake_host_class()
        frame = ItemPreviewFrame(output_root=Path(tempfile.mkdtemp(prefix="cdmw_item_preview_")), host_factory=FakeHost)
        frame._ensure_host()  # as if the frame had been on screen: the viewport exists
        moves = []
        frame.placement_changed.connect(lambda p, done: moves.append((p, done)))
        start = ModelPlacement(offset=(0.0, 0.0, -0.2), scale=(0.5, 0.5, 0.5))
        with patch.object(ItemPreviewFrame, "_start_package", lambda self_, request: setattr(self_, "_thread", object())):
            frame.show_placement(
                lambda _stop: PlacementScene(template=None, model=None),
                token="p",
                placement=start,
                model_bounds=((-0.1, 0.0, -1.0), (0.1, 5.0, 1.0)),
                grid_bounds=((-1.0, 0.0, -0.1), (1.0, 5.0, 0.1)),
            )
        self.assertIs(frame.placement, start)
        host = frame.host
        # a ready while the newest build is still running belongs to the package before:
        # the placement and the gizmo must not land on it
        frame._host_state("ready", "")
        self.assertFalse(frame.is_ready, "a stale ready is not this scene's")
        self.assertNotIn("set_alignment_state", [c[0] for c in host.calls])
        # the package lands: it is this request's, so the scene's presentation goes out
        frame._thread = None
        host.calls.clear()
        frame._package_ready(Path("pkg"), "p", True)
        frame._host_state("ready", "")
        self.assertTrue(frame.is_ready)
        self.assertTrue(frame.showing_placement)
        names = [c[0] for c in host.calls]
        self.assertIn("set_alignment_state", names)
        self.assertIn("set_alignment_gizmo_tool", names)
        self.assertIn("set_alignment_preview_transform", names)
        self.assertIn(("set_icon_capture_mode", (False,), {}), host.calls)
        self.assertNotIn(("set_icon_capture_mode", (True,), {}), host.calls, "a placement scene is not in icon-capture mode")
        self.assertIn("reset_view", names, "the package-authored canonical view is restored once")
        state = next(c for c in host.calls if c[0] == "set_alignment_state")
        self.assertTrue(state[2]["enabled"])
        self.assertNotIn("source_submesh_indices", state[2], "no source highlight: the model draws as itself")
        self.assertIn(
            ("remember_editable_local_bounds", ((-0.1, 0.0, -1.0), (0.1, 5.0, 1.0)), {}),
            host.calls,
        )
        self.assertIn(("reset_view", (), {}), host.calls)
        pushed = next(c for c in host.calls if c[0] == "set_alignment_preview_transform")
        self.assertEqual(pushed[2]["translation"], (0.0, 0.0, -0.2))
        self.assertEqual(pushed[2]["scale_xyz"], (0.5, 0.5, 0.5))
        # a move drag: deltas are totals since the drag began, added to the base; nothing
        # is pushed to the helper until the drag ends (it draws the provisional itself)
        host.calls.clear()
        host.alignment_drag_started.emit()
        host.alignment_drag_changed.emit(0.1, 0.0, 0.0)
        host.alignment_drag_changed.emit(0.2, 0.0, 0.0)
        self.assertFalse([c for c in host.calls if c[0] == "set_alignment_preview_transform"], "no push mid-drag")
        host.alignment_drag_finished.emit(0.25, 0.0, 0.05)
        self.assertEqual(len([c for c in host.calls if c[0] == "set_alignment_preview_transform"]), 1, "one push, at the end")
        self.assertEqual(tuple(round(v, 9) for v in moves[-1][0].offset), (0.25, 0.0, -0.15))
        self.assertTrue(moves[-1][1])
        self.assertEqual(moves[0][0].offset, (0.1, 0.0, -0.2))
        self.assertFalse(moves[0][1])
        # a rotate drag adds degrees; a scale drag adds per axis and never reaches zero
        host.alignment_drag_started.emit()
        host.alignment_rotation_finished.emit(0.0, 90.0, 0.0)
        self.assertEqual(frame.placement.rotation, (0.0, 90.0, 0.0))
        host.alignment_drag_started.emit()
        host.alignment_scale_finished.emit(-0.9, 0.0, 0.0)
        self.assertGreater(frame.placement.scale[0], 0.0)
        self.assertEqual(frame.placement.scale[1], 0.5)
        # the numbers: set_placement pushes at once; the tool and view go to the host
        host.calls.clear()
        frame.set_placement(ModelPlacement(offset=(1.0, 2.0, 3.0)))
        self.assertEqual(host.calls[-1][2]["translation"], (1.0, 2.0, 3.0))
        frame.set_gizmo_tool("rotate")
        self.assertIn(("set_alignment_gizmo_tool", ("rotate",), {}), host.calls)
        host.calls.clear()
        frame.set_view_mode("side_by_side")
        self.assertEqual(
            host.calls,
            [
                ("set_display_mode", ("side_by_side",), {}),
                ("reset_view", (), {}),
            ],
            "showing a different role layout must immediately frame both visible models",
        )
        frame.set_gizmo_enabled(False)
        self.assertFalse(next(c for c in reversed(host.calls) if c[0] == "set_alignment_state")[2]["enabled"])
        # the same token changes only the resident transform; it does not replay the
        # complete presentation or send the same transform twice.
        host.calls.clear()
        frame.show_placement(lambda _stop: None, token="p", placement=ModelPlacement())
        self.assertEqual(
            [c[0] for c in host.calls],
            ["set_alignment_state", "set_alignment_preview_transform"],
            "the previously disabled gizmo is re-enabled without replaying the scene presentation",
        )
        host.calls.clear()
        frame.show_placement(lambda _stop: None, token="p", placement=ModelPlacement())
        self.assertEqual(host.calls, [])
        # a new request takes the gizmo off the scene on screen at once
        host.calls.clear()
        with patch.object(ItemPreviewFrame, "_start_package", lambda self_, request: None):
            frame.show_placement(lambda _stop: None, token="q", placement=ModelPlacement())
        self.assertIn(("set_alignment_state", (), {"enabled": False}), host.calls, "the stale scene loses the gizmo")
        # leaving for a plain source forgets the placement
        frame.show(None)
        self.assertIsNone(frame.placement)
        self.assertFalse(frame.showing_placement)
        frame._closed = True

    def test_panel_records_a_finished_gizmo_drag_without_refreshing_the_package(self) -> None:
        from cdmw.ui.new_item.model_import import ModelPlacement
        from cdmw.ui.new_item.panels_model_preview_mixin import ModelPanelPreviewMixin

        placement = ModelPlacement(offset=(0.2, 0.0, 0.0))
        preview = SimpleNamespace(set_placement=lambda value: calls.append(("placement", value)))
        controller = SimpleNamespace(model_import=object())
        calls = []
        panel = SimpleNamespace(
            _controller=controller,
            preview=preview,
            _sync_placement_numbers=lambda value: calls.append(("numbers", value)),
            _refresh_apply_status=lambda: calls.append(("status", None)),
            refresh_preview=lambda: calls.append(("refresh", None)),
        )

        ModelPanelPreviewMixin._placement_changed(panel, placement)

        self.assertEqual(calls, [("numbers", placement), ("placement", placement), ("status", None)])

    def test_quick_turn_buttons_update_resident_placement_and_invalidate_applied_mesh(self) -> None:
        from unittest.mock import PropertyMock
        from cdmw.ui.new_item.controller import NewItemStudioController
        from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement
        from cdmw.ui.new_item.panels_model import ModelPanel

        controller = NewItemStudioController(synchronous=True)
        panel = ModelPanel(controller)
        self.addCleanup(panel.deleteLater)
        source = ModelImportSource(Path("blade.obj"), Path("blade.obj"),
                                   SimpleNamespace(mesh=None), None, None)
        controller.model_import = source
        panel._show_model(None)
        frame = panel.preview
        frame._host_factory = self._fake_host_class()
        frame._ensure_host()
        frame.is_ready = True
        frame._loaded_is_placement = True
        initial = ModelPlacement(offset=(0.25, -0.5, 0.75), scale=(1.5, 2.0, 0.5))
        frame.set_placement(initial)
        panel._refresh_placement_enabled()
        for (axis, degrees), button in panel.quick_turn_buttons.items():
            with self.subTest(axis=axis, degrees=degrees):
                controller.set_model_placement(initial)
                source.applied = (source.bake, initial)
                controller.model_result = SimpleNamespace()
                controller.plan = object()
                controller._plan_revision = controller._draft_revision
                frame.host.calls.clear()
                button.click()
                expected = [0.0, 0.0, 0.0]
                expected[axis] = {-90: -90.0, 90: 90.0, 180: -180.0}[degrees]
                placed = controller.model_placement
                self.assertEqual(placed.rotation, tuple(expected))
                self.assertEqual(placed.offset, initial.offset)
                self.assertEqual(placed.scale, initial.scale)
                self.assertEqual(tuple(spin.value() for spin in panel.rotation_spins), tuple(expected))
                self.assertEqual(placed.build_transform().rotate_xyz_degrees, tuple(expected))
                self.assertIsNone(controller.model_result)
                self.assertFalse(controller.has_current_plan)
                self.assertEqual(source.bake, ModelPlacement(), "the fitted mesh and template stay fixed")
                self.assertIn("Not applied", panel.apply_status.plain_text())
                self.assertEqual([call[0] for call in frame.host.calls], ["set_alignment_preview_transform"])
                self.assertEqual(frame.host.calls[0][2]["rotation_degrees"], tuple(expected))
                if degrees == 180:
                    button.click()
                    self.assertEqual(controller.model_placement, initial)

        controller.set_model_placement(initial.with_values(rotation=(350.0, -350.0, 0.0)))
        panel.quick_turn_buttons[0, 90].click()
        panel.quick_turn_buttons[1, -90].click()
        self.assertEqual(controller.model_placement.rotation, (80.0, -80.0, 0.0))
        panel.reset_rotation_button.click()
        self.assertEqual(controller.model_placement, initial)
        with patch.object(type(controller), "busy", new_callable=PropertyMock, return_value=True):
            panel._refresh_placement_enabled()
            self.assertFalse(panel.reset_rotation_button.isEnabled())
            panel.quick_turn_buttons[0, 180].click()
            self.assertEqual(controller.model_placement, initial)
        frame.is_ready = False
        panel._refresh_placement_enabled()
        self.assertFalse(panel.quick_turn_buttons[0, 180].isEnabled())
        frame.shutdown()

    def test_rust_material_presentation_carries_the_imported_v_flip(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.services.mesh_rust_preview_package import build_rust_preview_package

        mesh = ParsedMesh(
            path="model.gltf",
            format="gltf",
            submeshes=[SubMesh(name="model", vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[(0, 1, 2)])],
        )
        mesh.submeshes[0].preview_texture_flip_vertical = True
        package = build_rust_preview_package(mesh, include_material_resources=False)
        manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))

        self.assertTrue(manifest["material_presentations"][0]["texture_flip_vertical"])

    def test_the_finished_build_is_read_back_on_this_thread(self) -> None:
        """`completed` is connected to a bound method of the frame, so Qt runs it on the
        frame's thread: the viewport's process is created there and its protocol reaches
        the host. A lambda would be run on the worker's thread instead, and the viewport
        would launch but never report ready. The build in flight is therefore named on the
        frame (`_building`), not captured in the connection."""

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame
        from cdmw.ui.new_item.model_import import ModelPlacement

        FakeHost = self._fake_host_class()
        frame = ItemPreviewFrame(output_root=Path(tempfile.mkdtemp(prefix="cdmw_item_preview_")), host_factory=FakeHost)
        frame._ensure_host()
        started = []
        with patch.object(ItemPreviewFrame, "_start_package", lambda self_, request: started.append(request)):
            frame.show_placement(lambda _stop: None, token="p", placement=ModelPlacement())
        self.assertEqual(started[0][0], "p")
        # what _start_package records, and what _package_ready reads back without a token
        frame._building = ("p", True, "materials")
        frame._package_ready(Path("pkg"))
        self.assertEqual(frame._loaded_token, "p")
        self.assertTrue(frame._loaded_is_placement)
        frame._closed = True

    def test_shutdown_requests_preview_stop_without_waiting_on_the_ui_thread(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_shutdown_"))
        frame = ItemPreviewFrame(output_root=output, host_factory=self._fake_host_class())

        def slow_build(_source, *, output_root, **_kwargs):
            time.sleep(0.2)
            package = Path(output_root) / "cdmw_dotnet_preview_slow" / "package"
            package.mkdir(parents=True, exist_ok=True)
            return package

        with patch("cdmw.ui.new_item.item_preview.build_item_preview_package", slow_build):
            frame.show(object(), token="slow")
            deadline = time.monotonic() + 1.0
            while (frame._thread is None or not frame._thread.isRunning()) and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            started = time.monotonic()
            frame.shutdown()
            self.assertLess(time.monotonic() - started, 0.08)
            self.assertTrue(frame.iter_shutdown_workers(), "the live worker remains discoverable for the shell close sweep")
            while frame.iter_shutdown_workers() and time.monotonic() < deadline + 1.0:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            self.assertEqual(frame.iter_shutdown_workers(), ())

    def test_superseding_a_preview_releases_its_model_source_usage_after_worker_teardown(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.domain.cancellation import RunCancelled
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame, PlacementScene, ProgressivePreviewSource
        from cdmw.ui.new_item.model_import import ModelPlacement

        temporary = tempfile.TemporaryDirectory(prefix="cdmw_item_preview_usage_")
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        frame = ItemPreviewFrame(output_root=output, host_factory=self._fake_host_class())
        self.addCleanup(frame.shutdown)
        self.addCleanup(frame.deleteLater)
        acquired = threading.Event()
        released = threading.Event()
        material_started = threading.Event()

        class Usage:
            def release(self) -> None:
                released.set()

        def acquire_usage():
            acquired.set()
            return Usage()

        def build_scene(_stop_event: threading.Event):
            return PlacementScene(template=object(), model=object())

        def build_package(_item, *, token, include_material_resources, output_root, stop_event, **_kwargs):
            if token == "import" and include_material_resources:
                material_started.set()
                while not stop_event.wait(0.005):
                    pass
                raise RunCancelled("superseded")
            package = Path(output_root) / f"package_{token}_{'full' if include_material_resources else 'geometry'}"
            package.mkdir(parents=True, exist_ok=True)
            return package

        source = ProgressivePreviewSource(
            geometry=build_scene,
            materials=build_scene,
            acquire_usage=acquire_usage,
        )
        with patch("cdmw.ui.new_item.item_preview.build_item_preview_package", build_package):
            frame.show_placement(source, token="import", placement=ModelPlacement())
            deadline = time.monotonic() + 2.0
            while not material_started.is_set() and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            self.assertTrue(acquired.is_set())
            self.assertTrue(material_started.is_set(), "the nested material stage is running")
            self.assertFalse(released.is_set())

            frame.show(object(), token="template")
            while not released.is_set() and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            self.assertTrue(released.is_set(), "the retired source is released only after both build threads stop")

            frame.request_shutdown()
            while frame.iter_shutdown_workers() and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            self.assertEqual(frame.iter_shutdown_workers(), ())

    def test_a_hidden_frame_builds_the_package_and_loads_it_when_shown(self) -> None:
        """The package builds ahead of the step (shown or not); the viewport starts, and the
        package loads, when the frame comes on screen."""

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        FakeHost = self._fake_host_class()
        frame = ItemPreviewFrame(output_root=Path(tempfile.mkdtemp(prefix="cdmw_item_preview_")), host_factory=FakeHost)
        started = []
        with patch.object(ItemPreviewFrame, "_start_package", lambda self_, request: started.append(request[0])):
            frame.show(lambda _stop: None, token="t")
        self.assertEqual(started, ["t"], "the build starts while hidden")
        self.assertIsNone(frame.host, "no viewport until the frame shows")
        frame._package_ready(Path("pkg"), "t", False)
        self.assertIsNone(frame.host)
        self.assertEqual(frame._deferred_package, (Path("pkg"), "t", False, "materials"))
        with patch.object(ItemPreviewFrame, "isVisible", lambda self_: True):
            frame.showEvent(None)
        self.assertIsNotNone(frame.host, "the viewport starts on show")
        self.assertIsNone(frame._deferred_package)
        self.assertIn("load_package", [c[0] for c in frame.host.calls])
        frame._closed = True

    def test_the_same_token_is_not_rebuilt_and_a_newer_one_supersedes(self) -> None:
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        FakeHost = self._fake_host_class()
        frame = ItemPreviewFrame(output_root=Path(tempfile.mkdtemp(prefix="cdmw_item_preview_")), host_factory=FakeHost)
        frame._ensure_host()
        started = []

        def fake_start(self_, request):
            started.append(request[0])
            self_._thread = object()  # a build in flight

        with patch.object(ItemPreviewFrame, "_start_package", fake_start):
            frame.show(lambda _stop: None, token="a")
            self.assertEqual(started, ["a"])
            frame.show(lambda _stop: None, token="a")
            self.assertEqual(started, ["a"], "the token in flight is left alone")
            frame.show(lambda _stop: None, token="b")
            self.assertEqual(started, ["a"], "a newer token waits for the build in flight")
            self.assertEqual(frame._pending[0], "b")
            frame._thread = None  # the build finished without showing "b" (is_ready stays False)
            frame.show(lambda _stop: None, token="b")
            self.assertEqual(started, ["a", "b"], "once idle and not showing it, the newest request is built")
            frame._thread = None
            frame.is_ready = True  # "b" is on screen now
            frame.show(lambda _stop: None, token="b")
            self.assertEqual(started, ["a", "b"], "what is shown is not rebuilt")
            frame.show(None)
            self.assertIsNone(frame._pending)
        frame._closed = True

    def test_progressive_placement_loads_geometry_then_materials_without_camera_reset(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.item_preview import (
            ItemPreviewFrame,
            PlacementScene,
            ProgressivePreviewSource,
        )
        from cdmw.ui.new_item.model_import import ModelPlacement

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_progressive_"))
        frame = ItemPreviewFrame(output_root=output, host_factory=self._fake_host_class())
        frame._ensure_host()
        host = frame.host
        built = []

        def build_package(source, *, include_material_resources, output_root, **_kwargs):
            stage = "full" if include_material_resources else "geometry"
            built.append(stage)
            package = Path(output_root) / stage
            package.mkdir(parents=True, exist_ok=True)
            return package

        source = ProgressivePreviewSource(
            geometry=lambda _stop: PlacementScene(template=object(), model=object()),
            materials=lambda _stop: PlacementScene(template=object(), model=object()),
        )
        with patch("cdmw.ui.new_item.item_preview.build_item_preview_package", build_package):
            frame.show_placement(source, token="progressive", placement=ModelPlacement())
            deadline = time.monotonic() + 2.0
            while len([call for call in frame.host.calls if call[0] == "load_package"]) < 2 and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)

        loads = [call for call in frame.host.calls if call[0] == "load_package"]
        self.assertCountEqual(built, ["geometry", "full"])
        self.assertEqual([call[1][0] for call in loads], [output / "geometry", output / "full"])
        self.assertEqual([call[2]["reset_view"] for call in loads], [True, False])
        self.assertIs(frame.host, host, "the resident host is reused for both stages")
        self.assertTrue((output / "geometry").exists(), "the resident package stays intact until ready")
        frame.host.controller.state_changed.emit("ready", "")
        while frame.iter_shutdown_workers() and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertFalse((output / "geometry").exists(), "the old package retires only after ready")
        self.assertTrue((output / "full").exists())
        frame.shutdown()

    def test_progressive_template_loads_geometry_then_materials_without_camera_reset(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame, ProgressivePreviewSource

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_progressive_template_"))
        frame = ItemPreviewFrame(output_root=output, host_factory=self._fake_host_class())
        frame._ensure_host()
        host = frame.host
        built = []

        def build_package(source, *, include_material_resources, output_root, **_kwargs):
            stage = "materials" if include_material_resources else "geometry"
            built.append((stage, source))
            package = Path(output_root) / stage
            package.mkdir(parents=True, exist_ok=True)
            return package

        geometry_source = object()
        material_source = object()
        source = ProgressivePreviewSource(
            geometry=lambda _stop: geometry_source,
            materials=lambda _stop: material_source,
        )
        with patch("cdmw.ui.new_item.item_preview.build_item_preview_package", build_package):
            frame.show(source, token=("template", 17))
            deadline = time.monotonic() + 2.0
            while len([call for call in frame.host.calls if call[0] == "load_package"]) < 2 and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)

        loads = [call for call in frame.host.calls if call[0] == "load_package"]
        self.assertCountEqual(built, [("geometry", geometry_source), ("materials", material_source)])
        self.assertEqual([call[1][0] for call in loads], [output / "geometry", output / "materials"])
        self.assertEqual([call[2]["reset_view"] for call in loads], [True, False])
        self.assertIs(frame.host, host, "the resident host is reused for both stages")
        frame.shutdown()

    def test_progressive_template_loads_direct_textures_before_full_materials(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame, ProgressivePreviewSource

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_direct_template_"))
        frame = ItemPreviewFrame(output_root=output, host_factory=self._fake_host_class())
        frame._ensure_host()
        statuses = []
        frame.status_changed.connect(statuses.append)

        def build_package(_source, *, include_material_resources, output_root, **kwargs):
            if not include_material_resources:
                package = Path(output_root) / "geometry"
                package.mkdir(parents=True, exist_ok=True)
                return package
            direct = Path(output_root) / "direct"
            full = Path(output_root) / "full"
            direct.mkdir(parents=True, exist_ok=True)
            full.mkdir(parents=True, exist_ok=True)
            kwargs["fast_package_ready"](SimpleNamespace(package_dir=direct))
            return full

        source = ProgressivePreviewSource(
            geometry=lambda _stop: object(),
            materials=lambda _stop: object(),
            supports_fast_material_package=True,
        )
        with patch("cdmw.ui.new_item.item_preview.build_item_preview_package", build_package):
            frame.show(source, token=("template", 23))
            deadline = time.monotonic() + 2.0
            while (
                len([call for call in frame.host.calls if call[0] == "load_package"]) < 3
                and time.monotonic() < deadline
            ):
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)

        loads = [call for call in frame.host.calls if call[0] == "load_package"]
        self.assertEqual(
            [call[1][0] for call in loads],
            [output / "geometry", output / "direct", output / "full"],
        )
        self.assertEqual([call[2]["reset_view"] for call in loads], [True, False, False])
        self.assertEqual(frame._loaded_stage, "materials")
        self.assertEqual(statuses[-1], "Fast textures are visible; loading full textures…")
        frame.host.controller.state_changed.emit("ready", "")
        self.app.processEvents()
        self.assertEqual(statuses[-1], "Full textures loaded.")
        frame.shutdown()

    def test_full_material_ready_confirms_the_texture_loading_finished(self) -> None:
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_status_"))
        package = output / "full"
        package.mkdir()
        frame = ItemPreviewFrame(
            output_root=output,
            host_factory=self._fake_host_class(),
        )
        frame._ensure_host()
        frame._package_dir = package
        frame._pending = ("model", object())
        frame._loaded_token = "model"
        frame._loaded_stage = "materials"
        frame._building = ("model", False, "materials")
        statuses = []
        frame.status_changed.connect(statuses.append)

        frame._host_state("ready", "")

        self.assertEqual(statuses[-1], "Full textures loaded.")
        frame.shutdown()

    def test_fast_material_ready_keeps_the_full_quality_upgrade_visible(self) -> None:
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_fast_status_"))
        package = output / "direct"
        package.mkdir()
        frame = ItemPreviewFrame(output_root=output, host_factory=self._fake_host_class())
        frame._ensure_host()
        frame._package_dir = package
        frame._pending = ("model", object())
        frame._loaded_token = "model"
        frame._loaded_stage = "fast_materials"
        frame._building = ("model", False, "materials")
        statuses = []
        frame.status_changed.connect(statuses.append)

        frame._host_state("ready", "")
        self.assertEqual(statuses[-1], "Fast textures are visible; loading full textures…")

        frame._package_failed("material synthesis failed")
        self.assertEqual(
            statuses[-1],
            "Fast textures remain visible; full textures failed to load: material synthesis failed",
        )
        frame.shutdown()

    def test_resident_full_material_rejection_replaces_the_loading_status(self) -> None:
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_resident_failure_"))
        frame = ItemPreviewFrame(output_root=output, host_factory=self._fake_host_class())
        frame._ensure_host()
        frame._loaded_stage = "materials"
        frame._full_texture_upgrade_from_fast = True
        statuses = []
        frame.status_changed.connect(statuses.append)

        frame._host_state("package_error", "Preview package load failed: missing texture")

        self.assertEqual(
            statuses[-1],
            "Fast textures remain visible; full textures failed to load: "
            "Preview package load failed: missing texture",
        )
        self.assertFalse(frame._full_texture_upgrade_from_fast)
        frame.shutdown()

    def test_progressive_template_accepts_a_native_package_without_python_recompile(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame, ProgressivePreviewSource

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_native_template_"))
        native_cache = output / "native-cache"
        native_package = output / "package_native"
        native_package.mkdir(parents=True)
        frame = ItemPreviewFrame(
            output_root=output,
            native_preview_core_cache_root=native_cache,
            host_factory=self._fake_host_class(),
        )
        frame._ensure_host()
        built = []
        material_context = {}

        def build_package(source, *, include_material_resources, output_root, **_kwargs):
            self.assertFalse(include_material_resources, "the ready native package must bypass Python recompilation")
            built.append(source)
            package = Path(output_root) / "geometry"
            package.mkdir(parents=True, exist_ok=True)
            return package

        def build_materials(_stop, **kwargs):
            material_context.update(kwargs)
            return native_package

        geometry_source = object()
        source = ProgressivePreviewSource(
            geometry=lambda _stop: geometry_source,
            materials=build_materials,
        )
        with patch("cdmw.ui.new_item.item_preview.build_item_preview_package", build_package):
            frame.show(source, token=("template", 17))
            deadline = time.monotonic() + 2.0
            while len([call for call in frame.host.calls if call[0] == "load_package"]) < 2 and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)

        loads = [call for call in frame.host.calls if call[0] == "load_package"]
        self.assertEqual(built, [geometry_source])
        self.assertEqual([call[1][0] for call in loads], [output / "geometry", native_package])
        self.assertEqual(material_context["output_root"], output)
        self.assertEqual(material_context["native_preview_core_cache_root"], native_cache)
        self.assertEqual(material_context["render_settings"], frame._render_settings)
        frame.shutdown()

    def test_progressive_template_uses_a_durable_material_cache_hit_before_geometry(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame, ProgressivePreviewSource

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_progressive_cache_"))
        cached = output / "derived" / "package"
        cached.mkdir(parents=True)
        frame = ItemPreviewFrame(output_root=output, host_factory=self._fake_host_class())
        frame.set_cache_mode("balanced")
        frame._ensure_host()
        built = []
        source = ProgressivePreviewSource(
            geometry=lambda _stop: built.append("geometry"),
            materials=lambda _stop: built.append("materials"),
        )
        with patch(
            "cdmw.services.mesh_rust_preview_cache.lookup_rust_preview_package_from_model_identity",
            return_value=SimpleNamespace(package_dir=cached),
        ):
            frame.show(source, token=("template", 17))
            deadline = time.monotonic() + 2.0
            while (frame._thread is not None or not frame.host.calls) and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)

        loads = [call for call in frame.host.calls if call[0] == "load_package"]
        self.assertEqual(built, [], "a valid full-material cache hit bypasses both builders")
        self.assertEqual([call[1][0] for call in loads], [cached])
        self.assertEqual(frame._loaded_stage, "materials")
        frame.request_shutdown()

    def test_template_materials_start_before_geometry_finishes_and_are_joined(self) -> None:
        from cdmw.ui.new_item.item_preview import ProgressivePreviewSource, _PreviewPackageTask

        output = Path(tempfile.mkdtemp(prefix="cdmw_parallel_template_"))
        started = threading.Event()
        finished = threading.Event()

        def materials(_stop):
            started.set()
            finished.set()
            return output / "full"

        def geometry(_stop):
            self.assertTrue(started.wait(0.5), "material preparation must overlap geometry decode")
            return object()

        task = _PreviewPackageTask(
            output_root=output, token=("template", 17),
            candidate=ProgressivePreviewSource(geometry, materials),
            is_placement=False, full_stage=False, base_package=None,
            render_settings=None, cache_mode="off", native_preview_core_cache_root=None,
            source_usage_required=False, source_usage_acquired=False,
        )
        progress = []
        with patch("cdmw.ui.new_item.item_preview.build_item_preview_package", return_value=output / "bare"):
            result = task(None, lambda *args: progress.append(args), threading.Event())
        self.assertTrue(finished.is_set())
        self.assertEqual(result.package_dir, output / "full")
        self.assertEqual(len(progress), 1, "geometry must finish normally while materials run")

    def test_progressive_failure_cancels_and_joins_material_preparation(self) -> None:
        from cdmw.domain.cancellation import RunCancelled
        from cdmw.ui.new_item.item_preview import ProgressivePreviewSource, _PreviewPackageTask

        output = Path(tempfile.mkdtemp(prefix="cdmw_parallel_template_cancel_"))
        for failure in ("geometry_cancel", "progress_error"):
            with self.subTest(failure=failure):
                started, finished = threading.Event(), threading.Event()
                cancelled = []

                def materials(stop):
                    started.set()
                    cancelled.append(stop.wait(1.0))
                    finished.set()
                    return output / "full"

                def geometry(_stop):
                    self.assertTrue(started.wait(0.5))
                    if failure == "geometry_cancel":
                        raise RunCancelled("cancel geometry")
                    return object()

                def progress(*_args):
                    raise RuntimeError("delivery failed")

                task = _PreviewPackageTask(
                    output_root=output, token=("template", 17), candidate=ProgressivePreviewSource(geometry, materials),
                    is_placement=False, full_stage=False, base_package=None, render_settings=None,
                    cache_mode="off", native_preview_core_cache_root=None,
                    source_usage_required=False, source_usage_acquired=False,
                )
                expected = RunCancelled if failure == "geometry_cancel" else RuntimeError
                with patch("cdmw.ui.new_item.item_preview.build_item_preview_package", return_value=output / "bare"):
                    with self.assertRaises(expected):
                        task(None, progress, threading.Event())
                self.assertTrue(finished.is_set())
                self.assertEqual(cancelled, [True])

    def test_native_template_cache_hit_bypasses_both_progressive_builders(self) -> None:
        from cdmw.ui.new_item.item_preview import ProgressivePreviewSource, _PreviewPackageTask

        output = Path(tempfile.mkdtemp(prefix="cdmw_native_template_hit_"))
        cached = output / "durable" / "package"
        contexts = []
        built = []

        def lookup(stop_event, **context):
            self.assertFalse(stop_event.is_set())
            contexts.append(context)
            return cached

        source = ProgressivePreviewSource(
            geometry=lambda _stop: built.append("geometry"),
            materials=lambda _stop: built.append("materials"),
            cached_materials=lookup,
        )
        task = _PreviewPackageTask(
            output_root=output, token=("template", 17), candidate=source,
            is_placement=False, full_stage=False, base_package=None,
            render_settings="captured-settings", cache_mode="balanced",
            native_preview_core_cache_root=output / "native", source_usage_required=False,
            source_usage_acquired=False,
        )
        result = task(None, lambda *_args: self.fail("cached package must not publish bare geometry"), threading.Event())
        self.assertEqual(result.package_dir, cached)
        self.assertEqual(result.stage, "materials")
        self.assertEqual(built, [])
        self.assertEqual(contexts, [{
            "output_root": output, "native_preview_core_cache_root": output / "native",
            "render_settings": "captured-settings", "cache_mode": "balanced",
        }])

    def test_material_upgrade_preserves_geometry_and_adds_rust_textures(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.item_preview import (
            PlacementScene,
            build_item_preview_package,
            upgrade_item_preview_package_materials,
        )
        from cdmw.ui.new_item.model_import import ModelPlacement

        output = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_upgrade_"))
        mesh = ParsedMesh(
            path="item.pac",
            format="pac",
            submeshes=[SubMesh(
                name="item",
                material="item",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                faces=[(0, 1, 2)],
            )],
        )
        from PIL import Image

        texture = output / "item.png"
        Image.new("RGBA", (4, 4), (32, 96, 192, 255)).save(texture)
        mesh.submeshes[0].preview_texture_path = str(texture)
        scene = PlacementScene(template=mesh, model=mesh, placement=ModelPlacement())
        geometry = build_item_preview_package(
            scene,
            token="geometry",
            output_root=output,
            stop_event=threading.Event(),
            include_material_resources=False,
        )
        geometry_bytes = (geometry / "document.json").read_bytes()

        materials = upgrade_item_preview_package_materials(
            geometry,
            scene,
            output_root=output,
            stop_event=threading.Event(),
        )

        self.assertEqual((materials / "document.json").read_bytes(), geometry_bytes)
        geometry_manifest = json.loads((geometry / "manifest.json").read_text(encoding="utf-8"))
        material_manifest = json.loads((materials / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(geometry_manifest["textures"], [])
        self.assertGreaterEqual(len(material_manifest["textures"]), 1)
        for manifest in (geometry_manifest, material_manifest):
            preview_scene = manifest["state"]["preview_scene"]
            self.assertEqual(preview_scene["interaction_mode"], "placement")
            self.assertEqual(preview_scene["comparison_mode"], "overlay")
            self.assertEqual(preview_scene["reference_draw"], "wire")
            self.assertEqual(preview_scene["grid"]["normal_axis"], "z")
            self.assertGreater(preview_scene["editable_submesh_count"], 0)
            self.assertGreater(preview_scene["reference_submesh_count"], 0)
            self.assertTrue(preview_scene["grid"]["visible"])
            self.assertTrue(preview_scene["gizmo"]["visible"])


if __name__ == "__main__":
    unittest.main()
