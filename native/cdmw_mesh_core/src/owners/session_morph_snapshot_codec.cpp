std::string mesh_editor_morph_topology_digest(const MeshEditorSession& session) {
    std::ostringstream out;
    out << '[';
    bool wrote_submesh = false;
    for (const auto& item : mesh_editor_submeshes(session)) {
        if (wrote_submesh) out << ',';
        wrote_submesh = true;
        out << "{\"faces\":[";
        bool wrote_face = false;
        for (const auto& face : item.second.faces) {
            if (wrote_face) out << ',';
            wrote_face = true;
            out << '[' << face[0] << ',' << face[1] << ',' << face[2] << ']';
        }
        out << "],\"index\":" << item.first
            << ",\"vertex_count\":" << item.second.vertices.size() << '}';
    }
    out << ']';
    return mesh_editor_snapshot_sha256(out.str());
}

void mesh_editor_write_snapshot_vec3(std::ostream& out, const Vec3& value) {
    out << '[' << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2] << ']';
}

void mesh_editor_write_snapshot_vec3s(std::ostream& out, const std::vector<Vec3>& values) {
    out << '[';
    bool wrote = false;
    for (const Vec3& value : values) {
        if (wrote) out << ',';
        wrote = true;
        mesh_editor_write_snapshot_vec3(out, value);
    }
    out << ']';
}

void mesh_editor_write_snapshot_profile(std::ostream& out, const MeshMorphRuntime& morph) {
    if (!morph.profile) {
        out << "null";
        return;
    }
    out << "{\"profile_id\":";
    write_escaped(out, morph.profile->profile_id);
    out << ",\"name\":";
    write_escaped(out, morph.profile->name);
    out << ",\"topology_fingerprint\":";
    write_escaped(out, morph.profile->topology_fingerprint);
    out << ",\"definitions\":[";
    bool wrote_definition = false;
    for (const auto& item : morph.profile->definitions) {
        if (wrote_definition) out << ',';
        wrote_definition = true;
        const MeshMorphDefinitionRuntime& definition = item.second;
        out << "{\"definition_id\":";
        write_escaped(out, definition.definition_id);
        out << ",\"label\":";
        write_escaped(out, definition.label);
        out << ",\"category\":";
        write_escaped(out, definition.category);
        out << ",\"min_percent\":" << std::setprecision(17) << definition.min_percent
            << ",\"max_percent\":" << definition.max_percent
            << ",\"default_percent\":" << definition.default_percent << '}';
    }
    out << "],\"fields\":[";
    bool wrote_field = false;
    for (const auto& definition_item : morph.profile->definitions) {
        for (const bool post_refit : {false, true}) {
        const auto& fields = post_refit ? definition_item.second.post_refit_fields : definition_item.second.fields;
        for (const auto& field_item : fields) {
            if (wrote_field) out << ',';
            wrote_field = true;
            out << "{\"definition_id\":";
            write_escaped(out, definition_item.first);
            if (post_refit) out << ",\"stage\":\"post_refit\"";
            out << ",\"submesh_index\":" << field_item.first << ",\"vertex_indices\":[";
            bool wrote_index = false;
            for (const int vertex_index : field_item.second.vertex_indices) {
                if (wrote_index) out << ',';
                wrote_index = true;
                out << vertex_index;
            }
            out << "],\"deltas\":";
            mesh_editor_write_snapshot_vec3s(out, field_item.second.deltas);
            out << '}';
        }
        }
    }
    out << "]}";
}

