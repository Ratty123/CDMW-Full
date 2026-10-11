std::shared_ptr<MeshMorphRuntime> mesh_editor_clone_morph_runtime(const MeshEditorSession& session) {
    return std::make_shared<MeshMorphRuntime>(session.morph ? *session.morph : MeshMorphRuntime{});
}

std::vector<Vec3> mesh_editor_zero_morph_layer(std::size_t count) {
    return std::vector<Vec3>(count, Vec3{0.0, 0.0, 0.0});
}

bool mesh_editor_morph_layer_has_value(const std::map<int, std::vector<Vec3>>& layer) {
    for (const auto& item : layer) {
        for (const Vec3& delta : item.second) {
            if (dot_vec3(delta, delta) > 1.0e-30) return true;
        }
    }
    return false;
}

void mesh_editor_validate_morph_profile_field(
    const std::map<int, MeshSessionSubmesh>& submeshes,
    int submesh_index,
    const MeshMorphSparseFieldRuntime& field
) {
    const auto found = submeshes.find(submesh_index);
    if (found == submeshes.end()) {
        throw std::runtime_error("procedural morph field references a missing editable submesh");
    }
    if (field.vertex_indices.empty() || field.vertex_indices.size() != field.deltas.size()) {
        throw std::runtime_error("procedural morph field requires matching sparse indices and deltas");
    }
    int previous = -1;
    for (std::size_t position = 0; position < field.vertex_indices.size(); ++position) {
        const int vertex_index = field.vertex_indices[position];
        const Vec3& delta = field.deltas[position];
        if (vertex_index <= previous || vertex_index < 0
            || static_cast<std::size_t>(vertex_index) >= found->second.vertices.size()) {
            throw std::runtime_error("procedural morph field contains an invalid or duplicate vertex index");
        }
        if (!std::isfinite(delta[0]) || !std::isfinite(delta[1]) || !std::isfinite(delta[2])) {
            throw std::runtime_error("procedural morph field contains a non-finite delta");
        }
        previous = vertex_index;
    }
}

std::shared_ptr<const MeshMorphProfileRuntime> mesh_editor_morph_profile_from_json(
    const JsonValue* raw_profile,
    const std::map<int, MeshSessionSubmesh>& submeshes
) {
    if (raw_profile == nullptr || raw_profile->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing procedural morph profile");
    }
    const std::string profile_id = string_or(raw_profile->get("profile_id"), "");
    if (profile_id.empty()) {
        return {};
    }
    auto profile = std::make_shared<MeshMorphProfileRuntime>();
    profile->profile_id = profile_id;
    profile->name = string_or(raw_profile->get("name"), profile_id);
    profile->topology_fingerprint = string_or(raw_profile->get("topology_fingerprint"), "");
    if (profile->topology_fingerprint.size() != 64) {
        throw std::runtime_error("procedural morph profile is missing its exact topology fingerprint");
    }
    const JsonValue* raw_definitions = raw_profile->get("definitions");
    if (raw_definitions == nullptr || raw_definitions->type != JsonValue::Type::Array) {
        throw std::runtime_error("procedural morph profile is missing definitions");
    }
    for (const JsonValue& item : raw_definitions->array_value) {
        if (item.type != JsonValue::Type::Object) continue;
        MeshMorphDefinitionRuntime definition;
        definition.definition_id = string_or(item.get("definition_id"), "");
        definition.label = string_or(item.get("label"), definition.definition_id);
        definition.category = string_or(item.get("category"), "General");
        definition.min_percent = number_or(item.get("min_percent"), -100.0);
        definition.max_percent = number_or(item.get("max_percent"), 100.0);
        definition.default_percent = number_or(item.get("default_percent"), 0.0);
        if (definition.definition_id.empty() || !std::isfinite(definition.min_percent)
            || !std::isfinite(definition.max_percent) || !std::isfinite(definition.default_percent)
            || definition.min_percent >= definition.max_percent
            || definition.default_percent < definition.min_percent
            || definition.default_percent > definition.max_percent) {
            throw std::runtime_error("procedural morph definition metadata is invalid");
        }
        if (!profile->definitions.emplace(definition.definition_id, std::move(definition)).second) {
            throw std::runtime_error("procedural morph definition ids must be unique");
        }
    }
    const JsonValue* raw_fields = raw_profile->get("fields");
    if (raw_fields == nullptr || raw_fields->type != JsonValue::Type::Array) {
        throw std::runtime_error("procedural morph profile is missing sparse fields");
    }
    for (const JsonValue& item : raw_fields->array_value) {
        if (item.type != JsonValue::Type::Object) continue;
        const std::string definition_id = string_or(item.get("definition_id"), "");
        const int submesh_index = int_or(item.get("submesh_index"), -1);
        const auto definition = profile->definitions.find(definition_id);
        if (definition == profile->definitions.end() || submesh_index < 0) {
            throw std::runtime_error("procedural morph sparse field references an unknown definition or submesh");
        }
        MeshMorphSparseFieldRuntime field;
        field.vertex_indices = int_vector_from_json(item.get("vertex_indices"));
        field.deltas = vertices_from_json(item.get("deltas"));
        mesh_editor_validate_morph_profile_field(submeshes, submesh_index, field);
        const auto* raw_stage = item.get("stage");
        if (raw_stage && raw_stage->type != JsonValue::Type::String) {
            throw std::runtime_error("morph sparse field stage must be a string");
        }
        const std::string stage = string_or(raw_stage, "base");
        if (stage != "base" && stage != "post_refit") {
            throw std::runtime_error("morph sparse field stage must be base or post_refit");
        }
        auto& fields = stage == "post_refit" ? definition->second.post_refit_fields : definition->second.fields;
        if (!fields.emplace(submesh_index, std::move(field)).second) {
            throw std::runtime_error("procedural morph definition contains duplicate submesh fields");
        }
    }
    for (const auto& definition : profile->definitions) {
        if (definition.second.fields.empty() && definition.second.post_refit_fields.empty()) {
            throw std::runtime_error("procedural morph definition generated no sparse field");
        }
    }
    return profile;
}

std::map<int, std::vector<Vec3>> mesh_editor_build_procedural_morph_layer(
    const MeshMorphRuntime& morph,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    bool post_refit = false
) {
    std::map<int, std::vector<Vec3>> layer;
    if (!morph.profile) return layer;
    for (const auto& definition_item : morph.profile->definitions) {
        const MeshMorphDefinitionRuntime& definition = definition_item.second;
        const auto raw_value = morph.values.find(definition.definition_id);
        const double percent = std::max(
            definition.min_percent,
            std::min(definition.max_percent, raw_value == morph.values.end() ? 0.0 : raw_value->second)
        );
        if (std::fabs(percent) <= 1.0e-12) continue;
        const double factor = percent / 100.0;
        const auto& fields = post_refit ? definition.post_refit_fields : definition.fields;
        for (const auto& field_item : fields) {
            const auto submesh = submeshes.find(field_item.first);
            if (submesh == submeshes.end()) {
                throw std::runtime_error("procedural morph profile topology is no longer available");
            }
            std::vector<Vec3>& deltas = layer[field_item.first];
            if (deltas.empty()) deltas = mesh_editor_zero_morph_layer(submesh->second.vertices.size());
            const MeshMorphSparseFieldRuntime& field = field_item.second;
            for (std::size_t position = 0; position < field.vertex_indices.size(); ++position) {
                const int vertex_index = field.vertex_indices[position];
                deltas[static_cast<std::size_t>(vertex_index)] = add_vec3(
                    deltas[static_cast<std::size_t>(vertex_index)],
                    scale_vec3(field.deltas[position], factor)
                );
            }
        }
    }
    return layer;
}

const std::vector<Vec3>& mesh_editor_morph_layer_for_submesh(
    const std::map<int, std::vector<Vec3>>& layer,
    int submesh_index,
    const std::vector<Vec3>& zero
) {
    const auto found = layer.find(submesh_index);
    return found == layer.end() ? zero : found->second;
}

Vec3 mesh_editor_refit_driver_point(
    const MeshRefitVertexBindingRuntime& binding,
    const std::map<int, std::vector<Vec3>>& positions
) {
    const auto found = positions.find(binding.driver_submesh_index);
    if (found == positions.end()) {
        throw std::runtime_error("garment refit driver positions are missing");
    }
    Vec3 point{0.0, 0.0, 0.0};
    for (std::size_t corner = 0; corner < 3; ++corner) {
        const int vertex_index = binding.driver_vertices[corner];
        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= found->second.size()) {
            throw std::runtime_error("garment refit driver topology changed");
        }
        point = add_vec3(point, scale_vec3(found->second[static_cast<std::size_t>(vertex_index)], binding.barycentric[corner]));
    }
    return point;
}

using RefitMaskWeightsNative = std::map<int, std::vector<double>>;

RefitMaskWeightsNative mesh_editor_refit_masks(
    const MeshRefitRuntime& refit,
    const std::map<int, std::vector<Vec3>>& residual
) {
    RefitMaskWeightsNative result;
    if (refit.vertex_masks.empty()) return result;
    struct Cohort { Vec3 point; double weight; std::vector<std::pair<int, int>> vertices; };
    std::vector<Cohort> cohorts;
    std::map<std::tuple<long long, long long, long long>, std::vector<std::size_t>> cells;
    const double tolerance = std::max(1.0e-6, refit.driver_diagonal * 1.0e-7);
    for (const int index : refit.garment_submesh_indices) {
        const auto positions = residual.find(index);
        if (positions == residual.end()) throw std::runtime_error("refit mask target topology changed");
        const auto mask = refit.vertex_masks.find(index);
        auto& weights = result[index];
        weights.resize(positions->second.size(), mask == refit.vertex_masks.end() ? 1.0 : 0.0);
        if (mask != refit.vertex_masks.end()) for (const auto& entry : mask->second) {
            if (entry.first < 0 || static_cast<std::size_t>(entry.first) >= weights.size()) {
                throw std::runtime_error("refit mask target topology changed");
            }
            weights[static_cast<std::size_t>(entry.first)] = entry.second;
        }
        for (std::size_t vertex = 0; vertex < weights.size(); ++vertex) {
            const Vec3 point = positions->second[vertex];
            const auto cell = mesh_editor_refit_cell(point, tolerance);
            std::size_t selected = cohorts.size();
            for (long long x = -1; x <= 1 && selected == cohorts.size(); ++x)
                for (long long y = -1; y <= 1 && selected == cohorts.size(); ++y)
                    for (long long z = -1; z <= 1 && selected == cohorts.size(); ++z) {
                        const auto found = cells.find({std::get<0>(cell) + x, std::get<1>(cell) + y, std::get<2>(cell) + z});
                        if (found == cells.end()) continue;
                        for (const auto candidate : found->second) {
                            if (distance_squared_vec3(point, cohorts[candidate].point) <= tolerance * tolerance) {
                                selected = candidate;
                                break;
                            }
                        }
                    }
            if (selected == cohorts.size()) {
                cells[cell].push_back(selected);
                cohorts.push_back({point, weights[vertex], {}});
            }
            cohorts[selected].weight = std::min(cohorts[selected].weight, weights[vertex]);
            cohorts[selected].vertices.emplace_back(index, static_cast<int>(vertex));
        }
    }
    for (const auto& cohort : cohorts) for (const auto& vertex : cohort.vertices) {
        result.at(vertex.first)[static_cast<std::size_t>(vertex.second)] = cohort.weight;
    }
    return result;
}

double mesh_editor_refit_mask_weight(const RefitMaskWeightsNative& masks, int submesh, std::size_t vertex) {
    const auto found = masks.find(submesh);
    return found == masks.end() ? 1.0 : found->second.at(vertex);
}

Vec3 refit_rotate_quaternion_native(const std::array<double, 4>& q, const Vec3& point) {
    const Vec3 axis{q[1], q[2], q[3]};
    const Vec3 cross{axis[1] * point[2] - axis[2] * point[1],
                     axis[2] * point[0] - axis[0] * point[2],
                     axis[0] * point[1] - axis[1] * point[0]};
    return add_vec3(scale_vec3(point, q[0] * q[0] - dot_vec3(axis, axis)),
        add_vec3(scale_vec3(axis, 2.0 * dot_vec3(axis, point)), scale_vec3(cross, 2.0 * q[0])));
}

