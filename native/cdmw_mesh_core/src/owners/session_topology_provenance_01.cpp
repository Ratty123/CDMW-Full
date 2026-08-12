// Original-relative topology provenance for the resident editor session.
//
// A topology edit renumbers vertices and triangles, so the same-count source
// maps stop describing the result. What replaces them is a compressed sparse row
// table: one parent list per output vertex, weights that sum to 1, and one
// original face index per output triangle. Parents are always indices in the
// original LOD0 submesh, never in the intermediate edit that produced them, so
// a chain of edits stays one level deep.
//
// Composition runs before any mutation. A result that cannot be composed leaves
// geometry, provenance, history, and revisions untouched.

constexpr const char* MESH_TOPOLOGY_PROVENANCE_VERSION = "cdmw_mesh_topology_provenance_v1";
constexpr const char* MESH_TOPOLOGY_PROVENANCE_CAPABILITY = "topology_provenance_v1";

constexpr const char* MESH_TOPOLOGY_BLOCKER_PROVENANCE_REQUIRED = "TOPOLOGY_PROVENANCE_REQUIRED";
constexpr const char* MESH_TOPOLOGY_BLOCKER_CONTRACT_UNSUPPORTED = "TOPOLOGY_CONTRACT_UNSUPPORTED";
constexpr const char* MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID = "TOPOLOGY_VERTEX_ORIGIN_INVALID";
constexpr const char* MESH_TOPOLOGY_BLOCKER_FACE_ORIGIN_INVALID = "TOPOLOGY_FACE_ORIGIN_INVALID";
constexpr const char* MESH_TOPOLOGY_BLOCKER_OPERATION_NOT_REBUILDABLE = "TOPOLOGY_OPERATION_NOT_REBUILDABLE";
constexpr const char* MESH_TOPOLOGY_BLOCKER_EMPTY_SUBMESH = "TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED";

// The normalized weight sum has to land here exactly, not "close enough".
constexpr double MESH_TOPOLOGY_WEIGHT_SUM_TOLERANCE = 1e-12;

bool mesh_editor_is_rebuildable_topology_action(const std::string& action) {
    return action == "delete" || action == "loop_cut" || action == "subdivide";
}

// Kahan-compensated sum. The Python owner normalizes with math.fsum, and a naive
// accumulation here would disagree with it on the exactness check below.
double mesh_editor_compensated_sum(const std::vector<double>& values) {
    double total = 0.0;
    double compensation = 0.0;
    for (const double value : values) {
        const double adjusted = value - compensation;
        const double next = total + adjusted;
        compensation = (next - total) - adjusted;
        total = next;
    }
    return total;
}

void mesh_editor_clear_topology_provenance(MeshSessionSubmesh& submesh, const char* blocker) {
    submesh.vertex_origin_offsets.clear();
    submesh.vertex_origin_parents.clear();
    submesh.vertex_origin_weights.clear();
    submesh.topology_rebuild_valid = false;
    submesh.topology_blocker = blocker == nullptr ? std::string() : std::string(blocker);
}

