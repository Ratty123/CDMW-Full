static bool json_vec3_field(const std::string& object, const std::string& name, DirectX::XMFLOAT3& output) {
    const std::vector<float> values = json_float_array_field(object, name);
    if (values.size() < 3) return false;
    if (!std::isfinite(values[0]) || !std::isfinite(values[1]) || !std::isfinite(values[2])) return false;
    output = DirectX::XMFLOAT3(values[0], values[1], values[2]);
    return true;
}

static SkeletonOverlayState parse_skeleton_overlay_state(const std::string& manifest, RendererStats& stats) {
    SkeletonOverlayState state;
    const std::string skeleton_overlay = json_object_field(manifest, "skeleton_overlay");
    if (skeleton_overlay.empty()) return state;
    stats.skeleton_bone_count = std::max(0, json_int_field(skeleton_overlay, "bone_count", 0));
    stats.skeleton_overlay_enabled = json_bool_field(skeleton_overlay, "enabled", false) && stats.skeleton_bone_count > 0;
    stats.skeleton_pose_enabled = json_bool_field(skeleton_overlay, "pose_enabled", false);
    stats.skeleton_selected_bone_index = json_int_field(skeleton_overlay, "selected_bone_index", -1);
    stats.skeleton_posed_bone_count = std::max(0, json_int_field(skeleton_overlay, "posed_bone_count", 0));
    state.enabled = stats.skeleton_overlay_enabled;
    state.pose_enabled = stats.skeleton_pose_enabled;
    state.selected_bone_index = stats.skeleton_selected_bone_index;
    std::map<int, DirectX::XMFLOAT3> positions_by_index;
    for (const std::string& object : json_object_array_field(skeleton_overlay, "bones")) {
        SkeletonOverlayBoneState bone;
        bone.index = json_int_field(object, "index", -1);
        bone.parent_index = json_int_field(object, "parent_index", -1);
        bone.has_position = json_vec3_field(object, "position", bone.position);
        bone.has_parent_position = json_vec3_field(object, "parent_position", bone.parent_position);
        if (bone.index >= 0 && bone.has_position) {
            positions_by_index[bone.index] = bone.position;
        }
        if (bone.index >= 0) {
            state.bones.push_back(bone);
        }
        if (state.bones.size() >= 4096u) break;
    }
    for (SkeletonOverlayBoneState& bone : state.bones) {
        if (!bone.has_parent_position && bone.parent_index >= 0) {
            auto parent = positions_by_index.find(bone.parent_index);
            if (parent != positions_by_index.end()) {
                bone.parent_position = parent->second;
                bone.has_parent_position = true;
            }
        }
    }
    if (state.bones.empty()) {
        state.enabled = false;
        stats.skeleton_overlay_enabled = false;
    }
    return state;
}

static ViewSettings parse_view_settings(const std::string& manifest) {
    ViewSettings settings;
    settings.orbit_sensitivity = std::clamp(json_float_field(manifest, "orbit_sensitivity", settings.orbit_sensitivity), 0.001f, 8.0f);
    settings.pan_sensitivity = std::clamp(json_float_field(manifest, "pan_sensitivity", settings.pan_sensitivity), 0.001f, 8.0f);
    settings.invert_orbit_x = json_bool_field(manifest, "invert_orbit_x", settings.invert_orbit_x);
    settings.invert_orbit_y = json_bool_field(manifest, "invert_orbit_y", settings.invert_orbit_y);
    settings.invert_pan_x = json_bool_field(manifest, "invert_pan_x", settings.invert_pan_x);
    settings.invert_pan_y = json_bool_field(manifest, "invert_pan_y", settings.invert_pan_y);
    return settings;
}

