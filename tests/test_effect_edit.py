"""Editing an effect's look in place, and renaming its clones without moving a byte."""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

from cdmw.core.effect_binary import decode_effect_binary
from cdmw.core.effect_edit import (
    EffectEditError,
    apply_effect_look,
    emitter_paths_of,
    preset_names_of,
    preset_path,
    rename_effect_strings,
    rename_string_values,
    same_length_stem,
)
from cdmw.domain.new_item.spec import EffectLook

FIXTURES = Path(__file__).parent / "fixtures" / "effects"
EFFECT = FIXTURES / "fx_hit_common_fire_attach_a_loop.pae"
EMBER = FIXTURES / "cdem_standard_fire_large_fire_ember_001a.paem"
TRAIL = FIXTURES / "cdem_last_fire_circle_trail_001a.paem"
PRESET = FIXTURES / "fx_fire_uber_ember_01.parg"


def _values(data: bytes, name: str):
    return [value.value for value in decode_effect_binary(data).root.all_values() if value.name == name]


class StemTests(unittest.TestCase):
    def test_same_length_stems_end_in_the_tag_and_stay_unique(self) -> None:
        self.assertEqual(same_length_stem("cdem_standard_fire_large_fire_ember_001a", "_n90012"), "cdem_standard_fire_large_fire_emb_n90012")
        self.assertEqual(same_length_stem("fx_hit_common_fire_attach_a_loop", "_n90012"), "fx_hit_common_fire_attach_n90012")
        taken = {"fx_hit_common_fire_attach_n90012"}
        bumped = same_length_stem("fx_hit_common_fire_attach_a_loop", "_n90012", taken=taken)
        self.assertEqual(len(bumped), 32)
        self.assertNotIn(bumped, taken)
        self.assertTrue(bumped.endswith("_n900121"))
        short = same_length_stem("fx1", "_n90012")
        self.assertEqual(len(short), 3)
        self.assertNotEqual(short, "fx1")


class RenameTests(unittest.TestCase):
    def test_the_effect_names_its_emitters_twice_and_both_are_renamed(self) -> None:
        data = EFFECT.read_bytes()
        renames = {
            "fx_hit_common_fire_attach_a_loop": "fx_hit_common_fire_attach_n90012",
            "cdem_last_fire_circle_trail_001a": "cdem_last_fire_circle_tra_n90012",
        }
        renamed = rename_effect_strings(data, renames)
        self.assertEqual(len(renamed), len(data))
        doc = decode_effect_binary(renamed)
        self.assertTrue(doc.walk_complete, doc.walk_note)
        self.assertEqual(doc.root.value("_effectDataName").value, "fx/materialfx/fx_hit_common_fire_attach_n90012")
        self.assertIn("emitter/cdem_last_fire_circle_tra_n90012", doc.emitter_names())
        self.assertIn("emitter/cdem_material_firefly_alpha_uberstandard", doc.emitter_names(), "an emitter not renamed keeps its name")
        embedded = doc.root.child("_emitterVariationDataArray")[0].child("_internalEmitterData")
        self.assertEqual(embedded.type_name, "/effect/binary__/emitter/cdem_last_fire_circle_tra_n90012.paem")
        self.assertEqual(emitter_paths_of(doc), (
            "effect/binary__/emitter/cdem_last_fire_circle_tra_n90012.paem",
            "effect/binary__/emitter/cdem_material_firefly_alpha_uberstandard.paem",
        ))
        with self.assertRaises(EffectEditError):
            rename_effect_strings(data, {"fx_hit_common_fire_attach_a_loop": "short"})

    def test_an_emitter_renames_its_own_name(self) -> None:
        data = TRAIL.read_bytes()
        renamed = rename_effect_strings(data, {"cdem_last_fire_circle_trail_001a": "cdem_last_fire_circle_tra_n90012"})
        doc = decode_effect_binary(renamed)
        self.assertTrue(doc.walk_complete, doc.walk_note)
        self.assertEqual(doc.root.value("_emitterDataName").value, "emitter/cdem_last_fire_circle_tra_n90012")


