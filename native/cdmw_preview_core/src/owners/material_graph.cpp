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
    std::string declaration_source_path;
    std::string default_source_path;
    std::string material_family;
    std::string parameter_group_name;
    std::string included_by_source_path;
    bool ambiguous = false;
    bool declared = false;
};

using TechniqueParameterMap = std::unordered_map<std::string, TechniqueParameterInfo>;

struct TechniqueIndex {
    // `parameters_by_name` is diagnostic inventory only. Source defaults are
    // never selected from it because the same parameter name can have
    // different meanings/defaults in unrelated shader families.
    TechniqueParameterMap parameters_by_name;
    std::unordered_map<std::string, TechniqueParameterMap> direct_parameters_by_family;
    std::unordered_map<std::string, TechniqueParameterMap> parameter_groups_by_name;
    std::unordered_map<std::string, TechniqueParameterMap> resolved_parameters_by_family;
    std::unordered_map<std::string, std::vector<std::string>> group_names_by_family;
    std::unordered_map<std::string, std::string> family_source_by_name;
    std::unordered_map<std::string, std::string> group_source_by_name;
    std::set<std::string> ambiguous_family_keys;
    std::set<std::string> ambiguous_group_keys;
    std::set<std::string> technique_names;
    int files_scanned = 0;
    int parameters = 0;
    int texture_parameters = 0;
};

static std::string exact_casefolded_name(std::string value) {
    size_t start = 0;
    while (start < value.size() && std::isspace(static_cast<unsigned char>(value[start]))) ++start;
    size_t end = value.size();
    while (end > start && std::isspace(static_cast<unsigned char>(value[end - 1]))) --end;
    return lower_copy(value.substr(start, end - start));
}

static std::string exact_material_family_key(const std::string& value) {
    std::string base = basename_from_path(value);
    if (base.empty()) base = value;
    const std::string lower = lower_copy(base);
    for (const std::string& suffix : {std::string(".material"), std::string(".technique")}) {
        if (lower.ends_with(suffix)) {
            base.resize(base.size() - suffix.size());
            break;
        }
    }
    return exact_casefolded_name(base);
}

static bool technique_parameter_text_conflicts(
    const std::string& left,
    const std::string& right,
    bool archive_path = false
) {
    if (left.empty() || right.empty()) return false;
    const std::string normalized_left = archive_path
        ? lower_copy(native_archive_path(left)) : exact_casefolded_name(left);
    const std::string normalized_right = archive_path
        ? lower_copy(native_archive_path(right)) : exact_casefolded_name(right);
    return normalized_left != normalized_right;
}

static void merge_technique_parameter_info(
    TechniqueParameterMap& destination,
    const TechniqueParameterInfo& info
) {
    const std::string key = exact_casefolded_name(info.name);
    if (key.empty()) return;
    auto found = destination.find(key);
    if (found == destination.end()) {
        destination.emplace(key, info);
        return;
    }
    TechniqueParameterInfo& current = found->second;
    current.ambiguous = current.ambiguous || info.ambiguous
        || technique_parameter_text_conflicts(current.type, info.type)
        || technique_parameter_text_conflicts(current.srgb, info.srgb)
        || technique_parameter_text_conflicts(
            current.default_value, info.default_value, true);
    if (current.type.empty()) current.type = info.type;
    if (current.srgb.empty()) current.srgb = info.srgb;
    if (current.default_value.empty()) {
        current.default_value = info.default_value;
        current.default_source_path = info.default_source_path;
    }
    if (current.declaration_source_path.empty()) {
        current.declaration_source_path = info.declaration_source_path;
    }
    if (current.material_family.empty()) current.material_family = info.material_family;
    if (current.parameter_group_name.empty()) {
        current.parameter_group_name = info.parameter_group_name;
    }
    if (current.included_by_source_path.empty()) {
        current.included_by_source_path = info.included_by_source_path;
    }
    current.declared = current.declared || info.declared;
}

