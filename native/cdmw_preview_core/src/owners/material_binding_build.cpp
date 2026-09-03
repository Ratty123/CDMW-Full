struct MaterialBindingBuildState {
    const EntryJob& job;
    const PamtIndex& index;
    const std::vector<NativeSubmesh>& meshes;
    NativePackage& package;
    const TechniqueIndex& technique_index;
    std::vector<TextureBinding> bindings;
    std::vector<std::string> notes;
    std::set<std::string> seen;
    std::set<std::string> conservation_seen;
    std::unordered_map<std::string, size_t> conservation_row_by_key;
    std::set<std::string> sidecar_kinds;
    std::set<std::string> shader_rules;
};

struct MaterialComponentScope {
    std::string id;
    int model_property_index = 0;
    bool ambiguous = false;
};

static std::string material_component_directory_for_identity(const std::string& path) {
    std::string directory = lower_copy(native_archive_path(dirname_from_path(path)));
    const std::string marker = "/modelproperty/";
    const size_t marker_index = directory.find(marker);
    if (marker_index != std::string::npos) {
        directory.replace(marker_index, marker.size(), "/model/");
    }
    return directory;
}

static MaterialComponentScope material_component_scope_for_sidecar(
    const ArchiveEntryRef& sidecar,
    const std::vector<NativeSubmesh>& meshes
) {
    const std::string sidecar_stem = exact_casefolded_name(stem_from_path(sidecar.path));
    const std::string sidecar_directory = material_component_directory_for_identity(sidecar.path);
    std::map<std::string, int> exact_models;
    bool conflicting_model_property_index = false;
    for (const NativeSubmesh& mesh : meshes) {
        if (mesh.source_model_path.empty()
            || exact_casefolded_name(stem_from_path(mesh.source_model_path)) != sidecar_stem
            || material_component_directory_for_identity(mesh.source_model_path)
                != sidecar_directory) continue;
        const std::string model_path = lower_copy(native_archive_path(mesh.source_model_path));
        auto [found, inserted] = exact_models.emplace(model_path, mesh.model_property_index);
        if (!inserted && found->second != mesh.model_property_index) {
            conflicting_model_property_index = true;
        }
    }
    if (exact_models.size() == 1 && !conflicting_model_property_index) {
        const auto& [model_path, model_property_index] = *exact_models.begin();
        return MaterialComponentScope{
            model_path + "#model_property=" + std::to_string(model_property_index),
            model_property_index,
            false};
    }

    const std::string fallback_key = material_component_key_from_path(sidecar.path);
    int fallback_model_property_index = 0;
    for (const NativeSubmesh& mesh : meshes) {
        if (material_component_key_from_path(mesh.source_model_path) == fallback_key) {
            fallback_model_property_index = mesh.model_property_index;
            break;
        }
    }
    return MaterialComponentScope{
        "sidecar:" + lower_copy(native_archive_path(sidecar.path))
            + "#model_property=" + std::to_string(fallback_model_property_index),
        fallback_model_property_index,
        exact_models.size() > 1 || conflicting_model_property_index};
}

static bool sidecar_ref_has_exact_wrapper_identity(const SidecarTextureRef& ref) {
    return !ref.owner_wrapper_item_id.empty()
        && ref.material_wrapper_index >= 0
        && !ref.parameter_name.empty();
}

static int sidecar_scoped_mesh_count(
    const std::string& component_key,
    const std::vector<NativeSubmesh>& meshes
) {
    int count = 0;
    for (const NativeSubmesh& mesh : meshes) {
        const std::string mesh_key = material_component_key_from_path(mesh.source_model_path);
        if (component_key.empty() || mesh_key.empty() || component_key == mesh_key
            || material_keys_overlap(component_key, mesh_key)) ++count;
    }
    return count;
}

static bool sidecar_ref_matches_meshes(
    const SidecarTextureRef& ref,
    const std::string& component_key,
    bool wrapper_order_authoritative,
    int scoped_mesh_count,
    const std::vector<NativeSubmesh>& meshes,
    const std::string& model_family_key
) {
    const std::string material_key = normalized_material_key(ref.material_name);
    if (material_key.empty() || meshes.empty()) return true;
    const std::string texture_key = normalized_texture_family_key(ref.path);
    if (wrapper_order_authoritative && ref.material_wrapper_index >= 0
        && ref.material_wrapper_index < scoped_mesh_count) return true;
    for (const NativeSubmesh& mesh : meshes) {
        const std::string mesh_source_key = material_component_key_from_path(mesh.source_model_path);
        if (!component_key.empty() && !mesh_source_key.empty() && component_key != mesh_source_key
            && !material_keys_overlap(component_key, mesh_source_key)) continue;
        const std::string mesh_material_key = normalized_material_key(mesh.material);
        const std::string mesh_name_key = normalized_material_key(mesh.name);
        if (material_keys_match_for_identity(material_key, mesh_material_key)
            || material_keys_match_for_identity(material_key, mesh_name_key)
            || material_keys_match_for_identity(texture_key, mesh_material_key)
            || material_keys_match_for_identity(texture_key, mesh_name_key)) return true;
    }
    return model_family_fallback_allowed_for_sidecar_ref(material_key, texture_key, model_family_key);
}

