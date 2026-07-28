from __future__ import annotations

import html
import re
import struct
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    AttachmentBodyLocationChoice,
    AttachmentPartInOutDocument,
    AttachmentPartInOutPatchDiff,
    AttachmentPartInOutPatchResult,
    AttachmentPartInOutSocketInfo,
    AttachmentSocketDocument,
    AttachmentSocketInfo,
    AttachmentStackEquipInfo,
    AttachmentStackEquipTypePatchResult,
)
from cdmw.domain.archives.attachments import (
    PrefabAttachmentProfilePatchResult,
    PrefabSocketNameField,
    PrefabSocketNamePatchResult,
)
from cdmw.core.archive_binary_preview import _binary_sidecar_schema_declarations

def _parse_socket_float_tuple(value: str) -> Tuple[float, ...]:
    values: List[float] = []
    for part in str(value or "").replace(",", " ").split():
        try:
            values.append(float(part))
        except ValueError:
            continue
    return tuple(values)


def _xml_local_tag_name(value: object) -> str:
    text = str(value or "")
    if "}" in text:
        return text.rsplit("}", 1)[-1]
    return text


def parse_socket_bone_data_xml(text: str, source_path: str = "") -> AttachmentSocketDocument:
    """Parse Crimson Desert socket XML enough to explain attachment placement.

    This intentionally stays read-only. It recovers socket names, parent bones,
    transforms, and StackEquipInfo groupings used by weapon/armor placement.
    """
    try:
        root = ET.fromstring(str(text or ""))
    except Exception:
        return AttachmentSocketDocument(source_path=source_path)

    sockets: List[AttachmentSocketInfo] = []
    stack_infos: List[AttachmentStackEquipInfo] = []
    for element in root.iter():
        local_name = _xml_local_tag_name(element.tag)
        if local_name == "Socket" and "Parent" in element.attrib:
            sockets.append(
                AttachmentSocketInfo(
                    name=str(element.attrib.get("Name", "") or "").strip(),
                    parent=str(element.attrib.get("Parent", "") or "").strip(),
                    rotation=_parse_socket_float_tuple(str(element.attrib.get("Rotation", "") or "")),
                    translation=_parse_socket_float_tuple(str(element.attrib.get("Translation", "") or "")),
                    ui_view=str(element.attrib.get("UIView", "") or "").strip(),
                    source_path=source_path,
                )
            )
        elif local_name == "StackEquipInfo":
            socket_names: List[str] = []
            for child in tuple(element):
                if _xml_local_tag_name(child.tag) == "Socket":
                    socket_name = str(child.attrib.get("Name", "") or "").strip()
                    if socket_name:
                        socket_names.append(socket_name)
            stack_infos.append(
                AttachmentStackEquipInfo(
                    equip_type_name=str(element.attrib.get("EquipTypeName", "") or "").strip(),
                    socket_names=tuple(socket_names),
                    origin_bone_name=str(element.attrib.get("OriginBoneName", "") or "").strip(),
                    axis=str(element.attrib.get("Axis", "") or "").strip(),
                    inner_part_names=str(element.attrib.get("InnerPartNames", "") or "").strip(),
                    push_origin_bone=str(element.attrib.get("PushOriginBone", "") or "").strip(),
                    source_path=source_path,
                )
            )
    return AttachmentSocketDocument(source_path=source_path, sockets=tuple(sockets), stack_equip_infos=tuple(stack_infos))


_PART_IN_OUT_SOCKET_TAG_RE = re.compile(r"<PartInOutSocket\b(?P<attrs>[^<>]*?)/?>", re.IGNORECASE | re.DOTALL)
_PART_IN_OUT_ATTR_RE = re.compile(r"""(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<quote>['"])(?P<value>.*?)(?P=quote)""", re.DOTALL)
_PART_IN_OUT_PATCH_FIELDS: Tuple[str, ...] = (
    "InSocketBone",
    "InChildSocketBone",
    "OutSocketBone",
    "OutChildSocketBone",
    "BagSocketBone",
    "VehicleBagSocketBone",
    "WeaponCasePart",
    "Visible",
)
_STACK_EQUIP_DATA_CONTAINER_TAG_RE = re.compile(
    r"<StackEquipDataContainer\b(?P<attrs>[^<>]*?)/?>",
    re.IGNORECASE | re.DOTALL,
)


