// Surface fitting changes a displacement field, never the garment's rest vertices.
// Fixed, locally walked correspondences make repeat fits independent of the preview.
std::vector<Vec3>
mesh_editor_smooth_refit_contact(const std::vector<Vec3> &target, const std::vector<double> &mass,
                                 const std::map<std::pair<std::size_t, std::size_t>, double> &edges,
                                 double lambda, int maximum_iterations) {
    const std::size_t count = target.size();
    std::vector<double> diagonal(count);
    std::vector<Vec3> result(count), residual(count), direction(count), z(count);
    const auto inner = [](const std::vector<Vec3> &a, const std::vector<Vec3> &b) {
        double value = 0.0;
        for (std::size_t i = 0; i < a.size(); ++i)
            value += dot_vec3(a[i], b[i]);
        return value;
    };
    for (std::size_t i = 0; i < count; ++i) {
        diagonal[i] = std::max(mass[i], 1.0e-16);
        residual[i] = scale_vec3(target[i], diagonal[i]);
    }
    for (const auto &edge : edges) {
        diagonal[edge.first.first] += lambda * edge.second;
        diagonal[edge.first.second] += lambda * edge.second;
    }
    for (std::size_t i = 0; i < count; ++i)
        direction[i] = z[i] = scale_vec3(residual[i], 1.0 / diagonal[i]);
    const double norm = inner(residual, residual);
    double rz = inner(residual, z);
    if (norm <= 1.0e-30)
        return result;
    for (int iteration = 0; iteration < maximum_iterations; ++iteration) {
        std::vector<Vec3> product(count);
        for (std::size_t i = 0; i < count; ++i)
            product[i] = scale_vec3(direction[i], diagonal[i]);
        for (const auto &edge : edges) {
            const auto a = edge.first.first, b = edge.first.second;
            product[a] = sub_vec3(product[a], scale_vec3(direction[b], lambda * edge.second));
            product[b] = sub_vec3(product[b], scale_vec3(direction[a], lambda * edge.second));
        }
        const double denominator = inner(direction, product);
        if (!std::isfinite(denominator) || denominator <= 0.0)
            break;
        const double alpha = rz / denominator;
        for (std::size_t i = 0; i < count; ++i) {
            result[i] = add_vec3(result[i], scale_vec3(direction[i], alpha));
            residual[i] = sub_vec3(residual[i], scale_vec3(product[i], alpha));
        }
        if (inner(residual, residual) <= norm * 1.0e-6)
            return result;
        for (std::size_t i = 0; i < count; ++i)
            z[i] = scale_vec3(residual[i], 1.0 / diagonal[i]);
        const double next = inner(residual, z), beta = next / rz;
        for (std::size_t i = 0; i < count; ++i)
            direction[i] = add_vec3(z[i], scale_vec3(direction[i], beta));
        rz = next;
    }
    throw std::runtime_error("clearance displacement solve did not converge; previous preview retained");
}

