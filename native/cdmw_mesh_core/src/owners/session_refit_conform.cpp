// Surface fitting changes a displacement field, never the garment's rest vertices.
// Fixed, locally walked correspondences make repeat fits independent of the preview.
std::vector<Vec3>
mesh_editor_smooth_refit_contact(const std::vector<Vec3> &target, const std::vector<double> &mass,
                                 const std::map<std::pair<std::size_t, std::size_t>, double> &edges,
                                 double lambda) {
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
    for (int iteration = 0; iteration < 256; ++iteration) {
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
        Vec3 point{}, normal{}, target{};
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
            const auto cell = mesh_editor_refit_cell(point, tolerance);
            std::size_t selected = nodes.size();
            for (int x = -1; x <= 1 && selected == nodes.size(); ++x)
                for (int y = -1; y <= 1 && selected == nodes.size(); ++y)
                    for (int z = -1; z <= 1 && selected == nodes.size(); ++z) {
                        const auto found =
                            cells.find({std::get<0>(cell) + x, std::get<1>(cell) + y, std::get<2>(cell) + z});
                        if (found == cells.end())
                            continue;
                        for (const auto candidate : found->second)
                            if (distance_squared_vec3(point, nodes[candidate].point) <= tolerance * tolerance) {
                                selected = candidate;
                                break;
                            }
                    }
            if (selected == nodes.size()) {
                cells[cell].push_back(selected);
                nodes.push_back(Node{});
                nodes.back().point = point;
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
            const auto part_layer = layer.find(item.first);
            const Vec3 point = add_vec3(residual.at(item.first)[vertex],
                                        part_layer == layer.end() ? Vec3{} : part_layer->second[vertex]);
            const auto cell = mesh_editor_refit_cell(point, tolerance);
            for (int x = -1; x <= 1; ++x)
                for (int y = -1; y <= 1; ++y)
                    for (int z = -1; z <= 1; ++z) {
                        const auto found =
                            cells.find({std::get<0>(cell) + x, std::get<1>(cell) + y, std::get<2>(cell) + z});
                        if (found == cells.end())
                            continue;
                        for (const auto i : found->second)
                            if (distance_squared_vec3(point, nodes[i].point) <= tolerance * tolerance)
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
    std::map<std::tuple<int, int, int>, std::vector<std::size_t>> body_edges;
    for (std::size_t i = 0; i < body.triangles.size(); ++i) {
        const auto &triangle = body.triangles[i];
        triangle_ids[key_for(triangle.driver_submesh_index, triangle.driver_vertices)] = i;
        for (int corner = 0; corner < 3; ++corner) {
            const auto pair =
                std::minmax(triangle.driver_vertices[corner], triangle.driver_vertices[(corner + 1) % 3]);
            body_edges[{triangle.driver_submesh_index, pair.first, pair.second}].push_back(i);
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
    std::map<int, std::vector<Vec3>> garment_positions;
    for (const auto &item : garments)
        garment_positions[item.first] = item.second.vertices;
    std::vector<std::size_t> visited(body.triangles.size(), 0);
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
        const Vec3 seed_normal = refit_binding_face_normal_native(seed, driver_visible);
        const double reach =
            std::max(refit.driver_diagonal * 0.015, std::min(refit.driver_diagonal * 0.06, seed.distance * 1.5));
        double best = std::numeric_limits<double>::infinity();
        Vec3 target_point{}, target_normal{};
        // Walk only edge-connected triangles from the retained bind. No global
        // reprojection can jump from an arm to the torso during the solve.
        std::vector<std::pair<std::size_t, double>> pending{{seed_id->second, 0.0}};
        visited[seed_id->second] = i + 1;
        for (std::size_t cursor = 0; cursor < pending.size(); ++cursor) {
            const auto id = pending[cursor].first;
            const auto &triangle = body.triangles[id];
            if (!allowed(triangle))
                continue;
            const Vec3 normal =
                refit_face_normal_native(triangle.corners[0], triangle.corners[1], triangle.corners[2]);
            const auto closest = closest_triangle_point_native(node.point, triangle.corners[0],
                                                               triangle.corners[1], triangle.corners[2]);
            // Garments can contain folded backs and double-sided trim. Their
            // face winding is not a reliable outward-body classifier. Keep the
            // body's local orientation instead of rejecting those constructions.
            if (dot_vec3(normal, normal) > 0.5 && dot_vec3(normal, seed_normal) > 0.15) {
                if (closest.distance_squared < best) {
                    best = closest.distance_squared;
                    target_point = Vec3{};
                    for (int corner = 0; corner < 3; ++corner)
                        target_point = add_vec3(target_point,
                                                scale_vec3(triangle.corners[corner], closest.barycentric[corner]));
                    target_normal = normal;
                }
            }
            for (const auto next : adjacent[id]) {
                if (visited[next] == i + 1)
                    continue;
                const double distance = pending[cursor].second +
                                        length_vec3(sub_vec3(body.triangles[next].centroid, triangle.centroid));
                if (distance > reach || pending.size() >= 512)
                    continue;
                visited[next] = i + 1;
                pending.emplace_back(next, distance);
            }
        }
        if (!std::isfinite(best) || std::sqrt(best) > refit.driver_diagonal * 0.35)
            continue;
        reliable[i] = true;
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
                if (hit.driver_submesh_index == vertex.first)
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
    const auto multiply = [&](const std::vector<Vec3> &values) {
        std::vector<Vec3> result(nodes.size());
        for (std::size_t i = 0; i < nodes.size(); ++i)
            result[i] = scale_vec3(values[i], diagonal[i]);
        for (const auto &edge : edges)
            if (nodes[edge.a].mobility > 0.0 && nodes[edge.b].mobility > 0.0) {
                result[edge.a] = sub_vec3(result[edge.a], scale_vec3(values[edge.b], lambda * edge.weight));
                result[edge.b] = sub_vec3(result[edge.b], scale_vec3(values[edge.a], lambda * edge.weight));
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
    // A displacement solve is linear, but triangle orientation is not. Limit
    // locally unsafe steps, spreading the limit through adjacent cloth so tiny
    // folded details cannot turn over or create a spike in the broad fit.
    std::vector<double> step(nodes.size(), 1.0);
    const auto candidate = [&](std::size_t i, double scale) {
        return add_vec3(nodes[i].point, scale_vec3(displacement[i], scale));
    };
    for (int pass = 0; pass < 32; ++pass) {
        bool changed = false;
        for (const auto &item : garments)
            for (const auto &face : item.second.faces) {
                const auto &map = indices.at(item.first);
                const std::array<std::size_t, 3> v{map[face[0]], map[face[1]], map[face[2]]};
                const auto normal =
                    refit_face_normal_native(nodes[v[0]].point, nodes[v[1]].point, nodes[v[2]].point);
                if (dot_vec3(normal, normal) < 0.5)
                    continue;
                const auto safe = [&](double scale) {
                    std::array<Vec3, 3> p{candidate(v[0], step[v[0]] * scale), candidate(v[1], step[v[1]] * scale),
                                          candidate(v[2], step[v[2]] * scale)};
                    if (dot_vec3(normal, refit_face_normal_native(p[0], p[1], p[2])) < 0.1)
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
                    step[i] *= low * 0.95;
                changed = true;
            }
        if (!changed)
            break;
        auto limited = step;
        for (const auto &edge : edges) {
            // Limit changes over physical distance rather than edge count.
            const double transition = length_vec3(sub_vec3(nodes[edge.a].point, nodes[edge.b].point)) /
                                      std::max(smoothing_length, tolerance);
            limited[edge.a] = std::min(limited[edge.a], step[edge.b] + transition);
            limited[edge.b] = std::min(limited[edge.b], step[edge.a] + transition);
        }
        step = std::move(limited);
    }
    for (std::size_t i = 0; i < nodes.size(); ++i)
        for (const auto &vertex : nodes[i].vertices) {
            const Vec3 point = candidate(i, step[i] * nodes[i].tightness);
            layer.at(vertex.first)[vertex.second] = sub_vec3(point, residual.at(vertex.first)[vertex.second]);
        }
}

void mesh_editor_validate_conformed_refit(const MeshRefitRuntime &refit,
                                          const std::map<int, MeshSessionSubmesh> &submeshes,
                                          const std::map<int, std::vector<Vec3>> &residual,
                                          const std::map<int, std::vector<Vec3>> &before,
                                          const std::map<int, std::vector<Vec3>> &after, const char *stage) {
    const double tolerance = std::max(1.0e-6, refit.driver_diagonal * 1.0e-7);
    struct Seam {
        Vec3 before, after;
    };
    std::map<std::tuple<long long, long long, long long>, std::vector<Seam>> seams;
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
            const Vec3 a = add_vec3(residual.at(part)[vertex], before.at(part)[vertex]);
            const Vec3 b = add_vec3(residual.at(part)[vertex], after.at(part)[vertex]);
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
                if (a > 1.0e-16 && (b < a * 1.0e-6 || b > a * 9.0))
                    fail("edge ratio", std::sqrt(b / a));
            }
            ++face_index;
        }
    }
}