static std::string material_conservation_parameter_key(
    const std::string& component_scope_id,
    const MaterialWrapperDeclaration& declaration,
    const MaterialParameterRecord& parameter
) {
    if (parameter.kind == "texture") {
        return lower_copy(
            component_scope_id + "|" + declaration.owner_wrapper_item_id + "|"
            + std::to_string(declaration.material_wrapper_index) + "|" + parameter.name + "|"
            + native_archive_path(parameter.texture_path));
    }
    return lower_copy(
        component_scope_id + "|" + declaration.owner_wrapper_item_id + "|"
        + std::to_string(declaration.material_wrapper_index) + "|" + parameter.kind + "|"
        + parameter.name + "|" + parameter.tag_name + "|" + parameter.string_item_id + "|"
        + parameter.item_id + "|" + std::to_string(parameter.index) + "|"
        + parameter.texture_path + "|" + parameter.value);
}

static bool material_declaration_matches_meshes(
    const MaterialWrapperDeclaration& declaration,
    const std::string& component_key,
    bool wrapper_order_authoritative,
    int scoped_mesh_count,
    const std::vector<NativeSubmesh>& meshes,
    const std::string& model_family_key
) {
    SidecarTextureRef scope_ref;
    scope_ref.material_name = declaration.material_name;
    scope_ref.owner_wrapper_item_id = declaration.owner_wrapper_item_id;
    scope_ref.material_wrapper_index = declaration.material_wrapper_index;
    for (const MaterialParameterRecord& parameter : declaration.material_parameters) {
        if (!parameter.texture_path.empty()) {
            scope_ref.path = parameter.texture_path;
            break;
        }
    }
    return sidecar_ref_matches_meshes(
        scope_ref,
        component_key,
        wrapper_order_authoritative,
        scoped_mesh_count,
        meshes,
        model_family_key);
}

static bool sidecar_ref_owner_declaration_matches_meshes(
    const ParsedMaterialSidecar& parsed,
    const SidecarTextureRef& ref,
    const std::string& component_key,
    bool wrapper_order_authoritative,
    int scoped_mesh_count,
    const std::vector<NativeSubmesh>& meshes,
    const std::string& model_family_key
) {
    return std::any_of(
        parsed.declarations.begin(),
        parsed.declarations.end(),
        [&](const MaterialWrapperDeclaration& declaration) {
            return lower_copy(declaration.owner_wrapper_item_id)
                    == lower_copy(ref.owner_wrapper_item_id)
                && declaration.material_wrapper_index == ref.material_wrapper_index
                && material_declaration_matches_meshes(
                    declaration,
                    component_key,
                    wrapper_order_authoritative,
                    scoped_mesh_count,
                    meshes,
                    model_family_key);
        });
}

static bool declaration_has_exact_logical_texture_edge(
    const ParsedMaterialSidecar& parsed,
    const MaterialWrapperDeclaration& declaration,
    const MaterialParameterRecord& parameter
) {
    if (parameter.texture_path.empty()) return true;
    const std::string declared_path = lower_copy(native_archive_path(parameter.texture_path));
    for (const SidecarTextureRef& ref : parsed.refs) {
        if (lower_copy(ref.owner_wrapper_item_id) == lower_copy(declaration.owner_wrapper_item_id)
            && ref.material_wrapper_index == declaration.material_wrapper_index
            && lower_copy(ref.parameter_name) == lower_copy(parameter.name)
            && lower_copy(native_archive_path(ref.path)) == declared_path) return true;
    }
    return false;
}

static void record_material_wrapper_declaration(
    MaterialBindingBuildState& state,
    const ArchiveEntryRef& sidecar,
    const ParsedMaterialSidecar& parsed,
    const MaterialWrapperDeclaration& declaration,
    bool wrapper_order_authoritative,
    int scoped_mesh_count,
    const std::string& component_key,
    const std::string& component_scope_id,
    const std::string& model_family_key
) {
    if (!material_declaration_matches_meshes(
            declaration,
            component_key,
            wrapper_order_authoritative,
            scoped_mesh_count,
            state.meshes,
            model_family_key)) return;
    const std::string shader_family = declaration.shader_family.empty()
        ? parsed.shader_family : declaration.shader_family;
    const std::string shader_rule = shader_rule_for_family(shader_family);
    for (const MaterialParameterRecord& parameter : declaration.material_parameters) {
        const std::string key = material_conservation_parameter_key(
            component_scope_id, declaration, parameter);
        if (!state.conservation_seen.insert(key).second) {
            auto existing = state.conservation_row_by_key.find(key);
            if (existing != state.conservation_row_by_key.end()) {
                NativeMaterialConservationRow& row =
                    state.package.material_conservation_rows[existing->second];
                if (std::find(
                        row.representation_sidecar_paths.begin(),
                        row.representation_sidecar_paths.end(),
                        sidecar.path) == row.representation_sidecar_paths.end()) {
                    row.representation_sidecar_paths.push_back(sidecar.path);
                }
            }
            continue;
        }
        NativeMaterialConservationRow row;
        row.sidecar_path = sidecar.path;
        row.representation_sidecar_paths.push_back(sidecar.path);
        row.component_scope_id = component_scope_id;
        row.material_name = declaration.material_name;
        row.shader_family = shader_family;
        row.owner_wrapper_item_id = declaration.owner_wrapper_item_id;
        row.material_wrapper_index = declaration.material_wrapper_index;
        row.owner_slot_index = wrapper_order_authoritative
            ? declaration.material_wrapper_index : -1;
        row.parameter = parameter;
        if (parameter.kind == "texture") {
            const TechniqueParameterInfo* technique_parameter = technique_parameter_for_name(
                state.technique_index, parameter.name, shader_family);
            const std::string basename = lower_copy(basename_from_path(parameter.texture_path));
            row.role = role_from_parameter_shader_and_name(
                parameter.name, shader_rule, basename, technique_parameter);
            row.layer_role = layer_role_from_parameter(parameter.name, row.role);
            row.layer_channel = layer_channel_from_parameter(parameter.name);
            row.logical_graph_edge = declaration_has_exact_logical_texture_edge(
                parsed, declaration, parameter);
            if (parameter.texture_path.empty()) {
                row.status = "transported_null_texture";
            } else if (!row.logical_graph_edge) {
                row.status = "missing_graph_edge";
                row.finding = "missing_graph_edge";
                state.package.material_conservation_ok = false;
                state.package.material_conservation_findings.push_back(
                    "missing_graph_edge:" + sidecar.path + ":"
                    + declaration.owner_wrapper_item_id + ":" + parameter.name);
            } else {
                row.status = "transported_texture_edge";
            }
        } else {
            row.logical_graph_edge = true;
            row.status = "transported_parameter";
        }
        state.conservation_row_by_key.emplace(
            key, state.package.material_conservation_rows.size());
        state.package.material_conservation_rows.push_back(std::move(row));
    }
}

