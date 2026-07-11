
static std::vector<std::string> split_tab_row(const std::string& line) {
    std::vector<std::string> fields;
    std::string current;
    for (char ch : line) {
        if (ch == '\t') {
            fields.push_back(current);
            current.clear();
        } else {
            current.push_back(ch);
        }
    }
    fields.push_back(current);
    return fields;
}

static double parse_double_field(const std::vector<std::string>& fields, size_t index, double fallback = 0.0) {
    if (index >= fields.size()) return fallback;
    try {
        return std::stod(fields[index]);
    } catch (...) {
        return fallback;
    }
}

static int parse_int_field(const std::vector<std::string>& fields, size_t index, int fallback = 0) {
    if (index >= fields.size()) return fallback;
    try {
        return std::stoi(fields[index]);
    } catch (...) {
        return fallback;
    }
}

static std::int64_t parse_i64_field(const std::vector<std::string>& fields, size_t index, std::int64_t fallback = 0) {
    if (index >= fields.size()) return fallback;
    try {
        return std::stoll(fields[index]);
    } catch (...) {
        return fallback;
    }
}

static std::uint16_t float_to_half(float value) {
    if (!std::isfinite(value)) value = 0.0f;
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    const std::uint32_t sign = (bits >> 16) & 0x8000u;
    int exp = static_cast<int>((bits >> 23) & 0xFFu) - 127 + 15;
    std::uint32_t mant = bits & 0x7FFFFFu;
    if (exp <= 0) {
        if (exp < -10) return static_cast<std::uint16_t>(sign);
        mant |= 0x800000u;
        const std::uint32_t shifted = mant >> static_cast<std::uint32_t>(1 - exp);
        return static_cast<std::uint16_t>(sign | ((shifted + 0x1000u) >> 13));
    }
    if (exp >= 31) return static_cast<std::uint16_t>(sign | 0x7C00u);
    return static_cast<std::uint16_t>(sign | (static_cast<std::uint32_t>(exp) << 10) | ((mant + 0x1000u) >> 13));
}

static std::uint16_t quantize_pac_u16(float value, float bbox_min, float bbox_extent) {
    if (std::abs(bbox_extent) < 1.0e-10f || !std::isfinite(value) || !std::isfinite(bbox_min) || !std::isfinite(bbox_extent)) return 0;
    const float t = std::clamp((value - bbox_min) / bbox_extent, 0.0f, 1.0f);
    return static_cast<std::uint16_t>(std::clamp(static_cast<int>(std::nearbyint(t * 32767.0f)), 0, 32767));
}

static std::uint16_t quantize_pac_u16_double(double value, double bbox_min, double bbox_extent) {
    if (std::abs(bbox_extent) < 1.0e-10 || !std::isfinite(value) || !std::isfinite(bbox_min) || !std::isfinite(bbox_extent)) return 0;
    const double t = std::clamp((value - bbox_min) / bbox_extent, 0.0, 1.0);
    return static_cast<std::uint16_t>(std::clamp(static_cast<int>(std::nearbyint(t * 32767.0)), 0, 32767));
}

static std::uint16_t quantize_static_u16_double(double value, double bbox_min, double bbox_max) {
    const double span = bbox_max - bbox_min;
    if (std::abs(span) < 1.0e-10) return 32768;
    if (!std::isfinite(value) || !std::isfinite(bbox_min) || !std::isfinite(bbox_max)) return 0;
    const double t = std::clamp((value - bbox_min) / span, 0.0, 1.0);
    return static_cast<std::uint16_t>(std::clamp(static_cast<int>(std::nearbyint(t * 65535.0)), 0, 65535));
}

static std::uint32_t pack_pac_normal(Vec3 normal, std::uint32_t existing_packed) {
    auto enc = [](float value) -> std::uint32_t {
        value = std::clamp(std::isfinite(value) ? value : 0.0f, -1.0f, 1.0f);
        return static_cast<std::uint32_t>(std::clamp(static_cast<int>(std::nearbyint((value + 1.0f) * 511.5f)), 0, 1023));
    };
    const std::uint32_t packed = enc(normal.z) | (enc(normal.x) << 10) | (enc(normal.y) << 20);
    return (existing_packed & 0xC0000000u) | packed;
}

static void write_u16_le(std::vector<char>& data, size_t offset, std::uint16_t value) {
    if (offset + 2u > data.size()) throw std::runtime_error("native PAC rebuild write is outside output buffer");
    data[offset + 0] = static_cast<char>(value & 0xFFu);
    data[offset + 1] = static_cast<char>((value >> 8) & 0xFFu);
}

