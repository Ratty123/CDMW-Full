struct ParSection {
    int index = 0;
    std::uint32_t offset = 0;
    std::uint32_t size = 0;
};

struct PacDescriptor {
    std::string name;
    std::string material;
    Vec3 bbox_min;
    Vec3 bbox_extent;
    std::array<std::uint32_t, 10> vertex_counts{};
    std::array<std::uint32_t, 10> index_counts{};
    int stored_lod_count = 0;
    std::uint32_t descriptor_offset = 0;
};

struct NativeSubmesh {
    std::string name;
    std::string material;
    std::string source_model_path;
    std::string source_component_label;
    int model_property_index = 0;
    std::vector<Vec3> positions;
    std::vector<Vec2> uvs;
    std::vector<Vec3> normals;
    std::vector<std::uint32_t> indices;
    std::vector<std::int32_t> source_vertex_indices;
    int source_submesh_index = -1;
    int source_local_submesh_index = -1;
    int source_component_index = 0;
    bool source_prefab_component = false;
    bool source_context_component = false;
    std::string vertex_layout_name;
    int vertex_stride = 40;
    int uv_offset = 8;
    int normal_offset = 16;
    float uv_finite_ratio = 0.0f;
    float uv_span_u = 0.0f;
    float uv_span_v = 0.0f;
    float uv_abs_max = 0.0f;
    float uv_edge_outlier_ratio = 0.0f;
    float uv_degenerate_triangle_ratio = 0.0f;
    float degenerate_triangle_ratio = 0.0f;
    float edge_outlier_ratio = 0.0f;
    float normal_valid_ratio = 0.0f;
    float geometry_quality_score = 0.0f;
    bool geometry_safe = true;
    std::string geometry_quality_note;
};

struct NativePbdSidecarHint {
    std::string simulation_material_name;
    std::string material_name;
    std::string submesh_name;
    std::string parameter_name;
    std::string sidecar_path;
    std::string simulation_kind = "unknown";
};

struct NativePbdConfigMaterial {
    std::string name;
    std::string filename;
    std::string mode;
    std::string pbd_part;
};

struct NativePbdMaterialSettings {
    std::string material_name;
    std::string material_path;
    std::string simulation_kind = "cloth";
    float stretching_stiffness = 0.30f;
    float bending_stiffness = 0.18f;
    float damping = 0.65f;
    float gravity = -10.0f;
    float air_resistance = 1.0f;
    float wind_response = 0.40f;
    int solver_iterations = 30;
    bool collision_enabled = true;
    bool is_cloak = false;
};

struct NativeClothConstraint {
    int a = 0;
    int b = 0;
    float rest_length = 0.0f;
    float stiffness = 0.0f;
};

struct NativeClothRuntimeBatch {
    bool active = false;
    NativePbdSidecarHint hint;
    NativePbdMaterialSettings settings;
    fs::path particle_path;
    fs::path pin_path;
    fs::path constraint_path;
    int particle_count = 0;
    int constraint_count = 0;
};

struct MaterialParameterRecord {
    std::string kind;
    std::string name;
    std::string value;
    float numeric_value = 0.0f;
    bool has_numeric = false;
    // Integer PAC fields are source identifiers/bit patterns, not floats. Keep
    // their canonical decimal representation so Byte4/BitFlag32/UInt values
    // survive JSON transport without f32 rounding (notably 0xFFFFFFFF).
    std::string integer_value;
    bool has_integer = false;
    std::string tag_name;
    std::string string_item_id;
    std::string item_id;
    int index = -1;
    std::string texture_path;
};

struct NativeMaterialConservationRow {
    std::string sidecar_path;
    std::vector<std::string> representation_sidecar_paths;
    std::string component_scope_id;
    std::string material_name;
    std::string shader_family;
    std::string owner_wrapper_item_id;
    int material_wrapper_index = -1;
    int owner_slot_index = -1;
    MaterialParameterRecord parameter;
    std::string role;
    std::string layer_role;
    std::string layer_channel;
    std::string resolved_source_path;
    std::string resolved_archive_path;
    std::string source_resolution;
    std::string source_resolution_detail;
    std::string semantic_type;
    std::string semantic_subtype;
    std::string packed_channels;
    std::string srgb_mode;
    std::string sidecar_kind;
    bool declared_source_missing = false;
    bool logical_graph_edge = false;
    bool texture_resolved = false;
    std::string status = "transported";
    std::string finding;
};

