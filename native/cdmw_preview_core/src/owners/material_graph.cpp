static std::string native_archive_path(std::string value) {
    std::replace(value.begin(), value.end(), '\\', '/');
    return value;
}

static void add_native_pbd_hint(
    std::vector<NativePbdSidecarHint>& hints,
    std::set<std::string>& seen,
    const std::string& pbd_name,
    const std::string& material_name,
    const std::string& submesh_name,
    const std::string& parameter_name,
    const std::string& sidecar_path
) {
    if (pbd_name.empty()) return;
    NativePbdSidecarHint hint;
    hint.simulation_material_name = pbd_name;
    hint.material_name = material_name;
    hint.submesh_name = submesh_name;
    hint.parameter_name = parameter_name;
    hint.sidecar_path = sidecar_path;
    hint.simulation_kind = native_pbd_simulation_kind({pbd_name, material_name, submesh_name, parameter_name});
    const std::string key =
        normalized_key(hint.simulation_material_name) + "|" +
        normalized_key(hint.material_name) + "|" +
        normalized_key(hint.submesh_name) + "|" +
        normalized_key(hint.parameter_name) + "|" +
        lower_copy(hint.sidecar_path);
    if (seen.insert(key).second) {
        hints.push_back(std::move(hint));
    }
}

static std::vector<NativePbdSidecarHint> extract_native_pbd_sidecar_hints(
    const std::string& text,
    const std::string& sidecar_path
) {
    std::vector<NativePbdSidecarHint> hints;
    std::set<std::string> seen;
    if (text.empty()) return hints;
    for (const std::string& tag : collect_xml_open_tags(text)) {
        const auto attrs = xml_attribute_map(tag);
        const std::string pbd_name = xml_attr_value_from_map(attrs, {"_pbdSimulationMaterialName", "pbdSimulationMaterialName"});
        if (pbd_name.empty()) continue;
        add_native_pbd_hint(
            hints,
            seen,
            pbd_name,
            xml_attr_value_from_map(attrs, {"_materialName", "materialName", "MaterialName"}),
            xml_attr_value_from_map(attrs, {"_subMeshName", "subMeshName", "SubMeshName"}),
            xml_attr_value_from_map(attrs, {"_name", "Name"}),
            sidecar_path
        );
    }
    for (const std::string& property_name : {"SkinnedMeshProperty", "OverridedPbdMaterialProperty", "PbdMaterialProperty"}) {
        for (const std::string& block : collect_xml_tag_blocks(text, property_name)) {
            const auto parent_attrs = xml_attribute_map(block);
            const std::string pbd_name = xml_attr_value_from_map(parent_attrs, {"_pbdSimulationMaterialName", "pbdSimulationMaterialName"});
            if (pbd_name.empty()) continue;
            const std::string parent_material = xml_attr_value_from_map(parent_attrs, {"_materialName", "materialName", "MaterialName"});
            const std::string parent_submesh = xml_attr_value_from_map(parent_attrs, {"_subMeshName", "subMeshName", "SubMeshName"});
            add_native_pbd_hint(hints, seen, pbd_name, parent_material, parent_submesh, property_name, sidecar_path);
            for (const std::string& wrapper : collect_xml_tag_blocks(block, "SkinnedMeshMaterialWrapper")) {
                const auto wrapper_attrs = xml_attribute_map(wrapper);
                std::string material_name = xml_attr_value_from_map(wrapper_attrs, {"_materialName", "materialName", "MaterialName"});
                std::string submesh_name = xml_attr_value_from_map(wrapper_attrs, {"_subMeshName", "subMeshName", "SubMeshName"});
                for (const std::string& material_tag : collect_xml_tag_blocks(wrapper, "Material")) {
                    const auto material_attrs = xml_attribute_map(material_tag);
                    const std::string nested_material = xml_attr_value_from_map(material_attrs, {"_materialName", "materialName", "MaterialName"});
                    if (!nested_material.empty()) {
                        material_name = nested_material;
                        break;
                    }
                }
                add_native_pbd_hint(hints, seen, pbd_name, material_name, submesh_name, "SkinnedMeshMaterialWrapper", sidecar_path);
            }
        }
    }
    return hints;
}

