from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_descriptor_shape_kind_matches_hkx',
    '_hkx_shape_context_from_descriptor',
    '_hkx_simulation_role_description',
    '_hkx_simulation_role_from_parts',
)
def _hkx_physics_body_context_document(
    shapes: Sequence[Mapping[str, object]],
    descriptor_hints: Sequence[Mapping[str, object]],
) -> Optional[Dict[str, object]]:
    if not descriptor_hints:
        return None
    shape_cursor = 0
    body_contexts: List[Dict[str, object]] = []
    constraint_contexts: List[Dict[str, object]] = []
    for descriptor_hint in descriptor_hints:
        descriptor_path = str(descriptor_hint.get("path") or "")
        for body_descriptor in descriptor_hint.get("body_descriptors", []) if isinstance(descriptor_hint.get("body_descriptors"), list) else []:
            if not isinstance(body_descriptor, Mapping):
                continue
            body_context: Dict[str, object] = {
                "descriptor_path": descriptor_path,
                "descriptor_body_index": body_descriptor.get("index"),
                "body_name": body_descriptor.get("body_name"),
                "socket_name": body_descriptor.get("socket_name"),
                "fixed_socket_name": body_descriptor.get("fixed_socket_name"),
                "physics_material_name": body_descriptor.get("physics_material_name"),
                "simulation_role": _hkx_simulation_role_from_parts(
                    descriptor_path,
                    body_descriptor.get("tag"),
                    body_descriptor.get("body_name"),
                    body_descriptor.get("socket_name"),
                    body_descriptor.get("fixed_socket_name"),
                    body_descriptor.get("physics_material_name"),
                    body_descriptor.get("numeric_hints", []),
                ),
                "numeric_hints": body_descriptor.get("numeric_hints", []),
                "shape_matches": [],
                "description": (
                    "Descriptor-level body context for decoded HKX shapes. Names and damping/inertia values come from "
                    "referenced XML; decoded shape indices come from the HKX converter."
                ),
            }
            shape_descriptors = body_descriptor.get("shape_descriptors")
            matches: List[Dict[str, object]] = []
            if isinstance(shape_descriptors, list):
                for descriptor_shape in shape_descriptors:
                    if not isinstance(descriptor_shape, Mapping):
                        continue
                    descriptor_kind = str(descriptor_shape.get("shape_kind") or "shape")
                    match_index: Optional[int] = None
                    for index in range(shape_cursor, len(shapes)):
                        if _hkx_descriptor_shape_kind_matches_hkx(descriptor_kind, str(shapes[index].get("shape_type") or "")):
                            match_index = index
                            break
                    if match_index is None:
                        for index, candidate in enumerate(shapes):
                            if _hkx_descriptor_shape_kind_matches_hkx(descriptor_kind, str(candidate.get("shape_type") or "")):
                                match_index = index
                                break
                    if match_index is None:
                        matches.append(
                            {
                                "descriptor_shape_index": descriptor_shape.get("index"),
                                "descriptor_shape_kind": descriptor_kind,
                                "descriptor_tag": descriptor_shape.get("tag"),
                                "decoded_shape_index": None,
                                "confidence": "raw",
                                "description": "No decoded HKX shape of a compatible kind was available for this descriptor shape row.",
                            }
                        )
                        continue
                    confidence = "strong inference" if match_index >= shape_cursor else "experimental"
                    matches.append(_hkx_shape_context_from_descriptor(shapes[match_index], descriptor_shape, confidence=confidence))
                    shape_cursor = max(shape_cursor, match_index + 1)
            body_context["shape_matches"] = matches
            body_context["simulation_role_description"] = _hkx_simulation_role_description(body_context.get("simulation_role"))
            body_contexts.append(body_context)
        for constraint_descriptor in descriptor_hint.get("constraint_descriptors", []) if isinstance(descriptor_hint.get("constraint_descriptors"), list) else []:
            if not isinstance(constraint_descriptor, Mapping):
                continue
            simulation_role = _hkx_simulation_role_from_parts(
                descriptor_path,
                constraint_descriptor.get("tag"),
                constraint_descriptor.get("body_name"),
                constraint_descriptor.get("socket_name"),
                constraint_descriptor.get("fixed_socket_name"),
                constraint_descriptor.get("numeric_hints", []),
            )
            constraint_contexts.append(
                {
                    "descriptor_path": descriptor_path,
                    "descriptor_constraint_index": constraint_descriptor.get("index"),
                    "tag": constraint_descriptor.get("tag"),
                    "body_name": constraint_descriptor.get("body_name"),
                    "socket_name": constraint_descriptor.get("socket_name"),
                    "fixed_socket_name": constraint_descriptor.get("fixed_socket_name"),
                    "simulation_role": simulation_role,
                    "simulation_role_description": _hkx_simulation_role_description(simulation_role),
                    "numeric_hints": constraint_descriptor.get("numeric_hints", []),
                    "confidence": "descriptor_context",
                    "description": (
                        "Constraint tuning hints from referenced XML. These are not yet linked to specific HKX "
                        "hknpConstraintCinfo records, but they identify likely angular/friction/joint-limit controls."
                    ),
                }
            )
    if not body_contexts and not constraint_contexts:
        return None
    return {
        "status": "descriptor_correlated_context",
        "confidence": "strong inference" if body_contexts else "descriptor_context",
        "description": (
            "Higher-level body/shape/constraint context built by correlating referenced descriptor XML with decoded HKX shapes. "
            "This is an interpretation aid; import ignores it."
        ),
        "body_count": len(body_contexts),
        "constraint_hint_count": len(constraint_contexts),
        "body_contexts": body_contexts,
        "constraint_contexts": constraint_contexts,
    }


