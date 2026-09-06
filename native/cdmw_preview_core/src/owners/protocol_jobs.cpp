static std::uint16_t read_u16(const std::vector<char>& data, size_t offset) {
    if (offset + 2 > data.size()) throw std::runtime_error("u16 read outside buffer");
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint16_t>(p[0] | (p[1] << 8));
}

static std::int16_t read_i16(const std::vector<char>& data, size_t offset) {
    return static_cast<std::int16_t>(read_u16(data, offset));
}

static std::uint32_t read_u32(const std::vector<char>& data, size_t offset) {
    if (offset + 4 > data.size()) throw std::runtime_error("u32 read outside buffer");
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint32_t>(p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24));
}

static float read_f32(const std::vector<char>& data, size_t offset) {
    std::uint32_t raw = read_u32(data, offset);
    float value = 0.0f;
    std::memcpy(&value, &raw, sizeof(float));
    return value;
}

static float half_to_float(std::uint16_t value) {
    const std::uint32_t sign = (static_cast<std::uint32_t>(value & 0x8000u)) << 16;
    std::uint32_t exponent = (value >> 10) & 0x1Fu;
    std::uint32_t mantissa = value & 0x03FFu;
    std::uint32_t out = 0;
    if (exponent == 0) {
        if (mantissa == 0) {
            out = sign;
        } else {
            exponent = 1;
            while ((mantissa & 0x0400u) == 0) {
                mantissa <<= 1;
                --exponent;
            }
            mantissa &= 0x03FFu;
            out = sign | ((exponent + 127 - 15) << 23) | (mantissa << 13);
        }
    } else if (exponent == 31) {
        out = sign | 0x7F800000u | (mantissa << 13);
    } else {
        out = sign | ((exponent + 127 - 15) << 23) | (mantissa << 13);
    }
    float result = 0.0f;
    std::memcpy(&result, &out, sizeof(float));
    return std::isfinite(result) ? result : 0.0f;
}

static std::string read_c_string(const std::vector<char>& data, size_t offset, size_t max_length) {
    if (offset >= data.size()) return "";
    const size_t limit = std::min(data.size(), offset + max_length);
    size_t end = offset;
    while (end < limit && data[end] != '\0') ++end;
    if (end <= offset) return "";
    std::string out(data.data() + offset, data.data() + end);
    out.erase(std::remove_if(out.begin(), out.end(), [](unsigned char ch) {
        return ch < 0x20 || ch > 0x7E;
    }), out.end());
    return out;
}

static bool looks_like_dds_string(const std::vector<char>& data, size_t offset, size_t max_length = 256) {
    if (offset >= data.size()) return false;
    if (offset > 0) {
        const unsigned char previous = static_cast<unsigned char>(data[offset - 1]);
        if (previous >= 32 && previous <= 126) return false;
    }
    const size_t limit = std::min(data.size(), offset + max_length);
    size_t end = offset;
    while (end < limit && data[end] != '\0') ++end;
    const size_t length = end - offset;
    if (length <= 4 || length > 255) return false;
    std::string text(data.data() + offset, data.data() + end);
    return lower_copy(text).ends_with(".dds");
}