static std::optional<ArchiveEntryRef> select_sidecar_texture_candidate(
    const std::vector<ArchiveEntryRef>& candidates,
    const ArchiveEntryRef& sidecar,
    const std::string& basename
) {
    const ArchiveEntryRef* selected = nullptr;
    int best_score = -100000;
    const std::string sidecar_dir = lower_copy(dirname_from_path(sidecar.path));
    for (const ArchiveEntryRef& candidate : candidates) {
        int score = 10;
        const std::string path = lower_copy(candidate.path);
        const std::string directory = lower_copy(dirname_from_path(candidate.path));
        if (lower_copy(candidate.basename) == basename) score += 30;
        if (!sidecar_dir.empty() && directory == sidecar_dir) score += 50;
        if (path.find("/texture/") != std::string::npos) score += 20;
        if (path.find("/modelproperty/") != std::string::npos) score += 5;
        if (candidate.pamt_path == sidecar.pamt_path) score += 8;
        if (score > best_score) {
            best_score = score;
            selected = &candidate;
        }
    }
    if (selected == nullptr && !candidates.empty()) selected = &candidates.front();
    return selected == nullptr ? std::nullopt : std::optional<ArchiveEntryRef>(*selected);
}

struct ResolvedSidecarTextureCandidate {
    ArchiveEntryRef entry;
    std::string resolution;
    std::string detail;
    bool declared_source_missing = false;
};

static const ArchiveEntryRef* exact_archive_path_candidate(
    const std::vector<ArchiveEntryRef>& candidates,
    const std::string& archive_path
) {
    const std::string wanted = lower_copy(native_archive_path(archive_path));
    for (const ArchiveEntryRef& candidate : candidates) {
        if (lower_copy(native_archive_path(candidate.path)) == wanted) return &candidate;
    }
    return nullptr;
}

static std::string corrected_missing_texture_separator_path(const std::string& archive_path) {
    const std::string normalized = native_archive_path(archive_path);
    const std::string lower = lower_copy(normalized);
    static const std::string prefix = "character/texture";
    if (!lower.starts_with(prefix) || lower.size() <= prefix.size()
        || lower[prefix.size()] == '/') return {};
    return normalized.substr(0, prefix.size()) + "/" + normalized.substr(prefix.size());
}

static std::optional<ResolvedSidecarTextureCandidate> resolve_sidecar_texture_candidate(
    const EntryJob& job,
    const PamtIndex& index,
    const ArchiveEntryRef& sidecar,
    const SidecarTextureRef& ref,
    const TechniqueParameterInfo* technique_parameter
) {
    const std::string declared_path = native_archive_path(ref.path);
    const std::string declared_basename = lower_copy(basename_from_path(declared_path));
    const std::vector<ArchiveEntryRef> declared_candidates =
        lookup_basename_candidates_across_package(job, index, declared_basename, 96);
    if (const ArchiveEntryRef* exact = exact_archive_path_candidate(
            declared_candidates, declared_path)) {
        return ResolvedSidecarTextureCandidate{
            *exact, "declared_exact", declared_path, false};
    }

    const std::string corrected_path = corrected_missing_texture_separator_path(declared_path);
    if (!corrected_path.empty()) {
        const std::vector<ArchiveEntryRef> corrected_candidates =
            lookup_basename_candidates_across_package(
                job, index, lower_copy(basename_from_path(corrected_path)), 96);
        if (const ArchiveEntryRef* corrected = exact_archive_path_candidate(
                corrected_candidates, corrected_path)) {
            return ResolvedSidecarTextureCandidate{
                *corrected,
                "corrected_missing_separator",
                "declared_missing:" + declared_path + ";resolved_exact:" + corrected->path,
                true};
        }
    }

    if (technique_parameter != nullptr) {
        const std::string default_path = native_archive_path(technique_parameter->default_value);
        if (lower_copy(extension_from_path(default_path)) == ".dds") {
            // Preview associations contain source-declared dependencies, while
            // this authoritative default is discovered later from the global
            // technique graph. A bounded miss therefore cannot prove that the
            // default DDS is absent from the package.
            const std::vector<ArchiveEntryRef> default_candidates =
                lookup_basename_candidates_across_package(
                    job,
                    index,
                    lower_copy(basename_from_path(default_path)),
                    96,
                    true);
            const ArchiveEntryRef* selected_default = exact_archive_path_candidate(
                default_candidates, default_path);
            if (selected_default == nullptr) {
                const std::string suffix = "/" + lower_copy(default_path);
                for (const ArchiveEntryRef& candidate : default_candidates) {
                    if (lower_copy(native_archive_path(candidate.path)).ends_with(suffix)) {
                        selected_default = &candidate;
                        break;
                    }
                }
            }
            if (selected_default != nullptr) {
                return ResolvedSidecarTextureCandidate{
                    *selected_default,
                    "technique_default_after_missing_declared_source",
                    "declared_missing:" + declared_path + ";technique_default:"
                        + default_path + ";technique_source:"
                        + technique_parameter->default_source_path
                        + ";material_family:" + technique_parameter->material_family
                        + ";parameter_group:" + technique_parameter->parameter_group_name
                        + ";included_by:" + technique_parameter->included_by_source_path
                        + ";resolved_exact:" + selected_default->path,
                    true};
            }
        }
    }
    return std::nullopt;
}

