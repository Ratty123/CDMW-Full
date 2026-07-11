
static float decode_pac_position(std::uint16_t value, float min_value, float extent) {
    if (std::abs(extent) < 1.0e-8f) return min_value;
    return min_value + (static_cast<float>(value) / 32767.0f) * extent;
}

static Vec3 decode_pac_normal(const std::vector<char>& data, size_t rec_off, int normal_offset = 16) {
    if (normal_offset < 0 || rec_off + static_cast<size_t>(normal_offset) + 4 > data.size()) return Vec3{0.0f, 1.0f, 0.0f};
    const std::uint32_t packed = read_u32(data, rec_off + static_cast<size_t>(normal_offset));
    const std::uint32_t nx_raw = (packed >> 0) & 0x3FFu;
    const std::uint32_t ny_raw = (packed >> 10) & 0x3FFu;
    const std::uint32_t nz_raw = (packed >> 20) & 0x3FFu;
    return vec_normalize(Vec3{
        static_cast<float>(ny_raw) / 511.5f - 1.0f,
        static_cast<float>(nz_raw) / 511.5f - 1.0f,
        static_cast<float>(nx_raw) / 511.5f - 1.0f,
    });
}

struct PacVertexLayout {
    std::string name;
    int stride = 40;
    int uv_offset = 8;
    int normal_offset = 16;
};

static float triangle_area_estimate(const Vec3& a, const Vec3& b, const Vec3& c) {
    const Vec3 ab = vec_sub(b, a);
    const Vec3 ac = vec_sub(c, a);
    return std::sqrt(std::max(0.0f, vec_dot(vec_cross(ab, ac), vec_cross(ab, ac)))) * 0.5f;
}

