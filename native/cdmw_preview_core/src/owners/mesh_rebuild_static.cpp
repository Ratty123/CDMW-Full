
struct PamFullVertex {
    std::int64_t source_offset = -1;
    std::array<double, 3> position{};
    bool has_uv = false;
    std::array<double, 2> uv{};
};

struct PamFullFace {
    std::uint32_t a = 0;
    std::uint32_t b = 0;
    std::uint32_t c = 0;
};

struct PamFullSubmesh {
    int index = 0;
    int desc_offset = 0;
    int vertex_count = 0;
    int face_count = 0;
    int stride = 0;
    int original_vertex_base = 0;
    int original_vertex_count = 0;
    std::string texture;
    std::string material;
    int original_vertex_total = 0;
    int original_index_total = 0;
    std::array<float, 6> old_bbox{};
    std::array<float, 6> new_bbox{};
    std::vector<PamFullVertex> vertices;
    std::vector<PamFullFace> faces;
};

struct PamFullRebuildPlan {
    std::string kind;
    int geom_offset = 0;
    int old_geom_end = 0;
    int stride = 0;
    int scan_start = -1;
    int idx_base = -1;
    int vertex_end = -1;
    std::array<double, 3> bbox_min{};
    std::array<double, 3> bbox_max{};
    std::vector<PamFullSubmesh> submeshes;
};

static void append_bytes(std::vector<char>& out, const std::vector<char>& data, size_t start, size_t end) {
    if (start > end || end > data.size()) throw std::runtime_error("native PAM full rebuild slice is outside the file");
    out.insert(out.end(), data.begin() + static_cast<std::ptrdiff_t>(start), data.begin() + static_cast<std::ptrdiff_t>(end));
}

static bool float_close(float value, float target, float tolerance = 1.0e-3f) {
    return std::isfinite(value) && std::fabs(value - target) <= tolerance;
}

static void append_f32_bytes(std::vector<char>& out, float value) {
    std::uint32_t raw = 0;
    std::memcpy(&raw, &value, sizeof(raw));
    append_u32_le(out, raw);
}

static std::vector<char> pack_u32_pair(std::uint32_t a, std::uint32_t b) {
    std::vector<char> out;
    out.reserve(8);
    append_u32_le(out, a);
    append_u32_le(out, b);
    return out;
}

static std::vector<char> pack_bbox6(const std::array<float, 6>& values) {
    std::vector<char> out;
    out.reserve(24);
    for (float value : values) append_f32_bytes(out, value);
    return out;
}

static void replace_all_in_region(std::vector<char>& data, size_t start, size_t end, const std::vector<char>& old_bytes, const std::vector<char>& new_bytes) {
    if (old_bytes.empty() || old_bytes == new_bytes || start >= end || old_bytes.size() > end - start) return;
    for (size_t pos = start; pos + old_bytes.size() <= end;) {
        if (std::equal(old_bytes.begin(), old_bytes.end(), data.begin() + static_cast<std::ptrdiff_t>(pos))) {
            data.erase(data.begin() + static_cast<std::ptrdiff_t>(pos), data.begin() + static_cast<std::ptrdiff_t>(pos + old_bytes.size()));
            data.insert(data.begin() + static_cast<std::ptrdiff_t>(pos), new_bytes.begin(), new_bytes.end());
            pos += new_bytes.size();
            end = end - old_bytes.size() + new_bytes.size();
        } else {
            ++pos;
        }
    }
}

static void sync_pam_geom_size_header_native(std::vector<char>& result, const std::vector<char>& original, int geom_offset, int old_geom_end, int new_geom_end) {
    constexpr size_t header_geom_size_offset = 0x40u;
    if (
        result.size() < header_geom_size_offset + 4u
        || original.size() < header_geom_size_offset + 4u
        || geom_offset <= 0
        || old_geom_end < geom_offset
        || new_geom_end < geom_offset
    ) {
        return;
    }
    const int original_geom_len = old_geom_end - geom_offset;
    const int original_header_geom_len = static_cast<int>(read_u32(original, header_geom_size_offset));
    if (original_header_geom_len != original_geom_len) return;
    write_u32_le(result, header_geom_size_offset, static_cast<std::uint32_t>(new_geom_end - geom_offset));
}