static void apply_render_tuning_preset(RenderTuning& tuning, const std::string& normalized_view_mode, const std::string& normalized_lighting_preset) {
    if (normalized_view_mode == "shiny_metal_inspection" || normalized_lighting_preset == "shiny_metal_inspection") {
        tuning.diagnostic_mode = 0;
        tuning.ao_strength = std::max(tuning.ao_strength, 0.45f);
        tuning.roughness_bias = std::min(tuning.roughness_bias, -0.04f);
        tuning.environment_strength = std::max(tuning.environment_strength, 0.62f);
        tuning.ambient_strength = std::max(tuning.ambient_strength, 0.84f);
        tuning.diffuse_wrap_bias = std::min(tuning.diffuse_wrap_bias, 0.58f);
        tuning.diffuse_light_scale = std::max(tuning.diffuse_light_scale, 0.62f);
        tuning.specular_base = std::max(tuning.specular_base, 0.055f);
        tuning.specular_max = std::max(tuning.specular_max, 0.52f);
        tuning.tone_exposure = std::max(tuning.tone_exposure, 1.00f);
        tuning.tone_contrast = std::max(tuning.tone_contrast, 1.08f);
        tuning.tone_gamma = std::min(tuning.tone_gamma, 1.00f);
    } else if (normalized_view_mode == "game_outdoor" || normalized_view_mode == "cd_outdoor" || normalized_view_mode == "outdoor_game") {
        tuning.diagnostic_mode = 0;
        tuning.light_elevation_degrees = std::max(tuning.light_elevation_degrees, 42.0f);
        tuning.ao_strength = std::min(tuning.ao_strength, 0.55f);
        tuning.roughness_bias = std::min(tuning.roughness_bias, 0.04f);
        tuning.environment_strength = std::max(tuning.environment_strength, 0.70f);
        tuning.emissive_gain = std::max(tuning.emissive_gain, 1.80f);
        tuning.ambient_strength = std::max(tuning.ambient_strength, 0.78f);
        tuning.diffuse_wrap_bias = std::max(tuning.diffuse_wrap_bias, 0.70f);
        tuning.diffuse_light_scale = std::max(tuning.diffuse_light_scale, 1.05f);
        tuning.specular_max = std::max(tuning.specular_max, 0.22f);
    }
}