static void evaluate_native_submesh_quality(NativeSubmesh& mesh) {
    const size_t vertex_count = mesh.positions.size();
    if (vertex_count == 0 || mesh.indices.size() < 3) {
        mesh.geometry_safe = false;
        mesh.geometry_quality_note = "empty geometry";
        mesh.geometry_quality_score = -1000.0f;
        return;
    }

    float min_u = std::numeric_limits<float>::max();
    float min_v = std::numeric_limits<float>::max();
    float max_u = -std::numeric_limits<float>::max();
    float max_v = -std::numeric_limits<float>::max();
    float abs_max = 0.0f;
    size_t finite_uvs = 0;
    for (const Vec2& uv : mesh.uvs) {
        if (!std::isfinite(uv.x) || !std::isfinite(uv.y)) continue;
        ++finite_uvs;
        min_u = std::min(min_u, uv.x);
        min_v = std::min(min_v, uv.y);
        max_u = std::max(max_u, uv.x);
        max_v = std::max(max_v, uv.y);
        abs_max = std::max(abs_max, std::max(std::abs(uv.x), std::abs(uv.y)));
    }
    mesh.uv_finite_ratio = vertex_count > 0 ? static_cast<float>(finite_uvs) / static_cast<float>(vertex_count) : 0.0f;
    if (finite_uvs > 0) {
        mesh.uv_span_u = max_u - min_u;
        mesh.uv_span_v = max_v - min_v;
        mesh.uv_abs_max = abs_max;
    }

    Vec3 min_p{std::numeric_limits<float>::max(), std::numeric_limits<float>::max(), std::numeric_limits<float>::max()};
    Vec3 max_p{-std::numeric_limits<float>::max(), -std::numeric_limits<float>::max(), -std::numeric_limits<float>::max()};
    for (const Vec3& p : mesh.positions) {
        min_p.x = std::min(min_p.x, p.x); min_p.y = std::min(min_p.y, p.y); min_p.z = std::min(min_p.z, p.z);
        max_p.x = std::max(max_p.x, p.x); max_p.y = std::max(max_p.y, p.y); max_p.z = std::max(max_p.z, p.z);
    }
    const Vec3 diag_v = vec_sub(max_p, min_p);
    const float diag = std::max(1.0e-6f, std::sqrt(std::max(0.0f, vec_dot(diag_v, diag_v))));

    const float uv_span = std::max(mesh.uv_span_u, mesh.uv_span_v);
    const float uv_edge_limit = std::max(2.0f, std::min(16.0f, std::max(uv_span, 1.0f) * 0.65f));
    size_t degenerate = 0;
    size_t outlier_edges = 0;
    size_t uv_edge_outliers = 0;
    size_t uv_degenerate = 0;
    size_t uv_triangles = 0;
    size_t triangles = 0;
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t ia = mesh.indices[i];
        const std::uint32_t ib = mesh.indices[i + 1];
        const std::uint32_t ic = mesh.indices[i + 2];
        if (ia >= vertex_count || ib >= vertex_count || ic >= vertex_count) continue;
        ++triangles;
        const Vec3& a = mesh.positions[ia];
        const Vec3& b = mesh.positions[ib];
        const Vec3& c = mesh.positions[ic];
        if (triangle_area_estimate(a, b, c) <= diag * diag * 1.0e-10f) ++degenerate;
        const float ab = std::sqrt(std::max(0.0f, vec_dot(vec_sub(a, b), vec_sub(a, b))));
        const float bc = std::sqrt(std::max(0.0f, vec_dot(vec_sub(b, c), vec_sub(b, c))));
        const float ca = std::sqrt(std::max(0.0f, vec_dot(vec_sub(c, a), vec_sub(c, a))));
        if (std::max({ab, bc, ca}) > diag * 0.62f) ++outlier_edges;
        if (ia < mesh.uvs.size() && ib < mesh.uvs.size() && ic < mesh.uvs.size()) {
            const Vec2& uva = mesh.uvs[ia];
            const Vec2& uvb = mesh.uvs[ib];
            const Vec2& uvc = mesh.uvs[ic];
            if (
                std::isfinite(uva.x) && std::isfinite(uva.y) &&
                std::isfinite(uvb.x) && std::isfinite(uvb.y) &&
                std::isfinite(uvc.x) && std::isfinite(uvc.y)
            ) {
                ++uv_triangles;
                const float uab = std::hypot(uva.x - uvb.x, uva.y - uvb.y);
                const float ubc = std::hypot(uvb.x - uvc.x, uvb.y - uvc.y);
                const float uca = std::hypot(uvc.x - uva.x, uvc.y - uva.y);
                if (std::max({uab, ubc, uca}) > uv_edge_limit) ++uv_edge_outliers;
                const float uv_area = std::abs((uvb.x - uva.x) * (uvc.y - uva.y) - (uvc.x - uva.x) * (uvb.y - uva.y)) * 0.5f;
                if (uv_area <= 1.0e-10f) ++uv_degenerate;
            }
        }
    }
    mesh.degenerate_triangle_ratio = triangles > 0 ? static_cast<float>(degenerate) / static_cast<float>(triangles) : 1.0f;
    mesh.edge_outlier_ratio = triangles > 0 ? static_cast<float>(outlier_edges) / static_cast<float>(triangles) : 1.0f;
    mesh.uv_edge_outlier_ratio = uv_triangles > 0 ? static_cast<float>(uv_edge_outliers) / static_cast<float>(uv_triangles) : 1.0f;
    mesh.uv_degenerate_triangle_ratio = uv_triangles > 0 ? static_cast<float>(uv_degenerate) / static_cast<float>(uv_triangles) : 1.0f;

    size_t valid_normals = 0;
    for (const Vec3& n : mesh.normals) {
        const float len_sq = vec_dot(n, n);
        if (std::isfinite(n.x) && std::isfinite(n.y) && std::isfinite(n.z) && len_sq > 0.25f && len_sq < 1.75f) {
            ++valid_normals;
        }
    }
    mesh.normal_valid_ratio = vertex_count > 0 ? static_cast<float>(valid_normals) / static_cast<float>(vertex_count) : 0.0f;

    float score = 0.0f;
    score += std::min<float>(static_cast<float>(triangles), 250000.0f) * 0.002f;
    score += mesh.uv_finite_ratio * 140.0f;
    score += mesh.normal_valid_ratio * 60.0f;
    score -= std::max(0.0f, uv_span - 24.0f) * 9.0f;
    score -= std::max(0.0f, mesh.uv_abs_max - 48.0f) * 4.0f;
    score -= mesh.degenerate_triangle_ratio * 220.0f;
    score -= mesh.edge_outlier_ratio * 260.0f;
    score -= mesh.uv_edge_outlier_ratio * 320.0f;
    score -= std::max(0.0f, mesh.uv_degenerate_triangle_ratio - 0.55f) * 120.0f;
    mesh.geometry_quality_score = score;

    std::ostringstream note;
    note << "layout=" << mesh.vertex_layout_name
         << " stride=" << mesh.vertex_stride
         << " uv_offset=" << mesh.uv_offset
         << " normal_offset=" << mesh.normal_offset
         << " uv_finite=" << mesh.uv_finite_ratio
         << " uv_span=" << mesh.uv_span_u << "x" << mesh.uv_span_v
         << " uv_abs_max=" << mesh.uv_abs_max
         << " uv_edge_outlier=" << mesh.uv_edge_outlier_ratio
         << " uv_degenerate=" << mesh.uv_degenerate_triangle_ratio
         << " degenerate=" << mesh.degenerate_triangle_ratio
         << " edge_outlier=" << mesh.edge_outlier_ratio
         << " normal_valid=" << mesh.normal_valid_ratio
         << " score=" << mesh.geometry_quality_score;
    mesh.geometry_quality_note = note.str();
    mesh.geometry_safe =
        mesh.uv_finite_ratio >= 0.92f
        && mesh.uv_abs_max <= 96.0f
        && std::max(mesh.uv_span_u, mesh.uv_span_v) <= 64.0f
        && mesh.uv_edge_outlier_ratio <= 0.42f
        && mesh.degenerate_triangle_ratio <= 0.28f
        && mesh.edge_outlier_ratio <= 0.22f
        && mesh.normal_valid_ratio >= 0.70f;
}