void mesh_editor_write_snapshot_refit(std::ostream& out, const MeshMorphRuntime& morph) {
    if (!morph.refit) {
        out << "null";
        return;
    }
    const MeshRefitRuntime& refit = *morph.refit;
    out << "{\"driver_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, refit.driver_submesh_indices);
    out << ",\"garment_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, refit.garment_submesh_indices);
    out << ",\"driver_baseline_positions\":[";
    bool wrote_baseline = false;
    for (const auto& item : refit.driver_baseline_positions) {
        if (wrote_baseline) out << ',';
        wrote_baseline = true;
        out << "{\"submesh_index\":" << item.first << ",\"positions\":";
        mesh_editor_write_snapshot_vec3s(out, item.second);
        out << '}';
    }
    out << "],\"bindings\":[";
    bool wrote_binding = false;
    for (const MeshRefitVertexBindingRuntime& binding : refit.bindings) {
        if (wrote_binding) out << ',';
        wrote_binding = true;
        out << "{\"garment_submesh_index\":" << binding.garment_submesh_index
            << ",\"garment_vertex_index\":" << binding.garment_vertex_index
            << ",\"driver_submesh_index\":" << binding.driver_submesh_index
            << ",\"driver_vertices\":[" << binding.driver_vertices[0] << ','
            << binding.driver_vertices[1] << ',' << binding.driver_vertices[2]
            << "],\"barycentric\":[" << std::setprecision(17) << binding.barycentric[0] << ','
            << binding.barycentric[1] << ',' << binding.barycentric[2]
            << "],\"distance\":" << binding.distance << ",\"baseline_normal\":";
        mesh_editor_write_snapshot_vec3(out, binding.baseline_normal);
        out << ",\"normal_height\":" << binding.normal_height << ",\"rigid_local_offset\":";
        mesh_editor_write_snapshot_vec3(out, binding.rigid_local_offset);
        out << ",\"rigid_frame_valid\":" << (binding.rigid_frame_valid ? "true" : "false") << '}';
    }
    out << "],\"garment_settings\":[";
    bool wrote_settings = false;
    for (const auto& item : refit.garment_settings) {
        if (wrote_settings) out << ',';
        wrote_settings = true;
        out << "{\"submesh_index\":" << item.first
            << ",\"enabled\":" << (item.second.enabled ? "true" : "false")
            << ",\"intensity_percent\":" << std::setprecision(17) << item.second.intensity_percent
            << ",\"mode\":";
        write_escaped(out, item.second.mode);
        out << ",\"clearance_percent\":" << item.second.clearance_percent
            << ",\"tightness_percent\":" << item.second.tightness_percent
            << ",\"tightness_initialized\":" << (item.second.tightness_initialized ? "true" : "false");
        mesh_editor_write_refit_island_settings(out,item.second);
        out << '}';
    }
    out << "],\"driver_diagonal\":" << std::setprecision(17) << refit.driver_diagonal
        << ",\"maximum_distance\":" << refit.maximum_distance
        << ",\"p95_distance\":" << refit.p95_distance
        << ",\"warning_distance\":" << refit.warning_distance
        << ",\"distance_warning\":" << (refit.distance_warning ? "true" : "false")
        << ",\"driver_triangle_count\":" << refit.driver_triangle_count
        << ",\"candidate_triangle_tests\":" << refit.candidate_triangle_tests;
    mesh_editor_write_refit_constraints(out, refit);
    mesh_editor_write_refit_exclusions(out, refit);
    if (refit.reference_body) {
        out << ",\"reference_body\":";
        mesh_editor_write_refit_reference(out, *refit.reference_body);
    }
    if (refit.weight_transfer) {
        out << ",\"weight_transfer\":";
        mesh_editor_write_refit_weight_transfer(out, *refit.weight_transfer);
    }
    out << '}';
}

