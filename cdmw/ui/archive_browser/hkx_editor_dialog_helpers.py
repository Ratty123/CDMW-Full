"""Pure formatting helpers for the HKX editor dialog."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable, Mapping
from typing import Dict, List, Optional, Tuple

from PySide6.QtGui import QColor

from cdmw.models import (
    HkxPhysicsOverlayAnchor,
    HkxPhysicsOverlayBone,
    HkxPhysicsOverlayConstraint,
    HkxPhysicsOverlayData,
    HkxPhysicsOverlayShape,
    ModelPreviewData,
)


def hkx_status_display(status: object) -> Tuple[str, str, QColor]:
    status_key = str(status or "").strip().lower()
    if status_key == "editable":
        return (
            "Patchable",
            "Fixed-size value locations are mapped and can be edited through the CDMW patch path.",
            QColor("#9fd0ff"),
        )
    if status_key == "decoded":
        return (
            "Decoded",
            "Payload rows are decoded for browsing/export, but exact official hkClass member metadata may still be pending.",
            QColor("#86efac"),
        )
    if status_key == "partially_decoded":
        return (
            "Partially decoded",
            "CDMW recovered some fields/bytes for browsing, but official Havok member names, owner links, or safe patch sites are incomplete. Edit only rows marked Patchable.",
            QColor("#fde68a"),
        )
    if status_key in {"raw_preserved", "raw"}:
        return (
            "Raw preserved",
            "Bytes are preserved safely, but no stable structured decoder is available yet.",
            QColor("#fca5a5"),
        )
    return (
        str(status or "Unknown"),
        "Decoder status reported by the HKX converter.",
        QColor("#cbd5e1"),
    )


def hkx_confidence_color(confidence: object) -> QColor:
    confidence_key = str(confidence or "").strip().lower()
    if confidence_key in {"confirmed", "descriptor_context", "descriptor-context"}:
        return QColor("#86efac")
    if confidence_key in {"strong inference", "strong_inference", "skeleton_context"}:
        return QColor("#fde68a")
    if confidence_key in {"experimental", "raw", "raw_preserved"}:
        return QColor("#fca5a5")
    return QColor("#cbd5e1")


def hkx_numeric_text_kind(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped:
        return ""
    if re.search(r"(?:#record\d+|record\s+\d+|viewer=|shape/\d+|constraint/\d+|anchor/\d+|bone/\d+)", stripped, re.IGNORECASE):
        return "reference"
    if re.fullmatch(r"0x[0-9a-fA-F]+", stripped):
        return "offset"
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", stripped):
        return "number"
    if re.search(r"(?:^|\s)[xyzw]=[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", stripped):
        return "vector"
    if "->" in stripped and re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", stripped):
        return "before_after"
    if re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", stripped):
        return "mixed"
    return ""


def format_hkx_display_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "->" in text:
        before, after = (part.strip() for part in text.split("->", 1))
        before_fmt = format_hkx_display_value(before)
        after_fmt = format_hkx_display_value(after)
        delta = ""
        try:
            delta_value = float(after) - float(before)
            if math.isfinite(delta_value) and abs(delta_value) > 1e-12:
                delta = f" (delta {delta_value:.6g})"
        except (TypeError, ValueError, OverflowError):
            delta = ""
        return f"{before_fmt} -> {after_fmt}{delta}".strip()
    offset_match = re.fullmatch(r"0x[0-9a-fA-F]+", text)
    if offset_match:
        return "0x" + text[2:].upper().zfill(2)
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        try:
            numeric_value = float(text)
            if math.isfinite(numeric_value):
                return f"{numeric_value:.8g}"
        except (TypeError, ValueError, OverflowError):
            pass
    vector_match = re.fullmatch(r"[\[\(]?\s*([xyzwrgbauv][=:][^;,\]\)]+[\s;,]*){2,}[\]\)]?", text, re.IGNORECASE)
    if vector_match:
        parts = []
        for token in re.split(r"[;,]\s*|\s+", text.strip("[]() ")):
            if not token or "=" not in token:
                continue
            key, raw_value = token.split("=", 1)
            parts.append(f"{key}={format_hkx_display_value(raw_value)}")
        if parts:
            return " ".join(parts)
    if re.fullmatch(r"(?:\d{1,3}\s+){2,}\d{1,3}", text):
        values = []
        for token in text.split():
            try:
                values.append(f"{int(token) & 0xFF:02X}")
            except (TypeError, ValueError, OverflowError):
                return text
        return "bytes " + " ".join(values)
    return text


def filter_terms(text: str) -> List[str]:
    return [term for term in re.split(r"\s+", str(text or "").strip().casefold()) if term]


def row_matches_filter_terms(row_text: str, needle: str) -> bool:
    terms = filter_terms(needle)
    if not terms:
        return True
    haystack = str(row_text or "").casefold()
    return all(term in haystack for term in terms)


def friendly_hkx_value_meaning(data: Mapping[str, object]) -> str:
    haystack = " ".join(
        str(data.get(key) or "")
        for key in (
            "field",
            "label",
            "name",
            "category",
            "kind",
            "effect",
            "explanation",
            "identity_path",
            "patch_path",
            "shape_type",
        )
    ).strip().casefold()
    if not haystack:
        return ""
    if any(token in haystack for token in ("capsule_radius", "sphere_radius", "radius=", " radius", "capsule size")):
        return "Collision size. Increasing it usually makes the physics volume larger around the linked shape."
    if any(token in haystack for token in ("capsule_endpoints", "endpoint", "extent", "length")):
        return "Collision shape extent. This usually changes capsule/box length or the local endpoints used by the shape."
    if any(token in haystack for token in ("body_transform", "orientation", "localrotation", "local_rotation", "localtranslation", "local_translation")):
        return "Body local transform/orientation. Small edits can move or rotate the physics body relative to its attachment frame."
    if any(token in haystack for token in ("mass", "inertia", "center_of_mass", "centerofmass")):
        return "Mass/inertia candidate. This affects how strongly the physics body resists movement or rotation."
    if "damping" in haystack:
        return "Damping value. Higher values usually reduce motion, swinging, or oscillation."
    if any(token in haystack for token in ("friction", "torque")):
        return "Constraint friction/torque response. This usually controls how strongly a joint resists free motion."
    if any(token in haystack for token in ("stiffness", "strength", "motor", "force")):
        return "Constraint or motor strength. This usually controls how aggressively a joint tries to hold or return to its target."
    if any(token in haystack for token in ("limit", "angle", "twist", "cone")):
        return "Joint angular limit. This usually controls allowed rotation range for a ragdoll/attachment joint."
    if any(token in haystack for token in ("material", "friction", "restitution")):
        return "Physics material context. This can affect collision response, friction, or bounce if the field is patchable."
    if any(token in haystack for token in ("vertex", "vertices", "plane", "hull", "topology", "primitive")):
        return "Collision geometry context. These rows describe shape geometry; only explicitly patchable rows should be edited."
    if any(token in haystack for token in ("shape_tag", "shape tag", "aabb", "tree")):
        return "Mesh-shape acceleration/tag data. This is mostly decoder context until the exact layout is proven."
    if "reference" in haystack or "#record" in haystack or "refptr" in haystack:
        return "Reference/link context. This tells what another HKX object points to; it is not directly editable yet."
    return ""


def workflow_search_text(element: ET.Element) -> str:
    parts = list(element.attrib.values())
    parts.extend(str(child.text or "") for child in list(element) if child.text)
    return " ".join(str(part or "") for part in parts).casefold()


def workflow_matches(text: str, workflow: Mapping[str, object]) -> bool:
    terms = tuple(str(term or "").casefold() for term in workflow.get("terms", ()) if str(term or "").strip())
    return any(term in text for term in terms)


def workflow_catalog_counts(root: ET.Element, workflow: Mapping[str, object]) -> Tuple[int, int, int]:
    safe_rows = 0
    catalog_rows = 0
    context_rows = 0
    for field_element in root.findall("./editableFieldCatalog/fields/field"):
        if not workflow_matches(workflow_search_text(field_element), workflow):
            continue
        catalog_rows += 1
        if str(field_element.get("importable") or "").strip().lower() == "true":
            safe_rows += 1
    for row_element in root.findall("./editorModel/groups/group/rows/row"):
        if workflow_matches(workflow_search_text(row_element), workflow):
            context_rows += 1
    for context_element in root.findall("./physicsBodyContext/body_contexts/body_context"):
        if workflow_matches(workflow_search_text(context_element), workflow):
            context_rows += 1
    for constraint_element in root.findall("./physicsConstraintSummary/constraints/constraint"):
        if workflow_matches(workflow_search_text(constraint_element), workflow):
            context_rows += 1
    return safe_rows, max(catalog_rows, safe_rows), max(0, context_rows - safe_rows)


def workflow_detail_lines(data: Mapping[str, object]) -> List[str]:
    safe_rows = int(data.get("safe_rows") or 0)
    context_rows = int(data.get("context_rows") or 0)
    catalog_rows = int(data.get("catalog_rows") or 0)
    risk = str(data.get("computed_risk") or data.get("risk") or "Context only")
    area = str(data.get("area") or data.get("goal") or "Selected area")
    lines = [
        area,
        f"Meaning: {data.get('meaning') or 'No plain-language summary is available yet.'}",
        f"Useful values: {data.get('likely_edits') or 'unknown'}",
        f"Recovered: {safe_rows:,} safe/importable, {context_rows:,} context, {catalog_rows:,} catalog match(es). Risk: {risk}.",
    ]
    if safe_rows > 0:
        lines.append(
            "Blue cells are structurally safe fixed-size patch targets; gameplay meaning still depends on context."
        )
    elif context_rows > 0:
        lines.append(
            "Only labels/relationships were recovered here; treat them as browsing evidence."
        )
    else:
        lines.append(
            "No recovered rows for this area in this file."
        )
    if "high" in risk.casefold():
        lines.append("High-risk rows can move frames or affect solver behavior.")
    return lines


def collision_shape_by_index(root: ET.Element, shape_index: str) -> Optional[ET.Element]:
    for shape_element in root.findall("./shapes/shape"):
        if str(shape_element.get("index") or "") == str(shape_index):
            return shape_element
    return None


def collision_context_by_shape_index(root: ET.Element) -> Dict[str, List[Dict[str, str]]]:
    context_by_shape: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for body_element in root.findall("./physicsBodyContext/bodies/body"):
        body_name = body_element.get("body_name") or ""
        socket_name = body_element.get("socket_name") or ""
        fixed_socket_name = body_element.get("fixed_socket_name") or ""
        material_name = body_element.get("physics_material_name") or ""
        descriptor_path = body_element.get("descriptor_path") or ""
        for match_element in body_element.findall("./shapeMatches/shape"):
            decoded_shape_index = str(match_element.get("decoded_shape_index") or "").strip()
            if not decoded_shape_index:
                continue
            details = []
            for attr_name, label in (
                ("descriptor_radius", "descriptor radius"),
                ("descriptor_height", "descriptor height"),
                ("decoded_radius", "decoded radius"),
                ("decoded_length", "decoded length"),
            ):
                value = match_element.get(attr_name)
                if value is not None:
                    details.append(f"{label}={value}")
            context_by_shape[decoded_shape_index].append(
                {
                    "body_name": body_name,
                    "socket_name": socket_name,
                    "fixed_socket_name": fixed_socket_name,
                    "material_name": material_name,
                    "descriptor_path": descriptor_path,
                    "confidence": match_element.get("confidence") or "experimental",
                    "details": "; ".join(details),
                    "description": match_element.findtext("description", default=""),
                }
            )
    for shape_element in root.findall("./shapes/shape"):
        shape_index = str(shape_element.get("index") or "").strip()
        if not shape_index:
            continue
        for context_element in shape_element.findall("./body_contexts/body_context"):
            context_by_shape[shape_index].append(
                {
                    "body_name": context_element.get("body_name") or "",
                    "socket_name": context_element.get("socket_name") or "",
                    "fixed_socket_name": context_element.get("fixed_socket_name") or "",
                    "material_name": context_element.get("physics_material_name") or "",
                    "descriptor_path": context_element.get("descriptor_path") or "",
                    "confidence": context_element.get("confidence") or "experimental",
                    "details": (
                        f"descriptor shape={context_element.get('descriptor_shape_index') or ''}; "
                        f"kind={context_element.get('descriptor_shape_kind') or ''}"
                    ).strip("; "),
                    "description": context_element.findtext("description", default=""),
                }
            )
    for shape_index, contexts in list(context_by_shape.items()):
        unique_contexts: List[Dict[str, str]] = []
        seen_context_keys: set[Tuple[str, str, str, str]] = set()
        for context in contexts:
            key = (
                context.get("body_name") or "",
                context.get("socket_name") or "",
                context.get("fixed_socket_name") or "",
                context.get("descriptor_path") or "",
            )
            if key in seen_context_keys:
                continue
            seen_context_keys.add(key)
            unique_contexts.append(context)
        context_by_shape[shape_index] = unique_contexts
    return context_by_shape


def hkx_preview_skeleton_link_count(preview_model: object) -> int:
    if not isinstance(preview_model, ModelPreviewData):
        return 0
    overlay = getattr(preview_model, "physics_overlay", None)
    if not isinstance(overlay, HkxPhysicsOverlayData):
        return 0
    linked = 0
    for shape in tuple(getattr(overlay, "shapes", ()) or ()):
        if isinstance(shape, HkxPhysicsOverlayShape) and str(getattr(shape, "placement_source", "") or "").strip():
            linked += 1
    for anchor in tuple(getattr(overlay, "anchors", ()) or ()):
        if isinstance(anchor, HkxPhysicsOverlayAnchor) and str(getattr(anchor, "skeleton_bone_name", "") or "").strip():
            linked += 1
    for constraint in tuple(getattr(overlay, "constraints", ()) or ()):
        if (
            isinstance(constraint, HkxPhysicsOverlayConstraint)
            and str(getattr(constraint, "confidence", "") or "").strip().casefold() == "skeleton_context"
        ):
            linked += 1
    return linked


def hkx_preview_counts(preview_model: object) -> Tuple[int, int, int, int, int]:
    mesh_count = len(getattr(preview_model, "meshes", ()) or ()) if isinstance(preview_model, ModelPreviewData) else 0
    overlay = getattr(preview_model, "physics_overlay", None)
    shape_count = len(getattr(overlay, "shapes", ()) or ()) if overlay is not None else 0
    constraint_count = len(getattr(overlay, "constraints", ()) or ()) if overlay is not None else 0
    bone_count = len(getattr(overlay, "bones", ()) or ()) if overlay is not None else 0
    skeleton_link_count = hkx_preview_skeleton_link_count(preview_model)
    return mesh_count, shape_count, constraint_count, bone_count, skeleton_link_count


def hkx_preview_target_ids_from_model(preview_model: object, *, include_bones: bool = True) -> set[str]:
    if not isinstance(preview_model, ModelPreviewData):
        return set()
    overlay = getattr(preview_model, "physics_overlay", None)
    if not isinstance(overlay, HkxPhysicsOverlayData):
        return set()
    target_ids: set[str] = set()
    for fallback_index, shape in enumerate(tuple(getattr(overlay, "shapes", ()) or ())):
        if not isinstance(shape, HkxPhysicsOverlayShape):
            continue
        source_index = int(
            getattr(shape, "source_shape_index", fallback_index)
            if getattr(shape, "source_shape_index", -1) >= 0
            else fallback_index
        )
        target_ids.add(f"shape/{source_index}")
        target_ids.add(f"shape/{fallback_index}")
    for index, _constraint in enumerate(tuple(getattr(overlay, "constraints", ()) or ())):
        target_ids.add(f"constraint/{index}")
    for index, _anchor in enumerate(tuple(getattr(overlay, "anchors", ()) or ())):
        target_ids.add(f"anchor/{index}")
    if include_bones:
        for fallback_index, bone in enumerate(tuple(getattr(overlay, "bones", ()) or ())):
            if not isinstance(bone, HkxPhysicsOverlayBone):
                continue
            bone_index = int(getattr(bone, "index", fallback_index))
            target_ids.add(f"bone/{bone_index}")
            target_ids.add(f"bone/{fallback_index}")
    return {target_id for target_id in target_ids if previewable_viewer_id(target_id)}


def overlay_shape_position(shape: HkxPhysicsOverlayShape) -> Tuple[float, float, float]:
    center = tuple(getattr(shape, "center", ()) or ())
    if len(center) >= 3:
        return (float(center[0]), float(center[1]), float(center[2]))
    capsule_start = tuple(getattr(shape, "capsule_start", ()) or ())
    capsule_end = tuple(getattr(shape, "capsule_end", ()) or ())
    if len(capsule_start) >= 3 and len(capsule_end) >= 3:
        return (
            (float(capsule_start[0]) + float(capsule_end[0])) * 0.5,
            (float(capsule_start[1]) + float(capsule_end[1])) * 0.5,
            (float(capsule_start[2]) + float(capsule_end[2])) * 0.5,
        )
    bounds_min = tuple(getattr(shape, "bounds_min", ()) or ())
    bounds_max = tuple(getattr(shape, "bounds_max", ()) or ())
    if len(bounds_min) >= 3 and len(bounds_max) >= 3:
        return (
            (float(bounds_min[0]) + float(bounds_max[0])) * 0.5,
            (float(bounds_min[1]) + float(bounds_max[1])) * 0.5,
            (float(bounds_min[2]) + float(bounds_max[2])) * 0.5,
        )
    vertices = tuple(getattr(shape, "vertices", ()) or ())
    if vertices:
        usable = [tuple(vertex) for vertex in vertices[:32] if len(vertex) >= 3]
        if usable:
            count = float(len(usable))
            return (
                sum(float(vertex[0]) for vertex in usable) / count,
                sum(float(vertex[1]) for vertex in usable) / count,
                sum(float(vertex[2]) for vertex in usable) / count,
            )
    return ()


def overlay_target_position_from_model(
    preview_model: object,
    *,
    kind: str,
    index: int,
) -> Tuple[float, float, float]:
    if not isinstance(preview_model, ModelPreviewData):
        return ()
    overlay = getattr(preview_model, "physics_overlay", None)
    if not isinstance(overlay, HkxPhysicsOverlayData):
        return ()
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind == "bone":
        for fallback_index, bone in enumerate(tuple(getattr(overlay, "bones", ()) or ())):
            if not isinstance(bone, HkxPhysicsOverlayBone):
                continue
            bone_index = int(getattr(bone, "index", fallback_index))
            if bone_index != int(index) and fallback_index != int(index):
                continue
            position = tuple(getattr(bone, "position", ()) or ())
            if len(position) >= 3:
                return (float(position[0]), float(position[1]), float(position[2]))
    if normalized_kind == "shape":
        for fallback_index, shape in enumerate(tuple(getattr(overlay, "shapes", ()) or ())):
            if not isinstance(shape, HkxPhysicsOverlayShape):
                continue
            source_index = int(
                getattr(shape, "source_shape_index", fallback_index)
                if getattr(shape, "source_shape_index", -1) >= 0
                else fallback_index
            )
            if source_index != int(index) and fallback_index != int(index):
                continue
            return overlay_shape_position(shape)
    return ()


def hkx_preview_context_skeleton_note(
    bone_count: int,
    skeleton_link_count: int,
    *,
    show_skeleton: bool,
) -> str:
    if bone_count <= 0:
        return " No skeleton context recovered."
    if skeleton_link_count <= 0:
        return (
            f" {bone_count:,} context skeleton bone(s) recovered but hidden because this HKX has no skeleton-linked "
            "shape/constraint target; showing them would imply held/sheathed placement that HKX alone does not provide."
        )
    if show_skeleton:
        return (
            f" {bone_count:,} context skeleton bone(s) shown for {skeleton_link_count:,} skeleton-linked HKX target(s). "
            "This is visual context; held/sheathed placement still requires prefab/socket evidence."
        )
    return f" {bone_count:,} context skeleton bone(s) hidden; {skeleton_link_count:,} skeleton-linked HKX target(s) remain available."


def workspace_task_label_for_key(key: str) -> str:
    labels = {
        "collision_size": "Collision Size",
        "body_transform": "Body Transform",
        "joint_strength": "Joint Strength",
        "damping_motion": "Damping / Motion",
        "material_friction": "Material / Friction",
        "mesh_winding": "Mesh Winding",
        "inspect_only": "Inspect Only",
    }
    return labels.get(str(key or ""), "Inspect Only")


def workspace_group_sort_key(group_label: str) -> int:
    if group_label == "Patchable rows":
        return 0
    if group_label == "Read-only candidates":
        return 1
    return 2


def workspace_group_for_row(row_element: ET.Element) -> str:
    safety = str(row_element.get("import_safety") or "").strip()
    if safety == "Import-safe":
        return "Patchable rows"
    if safety == "Read-only candidate":
        return "Read-only candidates"
    return "Structural blocked / context only"


def connected_risk_bucket(data: Mapping[str, object], confidence: str, risk: str) -> str:
    if str(data.get("importable") or "").strip().lower() == "true":
        return "safe"
    confidence_key = str(confidence or "").strip().lower()
    risk_key = str(risk or "").strip().lower()
    if risk_key in {"high", "experimental"} or confidence_key in {"experimental", "raw", "raw_preserved"}:
        return "experimental"
    if "inference" in confidence_key or risk_key in {"medium", "inferred"}:
        return "inferred"
    if confidence_key in {"confirmed", "descriptor_context", "descriptor-context"}:
        return "safe" if str(data.get("editor_tab") or "") else "inferred"
    return "inferred"


def connected_node_lookup(root: ET.Element) -> dict[str, dict[str, str]]:
    nodes: dict[str, dict[str, str]] = {}
    for node in root.findall("./relationshipGraph/nodes/node"):
        node_id = str(node.get("id") or "").strip()
        if node_id:
            nodes[node_id] = dict(node.attrib)
    return nodes


def connected_node_label(nodes_by_id: Mapping[str, Mapping[str, str]], node_id: str) -> str:
    node = nodes_by_id.get(str(node_id or ""))
    if isinstance(node, Mapping):
        return str(node.get("label") or node.get("subject") or node_id)
    return str(node_id or "")


def connected_value_text(value: str, original_value: str) -> str:
    value_text = str(value or "").strip()
    original_text = str(original_value or "").strip()
    if original_text and value_text and original_text != value_text:
        return format_hkx_display_value(f"{original_text} -> {value_text}")
    return format_hkx_display_value(value_text or original_text)


def normalize_hkx_viewer_id_text(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/").replace("#", "/").replace(":", "/").casefold()
    parts = [part for part in text.split("/") if part]
    if len(parts) < 2:
        return ""
    kind = parts[0]
    if kind in {"hknpshape", "collisionshape", "collision_shape"}:
        kind = "shape"
    elif kind in {"constraintguide", "motor", "guide"}:
        kind = "constraint"
    elif kind in {"skeletonbone", "skeleton_bone"}:
        kind = "bone"
    try:
        index = int(parts[1])
    except (TypeError, ValueError):
        return ""
    return f"{kind}/{index}"


def previewable_viewer_id(value: object) -> str:
    viewer_id = normalize_hkx_viewer_id_text(value)
    kind = viewer_id.split("/", 1)[0] if "/" in viewer_id else ""
    return viewer_id if kind in {"shape", "constraint", "anchor", "bone"} else ""


def viewer_ids_from_text(text: object) -> List[str]:
    viewer_ids: List[str] = []
    for match in re.finditer(r"\b(shape|constraint|anchor|bone|record)[:/#](\d+)\b", str(text or ""), flags=re.IGNORECASE):
        viewer_id = normalize_hkx_viewer_id_text(f"{match.group(1)}/{match.group(2)}")
        if viewer_id and viewer_id not in viewer_ids:
            viewer_ids.append(viewer_id)
    return viewer_ids


def record_indices_from_data(data: Mapping[str, object]) -> set[str]:
    record_indices: set[str] = set()
    for key in ("record_index", "connected_label", "label", "value", "viewer_selection_id", "id"):
        value = str(data.get(key) or "").strip()
        if not value:
            continue
        if key == "record_index":
            try:
                record_indices.add(str(int(value, 0)))
            except ValueError:
                pass
        for match in re.finditer(r"\brecord[:/#\s]+(\d+)\b", value, flags=re.IGNORECASE):
            record_indices.add(str(int(match.group(1))))
    return record_indices


def has_preview_link_hint(data: Mapping[str, object]) -> bool:
    if not data:
        return False
    if previewable_viewer_id(data.get("viewer_selection_id")):
        return True
    if str(data.get("shape_index") or "").strip():
        return True
    for key in ("identity_path", "details", "patch_path", "label", "subject", "connected_label", "explanation"):
        if any(previewable_viewer_id(viewer_id) for viewer_id in viewer_ids_from_text(data.get(key))):
            return True
    return False


def browser_viewer_id_aliases(kind: object, index: object, viewer_id: object) -> set[str]:
    aliases = {str(viewer_id or "").strip().replace(":", "/")}
    kind_text = str(kind or "").strip().replace(":", "/")
    try:
        index_text = str(int(index))
    except (TypeError, ValueError, OverflowError):
        index_text = str(index or "").strip()
    if kind_text and index_text:
        aliases.add(f"{kind_text}/{index_text}")
        aliases.add(f"{kind_text}:{index_text}".replace(":", "/"))
    return {alias for alias in aliases if alias}


def browser_data_viewer_id(data: Mapping[str, object]) -> str:
    return str(data.get("viewer_selection_id") or data.get("id") or "").strip().replace(":", "/")


def connected_target_filter_aliases(target_text: object) -> set[str]:
    raw_text = str(target_text or "").strip().replace(":", "/").casefold()
    if not raw_text:
        return set()
    aliases = {raw_text}
    viewer_id = previewable_viewer_id(raw_text)
    if not viewer_id:
        return aliases
    aliases.add(viewer_id)
    aliases.add(viewer_id.replace("/", " "))
    kind, index_text = viewer_id.split("/", 1)
    aliases.update(
        {
            f"{kind}:{index_text}".replace(":", "/"),
            f"{kind} {index_text}",
            f"{kind}={index_text}",
            f"{kind}_index {index_text}",
            f"{kind}_index={index_text}",
            f"{kind}_index:{index_text}",
            f"viewer={viewer_id}",
        }
    )
    if kind == "shape":
        aliases.update(
            {
                f"hknpconvexshape {index_text}",
                f"hknpshape {index_text}",
                f"shape_index {index_text}",
                f"shape_index={index_text}",
                f"decoded shape #{index_text}",
            }
        )
    elif kind == "constraint":
        aliases.update(
            {
                f"constraint_index {index_text}",
                f"constraint_index={index_text}",
                f"constraint {index_text}",
                f"motor {index_text}",
            }
        )
    elif kind == "bone":
        aliases.update(
            {
                f"bone_index {index_text}",
                f"bone_index={index_text}",
                f"skeleton bone {index_text}",
            }
        )
    return {alias for alias in aliases if alias}


def connected_row_text_matches_target(row_text: str, target_text: object) -> bool:
    normalized_row = str(row_text or "").replace(":", "/").casefold()
    filter_text = str(target_text or "").strip()
    if not filter_text:
        return True
    aliases = connected_target_filter_aliases(filter_text)
    viewer_id = previewable_viewer_id(filter_text)
    if aliases and any(alias in normalized_row for alias in aliases):
        return True
    if viewer_id:
        return False
    terms = filter_terms(filter_text)
    return all(term in normalized_row for term in terms)


def connected_detail_lines_from_mapping(
    data: Mapping[str, object],
    *,
    comparison_lines_fn: Callable[[Mapping[str, object]], List[str]],
    summary_lines_fn: Callable[[str], List[str]],
) -> List[str]:
    lines = comparison_lines_fn(data)
    viewer_id = str(data.get("viewer_selection_id") or "").strip()
    editor_tab = str(data.get("editor_tab") or "").strip()
    details = str(data.get("details") or "").strip()
    risk_bucket = str(data.get("risk_bucket") or "").strip()
    link_evidence = str(data.get("link_evidence") or "").strip()
    identity_path = str(data.get("identity_path") or "").strip()
    if risk_bucket:
        lines.append(f"Risk bucket: {risk_bucket}")
    if link_evidence:
        lines.append(f"Link evidence: {link_evidence}")
    if editor_tab:
        lines.append(f"Linked view: {editor_tab}")
    if viewer_id:
        lines.append(f"3D target: {viewer_id}")
    if identity_path:
        lines.append(f"Identity path: {identity_path}")
    for label, key in (
        ("Absolute byte offset", "hex_absolute_data_offset"),
        ("Byte size", "byte_size"),
        ("Value type", "value_type"),
        ("Owner field", "owner_field"),
        ("Reference source", "reference_source"),
    ):
        value = data.get(key)
        if value not in (None, ""):
            lines.append(f"{label}: {value}")
    if details:
        lines.append(f"Link details: {details}")
    if str(data.get("importable") or "").strip().lower() == "true":
        lines.append("Action: Open Linked Value to edit the exact row in its owning structured editor.")
    summary_viewer_id = previewable_viewer_id(viewer_id or data.get("source_id") or data.get("target_id") or data.get("id"))
    if summary_viewer_id:
        summary_lines = summary_lines_fn(summary_viewer_id)
        if summary_lines:
            lines.append("")
            lines.extend(summary_lines)
    return lines


__all__ = [
    "browser_data_viewer_id",
    "browser_viewer_id_aliases",
    "collision_context_by_shape_index",
    "collision_shape_by_index",
    "connected_node_label",
    "connected_node_lookup",
    "connected_risk_bucket",
    "connected_detail_lines_from_mapping",
    "connected_row_text_matches_target",
    "connected_target_filter_aliases",
    "connected_value_text",
    "filter_terms",
    "format_hkx_display_value",
    "friendly_hkx_value_meaning",
    "has_preview_link_hint",
    "hkx_confidence_color",
    "hkx_numeric_text_kind",
    "hkx_preview_context_skeleton_note",
    "hkx_preview_counts",
    "hkx_preview_skeleton_link_count",
    "hkx_preview_target_ids_from_model",
    "hkx_status_display",
    "normalize_hkx_viewer_id_text",
    "overlay_shape_position",
    "overlay_target_position_from_model",
    "previewable_viewer_id",
    "record_indices_from_data",
    "row_matches_filter_terms",
    "viewer_ids_from_text",
    "workflow_catalog_counts",
    "workflow_detail_lines",
    "workflow_matches",
    "workflow_search_text",
    "workspace_group_for_row",
    "workspace_group_sort_key",
    "workspace_task_label_for_key",
]
