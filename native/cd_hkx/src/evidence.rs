use crate::*;

pub(crate) fn push_unique_limited(values: &mut Vec<String>, value: &str, limit: usize) {
    if values.len() >= limit || value.is_empty() || values.iter().any(|item| item == value) {
        return;
    }
    values.push(value.to_string());
}

pub(crate) fn push_unique_usize_limited(values: &mut Vec<usize>, value: usize, limit: usize) {
    if values.len() >= limit || values.contains(&value) {
        return;
    }
    values.push(value);
}

pub(crate) fn hard_internal_target_specs() -> Vec<(&'static str, &'static str, &'static str)> {
    vec![
        (
            "hknp_mesh_primitive_bit_layout",
            "hknpMeshShape primitive bit layout",
            "Packed primitive tuple bytes, triangle/quad detection, winding, shape-key bits, and section/material ownership.",
        ),
        (
            "hknp_mesh_aabb_tree",
            "hknpMeshShape AABB tree node encoding",
            "Quantized AABB tree nodes, child/leaf flags, primitive ranges, and section-local node ownership.",
        ),
        (
            "hknp_mesh_shape_tags",
            "hknpMeshShape shape tag ranges/tables",
            "Shape tag table/range ownership, per-primitive tag lookup, and material/filter linkage.",
        ),
        (
            "compound_child_transforms",
            "compound child transforms",
            "Compound shape child instances, local transforms, child shape references, tree nodes, and property ownership.",
        ),
        (
            "compressed_mass_properties",
            "compressed mass properties",
            "hknpShapeMassProperties, hkCompressedMassProperties, hkPackedVector3 scale/offset, inertia, center, and mass factors.",
        ),
        (
            "material_property_entries",
            "material/property/free-list entries",
            "hknpMaterial fields, hknpShapeProperties::Entry, hkFreeListArrayElement rows, ids, flags, and game material mapping.",
        ),
        (
            "skeleton_animation_containers",
            "skeleton/animation containers",
            "hkSkeleton, bones, parent indices, reference pose, hkaAnimationContainer, skeleton mappers, clips, and binding references.",
        ),
    ]
}

pub(crate) fn hard_internal_target_blockers(key: &str) -> Vec<String> {
    match key {
        "hknp_mesh_primitive_bit_layout" => vec![
            "primitive tuple bit roles are still inferred from byte patterns".to_string(),
            "shape keys/material ownership are not proven".to_string(),
            "only same-index-set winding/order edits are safe".to_string(),
        ],
        "hknp_mesh_aabb_tree" => vec![
            "quantized bounds scale/offset ownership is not proven".to_string(),
            "child/leaf flags and primitive-range linkage need corpus proof".to_string(),
            "AABB nodes cannot be rebuilt safely yet".to_string(),
        ],
        "hknp_mesh_shape_tags" => vec![
            "shape tag ranges and table ownership are not proven".to_string(),
            "per-primitive tag resolution needs mesh-heavy corpus samples".to_string(),
            "tag/material/filter linkage is read-only".to_string(),
        ],
        "compound_child_transforms" => vec![
            "shape-instance transform layout is still experimental".to_string(),
            "child shape refs need fixup-backed ownership across samples".to_string(),
            "compound tree/property rebuild rules are unknown".to_string(),
        ],
        "compressed_mass_properties" => vec![
            "compressed vector scale/offset ownership is unknown".to_string(),
            "mass/inertia/center fields are not mapped to real Havok names".to_string(),
            "compressed mass payload rebuild is blocked".to_string(),
        ],
        "material_property_entries" => vec![
            "material friction/restitution/filter fields are not confirmed".to_string(),
            "free-list entry semantics and allocation state are unknown".to_string(),
            "game material id/name linkage needs descriptor/corpus correlation".to_string(),
        ],
        "skeleton_animation_containers" => vec![
            "animation clip/container arrays are not fully owner-typed".to_string(),
            "mapper row transform/index semantics need paired skeleton corpus proof".to_string(),
            "skeleton/animation reference ownership is read-only".to_string(),
        ],
        _ => Vec::new(),
    }
}

