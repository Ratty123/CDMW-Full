static constexpr size_t kPatHeaderSize = 48u;
static constexpr size_t kPatVertexStride = 32u;
static constexpr size_t kPatDrawStride = 16u;

static size_t pat_checked_add(size_t left, size_t right, const char* label) {
    if (right > std::numeric_limits<size_t>::max() - left) {
        throw std::runtime_error(std::string("PAT ") + label + " offset overflow");
    }
    return left + right;
}

static size_t pat_checked_multiply(size_t left, size_t right, const char* label) {
    if (left != 0u && right > std::numeric_limits<size_t>::max() / left) {
        throw std::runtime_error(std::string("PAT ") + label + " size overflow");
    }
    return left * right;
}

static void pat_require_range(const std::vector<char>& data, size_t offset, size_t size, const char* label) {
    if (offset > data.size() || size > data.size() - offset) {
        throw std::runtime_error(std::string("PAT ") + label + " exceeds payload bounds");
    }
}

static std::vector<std::uint32_t> read_pat_u32_table(
    const std::vector<char>& data,
    size_t offset,
    size_t count,
    const char* label
) {
    pat_require_range(data, offset, pat_checked_multiply(count, 4u, label), label);
    std::vector<std::uint32_t> values;
    values.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        values.push_back(read_u32(data, offset + index * 4u));
    }
    return values;
}

static void require_pat_monotonic(
    const std::vector<std::uint32_t>& values,
    const char* label,
    bool starts_at_zero
) {
    if (starts_at_zero && !values.empty() && values.front() != 0u) {
        throw std::runtime_error(std::string("PAT ") + label + " must start at zero");
    }
    for (size_t index = 1; index < values.size(); ++index) {
        if (values[index - 1u] > values[index]) {
            throw std::runtime_error(std::string("PAT ") + label + " must be monotonic");
        }
    }
}

static std::vector<std::string> extract_pat_printable_strings(
    const std::vector<char>& data,
    size_t start
) {
    std::vector<std::string> values;
    std::string current;
    for (size_t offset = std::min(start, data.size()); offset <= data.size(); ++offset) {
        const bool printable = offset < data.size()
            && static_cast<unsigned char>(data[offset]) >= 32u
            && static_cast<unsigned char>(data[offset]) <= 126u;
        if (printable) {
            current.push_back(data[offset]);
            continue;
        }
        if (current.size() >= 4u) values.push_back(current);
        current.clear();
        if (values.size() >= 512u) break;
    }
    return values;
}

static std::string pat_token_through_marker(const std::string& value, const std::string& marker) {
    const std::string lowered = lower_copy(value);
    const size_t marker_offset = lowered.find(marker);
    if (marker_offset == std::string::npos) return {};
    size_t start = marker_offset;
    while (start > 0u) {
        const char candidate = value[start - 1u];
        const bool allowed = std::isalnum(static_cast<unsigned char>(candidate)) != 0
            || candidate == '_' || candidate == '-' || candidate == '.' || candidate == '/';
        if (!allowed) break;
        --start;
    }
    return value.substr(start, marker_offset + marker.size() - start);
}

static std::vector<std::string> pat_material_names(const std::vector<std::string>& strings) {
    std::vector<std::string> names;
    std::set<std::string> seen;
    for (const std::string& value : strings) {
        std::string name = pat_token_through_marker(value, "_mat");
        if (name.empty()) continue;
        const std::string key = lower_copy(name);
        if (seen.insert(key).second) names.push_back(std::move(name));
    }
    return names;
}

