from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_hkx_overlay_support import (
    _hkx_overlay_anchor_match_key,
    _hkx_overlay_body_shape_targets,
    _hkx_overlay_bones_from_skeleton_positions,
    _hkx_overlay_descriptor_vector,
    _hkx_overlay_shape_visual_center,
    _hkx_overlay_skeleton_bone_match,
    _hkx_overlay_translate_point,
    _hkx_overlay_tuning_hint_text,
    _hkx_overlay_vector,
)
from cdmw.core.archive_hkx_roles import (
    _hkx_simulation_role_counts,
    _hkx_simulation_role_description,
    _hkx_simulation_role_from_parts,
)
from cdmw.models import (
    HkxPhysicsOverlayAnchor,
    HkxPhysicsOverlayBone,
    HkxPhysicsOverlayConstraint,
    HkxPhysicsOverlayData,
    HkxPhysicsOverlayShape,
)


def _hkx_overlay_shape_context(shape: Mapping[str, object], source_path: str, fallback_index: int) -> Dict[str, object]:
    shape_type = str(shape.get("shape_type") or "hknpShape")
    context: Dict[str, object] = {
        "shape_type": shape_type,
        "source_shape_index": int(shape.get("index")) if isinstance(shape.get("index"), int) else fallback_index,
        "body_name": "",
        "socket_name": "",
        "fixed_socket_name": "",
        "physics_material_name": "",
        "simulation_role": "",
        "simulation_role_description": "",
        "label": "",
    }
    name_hint = shape.get("name_hint")
    if isinstance(name_hint, Mapping):
        context["label"] = str(name_hint.get("name") or "")
    if not context["label"]:
        contexts = shape.get("body_contexts")
        if isinstance(contexts, list):
            first_context = next((item for item in contexts if isinstance(item, Mapping)), None)
            if first_context is not None:
                context.update(
                    label=str(first_context.get("body_name") or first_context.get("socket_name") or ""),
                    body_name=str(first_context.get("body_name") or ""),
                    socket_name=str(first_context.get("socket_name") or ""),
                    fixed_socket_name=str(first_context.get("fixed_socket_name") or ""),
                    physics_material_name=str(first_context.get("physics_material_name") or ""),
                    simulation_role=str(first_context.get("simulation_role") or ""),
                    simulation_role_description=str(first_context.get("simulation_role_description") or ""),
                )
    if not context["label"]:
        context["label"] = f"{shape_type} {shape.get('index')}"
    if not context["simulation_role"]:
        context["simulation_role"] = _hkx_simulation_role_from_parts(
            source_path,
            context["label"],
            shape_type,
            context["body_name"],
            context["socket_name"],
            context["fixed_socket_name"],
            context["physics_material_name"],
        )
    if not context["simulation_role_description"]:
        context["simulation_role_description"] = _hkx_simulation_role_description(str(context["simulation_role"]))
    return context