static int find_pac_section_index_start(
    const std::vector<char>& data,
    const ParSection& geom_sec,
    const std::vector<PacDescriptor>& descriptors,
    int lod,
    int after_verts
) {
    const PacDescriptor* first = nullptr;
    for (const PacDescriptor& desc : descriptors) {
        if (lod >= 0 && lod < 10 && desc.vertex_counts[static_cast<size_t>(lod)] > 0) {
            first = &desc;
            break;
        }
    }
    if (first == nullptr) return -1;
    const std::uint32_t first_vc = first->vertex_counts[static_cast<size_t>(lod)];
    for (int adj = 0; after_verts + adj + 6 <= static_cast<int>(geom_sec.size); adj += 2) {
        const int trial = after_verts + adj;
        const size_t base = static_cast<size_t>(geom_sec.offset) + trial;
        const std::uint16_t v0 = read_u16(data, base);
        const std::uint16_t v1 = read_u16(data, base + 2);
        const std::uint16_t v2 = read_u16(data, base + 4);
        if (v0 == 0 && v1 < first_vc && v2 < first_vc) return trial;
    }
    return -1;
}

static std::pair<int, int> find_pac_section_layout(
    const std::vector<char>& data,
    const ParSection& geom_sec,
    const std::vector<PacDescriptor>& descriptors,
    int lod,
    int total_indices,
    int vertex_stride
) {
    std::uint32_t total_verts = 0;
    for (const PacDescriptor& desc : descriptors) {
        total_verts += desc.vertex_counts[static_cast<size_t>(lod)];
    }
    const int primary_bytes = static_cast<int>(total_verts) * vertex_stride;
    const int index_bytes = total_indices * 2;
    if (primary_bytes + index_bytes >= static_cast<int>(geom_sec.size)) {
        return {0, primary_bytes};
    }
    const int gap = static_cast<int>(geom_sec.size) - primary_bytes - index_bytes;
    if (gap <= 0) return {0, primary_bytes};
    const int secondary_bytes = (gap / vertex_stride) * vertex_stride;
    int best_v_start = 0;
    int best_i_start = primary_bytes + secondary_bytes;
    for (int n_secondary = 0; n_secondary <= gap / vertex_stride; ++n_secondary) {
        const int v_start = n_secondary * vertex_stride;
        const int all_verts_end = v_start + primary_bytes;
        if (all_verts_end >= static_cast<int>(geom_sec.size)) break;
        const int idx_start = find_pac_section_index_start(data, geom_sec, descriptors, lod, all_verts_end);
        if (idx_start >= 0 && idx_start + index_bytes <= static_cast<int>(geom_sec.size)) {
            best_v_start = v_start;
            best_i_start = idx_start;
            break;
        }
    }
    return {best_v_start, best_i_start};
}

