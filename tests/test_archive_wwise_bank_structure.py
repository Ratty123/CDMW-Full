"""Stream prefixes, added/removed properties and variations, and the remaining HIRC types,
on owned synthetic version-150 banks."""
from __future__ import annotations

import struct

import pytest

from cdmw.core.archive_wwise_bank import read_bank_chunks, read_bank_embedded_bytes, read_embedded_media
from cdmw.core.archive_wwise_bank_edit import (
    HircEdit,
    HircPropertyChange,
    WwiseBankEditError,
    change_hirc_properties,
    replace_embedded_media,
    retarget_loose_media,
    stream_prefix_size,
)
from cdmw.core.archive_wwise_bank_plan import (
    SoundBankEditPlan,
    VariationRequest,
    apply_sound_bank_edit_plan,
    build_sound_bank_editor_model,
)
from cdmw.core.archive_wwise_bank_variations import (
    add_sound_variation,
    allocate_wwise_id,
    fnv1_32,
    remove_sound_variation,
)
from cdmw.core.archive_wwise_hirc import PARSED, read_hirc_graph
from tests.test_archive_wwise_hirc import (
    EMBEDDED_A,
    EMBEDDED_B,
    actor_mixer,
    bank,
    chunk,
    event,
    hirc_object,
    node_base,
    play_action,
    props,
    random_container,
    ranged,
    sound,
    wem,
)

PCM = 0x00010001


def vorbis(packets: int, packet_size: int, *, header: int = 40, samples: int = 48000, rate: int = 48000) -> bytes:
    """A Wwise-Vorbis-shaped stream: 0x42-byte fmt, then headers and u16-sized packets."""

    fmt = bytearray(struct.pack("<HHIIHH", 0xFFFF, 1, rate, 0, 0, 0) + b"\x00" * 0x32)
    struct.pack_into("<I", fmt, 0x18, samples)
    struct.pack_into("<II", fmt, 0x28, 0, header)
    data = b"\x00" * header + b"".join(struct.pack("<H", packet_size) + bytes([i % 251]) * packet_size for i in range(packets))
    body = b"WAVE" + chunk(b"fmt ", bytes(fmt)) + chunk(b"data", data)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def data_start(media: bytes) -> int:
    return media.index(b"data") + 8


def test_stream_prefix_keeps_the_playing_time_and_ends_on_a_packet():
    original = vorbis(10, 100)
    prefix = data_start(original) + 40 + 3 * 102
    replacement = vorbis(20, 50)
    size = stream_prefix_size(original, prefix, replacement)
    assert size == data_start(replacement) + 40 + 6 * 52
    assert stream_prefix_size(original, prefix, original) == prefix
    assert stream_prefix_size(original, data_start(original) + 40, replacement) == data_start(replacement) + 40
    with pytest.raises(WwiseBankEditError, match="packet boundary"):
        stream_prefix_size(original, prefix + 1, replacement)


def test_prefetched_media_gets_a_new_prefix_in_the_bank_and_new_sizes():
    original = vorbis(10, 100)
    prefix_size = data_start(original) + 40 + 3 * 102
    data = bank([sound(1, 5000, prefix_size, stream=1), sound(2, 6000, 900, stream=2)], media=[(5000, original[:prefix_size])])
    replacement = vorbis(20, 50)
    result = replace_embedded_media(data, 5000, replacement, original_media=original)
    expected = data_start(replacement) + 40 + 6 * 52
    embedded = read_embedded_media(result.data)[0]
    assert read_bank_embedded_bytes(result.data, embedded) == replacement[:expected]
    assert read_hirc_graph(result.data).by_id()[1].source.in_memory_size == expected
    assert replace_embedded_media(data, 5000, original, original_media=original).data == data
    with pytest.raises(WwiseBankEditError, match="original file is needed"):
        replace_embedded_media(data, 5000, replacement)

    streamed_original = vorbis(10, 100)
    streamed = bank([sound(2, 6000, data_start(streamed_original) + 40 + 2 * 102, stream=2)])
    result = retarget_loose_media(streamed, 6000, replacement, original_media=streamed_original)
    assert read_hirc_graph(result.data).by_id()[2].source.in_memory_size == data_start(replacement) + 40 + 4 * 52