void mesh_editor_initialize_identity_topology_provenance(MeshSessionSubmesh& submesh) {
    const std::size_t vertex_count = submesh.vertices.size();
    const std::size_t face_count = submesh.faces.size();
    if (vertex_count == 0 || face_count == 0) {
        submesh.topology_original_vertex_count = 0;
        submesh.topology_original_face_count = 0;
        mesh_editor_clear_topology_provenance(submesh, MESH_TOPOLOGY_BLOCKER_EMPTY_SUBMESH);
        return;
    }
    // A session opened on geometry that already claims a non-identity face
    // lineage is not the original, so it cannot anchor original-relative
    // provenance. Fail closed rather than inventing an anchor.
    if (!submesh.source_face_indices.empty()) {
        if (submesh.source_face_indices.size() != face_count) {
            submesh.topology_original_vertex_count = 0;
            submesh.topology_original_face_count = 0;
            mesh_editor_clear_topology_provenance(submesh, MESH_TOPOLOGY_BLOCKER_PROVENANCE_REQUIRED);
            return;
        }
        for (std::size_t index = 0; index < face_count; ++index) {
            if (submesh.source_face_indices[index] != static_cast<int>(index)) {
                submesh.topology_original_vertex_count = 0;
                submesh.topology_original_face_count = 0;
                mesh_editor_clear_topology_provenance(submesh, MESH_TOPOLOGY_BLOCKER_PROVENANCE_REQUIRED);
                return;
            }
        }
    }
    submesh.topology_original_vertex_count = static_cast<int>(vertex_count);
    submesh.topology_original_face_count = static_cast<int>(face_count);
    submesh.vertex_origin_offsets.resize(vertex_count + 1);
    submesh.vertex_origin_parents.resize(vertex_count);
    submesh.vertex_origin_weights.assign(vertex_count, 1.0);
    for (std::size_t index = 0; index < vertex_count; ++index) {
        submesh.vertex_origin_offsets[index] = static_cast<int>(index);
        submesh.vertex_origin_parents[index] = static_cast<int>(index);
    }
    submesh.vertex_origin_offsets[vertex_count] = static_cast<int>(vertex_count);
    submesh.topology_rebuild_valid = true;
    submesh.topology_blocker.clear();
}

bool mesh_editor_topology_provenance_shape_valid(const MeshSessionSubmesh& submesh) {
    if (!submesh.topology_rebuild_valid) {
        return false;
    }
    const std::size_t vertex_count = submesh.vertices.size();
    if (vertex_count == 0 || submesh.faces.empty()) {
        return false;
    }
    if (submesh.vertex_origin_offsets.size() != vertex_count + 1) {
        return false;
    }
    if (submesh.vertex_origin_parents.size() != submesh.vertex_origin_weights.size()) {
        return false;
    }
    if (submesh.vertex_origin_offsets.front() != 0
        || submesh.vertex_origin_offsets.back() != static_cast<int>(submesh.vertex_origin_parents.size())) {
        return false;
    }
    if (submesh.source_face_indices.size() != submesh.faces.size()) {
        return false;
    }
    for (const int source_face_index : submesh.source_face_indices) {
        if (source_face_index < 0 || source_face_index >= submesh.topology_original_face_count) {
            return false;
        }
    }
    for (std::size_t index = 0; index < vertex_count; ++index) {
        const int start = submesh.vertex_origin_offsets[index];
        const int end = submesh.vertex_origin_offsets[index + 1];
        if (start < 0 || end < start || end > static_cast<int>(submesh.vertex_origin_parents.size())) {
            return false;
        }
        if (end == start) {
            return false;
        }
        std::vector<double> row;
        row.reserve(static_cast<std::size_t>(end - start));
        int previous_parent = -1;
        for (int entry = start; entry < end; ++entry) {
            const int parent = submesh.vertex_origin_parents[static_cast<std::size_t>(entry)];
            const double weight = submesh.vertex_origin_weights[static_cast<std::size_t>(entry)];
            if (parent <= previous_parent || parent < 0 || parent >= submesh.topology_original_vertex_count) {
                return false;
            }
            if (!std::isfinite(weight) || weight <= 0.0) {
                return false;
            }
            previous_parent = parent;
            row.push_back(weight);
        }
        if (std::fabs(mesh_editor_compensated_sum(row) - 1.0) > MESH_TOPOLOGY_WEIGHT_SUM_TOLERANCE) {
            return false;
        }
    }
    return true;
}

std::size_t mesh_editor_topology_provenance_parent_entries(const MeshSessionSubmesh& submesh) {
    return submesh.vertex_origin_parents.size();
}

int mesh_editor_topology_direct_vertex_count(const MeshSessionSubmesh& submesh) {
    if (submesh.vertex_origin_offsets.size() < 2) {
        return 0;
    }
    int direct = 0;
    for (std::size_t index = 0; index + 1 < submesh.vertex_origin_offsets.size(); ++index) {
        if (submesh.vertex_origin_offsets[index + 1] - submesh.vertex_origin_offsets[index] == 1) {
            ++direct;
        }
    }
    return direct;
}

