"""Wwise sound bank reading, .bnk playback selection, and manifest-derived links."""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

from cdmw.core.archive_asset_family import (
    _asset_family_group_for_entry,
    _attachment_asset_reference_re,
)
from cdmw.core.archive_wwise_bank import (
    embedded_media_wem_basenames,
    is_sound_bank,
    read_bank_chunks,
    read_embedded_media,
)
from cdmw.core.archive_wwise_bank_preview import (
    build_sound_bank_tracks,
    decode_sound_bank_track,
    select_sound_bank_track,
)
from cdmw.domain.archives.association_vocabulary import (
    ASSET_FAMILY_GROUP_ORDER,
    asset_reference_pattern,
    reference_container_extensions,
)
from cdmw.domain.archives.content_capabilities import (
    capability_for,
    load_capabilities,
    registered_extensions,
)
from cdmw.models import ArchiveEntry


def _chunk(identifier: bytes, payload: bytes) -> bytes:
    return identifier + struct.pack("<I", len(payload)) + payload


def _bank(*, sounds: tuple[tuple[int, int, int], ...] = (), with_hirc: bool = False) -> bytes:
    parts = [_chunk(b"BKHD", struct.pack("<II", 145, 4242))]
    if sounds:
        directory = b"".join(
            struct.pack("<III", source_id, offset, size) for source_id, offset, size in sounds
        )
        parts.append(_chunk(b"DIDX", directory))
        parts.append(_chunk(b"DATA", b"\x00" * sum(size for _id, _offset, size in sounds)))
    if with_hirc:
        parts.append(_chunk(b"HIRC", struct.pack("<I", 0)))
    return b"".join(parts)


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path="pack.pamt",
        paz_file="pack.paz",
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class WwiseBankReaderTests(unittest.TestCase):
    def test_didx_table_is_read_in_decoder_subsong_order(self) -> None:
        bank = _bank(sounds=((111222333, 0, 16), (444555666, 16, 32)))
        media = read_embedded_media(bank)
        self.assertEqual([sound.ordinal for sound in media], [1, 2])
        self.assertEqual([sound.source_id for sound in media], [111222333, 444555666])
        self.assertEqual([sound.size for sound in media], [16, 32])

    def test_a_bank_names_its_sounds_by_source_id(self) -> None:
        bank = _bank(sounds=((111222333, 0, 16), (444555666, 16, 32)))
        self.assertEqual(
            embedded_media_wem_basenames(bank),
            ("111222333.wem", "444555666.wem"),
        )

    def test_an_event_only_bank_embeds_nothing_to_play(self) -> None:
        # Its audio streams from separate .wem files, so an empty table is the
        # normal shape for this bank rather than a damaged read.
        bank = _bank(with_hirc=True)
        self.assertTrue(is_sound_bank(bank))
        self.assertEqual(read_embedded_media(bank), ())
        self.assertEqual(embedded_media_wem_basenames(bank), ())

    def test_a_chunk_walk_stops_at_a_bad_identifier_instead_of_running_off(self) -> None:
        bank = _bank(sounds=((7, 0, 4),)) + b"\xff\xff\xff\xff" + struct.pack("<I", 1 << 30)
        chunks, consumed = read_bank_chunks(bank)
        self.assertEqual([chunk.identifier for chunk in chunks], ["BKHD", "DIDX", "DATA"])
        self.assertLess(consumed, len(bank))

    def test_a_truncated_chunk_is_not_reported_as_readable(self) -> None:
        truncated = _chunk(b"BKHD", struct.pack("<II", 145, 1)) + b"DIDX" + struct.pack("<I", 4096)
        chunks, _consumed = read_bank_chunks(truncated)
        self.assertEqual([chunk.identifier for chunk in chunks], ["BKHD"])

    def test_a_file_without_a_bank_header_is_not_a_bank(self) -> None:
        self.assertFalse(is_sound_bank(b"RIFF\x00\x00\x00\x00WAVE"))
        self.assertEqual(read_embedded_media(b"RIFF\x00\x00\x00\x00WAVE"), ())