static std::map<std::string, NativePbdConfigMaterial> parse_native_pbd_config_materials(const std::string& text) {
    std::map<std::string, NativePbdConfigMaterial> materials;
    for (const std::string& tag : collect_xml_open_tags(text)) {
        const auto attrs = xml_attribute_map(tag);
        NativePbdConfigMaterial material;
        material.name = xml_attr_value_from_map(attrs, {"Name", "_name", "name"});
        material.filename = native_archive_path(xml_attr_value_from_map(attrs, {"Filename", "_filename", "filename"}));
        if (material.name.empty() || material.filename.empty()) continue;
        material.mode = xml_attr_value_from_map(attrs, {"Mode", "_mode", "mode"});
        material.pbd_part = xml_attr_value_from_map(attrs, {"PbdPart", "_pbdPart", "pbdPart"});
        materials[normalized_key(material.name)] = material;
    }
    return materials;
}

static std::map<std::string, std::string> native_material_scalar_values(const std::string& text) {
    std::map<std::string, std::string> values;
    for (const std::string& tag : collect_xml_open_tags(text)) {
        const auto attrs = xml_attribute_map(tag);
        const std::string name = xml_attr_value_from_map(attrs, {"Name", "_name", "name"});
        const std::string value = xml_attr_value_from_map(attrs, {"Value", "_value", "value", "DefaultValue"});
        if (!name.empty() && !value.empty()) {
            values[normalized_key(name)] = value;
        }
        for (const auto& [key, attr_value] : attrs) {
            if (!attr_value.empty()) {
                values[normalized_key(key)] = attr_value;
            }
        }
    }
    return values;
}

static std::string native_first_scalar(const std::map<std::string, std::string>& values, std::initializer_list<const char*> names) {
    for (const char* name : names) {
        auto found = values.find(normalized_key(name));
        if (found != values.end()) return found->second;
    }
    return "";
}

static float native_safe_float(const std::string& raw_value, float fallback) {
    if (raw_value.empty()) return fallback;
    bool ok = false;
    const float value = numeric_parameter_value(raw_value, &ok);
    if (!ok || !std::isfinite(value)) return fallback;
    return value;
}

static int native_safe_int(const std::string& raw_value, int fallback) {
    if (raw_value.empty()) return fallback;
    try {
        return static_cast<int>(std::lround(std::stof(raw_value)));
    } catch (...) {
        return fallback;
    }
}

static bool native_safe_bool(const std::string& raw_value, bool fallback) {
    const std::string text = lower_copy(raw_value);
    if (text == "1" || text == "true" || text == "yes" || text == "on" || text == "enabled") return true;
    if (text == "0" || text == "false" || text == "no" || text == "off" || text == "disabled") return false;
    return fallback;
}

static NativePbdMaterialSettings parse_native_pbd_material_settings(
    const std::string& text,
    const NativePbdConfigMaterial& config_material,
    const std::string& material_path
) {
    NativePbdMaterialSettings settings;
    settings.material_name = config_material.name;
    settings.material_path = material_path.empty() ? config_material.filename : material_path;
    settings.simulation_kind = native_pbd_simulation_kind({settings.material_name, settings.material_path, config_material.mode, config_material.pbd_part});
    settings.is_cloak = native_cloth_token_match(settings.material_name + " " + settings.material_path);
    const std::map<std::string, std::string> values = native_material_scalar_values(text);
    const std::string mode = native_first_scalar(values, {"SimulationMode", "Mode"});
    if (!mode.empty()) {
        settings.simulation_kind = native_pbd_simulation_kind({mode, settings.material_name, settings.material_path});
    }
    const std::string kind = lower_copy(settings.simulation_kind);
    if (kind == "leather") {
        settings.stretching_stiffness = 0.55f;
        settings.bending_stiffness = 0.34f;
        settings.damping = 0.82f;
        settings.wind_response = 0.22f;
    } else if (kind == "hair") {
        settings.stretching_stiffness = 0.24f;
        settings.bending_stiffness = 0.08f;
        settings.damping = 1.15f;
        settings.gravity = -6.5f;
        settings.air_resistance = 1.8f;
        settings.wind_response = 0.75f;
        settings.solver_iterations = 24;
        settings.collision_enabled = false;
    } else if (kind == "rope" || kind == "spline") {
        settings.stretching_stiffness = 0.82f;
        settings.bending_stiffness = 0.12f;
        settings.damping = 0.78f;
        settings.wind_response = 0.24f;
        settings.solver_iterations = 36;
    } else if (kind == "body_soft") {
        settings.stretching_stiffness = 0.45f;
        settings.bending_stiffness = 0.12f;
        settings.damping = 1.35f;
        settings.gravity = -4.0f;
        settings.wind_response = 0.10f;
        settings.solver_iterations = 20;
    }
    settings.stretching_stiffness = std::clamp(native_safe_float(native_first_scalar(values, {"StretchingStiffness", "StretchStiffness"}), settings.stretching_stiffness), 0.0f, 1.0f);
    settings.bending_stiffness = std::clamp(native_safe_float(native_first_scalar(values, {"BendingStiffness", "BendStiffness"}), settings.bending_stiffness), 0.0f, 1.0f);
    settings.damping = std::clamp(native_safe_float(native_first_scalar(values, {"Damping"}), settings.damping), 0.0f, 4.0f);
    settings.gravity = std::clamp(native_safe_float(native_first_scalar(values, {"Gravity"}), settings.gravity), -50.0f, 50.0f);
    settings.air_resistance = std::clamp(native_safe_float(native_first_scalar(values, {"AirResistance"}), settings.air_resistance), 0.0f, 8.0f);
    settings.wind_response = std::clamp(native_safe_float(native_first_scalar(values, {"WindResponse"}), settings.wind_response), 0.0f, 4.0f);
    settings.solver_iterations = std::clamp(native_safe_int(native_first_scalar(values, {"SolverIterationCount", "IterationCount"}), settings.solver_iterations), 1, 64);
    settings.collision_enabled = native_safe_bool(native_first_scalar(values, {"CollisionCheck", "CollisionEnabled"}), settings.collision_enabled);
    settings.is_cloak = native_safe_bool(native_first_scalar(values, {"IsCloak"}), settings.is_cloak);
    return settings;
}

