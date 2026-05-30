from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Mapping, Sequence, Tuple

from cdmw.models import AttachmentPartInOutPatchDiff, AttachmentPartInOutPatchResult


@dataclass(frozen=True, slots=True)
class WeaponSwapSocketRow:
    name: str
    parent: str
    rotation: Tuple[float, float, float, float]
    translation: Tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class WeaponSwapTemplate:
    template_id: str
    label: str
    description: str
    supported_scopes: Tuple[str, ...]
    supported_weapon_classes: Tuple[str, ...]
    risk_level: str = "stable"
    socket_rows: Tuple[WeaponSwapSocketRow, ...] = ()
    weapon_socket_rows: Tuple[WeaponSwapSocketRow, ...] = ()
    touches_iteminfo: bool = False
    touches_paac: bool = False
    touches_hkx: bool = False
    includes_motion_aliases: bool = False
    advanced_only: bool = False


@dataclass(frozen=True, slots=True)
class WeaponSwapValidatedWeapon:
    display_name: str
    model_stem: str
    sheath_stem: str = ""
    note: str = ""


TWOHAND_HIP_TILT_ROTATION: Tuple[float, float, float, float] = (0.0, 0.382683, 0.0, 0.923880)
TWOHAND_HIP_TILT_TRANSLATION: Tuple[float, float, float] = (0.0, 0.0, -0.150000)
TWOHAND_HORSE_BASELINE_PACKAGE = "all2h-as-1h motion-alias-v43-horse-spinefallbackhip-darkbringer-sheath-tilt45-5700"
TWOHAND_HORSE_RELEASE_FIX_VARIANT = "heldattack-v51A-currentvanillapaac-hipsocket"
TWOHAND_HORSE_PAAC_PATCH_NOTE = "v51A current original mounted 2H PAAC graph plus same-length hip socket retarget"
TWOHAND_HORSE_PAAC_PATH = "actionchart/bin__/upperaction/1_pc/1_phm/ride_weapon_twohandsword_upper.paac"
TWOHAND_HORSE_PAAC_BACK_SOCKET = b"Spine2_B_SubWeapon_Socket"
TWOHAND_HORSE_PAAC_HIP_SOCKET = b"Pelvis_L_SubWeapon_Socket"
TWOHAND_HORSE_FALLBACK_SOCKET_PARENT = "B_WeaponIn_R_00"
TWOHAND_HORSE_FALLBACK_SOCKET_ROTATION: Tuple[float, float, float, float] = (0.0, 0.216440, 0.0, 0.976296)
TWOHAND_HORSE_FALLBACK_SOCKET_TRANSLATION: Tuple[float, float, float] = (0.0, 0.0, 0.020000)
TWOHAND_TESTED_V43_WEAPONS: Tuple[WeaponSwapValidatedWeapon, ...] = (
    WeaponSwapValidatedWeapon(
        "Darkbringer",
        "cd_phm_02_sword_0015",
        "cd_phm_02_sword_0015_in",
        "Needs the v43 dedicated sheath socket sidecar.",
    ),
    WeaponSwapValidatedWeapon(
        "Rhett's Longsword",
        "cd_phm_02_sword_0009",
        "cd_phm_02_sword_0001_in",
        "Known item-index internal name: Rayhorn_TwoHandSword.",
    ),
    WeaponSwapValidatedWeapon(
        "Vessel of Dark Pursuit",
        "cd_phm_02_sword_0014",
        "",
        "Known item-index internal name: DarkLeader_TwoHandSword; confirm final display-name mapping if the item index changes.",
    ),
    WeaponSwapValidatedWeapon(
        "Hwando",
        "cd_phm_02_sword_0036",
        "cd_phm_02_sword_0036_in",
        "Known item-index internal name: Hwando_TwoHandSword.",
    ),
)