def _parse_part_in_out_attrs(text: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for match in _PART_IN_OUT_ATTR_RE.finditer(str(text or "")):
        name = str(match.group("name") or "").strip()
        if not name:
            continue
        attrs[name] = html.unescape(str(match.group("value") or ""))
    return attrs


def parse_part_in_out_socket_info_xml(text: str, source_path: str = "") -> AttachmentPartInOutDocument:
    """Parse character PartInOutSocket rows from Crimson descriptor XML-like text.

    Character descriptor files use non-standard closing tags such as ``</>`` in
    shipped samples, so this parser intentionally scans only self-contained
    PartInOutSocket tags instead of requiring a fully valid XML document.
    """
    rows: List[AttachmentPartInOutSocketInfo] = []
    for match in _PART_IN_OUT_SOCKET_TAG_RE.finditer(str(text or "")):
        attrs = _parse_part_in_out_attrs(str(match.group("attrs") or ""))
        part_name = str(attrs.get("PartName") or "").strip()
        if not part_name:
            continue
        rows.append(
            AttachmentPartInOutSocketInfo(
                part_name=part_name,
                in_socket_bone=str(attrs.get("InSocketBone") or ""),
                out_socket_bone=str(attrs.get("OutSocketBone") or ""),
                in_child_socket_bone=str(attrs.get("InChildSocketBone") or ""),
                out_child_socket_bone=str(attrs.get("OutChildSocketBone") or ""),
                bag_socket_bone=str(attrs.get("BagSocketBone") or ""),
                vehicle_bag_socket_bone=str(attrs.get("VehicleBagSocketBone") or ""),
                weapon_case_part=str(attrs.get("WeaponCasePart") or ""),
                visible=str(attrs.get("Visible") or ""),
                source_path=source_path,
                attributes=dict(attrs),
            )
        )
    return AttachmentPartInOutDocument(source_path=source_path, rows=tuple(rows))


def parse_pac_xml_stack_equip_type(text: str) -> str:
    """Return target item slot metadata from a modelproperty .pac_xml sidecar."""
    match = _STACK_EQUIP_DATA_CONTAINER_TAG_RE.search(str(text or ""))
    if not match:
        return ""
    attrs = _parse_part_in_out_attrs(str(match.group("attrs") or ""))
    return _part_in_out_attr_value(attrs, "_equipType").strip()


def infer_stack_equip_type_for_socket(
    socket_name: str,
    socket_document: Optional[AttachmentSocketDocument] = None,
) -> str:
    socket_text = str(socket_name or "").strip()
    if not socket_text:
        return ""
    socket_key = socket_text.casefold()
    if isinstance(socket_document, AttachmentSocketDocument):
        for stack in tuple(getattr(socket_document, "stack_equip_infos", ()) or ()):
            equip_type = str(getattr(stack, "equip_type_name", "") or "").strip()
            if not equip_type:
                continue
            for stack_socket_name in tuple(getattr(stack, "socket_names", ()) or ()):
                if str(stack_socket_name or "").strip().casefold() == socket_key:
                    return equip_type
    if "pelvis_l" in socket_key:
        return "Pelvis_L"
    if "pelvis_r" in socket_key:
        return "Pelvis_R"
    if "pelvis_b" in socket_key:
        return "Pelvis_B"
    if "shoulder_l" in socket_key or "clavicle_l" in socket_key:
        return "Shoulder_L"
    if "shoulder_r" in socket_key or "clavicle_r" in socket_key:
        return "Shoulder_R"
    if "spine" in socket_key or "back" in socket_key:
        return "Back"
    return ""


def build_pac_xml_stack_equip_type_patch(
    base_text: str,
    *,
    equip_type: str,
) -> AttachmentStackEquipTypePatchResult:
    target_equip_type = str(equip_type or "").strip()
    if not target_equip_type:
        return AttachmentStackEquipTypePatchResult(text=str(base_text or ""))
    old_equip_type = parse_pac_xml_stack_equip_type(base_text)
    if not old_equip_type:
        return AttachmentStackEquipTypePatchResult(text=str(base_text or ""))
    if old_equip_type == target_equip_type:
        return AttachmentStackEquipTypePatchResult(
            text=str(base_text or ""),
            old_equip_type=old_equip_type,
            new_equip_type=target_equip_type,
            changed=False,
        )

    changed = False

    def replace_tag(match: re.Match[str]) -> str:
        nonlocal changed
        if changed:
            return match.group(0)
        tag_text = match.group(0)
        attrs = _parse_part_in_out_attrs(str(match.group("attrs") or ""))
        current_value = _part_in_out_attr_value(attrs, "_equipType").strip()
        if current_value != old_equip_type or not _part_in_out_has_attr(attrs, "_equipType"):
            return tag_text
        changed = True
        return _part_in_out_set_attr(tag_text, "_equipType", target_equip_type)

    patched_text = _STACK_EQUIP_DATA_CONTAINER_TAG_RE.sub(replace_tag, str(base_text or ""), count=1)
    return AttachmentStackEquipTypePatchResult(
        text=patched_text,
        old_equip_type=old_equip_type,
        new_equip_type=target_equip_type,
        changed=changed,
    )

def infer_part_in_out_weapon_class(value: object) -> str:
    normalized = str(value or "").replace("\\", "/").strip().casefold()
    if not normalized:
        return ""

    compact = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    path_name = PurePosixPath(normalized).name.casefold()
    path_stem = PurePosixPath(path_name).stem.casefold()

    twohand_part_map = (
        ("cd_twohandweapon_sword", "twohand_sword"),
        ("cd_twohandweapon_axe", "axe"),
        ("cd_twohandweapon_mace", "mace"),
        ("cd_twohandweapon_spear", "spear"),
        ("cd_twohandweapon_alebard", "spear"),
        ("cd_twohandweapon_hammer", "hammer"),
        ("cd_twohandweapon_warhammer", "warhammer"),
        ("cd_twohandweapon_scythe", "scythe"),
        ("cd_twohandweapon_rod", "rod"),
        ("cd_twohandweapon_cannon", "cannon"),
        ("cd_twohandweapon_thrower", "thrower"),
    )
    for token, class_name in twohand_part_map:
        if compact == token or compact.startswith(f"{token}_"):
            return class_name

    mainhand_part_map = (
        ("cd_mainweapon_sword", "onehand_sword"),
        ("cd_mainweapon_dagger", "onehand_dagger"),
        ("cd_mainweapon_axe", "axe"),
        ("cd_mainweapon_mace", "mace"),
        ("cd_mainweapon_wand", "wand"),
    )
    for token, class_name in mainhand_part_map:
        if compact == token or compact.startswith(f"{token}_"):
            return class_name

    if "cd_phm_02_sword" in path_stem or ("/2_twohandweapon/" in normalized and "sword" in path_stem):
        return "twohand_sword"
    if "cd_phm_01_sword" in path_stem or ("/1_onehandweapon/" in normalized and "sword" in path_stem):
        return "onehand_sword"
    if "dagger" in path_stem:
        return "onehand_dagger"
    if "warhammer" in path_stem:
        return "warhammer"
    if "hammer" in path_stem:
        return "hammer"
    if "axe" in path_stem:
        return "axe"
    if "mace" in path_stem:
        return "mace"
    if "spear" in path_stem or "alebard" in path_stem:
        return "spear"
    if "scythe" in path_stem:
        return "scythe"
    if "rod" in path_stem:
        return "rod"
    if "cannon" in path_stem:
        return "cannon"
    if "thrower" in path_stem:
        return "thrower"
    if "wand" in path_stem:
        return "wand"
    if "twohandweapon" in normalized or "/2_twohandweapon/" in normalized:
        return "twohand"
    if "mainweapon" in normalized or "/1_onehandweapon/" in normalized:
        return "mainhand"
    return ""


def part_in_out_rows_for_weapon_class(
    document: AttachmentPartInOutDocument,
    weapon_class: str,
) -> Tuple[AttachmentPartInOutSocketInfo, ...]:
    normalized_class = str(weapon_class or "").strip().casefold()
    if not normalized_class:
        return tuple(document.rows)
    return tuple(
        row
        for row in tuple(getattr(document, "rows", ()) or ())
        if infer_part_in_out_weapon_class(row.part_name) == normalized_class
    )


_ATTACHMENT_BODY_GROUP_LABELS: Mapping[str, str] = {
    "back": "Back",
    "pelvis_l": "Left hip",
    "pelvis_r": "Right hip",
    "shoulder_l": "Left shoulder",
    "shoulder_r": "Right shoulder",
    "ring_l": "Left ring",
    "ring_r": "Right ring",
}

_ATTACHMENT_SOCKET_ROLE_LABELS: Tuple[Tuple[str, str], ...] = (
    ("spine2_b_mainweapon_socket", "main weapon"),
    ("spine2_b_subweapon_socket", "sub weapon"),
    ("spine2_b_rangeweapon_socket", "ranged weapon"),
    ("spine2_b_shield_socket", "shield"),
    ("spine1_b_socket", "upper back"),
    ("spine0_b_socket", "lower back"),
    ("pelvis_l_socket", "left hip"),
    ("pelvis_r_socket", "right hip"),
    ("pelvis_b_socket", "rear hip"),
    ("rhand_socket", "right hand"),
    ("lhand_socket", "left hand"),
    ("lforearm_socket", "left forearm"),
    ("rforearm_socket", "right forearm"),
    ("clavicle_l_socket", "left shoulder"),
    ("clavicle_r_socket", "right shoulder"),
    ("rthigh_socket", "right thigh"),
    ("lthigh_socket", "left thigh"),
)

_ATTACHMENT_BODY_LOCATION_SOCKET_TOKENS: Tuple[str, ...] = (
    "spine",
    "pelvis",
    "hand",
    "forearm",
    "thigh",
    "clavicle",
    "shoulder",
    "weapon",
    "shield",
    "rangeweapon",
    "lantern",
    "ring",
    "earring",
    "dock",
)


def _attachment_body_group_label(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "Other body"
    normalized = text.casefold()
    if normalized in _ATTACHMENT_BODY_GROUP_LABELS:
        return _ATTACHMENT_BODY_GROUP_LABELS[normalized]
    return re.sub(r"[_-]+", " ", text).strip().title()


def _attachment_socket_role_label(socket_name: object) -> str:
    normalized = str(socket_name or "").strip().casefold()
    for token, label in _ATTACHMENT_SOCKET_ROLE_LABELS:
        if normalized == token:
            return label
    text = str(socket_name or "").strip()
    if text.endswith("_Socket"):
        text = text[:-7]
    text = re.sub(r"[_-]+", " ", text).strip()
    return text or "socket"


def infer_attachment_child_socket_name(
    socket_name: str,
    part_document: Optional[AttachmentPartInOutDocument] = None,
    *,
    weapon_class: str = "",
) -> str:
    """Infer the weapon-side child socket for a selected character-side attach socket."""
    socket_text = str(socket_name or "").strip()
    if not socket_text:
        return ""
    socket_key = socket_text.casefold()
    class_key = str(weapon_class or "").strip().casefold()
    scored_children: Dict[str, Tuple[int, str]] = {}
    if isinstance(part_document, AttachmentPartInOutDocument):
        for row in tuple(getattr(part_document, "rows", ()) or ()):
            if str(getattr(row, "in_socket_bone", "") or "").strip().casefold() != socket_key:
                continue
            child = str(getattr(row, "in_child_socket_bone", "") or "").strip()
            if not child:
                continue
            score = 1
            if class_key and infer_part_in_out_weapon_class(row.part_name) == class_key:
                score += 8
            if str(getattr(row, "part_name", "") or "").casefold().endswith("_in"):
                score += 1
            current_score, current_child = scored_children.get(child.casefold(), (0, child))
            scored_children[child.casefold()] = (current_score + score, current_child)
    if scored_children:
        return sorted(scored_children.values(), key=lambda item: (-item[0], item[1].casefold()))[0][1]

    lowered = socket_key
    if "pelvis_l" in lowered:
        return "Pelvis_L_ChildSocket"
    if "pelvis_r" in lowered:
        return "Pelvis_R_ChildSocket"
    if "rangeweapon" in lowered:
        return "Spine2_B_RangeWeapon_ChildSocket"
    if "shield" in lowered:
        return "Spine2_B_Shield_ChildSocket"
    if "subweapon" in lowered or "mainweapon" in lowered or "pelvis_b" in lowered:
        return "Spine2_B_SubWeapon_ChildSocket"
    if "hand" in lowered or "forearm" in lowered:
        return "Basic_ChildSocket"
    if lowered == "spine1_b_socket":
        return "Pelvis_L_ChildSocket"
    if lowered == "spine0_b_socket":
        return "Pelvis_R_ChildSocket"
    if socket_text.endswith("_Socket"):
        return f"{socket_text[:-7]}_ChildSocket"
    return ""


def build_attachment_body_location_choices(
    socket_document: Optional[AttachmentSocketDocument],
    part_document: Optional[AttachmentPartInOutDocument] = None,
    *,
    weapon_class: str = "",
) -> Tuple[AttachmentBodyLocationChoice, ...]:
    """Build data-driven body attach choices from recovered SocketBoneData rows."""
    if not isinstance(socket_document, AttachmentSocketDocument):
        return ()
    sockets_by_key = {
        str(socket.name or "").strip().casefold(): socket
        for socket in tuple(getattr(socket_document, "sockets", ()) or ())
        if isinstance(socket, AttachmentSocketInfo) and str(socket.name or "").strip()
    }
    used_parts_by_socket: Dict[str, List[str]] = defaultdict(list)
    if isinstance(part_document, AttachmentPartInOutDocument):
        for row in tuple(getattr(part_document, "rows", ()) or ()):
            socket_name = str(getattr(row, "in_socket_bone", "") or "").strip()
            part_name = str(getattr(row, "part_name", "") or "").strip()
            if socket_name and part_name:
                used_parts_by_socket[socket_name.casefold()].append(part_name)

    choices: List[AttachmentBodyLocationChoice] = []
    seen: set[str] = set()

    def add_choice(socket_name: str, group_name: str, source: str) -> None:
        socket = sockets_by_key.get(str(socket_name or "").strip().casefold())
        if not isinstance(socket, AttachmentSocketInfo):
            return
        clean_socket_name = str(socket.name or "").strip()
        key = clean_socket_name.casefold()
        if not clean_socket_name or key in seen:
            return
        seen.add(key)
        group_label = _attachment_body_group_label(group_name)
        role_label = _attachment_socket_role_label(clean_socket_name)
        label = f"{group_label}: {role_label}" if group_name else role_label
        child_socket = infer_attachment_child_socket_name(
            clean_socket_name,
            part_document,
            weapon_class=weapon_class,
        )
        part_names = tuple(dict.fromkeys(used_parts_by_socket.get(key, ())))
        note_parts = [
            f"socket {clean_socket_name}",
            f"parent {socket.parent or '-'}",
        ]
        if child_socket:
            note_parts.append(f"child {child_socket}")
        if part_names:
            note_parts.append(f"used by {', '.join(part_names[:4])}" + (" ..." if len(part_names) > 4 else ""))
        choices.append(
            AttachmentBodyLocationChoice(
                label=label,
                group_name=str(group_name or "").strip(),
                socket_name=clean_socket_name,
                child_socket_name=child_socket,
                parent=socket.parent,
                translation=socket.translation,
                rotation=socket.rotation,
                source_path=socket.source_path or socket_document.source_path,
                source=source,
                note="; ".join(note_parts),
                used_by_part_names=part_names,
            )
        )

    for stack in tuple(getattr(socket_document, "stack_equip_infos", ()) or ()):
        group_name = str(getattr(stack, "equip_type_name", "") or "").strip()
        for socket_name in tuple(getattr(stack, "socket_names", ()) or ()):
            add_choice(str(socket_name or ""), group_name, "StackEquipInfo")

    for socket in tuple(getattr(socket_document, "sockets", ()) or ()):
        socket_name = str(getattr(socket, "name", "") or "").strip()
        key = socket_name.casefold()
        if not socket_name or key in seen:
            continue
        if key in used_parts_by_socket or any(token in key for token in _ATTACHMENT_BODY_LOCATION_SOCKET_TOKENS):
            add_choice(socket_name, "", "SocketList")

    return tuple(choices)


def _part_in_out_attr_value(attrs: Mapping[str, str], name: str) -> str:
    for attr_name, value in attrs.items():
        if str(attr_name or "").casefold() == str(name or "").casefold():
            return str(value or "")
    return ""


def _part_in_out_set_attr(tag_text: str, name: str, value: str) -> str:
    escaped = html.escape(str(value or ""), quote=True)
    pattern = re.compile(
        rf"""(?P<prefix>\b{re.escape(name)}\s*=\s*)(?P<quote>['"])(?P<value>.*?)(?P=quote)""",
        re.IGNORECASE | re.DOTALL,
    )

    def repl(match: re.Match[str]) -> str:
        quote = str(match.group("quote") or '"')
        return f"{match.group('prefix')}{quote}{escaped}{quote}"

    if pattern.search(tag_text):
        return pattern.sub(repl, tag_text, count=1)
    insert_at = tag_text.rfind("/>")
    if insert_at < 0:
        insert_at = tag_text.rfind(">")
    if insert_at < 0:
        return tag_text
    spacer = "" if tag_text[:insert_at].endswith((" ", "\t", "\n", "\r")) else " "
    return f"{tag_text[:insert_at]}{spacer}{name}=\"{escaped}\"{tag_text[insert_at:]}"


def _part_in_out_has_attr(attrs: Mapping[str, str], name: str) -> bool:
    key = str(name or "").casefold()
    return any(str(attr_name or "").casefold() == key for attr_name in attrs)


def _part_in_out_is_visible_only_row(attrs: Mapping[str, str]) -> bool:
    return _part_in_out_attr_value(attrs, "Visible").strip().casefold() == "out"


def _part_in_out_row_is_patchable_for_fields(
    row: AttachmentPartInOutSocketInfo,
    field_names: Sequence[str],
) -> bool:
    attrs = getattr(row, "attributes", {}) or {}
    if _part_in_out_is_visible_only_row(attrs):
        return False
    return any(_part_in_out_has_attr(attrs, field_name) for field_name in tuple(field_names or ()))


def _part_in_out_patch_state_fields(placement_state: str) -> Tuple[str, str]:
    normalized_state = str(placement_state or "stowed").strip().casefold()
    if normalized_state in {"held", "out", "hand", "hands", "equipped"}:
        return "OutSocketBone", "OutChildSocketBone"
    return "InSocketBone", "InChildSocketBone"


def build_part_in_out_socket_profile_patch(
    base_text: str,
    profile_text: str,
    *,
    weapon_class: str,
    fields: Sequence[str] = _PART_IN_OUT_PATCH_FIELDS,
) -> AttachmentPartInOutPatchResult:
    base_document = parse_part_in_out_socket_info_xml(base_text)
    profile_document = parse_part_in_out_socket_info_xml(profile_text)
    profile_rows_by_name = {
        row.part_name.casefold(): row
        for row in part_in_out_rows_for_weapon_class(profile_document, weapon_class)
        if _part_in_out_row_is_patchable_for_fields(row, fields)
    }
    target_part_names = {
        row.part_name.casefold()
        for row in part_in_out_rows_for_weapon_class(base_document, weapon_class)
        if _part_in_out_row_is_patchable_for_fields(row, fields)
    }
    if not target_part_names or not profile_rows_by_name:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))

    diffs: List[AttachmentPartInOutPatchDiff] = []
    patched_names: List[str] = []

    def replace_tag(match: re.Match[str]) -> str:
        tag_text = match.group(0)
        attrs = _parse_part_in_out_attrs(str(match.group("attrs") or ""))
        part_name = str(attrs.get("PartName") or "").strip()
        key = part_name.casefold()
        profile_row = profile_rows_by_name.get(key)
        if key not in target_part_names or profile_row is None:
            return tag_text
        if _part_in_out_is_visible_only_row(attrs):
            return tag_text
        updated = tag_text
        changed = False
        for field_name in fields:
            if not _part_in_out_has_attr(attrs, field_name):
                continue
            old_value = _part_in_out_attr_value(attrs, field_name)
            new_value = _part_in_out_attr_value(profile_row.attributes, field_name)
            if old_value == new_value:
                continue
            if not new_value and field_name not in profile_row.attributes:
                continue
            updated = _part_in_out_set_attr(updated, field_name, new_value)
            diffs.append(
                AttachmentPartInOutPatchDiff(
                    part_name=part_name,
                    field_name=field_name,
                    old_value=old_value,
                    new_value=new_value,
                )
            )
            changed = True
        if changed:
            patched_names.append(part_name)
        return updated

    patched_text = _PART_IN_OUT_SOCKET_TAG_RE.sub(replace_tag, str(base_text or ""))
    return AttachmentPartInOutPatchResult(
        text=patched_text,
        diffs=tuple(diffs),
        patched_part_names=tuple(dict.fromkeys(patched_names)),
    )


