struct NativePackageGeometryStats {
    Vec3 center{};
    float scale = 1.0f;
    int source_vertex_count = 0;
    int face_count = 0;
};

static NativePackageGeometryStats inspect_package_geometry(const std::vector<NativeSubmesh>& submeshes) {
    Vec3 minimum{1.0e30f, 1.0e30f, 1.0e30f};
    Vec3 maximum{-1.0e30f, -1.0e30f, -1.0e30f};
    NativePackageGeometryStats stats;
    for (const NativeSubmesh& mesh : submeshes) {
        stats.source_vertex_count += static_cast<int>(mesh.positions.size());
        stats.face_count += static_cast<int>(mesh.indices.size() / 3u);
        for (const Vec3& position : mesh.positions) {
            minimum.x = std::min(minimum.x, position.x);
            minimum.y = std::min(minimum.y, position.y);
            minimum.z = std::min(minimum.z, position.z);
            maximum.x = std::max(maximum.x, position.x);
            maximum.y = std::max(maximum.y, position.y);
            maximum.z = std::max(maximum.z, position.z);
        }
    }
    stats.center = {
        (minimum.x + maximum.x) * 0.5f,
        (minimum.y + maximum.y) * 0.5f,
        (minimum.z + maximum.z) * 0.5f,
    };
    const float max_dimension = std::max({
        maximum.x - minimum.x, maximum.y - minimum.y, maximum.z - minimum.z, 1.0e-6f});
    stats.scale = 2.0f / max_dimension;
    return stats;
}

struct PackageWriteState {
    const EntryJob& job;
    const std::vector<NativeSubmesh>& submeshes;
    const std::vector<TextureBinding>& bindings;
    NativePackage package;
    fs::path package_dir;
    fs::path geometry_dir;
    const PamtIndex* package_index = nullptr;
    NativePackageGeometryStats geometry;
    std::ostringstream batches_json;
    std::ostringstream material_slots_json;
    std::ostringstream selection_decisions_json;
    int emitted_batch_count = 0;
    int emitted_vertex_count = 0;
    int cloth_runtime_batch_count = 0;
    int cloth_runtime_particle_count = 0;
    int cloth_runtime_constraint_count = 0;
    bool has_metal_preview_response = false;
};

struct PackageBatchState {
    size_t index = 0;
    const NativeSubmesh* mesh = nullptr;
    std::string stem;
    fs::path geometry_path;
    fs::path identity_path;
    std::array<float, 3> color{};
    int vertex_count = 0;
    int base_score = 0;
    int normal_score = 0;
    int material_score = 0;
    int height_score = 0;
    int specular_score = 0;
    int detail_score = 0;
    int emissive_score = 0;
    const TextureBinding* base = nullptr;
    const TextureBinding* normal = nullptr;
    const TextureBinding* material = nullptr;
    const TextureBinding* height = nullptr;
    const TextureBinding* specular = nullptr;
    const TextureBinding* detail = nullptr;
    const TextureBinding* emissive = nullptr;
    const TextureBinding* preview_emissive = nullptr;
    bool visible_layer_albedo_used = false;
    bool base_low_authority_overlay_selected = false;
    int visible_layer_albedo_score = 0;
    bool visible_layer_tint_applied = false;
    std::array<float, 4> visible_layer_tint_color{1.0f, 1.0f, 1.0f, 1.0f};
    int base_identity_score = 0;
    bool base_technical = false;
    bool base_wrong_family_layer = false;
    bool base_semantically_unsafe_skin_albedo = false;
    bool base_low_res = false;
    bool base_low_authority = false;
    bool base_low_confidence = false;
    std::vector<const TextureBinding*> bindings;
    NativeClothRuntimeBatch cloth_runtime;
    bool is_hair = false;
    bool is_eye_surface = false;
    bool has_alpha_test = false;
    bool uses_alpha_cutout = false;
    float alpha_threshold = 0.0f;
    NativeMaterialHints material_hints;
    bool held_layer_albedo = false;
    std::vector<MaterialLayer> material_layers;
    std::string material_category;
    std::string material_category_reason;
    float material_category_confidence = 0.0f;
    NativeMaterialHints effective_material_hints;
    bool force_nonmetal_equipment_layer_tint = false;
    bool material_response_promoted = false;
    std::string material_response;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float roughness_hint = 0.0f;
    float base_tint_strength = 0.0f;
    bool base_tint_only_fallback = false;
    const MaterialLayer* primary_layer = nullptr;
};