std::array<double, 4> refit_component_rotation_native(
    const std::vector<Vec3>& original, const std::vector<Vec3>& target,
    const Vec3& original_center, const Vec3& target_center
) {
    double covariance[3][3]{};
    for (std::size_t i = 0; i < original.size(); ++i) {
        const Vec3 p = sub_vec3(original[i], original_center), q = sub_vec3(target[i], target_center);
        for (int row = 0; row < 3; ++row) for (int column = 0; column < 3; ++column)
            covariance[row][column] += p[row] * q[column];
    }
    const auto& s = covariance;
    double matrix[4][4]{
        {s[0][0]+s[1][1]+s[2][2], s[1][2]-s[2][1], s[2][0]-s[0][2], s[0][1]-s[1][0]},
        {s[1][2]-s[2][1], s[0][0]-s[1][1]-s[2][2], s[0][1]+s[1][0], s[0][2]+s[2][0]},
        {s[2][0]-s[0][2], s[0][1]+s[1][0], -s[0][0]+s[1][1]-s[2][2], s[1][2]+s[2][1]},
        {s[0][1]-s[1][0], s[0][2]+s[2][0], s[1][2]+s[2][1], -s[0][0]-s[1][1]+s[2][2]}
    };
    double eigenvectors[4][4]{};
    double scale = 0.0;
    for (int row = 0; row < 4; ++row) {
        eigenvectors[row][row] = 1.0;
        for (int column = 0; column < 4; ++column) scale = std::max(scale, std::abs(matrix[row][column]));
    }
    if (scale <= 1.0e-30) return {1.0, 0.0, 0.0, 0.0};
    // Deterministic Jacobi diagonalization of the symmetric quaternion fit.
    for (int iteration = 0; iteration < 64; ++iteration) {
        int first = 0, second = 1;
        for (int row = 0; row < 4; ++row) for (int column = row + 1; column < 4; ++column)
            if (std::abs(matrix[row][column]) > std::abs(matrix[first][second])) { first = row; second = column; }
        const double off = matrix[first][second];
        if (std::abs(off) <= scale * 1.0e-14) break;
        const double tau = (matrix[second][second] - matrix[first][first]) / (2.0 * off);
        const double tangent = std::copysign(1.0, tau) / (std::abs(tau) + std::sqrt(1.0 + tau * tau));
        const double cosine = 1.0 / std::sqrt(1.0 + tangent * tangent), sine = tangent * cosine;
        matrix[first][first] -= tangent * off;
        matrix[second][second] += tangent * off;
        matrix[first][second] = matrix[second][first] = 0.0;
        for (int row = 0; row < 4; ++row) {
            if (row != first && row != second) {
                const double a = matrix[row][first], b = matrix[row][second];
                matrix[row][first] = matrix[first][row] = cosine * a - sine * b;
                matrix[row][second] = matrix[second][row] = sine * a + cosine * b;
            }
            const double a = eigenvectors[row][first], b = eigenvectors[row][second];
            eigenvectors[row][first] = cosine * a - sine * b;
            eigenvectors[row][second] = sine * a + cosine * b;
        }
    }
    int selected = 0;
    for (int column = 1; column < 4; ++column)
        if (matrix[column][column] > matrix[selected][selected] + scale * 1.0e-13) selected = column;
    std::array<double, 4> q{};
    double norm = 0.0;
    for (int row = 0; row < 4; ++row) { q[row] = eigenvectors[row][selected]; norm += q[row] * q[row]; }
    const double factor = (q[0] < 0.0 ? -1.0 : 1.0) / std::sqrt(norm);
    for (auto& value : q) value *= factor;
    return q;
}

void mesh_editor_refit_components(
    const MeshRefitRuntime& refit,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& driver_visible,
    const std::map<int, std::vector<Vec3>>& residual,
    const std::map<int, std::vector<Vec3>>& base_layer,
    const RefitMaskWeightsNative& masks,
    std::map<int, std::vector<Vec3>>& layer,
    bool conforming = false
) {
    struct Vertex { int submesh; int vertex; Vec3 original; Vec3 target; double weight; };
    std::vector<Vertex> vertices;
    std::vector<std::size_t> roots;
    std::map<int, std::vector<std::size_t>> indices;
    const auto root_of = [&](std::size_t index) {
        while (roots[index] != index) { roots[index] = roots[roots[index]]; index = roots[index]; }
        return index;
    };
    const double tolerance = std::max(1.0e-6, refit.driver_diagonal * 1.0e-7);
    std::map<std::tuple<long long, long long, long long>, std::vector<std::size_t>> cells;
    for (const auto& item : refit.garment_settings) {
        if (!item.second.enabled || item.second.mode != "rigid_component") continue;
        if (conforming && item.second.tightness_percent == 0.0) continue;
        const auto& part = submeshes.at(item.first);
        const auto base = base_layer.find(item.first);
        for (std::size_t vertex = 0; vertex < part.vertices.size(); ++vertex) {
            const auto index = vertices.size();
            const Vec3 p = add_vec3(residual.at(item.first)[vertex],
                base == base_layer.end() ? Vec3{} : base->second[vertex]);
            roots.push_back(index);
            vertices.push_back({item.first, static_cast<int>(vertex), p,
                add_vec3(residual.at(item.first)[vertex], layer.at(item.first)[vertex]),
                mesh_editor_refit_mask_weight(masks, item.first, vertex)});
            indices[item.first].push_back(index);
            const auto cell = mesh_editor_refit_cell(p, tolerance);
            for (long long x = -1; x <= 1; ++x) for (long long y = -1; y <= 1; ++y) for (long long z = -1; z <= 1; ++z) {
                const auto found = cells.find({std::get<0>(cell) + x, std::get<1>(cell) + y, std::get<2>(cell) + z});
                if (found == cells.end()) continue;
                for (const auto other : found->second)
                    if (distance_squared_vec3(p, vertices[other].original) <= tolerance * tolerance)
                        roots[root_of(index)] = root_of(other);
            }
            cells[cell].push_back(index);
        }
        for (const auto& face : part.faces) {
            for (int corner = 0; corner < 3; ++corner) {
                if (face[corner] < 0 || static_cast<std::size_t>(face[corner]) >= part.vertices.size())
                    throw std::runtime_error("rigid component contains an invalid face");
            }
            roots[root_of(indices.at(item.first)[face[0]])] = root_of(indices.at(item.first)[face[1]]);
            roots[root_of(indices.at(item.first)[face[1]])] = root_of(indices.at(item.first)[face[2]]);
        }
    }
    if (vertices.empty()) return;
    std::map<std::size_t, std::vector<std::size_t>> components;
    for (std::size_t i = 0; i < vertices.size(); ++i) components[root_of(i)].push_back(i);
    std::map<int, MeshSessionSubmesh> drivers;
    for (const auto& item : driver_visible) { drivers[item.first].vertices = item.second; drivers[item.first].faces = submeshes.at(item.first).faces; }
    const auto spatial = build_refit_spatial_index_native(drivers, refit.driver_submesh_indices);
    for (const auto& component : components) {
        const auto& first = vertices[component.second.front()];
        const auto& settings = refit.garment_settings.at(first.submesh);
        std::vector<Vec3> original, target;
        Vec3 original_center{}, target_center{};
        for (const auto index : component.second) {
            const auto& vertex = vertices[index];
            const auto& current = refit.garment_settings.at(vertex.submesh);
            if (std::abs(vertex.weight - first.weight) > 1.0e-12
                || current.intensity_percent != settings.intensity_percent
                || current.tightness_percent != settings.tightness_percent
                || current.clearance_percent != settings.clearance_percent) {
                throw std::runtime_error("Part " + std::to_string(first.submesh)
                    + ": rigid components require uniform vertex masks, intensity, clearance and tightness");
            }
            original.push_back(vertex.original); target.push_back(vertex.target);
            original_center = add_vec3(original_center, vertex.original);
            target_center = add_vec3(target_center, vertex.target);
        }
        original_center = scale_vec3(original_center, 1.0 / original.size());
        target_center = scale_vec3(target_center, 1.0 / target.size());
        auto rotation = refit_component_rotation_native(original, target, original_center, target_center);
        const double amount = conforming ? 1.0 : settings.intensity_percent / 100.0 * first.weight;
        const double half_angle = std::acos(std::clamp(rotation[0], -1.0, 1.0));
        if (half_angle > 1.0e-12) {
            const double scale = std::sin(half_angle * amount) / std::sin(half_angle);
            rotation[0] = std::cos(half_angle * amount);
            for (int axis = 1; axis < 4; ++axis) rotation[axis] *= scale;
        }
        const Vec3 center = add_vec3(original_center, scale_vec3(sub_vec3(target_center, original_center), amount));
        std::vector<Vec3> fitted;
        for (const auto& point : original) fitted.push_back(amount == 0.0 ? point :
            add_vec3(center, refit_rotate_quaternion_native(rotation, sub_vec3(point, original_center))));
        auto samples = fitted;
        if (conforming) {
            std::map<std::size_t,std::size_t> local;
            for (std::size_t i=0;i<component.second.size();++i) local[component.second[i]]=i;
            std::set<std::pair<std::size_t,std::size_t>> sampled_edges;
            for (const auto& item : indices) for (const auto& face : submeshes.at(item.first).faces) {
                if (!local.count(item.second[face[0]])) continue;
                Vec3 center{};
                for (int c=0;c<3;++c) {
                    const auto a=local.at(item.second[face[c]]), b=local.at(item.second[face[(c+1)%3]]);
                    center=add_vec3(center,fitted[a]);
                    if (sampled_edges.insert(std::minmax(a,b)).second)
                        samples.push_back(scale_vec3(add_vec3(fitted[a],fitted[b]),0.5));
                }
                samples.push_back(scale_vec3(center,1.0/3.0));
            }
        }
        Vec3 clearance_shift{};
        const double clearance = refit.driver_diagonal * settings.clearance_percent / 100.0
            * (conforming ? 1.0 : first.weight);
        // Every clearance adjustment is one shared translation, preserving the hard part.
        if (clearance > 0.0 && first.weight > 0.0) for (int pass = 0; pass < (conforming ? 128 : 32); ++pass) {
            double missing_max = tolerance;
            Vec3 correction{};
            for (const auto& point : samples) {
                const Vec3 predicted = add_vec3(point, clearance_shift);
                long long candidate_tests = 0;
                const auto binding = closest_refit_binding_native(predicted, spatial, candidate_tests);
                const Vec3 normal = refit_binding_face_normal_native(binding, driver_visible);
                const double missing = clearance - dot_vec3(sub_vec3(predicted,
                    mesh_editor_refit_driver_point(binding, driver_visible)), normal);
                if (missing > missing_max) { missing_max = missing; correction = scale_vec3(normal, missing); }
            }
            if (missing_max <= tolerance) break;
            clearance_shift = add_vec3(clearance_shift, correction);
        }
        if (conforming) for (const auto& point : samples) {
            const Vec3 predicted=add_vec3(point,clearance_shift);
            long long tests=0;
            const auto nearest=closest_refit_binding_native(predicted,spatial,tests);
            const double height=dot_vec3(sub_vec3(predicted,mesh_editor_refit_driver_point(nearest,driver_visible)),
                refit_binding_face_normal_native(nearest,driver_visible));
            if (height < clearance-tolerance*4.0)
                throw std::runtime_error("Fit to body: Part " + std::to_string(first.submesh)
                    + " rigid component cannot clear the body while preserving its dimensions and mask");
        }
        for (std::size_t i = 0; i < component.second.size(); ++i) {
            const auto& vertex = vertices[component.second[i]];
            layer.at(vertex.submesh)[vertex.vertex] = sub_vec3(
                add_vec3(fitted[i], clearance_shift), residual.at(vertex.submesh)[vertex.vertex]);
        }
    }
}

std::vector<Vec3> mesh_editor_smooth_refit_contact(
    const std::vector<Vec3>&, const std::vector<double>&,
    const std::map<std::pair<std::size_t,std::size_t>,double>&, double, int = 256);