def test_properties_are_added_sorted_and_removed_with_sizes_rebuilt():
    data = bank([sound(1, 10, 10, properties=[(0x00, -4.0), (0x0C, -5.0)]), sound(2, 20, 10), random_container(3, [1, 2])])
    result = change_hirc_properties(
        data,
        [
            HircPropertyChange(1, "property:Pitch", 300.0),
            HircPropertyChange(1, "property:GameAuxSendVolume", None),
            HircPropertyChange(2, "property:Loop", 0),
            HircPropertyChange(3, "range:Volume", (-2.0, 1.0)),
        ],
    )
    nodes = read_hirc_graph(result.data).by_id()
    assert all(node.status == PARSED for node in nodes.values())
    assert [(p.prop_id, p.as_float) for p in nodes[1].properties] == [(0x00, -4.0), (0x01, 300.0)]
    assert [(p.prop_id, p.raw) for p in nodes[2].properties] == [(0x54, 0)]
    assert [item.prop_id for item in nodes[3].ranged_properties] == [0x00, 0x01]
    back = change_hirc_properties(
        result.data,
        [
            HircPropertyChange(1, "property:Pitch", None),
            HircPropertyChange(1, "property:GameAuxSendVolume", -5.0),
            HircPropertyChange(2, "property:Loop", None),
            HircPropertyChange(3, "range:Volume", None),
        ],
    )
    assert back.data == data


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (HircPropertyChange(1, "property:BusVolume", 2.0), "No shipped object of type 2 stores property:BusVolume"),
        (HircPropertyChange(1, "property:Volume", None), "nothing to remove"),
        (HircPropertyChange(1, "property:AttenuationID", 4), "measured, fixed type"),
        (HircPropertyChange(3, "range:Pitch", (2.0, 1.0)), "above its maximum"),
        (HircPropertyChange(3, "range:Pitch", 2.0), "needs a \\(min, max\\) pair"),
        (HircPropertyChange(9, "property:Volume", 1.0), "no HIRC object 9"),
    ],
)
def test_property_changes_outside_the_measured_set_are_refused(change, reason):
    data = bank([sound(1, 10, 10), sound(2, 20, 10), random_container(3, [1, 2])])
    with pytest.raises(WwiseBankEditError, match=reason):
        change_hirc_properties(data, [change])


def data_payload_offset(data: bytes) -> int:
    return next(c for c in read_bank_chunks(data)[0] if c.identifier == "DATA").offset


def test_a_variation_is_added_like_its_sibling_and_removing_it_keeps_its_media():
    data = bank(
        [
            sound(101, 9001, len(EMBEDDED_A), properties=[(0x00, -4.0)]),
            sound(102, 9002, len(EMBEDDED_B)),
            random_container(200, [101, 102]),
            play_action(300, 200),
            event(400, [300]),
            actor_mixer(500, [200]),
        ],
        media=[(9001, EMBEDDED_A), (9002, EMBEDDED_B)],
    )
    media = wem(b"\x42" * 70)
    result = add_sound_variation(data, 200, 101, media, new_sound_id=150, new_source_id=9500)
    graph = read_hirc_graph(result.data)
    nodes = graph.by_id()
    assert [node.object_id for node in graph.nodes][:3] == [101, 150, 102]
    assert nodes[200].children == (101, 102, 150)
    assert [(item.object_id, item.weight) for item in nodes[200].playlist] == [(101, 50000), (102, 50000), (150, 50000)]
    added = nodes[150]
    assert added.status == PARSED and added.parent_id == 500
    assert (added.source.source_id, added.source.stream_type, added.source.in_memory_size) == (9500, 0, len(media))
    assert added.property(0x00).as_float == -4.0
    assert [item.source_id for item in read_embedded_media(result.data)] == [9001, 9002, 9500]
    assert all(item.offset % 16 == 0 for item in read_embedded_media(result.data))
    assert data_payload_offset(result.data) % 16 == 0 and data_payload_offset(data) % 16 == 0
    removed = remove_sound_variation(result.data, 200, 150)
    nodes = read_hirc_graph(removed.data).by_id()
    assert 150 not in nodes and nodes[200].children == (101, 102)
    # Another bank's Sound may play media this bank holds, so removing a sound keeps it.
    assert [item.source_id for item in read_embedded_media(removed.data)] == [9001, 9002, 9500]
    assert data_payload_offset(removed.data) % 16 == 0


def test_a_variation_can_be_added_to_a_bank_without_embedded_media():
    data = bank([sound(1, 7000, 100), sound(2, 7001, 100), random_container(3, [1, 2])])
    result = add_sound_variation(data, 3, 1, wem(b"\x01" * 10), new_sound_id=4, new_source_id=9000, weight=1000)
    assert [item.source_id for item in read_embedded_media(result.data)] == [9000]
    assert result.data.index(b"BKHD") < result.data.index(b"DIDX") < result.data.index(b"DATA") < result.data.index(b"HIRC")
    assert data_payload_offset(result.data) % 16 == 0
    assert read_hirc_graph(result.data).by_id()[3].playlist[-1].weight == 1000