pub(crate) fn hard_internal_target_keys_for_type(type_name: &str) -> Vec<&'static str> {
    let mut keys = Vec::new();
    match type_name {
        "hknpMeshShape" | "hknpMeshShape::GeometrySection" => {
            keys.push("hknp_mesh_primitive_bit_layout");
            keys.push("hknp_mesh_aabb_tree");
            keys.push("hknp_mesh_shape_tags");
        }
        "hknpMeshShape::GeometrySection::Primitive" => {
            keys.push("hknp_mesh_primitive_bit_layout");
        }
        "hknpAabb8TreeNode" | "hkcdSimdTreeNamespace::Node" => {
            keys.push("hknp_mesh_aabb_tree");
        }
        "hknpMeshShape::ShapeTagTableEntry" => {
            keys.push("hknp_mesh_shape_tags");
        }
        "hknpCompoundShape" | "hknpShapeInstance" => {
            keys.push("compound_child_transforms");
        }
        "hknpShapeMassProperties" | "hkCompressedMassProperties" | "hkPackedVector3" => {
            keys.push("compressed_mass_properties");
        }
        "hknpMaterial" | "hknpShapeProperties::Entry" => {
            keys.push("material_property_entries");
        }
        "hkSkeleton"
        | "hkBone"
        | "hkInt16"
        | "hkQsTransform"
        | "hkaSkeletonMapper"
        | "hkaSkeletonMapperData::SimpleMapping"
        | "hkaAnimationContainer" => {
            keys.push("skeleton_animation_containers");
        }
        _ => {}
    }
    if type_name.starts_with("hkFreeListArrayElement") {
        keys.push("material_property_entries");
    }
    keys
}

pub(crate) fn build_hard_internal_evidence(objects: &[ObjectRecord]) -> HardInternalEvidenceReport {
    let specs = hard_internal_target_specs();
    let mut targets = specs
        .iter()
        .map(|(key, label, description)| HardInternalEvidenceTarget {
            key: (*key).to_string(),
            label: (*label).to_string(),
            description: (*description).to_string(),
            status: "open_needs_corpus_sample".to_string(),
            proof_status: "needs_corpus_sample".to_string(),
            present_in_file: false,
            resolved: false,
            import_blocking: true,
            observed_record_count: 0,
            observed_byte_count: 0,
            observed_types: Vec::new(),
            observed_fields: Vec::new(),
            record_indices: Vec::new(),
            unresolved_blockers: hard_internal_target_blockers(key),
            confidence: "none".to_string(),
        })
        .collect::<Vec<_>>();

    for object in objects {
        let keys = hard_internal_target_keys_for_type(&object.type_name);
        if keys.is_empty() {
            continue;
        }
        for key in keys {
            let Some(target) = targets.iter_mut().find(|target| target.key == key) else {
                continue;
            };
            target.present_in_file = true;
            target.observed_record_count += 1;
            target.observed_byte_count += object.byte_length;
            push_unique_limited(&mut target.observed_types, &object.type_name, 24);
            push_unique_usize_limited(&mut target.record_indices, object.record_index, 48);
            for field in &object.fields {
                if field.confidence == "raw" {
                    continue;
                }
                push_unique_limited(&mut target.observed_fields, &field.name, 64);
                if matches!(field.confidence.as_str(), "confirmed" | "strong inference") {
                    target.confidence = "strong inference".to_string();
                } else if target.confidence == "none" {
                    target.confidence = "experimental".to_string();
                }
            }
            if target.confidence == "none" {
                target.confidence = "experimental".to_string();
            }
        }
    }

    for target in &mut targets {
        if target.present_in_file {
            target.status = "open_observed_unproven".to_string();
            target.proof_status = "needs_corpus_proof".to_string();
        }
    }

    let observed_target_count = targets
        .iter()
        .filter(|target| target.present_in_file)
        .count();
    let unresolved_target_count = targets.iter().filter(|target| !target.resolved).count();
    let total_observed_byte_count = targets
        .iter()
        .map(|target| target.observed_byte_count)
        .sum::<usize>();
    HardInternalEvidenceReport {
        format: "cd_hkx_hard_internal_evidence_v1".to_string(),
        status: if observed_target_count > 0 {
            "hard_internals_observed_unproven".to_string()
        } else {
            "hard_internals_need_corpus".to_string()
        },
        imported: false,
        target_count: targets.len(),
        observed_target_count,
        unresolved_target_count,
        total_observed_byte_count,
        targets,
    }
}

