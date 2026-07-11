use crate::*;

pub(crate) fn add_mesh_shape_header_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if type_name == "hknpMeshShape" && payload.len() >= 16 {
        fields.push(layout_field(
            "mesh_shape_header_words",
            0,
            payload.len().min(64),
            "uint32[]",
            Some(LayoutValue::Text(format!(
                "word_sample_count={}",
                payload.len().min(64) / 4
            ))),
            "Read-only hknpMeshShape object header sample. Mesh-shape section/primitive schema is still being recovered.",
            "experimental",
            false,
        ));
    }
}

pub(crate) fn add_geometry_section_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if type_name == "hknpMeshShape::GeometrySection" && payload.len() >= 32 {
        for (offset, name, description) in [
            (
                0usize,
                "aabb_tree_relative_offset",
                "Candidate byte offset from the geometry-section area to hknpAabb8TreeNode data.",
            ),
            (
                4usize,
                "aabb_tree_node_count",
                "Candidate count of quantized AABB tree nodes referenced by this section.",
            ),
            (
                8usize,
                "primitive_relative_offset",
                "Candidate byte offset to packed primitive/index tuples for this section.",
            ),
            (
                12usize,
                "primitive_count",
                "Candidate primitive tuple count for this section.",
            ),
            (
                16usize,
                "mesh_byte_buffer_relative_offset",
                "Candidate byte offset to a mesh byte/index buffer used by this section.",
            ),
            (
                20usize,
                "mesh_byte_buffer_size",
                "Candidate byte length for the first mesh byte/index buffer.",
            ),
            (
                24usize,
                "secondary_buffer_relative_offset",
                "Candidate byte offset to a secondary mesh buffer or range table.",
            ),
            (
                28usize,
                "secondary_buffer_count_or_size",
                "Candidate count or byte length for the secondary mesh buffer.",
            ),
        ] {
            fields.push(layout_field(
                name,
                offset,
                4,
                "uint32",
                le_u32(&payload[offset..offset + 4]).map(LayoutValue::U32),
                description,
                "strong inference",
                false,
            ));
        }
        if payload.len() >= 56 {
            for (offset, name) in [
                (44usize, "quantization_or_scale_x"),
                (48usize, "quantization_or_scale_y"),
                (52usize, "quantization_or_scale_z"),
            ] {
                fields.push(layout_field(
                    name,
                    offset,
                    4,
                    "float32",
                    le_f32(&payload[offset..offset + 4]).map(LayoutValue::F32),
                    "Candidate float scale/quantization field for mesh bounds or AABB decoding.",
                    "experimental",
                    false,
                ));
            }
        }
    }
}

pub(crate) fn add_mesh_primitive_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if type_name == "hknpMeshShape::GeometrySection::Primitive" && !payload.is_empty() {
        let tuple_count = (payload.len() / 4).min(record.count as usize).min(128);
        let mut min_index: Option<u8> = None;
        let mut max_index: Option<u8> = None;
        let mut quad_count = 0usize;
        let mut triangle_count = 0usize;
        for tuple_index in 0..tuple_count {
            let base = tuple_index * 4;
            let tuple = &payload[base..base + 4];
            let active = tuple
                .iter()
                .copied()
                .filter(|value| *value != 0xFF)
                .collect::<Vec<_>>();
            if active.len() == 3 {
                triangle_count += 1;
            } else if active.len() == 4 {
                quad_count += 1;
            }
            for value in active {
                min_index = Some(min_index.map_or(value, |current| current.min(value)));
                max_index = Some(max_index.map_or(value, |current| current.max(value)));
            }
            if tuple_index < 32 {
                fields.push(layout_field(
                    &format!("primitive_tuple[{tuple_index}]"),
                    base,
                    4,
                    "uint8[4]",
                    Some(LayoutValue::Text(format!(
                        "{}, {}, {}, {}",
                        tuple[0], tuple[1], tuple[2], tuple[3]
                    ))),
                    "Read-only four-byte primitive tuple candidate. Values behave like compact vertex/primitive indices in sampled Crimson Desert mesh HKX files.",
                    "experimental",
                    false,
                ));
            }
        }
        fields.push(layout_field(
            "primitive_tuple_summary",
            0,
            tuple_count * 4,
            "summary",
            Some(LayoutValue::Text(format!(
                "tuples={tuple_count}; index_range={}..{}; quads={quad_count}; triangles={triangle_count}",
                min_index.map(|value| value.to_string()).unwrap_or_else(|| "?".to_string()),
                max_index.map(|value| value.to_string()).unwrap_or_else(|| "?".to_string())
            ))),
            "Read-only topology candidate summary. Primitive edits remain blocked until shape tags and AABB/tree rebuild rules are recovered.",
            "experimental",
            false,
        ));
    }
}

pub(crate) fn add_aabb_tree_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if type_name == "hknpAabb8TreeNode" && payload.len() >= 32 {
        let tuple_count = (payload.len() / 32).min(record.count as usize).min(64);
        fields.push(layout_field(
            "aabb8_candidate_node_summary",
            0,
            tuple_count * 32,
            "summary",
            Some(LayoutValue::Text(format!(
                "candidate_stride=32; decoded_nodes={tuple_count}; declared_count={}",
                record.count
            ))),
            "Read-only hknpAabb8TreeNode candidate segmentation. Bytes appear to contain quantized bounds and child/primitive links.",
            "experimental",
            false,
        ));
    }
}

