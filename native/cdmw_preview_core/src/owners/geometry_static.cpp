
struct RawPamEntry {
    int index = 0;
    std::uint32_t vertex_count = 0;
    std::uint32_t index_count = 0;
    std::uint32_t vertex_element_offset = 0;
    std::uint32_t index_element_offset = 0;
    std::string texture_name;
    std::string material_name;
};

static constexpr int kPamSubmeshTableOffset = 1040;
static constexpr int kPamSubmeshStride = 536;
static constexpr int kPamHeaderMeshCountOffset = 16;
static constexpr int kPamHeaderBboxMinOffset = 20;
static constexpr int kPamHeaderBboxMaxOffset = 32;
static constexpr int kPamHeaderGeomOffset = 60;
static constexpr int kPamGlobalVertexBase = 3068;
static constexpr int kPamGlobalIndexOffset = 104512;
static constexpr int kPamTextureNameOffset = 16;
static constexpr int kPamMaterialNameOffset = 272;
static constexpr int kPamNameMaxLength = 256;
static constexpr int kPamlodHeaderLodCountOffset = 0;
static constexpr int kPamlodHeaderGeomOffset = 4;
static constexpr int kPamlodHeaderBboxMinOffset = 16;
static constexpr int kPamlodHeaderBboxMaxOffset = 28;
static constexpr int kPamlodEntryTableOffset = 80;

static const std::array<int, 16> kPamCandidateStrides = {
    6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 36, 40
};
static const std::array<int, 16> kPamGlobalVertexBaseCandidates = {
    kPamGlobalVertexBase, 0, 256, 512, 1024, 1536, 2048, 2560,
    2816, 3328, 3584, 4096, 4608, 5120, 6144, 7168
};

static Vec3 read_vec3_f32(const std::vector<char>& data, size_t offset) {
    return Vec3{read_f32(data, offset), read_f32(data, offset + 4), read_f32(data, offset + 8)};
}

static std::vector<RawPamEntry> read_pam_entries(const std::vector<char>& data, int mesh_count) {
    std::vector<RawPamEntry> entries;
    for (int i = 0; i < mesh_count; ++i) {
        const size_t off = static_cast<size_t>(kPamSubmeshTableOffset) + static_cast<size_t>(i) * kPamSubmeshStride;
        if (off + kPamSubmeshStride > data.size()) break;
        entries.push_back(RawPamEntry{
            i,
            read_u32(data, off),
            read_u32(data, off + 4),
            read_u32(data, off + 8),
            read_u32(data, off + 12),
            read_c_string(data, off + kPamTextureNameOffset, kPamNameMaxLength),
            read_c_string(data, off + kPamMaterialNameOffset, kPamNameMaxLength),
        });
    }
    return entries;
}

static bool pam_uses_combined_layout(const std::vector<RawPamEntry>& entries) {
    if (entries.size() <= 1) return false;
    std::uint32_t expected_vertex_offset = 0;
    std::uint32_t expected_index_offset = 0;
    for (const RawPamEntry& entry : entries) {
        if (entry.vertex_element_offset != expected_vertex_offset || entry.index_element_offset != expected_index_offset) return false;
        expected_vertex_offset += entry.vertex_count;
        expected_index_offset += entry.index_count;
    }
    return true;
}

static bool indices_fit_vertex_count(
    const std::vector<char>& data,
    size_t index_offset,
    std::uint32_t index_count,
    std::uint32_t vertex_count
) {
    if (index_offset + static_cast<size_t>(index_count) * 2u > data.size()) return false;
    for (std::uint32_t i = 0; i < index_count; ++i) {
        if (read_u16(data, index_offset + static_cast<size_t>(i) * 2u) >= vertex_count) return false;
    }
    return true;
}

