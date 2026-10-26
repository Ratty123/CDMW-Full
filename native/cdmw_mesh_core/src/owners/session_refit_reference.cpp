// Reference-body garment transfer.
//
// A binding to the body a garment must fit says nothing about the body it was
// authored on, so the barycentric fitter cannot tell an authored drape from a
// misfit. This path is also given the authored body, already retargeted by the
// caller into the driver's bind space with the garment's skeleton. What
// remains between that retargeted body and the live driver becomes one smooth
// spatial field that every garment samples, so stacked layers move almost
// identically and keep their order. Rigid pieces take the field's best rigid
// motion. One bounded position-based relaxation then restores authored layer
// order, driver clearance, cloth edge lengths and rigid shapes together.
//
// Distances are tuned in metres for a body whose bounding diagonal is two
// metres and scale with the driver's diagonal.

constexpr double REFIT_REFERENCE_DIAGONAL = 2.0;
constexpr double REFIT_REFERENCE_RAY_REACH = 0.08;
constexpr double REFIT_REFERENCE_RAY_AGREEMENT = 0.3;
constexpr int REFIT_REFERENCE_FIELD_SMOOTHING = 30;
constexpr std::size_t REFIT_REFERENCE_FIELD_NEIGHBOURS = 48;
constexpr double REFIT_REFERENCE_FIELD_WIDTH = 0.012;
constexpr double REFIT_REFERENCE_FIELD_SPREAD = 0.6;
constexpr double REFIT_REFERENCE_CONTACT = 0.003;
// Touching rigid pieces form one assembly. An assembly that one rigid motion
// would sink into the body by more than ASSEMBLY_SINK, where the body's own
// motion keeps that point outside, splits into sub-assemblies: pieces joined
// only where the smaller is at most ASSEMBLY of the larger (a tip on its
// scabbard, a ring on its buckle), not a row of similar studs along a strap.
constexpr double REFIT_REFERENCE_ASSEMBLY = 0.5;
constexpr double REFIT_REFERENCE_ASSEMBLY_SINK = 0.002;
constexpr double REFIT_REFERENCE_LAYER_RADIUS = 0.012;
constexpr double REFIT_REFERENCE_LAYER_MIN_SIDE = 0.0003;
constexpr std::size_t REFIT_REFERENCE_LAYER_PARTNERS = 4;
constexpr double REFIT_REFERENCE_LAYER_KEEP = 0.8;
constexpr double REFIT_REFERENCE_LAYER_CAP = 0.003;
// Layer constraints weigh as much as an edge. Stiffer layers overrode the cloth's
// edges where stacked strips slid on a differently shaped body and shredded them.
constexpr double REFIT_REFERENCE_LAYER_WEIGHT = 1.0;
// Every so many iterations, a layer constraint whose particle has slid this many
// layer radii away from its partner point moves to the partner surface beneath it.
constexpr int REFIT_REFERENCE_LAYER_REANCHOR = 15;
constexpr double REFIT_REFERENCE_LAYER_STALE = 3.0;
// A driver vertex this close in front of its closest garment triangle, with
// normals agreeing this much, has come through the cloth. Rows are found again
// every SKIN_REFRESH iterations.
constexpr double REFIT_REFERENCE_SKIN_REACH = 0.02;
constexpr double REFIT_REFERENCE_SKIN_FACING = 0.5;
constexpr int REFIT_REFERENCE_SKIN_REFRESH = 10;
// Closed pieces up to this share of the driver's diagonal take one set of weights.
constexpr double REFIT_REFERENCE_SOLID_SIZE = 0.25;
constexpr double REFIT_REFERENCE_INSIDE = 0.0005;
constexpr double REFIT_REFERENCE_DEEP_INSIDE = 0.04;
constexpr double REFIT_REFERENCE_FAR_OUTSIDE = 0.03;
constexpr int REFIT_REFERENCE_ITERATIONS = 150;
constexpr double REFIT_REFERENCE_CONSTRAINT_WEIGHT = 10.0;
constexpr double REFIT_REFERENCE_ANCHOR = 0.02;
constexpr double REFIT_REFERENCE_RIGID_INVERSE_MASS = 0.25;
constexpr double REFIT_REFERENCE_STRETCH_MIN = 0.92;
constexpr double REFIT_REFERENCE_STRETCH_MAX = 1.04;
// A plain Jacobi step. Over-relaxing (1.5) overshot where layer, body and edge
// constraints disagree, so more iterations made such fits worse, not better.
constexpr double REFIT_REFERENCE_STEP = 1.0;
constexpr std::size_t REFIT_REFERENCE_MAX_VERTICES = 2000000;
// Skin pull closes part of the outfit's own gap to the skin. A point's gap is the
// innermost garment over the same skin within PULL_REACH, so stacked layers move
// together; cloth whose innermost layer hangs more than PULL_FULL off the body
// takes less of the pull, and none past PULL_NONE (a sash tail, a cape).
constexpr double REFIT_REFERENCE_PULL_REACH = 0.02;
constexpr double REFIT_REFERENCE_PULL_FULL = 0.06;
constexpr double REFIT_REFERENCE_PULL_NONE = 0.09;
// The pull is spread like the body field (Gaussian width), so neighbouring
// layers and touching pieces move alike instead of crossing.
constexpr double REFIT_REFERENCE_PULL_SPREAD = 0.015;

Vec3 refit_reference_cross(const Vec3& a, const Vec3& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}

std::tuple<long long, long long, long long> refit_reference_weld_key(const Vec3& point) {
    // Same quantization as mesh_editor_refit_islands, so welds never cross islands.
    return {std::llround(point[0] * 100000.0), std::llround(point[1] * 100000.0), std::llround(point[2] * 100000.0)};
}

struct RefitReferenceBoundsNode {
    Vec3 minimum{0.0, 0.0, 0.0};
    Vec3 maximum{0.0, 0.0, 0.0};
    std::size_t begin = 0;
    std::size_t end = 0;
    int left = -1;
    int right = -1;
};

// A static bounding-volume hierarchy over triangles with closest-point, first
// ray hit and radius queries. Splits are deterministic for equal centroids.
struct RefitReferenceTriangleIndex {
    std::vector<std::array<Vec3, 3>> corners;
    std::vector<int> order;
    std::vector<RefitReferenceBoundsNode> nodes;

    RefitReferenceTriangleIndex(const std::vector<Vec3>& points, const std::vector<std::array<int, 3>>& faces) {
        corners.reserve(faces.size());
        for (const auto& face : faces)
            corners.push_back({points.at(static_cast<std::size_t>(face[0])), points.at(static_cast<std::size_t>(face[1])),
                points.at(static_cast<std::size_t>(face[2]))});
        order.resize(corners.size());
        std::iota(order.begin(), order.end(), 0);
        if (!corners.empty()) {
            nodes.reserve(corners.size() * 2);
            build(0, corners.size());
        }
    }

    Vec3 centroid(int triangle) const {
        const auto& c = corners[static_cast<std::size_t>(triangle)];
        return scale_vec3(add_vec3(add_vec3(c[0], c[1]), c[2]), 1.0 / 3.0);
    }

    int build(std::size_t begin, std::size_t end) {
        RefitReferenceBoundsNode node;
        node.begin = begin;
        node.end = end;
        node.minimum = node.maximum = corners[static_cast<std::size_t>(order[begin])][0];
        Vec3 low = centroid(order[begin]), high = low;
        for (std::size_t i = begin; i < end; ++i) {
            for (const auto& point : corners[static_cast<std::size_t>(order[i])]) for (int axis = 0; axis < 3; ++axis) {
                node.minimum[axis] = std::min(node.minimum[axis], point[axis]);
                node.maximum[axis] = std::max(node.maximum[axis], point[axis]);
            }
            const Vec3 center = centroid(order[i]);
            for (int axis = 0; axis < 3; ++axis) {
                low[axis] = std::min(low[axis], center[axis]);
                high[axis] = std::max(high[axis], center[axis]);
            }
        }
        const int index = static_cast<int>(nodes.size());
        nodes.push_back(node);
        if (end - begin <= 6) return index;
        int axis = 0;
        for (int candidate = 1; candidate < 3; ++candidate)
            if (high[candidate] - low[candidate] > high[axis] - low[axis]) axis = candidate;
        const std::size_t middle = begin + (end - begin) / 2;
        std::nth_element(order.begin() + static_cast<std::ptrdiff_t>(begin), order.begin() + static_cast<std::ptrdiff_t>(middle),
            order.begin() + static_cast<std::ptrdiff_t>(end), [&](int a, int b) {
                const double ca = centroid(a)[axis], cb = centroid(b)[axis];
                return ca != cb ? ca < cb : a < b;
            });
        const int left = build(begin, middle);
        const int right = build(middle, end);
        nodes[static_cast<std::size_t>(index)].left = left;
        nodes[static_cast<std::size_t>(index)].right = right;
        return index;
    }

    struct Hit {
        int triangle = -1;
        Vec3 point{0.0, 0.0, 0.0};
        std::array<double, 3> barycentric{1.0, 0.0, 0.0};
        double distance_squared = std::numeric_limits<double>::infinity();
    };

    Hit closest(const Vec3& point) const {
        Hit best;
        if (nodes.empty()) return best;
        std::vector<int> pending{0};
        while (!pending.empty()) {
            const auto& node = nodes[static_cast<std::size_t>(pending.back())];
            pending.pop_back();
            if (refit_aabb_distance_squared_native(point, node.minimum, node.maximum) >= best.distance_squared) continue;
            if (node.left < 0) {
                for (std::size_t i = node.begin; i < node.end; ++i) {
                    const int triangle = order[i];
                    const auto& c = corners[static_cast<std::size_t>(triangle)];
                    const auto candidate = closest_triangle_point_native(point, c[0], c[1], c[2]);
                    if (candidate.distance_squared < best.distance_squared
                        || (candidate.distance_squared == best.distance_squared && triangle < best.triangle)) {
                        best.triangle = triangle;
                        best.barycentric = candidate.barycentric;
                        best.distance_squared = candidate.distance_squared;
                    }
                }
                continue;
            }
            const auto& left = nodes[static_cast<std::size_t>(node.left)];
            const auto& right = nodes[static_cast<std::size_t>(node.right)];
            const bool left_first = refit_aabb_distance_squared_native(point, left.minimum, left.maximum)
                <= refit_aabb_distance_squared_native(point, right.minimum, right.maximum);
            pending.push_back(left_first ? node.right : node.left);
            pending.push_back(left_first ? node.left : node.right);
        }
        if (best.triangle >= 0) {
            const auto& c = corners[static_cast<std::size_t>(best.triangle)];
            best.point = add_vec3(add_vec3(scale_vec3(c[0], best.barycentric[0]), scale_vec3(c[1], best.barycentric[1])),
                scale_vec3(c[2], best.barycentric[2]));
        }
        return best;
    }

