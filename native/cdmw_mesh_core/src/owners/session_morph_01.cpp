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

std::map<int, std::vector<Vec3>> mesh_editor_refit_seam_positions_for_parts(
    const std::set<int>& part_indices,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& residual,
    double tolerance,
    bool unique_matches
) {
    // Independently quantized material Parts can store one sewn border at
    // slightly different positions. Recognize matching boundary EDGES, rather
    // than welding every nearby vertex and accidentally joining thin layers.
    // These positions are grouping keys only; retain the authored coordinates.
    std::map<Vec3, std::size_t> lookup;
    std::vector<Vec3> points;
    std::map<int, std::vector<std::size_t>> indices;
    for (const int part : part_indices) {
        for (const auto& point : residual.at(part)) {
            const auto entry = lookup.emplace(point, points.size());
            if (entry.second) points.push_back(point);
            indices[part].push_back(entry.first->second);
        }
    }
    std::vector<std::size_t> roots(points.size());
    std::iota(roots.begin(), roots.end(), 0);
    const auto root_of = [&](std::size_t index) {
        while (roots[index] != index) index = roots[index] = roots[roots[index]];
        return index;
    };
    const auto join = [&](std::size_t a, std::size_t b) {
        a = root_of(a); b = root_of(b);
        if (distance_squared_vec3(points[a], points[b]) <= tolerance * tolerance)
            roots[std::max(a, b)] = std::min(a, b);
    };
    struct Border { int part; std::size_t a, b; Vec3 normal; };
    std::vector<Border> borders;
    for (const int part : part_indices) {
        const auto& map = indices.at(part);
        std::map<std::pair<std::size_t, std::size_t>, std::vector<Border>> edges;
        for (const auto& face : submeshes.at(part).faces) {
            const Vec3 normal = refit_face_normal_native(points[map[face[0]]], points[map[face[1]]], points[map[face[2]]]);
            for (int c = 0; c < 3; ++c) {
                const auto a = map[face[c]], b = map[face[(c+1)%3]];
                if (a != b) edges[std::minmax(a,b)].push_back({part, a, b, normal});
            }
        }
        for (const auto& edge : edges) if (edge.second.size() == 1) borders.push_back(edge.second.front());
    }
    // Only reciprocal single matches can become seams. Retain one candidate
    // and a saturated 0/1/many count so dense ambiguous borders use linear
    // storage instead of retaining every candidate pair.
    std::vector<std::size_t> match_candidates(unique_matches ? borders.size() : 0);
    std::vector<unsigned char> match_counts(unique_matches ? borders.size() : 0, 0);
    const auto record_match = [&](std::size_t edge, std::size_t candidate) {
        if (match_counts[edge] == 0) match_candidates[edge] = candidate;
        if (match_counts[edge] < 2) ++match_counts[edge];
    };
    std::map<std::tuple<long long, long long, long long>, std::vector<std::size_t>> cells;
    for (std::size_t i = 0; i < borders.size(); ++i) {
        const auto& edge = borders[i];
        if (distance_squared_vec3(points[edge.a], points[edge.b]) < tolerance*tolerance*64.0) continue;
        const auto cell = mesh_editor_refit_cell(points[edge.a], tolerance);
        for (int x=-1; x<=1; ++x) for (int y=-1; y<=1; ++y) for (int z=-1; z<=1; ++z) {
            const auto found = cells.find({std::get<0>(cell)+x, std::get<1>(cell)+y, std::get<2>(cell)+z});
            if (found == cells.end()) continue;
            for (const auto j : found->second) {
                const auto& other = borders[j];
                // Adjacent faces traverse a shared edge in opposite directions.
                // Parallel shell rims and back-to-back linings are not seams.
                if (edge.part == other.part
                    || dot_vec3(edge.normal, other.normal) <= (unique_matches ? 0.5 : 0.0)) continue;
                if (distance_squared_vec3(points[edge.a], points[other.b]) > tolerance*tolerance
                    || distance_squared_vec3(points[edge.b], points[other.a]) > tolerance*tolerance) continue;
                if (unique_matches) {
                    record_match(i, j);
                    record_match(j, i);
                } else {
                    join(edge.a, other.b);
                    join(edge.b, other.a);
                }
            }
        }
        cells[mesh_editor_refit_cell(points[edge.b], tolerance)].push_back(i);
    }
    if (unique_matches) for (std::size_t i = 0; i < match_counts.size(); ++i) {
        if (match_counts[i] != 1) continue;
        const auto j = match_candidates[i];
        if (j <= i || match_counts[j] != 1 || match_candidates[j] != i) continue;
        join(borders[i].a, borders[j].b);
        join(borders[i].b, borders[j].a);
    }
    std::map<int, std::vector<Vec3>> result;
    for (const auto& item : indices)
        for (const auto index : item.second) result[item.first].push_back(points[root_of(index)]);
    return result;
}

std::map<int, std::vector<Vec3>> mesh_editor_refit_seam_positions(
    const MeshRefitRuntime& refit,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& residual
) {
    std::set<int> garments;
    for (const auto& item : refit.garment_settings) garments.insert(item.first);
    return mesh_editor_refit_seam_positions_for_parts(garments, submeshes, residual,
        std::max(1.0e-6, refit.driver_diagonal * 2.0e-5), false);
}

std::map<int, std::vector<Vec3>> mesh_editor_refit_body_seam_positions(
    const MeshRefitRuntime& refit,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& driver_visible
) {
    // Use the established scale-relative precision window only for uniquely
    // paired, reversed boundary edges with compatible normals. Ambiguous nearby
    // body surfaces remain separate. These keys never replace source positions.
    return mesh_editor_refit_seam_positions_for_parts(refit.driver_submesh_indices,
        submeshes, driver_visible, std::max(1.0e-6, refit.driver_diagonal * 2.0e-5), true);
}

std::vector<std::size_t> mesh_editor_refit_surface_roots(
    const std::map<int, MeshSessionSubmesh>& garments,
    const std::map<int, std::vector<std::size_t>>& indices,
    std::size_t count
) {
    // Use the fitter's seam cohorts, not proximity between arbitrary surfaces.
    std::vector<std::size_t> roots(count);
    std::iota(roots.begin(), roots.end(), 0);
    const auto root_of = [&](std::size_t i) {
        while (roots[i] != i) i = roots[i] = roots[roots[i]];
        return i;
    };
    for (const auto& item : garments) {
        const auto& map = indices.at(item.first);
        for (const auto& face : item.second.faces) {
            for (int c = 1; c < 3; ++c)
                roots[root_of(map[face[c]])] = root_of(map[face[0]]);
        }
    }
    for (std::size_t i = 0; i < count; ++i) roots[i] = root_of(i);
    return roots;
}

std::map<std::pair<int, std::size_t>, RefitSpatialIndexNative> mesh_editor_refit_surface_indices(
    const std::map<int, MeshSessionSubmesh>& garments,
    const std::map<int, std::vector<std::size_t>>& indices,
    const std::vector<std::size_t>& roots
) {
    // Split only search indexes. Every triangle retains its source Part and
    // vertex IDs, and the common single-island Part keeps its existing BVH.
    std::map<std::pair<int, std::size_t>, RefitSpatialIndexNative> result;
    for (const auto& item : garments) {
        auto spatial = build_refit_spatial_index_native(garments, {item.first});
        if (spatial.root < 0) continue;
        const auto& map = indices.at(item.first);
        const auto first_root = roots[map[spatial.triangles.front().driver_vertices[0]]];
        const bool one_surface = std::all_of(spatial.triangles.begin(), spatial.triangles.end(),
            [&](const auto& triangle) { return roots[map[triangle.driver_vertices[0]]] == first_root; });
        if (one_surface) {
            result.emplace(std::make_pair(item.first, first_root), std::move(spatial));
            continue;
        }
        for (auto& triangle : spatial.triangles)
            result[{item.first, roots[map[triangle.driver_vertices[0]]]}].triangles.push_back(std::move(triangle));
        for (auto it = result.lower_bound({item.first, 0}); it != result.end() && it->first.first == item.first; ++it) {
            auto& surface = it->second;
            surface.triangle_order.resize(surface.triangles.size());
            std::iota(surface.triangle_order.begin(), surface.triangle_order.end(), 0);
            surface.nodes.reserve(surface.triangles.size() * 2);
            surface.root = refit_build_spatial_node_native(surface, 0, surface.triangles.size());
        }
    }
    return result;
}

std::set<std::pair<std::size_t, std::size_t>> mesh_editor_refit_rigid_joins(
    const std::map<int, MeshSessionSubmesh>& garments,
    const std::map<int, std::vector<std::size_t>>& indices,
    const std::vector<std::size_t>& roots, double tolerance,
    const std::set<int>& independent = {}
) {
    // Exported ornaments often overlap at their joins without shared vertices.
    // Keep that construction, including tiny authored gaps, as one hard object.
    const auto surfaces = mesh_editor_refit_surface_indices(garments, indices, roots);
    std::set<std::pair<std::size_t, std::size_t>> joins;
    const auto touches = [&](const RefitSpatialIndexNative& source, const RefitSpatialIndexNative& target) {
        std::set<std::pair<int, int>> edges;
        for (const auto& triangle : source.triangles) for (int c = 0; c < 3; ++c) {
            long long tests = 0;
            if (closest_refit_binding_native(triangle.corners[c], target, tests).distance <= tolerance) return true;
            if (!edges.insert(std::minmax(triangle.driver_vertices[c], triangle.driver_vertices[(c + 1) % 3])).second) continue;
            const Vec3 edge = sub_vec3(triangle.corners[(c + 1) % 3], triangle.corners[c]);
            const double length = length_vec3(edge);
            if (length <= tolerance) continue;
            const Vec3 middle = scale_vec3(add_vec3(triangle.corners[c], triangle.corners[(c + 1) % 3]), 0.5);
            if (!refit_surface_line_hits_native(middle, scale_vec3(edge, 1.0 / length), length * 0.5, target).empty()) return true;
        }
        return false;
    };
    for (auto first = surfaces.begin(); first != surfaces.end(); ++first) {
        for (auto second = std::next(first); second != surfaces.end(); ++second) {
            if (first->first.first != second->first.first
                && (independent.count(first->first.first) || independent.count(second->first.first))) continue;
            const auto pair = std::minmax(first->first.second, second->first.second);
            if (pair.first == pair.second || joins.count(pair)) continue;
            const auto& a = first->second.nodes[first->second.root];
            const auto& b = second->second.nodes[second->second.root];
            bool separated = false;
            for (int axis = 0; axis < 3; ++axis)
                separated |= a.minimum[axis] > b.maximum[axis] + tolerance
                    || b.minimum[axis] > a.maximum[axis] + tolerance;
            if (!separated && (touches(first->second, second->second) || touches(second->second, first->second)))
                joins.insert(pair);
        }
    }
    return joins;
}

RefitMaskWeightsNative mesh_editor_refit_masks(
    const MeshRefitRuntime& refit,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& residual
) {
    RefitMaskWeightsNative result;
    if (refit.vertex_masks.empty()) return result;
    struct Cohort { Vec3 point; double weight; std::vector<std::pair<int, int>> vertices; };
    std::vector<Cohort> cohorts;
    std::map<std::tuple<long long, long long, long long>, std::vector<std::size_t>> cells;
    const double tolerance = std::max(1.0e-6, refit.driver_diagonal * 1.0e-7);
    const bool tightening = std::any_of(refit.garment_settings.begin(), refit.garment_settings.end(),
        [](const auto& item) { return item.second.enabled && item.second.mode != "rigid" && item.second.tightness_percent > 0.0; });
    const auto seam_positions = tightening ? mesh_editor_refit_seam_positions(refit, submeshes, residual)
                                          : std::map<int, std::vector<Vec3>>{};
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
            const Vec3 point = tightening ? seam_positions.at(index)[vertex] : positions->second[vertex];
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

double mesh_editor_refit_layer_gap(double authored_gap, double clearance, double tightness, double tolerance) {
    const double snug_gap = std::min(authored_gap, std::max(clearance, tolerance * 4.0));
    return authored_gap + (snug_gap - authored_gap) * std::clamp(tightness, 0.0, 1.0);
}

Vec3 mesh_editor_refit_band_axis(const RefitSpatialIndexNative& surface, const RefitSpatialIndexNative& body,
                               double tolerance) {
    const auto& bounds = surface.nodes.at(surface.root);
    const auto& driver = body.nodes.at(body.root);
    const Vec3 extent = sub_vec3(bounds.maximum, bounds.minimum);
    const Vec3 body_extent = sub_vec3(driver.maximum, driver.minimum);
    const auto up = std::distance(body_extent.begin(), std::max_element(body_extent.begin(), body_extent.end()));
    double width = std::numeric_limits<double>::infinity();
    for (int axis = 0; axis < 3; ++axis) if (axis != up) {
        width = std::min(width, extent[axis]);
        const double center = (driver.maximum[axis] + driver.minimum[axis]) * 0.5;
        if (center < bounds.minimum[axis] - tolerance || center > bounds.maximum[axis] + tolerance) return {};
    }
    if (width < length_vec3(body_extent) * 0.04 || extent[up] > width * 0.4) return {};
    Vec3 axis{};
    axis[up] = 1.0;
    return axis;
}

bool mesh_editor_refit_band_has_walls(const RefitSpatialIndexNative& surface,
    const std::vector<std::size_t>& indices, double tolerance) {
    std::map<std::pair<std::size_t, std::size_t>, std::pair<int, int>> edges;
    const auto& bounds = surface.nodes.at(surface.root);
    const Vec3 center = scale_vec3(add_vec3(bounds.minimum, bounds.maximum), 0.5);
    double volume = 0.0, area = 0.0;
    for (const auto& face : surface.triangles) {
        const Vec3 a = sub_vec3(face.corners[0], center), b = sub_vec3(face.corners[1], center), c = sub_vec3(face.corners[2], center);
        const Vec3 cross{b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0]};
        volume += dot_vec3(a, cross);
        const Vec3 ab = sub_vec3(b, a), ac = sub_vec3(c, a);
        area += length_vec3(Vec3{ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0]});
        for (int edge = 0; edge < 3; ++edge) {
            const auto first = indices[face.driver_vertices[edge]], second = indices[face.driver_vertices[(edge + 1) % 3]];
            if (first == second) continue;
            auto& incidence = edges[std::minmax(first, second)];
            ++incidence.first; incidence.second += first < second ? 1 : -1;
        }
    }
    return std::abs(volume) > area * tolerance * 12.0 && std::all_of(edges.begin(), edges.end(),
        [](const auto& edge) { return edge.second.first == 2 && edge.second.second == 0; });
}