DUAL_BACK_BASELINE_PACKAGE = "dual1h-back-cross-sheath-v27A-revpitch8-yminus050-v18shielddraw"
DUAL_BACK_SHIELD_DRAW_PAA_SOURCE_PATH = "character/motion/1_pc/1_phm/cd_phm_longsword_00_01_normal_stand_weapon_out_000.paa"
DUAL_BACK_SHIELD_DRAW_PAA_TARGET_PATH = "character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_out_004.paa"
DUAL_BACK_SHIELD_DRAW_META_SOURCE_PATH = "actionchart/bin__/animmeta/1_pc/1_phm/cd_phm_dualsword_00_01_nor_stand_weapon_out_00.paa_metabin"
DUAL_BACK_SHIELD_DRAW_META_TARGET_PATH = "actionchart/bin__/animmeta/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_out_004.paa_metabin"
DUAL_BACK_RIGHT_ROTATION: Tuple[float, float, float, float] = (0.191043, -0.659543, 0.706874, -0.169808)
DUAL_BACK_CROSSED_LEFT_ROTATION: Tuple[float, float, float, float] = (-0.210303, -0.653956, 0.709543, 0.157044)
# Learned from dual1h v27A: v23A crossed placement plus v18 shield draw PAA to avoid the dlsd attack-stance regression.
DUAL_BACK_RIGHT_TRANSLATION: Tuple[float, float, float] = (-0.080000, -0.050000, 0.045000)
DUAL_BACK_LEFT_TRANSLATION: Tuple[float, float, float] = (0.050000, -0.050000, 0.035000)
DUAL_BACK_RIGHT_CHILD_ROTATION: Tuple[float, float, float, float] = (0.0, 1.0, 0.0, 0.0)
DUAL_BACK_LEFT_CHILD_ROTATION: Tuple[float, float, float, float] = (0.0, -1.0, 0.0, 0.0)
DUAL_BACK_CHILD_TRANSLATION: Tuple[float, float, float] = (0.0, 0.0, -0.360000)

WEAPON_SWAP_TEMPLATE_SELECTED_SCOPE = "selected_pac"
WEAPON_SWAP_TEMPLATE_SELECTION_SCOPE = "selected_archive_rows"
WEAPON_SWAP_TEMPLATE_CLASS_SCOPE = "class_wide_phm"


_TEMPLATES: Tuple[WeaponSwapTemplate, ...] = (
    WeaponSwapTemplate(
        template_id="twohand_sword_hip_tilted",
        label="2H sword on hip, tilted",
        description="Class-wide PHM 2H sword hip placement with the learned 45 degree weapon-child tilt and v51A mounted PAAC socket fix.",
        supported_scopes=(WEAPON_SWAP_TEMPLATE_SELECTED_SCOPE, WEAPON_SWAP_TEMPLATE_CLASS_SCOPE),
        supported_weapon_classes=("twohand_sword",),
        socket_rows=(
            WeaponSwapSocketRow("Pelvis_L_ChildSocket", "B_Weapon_0001", TWOHAND_HIP_TILT_ROTATION, TWOHAND_HIP_TILT_TRANSLATION),
            WeaponSwapSocketRow("Pelvis_L_SubWeapon_ChildSocket", "B_Weapon_0001", TWOHAND_HIP_TILT_ROTATION, TWOHAND_HIP_TILT_TRANSLATION),
        ),
        touches_paac=True,
        includes_motion_aliases=True,
    ),
    WeaponSwapTemplate(
        template_id="twohand_sword_placement_only",
        label="2H sword placement only",
        description="Class-wide PHM 2H sword hip placement without motion aliases, ItemInfo, HKX, combat, model, texture, or icon changes.",
        supported_scopes=(WEAPON_SWAP_TEMPLATE_SELECTED_SCOPE, WEAPON_SWAP_TEMPLATE_CLASS_SCOPE),
        supported_weapon_classes=("twohand_sword",),
        socket_rows=(
            WeaponSwapSocketRow("Pelvis_L_ChildSocket", "B_Weapon_0001", TWOHAND_HIP_TILT_ROTATION, TWOHAND_HIP_TILT_TRANSLATION),
            WeaponSwapSocketRow("Pelvis_L_SubWeapon_ChildSocket", "B_Weapon_0001", TWOHAND_HIP_TILT_ROTATION, TWOHAND_HIP_TILT_TRANSLATION),
        ),
        touches_paac=True,
    ),
    WeaponSwapTemplate(
        template_id="dual_onehand_back_crossed",
        label="Dual 1H back crossed",
        description="Dual 1H swords on the PHM back using the shoulder-fix crossed baseline.",
        supported_scopes=(WEAPON_SWAP_TEMPLATE_CLASS_SCOPE,),
        supported_weapon_classes=("onehand_sword",),
        socket_rows=(
            WeaponSwapSocketRow("Spine2_R_Socket", "Bip_Weapon_Attach_In_02", DUAL_BACK_RIGHT_ROTATION, DUAL_BACK_RIGHT_TRANSLATION),
            WeaponSwapSocketRow("Spine2_L_Socket", "Bip_Weapon_Attach_In_02", DUAL_BACK_CROSSED_LEFT_ROTATION, DUAL_BACK_LEFT_TRANSLATION),
        ),
        weapon_socket_rows=(
            WeaponSwapSocketRow("Spine2_R_ChildSocket", "B_Weapon_0001", DUAL_BACK_RIGHT_CHILD_ROTATION, DUAL_BACK_CHILD_TRANSLATION),
            WeaponSwapSocketRow("Spine2_L_ChildSocket", "B_Weapon_0001", DUAL_BACK_LEFT_CHILD_ROTATION, DUAL_BACK_CHILD_TRANSLATION),
        ),
        includes_motion_aliases=True,
    ),
    WeaponSwapTemplate(
        template_id="dual_onehand_back_parallel",
        label="Dual 1H back parallel",
        description="Dual 1H swords on the PHM back using the shoulder-fix parallel baseline.",
        supported_scopes=(WEAPON_SWAP_TEMPLATE_CLASS_SCOPE,),
        supported_weapon_classes=("onehand_sword",),
        socket_rows=(
            WeaponSwapSocketRow("Spine2_R_Socket", "Bip_Weapon_Attach_In_02", DUAL_BACK_RIGHT_ROTATION, DUAL_BACK_RIGHT_TRANSLATION),
            WeaponSwapSocketRow("Spine2_L_Socket", "Bip_Weapon_Attach_In_02", DUAL_BACK_RIGHT_ROTATION, DUAL_BACK_LEFT_TRANSLATION),
        ),
        weapon_socket_rows=(
            WeaponSwapSocketRow("Spine2_R_ChildSocket", "B_Weapon_0001", DUAL_BACK_RIGHT_CHILD_ROTATION, DUAL_BACK_CHILD_TRANSLATION),
            WeaponSwapSocketRow("Spine2_L_ChildSocket", "B_Weapon_0001", DUAL_BACK_LEFT_CHILD_ROTATION, DUAL_BACK_CHILD_TRANSLATION),
        ),
        includes_motion_aliases=True,
    ),
    WeaponSwapTemplate(
        template_id="custom_selected_pac",
        label="Custom selected PAC placement",
        description="Use the target-owned placement builder for one selected PAC/model row.",
        supported_scopes=(WEAPON_SWAP_TEMPLATE_SELECTED_SCOPE, WEAPON_SWAP_TEMPLATE_SELECTION_SCOPE),
        supported_weapon_classes=("onehand_sword", "twohand_sword", "onehand_dagger", "axe", "mace", "spear"),
    ),
)