static TextureBinding make_sidecar_texture_binding(
    const SidecarTextureRef& ref,
    const ParsedMaterialSidecar& parsed,
    const ArchiveEntryRef& sidecar,
    const ArchiveEntryRef& selected,
    const std::string& extracted,
    const std::string& shader_family,
    const std::string& shader_rule,
    const TechniqueParameterInfo* technique_parameter,
    const std::string& source_resolution,
    const std::string& source_resolution_detail,
    bool declared_source_missing,
    bool wrapper_order_authoritative,
    const std::string& component_scope_id,
    const std::vector<NativeSubmesh>& meshes
) {
    const std::string basename = lower_copy(basename_from_path(ref.path));
    const std::string texture_key = normalized_texture_family_key(ref.path);
    TextureBinding binding;
    binding.role = role_from_parameter_shader_and_name(ref.parameter_name, shader_rule, basename, technique_parameter);
    binding.source_path = extracted;
    binding.archive_path = selected.path;
    binding.texture_name = selected.basename;
    const DdsHeaderInfo dds = inspect_dds_header_file(extracted);
    binding.dds_width = dds.width;
    binding.dds_height = dds.height;
    binding.dds_format = dds.format;
    binding.parameter_name = ref.parameter_name.empty() ? basename : ref.parameter_name;
    binding.declared_texture_path = native_archive_path(ref.path);
    binding.source_resolution = source_resolution;
    binding.source_resolution_detail = source_resolution_detail;
    binding.declared_source_missing = declared_source_missing;
    const std::string parameter_lower = lower_copy(binding.parameter_name);
    if (binding.role == "base" && !parameter_is_authoritative_visible_base(binding.parameter_name)
        && role_is_technical_for_base(texture_role_from_name(basename))) binding.role = texture_role_from_name(basename);
    binding.semantic_type = semantic_type_for_role(binding.role);
    binding.semantic_subtype = semantic_subtype_for_role(binding.role);
    binding.shader_family = shader_family;
    binding.shader_rule = shader_rule;
    binding.material_name = ref.material_name.empty() ? stem_from_path(sidecar.path) : ref.material_name;
    binding.owner_wrapper_item_id = ref.owner_wrapper_item_id;
    binding.material_wrapper_index = ref.material_wrapper_index;
    binding.material_wrapper_count = parsed.material_wrapper_count;
    binding.material_wrapper_order_authoritative = wrapper_order_authoritative;
    for (const NativeSubmesh& mesh : meshes) {
        if (material_keys_match_for_identity(texture_key, normalized_material_key(mesh.material))
            || material_keys_match_for_identity(texture_key, normalized_material_key(mesh.name))) {
            binding.material_name = stem_from_path(ref.path);
            break;
        }
    }
    binding.sidecar_path = sidecar.path;
    binding.representation_sidecar_paths.push_back(sidecar.path);
    binding.component_scope_id = component_scope_id;
    binding.sidecar_kind = sidecar.extension;
    if (const NativePbdSidecarHint* hint = best_native_pbd_hint_for_binding(
        parsed.pbd_hints, binding.material_name, ref.material_name, binding.parameter_name)) {
        binding.pbd_simulation_material_name = hint->simulation_material_name;
        binding.pbd_simulation_kind = hint->simulation_kind;
        binding.pbd_material_name = hint->material_name;
        binding.pbd_submesh_name = hint->submesh_name;
    }
    binding.linked_mesh_path = parsed.parameter_summary.linked_mesh_path;
    binding.packed_channels = packed_channels_for_role(
        binding.role, basename, parameter_lower, binding.shader_rule);
    binding.srgb_mode = srgb_mode_for_role(
        binding.role, binding.parameter_name, technique_parameter);
    binding.parameter_declared_by = technique_parameter == nullptr
        ? std::string()
        : (technique_parameter->parameter_group_name.empty()
            ? "exact_material"
            : "exact_material_parameter_group");
    binding.visible_class = visible_class_for_binding(binding.parameter_name, binding.archive_path, binding.role);
    binding.source_authority = "sidecar";
    binding.relation_confidence = (!ref.parameter_name.empty() && !ref.material_name.empty())
        ? "authoritative" : "derived_same_stem";
    binding.relation_reason = ref.parameter_name.empty()
        ? "Resolved by native texture basename/family lookup."
        : "Resolved from native material sidecar texture parameter.";
    binding.layer_role = layer_role_from_parameter(binding.parameter_name, binding.role);
    binding.layer_channel = layer_channel_from_parameter(binding.parameter_name);
    binding.layer_weight = layer_weight_from_parameters(ref.material_parameters, binding.layer_role, binding.layer_channel);
    if (parameter_is_skin_detail_support(binding.parameter_name)) {
        binding.detail_scale = skin_detail_scale_from_parameters(ref.material_parameters);
    }
    binding.tint_color = tint_for_layer(ref.material_parameters, binding.layer_role, binding.layer_channel);
    for (size_t channel = 0; channel < binding.color_blending_tints.size(); ++channel) {
        binding.color_blending_tints[channel] = tint_for_layer(
            ref.material_parameters,
            "color_seed",
            std::string(1, "rgb"[channel]));
    }
    binding.blend_flags = normalized_key(binding.parameter_name).find("colorblending") != std::string::npos
        ? "color_blending_mask" : "";
    binding.material_parameter_names = joined_parameter_names_with_color_seed_sources(
        ref.material_parameters);
    binding.material_parameters = filtered_preview_material_parameters(
        ref.material_parameters);
    // The diagnostic name list is normally capped, but 0350's authoritative
    // dye colors occur after that cap. Retain the three selected palette-source
    // names so layer compilation can distinguish an authored white channel
    // from the neutral default without copying the entire PAC parameter table.
    binding.alpha_test_enabled = material_parameters_enable_flag(
        ref.material_parameters, {"AlphaTest", "AlphaClip", "AlphaCutout", "Cutout", "_alphaTest"});
    binding.roughness_hint_present = material_parameter_has_scalar(
        ref.material_parameters, {"roughness", "scratchRoughness"});
    binding.metalness_hint_present = material_parameter_has_scalar(
        ref.material_parameters, {"metallic", "metalness", "scratchMetallic"});
    binding.specular_hint_present = material_parameter_has_scalar(
        ref.material_parameters, {"specular", "specularAmount"});
    binding.height_scale_hint_present = material_parameter_has_scalar(
        ref.material_parameters,
        {"screenSpaceDisplacementScale", "detailScreenSpaceDisplacementScale", "heightIntensity"});
    binding.roughness_hint = std::clamp(scalar_parameter_hint(
        ref.material_parameters, {"roughness", "scratchRoughness"}, 0.0f), 0.0f, 1.0f);
    binding.metalness_hint = std::clamp(scalar_parameter_hint(
        ref.material_parameters, {"metallic", "metalness", "scratchMetallic"}, 0.0f), 0.0f, 1.0f);
    binding.specular_hint = std::clamp(scalar_parameter_hint(
        ref.material_parameters, {"specular", "specularAmount"}, 0.0f), 0.0f, 1.0f);
    binding.height_scale_hint = std::clamp(scalar_parameter_hint(ref.material_parameters,
        {"screenSpaceDisplacementScale", "detailScreenSpaceDisplacementScale", "heightIntensity"}, 0.0f), 0.0f, 1.0f);
    binding.emissive_intensity_hint = std::clamp(scalar_parameter_hint(ref.material_parameters,
        {"emissiveIntensity", "emissiveAmount", "emissivePower", "glowIntensity"}, 0.0f), 0.0f, 32.0f);
    if (const MaterialParameterRecord* emissive_color = find_material_parameter(
        ref.material_parameters,
        {"emissiveColor", "emissiveTintColor", "glowColor", "emissiveLightColor"})) {
        if (emissive_color->kind == "color") {
            const auto value = color_parameter_value(emissive_color->value);
            binding.emissive_color = {
                std::clamp(value[0], 0.0f, 1.0f),
                std::clamp(value[1], 0.0f, 1.0f),
                std::clamp(value[2], 0.0f, 1.0f),
            };
        }
    }
    if (binding.role == "emissive" && binding.emissive_intensity_hint <= 0.001f) {
        binding.emissive_intensity_hint = direct_emissive_texture_or_shader_evidence(
            ref.path, basename, shader_family) ? 4.0f : 0.0f;
    }
    const bool approximate = binding.role == "base"
        && !parameter_is_authoritative_visible_base(binding.parameter_name)
        && role_is_technical_for_base(texture_role_from_name(basename));
    if (approximate) binding.material_output_quality = "approximate";
    else if (!ref.parameter_name.empty() && !ref.material_name.empty()) binding.material_output_quality = "exact";
    else binding.material_output_quality = "inferred";
    if (binding.material_output_quality == "exact") binding.source_authority = "exact_sidecar";
    binding.evidence_grade = evidence_grade_for_binding(binding, technique_parameter);
    return binding;
}