struct TechniqueParameterInfo {
    std::string name;
    std::string type;
    std::string srgb;
    std::string default_value;
    bool declared = false;
};

struct TechniqueIndex {
    std::unordered_map<std::string, TechniqueParameterInfo> parameters_by_name;
    std::set<std::string> technique_names;
    int files_scanned = 0;
    int parameters = 0;
    int texture_parameters = 0;
};

static void add_technique_parameter(TechniqueIndex& index, const std::string& tag) {
    const auto attrs = xml_attribute_map(tag);
    TechniqueParameterInfo info;
    info.name = xml_attr_value_from_map(attrs, {"Name", "_name"});
    if (info.name.empty()) return;
    info.type = xml_attr_value_from_map(attrs, {"Type", "_type"});
    info.srgb = xml_attr_value_from_map(attrs, {"sRGB", "SRGB", "Srgb"});
    info.default_value = xml_attr_value_from_map(attrs, {"DefaultValue", "Value", "_defaultValue"});
    info.declared = true;
    ++index.parameters;
    const std::string key = lower_copy(info.name);
    const std::string type_lower = lower_copy(info.type);
    if (type_lower.find("texture") != std::string::npos || key.find("texture") != std::string::npos) {
        ++index.texture_parameters;
    }
    auto found = index.parameters_by_name.find(key);
    if (found == index.parameters_by_name.end()) {
        index.parameters_by_name.emplace(key, info);
    } else {
        if (found->second.srgb.empty()) found->second.srgb = info.srgb;
        if (found->second.type.empty()) found->second.type = info.type;
        if (found->second.default_value.empty()) found->second.default_value = info.default_value;
    }
}

static TechniqueIndex build_technique_index_for_pamt(const PamtIndex& pamt_index) {
    TechniqueIndex index;
    for (const ArchiveEntryRef& ref : pamt_index.material_sidecars) {
        if (ref.extension != ".technique" && ref.extension != ".material") continue;
        std::vector<char> bytes;
        try {
            bytes = read_archive_ref_decoded_bytes(ref);
        } catch (...) {
            continue;
        }
        ++index.files_scanned;
        const std::string text(bytes.begin(), bytes.end());
        for (const std::string& tag : collect_xml_tag_blocks(text, "Technique")) {
            const std::string name = xml_attr_value_from_map(xml_attribute_map(tag), {"Name"});
            if (!name.empty()) index.technique_names.insert(name);
        }
        for (const std::string& tag : collect_xml_tag_blocks(text, "Parameter")) {
            add_technique_parameter(index, tag);
        }
    }
    return index;
}

