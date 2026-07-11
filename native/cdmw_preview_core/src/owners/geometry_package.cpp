
static std::array<float, 3> color_for_batch(int index) {
    static const std::array<std::array<float, 3>, 8> colors = {{
        {0.78f, 0.62f, 0.44f},
        {0.58f, 0.68f, 0.78f},
        {0.68f, 0.55f, 0.44f},
        {0.64f, 0.64f, 0.56f},
        {0.55f, 0.72f, 0.62f},
        {0.76f, 0.58f, 0.62f},
        {0.62f, 0.60f, 0.78f},
        {0.72f, 0.70f, 0.60f},
    }};
    return colors[static_cast<size_t>(std::max(0, index)) % colors.size()];
}

static void append_float(std::vector<char>& out, float value) {
    const char* bytes = reinterpret_cast<const char*>(&value);
    out.insert(out.end(), bytes, bytes + sizeof(float));
}

static void append_int32(std::vector<char>& out, std::int32_t value) {
    const char* bytes = reinterpret_cast<const char*>(&value);
    out.insert(out.end(), bytes, bytes + sizeof(std::int32_t));
}

static void write_geometry_blob(
    const fs::path& geometry_path,
    const fs::path& identity_path,
    const NativeSubmesh& mesh,
    const Vec3& center,
    float scale,
    const std::array<float, 3>& color
) {
    std::vector<Vec3> tangents(mesh.positions.size());
    std::vector<Vec3> bitangents(mesh.positions.size());
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t i0 = mesh.indices[i];
        const std::uint32_t i1 = mesh.indices[i + 1];
        const std::uint32_t i2 = mesh.indices[i + 2];
        if (i0 >= mesh.positions.size() || i1 >= mesh.positions.size() || i2 >= mesh.positions.size()) continue;
        const Vec3 p0 = mesh.positions[i0];
        const Vec3 p1 = mesh.positions[i1];
        const Vec3 p2 = mesh.positions[i2];
        const Vec2 uv0 = i0 < mesh.uvs.size() ? mesh.uvs[i0] : Vec2{};
        const Vec2 uv1 = i1 < mesh.uvs.size() ? mesh.uvs[i1] : Vec2{};
        const Vec2 uv2 = i2 < mesh.uvs.size() ? mesh.uvs[i2] : Vec2{};
        const Vec3 e1 = vec_sub(p1, p0);
        const Vec3 e2 = vec_sub(p2, p0);
        const float du1 = uv1.x - uv0.x;
        const float dv1 = uv1.y - uv0.y;
        const float du2 = uv2.x - uv0.x;
        const float dv2 = uv2.y - uv0.y;
        const float denom = du1 * dv2 - du2 * dv1;
        if (std::abs(denom) < 1.0e-8f) continue;
        const float r = 1.0f / denom;
        const Vec3 tangent = vec_mul(vec_sub(vec_mul(e1, dv2), vec_mul(e2, dv1)), r);
        const Vec3 bitangent = vec_mul(vec_sub(vec_mul(e2, du1), vec_mul(e1, du2)), r);
        tangents[i0] = vec_add(tangents[i0], tangent);
        tangents[i1] = vec_add(tangents[i1], tangent);
        tangents[i2] = vec_add(tangents[i2], tangent);
        bitangents[i0] = vec_add(bitangents[i0], bitangent);
        bitangents[i1] = vec_add(bitangents[i1], bitangent);
        bitangents[i2] = vec_add(bitangents[i2], bitangent);
    }

    std::vector<char> geometry;
    std::vector<char> identity;
    geometry.reserve(mesh.indices.size() * 23u * 4u);
    identity.reserve(mesh.indices.size() * 8u);
    for (size_t tri = 0; tri + 2 < mesh.indices.size(); tri += 3) {
        const std::uint32_t indices[3] = {mesh.indices[tri], mesh.indices[tri + 1], mesh.indices[tri + 2]};
        for (int corner = 0; corner < 3; ++corner) {
            const std::uint32_t vi = indices[corner];
            const Vec3 raw_position = mesh.positions[vi];
            const Vec3 position = vec_mul(vec_sub(raw_position, center), scale);
            const Vec3 normal = vec_normalize(vi < mesh.normals.size() ? mesh.normals[vi] : Vec3{0.0f, 1.0f, 0.0f});
            Vec3 tangent = vec_normalize(vi < tangents.size() ? tangents[vi] : Vec3{}, Vec3{});
            Vec3 bitangent = vec_normalize(vi < bitangents.size() ? bitangents[vi] : Vec3{}, Vec3{});
            if (vec_dot(tangent, tangent) <= 1.0e-8f) {
                const Vec3 up = std::abs(normal.y) < 0.9f ? Vec3{0.0f, 1.0f, 0.0f} : Vec3{1.0f, 0.0f, 0.0f};
                tangent = vec_normalize(vec_cross(up, normal), Vec3{1.0f, 0.0f, 0.0f});
            }
            if (vec_dot(bitangent, bitangent) <= 1.0e-8f) {
                bitangent = vec_normalize(vec_cross(normal, tangent), Vec3{0.0f, 0.0f, 1.0f});
            }
            const Vec2 uv = vi < mesh.uvs.size() ? mesh.uvs[vi] : Vec2{};
            const std::int32_t source_vertex = vi < mesh.source_vertex_indices.size()
                ? mesh.source_vertex_indices[vi]
                : static_cast<std::int32_t>(vi);
            const float bary[3] = {corner == 0 ? 1.0f : 0.0f, corner == 1 ? 1.0f : 0.0f, corner == 2 ? 1.0f : 0.0f};
            for (float value : {
                position.x, position.y, position.z,
                normal.x, normal.y, normal.z,
                color[0], color[1], color[2],
                uv.x, uv.y,
                tangent.x, tangent.y, tangent.z,
                bitangent.x, bitangent.y, bitangent.z,
                normal.x, normal.y, normal.z,
                bary[0], bary[1], bary[2],
            }) {
                append_float(geometry, value);
            }
            append_int32(identity, static_cast<std::int32_t>(mesh.source_submesh_index));
            append_int32(identity, source_vertex);
        }
    }
    write_binary(geometry_path, geometry);
    write_binary(identity_path, identity);
}

