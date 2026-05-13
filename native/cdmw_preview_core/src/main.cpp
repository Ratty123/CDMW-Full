#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cstdint>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace fs = std::filesystem;

namespace {

std::string json_escape(const std::string& value) {
    std::string out;
    out.reserve(value.size() + 8);
    for (char ch : value) {
        switch (ch) {
        case '\\': out += "\\\\"; break;
        case '"': out += "\\\""; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (static_cast<unsigned char>(ch) < 0x20) {
                out += ' ';
            } else {
                out += ch;
            }
            break;
        }
    }
    return out;
}

std::string read_text(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("could not open " + path.string());
    }
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

void write_text(const fs::path& path, const std::string& text) {
    if (!path.parent_path().empty()) {
        fs::create_directories(path.parent_path());
    }
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error("could not write " + path.string());
    }
    out.write(text.data(), static_cast<std::streamsize>(text.size()));
}

std::string find_string_value(const std::string& json, const std::string& key) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return {};
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return {};
    pos = json.find('"', pos + 1);
    if (pos == std::string::npos) return {};
    std::string out;
    bool escaped = false;
    for (size_t i = pos + 1; i < json.size(); ++i) {
        char ch = json[i];
        if (escaped) {
            switch (ch) {
            case 'n': out += '\n'; break;
            case 'r': out += '\r'; break;
            case 't': out += '\t'; break;
            default: out += ch; break;
            }
            escaped = false;
            continue;
        }
        if (ch == '\\') {
            escaped = true;
            continue;
        }
        if (ch == '"') break;
        out += ch;
    }
    return out;
}

std::string find_object_value(const std::string& json, const std::string& key) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return {};
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return {};
    pos = json.find('{', pos + 1);
    if (pos == std::string::npos) return {};
    int depth = 0;
    bool in_string = false;
    bool escaped = false;
    for (size_t i = pos; i < json.size(); ++i) {
        const char ch = json[i];
        if (in_string) {
            if (escaped) {
                escaped = false;
            } else if (ch == '\\') {
                escaped = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }
        if (ch == '"') {
            in_string = true;
        } else if (ch == '{') {
            ++depth;
        } else if (ch == '}') {
            --depth;
            if (depth == 0) return json.substr(pos, i - pos + 1);
        }
    }
    return {};
}

long long find_int_value(const std::string& json, const std::string& key, long long fallback = 0) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return fallback;
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return fallback;
    ++pos;
    while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) ++pos;
    bool negative = false;
    if (pos < json.size() && json[pos] == '-') {
        negative = true;
        ++pos;
    }
    long long value = 0;
    bool any = false;
    while (pos < json.size() && std::isdigit(static_cast<unsigned char>(json[pos]))) {
        any = true;
        value = value * 10 + (json[pos] - '0');
        ++pos;
    }
    if (!any) return fallback;
    return negative ? -value : value;
}

std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

std::string basename_extension(const std::string& path) {
    const size_t slash = path.find_last_of("/\\");
    const size_t dot = path.find_last_of('.');
    if (dot == std::string::npos || (slash != std::string::npos && dot < slash)) return {};
    return lower_copy(path.substr(dot));
}

static std::string extension_from_path(const std::string& path) {
    size_t slash = path.find_last_of("/\\");
    size_t dot = path.find_last_of('.');
    if (dot == std::string::npos || (slash != std::string::npos && dot < slash)) return "";
    return lower_copy(path.substr(dot));
}

static std::string basename_from_path(const std::string& path) {
    size_t slash = path.find_last_of("/\\");
    return slash == std::string::npos ? path : path.substr(slash + 1);
}

struct ArchiveEntryRef {
    std::string path;
    std::string basename;
    std::string extension;
    fs::path pamt_path;
    fs::path paz_file;
    std::uint64_t offset = 0;
    std::uint64_t comp_size = 0;
    std::uint64_t orig_size = 0;
    std::uint32_t flags = 0;
    std::uint32_t paz_index = 0;

    int compression_type() const {
        return static_cast<int>(flags & 0x0F);
    }

    bool compressed() const {
        return comp_size != orig_size;
    }

    bool encrypted() const {
        return (flags >> 4) != 0;
    }

    int encryption_type() const {
        return static_cast<int>((flags >> 4) & 0x0F);
    }
};

struct EntryJob {
    std::string path;
    std::string extension;
    fs::path paz_file;
    std::uint64_t offset = 0;
    std::uint64_t comp_size = 0;
    std::uint64_t orig_size = 0;
    std::uint32_t flags = 0;
    fs::path output_root;
    fs::path cache_root;
    int schema_version = 4;
    ArchiveEntryRef entry;
    ArchiveEntryRef companion_entry;
};

ArchiveEntryRef parse_archive_entry_ref(const std::string& object) {
    ArchiveEntryRef entry;
    entry.path = find_string_value(object, "path");
    entry.basename = find_string_value(object, "basename");
    if (entry.basename.empty()) entry.basename = basename_from_path(entry.path);
    entry.extension = find_string_value(object, "extension");
    if (entry.extension.empty()) entry.extension = extension_from_path(entry.path);
    entry.pamt_path = fs::path(find_string_value(object, "pamt_path"));
    entry.paz_file = fs::path(find_string_value(object, "paz_file"));
    entry.offset = static_cast<std::uint64_t>(std::max<long long>(0, find_int_value(object, "offset")));
    entry.comp_size = static_cast<std::uint64_t>(std::max<long long>(0, find_int_value(object, "comp_size")));
    entry.orig_size = static_cast<std::uint64_t>(std::max<long long>(0, find_int_value(object, "orig_size")));
    entry.flags = static_cast<std::uint32_t>(std::max<long long>(0, find_int_value(object, "flags")));
    entry.paz_index = static_cast<std::uint32_t>(std::max<long long>(0, find_int_value(object, "paz_index")));
    return entry;
}

struct Vec2 {
    float x = 0.0f;
    float y = 0.0f;
};

struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

struct ParSection {
    int index = 0;
    std::uint32_t offset = 0;
    std::uint32_t size = 0;
};

struct PacDescriptor {
    std::string name;
    std::string material;
    Vec3 bbox_min;
    Vec3 bbox_extent;
    std::array<std::uint32_t, 10> vertex_counts{};
    std::array<std::uint32_t, 10> index_counts{};
    int stored_lod_count = 0;
    std::uint32_t descriptor_offset = 0;
};

struct NativeSubmesh {
    std::string name;
    std::string material;
    std::vector<Vec3> positions;
    std::vector<Vec2> uvs;
    std::vector<Vec3> normals;
    std::vector<std::uint32_t> indices;
    int source_submesh_index = -1;
};

struct TextureBinding {
    std::string role;
    std::string source_path;
    std::string archive_path;
    std::string texture_name;
    std::string parameter_name;
    std::string semantic_type;
    std::string semantic_subtype;
    std::string shader_family;
    std::string material_name;
};

struct NativePackage {
    fs::path path;
    int batch_count = 0;
    int vertex_count = 0;
    int face_count = 0;
    int dds_candidates = 0;
    int dds_extracted = 0;
    std::string mesh_parse = "unsupported";
    std::string material_index = "none";
    std::string texture_resolution = "none";
    std::vector<std::string> notes;
};

static std::uint16_t read_u16(const std::vector<char>& data, size_t offset) {
    if (offset + 2 > data.size()) throw std::runtime_error("u16 read outside buffer");
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint16_t>(p[0] | (p[1] << 8));
}

static std::uint32_t read_u32(const std::vector<char>& data, size_t offset) {
    if (offset + 4 > data.size()) throw std::runtime_error("u32 read outside buffer");
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint32_t>(p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24));
}

static float read_f32(const std::vector<char>& data, size_t offset) {
    std::uint32_t raw = read_u32(data, offset);
    float value = 0.0f;
    std::memcpy(&value, &raw, sizeof(float));
    return value;
}

static float half_to_float(std::uint16_t value) {
    const std::uint32_t sign = (static_cast<std::uint32_t>(value & 0x8000u)) << 16;
    std::uint32_t exponent = (value >> 10) & 0x1Fu;
    std::uint32_t mantissa = value & 0x03FFu;
    std::uint32_t out = 0;
    if (exponent == 0) {
        if (mantissa == 0) {
            out = sign;
        } else {
            exponent = 1;
            while ((mantissa & 0x0400u) == 0) {
                mantissa <<= 1;
                --exponent;
            }
            mantissa &= 0x03FFu;
            out = sign | ((exponent + 127 - 15) << 23) | (mantissa << 13);
        }
    } else if (exponent == 31) {
        out = sign | 0x7F800000u | (mantissa << 13);
    } else {
        out = sign | ((exponent + 127 - 15) << 23) | (mantissa << 13);
    }
    float result = 0.0f;
    std::memcpy(&result, &out, sizeof(float));
    return std::isfinite(result) ? result : 0.0f;
}

EntryJob parse_job(const fs::path& job_path) {
    const std::string text = read_text(job_path);
    EntryJob job;
    job.output_root = fs::path(find_string_value(text, "output_root"));
    job.cache_root = fs::path(find_string_value(text, "cache_root"));
    job.schema_version = static_cast<int>(std::max<long long>(1, find_int_value(text, "schema_version", 4)));
    const std::string entry_object = find_object_value(text, "entry");
    job.entry = parse_archive_entry_ref(entry_object.empty() ? text : entry_object);
    const std::string companion_object = find_object_value(text, "companion_entry");
    job.companion_entry = parse_archive_entry_ref(companion_object);
    job.path = job.entry.path;
    job.extension = job.entry.extension.empty() ? basename_extension(job.path) : job.entry.extension;
    job.paz_file = job.entry.paz_file;
    job.offset = job.entry.offset;
    job.comp_size = job.entry.comp_size;
    job.orig_size = job.entry.orig_size;
    job.flags = job.entry.flags;
    if (job.output_root.empty()) job.output_root = fs::temp_directory_path() / "cdmw_preview_core_package";
    if (job.cache_root.empty()) job.cache_root = fs::temp_directory_path() / "cdmw_preview_core_cache";
    return job;
}