_TEMPLATES_BY_ID: Dict[str, WeaponSwapTemplate] = {template.template_id: template for template in _TEMPLATES}


def iter_weapon_swap_templates(*, include_advanced: bool = False) -> Tuple[WeaponSwapTemplate, ...]:
    if include_advanced:
        return _TEMPLATES
    return tuple(template for template in _TEMPLATES if not template.advanced_only)


def get_weapon_swap_template(template_id: object) -> WeaponSwapTemplate:
    key = str(template_id or "").strip()
    try:
        return _TEMPLATES_BY_ID[key]
    except KeyError as exc:
        raise KeyError(f"Unknown weapon swap template: {template_id!r}") from exc


def _quat_normalize(values: Sequence[float]) -> Tuple[float, float, float, float]:
    raw = tuple(float(value) for value in tuple(values or (0.0, 0.0, 0.0, 1.0))[:4])
    while len(raw) < 4:
        raw = (*raw, 0.0)
    length = math.sqrt(sum(value * value for value in raw))
    if not math.isfinite(length) or length <= 1e-8:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(value / length for value in raw)  # type: ignore[return-value]


def _quat_multiply(left: Sequence[float], right: Sequence[float]) -> Tuple[float, float, float, float]:
    lx, ly, lz, lw = _quat_normalize(left)
    rx, ry, rz, rw = _quat_normalize(right)
    return _quat_normalize(
        (
            (lw * rx) + (lx * rw) + (ly * rz) - (lz * ry),
            (lw * ry) - (lx * rz) + (ly * rw) + (lz * rx),
            (lw * rz) + (lx * ry) - (ly * rx) + (lz * rw),
            (lw * rw) - (lx * rx) - (ly * ry) - (lz * rz),
        )
    )