    // Nearest hit along origin + t * direction for 0 <= t <= reach.
    bool first_hit(const Vec3& origin, const Vec3& direction, double reach, int& triangle, double& distance) const {
        triangle = -1;
        distance = reach;
        if (nodes.empty()) return false;
        std::vector<int> pending{0};
        while (!pending.empty()) {
            const auto& node = nodes[static_cast<std::size_t>(pending.back())];
            pending.pop_back();
            double near = 0.0, far = distance;
            bool intersects = true;
            for (int axis = 0; axis < 3 && intersects; ++axis) {
                if (std::abs(direction[axis]) <= 1.0e-15) {
                    if (origin[axis] < node.minimum[axis] || origin[axis] > node.maximum[axis]) intersects = false;
                    continue;
                }
                double first = (node.minimum[axis] - origin[axis]) / direction[axis];
                double second = (node.maximum[axis] - origin[axis]) / direction[axis];
                if (first > second) std::swap(first, second);
                near = std::max(near, first);
                far = std::min(far, second);
                if (near > far) intersects = false;
            }
            if (!intersects) continue;
            if (node.left >= 0) {
                pending.push_back(node.left);
                pending.push_back(node.right);
                continue;
            }
            for (std::size_t i = node.begin; i < node.end; ++i) {
                const auto& c = corners[static_cast<std::size_t>(order[i])];
                const Vec3 edge1 = sub_vec3(c[1], c[0]), edge2 = sub_vec3(c[2], c[0]);
                const Vec3 p = refit_reference_cross(direction, edge2);
                const double determinant = dot_vec3(edge1, p);
                const double scale = length_vec3(edge1) * length_vec3(edge2);
                if (!(std::abs(determinant) > scale * 1.0e-12)) continue;
                const Vec3 offset = sub_vec3(origin, c[0]);
                const double u = dot_vec3(offset, p) / determinant;
                if (u < -1.0e-9 || u > 1.0 + 1.0e-9) continue;
                const Vec3 q = refit_reference_cross(offset, edge1);
                const double v = dot_vec3(direction, q) / determinant;
                if (v < -1.0e-9 || u + v > 1.0 + 1.0e-9) continue;
                const double t = dot_vec3(edge2, q) / determinant;
                if (t < 0.0 || t > distance || (t == distance && triangle >= 0 && order[i] > triangle)) continue;
                distance = t;
                triangle = order[i];
            }
        }
        return triangle >= 0;
    }

    template <typename Visit>
    void within(const Vec3& point, double radius, Visit&& visit) const {
        if (nodes.empty()) return;
        const double limit = radius * radius;
        std::vector<int> pending{0};
        while (!pending.empty()) {
            const auto& node = nodes[static_cast<std::size_t>(pending.back())];
            pending.pop_back();
            if (refit_aabb_distance_squared_native(point, node.minimum, node.maximum) > limit) continue;
            if (node.left >= 0) {
                pending.push_back(node.right);
                pending.push_back(node.left);
                continue;
            }
            for (std::size_t i = node.begin; i < node.end; ++i) visit(order[i]);
        }
    }
};

// A static bounding-volume hierarchy over points for nearest-neighbour and
// radius queries.
struct RefitReferencePointIndex {
    std::vector<Vec3> points;
    std::vector<int> order;
    std::vector<RefitReferenceBoundsNode> nodes;

    explicit RefitReferencePointIndex(std::vector<Vec3> values) : points(std::move(values)) {
        order.resize(points.size());
        std::iota(order.begin(), order.end(), 0);
        if (!points.empty()) {
            nodes.reserve(points.size() / 4 + 4);
            build(0, points.size());
        }
    }

    int build(std::size_t begin, std::size_t end) {
        RefitReferenceBoundsNode node;
        node.begin = begin;
        node.end = end;
        node.minimum = node.maximum = points[static_cast<std::size_t>(order[begin])];
        for (std::size_t i = begin; i < end; ++i) for (int axis = 0; axis < 3; ++axis) {
            node.minimum[axis] = std::min(node.minimum[axis], points[static_cast<std::size_t>(order[i])][axis]);
            node.maximum[axis] = std::max(node.maximum[axis], points[static_cast<std::size_t>(order[i])][axis]);
        }
        const int index = static_cast<int>(nodes.size());
        nodes.push_back(node);
        if (end - begin <= 8) return index;
        int axis = 0;
        for (int candidate = 1; candidate < 3; ++candidate)
            if (node.maximum[candidate] - node.minimum[candidate] > node.maximum[axis] - node.minimum[axis]) axis = candidate;
        const std::size_t middle = begin + (end - begin) / 2;
        std::nth_element(order.begin() + static_cast<std::ptrdiff_t>(begin), order.begin() + static_cast<std::ptrdiff_t>(middle),
            order.begin() + static_cast<std::ptrdiff_t>(end), [&](int a, int b) {
                const double pa = points[static_cast<std::size_t>(a)][axis], pb = points[static_cast<std::size_t>(b)][axis];
                return pa != pb ? pa < pb : a < b;
            });
        const int left = build(begin, middle);
        const int right = build(middle, end);
        nodes[static_cast<std::size_t>(index)].left = left;
        nodes[static_cast<std::size_t>(index)].right = right;
        return index;
    }

    // The k nearest points as (squared distance, index), nearest first.
    std::vector<std::pair<double, int>> nearest(const Vec3& point, std::size_t k) const {
        std::vector<std::pair<double, int>> heap;
        if (nodes.empty() || k == 0) return heap;
        heap.reserve(k + 1);
        std::vector<int> pending{0};
        while (!pending.empty()) {
            const auto& node = nodes[static_cast<std::size_t>(pending.back())];
            pending.pop_back();
            if (heap.size() == k && refit_aabb_distance_squared_native(point, node.minimum, node.maximum) > heap.front().first)
                continue;
            if (node.left >= 0) {
                const auto& left = nodes[static_cast<std::size_t>(node.left)];
                const auto& right = nodes[static_cast<std::size_t>(node.right)];
                const bool left_first = refit_aabb_distance_squared_native(point, left.minimum, left.maximum)
                    <= refit_aabb_distance_squared_native(point, right.minimum, right.maximum);
                pending.push_back(left_first ? node.right : node.left);
                pending.push_back(left_first ? node.left : node.right);
                continue;
            }
            for (std::size_t i = node.begin; i < node.end; ++i) {
                const int candidate = order[i];
                const std::pair<double, int> item{distance_squared_vec3(point, points[static_cast<std::size_t>(candidate)]), candidate};
                if (heap.size() < k) {
                    heap.push_back(item);
                    std::push_heap(heap.begin(), heap.end());
                } else if (item < heap.front()) {
                    std::pop_heap(heap.begin(), heap.end());
                    heap.back() = item;
                    std::push_heap(heap.begin(), heap.end());
                }
            }
        }
        std::sort_heap(heap.begin(), heap.end());
        return heap;
    }

    template <typename Visit>
    void within(const Vec3& point, double radius, Visit&& visit) const {
        if (nodes.empty()) return;
        const double limit = radius * radius;
        std::vector<int> pending{0};
        while (!pending.empty()) {
            const auto& node = nodes[static_cast<std::size_t>(pending.back())];
            pending.pop_back();
            if (refit_aabb_distance_squared_native(point, node.minimum, node.maximum) > limit) continue;
            if (node.left >= 0) {
                pending.push_back(node.right);
                pending.push_back(node.left);
                continue;
            }
            for (std::size_t i = node.begin; i < node.end; ++i)
                if (distance_squared_vec3(point, points[static_cast<std::size_t>(order[i])]) <= limit) visit(order[i]);
        }
    }
};

// A closed-or-open surface that answers signed distances. Inside the closest
// triangle the side comes from its normal; on its edges and corners from the
// interpolated vertex normals, which do not flip across a crease.
//
// An open rim has no inside. A body PAC's head is a shell with the face cut
// out (the face is a separate PAC), so a hood in front of the opening finds
// the rim closest, and the rim's sideways normals would call it inside the
// head. Points whose closest feature is an open edge or corner therefore get
// no side: they read as far outside and receive no clearance push.
struct RefitReferenceSurface {
    std::vector<std::array<int, 3>> faces;
    std::vector<Vec3> face_normals;
    std::vector<Vec3> vertex_normals;
    std::vector<int> welded;
    std::set<std::pair<int, int>> open_edges;
    std::vector<char> open_corners;
    RefitReferenceTriangleIndex index;

    RefitReferenceSurface(const std::vector<Vec3>& points, std::vector<std::array<int, 3>> triangles)
        : faces(std::move(triangles)), index(points, faces) {
        face_normals.reserve(faces.size());
        vertex_normals.assign(points.size(), Vec3{0.0, 0.0, 0.0});
        for (const auto& face : faces) {
            const Vec3 weighted = face_cross(points[static_cast<std::size_t>(face[0])], points[static_cast<std::size_t>(face[1])],
                points[static_cast<std::size_t>(face[2])]);
            face_normals.push_back(normalized_vec3_or_zero(weighted));
            for (const int corner : face)
                vertex_normals[static_cast<std::size_t>(corner)] = add_vec3(vertex_normals[static_cast<std::size_t>(corner)], weighted);
        }
        for (auto& normal : vertex_normals) normal = normalized_vec3_or_zero(normal);
        // Topology by position, so seams between Parts (head and body at the
        // neck) and UV splits are not mistaken for openings.
        std::map<std::tuple<long long, long long, long long>, int> ids;
        welded.reserve(points.size());
        for (const auto& point : points)
            welded.push_back(ids.emplace(refit_reference_weld_key(point), static_cast<int>(ids.size())).first->second);
        std::map<std::pair<int, int>, int> uses;
        for (const auto& face : faces) for (int c = 0; c < 3; ++c) {
            const int a = welded[static_cast<std::size_t>(face[c])], b = welded[static_cast<std::size_t>(face[(c + 1) % 3])];
            if (a != b) ++uses[std::minmax(a, b)];
        }
        open_corners.assign(ids.size(), 0);
        for (const auto& item : uses) if (item.second == 1) {
            open_edges.insert(item.first);
            open_corners[static_cast<std::size_t>(item.first.first)] = 1;
            open_corners[static_cast<std::size_t>(item.first.second)] = 1;
        }
    }