class PresetTests(unittest.TestCase):
    def test_the_effect_names_its_render_preset_and_the_preset_decodes(self) -> None:
        doc = decode_effect_binary(EFFECT.read_bytes())
        self.assertIn(("render", "fx_fire_uber_ember_01"), preset_names_of(doc))
        self.assertEqual(preset_path("render", "fx_fire_uber_ember_01"), "effect/binary__/renderpreset/fx_fire_uber_ember_01.parg")
        self.assertEqual(preset_path("simulation", "butterfly"), "effect/binary__/simulationpreset/butterfly.pasg")
        preset = decode_effect_binary(PRESET.read_bytes())
        self.assertTrue(preset.walk_complete, preset.walk_note)
        self.assertEqual(preset.root_type, "EmitterRenderGroupData")
        self.assertIsNotNone(preset.root.value("_emissiveBrightness"))

    def test_a_preset_name_is_renamed_as_a_whole_string_value(self) -> None:
        data = EFFECT.read_bytes()
        renamed = rename_string_values(data, {"fx_fire_uber_ember_01": "fx_fire_uber_e_n90021"})
        self.assertEqual(len(renamed), len(data))
        doc = decode_effect_binary(renamed)
        self.assertTrue(doc.walk_complete)
        self.assertIn(("render", "fx_fire_uber_e_n90021"), preset_names_of(doc))
        self.assertNotIn(("render", "fx_fire_uber_ember_01"), preset_names_of(doc))
        with self.assertRaises(EffectEditError):
            rename_string_values(data, {"fx_fire_uber_ember_01": "short"})

    def test_a_colour_sets_the_override_flag_and_edits_the_preset_too(self) -> None:
        emitter, report = apply_effect_look(EMBER.read_bytes(), EffectLook(color=(0.2, 0.4, 1.0)))
        self.assertGreaterEqual(report.edited.get("_overridePresetColor", 0), 1)
        flags = [value.value for value in decode_effect_binary(emitter).root.all_values() if value.name == "_overridePresetColor"]
        self.assertTrue(flags and all(flags))
        preset, report = apply_effect_look(PRESET.read_bytes(), EffectLook(intensity=3.0))
        self.assertGreaterEqual(report.edited.get("_emissiveBrightness", 0), 1)
        before = decode_effect_binary(PRESET.read_bytes()).root.value("_emissiveBrightness").value
        after = decode_effect_binary(preset).root.value("_emissiveBrightness").value
        self.assertEqual(tuple(round(v, 4) for v in after), tuple(round(v * 3.0, 4) for v in before))


class LookTests(unittest.TestCase):
    def test_the_default_look_changes_nothing(self) -> None:
        data = EMBER.read_bytes()
        out, report = apply_effect_look(data, EffectLook())
        self.assertEqual(out, data)
        self.assertEqual(report.total, 0)

    def test_colour_keeps_the_brightness_and_takes_the_hue(self) -> None:
        data = EMBER.read_bytes()
        out, report = apply_effect_look(data, EffectLook(color=(0.0, 0.5, 1.0)))
        self.assertEqual(len(out), len(data))
        self.assertGreaterEqual(report.edited.get("_emissiveColor", 0), 1)
        before = _values(data, "_emissiveColor")[0]
        after = _values(out, "_emissiveColor")[0]
        self.assertAlmostEqual(max(after), max(before), places=6, msg="the peak component is kept")
        self.assertAlmostEqual(after[0], 0.0, places=6)
        self.assertAlmostEqual(after[1] / after[2], 0.5, places=4)
        self.assertTrue(decode_effect_binary(out).walk_complete)

    def test_factors_multiply_what_they_name(self) -> None:
        data = EMBER.read_bytes()
        look = EffectLook(intensity=2.0, size=0.5, rate=3.0, lifetime=1.5)
        out, report = apply_effect_look(data, look)
        self.assertEqual(len(out), len(data))
        for name in ("_emissiveBrightness", "_scaleMin", "_scaleMax", "_spawnCountMin", "_spawnCountMax", "_lifeTimeMin", "_lifeTimeMax"):
            self.assertGreaterEqual(report.edited.get(name, 0), 1, name)
        self.assertEqual(_values(out, "_emissiveBrightness")[0], tuple(v * 2.0 for v in _values(data, "_emissiveBrightness")[0]))
        self.assertEqual(_values(out, "_scaleMax")[0], tuple(v * 0.5 for v in _values(data, "_scaleMax")[0]))
        self.assertEqual(_values(out, "_spawnCountMin")[0], 9, "3 x 3")
        self.assertAlmostEqual(_values(out, "_lifeTimeMax")[0], 0.9 * 1.5, places=5)
        boxes = _values(out, "_emitterBoundingBoxMax")
        self.assertTrue(boxes)
        self.assertTrue(decode_effect_binary(out).walk_complete)

    def test_the_effect_file_edits_its_own_boxes_and_overrides(self) -> None:
        data = EFFECT.read_bytes()
        out, report = apply_effect_look(data, EffectLook(size=2.0, rate=2.0))
        before = decode_effect_binary(data).root.value("_boundingBoxMax").value
        after = decode_effect_binary(out).root.value("_boundingBoxMax").value
        self.assertEqual(tuple(round(v, 4) for v in after), tuple(round(v * 2.0, 4) for v in before))
        self.assertGreaterEqual(report.edited.get("_spawnCountMin", 0), 1, "the embedded override carries spawn counts")

    def test_a_broken_file_is_refused(self) -> None:
        with self.assertRaises((EffectEditError, ValueError)):
            apply_effect_look(b"PARC" + b"\x00" * 60, EffectLook(intensity=2.0))


if __name__ == "__main__":
    unittest.main()
