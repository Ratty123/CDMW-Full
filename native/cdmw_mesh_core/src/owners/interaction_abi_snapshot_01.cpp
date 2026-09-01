constexpr double k_mesh_interaction_bucket_size = 16.0;
constexpr std::size_t k_mesh_interaction_max_bucket_span = 256;

int64_t mesh_interaction_bucket_key(int x, int y) {
    const uint64_t high = static_cast<uint32_t>(x);
    const uint64_t low = static_cast<uint32_t>(y);
    return static_cast<int64_t>((high << 32) | low);
}

int mesh_interaction_bucket_coordinate(double value) {
    const double scaled = std::floor(value / k_mesh_interaction_bucket_size);
    if (scaled <= static_cast<double>(std::numeric_limits<int>::min())) {
        return std::numeric_limits<int>::min();
    }
    if (scaled >= static_cast<double>(std::numeric_limits<int>::max())) {
        return std::numeric_limits<int>::max();
    }
    return static_cast<int>(scaled);
}

std::array<double, 4> mesh_interaction_bounds(
    double ax,
    double ay,
    double bx,
    double by
) {
    return {std::min(ax, bx), std::min(ay, by), std::max(ax, bx), std::max(ay, by)};
}

void mesh_interaction_add_bounds_to_buckets(
    const std::array<double, 4>& bounds,
    std::size_t value,
    std::unordered_map<int64_t, std::vector<std::size_t>>& buckets,
    std::vector<std::size_t>& large
) {
    const int min_x = mesh_interaction_bucket_coordinate(bounds[0]);
    const int min_y = mesh_interaction_bucket_coordinate(bounds[1]);
    const int max_x = mesh_interaction_bucket_coordinate(bounds[2]);
    const int max_y = mesh_interaction_bucket_coordinate(bounds[3]);
    const int64_t width = static_cast<int64_t>(max_x) - min_x + 1;
    const int64_t height = static_cast<int64_t>(max_y) - min_y + 1;
    const uint64_t unsigned_width = width > 0 ? static_cast<uint64_t>(width) : 0;
    const uint64_t unsigned_height = height > 0 ? static_cast<uint64_t>(height) : 0;
    if (width <= 0 || height <= 0
        || unsigned_width > std::numeric_limits<uint64_t>::max() / unsigned_height
        || unsigned_width * unsigned_height > k_mesh_interaction_max_bucket_span) {
        large.push_back(value);
        return;
    }
    for (int64_t y = min_y; y <= max_y; ++y) {
        for (int64_t x = min_x; x <= max_x; ++x) {
            buckets[mesh_interaction_bucket_key(
                static_cast<int>(x), static_cast<int>(y)
            )].push_back(value);
        }
    }
}

int mesh_interaction_build_depth_bvh(
    MeshInteractionSnapshot& snapshot,
    std::size_t first,
    std::size_t count
) {
    MeshInteractionDepthBvhNode node;
    node.first = first;
    node.count = count;
    node.bounds = {
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
    };
    for (std::size_t offset = first; offset < first + count; ++offset) {
        const auto& bounds = snapshot.faces[snapshot.depth_face_order[offset]].bounds;
        node.bounds[0] = std::min(node.bounds[0], bounds[0]);
        node.bounds[1] = std::min(node.bounds[1], bounds[1]);
        node.bounds[2] = std::max(node.bounds[2], bounds[2]);
        node.bounds[3] = std::max(node.bounds[3], bounds[3]);
    }
    const int node_index = static_cast<int>(snapshot.depth_bvh.size());
    snapshot.depth_bvh.push_back(node);
    if (count <= 8) {
        return node_index;
    }
    const bool split_x = (node.bounds[2] - node.bounds[0]) >= (node.bounds[3] - node.bounds[1]);
    const std::size_t middle = first + count / 2;
    std::nth_element(
        snapshot.depth_face_order.begin() + static_cast<std::ptrdiff_t>(first),
        snapshot.depth_face_order.begin() + static_cast<std::ptrdiff_t>(middle),
        snapshot.depth_face_order.begin() + static_cast<std::ptrdiff_t>(first + count),
        [&](std::size_t left, std::size_t right) {
            const auto& a = snapshot.faces[left].bounds;
            const auto& b = snapshot.faces[right].bounds;
            const double ac = split_x ? a[0] + a[2] : a[1] + a[3];
            const double bc = split_x ? b[0] + b[2] : b[1] + b[3];
            return ac < bc;
        }
    );
    const int left = mesh_interaction_build_depth_bvh(snapshot, first, middle - first);
    const int right = mesh_interaction_build_depth_bvh(snapshot, middle, first + count - middle);
    snapshot.depth_bvh[node_index].left = left;
    snapshot.depth_bvh[node_index].right = right;
    snapshot.depth_bvh[node_index].count = 0;
    return node_index;
}

