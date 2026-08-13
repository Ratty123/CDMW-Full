"""The two skin influences a PAC record carries beyond its six palette slots.

Proven from the game's own vertex shaders: bytes 12-15 hold two more bone
indices as halves carrying whole numbers, bytes 34-35 their weights, and the
pair is live only when the low six bits of byte 39 are not 63. All eight index
the same bone matrix buffer, and the shader divides the accumulated transform by
the accumulated weight, so the stored bytes only matter up to scale.
"""

from __future__ import annotations

import struct

import pytest

from cdmw.modding.mesh_parser import (
    PAC_SKIN_EXTRA_INDEX_OFFSET,
    PAC_SKIN_GATE_DISABLED,
    PAC_SKIN_GATE_OFFSET,
    PAC_SKIN_INFLUENCES,
    PAC_SKIN_PALETTE_SLOTS,
    PAC_SKIN_SLOT_GROUPS,
    PAC_SKIN_WEIGHT_OFFSET,
    _decode_pac_skin_influences,
)


def _record(
    *,
    palette: tuple[int, ...] = (3, 9, 0, 0, 0, 0),
    weights: tuple[int, ...] = (150, 105, 0, 0, 0, 0, 0, 0),
    extra: tuple[float, float] = (0.0, 1.0),
    gate: int = PAC_SKIN_GATE_DISABLED,
) -> bytes:
    record = bytearray(40)
    for group, offset in enumerate(PAC_SKIN_SLOT_GROUPS):
        packed = 0
        for position in range(3):
            packed |= (palette[group * 3 + position] & 0x3FF) << (10 * position)
        struct.pack_into("<I", record, offset, packed)
    struct.pack_into(f"<{PAC_SKIN_INFLUENCES}B", record, PAC_SKIN_WEIGHT_OFFSET, *weights)
    struct.pack_into("<2e", record, PAC_SKIN_EXTRA_INDEX_OFFSET, *extra)
    record[PAC_SKIN_GATE_OFFSET] = gate
    return bytes(record)


def test_a_gated_off_record_reports_only_its_palette_influences() -> None:
    slots, weights = _decode_pac_skin_influences(_record(), 0)
    assert slots == (3, 9)
    assert sum(weights) == pytest.approx(1.0)


def test_the_sentinel_pair_is_never_reported_as_a_bone() -> None:
    # Bytes 12-15 read (0.0, 1.0) on every record that has no extra influences.
    # Bone 0 and bone 1 are real palette entries, so reporting them here would
    # invent influences on most of the corpus.
    slots, _weights = _decode_pac_skin_influences(_record(extra=(0.0, 1.0)), 0)
    assert slots == (3, 9)


def test_an_open_gate_adds_both_extra_influences() -> None:
    slots, weights = _decode_pac_skin_influences(
        _record(weights=(150, 105, 0, 0, 0, 0, 40, 60), extra=(203.0, 17.0), gate=0),
        0,
    )
    assert slots == (3, 9, 203, 17)
    assert sum(weights) == pytest.approx(1.0)
    # Proportions follow the raw bytes: 150:105:40:60 of 355.
    assert weights[0] == pytest.approx(150 / 355)
    assert weights[3] == pytest.approx(60 / 355)


def test_an_extra_influence_with_a_zero_weight_is_dropped() -> None:
    slots, _weights = _decode_pac_skin_influences(
        _record(weights=(150, 105, 0, 0, 0, 0, 0, 60), extra=(203.0, 17.0), gate=0),
        0,
    )
    assert slots == (3, 9, 17)


def test_the_gate_closes_on_exactly_sixty_three() -> None:
    live = _decode_pac_skin_influences(
        _record(weights=(150, 105, 0, 0, 0, 0, 40, 60), extra=(203.0, 17.0), gate=62), 0
    )
    dead = _decode_pac_skin_influences(
        _record(weights=(150, 105, 0, 0, 0, 0, 40, 60), extra=(203.0, 17.0), gate=63), 0
    )
    assert len(live[0]) == 4
    assert len(dead[0]) == 2


def test_only_the_low_six_bits_of_byte_39_are_the_gate() -> None:
    # The top two bits are unidentified and must not close the gate.
    slots, _weights = _decode_pac_skin_influences(
        _record(weights=(150, 105, 0, 0, 0, 0, 40, 60), extra=(203.0, 17.0), gate=0xC0), 0
    )
    assert len(slots) == 4


def test_a_row_can_reach_the_full_eight_influences() -> None:
    slots, weights = _decode_pac_skin_influences(
        _record(
            palette=(1, 2, 3, 4, 5, 6),
            weights=(60, 50, 40, 30, 20, 10, 25, 20),
            extra=(300.0, 400.0),
            gate=0,
        ),
        0,
    )
    assert slots == (1, 2, 3, 4, 5, 6, 300, 400)
    assert len(slots) == PAC_SKIN_INFLUENCES == PAC_SKIN_PALETTE_SLOTS + 2
    assert sum(weights) == pytest.approx(1.0)


def test_weights_are_normalized_by_their_own_total_not_by_255() -> None:
    # An eight-influence row's bytes sum to about 500 in real data, so dividing
    # by 255 would report weights summing to nearly two.
    _slots, weights = _decode_pac_skin_influences(
        _record(weights=(90, 80, 70, 60, 50, 40, 60, 50), extra=(11.0, 12.0), gate=0), 0
    )
    assert sum(weights) == pytest.approx(1.0)


def test_a_non_integral_extra_index_is_refused_rather_than_rounded_blindly() -> None:
    slots, _weights = _decode_pac_skin_influences(
        _record(weights=(150, 105, 0, 0, 0, 0, 40, 60), extra=(-5.0, 17.0), gate=0), 0
    )
    # A negative index is not a bone; its position drops out and the other stays.
    assert slots == (3, 9, 17)


def test_an_all_zero_weight_row_reports_nothing() -> None:
    assert _decode_pac_skin_influences(_record(weights=(0,) * 8), 0) == ((), ())


def test_a_truncated_record_reports_nothing_rather_than_raising() -> None:
    assert _decode_pac_skin_influences(b"\x00" * 20, 0) == ((), ())


def test_the_bulk_decoder_agrees_with_the_scalar_one_on_extra_influences() -> None:
    from cdmw.modding.mesh_parser import PacDescriptor, _decode_pac_vertex_records_bulk

    records = [
        _record(weights=(150, 105, 0, 0, 0, 0, 40, 60), extra=(203.0, 17.0), gate=0),
        _record(),
        _record(palette=(1, 2, 3, 4, 5, 6), weights=(60, 50, 40, 30, 20, 10, 25, 20), extra=(300.0, 400.0), gate=0),
    ]
    payload = b"".join(records)
    descriptor = PacDescriptor(
        name="part",
        material="part",
        bbox_min=(0.0, 0.0, 0.0),
        bbox_extent=(1.0, 1.0, 1.0),
        vertex_counts=[len(records)],
        index_counts=[0],
    )
    bulk = _decode_pac_vertex_records_bulk(
        payload, 0, len(records), descriptor, include_uv=True, include_skin=True
    )
    bulk_indices, bulk_weights = bulk[4], bulk[5]
    for index in range(len(records)):
        slots, weights = _decode_pac_skin_influences(payload, index * 40)
        assert tuple(bulk_indices[index]) == slots
        assert tuple(bulk_weights[index]) == pytest.approx(weights)