static NativeSubmesh build_pat_draw_mesh(
    const std::vector<char>& data,
    size_t vertex_start,
    std::uint32_t lod_vertex_count,
    size_t index_start,
    std::uint32_t lod_index_count,
    size_t draw_offset,
    int draw_index,
    const Vec3& bbox_min,
    const Vec3& bbox_max,
    const std::vector<std::string>& materials
) {
    NativeSubmesh mesh;
    const std::uint32_t material_id = read_u32(data, draw_offset);
    const std::uint32_t flags = read_u32(data, draw_offset + 4u);
    const std::uint32_t first_index = read_u32(data, draw_offset + 8u);
    const std::uint32_t index_count = read_u32(data, draw_offset + 12u);
    if (first_index > lod_index_count || index_count > lod_index_count - first_index) {
        throw std::runtime_error("PAT draw record exceeds its LOD index range");
    }

    mesh.name = "pat_lod0_draw" + std::to_string(draw_index);
    mesh.material = material_id < materials.size()
        ? materials[material_id]
        : "material_" + std::to_string(material_id);
    mesh.source_submesh_index = draw_index;
    mesh.source_local_submesh_index = draw_index;
    mesh.vertex_layout_name = "pat_u16_bbox_half_uv";
    mesh.vertex_stride = static_cast<int>(kPatVertexStride);
    mesh.uv_offset = 12;
    mesh.normal_offset = -1;
    mesh.geometry_quality_note = "PAT draw flags=" + std::to_string(flags);

    std::vector<std::uint32_t> source_indices;
    source_indices.reserve(index_count);
    std::set<std::uint32_t> unique_indices;
    for (std::uint32_t offset = 0; offset < index_count; ++offset) {
        const std::uint32_t source_index = read_u16(
            data,
            index_start + static_cast<size_t>(first_index + offset) * 2u);
        if (source_index >= lod_vertex_count) {
            throw std::runtime_error("PAT draw references a vertex outside LOD 0");
        }
        source_indices.push_back(source_index);
        unique_indices.insert(source_index);
    }

    std::unordered_map<std::uint32_t, std::uint32_t> source_to_local;
    for (std::uint32_t source_index : unique_indices) {
        const size_t record_offset = pat_checked_add(
            vertex_start,
            pat_checked_multiply(source_index, kPatVertexStride, "vertex"),
            "vertex");
        pat_require_range(data, record_offset, kPatVertexStride, "vertex record");
        source_to_local[source_index] = static_cast<std::uint32_t>(mesh.positions.size());
        mesh.positions.push_back(Vec3{
            dequantize_u16(read_u16(data, record_offset), bbox_min.x, bbox_max.x),
            dequantize_u16(read_u16(data, record_offset + 2u), bbox_min.y, bbox_max.y),
            dequantize_u16(read_u16(data, record_offset + 4u), bbox_min.z, bbox_max.z),
        });
        mesh.uvs.push_back(Vec2{
            half_to_float(read_u16(data, record_offset + 12u)),
            half_to_float(read_u16(data, record_offset + 14u)),
        });
        mesh.source_vertex_indices.push_back(static_cast<std::int32_t>(source_index));
    }
    for (size_t offset = 0; offset + 2u < source_indices.size(); offset += 3u) {
        mesh.indices.push_back(source_to_local.at(source_indices[offset]));
        mesh.indices.push_back(source_to_local.at(source_indices[offset + 1u]));
        mesh.indices.push_back(source_to_local.at(source_indices[offset + 2u]));
    }
    compute_missing_normals(mesh);
    evaluate_native_submesh_quality(mesh);
    return mesh;
}

static NativeMeshParseResult parse_pat_submeshes(const std::vector<char>& data) {
    pat_require_range(data, 0u, kPatHeaderSize, "header");
    if (std::memcmp(data.data(), "PAR ", 4u) != 0) {
        throw std::runtime_error("PAT magic is not 'PAR '");
    }
    const Vec3 bbox_min{read_f32(data, 16u), read_f32(data, 20u), read_f32(data, 24u)};
    const Vec3 bbox_max{read_f32(data, 28u), read_f32(data, 32u), read_f32(data, 36u)};
    const std::uint32_t lod_count_raw = read_u32(data, 40u);
    if (lod_count_raw == 0u || lod_count_raw > 16u) throw std::runtime_error("PAT LOD count is invalid");
    const size_t lod_count = static_cast<size_t>(lod_count_raw);

    const std::vector<std::uint32_t> vertex_counts = read_pat_u32_table(data, 48u, lod_count, "vertex table");
    require_pat_monotonic(vertex_counts, "vertex table", false);
    const size_t vertex_start = pat_checked_add(48u, lod_count * 4u, "vertex table");
    const size_t vertex_end = pat_checked_add(
        vertex_start,
        pat_checked_multiply(vertex_counts.back(), kPatVertexStride, "vertex buffer"),
        "vertex buffer");
    pat_require_range(data, vertex_start, vertex_end - vertex_start, "vertex buffer");

    const std::vector<std::uint32_t> index_offsets = read_pat_u32_table(
        data, vertex_end, lod_count + 1u, "index table");
    require_pat_monotonic(index_offsets, "index table", true);
    const size_t index_start = pat_checked_add(vertex_end, (lod_count + 1u) * 4u, "index table");
    const size_t index_end = pat_checked_add(
        index_start,
        pat_checked_multiply(index_offsets.back(), 2u, "index buffer"),
        "index buffer");
    pat_require_range(data, index_start, index_end - index_start, "index buffer");

    const std::vector<std::uint32_t> draw_offsets = read_pat_u32_table(
        data, index_end, lod_count + 1u, "draw table");
    require_pat_monotonic(draw_offsets, "draw table", true);
    const size_t draw_start = pat_checked_add(index_end, (lod_count + 1u) * 4u, "draw table");
    const size_t draw_end = pat_checked_add(
        draw_start,
        pat_checked_multiply(draw_offsets.back(), kPatDrawStride, "draw buffer"),
        "draw buffer");
    pat_require_range(data, draw_start, draw_end - draw_start, "draw buffer");

    const std::vector<std::string> materials = pat_material_names(extract_pat_printable_strings(data, draw_end));
    std::vector<NativeSubmesh> meshes;
    const std::uint32_t lod_index_count = index_offsets[1u] - index_offsets[0u];
    for (std::uint32_t draw = draw_offsets[0u]; draw < draw_offsets[1u]; ++draw) {
        NativeSubmesh mesh = build_pat_draw_mesh(
            data,
            vertex_start,
            vertex_counts[0u],
            index_start + static_cast<size_t>(index_offsets[0u]) * 2u,
            lod_index_count,
            draw_start + static_cast<size_t>(draw) * kPatDrawStride,
            static_cast<int>(draw - draw_offsets[0u]),
            bbox_min,
            bbox_max,
            materials);
        if (native_mesh_renderable(mesh)) meshes.push_back(std::move(mesh));
    }
    return NativeMeshParseResult{std::move(meshes), "native_pat_lod0", static_cast<int>(lod_count)};
}