void mesh_editor_relieve_refit_surface(
    const MeshRefitRuntime& refit,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& driver_visible,
    const std::map<int, std::vector<Vec3>>& residual,
    std::map<int, std::vector<Vec3>>& layer,
    const RefitMaskWeightsNative* fitting_masks = nullptr,
    bool validate_only = false,
    const std::map<int, std::vector<Vec3>>* layer_reference = nullptr
) {
    std::map<int, double> clearances;
    for (const auto& item : refit.garment_settings) {
        if (item.second.enabled && item.second.clearance_percent > 0.0
            && (item.second.mode == "surface" || (fitting_masks && item.second.mode == "rigid_component"))) {
            clearances[item.first] = refit.driver_diagonal * item.second.clearance_percent / 100.0;
        }
    }
    if (clearances.empty()) return;

    // A garment triangle can cross a curved body even when all its vertices
    // clear their original bindings. Query the live surface for its edges and
    // interior as well, without changing topology or the zero-clearance path.
    std::map<int, MeshSessionSubmesh> drivers;
    for (const auto& item : driver_visible) {
        drivers[item.first].vertices = item.second;
        drivers[item.first].faces = submeshes.at(item.first).faces;
    }
    const RefitSpatialIndexNative spatial_index = build_refit_spatial_index_native(
        drivers, refit.driver_submesh_indices
    );
    const double tolerance = std::max(1.0e-6, refit.driver_diagonal * 1.0e-7);
    struct Cohort {
        Vec3 original;
        Vec3 position;
        double clearance = 0.0;
        std::vector<std::pair<int, std::size_t>> vertices;
        bool has_surface = false;
        double mobility = 1.0;
    };
    std::vector<Cohort> cohorts;
    std::map<int, std::vector<std::size_t>> vertex_cohorts;
    std::map<std::tuple<long long, long long, long long>, std::vector<std::size_t>> cells;
    for (const auto& item : clearances) {
        const int index = item.first;
        auto& indices = vertex_cohorts[index];
        const auto& positions = residual.at(index);
        for (std::size_t vertex = 0; vertex < positions.size(); ++vertex) {
            const Vec3 point = add_vec3(positions[vertex], layer.at(index)[vertex]);
            const auto cell = mesh_editor_refit_cell(point, tolerance);
            std::size_t cohort_index = cohorts.size();
            for (long long dx = -1; dx <= 1 && cohort_index == cohorts.size(); ++dx) {
                for (long long dy = -1; dy <= 1 && cohort_index == cohorts.size(); ++dy) {
                    for (long long dz = -1; dz <= 1 && cohort_index == cohorts.size(); ++dz) {
                        const auto found = cells.find({
                            std::get<0>(cell) + dx, std::get<1>(cell) + dy, std::get<2>(cell) + dz
                        });
                        if (found == cells.end()) continue;
                        for (const std::size_t candidate : found->second) {
                            if (distance_squared_vec3(point, cohorts[candidate].original) <= tolerance * tolerance) {
                                cohort_index = candidate;
                                break;
                            }
                        }
                    }
                }
            }
            if (cohort_index == cohorts.size()) {
                cells[cell].push_back(cohort_index);
                cohorts.push_back(Cohort{point, point, item.second, {}});
            }
            Cohort& cohort = cohorts[cohort_index];
            cohort.clearance = std::max(cohort.clearance, item.second);
            cohort.vertices.push_back({index, vertex});
            if (fitting_masks && refit.garment_settings.at(index).mode == "rigid_component") cohort.mobility=0.0;
            if (fitting_masks) cohort.mobility = std::min(cohort.mobility,
                mesh_editor_refit_mask_weight(*fitting_masks, index, vertex));
            indices.push_back(cohort_index);
        }
    }
    if (fitting_masks) for (const auto& item : refit.garment_settings) {
        if (clearances.count(item.first)) continue;
        for (std::size_t vertex=0;vertex<residual.at(item.first).size();++vertex) {
            const auto part_layer=layer.find(item.first);
            const Vec3 point=add_vec3(residual.at(item.first)[vertex],part_layer==layer.end()?Vec3{}:part_layer->second[vertex]);
            const auto cell=mesh_editor_refit_cell(point,tolerance);
            for (int x=-1;x<=1;++x) for (int y=-1;y<=1;++y) for (int z=-1;z<=1;++z) {
                const auto found=cells.find({std::get<0>(cell)+x,std::get<1>(cell)+y,std::get<2>(cell)+z});
                if (found==cells.end()) continue;
                for (const auto i:found->second)
                    if (distance_squared_vec3(point,cohorts[i].original)<=tolerance*tolerance) cohorts[i].mobility=0.0;
            }
        }
    }
    struct SurfaceSample {
        std::array<std::size_t, 3> corners;
        Vec3 weights;
    };
    struct LayerConstraint {
        SurfaceSample first;
        SurfaceSample second;
        Vec3 rest_offset;
        Vec3 normal;
        double limit = 0.0;
    };
    const auto sample_point = [&](const SurfaceSample& sample, bool original) {
        Vec3 point{0.0, 0.0, 0.0};
        for (std::size_t corner = 0; corner < 3; ++corner) {
            const Cohort& cohort = cohorts[sample.corners[corner]];
            point = add_vec3(point, scale_vec3(original ? cohort.original : cohort.position, sample.weights[corner]));
        }
        return point;
    };
    // Shape constraints use the narrowed silhouette. Layer order must instead
    // come from the followed garment, before conforming can bring shells through
    // one another. Otherwise an intermediate crossing becomes the required order.
    std::vector<Vec3> layer_rest;
    for (const auto& cohort : cohorts) {
        const auto vertex = cohort.vertices.front();
        Vec3 point = cohort.original;
        if (layer_reference) {
            const auto found = layer_reference->find(vertex.first);
            point = add_vec3(residual.at(vertex.first)[vertex.second],
                found == layer_reference->end() ? Vec3{} : found->second[vertex.second]);
        }
        layer_rest.push_back(point);
    }
    const auto layer_sample_point = [&](const SurfaceSample& sample) {
        Vec3 point{};
        for (int corner = 0; corner < 3; ++corner)
            point = add_vec3(point, scale_vec3(layer_rest[sample.corners[corner]], sample.weights[corner]));
        return point;
    };
    std::set<std::pair<std::size_t, std::size_t>> edges;
    std::map<std::pair<std::size_t, std::size_t>, int> edge_faces;
    std::map<std::pair<std::size_t, std::size_t>, std::vector<std::size_t>> edge_opposites;
    std::map<int, MeshSessionSubmesh> garments;
    std::vector<double> contact_mass(cohorts.size(), 0.0);
    std::map<std::pair<std::size_t,std::size_t>,double> contact_weights;
    for (const auto& item : clearances) {
        auto& garment = garments[item.first];
        for (const auto index : vertex_cohorts.at(item.first)) garment.vertices.push_back(cohorts[index].original);
        garment.faces = submeshes.at(item.first).faces;
        for (const auto& face : garment.faces) {
            const Vec3 normal = refit_face_normal_native(garment.vertices[face[0]], garment.vertices[face[1]], garment.vertices[face[2]]);
            if (dot_vec3(normal, normal) < 0.5) continue;
            if (fitting_masks) for (int c=0;c<3;++c) {
                const auto& map = vertex_cohorts.at(item.first);
                const Vec3 a = sub_vec3(garment.vertices[face[(c+1)%3]],garment.vertices[face[c]]);
                const Vec3 b = sub_vec3(garment.vertices[face[(c+2)%3]],garment.vertices[face[c]]);
                const double area = length_vec3(Vec3{a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]});
                contact_mass[map[face[c]]] += area/6.0;
                if (area > 1.0e-20) contact_weights[std::minmax(map[face[(c+1)%3]],map[face[(c+2)%3]])]
                    += std::max(0.0,dot_vec3(a,b)/area)*0.5;
            }
            for (std::size_t corner = 0; corner < 3; ++corner) {
                const auto first = vertex_cohorts.at(item.first)[face[corner]];
                const auto second = vertex_cohorts.at(item.first)[face[(corner + 1) % 3]];
                cohorts[first].has_surface = true;
                if (first != second) {
                    edges.insert(std::minmax(first, second));
                    ++edge_faces[std::minmax(first, second)];
                    edge_opposites[std::minmax(first, second)].push_back(vertex_cohorts.at(item.first)[face[(corner + 2) % 3]]);
                }
            }
        }
    }
    // Opposite triangle corners resist sharp new creases without locking the
    // authored folds or preventing the surface from wrapping around a limb.
    std::set<std::pair<std::size_t, std::size_t>> bending_edges;
    for (const auto& item : edge_opposites) {
        if (item.second.size() == 2 && item.second[0] != item.second[1]) {
            bending_edges.insert(std::minmax(item.second[0], item.second[1]));
        }
    }
    // Surface normals describe a sleeve's outside, but also the tiny radius
    // of a solid vine or trim. Only guide a wrap through an opening large
    // enough for that correction, measured separately for each component.
    std::vector<std::size_t> surface_roots, opening_roots;
    for (std::size_t index = 0; index < cohorts.size(); ++index) {
        surface_roots.push_back(index);
        opening_roots.push_back(index);
    }
    const auto root_of = [](std::vector<std::size_t>& roots, std::size_t index) {
        while (roots[index] != index) {
            roots[index] = roots[roots[index]];
            index = roots[index];
        }
        return index;
    };
    for (const auto& edge : edges) {
        surface_roots[root_of(surface_roots, edge.first)] = root_of(surface_roots, edge.second);
        if (edge_faces.at(edge) == 1) {
            opening_roots[root_of(opening_roots, edge.first)] = root_of(opening_roots, edge.second);
        }
    }
    std::map<std::size_t, std::pair<Vec3, Vec3>> opening_bounds;
    for (const auto& edge : edges) {
        if (edge_faces.at(edge) != 1) continue;
        for (const auto index : {edge.first, edge.second}) {
            const Vec3& point = cohorts[index].original;
            auto& bounds = opening_bounds.try_emplace(root_of(opening_roots, index), point, point).first->second;
            for (std::size_t axis = 0; axis < 3; ++axis) {
                bounds.first[axis] = std::min(bounds.first[axis], point[axis]);
                bounds.second[axis] = std::max(bounds.second[axis], point[axis]);
            }
        }
    }
    std::vector<double> opening_reach(cohorts.size(), 0.0);
    for (const auto& item : opening_bounds) {
        auto& reach = opening_reach[root_of(surface_roots, item.first)];
        reach = std::max(reach, length_vec3(sub_vec3(item.second.second, item.second.first)));
    }
    std::vector<LayerConstraint> layer_constraints;
    auto layer_garments = garments;
    for (auto& item : layer_garments) {
        const auto& indices = vertex_cohorts.at(item.first);
        for (std::size_t i = 0; i < indices.size(); ++i) item.second.vertices[i] = layer_rest[indices[i]];
    }
    std::vector<std::vector<std::size_t>> layer_neighbors(cohorts.size());
    for (const auto& edge : edges) {
        layer_neighbors[edge.first].push_back(edge.second);
        layer_neighbors[edge.second].push_back(edge.first);
    }
    // Infer local layer order from the authored surfaces, including samples
    // inside coarse outer-shell triangles. Material names do not establish
    // which surface is outside. Only couple nearby surfaces facing the body.
    for (const auto& target : layer_garments) {
        if (target.second.faces.empty()) continue;
        const auto target_index = build_refit_spatial_index_native(layer_garments, {target.first});
        std::vector<double> authored_side(cohorts.size(), 0.0);
        std::vector<Vec3> authored_normal(cohorts.size());
        if (fitting_masks) for (std::size_t i = 0; i < cohorts.size(); ++i) {
            long long tests = 0;
            const auto nearest = closest_refit_binding_native(layer_rest[i], target_index, tests);
            if (nearest.distance > refit.driver_diagonal * 0.03) continue;
            const auto& face = nearest.driver_vertices;
            const auto& points = target.second.vertices;
            authored_normal[i] = refit_face_normal_native(points[face[0]], points[face[1]], points[face[2]]);
            authored_side[i] = dot_vec3(sub_vec3(layer_rest[i], points[face[0]]), authored_normal[i]);
        }
        const auto bind_layer = [&](const SurfaceSample& sample) {
            const Vec3 point = layer_sample_point(sample);
            long long candidate_tests = 0;
            const auto nearest = closest_refit_binding_native(point, target_index, candidate_tests);
            if (nearest.distance > refit.driver_diagonal * 0.03) return;
            SurfaceSample other{{}, nearest.barycentric};
            for (std::size_t corner = 0; corner < 3; ++corner) {
                other.corners[corner] = vertex_cohorts.at(target.first)[nearest.driver_vertices[corner]];
                for (std::size_t source = 0; source < 3; ++source) {
                    if (sample.weights[source] > 0.0 && sample.corners[source] == other.corners[corner]) return;
                }
            }
            const Vec3 normal = refit_face_normal_native(
                layer_rest[other.corners[0]], layer_rest[other.corners[1]], layer_rest[other.corners[2]]
            );
            const double height = dot_vec3(sub_vec3(point, layer_sample_point(other)), normal);
            // Near-coincident material skins are attachments, not measurable
            // separated shells. Their field links retain the join; assigning a
            // hard side from micrometre-scale source rounding creates chatter.
            const double order_epsilon = fitting_masks
                ? std::max(tolerance * 4.0, refit.driver_diagonal * 1.0e-5) : tolerance * 4.0;
            if (std::abs(height) <= order_epsilon || std::abs(height) < nearest.distance * 0.15) return;
            if (fitting_masks && length_vec3(sub_vec3(sub_vec3(point, layer_sample_point(other)),
                    scale_vec3(normal, height))) > tolerance * 4.0) return;
            // Intersecting authored trim has no consistent layer order in this
            // neighborhood. Its displacement links preserve the construction;
            // conflicting hard half-spaces would tear it apart or inflate it.
            if (fitting_masks) for (int c = 0; c < 3; ++c) {
                if (sample.weights[c] <= 0.0) continue;
                for (const auto neighbor : layer_neighbors[sample.corners[c]])
                    if (height * authored_side[neighbor] < -tolerance * tolerance
                        && dot_vec3(normal, authored_normal[neighbor]) > 0.5) return;
            }
            // A sleeve near the waist is not another layer of the vest. Require
            // both samples to lie over the same local, outward-facing body region.
            const auto first_body = closest_refit_binding_native(point, spatial_index, candidate_tests);
            const auto second_body = closest_refit_binding_native(layer_sample_point(other), spatial_index, candidate_tests);
            if (dot_vec3(refit_binding_face_normal_native(first_body, driver_visible),
                         refit_binding_face_normal_native(second_body, driver_visible)) < 0.5) return;
            const double region_radius = std::max(nearest.distance * 2.0, refit.driver_diagonal * 0.05);
            if (distance_squared_vec3(mesh_editor_refit_driver_point(first_body, driver_visible),
                                      mesh_editor_refit_driver_point(second_body, driver_visible)) > region_radius * region_radius) return;
            layer_constraints.push_back({sample, other, sub_vec3(point, layer_sample_point(other)), normal, 0.25 * std::abs(height)});
        };
        for (const auto& source : garments) {
            if (source.first == target.first) continue;
            const auto& indices = vertex_cohorts.at(source.first);
            for (const auto index : std::set<std::size_t>(indices.begin(), indices.end())) {
                bind_layer({{index, index, index}, {1.0, 0.0, 0.0}});
            }
            std::set<std::pair<std::size_t, std::size_t>> sampled_edges;
            for (const auto& face : source.second.faces) {
                const std::array<std::size_t, 3> corners{indices[face[0]], indices[face[1]], indices[face[2]]};
                bind_layer({corners, {1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0}});
                for (std::size_t corner = 0; corner < 3; ++corner) {
                    sampled_edges.insert(std::minmax(corners[corner], corners[(corner + 1) % 3]));
                }
            }
            for (const auto& edge : sampled_edges) {
                bind_layer({{edge.first, edge.second, edge.second}, {0.5, 0.5, 0.0}});
            }
        }
    }
    if (fitting_masks) for (const auto& constraint : layer_constraints) {
        // Contact must carry nearby shells together. Coupling their displacement
        // fields retains the measured standoff without smoothing either surface.
        for (int a=0;a<3;++a) for (int b=0;b<3;++b) {
            const auto i=constraint.first.corners[a],j=constraint.second.corners[b];
            const double influence=constraint.first.weights[a]*constraint.second.weights[b];
            if (i==j || influence<=0.0) continue;
            const double distance=distance_squared_vec3(cohorts[i].original,cohorts[j].original);
            const double area=std::min(contact_mass[i],contact_mass[j]);
            contact_weights[std::minmax(i,j)] += influence*area/std::max(area,distance);
        }
    }
    // Resolve contacts from the authored shape. Spreading an initial maximum
    // lift over the body also inflated clear shoulders and loose sleeve folds.
    std::map<int, std::vector<Vec3>> normals;
    std::map<Vec3, std::size_t> body_welds;
    std::map<int, std::vector<std::size_t>> body_vertices;
    std::vector<Vec3> body_points;
    std::vector<Vec3> body_vertex_normals;
    std::map<std::pair<std::size_t, std::size_t>, Vec3> body_edge_normals;
    std::map<std::pair<std::size_t, std::size_t>, int> body_edge_windings;
    for (const auto& item : driver_visible) {
        auto& vertices = body_vertices[item.first];
        for (const auto& point : item.second) {
            auto found = body_welds.emplace(point, body_welds.size());
            if (found.second) {
                body_points.push_back(point);
                body_vertex_normals.push_back({0.0, 0.0, 0.0});
            }
            vertices.push_back(found.first->second);
        }
        for (const auto& face : drivers.at(item.first).faces) {
            const Vec3 normal = refit_face_normal_native(item.second[face[0]], item.second[face[1]], item.second[face[2]]);
            for (std::size_t corner = 0; corner < 3; ++corner) {
                const auto first = vertices[face[corner]];
                const auto second = vertices[face[(corner + 1) % 3]];
                if (first != second) body_edge_windings[std::minmax(first, second)] += first < second ? 1 : -1;
                const Vec3 a = sub_vec3(item.second[face[(corner + 1) % 3]], item.second[face[corner]]);
                const Vec3 b = sub_vec3(item.second[face[(corner + 2) % 3]], item.second[face[corner]]);
                const double length = length_vec3(a) * length_vec3(b);
                if (length <= 0.0) continue;
                const double angle = std::acos(std::clamp(dot_vec3(a, b) / length, -1.0, 1.0));
                body_vertex_normals[first] = add_vec3(body_vertex_normals[first], scale_vec3(normal, angle));
                auto& edge_normal = body_edge_normals[std::minmax(first, second)];
                edge_normal = add_vec3(edge_normal, normal);
            }
        }
    }
    for (const auto& item : body_vertices) {
        for (const auto vertex : item.second) normals[item.first].push_back(body_vertex_normals[vertex]);
    }
    std::vector<std::pair<std::pair<std::size_t, std::size_t>, int>> body_boundary;
    for (const auto& edge : body_edge_windings) if (edge.second != 0) body_boundary.push_back(edge);
    const Vec3 boundary_center = scale_vec3(add_vec3(spatial_index.nodes[spatial_index.root].minimum,
        spatial_index.nodes[spatial_index.root].maximum), 0.5);
    const auto enclosed_body_region = [&](const Vec3& point) {
        // Capping each oriented boundary edge to one common point completes a
        // closed triangle chain. Its distance from an integer winding matches
        // the body's, without summing the entire body at every sample.
        // This works on either side of the surface, including cloth that only
        // enters the body later during shape relaxation.
        double angle = 0.0;
        const Vec3 c = sub_vec3(boundary_center, point);
        const double lc = length_vec3(c);
        for (const auto& edge : body_boundary) {
            const Vec3 a = sub_vec3(body_points[edge.first.first], point);
            const Vec3 b = sub_vec3(body_points[edge.first.second], point);
            const double la = length_vec3(a), lb = length_vec3(b);
            const Vec3 cross{b[1] * c[2] - b[2] * c[1], b[2] * c[0] - b[0] * c[2], b[0] * c[1] - b[1] * c[0]};
            angle += edge.second * 2.0 * std::atan2(dot_vec3(a, cross),
                la * lb * lc + dot_vec3(a, b) * lc + dot_vec3(b, c) * la + dot_vec3(c, a) * lb);
        }
        const double full_angle = 4.0 * std::acos(-1.0);
        return std::abs(angle - full_angle * std::round(angle / full_angle)) <= full_angle * 0.02;
    };
    const auto body_contact_normal = [&](const MeshRefitVertexBindingRuntime& nearest, const Vec3& point) {
        Vec3 normal = refit_binding_face_normal_native(nearest, driver_visible);
        const auto& vertices = body_vertices.at(nearest.driver_submesh_index);
        std::vector<std::size_t> support;
        for (std::size_t corner = 0; corner < 3; ++corner) {
            if (nearest.barycentric[corner] > 1.0e-7) support.push_back(vertices[nearest.driver_vertices[corner]]);
        }
        if (support.size() == 1) normal = body_vertex_normals[support[0]];
        else if (support.size() == 2) normal = body_edge_normals.at(std::minmax(support[0], support[1]));
        const Vec3 offset = sub_vec3(point, mesh_editor_refit_driver_point(nearest, driver_visible));
        const double distance = length_vec3(offset);
        // The pseudonormal establishes inside/outside at a shared edge. The
        // shortest surface direction then clears it without sliding sideways.
        if (distance > tolerance) return scale_vec3(offset, (dot_vec3(offset, normal) < 0.0 ? -1.0 : 1.0) / distance);
        const double length = length_vec3(normal);
        return length > 0.0 ? scale_vec3(normal, 1.0 / length) : refit_binding_face_normal_native(nearest, driver_visible);
    };
    struct BodyExit {
        Vec3 direction{0.0, 0.0, 0.0};
        double distance = std::numeric_limits<double>::infinity();
    };
    const auto body_exit = [&](const Vec3& point, const Vec3& direction, double clearance) {
        BodyExit result;
        // Avoid an exact shared edge or vertex when counting oriented crossings.
        result.direction = add_vec3(direction, Vec3{0.000073, 0.000037, 0.000019});
        result.direction = scale_vec3(result.direction, 1.0 / length_vec3(result.direction));
        std::vector<std::pair<double, int>> crossings;
        int winding = 0;
        for (const auto& hit : refit_surface_line_hits_native(point, result.direction, refit.driver_diagonal * 2.0, spatial_index)) {
            double distance = dot_vec3(sub_vec3(mesh_editor_refit_driver_point(hit, driver_visible), point), result.direction);
            const double alignment = dot_vec3(refit_binding_face_normal_native(hit, driver_visible), result.direction);
            if (std::abs(alignment) <= 1.0e-8) continue;
            const int crossing = alignment > 0.0 ? 1 : -1;
            // Include the clearance shell before merging occupied intervals;
            // exiting one surface into a narrower gap would hit the next one.
            distance += crossing * clearance / std::max(0.05, std::abs(alignment));
            if (distance <= tolerance * 0.1) continue;
            crossings.push_back({distance, crossing});
            winding += crossing;
        }
        if (winding <= 0) return result;
        std::sort(crossings.begin(), crossings.end());
        for (const auto& crossing : crossings) {
            winding -= crossing.second;
            if (winding <= 0) {
                result.distance = crossing.first;
                break;
            }
        }
        return result;
    };
    std::vector<double> body_node_areas(spatial_index.nodes.size(), 0.0);
    for (std::size_t index = spatial_index.nodes.size(); index-- > 0;) {
        const auto& node = spatial_index.nodes[index];
        if (node.left >= 0 && node.right >= 0) {
            body_node_areas[index] = body_node_areas[node.left] + body_node_areas[node.right];
        } else for (std::size_t position = node.begin; position < node.end; ++position) {
            const auto& triangle = spatial_index.triangles[spatial_index.triangle_order[position]];
            const Vec3 a = sub_vec3(triangle.corners[1], triangle.corners[0]);
            const Vec3 b = sub_vec3(triangle.corners[2], triangle.corners[0]);
            const Vec3 cross{a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
            body_node_areas[index] += 0.5 * length_vec3(cross);
        }
    }
    const auto inside_body_volume = [&](const Vec3& point) {
        // A ray through a remote opening can report a false interior. Confirm
        // ambiguous contacts with the body's total oriented solid angle.
        double angle = 0.0;
        double remaining = 0.0;
        const double threshold = 2.0 * std::acos(-1.0);
        std::vector<std::pair<double, int>> pending;
        const auto push = [&](int index) {
            const auto& node = spatial_index.nodes[index];
            const double distance = refit_aabb_distance_squared_native(point, node.minimum, node.maximum);
            const double bound = std::min(threshold * (node.end - node.begin),
                distance > 0.0 ? body_node_areas[index] / distance : std::numeric_limits<double>::infinity());
            remaining += bound;
            pending.push_back({bound, index});
            std::push_heap(pending.begin(), pending.end());
        };
        push(spatial_index.root);
        while (!pending.empty()) {
            // Area / squared distance bounds each unvisited solid angle. Skip
            // the remaining triangles only when they cannot change the result.
            if (angle + remaining < threshold - 1.0e-6) return false;
            if (angle - remaining > threshold + 1.0e-6) return true;
            std::pop_heap(pending.begin(), pending.end());
            const auto current = pending.back();
            pending.pop_back();
            remaining = std::max(0.0, remaining - current.first);
            const auto& node = spatial_index.nodes[current.second];
            if (node.left >= 0 && node.right >= 0) {
                push(node.left);
                push(node.right);
                continue;
            }
            for (std::size_t position = node.begin; position < node.end; ++position) {
                const auto& triangle = spatial_index.triangles[spatial_index.triangle_order[position]];
                const Vec3 a = sub_vec3(triangle.corners[0], point);
                const Vec3 b = sub_vec3(triangle.corners[1], point);
                const Vec3 c = sub_vec3(triangle.corners[2], point);
                const Vec3 cross{b[1] * c[2] - b[2] * c[1], b[2] * c[0] - b[0] * c[2], b[0] * c[1] - b[1] * c[0]};
                const double la = length_vec3(a), lb = length_vec3(b), lc = length_vec3(c);
                angle += 2.0 * std::atan2(dot_vec3(a, cross),
                    la * lb * lc + dot_vec3(a, b) * lc + dot_vec3(b, c) * la + dot_vec3(c, a) * lb);
            }
        }
        return angle > threshold;
    };
    // Point-only garments have no surface on which to infer layer links. Keep
    // their existing shared lift on each driver face, preserving point offsets.
    std::map<std::pair<int, std::array<int, 3>>, double> point_lifts;
    std::map<std::size_t, MeshRefitVertexBindingRuntime> point_bindings;
    for (std::size_t index = 0; index < cohorts.size(); ++index) {
        const Cohort& cohort = cohorts[index];
        if (cohort.has_surface) continue;
        long long candidate_tests = 0;
        const auto nearest = closest_refit_binding_native(cohort.original, spatial_index, candidate_tests);
        const Vec3 normal = refit_binding_face_normal_native(nearest, driver_visible);
        const double missing = cohort.clearance - dot_vec3(
            sub_vec3(cohort.original, mesh_editor_refit_driver_point(nearest, driver_visible)), normal
        );
        auto& lift = point_lifts[{nearest.driver_submesh_index, nearest.driver_vertices}];
        lift = std::max(lift, missing);
        point_bindings[index] = nearest;
    }
    for (const auto& item : point_bindings) {
        const auto& binding = item.second;
        auto& cohort = cohorts[item.first];
        cohort.position = add_vec3(cohort.original, scale_vec3(refit_binding_face_normal_native(binding, driver_visible),
            point_lifts.at({binding.driver_submesh_index, binding.driver_vertices})));
    }
    struct BodyConstraint {
        SurfaceSample sample;
        double clearance = 0.0;
        double preferred_reach = 0.0;
        Vec3 preferred_direction{0.0, 0.0, 0.0};
        Vec3 checked_position{0.0, 0.0, 0.0};
        double free_radius = 0.0;
    };
    struct BodyAnchor {
        SurfaceSample sample;
        Vec3 point;
        Vec3 normal;
        double clearance = 0.0;
        double reach = 0.0;
        double orientation = 1.0;
        Vec3 checked_position{0.0, 0.0, 0.0};
        double free_radius = 0.0;
    };
    struct BodyProbe {
        Vec3 point;
        Vec3 normal;
        double reach = 0.0;
    };
    std::vector<BodyProbe> body_probes;
    for (const auto& item : driver_visible) {
        for (std::size_t vertex = 0; vertex < item.second.size(); ++vertex) {
            const Vec3 point = item.second[vertex];
            Vec3 normal = normals.at(item.first)[vertex];
            const double length = length_vec3(normal);
            if (length <= tolerance) continue;
            normal = scale_vec3(normal, 1.0 / length);
            double reach = refit.driver_diagonal * 0.25;
            // Stop at this body's first opposite surface. A ray must not cross
            // the armpit or the space between legs to pull another panel.
            for (const auto& hit : refit_surface_line_hits_native(point, normal, reach, spatial_index)) {
                const double distance = dot_vec3(sub_vec3(mesh_editor_refit_driver_point(hit, driver_visible), point), normal);
                if (distance < -tolerance * 4.0) reach = std::min(reach, -distance);
            }
            body_probes.push_back({point, normal, reach});
        }
    }
    std::vector<BodyAnchor> body_anchors;
    std::set<int> surface_garments;
    std::map<int, double> garment_orientation;
    for (const auto& item : garments) {
        if (std::any_of(vertex_cohorts.at(item.first).begin(), vertex_cohorts.at(item.first).end(),
                [&](std::size_t index) { return cohorts[index].has_surface; })) surface_garments.insert(item.first);
        double alignment = 0.0, area_sum = 0.0;
        for (const auto& face : item.second.faces) {
            const auto& a = item.second.vertices[face[0]];
            const auto& b = item.second.vertices[face[1]];
            const auto& c = item.second.vertices[face[2]];
            const Vec3 normal = refit_face_normal_native(a, b, c);
            const Vec3 center = scale_vec3(add_vec3(a, add_vec3(b, c)), 1.0 / 3.0);
            long long candidate_tests = 0;
            const auto nearest = closest_refit_binding_native(center, spatial_index, candidate_tests);
            const Vec3 body_normal = refit_binding_face_normal_native(nearest, driver_visible);
            if (dot_vec3(sub_vec3(center, mesh_editor_refit_driver_point(nearest, driver_visible)), body_normal) < -clearances.at(item.first)) continue;
            const Vec3 first = sub_vec3(b, a), second = sub_vec3(c, a);
            const double dot = dot_vec3(first, second);
            const double area = std::sqrt(std::max(0.0, dot_vec3(first, first) * dot_vec3(second, second) - dot * dot));
            alignment += area * dot_vec3(normal, body_normal);
            area_sum += area;
        }
        garment_orientation[item.first] = alignment < -0.1 * area_sum ? -1.0 : 1.0;
    }
    auto garment_index = build_refit_spatial_index_native(garments, surface_garments);
    const auto refresh_body_anchors = [&] {
        body_anchors.clear();
        if (surface_garments.empty()) return;
        for (auto& item : garments) {
            const auto& indices = vertex_cohorts.at(item.first);
            for (std::size_t vertex = 0; vertex < indices.size(); ++vertex) item.second.vertices[vertex] = cohorts[indices[vertex]].position;
        }
        update_refit_spatial_index_native(garment_index, garments);
        for (const auto& probe : body_probes) {
            const Vec3 point = probe.point;
            const Vec3 normal = probe.normal;
            long long candidate_tests = 0;
            std::vector<Vec3> accepted;
            for (const auto& nearest : refit_surface_line_hits_native(point, normal, probe.reach, garment_index)) {
                SurfaceSample sample{{}, nearest.barycentric};
                for (std::size_t corner = 0; corner < 3; ++corner) {
                    sample.corners[corner] = vertex_cohorts.at(nearest.driver_submesh_index)[nearest.driver_vertices[corner]];
                }
                const Vec3 contact = sample_point(sample, false);
                const double clearance = clearances.at(nearest.driver_submesh_index);
                if (dot_vec3(sub_vec3(contact, point), normal) >= clearance) continue;
                bool boundary = false;
                for (std::size_t corner = 0; corner < 3; ++corner) {
                    if (sample.weights[corner] > 1.0e-7) continue;
                    const auto edge = std::minmax(sample.corners[(corner + 1) % 3], sample.corners[(corner + 2) % 3]);
                    const auto count = edge_faces.find(edge);
                    if (count == edge_faces.end() || count->second < 2) boundary = true;
                }
                if (boundary) continue;
                const Vec3 garment_normal = refit_face_normal_native(
                    cohorts[sample.corners[0]].position, cohorts[sample.corners[1]].position, cohorts[sample.corners[2]].position
                );
                const double orientation = garment_orientation.at(nearest.driver_submesh_index);
                if (orientation * dot_vec3(normal, garment_normal) < 0.3) continue;
                const auto region = closest_refit_binding_native(contact, spatial_index, candidate_tests);
                const Vec3 region_normal = body_contact_normal(region, contact);
                if (dot_vec3(normal, region_normal) < 0.3) continue;
                if (dot_vec3(sub_vec3(contact, mesh_editor_refit_driver_point(region, driver_visible)), region_normal) >= clearance) continue;
                const double local_reach = std::max(region.distance * 2.0, clearance * 4.0);
                if (distance_squared_vec3(point, contact) > local_reach * local_reach) continue;
                if (std::any_of(accepted.begin(), accepted.end(), [&](const Vec3& value) {
                        return distance_squared_vec3(contact, value) <= tolerance * tolerance;
                    })) continue;
                accepted.push_back(contact);
                body_anchors.push_back({sample, point, normal, clearance, probe.reach, orientation});
            }
        }
    };
    std::vector<Vec3> garment_normals(cohorts.size(), Vec3{0.0, 0.0, 0.0});
    const auto build_garment_normals = [&]() {
        std::fill(garment_normals.begin(), garment_normals.end(), Vec3{0.0, 0.0, 0.0});
        for (const auto& item : garments) {
            const auto& indices = vertex_cohorts.at(item.first);
            for (const auto& face : item.second.faces) {
                const std::array<Vec3, 3> points{{cohorts[indices[face[0]]].position,
                    cohorts[indices[face[1]]].position, cohorts[indices[face[2]]].position}};
                const Vec3 normal = scale_vec3(refit_face_normal_native(points[0], points[1], points[2]),
                    garment_orientation.at(item.first));
                for (std::size_t corner = 0; corner < 3; ++corner) {
                    const Vec3 a = sub_vec3(points[(corner + 1) % 3], points[corner]);
                    const Vec3 b = sub_vec3(points[(corner + 2) % 3], points[corner]);
                    const double length = length_vec3(a) * length_vec3(b);
                    if (length <= 0.0) continue;
                    const double angle = std::acos(std::clamp(dot_vec3(a, b) / length, -1.0, 1.0));
                    auto& value = garment_normals[indices[face[corner]]];
                    value = add_vec3(value, scale_vec3(normal, angle));
                }
            }
        }
        for (std::size_t index = 0; index < garment_normals.size(); ++index) {
            auto& normal = garment_normals[index];
            const double length = length_vec3(normal);
            if (length > tolerance) normal = scale_vec3(normal, 1.0 / length);
        }
    };
    build_garment_normals();
    std::vector<BodyConstraint> body_constraints;
    const auto add_body_constraint = [&](const SurfaceSample& sample, double clearance) {
        double reach = 0.0;
        Vec3 direction{0.0, 0.0, 0.0};
        for (std::size_t corner = 0; corner < 3; ++corner) {
            reach += sample.weights[corner] * opening_reach[root_of(surface_roots, sample.corners[corner])];
            direction = add_vec3(direction, scale_vec3(garment_normals[sample.corners[corner]], sample.weights[corner]));
        }
        const double length = length_vec3(direction);
        if (length > tolerance) direction = scale_vec3(direction, 1.0 / length);
        if (reach > tolerance && !enclosed_body_region(sample_point(sample, true))) reach = 0.0;
        body_constraints.push_back({sample, clearance, reach, direction});
    };
    for (std::size_t index = 0; index < cohorts.size(); ++index) {
        add_body_constraint({{index, index, index}, {1.0, 0.0, 0.0}}, cohorts[index].clearance);
    }
    for (const auto& edge : edges) {
        add_body_constraint({{edge.first, edge.second, edge.second}, {0.5, 0.5, 0.0}},
            std::max(cohorts[edge.first].clearance, cohorts[edge.second].clearance));
    }
    for (const auto& item : clearances) {
        const auto& indices = vertex_cohorts.at(item.first);
        for (const auto& face : submeshes.at(item.first).faces) {
            const std::array<std::size_t, 3> corners{indices[face[0]], indices[face[1]], indices[face[2]]};
            if (corners[0] == corners[1] || corners[0] == corners[2] || corners[1] == corners[2]) continue;
            add_body_constraint({corners, {1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0}}, item.second);
        }
    }
    const auto project_layers = [&](double& maximum_correction) {
        for (const auto& constraint : layer_constraints) {
            const Vec3 point = sample_point(constraint.first, false);
            const Vec3& a = cohorts[constraint.second.corners[0]].position;
            const Vec3& b = cohorts[constraint.second.corners[1]].position;
            const Vec3& c = cohorts[constraint.second.corners[2]].position;
            const Vec3 normal = refit_face_normal_native(a, b, c);
            const double height = dot_vec3(sub_vec3(point, a), normal);
            const double rest_height = dot_vec3(constraint.rest_offset, constraint.normal);
            const double order = rest_height > 0.0 ? 1.0 : -1.0;
            const double missing = std::abs(rest_height) - constraint.limit - order * height;
            if (missing <= tolerance) continue;
            // Keep the authored layer order without pulling an already-clear
            // belt or trim back toward a surface that moved away from it.
            const double correction = -order * missing;
            SurfaceSample other = constraint.second;
            other.weights = closest_triangle_point_native(point, a, b, c).barycentric;
            const Vec3 offset = sub_vec3(point, sample_point(other, false));
            // A nearby open edge does not cover a point past that edge.
            if (length_vec3(sub_vec3(offset, scale_vec3(normal, height)))
                    > (fitting_masks ? tolerance * 4.0 : refit.driver_diagonal * 0.005)) continue;
            maximum_correction = std::max(maximum_correction, std::abs(correction));
            double weight_squared = 0.0;
            for (int c = 0; c < 3; ++c) {
                weight_squared += constraint.first.weights[c] * constraint.first.weights[c]
                    * (fitting_masks ? cohorts[constraint.first.corners[c]].mobility : 1.0);
                weight_squared += other.weights[c] * other.weights[c]
                    * (fitting_masks ? cohorts[other.corners[c]].mobility : 1.0);
            }
            if (weight_squared <= 0.0) continue;
            const Vec3 delta = scale_vec3(normal, correction / weight_squared);
            for (std::size_t corner = 0; corner < 3; ++corner) {
                Cohort& first = cohorts[constraint.first.corners[corner]];
                Cohort& second = cohorts[other.corners[corner]];
                first.position = sub_vec3(first.position, scale_vec3(delta, constraint.first.weights[corner] * (fitting_masks ? first.mobility : 1.0)));
                second.position = add_vec3(second.position, scale_vec3(delta, other.weights[corner] * (fitting_masks ? second.mobility : 1.0)));
            }
        }
    };
    // Solve shape and contour constraints first, then use the final passes
    // only for sample clearance. Cohorts keep UV/material seams joined.
    constexpr int wrap_iterations = 16;
    constexpr int shape_iterations = 256;
    const int clearance_iterations = fitting_masks ? 512 : 256;
    for (int iteration = 0; !validate_only && iteration < shape_iterations + clearance_iterations; ++iteration) {
        std::vector<Vec3> previous;
        if (fitting_masks) for (const auto& cohort : cohorts) previous.push_back(cohort.position);
        if (iteration < shape_iterations && iteration % 64 == 0) refresh_body_anchors();
        double maximum_correction = 0.0;
        // The conformed silhouette already supplies the shape target. Pulling
        // contacts back into that penetrating pose fights a larger body's fit.
        const double attraction = fitting_masks ? 0.0 : 0.08 * std::max(0.0, 1.0 - iteration / 128.0);
        for (Cohort& cohort : cohorts) {
            if (!cohort.has_surface) continue;
            const Vec3 delta = scale_vec3(sub_vec3(cohort.original, cohort.position), attraction);
            cohort.position = add_vec3(cohort.position, delta);
            maximum_correction = std::max(maximum_correction, length_vec3(delta));
        }
        if (iteration < shape_iterations || fitting_masks) project_layers(maximum_correction);
        // Limit stretching and collapse while allowing edges to rotate around
        // the body. Locking displacement directions would pin a folded cuff
        // inside a hand even when it can bend clear without excessive stretch.
        for (int relaxation = 0; relaxation < (iteration < shape_iterations ? 3 : 0); ++relaxation) {
            for (const auto& edge : bending_edges) {
                Cohort& first = cohorts[edge.first];
                Cohort& second = cohorts[edge.second];
                const double rest_length = length_vec3(sub_vec3(second.original, first.original));
                const Vec3 current = sub_vec3(second.position, first.position);
                const double length = length_vec3(current);
                if (length <= tolerance) continue;
                const double target = std::clamp(length, rest_length * 0.75, rest_length * 1.5);
                if (std::abs(length - target) <= tolerance) continue;
                const Vec3 delta = scale_vec3(current, 0.1 * (length - target) / length);
                first.position = add_vec3(first.position, delta);
                second.position = sub_vec3(second.position, delta);
                maximum_correction = std::max(maximum_correction, length_vec3(delta));
            }
            for (const auto& edge : edges) {
                Cohort& first = cohorts[edge.first];
                Cohort& second = cohorts[edge.second];
                const Vec3 rest_edge = sub_vec3(second.original, first.original);
                const Vec3 current_edge = sub_vec3(second.position, first.position);
                const double rest_length = length_vec3(rest_edge);
                const double length = length_vec3(current_edge);
                const double target = std::clamp(length, rest_length * 0.75, rest_length * 1.5);
                if (std::abs(length - target) <= tolerance) continue;
                maximum_correction = std::max(maximum_correction, std::abs(length - target));
                const Vec3 direction = length > tolerance ? scale_vec3(current_edge, 1.0 / length) : scale_vec3(rest_edge, 1.0 / rest_length);
                const Vec3 delta = scale_vec3(direction, 0.5 * (length - target));
                first.position = add_vec3(first.position, delta);
                second.position = sub_vec3(second.position, delta);
            }
        }
        // Resolve body contact last so shape preservation cannot leave a cuff
        // inside the hand at the bounded iteration limit.
        if (iteration < shape_iterations) for (auto& anchor : body_anchors) {
            SurfaceSample sample = anchor.sample;
            const Vec3& a = cohorts[sample.corners[0]].position;
            const Vec3& b = cohorts[sample.corners[1]].position;
            const Vec3& c = cohorts[sample.corners[2]].position;
            MeshEditorScreenRay ray;
            const double reach = anchor.reach;
            ray.origin = add_vec3(anchor.point, scale_vec3(anchor.normal, reach));
            ray.direction = scale_vec3(anchor.normal, -1.0);
            double distance = 0.0;
            if (!mesh_editor_ray_intersects_triangle(ray, a, b, c, distance) || distance > reach * 2.0) continue;
            const Vec3 hit = add_vec3(ray.origin, scale_vec3(ray.direction, distance));
            sample.weights = closest_triangle_point_native(hit, a, b, c).barycentric;
            const Vec3 point = sample_point(sample, false);
            if (distance_squared_vec3(point, anchor.checked_position) < anchor.free_radius * anchor.free_radius) continue;
            const Vec3 normal = scale_vec3(refit_face_normal_native(a, b, c), anchor.orientation);
            if (dot_vec3(normal, anchor.normal) < 0.3) continue;
            const double missing = anchor.clearance - dot_vec3(sub_vec3(point, anchor.point), normal);
            if (missing <= 0.0) continue;
            long long candidate_tests = 0;
            const auto nearest = closest_refit_binding_native(point, spatial_index, candidate_tests);
            const Vec3 body_normal = body_contact_normal(nearest, point);
            const double body_gap = dot_vec3(sub_vec3(point, mesh_editor_refit_driver_point(nearest, driver_visible)), body_normal);
            anchor.checked_position = point;
            anchor.free_radius = body_gap >= anchor.clearance ? std::max(0.0, nearest.distance - anchor.clearance) : 0.0;
            if (body_gap >= anchor.clearance || dot_vec3(normal, body_normal) < 0.3) continue;
            const double local_reach = std::max(nearest.distance * 2.0, anchor.clearance * 4.0);
            if (distance_squared_vec3(anchor.point, point) > local_reach * local_reach) continue;
            maximum_correction = std::max(maximum_correction, missing);
            const double weight_squared = dot_vec3(sample.weights, sample.weights);
            for (std::size_t corner = 0; corner < 3; ++corner) {
                auto& cohort = cohorts[sample.corners[corner]];
                cohort.position = add_vec3(cohort.position, scale_vec3(normal, missing * sample.weights[corner] / weight_squared));
            }
        }
        // Evaluate body contacts at one common pose. Sequential projections
        // otherwise choose conflicting exits around an armpit and crease cloth.
        std::vector<Vec3> contact_delta(fitting_masks ? cohorts.size() : 0);
        std::vector<double> contact_count(fitting_masks ? cohorts.size() : 0, 0.0);
        for (auto& constraint : body_constraints) {
            const double contact_clearance = constraint.clearance
                + (fitting_masks ? std::max(tolerance*8.0,constraint.clearance*0.1) : 0.0);
            const Vec3 point = sample_point(constraint.sample, false);
            // The nearest-surface distance bounds a collision-free ball around
            // an exterior sample. Reuse it until the sample leaves that ball;
            // the body is fixed throughout this individual fit operation.
            if (distance_squared_vec3(point, constraint.checked_position) < constraint.free_radius * constraint.free_radius) continue;
            long long candidate_tests = 0;
            const auto nearest = closest_refit_binding_native(point, spatial_index, candidate_tests);
            Vec3 normal = body_contact_normal(nearest, point);
            const Vec3 surface = mesh_editor_refit_driver_point(nearest, driver_visible);
            const double height = dot_vec3(sub_vec3(point, surface), normal);
            double missing = contact_clearance - height;
            BodyExit exit = body_exit(point, normal, contact_clearance);
            // An internal arm/torso face is not an exit from their combined
            // volume. Search nearby directions when that face hides another
            // body surface, rather than forcing the cloth across the torso.
            if (std::isfinite(exit.distance) && exit.distance > std::max(0.0, missing) + tolerance * 16.0) {
                const Vec3 trial = add_vec3(point, scale_vec3(normal, std::max(0.0, missing)));
                const auto trial_nearest = closest_refit_binding_native(trial, spatial_index, candidate_tests);
                const double trial_height = dot_vec3(sub_vec3(trial, mesh_editor_refit_driver_point(trial_nearest, driver_visible)),
                    body_contact_normal(trial_nearest, trial));
                if (trial_height < contact_clearance - tolerance || inside_body_volume(trial)) {
                    for (int x = -1; x <= 1; ++x) for (int y = -1; y <= 1; ++y) for (int z = -1; z <= 1; ++z) {
                        if (x == 0 && y == 0 && z == 0) continue;
                        const Vec3 direction{static_cast<double>(x), static_cast<double>(y), static_cast<double>(z)};
                        const BodyExit candidate = body_exit(point, direction, contact_clearance);
                        if (candidate.distance < exit.distance) exit = candidate;
                    }
                    normal = exit.direction;
                    missing = exit.distance + tolerance * 2.0;
                }
            }
            // Use the authored direction to establish the wrap early. Keeping
            // this hint after the cloth has bent can drive folded trim away.
            if (iteration < wrap_iterations && missing > tolerance && constraint.preferred_reach > tolerance) {
                Vec3 direction = constraint.preferred_direction;
                const double length = length_vec3(direction);
                if (length > tolerance && dot_vec3(direction, normal) < length * 0.5) {
                    direction = scale_vec3(direction, 1.0 / length);
                    const BodyExit preferred = body_exit(point, direction, contact_clearance);
                    if (std::isfinite(preferred.distance) && preferred.distance <= std::min(missing * 2.0, constraint.preferred_reach)) {
                        const double distance = preferred.distance + tolerance * 2.0;
                        const Vec3 trial = add_vec3(point, scale_vec3(preferred.direction, distance));
                        const auto trial_nearest = closest_refit_binding_native(trial, spatial_index, candidate_tests);
                        const double trial_height = dot_vec3(sub_vec3(trial, mesh_editor_refit_driver_point(trial_nearest, driver_visible)),
                            body_contact_normal(trial_nearest, trial));
                        if (trial_height >= contact_clearance - tolerance) {
                            normal = preferred.direction;
                            missing = distance;
                        }
                    }
                }
            }
            constraint.checked_position = point;
            constraint.free_radius = missing <= 0.0 ? std::max(0.0, nearest.distance - contact_clearance) : 0.0;
            if (missing <= 0.0) continue;
            maximum_correction = std::max(maximum_correction, missing);
            const double weight_squared = dot_vec3(constraint.sample.weights, constraint.sample.weights);
            for (std::size_t corner = 0; corner < 3; ++corner) {
                Cohort& cohort = cohorts[constraint.sample.corners[corner]];
                const double weight = constraint.sample.weights[corner];
                if (weight <= 0.0) continue;
                const Vec3 delta = scale_vec3(normal, missing * weight / weight_squared);
                if (fitting_masks) {
                    const auto i = constraint.sample.corners[corner];
                    contact_delta[i] = add_vec3(contact_delta[i], delta);
                    contact_count[i] += 1.0;
                } else cohort.position = add_vec3(cohort.position, delta);
            }
        }
        if (fitting_masks) {
            for (std::size_t i = 0; i < cohorts.size(); ++i)
                if (contact_count[i] > 0.0) cohorts[i].position = add_vec3(cohorts[i].position,
                    scale_vec3(contact_delta[i], 1.0 / contact_count[i]));
            // Contact on one vertex of a small folded face must move its local
            // cloth neighborhood too. Smooth contact displacements, then limit
            // the step before it can turn a triangle over. Rest constraints here
            // refer to the conformed silhouette, not the oversized garment.
            std::vector<Vec3> correction(cohorts.size());
            for (std::size_t i = 0; i < cohorts.size(); ++i) {
                correction[i] = sub_vec3(cohorts[i].position, previous[i]);
            }
            try {
                // Large corrections need a wider patch to move around a limb;
                // small residuals need local freedom to finish contact and trim.
                const double smoothing_length = refit.driver_diagonal * 0.012;
                const double contact_length = std::clamp(maximum_correction * 2.0,
                    iteration < shape_iterations ? smoothing_length : smoothing_length * 0.1,
                    refit.driver_diagonal * 0.05);
                correction = mesh_editor_smooth_refit_contact(correction,contact_mass,contact_weights,
                    contact_length * contact_length);
            } catch (const std::runtime_error& error) {
                std::string parts;
                for (const auto& part:clearances) parts+=(parts.empty()?"":", ")+std::to_string(part.first);
                throw std::runtime_error("Fit to body: Parts " + parts + ": " + error.what());
            }
            for (std::size_t i = 0; i < cohorts.size(); ++i)
                cohorts[i].position = add_vec3(previous[i], scale_vec3(correction[i], cohorts[i].mobility));
            // Smoothing a common body lift must not erase layer separation.
            project_layers(maximum_correction);
            bool guarded = false;
            int guarded_part = clearances.begin()->first;
            // Neighboring strain projections can oppose one another. Reduce
            // the common step and retry within the same bounded solve.
            for (int backtrack = 0; backtrack < 8 && !guarded; ++backtrack) {
                if (backtrack > 0) for (std::size_t i=0; i<cohorts.size(); ++i)
                    cohorts[i].position = add_vec3(previous[i], scale_vec3(sub_vec3(cohorts[i].position, previous[i]), 0.5));
                for (int guard = 0; guard < 24 && !guarded; ++guard) {
                    guarded = true;
                    for (const auto& item : clearances) {
                        const auto& map = vertex_cohorts.at(item.first);
                        for (const auto& face : submeshes.at(item.first).faces) {
                            const std::array<std::size_t,3> v{map[face[0]],map[face[1]],map[face[2]]};
                            const Vec3 rest_normal = refit_face_normal_native(previous[v[0]],previous[v[1]],previous[v[2]]);
                            if (dot_vec3(rest_normal,rest_normal) < 0.5) continue;
                            Vec3 transport{};
                            double mobility = 1.0;
                            for (const auto i : v) {
                                transport = add_vec3(transport, scale_vec3(sub_vec3(cohorts[i].position, previous[i]), 1.0 / 3.0));
                                mobility = std::min(mobility, cohorts[i].mobility);
                            }
                            if (mobility <= 0.0) transport = Vec3{};
                            const auto transported = [&](std::size_t i, double step) {
                                return add_vec3(previous[i], add_vec3(transport,
                                    scale_vec3(sub_vec3(sub_vec3(cohorts[i].position, previous[i]), transport), step)));
                            };
                            const auto safe = [&](double step) {
                                std::array<Vec3,3> point;
                                for (int c = 0; c < 3; ++c) point[c] = transported(v[c], step);
                                const Vec3 e1 = sub_vec3(previous[v[1]],previous[v[0]]);
                                const Vec3 e2 = sub_vec3(previous[v[2]],previous[v[0]]);
                                const Vec3 d1 = sub_vec3(sub_vec3(point[1],point[0]),e1);
                                const Vec3 d2 = sub_vec3(sub_vec3(point[2],point[0]),e2);
                                const auto projected_area = [&](double t) {
                                    const Vec3 a = add_vec3(e1,scale_vec3(d1,t));
                                    const Vec3 b = add_vec3(e2,scale_vec3(d2,t));
                                    return dot_vec3(rest_normal, Vec3{a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]});
                                };
                                // The projected area is quadratic throughout a linear
                                // step. Check its minimum, not just its endpoint.
                                const double c = projected_area(0.0), end = projected_area(1.0);
                                const double a = 2.0*(end+c-2.0*projected_area(0.5));
                                const double b = end-c-a;
                                const double t = a > 0.0 ? std::clamp(-b/(2.0*a),0.0,1.0) : 1.0;
                                if (std::min(end,projected_area(t)) < c*0.05) return false;
                                for (int c = 0; c < 3; ++c) {
                                    const double rest = distance_squared_vec3(cohorts[v[c]].original,cohorts[v[(c+1)%3]].original);
                                    const double now = distance_squared_vec3(point[c],point[(c+1)%3]);
                                    const double before = distance_squared_vec3(previous[v[c]], previous[v[(c+1)%3]]);
                                    // Recover shortened edges when clearing a larger
                                    // body, without attracting the garment to its old size.
                                    const double authored = distance_squared_vec3(layer_rest[v[c]], layer_rest[v[(c+1)%3]]);
                                    // An edge already at the limit must admit a rigid
                                    // translation despite floating-point subtraction.
                                    const double roundoff = std::max(tolerance*tolerance, rest*1.0e-10);
                                    if (rest > tolerance*tolerance && (now < std::min(rest*0.04, before) - roundoff
                                        || now > std::max({rest*4.0, authored*4.0, before}) + roundoff)) return false;
                                }
                                return true;
                            };
                            if (safe(1.0)) continue;
                            guarded_part = item.first;
                            guarded = false;
                            double low = 0.0, high = 1.0;
                            for (int step = 0; step < 12; ++step) {
                                const double middle = (low+high)*0.5;
                                if (safe(middle)) low = middle; else high = middle;
                            }
                            for (const auto i : v) cohorts[i].position = transported(i, low*0.95);
                        }
                }
                }
            }
            if (!guarded) throw std::runtime_error("Fit to body: Part "
                + std::to_string(guarded_part) + " cannot preserve its triangles during clearance correction");
        }
        if (maximum_correction <= tolerance) {
            if (iteration >= shape_iterations) break;
            refresh_body_anchors();
            if (body_anchors.empty()) break;
        }
    }
    if (fitting_masks) for (const auto& constraint : body_constraints) {
        const Vec3 point = sample_point(constraint.sample, false);
        long long tests = 0;
        const auto nearest = closest_refit_binding_native(point, spatial_index, tests);
        const double height = dot_vec3(sub_vec3(point, mesh_editor_refit_driver_point(nearest, driver_visible)),
            body_contact_normal(nearest, point));
        if ((height < -tolerance * 4.0 && inside_body_volume(point))
            || (nearest.distance < constraint.clearance - tolerance * 4.0)) {
            const auto& vertex = cohorts[constraint.sample.corners[0]].vertices.front();
            throw std::runtime_error("Fit to body: Part " + std::to_string(vertex.first)
                + ", vertex " + std::to_string(vertex.second) + " cannot clear the body with its current protection mask or geometry (gap "
                + std::to_string(height) + ", requested " + std::to_string(constraint.clearance) + ")");
        }
    }
    if (fitting_masks) for (const auto& constraint : layer_constraints) {
        const Vec3 point=sample_point(constraint.first,false);
        const auto& a=cohorts[constraint.second.corners[0]].position;
        const auto& b=cohorts[constraint.second.corners[1]].position;
        const auto& c=cohorts[constraint.second.corners[2]].position;
        const Vec3 normal=refit_face_normal_native(a,b,c);
        const double height=dot_vec3(sub_vec3(point,a),normal);
        auto closest=constraint.second;
        closest.weights=closest_triangle_point_native(point,a,b,c).barycentric;
        const Vec3 offset=sub_vec3(point,sample_point(closest,false));
        // A point past an open triangle edge does not overlap that layer.
        // Only its perpendicular projection onto the face can establish order.
        if (length_vec3(sub_vec3(offset,scale_vec3(normal,height))) > tolerance*4.0) continue;
        const double rest=dot_vec3(constraint.rest_offset,constraint.normal);
        // Apply the same contact tolerance as the body validator. Near-coincident
        // skins must not require sub-tolerance positive gaps while body contact
        // accepts that same numerical error on either side of its boundary.
        if ((rest > 0.0 ? height : -height) < -tolerance * 4.0) {
            throw std::runtime_error("Fit to body: Part "
                + std::to_string(cohorts[constraint.first.corners[0]].vertices.front().first)
                + " cannot preserve its garment layer separation from Part "
                + std::to_string(cohorts[constraint.second.corners[0]].vertices.front().first)
                + " (rest " + std::to_string(rest) + ", gap " + std::to_string(height)
                + ", vertex " + std::to_string(cohorts[constraint.first.corners[0]].vertices.front().second) + ")");
        }
    }
    for (const Cohort& cohort : cohorts) {
        const Vec3 delta = sub_vec3(cohort.position, cohort.original);
        for (const auto& vertex : cohort.vertices) {
            layer.at(vertex.first)[vertex.second] = add_vec3(layer.at(vertex.first)[vertex.second], delta);
        }
    }
}