    bool open_at(const std::array<int, 3>& face, const std::array<double, 3>& barycentric) const {
        int zeros = 0, largest = 0;
        for (int c = 0; c < 3; ++c) {
            if (barycentric[c] <= 1.0e-7) ++zeros;
            if (barycentric[c] > barycentric[largest]) largest = c;
        }
        if (zeros == 2) return open_corners[static_cast<std::size_t>(welded[static_cast<std::size_t>(face[largest])])] != 0;
        if (zeros != 1) return false;
        int a = -1, b = -1;
        for (int c = 0; c < 3; ++c) if (barycentric[c] > 1.0e-7) (a < 0 ? a : b) = welded[static_cast<std::size_t>(face[c])];
        return open_edges.count(std::minmax(a, b)) != 0;
    }

    // Signed distance (positive outside) and the outward direction at point.
    double signed_distance(const Vec3& point, Vec3& outward, int* triangle = nullptr) const {
        const auto hit = index.closest(point);
        if (triangle) *triangle = hit.triangle;
        if (hit.triangle < 0 || open_at(faces[static_cast<std::size_t>(hit.triangle)], hit.barycentric)) {
            outward = {0.0, 0.0, 0.0};
            return std::numeric_limits<double>::infinity();
        }
        const auto& face = faces[static_cast<std::size_t>(hit.triangle)];
        Vec3 side = face_normals[static_cast<std::size_t>(hit.triangle)];
        if (std::min({hit.barycentric[0], hit.barycentric[1], hit.barycentric[2]}) <= 1.0e-7) {
            Vec3 blended{0.0, 0.0, 0.0};
            for (int corner = 0; corner < 3; ++corner)
                blended = add_vec3(blended, scale_vec3(vertex_normals[static_cast<std::size_t>(face[corner])], hit.barycentric[corner]));
            if (dot_vec3(blended, blended) > 1.0e-12) side = normalized_vec3_or_zero(blended);
        }
        const Vec3 delta = sub_vec3(point, hit.point);
        const double distance = std::sqrt(hit.distance_squared);
        const double sign = dot_vec3(delta, side) >= 0.0 ? 1.0 : -1.0;
        outward = distance > 1.0e-9 ? scale_vec3(delta, sign / distance) : side;
        return sign * distance;
    }
};

std::vector<Vec3> refit_reference_rigid_pose(const std::vector<Vec3>& rest, const std::vector<Vec3>& current) {
    Vec3 rest_center{0.0, 0.0, 0.0}, current_center{0.0, 0.0, 0.0};
    for (std::size_t i = 0; i < rest.size(); ++i) {
        rest_center = add_vec3(rest_center, rest[i]);
        current_center = add_vec3(current_center, current[i]);
    }
    rest_center = scale_vec3(rest_center, 1.0 / static_cast<double>(rest.size()));
    current_center = scale_vec3(current_center, 1.0 / static_cast<double>(rest.size()));
    const auto rotation = refit_component_rotation_native(rest, current, rest_center, current_center);
    std::vector<Vec3> posed;
    posed.reserve(rest.size());
    for (const auto& point : rest)
        posed.push_back(add_vec3(current_center, refit_rotate_quaternion_native(rotation, sub_vec3(point, rest_center))));
    return posed;
}

struct RefitReferenceBodyField {
    std::unique_ptr<RefitReferencePointIndex> points;
    std::vector<Vec3> displacement;
    long long ray_hits = 0;
    double maximum_displacement = 0.0;
};

// Displacement that carries each welded reference vertex, as authored, onto the
// driver surface. The retargeted reference supplies the correspondence: each
// vertex looks along its normal for a like-facing driver surface, or takes the
// closest point, and the result is smoothed over the reference surface.
RefitReferenceBodyField refit_reference_body_field(
    const MeshRefitReferenceBodyRuntime& reference, const RefitReferenceSurface& driver, double scale
) {
    std::map<std::tuple<long long, long long, long long>, int> welded;
    std::vector<int> weld(reference.source_positions.size());
    std::vector<Vec3> source, fitted;
    std::vector<double> counts;
    for (std::size_t i = 0; i < reference.source_positions.size(); ++i) {
        const auto inserted = welded.emplace(refit_reference_weld_key(reference.source_positions[i]), static_cast<int>(source.size()));
        weld[i] = inserted.first->second;
        if (inserted.second) {
            source.push_back(reference.source_positions[i]);
            fitted.push_back(Vec3{0.0, 0.0, 0.0});
            counts.push_back(0.0);
        }
        fitted[static_cast<std::size_t>(weld[i])] = add_vec3(fitted[static_cast<std::size_t>(weld[i])], reference.fitted_positions[i]);
        counts[static_cast<std::size_t>(weld[i])] += 1.0;
    }
    for (std::size_t i = 0; i < fitted.size(); ++i) fitted[i] = scale_vec3(fitted[i], 1.0 / counts[i]);
    std::vector<Vec3> normals(fitted.size(), Vec3{0.0, 0.0, 0.0});
    std::vector<std::set<int>> neighbours(fitted.size());
    for (const auto& face : reference.faces) {
        const std::array<int, 3> corners{weld[static_cast<std::size_t>(face[0])], weld[static_cast<std::size_t>(face[1])],
            weld[static_cast<std::size_t>(face[2])]};
        if (corners[0] == corners[1] || corners[1] == corners[2] || corners[0] == corners[2]) continue;
        const Vec3 weighted = face_cross(fitted[static_cast<std::size_t>(corners[0])], fitted[static_cast<std::size_t>(corners[1])],
            fitted[static_cast<std::size_t>(corners[2])]);
        for (int c = 0; c < 3; ++c) {
            normals[static_cast<std::size_t>(corners[c])] = add_vec3(normals[static_cast<std::size_t>(corners[c])], weighted);
            neighbours[static_cast<std::size_t>(corners[c])].insert(corners[(c + 1) % 3]);
            neighbours[static_cast<std::size_t>(corners[c])].insert(corners[(c + 2) % 3]);
        }
    }
    RefitReferenceBodyField field;
    std::vector<Vec3> displacement(fitted.size());
    const double reach = REFIT_REFERENCE_RAY_REACH * scale;
    for (std::size_t i = 0; i < fitted.size(); ++i) {
        const auto closest = driver.index.closest(fitted[i]);
        displacement[i] = closest.triangle < 0 ? Vec3{0.0, 0.0, 0.0} : sub_vec3(closest.point, fitted[i]);
        double best = std::sqrt(closest.distance_squared);
        const Vec3 normal = normalized_vec3_or_zero(normals[i]);
        if (dot_vec3(normal, normal) <= 0.5) continue;
        for (const double sign : {1.0, -1.0}) {
            const Vec3 direction = scale_vec3(normal, sign);
            const Vec3 origin = sub_vec3(fitted[i], scale_vec3(direction, 1.0e-4 * scale));
            int triangle = -1;
            double t = 0.0;
            if (!driver.index.first_hit(origin, direction, reach + 1.0e-4 * scale, triangle, t)) continue;
            const Vec3 hit = add_vec3(origin, scale_vec3(direction, t));
            const double distance = length_vec3(sub_vec3(hit, fitted[i]));
            if (dot_vec3(driver.face_normals[static_cast<std::size_t>(triangle)], normal) <= REFIT_REFERENCE_RAY_AGREEMENT
                || distance >= best * 2.5 || distance >= reach) continue;
            displacement[i] = sub_vec3(hit, fitted[i]);
            best = distance;
            ++field.ray_hits;
        }
    }
    for (int iteration = 0; iteration < REFIT_REFERENCE_FIELD_SMOOTHING; ++iteration) {
        std::vector<Vec3> next = displacement;
        for (std::size_t i = 0; i < displacement.size(); ++i) {
            if (neighbours[i].empty()) continue;
            Vec3 average{0.0, 0.0, 0.0};
            for (const int j : neighbours[i]) average = add_vec3(average, displacement[static_cast<std::size_t>(j)]);
            average = scale_vec3(average, 1.0 / static_cast<double>(neighbours[i].size()));
            next[i] = add_vec3(displacement[i], scale_vec3(sub_vec3(average, displacement[i]), 0.5));
        }
        displacement = std::move(next);
    }
    field.displacement.reserve(source.size());
    for (std::size_t i = 0; i < source.size(); ++i) {
        field.displacement.push_back(sub_vec3(add_vec3(fitted[i], displacement[i]), source[i]));
        field.maximum_displacement = std::max(field.maximum_displacement, length_vec3(field.displacement.back()));
    }
    field.points = std::make_unique<RefitReferencePointIndex>(std::move(source));
    return field;
}

// Kernel-weighted body motion at a garment point. The kernel widens with the
// distance to the body, so hanging geometry follows a smoother motion.
Vec3 refit_reference_field_at(const RefitReferenceBodyField& field, const Vec3& point, double scale) {
    const auto nearest = field.points->nearest(point, REFIT_REFERENCE_FIELD_NEIGHBOURS);
    if (nearest.empty()) return {0.0, 0.0, 0.0};
    const double closest = std::sqrt(nearest.front().first);
    const double width = REFIT_REFERENCE_FIELD_WIDTH * scale + REFIT_REFERENCE_FIELD_SPREAD * closest;
    Vec3 sum{0.0, 0.0, 0.0};
    double total = 0.0;
    for (const auto& item : nearest) {
        const double offset = (std::sqrt(item.first) - closest) / width;
        const double weight = std::exp(-offset * offset);
        sum = add_vec3(sum, scale_vec3(field.displacement[static_cast<std::size_t>(item.second)], weight));
        total += weight;
    }
    return scale_vec3(sum, 1.0 / total);
}