def build_part_in_out_socket_attach_point_patch(
    base_text: str,
    *,
    weapon_class: str,
    in_socket_bone: str,
    in_child_socket_bone: str = "",
    placement_state: str = "stowed",
) -> AttachmentPartInOutPatchResult:
    base_document = parse_part_in_out_socket_info_xml(base_text)
    target_part_names = {
        row.part_name.casefold()
        for row in part_in_out_rows_for_weapon_class(base_document, weapon_class)
    }
    socket_name = str(in_socket_bone or "").strip()
    child_socket_name = str(in_child_socket_bone or "").strip()
    if not target_part_names or not socket_name:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))
    socket_field_name, child_field_name = _part_in_out_patch_state_fields(placement_state)
    patch_fields = (socket_field_name, child_field_name)
    target_part_names = {
        row.part_name.casefold()
        for row in part_in_out_rows_for_weapon_class(base_document, weapon_class)
        if _part_in_out_row_is_patchable_for_fields(row, patch_fields)
    }
    if not target_part_names:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))

    diffs: List[AttachmentPartInOutPatchDiff] = []
    patched_names: List[str] = []

    def replace_tag(match: re.Match[str]) -> str:
        tag_text = match.group(0)
        attrs = _parse_part_in_out_attrs(str(match.group("attrs") or ""))
        part_name = str(attrs.get("PartName") or "").strip()
        if part_name.casefold() not in target_part_names:
            return tag_text
        if _part_in_out_is_visible_only_row(attrs):
            return tag_text
        updated = tag_text
        changed = False
        old_socket = _part_in_out_attr_value(attrs, socket_field_name)
        if _part_in_out_has_attr(attrs, socket_field_name) and old_socket != socket_name:
            updated = _part_in_out_set_attr(updated, socket_field_name, socket_name)
            diffs.append(AttachmentPartInOutPatchDiff(part_name, socket_field_name, old_socket, socket_name))
            changed = True
        if child_socket_name and _part_in_out_has_attr(attrs, child_field_name):
            old_child = _part_in_out_attr_value(attrs, child_field_name)
            if old_child != child_socket_name:
                updated = _part_in_out_set_attr(updated, child_field_name, child_socket_name)
                diffs.append(AttachmentPartInOutPatchDiff(part_name, child_field_name, old_child, child_socket_name))
                changed = True
        if changed:
            patched_names.append(part_name)
        return updated

    patched_text = _PART_IN_OUT_SOCKET_TAG_RE.sub(replace_tag, str(base_text or ""))
    return AttachmentPartInOutPatchResult(
        text=patched_text,
        diffs=tuple(diffs),
        patched_part_names=tuple(dict.fromkeys(patched_names)),
    )


