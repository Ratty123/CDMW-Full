from __future__ import annotations

import bisect
import re
import struct
from collections import Counter
from pathlib import PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    AttachmentAnimationAliasPair,
    AttachmentAnimationAliasPlanResult,
    AttachmentEquipTypeRecord,
    AttachmentItemInfoBehaviorPatchResult,
    AttachmentItemInfoBehaviorRecord,
    AttachmentUniversalItemInfoBehaviorPatchResult,
)
from cdmw.core.archive_format import hashlittle
from cdmw.core.structured_binary_editor import parse_pabgh_table

_ATTACHMENT_ITEMINFO_MODEL_HASH_INIT = 0xC5EDE


def _attachment_length_prefixed_text_at(data: bytes, offset: int, *, max_length: int = 512) -> str:
    payload = bytes(data or b"")
    cursor = int(offset)
    if cursor < 0 or cursor + 4 > len(payload):
        return ""
    length = struct.unpack_from("<I", payload, cursor)[0]
    if length <= 0 or length > max_length:
        return ""
    start = cursor + 4
    end = start + int(length)
    if end > len(payload):
        return ""
    raw = payload[start:end].split(b"\x00", 1)[0]
    try:
        return raw.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def parse_attachment_equip_type_records(
    equiptype_data: bytes,
    equiptype_header_data: bytes,
) -> Tuple[AttachmentEquipTypeRecord, ...]:
    """Parse equiptypeinfo enough to map equip-type row hashes to names."""
    try:
        table = parse_pabgh_table(equiptype_header_data)
    except Exception:
        return ()
    payload = bytes(equiptype_data or b"")
    records: List[AttachmentEquipTypeRecord] = []
    for row in tuple(getattr(table, "rows", ()) or ()):
        row_offset = int(getattr(row, "offset", -1))
        if row_offset < 0 or row_offset >= len(payload):
            continue
        name = _attachment_length_prefixed_text_at(payload, row_offset, max_length=128)
        if not name:
            name = _attachment_length_prefixed_text_at(payload, row_offset + 4, max_length=128)
        if not name:
            continue
        records.append(
            AttachmentEquipTypeRecord(
                name=name,
                row_id=int(getattr(row, "row_id", 0) or 0) & 0xFFFFFFFF,
                row_index=int(getattr(row, "index", 0) or 0),
                row_offset=row_offset,
            )
        )
    return tuple(records)


def _attachment_model_hash_candidate_names(model_path: object) -> Tuple[str, ...]:
    path_text = str(model_path or "").replace("\\", "/").strip()
    if not path_text:
        return ()
    name = PurePosixPath(path_text).name.strip().casefold()
    if not name:
        return ()
    stems = {name}
    for suffix in (
        ".prefabdata.xml",
        ".prefabdata_xml",
        ".pamlod_xml",
        ".pac_xml",
        ".pam_xml",
        ".prefab",
        ".pamlod",
        ".pac",
        ".pam",
    ):
        if name.endswith(suffix):
            stems.add(name[: -len(suffix)])
    base_stems = {stem for stem in stems if stem}
    variant_suffixes = ("", "_r", "_l", "_in", "_r_in", "_l_in")
    names: List[str] = []
    for stem in sorted(base_stems):
        for suffix in variant_suffixes:
            candidate = stem if not suffix or stem.endswith(suffix) else f"{stem}{suffix}"
            if candidate and candidate not in names:
                names.append(candidate)
    return tuple(names)


def _attachment_model_hash_candidates(model_path: object) -> Tuple[int, ...]:
    hashes: List[int] = []
    for name in _attachment_model_hash_candidate_names(model_path):
        try:
            value = hashlittle(name.encode("ascii", errors="ignore"), _ATTACHMENT_ITEMINFO_MODEL_HASH_INIT)
        except Exception:
            continue
        if value not in hashes:
            hashes.append(value)
    return tuple(hashes)


def _attachment_pabgb_row_end(data: bytes, rows: Sequence[object], row_offset: int) -> int:
    payload_len = len(data or b"")
    later_offsets = sorted(
        int(getattr(row, "offset", -1))
        for row in tuple(rows or ())
        if int(getattr(row, "offset", -1)) > int(row_offset) and int(getattr(row, "offset", -1)) <= payload_len
    )
    return later_offsets[0] if later_offsets else payload_len


def _attachment_scan_iteminfo_equip_hits(
    row_data: bytes,
    row_offset: int,
    equip_records_by_hash: Mapping[int, AttachmentEquipTypeRecord],
) -> Tuple[Tuple[int, int, AttachmentEquipTypeRecord], ...]:
    hits: List[Tuple[int, int, AttachmentEquipTypeRecord]] = []
    seen: set[Tuple[int, int]] = set()
    payload = bytes(row_data or b"")
    for rel_offset in range(0, max(0, len(payload) - 3)):
        value = struct.unpack_from("<I", payload, rel_offset)[0]
        record = equip_records_by_hash.get(value)
        if not isinstance(record, AttachmentEquipTypeRecord):
            continue
        key = (value, row_offset + rel_offset)
        if key in seen:
            continue
        seen.add(key)
        hits.append((value, row_offset + rel_offset, record))
    return tuple(hits)


def _attachment_iteminfo_behavior_records_for_hashes(
    iteminfo_data: bytes,
    iteminfo_header_data: bytes,
    equip_records: Sequence[AttachmentEquipTypeRecord],
    model_hashes: Sequence[int],
) -> Tuple[Tuple[AttachmentItemInfoBehaviorRecord, ...], str]:
    try:
        table = parse_pabgh_table(iteminfo_header_data)
    except Exception as exc:
        return (), f"ItemInfo header could not be parsed: {exc}"
    payload = bytes(iteminfo_data or b"")
    wanted_hashes = tuple(dict.fromkeys(int(value) & 0xFFFFFFFF for value in tuple(model_hashes or ())))
    if not payload or not wanted_hashes:
        return (), "No ItemInfo data or model hashes were available."
    equip_records_by_hash = {
        int(record.row_id) & 0xFFFFFFFF: record
        for record in tuple(equip_records or ())
        if isinstance(record, AttachmentEquipTypeRecord) and int(record.row_id or 0)
    }
    if not equip_records_by_hash:
        return (), "EquipTypeInfo records were unavailable."

    rows = tuple(getattr(table, "rows", ()) or ())
    row_spans: List[Tuple[int, int, object]] = []
    for row in sorted(rows, key=lambda value: int(getattr(value, "offset", -1))):
        row_offset = int(getattr(row, "offset", -1))
        if row_offset < 0 or row_offset >= len(payload):
            continue
        row_spans.append((row_offset, len(payload), row))
    if not row_spans:
        return (), "No usable ItemInfo row offsets were found."
    row_spans = [
        (
            start,
            row_spans[index + 1][0] if index + 1 < len(row_spans) else len(payload),
            row,
        )
        for index, (start, _end, row) in enumerate(row_spans)
    ]
    row_starts = [start for start, _end, _row in row_spans]
    matched_hashes_by_row_index: Dict[int, List[int]] = {}
    row_by_index: Dict[int, Tuple[int, int, object]] = {}
    for model_hash in wanted_hashes:
        needle = struct.pack("<I", model_hash)
        search_at = 0
        while True:
            found_at = payload.find(needle, search_at)
            if found_at < 0:
                break
            span_index = bisect.bisect_right(row_starts, found_at) - 1
            if span_index >= 0:
                row_start, row_end, row = row_spans[span_index]
                if row_start <= found_at < row_end:
                    row_index = int(getattr(row, "index", 0) or 0)
                    row_by_index[row_index] = (row_start, row_end, row)
                    hits = matched_hashes_by_row_index.setdefault(row_index, [])
                    if model_hash not in hits:
                        hits.append(model_hash)
            search_at = found_at + 1

    records: List[AttachmentItemInfoBehaviorRecord] = []
    ambiguous_rows: List[str] = []
    for row_index in sorted(matched_hashes_by_row_index):
        row_offset, row_end, row = row_by_index[row_index]
        if row_end <= row_offset:
            continue
        row_data = payload[row_offset:row_end]
        matched_hashes = tuple(matched_hashes_by_row_index.get(row_index, ()))
        equip_hits = _attachment_scan_iteminfo_equip_hits(row_data, row_offset, equip_records_by_hash)
        if len(equip_hits) != 1:
            ambiguous_rows.append(
                f"row {row_index} has {len(equip_hits)} equip-type candidate(s)"
            )
            continue
        equip_hash, equip_offset, equip_record = equip_hits[0]
        item_id = 0
        if row_offset + 4 <= len(payload):
            item_id = struct.unpack_from("<I", payload, row_offset)[0]
        records.append(
            AttachmentItemInfoBehaviorRecord(
                item_id=item_id,
                internal_name=_attachment_length_prefixed_text_at(payload, row_offset + 4, max_length=512),
                row_index=row_index,
                row_offset=row_offset,
                row_end=row_end,
                model_hashes=wanted_hashes,
                matched_model_hashes=matched_hashes,
                equip_type_hash=equip_hash,
                equip_type_name=str(equip_record.name or ""),
                equip_type_offset=equip_offset,
            )
        )
    if records:
        return tuple(records), ""
    if ambiguous_rows:
        return (), "Ambiguous ItemInfo behavior row: " + "; ".join(ambiguous_rows[:4])
    return (), "No ItemInfo row matched the selected model hash candidates."