static const TextureBinding* package_preview_base(const PackageBatchState& batch) {
    return batch.base_tint_only_fallback ? nullptr : batch.base;
}

static PackageWriteState start_package_write(
    const EntryJob& job,
    const std::vector<NativeSubmesh>& submeshes,
    const std::vector<TextureBinding>& bindings,
    NativePackage package
) {
    const fs::path package_dir = job.output_root;
    const fs::path geometry_dir = package_dir / "geometry";
    fs::create_directories(geometry_dir);
    return PackageWriteState{
        job,
        submeshes,
        bindings,
        std::move(package),
        package_dir,
        geometry_dir,
        &cached_pamt_index(job.entry.pamt_path, job.cache_root),
        inspect_package_geometry(submeshes),
    };
}

static PackageBatchState start_package_batch(PackageWriteState& state, size_t batch_index) {
    const NativeSubmesh& mesh = state.submeshes[batch_index];
    PackageBatchState batch;
    batch.index = batch_index;
    batch.mesh = &mesh;
    batch.stem = batch_stem(batch_index);
    batch.geometry_path = state.geometry_dir / (batch.stem + ".bin");
    batch.identity_path = state.geometry_dir / (batch.stem + "_identity.bin");
    batch.color = color_for_batch(static_cast<int>(batch_index));
    write_geometry_blob(
        batch.geometry_path,
        batch.identity_path,
        mesh,
        state.geometry.center,
        state.geometry.scale,
        batch.color);
    batch.vertex_count = static_cast<int>(mesh.indices.size());
    state.emitted_vertex_count += batch.vertex_count;
    return batch;
}

static void record_base_quality(PackageWriteState& state, PackageBatchState& batch) {
    const NativeSubmesh& mesh = *batch.mesh;
    const TextureBinding* base = batch.base;
    if (state.job.use_textures && base == nullptr) {
        ++state.package.base_missing_count;
        state.package.material_quality_safe = false;
        state.package.base_quality_notes.push_back(
            "batch " + std::to_string(batch.index) + " " + mesh.material + ": no reliable base DDS");
    } else if (state.job.use_textures && batch.base_technical) {
        ++state.package.base_technical_count;
        state.package.material_quality_safe = false;
        state.package.base_quality_notes.push_back(
            "batch " + std::to_string(batch.index) + " " + mesh.material + ": technical base rejected " + base->texture_name);
    } else if (state.job.use_textures && batch.base_wrong_family_layer) {
        ++state.package.base_low_confidence_count;
        state.package.material_quality_safe = false;
        state.package.base_quality_notes.push_back(
            "batch " + std::to_string(batch.index) + " " + mesh.material + ": wrong-family layer/terrain base fallback " + base->texture_name);
    } else if (state.job.use_textures && batch.base_low_res) {
        ++state.package.base_low_res_count;
        state.package.material_quality_safe = false;
        state.package.base_quality_notes.push_back(
            "batch " + std::to_string(batch.index) + " " + mesh.material + ": low-resolution base "
            + base->texture_name + " " + std::to_string(base->dds_width) + "x" + std::to_string(base->dds_height));
    } else if (state.job.use_textures && batch.base_low_authority) {
        ++state.package.base_low_confidence_count;
        state.package.material_quality_safe = false;
        state.package.base_quality_notes.push_back(
            "batch " + std::to_string(batch.index) + " " + mesh.material + ": low-authority base fallback " + base->texture_name);
    } else if (state.job.use_textures && batch.base_low_confidence) {
        ++state.package.base_low_confidence_count;
        state.package.material_quality_safe = false;
        state.package.base_quality_notes.push_back(
            "batch " + std::to_string(batch.index) + " " + mesh.material + ": low-confidence base "
            + base->texture_name + " score=" + std::to_string(batch.base_score)
            + " identity=" + std::to_string(batch.base_identity_score));
    }
}