static RenderTuning parse_render_tuning(const std::string& manifest) {
    RenderTuning tuning;
    const std::string d3d11_view_mode = json_string_field(manifest, "d3d11_view_mode");
    const std::string normalized_view_mode = lower_copy(d3d11_view_mode);
    const std::string normalized_lighting_preset = lower_copy(json_string_field(manifest, "lighting_preset"));
    const bool has_explicit_render_tuning =
        manifest.find("\"d3d11_mip_lod_bias\"") != std::string::npos ||
        manifest.find("\"ambient_strength\"") != std::string::npos ||
        manifest.find("\"diffuse_wrap_bias\"") != std::string::npos ||
        manifest.find("\"specular_base\"") != std::string::npos;
    tuning.diagnostic_mode = diagnostic_mode_code(d3d11_view_mode.empty() ? json_string_field(manifest, "render_diagnostic_mode") : d3d11_view_mode);
    tuning.max_anisotropy = std::clamp(json_int_field(manifest, "max_anisotropy", tuning.max_anisotropy), 1, 16);
    tuning.mip_lod_bias = std::clamp(json_float_field(manifest, "d3d11_mip_lod_bias", tuning.mip_lod_bias), -2.0f, 1.0f);
    tuning.cull_back_faces = json_bool_field(manifest, "d3d11_cull_back_faces", tuning.cull_back_faces);
    tuning.light_azimuth_degrees = std::clamp(json_float_field(manifest, "d3d11_light_azimuth_degrees", tuning.light_azimuth_degrees), -180.0f, 180.0f);
    tuning.light_elevation_degrees = std::clamp(json_float_field(manifest, "d3d11_light_elevation_degrees", tuning.light_elevation_degrees), -80.0f, 80.0f);
    const std::string normal_y_mode = lower_copy(json_string_field(manifest, "d3d11_normal_y_mode", "asset"));
    tuning.normal_y_mode = normal_y_mode == "force_flip" ? 1 : (normal_y_mode == "force_no_flip" ? 2 : 0);
    tuning.ao_strength = std::clamp(json_float_field(manifest, "d3d11_ao_strength", tuning.ao_strength), 0.0f, 2.0f);
    tuning.roughness_bias = std::clamp(json_float_field(manifest, "d3d11_roughness_bias", tuning.roughness_bias), -0.5f, 0.5f);
    tuning.metalness_scale = std::clamp(json_float_field(manifest, "d3d11_metalness_scale", tuning.metalness_scale), 0.0f, 2.0f);
    tuning.environment_strength = std::clamp(json_float_field(manifest, "d3d11_environment_strength", tuning.environment_strength), 0.0f, 2.0f);
    tuning.emissive_gain = std::clamp(json_float_field(manifest, "d3d11_emissive_gain", tuning.emissive_gain), 0.0f, 4.0f);
    tuning.tone_exposure = std::clamp(json_float_field(manifest, "d3d11_tone_exposure", tuning.tone_exposure), 0.25f, 2.0f);
    tuning.tone_contrast = std::clamp(json_float_field(manifest, "d3d11_tone_contrast", tuning.tone_contrast), 0.50f, 1.75f);
    tuning.tone_gamma = std::clamp(json_float_field(manifest, "d3d11_tone_gamma", tuning.tone_gamma), 0.50f, 2.20f);
    tuning.texture_address_mode = lower_copy(json_string_field(manifest, "d3d11_texture_address_mode", tuning.texture_address_mode));
    if (tuning.texture_address_mode != "clamp") tuning.texture_address_mode = "wrap";
    tuning.ambient_strength = std::clamp(json_float_field(manifest, "ambient_strength", tuning.ambient_strength), 0.05f, 1.20f);
    tuning.diffuse_wrap_bias = std::clamp(json_float_field(manifest, "diffuse_wrap_bias", tuning.diffuse_wrap_bias), 0.0f, 1.0f);
    tuning.diffuse_light_scale = std::clamp(json_float_field(manifest, "diffuse_light_scale", tuning.diffuse_light_scale), 0.05f, 1.50f);
    tuning.specular_base = std::clamp(json_float_field(manifest, "specular_base", tuning.specular_base), 0.0f, 0.50f);
    tuning.specular_max = std::clamp(json_float_field(manifest, "specular_max", tuning.specular_max), tuning.specular_base, 1.00f);
    tuning.shininess_min = std::clamp(json_float_field(manifest, "shininess_min", tuning.shininess_min), 1.0f, 128.0f);
    tuning.shininess_max = std::clamp(json_float_field(manifest, "shininess_max", tuning.shininess_max), tuning.shininess_min, 256.0f);
    if (!has_explicit_render_tuning) {
        apply_render_tuning_preset(tuning, normalized_view_mode, normalized_lighting_preset);
    }
    return tuning;
}

static std::vector<ClothCollider> parse_cloth_colliders(const fs::path& package_dir, const std::string& manifest) {
    std::vector<ClothCollider> colliders;
    std::wstring path = absolute_from_manifest_path(package_dir, json_string_field(manifest, "cloth_collider_file"));
    if (path.empty() || !fs::is_regular_file(fs::path(path))) return colliders;
    std::vector<uint8_t> data = read_binary(path);
    constexpr size_t kRecordFloats = 11u;
    constexpr size_t kRecordBytes = kRecordFloats * sizeof(float);
    const size_t record_count = data.size() / kRecordBytes;
    colliders.reserve(record_count);
    for (size_t index = 0; index < record_count; ++index) {
        const float* values = reinterpret_cast<const float*>(data.data() + index * kRecordBytes);
        ClothCollider collider;
        collider.type = static_cast<int>(std::round(values[0]));
        if (collider.type == 1) {
            collider.a = DirectX::XMFLOAT3(values[1], values[2], values[3]);
            collider.radius = std::max(0.0f, values[4]);
        } else if (collider.type == 2) {
            collider.a = DirectX::XMFLOAT3(values[1], values[2], values[3]);
            collider.b = DirectX::XMFLOAT3(values[4], values[5], values[6]);
            collider.radius = std::max(0.0f, values[7]);
        } else if (collider.type == 3) {
            collider.a = DirectX::XMFLOAT3(
                std::min(values[1], values[4]),
                std::min(values[2], values[5]),
                std::min(values[3], values[6]));
            collider.b = DirectX::XMFLOAT3(
                std::max(values[1], values[4]),
                std::max(values[2], values[5]),
                std::max(values[3], values[6]));
        } else {
            continue;
        }
        colliders.push_back(collider);
    }
    return colliders;
}