def build_part_in_out_socket_weapon_case_part_patch(
    base_text: str,
    *,
    part_name: str,
    weapon_case_part: str,
) -> AttachmentPartInOutPatchResult:
    target_part_name = str(part_name or "").strip()
    target_key = target_part_name.casefold()
    case_part = str(weapon_case_part or "").strip()
    if not target_key or not case_part:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))

    diffs: List[AttachmentPartInOutPatchDiff] = []
    patched_names: List[str] = []

    def replace_tag(match: re.Match[str]) -> str:
        tag_text = match.group(0)
        attrs = _parse_part_in_out_attrs(str(match.group("attrs") or ""))
        row_part_name = str(attrs.get("PartName") or "").strip()
        if row_part_name.casefold() != target_key:
            return tag_text
        if _part_in_out_is_visible_only_row(attrs):
            return tag_text
        old_case_part = _part_in_out_attr_value(attrs, "WeaponCasePart")
        if old_case_part == case_part:
            return tag_text
        updated = _part_in_out_set_attr(tag_text, "WeaponCasePart", case_part)
        if updated == tag_text:
            return tag_text
        diffs.append(AttachmentPartInOutPatchDiff(row_part_name, "WeaponCasePart", old_case_part, case_part))
        patched_names.append(row_part_name)
        return updated

    patched_text = _PART_IN_OUT_SOCKET_TAG_RE.sub(replace_tag, str(base_text or ""))
    return AttachmentPartInOutPatchResult(
        text=patched_text,
        diffs=tuple(diffs),
        patched_part_names=tuple(dict.fromkeys(patched_names)),
    )