static std::vector<std::uint32_t> read_pac_indices(
    const std::vector<char>& data,
    const ParSection& geom_sec,
    int index_start,
    std::uint32_t index_count
) {
    std::vector<std::uint32_t> indices;
    if (index_count == 0 || index_start < 0 || static_cast<std::uint32_t>(index_start) >= geom_sec.size) return indices;
    const std::uint32_t max_count = std::min<std::uint32_t>(index_count, (geom_sec.size - static_cast<std::uint32_t>(index_start)) / 2u);
    indices.reserve(max_count);
    const size_t base = static_cast<size_t>(geom_sec.offset) + static_cast<size_t>(index_start);
    for (std::uint32_t i = 0; i < max_count; ++i) {
        indices.push_back(read_u16(data, base + static_cast<size_t>(i) * 2u));
    }
    return indices;
}

static NativeSubmesh decode_pac_submesh_vertices(
    const std::vector<char>& data,
    const ParSection& geom_sec,
    const PacDescriptor& desc,
    int vertex_start,
    std::uint32_t vertex_count,
    const std::vector<std::uint32_t>& indices,
    int source_submesh_index,
    const PacVertexLayout& layout
) {
    NativeSubmesh mesh;
    mesh.name = desc.name;
    mesh.material = desc.material.empty() ? desc.name : desc.material;
    mesh.source_submesh_index = source_submesh_index;
    mesh.source_local_submesh_index = source_submesh_index;
    mesh.vertex_layout_name = layout.name;
    mesh.vertex_stride = layout.stride;
    mesh.uv_offset = layout.uv_offset;
    mesh.normal_offset = layout.normal_offset;
    mesh.positions.reserve(vertex_count);
    mesh.uvs.reserve(vertex_count);
    mesh.normals.reserve(vertex_count);
    for (std::uint32_t vi = 0; vi < vertex_count; ++vi) {
        const size_t rec_off = static_cast<size_t>(geom_sec.offset) + static_cast<size_t>(vertex_start) + static_cast<size_t>(vi) * static_cast<size_t>(layout.stride);
        if (rec_off + static_cast<size_t>(layout.stride) > data.size()) break;
        const std::uint16_t xu = read_u16(data, rec_off);
        const std::uint16_t yu = read_u16(data, rec_off + 2);
        const std::uint16_t zu = read_u16(data, rec_off + 4);
        mesh.positions.push_back(Vec3{
            decode_pac_position(xu, desc.bbox_min.x, desc.bbox_extent.x),
            decode_pac_position(yu, desc.bbox_min.y, desc.bbox_extent.y),
            decode_pac_position(zu, desc.bbox_min.z, desc.bbox_extent.z),
        });
        mesh.source_vertex_indices.push_back(static_cast<std::int32_t>(vi));
        float u = 0.0f;
        float v = 0.0f;
        if (layout.uv_offset >= 0 && rec_off + static_cast<size_t>(layout.uv_offset) + 4 <= data.size()) {
            u = half_to_float(read_u16(data, rec_off + static_cast<size_t>(layout.uv_offset)));
            v = half_to_float(read_u16(data, rec_off + static_cast<size_t>(layout.uv_offset + 2)));
        }
        mesh.uvs.push_back(Vec2{std::isfinite(u) ? u : 0.0f, std::isfinite(v) ? v : 0.0f});
        mesh.normals.push_back(decode_pac_normal(data, rec_off, layout.normal_offset));
    }
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        const std::uint32_t a = indices[i];
        const std::uint32_t b = indices[i + 1];
        const std::uint32_t c = indices[i + 2];
        if (a < mesh.positions.size() && b < mesh.positions.size() && c < mesh.positions.size() && a != b && b != c && a != c) {
            mesh.indices.push_back(a);
            mesh.indices.push_back(b);
            mesh.indices.push_back(c);
        }
    }
    evaluate_native_submesh_quality(mesh);
    return mesh;
}

