from __future__ import annotations

import struct

import numpy as np
import pytest

from tools import pac_shader_consumer_study as study

_DISASSEMBLY = """;
; Input signature:
;
; Name                 Index   Mask Register SysValue  Format   Used
; -------------------- ----- ------ -------- -------- ------- ------
; SV_VertexID              0   x           0   VERTID    uint   x
;
; Output signature:
;
; Name                 Index   Mask Register SysValue  Format   Used
; -------------------- ----- ------ -------- -------- ------- ------
; SV_Position              0   xyzw        0      POS   float   xyzw
; TEXCOORD                 0   xy          1     NONE   float   xy
;
;PSVRuntimeInfo:
; Vertex Shader
;
; Input signature:
;
; Name                 Index             InterpMode DynIdx
; -------------------- ----- ---------------------- ------
; SV_VertexID              0
;
; Output signature:
;
; Name                 Index             InterpMode DynIdx
; -------------------- ----- ---------------------- ------
; SV_Position              0          noperspective
; TEXCOORD                 0                 linear
;
; Resource bind info for g_bindlessPooledSkinnedMeshVertexBuffers
; {
;
;   struct struct.SkinnedMeshVertexData
;   {
;
;       uint2 _normalizedPackedPosition;              ; Offset:    0
;       half4 _texcoord;                              ; Offset:    8
;       uint _packedNormal;                           ; Offset:   16
;       uint2 _packedBoneIndex;                       ; Offset:   20
;       uint2 _packedBoneWeight;                      ; Offset:   28
;       uint _packedVertexColorRG_systemProperty;     ; Offset:   36
;
;   } $Element;                                       ; Offset:    0 Size:    40
;
; }
;
  %40 = call %dx.types.Handle @dx.op.annotateHandle(i32 216, %dx.types.Handle %39, %dx.types.ResourceProperties { i32 524, i32 40 })  ; AnnotateHandle(res,props)  resource: StructuredBuffer<stride=40>
  %41 = call %dx.types.ResRet.i32 @dx.op.rawBufferLoad.i32(i32 139, %dx.types.Handle %40, i32 %33, i32 0, i8 3, i32 4)  ; RawBufferLoad(srv,index,elementOffset,mask,alignment)
  %42 = extractvalue %dx.types.ResRet.i32 %41, 0
  %43 = extractvalue %dx.types.ResRet.i32 %41, 1
  %49 = call %dx.types.ResRet.i32 @dx.op.rawBufferLoad.i32(i32 139, %dx.types.Handle %40, i32 %33, i32 16, i8 1, i32 4)  ; RawBufferLoad(srv,index,elementOffset,mask,alignment)
  %50 = extractvalue %dx.types.ResRet.i32 %49, 0
  %83 = and i32 %42, 65535
  %84 = uitofp i32 %83 to float
  %89 = and i32 %43, 65535
  %90 = uitofp i32 %89 to float
  %91 = and i32 %50, 1023
  %92 = uitofp i32 %91 to float
"""


def test_the_record_struct_is_read_from_the_shader_reflection() -> None:
    result = study.analyse_disassembly(_DISASSEMBLY, digest="d", source_hlsl="shader/character.hlsl")
    assert result is not None
    assert result.struct_size == 40
    assert [(f.name, f.offset) for f in result.struct_fields] == [
        ("_normalizedPackedPosition", 0),
        ("_texcoord", 8),
        ("_packedNormal", 16),
        ("_packedBoneIndex", 20),
        ("_packedBoneWeight", 28),
        ("_packedVertexColorRG_systemProperty", 36),
    ]


def test_a_masked_off_half_of_a_dword_is_reported_fetched_but_unused() -> None:
    result = study.analyse_disassembly(_DISASSEMBLY, digest="d", source_hlsl="shader/character.hlsl")
    assert result is not None
    # The load covers bytes 0-7, and both dwords are masked to their low 16 bits,
    # so bytes 6-7 arrive on the GPU and are then discarded by this shader.
    assert all(result.byte_read[offset] for offset in range(8))
    assert result.byte_used[4] and result.byte_used[5]
    assert not result.byte_used[6]
    assert not result.byte_used[7]
    assert result.byte_used[0] and result.byte_used[1]


def test_only_the_bits_a_shader_masks_in_count_as_used() -> None:
    result = study.analyse_disassembly(_DISASSEMBLY, digest="d", source_hlsl="shader/character.hlsl")
    assert result is not None
    # _packedNormal is masked to its low 10 bits. Those bits live in byte 16 and
    # the bottom two bits of byte 17, so both count as used and the top half of
    # the dword is fetched but never reaches anything. Reporting is per byte, so
    # a byte counts as used when any of its bits do.
    assert result.byte_used[16]
    assert result.byte_used[17]
    assert not result.byte_used[18]
    assert not result.byte_used[19]


def test_the_shader_stage_and_interpolation_modes_are_recovered() -> None:
    result = study.analyse_disassembly(_DISASSEMBLY, digest="d", source_hlsl="shader/character.hlsl")
    assert result is not None
    assert result.stage == "Vertex Shader"
    outputs = {row["name"]: row["interpolation"] for row in result.signatures["output"]}
    assert outputs["SV_Position"] == "noperspective"
    assert outputs["TEXCOORD"] == "linear"


def test_a_shader_without_the_record_is_not_reported() -> None:
    assert study.analyse_disassembly("; nothing here\n", digest="d", source_hlsl="x") is None


# ── Bit usage is conservative ────────────────────────────────────────

