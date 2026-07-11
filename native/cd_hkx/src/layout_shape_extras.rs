use crate::*;

pub(crate) fn add_tuning_floats_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if matches!(
        type_name,
        "hknpSharedMotionProperties"
            | "hknpPhysicsSystemData::ExtendedBodyCinfo"
            | "hknpRagdollConstraintData"
            | "hknpLimitedHingeConstraintData"
            | "hknpPositionConstraintMotor"
    ) && record.count > 0
    {
        let item_stride = if record.count > 0 {
            payload.len() / record.count as usize
        } else {
            payload.len()
        };
        for item_index in 0..(record.count as usize).min(64) {
            let item_base = item_index * item_stride;
            if item_base >= payload.len() {
                break;
            }
            for offset in (0..item_stride.min(512).saturating_sub(3)).step_by(4) {
                let absolute_offset = item_base + offset;
                let Some(value) = le_f32(&payload[absolute_offset..absolute_offset + 4]) else {
                    continue;
                };
                if !value.is_finite() || value.abs() < 1e-8 || value.abs() > 1_000_000.0 {
                    continue;
                }
                fields.push(layout_field(
                    &format!("{}[{item_index}]", fixed_float_slot_name(type_name, offset)),
                    absolute_offset,
                    4,
                    "float32",
                    Some(LayoutValue::F32(value)),
                    &fixed_float_slot_description(type_name, offset),
                    fixed_float_slot_confidence(type_name, offset),
                    true,
                ));
            }
        }
    }
}

pub(crate) fn add_sphere_capsule_radius_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if matches!(type_name, "hknpSphereShape" | "hknpCapsuleShape") && payload.len() >= 0x6C {
        let radius = le_f32(&payload[0x68..0x6C]);
        fields.push(layout_field(
            "radius",
            0x68,
            4,
            "float32",
            radius.map(LayoutValue::F32),
            if type_name == "hknpSphereShape" {
                "Observed sphere radius slot. Fixed-size edits are supported when the value remains finite and positive."
            } else {
                "Observed capsule radius slot. Fixed-size edits are supported when the value remains finite and positive."
            },
            "strong inference",
            true,
        ));
    }
}