static void merge_technique_index(TechniqueIndex& destination, const TechniqueIndex& source) {
    destination.files_scanned += source.files_scanned;
    destination.parameters += source.parameters;
    destination.texture_parameters += source.texture_parameters;
    destination.technique_names.insert(source.technique_names.begin(), source.technique_names.end());
    for (const auto& [key, value] : source.parameters_by_name) {
        auto found = destination.parameters_by_name.find(key);
        if (found == destination.parameters_by_name.end()) {
            destination.parameters_by_name.emplace(key, value);
        } else {
            if (found->second.srgb.empty()) found->second.srgb = value.srgb;
            if (found->second.type.empty()) found->second.type = value.type;
            if (found->second.default_value.empty()) found->second.default_value = value.default_value;
        }
    }
}

static std::map<std::string, TechniqueIndex>& resident_technique_index_cache() {
    static std::map<std::string, TechniqueIndex> cache;
    return cache;
}

static std::map<std::string, TechniqueIndex>& resident_package_technique_index_cache() {
    static std::map<std::string, TechniqueIndex> cache;
    return cache;
}

static const TechniqueIndex& cached_technique_index(const PamtIndex& pamt_index) {
    auto& cache = resident_technique_index_cache();
    const std::string key = fs::absolute(pamt_index.pamt_path).string();
    auto it = cache.find(key);
    if (it == cache.end()) {
        it = cache.emplace(key, build_technique_index_for_pamt(pamt_index)).first;
    }
    return it->second;
}

static std::vector<fs::path> package_root_pamt_paths(const fs::path& package_root) {
    std::vector<fs::path> paths;
    if (package_root.empty()) return paths;
    std::error_code ec;
    if (fs::is_regular_file(package_root, ec) && package_root.extension() == ".pamt") {
        paths.push_back(package_root);
        return paths;
    }
    if (!fs::is_directory(package_root, ec)) return paths;
    for (const fs::directory_entry& root_entry : fs::directory_iterator(package_root, ec)) {
        if (ec) break;
        if (root_entry.is_regular_file(ec) && root_entry.path().extension() == ".pamt") {
            paths.push_back(root_entry.path());
        } else if (root_entry.is_directory(ec)) {
            std::error_code inner_ec;
            for (const fs::directory_entry& child : fs::directory_iterator(root_entry.path(), inner_ec)) {
                if (inner_ec) break;
                if (child.is_regular_file(inner_ec) && child.path().extension() == ".pamt") {
                    paths.push_back(child.path());
                }
            }
        }
        if (paths.size() >= 64) break;
    }
    std::sort(paths.begin(), paths.end());
    paths.erase(std::unique(paths.begin(), paths.end()), paths.end());
    return paths;
}

static const TechniqueIndex& cached_package_technique_index(
    const EntryJob& job,
    const PamtIndex& primary_index
) {
    if (job.package_root.empty()) {
        return cached_technique_index(primary_index);
    }
    auto& cache = resident_package_technique_index_cache();
    const std::string key = fs::absolute(job.package_root).string();
    auto found = cache.find(key);
    if (found != cache.end()) return found->second;
    TechniqueIndex combined;
    std::set<std::string> seen_pamts;
    merge_technique_index(combined, cached_technique_index(primary_index));
    seen_pamts.insert(fs::absolute(primary_index.pamt_path).string());
    for (const fs::path& pamt_path : package_root_pamt_paths(job.package_root)) {
        const std::string pamt_key = fs::absolute(pamt_path).string();
        if (!seen_pamts.insert(pamt_key).second) continue;
        try {
            merge_technique_index(combined, cached_technique_index(cached_pamt_index(pamt_path, job.cache_root)));
        } catch (...) {
        }
    }
    return cache.emplace(key, std::move(combined)).first->second;
}

struct NativeMaterialGraph {
    int version = kNativeMaterialGraphVersion;
    std::string key;
    fs::path cache_path;
    bool persistent_cache_hit = false;
    int pamt_count = 0;
    size_t entry_count = 0;
    size_t material_sidecar_count = 0;
    size_t texture_candidate_count = 0;
    TechniqueIndex technique_index;
};