int mesh_editor_refit_layer_order(
    const RefitSpatialIndexNative& first, const RefitSpatialIndexNative& second,
    const std::map<int, MeshSessionSubmesh>& garments, const RefitSpatialIndexNative& body,
    const std::map<int, std::vector<Vec3>>& body_positions, double reach, double tolerance
) {
    const auto& first_bounds = first.nodes.at(first.root);
    const auto& second_bounds = second.nodes.at(second.root);
    int shared_spans = 0;
    for (int axis = 0; axis < 3; ++axis) {
        const double a = first_bounds.maximum[axis] - first_bounds.minimum[axis];
        const double b = second_bounds.maximum[axis] - second_bounds.minimum[axis];
        if (std::min(a, b) > std::max(tolerance * 4.0, reach * 0.25)
            && std::min(a, b) >= std::max(a, b) * 0.5)
            ++shared_spans;
    }
    // A local knot or hanging strip beside a broad waist shell is trim, not
    // another nested garment. Retain its authored displacement relationship.
    if (shared_spans < 2) return 0;
    std::array<int, 2> sides{};
    std::array<bool, 2> wraps{};
    int orientation = 0;
    for (const auto& pair : {std::make_pair(&first, &second), std::make_pair(&second, &first)}) {
        bool positive = false, negative = false;
        Vec3 normal_sum{};
        std::size_t normal_count = 0;
        const auto sample = [&](const Vec3& point) {
            long long tests = 0;
            const auto binding = closest_refit_binding_native(point, *pair.second, tests);
            if (binding.distance > reach) return false;
            const auto& vertices = garments.at(binding.driver_submesh_index).vertices;
            Vec3 nearest{};
            for (int c = 0; c < 3; ++c)
                nearest = add_vec3(nearest, scale_vec3(vertices[binding.driver_vertices[c]], binding.barycentric[c]));
            // Layer order follows the body's outside. A solid belt's inner
            // faces have the opposite winding to the cloth beneath them.
            const auto driver = closest_refit_binding_native(point, body, tests);
            const Vec3 normal = refit_binding_face_normal_native(driver, body_positions);
            normal_sum = add_vec3(normal_sum, normal);
            ++normal_count;
            const Vec3 offset = sub_vec3(point, nearest);
            const double height = dot_vec3(offset, normal);
            // At a faceted rim the nearest point may be a shared vertex. Its
            // offset need only run mainly across the surface to establish side.
            if (height * height < binding.distance * binding.distance * 0.5) return false;
            positive |= height > tolerance * 4.0;
            negative |= height < -tolerance * 4.0;
            return positive && negative;
        };
        std::set<std::pair<int, int>> visited;
        for (const auto& triangle : pair.first->triangles) {
            for (int c = 0; c < 3; ++c)
                if (visited.insert({triangle.driver_submesh_index, triangle.driver_vertices[c]}).second
                    && sample(triangle.corners[c])) break;
            if (positive && negative) break;
        }
        wraps[orientation] = normal_count > 0 && length_vec3(normal_sum) < normal_count * 0.75;
        sides[orientation++] = positive && negative ? 2 : positive ? 1 : negative ? -1 : 0;
    }
    // Consistent outer corners establish order even if a coarse outer face
    // cuts an inner corner. Interleaved authored folds have mixed outer corners.
    const auto surface_profile = [&](const RefitSpatialIndexNative& surface) {
        double area = 0.0, across_body = 0.0;
        for (const auto& face : surface.triangles) {
            const Vec3 a = sub_vec3(face.corners[1], face.corners[0]);
            const Vec3 b = sub_vec3(face.corners[2], face.corners[0]);
            const Vec3 normal{a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]};
            const double weight = length_vec3(normal);
            long long tests = 0;
            const Vec3 center = scale_vec3(add_vec3(add_vec3(face.corners[0], face.corners[1]), face.corners[2]), 1.0 / 3.0);
            const auto driver = closest_refit_binding_native(center, body, tests);
            area += weight;
            across_body += std::abs(dot_vec3(normal, refit_binding_face_normal_native(driver, body_positions)));
        }
        return std::make_pair(area, across_body);
    };
    if (sides[0] == 2 || sides[1] == 2) {
        const auto a = surface_profile(first), b = surface_profile(second);
        // An inset cord has faces around its small cross-section, rather than
        // one broad cloth face. It can straddle a belt without making that belt
        // the outside of the cord. Preserve this attachment instead of assigning
        // the whole pair an inverted shell order from the belt's clear corners.
        if ((sides[0] == 2 && a.first * 4.0 < b.first && a.second < a.first * 0.8)
            || (sides[1] == 2 && b.first * 4.0 < a.first && b.second < b.first * 0.8)) return 0;
    }
    int order = 0;
    if (sides[0] == 1 && sides[1] == 1) return 0;
    if (sides[0] == 1) order = 1;
    else if (sides[1] == 1) order = -1;
    else if (sides[0] == -1 && sides[1] != 2) order = -1;
    else if (sides[1] == -1 && sides[0] != 2) order = 1;
    const auto broadly_covers = [&](const RefitSpatialIndexNative& source, const RefitSpatialIndexNative& target) {
        double area = 0.0, covered = 0.0;
        for (const auto& face : source.triangles) {
            const Vec3 a = sub_vec3(face.corners[1], face.corners[0]);
            const Vec3 b = sub_vec3(face.corners[2], face.corners[0]);
            const double weight = length_vec3(Vec3{a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]});
            area += weight;
            const Vec3 point = scale_vec3(add_vec3(add_vec3(face.corners[0], face.corners[1]), face.corners[2]), 1.0 / 3.0);
            long long tests = 0;
            const auto binding = closest_refit_binding_native(point, target, tests);
            if (binding.distance > reach) continue;
            Vec3 support{};
            const auto& vertices = garments.at(binding.driver_submesh_index).vertices;
            for (int c = 0; c < 3; ++c)
                support = add_vec3(support, scale_vec3(vertices[binding.driver_vertices[c]], binding.barycentric[c]));
            const auto first_body = closest_refit_binding_native(point, body, tests);
            const auto second_body = closest_refit_binding_native(support, body, tests);
            const Vec3 normal = refit_binding_face_normal_native(first_body, body_positions);
            const double height = dot_vec3(sub_vec3(point, support), normal);
            if (height * height >= binding.distance * binding.distance * 0.5
                && dot_vec3(normal, refit_binding_face_normal_native(second_body, body_positions)) >= 0.5
                && distance_squared_vec3(mesh_editor_refit_driver_point(first_body, body_positions),
                    mesh_editor_refit_driver_point(second_body, body_positions)) <= reach * reach * 0.25)
                covered += weight;
        }
        return area > 0.0 && covered >= area * 0.5;
    };
    // Front and back panels can meet at their side edges without being nested
    // shells. A local edge overlap must not impose one global inside/outside
    // order on those adjoining panels, especially after reopening a baked fit.
    if (order != 0 && !broadly_covers(first, second) && !broadly_covers(second, first)) return 0;
    // Crossing hanging ribbons are an authored fold, even when their corners
    // happen to agree on a side. A shell surrounding the body can instead have
    // coarse faces that cut its inner wrap and must be repaired.
    if (order != 0 && !wraps[0] && !wraps[1]) {
        for (const auto& pair : {std::make_pair(&first, &second), std::make_pair(&second, &first)}) {
            std::set<std::pair<int, int>> edges;
            for (const auto& face : pair.first->triangles) for (int c = 0; c < 3; ++c) {
                if (!edges.insert(std::minmax(face.driver_vertices[c], face.driver_vertices[(c + 1) % 3])).second) continue;
                const Vec3 a = face.corners[c], b = face.corners[(c + 1) % 3];
                const Vec3 delta = sub_vec3(b, a);
                const double length = length_vec3(delta);
                if (length > tolerance && !refit_surface_line_hits_native(scale_vec3(add_vec3(a, b), 0.5),
                        scale_vec3(delta, 1.0 / length), length * 0.5, *pair.second).empty()) return 0;
            }
        }
    }
    return order;
}

std::vector<Vec3> mesh_editor_refit_rigid_pose(
    const std::vector<Vec3>&, const std::vector<std::array<std::size_t,3>>&, std::size_t,
    const Vec3&, const Vec3&, const RefitSpatialIndexNative&,
    const std::map<int,std::vector<Vec3>>&, const RefitSpatialIndexNative&,
    const std::map<int,std::vector<Vec3>>&, double, double, double);
void mesh_editor_write_refit_island_settings(std::ostream&, const MeshRefitGarmentSettingsRuntime&);