def _axis_quat(axis: str, degrees: float) -> Tuple[float, float, float, float]:
    half = math.radians(float(degrees)) * 0.5
    sine = math.sin(half)
    cosine = math.cos(half)
    if axis == "x":
        return (sine, 0.0, 0.0, cosine)
    if axis == "y":
        return (0.0, sine, 0.0, cosine)
    return (0.0, 0.0, sine, cosine)


def _euler_quat(rotation_degrees: Sequence[float]) -> Tuple[float, float, float, float]:
    values = tuple(float(value) for value in tuple(rotation_degrees or (0.0, 0.0, 0.0))[:3])
    while len(values) < 3:
        values = (*values, 0.0)
    quat = (0.0, 0.0, 0.0, 1.0)
    for axis, degrees in zip(("x", "y", "z"), values):
        quat = _quat_multiply(quat, _axis_quat(axis, degrees))
    return quat


def weapon_swap_template_socket_rows(
    template_id: object,
    *,
    translation_delta: Sequence[float] = (),
    rotation_delta_degrees: Sequence[float] = (),
    dual_left_rotation_delta_degrees: Sequence[float] = (),
    dual_center_delta: float = 0.0,
    dual_spread_delta: float = 0.0,
    dual_body_distance_delta: float = 0.0,
    dual_height_delta: float = 0.0,
) -> Tuple[WeaponSwapSocketRow, ...]:
    template = get_weapon_swap_template(template_id)
    delta = tuple(float(value) for value in tuple(translation_delta or (0.0, 0.0, 0.0))[:3])
    while len(delta) < 3:
        delta = (*delta, 0.0)
    rotation_delta = _euler_quat(rotation_delta_degrees)
    rows = []
    for row in template.socket_rows:
        translation = (
            float(row.translation[0]) + delta[0],
            float(row.translation[1]) + delta[1],
            float(row.translation[2]) + delta[2],
        )
        if row.name in {"Spine2_R_Socket", "Spine2_L_Socket"}:
            side = -1.0 if row.name == "Spine2_R_Socket" else 1.0
            # Dual back tests v12/v13 showed body socket Y controls height; weapon child Z also moves vertical.
            # Keep body distance on body socket Z so close-body tests do not disturb learned height.
            translation = (
                translation[0] + float(dual_center_delta) + (side * float(dual_spread_delta)),
                translation[1] + float(dual_height_delta),
                translation[2] + float(dual_body_distance_delta),
            )
        row_rotation_delta = rotation_delta
        if row.name == "Spine2_L_Socket":
            row_rotation_delta = _quat_multiply(_euler_quat(dual_left_rotation_delta_degrees), row_rotation_delta)
        rows.append(
            WeaponSwapSocketRow(
                row.name,
                row.parent,
                _quat_multiply(row_rotation_delta, row.rotation),
                translation,
            )
        )
    return tuple(rows)


def twohand_sword_v43_character_socket_rows() -> Tuple[WeaponSwapSocketRow, ...]:
    return (
        WeaponSwapSocketRow(
            "Spine2_B_SubWeapon_Socket",
            TWOHAND_HORSE_FALLBACK_SOCKET_PARENT,
            TWOHAND_HORSE_FALLBACK_SOCKET_ROTATION,
            TWOHAND_HORSE_FALLBACK_SOCKET_TRANSLATION,
        ),
    )


def twohand_sword_v43_weapon_socket_rows() -> Tuple[WeaponSwapSocketRow, ...]:
    return (
        WeaponSwapSocketRow(
            "Spine2_B_SubWeapon_ChildSocket",
            "B_Weapon_0001",
            TWOHAND_HIP_TILT_ROTATION,
            TWOHAND_HIP_TILT_TRANSLATION,
        ),
    )


def twohand_sword_v43_socket_sidecar_paths() -> Tuple[str, ...]:
    base = "character/descriptors/socketbonedata/1_pc/1_phm/weapon/2_twohandweapon"
    paths = [
        f"{base}/cd_phm_02_sword_0001.sockets.xml",
        f"{base}/cd_phm_02_sword_0001_in.sockets.xml",
    ]
    for weapon in TWOHAND_TESTED_V43_WEAPONS:
        if weapon.sheath_stem and weapon.sheath_stem != "cd_phm_02_sword_0001_in":
            paths.append(f"{base}/{weapon.sheath_stem}.sockets.xml")
    return tuple(dict.fromkeys(paths))