static DirectX::XMFLOAT4 parse_hex_color(const std::string& hex, DirectX::XMFLOAT4 fallback) {
    if (hex.size() < 7 || hex[0] != '#') return fallback;
    try {
        int r = std::stoi(hex.substr(1, 2), nullptr, 16);
        int g = std::stoi(hex.substr(3, 2), nullptr, 16);
        int b = std::stoi(hex.substr(5, 2), nullptr, 16);
        return DirectX::XMFLOAT4(r / 255.0f, g / 255.0f, b / 255.0f, 1.0f);
    } catch (...) {
        return fallback;
    }
}

static std::string skipped_json(const std::vector<std::string>& skipped) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < skipped.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(skipped[i]) << "\"";
    }
    out << "]";
    return out.str();
}

static std::string string_array_json(const std::vector<std::string>& values) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < values.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(values[i]) << "\"";
    }
    out << "]";
    return out.str();
}

static std::string hresult_hex(HRESULT hr) {
    std::ostringstream out;
    out << "0x" << std::uppercase << std::hex << static_cast<unsigned long>(static_cast<unsigned int>(hr));
    return out.str();
}

static bool is_device_loss_hresult(HRESULT hr) {
    return hr == DXGI_ERROR_DEVICE_REMOVED
        || hr == DXGI_ERROR_DEVICE_RESET
        || hr == DXGI_ERROR_DRIVER_INTERNAL_ERROR;
}

static bool env_flag_enabled(const char* name) {
    if (name == nullptr || name[0] == '\0') return false;
    char value[16] = {};
    DWORD length = GetEnvironmentVariableA(name, value, static_cast<DWORD>(sizeof(value)));
    if (length == 0 || length >= sizeof(value)) return false;
    std::string text = lower_copy(value);
    return text == "1" || text == "true" || text == "yes" || text == "on";
}

static std::string failed_texture_json(const std::string& item) {
    std::vector<std::string> parts;
    size_t start = 0;
    while (parts.size() < 7) {
        const size_t pos = item.find('|', start);
        if (pos == std::string::npos) {
            parts.push_back(item.substr(start));
            break;
        }
        parts.push_back(item.substr(start, pos - start));
        start = pos + 1;
    }
    while (parts.size() < 7) parts.push_back("");
    const bool expanded = !parts[5].empty() || !parts[6].empty();
    const std::string slot = parts[0];
    const std::string source_kind = expanded ? parts[1] : "legacy";
    const std::string path = expanded ? parts[2] : parts[1];
    const std::string stage = expanded ? parts[3] : parts[2];
    const std::string hresult = expanded ? parts[4] : parts[3];
    const std::string required = expanded ? parts[5] : "false";
    const std::string message = expanded ? parts[6] : parts[4];
    const bool required_slot = lower_copy(required) == "required" || lower_copy(required) == "true";
    std::ostringstream out;
    out << "{"
        << "\"slot\":\"" << json_escape(slot) << "\","
        << "\"source_kind\":\"" << json_escape(source_kind) << "\","
        << "\"path\":\"" << json_escape(path) << "\","
        << "\"stage\":\"" << json_escape(stage) << "\","
        << "\"hresult\":\"" << json_escape(hresult) << "\","
        << "\"required\":" << (required_slot ? "true" : "false") << ","
        << "\"message\":\"" << json_escape(message) << "\""
        << "}";
    return out.str();
}

static std::string failed_textures_json(const std::vector<std::string>& values) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < values.size() && i < 24; ++i) {
        if (i) out << ",";
        out << failed_texture_json(values[i]);
    }
    out << "]";
    return out.str();
}

static std::string float3_json(const DirectX::XMFLOAT3& value) {
    std::ostringstream out;
    out << "[" << value.x << "," << value.y << "," << value.z << "]";
    return out.str();
}

