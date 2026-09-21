"""The effect binary decoder: two shipped files walk to the byte, and what they say."""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

from cdmw.core.effect_binary import (
    KIND_ARRAY,
    KIND_STRING,
    EffectBinaryError,
    decode_effect_binary,
    half_floats,
    write_value,
)

FIXTURES = Path(__file__).parent / "fixtures" / "effects"
EFFECT = FIXTURES / "fx_hit_common_fire_attach_a_loop.pae"
EMITTER = FIXTURES / "cdem_standard_fire_large_fire_ember_001a.paem"


class EmitterDecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = EMITTER.read_bytes()
        self.doc = decode_effect_binary(self.data)

    def test_the_walk_closes_the_blob(self) -> None:
        self.assertTrue(self.doc.walk_complete, self.doc.walk_note)
        self.assertEqual(self.doc.root_type, "EmitterData")
        self.assertEqual(self.doc.container_offset, 16)
        self.assertEqual(self.doc.byte_length, len(self.data))
        self.assertGreater(sum(1 for _ in self.doc.root.walk()), 100)

    def test_the_emitter_names_itself_and_its_textures(self) -> None:
        name = self.doc.root.value("_emitterDataName")
        self.assertIsNotNone(name)
        self.assertEqual(name.value, "emitter/cdem_standard_fire_large_fire_ember_001a")
        self.assertIn("effect/texture/pafx_fire_003a_kjd.dds", self.doc.resources())
        self.assertIn("effect/vectorfield/vectorfield.dds", self.doc.resources())

    def test_spawn_simulation_and_render_values_decode_by_type(self) -> None:
        spawn = next(self.doc.root.find("EmitterSpawnData"))
        self.assertEqual(spawn.value("_loopCount").value, -1)
        self.assertEqual(spawn.value("_spawnCountMin").value, 3)
        self.assertEqual(spawn.value("_maxParticleCount").value, 165)
        self.assertAlmostEqual(spawn.value("_lifeTimeMin").value, 0.3, places=5)
        self.assertAlmostEqual(spawn.value("_lifeTimeMax").value, 0.9, places=5)
        simulation = next(self.doc.root.find("EmitterSimulationData"))
        self.assertEqual(tuple(round(v, 3) for v in simulation.value("_scaleMax").value), (0.6, 0.6, 0.6))
        render = next(self.doc.root.find("EmitterRenderData"))
        colour = render.value("_emissiveColor").value
        self.assertEqual(tuple(round(v, 3) for v in colour), (0.371, 0.05, 0.005))
        self.assertEqual(render.value("_emissiveLightPreset").value, "Aura")
        self.assertEqual(render.value("_emissiveLightPreset").kind, KIND_STRING)

    def test_material_parameters_are_named_and_typed(self) -> None:
        material = next(self.doc.root.find("Material"))
        self.assertEqual(material.value("_materialName").value, "EffectUberStandard_DisableDepth")
        parameters = material.child("_parameters")
        self.assertIsInstance(parameters, tuple)
        names = [node.value("_name").value for node in parameters]
        self.assertIn("_textureEmissive", names)
        self.assertIn("_emissiveIntensityExponent", names)
        exponent = next(node for node in parameters if node.value("_name").value == "_emissiveIntensityExponent")
        self.assertEqual(exponent.value("_value").value, 5.0)
        emissive = next(node for node in parameters if node.value("_name").value == "_textureEmissive")
        path_node = emissive.child("_value")
        self.assertEqual(path_node.value("_path").value, "effect/texture/pafx_fire_003a_kjd.dds")

    def test_curves_are_half_float_sample_arrays(self) -> None:
        curves = self.doc.root.child("_curveEntryDataList")
        self.assertIsInstance(curves, tuple)
        self.assertEqual(len(curves), 12)
        first = curves[0].value("_splineData")
        self.assertEqual(first.kind, KIND_ARRAY)
        self.assertEqual(first.count, 128)
        samples = half_floats(first.raw)
        self.assertEqual(len(samples), 128)
        self.assertEqual(samples[0], 0.0)
        self.assertGreater(samples[10], samples[1])
        # an entry with a preset name and no baked samples keeps its null array
        preset = next(node for node in curves if node.value("_presetName") and node.value("_presetName").value)
        self.assertEqual(preset.value("_presetName").value, "splinedata/2d/linear")
        self.assertEqual(preset.value("_splineData").count, 0)

    def test_a_value_writes_back_in_place_and_reads_again(self) -> None:
        render = next(self.doc.root.find("EmitterRenderData"))
        colour = render.value("_emissiveColor")
        edited = write_value(self.data, colour, struct.pack("<3f", 0.1, 0.8, 0.2))
        self.assertEqual(len(edited), len(self.data))
        again = decode_effect_binary(edited)
        self.assertTrue(again.walk_complete, again.walk_note)
        new_colour = next(again.root.find("EmitterRenderData")).value("_emissiveColor")
        self.assertEqual(tuple(round(v, 3) for v in new_colour.value), (0.1, 0.8, 0.2))
        self.assertEqual(new_colour.offset, colour.offset)
        with self.assertRaises(EffectBinaryError):
            write_value(self.data, colour, b"\x00" * 8)


class EffectDecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = decode_effect_binary(EFFECT.read_bytes())

    def test_the_effect_walks_and_names_its_emitters(self) -> None:
        self.assertTrue(self.doc.walk_complete, self.doc.walk_note)
        self.assertEqual(self.doc.root_type, "EffectData")
        self.assertEqual(self.doc.root.value("_effectDataName").value, "fx/materialfx/fx_hit_common_fire_attach_a_loop")
        self.assertEqual(
            self.doc.emitter_names(),
            ("emitter/cdem_last_fire_circle_trail_001a", "emitter/cdem_material_firefly_alpha_uberstandard"),
        )

    def test_the_bounding_box_and_flags(self) -> None:
        low = self.doc.root.value("_boundingBoxMin").value
        high = self.doc.root.value("_boundingBoxMax").value
        self.assertEqual(tuple(round(v, 2) for v in low), (-1.24, -1.24, -1.39))
        self.assertEqual(tuple(round(v, 2) for v in high), (1.26, 1.29, 1.25))
        variations = self.doc.root.child("_emitterVariationDataArray")
        self.assertEqual(len(variations), 2)
        self.assertTrue(variations[0].value("_isOverrideEmitter").value)

    def test_an_embedded_emitter_is_typed_by_its_file_and_carries_overrides(self) -> None:
        variation = self.doc.root.child("_emitterVariationDataArray")[0]
        embedded = variation.child("_internalEmitterData")
        self.assertEqual(embedded.type_name, "/effect/binary__/emitter/cdem_last_fire_circle_trail_001a.paem")
        curves = embedded.child("_curveEntryDataList")
        self.assertEqual(len(curves), 11)
        # nine entries are untouched deltas, one overrides its samples, one is the
        # effect's own curve, and the whole list closes on the byte
        self.assertEqual(sum(1 for node in curves if node.override == 1 and node.mask == 0), 9)
        overridden = [node for node in curves if node.override == 1 and node.mask]
        self.assertEqual(len(overridden), 1)
        self.assertEqual(overridden[0].value("_splineData").count, 512)
        own = [node for node in curves if node.override == 0]
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0].value("_componentCount").value, 2)

    def test_a_bare_body_without_the_parc_header_decodes_too(self) -> None:
        body = EFFECT.read_bytes()[16:]
        doc = decode_effect_binary(body)
        self.assertTrue(doc.walk_complete, doc.walk_note)
        self.assertEqual(doc.container_offset, 0)
        self.assertEqual(doc.root.value("_boundingBoxMin").offset, self.doc.root.value("_boundingBoxMin").offset - 16)

    def test_garbage_is_refused_not_walked(self) -> None:
        with self.assertRaises(EffectBinaryError):
            decode_effect_binary(b"PARC" + b"\x00" * 40)


class WidePresenceMaskTests(unittest.TestCase):
    @staticmethod
    def _payload() -> bytes:
        from cdmw.core.prefab_binary import PrefabMember, PrefabType
        from cdmw.core.prefab_component_graft import encode_prefab_type

        kind = PrefabType("EffectData", tuple(
            PrefabMember(f"_value{i}", "float", 0, 4, 0, 0) for i in range(72)
        ), 0)
        prefix = struct.pack("<HHH", 0xFFFF, 4, 0) + bytes(8) + struct.pack("<IH", 15, 1)
        prefix += encode_prefab_type(kind) + struct.pack("<I", 0)
        mask = (1 << 0) | (1 << 64) | (1 << 71)
        blob = struct.pack("<H", 9) + mask.to_bytes(9, "little") + struct.pack("<HBB3f", 0, 0, 0, 1., 2., 3.)
        offset = len(prefix) + 28
        header = struct.pack("<IIIQII", 1, offset + len(blob), 0, 0xFFFFFFFFFFFFFFFF, offset, len(blob))
        return b"PARC" + struct.pack("<IQ", 1, 0) + prefix + header + blob

    def test_ninth_mask_byte_roundtrips_and_edits_high_fields(self) -> None:
        from cdmw.core.effect_writer import serialize_effect, set_typed_value

        source = self._payload()
        doc = decode_effect_binary(source)
        self.assertTrue(doc.walk_complete, doc.walk_note)
        self.assertTrue(decode_effect_binary(source, metadata_only=True).walk_complete)
        self.assertEqual([1., 2., 3.], [doc.root.value(f"_value{i}").value for i in (0, 64, 71)])
        self.assertEqual(source, serialize_effect(source, doc))
        self.assertTrue(set_typed_value(doc, doc.root, "_value71", 9.))
        again = decode_effect_binary(serialize_effect(source, doc))
        self.assertEqual(9., again.root.value("_value71").value)
        self.assertEqual(2., again.root.value("_value64").value)
        self.assertEqual(9, again.root.wire["width"])

    def test_unproven_mask_widths_remain_blocked(self) -> None:
        from cdmw.core.effect_writer import serialize_effect

        source = self._payload()
        doc = decode_effect_binary(source)
        for width in (0, 10):
            with self.subTest(width=width):
                broken = bytearray(source)
                struct.pack_into("<H", broken, doc.blob_offset, width)
                result = decode_effect_binary(bytes(broken))
                self.assertFalse(result.walk_complete)
                self.assertIn("mask width", result.walk_note)
        doc.root.wire["width"] = 10
        with self.assertRaisesRegex(EffectBinaryError, "72 fields"):
            serialize_effect(source, doc)