static NativeSubmesh parse_quantized_pam_mesh(
    const std::vector<char>& data,
    const RawPamEntry& raw,
    size_t vertex_base,
    size_t index_offset,
    int stride,
    const Vec3& bbox_min,
    const Vec3& bbox_max
) {
    NativeSubmesh mesh;
    mesh.name = raw.texture_name.empty() ? raw.material_name : raw.texture_name;
    mesh.material = raw.material_name.empty() ? raw.texture_name : raw.material_name;
    mesh.source_submesh_index = raw.index;
    mesh.source_local_submesh_index = raw.index;
    if (vertex_base >= data.size() || index_offset + static_cast<size_t>(raw.index_count) * 2u > data.size()) return mesh;
    std::vector<std::uint32_t> source_indices;
    source_indices.reserve(raw.index_count);
    std::set<std::uint32_t> unique_indices;
    for (std::uint32_t i = 0; i < raw.index_count; ++i) {
        std::uint32_t index = read_u16(data, index_offset + static_cast<size_t>(i) * 2u);
        source_indices.push_back(index);
        unique_indices.insert(index);
    }
    std::unordered_map<std::uint32_t, std::uint32_t> source_to_local;
    for (std::uint32_t source_index : unique_indices) {
        source_to_local[source_index] = static_cast<std::uint32_t>(source_to_local.size());
    }
    for (std::uint32_t source_index : unique_indices) {
        const size_t voff = vertex_base + static_cast<size_t>(source_index) * static_cast<size_t>(stride);
        if (voff + 6 > data.size()) break;
        mesh.positions.push_back(Vec3{
            dequantize_u16(read_u16(data, voff), bbox_min.x, bbox_max.x),
            dequantize_u16(read_u16(data, voff + 2), bbox_min.y, bbox_max.y),
            dequantize_u16(read_u16(data, voff + 4), bbox_min.z, bbox_max.z),
        });
        mesh.source_vertex_indices.push_back(static_cast<std::int32_t>(source_index));
        if (stride >= 12 && voff + 12 <= data.size()) {
            mesh.uvs.push_back(Vec2{
                half_to_float(read_u16(data, voff + 8)),
                half_to_float(read_u16(data, voff + 10)),
            });
        } else {
            mesh.uvs.push_back(Vec2{});
        }
    }
    for (size_t i = 0; i + 2 < source_indices.size(); i += 3) {
        auto a = source_to_local.find(source_indices[i]);
        auto b = source_to_local.find(source_indices[i + 1]);
        auto c = source_to_local.find(source_indices[i + 2]);
        if (a == source_to_local.end() || b == source_to_local.end() || c == source_to_local.end()) continue;
        mesh.indices.push_back(a->second);
        mesh.indices.push_back(b->second);
        mesh.indices.push_back(c->second);
    }
    return mesh;
}

static NativeSubmesh parse_global_pam_mesh_at(
    const std::vector<char>& data,
    const RawPamEntry& raw,
    int geom_offset,
    const Vec3& bbox_min,
    const Vec3& bbox_max,
    size_t index_offset,
    int global_vertex_base
) {
    NativeSubmesh mesh;
    mesh.name = raw.texture_name.empty() ? raw.material_name : raw.texture_name;
    mesh.material = raw.material_name.empty() ? raw.texture_name : raw.material_name;
    mesh.source_submesh_index = raw.index;
    mesh.source_local_submesh_index = raw.index;
    if (index_offset + static_cast<size_t>(raw.index_count) * 2u > data.size()) return mesh;
    std::vector<std::uint32_t> source_indices;
    source_indices.reserve(raw.index_count);
    std::set<std::uint32_t> unique_indices;
    for (std::uint32_t i = 0; i < raw.index_count; ++i) {
        std::uint32_t index = read_u16(data, index_offset + static_cast<size_t>(i) * 2u);
        source_indices.push_back(index);
        unique_indices.insert(index);
    }
    std::unordered_map<std::uint32_t, std::uint32_t> source_to_local;
    for (std::uint32_t source_index : unique_indices) {
        source_to_local[source_index] = static_cast<std::uint32_t>(source_to_local.size());
    }
    for (std::uint32_t source_index : unique_indices) {
        const int vertex_index = static_cast<int>(source_index) - global_vertex_base;
        if (vertex_index < 0) continue;
        const size_t voff = static_cast<size_t>(geom_offset) + static_cast<size_t>(vertex_index) * 6u;
        if (voff + 6 > data.size()) break;
        mesh.positions.push_back(Vec3{
            dequantize_i16(read_i16(data, voff), bbox_min.x, bbox_max.x),
            dequantize_i16(read_i16(data, voff + 2), bbox_min.y, bbox_max.y),
            dequantize_i16(read_i16(data, voff + 4), bbox_min.z, bbox_max.z),
        });
        mesh.uvs.push_back(Vec2{});
        mesh.source_vertex_indices.push_back(static_cast<std::int32_t>(source_index));
    }
    for (size_t i = 0; i + 2 < source_indices.size(); i += 3) {
        auto a = source_to_local.find(source_indices[i]);
        auto b = source_to_local.find(source_indices[i + 1]);
        auto c = source_to_local.find(source_indices[i + 2]);
        if (a == source_to_local.end() || b == source_to_local.end() || c == source_to_local.end()) continue;
        mesh.indices.push_back(a->second);
        mesh.indices.push_back(b->second);
        mesh.indices.push_back(c->second);
    }
    return mesh;
}

