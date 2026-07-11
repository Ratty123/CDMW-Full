use crate::*;

pub(crate) fn item_record_by_index(
    records: &[ItemRecord],
    record_index: usize,
) -> Option<&ItemRecord> {
    records.iter().find(|record| record.index == record_index)
}

pub(crate) fn record_string_value(
    data: &[u8],
    records: &[ItemRecord],
    record_index: usize,
) -> Option<String> {
    let record = item_record_by_index(records, record_index)?;
    if record.type_name != "char" && record.type_name != "hkStringPtr" {
        return None;
    }
    let start = record.absolute_data_offset?;
    if start >= data.len() {
        return None;
    }
    let max_len = if record.type_name == "char" && record.count > 0 {
        record.count as usize
    } else {
        records
            .iter()
            .filter_map(|candidate| candidate.absolute_data_offset)
            .filter(|offset| *offset > start)
            .min()
            .unwrap_or(data.len())
            .saturating_sub(start)
    };
    let end = start.saturating_add(max_len).min(data.len());
    let raw = &data[start..end];
    let nul_end = raw.iter().position(|byte| *byte == 0).unwrap_or(raw.len());
    if nul_end == 0 {
        return None;
    }
    let text = String::from_utf8_lossy(&raw[..nul_end]).trim().to_string();
    (!text.is_empty()).then_some(text)
}

pub(crate) fn owner_array_element_type(
    owner_type: &str,
    field_name: &str,
    target_type: &str,
) -> String {
    match (owner_type, field_name) {
        ("hkRootLevelContainer", "namedVariants") => {
            "hkRootLevelContainer::NamedVariant".to_string()
        }
        ("hknpPhysicsSystemData", "materials") => "hknpMaterial".to_string(),
        ("hknpPhysicsSystemData", "motionProperties") => "hknpSharedMotionProperties".to_string(),
        ("hknpPhysicsSystemData", "bodyCinfos") => {
            "hknpPhysicsSystemData::ExtendedBodyCinfo".to_string()
        }
        ("hknpPhysicsSystemData", "constraintCinfos") => "hknpConstraintCinfo".to_string(),
        ("hknpPhysicsSystemData", "shapeReferences") => "hkRefPtr<hknpShape>".to_string(),
        ("hknpPhysicsSceneData", _) => "hknpPhysicsSystemData".to_string(),
        ("hknpRagdollData", _) => "hknpConstraintCinfo".to_string(),
        ("hknpConvexShape", "vertices") | ("hknpBoxShape", "vertices") => "hkFloat3".to_string(),
        ("hknpConvexShape", "planes") | ("hknpBoxShape", "planes") => "hkVector4".to_string(),
        ("hknpConvexShape", "faces") | ("hknpBoxShape", "faces") => {
            "hknpConvexHull::Face".to_string()
        }
        ("hknpConvexShape", "faceIndices") | ("hknpBoxShape", "faceIndices") => {
            "hkUint8".to_string()
        }
        ("hknpCompoundShape", "shapeInstances") => "hknpShapeInstance".to_string(),
        ("hknpCompoundShape", "simdTreeNodes") => "hkcdSimdTreeNamespace::Node".to_string(),
        ("hknpCompoundShape", "shapeProperties") => "hknpShapeProperties::Entry".to_string(),
        ("hkSkeleton", "bones") => "hkBone".to_string(),
        ("hkSkeleton", "parentIndices") => "hkInt16".to_string(),
        ("hkSkeleton", "referencePose") => "hkQsTransform".to_string(),
        ("hkaSkeletonMapper", "mappingData") => "hkaSkeletonMapperData::SimpleMapping".to_string(),
        _ if !target_type.is_empty() => target_type.to_string(),
        _ => "void".to_string(),
    }
}

pub(crate) fn owner_array_type(owner_type: &str, field_name: &str, target_type: &str) -> String {
    let element_type = owner_array_element_type(owner_type, field_name, target_type);
    format!("hkArray<{element_type}>")
}

pub(crate) fn read_owner_array_count(
    data: &[u8],
    owner: &ItemRecord,
    owner_local_offset: usize,
    target: &ItemRecord,
) -> Option<u32> {
    let absolute = owner
        .absolute_data_offset?
        .saturating_add(owner_local_offset);
    if absolute.saturating_add(12) <= data.len() {
        if let Some(size) = le_u32(&data[absolute + 8..absolute + 12]) {
            if size <= 1_000_000 {
                return Some(size);
            }
        }
    }
    (target.count > 0).then_some(target.count)
}