std::string mesh_editor_morph_runtime_snapshot_payload(const MeshEditorSession& session) {
    const MeshMorphRuntime empty;
    const MeshMorphRuntime& morph = session.morph ? *session.morph : empty;
    std::ostringstream out;
    out << "{\"profile\":";
    mesh_editor_write_snapshot_profile(out, morph);
    out << ",\"preset_id\":";
    write_escaped(out, morph.preset_id);
    out << ",\"values\":{";
    bool wrote_value = false;
    for (const auto& item : morph.values) {
        if (wrote_value) out << ',';
        wrote_value = true;
        write_escaped(out, item.first);
        out << ':' << std::setprecision(17) << item.second;
    }
    out << "},\"current_layer\":[";
    bool wrote_layer = false;
    for (const auto& item : morph.current_layer) {
        if (wrote_layer) out << ',';
        wrote_layer = true;
        out << "{\"submesh_index\":" << item.first << ",\"deltas\":";
        mesh_editor_write_snapshot_vec3s(out, item.second);
        out << '}';
    }
    out << "],\"neutral_positions\":[";
    std::set<int> neutral_indices;
    for (const auto& item : morph.current_layer) neutral_indices.insert(item.first);
    for (const auto& item : morph.neutral_positions) neutral_indices.insert(item.first);
    const auto& submeshes = mesh_editor_submeshes(session);
    const auto neutral = mesh_editor_morph_residual_positions(morph, submeshes, neutral_indices);
    bool wrote_neutral = false;
    for (const auto& item : neutral) {
        if (wrote_neutral) out << ',';
        wrote_neutral = true;
        out << "{\"submesh_index\":" << item.first << ",\"positions\":";
        mesh_editor_write_snapshot_vec3s(out, item.second);
        out << ",\"composed_positions\":";
        mesh_editor_write_snapshot_vec3s(out, submeshes.at(item.first).vertices);
        if (const auto normals = morph.neutral_normals.find(item.first); normals != morph.neutral_normals.end()) {
            out << ",\"neutral_normals\":";
            mesh_editor_write_snapshot_vec3s(out, *normals->second);
        }
        out << '}';
    }
    out << "],\"driver_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, morph.driver_submesh_indices);
    out << ",\"refit\":";
    mesh_editor_write_snapshot_refit(out, morph);
    mesh_editor_write_snapshot_neutral_bones(out, morph);
    out << ",\"unbaked\":" << (morph.unbaked ? "true" : "false")
        << ",\"state_revision\":" << morph.state_revision
        << ",\"change_id\":";
    write_escaped(out, morph.change_id);
    out << ",\"active_change_id\":";
    write_escaped(out, morph.active_change_id);
    out << ",\"active_definition_id\":";
    write_escaped(out, morph.active_definition_id);
    out << ",\"active_change_update_count\":" << morph.active_change_update_count << '}';
    return out.str();
}

const JsonValue& mesh_editor_snapshot_required_member(
    const JsonValue& object,
    const std::string& key,
    JsonValue::Type type
) {
    const JsonValue* value = object.get(key);
    if (value == nullptr || value->type != type) {
        throw std::runtime_error("morph runtime snapshot has invalid " + key);
    }
    return *value;
}

double mesh_editor_snapshot_number(const JsonValue& object, const std::string& key) {
    const JsonValue& value = mesh_editor_snapshot_required_member(object, key, JsonValue::Type::Number);
    if (!std::isfinite(value.number_value)) {
        throw std::runtime_error("morph runtime snapshot has non-finite " + key);
    }
    return value.number_value;
}

long long mesh_editor_snapshot_integer(
    const JsonValue& object,
    const std::string& key,
    long long minimum = 0
) {
    const double value = mesh_editor_snapshot_number(object, key);
    constexpr double exact_integer_limit = 9007199254740991.0;
    if (std::floor(value) != value || value < static_cast<double>(minimum) || value > exact_integer_limit) {
        throw std::runtime_error("morph runtime snapshot has invalid integer " + key);
    }
    return static_cast<long long>(value);
}

bool mesh_editor_snapshot_bool(const JsonValue& object, const std::string& key) {
    return mesh_editor_snapshot_required_member(object, key, JsonValue::Type::Bool).bool_value;
}

std::string mesh_editor_snapshot_string(const JsonValue& object, const std::string& key) {
    return mesh_editor_snapshot_required_member(object, key, JsonValue::Type::String).string_value;
}

Vec3 mesh_editor_snapshot_vec3(const JsonValue& value, const std::string& label) {
    if (value.type != JsonValue::Type::Array || value.array_value.size() != 3) {
        throw std::runtime_error("morph runtime snapshot has invalid " + label);
    }
    Vec3 result{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        if (value.array_value[axis].type != JsonValue::Type::Number
            || !std::isfinite(value.array_value[axis].number_value)) {
            throw std::runtime_error("morph runtime snapshot has non-finite " + label);
        }
        result[axis] = value.array_value[axis].number_value;
    }
    return result;
}

