"""HIRC decoding and constrained bank writes, on owned synthetic version-150 banks."""
from __future__ import annotations

import struct

import pytest

from cdmw.core.archive_audio import _build_pcm_wem, build_wwise_media_replacement
from cdmw.core.archive_wwise_bank import read_bank_chunks, read_bank_embedded_bytes, read_embedded_media
from cdmw.core.archive_wwise_bank_edit import (
    HircEdit,
    WwiseBankEditError,
    apply_hirc_edits,
    replace_embedded_media,
    retarget_loose_media,
)
from cdmw.core.archive_wwise_hirc import (
    FRAMED,
    MISMATCH,
    PARSED,
    hirc_graph_preview_lines,
    read_hirc_graph,
)
from cdmw.models import ArchiveEntry

VORBIS = 0x00040001
PCM = 0x00010001


def chunk(identifier: bytes, body: bytes) -> bytes:
    return identifier + struct.pack("<I", len(body)) + body


def wem(payload: bytes, *, tag: int = 0xFFFF, channels: int = 1, rate: int = 48000) -> bytes:
    fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * 2, 2, 16) + b"\x00" * 0x32
    body = b"WAVE" + chunk(b"fmt ", fmt) + chunk(b"data", payload)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def props(entries) -> bytes:
    ids = bytes(prop_id for prop_id, _value in entries)
    values = b"".join(struct.pack("<f" if isinstance(value, float) else "<I", value) for _prop_id, value in entries)
    return bytes([len(entries)]) + ids + values


def ranged(entries) -> bytes:
    ids = bytes(prop_id for prop_id, _low, _high in entries)
    values = b"".join(struct.pack("<ff", low, high) for _prop_id, low, high in entries)
    return bytes([len(entries)]) + ids + values


def node_base(*, parent: int = 0, properties=(), ranges=(), positioning: bytes = b"\x00", rtpc: bytes = b"\x00\x00") -> bytes:
    return (
        b"\x00\x00"  # FX: override, count
        + b"\x00\x00"  # metadata: override, count
        + struct.pack("<II", 0, parent)  # bus, parent
        + b"\x00"  # priority bits
        + props(properties)
        + ranged(ranges)
        + positioning
        + b"\x00" + struct.pack("<I", 0)  # aux bits, reflections bus
        + b"\x00\x00\x00\x00\x00\x00"  # advanced settings
        + b"\x00\x00"  # state props, state groups (varints)
        + rtpc
    )


def hirc_object(kind: int, object_id: int, body: bytes) -> bytes:
    payload = struct.pack("<I", object_id) + body
    return struct.pack("<BI", kind, len(payload)) + payload


def source(source_id: int, size: int, *, plugin: int = VORBIS, stream: int = 0) -> bytes:
    return struct.pack("<IBIIB", plugin, stream, source_id, size, 0)


def sound(object_id: int, source_id: int, size: int, *, plugin: int = VORBIS, stream: int = 0, properties=()) -> bytes:
    return hirc_object(2, object_id, source(source_id, size, plugin=plugin, stream=stream) + node_base(parent=500, properties=properties))


def play_action(object_id: int, target: int) -> bytes:
    body = struct.pack("<HIB", 0x0403, target, 0) + props([(0x39, 250)]) + ranged([]) + b"\x04" + struct.pack("<II", 77, 0)
    return hirc_object(3, object_id, body)


def set_volume_action(object_id: int, target: int) -> bytes:
    body = struct.pack("<HIB", 0x0A02, target, 0) + props([]) + ranged([]) + b"\x04" + b"\x01" + struct.pack("<fff", -6.0, 0.0, 0.0) + b"\x00"
    return hirc_object(3, object_id, body)


def event(object_id: int, actions) -> bytes:
    return hirc_object(4, object_id, bytes([len(actions)]) + b"".join(struct.pack("<I", item) for item in actions))


