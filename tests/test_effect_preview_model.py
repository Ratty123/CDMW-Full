"""The approximate simulation description read out of an effect for the viewport preview."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from cdmw.core.effect_binary import decode_effect_binary
from cdmw.core.effect_edit import apply_effect_look, emitter_layout_of
from cdmw.domain.new_item.spec import EffectLook
from cdmw.services.effect_preview_model import CURVE_SAMPLES, build_effect_preview, curve_samples, effect_preview_json

FIXTURES = Path(__file__).parent / "fixtures" / "effects"
EFFECT = FIXTURES / "fx_hit_common_fire_attach_a_loop.pae"
TRAIL = FIXTURES / "cdem_last_fire_circle_trail_001a.paem"
TRAIL_PATH = "effect/binary__/emitter/cdem_last_fire_circle_trail_001a.paem"
PRESET = FIXTURES / "fx_fire_uber_ember_01.parg"


class CurveTests(unittest.TestCase):
    def test_samples_span_the_curve_evenly(self) -> None:
        import struct
        raw = struct.pack("<8e", 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5)  # 8 one-component samples
        samples = curve_samples(raw, 1, count=4)
        self.assertEqual([round(s[0], 3) for s in samples], [0.0, 1.167, 2.333, 3.5])
        self.assertEqual(curve_samples(b"", 1), ())


class TemperatureRampTests(unittest.TestCase):
    """The colour curve's fourth channel is a temperature and the ramp is written over a
    normalised one, but the corpus gives no single unit: across forty shipped effects the
    channel tops out at 1.4 on one fire, 10 on an aura, 268 on another and 2039 on a third.
    Reading it over a fixed 1000 put most curves at the bottom of their ramp, which is where
    the ramp is nearly black."""

    RAMP = (
        ((0.0, 0.0), (1.0, 1.0)),
        ((0.0, 0.0), (1.0, 0.2)),
        ((0.0, 0.0), (1.0, 0.05)),
        ((0.0, 0.0), (1.0, 1.0)),
    )

    def test_a_curve_that_never_reaches_a_thousand_still_reads_its_ramp(self) -> None:
        from cdmw.services.effect_preview_model import _colors_over_life

        curve = [(0.001, 0.0, 0.0, 0.5), (0.002, 0.0, 0.0, 1.4)]
        colours = _colors_over_life(curve, self.RAMP, 1.0, (1.0, 1.0, 1.0))
        hottest = colours[-1]
        self.assertGreater(hottest[0], 0.9, "the hottest sample reads the top of its own ramp")
        self.assertGreater(hottest[0], hottest[1] * 2.0, "and the ramp's own hue is warm")
        self.assertGreater(hottest[1], hottest[2])
        self.assertLess(colours[0][0], hottest[0], "a cooler sample stays lower on the ramp")

    def test_a_flat_temperature_reads_the_top_rather_than_the_bottom(self) -> None:
        from cdmw.services.effect_preview_model import _colors_over_life

        curve = [(0.0, 0.0, 0.0, 10.0), (0.0, 0.0, 0.0, 10.0)]
        colours = _colors_over_life(curve, self.RAMP, 1.0, (1.0, 1.0, 1.0))
        self.assertTrue(all(sample[0] > 0.9 for sample in colours))

    def test_without_a_temperature_the_emissive_colour_carries_the_hue(self) -> None:
        from cdmw.services.effect_preview_model import _colors_over_life

        curve = [(0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)]
        colours = _colors_over_life(curve, self.RAMP, 1.0, (0.3, 0.6, 0.9))
        self.assertEqual(colours, ((0.3, 0.6, 0.9), (0.3, 0.6, 0.9)))


class PreviewTests(unittest.TestCase):
    def _preview(self, effect_bytes: bytes, trail_bytes: bytes, *, with_preset: bool = True, preset_bytes: bytes = b""):
        document = decode_effect_binary(effect_bytes)
        trail = decode_effect_binary(trail_bytes)
        presets = {"fx_fire_uber_ember_01": decode_effect_binary(preset_bytes or PRESET.read_bytes())} if with_preset else {}
        return build_effect_preview(
            "fx_hit_common_fire_attach_a_loop", document,
            emitter_documents={TRAIL_PATH: trail}, layouts={TRAIL_PATH: emitter_layout_of(trail)}, preset_documents=presets,
            meshes={"effect/mesh/pafx_m_ds_firesword_trail_002a.pam": [(0.0, 0.0, 0.0), (0.0, 0.0, -0.5), (0.0, 0.0, -1.0)]},
        )

    def test_the_named_render_preset_fills_in_behind_the_emitter_file(self) -> None:
        with_preset = self._preview(EFFECT.read_bytes(), TRAIL.read_bytes(), with_preset=True)
        without = self._preview(EFFECT.read_bytes(), TRAIL.read_bytes(), with_preset=False)
        self.assertEqual(with_preset.emitters[0].texture, "effect/texture/pafx_fire_003a_kjd.dds", "the emitter file's material wins over the preset's")
        self.assertEqual(without.emitters[0].texture, "effect/texture/pafx_fire_003a_kjd.dds")
        # the preset's emissive brightness (0.05) is read where the emitter leaves it to the preset;
        # the trail's own render data carries 0.1 so that one stays
        self.assertAlmostEqual(with_preset.emitters[0].brightness, 0.1, places=5)
        self.assertEqual(len(without.notes), 1, "the firefly emitter file is not a fixture, and the preview says so")
        self.assertIn("cdem_material_firefly_alpha_uberstandard.paem is not in the archives", without.notes[0])
        self.assertIn("what a shipped emitter typically does", without.notes[0], "and what it stands in with")
        alone = build_effect_preview("x", decode_effect_binary(EFFECT.read_bytes()))
        self.assertEqual(len(alone.notes), 2, "both emitter files missing are said")

    def test_the_optional_arguments_default_to_mappings(self) -> None:
        """They defaulted to a tuple, which answers a truth question the way an empty
        mapping does and is never asked anything else -- until an emitter names a spawn
        mesh, the one path that calls `.get` on it, and then reading the effect raised
        AttributeError instead of previewing it."""

        import inspect

        from cdmw.services.effect_preview_model import _sample_surface

        signature = inspect.signature(build_effect_preview)
        for name in ("emitter_documents", "layouts", "preset_documents", "meshes"):
            default = signature.parameters[name].default
            self.assertTrue(hasattr(default, "get"), f"{name} defaults to {default!r}, which has no .get")
            self.assertFalse(default, f"{name} defaults to something that is not empty")
        self.assertEqual(_sample_surface("effect/mesh/x.pam", signature.parameters["meshes"].default, 8), ())

    def test_the_fire_loop_reads_as_two_billboard_emitters(self) -> None:
        preview = self._preview(EFFECT.read_bytes(), TRAIL.read_bytes())
        self.assertEqual([e.name for e in preview.emitters], ["emitter/cdem_last_fire_circle_trail_001a", "emitter/cdem_material_firefly_alpha_uberstandard"])
        trail = preview.emitters[0]
        self.assertEqual(trail.kind, "billboard")
        self.assertTrue(trail.loop, "the trail emitter loops (loop count -1)")
        self.assertGreater(trail.bursts_per_second, 1.0)
        self.assertEqual(trail.burst, 10, "the effect's embedded override (10) wins over the emitter file's own 150")
        self.assertEqual(trail.texture, "effect/texture/pafx_fire_003a_kjd.dds")
        self.assertEqual(len(trail.scale_over_life), CURVE_SAMPLES)
        self.assertEqual(len(trail.color_over_life), CURVE_SAMPLES)
        self.assertEqual(len(trail.alpha_over_life), CURVE_SAMPLES)
        firefly = preview.emitters[1]
        self.assertGreater(firefly.force[1][1], 0.0, "the fireflies are pushed upward")
        # the firefly's emitter file is not a fixture, so nothing states a loop count. All
        # 208 shipped emitters that state one state -1 and none states anything else, so a
        # missing file is stood in for as looping rather than as a single burst.
        self.assertTrue(firefly.loop, "a missing emitter file is taken to loop, as every shipped one does")
        self.assertEqual(trail.spawn, "spread", "the trail names no spawn mesh in this fixture")
        self.assertTrue(all(0.0 <= a <= 1.0 for a in trail.alpha_over_life))
        self.assertGreater(trail.alpha_over_life[1], trail.alpha_over_life[-1], "alpha (curve 2) rises fast and fades")
        self.assertGreater(trail.scale_over_life[-1], trail.scale_over_life[0], "the trail grows over life (curve 5)")
        early = trail.color_over_life[2]
        self.assertGreater(early[0], early[2], "the ramp read at this curve's hottest sample is orange: red over blue")
        self.assertGreater(early[0], 0.5)
        self.assertEqual(trail.sequence, (5, 5), "the sprite is a 5 x 5 flipbook")
        self.assertAlmostEqual(trail.spawn_time, 1.0, places=4, msg="the effect's override says 1.0 s over the emitter file's 0.2")
        self.assertAlmostEqual(trail.mass, 0.011, places=3)
        self.assertAlmostEqual(trail.velocity_stretch, 0.4, places=5)
        self.assertEqual(preview.textures, ("effect/texture/pafx_fire_003a_kjd.dds",))

    def test_a_look_edit_shows_in_the_preview(self) -> None:
        plain = self._preview(EFFECT.read_bytes(), TRAIL.read_bytes())
        look = EffectLook(color=(0.1, 0.3, 1.0), size=2.0)
        effect_edited, _r = apply_effect_look(EFFECT.read_bytes(), look, emitter_layouts={TRAIL_PATH: emitter_layout_of(decode_effect_binary(TRAIL.read_bytes()))})
        trail_edited, _r = apply_effect_look(TRAIL.read_bytes(), look)
        preset_edited, _r = apply_effect_look(PRESET.read_bytes(), look)
        edited = self._preview(effect_edited, trail_edited, preset_bytes=preset_edited)
        before, after = plain.emitters[0], edited.emitters[0]
        peak_before = max(max(c) for c in before.color_over_life)
        blue_after = after.color_over_life[len(after.color_over_life) // 2]
        self.assertGreater(blue_after[2], blue_after[0], "blue is the peak channel after the recolour")
        self.assertAlmostEqual(after.scale[1][0], before.scale[1][0] * 2.0, places=5)
        self.assertGreater(peak_before, 0.0)

    def test_the_snapshot_route_reads_effect_emitters_presets_and_spawn_meshes(self) -> None:
        from cdmw.core.effect_edit import RENDER_PRESET_DIR
        from cdmw.services.effect_preview_model import preview_effect_from_snapshot
        from cdmw.services.new_item_snapshot import EFFECT_DIR

        class Snapshot:
            def __init__(self) -> None:
                self.entries = {
                    EFFECT_DIR + "fx_hit_common_fire_attach_a_loop.pae": EFFECT.read_bytes(),
                    TRAIL_PATH: TRAIL.read_bytes(),
                    RENDER_PRESET_DIR + "fx_fire_uber_ember_01.parg": PRESET.read_bytes(),
                }
                self.reads: list = []

            def has_entry(self, path: str) -> bool:
                return path in self.entries

            def payload(self, path: str) -> bytes:
                self.reads.append(path)
                return self.entries[path]

        snapshot = Snapshot()
        plain = preview_effect_from_snapshot(snapshot, "fx_hit_common_fire_attach_a_loop.pae")
        self.assertEqual(len(plain.emitters), 2)
        self.assertIn(RENDER_PRESET_DIR + "fx_fire_uber_ember_01.parg", snapshot.reads, "the named render preset was read")
        self.assertEqual(plain.emitters[0].texture, "effect/texture/pafx_fire_003a_kjd.dds")
        blue = preview_effect_from_snapshot(snapshot, "fx_hit_common_fire_attach_a_loop", EffectLook(color=(0.1, 0.3, 1.0)))
        mid = blue.emitters[0].color_over_life[len(blue.emitters[0].color_over_life) // 2]
        self.assertGreater(mid[2], mid[0], "the look is applied before the preview is read")
        with self.assertRaises(KeyError):
            preview_effect_from_snapshot(snapshot, "no_such_effect")

    def test_the_json_is_what_the_viewer_reads(self) -> None:
        preview = self._preview(EFFECT.read_bytes(), TRAIL.read_bytes())
        payload = json.loads(effect_preview_json(preview))
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["stem"], "fx_hit_common_fire_attach_a_loop")
        self.assertEqual(len(payload["emitters"]), 2)
        first = payload["emitters"][0]
        # the keys the viewer's EffectParticlePreview.cs reads (schema 1)
        for key in ("kind", "texture", "blend", "burst", "bursts_per_second", "max_particles", "life", "loop", "spawn_time", "spawn", "spread", "points",
                    "force", "damping", "speed_limit", "scale", "rotation", "scale_over_life", "alpha_over_life", "color_over_life", "emissive_color",
                    "brightness", "beam_width", "beam_jitter", "beam_length", "beam_axis", "mass", "simulation_speed", "sequence", "velocity_stretch"):
            self.assertIn(key, first)
        self.assertEqual(len(first["color_over_life"][0]), 3)
        self.assertEqual(first["sequence"], [5, 5])
        self.assertEqual(first["beam_axis"], [0.0, 0.0, 0.0], "a sprite emitter has no beam axis")


if __name__ == "__main__":
    unittest.main()