std::vector<Vec3> mesh_editor_snapshot_vec3s(const JsonValue& value, const std::string& label) {
    if (value.type != JsonValue::Type::Array) {
        throw std::runtime_error("morph runtime snapshot has invalid " + label);
    }
    std::vector<Vec3> result;
    result.reserve(value.array_value.size());
    for (const JsonValue& item : value.array_value) {
        result.push_back(mesh_editor_snapshot_vec3(item, label));
    }
    return result;
}

std::set<int> mesh_editor_snapshot_submesh_set(
    const JsonValue& value,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::string& label,
    bool allow_empty
) {
    if (value.type != JsonValue::Type::Array) {
        throw std::runtime_error("morph runtime snapshot has invalid " + label);
    }
    std::set<int> result;
    for (const JsonValue& item : value.array_value) {
        int index = -1;
        if (!strict_int_or(&item, index) || index < 0 || submeshes.find(index) == submeshes.end()
            || !result.insert(index).second) {
            throw std::runtime_error("morph runtime snapshot has invalid " + label);
        }
    }
    if (!allow_empty && result.empty()) {
        throw std::runtime_error("morph runtime snapshot has empty " + label);
    }
    return result;
}

static void restore_refit_driver_baselines(const JsonValue* raw_refit, const std::map<int, MeshSessionSubmesh>& submeshes, const std::shared_ptr<MeshRefitRuntime>& refit) {
    const JsonValue& raw_baselines = mesh_editor_snapshot_required_member(
        *raw_refit, "driver_baseline_positions", JsonValue::Type::Array
    );
    for (const JsonValue& item : raw_baselines.array_value) {
        if (item.type != JsonValue::Type::Object) {
            throw std::runtime_error("morph runtime snapshot has invalid driver baseline");
        }
        int submesh_index = -1;
        if (!strict_int_or(item.get("submesh_index"), submesh_index)
            || refit->driver_submesh_indices.find(submesh_index) == refit->driver_submesh_indices.end()) {
            throw std::runtime_error("morph runtime snapshot has invalid driver baseline submesh");
        }
        std::vector<Vec3> positions = mesh_editor_snapshot_vec3s(
            mesh_editor_snapshot_required_member(item, "positions", JsonValue::Type::Array),
            "driver baseline positions"
        );
        const auto source = submeshes.find(submesh_index);
        if (source == submeshes.end() || positions.size() != source->second.vertices.size()
            || !refit->driver_baseline_positions.emplace(submesh_index, std::move(positions)).second) {
            throw std::runtime_error("morph runtime snapshot driver baseline topology does not match");
        }
    }
    if (refit->driver_baseline_positions.size() != refit->driver_submesh_indices.size()) {
        throw std::runtime_error("morph runtime snapshot is missing a driver baseline");
    }
}