static void apply_material_graph_summary(NativeMaterialGraph& graph, const std::string& summary) {
    if (summary.empty()) return;
    graph.pamt_count = static_cast<int>(std::max<long long>(graph.pamt_count, find_int_value(summary, "pamt_count", graph.pamt_count)));
    graph.entry_count = static_cast<size_t>(std::max<long long>(static_cast<long long>(graph.entry_count), find_int_value(summary, "entry_count", static_cast<long long>(graph.entry_count))));
    graph.material_sidecar_count = static_cast<size_t>(std::max<long long>(static_cast<long long>(graph.material_sidecar_count), find_int_value(summary, "material_sidecar_count", static_cast<long long>(graph.material_sidecar_count))));
    graph.texture_candidate_count = static_cast<size_t>(std::max<long long>(static_cast<long long>(graph.texture_candidate_count), find_int_value(summary, "texture_candidate_count", static_cast<long long>(graph.texture_candidate_count))));
    const int cached_technique_files = static_cast<int>(std::max<long long>(graph.technique_index.files_scanned, find_int_value(summary, "technique_files", graph.technique_index.files_scanned)));
    const int cached_technique_count = static_cast<int>(std::max<long long>(static_cast<long long>(graph.technique_index.technique_names.size()), find_int_value(summary, "techniques", static_cast<long long>(graph.technique_index.technique_names.size()))));
    const int cached_texture_params = static_cast<int>(std::max<long long>(graph.technique_index.texture_parameters, find_int_value(summary, "texture_parameters", graph.technique_index.texture_parameters)));
    graph.technique_index.files_scanned = cached_technique_files;
    graph.technique_index.texture_parameters = cached_texture_params;
    while (static_cast<int>(graph.technique_index.technique_names.size()) < cached_technique_count) {
        graph.technique_index.technique_names.insert("#cached_" + std::to_string(graph.technique_index.technique_names.size()));
    }
}

static size_t count_dds_basenames(const PamtIndex& index) {
    size_t count = 0;
    for (const auto& [basename, _refs] : index.by_basename) {
        if (lower_copy(basename).ends_with(".dds")) ++count;
    }
    return count;
}

static std::map<std::string, NativeMaterialGraph>& resident_native_material_graph_cache() {
    static std::map<std::string, NativeMaterialGraph> cache;
    return cache;
}

static const NativeMaterialGraph& cached_native_material_graph(
    const EntryJob& job,
    const PamtIndex& primary_index
) {
    auto& cache = resident_native_material_graph_cache();
    const std::string root_key = job.package_root.empty()
        ? fs::absolute(primary_index.pamt_path).string()
        : fs::absolute(job.package_root).string();
    const std::string key = root_key + "|material_graph_v" + std::to_string(kNativeMaterialGraphVersion);
    auto found = cache.find(key);
    if (found != cache.end()) return found->second;

    NativeMaterialGraph graph;
    graph.key = hex64(fnv1a64(key));
    graph.cache_path = job.cache_root / "native_material_graph" / (graph.key + ".json");
    graph.persistent_cache_hit = fs::is_regular_file(graph.cache_path);
    graph.technique_index = cached_technique_index(primary_index);
    graph.pamt_count = 1;
    graph.entry_count = primary_index.entry_count;
    graph.material_sidecar_count = primary_index.material_sidecars.size();
    graph.texture_candidate_count = count_dds_basenames(primary_index);
    if (graph.persistent_cache_hit) {
        try {
            apply_material_graph_summary(graph, read_text(graph.cache_path));
        } catch (...) {
        }
        return cache.emplace(key, std::move(graph)).first->second;
    }

    const bool build_archive_wide_summary = std::getenv("CDMW_PREVIEW_CORE_ARCHIVE_WIDE_GRAPH") != nullptr;
    if (build_archive_wide_summary && !job.package_root.empty()) {
        std::set<std::string> seen_pamts;
        seen_pamts.insert(fs::absolute(primary_index.pamt_path).string());
        for (const fs::path& pamt_path : package_root_pamt_paths(job.package_root)) {
            const std::string pamt_key = fs::absolute(pamt_path).string();
            if (!seen_pamts.insert(pamt_key).second) continue;
            try {
                const PamtIndex& index = cached_pamt_index(pamt_path, job.cache_root);
                ++graph.pamt_count;
                graph.entry_count += index.entry_count;
                graph.material_sidecar_count += index.material_sidecars.size();
                graph.texture_candidate_count += count_dds_basenames(index);
                merge_technique_index(graph.technique_index, cached_technique_index(index));
            } catch (...) {
            }
        }
    }
    if (!graph.persistent_cache_hit) {
        std::ostringstream summary;
        summary << "{"
            << "\"version\":" << graph.version << ","
            << "\"key\":\"" << json_escape(graph.key) << "\","
            << "\"root\":\"" << json_escape(root_key) << "\","
            << "\"pamt_count\":" << graph.pamt_count << ","
            << "\"entry_count\":" << graph.entry_count << ","
            << "\"material_sidecar_count\":" << graph.material_sidecar_count << ","
            << "\"texture_candidate_count\":" << graph.texture_candidate_count << ","
            << "\"technique_files\":" << graph.technique_index.files_scanned << ","
            << "\"techniques\":" << graph.technique_index.technique_names.size() << ","
            << "\"texture_parameters\":" << graph.technique_index.texture_parameters
            << "}";
        try {
            write_text(graph.cache_path, summary.str());
        } catch (...) {
        }
    }
    return cache.emplace(key, std::move(graph)).first->second;
}