static std::vector<NativeSubmesh> parse_pac_geometry_section(
    const std::vector<char>& data,
    const std::vector<PacDescriptor>& descriptors,
    const ParSection& geom_sec,
    int lod,
    const PacVertexLayout& layout
) {
    std::vector<NativeSubmesh> output;
    if (lod < 0 || lod >= 10) return output;
    int total_indices = 0;
    for (const PacDescriptor& desc : descriptors) {
        total_indices += static_cast<int>(desc.index_counts[static_cast<size_t>(lod)]);
    }
    const auto section_layout = find_pac_section_layout(data, geom_sec, descriptors, lod, total_indices, layout.stride);
    const int vert_base = section_layout.first;
    int idx_byte_offset = section_layout.second;
    const int index_region_start = idx_byte_offset;
    std::vector<int> desc_vert_offsets;
    desc_vert_offsets.reserve(descriptors.size());
    int cursor = vert_base;
    for (const PacDescriptor& desc : descriptors) {
        desc_vert_offsets.push_back(cursor);
        cursor += static_cast<int>(desc.vertex_counts[static_cast<size_t>(lod)]) * layout.stride;
    }

    for (size_t di = 0; di < descriptors.size(); ++di) {
        const PacDescriptor& desc = descriptors[di];
        const std::uint32_t vc = desc.vertex_counts[static_cast<size_t>(lod)];
        const std::uint32_t ic = desc.index_counts[static_cast<size_t>(lod)];
        if (vc == 0 && ic == 0) continue;
        std::vector<std::uint32_t> indices = read_pac_indices(data, geom_sec, idx_byte_offset, ic);
        idx_byte_offset += static_cast<int>(ic) * 2;
        std::uint32_t owner_vc = vc;
        int owner_idx = static_cast<int>(di);
        const auto max_it = std::max_element(indices.begin(), indices.end());
        const std::uint32_t max_index = max_it == indices.end() ? 0u : *max_it;
        if (max_index >= vc) {
            for (size_t pj = 0; pj < descriptors.size(); ++pj) {
                if (pj != di && descriptors[pj].vertex_counts[static_cast<size_t>(lod)] > max_index) {
                    owner_idx = static_cast<int>(pj);
                    owner_vc = descriptors[pj].vertex_counts[static_cast<size_t>(lod)];
                    break;
                }
            }
            if (owner_idx == static_cast<int>(di)) {
                const int available_vc = std::max(0, (index_region_start - desc_vert_offsets[di]) / layout.stride);
                if (max_index < static_cast<std::uint32_t>(available_vc)) owner_vc = max_index + 1u;
            }
        }
        NativeSubmesh mesh = decode_pac_submesh_vertices(
            data,
            geom_sec,
            descriptors[static_cast<size_t>(owner_idx)],
            desc_vert_offsets[static_cast<size_t>(owner_idx)],
            owner_vc,
            indices,
            static_cast<int>(di),
            layout
        );
        mesh.name = desc.name;
        mesh.material = desc.material.empty() ? desc.name : desc.material;
        if (!mesh.positions.empty() && mesh.indices.size() >= 3) output.push_back(std::move(mesh));
    }
    return output;
}

struct PacGeometryCandidate {
    int faces = 0;
    int vertices = 0;
    int submeshes = 0;
    int geom_section_idx = 0;
    float quality_score = 0.0f;
    int unsafe_meshes = 0;
    std::string layout_name;
    std::string diagnostic;
    std::vector<NativeSubmesh> meshes;
};