def test_an_unrecognised_instruction_consumes_the_whole_value() -> None:
    usage = study.BitUsage(["  %2 = add i32 %1, 7"])
    assert usage.used_bits("%1") == 0xFFFFFFFF


def test_a_value_nothing_reads_has_no_used_bits() -> None:
    assert study.BitUsage(["  %1 = extractvalue x, 0"]).used_bits("%1") == 0


def test_a_shift_then_mask_narrows_to_the_shifted_window() -> None:
    usage = study.BitUsage(
        [
            "  %2 = lshr i32 %1, 16",
            "  %3 = and i32 %2, 255",
            "  %4 = add i32 %3, 1",
        ]
    )
    assert usage.used_bits("%1") == 0x00FF0000


def test_a_truncation_narrows_to_its_width() -> None:
    usage = study.BitUsage(["  %2 = trunc i32 %1 to i16", "  %3 = add i16 %2, 1"])
    assert usage.used_bits("%1") == 0x0000FFFF


def test_a_store_escapes_the_whole_value() -> None:
    usage = study.BitUsage(["  store i32 %1, i32* %9, align 4"])
    assert usage.used_bits("%1") == 0xFFFFFFFF


# ── PASC container ───────────────────────────────────────────────────

def _pasc(source: str, payload: bytes) -> bytes:
    name = source.encode("utf-8")
    header = b"PASC" + struct.pack("<7I", 7, 0, 61, 0, 0, 0, 0) + struct.pack("<I", len(name))
    return header + name + payload


def test_a_pasc_container_yields_its_source_name_and_the_dxil_inside() -> None:
    parsed = study.parse_pasc(_pasc("shader/character.hlsl", b"junk" + b"DXBC" + b"\x00" * 8))
    assert parsed is not None
    assert parsed.source_hlsl == "shader/character.hlsl"
    assert parsed.container.startswith(b"DXBC")


def test_a_container_without_dxil_is_rejected() -> None:
    assert study.parse_pasc(_pasc("shader/character.hlsl", b"no container here")) is None


def test_a_non_pasc_blob_is_rejected() -> None:
    assert study.parse_pasc(b"NOPE" + b"\x00" * 64) is None


# ── The decode transcribed from the shader ───────────────────────────

def _record(*, packed_normal: int, tangent_lane: int) -> np.ndarray:
    record = bytearray(40)
    struct.pack_into("<h", record, 6, tangent_lane)
    struct.pack_into("<I", record, 16, packed_normal)
    return np.frombuffer(bytes(record), dtype=np.uint8).reshape(1, 40)


def _encode_component(value: float) -> int:
    return int(round((value + 1.0) * 1023.0 / 2.0))


def test_the_normal_z_sign_comes_from_bit_30() -> None:
    packed = (_encode_component(0.0) << 10) | (_encode_component(0.0) << 20)
    positive, _t, _h = study.decode_record_tbn(_record(packed_normal=packed, tangent_lane=0))
    negative, _t2, _h2 = study.decode_record_tbn(_record(packed_normal=packed | (1 << 30), tangent_lane=0))
    assert positive[0][2] == pytest.approx(1.0, abs=1e-3)
    assert negative[0][2] == pytest.approx(-1.0, abs=1e-3)


def test_the_handedness_comes_from_bit_31_and_is_not_the_z_sign() -> None:
    packed = (_encode_component(0.0) << 10) | (_encode_component(0.0) << 20)
    _n, _t, plus = study.decode_record_tbn(_record(packed_normal=packed, tangent_lane=0))
    _n2, _t2, minus = study.decode_record_tbn(_record(packed_normal=packed | (1 << 31), tangent_lane=0))
    assert plus[0] == pytest.approx(1.0)
    assert minus[0] == pytest.approx(-1.0)


def test_the_tangent_z_sign_comes_from_the_sign_of_bytes_6_7() -> None:
    packed = (_encode_component(0.0) << 10) | (_encode_component(0.0) << 20) | _encode_component(0.0)
    # Magnitude 32767 maps to tangent.x = +1, so make it smaller to leave room.
    positive, tangent_pos, _h = study.decode_record_tbn(_record(packed_normal=packed, tangent_lane=16384))
    _n, tangent_neg, _h2 = study.decode_record_tbn(_record(packed_normal=packed, tangent_lane=-16384))
    assert tangent_pos[0][2] > 0.0
    assert tangent_neg[0][2] < 0.0
    # The magnitude is the same; only the z sign flips.
    assert tangent_pos[0][0] == pytest.approx(tangent_neg[0][0])


def test_both_decoded_vectors_are_unit_length() -> None:
    packed = (_encode_component(0.3) << 10) | (_encode_component(-0.4) << 20) | _encode_component(0.6)
    normal, tangent, _h = study.decode_record_tbn(_record(packed_normal=packed, tangent_lane=9000))
    assert np.linalg.norm(normal[0]) == pytest.approx(1.0, abs=1e-3)
    assert np.linalg.norm(tangent[0]) == pytest.approx(1.0, abs=1e-3)


def test_quantisation_overshoot_is_clamped_rather_than_producing_nan() -> None:
    # x and y both near 1 makes 1 - x^2 - y^2 negative; the shader clamps at 0.
    packed = (_encode_component(1.0) << 10) | (_encode_component(1.0) << 20) | _encode_component(1.0)
    normal, tangent, _h = study.decode_record_tbn(_record(packed_normal=packed, tangent_lane=32767))
    assert np.isfinite(normal).all()
    assert np.isfinite(tangent).all()
    assert normal[0][2] == pytest.approx(0.0)