def build_part_in_out_socket_class_copy_patch(
    base_text: str,
    *,
    target_weapon_class: str,
    source_weapon_class: str,
    placement_state: str = "stowed",
) -> AttachmentPartInOutPatchResult:
    base_document = parse_part_in_out_socket_info_xml(base_text)
    target_rows = part_in_out_rows_for_weapon_class(base_document, target_weapon_class)
    source_rows = part_in_out_rows_for_weapon_class(base_document, source_weapon_class)
    if not target_rows or not source_rows:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))
    socket_field_name, child_field_name = _part_in_out_patch_state_fields(placement_state)
    patch_fields = (socket_field_name, child_field_name)
    target_rows = tuple(
        row
        for row in target_rows
        if _part_in_out_row_is_patchable_for_fields(row, patch_fields)
    )
    source_rows = tuple(
        row
        for row in source_rows
        if _part_in_out_row_is_patchable_for_fields(row, patch_fields)
    )
    if not target_rows or not source_rows:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))

    source_socket = ""
    source_child = ""
    for row in source_rows:
        source_socket = _part_in_out_attr_value(row.attributes, socket_field_name)
        source_child = _part_in_out_attr_value(row.attributes, child_field_name)
        if source_socket:
            break
    if not source_socket:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))

    target_part_names = {row.part_name.casefold() for row in target_rows}
    diffs: List[AttachmentPartInOutPatchDiff] = []
    patched_names: List[str] = []

    def replace_tag(match: re.Match[str]) -> str:
        tag_text = match.group(0)
        attrs = _parse_part_in_out_attrs(str(match.group("attrs") or ""))
        part_name = str(attrs.get("PartName") or "").strip()
        if part_name.casefold() not in target_part_names:
            return tag_text
        if _part_in_out_is_visible_only_row(attrs):
            return tag_text
        updated = tag_text
        changed = False
        old_socket = _part_in_out_attr_value(attrs, socket_field_name)
        if _part_in_out_has_attr(attrs, socket_field_name) and old_socket != source_socket:
            updated = _part_in_out_set_attr(updated, socket_field_name, source_socket)
            diffs.append(AttachmentPartInOutPatchDiff(part_name, socket_field_name, old_socket, source_socket))
            changed = True
        if source_child and _part_in_out_has_attr(attrs, child_field_name):
            old_child = _part_in_out_attr_value(attrs, child_field_name)
            if old_child != source_child:
                updated = _part_in_out_set_attr(updated, child_field_name, source_child)
                diffs.append(AttachmentPartInOutPatchDiff(part_name, child_field_name, old_child, source_child))
                changed = True
        if changed:
            patched_names.append(part_name)
        return updated

    patched_text = _PART_IN_OUT_SOCKET_TAG_RE.sub(replace_tag, str(base_text or ""))
    return AttachmentPartInOutPatchResult(
        text=patched_text,
        diffs=tuple(diffs),
        patched_part_names=tuple(dict.fromkeys(patched_names)),
    )


