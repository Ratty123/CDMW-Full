// Procedural morph field generation.
//
// A faithful port of generate_procedural_morph_fields / _rule_delta from
// cdmw/domain/mesh/morph.py. Measured on a vanilla female body with 145
// region sliders, the Python version costs ~950 ms of the ~1042 ms spent
// activating a profile: the work is 93,690 weighted vertices each evaluated
// through a small vector rule, which is exactly what Python is worst at.
//
// The host sends definitions (rule, pivot, basis, weighted vertices) instead
// of pre-computed deltas, so the 7.2 MB field payload never crosses the
// protocol at all — only 2.2 MB of definitions goes the other way.
//
// Ordering and epsilons match the Python exactly, because the two have to
// agree vertex for vertex while both exist.

namespace {

constexpr double kMorphFieldAxialEpsilon = 1e-12;
constexpr double kMorphFieldLengthEpsilon = 1e-30;

struct MorphFieldRule {
    std::string kind;
    int axis_index = 1;
    double amount = 0.0;
};

struct MorphFieldVertex {
    int submesh_index = 0;
    int vertex_index = 0;
    double weight = 1.0;
};

struct MorphFieldDefinition {
    std::string definition_id;
    MorphFieldRule rule;
    Vec3 pivot{0.0, 0.0, 0.0};
    std::array<Vec3, 3> local_basis{Vec3{1.0, 0.0, 0.0}, Vec3{0.0, 1.0, 0.0}, Vec3{0.0, 0.0, 1.0}};
    std::vector<MorphFieldVertex> vertices;
};

Vec3 morph_field_sub(const Vec3& left, const Vec3& right) {
    return Vec3{left[0] - right[0], left[1] - right[1], left[2] - right[2]};
}

Vec3 morph_field_add(const Vec3& left, const Vec3& right) {
    return Vec3{left[0] + right[0], left[1] + right[1], left[2] + right[2]};
}

Vec3 morph_field_scale(const Vec3& value, double factor) {
    return Vec3{value[0] * factor, value[1] * factor, value[2] * factor};
}

double morph_field_dot(const Vec3& left, const Vec3& right) {
    return (left[0] * right[0]) + (left[1] * right[1]) + (left[2] * right[2]);
}

double morph_field_length_squared(const Vec3& value) {
    return morph_field_dot(value, value);
}

Vec3 morph_field_normalized(const Vec3& value, const Vec3& fallback) {
    const double length = std::sqrt(morph_field_length_squared(value));
    return length > kMorphFieldAxialEpsilon ? morph_field_scale(value, 1.0 / length) : fallback;
}

Vec3 morph_field_rodrigues(const Vec3& value, const Vec3& axis, double angle) {
    const double cosine = std::cos(angle);
    const double sine = std::sin(angle);
    const Vec3 cross{
        (axis[1] * value[2]) - (axis[2] * value[1]),
        (axis[2] * value[0]) - (axis[0] * value[2]),
        (axis[0] * value[1]) - (axis[1] * value[0]),
    };
    return morph_field_add(
        morph_field_add(morph_field_scale(value, cosine), morph_field_scale(cross, sine)),
        morph_field_scale(axis, morph_field_dot(axis, value) * (1.0 - cosine))
    );
}

Vec3 morph_field_rule_delta(
    const Vec3& position,
    const Vec3& pivot,
    const Vec3& axis,
    const MorphFieldRule& rule,
    double axial_extent
) {
    const Vec3 local = morph_field_sub(position, pivot);
    const double projection = morph_field_dot(local, axis);
    const Vec3 axial = morph_field_scale(axis, projection);
    const Vec3 radial = morph_field_sub(local, axial);
    const double amount = rule.amount;
    if (rule.kind == "move") return morph_field_scale(axis, amount);
    if (rule.kind == "scale") return morph_field_scale(axial, amount);
    if (rule.kind == "flatten") return morph_field_scale(axial, -amount);
    if (rule.kind == "radius") return morph_field_scale(radial, amount);
    if (rule.kind == "taper") return morph_field_scale(radial, amount * (projection / axial_extent));
    if (rule.kind == "twist") {
        const double angle = (amount * 3.14159265358979323846 / 180.0) * (projection / axial_extent);
        return morph_field_sub(morph_field_rodrigues(radial, axis, angle), radial);
    }
    // "volume": a fixed push along the radial direction.
    return morph_field_scale(morph_field_normalized(radial, axis), amount);
}

Vec3 morph_field_vec3_from_json(const JsonValue* value, const Vec3& fallback) {
    if (value == nullptr || value->type != JsonValue::Type::Array || value->array_value.size() < 3) {
        return fallback;
    }
    return Vec3{
        number_or(&value->array_value[0], fallback[0]),
        number_or(&value->array_value[1], fallback[1]),
        number_or(&value->array_value[2], fallback[2]),
    };
}

int morph_field_axis_index(const std::string& axis) {
    if (axis == "x") return 0;
    if (axis == "z") return 2;
    return 1;
}

MorphFieldDefinition morph_field_definition_from_json(const JsonValue& item) {
    MorphFieldDefinition definition;
    definition.definition_id = string_or(item.get("definition_id"), "");
    if (definition.definition_id.empty()) {
        throw std::runtime_error("procedural morph field definition is missing its id");
    }
    const JsonValue* raw_rule = item.get("rule");
    if (raw_rule == nullptr || raw_rule->type != JsonValue::Type::Object) {
        throw std::runtime_error("procedural morph field definition is missing its rule");
    }
    definition.rule.kind = lower_ascii(string_or(raw_rule->get("kind"), "volume"));
    definition.rule.axis_index = morph_field_axis_index(lower_ascii(string_or(raw_rule->get("axis"), "y")));
    definition.rule.amount = number_or(raw_rule->get("amount"), 0.0);
    definition.pivot = morph_field_vec3_from_json(item.get("pivot"), Vec3{0.0, 0.0, 0.0});

    const JsonValue* raw_basis = item.get("local_basis");
    if (raw_basis == nullptr || raw_basis->type != JsonValue::Type::Array || raw_basis->array_value.size() < 3) {
        throw std::runtime_error("procedural morph field definition is missing its local basis");
    }
    for (std::size_t index = 0; index < 3; ++index) {
        definition.local_basis[index] =
            morph_field_vec3_from_json(&raw_basis->array_value[index], definition.local_basis[index]);
    }

    const JsonValue* raw_vertices = item.get("vertices");
    if (raw_vertices == nullptr || raw_vertices->type != JsonValue::Type::Array) {
        throw std::runtime_error("procedural morph field definition is missing its weighted vertices");
    }
    definition.vertices.reserve(raw_vertices->array_value.size());
    for (const JsonValue& row : raw_vertices->array_value) {
        MorphFieldVertex vertex;
        if (row.type == JsonValue::Type::Array && row.array_value.size() >= 3) {
            // Compact triple: [submesh, vertex, weight]. 145 sliders reference
            // 93,690 entries, so the object form would dominate the payload.
            vertex.submesh_index = int_or(&row.array_value[0], 0);
            vertex.vertex_index = int_or(&row.array_value[1], 0);
            vertex.weight = number_or(&row.array_value[2], 1.0);
        } else if (row.type == JsonValue::Type::Object) {
            vertex.submesh_index = int_or(row.get("submesh_index"), 0);
            vertex.vertex_index = int_or(row.get("vertex_index"), 0);
            vertex.weight = number_or(row.get("weight"), 1.0);
        } else {
            continue;
        }
        definition.vertices.push_back(vertex);
    }
    return definition;
}

void morph_field_write_vec3(std::ostream& out, const Vec3& value) {
    out << '[' << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2] << ']';
}

}  // namespace