static void sync_pam_header_mirrors_native(std::vector<char>& result, const std::vector<PamFullSubmesh>& submeshes, int geom_offset) {
    const size_t mesh_count = submeshes.size();
    const size_t region_start = 0x410u + mesh_count * 0x218u;
    const size_t region_end = std::min<size_t>(std::max<size_t>(static_cast<size_t>(std::max(0, geom_offset)), region_start), result.size());
    if (region_start >= region_end) return;

    for (const PamFullSubmesh& submesh : submeshes) {
        const std::uint32_t original_indices = static_cast<std::uint32_t>(std::max(0, submesh.original_index_total));
        const std::uint32_t new_indices = static_cast<std::uint32_t>(std::max(0, submesh.face_count * 3));
        const std::uint32_t original_vertices = static_cast<std::uint32_t>(std::max(0, submesh.original_vertex_total));
        const std::uint32_t new_vertices = static_cast<std::uint32_t>(std::max(0, submesh.vertex_count));

        std::vector<char> old_count_bbox;
        old_count_bbox.reserve(28);
        append_u32_le(old_count_bbox, original_indices);
        const std::vector<char> old_bbox = pack_bbox6(submesh.old_bbox);
        old_count_bbox.insert(old_count_bbox.end(), old_bbox.begin(), old_bbox.end());
        std::vector<char> new_count_bbox;
        new_count_bbox.reserve(28);
        append_u32_le(new_count_bbox, new_indices);
        const std::vector<char> new_bbox = pack_bbox6(submesh.new_bbox);
        new_count_bbox.insert(new_count_bbox.end(), new_bbox.begin(), new_bbox.end());
        replace_all_in_region(result, region_start, region_end, old_count_bbox, new_count_bbox);
        replace_all_in_region(result, region_start, region_end, old_bbox, new_bbox);

        for (size_t off = region_start; off + 28u <= region_end; off += 4u) {
            const std::uint32_t count = read_u32(result, off);
            bool bbox_matches = count == original_indices;
            for (int axis = 0; axis < 6 && bbox_matches; ++axis) {
                bbox_matches = float_close(read_f32(result, off + 4u + static_cast<size_t>(axis) * 4u), submesh.old_bbox[static_cast<size_t>(axis)]);
            }
            if (!bbox_matches) continue;
            write_u32_le(result, off, new_indices);
            for (int axis = 0; axis < 6; ++axis) {
                write_f32_le(result, off + 4u + static_cast<size_t>(axis) * 4u, submesh.new_bbox[static_cast<size_t>(axis)]);
            }
        }
        for (size_t off = region_start; off + 24u <= region_end; off += 4u) {
            bool bbox_matches = true;
            for (int axis = 0; axis < 6 && bbox_matches; ++axis) {
                bbox_matches = float_close(read_f32(result, off + static_cast<size_t>(axis) * 4u), submesh.old_bbox[static_cast<size_t>(axis)]);
            }
            if (!bbox_matches) continue;
            for (int axis = 0; axis < 6; ++axis) {
                write_f32_le(result, off + static_cast<size_t>(axis) * 4u, submesh.new_bbox[static_cast<size_t>(axis)]);
            }
        }

        const std::vector<char> old_pair = pack_u32_pair(original_vertices, original_indices);
        const std::vector<char> new_pair = pack_u32_pair(new_vertices, new_indices);
        if (old_pair == new_pair) continue;
        for (const std::string& anchor_text : {submesh.texture, submesh.material}) {
            if (anchor_text.empty()) continue;
            const std::vector<char> anchor(anchor_text.begin(), anchor_text.end());
            for (size_t cursor = region_start; cursor + anchor.size() <= region_end;) {
                auto it = std::search(result.begin() + static_cast<std::ptrdiff_t>(cursor), result.begin() + static_cast<std::ptrdiff_t>(region_end), anchor.begin(), anchor.end());
                if (it == result.begin() + static_cast<std::ptrdiff_t>(region_end)) break;
                const size_t pos = static_cast<size_t>(std::distance(result.begin(), it));
                if (pos >= 8u && pos - 8u >= region_start && pos <= result.size()) {
                    const size_t pair_off = pos - 8u;
                    if (std::equal(old_pair.begin(), old_pair.end(), result.begin() + static_cast<std::ptrdiff_t>(pair_off))) {
                        std::copy(new_pair.begin(), new_pair.end(), result.begin() + static_cast<std::ptrdiff_t>(pair_off));
                    }
                }
                cursor = pos + anchor.size();
            }
        }
    }
}