static std::vector<char> read_archive_ref_raw_bytes(const ArchiveEntryRef& entry) {
    if (entry.paz_file.empty()) {
        throw std::runtime_error("job has no paz_file");
    }
    if (entry.comp_size == 0) {
        return {};
    }
    std::ifstream in(entry.paz_file, std::ios::binary);
    if (!in) {
        throw std::runtime_error("could not open PAZ file " + entry.paz_file.string());
    }
    in.seekg(0, std::ios::end);
    const auto end_pos = in.tellg();
    if (end_pos < 0) {
        throw std::runtime_error("could not determine PAZ file size");
    }
    const std::uint64_t file_size = static_cast<std::uint64_t>(end_pos);
    if (entry.offset > file_size || entry.comp_size > file_size || entry.offset + entry.comp_size > file_size) {
        throw std::runtime_error("archive entry byte range is outside the PAZ file");
    }
    in.seekg(static_cast<std::streamoff>(entry.offset), std::ios::beg);
    std::vector<char> data(static_cast<size_t>(entry.comp_size));
    if (!data.empty()) {
        in.read(data.data(), static_cast<std::streamsize>(data.size()));
        if (static_cast<size_t>(in.gcount()) != data.size()) {
            throw std::runtime_error("short read from PAZ file");
        }
    }
    return data;
}

static std::vector<char> read_entry_raw_bytes(const EntryJob& job) {
    return read_archive_ref_raw_bytes(job.entry.path.empty() ? ArchiveEntryRef{
        job.path,
        basename_from_path(job.path),
        job.extension,
        fs::path(),
        job.paz_file,
        job.offset,
        job.comp_size,
        job.orig_size,
        job.flags,
        0,
    } : job.entry);
}

static std::vector<char> crypt_chacha20_filename(const std::vector<char>& data, const std::string& filename);

static std::vector<char> lz4_decompress_block(const std::vector<char>& input, size_t output_size) {
    std::vector<char> output(output_size);
    size_t ip = 0;
    size_t op = 0;
    while (ip < input.size()) {
        const unsigned char token = static_cast<unsigned char>(input[ip++]);
        size_t literal_len = token >> 4;
        if (literal_len == 15) {
            unsigned char s = 255;
            while (ip < input.size() && s == 255) {
                s = static_cast<unsigned char>(input[ip++]);
                literal_len += s;
            }
        }
        if (ip + literal_len > input.size() || op + literal_len > output.size()) {
            throw std::runtime_error("LZ4 literal run is outside buffer");
        }
        if (literal_len > 0) {
            std::memcpy(output.data() + op, input.data() + ip, literal_len);
            ip += literal_len;
            op += literal_len;
        }
        if (ip >= input.size()) break;
        if (ip + 2 > input.size()) throw std::runtime_error("LZ4 match offset is truncated");
        const size_t match_offset = static_cast<unsigned char>(input[ip]) | (static_cast<size_t>(static_cast<unsigned char>(input[ip + 1])) << 8);
        ip += 2;
        if (match_offset == 0 || match_offset > op) throw std::runtime_error("LZ4 match offset is invalid");
        size_t match_len = token & 0x0Fu;
        if (match_len == 15) {
            unsigned char s = 255;
            while (ip < input.size() && s == 255) {
                s = static_cast<unsigned char>(input[ip++]);
                match_len += s;
            }
        }
        match_len += 4;
        if (op + match_len > output.size()) throw std::runtime_error("LZ4 match run is outside output buffer");
        for (size_t i = 0; i < match_len; ++i) {
            output[op + i] = output[op - match_offset + i];
        }
        op += match_len;
    }
    if (op != output.size()) {
        output.resize(op);
    }
    return output;
}

static std::vector<char> maybe_decompress_partial_par(const ArchiveEntryRef& entry, const std::vector<char>& data) {
    if (entry.compression_type() != 1 || data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") {
        return {};
    }
    struct Slot {
        std::uint32_t comp_size = 0;
        std::uint32_t decomp_size = 0;
        size_t offset = 0;
    };
    std::vector<Slot> slots;
    size_t file_offset = 0x50;
    size_t rebuilt_size = 0x50;
    bool saw_compressed = false;
    for (int slot = 0; slot < 8; ++slot) {
        const size_t slot_offset = 0x10u + static_cast<size_t>(slot) * 8u;
        const std::uint32_t comp_size = read_u32(data, slot_offset);
        const std::uint32_t decomp_size = read_u32(data, slot_offset + 4);
        if (decomp_size == 0) continue;
        const std::uint32_t chunk_size = comp_size > 0 ? comp_size : decomp_size;
        if (chunk_size == 0 || file_offset + chunk_size > data.size()) return {};
        if (decomp_size > entry.orig_size || rebuilt_size + decomp_size > entry.orig_size) return {};
        slots.push_back(Slot{comp_size, decomp_size, file_offset});
        file_offset += chunk_size;
        rebuilt_size += decomp_size;
        if (comp_size > 0) saw_compressed = true;
    }
    if (!saw_compressed || file_offset != data.size() || rebuilt_size != entry.orig_size) return {};
    std::vector<char> rebuilt(data.begin(), data.begin() + 0x50);
    for (const Slot& slot : slots) {
        const size_t chunk_size = slot.comp_size > 0 ? slot.comp_size : slot.decomp_size;
        std::vector<char> chunk(data.begin() + static_cast<std::ptrdiff_t>(slot.offset), data.begin() + static_cast<std::ptrdiff_t>(slot.offset + chunk_size));
        if (slot.comp_size > 0) {
            chunk = lz4_decompress_block(chunk, slot.decomp_size);
            if (chunk.size() != slot.decomp_size) return {};
        }
        rebuilt.insert(rebuilt.end(), chunk.begin(), chunk.end());
    }
    if (rebuilt.size() != entry.orig_size) return {};
    for (int slot = 0; slot < 8; ++slot) {
        const size_t off = 0x10u + static_cast<size_t>(slot) * 8u;
        if (off + 4 <= rebuilt.size()) {
            rebuilt[off + 0] = 0;
            rebuilt[off + 1] = 0;
            rebuilt[off + 2] = 0;
            rebuilt[off + 3] = 0;
        }
    }
    return rebuilt;
}

static std::vector<char> decode_archive_ref_bytes(const ArchiveEntryRef& entry, const std::vector<char>& raw) {
    std::vector<char> data = raw;
    if (entry.encrypted()) {
        if (entry.encryption_type() != 3) {
            throw std::runtime_error("unsupported archive encryption type " + std::to_string(entry.encryption_type()));
        }
        data = crypt_chacha20_filename(data, entry.basename.empty() ? basename_from_path(entry.path) : entry.basename);
    }
    if (!entry.compressed()) return data;
    if (entry.compression_type() == 2) {
        return lz4_decompress_block(data, static_cast<size_t>(entry.orig_size));
    }
    if (entry.compression_type() == 1) {
        std::vector<char> partial_par = maybe_decompress_partial_par(entry, data);
        if (!partial_par.empty()) return partial_par;
        if (entry.extension == ".dds" && data.size() >= 4 && std::string(data.data(), data.data() + 4) == "DDS " && data.size() >= 128) {
            std::vector<char> padded = data;
            padded.resize(static_cast<size_t>(entry.orig_size), 0);
            return padded;
        }
        return data;
    }
    if (entry.extension == ".dds" && data.size() >= 4 && std::string(data.data(), data.data() + 4) == "DDS " && data.size() >= 128) {
        std::vector<char> padded = data;
        padded.resize(static_cast<size_t>(entry.orig_size), 0);
        return padded;
    }
    throw std::runtime_error("unsupported archive compression type " + std::to_string(entry.compression_type()));
}

static std::vector<char> read_archive_ref_decoded_bytes(const ArchiveEntryRef& entry) {
    return decode_archive_ref_bytes(entry, read_archive_ref_raw_bytes(entry));
}

static std::vector<char> read_entry_decoded_bytes(const EntryJob& job) {
    if (!job.entry.path.empty()) return read_archive_ref_decoded_bytes(job.entry);
    std::vector<char> raw = read_entry_raw_bytes(job);
    ArchiveEntryRef ref;
    ref.path = job.path;
    ref.extension = job.extension;
    ref.paz_file = job.paz_file;
    ref.offset = job.offset;
    ref.comp_size = job.comp_size;
    ref.orig_size = job.orig_size;
    ref.flags = job.flags;
    return decode_archive_ref_bytes(ref, raw);
}

static void write_binary(const fs::path& path, const std::vector<char>& data) {
    if (!path.parent_path().empty()) {
        fs::create_directories(path.parent_path());
    }
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error("could not write " + path.string());
    }
    if (!data.empty()) {
        out.write(data.data(), static_cast<std::streamsize>(data.size()));
    }
}

static std::string safe_filename(std::string value) {
    if (value.empty()) value = "texture";
    for (char& ch : value) {
        const unsigned char u = static_cast<unsigned char>(ch);
        if (!(std::isalnum(u) || ch == '.' || ch == '_' || ch == '-')) {
            ch = '_';
        }
    }
    return value;
}

static std::uint64_t fnv1a64(const std::string& text) {
    std::uint64_t hash = 1469598103934665603ull;
    for (unsigned char ch : text) {
        hash ^= static_cast<std::uint64_t>(ch);
        hash *= 1099511628211ull;
    }
    return hash;
}

static std::string hex64(std::uint64_t value) {
    std::ostringstream out;
    out << std::hex << std::setw(16) << std::setfill('0') << value;
    return out.str();
}

static std::uint32_t rot32(std::uint32_t value, int shift) {
    return (value << shift) | (value >> (32 - shift));
}

static std::uint32_t lookup3_finalize_c(std::uint32_t a, std::uint32_t b, std::uint32_t c) {
    c = (c ^ b) - rot32(b, 14);
    a = (a ^ c) - rot32(c, 11);
    b = (b ^ a) - rot32(a, 25);
    c = (c ^ b) - rot32(b, 16);
    a = (a ^ c) - rot32(c, 4);
    b = (b ^ a) - rot32(a, 14);
    c = (c ^ b) - rot32(b, 24);
    return c;
}

