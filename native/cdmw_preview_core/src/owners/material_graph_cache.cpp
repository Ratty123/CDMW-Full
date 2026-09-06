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

static NativeMaterialGraph build_bounded_native_material_graph(
    const PamtIndex& index
) {
    NativeMaterialGraph graph;
    graph.key = "bounded_snapshot";
    graph.entry_count = index.entry_count;
    graph.material_sidecar_count = index.material_sidecars.size();
    graph.texture_candidate_count = count_dds_basenames(index);
    graph.technique_index = build_technique_index_for_pamt(index);
    std::set<std::string> pamt_paths;
    for (const auto& [basename, refs] : index.by_basename) {
        (void)basename;
        for (const ArchiveEntryRef& ref : refs) {
            pamt_paths.insert(lower_copy(ref.pamt_path.string()));
        }
    }
    graph.pamt_count = static_cast<int>(std::max<size_t>(1, pamt_paths.size()));
    return graph;
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
    const std::string& parameter_name,
    const std::string& material_family
) {
    if (parameter_name.empty() || material_family.empty()) return nullptr;
    const std::string family_key = exact_material_family_key(material_family);
    if (family_key.empty() || index.ambiguous_family_keys.contains(family_key)) return nullptr;
    auto family = index.resolved_parameters_by_family.find(family_key);
    if (family == index.resolved_parameters_by_family.end()) return nullptr;
    auto found = family->second.find(exact_casefolded_name(parameter_name));
    if (found == family->second.end() || found->second.ambiguous) return nullptr;
    return &found->second;
}

static bool parameter_is_emissive_intensity_texture(const std::string& parameter_name) {
    const std::string key = normalized_key(parameter_name);
    const bool emissive_family = key.find("emissive") != std::string::npos
        || key.find("glow") != std::string::npos
        || key.find("illum") != std::string::npos;
    const bool scalar_mask = key.find("intensity") != std::string::npos
        || key.find("mask") != std::string::npos;
    return emissive_family && scalar_mask && key.find("texture") != std::string::npos;
}

