from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    '_hkx_decode_char_payload_text',
    '_hkx_parse_payload_hex',
)
def _hkx_char_record_texts_from_payloads(advanced_payloads: Sequence[Mapping[str, object]]) -> Dict[int, str]:
    texts: Dict[int, str] = {}
    for payload_info in advanced_payloads:
        if str(payload_info.get("type_name") or "") != "char":
            continue
        record_index = payload_info.get("record_index")
        count = payload_info.get("count")
        if not isinstance(record_index, int) or not isinstance(count, int):
            continue
        try:
            payload = _hkx_parse_payload_hex(payload_info.get("payload_hex"), name=f"record[{record_index}].payload_hex")
        except ValueError:
            continue
        text = _hkx_decode_char_payload_text(payload, count)
        if text:
            texts[record_index] = text
    return texts


@bind_archive_hkx_globals(
    '_hkx_char_record_texts_from_payloads',
    '_hkx_parse_payload_hex',
    '_hkx_simulation_role_description',
    '_hkx_simulation_role_from_parts',
    'struct',
)
def _hkx_shape_name_documents(advanced_payloads: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    char_texts = _hkx_char_record_texts_from_payloads(advanced_payloads)
    shape_names: List[Dict[str, object]] = []
    for payload_info in advanced_payloads:
        if str(payload_info.get("type_name") or "") != "HavokShapeNameProperty":
            continue
        record_index = payload_info.get("record_index")
        if not isinstance(record_index, int):
            continue
        try:
            payload = _hkx_parse_payload_hex(payload_info.get("payload_hex"), name=f"record[{record_index}].payload_hex")
        except ValueError:
            continue
        if len(payload) < 0x24:
            continue
        raw_value = struct.unpack_from("<I", payload, 0x20)[0]
        candidate_indices = [raw_value - 1, raw_value]
        name_record_index: Optional[int] = None
        name = ""
        confidence = "raw"
        for candidate_index in candidate_indices:
            if candidate_index in char_texts:
                name_record_index = candidate_index
                name = char_texts[candidate_index]
                confidence = "strong inference" if candidate_index == raw_value - 1 else "experimental"
                break
        shape_names.append(
            {
                "index": len(shape_names),
                "property_record_index": record_index,
                "raw_name_reference": raw_value,
                "name_record_index": name_record_index,
                "name": name,
                "simulation_role": _hkx_simulation_role_from_parts(name),
                "simulation_role_description": _hkx_simulation_role_description(_hkx_simulation_role_from_parts(name)),
                "confidence": confidence,
                "description": (
                    "Decoded HavokShapeNameProperty name hint. This is read-only context for identifying ragdoll/body "
                    "collision shapes; import ignores it."
                ),
            }
        )
    return shape_names


@bind_archive_hkx_globals(
    '_hkx_shape_name_documents',
)
def _hkx_attach_shape_name_property_interpretations(payloads: List[Dict[str, object]]) -> None:
    names_by_property_record = {
        int(shape_name["property_record_index"]): shape_name
        for shape_name in _hkx_shape_name_documents(payloads)
        if isinstance(shape_name.get("property_record_index"), int)
    }
    for payload_info in payloads:
        record_index = payload_info.get("record_index")
        if not isinstance(record_index, int) or record_index not in names_by_property_record:
            continue
        interpretation = payload_info.get("interpretation")
        if not isinstance(interpretation, dict):
            interpretation = {}
            payload_info["interpretation"] = interpretation
        shape_name = names_by_property_record[record_index]
        interpretation["decoded_shape_name"] = {
            "name": shape_name.get("name") or "",
            "name_record_index": shape_name.get("name_record_index"),
            "raw_name_reference": shape_name.get("raw_name_reference"),
            "confidence": shape_name.get("confidence") or "experimental",
            "description": shape_name.get("description") or "",
        }


@bind_archive_hkx_globals(
    '_hkx_fixed_float_slot_group_description',
    'defaultdict',
)
def _hkx_physics_system_document(summary: HkxTagfileSummary) -> Optional[Dict[str, object]]:
    relevant_types = {
        "hknpRagdollData",
        "hknpPhysicsSceneData",
        "hknpPhysicsSystemData",
        "hknpPhysicsSystemData::ExtendedBodyCinfo",
        "hknpConstraintCinfo",
        "hknpRagdollConstraintData",
        "hknpLimitedHingeConstraintData",
        "hknpPositionConstraintMotor",
        "hknpSharedMotionProperties",
        "hknpCapsuleShape",
        "hknpSphereShape",
        "hknpBoxShape",
        "hknpConvexShape",
        "hknpMeshShape",
        "hkaSkeleton",
        "hkBone",
        "hkQsTransform",
    }
    records_by_type: Dict[str, List[HkxItemRecord]] = defaultdict(list)
    for record in summary.item_records:
        if record.type_name in relevant_types:
            records_by_type[record.type_name].append(record)
    if not records_by_type:
        return None
    type_counts = {
        type_name: sum(max(0, record.count) for record in records)
        for type_name, records in sorted(records_by_type.items())
    }
    editable_groups = []
    for type_name in (
        "hknpSharedMotionProperties",
        "hknpPhysicsSystemData::ExtendedBodyCinfo",
        "hknpRagdollConstraintData",
        "hknpLimitedHingeConstraintData",
        "hknpPositionConstraintMotor",
    ):
        records = records_by_type.get(type_name, [])
        if not records:
            continue
        editable_groups.append(
            {
                "type_name": type_name,
                "record_indices": [record.index for record in records],
                "description": _hkx_fixed_float_slot_group_description(type_name),
            }
        )
    return {
        "status": "partial_reverse_engineering",
        "description": (
            "Detected higher-level Havok physics/ragdoll structures. These summaries help identify files that "
            "control body movement, constraints, motors, capsule bodies, and skeleton mapping. Field names are "
            "still partially recovered; editable values are exposed through advanced_record_payloads."
        ),
        "type_counts": type_counts,
        "likely_controls": [
            {
                "name": "body collision capsules",
                "types": ["hknpCapsuleShape", "hknpPhysicsSystemData::ExtendedBodyCinfo", "HavokShapeNameProperty"],
                "description": "Capsule bodies and body construction info define ragdoll/body collision volumes and placement.",
            },
            {
                "name": "static and attachment collision shapes",
                "types": ["hknpBoxShape", "hknpSphereShape", "hknpConvexShape", "hknpMeshShape"],
                "description": (
                    "Box, sphere, convex, and mesh shapes define collision volumes. Box shapes are now decoded as "
                    "read-only offset/count and local-frame candidates until their exact Havok 2024.2 fields are confirmed."
                ),
            },
            {
                "name": "joint limits and ragdoll constraints",
                "types": ["hknpRagdollConstraintData", "hknpLimitedHingeConstraintData", "hknpConstraintCinfo"],
                "description": "Constraint data is the most likely place for angular limits, joint frames, and ragdoll stiffness/damping-like behavior.",
            },
            {
                "name": "motor strength and damping",
                "types": ["hknpPositionConstraintMotor"],
                "description": "Position constraint motors likely tune how strongly constraints recover, resist motion, or damp movement.",
            },
            {
                "name": "shared motion tuning",
                "types": ["hknpSharedMotionProperties"],
                "description": "Shared motion properties likely tune damping, gravity/solver response, and velocity thresholds for bodies.",
            },
        ],
        "editable_record_groups": editable_groups,
    }


@bind_archive_hkx_globals(
    '_hkx_vector_component_slot_name',
)
def _hkx_physics_tuning_slot_name(type_name: str, offset: int) -> str:
    if type_name == "hknpPositionConstraintMotor":
        return {
            0x20: "min_force",
            0x24: "max_force",
            0x28: "stiffness_or_strength",
            0x2C: "damping_or_tau",
            0x30: "recovery_or_proportional_response",
            0x34: "scale_or_enable_factor",
        }.get(offset, f"motor_float_0x{offset:X}")
    if type_name == "hknpSharedMotionProperties":
        return {
            0x04: "motion_scale",
            0x10: "damping_or_solver_a",
            0x14: "damping_or_solver_b",
            0x18: "gravity_or_response_factor",
            0x28: "velocity_or_damping_limit_x",
            0x2C: "velocity_or_damping_limit_y",
            0x30: "velocity_or_damping_limit_z",
            0x34: "velocity_or_damping_limit_w",
            0x38: "solver_tolerance_a",
            0x3C: "solver_tolerance_b",
            0x40: "threshold",
            0x44: "solver_or_damping_a",
            0x48: "solver_or_damping_b",
        }.get(offset, f"motion_float_0x{offset:X}")
    if type_name == "hknpPhysicsSystemData::ExtendedBodyCinfo":
        if 0x30 <= offset <= 0x4C:
            return _hkx_vector_component_slot_name("body_transform_or_orientation", 0x30, offset)
        if offset in {0x70, 0x88, 0x8C, 0x98}:
            return {
                0x70: "mass_or_inertia_value",
                0x88: "solver_mass_or_inertia_tuning_a",
                0x8C: "solver_mass_or_inertia_tuning_b",
                0x98: "body_scale_or_activation_factor",
            }[offset]
        return f"body_float_0x{offset:X}"
    if type_name in {"hknpRagdollConstraintData", "hknpLimitedHingeConstraintData"}:
        if offset == 0x18:
            return "constraint_strength_or_tau"
        if 0x40 <= offset < 0x80:
            return _hkx_vector_component_slot_name("joint_frame_a", 0x40, offset)
        if 0x80 <= offset < 0xA0:
            return _hkx_vector_component_slot_name("joint_frame_b", 0x80, offset)
        if 0xA0 <= offset < 0xC0:
            return _hkx_vector_component_slot_name("angular_limit_or_axis", 0xA0, offset)
        if 0xC0 <= offset <= 0x160:
            return _hkx_vector_component_slot_name("constraint_friction_motor_or_damping", 0xC0, offset)
        return f"constraint_float_0x{offset:X}"
    return f"float_0x{offset:X}"


@bind_archive_hkx_globals()
def _hkx_physics_tuning_user_guidance(type_name: str, offset: int, name: str) -> Dict[str, object]:
    effect = "unknown physics tuning"
    increase = "The effect is not confirmed; test one small change at a time."
    decrease = "The effect is not confirmed; test one small change at a time."
    safe_hint = "Start with a small change, usually 10% or less, and keep the original value noted."
    risk = "experimental"
    value_constraints = "finite float; fixed offset; same payload length; no object, record, or array count changes"
    suggested_edit_step = "try +/- 5% to 10% first"
    if type_name == "hknpPositionConstraintMotor":
        if offset in {0x20, 0x24} or "force" in name:
            effect = "motor force limit"
            increase = "Can make the constraint hold harder or resist movement more strongly."
            decrease = "Can allow more movement, looser jiggle, or easier constraint slippage."
            safe_hint = "Keep min/max ordering intact; try +/- 10% to 25%."
            risk = "medium"
            value_constraints = "finite float; fixed offset; keep min/max force or torque pairs ordered"
            suggested_edit_step = "try +/- 10% to 25%"
        elif "stiffness" in name or "strength" in name:
            effect = "motor stiffness"
            increase = "Usually tightens the body or joint response."
            decrease = "Usually makes the body or joint respond more softly."
            safe_hint = "Try +/- 10% first; large increases can create harsh movement."
            risk = "medium"
            value_constraints = "finite float; fixed offset; avoid negative values unless the source already uses them"
            suggested_edit_step = "try +/- 10% first"
        elif "damping" in name or "tau" in name or "recovery" in name:
            effect = "motor damping/recovery"
            increase = "May settle movement faster or make it feel more controlled."
            decrease = "May allow more wobble, bounce, or delayed recovery."
            safe_hint = "Try +/- 10% to 25% and watch for jitter."
            risk = "medium"
            value_constraints = "finite float; fixed offset; avoid extreme jumps"
            suggested_edit_step = "try +/- 10% to 25%"
    elif type_name == "hknpSharedMotionProperties":
        effect = "shared body motion behavior"
        increase = "May increase damping, velocity limits, or solver response depending on the slot."
        decrease = "May loosen motion or reduce solver resistance depending on the slot."
        safe_hint = "Change one slot at a time by about 10%; these may affect multiple bodies."
        risk = "medium"
        value_constraints = "finite float; fixed offset; signs and paired values should be preserved unless understood"
        suggested_edit_step = "try +/- 10%"
    elif type_name == "hknpPhysicsSystemData::ExtendedBodyCinfo":
        if 0x30 <= offset <= 0x4C:
            effect = "body transform/orientation"
            increase = "Moves or rotates the body component along the inferred stored axis/value."
            decrease = "Moves or rotates the body component in the opposite direction."
            safe_hint = "Prefer descriptor XML/socket context; tiny changes only."
            risk = "high"
            value_constraints = "finite float; fixed offset; preserve vector grouping and coordinate-space assumptions"
            suggested_edit_step = "try very small absolute changes first"
        else:
            effect = "body mass/inertia/solver value"
            increase = "May make the body behave heavier, more resistant, or more solver-stable."
            decrease = "May make the body behave lighter or more reactive."
            safe_hint = "Try +/- 5% to 10%; mass/inertia mistakes can destabilize physics."
            risk = "high"
            value_constraints = "finite float; fixed offset; avoid negative mass/inertia-like values unless already present"
            suggested_edit_step = "try +/- 5% to 10%"
    elif type_name in {"hknpRagdollConstraintData", "hknpLimitedHingeConstraintData"}:
        if offset == 0x18:
            effect = "constraint strength/tau"
            increase = "May make the joint hold its target harder."
            decrease = "May loosen the joint and allow more secondary motion."
            safe_hint = "Try +/- 10%; compare pose and motion stability."
            risk = "medium"
            value_constraints = "finite float; fixed offset; avoid negative values unless already present"
            suggested_edit_step = "try +/- 10%"
        elif 0x40 <= offset <= 0xA0:
            effect = "joint frame/axis component"
            increase = "Likely changes a joint frame axis or transform component."
            decrease = "Likely changes the same frame component in the opposite direction."
            safe_hint = "High risk; use descriptor context and change one component at a time."
            risk = "high"
            value_constraints = "finite float; fixed offset; preserve vector/axis grouping"
            suggested_edit_step = "change one component by a small absolute amount"
        elif 0xA0 <= offset <= 0x160:
            effect = "joint angular limit/friction/damping"
            increase = "May tighten a limit, increase friction, or increase damping depending on the slot."
            decrease = "May loosen a limit, reduce friction, or allow more motion."
            safe_hint = "Try small changes and keep paired min/max/vector values consistent."
            risk = "high"
            value_constraints = "finite float; fixed offset; keep paired min/max values ordered and preserve signs"
            suggested_edit_step = "try +/- 5% to 10%"
    return {
        "plain_language_effect": effect,
        "if_increased": increase,
        "if_decreased": decrease,
        "safe_edit_hint": safe_hint,
        "edit_risk": risk,
        "value_constraints": value_constraints,
        "suggested_edit_step": suggested_edit_step,
    }


@bind_archive_hkx_globals(
    'Mapping',
    'math',
    're',
)
def _hkx_physics_slot_vector_groups(slots: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    component_order = {"x": 0, "y": 1, "z": 2, "w": 3}
    grouped: Dict[Tuple[int, str, int], Dict[str, object]] = {}
    pattern = re.compile(r"^(?P<prefix>.+)_row(?P<row>\d+)_(?P<component>[xyzw])$")
    for slot in slots:
        name = str(slot.get("name") or "")
        match = pattern.match(name)
        if match is None:
            continue
        try:
            item_index = int(slot.get("item_index"))
            row_index = int(match.group("row"))
        except (TypeError, ValueError):
            continue
        prefix = match.group("prefix")
        component = match.group("component")
        key = (item_index, prefix, row_index)
        group = grouped.setdefault(
            key,
            {
                "name": f"{prefix}_row{row_index}",
                "prefix": prefix,
                "item_index": item_index,
                "row_index": row_index,
                "components": {},
                "offsets": {},
                "confidence": str(slot.get("confidence") or "experimental"),
                "edit_risk": str(slot.get("edit_risk") or "high"),
                "description": (
                    "Grouped vector-like fixed-float slots recovered from adjacent Havok fields. "
                    "Edit components together only when you understand the coordinate frame."
                ),
                "imported": False,
            },
        )
        components = group.get("components")
        offsets = group.get("offsets")
        if isinstance(components, dict):
            components[component] = slot.get("value")
        if isinstance(offsets, dict):
            offsets[component] = slot.get("hex_offset") or f"0x{int(slot.get('offset') or 0):X}"
    groups: List[Dict[str, object]] = []
    for _key, group in sorted(grouped.items(), key=lambda item: item[0]):
        components = group.get("components")
        values: List[Optional[float]] = []
        present_components: List[str] = []
        if isinstance(components, Mapping):
            for component, _component_index in sorted(component_order.items(), key=lambda item: item[1]):
                if component not in components:
                    values.append(None)
                    continue
                present_components.append(component)
                value = components.get(component)
                values.append(float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None)
        group["present_components"] = present_components
        group["values_xyzw"] = values
        group["complete_xyzw"] = len(present_components) == 4
        if str(group.get("prefix") or "").startswith("joint_frame"):
            group["likely_role"] = "joint frame axis/transform vector"
        elif str(group.get("prefix") or "").startswith("body_transform"):
            group["likely_role"] = "body transform/orientation vector"
        elif str(group.get("prefix") or "").startswith("angular_limit"):
            group["likely_role"] = "angular limit or limit-axis vector"
        elif str(group.get("prefix") or "").startswith("constraint_friction"):
            group["likely_role"] = "constraint friction/motor/damping vector"
        else:
            group["likely_role"] = "vector-like physics tuning row"
        groups.append(group)
    return groups


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_fixed_float_slot_description',
    '_hkx_fixed_float_slot_group_description',
    '_hkx_physics_slot_vector_groups',
    '_hkx_physics_tuning_category',
    '_hkx_physics_tuning_confidence',
    '_hkx_physics_tuning_slot_name',
    '_hkx_physics_tuning_user_guidance',
)
def _hkx_physics_tuning_document(advanced_payloads: Sequence[Mapping[str, object]]) -> Optional[Dict[str, object]]:
    groups: List[Dict[str, object]] = []
    for payload_info in advanced_payloads:
        type_name = str(payload_info.get("type_name") or "")
        editable_values = payload_info.get("editable_values")
        if not isinstance(editable_values, Mapping) or editable_values.get("kind") != "fixed_float_slots":
            continue
        record_index = payload_info.get("record_index")
        if not isinstance(record_index, int):
            continue
        slots: List[Dict[str, object]] = []
        items = editable_values.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, Mapping) or not isinstance(item.get("index"), int):
                    continue
                item_index = int(item["index"])
                for slot in item.get("float_slots", []) if isinstance(item.get("float_slots"), list) else []:
                    if not isinstance(slot, Mapping) or not isinstance(slot.get("offset"), int):
                        continue
                    offset = int(slot["offset"])
                    slot_name = _hkx_physics_tuning_slot_name(type_name, offset)
                    guidance = _hkx_physics_tuning_user_guidance(type_name, offset, slot_name)
                    slots.append(
                        {
                            "item_index": item_index,
                            "offset": offset,
                            "hex_offset": f"0x{offset:X}",
                            "name": slot_name,
                            "value": float(slot.get("value")),
                            "description": str(slot.get("description") or _hkx_fixed_float_slot_description(type_name, offset)),
                            "confidence": _hkx_physics_tuning_confidence(type_name, offset),
                            "source_record_index": record_index,
                            "source_type_name": type_name,
                            **guidance,
                        }
                    )
        if not slots:
            continue
        vector_groups = _hkx_physics_slot_vector_groups(slots)
        groups.append(
            {
                "category": _hkx_physics_tuning_category(type_name),
                "label": f"{type_name} record {record_index}",
                "type_name": type_name,
                "record_index": record_index,
                "count": payload_info.get("count"),
                "byte_length": payload_info.get("byte_length"),
                "description": editable_values.get("description") or _hkx_fixed_float_slot_group_description(type_name),
                "confidence": "experimental",
                "edit_rule": "edit_value_only_keep_record_item_and_offset",
                "slots": slots,
                "slot_vector_groups": vector_groups,
            }
        )
    if not groups:
        return None
    return {
        "status": "partial_reverse_engineering",
        "edit_rule": "value_only_fixed_float_slots",
        "description": (
            "Convenience editing layer for likely ragdoll/body physics tuning. Each row maps back to a fixed "
            "Havok ITEM record, item index, and byte offset. Names are inferred; descriptions are ignored on import."
        ),
        "groups": groups,
    }


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_descriptor_hint_rows(
    descriptor_hints: Sequence[Mapping[str, object]],
    *,
    category: str,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if category in {"body_transform_mass", "motion_damping_solver"}:
        for descriptor_hint in descriptor_hints:
            descriptor_path = str(descriptor_hint.get("path") or "")
            body_descriptors = descriptor_hint.get("body_descriptors")
            if not isinstance(body_descriptors, list):
                continue
            for body in body_descriptors:
                if not isinstance(body, Mapping):
                    continue
                for hint in body.get("numeric_hints", []) if isinstance(body.get("numeric_hints"), list) else []:
                    if not isinstance(hint, Mapping):
                        continue
                    hint_name = str(hint.get("name") or "")
                    if hint_name not in {"_angularDamping", "_linearDamping", "_inertiaFactor", "_localTranslation", "_localRotation"}:
                        continue
                    rows.append(
                        {
                            "source": "descriptor_body",
                            "descriptor_path": descriptor_path,
                            "body_name": body.get("body_name"),
                            "socket_name": body.get("socket_name"),
                            "name": hint_name,
                            "value": hint.get("value"),
                            "description": hint.get("description"),
                            "confidence": "descriptor_context",
                        }
                    )
    if category in {"joint_limits_strength", "motor_force_response"}:
        for descriptor_hint in descriptor_hints:
            descriptor_path = str(descriptor_hint.get("path") or "")
            constraint_descriptors = descriptor_hint.get("constraint_descriptors")
            if not isinstance(constraint_descriptors, list):
                continue
            for constraint in constraint_descriptors:
                if not isinstance(constraint, Mapping):
                    continue
                for hint in constraint.get("numeric_hints", []) if isinstance(constraint.get("numeric_hints"), list) else []:
                    if not isinstance(hint, Mapping):
                        continue
                    hint_name = str(hint.get("name") or "")
                    if hint_name not in {
                        "_maxFrictionTorque",
                        "_angularLimitMin",
                        "_angularLimitMax",
                        "_coneAngle",
                        "_twistMin",
                        "_twistMax",
                        "_planeMin",
                        "_planeMax",
                        "_localTranslation",
                        "_localRotation",
                    }:
                        continue
                    rows.append(
                        {
                            "source": "descriptor_constraint",
                            "descriptor_path": descriptor_path,
                            "constraint_tag": constraint.get("tag"),
                            "body_name": constraint.get("body_name"),
                            "socket_name": constraint.get("socket_name"),
                            "name": hint_name,
                            "value": hint.get("value"),
                            "description": hint.get("description"),
                            "confidence": "descriptor_context",
                        }
                    )
    return rows[:128]


@bind_archive_hkx_globals(
    '_hkx_descriptor_hint_rows',
)
def _hkx_attach_descriptor_context_to_physics_tuning(
    physics_tuning: Optional[Dict[str, object]],
    descriptor_hints: Sequence[Mapping[str, object]],
) -> Optional[Dict[str, object]]:
    if not isinstance(physics_tuning, dict) or not descriptor_hints:
        return physics_tuning
    groups = physics_tuning.get("groups")
    if not isinstance(groups, list):
        return physics_tuning
    for group in groups:
        if not isinstance(group, dict):
            continue
        category = str(group.get("category") or "")
        context_rows = _hkx_descriptor_hint_rows(descriptor_hints, category=category)
        if not context_rows:
            continue
        group["descriptor_context_hints"] = context_rows
        group["description"] = (
            str(group.get("description") or "").rstrip()
            + " Descriptor context hints are shown for comparison only and are ignored on import."
        ).strip()
    return physics_tuning


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_descriptor_float_hint',
)
def _hkx_shape_context_from_descriptor(
    shape: Mapping[str, object],
    descriptor_shape: Mapping[str, object],
    *,
    confidence: str,
) -> Dict[str, object]:
    shape_type = str(shape.get("shape_type") or "")
    descriptor_kind = str(descriptor_shape.get("shape_kind") or "shape")
    numeric_hints = descriptor_shape.get("numeric_hints")
    context: Dict[str, object] = {
        "descriptor_shape_index": descriptor_shape.get("index"),
        "descriptor_shape_kind": descriptor_kind,
        "descriptor_tag": descriptor_shape.get("tag"),
        "decoded_shape_index": shape.get("index"),
        "decoded_shape_type": shape_type,
        "decoded_shape_record_index": shape.get("shape_record_index"),
        "confidence": confidence,
        "description": (
            "Best-effort association between a referenced descriptor XML shape row and a decoded HKX collision shape. "
            "Order/type matching is useful context, not a confirmed Havok object reference."
        ),
    }
    expected_radius = _hkx_descriptor_float_hint(numeric_hints, "_sphereRadius")
    expected_height = _hkx_descriptor_float_hint(numeric_hints, "_cylinderHeight")
    if expected_radius is not None:
        context["descriptor_radius"] = expected_radius
    if expected_height is not None:
        context["descriptor_height"] = expected_height
    capsule_summary = shape.get("capsule_summary")
    if isinstance(capsule_summary, Mapping):
        context["decoded_radius"] = capsule_summary.get("radius")
        context["decoded_length"] = capsule_summary.get("length")
        if expected_radius is not None and isinstance(capsule_summary.get("radius"), (int, float)):
            context["radius_delta"] = float(capsule_summary["radius"]) - expected_radius
        if expected_height is not None and isinstance(capsule_summary.get("length"), (int, float)):
            context["length_delta"] = float(capsule_summary["length"]) - expected_height
    sphere_radius = shape.get("sphere_radius")
    if isinstance(sphere_radius, (int, float)):
        context["decoded_radius"] = float(sphere_radius)
        if expected_radius is not None:
            context["radius_delta"] = float(sphere_radius) - expected_radius
    for key in ("bounds_min", "bounds_max", "center", "extent"):
        if key in shape:
            context[key] = shape.get(key)
    vertices = shape.get("vertices")
    planes = shape.get("planes")
    if isinstance(vertices, list):
        context["decoded_vertex_count"] = len(vertices)
    if isinstance(planes, list):
        context["decoded_plane_count"] = len(planes)
    return context