static PamFullRebuildPlan load_pam_full_rebuild_plan(const fs::path& table_path) {
    std::ifstream in(table_path);
    if (!in) throw std::runtime_error("could not open PAM full rebuild table");
    PamFullRebuildPlan plan;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        const std::vector<std::string> fields = split_tab_row(line);
        if (fields.empty()) continue;
        if (fields[0] == "header") {
            plan.kind = fields.size() > 1 ? fields[1] : "";
            plan.geom_offset = parse_int_field(fields, 2, 0);
            plan.old_geom_end = parse_int_field(fields, 3, 0);
            plan.stride = parse_int_field(fields, 4, 0);
            plan.scan_start = parse_int_field(fields, 5, -1);
            plan.idx_base = parse_int_field(fields, 6, -1);
            plan.vertex_end = parse_int_field(fields, 7, -1);
            plan.bbox_min = {parse_double_field(fields, 8), parse_double_field(fields, 9), parse_double_field(fields, 10)};
            plan.bbox_max = {parse_double_field(fields, 11), parse_double_field(fields, 12), parse_double_field(fields, 13)};
        } else if (fields[0] == "submesh") {
            const int index = parse_int_field(fields, 1, -1);
            if (index < 0) throw std::runtime_error("PAM full rebuild table has invalid submesh index");
            if (static_cast<size_t>(index) >= plan.submeshes.size()) plan.submeshes.resize(static_cast<size_t>(index) + 1u);
            PamFullSubmesh& submesh = plan.submeshes[static_cast<size_t>(index)];
            submesh.index = index;
            submesh.desc_offset = parse_int_field(fields, 2, 0);
            submesh.vertex_count = parse_int_field(fields, 3, 0);
            submesh.face_count = parse_int_field(fields, 4, 0);
            submesh.stride = parse_int_field(fields, 5, 0);
            submesh.original_vertex_base = parse_int_field(fields, 6, 0);
            submesh.original_vertex_count = parse_int_field(fields, 7, 0);
            submesh.texture = fields.size() > 8 ? fields[8] : "";
            submesh.material = fields.size() > 9 ? fields[9] : "";
            submesh.original_vertex_total = parse_int_field(fields, 10, 0);
            submesh.original_index_total = parse_int_field(fields, 11, 0);
            for (int i = 0; i < 6; ++i) submesh.old_bbox[static_cast<size_t>(i)] = static_cast<float>(parse_double_field(fields, 12u + static_cast<size_t>(i), 0.0));
            for (int i = 0; i < 6; ++i) submesh.new_bbox[static_cast<size_t>(i)] = static_cast<float>(parse_double_field(fields, 18u + static_cast<size_t>(i), 0.0));
            submesh.vertices.resize(static_cast<size_t>(std::max(0, submesh.vertex_count)));
            submesh.faces.resize(static_cast<size_t>(std::max(0, submesh.face_count)));
        } else if (fields[0] == "vertex") {
            const int submesh_index = parse_int_field(fields, 1, -1);
            const int vertex_index = parse_int_field(fields, 2, -1);
            if (submesh_index < 0 || vertex_index < 0 || static_cast<size_t>(submesh_index) >= plan.submeshes.size()) {
                throw std::runtime_error("PAM full vertex row references an invalid submesh");
            }
            PamFullSubmesh& submesh = plan.submeshes[static_cast<size_t>(submesh_index)];
            if (static_cast<size_t>(vertex_index) >= submesh.vertices.size()) throw std::runtime_error("PAM full vertex row references an invalid vertex");
            PamFullVertex& vertex = submesh.vertices[static_cast<size_t>(vertex_index)];
            vertex.source_offset = parse_i64_field(fields, 3, -1);
            vertex.position = {parse_double_field(fields, 4), parse_double_field(fields, 5), parse_double_field(fields, 6)};
            vertex.has_uv = parse_int_field(fields, 7, 0) != 0;
            vertex.uv = {parse_double_field(fields, 8), parse_double_field(fields, 9)};
        } else if (fields[0] == "face") {
            const int submesh_index = parse_int_field(fields, 1, -1);
            const int face_index = parse_int_field(fields, 2, -1);
            if (submesh_index < 0 || face_index < 0 || static_cast<size_t>(submesh_index) >= plan.submeshes.size()) {
                throw std::runtime_error("PAM full face row references an invalid submesh");
            }
            PamFullSubmesh& submesh = plan.submeshes[static_cast<size_t>(submesh_index)];
            if (static_cast<size_t>(face_index) >= submesh.faces.size()) throw std::runtime_error("PAM full face row references an invalid face");
            submesh.faces[static_cast<size_t>(face_index)] = PamFullFace{
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 3, 0))),
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 4, 0))),
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 5, 0))),
            };
        }
    }
    if (plan.kind.empty() || plan.geom_offset <= 0 || plan.old_geom_end < plan.geom_offset) {
        throw std::runtime_error("PAM full rebuild table is missing a valid header");
    }
    return plan;
}