static float mesh_parse_score(const NativeSubmesh& mesh, const RawPamEntry& raw) {
    if (!native_mesh_renderable(mesh)) return -1.0e30f;
    std::set<std::uint32_t> referenced;
    int non_degenerate = 0;
    float max_edge2 = 0.0f;
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t ia = mesh.indices[i];
        const std::uint32_t ib = mesh.indices[i + 1];
        const std::uint32_t ic = mesh.indices[i + 2];
        if (ia >= mesh.positions.size() || ib >= mesh.positions.size() || ic >= mesh.positions.size()) continue;
        referenced.insert(ia); referenced.insert(ib); referenced.insert(ic);
        const Vec3 ab = vec_sub(mesh.positions[ib], mesh.positions[ia]);
        const Vec3 ac = vec_sub(mesh.positions[ic], mesh.positions[ia]);
        if (vec_dot(vec_cross(ab, ac), vec_cross(ab, ac)) > 1.0e-18f) ++non_degenerate;
        max_edge2 = std::max({max_edge2, vec_dot(ab, ab), vec_dot(ac, ac), vec_dot(vec_sub(mesh.positions[ic], mesh.positions[ib]), vec_sub(mesh.positions[ic], mesh.positions[ib]))});
    }
    const float face_ratio = static_cast<float>(mesh.indices.size() / 3u) / static_cast<float>(std::max<std::uint32_t>(1, raw.index_count / 3u));
    const float ref_ratio = static_cast<float>(referenced.size()) / static_cast<float>(std::max<size_t>(1, mesh.positions.size()));
    const float nondeg_ratio = static_cast<float>(non_degenerate) / static_cast<float>(std::max<size_t>(1, mesh.indices.size() / 3u));
    return face_ratio * 4.0f + ref_ratio * 3.0f + nondeg_ratio * 2.0f - std::sqrt(std::max(0.0f, max_edge2)) * 0.35f;
}

static std::vector<int> pam_global_index_offset_candidates(
    const std::vector<char>& data,
    int geom_offset,
    const RawPamEntry& raw
) {
    std::vector<int> candidates;
    if (raw.index_count < 120 || raw.vertex_count < 256) return candidates;
    const int sample_count = static_cast<int>(std::min<std::uint32_t>(raw.index_count, 180));
    const int min_unique = std::min<int>(static_cast<int>(raw.vertex_count), std::max(12, std::min(24, sample_count / 6)));
    int search_start = std::max(kPamGlobalIndexOffset, geom_offset);
    int search_stop = static_cast<int>(data.size()) - sample_count * 2;
    if (search_stop <= search_start) return candidates;
    if (search_stop - search_start > 8 * 1024 * 1024) search_stop = search_start + 8 * 1024 * 1024;
    const int max_index_value = static_cast<int>(raw.vertex_count) + 8192;
    const auto started = std::chrono::steady_clock::now();
    for (int off = search_start; off <= search_stop; off += 2) {
        if ((off & 0x1FF) == 0) {
            const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
            if (elapsed > 0.35) break;
        }
        std::set<std::uint16_t> sampled;
        bool valid = true;
        for (int i = 0; i < sample_count; i += 3) {
            const std::uint16_t value = read_u16(data, static_cast<size_t>(off) + static_cast<size_t>(i) * 2u);
            if (value > max_index_value) {
                valid = false;
                break;
            }
            sampled.insert(value);
        }
        if (!valid || static_cast<int>(sampled.size()) < min_unique) continue;
        candidates.push_back(off);
        if (candidates.size() >= 12) break;
    }
    return candidates;
}