static std::string matrix4x4_json(const DirectX::XMFLOAT4X4& value) {
    std::ostringstream out;
    out << "["
        << value._11 << "," << value._12 << "," << value._13 << "," << value._14 << ","
        << value._21 << "," << value._22 << "," << value._23 << "," << value._24 << ","
        << value._31 << "," << value._32 << "," << value._33 << "," << value._34 << ","
        << value._41 << "," << value._42 << "," << value._43 << "," << value._44
        << "]";
    return out.str();
}

static std::string float3_delta_json(const DirectX::XMFLOAT3& value) {
    return float3_json(value);
}

static std::string loaded_payload_for_event(const RendererStats& stats, const std::string& event_name) {
    std::ostringstream loaded;
    loaded << "{"
           << "\"event\":\"" << json_escape(event_name.empty() ? "loaded" : event_name) << "\","
           << "\"backend\":\"D3D11\","
           << "\"capabilities\":[\"mesh_edit_revision_ack_v1\"],"
           << "\"batch_count\":" << stats.batch_count << ","
           << "\"vertex_count\":" << stats.vertex_count << ","
           << "\"schema_version\":" << stats.manifest_schema_version << ","
           << "\"textures\":" << slot_counts_json(stats.textures_loaded) << ","
           << "\"png_fallback\":" << stats.png_fallback << ","
           << "\"texture_cache_hits\":" << stats.texture_cache_hits << ","
           << "\"low_resolution_base_textures\":" << stats.low_resolution_base_textures << ","
           << "\"srgb_color_uploads\":" << stats.srgb_color_uploads << ","
           << "\"linear_data_uploads\":" << stats.linear_data_uploads << ","
           << "\"png_fallbacks\":" << slot_counts_json(stats.png_uploaded) << ","
           << "\"dds_direct_upload_candidates\":" << slot_counts_json(stats.dds_candidates) << ","
           << "\"dds_direct_uploads\":" << slot_counts_json(stats.dds_uploaded) << ","
           << "\"dds_upload_formats\":" << string_int_map_json(stats.dds_upload_formats) << ","
           << "\"material_combiner_active\":" << stats.material_combiner_active_batches << ","
           << "\"material_combiner_outputs\":" << string_int_map_json(stats.material_combiner_outputs) << ","
           << "\"material_combiner_decode_modes\":" << string_int_map_json(stats.material_combiner_decode_modes) << ","
           << "\"material_layer_active\":" << stats.material_layer_active_batches << ","
           << "\"material_layer_count\":" << stats.material_layer_count << ","
           << "\"material_layer_roles\":" << string_int_map_json(stats.material_layer_roles) << ","
           << "\"material_contract_schema\":" << stats.material_contract_schema << ","
           << "\"material_channel_contract_schema\":" << stats.material_channel_contract_schema << ","
           << "\"texture_quality_schema\":" << stats.texture_quality_schema << ","
           << "\"cloth_runtime_schema\":" << stats.cloth_runtime_schema << ","
           << "\"render_diagnostic_mode\":\"" << json_escape(stats.render_diagnostic_mode) << "\","
           << "\"lighting_preset\":\"" << json_escape(stats.lighting_preset) << "\","
           << "\"placement_frame_kind\":\"" << json_escape(stats.placement_frame_kind) << "\","
           << "\"grid_mode\":\"" << json_escape(stats.grid_mode) << "\","
           << "\"grid_y\":" << stats.grid_y << ","
           << "\"reference_tint_mode\":\"" << json_escape(stats.reference_tint_mode) << "\","
           << "\"reference_material_policy\":\"" << json_escape(stats.reference_material_policy) << "\","
           << "\"physics_overlay_enabled\":" << (stats.physics_overlay_enabled ? "true" : "false") << ","
           << "\"physics_overlay_cloth\":" << (stats.physics_overlay_cloth ? "true" : "false") << ","
           << "\"physics_shape_count\":" << stats.physics_shape_count << ","
           << "\"physics_anchor_count\":" << stats.physics_anchor_count << ","
           << "\"physics_constraint_count\":" << stats.physics_constraint_count << ","
           << "\"cloth_runtime_debug_enabled\":" << (stats.cloth_runtime_debug_enabled ? "true" : "false") << ","
           << "\"skeleton_overlay_enabled\":" << (stats.skeleton_overlay_enabled ? "true" : "false") << ","
           << "\"skeleton_bone_count\":" << stats.skeleton_bone_count << ","
           << "\"skeleton_pose_enabled\":" << (stats.skeleton_pose_enabled ? "true" : "false") << ","
           << "\"skeleton_selected_bone_index\":" << stats.skeleton_selected_bone_index << ","
           << "\"skeleton_posed_bone_count\":" << stats.skeleton_posed_bone_count << ","
           << "\"editable_value_group_count\":" << stats.editable_value_group_count << ","
           << "\"semantic_writes_enabled\":false,"
           << "\"cloth_batch_count\":" << stats.cloth_batch_count << ","
           << "\"cloth_particle_count\":" << stats.cloth_particle_count << ","
           << "\"cloth_constraint_count\":" << stats.cloth_constraint_count << ","
           << "\"cloth_collider_count\":" << stats.cloth_collider_count << ","
           << "\"pbd_hint_count\":" << stats.pbd_hint_count << ","
           << "\"pbd_soft_hint_count\":" << stats.pbd_soft_hint_count << ","
           << "\"pbd_cloth_hint_count\":" << stats.pbd_cloth_hint_count << ","
           << "\"cloth_simulation_steps\":" << stats.cloth_simulation_steps << ","
           << "\"manifest_read_ms\":" << stats.manifest_ms << ","
           << "\"texture_bind_ms\":" << stats.texture_ms << ","
           << "\"geometry_upload_ms\":" << stats.geometry_ms << ","
           << "\"native_manifest_ms\":" << stats.manifest_ms << ","
           << "\"native_geometry_ms\":" << stats.geometry_ms << ","
           << "\"native_texture_ms\":" << stats.texture_ms << ","
           << "\"first_frame_ms\":" << stats.first_frame_ms << ","
           << "\"texture_cache_entries\":" << stats.texture_cache_entries << ","
           << "\"texture_cache_releases\":" << stats.texture_cache_releases << ","
           << "\"estimated_texture_bytes\":" << stats.estimated_texture_bytes << ","
           << "\"texture_cache_bytes\":" << stats.texture_cache_bytes << ","
           << "\"live_texture_bytes\":" << stats.live_texture_bytes << ","
           << "\"texture_failures\":" << stats.texture_failures << ","
           << "\"required_texture_failures\":" << stats.required_texture_failures << ","
           << "\"texture_integrity\":\"" << json_escape(stats.texture_integrity) << "\","
           << "\"failed_textures\":" << failed_textures_json(stats.failed_textures) << ","
           << "\"device_lost\":" << (stats.device_lost ? "true" : "false") << ","
           << "\"device_loss_stage\":\"" << json_escape(stats.device_loss_stage) << "\","
           << "\"device_loss_hresult\":\"" << json_escape(stats.device_loss_hresult) << "\","
           << "\"device_removed_reason\":\"" << json_escape(stats.device_removed_reason) << "\","
           << "\"present_failure_count\":" << stats.present_failure_count << ","
           << "\"resize_failure_count\":" << stats.resize_failure_count << ","
           << "\"resize_failure_hresult\":\"" << json_escape(stats.resize_failure_hresult) << "\","
           << "\"resize_failure_reason\":\"" << json_escape(stats.resize_failure_reason) << "\","
           << "\"process_working_set_bytes\":" << stats.process_working_set_bytes << ","
           << "\"process_private_bytes\":" << stats.process_private_bytes << ","
           << "\"frame_count\":" << stats.frame_count << ","
           << "\"render_request_count\":" << stats.render_request_count << ","
           << "\"render_suppressed_count\":" << stats.render_suppressed_count << ","
           << "\"mesh_edit_selection_event_count\":" << stats.mesh_edit_selection_event_count << ","
           << "\"render_suppressed_reason\":\"" << json_escape(stats.render_suppressed_reason) << "\","
           << "\"parent_renderable\":" << (stats.parent_renderable ? "true" : "false") << ","
           << "\"parent_unresponsive_count\":" << stats.parent_unresponsive_count << ","
           << "\"parent_health\":\"" << json_escape(stats.parent_health) << "\","
           << "\"sampler_max_anisotropy\":" << stats.sampler_max_anisotropy << ","
           << "\"sampler_mip_lod_bias\":" << stats.sampler_mip_lod_bias << ","
           << "\"sampler_recreate_count\":" << stats.sampler_recreate_count << ","
           << "\"texture_details\":" << string_array_json(stats.texture_details) << ","
           << "\"skipped\":" << skipped_json(stats.skipped)
           << "}";
    return loaded.str();
}