class SoundBankPlaybackSelectionTests(unittest.TestCase):
    def test_tracks_are_labelled_with_their_wwise_source_id(self) -> None:
        tracks = build_sound_bank_tracks(_bank(sounds=((900, 0, 8), (901, 8, 8))))
        self.assertEqual([track.index for track in tracks], [1, 2])
        self.assertEqual([track.name for track in tracks], ["900", "901"])

    def test_a_request_for_a_sound_the_bank_lacks_falls_back_to_the_first(self) -> None:
        tracks = build_sound_bank_tracks(_bank(sounds=((900, 0, 8), (901, 8, 8))))
        self.assertEqual(select_sound_bank_track(tracks, 2), 2)
        self.assertEqual(select_sound_bank_track(tracks, 0), 1)
        self.assertEqual(select_sound_bank_track(tracks, 9), 1)

    def test_the_chosen_sound_is_decoded_as_that_subsong(self) -> None:
        seen: dict[str, object] = {}

        def ensure_media_source(source_path, extension, *, subsong, stop_event=None):
            seen["extension"] = extension
            seen["subsong"] = subsong
            return Path("decoded.wav"), "Decoded for playback with bundled vgmstream-cli."

        path, note = decode_sound_bank_track(
            _entry("sound/bank.bnk"),
            3,
            ensure_preview_source=lambda entry, stop_event=None: (Path("bank.bnk"), ""),
            ensure_media_source=ensure_media_source,
        )
        self.assertEqual(seen["subsong"], 3)
        self.assertEqual(seen["extension"], ".bnk")
        self.assertTrue(str(path).endswith("decoded.wav"))
        self.assertIn("vgmstream", note)

    def test_a_sound_the_decoder_cannot_read_keeps_the_bank_readable(self) -> None:
        def failing(source_path, extension, *, subsong, stop_event=None):
            raise ValueError("unsupported codec")

        path, note = decode_sound_bank_track(
            _entry("sound/bank.bnk"),
            2,
            ensure_preview_source=lambda entry, stop_event=None: (Path("bank.bnk"), ""),
            ensure_media_source=failing,
        )
        self.assertIsNone(path)
        self.assertIn("unsupported codec", note)


class CapabilityManifestTests(unittest.TestCase):
    def test_the_manifest_is_readable_and_registers_every_extension_once(self) -> None:
        capabilities = load_capabilities()
        self.assertGreater(len(capabilities), 100)
        extensions = [capability.extension for capability in capabilities]
        self.assertEqual(len(extensions), len(set(extensions)))

    def test_a_sound_bank_declares_playback_and_a_wav_export(self) -> None:
        capability = capability_for(".bnk")
        self.assertIsNotNone(capability)
        self.assertTrue(capability.playback)
        self.assertIn("wav", capability.exports)

    def test_registered_extensions_are_ordered_longest_first(self) -> None:
        lengths = [len(extension) for extension in registered_extensions()]
        self.assertEqual(lengths, sorted(lengths, reverse=True))


class AssetReferenceVocabularyTests(unittest.TestCase):
    def test_a_reference_is_followed_whole_and_never_clipped_short(self) -> None:
        # Each clipped target is a real registered format, so a pattern that
        # stops early names a file that can exist and is not the one referenced.
        for text, expected, clipped in (
            ("world/mesh.paem", "world/mesh.paem", "world/mesh.pae"),
            ("city.paccd", "city.paccd", "city.pac"),
            ("crate.prefab_xml", "crate.prefab_xml", "crate.prefab"),
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(capability_for(Path(clipped).suffix))
                match = asset_reference_pattern().search(text)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), expected)
                self.assertNotEqual(match.group(1), clipped)

    def test_the_asset_family_pattern_is_the_manifest_derived_one(self) -> None:
        match = _attachment_asset_reference_re().search("world/level.pat")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "world/level.pat")

    def test_a_two_extension_sidecar_matches_as_one_name(self) -> None:
        for text in ("armor.prefabdata.xml", "body.sockets.xml", "head.pac.xml"):
            with self.subTest(text=text):
                match = asset_reference_pattern().search(text)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), text)

    def test_a_bank_is_scanned_for_references_but_pixels_and_samples_are_not(self) -> None:
        containers = reference_container_extensions()
        self.assertIn(".bnk", containers)
        self.assertNotIn(".dds", containers)
        self.assertNotIn(".wem", containers)


class AssetFamilyGroupingTests(unittest.TestCase):
    def test_a_registered_format_no_named_rule_covers_still_reaches_a_group(self) -> None:
        for path, extension, expected in (
            ("world/terrain.pat", ".pat", "Selected Model"),
            ("world/area.levelinfo", ".levelinfo", "Prefab / Metadata"),
            ("sound/voice.wem", ".wem", "Audio / Video"),
            ("sound/bank.bnk", ".bnk", "Audio / Video"),
        ):
            with self.subTest(extension=extension):
                entry = _entry(path)
                self.assertEqual(_asset_family_group_for_entry(entry), expected)

    def test_every_group_a_classifier_can_produce_is_rendered(self) -> None:
        # The panel and the dialog render only the groups this order names, so a
        # group the classifier can return but the order omits would be computed
        # and then silently dropped.
        produced = {
            _asset_family_group_for_entry(_entry(f"a/b{extension}"))
            for extension in registered_extensions()
        }
        self.assertTrue(produced)
        self.assertLessEqual(produced, set(ASSET_FAMILY_GROUP_ORDER))


if __name__ == "__main__":
    unittest.main()