static std::uint32_t read_u32_padded(const std::vector<unsigned char>& data, size_t offset) {
    std::uint32_t value = 0;
    for (size_t i = 0; i < 4; ++i) {
        if (offset + i < data.size()) {
            value |= static_cast<std::uint32_t>(data[offset + i]) << (i * 8);
        }
    }
    return value;
}

static std::uint32_t hashlittle_bytes(const std::vector<unsigned char>& data, std::uint32_t initval) {
    size_t length = data.size();
    size_t remaining = length;
    std::uint32_t a = 0xDEADBEEFu + static_cast<std::uint32_t>(length) + initval;
    std::uint32_t b = a;
    std::uint32_t c = a;
    size_t offset = 0;
    while (remaining > 12) {
        a += read_u32_padded(data, offset);
        b += read_u32_padded(data, offset + 4);
        c += read_u32_padded(data, offset + 8);
        a -= c; a ^= rot32(c, 4); c += b;
        b -= a; b ^= rot32(a, 6); a += c;
        c -= b; c ^= rot32(b, 8); b += a;
        a -= c; a ^= rot32(c, 16); c += b;
        b -= a; b ^= rot32(a, 19); a += c;
        c -= b; c ^= rot32(b, 4); b += a;
        offset += 12;
        remaining -= 12;
    }
    if (remaining >= 12) {
        c += read_u32_padded(data, offset + 8);
    } else if (remaining >= 9) {
        c += read_u32_padded(data, offset + 8) & (0xFFFFFFFFu >> (8u * (12u - static_cast<unsigned int>(remaining))));
    }
    if (remaining >= 8) {
        b += read_u32_padded(data, offset + 4);
    } else if (remaining >= 5) {
        b += read_u32_padded(data, offset + 4) & (0xFFFFFFFFu >> (8u * (8u - static_cast<unsigned int>(remaining))));
    }
    if (remaining >= 4) {
        a += read_u32_padded(data, offset);
    } else if (remaining >= 1) {
        a += read_u32_padded(data, offset) & (0xFFFFFFFFu >> (8u * (4u - static_cast<unsigned int>(remaining))));
    } else {
        return c;
    }
    return lookup3_finalize_c(a, b, c);
}

static void chacha_quarter_round(std::uint32_t& a, std::uint32_t& b, std::uint32_t& c, std::uint32_t& d) {
    a += b; d ^= a; d = rot32(d, 16);
    c += d; b ^= c; b = rot32(b, 12);
    a += b; d ^= a; d = rot32(d, 8);
    c += d; b ^= c; b = rot32(b, 7);
}

static void chacha20_block(const std::array<std::uint32_t, 16>& state, std::array<unsigned char, 64>& out) {
    std::array<std::uint32_t, 16> working = state;
    for (int i = 0; i < 10; ++i) {
        chacha_quarter_round(working[0], working[4], working[8], working[12]);
        chacha_quarter_round(working[1], working[5], working[9], working[13]);
        chacha_quarter_round(working[2], working[6], working[10], working[14]);
        chacha_quarter_round(working[3], working[7], working[11], working[15]);
        chacha_quarter_round(working[0], working[5], working[10], working[15]);
        chacha_quarter_round(working[1], working[6], working[11], working[12]);
        chacha_quarter_round(working[2], working[7], working[8], working[13]);
        chacha_quarter_round(working[3], working[4], working[9], working[14]);
    }
    for (size_t i = 0; i < 16; ++i) {
        working[i] += state[i];
        out[i * 4 + 0] = static_cast<unsigned char>((working[i] >> 0) & 0xFF);
        out[i * 4 + 1] = static_cast<unsigned char>((working[i] >> 8) & 0xFF);
        out[i * 4 + 2] = static_cast<unsigned char>((working[i] >> 16) & 0xFF);
        out[i * 4 + 3] = static_cast<unsigned char>((working[i] >> 24) & 0xFF);
    }
}

static std::vector<char> crypt_chacha20_filename(const std::vector<char>& data, const std::string& filename) {
    std::string base = lower_copy(basename_from_path(filename));
    std::vector<unsigned char> base_bytes(base.begin(), base.end());
    const std::uint32_t seed = hashlittle_bytes(base_bytes, 0x000C5EDEu);
    const std::uint32_t key_base = seed ^ 0x60616263u;
    const std::array<std::uint32_t, 8> deltas = {
        0x00000000u, 0x0A0A0A0Au, 0x0C0C0C0Cu, 0x06060606u,
        0x0E0E0E0Eu, 0x0A0A0A0Au, 0x06060606u, 0x02020202u,
    };
    std::array<std::uint32_t, 16> state = {
        0x61707865u, 0x3320646Eu, 0x79622D32u, 0x6B206574u,
        key_base ^ deltas[0], key_base ^ deltas[1], key_base ^ deltas[2], key_base ^ deltas[3],
        key_base ^ deltas[4], key_base ^ deltas[5], key_base ^ deltas[6], key_base ^ deltas[7],
        seed, seed, seed, seed,
    };
    std::vector<char> out(data.size());
    size_t offset = 0;
    while (offset < data.size()) {
        std::array<unsigned char, 64> block{};
        chacha20_block(state, block);
        const size_t n = std::min<size_t>(64, data.size() - offset);
        for (size_t i = 0; i < n; ++i) {
            out[offset + i] = static_cast<char>(static_cast<unsigned char>(data[offset + i]) ^ block[i]);
        }
        ++state[12];
        if (state[12] == 0) ++state[13];
        offset += n;
    }
    return out;
}

class VfsPathResolver {
public:
    explicit VfsPathResolver(const std::vector<char>& name_block) : name_block_(name_block) {
        cache_[0xFFFFFFFFu] = "";
    }

    std::string get_full_path(std::uint32_t offset) {
        if (offset == 0xFFFFFFFFu || offset >= name_block_.size()) return "";
        auto cached = cache_.find(offset);
        if (cached != cache_.end()) return cached->second;
        std::vector<std::pair<std::uint32_t, std::string>> parts;
        std::uint32_t current = offset;
        std::string base;
        std::set<std::uint32_t> seen;
        while (current != 0xFFFFFFFFu) {
            if (!seen.insert(current).second) break;
            auto hit = cache_.find(current);
            if (hit != cache_.end()) {
                base = hit->second;
                break;
            }
            if (static_cast<size_t>(current) + 5 > name_block_.size()) break;
            const std::uint32_t parent = read_u32(name_block_, current);
            const std::uint8_t part_len = static_cast<std::uint8_t>(name_block_[current + 4]);
            if (static_cast<size_t>(current) + 5 + part_len > name_block_.size()) break;
            std::string part(name_block_.data() + current + 5, name_block_.data() + current + 5 + part_len);
            parts.emplace_back(current, part);
            current = parent;
            if (parts.size() > 255) break;
        }
        std::string built = base;
        for (auto it = parts.rbegin(); it != parts.rend(); ++it) {
            built += it->second;
            if (cache_.size() < 200000) {
                cache_[it->first] = built;
            }
        }
        return built;
    }

private:
    const std::vector<char>& name_block_;
    std::unordered_map<std::uint32_t, std::string> cache_;
};

struct PamtIndex {
    fs::path pamt_path;
    std::unordered_map<std::string, std::vector<ArchiveEntryRef>> by_basename;
    std::unordered_map<std::string, ArchiveEntryRef> by_path;
    size_t entry_count = 0;
};

static PamtIndex parse_pamt_index(const fs::path& pamt_path) {
    if (pamt_path.empty()) {
        throw std::runtime_error("job has no pamt_path");
    }
    std::ifstream in(pamt_path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("could not open PAMT file " + pamt_path.string());
    }
    in.seekg(0, std::ios::end);
    const auto size_pos = in.tellg();
    if (size_pos < 0) throw std::runtime_error("could not determine PAMT size");
    in.seekg(0, std::ios::beg);
    std::vector<char> data(static_cast<size_t>(size_pos));
    if (!data.empty()) {
        in.read(data.data(), static_cast<std::streamsize>(data.size()));
        if (static_cast<size_t>(in.gcount()) != data.size()) {
            throw std::runtime_error("short read from PAMT file");
        }
    }
    if (data.size() < 12) throw std::runtime_error("PAMT file is too small");
    size_t off = 0;
    (void)read_u32(data, off);
    off += 4;
    const std::uint32_t paz_count = read_u32(data, off);
    off += 8;
    off += static_cast<size_t>(paz_count) * 12u;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT directory block length is truncated");
    const std::uint32_t dir_block_size = read_u32(data, off);
    off += 4;
    if (off + dir_block_size > data.size()) throw std::runtime_error("PAMT directory block is truncated");
    std::vector<char> directory_data(data.begin() + static_cast<std::ptrdiff_t>(off), data.begin() + static_cast<std::ptrdiff_t>(off + dir_block_size));
    off += dir_block_size;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT filename block length is truncated");
    const std::uint32_t file_name_block_size = read_u32(data, off);
    off += 4;
    if (off + file_name_block_size > data.size()) throw std::runtime_error("PAMT filename block is truncated");
    std::vector<char> file_names(data.begin() + static_cast<std::ptrdiff_t>(off), data.begin() + static_cast<std::ptrdiff_t>(off + file_name_block_size));
    off += file_name_block_size;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT folder count is truncated");
    const std::uint32_t folder_count = read_u32(data, off);
    off += 4;
    const size_t folder_table_offset = off;
    const size_t folder_table_size = static_cast<size_t>(folder_count) * 16u;
    if (off + folder_table_size > data.size()) throw std::runtime_error("PAMT folder table is truncated");
    off += folder_table_size;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT file count is truncated");
    const std::uint32_t file_count = read_u32(data, off);
    off += 4;
    const size_t file_table_offset = off;
    const size_t file_record_size = 20u;
    if (off + static_cast<size_t>(file_count) * file_record_size > data.size()) {
        throw std::runtime_error("PAMT file table is truncated");
    }

    VfsPathResolver file_resolver(file_names);
    VfsPathResolver dir_resolver(directory_data);
    struct FolderRange {
        std::uint32_t start = 0;
        std::uint32_t end = 0;
        std::string path;
    };
    std::vector<FolderRange> folder_ranges;
    folder_ranges.reserve(folder_count);
    for (std::uint32_t i = 0; i < folder_count; ++i) {
        const size_t base = folder_table_offset + static_cast<size_t>(i) * 16u;
        const std::uint32_t name_offset = read_u32(data, base + 4);
        const std::uint32_t start = read_u32(data, base + 8);
        const std::uint32_t count = read_u32(data, base + 12);
        if (count == 0) continue;
        std::string folder = dir_resolver.get_full_path(name_offset);
        std::replace(folder.begin(), folder.end(), '\\', '/');
        while (!folder.empty() && folder.front() == '/') folder.erase(folder.begin());
        while (!folder.empty() && folder.back() == '/') folder.pop_back();
        folder_ranges.push_back(FolderRange{start, start + count, folder});
    }
    std::sort(folder_ranges.begin(), folder_ranges.end(), [](const FolderRange& a, const FolderRange& b) {
        return a.start < b.start;
    });

    PamtIndex index;
    index.pamt_path = pamt_path;
    index.entry_count = file_count;
    size_t folder_cursor = 0;
    for (std::uint32_t entry_index = 0; entry_index < file_count; ++entry_index) {
        const size_t base = file_table_offset + static_cast<size_t>(entry_index) * file_record_size;
        const std::uint32_t name_offset = read_u32(data, base);
        const std::uint32_t paz_offset = read_u32(data, base + 4);
        const std::uint32_t comp_size = read_u32(data, base + 8);
        const std::uint32_t orig_size = read_u32(data, base + 12);
        const std::uint16_t paz_index = read_u16(data, base + 16);
        const std::uint16_t flags = read_u16(data, base + 18);
        std::string relative = file_resolver.get_full_path(name_offset);
        std::replace(relative.begin(), relative.end(), '\\', '/');
        while (!relative.empty() && relative.front() == '/') relative.erase(relative.begin());
        while (folder_cursor < folder_ranges.size() && entry_index >= folder_ranges[folder_cursor].end) {
            ++folder_cursor;
        }
        std::string folder;
        if (folder_cursor < folder_ranges.size()) {
            const FolderRange& range = folder_ranges[folder_cursor];
            if (entry_index >= range.start && entry_index < range.end) {
                folder = range.path;
            }
        }
        const std::string full_path = folder.empty() ? relative : (folder + "/" + relative);
        ArchiveEntryRef ref;
        ref.path = full_path;
        ref.basename = basename_from_path(full_path);
        ref.extension = extension_from_path(full_path);
        ref.pamt_path = pamt_path;
        ref.paz_index = paz_index;
        ref.paz_file = pamt_path.parent_path() / (std::to_string(paz_index) + ".paz");
        ref.offset = paz_offset;
        ref.comp_size = comp_size;
        ref.orig_size = orig_size;
        ref.flags = flags;
        index.by_basename[lower_copy(ref.basename)].push_back(ref);
        index.by_path[lower_copy(full_path)] = ref;
    }
    return index;
}