def random_container(object_id: int, children) -> bytes:
    body = (
        node_base(parent=500, properties=[(0x00, -3.0), (0x54, 0)], ranges=[(0x01, -100.0, 100.0)])
        + struct.pack("<HHH", 2, 0, 0)
        + struct.pack("<fff", 0.0, 0.0, 0.0)
        + struct.pack("<H", 1)
        + b"\x00\x00\x00\x00"  # transition, random, mode, flags
        + struct.pack("<I", len(children)) + b"".join(struct.pack("<I", child) for child in children)
        + struct.pack("<H", len(children)) + b"".join(struct.pack("<Ii", child, 50000) for child in children)
    )
    return hirc_object(5, object_id, body)


def actor_mixer(object_id: int, children) -> bytes:
    body = node_base(properties=[(0x0C, -12.0)]) + struct.pack("<I", len(children)) + b"".join(struct.pack("<I", c) for c in children)
    return hirc_object(7, object_id, body)


def switch_container(object_id: int, child: int) -> bytes:
    body = (
        node_base(parent=500)
        + b"\x00" + struct.pack("<II", 11, 12) + b"\x00"
        + struct.pack("<II", 1, child)
        + struct.pack("<I", 1) + struct.pack("<II", 12, 1) + struct.pack("<I", child)
        + struct.pack("<I", 1) + struct.pack("<IBBii", child, 0, 0, 0, 0)
    )
    return hirc_object(6, object_id, body)


def layer_container(object_id: int, child: int) -> bytes:
    curve = struct.pack("<IBB", 5, 0, 0) + b"\x00" + struct.pack("<IBH", 6, 0, 1) + struct.pack("<ffI", 0.0, 1.0, 4)
    layer = struct.pack("<I", 1) + struct.pack("<H", 1) + curve + struct.pack("<IB", 9, 0) + struct.pack("<I", 1) + struct.pack("<II", child, 1) + struct.pack("<ffI", 0.0, 1.0, 4)
    body = node_base(parent=500) + struct.pack("<II", 1, child) + struct.pack("<I", 1) + layer + b"\x00"
    return hirc_object(9, object_id, body)


def music_track(object_id: int, source_id: int, size: int, *, stream: int = 0) -> bytes:
    body = (
        b"\x00"
        + struct.pack("<I", 1) + source(source_id, size, stream=stream)
        + struct.pack("<I", 1) + struct.pack("<III", 0, source_id, 0) + struct.pack("<dddd", 0.0, 0.0, 0.0, 1.0) + struct.pack("<I", 1)
        + struct.pack("<I", 0)
        + node_base(parent=500)
        + b"\x00" + struct.pack("<i", 0)
    )
    return hirc_object(11, object_id, body)


def attenuation(object_id: int) -> bytes:
    return hirc_object(14, object_id, b"\x00\x00" + b"\xff" * 19 + b"\x00" + b"\x00\x00")


def bank(objects, media=(), *, version: int = 150) -> bytes:
    header = chunk(b"BKHD", struct.pack("<II", version, 1234) + b"\x00" * 16)
    parts = [header]
    if media:
        directory = bytearray()
        blob = bytearray()
        for source_id, content in media:
            if len(blob) % 16:
                blob.extend(b"\x00" * (16 - len(blob) % 16))
            directory.extend(struct.pack("<III", source_id, len(blob), len(content)))
            blob.extend(content)
        parts += [chunk(b"DIDX", bytes(directory)), chunk(b"DATA", bytes(blob))]
    parts.append(chunk(b"HIRC", struct.pack("<I", len(objects)) + b"".join(objects)))
    return b"".join(parts)


EMBEDDED_A = wem(b"\x11" * 37)
EMBEDDED_B = wem(b"\x22" * 50)


