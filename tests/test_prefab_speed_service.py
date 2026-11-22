"""Prefab speed values: the catalogue finds them, scaling writes only their bytes."""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.archives.prefab_glossary import describe_field
from cdmw.domain.archives.prefab_speed import CATEGORIES, SPEED_MEMBERS
from cdmw.services.prefab_speed_service import (
    NO_VALUE,
    PARTLY_READ,
    UNCHANGED,
    ZERO_VALUES,
    PrefabSpeedEdit,
    PrefabSpeedError,
    apply_speed_edits,
    prefab_speed_hit,
    scale_speed_prefabs,
    scale_speed_values,
    search_speed_prefabs,
    speed_values,
    write_state,
)
from tests.prefab_speed_builder import build_speed_prefab


def _prefab() -> bytes:
    return build_speed_prefab([
        ("WindComponent", [("_windSpeedAccelerationScale", "float", 2.0), ("_gust", "float", 3.0)]),
        ("VelocityComponent", [("_angularVelocity", "float3", (0.0, 90.0, -45.0))]),
        ("MeshComponent", [("_speed", "float", 7.0)]),  # _speed counts only on a CameraComponent
    ])


def _numbers(data: bytes) -> dict[int, bytes]:
    document = decode_prefab_binary(data)
    return {number.offset: number.raw for obj in document.objects for number in obj.numbers}


def test_every_catalogue_entry_has_a_category_and_a_glossary_label():
    for (type_name, member), item in SPEED_MEMBERS.items():
        assert item.category in CATEGORIES and item.type_name == type_name and item.member == member
        assert describe_field(member).detail


def test_catalogue_values_are_found_and_others_are_not():
    values = speed_values(decode_prefab_binary(_prefab()))
    assert [(v.type_name, v.member, v.kind, v.category) for v in values] == [
        ("WindComponent", "_windSpeedAccelerationScale", "float", "moving"),
        ("VelocityComponent", "_angularVelocity", "float3", "moving"),
    ]
    assert values[0].value == 2.0 and values[1].value == (0.0, 90.0, -45.0)
    assert values[1].to_data()["value"] == [0.0, 90.0, -45.0]


def test_scaling_changes_only_the_value_bytes():
    data = _prefab()
    before = _numbers(data)
    patched, edits = scale_speed_values(data, 2.0)
    assert len(patched) == len(data) and len(edits) == 2
    after = _numbers(patched)
    values = speed_values(decode_prefab_binary(patched))
    assert values[0].value == 4.0 and values[1].value == (0.0, 180.0, -90.0)
    changed = {offset for offset in before if before[offset] != after[offset]}
    assert changed == {value.offset for value in values}
    spans = [(value.offset, value.size) for value in values]
    for index, (left, right) in enumerate(zip(data, patched)):
        if left != right:
            assert any(at <= index < at + size for at, size in spans)


def test_one_value_can_be_set_and_others_are_refused():
    data = _prefab()
    wind = speed_values(decode_prefab_binary(data))[0]
    patched = apply_speed_edits(data, [PrefabSpeedEdit(wind.offset, 0.5)])
    assert speed_values(decode_prefab_binary(patched))[0].value == 0.5
    gust = next(n for n in decode_prefab_binary(data).objects[0].numbers if n.name == "_gust")
    with pytest.raises(PrefabSpeedError, match="not a speed value"):
        apply_speed_edits(data, [PrefabSpeedEdit(gust.offset, 1.0)])
    with pytest.raises(PrefabSpeedError, match="finite"):
        apply_speed_edits(data, [PrefabSpeedEdit(wind.offset, float("inf"))])
    with pytest.raises(PrefabSpeedError, match="between"):
        scale_speed_values(data, 0.0)
    with pytest.raises(PrefabSpeedError, match="Not speed values"):
        scale_speed_values(data, 2.0, offsets=[gust.offset])