static const PamtIndex& cached_pamt_index(const fs::path& pamt_path) {
    static std::map<std::string, PamtIndex> cache;
    const std::string key = fs::absolute(pamt_path).string();
    auto it = cache.find(key);
    if (it == cache.end()) {
        it = cache.emplace(key, parse_pamt_index(pamt_path)).first;
    }
    return it->second;
}

std::string fourcc_from_bytes(const std::vector<char>& data) {
    if (data.size() < 4) return "";
    std::string value(data.data(), data.data() + 4);
    for (char& ch : value) {
        if (static_cast<unsigned char>(ch) < 0x20 || static_cast<unsigned char>(ch) > 0x7e) ch = '.';
    }
    return value;
}

static float vec_dot(const Vec3& a, const Vec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

static Vec3 vec_cross(const Vec3& a, const Vec3& b) {
    return Vec3{
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}

static Vec3 vec_add(const Vec3& a, const Vec3& b) {
    return Vec3{a.x + b.x, a.y + b.y, a.z + b.z};
}

static Vec3 vec_sub(const Vec3& a, const Vec3& b) {
    return Vec3{a.x - b.x, a.y - b.y, a.z - b.z};
}

static Vec3 vec_mul(const Vec3& value, float scale) {
    return Vec3{value.x * scale, value.y * scale, value.z * scale};
}

static Vec3 vec_normalize(const Vec3& value, const Vec3& fallback = Vec3{0.0f, 1.0f, 0.0f}) {
    const float len2 = vec_dot(value, value);
    if (len2 <= 1.0e-12f || !std::isfinite(len2)) return fallback;
    const float inv = 1.0f / std::sqrt(len2);
    return Vec3{value.x * inv, value.y * inv, value.z * inv};
}

static std::vector<ParSection> parse_par_sections(const std::vector<char>& data) {
    std::vector<ParSection> sections;
    if (data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") return sections;
    std::uint32_t offset = 0x50;
    for (int i = 0; i < 8; ++i) {
        const size_t slot_off = 0x10u + static_cast<size_t>(i) * 8u;
        const std::uint32_t comp_size = read_u32(data, slot_off);
        const std::uint32_t decomp_size = read_u32(data, slot_off + 4);
        const std::uint32_t stored_size = comp_size > 0 ? comp_size : decomp_size;
        if (decomp_size == 0) continue;
        if (offset + stored_size > data.size()) return {};
        if (comp_size > 0 && comp_size < decomp_size) {
            // A compressed PAR section needs LZ4 reconstruction. Keep this
            // path conservative so the Python fallback handles partial PARs.
            return {};
        }
        sections.push_back(ParSection{i, offset, decomp_size});
        offset += stored_size;
    }
    return sections;
}

static int find_bytes(const std::vector<char>& data, const std::vector<unsigned char>& pattern, size_t start, size_t end) {
    if (pattern.empty() || start >= end || pattern.size() > end - start) return -1;
    for (size_t i = start; i + pattern.size() <= end; ++i) {
        bool ok = true;
        for (size_t j = 0; j < pattern.size(); ++j) {
            if (static_cast<unsigned char>(data[i + j]) != pattern[j]) {
                ok = false;
                break;
            }
        }
        if (ok) return static_cast<int>(i);
    }
    return -1;
}

static std::pair<std::string, std::string> find_descriptor_names(
    const std::vector<char>& data,
    size_t region_start,
    size_t desc_start
) {
    std::vector<std::string> names;
    size_t cursor = desc_start;
    for (int n = 0; n < 2; ++n) {
        bool found = false;
        for (size_t back = 1; back < 200 && cursor >= region_start + back; ++back) {
            const size_t pos = cursor - back;
            const unsigned char candidate_len = static_cast<unsigned char>(data[pos]);
            if (candidate_len == 0 || candidate_len != back - 1) continue;
            bool ascii = true;
            for (size_t p = pos + 1; p < cursor; ++p) {
                const unsigned char ch = static_cast<unsigned char>(data[p]);
                if (ch < 32 || ch >= 127) {
                    ascii = false;
                    break;
                }
            }
            if (!ascii || cursor <= pos + 1) continue;
            names.emplace_back(data.data() + pos + 1, data.data() + cursor);
            cursor = pos;
            found = true;
            break;
        }
        if (!found) {
            std::ostringstream unknown;
            unknown << "unknown_" << std::hex << (desc_start - region_start);
            names.push_back(unknown.str());
        }
    }
    std::reverse(names.begin(), names.end());
    return {names.size() > 0 ? names[0] : "", names.size() > 1 ? names[1] : ""};
}

static std::vector<PacDescriptor> find_pac_descriptors(
    const std::vector<char>& data,
    const ParSection& sec0,
    int n_lods
) {
    std::vector<PacDescriptor> descriptors;
    std::set<size_t> seen_starts;
    const size_t region_start = sec0.offset;
    const size_t region_end = static_cast<size_t>(sec0.offset) + sec0.size;
    if (region_end > data.size() || region_start >= region_end) return descriptors;
    const int pad_len = std::max(4, n_lods);

    auto append_descriptor = [&](size_t pattern_pos, int stored_lod_count, int vc_off, int ic_off) {
        if (pattern_pos < 35) return;
        const size_t desc_start = pattern_pos - 35;
        if (desc_start < region_start || !seen_starts.insert(desc_start).second) return;
        if (desc_start + static_cast<size_t>(ic_off) + static_cast<size_t>(stored_lod_count) * 4u > region_end) return;
        if (static_cast<unsigned char>(data[desc_start]) != 0x01) return;
        PacDescriptor desc;
        try {
            desc.bbox_min = Vec3{
                read_f32(data, desc_start + 3 + 2 * 4),
                read_f32(data, desc_start + 3 + 3 * 4),
                read_f32(data, desc_start + 3 + 4 * 4),
            };
            desc.bbox_extent = Vec3{
                read_f32(data, desc_start + 3 + 5 * 4),
                read_f32(data, desc_start + 3 + 6 * 4),
                read_f32(data, desc_start + 3 + 7 * 4),
            };
            for (int i = 0; i < stored_lod_count && i < pad_len && i < 10; ++i) {
                desc.vertex_counts[static_cast<size_t>(i)] = read_u16(data, desc_start + vc_off + static_cast<size_t>(i) * 2u);
                desc.index_counts[static_cast<size_t>(i)] = read_u32(data, desc_start + ic_off + static_cast<size_t>(i) * 4u);
            }
        } catch (...) {
            return;
        }
        bool any_vertices = false;
        for (std::uint32_t count : desc.vertex_counts) {
            if (count > 0) any_vertices = true;
            if (count > 200000) return;
        }
        for (std::uint32_t count : desc.index_counts) {
            if (count > 20000000) return;
        }
        if (!any_vertices) return;
        auto names = find_descriptor_names(data, region_start, desc_start);
        desc.name = names.first;
        desc.material = names.second;
        desc.stored_lod_count = stored_lod_count;
        desc.descriptor_offset = static_cast<std::uint32_t>(desc_start);
        descriptors.push_back(desc);
    };

    struct PatternSpec {
        std::vector<unsigned char> pattern;
        int lod_count;
        int vc_off;
        int ic_off;
        int reject_prev;
    };
    const std::vector<PatternSpec> specs = {
        {{0x04, 0x00, 0x01, 0x02, 0x03}, 4, 40, 48, -1},
        {{0x03, 0x00, 0x01, 0x01, 0x02}, 3, 40, 46, -1},
        {{0x03, 0x00, 0x01, 0x02}, 3, 40, 46, 0x04},
        {{0x02, 0x00, 0x01}, 2, 40, 44, 0x03},
    };
    for (const PatternSpec& spec : specs) {
        size_t pos = region_start;
        while (true) {
            const int found = find_bytes(data, spec.pattern, pos, region_end);
            if (found < 0) break;
            const size_t idx = static_cast<size_t>(found);
            bool accept = true;
            if (spec.reject_prev >= 0 && idx > region_start) {
                const unsigned char prev = static_cast<unsigned char>(data[idx - 1]);
                if (spec.lod_count == 3) accept = prev != 0x04;
                if (spec.lod_count == 2) accept = prev != 0x03 && prev != 0x04;
            }
            if (accept) append_descriptor(idx, spec.lod_count, spec.vc_off, spec.ic_off);
            pos = idx + spec.pattern.size();
        }
    }
    std::sort(descriptors.begin(), descriptors.end(), [](const PacDescriptor& a, const PacDescriptor& b) {
        return a.descriptor_offset < b.descriptor_offset;
    });
    return descriptors;
}

static float decode_pac_position(std::uint16_t value, float min_value, float extent) {
    if (std::abs(extent) < 1.0e-8f) return min_value;
    return min_value + (static_cast<float>(value) / 32767.0f) * extent;
}

static Vec3 decode_pac_normal(const std::vector<char>& data, size_t rec_off) {
    if (rec_off + 20 > data.size()) return Vec3{0.0f, 1.0f, 0.0f};
    const std::uint32_t packed = read_u32(data, rec_off + 16);
    const std::uint32_t nx_raw = (packed >> 0) & 0x3FFu;
    const std::uint32_t ny_raw = (packed >> 10) & 0x3FFu;
    const std::uint32_t nz_raw = (packed >> 20) & 0x3FFu;
    return vec_normalize(Vec3{
        static_cast<float>(ny_raw) / 511.5f - 1.0f,
        static_cast<float>(nz_raw) / 511.5f - 1.0f,
        static_cast<float>(nx_raw) / 511.5f - 1.0f,
    });
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
    int total_indices
) {
    std::uint32_t total_verts = 0;
    for (const PacDescriptor& desc : descriptors) {
        total_verts += desc.vertex_counts[static_cast<size_t>(lod)];
    }
    const int primary_bytes = static_cast<int>(total_verts) * 40;
    const int index_bytes = total_indices * 2;
    if (primary_bytes + index_bytes >= static_cast<int>(geom_sec.size)) {
        return {0, primary_bytes};
    }
    const int gap = static_cast<int>(geom_sec.size) - primary_bytes - index_bytes;
    if (gap <= 0) return {0, primary_bytes};
    const int secondary_bytes = (gap / 40) * 40;
    int best_v_start = 0;
    int best_i_start = primary_bytes + secondary_bytes;
    for (int n_secondary = 0; n_secondary <= gap / 40; ++n_secondary) {
        const int v_start = n_secondary * 40;
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
    int source_submesh_index
) {
    NativeSubmesh mesh;
    mesh.name = desc.name;
    mesh.material = desc.material.empty() ? desc.name : desc.material;
    mesh.source_submesh_index = source_submesh_index;
    mesh.positions.reserve(vertex_count);
    mesh.uvs.reserve(vertex_count);
    mesh.normals.reserve(vertex_count);
    for (std::uint32_t vi = 0; vi < vertex_count; ++vi) {
        const size_t rec_off = static_cast<size_t>(geom_sec.offset) + static_cast<size_t>(vertex_start) + static_cast<size_t>(vi) * 40u;
        if (rec_off + 40 > data.size()) break;
        const std::uint16_t xu = read_u16(data, rec_off);
        const std::uint16_t yu = read_u16(data, rec_off + 2);
        const std::uint16_t zu = read_u16(data, rec_off + 4);
        mesh.positions.push_back(Vec3{
            decode_pac_position(xu, desc.bbox_min.x, desc.bbox_extent.x),
            decode_pac_position(yu, desc.bbox_min.y, desc.bbox_extent.y),
            decode_pac_position(zu, desc.bbox_min.z, desc.bbox_extent.z),
        });
        const float u = half_to_float(read_u16(data, rec_off + 8));
        const float v = half_to_float(read_u16(data, rec_off + 10));
        mesh.uvs.push_back(Vec2{std::isfinite(u) ? u : 0.0f, std::isfinite(v) ? v : 0.0f});
        mesh.normals.push_back(decode_pac_normal(data, rec_off));
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
    return mesh;
}

static std::vector<NativeSubmesh> parse_pac_geometry_section(
    const std::vector<char>& data,
    const std::vector<PacDescriptor>& descriptors,
    const ParSection& geom_sec,
    int lod
) {
    std::vector<NativeSubmesh> output;
    if (lod < 0 || lod >= 10) return output;
    int total_indices = 0;
    for (const PacDescriptor& desc : descriptors) {
        total_indices += static_cast<int>(desc.index_counts[static_cast<size_t>(lod)]);
    }
    const auto layout = find_pac_section_layout(data, geom_sec, descriptors, lod, total_indices);
    const int vert_base = layout.first;
    int idx_byte_offset = layout.second;
    const int index_region_start = idx_byte_offset;
    std::vector<int> desc_vert_offsets;
    desc_vert_offsets.reserve(descriptors.size());
    int cursor = vert_base;
    for (const PacDescriptor& desc : descriptors) {
        desc_vert_offsets.push_back(cursor);
        cursor += static_cast<int>(desc.vertex_counts[static_cast<size_t>(lod)]) * 40;
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
                const int available_vc = std::max(0, (index_region_start - desc_vert_offsets[di]) / 40);
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
            static_cast<int>(di)
        );
        mesh.name = desc.name;
        mesh.material = desc.material.empty() ? desc.name : desc.material;
        if (!mesh.positions.empty() && mesh.indices.size() >= 3) output.push_back(std::move(mesh));
    }
    return output;
}

static std::vector<NativeSubmesh> parse_pac_submeshes(const std::vector<char>& data) {
    if (data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") {
        throw std::runtime_error("selected PAC is missing a PAR header");
    }
    const std::vector<ParSection> sections = parse_par_sections(data);
    if (sections.empty()) {
        throw std::runtime_error("native PAC parser does not yet support compressed PAR sections");
    }
    std::map<int, ParSection> by_index;
    for (const ParSection& section : sections) by_index[section.index] = section;
    auto sec0_it = by_index.find(0);
    if (sec0_it == by_index.end()) throw std::runtime_error("PAC section 0 is missing");
    const ParSection& sec0 = sec0_it->second;
    if (static_cast<size_t>(sec0.offset) + 5 > data.size()) throw std::runtime_error("PAC section 0 is truncated");
    const int n_lods = static_cast<unsigned char>(data[sec0.offset + 4]);
    if (n_lods <= 0 || n_lods > 10) throw std::runtime_error("PAC LOD count is unsupported");
    const std::vector<PacDescriptor> descriptors = find_pac_descriptors(data, sec0, n_lods);
    if (descriptors.empty()) throw std::runtime_error("native PAC parser found no submesh descriptors");

    struct Candidate {
        int faces = 0;
        int vertices = 0;
        int submeshes = 0;
        int geom_section_idx = 0;
        std::vector<NativeSubmesh> meshes;
    };
    std::vector<Candidate> candidates;
    for (int geom_section_idx : {4, 3, 2, 1}) {
        auto it = by_index.find(geom_section_idx);
        if (it == by_index.end()) continue;
        const int lod = 4 - geom_section_idx;
        if (lod < 0 || lod >= n_lods) continue;
        std::vector<NativeSubmesh> meshes = parse_pac_geometry_section(data, descriptors, it->second, lod);
        int faces = 0;
        int vertices = 0;
        for (const NativeSubmesh& mesh : meshes) {
            faces += static_cast<int>(mesh.indices.size() / 3u);
            vertices += static_cast<int>(mesh.positions.size());
        }
        if (!meshes.empty() && faces > 0) {
            candidates.push_back(Candidate{faces, vertices, static_cast<int>(meshes.size()), geom_section_idx, std::move(meshes)});
        }
    }
    if (candidates.empty()) throw std::runtime_error("native PAC parser found no renderable geometry sections");
    std::sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
        if (a.faces != b.faces) return a.faces > b.faces;
        if (a.vertices != b.vertices) return a.vertices > b.vertices;
        if (a.submeshes != b.submeshes) return a.submeshes > b.submeshes;
        return a.geom_section_idx > b.geom_section_idx;
    });
    return std::move(candidates.front().meshes);
}

static std::string texture_role_from_name(const std::string& raw_name) {
    const std::string name = lower_copy(raw_name);
    if (name.find("_n.dds") != std::string::npos || name.find("normal") != std::string::npos) return "normal";
    if (name.find("_disp.dds") != std::string::npos || name.find("height") != std::string::npos || name.find("displacement") != std::string::npos) return "height";
    if (name.find("_sp.dds") != std::string::npos || name.find("specular") != std::string::npos) return "specular";
    if (name.find("_ma.dds") != std::string::npos || name.find("_m.dds") != std::string::npos || name.find("material") != std::string::npos) return "material";
    if (name.find("_mg.dds") != std::string::npos || name.find("detail") != std::string::npos || name.find("grime") != std::string::npos || name.find("mask") != std::string::npos) return "detail";
    if (name.find("_o.dds") != std::string::npos || name.find("base") != std::string::npos || name.find("diffuse") != std::string::npos || name.find("albedo") != std::string::npos || name.find("texturelayer") != std::string::npos) return "base";
    return "base";
}

static bool role_is_technical_for_base(const std::string& role) {
    return role == "normal" || role == "height" || role == "material" || role == "detail" || role == "specular";
}

static std::string semantic_subtype_for_role(const std::string& role) {
    if (role == "normal") return "normal";
    if (role == "height") return "height";
    if (role == "specular") return "specular";
    if (role == "detail") return "detail_mask";
    if (role == "material") return "material_mask";
    return "base_color";
}

static std::vector<std::string> extract_dds_tokens(const std::string& text) {
    std::vector<std::string> tokens;
    std::set<std::string> seen;
    const std::regex pattern("([A-Za-z0-9_./\\\\-]+\\.dds)", std::regex_constants::icase);
    auto begin = std::sregex_iterator(text.begin(), text.end(), pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        std::string token = (*it)[1].str();
        std::replace(token.begin(), token.end(), '\\', '/');
        const std::string key = lower_copy(basename_from_path(token));
        if (!key.empty() && seen.insert(key).second) {
            tokens.push_back(token);
        }
    }
    return tokens;
}

struct SidecarTextureRef {
    std::string path;
    std::string parameter_name;
};

static std::vector<SidecarTextureRef> extract_sidecar_texture_refs(const std::string& text) {
    std::vector<SidecarTextureRef> refs;
    std::set<std::string> seen;
    const std::regex param_pattern(
        "<MaterialParameterTexture[^>]*(?:_name|StringItemID)=\"([^\"]*)\"[^>]*>[\\s\\S]*?<ResourceReferencePath_ITexture[^>]*_path=\"([^\"]+\\.dds)\"",
        std::regex_constants::icase
    );
    auto begin = std::sregex_iterator(text.begin(), text.end(), param_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        std::string parameter = (*it)[1].str();
        std::string path = (*it)[2].str();
        std::replace(path.begin(), path.end(), '\\', '/');
        const std::string key = lower_copy(path + "|" + parameter);
        if (seen.insert(key).second) refs.push_back(SidecarTextureRef{path, parameter});
    }
    if (!refs.empty()) return refs;
    for (const std::string& token : extract_dds_tokens(text)) {
        refs.push_back(SidecarTextureRef{token, basename_from_path(token)});
    }
    return refs;
}

static std::string extract_shader_family_hint(const std::string& text) {
    const std::regex material_name_pattern("_materialName=\"([^\"]+)\"", std::regex_constants::icase);
    std::smatch match;
    if (std::regex_search(text, match, material_name_pattern)) return match[1].str();
    const std::regex pattern("(SkinnedMesh(?:Skin|Standard(?:_Ver2)?|Cloth(?:_Ver2)?|Hair)|MultiTextured|Standard)", std::regex_constants::icase);
    if (std::regex_search(text, match, pattern)) return match[1].str();
    return "";
}

static std::string extracted_dds_path_for_entry(
    const ArchiveEntryRef& ref,
    const fs::path& cache_root,
    std::vector<std::string>& notes
) {
    if (ref.path.empty() || ref.extension != ".dds") return "";
    if (ref.compressed() && ref.comp_size != ref.orig_size) {
        // Sparse DDS often has the header and first payload bytes stored. Padding
        // is acceptable for preview, but fully compressed entries stay on Python.
    }
    std::vector<char> data;
    try {
        data = read_archive_ref_decoded_bytes(ref);
    } catch (const std::exception& exc) {
        notes.push_back("DDS read failed:" + ref.basename + ":" + exc.what());
        return "";
    }
    if (data.size() < 4 || std::string(data.data(), data.data() + 4) != "DDS ") {
        notes.push_back("DDS candidate skipped:missing header:" + ref.basename);
        return "";
    }
    if (ref.orig_size > data.size() && data.size() >= 128) {
        data.resize(static_cast<size_t>(ref.orig_size), 0);
        notes.push_back("DDS sparse padded:" + ref.basename);
    }
    const std::string identity = ref.pamt_path.string() + "|" + ref.path + "|" + std::to_string(ref.offset) + "|" + std::to_string(ref.comp_size) + "|" + std::to_string(ref.orig_size);
    const fs::path out_path = cache_root / "dds" / (hex64(fnv1a64(identity)) + "_" + safe_filename(ref.basename));
    try {
        if (!fs::is_regular_file(out_path) || fs::file_size(out_path) != data.size()) {
            write_binary(out_path, data);
        }
    } catch (const std::exception& exc) {
        notes.push_back("DDS cache write failed:" + ref.basename + ":" + exc.what());
        return "";
    }
    return fs::absolute(out_path).string();
}

static int material_match_score(const TextureBinding& binding, const NativeSubmesh& mesh, const std::string& desired_role) {
    int score = 0;
    if (binding.role == desired_role) score += 100;
    if (desired_role == "material" && (binding.role == "detail" || binding.role == "specular")) score += 16;
    if (desired_role == "base" && role_is_technical_for_base(binding.role)) score -= 200;
    const std::string material = lower_copy(mesh.material + " " + mesh.name);
    const std::string texture = lower_copy(binding.texture_name + " " + binding.archive_path);
    std::vector<std::string> material_tokens;
    std::string current;
    for (char ch : material) {
        if (std::isalnum(static_cast<unsigned char>(ch))) current.push_back(ch);
        else if (!current.empty()) {
            material_tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) material_tokens.push_back(current);
    for (const std::string& token : material_tokens) {
        if (token.size() >= 3 && texture.find(token) != std::string::npos) score += 12;
    }
    if (texture.find(material) != std::string::npos && !material.empty()) score += 40;
    return score;
}

static const TextureBinding* best_binding_for_role(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh,
    const std::string& desired_role
) {
    const TextureBinding* best = nullptr;
    int best_score = desired_role == "base" ? 40 : 20;
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty()) continue;
        const int score = material_match_score(binding, mesh, desired_role);
        if (score > best_score) {
            best_score = score;
            best = &binding;
        }
    }
    return best;
}

static std::vector<TextureBinding> build_material_bindings(
    const EntryJob& job,
    const PamtIndex& index,
    NativePackage& package
) {
    std::vector<TextureBinding> bindings;
    if (job.companion_entry.path.empty() || job.companion_entry.comp_size == 0) return bindings;
    std::vector<char> sidecar_bytes;
    try {
        sidecar_bytes = read_archive_ref_decoded_bytes(job.companion_entry);
    } catch (const std::exception& exc) {
        package.notes.push_back(std::string("native material sidecar read failed:") + exc.what());
        return bindings;
    }
    std::string sidecar_text(sidecar_bytes.begin(), sidecar_bytes.end());
    const std::string shader_family = extract_shader_family_hint(sidecar_text);
    const std::vector<SidecarTextureRef> refs = extract_sidecar_texture_refs(sidecar_text);
    package.dds_candidates = static_cast<int>(refs.size());
    std::vector<std::string> notes;
    for (const SidecarTextureRef& texture_ref : refs) {
        const std::string base = lower_copy(basename_from_path(texture_ref.path));
        auto it = index.by_basename.find(base);
        if (it == index.by_basename.end()) {
            continue;
        }
        const ArchiveEntryRef* selected = nullptr;
        for (const ArchiveEntryRef& ref : it->second) {
            if (lower_copy(ref.basename) == base) {
                selected = &ref;
                break;
            }
        }
        if (selected == nullptr && !it->second.empty()) selected = &it->second.front();
        if (selected == nullptr) continue;
        const std::string extracted = extracted_dds_path_for_entry(*selected, job.cache_root, notes);
        if (extracted.empty()) continue;
        TextureBinding binding;
        binding.role = texture_role_from_name(base);
        binding.source_path = extracted;
        binding.archive_path = selected->path;
        binding.texture_name = selected->basename;
        binding.parameter_name = texture_ref.parameter_name.empty() ? base : texture_ref.parameter_name;
        const std::string parameter_lower = lower_copy(binding.parameter_name);
        if (parameter_lower.find("normal") != std::string::npos) binding.role = "normal";
        else if (parameter_lower.find("height") != std::string::npos || parameter_lower.find("displacement") != std::string::npos) binding.role = "height";
        else if (parameter_lower.find("specular") != std::string::npos) binding.role = "specular";
        else if (parameter_lower.find("detail") != std::string::npos && parameter_lower.find("diffuse") != std::string::npos) binding.role = "base";
        else if (parameter_lower.find("overlaycolor") != std::string::npos) binding.role = "base";
        else if (parameter_lower.find("basecolor") != std::string::npos || parameter_lower.find("diffuse") != std::string::npos) binding.role = "base";
        else if (parameter_lower.find("mask") != std::string::npos || parameter_lower.find("material") != std::string::npos || parameter_lower.find("blending") != std::string::npos) binding.role = "material";
        binding.semantic_type = binding.role == "base" ? "albedo" : "material";
        binding.semantic_subtype = semantic_subtype_for_role(binding.role);
        binding.shader_family = shader_family;
        bindings.push_back(binding);
    }
    package.dds_extracted = static_cast<int>(bindings.size());
    package.material_index = bindings.empty() ? "sidecar_no_resolved_dds" : "pac_xml_dds_tokens";
    package.texture_resolution = bindings.empty() ? "none" : "same_pamt_basename";
    for (const std::string& note : notes) {
        package.notes.push_back(note);
    }
    return bindings;
}

static std::array<float, 3> color_for_batch(int index) {
    static const std::array<std::array<float, 3>, 8> colors = {{
        {0.78f, 0.62f, 0.44f},
        {0.58f, 0.68f, 0.78f},
        {0.68f, 0.55f, 0.44f},
        {0.64f, 0.64f, 0.56f},
        {0.55f, 0.72f, 0.62f},
        {0.76f, 0.58f, 0.62f},
        {0.62f, 0.60f, 0.78f},
        {0.72f, 0.70f, 0.60f},
    }};
    return colors[static_cast<size_t>(std::max(0, index)) % colors.size()];
}

static void append_float(std::vector<char>& out, float value) {
    const char* bytes = reinterpret_cast<const char*>(&value);
    out.insert(out.end(), bytes, bytes + sizeof(float));
}

static void append_int32(std::vector<char>& out, std::int32_t value) {
    const char* bytes = reinterpret_cast<const char*>(&value);
    out.insert(out.end(), bytes, bytes + sizeof(std::int32_t));
}

static void write_geometry_blob(
    const fs::path& geometry_path,
    const fs::path& identity_path,
    const NativeSubmesh& mesh,
    const Vec3& center,
    float scale,
    const std::array<float, 3>& color
) {
    std::vector<Vec3> tangents(mesh.positions.size());
    std::vector<Vec3> bitangents(mesh.positions.size());
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t i0 = mesh.indices[i];
        const std::uint32_t i1 = mesh.indices[i + 1];
        const std::uint32_t i2 = mesh.indices[i + 2];
        if (i0 >= mesh.positions.size() || i1 >= mesh.positions.size() || i2 >= mesh.positions.size()) continue;
        const Vec3 p0 = mesh.positions[i0];
        const Vec3 p1 = mesh.positions[i1];
        const Vec3 p2 = mesh.positions[i2];
        const Vec2 uv0 = i0 < mesh.uvs.size() ? mesh.uvs[i0] : Vec2{};
        const Vec2 uv1 = i1 < mesh.uvs.size() ? mesh.uvs[i1] : Vec2{};
        const Vec2 uv2 = i2 < mesh.uvs.size() ? mesh.uvs[i2] : Vec2{};
        const Vec3 e1 = vec_sub(p1, p0);
        const Vec3 e2 = vec_sub(p2, p0);
        const float du1 = uv1.x - uv0.x;
        const float dv1 = uv1.y - uv0.y;
        const float du2 = uv2.x - uv0.x;
        const float dv2 = uv2.y - uv0.y;
        const float denom = du1 * dv2 - du2 * dv1;
        if (std::abs(denom) < 1.0e-8f) continue;
        const float r = 1.0f / denom;
        const Vec3 tangent = vec_mul(vec_sub(vec_mul(e1, dv2), vec_mul(e2, dv1)), r);
        const Vec3 bitangent = vec_mul(vec_sub(vec_mul(e2, du1), vec_mul(e1, du2)), r);
        tangents[i0] = vec_add(tangents[i0], tangent);
        tangents[i1] = vec_add(tangents[i1], tangent);
        tangents[i2] = vec_add(tangents[i2], tangent);
        bitangents[i0] = vec_add(bitangents[i0], bitangent);
        bitangents[i1] = vec_add(bitangents[i1], bitangent);
        bitangents[i2] = vec_add(bitangents[i2], bitangent);
    }

    std::vector<char> geometry;
    std::vector<char> identity;
    geometry.reserve(mesh.indices.size() * 23u * 4u);
    identity.reserve(mesh.indices.size() * 8u);
    for (size_t tri = 0; tri + 2 < mesh.indices.size(); tri += 3) {
        const std::uint32_t indices[3] = {mesh.indices[tri], mesh.indices[tri + 1], mesh.indices[tri + 2]};
        for (int corner = 0; corner < 3; ++corner) {
            const std::uint32_t vi = indices[corner];
            const Vec3 raw_position = mesh.positions[vi];
            const Vec3 position = vec_mul(vec_sub(raw_position, center), scale);
            const Vec3 normal = vec_normalize(vi < mesh.normals.size() ? mesh.normals[vi] : Vec3{0.0f, 1.0f, 0.0f});
            Vec3 tangent = vec_normalize(vi < tangents.size() ? tangents[vi] : Vec3{}, Vec3{});
            Vec3 bitangent = vec_normalize(vi < bitangents.size() ? bitangents[vi] : Vec3{}, Vec3{});
            if (vec_dot(tangent, tangent) <= 1.0e-8f) {
                const Vec3 up = std::abs(normal.y) < 0.9f ? Vec3{0.0f, 1.0f, 0.0f} : Vec3{1.0f, 0.0f, 0.0f};
                tangent = vec_normalize(vec_cross(up, normal), Vec3{1.0f, 0.0f, 0.0f});
            }
            if (vec_dot(bitangent, bitangent) <= 1.0e-8f) {
                bitangent = vec_normalize(vec_cross(normal, tangent), Vec3{0.0f, 0.0f, 1.0f});
            }
            const Vec2 uv = vi < mesh.uvs.size() ? mesh.uvs[vi] : Vec2{};
            const float bary[3] = {corner == 0 ? 1.0f : 0.0f, corner == 1 ? 1.0f : 0.0f, corner == 2 ? 1.0f : 0.0f};
            for (float value : {
                position.x, position.y, position.z,
                normal.x, normal.y, normal.z,
                color[0], color[1], color[2],
                uv.x, uv.y,
                tangent.x, tangent.y, tangent.z,
                bitangent.x, bitangent.y, bitangent.z,
                normal.x, normal.y, normal.z,
                bary[0], bary[1], bary[2],
            }) {
                append_float(geometry, value);
            }
            append_int32(identity, static_cast<std::int32_t>(mesh.source_submesh_index));
            append_int32(identity, static_cast<std::int32_t>(vi));
        }
    }
    write_binary(geometry_path, geometry);
    write_binary(identity_path, identity);
}

