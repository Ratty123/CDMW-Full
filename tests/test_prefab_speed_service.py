"""Prefab speed values: the catalogue finds them, scaling writes only their bytes."""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.archives.prefab_glossary import describe_field
from cdmw.domain.archives.prefab_speed import CATEGORIES, SPEED_MEMBERS
from cdmw.services.prefab_speed_service import (
    PrefabSpeedEdit,
    PrefabSpeedError,
    apply_speed_edits,
    prefab_speed_hit,
    scale_speed_values,
    search_speed_prefabs,
    speed_values,
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
