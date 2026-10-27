// Surface fitting changes a displacement field, never the garment's rest vertices.
// Fixed, locally walked correspondences make repeat fits independent of the preview.
std::vector<Vec3>
mesh_editor_smooth_refit_contact(const std::vector<Vec3> &target, const std::vector<double> &mass,
                                 const std::map<std::pair<std::size_t, std::size_t>, double> &edges,
                                 double lambda, int maximum_iterations) {
    const std::size_t count = target.size();
    std::vector<double> diagonal(count);
    std::vector<Vec3> result(target), residual(count), direction(count), z(count);
    // The graph is fixed throughout PCG. Traverse a contiguous copy rather
    // than chasing the map's tree nodes on every matrix multiplication.
    struct Edge { std::size_t a, b; double weight; };
    std::vector<Edge> graph;
    graph.reserve(edges.size());
    for (const auto& edge : edges)
        graph.push_back({edge.first.first, edge.first.second, lambda * edge.second});
    const auto inner = [](const std::vector<Vec3> &a, const std::vector<Vec3> &b) {
        double value = 0.0;
        for (std::size_t i = 0; i < a.size(); ++i)
            value += dot_vec3(a[i], b[i]);
        return value;
    };
    double norm = 0.0;
    for (std::size_t i = 0; i < count; ++i) {
        diagonal[i] = std::max(mass[i], 1.0e-16);
        const Vec3 rhs = scale_vec3(target[i], diagonal[i]);
        norm += dot_vec3(rhs, rhs);
    }
    // Start at the requested displacement. Uniform motion is already an exact
    // solution, including on tiny retained draws after exclusions. Starting at
    // zero makes the solver reconstruct that motion through very stiff edges.
    for (const auto &edge : graph) {
        diagonal[edge.a] += edge.weight;
        diagonal[edge.b] += edge.weight;
        const Vec3 difference = scale_vec3(sub_vec3(target[edge.a], target[edge.b]), edge.weight);
        residual[edge.a] = sub_vec3(residual[edge.a], difference);
        residual[edge.b] = add_vec3(residual[edge.b], difference);
    }
    if (norm <= 1.0e-30)
        return std::vector<Vec3>(count);
    if (inner(residual, residual) <= norm * 1.0e-6)
        return result;
    const auto initial_residual = residual;
    const auto solve = [&](const auto& apply_preconditioner) {
        direction = z = apply_preconditioner(residual);
        double rz = inner(residual, z);
        for (int iteration = 0; iteration < maximum_iterations; ++iteration) {
            std::vector<Vec3> product(count);
            for (std::size_t i = 0; i < count; ++i)
                product[i] = scale_vec3(direction[i], std::max(mass[i], 1.0e-16));
            for (const auto &edge : graph) {
                const auto a = edge.a, b = edge.b;
                const Vec3 difference = scale_vec3(sub_vec3(direction[a], direction[b]), edge.weight);
                product[a] = add_vec3(product[a], difference);
                product[b] = sub_vec3(product[b], difference);
            }
            const double denominator = inner(direction, product);
            if (!std::isfinite(denominator) || denominator <= 0.0) break;
            const double alpha = rz / denominator;
            for (std::size_t i = 0; i < count; ++i) {
                result[i] = add_vec3(result[i], scale_vec3(direction[i], alpha));
                residual[i] = sub_vec3(residual[i], scale_vec3(product[i], alpha));
            }
            if (inner(residual, residual) <= norm * 1.0e-6) return true;
            z = apply_preconditioner(residual);
            const double next = inner(residual, z), beta = next / rz;
            for (std::size_t i = 0; i < count; ++i)
                direction[i] = add_vec3(z[i], scale_vec3(direction[i], beta));
            rz = next;
        }
        return false;
    };
    const auto jacobi = [&](const std::vector<Vec3>& rhs) {
        auto value = rhs;
        for (std::size_t i = 0; i < count; ++i) value[i] = scale_vec3(value[i], 1.0 / diagonal[i]);
        return value;
    };
    // Preserve established converged results exactly. Only an unfinished solve
    // gets one sparse-factor retry from the original requested displacement.
    if (solve(jacobi)) return result;
    if (maximum_iterations <= 0)
        throw std::runtime_error("clearance displacement solve did not converge; previous preview retained");
    result = target;
    residual = initial_residual;
    // IC(0) retains the sparse cloth graph in the preconditioner. Diagonal
    // scaling alone cannot resolve long stiff seams and tiny adjacent faces
    // within the same bounded PCG budget. The operator and stopping residual
    // remain unchanged; stabilizing a factor pivot changes only this aid.
    std::vector<std::vector<std::pair<std::size_t, double>>> lower(count);
    for (const auto& edge : graph) {
        const auto ends = std::minmax(edge.a, edge.b);
        if (ends.first != ends.second && edge.weight != 0.0)
            lower[ends.second].push_back({ends.first, -edge.weight});
    }
    std::vector<double> pivots(diagonal);
    for (std::size_t i = 0; i < count; ++i) {
        auto& row = lower[i];
        std::sort(row.begin(), row.end());
        std::size_t unique = 0;
        for (const auto& entry : row) {
            if (unique && row[unique - 1].first == entry.first) row[unique - 1].second += entry.second;
            else row[unique++] = entry;
        }
        row.resize(unique);
        for (std::size_t slot = 0; slot < row.size(); ++slot) {
            const auto j = row[slot].first;
            const auto& other = lower[j];
            double value = row[slot].second;
            std::size_t a = 0, b = 0;
            while (a < slot && b < other.size()) {
                if (row[a].first < other[b].first) ++a;
                else if (row[a].first > other[b].first) ++b;
                else {
                    value -= row[a].second * pivots[row[a].first] * other[b].second;
                    ++a;
                    ++b;
                }
            }
            row[slot].second = value / pivots[j];
            pivots[i] -= row[slot].second * row[slot].second * pivots[j];
        }
        pivots[i] = std::max(pivots[i], diagonal[i] * 1.0e-12);
    }
    const auto precondition = [&](const std::vector<Vec3>& rhs) {
        auto value = rhs;
        for (std::size_t i = 0; i < count; ++i)
            for (const auto& entry : lower[i])
                value[i] = sub_vec3(value[i], scale_vec3(value[entry.first], entry.second));
        for (std::size_t i = 0; i < count; ++i) value[i] = scale_vec3(value[i], 1.0 / pivots[i]);
        for (std::size_t i = count; i-- > 0;)
            for (const auto& entry : lower[i])
                value[entry.first] = sub_vec3(value[entry.first], scale_vec3(value[i], entry.second));
        return value;
    };
    if (solve(precondition)) return result;
    throw std::runtime_error("clearance displacement solve did not converge; previous preview retained");
}