pub(crate) fn graph_class_priority(type_name: &str) -> u8 {
    match type_name {
        "hkRootLevelContainer" => 0,
        "hkRootLevelContainer::NamedVariant" => 1,
        "hknpPhysicsSceneData" => 2,
        "hknpPhysicsSystemData" | "hknpRagdollData" => 3,
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => 4,
        "hknpConstraintCinfo" => 5,
        name if name.contains("ConstraintData") => 6,
        name if name.contains("Shape") => 7,
        "hknpMaterial" | "hknpSharedMotionProperties" => 8,
        "hkSkeleton" | "hkaAnimationContainer" | "hkaSkeletonMapper" => 9,
        _ => 32,
    }
}

pub(crate) fn build_graph_order(
    records: &[ItemRecord],
    edges: &[NativeGraphEdge],
    root_record_index: Option<usize>,
) -> Vec<usize> {
    let mut ordered = Vec::<usize>::new();
    let mut queue = Vec::<usize>::new();
    if let Some(root) = root_record_index {
        queue.push(root);
    }
    while let Some(record_index) = queue.pop() {
        if ordered.contains(&record_index) {
            continue;
        }
        ordered.push(record_index);
        let mut children = edges
            .iter()
            .filter(|edge| edge.source_record_index == Some(record_index))
            .filter_map(|edge| edge.target_record_index)
            .filter(|target| !ordered.contains(target) && !queue.contains(target))
            .collect::<Vec<_>>();
        children.sort_unstable();
        for child in children.into_iter().rev() {
            queue.push(child);
        }
    }
    let mut remaining = records
        .iter()
        .filter(|record| !ordered.contains(&record.index))
        .collect::<Vec<_>>();
    remaining.sort_by_key(|record| {
        (
            graph_class_priority(&record.type_name),
            record.data_offset,
            record.index,
        )
    });
    ordered.extend(remaining.into_iter().map(|record| record.index));
    ordered
}

pub(crate) fn native_root_info(
    data: &[u8],
    records: &[ItemRecord],
    edges: &[NativeGraphEdge],
) -> NativeRootInfo {
    let named_variant_records = records
        .iter()
        .filter(|record| record.type_name == "hkRootLevelContainer::NamedVariant")
        .map(|record| record.index)
        .collect::<Vec<_>>();
    let mut named_variants = Vec::new();
    for variant_record_index in named_variant_records {
        let mut name = None;
        let mut class_name = None;
        let mut object_record_index = None;
        for edge in edges
            .iter()
            .filter(|edge| edge.source_record_index == Some(variant_record_index))
        {
            match edge.owner_field_name.as_deref() {
                Some("name") => {
                    name = edge
                        .target_record_index
                        .and_then(|target| record_string_value(data, records, target));
                }
                Some("className") => {
                    class_name = edge
                        .target_record_index
                        .and_then(|target| record_string_value(data, records, target));
                }
                Some("variant") => {
                    object_record_index = edge.target_record_index;
                }
                _ => {}
            }
        }
        let object_type_name = object_record_index
            .and_then(|index| item_record_by_index(records, index))
            .map(|record| record.type_name.clone());
        named_variants.push(NativeNamedVariant {
            variant_record_index,
            name,
            class_name,
            object_record_index,
            object_type_name,
            confidence: if object_record_index.is_some() {
                "strong inference".to_string()
            } else {
                "experimental".to_string()
            },
        });
    }
    if let Some(root) = records
        .iter()
        .find(|record| record.type_name == "hkRootLevelContainer")
    {
        return NativeRootInfo {
            record_index: Some(root.index),
            type_name: Some(root.type_name.clone()),
            method: "native_hkRootLevelContainer".to_string(),
            confidence: "strong inference".to_string(),
            named_variant_count: named_variants.len(),
            named_variants,
        };
    }
    if let Some(variant_target) = named_variants
        .iter()
        .find_map(|variant| variant.object_record_index)
    {
        let root_record = item_record_by_index(records, variant_target);
        return NativeRootInfo {
            record_index: Some(variant_target),
            type_name: root_record.map(|record| record.type_name.clone()),
            method: "native_named_variant_target".to_string(),
            confidence: "strong inference".to_string(),
            named_variant_count: named_variants.len(),
            named_variants,
        };
    }
    let preferred = [
        "hknpPhysicsSceneData",
        "hknpPhysicsSystemData",
        "hknpRagdollData",
        "hkaAnimationContainer",
        "hkSkeleton",
    ];
    for class_name in preferred {
        if let Some(record) = records.iter().find(|record| record.type_name == class_name) {
            return NativeRootInfo {
                record_index: Some(record.index),
                type_name: Some(record.type_name.clone()),
                method: "native_preferred_root_class".to_string(),
                confidence: "strong inference".to_string(),
                named_variant_count: named_variants.len(),
                named_variants,
            };
        }
    }
    let first = records.first();
    NativeRootInfo {
        record_index: first.map(|record| record.index),
        type_name: first.map(|record| record.type_name.clone()),
        method: if first.is_some() {
            "native_first_record_fallback".to_string()
        } else {
            "not_recovered".to_string()
        },
        confidence: if first.is_some() {
            "experimental".to_string()
        } else {
            "none".to_string()
        },
        named_variant_count: named_variants.len(),
        named_variants,
    }
}