static void add_sidecar_texture_binding(
    MaterialBindingBuildState& state,
    TextureBinding binding,
    const ArchiveEntryRef& selected,
    const ArchiveEntryRef& sidecar,
    bool parameter_was_named
) {
    const std::string key = lower_copy(
        binding.component_scope_id + "|" + binding.owner_wrapper_item_id + "|"
        + std::to_string(binding.material_wrapper_index) + "|" + binding.parameter_name + "|"
        + binding.declared_texture_path);
    if (!state.seen.insert(key).second) {
        for (TextureBinding& existing : state.bindings) {
            const std::string existing_key = lower_copy(
                existing.component_scope_id + "|" + existing.owner_wrapper_item_id + "|"
                + std::to_string(existing.material_wrapper_index) + "|"
                + existing.parameter_name + "|" + existing.declared_texture_path);
            if (existing_key != key) continue;
            for (const std::string& representation : binding.representation_sidecar_paths) {
                if (std::find(
                        existing.representation_sidecar_paths.begin(),
                        existing.representation_sidecar_paths.end(),
                        representation) == existing.representation_sidecar_paths.end()) {
                    existing.representation_sidecar_paths.push_back(representation);
                }
            }
            break;
        }
        return;
    }
    state.bindings.push_back(binding);
    add_asset_family_row(state.package, NativeAssetFamilyRow{
        "Textures", "Texture", selected.basename.empty() ? basename_from_path(selected.path) : selected.basename,
        selected.path, "Resolved", parameter_was_named ? "Sidecar" : "Family",
        binding.relation_confidence, "required", binding.relation_reason, "texture",
        binding.semantic_type.empty() ? binding.role : binding.semantic_type,
        binding.parameter_name, binding.parameter_name, binding.material_name,
        package_label_for_ref(selected), sidecar.extension, binding.shader_family, binding.role, "", ""
    });
}