def resolve_attachment_iteminfo_behavior_record(
    iteminfo_data: bytes,
    iteminfo_header_data: bytes,
    equip_records: Sequence[AttachmentEquipTypeRecord],
    model_path: object,
) -> Tuple[Optional[AttachmentItemInfoBehaviorRecord], str]:
    """Resolve one ItemInfo row by selected PAC/prefab stem hash candidates."""
    records, reason = _attachment_iteminfo_behavior_records_for_hashes(
        iteminfo_data,
        iteminfo_header_data,
        equip_records,
        _attachment_model_hash_candidates(model_path),
    )
    if not records:
        return None, reason
    if len(records) > 1:
        names = ", ".join(
            f"{record.row_index}:{record.internal_name or record.item_id}"
            for record in records[:6]
        )
        return None, f"ItemInfo model hash matched multiple rows: {names}"
    return records[0], ""


def _attachment_equip_type_name_for_weapon_class(weapon_class: object) -> str:
    normalized = str(weapon_class or "").strip().casefold()
    mapping = {
        "onehand_sword": "OneHandSword",
        "twohand_sword": "TwoHandSword",
        "onehand_dagger": "OneHandDagger",
    }
    return mapping.get(normalized, "")


def _attachment_behavior_family(value: object) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    for token, family in (
        ("sword", "sword"),
        ("dagger", "dagger"),
        ("axe", "axe"),
        ("mace", "mace"),
        ("spear", "spear"),
        ("hammer", "hammer"),
        ("scythe", "scythe"),
        ("rod", "rod"),
        ("cannon", "cannon"),
        ("thrower", "thrower"),
        ("wand", "wand"),
    ):
        if token in text:
            return family
    return text


def build_iteminfo_behavior_equip_type_patch(
    iteminfo_data: bytes,
    iteminfo_header_data: bytes,
    equiptype_data: bytes,
    equiptype_header_data: bytes,
    *,
    target_model_path: str,
    source_model_path: str = "",
    target_weapon_class: str = "",
    source_weapon_class: str = "",
    source_equip_type_name: str = "",
) -> AttachmentItemInfoBehaviorPatchResult:
    """Patch only ItemInfo._equipTypeInfo u32 for full 1H/2H behavior swaps."""
    payload = bytes(iteminfo_data or b"")
    equip_records = parse_attachment_equip_type_records(equiptype_data, equiptype_header_data)
    target_record, target_reason = resolve_attachment_iteminfo_behavior_record(
        payload,
        iteminfo_header_data,
        equip_records,
        target_model_path,
    )
    if not isinstance(target_record, AttachmentItemInfoBehaviorRecord):
        return AttachmentItemInfoBehaviorPatchResult(
            data=payload,
            blocking_reason=f"Full behavior swap needs a resolved target ItemInfo row. {target_reason}",
        )

    equip_records_by_name = {
        str(record.name or "").strip().casefold(): record
        for record in equip_records
        if isinstance(record, AttachmentEquipTypeRecord) and str(record.name or "").strip()
    }
    source_record: Optional[AttachmentItemInfoBehaviorRecord] = None
    source_reason = ""
    if source_model_path:
        source_record, source_reason = resolve_attachment_iteminfo_behavior_record(
            payload,
            iteminfo_header_data,
            equip_records,
            source_model_path,
        )

    requested_source_name = str(source_equip_type_name or "").strip()
    if not requested_source_name and isinstance(source_record, AttachmentItemInfoBehaviorRecord):
        requested_source_name = source_record.equip_type_name
    if not requested_source_name:
        requested_source_name = _attachment_equip_type_name_for_weapon_class(source_weapon_class)
    source_equip_record = equip_records_by_name.get(requested_source_name.casefold())
    if not isinstance(source_equip_record, AttachmentEquipTypeRecord):
        reason = source_reason if source_reason else "No source equip-type name was resolved."
        return AttachmentItemInfoBehaviorPatchResult(
            data=payload,
            target_record=target_record,
            source_record=source_record,
            old_equip_type_name=target_record.equip_type_name,
            old_equip_type_hash=target_record.equip_type_hash,
            blocking_reason=f"Full behavior swap needs a resolved source equip type. {reason}",
        )

    target_family = _attachment_behavior_family(target_record.equip_type_name or target_weapon_class)
    source_family = _attachment_behavior_family(source_equip_record.name or source_weapon_class)
    if target_family and source_family and target_family != source_family:
        return AttachmentItemInfoBehaviorPatchResult(
            data=payload,
            target_record=target_record,
            source_record=source_record,
            old_equip_type_name=target_record.equip_type_name,
            new_equip_type_name=source_equip_record.name,
            old_equip_type_hash=target_record.equip_type_hash,
            new_equip_type_hash=source_equip_record.row_id,
            blocking_reason=(
                "Full behavior swap is blocked for mixed weapon families: "
                f"{target_record.equip_type_name or target_weapon_class} -> {source_equip_record.name}."
            ),
        )

    patch_offset = int(target_record.equip_type_offset)
    if patch_offset < 0 or patch_offset + 4 > len(payload):
        return AttachmentItemInfoBehaviorPatchResult(
            data=payload,
            target_record=target_record,
            source_record=source_record,
            blocking_reason="Target ItemInfo equip-type offset is outside the table payload.",
        )
    old_hash = int(target_record.equip_type_hash) & 0xFFFFFFFF
    new_hash = int(source_equip_record.row_id) & 0xFFFFFFFF
    proof_lines = (
        f"target ItemInfo row {target_record.row_index} item {target_record.item_id} {target_record.internal_name or '-'}",
        f"source ItemInfo row {source_record.row_index} item {source_record.item_id} {source_record.internal_name or '-'}"
        if isinstance(source_record, AttachmentItemInfoBehaviorRecord)
        else f"source equip type resolved from class {source_weapon_class or '-'}",
        f"_equipTypeInfo u32 offset 0x{patch_offset:X}: 0x{old_hash:08X} {target_record.equip_type_name} -> 0x{new_hash:08X} {source_equip_record.name}",
    )
    if old_hash == new_hash:
        return AttachmentItemInfoBehaviorPatchResult(
            data=payload,
            target_record=target_record,
            source_record=source_record,
            old_equip_type_name=target_record.equip_type_name,
            new_equip_type_name=source_equip_record.name,
            old_equip_type_hash=old_hash,
            new_equip_type_hash=new_hash,
            patch_offset=patch_offset,
            changed=False,
            proof_lines=proof_lines,
        )
    patched = bytearray(payload)
    patched[patch_offset : patch_offset + 4] = struct.pack("<I", new_hash)
    return AttachmentItemInfoBehaviorPatchResult(
        data=bytes(patched),
        target_record=target_record,
        source_record=source_record,
        old_equip_type_name=target_record.equip_type_name,
        new_equip_type_name=source_equip_record.name,
        old_equip_type_hash=old_hash,
        new_equip_type_hash=new_hash,
        patch_offset=patch_offset,
        changed=True,
        proof_lines=proof_lines,
    )