@pytest.fixture
def sample_bank() -> bytes:
    return bank(
        [
            sound(101, 9001, len(EMBEDDED_A), properties=[(0x00, -4.0), (0x01, 200.0)]),
            sound(102, 9002, len(EMBEDDED_B)),
            sound(103, 7000, 5000),  # loose in-memory media
            sound(104, 8000, 900, stream=2),  # streamed
            random_container(200, [101, 102]),
            switch_container(210, 103),
            layer_container(220, 104),
            music_track(230, 7000, 5000),
            play_action(300, 200),
            set_volume_action(301, 200),
            event(400, [300, 301]),
            actor_mixer(500, [200, 210, 220, 230]),
            attenuation(600),
            hirc_object(23, 700, b"\x01\x02"),  # a type the decoder does not model
        ],
        media=[(9001, EMBEDDED_A), (9002, EMBEDDED_B)],
    )


def test_every_modelled_object_decodes_to_the_byte(sample_bank):
    graph = read_hirc_graph(sample_bank)
    assert graph.version == 150 and graph.framing_complete
    statuses = {node.object_id: node.status for node in graph.nodes}
    assert statuses.pop(700) == FRAMED
    assert set(statuses.values()) == {PARSED}
    nodes = graph.by_id()
    assert nodes[101].source.source_id == 9001 and nodes[101].parent_id == 500
    assert nodes[101].property(0x00).as_float == -4.0
    assert nodes[400].actions == (300, 301)
    assert (nodes[300].action_name, nodes[300].target_id, nodes[300].details["bank_id"]) == ("Play", 200, 77)
    assert nodes[301].action_name == "SetVolume" and nodes[301].value("base").value == -6.0
    assert [item.object_id for item in nodes[200].playlist] == [101, 102]
    assert nodes[200].value("loop_count").value == 2
    assert nodes[200].ranged_properties[0].name == "Pitch"
    assert nodes[500].children == (200, 210, 220, 230)
    assert [s.source_id for s in nodes[230].sources] == [7000]
    assert {node.object_id for node in graph.sounds_for_source(7000)} == {103, 230}


def test_a_body_that_does_not_end_on_its_size_is_a_mismatch_not_a_guess():
    padded = hirc_object(4, 400, b"\x01" + struct.pack("<I", 300) + b"\x00")
    graph = read_hirc_graph(bank([padded]))
    assert graph.framing_complete
    assert graph.nodes[0].status == MISMATCH and "before the declared end" in graph.nodes[0].mismatch_reason
    truncated = hirc_object(4, 401, b"\x02" + struct.pack("<I", 300))
    assert read_hirc_graph(bank([truncated])).nodes[0].status == MISMATCH


def test_other_bank_versions_are_not_decoded(sample_bank):
    old = bank([event(400, [300])], version=145)
    graph = read_hirc_graph(old)
    assert graph.nodes == () and not graph.framing_complete
    assert "not decoded for bank version 145" in hirc_graph_preview_lines(old)[0]


def test_preview_lines_summarise_events_containers_and_coverage(sample_bank):
    text = "\n".join(hirc_graph_preview_lines(sample_bank))
    assert "13 of 14 objects decoded to the byte" in text
    assert "framed only, layout not modelled: type 23" in text
    assert "event 400: Play -> 200; SetVolume -> 200" in text
    assert "container 200: random, plays 2x, 2 in its playlist" in text


def test_value_edits_change_only_their_bytes(sample_bank):
    edits = [
        HircEdit(101, "property:Volume", -9.5),
        HircEdit(200, "range:Pitch:max", 300.0),
        HircEdit(200, "property:Loop", 3),
        HircEdit(200, "value:loop_count", 0),
        HircEdit(200, "weight:102", 25000),
        HircEdit(301, "value:base", -12.0),
    ]
    result = apply_hirc_edits(sample_bank, edits)
    assert len(result.data) == len(sample_bank)
    nodes = read_hirc_graph(result.data).by_id()
    assert nodes[101].property(0x00).as_float == -9.5
    assert nodes[101].property(0x01).as_float == 200.0
    assert struct.unpack("<f", struct.pack("<I", nodes[200].ranged_properties[0].max_raw))[0] == 300.0
    assert nodes[200].property(0x54).raw == 3
    assert nodes[200].value("loop_count").value == 0
    assert [item.weight for item in nodes[200].playlist] == [50000, 25000]
    assert nodes[301].value("base").value == -12.0
    changed = sum(1 for a, b in zip(sample_bank, result.data) if a != b)
    assert 0 < changed <= 6 * 4
    assert apply_hirc_edits(sample_bank, [HircEdit(101, "property:Volume", -4.0)]).data == sample_bank