static void write_u32_le(std::vector<char>& data, size_t offset, std::uint32_t value) {
    if (offset + 4u > data.size()) throw std::runtime_error("native PAC rebuild write is outside output buffer");
    data[offset + 0] = static_cast<char>(value & 0xFFu);
    data[offset + 1] = static_cast<char>((value >> 8) & 0xFFu);
    data[offset + 2] = static_cast<char>((value >> 16) & 0xFFu);
    data[offset + 3] = static_cast<char>((value >> 24) & 0xFFu);
}

static void write_f32_le(std::vector<char>& data, size_t offset, float value) {
    std::uint32_t raw = 0;
    std::memcpy(&raw, &value, sizeof(raw));
    write_u32_le(data, offset, raw);
}

static void append_u16_le(std::vector<char>& out, std::uint16_t value) {
    out.push_back(static_cast<char>(value & 0xFFu));
    out.push_back(static_cast<char>((value >> 8) & 0xFFu));
}

static void append_u32_le(std::vector<char>& out, std::uint32_t value) {
    out.push_back(static_cast<char>(value & 0xFFu));
    out.push_back(static_cast<char>((value >> 8) & 0xFFu));
    out.push_back(static_cast<char>((value >> 16) & 0xFFu));
    out.push_back(static_cast<char>((value >> 24) & 0xFFu));
}

struct PacPatchVertex {
    std::array<double, 3> position{};
    std::array<double, 2> uv{};
    std::array<double, 3> normal{0.0, 1.0, 0.0};
    std::int64_t source_offset = -1;
};

struct PacPatchFace {
    std::uint32_t a = 0;
    std::uint32_t b = 0;
    std::uint32_t c = 0;
};

struct PacPatchSubmesh {
    std::string name;
    int vertex_count = 0;
    int face_count = 0;
    int stride = 0;
    std::int64_t descriptor_offset = -1;
    std::int64_t index_offset = -1;
    int source_index_count = 0;
    bool clean_shading = false;
    std::vector<PacPatchVertex> vertices;
    std::vector<PacPatchFace> faces;
};

struct PacFullSubmesh {
    std::string name;
    int vertex_count = 0;
    int face_count = 0;
    int stride = 0;
    int source_lod_count = 0;
    bool clean_shading = false;
    std::vector<PacPatchVertex> vertices;
    std::vector<PacPatchFace> faces;
};

static int pac_descriptor_record_length(const PacDescriptor& desc) {
    const int stored_lod_count = std::max(1, desc.stored_lod_count);
    if (stored_lod_count >= 4) return 48 + stored_lod_count * 4;
    if (stored_lod_count == 3) return 46 + stored_lod_count * 4;
    return 44 + stored_lod_count * 4;
}