// The legacy `source_vertex_map` view: the single original index for a direct
// vertex, -1 where the vertex was derived from more than one parent.
std::vector<int> mesh_editor_topology_source_vertex_map(const MeshSessionSubmesh& submesh) {
    std::vector<int> values;
    if (submesh.vertex_origin_offsets.size() < 2) {
        return values;
    }
    values.reserve(submesh.vertex_origin_offsets.size() - 1);
    for (std::size_t index = 0; index + 1 < submesh.vertex_origin_offsets.size(); ++index) {
        const int start = submesh.vertex_origin_offsets[index];
        const int end = submesh.vertex_origin_offsets[index + 1];
        values.push_back(
            end - start == 1 && start >= 0 && start < static_cast<int>(submesh.vertex_origin_parents.size())
                ? submesh.vertex_origin_parents[static_cast<std::size_t>(start)]
                : -1
        );
    }
    return values;
}

// Fold one native result onto the previous original-relative lineage. Returns
// false with a stable blocker when the result cannot be described exactly; the
// caller then leaves the session untouched or marks the submesh non-rebuildable,
// but never guesses.
bool mesh_editor_compose_topology_provenance(
    const MeshSessionSubmesh& previous,
    const SubmeshMeshEditResult& result,
    std::vector<int>& out_offsets,
    std::vector<int>& out_parents,
    std::vector<double>& out_weights,
    std::string& out_blocker
) {
    out_offsets.clear();
    out_parents.clear();
    out_weights.clear();
    out_blocker.clear();

    if (!mesh_editor_topology_provenance_shape_valid(previous)) {
        out_blocker = MESH_TOPOLOGY_BLOCKER_PROVENANCE_REQUIRED;
        return false;
    }
    const std::size_t output_vertex_count = result.vertices.size();
    if (output_vertex_count == 0 || result.faces.empty()) {
        out_blocker = MESH_TOPOLOGY_BLOCKER_EMPTY_SUBMESH;
        return false;
    }
    if (result.copy_vertex_indices.size() != output_vertex_count) {
        out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
        return false;
    }
    if (result.source_face_indices.size() != result.faces.size()) {
        out_blocker = MESH_TOPOLOGY_BLOCKER_FACE_ORIGIN_INVALID;
        return false;
    }
    for (const int source_face_index : result.source_face_indices) {
        if (source_face_index < 0 || source_face_index >= previous.topology_original_face_count) {
            out_blocker = MESH_TOPOLOGY_BLOCKER_FACE_ORIGIN_INVALID;
            return false;
        }
    }

    const int previous_vertex_count = static_cast<int>(previous.vertices.size());
    std::map<int, std::array<double, 3>> blends;   // output index -> {left, right, factor}
    for (const VertexBlend& blend : result.vertex_blends) {
        if (blend.index < 0 || static_cast<std::size_t>(blend.index) >= output_vertex_count) {
            out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
            return false;
        }
        if (blends.find(blend.index) != blends.end()) {
            out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
            return false;
        }
        if (blend.left < 0 || blend.left >= previous_vertex_count
            || blend.right < 0 || blend.right >= previous_vertex_count) {
            out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
            return false;
        }
        if (!std::isfinite(blend.factor) || blend.factor <= 0.0 || blend.factor >= 1.0) {
            out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
            return false;
        }
        blends[blend.index] = {static_cast<double>(blend.left), static_cast<double>(blend.right), blend.factor};
    }

    out_offsets.reserve(output_vertex_count + 1);
    out_offsets.push_back(0);
    for (std::size_t output_index = 0; output_index < output_vertex_count; ++output_index) {
        const int copy_index = result.copy_vertex_indices[output_index];
        const auto blend = blends.find(static_cast<int>(output_index));
        if (copy_index >= 0) {
            if (blend != blends.end() || copy_index >= previous_vertex_count) {
                out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
                return false;
            }
            const int start = previous.vertex_origin_offsets[static_cast<std::size_t>(copy_index)];
            const int end = previous.vertex_origin_offsets[static_cast<std::size_t>(copy_index) + 1];
            for (int entry = start; entry < end; ++entry) {
                out_parents.push_back(previous.vertex_origin_parents[static_cast<std::size_t>(entry)]);
                out_weights.push_back(previous.vertex_origin_weights[static_cast<std::size_t>(entry)]);
            }
            out_offsets.push_back(static_cast<int>(out_parents.size()));
            blends.erase(static_cast<int>(output_index));
            continue;
        }
        if (blend == blends.end()) {
            out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
            return false;
        }
        const int left = static_cast<int>(blend->second[0]);
        const int right = static_cast<int>(blend->second[1]);
        const double factor = blend->second[2];
        std::map<int, std::vector<double>> merged;
        const int left_start = previous.vertex_origin_offsets[static_cast<std::size_t>(left)];
        const int left_end = previous.vertex_origin_offsets[static_cast<std::size_t>(left) + 1];
        for (int entry = left_start; entry < left_end; ++entry) {
            const double weight = previous.vertex_origin_weights[static_cast<std::size_t>(entry)] * (1.0 - factor);
            if (weight > 0.0) {
                merged[previous.vertex_origin_parents[static_cast<std::size_t>(entry)]].push_back(weight);
            }
        }
        const int right_start = previous.vertex_origin_offsets[static_cast<std::size_t>(right)];
        const int right_end = previous.vertex_origin_offsets[static_cast<std::size_t>(right) + 1];
        for (int entry = right_start; entry < right_end; ++entry) {
            const double weight = previous.vertex_origin_weights[static_cast<std::size_t>(entry)] * factor;
            if (weight > 0.0) {
                merged[previous.vertex_origin_parents[static_cast<std::size_t>(entry)]].push_back(weight);
            }
        }
        if (merged.empty()) {
            out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
            return false;
        }
        std::vector<double> totals;
        totals.reserve(merged.size());
        for (const auto& item : merged) {
            totals.push_back(mesh_editor_compensated_sum(item.second));
        }
        const double total = mesh_editor_compensated_sum(totals);
        if (!std::isfinite(total) || total <= 0.0) {
            out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
            return false;
        }
        std::size_t position = 0;
        std::vector<double> normalized;
        normalized.reserve(totals.size());
        for (const auto& item : merged) {
            const double weight = totals[position++] / total;
            if (!std::isfinite(weight) || weight <= 0.0) {
                out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
                return false;
            }
            out_parents.push_back(item.first);
            out_weights.push_back(weight);
            normalized.push_back(weight);
        }
        if (std::fabs(mesh_editor_compensated_sum(normalized) - 1.0) > MESH_TOPOLOGY_WEIGHT_SUM_TOLERANCE) {
            out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
            return false;
        }
        out_offsets.push_back(static_cast<int>(out_parents.size()));
        blends.erase(blend);
    }
    if (!blends.empty()) {
        out_blocker = MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID;
        return false;
    }
    return true;
}