struct RefitReferenceIslandNative {
    bool fitted = false;
    std::string mode = "surface";
    double clearance = 0.0;
    double pull = 0.0;
    int unit = -1;
};

struct RefitReferenceParticle {
    int part = -1;
    int island = -1;
    int surface = -1;
    double clearance = 0.0;
    int unit = -1;
    double pull = 0.0;
};

// Defined in session_refit_weights.cpp.
std::map<int, BoneAssignments> mesh_editor_refit_transfer_weights(
    const MeshMorphRuntime&, const std::map<int, MeshSessionSubmesh>&, const RefitReferenceSurface&,
    const RefitReferenceSurface&, const std::map<int, std::vector<int>>&, const std::vector<Vec3>&,
    const std::vector<Vec3>&, const std::vector<std::vector<int>>&, const RefitMaskWeightsNative&, double, std::ostream&);

std::string mesh_editor_apply_reference_refit(
    const MeshMorphRuntime& morph,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& residual,
    std::map<int, std::vector<Vec3>>& layer,
    const std::map<int, std::vector<Vec3>>& post_refit,
    std::map<int, BoneAssignments>* weights
) {
    const auto started = std::chrono::steady_clock::now();
    const MeshRefitRuntime& refit = *morph.refit;
    const MeshRefitReferenceBodyRuntime& reference = *refit.reference_body;
    const double scale = refit.driver_diagonal > 0.0 ? refit.driver_diagonal / REFIT_REFERENCE_DIAGONAL : 1.0;
    const auto base_layer = layer;
    const auto visible = [&](int part, std::size_t vertex) {
        const auto procedural = base_layer.find(part);
        const Vec3 rest = residual.at(part).at(vertex);
        return procedural == base_layer.end() || procedural->second.empty() ? rest : add_vec3(rest, procedural->second.at(vertex));
    };

    std::vector<Vec3> driver_points;
    std::vector<std::array<int, 3>> driver_faces;
    for (const int part : refit.driver_submesh_indices) {
        const auto found = submeshes.find(part);
        if (found == submeshes.end() || !residual.count(part) || residual.at(part).size() != found->second.vertices.size())
            throw std::runtime_error("garment refit driver topology changed");
        const int offset = static_cast<int>(driver_points.size());
        for (std::size_t v = 0; v < found->second.vertices.size(); ++v) driver_points.push_back(visible(part, v));
        for (const auto& face : found->second.faces)
            driver_faces.push_back({face[0] + offset, face[1] + offset, face[2] + offset});
    }
    if (driver_faces.empty()) throw std::runtime_error("Fit to reference body requires a driver surface");
    const RefitReferenceSurface driver(driver_points, std::move(driver_faces));

    // Fitting domains. Disabled or excluded islands neither move nor collide.
    std::map<int, std::vector<RefitReferenceIslandNative>> islands;
    std::map<int, std::vector<int>> face_islands;
    std::map<int, std::vector<int>> particles;
    std::vector<RefitReferenceParticle> particle_rows;
    std::vector<Vec3> start;
    std::map<std::pair<int, int>, int> surfaces;
    int units = 0;
    for (const int part : refit.garment_submesh_indices) {
        const auto found = submeshes.find(part);
        if (found == submeshes.end() || !residual.count(part) || residual.at(part).size() != found->second.vertices.size())
            throw std::runtime_error("garment refit target topology changed");
        MeshRefitGarmentSettingsRuntime settings;
        const auto configured = refit.garment_settings.find(part);
        if (configured != refit.garment_settings.end()) settings = configured->second;
        auto topology = found->second;
        const auto neutral = morph.neutral_positions.find(part);
        if (neutral != morph.neutral_positions.end() && neutral->second.size() == topology.vertices.size())
            topology.vertices = neutral->second;
        const auto groups = mesh_editor_refit_islands(topology);
        const auto excluded = refit.excluded_faces.find(part);
        auto& rows = islands[part];
        auto& owner = face_islands[part];
        owner.assign(found->second.faces.size(), -1);
        int part_unit = -1;
        for (std::size_t g = 0; g < groups.size(); ++g) {
            RefitReferenceIslandNative island;
            bool enabled = settings.enabled;
            std::string mode = settings.mode;
            double clearance = settings.clearance_percent;
            double pull = settings.skin_pull_percent;
            bool inherits = true;
            for (const auto& item : settings.island_settings) {
                if (item.face_indices != groups[g]) continue;
                enabled = item.enabled;
                mode = item.mode;
                clearance = item.clearance_percent;
                pull = item.skin_pull_percent;
                inherits = false;
            }
            const bool removed = excluded != refit.excluded_faces.end()
                && (excluded->second.empty() || excluded->second.count(groups[g].front()));
            island.fitted = enabled && !removed;
            island.mode = mode;
            island.clearance = refit.driver_diagonal * clearance / 100.0;
            island.pull = pull / 100.0;
            if (island.fitted && mode == "rigid" && inherits) {
                // A rigid Part moves as one piece; a rigid island override moves alone.
                if (part_unit < 0) part_unit = units++;
                island.unit = part_unit;
            } else if (island.fitted && mode != "surface") {
                island.unit = units++;
            }
            for (const int face : groups[g]) owner[static_cast<std::size_t>(face)] = static_cast<int>(g);
            if (island.fitted) surfaces.emplace(std::make_pair(part, static_cast<int>(g)), static_cast<int>(surfaces.size()));
            rows.push_back(island);
        }
        auto& map = particles[part];
        map.assign(found->second.vertices.size(), -1);
        std::map<std::tuple<long long, long long, long long>, int> welded;
        for (std::size_t f = 0; f < found->second.faces.size(); ++f) {
            const int island = owner[f];
            if (island < 0 || !rows[static_cast<std::size_t>(island)].fitted) continue;
            for (const int vertex : found->second.faces[f]) {
                if (map[static_cast<std::size_t>(vertex)] >= 0) continue;
                const Vec3 point = visible(part, static_cast<std::size_t>(vertex));
                const auto inserted = welded.emplace(refit_reference_weld_key(point), static_cast<int>(start.size()));
                map[static_cast<std::size_t>(vertex)] = inserted.first->second;
                if (!inserted.second) continue;
                const auto& row = rows[static_cast<std::size_t>(island)];
                particle_rows.push_back({part, island, surfaces.at({part, island}), row.clearance, row.unit, row.pull});
                start.push_back(point);
            }
        }
    }
    const std::size_t count = start.size();
    std::ostringstream report;
    report << "{\"method\":\"reference_body\",\"reference_label\":";
    write_escaped(report, reference.label);
    if (count == 0) {
        report << ",\"particles\":0}";
        return report.str();
    }
    if (count > REFIT_REFERENCE_MAX_VERTICES) throw std::runtime_error("Fit to reference body supports at most two million garment vertices");

    // Rigid pieces that touch move together, also across Parts (a scabbard and
    // its tip). Two merges are made: every touching pair (whole assemblies), and
    // only a small piece onto a larger one (sub-assemblies). After the transfer,
    // an assembly whose best rigid motion strays from the body motion under it
    // splits into its sub-assemblies, so a row of studs along a strap across a
    // changed chest neither sinks into the body as one bar nor drags its cloth,
    // while a ring of beads around a waist that barely changed stays whole.
    std::vector<Vec3> rigid_points;
    std::vector<int> rigid_particles;
    const double far = std::numeric_limits<double>::infinity();
    std::vector<Vec3> unit_low(static_cast<std::size_t>(units), Vec3{far, far, far});
    std::vector<Vec3> unit_high(static_cast<std::size_t>(units), Vec3{-far, -far, -far});
    for (std::size_t i = 0; i < count; ++i) if (particle_rows[i].unit >= 0) {
        rigid_points.push_back(start[i]);
        rigid_particles.push_back(static_cast<int>(i));
        const auto unit = static_cast<std::size_t>(particle_rows[i].unit);
        for (int axis = 0; axis < 3; ++axis) {
            unit_low[unit][axis] = std::min(unit_low[unit][axis], start[i][axis]);
            unit_high[unit][axis] = std::max(unit_high[unit][axis], start[i][axis]);
        }
    }
    const RefitReferencePointIndex rigid_index(rigid_points);
    const auto merge_units = [&](double ratio) {
        std::vector<int> root(static_cast<std::size_t>(units));
        std::iota(root.begin(), root.end(), 0);
        std::vector<Vec3> low = unit_low, high = unit_high;
        const auto find = [&](int unit) {
            while (root[static_cast<std::size_t>(unit)] != unit) {
                root[static_cast<std::size_t>(unit)] = root[static_cast<std::size_t>(root[static_cast<std::size_t>(unit)])];
                unit = root[static_cast<std::size_t>(unit)];
            }
            return unit;
        };
        const auto size_of = [&](int unit) {
            return length_vec3(sub_vec3(high[static_cast<std::size_t>(unit)], low[static_cast<std::size_t>(unit)]));
        };
        for (std::size_t k = 0; k < rigid_particles.size(); ++k) {
            const int unit = particle_rows[static_cast<std::size_t>(rigid_particles[k])].unit;
            rigid_index.within(rigid_points[k], REFIT_REFERENCE_CONTACT * scale, [&](int other) {
                const int a = find(unit), b = find(particle_rows[static_cast<std::size_t>(rigid_particles[static_cast<std::size_t>(other)])].unit);
                if (a == b || std::min(size_of(a), size_of(b)) > ratio * std::max(size_of(a), size_of(b))) return;
                const int keep = std::min(a, b), gone = std::max(a, b);
                root[static_cast<std::size_t>(gone)] = keep;
                for (int axis = 0; axis < 3; ++axis) {
                    low[static_cast<std::size_t>(keep)][axis] = std::min(low[static_cast<std::size_t>(keep)][axis], low[static_cast<std::size_t>(gone)][axis]);
                    high[static_cast<std::size_t>(keep)][axis] = std::max(high[static_cast<std::size_t>(keep)][axis], high[static_cast<std::size_t>(gone)][axis]);
                }
            });
        }
        for (int unit = 0; unit < units; ++unit) root[static_cast<std::size_t>(unit)] = find(unit);
        return root;
    };
    const auto whole_root = merge_units(1.0);
    const auto small_root = merge_units(REFIT_REFERENCE_ASSEMBLY);

    // Transfer through the shared body field, then pose rigid groups.
    const auto field_started = std::chrono::steady_clock::now();
    const auto field = refit_reference_body_field(reference, driver, scale);
    std::vector<Vec3> rest(count);
    for (std::size_t i = 0; i < count; ++i) rest[i] = add_vec3(start[i], refit_reference_field_at(field, start[i], scale));
    const RefitReferenceSurface authored(reference.source_positions, reference.faces);
    const double sink = REFIT_REFERENCE_ASSEMBLY_SINK * scale;
    std::map<int, std::vector<int>> assemblies;
    for (std::size_t i = 0; i < count; ++i)
        if (particle_rows[i].unit >= 0) assemblies[whole_root[static_cast<std::size_t>(particle_rows[i].unit)]].push_back(static_cast<int>(i));
    std::vector<std::vector<int>> rigid_groups;
    long long split_assemblies = 0;
    for (auto& item : assemblies) {
        const auto& group = item.second;
        std::map<int, std::vector<int>> parts_of;
        for (const int i : group) parts_of[small_root[static_cast<std::size_t>(particle_rows[static_cast<std::size_t>(i)].unit)]].push_back(i);
        bool split = false;
        if (parts_of.size() > 1) {
            std::vector<Vec3> source, moved;
            for (const int i : group) {
                source.push_back(start[static_cast<std::size_t>(i)]);
                moved.push_back(rest[static_cast<std::size_t>(i)]);
            }
            const auto posed = refit_reference_rigid_pose(source, moved);
            for (std::size_t k = 0; k < posed.size() && !split; ++k) {
                // Floating a little off the body is harmless; sinking into it is not.
                if (distance_squared_vec3(posed[k], moved[k]) <= sink * sink) continue;
                Vec3 outward;
                split = driver.signed_distance(posed[k], outward) < -sink
                    && driver.signed_distance(moved[k], outward) > -REFIT_REFERENCE_INSIDE * scale;
            }
        }
        if (!split) {
            rigid_groups.push_back(group);
            continue;
        }
        ++split_assemblies;
        for (auto& part : parts_of) rigid_groups.push_back(std::move(part.second));
    }
    for (const auto& group : rigid_groups) {
        std::vector<Vec3> source, moved;
        for (const int i : group) {
            source.push_back(start[static_cast<std::size_t>(i)]);
            moved.push_back(rest[static_cast<std::size_t>(i)]);
        }
        const auto posed = refit_reference_rigid_pose(source, moved);
        for (std::size_t k = 0; k < group.size(); ++k) rest[static_cast<std::size_t>(group[k])] = posed[k];
    }
    const double field_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - field_started).count();

    // Garment edges and triangles in particle space.
    std::vector<std::array<int, 3>> garment_faces;
    std::vector<int> garment_face_surface;
    std::set<std::pair<int, int>> edge_set;
    for (const auto& part : particles) {
        const auto& faces = submeshes.at(part.first).faces;
        for (std::size_t f = 0; f < faces.size(); ++f) {
            const int island = face_islands.at(part.first)[f];
            if (island < 0 || !islands.at(part.first)[static_cast<std::size_t>(island)].fitted) continue;
            const std::array<int, 3> corners{part.second[static_cast<std::size_t>(faces[f][0])],
                part.second[static_cast<std::size_t>(faces[f][1])], part.second[static_cast<std::size_t>(faces[f][2])]};
            for (int c = 0; c < 3; ++c) {
                const int a = corners[c], b = corners[(c + 1) % 3];
                if (a != b) edge_set.insert(std::minmax(a, b));
            }
            if (corners[0] == corners[1] || corners[1] == corners[2] || corners[0] == corners[2]) continue;
            garment_faces.push_back(corners);
            garment_face_surface.push_back(surfaces.at({part.first, island}));
        }
    }
    const std::vector<std::pair<int, int>> edges(edge_set.begin(), edge_set.end());
    std::vector<std::vector<int>> surface_faces(surfaces.size());
    for (std::size_t f = 0; f < garment_faces.size(); ++f)
        surface_faces[static_cast<std::size_t>(garment_face_surface[f])].push_back(static_cast<int>(f));
    // A small closed piece the fit does not hold rigid (a bead, a clasp) must not
    // bend, unless the body passes through it (a collar).
    const auto small_closed_pieces = [&](const std::vector<std::vector<int>>& face_groups) {
        std::vector<std::vector<int>> found;
        Vec3 low = driver_points.front(), high = low;
        for (const auto& point : driver_points) for (int axis = 0; axis < 3; ++axis) {
            low[axis] = std::min(low[axis], point[axis]);
            high[axis] = std::max(high[axis], point[axis]);
        }
        int up = 0;
        for (int axis = 1; axis < 3; ++axis) if (high[axis] - low[axis] > high[up] - low[up]) up = axis;
        for (const auto& faces : face_groups) {
            std::map<std::pair<int, int>, int> uses;
            std::set<int> members;
            for (const int f : faces) {
                const auto& corners = garment_faces[static_cast<std::size_t>(f)];
                for (int c = 0; c < 3; ++c) {
                    ++uses[std::minmax(corners[c], corners[(c + 1) % 3])];
                    members.insert(corners[c]);
                }
            }
            if (members.empty() || std::any_of(members.begin(), members.end(),
                    [&](int i) { return particle_rows[static_cast<std::size_t>(i)].unit >= 0; })
                || std::any_of(uses.begin(), uses.end(), [](const auto& edge) { return edge.second != 2; }))
                continue;
            Vec3 piece_low = start[static_cast<std::size_t>(*members.begin())], piece_high = piece_low;
            for (const int i : members) for (int axis = 0; axis < 3; ++axis) {
                piece_low[axis] = std::min(piece_low[axis], start[static_cast<std::size_t>(i)][axis]);
                piece_high[axis] = std::max(piece_high[axis], start[static_cast<std::size_t>(i)][axis]);
            }
            bool band = true;
            for (int axis = 0; axis < 3; ++axis) {
                const double centre = (low[axis] + high[axis]) / 2.0;
                if (axis != up && (centre < piece_low[axis] || centre > piece_high[axis])) band = false;
            }
            if (band || length_vec3(sub_vec3(piece_high, piece_low)) > REFIT_REFERENCE_SOLID_SIZE * refit.driver_diagonal) continue;
            found.emplace_back(members.begin(), members.end());
        }
        return found;
    };

    // Skin pull, authored-body fits only: close the chosen share of the outfit's
    // own gap to the skin. A point's gap is the one under the innermost garment
    // over the same skin, so a stack of layers keeps its spacing; the result is
    // spread like the body field, and each rigid group and small closed piece
    // moves by its average, keeping its shape. Pieces that were inside the
    // authored body (a mask, a lining) neither move nor count.
    long long pulled = 0;
    if (std::any_of(particle_rows.begin(), particle_rows.end(), [](const auto& row) { return row.pull > 0.0; })) {
        std::vector<double> gap(count, std::numeric_limits<double>::infinity());
        std::vector<Vec3> inward(count, Vec3{0.0, 0.0, 0.0}), skin(count, Vec3{0.0, 0.0, 0.0});
        std::vector<int> valid;
        for (std::size_t i = 0; i < count; ++i) {
            Vec3 outward;
            if (authored.signed_distance(start[i], outward) < -REFIT_REFERENCE_INSIDE * scale) continue;
            const double distance = driver.signed_distance(rest[i], outward);
            if (!std::isfinite(distance) || dot_vec3(outward, outward) < 0.5) continue;
            gap[i] = distance;
            inward[i] = scale_vec3(outward, -1.0);
            skin[i] = sub_vec3(rest[i], scale_vec3(outward, distance));
            valid.push_back(static_cast<int>(i));
        }
        std::vector<Vec3> skin_points;
        for (const int i : valid) skin_points.push_back(skin[static_cast<std::size_t>(i)]);
        const RefitReferencePointIndex skin_index(skin_points);
        const double reach = REFIT_REFERENCE_PULL_REACH * scale;
        std::vector<double> innermost(count, std::numeric_limits<double>::infinity());
        for (const int i : valid) skin_index.within(skin[static_cast<std::size_t>(i)], reach, [&](int k) {
            innermost[static_cast<std::size_t>(i)] = std::min(innermost[static_cast<std::size_t>(i)],
                gap[static_cast<std::size_t>(valid[static_cast<std::size_t>(k)])]);
        });
        const double full = REFIT_REFERENCE_PULL_FULL * scale, none = REFIT_REFERENCE_PULL_NONE * scale;
        std::vector<Vec3> raw(count, Vec3{0.0, 0.0, 0.0});
        std::vector<int> members;
        for (const int i : valid) {
            const auto& row = particle_rows[static_cast<std::size_t>(i)];
            if (row.pull <= 0.0) continue;
            members.push_back(i);
            double under = 0.0;
            int samples = 0;
            skin_index.within(skin[static_cast<std::size_t>(i)], reach, [&](int k) {
                under += innermost[static_cast<std::size_t>(valid[static_cast<std::size_t>(k)])];
                ++samples;
            });
            under = samples ? under / samples : innermost[static_cast<std::size_t>(i)];
            if (!(under > row.clearance)) continue;
            const double share = row.pull * std::clamp((none - under) / (none - full), 0.0, 1.0);
            raw[static_cast<std::size_t>(i)] = scale_vec3(inward[static_cast<std::size_t>(i)], share * (under - row.clearance));
        }
        std::vector<Vec3> member_points;
        for (const int i : members) member_points.push_back(rest[static_cast<std::size_t>(i)]);
        const RefitReferencePointIndex member_index(member_points);
        const double spread = REFIT_REFERENCE_PULL_SPREAD * scale;
        std::vector<Vec3> shift(count, Vec3{0.0, 0.0, 0.0});
        for (const int i : members) {
            Vec3 sum{0.0, 0.0, 0.0};
            double weight = 0.0;
            member_index.within(rest[static_cast<std::size_t>(i)], 2.5 * spread, [&](int k) {
                const int j = members[static_cast<std::size_t>(k)];
                const double w = std::exp(-distance_squared_vec3(rest[static_cast<std::size_t>(i)], rest[static_cast<std::size_t>(j)])
                    / (2.0 * spread * spread));
                sum = add_vec3(sum, scale_vec3(raw[static_cast<std::size_t>(j)], w));
                weight += w;
            });
            if (weight <= 0.0) continue;
            // Spreading must not carry a point past its own skin.
            Vec3 spread_shift = scale_vec3(sum, 1.0 / weight);
            const double allowed = std::max(0.0, gap[static_cast<std::size_t>(i)] - particle_rows[static_cast<std::size_t>(i)].clearance);
            const double length = length_vec3(spread_shift);
            if (length > allowed) spread_shift = length > 0.0 ? scale_vec3(spread_shift, allowed / length) : spread_shift;
            shift[static_cast<std::size_t>(i)] = spread_shift;
        }
        // A rigid group moves by its smallest shift, so no end sinks into the
        // cloth under it. A small closed piece (also one inside a larger island,
        // a bead on a cord) moves by its average and is then held rigid like a
        // rigid group, or the layers under it would bend it as they come in.
        const auto translate = [&](const std::vector<int>& group) {
            Vec3 least = shift[static_cast<std::size_t>(group.front())];
            for (const int i : group)
                if (dot_vec3(shift[static_cast<std::size_t>(i)], shift[static_cast<std::size_t>(i)]) < dot_vec3(least, least))
                    least = shift[static_cast<std::size_t>(i)];
            for (const int i : group) shift[static_cast<std::size_t>(i)] = least;
        };
        for (const auto& group : rigid_groups) translate(group);
        std::vector<int> root(count);
        std::iota(root.begin(), root.end(), 0);
        const auto find = [&](int i) {
            while (root[static_cast<std::size_t>(i)] != i) i = root[static_cast<std::size_t>(i)] = root[static_cast<std::size_t>(root[static_cast<std::size_t>(i)])];
            return i;
        };
        for (const auto& face : garment_faces)
            for (int c = 1; c < 3; ++c) root[static_cast<std::size_t>(find(face[c]))] = find(face[0]);
        std::map<int, std::vector<int>> components;
        for (std::size_t f = 0; f < garment_faces.size(); ++f) components[find(garment_faces[f][0])].push_back(static_cast<int>(f));
        std::vector<std::vector<int>> component_faces;
        for (auto& item : components) component_faces.push_back(std::move(item.second));
        // Islands first (a bead welded to its cord), then whole components.
        auto closed = small_closed_pieces(surface_faces);
        for (auto& piece : small_closed_pieces(component_faces)) closed.push_back(std::move(piece));
        std::set<int> held;
        for (const auto& group : rigid_groups) held.insert(group.begin(), group.end());
        for (const auto& piece : closed) {
            if (std::any_of(piece.begin(), piece.end(), [&](int i) { return held.count(i) != 0; })) continue;
            Vec3 mean{0.0, 0.0, 0.0};
            for (const int i : piece) mean = add_vec3(mean, shift[static_cast<std::size_t>(i)]);
            mean = scale_vec3(mean, 1.0 / static_cast<double>(piece.size()));
            for (const int i : piece) shift[static_cast<std::size_t>(i)] = mean;
            held.insert(piece.begin(), piece.end());
            rigid_groups.push_back(piece);
        }
        for (std::size_t i = 0; i < count; ++i) {
            if (dot_vec3(shift[i], shift[i]) <= 1.0e-12) continue;
            rest[i] = add_vec3(rest[i], shift[i]);
            ++pulled;
        }
    }
    std::vector<double> rest_lengths;
    rest_lengths.reserve(edges.size());
    for (const auto& edge : edges)
        rest_lengths.push_back(length_vec3(sub_vec3(rest[static_cast<std::size_t>(edge.second)], rest[static_cast<std::size_t>(edge.first)])));

    // Authored stacking: each particle near another island's surface, clearly
    // on one side of it, keeps that side after the transfer.
    struct LayerRow { int particle; std::array<int, 3> triangle; std::array<double, 3> barycentric; double offset; int surface; int face; };
    std::vector<LayerRow> layer_rows;
    {
        const RefitReferenceTriangleIndex garment_index(start, garment_faces);
        const double radius = REFIT_REFERENCE_LAYER_RADIUS * scale;
        for (std::size_t i = 0; i < count; ++i) {
            std::map<int, std::pair<double, int>> nearest;
            std::map<int, std::array<double, 3>> barycentric;
            garment_index.within(start[i], radius, [&](int triangle) {
                const int surface = garment_face_surface[static_cast<std::size_t>(triangle)];
                if (surface == particle_rows[i].surface) return;
                const auto& c = garment_index.corners[static_cast<std::size_t>(triangle)];
                const auto hit = closest_triangle_point_native(start[i], c[0], c[1], c[2]);
                const auto found = nearest.find(surface);
                if (found != nearest.end() && (found->second.first < hit.distance_squared
                        || (found->second.first == hit.distance_squared && found->second.second < triangle))) return;
                nearest[surface] = {hit.distance_squared, triangle};
                barycentric[surface] = hit.barycentric;
            });
            std::vector<std::pair<std::pair<double, int>, int>> ranked;
            for (const auto& item : nearest) ranked.push_back({item.second, item.first});
            std::sort(ranked.begin(), ranked.end());
            if (ranked.size() > REFIT_REFERENCE_LAYER_PARTNERS) ranked.resize(REFIT_REFERENCE_LAYER_PARTNERS);
            for (const auto& item : ranked) {
                const double distance = std::sqrt(item.first.first);
                if (distance > radius) continue;
                const int triangle = item.first.second;
                const auto& corners = garment_faces[static_cast<std::size_t>(triangle)];
                const auto& b = barycentric.at(item.second);
                const auto& c = garment_index.corners[static_cast<std::size_t>(triangle)];
                const Vec3 normal = normalized_vec3_or_zero(face_cross(c[0], c[1], c[2]));
                if (dot_vec3(normal, normal) < 0.5) continue;
                const Vec3 point = add_vec3(add_vec3(scale_vec3(c[0], b[0]), scale_vec3(c[1], b[1])), scale_vec3(c[2], b[2]));
                const double offset = dot_vec3(sub_vec3(start[i], point), normal);
                if (std::abs(offset) < REFIT_REFERENCE_LAYER_MIN_SIDE * scale || std::abs(offset) < 0.5 * distance) continue;
                layer_rows.push_back({static_cast<int>(i), corners, b, offset, item.second, triangle});
            }
        }
    }

    // Garment pieces that were already inside the authored body (a mask inside
    // the head, a lining under the skin) keep that relation.
    std::vector<char> exempt(count, 0);
    {
        Vec3 outward;
        for (std::size_t i = 0; i < count; ++i)
            exempt[i] = authored.signed_distance(start[i], outward) < -REFIT_REFERENCE_INSIDE * scale;
    }

    // Position-based relaxation, Jacobi-averaged for order independence.
    std::vector<double> inverse_mass(count, 1.0);
    std::vector<std::vector<Vec3>> rigid_rest;
    for (const auto& group : rigid_groups) {
        std::vector<Vec3> shape;
        for (const int i : group) {
            inverse_mass[static_cast<std::size_t>(i)] = REFIT_REFERENCE_RIGID_INVERSE_MASS;
            shape.push_back(rest[static_cast<std::size_t>(i)]);
        }
        rigid_rest.push_back(std::move(shape));
    }
    const double weight = REFIT_REFERENCE_CONSTRAINT_WEIGHT;
    const double deep = REFIT_REFERENCE_DEEP_INSIDE * scale;
    const double far_outside = REFIT_REFERENCE_FAR_OUTSIDE * scale;
    std::vector<Vec3> x = rest, previous = rest, delta(count), outward(count), queried(count);
    std::vector<double> total(count), distance(count, std::numeric_limits<double>::infinity()), queried_distance(count);
    std::vector<char> known(count, 0);
    long long layer_violations = 0, body_violations = 0, body_queries = 0, reanchored = 0;
    double deepest = 0.0;
    const double layer_weight = REFIT_REFERENCE_LAYER_WEIGHT;
    const double stale = REFIT_REFERENCE_LAYER_STALE * REFIT_REFERENCE_LAYER_RADIUS * scale;

    // Skin through cloth. A garment triangle is often coarser than the body
    // under it, so a breast or knee can come out through a triangle whose
    // corners all keep their clearance. A driver vertex has come through when
    // the point of its closest garment triangle beneath it is inside the body;
    // from then on it pushes that triangle out along its normal to the
    // clearance. A hand hanging in front of a strap that lies on the hip has
    // the strap point beneath it outside the body, so it never pushes. Rows
    // also need the two to face the same way (not a lining) and the closest
    // point off the garment's open hem, where the body is beside the garment
    // rather than under it. Many outfits come with their own body through
    // them (the game presumably hides it), so where that garment point, as
    // authored, was inside the authored body, the vertex never pushes; nor do
    // pieces inside the authored body (a mask in the head).
    std::map<std::pair<int, int>, int> garment_edge_uses;
    for (const auto& face : garment_faces) for (int c = 0; c < 3; ++c) ++garment_edge_uses[std::minmax(face[c], face[(c + 1) % 3])];
    std::vector<char> hem_corner(count, 0);
    for (const auto& item : garment_edge_uses) if (item.second == 1)
        hem_corner[static_cast<std::size_t>(item.first.first)] = hem_corner[static_cast<std::size_t>(item.first.second)] = 1;
    const auto on_hem = [&](const std::array<int, 3>& face, const std::array<double, 3>& barycentric) {
        int zeros = 0, largest = 0;
        for (int c = 0; c < 3; ++c) {
            if (barycentric[c] <= 1.0e-7) ++zeros;
            if (barycentric[c] > barycentric[largest]) largest = c;
        }
        if (zeros == 2) return hem_corner[static_cast<std::size_t>(face[largest])] != 0;
        if (zeros != 1) return false;
        int a = -1, b = -1;
        for (int c = 0; c < 3; ++c) if (barycentric[c] > 1.0e-7) (a < 0 ? a : b) = face[c];
        return garment_edge_uses.at(std::minmax(a, b)) == 1;
    };
    std::vector<int> skin_faces;
    for (std::size_t f = 0; f < garment_faces.size(); ++f) {
        const auto& corners = garment_faces[f];
        if (!exempt[static_cast<std::size_t>(corners[0])] && !exempt[static_cast<std::size_t>(corners[1])]
            && !exempt[static_cast<std::size_t>(corners[2])]) skin_faces.push_back(static_cast<int>(f));
    }
    std::vector<int> skin_vertices;
    {
        std::vector<char> seen(driver.open_corners.size(), 0);
        for (std::size_t v = 0; v < driver_points.size(); ++v) {
            auto& first = seen[static_cast<std::size_t>(driver.welded[v])];
            if (first || dot_vec3(driver.vertex_normals[v], driver.vertex_normals[v]) < 0.5) continue;
            first = 1;
            skin_vertices.push_back(static_cast<int>(v));
        }
    }
    struct SkinRow { int vertex; int face; };
    std::vector<SkinRow> skin_rows;
    // Per driver vertex: 0 not through yet, 1 came through, 2 through as authored.
    std::vector<char> through(driver_points.size(), 0);
    long long authored_through = 0;
    long long skin_violations = 0;
    const double skin_reach = REFIT_REFERENCE_SKIN_REACH * scale;
    const auto anchor_of = [&](const LayerRow& row, Vec3& normal) {
        const auto& t = row.triangle;
        const Vec3 a = x[static_cast<std::size_t>(t[0])], b = x[static_cast<std::size_t>(t[1])], c = x[static_cast<std::size_t>(t[2])];
        normal = normalized_vec3_or_zero(face_cross(a, b, c));
        return add_vec3(add_vec3(scale_vec3(a, row.barycentric[0]), scale_vec3(b, row.barycentric[1])),
            scale_vec3(c, row.barycentric[2]));
    };
    const auto relax_started = std::chrono::steady_clock::now();
    for (int iteration = 0; iteration < REFIT_REFERENCE_ITERATIONS; ++iteration) {
        if (iteration % REFIT_REFERENCE_LAYER_REANCHOR == 0) {
            // Layers slide over each other where the body changes under them. A
            // particle that has moved far from its authored partner point is held
            // to the partner surface beneath it now, on a triangle facing the same
            // way (a thin band's far side faces the other way, and its side would
            // be the opposite one).
            std::vector<std::unique_ptr<RefitReferenceTriangleIndex>> partners(surfaces.size());
            for (auto& row : layer_rows) {
                Vec3 normal;
                const Vec3 relative = sub_vec3(x[static_cast<std::size_t>(row.particle)], anchor_of(row, normal));
                const Vec3 across = sub_vec3(relative, scale_vec3(normal, dot_vec3(relative, normal)));
                if (dot_vec3(across, across) <= stale * stale) continue;
                auto& partner = partners[static_cast<std::size_t>(row.surface)];
                if (!partner) {
                    std::vector<std::array<int, 3>> faces;
                    for (const int f : surface_faces[static_cast<std::size_t>(row.surface)])
                        faces.push_back(garment_faces[static_cast<std::size_t>(f)]);
                    partner = std::make_unique<RefitReferenceTriangleIndex>(x, faces);
                }
                const auto hit = partner->closest(x[static_cast<std::size_t>(row.particle)]);
                if (hit.triangle < 0) continue;
                const int face = surface_faces[static_cast<std::size_t>(row.surface)][static_cast<std::size_t>(hit.triangle)];
                const auto& c = garment_faces[static_cast<std::size_t>(face)];
                const Vec3 facing = normalized_vec3_or_zero(face_cross(x[static_cast<std::size_t>(c[0])],
                    x[static_cast<std::size_t>(c[1])], x[static_cast<std::size_t>(c[2])]));
                if (dot_vec3(facing, normal) < 0.5) continue;
                row.face = face;
                row.triangle = c;
                row.barycentric = hit.barycentric;
                ++reanchored;
            }
        }
        if (iteration % REFIT_REFERENCE_SKIN_REFRESH == 0 && !skin_faces.empty()) {
            skin_rows.clear();
            std::vector<std::array<int, 3>> faces;
            faces.reserve(skin_faces.size());
            for (const int f : skin_faces) faces.push_back(garment_faces[static_cast<std::size_t>(f)]);
            const RefitReferenceTriangleIndex cloth(x, faces);
            const auto& bounds = cloth.nodes.front();
            for (const int v : skin_vertices) {
                const Vec3& point = driver_points[static_cast<std::size_t>(v)];
                if (refit_aabb_distance_squared_native(point, bounds.minimum, bounds.maximum) > skin_reach * skin_reach) continue;
                const auto hit = cloth.closest(point);
                if (hit.triangle < 0 || hit.distance_squared > skin_reach * skin_reach) continue;
                const int face = skin_faces[static_cast<std::size_t>(hit.triangle)];
                const auto& c = garment_faces[static_cast<std::size_t>(face)];
                if (on_hem(c, hit.barycentric)) continue;
                const Vec3 normal = normalized_vec3_or_zero(face_cross(x[static_cast<std::size_t>(c[0])],
                    x[static_cast<std::size_t>(c[1])], x[static_cast<std::size_t>(c[2])]));
                if (dot_vec3(normal, driver.vertex_normals[static_cast<std::size_t>(v)]) < REFIT_REFERENCE_SKIN_FACING) continue;
                auto& state = through[static_cast<std::size_t>(v)];
                if (state == 0) {
                    // Only skin in front of the triangle can have come through it.
                    Vec3 side;
                    if (dot_vec3(sub_vec3(point, hit.point), normal) <= 0.0
                        || !(driver.signed_distance(hit.point, side) < 0.0)) continue;
                    Vec3 before{0.0, 0.0, 0.0};
                    for (int k = 0; k < 3; ++k)
                        before = add_vec3(before, scale_vec3(start[static_cast<std::size_t>(c[k])], hit.barycentric[k]));
                    state = authored.signed_distance(before, side) < -REFIT_REFERENCE_INSIDE * scale ? 2 : 1;
                    if (state == 2) ++authored_through;
                }
                if (state == 1) skin_rows.push_back({v, face});
            }
        }
        std::fill(delta.begin(), delta.end(), Vec3{0.0, 0.0, 0.0});
        std::fill(total.begin(), total.end(), 0.0);
        for (std::size_t e = 0; e < edges.size(); ++e) {
            const auto a = static_cast<std::size_t>(edges[e].first), b = static_cast<std::size_t>(edges[e].second);
            total[a] += 1.0;
            total[b] += 1.0;
            const Vec3 d = sub_vec3(x[b], x[a]);
            const double length = length_vec3(d);
            if (length <= 1.0e-12) continue;
            const double target = std::clamp(length, rest_lengths[e] * REFIT_REFERENCE_STRETCH_MIN,
                rest_lengths[e] * REFIT_REFERENCE_STRETCH_MAX);
            if (target == length) continue;
            const Vec3 correction = scale_vec3(d, (length - target) / length);
            const double sum = inverse_mass[a] + inverse_mass[b];
            delta[a] = add_vec3(delta[a], scale_vec3(correction, inverse_mass[a] / sum));
            delta[b] = sub_vec3(delta[b], scale_vec3(correction, inverse_mass[b] / sum));
        }
        layer_violations = 0;
        for (const auto& row : layer_rows) {
            const auto& t = row.triangle;
            Vec3 normal;
            const Vec3 anchor = anchor_of(row, normal);
            if (dot_vec3(normal, normal) < 0.5) continue;
            // A partner triangle turned over since the transfer has no trustworthy side.
            if (dot_vec3(normal, face_cross(rest[static_cast<std::size_t>(t[0])], rest[static_cast<std::size_t>(t[1])],
                    rest[static_cast<std::size_t>(t[2])])) <= 0.0) continue;
            const auto v = static_cast<std::size_t>(row.particle);
            const double now = dot_vec3(sub_vec3(x[v], anchor), normal);
            const double want = std::copysign(std::min(std::abs(row.offset) * REFIT_REFERENCE_LAYER_KEEP,
                REFIT_REFERENCE_LAYER_CAP * scale), row.offset);
            if (row.offset > 0.0 ? now >= want : now <= want) continue;
            ++layer_violations;
            const Vec3 push = scale_vec3(normal, want - now);
            double sum = inverse_mass[v];
            for (int k = 0; k < 3; ++k)
                sum += row.barycentric[k] * row.barycentric[k] * inverse_mass[static_cast<std::size_t>(t[k])];
            if (sum <= 0.0) sum = 1.0;
            delta[v] = add_vec3(delta[v], scale_vec3(push, layer_weight * inverse_mass[v] / sum));
            total[v] += layer_weight;
            for (int k = 0; k < 3; ++k) {
                const auto corner = static_cast<std::size_t>(t[k]);
                delta[corner] = sub_vec3(delta[corner], scale_vec3(push, layer_weight * row.barycentric[k] * inverse_mass[corner] / sum));
                total[corner] += layer_weight * row.barycentric[k];
            }
        }
        body_violations = 0;
        deepest = 0.0;
        for (std::size_t i = 0; i < count; ++i) {
            if (iteration % 2 == 0) {
                const double moved = known[i] ? length_vec3(sub_vec3(x[i], queried[i])) : 0.0;
                if (known[i] && queried_distance[i] > 0.0 && queried_distance[i] - moved > far_outside) {
                    // Still well clear of the driver: no clearance work is possible here.
                    distance[i] = queried_distance[i] - moved;
                } else {
                    distance[i] = driver.signed_distance(x[i], outward[i]);
                    queried[i] = x[i];
                    // Beside an open rim the side is unknown: ask again next time.
                    queried_distance[i] = std::isfinite(distance[i]) ? distance[i] : 0.0;
                    known[i] = 1;
                    ++body_queries;
                }
            } else {
                distance[i] += dot_vec3(sub_vec3(x[i], previous[i]), outward[i]);
            }
            if (exempt[i]) continue;
            const double need = particle_rows[i].clearance - distance[i];
            if (need <= 0.0 || distance[i] <= -deep) continue;
            ++body_violations;
            deepest = std::max(deepest, -distance[i]);
            delta[i] = add_vec3(delta[i], scale_vec3(outward[i], need * weight));
            total[i] += weight;
        }
        skin_violations = 0;
        for (const auto& row : skin_rows) {
            const auto& t = garment_faces[static_cast<std::size_t>(row.face)];
            const Vec3 a = x[static_cast<std::size_t>(t[0])], b = x[static_cast<std::size_t>(t[1])], c = x[static_cast<std::size_t>(t[2])];
            const Vec3 normal = normalized_vec3_or_zero(face_cross(a, b, c));
            if (dot_vec3(normal, normal) < 0.5) continue;
            const Vec3& point = driver_points[static_cast<std::size_t>(row.vertex)];
            const auto w = closest_triangle_point_native(point, a, b, c).barycentric;
            const Vec3 under = add_vec3(add_vec3(scale_vec3(a, w[0]), scale_vec3(b, w[1])), scale_vec3(c, w[2]));
            double clearance = 0.0, sum = 0.0;
            for (int k = 0; k < 3; ++k) {
                clearance += w[k] * particle_rows[static_cast<std::size_t>(t[k])].clearance;
                sum += w[k] * w[k] * inverse_mass[static_cast<std::size_t>(t[k])];
            }
            const double need = dot_vec3(sub_vec3(point, under), normal) + clearance;
            if (need <= 0.0 || sum <= 0.0) continue;
            ++skin_violations;
            const Vec3 push = scale_vec3(normal, need * weight / sum);
            for (int k = 0; k < 3; ++k) {
                const auto corner = static_cast<std::size_t>(t[k]);
                delta[corner] = add_vec3(delta[corner], scale_vec3(push, w[k] * inverse_mass[corner]));
                total[corner] += weight * w[k];
            }
        }
        previous = x;
        for (std::size_t i = 0; i < count; ++i) {
            delta[i] = add_vec3(delta[i], scale_vec3(sub_vec3(rest[i], x[i]), REFIT_REFERENCE_ANCHOR));
            total[i] += REFIT_REFERENCE_ANCHOR;
            x[i] = add_vec3(x[i], scale_vec3(delta[i], REFIT_REFERENCE_STEP / std::max(total[i], 1.0)));
        }
        for (std::size_t g = 0; g < rigid_groups.size(); ++g) {
            std::vector<Vec3> current;
            current.reserve(rigid_groups[g].size());
            for (const int i : rigid_groups[g]) current.push_back(x[static_cast<std::size_t>(i)]);
            const auto posed = refit_reference_rigid_pose(rigid_rest[g], current);
            for (std::size_t k = 0; k < rigid_groups[g].size(); ++k) x[static_cast<std::size_t>(rigid_groups[g][k])] = posed[k];
        }
    }
    const double relax_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - relax_started).count();

    // Publish the transfer as refit layer displacement, then masks and
    // post-refit corrections exactly as the bound fitter applies them.
    const auto masks = mesh_editor_refit_masks(refit, submeshes, residual);
    for (const auto& part : particles) {
        auto& target = layer[part.first];
        if (target.empty()) target = mesh_editor_zero_morph_layer(part.second.size());
        for (std::size_t v = 0; v < part.second.size(); ++v) {
            if (part.second[v] < 0) continue;
            const Vec3 moved = sub_vec3(x[static_cast<std::size_t>(part.second[v])], visible(part.first, v));
            target[v] = add_vec3(target[v], scale_vec3(moved, mesh_editor_refit_mask_weight(masks, part.first, v)));
        }
    }
    for (const auto& item : post_refit) {
        if (!refit.garment_submesh_indices.count(item.first)) continue;
        const auto settings = refit.garment_settings.find(item.first);
        if (settings != refit.garment_settings.end() && !settings->second.enabled) continue;
        auto& target = layer[item.first];
        if (target.empty()) target = mesh_editor_zero_morph_layer(item.second.size());
        for (std::size_t v = 0; v < target.size(); ++v)
            target[v] = add_vec3(target[v], scale_vec3(item.second[v], mesh_editor_refit_mask_weight(masks, item.first, v)));
    }
    if (weights && refit.weight_transfer) {
        // Weights go to each rigid piece, not each assembly: a chain of studs
        // that moves as one in the fit must still bend at its joins in motion.
        std::vector<std::vector<int>> pieces(static_cast<std::size_t>(units));
        for (std::size_t i = 0; i < count; ++i)
            if (particle_rows[i].unit >= 0) pieces[static_cast<std::size_t>(particle_rows[i].unit)].push_back(static_cast<int>(i));
        pieces.erase(std::remove_if(pieces.begin(), pieces.end(), [](const auto& piece) { return piece.empty(); }), pieces.end());
        for (auto& piece : small_closed_pieces(surface_faces)) pieces.push_back(std::move(piece));
        *weights = mesh_editor_refit_transfer_weights(
            morph, submeshes, driver, authored, particles, start, x, pieces, masks, scale, report);
    }
    std::size_t largest_group = 0;
    for (const auto& group : rigid_groups) largest_group = std::max(largest_group, group.size());
    long long exempt_count = 0;
    for (const char value : exempt) exempt_count += value ? 1 : 0;
    std::size_t automatic_islands = 0;
    for (const auto& item : refit.automatic_rigid_islands) automatic_islands += item.second.size();
    report << ",\"particles\":" << count << ",\"rigid_groups\":" << rigid_groups.size()
           << ",\"automatic_rigid_parts\":" << refit.automatic_rigid_parts.size()
           << ",\"automatic_rigid_islands\":" << automatic_islands
           << ",\"largest_rigid_group\":" << largest_group << ",\"split_assemblies\":" << split_assemblies
           << ",\"layer_constraints\":" << layer_rows.size()
           << ",\"remaining_layer_violations\":" << layer_violations
           << ",\"remaining_body_violations\":" << body_violations
           << ",\"skin_constraints\":" << skin_rows.size() << ",\"remaining_skin_violations\":" << skin_violations
           << ",\"skin_through_as_authored\":" << authored_through
           << ",\"pulled_to_skin\":" << pulled
           << ",\"deepest_body_violation\":" << std::setprecision(17) << deepest
           << ",\"exempt_particles\":" << exempt_count << ",\"open_driver_edges\":" << driver.open_edges.size()
           << ",\"reanchored_layer_constraints\":" << reanchored
           << ",\"reference_ray_hits\":" << field.ray_hits
           << ",\"maximum_field_displacement\":" << field.maximum_displacement
           << ",\"iterations\":" << REFIT_REFERENCE_ITERATIONS << ",\"body_queries\":" << body_queries
           << ",\"field_ms\":" << field_ms << ",\"relax_ms\":" << relax_ms
           << ",\"total_ms\":" << std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count()
           << '}';
    return report.str();
}