pub(crate) fn add_convex_shape_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if type_name == "hknpConvexShape" && payload.len() >= 0x68 {
        for (offset, name, description) in [
            (
                0x30,
                "vertices_offset_count",
                "Observed pair; count often matches decoded vertex count.",
            ),
            (
                0x40,
                "planes_offset_count",
                "Observed pair; count often matches decoded hull plane count.",
            ),
            (
                0x48,
                "faces_offset_count",
                "Observed pair; count often matches decoded face count.",
            ),
            (
                0x50,
                "face_indices_offset_count",
                "Observed pair; count often matches face-index byte count.",
            ),
            (
                0x58,
                "edge_table_a_offset_count",
                "Observed pair; likely convex edge/support metadata.",
            ),
            (
                0x60,
                "edge_table_b_offset_count",
                "Observed pair; likely convex edge/support metadata.",
            ),
        ] {
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]",
                Some(LayoutValue::Text(format!(
                    "{}, {}",
                    le_u32(&payload[offset..offset + 4]).unwrap_or(0),
                    le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0)
                ))),
                description,
                "strong inference",
                false,
            ));
        }
    }
}

pub(crate) fn add_box_shape_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if type_name == "hknpBoxShape" && payload.len() >= 0x6C {
        for (offset, name, description) in [
            (
                0x30,
                "shape_property_or_material_index",
                "Observed hknpBoxShape word. In Crimson Desert samples this often looks like a small property/material index.",
            ),
            (
                0x38,
                "box_vertices_offset_count",
                "Likely offset/count pair for the eight box corner vertices or equivalent local box point table.",
            ),
            (
                0x40,
                "box_planes_offset_count",
                "Likely offset/count pair for the six box plane equations.",
            ),
            (
                0x48,
                "box_faces_offset_count",
                "Likely offset/count pair for the six box face records.",
            ),
            (
                0x50,
                "box_face_indices_offset_count",
                "Likely offset/count pair for the fixed box face-index byte buffer.",
            ),
            (
                0x58,
                "box_edge_table_a_offset_count",
                "Likely offset/count pair for box edge/support metadata.",
            ),
            (
                0x60,
                "box_edge_table_b_offset_count",
                "Likely offset/count pair for box edge/support metadata.",
            ),
        ] {
            fields.push(layout_field(
                name,
                offset,
                8,
                if offset == 0x30 { "uint32[2]/index" } else { "uint32[2]" },
                Some(LayoutValue::Text(format!(
                    "{}, {}",
                    le_u32(&payload[offset..offset + 4]).unwrap_or(0),
                    le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0)
                ))),
                description,
                if offset >= 0x38 { "strong inference" } else { "experimental" },
                false,
            ));
        }
        for (offset, name, description) in [
            (
                0x68,
                "convex_radius_or_collision_margin",
                "Likely box convex radius/collision margin. Kept read-only until the exact hknpBoxShape field role is confirmed.",
            ),
            (
                0x6C,
                "aabb_or_radius_factor",
                "Likely AABB expansion/radius factor for the box shape. Kept read-only until confirmed across more samples.",
            ),
        ] {
            if offset + 4 <= payload.len() {
                fields.push(layout_field(
                    name,
                    offset,
                    4,
                    "float32",
                    le_f32(&payload[offset..offset + 4]).map(LayoutValue::F32),
                    description,
                    "strong inference",
                    false,
                ));
            }
        }
        if payload.len() >= 0xC0 {
            for row_index in 0..4usize {
                let row_offset = 0x80 + row_index * 16;
                let row = (0..4usize)
                    .map(|component| {
                        le_f32(&payload[row_offset + component * 4..row_offset + component * 4 + 4])
                            .unwrap_or(0.0)
                    })
                    .map(|value| format!("{value:.6}"))
                    .collect::<Vec<_>>()
                    .join(", ");
                fields.push(layout_field(
                    &format!("box_local_frame_or_extent_row[{row_index}]"),
                    row_offset,
                    16,
                    "float32[4]",
                    Some(LayoutValue::Text(row)),
                    "Likely local box frame, center, extent, or packed transform row. Included for comparison between samples; not safe for GUI editing yet.",
                    "experimental",
                    false,
                ));
            }
            fields.push(layout_field(
                "box_local_frame_or_extents",
                0x80,
                0x40,
                "float32[4][4]",
                Some(LayoutValue::Text("4 rows".to_string())),
                "Four-row hknpBoxShape float block observed in real Crimson Desert samples. This is likely where local orientation/center/extents live, but exact field names need more sample correlation before edits are enabled.",
                "experimental",
                false,
            ));
        }
    }
}

pub(crate) fn add_box_sample_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if type_name == "hknpBoxShape" && payload.len() >= 32 {
        let words = (0..payload.len().min(64) / 4)
            .map(|word_index| le_u32(&payload[word_index * 4..word_index * 4 + 4]).unwrap_or(0))
            .map(|word| format!("0x{word:08X}"))
            .collect::<Vec<_>>()
            .join(" ");
        fields.push(layout_field(
            "box_shape_payload_sample",
            0,
            payload.len().min(128),
            "float32[]/uint32[]",
            Some(LayoutValue::Text(words)),
            "Read-only hknpBoxShape payload sample. Box half-extents/orientation fields are not fully named yet.",
            "experimental",
            false,
        ));
    }
}