static std::string dds_entry_json(const TextureBinding* binding, const std::string& slot) {
    if (binding == nullptr || binding->source_path.empty()) return "";
    std::ostringstream out;
    out << "\"" << json_escape(slot) << "\":{"
        << "\"slot\":\"" << json_escape(slot) << "\","
        << "\"source_path\":\"" << json_escape(binding->source_path) << "\","
        << "\"archive_path\":\"" << json_escape(binding->archive_path) << "\","
        << "\"parameter_name\":\"" << json_escape(binding->parameter_name) << "\","
        << "\"semantic_type\":\"" << json_escape(binding->semantic_type) << "\","
        << "\"semantic_subtype\":\"" << json_escape(binding->semantic_subtype) << "\","
        << "\"available\":true,"
        << "\"direct_upload_candidate\":true"
        << "}";
    return out.str();
}

static std::string batch_stem(size_t batch_index) {
    std::ostringstream out;
    out << "batch_" << std::setw(3) << std::setfill('0') << batch_index;
    return out.str();
}

static NativePackage write_d3d11_package(
    const EntryJob& job,
    const std::vector<NativeSubmesh>& submeshes,
    const std::vector<TextureBinding>& bindings,
    NativePackage package
) {
    if (submeshes.empty()) throw std::runtime_error("native package writer received no submeshes");
    const fs::path package_dir = job.output_root;
    const fs::path geometry_dir = package_dir / "geometry";
    fs::create_directories(geometry_dir);
    Vec3 min_v{1.0e30f, 1.0e30f, 1.0e30f};
    Vec3 max_v{-1.0e30f, -1.0e30f, -1.0e30f};
    int source_vertex_total = 0;
    int face_total = 0;
    for (const NativeSubmesh& mesh : submeshes) {
        source_vertex_total += static_cast<int>(mesh.positions.size());
        face_total += static_cast<int>(mesh.indices.size() / 3u);
        for (const Vec3& p : mesh.positions) {
            min_v.x = std::min(min_v.x, p.x); min_v.y = std::min(min_v.y, p.y); min_v.z = std::min(min_v.z, p.z);
            max_v.x = std::max(max_v.x, p.x); max_v.y = std::max(max_v.y, p.y); max_v.z = std::max(max_v.z, p.z);
        }
    }
    const Vec3 center{(min_v.x + max_v.x) * 0.5f, (min_v.y + max_v.y) * 0.5f, (min_v.z + max_v.z) * 0.5f};
    const float max_dim = std::max({max_v.x - min_v.x, max_v.y - min_v.y, max_v.z - min_v.z, 1.0e-6f});
    const float scale = 2.0f / max_dim;

    std::ostringstream batches_json;
    int emitted_batch_count = 0;
    int emitted_vertex_count = 0;
    for (size_t batch_index = 0; batch_index < submeshes.size(); ++batch_index) {
        const NativeSubmesh& mesh = submeshes[batch_index];
        if (mesh.indices.size() < 3) continue;
        const std::string stem = batch_stem(batch_index);
        const fs::path geometry_path = geometry_dir / (stem + ".bin");
        const fs::path identity_path = geometry_dir / (stem + "_identity.bin");
        const auto color = color_for_batch(static_cast<int>(batch_index));
        write_geometry_blob(geometry_path, identity_path, mesh, center, scale, color);
        const int vertex_count = static_cast<int>(mesh.indices.size());
        emitted_vertex_count += vertex_count;
        const TextureBinding* base = best_binding_for_role(bindings, mesh, "base");
        const TextureBinding* normal = best_binding_for_role(bindings, mesh, "normal");
        const TextureBinding* material = best_binding_for_role(bindings, mesh, "material");
        const TextureBinding* height = best_binding_for_role(bindings, mesh, "height");
        if (emitted_batch_count++) batches_json << ",";
        batches_json << "{"
            << "\"index\":" << batch_index << ","
            << "\"material_name\":\"" << json_escape(mesh.material) << "\","
            << "\"texture_name\":\"" << json_escape(mesh.material.empty() ? mesh.name : mesh.material) << "\","
            << "\"vertex_file\":\"" << json_escape(geometry_path.lexically_relative(package_dir).generic_string()) << "\","
            << "\"vertex_count\":" << vertex_count << ","
            << "\"editor_identity\":{\"source_submesh_index\":" << mesh.source_submesh_index
            << ",\"identity_file\":\"" << json_escape(identity_path.lexically_relative(package_dir).generic_string()) << "\"},"
            << "\"base_color\":[" << color[0] << "," << color[1] << "," << color[2] << "],"
            << "\"textures\":{},"
            << "\"dds_textures\":{";
        bool wrote_slot = false;
        for (const auto& slot_pair : std::vector<std::pair<std::string, const TextureBinding*>>{
            {"base", base},
            {"normal", normal},
            {"material", material},
            {"height", height},
        }) {
            const std::string slot_json = dds_entry_json(slot_pair.second, slot_pair.first);
            if (slot_json.empty()) continue;
            if (wrote_slot) batches_json << ",";
            batches_json << slot_json;
            wrote_slot = true;
        }
        if (!bindings.empty()) {
            if (wrote_slot) batches_json << ",";
            batches_json << "\"material_inputs\":[";
            bool first_input = true;
            for (const TextureBinding& binding : bindings) {
                if (binding.source_path.empty()) continue;
                if (!first_input) batches_json << ",";
                first_input = false;
                batches_json << "{"
                    << "\"slot\":\"" << json_escape(binding.role) << "\","
                    << "\"source_path\":\"" << json_escape(binding.source_path) << "\","
                    << "\"archive_path\":\"" << json_escape(binding.archive_path) << "\","
                    << "\"parameter_name\":\"" << json_escape(binding.parameter_name) << "\","
                    << "\"semantic_type\":\"" << json_escape(binding.semantic_type) << "\","
                    << "\"semantic_subtype\":\"" << json_escape(binding.semantic_subtype) << "\","
                    << "\"material_name\":\"" << json_escape(mesh.material) << "\","
                    << "\"shader_family\":\"" << json_escape(binding.shader_family) << "\","
                    << "\"available\":true,"
                    << "\"direct_upload_candidate\":true"
                    << "}";
            }
            batches_json << "]";
        }
        batches_json << "},"
            << "\"texture_flip_vertical\":true,"
            << "\"has_texture_coordinates\":true,"
            << "\"tangents_usable\":true,"
            << "\"normal_strength\":1.0,"
            << "\"height_amount\":0.04,"
            << "\"roughness\":0.45,"
            << "\"metalness\":0.0,"
            << "\"specular\":0.45,"
            << "\"height_scale\":0.35,"
            << "\"native_material_hints\":{\"shader_family\":\"" << json_escape(bindings.empty() ? "" : bindings.front().shader_family) << "\",\"roughness\":0.45,\"specular\":0.45,\"height_scale\":0.35},"
            << "\"notes\":[\"generated by cdmw-preview-core native PAC path\"],"
            << "\"material_combiner_active\":false,"
            << "\"material_combiner_outputs\":[],"
            << "\"material_combiner_decode_modes\":[\"direct_dds_sidecar\"]"
            << "}";
    }
    package.path = package_dir;
    package.batch_count = emitted_batch_count;
    package.vertex_count = emitted_vertex_count;
    package.face_count = face_total;
    std::ostringstream manifest;
    manifest << "{"
        << "\"schema_version\":" << std::max(4, job.schema_version) << ","
        << "\"backend\":\"d3d11\","
        << "\"source_path\":\"" << json_escape(job.path) << "\","
        << "\"format\":\"pac\","
        << "\"summary\":\"Native preview-core PAC package\","
        << "\"mesh_count\":" << emitted_batch_count << ","
        << "\"source_vertex_count\":" << source_vertex_total << ","
        << "\"vertex_count\":" << emitted_vertex_count << ","
        << "\"face_count\":" << face_total << ","
        << "\"normalization_center\":[" << center.x << "," << center.y << "," << center.z << "],"
        << "\"normalization_scale\":" << scale << ","
        << "\"orbit_sensitivity\":0.22,"
        << "\"pan_sensitivity\":0.60,"
        << "\"invert_orbit_x\":false,"
        << "\"invert_orbit_y\":false,"
        << "\"invert_pan_x\":false,"
        << "\"invert_pan_y\":false,"
        << "\"max_anisotropy\":16,"
        << "\"ambient_strength\":0.32,"
        << "\"diffuse_light_scale\":0.92,"
        << "\"specular_base\":0.10,"
        << "\"specular_max\":0.72,"
        << "\"shininess_min\":18.0,"
        << "\"shininess_max\":180.0,"
        << "\"use_textures\":true,"
        << "\"high_quality_textures\":true,"
        << "\"native_preview_core\":{\"mesh_parse\":\"" << json_escape(package.mesh_parse) << "\",\"material_index\":\"" << json_escape(package.material_index) << "\",\"texture_resolution\":\"" << json_escape(package.texture_resolution) << "\"},"
        << "\"batches\":[" << batches_json.str() << "]"
        << "}";
    write_text(package_dir / "manifest.json", manifest.str());
    return package;
}