def build_universal_twohand_sword_iteminfo_behavior_patch(
    iteminfo_data: bytes,
    iteminfo_header_data: bytes,
    equiptype_data: bytes,
    equiptype_header_data: bytes,
    *,
    source_equip_type_names: Sequence[str] = ("TwoHandSword", "TwoHandGiantSword"),
    target_equip_type_name: str = "OneHandSword",
) -> AttachmentUniversalItemInfoBehaviorPatchResult:
    """Patch every 2H sword ItemInfo._equipTypeInfo u32 to OneHandSword."""
    payload = bytes(iteminfo_data or b"")
    if not payload:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=str(target_equip_type_name or ""),
            source_equip_type_names=tuple(str(value or "") for value in tuple(source_equip_type_names or ())),
            blocking_reason="Universal 2H sword behavior needs iteminfo.pabgb data.",
        )
    try:
        table = parse_pabgh_table(iteminfo_header_data)
    except Exception as exc:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=str(target_equip_type_name or ""),
            source_equip_type_names=tuple(str(value or "") for value in tuple(source_equip_type_names or ())),
            blocking_reason=f"ItemInfo header could not be parsed: {exc}",
        )

    equip_records = parse_attachment_equip_type_records(equiptype_data, equiptype_header_data)
    equip_records_by_hash = {
        int(record.row_id) & 0xFFFFFFFF: record
        for record in tuple(equip_records or ())
        if isinstance(record, AttachmentEquipTypeRecord) and str(record.name or "").strip()
    }
    equip_records_by_name = {
        str(record.name or "").strip().casefold(): record
        for record in tuple(equip_records or ())
        if isinstance(record, AttachmentEquipTypeRecord) and str(record.name or "").strip()
    }
    clean_source_names = tuple(
        dict.fromkeys(str(value or "").strip() for value in tuple(source_equip_type_names or ()) if str(value or "").strip())
    )
    source_name_keys = {name.casefold() for name in clean_source_names}
    target_name = str(target_equip_type_name or "").strip()
    target_record = equip_records_by_name.get(target_name.casefold())
    if not equip_records_by_hash or not isinstance(target_record, AttachmentEquipTypeRecord):
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_name,
            source_equip_type_names=clean_source_names,
            blocking_reason=(
                "Universal 2H sword behavior needs EquipTypeInfo rows for "
                f"{target_name or 'OneHandSword'} and {', '.join(clean_source_names) or '2H swords'}."
            ),
        )
    missing_sources = [name for name in clean_source_names if name.casefold() not in equip_records_by_name]
    if missing_sources:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=int(target_record.row_id) & 0xFFFFFFFF,
            source_equip_type_names=clean_source_names,
            blocking_reason="EquipTypeInfo missing source sword type(s): " + ", ".join(missing_sources),
        )

    rows = tuple(getattr(table, "rows", ()) or ())
    usable_rows = sorted(
        (
            row
            for row in rows
            if 0 <= int(getattr(row, "offset", -1)) < len(payload)
        ),
        key=lambda row: int(getattr(row, "offset", -1)),
    )
    if not usable_rows:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=int(target_record.row_id) & 0xFFFFFFFF,
            source_equip_type_names=clean_source_names,
            blocking_reason="No usable ItemInfo row offsets were found.",
        )

    target_hash = int(target_record.row_id) & 0xFFFFFFFF
    patched = bytearray(payload)
    proof_lines: List[str] = []
    changed_offsets: List[int] = []
    changed_counts = Counter()
    ambiguous_source_rows: List[str] = []
    scanned_rows = 0
    rows_with_single_equip_hit = 0

    for index, row in enumerate(usable_rows):
        row_offset = int(getattr(row, "offset", -1))
        next_offset = int(getattr(usable_rows[index + 1], "offset", len(payload))) if index + 1 < len(usable_rows) else len(payload)
        row_end = next_offset if row_offset < next_offset <= len(payload) else _attachment_pabgb_row_end(payload, usable_rows, row_offset)
        if row_end <= row_offset:
            continue
        scanned_rows += 1
        row_data = payload[row_offset:row_end]
        equip_hits = _attachment_scan_iteminfo_equip_hits(row_data, row_offset, equip_records_by_hash)
        if len(equip_hits) != 1:
            source_hits = [
                hit_record
                for _hit_hash, _hit_offset, hit_record in equip_hits
                if str(getattr(hit_record, "name", "") or "").strip().casefold() in source_name_keys
            ]
            if source_hits:
                row_index = int(getattr(row, "index", index) or index)
                row_id = int(getattr(row, "row_id", 0) or 0) & 0xFFFFFFFF
                names = ", ".join(str(record.name or "-") for record in source_hits[:4])
                ambiguous_source_rows.append(f"row {row_index} item {row_id}: {len(equip_hits)} equip candidates ({names})")
            continue
        rows_with_single_equip_hit += 1
        old_hash, patch_offset, old_record = equip_hits[0]
        old_name = str(getattr(old_record, "name", "") or "").strip()
        if old_name.casefold() not in source_name_keys:
            continue
        if patch_offset < 0 or patch_offset + 4 > len(patched):
            ambiguous_source_rows.append(
                f"row {int(getattr(row, 'index', index) or index)} item {int(getattr(row, 'row_id', 0) or 0)}: equip offset outside payload"
            )
            continue
        if (int(old_hash) & 0xFFFFFFFF) == target_hash:
            continue
        patched[patch_offset : patch_offset + 4] = struct.pack("<I", target_hash)
        changed_offsets.append(patch_offset)
        changed_counts[old_name] += 1
        item_id = 0
        if row_offset + 4 <= len(payload):
            item_id = struct.unpack_from("<I", payload, row_offset)[0]
        internal_name = _attachment_length_prefixed_text_at(payload, row_offset + 4, max_length=512)
        proof_lines.append(
            "row "
            f"{int(getattr(row, 'index', index) or index)} item {item_id} {internal_name or '-'} "
            f"_equipTypeInfo 0x{patch_offset:X}: 0x{int(old_hash) & 0xFFFFFFFF:08X} {old_name} -> "
            f"0x{target_hash:08X} {target_record.name}"
        )

    if ambiguous_source_rows:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=target_hash,
            source_equip_type_names=clean_source_names,
            changed_counts_by_source=tuple(sorted(changed_counts.items())),
            changed_offsets=tuple(changed_offsets),
            proof_lines=tuple(proof_lines),
            blocking_reason="Ambiguous ItemInfo source sword row(s); export blocked instead of guessing. "
            + "; ".join(ambiguous_source_rows[:6]),
        )
    if len(patched) != len(payload):
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=target_hash,
            source_equip_type_names=clean_source_names,
            changed_counts_by_source=tuple(sorted(changed_counts.items())),
            changed_offsets=tuple(changed_offsets),
            proof_lines=tuple(proof_lines),
            blocking_reason="Universal 2H sword behavior patch changed ItemInfo file length; export blocked.",
        )
    if not changed_offsets:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=target_hash,
            source_equip_type_names=clean_source_names,
            changed_counts_by_source=tuple(sorted(changed_counts.items())),
            proof_lines=(
                f"scanned {scanned_rows:,} ItemInfo row(s); {rows_with_single_equip_hit:,} row(s) had one equip-type candidate",
            ),
            blocking_reason="No TwoHandSword or TwoHandGiantSword ItemInfo rows were found to patch.",
        )

    summary_lines = (
        f"target equip type {target_record.name} hash 0x{target_hash:08X}",
        f"patched {len(changed_offsets):,} ItemInfo row(s); file length preserved at {len(payload):,} byte(s)",
        f"scanned {scanned_rows:,} ItemInfo row(s); {rows_with_single_equip_hit:,} row(s) had one equip-type candidate",
    )
    return AttachmentUniversalItemInfoBehaviorPatchResult(
        data=bytes(patched),
        target_equip_type_name=target_record.name,
        target_equip_type_hash=target_hash,
        source_equip_type_names=clean_source_names,
        changed_count=len(changed_offsets),
        changed_counts_by_source=tuple(sorted(changed_counts.items())),
        changed_offsets=tuple(changed_offsets),
        proof_lines=summary_lines + tuple(proof_lines),
        changed=True,
    )


_UNIVERSAL_TWOHAND_SWORD_ITEMINFO_EQUIP_FAMILY_REL_OFFSET = 0x33
_UNIVERSAL_TWOHAND_SWORD_ITEMINFO_FAMILY_SIGNATURES_BY_SOURCE = {
    "TwoHandSword": bytes.fromhex("48 4A 0F 92 41 4A 0F 92 41"),
    "TwoHandGiantSword": bytes.fromhex("44 4A 0F 92 41 4A 0F 92 41"),
}
_UNIVERSAL_ONEHAND_SWORD_ITEMINFO_FAMILY_SIGNATURE = bytes.fromhex("38 A0 C9 39 BA A0 C9 39 BA")
_UNIVERSAL_TWOHAND_SWORD_ITEMINFO_ITEM_TYPES_BY_SOURCE = {
    "TwoHandSword": 0xCA,
    "TwoHandGiantSword": 0xDA,
}
_UNIVERSAL_ONEHAND_SWORD_ITEMINFO_ITEM_TYPE = 0x67
_UNIVERSAL_TWOHAND_SWORD_ITEMINFO_ITEM_TYPE_SEARCH_REL_END = 0x90