static std::vector<PacFullSubmesh> load_pac_full_rebuild_tables(
    const fs::path& submeshes_path,
    const fs::path& vertices_path,
    const fs::path& faces_path
) {
    std::vector<PacFullSubmesh> submeshes;
    {
        std::ifstream in(submeshes_path);
        if (!in) throw std::runtime_error("could not open PAC full submesh table");
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty()) continue;
            const std::vector<std::string> fields = split_tab_row(line);
            if (fields.empty() || fields[0] == "header") continue;
            if (fields[0] != "submesh") throw std::runtime_error("PAC full submesh table has an invalid row");
            const int index = parse_int_field(fields, 1, -1);
            if (index < 0) throw std::runtime_error("PAC full submesh table has invalid index");
            if (static_cast<size_t>(index) >= submeshes.size()) submeshes.resize(static_cast<size_t>(index) + 1u);
            PacFullSubmesh& submesh = submeshes[static_cast<size_t>(index)];
            submesh.name = fields.size() > 2 ? fields[2] : "";
            submesh.vertex_count = parse_int_field(fields, 3, 0);
            submesh.face_count = parse_int_field(fields, 4, 0);
            submesh.stride = parse_int_field(fields, 5, 0);
            submesh.source_lod_count = parse_int_field(fields, 6, 0);
            submesh.clean_shading = parse_int_field(fields, 7, 0) != 0;
            submesh.vertices.resize(static_cast<size_t>(std::max(0, submesh.vertex_count)));
            submesh.faces.resize(static_cast<size_t>(std::max(0, submesh.face_count)));
        }
    }
    {
        std::ifstream in(vertices_path);
        if (!in) throw std::runtime_error("could not open PAC full vertex table");
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty()) continue;
            const std::vector<std::string> fields = split_tab_row(line);
            if (fields.empty() || fields[0] != "vertex") continue;
            const int submesh_index = parse_int_field(fields, 1, -1);
            const int vertex_index = parse_int_field(fields, 2, -1);
            if (submesh_index < 0 || vertex_index < 0 || static_cast<size_t>(submesh_index) >= submeshes.size()) {
                throw std::runtime_error("PAC full vertex table references an invalid submesh");
            }
            PacFullSubmesh& submesh = submeshes[static_cast<size_t>(submesh_index)];
            if (static_cast<size_t>(vertex_index) >= submesh.vertices.size()) {
                throw std::runtime_error("PAC full vertex table references an invalid vertex");
            }
            PacPatchVertex& vertex = submesh.vertices[static_cast<size_t>(vertex_index)];
            vertex.source_offset = parse_i64_field(fields, 3, -1);
            vertex.position = {parse_double_field(fields, 4), parse_double_field(fields, 5), parse_double_field(fields, 6)};
            vertex.uv = {parse_double_field(fields, 7), parse_double_field(fields, 8)};
            vertex.normal = {parse_double_field(fields, 9, 0.0), parse_double_field(fields, 10, 1.0), parse_double_field(fields, 11, 0.0)};
        }
    }
    {
        std::ifstream in(faces_path);
        if (!in) throw std::runtime_error("could not open PAC full face table");
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty()) continue;
            const std::vector<std::string> fields = split_tab_row(line);
            if (fields.empty() || fields[0] != "face") continue;
            const int submesh_index = parse_int_field(fields, 1, -1);
            const int face_index = parse_int_field(fields, 2, -1);
            if (submesh_index < 0 || face_index < 0 || static_cast<size_t>(submesh_index) >= submeshes.size()) {
                throw std::runtime_error("PAC full face table references an invalid submesh");
            }
            PacFullSubmesh& submesh = submeshes[static_cast<size_t>(submesh_index)];
            if (static_cast<size_t>(face_index) >= submesh.faces.size()) {
                throw std::runtime_error("PAC full face table references an invalid face");
            }
            submesh.faces[static_cast<size_t>(face_index)] = PacPatchFace{
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 3, 0))),
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 4, 0))),
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 5, 0))),
            };
        }
    }
    return submeshes;
}

static std::vector<PacPatchSubmesh> load_pac_patch_tables(
    const fs::path& submeshes_path,
    const fs::path& vertices_path,
    const fs::path& faces_path
) {
    std::vector<PacPatchSubmesh> submeshes;
    {
        std::ifstream in(submeshes_path);
        if (!in) throw std::runtime_error("could not open PAC submesh patch table");
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty()) continue;
            const std::vector<std::string> fields = split_tab_row(line);
            const int index = parse_int_field(fields, 0, -1);
            if (index < 0) throw std::runtime_error("PAC submesh patch table has invalid index");
            if (static_cast<size_t>(index) >= submeshes.size()) submeshes.resize(static_cast<size_t>(index) + 1u);
            PacPatchSubmesh& submesh = submeshes[static_cast<size_t>(index)];
            submesh.name = fields.size() > 1 ? fields[1] : "";
            submesh.vertex_count = parse_int_field(fields, 2, 0);
            submesh.face_count = parse_int_field(fields, 3, 0);
            submesh.stride = parse_int_field(fields, 4, 0);
            submesh.descriptor_offset = parse_i64_field(fields, 5, -1);
            submesh.index_offset = parse_i64_field(fields, 6, -1);
            submesh.source_index_count = parse_int_field(fields, 7, 0);
            submesh.clean_shading = parse_int_field(fields, 8, 0) != 0;
            submesh.vertices.resize(static_cast<size_t>(std::max(0, submesh.vertex_count)));
            submesh.faces.resize(static_cast<size_t>(std::max(0, submesh.face_count)));
        }
    }
    {
        std::ifstream in(vertices_path);
        if (!in) throw std::runtime_error("could not open PAC vertex patch table");
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty()) continue;
            const std::vector<std::string> fields = split_tab_row(line);
            const int submesh_index = parse_int_field(fields, 0, -1);
            const int vertex_index = parse_int_field(fields, 1, -1);
            if (submesh_index < 0 || vertex_index < 0 || static_cast<size_t>(submesh_index) >= submeshes.size()) {
                throw std::runtime_error("PAC vertex patch table references an invalid submesh");
            }
            PacPatchSubmesh& submesh = submeshes[static_cast<size_t>(submesh_index)];
            if (static_cast<size_t>(vertex_index) >= submesh.vertices.size()) {
                throw std::runtime_error("PAC vertex patch table references an invalid vertex");
            }
            PacPatchVertex& vertex = submesh.vertices[static_cast<size_t>(vertex_index)];
            vertex.position = {parse_double_field(fields, 2), parse_double_field(fields, 3), parse_double_field(fields, 4)};
            vertex.uv = {parse_double_field(fields, 5), parse_double_field(fields, 6)};
            vertex.normal = {parse_double_field(fields, 7, 0.0), parse_double_field(fields, 8, 1.0), parse_double_field(fields, 9, 0.0)};
            vertex.source_offset = parse_i64_field(fields, 10, -1);
        }
    }
    {
        std::ifstream in(faces_path);
        if (!in) throw std::runtime_error("could not open PAC face patch table");
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty()) continue;
            const std::vector<std::string> fields = split_tab_row(line);
            const int submesh_index = parse_int_field(fields, 0, -1);
            const int face_index = parse_int_field(fields, 1, -1);
            if (submesh_index < 0 || face_index < 0 || static_cast<size_t>(submesh_index) >= submeshes.size()) {
                throw std::runtime_error("PAC face patch table references an invalid submesh");
            }
            PacPatchSubmesh& submesh = submeshes[static_cast<size_t>(submesh_index)];
            if (static_cast<size_t>(face_index) >= submesh.faces.size()) {
                throw std::runtime_error("PAC face patch table references an invalid face");
            }
            submesh.faces[static_cast<size_t>(face_index)] = PacPatchFace{
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 2, 0))),
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 3, 0))),
                static_cast<std::uint32_t>(std::max(0, parse_int_field(fields, 4, 0))),
            };
        }
    }
    return submeshes;
}