static std::vector<char> make_pam_template_record(const std::vector<char>& original, const PamFullVertex& vertex, int stride) {
    if (stride <= 0) throw std::runtime_error("PAM full rebuild has invalid vertex stride");
    std::vector<char> record(static_cast<size_t>(stride), 0);
    if (vertex.source_offset >= 0) {
        const size_t source_offset = static_cast<size_t>(vertex.source_offset);
        if (source_offset + static_cast<size_t>(stride) <= original.size()) {
            std::copy(
                original.begin() + static_cast<std::ptrdiff_t>(source_offset),
                original.begin() + static_cast<std::ptrdiff_t>(source_offset + stride),
                record.begin()
            );
        }
    }
    return record;
}

static void pack_static_vertex_record_native(
    std::vector<char>& record,
    int stride,
    const PamFullVertex& vertex,
    const std::array<double, 3>& bmin,
    const std::array<double, 3>& bmax
) {
    if (static_cast<int>(record.size()) < stride) record.resize(static_cast<size_t>(stride), 0);
    write_u16_le(record, 0u, quantize_static_u16_double(vertex.position[0], bmin[0], bmax[0]));
    write_u16_le(record, 2u, quantize_static_u16_double(vertex.position[1], bmin[1], bmax[1]));
    write_u16_le(record, 4u, quantize_static_u16_double(vertex.position[2], bmin[2], bmax[2]));
    if (stride >= 12 && vertex.has_uv) {
        write_u16_le(record, 8u, float_to_half(static_cast<float>(vertex.uv[0])));
        write_u16_le(record, 10u, float_to_half(static_cast<float>(vertex.uv[1])));
    }
}

