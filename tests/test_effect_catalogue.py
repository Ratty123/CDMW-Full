"""The effect catalogue: facts from a decoded effect, search, and the on-disk cache."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cdmw.core.effect_binary import decode_effect_binary
from cdmw.services.effect_catalogue import (
    CATALOGUE_SCHEMA,
    EffectCatalogue,
    EffectFacts,
    effect_facts_from_document,
    load_effect_catalogue,
    save_effect_catalogue,
)

FIXTURE = Path(__file__).parent / "fixtures" / "effects" / "fx_hit_common_fire_attach_a_loop.pae"


class EffectFactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = effect_facts_from_document("fx_hit_common_fire_attach_a_loop", decode_effect_binary(FIXTURE.read_bytes()))

    def test_facts_come_from_the_binary(self) -> None:
        self.assertEqual(self.facts.name, "fx/materialfx/fx_hit_common_fire_attach_a_loop")
        self.assertEqual(self.facts.emitters, ("emitter/cdem_last_fire_circle_trail_001a", "emitter/cdem_material_firefly_alpha_uberstandard"))
        self.assertEqual(self.facts.textures, ("effect/vectorfield/pafx_vector_chaos_01a.dds",))
        self.assertEqual(self.facts.meshes, ())
        self.assertEqual(tuple(round(v, 2) for v in self.facts.size), (2.5, 2.53, 2.64))
        self.assertTrue(self.facts.infinite_emitter, "an emitter with loop count -1 loops")
        self.assertTrue(self.facts.loops)
        self.assertEqual(self.facts.walk_note, "")
        self.assertGreater(self.facts.byte_length, 20000)

    def test_search_matches_every_word_over_stem_emitters_and_textures(self) -> None:
        self.assertTrue(self.facts.matches(""))
        self.assertTrue(self.facts.matches("fire attach"))
        self.assertTrue(self.facts.matches("firefly"))
        self.assertTrue(self.facts.matches("vector_chaos"))
        self.assertTrue(self.facts.matches("FIRE Circle"))
        self.assertFalse(self.facts.matches("fire lightning"))
        catalogue = EffectCatalogue(facts={self.facts.stem: self.facts})
        self.assertEqual([item.stem for item in catalogue.search("ember")], [])
        self.assertEqual([item.stem for item in catalogue.search("circle")], [self.facts.stem])
        self.assertIs(catalogue.get(self.facts.stem), self.facts)
        self.assertIsNone(catalogue.get("nothing"))


class CatalogueCacheTests(unittest.TestCase):
    def test_save_and_load_round_trip_and_the_signature_gate(self) -> None:
        facts = effect_facts_from_document("fx_a", decode_effect_binary(FIXTURE.read_bytes()))
        broken = EffectFacts(
            stem="fx_b", name="", emitters=(), textures=(), meshes=(), box_min=(0.0, 0.0, 0.0), box_max=(0.0, 0.0, 0.0),
            infinite_emitter=False, infinite_particle=False, has_lights=False, max_spawnable_time=0.0, life_cycle_time=0.0,
            byte_length=0, walk_note="unexpected magic",
        )
        catalogue = EffectCatalogue(facts={"fx_a": facts, "fx_b": broken}, signature=f"{CATALOGUE_SCHEMA}:2:12345")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sub" / "effects.json"
            save_effect_catalogue(catalogue, path)
            loaded = load_effect_catalogue(path)
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded.get("fx_a").emitters, facts.emitters)
            self.assertEqual(loaded.get("fx_a").box_max, facts.box_max)
            self.assertEqual(loaded.get("fx_b").walk_note, "unexpected magic")
            self.assertEqual(loaded.signature, catalogue.signature)
            self.assertIsNotNone(load_effect_catalogue(path, signature=catalogue.signature))
            self.assertIsNone(load_effect_catalogue(path, signature="1:3:999"), "another effect population")
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(load_effect_catalogue(path))
            self.assertIsNone(load_effect_catalogue(Path(folder) / "missing.json"))


if __name__ == "__main__":
    unittest.main()