static TechniqueParameterInfo technique_parameter_from_tag(
    const std::string& tag,
    const std::string& source_path = {}
) {
    const auto attrs = xml_attribute_map(tag);
    TechniqueParameterInfo info;
    info.name = xml_attr_value_from_map(attrs, {"Name", "_name"});
    if (info.name.empty()) return info;
    info.type = xml_attr_value_from_map(attrs, {"Type", "_type"});
    info.srgb = xml_attr_value_from_map(attrs, {"sRGB", "SRGB", "Srgb"});
    info.default_value = xml_attr_value_from_map(attrs, {"DefaultValue", "Value", "_defaultValue"});
    info.declaration_source_path = source_path;
    if (!info.default_value.empty()) info.default_source_path = source_path;
    info.declared = true;
    return info;
}

static void add_technique_parameter(
    TechniqueIndex& index,
    TechniqueParameterMap& destination,
    const std::string& tag,
    const std::string& source_path,
    const std::string& material_family = {},
    const std::string& parameter_group_name = {}
) {
    TechniqueParameterInfo info = technique_parameter_from_tag(tag, source_path);
    if (info.name.empty()) return;
    info.material_family = material_family;
    info.parameter_group_name = parameter_group_name;
    ++index.parameters;
    const std::string key = exact_casefolded_name(info.name);
    const std::string type_lower = lower_copy(info.type);
    if (type_lower.find("texture") != std::string::npos || key.find("texture") != std::string::npos) {
        ++index.texture_parameters;
    }
    merge_technique_parameter_info(destination, info);
    merge_technique_parameter_info(index.parameters_by_name, info);
}

static void record_exact_definition_source(
    std::unordered_map<std::string, std::string>& sources,
    std::set<std::string>& ambiguous_keys,
    const std::string& key,
    const std::string& source_path
) {
    if (key.empty()) return;
    auto found = sources.find(key);
    if (found == sources.end()) {
        sources.emplace(key, source_path);
    } else if (lower_copy(native_archive_path(found->second))
               != lower_copy(native_archive_path(source_path))) {
        ambiguous_keys.insert(key);
    }
}

static void rebuild_resolved_technique_parameters(TechniqueIndex& index) {
    index.resolved_parameters_by_family.clear();
    for (const auto& [family_key, family_source] : index.family_source_by_name) {
        if (index.ambiguous_family_keys.contains(family_key)) continue;
        TechniqueParameterMap resolved;
        auto direct = index.direct_parameters_by_family.find(family_key);
        if (direct != index.direct_parameters_by_family.end()) resolved = direct->second;
        auto groups = index.group_names_by_family.find(family_key);
        if (groups != index.group_names_by_family.end()) {
            for (const std::string& group_key : groups->second) {
                if (index.ambiguous_group_keys.contains(group_key)) continue;
                auto group = index.parameter_groups_by_name.find(group_key);
                if (group == index.parameter_groups_by_name.end()) continue;
                for (const auto& [parameter_key, group_info] : group->second) {
                    TechniqueParameterInfo included = group_info;
                    included.material_family = family_key;
                    included.parameter_group_name = group_key;
                    included.included_by_source_path = family_source;
                    auto existing = resolved.find(parameter_key);
                    if (existing == resolved.end()) {
                        resolved.emplace(parameter_key, std::move(included));
                    } else if (!existing->second.parameter_group_name.empty()) {
                        // Two included groups may declare the same parameter.
                        // Only congruent declarations are safe without knowing
                        // a proprietary engine precedence rule.
                        merge_technique_parameter_info(resolved, included);
                    }
                    // A direct declaration in the exact .material wins over an
                    // included group by source contract.
                }
            }
        }
        index.resolved_parameters_by_family.emplace(family_key, std::move(resolved));
    }
}