@pytest.mark.parametrize(
    ("call", "reason"),
    [
        (lambda data: add_sound_variation(data, 3, 1, wem(b"\x00"), new_sound_id=2, new_source_id=99), "already used"),
        (lambda data: add_sound_variation(data, 3, 1, wem(b"\x00"), new_sound_id=50, new_source_id=7000), "already used"),
        (lambda data: add_sound_variation(data, 3, 9, wem(b"\x00"), new_sound_id=50, new_source_id=51), "expected one sound"),
        (lambda data: remove_sound_variation(data, 4, 5), "would be left without sounds"),
        (lambda data: remove_sound_variation(data, 3, 6), "also named by object 7"),
    ],
)
def test_variation_refusals(call, reason):
    data = bank(
        [
            sound(1, 7000, 100),
            sound(2, 7001, 100),
            sound(5, 7002, 100),
            sound(6, 7003, 100),
            random_container(3, [1, 2, 6]),
            random_container(4, [5]),
            play_action(7, 6),
        ]
    )
    with pytest.raises(WwiseBankEditError, match=reason):
        call(data)


def test_new_ids_are_wwise_short_ids_that_avoid_taken_ones():
    assert fnv1_32("") == 2166136261
    first = allocate_wwise_id("cdmw_variation", ())
    assert first == fnv1_32("cdmw_variation")
    assert allocate_wwise_id("cdmw_variation", {first}) == fnv1_32("cdmw_variation_1")


def bus(object_id: int) -> bytes:
    body = (
        struct.pack("<II", 0, 77)  # no parent bus, so a device share set follows
        + props([(0x04, -3.0)])
        + b"\x00"  # positioning
        + b"\x00" + struct.pack("<I", 0)  # aux
        + b"\x00" + struct.pack("<HI", 0, 0) + b"\x00"
        + struct.pack("<if", 0, -96.0)
        + struct.pack("<I", 1) + struct.pack("<IfiiBB", 5, -6.0, 100, 100, 4, 0)
        + b"\x00"  # effect slots
        + b"\x00"  # metadata effects
        + b"\x00\x00"  # RTPC curves
        + b"\x00\x00"  # state chunk
    )
    return hirc_object(8, object_id, body)


def fx(object_id: int, media_ids=()) -> bytes:
    body = (
        struct.pack("<II", 0x00760003, 3) + b"\x01\x02\x03"
        + bytes([len(media_ids)]) + b"".join(struct.pack("<BI", i, m) for i, m in enumerate(media_ids))
        + b"\x00\x00" + b"\x00\x00"
        + struct.pack("<H", 1) + b"\x05\x00" + struct.pack("<f", 1.0)
    )
    return hirc_object(17, object_id, body)


def modulator(object_id: int) -> bytes:
    return hirc_object(19, object_id, props([(0x01, 2.0)]) + ranged([]) + b"\x00\x00")


def music_node(children) -> bytes:
    return (
        b"\x00" + node_base()
        + struct.pack("<I", len(children)) + b"".join(struct.pack("<I", c) for c in children)
        + struct.pack("<ddfBB", 1.0, 0.0, 120.0, 4, 4) + b"\x00"
        + struct.pack("<I", 0)
    )


def music_segment(object_id: int) -> bytes:
    markers = struct.pack("<I", 2) + struct.pack("<Id", 1, 0.0) + b"Entry\x00" + struct.pack("<Id", 2, 3.5) + b"\x00"
    return hirc_object(10, object_id, music_node([]) + struct.pack("<d", 3500.0) + markers)


def music_transitions(children) -> bytes:
    rule = (
        struct.pack("<II", 1, 0xFFFFFFFF) + struct.pack("<II", 1, 0xFFFFFFFF)
        + b"\x00" * 21 + b"\x00" * 26 + b"\x01" + b"\x00" * 30
    )
    return music_node(children) + struct.pack("<I", 1) + rule


def music_playlist_item(segment: int, children: int) -> bytes:
    return struct.pack("<III", segment, 0, children) + struct.pack("<IhhhIHBB", 0, 1, 0, 0, 50000, 0, 0, 0)