// Compose every topology-changed result against the pre-mutation session. An
// admitted operation that will not compose leaves the whole apply untouched; an
// operation outside the rebuildable set is recorded as non-rebuildable and stays
// available for experimentation.
void mesh_editor_prepare_topology_provenance(
    const std::map<int, MeshSessionSubmesh>& native_session,
    std::vector<SubmeshMeshEditResult>& results,
    double& out_elapsed_ms,
    std::size_t& out_parent_entries
) {
    const auto started = std::chrono::steady_clock::now();
    out_parent_entries = 0;
    double prepared_ms = 0.0;
    for (SubmeshMeshEditResult& result : results) {
        if (!result.topology_changed || result.index < 0 || result.vertices.empty()) {
            continue;
        }
        if (result.topology_provenance_prepared) {
            // run_mesh_edit already composed this against the pre-mutation
            // session; re-reading the map here would see the mutated state.
            out_parent_entries += result.topology_vertex_origin_parents.size();
            prepared_ms += result.topology_provenance_ms;
            continue;
        }
        if (result.append_submesh) {
            // An appended part is a new submesh with no original of its own.
            result.topology_rebuild_valid = false;
            result.topology_blocker = MESH_TOPOLOGY_BLOCKER_OPERATION_NOT_REBUILDABLE;
            continue;
        }
        const auto previous = native_session.find(result.index);
        if (previous == native_session.end()) {
            result.topology_rebuild_valid = false;
            result.topology_blocker = MESH_TOPOLOGY_BLOCKER_PROVENANCE_REQUIRED;
            continue;
        }
        result.topology_original_vertex_count = previous->second.topology_original_vertex_count;
        result.topology_original_face_count = previous->second.topology_original_face_count;
        if (!mesh_editor_is_rebuildable_topology_action(result.action)) {
            result.topology_rebuild_valid = false;
            result.topology_blocker = MESH_TOPOLOGY_BLOCKER_OPERATION_NOT_REBUILDABLE;
            continue;
        }
        std::string blocker;
        if (!mesh_editor_compose_topology_provenance(
                previous->second,
                result,
                result.topology_vertex_origin_offsets,
                result.topology_vertex_origin_parents,
                result.topology_vertex_origin_weights,
                blocker)) {
            if (blocker == MESH_TOPOLOGY_BLOCKER_PROVENANCE_REQUIRED
                || blocker == MESH_TOPOLOGY_BLOCKER_CONTRACT_UNSUPPORTED) {
                // The submesh never had a usable contract; the edit itself is
                // still fine, it simply cannot be rebuilt exactly.
                result.topology_rebuild_valid = false;
                result.topology_blocker = blocker;
                continue;
            }
            // An admitted operation that produced a malformed derivation is a
            // native defect, not a user state. Refuse before anything mutates.
            throw std::runtime_error(
                "mesh editor topology provenance composition failed for submesh "
                + std::to_string(result.index) + ": " + blocker
            );
        }
        result.topology_rebuild_valid = true;
        result.topology_blocker.clear();
        out_parent_entries += result.topology_vertex_origin_parents.size();
    }
    const auto finished = std::chrono::steady_clock::now();
    // Composition that already ran before the session was mutated is the real
    // cost; this pass only sweeps up whatever it did not cover.
    out_elapsed_ms = prepared_ms + std::chrono::duration<double, std::milli>(finished - started).count();
}