static NativeSubmesh parse_best_global_pam_mesh(
    const std::vector<char>& data,
    const RawPamEntry& raw,
    int geom_offset,
    const Vec3& bbox_min,
    const Vec3& bbox_max
) {
    NativeSubmesh best = parse_global_pam_mesh_at(
        data,
        raw,
        geom_offset,
        bbox_min,
        bbox_max,
        static_cast<size_t>(kPamGlobalIndexOffset) + static_cast<size_t>(raw.index_element_offset) * 2u,
        kPamGlobalVertexBase
    );
    float best_score = mesh_parse_score(best, raw);
    for (int candidate_index_offset : pam_global_index_offset_candidates(data, geom_offset, raw)) {
        for (int global_vertex_base : kPamGlobalVertexBaseCandidates) {
            NativeSubmesh candidate = parse_global_pam_mesh_at(
                data,
                raw,
                geom_offset,
                bbox_min,
                bbox_max,
                static_cast<size_t>(candidate_index_offset),
                global_vertex_base
            );
            const float score = mesh_parse_score(candidate, raw);
            if (score > best_score) {
                best_score = score;
                best = std::move(candidate);
            }
        }
    }
    return best;
}

static NativeSubmesh parse_scan_pam_mesh(
    const std::vector<char>& data,
    const RawPamEntry& raw,
    size_t vertex_base,
    size_t index_offset,
    int stride,
    const Vec3& bbox_min,
    const Vec3& bbox_max
) {
    NativeSubmesh mesh = parse_quantized_pam_mesh(data, raw, vertex_base, index_offset, stride, bbox_min, bbox_max);
    mesh.name = "mesh_" + (raw.index < 10 ? std::string("0") : std::string()) + std::to_string(raw.index) + "_" + (raw.material_name.empty() ? std::to_string(raw.index) : raw.material_name);
    mesh.material = raw.material_name;
    return mesh;
}

static std::vector<NativeSubmesh> parse_pam_scan_fallback(
    const std::vector<char>& data,
    const std::vector<RawPamEntry>& entries,
    int geom_offset,
    const Vec3& bbox_min,
    const Vec3& bbox_max,
    std::string& parser_name
) {
    std::vector<NativeSubmesh> output;
    std::uint64_t total_vertices = 0;
    std::uint64_t total_indices = 0;
    for (const RawPamEntry& entry : entries) {
        total_vertices += entry.vertex_count;
        total_indices += entry.index_count;
    }
    if (total_vertices < 3 || total_indices < 3 || geom_offset < 0 || static_cast<size_t>(geom_offset) >= data.size()) return output;
    const int search_limit = std::min<int>(
        static_cast<int>(data.size()) - 100,
        geom_offset + std::min<int>(static_cast<int>(data.size() / 2u), 2000000)
    );
    const int step = (search_limit - geom_offset) < 500000 ? 2 : 4;
    for (int scan_start = geom_offset; scan_start < search_limit; scan_start += step) {
        if (scan_start + 60 > static_cast<int>(data.size())) break;
        std::uint16_t min_value = 65535;
        std::uint16_t max_value = 0;
        for (int j = 0; j < 30; ++j) {
            const std::uint16_t value = read_u16(data, static_cast<size_t>(scan_start) + static_cast<size_t>(j) * 2u);
            min_value = std::min(min_value, value);
            max_value = std::max(max_value, value);
        }
        if (static_cast<int>(max_value) - static_cast<int>(min_value) < 5000) continue;
        for (int stride : {6, 8, 10, 12, 14, 16, 20, 24, 28, 32}) {
            const size_t index_base = static_cast<size_t>(scan_start) + static_cast<size_t>(total_vertices) * static_cast<size_t>(stride);
            if (index_base + static_cast<size_t>(total_indices) * 2u > data.size()) continue;
            bool valid = true;
            for (size_t j = 0; j < std::min<std::uint64_t>(50, total_indices); ++j) {
                if (read_u16(data, index_base + j * 2u) >= total_vertices) {
                    valid = false;
                    break;
                }
            }
            if (!valid) continue;
            for (size_t j = 0; j < std::min<std::uint64_t>(500, total_indices); ++j) {
                if (read_u16(data, index_base + j * 2u) >= total_vertices) {
                    valid = false;
                    break;
                }
            }
            if (!valid) continue;
            for (const RawPamEntry& raw : entries) {
                if (raw.vertex_count == 0 || raw.index_count < 3) continue;
                output.push_back(parse_scan_pam_mesh(
                    data,
                    raw,
                    static_cast<size_t>(scan_start) + static_cast<size_t>(raw.vertex_element_offset) * static_cast<size_t>(stride),
                    index_base + static_cast<size_t>(raw.index_element_offset) * 2u,
                    stride,
                    bbox_min,
                    bbox_max
                ));
            }
            complete_native_meshes_without_filtering(output);
            if (!output.empty()) {
                parser_name = "native_pam_scan_combined";
                return output;
            }
        }
    }

    for (int scan_end = static_cast<int>(data.size()) - 2; scan_end > geom_offset + static_cast<int>(total_vertices) * 6; scan_end -= 2) {
        const int test_start = scan_end - static_cast<int>(total_indices) * 2 + 2;
        if (test_start < geom_offset) break;
        if (read_u16(data, static_cast<size_t>(test_start)) >= total_vertices) continue;
        bool valid = true;
        for (size_t j = 0; j < std::min<std::uint64_t>(30, total_indices); ++j) {
            if (read_u16(data, static_cast<size_t>(test_start) + j * 2u) >= total_vertices) {
                valid = false;
                break;
            }
        }
        if (!valid) continue;
        for (size_t j = 0; j < std::min<std::uint64_t>(300, total_indices); ++j) {
            if (read_u16(data, static_cast<size_t>(test_start) + j * 2u) >= total_vertices) {
                valid = false;
                break;
            }
        }
        if (!valid) continue;
        for (size_t j = 0; j < total_indices; ++j) {
            if (read_u16(data, static_cast<size_t>(test_start) + j * 2u) >= total_vertices) {
                valid = false;
                break;
            }
        }
        if (!valid) continue;
        const int vertex_region = test_start - geom_offset;
        int best_stride = 0;
        for (int stride : {6, 8, 10, 12, 14, 16, 20, 24, 28, 32}) {
            const int expected_end = geom_offset + static_cast<int>(total_vertices) * stride;
            if (expected_end <= test_start && (test_start - expected_end) < 16384) {
                best_stride = stride;
                break;
            }
        }
        if (best_stride == 0) {
            best_stride = static_cast<int>(vertex_region / static_cast<int>(std::max<std::uint64_t>(1, total_vertices)));
            if (best_stride < 6) best_stride = 6;
        }
        for (const RawPamEntry& raw : entries) {
            if (raw.vertex_count == 0 || raw.index_count < 3) continue;
            output.push_back(parse_scan_pam_mesh(
                data,
                raw,
                static_cast<size_t>(geom_offset) + static_cast<size_t>(raw.vertex_element_offset) * static_cast<size_t>(best_stride),
                static_cast<size_t>(test_start) + static_cast<size_t>(raw.index_element_offset) * 2u,
                best_stride,
                bbox_min,
                bbox_max
            ));
        }
        complete_native_meshes_without_filtering(output);
        if (!output.empty()) {
            parser_name = "native_pam_backward_scan_combined";
            return output;
        }
    }
    return {};
}

