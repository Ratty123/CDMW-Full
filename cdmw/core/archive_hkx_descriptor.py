"""Companion descriptor XML hint extraction for HKX reports and previews."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_hkx_roles import (
    _hkx_simulation_role_description,
    _hkx_simulation_role_from_parts,
)


_HKX_DESCRIPTOR_NUMERIC_HINT_DESCRIPTIONS: Dict[str, str] = {
    "_angularDamping": "Likely angular damping for a dynamic attachment body; higher values usually reduce rotation/jiggle.",
    "_linearDamping": "Likely linear damping for a dynamic attachment body; higher values usually reduce positional swing.",
    "_inertiaFactor": "Likely inertia scaling for a dynamic body; higher values usually make it resist motion changes more.",
    "_sphereRadius": "Capsule end-sphere radius from descriptor XML.",
    "_cylinderHeight": "Capsule cylinder length/height from descriptor XML.",
    "_radius": "Sphere radius from descriptor XML.",
    "_maxFrictionTorque": "Constraint friction torque; often controls how strongly a joint resists free rotation.",
    "_angularLimitMin": "Minimum angular limits from descriptor XML, usually a three-component vector.",
    "_angularLimitMax": "Maximum angular limits from descriptor XML, usually a three-component vector.",
    "_coneAngle": "Ragdoll cone angle limit from descriptor XML.",
    "_twistMin": "Ragdoll twist minimum limit from descriptor XML.",
    "_twistMax": "Ragdoll twist maximum limit from descriptor XML.",
    "_planeMin": "Ragdoll plane minimum limit from descriptor XML.",
    "_planeMax": "Ragdoll plane maximum limit from descriptor XML.",
    "_localTranslation": "Body/socket local translation hint from descriptor XML.",
    "_shapeLocalTranslation": "Shape local translation hint from descriptor XML.",
    "_localRotation": "Body/socket local rotation quaternion hint from descriptor XML.",
    "_shapeLocalRotation": "Shape local rotation quaternion hint from descriptor XML.",
}


def _hkx_descriptor_element_local_name(element: ET.Element) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def _hkx_descriptor_numeric_hint_values(element: ET.Element) -> List[Dict[str, object]]:
    hints: List[Dict[str, object]] = []
    for name, description in _HKX_DESCRIPTOR_NUMERIC_HINT_DESCRIPTIONS.items():
        value = str(element.get(name) or "").strip()
        if not value:
            continue
        hints.append({"name": name, "value": value, "description": description})
    return hints


def _hkx_descriptor_core_attributes(element: ET.Element) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for source_name, target_name in (
        ("_bodyName", "body_name"),
        ("_socketName", "socket_name"),
        ("_fixedSocketName", "fixed_socket_name"),
        ("_physicsMaterialName", "physics_material_name"),
        ("_name", "name"),
    ):
        value = str(element.get(source_name) or "").strip()
        if value:
            result[target_name] = value
    return result


def _hkx_descriptor_shape_type(tag_name: str) -> str:
    lowered = tag_name.lower()
    if "capsule" in lowered:
        return "capsule"
    if "sphere" in lowered:
        return "sphere"
    if "box" in lowered:
        return "box"
    if "convex" in lowered:
        return "convex"
    if "mesh" in lowered:
        return "mesh"
    return "shape"


def _hkx_descriptor_body_documents(root: ET.Element) -> List[Dict[str, object]]:
    bodies: List[Dict[str, object]] = []
    for element in root.iter():
        tag_name = _hkx_descriptor_element_local_name(element)
        if not tag_name.endswith("BodyCreationDesc"):
            continue
        body: Dict[str, object] = {
            "index": len(bodies),
            "tag": tag_name,
            "numeric_hints": _hkx_descriptor_numeric_hint_values(element),
            "shape_descriptors": [],
        }
        body.update(_hkx_descriptor_core_attributes(element))
        shape_descriptors: List[Dict[str, object]] = []
        for child in list(element):
            child_tag = _hkx_descriptor_element_local_name(child)
            if not child_tag.endswith("ShapeDesc"):
                continue
            shape: Dict[str, object] = {
                "index": len(shape_descriptors),
                "tag": child_tag,
                "shape_kind": _hkx_descriptor_shape_type(child_tag),
                "numeric_hints": _hkx_descriptor_numeric_hint_values(child),
            }
            shape.update(_hkx_descriptor_core_attributes(child))
            shape_descriptors.append(shape)
        body["shape_descriptors"] = shape_descriptors
        bodies.append(body)
    return bodies


def _hkx_descriptor_material_simulation_documents(root: ET.Element) -> List[Dict[str, object]]:
    hints: List[Dict[str, object]] = []
    seen: set[Tuple[str, str, str]] = set()
    for element in root.iter():
        tag_name = _hkx_descriptor_element_local_name(element)
        values = {
            "pbd_simulation_material": str(element.get("_pbdSimulationMaterialName") or "").strip(),
            "material_name": str(element.get("_materialName") or "").strip(),
            "submesh_name": str(element.get("_subMeshName") or "").strip(),
            "jiggle_wind_weight": str(element.get("_jiggleWindWeight") or "").strip(),
            "parameter_name": str(element.get("_name") or "").strip(),
            "parameter_value": str(element.get("_value") or "").strip(),
        }
        role = _hkx_simulation_role_from_parts(tag_name, *values.values())
        if role == "collision":
            continue
        key = (
            values["pbd_simulation_material"],
            values["material_name"],
            values["submesh_name"] or values["parameter_name"],
        )
        if key in seen:
            continue
        seen.add(key)
        hint = {
            "index": len(hints),
            "tag": tag_name,
            "simulation_role": role,
            "simulation_role_description": _hkx_simulation_role_description(role),
            "description": (
                "Model/material sidecar simulation hint. This helps classify rendered meshes as cloth, hair, or "
                "dynamic attachments; it is read-only context and is ignored by HKX import."
            ),
        }
        for key_name, value in values.items():
            if value:
                hint[key_name] = value
        hints.append(hint)
        if len(hints) >= 256:
            break
    return hints


def _hkx_descriptor_constraint_documents(root: ET.Element) -> List[Dict[str, object]]:
    constraints: List[Dict[str, object]] = []
    consumed_element_ids: set[int] = set()
    for instance in root.iter():
        instance_tag = _hkx_descriptor_element_local_name(instance)
        if "Instance" not in instance_tag:
            continue
        body_elements = [
            child
            for child in list(instance)
            if _hkx_descriptor_element_local_name(child).endswith("BodyCreationDesc")
        ]
        if len(body_elements) < 2:
            continue
        constraint_elements = [
            child
            for child in instance.iter()
            if "ConstraintDesc" in _hkx_descriptor_element_local_name(child)
        ]
        if not constraint_elements:
            continue
        parent_body = next(
            (
                body
                for body in body_elements
                if str(body.get("Name") or "").strip().casefold() == "_parentbodydesc"
            ),
            body_elements[0],
        )
        child_body = next(
            (
                body
                for body in body_elements
                if str(body.get("Name") or "").strip().casefold() == "_childbodydesc"
            ),
            body_elements[1],
        )
        parent_attributes = _hkx_descriptor_core_attributes(parent_body)
        child_attributes = _hkx_descriptor_core_attributes(child_body)
        for element in constraint_elements:
            tag_name = _hkx_descriptor_element_local_name(element)
            constraint: Dict[str, object] = {
                "index": len(constraints),
                "tag": tag_name,
                "numeric_hints": _hkx_descriptor_numeric_hint_values(element),
            }
            constraint.update(_hkx_descriptor_core_attributes(element))
            constraint.setdefault("body_name", child_attributes.get("body_name"))
            constraint.setdefault("socket_name", child_attributes.get("socket_name"))
            constraint.setdefault(
                "fixed_socket_name",
                parent_attributes.get("socket_name") or parent_attributes.get("body_name"),
            )
            if parent_attributes.get("body_name"):
                constraint["fixed_body_name"] = parent_attributes.get("body_name")
            if parent_attributes.get("socket_name"):
                constraint["parent_socket_name"] = parent_attributes.get("socket_name")
            constraints.append(constraint)
            consumed_element_ids.add(id(element))
    for element in root.iter():
        tag_name = _hkx_descriptor_element_local_name(element)
        if "ConstraintDesc" not in tag_name or id(element) in consumed_element_ids:
            continue
        constraint = {
            "index": len(constraints),
            "tag": tag_name,
            "numeric_hints": _hkx_descriptor_numeric_hint_values(element),
        }
        constraint.update(_hkx_descriptor_core_attributes(element))
        constraints.append(constraint)
    return constraints


def _hkx_descriptor_unique_values(
    root: ET.Element,
    attribute_names: Sequence[str],
    *,
    limit: int = 128,
) -> Dict[str, List[str]]:
    values: Dict[str, List[str]] = {name: [] for name in attribute_names}
    seen: Dict[str, set[str]] = {name: set() for name in attribute_names}
    for element in root.iter():
        for name in attribute_names:
            value = str(element.get(name) or "").strip()
            if not value or value in seen[name]:
                continue
            seen[name].add(value)
            values[name].append(value)
            if len(values[name]) >= limit:
                break
    return {name: collected for name, collected in values.items() if collected}


def _hkx_descriptor_hint_from_root(root: ET.Element, source_path: str) -> Optional[Dict[str, object]]:
    body_values = _hkx_descriptor_unique_values(
        root,
        ("_bodyName", "_socketName", "_fixedSocketName", "_physicsMaterialName"),
    )
    numeric_values = _hkx_descriptor_unique_values(root, tuple(_HKX_DESCRIPTOR_NUMERIC_HINT_DESCRIPTIONS))
    body_descriptors = _hkx_descriptor_body_documents(root)
    constraint_descriptors = _hkx_descriptor_constraint_documents(root)
    material_simulation_hints = _hkx_descriptor_material_simulation_documents(root)
    if not body_values and not numeric_values and not body_descriptors and not constraint_descriptors and not material_simulation_hints:
        return None
    body_desc_count = sum(1 for element in root.iter() if element.tag.endswith("BodyCreationDesc"))
    constraint_desc_count = sum(1 for element in root.iter() if "ConstraintDesc" in element.tag)
    shape_desc_count = sum(1 for element in root.iter() if element.tag.endswith("ShapeDesc"))
    source = Path(source_path.replace("\\", "/")).name if source_path else ""
    return {
        "path": source_path,
        "stem": Path(source).stem if source else "",
        "root_tag": root.tag,
        "body_desc_count": body_desc_count,
        "constraint_desc_count": constraint_desc_count,
        "shape_desc_count": shape_desc_count,
        "material_simulation_hint_count": len(material_simulation_hints),
        "body_names": body_values.get("_bodyName", []),
        "socket_names": body_values.get("_socketName", []),
        "fixed_socket_names": body_values.get("_fixedSocketName", []),
        "physics_material_names": body_values.get("_physicsMaterialName", []),
        "numeric_hints": [
            {
                "name": name,
                "values": values,
                "description": _HKX_DESCRIPTOR_NUMERIC_HINT_DESCRIPTIONS.get(
                    name,
                    "Descriptor XML numeric hint.",
                ),
            }
            for name, values in sorted(numeric_values.items())
        ],
        "body_descriptors": body_descriptors,
        "constraint_descriptors": constraint_descriptors,
        "material_simulation_hints": material_simulation_hints,
        "description": (
            "Physics descriptor XML hints. These names and values are not imported into HKX automatically, "
            "but they help label likely body, socket, damping, inertia, shape, friction, and angular-limit roles."
        ),
    }


def build_hkx_descriptor_hint_from_xml_text(
    text: str,
    virtual_path: str = "",
) -> Optional[Dict[str, object]]:
    """Extract readable physics/body naming hints from a companion descriptor XML string."""

    try:
        root = ET.fromstring(text)
    except Exception:
        return None
    return _hkx_descriptor_hint_from_root(root, virtual_path)


__all__ = [
    "_HKX_DESCRIPTOR_NUMERIC_HINT_DESCRIPTIONS",
    "_hkx_descriptor_body_documents",
    "_hkx_descriptor_constraint_documents",
    "_hkx_descriptor_core_attributes",
    "_hkx_descriptor_element_local_name",
    "_hkx_descriptor_hint_from_root",
    "_hkx_descriptor_material_simulation_documents",
    "_hkx_descriptor_numeric_hint_values",
    "_hkx_descriptor_shape_type",
    "_hkx_descriptor_unique_values",
    "build_hkx_descriptor_hint_from_xml_text",
]