std::shared_ptr<const MeshRefitReferenceBodyRuntime> mesh_editor_refit_reference_from_json(const JsonValue& raw) {
    if (raw.type != JsonValue::Type::Object) throw std::runtime_error("Fit reference body must be an object");
    const auto* label = raw.get("label");
    const auto* source = raw.get("source_positions");
    const auto* fitted = raw.get("fitted_positions");
    const auto* faces = raw.get("faces");
    if ((label && label->type != JsonValue::Type::String) || !source || !fitted || !faces
        || source->type != JsonValue::Type::Array || fitted->type != JsonValue::Type::Array || faces->type != JsonValue::Type::Array
        || source->array_value.size() != fitted->array_value.size() || source->array_value.size() % 3 != 0
        || faces->array_value.size() % 3 != 0 || source->array_value.empty() || faces->array_value.empty()
        || source->array_value.size() / 3 > REFIT_REFERENCE_MAX_VERTICES)
        throw std::runtime_error("Fit reference body requires matching flat source and fitted positions and faces");
    auto reference = std::make_shared<MeshRefitReferenceBodyRuntime>();
    reference->label = label ? label->string_value : std::string();
    for (const auto* rows : {source, fitted}) {
        auto& target = rows == source ? reference->source_positions : reference->fitted_positions;
        target.reserve(rows->array_value.size() / 3);
        for (std::size_t i = 0; i < rows->array_value.size(); i += 3) {
            Vec3 point{};
            for (int axis = 0; axis < 3; ++axis) {
                const auto& value = rows->array_value[i + static_cast<std::size_t>(axis)];
                if (value.type != JsonValue::Type::Number || !std::isfinite(value.number_value))
                    throw std::runtime_error("Fit reference body positions must be finite numbers");
                point[axis] = value.number_value;
            }
            target.push_back(point);
        }
    }
    reference->faces.reserve(faces->array_value.size() / 3);
    for (std::size_t i = 0; i < faces->array_value.size(); i += 3) {
        std::array<int, 3> face{};
        for (int corner = 0; corner < 3; ++corner) {
            int index = -1;
            if (!strict_int_or(&faces->array_value[i + static_cast<std::size_t>(corner)], index) || index < 0
                || static_cast<std::size_t>(index) >= reference->source_positions.size())
                throw std::runtime_error("Fit reference body faces must reference its vertices");
            face[corner] = index;
        }
        reference->faces.push_back(face);
    }
    return reference;
}