static NativePackage try_generate_native_package(const EntryJob& job, const std::vector<char>& data) {
    NativePackage package;
    if (job.extension != ".pac") {
        throw std::runtime_error("native preview-core package generation currently supports PAC first; PAM/PAMLOD still use Python fallback");
    }
    std::vector<NativeSubmesh> submeshes = parse_pac_submeshes(data);
    package.mesh_parse = "native_pac_par_sections";
    const PamtIndex& index = cached_pamt_index(job.entry.pamt_path);
    std::vector<TextureBinding> bindings = build_material_bindings(job, index, package);
    if (!job.companion_entry.path.empty() && bindings.empty()) {
        throw std::runtime_error("native PAC geometry parsed, but no reliable DDS sidecar bindings were resolved; using Python material fallback");
    }
    if (bindings.empty()) {
        package.material_index = "none";
        package.texture_resolution = "none";
    }
    return write_d3d11_package(job, submeshes, bindings, package);
}

std::string preview_report_for_job(const fs::path& job_path) {
    const auto started = std::chrono::steady_clock::now();
    EntryJob job = parse_job(job_path);
    std::string status = "unsupported";
    std::string fallback_reason;
    std::string message;
    std::string format_fourcc;
    std::uint64_t bytes_read = 0;
    const int compression_type = static_cast<int>(job.flags & 0x0F);
    bool raw_read_ok = false;
    NativePackage package;
    try {
        fs::create_directories(job.output_root);
        fs::create_directories(job.cache_root);
        auto data = read_entry_decoded_bytes(job);
        bytes_read = static_cast<std::uint64_t>(data.size());
        format_fourcc = fourcc_from_bytes(data);
        raw_read_ok = true;
        if (job.extension != ".pam" && job.extension != ".pamlod" && job.extension != ".pac") {
            fallback_reason = "selected entry is not a native-preview-core model target";
        } else if (compression_type != 0 && compression_type != 1 && compression_type != 2 && job.comp_size != job.orig_size) {
            fallback_reason = "native decompression/reconstruction is not enabled for this milestone";
        } else {
            try {
                package = try_generate_native_package(job, data);
                if (package.batch_count > 0 && !package.path.empty()) {
                    status = "ok";
                    fallback_reason.clear();
                    message = "native preview-core generated a D3D11 package";
                } else {
                    fallback_reason = "native preview-core generated no renderable batches";
                }
            } catch (const std::exception& native_exc) {
                fallback_reason = native_exc.what();
            }
        }
        if (message.empty()) {
            message = status == "ok"
                ? "native preview-core generated a D3D11 package"
                : "native archive IO completed; Python preview fallback remains active";
        }
    } catch (const std::exception& exc) {
        status = "error";
        fallback_reason = exc.what();
        message = "native archive IO preflight failed";
    }
    const double elapsed_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started).count();
    std::ostringstream out;
    out << "{"
        << "\"status\":\"" << json_escape(status) << "\","
        << "\"backend\":\"cdmw_preview_core_0.1\","
        << "\"native_archive_io\":\"" << (raw_read_ok ? "ok" : "failed") << "\","
        << "\"native_mesh_parser\":\"" << json_escape(package.mesh_parse.empty() ? "pending" : package.mesh_parse) << "\","
        << "\"native_material_index\":\"" << json_escape(package.material_index.empty() ? "pending" : package.material_index) << "\","
        << "\"native_texture_resolution\":\"" << json_escape(package.texture_resolution.empty() ? "pending" : package.texture_resolution) << "\","
        << "\"schema_version\":" << job.schema_version << ","
        << "\"entry_path\":\"" << json_escape(job.path) << "\","
        << "\"extension\":\"" << json_escape(job.extension) << "\","
        << "\"format_fourcc\":\"" << json_escape(format_fourcc) << "\","
        << "\"compression_type\":" << compression_type << ","
        << "\"bytes_read\":" << bytes_read << ","
        << "\"batch_count\":" << package.batch_count << ","
        << "\"vertex_count\":" << package.vertex_count << ","
        << "\"face_count\":" << package.face_count << ","
        << "\"dds_candidates\":" << package.dds_candidates << ","
        << "\"dds_extracted\":" << package.dds_extracted << ","
        << "\"elapsed_ms\":" << elapsed_ms << ","
        << "\"package_path\":\"" << json_escape(status == "ok" ? package.path.string() : "") << "\","
        << "\"fallback_reason\":\"" << json_escape(fallback_reason) << "\","
        << "\"message\":\"" << json_escape(message) << "\","
        << "\"notes\":[";
    for (size_t i = 0; i < package.notes.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(package.notes[i]) << "\"";
    }
    out << "]"
        << "}";
    return out.str();
}