static std::string srgb_mode_for_role(
    const std::string& role,
    const std::string& parameter_name,
    const TechniqueParameterInfo* technique_parameter
) {
    // `_emissiveIntensityTexture` and equivalent masks are scalar energy fields,
    // not emissive colours.  Shipped equipment uses BC4 for this slot; asking for
    // an sRGB view is both semantically wrong and unsupported for single-channel
    // BC4/R8 data.  This source contract outranks a broad technique sRGB flag.
    const std::string& declared_name = technique_parameter != nullptr
        && !technique_parameter->name.empty() ? technique_parameter->name : parameter_name;
    if (role == "emissive" && parameter_is_emissive_intensity_texture(declared_name)) {
        return "linear";
    }
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
    const std::string& owner_wrapper_item_id,
    int material_wrapper_index,
    const std::vector<MaterialParameterRecord>& material_parameters = {}
) {
    std::replace(path.begin(), path.end(), '\\', '/');
    if (lower_copy(path).find(".dds") == std::string::npos) return;
    if (parameter.empty()) parameter = basename_from_path(path);
    // Logical graph edges are distinct even when their bytes are not. A single
    // DDS can intentionally drive grime and detail parameters in one wrapper;
    // collapsing by path loses authored layer semantics before Rust sees them.
    const std::string key = lower_copy(
        owner_wrapper_item_id + "|" + parameter + "|" + path);
    if (seen.insert(key).second) {
        refs.push_back(SidecarTextureRef{
            path,
            parameter,
            material_name,
            shader_family,
            owner_wrapper_item_id,
            material_wrapper_index,
            material_parameters,
        });
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
    const std::string& parameter,
    const std::string& material_name,
    const std::string& shader_family,
    const std::string& owner_wrapper_item_id,
    int material_wrapper_index,
    const std::vector<MaterialParameterRecord>& material_parameters
) {
    const std::string parameter_key = normalized_key(parameter);
    if (parameter_key.find("detail") != std::string::npos
        || parameter_key.find("grime") != std::string::npos
        || parameter_key.find("dye") != std::string::npos) {
        // Layer-family support maps are completed below with their authored
        // detail/grime parameter. Promoting their diffuse sibling to a generic
        // base edge makes that layer eligible to overpaint the whole material.
        return;
    }
    if (!texture_path_has_visual_support_suffix(path)) return;
    const std::string diffuse_path = texture_path_without_known_suffix(path);
    if (diffuse_path.empty() || lower_copy(diffuse_path) == lower_copy(path)) return;
    add_sidecar_texture_ref(refs, seen, diffuse_path, "_baseColorTexture", material_name,
        shader_family, owner_wrapper_item_id, material_wrapper_index, material_parameters);
}

static void add_layer_family_sibling_refs(
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen,
    const std::string& path,
    const std::string& parameter,
    const std::string& material_name,
    const std::string& shader_family,
    const std::string& owner_wrapper_item_id,
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
    add_sidecar_texture_ref(refs, seen, diffuse_path, diffuse_parameter, material_name,
        shader_family, owner_wrapper_item_id, material_wrapper_index, material_parameters);
    add_sidecar_texture_ref(refs, seen, stem + "_n.dds", normal_parameter, material_name,
        shader_family, owner_wrapper_item_id, material_wrapper_index, material_parameters);
    add_sidecar_texture_ref(refs, seen, stem + "_sp.dds", material_parameter, material_name,
        shader_family, owner_wrapper_item_id, material_wrapper_index, material_parameters);
    add_sidecar_texture_ref(refs, seen, stem + "_disp.dds", height_parameter, material_name,
        shader_family, owner_wrapper_item_id, material_wrapper_index, material_parameters);
}

static void extract_texture_refs_from_scope(
    const std::string& scope_text,
    const std::string& material_name,
    const std::string& shader_family,
    const std::string& owner_wrapper_item_id,
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
        add_sidecar_texture_ref(refs, seen, path, parameter, material_name, shader_family,
            owner_wrapper_item_id, material_wrapper_index, material_parameters);
        add_support_base_sibling_ref(refs, seen, path, parameter, material_name, shader_family,
            owner_wrapper_item_id, material_wrapper_index, material_parameters);
        add_layer_family_sibling_refs(refs, seen, path, parameter, material_name, shader_family,
            owner_wrapper_item_id, material_wrapper_index, material_parameters);
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

static int xml_model_property_index(const std::string& block) {
    const std::string value = xml_attr_value_from_map(
        xml_attribute_map(block),
        {"Index", "_index"});
    if (value.empty()) return -1;
    char* end = nullptr;
    const long parsed = std::strtol(value.c_str(), &end, 10);
    return end != value.c_str() && *end == '\0' && parsed >= 0 && parsed <= 255
        ? static_cast<int>(parsed)
        : -1;
}

static std::string material_sidecar_scope_for_model_property(
    const std::string& text,
    int model_property_index
) {
    std::string index_zero_scope;
    for (const std::string& block : collect_xml_tag_blocks(text, "ModelProperty")) {
        const int block_index = xml_model_property_index(block);
        if (block_index == model_property_index) return block;
        if (block_index == 0 && index_zero_scope.empty()) index_zero_scope = block;
    }
    return index_zero_scope.empty() ? text : index_zero_scope;
}

static void append_material_wrapper_declaration(
    std::vector<MaterialWrapperDeclaration>* declarations,
    const std::string& scope,
    const std::string& material_name,
    const std::string& shader_family,
    const std::string& owner_wrapper_item_id,
    int material_wrapper_index
) {
    if (declarations == nullptr) return;
    declarations->push_back(MaterialWrapperDeclaration{
        material_name,
        shader_family,
        owner_wrapper_item_id,
        material_wrapper_index,
        extract_material_parameters(scope),
    });
}

static std::vector<SidecarTextureRef> extract_sidecar_texture_refs(
    const std::string& text,
    int model_property_index = 0,
    std::vector<MaterialWrapperDeclaration>* declarations = nullptr
) {
    std::vector<SidecarTextureRef> refs;
    std::set<std::string> seen;
    const std::string scope = material_sidecar_scope_for_model_property(
        text,
        model_property_index);

    int wrapper_index = 0;
    for (const std::string& block : collect_xml_tag_blocks(scope, "SkinnedMeshMaterialWrapper")) {
        std::string material_name = xml_attr_value(block, {"_subMeshName", "PrimitiveName", "Name"});
        std::replace(material_name.begin(), material_name.end(), '\\', '/');
        const std::string shader_family = extract_shader_family_hint(block);
        const auto wrapper_attrs = xml_attribute_map(block);
        const std::string item_id = xml_attr_value_from_map(
            wrapper_attrs, {"ItemID", "StringItemID"});
        const std::string wrapper_identity = !item_id.empty()
            ? item_id
            : "model-property:" + std::to_string(model_property_index)
                + ":wrapper:" + std::to_string(wrapper_index);
        append_material_wrapper_declaration(
            declarations, block, material_name, shader_family,
            wrapper_identity, wrapper_index);
        extract_texture_refs_from_scope(block, material_name, shader_family, wrapper_identity,
            wrapper_index++, refs, seen);
    }

    if (refs.empty()) {
        wrapper_index = 0;
        for (const std::string& block : collect_xml_tag_blocks(scope, "Material")) {
            std::string material_name = xml_attr_value(block, {"PrimitiveName", "_subMeshName", "Name"});
            std::replace(material_name.begin(), material_name.end(), '\\', '/');
            std::string shader_family = extract_shader_family_hint(block);
            if (shader_family.empty()) shader_family = xml_attr_value(block, {"MaterialName", "_materialName"});
            const auto wrapper_attrs = xml_attribute_map(block);
            const std::string item_id = xml_attr_value_from_map(
                wrapper_attrs, {"ItemID", "StringItemID"});
            const std::string wrapper_identity = !item_id.empty()
                ? item_id
                : "model-property:" + std::to_string(model_property_index)
                    + ":material:" + std::to_string(wrapper_index);
            append_material_wrapper_declaration(
                declarations, block, material_name, shader_family,
                wrapper_identity, wrapper_index);
            extract_texture_refs_from_scope(block, material_name, shader_family, wrapper_identity,
                wrapper_index++, refs, seen);
        }
    }

    if (refs.empty()) {
        if (declarations == nullptr || declarations->empty()) {
            append_material_wrapper_declaration(
                declarations,
                scope,
                "",
                "",
                "model-property:" + std::to_string(model_property_index) + ":scope",
                -1);
        }
        extract_texture_refs_from_scope(scope, "", "",
            "model-property:" + std::to_string(model_property_index) + ":scope",
            -1, refs, seen);
    }

    if (!refs.empty()) return refs;
    for (const std::string& token : extract_dds_tokens(scope)) {
        add_sidecar_texture_ref(refs, seen, token, basename_from_path(token), "", "",
            "model-property:" + std::to_string(model_property_index) + ":token", -1);
    }
    return refs;
}
