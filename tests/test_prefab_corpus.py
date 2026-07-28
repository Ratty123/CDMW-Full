from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cdmw.core.prefab_corpus import (
    PREFAB_JSON_IMPORT_CORPUS_FORMAT,
    _array_exact_payload_owner_counts,
    _array_theoretical_payload_span_fit_metrics,
    _descriptor_kind_nonzero_word3_offset_candidate_status_counts,
    _descriptor_kind_nonzero_word3_offset_candidate_target_counts,
    _effective_offset_value_replacements_after_resize,
    _offset_candidate_remap_metrics_after_resize,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_collapse_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_identity_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_profile_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_role_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_shape_counts,
    _resize_impact_unique_offset_candidate_mixed_target_overlap_shift_conflict_counts,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_group_detail_counts,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_identity_counts,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_metadata_collision_counts,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_profile_counts,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_shape_counts,
    _resize_impact_unique_offset_candidate_same_target_overlap_collapse_counts,
    _resize_impact_unique_offset_candidate_same_target_overlap_shift_conflict_counts,
    _resize_impact_unique_offset_candidate_same_target_resource_alias_counts,
    _resize_impact_unique_offset_candidate_same_target_shift_conflict_group_detail_counts,
    _selected_resize_offset_candidate_metrics,
    _transform_exact_payload_owner_counts,
    _transform_theoretical_payload_span_fit_metrics,
    audit_prefab_json_import_sample,
    build_prefab_json_import_archive_entry_report,
    build_prefab_json_import_corpus_json,
    build_prefab_json_import_corpus_report,
    discover_prefab_archive_entries,
    discover_loose_prefab_corpus_paths,
    merge_prefab_json_import_corpus_reports,
)
from cdmw.models import ArchiveEntry