std::shared_ptr<const MeshRefitRuntime> mesh_editor_refit_from_snapshot(
    const JsonValue* raw_refit,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::set<int>& runtime_drivers,
    int version
) {
    if (raw_refit == nullptr || raw_refit->type == JsonValue::Type::Null) return {};
    if (raw_refit->type != JsonValue::Type::Object) {
        throw std::runtime_error("morph runtime snapshot has invalid refit state");
    }
    auto refit = std::make_shared<MeshRefitRuntime>();
    refit->driver_submesh_indices = mesh_editor_snapshot_submesh_set(
        mesh_editor_snapshot_required_member(*raw_refit, "driver_submesh_indices", JsonValue::Type::Array),
        submeshes,
        "refit driver submeshes",
        false
    );
    if (refit->driver_submesh_indices != runtime_drivers) {
        throw std::runtime_error("morph runtime snapshot refit driver set does not match its runtime driver set");
    }
    refit->garment_submesh_indices = mesh_editor_snapshot_submesh_set(
        mesh_editor_snapshot_required_member(*raw_refit, "garment_submesh_indices", JsonValue::Type::Array),
        submeshes,
        "refit garment submeshes",
        false
    );
    for (const int index : refit->garment_submesh_indices) {
        if (refit->driver_submesh_indices.find(index) != refit->driver_submesh_indices.end()) {
            throw std::runtime_error("morph runtime snapshot refit driver and garment sets overlap");
        }
    }
    restore_refit_driver_baselines(raw_refit, submeshes, refit);
    // Version 4 exists only for exclusions; version 5 (a reference body) may have none.
    if (version == 4 || (version >= 5 && raw_refit->get("excluded_faces")))
        mesh_editor_read_refit_exclusions(*refit,&mesh_editor_snapshot_required_member(
            *raw_refit,"excluded_faces",JsonValue::Type::Array),submeshes);
    else if (raw_refit->get("excluded_faces"))
        throw std::runtime_error("Fitting output exclusions require runtime snapshot version 4");
    refit_read_vertex_masks_native(*refit, raw_refit->get("vertex_masks"), submeshes, refit->garment_submesh_indices);
    if (const auto* raw_regions = raw_refit->get("garment_regions")) {
        if (raw_regions->type != JsonValue::Type::Array) throw std::runtime_error("invalid refit garment regions");
        for (const auto& item : raw_regions->array_value) {
            int index = -1;
            if (item.type != JsonValue::Type::Object || !strict_int_or(item.get("garment_submesh_index"), index)
                || !refit->garment_submesh_indices.count(index) || refit->garment_regions.count(index)
                || !item.get("driver_regions")) throw std::runtime_error("invalid refit garment region target");
            refit->garment_regions[index] = refit_regions_from_json_native(
                item.get("driver_regions"), submeshes, refit->driver_submesh_indices);
        }
    }
    const JsonValue& raw_bindings = mesh_editor_snapshot_required_member(
        *raw_refit, "bindings", JsonValue::Type::Array
    );
    std::set<std::pair<int, int>> bound_vertices;
    refit->bindings.reserve(raw_bindings.array_value.size());
    for (const JsonValue& item : raw_bindings.array_value) {
        if (item.type != JsonValue::Type::Object) {
            throw std::runtime_error("morph runtime snapshot has invalid refit binding");
        }
        MeshRefitVertexBindingRuntime binding;
        if (!strict_int_or(item.get("garment_submesh_index"), binding.garment_submesh_index)
            || !strict_int_or(item.get("garment_vertex_index"), binding.garment_vertex_index)
            || !strict_int_or(item.get("driver_submesh_index"), binding.driver_submesh_index)) {
            throw std::runtime_error("morph runtime snapshot has invalid refit binding indices");
        }
        const auto garment = submeshes.find(binding.garment_submesh_index);
        const auto driver = submeshes.find(binding.driver_submesh_index);
        if (refit->garment_submesh_indices.find(binding.garment_submesh_index)
                == refit->garment_submesh_indices.end()
            || refit->driver_submesh_indices.find(binding.driver_submesh_index)
                == refit->driver_submesh_indices.end()
            || garment == submeshes.end() || driver == submeshes.end()
            || binding.garment_vertex_index < 0
            || static_cast<std::size_t>(binding.garment_vertex_index) >= garment->second.vertices.size()
            || !bound_vertices.emplace(binding.garment_submesh_index, binding.garment_vertex_index).second) {
            throw std::runtime_error("morph runtime snapshot refit binding topology does not match");
        }
        const JsonValue& raw_vertices = mesh_editor_snapshot_required_member(
            item, "driver_vertices", JsonValue::Type::Array
        );
        const JsonValue& raw_barycentric = mesh_editor_snapshot_required_member(
            item, "barycentric", JsonValue::Type::Array
        );
        if (raw_vertices.array_value.size() != 3 || raw_barycentric.array_value.size() != 3) {
            throw std::runtime_error("morph runtime snapshot refit binding triangle is invalid");
        }
        for (std::size_t corner = 0; corner < 3; ++corner) {
            if (!strict_int_or(&raw_vertices.array_value[corner], binding.driver_vertices[corner])
                || binding.driver_vertices[corner] < 0
                || static_cast<std::size_t>(binding.driver_vertices[corner]) >= driver->second.vertices.size()
                || raw_barycentric.array_value[corner].type != JsonValue::Type::Number
                || !std::isfinite(raw_barycentric.array_value[corner].number_value)) {
                throw std::runtime_error("morph runtime snapshot refit binding triangle is invalid");
            }
            binding.barycentric[corner] = raw_barycentric.array_value[corner].number_value;
        }
        const auto restriction = refit->garment_regions.find(binding.garment_submesh_index);
        if (restriction != refit->garment_regions.end()) {
            const auto allowed = restriction->second.find(binding.driver_submesh_index);
            if (allowed == restriction->second.end()
                || !allowed->second.count(binding.driver_vertices[0])
                || !allowed->second.count(binding.driver_vertices[1])
                || !allowed->second.count(binding.driver_vertices[2])) {
                throw std::runtime_error("refit binding escaped its allowed driver region");
            }
        }
        binding.distance = mesh_editor_snapshot_number(item, "distance");
        binding.baseline_normal = mesh_editor_snapshot_vec3(
            mesh_editor_snapshot_required_member(item, "baseline_normal", JsonValue::Type::Array),
            "refit baseline normal"
        );
        binding.normal_height = mesh_editor_snapshot_number(item, "normal_height");
        binding.rigid_local_offset = mesh_editor_snapshot_vec3(
            mesh_editor_snapshot_required_member(item, "rigid_local_offset", JsonValue::Type::Array),
            "refit rigid local offset"
        );
        binding.rigid_frame_valid = mesh_editor_snapshot_bool(item, "rigid_frame_valid");
        refit->bindings.push_back(binding);
    }
    std::size_t expected_binding_count = 0;
    for (const int index : refit->garment_submesh_indices) {
        expected_binding_count += submeshes.at(index).vertices.size();
    }
    if (refit->bindings.size() != expected_binding_count) {
        throw std::runtime_error("morph runtime snapshot is missing garment refit bindings");
    }
    const JsonValue& raw_settings = mesh_editor_snapshot_required_member(
        *raw_refit, "garment_settings", JsonValue::Type::Array
    );
    for (const JsonValue& item : raw_settings.array_value) {
        if (item.type != JsonValue::Type::Object) {
            throw std::runtime_error("morph runtime snapshot has invalid garment settings");
        }
        int submesh_index = -1;
        if (!strict_int_or(item.get("submesh_index"), submesh_index)
            || refit->garment_submesh_indices.find(submesh_index) == refit->garment_submesh_indices.end()) {
            throw std::runtime_error("morph runtime snapshot garment settings topology does not match");
        }
        MeshRefitGarmentSettingsRuntime settings;
        settings.enabled = mesh_editor_snapshot_bool(item, "enabled");
        settings.intensity_percent = mesh_editor_snapshot_number(item, "intensity_percent");
        settings.mode = mesh_editor_snapshot_string(item, "mode");
        settings.clearance_percent = mesh_editor_snapshot_number(item, "clearance_percent");
        settings.tightness_percent = version >= 2 ? mesh_editor_snapshot_number(item, "tightness_percent") : 0.0;
        settings.tightness_initialized = version >= 2 && item.get("tightness_initialized")
            ? mesh_editor_snapshot_bool(item, "tightness_initialized") : true;
        if (version >= 3) settings = mesh_editor_refit_settings_from_json(item,settings,true);
        else if (item.get("island_settings"))
            throw std::runtime_error("Island fitting requires runtime snapshot version 3");
        if (settings.intensity_percent < 0.0 || settings.intensity_percent > 200.0
            || (settings.mode != "surface" && settings.mode != "rigid" && settings.mode != "rigid_component")
            || settings.clearance_percent < 0.0 || settings.clearance_percent > 5.0
            || settings.tightness_percent < 0.0 || settings.tightness_percent > 100.0
            || !refit->garment_settings.emplace(submesh_index, std::move(settings)).second) {
            throw std::runtime_error("morph runtime snapshot has invalid garment settings");
        }
    }
    if (const auto* reference = raw_refit->get("reference_body")) {
        if (version < 5) throw std::runtime_error("Fit reference bodies require runtime snapshot version 5");
        refit->reference_body = mesh_editor_refit_reference_from_json(*reference);
    }
    if (const auto* transfer = raw_refit->get("weight_transfer")) {
        if (!refit->reference_body) throw std::runtime_error("morph runtime snapshot has weights without a reference body");
        refit->weight_transfer = mesh_editor_refit_weight_transfer_from_json(*transfer, submeshes, *refit);
    }
    refit->driver_diagonal = mesh_editor_snapshot_number(*raw_refit, "driver_diagonal");
    refit->maximum_distance = mesh_editor_snapshot_number(*raw_refit, "maximum_distance");
    refit->p95_distance = mesh_editor_snapshot_number(*raw_refit, "p95_distance");
    refit->warning_distance = mesh_editor_snapshot_number(*raw_refit, "warning_distance");
    refit->distance_warning = mesh_editor_snapshot_bool(*raw_refit, "distance_warning");
    refit->driver_triangle_count = mesh_editor_snapshot_integer(*raw_refit, "driver_triangle_count");
    refit->candidate_triangle_tests = mesh_editor_snapshot_integer(*raw_refit, "candidate_triangle_tests");
    if (refit->driver_diagonal < 0.0 || refit->maximum_distance < 0.0 || refit->p95_distance < 0.0
        || refit->warning_distance < 0.0) {
        throw std::runtime_error("morph runtime snapshot has invalid refit metrics");
    }
    return refit;
}