static std::string loaded_payload(const RendererStats& stats) {
    return loaded_payload_for_event(stats, "loaded");
}

static std::string resources_loaded_payload(const RendererStats& stats) {
    return loaded_payload_for_event(stats, "resources_loaded");
}

static std::string error_payload(const std::string& message, const RendererStats& stats) {
    std::ostringstream out;
    out << "{"
        << "\"event\":\"error\","
        << "\"backend\":\"D3D11\","
        << "\"message\":\"" << json_escape(message) << "\","
        << "\"batch_count\":" << stats.batch_count << ","
        << "\"vertex_count\":" << stats.vertex_count << ","
        << "\"texture_failures\":" << stats.texture_failures << ","
        << "\"required_texture_failures\":" << stats.required_texture_failures << ","
        << "\"texture_integrity\":\"" << json_escape(stats.texture_integrity) << "\","
        << "\"failed_textures\":" << failed_textures_json(stats.failed_textures) << ","
        << "\"device_lost\":" << (stats.device_lost ? "true" : "false") << ","
        << "\"device_loss_stage\":\"" << json_escape(stats.device_loss_stage) << "\","
        << "\"device_loss_hresult\":\"" << json_escape(stats.device_loss_hresult) << "\","
        << "\"device_removed_reason\":\"" << json_escape(stats.device_removed_reason) << "\","
        << "\"present_failure_count\":" << stats.present_failure_count << ","
        << "\"resize_failure_count\":" << stats.resize_failure_count << ","
        << "\"resize_failure_hresult\":\"" << json_escape(stats.resize_failure_hresult) << "\","
        << "\"resize_failure_reason\":\"" << json_escape(stats.resize_failure_reason) << "\","
        << "\"texture_bind_ms\":" << stats.texture_ms << ","
        << "\"geometry_upload_ms\":" << stats.geometry_ms << ","
        << "\"texture_cache_entries\":" << stats.texture_cache_entries << ","
        << "\"texture_cache_releases\":" << stats.texture_cache_releases << ","
        << "\"estimated_texture_bytes\":" << stats.estimated_texture_bytes << ","
        << "\"texture_cache_bytes\":" << stats.texture_cache_bytes << ","
        << "\"live_texture_bytes\":" << stats.live_texture_bytes << ","
        << "\"texture_cache_bytes\":" << stats.texture_cache_bytes << ","
        << "\"live_texture_bytes\":" << stats.live_texture_bytes << ","
        << "\"skipped\":" << skipped_json(stats.skipped)
        << "}";
    return out.str();
}

