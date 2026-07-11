use crate::*;

pub fn parse_object_records(
    data: &[u8],
    items: &[TagItem],
    records: &[ItemRecord],
) -> Vec<ObjectRecord> {
    let spans = item_record_spans(data, items, records);
    let mut objects = Vec::new();
    for record in records {
        let Some((_index, start, end)) = spans
            .iter()
            .find(|(index, _, _)| *index == record.index)
            .copied()
        else {
            continue;
        };
        let payload = &data[start..end];
        let fields = decode_layout_fields(payload, record);
        let references = possible_reference_candidates(payload, records, record, 64);
        let editable = fields.iter().any(|field| field.editable);
        let status = if editable {
            "editable"
        } else if fields.iter().any(|field| field.confidence != "raw") || !references.is_empty() {
            "partially_decoded"
        } else {
            "raw_preserved"
        };
        objects.push(ObjectRecord {
            record_index: record.index,
            type_index: record.type_index,
            type_name: record.type_name.clone(),
            count: record.count,
            data_offset: record.data_offset,
            absolute_data_offset: record.absolute_data_offset,
            byte_length: end - start,
            stride: if record.count > 0 {
                Some((end - start) as f32 / record.count as f32)
            } else {
                None
            },
            status: status.to_string(),
            fields,
            references,
            raw_hex_prefix: payload_hex_prefix(payload, 64),
        });
    }
    objects
}

pub(crate) fn fixed_float_group_category(type_name: &str) -> Option<&'static str> {
    match type_name {
        "hknpPositionConstraintMotor" => Some("motor_force_response"),
        "hknpSharedMotionProperties" => Some("motion_damping_solver"),
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => Some("body_transform_mass"),
        "hknpRagdollConstraintData" | "hknpLimitedHingeConstraintData" => {
            Some("joint_limits_strength")
        }
        _ => None,
    }
}

pub(crate) fn fixed_float_group_description(type_name: &str) -> &'static str {
    match type_name {
        "hknpPositionConstraintMotor" => {
            "Editable fixed-size motor float slots. Likely affects constraint force limits, recovery strength, and damping."
        }
        "hknpSharedMotionProperties" => {
            "Editable fixed-size shared motion-property float slots. Likely affects damping, solver response, and velocity thresholds."
        }
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => {
            "Editable fixed-size body construction float slots. Likely includes transform, mass/inertia, and solver-related values."
        }
        "hknpRagdollConstraintData" | "hknpLimitedHingeConstraintData" => {
            "Editable fixed-size constraint float slots. Likely includes strength/tau, joint frames, limits, friction, and damping-like values."
        }
        _ => "Editable fixed-size physics float slots.",
    }
}