std::shared_ptr<MeshMorphRuntime> mesh_editor_morph_runtime_from_snapshot(
    const JsonValue& raw_runtime,
    const MeshEditorSession& session,
    int version
) {
    if (raw_runtime.type != JsonValue::Type::Object) {
        throw std::runtime_error("morph runtime snapshot has invalid runtime state");
    }
    const auto& submeshes = mesh_editor_submeshes(session);
    auto runtime = std::make_shared<MeshMorphRuntime>();
    const JsonValue* raw_profile = raw_runtime.get("profile");
    if (raw_profile == nullptr) throw std::runtime_error("morph runtime snapshot is missing its profile");
    if (raw_profile->type != JsonValue::Type::Null) {
        runtime->profile = mesh_editor_morph_profile_from_json(raw_profile, submeshes);
        if (!runtime->profile) throw std::runtime_error("morph runtime snapshot has an empty profile id");
    }
    runtime->preset_id = mesh_editor_snapshot_string(raw_runtime, "preset_id");
    const JsonValue& raw_values = mesh_editor_snapshot_required_member(
        raw_runtime, "values", JsonValue::Type::Object
    );
    for (const auto& item : raw_values.object_value) {
        if (item.second.type != JsonValue::Type::Number || !std::isfinite(item.second.number_value)) {
            throw std::runtime_error("morph runtime snapshot has invalid slider values");
        }
        runtime->values[item.first] = item.second.number_value;
    }
    if (runtime->profile) {
        if (runtime->values.size() != runtime->profile->definitions.size()) {
            throw std::runtime_error("morph runtime snapshot slider values do not match its profile");
        }
        for (const auto& item : runtime->profile->definitions) {
            const auto value = runtime->values.find(item.first);
            if (value == runtime->values.end() || value->second < item.second.min_percent
                || value->second > item.second.max_percent) {
                throw std::runtime_error("morph runtime snapshot slider values do not match its profile");
            }
        }
    } else if (!runtime->values.empty() || !runtime->preset_id.empty()) {
        throw std::runtime_error("morph runtime snapshot has slider state without a profile");
    }
    const JsonValue& raw_layer = mesh_editor_snapshot_required_member(
        raw_runtime, "current_layer", JsonValue::Type::Array
    );
    for (const JsonValue& item : raw_layer.array_value) {
        if (item.type != JsonValue::Type::Object) {
            throw std::runtime_error("morph runtime snapshot has invalid current layer");
        }
        int submesh_index = -1;
        if (!strict_int_or(item.get("submesh_index"), submesh_index)) {
            throw std::runtime_error("morph runtime snapshot has invalid current layer submesh");
        }
        const auto submesh = submeshes.find(submesh_index);
        std::vector<Vec3> deltas = mesh_editor_snapshot_vec3s(
            mesh_editor_snapshot_required_member(item, "deltas", JsonValue::Type::Array),
            "current morph layer"
        );
        if (submesh == submeshes.end() || deltas.size() != submesh->second.vertices.size()
            || !runtime->current_layer.emplace(submesh_index, std::move(deltas)).second) {
            throw std::runtime_error("morph runtime snapshot current layer topology does not match");
        }
    }
    if (const auto* raw_neutral = raw_runtime.get("neutral_positions")) {
        if (raw_neutral->type != JsonValue::Type::Array) {
            throw std::runtime_error("morph runtime snapshot has invalid neutral positions");
        }
        for (const auto& row : raw_neutral->array_value) {
            int index = -1;
            if (row.type != JsonValue::Type::Object || !strict_int_or(row.get("submesh_index"), index)
                || !submeshes.count(index) || runtime->neutral_positions.count(index)) {
                throw std::runtime_error("morph runtime snapshot has invalid neutral submesh");
            }
            auto neutral = mesh_editor_snapshot_vec3s(
                mesh_editor_snapshot_required_member(row, "positions", JsonValue::Type::Array),
                "neutral positions");
            const auto composed = mesh_editor_snapshot_vec3s(
                mesh_editor_snapshot_required_member(row, "composed_positions", JsonValue::Type::Array),
                "composed positions");
            const auto& visible = submeshes.at(index).vertices;
            if (neutral.size() != visible.size() || composed.size() != visible.size()) {
                throw std::runtime_error("morph runtime snapshot neutral topology does not match");
            }
            for (std::size_t vertex = 0; vertex < visible.size(); ++vertex) {
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    const double source = composed[vertex][axis];
                    const double target = visible[vertex][axis];
                    // Geometry snapshots may round to float32. A compatible
                    // replacement can also carry real edits, which stay residual.
                    if (target != source && target != static_cast<double>(static_cast<float>(source))) {
                        neutral[vertex][axis] += target - source;
                    }
                }
            }
            runtime->neutral_positions[index] = std::move(neutral);
            runtime->composed_positions[index] = visible;
            if (const auto* raw_normals = row.get("neutral_normals")) {
                auto normals = mesh_editor_snapshot_vec3s(*raw_normals, "neutral normals");
                if (!normals.empty() && normals.size() != visible.size())
                    throw std::runtime_error("morph runtime snapshot normal topology does not match");
                runtime->neutral_normals[index] = std::make_shared<const std::vector<Vec3>>(std::move(normals));
            }
        }
    }
    runtime->driver_submesh_indices = mesh_editor_snapshot_submesh_set(
        mesh_editor_snapshot_required_member(raw_runtime, "driver_submesh_indices", JsonValue::Type::Array),
        submeshes,
        "runtime driver submeshes",
        true
    );
    runtime->refit = mesh_editor_refit_from_snapshot(
        raw_runtime.get("refit"), submeshes, runtime->driver_submesh_indices, version
    );
    mesh_editor_read_snapshot_neutral_bones(raw_runtime.get("neutral_bones"), submeshes, *runtime);
    if (runtime->refit) for (const auto& item : runtime->refit->garment_settings) {
        auto topology = submeshes.at(item.first);
        const auto neutral = runtime->neutral_positions.find(item.first);
        if (neutral != runtime->neutral_positions.end()) topology.vertices = neutral->second;
        mesh_editor_validate_refit_islands(topology,item.second);
    }
    runtime->unbaked = mesh_editor_snapshot_bool(raw_runtime, "unbaked");
    if (runtime->unbaked != mesh_editor_morph_layer_has_value(runtime->current_layer)) {
        throw std::runtime_error("morph runtime snapshot unbaked state does not match its current layer");
    }
    runtime->state_revision = mesh_editor_snapshot_integer(raw_runtime, "state_revision");
    runtime->change_id = mesh_editor_snapshot_string(raw_runtime, "change_id");
    runtime->active_change_id = mesh_editor_snapshot_string(raw_runtime, "active_change_id");
    runtime->active_definition_id = mesh_editor_snapshot_string(raw_runtime, "active_definition_id");
    const long long active_change_update_count = mesh_editor_snapshot_integer(
        raw_runtime, "active_change_update_count"
    );
    if (active_change_update_count > INT_MAX) {
        throw std::runtime_error("morph runtime snapshot active gesture counter is invalid");
    }
    runtime->active_change_update_count = static_cast<int>(active_change_update_count);
    if (!runtime->active_change_id.empty() || !runtime->active_definition_id.empty()
        || runtime->active_change_update_count != 0) {
        throw std::runtime_error("morph runtime snapshot contains an unfinished gesture");
    }
    return runtime;
}