static std::optional<std::pair<int, size_t>> find_combined_pam_layout(
    const std::vector<char>& data,
    const std::vector<RawPamEntry>& entries,
    int geom_offset
) {
    std::uint64_t total_vertices = 0;
    std::uint64_t total_indices = 0;
    for (const RawPamEntry& entry : entries) {
        total_vertices += entry.vertex_count;
        total_indices += entry.index_count;
    }
    if (total_vertices == 0 || total_indices == 0 || geom_offset < 0 || static_cast<size_t>(geom_offset) >= data.size()) return std::nullopt;
    const double target_stride = static_cast<double>(data.size() - static_cast<size_t>(geom_offset) - total_indices * 2u) / static_cast<double>(total_vertices);
    std::vector<int> strides(kPamCandidateStrides.begin(), kPamCandidateStrides.end());
    std::sort(strides.begin(), strides.end(), [target_stride](int a, int b) {
        return std::abs(static_cast<double>(a) - target_stride) < std::abs(static_cast<double>(b) - target_stride);
    });
    for (int stride : strides) {
        const size_t index_block = static_cast<size_t>(geom_offset) + static_cast<size_t>(total_vertices) * static_cast<size_t>(stride);
        if (index_block + static_cast<size_t>(total_indices) * 2u > data.size()) continue;
        return std::make_pair(stride, index_block);
    }
    return std::nullopt;
}

static std::optional<std::pair<int, size_t>> find_local_pam_layout(
    const std::vector<char>& data,
    int geom_offset,
    const RawPamEntry& raw
) {
    const size_t vertex_base = static_cast<size_t>(geom_offset) + raw.vertex_element_offset;
    if (vertex_base >= data.size()) return std::nullopt;
    for (int stride : kPamCandidateStrides) {
        const size_t index_offset = vertex_base + static_cast<size_t>(raw.vertex_count) * static_cast<size_t>(stride);
        if (indices_fit_vertex_count(data, index_offset, raw.index_count, raw.vertex_count)) {
            return std::make_pair(stride, index_offset);
        }
    }
    return std::nullopt;
}