def _lp(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(4, "little") + encoded


def _prefab_decl(name: str, declared_type: str, descriptor: bytes) -> bytes:
    return _lp(name) + _lp(declared_type) + descriptor


def _prefab_profile_payload() -> bytes:
    string_descriptor = b"\x01\x00\x01\x00\x10\x00\x00\x00"
    return (
        b"\xff\xff\x04\x00"
        + _prefab_decl("_attachedSocketName", "IndexedStringA", string_descriptor)
        + _prefab_decl("_pivotSocketName", "IndexedStringA", string_descriptor)
        + b"\x00" * 16
        + _lp("Spine2_B_Socket")
        + _lp("Spine2_B_ChildSocket")
        + _lp("CD_TwoHandWeapon_Sword")
        + _lp("character/model/weapon/test.pac")
        + _lp("character/descriptors/socketbonedata/weapon/test.sockets.xml")
    )


def _prefab_array_count_hint_payload() -> bytes:
    array_descriptor = b"\x00\x00\x04\x00\x00\x10\x03\x00"
    return (
        b"\xff\xff\x04\x00"
        + _prefab_decl("_items", "vector<uint32>", array_descriptor)
        + _lp("character/model/test_array.pac")
    )


def _prefab_transform_word3_payload() -> bytes:
    transform_descriptor = b"\x00\x00\x28\x00\x00\x00\x02\x00"
    return (
        b"\xff\xff\x04\x00"
        + _prefab_decl("_transform", "Transform", transform_descriptor)
        + _lp("character/model/test_transform.pac")
    )


def _prefab_reference_word3_payload() -> bytes:
    reference_descriptor = b"\x00\x00\x28\x00\x00\x00\x02\x00"
    return (
        b"\xff\xff\x04\x00"
        + _prefab_decl("_targetRef", "ReflectObjectPtr", reference_descriptor)
        + _lp("character/model/test_reference.pac")
    )


def _prefab_preserved_unknown_payload() -> bytes:
    return b"\xff\xff\x04\x00" + _lp("character/model/test_unknown.pac") + b"\x11\x22\x33"


def _prefab_descriptor_word3_payload() -> bytes:
    descriptor = b"\x00\x00\x04\x00\x00\x00\x02\x00"
    return (
        b"\xff\xff\x04\x00"
        + _prefab_decl("_count", "uint32", descriptor)
        + _lp("character/model/test_descriptor.pac")
    )


def _prefab_array_descriptor_tail_payload() -> bytes:
    descriptor = b"\x00\x00\x04\x00\x00\x10\x03\x00\xaa\xbb\xcc\xdd"
    return (
        b"\xff\xff\x04\x00"
        + _prefab_decl("_items", "vector<uint32>", descriptor)
        + _lp("character/model/test_array_tail.pac")
    )


def _prefab_reference_descriptor_tail_payload() -> bytes:
    header = b"\x07\x00\x00\x00\x28\x10\x01\x00"
    tail = bytearray(b"\x00" * 80)
    name = _lp("_childSceneObjects")
    type_name = _lp("ReflectObjectPtr")
    model = _lp("character/model/test_reference_tail.pac")
    model_value_offset = 4 + len(name) + len(type_name) + len(header) + len(tail) + 4
    tail[12:16] = model_value_offset.to_bytes(4, "little")
    descriptor = header + bytes(tail)
    return (
        b"\xff\xff\x04\x00"
        + name
        + type_name
        + descriptor
        + model
    )


def _write_prefab(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xff\x04\x00" + _lp(f"character/model/{name}.pac"))


def _entry(path: str, root: Path, data: bytes) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=root / "0.pamt",
        paz_file=root / "0.paz",
        offset=0,
        comp_size=len(data),
        orig_size=len(data),
        flags=0,
        paz_index=0,
    )


def test_prefab_corpus_summarizes_nonzero_word3_status_by_descriptor_kind() -> None:
    assert _descriptor_kind_nonzero_word3_offset_candidate_status_counts(
        {
            "array": {"with_offset_candidate": 2, "without_offset_candidate": 3},
            "transform": {"with_offset_candidate": 0, "without_offset_candidate": 4},
        }
    ) == {
        "array|with_offset_candidate": 2,
        "array|without_offset_candidate": 3,
        "transform|with_offset_candidate": 0,
        "transform|without_offset_candidate": 4,
    }


def test_prefab_corpus_summarizes_nonzero_word3_targets_by_descriptor_kind() -> None:
    assert _descriptor_kind_nonzero_word3_offset_candidate_target_counts(
        {
            "array": {"resource_reference|string_length_prefix": 2},
            "transform": {"member_type|string_end": 3},
        }
    ) == {
        "array|resource_reference|string_length_prefix": 2,
        "transform|member_type|string_end": 3,
    }


def test_prefab_corpus_counts_same_target_overlap_collapse_candidates() -> None:
    same_a = SimpleNamespace(offset=100, value=64, target_kind="string_length_prefix", target_field_index=7)
    same_b = SimpleNamespace(offset=103, value=64, target_kind="string_length_prefix", target_field_index=7)
    mixed_a = SimpleNamespace(offset=200, value=80, target_kind="string_length_prefix", target_field_index=8)
    mixed_b = SimpleNamespace(offset=201, value=81, target_kind="string_length_prefix", target_field_index=8)
    decoded = SimpleNamespace(offset_candidates=(same_a, same_b, mixed_a, mixed_b))

    counts = _resize_impact_unique_offset_candidate_same_target_overlap_collapse_counts(
        decoded,
        [{"offset": 0, "byte_length": 10}],
    )

    assert counts == {
        "impacted_overlap_group_count": 2,
        "impacted_overlap_candidate_count": 4,
        "same_target_duplicate_group_count": 1,
        "same_target_duplicate_candidate_count": 2,
        "mixed_target_group_count": 1,
        "mixed_target_candidate_count": 2,
        "blocker_group_count_after_same_target_collapse": 1,
        "blocker_candidate_count_after_same_target_collapse": 2,
    }


def test_prefab_corpus_counts_same_target_overlap_shift_conflicts() -> None:
    first = SimpleNamespace(offset=0, value=65536, target_kind="string_length_prefix", target_field_index=7)
    second = SimpleNamespace(offset=3, value=65536, target_kind="string_length_prefix", target_field_index=7)
    decoded = SimpleNamespace(offset_candidates=(first, second), layout=SimpleNamespace(spans=()), member_declarations=(), references=())
    rows = [{"offset": 0, "byte_length": 10}]
    payload = bytes.fromhex("00000100000100")

    counts = _resize_impact_unique_offset_candidate_same_target_overlap_shift_conflict_counts(
        decoded,
        rows,
        payload,
    )

    assert counts == {
        "same_target_overlap_group_count": 1,
        "same_target_overlap_candidate_count": 2,
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "shift_conflict_group_count": 1,
        "shift_conflict_candidate_count": 2,
    }
    assert _resize_impact_unique_offset_candidate_same_target_shift_conflict_group_detail_counts(
        decoded,
        rows,
        payload,
    ) == {
        "size_2|deltas_0,3|"
        "group=delta_0:other_string|string_length_prefix|value_65536|field_7||word_00000100|mod4_0|outside_preserved_span,"
        "delta_3:other_string|string_length_prefix|value_65536|field_7||word_00000100|mod4_3|outside_preserved_span|"
        "impacted=delta_0:other_string|string_length_prefix|value_65536|field_7||word_00000100|mod4_0|outside_preserved_span,"
        "delta_3:other_string|string_length_prefix|value_65536|field_7||word_00000100|mod4_3|outside_preserved_span": 1,
    }

    resource_decoded = SimpleNamespace(
        offset_candidates=(first, second),
        layout=SimpleNamespace(spans=(SimpleNamespace(kind="preserved", start=-100, end=30),)),
        member_declarations=(),
        references=(SimpleNamespace(field=SimpleNamespace(index=7), text="object/test.pami"),),
    )
    assert _resize_impact_unique_offset_candidate_same_target_resource_alias_counts(
        resource_decoded,
        rows,
        payload,
    ) == {
        "same_target_conflict_group_count": 1,
        "same_target_conflict_candidate_count": 2,
        "resource_alias_group_count": 1,
        "resource_alias_candidate_count": 2,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }
    assert _selected_resize_offset_candidate_metrics(
        resource_decoded,
        [(0, 1)],
        payload,
    )["selected_resize_offset_candidate_same_target_resource_alias_counts"] == {
        "same_target_shift_conflict_group_count": 1,
        "same_target_shift_conflict_candidate_count": 2,
        "resource_alias_group_count": 1,
        "resource_alias_candidate_count": 2,
        "resource_reference_non_alias_group_count": 0,
        "resource_reference_non_alias_candidate_count": 0,
        "other_group_count": 0,
        "other_candidate_count": 0,
    }


def test_prefab_corpus_counts_mixed_target_overlap_shift_conflicts() -> None:
    first = SimpleNamespace(offset=0, value=16, target_kind="string_length_prefix", target_field_index=7)
    second = SimpleNamespace(offset=1, value=20, target_kind="string_length_prefix", target_field_index=8)
    decoded = SimpleNamespace(offset_candidates=(first, second))

    counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_shift_conflict_counts(
        decoded,
        [{"offset": 0, "byte_length": 10}],
        bytes(8),
    )

    assert counts == {
        "mixed_target_overlap_group_count": 1,
        "mixed_target_overlap_candidate_count": 2,
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "shift_conflict_group_count": 1,
        "shift_conflict_candidate_count": 2,
    }


def test_prefab_corpus_summarizes_mixed_target_shift_consistent_groups() -> None:
    first = SimpleNamespace(offset=0, value=16, target_kind="string_length_prefix", target_field_index=7)
    second = SimpleNamespace(offset=1, value=83886079, target_kind="string_length_prefix", target_field_index=8)
    decoded = SimpleNamespace(
        offset_candidates=(first, second),
        layout=SimpleNamespace(spans=()),
        member_declarations=(),
        references=(),
    )
    rows = [{"offset": 0, "byte_length": 1}]
    payload = bytes(8)

    assert _resize_impact_unique_offset_candidate_mixed_target_overlap_shift_conflict_counts(
        decoded,
        rows,
        payload,
    ) == {
        "mixed_target_overlap_group_count": 1,
        "mixed_target_overlap_candidate_count": 2,
        "shift_consistent_group_count": 1,
        "shift_consistent_candidate_count": 2,
        "shift_conflict_group_count": 0,
        "shift_conflict_candidate_count": 0,
    }
    assert _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_profile_counts(
        decoded,
        rows,
        payload,
    ) == {
        "size_2|width_5|deltas_0,1|group=outside_member_descriptor:other_string:string_length_prefix|"
        "impacted=outside_member_descriptor:other_string:string_length_prefix": 1,
    }
    assert _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_identity_counts(
        decoded,
        rows,
        payload,
    ) == {
        "other_string|string_length_prefix|value_16|field_7|": 1,
        "other_string|string_length_prefix|value_83886079|field_8|": 1,
    }
    assert _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_shape_counts(
        decoded,
        rows,
        payload,
    ) == {
        "other_string|string_length_prefix|value_16|field_7||word_00000000|mod4_0|outside_preserved_span|deltas_0,1": 1,
        "other_string|string_length_prefix|value_83886079|field_8||word_00000000|mod4_1|outside_preserved_span|deltas_0,1": 1,
    }
    assert _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_group_detail_counts(
        decoded,
        rows,
        payload,
    ) == {
        "size_2|deltas_0,1|"
        "group=delta_0:other_string|string_length_prefix|value_16|field_7||word_00000000|mod4_0|outside_preserved_span,"
        "delta_1:other_string|string_length_prefix|value_83886079|field_8||word_00000000|mod4_1|outside_preserved_span|"
        "impacted=delta_0:other_string|string_length_prefix|value_16|field_7||word_00000000|mod4_0|outside_preserved_span,"
        "delta_1:other_string|string_length_prefix|value_83886079|field_8||word_00000000|mod4_1|outside_preserved_span": 1,
    }


def test_prefab_corpus_counts_shift_consistent_bool_metadata_collisions() -> None:
    impacted = SimpleNamespace(offset=0, value=49407, target_kind="string_value", target_field_index=2259)
    bool_end = SimpleNamespace(offset=1, value=192, target_kind="string_end", target_field_index=8)
    decoded = SimpleNamespace(
        offset_candidates=(impacted, bool_end),
        layout=SimpleNamespace(spans=()),
        member_declarations=(SimpleNamespace(type_field_index=8, name_field_index=-1, type_name="bool"),),
        references=(),
    )

    assert _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_metadata_collision_counts(
        decoded,
        [{"offset": 0, "byte_length": 200}],
        bytes.fromhex("ffc0000000"),
    ) == {
        "shift_consistent_group_count": 1,
        "shift_consistent_candidate_count": 1,
        "metadata_collision_group_count": 1,
        "metadata_collision_candidate_count": 1,
        "remaining_group_count": 0,
        "remaining_candidate_count": 0,
    }


def test_offset_candidate_remap_counts_metadata_target_misses() -> None:
    before = SimpleNamespace(
        references=(SimpleNamespace(field=SimpleNamespace(index=2), text="asset/path.pat"),),
        member_declarations=(),
        offset_candidates=(
            SimpleNamespace(offset=10, value=20, target_kind="string_length_prefix", target_field_index=1),
            SimpleNamespace(offset=30, value=40, target_kind="string_length_prefix", target_field_index=2),
        ),
    )
    after = SimpleNamespace(offset_candidates=())
    after_payload = bytearray(48)
    after_payload[10:14] = (20).to_bytes(4, "little")
    after_payload[35:39] = (45).to_bytes(4, "little")

    metrics = _offset_candidate_remap_metrics_after_resize(before, after, [(15, 5)], bytes(after_payload))

    assert metrics["report_only_effective_remap_status"] == "blocked_missing_shifted_or_unknown_values"
    assert metrics["effectively_remapped"] is False
    assert metrics["missing_count"] == 2
    assert metrics["missing_metadata_target_count"] == 1
    assert metrics["missing_non_metadata_target_count"] == 1
    assert metrics["missing_metadata_owner_kind_target_role_kind_counts"] == {
        "outside_member_descriptor|other_string|string_length_prefix": 1
    }
    assert metrics["missing_non_metadata_owner_kind_target_role_kind_counts"] == {
        "outside_member_descriptor|resource_reference|string_length_prefix": 1
    }
    assert metrics["missing_non_metadata_resource_reference_extension_counts"] == {".pat": 1}
    assert metrics["missing_non_metadata_resource_reference_target_kind_extension_counts"] == {
        "string_length_prefix|.pat": 1
    }
    assert metrics["missing_non_metadata_resource_reference_target_name_top_counts"] == {"path.pat": 1}
    assert metrics["missing_unshifted_value_at_expected_offset_count"] == 1
    assert metrics["missing_shifted_value_at_expected_offset_count"] == 1
    assert metrics["missing_other_value_at_expected_offset_count"] == 0
    assert metrics["missing_out_of_bounds_expected_offset_count"] == 0
    assert metrics["missing_after_excluding_unshifted_value_at_expected_offset_count"] == 1
    assert metrics["remapped_after_excluding_unshifted_value_at_expected_offset"] is False
    assert metrics["missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts"] == {
        "outside_member_descriptor|other_string|string_length_prefix": 1
    }


def test_offset_candidate_remap_effective_pass_excludes_preserved_raw_values() -> None:
    before = SimpleNamespace(
        references=(),
        member_declarations=(),
        offset_candidates=(
            SimpleNamespace(offset=10, value=20, target_kind="string_length_prefix", target_field_index=1),
            SimpleNamespace(offset=30, value=40, target_kind="string_length_prefix", target_field_index=2),
        ),
    )
    after = SimpleNamespace(offset_candidates=())
    after_payload = bytearray(48)
    after_payload[15:19] = (20).to_bytes(4, "little")
    after_payload[35:39] = (40).to_bytes(4, "little")

    metrics = _offset_candidate_remap_metrics_after_resize(before, after, [(5, 5)], bytes(after_payload))

    assert metrics["report_only_effective_remap_status"] == "preserved_raw_exclusion_passed"
    assert metrics["effectively_remapped"] is True
    assert metrics["remapped"] is False
    assert metrics["missing_count"] == 2
    assert metrics["missing_unshifted_value_at_expected_offset_count"] == 2
    assert metrics["missing_after_excluding_unshifted_value_at_expected_offset_count"] == 0
    assert metrics["remapped_after_excluding_unshifted_value_at_expected_offset"] is True


def test_offset_candidate_remap_effective_pass_requires_payload_evidence() -> None:
    before = SimpleNamespace(
        references=(),
        member_declarations=(),
        offset_candidates=(
            SimpleNamespace(offset=10, value=20, target_kind="string_length_prefix", target_field_index=1),
        ),
    )
    after = SimpleNamespace(offset_candidates=())

    metrics = _offset_candidate_remap_metrics_after_resize(before, after, [(5, 5)])

    assert metrics["report_only_effective_remap_status"] == "blocked_missing_shifted_or_unknown_values"
    assert metrics["effectively_remapped"] is False
    assert metrics["missing_count"] == 1
    assert metrics["missing_unshifted_value_at_expected_offset_count"] == 0
    assert metrics["missing_after_excluding_unshifted_value_at_expected_offset_count"] == 1
    assert metrics["remapped_after_excluding_unshifted_value_at_expected_offset"] is False


def test_effective_offset_value_replacements_exclude_preserved_raw_candidates() -> None:
    before = SimpleNamespace(
        offset_candidates=(
            SimpleNamespace(offset=10, value=20),
            SimpleNamespace(offset=30, value=40),
        ),
    )
    after_payload = bytearray(64)
    after_payload[15:19] = (20).to_bytes(4, "little")
    after_payload[35:39] = (45).to_bytes(4, "little")

    assert _effective_offset_value_replacements_after_resize(before, [(5, 5)], bytes(after_payload)) == (
        (30, 45),
    )


def test_prefab_corpus_counts_high_repeat_identity_collapse_candidates() -> None:
    candidates = []
    for index in range(10):
        base = 100 + index * 10
        candidates.extend(
            [
                SimpleNamespace(
                    offset=base,
                    value=65536,
                    target_kind="string_length_prefix",
                    target_field_index=7,
                ),
                SimpleNamespace(
                    offset=base + 1,
                    value=70000 + index,
                    target_kind="string_length_prefix",
                    target_field_index=20 + index,
                ),
            ]
        )
    decoded = SimpleNamespace(offset_candidates=tuple(candidates))
    payload = b"\x00" * 256

    counts = _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_collapse_counts(
        decoded,
        [{"offset": 0, "byte_length": 10}],
    )

    assert counts == {
        "mixed_target_group_count": 10,
        "mixed_target_candidate_count": 20,
        "high_repeat_identity_count": 1,
        "high_repeat_candidate_count": 10,
        "remaining_group_count_after_high_repeat_collapse": 10,
        "remaining_candidate_count_after_high_repeat_collapse": 10,
    }
    assert _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_profile_counts(
        decoded,
        [{"offset": 0, "byte_length": 10}],
    ) == {
        "size_2|width_5|deltas_0,1|group=outside_member_descriptor:other_string:string_length_prefix|remaining=outside_member_descriptor:other_string:string_length_prefix": 10,
    }
    assert _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_identity_counts(
        decoded,
        [{"offset": 0, "byte_length": 10}],
    ) == {
        f"other_string|string_length_prefix|value_{70000 + index}|field_{20 + index}|": 1
        for index in range(10)
    }
    assert _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_role_counts(
        decoded,
        [{"offset": 0, "byte_length": 10}],
    ) == {
        "remaining_group_count": 10,
        "remaining_candidate_count": 10,
        "remaining_resource_reference_candidate_count": 0,
        "remaining_metadata_candidate_count": 10,
        "remaining_resource_reference_group_count": 0,
        "remaining_metadata_only_group_count": 10,
    }
    assert _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_shape_counts(
        decoded,
        [{"offset": 0, "byte_length": 10}],
        payload,
    ) == {
        (
            f"other_string|string_length_prefix|value_{70000 + index}|field_{20 + index}|"
            f"|word_00000000|mod4_{(101 + index * 10) % 4}|outside_preserved_span|deltas_0,1"
        ): 1
        for index in range(10)
    }


def test_prefab_corpus_details_remaining_resource_reference_overlap_groups() -> None:
    resource = SimpleNamespace(offset=0, value=20, target_kind="string_value", target_field_index=99)
    metadata = SimpleNamespace(offset=1, value=21, target_kind="string_end", target_field_index=8)
    decoded = SimpleNamespace(
        offset_candidates=(resource, metadata),
        layout=SimpleNamespace(spans=()),
        member_declarations=(SimpleNamespace(type_field_index=8, name_field_index=-1, type_name="bool"),),
        references=(SimpleNamespace(field=SimpleNamespace(index=99), text="object/test.pami"),),
    )

    assert _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts(
        decoded,
        [{"offset": 0, "byte_length": 10}],
        bytes.fromhex("0102030405"),
    ) == {
        "size_2|deltas_0,1|"
        "group=delta_0:resource_reference|string_value|value_20|field_99|object/test.pami|word_01020304|mod4_0|outside_preserved_span,"
        "delta_1:member_type|string_end|value_21|field_8|bool|word_02030405|mod4_1|outside_preserved_span|"
        "remaining_resource_reference=delta_0:resource_reference|string_value|value_20|field_99|object/test.pami|word_01020304|mod4_0|outside_preserved_span": 1,
    }


def test_prefab_corpus_counts_remaining_resource_reference_metadata_collisions() -> None:
    resource = SimpleNamespace(offset=0, value=200, target_kind="string_value", target_field_index=99)
    metadata = SimpleNamespace(offset=1, value=201, target_kind="string_end", target_field_index=8)
    other_resource = SimpleNamespace(offset=20, value=232, target_kind="string_value", target_field_index=100)
    colliding_resource = SimpleNamespace(offset=21, value=233, target_kind="string_end", target_field_index=101)
    decoded = SimpleNamespace(
        offset_candidates=(resource, metadata, other_resource, colliding_resource),
        member_declarations=(SimpleNamespace(type_field_index=8, name_field_index=-1, type_name="bool"),),
        references=(
            SimpleNamespace(field=SimpleNamespace(index=99), text="object/test_a.pami"),
            SimpleNamespace(field=SimpleNamespace(index=100), text="object/test_b.pami"),
            SimpleNamespace(field=SimpleNamespace(index=101), text="object/test_c.pami"),
        ),
    )

    assert _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts(
        decoded,
        [{"offset": 0, "byte_length": 100}],
    ) == {
        "remaining_resource_reference_group_count": 2,
        "remaining_resource_reference_candidate_count": 3,
        "metadata_collision_group_count": 1,
        "metadata_collision_candidate_count": 1,
        "remaining_group_count": 1,
        "remaining_candidate_count": 2,
    }


def test_prefab_corpus_counts_remaining_resource_reference_nonimpacted_reference_collisions() -> None:
    resource = SimpleNamespace(offset=0, value=200, target_kind="string_value", target_field_index=99)
    nonimpacted_resource = SimpleNamespace(offset=1, value=20, target_kind="string_end", target_field_index=100)
    other_resource = SimpleNamespace(offset=20, value=232, target_kind="string_value", target_field_index=101)
    impacted_resource = SimpleNamespace(offset=21, value=233, target_kind="string_end", target_field_index=102)
    decoded = SimpleNamespace(
        offset_candidates=(resource, nonimpacted_resource, other_resource, impacted_resource),
        member_declarations=(),
        references=(
            SimpleNamespace(field=SimpleNamespace(index=99), text="object/test_a.pami"),
            SimpleNamespace(field=SimpleNamespace(index=100), text="object/test_b.pami"),
            SimpleNamespace(field=SimpleNamespace(index=101), text="object/test_c.pami"),
            SimpleNamespace(field=SimpleNamespace(index=102), text="object/test_d.pami"),
        ),
    )

    assert _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts(
        decoded,
        [{"offset": 0, "byte_length": 100}],
    ) == {
        "remaining_resource_reference_group_count": 2,
        "remaining_resource_reference_candidate_count": 3,
        "nonimpacted_reference_collision_group_count": 1,
        "nonimpacted_reference_collision_candidate_count": 1,
        "remaining_group_count": 1,
        "remaining_candidate_count": 2,
    }


def test_prefab_corpus_discovers_loose_prefabs_only(tmp_path: Path) -> None:
    _write_prefab(tmp_path / "a.prefab", "test_a")
    _write_prefab(tmp_path / "nested" / "b.PREFAB", "test_b")
    (tmp_path / "ignore.txt").write_text("character/model/test_c.pac", encoding="utf-8")

    paths = discover_loose_prefab_corpus_paths([tmp_path])

    assert [path.name for path in paths] == ["a.prefab", "b.PREFAB"]


def test_prefab_corpus_report_proves_no_edit_roundtrip(tmp_path: Path) -> None:
    _write_prefab(tmp_path / "a.prefab", "test_a")
    _write_prefab(tmp_path / "nested" / "b.prefab", "test_b")

    report = build_prefab_json_import_corpus_report([tmp_path])

    assert report["format"] == PREFAB_JSON_IMPORT_CORPUS_FORMAT
    assert report["summary"]["files_discovered"] == 2
    assert report["summary"]["files_scanned"] == 2
    assert report["summary"]["edit_probes_enabled"] is True
    assert report["summary"]["discovery_limited"] is False
    assert report["summary"]["all_discovered_files_scanned"] is True
    assert report["summary"]["no_edit_roundtrip_passed"] == 2
    assert report["summary"]["layout_rebuild_passed"] == 2
    assert report["summary"]["layout_rebuild_failed"] == 0
    assert report["summary"]["json_layout_rebuild_passed"] == 2
    assert report["summary"]["json_layout_rebuild_failed"] == 0
    assert report["summary"]["prefab_header_versions"] == {"4": 2}
    assert report["summary"]["layout_fully_accounted_files"] == 2
    assert report["summary"]["preserved_unknown_bytes"] == 8
    assert report["summary"]["member_descriptor_preserved_bytes"] == 0
    assert report["summary"]["member_descriptor_header_preserved_bytes"] == 0
    assert report["summary"]["member_descriptor_tail_preserved_bytes"] == 0
    assert report["summary"]["preserved_unknown_bytes_excluding_member_descriptors"] == 8
    assert report["summary"]["preserved_unknown_bytes_excluding_member_descriptor_headers"] == 8
    assert report["summary"]["preserved_unknown_bytes_without_block_semantics"] == 8
    assert report["summary"]["preserved_spans_with_member_descriptors"] == 0
    assert report["summary"]["preserved_spans_with_member_descriptor_headers"] == 0
    assert report["summary"]["preserved_spans_with_member_descriptor_tails"] == 0
    assert report["summary"]["preserved_spans_without_member_descriptors"] == 2
    assert report["summary"]["parsed_string_bytes"] > 0
    assert report["summary"]["member_declaration_rows"] == 0
    assert report["summary"]["member_descriptor_bytes"] == 0
    assert report["summary"]["descriptor_tail_member_kind_counts"] == {}
    assert report["summary"]["descriptor_tail_byte_kind_counts"] == {}
    assert report["summary"]["descriptor_tail_member_detail_counts"] == {}
    assert report["summary"]["transform_member_rows"] == 0
    assert report["summary"]["decoded_transform_payload_value_rows"] == 0
    assert report["summary"]["transform_members_without_payload_values"] == 0
    assert report["summary"]["transform_members_with_descriptor_tail_bytes"] == 0
    assert report["summary"]["transform_descriptor_tail_bytes"] == 0
    assert report["summary"]["transform_name_only_member_rows"] == 0
    assert report["summary"]["transform_descriptor_signature_counts"] == {}
    assert report["summary"]["transform_descriptor_signature_offset_candidate_counts"] == {}
    assert report["summary"]["transform_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["transform_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["summary"]["transform_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["summary"]["transform_descriptor_word0_value_counts"] == {}
    assert report["summary"]["transform_descriptor_word1_value_counts"] == {}
    assert report["summary"]["transform_descriptor_word2_value_counts"] == {}
    assert report["summary"]["transform_descriptor_word3_value_counts"] == {}
    assert report["summary"]["array_member_rows"] == 0
    assert report["summary"]["decoded_array_payload_element_rows"] == 0
    assert report["summary"]["array_members_without_payload_elements"] == 0
    assert report["summary"]["array_members_with_descriptor_tail_bytes"] == 0
    assert report["summary"]["array_descriptor_tail_bytes"] == 0
    assert report["summary"]["array_member_stride_hint_rows"] == 0
    assert report["summary"]["array_member_count_hint_rows"] == 0
    assert report["summary"]["array_descriptor_signature_counts"] == {}
    assert report["summary"]["array_descriptor_signature_offset_candidate_counts"] == {}
    assert report["summary"]["array_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["summary"]["array_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["summary"]["array_descriptor_word0_value_counts"] == {}
    assert report["summary"]["array_descriptor_word1_value_counts"] == {}
    assert report["summary"]["array_descriptor_word2_value_counts"] == {}
    assert report["summary"]["array_descriptor_word3_value_counts"] == {}
    assert report["summary"]["array_stride_hint_type_counts"] == {}
    assert report["summary"]["array_count_hint_type_counts"] == {}
    assert report["summary"]["array_count_hint_member_counts"] == {}
    assert report["summary"]["array_word2_delta_member_counts"] == {}
    assert report["summary"]["array_word2_delta_word3_member_counts"] == {}
    assert report["summary"]["array_word2_delta_word3_member_offset_candidate_counts"] == {}
    assert report["summary"]["array_classification_source_counts"] == {
        "name_list_flag_count": 0,
        "type_brackets_count": 0,
        "type_vector_count": 0,
    }
    assert report["summary"]["array_word3_category_counts"] == {
        "nonzero_with_stride_hint_count": 0,
        "nonzero_without_stride_hint_count": 0,
        "one_count": 0,
        "other_nonzero_count": 0,
        "power_of_two_gt_one_count": 0,
        "zero_count": 0,
    }
    assert report["summary"]["reference_member_rows"] == 0
    assert report["summary"]["reference_members_without_descriptor_semantics"] == 0
    assert report["summary"]["reference_members_with_descriptor_tail_bytes"] == 0
    assert report["summary"]["reference_descriptor_tail_bytes"] == 0
    assert report["summary"]["reference_descriptor_signature_counts"] == {}
    assert report["summary"]["reference_descriptor_signature_offset_candidate_counts"] == {}
    assert report["summary"]["reference_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["reference_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["summary"]["reference_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["summary"]["scalar_or_bool_descriptor_signature_counts"] == {}
    assert report["summary"]["scalar_or_bool_descriptor_signature_offset_candidate_counts"] == {}
    assert report["summary"]["scalar_or_bool_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["scalar_or_bool_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["summary"]["scalar_or_bool_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["summary"]["string_descriptor_signature_counts"] == {}
    assert report["summary"]["string_descriptor_signature_offset_candidate_counts"] == {}
    assert report["summary"]["string_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["string_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["summary"]["string_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["summary"]["generic_descriptor_signature_counts"] == {}
    assert report["summary"]["generic_descriptor_signature_offset_candidate_counts"] == {}
    assert report["summary"]["generic_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["generic_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["summary"]["generic_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["summary"]["descriptor_kind_nonzero_word3_offset_candidate_status_counts"] == {
        "array|with_offset_candidate": 0,
        "array|without_offset_candidate": 0,
        "generic|with_offset_candidate": 0,
        "generic|without_offset_candidate": 0,
        "reference|with_offset_candidate": 0,
        "reference|without_offset_candidate": 0,
        "scalar_or_bool|with_offset_candidate": 0,
        "scalar_or_bool|without_offset_candidate": 0,
        "string|with_offset_candidate": 0,
        "string|without_offset_candidate": 0,
        "transform|with_offset_candidate": 0,
        "transform|without_offset_candidate": 0,
    }
    assert report["summary"]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["summary"]["descriptor_owner_kind_offset_candidate_counts"] == {}
    assert report["summary"]["descriptor_owner_kind_offset_candidate_target_counts"] == {}
    assert report["summary"]["offset_candidate_rows"] == 0
    assert report["summary"]["offset_candidate_overlap_rows"] == 0
    assert report["summary"]["offset_candidate_aligned_rows"] == 0
    assert report["summary"]["offset_candidate_unaligned_rows"] == 0
    assert report["summary"]["offset_candidate_overlap_group_rows"] == 0
    assert report["summary"]["offset_candidate_overlapping_window_rows"] == 0
    assert report["summary"]["offset_candidate_isolated_rows"] == 0
    assert report["summary"]["offset_candidate_aligned_isolated_rows"] == 0
    assert report["summary"]["offset_candidate_unaligned_isolated_rows"] == 0
    assert report["summary"]["offset_candidate_unaligned_or_overlapping_rows"] == 0
    assert report["summary"]["offset_candidate_target_string_length_prefix_rows"] == 0
    assert report["summary"]["offset_candidate_target_string_value_rows"] == 0
    assert report["summary"]["offset_candidate_target_string_end_rows"] == 0
    assert report["summary"]["offset_candidate_in_member_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_in_array_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_in_transform_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_in_reference_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_in_scalar_or_bool_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_aligned_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_unaligned_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_overlap_group_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_overlapping_window_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_isolated_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_aligned_isolated_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_unaligned_isolated_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_unaligned_or_overlapping_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_target_string_length_prefix_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_target_string_value_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_target_string_end_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_target_value_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_neighbor_byte_class_counts"] == {
        "ascii_like": 0,
        "binary_like": 0,
        "empty": 0,
        "nul_rich": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_target_role_counts"] == {
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
        "resource_reference_count": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_string_value_target_role_counts"] == {
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
        "resource_reference_count": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_aligned_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_unaligned_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_isolated_rows"] == 0
    assert (
        report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_rows"]
        == 0
    )
    assert (
        report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_rows"]
        == 0
    )
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_target_string_value_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_target_string_end_rows"] == 0
    assert (
        report["summary"][
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts"
        ]
        == {}
    )
    assert (
        report["summary"][
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts"
        ]
        == {}
    )
    assert (
        report["summary"][
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts"
        ]
        == {}
    )
    assert (
        report["summary"][
            "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts"
        ]
        == {}
    )
    assert (
        report["summary"][
            "offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts"
        ]
        == {}
    )
    assert (
        report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts"]
        == {}
    )
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts"
    ] == {
        "le_16": 0,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts"
    ] == {
        "le_16": 0,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }
    assert (
        report["summary"][
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts"
        ]
        == {}
    )
    assert (
        report["summary"][
            "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts"
        ]
        == {}
    )
    assert report["summary"]["offset_candidate_in_preserved_span_rows"] == 0
    assert report["summary"]["offset_candidate_outside_preserved_span_rows"] == 0
    assert report["summary"]["offset_candidate_preserved_span_exact_4_rows"] == 0
    assert report["summary"]["offset_candidate_preserved_span_le_8_rows"] == 0
    assert report["summary"]["offset_candidate_at_preserved_span_start_rows"] == 0
    assert report["summary"]["offset_candidate_at_preserved_span_end_rows"] == 0
    assert report["summary"]["offset_candidate_in_preserved_span_middle_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_preserved_span_exact_4_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_preserved_span_le_8_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_preserved_span_middle_rows"] == 0
    assert report["summary"]["largest_preserved_span_bytes"] == 4
    assert report["summary"]["preserved_spans_with_offset_candidates"] == 0
    assert report["summary"]["preserved_spans_without_offset_candidates"] == 2
    assert report["summary"]["files_with_offset_candidates"] == 0
    assert report["summary"]["files_with_offset_candidate_overlaps"] == 0
    assert report["summary"]["editable_reference_rows"] == 2
    assert report["summary"]["editable_placement_field_rows"] == 0
    assert report["summary"]["resource_resize_impact_offset_candidate_rows"] == 0
    assert report["summary"]["placement_resize_impact_offset_candidate_rows"] == 0
    assert report["summary"]["resource_resize_impact_target_role_kind_counts"] == {}
    assert report["summary"]["placement_resize_impact_target_role_kind_counts"] == {}
    assert report["summary"]["resource_resize_impact_owner_kind_target_counts"] == {}
    assert report["summary"]["placement_resize_impact_owner_kind_target_counts"] == {}
    assert report["summary"]["resource_resize_impact_resource_reference_target_profile_distance_counts"] == {}
    assert report["summary"]["placement_resize_impact_resource_reference_target_profile_distance_counts"] == {}
    assert report["summary"]["resource_resize_impact_resource_reference_target_profile_span_position_counts"] == {}
    assert report["summary"]["placement_resize_impact_resource_reference_target_profile_span_position_counts"] == {}
    assert report["summary"]["resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts"] == {}
    assert report["summary"]["placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts"] == {}
    assert report["summary"]["resource_resize_impact_unique_offset_candidate_rows"] == 0
    assert report["summary"]["placement_resize_impact_unique_offset_candidate_rows"] == 0
    assert report["summary"]["resource_resize_impact_unique_target_role_kind_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_target_role_kind_counts"] == {}
    assert report["summary"]["resource_resize_impact_unique_owner_kind_target_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_owner_kind_target_counts"] == {}
    assert report["summary"]["resource_resize_impact_unique_candidate_profile_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_candidate_profile_counts"] == {}
    assert report["summary"]["resource_resize_impact_unique_resource_reference_target_profile_distance_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_resource_reference_target_profile_distance_counts"] == {}
    assert report["summary"]["length_change_tail_only_candidate_rows"] == 2
    assert report["summary"]["length_change_downstream_rebuild_rows"] == 0
    assert report["summary"]["length_change_offset_rebuild_rows"] == 0
    assert report["summary"]["policy_resize_readiness_editable_rows"] == 2
    assert report["summary"]["policy_resize_readiness_impacted_rows"] == 0
    assert report["summary"]["policy_resize_readiness_offset_candidate_rows"] == 0
    assert report["summary"]["policy_length_changing_ready_files"] == 0
    assert report["summary"]["files_with_editable_placement_fields"] == 0
    assert report["summary"]["files_with_policy_resize_impacts"] == 0
    assert report["summary"]["same_length_resource_edit_probe_passed"] == 2
    assert report["summary"]["same_length_resource_edit_probe_skipped"] == 0
    assert report["summary"]["same_length_resource_edit_probe_failed"] == 0
    assert report["summary"]["same_length_resource_edit_probe_rows_patched"] == 2
    assert report["summary"]["same_length_placement_edit_probe_passed"] == 0
    assert report["summary"]["same_length_placement_edit_probe_skipped"] == 2
    assert report["summary"]["same_length_placement_edit_probe_failed"] == 0
    assert report["summary"]["experimental_length_change_placement_rebuild_probe_skipped"] == 2
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_passed"] == 2
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_failed"] == 0
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_rows_patched"] == 2
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_byte_delta"] > 0
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_offset_candidate_rows_after_edit"] == 0
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_offset_remap_passed"] == 2
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_effective_offset_remap_passed"] == 2
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_changed_only_expected_passed"] == 2
    assert (
        report["summary"][
            "experimental_length_change_resource_rebuild_probe_changed_only_effective_expected_passed"
        ]
        == 2
    )
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_offset_candidate_count"] == 0
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_non_overlapping_count"] == 0
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_overlapping_count"] == 0
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_target_role_kind_counts"] == {}
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_owner_kind_target_counts"] == {}
    assert (
        report["summary"][
            "experimental_length_change_resource_rebuild_probe_missing_after_effective_offset_remap_exclusion"
        ]
        == 0
    )
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_skip_reasons"] == {}
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_failure_reasons"] == {}
    assert report["summary"]["report_only_array_count_hint_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_array_count_hint_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_array_count_hint_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_array_count_hint_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_array_count_hint_mutation_probe_status_semantics_proven_counts"] == {
        "skipped|false": 2
    }
    assert report["summary"]["report_only_array_count_hint_mutation_probe_skip_reasons"] == {
        "No array descriptor with a nonzero count hint.": 2
    }
    assert report["summary"]["report_only_array_count_hint_mutation_probe_failure_reasons"] == {}
    assert report["summary"]["report_only_transform_word3_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_transform_word3_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_transform_word3_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_transform_word3_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_transform_word3_mutation_probe_status_semantics_proven_counts"] == {
        "skipped|false": 2
    }
    assert report["summary"]["report_only_transform_word3_mutation_probe_skip_reasons"] == {
        "No transform descriptor with a nonzero word3.": 2
    }
    assert report["summary"]["report_only_transform_word3_mutation_probe_failure_reasons"] == {}
    assert report["summary"]["report_only_reference_word3_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_reference_word3_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_reference_word3_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_reference_word3_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_reference_word3_mutation_probe_status_semantics_proven_counts"] == {
        "skipped|false": 2
    }
    assert report["summary"]["report_only_reference_word3_mutation_probe_skip_reasons"] == {
        "No reference descriptor with a nonzero word3.": 2
    }
    assert report["summary"]["report_only_reference_word3_mutation_probe_failure_reasons"] == {}
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_status_semantics_proven_counts"] == {
        "skipped|false": 2
    }
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_skip_reasons"] == {
        "No non-header preserved span available for direct mutation.": 2
    }
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_failure_reasons"] == {}
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_status_semantics_proven_counts"] == {
        "skipped|false": 2
    }
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_skip_reasons"] == {
        "No non-array/non-reference/non-transform descriptor with a nonzero word3.": 2
    }
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_failure_reasons"] == {}
    assert report["gate"]["same_length_import_ready"] is True
    assert report["gate"]["layout_no_edit_rebuild_ready"] is True
    assert report["gate"]["json_layout_no_edit_rebuild_ready"] is True
    assert report["gate"]["same_length_resource_edit_probe_ready"] is True
    assert report["gate"]["same_length_placement_edit_probe_ready"] is False
    assert report["gate"]["experimental_length_change_rebuild_probe_ready"] is True
    assert report["gate"]["full_corpus_no_edit_rebuild_ready"] is True
    assert report["gate"]["length_changing_import_ready"] is False
    assert report["gate"]["length_changing_failed_subgates"] == [
        "resize_offset_validator_ready",
        "descriptor_value_editing_ready",
        "transform_value_editing_ready",
        "array_resizing_ready",
        "unknown_reference_preservation_ready",
    ]
    assert report["gate"]["resource_resize_offset_gate_ready"] is True
    assert report["gate"]["placement_resize_offset_gate_ready"] is False
    assert report["gate"]["resize_offset_validator_ready"] is False
    assert report["gate"]["resource_effective_resize_offset_model_ready"] is True
    assert report["gate"]["placement_effective_resize_offset_model_ready"] is False
    assert report["gate"]["effective_resize_offset_model_ready"] is False
    assert report["gate"]["descriptor_count_semantics_proven"] is False
    assert report["gate"]["descriptor_count_mutation_proven"] is False
    assert report["gate"]["descriptor_value_editing_ready"] is False
    assert report["gate"]["transform_payload_layout_proven"] is False
    assert report["gate"]["transform_value_mutation_proven"] is False
    assert report["gate"]["transform_value_editing_ready"] is False
    assert report["gate"]["array_payload_layout_proven"] is False
    assert report["gate"]["array_count_mutation_proven"] is False
    assert report["gate"]["array_resizing_ready"] is False
    assert report["gate"]["unknown_block_edit_semantics_proven"] is False
    assert report["gate"]["reference_descriptor_edit_semantics_proven"] is False
    assert report["gate"]["unknown_reference_preservation_ready"] is False
    assert report["gate"]["length_changing_blocker_detail_counts"][
        "placement_length_probe_skipped_rows"
    ] == 2
    assert report["gate"]["length_changing_blocker_detail_counts"][
        "placement_non_strict_effective_remap_rows"
    ] == 2
    assert report["gate"]["length_changing_blocker_detail_counts"][
        "resource_non_strict_effective_remap_rows"
    ] == 0
    assert "offset/count rebuild is not proven" in report["gate"]["length_changing_blockers"]
    assert "potential offset references" in "\n".join(report["gate"]["length_changing_blockers"])
    assert (
        "placement length-changing probe skipped rows still block resize-offset readiness"
        in report["gate"]["length_changing_blockers"]
    )
    assert (
        "placement length-changing probes include non-strict effective remap statuses"
        in report["gate"]["length_changing_blockers"]
    )
    assert "unknown/reference descriptor edit semantics are not proven" in report["gate"]["length_changing_blockers"]
    assert "full-corpus no-edit rebuild has not been run" not in report["gate"]["length_changing_blockers"]
    assert {row["status"] for row in report["rows"]} == {"passed"}


def test_prefab_corpus_report_can_skip_edit_probes_for_wide_no_edit_scans(tmp_path: Path) -> None:
    _write_prefab(tmp_path / "a.prefab", "test_a")
    _write_prefab(tmp_path / "nested" / "b.prefab", "test_b")

    report = build_prefab_json_import_corpus_report([tmp_path], include_edit_probes=False)

    assert report["summary"]["edit_probes_enabled"] is False
    assert report["summary"]["discovery_limited"] is False
    assert report["summary"]["all_discovered_files_scanned"] is True
    assert report["summary"]["files_scanned"] == 2
    assert report["summary"]["no_edit_roundtrip_passed"] == 2
    assert report["summary"]["layout_rebuild_passed"] == 2
    assert report["summary"]["json_layout_rebuild_passed"] == 2
    assert report["summary"]["same_length_resource_edit_probe_passed"] == 0
    assert report["summary"]["same_length_resource_edit_probe_skipped"] == 2
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_skipped"] == 2
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_skip_reasons"] == {
        "Edit probes disabled for no-edit-only corpus scan.": 2
    }
    assert report["summary"]["report_only_array_count_hint_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_array_count_hint_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_array_count_hint_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_array_count_hint_mutation_probe_skip_reasons"] == {
        "Edit probes disabled for no-edit-only corpus scan.": 2
    }
    assert report["summary"]["report_only_transform_word3_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_transform_word3_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_transform_word3_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_transform_word3_mutation_probe_skip_reasons"] == {
        "Edit probes disabled for no-edit-only corpus scan.": 2
    }
    assert report["summary"]["report_only_reference_word3_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_reference_word3_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_reference_word3_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_reference_word3_mutation_probe_skip_reasons"] == {
        "Edit probes disabled for no-edit-only corpus scan.": 2
    }
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_skip_reasons"] == {
        "Edit probes disabled for no-edit-only corpus scan.": 2
    }
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_passed"] == 0
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_skipped"] == 2
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_skip_reasons"] == {
        "Edit probes disabled for no-edit-only corpus scan.": 2
    }
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["resource_length_probe_edit_probes_disabled_skipped_rows"] == 2
    assert detail_counts["placement_length_probe_edit_probes_disabled_skipped_rows"] == 2
    assert detail_counts["resource_length_probe_no_safe_candidate_skipped_rows"] == 0
    assert detail_counts["placement_length_probe_no_safe_candidate_skipped_rows"] == 0
    assert detail_counts["resource_length_probe_overlap_ambiguous_skipped_rows"] == 0
    assert report["gate"]["layout_no_edit_rebuild_ready"] is True
    assert report["gate"]["json_layout_no_edit_rebuild_ready"] is True
    assert report["gate"]["full_corpus_no_edit_rebuild_ready"] is True
    assert report["gate"]["same_length_import_ready"] is False
    assert "full-corpus no-edit rebuild has not been run" not in report["gate"]["length_changing_blockers"]
    assert "No-edit proof passed" in report["gate"]["reason"]
    assert {row["same_length_resource_edit_probe"]["status"] for row in report["rows"]} == {"skipped"}


def test_prefab_corpus_report_empty_source_is_not_proof(tmp_path: Path) -> None:
    report = build_prefab_json_import_corpus_report([tmp_path])

    assert report["summary"]["files_discovered"] == 0
    assert report["summary"]["discovery_limited"] is False
    assert report["summary"]["all_discovered_files_scanned"] is False
    assert report["gate"]["same_length_import_ready"] is False
    assert report["gate"]["layout_no_edit_rebuild_ready"] is False
    assert report["gate"]["json_layout_no_edit_rebuild_ready"] is False
    assert report["gate"]["full_corpus_no_edit_rebuild_ready"] is False
    assert report["gate"]["same_length_resource_edit_probe_ready"] is False
    assert report["gate"]["same_length_placement_edit_probe_ready"] is False
    assert report["gate"]["experimental_length_change_rebuild_probe_ready"] is False
    assert "No corpus proof" in report["gate"]["reason"]


def test_prefab_corpus_report_respects_detail_scan_limit(tmp_path: Path) -> None:
    _write_prefab(tmp_path / "a.prefab", "test_a")
    _write_prefab(tmp_path / "b.prefab", "test_b")

    report = build_prefab_json_import_corpus_report([tmp_path], detail_scan_limit=1)

    assert report["summary"]["files_discovered"] == 2
    assert report["summary"]["files_scanned"] == 1
    assert report["summary"]["discovery_limited"] is False
    assert report["summary"]["all_discovered_files_scanned"] is False
    assert report["gate"]["full_corpus_no_edit_rebuild_ready"] is False
    assert len(report["rows"]) == 1


def test_prefab_corpus_report_discovery_limit_is_bounded_not_full_corpus(tmp_path: Path) -> None:
    _write_prefab(tmp_path / "a.prefab", "test_a")
    _write_prefab(tmp_path / "b.prefab", "test_b")

    report = build_prefab_json_import_corpus_report(
        [tmp_path],
        discovery_limit=1,
        detail_scan_limit=None,
        include_edit_probes=False,
    )

    assert report["summary"]["files_discovered"] == 1
    assert report["summary"]["files_scanned"] == 1
    assert report["summary"]["discovery_limited"] is True
    assert report["summary"]["all_discovered_files_scanned"] is True
    assert report["gate"]["layout_no_edit_rebuild_ready"] is True
    assert report["gate"]["json_layout_no_edit_rebuild_ready"] is True
    assert report["gate"]["full_corpus_no_edit_rebuild_ready"] is False
    assert "full-corpus no-edit rebuild has not been run" in report["gate"]["length_changing_blockers"]


def test_prefab_corpus_json_serializes_report(tmp_path: Path) -> None:
    _write_prefab(tmp_path / "a.prefab", "test_a")

    report = json.loads(build_prefab_json_import_corpus_json([tmp_path]))

    assert report["format"] == PREFAB_JSON_IMPORT_CORPUS_FORMAT
    assert report["summary"]["files_scanned"] == 1


def test_prefab_sample_audit_reports_no_edit_result() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")

    row = audit_prefab_json_import_sample(payload, "character/prefab/test.prefab")

    assert row["status"] == "passed"
    assert row["prefab_header"]["magic"] == 0xFFFF
    assert row["prefab_header"]["version"] == 4
    assert row["prefab_layout"]["fully_accounted"] is True
    assert row["prefab_layout"]["accounted_byte_count"] == len(payload)
    assert row["layout_rebuild_byte_identical"] is True
    assert row["json_layout_rebuild_byte_identical"] is True
    assert row["no_edit_roundtrip_byte_identical"] is True
    assert row["member_declaration_count"] == 0
    assert row["member_descriptor_bytes"] == 0
    assert row["descriptor_tail_member_kind_counts"] == {}
    assert row["descriptor_tail_byte_kind_counts"] == {}
    assert row["descriptor_tail_member_detail_counts"] == {}
    assert row["transform_member_count"] == 0
    assert row["decoded_transform_payload_value_rows"] == 0
    assert row["transform_members_without_payload_values"] == 0
    assert row["transform_members_with_descriptor_tail_bytes"] == 0
    assert row["transform_descriptor_tail_bytes"] == 0
    assert row["transform_name_only_member_count"] == 0
    assert row["transform_descriptor_signature_counts"] == {}
    assert row["transform_descriptor_signature_offset_candidate_counts"] == {}
    assert row["transform_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert row["transform_descriptor_signature_offset_candidate_target_counts"] == {}
    assert row["transform_descriptor_word0_value_counts"] == {}
    assert row["transform_descriptor_word1_value_counts"] == {}
    assert row["transform_descriptor_word2_value_counts"] == {}
    assert row["transform_descriptor_word3_value_counts"] == {}
    assert row["array_member_count"] == 0
    assert row["decoded_array_payload_element_rows"] == 0
    assert row["array_members_without_payload_elements"] == 0
    assert row["array_members_with_descriptor_tail_bytes"] == 0
    assert row["array_descriptor_tail_bytes"] == 0
    assert row["array_member_stride_hint_count"] == 0
    assert row["array_member_count_hint_count"] == 0
    assert row["array_descriptor_signature_counts"] == {}
    assert row["array_descriptor_signature_offset_candidate_counts"] == {}
    assert row["array_descriptor_signature_offset_candidate_target_counts"] == {}
    assert row["array_descriptor_word0_value_counts"] == {}
    assert row["array_descriptor_word1_value_counts"] == {}
    assert row["array_descriptor_word2_value_counts"] == {}
    assert row["array_descriptor_word3_value_counts"] == {}
    assert row["array_stride_hint_type_counts"] == {}
    assert row["array_count_hint_type_counts"] == {}
    assert row["array_count_hint_member_counts"] == {}
    assert row["array_word2_delta_member_counts"] == {}
    assert row["array_word2_delta_word3_member_counts"] == {}
    assert row["array_word2_delta_word3_member_offset_candidate_counts"] == {}
    assert row["array_classification_source_counts"] == {
        "type_vector_count": 0,
        "type_brackets_count": 0,
        "name_list_flag_count": 0,
    }
    assert row["array_word3_category_counts"] == {
        "zero_count": 0,
        "one_count": 0,
        "power_of_two_gt_one_count": 0,
        "other_nonzero_count": 0,
        "nonzero_with_stride_hint_count": 0,
        "nonzero_without_stride_hint_count": 0,
    }
    assert row["reference_member_count"] == 0
    assert row["reference_members_without_descriptor_semantics"] == 0
    assert row["reference_members_with_descriptor_tail_bytes"] == 0
    assert row["reference_descriptor_tail_bytes"] == 0
    assert row["reference_descriptor_signature_counts"] == {}
    assert row["reference_descriptor_signature_offset_candidate_counts"] == {}
    assert row["reference_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert row["reference_descriptor_signature_offset_candidate_target_counts"] == {}
    assert row["reference_nonzero_word3_offset_candidate_target_counts"] == {}
    assert row["scalar_or_bool_descriptor_signature_counts"] == {}
    assert row["scalar_or_bool_descriptor_signature_offset_candidate_counts"] == {}
    assert row["scalar_or_bool_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert row["scalar_or_bool_descriptor_signature_offset_candidate_target_counts"] == {}
    assert row["scalar_or_bool_nonzero_word3_offset_candidate_target_counts"] == {}
    assert row["string_descriptor_signature_counts"] == {}
    assert row["string_descriptor_signature_offset_candidate_counts"] == {}
    assert row["string_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert row["string_descriptor_signature_offset_candidate_target_counts"] == {}
    assert row["string_nonzero_word3_offset_candidate_target_counts"] == {}
    assert row["generic_descriptor_signature_counts"] == {}
    assert row["generic_descriptor_signature_offset_candidate_counts"] == {}
    assert row["generic_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert row["generic_descriptor_signature_offset_candidate_target_counts"] == {}
    assert row["generic_nonzero_word3_offset_candidate_target_counts"] == {}
    assert row["descriptor_owner_kind_offset_candidate_counts"] == {}
    assert row["descriptor_owner_kind_offset_candidate_target_counts"] == {}
    assert row["offset_candidate_count"] == 0
    assert row["offset_candidate_overlap_count"] == 0
    assert row["offset_candidate_aligned_count"] == 0
    assert row["offset_candidate_unaligned_count"] == 0
    assert row["offset_candidate_overlap_group_count"] == 0
    assert row["offset_candidate_overlapping_window_count"] == 0
    assert row["offset_candidate_isolated_count"] == 0
    assert row["offset_candidate_aligned_isolated_count"] == 0
    assert row["offset_candidate_unaligned_isolated_count"] == 0
    assert row["offset_candidate_unaligned_or_overlapping_count"] == 0
    assert row["offset_candidate_in_member_descriptor_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_count"] == 0
    assert row["offset_candidate_in_array_descriptor_count"] == 0
    assert row["offset_candidate_in_transform_descriptor_count"] == 0
    assert row["offset_candidate_in_reference_descriptor_count"] == 0
    assert row["offset_candidate_in_scalar_or_bool_descriptor_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_aligned_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_unaligned_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_overlap_group_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_overlapping_window_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_isolated_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_unaligned_isolated_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_target_string_length_prefix_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_target_string_value_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_target_string_end_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_target_value_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_neighbor_byte_class_counts"] == {
        "ascii_like": 0,
        "binary_like": 0,
        "empty": 0,
        "nul_rich": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_target_role_counts"] == {
        "resource_reference_count": 0,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_string_value_target_role_counts"] == {
        "resource_reference_count": 0,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_aligned_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_unaligned_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_isolated_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts"] == {}
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts"] == {}
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts"] == {}
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts"] == {}
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts"] == {}
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts"] == {}
    assert row["offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts"] == {
        "le_16": 0,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts"] == {
        "le_16": 0,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }
    assert row[
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts"
    ] == {}
    assert row[
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts"
    ] == {}
    assert row["offset_candidate_in_preserved_span_count"] == 0
    assert row["offset_candidate_outside_preserved_span_count"] == 0
    assert row["offset_candidate_preserved_span_exact_4_count"] == 0
    assert row["offset_candidate_preserved_span_le_8_count"] == 0
    assert row["offset_candidate_at_preserved_span_start_count"] == 0
    assert row["offset_candidate_at_preserved_span_end_count"] == 0
    assert row["offset_candidate_in_preserved_span_middle_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_preserved_span_exact_4_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_preserved_span_le_8_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_count"] == 0
    assert row["largest_preserved_span_byte_count"] == 4
    assert row["preserved_span_with_offset_candidate_count"] == 0
    assert row["preserved_span_without_offset_candidate_count"] == 1
    assert row["editable_reference_count"] == 1
    assert row["editable_placement_field_count"] == 0
    assert row["resource_resize_impact_offset_candidate_count"] == 0
    assert row["placement_resize_impact_offset_candidate_count"] == 0
    assert row["resource_resize_impact_target_role_kind_counts"] == {}
    assert row["placement_resize_impact_target_role_kind_counts"] == {}
    assert row["resource_resize_impact_owner_kind_target_counts"] == {}
    assert row["placement_resize_impact_owner_kind_target_counts"] == {}
    assert row["resource_resize_impact_resource_reference_target_profile_distance_counts"] == {}
    assert row["placement_resize_impact_resource_reference_target_profile_distance_counts"] == {}
    assert row["resource_resize_impact_resource_reference_target_profile_span_position_counts"] == {}
    assert row["placement_resize_impact_resource_reference_target_profile_span_position_counts"] == {}
    assert row["resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts"] == {}
    assert row["placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts"] == {}
    assert row["resource_resize_impact_unique_offset_candidate_count"] == 0
    assert row["placement_resize_impact_unique_offset_candidate_count"] == 0
    assert row["resource_resize_impact_unique_target_role_kind_counts"] == {}
    assert row["placement_resize_impact_unique_target_role_kind_counts"] == {}
    assert row["resource_resize_impact_unique_owner_kind_target_counts"] == {}
    assert row["placement_resize_impact_unique_owner_kind_target_counts"] == {}
    assert row["resource_resize_impact_unique_candidate_profile_counts"] == {}
    assert row["placement_resize_impact_unique_candidate_profile_counts"] == {}
    assert row["resource_resize_impact_unique_resource_reference_target_profile_distance_counts"] == {}
    assert row["placement_resize_impact_unique_resource_reference_target_profile_distance_counts"] == {}
    assert row["policy_resize_readiness"]["length_changing_import_ready"] is False
    assert row["policy_resize_readiness"]["editable_row_count"] == 1
    assert row["policy_resize_readiness"]["affected_offset_candidate_rows"] == 0
    assert row["length_change_tail_only_candidate_count"] == 1
    assert row["length_change_downstream_rebuild_row_count"] == 0
    assert row["length_change_offset_rebuild_row_count"] == 0
    assert row["same_length_resource_edit_probe"]["status"] == "passed"
    assert row["same_length_resource_edit_probe"]["edited_reference_count"] == 1
    assert row["same_length_resource_edit_probe"]["changed_only_expected_bytes"] is True
    assert row["same_length_resource_edit_probe"]["layout_fully_accounted_after_edit"] is True
    assert row["same_length_placement_edit_probe"]["status"] == "skipped"
    assert row["experimental_length_change_resource_rebuild_probe"]["status"] == "passed"
    assert row["experimental_length_change_resource_rebuild_probe"]["edited_reference_count"] == 1
    assert row["experimental_length_change_resource_rebuild_probe"]["byte_delta"] > 0
    assert row["experimental_length_change_resource_rebuild_probe"]["offset_candidate_count_after_edit"] == 0
    assert row["experimental_length_change_resource_rebuild_probe"]["offset_candidates_remapped_after_edit"] is True
    assert (
        row["experimental_length_change_resource_rebuild_probe"][
            "offset_candidates_effectively_remapped_after_edit"
        ]
        is True
    )
    assert (
        row["experimental_length_change_resource_rebuild_probe"][
            "offset_candidate_report_only_effective_remap_status"
        ]
        == "strict_remap_passed"
    )
    assert row["experimental_length_change_resource_rebuild_probe"]["resized_rebuild_changed_only_expected_bytes"] is True
    assert (
        row["experimental_length_change_resource_rebuild_probe"][
            "resized_rebuild_changed_only_effective_expected_bytes"
        ]
        is True
    )
    assert row["experimental_length_change_resource_rebuild_probe"]["layout_fully_accounted_after_edit"] is True
    assert row["experimental_length_change_resource_rebuild_probe"]["no_edit_rebuild_after_edit"] is True
    assert row["experimental_length_change_resource_rebuild_probe"]["json_no_edit_roundtrip_after_edit"] is True
    assert row["experimental_length_change_resource_rebuild_probe"]["json_layout_rebuild_after_edit"] is True
    assert row["experimental_length_change_resource_rebuild_probe"]["used_opt_in_import_path"] is True
    assert row["experimental_length_change_resource_rebuild_probe"]["replacement_reference_found"] is True


def test_prefab_corpus_report_probes_same_length_placement_edits(tmp_path: Path) -> None:
    path = tmp_path / "profile.prefab"
    path.write_bytes(_prefab_profile_payload())

    report = build_prefab_json_import_corpus_report([tmp_path])
    row = report["rows"][0]

    assert row["editable_placement_field_count"] == 3
    assert row["same_length_placement_edit_probe"]["status"] == "passed"
    assert row["same_length_placement_edit_probe"]["edited_field_count"] == 1
    assert row["same_length_placement_edit_probe"]["changed_only_expected_bytes"] is True
    assert row["same_length_placement_edit_probe"]["layout_fully_accounted_after_edit"] is True
    assert row["experimental_length_change_resource_rebuild_probe"]["status"] == "passed"
    assert row["experimental_length_change_resource_rebuild_probe"]["edited_reference_count"] == 2
    assert row["experimental_length_change_resource_rebuild_probe"]["used_opt_in_import_path"] is True
    assert row["experimental_length_change_resource_rebuild_probe"]["replacement_reference_found"] is True
    # The length-changing placement rebuild is refused on this fixture, and the
    # refusal is the correct outcome rather than a regression. Since a7d92987 a
    # length-changing socket edit goes through exact pointer relocation instead
    # of splicing the new name over the old span, and relocation needs a prefab
    # that decodes all the way through. `_prefab_profile_payload` is a
    # hand-assembled byte string with no real type table, so the walk stops on an
    # implausible type count and the rebuild declines. That commit updated the
    # equivalent expectation in test_archive_relationships.py and missed this
    # one; the old path would have spliced the bytes and left every absolute
    # pointer after the edit addressing the wrong byte.
    placement_rebuild = row["experimental_length_change_placement_rebuild_probe"]
    assert placement_rebuild["status"] == "failed"
    assert placement_rebuild["byte_delta"] == 0
    assert placement_rebuild["replacement_field_found"] is False
    assert placement_rebuild["layout_fully_accounted_after_edit"] is False
    assert placement_rebuild["offset_candidates_remapped_after_edit"] is False
    assert "read all the way through" in placement_rebuild["error"]
    assert "Same-length replacements still work" in placement_rebuild["error"]

    # Same-length editing is untouched by the gate, and it is the capability that
    # actually ships: it moves no bytes, so no pointer can go stale.
    assert report["summary"]["same_length_placement_edit_probe_passed"] == 1
    assert report["summary"]["same_length_placement_edit_probe_failed"] == 0
    assert report["summary"]["same_length_placement_edit_probe_rows_patched"] == 1
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_rows_patched"] == 2
    assert report["summary"]["experimental_length_change_placement_rebuild_probe_passed"] == 0
    assert report["summary"]["experimental_length_change_placement_rebuild_probe_failed"] == 1
    assert report["summary"]["experimental_length_change_placement_rebuild_probe_rows_patched"] == 0

    assert report["gate"]["same_length_placement_edit_probe_ready"] is True
    assert report["gate"]["same_length_import_ready"] is True
    assert report["gate"]["resource_resize_offset_gate_ready"] is True
    assert report["gate"]["resource_effective_resize_offset_model_ready"] is True
    assert report["gate"]["experimental_placement_length_change_rebuild_probe_ready"] is False
    assert report["gate"]["placement_resize_offset_gate_ready"] is False
    assert report["gate"]["placement_effective_resize_offset_model_ready"] is False
    assert report["gate"]["effective_resize_offset_model_ready"] is False
    assert report["gate"]["resize_offset_validator_ready"] is False
    assert report["gate"]["length_changing_import_ready"] is False
    assert report["gate"]["descriptor_value_editing_ready"] is False
    assert report["gate"]["unknown_reference_preservation_ready"] is False
    assert "offset/count rebuild is not proven" in report["gate"]["length_changing_blockers"]
    assert "unknown/reference descriptor edit semantics are not proven" in report["gate"]["length_changing_blockers"]
    assert (
        "placement length-changing probe failed rows still block resize-offset readiness"
        in report["gate"]["length_changing_blockers"]
    )


def test_prefab_corpus_report_probes_array_count_hint_direct_mutation(tmp_path: Path) -> None:
    (tmp_path / "array.prefab").write_bytes(_prefab_array_count_hint_payload())

    report = build_prefab_json_import_corpus_report([tmp_path])
    row = report["rows"][0]
    probe = row["report_only_array_count_hint_mutation_probe"]

    assert row["array_member_count"] == 1
    assert row["decoded_array_payload_element_rows"] == 0
    assert row["array_members_without_payload_elements"] == 1
    assert row["array_members_with_descriptor_tail_bytes"] == 0
    assert row["array_descriptor_tail_bytes"] == 0
    assert row["array_member_count_hint_count"] == 1
    assert row["array_theoretical_payload_shape_counts"] == {"_items|vector<uint32>|4|3|12": 1}
    assert row["array_theoretical_payload_member_rows"] == 1
    assert row["array_theoretical_payload_byte_count"] == 12
    assert row["array_theoretical_payload_non_tiny_member_rows"] == 1
    assert row["array_theoretical_payload_non_tiny_byte_count"] == 12
    assert row["array_theoretical_payload_exact_preserved_span_rows"] == 0
    assert row["array_theoretical_payload_later_preserved_span_fit_rows"] == 0
    assert row["array_theoretical_payload_no_preserved_span_fit_rows"] == 1
    assert row["array_theoretical_payload_immediate_window_string_span_overlap_rows"] == 1
    assert row["array_theoretical_payload_immediate_window_string_span_overlap_count"] == 1
    assert row["array_theoretical_payload_immediate_window_string_span_role_counts"] == {"resource_reference": 1}
    assert row["array_theoretical_payload_immediate_window_string_span_relation_counts"] == {"resource_reference": 1}
    assert row["array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows"] == 0
    assert row["array_theoretical_payload_later_fit_gap_string_span_relation_counts"] == {}
    assert row["array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts"] == {}
    assert probe["status"] == "passed"
    assert probe["member_name"] == "_items"
    assert probe["member_type"] == "vector<uint32>"
    assert probe["old_count_hint"] == 3
    assert probe["new_count_hint"] == 4
    assert probe["changed_only_expected_bytes"] is True
    assert probe["layout_fully_accounted_after_edit"] is True
    assert probe["no_edit_rebuild_after_edit"] is True
    assert probe["json_no_edit_roundtrip_after_edit"] is True
    assert probe["json_layout_rebuild_after_edit"] is True
    assert probe["decoded_count_hint_changed"] is True
    assert probe["member_identity_preserved"] is True
    assert probe["semantics_proven"] is False
    assert report["summary"]["report_only_array_count_hint_mutation_probe_passed"] == 1
    assert report["summary"]["report_only_array_count_hint_mutation_probe_skipped"] == 0
    assert report["summary"]["report_only_array_count_hint_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_array_count_hint_mutation_probe_changed_only_expected_passed"] == 1
    assert report["summary"]["report_only_array_count_hint_mutation_probe_layout_fully_accounted_passed"] == 1
    assert report["summary"]["report_only_array_count_hint_mutation_probe_no_edit_rebuild_passed"] == 1
    assert report["summary"]["report_only_array_count_hint_mutation_probe_json_no_edit_roundtrip_passed"] == 1
    assert report["summary"]["report_only_array_count_hint_mutation_probe_json_layout_rebuild_passed"] == 1
    assert report["summary"]["report_only_array_count_hint_mutation_probe_decoded_count_hint_changed"] == 1
    assert report["summary"]["report_only_array_count_hint_mutation_probe_member_identity_preserved"] == 1
    assert report["summary"]["report_only_array_count_hint_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_array_count_hint_mutation_probe_status_semantics_proven_counts"] == {
        "passed|false": 1
    }
    assert report["summary"]["report_only_array_count_hint_mutation_probe_member_counts"] == {"_items": 1}
    assert report["summary"]["report_only_array_count_hint_mutation_probe_type_counts"] == {"vector<uint32>": 1}
    assert report["summary"]["report_only_array_count_hint_mutation_probe_skip_reasons"] == {}
    assert report["summary"]["report_only_array_count_hint_mutation_probe_failure_reasons"] == {}
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["array_count_hint_mutation_probe_non_skipped_rows"] == 1
    assert detail_counts["array_count_hint_semantic_missing_rows"] == 1
    assert report["gate"]["array_count_hint_semantics_proven"] is False
    assert report["summary"]["decoded_array_payload_element_rows"] == 0
    assert report["summary"]["array_members_without_payload_elements"] == 1
    assert report["summary"]["array_members_with_descriptor_tail_bytes"] == 0
    assert report["summary"]["array_descriptor_tail_bytes"] == 0
    assert report["summary"]["array_theoretical_payload_shape_counts"] == {"_items|vector<uint32>|4|3|12": 1}
    assert report["summary"]["array_theoretical_payload_member_rows"] == 1
    assert report["summary"]["array_theoretical_payload_byte_count"] == 12
    assert report["summary"]["array_theoretical_payload_non_tiny_member_rows"] == 1
    assert report["summary"]["array_theoretical_payload_non_tiny_byte_count"] == 12
    assert report["summary"]["array_theoretical_payload_exact_preserved_span_rows"] == 0
    assert report["summary"]["array_theoretical_payload_later_preserved_span_fit_rows"] == 0
    assert report["summary"]["array_theoretical_payload_no_preserved_span_fit_rows"] == 1
    assert report["summary"]["array_theoretical_payload_immediate_window_string_span_overlap_rows"] == 1
    assert report["summary"]["array_theoretical_payload_immediate_window_string_span_overlap_count"] == 1
    assert report["summary"]["array_theoretical_payload_immediate_window_string_span_role_counts"] == {
        "resource_reference": 1
    }
    assert report["summary"]["array_theoretical_payload_immediate_window_string_span_relation_counts"] == {
        "resource_reference": 1
    }
    assert report["summary"]["array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows"] == 0
    assert report["summary"]["array_theoretical_payload_later_fit_gap_string_span_relation_counts"] == {}
    assert report["summary"]["array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts"] == {}
    assert report["gate"]["array_payload_layout_proven"] is False
    assert report["gate"]["array_count_mutation_proven"] is False
    assert report["gate"]["array_resizing_ready"] is False
    assert report["gate"]["length_changing_import_ready"] is False
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["array_payload_decoded_element_rows"] == 0
    assert detail_counts["array_payload_missing_member_rows"] == 1
    assert detail_counts["array_payload_immediate_string_overlap_rows"] == 1
    assert detail_counts["array_payload_immediate_string_overlap_count"] == 1
    assert detail_counts["array_payload_later_intervening_rows"] == 0
    assert (
        "array count-hint direct mutation preserves bytes but proves no count semantics"
        in report["gate"]["length_changing_blockers"]
    )
    assert (
        "array theoretical payload ownership is blocked by immediate string-span overlap"
        in report["gate"]["length_changing_blockers"]
    )


def test_prefab_corpus_counts_array_theoretical_payload_exact_span() -> None:
    decoded = SimpleNamespace(
        member_declarations=(
            SimpleNamespace(
                is_array=True,
                array_count_hint=3,
                array_stride_hint=4,
                descriptor_offset=20,
                descriptor_byte_length=8,
                descriptor_words_le_u16=(0, 4, 4096, 3),
            ),
        ),
        layout=SimpleNamespace(
            spans=(
                SimpleNamespace(kind="preserved", start=0, end=4),
                SimpleNamespace(kind="preserved", start=28, end=40),
            )
        ),
    )

    assert _array_theoretical_payload_span_fit_metrics(decoded) == {
        "member_rows": 1,
        "byte_count": 12,
        "non_tiny_member_rows": 1,
        "non_tiny_byte_count": 12,
        "exact_preserved_span_rows": 1,
        "later_preserved_span_fit_rows": 0,
        "no_preserved_span_fit_rows": 0,
        "immediate_window_string_span_overlap_rows": 0,
        "immediate_window_string_span_overlap_count": 0,
        "immediate_window_string_span_role_counts": {},
        "immediate_window_string_span_relation_counts": {},
        "later_fit_with_intervening_string_or_declaration_rows": 0,
        "later_fit_gap_string_span_relation_counts": {},
        "later_fit_gap_member_descriptor_relation_counts": {},
    }


def test_prefab_corpus_counts_array_exact_payload_owner_elements() -> None:
    decoded = SimpleNamespace(
        member_declarations=(
            SimpleNamespace(
                is_array=True,
                array_count_hint=3,
                array_stride_hint=4,
                descriptor_offset=20,
                descriptor_byte_length=8,
                descriptor_words_le_u16=(0, 4, 4096, 3),
            ),
            SimpleNamespace(
                is_array=True,
                array_count_hint=2,
                array_stride_hint=4,
                descriptor_offset=80,
                descriptor_byte_length=8,
                descriptor_words_le_u16=(0, 4, 4096, 2),
            ),
        ),
        layout=SimpleNamespace(
            spans=(
                SimpleNamespace(kind="preserved", start=28, end=40),
                SimpleNamespace(kind="preserved", start=88, end=100),
            )
        ),
    )

    assert _array_exact_payload_owner_counts(decoded) == {"member_rows": 1, "element_rows": 3}


def test_prefab_corpus_counts_array_theoretical_payload_blocked_by_intervening_string() -> None:
    decoded = SimpleNamespace(
        member_declarations=(
            SimpleNamespace(
                is_array=True,
                array_count_hint=3,
                array_stride_hint=4,
                descriptor_offset=20,
                descriptor_byte_length=8,
                descriptor_words_le_u16=(0, 4, 4096, 3),
            ),
        ),
        layout=SimpleNamespace(
            spans=(
                SimpleNamespace(kind="preserved", start=0, end=4),
                SimpleNamespace(kind="string_field", start=30, end=34),
                SimpleNamespace(kind="preserved", start=48, end=60),
            )
        ),
    )

    assert _array_theoretical_payload_span_fit_metrics(decoded) == {
        "member_rows": 1,
        "byte_count": 12,
        "non_tiny_member_rows": 1,
        "non_tiny_byte_count": 12,
        "exact_preserved_span_rows": 0,
        "later_preserved_span_fit_rows": 1,
        "no_preserved_span_fit_rows": 0,
        "immediate_window_string_span_overlap_rows": 1,
        "immediate_window_string_span_overlap_count": 1,
        "immediate_window_string_span_role_counts": {"other_string": 1},
        "immediate_window_string_span_relation_counts": {"other_string": 1},
        "later_fit_with_intervening_string_or_declaration_rows": 1,
        "later_fit_gap_string_span_relation_counts": {"other_string": 1},
        "later_fit_gap_member_descriptor_relation_counts": {},
    }


def test_prefab_corpus_classifies_payload_overlap_later_declaration_strings() -> None:
    decoded = SimpleNamespace(
        member_declarations=(
            SimpleNamespace(
                member_index=0,
                name_field_index=1,
                type_field_index=2,
                is_array=True,
                is_transform=False,
                array_count_hint=3,
                array_stride_hint=4,
                descriptor_offset=20,
                descriptor_byte_length=8,
                descriptor_words_le_u16=(0, 4, 4096, 3),
            ),
            SimpleNamespace(
                member_index=1,
                name_field_index=10,
                type_field_index=11,
                is_array=False,
                is_transform=False,
                descriptor_offset=40,
                descriptor_byte_length=8,
            ),
        ),
        layout=SimpleNamespace(
            spans=(
                SimpleNamespace(kind="string_field", start=30, end=34, field_index=10),
                SimpleNamespace(kind="string_field", start=34, end=38, field_index=11),
                SimpleNamespace(kind="preserved", start=50, end=62),
            )
        ),
        references=(),
    )

    metrics = _array_theoretical_payload_span_fit_metrics(decoded)

    assert metrics["immediate_window_string_span_role_counts"] == {"member_name": 1, "member_type": 1}
    assert metrics["immediate_window_string_span_relation_counts"] == {
        "later_member_name": 1,
        "later_member_type": 1,
    }
    assert metrics["later_fit_gap_string_span_relation_counts"] == {
        "later_member_name": 1,
        "later_member_type": 1,
    }
    assert metrics["later_fit_gap_member_descriptor_relation_counts"] == {"later_member_descriptor": 1}


def test_prefab_corpus_reports_descriptor_tail_bytes(tmp_path: Path) -> None:
    (tmp_path / "array_tail.prefab").write_bytes(_prefab_array_descriptor_tail_payload())

    report = build_prefab_json_import_corpus_report([tmp_path])
    row = report["rows"][0]

    assert row["array_member_count"] == 1
    assert row["array_members_with_descriptor_tail_bytes"] == 1
    assert row["array_descriptor_tail_bytes"] == 4
    assert row["descriptor_tail_member_kind_counts"] == {"array": 1}
    assert row["descriptor_tail_byte_kind_counts"] == {"array": 4}
    assert row["descriptor_tail_member_detail_counts"] == {"array|_items|vector<uint32>|0,4,4096,3|4": 1}
    assert row["member_descriptor_preserved_bytes"] == 12
    assert row["member_descriptor_header_preserved_bytes"] == 8
    assert row["member_descriptor_tail_preserved_bytes"] == 4
    assert row["preserved_unknown_bytes_excluding_member_descriptors"] == 4
    assert row["preserved_unknown_bytes_excluding_member_descriptor_headers"] == 8
    assert row["preserved_unknown_bytes_without_block_semantics"] == 8
    assert row["preserved_span_with_member_descriptor_count"] == 1
    assert row["preserved_span_with_member_descriptor_header_count"] == 1
    assert row["preserved_span_with_member_descriptor_tail_count"] == 1
    assert row["decoded_array_payload_element_rows"] == 0
    assert row["array_members_without_payload_elements"] == 1
    assert report["summary"]["member_descriptor_preserved_bytes"] == 12
    assert report["summary"]["member_descriptor_header_preserved_bytes"] == 8
    assert report["summary"]["member_descriptor_tail_preserved_bytes"] == 4
    assert report["summary"]["descriptor_tail_member_kind_counts"] == {"array": 1}
    assert report["summary"]["descriptor_tail_byte_kind_counts"] == {"array": 4}
    assert report["summary"]["descriptor_tail_member_detail_counts"] == {
        "array|_items|vector<uint32>|0,4,4096,3|4": 1
    }
    assert report["summary"]["preserved_unknown_bytes_excluding_member_descriptors"] == 4
    assert report["summary"]["preserved_unknown_bytes_excluding_member_descriptor_headers"] == 8
    assert report["summary"]["preserved_unknown_bytes_without_block_semantics"] == 8
    assert report["summary"]["preserved_spans_with_member_descriptors"] == 1
    assert report["summary"]["preserved_spans_with_member_descriptor_headers"] == 1
    assert report["summary"]["preserved_spans_with_member_descriptor_tails"] == 1
    assert report["summary"]["array_members_with_descriptor_tail_bytes"] == 1
    assert report["summary"]["array_descriptor_tail_bytes"] == 4
    assert report["gate"]["array_payload_layout_proven"] is False
    assert report["gate"]["length_changing_import_ready"] is False


def test_prefab_corpus_reports_reference_tail_record_shapes(tmp_path: Path) -> None:
    (tmp_path / "reference_tail.prefab").write_bytes(_prefab_reference_descriptor_tail_payload())

    report = build_prefab_json_import_corpus_report([tmp_path])
    row = report["rows"][0]
    expected = {"exact|4136|40|2|80": 1}

    assert row["reference_member_count"] == 1
    assert row["reference_members_with_descriptor_tail_bytes"] == 1
    assert row["reference_descriptor_tail_bytes"] == 80
    assert row["descriptor_tail_member_kind_counts"] == {"reference": 1}
    assert row["descriptor_tail_byte_kind_counts"] == {"reference": 80}
    assert row["descriptor_tail_member_detail_counts"] == {
        "reference|_childSceneObjects|ReflectObjectPtr|7,0,4136,1|80": 1
    }
    assert row["reference_descriptor_tail_record_shape_counts"] == expected
    assert row["reference_descriptor_tail_offset_candidate_mod_counts"] == {
        "4136|40|string_value|12": 1
    }
    assert row["reference_descriptor_tail_record_profile_counts"] == {
        "exact_tail_members": 1,
        "record_count_total": 2,
        "unique_record_count_total": 2,
        "duplicate_record_count_total": 0,
        "offset_candidate_record_count_total": 1,
        "offset_candidate_free_record_count_total": 1,
        "offset_candidate_multi_kind_record_count_total": 0,
        "max_offset_candidates_per_record": 1,
    }
    assert row["reference_descriptor_tail_numeric_profile_counts"] == {
        "exact_tail_members": 1,
        "record_count_total": 2,
        "u32_columns_total": 10,
        "finite_float_columns": 10,
        "worldish_float_columns": 10,
        "unitish_float_columns": 10,
        "zero_heavy_u32_columns": 9,
        "one_float_heavy_columns": 0,
        "tiny_or_zero_heavy_float_columns": 10,
        "huge_float_columns": 0,
    }
    expected_column_profile = {
        "exact_tail_members": 1,
        "record_count_total": 2,
        "u32_columns_total": 10,
        "constant_u32_columns": 9,
        "variable_u32_columns": 1,
        "all_zero_u32_columns": 9,
        "mostly_zero_u32_columns": 10,
        "offset_candidate_u32_columns": 1,
        "offset_candidate_free_u32_columns": 9,
        "unique_u32_value_total": 11,
        "max_unique_u32_values_per_column": 2,
        "unaligned_offset_candidate_rows": 0,
    }
    assert row["reference_descriptor_tail_column_profile_counts"] == expected_column_profile
    assert report["summary"]["reference_descriptor_tail_record_shape_counts"] == expected
    assert report["summary"]["reference_descriptor_tail_offset_candidate_mod_counts"] == {
        "4136|40|string_value|12": 1
    }
    assert report["summary"]["reference_descriptor_tail_record_profile_counts"] == {
        "exact_tail_members": 1,
        "record_count_total": 2,
        "unique_record_count_total": 2,
        "duplicate_record_count_total": 0,
        "offset_candidate_record_count_total": 1,
        "offset_candidate_free_record_count_total": 1,
        "offset_candidate_multi_kind_record_count_total": 0,
        "max_offset_candidates_per_record": 1,
    }
    assert report["summary"]["reference_descriptor_tail_numeric_profile_counts"] == {
        "exact_tail_members": 1,
        "record_count_total": 2,
        "u32_columns_total": 10,
        "finite_float_columns": 10,
        "worldish_float_columns": 10,
        "unitish_float_columns": 10,
        "zero_heavy_u32_columns": 9,
        "one_float_heavy_columns": 0,
        "tiny_or_zero_heavy_float_columns": 10,
        "huge_float_columns": 0,
    }
    assert report["summary"]["reference_descriptor_tail_column_profile_counts"] == expected_column_profile
    assert report["gate"]["reference_descriptor_edit_semantics_proven"] is False
    assert report["gate"]["length_changing_import_ready"] is False
    assert (
        "reference descriptor tail records are preserved but lack semantic column ownership"
        in report["gate"]["length_changing_blockers"]
    )


def test_prefab_corpus_report_probes_transform_word3_direct_mutation(tmp_path: Path) -> None:
    (tmp_path / "transform.prefab").write_bytes(_prefab_transform_word3_payload())

    report = build_prefab_json_import_corpus_report([tmp_path])
    row = report["rows"][0]
    probe = row["report_only_transform_word3_mutation_probe"]

    assert row["transform_member_count"] == 1
    assert row["decoded_transform_payload_value_rows"] == 0
    assert row["transform_members_without_payload_values"] == 1
    assert row["transform_members_with_descriptor_tail_bytes"] == 0
    assert row["transform_descriptor_tail_bytes"] == 0
    assert row["transform_theoretical_payload_shape_counts"] == {"_transform|Transform|40": 1}
    assert row["transform_theoretical_payload_member_rows"] == 1
    assert row["transform_theoretical_payload_byte_count"] == 40
    assert row["transform_theoretical_payload_exact_preserved_span_rows"] == 0
    assert row["transform_theoretical_payload_later_preserved_span_fit_rows"] == 0
    assert row["transform_theoretical_payload_no_preserved_span_fit_rows"] == 1
    assert row["transform_theoretical_payload_immediate_window_string_span_overlap_rows"] == 1
    assert row["transform_theoretical_payload_immediate_window_string_span_overlap_count"] == 1
    assert row["transform_theoretical_payload_immediate_window_string_span_role_counts"] == {"resource_reference": 1}
    assert row["transform_theoretical_payload_immediate_window_string_span_relation_counts"] == {"resource_reference": 1}
    assert row["transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows"] == 0
    assert row["transform_theoretical_payload_later_fit_gap_string_span_relation_counts"] == {}
    assert row["transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts"] == {}
    assert probe["status"] == "passed"
    assert probe["member_name"] == "_transform"
    assert probe["member_type"] == "Transform"
    assert probe["old_word3"] == 2
    assert probe["new_word3"] == 3
    assert probe["changed_only_expected_bytes"] is True
    assert probe["layout_fully_accounted_after_edit"] is True
    assert probe["no_edit_rebuild_after_edit"] is True
    assert probe["json_no_edit_roundtrip_after_edit"] is True
    assert probe["json_layout_rebuild_after_edit"] is True
    assert probe["decoded_word3_changed"] is True
    assert probe["member_identity_preserved"] is True
    assert probe["semantics_proven"] is False
    assert report["summary"]["report_only_transform_word3_mutation_probe_passed"] == 1
    assert report["summary"]["report_only_transform_word3_mutation_probe_skipped"] == 0
    assert report["summary"]["report_only_transform_word3_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_transform_word3_mutation_probe_changed_only_expected_passed"] == 1
    assert report["summary"]["report_only_transform_word3_mutation_probe_layout_fully_accounted_passed"] == 1
    assert report["summary"]["report_only_transform_word3_mutation_probe_no_edit_rebuild_passed"] == 1
    assert report["summary"]["report_only_transform_word3_mutation_probe_json_no_edit_roundtrip_passed"] == 1
    assert report["summary"]["report_only_transform_word3_mutation_probe_json_layout_rebuild_passed"] == 1
    assert report["summary"]["report_only_transform_word3_mutation_probe_decoded_word3_changed"] == 1
    assert report["summary"]["report_only_transform_word3_mutation_probe_member_identity_preserved"] == 1
    assert report["summary"]["report_only_transform_word3_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_transform_word3_mutation_probe_status_semantics_proven_counts"] == {
        "passed|false": 1
    }
    assert report["summary"]["report_only_transform_word3_mutation_probe_member_counts"] == {"_transform": 1}
    assert report["summary"]["report_only_transform_word3_mutation_probe_type_counts"] == {"Transform": 1}
    assert report["summary"]["report_only_transform_word3_mutation_probe_skip_reasons"] == {}
    assert report["summary"]["report_only_transform_word3_mutation_probe_failure_reasons"] == {}
    assert report["gate"]["transform_value_semantics_proven"] is False
    assert report["summary"]["decoded_transform_payload_value_rows"] == 0
    assert report["summary"]["transform_members_without_payload_values"] == 1
    assert report["summary"]["transform_members_with_descriptor_tail_bytes"] == 0
    assert report["summary"]["transform_descriptor_tail_bytes"] == 0
    assert report["summary"]["transform_theoretical_payload_shape_counts"] == {"_transform|Transform|40": 1}
    assert report["summary"]["transform_theoretical_payload_member_rows"] == 1
    assert report["summary"]["transform_theoretical_payload_byte_count"] == 40
    assert report["summary"]["transform_theoretical_payload_exact_preserved_span_rows"] == 0
    assert report["summary"]["transform_theoretical_payload_later_preserved_span_fit_rows"] == 0
    assert report["summary"]["transform_theoretical_payload_no_preserved_span_fit_rows"] == 1
    assert report["summary"]["transform_theoretical_payload_immediate_window_string_span_overlap_rows"] == 1
    assert report["summary"]["transform_theoretical_payload_immediate_window_string_span_overlap_count"] == 1
    assert report["summary"]["transform_theoretical_payload_immediate_window_string_span_role_counts"] == {
        "resource_reference": 1
    }
    assert report["summary"]["transform_theoretical_payload_immediate_window_string_span_relation_counts"] == {
        "resource_reference": 1
    }
    assert report["summary"]["transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows"] == 0
    assert report["summary"]["transform_theoretical_payload_later_fit_gap_string_span_relation_counts"] == {}
    assert report["summary"]["transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts"] == {}
    assert report["gate"]["transform_payload_layout_proven"] is False
    assert report["gate"]["transform_value_mutation_proven"] is False
    assert report["gate"]["transform_value_editing_ready"] is False
    assert report["gate"]["length_changing_import_ready"] is False
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["transform_word3_mutation_probe_non_skipped_rows"] == 1
    assert detail_counts["transform_word3_semantic_missing_rows"] == 1
    assert detail_counts["transform_word3_preserved_not_semantic_rows"] == 1
    assert detail_counts["transform_payload_decoded_value_rows"] == 0
    assert detail_counts["transform_payload_missing_member_rows"] == 1
    assert detail_counts["transform_payload_immediate_string_overlap_rows"] == 1
    assert detail_counts["transform_payload_immediate_string_overlap_count"] == 1
    assert detail_counts["transform_payload_later_intervening_rows"] == 0
    assert (
        "transform theoretical payload ownership is blocked by immediate string-span overlap"
        in report["gate"]["length_changing_blockers"]
    )


def test_prefab_corpus_counts_transform_theoretical_payload_exact_span() -> None:
    decoded = SimpleNamespace(
        member_declarations=(
            SimpleNamespace(
                is_transform=True,
                descriptor_offset=20,
                descriptor_byte_length=8,
                descriptor_words_le_u16=(0, 40, 0, 0),
            ),
        ),
        layout=SimpleNamespace(
            spans=(
                SimpleNamespace(kind="preserved", start=0, end=4),
                SimpleNamespace(kind="preserved", start=28, end=68),
            )
        ),
    )

    assert _transform_theoretical_payload_span_fit_metrics(decoded) == {
        "member_rows": 1,
        "byte_count": 40,
        "exact_preserved_span_rows": 1,
        "later_preserved_span_fit_rows": 0,
        "no_preserved_span_fit_rows": 0,
        "immediate_window_string_span_overlap_rows": 0,
        "immediate_window_string_span_overlap_count": 0,
        "immediate_window_string_span_role_counts": {},
        "immediate_window_string_span_relation_counts": {},
        "later_fit_with_intervening_string_or_declaration_rows": 0,
        "later_fit_gap_string_span_relation_counts": {},
        "later_fit_gap_member_descriptor_relation_counts": {},
    }


def test_prefab_corpus_counts_transform_exact_payload_owner_values() -> None:
    decoded = SimpleNamespace(
        member_declarations=(
            SimpleNamespace(
                is_transform=True,
                descriptor_offset=20,
                descriptor_byte_length=8,
                descriptor_words_le_u16=(0, 40, 0, 0),
            ),
            SimpleNamespace(
                is_transform=True,
                descriptor_offset=100,
                descriptor_byte_length=8,
                descriptor_words_le_u16=(0, 40, 0, 0),
            ),
        ),
        layout=SimpleNamespace(
            spans=(
                SimpleNamespace(kind="preserved", start=28, end=68),
                SimpleNamespace(kind="preserved", start=108, end=160),
            )
        ),
    )

    assert _transform_exact_payload_owner_counts(decoded) == {"member_rows": 1, "value_rows": 1}


def test_prefab_corpus_counts_transform_theoretical_payload_blocked_by_intervening_string() -> None:
    decoded = SimpleNamespace(
        member_declarations=(
            SimpleNamespace(
                is_transform=True,
                descriptor_offset=20,
                descriptor_byte_length=8,
                descriptor_words_le_u16=(0, 40, 0, 0),
            ),
        ),
        layout=SimpleNamespace(
            spans=(
                SimpleNamespace(kind="preserved", start=0, end=4),
                SimpleNamespace(kind="string_field", start=32, end=36),
                SimpleNamespace(kind="preserved", start=80, end=120),
            )
        ),
    )

    assert _transform_theoretical_payload_span_fit_metrics(decoded) == {
        "member_rows": 1,
        "byte_count": 40,
        "exact_preserved_span_rows": 0,
        "later_preserved_span_fit_rows": 1,
        "no_preserved_span_fit_rows": 0,
        "immediate_window_string_span_overlap_rows": 1,
        "immediate_window_string_span_overlap_count": 1,
        "immediate_window_string_span_role_counts": {"other_string": 1},
        "immediate_window_string_span_relation_counts": {"other_string": 1},
        "later_fit_with_intervening_string_or_declaration_rows": 1,
        "later_fit_gap_string_span_relation_counts": {"other_string": 1},
        "later_fit_gap_member_descriptor_relation_counts": {},
    }


def test_prefab_corpus_report_probes_reference_word3_direct_mutation(tmp_path: Path) -> None:
    (tmp_path / "reference.prefab").write_bytes(_prefab_reference_word3_payload())

    report = build_prefab_json_import_corpus_report([tmp_path])
    row = report["rows"][0]
    probe = row["report_only_reference_word3_mutation_probe"]

    assert row["reference_member_count"] == 1
    assert row["reference_members_without_descriptor_semantics"] == 1
    assert row["reference_members_with_descriptor_tail_bytes"] == 0
    assert row["reference_descriptor_tail_bytes"] == 0
    assert probe["status"] == "passed"
    assert probe["member_name"] == "_targetRef"
    assert probe["member_type"] == "ReflectObjectPtr"
    assert probe["old_word3"] == 2
    assert probe["new_word3"] == 3
    assert probe["changed_only_expected_bytes"] is True
    assert probe["layout_fully_accounted_after_edit"] is True
    assert probe["no_edit_rebuild_after_edit"] is True
    assert probe["json_no_edit_roundtrip_after_edit"] is True
    assert probe["json_layout_rebuild_after_edit"] is True
    assert probe["decoded_word3_changed"] is True
    assert probe["member_identity_preserved"] is True
    assert probe["semantics_proven"] is False
    assert report["summary"]["report_only_reference_word3_mutation_probe_passed"] == 1
    assert report["summary"]["report_only_reference_word3_mutation_probe_skipped"] == 0
    assert report["summary"]["report_only_reference_word3_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_reference_word3_mutation_probe_changed_only_expected_passed"] == 1
    assert report["summary"]["report_only_reference_word3_mutation_probe_layout_fully_accounted_passed"] == 1
    assert report["summary"]["report_only_reference_word3_mutation_probe_no_edit_rebuild_passed"] == 1
    assert report["summary"]["report_only_reference_word3_mutation_probe_json_no_edit_roundtrip_passed"] == 1
    assert report["summary"]["report_only_reference_word3_mutation_probe_json_layout_rebuild_passed"] == 1
    assert report["summary"]["report_only_reference_word3_mutation_probe_decoded_word3_changed"] == 1
    assert report["summary"]["report_only_reference_word3_mutation_probe_member_identity_preserved"] == 1
    assert report["summary"]["report_only_reference_word3_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_reference_word3_mutation_probe_status_semantics_proven_counts"] == {
        "passed|false": 1
    }
    assert report["summary"]["report_only_reference_word3_mutation_probe_member_counts"] == {"_targetRef": 1}
    assert report["summary"]["report_only_reference_word3_mutation_probe_type_counts"] == {"ReflectObjectPtr": 1}
    assert report["summary"]["report_only_reference_word3_mutation_probe_skip_reasons"] == {}
    assert report["summary"]["report_only_reference_word3_mutation_probe_failure_reasons"] == {}
    assert report["summary"]["reference_members_without_descriptor_semantics"] == 1
    assert report["summary"]["reference_members_with_descriptor_tail_bytes"] == 0
    assert report["summary"]["reference_descriptor_tail_bytes"] == 0
    assert report["gate"]["reference_descriptor_edit_semantics_proven"] is False
    assert report["gate"]["unknown_reference_preservation_ready"] is False
    assert report["gate"]["length_changing_import_ready"] is False
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["reference_word3_mutation_probe_non_skipped_rows"] == 1
    assert detail_counts["reference_word3_semantic_missing_rows"] == 1
    assert detail_counts["reference_word3_preserved_not_semantic_rows"] == 1
    assert (
        "reference word3 direct mutation preserves bytes but proves no semantics"
        in report["gate"]["length_changing_blockers"]
    )


def test_prefab_corpus_report_probes_preserved_unknown_byte_direct_mutation(tmp_path: Path) -> None:
    (tmp_path / "unknown.prefab").write_bytes(_prefab_preserved_unknown_payload())

    report = build_prefab_json_import_corpus_report([tmp_path])
    row = report["rows"][0]
    probe = row["report_only_preserved_unknown_byte_mutation_probe"]

    assert row["prefab_layout"]["preserved_span_count"] == 2
    assert row["preserved_unknown_bytes_without_block_semantics"] == 7
    assert probe["status"] == "passed"
    assert probe["span_start"] > 4
    assert probe["span_end"] == probe["span_start"] + 3
    assert probe["mutation_offset"] == probe["span_start"]
    assert probe["old_byte"] == 0x11
    assert probe["new_byte"] == 0xEE
    assert probe["changed_only_expected_bytes"] is True
    assert probe["layout_fully_accounted_after_edit"] is True
    assert probe["no_edit_rebuild_after_edit"] is True
    assert probe["json_no_edit_roundtrip_after_edit"] is True
    assert probe["json_layout_rebuild_after_edit"] is True
    assert probe["decoded_byte_changed"] is True
    assert probe["span_identity_preserved"] is True
    assert probe["semantics_proven"] is False
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_passed"] == 1
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_skipped"] == 0
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_changed_only_expected_passed"] == 1
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_layout_fully_accounted_passed"] == 1
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_no_edit_rebuild_passed"] == 1
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_json_no_edit_roundtrip_passed"] == 1
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_json_layout_rebuild_passed"] == 1
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_decoded_byte_changed"] == 1
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_span_identity_preserved"] == 1
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_status_semantics_proven_counts"] == {
        "passed|false": 1
    }
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_skip_reasons"] == {}
    assert report["summary"]["report_only_preserved_unknown_byte_mutation_probe_failure_reasons"] == {}
    assert report["summary"]["preserved_unknown_bytes_without_block_semantics"] == 7
    assert report["gate"]["unknown_block_edit_semantics_proven"] is False
    assert report["gate"]["unknown_reference_preservation_ready"] is False
    assert report["gate"]["length_changing_import_ready"] is False
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["preserved_unknown_byte_mutation_probe_non_skipped_rows"] == 1
    assert detail_counts["preserved_unknown_byte_semantic_missing_rows"] == 1
    assert detail_counts["preserved_unknown_byte_preserved_not_semantic_rows"] == 1
    assert (
        "preserved unknown-byte direct mutation preserves bytes but proves no semantics"
        in report["gate"]["length_changing_blockers"]
    )


def test_prefab_corpus_report_probes_descriptor_word3_direct_mutation(tmp_path: Path) -> None:
    (tmp_path / "descriptor.prefab").write_bytes(_prefab_descriptor_word3_payload())

    report = build_prefab_json_import_corpus_report([tmp_path])
    row = report["rows"][0]
    probe = row["report_only_descriptor_word3_mutation_probe"]

    assert row["member_declaration_count"] == 1
    assert probe["status"] == "passed"
    assert probe["member_name"] == "_count"
    assert probe["member_type"] == "uint32"
    assert probe["descriptor_kind"] == "scalar"
    assert probe["old_word3"] == 2
    assert probe["new_word3"] == 3
    assert probe["changed_only_expected_bytes"] is True
    assert probe["layout_fully_accounted_after_edit"] is True
    assert probe["no_edit_rebuild_after_edit"] is True
    assert probe["json_no_edit_roundtrip_after_edit"] is True
    assert probe["json_layout_rebuild_after_edit"] is True
    assert probe["decoded_word3_changed"] is True
    assert probe["member_identity_preserved"] is True
    assert probe["semantics_proven"] is False
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_passed"] == 1
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_skipped"] == 0
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_failed"] == 0
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_changed_only_expected_passed"] == 1
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_layout_fully_accounted_passed"] == 1
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_no_edit_rebuild_passed"] == 1
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_json_no_edit_roundtrip_passed"] == 1
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_json_layout_rebuild_passed"] == 1
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_decoded_word3_changed"] == 1
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_member_identity_preserved"] == 1
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_semantics_proven"] == 0
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_status_semantics_proven_counts"] == {
        "passed|false": 1
    }
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_kind_counts"] == {"scalar": 1}
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_member_counts"] == {"_count": 1}
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_type_counts"] == {"uint32": 1}
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_skip_reasons"] == {}
    assert report["summary"]["report_only_descriptor_word3_mutation_probe_failure_reasons"] == {}
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["descriptor_word3_mutation_probe_non_skipped_rows"] == 1
    assert detail_counts["descriptor_word3_semantic_missing_rows"] == 1
    assert report["gate"]["descriptor_word3_semantics_proven"] is False
    assert report["gate"]["descriptor_count_mutation_proven"] is False
    assert report["gate"]["descriptor_value_editing_ready"] is False
    assert report["gate"]["length_changing_import_ready"] is False
    assert (
        "descriptor word3 direct mutation preserves bytes but proves no count semantics"
        in report["gate"]["length_changing_blockers"]
    )


def test_prefab_archive_entry_report_reads_prefab_entries(tmp_path: Path) -> None:
    prefab_payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    entries = [
        _entry("character/prefab/test.prefab", tmp_path, prefab_payload),
        _entry("character/model/test.pac", tmp_path, b"pac"),
    ]

    def read_entry_data(entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return (prefab_payload if entry.extension == ".prefab" else b"pac"), False, ""

    report = build_prefab_json_import_archive_entry_report(
        entries,
        read_entry_data=read_entry_data,
        source_label="fixture_archive",
    )

    assert discover_prefab_archive_entries(entries) == [entries[0]]
    assert report["source_type"] == "archive_entries"
    assert report["source_paths"] == ["fixture_archive"]
    assert report["summary"]["files_discovered"] == 1
    assert report["summary"]["files_scanned"] == 1
    assert report["summary"]["no_edit_roundtrip_passed"] == 1
    assert report["summary"]["layout_rebuild_passed"] == 1
    assert report["summary"]["json_layout_rebuild_passed"] == 1
    assert report["gate"]["same_length_import_ready"] is True
    assert report["gate"]["same_length_resource_edit_probe_ready"] is True
    assert report["gate"]["same_length_placement_edit_probe_ready"] is False
    assert report["gate"]["experimental_length_change_rebuild_probe_ready"] is True


def test_prefab_corpus_report_counts_offset_candidates(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00\x00"
    path = "character/model/test_a.pac"
    target_end = len(prefix) + 4 + len(_lp(path))
    payload = prefix + target_end.to_bytes(4, "little") + _lp(path)
    entry = _entry("character/prefab/offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)

    assert report["rows"][0]["offset_candidate_count"] == 1
    assert report["rows"][0]["offset_candidate_overlap_count"] == 0
    assert report["rows"][0]["offset_candidate_aligned_count"] == 0
    assert report["rows"][0]["offset_candidate_unaligned_count"] == 1
    assert report["rows"][0]["offset_candidate_overlap_group_count"] == 0
    assert report["rows"][0]["offset_candidate_overlapping_window_count"] == 0
    assert report["rows"][0]["offset_candidate_isolated_count"] == 1
    assert report["rows"][0]["offset_candidate_aligned_isolated_count"] == 0
    assert report["rows"][0]["offset_candidate_unaligned_isolated_count"] == 1
    assert report["rows"][0]["offset_candidate_unaligned_or_overlapping_count"] == 1
    assert report["rows"][0]["offset_candidate_target_string_end_count"] == 1
    assert report["rows"][0]["offset_candidate_in_member_descriptor_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_count"] == 1
    assert report["rows"][0]["offset_candidate_in_array_descriptor_count"] == 0
    assert report["rows"][0]["offset_candidate_in_transform_descriptor_count"] == 0
    assert report["rows"][0]["offset_candidate_in_reference_descriptor_count"] == 0
    assert report["rows"][0]["offset_candidate_in_scalar_or_bool_descriptor_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_aligned_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_unaligned_count"] == 1
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_overlap_group_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_overlapping_window_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_isolated_count"] == 1
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_aligned_isolated_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_unaligned_isolated_count"] == 1
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count"] == 1
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_target_string_length_prefix_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_target_string_value_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_target_string_end_count"] == 1
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 1,
        "2": 0,
        "3": 0,
    }
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_target_value_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 1,
    }
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_target_role_counts"] == {
        "resource_reference_count": 1,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_string_value_target_role_counts"] == {
        "resource_reference_count": 0,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_resource_reference_count"] == 1
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_resource_reference_aligned_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_resource_reference_unaligned_count"] == 1
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_resource_reference_isolated_count"] == 1
    assert (
        report["rows"][0]["offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count"]
        == 1
    )
    assert (
        report["rows"][0][
            "offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count"
        ]
        == 0
    )
    assert (
        report["rows"][0]["offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count"]
        == 0
    )
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count"] == 1
    assert report["rows"][0]["offset_candidate_in_preserved_span_count"] == 1
    assert report["rows"][0]["offset_candidate_outside_preserved_span_count"] == 0
    assert report["rows"][0]["offset_candidate_preserved_span_exact_4_count"] == 0
    assert report["rows"][0]["offset_candidate_preserved_span_le_8_count"] == 0
    assert report["rows"][0]["offset_candidate_at_preserved_span_start_count"] == 0
    assert report["rows"][0]["offset_candidate_at_preserved_span_end_count"] == 1
    assert report["rows"][0]["offset_candidate_in_preserved_span_middle_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_preserved_span_exact_4_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_preserved_span_le_8_count"] == 0
    assert report["rows"][0]["offset_candidate_outside_member_descriptor_preserved_span_middle_count"] == 0
    assert report["rows"][0]["resource_resize_impact_offset_candidate_count"] == 1
    assert report["rows"][0]["resource_resize_impact_target_role_kind_counts"] == {
        "resource_reference|string_end": 1,
    }
    assert report["rows"][0]["resource_resize_impact_owner_kind_target_counts"] == {
        "outside_member_descriptor|resource_reference|string_end": 1,
    }
    assert report["rows"][0]["resource_resize_impact_resource_reference_target_profile_distance_counts"] == {
        "unaligned|string_end|model|.pac|forward_le_64": 1,
    }
    assert report["rows"][0]["resource_resize_impact_resource_reference_target_profile_span_position_counts"] == {
        "unaligned|string_end|model|.pac|at_end": 1,
    }
    assert report["rows"][0]["resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts"] == {
        "unaligned|string_end|model|.pac|nul_rich": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_offset_candidate_count"] == 1
    assert report["rows"][0]["resource_resize_impact_unique_target_role_kind_counts"] == {
        "resource_reference|string_end": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_owner_kind_target_counts"] == {
        "outside_member_descriptor|resource_reference|string_end": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_candidate_profile_counts"] == {
        "outside_member_descriptor|resource_reference|string_end|unaligned|at_end|nul_rich|forward_le_64": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_overlap_profile_counts"] == {
        "non_overlapping|outside_member_descriptor|resource_reference|string_end|unaligned|at_end|nul_rich|forward_le_64": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_overlap_group_profile_counts"] == {}
    assert report["rows"][0]["resource_resize_impact_unique_overlap_group_target_identity_counts"] == {}
    assert report["rows"][0]["resource_resize_impact_unique_same_target_overlap_collapse_counts"] == {
        "impacted_overlap_group_count": 0,
        "impacted_overlap_candidate_count": 0,
        "same_target_duplicate_group_count": 0,
        "same_target_duplicate_candidate_count": 0,
        "mixed_target_group_count": 0,
        "mixed_target_candidate_count": 0,
        "blocker_group_count_after_same_target_collapse": 0,
        "blocker_candidate_count_after_same_target_collapse": 0,
    }
    assert report["rows"][0]["resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts"] == {}
    assert report["rows"][0]["resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts"] == {}
    assert report["rows"][0]["resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary"] == {
        "candidate_count": 0,
        "unique_identity_count": 0,
        "repeated_identity_count": 0,
        "repeated_candidate_count": 0,
        "high_repeat_10_identity_count": 0,
        "high_repeat_10_candidate_count": 0,
        "max_identity_candidate_count": 0,
    }
    assert report["rows"][0]["resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts"] == {}
    assert report["rows"][0]["resource_resize_impact_unique_resource_reference_target_profile_distance_counts"] == {
        "unaligned|string_end|model|.pac|forward_le_64": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_overlap_counts"] == {
        "non_overlapping_count": 1,
        "overlapping_count": 0,
    }
    assert report["rows"][0]["resource_resize_impact_unique_resource_reference_overlap_counts"] == {
        "non_overlapping_count": 1,
        "overlapping_count": 0,
    }
    assert report["rows"][0]["placement_resize_impact_target_role_kind_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_owner_kind_target_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_resource_reference_target_profile_distance_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_resource_reference_target_profile_span_position_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_unique_offset_candidate_count"] == 0
    assert report["rows"][0]["placement_resize_impact_unique_target_role_kind_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_unique_owner_kind_target_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_unique_candidate_profile_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_unique_overlap_profile_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_unique_resource_reference_target_profile_distance_counts"] == {}
    assert report["rows"][0]["placement_resize_impact_unique_overlap_counts"] == {
        "non_overlapping_count": 0,
        "overlapping_count": 0,
    }
    assert report["rows"][0]["placement_resize_impact_unique_resource_reference_overlap_counts"] == {
        "non_overlapping_count": 0,
        "overlapping_count": 0,
    }
    assert report["rows"][0]["policy_resize_readiness"]["editable_row_count"] == 1
    assert report["rows"][0]["policy_resize_readiness"]["editable_rows_with_resize_impact"] == 1
    assert report["rows"][0]["policy_resize_readiness"]["affected_offset_candidate_rows"] == 1
    assert report["rows"][0]["length_change_tail_only_candidate_count"] == 0
    assert report["rows"][0]["length_change_offset_rebuild_row_count"] == 1
    assert report["rows"][0]["experimental_length_change_resource_rebuild_probe"]["status"] == "passed"
    assert report["rows"][0]["experimental_length_change_resource_rebuild_probe"]["offset_candidate_count_after_edit"] == 1
    assert report["rows"][0]["experimental_length_change_resource_rebuild_probe"]["offset_candidates_remapped_after_edit"] is True
    assert report["rows"][0]["experimental_length_change_resource_rebuild_probe"]["resized_rebuild_changed_only_expected_bytes"] is True
    assert report["summary"]["offset_candidate_rows"] == 1
    assert report["summary"]["offset_candidate_overlap_rows"] == 0
    assert report["summary"]["offset_candidate_aligned_rows"] == 0
    assert report["summary"]["offset_candidate_unaligned_rows"] == 1
    assert report["summary"]["offset_candidate_overlap_group_rows"] == 0
    assert report["summary"]["offset_candidate_overlapping_window_rows"] == 0
    assert report["summary"]["offset_candidate_isolated_rows"] == 1
    assert report["summary"]["offset_candidate_aligned_isolated_rows"] == 0
    assert report["summary"]["offset_candidate_unaligned_isolated_rows"] == 1
    assert report["summary"]["offset_candidate_unaligned_or_overlapping_rows"] == 1
    assert report["summary"]["offset_candidate_target_string_end_rows"] == 1
    assert report["summary"]["offset_candidate_in_member_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_rows"] == 1
    assert report["summary"]["offset_candidate_in_array_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_in_transform_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_in_reference_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_in_scalar_or_bool_descriptor_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_unaligned_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_isolated_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_unaligned_or_overlapping_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_target_string_end_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 1,
        "2": 0,
        "3": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_target_value_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 1,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_target_role_counts"] == {
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
        "resource_reference_count": 1,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_unaligned_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_target_string_end_rows"] == 1
    assert report["summary"]["offset_candidate_in_preserved_span_rows"] == 1
    assert report["summary"]["offset_candidate_outside_preserved_span_rows"] == 0
    assert report["summary"]["offset_candidate_at_preserved_span_end_rows"] == 1
    assert report["summary"]["preserved_spans_with_offset_candidates"] == 1
    assert report["summary"]["preserved_spans_without_offset_candidates"] == 0
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["offset_candidate_rows"] == 1
    assert detail_counts["preserved_spans_with_offset_candidates"] == 1
    assert report["summary"]["files_with_offset_candidates"] == 1
    assert report["summary"]["files_with_offset_candidate_overlaps"] == 0
    assert report["summary"]["resource_resize_impact_offset_candidate_rows"] == 1
    assert report["summary"]["resource_resize_impact_target_role_kind_counts"] == {
        "resource_reference|string_end": 1,
    }
    assert report["summary"]["resource_resize_impact_owner_kind_target_counts"] == {
        "outside_member_descriptor|resource_reference|string_end": 1,
    }
    assert report["summary"]["resource_resize_impact_resource_reference_target_profile_distance_counts"] == {
        "unaligned|string_end|model|.pac|forward_le_64": 1,
    }
    assert report["summary"]["resource_resize_impact_resource_reference_target_profile_span_position_counts"] == {
        "unaligned|string_end|model|.pac|at_end": 1,
    }
    assert report["summary"]["resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts"] == {
        "unaligned|string_end|model|.pac|nul_rich": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_offset_candidate_rows"] == 1
    assert report["summary"]["resource_resize_impact_unique_target_role_kind_counts"] == {
        "resource_reference|string_end": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_owner_kind_target_counts"] == {
        "outside_member_descriptor|resource_reference|string_end": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_candidate_profile_counts"] == {
        "outside_member_descriptor|resource_reference|string_end|unaligned|at_end|nul_rich|forward_le_64": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_overlap_profile_counts"] == {
        "non_overlapping|outside_member_descriptor|resource_reference|string_end|unaligned|at_end|nul_rich|forward_le_64": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_overlap_group_profile_counts"] == {}
    assert report["summary"]["resource_resize_impact_unique_overlap_group_target_identity_counts"] == {}
    assert report["summary"]["resource_resize_impact_unique_same_target_overlap_collapse_counts"] == {
        "impacted_overlap_group_count": 0,
        "impacted_overlap_candidate_count": 0,
        "same_target_duplicate_group_count": 0,
        "same_target_duplicate_candidate_count": 0,
        "mixed_target_group_count": 0,
        "mixed_target_candidate_count": 0,
        "blocker_group_count_after_same_target_collapse": 0,
        "blocker_candidate_count_after_same_target_collapse": 0,
    }
    assert report["summary"]["resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts"] == {}
    assert report["summary"]["resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts"] == {}
    assert report["summary"]["resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary"] == {
        "candidate_count": 0,
        "unique_identity_count": 0,
        "repeated_identity_count": 0,
        "repeated_candidate_count": 0,
        "high_repeat_10_identity_count": 0,
        "high_repeat_10_candidate_count": 0,
        "max_identity_candidate_count": 0,
    }
    assert report["summary"]["resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts"] == {}
    assert report["summary"]["resource_resize_impact_unique_resource_reference_target_profile_distance_counts"] == {
        "unaligned|string_end|model|.pac|forward_le_64": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_overlap_counts"] == {
        "non_overlapping_count": 1,
        "overlapping_count": 0,
    }
    assert report["summary"]["resource_resize_impact_unique_resource_reference_overlap_counts"] == {
        "non_overlapping_count": 1,
        "overlapping_count": 0,
    }
    assert report["summary"]["placement_resize_impact_target_role_kind_counts"] == {}
    assert report["summary"]["placement_resize_impact_owner_kind_target_counts"] == {}
    assert report["summary"]["placement_resize_impact_resource_reference_target_profile_distance_counts"] == {}
    assert report["summary"]["placement_resize_impact_resource_reference_target_profile_span_position_counts"] == {}
    assert report["summary"]["placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_offset_candidate_rows"] == 0
    assert report["summary"]["placement_resize_impact_unique_target_role_kind_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_owner_kind_target_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_candidate_profile_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_overlap_profile_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_resource_reference_target_profile_distance_counts"] == {}
    assert report["summary"]["placement_resize_impact_unique_overlap_counts"] == {
        "non_overlapping_count": 0,
        "overlapping_count": 0,
    }
    assert report["summary"]["placement_resize_impact_unique_resource_reference_overlap_counts"] == {
        "non_overlapping_count": 0,
        "overlapping_count": 0,
    }
    assert report["summary"]["length_change_tail_only_candidate_rows"] == 0
    assert report["summary"]["length_change_offset_rebuild_rows"] == 1
    assert report["summary"]["policy_resize_readiness_editable_rows"] == 1
    assert report["summary"]["policy_resize_readiness_impacted_rows"] == 1
    assert report["summary"]["policy_resize_readiness_offset_candidate_rows"] == 1
    assert report["summary"]["files_with_policy_resize_impacts"] == 1
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_offset_candidate_rows_after_edit"] == 1
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_offset_remap_passed"] == 1


def test_prefab_corpus_report_counts_unique_resize_impact_candidates(tmp_path: Path) -> None:
    path_a = "character/model/test_a.pac"
    path_b = "character/model/test_b.pac"
    prefix = b"\xff\xff\x04\x00" + _lp(path_a)
    target_end = len(prefix) + 4 + len(_lp(path_b))
    payload = prefix + target_end.to_bytes(4, "little") + _lp(path_b)
    entry = _entry("character/prefab/duplicate-impact-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    row = report["rows"][0]

    assert row["editable_reference_count"] == 2
    assert row["resource_resize_impact_offset_candidate_count"] == 2
    assert row["resource_resize_impact_unique_offset_candidate_count"] == 1
    assert row["resource_resize_impact_target_role_kind_counts"] == {
        "resource_reference|string_end": 2,
    }
    assert row["resource_resize_impact_unique_target_role_kind_counts"] == {
        "resource_reference|string_end": 1,
    }
    assert row["resource_resize_impact_unique_owner_kind_target_counts"] == {
        "outside_member_descriptor|resource_reference|string_end": 1,
    }
    assert row["resource_resize_impact_unique_candidate_profile_counts"] == {
        "outside_member_descriptor|resource_reference|string_end|unaligned|at_start|ascii_like|forward_le_64": 1,
    }
    assert row["resource_resize_impact_unique_resource_reference_target_profile_distance_counts"] == {
        "unaligned|string_end|model|.pac|forward_le_64": 1,
    }
    assert report["summary"]["resource_resize_impact_offset_candidate_rows"] == 2
    assert report["summary"]["resource_resize_impact_unique_offset_candidate_rows"] == 1
    assert report["summary"]["resource_resize_impact_unique_target_role_kind_counts"] == {
        "resource_reference|string_end": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_owner_kind_target_counts"] == {
        "outside_member_descriptor|resource_reference|string_end": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_candidate_profile_counts"] == {
        "outside_member_descriptor|resource_reference|string_end|unaligned|at_start|ascii_like|forward_le_64": 1,
    }


def test_prefab_corpus_report_counts_aligned_isolated_outside_descriptor_roles(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00"
    path = "character/model/test_a.pac"
    target_value = len(prefix) + 4
    payload = prefix + target_value.to_bytes(4, "little") + _lp(path)
    entry = _entry("character/prefab/aligned-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    row = report["rows"][0]

    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts"] == {
        "resource_reference|string_length_prefix": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts"] == {
        "aligned|string_length_prefix": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts"] == {
        "aligned|string_length_prefix|.pac": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts"] == {
        "aligned|string_length_prefix|model": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts"] == {
        "aligned|string_length_prefix|le_16": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts"] == {
        "aligned|string_length_prefix|at_end": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts"] == {
        "aligned|string_length_prefix|model|.pac|at_end": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts"] == {
        "aligned|string_length_prefix|model|.pac|forward_le_16": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts"] == {
        "le_16": 1,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_aligned_isolated_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts"] == {
        "resource_reference|string_length_prefix": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts"
    ] == {
        "aligned|string_length_prefix|.pac": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts"
    ] == {
        "aligned|string_length_prefix|model": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts"
    ] == {
        "aligned|string_length_prefix|le_16": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts"
    ] == {
        "aligned|string_length_prefix|at_end": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts"
    ] == {
        "aligned|string_length_prefix|model|.pac|at_end": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts"
    ] == {
        "aligned|string_length_prefix|model|.pac|forward_le_16": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts"
    ] == {
        "le_16": 1,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_rows"] == 0
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_rows"
    ] == 0
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_rows"
    ] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_rows"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_rows"] == 1
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_rows"
    ] == 0


def test_prefab_corpus_report_counts_descriptor_owned_offset_candidates(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00" + _lp("_customRef") + _lp("ReflectObjectPtr")
    path = "character/model/test_a.pac"
    target_end = len(prefix) + 8 + len(_lp(path))
    payload = prefix + target_end.to_bytes(4, "little") + b"\x00\x00\x03\x00" + _lp(path)
    entry = _entry("character/prefab/descriptor-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    row = report["rows"][0]

    word0 = target_end & 0xFFFF
    word1 = target_end >> 16
    expected_signature = {f"ReflectObjectPtr|{word0},{word1},0,3": 1}
    expected_signature_status = {f"ReflectObjectPtr|{word0},{word1},0,3|with_offset_candidate": 1}
    expected_signature_target = {f"ReflectObjectPtr|{word0},{word1},0,3|resource_reference|string_end": 1}
    expected_nonzero_target = {"resource_reference|string_end": 1}

    assert row["reference_member_count"] == 1
    assert row["reference_descriptor_signature_counts"] == expected_signature
    assert row["reference_descriptor_signature_offset_candidate_counts"] == expected_signature_status
    assert row["reference_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert row["reference_descriptor_signature_offset_candidate_target_counts"] == expected_signature_target
    assert row["reference_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert row["offset_candidate_count"] == 1
    assert row["offset_candidate_in_member_descriptor_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_count"] == 0
    assert row["offset_candidate_in_array_descriptor_count"] == 0
    assert row["offset_candidate_in_transform_descriptor_count"] == 0
    assert row["offset_candidate_in_reference_descriptor_count"] == 1
    assert row["offset_candidate_in_scalar_or_bool_descriptor_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_aligned_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_unaligned_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_target_string_end_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 0,
        "2": 0,
        "3": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_target_role_counts"] == {
        "resource_reference_count": 0,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_count"] == 0
    assert row["offset_candidate_in_preserved_span_count"] == 1
    assert row["offset_candidate_preserved_span_le_8_count"] == 1
    assert row["offset_candidate_at_preserved_span_start_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_preserved_span_le_8_count"] == 0
    assert report["summary"]["offset_candidate_in_member_descriptor_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_rows"] == 0
    assert report["summary"]["reference_member_rows"] == 1
    assert report["summary"]["reference_descriptor_signature_counts"] == expected_signature
    assert report["summary"]["reference_descriptor_signature_offset_candidate_counts"] == expected_signature_status
    assert report["summary"]["reference_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["reference_descriptor_signature_offset_candidate_target_counts"] == expected_signature_target
    assert report["summary"]["reference_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert report["summary"]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {
        "reference|resource_reference|string_end": 1
    }
    assert report["summary"]["offset_candidate_in_reference_descriptor_rows"] == 1


def test_prefab_corpus_report_counts_scalar_descriptor_offset_candidates(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00" + _lp("_customScalar") + _lp("uint32")
    path = "character/model/test_a.pac"
    target_end = len(prefix) + 8 + len(_lp(path))
    payload = prefix + target_end.to_bytes(4, "little") + b"\x00\x00\x02\x00" + _lp(path)
    entry = _entry("character/prefab/scalar-descriptor-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    row = report["rows"][0]

    word0 = target_end & 0xFFFF
    word1 = target_end >> 16
    expected_signature = {f"uint32|{word0},{word1},0,2": 1}
    expected_signature_status = {f"uint32|{word0},{word1},0,2|with_offset_candidate": 1}
    expected_signature_target = {f"uint32|{word0},{word1},0,2|resource_reference|string_end": 1}
    expected_nonzero_target = {"resource_reference|string_end": 1}

    assert row["scalar_or_bool_descriptor_signature_counts"] == expected_signature
    assert row["scalar_or_bool_descriptor_signature_offset_candidate_counts"] == expected_signature_status
    assert row["scalar_or_bool_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert row["scalar_or_bool_descriptor_signature_offset_candidate_target_counts"] == expected_signature_target
    assert row["scalar_or_bool_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert row["offset_candidate_in_scalar_or_bool_descriptor_count"] == 1
    assert report["summary"]["scalar_or_bool_descriptor_signature_counts"] == expected_signature
    assert report["summary"]["scalar_or_bool_descriptor_signature_offset_candidate_counts"] == expected_signature_status
    assert report["summary"]["scalar_or_bool_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["scalar_or_bool_descriptor_signature_offset_candidate_target_counts"] == expected_signature_target
    assert report["summary"]["scalar_or_bool_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert report["summary"]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {
        "scalar_or_bool|resource_reference|string_end": 1
    }
    assert report["summary"]["offset_candidate_in_scalar_or_bool_descriptor_rows"] == 1


def test_prefab_corpus_report_counts_string_descriptor_offset_candidates(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00" + _lp("_customName") + _lp("IndexedStringA")
    path = "character/model/test_a.pac"
    target_end = len(prefix) + 8 + len(_lp(path))
    payload = prefix + target_end.to_bytes(4, "little") + b"\x00\x00\x04\x00" + _lp(path)
    entry = _entry("character/prefab/string-descriptor-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    row = report["rows"][0]

    word0 = target_end & 0xFFFF
    word1 = target_end >> 16
    expected_signature = {f"IndexedStringA|{word0},{word1},0,4": 1}
    expected_signature_status = {f"IndexedStringA|{word0},{word1},0,4|with_offset_candidate": 1}
    expected_signature_target = {f"IndexedStringA|{word0},{word1},0,4|resource_reference|string_end": 1}
    expected_nonzero_target = {"resource_reference|string_end": 1}
    expected_owner_kind = {"string": 1}
    expected_owner_kind_target = {"string|resource_reference|string_end": 1}

    assert row["string_descriptor_signature_counts"] == expected_signature
    assert row["string_descriptor_signature_offset_candidate_counts"] == expected_signature_status
    assert row["string_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert row["string_descriptor_signature_offset_candidate_target_counts"] == expected_signature_target
    assert row["string_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert row["descriptor_owner_kind_offset_candidate_counts"] == expected_owner_kind
    assert row["descriptor_owner_kind_offset_candidate_target_counts"] == expected_owner_kind_target
    assert report["summary"]["string_descriptor_signature_counts"] == expected_signature
    assert report["summary"]["string_descriptor_signature_offset_candidate_counts"] == expected_signature_status
    assert report["summary"]["string_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["string_descriptor_signature_offset_candidate_target_counts"] == expected_signature_target
    assert report["summary"]["string_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert report["summary"]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {
        "string|resource_reference|string_end": 1
    }
    assert report["summary"]["descriptor_owner_kind_offset_candidate_counts"] == expected_owner_kind
    assert report["summary"]["descriptor_owner_kind_offset_candidate_target_counts"] == expected_owner_kind_target


def test_prefab_corpus_report_counts_generic_descriptor_offset_candidates(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00" + _lp("_customDescriptor") + _lp("CustomDescriptor")
    path = "character/model/test_a.pac"
    target_end = len(prefix) + 8 + len(_lp(path))
    payload = prefix + target_end.to_bytes(4, "little") + b"\x00\x00\x03\x00" + _lp(path)
    entry = _entry("character/prefab/generic-descriptor-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    row = report["rows"][0]

    word0 = target_end & 0xFFFF
    word1 = target_end >> 16
    expected_signature = {f"CustomDescriptor|{word0},{word1},0,3": 1}
    expected_signature_status = {f"CustomDescriptor|{word0},{word1},0,3|with_offset_candidate": 1}
    expected_signature_target = {f"CustomDescriptor|{word0},{word1},0,3|resource_reference|string_end": 1}
    expected_nonzero_target = {"resource_reference|string_end": 1}
    expected_owner_kind = {"descriptor": 1}
    expected_owner_kind_target = {"descriptor|resource_reference|string_end": 1}

    assert row["generic_descriptor_signature_counts"] == expected_signature
    assert row["generic_descriptor_signature_offset_candidate_counts"] == expected_signature_status
    assert row["generic_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert row["generic_descriptor_signature_offset_candidate_target_counts"] == expected_signature_target
    assert row["generic_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert row["descriptor_owner_kind_offset_candidate_counts"] == expected_owner_kind
    assert row["descriptor_owner_kind_offset_candidate_target_counts"] == expected_owner_kind_target
    assert report["summary"]["generic_descriptor_signature_counts"] == expected_signature
    assert report["summary"]["generic_descriptor_signature_offset_candidate_counts"] == expected_signature_status
    assert report["summary"]["generic_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["generic_descriptor_signature_offset_candidate_target_counts"] == expected_signature_target
    assert report["summary"]["generic_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert report["summary"]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {
        "generic|resource_reference|string_end": 1
    }
    assert report["summary"]["descriptor_owner_kind_offset_candidate_counts"] == expected_owner_kind
    assert report["summary"]["descriptor_owner_kind_offset_candidate_target_counts"] == expected_owner_kind_target


def test_prefab_corpus_report_counts_exact_preserved_span_offset_candidates(tmp_path: Path) -> None:
    path_a = "character/model/test_a.pac"
    path_b = "character/model/test_b.pac"
    prefix = b"\xff\xff\x04\x00" + _lp(path_a)
    target_end = len(prefix) + 4 + len(_lp(path_b))
    payload = prefix + target_end.to_bytes(4, "little") + _lp(path_b)
    entry = _entry("character/prefab/exact-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    row = report["rows"][0]

    assert row["offset_candidate_count"] == 1
    assert row["offset_candidate_in_preserved_span_count"] == 1
    assert row["offset_candidate_outside_preserved_span_count"] == 0
    assert row["offset_candidate_preserved_span_exact_4_count"] == 1
    assert row["offset_candidate_preserved_span_le_8_count"] == 1
    assert row["offset_candidate_at_preserved_span_start_count"] == 1
    assert row["offset_candidate_at_preserved_span_end_count"] == 1
    assert row["offset_candidate_in_preserved_span_middle_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_preserved_span_exact_4_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_preserved_span_le_8_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_count"] == 0
    assert report["summary"]["offset_candidate_preserved_span_exact_4_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_preserved_span_exact_4_rows"] == 1


def test_prefab_corpus_report_counts_outside_descriptor_middle_offset_candidates(tmp_path: Path) -> None:
    path = "character/model/test_a.pac"
    prefix = b"\xff\xff\x04\x00\x00\x00"
    target_value = len(prefix) + 6
    payload = prefix + target_value.to_bytes(4, "little") + b"\x00\x00" + _lp(path)
    entry = _entry("character/prefab/middle-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    row = report["rows"][0]

    assert row["offset_candidate_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts"] == {
        "resource_reference_count": 1,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts"] == {
        "resource_reference|string_length_prefix": 1,
    }
    assert row[
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts"
    ] == {
        "resource_reference|string_length_prefix|near_start_le_16": 1,
    }
    assert row[
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts"
    ] == {
        "resource_reference|string_length_prefix|nul_rich": 1,
    }
    assert row[
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts"
    ] == {
        "resource_reference|string_length_prefix|near_start_le_16|nul_rich": 1,
    }
    assert row[
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts"
    ] == {
        "resource_reference|string_length_prefix|forward_le_16": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts"] == {
        "le_16": 1,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_preserved_span_middle_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_rows"] == 1
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts"
    ] == {
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
        "resource_reference_count": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts"
    ] == {
        "resource_reference|string_length_prefix": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts"
    ] == {
        "resource_reference|string_length_prefix|near_start_le_16": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts"
    ] == {
        "resource_reference|string_length_prefix|nul_rich": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts"
    ] == {
        "resource_reference|string_length_prefix|near_start_le_16|nul_rich": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts"
    ] == {
        "resource_reference|string_length_prefix|forward_le_16": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts"
    ] == {
        "le_16": 1,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }


def test_prefab_corpus_report_counts_outside_descriptor_string_value_mod4(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00\x00"
    path = "character/model/test_a.pac"
    target_value = len(prefix) + 8
    payload = prefix + target_value.to_bytes(4, "little") + _lp(path)
    entry = _entry("character/prefab/string-value-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    row = report["rows"][0]

    assert row["offset_candidate_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_target_string_value_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 1,
        "2": 0,
        "3": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts"] == {
        "0": 0,
        "1": 1,
        "2": 0,
        "3": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_target_role_counts"] == {
        "resource_reference_count": 1,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_string_value_target_role_counts"] == {
        "resource_reference_count": 1,
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 1,
        "2": 0,
        "3": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts"] == {
        "0": 0,
        "1": 1,
        "2": 0,
        "3": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_neighbor_byte_class_counts"] == {
        "ascii_like": 0,
        "binary_like": 0,
        "empty": 0,
        "nul_rich": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts"] == {
        "ascii_like": 0,
        "binary_like": 0,
        "empty": 0,
        "nul_rich": 1,
    }
    assert row[
        "offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts"
    ] == {
        "unaligned|string_value|model|.pac|nul_rich": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts"] == {
        "unaligned|string_value": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts"] == {
        "unaligned|string_value|.pac": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts"] == {
        "unaligned|string_value|model": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts"] == {
        "unaligned|string_value|le_16": 1,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts"] == {
        "le_16": 1,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }
    assert row["offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count"] == 0
    assert row["offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count"] == 1
    assert row["offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count"] == 0
    assert report["summary"]["offset_candidate_outside_member_descriptor_target_string_value_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts"] == {
        "0": 0,
        "1": 1,
        "2": 0,
        "3": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_string_value_target_role_counts"] == {
        "member_name_count": 0,
        "member_type_count": 0,
        "other_string_count": 0,
        "resource_reference_count": 1,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_target_string_value_rows"] == 1
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts"
    ] == {"0": 0, "1": 1, "2": 0, "3": 0}
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts"] == {
        "0": 0,
        "1": 1,
        "2": 0,
        "3": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_neighbor_byte_class_counts"] == {
        "ascii_like": 0,
        "binary_like": 0,
        "empty": 0,
        "nul_rich": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts"
    ] == {
        "ascii_like": 0,
        "binary_like": 0,
        "empty": 0,
        "nul_rich": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts"
    ] == {
        "unaligned|string_value|model|.pac|nul_rich": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts"
    ] == {
        "unaligned|string_value": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts"
    ] == {
        "unaligned|string_value|.pac": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts"
    ] == {
        "unaligned|string_value|model": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts"
    ] == {
        "unaligned|string_value|le_16": 1,
    }
    assert report["summary"][
        "offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts"
    ] == {
        "le_16": 1,
        "le_32": 0,
        "le_64": 0,
        "le_128": 0,
        "gt_128": 0,
    }
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_rows"] == 1
    assert report["summary"]["offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_rows"] == 1


def test_prefab_corpus_report_counts_array_descriptor_signatures(tmp_path: Path) -> None:
    payload = (
        b"\xff\xff\x04\x00"
        + _lp("_socketList")
        + _lp("ReflectObjectPtr")
        + b"\x07\x00\x00\x00\x08\x10\x00\x01"
        + _lp("character/model/test_a.pac")
    )
    entry = _entry("character/prefab/array.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)

    expected = {"ReflectObjectPtr|7,0,4104,256": 1}
    assert report["rows"][0]["array_member_count"] == 1
    assert report["rows"][0]["array_member_count_hint_count"] == 1
    assert report["rows"][0]["array_descriptor_signature_counts"] == expected
    assert report["rows"][0]["array_descriptor_signature_offset_candidate_counts"] == {
        "ReflectObjectPtr|7,0,4104,256|without_offset_candidate": 1
    }
    assert report["rows"][0]["array_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["rows"][0]["array_descriptor_word0_value_counts"] == {"7": 1}
    assert report["rows"][0]["array_descriptor_word1_value_counts"] == {"0": 1}
    assert report["rows"][0]["array_descriptor_word2_value_counts"] == {"4104": 1}
    assert report["rows"][0]["array_descriptor_word3_value_counts"] == {"256": 1}
    assert report["rows"][0]["descriptor_tail_member_kind_counts"] == {}
    assert report["rows"][0]["descriptor_tail_byte_kind_counts"] == {}
    assert report["rows"][0]["descriptor_tail_member_detail_counts"] == {}
    assert report["rows"][0]["member_descriptor_preserved_bytes"] == 8
    assert report["rows"][0]["member_descriptor_header_preserved_bytes"] == 8
    assert report["rows"][0]["member_descriptor_tail_preserved_bytes"] == 0
    assert report["rows"][0]["preserved_unknown_bytes_excluding_member_descriptors"] == 4
    assert report["rows"][0]["preserved_unknown_bytes_excluding_member_descriptor_headers"] == 4
    assert report["rows"][0]["preserved_span_with_member_descriptor_count"] == 1
    assert report["rows"][0]["preserved_span_with_member_descriptor_header_count"] == 1
    assert report["rows"][0]["preserved_span_with_member_descriptor_tail_count"] == 0
    assert report["rows"][0]["preserved_span_without_member_descriptor_count"] == 1
    assert report["rows"][0]["array_stride_hint_type_counts"] == {}
    assert report["rows"][0]["array_count_hint_type_counts"] == {"ReflectObjectPtr|256": 1}
    assert report["rows"][0]["array_count_hint_member_counts"] == {"_socketList|ReflectObjectPtr|256": 1}
    assert report["rows"][0]["array_word3_relation_counts"] == {
        "array_rows": 1,
        "with_count_hint_rows": 1,
        "with_stride_hint_rows": 0,
        "word3_zero_rows": 0,
        "word3_nonzero_rows": 1,
        "word3_equals_count_hint_rows": 1,
        "word3_nonzero_equals_count_hint_rows": 1,
        "count_hint_positive_word3_equals_count_hint_rows": 1,
        "count_hint_positive_word3_not_count_hint_rows": 0,
        "word3_equals_stride_hint_rows": 0,
        "word3_equals_word2_delta_rows": 0,
        "word3_nonzero_without_count_hint_rows": 0,
        "word3_nonzero_without_stride_hint_rows": 1,
    }
    assert report["rows"][0]["array_word2_delta_member_counts"] == {"_socketList|ReflectObjectPtr|8": 1}
    assert report["rows"][0]["array_word2_delta_word3_member_counts"] == {
        "_socketList|ReflectObjectPtr|8|256": 1
    }
    assert report["rows"][0]["array_word2_delta_word3_member_offset_candidate_counts"] == {
        "_socketList|ReflectObjectPtr|8|256|without_offset_candidate": 1
    }
    assert report["rows"][0]["array_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["rows"][0]["array_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 1,
    }
    assert report["rows"][0]["array_classification_source_counts"] == {
        "type_vector_count": 0,
        "type_brackets_count": 0,
        "name_list_flag_count": 1,
    }
    assert report["rows"][0]["array_word3_category_counts"] == {
        "zero_count": 0,
        "one_count": 0,
        "power_of_two_gt_one_count": 1,
        "other_nonzero_count": 0,
        "nonzero_with_stride_hint_count": 0,
        "nonzero_without_stride_hint_count": 1,
    }
    assert report["summary"]["array_member_rows"] == 1
    assert report["summary"]["array_descriptor_signature_counts"] == expected
    assert report["summary"]["array_descriptor_signature_offset_candidate_counts"] == {
        "ReflectObjectPtr|7,0,4104,256|without_offset_candidate": 1
    }
    assert report["summary"]["array_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["summary"]["array_descriptor_word0_value_counts"] == {"7": 1}
    assert report["summary"]["array_descriptor_word1_value_counts"] == {"0": 1}
    assert report["summary"]["array_descriptor_word2_value_counts"] == {"4104": 1}
    assert report["summary"]["array_descriptor_word3_value_counts"] == {"256": 1}
    assert report["summary"]["descriptor_tail_member_kind_counts"] == {}
    assert report["summary"]["descriptor_tail_byte_kind_counts"] == {}
    assert report["summary"]["descriptor_tail_member_detail_counts"] == {}
    assert report["summary"]["member_descriptor_preserved_bytes"] == 8
    assert report["summary"]["member_descriptor_header_preserved_bytes"] == 8
    assert report["summary"]["member_descriptor_tail_preserved_bytes"] == 0
    assert report["summary"]["preserved_unknown_bytes_excluding_member_descriptors"] == 4
    assert report["summary"]["preserved_unknown_bytes_excluding_member_descriptor_headers"] == 4
    assert report["summary"]["preserved_spans_with_member_descriptors"] == 1
    assert report["summary"]["preserved_spans_with_member_descriptor_headers"] == 1
    assert report["summary"]["preserved_spans_with_member_descriptor_tails"] == 0
    assert report["summary"]["preserved_spans_without_member_descriptors"] == 1
    assert report["summary"]["array_stride_hint_type_counts"] == {}
    assert report["summary"]["array_count_hint_type_counts"] == {"ReflectObjectPtr|256": 1}
    assert report["summary"]["array_count_hint_member_counts"] == {"_socketList|ReflectObjectPtr|256": 1}
    assert report["summary"]["array_word3_relation_counts"] == {
        "array_rows": 1,
        "count_hint_positive_word3_equals_count_hint_rows": 1,
        "count_hint_positive_word3_not_count_hint_rows": 0,
        "with_count_hint_rows": 1,
        "with_stride_hint_rows": 0,
        "word3_equals_count_hint_rows": 1,
        "word3_equals_stride_hint_rows": 0,
        "word3_equals_word2_delta_rows": 0,
        "word3_nonzero_equals_count_hint_rows": 1,
        "word3_nonzero_rows": 1,
        "word3_nonzero_without_count_hint_rows": 0,
        "word3_nonzero_without_stride_hint_rows": 1,
        "word3_zero_rows": 0,
    }
    assert report["summary"]["array_word2_delta_member_counts"] == {"_socketList|ReflectObjectPtr|8": 1}
    assert report["summary"]["array_word2_delta_word3_member_counts"] == {
        "_socketList|ReflectObjectPtr|8|256": 1
    }
    assert report["summary"]["array_word2_delta_word3_member_offset_candidate_counts"] == {
        "_socketList|ReflectObjectPtr|8|256|without_offset_candidate": 1
    }
    assert report["summary"]["array_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["summary"]["array_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 1,
    }
    assert report["summary"]["array_classification_source_counts"] == {
        "name_list_flag_count": 1,
        "type_brackets_count": 0,
        "type_vector_count": 0,
    }
    assert report["summary"]["array_word3_category_counts"] == {
        "nonzero_with_stride_hint_count": 0,
        "nonzero_without_stride_hint_count": 1,
        "one_count": 0,
        "other_nonzero_count": 0,
        "power_of_two_gt_one_count": 1,
        "zero_count": 0,
    }


def test_prefab_corpus_report_counts_array_descriptor_offset_candidates(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00" + _lp("_socketList") + _lp("ReflectObjectPtr")
    target_value = len(prefix) + 8
    descriptor = target_value.to_bytes(4, "little") + b"\x00\x10\x00\x00"
    payload = prefix + descriptor + _lp("character/model/test_a.pac")
    entry = _entry("character/prefab/array-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)

    word0 = target_value & 0xFFFF
    word1 = target_value >> 16
    expected = {f"ReflectObjectPtr|{word0},{word1},4096,0|with_offset_candidate": 1}
    expected_target = {f"ReflectObjectPtr|{word0},{word1},4096,0|resource_reference|string_length_prefix": 1}
    expected_member = {f"_socketList|ReflectObjectPtr|0|0|with_offset_candidate": 1}
    assert report["rows"][0]["array_descriptor_signature_offset_candidate_counts"] == expected
    assert report["rows"][0]["array_descriptor_signature_offset_candidate_target_counts"] == expected_target
    assert report["rows"][0]["array_word2_delta_word3_member_offset_candidate_counts"] == expected_member
    assert report["rows"][0]["offset_candidate_in_array_descriptor_count"] == 1
    assert report["summary"]["array_descriptor_signature_offset_candidate_counts"] == expected
    assert report["summary"]["array_descriptor_signature_offset_candidate_target_counts"] == expected_target
    assert report["summary"]["array_word2_delta_word3_member_offset_candidate_counts"] == expected_member
    assert report["summary"]["array_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["offset_candidate_in_array_descriptor_rows"] == 1


def test_prefab_corpus_report_counts_nonzero_array_word3_offset_candidate_targets(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00" + _lp("_socketList") + _lp("ReflectObjectPtr")
    target_value = len(prefix) + 8
    descriptor = (
        (target_value & 0xFFFF).to_bytes(2, "little")
        + (target_value >> 16).to_bytes(2, "little")
        + (4104).to_bytes(2, "little")
        + (256).to_bytes(2, "little")
    )
    payload = prefix + descriptor + _lp("character/model/test_a.pac")
    entry = _entry("character/prefab/array-word3-target.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)

    word0 = target_value & 0xFFFF
    word1 = target_value >> 16
    expected_signature = {f"ReflectObjectPtr|{word0},{word1},4104,256|with_offset_candidate": 1}
    expected_target = {f"ReflectObjectPtr|{word0},{word1},4104,256|resource_reference|string_length_prefix": 1}
    expected_nonzero_target = {"resource_reference|string_length_prefix": 1}
    assert report["rows"][0]["array_descriptor_signature_offset_candidate_counts"] == expected_signature
    assert report["rows"][0]["array_descriptor_signature_offset_candidate_target_counts"] == expected_target
    assert report["rows"][0]["array_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert report["rows"][0]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {
        "array|resource_reference|string_length_prefix": 1
    }
    assert report["summary"]["array_descriptor_signature_offset_candidate_counts"] == expected_signature
    assert report["summary"]["array_descriptor_signature_offset_candidate_target_counts"] == expected_target
    assert report["summary"]["array_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert report["summary"]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {
        "array|resource_reference|string_length_prefix": 1
    }


def test_prefab_corpus_report_counts_array_stride_hint_types(tmp_path: Path) -> None:
    payload = (
        b"\xff\xff\x04\x00"
        + _lp("_valueList")
        + _lp("float3")
        + b"\x03\x00\x0c\x00\x00\x10\x00\x00"
        + _lp("character/model/test_a.pac")
    )
    entry = _entry("character/prefab/array-stride.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)

    expected = {"float3|12": 1}
    assert report["rows"][0]["array_member_count"] == 1
    assert report["rows"][0]["array_member_stride_hint_count"] == 1
    assert report["rows"][0]["array_member_count_hint_count"] == 0
    assert report["rows"][0]["array_stride_hint_type_counts"] == expected
    assert report["rows"][0]["array_count_hint_type_counts"] == {}
    assert report["rows"][0]["array_count_hint_member_counts"] == {}
    assert report["rows"][0]["array_word2_delta_member_counts"] == {"_valueList|float3|0": 1}
    assert report["rows"][0]["array_word2_delta_word3_member_counts"] == {"_valueList|float3|0|0": 1}
    assert report["summary"]["array_member_rows"] == 1
    assert report["summary"]["array_member_stride_hint_rows"] == 1
    assert report["summary"]["array_member_count_hint_rows"] == 0
    assert report["summary"]["array_stride_hint_type_counts"] == expected
    assert report["summary"]["array_count_hint_type_counts"] == {}
    assert report["summary"]["array_count_hint_member_counts"] == {}
    assert report["summary"]["array_word2_delta_member_counts"] == {"_valueList|float3|0": 1}
    assert report["summary"]["array_word2_delta_word3_member_counts"] == {"_valueList|float3|0|0": 1}


def test_prefab_corpus_report_counts_transform_descriptor_signatures(tmp_path: Path) -> None:
    payload = (
        b"\xff\xff\x04\x00"
        + _lp("_worldTransform")
        + _lp("Transform")
        + b"\x00\x00\x28\x00\x00\x00\x00\x00"
        + _lp("character/model/test_a.pac")
    )
    entry = _entry("character/prefab/transform.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)

    expected = {"Transform|0,40,0,0": 1}
    assert report["rows"][0]["transform_member_count"] == 1
    assert report["rows"][0]["transform_descriptor_signature_counts"] == expected
    assert report["rows"][0]["transform_descriptor_signature_offset_candidate_counts"] == {
        "Transform|0,40,0,0|without_offset_candidate": 1
    }
    assert report["rows"][0]["transform_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert report["rows"][0]["transform_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["rows"][0]["transform_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["rows"][0]["transform_descriptor_word0_value_counts"] == {"0": 1}
    assert report["rows"][0]["transform_descriptor_word1_value_counts"] == {"40": 1}
    assert report["rows"][0]["transform_descriptor_word2_value_counts"] == {"0": 1}
    assert report["rows"][0]["transform_descriptor_word3_value_counts"] == {"0": 1}
    assert report["rows"][0]["transform_theoretical_payload_shape_counts"] == {"_worldTransform|Transform|40": 1}
    assert report["summary"]["transform_member_rows"] == 1
    assert report["summary"]["transform_descriptor_signature_counts"] == expected
    assert report["summary"]["transform_descriptor_signature_offset_candidate_counts"] == {
        "Transform|0,40,0,0|without_offset_candidate": 1
    }
    assert report["summary"]["transform_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 0,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["transform_descriptor_signature_offset_candidate_target_counts"] == {}
    assert report["summary"]["transform_nonzero_word3_offset_candidate_target_counts"] == {}
    assert report["summary"]["transform_descriptor_word0_value_counts"] == {"0": 1}
    assert report["summary"]["transform_descriptor_word1_value_counts"] == {"40": 1}
    assert report["summary"]["transform_descriptor_word2_value_counts"] == {"0": 1}
    assert report["summary"]["transform_descriptor_word3_value_counts"] == {"0": 1}
    assert report["summary"]["transform_theoretical_payload_shape_counts"] == {"_worldTransform|Transform|40": 1}


def test_prefab_corpus_report_counts_transform_descriptor_offset_candidates(tmp_path: Path) -> None:
    prefix = b"\xff\xff\x04\x00" + _lp("_worldTransform") + _lp("Transform")
    target_value = len(prefix) + 8
    descriptor = target_value.to_bytes(4, "little") + b"\x00\x10\x02\x00"
    payload = prefix + descriptor + _lp("character/model/test_a.pac")
    entry = _entry("character/prefab/transform-offset.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)

    word0 = target_value & 0xFFFF
    word1 = target_value >> 16
    expected = {f"Transform|{word0},{word1},4096,2|with_offset_candidate": 1}
    expected_target = {f"Transform|{word0},{word1},4096,2|resource_reference|string_length_prefix": 1}
    expected_nonzero_target = {"resource_reference|string_length_prefix": 1}
    assert report["rows"][0]["transform_descriptor_signature_offset_candidate_counts"] == expected
    assert report["rows"][0]["transform_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert report["rows"][0]["transform_descriptor_signature_offset_candidate_target_counts"] == expected_target
    assert report["rows"][0]["transform_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert report["rows"][0]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {
        "transform|resource_reference|string_length_prefix": 1
    }
    assert report["rows"][0]["offset_candidate_in_transform_descriptor_count"] == 1
    assert report["summary"]["transform_descriptor_signature_offset_candidate_counts"] == expected
    assert report["summary"]["transform_nonzero_word3_offset_candidate_status_counts"] == {
        "with_offset_candidate": 1,
        "without_offset_candidate": 0,
    }
    assert report["summary"]["transform_descriptor_signature_offset_candidate_target_counts"] == expected_target
    assert report["summary"]["transform_nonzero_word3_offset_candidate_target_counts"] == expected_nonzero_target
    assert report["summary"]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {
        "transform|resource_reference|string_length_prefix": 1
    }
    assert report["summary"]["offset_candidate_in_transform_descriptor_rows"] == 1


def test_prefab_corpus_report_counts_transform_name_only_members(tmp_path: Path) -> None:
    payload = (
        b"\xff\xff\x04\x00"
        + _lp("_applyTransform")
        + _lp("bool")
        + b"\x00\x00\x01\x00\x00\x00\x00\x00"
        + _lp("character/model/test_a.pac")
    )
    entry = _entry("character/prefab/transform-name.prefab", tmp_path, payload)

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)

    assert report["rows"][0]["transform_member_count"] == 0
    assert report["rows"][0]["transform_name_only_member_count"] == 1
    assert report["rows"][0]["transform_descriptor_signature_counts"] == {}
    assert report["rows"][0]["transform_descriptor_word0_value_counts"] == {}
    assert report["rows"][0]["transform_descriptor_word1_value_counts"] == {}
    assert report["rows"][0]["transform_descriptor_word2_value_counts"] == {}
    assert report["rows"][0]["transform_descriptor_word3_value_counts"] == {}
    assert report["summary"]["transform_member_rows"] == 0
    assert report["summary"]["transform_name_only_member_rows"] == 1


def test_prefab_corpus_probe_skips_overlapping_offset_candidates(tmp_path: Path) -> None:
    path = "character/model/a.pac"
    target = "tree/tree_pine_spruce_norway_hero_03.pat"
    payload = bytearray(b"\x00" * 16653)
    payload[0:4] = b"\xff\xff\x04\x00"
    payload[4 : 4 + len(_lp(path))] = _lp(path)
    payload[40:45] = bytes((0xE5, 0x40, 0, 0, 0))
    payload[60 : 60 + len(_lp("IndexedStringA"))] = _lp("IndexedStringA")
    payload[16609 : 16609 + len(_lp(target))] = _lp(target)
    entry = _entry("character/prefab/overlap.prefab", tmp_path, bytes(payload))

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return bytes(payload), False, ""

    report = build_prefab_json_import_archive_entry_report([entry], read_entry_data=read_entry_data)
    probe = report["rows"][0]["experimental_length_change_resource_rebuild_probe"]

    assert report["rows"][0]["status"] == "passed"
    assert report["rows"][0]["offset_candidate_overlap_count"] == 1
    assert report["rows"][0]["offset_candidate_overlap_group_count"] == 1
    assert report["rows"][0]["offset_candidate_overlapping_window_count"] == 2
    assert report["rows"][0]["offset_candidate_isolated_count"] == 0
    assert report["rows"][0]["offset_candidate_unaligned_or_overlapping_count"] == 2
    assert report["rows"][0]["resource_resize_impact_unique_overlap_counts"] == {
        "non_overlapping_count": 0,
        "overlapping_count": 2,
    }
    assert report["rows"][0]["resource_resize_impact_unique_resource_reference_overlap_counts"] == {
        "non_overlapping_count": 0,
        "overlapping_count": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_overlap_profile_counts"] == {
        "overlapping|outside_member_descriptor|other_string|string_value|unaligned|near_start_le_16|nul_rich|forward_le_64": 1,
        "overlapping|outside_member_descriptor|resource_reference|string_value|aligned|near_start_le_16|nul_rich|forward_gt_1024": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_overlap_group_profile_counts"] == {
        "size_2|width_5|deltas_0,1|group=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value|impacted=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_overlap_group_target_identity_counts"] == {
        "size_2|width_5|deltas_0,1|group_mixed_target_identity|impacted_mixed_target_identity": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_same_target_overlap_collapse_counts"] == {
        "impacted_overlap_group_count": 1,
        "impacted_overlap_candidate_count": 2,
        "same_target_duplicate_group_count": 0,
        "same_target_duplicate_candidate_count": 0,
        "mixed_target_group_count": 1,
        "mixed_target_candidate_count": 2,
        "blocker_group_count_after_same_target_collapse": 1,
        "blocker_candidate_count_after_same_target_collapse": 2,
    }
    assert report["rows"][0]["resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts"] == {
        "size_2|width_5|deltas_0,1|group=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value|impacted=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts"] == {
        "other_string|string_value|value_64|field_1|": 1,
        f"resource_reference|string_value|value_16613|field_2|{target}": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary"] == {
        "candidate_count": 2,
        "unique_identity_count": 2,
        "repeated_identity_count": 0,
        "repeated_candidate_count": 0,
        "high_repeat_10_identity_count": 0,
        "high_repeat_10_candidate_count": 0,
        "max_identity_candidate_count": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts"] == {
        "mixed_target_group_count": 1,
        "mixed_target_candidate_count": 2,
        "high_repeat_identity_count": 0,
        "high_repeat_candidate_count": 0,
        "remaining_group_count_after_high_repeat_collapse": 1,
        "remaining_candidate_count_after_high_repeat_collapse": 2,
    }
    assert report["rows"][0][
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts"
    ] == {
        "size_2|width_5|deltas_0,1|group=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value|remaining=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value": 1,
    }
    assert report["rows"][0][
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts"
    ] == {
        "other_string|string_value|value_64|field_1|": 1,
        f"resource_reference|string_value|value_16613|field_2|{target}": 1,
    }
    assert report["rows"][0][
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts"
    ] == {
        "other_string|string_value|value_64|field_1||word_40000000|mod4_1|near_start_le_16|deltas_0,1": 1,
        f"resource_reference|string_value|value_16613|field_2|{target}|word_e5400000|mod4_0|near_start_le_16|deltas_0,1": 1,
    }
    assert report["rows"][0]["resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts"] == {
        "other_string|string_value|value_64|field_1||word_40000000|mod4_1|near_start_le_16|deltas_0,1": 1,
        f"resource_reference|string_value|value_16613|field_2|{target}|word_e5400000|mod4_0|near_start_le_16|deltas_0,1": 1,
    }
    assert probe["status"] == "skipped"
    assert "offset candidates overlap" in probe["error"]
    assert probe["used_opt_in_import_path"] is True
    assert probe["selected_resize_offset_candidate_count"] == 2
    assert probe["selected_resize_offset_candidate_non_overlapping_count"] == 0
    assert probe["selected_resize_offset_candidate_overlapping_count"] == 2
    assert probe["selected_resize_offset_candidate_target_role_kind_counts"] == {
        "other_string|string_value": 1,
        "resource_reference|string_value": 1,
    }
    assert probe["selected_resize_offset_candidate_owner_kind_target_counts"] == {
        "outside_member_descriptor|other_string|string_value": 1,
        "outside_member_descriptor|resource_reference|string_value": 1,
    }
    assert probe["selected_resize_offset_candidate_same_target_overlap_shift_conflict_counts"] == {
        "same_target_overlap_group_count": 0,
        "same_target_overlap_candidate_count": 0,
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "shift_conflict_group_count": 0,
        "shift_conflict_candidate_count": 0,
    }
    assert probe["selected_resize_offset_candidate_same_target_overlap_shift_conflict_profile_counts"] == {}
    assert probe["selected_resize_offset_candidate_same_target_resource_alias_counts"] == {
        "same_target_shift_conflict_group_count": 0,
        "same_target_shift_conflict_candidate_count": 0,
        "resource_alias_group_count": 0,
        "resource_alias_candidate_count": 0,
        "resource_reference_non_alias_group_count": 0,
        "resource_reference_non_alias_candidate_count": 0,
        "other_group_count": 0,
        "other_candidate_count": 0,
    }
    assert probe["selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_counts"] == {
        "mixed_target_overlap_group_count": 1,
        "mixed_target_overlap_candidate_count": 2,
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "shift_conflict_group_count": 1,
        "shift_conflict_candidate_count": 2,
    }
    expected_selected_mixed_profile = {
        "shift_conflict|size_2|width_5|deltas_0,1|group=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value|impacted=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value": 1,
    }
    assert probe["selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_profile_counts"] == (
        expected_selected_mixed_profile
    )
    expected_selected_mixed_resource_reference_detail = {
        "shift_conflict|size_2|deltas_0,1|"
        "group=delta_0:resource_reference|string_value|"
        f"value_16613|field_2|{target}|word_e5400000|mod4_0|near_start_le_16,"
        "delta_1:other_string|string_value|value_64|field_1||word_40000000|mod4_1|near_start_le_16|"
        "impacted=delta_0:resource_reference|string_value|"
        f"value_16613|field_2|{target}|word_e5400000|mod4_0|near_start_le_16,"
        "delta_1:other_string|string_value|value_64|field_1||word_40000000|mod4_1|near_start_le_16": 1,
    }
    assert probe["selected_resize_offset_candidate_mixed_target_resource_reference_group_detail_counts"] == (
        expected_selected_mixed_resource_reference_detail
    )
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_failed"] == 0
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_skipped"] == 1
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_offset_candidate_count"] == 2
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_non_overlapping_count"] == 0
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_overlapping_count"] == 2
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_target_role_kind_counts"] == {
        "other_string|string_value": 1,
        "resource_reference|string_value": 1,
    }
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_selected_owner_kind_target_counts"] == {
        "outside_member_descriptor|other_string|string_value": 1,
        "outside_member_descriptor|resource_reference|string_value": 1,
    }
    assert report["summary"][
        "experimental_length_change_resource_rebuild_probe_selected_mixed_target_overlap_shift_conflict_counts"
    ] == {
        "mixed_target_overlap_group_count": 1,
        "mixed_target_overlap_candidate_count": 2,
        "shift_consistent_group_count": 0,
        "shift_consistent_candidate_count": 0,
        "shift_conflict_group_count": 1,
        "shift_conflict_candidate_count": 2,
    }
    assert report["summary"][
        "experimental_length_change_resource_rebuild_probe_selected_mixed_target_overlap_shift_conflict_profile_counts"
    ] == expected_selected_mixed_profile
    assert report["summary"][
        "experimental_length_change_resource_rebuild_probe_selected_mixed_target_resource_reference_group_detail_counts"
    ] == expected_selected_mixed_resource_reference_detail
    assert report["summary"][
        "experimental_length_change_resource_rebuild_probe_selected_same_target_resource_alias_counts"
    ] == {
        "same_target_shift_conflict_group_count": 0,
        "same_target_shift_conflict_candidate_count": 0,
        "resource_alias_group_count": 0,
        "resource_alias_candidate_count": 0,
        "resource_reference_non_alias_group_count": 0,
        "resource_reference_non_alias_candidate_count": 0,
        "other_group_count": 0,
        "other_candidate_count": 0,
    }
    assert report["summary"]["offset_candidate_overlap_rows"] == 1
    assert report["summary"]["offset_candidate_overlap_group_rows"] == 1
    assert report["summary"]["offset_candidate_overlapping_window_rows"] == 2
    assert report["summary"]["offset_candidate_isolated_rows"] == 0
    assert report["summary"]["offset_candidate_unaligned_or_overlapping_rows"] == 2
    assert report["summary"]["files_with_offset_candidate_overlaps"] == 1
    assert report["summary"]["resource_resize_impact_unique_overlap_counts"] == {
        "non_overlapping_count": 0,
        "overlapping_count": 2,
    }
    assert report["summary"]["resource_resize_impact_unique_resource_reference_overlap_counts"] == {
        "non_overlapping_count": 0,
        "overlapping_count": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_overlap_profile_counts"] == {
        "overlapping|outside_member_descriptor|other_string|string_value|unaligned|near_start_le_16|nul_rich|forward_le_64": 1,
        "overlapping|outside_member_descriptor|resource_reference|string_value|aligned|near_start_le_16|nul_rich|forward_gt_1024": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_overlap_group_profile_counts"] == {
        "size_2|width_5|deltas_0,1|group=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value|impacted=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_overlap_group_target_identity_counts"] == {
        "size_2|width_5|deltas_0,1|group_mixed_target_identity|impacted_mixed_target_identity": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_same_target_overlap_collapse_counts"] == {
        "impacted_overlap_group_count": 1,
        "impacted_overlap_candidate_count": 2,
        "same_target_duplicate_group_count": 0,
        "same_target_duplicate_candidate_count": 0,
        "mixed_target_group_count": 1,
        "mixed_target_candidate_count": 2,
        "blocker_group_count_after_same_target_collapse": 1,
        "blocker_candidate_count_after_same_target_collapse": 2,
    }
    assert report["summary"]["resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts"] == {
        "size_2|width_5|deltas_0,1|group=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value|impacted=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts"] == {
        "other_string|string_value|value_64|field_1|": 1,
        f"resource_reference|string_value|value_16613|field_2|{target}": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary"] == {
        "candidate_count": 2,
        "unique_identity_count": 2,
        "repeated_identity_count": 0,
        "repeated_candidate_count": 0,
        "high_repeat_10_identity_count": 0,
        "high_repeat_10_candidate_count": 0,
        "max_identity_candidate_count": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts"] == {
        "mixed_target_group_count": 1,
        "mixed_target_candidate_count": 2,
        "high_repeat_identity_count": 0,
        "high_repeat_candidate_count": 0,
        "remaining_group_count_after_high_repeat_collapse": 1,
        "remaining_candidate_count_after_high_repeat_collapse": 2,
    }
    assert report["summary"][
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts"
    ] == {
        "size_2|width_5|deltas_0,1|group=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value|remaining=outside_member_descriptor:other_string:string_value,outside_member_descriptor:resource_reference:string_value": 1,
    }
    assert report["summary"][
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts"
    ] == {
        "other_string|string_value|value_64|field_1|": 1,
        f"resource_reference|string_value|value_16613|field_2|{target}": 1,
    }
    assert report["summary"][
        "resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts"
    ] == {
        "other_string|string_value|value_64|field_1||word_40000000|mod4_1|near_start_le_16|deltas_0,1": 1,
        f"resource_reference|string_value|value_16613|field_2|{target}|word_e5400000|mod4_0|near_start_le_16|deltas_0,1": 1,
    }
    assert report["summary"]["resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts"] == {
        "other_string|string_value|value_64|field_1||word_40000000|mod4_1|near_start_le_16|deltas_0,1": 1,
        f"resource_reference|string_value|value_16613|field_2|{target}|word_e5400000|mod4_0|near_start_le_16|deltas_0,1": 1,
    }
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_skip_reasons"] == {
        "Prefab offset candidates overlap; length-changing rebuild is ambiguous.": 1
    }
    assert report["summary"]["experimental_length_change_resource_rebuild_probe_failure_reasons"] == {}
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["resource_length_probe_overlap_ambiguous_skipped_rows"] == 1
    assert detail_counts["resource_length_probe_no_safe_candidate_skipped_rows"] == 0
    assert detail_counts["resource_length_probe_edit_probes_disabled_skipped_rows"] == 0
    assert detail_counts["resource_resize_impact_mixed_target_shift_conflict_groups"] == 1
    assert detail_counts["resource_resize_impact_mixed_target_shift_conflict_candidates"] == 2
    assert detail_counts["resource_resize_impact_mixed_target_shift_consistent_groups"] == 0
    assert detail_counts["resource_resize_impact_mixed_target_shift_consistent_candidates"] == 0
    assert detail_counts["resource_resize_impact_same_target_resource_alias_remaining_groups"] == 0
    assert detail_counts["resource_resize_impact_same_target_resource_alias_remaining_candidates"] == 0
    assert report["gate"]["experimental_length_change_rebuild_probe_ready"] is False


def test_prefab_archive_entry_report_samples_across_discovered_entries(tmp_path: Path) -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    entries = [_entry(f"character/prefab/{index}.prefab", tmp_path, payload) for index in range(5)]

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report(
        entries,
        read_entry_data=read_entry_data,
        detail_scan_limit=3,
    )

    assert [row["path"] for row in report["rows"]] == [
        "character/prefab/0.prefab",
        "character/prefab/2.prefab",
        "character/prefab/4.prefab",
    ]


def test_prefab_archive_entry_report_scans_contiguous_shard(tmp_path: Path) -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    entries = [_entry(f"character/prefab/{index}.prefab", tmp_path, payload) for index in range(5)]

    def read_entry_data(_entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return payload, False, ""

    report = build_prefab_json_import_archive_entry_report(
        entries,
        read_entry_data=read_entry_data,
        scan_offset=1,
        scan_count=2,
        include_edit_probes=False,
    )

    assert [row["path"] for row in report["rows"]] == [
        "character/prefab/1.prefab",
        "character/prefab/2.prefab",
    ]
    assert report["summary"]["files_discovered"] == 5
    assert report["summary"]["files_scanned"] == 2
    assert report["summary"]["scan_offset"] == 1
    assert report["summary"]["scan_count"] == 2
    assert report["summary"]["all_discovered_files_scanned"] is False
    assert report["gate"]["full_corpus_no_edit_rebuild_ready"] is False


def test_prefab_corpus_report_merge_proves_complete_shard_coverage(tmp_path: Path) -> None:
    _write_prefab(tmp_path / "a.prefab", "test_a")
    _write_prefab(tmp_path / "b.prefab", "test_b")

    first = build_prefab_json_import_corpus_report(
        [tmp_path],
        scan_offset=0,
        scan_count=1,
        include_edit_probes=False,
    )
    second = build_prefab_json_import_corpus_report(
        [tmp_path],
        scan_offset=1,
        scan_count=1,
        include_edit_probes=False,
    )

    merged = merge_prefab_json_import_corpus_reports([first, second])

    assert merged["summary"]["files_discovered"] == 2
    assert merged["summary"]["files_scanned"] == 2
    assert merged["summary"]["merged_report_count"] == 2
    assert merged["summary"]["coverage_complete"] is True
    assert merged["summary"]["coverage_errors"] == []
    assert merged["summary"]["all_discovered_files_scanned"] is True
    assert merged["gate"]["full_corpus_no_edit_rebuild_ready"] is True
    assert "full-corpus no-edit rebuild has not been run" not in merged["gate"]["length_changing_blockers"]


def test_prefab_corpus_report_merge_derives_word3_target_metrics_from_legacy_rows() -> None:
    legacy = {
        "format": PREFAB_JSON_IMPORT_CORPUS_FORMAT,
        "source_type": "loose_files",
        "source_paths": ["legacy"],
        "summary": {
            "files_discovered": 1,
            "files_scanned": 1,
            "scan_offset": 0,
            "scan_count": 1,
            "edit_probes_enabled": False,
            "discovery_limited": False,
        },
        "rows": [
            {
                "path": "legacy.prefab",
                "status": "passed",
                "array_descriptor_signature_offset_candidate_target_counts": {
                    "ReflectObjectPtr|7,0,4104,256|resource_reference|string_length_prefix": 2,
                },
                "transform_descriptor_signature_offset_candidate_target_counts": {
                    "Transform|0,40,0,2|member_type|string_end": 3,
                },
                "reference_descriptor_signature_offset_candidate_target_counts": {
                    "ReflectObjectPtr|7,0,4136,1|member_name|string_value": 4,
                },
                "scalar_or_bool_descriptor_signature_offset_candidate_target_counts": {
                    "uint32|3,4,4128,2|other_string|string_end": 5,
                },
                "string_descriptor_signature_offset_candidate_target_counts": {
                    "IndexedStringA|1,2,0,4|resource_reference|string_value": 6,
                },
                "generic_descriptor_signature_offset_candidate_target_counts": {
                    "CustomDescriptor|1,2,0,3|member_type|string_length_prefix": 7,
                },
            }
        ],
    }

    merged = merge_prefab_json_import_corpus_reports([legacy])

    assert merged["summary"]["array_nonzero_word3_offset_candidate_target_counts"] == {
        "resource_reference|string_length_prefix": 2,
    }
    assert merged["summary"]["transform_nonzero_word3_offset_candidate_target_counts"] == {
        "member_type|string_end": 3,
    }
    assert merged["summary"]["reference_nonzero_word3_offset_candidate_target_counts"] == {
        "member_name|string_value": 4,
    }
    assert merged["summary"]["scalar_or_bool_nonzero_word3_offset_candidate_target_counts"] == {
        "other_string|string_end": 5,
    }
    assert merged["summary"]["string_nonzero_word3_offset_candidate_target_counts"] == {
        "resource_reference|string_value": 6,
    }
    assert merged["summary"]["generic_nonzero_word3_offset_candidate_target_counts"] == {
        "member_type|string_length_prefix": 7,
    }
    assert merged["summary"]["descriptor_kind_nonzero_word3_offset_candidate_target_counts"] == {
        "array|resource_reference|string_length_prefix": 2,
        "generic|member_type|string_length_prefix": 7,
        "reference|member_name|string_value": 4,
        "scalar_or_bool|other_string|string_end": 5,
        "string|resource_reference|string_value": 6,
        "transform|member_type|string_end": 3,
    }
    detail_counts = merged["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["resource_length_probe_edit_probes_disabled_skipped_rows"] == 1
    assert detail_counts["placement_length_probe_edit_probes_disabled_skipped_rows"] == 1
    assert detail_counts["resource_resize_impact_mixed_target_shift_conflict_groups"] == 0
    assert detail_counts["placement_resize_impact_mixed_target_shift_conflict_groups"] == 0
    assert detail_counts["resource_resize_impact_same_target_resource_alias_remaining_groups"] == 0
    assert detail_counts["placement_resize_impact_same_target_resource_alias_remaining_groups"] == 0


def test_prefab_corpus_report_merge_summarizes_effective_remap_preserved_raw_roles() -> None:
    report = {
        "format": PREFAB_JSON_IMPORT_CORPUS_FORMAT,
        "source_type": "loose_files",
        "source_paths": ["fixture"],
        "summary": {
            "files_discovered": 1,
            "files_scanned": 1,
            "scan_offset": 0,
            "scan_count": 1,
            "edit_probes_enabled": True,
            "discovery_limited": False,
        },
        "rows": [
            {
                "path": "fixture.prefab",
                "status": "passed",
                "layout_rebuild_byte_identical": True,
                "json_layout_rebuild_byte_identical": True,
                "experimental_length_change_resource_rebuild_probe": {
                    "status": "failed",
                    "offset_candidates_effectively_remapped_after_edit": True,
                    "offset_candidate_report_only_effective_remap_status": "preserved_raw_exclusion_passed",
                    "resized_rebuild_changed_only_expected_bytes": False,
                    "resized_rebuild_changed_only_effective_expected_bytes": True,
                    "offset_candidates_remapped_after_excluding_unshifted_value_at_expected_offset": True,
                    "offset_candidate_remap_missing_count": 2,
                    "offset_candidate_remap_missing_after_excluding_unshifted_value_at_expected_offset_count": 0,
                    "offset_candidate_remap_missing_unshifted_value_at_expected_offset_count": 2,
                    "offset_candidate_remap_missing_shifted_value_at_expected_offset_count": 0,
                    "offset_candidate_remap_missing_other_value_at_expected_offset_count": 0,
                    "offset_candidate_remap_missing_out_of_bounds_expected_offset_count": 0,
                    "offset_candidate_remap_missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts": {
                        "outside_member_descriptor|resource_reference|string_value": 2,
                    },
                    "offset_candidate_remap_missing_non_metadata_resource_reference_extension_counts": {
                        ".pami": 2,
                    },
                    "offset_candidate_remap_missing_non_metadata_resource_reference_target_kind_extension_counts": {
                        "string_value|.pami": 2,
                    },
                    "offset_candidate_remap_missing_non_metadata_resource_reference_target_name_top_counts": {
                        "path_a.pami": 2,
                    },
                },
                "experimental_length_change_placement_rebuild_probe": {
                    "status": "failed",
                    "offset_candidates_effectively_remapped_after_edit": True,
                    "offset_candidate_report_only_effective_remap_status": "preserved_raw_exclusion_passed",
                    "resized_rebuild_changed_only_expected_bytes": False,
                    "resized_rebuild_changed_only_effective_expected_bytes": True,
                    "offset_candidates_remapped_after_excluding_unshifted_value_at_expected_offset": True,
                    "offset_candidate_remap_missing_count": 4,
                    "offset_candidate_remap_missing_after_excluding_unshifted_value_at_expected_offset_count": 0,
                    "offset_candidate_remap_missing_unshifted_value_at_expected_offset_count": 4,
                    "offset_candidate_remap_missing_shifted_value_at_expected_offset_count": 0,
                    "offset_candidate_remap_missing_other_value_at_expected_offset_count": 0,
                    "offset_candidate_remap_missing_out_of_bounds_expected_offset_count": 0,
                    "offset_candidate_remap_missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts": {
                        "outside_member_descriptor|member_name|string_length_prefix": 3,
                        "outside_member_descriptor|resource_reference|string_end": 1,
                    },
                    "offset_candidate_remap_missing_non_metadata_resource_reference_extension_counts": {
                        ".prefab": 1,
                    },
                    "offset_candidate_remap_missing_non_metadata_resource_reference_target_kind_extension_counts": {
                        "string_end|.prefab": 1,
                    },
                    "offset_candidate_remap_missing_non_metadata_resource_reference_target_name_top_counts": {
                        "path_b.prefab": 1,
                    },
                    "selected_resize_offset_candidate_count": 5,
                    "selected_resize_offset_candidate_non_overlapping_count": 4,
                    "selected_resize_offset_candidate_overlapping_count": 1,
                    "selected_resize_offset_candidate_target_role_kind_counts": {
                        "member_name|string_length_prefix": 3,
                        "resource_reference|string_end": 2,
                    },
                    "selected_resize_offset_candidate_owner_kind_target_counts": {
                        "outside_member_descriptor|member_name|string_length_prefix": 3,
                        "outside_member_descriptor|resource_reference|string_end": 2,
                    },
                },
            }
        ],
    }

    merged = merge_prefab_json_import_corpus_reports([report])

    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_missing_unshifted_owner_kind_target_role_kind_counts"
        ]
        == {"outside_member_descriptor|resource_reference|string_value": 2}
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_offset_remap_missing_count"
        ]
        == 2
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_report_only_effective_remap_status_counts"
        ]
        == {"preserved_raw_exclusion_passed": 1}
    )
    assert (
        merged["summary"]["experimental_length_change_resource_rebuild_probe_effective_offset_remap_passed"] == 1
    )
    assert (
        merged["summary"]["experimental_length_change_resource_rebuild_probe_changed_only_expected_passed"] == 0
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_changed_only_effective_expected_passed"
        ]
        == 1
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_status_effective_remap_status_counts"
        ]
        == {"failed|preserved_raw_exclusion_passed": 1}
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_status_effective_expected_counts"
        ]
        == {"failed|true": 1}
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_missing_unshifted_value_at_expected_offset_count"
        ]
        == 2
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_missing_shifted_value_at_expected_offset_count"
        ]
        == 0
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_missing_non_metadata_resource_reference_extension_counts"
        ]
        == {".pami": 2}
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_missing_non_metadata_resource_reference_target_kind_extension_counts"
        ]
        == {"string_value|.pami": 2}
    )
    assert (
        merged["summary"][
            "experimental_length_change_resource_rebuild_probe_missing_non_metadata_resource_reference_target_name_top_counts"
        ]
        == {"path_a.pami": 2}
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_missing_unshifted_owner_kind_target_role_kind_counts"
        ]
        == {
            "outside_member_descriptor|member_name|string_length_prefix": 3,
            "outside_member_descriptor|resource_reference|string_end": 1,
        }
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_offset_remap_missing_count"
        ]
        == 4
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_report_only_effective_remap_status_counts"
        ]
        == {"preserved_raw_exclusion_passed": 1}
    )
    assert (
        merged["summary"]["experimental_length_change_placement_rebuild_probe_effective_offset_remap_passed"] == 1
    )
    assert (
        merged["summary"]["experimental_length_change_placement_rebuild_probe_changed_only_expected_passed"] == 0
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_changed_only_effective_expected_passed"
        ]
        == 1
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_status_effective_remap_status_counts"
        ]
        == {"failed|preserved_raw_exclusion_passed": 1}
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_status_effective_expected_counts"
        ]
        == {"failed|true": 1}
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_missing_unshifted_value_at_expected_offset_count"
        ]
        == 4
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_missing_out_of_bounds_expected_offset_count"
        ]
        == 0
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_missing_non_metadata_resource_reference_extension_counts"
        ]
        == {".prefab": 1}
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_missing_non_metadata_resource_reference_target_kind_extension_counts"
        ]
        == {"string_end|.prefab": 1}
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_missing_non_metadata_resource_reference_target_name_top_counts"
        ]
        == {"path_b.prefab": 1}
    )
    assert (
        merged["summary"]["experimental_length_change_placement_rebuild_probe_selected_offset_candidate_count"] == 5
    )
    assert (
        merged["summary"]["experimental_length_change_placement_rebuild_probe_selected_non_overlapping_count"] == 4
    )
    assert (
        merged["summary"]["experimental_length_change_placement_rebuild_probe_selected_overlapping_count"] == 1
    )
    assert (
        merged["summary"]["experimental_length_change_placement_rebuild_probe_selected_target_role_kind_counts"]
        == {
            "member_name|string_length_prefix": 3,
            "resource_reference|string_end": 2,
        }
    )
    assert (
        merged["summary"]["experimental_length_change_placement_rebuild_probe_selected_owner_kind_target_counts"]
        == {
            "outside_member_descriptor|member_name|string_length_prefix": 3,
            "outside_member_descriptor|resource_reference|string_end": 2,
        }
    )
    detail_counts = merged["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["resource_effective_remap_preserved_raw_exclusion_passed_rows"] == 1
    assert detail_counts["resource_effective_remap_strict_passed_rows"] == 0
    assert detail_counts["resource_effective_remap_none_rows"] == 0
    assert detail_counts["resource_length_probe_changed_only_expected_passed_rows"] == 0
    assert detail_counts["resource_length_probe_changed_only_effective_expected_passed_rows"] == 1
    assert detail_counts["resource_length_probe_effective_expected_missing_rows"] == 0
    assert detail_counts["resource_length_probe_effective_remap_missing_rows"] == 0
    assert detail_counts["resource_length_probe_non_skipped_rows"] == 1
    assert detail_counts["placement_effective_remap_preserved_raw_exclusion_passed_rows"] == 1
    assert detail_counts["placement_effective_remap_strict_passed_rows"] == 0
    assert detail_counts["placement_effective_remap_none_rows"] == 0
    assert detail_counts["placement_length_probe_changed_only_expected_passed_rows"] == 0
    assert detail_counts["placement_length_probe_changed_only_effective_expected_passed_rows"] == 1
    assert detail_counts["placement_length_probe_effective_expected_missing_rows"] == 0
    assert detail_counts["placement_length_probe_effective_remap_missing_rows"] == 0
    assert detail_counts["placement_length_probe_non_skipped_rows"] == 1
    assert merged["gate"]["resource_resize_offset_gate_ready"] is False
    assert merged["gate"]["placement_resize_offset_gate_ready"] is False
    assert merged["gate"]["resize_offset_validator_ready"] is False
    assert merged["gate"]["resource_effective_resize_offset_model_ready"] is True
    assert merged["gate"]["placement_effective_resize_offset_model_ready"] is True
    assert merged["gate"]["effective_resize_offset_model_ready"] is True


def test_prefab_corpus_report_merge_counts_missing_effective_remap_status_as_none() -> None:
    report = {
        "format": PREFAB_JSON_IMPORT_CORPUS_FORMAT,
        "source_type": "loose_files",
        "source_paths": ["fixture"],
        "summary": {
            "files_discovered": 1,
            "files_scanned": 1,
            "scan_offset": 0,
            "scan_count": 1,
            "edit_probes_enabled": True,
            "discovery_limited": False,
        },
        "rows": [
            {
                "path": "fixture.prefab",
                "experimental_length_change_placement_rebuild_probe": {
                    "status": "failed",
                    "offset_candidate_remap_missing_count": 1,
                },
            }
        ],
    }

    merged = merge_prefab_json_import_corpus_reports([report])

    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_report_only_effective_remap_status_counts"
        ]
        == {"none": 1}
    )
    assert (
        merged["summary"][
            "experimental_length_change_placement_rebuild_probe_status_effective_remap_status_counts"
        ]
        == {"failed|none": 1}
    )
    assert (
        merged["gate"]["length_changing_blocker_detail_counts"]["placement_effective_remap_none_rows"] == 1
    )
    detail_counts = merged["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["placement_length_probe_effective_expected_missing_rows"] == 1
    assert detail_counts["placement_length_probe_effective_remap_missing_rows"] == 1
    assert detail_counts["placement_length_probe_non_skipped_rows"] == 1


def test_prefab_corpus_report_computes_descriptor_count_gate_from_semantic_probes() -> None:
    semantic_probe = {
        "status": "passed",
        "changed_only_expected_bytes": True,
        "layout_fully_accounted_after_edit": True,
        "no_edit_rebuild_after_edit": True,
        "json_no_edit_roundtrip_after_edit": True,
        "json_layout_rebuild_after_edit": True,
        "member_identity_preserved": True,
        "semantics_proven": True,
    }
    report = {
        "format": PREFAB_JSON_IMPORT_CORPUS_FORMAT,
        "source_type": "loose_files",
        "source_paths": ["fixture"],
        "summary": {
            "files_discovered": 2,
            "files_scanned": 2,
            "scan_offset": 0,
            "scan_count": 2,
            "edit_probes_enabled": True,
            "discovery_limited": False,
        },
        "rows": [
            {
                "path": "array.prefab",
                "status": "passed",
                "layout_rebuild_byte_identical": True,
                "json_layout_rebuild_byte_identical": True,
                "report_only_array_count_hint_mutation_probe": {
                    **semantic_probe,
                    "decoded_count_hint_changed": True,
                },
            },
            {
                "path": "descriptor.prefab",
                "status": "passed",
                "layout_rebuild_byte_identical": True,
                "json_layout_rebuild_byte_identical": True,
                "report_only_descriptor_word3_mutation_probe": {
                    **semantic_probe,
                    "decoded_word3_changed": True,
                },
            },
        ],
    }

    merged = merge_prefab_json_import_corpus_reports([report])

    assert merged["gate"]["descriptor_count_semantics_proven"] is True
    assert merged["gate"]["array_count_hint_semantics_proven"] is True
    assert merged["gate"]["descriptor_word3_semantics_proven"] is True
    assert merged["gate"]["descriptor_count_mutation_proven"] is True
    assert merged["gate"]["descriptor_value_editing_ready"] is True
    assert merged["gate"]["length_changing_import_ready"] is False


def test_prefab_corpus_report_computes_transform_gate_from_layout_and_semantic_probe() -> None:
    report = {
        "format": PREFAB_JSON_IMPORT_CORPUS_FORMAT,
        "source_type": "loose_files",
        "source_paths": ["fixture"],
        "summary": {
            "files_discovered": 1,
            "files_scanned": 1,
            "scan_offset": 0,
            "scan_count": 1,
            "edit_probes_enabled": True,
            "discovery_limited": False,
        },
        "rows": [
            {
                "path": "transform.prefab",
                "status": "passed",
                "layout_rebuild_byte_identical": True,
                "json_layout_rebuild_byte_identical": True,
                "transform_member_count": 1,
                "decoded_transform_payload_value_rows": 1,
                "transform_members_without_payload_values": 0,
                "report_only_transform_word3_mutation_probe": {
                    "status": "passed",
                    "changed_only_expected_bytes": True,
                    "layout_fully_accounted_after_edit": True,
                    "no_edit_rebuild_after_edit": True,
                    "json_no_edit_roundtrip_after_edit": True,
                    "json_layout_rebuild_after_edit": True,
                    "decoded_word3_changed": True,
                    "member_identity_preserved": True,
                    "semantics_proven": True,
                },
            },
        ],
    }

    merged = merge_prefab_json_import_corpus_reports([report])

    assert merged["gate"]["transform_payload_layout_proven"] is True
    assert merged["gate"]["transform_value_semantics_proven"] is True
    assert merged["gate"]["transform_value_mutation_proven"] is True
    assert merged["gate"]["transform_value_editing_ready"] is True
    assert merged["gate"]["length_changing_import_ready"] is False


def test_prefab_corpus_report_computes_array_gate_from_layout_and_semantic_probe() -> None:
    report = {
        "format": PREFAB_JSON_IMPORT_CORPUS_FORMAT,
        "source_type": "loose_files",
        "source_paths": ["fixture"],
        "summary": {
            "files_discovered": 1,
            "files_scanned": 1,
            "scan_offset": 0,
            "scan_count": 1,
            "edit_probes_enabled": True,
            "discovery_limited": False,
        },
        "rows": [
            {
                "path": "array.prefab",
                "status": "passed",
                "layout_rebuild_byte_identical": True,
                "json_layout_rebuild_byte_identical": True,
                "array_member_count": 1,
                "decoded_array_payload_element_rows": 3,
                "array_members_without_payload_elements": 0,
                "report_only_array_count_hint_mutation_probe": {
                    "status": "passed",
                    "changed_only_expected_bytes": True,
                    "layout_fully_accounted_after_edit": True,
                    "no_edit_rebuild_after_edit": True,
                    "json_no_edit_roundtrip_after_edit": True,
                    "json_layout_rebuild_after_edit": True,
                    "decoded_count_hint_changed": True,
                    "member_identity_preserved": True,
                    "semantics_proven": True,
                },
            },
        ],
    }

    merged = merge_prefab_json_import_corpus_reports([report])

    assert merged["gate"]["array_payload_layout_proven"] is True
    assert merged["gate"]["array_count_mutation_proven"] is True
    assert merged["gate"]["array_resizing_ready"] is True
    assert merged["gate"]["length_changing_import_ready"] is False


def test_prefab_corpus_report_computes_unknown_reference_gate_from_semantic_probes() -> None:
    semantic_probe = {
        "status": "passed",
        "changed_only_expected_bytes": True,
        "layout_fully_accounted_after_edit": True,
        "no_edit_rebuild_after_edit": True,
        "json_no_edit_roundtrip_after_edit": True,
        "json_layout_rebuild_after_edit": True,
        "semantics_proven": True,
    }
    report = {
        "format": PREFAB_JSON_IMPORT_CORPUS_FORMAT,
        "source_type": "loose_files",
        "source_paths": ["fixture"],
        "summary": {
            "files_discovered": 2,
            "files_scanned": 2,
            "scan_offset": 0,
            "scan_count": 2,
            "edit_probes_enabled": True,
            "discovery_limited": False,
        },
        "rows": [
            {
                "path": "reference.prefab",
                "status": "passed",
                "layout_rebuild_byte_identical": True,
                "json_layout_rebuild_byte_identical": True,
                "report_only_reference_word3_mutation_probe": {
                    **semantic_probe,
                    "decoded_word3_changed": True,
                    "member_identity_preserved": True,
                },
            },
            {
                "path": "unknown.prefab",
                "status": "passed",
                "layout_rebuild_byte_identical": True,
                "json_layout_rebuild_byte_identical": True,
                "report_only_preserved_unknown_byte_mutation_probe": {
                    **semantic_probe,
                    "decoded_byte_changed": True,
                    "span_identity_preserved": True,
                },
            },
        ],
    }

    merged = merge_prefab_json_import_corpus_reports([report])

    assert merged["gate"]["reference_descriptor_edit_semantics_proven"] is True
    assert merged["gate"]["unknown_block_edit_semantics_proven"] is True
    assert merged["gate"]["unknown_reference_preservation_ready"] is True
    assert merged["gate"]["length_changing_import_ready"] is False


def test_prefab_corpus_report_computes_length_changing_gate_from_all_subgates() -> None:
    mutation_probe = {
        "status": "passed",
        "changed_only_expected_bytes": True,
        "layout_fully_accounted_after_edit": True,
        "no_edit_rebuild_after_edit": True,
        "json_no_edit_roundtrip_after_edit": True,
        "json_layout_rebuild_after_edit": True,
        "member_identity_preserved": True,
        "semantics_proven": True,
    }
    resize_probe = {
        "status": "passed",
        "offset_candidates_remapped_after_edit": True,
        "offset_candidates_effectively_remapped_after_edit": True,
        "resized_rebuild_changed_only_effective_expected_bytes": True,
        "offset_candidate_report_only_effective_remap_status": "strict_remap_passed",
    }
    report = {
        "format": PREFAB_JSON_IMPORT_CORPUS_FORMAT,
        "source_type": "loose_files",
        "source_paths": ["fixture"],
        "summary": {
            "files_discovered": 1,
            "files_scanned": 1,
            "scan_offset": 0,
            "scan_count": 1,
            "edit_probes_enabled": True,
            "discovery_limited": False,
        },
        "rows": [
            {
                "path": "ready.prefab",
                "status": "passed",
                "layout_rebuild_byte_identical": True,
                "json_layout_rebuild_byte_identical": True,
                "same_length_resource_edit_probe": {"status": "passed"},
                "same_length_placement_edit_probe": {"status": "passed"},
                "experimental_length_change_resource_rebuild_probe": resize_probe,
                "experimental_length_change_placement_rebuild_probe": resize_probe,
                "array_member_count": 1,
                "decoded_array_payload_element_rows": 1,
                "array_members_without_payload_elements": 0,
                "transform_member_count": 1,
                "decoded_transform_payload_value_rows": 1,
                "transform_members_without_payload_values": 0,
                "report_only_array_count_hint_mutation_probe": {
                    **mutation_probe,
                    "decoded_count_hint_changed": True,
                },
                "report_only_descriptor_word3_mutation_probe": {
                    **mutation_probe,
                    "decoded_word3_changed": True,
                },
                "report_only_transform_word3_mutation_probe": {
                    **mutation_probe,
                    "decoded_word3_changed": True,
                },
                "report_only_reference_word3_mutation_probe": {
                    **mutation_probe,
                    "decoded_word3_changed": True,
                },
                "report_only_preserved_unknown_byte_mutation_probe": {
                    **mutation_probe,
                    "decoded_byte_changed": True,
                    "span_identity_preserved": True,
                },
            },
        ],
    }

    merged = merge_prefab_json_import_corpus_reports([report])

    assert merged["gate"]["same_length_import_ready"] is True
    assert merged["gate"]["resize_offset_validator_ready"] is True
    assert merged["gate"]["effective_resize_offset_model_ready"] is True
    assert merged["gate"]["descriptor_value_editing_ready"] is True
    assert merged["gate"]["transform_value_editing_ready"] is True
    assert merged["gate"]["array_resizing_ready"] is True
    assert merged["gate"]["unknown_reference_preservation_ready"] is True
    assert merged["gate"]["length_changing_import_ready"] is True
    assert merged["gate"]["length_changing_failed_subgates"] == []
    assert merged["gate"]["length_changing_blockers"] == []


def test_prefab_corpus_report_skipped_length_change_probes_emit_none_effective_status(tmp_path: Path) -> None:
    (tmp_path / "empty.prefab").write_bytes(b"\xff\xff\x04\x00")

    report = build_prefab_json_import_corpus_report([tmp_path])
    row = report["rows"][0]

    resource_probe = row["experimental_length_change_resource_rebuild_probe"]
    placement_probe = row["experimental_length_change_placement_rebuild_probe"]
    assert resource_probe["status"] == "skipped"
    assert placement_probe["status"] == "skipped"
    assert resource_probe["offset_candidate_report_only_effective_remap_status"] == "none"
    assert placement_probe["offset_candidate_report_only_effective_remap_status"] == "none"
    assert resource_probe["offset_candidates_effectively_remapped_after_edit"] is False
    assert placement_probe["offset_candidates_effectively_remapped_after_edit"] is False
    assert resource_probe["resized_rebuild_changed_only_effective_expected_bytes"] is False
    assert placement_probe["resized_rebuild_changed_only_effective_expected_bytes"] is False
    assert (
        report["summary"][
            "experimental_length_change_resource_rebuild_probe_report_only_effective_remap_status_counts"
        ]
        == {"none": 1}
    )
    assert (
        report["summary"][
            "experimental_length_change_resource_rebuild_probe_status_effective_remap_status_counts"
        ]
        == {"skipped|none": 1}
    )
    assert (
        report["summary"][
            "experimental_length_change_resource_rebuild_probe_status_effective_expected_counts"
        ]
        == {"skipped|false": 1}
    )
    assert (
        report["summary"][
            "experimental_length_change_placement_rebuild_probe_report_only_effective_remap_status_counts"
        ]
        == {"none": 1}
    )
    assert (
        report["summary"][
            "experimental_length_change_placement_rebuild_probe_status_effective_remap_status_counts"
        ]
        == {"skipped|none": 1}
    )
    assert (
        report["summary"][
            "experimental_length_change_placement_rebuild_probe_status_effective_expected_counts"
        ]
        == {"skipped|false": 1}
    )
    detail_counts = report["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["resource_length_probe_no_safe_candidate_skipped_rows"] == 1
    assert detail_counts["placement_length_probe_no_safe_candidate_skipped_rows"] == 1
    assert detail_counts["resource_length_probe_edit_probes_disabled_skipped_rows"] == 0
    assert detail_counts["placement_length_probe_edit_probes_disabled_skipped_rows"] == 0
    assert detail_counts["resource_length_probe_overlap_ambiguous_skipped_rows"] == 0
    assert detail_counts["resource_effective_remap_none_rows"] == 1
    assert detail_counts["placement_effective_remap_none_rows"] == 1
    assert report["gate"]["resource_effective_resize_offset_model_ready"] is False
    assert report["gate"]["placement_effective_resize_offset_model_ready"] is False
    assert report["gate"]["effective_resize_offset_model_ready"] is False


def test_prefab_corpus_report_merge_rejects_coverage_gap(tmp_path: Path) -> None:
    _write_prefab(tmp_path / "a.prefab", "test_a")
    _write_prefab(tmp_path / "b.prefab", "test_b")

    second = build_prefab_json_import_corpus_report(
        [tmp_path],
        scan_offset=1,
        scan_count=1,
        include_edit_probes=False,
    )

    merged = merge_prefab_json_import_corpus_reports([second])

    assert merged["summary"]["files_discovered"] == 2
    assert merged["summary"]["files_scanned"] == 1
    assert merged["summary"]["coverage_complete"] is False
    assert merged["summary"]["coverage_errors"]
    assert merged["summary"]["all_discovered_files_scanned"] is False
    assert merged["gate"]["full_corpus_no_edit_rebuild_ready"] is False
    detail_counts = merged["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["full_corpus_no_edit_missing_rows"] == 1
    assert "full-corpus no-edit rebuild has not been run" in merged["gate"]["length_changing_blockers"]


def test_prefab_corpus_report_merge_preserves_discovery_limit_flag(tmp_path: Path) -> None:
    _write_prefab(tmp_path / "a.prefab", "test_a")
    _write_prefab(tmp_path / "b.prefab", "test_b")

    bounded = build_prefab_json_import_corpus_report(
        [tmp_path],
        discovery_limit=1,
        include_edit_probes=False,
    )

    merged = merge_prefab_json_import_corpus_reports([bounded])

    assert merged["summary"]["discovery_limited"] is True
    assert merged["summary"]["coverage_complete"] is False
    assert merged["summary"]["coverage_errors"] == [
        "Report 0 used discovery_limit and cannot prove full corpus coverage."
    ]
    assert merged["gate"]["full_corpus_no_edit_rebuild_ready"] is False