def test_scaling_one_category_leaves_the_rest():
    data = build_speed_prefab([
        ("WindComponent", [("_windSpeedAccelerationScale", "float", 2.0)]),
        ("CloudDensityVolumeComponent", [("_macroNoiseFlowSpeed", "float", 0.05)]),
    ])
    patched, edits = scale_speed_values(data, 3.0, category="weather")
    values = {v.member: v.value for v in speed_values(decode_prefab_binary(patched))}
    assert len(edits) == 1 and values["_windSpeedAccelerationScale"] == 2.0
    assert values["_macroNoiseFlowSpeed"] == pytest.approx(0.15)
    assert struct.unpack("<f", struct.pack("<f", 0.15))[0] == pytest.approx(values["_macroNoiseFlowSpeed"])


def test_search_reads_only_type_tables_and_lists_by_category():
    camera = build_speed_prefab([("CameraComponent", [("_speed", "float", 6.0)])])
    plain = build_speed_prefab([("MeshComponent", [("_scale", "float", 1.0)])])
    assert prefab_speed_hit("a.prefab", plain) is None
    entries = [SimpleNamespace(path="object/prefab/wind.prefab", data=_prefab()),
               SimpleNamespace(path="object/prefab/cam.prefab", data=camera),
               SimpleNamespace(path="object/prefab/plain.prefab", data=plain),
               SimpleNamespace(path="object/notprefab.pac", data=b"")]
    read = lambda entry: entry.data  # noqa: E731
    key = object()
    hits = search_speed_prefabs(entries, read, key=key)
    assert [(hit.path, hit.categories) for hit in hits] == [("object/prefab/cam.prefab", ("cameras",)),
                                                             ("object/prefab/wind.prefab", ("moving",))]
    assert [hit.path for hit in search_speed_prefabs(entries, read, category="cameras", key=key)] == [
        "object/prefab/cam.prefab"]
    assert hits[0].to_data()["category_label"] == "Scene cameras"


# --- which prefabs may be written, what a search really finds, and many prefabs at once ----------

TWO = [("WindComponent", [("_windSpeedAccelerationScale", "float", 2.0)]),
       ("CameraComponent", [("_speed", "float", 6.0)])]


def _partly_read() -> bytes:
    """A two-value prefab damaged so that reading stops after the first value."""

    data = build_speed_prefab(TWO)
    for position in range(len(data) - 1, 0, -1):
        damaged = bytearray(data)
        damaged[position] ^= 0xFF
        try:
            document = decode_prefab_binary(bytes(damaged))
        except Exception:  # noqa: BLE001 - this damage is not the case wanted
            continue
        if not document.walk_complete and len(speed_values(document, stated_only=True)) == 1:
            return bytes(damaged)
    raise AssertionError("no partly read prefab could be made")


def test_a_partly_read_prefab_is_never_written():
    whole, damaged = build_speed_prefab(TWO), _partly_read()
    assert write_state(whole) == "" and write_state(damaged) == PARTLY_READ
    assert write_state(b"not a prefab") == "could not be read"
    # It used to scale the one value before the stop and report success.
    with pytest.raises(PrefabSpeedError, match="partly read"):
        scale_speed_values(damaged, 2.0)
    offset = speed_values(decode_prefab_binary(damaged), stated_only=True)[0].offset
    with pytest.raises(PrefabSpeedError, match="partly read"):
        apply_speed_edits(damaged, [PrefabSpeedEdit(offset, 4.0)])
    patched, edits = scale_speed_values(whole, 2.0)
    assert len(edits) == 2 and [value.value for value in speed_values(decode_prefab_binary(patched))] == [4.0, 12.0]


def test_a_value_too_large_for_its_field_is_refused_by_name():
    huge = build_speed_prefab([("CameraComponent", [("_speed", "float", 1e37)])])
    with pytest.raises(PrefabSpeedError, match="too large for this field"):
        scale_speed_values(huge, 100.0)