void mesh_editor_conform_refit(
    const MeshRefitRuntime&, const std::map<int, MeshSessionSubmesh>&,
    const std::map<int, std::vector<Vec3>>&, const std::map<int, std::vector<Vec3>>&,
    const RefitMaskWeightsNative&, std::map<int, std::vector<Vec3>>&);
void mesh_editor_validate_conformed_refit(
    const MeshRefitRuntime&, const std::map<int, MeshSessionSubmesh>&,
    const std::map<int, std::vector<Vec3>>&, const std::map<int, std::vector<Vec3>>&,
    const std::map<int, std::vector<Vec3>>&, const char*,
    const std::map<int, std::vector<Vec3>>* = nullptr);

void mesh_editor_add_refit_layer(
    const MeshMorphRuntime& morph,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& residual,
    std::map<int, std::vector<Vec3>>& layer
) {
    if (!morph.refit) return;
    const auto base_layer = layer;
    const auto masks = mesh_editor_refit_masks(*morph.refit, residual);
    std::map<int, std::vector<Vec3>> driver_visible;
    for (const int driver_index : morph.refit->driver_submesh_indices) {
        const auto current = submeshes.find(driver_index);
        const auto residual_item = residual.find(driver_index);
        if (current == submeshes.end() || residual_item == residual.end()) {
            throw std::runtime_error("garment refit driver topology changed");
        }
        const std::vector<Vec3> zero = mesh_editor_zero_morph_layer(current->second.vertices.size());
        const std::vector<Vec3>& procedural = mesh_editor_morph_layer_for_submesh(layer, driver_index, zero);
        std::vector<Vec3>& visible = driver_visible[driver_index];
        visible.reserve(current->second.vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < current->second.vertices.size(); ++vertex_index) {
            visible.push_back(add_vec3(residual_item->second[vertex_index], procedural[vertex_index]));
        }
    }
    for (const MeshRefitVertexBindingRuntime& binding : morph.refit->bindings) {
        MeshRefitGarmentSettingsRuntime settings;
        const auto configured = morph.refit->garment_settings.find(binding.garment_submesh_index);
        if (configured != morph.refit->garment_settings.end()) settings = configured->second;
        if (!settings.enabled) continue;
        const auto target = submeshes.find(binding.garment_submesh_index);
        const auto target_residual = residual.find(binding.garment_submesh_index);
        if (target == submeshes.end() || target_residual == residual.end() || binding.garment_vertex_index < 0
            || static_cast<std::size_t>(binding.garment_vertex_index) >= target->second.vertices.size()) {
            throw std::runtime_error("garment refit target topology changed");
        }
        std::vector<Vec3>& target_layer = layer[binding.garment_submesh_index];
        if (target_layer.empty()) target_layer = mesh_editor_zero_morph_layer(target->second.vertices.size());
        const std::size_t target_vertex_index = static_cast<std::size_t>(binding.garment_vertex_index);
        const Vec3 current_point = mesh_editor_refit_driver_point(binding, driver_visible);
        const Vec3 baseline_point = mesh_editor_refit_driver_point(binding, morph.refit->driver_baseline_positions);
        Vec3 refit_delta = add_vec3(
            sub_vec3(current_point, baseline_point),
            refit_normal_correction_native(binding, driver_visible)
        );
        if (settings.mode == "rigid") {
            Vec3 rigid_delta{0.0, 0.0, 0.0};
            if (refit_rigid_delta_native(
                    binding, morph.refit->driver_baseline_positions, driver_visible, rigid_delta
                )) refit_delta = rigid_delta;
        }
        const double intensity = settings.mode == "rigid_component" ? 1.0 : settings.intensity_percent / 100.0;
        if (intensity != 1.0) refit_delta = scale_vec3(refit_delta, intensity);
        const double clearance = morph.refit->driver_diagonal * settings.clearance_percent / 100.0;
        if (clearance > 0.0 && settings.mode == "rigid") {
            // Clearance is measured toward the body's exterior even when a
            // garment was already inside the body when it was bound.
            const Vec3 outward = refit_binding_face_normal_native(binding, driver_visible);
            if (dot_vec3(outward, outward) > 0.0) {
                const Vec3 predicted = add_vec3(
                    add_vec3(target_residual->second[target_vertex_index], target_layer[target_vertex_index]),
                    refit_delta
                );
                const double signed_clearance = dot_vec3(sub_vec3(predicted, current_point), outward);
                if (signed_clearance < clearance) {
                    refit_delta = add_vec3(refit_delta, scale_vec3(outward, clearance - signed_clearance));
                }
            }
        }
        target_layer[target_vertex_index] = add_vec3(target_layer[target_vertex_index], refit_delta);
    }
    const bool tightening = std::any_of(morph.refit->garment_settings.begin(), morph.refit->garment_settings.end(),
        [](const auto& item) { return item.second.enabled && item.second.mode != "rigid" && item.second.tightness_percent > 0.0; });
    if (!tightening) mesh_editor_relieve_refit_surface(*morph.refit, submeshes, driver_visible, residual, layer);
    for (const auto& item : masks) {
        const auto settings = morph.refit->garment_settings.find(item.first);
        if (settings != morph.refit->garment_settings.end() && settings->second.mode == "rigid_component") continue;
        auto target = layer.find(item.first);
        if (target == layer.end()) continue;
        const auto original = base_layer.find(item.first);
        for (std::size_t vertex = 0; vertex < item.second.size(); ++vertex) {
            const Vec3 base = original == base_layer.end() ? Vec3{} : original->second[vertex];
            target->second[vertex] = add_vec3(base, scale_vec3(sub_vec3(target->second[vertex], base), item.second[vertex]));
        }
    }
    mesh_editor_refit_components(*morph.refit, submeshes, driver_visible, residual, base_layer, masks, layer);
    if (tightening) {
        const auto followed = layer;
        mesh_editor_conform_refit(*morph.refit, submeshes, driver_visible, residual, masks, layer);
        mesh_editor_refit_components(*morph.refit, submeshes, driver_visible, residual, followed, masks, layer, true);
        mesh_editor_validate_conformed_refit(*morph.refit, submeshes, residual, followed, layer, "conforming");
        const auto conformed = layer;
        mesh_editor_relieve_refit_surface(*morph.refit, submeshes, driver_visible, residual, layer, &masks, false, &followed);
        mesh_editor_validate_conformed_refit(*morph.refit, submeshes, residual, conformed, layer, "clearance", &followed);
    }
}

