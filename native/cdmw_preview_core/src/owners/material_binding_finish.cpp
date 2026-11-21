// The last step of material binding: every declared texture row is settled against
// the bindings that were made, and the package is told what it ended up with.

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
        const std::string row_parameter_key = normalized_key(row.parameter.name);
        // A source this row's own material wrapper has for another of its parameters.
        const auto same_wrapper_source = [&](const char* parameter_key, bool exact_only) {
            return std::any_of(state.bindings.begin(), state.bindings.end(), [&](const TextureBinding& binding) {
                return normalized_key(binding.parameter_name) == parameter_key
                    && !binding.source_path.empty()
                    && (!exact_only || binding.source_authority == "exact_sidecar")
                    && lower_copy(binding.component_scope_id) == lower_copy(row.component_scope_id)
                    && lower_copy(binding.sidecar_path) == lower_copy(row.sidecar_path)
                    && lower_copy(binding.owner_wrapper_item_id) == lower_copy(row.owner_wrapper_item_id)
                    && binding.material_wrapper_index == row.material_wrapper_index;
            });
        };
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
            // Another material's technique default is not a binding of this
            // owner's missing source. Keep the missing-source diagnosis so
            // the caller can offer its explicit geometry-only preview.
            if (binding.source_resolution != "technique_default_after_missing_declared_source") {
                cross_owner = &binding;
            }
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
        } else if (row_parameter_key == "emissivetexture"
            && same_wrapper_source("emissiveintensitytexture", true)) {
            // The native scalar emission path takes precedence over RGB.
            // Keep the missing declaration as evidence, but it is not an active
            // preview edge and must not discard every other material map.
            row.declared_source_missing = true;
            row.status = "transported_inactive_rgb_emission";
            row.source_resolution_detail = "resolved_same_wrapper_emissive_intensity_takes_precedence";
        } else if ((row_parameter_key == "emissivetexture" || row_parameter_key == "emissiveintensitytexture")
            && !same_wrapper_source(
                row_parameter_key == "emissivetexture" ? "emissiveintensitytexture" : "emissivetexture",
                false)) {
            // Many world materials declare an emission pair whose files the game
            // does not ship. With no emission source in the wrapper the material
            // does not glow; that must not discard its colour, normal and
            // response maps. A missing half of a pair whose other half is active
            // still fails below.
            row.declared_source_missing = true;
            row.status = "transported_inactive_missing_emission";
            row.source_resolution_detail = "no_emission_source_in_same_wrapper";
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