void mesh_editor_refit_components(
    const MeshRefitRuntime& refit,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& driver_visible,
    const std::map<int, std::vector<Vec3>>& residual,
    const std::map<int, std::vector<Vec3>>& base_layer,
    const RefitMaskWeightsNative& masks,
    std::map<int, std::vector<Vec3>>& layer,
    bool conforming = false,
    std::map<int, std::vector<Vec3>>* centering_axes = nullptr,
    bool depth_pose = false
) {
    if (std::none_of(refit.garment_settings.begin(), refit.garment_settings.end(),
        [](const auto& item) { return item.second.enabled && item.second.mode == "rigid_component"; })) return;
    struct Vertex { int submesh; int vertex; Vec3 original; Vec3 target; Vec3 key; double weight; };
    std::vector<Vertex> vertices;
    std::vector<std::size_t> roots;
    std::map<int, std::vector<std::size_t>> indices;
    const auto root_of = [&](std::size_t index) {
        while (roots[index] != index) { roots[index] = roots[roots[index]]; index = roots[index]; }
        return index;
    };
    const double tolerance = std::max(1.0e-6, refit.driver_diagonal * 1.0e-7);
    std::map<std::tuple<long long, long long, long long>, std::vector<std::size_t>> cells;
    // Use the same authored seam groups as conforming. Independently quantized
    // material borders still belong to one hard piece; keep their real positions.
    const auto seam_positions = mesh_editor_refit_seam_positions(refit, submeshes, residual);
    for (const auto& item : refit.garment_settings) {
        if (!item.second.enabled || item.second.mode != "rigid_component") continue;
        if (conforming && item.second.tightness_percent == 0.0) continue;
        const auto& part = submeshes.at(item.first);
        const auto base = base_layer.find(item.first);
        for (std::size_t vertex = 0; vertex < part.vertices.size(); ++vertex) {
            const auto index = vertices.size();
            const Vec3 p = add_vec3(residual.at(item.first)[vertex],
                base == base_layer.end() ? Vec3{} : base->second[vertex]);
            const Vec3 key = seam_positions.at(item.first)[vertex];
            roots.push_back(index);
            vertices.push_back({item.first, static_cast<int>(vertex), p,
                add_vec3(residual.at(item.first)[vertex], layer.at(item.first)[vertex]),
                key, mesh_editor_refit_mask_weight(masks, item.first, vertex)});
            indices[item.first].push_back(index);
            const auto cell = mesh_editor_refit_cell(key, tolerance);
            for (long long x = -1; x <= 1; ++x) for (long long y = -1; y <= 1; ++y) for (long long z = -1; z <= 1; ++z) {
                const auto found = cells.find({std::get<0>(cell) + x, std::get<1>(cell) + y, std::get<2>(cell) + z});
                if (found == cells.end()) continue;
                for (const auto other : found->second)
                    if (distance_squared_vec3(key, vertices[other].key) <= tolerance * tolerance)
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
    for (std::size_t i = 0; i < roots.size(); ++i) roots[i] = root_of(i);
    const auto topology_roots = roots;
    std::map<int, MeshSessionSubmesh> authored;
    for (const auto& part : indices) {
        authored[part.first].vertices = residual.at(part.first);
        authored[part.first].faces = submeshes.at(part.first).faces;
    }
    for (const auto& join : mesh_editor_refit_rigid_joins(authored, indices, roots,
             std::max(tolerance, refit.driver_diagonal * 0.0005), refit.independent_island_parts))
        roots[root_of(join.second)] = root_of(join.first);
    std::map<std::size_t, std::vector<std::size_t>> components;
    for (std::size_t i = 0; i < vertices.size(); ++i) components[root_of(i)].push_back(i);
    std::map<int, MeshSessionSubmesh> drivers;
    for (const auto& item : driver_visible) { drivers[item.first].vertices = item.second; drivers[item.first].faces = submeshes.at(item.first).faces; }
    const auto spatial = build_refit_spatial_index_native(drivers, refit.driver_submesh_indices);
    std::vector<Vec3> body_source, body_target;
    Vec3 body_source_center{}, body_target_center{}, body_min{}, body_max{};
    for (const auto& item : refit.driver_baseline_positions) for (std::size_t i = 0; i < item.second.size(); ++i) {
        const auto& point = item.second[i];
        if (body_source.empty()) body_min = body_max = point;
        for (int axis = 0; axis < 3; ++axis) {
            body_min[axis] = std::min(body_min[axis], point[axis]);
            body_max[axis] = std::max(body_max[axis], point[axis]);
        }
        body_source.push_back(point);
        body_target.push_back(driver_visible.at(item.first)[i]);
        body_source_center = add_vec3(body_source_center, point);
        body_target_center = add_vec3(body_target_center, body_target.back());
    }
    body_source_center = scale_vec3(body_source_center, 1.0 / body_source.size());
    body_target_center = scale_vec3(body_target_center, 1.0 / body_target.size());
    const auto body_rotation = refit_component_rotation_native(body_source, body_target, body_source_center, body_target_center);
    const Vec3 body_center = scale_vec3(add_vec3(body_min, body_max), 0.5);
    const Vec3 body_extent = sub_vec3(body_max, body_min);
    const auto up_axis = std::distance(body_extent.begin(), std::max_element(body_extent.begin(), body_extent.end()));
    Vec3 up{}; up[up_axis] = 1.0;
    std::map<int, MeshSessionSubmesh> flexible;
    std::map<int, std::vector<Vec3>> flexible_base, flexible_target;
    std::set<int> flexible_parts;
    for (const auto& item : refit.garment_settings) {
        if (!item.second.enabled || item.second.mode != "surface") continue;
        flexible_parts.insert(item.first);
        flexible[item.first].vertices = residual.at(item.first);
        flexible[item.first].faces = submeshes.at(item.first).faces;
        const auto base = base_layer.find(item.first);
        const auto current = layer.find(item.first);
        for (std::size_t i = 0; i < residual.at(item.first).size(); ++i) {
            const auto& point = residual.at(item.first)[i];
            flexible_base[item.first].push_back(add_vec3(point, base == base_layer.end() ? Vec3{} : base->second[i]));
            flexible_target[item.first].push_back(add_vec3(point, current == layer.end() ? Vec3{} : current->second[i]));
        }
    }
    // Bind in authored coordinates on every evaluation, never to the preceding
    // preview. A dangling ornament follows its join, not its whole-body average.
    const auto supports = build_refit_spatial_index_native(flexible, flexible_parts);
    auto pose_surfaces = driver_visible;
    auto pose_parts = drivers;
    auto pose_indices = refit.driver_submesh_indices;
    for (const auto& item : flexible_target) {
        pose_surfaces[item.first] = item.second;
        pose_parts[item.first].vertices = item.second;
        pose_parts[item.first].faces = submeshes.at(item.first).faces;
        pose_indices.insert(item.first);
    }
    const auto pose_obstacles = depth_pose ? build_refit_spatial_index_native(pose_parts, pose_indices) : RefitSpatialIndexNative{};
    const double join_tolerance = std::max(tolerance * 4.0, refit.driver_diagonal * 0.0005);
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
        Vec3 authored_normal{};
        for (const auto& binding : refit.bindings) {
            const auto part = indices.find(binding.garment_submesh_index);
            if (part != indices.end() && root_of(part->second[binding.garment_vertex_index]) == component.first)
                authored_normal = add_vec3(authored_normal,
                    refit_binding_face_normal_native(binding, refit.driver_baseline_positions));
        }
        const Vec3 lateral{up[1]*authored_normal[2]-up[2]*authored_normal[1],
                           up[2]*authored_normal[0]-up[0]*authored_normal[2],
                           up[0]*authored_normal[1]-up[1]*authored_normal[0]};
        Vec3 source_axis{};
        int lateral_axis = 0;
        for (int axis = 1; axis < 3; ++axis)
            if (std::abs(lateral[axis]) > std::abs(lateral[lateral_axis])) lateral_axis = axis;
        if (length_vec3(lateral) > original.size() * 1.0e-6) source_axis[lateral_axis] = 1.0;
        double side_min = std::numeric_limits<double>::infinity(), side_max = -side_min;
        for (const auto i : component.second) {
            const auto& vertex = vertices[i];
            const double side = dot_vec3(sub_vec3(residual.at(vertex.submesh)[vertex.vertex], body_center), source_axis);
            side_min = std::min(side_min, side); side_max = std::max(side_max, side);
        }
        const bool spans_center = side_min < -tolerance && side_max > tolerance;
        std::vector<MeshRefitVertexBindingRuntime> attachments;
        double closest_support = refit.driver_diagonal * 0.03;
        if (supports.root >= 0 && first.weight > 0.0) for (const auto index : component.second) {
            const auto& vertex = vertices[index];
            long long tests = 0;
            const auto binding = closest_refit_binding_native(residual.at(vertex.submesh)[vertex.vertex], supports, tests);
            if (binding.distance > join_tolerance) {
                // A one-sided scarf overlap must not capture a body-centred
                // assembly. Local ornaments can still follow their backing cloth.
                if (spans_center) continue;
                const Vec3 offset = sub_vec3(residual.at(vertex.submesh)[vertex.vertex],
                    mesh_editor_refit_driver_point(binding, residual));
                const double height = dot_vec3(offset, refit_binding_face_normal_native(binding, residual));
                if (height * height < binding.distance * binding.distance * 0.5) continue;
            }
            const auto& support_settings = refit.garment_settings.at(binding.driver_submesh_index);
            // Different follow strengths are deliberate. Do not override them or
            // apply an already masked/intensity-scaled cloth displacement twice.
            if (!conforming && support_settings.intensity_percent != settings.intensity_percent) continue;
            double weight = 0.0;
            for (int c = 0; c < 3; ++c)
                weight += binding.barycentric[c] * mesh_editor_refit_mask_weight(masks,
                    binding.driver_submesh_index, binding.driver_vertices[c]);
            if (std::abs(weight - first.weight) > 1.0e-12) continue;
            closest_support = std::min(closest_support, binding.distance);
            attachments.push_back(binding);
        }
        std::vector<Vec3> support_source, support_target;
        double attachment_min = std::numeric_limits<double>::infinity(), attachment_max = -attachment_min;
        for (const auto& binding : attachments) {
            // Prefer the closest attachment patch. Nearby cloth under the rest
            // of a pendant must not dilute the motion of its actual join.
            if (binding.distance > std::min(refit.driver_diagonal * 0.03, closest_support + join_tolerance)) continue;
            std::array<Vec3, 3> source_triangle{}, target_triangle{};
            refit_triangle_corners_native(flexible_base, binding.driver_submesh_index, binding.driver_vertices, source_triangle);
            refit_triangle_corners_native(flexible_target, binding.driver_submesh_index, binding.driver_vertices, target_triangle);
            const auto a = refit_face_frame_native(source_triangle), b = refit_face_frame_native(target_triangle);
            if (!a.valid || !b.valid) continue;
            const double side = dot_vec3(sub_vec3(mesh_editor_refit_driver_point(binding, residual), body_center), source_axis);
            attachment_min = std::min(attachment_min, side);
            attachment_max = std::max(attachment_max, side);
            const Vec3 source = mesh_editor_refit_driver_point(binding, flexible_base);
            const Vec3 target = mesh_editor_refit_driver_point(binding, flexible_target);
            // Symmetric frame samples retain orientation even at a single-point
            // or straight-edge join, without inheriting cloth stretch or scale.
            for (const auto& axes : {std::make_pair(a.tangent, b.tangent),
                                    std::make_pair(a.bitangent, b.bitangent), std::make_pair(a.normal, b.normal)})
                for (const double sign : {-1.0, 1.0}) {
                    support_source.push_back(add_vec3(source, scale_vec3(axes.first, sign * join_tolerance)));
                    support_target.push_back(add_vec3(target, scale_vec3(axes.second, sign * join_tolerance)));
                }
        }
        if (conforming && spans_center
            && (attachment_min > join_tolerance || attachment_max < -join_tolerance)) {
            // A single lateral contact cannot locate an entire centred necklace.
            // A central join or joins spanning the centre remain real anchors.
            support_source.clear(); support_target.clear();
        }
        const bool attached = !support_source.empty();
        if (attached) {
            original_center = {}; target_center = {};
            for (std::size_t i = 0; i < support_source.size(); ++i) {
                original_center = add_vec3(original_center, support_source[i]);
                target_center = add_vec3(target_center, support_target[i]);
            }
            original_center = scale_vec3(original_center, 1.0 / support_source.size());
            target_center = scale_vec3(target_center, 1.0 / support_target.size());
        }
        Vec3 centering_axis{};
        if (conforming && !attached && spans_center && first.weight > 0.0) {
            // Retain the body's authored lateral axis through body rotation;
            // individual triangle normals would bias it by a tessellation step.
            centering_axis = refit_rotate_quaternion_native(body_rotation, source_axis);
            const Vec3 current_body_center = add_vec3(body_target_center,
                refit_rotate_quaternion_native(body_rotation, sub_vec3(body_center, body_source_center)));
            double minimum = std::numeric_limits<double>::infinity(), maximum = -minimum;
            for (const auto& point : original) {
                const double side = dot_vec3(sub_vec3(point, current_body_center), centering_axis);
                minimum = std::min(minimum, side); maximum = std::max(maximum, side);
            }
            target_center = sub_vec3(target_center, scale_vec3(centering_axis,
                dot_vec3(sub_vec3(target_center, original_center), centering_axis)
                + (minimum + maximum) * 0.5 * settings.tightness_percent / 100.0 * first.weight));
        }
        if (centering_axes) for (const auto i : component.second) {
            const auto& vertex = vertices[i];
            auto& axes = (*centering_axes)[vertex.submesh];
            axes.resize(submeshes.at(vertex.submesh).vertices.size());
            axes[vertex.vertex] = centering_axis;
        }
        const bool assembled = std::any_of(component.second.begin(), component.second.end(), [&](const auto i) {
            return topology_roots[i] != topology_roots[component.second.front()];
        });
        if (depth_pose && (!assembled || attached || length_vec3(centering_axis) < .5)) continue;
        // With no Flexible attachment, tightening translates an assembly without
        // tipping its chain and pendants onto the neck. An attachment instead
        // supplies one shared rigid transform, including its fitted orientation.
        auto rotation = conforming && assembled && !attached ? std::array<double, 4>{1.0, 0.0, 0.0, 0.0}
            : refit_component_rotation_native(attached ? support_source : original, attached ? support_target : target,
                original_center, target_center);
        const double amount = conforming || attached ? 1.0 : settings.intensity_percent / 100.0 * first.weight;
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
        if (depth_pose) fitted = target;
        auto samples = fitted;
        std::vector<std::array<std::size_t,3>> rigid_faces;
        if (conforming) {
            std::map<std::size_t,std::size_t> local;
            for (std::size_t i=0;i<component.second.size();++i) local[component.second[i]]=i;
            std::set<std::pair<std::size_t,std::size_t>> sampled_edges;
            for (const auto& item : indices) for (const auto& face : submeshes.at(item.first).faces) {
                if (!local.count(item.second[face[0]])) continue;
                rigid_faces.push_back({local.at(item.second[face[0]]), local.at(item.second[face[1]]), local.at(item.second[face[2]])});
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
        if (depth_pose) {
            samples = mesh_editor_refit_rigid_pose(samples, rigid_faces, fitted.size(), centering_axis,
                refit_rotate_quaternion_native(body_rotation, up), spatial, driver_visible,
                pose_obstacles, pose_surfaces, refit.driver_diagonal,
                clearance, settings.tightness_percent / 100.0 * first.weight);
            std::copy_n(samples.begin(), fitted.size(), fitted.begin());
        }
        // Every clearance adjustment is one shared translation, preserving the hard part.
        // Keep the authored cloth-to-accessory spacing until the joint fit has
        // captured it. Clearing only the hard piece first can move it beyond
        // its cloth support before the cloth catches up on a larger body.
        const bool resolve_clearance = conforming || settings.tightness_percent <= 0.0;
        if (resolve_clearance && clearance > 0.0 && first.weight > 0.0) for (int pass = 0; pass < (conforming ? 128 : 32); ++pass) {
            double missing_max = tolerance;
            Vec3 correction{};
            for (const auto& point : samples) {
                const Vec3 predicted = add_vec3(point, clearance_shift);
                long long candidate_tests = 0;
                const auto binding = closest_refit_binding_native(predicted, spatial, candidate_tests);
                const Vec3 normal = refit_binding_face_normal_native(binding, driver_visible);
                const double missing = clearance - dot_vec3(sub_vec3(predicted,
                    mesh_editor_refit_driver_point(binding, driver_visible)), normal);
                if (missing <= tolerance) continue;
                const Vec3 direction = sub_vec3(normal, scale_vec3(centering_axis, dot_vec3(normal, centering_axis)));
                const double freedom = dot_vec3(normal, direction);
                if (missing > missing_max && freedom > 1.0e-8) {
                    missing_max = missing;
                    correction = scale_vec3(direction, missing / freedom);
                }
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
    const std::map<int, std::vector<Vec3>>* layer_reference = nullptr,
    const std::map<int, std::vector<Vec3>>* centering_axes = nullptr
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
        Vec3 key;
        double clearance = 0.0;
        std::vector<std::pair<int, std::size_t>> vertices;
        bool has_surface = false;
        double mobility = 1.0;
    };
    std::vector<Cohort> cohorts;
    std::map<int, std::vector<std::size_t>> vertex_cohorts;
    std::map<std::tuple<long long, long long, long long>, std::vector<std::size_t>> cells;
    const auto seam_positions = fitting_masks ? mesh_editor_refit_seam_positions(refit, submeshes, residual)
                                             : std::map<int, std::vector<Vec3>>{};
    for (const auto& item : clearances) {
        const int index = item.first;
        auto& indices = vertex_cohorts[index];
        const auto& positions = residual.at(index);
        for (std::size_t vertex = 0; vertex < positions.size(); ++vertex) {
            const Vec3 point = add_vec3(positions[vertex], layer.at(index)[vertex]);
            const Vec3 key = fitting_masks ? seam_positions.at(index)[vertex] : point;
            const auto cell = mesh_editor_refit_cell(key, tolerance);
            std::size_t cohort_index = cohorts.size();
            for (long long dx = -1; dx <= 1 && cohort_index == cohorts.size(); ++dx) {
                for (long long dy = -1; dy <= 1 && cohort_index == cohorts.size(); ++dy) {
                    for (long long dz = -1; dz <= 1 && cohort_index == cohorts.size(); ++dz) {
                        const auto found = cells.find({
                            std::get<0>(cell) + dx, std::get<1>(cell) + dy, std::get<2>(cell) + dz
                        });
                        if (found == cells.end()) continue;
                        for (const std::size_t candidate : found->second) {
                            if (distance_squared_vec3(key, cohorts[candidate].key) <= tolerance * tolerance) {
                                cohort_index = candidate;
                                break;
                            }
                        }
                    }
                }
            }
            if (cohort_index == cohorts.size()) {
                cells[cell].push_back(cohort_index);
                cohorts.push_back(Cohort{point, point, key, item.second, {}});
            }
            Cohort& cohort = cohorts[cohort_index];
            cohort.clearance = std::max(cohort.clearance, item.second);
            cohort.vertices.push_back({index, vertex});
            if (fitting_masks) cohort.mobility = std::min(cohort.mobility,
                mesh_editor_refit_mask_weight(*fitting_masks, index, vertex));
            indices.push_back(cohort_index);
        }
    }
    if (fitting_masks) for (const auto& item : refit.garment_settings) {
        if (clearances.count(item.first)) continue;
        for (std::size_t vertex=0;vertex<residual.at(item.first).size();++vertex) {
            const Vec3 point=seam_positions.at(item.first)[vertex];
            const auto cell=mesh_editor_refit_cell(point,tolerance);
            for (int x=-1;x<=1;++x) for (int y=-1;y<=1;++y) for (int z=-1;z<=1;++z) {
                const auto found=cells.find({std::get<0>(cell)+x,std::get<1>(cell)+y,std::get<2>(cell)+z});
                if (found==cells.end()) continue;
                for (const auto i:found->second)
                    if (distance_squared_vec3(point,cohorts[i].key)<=tolerance*tolerance) cohorts[i].mobility=0.0;
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
        double snug_gap = -1.0;
        std::pair<int, std::size_t> target_surface{-1, 0};
        bool ordered = false;
        mutable std::array<std::size_t, 3> live_corners{};
        mutable int live_generation = -1;
    };
    std::map<std::size_t, std::map<std::size_t, double>> detail_supports;
    std::map<std::size_t, Vec3> detail_offsets;
    std::map<std::size_t, std::size_t> detail_frames;
    std::map<std::size_t, std::array<double, 4>> detail_rotations;
    const auto live_point = [&](std::size_t i) {
        const auto detail = detail_offsets.find(i);
        if (detail == detail_offsets.end()) return cohorts[i].position;
        Vec3 point = refit_rotate_quaternion_native(detail_rotations.at(detail_frames.at(i)), detail->second);
        for (const auto& parent : detail_supports.at(i))
            point = add_vec3(point, scale_vec3(cohorts[parent.first].position, parent.second));
        return point;
    };
    const auto sample_point = [&](const SurfaceSample& sample, bool original) {
        Vec3 point{0.0, 0.0, 0.0};
        for (std::size_t corner = 0; corner < 3; ++corner) {
            const Cohort& cohort = cohorts[sample.corners[corner]];
            point = add_vec3(point, scale_vec3(original ? cohort.original : live_point(sample.corners[corner]), sample.weights[corner]));
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
    // A hard attachment has one translation during clearance, rather than
    // immovable vertices or independent per-vertex corrections. Canonical
    // cohorts carry that translation across quantized material seams too.
    std::vector<std::size_t> rigid_roots;
    std::vector<bool> rigid_vertex(cohorts.size(), false);
    for (std::size_t i = 0; i < cohorts.size(); ++i) rigid_roots.push_back(i);
    if (fitting_masks) for (const auto& item : clearances) {
        if (refit.garment_settings.at(item.first).mode != "rigid_component") continue;
        const auto& map = vertex_cohorts.at(item.first);
        for (const auto i : map) rigid_vertex[i] = true;
        for (const auto& face : submeshes.at(item.first).faces)
            for (int c = 1; c < 3; ++c)
                rigid_roots[root_of(rigid_roots, map[face[c]])] = root_of(rigid_roots, map[face[0]]);
    }
    for (std::size_t i = 0; i < rigid_roots.size(); ++i) rigid_roots[i] = root_of(rigid_roots, i);
    std::map<int, MeshSessionSubmesh> authored_rigid;
    if (fitting_masks) for (const auto& item : clearances) {
        if (refit.garment_settings.at(item.first).mode != "rigid_component") continue;
        authored_rigid[item.first].vertices = residual.at(item.first);
        authored_rigid[item.first].faces = submeshes.at(item.first).faces;
    }
    for (const auto& join : mesh_editor_refit_rigid_joins(authored_rigid, vertex_cohorts, rigid_roots,
             std::max(tolerance, refit.driver_diagonal * 0.0005), refit.independent_island_parts))
        rigid_roots[root_of(rigid_roots, join.second)] = root_of(rigid_roots, join.first);
    std::map<std::size_t, std::vector<std::size_t>> rigid_groups;
    for (std::size_t i = 0; i < cohorts.size(); ++i) {
        rigid_roots[i] = root_of(rigid_roots, i);
        if (rigid_vertex[i]) rigid_groups[rigid_roots[i]].push_back(i);
    }
    for (const auto& group : rigid_groups) {
        double mobility = 1.0;
        for (const auto i : group.second) mobility = std::min(mobility, cohorts[i].mobility);
        for (const auto i : group.second) cohorts[i].mobility = mobility;
    }
    std::vector<Vec3> contact_fixed_axes(cohorts.size());
    if (centering_axes) for (const auto& group : rigid_groups) {
        Vec3 axis{};
        for (const auto i : group.second) for (const auto& vertex : cohorts[i].vertices) {
            const auto found = centering_axes->find(vertex.first);
            if (found != centering_axes->end()) axis = add_vec3(axis, found->second[vertex.second]);
        }
        const double length = length_vec3(axis);
        if (length > tolerance) for (const auto i : group.second)
            contact_fixed_axes[i] = scale_vec3(axis, 1.0 / length);
    }
    const auto project_contact = [&](std::size_t i, const Vec3& delta) {
        return sub_vec3(delta, scale_vec3(contact_fixed_axes[i], dot_vec3(delta, contact_fixed_axes[i])));
    };
    const auto move_contact = [&](std::size_t i, const Vec3& delta) {
        if (rigid_vertex[i]) {
            for (const auto j : rigid_groups.at(rigid_roots[i]))
                cohorts[j].position = add_vec3(cohorts[j].position, project_contact(i, delta));
        } else cohorts[i].position = add_vec3(cohorts[i].position, project_contact(i, delta));
    };
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
    const auto layer_roots = mesh_editor_refit_surface_roots(garments, vertex_cohorts, cohorts.size());
    const auto layer_surfaces = mesh_editor_refit_surface_indices(layer_garments, vertex_cohorts, layer_roots);
    std::map<std::size_t, Vec3> band_axes;
    std::map<std::size_t, Vec3> solid_band_axes;
    if (fitting_masks) for (const auto& surface : layer_surfaces) {
        if (refit.garment_settings.at(surface.first.first).mode != "surface") continue;
        const Vec3 axis = mesh_editor_refit_band_axis(surface.second, spatial_index, tolerance);
        if (dot_vec3(axis, axis) < 0.5) continue;
        std::set<std::size_t> vertices;
        const auto& map = vertex_cohorts.at(surface.first.first);
        for (const auto& face : surface.second.triangles)
            for (const auto vertex : face.driver_vertices) vertices.insert(map[vertex]);
        const auto first = *vertices.begin();
        const auto& first_settings = refit.garment_settings.at(cohorts[first].vertices.front().first);
        const bool uniform = std::all_of(vertices.begin(), vertices.end(), [&](const auto i) {
            return std::abs(cohorts[i].mobility - cohorts[first].mobility) < 1.0e-9
                && std::all_of(cohorts[i].vertices.begin(), cohorts[i].vertices.end(), [&](const auto& vertex) {
                    const auto& settings = refit.garment_settings.at(vertex.first);
                    return settings.mode == "surface"
                        && std::abs(settings.tightness_percent - first_settings.tightness_percent) < 1.0e-9;
                });
        });
        if (uniform) {
            for (const auto i : vertices) contact_fixed_axes[i] = axis;
            band_axes[surface.first.second] = axis;
            if (mesh_editor_refit_band_has_walls(surface.second, map, tolerance)) solid_band_axes[surface.first.second] = axis;
        }
    }
    std::vector<double> band_wall_depth(cohorts.size(), 0.0);
    for (const auto& surface : layer_surfaces) if (solid_band_axes.count(surface.first.second)) {
        const auto& map = vertex_cohorts.at(surface.first.first);
        std::set<std::size_t> vertices;
        for (const auto& face : surface.second.triangles)
            for (const auto vertex : face.driver_vertices) vertices.insert(map[vertex]);
        for (const auto i : vertices) {
            long long tests = 0;
            const auto body = closest_refit_binding_native(layer_rest[i], spatial_index, tests);
            const Vec3 normal = refit_binding_face_normal_native(body, driver_visible);
            double depth = std::numeric_limits<double>::infinity();
            for (const auto& hit : refit_surface_line_hits_native(layer_rest[i], normal, refit.driver_diagonal * 0.03, surface.second)) {
                Vec3 point{};
                for (int c = 0; c < 3; ++c) point = add_vec3(point,
                    scale_vec3(layer_rest[map[hit.driver_vertices[c]]], hit.barycentric[c]));
                const double distance = dot_vec3(sub_vec3(layer_rest[i], point), normal);
                if (distance > tolerance * 4.0) depth = std::min(depth, distance);
            }
            if (std::isfinite(depth)) band_wall_depth[i] = depth;
        }
    }
    using LayerKey = std::pair<int, std::size_t>;
    std::map<std::pair<LayerKey, LayerKey>, int> layer_orders;
    struct LayerProbe {
        SurfaceSample inner;
        LayerKey outer;
        Vec3 normal;
        double clearance = 0.0;
        SurfaceSample contact{};
        bool exact_contact = false;
        mutable std::vector<std::array<std::size_t, 3>> live_faces;
        mutable int live_generation = -1;
    };
    std::vector<LayerProbe> layer_probes;
    std::map<LayerKey, bool> exterior_layers;
    if (fitting_masks) for (const auto& surface : layer_surfaces) {
        std::set<std::size_t> vertices;
        const auto& map = vertex_cohorts.at(surface.first.first);
        for (const auto& face : surface.second.triangles)
            for (const auto vertex : face.driver_vertices) vertices.insert(map[vertex]);
        double outside = 0.0, area = 0.0;
        for (const auto i : vertices) {
            const auto& vertex = cohorts[i].vertices.front();
            const Vec3 point = residual.at(vertex.first)[vertex.second];
            long long tests = 0;
            const auto body = closest_refit_binding_native(point, spatial_index, tests);
            const double height = dot_vec3(sub_vec3(point, mesh_editor_refit_driver_point(body, driver_visible)),
                refit_binding_face_normal_native(body, driver_visible));
            area += contact_mass[i];
            if (height >= -tolerance * 4.0) outside += contact_mass[i];
        }
        // A shell buried in a larger body needs the combined-volume exit first.
        // Isolated authored penetrations in otherwise exterior cloth still need
        // triangle contact repair after that cloth has cleared the body.
        exterior_layers[surface.first] = outside >= area * 0.5;
    }
    std::vector<bool> layer_boundary(cohorts.size(), false);
    for (const auto& edge : edge_faces) if (edge.second != 2)
        layer_boundary[edge.first.first] = layer_boundary[edge.first.second] = true;
    const auto interior_layer_feature = [&](const SurfaceSample& sample) {
        std::vector<std::size_t> active;
        for (int c = 0; c < 3; ++c) if (sample.weights[c] > 1.0e-7) active.push_back(sample.corners[c]);
        if (active.size() == 1) return !layer_boundary[active[0]];
        if (active.size() != 2) return false;
        const auto edge = edge_faces.find(std::minmax(active[0], active[1]));
        return edge != edge_faces.end() && edge->second == 2;
    };
    const auto layer_contact_normal = [&](const SurfaceSample& sample, const std::vector<Vec3>& normals,
                                          const Vec3& face_normal) {
        Vec3 normal{};
        for (int c = 0; c < 3; ++c) normal = add_vec3(normal, scale_vec3(normals[sample.corners[c]], sample.weights[c]));
        const double length = length_vec3(normal);
        if (length <= tolerance) return face_normal;
        return scale_vec3(normal, (dot_vec3(normal, face_normal) < 0.0 ? -1.0 : 1.0) / length);
    };
    std::vector<Vec3> reference_normals(cohorts.size());
    for (const auto& part : layer_garments) for (const auto& face : part.second.faces) {
        const auto& map = vertex_cohorts.at(part.first);
        const Vec3 a = sub_vec3(layer_rest[map[face[1]]], layer_rest[map[face[0]]]);
        const Vec3 b = sub_vec3(layer_rest[map[face[2]]], layer_rest[map[face[0]]]);
        const Vec3 normal{a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]};
        for (const auto vertex : face) reference_normals[map[vertex]] = add_vec3(reference_normals[map[vertex]], normal);
    }
    for (auto& normal : reference_normals) {
        const double length = length_vec3(normal);
        if (length > 0.0) normal = scale_vec3(normal, 1.0 / length);
    }
    auto live_layer_garments = layer_garments;
    std::map<LayerKey, RefitSpatialIndexNative> live_layer_surfaces;
    int live_layer_generation = 0;
    const auto refresh_layer_surfaces = [&] {
        for (auto& part : live_layer_garments) {
            const auto& map = vertex_cohorts.at(part.first);
            for (std::size_t i = 0; i < map.size(); ++i) part.second.vertices[i] = cohorts[map[i]].position;
        }
        live_layer_surfaces = mesh_editor_refit_surface_indices(live_layer_garments, vertex_cohorts, layer_roots);
        ++live_layer_generation;
    };
    const auto current_layer_sample = [&](const LayerConstraint& constraint, const Vec3& point) {
        auto other = constraint.second;
        if (constraint.ordered) {
            if (constraint.live_generation != live_layer_generation) {
                const auto surface = live_layer_surfaces.find(constraint.target_surface);
                if (surface == live_layer_surfaces.end()) throw std::runtime_error("Fit to body: opposing layer lost its surface");
                long long tests = 0;
                const auto binding = closest_refit_binding_native(point, surface->second, tests);
                for (int c = 0; c < 3; ++c)
                    constraint.live_corners[c] = vertex_cohorts.at(binding.driver_submesh_index)[binding.driver_vertices[c]];
                constraint.live_generation = live_layer_generation;
            }
            other.corners = constraint.live_corners;
        }
        other.weights = closest_triangle_point_native(point, live_point(other.corners[0]),
            live_point(other.corners[1]), live_point(other.corners[2])).barycentric;
        return other;
    };
    // A rope inset into a belt is an attachment, not a nested shell. Its two
    // sides deliberately straddle the backing, so half-space constraints cannot
    // retain its visible profile. Share the backing's displacement instead of
    // independently shrinking the detail toward the body.
    struct DetailAttachment {
        std::size_t vertex;
        std::map<std::size_t, double> backing;
    };
    using DetailCandidate = std::pair<double, DetailAttachment>;
    std::map<std::size_t, double> root_areas;
    for (const auto& surface : layer_surfaces) for (const auto& face : surface.second.triangles) {
        const Vec3 a = sub_vec3(face.corners[1], face.corners[0]);
        const Vec3 b = sub_vec3(face.corners[2], face.corners[0]);
        const double area = 0.5 * length_vec3(Vec3{
            a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]});
        root_areas[surface.first.second] += area;
    }
    std::map<std::size_t, DetailCandidate> detail_candidates;
    std::map<LayerKey, std::pair<double, std::vector<DetailCandidate>>> detail_backings;
    std::map<int, LayerKey> band_backings;
    for (const auto& surface : layer_surfaces) if (band_axes.count(surface.first.second))
        band_backings.emplace(surface.first.first, surface.first);
    if (fitting_masks) for (const auto& source : layer_surfaces) {
        const auto& settings = refit.garment_settings.at(source.first.first);
        if (settings.mode != "surface" || settings.tightness_percent <= 0.0) continue;
        std::set<std::size_t> vertices;
        for (const auto& face : source.second.triangles) for (const auto v : face.driver_vertices)
            vertices.insert(vertex_cohorts.at(source.first.first)[v]);
        if (!std::all_of(vertices.begin(), vertices.end(), [&](const auto i) {
                return std::abs(cohorts[i].mobility - cohorts[*vertices.begin()].mobility) < 1.0e-9;
            })) continue;
        std::map<LayerKey, std::map<std::size_t, std::vector<DetailCandidate>>> backing_parts;
        for (const auto& target : layer_surfaces) {
            // This field preserves relief on a tightening band. Nearby coat
            // panels and loose decorations still need independent surface fits.
            if (!band_axes.count(target.first.second)) continue;
            // Count whole seam-connected surfaces, including their material
            // Parts. Strictly increasing backing area also makes attachment
            // chains acyclic even when a seam has more than one material owner.
            const double source_area = root_areas[source.first.second];
            const double target_area = root_areas[target.first.second];
            if (target.first.second == source.first.second || source_area <= 0.0
                || !std::isfinite(target_area) || !(target_area >= source_area * 4.0)) continue;
            const auto& backing_settings = refit.garment_settings.at(target.first.first);
            if (backing_settings.mode != "surface"
                || backing_settings.tightness_percent != settings.tightness_percent
                || backing_settings.intensity_percent != settings.intensity_percent) continue;
            const auto keys = std::minmax(source.first, target.first);
            const auto key = std::make_pair(keys.first, keys.second);
            auto order = layer_orders.find(key);
            if (order == layer_orders.end()) order = layer_orders.emplace(key,
                mesh_editor_refit_layer_order(layer_surfaces.at(key.first), layer_surfaces.at(key.second),
                    layer_garments, spatial_index, driver_visible, refit.driver_diagonal * 0.06, tolerance)).first;
            if (order->second != 0) continue;
            const auto& bounds = target.second.nodes[target.second.root];
            const double reach = refit.driver_diagonal * 0.01;
            const auto& source_bounds = source.second.nodes[source.second.root];
            bool local = true;
            for (int axis = 0; axis < 3; ++axis) {
                const double extent = bounds.maximum[axis] - bounds.minimum[axis];
                local &= source_bounds.maximum[axis] - source_bounds.minimum[axis]
                    <= std::max(extent * 2.5, extent + reach * 2.0);
            }
            // A long skirt or belt tail touching a waist wrap is not a local
            // ornament. Its free length must retain its own body-following field.
            if (!local) continue;
            std::vector<DetailCandidate> candidates;
            double outside = 0.0, weight = 0.0;
            for (const auto i : vertices) {
                if (cohorts[i].mobility <= 0.0 || rigid_vertex[i]
                    || refit_aabb_distance_squared_native(layer_rest[i], bounds.minimum, bounds.maximum) > reach * reach) continue;
                long long tests = 0;
                const auto nearest = closest_refit_binding_native(layer_rest[i], target.second, tests);
                if (nearest.distance > reach) continue;
                SurfaceSample backing{{}, nearest.barycentric};
                bool compatible = true;
                for (int c = 0; c < 3; ++c) {
                    const auto j = vertex_cohorts.at(target.first.first)[nearest.driver_vertices[c]];
                    backing.corners[c] = j;
                    compatible &= i != j && !rigid_vertex[j]
                        && std::abs(cohorts[i].mobility - cohorts[j].mobility) < 1.0e-9;
                }
                if (!compatible) continue;
                const Vec3 point = layer_sample_point(backing);
                const auto body = closest_refit_binding_native(layer_rest[i], spatial_index, tests);
                const auto support = closest_refit_binding_native(point, spatial_index, tests);
                const Vec3 normal = refit_binding_face_normal_native(body, driver_visible);
                if (dot_vec3(normal, refit_binding_face_normal_native(support, driver_visible)) < 0.5
                    || distance_squared_vec3(mesh_editor_refit_driver_point(body, driver_visible),
                        mesh_editor_refit_driver_point(support, driver_visible)) > reach * reach * 4.0) continue;
                const Vec3 offset = sub_vec3(layer_rest[i], point);
                std::map<std::size_t, double> support_weights;
                for (int c = 0; c < 3; ++c)
                    support_weights[backing.corners[c]] += backing.weights[c];
                DetailAttachment attachment{i, std::move(support_weights)};
                outside += contact_mass[i] * dot_vec3(offset, normal);
                weight += contact_mass[i];
                candidates.push_back({nearest.distance, attachment});
            }
            // The backing's own inner hem must not attach to outer trim.
            if (outside <= weight * tolerance * 4.0) continue;
            const auto backing_key = band_axes.count(target.first.second)
                ? band_backings.at(target.first.first) : target.first;
            auto& part = backing_parts[backing_key];
            for (const auto& candidate : candidates) part[candidate.second.vertex].push_back(candidate);
        }
        // Adjoining front/back band panels can remain separate after Bake.
        // Carry a surrounding detail with both panels. Hanging tails remain
        // separate supports; their leg-following field must not pull the rope.
        for (const auto& part : backing_parts) {
            double distance = 0.0, weight = 0.0;
            std::vector<DetailCandidate> candidates;
            for (const auto& vertex : part.second) {
                std::map<std::size_t, double> supports;
                double total = 0.0, nearest = std::numeric_limits<double>::infinity();
                const double reach = refit.driver_diagonal * 0.01;
                for (const auto& candidate : vertex.second) {
                    // Blend the displacement across adjoining panels. Choosing
                    // a different panel for each side of a thin cord can tear
                    // its cross-section when the panels slip tangentially.
                    const double kernel = std::pow(std::max(0.0, 1.0 - candidate.first * candidate.first / (reach * reach)), 2.0);
                    total += kernel;
                    nearest = std::min(nearest, candidate.first);
                    for (const auto& parent : candidate.second.backing)
                        supports[parent.first] += kernel * parent.second;
                }
                if (total <= 0.0) continue;
                for (auto& parent : supports) parent.second /= total;
                const double area = contact_mass[vertex.first];
                distance += area * nearest;
                weight += area;
                candidates.push_back({nearest, DetailAttachment{vertex.first, std::move(supports)}});
            }
            if (weight <= 0.0) continue;
            const auto previous = detail_backings.find(source.first);
            if (previous == detail_backings.end() || distance / weight < previous->second.first)
                detail_backings[source.first] = {distance / weight, std::move(candidates)};
        }
    }
    for (const auto& backing : detail_backings) {
        for (const auto& candidate : backing.second.second) detail_candidates[candidate.second.vertex] = candidate;
        // A dangling end follows the same attachment as its connected knot.
        // Letting just the near end follow the belt while the far end seeks the
        // skin independently stretches the knot and can turn its triangles over.
        std::set<std::size_t> vertices;
        for (const auto& face : layer_surfaces.at(backing.first).triangles) for (const auto v : face.driver_vertices)
            vertices.insert(vertex_cohorts.at(backing.first.first)[v]);
        for (const auto i : vertices) if (!detail_candidates.count(i)) {
            const auto closest = std::min_element(backing.second.second.begin(), backing.second.second.end(),
                [&](const auto& a, const auto& b) {
                    return distance_squared_vec3(layer_rest[i], layer_rest[a.second.vertex])
                        < distance_squared_vec3(layer_rest[i], layer_rest[b.second.vertex]);
                });
            detail_candidates[i] = {closest->first, DetailAttachment{i, closest->second.backing}};
        }
    }
    // A compact knot can contain several touching, unwelded islands. Carry
    // those islands from one backing patch so the knot keeps its construction;
    // the surrounding long cord still bends with the tightening band.
    std::set<std::size_t> compact_details;
    for (const auto& detail : detail_backings) {
        if (band_axes.count(detail.first.second)) continue;
        const auto& surface = layer_surfaces.at(detail.first);
        const auto& bounds = surface.nodes[surface.root];
        const Vec3 extent = sub_vec3(bounds.maximum, bounds.minimum);
        if (*std::max_element(extent.begin(), extent.end()) <= refit.driver_diagonal * 0.03)
            compact_details.insert(detail.first.second);
    }
    auto detail_roots = layer_roots;
    std::map<int, MeshSessionSubmesh> compact_garments;
    for (const auto& item : layer_garments) {
        MeshSessionSubmesh compact = item.second;
        compact.faces.clear();
        for (const auto& face : item.second.faces)
            if (compact_details.count(layer_roots[vertex_cohorts.at(item.first)[face[0]]]))
                compact.faces.push_back(face);
        if (!compact.faces.empty()) compact_garments.emplace(item.first, std::move(compact));
    }
    for (const auto& join : mesh_editor_refit_rigid_joins(compact_garments, vertex_cohorts,
            layer_roots, std::max(tolerance * 4.0, refit.driver_diagonal * 0.0005))) {
        if (std::abs(cohorts[join.first].mobility - cohorts[join.second].mobility) > 1.0e-9) continue;
        const auto& a = refit.garment_settings.at(cohorts[join.first].vertices.front().first);
        const auto& b = refit.garment_settings.at(cohorts[join.second].vertices.front().first);
        if (a.tightness_percent != b.tightness_percent || a.intensity_percent != b.intensity_percent) continue;
        detail_roots[root_of(detail_roots, join.second)] = root_of(detail_roots, join.first);
    }
    std::map<std::size_t, std::map<std::size_t, double>> compact_supports;
    std::map<std::size_t, double> compact_mass;
    for (const auto& detail : detail_candidates) if (compact_details.count(layer_roots[detail.first])) {
        const auto root = root_of(detail_roots, detail.first);
        const double mass = contact_mass[detail.first];
        compact_mass[root] += mass;
        for (const auto& parent : detail.second.second.backing)
            compact_supports[root][parent.first] += parent.second * mass;
    }
    for (auto& detail : detail_candidates) if (compact_details.count(layer_roots[detail.first])) {
        const auto root = root_of(detail_roots, detail.first);
        if (compact_mass[root] <= 0.0) continue;
        detail.second.second.backing = compact_supports.at(root);
        for (auto& parent : detail.second.second.backing) parent.second /= compact_mass[root];
    }
    const auto resolve_detail = [&](auto&& self, std::size_t i) -> const std::map<std::size_t, double>& {
        const auto known = detail_supports.find(i);
        if (known != detail_supports.end()) return known->second;
        auto& support = detail_supports[i];
        const auto detail = detail_candidates.find(i);
        if (detail == detail_candidates.end()) support[i] = 1.0;
        else for (const auto& backing : detail->second.second.backing)
            for (const auto& parent : self(self, backing.first)) support[parent.first] += backing.second * parent.second;
        return support;
    };
    for (const auto& detail : detail_candidates) {
        Vec3 point{};
        for (const auto& parent : resolve_detail(resolve_detail, detail.first))
            point = add_vec3(point, scale_vec3(layer_rest[parent.first], parent.second));
        detail_offsets[detail.first] = sub_vec3(layer_rest[detail.first], point);
        detail_frames[detail.first] = root_of(detail_roots, detail.first);
    }
    std::map<std::size_t, std::set<std::size_t>> detail_controls;
    for (const auto& detail : detail_frames) for (const auto& parent : detail_supports.at(detail.first))
        detail_controls[detail.second].insert(parent.first);
    const auto refresh_detail_frames = [&] {
        // Turn a connected ornament with its backing patch. Independent
        // triangle frames can disagree at panel seams and tear a thin cord.
        for (const auto& frame : detail_controls) {
            std::vector<Vec3> source, target;
            Vec3 a{}, b{};
            for (const auto i : frame.second) {
                source.push_back(layer_rest[i]);
                target.push_back(cohorts[i].position);
                a = add_vec3(a, source.back());
                b = add_vec3(b, target.back());
            }
            a = scale_vec3(a, 1.0 / source.size());
            b = scale_vec3(b, 1.0 / target.size());
            detail_rotations[frame.first] = refit_component_rotation_native(source, target, a, b);
        }
    };
    refresh_detail_frames();
    std::map<LayerKey, std::set<LayerKey>> layer_backings;
    for (const auto& detail : detail_backings) {
        std::set<LayerKey> parents;
        for (const auto& sample : detail.second.second) for (const auto& parent : detail_supports.at(sample.second.vertex)) {
            if (parent.second <= 0.0) continue;
            const auto vertex = cohorts[parent.first].vertices.front();
            parents.insert({vertex.first, layer_roots[parent.first]});
        }
        if (!parents.empty()) layer_backings[detail.first] = std::move(parents);
    }
    // A carried knot belongs to its belt's layer. Inferring another shell order
    // independently for each small strand can ask both the knot and the cloth
    // to be outside one another, or retain a large gap left by the loose outfit.
    for (const auto& attached : layer_backings) for (const auto& target : layer_surfaces) {
        if (attached.first == target.first) continue;
        const auto target_backing = layer_backings.find(target.first);
        const auto parents = target_backing == layer_backings.end() ? std::set<LayerKey>{target.first} : target_backing->second;
        bool shared = false;
        std::set<int> orders;
        for (const auto& first : attached.second) for (const auto& second : parents) {
            if (first == second) { shared = true; continue; }
            const auto keys = std::minmax(first, second);
            const auto key = std::make_pair(keys.first, keys.second);
            auto found = layer_orders.find(key);
            if (found == layer_orders.end()) found = layer_orders.emplace(key,
                mesh_editor_refit_layer_order(layer_surfaces.at(key.first), layer_surfaces.at(key.second),
                    layer_garments, spatial_index, driver_visible, refit.driver_diagonal * 0.06, tolerance)).first;
            const int value = first == key.first ? found->second : -found->second;
            if (value != 0) orders.insert(value);
        }
        if (!shared && orders.size() != 1) continue;
        const int order = shared ? 0 : *orders.begin();
        const auto keys = std::minmax(attached.first, target.first);
        layer_orders[{keys.first, keys.second}] = attached.first == keys.first ? order : -order;
    }
    const auto add_contact_weight = [&](std::map<std::size_t, double>& weights, std::size_t i, double weight) {
        const auto detail = detail_offsets.find(i);
        if (detail == detail_offsets.end()) weights[rigid_vertex[i] ? rigid_roots[i] : i] += weight;
        else for (const auto& parent : detail_supports.at(i)) weights[parent.first] += weight * parent.second;
    };
    const auto project_details = [&](double& maximum_correction) {
        // Strain in a carried strand belongs to its backing field. Moving only
        // the detail vertices is undone by the next attachment projection.
        for (int pass = 0; !validate_only && pass < 2; ++pass) for (const auto& edge : edges) {
            if (!detail_offsets.count(edge.first) && !detail_offsets.count(edge.second)) continue;
            const Vec3 delta = sub_vec3(live_point(edge.second), live_point(edge.first));
            const double length = length_vec3(delta);
            if (length <= tolerance) continue;
            const double rest = length_vec3(sub_vec3(cohorts[edge.second].original, cohorts[edge.first].original));
            const double authored = length_vec3(sub_vec3(layer_rest[edge.second], layer_rest[edge.first]));
            const double target = std::clamp(length, rest * 0.2, std::max(rest, authored) * 2.0);
            if (std::abs(length - target) <= tolerance) continue;
            const Vec3 normal = scale_vec3(delta, 1.0 / length);
            std::map<std::size_t, double> weights;
            add_contact_weight(weights, edge.first, -1.0);
            add_contact_weight(weights, edge.second, 1.0);
            double freedom = 0.0;
            for (const auto& weight : weights)
                freedom += weight.second * weight.second * cohorts[weight.first].mobility
                    * dot_vec3(normal, project_contact(weight.first, normal));
            if (freedom <= 1.0e-8) continue;
            for (const auto& weight : weights) {
                const Vec3 correction = scale_vec3(normal, (target - length) * weight.second
                    * cohorts[weight.first].mobility / freedom);
                move_contact(weight.first, correction);
                maximum_correction = std::max(maximum_correction, length_vec3(correction));
            }
        }
        for (const auto& detail : detail_offsets) {
            const Vec3 target = live_point(detail.first);
            maximum_correction = std::max(maximum_correction, length_vec3(sub_vec3(target, cohorts[detail.first].position)));
            cohorts[detail.first].position = target;
        }
    };
    for (const auto& target : layer_surfaces) {
        const int target_part = target.first.first;
        const auto target_root = target.first.second;
        const auto& target_index = target.second;
        const auto close_to_target = [&](const Vec3& point) {
            const auto& bounds = target_index.nodes[target_index.root];
            return refit_aabb_distance_squared_native(point, bounds.minimum, bounds.maximum)
                <= std::pow(refit.driver_diagonal * 0.03, 2.0);
        };
        std::vector<double> authored_side(cohorts.size(), 0.0);
        std::vector<Vec3> authored_normal(cohorts.size());
        if (fitting_masks) for (std::size_t i = 0; i < cohorts.size(); ++i) {
            if (!close_to_target(layer_rest[i])) continue;
            long long tests = 0;
            const auto nearest = closest_refit_binding_native(layer_rest[i], target_index, tests);
            if (nearest.distance > refit.driver_diagonal * 0.03) continue;
            const auto& face = nearest.driver_vertices;
            const auto& points = layer_garments.at(target_part).vertices;
            authored_normal[i] = refit_face_normal_native(points[face[0]], points[face[1]], points[face[2]]);
            authored_side[i] = dot_vec3(sub_vec3(layer_rest[i], points[face[0]]), authored_normal[i]);
        }
        const auto bind_layer = [&](const SurfaceSample& sample, int source_part) {
            const LayerKey source{source_part, layer_roots[sample.corners[0]]};
            const auto source_surface = layer_surfaces.find(source);
            // PAC exclusions retain unused vertex records. A record without a
            // usable triangle cannot establish an opposing garment layer.
            if (source_surface == layer_surfaces.end()) return;
            const Vec3 point = layer_sample_point(sample);
            if (!close_to_target(point)) return;
            long long candidate_tests = 0;
            const auto nearest = closest_refit_binding_native(point, target_index, candidate_tests);
            if (nearest.distance > refit.driver_diagonal * 0.03) return;
            SurfaceSample other{{}, nearest.barycentric};
            for (std::size_t corner = 0; corner < 3; ++corner) {
                other.corners[corner] = vertex_cohorts.at(target_part)[nearest.driver_vertices[corner]];
                for (std::size_t source = 0; source < 3; ++source) {
                    if (sample.weights[source] > 0.0 && sample.corners[source] == other.corners[corner]) return;
                }
            }
            if (rigid_vertex[sample.corners[0]] && rigid_vertex[other.corners[0]]
                && rigid_roots[sample.corners[0]] == rigid_roots[other.corners[0]]) return;
            Vec3 normal = refit_face_normal_native(
                layer_rest[other.corners[0]], layer_rest[other.corners[1]], layer_rest[other.corners[2]]
            );
            int pair_order = 0;
            if (fitting_masks && refit.garment_settings.at(source_part).mode == "surface"
                && refit.garment_settings.at(target_part).mode == "surface") {
                const auto keys = std::minmax(source, target.first);
                const auto key = std::make_pair(keys.first, keys.second);
                auto found = layer_orders.find(key);
                if (found == layer_orders.end()) found = layer_orders.emplace(key,
                    mesh_editor_refit_layer_order(layer_surfaces.at(key.first), layer_surfaces.at(key.second),
                        layer_garments, spatial_index, driver_visible, refit.driver_diagonal * 0.06, tolerance)).first;
                pair_order = source == key.first ? found->second : -found->second;
            }
            if (pair_order == 0 && refit.garment_settings.at(source_part).mode == "surface"
                && refit.garment_settings.at(target_part).mode == "surface"
                && (band_axes.count(source.second) || band_axes.count(target_root))) return;
            // Probe from the inner cloth along its outside. A nearest query in
            // this direction can instead pick a belt's side wall or back face.
            // Rays only constrain outer triangles that actually cover the cloth.
            if (pair_order < 0) {
                Vec3 direction{};
                for (int c = 0; c < 3; ++c)
                    direction = add_vec3(direction, scale_vec3(reference_normals[sample.corners[c]], sample.weights[c]));
                const double length = length_vec3(direction);
                if (length <= tolerance) return;
                direction = scale_vec3(direction, 1.0 / length);
                const auto body = closest_refit_binding_native(point, spatial_index, candidate_tests);
                const Vec3 body_normal = refit_binding_face_normal_native(body, driver_visible);
                // A buried sleeve first needs the body's combined-volume exit,
                // not an outward ray from an internal arm or torso face.
                if (dot_vec3(sub_vec3(point, mesh_editor_refit_driver_point(body, driver_visible)), body_normal)
                        < tolerance * 4.0) return;
                const Vec3 support = layer_sample_point(other);
                const double across = dot_vec3(sub_vec3(point, support), body_normal);
                if (across * across < nearest.distance * nearest.distance * 0.5) return;
                const auto support_body = closest_refit_binding_native(support, spatial_index, candidate_tests);
                if (dot_vec3(body_normal, refit_binding_face_normal_native(support_body, driver_visible)) < 0.5
                    || distance_squared_vec3(mesh_editor_refit_driver_point(body, driver_visible),
                        mesh_editor_refit_driver_point(support_body, driver_visible))
                        > std::pow(refit.driver_diagonal * 0.05, 2.0)) return;
                const double alignment = dot_vec3(direction, body_normal);
                if (std::abs(alignment) < 0.5) return;
                if (alignment < 0.0) direction = scale_vec3(direction, -1.0);
                bool before = false, after = false;
                for (const auto& hit : refit_surface_line_hits_native(point, direction, refit.driver_diagonal * 0.03, target_index)) {
                    SurfaceSample contact{{}, hit.barycentric};
                    for (int c = 0; c < 3; ++c)
                        contact.corners[c] = vertex_cohorts.at(hit.driver_submesh_index)[hit.driver_vertices[c]];
                    const double height = dot_vec3(sub_vec3(layer_sample_point(contact), point), direction);
                    before |= height < -tolerance * 4.0;
                    after |= height > tolerance * 4.0;
                }
                // Solid trim already threaded through this cloth is an authored
                // join. Its displacement links retain that construction.
                if (before && after) return;
                layer_probes.push_back({sample, target.first, direction,
                    std::max(clearances.at(source_part), clearances.at(target_part))});
                return;
            }
            const bool interior_feature = pair_order != 0 && interior_layer_feature(other);
            if (interior_feature) normal = layer_contact_normal(other, reference_normals, normal);
            if (pair_order != 0) {
                const auto body = closest_refit_binding_native(point, spatial_index, candidate_tests);
                if (dot_vec3(normal, refit_binding_face_normal_native(body, driver_visible)) < 0.0)
                    normal = scale_vec3(normal, -1.0);
            }
            const double height = dot_vec3(sub_vec3(point, layer_sample_point(other)), normal);
            // Near-coincident material skins are attachments, not measurable
            // separated shells. Their field links retain the join; assigning a
            // hard side from micrometre-scale source rounding creates chatter.
            const double order_epsilon = fitting_masks
                ? std::max(tolerance * 4.0, refit.driver_diagonal * 1.0e-5) : tolerance * 4.0;
            if ((pair_order == 0 && std::abs(height) <= order_epsilon)
                || std::abs(height) < nearest.distance * 0.15) return;
            if (fitting_masks && !interior_feature && length_vec3(sub_vec3(sub_vec3(point, layer_sample_point(other)),
                    scale_vec3(normal, height))) > tolerance * 4.0) return;
            // Intersecting authored trim has no consistent layer order in this
            // neighborhood. Its displacement links preserve the construction;
            // conflicting hard half-spaces would tear it apart or inflate it.
            if (fitting_masks && pair_order == 0) for (int c = 0; c < 3; ++c) {
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
            double minimum_gap = 0.75 * std::abs(height);
            bool flexible = fitting_masks != nullptr;
            double tightness = 1.0, clearance = 0.0;
            for (const auto& side : {sample, other}) for (int c = 0; c < 3; ++c) {
                if (side.weights[c] <= 0.0) continue;
                const auto& cohort = cohorts[side.corners[c]];
                clearance = std::max(clearance, cohort.clearance);
                for (const auto& vertex : cohort.vertices) {
                    const auto& settings = refit.garment_settings.at(vertex.first);
                    flexible &= settings.mode == "surface";
                    tightness = std::min(tightness, settings.tightness_percent / 100.0 * cohort.mobility);
                }
            }
            flexible &= pair_order != 0;
            double wall_depth = 0.0;
            for (int c = 0; c < 3; ++c) wall_depth += sample.weights[c] * band_wall_depth[sample.corners[c]];
            if (flexible) minimum_gap = mesh_editor_refit_layer_gap(
                pair_order * height <= tolerance ? std::max(std::abs(height), clearance + wall_depth) : std::abs(height),
                clearance + wall_depth, tightness, tolerance);
            const double reference_height = pair_order != 0
                ? pair_order * std::max(std::abs(height), tolerance * 4.0) : height;
            // Authored corners establish the layer order. A coarse triangle
            // cutting through the inner layer is a contact to fix, not a fold
            // whose inverted order should be preserved.
            const Vec3 rest_offset = add_vec3(sub_vec3(point, layer_sample_point(other)),
                scale_vec3(normal, reference_height - height));
            layer_constraints.push_back({sample, other, rest_offset, normal,
                std::abs(reference_height) - minimum_gap, flexible && tightness > 0.0 ? minimum_gap : -1.0,
                target.first, pair_order != 0});
        };
        for (const auto& source : garments) {
            const auto& indices = vertex_cohorts.at(source.first);
            const auto same_surface = [&](std::size_t index) {
                return source.first == target_part && layer_roots[index] == target_root;
            };
            for (const auto index : std::set<std::size_t>(indices.begin(), indices.end())) {
                if (!same_surface(index)) bind_layer({{index, index, index}, {1.0, 0.0, 0.0}}, source.first);
            }
            std::set<std::pair<std::size_t, std::size_t>> sampled_edges;
            for (const auto& face : source.second.faces) {
                const std::array<std::size_t, 3> corners{indices[face[0]], indices[face[1]], indices[face[2]]};
                if (same_surface(corners[0])) continue;
                bind_layer({corners, {1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0}}, source.first);
                for (std::size_t corner = 0; corner < 3; ++corner) {
                    sampled_edges.insert(std::minmax(corners[corner], corners[(corner + 1) % 3]));
                }
            }
            for (const auto& edge : sampled_edges) {
                bind_layer({{edge.first, edge.second, edge.second}, {0.5, 0.5, 0.0}}, source.first);
            }
        }
    }
    std::map<int, MeshSessionSubmesh> attachment_garments;
    for (const auto& detail : detail_candidates) {
        for (const auto& vertex : cohorts[detail.first].vertices)
            attachment_garments[vertex.first] = layer_garments.at(vertex.first);
        for (const auto& parent : detail.second.second.backing) for (const auto& vertex : cohorts[parent.first].vertices)
            attachment_garments[vertex.first] = layer_garments.at(vertex.first);
    }
    const auto attachment_joins = mesh_editor_refit_rigid_joins(attachment_garments, vertex_cohorts,
        layer_roots, std::max(tolerance * 4.0, refit.driver_diagonal * 0.0005));
    layer_constraints.erase(std::remove_if(layer_constraints.begin(), layer_constraints.end(), [&](const auto& constraint) {
        if (constraint.ordered) return false;
        bool attached = false;
        for (const auto& sample : {constraint.first, constraint.second}) for (const auto i : sample.corners)
            attached |= detail_offsets.count(i) != 0;
        return attached && attachment_joins.count(std::minmax(layer_roots[constraint.first.corners[0]],
            layer_roots[constraint.second.corners[0]])) != 0;
    }), layer_constraints.end());
    const bool ordered_layers = !layer_probes.empty() || std::any_of(layer_constraints.begin(), layer_constraints.end(),
        [](const auto& constraint) { return constraint.ordered; });
    if (fitting_masks) for (const auto& constraint : layer_constraints) {
        // Ordered contact moves the outer cloth away from its fixed support.
        // Diffusing that correction back through the inner shell would undo
        // the separation and drive unrelated trim in the opposite direction.
        if (constraint.ordered) continue;
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
    // Hard assemblies are moved directly by their shared contacts. Exclude
    // them from cloth diffusion and its residual norm so small cloth corrections
    // still converge when a much larger hard ornament moves at the same time.
    for (std::size_t i = 0; i < cohorts.size(); ++i)
        if (rigid_vertex[i]) contact_mass[i] = 1.0;
    for (auto it = contact_weights.begin(); it != contact_weights.end();) {
        if (rigid_vertex[it->first.first] || rigid_vertex[it->first.second]) it = contact_weights.erase(it);
        else ++it;
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
    const auto body_seam_positions = mesh_editor_refit_body_seam_positions(refit, drivers, driver_visible);
    for (const auto& item : driver_visible) {
        auto& vertices = body_vertices[item.first];
        for (const auto& point : body_seam_positions.at(item.first)) {
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
    std::set<std::size_t> body_boundary_vertices;
    for (const auto& edge : body_edge_windings) if (edge.second != 0) {
        body_boundary.push_back(edge);
        body_boundary_vertices.insert(edge.first.first);
        body_boundary_vertices.insert(edge.first.second);
    }
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
        // During tightening an open body's rim can face away from cloth spanning
        // the missing surface. Confirm that ambiguous sign before pushing a mask
        // all the way to the face-hole border. Actual near-surface clearance
        // and occupied body volume remain constraints.
        bool inside = dot_vec3(offset, normal) < 0.0;
        const auto support_edge = support.size() == 2
            ? body_edge_windings.find(std::minmax(support[0], support[1])) : body_edge_windings.end();
        const bool on_open_rim = (support.size() == 1 && body_boundary_vertices.count(support[0]))
            || (support_edge != body_edge_windings.end() && support_edge->second != 0);
        if (fitting_masks && inside && on_open_rim && !enclosed_body_region(point))
            inside = inside_body_volume(point);
        if (distance > tolerance) return scale_vec3(offset, (inside ? -1.0 : 1.0) / distance);
        const double length = length_vec3(normal);
        return length > 0.0 ? scale_vec3(normal, 1.0 / length) : refit_binding_face_normal_native(nearest, driver_visible);
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
        const Vec3 normal = refit_binding_face_normal_native(binding, driver_visible);
        const Vec3 direction = project_contact(item.first, normal);
        const double freedom = dot_vec3(normal, direction);
        if (freedom > 1.0e-8) cohort.position = add_vec3(cohort.original, scale_vec3(direction,
            point_lifts.at({binding.driver_submesh_index, binding.driver_vertices}) / freedom));
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
        Vec3 direction{};
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
    using BodyFeature = std::pair<int, std::array<int, 3>>;
    using BodyContactKey = std::pair<std::array<std::size_t, 3>, BodyFeature>;
    std::map<BodyContactKey, std::vector<std::size_t>> body_crossing_samples;
    bool body_crossings_present = false;
    bool body_contacts_ready = false;
    const auto refresh_body_crossings = [&] {
        body_contacts_ready = true;
        body_crossings_present = false;
        auto current = garments;
        std::set<int> parts;
        for (auto& part : current) {
            parts.insert(part.first);
            const auto& map = vertex_cohorts.at(part.first);
            for (std::size_t i = 0; i < map.size(); ++i) part.second.vertices[i] = live_point(map[i]);
        }
        const auto garment_index = build_refit_spatial_index_native(current, parts);
        // Either mesh may put an edge through the other's face without any
        // vertex, edge midpoint or face centroid entering the body.
        for (const bool body_edges : {false, true}) {
            const auto& source = body_edges ? spatial_index : garment_index;
            const auto& target = body_edges ? garment_index : spatial_index;
            std::set<std::tuple<int, int, int>> visited_edges;
            for (const auto& face : source.triangles) for (int edge = 0; edge < 3; ++edge) {
                const int first = face.driver_vertices[edge], second = face.driver_vertices[(edge + 1) % 3];
                const auto endpoints = std::minmax(first, second);
                if (!visited_edges.emplace(face.driver_submesh_index, endpoints.first, endpoints.second).second) continue;
                const Vec3 a = face.corners[edge], b = face.corners[(edge + 1) % 3];
                const Vec3 delta = sub_vec3(b, a);
                const double length = length_vec3(delta);
                if (length <= tolerance) continue;
                for (const auto& hit : refit_surface_line_hits_native(scale_vec3(add_vec3(a, b), 0.5),
                        scale_vec3(delta, 1.0 / length), length * 0.5, target)) {
                    body_crossings_present = true;
                    SurfaceSample sample{};
                    BodyFeature feature;
                    if (body_edges) {
                        sample.weights = hit.barycentric;
                        for (int c = 0; c < 3; ++c)
                            sample.corners[c] = vertex_cohorts.at(hit.driver_submesh_index)[hit.driver_vertices[c]];
                        feature = {face.driver_submesh_index, {first, second, second}};
                    } else {
                        Vec3 point{};
                        for (int c = 0; c < 3; ++c) point = add_vec3(point,
                            scale_vec3(driver_visible.at(hit.driver_submesh_index)[hit.driver_vertices[c]], hit.barycentric[c]));
                        const double weight = std::clamp(dot_vec3(sub_vec3(point, a), delta) / (length * length), 0.0, 1.0);
                        const auto& map = vertex_cohorts.at(face.driver_submesh_index);
                        sample = {{map[first], map[second], map[second]}, {1.0 - weight, weight, 0.0}};
                        feature.first = hit.driver_submesh_index;
                        for (int c = 0; c < 3; ++c) feature.second[c] = hit.driver_vertices[c];
                    }
                    auto corners = sample.corners;
                    std::sort(corners.begin(), corners.end());
                    std::sort(feature.second.begin(), feature.second.end());
                    double clearance = 0.0;
                    for (int c = 0; c < 3; ++c) clearance = std::max(clearance, cohorts[sample.corners[c]].clearance);
                    auto& previous = body_crossing_samples[{corners, feature}];
                    const Vec3 rest = layer_sample_point(sample);
                    const double radius = std::max(tolerance * 4.0, clearance * 0.25);
                    if (std::any_of(previous.begin(), previous.end(), [&](const auto i) {
                            return distance_squared_vec3(rest, layer_sample_point(body_constraints[i].sample)) <= radius * radius;
                        })) continue;
                    // Retain earlier contact locations as the intersection
                    // moves. Replacing them on refresh lets a coarse face walk
                    // through a curved body between successive samples.
                    previous.push_back(body_constraints.size());
                    body_constraints.push_back({sample, clearance, 0.0, {}});
                }
            }
        }
    };
    struct BandContact {
        SurfaceSample first, second;
        Vec3 normal;
        double gap;
    };
    std::vector<BandContact> band_contacts;
    using BandContactKey = std::pair<std::array<std::size_t, 3>, std::array<std::size_t, 3>>;
    std::map<BandContactKey, std::vector<std::size_t>> band_contact_samples;
    bool band_crossings_present = false;
    const auto refresh_band_crossings = [&] {
        band_crossings_present = false;
        for (const auto& item : live_layer_surfaces) {
            if (!band_axes.count(item.first.second)) continue;
            const auto& surface = item.second;
            const auto& map = vertex_cohorts.at(item.first.first);
            std::set<std::pair<int, int>> visited;
            for (const auto& face : surface.triangles) for (int edge = 0; edge < 3; ++edge) {
                const int first = face.driver_vertices[edge], second = face.driver_vertices[(edge + 1) % 3];
                if (!visited.insert(std::minmax(first, second)).second) continue;
                const Vec3 a = face.corners[edge], b = face.corners[(edge + 1) % 3];
                const Vec3 delta = sub_vec3(b, a);
                const double length = length_vec3(delta);
                if (length <= tolerance) continue;
                for (const auto& hit : refit_surface_line_hits_native(scale_vec3(add_vec3(a, b), 0.5),
                        scale_vec3(delta, 1.0 / length), length * 0.5, surface)) {
                    SurfaceSample target{{}, hit.barycentric};
                    std::array<std::size_t, 3> source_corners{};
                    bool adjacent = false;
                    for (int c = 0; c < 3; ++c) {
                        target.corners[c] = map[hit.driver_vertices[c]];
                        source_corners[c] = map[face.driver_vertices[c]];
                        for (const auto vertex : face.driver_vertices)
                            adjacent |= target.corners[c] == map[vertex];
                    }
                    if (adjacent) continue;
                    // Authored folds and knot joins are not new collisions.
                    // Test both sets of source edges before binding a repair.
                    const auto authored_crossing = [&](const auto& left, const auto& right) {
                        for (int c = 0; c < 3; ++c) {
                            MeshEditorScreenRay ray;
                            ray.origin = layer_rest[left[c]];
                            ray.direction = sub_vec3(layer_rest[left[(c + 1) % 3]], ray.origin);
                            const double reach = length_vec3(ray.direction);
                            if (reach <= tolerance) continue;
                            ray.direction = scale_vec3(ray.direction, 1.0 / reach);
                            double distance = 0.0;
                            if (mesh_editor_ray_intersects_triangle(ray, layer_rest[right[0]], layer_rest[right[1]],
                                    layer_rest[right[2]], distance) && distance > tolerance
                                    && distance < reach - tolerance) return true;
                        }
                        return false;
                    };
                    if (authored_crossing(source_corners, target.corners)
                        || authored_crossing(target.corners, source_corners)) continue;
                    const Vec3 point = sample_point(target, false);
                    const double weight = std::clamp(dot_vec3(sub_vec3(point, a), delta) / (length * length), 0.0, 1.0);
                    const SurfaceSample sample{{map[first], map[second], map[second]}, {1.0 - weight, weight, 0.0}};
                    Vec3 normal = refit_face_normal_native(layer_rest[target.corners[0]],
                        layer_rest[target.corners[1]], layer_rest[target.corners[2]]);
                    const Vec3 rest = layer_sample_point(sample);
                    const double height = dot_vec3(sub_vec3(rest, layer_sample_point(target)), normal);
                    if (std::abs(height) <= tolerance * 4.0) continue;
                    band_crossings_present = true;
                    if (height < 0.0) normal = scale_vec3(normal, -1.0);
                    auto source_key = source_corners, target_key = target.corners;
                    std::sort(source_key.begin(), source_key.end());
                    std::sort(target_key.begin(), target_key.end());
                    auto& previous = band_contact_samples[{source_key, target_key}];
                    const double gap = std::max(tolerance * 8.0,
                        std::min(std::abs(height), clearances.at(item.first.first)) * 0.1);
                    if (std::any_of(previous.begin(), previous.end(), [&](const auto i) {
                            return distance_squared_vec3(rest, layer_sample_point(band_contacts[i].first)) < gap * gap;
                        })) continue;
                    previous.push_back(band_contacts.size());
                    band_contacts.push_back({sample, target, normal, gap});
                }
            }
        }
    };
    std::vector<LayerProbe> crossing_layer_probes;
    const auto refresh_layer_crossings = [&] {
        crossing_layer_probes.clear();
        std::map<LayerKey, bool> live_exterior;
        const auto is_exterior = [&](const LayerKey& key) {
            if (exterior_layers.at(key)) return true;
            if (!body_contacts_ready || body_crossings_present) return false;
            const auto known = live_exterior.find(key);
            if (known != live_exterior.end()) return known->second;
            std::set<std::size_t> vertices;
            for (const auto& face : live_layer_surfaces.at(key).triangles)
                for (const auto v : face.driver_vertices) vertices.insert(vertex_cohorts.at(key.first)[v]);
            bool clear = !body_crossings_present;
            for (const auto i : vertices) {
                const Vec3 point = live_point(i);
                long long tests = 0;
                const auto body = closest_refit_binding_native(point, spatial_index, tests);
                const double height = dot_vec3(sub_vec3(point, mesh_editor_refit_driver_point(body, driver_visible)),
                    body_contact_normal(body, point));
                clear &= body.distance >= cohorts[i].clearance - tolerance * 4.0
                    && !(height < -tolerance * 4.0 && inside_body_volume(point));
            }
            // Combined-volume clearance owns an initially buried shell first.
            // Once it has emerged, its layer crossings need the same protection
            // as a shell that started outside the body.
            return live_exterior[key] = clear;
        };
        for (const auto& pair : layer_orders) {
            if (pair.second == 0) continue;
            const LayerKey outer = pair.second > 0 ? pair.first.first : pair.first.second;
            const LayerKey inner = pair.second > 0 ? pair.first.second : pair.first.first;
            if (!is_exterior(inner)) continue;
            const auto& outer_surface = live_layer_surfaces.at(outer);
            const auto& inner_surface = live_layer_surfaces.at(inner);
            std::set<std::tuple<long long, long long, long long>> accepted;
            for (const bool inner_edges : {false, true}) {
                const auto& source = inner_edges ? inner_surface : outer_surface;
                const auto& target = inner_edges ? outer_surface : inner_surface;
                std::set<std::pair<int, int>> visited;
                for (const auto& face : source.triangles) for (int edge = 0; edge < 3; ++edge) {
                    const auto first = face.driver_vertices[edge], second = face.driver_vertices[(edge + 1) % 3];
                    if (!visited.insert(std::minmax(first, second)).second) continue;
                    const Vec3 a = face.corners[edge], b = face.corners[(edge + 1) % 3];
                    const Vec3 delta = sub_vec3(b, a);
                    const double length = length_vec3(delta);
                    if (length <= tolerance) continue;
                    for (const auto& hit : refit_surface_line_hits_native(scale_vec3(add_vec3(a, b), 0.5),
                            scale_vec3(delta, 1.0 / length), length * 0.5, target)) {
                        SurfaceSample contact{{}, hit.barycentric};
                        for (int c = 0; c < 3; ++c)
                            contact.corners[c] = vertex_cohorts.at(hit.driver_submesh_index)[hit.driver_vertices[c]];
                        const Vec3 point = sample_point(contact, false);
                        if (!accepted.insert(mesh_editor_refit_cell(point, tolerance * 4.0)).second) continue;
                        SurfaceSample outer_contact = contact;
                        const double weight = std::clamp(dot_vec3(sub_vec3(point, a), delta) / (length * length), 0.0, 1.0);
                        const auto& map = vertex_cohorts.at(face.driver_submesh_index);
                        const SurfaceSample edge_sample{{map[first], map[second], map[second]}, {1.0 - weight, weight, 0.0}};
                        if (inner_edges) {
                            contact = edge_sample;
                        } else outer_contact = edge_sample;
                        Vec3 normal{};
                        for (int c = 0; c < 3; ++c)
                            normal = add_vec3(normal, scale_vec3(garment_normals[contact.corners[c]], contact.weights[c]));
                        const double normal_length = length_vec3(normal);
                        if (normal_length <= tolerance) continue;
                        normal = scale_vec3(normal, 1.0 / normal_length);
                        long long tests = 0;
                        const auto body = closest_refit_binding_native(point, spatial_index, tests);
                        const Vec3 outside = body_contact_normal(body, point);
                        const double alignment = dot_vec3(normal, outside);
                        if (std::abs(alignment) < 0.5) normal = outside;
                        else if (alignment < 0.0) normal = scale_vec3(normal, -1.0);
                        crossing_layer_probes.push_back({contact, outer, normal,
                            std::max(clearances.at(inner.first), clearances.at(outer.first)), outer_contact, true});
                    }
                }
            }
        }
    };
    const auto project_layer_probes = [&](double& maximum_correction, bool validate = false, bool tighten = false) {
        for (const auto* probes : {&layer_probes, &crossing_layer_probes}) for (const auto& probe : *probes) {
            const Vec3 point = sample_point(probe.inner, false);
            Vec3 normal{};
            for (int c = 0; c < 3; ++c)
                normal = add_vec3(normal, scale_vec3(garment_normals[probe.inner.corners[c]], probe.inner.weights[c]));
            const double length = length_vec3(normal);
            normal = length > tolerance ? scale_vec3(normal, 1.0 / length) : probe.normal;
            if (std::abs(dot_vec3(normal, probe.normal)) < 0.5) normal = probe.normal;
            if (dot_vec3(normal, probe.normal) < 0.0) normal = scale_vec3(normal, -1.0);
            const double reach = refit.driver_diagonal * 0.03;
            if (probe.live_generation != live_layer_generation) {
                probe.live_faces.clear();
                long long tests = 0;
                const auto inner_body = closest_refit_binding_native(point, spatial_index, tests);
                if (probe.exact_contact) probe.live_faces.push_back(probe.contact.corners);
                else for (const auto& hit : refit_surface_line_hits_native(point, normal, reach, live_layer_surfaces.at(probe.outer))) {
                    std::array<std::size_t, 3> corners{};
                    for (int c = 0; c < 3; ++c)
                        corners[c] = vertex_cohorts.at(hit.driver_submesh_index)[hit.driver_vertices[c]];
                    const Vec3 contact = sample_point({corners, hit.barycentric}, false);
                    const auto outer_body = closest_refit_binding_native(contact, spatial_index, tests);
                    if (dot_vec3(body_contact_normal(outer_body, contact), normal) < 0.5
                        || distance_squared_vec3(mesh_editor_refit_driver_point(inner_body, driver_visible),
                            mesh_editor_refit_driver_point(outer_body, driver_visible))
                            > std::pow(refit.driver_diagonal * 0.05, 2.0)) continue;
                    probe.live_faces.push_back(corners);
                }
                probe.live_generation = live_layer_generation;
            }
            for (const auto& corners : probe.live_faces) {
                SurfaceSample outer{corners, probe.exact_contact ? probe.contact.weights : Vec3{}};
                const Vec3 a = live_point(outer.corners[0]);
                const Vec3 b = live_point(outer.corners[1]);
                const Vec3 c = live_point(outer.corners[2]);
                Vec3 contact = sample_point(outer, false);
                if (!probe.exact_contact) {
                    if (std::abs(dot_vec3(refit_face_normal_native(a, b, c), normal)) < 0.3) continue;
                    MeshEditorScreenRay ray;
                    ray.origin = add_vec3(point, scale_vec3(normal, reach));
                    ray.direction = scale_vec3(normal, -1.0);
                    double distance = 0.0;
                    if (!mesh_editor_ray_intersects_triangle(ray, a, b, c, distance) || distance > reach * 2.0) continue;
                    contact = add_vec3(ray.origin, scale_vec3(ray.direction, distance));
                    outer.weights = closest_triangle_point_native(contact, a, b, c).barycentric;
                }
                const double gap = dot_vec3(sub_vec3(contact, point), normal);
                // Body clearance takes priority in a narrow joint. Shape fitting
                // targets the full layer gap; final contacts retain a positive
                // separation without forcing cloth into an adjacent body surface.
                double wall_depth = 0.0;
                for (int c = 0; c < 3; ++c) wall_depth += outer.weights[c] * band_wall_depth[outer.corners[c]];
                const double missing = probe.clearance * (tighten || band_axes.count(probe.outer.second) ? 1.0 : 0.25) + wall_depth - gap;
                if (missing <= tolerance) continue;
                if (validate) {
                    if (gap >= -tolerance * 4.0) continue;
                    throw std::runtime_error("Fit to body: Part " + std::to_string(probe.outer.first)
                        + " cannot clear Part " + std::to_string(cohorts[probe.inner.corners[0]].vertices.front().first)
                        + " beneath its triangles (gap "
                        + std::to_string(gap) + ", requested " + std::to_string(probe.clearance)
                        + "); previous preview retained");
                }
                std::map<std::size_t, double> weights;
                for (int c = 0; c < 3; ++c) add_contact_weight(weights, outer.corners[c], outer.weights[c]);
                double weight_squared = 0.0;
                for (const auto& weight : weights)
                    weight_squared += weight.second * weight.second * cohorts[weight.first].mobility
                        * dot_vec3(normal, project_contact(weight.first, normal));
                if (weight_squared <= 0.0) continue;
                maximum_correction = std::max(maximum_correction, missing);
                for (const auto& weight : weights)
                    move_contact(weight.first, scale_vec3(normal,
                        missing * weight.second * cohorts[weight.first].mobility / weight_squared));
            }
        }
    };
    const auto project_layers = [&](double& maximum_correction, bool tighten = false) {
        for (const auto& contact : band_contacts) {
            Vec3 normal = refit_face_normal_native(live_point(contact.second.corners[0]),
                live_point(contact.second.corners[1]), live_point(contact.second.corners[2]));
            if (dot_vec3(normal, contact.normal) < 0.0) normal = scale_vec3(normal, -1.0);
            const double missing = contact.gap - dot_vec3(normal,
                sub_vec3(sample_point(contact.first, false), sample_point(contact.second, false)));
            if (missing <= tolerance) continue;
            std::map<std::size_t, double> weights;
            for (int c = 0; c < 3; ++c) {
                add_contact_weight(weights, contact.first.corners[c], contact.first.weights[c]);
                add_contact_weight(weights, contact.second.corners[c], -contact.second.weights[c]);
            }
            double denominator = 0.0;
            for (const auto& weight : weights) denominator += weight.second * weight.second
                * cohorts[weight.first].mobility * dot_vec3(normal, project_contact(weight.first, normal));
            if (denominator <= 0.0) continue;
            maximum_correction = std::max(maximum_correction, missing);
            for (const auto& weight : weights) move_contact(weight.first,
                scale_vec3(normal, missing * weight.second * cohorts[weight.first].mobility / denominator));
        }
        for (const auto& constraint : layer_constraints) {
            const Vec3 point = sample_point(constraint.first, false);
            const auto other = current_layer_sample(constraint, point);
            Vec3 normal = refit_face_normal_native(live_point(other.corners[0]),
                live_point(other.corners[1]), live_point(other.corners[2]));
            const bool interior_feature = constraint.ordered && interior_layer_feature(other);
            if (interior_feature) normal = layer_contact_normal(other, garment_normals, normal);
            // Solid belt trim has inward-facing back faces too. Ordered cloth
            // contact follows the body's outside, rather than that face winding.
            if (constraint.ordered && dot_vec3(normal, constraint.normal) < 0.0)
                normal = scale_vec3(normal, -1.0);
            const Vec3 offset = sub_vec3(point, sample_point(other, false));
            const double height = dot_vec3(offset, normal);
            const double rest_height = dot_vec3(constraint.rest_offset, constraint.normal);
            const double order = rest_height > 0.0 ? 1.0 : -1.0;
            const double minimum_gap = std::abs(rest_height) - constraint.limit;
            const bool band = band_axes.count(layer_roots[constraint.first.corners[0]]) != 0;
            double missing = minimum_gap * (constraint.ordered && !tighten && !band ? 0.25 : 1.0) - order * height;
            if (missing <= tolerance) {
                bool attached = false;
                for (int c = 0; c < 3; ++c) attached |= detail_candidates.count(constraint.first.corners[c]) != 0
                    || detail_candidates.count(other.corners[c]) != 0;
                if (!tighten || constraint.snug_gap < 0.0
                    || attached
                    || order * height <= constraint.snug_gap * 1.25 + tolerance) continue;
                missing = 0.25 * (constraint.snug_gap * 1.25 - order * height);
            }
            // Preserve order throughout. During shape fitting, take up slack
            // only where a flexible layer still covers the opposing sample.
            const double correction = -order * missing;
            // A nearby open edge does not cover a point past that edge.
            if (!interior_feature && length_vec3(sub_vec3(offset, scale_vec3(normal, height)))
                    > (fitting_masks ? tolerance * 4.0 : refit.driver_diagonal * 0.005)) continue;
            maximum_correction = std::max(maximum_correction, std::abs(correction));
            // Sum each rigid piece's Jacobian before projecting: barycentric
            // corners on the same piece are one movable object.
            std::map<std::size_t, double> weights;
            for (int c = 0; c < 3; ++c) {
                const auto a = constraint.first.corners[c], b = other.corners[c];
                // An ordered outer shell must clear the inner cloth. Moving
                // both sides equally would push that cloth back into the body
                // every time its contact solver restores the body clearance.
                if (!constraint.ordered || order > 0.0)
                    add_contact_weight(weights, a, constraint.first.weights[c]);
                if (!constraint.ordered || order < 0.0)
                    add_contact_weight(weights, b, -other.weights[c]);
            }
            double weight_squared = 0.0;
            for (const auto& weight : weights)
                weight_squared += weight.second * weight.second
                    * (fitting_masks ? cohorts[weight.first].mobility : 1.0)
                    * dot_vec3(normal, project_contact(weight.first, normal));
            if (weight_squared <= 0.0) continue;
            const Vec3 delta = scale_vec3(normal, correction / weight_squared);
            for (const auto& weight : weights)
                move_contact(weight.first, scale_vec3(delta, -weight.second
                    * (fitting_masks ? cohorts[weight.first].mobility : 1.0)));
        }
        project_layer_probes(maximum_correction, false, tighten);
    };
    // Solve shape and contour constraints first, then use the final passes
    // only for sample clearance. Cohorts keep UV/material seams joined.
    constexpr int wrap_iterations = 16;
    constexpr int shape_iterations = 256;
    const int clearance_iterations = fitting_masks ? 512 : 256;
    for (int iteration = 0; !validate_only && iteration < shape_iterations + clearance_iterations; ++iteration) {
        refresh_detail_frames();
        double detail_correction = 0.0;
        project_details(detail_correction);
        std::vector<Vec3> previous;
        if (fitting_masks) for (const auto& cohort : cohorts) previous.push_back(cohort.position);
        if (iteration < shape_iterations && iteration % 64 == 0) refresh_body_anchors();
        // Finish the broad wrap before binding exact contacts, so transient
        // conforming crossings do not steer an otherwise clear cloth fit.
        if (fitting_masks && iteration >= shape_iterations && (iteration % 32 == 0
                || iteration >= shape_iterations + clearance_iterations - 16)) refresh_body_crossings();
        // Late body corrections can create a new layer contact between the
        // regular broad-phase updates. Refresh every final pass so that it can
        // be resolved before the final intersection check.
        if (ordered_layers && (iteration % 16 == 0
                || iteration >= shape_iterations + clearance_iterations - 16)) {
            refresh_layer_surfaces();
            build_garment_normals();
            refresh_layer_crossings();
        }
        if (fitting_masks && !band_axes.empty() && iteration >= shape_iterations && iteration % 16 == 0) {
            refresh_layer_surfaces();
            refresh_band_crossings();
        }
        double maximum_correction = detail_correction;
        // The conformed silhouette already supplies the shape target. Pulling
        // contacts back into that penetrating pose fights a larger body's fit.
        const double attraction = fitting_masks ? 0.0 : 0.08 * std::max(0.0, 1.0 - iteration / 128.0);
        for (Cohort& cohort : cohorts) {
            if (!cohort.has_surface) continue;
            const Vec3 delta = scale_vec3(sub_vec3(cohort.original, cohort.position), attraction);
            cohort.position = add_vec3(cohort.position, delta);
            maximum_correction = std::max(maximum_correction, length_vec3(delta));
        }
        if (iteration < shape_iterations || fitting_masks)
            project_layers(maximum_correction, fitting_masks && iteration < shape_iterations);
        project_details(maximum_correction);
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
                const auto i = sample.corners[corner];
                move_contact(i, scale_vec3(normal, missing * sample.weights[corner]
                    / (rigid_vertex[i] ? 1.0 : weight_squared)));
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
            bool attached = false;
            for (int c = 0; c < 3; ++c) attached |= detail_offsets.count(constraint.sample.corners[c]) != 0;
            if (attached) {
                std::map<std::size_t, double> weights;
                for (int c = 0; c < 3; ++c) add_contact_weight(weights, constraint.sample.corners[c], constraint.sample.weights[c]);
                double freedom = 0.0;
                for (const auto& weight : weights) freedom += weight.second * weight.second
                    * dot_vec3(normal, project_contact(weight.first, normal));
                if (freedom <= 1.0e-8) continue;
                for (const auto& weight : weights) {
                    contact_delta[weight.first] = add_vec3(contact_delta[weight.first],
                        scale_vec3(project_contact(weight.first, normal), missing * weight.second / freedom));
                    contact_count[weight.first] += 1.0;
                }
                continue;
            }
            for (std::size_t corner = 0; corner < 3; ++corner) {
                Cohort& cohort = cohorts[constraint.sample.corners[corner]];
                const double weight = constraint.sample.weights[corner];
                if (weight <= 0.0) continue;
                const auto i = constraint.sample.corners[corner];
                const Vec3 direction = project_contact(i, normal);
                const double freedom = dot_vec3(normal, direction);
                if (freedom <= 1.0e-8) continue;
                const Vec3 delta = scale_vec3(direction, missing * weight / (weight_squared * freedom));
                if (fitting_masks) {
                    contact_delta[i] = add_vec3(contact_delta[i], delta);
                    contact_count[i] += 1.0;
                } else cohort.position = add_vec3(cohort.position, delta);
            }
        }
        if (fitting_masks) {
            for (const auto& group : rigid_groups) {
                Vec3 correction{};
                for (const auto i : group.second) if (contact_count[i] > 0.0) {
                    const Vec3 candidate = project_contact(i, scale_vec3(contact_delta[i], 1.0 / contact_count[i]));
                    if (dot_vec3(candidate, candidate) > dot_vec3(correction, correction)) correction = candidate;
                }
                for (const auto i : group.second) {
                    contact_delta[i] = correction;
                    contact_count[i] = 1.0;
                }
            }
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
            const auto rigid_correction = correction;
            for (std::size_t i = 0; i < cohorts.size(); ++i)
                if (rigid_vertex[i]) correction[i] = {};
            try {
                // Large corrections need a wider patch to move around a limb;
                // small residuals need local freedom to finish contact and trim.
                const double smoothing_length = refit.driver_diagonal * 0.012;
                const double contact_length = std::clamp(maximum_correction * 2.0,
                    iteration < shape_iterations ? smoothing_length : smoothing_length * 0.1,
                    refit.driver_diagonal * 0.05);
                // Split diffusion into two shorter solves. One screened solve has
                // a pointed response to isolated contacts, especially on dense
                // meshes. The split rounds that response at the same total scale;
                // smoothing the correction rather than vertices retains folds.
                for (int smooth_pass = 0; smooth_pass < 2; ++smooth_pass)
                    correction = mesh_editor_smooth_refit_contact(correction,contact_mass,contact_weights,
                        contact_length * contact_length * 0.5);
            } catch (const std::runtime_error& error) {
                std::string parts;
                for (const auto& part:clearances) parts+=(parts.empty()?"":", ")+std::to_string(part.first);
                throw std::runtime_error("Fit to body: Parts " + parts + ": " + error.what());
            }
            for (const auto& group : rigid_groups) {
                Vec3 translation{};
                for (const auto i : group.second) translation = add_vec3(translation, rigid_correction[i]);
                translation = scale_vec3(translation, 1.0 / group.second.size());
                for (const auto i : group.second) correction[i] = translation;
            }
            for (std::size_t i = 0; i < cohorts.size(); ++i)
                cohorts[i].position = add_vec3(previous[i], scale_vec3(project_contact(i, correction[i]), cohorts[i].mobility));
            // Smoothing a common body lift must not erase layer separation.
            project_layers(maximum_correction, iteration < shape_iterations);
            project_details(maximum_correction);
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
                        if (refit.garment_settings.at(item.first).mode == "rigid_component") continue;
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
            if (!guarded) {
                throw std::runtime_error("Fit to body: Part "
                    + std::to_string(guarded_part) + " cannot preserve its triangles during clearance correction");
            }
        }
        if (maximum_correction <= tolerance) {
            // A contact can appear between broad-phase updates even though
            // every existing sample has settled. Bind it before declaring
            // convergence, so final validation does not discover it too late.
            if (fitting_masks) {
                refresh_body_crossings();
                if (body_crossings_present) continue;
                if (!band_axes.empty()) {
                    refresh_layer_surfaces();
                    refresh_band_crossings();
                    if (band_crossings_present) continue;
                }
            }
            if (ordered_layers) {
                refresh_layer_surfaces();
                build_garment_normals();
                refresh_layer_crossings();
                if (!crossing_layer_probes.empty()) continue;
                // A refreshed curved-layer normal can reveal a residual even
                // without an edge crossing. Detect it without bypassing the
                // next iteration's strain guard or publishing a late correction.
                std::vector<Vec3> settled;
                for (const auto& cohort : cohorts) settled.push_back(cohort.position);
                double refreshed_correction = 0.0;
                project_layers(refreshed_correction, false);
                project_details(refreshed_correction);
                for (std::size_t i = 0; i < cohorts.size(); ++i) cohorts[i].position = settled[i];
                if (refreshed_correction > tolerance) continue;
            }
            if (iteration >= shape_iterations) break;
            refresh_body_anchors();
            if (body_anchors.empty()) break;
        }
    }
    if (fitting_masks) {
        refresh_detail_frames();
        double unused = 0.0;
        project_details(unused);
        if (!band_axes.empty()) {
            refresh_layer_surfaces();
            refresh_band_crossings();
            if (band_crossings_present)
                throw std::runtime_error("Fit to body: a waist band still crosses its own surface; previous preview retained");
        }
    }
    if (fitting_masks) for (const auto& group : rigid_groups) {
        std::vector<Vec3> source, target;
        Vec3 a{}, b{};
        for (const auto i : group.second) {
            source.push_back(layer_rest[i]);
            target.push_back(cohorts[i].position);
            a = add_vec3(a, source.back());
            b = add_vec3(b, target.back());
        }
        a = scale_vec3(a, 1.0 / source.size());
        b = scale_vec3(b, 1.0 / target.size());
        const auto rotation = refit_component_rotation_native(source, target, a, b);
        for (std::size_t i = 0; i < source.size(); ++i)
            if (distance_squared_vec3(target[i],
                    add_vec3(b, refit_rotate_quaternion_native(rotation, sub_vec3(source[i], a))))
                    > tolerance * tolerance * 16.0)
                throw std::runtime_error("Fit to body: Part "
                    + std::to_string(cohorts[group.first].vertices.front().first)
                    + " would separate or deform a rigid assembly; previous preview retained");
    }
    if (fitting_masks) refresh_body_crossings();
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
    if (ordered_layers) {
        refresh_layer_surfaces();
        build_garment_normals();
        refresh_layer_crossings();
        double unused_correction = 0.0;
        project_layer_probes(unused_correction, true);
        if (!crossing_layer_probes.empty()) {
            throw std::runtime_error("Fit to body: Part " + std::to_string(crossing_layer_probes.front().outer.first)
                + " still intersects Part " + std::to_string(cohorts[crossing_layer_probes.front().inner.corners[0]].vertices.front().first)
                + " beneath its triangles; previous preview retained");
        }
    }
    if (fitting_masks) for (const auto& constraint : layer_constraints) {
        const Vec3 point=sample_point(constraint.first,false);
        const auto closest=current_layer_sample(constraint,point);
        Vec3 normal=refit_face_normal_native(cohorts[closest.corners[0]].position,
            cohorts[closest.corners[1]].position,cohorts[closest.corners[2]].position);
        const bool interior_feature=constraint.ordered && interior_layer_feature(closest);
        if (interior_feature) normal=layer_contact_normal(closest,garment_normals,normal);
        if (constraint.ordered && dot_vec3(normal,constraint.normal)<0.0) normal=scale_vec3(normal,-1.0);
        const Vec3 offset=sub_vec3(point,sample_point(closest,false));
        const double height=dot_vec3(offset,normal);
        // A point past an open triangle edge does not overlap that layer.
        // Only its perpendicular projection onto the face can establish order.
        if (!interior_feature && length_vec3(sub_vec3(offset,scale_vec3(normal,height))) > tolerance*4.0) continue;
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
    const auto masks = mesh_editor_refit_masks(*morph.refit, submeshes, residual);
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
        std::map<int, std::vector<Vec3>> centering_axes;
        mesh_editor_conform_refit(*morph.refit, submeshes, driver_visible, residual, masks, layer);
        mesh_editor_refit_components(*morph.refit, submeshes, driver_visible, residual, followed, masks, layer, true, &centering_axes);
        mesh_editor_validate_conformed_refit(*morph.refit, submeshes, residual, followed, layer, "conforming");
        const auto conformed = layer;
        mesh_editor_relieve_refit_surface(*morph.refit, submeshes, driver_visible, residual, layer, &masks, false, &followed, &centering_axes);
        mesh_editor_validate_conformed_refit(*morph.refit, submeshes, residual, conformed, layer, "clearance", &followed);
        // Resolve the hanging rigid pose against the settled cloth. It must not
        // perturb a separate waist-band contact solve or inherit the scarf's tilt.
        const auto settled = layer;
        mesh_editor_refit_components(*morph.refit, submeshes, driver_visible, residual, settled, masks, layer, true, nullptr, true);
        mesh_editor_validate_conformed_refit(*morph.refit, submeshes, residual, settled, layer, "rigid pose", &followed);
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

void mesh_editor_apply_refit_corrections(
    const MeshMorphRuntime& next, const std::map<int,MeshSessionSubmesh>& submeshes,
    const std::map<int,std::vector<Vec3>>& residual, std::map<int,std::vector<Vec3>>& new_layer,
    const std::map<int,std::vector<Vec3>>& post_refit
) {
    mesh_editor_add_refit_layer(next, submeshes, residual, new_layer);
    const auto masks = next.refit ? mesh_editor_refit_masks(*next.refit, submeshes, residual) : RefitMaskWeightsNative{};
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
}

void mesh_editor_apply_island_refit_corrections(
    const MeshMorphRuntime&, const std::map<int,MeshSessionSubmesh>&,
    const std::map<int,std::vector<Vec3>>&, std::map<int,std::vector<Vec3>>&,
    const std::map<int,std::vector<Vec3>>&);

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
    const bool islands = next.refit && std::any_of(next.refit->garment_settings.begin(), next.refit->garment_settings.end(),
        [](const auto& item) { return !item.second.island_settings.empty(); });
    if (islands) mesh_editor_apply_island_refit_corrections(next, submeshes, residual, new_layer, post_refit);
    else mesh_editor_apply_refit_corrections(next, submeshes, residual, new_layer, post_refit);
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
            << ",\"tightness_percent\":" << settings.tightness_percent;
        mesh_editor_write_refit_island_settings(out, settings);
        out << '}';
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