static bool process_sidecar_texture_ref(
    MaterialBindingBuildState& state,
    const ArchiveEntryRef& sidecar,
    const ParsedMaterialSidecar& parsed,
    const SidecarTextureRef& ref,
    bool wrapper_order_authoritative,
    int scoped_mesh_count,
    const std::string& component_key,
    const std::string& component_scope_id,
    const std::string& model_family_key
) {
    const bool owner_declaration_matches = sidecar_ref_owner_declaration_matches_meshes(
        parsed,
        ref,
        component_key,
        wrapper_order_authoritative,
        scoped_mesh_count,
        state.meshes,
        model_family_key);
    if (!owner_declaration_matches
        && !sidecar_ref_matches_meshes(ref, component_key, wrapper_order_authoritative,
            scoped_mesh_count, state.meshes, model_family_key)) {
        if (state.package.rejected_texture_examples.size() < 16) {
            state.package.rejected_texture_examples.push_back(
                "sidecar skipped unrelated material wrapper "
                + (ref.material_name.empty() ? std::string("-") : ref.material_name)
                + " texture=" + basename_from_path(ref.path));
        }
        return false;
    }
    std::string shader_family = ref.shader_family.empty() ? parsed.shader_family : ref.shader_family;
    if (shader_family.empty() && sidecar.extension == ".pami") shader_family = "StaticMaterial";
    const std::string shader_rule = shader_rule_for_family(shader_family);
    const TechniqueParameterInfo* technique_parameter = technique_parameter_for_name(
        state.technique_index, ref.parameter_name, shader_family);
    const std::string basename = lower_copy(basename_from_path(ref.path));
    const std::string role = role_from_parameter_shader_and_name(
        ref.parameter_name, shader_rule, basename, technique_parameter);
    const std::string parameter_key = normalized_key(ref.parameter_name);
    const bool exact_skin_detail_support = shader_rule == "skin"
        && parameter_is_skin_detail_support(ref.parameter_name);
    const bool exact_emissive_layer_support = shader_rule == "emissive"
        && wrapper_order_authoritative
        && ref.material_wrapper_index >= 0
        && !ref.material_name.empty()
        && !ref.parameter_name.empty()
        && (parameter_key.find("detail") != std::string::npos
            || parameter_key.find("grime") != std::string::npos
            || parameter_key.find("dye") != std::string::npos);
    const bool keep_layer_stack_aux = shader_rule.find("standard") != std::string::npos
        || shader_rule.find("cloth") != std::string::npos
        || shader_rule.find("multitextured") != std::string::npos
        || (shader_rule.find("generic") != std::string::npos
            && native_pbd_hints_have_soft_physics(parsed.pbd_hints));
    if (normalize_visible_texture_mode(state.job.visible_texture_mode) == "mesh_base_first"
        && !keep_layer_stack_aux
        && !exact_skin_detail_support
        && !exact_emissive_layer_support
        && !sidecar_ref_has_exact_wrapper_identity(ref)
        && (parameter_key.find("detail") != std::string::npos
            || parameter_key.find("grime") != std::string::npos
            || parameter_key.find("dye") != std::string::npos)
        && role != "base") return false;
    std::optional<ResolvedSidecarTextureCandidate> selected =
        resolve_sidecar_texture_candidate(
            state.job, state.index, sidecar, ref, technique_parameter);
    if (!selected.has_value() && !state.job.package_root.empty()) {
        // Most declared DDS paths resolve without a package-wide technique
        // scan. Load the authoritative global declarations only when a source
        // is actually absent, then keep them resident for the service's later
        // jobs. This preserves source defaults without taxing ordinary/Rhett
        // first-use latency.
        const TechniqueIndex& package_techniques = cached_package_technique_index(
            state.job, state.index);
        technique_parameter = technique_parameter_for_name(
            package_techniques, ref.parameter_name, shader_family);
        selected = resolve_sidecar_texture_candidate(
            state.job, state.index, sidecar, ref, technique_parameter);
    }
    if (!selected.has_value()) return true;
    const std::string extracted = extracted_dds_path_for_entry(
        selected->entry, state.job.cache_root, state.notes);
    if (extracted.empty()) return true;
    add_sidecar_texture_binding(state, make_sidecar_texture_binding(
        ref, parsed, sidecar, selected->entry, extracted, shader_family, shader_rule,
        technique_parameter, selected->resolution, selected->detail,
        selected->declared_source_missing, wrapper_order_authoritative,
        component_scope_id, state.meshes),
        selected->entry, sidecar, !ref.parameter_name.empty());
    return true;
}