pub(crate) fn fixed_float_slot_name(type_name: &str, offset: usize) -> String {
    fn vector_component_slot_name(prefix: &str, start_offset: usize, offset: usize) -> String {
        let components = ["x", "y", "z", "w"];
        let relative = offset.saturating_sub(start_offset);
        let row_index = relative / 16;
        let component_index = (relative % 16) / 4;
        let component = components.get(component_index).copied().unwrap_or("n");
        format!("{prefix}_row{row_index}_{component}")
    }
    match type_name {
        "hknpPositionConstraintMotor" => match offset {
            0x20 => "min_force".to_string(),
            0x24 => "max_force".to_string(),
            0x28 => "stiffness_or_strength".to_string(),
            0x2C => "damping_or_tau".to_string(),
            0x30 => "recovery_or_proportional_response".to_string(),
            0x34 => "scale_or_enable_factor".to_string(),
            _ => format!("motor_float_0x{offset:X}"),
        },
        "hknpSharedMotionProperties" => match offset {
            0x04 => "motion_scale".to_string(),
            0x10 => "damping_or_solver_a".to_string(),
            0x14 => "damping_or_solver_b".to_string(),
            0x18 => "gravity_or_response_factor".to_string(),
            0x28 => "velocity_or_damping_limit_x".to_string(),
            0x2C => "velocity_or_damping_limit_y".to_string(),
            0x30 => "velocity_or_damping_limit_z".to_string(),
            0x34 => "velocity_or_damping_limit_w".to_string(),
            0x38 => "solver_tolerance_a".to_string(),
            0x3C => "solver_tolerance_b".to_string(),
            0x40 => "threshold".to_string(),
            0x44 => "solver_or_damping_a".to_string(),
            0x48 => "solver_or_damping_b".to_string(),
            _ => format!("motion_float_0x{offset:X}"),
        },
        "hknpMaterial" => match offset {
            0x00 => "material_friction_or_filter_a".to_string(),
            0x04 => "material_friction_or_restitution".to_string(),
            0x08 => "material_restitution_or_surface_response".to_string(),
            0x0C => "material_filter_or_flags".to_string(),
            0x10 => "material_user_data_or_property_a".to_string(),
            0x14 => "material_user_data_or_property_b".to_string(),
            0x18 => "material_surface_response_a".to_string(),
            0x1C => "material_surface_response_b".to_string(),
            0x20 => "material_surface_response_c".to_string(),
            0x30 => "material_property_scalar".to_string(),
            _ => format!("material_float_0x{offset:X}"),
        },
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => {
            if (0x30..=0x4C).contains(&offset) {
                return vector_component_slot_name("body_transform_or_orientation", 0x30, offset);
            }
            match offset {
                0x70 => "mass_or_inertia_value".to_string(),
                0x88 => "solver_mass_or_inertia_tuning_a".to_string(),
                0x8C => "solver_mass_or_inertia_tuning_b".to_string(),
                0x98 => "body_scale_or_activation_factor".to_string(),
                _ => format!("body_float_0x{offset:X}"),
            }
        }
        "hknpRagdollConstraintData" | "hknpLimitedHingeConstraintData" => {
            if offset == 0x18 {
                return "constraint_strength_or_tau".to_string();
            }
            if (0x40..0x80).contains(&offset) {
                return vector_component_slot_name("joint_frame_a", 0x40, offset);
            }
            if (0x80..0xA0).contains(&offset) {
                return vector_component_slot_name("joint_frame_b", 0x80, offset);
            }
            if (0xA0..0xC0).contains(&offset) {
                return vector_component_slot_name("angular_limit_or_axis", 0xA0, offset);
            }
            if (0xC0..=0x160).contains(&offset) {
                return vector_component_slot_name(
                    "constraint_friction_motor_or_damping",
                    0xC0,
                    offset,
                );
            }
            format!("constraint_float_0x{offset:X}")
        }
        _ => format!("float_0x{offset:X}"),
    }
}