pub(crate) fn decoder_reference_semantic_from_parts(
    reference_category: &str,
    match_kind: &str,
    target_status: &str,
) -> &'static str {
    let category = reference_category.to_ascii_lowercase();
    let kind = match_kind.to_ascii_lowercase();
    let status = target_status.to_ascii_lowercase();
    if kind.contains("varuint")
        || kind.contains("packed")
        || category.contains("varuint")
        || category.contains("packed")
    {
        return "packed_or_varuint";
    }
    if status == "null" || kind == "null" || category == "null_reference" {
        return "null";
    }
    if status == "object" || category == "object_reference" {
        return "object";
    }
    if category == "array_data_reference"
        || category == "data_reference"
        || category == "data_reference_candidate"
    {
        return "data_candidate";
    }
    if category == "string_reference" {
        return "string_candidate";
    }
    if category == "type_reference" || category == "type_class_reference" {
        return "type_class";
    }
    if status == "unresolved"
        || category == "unresolved_fixup_word"
        || category == "unresolved"
        || kind == "unresolved_word"
    {
        return "unresolved";
    }
    "unresolved"
}

pub(crate) fn decoder_link_evidence_for_edge(edge: &NativeGraphEdge) -> &'static str {
    if edge.resolution_source == "ptch" {
        return "fixup_backed";
    }
    if edge.reference_category == "array_data_reference" {
        return "declared_owner_array";
    }
    if edge.resolution_source == "typed_layout" {
        return "typed_layout";
    }
    if edge.resolution_source == "inferred_offset" {
        return "inferred";
    }
    "raw_observation"
}

pub(crate) fn decoder_missing_requirements_for_type(type_name: &str, status: &str) -> Vec<String> {
    if type_name.starts_with("hkArray") {
        return vec![
            "owner-field array mapping".to_string(),
            "element template/class metadata".to_string(),
            "fixup-backed data pointer semantics".to_string(),
            "rebuild-safe count/capacity rules".to_string(),
        ];
    }
    if type_name.starts_with("hkRefPtr") || type_name.starts_with("hkRelPtr") {
        return vec![
            "PTCH/fixup-backed target classification".to_string(),
            "null/data/string/type reference distinction".to_string(),
            "target class member metadata".to_string(),
        ];
    }
    let hard_keys = hard_internal_target_keys_for_type(type_name);
    let mut requirements = Vec::<String>::new();
    for key in hard_keys {
        for blocker in hard_internal_target_blockers(key) {
            push_unique_limited(&mut requirements, &blocker, 12);
        }
    }
    if requirements.is_empty() && type_name.starts_with("hknp") {
        requirements.push("real hkClass member metadata".to_string());
        requirements.push("member flags/offsets/defaults".to_string());
        requirements.push("owner/reference semantics".to_string());
    }
    if requirements.is_empty() && (type_name.starts_with("hk") || type_name.starts_with("hka")) {
        requirements.push("real hkClass member metadata".to_string());
        requirements.push("template/owner array context".to_string());
    }
    if requirements.is_empty() && (status == "raw_preserved" || status == "raw") {
        requirements.push("typed payload decoder".to_string());
    }
    requirements
}

pub(crate) fn decoder_friendly_status_for_type(type_name: &str, status: &str) -> String {
    match type_name {
        "hknpMeshShape" | "hknpMeshShape::GeometrySection" => {
            "Readable, missing AABB/tree and primitive ownership semantics".to_string()
        }
        "hknpMeshShape::GeometrySection::Primitive" => {
            "Readable, missing primitive bit layout semantics".to_string()
        }
        "hknpMeshShape::ShapeTagTableEntry" => {
            "Readable, missing shape tag range semantics".to_string()
        }
        "hknpTriangleShape" => {
            "Readable, missing triangle material/shape-tag semantics".to_string()
        }
        "hknpCompoundShape" | "hknpShapeInstance" => {
            "Readable, missing compound child transform ownership".to_string()
        }
        "hknpMaterial" | "hknpShapeProperties::Entry" => {
            "Readable, missing material/property table semantics".to_string()
        }
        "hknpShapeMassProperties" | "hkCompressedMassProperties" | "hkPackedVector3" => {
            "Readable, missing compressed mass rules".to_string()
        }
        "hkSkeleton"
        | "hkBone"
        | "hkQsTransform"
        | "hkaSkeletonMapper"
        | "hkaSkeletonMapperData::SimpleMapping"
        | "hkaAnimationContainer" => {
            "Readable, missing skeleton/animation owner semantics".to_string()
        }
        _ if type_name.starts_with("hkArray") => {
            "Readable, missing owner array element type".to_string()
        }
        _ if type_name.starts_with("hkRefPtr") || type_name.starts_with("hkRelPtr") => {
            "Readable, missing reference target semantics".to_string()
        }
        _ if status == "raw_preserved" || status == "raw" => {
            "Raw preserved, decoder needed".to_string()
        }
        _ if status == "editable" => {
            "Fixed-size patch slots recovered; official hkClass names still partial".to_string()
        }
        _ => "Readable, not fully mapped".to_string(),
    }
}