def test_a_search_says_what_each_prefab_really_holds_and_lists_values_first():
    declared = build_speed_prefab([("CameraComponent", [("_speed", "float", 6.0), ("_fov", "float", 1.0)])],
                                  absent={"_speed"})  # the type is declared; the object holds no speed
    entries = [SimpleNamespace(path="object/prefab/a_declared.prefab", data=declared),
               SimpleNamespace(path="object/prefab/b_damaged.prefab", data=_partly_read()),
               SimpleNamespace(path="object/prefab/c_two.prefab", data=build_speed_prefab(TWO))]
    hits = search_speed_prefabs(entries, lambda entry: entry.data)
    assert [hit.path.rsplit("/", 1)[-1] for hit in hits] == ["c_two.prefab", "a_declared.prefab", "b_damaged.prefab"]
    two, only_declared, damaged = hits
    assert two.value_count() == 2 and two.value_count("cameras") == 1 and two.state == ""
    assert two.to_data("cameras")["values"] == 1 and len(two.to_data()["labels"]) == 2
    assert only_declared.value_count() == 0 and only_declared.state == "" and only_declared.to_data()["labels"] == []
    assert damaged.state == PARTLY_READ and damaged.to_data()["state"] == PARTLY_READ
    # For one category, a prefab that holds no value of it goes after the ones that do.
    cameras = search_speed_prefabs(entries, lambda entry: entry.data, category="cameras")
    assert [hit.path.rsplit("/", 1)[-1] for hit in cameras][0] == "c_two.prefab"
    key = object()
    assert search_speed_prefabs(entries, lambda entry: entry.data, key=key) == hits
    assert search_speed_prefabs(entries, lambda entry: 1 / 0, key=key) == hits  # kept for the session


def test_many_prefabs_are_scaled_or_left_out_with_a_reason():
    import threading

    zero = build_speed_prefab([("CameraComponent", [("_speed", "float", 0.0)])])
    entries = [SimpleNamespace(path="object/prefab/two.prefab", data=build_speed_prefab(TWO)),
               SimpleNamespace(path="object/prefab/zero.prefab", data=zero),
               SimpleNamespace(path="object/prefab/damaged.prefab", data=_partly_read()),
               SimpleNamespace(path="object/prefab/wind.prefab", data=_prefab())]
    seen = []
    outcomes = scale_speed_prefabs(entries, lambda entry: entry.data, 0.5, category="cameras",
                                   on_progress=lambda done, total: seen.append((done, total)))
    two, zeros, damaged, wind = outcomes
    assert two.reason == "" and two.values == 1 and two.before == (6.0, 6.0) and two.after == (3.0, 3.0)
    values = {value.member: value.value for value in speed_values(decode_prefab_binary(two.patched))}
    assert values == {"_windSpeedAccelerationScale": 2.0, "_speed": 3.0}  # only the chosen category
    assert (zeros.reason, zeros.patched) == (ZERO_VALUES, None) and damaged.reason == PARTLY_READ
    assert wind.reason == NO_VALUE and wind.to_data()["after"] is None
    assert seen[0] == (0, 4) and seen[-1] == (4, 4)
    with pytest.raises(PrefabSpeedError, match="factor"):
        scale_speed_prefabs(entries, lambda entry: entry.data, 0.0)
    stop = threading.Event()
    stop.set()
    with pytest.raises(Exception, match="cancelled"):
        scale_speed_prefabs(entries, lambda entry: entry.data, 2.0, stop_event=stop)


def test_scale_factor_one_on_nonzero_prefab_reports_unchanged_not_zero_values():
    entries = [SimpleNamespace(path="object/prefab/two.prefab", data=build_speed_prefab(TWO))]
    outcomes = scale_speed_prefabs(entries, lambda entry: entry.data, 1.0)
    assert len(outcomes) == 1
    assert outcomes[0].patched is None
    assert outcomes[0].reason == UNCHANGED