static void collect_pac_geometry_candidates(
    const std::vector<char>& data,
    const std::vector<PacDescriptor>& descriptors,
    const std::map<int, ParSection>& sections,
    int lod_count,
    const std::vector<PacVertexLayout>& layouts,
    std::vector<PacGeometryCandidate>& candidates
) {
    for (int geom_section_idx : {4, 3, 2, 1}) {
        auto section = sections.find(geom_section_idx);
        if (section == sections.end()) continue;
        const int lod = 4 - geom_section_idx;
        if (lod < 0 || lod >= lod_count) continue;
        for (const PacVertexLayout& layout : layouts) {
            std::vector<NativeSubmesh> meshes = parse_pac_geometry_section(data, descriptors, section->second, lod, layout);
            int faces = 0;
            int vertices = 0;
            float quality = 0.0f;
            int unsafe = 0;
            std::ostringstream diag;
            for (const NativeSubmesh& mesh : meshes) {
                faces += static_cast<int>(mesh.indices.size() / 3u);
                vertices += static_cast<int>(mesh.positions.size());
                quality += mesh.geometry_quality_score;
                if (!mesh.geometry_safe) ++unsafe;
                if (diag.tellp() < 600) {
                    if (diag.tellp() > 0) diag << "; ";
                    diag << mesh.material << ": " << mesh.geometry_quality_note;
                }
            }
            if (meshes.empty() || faces <= 0) continue;
            candidates.push_back(PacGeometryCandidate{
                faces, vertices, static_cast<int>(meshes.size()), geom_section_idx,
                quality, unsafe, layout.name, diag.str(), std::move(meshes)
            });
            const PacGeometryCandidate& original = candidates.back();
            if (original.unsafe_meshes <= 0 || original.unsafe_meshes >= original.submeshes) continue;
            std::vector<NativeSubmesh> safe_meshes;
            int safe_faces = 0;
            int safe_vertices = 0;
            float safe_quality = 0.0f;
            for (const NativeSubmesh& mesh : original.meshes) {
                if (!mesh.geometry_safe) continue;
                safe_faces += static_cast<int>(mesh.indices.size() / 3u);
                safe_vertices += static_cast<int>(mesh.positions.size());
                safe_quality += mesh.geometry_quality_score;
                safe_meshes.push_back(mesh);
            }
            if (safe_meshes.empty()
                || safe_faces < static_cast<int>(static_cast<float>(original.faces) * 0.60f)
                || safe_quality < 140.0f) continue;
            candidates.push_back(PacGeometryCandidate{
                safe_faces, safe_vertices, static_cast<int>(safe_meshes.size()), geom_section_idx,
                safe_quality - static_cast<float>(original.unsafe_meshes) * 24.0f, 0,
                layout.name + "_filtered_safe",
                std::string("filtered unsafe native PAC submesh(es); ") + original.diagnostic,
                std::move(safe_meshes)
            });
        }
    }
}