def twohand_sword_v43_known_weapon_summary() -> str:
    return "; ".join(
        f"{weapon.display_name} ({weapon.model_stem}{', sheath ' + weapon.sheath_stem if weapon.sheath_stem else ''})"
        for weapon in TWOHAND_TESTED_V43_WEAPONS
    )


def patch_twohand_horse_paac_socket_bytes(data: bytes) -> Tuple[bytes, int]:
    """Apply the v51A mounted 2H fix: keep current PAAC graph, retarget only the socket bytes."""
    payload = bytes(data or b"")
    if len(TWOHAND_HORSE_PAAC_BACK_SOCKET) != len(TWOHAND_HORSE_PAAC_HIP_SOCKET):
        raise ValueError("2H horse PAAC socket replacement must be same length.")
    count = payload.count(TWOHAND_HORSE_PAAC_BACK_SOCKET)
    if count <= 0:
        return payload, 0
    return payload.replace(TWOHAND_HORSE_PAAC_BACK_SOCKET, TWOHAND_HORSE_PAAC_HIP_SOCKET), count


def weapon_swap_template_weapon_socket_rows(template_id: object) -> Tuple[WeaponSwapSocketRow, ...]:
    return tuple(get_weapon_swap_template(template_id).weapon_socket_rows)


def _format_vector(values: Sequence[float]) -> str:
    return " ".join(f"{float(value):.6f}" for value in tuple(values))


def _find_socket_list(root: ET.Element) -> ET.Element:
    for element in root.iter():
        if str(element.tag).rsplit("}", 1)[-1] == "SocketList":
            return element
    raise ValueError("SocketBoneData XML does not contain a SocketList.")


def build_socket_bone_weapon_swap_rows_patch(
    base_text: str,
    rows: Sequence[WeaponSwapSocketRow],
) -> AttachmentPartInOutPatchResult:
    rows = tuple(rows or ())
    if not rows:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))
    root = ET.fromstring(str(base_text or ""))
    socket_list = _find_socket_list(root)
    sockets_by_name = {
        str(element.attrib.get("Name", "") or "").strip().casefold(): element
        for element in list(socket_list)
        if str(element.tag).rsplit("}", 1)[-1] == "Socket" and str(element.attrib.get("Name", "") or "").strip()
    }
    diffs = []
    patched_names = []
    for row in rows:
        key = row.name.casefold()
        element = sockets_by_name.get(key)
        added = False
        if element is None:
            element = ET.SubElement(socket_list, "Socket")
            element.set("Name", row.name)
            added = True
        for field_name, new_value in (
            ("Parent", row.parent),
            ("Rotation", _format_vector(row.rotation)),
            ("Translation", _format_vector(row.translation)),
        ):
            old_value = str(element.attrib.get(field_name, "") or "")
            if old_value != new_value:
                element.set(field_name, new_value)
                diffs.append(AttachmentPartInOutPatchDiff(row.name, field_name, old_value, new_value))
        if added:
            diffs.append(AttachmentPartInOutPatchDiff(row.name, "Socket", "", "added"))
        patched_names.append(row.name)
    socket_count = sum(1 for element in list(socket_list) if str(element.tag).rsplit("}", 1)[-1] == "Socket")
    socket_list.set("Count", str(socket_count))
    try:
        ET.indent(root, space="\t")
    except AttributeError:
        pass
    return AttachmentPartInOutPatchResult(
        text=ET.tostring(root, encoding="unicode"),
        diffs=tuple(diffs),
        patched_part_names=tuple(dict.fromkeys(patched_names)),
    )


def build_socket_bone_weapon_swap_template_patch(
    base_text: str,
    template_id: object,
    *,
    translation_delta: Sequence[float] = (),
    rotation_delta_degrees: Sequence[float] = (),
    dual_left_rotation_delta_degrees: Sequence[float] = (),
    dual_center_delta: float = 0.0,
    dual_spread_delta: float = 0.0,
    dual_body_distance_delta: float = 0.0,
    dual_height_delta: float = 0.0,
) -> AttachmentPartInOutPatchResult:
    rows = weapon_swap_template_socket_rows(
        template_id,
        translation_delta=translation_delta,
        rotation_delta_degrees=rotation_delta_degrees,
        dual_left_rotation_delta_degrees=dual_left_rotation_delta_degrees,
        dual_center_delta=dual_center_delta,
        dual_spread_delta=dual_spread_delta,
        dual_body_distance_delta=dual_body_distance_delta,
        dual_height_delta=dual_height_delta,
    )
    return build_socket_bone_weapon_swap_rows_patch(base_text, rows)