_SOCKET_BONE_SOCKET_TAG_RE = re.compile(r"<Socket\b(?P<attrs>[^<>]*\bParent\s*=\s*['\"][^<>]*?)/?>", re.IGNORECASE | re.DOTALL)
_SOCKET_BONE_PATCH_FIELDS: Tuple[str, ...] = ("Parent", "Rotation", "Translation", "UIView")


def build_socket_bone_data_profile_patch(
    base_text: str,
    profile_text: str,
    *,
    socket_names: Sequence[str] = (),
    fields: Sequence[str] = _SOCKET_BONE_PATCH_FIELDS,
) -> AttachmentPartInOutPatchResult:
    base_document = parse_socket_bone_data_xml(base_text)
    profile_document = parse_socket_bone_data_xml(profile_text)
    profile_sockets = {
        socket.name.casefold(): socket
        for socket in tuple(profile_document.sockets or ())
        if str(socket.name or "").strip()
    }
    if socket_names:
        target_names = {str(name or "").strip().casefold() for name in socket_names if str(name or "").strip()}
    else:
        target_names = {
            socket.name.casefold()
            for socket in tuple(base_document.sockets or ())
            if str(socket.name or "").strip() and socket.name.casefold() in profile_sockets
        }
    target_names.discard("")
    if not target_names or not profile_sockets:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))

    diffs: List[AttachmentPartInOutPatchDiff] = []
    patched_names: List[str] = []

    def profile_value(socket: AttachmentSocketInfo, field_name: str) -> str:
        if field_name == "Parent":
            return str(socket.parent or "")
        if field_name == "Rotation":
            return " ".join(f"{float(value):.6f}" for value in tuple(socket.rotation or ()))
        if field_name == "Translation":
            return " ".join(f"{float(value):.6f}" for value in tuple(socket.translation or ()))
        if field_name == "UIView":
            return str(socket.ui_view or "")
        return ""

    def replace_tag(match: re.Match[str]) -> str:
        tag_text = match.group(0)
        attrs = _parse_part_in_out_attrs(str(match.group("attrs") or ""))
        socket_name = str(attrs.get("Name") or "").strip()
        key = socket_name.casefold()
        profile_socket = profile_sockets.get(key)
        if key not in target_names or profile_socket is None:
            return tag_text
        updated = tag_text
        changed = False
        for field_name in fields:
            new_value = profile_value(profile_socket, field_name)
            if not new_value and field_name == "UIView" and field_name not in attrs:
                continue
            old_value = _part_in_out_attr_value(attrs, field_name)
            if old_value == new_value:
                continue
            updated = _part_in_out_set_attr(updated, field_name, new_value)
            diffs.append(AttachmentPartInOutPatchDiff(socket_name, field_name, old_value, new_value))
            changed = True
        if changed:
            patched_names.append(socket_name)
        return updated

    patched_text = _SOCKET_BONE_SOCKET_TAG_RE.sub(replace_tag, str(base_text or ""))
    return AttachmentPartInOutPatchResult(
        text=patched_text,
        diffs=tuple(diffs),
        patched_part_names=tuple(dict.fromkeys(patched_names)),
    )


def _iter_prefab_length_prefixed_ascii_values(
    data: bytes,
    *,
    start_offset: int,
    max_length: int = 260,
) -> Iterator[Tuple[int, int, str]]:
    for length_offset in range(max(0, start_offset), max(0, len(data) - 4)):
        length = struct.unpack_from("<I", data, length_offset)[0]
        if length < 4 or length > max_length:
            continue
        value_offset = length_offset + 4
        value_end = value_offset + length
        if value_end > len(data):
            continue
        raw_value = data[value_offset:value_end]
        if not raw_value or any(byte < 0x20 or byte > 0x7E for byte in raw_value):
            continue
        text = raw_value.decode("ascii", errors="ignore")
        if not text or sum(1 for char in text if char.isalpha()) <= 0:
            continue
        yield length_offset, length, text