static NativeMeshParseResult parse_pam_submeshes(const std::vector<char>& data) {
    if (data.size() < 64 || std::string(data.data(), data.data() + 4) != "PAR ") {
        throw std::runtime_error("selected PAM is missing a PAR header");
    }
    const Vec3 bbox_min = read_vec3_f32(data, kPamHeaderBboxMinOffset);
    const Vec3 bbox_max = read_vec3_f32(data, kPamHeaderBboxMaxOffset);
    const int geom_offset = static_cast<int>(read_u32(data, kPamHeaderGeomOffset));
    const int mesh_count = static_cast<int>(read_u32(data, kPamHeaderMeshCountOffset));
    if (geom_offset <= 0 || static_cast<size_t>(geom_offset) >= data.size() || mesh_count <= 0 || mesh_count > 4096) {
        throw std::runtime_error("PAM geometry header is invalid");
    }
    std::vector<RawPamEntry> entries = read_pam_entries(data, mesh_count);
    if (entries.empty()) throw std::runtime_error("PAM submesh table is empty");

    auto scan_fallback = [&]() -> NativeMeshParseResult {
        std::string parser;
        std::vector<NativeSubmesh> meshes = parse_pam_scan_fallback(data, entries, geom_offset, bbox_min, bbox_max, parser);
        if (meshes.empty()) throw std::runtime_error("native PAM parser found no renderable geometry");
        return NativeMeshParseResult{std::move(meshes), parser.empty() ? "native_pam_scan_combined" : parser, 0};
    };

    if (pam_uses_combined_layout(entries)) {
        auto layout = find_combined_pam_layout(data, entries, geom_offset);
        if (layout.has_value()) {
            std::vector<NativeSubmesh> meshes;
            for (const RawPamEntry& raw : entries) {
                if (raw.vertex_count == 0 || raw.index_count < 3) continue;
                meshes.push_back(parse_quantized_pam_mesh(
                    data,
                    raw,
                    static_cast<size_t>(geom_offset) + static_cast<size_t>(raw.vertex_element_offset) * static_cast<size_t>(layout->first),
                    layout->second + static_cast<size_t>(raw.index_element_offset) * 2u,
                    layout->first,
                    bbox_min,
                    bbox_max
                ));
            }
            complete_native_meshes_without_filtering(meshes);
            if (!meshes.empty()) return NativeMeshParseResult{std::move(meshes), "native_pam_combined", 0};
        }
    }

    std::vector<NativeSubmesh> local_meshes;
    const std::uint32_t max_global_index_count = data.size() > kPamGlobalIndexOffset
        ? static_cast<std::uint32_t>((data.size() - kPamGlobalIndexOffset) / 2u)
        : 0u;
    bool used_global = false;
    for (const RawPamEntry& raw : entries) {
        if (raw.vertex_count == 0 || raw.index_count < 3) continue;
        auto local_layout = find_local_pam_layout(data, geom_offset, raw);
        if (local_layout.has_value()) {
            local_meshes.push_back(parse_quantized_pam_mesh(
                data,
                raw,
                static_cast<size_t>(geom_offset) + raw.vertex_element_offset,
                local_layout->second,
                local_layout->first,
                bbox_min,
                bbox_max
            ));
        } else if (raw.index_element_offset + raw.index_count <= max_global_index_count) {
            used_global = true;
            local_meshes.push_back(parse_best_global_pam_mesh(data, raw, geom_offset, bbox_min, bbox_max));
        }
    }
    complete_native_meshes_without_filtering(local_meshes);
    if (local_meshes.empty() || used_global) {
        try {
            NativeMeshParseResult scanned = scan_fallback();
            if (!used_global || local_meshes.empty()) return scanned;
            int scanned_faces = 0;
            int local_faces = 0;
            int scanned_vertices = 0;
            int local_vertices = 0;
            for (const NativeSubmesh& mesh : scanned.meshes) scanned_faces += static_cast<int>(mesh.indices.size() / 3u);
            for (const NativeSubmesh& mesh : local_meshes) local_faces += static_cast<int>(mesh.indices.size() / 3u);
            for (const NativeSubmesh& mesh : scanned.meshes) scanned_vertices += static_cast<int>(mesh.positions.size());
            for (const NativeSubmesh& mesh : local_meshes) local_vertices += static_cast<int>(mesh.positions.size());
            if (scanned_faces > local_faces || (scanned_faces == local_faces && scanned_vertices > local_vertices)) return scanned;
        } catch (...) {
            if (local_meshes.empty()) throw;
        }
    }
    if (local_meshes.empty()) throw std::runtime_error("native PAM parser found no renderable geometry");
    return NativeMeshParseResult{std::move(local_meshes), used_global ? "native_pam_global" : "native_pam_local", 0};
}