static size_t resident_material_graph_metadata_count() {
    return resident_technique_index_cache().size()
        + resident_package_technique_index_cache().size()
        + resident_native_material_graph_cache().size();
}

static void release_resident_material_graph_metadata() {
    std::map<std::string, TechniqueIndex> technique_indexes;
    std::map<std::string, TechniqueIndex> package_technique_indexes;
    std::map<std::string, NativeMaterialGraph> material_graphs;
    resident_technique_index_cache().swap(technique_indexes);
    resident_package_technique_index_cache().swap(package_technique_indexes);
    resident_native_material_graph_cache().swap(material_graphs);
}

// Building a technique index decodes every .technique/.material entry of a
// .pamt from its archives, which can cost a second per job. The maps are keyed
// per .pamt or package root and hold only parameter metadata, so keeping them
// resident between jobs is cheap; the bounds below are safety valves for
// sessions that hop across many package roots.
static constexpr size_t kResidentTechniqueIndexMaxCount = 16;
static constexpr size_t kResidentPackageTechniqueIndexMaxCount = 4;
static constexpr size_t kResidentMaterialGraphMaxCount = 16;

static void trim_resident_material_graph_metadata() {
    if (resident_technique_index_cache().size() > kResidentTechniqueIndexMaxCount) {
        std::map<std::string, TechniqueIndex> technique_indexes;
        resident_technique_index_cache().swap(technique_indexes);
    }
    if (resident_package_technique_index_cache().size() > kResidentPackageTechniqueIndexMaxCount) {
        std::map<std::string, TechniqueIndex> package_technique_indexes;
        resident_package_technique_index_cache().swap(package_technique_indexes);
    }
    if (resident_native_material_graph_cache().size() > kResidentMaterialGraphMaxCount) {
        std::map<std::string, NativeMaterialGraph> material_graphs;
        resident_native_material_graph_cache().swap(material_graphs);
    }
}

static const TechniqueParameterInfo* technique_parameter_for_name(
    const TechniqueIndex& index,
    const std::string& parameter_name
) {
    if (parameter_name.empty()) return nullptr;
    auto found = index.parameters_by_name.find(lower_copy(parameter_name));
    if (found == index.parameters_by_name.end()) return nullptr;
    return &found->second;
}

static std::string srgb_mode_for_role(
    const std::string& role,
    const TechniqueParameterInfo* technique_parameter
) {
    if (technique_parameter != nullptr && !technique_parameter->srgb.empty()) {
        const std::string srgb = lower_copy(technique_parameter->srgb);
        if (srgb == "true" || srgb == "1" || srgb == "yes") return "srgb";
        if (srgb == "false" || srgb == "0" || srgb == "no") return "linear";
    }
    return (role == "base" || role == "emissive") ? "srgb" : "linear";
}

static void add_sidecar_texture_ref(
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen,
    std::string path,
    std::string parameter,
    const std::string& material_name,
    const std::string& shader_family,
    int material_wrapper_index,
    const std::vector<MaterialParameterRecord>& material_parameters = {}
) {
    std::replace(path.begin(), path.end(), '\\', '/');
    if (lower_copy(path).find(".dds") == std::string::npos) return;
    if (parameter.empty()) parameter = basename_from_path(path);
    // A single DDS can appear under multiple same-slot layer parameters and again
    // through synthetic sibling expansion. Extracting it once per material keeps
    // native packages smaller without losing the slot ownership evidence.
    const std::string key = lower_copy(path + "|" + material_name + "|" + shader_family);
    if (seen.insert(key).second) {
        refs.push_back(SidecarTextureRef{path, parameter, material_name, shader_family, material_wrapper_index, material_parameters});
    }
}