void mesh_editor_conform_refit(const MeshRefitRuntime &refit, const std::map<int, MeshSessionSubmesh> &submeshes,
                               const std::map<int, std::vector<Vec3>> &driver_visible,
                               const std::map<int, std::vector<Vec3>> &residual,
                               const RefitMaskWeightsNative &masks, std::map<int, std::vector<Vec3>> &layer) {
    struct Node {
        Vec3 point{}, normal{}, target{}, key{}, rest{};
        double area = 0.0, mobility = 1.0, tightness = 1.0;
        bool boundary = false;
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
    const auto surface_roots = mesh_editor_refit_surface_roots(garments, indices, nodes.size());
    const auto garment_surfaces = mesh_editor_refit_surface_indices(garments, indices, surface_roots);
    std::map<int, std::vector<Vec3>> garment_positions;
    for (const auto &item : garments)
        garment_positions[item.first] = item.second.vertices;
    std::vector<std::size_t> visited(body.triangles.size(), 0);
    std::vector<Vec3> body_points(nodes.size()), body_normals(nodes.size());
    std::vector<bool> reliable(nodes.size(), false);
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        auto &node = nodes[i];
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
                const auto closest = closest_triangle_point_native({}, metric(triangle.corners[0]),
                                                                    metric(triangle.corners[1]),
                                                                    metric(triangle.corners[2]));
                Vec3 point{};
                for (int corner = 0; corner < 3; ++corner)
                    point = add_vec3(point, scale_vec3(triangle.corners[corner], closest.barycentric[corner]));
                if (closest.distance_squared < best_score - tolerance * tolerance * 0.01) {
                    best_score = closest.distance_squared;
                    best = distance_squared_vec3(node.point, point);
                    target_point = point;
                    target_normal = normal;
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
        reliable[i] = true;
        body_points[i] = target_point;
        body_normals[i] = target_normal;
        double clearance = 0.0;
        for (const auto &source : node.vertices)
            clearance = std::max(clearance, refit.garment_settings.at(source.first).clearance_percent *
                                                refit.driver_diagonal / 100.0);
        const double height = dot_vec3(sub_vec3(node.point, target_point), target_normal);
        // Carry stacked shells with their inner layer's field. The standoff is
        // measured on the neutral garment; projecting every shell to skin would
        // erase layer separation before collision correction could preserve it.
        double inner_height = height;
        if (garment_spatial.root >= 0) {
            for (const auto &hit : refit_surface_line_hits_native(node.point, target_normal,
                                                                  refit.driver_diagonal * 0.06, garment_spatial)) {
                if (hit.driver_submesh_index == vertex.first
                    && surface_roots[indices.at(hit.driver_submesh_index)[hit.driver_vertices[0]]] == surface_roots[i])
                    continue;
                if (dot_vec3(refit_binding_face_normal_native(hit, garment_positions), target_normal) < 0.5)
                    continue;
                const Vec3 point = mesh_editor_refit_driver_point(hit, garment_positions);
                const double h = dot_vec3(sub_vec3(point, target_point), target_normal);
                if (h >= inner_height)
                    continue;
                // Penetration does not erase a layer. A larger body may already
                // contain both shells; retain their relative spacing as they exit.
                long long tests = 0;
                const auto inner_body = closest_refit_binding_native(point, body, tests);
                if (dot_vec3(refit_binding_face_normal_native(inner_body, driver_visible), target_normal) < 0.5)
                    continue;
                if (distance_squared_vec3(mesh_editor_refit_driver_point(inner_body, driver_visible),
                                          target_point) > std::pow(refit.driver_diagonal * 0.05, 2.0))
                    continue;
                inner_height = h;
            }
        }
        const double standoff = std::max(0.0, height - inner_height);
        // Reserve a small contact band for interpolation over curved body faces.
        // Clearance is a minimum; the final contact solve checks the actual gap.
        node.target =
            sub_vec3(add_vec3(target_point, scale_vec3(target_normal, clearance * 2.0 + standoff)), node.point);
    }
    // Open boundaries have no skin attraction. The adjacent cloth supplies their
    // displacement, retaining cuff flare and avoiding independent finger binds.
    // A ribbon with no interior samples receives one translation, not a collapse.
    std::vector<bool> seen(nodes.size(), false);
    std::vector<double> screen(nodes.size(), 0.0);
    for (std::size_t start = 0; start < nodes.size(); ++start) {
        if (seen[start])
            continue;
        std::vector<std::size_t> component{start};
        seen[start] = true;
        std::size_t interior = 0, good = 0, moving = 0;
        Vec3 average{};
        double total = 0.0;
        for (std::size_t cursor = 0; cursor < component.size(); ++cursor) {
            const auto i = component[cursor];
            const auto &node = nodes[i];
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
            if (interior == 0) {
                nodes[i].target = average;
                screen[i] = nodes[i].area;
            } else if (!nodes[i].boundary && reliable[i])
                screen[i] = nodes[i].area;
        }
    }
    // Overlapping surface islands share a local displacement field, including
    // islands stored in one Part. A belt or folded panel follows the cloth underneath instead of independently
    // seeking the skin. Barycentric links preserve details even when the two
    // surfaces have different tessellation; they do not weld their positions.
    struct LayerLink {
        std::array<std::size_t, 4> nodes;
        std::array<double, 4> weights;
        double strength;
    };
    std::vector<LayerLink> layer_links;
    for (const auto& item : garment_surfaces) {
        const int part = item.first.first;
        const auto& surface = item.second;
        const auto& bounds = surface.nodes[surface.root];
        for (std::size_t i = 0; i < nodes.size(); ++i) {
            if (!reliable[i] || (surface_roots[i] == item.first.second
                && std::any_of(nodes[i].vertices.begin(), nodes[i].vertices.end(),
                    [&](const auto& vertex) { return vertex.first == part; }))) continue;
            if (refit_aabb_distance_squared_native(nodes[i].point, bounds.minimum, bounds.maximum)
                > std::pow(refit.driver_diagonal * 0.03, 2.0)) continue;
            long long tests = 0;
            const auto nearest = closest_refit_binding_native(nodes[i].point, surface, tests);
            if (nearest.distance > refit.driver_diagonal * 0.03) continue;
            const Vec3 point = mesh_editor_refit_driver_point(nearest, garment_positions);
            const Vec3 normal = refit_binding_face_normal_native(nearest, garment_positions);
            const double height = dot_vec3(sub_vec3(nodes[i].point, point), normal);
            if (std::abs(height) < nearest.distance * 0.15) continue;
            const auto anchor = closest_refit_binding_native(point, body, tests);
            if (dot_vec3(refit_binding_face_normal_native(anchor, driver_visible), body_normals[i]) < 0.5
                || distance_squared_vec3(mesh_editor_refit_driver_point(anchor, driver_visible), body_points[i])
                    > std::pow(refit.driver_diagonal * 0.05, 2.0)) continue;
            LayerLink link{{i, 0, 0, 0}, {1.0, 0.0, 0.0, 0.0}, nodes[i].area * 16.0};
            bool shared = false;
            for (int c = 0; c < 3; ++c) {
                link.nodes[c + 1] = indices.at(part)[nearest.driver_vertices[c]];
                link.weights[c + 1] = -nearest.barycentric[c];
                shared |= link.nodes[c + 1] == i;
            }
            if (!shared) layer_links.push_back(link);
        }
    }
    std::vector<double> diagonal(nodes.size());
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
        if (nodes[link.nodes[c]].mobility > 0.0)
            diagonal[link.nodes[c]] += link.strength * link.weights[c] * link.weights[c];
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
    r = rhs;
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        if (diagonal[i] <= 0.0)
            fail(nodes[i].vertices.front().first, "contains an unconstrained vertex");
        direction[i] = z[i] = scale_vec3(r[i], 1.0 / diagonal[i]);
    }
    const double norm = inner(rhs, rhs);
    double rz = inner(r, z);
    bool converged = norm <= 1.0e-30;
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
    // Limit local strain, not the common translation. Stopping every component
    // of an unsafe displacement pins small folds and creates flared hem corners;
    // carrying the triangle together lets its detail follow the fitted silhouette.
    const auto candidate = [&](std::size_t i, double scale) {
        return add_vec3(nodes[i].point, scale_vec3(displacement[i], scale));
    };
    for (int pass = 0; pass < 64; ++pass) {
        bool changed = false;
        for (const auto &item : garments) {
            const auto& map = indices.at(item.first);
            std::vector<std::set<int>> local_neighbors(item.second.vertices.size());
            for (const auto& face : item.second.faces) for (const int a : face) for (const int b : face)
                local_neighbors[a].insert(b);
            std::vector<std::array<double, 4>> rotations(map.size());
            for (std::size_t vertex = 0; vertex < map.size(); ++vertex) {
                std::vector<Vec3> source, target;
                Vec3 a{}, b{};
                for (const auto other : local_neighbors[vertex]) {
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
                Vec3 transport{};
                double mobility = 1.0;
                for (const auto i : v) {
                    transport = add_vec3(transport, scale_vec3(displacement[i], 1.0 / 3.0));
                    mobility = std::min(mobility, nodes[i].mobility);
                }
                if (mobility <= 0.0) transport = Vec3{};
                const auto transported = [&](std::size_t i, double scale) {
                    return add_vec3(nodes[i].point, add_vec3(transport,
                        scale_vec3(sub_vec3(displacement[i], transport), scale)));
                };
                const auto safe = [&](double scale) {
                    std::array<Vec3, 3> p{transported(v[0], scale), transported(v[1], scale), transported(v[2], scale)};
                    if (dot_vec3(normal, refit_face_normal_native(p[0], p[1], p[2])) < 0.1)
                        return false;
                    // Use the same moving neighborhood as final validation.
                    // A thin folded attachment can invert relative to adjacent
                    // cloth even while its global normal still points forward.
                    if (dot_vec3(expected, refit_face_normal_native(p[0], p[1], p[2])) < 0.05)
                        return false;
                    for (int c = 0; c < 3; ++c) {
                        const double a = distance_squared_vec3(nodes[v[c]].point, nodes[v[(c + 1) % 3]].point);
                        const double b = distance_squared_vec3(p[c], p[(c + 1) % 3]);
                        if (a > 1.0e-16 && (b < a * 0.0025 || b > a * 6.25))
                            return false;
                    }
                    return true;
                };
                if (safe(1.0))
                    continue;
                double low = 0.0, high = 1.0;
                for (int iteration = 0; iteration < 16; ++iteration) {
                    const double middle = (low + high) * 0.5;
                    if (safe(middle))
                        low = middle;
                    else
                        high = middle;
                }
                for (const auto i : v)
                    displacement[i] = add_vec3(transport,
                        scale_vec3(sub_vec3(displacement[i], transport), low * 0.95));
                changed = true;
            }
        }
        if (!changed)
            break;
    }
    for (std::size_t i = 0; i < nodes.size(); ++i)
        for (const auto &vertex : nodes[i].vertices) {
            const Vec3 point = candidate(i, nodes[i].tightness);
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
        if (!item.second.enabled || item.second.mode == "rigid" || item.second.tightness_percent <= 0.0)
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