pub(crate) fn add_native_graph_edge(
    edges: &mut Vec<NativeGraphEdge>,
    seen: &mut Vec<(usize, Option<usize>, Option<usize>, String)>,
    edge: NativeGraphEdge,
) {
    let key = (
        edge.source_record_index.unwrap_or(usize::MAX),
        edge.target_record_index,
        edge.owner_local_offset,
        edge.resolution_source.clone(),
    );
    if seen.contains(&key) {
        return;
    }
    seen.push(key);
    edges.push(edge);
}

pub(crate) fn empty_native_model_graph() -> NativeModelGraph {
    NativeModelGraph {
        format: "cd_hkx_native_model_graph_v1".to_string(),
        status: "not_recovered".to_string(),
        imported: false,
        node_count: 0,
        edge_count: 0,
        fixup_backed_reference_edge_count: 0,
        inferred_reference_edge_count: 0,
        owner_array_count: 0,
        root: NativeRootInfo {
            record_index: None,
            type_name: None,
            method: "not_recovered".to_string(),
            confidence: "none".to_string(),
            named_variant_count: 0,
            named_variants: Vec::new(),
        },
        graph_order: Vec::new(),
        nodes: Vec::new(),
        edges: Vec::new(),
        owner_arrays: Vec::new(),
    }
}

pub(crate) fn build_native_graph_edges(
    records: &[ItemRecord],
    objects: &[ObjectRecord],
    fixups: &TagfileFixupSummary,
) -> Vec<NativeGraphEdge> {
    let mut edges = Vec::<NativeGraphEdge>::new();
    let mut seen_edges = Vec::<(usize, Option<usize>, Option<usize>, String)>::new();
    for section in &fixups.sections {
        for table in &section.ptch_tables {
            for site in &table.patch_sites {
                let Some(owner_record_index) = site.owner_record_index else {
                    continue;
                };
                let Some(owner) = item_record_by_index(records, owner_record_index) else {
                    continue;
                };
                let local_offset = site.owner_local_offset.unwrap_or(0);
                let (field_name, field_category) =
                    object_reference_owner_field(&owner.type_name, local_offset)
                        .map(|(name, category)| (Some(name.to_string()), category.to_string()))
                        .unwrap_or((None, site.reference_category.clone()));
                let target = site
                    .target_record_index
                    .and_then(|index| item_record_by_index(records, index));
                add_native_graph_edge(
                    &mut edges,
                    &mut seen_edges,
                    NativeGraphEdge {
                        source: format!("record:{owner_record_index}"),
                        target: site
                            .target_record_index
                            .map(|index| format!("record:{index}"))
                            .unwrap_or_else(|| "null".to_string()),
                        relation: field_name
                            .clone()
                            .unwrap_or_else(|| "fixup_reference".to_string()),
                        source_record_index: Some(owner_record_index),
                        target_record_index: site.target_record_index,
                        owner_field_name: field_name,
                        owner_local_offset: site.owner_local_offset,
                        reference_category: if site.target_status == "null" {
                            "null_reference".to_string()
                        } else {
                            field_category
                        },
                        resolution_source: "ptch".to_string(),
                        confidence: if target.is_some() || site.target_status == "null" {
                            "strong inference".to_string()
                        } else {
                            "experimental".to_string()
                        },
                    },
                );
            }
        }
    }
    let ptch_owner_offsets = edges
        .iter()
        .filter(|edge| edge.resolution_source == "ptch")
        .filter_map(|edge| Some((edge.source_record_index?, edge.owner_local_offset?)))
        .collect::<Vec<_>>();
    for object in objects {
        let Some(owner) = item_record_by_index(records, object.record_index) else {
            continue;
        };
        for reference in &object.references {
            if ptch_owner_offsets.contains(&(object.record_index, reference.offset)) {
                continue;
            }
            add_native_graph_edge(
                &mut edges,
                &mut seen_edges,
                NativeGraphEdge {
                    source: format!("record:{}", object.record_index),
                    target: format!("record:{}", reference.target_record_index),
                    relation: reference
                        .owner_field_name
                        .clone()
                        .unwrap_or_else(|| reference.reference_kind.clone()),
                    source_record_index: Some(object.record_index),
                    target_record_index: Some(reference.target_record_index),
                    owner_field_name: reference.owner_field_name.clone(),
                    owner_local_offset: Some(reference.offset),
                    reference_category: reference.reference_category.clone(),
                    resolution_source: "inferred_offset".to_string(),
                    confidence: if owner.type_name.is_empty() {
                        "experimental".to_string()
                    } else {
                        "strong inference".to_string()
                    },
                },
            );
        }
    }
    edges
}