static int material_sidecar_model_property_index(
    const std::string& component_key,
    const std::vector<NativeSubmesh>& meshes
) {
    for (const NativeSubmesh& mesh : meshes) {
        if (material_component_key_from_path(mesh.source_model_path) == component_key) {
            return mesh.model_property_index;
        }
    }
    return 0;
}

static void process_material_sidecar(MaterialBindingBuildState& state, const ArchiveEntryRef& sidecar) {
    add_asset_family_row(state.package, NativeAssetFamilyRow{
        "Material", sidecar.extension == ".pami" ? "Material Index" : "Material Sidecar",
        sidecar.basename.empty() ? basename_from_path(sidecar.path) : sidecar.basename,
        sidecar.path, "Resolved", "Sidecar", "authoritative", "required",
        "Native preview-core selected this material sidecar for the current model.",
        "metadata", "Material sidecar", "", "", "", package_label_for_ref(sidecar),
        sidecar.extension, "", "", "", ""
    });
    const std::string component_key = material_component_key_from_path(sidecar.path);
    const MaterialComponentScope component_scope =
        material_component_scope_for_sidecar(sidecar, state.meshes);
    const int model_property_index = component_scope.model_property_index;
    if (component_scope.ambiguous) {
        state.package.material_conservation_ok = false;
        state.package.material_conservation_findings.push_back(
            "ambiguous_component_scope:" + sidecar.path);
    }
    const ParsedMaterialSidecar* parsed = nullptr;
    try {
        parsed = &cached_parsed_material_sidecar(sidecar, model_property_index);
    } catch (const std::exception& exc) {
        state.package.notes.push_back(
            std::string("native material sidecar read failed:") + sidecar.path + ": " + exc.what());
        return;
    }
    state.package.pbd_hint_count += static_cast<int>(parsed->pbd_hints.size());
    for (const NativePbdSidecarHint& hint : parsed->pbd_hints) {
        if (native_pbd_hint_is_soft_physics(hint)) ++state.package.pbd_soft_hint_count;
        if (native_pbd_hint_is_cloth(hint)) ++state.package.pbd_cloth_hint_count;
    }
    state.shader_rules.insert(parsed->shader_rule);
    state.sidecar_kinds.insert(sidecar.extension.empty() ? "unknown" : sidecar.extension);
    state.package.notes.push_back(
        "native material sidecar: " + sidecar.path
        + "; rule=" + parsed->shader_rule
        + "; texture_params=" + std::to_string(parsed->parameter_summary.texture_params)
        + "; float_params=" + std::to_string(parsed->parameter_summary.float_params)
        + "; color_params=" + std::to_string(parsed->parameter_summary.color_params)
        + "; byte4_params=" + std::to_string(parsed->parameter_summary.byte4_params)
        + "; flags=" + std::to_string(parsed->parameter_summary.bit_flags)
        + "; pbd_hints=" + std::to_string(parsed->pbd_hints.size())
        + "; model_property_index=" + std::to_string(model_property_index));
    const int scoped_count = sidecar_scoped_mesh_count(component_key, state.meshes);
    const bool wrapper_order_authoritative = parsed->material_wrapper_count > 0
        && parsed->material_wrapper_count == scoped_count;
    const std::string model_family_key = normalized_material_key(stem_from_path(state.job.path));
    for (const MaterialWrapperDeclaration& declaration : parsed->declarations) {
        record_material_wrapper_declaration(
            state,
            sidecar,
            *parsed,
            declaration,
            wrapper_order_authoritative,
            scoped_count,
            component_key,
            component_scope.id,
            model_family_key);
    }
    int considered = 0;
    for (const SidecarTextureRef& ref : parsed->refs) {
        if (process_sidecar_texture_ref(state, sidecar, *parsed, ref, wrapper_order_authoritative,
            scoped_count, component_key, component_scope.id, model_family_key)) ++considered;
    }
    state.package.dds_candidates += considered;
}

static std::string joined_material_set(const std::set<std::string>& values) {
    std::ostringstream output;
    bool first = true;
    for (const std::string& value : values) {
        if (!first) output << "+";
        first = false;
        output << value;
    }
    return output.str();
}