std::map<int, std::vector<Vec3>> mesh_editor_morph_residual_positions(
    const MeshMorphRuntime& morph,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::set<int>& indices
) {
    std::map<int, std::vector<Vec3>> residual;
    for (const int index : indices) {
        const auto current = submeshes.find(index);
        if (current == submeshes.end()) continue;
        const std::vector<Vec3> zero = mesh_editor_zero_morph_layer(current->second.vertices.size());
        const std::vector<Vec3>& old_layer = mesh_editor_morph_layer_for_submesh(morph.current_layer, index, zero);
        if (old_layer.size() != current->second.vertices.size()) {
            throw std::runtime_error("procedural morph topology changed without Bake or Reset");
        }
        const auto neutral = morph.neutral_positions.find(index);
        const auto composed = morph.composed_positions.find(index);
        const bool has_neutral = neutral != morph.neutral_positions.end()
            && composed != morph.composed_positions.end();
        if (has_neutral && (neutral->second.size() != current->second.vertices.size()
            || composed->second.size() != current->second.vertices.size())) {
            throw std::runtime_error("procedural morph neutral topology changed without Bake or Reset");
        }
        std::vector<Vec3>& values = residual[index];
        values.reserve(current->second.vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < current->second.vertices.size(); ++vertex_index) {
            if (!has_neutral) {
                // Legacy snapshots have no retained neutral coordinates.
                values.push_back(sub_vec3(current->second.vertices[vertex_index], old_layer[vertex_index]));
                continue;
            }
            Vec3 value = neutral->second[vertex_index];
            for (std::size_t axis = 0; axis < 3; ++axis) {
                const double visible = current->second.vertices[vertex_index][axis];
                const double anchor = composed->second[vertex_index][axis];
                if (visible != anchor) value[axis] += visible - anchor;
            }
            values.push_back(value);
        }
    }
    return residual;
}