pub(crate) fn fixed_float_slot_description(type_name: &str, offset: usize) -> String {
    match type_name {
        "hknpPositionConstraintMotor" => match offset {
            0x20 => "Likely minimum motor force limit.".to_string(),
            0x24 => "Likely maximum motor force limit.".to_string(),
            0x28 => "Likely motor stiffness/strength value.".to_string(),
            0x2C => "Likely damping or tau response value.".to_string(),
            0x30 => "Likely recovery/proportional response value.".to_string(),
            0x34 => "Likely scale or enable factor.".to_string(),
            _ => "Unverified hknpPositionConstraintMotor float slot.".to_string(),
        },
        "hknpSharedMotionProperties" => {
            "Likely shared motion damping, solver, gravity, or velocity threshold value."
                .to_string()
        }
        "hknpMaterial" => match offset {
            0x00 | 0x04 | 0x08 | 0x18 | 0x1C | 0x20 => {
                "Likely material friction, restitution, or surface response scalar. Read-only until fixed-edit proof confirms the exact member role.".to_string()
            }
            0x0C | 0x10 | 0x14 | 0x30 => {
                "Likely material filter, flag, or property scalar. Read-only until member semantics are confirmed.".to_string()
            }
            _ => "Unverified hknpMaterial scalar slot.".to_string(),
        },
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => {
            if (0x30..=0x4C).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0x30);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!(
                    "Likely body transform/orientation vector block row {row}, component {component}. This may be a local body frame, position, or quaternion-like value."
                )
            } else {
                "Likely body mass, inertia, solver, activation, or scale value.".to_string()
            }
        }
        "hknpRagdollConstraintData" | "hknpLimitedHingeConstraintData" => {
            if offset == 0x18 {
                "Likely constraint tau/strength-like value, often around 100.".to_string()
            } else if (0x40..0x80).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0x40);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!("Likely joint frame A vector row {row}, component {component}.")
            } else if (0x80..0xA0).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0x80);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!("Likely joint frame B vector row {row}, component {component}.")
            } else if (0xA0..0xC0).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0xA0);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!(
                    "Likely angular limit or limit-axis vector row {row}, component {component}."
                )
            } else if (0xC0..=0x160).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0xC0);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!("Likely constraint friction, motor, or damping vector row {row}, component {component}.")
            } else {
                format!("Unverified {type_name} float slot.")
            }
        }
        _ => format!("Unverified {type_name} float slot."),
    }
}

pub(crate) fn fixed_float_slot_confidence(type_name: &str, offset: usize) -> &'static str {
    if type_name == "hknpPositionConstraintMotor" && matches!(offset, 0x20 | 0x24) {
        "strong inference"
    } else if type_name == "hknpMaterial"
        && matches!(offset, 0x00 | 0x04 | 0x08 | 0x18 | 0x1C | 0x20)
    {
        "experimental"
    } else {
        "experimental"
    }
}

pub fn parse_physics_tuning_groups(
    data: &[u8],
    items: &[TagItem],
    records: &[ItemRecord],
) -> Vec<PhysicsTuningGroup> {
    let spans = item_record_spans(data, items, records);
    let mut groups = Vec::new();
    for record in records {
        let Some(category) = fixed_float_group_category(&record.type_name) else {
            continue;
        };
        if record.count == 0 {
            continue;
        }
        let Some((_index, start, end)) = spans
            .iter()
            .find(|(index, _, _)| *index == record.index)
            .copied()
        else {
            continue;
        };
        let byte_length = end.saturating_sub(start);
        let stride = byte_length / record.count as usize;
        if stride == 0 {
            continue;
        }
        let payload = &data[start..end];
        let mut slots = Vec::new();
        for item_index in 0..record.count as usize {
            let base = item_index * stride;
            for offset in (0..stride.min(512).saturating_sub(3)).step_by(4) {
                let absolute = base + offset;
                if absolute + 4 > payload.len() {
                    continue;
                }
                let Some(value) = le_f32(&payload[absolute..absolute + 4]) else {
                    continue;
                };
                if !value.is_finite() || value.abs() < 1e-8 || value.abs() > 1_000_000.0 {
                    continue;
                }
                slots.push(FixedFloatSlot {
                    item_index,
                    offset,
                    name: fixed_float_slot_name(&record.type_name, offset),
                    value,
                    description: fixed_float_slot_description(&record.type_name, offset),
                    confidence: fixed_float_slot_confidence(&record.type_name, offset).to_string(),
                });
            }
        }
        if slots.is_empty() {
            continue;
        }
        groups.push(PhysicsTuningGroup {
            category: category.to_string(),
            label: format!("{} record {}", record.type_name, record.index),
            type_name: record.type_name.clone(),
            record_index: record.index,
            count: record.count,
            byte_length,
            stride,
            description: fixed_float_group_description(&record.type_name).to_string(),
            confidence: "experimental".to_string(),
            edit_rule: "edit_value_only_keep_record_item_and_offset".to_string(),
            slots,
        });
    }
    groups
}