_PART_IN_OUT_TAG_RE = re.compile(r"<PartInOutSocket\b(?P<attrs>[^<>]*)/?>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(['\"])(.*?)\2", re.DOTALL)


def _attrs(text: str) -> Dict[str, str]:
    return {match.group(1): match.group(3) for match in _ATTR_RE.finditer(str(text or ""))}


def _set_attr(tag_text: str, name: str, value: str) -> str:
    pattern = re.compile(rf"(\b{re.escape(name)}\s*=\s*)(['\"])(.*?)\2", re.IGNORECASE | re.DOTALL)
    escaped = str(value or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    if pattern.search(tag_text):
        return pattern.sub(lambda match: f'{match.group(1)}"{escaped}"', tag_text, count=1)
    insert_at = tag_text.rfind("/>")
    if insert_at < 0:
        insert_at = tag_text.rfind(">")
    if insert_at < 0:
        return tag_text
    spacer = "" if tag_text[:insert_at].endswith((" ", "\t", "\n", "\r")) else " "
    return f'{tag_text[:insert_at]}{spacer}{name}="{escaped}"{tag_text[insert_at:]}'


def build_part_in_out_weapon_swap_template_patch(
    base_text: str,
    template_id: object,
) -> AttachmentPartInOutPatchResult:
    template = get_weapon_swap_template(template_id)
    if template.template_id not in {"dual_onehand_back_crossed", "dual_onehand_back_parallel"}:
        return AttachmentPartInOutPatchResult(text=str(base_text or ""))
    desired: Mapping[str, Mapping[str, str]] = {
        "CD_MainWeapon_Sword_R": {
            "InSocketBone": "Spine2_R_Socket",
            "InChildSocketBone": "Spine2_R_ChildSocket",
            "WeaponCasePart": "CD_MainWeapon_Sword_IN_R",
        },
        "CD_MainWeapon_Sword_IN_R": {
            "InSocketBone": "Spine2_R_Socket",
            "OutSocketBone": "Spine2_R_Socket",
            "InChildSocketBone": "Spine2_R_ChildSocket",
            "OutChildSocketBone": "Spine2_R_ChildSocket",
        },
        "CD_MainWeapon_Sword_L": {
            "InSocketBone": "Spine2_L_Socket",
            "InChildSocketBone": "Spine2_L_ChildSocket",
            "WeaponCasePart": "CD_MainWeapon_Sword_IN_L",
        },
        "CD_MainWeapon_Sword_IN_L": {
            "InSocketBone": "Spine2_L_Socket",
            "OutSocketBone": "Spine2_L_Socket",
            "InChildSocketBone": "Spine2_L_ChildSocket",
            "OutChildSocketBone": "Spine2_L_ChildSocket",
        },
        "CD_MainWeapon_Sword_R_Aux": {
            "InSocketBone": "Spine2_L_Socket",
            "InChildSocketBone": "Spine2_L_ChildSocket",
            "WeaponCasePart": "CD_MainWeapon_Sword_IN_R_Aux",
        },
        "CD_MainWeapon_Sword_IN_R_Aux": {
            "InSocketBone": "Spine2_L_Socket",
            "OutSocketBone": "Spine2_L_Socket",
            "InChildSocketBone": "Spine2_L_ChildSocket",
            "OutChildSocketBone": "Spine2_L_ChildSocket",
        },
    }
    diffs = []
    patched_names = []

    def replace(match: re.Match[str]) -> str:
        tag_text = match.group(0)
        current_attrs = _attrs(str(match.group("attrs") or ""))
        part_name = str(current_attrs.get("PartName") or "").strip()
        fields = desired.get(part_name)
        if fields is None:
            return tag_text
        updated = tag_text
        changed = False
        for field_name, new_value in fields.items():
            old_value = str(current_attrs.get(field_name) or "")
            if old_value == new_value:
                continue
            updated = _set_attr(updated, field_name, new_value)
            diffs.append(AttachmentPartInOutPatchDiff(part_name, field_name, old_value, new_value))
            changed = True
        if changed:
            patched_names.append(part_name)
        return updated

    patched_text = _PART_IN_OUT_TAG_RE.sub(replace, str(base_text or ""))
    return AttachmentPartInOutPatchResult(
        text=patched_text,
        diffs=tuple(diffs),
        patched_part_names=tuple(dict.fromkeys(patched_names)),
    )