@bind_archive_hkx_globals(
    'Mapping',
    'defaultdict',
)
def _hkx_attach_body_contexts_to_shapes(
    shapes: List[Dict[str, object]],
    physics_body_context: Optional[Mapping[str, object]],
) -> None:
    if not isinstance(physics_body_context, Mapping):
        return
    contexts_by_shape_index: Dict[int, List[Dict[str, object]]] = defaultdict(list)
    body_contexts = physics_body_context.get("body_contexts")
    if not isinstance(body_contexts, list):
        return
    for body_context in body_contexts:
        if not isinstance(body_context, Mapping):
            continue
        shape_matches = body_context.get("shape_matches")
        if not isinstance(shape_matches, list):
            continue
        for match in shape_matches:
            if not isinstance(match, Mapping) or not isinstance(match.get("decoded_shape_index"), int):
                continue
            decoded_shape_index = int(match["decoded_shape_index"])
            contexts_by_shape_index[decoded_shape_index].append(
                {
                    "body_name": body_context.get("body_name"),
                    "socket_name": body_context.get("socket_name"),
                    "fixed_socket_name": body_context.get("fixed_socket_name"),
                    "physics_material_name": body_context.get("physics_material_name"),
                    "simulation_role": body_context.get("simulation_role"),
                    "simulation_role_description": body_context.get("simulation_role_description"),
                    "descriptor_path": body_context.get("descriptor_path"),
                    "descriptor_body_index": body_context.get("descriptor_body_index"),
                    "descriptor_shape_index": match.get("descriptor_shape_index"),
                    "descriptor_shape_kind": match.get("descriptor_shape_kind"),
                    "confidence": match.get("confidence"),
                    "description": (
                        "Likely descriptor body/socket/material label for this decoded HKX shape. "
                        "This is exported context only and is ignored on import."
                    ),
                }
            )
    for shape in shapes:
        shape_index = shape.get("index")
        if not isinstance(shape_index, int):
            continue
        contexts = contexts_by_shape_index.get(shape_index)
        if contexts:
            shape["body_contexts"] = contexts


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_attach_shape_name_hints_to_shapes(
    shapes: List[Dict[str, object]],
    shape_names: Sequence[Mapping[str, object]],
) -> None:
    if not shape_names:
        return
    capsule_shapes = [shape for shape in shapes if str(shape.get("shape_type") or "") == "hknpCapsuleShape"]
    for shape, shape_name in zip(capsule_shapes, shape_names):
        if not isinstance(shape_name, Mapping):
            continue
        name = str(shape_name.get("name") or "").strip()
        if not name:
            continue
        shape["name_hint"] = {
            "name": name,
            "source": "HavokShapeNameProperty",
            "property_record_index": shape_name.get("property_record_index"),
            "name_record_index": shape_name.get("name_record_index"),
            "confidence": shape_name.get("confidence") or "experimental",
            "description": (
                "Decoded in-HKX ragdoll/body shape label. This is useful for identifying which body part a collision "
                "shape belongs to; import ignores it."
            ),
        }


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_simulation_role_description',
    '_hkx_simulation_role_from_parts',
)
def _hkx_physics_body_summary_document(shapes: Sequence[Mapping[str, object]]) -> Optional[Dict[str, object]]:
    bodies: List[Dict[str, object]] = []
    for shape in shapes:
        if not isinstance(shape, Mapping):
            continue
        shape_type = str(shape.get("shape_type") or "")
        name_hint = shape.get("name_hint")
        body_contexts = shape.get("body_contexts")
        primary_context = body_contexts[0] if isinstance(body_contexts, list) and body_contexts and isinstance(body_contexts[0], Mapping) else {}
        if shape_type != "hknpCapsuleShape" and not isinstance(name_hint, Mapping) and not primary_context:
            continue
        capsule_summary = shape.get("capsule_summary")
        body_name = ""
        confidence = "experimental"
        if isinstance(name_hint, Mapping) and str(name_hint.get("name") or "").strip():
            body_name = str(name_hint.get("name") or "").strip()
            confidence = str(name_hint.get("confidence") or "strong inference")
        elif isinstance(primary_context, Mapping):
            body_name = str(primary_context.get("body_name") or primary_context.get("socket_name") or "").strip()
            confidence = str(primary_context.get("confidence") or "descriptor_context")
        use_descriptor_as_primary = not isinstance(name_hint, Mapping)
        simulation_role = "collision"
        if isinstance(primary_context, Mapping):
            simulation_role = str(primary_context.get("simulation_role") or "")
        if not simulation_role or simulation_role == "collision":
            simulation_role = _hkx_simulation_role_from_parts(
                body_name,
                primary_context.get("body_name") if isinstance(primary_context, Mapping) else "",
                primary_context.get("socket_name") if isinstance(primary_context, Mapping) else "",
                primary_context.get("physics_material_name") if isinstance(primary_context, Mapping) else "",
                shape_type,
            )
        editable_fields = shape.get("editable_fields")
        body: Dict[str, object] = {
            "index": len(bodies),
            "shape_index": shape.get("index"),
            "shape_type": shape_type,
            "body_name": body_name,
            "simulation_role": simulation_role,
            "simulation_role_description": _hkx_simulation_role_description(simulation_role),
            "socket_name": primary_context.get("socket_name") if use_descriptor_as_primary and isinstance(primary_context, Mapping) else None,
            "fixed_socket_name": primary_context.get("fixed_socket_name") if use_descriptor_as_primary and isinstance(primary_context, Mapping) else None,
            "physics_material_name": primary_context.get("physics_material_name") if use_descriptor_as_primary and isinstance(primary_context, Mapping) else None,
            "confidence": confidence,
            "editable_fields": list(editable_fields) if isinstance(editable_fields, list) else [],
            "description": (
                "Body-level summary assembled from decoded HKX names, capsule/shape data, and optional descriptor XML. "
                "This is read-only context; edit the linked shape/tuning fields instead."
            ),
        }
        if isinstance(body_contexts, list) and body_contexts:
            body["descriptor_contexts"] = [
                dict(context)
                for context in body_contexts
                if isinstance(context, Mapping)
            ]
        if isinstance(name_hint, Mapping):
            body["name_hint"] = dict(name_hint)
        if isinstance(capsule_summary, Mapping):
            body["capsule"] = {
                "radius": capsule_summary.get("radius"),
                "length": capsule_summary.get("length"),
                "start": capsule_summary.get("start"),
                "end": capsule_summary.get("end"),
                "description": (
                    "Capsule collision volume for this body. Radius and endpoints are fixed-size editable values "
                    "when present in the linked shape."
                ),
            }
        records = shape.get("records")
        if isinstance(records, Mapping):
            body["records"] = dict(records)
        bodies.append(body)
    if not bodies:
        return None
    return {
        "status": "partial_reverse_engineering",
        "confidence": "strong inference" if any(body.get("name_hint") for body in bodies) else "experimental",
        "body_count": len(bodies),
        "description": (
            "Readable body summary for Crimson Desert HKX physics files. It links decoded names and descriptor hints "
            "to collision shapes so editable values are easier to understand."
        ),
        "bodies": bodies,
    }


