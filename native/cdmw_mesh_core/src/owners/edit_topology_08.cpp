std::vector<int> choose_static_donor_indices_native(
    const std::vector<Vec3>& orig_vertices,
    const std::vector<Vec3>& new_vertices,
    bool& sequence_alignment_used,
    bool& sequence_alignment_fallback
) {
    sequence_alignment_used = false;
    sequence_alignment_fallback = false;
    if (new_vertices.empty()) {
        return {};
    }
    if (orig_vertices.empty()) {
        return std::vector<int>(new_vertices.size(), 0);
    }

    std::vector<int> donor_indices;
    try {
        donor_indices = align_static_donor_vertex_sequences(orig_vertices, new_vertices);
        sequence_alignment_used = true;
    } catch (const std::exception&) {
        donor_indices.assign(new_vertices.size(), -1);
        sequence_alignment_fallback = true;
    }

    std::map<std::tuple<long long, long long, long long>, std::vector<int>> rounded_map;
    for (std::size_t orig_index = 0; orig_index < orig_vertices.size(); ++orig_index) {
        rounded_map[static_donor_rounded_key(orig_vertices[orig_index])].push_back(static_cast<int>(orig_index));
    }

    const auto spatial = build_static_donor_spatial_hash(orig_vertices);
    for (std::size_t new_index = 0; new_index < new_vertices.size(); ++new_index) {
        if (0 <= donor_indices[new_index] && static_cast<std::size_t>(donor_indices[new_index]) < orig_vertices.size()) {
            continue;
        }
        const auto exact_hits = rounded_map.find(static_donor_rounded_key(new_vertices[new_index]));
        if (exact_hits != rounded_map.end() && !exact_hits->second.empty()) {
            int best_index = exact_hits->second.front();
            int best_delta = std::abs(best_index - static_cast<int>(new_index));
            for (const int candidate : exact_hits->second) {
                const int delta = std::abs(candidate - static_cast<int>(new_index));
                if (delta < best_delta) {
                    best_index = candidate;
                    best_delta = delta;
                }
            }
            donor_indices[new_index] = best_index;
            continue;
        }
        donor_indices[new_index] = nearest_static_donor_point_index(
            new_vertices[new_index],
            orig_vertices,
            spatial.first,
            spatial.second
        );
    }
    return donor_indices;
}

std::vector<SubmeshStaticDonorIndicesResult> run_static_donor_indices(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshStaticDonorIndicesResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        const std::vector<Vec3> original_vertices =
            vertices_from_binary_or_json(item, "original_vertices_binary", "original_vertices");
        const std::vector<Vec3> new_vertices =
            vertices_from_binary_or_json(item, "new_vertices_binary", "new_vertices");
        SubmeshStaticDonorIndicesResult result;
        result.index = index;
        result.original_vertex_count = static_cast<int>(original_vertices.size());
        result.new_vertex_count = static_cast<int>(new_vertices.size());
        result.donor_indices_path = string_or(item.get("donor_indices_output_path"), "");
        result.donor_indices = choose_static_donor_indices_native(
            original_vertices,
            new_vertices,
            result.sequence_alignment_used,
            result.sequence_alignment_fallback
        );
        if (static_cast<int>(result.donor_indices.size()) != result.new_vertex_count) {
            throw std::runtime_error("static donor index count mismatch");
        }
        write_int_binary_file(result.donor_indices_path, result.donor_indices);
        results.push_back(std::move(result));
    }
    return results;
}

using PoseMatrix4 = std::array<double, 16>;