void mesh_editor_conform_refit(const MeshRefitRuntime &refit, const std::map<int, MeshSessionSubmesh> &submeshes,
                               const std::map<int, std::vector<Vec3>> &driver_visible,
                               const std::map<int, std::vector<Vec3>> &residual,
                               const RefitMaskWeightsNative &masks, std::map<int, std::vector<Vec3>> &layer,
                               bool coherent_bands, bool smooth_bands) {
    struct Node {
        Vec3 point{}, normal{}, target{}, key{}, rest{};
        double area = 0.0, mobility = 1.0, tightness = 1.0;
        bool boundary = false, unsupported = false;
        std::vector<std::pair<int, std::size_t>> vertices;
    };
    struct Edge {
        std::size_t a, b;
        double weight;
    };
    const double tolerance = std::max(1.0e-6, refit.driver_diagonal * 1.0e-7);
    const double smoothing_length = refit.driver_diagonal * 0.018;
    const double lambda = smoothing_length * smoothing_length;
    const auto fail = [](int part, const char *reason) {
        throw std::runtime_error("Fit to body: Part " + std::to_string(part) + " " + reason);
    };
    std::vector<Node> nodes;
    std::map<int, std::vector<std::size_t>> indices;
    std::map<std::tuple<long long, long long, long long>, std::vector<std::size_t>> cells;
    std::map<int, MeshSessionSubmesh> garments, drivers;
    std::set<int> garment_set;
    const auto seam_positions = mesh_editor_refit_seam_positions(refit, submeshes, residual);
    for (const auto &item : refit.garment_settings) {
        if (!item.second.enabled || item.second.mode == "rigid" || item.second.tightness_percent <= 0.0)
            continue;
        const int part = item.first;
        garment_set.insert(part);
        auto &garment = garments[part];
        garment.faces = submeshes.at(part).faces;
        for (std::size_t vertex = 0; vertex < residual.at(part).size(); ++vertex) {
            const Vec3 point = add_vec3(residual.at(part)[vertex], layer.at(part)[vertex]);
            garment.vertices.push_back(point);
            const Vec3 key = seam_positions.at(part)[vertex];
            const auto cell = mesh_editor_refit_cell(key, tolerance);
            std::size_t selected = nodes.size();
            for (int x = -1; x <= 1 && selected == nodes.size(); ++x)
                for (int y = -1; y <= 1 && selected == nodes.size(); ++y)
                    for (int z = -1; z <= 1 && selected == nodes.size(); ++z) {
                        const auto found =
                            cells.find({std::get<0>(cell) + x, std::get<1>(cell) + y, std::get<2>(cell) + z});
                        if (found == cells.end())
                            continue;
                        for (const auto candidate : found->second)
                            if (distance_squared_vec3(key, nodes[candidate].key) <= tolerance * tolerance) {
                                selected = candidate;
                                break;
                            }
                    }
            if (selected == nodes.size()) {
                cells[cell].push_back(selected);
                nodes.push_back(Node{});
                nodes.back().point = point;
                nodes.back().key = key;
                nodes.back().rest = residual.at(part)[vertex];
            }
            auto &node = nodes[selected];
            node.mobility = std::min(node.mobility, mesh_editor_refit_mask_weight(masks, part, vertex));
            node.tightness = std::min(node.tightness, item.second.tightness_percent / 100.0);
            node.vertices.emplace_back(part, vertex);
            indices[part].push_back(selected);
        }
    }
    if (nodes.empty())
        return;
    // A selected Part must not open a coincident seam with an inactive Part.
    // Those neighboring vertices are fixed constraints, not extra fit targets.
    for (const auto &item : refit.garment_settings) {
        if (garment_set.count(item.first))
            continue;
        for (std::size_t vertex = 0; vertex < residual.at(item.first).size(); ++vertex) {
            const Vec3 point = seam_positions.at(item.first)[vertex];
            const auto cell = mesh_editor_refit_cell(point, tolerance);
            for (int x = -1; x <= 1; ++x)
                for (int y = -1; y <= 1; ++y)
                    for (int z = -1; z <= 1; ++z) {
                        const auto found =
                            cells.find({std::get<0>(cell) + x, std::get<1>(cell) + y, std::get<2>(cell) + z});
                        if (found == cells.end())
                            continue;
                        for (const auto i : found->second)
                            if (distance_squared_vec3(point, nodes[i].key) <= tolerance * tolerance)
                                nodes[i].mobility = 0.0;
                    }
        }
    }
    std::map<std::pair<std::size_t, std::size_t>, double> weights;
    std::map<std::pair<std::size_t, std::size_t>, int> incidence;
    for (const auto &item : garments)
        for (const auto &face : item.second.faces) {
            const auto &map = indices.at(item.first);
            const std::array<std::size_t, 3> v{map.at(face[0]), map.at(face[1]), map.at(face[2])};
            const Vec3 ab = sub_vec3(nodes[v[1]].point, nodes[v[0]].point);
            const Vec3 ac = sub_vec3(nodes[v[2]].point, nodes[v[0]].point);
            const Vec3 cross{ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2],
                             ab[0] * ac[1] - ab[1] * ac[0]};
            const double twice_area = length_vec3(cross);
            if (twice_area <= tolerance * tolerance)
                continue;
            for (int corner = 0; corner < 3; ++corner) {
                nodes[v[corner]].area += twice_area / 6.0;
                nodes[v[corner]].normal = add_vec3(nodes[v[corner]].normal, cross);
                const auto a = v[(corner + 1) % 3], b = v[(corner + 2) % 3];
                if (a == b)
                    continue;
                const auto edge = std::minmax(a, b);
                const Vec3 ca = sub_vec3(nodes[a].point, nodes[v[corner]].point);
                const Vec3 cb = sub_vec3(nodes[b].point, nodes[v[corner]].point);
                // Positive cotangents give an SPD solve even for obtuse imported faces.
                weights[edge] += std::max(0.0, dot_vec3(ca, cb) / twice_area) * 0.5;
                ++incidence[edge];
            }
        }
    // A whole-body length scale can make a narrow cuff resist contraction like
    // a rigid ring. Bound smoothing by each connected surface's physical width;
    // area/perimeter is independent of tessellation and material seam splits.
    const auto surface_roots = mesh_editor_refit_surface_roots(garments, indices, nodes.size());
    std::vector<double> surface_area(nodes.size()), surface_perimeter(nodes.size());
    for (std::size_t i = 0; i < nodes.size(); ++i)
        surface_area[surface_roots[i]] += nodes[i].area;
    for (const auto& edge : incidence)
        if (edge.second == 1)
            surface_perimeter[surface_roots[edge.first.first]] +=
                length_vec3(sub_vec3(nodes[edge.first.first].point, nodes[edge.first.second].point));
    for (auto& edge : weights) {
        const auto root = surface_roots[edge.first.first];
        if (surface_perimeter[root] <= tolerance)
            continue;
        const double local_length = std::min(smoothing_length,
            std::max(tolerance * 8.0, 0.2 * surface_area[root] / surface_perimeter[root]));
        edge.second *= local_length * local_length / lambda;
    }
    std::vector<Edge> edges;
    std::vector<std::vector<std::size_t>> neighbors(nodes.size());
    for (const auto &item : weights) {
        edges.push_back({item.first.first, item.first.second, std::max(1.0e-8, item.second)});
        neighbors[item.first.first].push_back(item.first.second);
        neighbors[item.first.second].push_back(item.first.first);
        if (incidence.at(item.first) == 1)
            nodes[item.first.first].boundary = nodes[item.first.second].boundary = true;
    }
    // Small folds can turn a vertex normal toward the feet or along the sleeve.
    // Estimate the broad cloth direction on the same area-weighted surface so
    // correspondence scoring retains longitudinal position while narrowing it.
    std::vector<Vec3> cloth_normals(nodes.size());
    std::vector<double> cloth_areas(nodes.size());
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        cloth_areas[i] = nodes[i].area;
        if (nodes[i].area > tolerance * tolerance)
            cloth_normals[i] = scale_vec3(nodes[i].normal, 1.0 / (6.0 * nodes[i].area));
    }
    try {
        // This one-time, wider field needs the same bounded budget as conforming.
        cloth_normals = mesh_editor_smooth_refit_contact(cloth_normals, cloth_areas, weights, lambda * 4.0, 512);
    } catch (const std::runtime_error&) {
        std::string parts;
        for (const auto part : garment_set)
            parts += (parts.empty() ? "" : ", ") + std::to_string(part);
        throw std::runtime_error("Fit to body: Parts " + parts +
                                 " surface direction solve did not converge; previous preview retained");
    }
    for (const auto &item : driver_visible) {
        drivers[item.first].vertices = item.second;
        drivers[item.first].faces = submeshes.at(item.first).faces;
    }
    const auto body = build_refit_spatial_index_native(drivers, refit.driver_submesh_indices);
    if (body.triangles.empty())
        fail(nodes.front().vertices.front().first, "has no usable body surface");
    using TriangleKey = std::tuple<int, int, int, int>;
    const auto key_for = [](int part, std::array<int, 3> vertices) {
        std::sort(vertices.begin(), vertices.end());
        return TriangleKey{part, vertices[0], vertices[1], vertices[2]};
    };
    std::map<TriangleKey, std::size_t> triangle_ids;
    // UV/material seams duplicate vertices without cutting the body surface.
    // Only the search graph is welded; retained bindings and region IDs stay intact.
    const auto body_seam_positions = mesh_editor_refit_body_seam_positions(refit, drivers, driver_visible);
    std::map<Vec3, std::size_t> body_welds;
    std::map<std::pair<std::size_t, std::size_t>, std::vector<std::size_t>> body_edges;
    std::vector<std::array<std::size_t, 3>> body_corners;
    for (std::size_t i = 0; i < body.triangles.size(); ++i) {
        const auto &triangle = body.triangles[i];
        triangle_ids[key_for(triangle.driver_submesh_index, triangle.driver_vertices)] = i;
        std::array<std::size_t, 3> welded{};
        for (int corner = 0; corner < 3; ++corner)
            welded[corner] = body_welds.emplace(body_seam_positions.at(triangle.driver_submesh_index)
                [triangle.driver_vertices[corner]], body_welds.size()).first->second;
        for (int corner = 0; corner < 3; ++corner) {
            body_edges[std::minmax(welded[corner], welded[(corner + 1) % 3])].push_back(i);
        }
        body_corners.push_back(welded);
    }
    std::vector<std::vector<std::size_t>> adjacent(body.triangles.size());
    for (const auto &edge : body_edges)
        for (const auto first : edge.second)
            for (const auto second : edge.second)
                if (first != second)
                    adjacent[first].push_back(second);
    std::map<std::pair<int, std::size_t>, const MeshRefitVertexBindingRuntime *> bindings;
    for (const auto &binding : refit.bindings)
        bindings[{binding.garment_submesh_index, static_cast<std::size_t>(binding.garment_vertex_index)}] =
            &binding;
    const auto garment_spatial = build_refit_spatial_index_native(garments, garment_set);
    const auto garment_surfaces = mesh_editor_refit_surface_indices(garments, indices, surface_roots);
    const auto surface_shapes = mesh_editor_refit_surface_shapes(garments, indices, surface_roots);
    std::map<std::size_t, Vec3> band_axes;
    std::map<std::size_t, Vec3> solid_band_axes;
    for (const auto& surface : garment_surfaces) {
        if (refit.garment_settings.at(surface.first.first).mode != "surface") continue;
        const Vec3 axis = mesh_editor_refit_band_axis(surface.second, body, tolerance);
        if (dot_vec3(axis, axis) > 0.5) {
            band_axes[surface.first.second] = axis;
            if (mesh_editor_refit_band_has_walls(surface.second, indices.at(surface.first.first), tolerance))
                solid_band_axes[surface.first.second] = axis;
        }
    }
    std::map<std::size_t, std::vector<std::size_t>> band_nodes;
    for (std::size_t i = 0; i < nodes.size(); ++i)
        if (nodes[i].area > 0.0 && band_axes.count(surface_roots[i])) band_nodes[surface_roots[i]].push_back(i);
    for (auto group = band_nodes.begin(); group != band_nodes.end();) {
        const auto& first = nodes[group->second.front()];
        const bool uniform = std::all_of(group->second.begin(), group->second.end(), [&](const auto i) {
            return std::abs(nodes[i].mobility - first.mobility) < 1.0e-9
                && std::abs(nodes[i].tightness - first.tightness) < 1.0e-9
                && std::all_of(nodes[i].vertices.begin(), nodes[i].vertices.end(), [&](const auto& vertex) {
                    return refit.garment_settings.at(vertex.first).mode == "surface";
                });
        });
        if (!uniform) group = band_nodes.erase(group); else ++group;
    }
    std::map<std::size_t, std::vector<std::size_t>> solid_band_nodes;
    for (const auto& group : band_nodes) if (solid_band_axes.count(group.first)) solid_band_nodes.emplace(group);
    std::map<std::size_t, Vec3> broad_band_axes;
    for (const auto& group : band_nodes) {
        const Vec3 axis = band_axes.at(group.first);
        const auto& shape = surface_shapes.at(group.first);
        const Vec3 extent = sub_vec3(shape.maximum, shape.minimum);
        double width = std::numeric_limits<double>::infinity();
        for (int c = 0; c < 3; ++c) if (std::abs(axis[c]) < 0.5) width = std::min(width, extent[c]);
        if (dot_vec3(extent, axis) > width * 0.4) broad_band_axes[group.first] = axis;
    }
    std::vector<bool> reliable(nodes.size(), false);
    const auto level_bands = [&](std::vector<Vec3>& field) {
        if (band_nodes.empty()) return;
        for (const auto& group : band_nodes) {
            const Vec3 axis = band_axes.at(group.first);
            double height = 0.0, area = 0.0;
            for (const auto i : group.second) if (reliable[i]) {
                height += dot_vec3(field[i], axis) * nodes[i].area; area += nodes[i].area;
            }
            if (area > 0.0) for (const auto i : group.second)
                field[i] = add_vec3(field[i], scale_vec3(axis, height / area - dot_vec3(field[i], axis)));
        }
        if (coherent_bands) {
            std::vector<Vec3> positions;
            std::vector<double> mass;
            for (std::size_t i = 0; i < nodes.size(); ++i) {
                positions.push_back(nodes[i].point);
                // A rejected arm/leg target must not enter the band's shared
                // field and pull the surrounding waist back toward that limb.
                mass.push_back(reliable[i] ? nodes[i].area : 0.0);
            }
            const auto& bounds = body.nodes[body.root];
            mesh_editor_cohere_refit_bands(band_nodes,band_axes,positions,
                scale_vec3(add_vec3(bounds.minimum,bounds.maximum),0.5),mass,field,false,smooth_bands);
        }
    };
    std::map<int, std::vector<Vec3>> garment_positions;
    for (const auto &item : garments)
        garment_positions[item.first] = item.second.vertices;
    // Enabled garments this solve leaves in place (0% Tightness) keep their
    // followed shape, but they still back the tightened layers that cover them:
    // a belt over a loose skirt takes up its slack down to the skirt, not
    // through it to the skin.
    std::map<int, MeshSessionSubmesh> supports;
    std::map<int, std::vector<std::size_t>> support_indices;
    std::map<int, std::vector<Vec3>> support_positions;
    std::set<int> support_set;
    std::size_t support_count = 0;
    for (const auto &item : refit.garment_settings) {
        if (!item.second.enabled || item.second.mode == "rigid" || garment_set.count(item.first))
            continue;
        const auto followed = layer.find(item.first);
        auto &support = supports[item.first];
        support.faces = submeshes.at(item.first).faces;
        for (std::size_t vertex = 0; vertex < residual.at(item.first).size(); ++vertex) {
            Vec3 point = residual.at(item.first)[vertex];
            if (followed != layer.end() && vertex < followed->second.size())
                point = add_vec3(point, followed->second[vertex]);
            support.vertices.push_back(point);
            support_indices[item.first].push_back(support_count++);
        }
        support_positions[item.first] = support.vertices;
        support_set.insert(item.first);
    }
    const auto support_roots = mesh_editor_refit_surface_roots(supports, support_indices, support_count);
    const auto support_surfaces = mesh_editor_refit_surface_indices(supports, support_indices, support_roots);
    const auto support_spatial = build_refit_spatial_index_native(supports, support_set);
    auto layered_garments = garments;
    for (const auto &item : supports)
        layered_garments.emplace(item);
    using LayerKey = std::pair<int, std::size_t>;
    const auto layer_surface = [&](const LayerKey& key) -> const RefitSpatialIndexNative& {
        const auto found = garment_surfaces.find(key);
        return found != garment_surfaces.end() ? found->second : support_surfaces.at(key);
    };
    std::map<std::pair<LayerKey, LayerKey>, int> layer_orders;
    const auto ordered_layer = [&](std::size_t source, const LayerKey& target) {
        auto first = garment_surfaces.end();
        for (const auto& vertex : nodes[source].vertices) {
            first = garment_surfaces.find({vertex.first, surface_roots[source]});
            if (first != garment_surfaces.end()) break;
        }
        if (first == garment_surfaces.end()) return false;
        const auto keys = std::minmax(first->first, target);
        const auto key = std::make_pair(keys.first, keys.second);
        auto found = layer_orders.find(key);
        if (found == layer_orders.end()) found = layer_orders.emplace(key,
            mesh_editor_refit_layer_order(layer_surface(key.first), layer_surface(key.second),
                layered_garments, body, driver_visible, refit.driver_diagonal * 0.06, tolerance)).first;
        return found->second != 0;
    };
    std::vector<std::size_t> visited(body.triangles.size(), 0);
    std::vector<Vec3> body_points(nodes.size()), body_normals(nodes.size());
    std::vector<double> support_floors(nodes.size(), -1.0);
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        auto &node = nodes[i];
        // PAC island exclusions retain vertex records after their triangles
        // disappear. These records have no surface to fit: keep their followed
        // positions without requiring a body correspondence or a solve target.
        if (node.area == 0.0) {
            node.mobility = 0.0;
            continue;
        }
        const auto vertex = node.vertices.front();
        const auto binding = bindings.find(vertex);
        if (binding == bindings.end())
            fail(vertex.first, "has incomplete body correspondences");
        const auto &seed = *binding->second;
        const auto seed_id = triangle_ids.find(key_for(seed.driver_submesh_index, seed.driver_vertices));
        if (seed_id == triangle_ids.end())
            fail(vertex.first, "has an invalid body correspondence");
        const auto region = refit.garment_regions.find(vertex.first);
        const auto allowed = [&](const RefitSpatialTriangleNative &triangle) {
            if (region == refit.garment_regions.end())
                return true;
            const auto part = region->second.find(triangle.driver_submesh_index);
            return part != region->second.end() && part->second.count(triangle.driver_vertices[0]) &&
                   part->second.count(triangle.driver_vertices[1]) &&
                   part->second.count(triangle.driver_vertices[2]);
        };
        const double reach =
            std::max(refit.driver_diagonal * 0.015, std::min(refit.driver_diagonal * 0.12, seed.distance * 1.5));
        const Vec3 seed_point = mesh_editor_refit_driver_point(seed, driver_visible);
        double best = std::numeric_limits<double>::infinity(), best_score = best;
        Vec3 garment_direction{};
        const double normal_length = length_vec3(cloth_normals[i]);
        if (normal_length > 0.15)
            garment_direction = scale_vec3(cloth_normals[i], 1.0 / normal_length);
        Vec3 target_point{}, target_normal{};
        // Walk only edge-connected triangles from the retained bind. No global
        // reprojection can jump from an arm to the torso during the solve.
        std::vector<std::size_t> pending{seed_id->second};
        visited[seed_id->second] = i + 1;
        for (std::size_t cursor = 0; cursor < pending.size(); ++cursor) {
            const auto id = pending[cursor];
            const auto &triangle = body.triangles[id];
            if (!allowed(triangle))
                continue;
            const Vec3 normal =
                refit_face_normal_native(triangle.corners[0], triangle.corners[1], triangle.corners[2]);
            // Garments can contain folded backs and double-sided trim. Their
            // winding is not a reliable outward-body classifier. Penalize
            // tangential travel in either normal direction instead. Find the
            // actual closest point in that metric, independent of triangulation.
            if (dot_vec3(normal, normal) > 0.5) {
                const auto metric = [&](const Vec3 &corner) {
                    const Vec3 offset = sub_vec3(corner, node.point);
                    if (normal_length <= 0.15)
                        return offset;
                    return sub_vec3(scale_vec3(offset, std::sqrt(5.0)),
                                     scale_vec3(garment_direction, (std::sqrt(5.0) - 1.0) *
                                                                       dot_vec3(offset, garment_direction)));
                };
                auto closest = closest_triangle_point_native({}, metric(triangle.corners[0]),
                                                                    metric(triangle.corners[1]),
                                                                    metric(triangle.corners[2]));
                const auto broad = broad_band_axes.find(surface_roots[i]);
                if (broad != broad_band_axes.end()) {
                    // This wrap retains its height contour. Choose the body
                    // cross-section at that height, rather than finding a
                    // nearer hip and subsequently discarding vertical travel.
                    std::array<double, 3> height{};
                    for (int c = 0; c < 3; ++c)
                        height[c] = dot_vec3(sub_vec3(triangle.corners[c], node.point), broad->second);
                    if (!std::all_of(height.begin(), height.end(), [&](double h) { return std::abs(h) <= tolerance; })) {
                        std::vector<Vec3> weights, section;
                        for (int c = 0; c < 3; ++c) {
                            Vec3 w{};
                            if (std::abs(height[c]) <= tolerance) { w[c] = 1.0; weights.push_back(w); }
                            const int next = (c + 1) % 3;
                            if (height[c] * height[next] < 0.0) {
                                const double t = height[c] / (height[c] - height[next]);
                                w = {}; w[c] = 1.0 - t; w[next] = t; weights.push_back(w);
                            }
                        }
                        for (const auto& w : weights) {
                            Vec3 p{};
                            for (int c = 0; c < 3; ++c) p = add_vec3(p, scale_vec3(triangle.corners[c], w[c]));
                            section.push_back(metric(p));
                        }
                        closest = ClosestTrianglePointNative{};
                        for (std::size_t a = 0; a < section.size(); ++a) for (std::size_t b = a; b < section.size(); ++b) {
                            const Vec3 edge = sub_vec3(section[b], section[a]);
                            const double length = dot_vec3(edge, edge);
                            const double t = length > tolerance * tolerance
                                ? std::clamp(-dot_vec3(section[a], edge) / length, 0.0, 1.0) : 0.0;
                            const Vec3 point = add_vec3(section[a], scale_vec3(edge, t));
                            const double distance = dot_vec3(point, point);
                            if (distance < closest.distance_squared) {
                                closest.distance_squared = distance;
                                closest.barycentric = add_vec3(scale_vec3(weights[a], 1.0 - t), scale_vec3(weights[b], t));
                            }
                        }
                    }
                }
                Vec3 point{};
                for (int corner = 0; corner < 3; ++corner)
                    point = add_vec3(point, scale_vec3(triangle.corners[corner], closest.barycentric[corner]));
                if (closest.distance_squared < best_score - tolerance * tolerance * 0.01) {
                    best_score = closest.distance_squared;
                    best = distance_squared_vec3(node.point, point);
                    target_point = point;
                    target_normal = normal;
                    node.unsupported = false;
                    for (int corner = 0; corner < 3; ++corner)
                        if (closest.barycentric[corner] <= 1.0e-7
                            && body_edges.at(std::minmax(body_corners[id][(corner + 1) % 3],
                                                        body_corners[id][(corner + 2) % 3])).size() == 1)
                            node.unsupported = true;
                }
            }
            for (const auto next : adjacent[id]) {
                if (visited[next] == i + 1)
                    continue;
                // Measure the patch on the surface, not by centroid hops, which
                // prematurely stop at coarse triangles or seam tessellation.
                const auto &candidate = body.triangles[next];
                const auto distance = closest_triangle_point_native(seed_point, candidate.corners[0],
                                                                     candidate.corners[1], candidate.corners[2]);
                if (distance.distance_squared > reach * reach || pending.size() >= 2048)
                    continue;
                visited[next] = i + 1;
                pending.push_back(next);
            }
        }
        if (!std::isfinite(best) || std::sqrt(best) > refit.driver_diagonal * 0.35)
            continue;
        const auto broad = broad_band_axes.find(surface_roots[i]);
        if (broad != broad_band_axes.end()) {
            const auto& bounds = body.nodes[body.root];
            Vec3 radial = sub_vec3(node.point, scale_vec3(add_vec3(bounds.minimum, bounds.maximum), 0.5));
            radial = sub_vec3(radial, scale_vec3(broad->second, dot_vec3(radial, broad->second)));
            // The inside of a nearby arm faces into a waist wrap. It cannot
            // support that wrap's outward surface, even when it was closest
            // at bind time. Carry this sample from the connected cloth instead
            // of pulling the rim out toward the arm or rebinding elsewhere.
            if (dot_vec3(radial, target_normal) < -tolerance) continue;
        }
        reliable[i] = true;
        body_points[i] = target_point;
        body_normals[i] = target_normal;
        // A body may omit the face underneath a mask. Its exposed rim is not
        // a surface for the covering to shrink onto: retain the followed cloth
        // there while the supported neighborhood fits. Do not invent a body cap.
        if (node.unsupported)
            continue;
        double clearance = 0.0;
        for (const auto &source : node.vertices)
            clearance = std::max(clearance, refit.garment_settings.at(source.first).clearance_percent *
                                                refit.driver_diagonal / 100.0);
        const double height = dot_vec3(sub_vec3(node.point, target_point), target_normal);
        // Flexible layers take up slack at full Tightness, retaining a clearance
        // gap and their authored order. Hard trim keeps its original standoff.
        std::map<std::pair<int, std::size_t>, std::pair<double, bool>> inner_layers;
        const bool band = band_nodes.count(surface_roots[i]) != 0;
        const bool solid_band = solid_band_nodes.count(surface_roots[i]) != 0;
        double wall_depth = 0.0;
        const auto add_inner_layer = [&](const MeshRefitVertexBindingRuntime& hit,
                                         const std::map<int, std::vector<Vec3>>& positions, const LayerKey& key) {
            if (dot_vec3(refit_binding_face_normal_native(hit, positions), target_normal) < 0.5)
                return;
            const Vec3 point = mesh_editor_refit_driver_point(hit, positions);
            const double h = dot_vec3(sub_vec3(point, target_point), target_normal);
            if (h >= height)
                return;
            // Penetration does not erase a layer. A larger body may already
            // contain both shells; retain their relative spacing as they exit.
            long long tests = 0;
            const auto inner_body = closest_refit_binding_native(point, body, tests);
            if (dot_vec3(refit_binding_face_normal_native(inner_body, driver_visible), target_normal) < 0.5)
                return;
            if (distance_squared_vec3(mesh_editor_refit_driver_point(inner_body, driver_visible),
                                      target_point) > std::pow(refit.driver_diagonal * 0.05, 2.0))
                return;
            const bool ordered = ordered_layer(i, key);
            const auto found = inner_layers.find(key);
            if (found == inner_layers.end()) inner_layers.emplace(key, std::make_pair(h, ordered));
            else {
                found->second.first = std::min(found->second.first, h);
                found->second.second &= ordered;
            }
        };
        if (garment_spatial.root >= 0) {
            for (const auto &hit : refit_surface_line_hits_native(node.point, target_normal,
                                                                  refit.driver_diagonal * 0.06, garment_spatial)) {
                // A sewn material split is still the same cloth, including a
                // turned rim. It must not become its own supporting layer.
                if (surface_roots[indices.at(hit.driver_submesh_index)[hit.driver_vertices[0]]] == surface_roots[i]) {
                    if (solid_band) wall_depth = std::max(wall_depth, height - dot_vec3(sub_vec3(
                        mesh_editor_refit_driver_point(hit, garment_positions), target_point), target_normal));
                    continue;
                }
                add_inner_layer(hit, garment_positions, std::make_pair(hit.driver_submesh_index,
                    surface_roots[indices.at(hit.driver_submesh_index)[hit.driver_vertices[0]]]));
            }
        }
        if (support_spatial.root >= 0)
            for (const auto &hit : refit_surface_line_hits_native(node.point, target_normal,
                                                                  refit.driver_diagonal * 0.06, support_spatial))
                add_inner_layer(hit, support_positions, std::make_pair(hit.driver_submesh_index,
                    support_roots[support_indices.at(hit.driver_submesh_index)[hit.driver_vertices[0]]]));
        std::vector<std::tuple<double, int, bool>> ordered_layers;
        for (const auto& inner : inner_layers)
            ordered_layers.emplace_back(inner.second.first, inner.first.first, inner.second.second);
        std::sort(ordered_layers.begin(), ordered_layers.end(), std::greater<>());
        bool flexible = std::all_of(node.vertices.begin(), node.vertices.end(), [&](const auto& vertex) {
            return refit.garment_settings.at(vertex.first).mode == "surface";
        });
        double standoff = 0.0, previous_height = height, previous_clearance = clearance, support_floor = 0.0;
        for (const auto& inner : ordered_layers) {
            const auto& settings = refit.garment_settings.at(std::get<1>(inner));
            // Nearby rope knots do not define a waist band's backing surface.
            // Keep its ordered wrap and the band's own wall depth instead. A
            // layer left in place still does: the band cannot pass through it.
            const bool support = support_set.count(std::get<1>(inner)) != 0;
            if (band && settings.mode == "surface" && !std::get<2>(inner) && !support) continue;
            const double inner_clearance = settings.clearance_percent * refit.driver_diagonal / 100.0;
            const double gap = std::max(0.0, previous_height - std::get<0>(inner));
            const bool inner_flexible = settings.mode == "surface";
            standoff += flexible && inner_flexible && std::get<2>(inner) ? mesh_editor_refit_layer_gap(gap,
                std::max(previous_clearance, inner_clearance), 1.0, tolerance) : gap;
            previous_height = std::get<0>(inner);
            previous_clearance = inner_clearance;
            flexible = inner_flexible;
            // A layer left in place keeps its height above the body, so the
            // layers over it stack from there rather than from the skin.
            if (support)
                support_floor = std::max(support_floor, std::get<0>(inner) + standoff);
        }
        // Reserve a small contact band for interpolation over curved body faces.
        // Clearance is a minimum; the final contact solve checks the actual gap.
        node.target = sub_vec3(add_vec3(target_point, scale_vec3(target_normal,
            std::max(clearance * 2.0 + standoff, support_floor) + wall_depth)), node.point);
        if (support_floor > 0.0)
            support_floors[i] = support_floor + wall_depth;
    }
    // A protruding waist vertex can initially bind to a nearby arm. Reject an
    // isolated target only when it both jumps far beyond its cloth neighborhood
    // on the body and pulls against that neighborhood. The connected cloth solve
    // carries that vertex; retained bindings/allowed regions stay unchanged and
    // the final clearance pass still checks the complete body.
    auto coherent = reliable;
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        if (!reliable[i] || nodes[i].unsupported) continue;
        Vec3 target{}, body_center{};
        double reach = 0.0;
        std::size_t count = 0;
        for (const auto j : neighbors[i]) {
            if (!reliable[j] || nodes[j].unsupported) continue;
            target = add_vec3(target, nodes[j].target);
            body_center = add_vec3(body_center, body_points[j]);
            reach += length_vec3(sub_vec3(nodes[j].point, nodes[i].point));
            ++count;
        }
        if (count < 3) continue;
        body_center = scale_vec3(body_center, 1.0 / static_cast<double>(count));
        reach /= static_cast<double>(count);
        if (dot_vec3(nodes[i].target, target) < -0.5 * length_vec3(nodes[i].target) * length_vec3(target)
            && distance_squared_vec3(body_points[i], body_center) > 4.0 * reach * reach)
            coherent[i] = false;
    }
    reliable.swap(coherent);
    // Continue the interior fit gradient to an open rim. A zero-gradient rim
    // leaves the waist/cuff at the width of the row behind it on a tapering body.
    // Extrapolate displacement, not positions, so authored cuff flare survives.
    std::vector<int> depth(nodes.size(), -1);
    std::vector<std::size_t> frontier;
    for (std::size_t i = 0; i < nodes.size(); ++i)
        if (nodes[i].boundary) {
            depth[i] = 0;
            frontier.push_back(i);
        }
    for (std::size_t cursor = 0; cursor < frontier.size(); ++cursor)
        for (const auto other : neighbors[frontier[cursor]])
            if (depth[other] < 0) {
                depth[other] = depth[frontier[cursor]] + 1;
                frontier.push_back(other);
            }
    // Thin ribbons can have no interior row. Fit their broad normal direction
    // while retaining a shared tangential translation and tiny folded details.
    std::vector<bool> seen(nodes.size(), false);
    std::vector<double> screen(nodes.size(), 0.0);
    for (std::size_t start = 0; start < nodes.size(); ++start) {
        if (seen[start])
            continue;
        std::vector<std::size_t> component{start};
        seen[start] = true;
        std::size_t interior = 0, good = 0, moving = 0;
        int maximum_depth = 0;
        Vec3 average{};
        double total = 0.0;
        for (std::size_t cursor = 0; cursor < component.size(); ++cursor) {
            const auto i = component[cursor];
            const auto &node = nodes[i];
            maximum_depth = std::max(maximum_depth, depth[i]);
            if (node.mobility > 0.0)
                ++moving;
            if (!node.boundary) {
                ++interior;
                if (reliable[i])
                    ++good;
            }
            if (reliable[i]) {
                average = add_vec3(average, scale_vec3(node.target, node.area));
                total += node.area;
            }
            for (const auto other : neighbors[i])
                if (!seen[other]) {
                    seen[other] = true;
                    component.push_back(other);
                }
        }
        if (!moving)
            continue;
        if (total <= tolerance * tolerance || (interior > 0 && good * 5 < interior * 4))
            fail(nodes[start].vertices.front().first,
                 "has unreliable body correspondences; adjust its allowed body region");
        average = scale_vec3(average, 1.0 / total);
        for (const auto i : component) {
            if (nodes[i].unsupported) {
                screen[i] = nodes[i].area;
            } else if (nodes[i].boundary && reliable[i] && broad_band_axes.count(surface_roots[i])) {
                // A reliable cross-section already supplies the rim target.
                // Extrapolating the neighboring displacement can overshoot
                // that target and make clearance inflate the neighboring rows.
                screen[i] = nodes[i].area;
            } else if (nodes[i].boundary && reliable[i]) {
                Vec3 extended{}, rim_detail{};
                double weight_sum = 0.0;
                for (const auto j : neighbors[i]) {
                    if (depth[j] != 1 || !reliable[j] || nodes[j].unsupported)
                        continue;
                    const Vec3 outward = sub_vec3(nodes[i].point, nodes[j].point);
                    const double outward_squared = dot_vec3(outward, outward);
                    for (const auto k : neighbors[j]) {
                        if (depth[k] != 2 || !reliable[k] || nodes[k].unsupported)
                            continue;
                        const Vec3 step = sub_vec3(nodes[j].point, nodes[k].point);
                        const double step_squared = dot_vec3(step, step);
                        const double projection = dot_vec3(outward, step);
                        if (projection <= 0.0 || step_squared <= tolerance * tolerance
                            || outward_squared <= tolerance * tolerance)
                            continue;
                        const double weight = projection * projection / (step_squared * outward_squared);
                        const double continuation = std::min(2.0, projection / step_squared);
                        const Vec3 target = add_vec3(nodes[j].target,
                            scale_vec3(sub_vec3(nodes[j].target, nodes[k].target),
                                       continuation));
                        extended = add_vec3(extended, scale_vec3(target, weight));
                        rim_detail = add_vec3(rim_detail,
                            scale_vec3(sub_vec3(outward, scale_vec3(step, continuation)), weight));
                        weight_sum += weight;
                    }
                }
                const double length = length_vec3(cloth_normals[i]);
                Vec3 normal = length > 0.15 ? scale_vec3(cloth_normals[i], 1.0 / length) : Vec3{};
                if (dot_vec3(normal, body_normals[i]) < 0.0)
                    normal = scale_vec3(normal, -1.0);
                if (weight_sum > 0.0) {
                    extended = scale_vec3(extended, 1.0 / weight_sum);
                    const double flare = std::max(0.0, dot_vec3(rim_detail, normal) / weight_sum);
                    nodes[i].target = add_vec3(extended, scale_vec3(normal,
                        dot_vec3(sub_vec3(nodes[i].target, extended), normal) + flare));
                    // An extrapolated target is less certain than skin contact.
                    // Keep the surrounding cloth dominant across folded layers.
                    screen[i] = nodes[i].area * 0.25;
                } else if (maximum_depth <= 1 && (interior == 0 || length > 0.15)) {
                    nodes[i].target = add_vec3(average, scale_vec3(normal,
                        dot_vec3(sub_vec3(nodes[i].target, average), normal)));
                    screen[i] = nodes[i].area;
                }
            } else if (!nodes[i].boundary && reliable[i])
                screen[i] = nodes[i].area;
        }
    }
    // A waist band tightens around the torso while retaining its height contour.
    // Give attached trim the same broad target before solving their shared field.
    std::vector<Vec3> band_targets;
    for (const auto& node : nodes) band_targets.push_back(node.target);
    level_bands(band_targets);
    for (std::size_t i = 0; i < nodes.size(); ++i) nodes[i].target = band_targets[i];
    // Rim extrapolation and band levelling must not carry a target back below
    // a layer left in place.
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        if (support_floors[i] < 0.0) continue;
        const double reached = dot_vec3(sub_vec3(add_vec3(nodes[i].point, nodes[i].target), body_points[i]),
                                        body_normals[i]);
        if (reached < support_floors[i])
            nodes[i].target = add_vec3(nodes[i].target, scale_vec3(body_normals[i], support_floors[i] - reached));
    }
    // Overlapping surface islands share a local displacement field, including
    // islands stored in one Part. A belt or folded panel follows the cloth underneath instead of independently
    // seeking the skin. Barycentric links preserve details even when the two
    // surfaces have different tessellation; they do not weld their positions.
    struct LayerLink {
        std::array<std::size_t, 4> nodes;
        std::array<double, 4> weights;
        double strength;
        Vec3 target{};
    };
    std::vector<LayerLink> layer_links;
    std::set<std::size_t> carried_roots;
    // A layer left in place does not move. A tightened piece over it settles
    // onto it in an established order, and otherwise stays with it, as it
    // would follow the cloth underneath, instead of seeking the skin through it.
    const auto link_layer = [&](std::size_t i, const LayerKey& key, const RefitSpatialIndexNative& surface,
                                const std::map<int, std::vector<Vec3>>& positions, double area, bool fixed) {
        const int part = key.first;
        const auto& bounds = surface.nodes[surface.root];
        const bool rigid = refit.garment_settings.at(part).mode == "rigid_component";
        const bool source_rigid = std::any_of(nodes[i].vertices.begin(), nodes[i].vertices.end(),
            [&](const auto& vertex) { return refit.garment_settings.at(vertex.first).mode == "rigid_component"; });
        // Hard pieces receive a rigid transform from their fitted support
        // after this solve. Their per-vertex skin targets must not pull a
        // flexible backing into that piece's incompatible deformation.
        if (rigid != source_rigid) return;
        if (!reliable[i] || (!fixed && surface_roots[i] == key.second)) return;
        if (refit_aabb_distance_squared_native(nodes[i].point, bounds.minimum, bounds.maximum)
            > std::pow(refit.driver_diagonal * 0.03, 2.0)) return;
        long long tests = 0;
        const auto nearest = closest_refit_binding_native(nodes[i].point, surface, tests);
        if (nearest.distance > refit.driver_diagonal * 0.03) return;
        const Vec3 point = mesh_editor_refit_driver_point(nearest, positions);
        const Vec3 normal = refit_binding_face_normal_native(nearest, positions);
        const double height = dot_vec3(sub_vec3(nodes[i].point, point), normal);
        if (std::abs(height) < nearest.distance * 0.15) return;
        // Nearby edges of sloping cloth need not overlap. A connection that
        // runs mostly along the body tethers a waist opening to a different
        // height on the taper. Measure against the body, not the fold normal.
        const double body_height = dot_vec3(sub_vec3(nodes[i].point, point), body_normals[i]);
        if (body_height * body_height < nearest.distance * nearest.distance * 0.5) return;
        // Only an inner support holds a layer; tightening moves away from an outer one.
        if (fixed && body_height <= 0.0) return;
        // A support holds only what lies directly on it: beneath this piece
        // along the body normal, with no tightened layer in between to carry
        // it instead, stacked over the support's floor.
        if (fixed) {
            const Vec3 down = scale_vec3(body_normals[i], -1.0);
            const auto beneath = refit_surface_line_hits_native(nodes[i].point, down, refit.driver_diagonal * 0.03, surface);
            if (std::none_of(beneath.begin(), beneath.end(), [&](const auto& hit) {
                    return dot_vec3(sub_vec3(nodes[i].point, mesh_editor_refit_driver_point(hit, positions)),
                                    body_normals[i]) > tolerance;
                })) return;
            for (const auto& hit : refit_surface_line_hits_native(nodes[i].point, down, body_height, garment_spatial)) {
                if (surface_roots[indices.at(hit.driver_submesh_index)[hit.driver_vertices[0]]] == surface_roots[i])
                    continue;
                const double depth = dot_vec3(sub_vec3(nodes[i].point,
                    mesh_editor_refit_driver_point(hit, garment_positions)), body_normals[i]);
                if (depth > tolerance && depth < body_height - tolerance) return;
            }
        }
        const auto anchor = closest_refit_binding_native(point, body, tests);
        if (dot_vec3(refit_binding_face_normal_native(anchor, driver_visible), body_normals[i]) < 0.5
            || distance_squared_vec3(mesh_editor_refit_driver_point(anchor, driver_visible), body_points[i])
                > std::pow(refit.driver_diagonal * 0.05, 2.0)) return;
        LayerLink link{{i, 0, 0, 0}, {1.0, 0.0, 0.0, 0.0}, nodes[i].area * 16.0};
        bool invalid = false;
        for (int c = 0; c < 3 && !fixed; ++c) {
            link.nodes[c + 1] = indices.at(part)[nearest.driver_vertices[c]];
            link.weights[c + 1] = -nearest.barycentric[c];
            // A discarded body target cannot support another layer either;
            // otherwise a sleeve can pull that waist vertex back to the arm.
            invalid |= link.nodes[c + 1] == i
                || (nearest.barycentric[c] > 1.0e-7 && !reliable[link.nodes[c + 1]]);
        }
        if (!invalid) {
            bool flexible = refit.garment_settings.at(part).mode == "surface";
            double clearance = refit.garment_settings.at(part).clearance_percent * refit.driver_diagonal / 100.0;
            for (const auto& vertex : nodes[i].vertices) {
                const auto& settings = refit.garment_settings.at(vertex.first);
                flexible &= settings.mode == "surface";
                clearance = std::max(clearance, settings.clearance_percent * refit.driver_diagonal / 100.0);
            }
            bool held = false;
            if (flexible && ordered_layer(i, key)) {
                const double gap = mesh_editor_refit_layer_gap(std::abs(height), clearance, 1.0, tolerance);
                link.target = scale_vec3(normal, std::copysign(gap, height) - height);
                held = true;
            } else if (flexible && area >= surface_area[surface_roots[i]] * 2.0
                       && !(fixed && band_nodes.count(surface_roots[i]))) {
                // A local ornament follows its supporting surface. Giving
                // it a second skin target first flattens the relief and
                // makes the subsequent contact solve fight its attachment.
                // A waist band over a layer left in place still tightens
                // where it is free; its floor keeps it outside that layer.
                const auto source = garment_surfaces.find({nodes[i].vertices.front().first, surface_roots[i]});
                if (source != garment_surfaces.end()) {
                    const auto& source_bounds = surface_shapes.at(surface_roots[i]);
                    bool local = true;
                    for (int axis = 0; axis < 3; ++axis) {
                        const double extent = bounds.maximum[axis] - bounds.minimum[axis];
                        local &= source_bounds.maximum[axis] - source_bounds.minimum[axis]
                            <= std::max(extent * 1.25, extent + refit.driver_diagonal * 0.02);
                    }
                    const Vec3 extent = sub_vec3(source_bounds.maximum, source_bounds.minimum);
                    if (local || (source_bounds.closed && *std::max_element(extent.begin(), extent.end())
                            <= refit.driver_diagonal * 0.25)) {
                        carried_roots.insert(surface_roots[i]);
                        held = true;
                    }
                }
            }
            // Otherwise a layer left in place is only a floor. Holding every
            // overlap in place would also hold whatever follows those pieces.
            if (fixed && !held) return;
            layer_links.push_back(link);
        }
    };
    for (const auto& item : garment_surfaces)
        for (std::size_t i = 0; i < nodes.size(); ++i)
            link_layer(i, item.first, item.second, garment_positions, surface_area[item.first.second], false);
    for (const auto& item : support_surfaces) {
        double area = 0.0;
        for (const auto& face : item.second.triangles)
            area += 0.5 * length_vec3(cross_vec3(sub_vec3(face.corners[1], face.corners[0]),
                                                 sub_vec3(face.corners[2], face.corners[0])));
        for (std::size_t i = 0; i < nodes.size(); ++i)
            link_layer(i, item.first, item.second, support_positions, area, true);
    }
    std::vector<double> diagonal(nodes.size());
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        // Broad wraps must take up waist slack instead of preserving their
        // original cylinder. Retain local smoothing, with the measured body
        // section carrying more weight than displacement regularization.
        if (broad_band_axes.count(surface_roots[i])) screen[i] *= 4.0;
        if (carried_roots.count(surface_roots[i])) screen[i] = 0.0;
    }
    std::vector<Vec3> rhs(nodes.size()), displacement(nodes.size()), r(nodes.size()), z(nodes.size()),
        direction(nodes.size());
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        // Mobility is a constraint in the system, including the seam minimum.
        // Tightness is applied after solving so all percentages share one field.
        diagonal[i] = nodes[i].mobility <= 0.0 ? 1.0 : screen[i] / std::max(1.0e-6, nodes[i].mobility);
        rhs[i] = nodes[i].mobility <= 0.0 ? Vec3{} : scale_vec3(nodes[i].target, screen[i]);
    }
    for (const auto &edge : edges) {
        if (nodes[edge.a].mobility > 0.0)
            diagonal[edge.a] += lambda * edge.weight;
        if (nodes[edge.b].mobility > 0.0)
            diagonal[edge.b] += lambda * edge.weight;
    }
    for (const auto& link : layer_links) for (int c = 0; c < 4; ++c)
        if (nodes[link.nodes[c]].mobility > 0.0) {
            diagonal[link.nodes[c]] += link.strength * link.weights[c] * link.weights[c];
            rhs[link.nodes[c]] = add_vec3(rhs[link.nodes[c]], scale_vec3(link.target, link.strength * link.weights[c]));
        }
    const auto base_diagonal = diagonal;
    const auto base_rhs = rhs;
    const auto multiply = [&](const std::vector<Vec3> &values) {
        std::vector<Vec3> result(nodes.size());
        for (std::size_t i = 0; i < nodes.size(); ++i)
            result[i] = scale_vec3(values[i], diagonal[i]);
        for (const auto &edge : edges)
            if (nodes[edge.a].mobility > 0.0 && nodes[edge.b].mobility > 0.0) {
                result[edge.a] = sub_vec3(result[edge.a], scale_vec3(values[edge.b], lambda * edge.weight));
                result[edge.b] = sub_vec3(result[edge.b], scale_vec3(values[edge.a], lambda * edge.weight));
            }
        for (const auto& link : layer_links) {
            Vec3 difference{};
            for (int c = 0; c < 4; ++c) if (nodes[link.nodes[c]].mobility > 0.0)
                difference = add_vec3(difference, scale_vec3(values[link.nodes[c]], link.weights[c]));
            for (int c = 0; c < 4; ++c) if (nodes[link.nodes[c]].mobility > 0.0)
                result[link.nodes[c]] = add_vec3(result[link.nodes[c]], scale_vec3(
                    sub_vec3(difference, scale_vec3(values[link.nodes[c]], link.weights[c])),
                    link.strength * link.weights[c]));
        }
        return result;
    };
    const auto inner = [](const std::vector<Vec3> &a, const std::vector<Vec3> &b) {
        double result = 0.0;
        for (std::size_t i = 0; i < a.size(); ++i)
            result += dot_vec3(a[i], b[i]);
        return result;
    };
    // A layer left in place is a floor, not a preference: smoothing must bend
    // the tightened cloth around it instead of pulling samples through it.
    // Hold only the samples that finish below their floor, where the field put
    // them but lifted onto the floor along the body normal, then solve again
    // from that field. The field keeps their motion along the surface.
    std::vector<char> held(nodes.size(), 0);
    std::vector<Vec3> holds(nodes.size());
    for (int round = 0;; ++round) {
        for (std::size_t i = 0; i < nodes.size(); ++i) {
            diagonal[i] = base_diagonal[i];
            rhs[i] = base_rhs[i];
            if (!held[i]) continue;
            const double weight = base_diagonal[i] * 1024.0;
            diagonal[i] += weight;
            rhs[i] = add_vec3(rhs[i], scale_vec3(holds[i], weight));
        }
        r = rhs;
        const auto start = multiply(displacement);
        for (std::size_t i = 0; i < nodes.size(); ++i) {
            if (diagonal[i] <= 0.0)
                fail(nodes[i].vertices.front().first, "contains an unconstrained vertex");
            r[i] = sub_vec3(r[i], start[i]);
            direction[i] = z[i] = scale_vec3(r[i], 1.0 / diagonal[i]);
        }
        const double norm = inner(rhs, rhs);
        double rz = inner(r, z);
        bool converged = norm <= 1.0e-30 || inner(r, r) <= norm * 1.0e-12;
        for (int iteration = 0; iteration < 512 && !converged; ++iteration) {
            const auto ad = multiply(direction);
            const double denominator = inner(direction, ad);
            if (!std::isfinite(denominator) || denominator <= 0.0)
                break;
            const double alpha = rz / denominator;
            for (std::size_t i = 0; i < nodes.size(); ++i) {
                displacement[i] = add_vec3(displacement[i], scale_vec3(direction[i], alpha));
                r[i] = sub_vec3(r[i], scale_vec3(ad[i], alpha));
            }
            converged = inner(r, r) <= norm * 1.0e-12;
            if (converged)
                break;
            for (std::size_t i = 0; i < nodes.size(); ++i)
                z[i] = scale_vec3(r[i], 1.0 / diagonal[i]);
            const double next = inner(r, z), beta = next / rz;
            for (std::size_t i = 0; i < nodes.size(); ++i)
                direction[i] = add_vec3(z[i], scale_vec3(direction[i], beta));
            rz = next;
        }
        if (!converged)
            fail(nodes.front().vertices.front().first, "fitting did not converge; previous preview retained");
        bool added = false;
        for (std::size_t i = 0; round < 8 && i < nodes.size(); ++i) {
            if (support_floors[i] < 0.0 || nodes[i].mobility <= 0.0) continue;
            const double reached = dot_vec3(sub_vec3(add_vec3(nodes[i].point, displacement[i]), body_points[i]),
                                            body_normals[i]);
            if (reached >= support_floors[i] - refit.driver_diagonal * 1.0e-4) continue;
            holds[i] = add_vec3(displacement[i], scale_vec3(body_normals[i], support_floors[i] - reached));
            held[i] = added = true;
        }
        if (!added) break;
    }
    level_bands(displacement);
    // Levelling the band again must not lower a held sample below its floor.
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        if (support_floors[i] < 0.0 || nodes[i].mobility <= 0.0) continue;
        const double reached = dot_vec3(sub_vec3(add_vec3(nodes[i].point, displacement[i]), body_points[i]),
                                        body_normals[i]);
        if (reached < support_floors[i])
            displacement[i] = add_vec3(displacement[i], scale_vec3(body_normals[i], support_floors[i] - reached));
    }
    // Constrain the actual requested pose. A valid full-strength fit can pass
    // through a folded or inverted triangle at an intermediate percentage.
    for (std::size_t i = 0; i < nodes.size(); ++i)
        displacement[i] = scale_vec3(displacement[i], nodes[i].tightness);
    // Limit local strain in the moving cloth frame. Correct only violated
    // orientation and edge constraints, leaving valid translation and rotation
    // alone instead of resetting a whole face against its neighbors.
    const auto candidate = [&](std::size_t i, double scale) {
        return add_vec3(nodes[i].point, scale_vec3(displacement[i], scale));
    };
    std::map<int, std::vector<std::set<int>>> local_neighbors;
    for (const auto& item : garments) {
        auto& neighbors = local_neighbors[item.first];
        neighbors.resize(item.second.vertices.size());
        for (const auto& face : item.second.faces) for (const int a : face) for (const int b : face)
            neighbors[a].insert(b);
    }
    for (int pass = 0; pass < 128; ++pass) {
        bool changed = false;
        for (const auto &item : garments) {
            const auto& map = indices.at(item.first);
            std::vector<std::array<double, 4>> rotations(map.size());
            for (std::size_t vertex = 0; vertex < map.size(); ++vertex) {
                std::vector<Vec3> source, target;
                Vec3 a{}, b{};
                for (const auto other : local_neighbors.at(item.first)[vertex]) {
                    source.push_back(nodes[map[other]].point);
                    target.push_back(candidate(map[other], 1.0));
                    a = add_vec3(a, source.back());
                    b = add_vec3(b, target.back());
                }
                rotations[vertex] = source.empty() ? std::array<double, 4>{1., 0., 0., 0.}
                    : refit_component_rotation_native(source, target,
                        scale_vec3(a, 1.0 / source.size()), scale_vec3(b, 1.0 / target.size()));
            }
            for (const auto &face : item.second.faces) {
                const auto &map = indices.at(item.first);
                const std::array<std::size_t, 3> v{map[face[0]], map[face[1]], map[face[2]]};
                const auto normal =
                    refit_face_normal_native(nodes[v[0]].point, nodes[v[1]].point, nodes[v[2]].point);
                if (dot_vec3(normal, normal) < 0.5)
                    continue;
                Vec3 expected{};
                for (const auto vertex : face)
                    expected = add_vec3(expected, refit_rotate_quaternion_native(rotations[vertex], normal));
                // Project only the violated strain, rather than resetting a
                // whole face's displacement. Shared corners then receive
                // compatible local corrections instead of fighting adjacent
                // folds' rotations and common translation.
                for (int c = 0; c < 3; ++c) {
                    const auto a = v[c], b = v[(c + 1) % 3];
                    const double rest = length_vec3(sub_vec3(nodes[b].point, nodes[a].point));
                    const Vec3 edge = sub_vec3(candidate(b, 1.0), candidate(a, 1.0));
                    const double length = length_vec3(edge);
                    if (rest <= tolerance || length <= tolerance) continue;
                    const double target = std::clamp(length, rest * 0.05, rest * 2.5);
                    if (std::abs(length - target) <= tolerance * 0.01) continue;
                    const double mobility = nodes[a].mobility + nodes[b].mobility;
                    if (mobility <= 0.0) continue;
                    const Vec3 correction = scale_vec3(edge, (length - target) / (length * mobility));
                    displacement[a] = add_vec3(displacement[a], scale_vec3(correction, nodes[a].mobility));
                    displacement[b] = sub_vec3(displacement[b], scale_vec3(correction, nodes[b].mobility));
                    changed = true;
                }
                const double expected_length = length_vec3(expected);
                if (expected_length <= tolerance) continue;
                expected = scale_vec3(expected, 1.0 / expected_length);
                std::array<Vec3, 3> p{candidate(v[0], 1.0), candidate(v[1], 1.0), candidate(v[2], 1.0)};
                const Vec3 rest_cross = cross_vec3(sub_vec3(nodes[v[1]].point, nodes[v[0]].point),
                    sub_vec3(nodes[v[2]].point, nodes[v[0]].point));
                const double minimum_area = length_vec3(rest_cross) * 0.05;
                const double area = dot_vec3(expected, cross_vec3(sub_vec3(p[1], p[0]), sub_vec3(p[2], p[0])));
                if (area >= minimum_area) continue;
                const std::array<Vec3, 3> gradient{
                    cross_vec3(sub_vec3(p[1], p[2]), expected),
                    cross_vec3(sub_vec3(p[2], p[0]), expected),
                    cross_vec3(sub_vec3(p[0], p[1]), expected)};
                double freedom = 0.0;
                for (int c = 0; c < 3; ++c)
                    freedom += nodes[v[c]].mobility * dot_vec3(gradient[c], gradient[c]);
                if (freedom <= tolerance * tolerance) continue;
                for (int c = 0; c < 3; ++c)
                    displacement[v[c]] = add_vec3(displacement[v[c]], scale_vec3(gradient[c],
                        (minimum_area - area) * nodes[v[c]].mobility / freedom));
                changed = true;
            }
        }
        if (!changed)
            break;
    }
    for (std::size_t i = 0; i < nodes.size(); ++i)
        for (const auto &vertex : nodes[i].vertices) {
            const Vec3 point = candidate(i, 1.0);
            // Share the displacement, retaining each Part's quantized rest
            // position. Protected vertices must not be snapped onto a neighbor.
            layer.at(vertex.first)[vertex.second] = sub_vec3(point, nodes[i].rest);
        }
}