def build_universal_twohand_sword_true_onehand_iteminfo_patch(
    iteminfo_data: bytes,
    iteminfo_header_data: bytes,
    equiptype_data: bytes,
    equiptype_header_data: bytes,
    *,
    source_equip_type_names: Sequence[str] = ("TwoHandSword", "TwoHandGiantSword"),
    target_equip_type_name: str = "OneHandSword",
) -> AttachmentUniversalItemInfoBehaviorPatchResult:
    """
    Patch 2H sword ItemInfo rows to the proven 1H sword equipment behavior shape.

    The earlier universal behavior patch changed only `_equipTypeInfo`. Current
    game data also carries a sword-family equipment signature and a compact
    item-type discriminator near that field. Leaving either 2H value behind can
    produce a mixed 1H/2H state, so this helper patches all three fields and
    blocks if the expected source values are not present exactly once.
    """
    payload = bytes(iteminfo_data or b"")
    if not payload:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=str(target_equip_type_name or ""),
            source_equip_type_names=tuple(str(value or "") for value in tuple(source_equip_type_names or ())),
            blocking_reason="Universal true 1H sword behavior needs iteminfo.pabgb data.",
        )
    try:
        table = parse_pabgh_table(iteminfo_header_data)
    except Exception as exc:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=str(target_equip_type_name or ""),
            source_equip_type_names=tuple(str(value or "") for value in tuple(source_equip_type_names or ())),
            blocking_reason=f"ItemInfo header could not be parsed: {exc}",
        )

    equip_records = parse_attachment_equip_type_records(equiptype_data, equiptype_header_data)
    equip_records_by_hash = {
        int(record.row_id) & 0xFFFFFFFF: record
        for record in tuple(equip_records or ())
        if isinstance(record, AttachmentEquipTypeRecord) and str(record.name or "").strip()
    }
    equip_records_by_name = {
        str(record.name or "").strip().casefold(): record
        for record in tuple(equip_records or ())
        if isinstance(record, AttachmentEquipTypeRecord) and str(record.name or "").strip()
    }
    clean_source_names = tuple(
        dict.fromkeys(str(value or "").strip() for value in tuple(source_equip_type_names or ()) if str(value or "").strip())
    )
    source_name_keys = {name.casefold() for name in clean_source_names}
    target_record = equip_records_by_name.get(str(target_equip_type_name or "").strip().casefold())
    if not equip_records_by_hash or not isinstance(target_record, AttachmentEquipTypeRecord):
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=str(target_equip_type_name or "").strip(),
            source_equip_type_names=clean_source_names,
            blocking_reason=(
                "Universal true 1H sword behavior needs EquipTypeInfo rows for "
                f"{target_equip_type_name or 'OneHandSword'} and {', '.join(clean_source_names) or '2H swords'}."
            ),
        )
    missing_sources = [name for name in clean_source_names if name.casefold() not in equip_records_by_name]
    if missing_sources:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=int(target_record.row_id) & 0xFFFFFFFF,
            source_equip_type_names=clean_source_names,
            blocking_reason="EquipTypeInfo missing source sword type(s): " + ", ".join(missing_sources),
        )

    rows = tuple(getattr(table, "rows", ()) or ())
    usable_rows = sorted(
        (
            row
            for row in rows
            if 0 <= int(getattr(row, "offset", -1)) < len(payload)
        ),
        key=lambda row: int(getattr(row, "offset", -1)),
    )
    if not usable_rows:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=int(target_record.row_id) & 0xFFFFFFFF,
            source_equip_type_names=clean_source_names,
            blocking_reason="No usable ItemInfo row offsets were found.",
        )

    target_hash = int(target_record.row_id) & 0xFFFFFFFF
    patched = bytearray(payload)
    proof_lines: List[str] = []
    changed_offsets: List[int] = []
    changed_counts = Counter()
    blocking_rows: List[str] = []
    scanned_rows = 0
    rows_with_single_equip_hit = 0

    for index, row in enumerate(usable_rows):
        row_offset = int(getattr(row, "offset", -1))
        next_offset = int(getattr(usable_rows[index + 1], "offset", len(payload))) if index + 1 < len(usable_rows) else len(payload)
        row_end = next_offset if row_offset < next_offset <= len(payload) else _attachment_pabgb_row_end(payload, usable_rows, row_offset)
        if row_end <= row_offset:
            continue
        scanned_rows += 1
        row_data = payload[row_offset:row_end]
        equip_hits = _attachment_scan_iteminfo_equip_hits(row_data, row_offset, equip_records_by_hash)
        source_hits = [
            (hit_hash, hit_offset, hit_record)
            for hit_hash, hit_offset, hit_record in equip_hits
            if str(getattr(hit_record, "name", "") or "").strip().casefold() in source_name_keys
        ]
        if len(equip_hits) != 1:
            if source_hits:
                row_index = int(getattr(row, "index", index) or index)
                row_id = int(getattr(row, "row_id", 0) or 0) & 0xFFFFFFFF
                names = ", ".join(str(record.name or "-") for _hash, _offset, record in source_hits[:4])
                blocking_rows.append(f"row {row_index} item {row_id}: {len(equip_hits)} equip candidates ({names})")
            continue
        rows_with_single_equip_hit += 1
        old_hash, patch_offset, old_record = equip_hits[0]
        old_name = str(getattr(old_record, "name", "") or "").strip()
        if old_name.casefold() not in source_name_keys:
            continue
        expected_signature = _UNIVERSAL_TWOHAND_SWORD_ITEMINFO_FAMILY_SIGNATURES_BY_SOURCE.get(old_name)
        if not expected_signature:
            blocking_rows.append(f"row {int(getattr(row, 'index', index) or index)}: no signature rule for {old_name}")
            continue
        expected_item_type = _UNIVERSAL_TWOHAND_SWORD_ITEMINFO_ITEM_TYPES_BY_SOURCE.get(old_name)
        if expected_item_type is None:
            blocking_rows.append(f"row {int(getattr(row, 'index', index) or index)}: no item-type rule for {old_name}")
            continue
        signature_offset = patch_offset + _UNIVERSAL_TWOHAND_SWORD_ITEMINFO_EQUIP_FAMILY_REL_OFFSET
        if patch_offset < 0 or patch_offset + 4 > len(patched):
            blocking_rows.append(
                f"row {int(getattr(row, 'index', index) or index)} item {int(getattr(row, 'row_id', 0) or 0)}: equip offset outside payload"
            )
            continue
        if signature_offset < row_offset or signature_offset + len(expected_signature) > row_end:
            blocking_rows.append(
                f"row {int(getattr(row, 'index', index) or index)} item {int(getattr(row, 'row_id', 0) or 0)}: equip signature outside row"
            )
            continue
        actual_signature = payload[signature_offset : signature_offset + len(expected_signature)]
        if actual_signature != expected_signature:
            blocking_rows.append(
                f"row {int(getattr(row, 'index', index) or index)} item {int(getattr(row, 'row_id', 0) or 0)} "
                f"{old_name}: expected signature {expected_signature.hex()} at 0x{signature_offset:X}, found {actual_signature.hex()}"
            )
            continue
        item_type_window_start = signature_offset + len(expected_signature)
        item_type_window_end = min(
            row_end,
            patch_offset + _UNIVERSAL_TWOHAND_SWORD_ITEMINFO_ITEM_TYPE_SEARCH_REL_END,
        )
        item_type_hits: List[int] = []
        item_type_bytes = struct.pack("<I", int(expected_item_type) & 0xFFFFFFFF)
        search_at = item_type_window_start
        while search_at + 4 <= item_type_window_end:
            found_at = payload.find(item_type_bytes, search_at, item_type_window_end)
            if found_at < 0 or found_at + 4 > item_type_window_end:
                break
            item_type_hits.append(found_at)
            search_at = found_at + 1
        if len(item_type_hits) != 1:
            blocking_rows.append(
                f"row {int(getattr(row, 'index', index) or index)} item {int(getattr(row, 'row_id', 0) or 0)} "
                f"{old_name}: expected one item-type 0x{int(expected_item_type) & 0xFFFFFFFF:08X} "
                f"between 0x{item_type_window_start:X} and 0x{item_type_window_end:X}, found {len(item_type_hits)}"
            )
            continue
        item_type_offset = item_type_hits[0]

        patched[patch_offset : patch_offset + 4] = struct.pack("<I", target_hash)
        patched[signature_offset : signature_offset + len(expected_signature)] = _UNIVERSAL_ONEHAND_SWORD_ITEMINFO_FAMILY_SIGNATURE
        patched[item_type_offset : item_type_offset + 4] = struct.pack(
            "<I",
            _UNIVERSAL_ONEHAND_SWORD_ITEMINFO_ITEM_TYPE,
        )
        changed_offsets.extend((patch_offset, signature_offset, item_type_offset))
        changed_counts[old_name] += 1
        item_id = 0
        if row_offset + 4 <= len(payload):
            item_id = struct.unpack_from("<I", payload, row_offset)[0]
        internal_name = _attachment_length_prefixed_text_at(payload, row_offset + 4, max_length=512)
        proof_lines.append(
            "row "
            f"{int(getattr(row, 'index', index) or index)} item {item_id} {internal_name or '-'} "
            f"_equipTypeInfo 0x{patch_offset:X}: 0x{int(old_hash) & 0xFFFFFFFF:08X} {old_name} -> "
            f"0x{target_hash:08X} {target_record.name}; 9-byte sword family 0x{signature_offset:X}: "
            f"{expected_signature.hex()} -> {_UNIVERSAL_ONEHAND_SWORD_ITEMINFO_FAMILY_SIGNATURE.hex()}; "
            f"_itemType 0x{item_type_offset:X}: 0x{int(expected_item_type) & 0xFFFFFFFF:08X} -> "
            f"0x{_UNIVERSAL_ONEHAND_SWORD_ITEMINFO_ITEM_TYPE:08X}"
        )

    if blocking_rows:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=target_hash,
            source_equip_type_names=clean_source_names,
            changed_counts_by_source=tuple(sorted(changed_counts.items())),
            changed_offsets=tuple(changed_offsets),
            proof_lines=tuple(proof_lines),
            blocking_reason="Universal true 1H ItemInfo patch blocked instead of guessing. " + "; ".join(blocking_rows[:6]),
        )
    if len(patched) != len(payload):
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=target_hash,
            source_equip_type_names=clean_source_names,
            changed_counts_by_source=tuple(sorted(changed_counts.items())),
            changed_offsets=tuple(changed_offsets),
            proof_lines=tuple(proof_lines),
            blocking_reason="Universal true 1H ItemInfo patch changed ItemInfo file length; export blocked.",
        )
    if not changed_offsets:
        return AttachmentUniversalItemInfoBehaviorPatchResult(
            data=payload,
            target_equip_type_name=target_record.name,
            target_equip_type_hash=target_hash,
            source_equip_type_names=clean_source_names,
            changed_counts_by_source=tuple(sorted(changed_counts.items())),
            proof_lines=(
                f"scanned {scanned_rows:,} ItemInfo row(s); {rows_with_single_equip_hit:,} row(s) had one equip-type candidate",
            ),
            blocking_reason="No TwoHandSword or TwoHandGiantSword ItemInfo rows were found to patch.",
        )

    summary_lines = (
        f"target equip type {target_record.name} hash 0x{target_hash:08X}",
        "patched ItemInfo _equipTypeInfo plus the 9-byte one-hand sword family signature and _itemType",
        f"patched {sum(changed_counts.values()):,} ItemInfo row(s); file length preserved at {len(payload):,} byte(s)",
        f"scanned {scanned_rows:,} ItemInfo row(s); {rows_with_single_equip_hit:,} row(s) had one equip-type candidate",
    )
    return AttachmentUniversalItemInfoBehaviorPatchResult(
        data=bytes(patched),
        target_equip_type_name=target_record.name,
        target_equip_type_hash=target_hash,
        source_equip_type_names=clean_source_names,
        changed_count=sum(changed_counts.values()),
        changed_counts_by_source=tuple(sorted(changed_counts.items())),
        changed_offsets=tuple(changed_offsets),
        proof_lines=summary_lines + tuple(proof_lines),
        changed=True,
    )


_ACTIONCHART_ASSET_REFERENCE_PATH_BYTES = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./-"
)


