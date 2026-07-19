use crate::*;

#[derive(Debug, Clone, PartialEq)]
pub struct HkxPreviewBone {
    pub index: usize,
    pub parent_index: i32,
    pub position: [f32; 3],
}

#[derive(Debug, Clone, PartialEq)]
pub struct HkxPreviewShape {
    pub record_index: usize,
    pub shape_type: String,
    pub center: Option<[f32; 3]>,
    pub half_extents: Option<[f32; 3]>,
    pub radius: Option<f32>,
    pub endpoints: Vec<[f32; 3]>,
    pub vertices: Vec<[f32; 3]>,
    pub triangles: Vec<[u32; 3]>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HkxPreview {
    pub status: String,
    pub preview_kind: String,
    pub sdk_version: String,
    pub bone_count: usize,
    pub bones: Vec<HkxPreviewBone>,
    pub shape_count: usize,
    pub shapes: Vec<HkxPreviewShape>,
    pub warnings: Vec<String>,
}

#[derive(Clone, Copy)]
struct LocalTransform {
    translation: [f32; 3],
    rotation: [f32; 4],
}

pub fn build_hkx_preview(data: &[u8]) -> HkxPreview {
    let summary = parse_summary(data);
    let mut warnings = summary.warnings.clone();
    let bones = extract_skeleton_bones(data, &summary, &mut warnings);
    let shapes = if bones.is_empty() {
        extract_collision_shapes(data, &summary, &mut warnings)
    } else {
        Vec::new()
    };
    let preview_kind = if !bones.is_empty() {
        "skeleton"
    } else if !shapes.is_empty() {
        "collision"
    } else {
        if summary
            .item_records
            .iter()
            .any(|record| record.type_name == "hknpMeshShape")
        {
            warnings.push(
                "Packed hknpMeshShape geometry was recognized but is not decoded safely enough to render. No proxy object graph is shown."
                    .to_string(),
            );
        } else {
            warnings
                .push("No renderable skeleton or collision geometry was recovered.".to_string());
        }
        "unsupported"
    };
    HkxPreview {
        status: if preview_kind == "unsupported" {
            "unsupported"
        } else {
            "ok"
        }
        .to_string(),
        preview_kind: preview_kind.to_string(),
        sdk_version: summary.sdk_version,
        bone_count: bones.len(),
        bones,
        shape_count: shapes.len(),
        shapes,
        warnings,
    }
}

fn extract_skeleton_bones(
    data: &[u8],
    summary: &HkxSummary,
    warnings: &mut Vec<String>,
) -> Vec<HkxPreviewBone> {
    let owner_arrays = &summary.native_model_graph.owner_arrays;
    let skeleton_record = summary
        .item_records
        .iter()
        .find(|record| matches!(record.type_name.as_str(), "hkSkeleton" | "hkaSkeleton"));
    if skeleton_record.is_none() {
        return Vec::new();
    }
    let pose_owner = owner_arrays.iter().find(|owner| {
        matches!(owner.owner_type_name.as_str(), "hkSkeleton" | "hkaSkeleton")
            && owner.field_name == "referencePose"
    });
    let parent_owner = owner_arrays.iter().find(|owner| {
        matches!(owner.owner_type_name.as_str(), "hkSkeleton" | "hkaSkeleton")
            && owner.field_name == "parentIndices"
    });
    let Some(pose_record) = pose_owner
        .and_then(|owner| item_record_by_index(&summary.item_records, owner.target_record_index))
        .filter(|record| record.type_name == "hkQsTransform")
        .or_else(|| {
            summary
                .item_records
                .iter()
                .find(|record| record.type_name == "hkQsTransform")
        })
    else {
        return Vec::new();
    };
    let requested_count = pose_owner
        .and_then(|owner| owner.numelements)
        .filter(|count| *count > 0)
        .unwrap_or(pose_record.count)
        .min(4096) as usize;
    if requested_count == 0 {
        return Vec::new();
    }
    let Some(pose_payload) = record_payload(data, summary, pose_record.index) else {
        warnings.push("Skeleton reference-pose payload is unavailable.".to_string());
        return Vec::new();
    };
    let stride = pose_payload.len() / requested_count;
    if stride < 32 {
        warnings.push(format!(
            "Skeleton reference-pose stride {stride} is too small for hkQsTransform."
        ));
        return Vec::new();
    }

    let parent_record = parent_owner
        .and_then(|owner| item_record_by_index(&summary.item_records, owner.target_record_index))
        .filter(|record| record.type_name == "hkInt16")
        .or_else(|| {
            summary.item_records.iter().find(|record| {
                record.type_name == "hkInt16" && record.count as usize == requested_count
            })
        });
    let parent_payload =
        parent_record.and_then(|record| record_payload(data, summary, record.index));
    let mut parents = vec![-1i32; requested_count];
    if let Some(payload) = parent_payload {
        for (index, parent) in parents.iter_mut().enumerate() {
            let offset = index * 2;
            if offset + 2 <= payload.len() {
                *parent = i16::from_le_bytes([payload[offset], payload[offset + 1]]) as i32;
            }
        }
    } else {
        warnings.push("Skeleton parent indices were not recovered.".to_string());
        return Vec::new();
    }

    let mut local = Vec::with_capacity(requested_count);
    for index in 0..requested_count {
        let base = index * stride;
        if base + 32 > pose_payload.len() {
            break;
        }
        let translation = [
            read_f32(pose_payload, base),
            read_f32(pose_payload, base + 4),
            read_f32(pose_payload, base + 8),
        ];
        let rotation = normalize_quaternion([
            read_f32(pose_payload, base + 16),
            read_f32(pose_payload, base + 20),
            read_f32(pose_payload, base + 24),
            read_f32(pose_payload, base + 28),
        ]);
        if !translation.iter().all(|value| value.is_finite()) {
            warnings.push(format!(
                "Bone {index} has a non-finite translation and was reset to the origin."
            ));
            local.push(LocalTransform {
                translation: [0.0; 3],
                rotation,
            });
        } else {
            local.push(LocalTransform {
                translation,
                rotation,
            });
        }
    }
    parents.truncate(local.len());
    build_world_bones(&local, &parents)
}

fn build_world_bones(local: &[LocalTransform], parents: &[i32]) -> Vec<HkxPreviewBone> {
    let mut world_positions = vec![[0.0f32; 3]; local.len()];
    let mut world_rotations = vec![[0.0f32, 0.0, 0.0, 1.0]; local.len()];
    let mut resolved = vec![false; local.len()];
    for _ in 0..=local.len() {
        let mut changed = false;
        for index in 0..local.len() {
            if resolved[index] {
                continue;
            }
            let parent = parents.get(index).copied().unwrap_or(-1);
            if parent < 0 || parent as usize >= local.len() || parent as usize == index {
                world_positions[index] = local[index].translation;
                world_rotations[index] = local[index].rotation;
                resolved[index] = true;
                changed = true;
            } else if resolved[parent as usize] {
                let parent_index = parent as usize;
                let rotated =
                    rotate_vector(world_rotations[parent_index], local[index].translation);
                world_positions[index] = add(world_positions[parent_index], rotated);
                world_rotations[index] = normalize_quaternion(multiply_quaternion(
                    world_rotations[parent_index],
                    local[index].rotation,
                ));
                resolved[index] = true;
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    local
        .iter()
        .enumerate()
        .map(|(index, transform)| HkxPreviewBone {
            index,
            parent_index: parents.get(index).copied().unwrap_or(-1),
            position: if resolved[index] {
                world_positions[index]
            } else {
                transform.translation
            },
        })
        .collect()
}

const MAXIMUM_PREVIEW_SHAPES: usize = 96;
const MAXIMUM_PREVIEW_VERTICES: usize = 4096;
const MAXIMUM_PREVIEW_TRIANGLES: usize = 8192;

fn extract_collision_shapes(
    data: &[u8],
    summary: &HkxSummary,
    warnings: &mut Vec<String>,
) -> Vec<HkxPreviewShape> {
    let spans = item_record_spans(data, &summary.tag_items, &summary.item_records);
    let records = &summary.item_records;
    let mut shapes = Vec::new();
    let mut vertex_total = 0usize;
    let mut triangle_total = 0usize;

    for (position, record) in records.iter().enumerate() {
        if shapes.len() >= MAXIMUM_PREVIEW_SHAPES {
            break;
        }
        match record.type_name.as_str() {
            "hknpBoxShape" => {
                let Some(payload) = record_payload_from_spans(data, &spans, record.index) else {
                    continue;
                };
                if payload.len() < 0xC0 {
                    continue;
                }
                let center = [
                    read_f32(payload, 0xB0),
                    read_f32(payload, 0xB4),
                    read_f32(payload, 0xB8),
                ];
                let half_extents = [
                    read_f32(payload, 0x8C).abs(),
                    read_f32(payload, 0x9C).abs(),
                    read_f32(payload, 0xAC).abs(),
                ];
                if finite_vector(center)
                    && finite_vector(half_extents)
                    && half_extents.iter().any(|value| *value > 1e-6)
                    && half_extents.iter().all(|value| *value < 1_000_000.0)
                {
                    append_shape(
                        &mut shapes,
                        &mut vertex_total,
                        &mut triangle_total,
                        HkxPreviewShape {
                            record_index: record.index,
                            shape_type: "box".to_string(),
                            center: Some(center),
                            half_extents: Some(half_extents),
                            radius: None,
                            endpoints: Vec::new(),
                            vertices: Vec::new(),
                            triangles: Vec::new(),
                        },
                        warnings,
                    );
                }
            }
            "hknpSphereShape" => {
                let Some(payload) = record_payload_from_spans(data, &spans, record.index) else {
                    continue;
                };
                let Some(radius) = positive_radius(payload, 0x68) else {
                    continue;
                };
                let center = associated_float3(data, &spans, records, position, 1)
                    .and_then(|points| points.first().copied())
                    .unwrap_or([0.0; 3]);
                append_shape(
                    &mut shapes,
                    &mut vertex_total,
                    &mut triangle_total,
                    HkxPreviewShape {
                        record_index: record.index,
                        shape_type: "sphere".to_string(),
                        center: Some(center),
                        half_extents: None,
                        radius: Some(radius),
                        endpoints: Vec::new(),
                        vertices: Vec::new(),
                        triangles: Vec::new(),
                    },
                    warnings,
                );
            }
            "hknpCapsuleShape" => {
                let Some(payload) = record_payload_from_spans(data, &spans, record.index) else {
                    continue;
                };
                let Some(radius) = positive_radius(payload, 0x68) else {
                    continue;
                };
                let Some(endpoints) = associated_float3(data, &spans, records, position, 2) else {
                    continue;
                };
                if endpoints.len() < 2 {
                    continue;
                }
                append_shape(
                    &mut shapes,
                    &mut vertex_total,
                    &mut triangle_total,
                    HkxPreviewShape {
                        record_index: record.index,
                        shape_type: "capsule".to_string(),
                        center: None,
                        half_extents: None,
                        radius: Some(radius),
                        endpoints: endpoints.into_iter().take(2).collect(),
                        vertices: Vec::new(),
                        triangles: Vec::new(),
                    },
                    warnings,
                );
            }
            _ => {}
        }
    }

    let convex_records = records
        .iter()
        .filter(|record| record.type_name == "hknpConvexShape")
        .collect::<Vec<_>>();
    let property_positions = records
        .iter()
        .enumerate()
        .filter_map(|(index, record)| {
            (record.type_name == "hknpShapeProperties::Entry").then_some(index)
        })
        .collect::<Vec<_>>();
    if !property_positions.is_empty() {
        for (group_index, start) in property_positions.iter().copied().enumerate() {
            let end = property_positions
                .get(group_index + 1)
                .copied()
                .unwrap_or(records.len());
            let record_index = convex_records
                .get(group_index)
                .map(|record| record.index)
                .unwrap_or(records[start].index);
            if let Some(shape) = convex_shape(data, &spans, &records[start..end], record_index) {
                append_shape(
                    &mut shapes,
                    &mut vertex_total,
                    &mut triangle_total,
                    shape,
                    warnings,
                );
            }
        }
    } else if let Some(record) = convex_records.first() {
        if let Some(shape) = convex_shape(data, &spans, records, record.index) {
            append_shape(
                &mut shapes,
                &mut vertex_total,
                &mut triangle_total,
                shape,
                warnings,
            );
        }
    }
    shapes
}

fn append_shape(
    shapes: &mut Vec<HkxPreviewShape>,
    vertex_total: &mut usize,
    triangle_total: &mut usize,
    shape: HkxPreviewShape,
    warnings: &mut Vec<String>,
) {
    if shapes.len() >= MAXIMUM_PREVIEW_SHAPES
        || *vertex_total + shape.vertices.len() > MAXIMUM_PREVIEW_VERTICES
        || *triangle_total + shape.triangles.len() > MAXIMUM_PREVIEW_TRIANGLES
    {
        if !warnings
            .iter()
            .any(|warning| warning.contains("preview geometry limit"))
        {
            warnings.push(
                "HKX collision preview geometry limit reached; remaining shapes were omitted."
                    .to_string(),
            );
        }
        return;
    }
    *vertex_total += shape.vertices.len();
    *triangle_total += shape.triangles.len();
    shapes.push(shape);
}

fn convex_shape(
    data: &[u8],
    spans: &[(usize, usize, usize)],
    records: &[ItemRecord],
    record_index: usize,
) -> Option<HkxPreviewShape> {
    let vertex_record = records.iter().find(|record| {
        record.type_name == "hkFloat3" && record.count >= 3 && record.count <= 4096
    })?;
    let face_record = records
        .iter()
        .find(|record| record.type_name == "hknpConvexHull::Face" && record.count > 0)?;
    let index_record = records
        .iter()
        .find(|record| record.type_name == "hkUint8" && record.count > 0)?;
    let vertices = read_float3_record(data, spans, vertex_record)?;
    let face_payload = record_payload_from_spans(data, spans, face_record.index)?;
    let index_payload = record_payload_from_spans(data, spans, index_record.index)?;
    let mut triangles = Vec::new();
    for face_index in 0..(face_record.count as usize).min(4096) {
        let offset = face_index * 4;
        if offset + 4 > face_payload.len() {
            break;
        }
        let index_start =
            u16::from_le_bytes([face_payload[offset], face_payload[offset + 1]]) as usize;
        let vertex_count = face_payload[offset + 2] as usize;
        if !(3..=64).contains(&vertex_count) || index_start + vertex_count > index_payload.len() {
            continue;
        }
        let first = index_payload[index_start] as u32;
        for corner in 1..vertex_count - 1 {
            let triangle = [
                first,
                index_payload[index_start + corner] as u32,
                index_payload[index_start + corner + 1] as u32,
            ];
            if triangle
                .iter()
                .all(|index| (*index as usize) < vertices.len())
            {
                triangles.push(triangle);
                if triangles.len() >= MAXIMUM_PREVIEW_TRIANGLES {
                    break;
                }
            }
        }
    }
    if triangles.is_empty() {
        return None;
    }
    Some(HkxPreviewShape {
        record_index,
        shape_type: "convex".to_string(),
        center: None,
        half_extents: None,
        radius: None,
        endpoints: Vec::new(),
        vertices,
        triangles,
    })
}

fn associated_float3(
    data: &[u8],
    spans: &[(usize, usize, usize)],
    records: &[ItemRecord],
    shape_position: usize,
    count: u32,
) -> Option<Vec<[f32; 3]>> {
    let end = records
        .iter()
        .enumerate()
        .skip(shape_position + 1)
        .find_map(|(index, record)| is_shape_record(&record.type_name).then_some(index))
        .unwrap_or(records.len());
    let record = records[shape_position + 1..end]
        .iter()
        .find(|record| record.type_name == "hkFloat3" && record.count == count)?;
    read_float3_record(data, spans, record)
}

fn is_shape_record(type_name: &str) -> bool {
    matches!(
        type_name,
        "hknpBoxShape"
            | "hknpConvexShape"
            | "hknpSphereShape"
            | "hknpCapsuleShape"
            | "hknpMeshShape"
    )
}

fn read_float3_record(
    data: &[u8],
    spans: &[(usize, usize, usize)],
    record: &ItemRecord,
) -> Option<Vec<[f32; 3]>> {
    let payload = record_payload_from_spans(data, spans, record.index)?;
    let count = (record.count as usize).min(MAXIMUM_PREVIEW_VERTICES);
    if count == 0 || payload.len() < count * 12 {
        return None;
    }
    let points = (0..count)
        .map(|index| {
            let offset = index * 12;
            [
                read_f32(payload, offset),
                read_f32(payload, offset + 4),
                read_f32(payload, offset + 8),
            ]
        })
        .collect::<Vec<_>>();
    points
        .iter()
        .all(|point| finite_vector(*point))
        .then_some(points)
}

fn record_payload_from_spans<'a>(
    data: &'a [u8],
    spans: &[(usize, usize, usize)],
    record_index: usize,
) -> Option<&'a [u8]> {
    let (_, start, end) = spans
        .iter()
        .copied()
        .find(|(index, _, _)| *index == record_index)?;
    data.get(start..end)
}

fn positive_radius(payload: &[u8], offset: usize) -> Option<f32> {
    let value = read_f32(payload, offset);
    (value.is_finite() && value > 0.0 && value < 1_000_000.0).then_some(value)
}

fn finite_vector(value: [f32; 3]) -> bool {
    value
        .iter()
        .all(|component| component.is_finite() && component.abs() < 1_000_000_000.0)
}

fn record_payload<'a>(
    data: &'a [u8],
    summary: &HkxSummary,
    record_index: usize,
) -> Option<&'a [u8]> {
    let (_, start, end) = item_record_spans(data, &summary.tag_items, &summary.item_records)
        .into_iter()
        .find(|(index, _, _)| *index == record_index)?;
    data.get(start..end)
}