static std::vector<char> rebuild_pam_full_native(const std::vector<char>& original, const PamFullRebuildPlan& plan) {
    const bool combined = plan.kind == "combined";
    const bool scan = plan.kind == "scan_combined";
    const bool backward = plan.kind == "backward_scan_combined";
    const bool local = plan.kind == "local";
    if (!combined && !scan && !backward && !local) throw std::runtime_error("unsupported PAM full rebuild layout");
    const int write_start = scan ? plan.scan_start : plan.geom_offset;
    if (write_start <= 0 || static_cast<size_t>(write_start) > original.size()) throw std::runtime_error("PAM full rebuild write start is invalid");

    std::vector<char> result(original.begin(), original.begin() + static_cast<std::ptrdiff_t>(write_start));
    write_f32_le(result, 0x14u, static_cast<float>(plan.bbox_min[0]));
    write_f32_le(result, 0x18u, static_cast<float>(plan.bbox_min[1]));
    write_f32_le(result, 0x1Cu, static_cast<float>(plan.bbox_min[2]));
    write_f32_le(result, 0x20u, static_cast<float>(plan.bbox_max[0]));
    write_f32_le(result, 0x24u, static_cast<float>(plan.bbox_max[1]));
    write_f32_le(result, 0x28u, static_cast<float>(plan.bbox_max[2]));

    std::vector<char> geom_data;
    std::vector<char> index_data;
    int vertex_cursor = 0;
    int index_cursor = 0;
    int current_voff = 0;

    for (const PamFullSubmesh& submesh : plan.submeshes) {
        if (submesh.desc_offset < 0 || static_cast<size_t>(submesh.desc_offset) + 16u > result.size()) {
            throw std::runtime_error("PAM full rebuild descriptor offset is outside the preserved header");
        }
        write_u32_le(result, static_cast<size_t>(submesh.desc_offset), static_cast<std::uint32_t>(submesh.vertex_count));
        write_u32_le(result, static_cast<size_t>(submesh.desc_offset) + 4u, static_cast<std::uint32_t>(submesh.face_count * 3));
        if (local) {
            write_u32_le(result, static_cast<size_t>(submesh.desc_offset) + 8u, static_cast<std::uint32_t>(current_voff));
            write_u32_le(result, static_cast<size_t>(submesh.desc_offset) + 12u, 0u);
            for (const PamFullVertex& vertex : submesh.vertices) {
                std::vector<char> record = make_pam_template_record(original, vertex, submesh.stride);
                pack_static_vertex_record_native(record, submesh.stride, vertex, plan.bbox_min, plan.bbox_max);
                geom_data.insert(geom_data.end(), record.begin(), record.end());
            }
            for (const PamFullFace& face : submesh.faces) {
                if (face.a >= static_cast<std::uint32_t>(submesh.vertex_count) || face.b >= static_cast<std::uint32_t>(submesh.vertex_count) || face.c >= static_cast<std::uint32_t>(submesh.vertex_count)) {
                    throw std::runtime_error("PAM full rebuild face references an out-of-range vertex");
                }
                append_u16_le(geom_data, static_cast<std::uint16_t>(face.a));
                append_u16_le(geom_data, static_cast<std::uint16_t>(face.b));
                append_u16_le(geom_data, static_cast<std::uint16_t>(face.c));
            }
            current_voff += submesh.vertex_count * submesh.stride + submesh.face_count * 6;
        } else {
            write_u32_le(result, static_cast<size_t>(submesh.desc_offset) + 8u, static_cast<std::uint32_t>(vertex_cursor));
            write_u32_le(result, static_cast<size_t>(submesh.desc_offset) + 12u, static_cast<std::uint32_t>(index_cursor));
            for (const PamFullVertex& vertex : submesh.vertices) {
                std::vector<char> record = make_pam_template_record(original, vertex, submesh.stride);
                pack_static_vertex_record_native(record, submesh.stride, vertex, plan.bbox_min, plan.bbox_max);
                geom_data.insert(geom_data.end(), record.begin(), record.end());
            }
            for (const PamFullFace& face : submesh.faces) {
                if (face.a >= static_cast<std::uint32_t>(submesh.vertex_count) || face.b >= static_cast<std::uint32_t>(submesh.vertex_count) || face.c >= static_cast<std::uint32_t>(submesh.vertex_count)) {
                    throw std::runtime_error("PAM full rebuild face references an out-of-range vertex");
                }
                append_u16_le(index_data, static_cast<std::uint16_t>(face.a + static_cast<std::uint32_t>(vertex_cursor)));
                append_u16_le(index_data, static_cast<std::uint16_t>(face.b + static_cast<std::uint32_t>(vertex_cursor)));
                append_u16_le(index_data, static_cast<std::uint16_t>(face.c + static_cast<std::uint32_t>(vertex_cursor)));
            }
            vertex_cursor += submesh.vertex_count;
            index_cursor += submesh.face_count * 3;
        }
    }

    int new_geom_end = plan.geom_offset;
    if (combined || scan) {
        result.insert(result.end(), geom_data.begin(), geom_data.end());
        result.insert(result.end(), index_data.begin(), index_data.end());
        new_geom_end = plan.geom_offset + static_cast<int>(geom_data.size() + index_data.size());
    } else if (backward) {
        if (plan.vertex_end < 0 || plan.idx_base < plan.vertex_end || plan.old_geom_end < plan.idx_base) {
            throw std::runtime_error("PAM backward-scan full rebuild padding is invalid");
        }
        result.insert(result.end(), geom_data.begin(), geom_data.end());
        append_bytes(result, original, static_cast<size_t>(plan.vertex_end), static_cast<size_t>(plan.idx_base));
        result.insert(result.end(), index_data.begin(), index_data.end());
        new_geom_end = plan.geom_offset + static_cast<int>(geom_data.size() + static_cast<size_t>(plan.idx_base - plan.vertex_end) + index_data.size());
    } else {
        result.insert(result.end(), geom_data.begin(), geom_data.end());
        new_geom_end = plan.geom_offset + static_cast<int>(geom_data.size());
    }

    sync_pam_geom_size_header_native(result, original, plan.geom_offset, plan.old_geom_end, new_geom_end);
    append_bytes(result, original, static_cast<size_t>(plan.old_geom_end), original.size());
    sync_pam_header_mirrors_native(result, plan.submeshes, plan.geom_offset);
    return result;
}