def inspect_prefab_socket_name_fields(data: bytes) -> Tuple[PrefabSocketNameField, ...]:
    """Recover the two prefab socket-name value records when their layout is proven.

    The proven safe subset is intentionally narrow: the prefab must declare the
    `_attachedSocketName` and `_pivotSocketName` members as strings, and the
    value block must then expose two length-prefixed socket strings in the same
    order. This matches the original two-hand prefabs and the working 2H-to-1H
    loose mod samples.
    """
    schema = _binary_sidecar_schema_declarations(data, ".prefab")
    rows = tuple(schema.get("declared_member_rows", ()) if isinstance(schema, Mapping) else ())
    row_by_name = {str(row.get("name") or ""): row for row in rows if isinstance(row, Mapping)}
    attached_row = row_by_name.get("_attachedSocketName")
    pivot_row = row_by_name.get("_pivotSocketName")
    if not isinstance(attached_row, Mapping) or not isinstance(pivot_row, Mapping):
        return ()
    if str(attached_row.get("declared_type") or "").casefold() not in {"indexedstringa", "staticstringa"}:
        return ()
    if str(pivot_row.get("declared_type") or "").casefold() not in {"indexedstringa", "staticstringa"}:
        return ()
    try:
        value_scan_start = max(
            int(row.get("descriptor_offset") or 0) + 8
            for row in rows
            if isinstance(row, Mapping)
        )
    except ValueError:
        value_scan_start = 0

    socket_records: List[Tuple[int, int, str]] = []
    for length_offset, length, text in _iter_prefab_length_prefixed_ascii_values(data, start_offset=value_scan_start):
        lowered = text.casefold()
        if (
            "socket" not in lowered
            or text.startswith("_")
            or "/" in text
            or "\\" in text
            or "." in text
        ):
            continue
        socket_records.append((length_offset, length, text))
        if len(socket_records) >= 2:
            break
    if len(socket_records) < 2:
        return ()
    attached_offset, attached_length, attached_text = socket_records[0]
    pivot_offset, pivot_length, pivot_text = socket_records[1]
    if "childsocket" in attached_text.casefold():
        return ()
    if pivot_offset <= attached_offset:
        return ()
    return (
        PrefabSocketNameField(
            field_name="_attachedSocketName",
            value=attached_text,
            length_offset=attached_offset,
            value_offset=attached_offset + 4,
            byte_length=attached_length,
        ),
        PrefabSocketNameField(
            field_name="_pivotSocketName",
            value=pivot_text,
            length_offset=pivot_offset,
            value_offset=pivot_offset + 4,
            byte_length=pivot_length,
        ),
    )


def inspect_prefab_attachment_profile_fields(data: bytes) -> Tuple[PrefabSocketNameField, ...]:
    """Recover target prefab placement/role value records from the proven value block.

    The socket fields alone move a prefab. The following part-name/socket-file
    records tell the game which weapon role profile owns that moved prefab.
    Copying these two records from a 1H/2H source lets one selected target use
    the source placement role while keeping the target model path untouched.
    """
    socket_fields = inspect_prefab_socket_name_fields(data)
    if len(socket_fields) != 2:
        return ()
    pivot_field = socket_fields[1]
    scan_start = pivot_field.value_offset + pivot_field.byte_length
    part_field: Optional[PrefabSocketNameField] = None
    model_field: Optional[PrefabSocketNameField] = None
    socket_file_field: Optional[PrefabSocketNameField] = None
    for length_offset, length, text in _iter_prefab_length_prefixed_ascii_values(data, start_offset=scan_start):
        lowered = text.casefold()
        if part_field is None and text.startswith("CD_") and "/" not in text and "\\" not in text and "." not in text:
            part_field = PrefabSocketNameField(
                field_name="_partName",
                value=text,
                length_offset=length_offset,
                value_offset=length_offset + 4,
                byte_length=length,
            )
            continue
        if model_field is None and "/" in text and lowered.endswith((".pac", ".pam", ".pamlod")):
            model_field = PrefabSocketNameField(
                field_name="_skinnedMeshFileName",
                value=text,
                length_offset=length_offset,
                value_offset=length_offset + 4,
                byte_length=length,
            )
            continue
        if socket_file_field is None and "/" in text and lowered.endswith(".sockets.xml"):
            socket_file_field = PrefabSocketNameField(
                field_name="_socketFileName",
                value=text,
                length_offset=length_offset,
                value_offset=length_offset + 4,
                byte_length=length,
            )
            break
    fields: List[PrefabSocketNameField] = list(socket_fields)
    if isinstance(part_field, PrefabSocketNameField):
        fields.append(part_field)
    if isinstance(model_field, PrefabSocketNameField):
        fields.append(model_field)
    if isinstance(socket_file_field, PrefabSocketNameField):
        fields.append(socket_file_field)
    return tuple(fields)


def _validate_prefab_socket_name_replacement(field: PrefabSocketNameField, value: str) -> bytes:
    text = str(value or "").strip()
    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field.field_name} must be ASCII for a safe prefab socket-name rewrite.") from exc
    if not text or any(byte < 0x20 or byte > 0x7E for byte in encoded):
        raise ValueError(f"{field.field_name} contains characters that are unsafe for this prefab string slot.")
    if "socket" not in text.casefold() or "/" in text or "\\" in text or "." in text:
        raise ValueError(f"{field.field_name} replacement must be a socket name, not a path.")
    if len(encoded) != field.byte_length:
        raise ValueError(
            f"{field.field_name} replacement must be exactly {field.byte_length} byte(s) for the proven safe prefab rewrite; "
            f"{text!r} is {len(encoded)} byte(s)."
        )
    return encoded