@bind_archive_hkx_globals(
    'Counter',
    'Mapping',
)
def _hkx_material_simulation_context_document(
    descriptor_hints: Sequence[Mapping[str, object]],
) -> Optional[Dict[str, object]]:
    material_hints: List[Dict[str, object]] = []
    role_counts: Counter[str] = Counter()
    for descriptor_hint in descriptor_hints:
        if not isinstance(descriptor_hint, Mapping):
            continue
        descriptor_path = str(descriptor_hint.get("path") or "")
        hints = descriptor_hint.get("material_simulation_hints")
        if not isinstance(hints, list):
            continue
        for hint in hints:
            if not isinstance(hint, Mapping):
                continue
            row = dict(hint)
            row["descriptor_path"] = descriptor_path
            role = str(row.get("simulation_role") or "collision")
            role_counts[role] += 1
            material_hints.append(row)
    if not material_hints:
        return None
    return {
        "status": "descriptor_material_context",
        "confidence": "descriptor_context",
        "hint_count": len(material_hints),
        "role_counts": dict(sorted(role_counts.items())),
        "description": (
            "Readable cloth/hair/PBD material context from companion modelproperty/material XML. These rows help "
            "connect rendered meshes to possible simulation roles, but they are read-only and are ignored on HKX import."
        ),
        "hints": material_hints,
    }


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_descriptor_constraint_contexts(descriptor_hints: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    contexts: List[Dict[str, object]] = []
    for descriptor_hint in descriptor_hints:
        if not isinstance(descriptor_hint, Mapping):
            continue
        descriptor_path = str(descriptor_hint.get("path") or "")
        constraint_descriptors = descriptor_hint.get("constraint_descriptors")
        if not isinstance(constraint_descriptors, list):
            continue
        for constraint in constraint_descriptors:
            if not isinstance(constraint, Mapping):
                continue
            contexts.append(
                {
                    "descriptor_path": descriptor_path,
                    "descriptor_constraint_index": constraint.get("index"),
                    "tag": constraint.get("tag"),
                    "body_name": constraint.get("body_name"),
                    "socket_name": constraint.get("socket_name"),
                    "fixed_socket_name": constraint.get("fixed_socket_name"),
                    "numeric_hints": constraint.get("numeric_hints", []),
                    "confidence": "descriptor_context",
                    "description": (
                        "Descriptor XML constraint hint. This can name expected limit/friction values but is not a "
                        "confirmed HKX object reference and is ignored on import."
                    ),
                }
            )
    return contexts


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_char_record_texts_from_payloads',
    '_hkx_constraint_name_matches_type',
    '_hkx_descriptor_constraint_contexts',
    '_hkx_payload_fixed_float_slots',
)
def _hkx_physics_constraint_summary_document(
    advanced_payloads: Sequence[Mapping[str, object]],
    descriptor_hints: Sequence[Mapping[str, object]],
) -> Optional[Dict[str, object]]:
    constraint_records = [
        payload
        for payload in advanced_payloads
        if str(payload.get("type_name") or "") in {"hknpRagdollConstraintData", "hknpLimitedHingeConstraintData"}
        and isinstance(payload.get("record_index"), int)
    ]
    motor_records = [
        payload
        for payload in advanced_payloads
        if str(payload.get("type_name") or "") == "hknpPositionConstraintMotor"
        and isinstance(payload.get("record_index"), int)
    ]
    if not constraint_records and not motor_records:
        return None
    constraint_records.sort(key=lambda payload: int(payload.get("record_index") or 0))
    motor_records.sort(key=lambda payload: int(payload.get("record_index") or 0))
    char_texts = _hkx_char_record_texts_from_payloads(advanced_payloads)
    constraint_names = [
        {"name_record_index": record_index, "name": text}
        for record_index, text in sorted(char_texts.items())
        if "constraint" in text.casefold()
    ]
    unused_constraint_names = list(constraint_names)
    descriptor_contexts = _hkx_descriptor_constraint_contexts(descriptor_hints)
    constraints: List[Dict[str, object]] = []
    for index, constraint_payload in enumerate(constraint_records):
        constraint_record_index = int(constraint_payload.get("record_index") or -1)
        constraint_type_name = str(constraint_payload.get("type_name") or "")
        motor_payload = motor_records[index] if index < len(motor_records) else None
        name_hint = None
        for candidate in list(unused_constraint_names):
            if _hkx_constraint_name_matches_type(str(candidate.get("name") or ""), constraint_type_name):
                name_hint = candidate
                unused_constraint_names.remove(candidate)
                break
        if name_hint is None and unused_constraint_names:
            candidate = unused_constraint_names[0]
            candidate_name = str(candidate.get("name") or "")
            if "hinge" not in candidate_name.casefold() and "ragdoll" not in candidate_name.casefold():
                name_hint = unused_constraint_names.pop(0)
        descriptor_context = descriptor_contexts[index] if index < len(descriptor_contexts) else None
        constraint: Dict[str, object] = {
            "index": index,
            "name": str(name_hint.get("name") or "") if isinstance(name_hint, Mapping) else f"constraint {index}",
            "type_name": constraint_type_name,
            "constraint_record_index": constraint_record_index,
            "motor_record_index": motor_payload.get("record_index") if isinstance(motor_payload, Mapping) else None,
            "name_record_index": name_hint.get("name_record_index") if isinstance(name_hint, Mapping) else None,
            "confidence": "strong inference" if isinstance(name_hint, Mapping) else "experimental",
            "description": (
                "Constraint summary assembled by ordering decoded constraint-data records, constraint name strings, "
                "and position motors. It is read-only context; edit linked fixed-size tuning slots."
            ),
            "constraint_slots": _hkx_payload_fixed_float_slots(constraint_payload),
            "motor_slots": _hkx_payload_fixed_float_slots(motor_payload) if isinstance(motor_payload, Mapping) else [],
        }
        if isinstance(descriptor_context, Mapping):
            constraint["descriptor_context"] = dict(descriptor_context)
        constraints.append(constraint)
    for index in range(len(constraint_records), len(motor_records)):
        motor_payload = motor_records[index]
        constraints.append(
            {
                "index": len(constraints),
                "name": f"motor {index}",
                "type_name": "hknpPositionConstraintMotor",
                "constraint_record_index": None,
                "motor_record_index": motor_payload.get("record_index"),
                "confidence": "experimental",
                "description": "Unpaired position motor record. It is still editable through linked fixed-size tuning slots.",
                "constraint_slots": [],
                "motor_slots": _hkx_payload_fixed_float_slots(motor_payload),
            }
        )
    return {
        "status": "partial_reverse_engineering",
        "confidence": "strong inference" if constraint_names else "experimental",
        "constraint_count": len(constraints),
        "description": (
            "Readable constraint/motor summary. These rows are likely the main controls for ragdoll limits, stiffness, "
            "damping, force, and response. Links are order-based until Havok 2024.2 references are fully recovered."
        ),
        "constraints": constraints,
    }