static std::string texture_path_without_known_suffix(const std::string& raw_path) {
    std::string path = raw_path;
    const std::string lower = lower_copy(path);
    for (const std::string& suffix : {"_sp.dds", "_ma.dds", "_mg.dds", "_m.dds", "_n.dds", "_disp.dds"}) {
        if (lower.ends_with(suffix) && path.size() > suffix.size()) {
            path.resize(path.size() - suffix.size());
            path += ".dds";
            return path;
        }
    }
    return "";
}

static bool texture_path_has_visual_support_suffix(const std::string& raw_path) {
    const std::string lower = lower_copy(raw_path);
    return lower.ends_with("_sp.dds") || lower.ends_with("_n.dds");
}

static bool shader_rule_allows_visible_layer_family(const std::string& shader_family) {
    const std::string rule = shader_rule_for_family(shader_family);
    return rule == "standard" || rule == "standard_v2" || rule == "cloth" || rule == "cloth_v2" || rule == "static_standard" || rule == "static_multitextured" || rule == "generic";
}

static void add_support_base_sibling_ref(
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen,
    const std::string& path,
    const std::string& material_name,
    const std::string& shader_family,
    int material_wrapper_index,
    const std::vector<MaterialParameterRecord>& material_parameters
) {
    if (!texture_path_has_visual_support_suffix(path)) return;
    const std::string diffuse_path = texture_path_without_known_suffix(path);
    if (diffuse_path.empty() || lower_copy(diffuse_path) == lower_copy(path)) return;
    add_sidecar_texture_ref(refs, seen, diffuse_path, "_baseColorTexture", material_name, shader_family, material_wrapper_index, material_parameters);
}

static void add_layer_family_sibling_refs(
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen,
    const std::string& path,
    const std::string& parameter,
    const std::string& material_name,
    const std::string& shader_family,
    int material_wrapper_index,
    const std::vector<MaterialParameterRecord>& material_parameters
) {
    if (!shader_rule_allows_visible_layer_family(shader_family)) return;
    const std::string key = normalized_key(parameter);
    const bool layer_parameter =
        key.find("detail") != std::string::npos
        || key.find("grime") != std::string::npos
        || key.find("dye") != std::string::npos;
    if (!layer_parameter) return;
    const std::string diffuse_path = texture_path_without_known_suffix(path);
    if (diffuse_path.empty() || lower_copy(diffuse_path) == lower_copy(path)) return;
    std::string channel;
    if (!parameter.empty()) {
        const char last = static_cast<char>(std::tolower(static_cast<unsigned char>(parameter.back())));
        if (last == 'r' || last == 'g' || last == 'b' || last == 'a') channel.push_back(last);
    }
    const std::string suffix = channel.empty() ? "" : std::string(1, static_cast<char>(std::toupper(static_cast<unsigned char>(channel.front()))));
    const std::string diffuse_parameter = key.find("grime") != std::string::npos ? ("_grimeDiffuseTexture" + suffix) : ("_detailDiffuseMask" + suffix);
    const std::string normal_parameter = key.find("grime") != std::string::npos ? ("_grimeNormalTexture" + suffix) : ("_detailNormalMask" + suffix);
    const std::string material_parameter = key.find("grime") != std::string::npos ? ("_grimeMaterialTexture" + suffix) : ("_detailMaterialMask" + suffix);
    const std::string height_parameter = "_detailHeightMask" + suffix;
    const std::string stem = diffuse_path.substr(0, diffuse_path.size() - 4);
    add_sidecar_texture_ref(refs, seen, diffuse_path, diffuse_parameter, material_name, shader_family, material_wrapper_index, material_parameters);
    add_sidecar_texture_ref(refs, seen, stem + "_n.dds", normal_parameter, material_name, shader_family, material_wrapper_index, material_parameters);
    add_sidecar_texture_ref(refs, seen, stem + "_sp.dds", material_parameter, material_name, shader_family, material_wrapper_index, material_parameters);
    add_sidecar_texture_ref(refs, seen, stem + "_disp.dds", height_parameter, material_name, shader_family, material_wrapper_index, material_parameters);
}