std::set<int> mesh_editor_morph_runtime_indices(
    const MeshMorphRuntime& morph,
    const std::map<int, std::vector<Vec3>>& new_layer
) {
    std::set<int> indices;
    for (const auto& item : morph.current_layer) indices.insert(item.first);
    for (const auto& item : new_layer) indices.insert(item.first);
    if (morph.refit) {
        indices.insert(morph.refit->driver_submesh_indices.begin(), morph.refit->driver_submesh_indices.end());
        indices.insert(morph.refit->garment_submesh_indices.begin(), morph.refit->garment_submesh_indices.end());
    }
    return indices;
}

SubmeshMeshEditResult mesh_editor_morph_sparse_result(
    int submesh_index,
    MeshSessionSubmesh& submesh,
    const std::vector<Vec3>& before,
    const std::string& action,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshMeshEditResult result;
    result.index = submesh_index;
    result.action = action;
    result.sparse = true;
    result.resident_sparse = true;
    for (std::size_t vertex_index = 0; vertex_index < submesh.vertices.size(); ++vertex_index) {
        if (before[vertex_index] == submesh.vertices[vertex_index]) continue;
        result.changed_vertices.push_back(static_cast<int>(vertex_index));
        result.before_positions.push_back(before[vertex_index]);
        result.changed_positions.push_back(submesh.vertices[vertex_index]);
        result.changed_source_vertex_ids.push_back(
            submesh.source_vertex_map.size() == submesh.vertices.size()
                ? submesh.source_vertex_map[vertex_index]
                : static_cast<int>(vertex_index)
        );
    }
    if (!result.changed_vertices.empty()) {
        if (!submesh.faces.empty()) {
            submesh.normals = compute_smooth_normals(submesh.vertices, submesh.faces);
            result.preview_normals = submesh.normals;
        } else {
            submesh.normals.clear();
        }
        submesh.tangents.clear();
        submesh.tangent_signs.clear();
        mesh_editor_set_result_output_paths(result, delta_output_dir, session_id);
    }
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_recompose_morph(
    MeshEditorSession& session,
    MeshMorphRuntime& next,
    const std::string& action,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    std::map<int, MeshSessionSubmesh>& submeshes = mesh_editor_submeshes(session);
    std::map<int, std::vector<Vec3>> new_layer = mesh_editor_build_procedural_morph_layer(next, submeshes);
    const auto post_refit = mesh_editor_build_procedural_morph_layer(next, submeshes, true);
    std::set<int> indices = mesh_editor_morph_runtime_indices(*session.morph, new_layer);
    for (const auto& item : post_refit) indices.insert(item.first);
    if (next.refit) {
        indices.insert(next.refit->driver_submesh_indices.begin(), next.refit->driver_submesh_indices.end());
        indices.insert(next.refit->garment_submesh_indices.begin(), next.refit->garment_submesh_indices.end());
    }
    const std::map<int, std::vector<Vec3>> residual = mesh_editor_morph_residual_positions(*session.morph, submeshes, indices);
    mesh_editor_add_refit_layer(next, submeshes, residual, new_layer);
    const auto masks = next.refit ? mesh_editor_refit_masks(*next.refit, residual) : RefitMaskWeightsNative{};
    const bool check_corrections = next.refit && !post_refit.empty()
        && std::any_of(next.refit->garment_settings.begin(),next.refit->garment_settings.end(),
            [](const auto& item) { return item.second.enabled && item.second.mode!="rigid" && item.second.tightness_percent>0.0; })
        && std::any_of(post_refit.begin(),post_refit.end(),[](const auto& part) {
            return std::any_of(part.second.begin(),part.second.end(),[](const Vec3& value) { return dot_vec3(value,value)>0.0; });
        });
    const auto fitted_layer = check_corrections ? new_layer : std::map<int,std::vector<Vec3>>{};
    for (const auto& item : post_refit) {
        // Corrections belong to an enabled garment binding. Clearing refit must
        // remove their displacement, not expose previously masked corrections.
        if (!next.refit || !next.refit->garment_submesh_indices.count(item.first)) continue;
        const auto settings = next.refit->garment_settings.find(item.first);
        if (settings != next.refit->garment_settings.end() && !settings->second.enabled) continue;
        auto& target = new_layer[item.first];
        if (target.empty()) target = mesh_editor_zero_morph_layer(item.second.size());
        for (std::size_t vertex = 0; vertex < target.size(); ++vertex) {
            target[vertex] = add_vec3(target[vertex], scale_vec3(item.second[vertex],
                mesh_editor_refit_mask_weight(masks, item.first, vertex)));
        }
    }
    if (check_corrections) {
        std::map<int,std::vector<Vec3>> driver_visible;
        for (const int part:next.refit->driver_submesh_indices) {
            const auto body_layer=new_layer.find(part);
            for (std::size_t i=0;i<residual.at(part).size();++i)
                driver_visible[part].push_back(add_vec3(residual.at(part)[i],
                    body_layer==new_layer.end()?Vec3{}:body_layer->second[i]));
        }
        mesh_editor_validate_conformed_refit(*next.refit,submeshes,residual,fitted_layer,new_layer,"garment correction");
        mesh_editor_relieve_refit_surface(*next.refit,submeshes,driver_visible,residual,new_layer,&masks,true,&fitted_layer);
    }
    for (const auto& item : new_layer) indices.insert(item.first);
    std::vector<SubmeshMeshEditResult> results;
    for (const int index : indices) {
        auto current = submeshes.find(index);
        const auto residual_item = residual.find(index);
        if (current == submeshes.end() || residual_item == residual.end()) continue;
        const std::vector<Vec3> before = current->second.vertices;
        const std::vector<Vec3> zero = mesh_editor_zero_morph_layer(before.size());
        const std::vector<Vec3>& layer = mesh_editor_morph_layer_for_submesh(new_layer, index, zero);
        if (layer.size() != before.size()) throw std::runtime_error("procedural morph layer size mismatch");
        for (std::size_t vertex_index = 0; vertex_index < before.size(); ++vertex_index) {
            current->second.vertices[vertex_index] = add_vec3(residual_item->second[vertex_index], layer[vertex_index]);
        }
        SubmeshMeshEditResult result = mesh_editor_morph_sparse_result(
            index, current->second, before, action, delta_output_dir, session_id
        );
        if (!result.changed_vertices.empty()) results.push_back(std::move(result));
        next.neutral_positions[index] = residual_item->second;
        next.composed_positions[index] = current->second.vertices;
    }
    next.current_layer = std::move(new_layer);
    next.unbaked = mesh_editor_morph_layer_has_value(next.current_layer);
    return results;
}

MeshEditorSubmeshDelta mesh_editor_morph_history_delta(
    const MeshSessionSubmesh& before,
    const MeshSessionSubmesh& after
) {
    MeshEditorSubmeshDelta delta;
    delta.vertices = mesh_editor_make_channel_delta(before.vertices, after.vertices);
    delta.normals = mesh_editor_make_channel_delta(before.normals, after.normals);
    delta.tangents = mesh_editor_make_channel_delta(before.tangents, after.tangents);
    delta.tangent_signs = mesh_editor_make_channel_delta(before.tangent_signs, after.tangent_signs);
    return delta;
}

bool mesh_editor_publish_morph_history(
    MeshEditorSession& session,
    MeshEditorHistoryEntry entry,
    const std::map<int, MeshSessionSubmesh>& before,
    const std::string& change_id,
    bool coalesce
) {
    const auto& after = mesh_editor_submeshes(session);
    for (const auto& item : before) {
        const auto current = after.find(item.first);
        if (current == after.end()) continue;
        MeshEditorSubmeshDelta delta = mesh_editor_morph_history_delta(item.second, current->second);
        if (!mesh_editor_submesh_delta_empty(delta)) entry.deltas[item.first] = std::move(delta);
    }
    entry.morph_after = session.morph;
    entry.morph_state_changed = true;
    entry.stroke_id = change_id;
    if (coalesce && !change_id.empty() && !session.undo_stack.empty()) {
        MeshEditorHistoryEntry& previous = session.undo_stack.back();
        if (previous.operation == entry.operation && previous.stroke_id == change_id && !previous.topology_changed) {
            for (const auto& item : entry.deltas) {
                const auto found = previous.deltas.find(item.first);
                if (found != previous.deltas.end() && !mesh_editor_can_merge_submesh_delta(found->second, item.second)) {
                    throw std::runtime_error("procedural morph history could not coalesce its sparse delta");
                }
            }
            for (const auto& item : entry.deltas) {
                const auto found = previous.deltas.find(item.first);
                if (found == previous.deltas.end()) previous.deltas[item.first] = item.second;
                else (void)mesh_editor_merge_submesh_delta(found->second, item.second);
            }
            previous.morph_after = entry.morph_after;
            previous.stroke_update_count += 1;
            session.redo_stack.clear();
            mesh_editor_trim_session_history(session);
            return false;
        }
    }
    mesh_editor_push_history(session.undo_stack, std::move(entry));
    session.redo_stack.clear();
    mesh_editor_trim_session_history(session);
    return true;
}

void mesh_editor_write_morph_index_set(std::ostream& out, const std::set<int>& indices) {
    out << '[';
    bool wrote = false;
    for (const int index : indices) {
        if (wrote) out << ',';
        wrote = true;
        out << index;
    }
    out << ']';
}

void mesh_editor_write_refit_settings(std::ostream& out, const MeshRefitRuntime& refit) {
    out << '[';
    bool wrote = false;
    for (const int submesh_index : refit.garment_submesh_indices) {
        MeshRefitGarmentSettingsRuntime settings;
        const auto found = refit.garment_settings.find(submesh_index);
        if (found != refit.garment_settings.end()) settings = found->second;
        if (wrote) out << ',';
        wrote = true;
        out << "{\"submesh_index\":" << submesh_index
            << ",\"enabled\":" << (settings.enabled ? "true" : "false")
            << ",\"intensity_percent\":" << std::setprecision(17) << settings.intensity_percent
            << ",\"mode\":";
        write_escaped(out, settings.mode);
        out << ",\"clearance_percent\":" << std::setprecision(17) << settings.clearance_percent
            << ",\"tightness_percent\":" << settings.tightness_percent << '}';
    }
    out << ']';
}

void mesh_editor_write_refit_constraints(std::ostream& out, const MeshRefitRuntime& refit) {
    out << ",\"vertex_masks\":[";
    bool wrote = false;
    for (const auto& item : refit.vertex_masks) {
        if (wrote) out << ',';
        wrote = true;
        out << "{\"submesh_index\":" << item.first << ",\"vertex_indices\":[";
        bool first = true;
        for (const auto& entry : item.second) { if (!first) out << ','; first = false; out << entry.first; }
        out << "],\"weights\":[";
        first = true;
        for (const auto& entry : item.second) { if (!first) out << ','; first = false; out << std::setprecision(17) << entry.second; }
        out << "]}";
    }
    out << "],\"garment_regions\":[";
    wrote = false;
    for (const auto& garment : refit.garment_regions) {
        if (wrote) out << ',';
        wrote = true;
        out << "{\"garment_submesh_index\":" << garment.first << ",\"driver_regions\":[";
        bool first = true;
        for (const auto& region : garment.second) {
            if (!first) out << ',';
            first = false;
            out << "{\"submesh_index\":" << region.first << ",\"vertex_indices\":";
            mesh_editor_write_morph_index_set(out, region.second);
            out << '}';
        }
        out << "]}";
    }
    out << ']';
}

void mesh_editor_write_morph_state(std::ostream& out, const MeshEditorSession& session) {
    const MeshMorphRuntime empty;
    const MeshMorphRuntime& morph = session.morph ? *session.morph : empty;
    out << "{\"profile_id\":";
    write_escaped(out, morph.profile ? morph.profile->profile_id : std::string());
    out << ",\"preset_id\":";
    write_escaped(out, morph.preset_id);
    out << ",\"values\":{";
    bool wrote = false;
    for (const auto& item : morph.values) {
        if (wrote) out << ',';
        wrote = true;
        write_escaped(out, item.first);
        out << ':' << std::setprecision(17) << item.second;
    }
    out << "},\"driver_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, morph.driver_submesh_indices);
    out << ",\"refit\":{";
    if (morph.refit) {
        out << "\"driver_submesh_indices\":";
        mesh_editor_write_morph_index_set(out, morph.refit->driver_submesh_indices);
        out << ",\"garment_submesh_indices\":";
        mesh_editor_write_morph_index_set(out, morph.refit->garment_submesh_indices);
        out << ",\"bound_vertex_count\":" << morph.refit->bindings.size()
            << ",\"maximum_distance\":" << std::setprecision(17) << morph.refit->maximum_distance
            << ",\"p95_distance\":" << morph.refit->p95_distance
            << ",\"warning_distance\":" << morph.refit->warning_distance
            << ",\"distance_warning\":" << (morph.refit->distance_warning ? "true" : "false")
            << ",\"driver_triangle_count\":" << morph.refit->driver_triangle_count
            << ",\"candidate_triangle_tests\":" << morph.refit->candidate_triangle_tests
            << ",\"garment_settings\":";
        mesh_editor_write_refit_settings(out, *morph.refit);
        mesh_editor_write_refit_constraints(out, *morph.refit);
    } else {
        out << "\"driver_submesh_indices\":[],\"garment_submesh_indices\":[],\"bound_vertex_count\":0,"
               "\"maximum_distance\":0,\"p95_distance\":0,\"warning_distance\":0,\"distance_warning\":false,"
               "\"driver_triangle_count\":0,\"candidate_triangle_tests\":0,\"garment_settings\":[]";
    }
    out << "},\"unbaked\":" << (morph.unbaked ? "true" : "false")
        << ",\"topology_blocked\":" << (morph.unbaked ? "true" : "false")
        << ",\"busy\":" << (!morph.active_change_id.empty() ? "true" : "false")
        << ",\"failure\":\"\",\"diagnostics\":[";
    if (morph.refit && morph.refit->distance_warning) {
        write_escaped(out, "Garment refit binding distances exceed the existing spatial warning threshold.");
    }
    out << "],\"state_revision\":" << morph.state_revision
        << ",\"edit_revision\":" << session.edit_revision
        << ",\"change_id\":";
    write_escaped(out, morph.change_id);
    out << '}';
}

constexpr const char* MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_SCHEMA =
    "cdmw_mesh_editor_morph_runtime_snapshot_v1";

std::uint32_t mesh_editor_snapshot_rotr(std::uint32_t value, int count) {
    return (value >> count) | (value << (32 - count));
}

std::string mesh_editor_snapshot_sha256(const std::string& payload) {
    static constexpr std::array<std::uint32_t, 64> constants{
        0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U,
        0xab1c5ed5U, 0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU,
        0x9bdc06a7U, 0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU,
        0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
        0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
        0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U, 0xa2bfe8a1U, 0xa81a664bU,
        0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U,
        0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
        0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U,
        0xc67178f2U,
    };
    std::array<std::uint32_t, 8> digest{
        0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
        0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U,
    };
    if (payload.size() > (std::numeric_limits<std::uint64_t>::max() / 8ULL)) {
        throw std::runtime_error("morph runtime snapshot payload is too large to hash");
    }
    const std::uint64_t bit_length = static_cast<std::uint64_t>(payload.size()) * 8ULL;
    const std::size_t padded_size = ((payload.size() + 9ULL + 63ULL) / 64ULL) * 64ULL;
    for (std::size_t block_start = 0; block_start < padded_size; block_start += 64ULL) {
        std::array<std::uint32_t, 64> words{};
        for (std::size_t word_index = 0; word_index < 16; ++word_index) {
            std::uint32_t word = 0;
            for (std::size_t byte_index = 0; byte_index < 4; ++byte_index) {
                const std::size_t offset = block_start + word_index * 4ULL + byte_index;
                unsigned char value = 0;
                if (offset < payload.size()) {
                    value = static_cast<unsigned char>(payload[offset]);
                } else if (offset == payload.size()) {
                    value = 0x80U;
                } else if (offset >= padded_size - 8ULL) {
                    const std::size_t shift = (padded_size - 1ULL - offset) * 8ULL;
                    value = static_cast<unsigned char>((bit_length >> shift) & 0xffU);
                }
                word = (word << 8U) | static_cast<std::uint32_t>(value);
            }
            words[word_index] = word;
        }
        for (std::size_t index = 16; index < words.size(); ++index) {
            const std::uint32_t s0 = mesh_editor_snapshot_rotr(words[index - 15], 7)
                ^ mesh_editor_snapshot_rotr(words[index - 15], 18)
                ^ (words[index - 15] >> 3U);
            const std::uint32_t s1 = mesh_editor_snapshot_rotr(words[index - 2], 17)
                ^ mesh_editor_snapshot_rotr(words[index - 2], 19)
                ^ (words[index - 2] >> 10U);
            words[index] = words[index - 16] + s0 + words[index - 7] + s1;
        }
        std::uint32_t a = digest[0];
        std::uint32_t b = digest[1];
        std::uint32_t c = digest[2];
        std::uint32_t d = digest[3];
        std::uint32_t e = digest[4];
        std::uint32_t f = digest[5];
        std::uint32_t g = digest[6];
        std::uint32_t h = digest[7];
        for (std::size_t index = 0; index < words.size(); ++index) {
            const std::uint32_t sum1 = mesh_editor_snapshot_rotr(e, 6)
                ^ mesh_editor_snapshot_rotr(e, 11)
                ^ mesh_editor_snapshot_rotr(e, 25);
            const std::uint32_t choose = (e & f) ^ ((~e) & g);
            const std::uint32_t temp1 = h + sum1 + choose + constants[index] + words[index];
            const std::uint32_t sum0 = mesh_editor_snapshot_rotr(a, 2)
                ^ mesh_editor_snapshot_rotr(a, 13)
                ^ mesh_editor_snapshot_rotr(a, 22);
            const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
            const std::uint32_t temp2 = sum0 + majority;
            h = g;
            g = f;
            f = e;
            e = d + temp1;
            d = c;
            c = b;
            b = a;
            a = temp1 + temp2;
        }
        digest[0] += a;
        digest[1] += b;
        digest[2] += c;
        digest[3] += d;
        digest[4] += e;
        digest[5] += f;
        digest[6] += g;
        digest[7] += h;
    }
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (const std::uint32_t value : digest) out << std::setw(8) << value;
    return out.str();
}