void mesh_editor_store_result_topology_provenance(
    MeshSessionSubmesh& submesh,
    const SubmeshMeshEditResult& result
) {
    submesh.topology_original_vertex_count = result.topology_original_vertex_count;
    submesh.topology_original_face_count = result.topology_original_face_count;
    if (!result.topology_rebuild_valid) {
        mesh_editor_clear_topology_provenance(
            submesh,
            result.topology_blocker.empty()
                ? MESH_TOPOLOGY_BLOCKER_OPERATION_NOT_REBUILDABLE
                : result.topology_blocker.c_str()
        );
        return;
    }
    submesh.vertex_origin_offsets = result.topology_vertex_origin_offsets;
    submesh.vertex_origin_parents = result.topology_vertex_origin_parents;
    submesh.vertex_origin_weights = result.topology_vertex_origin_weights;
    submesh.topology_rebuild_valid = true;
    submesh.topology_blocker.clear();
    if (!mesh_editor_topology_provenance_shape_valid(submesh)) {
        // Every output vertex and face is checked once more against the submesh
        // it now describes, so a composition that no longer matches the stored
        // geometry can never be published as valid.
        mesh_editor_clear_topology_provenance(submesh, MESH_TOPOLOGY_BLOCKER_VERTEX_ORIGIN_INVALID);
    }
}