static std::vector<RawPamEntry> read_pamlod_entries(const std::vector<char>& data, int geom_offset) {
    std::vector<RawPamEntry> entries;
    const int search_limit = std::max(kPamlodEntryTableOffset, geom_offset - 5);
    for (int off = kPamlodEntryTableOffset; off < search_limit; ++off) {
        if (!looks_like_dds_string(data, static_cast<size_t>(off), kPamNameMaxLength)) continue;
        const int entry_offset = off - 16;
        if (entry_offset < kPamlodEntryTableOffset || static_cast<size_t>(off) + kPamNameMaxLength > data.size()) continue;
        const std::uint32_t vc = read_u32(data, entry_offset);
        const std::uint32_t ic = read_u32(data, entry_offset + 4);
        if (vc == 0 || vc > 131072 || ic == 0 || (ic % 3) != 0) continue;
        entries.push_back(RawPamEntry{
            static_cast<int>(entries.size()),
            vc,
            ic,
            read_u32(data, off - 8),
            read_u32(data, off - 4),
            read_c_string(data, off, kPamNameMaxLength),
            read_c_string(data, static_cast<size_t>(off) + kPamNameMaxLength, kPamNameMaxLength),
        });
    }
    return entries;
}

static std::vector<std::vector<RawPamEntry>> group_pamlod_entries(const std::vector<RawPamEntry>& entries, int lod_count) {
    std::vector<std::vector<RawPamEntry>> groups;
    std::vector<RawPamEntry> current;
    std::uint32_t expected_vertex_offset = 0;
    std::uint32_t expected_index_offset = 0;
    for (const RawPamEntry& entry : entries) {
        if (!current.empty() && (entry.vertex_element_offset != expected_vertex_offset || entry.index_element_offset != expected_index_offset)) {
            groups.push_back(current);
            current.clear();
        }
        current.push_back(entry);
        expected_vertex_offset = entry.vertex_element_offset + entry.vertex_count;
        expected_index_offset = entry.index_element_offset + entry.index_count;
    }
    if (!current.empty()) groups.push_back(current);
    if (lod_count >= 0 && static_cast<int>(groups.size()) > lod_count) groups.resize(static_cast<size_t>(lod_count));
    return groups;
}

static std::vector<int> pamlod_padding_candidates() {
    std::vector<int> out;
    for (int i = 0; i < 64; i += 2) out.push_back(i);
    for (int i = 64; i < 512; i += 4) out.push_back(i);
    for (int i = 512; i < 4096; i += 8) out.push_back(i);
    return out;
}

static std::optional<std::tuple<size_t, int, size_t>> find_pamlod_group_layout(
    const std::vector<char>& data,
    size_t cursor,
    const std::vector<RawPamEntry>& group
) {
    std::uint64_t total_vertices = 0;
    std::uint64_t total_indices = 0;
    for (const RawPamEntry& raw : group) {
        total_vertices += raw.vertex_count;
        total_indices += raw.index_count;
    }
    if (total_vertices == 0 || total_indices == 0) return std::nullopt;
    std::vector<int> strides(kPamCandidateStrides.begin(), kPamCandidateStrides.end());
    std::sort(strides.begin(), strides.end(), [](int a, int b) {
        return std::pair<int, int>(std::abs(a - 20), a) < std::pair<int, int>(std::abs(b - 20), b);
    });
    for (int padding : pamlod_padding_candidates()) {
        const size_t vertex_base = cursor + static_cast<size_t>(padding);
        for (int stride : strides) {
            const size_t index_offset = vertex_base + static_cast<size_t>(total_vertices) * static_cast<size_t>(stride);
            if (index_offset + static_cast<size_t>(total_indices) * 2u > data.size()) continue;
            bool ok = true;
            for (const RawPamEntry& raw : group) {
                if (!indices_fit_vertex_count(data, index_offset + static_cast<size_t>(raw.index_element_offset) * 2u, raw.index_count, raw.vertex_count)) {
                    ok = false;
                    break;
                }
            }
            if (ok) return std::make_tuple(vertex_base, stride, index_offset);
        }
    }
    return std::nullopt;
}

