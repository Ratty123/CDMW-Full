"""Gates for the New Item Studio's plain-PBR material route (`cdmw.services.new_item_materials`)."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.pac_xml_standard_material import EMISSIVE_SHADER, LAYERED_SHADER, STANDARD_SHADER, find_material_wrappers  # noqa: E402
from cdmw.domain.new_item.spec import MaterialRoute  # noqa: E402
from cdmw.services.new_item_materials import (  # noqa: E402
    SourceMaterialTextures,
    encode_emissive_from_png,
    encode_sp_from_factors,
    encode_sp_from_png,
    route_model_files,
    route_plain_pbr,
    source_materials_from_import,
)
from cdmw.services.new_item_planning import ModelFiles, NewItemPlanError  # noqa: E402
from test_pac_xml_standard_material import SIDECAR, TEX  # noqa: E402

XML = "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0003.pac_xml"
BASE = f"{TEX}/cd_phm_02_sword_0003_lambert1_basecolor.dds"
NORMAL = f"{TEX}/cd_phm_02_sword_0003_lambert1_n.dds"
MASK = f"{TEX}/cd_phm_02_sword_0003_lambert1_material_mask_x_ma.dds"
GEM_BASE = f"{TEX}/cd_phm_02_sword_0003_gem_base_474747fcf8c5.dds"
GEM_MASK = f"{TEX}/cd_phm_02_sword_0003_gem_detail_mask_neutral_ma.dds"
GEM_EMI = f"{TEX}/cd_phm_02_sword_0003_gem_emissive_emi.dds"


def dds(tag: bytes = b"DXT1") -> bytes:
    data = bytearray(128)
    data[:4] = b"DDS "
    struct.pack_into("<I", data, 4, 124)
    struct.pack_into("<II", data, 12, 16, 16)
    struct.pack_into("<I", data, 28, 5)
    struct.pack_into("<I", data, 76, 32)
    struct.pack_into("<I", data, 80, 4)
    data[84:88] = tag
    return bytes(data) + bytes(64)


def builder_files() -> ModelFiles:
    return ModelFiles(pac_data=b"PAC", side_files={
        XML: SIDECAR.encode("utf-8"),
        BASE: dds(), NORMAL: dds(b"BC5U"), MASK: dds(),
        GEM_BASE: dds(), GEM_MASK: dds(), GEM_EMI: dds(b"BC5U"),
    })


@dataclass
class Section:
    target_submesh_name: str
    source_material_name: str


@dataclass
class Binding:
    material_name: str
    texture_slots: tuple = ()
    submesh_index: int = -1


@dataclass
class Result:
    source_owned_output_draw_sections: tuple = ()


@dataclass
class Parameter:
    parameter_name: str
    value: str


@dataclass
class Submesh:
    preview_material_parameters: tuple = ()


@dataclass
class Mesh:
    submeshes: tuple = ()


@dataclass
class Scene:
    material_bindings: tuple = ()
    mesh: object = None


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.folder = Path(self._temp.name)
        self.mr = self.folder / "lambert1_metallicRoughness.png"
        self.mr.write_bytes(b"png")
        self.emi = self.folder / "gem_emissive.png"
        self.emi.write_bytes(b"png")
        self.encoded = []

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _encode(self, png: Path) -> bytes:
        self.encoded.append(png.name)
        return dds()

    def _encode_emissive(self, png: Path):
        self.encoded.append(png.name)
        return dds(b"BC4U"), "#4461F3FF"

    def _encode_factors(self, roughness: float, metallic: float) -> bytes:
        self.encoded.append(f"factors {roughness:g} {metallic:g}")
        return dds()

    def test_rewrites_owned_wrappers_with_a_source_sp_and_drops_the_orphaned_mask(self) -> None:
        sources = {"cd_phm_02_sword_0003": SourceMaterialTextures(name="lambert1", material=self.mr)}
        route = route_plain_pbr(builder_files(), sources=sources, encode=self._encode, encode_emissive=self._encode_emissive)
        self.assertEqual(route.rewritten, ("cd_phm_02_sword_0003", "cd_phm_02_sword_handle_0003"))
        sp = f"{TEX}/cd_phm_02_sword_0003_lambert1_sp.dds"
        self.assertEqual(route.encoded, (sp,))
        self.assertEqual(self.encoded, ["lambert1_metallicRoughness.png"])
        files = route.files
        self.assertEqual(files.pac_data, b"PAC")
        self.assertEqual(files.material_route, MaterialRoute.PLAIN_PBR.value)
        self.assertIn(sp, files.side_files)
        self.assertNotIn(MASK, files.side_files, "the Builder mask no wrapper names any more is dropped")
        self.assertIn(GEM_MASK, files.side_files, "the gem's mask stands in for its _sp")
        self.assertEqual(set(files.side_files) - {XML, sp}, {BASE, NORMAL, GEM_BASE, GEM_MASK, GEM_EMI})
        text = files.side_files[XML].decode("utf-8")
        self.assertTrue(text.startswith("\ufeff<SkinnedMeshPropertyCommon"), "the BOM stays")
        wrappers = {w.submesh_name: w for w in find_material_wrappers(text)}
        self.assertEqual(wrappers["cd_phm_02_sword_0003"].shader, STANDARD_SHADER)
        self.assertEqual(wrappers["cd_phm_02_sword_0003"].textures, {"_baseColorTexture": BASE, "_normalTexture": NORMAL, "_materialTexture": sp})
        gem = wrappers["cd_phm_02_sword_handle_0003"]
        self.assertEqual(gem.shader, EMISSIVE_SHADER)
        self.assertEqual(gem.textures, {"_baseColorTexture": GEM_BASE, "_materialTexture": GEM_MASK, "_emissiveIntensityTexture": GEM_EMI})
        self.assertEqual((gem.value("_emissiveColor"), gem.value("_emissiveIntensity")), ("#00FFCAFF", "10.000000"), "the Builder's colour and intensity carry over")
        self.assertEqual(wrappers["cd_phm_02_sword_guard_0003"].shader, LAYERED_SHADER, "the template's own wrapper is untouched")
        self.assertTrue(any("lambert1_metallicRoughness.png" in line for line in route.lines), route.lines)
        self.assertTrue(any("gem" not in w and "handle" in w for w in route.warnings), route.warnings)
        self.assertEqual(files.notes, route.lines)
        self.assertEqual(files.warnings, route.warnings)

    def test_source_emissive_is_encoded_with_its_colour(self) -> None:
        sources = {"cd_phm_02_sword_handle_0003": SourceMaterialTextures(name="Gem", emissive=self.emi, roughness_factor=0.3, metallic_factor=0.9)}
        route = route_plain_pbr(builder_files(), sources=sources, encode=self._encode, encode_emissive=self._encode_emissive, encode_factors=self._encode_factors)
        # no metallic/roughness map on the source: its factors become a solid _sp; the emissive is encoded from the source
        self.assertEqual(self.encoded, ["factors 0.3 0.9", "gem_emissive.png"])
        gem_sp = f"{TEX}/cd_phm_02_sword_0003_gem_sp.dds"
        self.assertEqual(route.encoded, (gem_sp, GEM_EMI))
        gem = {w.submesh_name: w for w in find_material_wrappers(route.files.side_files[XML].decode("utf-8"))}["cd_phm_02_sword_handle_0003"]
        self.assertEqual(gem.textures["_materialTexture"], gem_sp)
        self.assertNotIn(GEM_MASK, route.files.side_files, "the Builder's mask is no longer named")
        self.assertEqual(gem.value("_emissiveColor"), "#4461F3FF", "the colour the source glows in")
        self.assertEqual(gem.value("_emissiveIntensity"), "10.000000")
        self.assertEqual(route.files.side_files[GEM_EMI][84:88], b"BC4U", "the intensity map replaces the Builder's")
        self.assertTrue(any("factors (roughness 0.3, metalness 0.9)" in line for line in route.lines), route.lines)

    def test_without_sources_the_builder_masks_stand_in(self) -> None:
        route = route_plain_pbr(builder_files(), encode=self._encode)
        self.assertEqual(self.encoded, [])
        self.assertEqual(route.encoded, ())
        wrappers = {w.submesh_name: w for w in find_material_wrappers(route.files.side_files[XML].decode("utf-8"))}
        self.assertEqual(wrappers["cd_phm_02_sword_0003"].textures["_materialTexture"], MASK)
        self.assertEqual(len(route.warnings), 2)
        self.assertEqual(set(route.files.side_files), set(builder_files().side_files), "nothing dropped, nothing added")

    def test_wrappers_sharing_a_base_share_the_source(self) -> None:
        # a cloned section (the guard drawing with the handle's textures) has no draw section of its own
        text = (
            SIDECAR.replace(f"{TEX}/cd_phm_02_guard_0003_n.dds", NORMAL)
            .replace(f"{TEX}/cd_temp_r_m.dds", BASE)
            .replace('StringItemID="_colorBlendingMaskTexture" ItemID="3936485985222654" _name="_colorBlendingMaskTexture"', 'StringItemID="_baseColorTexture" ItemID="0" _name="_baseColorTexture"')
        )
        files = ModelFiles(pac_data=b"PAC", side_files={**builder_files().side_files, XML: text.encode("utf-8")})
        sources = {"cd_phm_02_sword_0003": SourceMaterialTextures(name="lambert1", material=self.mr)}
        route = route_plain_pbr(files, sources=sources, encode=self._encode)
        self.assertEqual(self.encoded, ["lambert1_metallicRoughness.png"], "encoded once")
        wrappers = {w.submesh_name: w for w in find_material_wrappers(route.files.side_files[XML].decode("utf-8"))}
        self.assertEqual(wrappers["cd_phm_02_sword_guard_0003"].shader, STANDARD_SHADER)
        self.assertEqual(wrappers["cd_phm_02_sword_guard_0003"].textures["_materialTexture"], f"{TEX}/cd_phm_02_sword_0003_lambert1_sp.dds")

    def test_refuses_an_import_without_one_sidecar_or_without_owned_wrappers(self) -> None:
        with self.assertRaisesRegex(NewItemPlanError, "0 .pac_xml"):
            route_plain_pbr(ModelFiles(pac_data=b"PAC", side_files={BASE: dds()}), encode=self._encode)
        with self.assertRaisesRegex(NewItemPlanError, "owns no material wrapper"):
            route_plain_pbr(ModelFiles(pac_data=b"PAC", side_files={XML: SIDECAR.encode("utf-8")}), encode=self._encode)

    def test_source_materials_are_read_off_the_result_and_the_scene(self) -> None:
        result = Result((Section("cd_phm_02_sword_0003", "lambert1"), Section("cd_phm_02_sword_guard_0003", "Gem_outside"), Section("x", "unknown")))
        scene = Scene((
            Binding("lambert1", (("base", str(self.folder / "missing.png")), ("material", str(self.mr)), ("emissive", str(self.emi))), submesh_index=0),
            Binding("Gem_outside", (), submesh_index=1),
        ), mesh=Mesh((Submesh(), Submesh((Parameter("_roughnessFactor", "0.250000"), Parameter("_metallicFactor", "1.000000"), Parameter("_baseColorFactor", "#112233"))))))
        sources = source_materials_from_import(result, scene)
        self.assertEqual(set(sources), {"cd_phm_02_sword_0003", "cd_phm_02_sword_guard_0003"})
        lambert = sources["cd_phm_02_sword_0003"]
        self.assertEqual((lambert.name, lambert.material, lambert.emissive, lambert.base), ("lambert1", self.mr, self.emi, None), "only files that exist")
        self.assertEqual((lambert.roughness_factor, lambert.metallic_factor), (1.0, 1.0), "no factors given: the glTF defaults")
        gem = sources["cd_phm_02_sword_guard_0003"]
        self.assertEqual((gem.material, gem.roughness_factor, gem.metallic_factor), (None, 0.25, 1.0), "the factors the importer kept on the submesh")
        self.assertEqual(source_materials_from_import(None, None), {})
        self.assertEqual(source_materials_from_import(result, None), {})

    def test_route_model_files_keeps_the_builder_sidecar_when_asked(self) -> None:
        files = builder_files()
        kept = route_model_files(files, MaterialRoute.BUILDER)
        self.assertEqual(kept.side_files, files.side_files)
        self.assertEqual(kept.material_route, MaterialRoute.BUILDER.value)
        self.assertTrue(kept.notes)
        routed = route_model_files(files, MaterialRoute.PLAIN_PBR, result=Result(()), scene=Scene(()))
        self.assertEqual(routed.material_route, MaterialRoute.PLAIN_PBR.value)
        self.assertEqual({w.shader for w in find_material_wrappers(routed.side_files[XML].decode("utf-8"))}, {STANDARD_SHADER, EMISSIVE_SHADER, LAYERED_SHADER})


class EncoderTests(unittest.TestCase):
    """The real encoders, on tiny images: what the game reads."""

    def test_sp_and_emissive_encodes(self) -> None:
        from PIL import Image

        from cdmw.core.dds_native import inspect_dds_native

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            mr = folder / "mr.png"
            Image.merge("RGB", (Image.new("L", (16, 16), 255), Image.new("L", (16, 16), 40), Image.new("L", (16, 16), 220))).save(mr)
            try:
                sp = encode_sp_from_png(mr)
            except Exception as exc:  # the native encoder is a build artefact; without it the gate says so and stops
                self.skipTest(f"native DDS encoder unavailable: {exc}")
            info = inspect_dds_native(sp)
            self.assertEqual((info.width, info.height, info.mip_count), (16, 16, 5))
            self.assertIn("BC1", str(info.format_name).upper())
            emissive = folder / "emi.png"
            image = Image.new("RGB", (16, 16), (0, 0, 0))
            for x in range(8):
                for y in range(16):
                    image.putpixel((x, y), (68, 97, 243))
            image.save(emissive)
            data, color = encode_emissive_from_png(emissive)
            info = inspect_dds_native(data)
            self.assertEqual((info.width, info.height, info.mip_count), (16, 16, 5))
            self.assertIn("BC4", str(info.format_name).upper())
            self.assertEqual(color, "#4766FFFF", "the lit pixels' colour, brightest channel full")
            solid = encode_sp_from_factors(0.3, 0.9)
            info = inspect_dds_native(solid)
            self.assertEqual((info.width, info.height, info.mip_count), (16, 16, 5))
            self.assertIn("BC1", str(info.format_name).upper())


if __name__ == "__main__":
    unittest.main()