static void finish_material_bindings(MaterialBindingBuildState& state, size_t sidecar_count) {
    state.package.dds_extracted = static_cast<int>(state.bindings.size());
    int exact = 0;
    int inferred = 0;
    int approximate = 0;
    for (const TextureBinding& binding : state.bindings) {
        if (binding.material_output_quality == "exact") ++exact;
        else if (binding.material_output_quality == "approximate") ++approximate;
        else ++inferred;
    }
    for (NativeMaterialConservationRow& row : state.package.material_conservation_rows) {
        if (row.parameter.kind != "texture" || row.parameter.texture_path.empty()
            || !row.logical_graph_edge) continue;
        const TextureBinding* resolved = nullptr;
        const TextureBinding* cross_owner = nullptr;
        for (const TextureBinding& binding : state.bindings) {
            const bool same_component_scope = lower_copy(binding.component_scope_id)
                == lower_copy(row.component_scope_id);
            const bool same_parameter = lower_copy(binding.parameter_name)
                == lower_copy(row.parameter.name);
            const bool same_path = lower_copy(native_archive_path(binding.declared_texture_path))
                == lower_copy(native_archive_path(row.parameter.texture_path));
            if (!same_component_scope || !same_parameter || !same_path) continue;
            if (lower_copy(binding.owner_wrapper_item_id)
                    == lower_copy(row.owner_wrapper_item_id)
                && binding.material_wrapper_index == row.material_wrapper_index) {
                resolved = &binding;
                break;
            }
            cross_owner = &binding;
        }
        if (resolved != nullptr) {
            row.texture_resolved = true;
            row.role = resolved->role;
            row.layer_role = resolved->layer_role;
            row.layer_channel = resolved->layer_channel;
            row.resolved_source_path = resolved->source_path;
            row.resolved_archive_path = resolved->archive_path;
            row.source_resolution = resolved->source_resolution;
            row.source_resolution_detail = resolved->source_resolution_detail;
            row.semantic_type = resolved->semantic_type;
            row.semantic_subtype = resolved->semantic_subtype;
            row.packed_channels = resolved->packed_channels;
            row.srgb_mode = resolved->srgb_mode;
            row.sidecar_kind = resolved->sidecar_kind;
            row.declared_source_missing = resolved->declared_source_missing;
            row.status = "resolved_exact_owner";
        } else if (cross_owner != nullptr) {
            row.status = "cross_owner_binding";
            row.finding = "cross_owner_binding";
            state.package.material_conservation_ok = false;
            state.package.material_conservation_findings.push_back(
                "cross_owner_binding:" + row.sidecar_path + ":"
                + row.owner_wrapper_item_id + ":" + row.parameter.name);
        } else {
            row.status = "transported_source_unavailable";
            row.finding = "source_dds_unavailable";
            state.package.material_conservation_ok = false;
            state.package.material_conservation_findings.push_back(
                "source_dds_unavailable:" + row.sidecar_path + ":"
                + row.owner_wrapper_item_id + ":" + row.parameter.name + ":"
                + row.parameter.texture_path);
        }
    }
    const std::string kind_summary = joined_material_set(state.sidecar_kinds);
    const std::string rule_summary = joined_material_set(state.shader_rules);
    state.package.material_index = state.bindings.empty()
        ? "native_sidecars_no_resolved_dds" : ("native_sidecar_index:" + kind_summary);
    state.package.texture_resolution = state.bindings.empty() ? "none" : "same_pamt_basename";
    state.package.material_output_quality = state.bindings.empty()
        ? "approximate" : (exact > 0 ? "exact_inputs_inferred_shader" : "inferred");
    state.package.notes.push_back(
        std::string("native material accuracy: ") + state.package.material_output_quality
        + "; sidecars=" + std::to_string(sidecar_count)
        + "; shader_rules=" + (rule_summary.empty() ? "generic" : rule_summary)
        + "; bindings exact=" + std::to_string(exact)
        + " inferred=" + std::to_string(inferred)
        + " approximate=" + std::to_string(approximate));
    state.package.notes.insert(state.package.notes.end(), state.notes.begin(), state.notes.end());
}

static std::vector<TextureBinding> build_material_bindings(
    const EntryJob& job,
    const PamtIndex& index,
    const std::vector<NativeSubmesh>& meshes,
    NativePackage& package
) {
    std::optional<NativeMaterialGraph> bounded_graph;
    const NativeMaterialGraph* graph = nullptr;
    if (job.archive_dependency_entries_complete) {
        bounded_graph.emplace(build_bounded_native_material_graph(index));
        graph = &*bounded_graph;
    } else {
        graph = &cached_native_material_graph(job, index);
    }
    package.material_graph_status = "active";
    package.material_graph_cache_path = graph->cache_path.string();
    package.material_graph_cache_hit = graph->persistent_cache_hit;
    package.notes.push_back(
        "native material graph: version=" + std::to_string(graph->version)
        + "; cache=" + std::string(
            job.archive_dependency_entries_complete
                ? "bounded_snapshot"
                : (graph->persistent_cache_hit ? "hit" : "write"))
        + "; pamts=" + std::to_string(graph->pamt_count)
        + "; entries=" + std::to_string(graph->entry_count)
        + "; sidecars=" + std::to_string(graph->material_sidecar_count)
        + "; dds_basenames=" + std::to_string(graph->texture_candidate_count));
    const std::vector<ArchiveEntryRef> sidecars = material_sidecar_candidates_for_job(job, index);
    if (sidecars.empty()) {
        package.material_index = "native_index_no_sidecar";
        package.texture_resolution = "none";
        package.notes.push_back("native material index: no matching .pac_xml/.pam_xml/.pamlod_xml/.pami/.material/.technique/.prefab sidecar");
        return {};
    }
    if (graph->technique_index.files_scanned > 0) {
        package.notes.push_back(
            "native technique index: files=" + std::to_string(graph->technique_index.files_scanned)
            + "; techniques=" + std::to_string(graph->technique_index.technique_names.size())
            + "; texture_params=" + std::to_string(graph->technique_index.texture_parameters));
    }
    MaterialBindingBuildState state{job, index, meshes, package, graph->technique_index};
    for (const ArchiveEntryRef& sidecar : sidecars) process_material_sidecar(state, sidecar);
    finish_material_bindings(state, sidecars.size());
    return std::move(state.bindings);
}