pub(crate) fn decoder_reference_counts(
    fixups: &TagfileFixupSummary,
    fixup_semantics: &FixupSemanticsReport,
) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::<String, usize>::new();
    let mut observations = 0usize;
    for section in &fixups.sections {
        for word in &section.words {
            if word.reference_category.is_empty() {
                continue;
            }
            observations += 1;
            increment_count(
                &mut counts,
                decoder_reference_semantic_from_parts(
                    &word.reference_category,
                    &word.match_kind,
                    "",
                ),
            );
        }
        for table in &section.ptch_tables {
            for site in &table.patch_sites {
                observations += 1;
                increment_count(
                    &mut counts,
                    decoder_reference_semantic_from_parts(
                        &site.reference_category,
                        "",
                        &site.target_status,
                    ),
                );
            }
        }
    }
    if observations == 0 {
        for (category, count) in &fixups.reference_category_counts {
            increment_count_by(
                &mut counts,
                decoder_reference_semantic_from_parts(category, "", ""),
                *count,
            );
        }
    }
    for case in &fixup_semantics.ptch_remaining_case_priorities {
        if case.case_name.contains("varuint") || case.case_name.contains("packed") {
            increment_count_by(&mut counts, "packed_or_varuint", case.count);
        } else if case.case_name.contains("unresolved") {
            increment_count_by(&mut counts, "unresolved", case.count);
        }
    }
    counts
}

pub(crate) fn decoder_link_counts(
    objects: &[ObjectRecord],
    graph: &NativeModelGraph,
) -> (
    BTreeMap<String, usize>,
    BTreeMap<String, Vec<String>>,
    BTreeMap<(String, String, String), (usize, String)>,
) {
    let mut link_counts = BTreeMap::<String, usize>::new();
    let mut class_links = BTreeMap::<String, Vec<String>>::new();
    let record_type = objects
        .iter()
        .map(|object| (object.record_index, object.type_name.clone()))
        .collect::<BTreeMap<_, _>>();
    let mut fixup_fields = BTreeMap::<(String, String, String), (usize, String)>::new();
    for edge in &graph.edges {
        let evidence = decoder_link_evidence_for_edge(edge);
        increment_count(&mut link_counts, evidence);
        for record_index in [edge.source_record_index, edge.target_record_index]
            .iter()
            .flatten()
        {
            if let Some(type_name) = record_type.get(record_index) {
                push_unique_limited(
                    class_links.entry(type_name.clone()).or_default(),
                    evidence,
                    8,
                );
            }
        }
        if edge.resolution_source != "ptch" {
            continue;
        }
        let Some(source_record_index) = edge.source_record_index else {
            continue;
        };
        let Some(class_name) = record_type.get(&source_record_index) else {
            continue;
        };
        let field_name = edge
            .owner_field_name
            .clone()
            .unwrap_or_else(|| edge.relation.clone());
        let entry = fixup_fields
            .entry((
                class_name.clone(),
                field_name,
                edge.reference_category.clone(),
            ))
            .or_insert_with(|| (0, edge.confidence.clone()));
        entry.0 += 1;
        if entry.1 == "experimental" && edge.confidence != "experimental" {
            entry.1 = edge.confidence.clone();
        }
    }
    if !graph.owner_arrays.is_empty() {
        increment_count_by(
            &mut link_counts,
            "declared_owner_array",
            graph.owner_arrays.len(),
        );
        for array in &graph.owner_arrays {
            push_unique_limited(
                class_links
                    .entry(array.owner_type_name.clone())
                    .or_default(),
                "declared_owner_array",
                8,
            );
        }
    }
    (link_counts, class_links, fixup_fields)
}