def _hkx_overlay_shape_topology(
    shape: Mapping[str, object],
    *,
    normalization_center: Sequence[object],
    normalization_scale: float,
    max_vertices: int,
    max_faces: int,
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, ...]]]:
    vertices: List[Tuple[float, float, float]] = []
    for raw_vertex in shape.get("vertices") if isinstance(shape.get("vertices"), list) else []:
        point = _hkx_overlay_vector(
            raw_vertex,
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
        if len(point) == 3:
            vertices.append(point)
            if len(vertices) >= max_vertices:
                break
    faces: List[Tuple[int, ...]] = []
    raw_faces = shape.get("faces")
    if not isinstance(raw_faces, list):
        hull_topology = shape.get("hull_topology")
        if isinstance(hull_topology, Mapping):
            raw_faces = hull_topology.get("face_vertex_loops")
    if isinstance(raw_faces, list):
        for raw_face in raw_faces:
            if not isinstance(raw_face, (list, tuple)):
                continue
            face = tuple(
                int(index)
                for index in raw_face
                if isinstance(index, int) or (isinstance(index, str) and index.strip().lstrip("-").isdigit())
            )
            if len(face) >= 2:
                faces.append(face)
            if len(faces) >= max_faces:
                break
    return vertices, faces


def _hkx_overlay_shape_spatial(
    shape: Mapping[str, object],
    vertices: List[Tuple[float, float, float]],
    *,
    normalization_center: Sequence[object],
    normalization_scale: float,
) -> Dict[str, object]:
    bounds_min = _hkx_overlay_vector(
        shape.get("bounds_min"),
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )
    bounds_max = _hkx_overlay_vector(
        shape.get("bounds_max"),
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )
    center = _hkx_overlay_vector(
        shape.get("center"),
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )
    if not center and bounds_min and bounds_max:
        center = tuple((bounds_min[index] + bounds_max[index]) * 0.5 for index in range(3))
    radius = 0.0
    for key in ("sphere_radius", "capsule_radius"):
        value = shape.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            radius = max(radius, abs(float(value) * float(normalization_scale or 1.0)))
    capsule_start: Tuple[float, float, float] = ()
    capsule_end: Tuple[float, float, float] = ()
    endpoints = shape.get("capsule_endpoints")
    if isinstance(endpoints, list) and len(endpoints) >= 2:
        capsule_start = _hkx_overlay_vector(
            endpoints[0],
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
        capsule_end = _hkx_overlay_vector(
            endpoints[1],
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
    return {
        "vertices": vertices,
        "bounds_min": bounds_min,
        "bounds_max": bounds_max,
        "center": center,
        "radius": radius,
        "capsule_start": capsule_start,
        "capsule_end": capsule_end,
    }


def _hkx_overlay_place_shape(
    spatial: Dict[str, object],
    placement: object,
) -> Tuple[str, str, Tuple[float, float, float]]:
    if not isinstance(placement, Mapping):
        return "", "", ()
    target_position = placement.get("position")
    if not isinstance(target_position, (list, tuple)) or len(target_position) < 3:
        return "", "", ()
    visual_center = _hkx_overlay_shape_visual_center(
        center=spatial["center"],
        bounds_min=spatial["bounds_min"],
        bounds_max=spatial["bounds_max"],
        capsule_start=spatial["capsule_start"],
        capsule_end=spatial["capsule_end"],
        vertices=spatial["vertices"],
    )
    if not visual_center:
        return "", "", ()
    try:
        target = (float(target_position[0]), float(target_position[1]), float(target_position[2]))
        delta = tuple(target[index] - visual_center[index] for index in range(3))
    except (TypeError, ValueError, OverflowError):
        return "", "", ()
    if math.sqrt(sum(component * component for component in delta)) <= 1e-5:
        return "", "", ()
    spatial["vertices"] = [
        translated
        for translated in (_hkx_overlay_translate_point(vertex, delta) for vertex in spatial["vertices"])
        if translated
    ]
    for key in ("bounds_min", "bounds_max", "center", "capsule_start", "capsule_end"):
        if spatial[key]:
            spatial[key] = _hkx_overlay_translate_point(spatial[key], delta)
    return str(placement.get("source") or "skeleton_socket"), str(placement.get("target") or ""), delta


def _hkx_overlay_shape(
    shape: Mapping[str, object],
    *,
    source_path: str,
    fallback_index: int,
    placement_targets: Mapping[int, Mapping[str, object]],
    skeleton_bone_positions: Optional[Mapping[str, object]],
    normalization_center: Sequence[object],
    normalization_scale: float,
    max_vertices: int,
    max_faces: int,
) -> Optional[HkxPhysicsOverlayShape]:
    context = _hkx_overlay_shape_context(shape, source_path, fallback_index)
    vertices, faces = _hkx_overlay_shape_topology(
        shape,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
        max_vertices=max_vertices,
        max_faces=max_faces,
    )
    spatial = _hkx_overlay_shape_spatial(
        shape,
        vertices,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )
    if not any(
        (
            spatial["vertices"],
            spatial["bounds_min"] and spatial["bounds_max"],
            spatial["center"],
            spatial["capsule_start"] and spatial["capsule_end"],
            spatial["radius"],
        )
    ):
        return None
    source_shape_index = int(context["source_shape_index"])
    placement = placement_targets.get(source_shape_index)
    if not isinstance(placement, Mapping):
        skeleton_position, bone_name, bone_index, bone_source = _hkx_overlay_skeleton_bone_match(
            skeleton_bone_positions,
            context["socket_name"],
            context["fixed_socket_name"],
            context["body_name"],
            context["label"],
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
        if skeleton_position:
            placement = {
                "position": skeleton_position,
                "source": "skeleton_label",
                "target": bone_name or context["socket_name"] or context["fixed_socket_name"] or context["body_name"] or context["label"],
                "bone_index": bone_index,
                "source_path": bone_source,
                "confidence": "skeleton_context",
            }
    placement_source, placement_target, placement_delta = _hkx_overlay_place_shape(spatial, placement)
    shape_type = str(context["shape_type"])
    return HkxPhysicsOverlayShape(
        shape_type=shape_type,
        label=str(context["label"]),
        source_path=source_path,
        source_shape_index=source_shape_index,
        simulation_role=str(context["simulation_role"]),
        simulation_role_description=str(context["simulation_role_description"]),
        body_name=str(context["body_name"]),
        socket_name=str(context["socket_name"]),
        fixed_socket_name=str(context["fixed_socket_name"]),
        physics_material_name=str(context["physics_material_name"]),
        confidence="strong inference" if shape_type in {"hknpConvexShape", "hknpBoxShape", "hknpSphereShape", "hknpCapsuleShape"} else "experimental",
        read_only_reason=str(shape.get("read_only_reason") or ""),
        bounds_min=spatial["bounds_min"],
        bounds_max=spatial["bounds_max"],
        center=spatial["center"],
        radius=float(spatial["radius"]),
        capsule_start=spatial["capsule_start"],
        capsule_end=spatial["capsule_end"],
        vertices=tuple(spatial["vertices"]),
        faces=tuple(faces),
        placement_source=placement_source,
        placement_target=placement_target,
        placement_delta=placement_delta,
    )


def _hkx_overlay_shapes(
    shapes_value: List[object],
    document: Mapping[str, object],
    *,
    source_path: str,
    skeleton_bone_positions: Optional[Mapping[str, object]],
    normalization_center: Sequence[object],
    normalization_scale: float,
    max_shapes: int,
    max_vertices: int,
    max_faces: int,
) -> Tuple[List[HkxPhysicsOverlayShape], Dict[int, Tuple[float, float, float]]]:
    placement_targets = _hkx_overlay_body_shape_targets(
        document,
        skeleton_bone_positions,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )
    overlay_shapes: List[HkxPhysicsOverlayShape] = []
    positions: Dict[int, Tuple[float, float, float]] = {}
    for shape in shapes_value:
        if len(overlay_shapes) >= max_shapes:
            break
        if not isinstance(shape, Mapping):
            continue
        overlay_shape = _hkx_overlay_shape(
            shape,
            source_path=source_path,
            fallback_index=len(overlay_shapes),
            placement_targets=placement_targets,
            skeleton_bone_positions=skeleton_bone_positions,
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
            max_vertices=max_vertices,
            max_faces=max_faces,
        )
        if overlay_shape is None:
            continue
        visual_position = _hkx_overlay_shape_visual_center(
            center=overlay_shape.center,
            bounds_min=overlay_shape.bounds_min,
            bounds_max=overlay_shape.bounds_max,
            capsule_start=overlay_shape.capsule_start,
            capsule_end=overlay_shape.capsule_end,
            vertices=overlay_shape.vertices,
        )
        if visual_position:
            positions[overlay_shape.source_shape_index] = visual_position
        overlay_shapes.append(overlay_shape)
    return overlay_shapes, positions


def _hkx_overlay_anchors(
    physics_body_context: object,
    shape_positions: Mapping[int, Tuple[float, float, float]],
    *,
    source_path: str,
    skeleton_bone_positions: Optional[Mapping[str, object]],
    normalization_center: Sequence[object],
    normalization_scale: float,
) -> Tuple[List[HkxPhysicsOverlayAnchor], Dict[str, HkxPhysicsOverlayAnchor]]:
    anchors: List[HkxPhysicsOverlayAnchor] = []
    anchors_by_key: Dict[str, HkxPhysicsOverlayAnchor] = {}
    if not isinstance(physics_body_context, Mapping):
        return anchors, anchors_by_key
    body_contexts = physics_body_context.get("body_contexts")
    if not isinstance(body_contexts, list):
        return anchors, anchors_by_key
    for body_context in body_contexts:
        if not isinstance(body_context, Mapping):
            continue
        body_name = str(body_context.get("body_name") or "")
        socket_name = str(body_context.get("socket_name") or "")
        fixed_socket_name = str(body_context.get("fixed_socket_name") or "")
        shape_indices: List[int] = []
        positions: List[Tuple[float, float, float]] = []
        shape_matches = body_context.get("shape_matches")
        if isinstance(shape_matches, list):
            for match in shape_matches:
                if not isinstance(match, Mapping) or not isinstance(match.get("decoded_shape_index"), int):
                    continue
                decoded_shape_index = int(match["decoded_shape_index"])
                shape_indices.append(decoded_shape_index)
                if decoded_shape_index in shape_positions:
                    positions.append(shape_positions[decoded_shape_index])
        position, bone_name, bone_index, bone_source = _hkx_overlay_skeleton_bone_match(
            skeleton_bone_positions,
            socket_name,
            fixed_socket_name,
            body_name,
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
        if not position and positions:
            position = tuple(sum(point[index] for point in positions) / float(len(positions)) for index in range(3))
        if not position:
            position = _hkx_overlay_descriptor_vector(
                body_context.get("numeric_hints"),
                "_localTranslation",
                normalization_center=normalization_center,
                normalization_scale=normalization_scale,
            )
        if not position:
            continue
        label = body_name or socket_name or fixed_socket_name or f"body {len(anchors)}"
        role = str(body_context.get("simulation_role") or "") or _hkx_simulation_role_from_parts(
            source_path,
            label,
            body_name,
            socket_name,
            fixed_socket_name,
            body_context.get("physics_material_name"),
            body_context.get("numeric_hints"),
        )
        anchor = HkxPhysicsOverlayAnchor(
            label=label,
            source_path=source_path,
            simulation_role=role,
            simulation_role_description=str(body_context.get("simulation_role_description") or _hkx_simulation_role_description(role)),
            body_name=body_name,
            socket_name=socket_name,
            fixed_socket_name=fixed_socket_name,
            physics_material_name=str(body_context.get("physics_material_name") or ""),
            skeleton_bone_name=bone_name,
            skeleton_bone_index=bone_index,
            skeleton_source_path=bone_source,
            confidence="skeleton_context" if bone_name else str(body_context.get("confidence") or "descriptor_context"),
            position=position,
            shape_indices=tuple(shape_indices),
            tuning_hints=_hkx_overlay_tuning_hint_text(
                body_context.get("numeric_hints"),
                {"_angularDamping", "_linearDamping", "_inertiaFactor"},
            ),
        )
        anchors.append(anchor)
        for key in {
            _hkx_overlay_anchor_match_key(body_name),
            _hkx_overlay_anchor_match_key(socket_name),
            _hkx_overlay_anchor_match_key(fixed_socket_name),
        }:
            if key and key not in anchors_by_key:
                anchors_by_key[key] = anchor
    return anchors, anchors_by_key


def _hkx_overlay_constraint_positions(
    descriptor_context: Mapping[str, object],
    anchors_by_key: Mapping[str, HkxPhysicsOverlayAnchor],
    skeleton_bone_positions: Optional[Mapping[str, object]],
    *,
    normalization_center: Sequence[object],
    normalization_scale: float,
):
    body_name = str(descriptor_context.get("body_name") or "")
    socket_name = str(descriptor_context.get("socket_name") or "")
    fixed_socket_name = str(descriptor_context.get("fixed_socket_name") or "")
    start_anchor = anchors_by_key.get(_hkx_overlay_anchor_match_key(body_name, socket_name))
    end_anchor = anchors_by_key.get(_hkx_overlay_anchor_match_key(fixed_socket_name))
    start = start_anchor.position if isinstance(start_anchor, HkxPhysicsOverlayAnchor) else ()
    end = end_anchor.position if isinstance(end_anchor, HkxPhysicsOverlayAnchor) else ()
    end_bone_name = ""
    if not end:
        end, end_bone_name, _bone_index, _bone_source = _hkx_overlay_skeleton_bone_match(
            skeleton_bone_positions,
            fixed_socket_name,
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
    if not end:
        end = _hkx_overlay_descriptor_vector(
            descriptor_context.get("numeric_hints"),
            "_localTranslation",
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
    if not start and end:
        start = (end[0], end[1] - 0.08, end[2])
    return body_name, socket_name, fixed_socket_name, start_anchor, end_anchor, start, end, end_bone_name


def _hkx_overlay_summary_constraints(
    constraint_summary: object,
    anchors_by_key: Mapping[str, HkxPhysicsOverlayAnchor],
    *,
    source_path: str,
    skeleton_bone_positions: Optional[Mapping[str, object]],
    normalization_center: Sequence[object],
    normalization_scale: float,
) -> List[HkxPhysicsOverlayConstraint]:
    constraints: List[HkxPhysicsOverlayConstraint] = []
    raw_constraints = constraint_summary.get("constraints") if isinstance(constraint_summary, Mapping) else None
    if not isinstance(raw_constraints, list):
        return constraints
    for raw_constraint in raw_constraints[:128]:
        if not isinstance(raw_constraint, Mapping):
            continue
        descriptor_context = raw_constraint.get("descriptor_context")
        descriptor_context = descriptor_context if isinstance(descriptor_context, Mapping) else {}
        parts = _hkx_overlay_constraint_positions(
            descriptor_context,
            anchors_by_key,
            skeleton_bone_positions,
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
        body_name, socket_name, fixed_socket_name, start_anchor, end_anchor, start, end, end_bone_name = parts
        if not start and not end:
            continue
        role = str(descriptor_context.get("simulation_role") or "") or _hkx_simulation_role_from_parts(
            source_path,
            raw_constraint.get("name"),
            raw_constraint.get("type_name"),
            body_name,
            socket_name,
            fixed_socket_name,
            descriptor_context.get("numeric_hints"),
        )
        if isinstance(start_anchor, HkxPhysicsOverlayAnchor) and start_anchor.simulation_role:
            role = str(start_anchor.simulation_role)
        motor_hints: List[str] = []
        for slot in raw_constraint.get("motor_slots", []) if isinstance(raw_constraint.get("motor_slots"), list) else []:
            if not isinstance(slot, Mapping):
                continue
            name = str(slot.get("name") or "")
            value = slot.get("value")
            if name and isinstance(value, (int, float)):
                motor_hints.append(f"{name}={float(value):.4g}")
            if len(motor_hints) >= 4:
                break
        confidence = str(raw_constraint.get("confidence") or descriptor_context.get("confidence") or "experimental")
        if (
            (isinstance(start_anchor, HkxPhysicsOverlayAnchor) and start_anchor.confidence == "skeleton_context")
            or (isinstance(end_anchor, HkxPhysicsOverlayAnchor) and end_anchor.confidence == "skeleton_context")
            or bool(end_bone_name)
        ):
            confidence = "skeleton_context"
        constraints.append(
            HkxPhysicsOverlayConstraint(
                label=str(raw_constraint.get("name") or f"constraint {len(constraints)}"),
                source_path=source_path,
                constraint_type=str(raw_constraint.get("type_name") or descriptor_context.get("tag") or "constraint"),
                simulation_role=role,
                simulation_role_description=str(
                    getattr(start_anchor, "simulation_role_description", "")
                    if isinstance(start_anchor, HkxPhysicsOverlayAnchor)
                    else descriptor_context.get("simulation_role_description") or _hkx_simulation_role_description(role)
                ),
                body_name=body_name,
                socket_name=socket_name,
                fixed_socket_name=fixed_socket_name,
                confidence=confidence,
                start=start,
                end=end,
                motor_hints=tuple(motor_hints),
                limit_hints=_hkx_overlay_tuning_hint_text(
                    descriptor_context.get("numeric_hints"),
                    {"_maxFrictionTorque", "_angularLimitMin", "_angularLimitMax", "_coneAngle", "_twistMin", "_twistMax", "_planeMin", "_planeMax"},
                    limit=8,
                ),
            )
        )
    return constraints


def _hkx_overlay_descriptor_constraints(
    physics_body_context: object,
    constraints: List[HkxPhysicsOverlayConstraint],
    anchors_by_key: Mapping[str, HkxPhysicsOverlayAnchor],
    *,
    source_path: str,
    skeleton_bone_positions: Optional[Mapping[str, object]],
    normalization_center: Sequence[object],
    normalization_scale: float,
) -> None:
    contexts = physics_body_context.get("constraint_contexts") if isinstance(physics_body_context, Mapping) else None
    if not isinstance(contexts, list):
        return
    for descriptor_context in contexts[:128]:
        if not isinstance(descriptor_context, Mapping):
            continue
        body_name = str(descriptor_context.get("body_name") or "")
        socket_name = str(descriptor_context.get("socket_name") or "")
        fixed_socket_name = str(descriptor_context.get("fixed_socket_name") or "")
        if any(
            existing.body_name == body_name
            and existing.socket_name == socket_name
            and existing.fixed_socket_name == fixed_socket_name
            for existing in constraints
        ):
            continue
        parts = _hkx_overlay_constraint_positions(
            descriptor_context,
            anchors_by_key,
            skeleton_bone_positions,
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
        _, _, _, start_anchor, end_anchor, start, end, end_bone_name = parts
        if not start and not end:
            continue
        role = str(descriptor_context.get("simulation_role") or "") or _hkx_simulation_role_from_parts(
            source_path,
            descriptor_context.get("tag"),
            body_name,
            socket_name,
            fixed_socket_name,
            descriptor_context.get("numeric_hints"),
        )
        if isinstance(start_anchor, HkxPhysicsOverlayAnchor) and start_anchor.simulation_role:
            role = str(start_anchor.simulation_role)
        confidence = str(descriptor_context.get("confidence") or "descriptor_context")
        if (
            (isinstance(start_anchor, HkxPhysicsOverlayAnchor) and start_anchor.confidence == "skeleton_context")
            or (isinstance(end_anchor, HkxPhysicsOverlayAnchor) and end_anchor.confidence == "skeleton_context")
            or bool(end_bone_name)
        ):
            confidence = "skeleton_context"
        constraints.append(
            HkxPhysicsOverlayConstraint(
                label=str(descriptor_context.get("tag") or f"constraint guide {len(constraints)}"),
                source_path=source_path,
                constraint_type=str(descriptor_context.get("tag") or "descriptor_constraint"),
                simulation_role=role,
                simulation_role_description=str(
                    getattr(start_anchor, "simulation_role_description", "")
                    if isinstance(start_anchor, HkxPhysicsOverlayAnchor)
                    else descriptor_context.get("simulation_role_description") or _hkx_simulation_role_description(role)
                ),
                body_name=body_name,
                socket_name=socket_name,
                fixed_socket_name=fixed_socket_name,
                confidence=confidence,
                start=start,
                end=end,
                limit_hints=_hkx_overlay_tuning_hint_text(
                    descriptor_context.get("numeric_hints"),
                    {"_maxFrictionTorque", "_angularLimitMin", "_angularLimitMax", "_coneAngle", "_twistMin", "_twistMax", "_planeMin", "_planeMax"},
                    limit=8,
                ),
            )
        )


def _hkx_overlay_result(document, source_path, shapes, anchors, constraints, bones, constraint_summary):
    body_summary = document.get("physics_body_summary")
    body_count = int(body_summary.get("body_count") or 0) if isinstance(body_summary, Mapping) else 0
    constraint_count = int(constraint_summary.get("constraint_count") or 0) if isinstance(constraint_summary, Mapping) else 0
    skeleton_anchor_count = sum(1 for anchor in anchors if anchor.skeleton_bone_name)
    role_counts = _hkx_simulation_role_counts(anchors, constraints, shapes)
    role_text = ", ".join(f"{role}={count:,}" for role, count in role_counts)
    return HkxPhysicsOverlayData(
        summary=(
            f"HKX physics overlay: {len(shapes):,} decoded shape(s)"
            + (f", {len(anchors):,} body anchor(s)" if anchors else "")
            + (f", {skeleton_anchor_count:,} skeleton-linked" if skeleton_anchor_count else "")
            + (f", {len(bones):,} rig bone(s)" if bones else "")
            + (f", {len(constraints):,} constraint guide(s)" if constraints else "")
            + (f", {body_count:,} body label(s)" if body_count else "")
            + (f", {constraint_count:,} constraint hint(s)" if constraint_count else "")
            + (f", roles: {role_text}" if role_text else "")
        ),
        source_paths=(source_path,) if source_path else (),
        simulation_role_counts=role_counts,
        shapes=tuple(shapes),
        anchors=tuple(anchors),
        constraints=tuple(constraints),
        bones=bones,
        body_count=body_count,
        constraint_count=constraint_count,
        limitations=(
            "Visual collision/physics structure overlay only.",
            "Constraint and motor guides are descriptor/type correlations, not a Havok solver simulation.",
            "No Havok 2024.2 cloth, ragdoll, or solver simulation is run.",
            "Coordinates are transformed into the current normalized model-preview space.",
        ),
    )


def build_hkx_physics_overlay_from_document(
    document: Mapping[str, object],
    *,
    source_path: str = "",
    normalization_center: Sequence[object] = (0.0, 0.0, 0.0),
    normalization_scale: float = 1.0,
    skeleton_bone_positions: Optional[Mapping[str, object]] = None,
    max_shapes: int = 96,
    max_vertices_per_shape: int = 512,
    max_faces_per_shape: int = 512,
) -> Optional[HkxPhysicsOverlayData]:
    """Build a model-preview overlay from a decoded Crimson Desert HKX converter document.

    This is intentionally visual-only. It draws recovered collision bodies in the same normalized coordinate
    space as the model preview and does not simulate Havok constraints or cloth.
    """

    shapes_value = document.get("collision_shapes") or document.get("shapes")
    if not isinstance(shapes_value, list):
        return None
    shapes, positions = _hkx_overlay_shapes(
        shapes_value,
        document,
        source_path=source_path,
        skeleton_bone_positions=skeleton_bone_positions,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
        max_shapes=max_shapes,
        max_vertices=max_vertices_per_shape,
        max_faces=max_faces_per_shape,
    )
    if not shapes:
        return None
    bones = _hkx_overlay_bones_from_skeleton_positions(
        skeleton_bone_positions,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )
    physics_body_context = document.get("physics_body_context")
    anchors, anchors_by_key = _hkx_overlay_anchors(
        physics_body_context,
        positions,
        source_path=source_path,
        skeleton_bone_positions=skeleton_bone_positions,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )
    constraint_summary = document.get("physics_constraint_summary")
    constraints = _hkx_overlay_summary_constraints(
        constraint_summary,
        anchors_by_key,
        source_path=source_path,
        skeleton_bone_positions=skeleton_bone_positions,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )
    _hkx_overlay_descriptor_constraints(
        physics_body_context,
        constraints,
        anchors_by_key,
        source_path=source_path,
        skeleton_bone_positions=skeleton_bone_positions,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )
    return _hkx_overlay_result(document, source_path, shapes, anchors, constraints, bones, constraint_summary)


def merge_hkx_physics_overlays(overlays: Sequence[Optional[HkxPhysicsOverlayData]]) -> Optional[HkxPhysicsOverlayData]:
    valid = [overlay for overlay in overlays if isinstance(overlay, HkxPhysicsOverlayData) and overlay.shapes]
    if not valid:
        return None
    shapes: List[HkxPhysicsOverlayShape] = []
    anchors: List[HkxPhysicsOverlayAnchor] = []
    constraints: List[HkxPhysicsOverlayConstraint] = []
    bones: List[HkxPhysicsOverlayBone] = []
    source_paths: List[str] = []
    body_count = 0
    constraint_count = 0
    limitations: List[str] = []
    role_counter: Counter[str] = Counter()
    for overlay in valid:
        shapes.extend(overlay.shapes)
        anchors.extend(overlay.anchors)
        constraints.extend(overlay.constraints)
        bones.extend(overlay.bones)
        body_count += int(overlay.body_count or 0)
        constraint_count += int(overlay.constraint_count or 0)
        for role, count in tuple(getattr(overlay, "simulation_role_counts", ()) or ()):
            role_counter[str(role)] += int(count)
        for source_path in overlay.source_paths:
            if source_path not in source_paths:
                source_paths.append(source_path)
        for limitation in overlay.limitations:
            if limitation not in limitations:
                limitations.append(limitation)
    return HkxPhysicsOverlayData(
        summary=f"HKX physics overlay: {len(shapes):,} decoded shape(s) from {len(source_paths):,} HKX file(s)",
        source_paths=tuple(source_paths),
        simulation_role_counts=tuple(sorted(role_counter.items())),
        shapes=tuple(shapes),
        anchors=tuple(anchors),
        constraints=tuple(constraints),
        bones=tuple(bones),
        body_count=body_count,
        constraint_count=constraint_count,
        limitations=tuple(limitations),
    )