std::string mesh_editor_morph_generate_fields_report(
    const JsonValue& root,
    const std::string& session_id,
    const MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    const std::map<int, MeshSessionSubmesh>& submeshes = mesh_editor_submeshes(session);
    const JsonValue* raw_definitions = root.get("definitions");
    if (raw_definitions == nullptr || raw_definitions->type != JsonValue::Type::Array) {
        throw std::runtime_error("morph_generate_fields is missing its definitions");
    }
    const bool return_fields = bool_or(root.get("return_fields"), true);

    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\""
        << ",\"protocol\":\"mesh-editor-session-json\",\"command\":\"morph_generate_fields\""
        << ",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"fields\":[";
    bool wrote_field = false;
    std::size_t definition_count = 0;
    std::size_t delta_count = 0;

    for (const JsonValue& item : raw_definitions->array_value) {
        if (item.type != JsonValue::Type::Object) continue;
        const MorphFieldDefinition definition = morph_field_definition_from_json(item);
        ++definition_count;

        const Vec3 axis = morph_field_normalized(
            definition.local_basis[static_cast<std::size_t>(definition.rule.axis_index)],
            Vec3{0.0, 1.0, 0.0}
        );

        // Resolve positions first: the axial extent normalises taper and twist
        // across the whole selection, so it has to be known before any delta.
        std::vector<Vec3> positions;
        positions.reserve(definition.vertices.size());
        double axial_extent = 0.0;
        for (const MorphFieldVertex& vertex : definition.vertices) {
            const auto found = submeshes.find(vertex.submesh_index);
            if (found == submeshes.end()) {
                throw std::runtime_error(
                    "morph definition submesh is out of range: " + std::to_string(vertex.submesh_index)
                );
            }
            const std::vector<Vec3>& vertices = found->second.vertices;
            if (vertex.vertex_index < 0 || static_cast<std::size_t>(vertex.vertex_index) >= vertices.size()) {
                throw std::runtime_error(
                    "morph definition vertex is out of range: " + std::to_string(vertex.vertex_index)
                );
            }
            const Vec3& position = vertices[static_cast<std::size_t>(vertex.vertex_index)];
            positions.push_back(position);
            axial_extent = std::max(
                axial_extent,
                std::fabs(morph_field_dot(morph_field_sub(position, definition.pivot), axis))
            );
        }
        if (axial_extent <= kMorphFieldAxialEpsilon) {
            axial_extent = 1.0;
        }

        // Grouped by submesh then sorted by vertex index, matching the Python.
        std::map<int, std::vector<std::pair<int, Vec3>>> grouped;
        for (std::size_t index = 0; index < definition.vertices.size(); ++index) {
            const MorphFieldVertex& vertex = definition.vertices[index];
            const Vec3 delta = morph_field_rule_delta(
                positions[index], definition.pivot, axis, definition.rule, axial_extent
            );
            const double weight = std::max(0.0, std::min(1.0, vertex.weight));
            const Vec3 weighted = morph_field_scale(delta, weight);
            if (morph_field_length_squared(weighted) <= kMorphFieldLengthEpsilon) continue;
            grouped[vertex.submesh_index].emplace_back(vertex.vertex_index, weighted);
        }

        for (auto& entry : grouped) {
            std::sort(
                entry.second.begin(),
                entry.second.end(),
                [](const std::pair<int, Vec3>& left, const std::pair<int, Vec3>& right) {
                    return left.first < right.first;
                }
            );
            delta_count += entry.second.size();
            if (!return_fields) continue;
            if (wrote_field) out << ',';
            wrote_field = true;
            out << "{\"definition_id\":";
            write_escaped(out, definition.definition_id);
            out << ",\"submesh_index\":" << entry.first << ",\"vertex_indices\":[";
            bool wrote_index = false;
            for (const auto& row : entry.second) {
                if (wrote_index) out << ',';
                wrote_index = true;
                out << row.first;
            }
            out << "],\"deltas\":[";
            bool wrote_delta = false;
            for (const auto& row : entry.second) {
                if (wrote_delta) out << ',';
                wrote_delta = true;
                morph_field_write_vec3(out, row.second);
            }
            out << "]}";
        }
    }

    out << "],\"definition_count\":" << definition_count
        << ",\"delta_count\":" << delta_count
        << ",\"returned_fields\":" << (return_fields ? "true" : "false")
        << ",\"duration_ms\":"
        << std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count()
        << '}';
    return out.str();
}