struct PamlodFullPlan {
    int geom_offset = 0;
    int old_lod0_end = 0;
    int stride = 0;
    int vertex_base = 0;
    std::array<double, 3> bbox_min{};
    std::array<double, 3> bbox_max{};
    std::vector<PamFullSubmesh> submeshes;
};

static PamlodFullPlan load_pamlod_full_rebuild_plan(const fs::path& table_path) {
    std::ifstream in(table_path);
    if (!in) throw std::runtime_error("could not open PAMLOD full rebuild table");
    PamlodFullPlan plan;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        const std::vector<std::string> fields = split_tab_row(line);
        if (fields.empty()) continue;
        if (fields[0] == "header") {
            const std::string kind = fields.size() > 1 ? fields[1] : "";
            if (kind != "pamlod_lod0_single" && kind != "pamlod_lod0") throw std::runtime_error("unsupported PAMLOD full rebuild table");
            plan.geom_offset = parse_int_field(fields, 2, 0);
            plan.old_lod0_end = parse_int_field(fields, 3, 0);
            plan.stride = parse_int_field(fields, 4, 0);
            plan.vertex_base = parse_int_field(fields, 5, 0);
            plan.bbox_min = {parse_double_field(fields, 6), parse_double_field(fields, 7), parse_double_field(fields, 8)};
            plan.bbox_max = {parse_double_field(fields, 9), parse_double_field(fields, 10), parse_double_field(fields, 11)};
        } else if (fields[0] == "submesh") {
            PamFullSubmesh submesh;
            submesh.index = parse_int_field(fields, 1, -1);
            submesh.desc_offset = parse_int_field(fields, 2, 0);
            submesh.vertex_count = parse_int_field(fields, 3, 0);
            submesh.face_count = parse_int_field(fields, 4, 0);
            submesh.original_vertex_count = parse_int_field(fields, 5, 0);
            submesh.stride = plan.stride;
            if (submesh.index < 0) throw std::runtime_error("PAMLOD full rebuild submesh row has an invalid index");
            if (static_cast<size_t>(submesh.index) >= plan.submeshes.size()) {
                plan.submeshes.resize(static_cast<size_t>(submesh.index) + 1u);
            }
            submesh.vertices.resize(static_cast<size_t>(std::max(0, submesh.vertex_count)));
            submesh.faces.resize(static_cast<size_t>(std::max(0, submesh.face_count)));
            plan.submeshes[static_cast<size_t>(submesh.index)] = std::move(submesh);
        } else if (fields[0] == "vertex") {
            const int submesh_index = parse_int_field(fields, 1, -1);
            const int vertex_index = parse_int_field(fields, 2, -1);
            if (submesh_index < 0 || static_cast<size_t>(submesh_index) >= plan.submeshes.size()) {
                throw std::runtime_error("PAMLOD full vertex row references an invalid submesh");
            }
            PamFullSubmesh& submesh = plan.submeshes[static_cast<size_t>(submesh_index)];
            if (vertex_index < 0 || static_cast<size_t>(vertex_index) >= submesh.vertices.size()) {
                throw std::runtime_error("PAMLOD full vertex row references an invalid vertex");
            }
            PamFullVertex& vertex = submesh.vertices[static_cast<size_t>(vertex_index)];
            vertex.source_offset = parse_i64_field(fields, 3, -1);
            vertex.position = {parse_double_field(fields, 4), parse_double_field(fields, 5), parse_double_field(fields, 6)};
            vertex.has_uv = parse_int_field(fields, 7, 0) != 0;
            vertex.uv = {parse_double_field(fields, 8), parse_double_field(fields, 9)};
        } else if (fields[0] == "face") {
            const int submesh_index = parse_int_field(fields, 1, -1);
            const int face_index = parse_int_field(fields, 2, -1);
            if (submesh_index < 0 || static_cast<size_t>(submesh_index) >= plan.submeshes.size()) {
                throw std::runtime_error("PAMLOD full face row references an invalid submesh");
            }
            PamFullSubmesh& submesh = plan.submeshes[static_cast<size_t>(submesh_index)];
            if (face_index < 0 || static_cast<size_t>(face_index) >= submesh.faces.size()) {
                throw std::runtime_error("PAMLOD full face row references an invalid face");
            }
            submesh.faces[static_cast<size_t>(face_index)] = PamFullFace{
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 3, 0))),
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 4, 0))),
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 5, 0))),
            };
        }
    }
    if (plan.geom_offset <= 0 || plan.old_lod0_end < plan.geom_offset || plan.stride <= 0 || plan.vertex_base <= 0) {
        throw std::runtime_error("PAMLOD full rebuild table is missing a valid header");
    }
    if (plan.submeshes.empty()) {
        throw std::runtime_error("PAMLOD full rebuild table has no LOD0 entries");
    }
    return plan;
}