@bind_archive_hkx_globals(
    'Mapping',
    '_format_hkx_vector',
    '_hkx_xml_scalar',
)
def _hkx_editable_shape_field_value_summary(shape: Mapping[str, object], field_name: str) -> str:
    value = shape.get(field_name)
    if field_name in {"vertices", "planes", "capsule_endpoints"} and isinstance(value, list):
        return f"{len(value)} row(s)"
    if field_name == "sphere_center" and isinstance(value, list):
        return _format_hkx_vector([float(item) for item in value[:3] if isinstance(item, (int, float))])
    if field_name in {"sphere_radius", "capsule_radius"} and isinstance(value, (int, float)):
        return _hkx_xml_scalar(value)
    if field_name == "mass_properties" and isinstance(value, Mapping):
        rows = value.get("float_rows")
        return f"{len(rows)} row(s)" if isinstance(rows, list) else "fixed-size rows"
    if field_name == "shape_payload" and isinstance(value, Mapping):
        slots = value.get("float_slots")
        return f"{len(slots)} slot(s)" if isinstance(slots, list) else "fixed-offset slots"
    if field_name == "hull_topology" and isinstance(value, Mapping):
        parts = []
        for key, label in (
            ("face_records", "faces"),
            ("face_indices", "indices"),
            ("edge_tables", "edge tables"),
        ):
            item = value.get(key)
            if isinstance(item, list):
                parts.append(f"{label}={len(item)}")
        return "; ".join(parts)
    return ""
