// Find one depth/pitch pose for a sparse, body-centred rigid assembly. Dense
// plates and real cloth attachments retain their existing placement rules.
std::vector<Vec3> mesh_editor_refit_rigid_pose(
    const std::vector<Vec3>& samples, const std::vector<std::array<std::size_t, 3>>& faces,
    std::size_t vertex_count, const Vec3& lateral, const Vec3& up,
    const RefitSpatialIndexNative& body, const std::map<int, std::vector<Vec3>>& driver,
    const RefitSpatialIndexNative& obstacles, const std::map<int, std::vector<Vec3>>& surfaces,
    double diagonal, double clearance, double influence
) {
    if (samples.empty() || faces.empty() || influence <= 0.0) return samples;
    Vec3 depth{lateral[1]*up[2]-lateral[2]*up[1], lateral[2]*up[0]-lateral[0]*up[2],
               lateral[0]*up[1]-lateral[1]*up[0]};
    const double depth_length = length_vec3(depth);
    if (depth_length < .5) return samples;
    depth = scale_vec3(depth, 1.0 / depth_length);
    Vec3 centre{}, outward{};
    double left = std::numeric_limits<double>::infinity(), right = -left, bottom = left, top = -left;
    for (std::size_t i = 0; i < vertex_count; ++i) {
        centre = add_vec3(centre, samples[i]);
        const double x = dot_vec3(samples[i], lateral), y = dot_vec3(samples[i], up);
        left = std::min(left, x); right = std::max(right, x);
        bottom = std::min(bottom, y); top = std::max(top, y);
        long long tests = 0;
        const auto hit = closest_refit_binding_native(samples[i], body, tests);
        outward = add_vec3(outward, refit_binding_face_normal_native(hit, driver));
    }
    centre = scale_vec3(centre, 1.0 / vertex_count);
    double projected_area = 0.0;
    for (const auto& face : faces) {
        const auto a = sub_vec3(samples[face[1]], samples[face[0]]);
        const auto b = sub_vec3(samples[face[2]], samples[face[0]]);
        projected_area += .5 * std::abs(dot_vec3(depth, Vec3{
            a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]}));
    }
    if (right-left < diagonal*.01 || top-bottom < diagonal*.01
        || projected_area > (right-left)*(top-bottom)*.65
        || std::abs(dot_vec3(outward, depth)) < length_vec3(outward)*.3) return samples;
    if (dot_vec3(outward, depth) < 0.0) depth = scale_vec3(depth, -1.0);
    struct Pose { double angle = 0.0, shift = 0.0, score = 0.0; std::size_t coverage = 0; };
    const auto evaluate = [&](double angle) {
        Pose pose; pose.angle = angle;
        pose.shift = -std::numeric_limits<double>::infinity();
        const std::array<double,4> rotation{std::cos(angle*.5), lateral[0]*std::sin(angle*.5),
                                          lateral[1]*std::sin(angle*.5), lateral[2]*std::sin(angle*.5)};
        std::vector<std::pair<double,double>> limits;
        for (const auto& source : samples) {
            const Vec3 point = add_vec3(centre, refit_rotate_quaternion_native(rotation, sub_vec3(source, centre)));
            double front = -std::numeric_limits<double>::infinity();
            for (const auto& hit : refit_surface_line_hits_native(point, depth, diagonal*2.0, body)) {
                const Vec3 normal = refit_binding_face_normal_native(hit, driver);
                const double facing = dot_vec3(normal, depth);
                if (facing < .15) continue;
                const Vec3 surface = mesh_editor_refit_driver_point(hit, driver);
                front = std::max(front, dot_vec3(sub_vec3(surface, point), depth) + clearance / facing);
            }
            if (!std::isfinite(front)) continue;
            double outer = front;
            for (const auto& hit : refit_surface_line_hits_native(point, depth, diagonal*2.0, obstacles)) {
                const double facing = dot_vec3(refit_binding_face_normal_native(hit, surfaces), depth);
                if (facing < .15) continue;
                outer = std::max(outer, dot_vec3(sub_vec3(mesh_editor_refit_driver_point(hit, surfaces), point), depth)
                    + clearance / facing);
            }
            // A hanging assembly rests its lower ornaments against the chest;
            // its upper strands can bridge the neck's concave transition.
            const double height = std::clamp((top-dot_vec3(source,up))/(top-bottom), 0.0, 1.0);
            limits.emplace_back(front, .1 + 4.0*std::pow(height,4.0));
            pose.shift = std::max(pose.shift, outer);
        }
        pose.coverage = limits.size();
        if (limits.empty()) { pose.score = std::numeric_limits<double>::infinity(); return pose; }
        double total = 0.0;
        for (const auto& limit : limits) {
            pose.score += limit.second*(pose.shift-limit.first)*(pose.shift-limit.first);
            total += limit.second;
        }
        pose.score /= total;
        return pose;
    };
    const Pose baseline = evaluate(0.0);
    if (!baseline.coverage || !std::isfinite(baseline.score)) return samples;
    Pose best = baseline;
    const auto consider = [&](double degrees) {
        const auto candidate = evaluate(degrees * 3.14159265358979323846 / 180.0);
        if (candidate.coverage >= baseline.coverage*.95 && candidate.score < best.score)
            best = candidate;
    };
    for (int step = -10; step <= 10; ++step) consider(step*2.5);
    const double coarse = best.angle * 180.0 / 3.14159265358979323846;
    for (int step = -4; step <= 4; ++step) consider(std::clamp(coarse+step*.5, -25.0, 25.0));
    if (best.score >= baseline.score*.98) best = baseline;
    const double angle = best.angle * influence;
    const auto blended = evaluate(angle);
    const double shift = blended.shift * influence;
    const std::array<double,4> rotation{std::cos(angle*.5), lateral[0]*std::sin(angle*.5),
                                      lateral[1]*std::sin(angle*.5), lateral[2]*std::sin(angle*.5)};
    std::vector<Vec3> result;
    for (const auto& point : samples)
        result.push_back(add_vec3(add_vec3(centre, scale_vec3(depth, shift)),
            refit_rotate_quaternion_native(rotation, sub_vec3(point, centre))));
    return result;
}