fn read_f32(data: &[u8], offset: usize) -> f32 {
    data.get(offset..offset + 4)
        .map(|value| f32::from_le_bytes([value[0], value[1], value[2], value[3]]))
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
}

fn normalize_quaternion(value: [f32; 4]) -> [f32; 4] {
    let length = value
        .iter()
        .map(|component| component * component)
        .sum::<f32>()
        .sqrt();
    if !length.is_finite() || length <= 1e-8 {
        return [0.0, 0.0, 0.0, 1.0];
    }
    [
        value[0] / length,
        value[1] / length,
        value[2] / length,
        value[3] / length,
    ]
}

fn multiply_quaternion(a: [f32; 4], b: [f32; 4]) -> [f32; 4] {
    [
        a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
        a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
        a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
        a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
    ]
}

fn rotate_vector(q: [f32; 4], value: [f32; 3]) -> [f32; 3] {
    let q_vector = [q[0], q[1], q[2]];
    let uv = cross(q_vector, value);
    let uuv = cross(q_vector, uv);
    add(value, add(scale(uv, 2.0 * q[3]), scale(uuv, 2.0)))
}

fn cross(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

fn add(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

fn scale(value: [f32; 3], factor: f32) -> [f32; 3] {
    [value[0] * factor, value[1] * factor, value[2] * factor]
}

pub fn hkx_preview_to_json(preview: &HkxPreview) -> String {
    let mut out = String::new();
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_preview_v2\",\"status\":\"{}\",\"preview_kind\":\"{}\",\"sdk_version\":\"{}\",\"bone_count\":{},\"bones\":[",
        json_escape(&preview.status),
        json_escape(&preview.preview_kind),
        json_escape(&preview.sdk_version),
        preview.bone_count
    );
    for (index, bone) in preview.bones.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"index\":{},\"parent_index\":{},\"position\":[{},{},{}]}}",
            bone.index, bone.parent_index, bone.position[0], bone.position[1], bone.position[2]
        );
    }
    let _ = write!(
        out,
        "],\"shape_count\":{},\"shapes\":[",
        preview.shape_count
    );
    for (index, shape) in preview.shapes.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"record_index\":{},\"shape_type\":\"{}\",\"center\":",
            shape.record_index,
            json_escape(&shape.shape_type),
        );
        if let Some(center) = shape.center {
            write_json_vector3(&mut out, center);
        } else {
            out.push_str("null");
        }
        out.push_str(",\"half_extents\":");
        if let Some(half_extents) = shape.half_extents {
            write_json_vector3(&mut out, half_extents);
        } else {
            out.push_str("null");
        }
        out.push_str(",\"radius\":");
        if let Some(radius) = shape.radius {
            let _ = write!(out, "{radius}");
        } else {
            out.push_str("null");
        }
        out.push_str(",\"endpoints\":");
        write_json_vector3_array(&mut out, &shape.endpoints);
        out.push_str(",\"vertices\":");
        write_json_vector3_array(&mut out, &shape.vertices);
        out.push_str(",\"triangles\":[");
        for (triangle_index, triangle) in shape.triangles.iter().enumerate() {
            if triangle_index > 0 {
                out.push(',');
            }
            let _ = write!(out, "[{},{},{}]", triangle[0], triangle[1], triangle[2]);
        }
        out.push_str("]}");
    }
    out.push_str("],\"warnings\":[");
    for (index, warning) in preview.warnings.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(warning));
    }
    out.push_str("]}");
    out
}

fn write_json_vector3(out: &mut String, value: [f32; 3]) {
    let _ = write!(out, "[{},{},{}]", value[0], value[1], value[2]);
}

fn write_json_vector3_array(out: &mut String, values: &[[f32; 3]]) {
    out.push('[');
    for (index, value) in values.iter().copied().enumerate() {
        if index > 0 {
            out.push(',');
        }
        write_json_vector3(out, value);
    }
    out.push(']');
}