static std::string device_lost_payload(const RendererStats& stats, const std::string& stage) {
    std::ostringstream out;
    out << "{"
        << "\"event\":\"device_lost\","
        << "\"backend\":\"D3D11\","
        << "\"message\":\"Native D3D11 device lost during " << json_escape(stage) << "\","
        << "\"stage\":\"" << json_escape(stage) << "\","
        << "\"device_lost\":true,"
        << "\"device_loss_hresult\":\"" << json_escape(stats.device_loss_hresult) << "\","
        << "\"device_removed_reason\":\"" << json_escape(stats.device_removed_reason) << "\","
        << "\"frame_count\":" << stats.frame_count << ","
        << "\"render_request_count\":" << stats.render_request_count << ","
        << "\"present_failure_count\":" << stats.present_failure_count << ","
        << "\"resize_failure_count\":" << stats.resize_failure_count << ","
        << "\"resize_failure_hresult\":\"" << json_escape(stats.resize_failure_hresult) << "\","
        << "\"resize_failure_reason\":\"" << json_escape(stats.resize_failure_reason) << "\""
        << "}";
    return out.str();
}

static std::string cleared_payload(const RendererStats& stats) {
    std::ostringstream out;
    out << "{"
        << "\"event\":\"cleared\","
        << "\"backend\":\"D3D11\","
        << "\"message\":\"Native D3D11 preview cleared\","
        << "\"texture_cache_entries\":" << stats.texture_cache_entries << ","
        << "\"texture_cache_releases\":" << stats.texture_cache_releases << ","
        << "\"estimated_texture_bytes\":" << stats.estimated_texture_bytes << ","
        << "\"texture_cache_bytes\":" << stats.texture_cache_bytes << ","
        << "\"live_texture_bytes\":" << stats.live_texture_bytes << ","
        << "\"process_working_set_bytes\":" << stats.process_working_set_bytes << ","
        << "\"process_private_bytes\":" << stats.process_private_bytes << ","
        << "\"frame_count\":" << stats.frame_count << ","
        << "\"render_request_count\":" << stats.render_request_count << ","
        << "\"render_suppressed_count\":" << stats.render_suppressed_count << ","
        << "\"mesh_edit_selection_event_count\":" << stats.mesh_edit_selection_event_count << ","
        << "\"parent_unresponsive_count\":" << stats.parent_unresponsive_count << ","
        << "\"parent_health\":\"" << json_escape(stats.parent_health) << "\""
        << "}";
    return out.str();
}