pub(crate) fn build_native_owner_arrays(
    data: &[u8],
    records: &[ItemRecord],
    edges: &[NativeGraphEdge],
) -> Vec<NativeOwnerArray> {
    let mut owner_arrays = Vec::<NativeOwnerArray>::new();
    let mut seen_arrays = Vec::<(usize, usize, usize)>::new();
    for edge in edges {
        if edge.reference_category != "array_data_reference" {
            continue;
        }
        let (Some(owner_record_index), Some(target_record_index), Some(owner_local_offset)) = (
            edge.source_record_index,
            edge.target_record_index,
            edge.owner_local_offset,
        ) else {
            continue;
        };
        let key = (owner_record_index, target_record_index, owner_local_offset);
        if seen_arrays.contains(&key) {
            continue;
        }
        let Some(owner) = item_record_by_index(records, owner_record_index) else {
            continue;
        };
        let Some(target) = item_record_by_index(records, target_record_index) else {
            continue;
        };
        let field_name = edge
            .owner_field_name
            .clone()
            .unwrap_or_else(|| "data".to_string());
        seen_arrays.push(key);
        owner_arrays.push(NativeOwnerArray {
            owner_record_index,
            owner_type_name: owner.type_name.clone(),
            field_name: field_name.clone(),
            target_record_index,
            target_type_name: target.type_name.clone(),
            array_type: owner_array_type(&owner.type_name, &field_name, &target.type_name),
            element_type: owner_array_element_type(
                &owner.type_name,
                &field_name,
                &target.type_name,
            ),
            numelements: read_owner_array_count(data, owner, owner_local_offset, target),
            owner_local_offset,
            resolution_source: edge.resolution_source.clone(),
            confidence: edge.confidence.clone(),
        });
    }
    owner_arrays
}

pub(crate) fn build_native_graph_nodes(
    records: &[ItemRecord],
    graph_order: &[usize],
) -> Vec<NativeGraphNode> {
    let order_by_record = graph_order
        .iter()
        .enumerate()
        .map(|(order, record_index)| (*record_index, order))
        .collect::<BTreeMap<_, _>>();
    records
        .iter()
        .map(|record| NativeGraphNode {
            id: format!("record:{}", record.index),
            kind: "item_record".to_string(),
            label: format!("{}: {}", record.index, record.type_name),
            record_index: Some(record.index),
            type_index: Some(record.type_index),
            type_name: Some(record.type_name.clone()),
            data_offset: Some(record.data_offset),
            count: Some(record.count),
            graph_order: order_by_record
                .get(&record.index)
                .copied()
                .unwrap_or(record.index),
        })
        .collect()
}

pub(crate) fn build_native_model_graph(
    data: &[u8],
    records: &[ItemRecord],
    objects: &[ObjectRecord],
    fixups: &TagfileFixupSummary,
) -> NativeModelGraph {
    if records.is_empty() {
        return empty_native_model_graph();
    }
    let edges = build_native_graph_edges(records, objects, fixups);
    let owner_arrays = build_native_owner_arrays(data, records, &edges);
    let root = native_root_info(data, records, &edges);
    let graph_order = build_graph_order(records, &edges, root.record_index);
    let nodes = build_native_graph_nodes(records, &graph_order);
    let fixup_backed_reference_edge_count = edges
        .iter()
        .filter(|edge| edge.resolution_source == "ptch" && edge.target_record_index.is_some())
        .count();
    let inferred_reference_edge_count = edges
        .iter()
        .filter(|edge| edge.resolution_source == "inferred_offset")
        .count();
    NativeModelGraph {
        format: "cd_hkx_native_model_graph_v1".to_string(),
        status: if edges.is_empty() {
            "native_object_nodes_only"
        } else {
            "native_model_graph_partial"
        }
        .to_string(),
        imported: false,
        node_count: nodes.len(),
        edge_count: edges.len(),
        fixup_backed_reference_edge_count,
        inferred_reference_edge_count,
        owner_array_count: owner_arrays.len(),
        root,
        graph_order,
        nodes,
        edges,
        owner_arrays,
    }
}