static std::vector<char> rebuild_pac_in_place_native(const std::vector<char>& original, const std::vector<PacPatchSubmesh>& submeshes) {
    std::vector<char> output = original;
    for (size_t submesh_index = 0; submesh_index < submeshes.size(); ++submesh_index) {
        const PacPatchSubmesh& submesh = submeshes[submesh_index];
        if (submesh.vertex_count != static_cast<int>(submesh.vertices.size()) || submesh.face_count != static_cast<int>(submesh.faces.size())) {
            throw std::runtime_error("PAC patch table topology is inconsistent");
        }
        if (submesh.vertex_count <= 0 && submesh.face_count <= 0) continue;
        if (submesh.stride < 12) throw std::runtime_error("native PAC rebuild requires source vertex stride metadata");
        std::array<double, 3> bmin{1.0e300, 1.0e300, 1.0e300};
        std::array<double, 3> bmax{-1.0e300, -1.0e300, -1.0e300};
        for (const PacPatchVertex& vertex : submesh.vertices) {
            bmin[0] = std::min(bmin[0], vertex.position[0]); bmin[1] = std::min(bmin[1], vertex.position[1]); bmin[2] = std::min(bmin[2], vertex.position[2]);
            bmax[0] = std::max(bmax[0], vertex.position[0]); bmax[1] = std::max(bmax[1], vertex.position[1]); bmax[2] = std::max(bmax[2], vertex.position[2]);
        }
        constexpr double bbox_eps = 1.0e-6;
        for (int axis = 0; axis < 3; ++axis) {
            bmin[axis] -= bbox_eps;
            bmax[axis] += bbox_eps;
        }
        const std::array<double, 3> extent{bmax[0] - bmin[0], bmax[1] - bmin[1], bmax[2] - bmin[2]};
        if (submesh.descriptor_offset >= 0) {
            const size_t desc = static_cast<size_t>(submesh.descriptor_offset);
            if (desc + 35u > output.size()) throw std::runtime_error("PAC descriptor offset is outside the file");
            const size_t floats = desc + 3u;
            write_f32_le(output, floats + 2u * 4u, static_cast<float>(bmin[0]));
            write_f32_le(output, floats + 3u * 4u, static_cast<float>(bmin[1]));
            write_f32_le(output, floats + 4u * 4u, static_cast<float>(bmin[2]));
            write_f32_le(output, floats + 5u * 4u, static_cast<float>(extent[0]));
            write_f32_le(output, floats + 6u * 4u, static_cast<float>(extent[1]));
            write_f32_le(output, floats + 7u * 4u, static_cast<float>(extent[2]));
        }
        for (size_t vertex_index = 0; vertex_index < submesh.vertices.size(); ++vertex_index) {
            const PacPatchVertex& vertex = submesh.vertices[vertex_index];
            if (vertex.source_offset < 0) throw std::runtime_error("PAC vertex patch is missing source offset metadata");
            const size_t rec_off = static_cast<size_t>(vertex.source_offset);
            if (rec_off + static_cast<size_t>(submesh.stride) > output.size()) throw std::runtime_error("PAC vertex source offset is outside the file");
            if (submesh.clean_shading) {
                if (submesh.stride >= 8) write_u16_le(output, rec_off + 6u, 0);
                if (submesh.stride >= 28) {
                    for (size_t i = 20; i < 28; ++i) output[rec_off + i] = 0;
                }
            }
            write_u16_le(output, rec_off + 0u, quantize_pac_u16_double(vertex.position[0], bmin[0], extent[0]));
            write_u16_le(output, rec_off + 2u, quantize_pac_u16_double(vertex.position[1], bmin[1], extent[1]));
            write_u16_le(output, rec_off + 4u, quantize_pac_u16_double(vertex.position[2], bmin[2], extent[2]));
            if (submesh.stride >= 12) {
                write_u16_le(output, rec_off + 8u, float_to_half(static_cast<float>(vertex.uv[0])));
                write_u16_le(output, rec_off + 10u, float_to_half(static_cast<float>(vertex.uv[1])));
            }
            if (submesh.stride >= 20) {
                const std::uint32_t existing = read_u32(output, rec_off + 16u);
                write_u32_le(output, rec_off + 16u, pack_pac_normal(Vec3{static_cast<float>(vertex.normal[0]), static_cast<float>(vertex.normal[1]), static_cast<float>(vertex.normal[2])}, submesh.clean_shading ? 0u : existing));
            }
        }
        if (submesh.index_offset >= 0) {
            for (size_t face_index = 0; face_index < submesh.faces.size(); ++face_index) {
                const PacPatchFace& face = submesh.faces[face_index];
                if (
                    face.a >= static_cast<std::uint32_t>(submesh.vertices.size())
                    || face.b >= static_cast<std::uint32_t>(submesh.vertices.size())
                    || face.c >= static_cast<std::uint32_t>(submesh.vertices.size())
                ) {
                    throw std::runtime_error("PAC face patch references an out-of-range vertex");
                }
                const size_t face_off = static_cast<size_t>(submesh.index_offset) + face_index * 6u;
                if (face_off + 6u > output.size()) throw std::runtime_error("PAC face source offset is outside the file");
                write_u16_le(output, face_off + 0u, static_cast<std::uint16_t>(face.a));
                write_u16_le(output, face_off + 2u, static_cast<std::uint16_t>(face.b));
                write_u16_le(output, face_off + 4u, static_cast<std::uint16_t>(face.c));
            }
        }
    }
    return output;
}

