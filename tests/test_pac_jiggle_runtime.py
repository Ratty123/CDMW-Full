"""CPU timer/resource handoff through the existing shader blend reference."""

import struct

import pytest

from cdmw.modding.pac_jiggle_bones import jiggle_bone_blend_override
from cdmw.modding.pac_jiggle_runtime import (
    advance_jiggle_hit_window, jiggle_runtime_can_release,
    jiggle_runtime_shader_upload, refresh_jiggle_runtime_resources,
)


NORMAL = (680, .82, 3, .055, 400, .7, 200, .7)
HIT = (680, 1, 3, .055, 1500, .9, 200, .7)


def state():
    record = bytearray(0x220)
    # Opaque prefix bytes prove these helpers do not rebuild a guessed object.
    record[:16] = bytes(range(16))
    for offset in (0x10, 0x120, 0x130, 0x21C):
        struct.pack_into('<I', record, offset, 0xFFFFFFFF)
    struct.pack_into('<8f', record, 0x134, *NORMAL)
    return record


def resources(record, **changes):
    args = dict(shader_data_index=5, state_buffer_offset=20, command_offset=30,
                profile_settings=NORMAL, hit_settings=HIT)
    return refresh_jiggle_runtime_resources(record, **(args | changes))


def test_hit_window_crossing_zero_keeps_override_for_one_update_then_restores_masks():
    record = state()
    record[0x110] = 1
    struct.pack_into('<f', record, 0x10C, .01)
    struct.pack_into('<2I', record, 0x154, 0x80, 1)
    struct.pack_into('<H', record, 0x15C, 7)
    struct.pack_into('<f', record, 0x19C, .8)
    active = advance_jiggle_hit_window(record, .02)
    assert active[0x110] == 1
    assert struct.unpack_from('<f', active, 0x10C)[0] < 0
    assert struct.unpack_from('<I', active, 0x154)[0] == 0x83
    index, uploaded = jiggle_runtime_shader_upload(resources(active))
    assert index == 5 and len(uploaded) == 264
    # Hit mode 3 supersedes the named mask with per-bone instance output.
    assert jiggle_bone_blend_override(uploaded, original_bone_index=7, instance_weight=.25) == (1, .25)
    assert jiggle_bone_blend_override(uploaded, original_bone_index=8, instance_weight=0) == (1, 0)
    expired = advance_jiggle_hit_window(active, 0)
    assert expired[0x110] == 0 and struct.unpack_from('<f', expired, 0x10C)[0] == 0
    assert struct.unpack_from('<I', expired, 0x154)[0] == 0x82
    _, uploaded = jiggle_runtime_shader_upload(resources(expired))
    assert jiggle_bone_blend_override(uploaded, original_bone_index=7, instance_weight=.25) == pytest.approx((1, .8))
    allowed = set(range(0x10C, 0x111)) | set(range(0x154, 0x158))
    assert all(a == b for i, (a, b) in enumerate(zip(record, expired, strict=True)) if i not in allowed)


def test_inactive_timer_is_not_counted_down_and_unmasked_vertices_keep_their_blend():
    record = state()
    struct.pack_into('<f', record, 0x10C, 7)
    struct.pack_into('<I', record, 0x154, 0x83)
    updated = advance_jiggle_hit_window(record, .5)
    assert struct.unpack_from('<f', updated, 0x10C)[0] == 7
    _, shader = jiggle_runtime_shader_upload(resources(updated))
    assert jiggle_bone_blend_override(shader, original_bone_index=0, instance_weight=0) == (0, 0)


def test_resources_preserve_previous_offset_and_apply_only_positive_overrides():
    record = state()
    record[0x110] = 1
    struct.pack_into('<I', record, 0x120, 17)
    updated = resources(record, runtime_overrides=(0, -1, 6, 0, -4, .5, 0, 0))
    assert struct.unpack_from('<I', updated, 0x130)[0] == 17
    assert struct.unpack_from('<I', updated, 0x120)[0] == 20
    assert struct.unpack_from('<8f', updated, 0x134) == pytest.approx((680, 1, 6, .055, 1500, .5, 200, .7))
    assert updated[:16] == record[:16]
    # No resource change means no settings refresh, even if the clock just expired.
    expired = bytearray(updated)
    expired[0x110] = 0
    assert resources(expired, profile_settings=(), hit_settings=()) == bytes(expired)
    refreshed = resources(expired, state_buffer_offset=21)
    assert struct.unpack_from('<8f', refreshed, 0x134) == pytest.approx(NORMAL)
    assert struct.unpack_from('<I', refreshed, 0x130)[0] == 20


@pytest.mark.parametrize('offset', [0x10, 0x120, 0x130, 0x21C])
def test_release_waits_for_every_resource_slot_to_clear(offset):
    record = state()
    assert jiggle_runtime_shader_upload(record) is None
    assert jiggle_runtime_can_release(record, empty_profile_id=0)
    struct.pack_into('<I', record, offset, 0)
    assert not jiggle_runtime_can_release(record, empty_profile_id=0)
    if offset == 0x21C:
        assert jiggle_runtime_shader_upload(record) == (0, record[0x114:0x21C])


@pytest.mark.parametrize('offset', [0x108, 0x110, 0x14])
def test_release_waits_for_platform_hit_and_named_profile(offset):
    record = state()
    record[offset] = 1
    assert not jiggle_runtime_can_release(record, empty_profile_id=0)
    if offset == 0x14:
        assert jiggle_runtime_can_release(record, empty_profile_id=1)


@pytest.mark.parametrize('dt', [-1, float('nan'), float('inf')])
def test_invalid_runtime_clock_is_rejected(dt):
    with pytest.raises(ValueError):
        advance_jiggle_hit_window(state(), dt)


def test_invalid_storage_masks_and_resource_parameters_are_rejected():
    with pytest.raises(ValueError, match='0x220'):
        jiggle_runtime_shader_upload(bytes(264))
    record = state()
    struct.pack_into('<I', record, 0x158, 33)
    with pytest.raises(ValueError, match='32-entry'):
        advance_jiggle_hit_window(record, 0)
    with pytest.raises(ValueError, match='unsigned'):
        resources(state(), state_buffer_offset=-1)
    with pytest.raises(ValueError, match='eight floats'):
        resources(state(), profile_settings=(1,))
    with pytest.raises(ValueError, match='finite'):
        resources(state(), runtime_overrides=(float('nan'),) * 8)