class CollectionLookupTests(unittest.TestCase):
    @staticmethod
    def _payload(with_ids: bool) -> bytes:
        from cdmw.core.prefab_binary import PrefabMember, PrefabType
        from cdmw.core.prefab_component_graft import encode_prefab_type

        types = (
            PrefabType("EffectData", (PrefabMember("_items", "CurveData", 7, 0, 0, 0),), 0),
            PrefabType("CurveData", (PrefabMember("_value", "float", 0, 4, 0, 0),), 0),
        )
        prefix = struct.pack("<HHH", 0xFFFF, 4, 0) + bytes(8) + struct.pack("<IH", 15, 2)
        prefix += b"".join(encode_prefab_type(t) for t in types) + struct.pack("<I", 0)
        base = len(prefix) + 28
        blob = bytearray(struct.pack("<HBHBB", 1, 0, 0, 0, 0))
        blob += struct.pack("<BIBIII", 0, 2, int(with_ids), 20, 0, 1)
        # Slot 13 belongs to the inherited collection, not our two overrides.
        blob += struct.pack("<Q", 0x000DA6117BEFFFFE) if with_ids else struct.pack("<II", 13, 0)
        if with_ids:
            blob += struct.pack("<I", 13)
        for index in range(2):
            blob += struct.pack("<HBHB", 1, 1, 1, 1)
            if with_ids:
                blob += struct.pack("<I", index + 3)
            blob += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
            blob += struct.pack("<I", base + len(blob) + 4)
            pointee = len(blob)
            blob += struct.pack("<HHf", 0, 0, float(index + 1))
            blob += struct.pack("<I", len(blob) - pointee)
        header = struct.pack("<IIIQII", 1, base + len(blob), 0, 0xFFFFFFFFFFFFFFFF, base, len(blob))
        return b"PARC" + struct.pack("<IQ", 1, 0) + prefix + header + blob

    def test_inherited_lookup_tables_roundtrip_and_allow_value_edits(self) -> None:
        from cdmw.core.effect_writer import serialize_effect, set_typed_value

        for with_ids in (False, True):
            with self.subTest(with_ids=with_ids):
                source = self._payload(with_ids)
                doc = decode_effect_binary(source)
                self.assertTrue(doc.walk_complete, doc.walk_note)
                self.assertEqual(source, serialize_effect(source, doc))
                lookup = dict(doc.root.wire["_items"])
                self.assertEqual(4 if with_ids else 0, len(lookup["indices"]))
                set_typed_value(doc, doc.root.child("_items")[0], "_value", 4.)
                after = decode_effect_binary(serialize_effect(source, doc))
                self.assertEqual(4., after.root.child("_items")[0].value("_value").value)
                self.assertEqual(lookup, after.root.wire["_items"])

    def test_lookup_metadata_cannot_be_reordered_resized_or_rewritten(self) -> None:
        from cdmw.core.effect_writer import serialize_effect

        for with_ids in (False, True):
            for change in ("reorder", "resize", "clear", "lookup", "remove_lookup"):
                with self.subTest(with_ids=with_ids, change=change):
                    source = self._payload(with_ids)
                    doc = decode_effect_binary(source)
                    children = doc.root.child("_items")
                    if change == "reorder":
                        doc.root.children = [("_items", tuple(reversed(children)))]
                    elif change == "resize":
                        doc.root.children = [("_items", children[:1])]
                    elif change == "clear":
                        doc.root.children = [("_items", None)]
                    elif change == "lookup":
                        doc.root.wire["_items"]["pairs"] = bytes(8)
                    else:
                        doc.root.wire["_items"].update(pairs=b"", indices=b"")
                    with self.assertRaisesRegex(EffectBinaryError, "lookup table"):
                        serialize_effect(source, doc)


class ShippedEffectCorpusTests(unittest.TestCase):
    """Every effect and emitter the game ships walks to its last byte."""

    def test_the_whole_corpus_closes(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        import os

        if os.environ.get("CDMW_EFFECT_CORPUS") != "1":
            self.skipTest("set CDMW_EFFECT_CORPUS=1 to walk the 6,855 shipped effect files (minutes)")
        total = complete = 0
        failures: list[str] = []
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if not path.startswith("effect/binary__/") or not path.endswith((".pae", ".paem")):
                continue
            total += 1
            doc = decode_effect_binary(read_archive_entry_data(entry)[0])
            if doc.walk_complete:
                complete += 1
            elif len(failures) < 10:
                failures.append(f"{path}: {doc.walk_note}")
        self.assertGreater(total, 6000)
        self.assertEqual(complete, total, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