def _actionchart_asset_references_from_bytes(
    data: bytes,
    *,
    extensions: Sequence[str] = (".paa", ".motionblending"),
) -> Tuple[str, ...]:
    """Recover path-like actionchart references without rewriting the PAAC graph."""
    payload = bytes(data or b"")
    if not payload:
        return ()
    extension_bytes = sorted(
        (str(ext or "").strip().lower().encode("ascii", errors="ignore") for ext in tuple(extensions or ())),
        key=len,
        reverse=True,
    )
    refs: List[str] = []
    seen: set[str] = set()
    for ext in extension_bytes:
        if not ext:
            continue
        search_at = 0
        while True:
            found_at = payload.lower().find(ext, search_at)
            if found_at < 0:
                break
            end = found_at + len(ext)
            while end < len(payload) and payload[end] in _ACTIONCHART_ASSET_REFERENCE_PATH_BYTES:
                end += 1
            start = found_at - 1
            while start >= 0 and payload[start] in _ACTIONCHART_ASSET_REFERENCE_PATH_BYTES:
                start -= 1
            raw = payload[start + 1 : end].decode("ascii", errors="ignore").strip().strip("/")
            lowered = raw.casefold()
            prefix_offsets = [
                offset
                for offset in (
                    lowered.find(prefix)
                    for prefix in (
                        "character/",
                        "1_pc/",
                        "2_pc/",
                        "2_mon/",
                        "1_phm/",
                        "2_phw/",
                        "phm_locomotion/",
                        "phw_locomotion/",
                        "phm/",
                        "phw/",
                        "cd_",
                    )
                )
                if offset >= 0
            ]
            if prefix_offsets:
                raw = raw[min(prefix_offsets) :].strip().strip("/")
            normalized = raw.replace("\\", "/").strip().strip("/")
            normalized_lower = normalized.casefold()
            if not normalized or normalized_lower in seen:
                search_at = found_at + 1
                continue
            if not any(normalized_lower.endswith(str(ext_text or "").casefold()) for ext_text in tuple(extensions or ())):
                search_at = found_at + 1
                continue
            seen.add(normalized_lower)
            refs.append(normalized)
            search_at = found_at + 1
    return tuple(refs)


def _normalize_actionchart_motion_reference_to_virtual_path(reference: object) -> str:
    text = str(reference or "").replace("\\", "/").strip().strip("/")
    if not text:
        return ""
    lowered = text.casefold()
    if lowered.endswith(".motionblending"):
        if lowered.startswith("character/"):
            return text
        return f"character/binary/motionblending/{text}".strip("/")
    if not lowered.endswith(".paa"):
        return ""
    if lowered.startswith("character/motion/"):
        return text
    if lowered.startswith(("1_phm/", "2_phw/")):
        text = f"1_pc/{text}"
    elif lowered.startswith("cd_"):
        text = f"1_pc/1_phm/{text}"
    return f"character/motion/{text}".strip("/")


def _universal_twohand_sword_motion_metadata_path(motion_virtual_path: object) -> str:
    text = str(motion_virtual_path or "").replace("\\", "/").strip().strip("/")
    lowered = text.casefold()
    prefix = "character/motion/"
    if not lowered.startswith(prefix) or not lowered.endswith(".paa"):
        return ""
    relative = text[len(prefix) : -len(".paa")]
    return f"actionchart/bin__/animmeta/{relative}.paa_metabin"


def _is_universal_twohand_sword_alias_target(path_text: object) -> bool:
    text = str(path_text or "").replace("\\", "/").strip().strip("/")
    lowered = text.casefold()
    if not any(token in lowered for token in ("longsword", "lswd", "lwsd")):
        return False
    if lowered.startswith("character/motion/1_pc/1_phm/"):
        # Keep this Kliff/PHM-focused. Oongka and monster branches are separate
        # animation families and should not be fed PHM one-hand sword clips.
        return "/00_mon/" not in lowered and "oongka" not in lowered
    if lowered.startswith("character/binary/motionblending/phm/"):
        return True
    if lowered.startswith("character/binary/motionblending/phm_locomotion/"):
        return True
    return False


def _is_universal_twohand_sword_combat_alias_target(path_text: object) -> bool:
    lowered = str(path_text or "").replace("\\", "/").strip().strip("/").casefold()
    if not lowered:
        return False
    basename = lowered.rsplit("/", 1)[-1]
    if any(token in basename for token in ("weapon_in", "weapon_out", "weaponin", "weaponout")):
        return False
    combat_tokens = (
        "_att_",
        "_counteratt_",
        "_skill_",
        "_def_",
        "_guard",
        "guard_",
        "_guard_",
        "parrying",
        "rebound",
        "justavoid",
        "_avoid_",
        "avoid_",
        "_roll_",
        "_rush_",
        "rush_move",
        "chargeatt",
        "_charge_",
        "thrust",
        "swing",
        "bash",
        "fin_lk",
        "longrangeatt",
        "jumpatt",
        "spinatt",
        "duel",
        "stealweapon",
        "swordwrestling",
        "mockery",
        "reflex",
        "downstap",
        "downthrust",
        "groundswing",
        "standup_move_swing",
    )
    return any(token in basename for token in combat_tokens)


def _is_universal_twohand_sword_passive_graph_reference(path_text: object) -> bool:
    lowered = str(path_text or "").replace("\\", "/").strip().strip("/").casefold()
    if not _is_universal_twohand_sword_alias_target(lowered):
        return False
    if _is_universal_twohand_sword_combat_alias_target(lowered):
        return False
    passive_tokens = (
        "stand_idle",
        "std_idle",
        "stand_to_",
        "stance",
        "weapon_out",
        "weapon_in",
        "weaponout",
        "weaponin",
        "idle_stop",
    )
    if not any(token in lowered for token in passive_tokens):
        return False
    return True


