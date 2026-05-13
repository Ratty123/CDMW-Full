from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


TABLE_CATALOG_VERSION = "449-curated-v1"
TABLE_CATALOG_SOURCE = "449table.txt"
TABLE_CATALOG_PARSER_COVERAGE = "curated_schema_only"


@dataclass(frozen=True, slots=True)
class TableFieldSpec:
    source_field: str
    role: str
    target_kind: str = ""
    confidence: str = "schema_field"
    texture_role: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class TableSpec:
    source_table: str
    parser_status: str = ""
    on_disk: bool = True
    runtime_usable: bool = False
    fields: Tuple[TableFieldSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class TableEvidenceRecord:
    source_table: str
    source_field: str
    target: str
    role: str
    confidence: str = "table_schema_hint"
    texture_role: str = ""
    note: str = ""

    @property
    def label(self) -> str:
        return table_field_label(self.source_table, self.source_field)

    def to_cache_dict(self) -> Dict[str, object]:
        return {
            "source_table": self.source_table,
            "source_field": self.source_field,
            "target": self.target,
            "role": self.role,
            "confidence": self.confidence,
            "texture_role": self.texture_role,
            "note": self.note,
            "label": self.label,
        }


def _field(
    source_field: str,
    role: str,
    target_kind: str = "",
    *,
    confidence: str = "schema_field",
    texture_role: str = "",
    note: str = "",
) -> TableFieldSpec:
    return TableFieldSpec(
        source_field=source_field,
        role=role,
        target_kind=target_kind,
        confidence=confidence,
        texture_role=texture_role,
        note=note,
    )


TABLE_SPECS: Tuple[TableSpec, ...] = (
    TableSpec(
        "ItemInfo",
        parser_status="T0",
        fields=(
            _field("_key", "item_id", "id", confidence="table_iteminfo_row_scan"),
            _field("_stringKey", "item_internal_name", "name", confidence="table_iteminfo_row_scan"),
            _field("_itemName", "localized_display_name", "localized_name", confidence="table_localization_join"),
            _field("_itemIconList", "ui_icon_path", "texture", texture_role="ui_icon"),
            _field("_mapIconPath", "map_icon_path", "texture", texture_role="ui_map_icon"),
            _field("_moneyIconPath", "money_icon_path", "texture", texture_role="ui_icon"),
            _field("_defaultTexturePath", "default_texture", "texture", texture_role="visible_default"),
            _field("_prefabDataList", "model_hash_reference", "prefab"),
            _field("_gimmickVisualPrefabDataList", "gimmick_prefab_reference", "prefab"),
            _field("_itemGroupInfoList", "item_group", "category"),
            _field("_itemType", "item_type", "category"),
            _field("_equipTypeInfo", "equip_type", "compatibility"),
            _field("_equipAbleHash", "equip_able_hash", "compatibility"),
            _field("_isDyeable", "dyeable_flag", "compatibility"),
            _field("_isEditableGrime", "editable_grime_flag", "compatibility"),
        ),
    ),
    TableSpec(
        "ItemGroupInfo",
        parser_status="T0",
        fields=(
            _field("_groupName", "item_group_name", "category"),
            _field("_itemGroupInfoList", "nested_item_group", "category"),
            _field("_itemInfoList", "group_item_list", "item"),
            _field("_iconPath", "group_icon_path", "texture", texture_role="ui_icon"),
        ),
    ),
    TableSpec(
        "EquipInfoData",
        parser_status="T0",
        fields=(
            _field("_equipTypeList", "equip_type_list", "compatibility"),
            _field("_equipSlotNo", "equip_slot_number", "compatibility"),
            _field("_equipSlotName", "equip_slot_name", "compatibility"),
            _field("_isWeaponSlot", "weapon_slot_flag", "compatibility"),
            _field("_isSpawnCustomMesh", "custom_mesh_spawn_flag", "compatibility"),
        ),
    ),
    TableSpec(
        "EquipTypeInfo",
        parser_status="T0",
        fields=(
            _field("_equipTypeName", "equip_type_name", "compatibility"),
            _field("_equipAbleHashList", "equip_able_hash_list", "compatibility"),
        ),
    ),
    TableSpec(
        "CharacterInfo",
        parser_status="T0",
        fields=(
            _field("_characterPrefabPath", "character_prefab_path", "prefab"),
            _field("_skeletonName", "skeleton_name", "skeleton"),
            _field("_skeletonVariationName", "skeleton_variation_name", "skeleton"),
            _field("_appearanceName", "appearance_name", "appearance"),
            _field("_equipItemInfoList", "default_equip_item_list", "item"),
            _field("_uiIconPath", "character_ui_icon", "texture", texture_role="ui_icon"),
            _field("_uiPortraitPath", "character_portrait", "texture", texture_role="ui_portrait"),
            _field("_uiMapTextureInfo", "map_texture_info", "texture", texture_role="ui_map_icon"),
        ),
    ),
    TableSpec(
        "ItemMeshGroupInfo",
        parser_status="T0",
        fields=(
            _field("_itemMeshGroupDataList", "item_mesh_group_data", "mesh_group"),
            _field("_partCombinationNameList", "part_combination_names", "submesh"),
        ),
    ),
    TableSpec(
        "PartPrefabDyeSlotInfo",
        parser_status="T0",
        fields=(
            _field("_subMeshList", "submesh_dye_slot_list", "submesh"),
            _field("_meshFileName", "mesh_file_name", "mesh"),
        ),
    ),
    TableSpec(
        "PartPrefabDyeTextureSet",
        parser_status="T0",
        fields=(
            _field("_iconPath", "dye_icon_path", "texture", texture_role="ui_icon"),
            _field("_baseColorTexturePath", "dye_base_color_texture", "texture", texture_role="base_color"),
        ),
    ),
    TableSpec(
        "UIMapTextureInfo",
        parser_status="T0",
        fields=(
            _field("_uiTextureName", "map_texture", "texture", texture_role="ui_map"),
            _field("_uiSmallTextureName", "map_small_texture", "texture", texture_role="ui_map_small"),
            _field("_uiFilterTextureName", "map_filter_texture", "texture", texture_role="ui_filter"),
        ),
    ),
    TableSpec(
        "StageChart_Function_SetCustomMesh",
        parser_status="T0",
        fields=(
            _field("_targetName", "custom_mesh_target", "mesh"),
            _field("_resourceName", "custom_mesh_resource", "mesh"),
            _field("_targetNodeId", "custom_mesh_node", "mesh"),
        ),
    ),
)


_TABLE_BY_NAME = {spec.source_table.lower(): spec for spec in TABLE_SPECS}
_TABLE_BY_PATH_STEM = {
    re.sub(r"[^a-z0-9]+", "", spec.source_table.lower()): spec
    for spec in TABLE_SPECS
}
_TABLE_BY_PATH_STEM.update(
    {
        "itemmeshgroupdata": _TABLE_BY_NAME["itemmeshgroupinfo"],
        "stagechartfunctionsetcustommesh": _TABLE_BY_NAME["stagechart_function_setcustommesh"],
        "uimaptextureinfo": _TABLE_BY_NAME["uimaptextureinfo"],
    }
)

_TEXTURE_EXTENSIONS = {".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff"}
_MODEL_EXTENSIONS = {".pac", ".pam", ".pamlod", ".meshinfo"}
_PREFAB_EXTENSIONS = {".prefab", ".prefabdata_xml", ".prefabdata", ".app_xml", ".xml"}
_SKELETON_EXTENSIONS = {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"}
_ASSET_EXTENSIONS = _TEXTURE_EXTENSIONS | _MODEL_EXTENSIONS | _PREFAB_EXTENSIONS | _SKELETON_EXTENSIONS | {
    ".hkx",
    ".hkt",
    ".pami",
    ".pac_xml",
    ".pam_xml",
    ".pamlod_xml",
    ".pappt",
    ".pamhc",
}


def _catalog_signature() -> str:
    rows = [
        {
            "source_table": spec.source_table,
            "parser_status": spec.parser_status,
            "on_disk": spec.on_disk,
            "runtime_usable": spec.runtime_usable,
            "fields": [
                {
                    "source_field": field.source_field,
                    "role": field.role,
                    "target_kind": field.target_kind,
                    "confidence": field.confidence,
                    "texture_role": field.texture_role,
                    "note": field.note,
                }
                for field in spec.fields
            ],
        }
        for spec in TABLE_SPECS
    ]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


TABLE_CATALOG_SIGNATURE = _catalog_signature()


def table_field_label(source_table: str, source_field: str) -> str:
    table = str(source_table or "").strip()
    field = str(source_field or "").strip()
    if table and field:
        return f"{table}.{field}"
    return table or field


def evidence_label(record: TableEvidenceRecord) -> str:
    return table_field_label(record.source_table, record.source_field)


def get_table_spec(source_table: str) -> Optional[TableSpec]:
    return _TABLE_BY_NAME.get(str(source_table or "").strip().lower())


def recognized_table_for_path(path: str) -> Optional[TableSpec]:
    name = PurePosixPath(str(path or "").replace("\\", "/")).name
    stem = name
    for suffix in (".pabgb", ".pabgh", ".pab", ".bin", ".table"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    normalized = re.sub(r"[^a-z0-9]+", "", stem.lower())
    return _TABLE_BY_PATH_STEM.get(normalized)


def table_catalog_cache_metadata(*, row_counts: Optional[Mapping[str, int]] = None) -> Dict[str, object]:
    return {
        "version": TABLE_CATALOG_VERSION,
        "source": TABLE_CATALOG_SOURCE,
        "signature": TABLE_CATALOG_SIGNATURE,
        "parser_coverage": TABLE_CATALOG_PARSER_COVERAGE,
        "row_counts": {str(key): int(value) for key, value in (row_counts or {}).items()},
    }


def table_catalog_cache_metadata_matches(metadata: object) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    return (
        str(metadata.get("version", "")) == TABLE_CATALOG_VERSION
        and str(metadata.get("signature", "")) == TABLE_CATALOG_SIGNATURE
        and str(metadata.get("parser_coverage", "")) == TABLE_CATALOG_PARSER_COVERAGE
    )


def deserialize_table_evidence(rows: object) -> Tuple[TableEvidenceRecord, ...]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return ()
    records: List[TableEvidenceRecord] = []
    for row in rows:
        if isinstance(row, TableEvidenceRecord):
            records.append(row)
            continue
        if not isinstance(row, Mapping):
            continue
        source_table = str(row.get("source_table", "") or "").strip()
        source_field = str(row.get("source_field", "") or "").strip()
        if not source_table or not source_field:
            continue
        records.append(
            TableEvidenceRecord(
                source_table=source_table,
                source_field=source_field,
                target=str(row.get("target", "") or "").strip(),
                role=str(row.get("role", "") or "").strip(),
                confidence=str(row.get("confidence", "") or "table_schema_hint").strip(),
                texture_role=str(row.get("texture_role", "") or "").strip(),
                note=str(row.get("note", "") or "").strip(),
            )
        )
    return tuple(records)


def serialize_table_evidence(records: Sequence[TableEvidenceRecord]) -> List[Dict[str, object]]:
    return [record.to_cache_dict() for record in merge_table_evidence(records)]


def merge_table_evidence(*sources: Sequence[TableEvidenceRecord]) -> Tuple[TableEvidenceRecord, ...]:
    result: List[TableEvidenceRecord] = []
    seen: set[Tuple[str, str, str, str]] = set()
    for source in sources:
        for record in deserialize_table_evidence(source):
            key = (
                record.source_table.lower(),
                record.source_field.lower(),
                record.target.lower(),
                record.role.lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(record)
    return tuple(result)


def summarize_table_evidence(records: Sequence[TableEvidenceRecord], *, max_labels: int = 6) -> str:
    labels: List[str] = []
    seen: set[str] = set()
    for record in deserialize_table_evidence(records):
        label = record.label
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
        if len(labels) >= max_labels:
            break
    return "; ".join(labels)


def infer_table_texture_role(source_field: str) -> str:
    field = str(source_field or "").strip().lower()
    if not field:
        return ""
    if "basecolor" in field or "base_color" in field:
        return "base_color"
    if "defaulttexture" in field:
        return "visible_default"
    if "portrait" in field:
        return "ui_portrait"
    if "map" in field and "texture" in field:
        return "ui_map"
    if "icon" in field:
        return "ui_icon"
    if "uitexture" in field or "texture" in field:
        return "texture"
    return ""


def build_item_table_evidence(
    *,
    item_id: int = 0,
    internal_name: str = "",
    display_name: str = "",
    localized_names: Sequence[str] = (),
    prefab_hashes: Sequence[int] = (),
    model_stems: Sequence[str] = (),
    icon_paths: Sequence[str] = (),
) -> Tuple[TableEvidenceRecord, ...]:
    records: List[TableEvidenceRecord] = []
    if int(item_id or 0) > 0:
        records.append(
            TableEvidenceRecord(
                "ItemInfo",
                "_key",
                str(int(item_id)),
                "item_id",
                confidence="table_iteminfo_row_scan",
            )
        )
    if str(internal_name or "").strip():
        records.append(
            TableEvidenceRecord(
                "ItemInfo",
                "_stringKey",
                str(internal_name).strip(),
                "item_internal_name",
                confidence="table_iteminfo_row_scan",
            )
        )
    display_target = str(display_name or "").strip() or next((str(value).strip() for value in localized_names if str(value).strip()), "")
    if display_target:
        records.append(
            TableEvidenceRecord(
                "ItemInfo",
                "_itemName",
                display_target,
                "localized_display_name",
                confidence="table_localization_join",
            )
        )
    for prefab_hash in prefab_hashes:
        if int(prefab_hash or 0):
            records.append(
                TableEvidenceRecord(
                    "ItemInfo",
                    "_prefabDataList",
                    str(int(prefab_hash)),
                    "model_hash_reference",
                    confidence="table_prefab_hash_reference",
                )
            )
    for model_stem in model_stems:
        value = str(model_stem or "").strip()
        if value:
            records.append(
                TableEvidenceRecord(
                    "ItemInfo",
                    "_itemIconList",
                    value,
                    "icon_model_reference",
                    confidence="table_icon_hash_join",
                )
            )
    for icon_path in icon_paths:
        value = str(icon_path or "").replace("\\", "/").strip()
        if value:
            records.append(
                TableEvidenceRecord(
                    "ItemInfo",
                    "_itemIconList",
                    value,
                    "ui_icon_path",
                    confidence="table_icon_path_join",
                    texture_role="ui_icon",
                )
            )
    return merge_table_evidence(records)


def _looks_like_asset_reference(value: str) -> bool:
    text = str(value or "").strip().replace("\\", "/")
    if not text or len(text) > 260:
        return False
    if not ("/" in text or "." in PurePosixPath(text).name):
        return False
    suffix = PurePosixPath(text).suffix.lower()
    if suffix in _ASSET_EXTENSIONS:
        return True
    lowered = text.lower()
    return lowered.endswith((".pac_xml", ".pam_xml", ".pamlod_xml", ".prefabdata_xml", ".app_xml"))


def _field_for_asset_reference(source_table: str, value: str) -> Tuple[str, str, str]:
    table = str(source_table or "").strip()
    lowered_table = table.lower()
    normalized = str(value or "").replace("\\", "/").strip()
    lowered = normalized.lower()
    suffix = PurePosixPath(lowered).suffix
    if lowered.endswith(".pac_xml"):
        suffix = ".pac_xml"
    elif lowered.endswith(".pam_xml"):
        suffix = ".pam_xml"
    elif lowered.endswith(".pamlod_xml"):
        suffix = ".pamlod_xml"
    elif lowered.endswith(".prefabdata_xml"):
        suffix = ".prefabdata_xml"
    elif lowered.endswith(".app_xml"):
        suffix = ".app_xml"

    if lowered_table == "iteminfo":
        if suffix in _TEXTURE_EXTENSIONS:
            if "map" in lowered:
                return "_mapIconPath", "map_icon_texture", "ui_map_icon"
            if "money" in lowered or "icon" in lowered or "/ui/" in lowered:
                return "_itemIconList", "ui_icon_texture", "ui_icon"
            return "_defaultTexturePath", "default_texture", "visible_default"
        if suffix in _MODEL_EXTENSIONS or suffix in _PREFAB_EXTENSIONS:
            return "_prefabDataList", "model_or_prefab_reference", ""
    if lowered_table == "characterinfo":
        if suffix in _SKELETON_EXTENSIONS:
            return "_skeletonName", "skeleton_reference", ""
        if suffix in _TEXTURE_EXTENSIONS:
            if "portrait" in lowered:
                return "_uiPortraitPath", "character_portrait", "ui_portrait"
            return "_uiIconPath", "character_icon_texture", "ui_icon"
        if suffix in _MODEL_EXTENSIONS or suffix in _PREFAB_EXTENSIONS:
            return "_characterPrefabPath", "character_prefab_reference", ""
    if lowered_table == "partprefabdyetextureset" and suffix in _TEXTURE_EXTENSIONS:
        if "icon" in lowered:
            return "_iconPath", "dye_icon_texture", "ui_icon"
        return "_baseColorTexturePath", "dye_base_color_texture", "base_color"
    if lowered_table == "partprefabdyeslotinfo":
        if suffix in _MODEL_EXTENSIONS:
            return "_meshFileName", "dye_slot_mesh", ""
        return "_subMeshList", "dye_slot_submesh", ""
    if lowered_table == "uimaptextureinfo" and suffix in _TEXTURE_EXTENSIONS:
        if "small" in lowered:
            return "_uiSmallTextureName", "map_small_texture", "ui_map_small"
        if "filter" in lowered:
            return "_uiFilterTextureName", "map_filter_texture", "ui_filter"
        return "_uiTextureName", "map_texture", "ui_map"
    if lowered_table == "stagechart_function_setcustommesh":
        if suffix in _MODEL_EXTENSIONS or suffix in _PREFAB_EXTENSIONS:
            return "_resourceName", "custom_mesh_resource", ""
        return "_targetName", "custom_mesh_target", ""

    spec = get_table_spec(table)
    if spec is not None:
        target_kind = "texture" if suffix in _TEXTURE_EXTENSIONS else "mesh" if suffix in _MODEL_EXTENSIONS else "prefab"
        for field in spec.fields:
            if field.target_kind == target_kind:
                return field.source_field, field.role, field.texture_role
    return "", "table_asset_reference", ""


def extract_table_asset_reference_evidence(
    source_table: str,
    values: Iterable[str],
) -> Tuple[TableEvidenceRecord, ...]:
    records: List[TableEvidenceRecord] = []
    table = str(source_table or "").strip()
    if not table:
        return ()
    for raw_value in values:
        value = str(raw_value or "").strip().strip("\x00").replace("\\", "/")
        if not _looks_like_asset_reference(value):
            continue
        source_field, role, texture_role = _field_for_asset_reference(table, value)
        if not source_field:
            continue
        records.append(
            TableEvidenceRecord(
                source_table=table,
                source_field=source_field,
                target=value,
                role=role,
                confidence="table_string_reference",
                texture_role=texture_role or infer_table_texture_role(source_field),
            )
        )
    return merge_table_evidence(records)


def compatibility_tags_for_catalog_row(
    category: str,
    group: str,
    evidence: Sequence[TableEvidenceRecord] = (),
) -> Tuple[str, ...]:
    tags: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        normalized = str(value or "").strip().lower().replace(" ", "_").replace("/", "_")
        normalized = re.sub(r"[^a-z0-9:_-]+", "", normalized)
        if normalized and normalized not in seen:
            tags.append(normalized)
            seen.add(normalized)

    category_text = str(category or "").strip().lower()
    group_text = str(group or "").strip().lower()
    if category_text:
        add(f"category:{category_text}")
    if group_text:
        add(f"group:{group_text}")
    if category_text == "weapon":
        add("equip_family:weapon")
        add(f"equip_slot:{group_text or 'weapon'}")
    elif category_text == "armor":
        add("equip_family:armor")
        add(f"equip_slot:{group_text or 'armor'}")
    elif category_text == "accessory":
        add("equip_family:accessory")
        add(f"equip_slot:{group_text or 'accessory'}")
    elif category_text == "mount / pet":
        add("equip_family:mount_pet")
        add(f"equip_slot:{group_text or 'mount_pet'}")
    for record in deserialize_table_evidence(evidence):
        if record.source_field in {"_equipSlotName", "_equipTypeName"} and record.target:
            add(f"equip_slot:{record.target}")
        if record.source_field in {"_equipTypeInfo", "_equipAbleHash", "_equipAbleHashList"}:
            add("table_equipment_hint")
    return tuple(tags)


def build_table_compatibility_warning(
    target_tags: Sequence[str],
    source_tags: Sequence[str],
) -> str:
    target = {str(value or "").strip().lower() for value in target_tags if str(value or "").strip()}
    source = {str(value or "").strip().lower() for value in source_tags if str(value or "").strip()}
    if not target or not source:
        return ""
    target_families = {value.split(":", 1)[1] for value in target if value.startswith("equip_family:")}
    source_families = {value.split(":", 1)[1] for value in source if value.startswith("equip_family:")}
    if target_families and source_families and target_families.isdisjoint(source_families):
        return (
            "Table catalog compatibility warning: source and target equipment families differ "
            f"({', '.join(sorted(source_families))} -> {', '.join(sorted(target_families))})."
        )
    target_slots = {value.split(":", 1)[1] for value in target if value.startswith("equip_slot:")}
    source_slots = {value.split(":", 1)[1] for value in source if value.startswith("equip_slot:")}
    if target_slots and source_slots and target_slots.isdisjoint(source_slots):
        return (
            "Table catalog compatibility warning: source and target equipment slots differ "
            f"({', '.join(sorted(source_slots))} -> {', '.join(sorted(target_slots))})."
        )
    return ""