EntryJob parse_job(const fs::path& job_path) {
    const std::string text = read_text(job_path);
    EntryJob job;
    job.output_root = fs::path(find_string_value(text, "output_root"));
    job.cache_root = fs::path(find_string_value(text, "cache_root"));
    job.package_root = fs::path(find_string_value(text, "package_root"));
    job.archive_index_path = fs::path(find_string_value(text, "archive_index_path"));
    job.archive_basename_index_path = fs::path(find_string_value(text, "archive_basename_index_path"));
    job.schema_version = static_cast<int>(std::max<long long>(1, find_int_value(text, "schema_version", 4)));
    const std::string entry_object = find_object_value(text, "entry");
    job.entry = parse_archive_entry_ref(entry_object.empty() ? text : entry_object);
    const std::string companion_object = find_object_value(text, "companion_entry");
    job.companion_entry = parse_archive_entry_ref(companion_object);
    bool dependency_entries_truncated = false;
    for (const std::string& dependency_object : find_object_array_values(
             text,
             "archive_dependency_entries",
             4096,
             dependency_entries_truncated)) {
        job.archive_dependency_entries.push_back(parse_archive_entry_ref(dependency_object));
    }
    job.archive_dependency_entries_complete = find_bool_value(
        text,
        "archive_dependency_entries_complete",
        false);
    if (job.archive_dependency_entries_complete && dependency_entries_truncated) {
        throw std::runtime_error("archive dependency entries exceeded the 4,096-entry safety bound");
    }
    bool prefab_components_truncated = false;
    job.enabled_prefab_component_paths = find_string_array_values(
        text,
        "enabled_prefab_component_paths",
        32,
        prefab_components_truncated);
    if (prefab_components_truncated) {
        throw std::runtime_error("enabled prefab component paths exceeded the 32-entry safety bound");
    }
    bool model_property_indices_truncated = false;
    for (const std::string& selection_object : find_object_array_values(
             text,
             "model_property_indices",
             32,
             model_property_indices_truncated)) {
        std::string path = find_string_value(selection_object, "path");
        std::replace(path.begin(), path.end(), '\\', '/');
        path = lower_copy(path);
        const long long index = find_int_value(selection_object, "index", -1);
        if (path.empty() || index < 0 || index > 255) {
            throw std::runtime_error("model property selection has an invalid path or index");
        }
        job.model_property_indices.emplace(path, static_cast<int>(index));
    }
    if (model_property_indices_truncated) {
        throw std::runtime_error("model property selections exceeded the 32-entry safety bound");
    }
    bool context_components_truncated = false;
    for (const std::string& component_object : find_object_array_values(text, "preview_context_components", 32, context_components_truncated)) {
        job.preview_context_components.push_back(parse_preview_context_component_ref(component_object));
    }
    if (context_components_truncated) {
        throw std::runtime_error("preview context components exceeded the 32-entry safety bound");
    }
    job.presentation_geometry_path = fs::path(find_string_value(text, "presentation_geometry_path"));
    job.presentation_geometry_source = find_string_value(text, "presentation_geometry_source");
    job.path = job.entry.path;
    job.extension = job.entry.extension.empty() ? basename_extension(job.path) : job.entry.extension;
    job.paz_file = job.entry.paz_file;
    job.offset = job.entry.offset;
    job.comp_size = job.entry.comp_size;
    job.orig_size = job.entry.orig_size;
    job.flags = job.entry.flags;
    const std::string render_settings = find_object_value(text, "render_settings");
    if (!render_settings.empty()) {
        const std::string native_visible_mode = find_string_value(render_settings, "visible_texture_mode");
        if (!native_visible_mode.empty()) job.visible_texture_mode = normalize_visible_texture_mode(native_visible_mode);
        const std::string diagnostic_mode = lower_copy(find_string_value(render_settings, "render_diagnostic_mode"));
        if (!diagnostic_mode.empty()) job.render_diagnostic_mode = diagnostic_mode;
        const std::string d3d11_view_mode = lower_copy(find_string_value(render_settings, "d3d11_view_mode"));
        if (!d3d11_view_mode.empty()) job.d3d11_view_mode = d3d11_view_mode;
        const std::string d3d11_normal_y_mode = lower_copy(find_string_value(render_settings, "d3d11_normal_y_mode"));
        if (!d3d11_normal_y_mode.empty()) job.d3d11_normal_y_mode = d3d11_normal_y_mode;
        const std::string d3d11_texture_address_mode = lower_copy(find_string_value(render_settings, "d3d11_texture_address_mode"));
        if (d3d11_texture_address_mode == "clamp") job.d3d11_texture_address_mode = "clamp";
        else if (d3d11_texture_address_mode == "wrap") job.d3d11_texture_address_mode = "wrap";
        job.use_textures = find_bool_value(render_settings, "use_textures_by_default", job.use_textures);
        job.high_quality_textures = find_bool_value(render_settings, "high_quality_by_default", job.high_quality_textures);
        job.disable_all_support_maps = find_bool_value(render_settings, "disable_all_support_maps", job.disable_all_support_maps);
        job.disable_normal_map = find_bool_value(render_settings, "disable_normal_map", job.disable_normal_map);
        job.disable_material_map = find_bool_value(render_settings, "disable_material_map", job.disable_material_map);
        job.disable_height_map = find_bool_value(render_settings, "disable_height_map", job.disable_height_map);
        job.flip_texture_v = find_bool_value(render_settings, "flip_texture_v", job.flip_texture_v);
        job.normal_strength_cap = std::clamp(find_float_value(render_settings, "normal_strength_cap", job.normal_strength_cap), 0.0f, 2.0f);
        job.height_effect_max = std::clamp(find_float_value(render_settings, "height_effect_max", job.height_effect_max), 0.0f, 1.5f);
        job.max_anisotropy = static_cast<int>(std::clamp<long long>(find_int_value(render_settings, "max_anisotropy", job.max_anisotropy), 1, 16));
        job.d3d11_mip_lod_bias = std::clamp(find_float_value(render_settings, "d3d11_mip_lod_bias", job.d3d11_mip_lod_bias), -2.0f, 1.0f);
        job.d3d11_cull_back_faces = find_bool_value(render_settings, "d3d11_cull_back_faces", job.d3d11_cull_back_faces);
        job.d3d11_light_azimuth_degrees = std::clamp(find_float_value(render_settings, "d3d11_light_azimuth_degrees", job.d3d11_light_azimuth_degrees), -180.0f, 180.0f);
        job.d3d11_light_elevation_degrees = std::clamp(find_float_value(render_settings, "d3d11_light_elevation_degrees", job.d3d11_light_elevation_degrees), -80.0f, 80.0f);
        job.d3d11_ao_strength = std::clamp(find_float_value(render_settings, "d3d11_ao_strength", job.d3d11_ao_strength), 0.0f, 2.0f);
        job.d3d11_roughness_bias = std::clamp(find_float_value(render_settings, "d3d11_roughness_bias", job.d3d11_roughness_bias), -0.5f, 0.5f);
        job.d3d11_metalness_scale = std::clamp(find_float_value(render_settings, "d3d11_metalness_scale", job.d3d11_metalness_scale), 0.0f, 2.0f);
        job.d3d11_environment_strength = std::clamp(find_float_value(render_settings, "d3d11_environment_strength", job.d3d11_environment_strength), 0.0f, 2.0f);
        job.d3d11_emissive_gain = std::clamp(find_float_value(render_settings, "d3d11_emissive_gain", job.d3d11_emissive_gain), 0.0f, 4.0f);
        job.d3d11_tone_exposure = std::clamp(find_float_value(render_settings, "d3d11_tone_exposure", job.d3d11_tone_exposure), 0.25f, 2.0f);
        job.d3d11_tone_contrast = std::clamp(find_float_value(render_settings, "d3d11_tone_contrast", job.d3d11_tone_contrast), 0.50f, 1.75f);
        job.d3d11_tone_gamma = std::clamp(find_float_value(render_settings, "d3d11_tone_gamma", job.d3d11_tone_gamma), 0.50f, 2.20f);
        job.ambient_strength = std::clamp(find_float_value(render_settings, "ambient_strength", job.ambient_strength), 0.05f, 1.2f);
        job.diffuse_wrap_bias = std::clamp(find_float_value(render_settings, "diffuse_wrap_bias", job.diffuse_wrap_bias), 0.0f, 1.0f);
        job.diffuse_light_scale = std::clamp(find_float_value(render_settings, "diffuse_light_scale", job.diffuse_light_scale), 0.05f, 1.5f);
        job.specular_base = std::clamp(find_float_value(render_settings, "specular_base", job.specular_base), 0.0f, 0.5f);
        job.specular_max = std::clamp(find_float_value(render_settings, "specular_max", job.specular_max), job.specular_base, 1.0f);
        job.shininess_min = std::clamp(find_float_value(render_settings, "shininess_min", job.shininess_min), 1.0f, 128.0f);
        job.shininess_max = std::clamp(find_float_value(render_settings, "shininess_max", job.shininess_max), job.shininess_min, 256.0f);
        job.orbit_sensitivity = std::clamp(find_float_value(render_settings, "orbit_sensitivity", job.orbit_sensitivity), 0.001f, 8.0f);
        job.pan_sensitivity = std::clamp(find_float_value(render_settings, "pan_sensitivity", job.pan_sensitivity), 0.001f, 8.0f);
        job.invert_orbit_x = find_bool_value(render_settings, "invert_orbit_x", job.invert_orbit_x);
        job.invert_orbit_y = find_bool_value(render_settings, "invert_orbit_y", job.invert_orbit_y);
        job.invert_pan_x = find_bool_value(render_settings, "invert_pan_x", job.invert_pan_x);
        job.invert_pan_y = find_bool_value(render_settings, "invert_pan_y", job.invert_pan_y);
    }
    if (job.output_root.empty()) job.output_root = fs::temp_directory_path() / "cdmw_preview_core_package";
    if (job.cache_root.empty()) job.cache_root = fs::temp_directory_path() / "cdmw_preview_core_cache";
    return job;
}