static void extract_texture_refs_from_scope(
    const std::string& scope_text,
    const std::string& material_name,
    const std::string& shader_family,
    int material_wrapper_index,
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen
) {
    const std::vector<MaterialParameterRecord> material_parameters = extract_material_parameters(scope_text);
    for (const std::string& tag : collect_xml_tag_blocks(scope_text, "MaterialParameterTexture")) {
        const auto attrs = xml_attribute_map(tag);
        const std::string parameter = xml_attr_value_from_map(attrs, {"_name", "StringItemID", "Name"});
        std::string path = xml_attr_value_from_map(attrs, {"Value", "_path"});
        if (path.empty()) {
            for (const std::string& resource_tag : collect_xml_tag_blocks(tag, "ResourceReferencePath_ITexture")) {
                const auto resource_attrs = xml_attribute_map(resource_tag);
                path = xml_attr_value_from_map(resource_attrs, {"_path", "Value"});
                if (!path.empty()) break;
            }
        }
        add_sidecar_texture_ref(refs, seen, path, parameter, material_name, shader_family, material_wrapper_index, material_parameters);
        add_support_base_sibling_ref(refs, seen, path, material_name, shader_family, material_wrapper_index, material_parameters);
        add_layer_family_sibling_refs(refs, seen, path, parameter, material_name, shader_family, material_wrapper_index, material_parameters);
    }
}

static int score_material_wrapper_block_for_preview(const std::string& block, const std::string& material_name) {
    const std::string shader_family = extract_shader_family_hint(block);
    const std::string shader_rule = shader_rule_for_family(shader_family);
    const std::string block_lower = lower_copy(block);
    const std::string material_key = normalized_key(material_name);
    int score = 0;
    if (block_lower.find("_basecolortexture") != std::string::npos) score += 180;
    if (block_lower.find("_normaltexture") != std::string::npos) score += 35;
    if (block_lower.find("_materialtexture") != std::string::npos) score += 35;
    if (block_lower.find("_heighttexture") != std::string::npos) score += 18;
    if (block_lower.find("_overlaycolortexture") != std::string::npos && block_lower.find("_basecolortexture") == std::string::npos) score -= 80;
    if (shader_rule == "standard_v2" || shader_rule == "cloth_v2") score += 28;
    else if (shader_rule == "standard" || shader_rule == "cloth" || shader_rule == "skin") score += 22;
    else if (shader_rule == "hair") score -= 35;
    else if (shader_rule == "generic") score -= 55;
    for (const std::string& texture_tag : collect_xml_tag_blocks(block, "MaterialParameterTexture")) {
        const auto attrs = xml_attribute_map(texture_tag);
        std::string path = xml_attr_value_from_map(attrs, {"Value", "_path"});
        if (path.empty()) {
            for (const std::string& resource_tag : collect_xml_tag_blocks(texture_tag, "ResourceReferencePath_ITexture")) {
                const auto resource_attrs = xml_attribute_map(resource_tag);
                path = xml_attr_value_from_map(resource_attrs, {"_path", "Value"});
                if (!path.empty()) break;
            }
        }
        const std::string stem_key = normalized_key(stem_from_path(path));
        if (!material_key.empty() && !stem_key.empty() && (stem_key == material_key || stem_key.find(material_key) != std::string::npos || material_key.find(stem_key) != std::string::npos)) {
            score += 95;
        }
    }
    return score;
}

static std::vector<SidecarTextureRef> extract_sidecar_texture_refs(const std::string& text) {
    std::vector<SidecarTextureRef> refs;
    std::set<std::string> seen;

    int wrapper_index = 0;
    for (const std::string& block : collect_xml_tag_blocks(text, "SkinnedMeshMaterialWrapper")) {
        std::string material_name = xml_attr_value(block, {"_subMeshName", "PrimitiveName", "Name"});
        std::replace(material_name.begin(), material_name.end(), '\\', '/');
        const std::string shader_family = extract_shader_family_hint(block);
        extract_texture_refs_from_scope(block, material_name, shader_family, wrapper_index++, refs, seen);
    }

    if (refs.empty()) {
        wrapper_index = 0;
        for (const std::string& block : collect_xml_tag_blocks(text, "Material")) {
            std::string material_name = xml_attr_value(block, {"PrimitiveName", "_subMeshName", "Name"});
            std::replace(material_name.begin(), material_name.end(), '\\', '/');
            std::string shader_family = extract_shader_family_hint(block);
            if (shader_family.empty()) shader_family = xml_attr_value(block, {"MaterialName", "_materialName"});
            extract_texture_refs_from_scope(block, material_name, shader_family, wrapper_index++, refs, seen);
        }
    }

    if (refs.empty()) {
        extract_texture_refs_from_scope(text, "", "", -1, refs, seen);
    }

    if (!refs.empty()) return refs;
    for (const std::string& token : extract_dds_tokens(text)) {
        add_sidecar_texture_ref(refs, seen, token, basename_from_path(token), "", "", -1);
    }
    return refs;
}