def _universal_twohand_sword_candidate_paths_for_target(path_text: object) -> Tuple[str, ...]:
    text = str(path_text or "").replace("\\", "/").strip().strip("/")
    lowered = text.casefold()
    candidates: List[str] = []

    def add(value: object) -> None:
        normalized = str(value or "").replace("\\", "/").strip().strip("/")
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    if lowered.endswith(".motionblending"):
        direct = text
        direct = re.sub("ride_lswd_upper", "ride_sword_upper", direct, flags=re.IGNORECASE)
        direct = re.sub("lswd_guard_stride_upper", "sword_guard_stride_upper", direct, flags=re.IGNORECASE)
        direct = re.sub("lswd_flash_signal", "sword_flash_signal", direct, flags=re.IGNORECASE)
        direct = re.sub("lswd_flash", "sword_flash", direct, flags=re.IGNORECASE)
        direct = re.sub("lswd_stride", "sword_stride", direct, flags=re.IGNORECASE)
        direct = re.sub("lswd_move_", "sword_move_", direct, flags=re.IGNORECASE)
        direct = re.sub("crouch_move_lv2_lswd", "crouch_move_lv2_sword", direct, flags=re.IGNORECASE)
        direct = re.sub("crouch_move_lv3_lswd", "crouch_move_lv3_sword", direct, flags=re.IGNORECASE)
        direct = re.sub("longsword", "sword", direct, flags=re.IGNORECASE)
        add(direct)
        return tuple(candidates)

    if not lowered.endswith(".paa"):
        return ()

    phm_motion_root = "character/motion/1_pc/1_phm/"
    exact_source_names_by_target_name = {
        # These pairs are present side-by-side in the PHM 2H sword upper graph.
        # Prefer them over generic lswd->swd replacement, which can pick shield
        # stance clips for in-place turns and leave traversal clips unresolved.
        "cd_phm_lswd_01_00_nor_std_turn90l_00.paa": ("cd_phm_sword_01_00_nor_stand_turn_90_l_000.paa",),
        "cd_phm_lswd_01_00_nor_std_turn90r_00.paa": ("cd_phm_sword_01_00_nor_stand_turn_90_r_000.paa",),
        "cd_phm_lswd_01_00_nor_std_turn180l_00.paa": ("cd_phm_sword_01_00_nor_stand_turn_180_l_000.paa",),
        "cd_phm_lswd_01_00_nor_std_turn180r_00.paa": ("cd_phm_sword_01_00_nor_stand_turn_180_r_000.paa",),
        "cd_phm_lswd_01_00_nor_move_run_turn90l_stt_00.paa": ("cd_phm_swd_00_01_nor_move_run_turn90l_stt_00.paa",),
        "cd_phm_lswd_01_00_nor_move_run_turn90r_stt_00.paa": ("cd_phm_swd_00_01_nor_move_run_turn90r_stt_00.paa",),
        "cd_phm_lswd_01_00_nor_move_run_turn180l_stt_00.paa": ("cd_phm_swd_00_01_nor_move_run_turn180l_stt_00.paa",),
        "cd_phm_lswd_01_00_nor_move_run_turn180r_stt_00.paa": ("cd_phm_swd_00_01_nor_move_run_turn180r_stt_00.paa",),
        "cd_phm_lswd_00_01_nor_base_move_walkfast_turn_180_l_r_00.paa": ("cd_phm_sword_00_01_normal_move_walkfast_turn_180_l_000.paa",),
        "cd_phm_lswd_00_01_nor_base_move_walkfast_turn_180_r_l_00.paa": ("cd_phm_sword_00_01_normal_move_walkfast_turn_180_r_000.paa",),
        "cd_phm_lswd_00_01_nor_base_move_run_turn_180_l_r_00.paa": ("cd_phm_sword_00_01_normal_move_run_turn_180_l_r_000.paa",),
        "cd_phm_lswd_00_01_nor_base_move_run_turn_180_r_l_00.paa": ("cd_phm_sword_00_01_normal_move_run_turn_180_r_l_000.paa",),
        "cd_phm_lswd_00_01_nor_base_move_runfast_turn_180_l_r_00.paa": ("cd_phm_sword_00_01_normal_move_runfast_turn_180_l_r_000.paa",),
        "cd_phm_lswd_00_01_nor_base_move_runfast_turn_180_r_l_00.paa": ("cd_phm_sword_00_01_normal_move_runfast_turn_180_r_l_000.paa",),
        "cd_phm_lswd_00_01_nor_base_move_runfast2_turn_180_l_r_00.paa": ("cd_phm_sword_00_01_normal_move_runfast2_turn_180_l_r_000.paa",),
        "cd_phm_lswd_00_01_nor_base_move_runfast2_turn_180_r_l_00.paa": ("cd_phm_sword_00_01_normal_move_runfast2_turn_180_r_l_000.paa",),
        "cd_phm_lswd_01_00_nor_move_walkfast_jump_f_m_stt_r_00.paa": ("cd_phm_swd_00_01_nor_move_walkfast_jump_f_m_stt_r_00.paa",),
        "cd_phm_lswd_01_00_nor_move_walkfast_jump_f_m_stt_l_00.paa": ("cd_phm_swd_00_01_nor_move_walkfast_jump_f_m_stt_l_00.paa",),
        "cd_phm_lswd_01_00_nor_move_walkfast_jump_f_m_end_r_00.paa": ("cd_phm_swd_00_01_nor_move_walkfast_jump_f_m_end_r_00.paa",),
        "cd_phm_lswd_01_00_nor_move_walkfast_jump_f_m_end_l_00.paa": ("cd_phm_swd_00_01_nor_move_walkfast_jump_f_m_end_l_00.paa",),
        "cd_phm_lswd_01_00_nor_move_run_jump_f_m_stt_r_00.paa": ("cd_phm_swd_00_01_nor_move_run_jump_f_m_stt_r_00.paa",),
        "cd_phm_lswd_01_00_nor_move_run_jump_f_m_stt_l_00.paa": ("cd_phm_swd_00_01_nor_move_run_jump_f_m_stt_l_00.paa",),
        "cd_phm_lswd_01_00_nor_move_run_jump_f_m_end_r_00.paa": ("cd_phm_swd_00_01_nor_move_run_jump_f_m_end_r_00.paa",),
        "cd_phm_lswd_01_00_nor_move_run_jump_f_m_end_l_00.paa": ("cd_phm_swd_00_01_nor_move_run_jump_f_m_end_l_00.paa",),
        "cd_phm_lswd_01_00_nor_move_run_jump_f_short_end_r_00.paa": ("cd_phm_swd_00_01_nor_move_run_jump_f_short_end_r_00.paa",),
        "cd_phm_lswd_01_00_nor_move_run_jump_f_short_end_l_00.paa": ("cd_phm_swd_00_01_nor_move_run_jump_f_short_end_l_00.paa",),
        "cd_phm_lswd_01_00_nor_move_runfast_jump_f_m_stt_r_00.paa": ("cd_phm_swd_00_01_nor_move_runfast_jump_f_m_stt_r_00.paa",),
        "cd_phm_lswd_01_00_nor_move_runfast_jump_f_m_stt_l_00.paa": ("cd_phm_swd_00_01_nor_move_runfast_jump_f_m_stt_l_00.paa",),
        "cd_phm_lswd_01_00_nor_move_runfast_jump_f_m_end_r_00.paa": ("cd_phm_swd_00_01_nor_move_runfast_jump_f_m_end_r_00.paa",),
        "cd_phm_lswd_01_00_nor_move_runfast_jump_f_m_end_l_00.paa": ("cd_phm_swd_00_01_nor_move_runfast_jump_f_m_end_l_00.paa",),
        "cd_phm_lswd_01_00_nor_move_runfast_jump_f_short_end_r_00.paa": ("cd_phm_swd_00_01_nor_move_runfast_jump_f_short_end_r_00.paa",),
        "cd_phm_lswd_01_00_nor_move_runfast_jump_f_short_end_l_00.paa": ("cd_phm_swd_00_01_nor_move_runfast_jump_f_short_end_l_00.paa",),
        "cd_phm_longsword_01_00_normal_move_runfast_jump_f_start_r_000.paa": ("cd_phm_basic_00_00_nor_move_runfast_jump_f_short_stt_r_00.paa",),
        "cd_phm_longsword_01_00_normal_move_runfast_jump_f_start_l_000.paa": ("cd_phm_basic_00_00_nor_move_runfast_jump_f_short_stt_l_00.paa",),
        "cd_phm_lswd_01_00_nor_std_jump_s_ing_00.paa": (
            "cd_phm_sword_00_00_normal_stand_jump_ing_000.paa",
            "cd_phm_basic_00_00_normal_stand_jump_ing_000.paa",
        ),
        "cd_phm_lswd_01_00_nor_std_jump_s_end_00.paa": ("cd_phm_swd_00_01_nor_std_jump_s_end_00.paa",),
        "cd_phm_lswd_01_00_freeclimb_move_f_stt_00.paa": ("cd_phm_basic_00_00_freeclimb_move_f_stt_00.paa",),
        "cd_phm_lswd_01_00_nor_move_jump_150_stt_r_00.paa": ("cd_phm_basic_00_00_nor_move_jump_150_stt_r_00.paa",),
        "cd_phm_lswd_01_00_nor_move_jump_150_stt_l_00.paa": ("cd_phm_basic_00_00_nor_move_jump_150_stt_l_00.paa",),
        "cd_phm_lswd_01_00_nor_move_jump_fall_stt_00.paa": ("cd_phm_basic_00_00_nor_move_jump_fall_stt_00.paa",),
        "cd_phm_lswd_01_00_nor_move_roll_f_standup_000.paa": ("cd_phm_swds_00_01_nor_move_roll_f_standup_00.paa",),
        "cd_phm_lswd_01_00_def_nor_guard_stt_00.paa": ("cd_phm_swd_01_01_def_nor_guard_stt_00.paa",),
        "cd_phm_lswd_01_00_def_nor_guard_end_00.paa": ("cd_phm_swd_01_01_def_nor_guard_end_00.paa",),
        "cd_phm_longsword_01_04_def_stand_idle_00.paa": ("cd_phm_swd_01_01_def_nor_guard_ing_00.paa",),
        "cd_phm_longsword_01_04_def_stand_to_0103nor_00.paa": ("cd_phm_swd_01_01_def_nor_guard_ing_00.paa",),
        "cd_phm_lswd_01_01_nor_def_std_guard_success_1_00.paa": ("cd_phm_swd_01_01_nor_def_std_guard_success_1_00.paa",),
        "cd_phm_lswd_01_01_nor_def_std_guard_success_2_00.paa": ("cd_phm_swd_01_01_nor_def_std_guard_success_2_00.paa",),
        "cd_phm_lswd_01_01_nor_def_std_guard_success_3_00.paa": ("cd_phm_swd_01_01_nor_def_std_guard_success_3_00.paa",),
        "cd_phm_lswd_01_01_nor_def_std_guard_success_4_00.paa": ("cd_phm_swd_01_01_nor_def_std_guard_success_4_00.paa",),
        "cd_phm_lswd_01_01_nor_def_std_guard_success_5_00.paa": ("cd_phm_swd_01_01_nor_def_std_guard_success_5_00.paa",),
        "cd_phm_lswd_01_01_nor_def_std_guard_success_6_00.paa": ("cd_phm_swd_01_01_nor_def_std_guard_success_6_00.paa",),
        "cd_phm_lswd_01_01_nor_def_std_guard_success_7_00.paa": ("cd_phm_swd_01_01_nor_def_std_guard_success_7_00.paa",),
        "cd_phm_lswd_01_01_nor_def_std_guard_success_8_00.paa": ("cd_phm_swd_01_01_nor_def_std_guard_success_8_00.paa",),
        "cd_phm_lswd_01_01_nor_def_std_guard_success_9_00.paa": ("cd_phm_swd_01_01_nor_def_std_guard_success_9_00.paa",),
        "cd_phm_longsword_01_04_att_com_a_1_move_f_swing_4_00.paa": ("cd_phm_sword_01_01_att_combo_a_1_move_f_swing_1_01.paa",),
        "cd_phm_longsword_01_04_att_com_a_2_move_f_swing_9_00.paa": ("cd_phm_sword_01_01_att_combo_a_2_move_f_swing_6_00.paa",),
        "cd_phm_longsword_01_04_att_com_a_3_move_f_swing_7_00.paa": ("cd_phm_sword_01_01_att_combo_a_3_move_f_swing_2_01.paa",),
        "cd_phm_longsword_01_04_att_com_a_4_move_f_swing_3_00.paa": ("cd_phm_sword_01_01_att_combo_g_3_move_f_swing_1_00.paa",),
        "cd_phm_longsword_01_01_att_skill_normal_combo_c_004.paa": ("cd_phm_sword_01_01_att_combo_c_003_move_f_handl_footl_thrust_05.paa",),
        "cd_phm_lswd_01_01_nor_att_coma_1_move_swing_00.paa": ("cd_phm_sword_01_01_att_combo_a_1_move_f_swing_1_01.paa",),
        "cd_phm_lswd_01_01_nor_att_comb_2_move_swing_00.paa": ("cd_phm_sword_01_01_att_combo_a_2_move_f_swing_6_00.paa",),
        "cd_phm_lswd_01_01_nor_att_comf_1_move_swing_00.paa": ("cd_phm_sword_01_01_att_combo_f_001_move_f_handr_footl_swing_01.paa",),
        "cd_phm_lswd_01_01_nor_att_comf_2_move_swing_3_00.paa": ("cd_phm_sword_01_01_att_combo_f_002_move_f_handr_footl_swing_06.paa",),
        "cd_phm_lswd_01_01_nor_att_comd_2_move_swing_00.paa": ("cd_phm_sword_01_01_att_combo_g_2_move_f_swing_3_00.paa",),
        "cd_phm_lswd_01_03_att_nor_fin_lk_coma_3_swing_00.paa": ("cd_phm_swd_01_01_att_fin_coma_3_lk_swing_01.paa",),
        "cd_phm_lswd_01_03_att_nor_fin_lk_coma_4_swing_00.paa": ("cd_phm_swds_01_01_att_nor_fin_lk_bashcoma_4_swing_00.paa",),
        "cd_phm_lswd_01_03_att_nor_fin_lk_runatt_1_swing_00.paa": ("cd_phm_sword_01_01_att_skill_dash_move_att_008.paa",),
        "cd_phm_longsword_01_04_att_move_run_f_end_swing_4_00.paa": ("cd_phm_sword_01_01_att_skill_dash_move_att_008.paa",),
        "cd_phm_longsword_01_03_att_nor_move_run_f_end_swing_1_00.paa": ("cd_phm_sword_01_01_skill_rush_move_f_end_000.paa",),
        "cd_phm_longsword_01_03_att_longrangeatt_f_handlr_footl_001.paa": ("cd_phm_sword_01_01_att_longrangeatt_001_move_f_handl_footl_swing_01.paa",),
        "cd_phm_lswd_01_03_att_nor_fin_lk_longrangeatt_1_swing_00.paa": ("cd_phm_swds_01_01_att_nor_fin_lk_longrangeatt_smash_00.paa",),
        "cd_phm_longsword_01_03_att_nor_move_f_swing_1_00.paa": ("cd_phm_sword_01_01_att_combo_h_1_move_f_swing_9_00.paa",),
        "cd_phm_lswd_01_03_att_nor_move_f_swing_4_02.paa": ("cd_phm_swds_01_01_att_nor_move_f_swing_4_00.paa",),
        "cd_phm_lswd_01_03_att_nor_move_f_swing_6_01.paa": ("cd_phm_swds_01_01_att_nor_move_f_swing_6_00.paa",),
        "cd_phm_lswd_01_03_att_nor_move_f_swing_6_02.paa": ("cd_phm_swds_01_01_att_nor_move_f_swing_6_00.paa",),
        "cd_phm_lswd_01_01_att_nor_move_f_swing_00.paa": ("cd_phm_axeshield_01_01_nor_att_nor_move_f_swing_00.paa",),
        "cd_phm_lswd_01_01_att_nor_move_f_swing_01.paa": ("cd_phm_sword_01_01_att_normal_move_010.paa",),
        "cd_phm_lswd_01_01_att_nor_move_b_swing_00.paa": ("cd_phm_axeshield_01_01_nor_att_nor_move_b_swing_00.paa",),
        "cd_phm_lswd_01_01_att_nor_move_b_swing_01.paa": ("cd_phm_sword_01_01_att_normal_move_011.paa",),
        "cd_phm_lswd_01_03_nor_att_move_f_jumpatt_smash_2_stt_00.paa": ("cd_phm_swds_01_01_att_nor_move_jump_end_swing_2_stt_00.paa",),
        "cd_phm_lswd_01_03_nor_att_move_f_jumpatt_smash_2_ing_00.paa": ("cd_phm_swds_01_01_att_nor_move_jump_end_swing_2_ing_00.paa",),
        "cd_phm_lswd_01_03_nor_att_move_f_jumpatt_smash_2_end_00.paa": ("cd_phm_swds_01_01_att_nor_move_jump_end_swing_2_end_00.paa",),
        "cd_phm_lswd_01_03_att_nor_move_f_spinatt_ing_00.paa": ("cd_phm_sword_01_01_att_combo_h_1_move_f_swing_9_00.paa",),
        "cd_phm_lswd_01_03_att_nor_move_f_spinatt_ing_01.paa": ("cd_phm_sword_01_01_att_combo_h_2_move_f_swing_2_00.paa",),
        "cd_phm_lswd_01_03_att_nor_move_f_spinatt_end_00.paa": ("cd_phm_sword_01_01_att_combo_g_3_move_f_swing_1_00.paa",),
        "cd_phm_lwsd_01_01_nor_att_rush_move_f_stt_00.paa": ("cd_phm_sword_01_01_skill_rush_move_f_start_000.paa",),
        "cd_phm_lwsd_01_01_nor_att_rush_move_f_ing_00.paa": ("cd_phm_sword_01_01_skill_rush_move_f_start_000.paa",),
        "cd_phm_lwsd_01_01_nor_att_rush_move_f_end_00.paa": ("cd_phm_sword_01_01_skill_rush_move_f_end_000.paa",),
        "cd_phm_lswd_01_01_nor_skill_chargeatt_move_bash_2_00.paa": ("cd_phm_sword_01_01_skill_move_jumpstep_bashatt_000.paa",),
        "cd_phm_lswd_01_03_att_nor_std_charge_00.paa": ("cd_phm_swd_01_01_def_nor_guard_ing_00.paa",),
        "cd_phm_lswd_01_03_nor_att_std_reflex_00.paa": ("cd_phm_swd_01_01_att_nor_std_reflex_01.paa",),
        "cd_phm_lswd_01_03_att_nor_move_f_downthrust_00.paa": ("cd_phm_sword_01_01_att_nor_move_f_downthrust_00.paa",),
        "cd_phm_longsword_01_03_att_nor_stand_downstap_thrust_2_00.paa": ("cd_phm_sword_01_01_att_nor_move_f_downthrust_00.paa",),
        "cd_phm_lswd_01_03_att_nor_move_roll_end_swing_00.paa": ("cd_phm_swd_01_01_att_nor_move_f_roll_swing_6_00.paa",),
        "cd_phm_longsword_01_04_att_standup_move_swing_4_00.paa": ("cd_phm_sword_01_01_skill_normal_standup_handr_footl_swing_04.paa",),
        "cd_phm_longsword_00_00_att_normal_skill_groundswing_01_move_f_handlr_footr_swing_03.paa": ("cd_phm_sword_01_01_att_nor_stepon_00.paa",),
        "cd_kliff_helldoglswd_01_01_att_nor_coma_1_move_f_swing_00.paa": ("cd_phm_sword_01_01_att_combo_a_1_move_f_swing_1_01.paa",),
        "cd_prh_lswd_01_01_nor_std_weapon_in_00.paa": ("00_riding/cd_prh_swd_01_01_nor_std_weapon_in_00.paa",),
    }
    for source_name in exact_source_names_by_target_name.get(lowered.rsplit("/", 1)[-1], ()):
        add(f"{phm_motion_root}{source_name}")

    if any(token in lowered for token in ("stand_weapon_out", "std_weapon_out", "std_weaponout")):
        if "sit_" in lowered:
            add("character/motion/1_pc/1_phm/cd_phm_swds_00_01_sit_std_weapon_out_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_out_000.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_out_004.paa")
    if "move_walkfast_f_weapon_out" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_move_walkfast_f_weapon_out_000.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_nor_move_walkfast_f_weapon_out_l_00.paa")
    if any(token in lowered for token in ("stand_weapon_in", "std_weapon_in", "std_weaponin")):
        if "sit_" in lowered:
            add("character/motion/1_pc/1_phm/cd_phm_swds_00_01_sit_std_weapon_in_00.paa")
        # Keep the normal 1H hip-sheath clip first. Longer numbered variants
        # are alternate stow poses and can put the sword in front of the body.
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_in_000.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_in_004.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_in_003.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_in_002.paa")
    if "move_walkfast_f_weapon_in" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_move_walkfast_f_weapon_in_000.paa")
    if "idle_stop" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_stand_idle_stop_r_000.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_stand_idle_000.paa")
    if "guard" in lowered or "_def_" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_idle_000.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_stand_idle_000.paa")
    if "sit_" not in lowered and any(
        token in lowered
        for token in ("normal_stand_idle", "noraml_stand_idle", "def_stand_idle", "stand_idle")
    ):
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_idle_000.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_stand_idle_000.paa")
    if "normal_move_walkfast_start_90_r" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_move_walkfast_start_90_r_000.paa")
    if "normal_move_walkfast_start_90_l" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_move_walkfast_start_90_l_000.paa")
    if "normal_move_walkfast_start_180_r" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_move_walkfast_turn_180_r_000.paa")
    if "normal_move_walkfast_start_180_l" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_move_walkfast_turn_180_l_000.paa")
    if "normal_move_walkfast_end_r" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_walkfast_f_endr_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_move_walk_f_end_r_000.paa")
    if "normal_move_walkfast_end_l" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_walkfast_f_endl_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_move_walk_f_end_l_000.paa")
    if "normal_move_run_f_ing" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_nor_move_run_f_ing_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_move_run_f_ing_000.paa")
    if "normal_move_run_f_end_r" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_run_f_endr_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_swd_01_01_nor_move_run_f_endr_00.paa")
    if "normal_move_run_f_end_l" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_run_f_endl_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_swd_01_01_nor_move_run_f_endl_00.paa")
    if "normal_move_runfast_f_ing" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_nor_move_runfast_f_ing_00.paa")
    if "normal_move_runfast_f_end_r" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_run_f_endr_00.paa")
    if "normal_move_runfast_f_end_l" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_run_f_endl_00.paa")
    if "move_walkfast_turn_180_l_r" in lowered or "move_walkfast_turn_180_l_l" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_nor_move_walkfast_f_180turn_l_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_walkfast_turn45l_00.paa")
    if "move_walkfast_turn_180_r_l" in lowered or "move_walkfast_turn_180_r_r" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_nor_move_walkfast_f_180turn_r_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_walkfast_turn45r_00.paa")
    if "move_run_turn_180_l_r" in lowered or "move_run_turn_180_l_l" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_nor_move_run_f_180turn_l_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_run_turn180l_stt_00.paa")
    if "move_run_turn_180_r_l" in lowered or "move_run_turn_180_r_r" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_nor_move_run_f_180turn_r_00.paa")
        add("character/motion/1_pc/1_phm/cd_phm_swd_00_01_nor_move_run_turn180r_stt_00.paa")
    if "move_runfast_turn_180_l_r" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_nor_move_runfast_f_180turn_l_00.paa")
    if "move_runfast_turn_180_r_l" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_nor_move_runfast_f_180turn_r_00.paa")

    family_variants = {text}
    for pattern, replacement in (
        ("longsword", "sword"),
        ("lswd", "swd"),
        ("lswd", "swds"),
        ("lswd", "sword"),
        ("lwsd", "swd"),
        ("lwsd", "swds"),
        ("lwsd", "sword"),
    ):
        family_variants.update(re.sub(pattern, replacement, value, flags=re.IGNORECASE) for value in tuple(family_variants))

    stance_variants = set(family_variants)
    for value in tuple(family_variants):
        for old, new in (("_01_00_", "_01_01_"), ("_01_03_", "_01_01_"), ("_01_04_", "_01_01_")):
            stance_variants.add(value.replace(old, new))
    for value in tuple(stance_variants):
        if "cd_phm_swd_" in value:
            add(value)
            add(value.replace("cd_phm_swd_", "cd_phm_swds_"))
            add(value.replace("cd_phm_swd_", "cd_phm_sword_"))
        elif "cd_phm_swds_" in value:
            add(value)
            add(value.replace("cd_phm_swds_", "cd_phm_swd_"))
            add(value.replace("cd_phm_swds_", "cd_phm_sword_"))
        elif "cd_phm_sword_" in value:
            add(value)
            add(value.replace("cd_phm_sword_", "cd_phm_swd_"))
            add(value.replace("cd_phm_sword_", "cd_phm_swds_"))
        else:
            add(value)

    # The 2H upper graph keeps these PHM longsword stance bridge clips next
    # to the matching 1H sword transition clips, but the names do not share
    # enough structure for the generic lswd/longsword replacement rules.
    if "cd_phm_longsword_01_00_nor_stand_to_0103nor_00.paa" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stance_change_01_01_002.paa")
    if (
        "cd_phm_longsword_01_03_nor_stand_to_0100nor_00.paa" in lowered
        or "cd_phm_longsword_01_03_nor_stand_to_0100nor_01.paa" in lowered
    ):
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_stand_idle_change_00_00_000.paa")
    if "cd_phm_longsword_01_04_def_stand_to_0103nor_00.paa" in lowered:
        add("character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stance_change_01_01_002.paa")

    if "sit_" not in lowered and any(token in lowered for token in ("normal_stand_idle", "noraml_stand_idle", "def_stand_idle", "stand_idle")):
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_stand_idle_000.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_stand_idle_001.paa")
        add("character/motion/1_pc/1_phm/cd_phm_sword_01_01_normal_stand_idle_002.paa")

    return tuple(candidates)