void mesh_editor_write_refit_reference(std::ostream& out, const MeshRefitReferenceBodyRuntime& reference) {
    out << "{\"label\":";
    write_escaped(out, reference.label);
    out << ",\"source_positions\":[" << std::setprecision(17);
    for (const auto* rows : {&reference.source_positions, &reference.fitted_positions}) {
        if (rows == &reference.fitted_positions) out << "],\"fitted_positions\":[";
        for (std::size_t i = 0; i < rows->size(); ++i) {
            if (i) out << ',';
            out << (*rows)[i][0] << ',' << (*rows)[i][1] << ',' << (*rows)[i][2];
        }
    }
    out << "],\"faces\":[";
    for (std::size_t i = 0; i < reference.faces.size(); ++i) {
        if (i) out << ',';
        out << reference.faces[i][0] << ',' << reference.faces[i][1] << ',' << reference.faces[i][2];
    }
    out << "]}";
}

void mesh_editor_write_refit_reference_summary(std::ostream& out, const MeshEditorSession& session) {
    const auto* reference = session.morph && session.morph->refit ? session.morph->refit->reference_body.get() : nullptr;
    out << ",\"reference_body\":";
    if (!reference) {
        out << "null";
        return;
    }
    out << "{\"label\":";
    write_escaped(out, reference->label);
    out << ",\"vertex_count\":" << reference->source_positions.size() << ",\"face_count\":" << reference->faces.size()
        << ",\"last_fit\":" << (session.reference_refit_report.empty() ? std::string("null") : session.reference_refit_report) << '}';
}