@pytest.mark.parametrize(
    ("edit", "reason"),
    [
        (HircEdit(102, "property:Volume", 1.0), "adding a property changes the object's size"),
        (HircEdit(101, "property:AttenuationID", 5), "measured, fixed type"),
        (HircEdit(101, "property:Volume", float("inf")), "finite"),
        (HircEdit(200, "property:Loop", 1.5), "whole number"),
        (HircEdit(200, "weight:999", 1), "no playlist entry"),
        (HircEdit(200, "weight:101", -1), "cannot be negative"),
        (HircEdit(700, "property:Volume", 1.0), "did not decode exactly"),
        (HircEdit(999, "property:Volume", 1.0), "no HIRC object"),
        (HircEdit(101, "colour", 1), "not recognised"),
    ],
)
def test_value_edits_outside_the_proven_set_are_refused(sample_bank, edit, reason):
    with pytest.raises(WwiseBankEditError, match=reason):
        apply_hirc_edits(sample_bank, [edit])


def test_duplicate_object_ids_make_an_edit_ambiguous():
    data = bank([sound(101, 1, 10, properties=[(0x00, 0.0)]), sound(101, 2, 10, properties=[(0x00, 0.0)])])
    with pytest.raises(WwiseBankEditError, match="ambiguous"):
        apply_hirc_edits(data, [HircEdit(101, "property:Volume", 1.0)])


def test_replacing_embedded_media_rebuilds_the_table_and_retargets_its_sounds(sample_bank):
    replacement = _build_pcm_wem(b"\x05\x00" * 300, 48000, 1, channel_layout=0x00004101)
    result = replace_embedded_media(sample_bank, 9001, replacement)
    media = read_embedded_media(result.data)
    assert [item.source_id for item in media] == [9001, 9002]
    assert all(item.offset % 16 == 0 for item in media)
    assert read_bank_embedded_bytes(result.data, media[0]) == replacement
    assert read_bank_embedded_bytes(result.data, media[1]) == EMBEDDED_B
    data_chunk = next(c for c in read_bank_chunks(result.data)[0] if c.identifier == "DATA")
    assert data_chunk.size == media[1].offset + media[1].size
    nodes = read_hirc_graph(result.data).by_id()
    assert (nodes[101].source.plugin_id, nodes[101].source.in_memory_size) == (PCM, len(replacement))
    assert nodes[101].property(0x00).as_float == -4.0
    assert (nodes[102].source.plugin_id, nodes[102].source.in_memory_size) == (VORBIS, len(EMBEDDED_B))
    assert replace_embedded_media(sample_bank, 9001, EMBEDDED_A).data == sample_bank


def test_loose_media_retarget_updates_every_in_memory_source(sample_bank):
    replacement = wem(b"\x09" * 4000)
    result = retarget_loose_media(sample_bank, 7000, replacement)
    nodes = read_hirc_graph(result.data).by_id()
    assert nodes[103].source.in_memory_size == len(replacement)
    assert nodes[230].sources[0].in_memory_size == len(replacement)
    assert len(result.data) == len(sample_bank) and len(result.changes) == 2


@pytest.mark.parametrize(
    ("source_id", "media", "reason"),
    [
        (8000, wem(b"\x00" * 10), "original file is needed"),
        (9001, wem(b"\x00" * 10), "replace the embedded copy"),
        (7000, b"OggS" + b"\x00" * 40, "not a RIFF/WAVE"),
        (7000, wem(b"\x00" * 10, tag=0x3041), "not one this game's banks play"),
        (7000, wem(b"\x00" * 10)[:-4], "no data chunk"),
    ],
)
def test_loose_media_retarget_refusals(sample_bank, source_id, media, reason):
    with pytest.raises(WwiseBankEditError, match=reason):
        retarget_loose_media(sample_bank, source_id, media)


