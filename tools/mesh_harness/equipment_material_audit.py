"""Frozen catalogue and live-resolution contracts for the equipment material audit.

The audit deliberately separates the immutable Item Finder selection from the
live archive capture.  Item identity comes from one hash-pinned catalogue
generation; current PAMT/PAZ metadata is used only to resolve and render those
already-frozen logical identities.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cdmw.core.atomic_file import atomic_write_text


EQUIPMENT_AUDIT_CATALOGUE_SCHEMA = "cdmw_equipment_material_audit_catalogue_v1"
EQUIPMENT_AUDIT_SOURCE_SCHEMA_VERSION = 3
EQUIPMENT_AUDIT_ROOT_ID = "e8578fec566544cb54802d77"
EQUIPMENT_AUDIT_GENERATION_ID = "20260829154457899-2decae0c9e79"
EQUIPMENT_AUDIT_ARCHIVE_FINGERPRINT = (
    "14171155de0653e2126262f54c6fe3f3169dd2c2efe33b792a07d46ed7d4f449"
)
EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256 = (
    "5ce2c8e3d5c0e6b6836d9548045312a2b8df922a0cc13fe59e8daace015dc35e"
)
EQUIPMENT_AUDIT_ITEM_CATALOG_BYTES = 2_666_736
EQUIPMENT_AUDIT_SOURCE_ITEM_COUNT = 3_144
EQUIPMENT_AUDIT_ARMOR_RECORD_COUNT = 2_158
EQUIPMENT_AUDIT_SWORD_RECORD_COUNT = 62
EQUIPMENT_AUDIT_AXE_MACE_HAMMER_RECORD_COUNT = 114
EQUIPMENT_AUDIT_RECORD_COUNT = 2_334
EQUIPMENT_AUDIT_LOGICAL_PAC_EDGE_COUNT = 2_400
EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT = 2_057
EQUIPMENT_AUDIT_ICON_EDGE_COUNT = 3_069
EQUIPMENT_AUDIT_ICON_COUNT = 2_337
EQUIPMENT_AUDIT_RHETT_ITEM_ID = 240_026
EQUIPMENT_AUDIT_RHETT_INTERNAL_NAME = "Rayhorn_TwoHandSword"
EQUIPMENT_AUDIT_RHETT_DISPLAY_NAME = "Rhett's Longsword"
EQUIPMENT_AUDIT_RHETT_LOGICAL_PAC = "cd_phm_02_sword_0009.pac"
EQUIPMENT_AUDIT_RHETT_ICON = (
    "ui/texture/icon/itemicon_prefab_cd_phm_02_sword_0009.dds"
)

_SELECTED_GROUPS = frozenset({"Sword", "Axe / Mace / Hammer"})


@dataclass(frozen=True, slots=True)
class FrozenEquipmentCatalogue:
    """Validated immutable selection plus its serializable evidence payload."""

    source_path: Path
    source_sha256: str
    records: tuple[Mapping[str, object], ...]
    logical_models: tuple[Mapping[str, object], ...]
    icons: tuple[Mapping[str, object], ...]
    payload: Mapping[str, object]


def normalize_archive_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def normalized_archive_key(value: object) -> str:
    return normalize_archive_path(value).casefold()


def equipment_audit_generation_path(workspace_root: Path | str) -> Path:
    return (
        Path(workspace_root)
        / "workspace"
        / "cache"
        / "index"
        / "catalogue_v2"
        / EQUIPMENT_AUDIT_ROOT_ID
        / "generations"
        / EQUIPMENT_AUDIT_GENERATION_ID
    )


def build_frozen_equipment_catalogue(
    generation_path: Path | str,
) -> FrozenEquipmentCatalogue:
    """Load and prove the one catalogue snapshot named by the audit objective."""

    generation = Path(generation_path).expanduser().resolve(strict=True)
    if generation.name != EQUIPMENT_AUDIT_GENERATION_ID:
        raise ValueError(
            "Equipment audit requires frozen catalogue generation "
            f"{EQUIPMENT_AUDIT_GENERATION_ID}; received {generation.name}."
        )
    generation_manifest_path = generation / "manifest.json"
    source_path = generation / "item-catalog-v3.json"
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if len(source_bytes) != EQUIPMENT_AUDIT_ITEM_CATALOG_BYTES:
        raise ValueError(
            "Frozen equipment item catalogue byte length changed: "
            f"expected {EQUIPMENT_AUDIT_ITEM_CATALOG_BYTES:,}, found {len(source_bytes):,}."
        )
    if source_sha256 != EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256:
        raise ValueError(
            "Frozen equipment item catalogue SHA-256 changed: "
            f"expected {EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256}, found {source_sha256}."
        )

    generation_manifest = _read_json_object(
        generation_manifest_path,
        label="frozen catalogue generation manifest",
    )
    _validate_generation_manifest(generation_manifest)
    try:
        source = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Frozen equipment item catalogue is not valid UTF-8 JSON.") from exc
    if not isinstance(source, Mapping):
        raise ValueError("Frozen equipment item catalogue root must be an object.")
    if int(source.get("schema_version", 0) or 0) != EQUIPMENT_AUDIT_SOURCE_SCHEMA_VERSION:
        raise ValueError("Frozen equipment item catalogue schema is not version 3.")
    raw_items = source.get("items")
    if (
        not isinstance(raw_items, Sequence)
        or isinstance(raw_items, (str, bytes, bytearray))
        or len(raw_items) != EQUIPMENT_AUDIT_SOURCE_ITEM_COUNT
    ):
        raise ValueError(
            "Frozen equipment item catalogue must contain exactly "
            f"{EQUIPMENT_AUDIT_SOURCE_ITEM_COUNT:,} source rows."
        )

    selected: list[dict[str, object]] = []
    category_counts = {"Armor": 0}
    group_counts = {group: 0 for group in sorted(_SELECTED_GROUPS)}
    for source_index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping):
            raise ValueError(f"Frozen item catalogue row {source_index} is not an object.")
        category = str(raw_item.get("category", "") or "").strip()
        group = str(raw_item.get("group", "") or "").strip()
        if category != "Armor" and group not in _SELECTED_GROUPS:
            continue
        if category == "Armor":
            category_counts["Armor"] += 1
        if group in group_counts:
            group_counts[group] += 1
        selected.append(_frozen_record(raw_item, source_index=source_index))

    logical_models = _logical_identity_rows(selected, source_key="pac_files")
    icons = _logical_identity_rows(selected, source_key="icon_paths")
    _validate_frozen_counts(selected, logical_models, icons, category_counts, group_counts)
    rhett = _validate_rhett_record(selected)
    selection_sha256 = _canonical_sha256(selected)
    payload: dict[str, object] = {
        "schema": EQUIPMENT_AUDIT_CATALOGUE_SCHEMA,
        "source": {
            "root_id": EQUIPMENT_AUDIT_ROOT_ID,
            "generation_id": EQUIPMENT_AUDIT_GENERATION_ID,
            "archive_fingerprint": EQUIPMENT_AUDIT_ARCHIVE_FINGERPRINT,
            "generation_manifest_path": str(generation_manifest_path),
            "item_catalog_path": str(source_path),
            "item_catalog_schema_version": EQUIPMENT_AUDIT_SOURCE_SCHEMA_VERSION,
            "item_catalog_bytes": len(source_bytes),
            "item_catalog_sha256": source_sha256,
            "source_item_count": len(raw_items),
        },
        "selection": {
            "rule": "category == Armor OR group in [Sword, Axe / Mace / Hammer]",
            "category_counts": category_counts,
            "group_counts": group_counts,
            "record_count": len(selected),
            "logical_pac_edge_count": sum(
                len(tuple(record["pac_files"])) for record in selected
            ),
            "unique_logical_pac_count": len(logical_models),
            "icon_edge_count": sum(
                len(tuple(record["icon_paths"])) for record in selected
            ),
            "unique_icon_count": len(icons),
            "selection_sha256": selection_sha256,
        },
        "canonical_item": {
            "record_id": rhett["record_id"],
            "item_id": rhett["item_id"],
            "internal_name": rhett["internal_name"],
            "display_name": rhett["display_name"],
            "logical_pac": EQUIPMENT_AUDIT_RHETT_LOGICAL_PAC,
            "icon_path": EQUIPMENT_AUDIT_RHETT_ICON,
        },
        "records": selected,
        "logical_models": logical_models,
        "icons": icons,
    }
    return FrozenEquipmentCatalogue(
        source_path=source_path,
        source_sha256=source_sha256,
        records=tuple(selected),
        logical_models=tuple(logical_models),
        icons=tuple(icons),
        payload=payload,
    )


def write_frozen_equipment_catalogue(
    catalogue: FrozenEquipmentCatalogue,
    output_path: Path | str,
) -> Path:
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        destination,
        json.dumps(catalogue.payload, indent=2, sort_keys=True),
    )
    return destination


def _frozen_record(raw_item: Mapping[str, object], *, source_index: int) -> dict[str, object]:
    item_id = raw_item.get("item_id")
    if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id < 0:
        raise ValueError(f"Frozen item catalogue row {source_index} has an invalid item_id.")
    pac_files = _string_list(raw_item.get("pac_files"), field="pac_files", source_index=source_index)
    icon_paths = _string_list(raw_item.get("icon_paths"), field="icon_paths", source_index=source_index)
    if not pac_files:
        raise ValueError(f"Selected equipment row {source_index} has no logical PAC edge.")
    record_id = f"{source_index:04d}-{item_id}"
    return {
        "record_id": record_id,
        "source_index": source_index,
        "item_id": item_id,
        "internal_name": str(raw_item.get("internal_name", "") or "").strip(),
        "display_name": str(raw_item.get("display_name", "") or "").strip(),
        "localized_names": _string_list(
            raw_item.get("localized_names"),
            field="localized_names",
            source_index=source_index,
            allow_empty=True,
        ),
        "prefab_hashes": _integer_list(
            raw_item.get("prefab_hashes"),
            field="prefab_hashes",
            source_index=source_index,
        ),
        "model_stems": _string_list(
            raw_item.get("model_stems"),
            field="model_stems",
            source_index=source_index,
            allow_empty=True,
        ),
        "pac_files": pac_files,
        "icon_paths": icon_paths,
        "category": str(raw_item.get("category", "") or "").strip(),
        "group": str(raw_item.get("group", "") or "").strip(),
        "variant_count": int(raw_item.get("variant_count", 0) or 0),
        "evidence": str(raw_item.get("evidence", "") or "").strip(),
        "equip_type": str(raw_item.get("equip_type", "") or "").strip(),
    }


def _logical_identity_rows(
    records: Sequence[Mapping[str, object]],
    *,
    source_key: str,
) -> list[dict[str, object]]:
    owners: dict[str, list[dict[str, object]]] = defaultdict(list)
    spellings: dict[str, str] = {}
    edge_index = 0
    for record in records:
        values = record.get(source_key)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
            raise ValueError(f"Frozen equipment record has invalid {source_key} values.")
        for value in values:
            declared = normalize_archive_path(value)
            if not declared:
                raise ValueError(f"Frozen equipment record has an empty {source_key} edge.")
            identity = (
                PurePosixPath(declared).name.casefold()
                if source_key == "pac_files"
                else declared.casefold()
            )
            spellings.setdefault(identity, declared)
            owners[identity].append(
                {
                    "edge_index": edge_index,
                    "record_id": str(record["record_id"]),
                    "item_id": int(record["item_id"]),
                    "declared_path": declared,
                }
            )
            edge_index += 1
    return [
        {
            "identity": identity,
            "declared_name": spellings[identity],
            "owner_count": len(rows),
            "owners": rows,
        }
        for identity, rows in sorted(owners.items())
    ]


def _validate_frozen_counts(
    selected: Sequence[Mapping[str, object]],
    logical_models: Sequence[Mapping[str, object]],
    icons: Sequence[Mapping[str, object]],
    category_counts: Mapping[str, int],
    group_counts: Mapping[str, int],
) -> None:
    actual = {
        "armor_records": int(category_counts.get("Armor", 0)),
        "sword_records": int(group_counts.get("Sword", 0)),
        "axe_mace_hammer_records": int(group_counts.get("Axe / Mace / Hammer", 0)),
        "records": len(selected),
        "logical_pac_edges": sum(len(tuple(row["pac_files"])) for row in selected),
        "logical_pacs": len(logical_models),
        "icon_edges": sum(len(tuple(row["icon_paths"])) for row in selected),
        "icons": len(icons),
    }
    expected = {
        "armor_records": EQUIPMENT_AUDIT_ARMOR_RECORD_COUNT,
        "sword_records": EQUIPMENT_AUDIT_SWORD_RECORD_COUNT,
        "axe_mace_hammer_records": EQUIPMENT_AUDIT_AXE_MACE_HAMMER_RECORD_COUNT,
        "records": EQUIPMENT_AUDIT_RECORD_COUNT,
        "logical_pac_edges": EQUIPMENT_AUDIT_LOGICAL_PAC_EDGE_COUNT,
        "logical_pacs": EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
        "icon_edges": EQUIPMENT_AUDIT_ICON_EDGE_COUNT,
        "icons": EQUIPMENT_AUDIT_ICON_COUNT,
    }
    if actual != expected:
        raise ValueError(
            "Frozen equipment audit selection no longer matches its exact contract: "
            f"expected {expected}, found {actual}."
        )


def _validate_rhett_record(
    selected: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    matches = [row for row in selected if row.get("item_id") == EQUIPMENT_AUDIT_RHETT_ITEM_ID]
    if len(matches) != 1:
        raise ValueError("Frozen equipment catalogue must contain exactly one Rhett record.")
    row = matches[0]
    expected = {
        "internal_name": EQUIPMENT_AUDIT_RHETT_INTERNAL_NAME,
        "display_name": EQUIPMENT_AUDIT_RHETT_DISPLAY_NAME,
        "pac_files": [EQUIPMENT_AUDIT_RHETT_LOGICAL_PAC],
        "icon_paths": [EQUIPMENT_AUDIT_RHETT_ICON],
    }
    actual = {key: row.get(key) for key in expected}
    if actual != expected:
        raise ValueError(
            f"Frozen Rhett canonical identity changed: expected {expected}, found {actual}."
        )
    return row


def _validate_generation_manifest(manifest: Mapping[str, object]) -> None:
    expected = {
        "root_id": EQUIPMENT_AUDIT_ROOT_ID,
        "generation_id": EQUIPMENT_AUDIT_GENERATION_ID,
        "fingerprint": EQUIPMENT_AUDIT_ARCHIVE_FINGERPRINT,
        "entry_count": 2_024_267,
        "index_version": 3,
    }
    actual = {key: manifest.get(key) for key in expected}
    if actual != expected:
        raise ValueError(
            "Frozen catalogue generation manifest changed: "
            f"expected {expected}, found {actual}."
        )


def _read_json_object(path: Path, *, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label.capitalize()} is unavailable or invalid: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label.capitalize()} must contain a JSON object: {path}")
    return payload


def _string_list(
    value: object,
    *,
    field: str,
    source_index: int,
    allow_empty: bool = False,
) -> list[str]:
    if value is None and allow_empty:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"Frozen item catalogue row {source_index} has invalid {field}.")
    result = [normalize_archive_path(item) for item in value]
    if any(not item for item in result):
        raise ValueError(f"Frozen item catalogue row {source_index} has an empty {field} value.")
    return result


def _integer_list(value: object, *, field: str, source_index: int) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"Frozen item catalogue row {source_index} has invalid {field}.")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"Frozen item catalogue row {source_index} has invalid {field}.")
        result.append(item)
    return result


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "EQUIPMENT_AUDIT_CATALOGUE_SCHEMA",
    "EQUIPMENT_AUDIT_GENERATION_ID",
    "EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256",
    "EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT",
    "EQUIPMENT_AUDIT_RECORD_COUNT",
    "FrozenEquipmentCatalogue",
    "build_frozen_equipment_catalogue",
    "equipment_audit_generation_path",
    "normalize_archive_path",
    "normalized_archive_key",
    "write_frozen_equipment_catalogue",
]
