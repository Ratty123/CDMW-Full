use crate::*;

#[derive(Debug, Clone, PartialEq)]
pub struct HkxPreviewBone {
    pub index: usize,
    pub parent_index: i32,
    pub position: [f32; 3],
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HkxPreviewNode {
    pub record_index: usize,
    pub type_name: String,
    pub count: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HkxPreviewEdge {
    pub source_record_index: usize,
    pub target_record_index: usize,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HkxPreview {
    pub status: String,
    pub preview_kind: String,
    pub sdk_version: String,
    pub bone_count: usize,
    pub bones: Vec<HkxPreviewBone>,
    pub nodes: Vec<HkxPreviewNode>,
    pub edges: Vec<HkxPreviewEdge>,
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
    let (nodes, edges) = if bones.is_empty() {
        extract_structure_graph(&summary)
    } else {
        (Vec::new(), Vec::new())
    };
    let preview_kind = if !bones.is_empty() {
        "skeleton"
    } else if !nodes.is_empty() {
        "structure"
    } else {
        warnings.push("No renderable skeleton or native object graph was recovered.".to_string());
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
        nodes,
        edges,
        warnings,
    }
}

fn extract_skeleton_bones(
    data: &[u8],
    summary: &HkxSummary,
    warnings: &mut Vec<String>,
) -> Vec<HkxPreviewBone> {
    let owner_arrays = &summary.native_model_graph.owner_arrays;
    let pose_owner = owner_arrays
        .iter()
        .find(|owner| owner.owner_type_name == "hkSkeleton" && owner.field_name == "referencePose");
    let parent_owner = owner_arrays
        .iter()
        .find(|owner| owner.owner_type_name == "hkSkeleton" && owner.field_name == "parentIndices");
    let pose_record = pose_owner
        .and_then(|owner| item_record_by_index(&summary.item_records, owner.target_record_index))
        .filter(|record| record.type_name == "hkQsTransform")
        .or_else(|| {
            summary
                .item_records
                .iter()
                .find(|record| record.type_name == "hkQsTransform")
        });
    let Some(pose_record) = pose_record else {
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
        warnings.push(
            "Skeleton parent indices were not recovered; bones are shown as roots.".to_string(),
        );
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

fn extract_structure_graph(summary: &HkxSummary) -> (Vec<HkxPreviewNode>, Vec<HkxPreviewEdge>) {
    let mut nodes = summary
        .native_model_graph
        .nodes
        .iter()
        .filter_map(|node| {
            let record_index = node.record_index?;
            Some(HkxPreviewNode {
                record_index,
                type_name: node.type_name.clone().unwrap_or_else(|| node.label.clone()),
                count: node.count.unwrap_or(0),
            })
        })
        .take(128)
        .collect::<Vec<_>>();
    nodes.sort_by_key(|node| record_order(summary, node.record_index));
    let allowed = nodes
        .iter()
        .map(|node| node.record_index)
        .collect::<Vec<_>>();
    let mut edges = summary
        .native_model_graph
        .edges
        .iter()
        .filter_map(|edge| Some((edge.source_record_index?, edge.target_record_index?)))
        .filter(|(source, target)| {
            allowed.contains(source) && allowed.contains(target) && source != target
        })
        .map(|(source, target)| HkxPreviewEdge {
            source_record_index: source,
            target_record_index: target,
        })
        .take(256)
        .collect::<Vec<_>>();
    edges.sort_by_key(|edge| (edge.source_record_index, edge.target_record_index));
    edges.dedup_by_key(|edge| (edge.source_record_index, edge.target_record_index));
    (nodes, edges)
}

fn record_order(summary: &HkxSummary, record_index: usize) -> usize {
    summary
        .native_model_graph
        .graph_order
        .iter()
        .position(|candidate| *candidate == record_index)
        .unwrap_or(usize::MAX)
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
        "{{\"format\":\"cd_hkx_preview_v1\",\"status\":\"{}\",\"preview_kind\":\"{}\",\"sdk_version\":\"{}\",\"bone_count\":{},\"bones\":[",
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
    out.push_str("],\"nodes\":[");
    for (index, node) in preview.nodes.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"record_index\":{},\"type_name\":\"{}\",\"count\":{}}}",
            node.record_index,
            json_escape(&node.type_name),
            node.count
        );
    }
    out.push_str("],\"edges\":[");
    for (index, edge) in preview.edges.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"source_record_index\":{},\"target_record_index\":{}}}",
            edge.source_record_index, edge.target_record_index
        );
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