static TechniqueIndex build_technique_index_for_pamt(const PamtIndex& pamt_index) {
    TechniqueIndex index;
    for (const ArchiveEntryRef& ref : pamt_index.material_sidecars) {
        if (ref.extension != ".technique" && ref.extension != ".material"
            && ref.extension != ".xml") continue;
        const std::string path_lower = lower_copy(native_archive_path(ref.path));
        if (ref.extension == ".xml" && !path_lower.starts_with("material/")
            && path_lower.find("/material/") == std::string::npos) continue;
        std::vector<char> bytes;
        try {
            bytes = read_archive_ref_decoded_bytes(ref);
        } catch (...) {
            continue;
        }
        ++index.files_scanned;
        const std::string text(bytes.begin(), bytes.end());
        if (ref.extension == ".xml") {
            for (const std::string& block : collect_xml_tag_blocks(text, "ParameterGroup")) {
                if (lower_copy(block).find("</parametergroup>") == std::string::npos) continue;
                const std::string group_name = xml_attr_value_from_map(
                    xml_attribute_map(block), {"Name"});
                const std::string group_key = exact_casefolded_name(group_name);
                if (group_key.empty()) continue;
                record_exact_definition_source(
                    index.group_source_by_name,
                    index.ambiguous_group_keys,
                    group_key,
                    ref.path);
                TechniqueParameterMap& parameters = index.parameter_groups_by_name[group_key];
                for (const std::string& tag : collect_xml_tag_blocks(block, "Parameter")) {
                    add_technique_parameter(
                        index, parameters, tag, ref.path, {}, group_name);
                }
            }
            continue;
        }

        const std::string family_key = exact_material_family_key(ref.path);
        if (family_key.empty()) continue;
        record_exact_definition_source(
            index.family_source_by_name,
            index.ambiguous_family_keys,
            family_key,
            ref.path);
        for (const std::string& tag : collect_xml_tag_blocks(text, "Technique")) {
            const std::string name = xml_attr_value_from_map(xml_attribute_map(tag), {"Name"});
            if (!name.empty()) index.technique_names.insert(name);
        }
        auto& included_groups = index.group_names_by_family[family_key];
        for (const std::string& tag : collect_xml_tag_blocks(text, "ParameterGroup")) {
            const std::string group_key = exact_casefolded_name(
                xml_attr_value_from_map(xml_attribute_map(tag), {"Name"}));
            if (!group_key.empty()
                && std::find(included_groups.begin(), included_groups.end(), group_key)
                    == included_groups.end()) {
                included_groups.push_back(group_key);
            }
        }
        TechniqueParameterMap& direct_parameters = index.direct_parameters_by_family[family_key];
        for (const std::string& tag : collect_xml_tag_blocks(text, "Parameter")) {
            add_technique_parameter(
                index, direct_parameters, tag, ref.path, family_key, {});
        }
    }
    rebuild_resolved_technique_parameters(index);
    return index;
}

static void merge_technique_index(TechniqueIndex& destination, const TechniqueIndex& source) {
    destination.files_scanned += source.files_scanned;
    destination.parameters += source.parameters;
    destination.texture_parameters += source.texture_parameters;
    destination.technique_names.insert(source.technique_names.begin(), source.technique_names.end());
    for (const auto& [key, value] : source.parameters_by_name) {
        (void)key;
        merge_technique_parameter_info(destination.parameters_by_name, value);
    }
    for (const auto& [family_key, parameters] : source.direct_parameters_by_family) {
        TechniqueParameterMap& destination_parameters =
            destination.direct_parameters_by_family[family_key];
        for (const auto& [key, value] : parameters) {
            (void)key;
            merge_technique_parameter_info(destination_parameters, value);
        }
    }
    for (const auto& [group_key, parameters] : source.parameter_groups_by_name) {
        TechniqueParameterMap& destination_parameters =
            destination.parameter_groups_by_name[group_key];
        for (const auto& [key, value] : parameters) {
            (void)key;
            merge_technique_parameter_info(destination_parameters, value);
        }
    }
    for (const auto& [family_key, groups] : source.group_names_by_family) {
        auto& destination_groups = destination.group_names_by_family[family_key];
        for (const std::string& group_key : groups) {
            if (std::find(destination_groups.begin(), destination_groups.end(), group_key)
                == destination_groups.end()) destination_groups.push_back(group_key);
        }
    }
    for (const auto& [key, path] : source.family_source_by_name) {
        record_exact_definition_source(
            destination.family_source_by_name,
            destination.ambiguous_family_keys,
            key,
            path);
    }
    for (const auto& [key, path] : source.group_source_by_name) {
        record_exact_definition_source(
            destination.group_source_by_name,
            destination.ambiguous_group_keys,
            key,
            path);
    }
    destination.ambiguous_family_keys.insert(
        source.ambiguous_family_keys.begin(), source.ambiguous_family_keys.end());
    destination.ambiguous_group_keys.insert(
        source.ambiguous_group_keys.begin(), source.ambiguous_group_keys.end());
    rebuild_resolved_technique_parameters(destination);
}