def build_universal_twohand_sword_animation_alias_plan(
    twohand_actionchart_data: bytes,
    ride_twohand_actionchart_data: bytes = b"",
    *,
    available_paths: Sequence[str],
    include_metadata: bool = True,
    include_combat_aliases: bool = False,
    longsword_actionchart_data: bytes = b"",
    weaponin_actionchart_data: bytes = b"",
) -> AttachmentAnimationAliasPlanResult:
    """Plan safe PHM 2H-sword motion aliases without copying PAAC graphs or ItemInfo."""
    available_by_key = {
        str(path or "").replace("\\", "/").strip().strip("/").casefold(): str(path or "").replace("\\", "/").strip().strip("/")
        for path in tuple(available_paths or ())
        if str(path or "").strip()
    }
    if not available_by_key:
        return AttachmentAnimationAliasPlanResult(blocking_reason="No original archive paths were available.")

    references: List[str] = []
    actionchart_payloads: Tuple[Tuple[bytes, bool], ...] = (
        (twohand_actionchart_data, False),
        (longsword_actionchart_data, True),
        (ride_twohand_actionchart_data, False),
        (weaponin_actionchart_data, False),
    )
    scanned_payload_count = sum(1 for payload, _passive_only in actionchart_payloads if payload)
    passive_filtered_count = 0
    combat_filtered_count = 0
    supplemental_reference_count = 0
    for payload, passive_only in actionchart_payloads:
        for reference in _actionchart_asset_references_from_bytes(payload, extensions=(".paa", ".motionblending")):
            virtual_path = _normalize_actionchart_motion_reference_to_virtual_path(reference)
            if (
                virtual_path
                and not include_combat_aliases
                and _is_universal_twohand_sword_combat_alias_target(virtual_path)
            ):
                combat_filtered_count += 1
                continue
            if passive_only and virtual_path and not _is_universal_twohand_sword_passive_graph_reference(virtual_path):
                passive_filtered_count += 1
                continue
            if virtual_path and virtual_path not in references:
                references.append(virtual_path)
    supplemental_targets = (
        # The mounted 2H stow clip is not consistently referenced by the 2H
        # ride upper graph, but the payload exists in the PHM motion archive.
        "character/motion/1_pc/1_phm/00_riding/cd_prh_lswd_01_01_nor_std_weapon_in_00.paa",
    )
    for target_path in supplemental_targets:
        target_key = target_path.casefold()
        if target_key in available_by_key and target_path not in references:
            references.append(target_path)
            supplemental_reference_count += 1

    pairs: List[AttachmentAnimationAliasPair] = []
    skipped: List[str] = []
    used_targets: set[str] = set()
    for target_path in references:
        target_key = target_path.casefold()
        if not _is_universal_twohand_sword_alias_target(target_path):
            continue
        if target_key not in available_by_key:
            skipped.append(target_path)
            continue
        source_path = ""
        for candidate in _universal_twohand_sword_candidate_paths_for_target(target_path):
            candidate_key = candidate.casefold()
            candidate_lower = candidate.casefold()
            if candidate_key == target_key or candidate_key not in available_by_key:
                continue
            if any(token in candidate_lower for token in ("longsword", "lswd", "lwsd", "twohand")):
                continue
            if candidate_lower.endswith(".paa") and not candidate_lower.startswith("character/motion/1_pc/1_phm/"):
                continue
            if candidate_lower.endswith(".motionblending") and not candidate_lower.startswith(
                (
                    "character/binary/motionblending/phm/",
                    "character/binary/motionblending/phm_locomotion/",
                )
            ):
                continue
            source_path = available_by_key[candidate_key]
            break
        if not source_path:
            skipped.append(target_path)
            continue
        if target_key not in used_targets:
            pairs.append(
                AttachmentAnimationAliasPair(
                    target_path=available_by_key[target_key],
                    source_path=source_path,
                    reason="PHM 2H sword motion uses matching 1H sword payload",
                )
            )
            used_targets.add(target_key)

        if include_metadata and target_path.casefold().endswith(".paa"):
            target_meta = _universal_twohand_sword_motion_metadata_path(target_path)
            source_meta = _universal_twohand_sword_motion_metadata_path(source_path)
            target_meta_key = target_meta.casefold()
            source_meta_key = source_meta.casefold()
            if (
                target_meta
                and source_meta
                and target_meta_key in available_by_key
                and source_meta_key in available_by_key
                and target_meta_key not in used_targets
            ):
                pairs.append(
                    AttachmentAnimationAliasPair(
                        target_path=available_by_key[target_meta_key],
                        source_path=available_by_key[source_meta_key],
                        reason="Matching PHM 2H sword animation metadata uses 1H sword metadata payload",
                    )
                )
                used_targets.add(target_meta_key)

    if not pairs:
        return AttachmentAnimationAliasPlanResult(
            skipped_paths=tuple(skipped[:64]),
            proof_lines=(f"scanned {len(references):,} actionchart asset reference(s)",),
            blocking_reason="No conservative PHM 2H sword -> 1H sword animation aliases could be resolved.",
        )
    motion_pairs = sum(1 for pair in pairs if pair.target_path.casefold().endswith(".paa"))
    metadata_pairs = sum(1 for pair in pairs if pair.target_path.casefold().endswith(".paa_metabin"))
    motionblend_pairs = sum(1 for pair in pairs if pair.target_path.casefold().endswith(".motionblending"))
    proof_lines = (
        f"planned {len(pairs):,} PHM animation alias payload(s)",
        f"{motion_pairs:,} .paa motion, {metadata_pairs:,} .paa_metabin metadata, {motionblend_pairs:,} .motionblending",
        f"scanned {len(references):,} actionchart asset reference(s) across {scanned_payload_count:,} graph(s); skipped {len(skipped):,} unresolved/non-PHM 2H reference(s)",
        f"filtered {combat_filtered_count:,} combat/guard alias reference(s) from the default stable package",
        f"filtered {passive_filtered_count:,} non-passive longsword_upper reference(s) from the crash-prone extended graph",
        f"added {supplemental_reference_count:,} supplemental mounted sheath reference(s)",
        "no actionchart .paac payloads and no ItemInfo tables are exported",
    )
    return AttachmentAnimationAliasPlanResult(
        pairs=tuple(pairs),
        skipped_paths=tuple(skipped[:64]),
        proof_lines=proof_lines,
    )