void mesh_editor_validate_conformed_refit(const MeshRefitRuntime &refit,
                                          const std::map<int, MeshSessionSubmesh> &submeshes,
                                          const std::map<int, std::vector<Vec3>> &residual,
                                          const std::map<int, std::vector<Vec3>> &before,
                                          const std::map<int, std::vector<Vec3>> &after, const char *stage,
                                          const std::map<int, std::vector<Vec3>> *strain_reference) {
    const double tolerance = std::max(1.0e-6, refit.driver_diagonal * 1.0e-7);
    struct Seam {
        Vec3 before, after;
    };
    std::map<std::tuple<long long, long long, long long>, std::vector<Seam>> seams;
    const auto seam_positions = mesh_editor_refit_seam_positions(refit, submeshes, residual);
    for (const auto &item : refit.garment_settings) {
        if (!item.second.enabled || item.second.mode == "rigid"
            || (item.second.tightness_percent <= 0.0 && item.second.clearance_percent <= 0.0))
            continue;
        const int part = item.first;
        std::size_t face_index = 0;
        const auto fail = [&](const char *reason, double value) {
            throw std::runtime_error("Fit to body: Part " + std::to_string(part) + ", triangle " +
                                     std::to_string(face_index) +
                                     " would contain a spike, inverted or collapsed triangle after " + stage +
                                     " (" + reason + " " + std::to_string(value) + "); previous preview retained");
        };
        for (const auto &delta : after.at(part))
            for (const auto axis : delta)
                if (!std::isfinite(axis))
                    fail("nonfinite", axis);
        for (std::size_t vertex = 0; vertex < residual.at(part).size(); ++vertex) {
            const Vec3 a = seam_positions.at(part)[vertex];
            const Vec3 b = after.at(part)[vertex];
            const auto cell = mesh_editor_refit_cell(a, tolerance);
            for (int x = -1; x <= 1; ++x)
                for (int y = -1; y <= 1; ++y)
                    for (int z = -1; z <= 1; ++z) {
                        const auto found =
                            seams.find({std::get<0>(cell) + x, std::get<1>(cell) + y, std::get<2>(cell) + z});
                        if (found == seams.end())
                            continue;
                        for (const auto &seam : found->second)
                            if (distance_squared_vec3(a, seam.before) <= tolerance * tolerance &&
                                distance_squared_vec3(b, seam.after) > tolerance * tolerance * 16.0)
                                throw std::runtime_error("Fit to body: Part " + std::to_string(part) +
                                                         " would open a coincident seam after " + stage);
                    }
            seams[cell].push_back({a, b});
        }
        std::vector<std::set<int>> neighbors(residual.at(part).size());
        for (const auto &face : submeshes.at(part).faces)
            for (int a = 0; a < 3; ++a)
                for (int b = 0; b < 3; ++b)
                    neighbors[face[a]].insert(face[b]);
        if (item.second.mode == "rigid_component") {
            std::vector<bool> visited(neighbors.size(), false);
            for (std::size_t start = 0; start < neighbors.size(); ++start) {
                if (visited[start])
                    continue;
                std::vector<std::size_t> component{start};
                visited[start] = true;
                std::vector<Vec3> source, target;
                Vec3 a{}, b{};
                for (std::size_t cursor = 0; cursor < component.size(); ++cursor) {
                    const auto vertex = component[cursor];
                    source.push_back(add_vec3(residual.at(part)[vertex], before.at(part)[vertex]));
                    target.push_back(add_vec3(residual.at(part)[vertex], after.at(part)[vertex]));
                    a = add_vec3(a, source.back());
                    b = add_vec3(b, target.back());
                    for (const int other : neighbors[vertex])
                        if (!visited[other]) {
                            visited[other] = true;
                            component.push_back(other);
                        }
                }
                a = scale_vec3(a, 1.0 / source.size());
                b = scale_vec3(b, 1.0 / target.size());
                const auto rotation = refit_component_rotation_native(source, target, a, b);
                for (std::size_t i = 0; i < source.size(); ++i)
                    if (distance_squared_vec3(target[i], add_vec3(b, refit_rotate_quaternion_native(
                                                                         rotation, sub_vec3(source[i], a)))) >
                        tolerance * tolerance * 16.0)
                        throw std::runtime_error("Fit to body: Part " + std::to_string(part) +
                                                 " would change rigid component dimensions after " + stage);
            }
        }
        std::vector<std::array<double, 4>> rotations(neighbors.size());
        for (std::size_t vertex = 0; vertex < neighbors.size(); ++vertex) {
            std::vector<Vec3> source, target;
            Vec3 a{}, b{};
            for (const int other : neighbors[vertex]) {
                source.push_back(add_vec3(residual.at(part)[other], before.at(part)[other]));
                target.push_back(add_vec3(residual.at(part)[other], after.at(part)[other]));
                a = add_vec3(a, source.back());
                b = add_vec3(b, target.back());
            }
            rotations[vertex] =
                source.empty()
                    ? std::array<double, 4>{1., 0., 0., 0.}
                    : refit_component_rotation_native(source, target, scale_vec3(a, 1.0 / source.size()),
                                                      scale_vec3(b, 1.0 / source.size()));
        }
        for (const auto &face : submeshes.at(part).faces) {
            std::array<Vec3, 3> original, candidate;
            for (int corner = 0; corner < 3; ++corner) {
                original[corner] = add_vec3(residual.at(part).at(face[corner]), before.at(part).at(face[corner]));
                candidate[corner] = add_vec3(residual.at(part).at(face[corner]), after.at(part).at(face[corner]));
            }
            const Vec3 old_normal = refit_face_normal_native(original[0], original[1], original[2]);
            const Vec3 new_normal = refit_face_normal_native(candidate[0], candidate[1], candidate[2]);
            Vec3 expected{};
            for (const int vertex : face)
                expected = add_vec3(expected, refit_rotate_quaternion_native(rotations[vertex], old_normal));
            // Compare in the moving neighborhood frame: a sleeve or folded cuff
            // may rotate past its original global normal without turning inside out.
            if (dot_vec3(old_normal, old_normal) > 0.5 &&
                (dot_vec3(new_normal, new_normal) < 0.5 ||
                 (std::string(stage) != "clearance" && dot_vec3(expected, new_normal) < -0.05)))
                fail("orientation", dot_vec3(expected, new_normal));
            for (int corner = 0; corner < 3; ++corner) {
                const double a = distance_squared_vec3(original[corner], original[(corner + 1) % 3]);
                const double b = distance_squared_vec3(candidate[corner], candidate[(corner + 1) % 3]);
                // Clearance may recover an edge that conforming shortened.
                // This is a strain ceiling, never a spring toward the old width.
                double upper = a;
                if (strain_reference) {
                    const auto& reference = strain_reference->at(part);
                    upper = std::max(upper, distance_squared_vec3(
                        add_vec3(residual.at(part)[face[corner]], reference[face[corner]]),
                        add_vec3(residual.at(part)[face[(corner + 1) % 3]], reference[face[(corner + 1) % 3]])));
                }
                if (a > 1.0e-16 && (b < a * 1.0e-6 || b > upper * 9.0))
                    fail("edge ratio", std::sqrt(b / a));
            }
            ++face_index;
        }
    }
}