static NativeSubmesh combine_pamlod_group_meshes(const std::vector<NativeSubmesh>& parts, int lod_index) {
    NativeSubmesh combined;
    if (parts.empty()) return combined;
    combined.name = "lod" + std::to_string(lod_index);
    combined.material = parts.front().material.empty() ? combined.name : parts.front().material;
    combined.source_submesh_index = lod_index;
    combined.source_local_submesh_index = lod_index;
    combined.vertex_layout_name = parts.front().vertex_layout_name;
    combined.vertex_stride = parts.front().vertex_stride;
    combined.uv_offset = parts.front().uv_offset;
    combined.normal_offset = parts.front().normal_offset;
    std::uint32_t vertex_base = 0;
    for (const NativeSubmesh& part : parts) {
        if (combined.name == "lod" + std::to_string(lod_index) && !part.name.empty()) {
            combined.name = "lod" + std::to_string(lod_index) + "_" + part.name;
        }
        combined.positions.insert(combined.positions.end(), part.positions.begin(), part.positions.end());
        combined.uvs.insert(combined.uvs.end(), part.uvs.begin(), part.uvs.end());
        combined.normals.insert(combined.normals.end(), part.normals.begin(), part.normals.end());
        combined.source_vertex_indices.insert(combined.source_vertex_indices.end(), part.source_vertex_indices.begin(), part.source_vertex_indices.end());
        for (std::uint32_t index : part.indices) {
            combined.indices.push_back(vertex_base + index);
        }
        vertex_base += static_cast<std::uint32_t>(part.positions.size());
    }
    evaluate_native_submesh_quality(combined);
    return combined;
}

static NativeMeshParseResult parse_pamlod_submeshes(const std::vector<char>& data) {
    if (data.size() < kPamlodEntryTableOffset) {
        throw std::runtime_error("selected PAMLOD is too small");
    }
    const int lod_count = static_cast<int>(read_u32(data, kPamlodHeaderLodCountOffset));
    const int geom_offset = static_cast<int>(read_u32(data, kPamlodHeaderGeomOffset));
    if (lod_count <= 0 || lod_count > 32 || geom_offset <= 0 || static_cast<size_t>(geom_offset) >= data.size()) {
        throw std::runtime_error("PAMLOD geometry header is invalid");
    }
    const Vec3 bbox_min = read_vec3_f32(data, kPamlodHeaderBboxMinOffset);
    const Vec3 bbox_max = read_vec3_f32(data, kPamlodHeaderBboxMaxOffset);
    std::vector<RawPamEntry> entries = read_pamlod_entries(data, geom_offset);
    if (entries.empty()) throw std::runtime_error("PAMLOD mesh table is empty");
    std::vector<std::vector<RawPamEntry>> groups = group_pamlod_entries(entries, lod_count);
    size_t cursor = static_cast<size_t>(geom_offset);
    int lod_index = 0;
    for (const std::vector<RawPamEntry>& group : groups) {
        auto layout = find_pamlod_group_layout(data, cursor, group);
        if (!layout.has_value()) {
            ++lod_index;
            continue;
        }
        const size_t vertex_base = std::get<0>(*layout);
        const int stride = std::get<1>(*layout);
        const size_t index_offset = std::get<2>(*layout);
        std::vector<NativeSubmesh> parts;
        for (const RawPamEntry& raw : group) {
            parts.push_back(parse_quantized_pam_mesh(
                data,
                raw,
                vertex_base + static_cast<size_t>(raw.vertex_element_offset) * static_cast<size_t>(stride),
                index_offset + static_cast<size_t>(raw.index_element_offset) * 2u,
                stride,
                bbox_min,
                bbox_max
            ));
        }
        std::vector<NativeSubmesh> meshes;
        meshes.push_back(combine_pamlod_group_meshes(parts, lod_index));
        complete_native_meshes_without_filtering(meshes);
        if (!meshes.empty()) return NativeMeshParseResult{std::move(meshes), "native_pamlod_lod0", static_cast<int>(groups.size())};
        std::uint64_t total_indices = 0;
        for (const RawPamEntry& raw : group) total_indices += raw.index_count;
        cursor = index_offset + static_cast<size_t>(total_indices) * 2u;
        ++lod_index;
    }
    throw std::runtime_error("native PAMLOD parser found no renderable LOD geometry");
}