static std::vector<char> rebuild_pamlod_lod0_full_native(const std::vector<char>& original, const PamlodFullPlan& plan) {
    if (static_cast<size_t>(plan.vertex_base) > original.size() || static_cast<size_t>(plan.old_lod0_end) > original.size()) {
        throw std::runtime_error("PAMLOD full rebuild offsets are outside the file");
    }
    std::vector<char> result(original.begin(), original.begin() + static_cast<std::ptrdiff_t>(plan.vertex_base));
    write_f32_le(result, 0x10u, static_cast<float>(plan.bbox_min[0]));
    write_f32_le(result, 0x14u, static_cast<float>(plan.bbox_min[1]));
    write_f32_le(result, 0x18u, static_cast<float>(plan.bbox_min[2]));
    write_f32_le(result, 0x1Cu, static_cast<float>(plan.bbox_max[0]));
    write_f32_le(result, 0x20u, static_cast<float>(plan.bbox_max[1]));
    write_f32_le(result, 0x24u, static_cast<float>(plan.bbox_max[2]));
    std::vector<char> geom_data;
    std::vector<char> index_data;
    int vertex_cursor = 0;
    int index_cursor = 0;
    for (const PamFullSubmesh& submesh : plan.submeshes) {
        if (submesh.desc_offset < 0 || static_cast<size_t>(submesh.desc_offset) + 16u > result.size()) {
            throw std::runtime_error("PAMLOD full rebuild descriptor offset is outside the header");
        }
        write_u32_le(result, static_cast<size_t>(submesh.desc_offset), static_cast<std::uint32_t>(submesh.vertex_count));
        write_u32_le(result, static_cast<size_t>(submesh.desc_offset) + 4u, static_cast<std::uint32_t>(submesh.face_count * 3));
        write_u32_le(result, static_cast<size_t>(submesh.desc_offset) + 8u, static_cast<std::uint32_t>(vertex_cursor));
        write_u32_le(result, static_cast<size_t>(submesh.desc_offset) + 12u, static_cast<std::uint32_t>(index_cursor));
        for (const PamFullVertex& vertex : submesh.vertices) {
            std::vector<char> record = make_pam_template_record(original, vertex, plan.stride);
            pack_static_vertex_record_native(record, plan.stride, vertex, plan.bbox_min, plan.bbox_max);
            geom_data.insert(geom_data.end(), record.begin(), record.end());
        }
        for (const PamFullFace& face : submesh.faces) {
            if (face.a >= static_cast<std::uint32_t>(submesh.vertex_count) || face.b >= static_cast<std::uint32_t>(submesh.vertex_count) || face.c >= static_cast<std::uint32_t>(submesh.vertex_count)) {
                throw std::runtime_error("PAMLOD full rebuild face references an out-of-range vertex");
            }
            append_u16_le(index_data, static_cast<std::uint16_t>(face.a));
            append_u16_le(index_data, static_cast<std::uint16_t>(face.b));
            append_u16_le(index_data, static_cast<std::uint16_t>(face.c));
        }
        vertex_cursor += submesh.vertex_count;
        index_cursor += submesh.face_count * 3;
    }
    result.insert(result.end(), geom_data.begin(), geom_data.end());
    result.insert(result.end(), index_data.begin(), index_data.end());
    append_bytes(result, original, static_cast<size_t>(plan.old_lod0_end), original.size());
    return result;
}