struct PreparedPacFull {
    const PacFullSubmesh* submesh = nullptr;
    int stored_lod_count = 0;
    std::array<double, 3> bbox_min{};
    std::array<double, 3> bbox_extent{};
};

static std::vector<PreparedPacFull> prepare_pac_full_submeshes(
    const std::vector<PacFullSubmesh>& submeshes,
    const std::vector<PacDescriptor>& descriptors,
    const ParSection& section_zero,
    int lod_count,
    std::vector<char>& section_zero_data
) {
    std::vector<PreparedPacFull> prepared;
    prepared.reserve(submeshes.size());
    for (size_t index = 0; index < submeshes.size(); ++index) {
        const PacFullSubmesh& submesh = submeshes[index];
        const PacDescriptor& descriptor = descriptors[index];
        const int descriptor_offset = static_cast<int>(descriptor.descriptor_offset) - static_cast<int>(section_zero.offset);
        if (descriptor_offset < 0 || static_cast<size_t>(descriptor_offset) + 40u > section_zero_data.size()) {
            throw std::runtime_error("PAC full rebuild descriptor offset is outside section 0");
        }
        if (static_cast<size_t>(descriptor_offset + pac_descriptor_record_length(descriptor)) > section_zero_data.size()) {
            throw std::runtime_error("PAC full rebuild descriptor record is truncated");
        }
        const int stored_lod_count = std::max(
            1, std::min(lod_count, submesh.source_lod_count > 0 ? submesh.source_lod_count : descriptor.stored_lod_count));
        const int vertex_count_offset = descriptor_offset + 40;
        const int index_count_offset = vertex_count_offset + descriptor.stored_lod_count * 2;
        if (submesh.vertex_count <= 0 && submesh.face_count <= 0) {
            for (int lod = 0; lod < descriptor.stored_lod_count; ++lod) {
                write_u16_le(section_zero_data, static_cast<size_t>(vertex_count_offset + lod * 2), 0);
                write_u32_le(section_zero_data, static_cast<size_t>(index_count_offset + lod * 4), 0);
            }
            continue;
        }
        if (submesh.stride < 12) throw std::runtime_error("PAC full rebuild requires source vertex stride metadata");
        std::array<double, 3> minimum{1.0e300, 1.0e300, 1.0e300};
        std::array<double, 3> maximum{-1.0e300, -1.0e300, -1.0e300};
        for (const PacPatchVertex& vertex : submesh.vertices) {
            for (int axis = 0; axis < 3; ++axis) {
                minimum[axis] = std::min(minimum[axis], vertex.position[axis]);
                maximum[axis] = std::max(maximum[axis], vertex.position[axis]);
            }
        }
        constexpr double bbox_epsilon = 1.0e-6;
        for (int axis = 0; axis < 3; ++axis) {
            minimum[axis] -= bbox_epsilon;
            maximum[axis] += bbox_epsilon;
        }
        const std::array<double, 3> extent{
            maximum[0] - minimum[0], maximum[1] - minimum[1], maximum[2] - minimum[2]};
        const size_t floats = static_cast<size_t>(descriptor_offset) + 3u;
        for (int axis = 0; axis < 3; ++axis) {
            write_f32_le(section_zero_data, floats + static_cast<size_t>(axis + 2) * 4u, static_cast<float>(minimum[axis]));
            write_f32_le(section_zero_data, floats + static_cast<size_t>(axis + 5) * 4u, static_cast<float>(extent[axis]));
        }
        for (int lod = 0; lod < descriptor.stored_lod_count; ++lod) {
            write_u16_le(section_zero_data, static_cast<size_t>(vertex_count_offset + lod * 2), static_cast<std::uint16_t>(submesh.vertex_count));
            write_u32_le(section_zero_data, static_cast<size_t>(index_count_offset + lod * 4), static_cast<std::uint32_t>(submesh.face_count * 3));
        }
        prepared.push_back(PreparedPacFull{&submesh, stored_lod_count, minimum, extent});
    }
    return prepared;
}