struct MeshInteractionSnapshotSubmeshInput {
    int submesh_index = -1;
    std::vector<Vec3> vertices;
    std::vector<std::array<int, 3>> faces;
    std::array<double, 16> matrix{};
};

MeshInteractionSnapshot mesh_interaction_build_snapshot(
    const CdmwMeshInteractionPrepareSnapshotV1& request,
    const std::vector<MeshInteractionSnapshotSubmeshInput>& inputs,
    double viewport_width,
    double viewport_height
) {
    MeshInteractionSnapshot snapshot;
    snapshot.mesh_revision = request.mesh_revision;
    snapshot.topology_generation = request.topology_generation;
    snapshot.camera_revision = request.camera_revision;
    snapshot.viewport_revision = request.viewport_revision;
    snapshot.visible_parts_revision = request.visible_parts_revision;
    snapshot.model_transform_revision = request.model_transform_revision;
    snapshot.xray = request.xray != 0;
    for (const auto& input : inputs) {
        std::vector<std::size_t>& lookup = snapshot.vertex_lookup[input.submesh_index];
        lookup.assign(input.vertices.size(), std::numeric_limits<std::size_t>::max());
        for (std::size_t vertex_index = 0; vertex_index < input.vertices.size(); ++vertex_index) {
            double x = 0.0;
            double y = 0.0;
            double depth = 0.0;
            if (!project_vertex_with_matrix_depth(
                    input.matrix,
                    input.vertices[vertex_index],
                    0.0,
                    0.0,
                    viewport_width,
                    viewport_height,
                    x,
                    y,
                    depth)) {
                continue;
            }
            const std::size_t projected_index = snapshot.vertices.size();
            snapshot.vertices.push_back(MeshInteractionProjectedVertex{
                input.submesh_index,
                static_cast<int>(vertex_index),
                x,
                y,
                depth,
            });
            lookup[vertex_index] = projected_index;
            const int cell_x = mesh_interaction_bucket_coordinate(x);
            const int cell_y = mesh_interaction_bucket_coordinate(y);
            snapshot.vertex_buckets[mesh_interaction_bucket_key(cell_x, cell_y)].push_back(
                projected_index
            );
        }

        std::set<std::array<int, 2>> edges;
        std::vector<std::vector<int>>& adjacency = snapshot.adjacency[input.submesh_index];
        adjacency.resize(input.vertices.size());
        for (std::size_t face_index = 0; face_index < input.faces.size(); ++face_index) {
            const auto& face = input.faces[face_index];
            if (face[0] < 0 || face[1] < 0 || face[2] < 0
                || static_cast<std::size_t>(face[0]) >= lookup.size()
                || static_cast<std::size_t>(face[1]) >= lookup.size()
                || static_cast<std::size_t>(face[2]) >= lookup.size()) {
                continue;
            }
            const std::size_t p0 = lookup[face[0]];
            const std::size_t p1 = lookup[face[1]];
            const std::size_t p2 = lookup[face[2]];
            if (p0 == std::numeric_limits<std::size_t>::max()
                || p1 == std::numeric_limits<std::size_t>::max()
                || p2 == std::numeric_limits<std::size_t>::max()) {
                continue;
            }
            const auto& a = snapshot.vertices[p0];
            const auto& b = snapshot.vertices[p1];
            const auto& c = snapshot.vertices[p2];
            MeshInteractionProjectedFace projected;
            projected.submesh_index = input.submesh_index;
            projected.face_index = static_cast<int>(face_index);
            projected.vertices = face;
            projected.projected = {a.x, a.y, a.depth, b.x, b.y, b.depth, c.x, c.y, c.depth};
            projected.bounds = {
                std::min({a.x, b.x, c.x}),
                std::min({a.y, b.y, c.y}),
                std::max({a.x, b.x, c.x}),
                std::max({a.y, b.y, c.y}),
            };
            const std::size_t face_slot = snapshot.faces.size();
            snapshot.faces.push_back(projected);
            mesh_interaction_add_bounds_to_buckets(
                projected.bounds,
                face_slot,
                snapshot.face_buckets,
                snapshot.large_faces
            );
            for (int edge_index = 0; edge_index < 3; ++edge_index) {
                int left = face[edge_index];
                int right = face[(edge_index + 1) % 3];
                if (left > right) std::swap(left, right);
                edges.insert({left, right});
                adjacency[left].push_back(right);
                adjacency[right].push_back(left);
            }
        }
        for (auto& neighbors : adjacency) {
            std::sort(neighbors.begin(), neighbors.end());
            neighbors.erase(std::unique(neighbors.begin(), neighbors.end()), neighbors.end());
        }
        for (const auto& edge : edges) {
            const std::size_t left = lookup[edge[0]];
            const std::size_t right = lookup[edge[1]];
            if (left == std::numeric_limits<std::size_t>::max()
                || right == std::numeric_limits<std::size_t>::max()) {
                continue;
            }
            const auto& a = snapshot.vertices[left];
            const auto& b = snapshot.vertices[right];
            MeshInteractionProjectedEdge projected{
                input.submesh_index,
                edge[0],
                edge[1],
                mesh_interaction_bounds(a.x, a.y, b.x, b.y),
            };
            const std::size_t edge_slot = snapshot.edges.size();
            snapshot.edges.push_back(projected);
            mesh_interaction_add_bounds_to_buckets(
                projected.bounds,
                edge_slot,
                snapshot.edge_buckets,
                snapshot.large_edges
            );
        }
    }
    snapshot.depth_face_order.resize(snapshot.faces.size());
    std::iota(snapshot.depth_face_order.begin(), snapshot.depth_face_order.end(), 0);
    if (!snapshot.depth_face_order.empty()) {
        (void)mesh_interaction_build_depth_bvh(snapshot, 0, snapshot.depth_face_order.size());
    }
    snapshot.ready = true;
    return snapshot;
}