def _validate_prefab_attachment_profile_replacement(field: PrefabSocketNameField, value: str) -> bytes:
    text = str(value or "").strip()
    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field.field_name} must be ASCII for a safe prefab profile rewrite.") from exc
    if not text or any(byte < 0x20 or byte > 0x7E for byte in encoded):
        raise ValueError(f"{field.field_name} contains characters that are unsafe for this prefab string slot.")
    lowered = text.casefold()
    if field.field_name in {"_attachedSocketName", "_pivotSocketName"}:
        if "socket" not in lowered or "/" in text or "\\" in text or "." in text:
            raise ValueError(f"{field.field_name} replacement must be a socket name, not a path.")
    elif field.field_name == "_partName":
        if not text.startswith("CD_") or "/" in text or "\\" in text or "." in text:
            raise ValueError("_partName replacement must be a Crimson part role such as CD_MainWeapon_Sword_R.")
    elif field.field_name == "_socketFileName":
        if "/" not in text or not lowered.endswith(".sockets.xml"):
            raise ValueError("_socketFileName replacement must be a socket descriptor path ending in .sockets.xml.")
    else:
        raise ValueError(f"{field.field_name} is not editable in a prefab placement profile patch.")
    if len(encoded) > 260:
        raise ValueError(f"{field.field_name} replacement is too long for the prefab placement profile patch.")
    return encoded


def build_prefab_socket_name_patch(
    data: bytes,
    *,
    attached_socket_name: str = "",
    pivot_socket_name: str = "",
) -> PrefabSocketNamePatchResult:
    fields = inspect_prefab_socket_name_fields(data)
    if len(fields) != 2:
        raise ValueError("Prefab socket-name fields were not proven safe to edit.")
    replacements = {
        "_attachedSocketName": attached_socket_name,
        "_pivotSocketName": pivot_socket_name,
    }
    patched = bytearray(data)
    proof_lines: List[str] = [
        "Prefab declares _attachedSocketName and _pivotSocketName as string members.",
        "Socket values were recovered as length-prefixed ASCII records in prefab value order.",
        "Patch is same-length only, so no binary offsets or trailing record positions move.",
    ]
    for field in fields:
        replacement = str(replacements.get(field.field_name) or field.value)
        encoded = _validate_prefab_socket_name_replacement(field, replacement)
        patched[field.value_offset:field.value_offset + field.byte_length] = encoded
        proof_lines.append(f"{field.field_name}: {field.value} -> {replacement}")
    return PrefabSocketNamePatchResult(data=bytes(patched), fields=fields, proof_lines=tuple(proof_lines))


def build_prefab_attachment_profile_patch(
    data: bytes,
    *,
    attached_socket_name: str = "",
    pivot_socket_name: str = "",
    part_name: str = "",
    socket_file_path: str = "",
    allow_length_changes: bool = False,
) -> PrefabAttachmentProfilePatchResult:
    fields = inspect_prefab_attachment_profile_fields(data)
    if len(fields) < 2:
        raise ValueError("Prefab placement profile fields were not proven safe to edit.")
    fields_by_name = {field.field_name: field for field in fields}
    replacements = {
        "_attachedSocketName": attached_socket_name,
        "_pivotSocketName": pivot_socket_name,
        "_partName": part_name,
        "_socketFileName": socket_file_path,
    }
    edits: List[Tuple[PrefabSocketNameField, bytes]] = []
    proof_lines: List[str] = [
        "Prefab declares _attachedSocketName and _pivotSocketName as string members.",
        "Placement role records were recovered as length-prefixed ASCII values in prefab value order.",
        "Target model path is preserved; only placement sockets, part role, and optional socket descriptor path are rewritten.",
        (
            "Patch is same-length only, so no binary offsets or trailing record positions move."
            if not allow_length_changes
            else "Length-changing prefab rewrite via the exact pointer-relocation path."
        ),
    ]
    for field_name in ("_attachedSocketName", "_pivotSocketName", "_partName", "_socketFileName"):
        field = fields_by_name.get(field_name)
        if not isinstance(field, PrefabSocketNameField):
            continue
        replacement = str(replacements.get(field_name) or "").strip()
        if not replacement or replacement == field.value:
            continue
        encoded = _validate_prefab_attachment_profile_replacement(field, replacement)
        if len(encoded) != field.byte_length and not allow_length_changes:
            raise ValueError(
                "Unsafe prefab rewrite blocked: replacement would resize target prefab "
                f"({field.field_name} {field.byte_length} -> {len(encoded)} bytes)."
            )
        edits.append((field, encoded, replacement))
        proof_lines.append(f"{field.field_name}: {field.value} -> {replacement}")
    if not edits:
        return PrefabAttachmentProfilePatchResult(
            data=bytes(data or b""),
            fields=fields,
            changed_fields=(),
            proof_lines=tuple(proof_lines + ["No prefab placement profile values changed."]),
        )
    patched = bytearray(data or b"")
    changed_fields: List[PrefabSocketNameField] = []
    if allow_length_changes:
        # This used to splice each new length-prefixed record over the old span
        # and stop there. Every absolute pointer after the edit then addressed
        # the wrong byte, and no pointee length field or data-header size was
        # touched -- a corrupted prefab, produced by a checkbox. The exact
        # rewriter relocates all of it, and is validated against the game's own
        # authoring tool on 10,066 of 10,066 length-changing vanilla pairs.
        from cdmw.core.prefab_binary import PrefabBinaryError
        from cdmw.core.prefab_binary_edit import PrefabPathEdit, rewrite_prefab_paths

        try:
            rewrite = rewrite_prefab_paths(
                bytes(data or b""),
                [
                    PrefabPathEdit(offset=field.length_offset, old_text=field.value, new_text=text)
                    for field, _encoded, text in edits
                ],
            )
        except PrefabBinaryError as exc:
            raise ValueError(
                "Changing a socket name to a different length needs a prefab this tool "
                f"can read all the way through, and this one stopped: {exc}. Same-length "
                "replacements still work, and do not move any bytes."
            ) from exc
        patched = bytearray(rewrite.data)
        changed_fields.extend(field for field, _encoded, _text in edits)
        proof_lines.extend(rewrite.proof_lines)
        proof_lines.append(
            f"Prefab stream length {len(data or b''):,} -> {len(patched):,}."
        )
    else:
        for field, encoded, _text in edits:
            patched[field.value_offset : field.value_offset + field.byte_length] = encoded
            changed_fields.append(field)
        proof_lines.append(f"Prefab stream length preserved at {len(patched):,} bytes.")
    return PrefabAttachmentProfilePatchResult(
        data=bytes(patched),
        fields=fields,
        changed_fields=tuple(reversed(changed_fields)),
        proof_lines=tuple(proof_lines),
    )