static std::pair<std::vector<char>, int> build_pac_full_lod_payload(
    const std::vector<char>& original,
    const std::vector<PreparedPacFull>& prepared,
    int lod_index
) {
    std::vector<char> vertices;
    std::vector<char> indices;
    for (const PreparedPacFull& item : prepared) {
        if (item.submesh == nullptr || lod_index >= item.stored_lod_count) continue;
        const PacFullSubmesh& submesh = *item.submesh;
        for (const PacPatchVertex& vertex : submesh.vertices) {
            if (vertex.source_offset < 0) throw std::runtime_error("PAC full rebuild vertex is missing donor source offset");
            const size_t source_offset = static_cast<size_t>(vertex.source_offset);
            if (source_offset + static_cast<size_t>(submesh.stride) > original.size()) {
                throw std::runtime_error("PAC full rebuild donor record is outside the file");
            }
            std::vector<char> record(
                original.begin() + static_cast<std::ptrdiff_t>(source_offset),
                original.begin() + static_cast<std::ptrdiff_t>(source_offset + submesh.stride));
            if (submesh.clean_shading) {
                if (submesh.stride >= 8) write_u16_le(record, 6u, 0);
                if (submesh.stride >= 28) std::fill(record.begin() + 20, record.begin() + 28, 0);
            }
            for (int axis = 0; axis < 3; ++axis) {
                write_u16_le(record, static_cast<size_t>(axis) * 2u,
                    quantize_pac_u16_double(vertex.position[axis], item.bbox_min[axis], item.bbox_extent[axis]));
            }
            if (submesh.stride >= 12) {
                write_u16_le(record, 8u, float_to_half(static_cast<float>(vertex.uv[0])));
                write_u16_le(record, 10u, float_to_half(static_cast<float>(vertex.uv[1])));
            }
            if (submesh.stride >= 20) {
                const std::uint32_t existing = read_u32(record, 16u);
                write_u32_le(record, 16u, pack_pac_normal(Vec3{
                    static_cast<float>(vertex.normal[0]), static_cast<float>(vertex.normal[1]), static_cast<float>(vertex.normal[2])},
                    submesh.clean_shading ? 0u : existing));
            }
            vertices.insert(vertices.end(), record.begin(), record.end());
        }
        for (const PacPatchFace& face : submesh.faces) {
            if (face.a >= static_cast<std::uint32_t>(submesh.vertex_count)
                || face.b >= static_cast<std::uint32_t>(submesh.vertex_count)
                || face.c >= static_cast<std::uint32_t>(submesh.vertex_count)) {
                throw std::runtime_error("PAC full rebuild face references an out-of-range vertex");
            }
            append_u16_le(indices, static_cast<std::uint16_t>(face.a));
            append_u16_le(indices, static_cast<std::uint16_t>(face.b));
            append_u16_le(indices, static_cast<std::uint16_t>(face.c));
        }
    }
    const int split = static_cast<int>(vertices.size());
    vertices.insert(vertices.end(), indices.begin(), indices.end());
    return {std::move(vertices), split};
}