def music_random_sequence(object_id: int, segment: int) -> bytes:
    playlist = struct.pack("<I", 2) + music_playlist_item(0, 1) + music_playlist_item(segment, 0)
    return hirc_object(13, object_id, music_transitions([segment]) + playlist)


def music_switch(object_id: int, segment: int) -> bytes:
    tree = struct.pack("<IHHHH", 0, 1, 1, 50, 100) + struct.pack("<IIHH", 0, segment, 50, 100)
    body = music_transitions([segment]) + b"\x00" + struct.pack("<I", 1) + struct.pack("<I", 9) + b"\x00"
    return hirc_object(12, object_id, body + struct.pack("<I", len(tree)) + b"\x00" + tree)


def test_buses_effects_modulators_and_music_containers_decode_to_the_byte():
    data = bank([bus(10), fx(11, [9001]), modulator(12), music_segment(13), music_random_sequence(14, 13), music_switch(15, 13)])
    graph = read_hirc_graph(data)
    assert [node.status for node in graph.nodes] == [PARSED] * 6
    nodes = graph.by_id()
    assert nodes[10].property(0x04).as_float == -3.0 and nodes[10].value("max_duck_volume").value == -96.0
    assert nodes[11].plugin_media == (9001,)
    assert nodes[12].properties == ()  # modulator ids are their own enumeration
    assert nodes[13].value("duration").value == 3500.0
    assert nodes[14].children == (13,) and nodes[15].children == (13,)
    with pytest.raises(WwiseBankEditError, match="loads media 9001 as plugin data"):
        retarget_loose_media(bank([sound(1, 9001, 10), fx(11, [9001])]), 9001, wem(b"\x00" * 4))


def test_the_editor_model_and_plan_apply_values_properties_and_variations(tmp_path):
    data = bank(
        [sound(101, 9001, len(EMBEDDED_A), properties=[(0x00, -4.0)]), sound(102, 9002, len(EMBEDDED_B)), random_container(200, [101, 102])],
        media=[(9001, EMBEDDED_A), (9002, EMBEDDED_B)],
    )
    model = build_sound_bank_editor_model(data)
    targets = {(row.object_id, row.target) for row in model.rows}
    assert {(101, "property:Volume"), (200, "range:Pitch:min"), (200, "weight:102"), (200, "value:loop_count")} <= targets
    container = next(obj for obj in model.objects if obj.object_id == 200)
    assert container.children == (101, 102) and "Pitch" not in container.addable_ranges and "Volume" not in container.addable_properties
    audio = tmp_path / "new.wav"
    audio.write_bytes(b"unused")
    plan = SoundBankEditPlan(
        values=(HircEdit(101, "property:Volume", -1.0),),
        properties=(HircPropertyChange(102, "property:Pitch", -200.0),),
        added_variations=(VariationRequest(200, 102, audio),),
    )
    built = wem(b"\x33" * 20)
    result, changes = apply_sound_bank_edit_plan(data, plan, build_media=lambda original, path: built, taken_ids=[1, 2])
    nodes = read_hirc_graph(result).by_id()
    assert nodes[101].property(0x00).as_float == -1.0
    assert nodes[102].property(0x01).as_float == -200.0
    added = [child for child in nodes[200].children if child not in (101, 102)]
    assert len(added) == 1 and nodes[added[0]].property(0x01).as_float == -200.0
    assert len(changes) == 4


def test_bank_header_padding_tracks_the_media_table_and_refuses_unknown_headers():
    one = bank([sound(1, 7000, 100), sound(2, 7001, 100), random_container(3, [1, 2])], media=[(7000, wem(b"\x01" * 9))])
    for count in range(1, 5):
        one = add_sound_variation(one, 3, 1, wem(b"\x02" * 9), new_sound_id=100 + count, new_source_id=9000 + count).data
        assert data_payload_offset(one) % 16 == 0
        header = next(c for c in read_bank_chunks(one)[0] if c.identifier == "BKHD")
        assert 40 <= header.size < 56
    odd = bytearray(bank([sound(1, 7000, 100), sound(2, 7001, 100), random_container(3, [1, 2])], media=[(7000, wem(b"\x01" * 9))]))
    assert next(c for c in read_bank_chunks(bytes(odd))[0] if c.identifier == "BKHD").size == 44
    odd[8 + 42] = 1  # a non-zero byte in the header's padding
    with pytest.raises(WwiseBankEditError, match="40 bytes plus zero padding"):
        add_sound_variation(bytes(odd), 3, 1, wem(b"\x02" * 9), new_sound_id=9, new_source_id=9001)