static std::vector<NativeSubmesh> parse_pac_submeshes(const std::vector<char>& data) {
    if (data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") {
        throw std::runtime_error("selected PAC is missing a PAR header");
    }
    std::vector<char> decompressed_par = decompress_internal_par_sections(data);
    const std::vector<char>& parse_data = decompressed_par.empty() ? data : decompressed_par;
    const std::vector<ParSection> sections = parse_par_sections(parse_data);
    if (sections.empty()) {
        throw std::runtime_error("native PAC parser found no valid PAR sections");
    }
    std::map<int, ParSection> by_index;
    for (const ParSection& section : sections) by_index[section.index] = section;
    auto sec0_it = by_index.find(0);
    if (sec0_it == by_index.end()) throw std::runtime_error("PAC section 0 is missing");
    const ParSection& sec0 = sec0_it->second;
    if (static_cast<size_t>(sec0.offset) + 5 > parse_data.size()) throw std::runtime_error("PAC section 0 is truncated");
    const int n_lods = static_cast<unsigned char>(parse_data[sec0.offset + 4]);
    if (n_lods <= 0 || n_lods > 10) throw std::runtime_error("PAC LOD count is unsupported");
    const std::vector<PacDescriptor> descriptors = find_pac_descriptors(parse_data, sec0, n_lods);
    if (descriptors.empty()) throw std::runtime_error("native PAC parser found no submesh descriptors");

    std::vector<PacGeometryCandidate> candidates;
    const std::vector<PacVertexLayout> primary_vertex_layouts = {
        {"pac40_uv8_n16", 40, 8, 16},
        {"pac40_uv12_n16", 40, 12, 16},
        {"pac40_uv20_n16", 40, 20, 16},
        {"pac40_uv24_n16", 40, 24, 16},
        {"pac40_uv28_n16", 40, 28, 16},
        {"pac40_uv32_n16", 40, 32, 16},
    };
    const std::vector<PacVertexLayout> alternate_vertex_layouts = {
        {"pac32_uv8_n16", 32, 8, 16},
        {"pac32_uv12_n16", 32, 12, 16},
        {"pac32_uv20_n16", 32, 20, 16},
        {"pac32_uv24_n16", 32, 24, 16},
        {"pac36_uv8_n16", 36, 8, 16},
        {"pac36_uv12_n16", 36, 12, 16},
        {"pac36_uv20_n16", 36, 20, 16},
        {"pac36_uv24_n16", 36, 24, 16},
        {"pac36_uv28_n16", 36, 28, 16},
        {"pac44_uv8_n16", 44, 8, 16},
        {"pac44_uv12_n16", 44, 12, 16},
        {"pac44_uv20_n16", 44, 20, 16},
        {"pac44_uv24_n16", 44, 24, 16},
        {"pac44_uv28_n16", 44, 28, 16},
        {"pac44_uv32_n16", 44, 32, 16},
        {"pac44_uv36_n16", 44, 36, 16},
        {"pac48_uv8_n16", 48, 8, 16},
        {"pac48_uv12_n16", 48, 12, 16},
        {"pac48_uv20_n16", 48, 20, 16},
        {"pac48_uv24_n16", 48, 24, 16},
        {"pac48_uv28_n16", 48, 28, 16},
        {"pac48_uv32_n16", 48, 32, 16},
        {"pac48_uv36_n16", 48, 36, 16},
        {"pac48_uv40_n16", 48, 40, 16},
    };
    collect_pac_geometry_candidates(parse_data, descriptors, by_index, n_lods, primary_vertex_layouts, candidates);
    const bool has_confident_primary = std::any_of(candidates.begin(), candidates.end(), [](const PacGeometryCandidate& candidate) {
        return candidate.unsafe_meshes == 0 && candidate.quality_score >= 140.0f;
    });
    if (!has_confident_primary) {
        collect_pac_geometry_candidates(parse_data, descriptors, by_index, n_lods, alternate_vertex_layouts, candidates);
    }
    if (candidates.empty()) throw std::runtime_error("native PAC parser found no renderable geometry sections");
    std::sort(candidates.begin(), candidates.end(), [](const PacGeometryCandidate& a, const PacGeometryCandidate& b) {
        const bool a_safe = a.unsafe_meshes == 0;
        const bool b_safe = b.unsafe_meshes == 0;
        if (a_safe != b_safe) return a_safe;
        if (std::abs(a.quality_score - b.quality_score) > 1.0f) return a.quality_score > b.quality_score;
        if (a.faces != b.faces) return a.faces > b.faces;
        if (a.vertices != b.vertices) return a.vertices > b.vertices;
        if (a.submeshes != b.submeshes) return a.submeshes > b.submeshes;
        return a.geom_section_idx > b.geom_section_idx;
    });
    const PacGeometryCandidate& best = candidates.front();
    if (best.unsafe_meshes > 0 || best.quality_score < 60.0f) {
        std::ostringstream reason;
        reason << "native geometry unsafe: section=" << best.geom_section_idx
               << " layout=" << best.layout_name
               << " unsafe_meshes=" << best.unsafe_meshes
               << " quality=" << best.quality_score
               << " diagnostics=" << best.diagnostic;
        throw std::runtime_error(reason.str());
    }
    return std::move(candidates.front().meshes);
}