static float native_distance(const Vec3& a, const Vec3& b) {
    const float dx = a.x - b.x;
    const float dy = a.y - b.y;
    const float dz = a.z - b.z;
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

static std::optional<NativePbdSidecarHint> native_pbd_hint_for_mesh(
    const NativeSubmesh& mesh,
    const std::vector<const TextureBinding*>& batch_bindings
) {
    std::optional<NativePbdSidecarHint> best;
    int best_score = 0;
    const std::string mesh_material_key = normalized_material_key(mesh.material);
    const std::string mesh_name_key = normalized_material_key(mesh.name);
    const std::string mesh_scope_text = mesh.material.empty() ? mesh.name : mesh.material;
    const bool mesh_looks_like_soft_physics = native_soft_pbd_token_match(mesh_scope_text);
    if (native_rigid_pbd_token_match(mesh_scope_text) && !mesh_looks_like_soft_physics) {
        return std::nullopt;
    }
    for (const TextureBinding* binding : batch_bindings) {
        if (binding == nullptr || binding->pbd_simulation_material_name.empty()) continue;
        const std::string kind = lower_copy(binding->pbd_simulation_kind.empty() ? "unknown" : binding->pbd_simulation_kind);
        NativePbdSidecarHint hint;
        hint.simulation_material_name = binding->pbd_simulation_material_name;
        hint.simulation_kind = kind;
        hint.material_name = binding->pbd_material_name.empty() ? binding->material_name : binding->pbd_material_name;
        hint.submesh_name = binding->pbd_submesh_name;
        hint.parameter_name = binding->parameter_name;
        hint.sidecar_path = binding->sidecar_path;
        if (!native_pbd_hint_is_soft_physics(hint)) continue;
        const std::string hint_material_key = normalized_material_key(hint.material_name);
        const std::string hint_submesh_key = normalized_material_key(hint.submesh_name);
        const bool hint_has_scope = !hint_material_key.empty() || !hint_submesh_key.empty();
        const bool material_scope_match = !hint_material_key.empty() && (
            hint_material_key == mesh_material_key ||
            hint_material_key == mesh_name_key ||
            material_keys_match_for_identity(hint_material_key, mesh_material_key) ||
            material_keys_match_for_identity(hint_material_key, mesh_name_key)
        );
        const bool submesh_scope_match = !hint_submesh_key.empty() && (
            hint_submesh_key == mesh_material_key ||
            hint_submesh_key == mesh_name_key ||
            material_keys_match_for_identity(hint_submesh_key, mesh_material_key) ||
            material_keys_match_for_identity(hint_submesh_key, mesh_name_key)
        );
        const int identity_score = material_identity_match_score(*binding, mesh);
        const bool strong_identity_match = identity_score >= 180;
        if (hint_has_scope && !material_scope_match && !submesh_scope_match && !strong_identity_match) {
            continue;
        }
        int score = 0;
        if (material_scope_match) score += 120;
        if (submesh_scope_match) score += 120;
        if (mesh_looks_like_soft_physics) score += 20;
        if (strong_identity_match) score += 40;
        if (material_binding_matches_mesh_source(*binding, mesh)) score += 10;
        if (score > best_score) {
            best_score = score;
            best = hint;
        }
    }
    return best_score >= 80 ? best : std::nullopt;
}

static std::vector<NativeClothConstraint> build_native_cloth_constraints(
    const std::vector<Vec3>& positions,
    const std::vector<std::uint32_t>& indices,
    const NativePbdMaterialSettings& settings,
    size_t max_constraints = 60000
) {
    std::vector<std::array<int, 3>> triangles;
    triangles.reserve(indices.size() / 3u);
    std::map<std::pair<int, int>, std::vector<int>> edge_faces;
    std::set<std::pair<int, int>> structural_edges;
    auto add_edge = [&](int a, int b, int face_index) {
        if (a == b) return;
        if (a > b) std::swap(a, b);
        std::pair<int, int> edge{a, b};
        structural_edges.insert(edge);
        edge_faces[edge].push_back(face_index);
    };
    for (size_t offset = 0; offset + 2 < indices.size(); offset += 3) {
        const int a = static_cast<int>(indices[offset]);
        const int b = static_cast<int>(indices[offset + 1]);
        const int c = static_cast<int>(indices[offset + 2]);
        if (a < 0 || b < 0 || c < 0) continue;
        if (static_cast<size_t>(a) >= positions.size() || static_cast<size_t>(b) >= positions.size() || static_cast<size_t>(c) >= positions.size()) continue;
        if (a == b || b == c || c == a) continue;
        const int face_index = static_cast<int>(triangles.size());
        triangles.push_back({a, b, c});
        add_edge(a, b, face_index);
        add_edge(b, c, face_index);
        add_edge(c, a, face_index);
    }
    std::vector<NativeClothConstraint> constraints;
    constraints.reserve(std::min<size_t>(max_constraints, structural_edges.size() * 2u));
    for (const auto& edge : structural_edges) {
        NativeClothConstraint constraint;
        constraint.a = edge.first;
        constraint.b = edge.second;
        constraint.rest_length = native_distance(positions[static_cast<size_t>(constraint.a)], positions[static_cast<size_t>(constraint.b)]);
        constraint.stiffness = settings.stretching_stiffness;
        constraints.push_back(constraint);
        if (constraints.size() >= max_constraints) return constraints;
    }
    std::set<std::pair<int, int>> bend_seen;
    for (const auto& [edge, face_indices] : edge_faces) {
        if (face_indices.size() < 2) continue;
        const auto& first = triangles[static_cast<size_t>(face_indices[0])];
        const auto& second = triangles[static_cast<size_t>(face_indices[1])];
        std::vector<int> opposite;
        for (int value : first) {
            if (value != edge.first && value != edge.second) opposite.push_back(value);
        }
        for (int value : second) {
            if (value != edge.first && value != edge.second) opposite.push_back(value);
        }
        if (opposite.size() < 2 || opposite[0] == opposite[1]) continue;
        int a = opposite[0];
        int b = opposite[1];
        if (a > b) std::swap(a, b);
        std::pair<int, int> bend{a, b};
        if (!bend_seen.insert(bend).second) continue;
        NativeClothConstraint constraint;
        constraint.a = bend.first;
        constraint.b = bend.second;
        constraint.rest_length = native_distance(positions[static_cast<size_t>(constraint.a)], positions[static_cast<size_t>(constraint.b)]);
        constraint.stiffness = settings.bending_stiffness;
        constraints.push_back(constraint);
        if (constraints.size() >= max_constraints) break;
    }
    return constraints;
}

static std::vector<float> build_native_cloth_pin_weights(
    const std::vector<Vec3>& positions,
    const std::vector<std::uint32_t>& indices,
    bool cloak_bias,
    const std::string& simulation_kind = "cloth",
    const std::vector<Vec3>* attachment_anchors = nullptr
) {
    std::vector<float> weights(positions.size(), 0.0f);
    if (positions.empty()) return weights;
    const std::string kind = lower_copy(simulation_kind);
    float hard_height = cloak_bias ? 0.16f : 0.12f;
    float fade_height = cloak_bias ? 0.36f : 0.28f;
    if (kind == "rope" || kind == "spline") {
        hard_height = 0.06f;
        fade_height = 0.18f;
    } else if (kind == "hair") {
        hard_height = 0.08f;
        fade_height = 0.24f;
    } else if (kind == "leather") {
        hard_height = 0.10f;
        fade_height = 0.24f;
    } else if (kind == "body_soft") {
        hard_height = 0.20f;
        fade_height = 0.45f;
    }
    std::vector<size_t> parent(positions.size());
    for (size_t index = 0; index < parent.size(); ++index) parent[index] = index;
    auto find_root = [&](size_t start) {
        size_t index = start;
        while (parent[index] != index) {
            parent[index] = parent[parent[index]];
            index = parent[index];
        }
        return index;
    };
    auto unite = [&](size_t left, size_t right) {
        const size_t left_root = find_root(left);
        const size_t right_root = find_root(right);
        if (left_root != right_root) parent[right_root] = left_root;
    };
    size_t valid_triangles = 0;
    for (size_t offset = 0; offset + 2u < indices.size(); offset += 3u) {
        const size_t a = static_cast<size_t>(indices[offset]);
        const size_t b = static_cast<size_t>(indices[offset + 1u]);
        const size_t c = static_cast<size_t>(indices[offset + 2u]);
        if (a >= positions.size() || b >= positions.size() || c >= positions.size()) continue;
        if (a == b || b == c || c == a) continue;
        ++valid_triangles;
        unite(a, b);
        unite(b, c);
        unite(c, a);
    }
    std::map<size_t, std::vector<size_t>> components;
    if (valid_triangles <= 0) {
        std::vector<size_t> all_indices(positions.size());
        for (size_t index = 0; index < all_indices.size(); ++index) all_indices[index] = index;
        components[0] = all_indices;
    } else {
        for (size_t index = 0; index < positions.size(); ++index) {
            components[find_root(index)].push_back(index);
        }
    }
    for (const auto& [component_key, component] : components) {
        (void)component_key;
        if (component.empty()) continue;
        if (attachment_anchors != nullptr && !attachment_anchors->empty()) {
            std::vector<std::pair<float, size_t>> nearest;
            nearest.reserve(component.size());
            for (size_t index : component) {
                float best_distance = std::numeric_limits<float>::max();
                for (const Vec3& anchor : *attachment_anchors) {
                    best_distance = std::min(best_distance, native_distance(positions[index], anchor));
                }
                nearest.push_back({best_distance, index});
            }
            std::sort(nearest.begin(), nearest.end(), [](const auto& a, const auto& b) {
                if (a.first != b.first) return a.first < b.first;
                return a.second < b.second;
            });
            const size_t hard_count = std::max<size_t>(1, std::min<size_t>(8, std::max<size_t>(2, component.size() / 10u)));
            const size_t fade_count = std::max<size_t>(hard_count, std::min<size_t>(component.size(), hard_count * 3u));
            for (size_t rank = 0; rank < nearest.size() && rank < fade_count; ++rank) {
                const size_t index = nearest[rank].second;
                if (rank < hard_count || hard_count == fade_count) {
                    weights[index] = 1.0f;
                } else {
                    const float t = 1.0f - static_cast<float>(rank - hard_count + 1u) / static_cast<float>(std::max<size_t>(1, fade_count - hard_count + 1u));
                    weights[index] = std::max(weights[index], std::clamp(t, 0.0f, 1.0f));
                }
            }
            continue;
        }
        float component_min_y = positions[component.front()].y;
        float component_max_y = positions[component.front()].y;
        for (size_t index : component) {
            component_min_y = std::min(component_min_y, positions[index].y);
            component_max_y = std::max(component_max_y, positions[index].y);
        }
        const float component_span = std::max(1.0e-6f, component_max_y - component_min_y);
        const float hard_line = component_max_y - component_span * hard_height;
        const float fade_line = component_max_y - component_span * fade_height;
        float component_max_weight = 0.0f;
        for (size_t index : component) {
            const float y = positions[index].y;
            if (y >= hard_line) {
                weights[index] = 1.0f;
            } else if (y >= fade_line) {
                weights[index] = std::clamp((y - fade_line) / std::max(1.0e-6f, hard_line - fade_line), 0.0f, 1.0f);
            }
            component_max_weight = std::max(component_max_weight, weights[index]);
        }
        if (component_max_weight <= 0.0f) {
            std::vector<size_t> order = component;
            std::sort(order.begin(), order.end(), [&](size_t a, size_t b) {
                return positions[a].y > positions[b].y;
            });
            const size_t count = std::max<size_t>(1, std::min<size_t>(3, order.size()));
            for (size_t index = 0; index < count; ++index) weights[order[index]] = 1.0f;
        }
    }
    return weights;
}

static bool native_pbd_runtime_should_use_attachment_anchors(
    const NativePbdSidecarHint& hint,
    const NativePbdMaterialSettings& settings,
    const NativeSubmesh& mesh
) {
    const std::string kind = lower_copy(settings.simulation_kind);
    const std::string context = lower_copy(
        hint.simulation_material_name + " " +
        hint.material_name + " " +
        hint.submesh_name + " " +
        mesh.material + " " +
        mesh.name
    );
    return kind == "spline"
        || (kind == "rope" && context.find("weapon") != std::string::npos)
        || context.find("flag") != std::string::npos
        || context.find("banner") != std::string::npos
        || context.find("ribbon") != std::string::npos;
}

static std::vector<Vec3> collect_native_attachment_anchor_positions(
    const std::vector<NativeSubmesh>& submeshes,
    size_t cloth_batch_index,
    const Vec3& center,
    float scale
) {
    std::vector<Vec3> anchors;
    size_t total_positions = 0;
    for (size_t index = 0; index < submeshes.size(); ++index) {
        if (index == cloth_batch_index) continue;
        total_positions += submeshes[index].positions.size();
    }
    const size_t stride = total_positions > 4096u ? std::max<size_t>(1, total_positions / 4096u) : 1u;
    size_t seen = 0;
    for (size_t mesh_index = 0; mesh_index < submeshes.size(); ++mesh_index) {
        if (mesh_index == cloth_batch_index) continue;
        const NativeSubmesh& mesh = submeshes[mesh_index];
        for (const Vec3& raw_position : mesh.positions) {
            if ((seen++ % stride) != 0u) continue;
            anchors.push_back(vec_mul(vec_sub(raw_position, center), scale));
        }
    }
    return anchors;
}

static NativeClothRuntimeBatch build_native_cloth_runtime_batch(
    const EntryJob& job,
    const PamtIndex& primary_index,
    const std::vector<NativeSubmesh>& submeshes,
    size_t batch_index,
    const NativeSubmesh& mesh,
    const std::vector<const TextureBinding*>& batch_bindings,
    const fs::path& package_dir,
    const fs::path& geometry_dir,
    const std::string& stem,
    const Vec3& center,
    float scale
) {
    NativeClothRuntimeBatch runtime;
    std::optional<NativePbdSidecarHint> hint = native_pbd_hint_for_mesh(mesh, batch_bindings);
    if (!hint.has_value()) return runtime;
    runtime.hint = *hint;
    runtime.settings = resolve_native_pbd_material_settings(job, primary_index, runtime.hint);
    if (!native_soft_pbd_kind(runtime.settings.simulation_kind)) return runtime;
    if (mesh.positions.size() < 3 || mesh.indices.size() < 3) return runtime;
    std::vector<Vec3> normalized_positions;
    normalized_positions.reserve(mesh.positions.size());
    for (const Vec3& raw_position : mesh.positions) {
        normalized_positions.push_back(vec_mul(vec_sub(raw_position, center), scale));
    }
    std::vector<NativeClothConstraint> constraints = build_native_cloth_constraints(normalized_positions, mesh.indices, runtime.settings);
    if (constraints.empty()) return runtime;
    const std::vector<Vec3> attachment_anchors = native_pbd_runtime_should_use_attachment_anchors(runtime.hint, runtime.settings, mesh)
        ? collect_native_attachment_anchor_positions(submeshes, batch_index, center, scale)
        : std::vector<Vec3>();
    const std::vector<float> pins = build_native_cloth_pin_weights(
        normalized_positions,
        mesh.indices,
        runtime.settings.is_cloak || native_cloth_token_match(runtime.hint.simulation_material_name + " " + mesh.material + " " + mesh.name),
        runtime.settings.simulation_kind,
        attachment_anchors.empty() ? nullptr : &attachment_anchors
    );
    runtime.particle_path = geometry_dir / (stem + "_cloth_particles.bin");
    runtime.pin_path = geometry_dir / (stem + "_cloth_pins.bin");
    runtime.constraint_path = geometry_dir / (stem + "_cloth_constraints.bin");

    std::vector<char> particle_blob;
    particle_blob.reserve(normalized_positions.size() * sizeof(float) * 3u);
    for (const Vec3& position : normalized_positions) {
        append_float(particle_blob, position.x);
        append_float(particle_blob, position.y);
        append_float(particle_blob, position.z);
    }
    std::vector<char> pin_blob;
    pin_blob.reserve(pins.size() * sizeof(float));
    for (float weight : pins) append_float(pin_blob, std::clamp(weight, 0.0f, 1.0f));

    std::vector<char> constraint_blob;
    constraint_blob.reserve(constraints.size() * (sizeof(std::int32_t) * 2u + sizeof(float) * 2u));
    for (const NativeClothConstraint& constraint : constraints) {
        append_int32(constraint_blob, static_cast<std::int32_t>(constraint.a));
        append_int32(constraint_blob, static_cast<std::int32_t>(constraint.b));
        append_float(constraint_blob, constraint.rest_length);
        append_float(constraint_blob, std::clamp(constraint.stiffness, 0.0f, 1.0f));
    }
    write_binary(runtime.particle_path, particle_blob);
    write_binary(runtime.pin_path, pin_blob);
    write_binary(runtime.constraint_path, constraint_blob);
    runtime.particle_count = static_cast<int>(normalized_positions.size());
    runtime.constraint_count = static_cast<int>(constraints.size());
    runtime.active = true;
    (void)package_dir;
    return runtime;
}

static std::string dds_entry_json(const TextureBinding* binding, const std::string& slot) {
    if (binding == nullptr || binding->source_path.empty()) return "";
    std::ostringstream out;
    out << "\"" << json_escape(slot) << "\":{"
        << "\"slot\":\"" << json_escape(slot) << "\","
        << "\"source_path\":\"" << json_escape(binding->source_path) << "\","
        << "\"archive_path\":\"" << json_escape(binding->archive_path) << "\","
        << "\"parameter_name\":\"" << json_escape(binding->parameter_name) << "\","
        << "\"semantic_type\":\"" << json_escape(binding->semantic_type) << "\","
        << "\"semantic_subtype\":\"" << json_escape(binding->semantic_subtype) << "\","
        << "\"shader_family\":\"" << json_escape(binding->shader_family) << "\","
        << "\"shader_rule\":\"" << json_escape(binding->shader_rule) << "\","
        << "\"sidecar_path\":\"" << json_escape(binding->sidecar_path) << "\","
        << "\"sidecar_kind\":\"" << json_escape(binding->sidecar_kind) << "\","
        << "\"linked_mesh_path\":\"" << json_escape(binding->linked_mesh_path) << "\","
        << "\"packed_channels\":\"" << json_escape(binding->packed_channels) << "\","
        << "\"srgb_mode\":\"" << json_escape(binding->srgb_mode) << "\","
        << "\"parameter_declared_by\":\"" << json_escape(binding->parameter_declared_by) << "\","
        << "\"material_output_quality\":\"" << json_escape(binding->material_output_quality) << "\","
        << "\"roughness_hint\":" << binding->roughness_hint << ","
        << "\"metalness_hint\":" << binding->metalness_hint << ","
        << "\"specular_hint\":" << binding->specular_hint << ","
        << "\"height_scale_hint\":" << binding->height_scale_hint << ","
        << "\"emissive_intensity_hint\":" << binding->emissive_intensity_hint << ","
        << "\"tint_color\":[" << binding->tint_color[0] << "," << binding->tint_color[1] << "," << binding->tint_color[2] << "," << binding->tint_color[3] << "],"
        << "\"width\":" << binding->dds_width << ","
        << "\"height\":" << binding->dds_height << ","
        << "\"format\":\"" << json_escape(binding->dds_format) << "\","
        << "\"available\":true,"
        << "\"direct_upload_candidate\":true"
        << "}";
    return out.str();
}

static std::string batch_stem(size_t batch_index) {
    std::ostringstream out;
    out << "batch_" << std::setw(3) << std::setfill('0') << batch_index;
    return out.str();
}

static std::vector<const TextureBinding*> relevant_bindings_for_mesh(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh,
    const std::vector<const TextureBinding*>& selected_slots
) {
    std::vector<const TextureBinding*> result;
    std::set<const TextureBinding*> seen;
    auto add = [&](const TextureBinding* binding) {
        if (binding != nullptr && seen.insert(binding).second) result.push_back(binding);
    };
    for (const TextureBinding* binding : selected_slots) add(binding);
    if (bindings.size() <= 8) {
        std::set<std::string> scoped_materials;
        for (const TextureBinding& binding : bindings) {
            const std::string key = normalized_material_key(binding.material_name);
            if (!key.empty()) scoped_materials.insert(key);
        }
        if (scoped_materials.size() <= 1) {
            for (const TextureBinding& binding : bindings) {
                if (!material_binding_matches_mesh_source(binding, mesh)) continue;
                add(&binding);
            }
            return result;
        }
        for (const TextureBinding& binding : bindings) {
            if (!material_binding_matches_mesh_source(binding, mesh)) continue;
            if (material_identity_match_score(binding, mesh) >= 120) add(&binding);
        }
        return result;
    }
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty()) continue;
        if (!material_binding_matches_mesh_source(binding, mesh)) continue;
        const int score = material_identity_match_score(binding, mesh);
        const int threshold = normalized_material_key(binding.material_name).empty() ? 42 : 120;
        if (score >= threshold) add(&binding);
    }
    return result;
}