static std::vector<char> assemble_pac_full_sections(
    const std::vector<char>& original,
    int lod_count,
    std::map<int, std::vector<char>>& payloads,
    const std::map<int, int>& split_bytes
) {
    std::map<int, int> offsets;
    offsets[0] = 0x50;
    int next_offset = 0x50 + static_cast<int>(payloads[0].size());
    for (int slot = 1; slot < 8; ++slot) {
        auto payload = payloads.find(slot);
        if (payload == payloads.end()) continue;
        offsets[slot] = next_offset;
        next_offset += static_cast<int>(payload->second.size());
    }
    int table_offset = 5;
    for (int lod_index = 0; lod_index < lod_count; ++lod_index) {
        const int section_index = lod_count - lod_index;
        write_u32_le(payloads[0], static_cast<size_t>(table_offset + lod_index * 4), static_cast<std::uint32_t>(offsets[section_index]));
    }
    table_offset += lod_count * 4;
    for (int lod_index = 0; lod_index < lod_count; ++lod_index) {
        const int section_index = lod_count - lod_index;
        write_u32_le(payloads[0], static_cast<size_t>(table_offset + lod_index * 4),
            static_cast<std::uint32_t>(offsets[section_index] + split_bytes.at(section_index)));
    }
    std::vector<char> assembled(original.begin(), original.begin() + 0x50);
    for (int slot = 0; slot < 8; ++slot) {
        write_u32_le(assembled, 0x10u + static_cast<size_t>(slot) * 8u, 0);
        write_u32_le(assembled, 0x10u + static_cast<size_t>(slot) * 8u + 4u, 0);
    }
    for (int slot = 0; slot < 8; ++slot) {
        auto payload = payloads.find(slot);
        if (payload == payloads.end()) continue;
        write_u32_le(assembled, 0x10u + static_cast<size_t>(slot) * 8u + 4u, static_cast<std::uint32_t>(payload->second.size()));
        assembled.insert(assembled.end(), payload->second.begin(), payload->second.end());
    }
    return assembled;
}

static std::vector<char> rebuild_pac_full_native(const std::vector<char>& original, const std::vector<PacFullSubmesh>& submeshes) {
    if (original.size() < 0x50 || std::string(original.data(), original.data() + 4) != "PAR ") {
        throw std::runtime_error("native PAC full rebuild requires a PAR input");
    }
    std::vector<char> decompressed_par = decompress_internal_par_sections(original);
    if (!decompressed_par.empty()) {
        throw std::runtime_error("native PAC full rebuild does not write compressed internal PAR sections yet");
    }
    const std::vector<ParSection> sections = parse_par_sections(original);
    std::map<int, ParSection> section_by_index;
    for (const ParSection& section : sections) section_by_index[section.index] = section;
    auto sec0_it = section_by_index.find(0);
    if (sec0_it == section_by_index.end()) throw std::runtime_error("PAC full rebuild section 0 is missing");
    const ParSection& sec0 = sec0_it->second;
    if (static_cast<size_t>(sec0.offset) + sec0.size > original.size() || sec0.size < 5u) {
        throw std::runtime_error("PAC full rebuild section 0 is truncated");
    }
    const int n_lods = static_cast<unsigned char>(original[sec0.offset + 4u]);
    if (n_lods <= 0 || n_lods > 10) throw std::runtime_error("PAC full rebuild has invalid LOD count");
    std::vector<PacDescriptor> descriptors = find_pac_descriptors(original, sec0, n_lods);
    if (descriptors.size() < submeshes.size()) throw std::runtime_error("PAC full rebuild descriptor count does not match submeshes");

    std::vector<char> sec0_data(
        original.begin() + static_cast<std::ptrdiff_t>(sec0.offset),
        original.begin() + static_cast<std::ptrdiff_t>(sec0.offset + sec0.size)
    );
    descriptors.resize(submeshes.size());

    std::map<int, std::vector<char>> preserved_sections;
    for (const ParSection& section : sections) {
        if (section.index <= n_lods) continue;
        preserved_sections[section.index] = std::vector<char>(
            original.begin() + static_cast<std::ptrdiff_t>(section.offset),
            original.begin() + static_cast<std::ptrdiff_t>(section.offset + section.size)
        );
    }

    const std::vector<PreparedPacFull> prepared = prepare_pac_full_submeshes(
        submeshes, descriptors, sec0, n_lods, sec0_data);

    std::map<int, std::vector<char>> section_payloads;
    std::map<int, int> lod_split_bytes;
    section_payloads[0] = sec0_data;
    for (int sec_idx = 1; sec_idx <= n_lods; ++sec_idx) {
        const int lod_idx = n_lods - sec_idx;
        auto [payload, split] = build_pac_full_lod_payload(original, prepared, lod_idx);
        lod_split_bytes[sec_idx] = split;
        section_payloads[sec_idx] = std::move(payload);
    }
    for (auto& [index, payload] : preserved_sections) {
        section_payloads[index] = std::move(payload);
    }

    return assemble_pac_full_sections(original, n_lods, section_payloads, lod_split_bytes);
}

