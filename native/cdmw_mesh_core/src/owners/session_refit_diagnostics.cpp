// Optional read-only inspection of the published mesh. This owner does not
// recompose a fit, publish geometry, or modify the morph/history revisions.
namespace {
constexpr std::size_t REFIT_DIAGNOSTIC_MAX_PARTS = 128;
constexpr std::size_t REFIT_DIAGNOSTIC_MAX_VERTICES = 200000;
constexpr std::size_t REFIT_DIAGNOSTIC_MAX_TRIANGLES = 250000;
constexpr std::size_t REFIT_DIAGNOSTIC_MAX_SURFACES = 256;
constexpr long long REFIT_DIAGNOSTIC_MAX_TRIANGLE_TESTS = 2000000;
constexpr std::size_t REFIT_DIAGNOSTIC_MAX_QUERIES = 32768;
constexpr std::size_t REFIT_DIAGNOSTIC_MAX_NODE_VISITS = 8000000;
constexpr double REFIT_DIAGNOSTIC_MAX_MS = 2000.0;

struct RefitDiagnosticBudget {
    std::chrono::steady_clock::time_point started = std::chrono::steady_clock::now();
    long long triangle_tests = 0;
    std::size_t queries = 0, node_visits = 0;
    bool stopped = false;

    double elapsed_ms() const {
        return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
    }
    bool ready() {
        if (stopped || triangle_tests >= REFIT_DIAGNOSTIC_MAX_TRIANGLE_TESTS
            || queries >= REFIT_DIAGNOSTIC_MAX_QUERIES
            || node_visits >= REFIT_DIAGNOSTIC_MAX_NODE_VISITS
            || elapsed_ms() >= REFIT_DIAGNOSTIC_MAX_MS) stopped = true;
        return !stopped;
    }
};

// A stopped nearest-surface search is discarded. A partial BVH traversal must
// never report an overestimated distance as a completed clearance measurement.
bool refit_diagnostic_query_node(
    const RefitSpatialIndexNative& index, int node_index, const Vec3& point,
    ClosestTrianglePointNative& closest, std::size_t& closest_order,
    MeshRefitVertexBindingRuntime& binding, RefitDiagnosticBudget& budget
) {
    if (budget.stopped) return false;
    if (++budget.node_visits >= REFIT_DIAGNOSTIC_MAX_NODE_VISITS
        || (budget.node_visits % 128 == 0 && budget.elapsed_ms() >= REFIT_DIAGNOSTIC_MAX_MS)) {
        budget.stopped = true;
        return false;
    }
    const auto& node = index.nodes[static_cast<std::size_t>(node_index)];
    if (refit_aabb_distance_squared_native(point, node.minimum, node.maximum) > closest.distance_squared) return true;
    if (node.left < 0 || node.right < 0) {
        for (std::size_t position = node.begin; position < node.end; ++position) {
            if (budget.triangle_tests >= REFIT_DIAGNOSTIC_MAX_TRIANGLE_TESTS) {
                budget.stopped = true;
                return false;
            }
            const auto& triangle = index.triangles[index.triangle_order[position]];
            ++budget.triangle_tests;
            const auto candidate = closest_triangle_point_native(point,
                triangle.corners[0], triangle.corners[1], triangle.corners[2]);
            if (candidate.distance_squared < closest.distance_squared
                || (candidate.distance_squared == closest.distance_squared && triangle.source_order < closest_order)) {
                closest = candidate;
                closest_order = triangle.source_order;
                binding.driver_submesh_index = triangle.driver_submesh_index;
                binding.driver_vertices = triangle.driver_vertices;
                binding.barycentric = candidate.barycentric;
            }
        }
        return true;
    }
    const auto& left = index.nodes[static_cast<std::size_t>(node.left)];
    const auto& right = index.nodes[static_cast<std::size_t>(node.right)];
    const bool left_first = refit_aabb_distance_squared_native(point, left.minimum, left.maximum)
        <= refit_aabb_distance_squared_native(point, right.minimum, right.maximum);
    return refit_diagnostic_query_node(index, left_first ? node.left : node.right, point,
            closest, closest_order, binding, budget)
        && refit_diagnostic_query_node(index, left_first ? node.right : node.left, point,
            closest, closest_order, binding, budget);
}

bool refit_diagnostic_nearest(const Vec3& point, const RefitSpatialIndexNative& index,
    MeshRefitVertexBindingRuntime& binding, RefitDiagnosticBudget& budget) {
    if (index.root < 0 || !budget.ready()) return false;
    ++budget.queries;
    ClosestTrianglePointNative closest;
    std::size_t order = std::numeric_limits<std::size_t>::max();
    if (!refit_diagnostic_query_node(index, index.root, point, closest, order, binding, budget)
        || binding.driver_submesh_index < 0 || !std::isfinite(closest.distance_squared)) return false;
    binding.distance = std::sqrt(std::max(0.0, closest.distance_squared));
    return true;
}

struct RefitDiagnosticSample {
    int part = -1;
    std::size_t ordinal = 0;
    std::array<int, 3> vertices{};
    Vec3 weights{1.0, 0.0, 0.0};
    const char* kind = "vertex";
    Vec3 position{}, reference{};
};

Vec3 refit_diagnostic_point(const std::vector<Vec3>& vertices,
    const std::array<int, 3>& indices, const Vec3& weights) {
    Vec3 result{};
    for (int c = 0; c < 3; ++c) result = add_vec3(result,
        scale_vec3(vertices[static_cast<std::size_t>(indices[c])], weights[c]));
    return result;
}

void refit_diagnostic_number(std::ostream& out, double value) {
    if (std::isfinite(value)) out << std::setprecision(17) << value;
    else out << "null";
}

void refit_diagnostic_vec3(std::ostream& out, const Vec3& value) {
    out << '[';
    for (int c = 0; c < 3; ++c) { if (c) out << ','; refit_diagnostic_number(out, value[c]); }
    out << ']';
}

void refit_diagnostic_sample_json(std::ostream& out, const RefitDiagnosticSample& sample) {
    out << "{\"submesh_index\":" << sample.part << ",\"kind\":";
    write_escaped(out, sample.kind);
    out << ",\"vertex_indices\":[" << sample.vertices[0] << ',' << sample.vertices[1] << ',' << sample.vertices[2]
        << "],\"weights\":";
    refit_diagnostic_vec3(out, sample.weights);
    out << ",\"position\":";
    refit_diagnostic_vec3(out, sample.position);
    out << '}';
}

void refit_diagnostic_identity(std::ostream& out, const std::string& session_id, const MeshEditorSession& session) {
    out << "{\"schema\":\"cdmw.refit_diagnostics.v1\",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"state_revision\":" << (session.morph ? session.morph->state_revision : 0)
        << ",\"edit_revision\":" << session.edit_revision
        << ",\"units\":\"mesh coordinates\",\"sampling\":\"vertices, triangle centers and edge midpoints\""
        << ",\"global_collision_proof\":false,\"limits\":{\"parts\":" << REFIT_DIAGNOSTIC_MAX_PARTS
        << ",\"vertices\":" << REFIT_DIAGNOSTIC_MAX_VERTICES << ",\"triangles\":" << REFIT_DIAGNOSTIC_MAX_TRIANGLES
        << ",\"surfaces\":" << REFIT_DIAGNOSTIC_MAX_SURFACES << ",\"triangle_tests\":" << REFIT_DIAGNOSTIC_MAX_TRIANGLE_TESTS
        << ",\"queries\":" << REFIT_DIAGNOSTIC_MAX_QUERIES
        << ",\"part_summaries\":" << REFIT_DIAGNOSTIC_MAX_PARTS
        << ",\"cooperative_analysis_ms\":" << REFIT_DIAGNOSTIC_MAX_MS << '}';
}

std::string refit_diagnostic_unavailable(const std::string& session_id, const MeshEditorSession& session,
    const std::string& reason) {
    std::ostringstream out;
    refit_diagnostic_identity(out, session_id, session);
    out << ",\"available\":false,\"status\":\"unavailable\",\"reason\":";
    write_escaped(out, reason);
    out << ",\"body_clearance\":{\"available\":false},\"layer_spacing\":{\"available\":false},\"parts\":[]}";
    return out.str();
}

struct RefitDiagnosticPart {
    std::size_t candidate_samples = 0, planned_samples = 0, measured_samples = 0;
    double minimum_distance = std::numeric_limits<double>::infinity();
    double minimum_normal_offset = std::numeric_limits<double>::infinity();
    RefitDiagnosticSample distance_sample, normal_sample;
};

struct RefitDiagnosticLayer {
    RefitDiagnosticSample sample;
    MeshRefitVertexBindingRuntime target;
    Vec3 target_position{};
    double reference_gap = 0.0, current_gap = 0.0, retained_ratio = 0.0;
};
} // namespace