def test_media_named_inside_an_undecoded_object_is_refused():
    data = bank([sound(103, 7000, 50), hirc_object(14, 600, struct.pack("<I", 7000))])
    with pytest.raises(WwiseBankEditError, match="not decoded and may refer to media 7000"):
        retarget_loose_media(data, 7000, wem(b"\x00" * 8))


def _entry(path: str, size: int = 0) -> ArchiveEntry:
    return ArchiveEntry(path, None, None, 0, size, size, 0, 0)


def test_media_replacement_collects_the_wem_and_every_bank_that_plays_it(sample_bank):
    unrelated = bank([sound(1, 42, 10)])
    streamed_elsewhere = bank([sound(5, 7000, 5000, stream=1)])
    entries = {"a.bnk": sample_bank, "b.bnk": unrelated, "c.bnk": streamed_elsewhere}
    wem_entry = _entry("sound/windows/media/7000.wem", 5000)
    original = wem(b"\x01" * 4900)
    media = _build_pcm_wem(b"\x00\x00" * 20000, 48000, 1)

    result = build_wwise_media_replacement(
        7000,
        media,
        original_media=original,
        wem_entries=[wem_entry],
        bank_entries=[_entry("a.bnk"), _entry("b.bnk")],
        read_entry=lambda entry: entries[entry.path],
    )
    assert [entry.path for entry, _data in result.payloads] == ["sound/windows/media/7000.wem", "a.bnk"]
    assert result.payloads[0][1] == media
    assert read_hirc_graph(result.payloads[1][1]).by_id()[103].source.plugin_id == PCM
    assert any("PCM codec" in note for note in result.notes)
    assert any("times the size" in note for note in result.notes)

    with pytest.raises(WwiseBankEditError, match=r"c\.bnk: .*does not fit the original media"):
        build_wwise_media_replacement(
            7000,
            media,
            original_media=original,
            wem_entries=[wem_entry],
            bank_entries=[_entry("a.bnk"), _entry("c.bnk")],
            read_entry=lambda entry: entries[entry.path],
        )


def test_pcm_wem_and_rebuilt_bank_decode_with_the_bundled_decoder(sample_bank, tmp_path):
    from cdmw.core import archive_media_preview
    from cdmw.core.archive_audio import _decode_with_vgmstream

    if archive_media_preview._resolve_vgmstream_cli_path() is None:
        pytest.skip("bundled vgmstream-cli is required")
    import wave

    media = _build_pcm_wem(b"\x10\x00\x20\x00" * 4800, 48000, 2, channel_layout=0x00003102)
    (tmp_path / "sound.wem").write_bytes(media)
    with wave.open(str(_decode_with_vgmstream(tmp_path / "sound.wem", tmp_path / "sound.wav")), "rb") as audio:
        assert (audio.getnchannels(), audio.getframerate(), audio.getnframes()) == (2, 48000, 4800)
    rebuilt = replace_embedded_media(sample_bank, 9002, _build_pcm_wem(b"\x00\x00" * 960, 48000, 1, channel_layout=0x00004101))
    (tmp_path / "bank.bnk").write_bytes(rebuilt.data)
    with wave.open(str(_decode_with_vgmstream(tmp_path / "bank.bnk", tmp_path / "bank.wav", subsong=2)), "rb") as audio:
        assert audio.getnframes() == 960


def test_pcm_wem_carries_the_original_speaker_layout():
    media = _build_pcm_wem(b"\x01\x00\x02\x00" * 10, 44100, 2, channel_layout=0x00003102)
    fmt_offset = media.index(b"fmt ") + 8
    tag, channels, rate = struct.unpack_from("<HHI", media, fmt_offset)
    assert (tag, channels, rate) == (0xFFFE, 2, 44100)
    assert struct.unpack_from("<I", media, fmt_offset - 4)[0] == 0x18
    assert struct.unpack_from("<I", media, fmt_offset + 0x14)[0] == 0x00003102