static std::string closed_payload(const RendererStats& stats, const std::string& reason) {
    std::ostringstream out;
    out << "{"
        << "\"event\":\"closed\","
        << "\"backend\":\"D3D11\","
        << "\"reason\":\"" << json_escape(reason) << "\","
        << "\"device_lost\":" << (stats.device_lost ? "true" : "false") << ","
        << "\"device_loss_stage\":\"" << json_escape(stats.device_loss_stage) << "\","
        << "\"device_loss_hresult\":\"" << json_escape(stats.device_loss_hresult) << "\","
        << "\"device_removed_reason\":\"" << json_escape(stats.device_removed_reason) << "\","
        << "\"texture_cache_entries\":" << stats.texture_cache_entries << ","
        << "\"texture_cache_releases\":" << stats.texture_cache_releases << ","
        << "\"estimated_texture_bytes\":" << stats.estimated_texture_bytes << ","
        << "\"process_working_set_bytes\":" << stats.process_working_set_bytes << ","
        << "\"process_private_bytes\":" << stats.process_private_bytes << ","
        << "\"frame_count\":" << stats.frame_count << ","
        << "\"render_request_count\":" << stats.render_request_count << ","
        << "\"render_suppressed_count\":" << stats.render_suppressed_count << ","
        << "\"mesh_edit_selection_event_count\":" << stats.mesh_edit_selection_event_count << ","
        << "\"parent_unresponsive_count\":" << stats.parent_unresponsive_count << ","
        << "\"parent_health\":\"" << json_escape(stats.parent_health) << "\""
        << "}";
    return out.str();
}

static HRESULT compile_shader(const char* source, const char* entry, const char* target, ID3DBlob** blob, std::string& error_text) {
    UINT flags = D3DCOMPILE_ENABLE_STRICTNESS;
#if defined(_DEBUG)
    flags |= D3DCOMPILE_DEBUG;
#endif
    ComPtr<ID3DBlob> errors;
    HRESULT hr = D3DCompile(source, strlen(source), nullptr, nullptr, nullptr, entry, target, flags, 0, blob, errors.GetAddressOf());
    if (FAILED(hr) && errors) {
        error_text.assign(static_cast<const char*>(errors->GetBufferPointer()), errors->GetBufferSize());
    }
    return hr;
}

static HRESULT compile_shader(const std::string& source, const char* entry, const char* target, ID3DBlob** blob, std::string& error_text) {
    return compile_shader(source.c_str(), entry, target, blob, error_text);
}
