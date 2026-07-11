struct MaterialBindingBuildState {
    const EntryJob& job;
    const PamtIndex& index;
    const std::vector<NativeSubmesh>& meshes;
    NativePackage& package;
    const TechniqueIndex& technique_index;
    std::vector<TextureBinding> bindings;
    std::vector<std::string> notes;
    std::set<std::string> seen;
    std::set<std::string> sidecar_kinds;
    std::set<std::string> shader_rules;
};

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

static TextureBinding make_sidecar_texture_binding(
    const SidecarTextureRef& ref,
    const ParsedMaterialSidecar& parsed,
    const ArchiveEntryRef& sidecar,
    const ArchiveEntryRef& selected,
    const std::string& extracted,
    const std::string& shader_family,
    const std::string& shader_rule,
    const TechniqueParameterInfo* technique_parameter,
    bool wrapper_order_authoritative,
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
    const std::string parameter_lower = lower_copy(binding.parameter_name);
    if (binding.role == "base" && !parameter_is_authoritative_visible_base(binding.parameter_name)
        && role_is_technical_for_base(texture_role_from_name(basename))) binding.role = texture_role_from_name(basename);
    binding.semantic_type = semantic_type_for_role(binding.role);
    binding.semantic_subtype = semantic_subtype_for_role(binding.role);
    binding.shader_family = shader_family;
    binding.shader_rule = shader_rule;
    binding.material_name = ref.material_name.empty() ? stem_from_path(sidecar.path) : ref.material_name;
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
    binding.sidecar_kind = sidecar.extension;
    if (const NativePbdSidecarHint* hint = best_native_pbd_hint_for_binding(
        parsed.pbd_hints, binding.material_name, ref.material_name, binding.parameter_name)) {
        binding.pbd_simulation_material_name = hint->simulation_material_name;
        binding.pbd_simulation_kind = hint->simulation_kind;
        binding.pbd_material_name = hint->material_name;
        binding.pbd_submesh_name = hint->submesh_name;
    }
    binding.linked_mesh_path = parsed.parameter_summary.linked_mesh_path;
    binding.packed_channels = packed_channels_for_role(binding.role, basename, parameter_lower);
    binding.srgb_mode = srgb_mode_for_role(binding.role, technique_parameter);
    binding.parameter_declared_by = technique_parameter != nullptr ? "technique" : "";
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
    binding.tint_color = tint_for_layer(ref.material_parameters, binding.layer_role, binding.layer_channel);
    binding.blend_flags = normalized_key(binding.parameter_name).find("colorblending") != std::string::npos
        ? "color_blending_mask" : "";
    binding.material_parameter_names = joined_parameter_names(ref.material_parameters);
    binding.alpha_test_enabled = material_parameters_enable_flag(
        ref.material_parameters, {"AlphaTest", "AlphaClip", "AlphaCutout", "Cutout", "_alphaTest"});
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
        binding.role + "|" + binding.archive_path + "|" + binding.parameter_name + "|" + binding.material_name);
    if (!state.seen.insert(key).second) return;
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
    const std::string& model_family_key
) {
    if (!sidecar_ref_matches_meshes(ref, component_key, wrapper_order_authoritative,
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
        state.technique_index, ref.parameter_name);
    const std::string basename = lower_copy(basename_from_path(ref.path));
    const std::string role = role_from_parameter_shader_and_name(
        ref.parameter_name, shader_rule, basename, technique_parameter);
    const std::string parameter_key = normalized_key(ref.parameter_name);
    const bool keep_layer_stack_aux = shader_rule.find("standard") != std::string::npos
        || shader_rule.find("cloth") != std::string::npos
        || shader_rule.find("multitextured") != std::string::npos
        || (shader_rule.find("generic") != std::string::npos
            && native_pbd_hints_have_soft_physics(parsed.pbd_hints));
    if (normalize_visible_texture_mode(state.job.visible_texture_mode) == "mesh_base_first"
        && !keep_layer_stack_aux
        && (parameter_key.find("detail") != std::string::npos
            || parameter_key.find("grime") != std::string::npos
            || parameter_key.find("dye") != std::string::npos)
        && role != "base") return false;
    const std::vector<ArchiveEntryRef> candidates = lookup_basename_candidates_across_package(
        state.job, state.index, basename, 96);
    const std::optional<ArchiveEntryRef> selected = select_sidecar_texture_candidate(candidates, sidecar, basename);
    if (!selected.has_value()) return true;
    const std::string extracted = extracted_dds_path_for_entry(*selected, state.job.cache_root, state.notes);
    if (extracted.empty()) return true;
    add_sidecar_texture_binding(state, make_sidecar_texture_binding(
        ref, parsed, sidecar, *selected, extracted, shader_family, shader_rule,
        technique_parameter, wrapper_order_authoritative, state.meshes),
        *selected, sidecar, !ref.parameter_name.empty());
    return true;
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
    const ParsedMaterialSidecar* parsed = nullptr;
    try {
        parsed = &cached_parsed_material_sidecar(sidecar);
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
        + "; pbd_hints=" + std::to_string(parsed->pbd_hints.size()));
    const std::string component_key = material_component_key_from_path(sidecar.path);
    const int scoped_count = sidecar_scoped_mesh_count(component_key, state.meshes);
    const bool wrapper_order_authoritative = parsed->material_wrapper_count > 0
        && parsed->material_wrapper_count == scoped_count;
    const std::string model_family_key = normalized_material_key(stem_from_path(state.job.path));
    int considered = 0;
    for (const SidecarTextureRef& ref : parsed->refs) {
        if (process_sidecar_texture_ref(state, sidecar, *parsed, ref, wrapper_order_authoritative,
            scoped_count, component_key, model_family_key)) ++considered;
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
    const NativeMaterialGraph& graph = cached_native_material_graph(job, index);
    package.material_graph_status = "active";
    package.material_graph_cache_path = graph.cache_path.string();
    package.material_graph_cache_hit = graph.persistent_cache_hit;
    package.notes.push_back(
        "native material graph: version=" + std::to_string(graph.version)
        + "; cache=" + std::string(graph.persistent_cache_hit ? "hit" : "write")
        + "; pamts=" + std::to_string(graph.pamt_count)
        + "; entries=" + std::to_string(graph.entry_count)
        + "; sidecars=" + std::to_string(graph.material_sidecar_count)
        + "; dds_basenames=" + std::to_string(graph.texture_candidate_count));
    const std::vector<ArchiveEntryRef> sidecars = material_sidecar_candidates_for_job(job, index);
    if (sidecars.empty()) {
        package.material_index = "native_index_no_sidecar";
        package.texture_resolution = "none";
        package.notes.push_back("native material index: no matching .pac_xml/.pam_xml/.pamlod_xml/.pami/.material/.technique/.prefab sidecar");
        return {};
    }
    if (graph.technique_index.files_scanned > 0) {
        package.notes.push_back(
            "native technique index: files=" + std::to_string(graph.technique_index.files_scanned)
            + "; techniques=" + std::to_string(graph.technique_index.technique_names.size())
            + "; texture_params=" + std::to_string(graph.technique_index.texture_parameters));
    }
    MaterialBindingBuildState state{job, index, meshes, package, graph.technique_index};
    for (const ArchiveEntryRef& sidecar : sidecars) process_material_sidecar(state, sidecar);
    finish_material_bindings(state, sidecars.size());
    return std::move(state.bindings);
}