int run_preview_job(const fs::path& job_path, const fs::path& report_path) {
    try {
        write_text(report_path, preview_report_for_job(job_path));
        return 0;
    } catch (const std::exception& exc) {
        std::ostringstream out;
        out << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\""
            << json_escape(exc.what()) << "\",\"fallback_reason\":\"" << json_escape(exc.what()) << "\"}";
        try {
            write_text(report_path, out.str());
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

std::string extract_line_path(const std::string& line, const std::string& key) {
    std::string value = find_string_value(line, key);
    if (!value.empty()) return value;
    return {};
}

int run_service() {
    std::cout << "{\"event\":\"ready\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
    std::string line;
    while (std::getline(std::cin, line)) {
        const std::string lowered = lower_copy(line);
        if (lowered.find("\"shutdown\"") != std::string::npos) {
            std::cout << "{\"event\":\"closed\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
            return 0;
        }
        if (lowered.find("\"ping\"") != std::string::npos) {
            std::cout << "{\"event\":\"pong\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
            continue;
        }
        const std::string job_path = extract_line_path(line, "job_path");
        const std::string report_path = extract_line_path(line, "report_path");
        if (!job_path.empty() && !report_path.empty()) {
            run_preview_job(fs::path(job_path), fs::path(report_path));
            try {
                std::cout << read_text(fs::path(report_path)) << std::endl;
            } catch (...) {
                std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\"report readback failed\"}" << std::endl;
            }
            continue;
        }
        std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\"unknown command\"}" << std::endl;
    }
    return 0;
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc >= 2 && std::string(argv[1]) == "self-test") {
            std::cout << "{\"event\":\"self_test\",\"ok\":true,\"backend\":\"cdmw_preview_core_0.1\"}\n";
            return 0;
        }
        if (argc >= 2 && std::string(argv[1]) == "--service") {
            return run_service();
        }
        if (argc >= 4 && std::string(argv[1]) == "preview-job") {
            return run_preview_job(fs::path(argv[2]), fs::path(argv[3]));
        }
        std::cerr << "usage: cdmw-preview-core self-test | --service | preview-job <job.json> <report.json>\n";
        return 1;
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << "\n";
        return 2;
    }
}
