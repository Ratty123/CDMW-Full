
static std::string native_asset_family_summary(const std::vector<NativeAssetFamilyRow>& rows) {
    int materials = 0;
    int textures = 0;
    int physics = 0;
    int meshinfo = 0;
    int prefab = 0;
    int skeleton = 0;
    for (const NativeAssetFamilyRow& row : rows) {
        if (row.group == "Material") ++materials;
        else if (row.group == "Textures") ++textures;
        else if (row.group == "Physics / HKX") ++physics;
        else if (row.group == "MeshInfo") ++meshinfo;
        else if (row.group == "Prefab / Metadata") ++prefab;
        else if (row.group == "Skeleton / Rig") ++skeleton;
    }
    std::ostringstream out;
    out << "Model OK";
    if (materials) out << " | " << materials << " material";
    if (textures) out << " | " << textures << " textures";
    if (physics) out << " | HKX hint";
    if (meshinfo) out << " | meshinfo hint";
    if (prefab) out << " | prefab hint";
    if (skeleton) out << " | skeletons hint";
    return out.str();
}

static std::string native_asset_family_json(const NativePackage& package, const EntryJob& job) {
    std::ostringstream out;
    out << "\"asset_family\":{"
        << "\"source\":\"native-core\","
        << "\"schema_version\":" << kNativePackageSchemaVersion << ","
        << "\"root_path\":\"" << json_escape(job.path) << "\","
        << "\"family_key\":\"" << json_escape(stem_from_path(job.path)) << "\","
        << "\"summary\":\"" << json_escape(native_asset_family_summary(package.asset_family_rows)) << "\","
        << "\"reference_count\":" << package.asset_family_reference_count << ","
        << "\"member_rows\":[";
    for (size_t i = 0; i < package.asset_family_rows.size(); ++i) {
        const NativeAssetFamilyRow& row = package.asset_family_rows[i];
        if (i) out << ",";
        out << "{"
            << "\"group\":\"" << json_escape(row.group) << "\","
            << "\"role\":\"" << json_escape(row.role) << "\","
            << "\"display_name\":\"" << json_escape(row.display_name) << "\","
            << "\"path\":\"" << json_escape(row.path) << "\","
            << "\"status\":\"" << json_escape(row.status) << "\","
            << "\"evidence\":\"" << json_escape(row.evidence) << "\","
            << "\"confidence\":\"" << json_escape(row.confidence) << "\","
            << "\"include_policy\":\"" << json_escape(row.include_policy) << "\","
            << "\"reason\":\"" << json_escape(row.reason) << "\","
            << "\"relation_kind\":\"" << json_escape(row.relation_kind) << "\","
            << "\"semantic_label\":\"" << json_escape(row.semantic_label) << "\","
            << "\"semantic_hint\":\"" << json_escape(row.semantic_hint) << "\","
            << "\"sidecar_parameter_name\":\"" << json_escape(row.sidecar_parameter_name) << "\","
            << "\"material_name\":\"" << json_escape(row.material_name) << "\","
            << "\"package_label\":\"" << json_escape(row.package_label) << "\","
            << "\"sidecar_kind\":\"" << json_escape(row.sidecar_kind) << "\","
            << "\"shader_family\":\"" << json_escape(row.shader_family) << "\","
            << "\"texture_role\":\"" << json_escape(row.texture_role) << "\","
            << "\"source_table\":\"" << json_escape(row.source_table) << "\","
            << "\"source_field\":\"" << json_escape(row.source_field) << "\""
            << "}";
    }
    out << "],\"references\":[";
    bool first = true;
    for (const NativeAssetFamilyRow& row : package.asset_family_rows) {
        if (row.group == "Selected Model") continue;
        if (row.path.empty()) continue;
        if (!first) out << ",";
        first = false;
        out << "{"
            << "\"reference_name\":\"" << json_escape(row.display_name.empty() ? basename_from_path(row.path) : row.display_name) << "\","
            << "\"material_name\":\"" << json_escape(row.material_name) << "\","
            << "\"semantic_label\":\"" << json_escape(row.semantic_label) << "\","
            << "\"semantic_hint\":\"" << json_escape(row.semantic_hint) << "\","
            << "\"sidecar_parameter_name\":\"" << json_escape(row.sidecar_parameter_name) << "\","
            << "\"sidecar_kind\":\"" << json_escape(row.sidecar_kind) << "\","
            << "\"shader_family\":\"" << json_escape(row.shader_family) << "\","
            << "\"texture_role\":\"" << json_escape(row.texture_role) << "\","
            << "\"resolution_status\":\"" << json_escape(lower_copy(row.status) == "resolved" ? "resolved" : "missing") << "\","
            << "\"resolved_archive_path\":\"" << json_escape(row.path) << "\","
            << "\"resolved_package_label\":\"" << json_escape(row.package_label) << "\","
            << "\"reference_kind\":\"" << json_escape(row.relation_kind.empty() ? "metadata" : row.relation_kind) << "\","
            << "\"relation_group\":\"" << json_escape(row.group) << "\","
            << "\"relation_reason\":\"" << json_escape(row.reason) << "\","
            << "\"relation_confidence\":\"" << json_escape(row.confidence) << "\","
            << "\"source_table\":\"" << json_escape(row.source_table) << "\","
            << "\"source_field\":\"" << json_escape(row.source_field) << "\""
            << "}";
    }
    out << "]}";
    return out.str();
}