static std::vector<char> rebuild_static_quantized_in_place_native(const std::vector<char>& original, const fs::path& patch_path) {
    std::ifstream in(patch_path);
    if (!in) throw std::runtime_error("could not open static mesh patch table");
    std::vector<char> output = original;
    std::array<double, 3> bmin{0.0, 0.0, 0.0};
    std::array<double, 3> bmax{1.0, 1.0, 1.0};
    int header_min_offset = -1;
    int header_max_offset = -1;
    bool saw_bbox = false;
    struct VertexPatch {
        size_t offset = 0;
        std::array<double, 3> position{};
    };
    std::vector<VertexPatch> patches;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        const std::vector<std::string> fields = split_tab_row(line);
        if (fields.empty()) continue;
        if (fields[0] == "bbox") {
            bmin = {parse_double_field(fields, 1), parse_double_field(fields, 2), parse_double_field(fields, 3)};
            bmax = {parse_double_field(fields, 4, 1.0), parse_double_field(fields, 5, 1.0), parse_double_field(fields, 6, 1.0)};
            header_min_offset = parse_int_field(fields, 7, -1);
            header_max_offset = parse_int_field(fields, 8, -1);
            saw_bbox = true;
        } else if (fields[0] == "vertex") {
            const std::int64_t raw_offset = parse_i64_field(fields, 1, -1);
            if (raw_offset < 0) continue;
            patches.push_back(VertexPatch{
                static_cast<size_t>(raw_offset),
                {parse_double_field(fields, 2), parse_double_field(fields, 3), parse_double_field(fields, 4)}
            });
        }
    }
    if (!saw_bbox) throw std::runtime_error("static mesh patch table is missing bbox row");
    if (header_min_offset >= 0 && header_max_offset >= 0) {
        write_f32_le(output, static_cast<size_t>(header_min_offset) + 0u, static_cast<float>(bmin[0]));
        write_f32_le(output, static_cast<size_t>(header_min_offset) + 4u, static_cast<float>(bmin[1]));
        write_f32_le(output, static_cast<size_t>(header_min_offset) + 8u, static_cast<float>(bmin[2]));
        write_f32_le(output, static_cast<size_t>(header_max_offset) + 0u, static_cast<float>(bmax[0]));
        write_f32_le(output, static_cast<size_t>(header_max_offset) + 4u, static_cast<float>(bmax[1]));
        write_f32_le(output, static_cast<size_t>(header_max_offset) + 8u, static_cast<float>(bmax[2]));
    }
    for (const VertexPatch& patch : patches) {
        if (patch.offset + 6u > output.size()) throw std::runtime_error("static mesh vertex patch is outside output buffer");
        write_u16_le(output, patch.offset + 0u, quantize_static_u16_double(patch.position[0], bmin[0], bmax[0]));
        write_u16_le(output, patch.offset + 2u, quantize_static_u16_double(patch.position[1], bmin[1], bmax[1]));
        write_u16_le(output, patch.offset + 4u, quantize_static_u16_double(patch.position[2], bmin[2], bmax[2]));
    }
    return output;
}