uint32_t interaction_abi_prepare_snapshot(
    const CdmwMeshInteractionPrepareSnapshotV1* request,
    CdmwMeshInteractionResultV1* result
) {
    std::string message;
    uint32_t status = mesh_interaction_abi_prepare_call(request, result, message);
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    status = mesh_interaction_abi_validate_request(request, message);
    if (status != CDMW_MESH_INTERACTION_OK) {
        return mesh_interaction_abi_fail(result, status, message);
    }
    std::shared_ptr<MeshInteractionAbiSession> runtime;
    {
        std::shared_lock<std::shared_mutex> registry_lock(g_mesh_interaction_abi_registry_mutex);
        runtime = mesh_interaction_abi_find_session(request->session_handle);
    }
    if (runtime == nullptr) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_SESSION_NOT_FOUND, "session handle is not open"
        );
    }

    std::vector<MeshInteractionSnapshotSubmeshInput> inputs;
    double viewport_width = 0.0;
    double viewport_height = 0.0;
    {
        std::lock_guard<std::mutex> session_lock(runtime->mutex);
        if (runtime->closed) {
            return mesh_interaction_abi_fail(
                result, CDMW_MESH_INTERACTION_SESSION_NOT_FOUND, "session handle is closed"
            );
        }
        if (request->mesh_revision != runtime->mesh_revision
            || request->selection_revision != runtime->selection_revision
            || request->topology_generation != runtime->topology_generation
            || request->camera_revision != runtime->camera_revision
            || request->viewport_revision != runtime->viewport_revision
            || !runtime->camera_valid
            || runtime->viewport_width <= 0.0
            || runtime->viewport_height <= 0.0) {
            return mesh_interaction_abi_fail(
                result, CDMW_MESH_INTERACTION_REVISION_MISMATCH,
                "snapshot revisions do not match the resident presentation"
            );
        }
        MeshEditorSession* editor = mesh_interaction_abi_find_editor(*runtime);
        if (editor == nullptr) {
            return mesh_interaction_abi_fail(
                result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, "resident editor is missing"
            );
        }
        const auto* submeshes_pointer = mesh_interaction_abi_find_submeshes(*runtime);
        if (submeshes_pointer == nullptr) {
            return mesh_interaction_abi_fail(
                result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, "resident mesh session is missing"
            );
        }
        const auto& submeshes = *submeshes_pointer;
        inputs.reserve(runtime->submesh_world_view_projections.size());
        for (const auto& projection : runtime->submesh_world_view_projections) {
            const auto submesh = submeshes.find(projection.first);
            if (submesh == submeshes.end()) continue;
            inputs.push_back(MeshInteractionSnapshotSubmeshInput{
                projection.first,
                submesh->second.vertices,
                submesh->second.faces,
                projection.second,
            });
        }
        viewport_width = runtime->viewport_width;
        viewport_height = runtime->viewport_height;
    }

    MeshInteractionSnapshot prepared = mesh_interaction_build_snapshot(
        *request,
        inputs,
        viewport_width,
        viewport_height
    );
    {
        std::lock_guard<std::mutex> session_lock(runtime->mutex);
        if (runtime->closed
            || request->mesh_revision != runtime->mesh_revision
            || request->selection_revision != runtime->selection_revision
            || request->topology_generation != runtime->topology_generation
            || request->camera_revision != runtime->camera_revision
            || request->viewport_revision != runtime->viewport_revision) {
            return mesh_interaction_abi_fail(
                result, CDMW_MESH_INTERACTION_REVISION_MISMATCH,
                "snapshot became stale before publication"
            );
        }
        runtime->snapshot = std::move(prepared);
        ++runtime->interaction_generation;
        return mesh_interaction_abi_finish_result(runtime.get(), result, {}, {}, "indexed snapshot prepared");
    }
}