std::string mesh_editor_refit_diagnostics_json(const JsonValue& root,
    const std::string& session_id, const MeshEditorSession& session) {
    if (!session.morph || !session.morph->refit)
        return refit_diagnostic_unavailable(session_id, session, "Bind garments before analyzing the current fit.");
    const auto& morph = *session.morph;
    const auto& refit = *morph.refit;
    const auto& submeshes = mesh_editor_submeshes(session);
    int sample_limit = 2048, detail_limit = 24;
    for (const auto& setting : {std::make_pair("diagnostic_sample_limit", &sample_limit),
                               std::make_pair("diagnostic_detail_limit", &detail_limit)}) {
        if (root.get(setting.first) && !strict_int_or(root.get(setting.first), *setting.second))
            throw std::runtime_error("refit diagnostic limits must be integers");
    }
    if (sample_limit < 1 || sample_limit > 4096 || detail_limit < 1 || detail_limit > 64)
        throw std::runtime_error("refit diagnostics allow 1..4096 samples and 1..64 details");
    const auto* requested = root.get("submesh_indices");
    if (!requested || requested->type != JsonValue::Type::Array || requested->array_value.empty()
        || requested->array_value.size() > REFIT_DIAGNOSTIC_MAX_PARTS)
        throw std::runtime_error("refit diagnostics require 1..128 explicit garment Part indices");
    std::set<int> selected;
    for (const auto& value : requested->array_value) {
        int index = -1;
        if (!strict_int_or(&value, index) || !refit.garment_submesh_indices.count(index)
            || !selected.insert(index).second)
            throw std::runtime_error("refit diagnostics contain an invalid, unbound or duplicate garment Part");
    }
    if (selected.size() > static_cast<std::size_t>(sample_limit))
        throw std::runtime_error("refit diagnostic sample limit must cover every requested Part");
    std::set<int> needed = refit.driver_submesh_indices;
    needed.insert(refit.garment_submesh_indices.begin(), refit.garment_submesh_indices.end());
    if (needed.size() > REFIT_DIAGNOSTIC_MAX_PARTS)
        return refit_diagnostic_unavailable(session_id, session, "The bound fit exceeds the 128 Part analysis limit.");
    std::size_t vertex_count = 0, face_count = 0;
    for (const int index : needed) {
        const auto found = submeshes.find(index);
        if (found == submeshes.end())
            return refit_diagnostic_unavailable(session_id, session, "The bound fit topology is no longer available.");
        vertex_count += found->second.vertices.size();
        face_count += found->second.faces.size();
        if (vertex_count > REFIT_DIAGNOSTIC_MAX_VERTICES || face_count > REFIT_DIAGNOSTIC_MAX_TRIANGLES)
            return refit_diagnostic_unavailable(session_id, session,
                "The bound fit exceeds the analysis limit of 200000 vertices or 250000 triangles.");
    }
    RefitDiagnosticBudget budget;
    for (const int index : needed) {
        const auto& mesh = submeshes.at(index);
        for (const auto& point : mesh.vertices) for (const double value : point)
            if (!std::isfinite(value)) return refit_diagnostic_unavailable(session_id, session, "The current fit contains non-finite positions.");
        for (const auto& face : mesh.faces) for (const int vertex : face)
            if (vertex < 0 || static_cast<std::size_t>(vertex) >= mesh.vertices.size())
                return refit_diagnostic_unavailable(session_id, session, "The current fit contains invalid triangle indices.");
    }
    const auto body_index = build_refit_spatial_index_native(submeshes, refit.driver_submesh_indices);
    if (body_index.root < 0)
        return refit_diagnostic_unavailable(session_id, session, "The bound body has no usable triangles.");
    std::map<int, RefitDiagnosticPart> parts;
    std::vector<RefitDiagnosticSample> samples;
    std::size_t remaining = static_cast<std::size_t>(sample_limit), parts_left = selected.size(), candidate_samples = 0;
    for (const int index : selected) {
        const auto& mesh = submeshes.at(index);
        auto& part = parts[index];
        part.candidate_samples = mesh.vertices.size() + 4 * mesh.faces.size();
        candidate_samples += part.candidate_samples;
        part.planned_samples = std::min(part.candidate_samples, remaining / parts_left);
        remaining -= part.planned_samples;
        --parts_left;
        for (std::size_t ordinal = 0; ordinal < part.planned_samples; ++ordinal) {
            const std::size_t candidate = ordinal * part.candidate_samples / part.planned_samples;
            RefitDiagnosticSample sample;
            sample.part = index;
            sample.ordinal = candidate;
            if (candidate < mesh.vertices.size()) {
                sample.vertices.fill(static_cast<int>(candidate));
            } else {
                const std::size_t face_sample = candidate - mesh.vertices.size();
                sample.vertices = mesh.faces[face_sample / 4];
                const std::size_t slot = face_sample % 4;
                if (slot == 0) {
                    sample.kind = "triangle_center";
                    sample.weights = {1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0};
                } else {
                    sample.kind = "edge_midpoint";
                    sample.weights = {};
                    sample.weights[slot - 1] = 0.5;
                    sample.weights[slot % 3] = 0.5;
                }
            }
            sample.position = refit_diagnostic_point(mesh.vertices, sample.vertices, sample.weights);
            samples.push_back(sample);
        }
    }
    std::map<int, std::vector<Vec3>> body_positions;
    for (const int index : refit.driver_submesh_indices) body_positions[index] = submeshes.at(index).vertices;
    std::size_t body_samples = 0;
    double minimum_distance = std::numeric_limits<double>::infinity();
    double minimum_normal_offset = std::numeric_limits<double>::infinity();
    for (const auto& sample : samples) {
        MeshRefitVertexBindingRuntime nearest;
        if (!refit_diagnostic_nearest(sample.position, body_index, nearest, budget)) {
            if (budget.stopped) break;
            continue;
        }
        ++body_samples;
        auto& part = parts.at(sample.part);
        ++part.measured_samples;
        minimum_distance = std::min(minimum_distance, nearest.distance);
        if (nearest.distance < part.minimum_distance) {
            part.minimum_distance = nearest.distance;
            part.distance_sample = sample;
        }
        const Vec3 normal = refit_binding_face_normal_native(nearest, body_positions);
        if (length_vec3(normal) > 1.0e-12) {
            const double offset = dot_vec3(sub_vec3(sample.position,
                mesh_editor_refit_driver_point(nearest, body_positions)), normal);
            minimum_normal_offset = std::min(minimum_normal_offset, offset);
            if (offset < part.minimum_normal_offset) {
                part.minimum_normal_offset = offset;
                part.normal_sample = sample;
            }
        }
    }

    std::vector<RefitDiagnosticLayer> layer_details;
    std::size_t layer_samples = 0, recognized_layers = 0, ambiguous_layers = 0;
    double minimum_current_gap = std::numeric_limits<double>::infinity();
    double minimum_retained_ratio = std::numeric_limits<double>::infinity();
    std::string layer_reason;
    if (budget.ready()) {
        // Reconstruct neutral reference coordinates without running the fitter.
        // Original source IDs are retained in every sample and search triangle.
        const auto reference = mesh_editor_morph_residual_positions(morph, submeshes, needed);
        bool finite = true;
        for (const auto& part : reference) for (const auto& point : part.second)
            for (const double value : point) finite = finite && std::isfinite(value);
        if (!finite) layer_reason = "The neutral reference contains non-finite positions.";
        else {
            std::map<int, MeshSessionSubmesh> garments, reference_body;
            // Match the fitter's seam identity without snapping the coordinates
            // used by geometric measurements or changing their source IDs.
            const auto seam_positions = mesh_editor_refit_seam_positions(refit, submeshes, reference);
            std::map<Vec3, std::size_t> cohorts;
            std::vector<Vec3> cohort_positions;
            std::map<int, std::vector<std::size_t>> indices;
            for (const int index : refit.garment_submesh_indices) {
                garments[index].vertices = reference.at(index);
                garments[index].faces = submeshes.at(index).faces;
                for (std::size_t vertex = 0; vertex < reference.at(index).size(); ++vertex) {
                    const auto entry = cohorts.emplace(seam_positions.at(index)[vertex], cohorts.size());
                    if (entry.second) cohort_positions.push_back(reference.at(index)[vertex]);
                    indices[index].push_back(entry.first->second);
                }
            }
            const auto roots = mesh_editor_refit_surface_roots(garments, indices, cohorts.size());
            std::set<std::pair<int, std::size_t>> surfaces;
            for (const auto& part : garments) for (const auto& face : part.second.faces)
                surfaces.insert({part.first, roots[indices.at(part.first)[face[0]]]});
            if (surfaces.size() > REFIT_DIAGNOSTIC_MAX_SURFACES)
                layer_reason = "Layer analysis exceeds the 256 surface-island limit.";
            else if (budget.ready()) {
                const auto surface_indices = mesh_editor_refit_surface_indices(garments, indices, roots);
                for (const int index : refit.driver_submesh_indices) {
                    reference_body[index].vertices = reference.at(index);
                    reference_body[index].faces = submeshes.at(index).faces;
                }
                const auto reference_body_index = build_refit_spatial_index_native(reference_body, refit.driver_submesh_indices);
                const double tolerance = std::max(1.0e-6, refit.driver_diagonal * 1.0e-7);
                // Nearly coincident skins have no reliable separated layer order.
                // Recognized sewn borders already share the fitter's cohorts.
                const double order_epsilon = std::max(tolerance * 4.0, refit.driver_diagonal * 1.0e-5);
                std::vector<std::set<std::size_t>> neighbors(cohorts.size());
                for (const auto& part : garments) for (const auto& face : part.second.faces)
                    for (int c = 0; c < 3; ++c) {
                        const auto a = indices.at(part.first)[face[c]], b = indices.at(part.first)[face[(c + 1) % 3]];
                        if (a != b) { neighbors[a].insert(b); neighbors[b].insert(a); }
                    }
                for (auto sample : samples) {
                    if (!budget.ready()) break;
                    sample.reference = refit_diagnostic_point(reference.at(sample.part), sample.vertices, sample.weights);
                    MeshRefitVertexBindingRuntime source_body;
                    if (!refit_diagnostic_nearest(sample.reference, reference_body_index, source_body, budget)) continue;
                    const auto source_root = roots[indices.at(sample.part)[sample.vertices[0]]];
                    for (const auto& target : surface_indices) {
                        if (!budget.ready()) break;
                        if (target.first.second == source_root) continue;
                        const auto& bounds = target.second.nodes[target.second.root];
                        if (refit_aabb_distance_squared_native(sample.reference, bounds.minimum, bounds.maximum)
                            > std::pow(refit.driver_diagonal * 0.03, 2.0)) continue;
                        MeshRefitVertexBindingRuntime nearest;
                        if (!refit_diagnostic_nearest(sample.reference, target.second, nearest, budget)) continue;
                        if (nearest.distance > refit.driver_diagonal * 0.03) continue;
                        const Vec3 target_reference = mesh_editor_refit_driver_point(nearest, reference);
                        const Vec3 normal = refit_binding_face_normal_native(nearest, reference);
                        const Vec3 offset = sub_vec3(sample.reference, target_reference);
                        const double height = dot_vec3(offset, normal);
                        if (std::abs(height) <= order_epsilon || std::abs(height) < nearest.distance * 0.15
                            || length_vec3(sub_vec3(offset, scale_vec3(normal, height))) > tolerance * 4.0) {
                            ++ambiguous_layers;
                            continue;
                        }
                        bool ambiguous = false;
                        // Reject a sample whose immediate authored neighbors
                        // change sides against the same local facing surface.
                        std::set<std::size_t> checked;
                        for (int c = 0; c < 3 && !ambiguous; ++c) {
                            if (sample.weights[c] <= 0.0) continue;
                            for (const auto neighbor : neighbors[indices.at(sample.part)[sample.vertices[c]]]) {
                                if (!checked.insert(neighbor).second) continue;
                                MeshRefitVertexBindingRuntime nearby;
                                if (!refit_diagnostic_nearest(cohort_positions[neighbor], target.second, nearby, budget)) {
                                    ambiguous = true;
                                    break;
                                }
                                const Vec3 nearby_normal = refit_binding_face_normal_native(nearby, reference);
                                const double side = dot_vec3(sub_vec3(cohort_positions[neighbor],
                                    mesh_editor_refit_driver_point(nearby, reference)), nearby_normal);
                                if (height * side < -tolerance * tolerance && dot_vec3(normal, nearby_normal) > 0.5) {
                                    ambiguous = true;
                                    break;
                                }
                            }
                        }
                        if (ambiguous || budget.stopped) { ++ambiguous_layers; continue; }
                        MeshRefitVertexBindingRuntime target_body;
                        if (!refit_diagnostic_nearest(target_reference, reference_body_index, target_body, budget)) continue;
                        const double region_radius = std::max(nearest.distance * 2.0, refit.driver_diagonal * 0.05);
                        if (dot_vec3(refit_binding_face_normal_native(source_body, reference),
                                refit_binding_face_normal_native(target_body, reference)) < 0.5
                            || distance_squared_vec3(mesh_editor_refit_driver_point(source_body, reference),
                                mesh_editor_refit_driver_point(target_body, reference)) > region_radius * region_radius) {
                            ++ambiguous_layers;
                            continue;
                        }
                        const auto& current_target = submeshes.at(nearest.driver_submesh_index).vertices;
                        const Vec3 target_position = refit_diagnostic_point(current_target, nearest.driver_vertices, nearest.barycentric);
                        const Vec3 current_normal = refit_face_normal_native(current_target[nearest.driver_vertices[0]],
                            current_target[nearest.driver_vertices[1]], current_target[nearest.driver_vertices[2]]);
                        if (length_vec3(current_normal) <= 1.0e-12) { ++ambiguous_layers; continue; }
                        const double gap = dot_vec3(sub_vec3(sample.position, target_position), current_normal)
                            * (height < 0.0 ? -1.0 : 1.0);
                        const double ratio = gap / std::abs(height);
                        if (!std::isfinite(gap) || !std::isfinite(ratio)) { ++ambiguous_layers; continue; }
                        ++recognized_layers;
                        minimum_current_gap = std::min(minimum_current_gap, gap);
                        minimum_retained_ratio = std::min(minimum_retained_ratio, ratio);
                        layer_details.push_back({sample, nearest, target_position, std::abs(height), gap, ratio});
                        std::stable_sort(layer_details.begin(), layer_details.end(), [](const auto& a, const auto& b) {
                            return a.retained_ratio < b.retained_ratio;
                        });
                        if (layer_details.size() > static_cast<std::size_t>(detail_limit)) layer_details.pop_back();
                    }
                    if (!budget.stopped) ++layer_samples;
                }
            }
        }
    }
    if (budget.stopped) layer_reason = "The analysis work limit was reached; unfinished samples were not reported as measured.";
    else if (!recognized_layers && layer_reason.empty())
        layer_reason = "No unambiguous separated layer correspondence was found in the sampled neutral geometry.";

    std::ostringstream out;
    refit_diagnostic_identity(out, session_id, session);
    out << ",\"available\":" << (body_samples ? "true" : "false") << ",\"status\":";
    write_escaped(out, body_samples ? (budget.stopped ? "partial" : "ok") : "unavailable");
    out << ",\"reason\":";
    write_escaped(out, budget.stopped ? "The bounded analysis stopped before all planned work completed." : "");
    out << ",\"sample_limit\":" << sample_limit << ",\"detail_limit\":" << detail_limit
        << ",\"detail_limit_scope\":\"layer_spacing.details\""
        << ",\"candidate_sample_count\":" << candidate_samples << ",\"planned_sample_count\":" << samples.size()
        << ",\"sampled\":" << (samples.size() < candidate_samples ? "true" : "false")
        << ",\"body_triangle_count\":" << body_index.triangles.size() << ",\"input_vertex_count\":" << vertex_count
        << ",\"input_triangle_count\":" << face_count << ",\"triangle_tests\":" << budget.triangle_tests
        << ",\"queries\":" << budget.queries << ",\"elapsed_ms\":";
    refit_diagnostic_number(out, budget.elapsed_ms());
    out << ",\"body_clearance\":{\"available\":" << (body_samples ? "true" : "false")
        << ",\"evaluated_sample_count\":" << body_samples << ",\"minimum_distance\":";
    refit_diagnostic_number(out, minimum_distance);
    out << ",\"minimum_normal_offset\":";
    refit_diagnostic_number(out, minimum_normal_offset);
    out << ",\"normal_offset_method\":\"nearest face normal; local orientation only, not an inside-body test\"}"
        << ",\"layer_spacing\":{\"available\":" << (recognized_layers ? "true" : "false")
        << ",\"reference\":\"neutral authored geometry\",\"reason\":";
    write_escaped(out, layer_reason);
    out << ",\"evaluated_sample_count\":" << layer_samples << ",\"recognized_correspondence_count\":" << recognized_layers
        << ",\"ambiguous_candidate_count\":" << ambiguous_layers << ",\"minimum_current_gap\":";
    refit_diagnostic_number(out, minimum_current_gap);
    out << ",\"minimum_retained_ratio\":";
    refit_diagnostic_number(out, minimum_retained_ratio);
    out << ",\"details_truncated\":" << (recognized_layers > layer_details.size() ? "true" : "false") << ",\"details\":[";
    for (std::size_t i = 0; i < layer_details.size(); ++i) {
        if (i) out << ',';
        const auto& detail = layer_details[i];
        out << "{\"sample\":";
        refit_diagnostic_sample_json(out, detail.sample);
        out << ",\"target_submesh_index\":" << detail.target.driver_submesh_index
            << ",\"target_vertex_indices\":[" << detail.target.driver_vertices[0] << ',' << detail.target.driver_vertices[1]
            << ',' << detail.target.driver_vertices[2] << "],\"target_weights\":";
        refit_diagnostic_vec3(out, detail.target.barycentric);
        out << ",\"target_position\":";
        refit_diagnostic_vec3(out, detail.target_position);
        out << ",\"reference_gap\":"; refit_diagnostic_number(out, detail.reference_gap);
        out << ",\"current_gap\":"; refit_diagnostic_number(out, detail.current_gap);
        out << ",\"retained_ratio\":"; refit_diagnostic_number(out, detail.retained_ratio);
        out << '}';
    }
    out << "]},\"parts\":[";
    bool wrote = false;
    for (const auto& item : parts) {
        if (wrote) out << ',';
        wrote = true;
        const auto& part = item.second;
        const auto configured = refit.garment_settings.find(item.first);
        const MeshRefitGarmentSettingsRuntime settings = configured == refit.garment_settings.end()
            ? MeshRefitGarmentSettingsRuntime{} : configured->second;
        out << "{\"submesh_index\":" << item.first << ",\"candidate_sample_count\":" << part.candidate_samples
            << ",\"planned_sample_count\":" << part.planned_samples << ",\"evaluated_sample_count\":" << part.measured_samples
            << ",\"enabled\":" << (settings.enabled ? "true" : "false") << ",\"mode\":";
        write_escaped(out, settings.mode);
        out << ",\"has_influence_mask\":" << (refit.vertex_masks.count(item.first) ? "true" : "false")
            << ",\"has_driver_region\":" << (refit.garment_regions.count(item.first) ? "true" : "false")
            << ",\"requested_clearance\":";
        refit_diagnostic_number(out, refit.driver_diagonal * settings.clearance_percent / 100.0);
        out << ",\"minimum_distance\":"; refit_diagnostic_number(out, part.minimum_distance);
        out << ",\"minimum_normal_offset\":"; refit_diagnostic_number(out, part.minimum_normal_offset);
        if (std::isfinite(part.minimum_distance)) {
            out << ",\"minimum_distance_sample\":";
            refit_diagnostic_sample_json(out, part.distance_sample);
        }
        if (std::isfinite(part.minimum_normal_offset)) {
            out << ",\"minimum_normal_offset_sample\":";
            refit_diagnostic_sample_json(out, part.normal_sample);
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}