struct TextureBinding {
    std::string role;
    std::string source_path;
    std::string archive_path;
    std::string texture_name;
    std::string parameter_name;
    std::string declared_texture_path;
    std::string source_resolution = "declared_exact";
    std::string source_resolution_detail;
    bool declared_source_missing = false;
    std::string semantic_type;
    std::string semantic_subtype;
    std::string shader_family;
    std::string shader_rule;
    std::string material_name;
    std::string owner_wrapper_item_id;
    std::string sidecar_path;
    std::vector<std::string> representation_sidecar_paths;
    std::string component_scope_id;
    std::string sidecar_kind;
    std::string linked_mesh_path;
    std::string packed_channels;
    std::string material_output_quality = "inferred";
    std::string srgb_mode = "auto";
    std::string parameter_declared_by;
    std::string visible_class = "visible_generic";
    std::string source_authority = "sidecar";
    std::string relation_confidence = "derived_same_stem";
    std::string relation_reason = "Recovered by native material index.";
    std::string layer_role;
    std::string layer_channel;
    std::string evidence_grade = "corpus_inferred";
    std::string blend_flags;
    std::string material_parameter_names;
    std::vector<MaterialParameterRecord> material_parameters;
    std::string pbd_simulation_material_name;
    std::string pbd_simulation_kind;
    std::string pbd_material_name;
    std::string pbd_submesh_name;
    int material_wrapper_index = -1;
    int material_wrapper_count = 0;
    bool material_wrapper_order_authoritative = false;
    bool alpha_test_enabled = false;
    float layer_weight = 0.0f, detail_scale = 0.0f;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float height_scale_hint = 0.0f;
    bool roughness_hint_present = false;
    bool metalness_hint_present = false;
    bool specular_hint_present = false;
    bool height_scale_hint_present = false;
    float emissive_intensity_hint = 0.0f;
    // Neutral unless the material authors an emissive colour. An `_emi` map
    // already carries the colour it emits, so a non-neutral default would tint
    // every glow in the game the same shade.
    std::array<float, 3> emissive_color{1.0f, 1.0f, 1.0f};
    std::array<float, 4> tint_color{1.0f, 1.0f, 1.0f, 1.0f};
    std::array<std::array<float, 4>, 3> color_blending_tints{{
        {1.0f, 1.0f, 1.0f, 1.0f},
        {1.0f, 1.0f, 1.0f, 1.0f},
        {1.0f, 1.0f, 1.0f, 1.0f},
    }};
    int dds_width = 0;
    int dds_height = 0;
    std::string dds_format = "";
};

struct MaterialLayer {
    std::string component_scope_id;
    std::string owner_wrapper_item_id;
    int material_wrapper_index = -1;
    std::string layer_role;
    std::string layer_channel = "r";
    std::string shader_family;
    std::string shader_rule;
    std::string evidence_grade = "corpus_inferred";
    std::string blend_order = "base_then_layer";
    std::string source_parameter;
    std::string mask_parameter;
    std::string diffuse_source;
    std::string diffuse_archive_path;
    std::string normal_source;
    std::string normal_archive_path;
    std::string material_source;
    std::string material_archive_path;
    std::string height_source;
    std::string height_archive_path;
    std::string mask_source;
    std::string mask_archive_path;
    std::string roughness_hint_source;
    std::string metallic_hint_source;
    std::string specular_hint_source;
    float weight = 0.0f, detail_scale = 0.0f;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float height_scale_hint = 0.0f;
    std::array<float, 4> tint{1.0f, 1.0f, 1.0f, 1.0f};
};

struct NativeAssetFamilyRow {
    std::string group;
    std::string role;
    std::string display_name;
    std::string path;
    std::string status = "Resolved";
    std::string evidence = "Hint";
    std::string confidence = "derived_same_stem";
    std::string include_policy = "manual";
    std::string reason;
    std::string relation_kind = "metadata";
    std::string semantic_label;
    std::string semantic_hint;
    std::string sidecar_parameter_name;
    std::string material_name;
    std::string package_label;
    std::string sidecar_kind;
    std::string shader_family;
    std::string texture_role;
    std::string source_table;
    std::string source_field;
};

struct NativePackage {
    fs::path path;
    int batch_count = 0;
    int vertex_count = 0;
    int face_count = 0;
    int dds_candidates = 0;
    int dds_extracted = 0;
    double pamt_index_ms = 0.0;
    double mesh_parse_ms = 0.0;
    double material_binding_ms = 0.0;
    double package_write_ms = 0.0;
    size_t pamt_index_entries = 0;
    bool pamt_index_bounded_snapshot = false;
    bool pamt_index_cache_hit = false;
    std::string pamt_index_cache_path;
    std::string mesh_parse = "unsupported";
    bool presentation_geometry_applied = false;
    int presentation_geometry_vertex_count = 0;
    std::string presentation_geometry_source;
    int context_presentation_component_count = 0;
    int context_presentation_vertex_count = 0;
    std::string material_index = "none";
    std::string material_graph_status = "not_started";
    std::string material_graph_cache_path;
    bool material_graph_cache_hit = false;
    std::string texture_resolution = "none";
    std::string material_output_quality = "approximate";
    std::vector<std::string> notes;
    int lod_count = 0;
    bool material_quality_safe = true;
    int base_missing_count = 0;
    int base_low_res_count = 0;
    int base_low_confidence_count = 0;
    int base_technical_count = 0;
    int pbd_hint_count = 0;
    int pbd_soft_hint_count = 0;
    int pbd_cloth_hint_count = 0;
    std::vector<std::string> base_quality_notes;
    std::vector<std::string> selected_texture_examples;
    std::vector<std::string> rejected_texture_examples;
    std::vector<NativeAssetFamilyRow> asset_family_rows;
    int asset_family_reference_count = 0;
    bool material_conservation_ok = true;
    std::vector<NativeMaterialConservationRow> material_conservation_rows;
    std::vector<std::string> material_conservation_findings;
};