struct NativeMeshParseResult {
    std::vector<NativeSubmesh> meshes;
    std::string parser;
    int lod_count = 0;
};

static float dequantize_u16(std::uint16_t value, float minimum, float maximum) {
    return minimum + (static_cast<float>(value) / 65535.0f) * (maximum - minimum);
}

static float dequantize_i16(std::int16_t value, float minimum, float maximum) {
    return minimum + ((static_cast<float>(value) + 32768.0f) / 65536.0f) * (maximum - minimum);
}

static void compute_missing_normals(NativeSubmesh& mesh) {
    if (mesh.normals.size() == mesh.positions.size()) return;
    mesh.normals.assign(mesh.positions.size(), Vec3{});
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t ia = mesh.indices[i];
        const std::uint32_t ib = mesh.indices[i + 1];
        const std::uint32_t ic = mesh.indices[i + 2];
        if (ia >= mesh.positions.size() || ib >= mesh.positions.size() || ic >= mesh.positions.size()) continue;
        const Vec3 ab = vec_sub(mesh.positions[ib], mesh.positions[ia]);
        const Vec3 ac = vec_sub(mesh.positions[ic], mesh.positions[ia]);
        const Vec3 normal = vec_cross(ab, ac);
        if (vec_dot(normal, normal) <= 1.0e-18f) continue;
        mesh.normals[ia] = vec_add(mesh.normals[ia], normal);
        mesh.normals[ib] = vec_add(mesh.normals[ib], normal);
        mesh.normals[ic] = vec_add(mesh.normals[ic], normal);
    }
    for (Vec3& normal : mesh.normals) {
        normal = vec_normalize(normal);
    }
}

static bool native_mesh_renderable(const NativeSubmesh& mesh) {
    if (mesh.positions.size() < 3 || mesh.indices.size() < 3) return false;
    Vec3 min_v{1.0e30f, 1.0e30f, 1.0e30f};
    Vec3 max_v{-1.0e30f, -1.0e30f, -1.0e30f};
    for (const Vec3& p : mesh.positions) {
        min_v.x = std::min(min_v.x, p.x); min_v.y = std::min(min_v.y, p.y); min_v.z = std::min(min_v.z, p.z);
        max_v.x = std::max(max_v.x, p.x); max_v.y = std::max(max_v.y, p.y); max_v.z = std::max(max_v.z, p.z);
    }
    const float dim = std::max({max_v.x - min_v.x, max_v.y - min_v.y, max_v.z - min_v.z});
    if (dim <= 1.0e-9f || !std::isfinite(dim)) return false;
    int non_degenerate = 0;
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t ia = mesh.indices[i];
        const std::uint32_t ib = mesh.indices[i + 1];
        const std::uint32_t ic = mesh.indices[i + 2];
        if (ia >= mesh.positions.size() || ib >= mesh.positions.size() || ic >= mesh.positions.size()) continue;
        const Vec3 normal = vec_cross(vec_sub(mesh.positions[ib], mesh.positions[ia]), vec_sub(mesh.positions[ic], mesh.positions[ia]));
        if (vec_dot(normal, normal) > 1.0e-18f && ++non_degenerate >= 1) return true;
    }
    return false;
}

static void finalize_native_meshes(std::vector<NativeSubmesh>& meshes) {
    std::vector<NativeSubmesh> filtered;
    filtered.reserve(meshes.size());
    for (NativeSubmesh& mesh : meshes) {
        if (!native_mesh_renderable(mesh)) continue;
        compute_missing_normals(mesh);
        filtered.push_back(std::move(mesh));
    }
    meshes = std::move(filtered);
}

static void complete_native_meshes_without_filtering(std::vector<NativeSubmesh>& meshes) {
    for (NativeSubmesh& mesh : meshes) {
        compute_missing_normals(mesh);
        evaluate_native_submesh_quality(mesh);
    }
}