pub(crate) fn decoder_class_statuses(
    objects: &[ObjectRecord],
    mut class_links: BTreeMap<String, Vec<String>>,
) -> (Vec<DecoderEvidenceClassStatus>, usize) {
    let mut rows = BTreeMap::<String, DecoderEvidenceClassStatus>::new();
    for object in objects {
        let row =
            rows.entry(object.type_name.clone())
                .or_insert_with(|| DecoderEvidenceClassStatus {
                    type_name: object.type_name.clone(),
                    record_count: 0,
                    byte_count: 0,
                    decoded_field_count: 0,
                    reference_count: 0,
                    editable_field_count: 0,
                    status: object.status.clone(),
                    friendly_status: String::new(),
                    missing_requirements: Vec::new(),
                    link_evidence: Vec::new(),
                    corpus_priority_score: 0,
                    read_only: true,
                });
        row.record_count += 1;
        row.byte_count += object.byte_length;
        row.decoded_field_count += object
            .fields
            .iter()
            .filter(|field| field.confidence != "raw")
            .count();
        row.editable_field_count += object.fields.iter().filter(|field| field.editable).count();
        row.reference_count += object.references.len();
        if row.status != "raw_preserved" && object.status == "raw_preserved" {
            row.status = object.status.clone();
        } else if row.status == "editable" && object.status != "editable" {
            row.status = object.status.clone();
        }
    }
    let mut statuses = rows.into_values().collect::<Vec<_>>();
    let mut total_partial_byte_count = 0usize;
    for row in &mut statuses {
        row.missing_requirements =
            decoder_missing_requirements_for_type(&row.type_name, &row.status);
        row.friendly_status = decoder_friendly_status_for_type(&row.type_name, &row.status);
        row.link_evidence = class_links.remove(&row.type_name).unwrap_or_default();
        let partial_weight = if matches!(
            row.status.as_str(),
            "partially_decoded" | "raw_preserved" | "raw"
        ) {
            row.byte_count
        } else {
            row.byte_count / 4
        };
        total_partial_byte_count += partial_weight;
        row.corpus_priority_score = partial_weight
            + row.reference_count.saturating_mul(64)
            + row.missing_requirements.len().saturating_mul(256)
            + row.record_count.saturating_mul(128);
    }
    statuses.sort_by(|left, right| {
        right
            .corpus_priority_score
            .cmp(&left.corpus_priority_score)
            .then_with(|| left.type_name.cmp(&right.type_name))
    });
    (statuses, total_partial_byte_count)
}

pub(crate) fn build_decoder_evidence_v2(
    objects: &[ObjectRecord],
    fixups: &TagfileFixupSummary,
    fixup_semantics: &FixupSemanticsReport,
    graph: &NativeModelGraph,
) -> DecoderEvidenceV2 {
    let reference_semantic_counts = decoder_reference_counts(fixups, fixup_semantics);
    let (link_evidence_counts, class_links, fixup_fields) = decoder_link_counts(objects, graph);
    let (class_statuses, total_partial_byte_count) = decoder_class_statuses(objects, class_links);
    let mut fixup_backed_fields = fixup_fields
        .into_iter()
        .map(
            |((class_name, field_name, reference_category), (count, confidence))| {
                DecoderEvidenceFixupBackedField {
                    class_name,
                    field_name,
                    reference_category,
                    count,
                    confidence,
                }
            },
        )
        .collect::<Vec<_>>();
    fixup_backed_fields.sort_by(|left, right| {
        right
            .count
            .cmp(&left.count)
            .then_with(|| left.class_name.cmp(&right.class_name))
            .then_with(|| left.field_name.cmp(&right.field_name))
    });
    let unresolved_or_packed_case_count = reference_semantic_counts
        .get("unresolved")
        .copied()
        .unwrap_or(0)
        + reference_semantic_counts
            .get("packed_or_varuint")
            .copied()
            .unwrap_or(0);
    let priority_class_count = class_statuses
        .iter()
        .filter(|row| !row.missing_requirements.is_empty())
        .count();
    DecoderEvidenceV2 {
        format: "cd_hkx_decoder_evidence_v2".to_string(),
        status: if objects.is_empty() {
            "no_object_records"
        } else {
            "read_only_native_evidence"
        }
        .to_string(),
        imported: false,
        read_only: true,
        class_status_count: class_statuses.len(),
        priority_class_count,
        total_partial_byte_count,
        unresolved_or_packed_case_count,
        owner_array_count: graph.owner_array_count,
        reference_semantic_counts,
        link_evidence_counts,
        class_statuses,
        fixup_backed_fields,
    }
}
