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
#include <limits>
#include <map>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

#include "../../common/native_diagnostics.h"

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

static std::string dirname_from_path(const std::string& path) {
    const size_t slash = path.find_last_of("/\\");
    return slash == std::string::npos ? "" : path.substr(0, slash);
}

static std::string stem_from_path(const std::string& path) {
    std::string base = basename_from_path(path);
    const std::string ext = extension_from_path(base);
    if (!ext.empty() && base.size() > ext.size()) {
        base.resize(base.size() - ext.size());
    }
    return base;
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
    fs::path package_root;
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
    std::vector<std::int32_t> source_vertex_indices;
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
    std::string shader_rule;
    std::string material_name;
    std::string sidecar_path;
    std::string sidecar_kind;
    std::string linked_mesh_path;
    std::string packed_channels;
    std::string material_output_quality = "inferred";
    std::string srgb_mode = "auto";
    std::string parameter_declared_by;
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
    std::string material_output_quality = "approximate";
    std::vector<std::string> notes;
    int lod_count = 0;
};

static std::uint16_t read_u16(const std::vector<char>& data, size_t offset) {
    if (offset + 2 > data.size()) throw std::runtime_error("u16 read outside buffer");
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint16_t>(p[0] | (p[1] << 8));
}

static std::int16_t read_i16(const std::vector<char>& data, size_t offset) {
    return static_cast<std::int16_t>(read_u16(data, offset));
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

static std::string read_c_string(const std::vector<char>& data, size_t offset, size_t max_length) {
    if (offset >= data.size()) return "";
    const size_t limit = std::min(data.size(), offset + max_length);
    size_t end = offset;
    while (end < limit && data[end] != '\0') ++end;
    if (end <= offset) return "";
    std::string out(data.data() + offset, data.data() + end);
    out.erase(std::remove_if(out.begin(), out.end(), [](unsigned char ch) {
        return ch < 0x20 || ch > 0x7E;
    }), out.end());
    return out;
}

static bool looks_like_dds_string(const std::vector<char>& data, size_t offset, size_t max_length = 256) {
    if (offset >= data.size()) return false;
    if (offset > 0) {
        const unsigned char previous = static_cast<unsigned char>(data[offset - 1]);
        if (previous >= 32 && previous <= 126) return false;
    }
    const size_t limit = std::min(data.size(), offset + max_length);
    size_t end = offset;
    while (end < limit && data[end] != '\0') ++end;
    const size_t length = end - offset;
    if (length <= 4 || length > 255) return false;
    std::string text(data.data() + offset, data.data() + end);
    return lower_copy(text).ends_with(".dds");
}

EntryJob parse_job(const fs::path& job_path) {
    const std::string text = read_text(job_path);
    EntryJob job;
    job.output_root = fs::path(find_string_value(text, "output_root"));
    job.cache_root = fs::path(find_string_value(text, "cache_root"));
    job.package_root = fs::path(find_string_value(text, "package_root"));
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

static std::string archive_ref_identity(const ArchiveEntryRef& entry) {
    return entry.pamt_path.string() + "|" + entry.paz_file.string() + "|" + entry.path + "|" +
        std::to_string(entry.offset) + "|" + std::to_string(entry.comp_size) + "|" +
        std::to_string(entry.orig_size) + "|" + std::to_string(entry.flags) + "|" +
        std::to_string(entry.paz_index);
}

struct DecodedEntryCacheValue {
    std::vector<char> bytes;
    size_t last_used = 0;
};

static std::unordered_map<std::string, DecodedEntryCacheValue> g_decoded_entry_cache;
static size_t g_decoded_entry_cache_bytes = 0;
static size_t g_decoded_entry_cache_clock = 0;
static std::uint64_t g_decoded_entry_cache_hits = 0;
static std::uint64_t g_decoded_entry_cache_misses = 0;
static std::uint64_t g_decoded_entry_cache_evictions = 0;
static constexpr size_t kDecodedEntryCacheMaxEntries = 1024;
static constexpr size_t kDecodedEntryCacheMaxBytes = 512ull * 1024ull * 1024ull;
static constexpr size_t kDecodedEntryCacheMaxSingleBytes = 64ull * 1024ull * 1024ull;

static size_t decoded_entry_cache_entries() {
    return g_decoded_entry_cache.size();
}

static size_t decoded_entry_cache_bytes() {
    return g_decoded_entry_cache_bytes;
}

static std::uint64_t decoded_entry_cache_hits() {
    return g_decoded_entry_cache_hits;
}

static std::uint64_t decoded_entry_cache_misses() {
    return g_decoded_entry_cache_misses;
}

static std::uint64_t decoded_entry_cache_evictions() {
    return g_decoded_entry_cache_evictions;
}

static void prune_decoded_entry_cache() {
    while (
        g_decoded_entry_cache.size() > kDecodedEntryCacheMaxEntries ||
        g_decoded_entry_cache_bytes > kDecodedEntryCacheMaxBytes
    ) {
        auto oldest = g_decoded_entry_cache.end();
        size_t oldest_tick = std::numeric_limits<size_t>::max();
        for (auto it = g_decoded_entry_cache.begin(); it != g_decoded_entry_cache.end(); ++it) {
            if (it->second.last_used < oldest_tick) {
                oldest_tick = it->second.last_used;
                oldest = it;
            }
        }
        if (oldest == g_decoded_entry_cache.end()) break;
        g_decoded_entry_cache_bytes -= oldest->second.bytes.size();
        g_decoded_entry_cache.erase(oldest);
        ++g_decoded_entry_cache_evictions;
    }
}

static std::vector<char> read_archive_ref_decoded_bytes(const ArchiveEntryRef& entry) {
    const std::string key = archive_ref_identity(entry);
    auto found = g_decoded_entry_cache.find(key);
    if (found != g_decoded_entry_cache.end()) {
        ++g_decoded_entry_cache_hits;
        found->second.last_used = ++g_decoded_entry_cache_clock;
        return found->second.bytes;
    }
    ++g_decoded_entry_cache_misses;
    std::vector<char> decoded = decode_archive_ref_bytes(entry, read_archive_ref_raw_bytes(entry));
    if (decoded.size() <= kDecodedEntryCacheMaxSingleBytes) {
        g_decoded_entry_cache_bytes += decoded.size();
        g_decoded_entry_cache.emplace(key, DecodedEntryCacheValue{decoded, ++g_decoded_entry_cache_clock});
        prune_decoded_entry_cache();
    }
    return decoded;
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
    std::vector<ArchiveEntryRef> material_sidecars;
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
        if (
            ref.extension == ".pami" ||
            ref.extension == ".pac_xml" ||
            ref.extension == ".pam_xml" ||
            ref.extension == ".pamlod_xml" ||
            ref.extension == ".material" ||
            ref.extension == ".technique" ||
            ref.extension == ".prefab"
        ) {
            index.material_sidecars.push_back(ref);
        }
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
        mesh.source_vertex_indices.push_back(static_cast<std::int32_t>(vi));
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
        const size_t voff = vertex_base + static_cast<size_t>(source_index) * static_cast<size_t>(stride);
        if (voff + 6 > data.size()) continue;
        source_to_local[source_index] = static_cast<std::uint32_t>(mesh.positions.size());
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
        if (a->second == b->second || b->second == c->second || a->second == c->second) continue;
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
        const int vertex_index = static_cast<int>(source_index) - global_vertex_base;
        if (vertex_index < 0) continue;
        const size_t voff = static_cast<size_t>(geom_offset) + static_cast<size_t>(vertex_index) * 6u;
        if (voff + 6 > data.size()) continue;
        source_to_local[source_index] = static_cast<std::uint32_t>(mesh.positions.size());
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
        if (a->second == b->second || b->second == c->second || a->second == c->second) continue;
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
        bool ok = true;
        for (const RawPamEntry& entry : entries) {
            if (!indices_fit_vertex_count(data, index_block + static_cast<size_t>(entry.index_element_offset) * 2u, entry.index_count, entry.vertex_count)) {
                ok = false;
                break;
            }
        }
        if (ok) return std::make_pair(stride, index_block);
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
            finalize_native_meshes(meshes);
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
    finalize_native_meshes(local_meshes);
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
    for (const std::vector<RawPamEntry>& group : groups) {
        auto layout = find_pamlod_group_layout(data, cursor, group);
        if (!layout.has_value()) continue;
        const size_t vertex_base = std::get<0>(*layout);
        const int stride = std::get<1>(*layout);
        const size_t index_offset = std::get<2>(*layout);
        std::vector<NativeSubmesh> meshes;
        for (const RawPamEntry& raw : group) {
            meshes.push_back(parse_quantized_pam_mesh(
                data,
                raw,
                vertex_base + static_cast<size_t>(raw.vertex_element_offset) * static_cast<size_t>(stride),
                index_offset + static_cast<size_t>(raw.index_element_offset) * 2u,
                stride,
                bbox_min,
                bbox_max
            ));
        }
        finalize_native_meshes(meshes);
        if (!meshes.empty()) return NativeMeshParseResult{std::move(meshes), "native_pamlod_lod0", static_cast<int>(groups.size())};
        std::uint64_t total_indices = 0;
        for (const RawPamEntry& raw : group) total_indices += raw.index_count;
        cursor = index_offset + static_cast<size_t>(total_indices) * 2u;
    }
    throw std::runtime_error("native PAMLOD parser found no renderable LOD geometry");
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
    std::string material_name;
    std::string shader_family;
};

static std::string extract_shader_family_hint(const std::string& text) {
    const std::regex material_name_pattern("_materialName=\"([^\"]+)\"", std::regex_constants::icase);
    std::smatch match;
    if (std::regex_search(text, match, material_name_pattern)) return match[1].str();
    const std::regex pattern("(SkinnedMesh(?:Skin|Standard(?:_Ver2)?|Cloth(?:_Ver2)?|Hair)|MultiTextured|Standard)", std::regex_constants::icase);
    if (std::regex_search(text, match, pattern)) return match[1].str();
    return "";
}

static std::string xml_attr_value(const std::string& text, std::initializer_list<const char*> names) {
    for (const char* raw_name : names) {
        const std::string name(raw_name);
        const std::regex pattern("(?:^|\\s)" + name + "=\"([^\"]*)\"", std::regex_constants::icase);
        std::smatch match;
        if (std::regex_search(text, match, pattern)) return match[1].str();
    }
    return "";
}

struct TechniqueParameterInfo {
    std::string name;
    std::string type;
    std::string srgb;
    std::string default_value;
    bool declared = false;
};

struct TechniqueIndex {
    std::unordered_map<std::string, TechniqueParameterInfo> parameters_by_name;
    std::set<std::string> technique_names;
    int files_scanned = 0;
    int parameters = 0;
    int texture_parameters = 0;
};

static void add_technique_parameter(TechniqueIndex& index, const std::string& tag) {
    TechniqueParameterInfo info;
    info.name = xml_attr_value(tag, {"Name", "_name"});
    if (info.name.empty()) return;
    info.type = xml_attr_value(tag, {"Type", "_type"});
    info.srgb = xml_attr_value(tag, {"sRGB", "SRGB", "Srgb"});
    info.default_value = xml_attr_value(tag, {"DefaultValue", "Value", "_defaultValue"});
    info.declared = true;
    ++index.parameters;
    const std::string key = lower_copy(info.name);
    const std::string type_lower = lower_copy(info.type);
    if (type_lower.find("texture") != std::string::npos || key.find("texture") != std::string::npos) {
        ++index.texture_parameters;
    }
    auto found = index.parameters_by_name.find(key);
    if (found == index.parameters_by_name.end()) {
        index.parameters_by_name.emplace(key, info);
    } else {
        if (found->second.srgb.empty()) found->second.srgb = info.srgb;
        if (found->second.type.empty()) found->second.type = info.type;
        if (found->second.default_value.empty()) found->second.default_value = info.default_value;
    }
}

static TechniqueIndex build_technique_index_for_pamt(const PamtIndex& pamt_index) {
    TechniqueIndex index;
    const std::regex technique_tag_pattern("<Technique\\b[^>]*>", std::regex_constants::icase);
    const std::regex parameter_tag_pattern("<Parameter\\b[^>]*(?:/>|>[\\s\\S]*?</Parameter\\s*>)", std::regex_constants::icase);
    for (const ArchiveEntryRef& ref : pamt_index.material_sidecars) {
        if (ref.extension != ".technique" && ref.extension != ".material") continue;
        std::vector<char> bytes;
        try {
            bytes = read_archive_ref_decoded_bytes(ref);
        } catch (...) {
            continue;
        }
        ++index.files_scanned;
        const std::string text(bytes.begin(), bytes.end());
        auto technique_begin = std::sregex_iterator(text.begin(), text.end(), technique_tag_pattern);
        auto technique_end = std::sregex_iterator();
        for (auto it = technique_begin; it != technique_end; ++it) {
            const std::string name = xml_attr_value(it->str(), {"Name"});
            if (!name.empty()) index.technique_names.insert(name);
        }
        auto parameter_begin = std::sregex_iterator(text.begin(), text.end(), parameter_tag_pattern);
        auto parameter_end = std::sregex_iterator();
        for (auto it = parameter_begin; it != parameter_end; ++it) {
            add_technique_parameter(index, it->str());
        }
    }
    return index;
}

static void merge_technique_index(TechniqueIndex& destination, const TechniqueIndex& source) {
    destination.files_scanned += source.files_scanned;
    destination.parameters += source.parameters;
    destination.texture_parameters += source.texture_parameters;
    destination.technique_names.insert(source.technique_names.begin(), source.technique_names.end());
    for (const auto& [key, value] : source.parameters_by_name) {
        auto found = destination.parameters_by_name.find(key);
        if (found == destination.parameters_by_name.end()) {
            destination.parameters_by_name.emplace(key, value);
        } else {
            if (found->second.srgb.empty()) found->second.srgb = value.srgb;
            if (found->second.type.empty()) found->second.type = value.type;
            if (found->second.default_value.empty()) found->second.default_value = value.default_value;
        }
    }
}

static const TechniqueIndex& cached_technique_index(const PamtIndex& pamt_index) {
    static std::map<std::string, TechniqueIndex> cache;
    const std::string key = fs::absolute(pamt_index.pamt_path).string();
    auto it = cache.find(key);
    if (it == cache.end()) {
        it = cache.emplace(key, build_technique_index_for_pamt(pamt_index)).first;
    }
    return it->second;
}

static std::vector<fs::path> package_root_pamt_paths(const fs::path& package_root) {
    std::vector<fs::path> paths;
    if (package_root.empty()) return paths;
    std::error_code ec;
    if (fs::is_regular_file(package_root, ec) && package_root.extension() == ".pamt") {
        paths.push_back(package_root);
        return paths;
    }
    if (!fs::is_directory(package_root, ec)) return paths;
    for (const fs::directory_entry& root_entry : fs::directory_iterator(package_root, ec)) {
        if (ec) break;
        if (root_entry.is_regular_file(ec) && root_entry.path().extension() == ".pamt") {
            paths.push_back(root_entry.path());
        } else if (root_entry.is_directory(ec)) {
            std::error_code inner_ec;
            for (const fs::directory_entry& child : fs::directory_iterator(root_entry.path(), inner_ec)) {
                if (inner_ec) break;
                if (child.is_regular_file(inner_ec) && child.path().extension() == ".pamt") {
                    paths.push_back(child.path());
                }
            }
        }
        if (paths.size() >= 64) break;
    }
    std::sort(paths.begin(), paths.end());
    paths.erase(std::unique(paths.begin(), paths.end()), paths.end());
    return paths;
}

static const TechniqueIndex& cached_package_technique_index(
    const EntryJob& job,
    const PamtIndex& primary_index
) {
    if (job.package_root.empty()) {
        return cached_technique_index(primary_index);
    }
    static std::map<std::string, TechniqueIndex> cache;
    const std::string key = fs::absolute(job.package_root).string();
    auto found = cache.find(key);
    if (found != cache.end()) return found->second;
    TechniqueIndex combined;
    std::set<std::string> seen_pamts;
    merge_technique_index(combined, cached_technique_index(primary_index));
    seen_pamts.insert(fs::absolute(primary_index.pamt_path).string());
    for (const fs::path& pamt_path : package_root_pamt_paths(job.package_root)) {
        const std::string pamt_key = fs::absolute(pamt_path).string();
        if (!seen_pamts.insert(pamt_key).second) continue;
        try {
            merge_technique_index(combined, cached_technique_index(cached_pamt_index(pamt_path)));
        } catch (...) {
        }
    }
    return cache.emplace(key, std::move(combined)).first->second;
}

static const TechniqueParameterInfo* technique_parameter_for_name(
    const TechniqueIndex& index,
    const std::string& parameter_name
) {
    if (parameter_name.empty()) return nullptr;
    auto found = index.parameters_by_name.find(lower_copy(parameter_name));
    if (found == index.parameters_by_name.end()) return nullptr;
    return &found->second;
}

static std::string srgb_mode_for_role(
    const std::string& role,
    const TechniqueParameterInfo* technique_parameter
) {
    if (technique_parameter != nullptr && !technique_parameter->srgb.empty()) {
        const std::string srgb = lower_copy(technique_parameter->srgb);
        if (srgb == "true" || srgb == "1" || srgb == "yes") return "srgb";
        if (srgb == "false" || srgb == "0" || srgb == "no") return "linear";
    }
    return role == "base" ? "srgb" : "linear";
}

static void add_sidecar_texture_ref(
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen,
    std::string path,
    std::string parameter,
    const std::string& material_name,
    const std::string& shader_family
) {
    std::replace(path.begin(), path.end(), '\\', '/');
    if (lower_copy(path).find(".dds") == std::string::npos) return;
    if (parameter.empty()) parameter = basename_from_path(path);
    const std::string key = lower_copy(path + "|" + parameter + "|" + material_name + "|" + shader_family);
    if (seen.insert(key).second) {
        refs.push_back(SidecarTextureRef{path, parameter, material_name, shader_family});
    }
}

static void extract_texture_refs_from_scope(
    const std::string& scope_text,
    const std::string& material_name,
    const std::string& shader_family,
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen
) {
    const std::regex texture_tag_pattern(
        "<MaterialParameterTexture[^>]*(?:/>|>[\\s\\S]*?</MaterialParameterTexture\\s*>)",
        std::regex_constants::icase
    );
    auto begin = std::sregex_iterator(scope_text.begin(), scope_text.end(), texture_tag_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        const std::string tag = it->str();
        const std::string parameter = xml_attr_value(tag, {"_name", "StringItemID", "Name"});
        std::string path = xml_attr_value(tag, {"Value", "_path"});
        if (path.empty()) {
            const std::regex resource_pattern("ResourceReferencePath_ITexture[^>]*_path=\"([^\"]+\\.dds)\"", std::regex_constants::icase);
            std::smatch match;
            if (std::regex_search(tag, match, resource_pattern)) path = match[1].str();
        }
        add_sidecar_texture_ref(refs, seen, path, parameter, material_name, shader_family);
    }
}

static std::vector<SidecarTextureRef> extract_sidecar_texture_refs(const std::string& text) {
    std::vector<SidecarTextureRef> refs;
    std::set<std::string> seen;

    const std::regex skinned_wrapper_pattern(
        "<SkinnedMeshMaterialWrapper[^>]*>[\\s\\S]*?</SkinnedMeshMaterialWrapper\\s*>",
        std::regex_constants::icase
    );
    auto wrapper_begin = std::sregex_iterator(text.begin(), text.end(), skinned_wrapper_pattern);
    auto wrapper_end = std::sregex_iterator();
    for (auto it = wrapper_begin; it != wrapper_end; ++it) {
        const std::string block = it->str();
        const std::string material_name = xml_attr_value(block, {"_subMeshName", "PrimitiveName", "Name"});
        const std::string shader_family = extract_shader_family_hint(block);
        extract_texture_refs_from_scope(block, material_name, shader_family, refs, seen);
    }

    const std::string lowered_text = lower_copy(text);
    size_t material_search = 0;
    while (true) {
        const size_t material_pos = lowered_text.find("<material ", material_search);
        if (material_pos == std::string::npos) break;
        const size_t material_end = lowered_text.find("</material>", material_pos);
        if (material_end == std::string::npos) break;
        const std::string block = text.substr(material_pos, material_end + std::string("</Material>").size() - material_pos);
        std::string material_name = xml_attr_value(block, {"PrimitiveName", "_subMeshName", "Name"});
        std::replace(material_name.begin(), material_name.end(), '\\', '/');
        std::string shader_family = extract_shader_family_hint(block);
        if (shader_family.empty()) shader_family = xml_attr_value(block, {"MaterialName", "_materialName"});
        extract_texture_refs_from_scope(block, material_name, shader_family, refs, seen);
        material_search = material_end + std::string("</material>").size();
    }

    if (refs.empty()) {
        extract_texture_refs_from_scope(text, "", "", refs, seen);
    }

    if (!refs.empty()) return refs;
    for (const std::string& token : extract_dds_tokens(text)) {
        add_sidecar_texture_ref(refs, seen, token, basename_from_path(token), "", "");
    }
    return refs;
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
    const std::string texture = lower_copy(
        binding.texture_name + " " +
        binding.archive_path + " " +
        binding.material_name + " " +
        binding.parameter_name
    );
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
    const std::string binding_material = lower_copy(binding.material_name);
    if (!binding_material.empty() && material.find(binding_material) != std::string::npos) score += 70;
    if (!binding_material.empty() && texture.find(material) != std::string::npos) score += 20;
    if (texture.find(material) != std::string::npos && !material.empty()) score += 40;
    return score;
}

static std::string normalized_material_key(const std::string& text) {
    std::string key = lower_copy(basename_from_path(text));
    if (key.ends_with(".dds")) key = key.substr(0, key.size() - 4);
    return key;
}

static int material_identity_match_score(const TextureBinding& binding, const NativeSubmesh& mesh) {
    const std::string mesh_text = lower_copy(mesh.material + " " + mesh.name);
    const std::string binding_text = lower_copy(binding.material_name + " " + binding.texture_name + " " + binding.archive_path);
    const std::string mesh_key_a = normalized_material_key(mesh.material);
    const std::string mesh_key_b = normalized_material_key(mesh.name);
    const std::string binding_key = normalized_material_key(binding.material_name);
    int score = 0;
    if (!binding_key.empty() && (!mesh_key_a.empty() || !mesh_key_b.empty())) {
        if (binding_key == mesh_key_a || binding_key == mesh_key_b) score += 160;
        if (!mesh_key_a.empty() && binding_key.find(mesh_key_a) != std::string::npos) score += 72;
        if (!mesh_key_b.empty() && binding_key.find(mesh_key_b) != std::string::npos) score += 72;
        if (!mesh_key_a.empty() && mesh_key_a.find(binding_key) != std::string::npos) score += 54;
        if (!mesh_key_b.empty() && mesh_key_b.find(binding_key) != std::string::npos) score += 54;
        if (score == 0) return 0;
    }
    std::string current;
    std::vector<std::string> mesh_tokens;
    for (char ch : mesh_text) {
        if (std::isalnum(static_cast<unsigned char>(ch))) current.push_back(ch);
        else if (!current.empty()) {
            mesh_tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) mesh_tokens.push_back(current);
    for (const std::string& token : mesh_tokens) {
        if (token.size() >= 4 && binding_text.find(token) != std::string::npos) score += 14;
    }
    return score;
}

static bool material_identity_requires_exact_path_match(const TextureBinding& binding, const NativeSubmesh& mesh) {
    const std::string binding_material = lower_copy(binding.material_name);
    const std::string mesh_material = lower_copy(mesh.material + " " + mesh.name);
    return binding_material.find(".dds") != std::string::npos && mesh_material.find(".dds") != std::string::npos;
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
        if (binding.role != desired_role) {
            const bool compatible_material_response = desired_role == "material" && (binding.role == "detail" || binding.role == "specular");
            if (!compatible_material_response) continue;
        }
        if (material_identity_requires_exact_path_match(binding, mesh) && material_identity_match_score(binding, mesh) < 120) {
            continue;
        }
        const int score = material_match_score(binding, mesh, desired_role);
        if (score > best_score) {
            best_score = score;
            best = &binding;
        }
    }
    return best;
}

static std::string shader_rule_for_family(const std::string& family) {
    const std::string lower = lower_copy(family);
    if (lower.find("skinnedmeshskin") != std::string::npos) return "skin";
    if (lower.find("skinnedmeshcloth_ver2") != std::string::npos) return "cloth_v2";
    if (lower.find("skinnedmeshcloth") != std::string::npos) return "cloth";
    if (lower.find("skinnedmeshstandard_ver2") != std::string::npos) return "standard_v2";
    if (lower.find("skinnedmeshstandard") != std::string::npos) return "standard";
    if (lower.find("skinnedmeshhair") != std::string::npos) return "hair";
    if (lower.find("multitextured") != std::string::npos) return "static_multitextured";
    if (lower.find("standard") != std::string::npos) return "static_standard";
    return "generic";
}

struct SidecarParameterSummary {
    int texture_params = 0;
    int float_params = 0;
    int color_params = 0;
    int byte4_params = 0;
    int bit_flags = 0;
    std::string linked_mesh_path;
};

static int regex_count(const std::string& text, const std::regex& pattern) {
    return static_cast<int>(std::distance(std::sregex_iterator(text.begin(), text.end(), pattern), std::sregex_iterator()));
}

static SidecarParameterSummary summarize_sidecar_parameters(const std::string& text) {
    SidecarParameterSummary summary;
    summary.texture_params = regex_count(text, std::regex("MaterialParameterTexture", std::regex_constants::icase));
    summary.float_params = regex_count(text, std::regex("MaterialParameterFloat|<FloatParameter|_float", std::regex_constants::icase));
    summary.color_params = regex_count(text, std::regex("MaterialParameterColor|ColorParameter|Tint|_color", std::regex_constants::icase));
    summary.byte4_params = regex_count(text, std::regex("MaterialParameterByte4|Byte4", std::regex_constants::icase));
    summary.bit_flags = regex_count(text, std::regex("BitFlag|MaterialBit|_flag", std::regex_constants::icase));
    const std::regex linked_mesh_pattern("([A-Za-z0-9_./\\\\-]+\\.(?:pac|pam|pamlod))", std::regex_constants::icase);
    std::smatch match;
    if (std::regex_search(text, match, linked_mesh_pattern)) {
        summary.linked_mesh_path = match[1].str();
        std::replace(summary.linked_mesh_path.begin(), summary.linked_mesh_path.end(), '\\', '/');
    }
    return summary;
}

static std::string packed_channels_for_role(const std::string& role, const std::string& name, const std::string& parameter_name) {
    const std::string lower = lower_copy(name + " " + parameter_name);
    if (role == "material") {
        if (lower.find("orm") != std::string::npos) return "r=occlusion,g=roughness,b=metalness";
        if (lower.find("rma") != std::string::npos) return "r=roughness,g=metalness,b=occlusion";
        if (lower.find("mra") != std::string::npos) return "r=metalness,g=roughness,b=occlusion";
        if (lower.find("arm") != std::string::npos) return "r=occlusion,g=roughness,b=metalness";
        if (lower.find("_ma") != std::string::npos || lower.find("material") != std::string::npos) {
            return "approx:r=occlusion,g=roughness,b=metalness,a=specular";
        }
        if (lower.find("_m") != std::string::npos) return "approx:packed_material_mask";
    }
    if (role == "detail") return "approx:detail/grime/dye mask weights";
    if (role == "specular") return "approx:specular/roughness response";
    if (role == "height") return "height";
    if (role == "normal") return "normal_xy";
    return "";
}

static std::string role_from_parameter_shader_and_name(
    const std::string& parameter_name,
    const std::string& shader_rule,
    const std::string& texture_name,
    const TechniqueParameterInfo* technique_parameter = nullptr
) {
    const std::string p = lower_copy(parameter_name);
    const std::string t = lower_copy(texture_name);
    if (technique_parameter != nullptr && technique_parameter->declared) {
        const std::string declared_type = lower_copy(technique_parameter->type);
        const std::string declared_default = lower_copy(technique_parameter->default_value);
        const bool declared_texture = declared_type.find("texture") != std::string::npos || p.find("texture") != std::string::npos;
        if (declared_texture) {
            if (p.find("normal") != std::string::npos || declared_default.find("0xff7f7f00") != std::string::npos) return "normal";
            if (p.find("height") != std::string::npos || p.find("displacement") != std::string::npos || p.find("disp") != std::string::npos) return "height";
            if (p.find("specular") != std::string::npos || p.find("gloss") != std::string::npos || p.find("smoothness") != std::string::npos) return "specular";
            if (p.find("basecolor") != std::string::npos || p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos) return "base";
            if (p.find("overlaycolor") != std::string::npos || p.find("layerbasecolor") != std::string::npos || p.find("layercolor") != std::string::npos) return "base";
            if (p.find("mask") != std::string::npos && (p.find("detail") != std::string::npos || p.find("blend") != std::string::npos || p.find("layer") != std::string::npos)) return "detail";
            if (p.find("material") != std::string::npos || p.find("colorblendingmask") != std::string::npos || p == "_masktexture") return "material";
        }
    }
    if (p.find("normal") != std::string::npos || p == "n" || t.find("_n.dds") != std::string::npos) return "normal";
    if (p.find("height") != std::string::npos || p.find("displacement") != std::string::npos || p.find("disp") != std::string::npos || t.find("_disp.dds") != std::string::npos) return "height";
    if (p.find("specular") != std::string::npos || p.find("_sp") != std::string::npos || t.find("_sp.dds") != std::string::npos) return "specular";
    if (p.find("material") != std::string::npos || p.find("colorblendingmask") != std::string::npos || p.find("blending") != std::string::npos || t.find("_ma.dds") != std::string::npos || t.find("_m.dds") != std::string::npos) return "material";
    if (p.find("detail") != std::string::npos || p.find("grime") != std::string::npos || p.find("dye") != std::string::npos || p.find("mask") != std::string::npos || t.find("_mg.dds") != std::string::npos) {
        if (p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos || p.find("color") != std::string::npos) return "base";
        return "detail";
    }
    if (p.find("overlaycolor") != std::string::npos || p.find("layercolor") != std::string::npos) return "base";
    if (p.find("basecolor") != std::string::npos || p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos) return "base";
    if (shader_rule == "skin" && t.find("_sp.dds") != std::string::npos) return "specular";
    return texture_role_from_name(texture_name);
}

static std::string semantic_type_for_role(const std::string& role) {
    if (role == "base") return "albedo";
    if (role == "normal") return "normal";
    if (role == "height") return "height";
    if (role == "specular") return "specular";
    if (role == "detail") return "detail_mask";
    return "packed_material";
}

static void add_sidecar_candidate(
    std::vector<ArchiveEntryRef>& out,
    std::set<std::string>& seen,
    const ArchiveEntryRef& ref
) {
    if (ref.path.empty() || ref.comp_size == 0) return;
    const std::string key = lower_copy(ref.path);
    if (seen.insert(key).second) out.push_back(ref);
}

static void add_sidecar_basename_candidates(
    std::vector<ArchiveEntryRef>& out,
    std::set<std::string>& seen,
    const PamtIndex& index,
    const std::string& basename,
    const std::string& preferred_dir
) {
    auto it = index.by_basename.find(lower_copy(basename));
    if (it == index.by_basename.end()) return;
    std::vector<std::pair<int, ArchiveEntryRef>> scored;
    for (const ArchiveEntryRef& ref : it->second) {
        int score = 10;
        const std::string path = lower_copy(ref.path);
        const std::string dir = lower_copy(dirname_from_path(ref.path));
        if (!preferred_dir.empty() && dir == lower_copy(preferred_dir)) score += 80;
        if (path.find("/modelproperty/") != std::string::npos) score += 30;
        if (path.find("/model/") != std::string::npos) score += 10;
        scored.emplace_back(score, ref);
    }
    std::sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
        return a.first > b.first;
    });
    for (const auto& item : scored) add_sidecar_candidate(out, seen, item.second);
}

static std::vector<ArchiveEntryRef> material_sidecar_candidates_for_job(
    const EntryJob& job,
    const PamtIndex& index
) {
    std::vector<ArchiveEntryRef> candidates;
    std::set<std::string> seen;
    add_sidecar_candidate(candidates, seen, job.companion_entry);

    const std::string model_stem = stem_from_path(job.path);
    const std::string model_stem_lower = lower_copy(model_stem);
    const std::string model_dir = dirname_from_path(job.path);
    std::vector<std::string> basenames;
    if (job.extension == ".pac") {
        basenames = {model_stem + ".pac_xml", model_stem + ".material", model_stem + ".technique", model_stem + ".prefab"};
    } else if (job.extension == ".pam") {
        basenames = {model_stem + ".pami", model_stem + ".pam_xml", model_stem + ".material", model_stem + ".technique", model_stem + ".prefab"};
    } else if (job.extension == ".pamlod") {
        basenames = {model_stem + ".pamlod_xml", model_stem + ".pami", model_stem + ".pam_xml", model_stem + ".material", model_stem + ".technique", model_stem + ".prefab"};
    }
    for (const std::string& base : basenames) {
        add_sidecar_basename_candidates(candidates, seen, index, base, model_dir);
    }
    if ((job.extension == ".pam" || job.extension == ".pamlod") && !candidates.empty()) {
        return candidates;
    }

    std::vector<std::pair<int, ArchiveEntryRef>> scored;
    const std::string model_dir_lower = lower_copy(model_dir);
    const std::string model_property_dir = lower_copy([&]() {
        std::string converted = model_dir;
        const std::string marker = "/model/";
        const size_t pos = lower_copy(converted).find(marker);
        if (pos != std::string::npos) {
            converted.replace(pos, marker.size(), "/modelproperty/");
        }
        return converted;
    }());
    for (const ArchiveEntryRef& ref : index.material_sidecars) {
        if (seen.find(lower_copy(ref.path)) != seen.end()) continue;
        const std::string ref_stem = lower_copy(stem_from_path(ref.path));
        const std::string ref_path = lower_copy(ref.path);
        const std::string ref_dir = lower_copy(dirname_from_path(ref.path));
        int score = 0;
        if (!model_stem_lower.empty() && ref_stem == model_stem_lower) score += 100;
        if (!model_stem_lower.empty() && ref_path.find(model_stem_lower) != std::string::npos) score += 40;
        if (!model_dir_lower.empty() && ref_dir == model_dir_lower) score += 25;
        if (!model_property_dir.empty() && ref_dir == model_property_dir) score += 45;
        if (ref.extension == ".pami" && (job.extension == ".pam" || job.extension == ".pamlod")) score += 20;
        if ((ref.extension == ".pac_xml" || ref.extension == ".pam_xml" || ref.extension == ".pamlod_xml") && ref_path.find("/modelproperty/") != std::string::npos) score += 15;
        if (score >= 80) scored.emplace_back(score, ref);
    }
    std::sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
        return a.first > b.first;
    });
    for (const auto& item : scored) {
        if (candidates.size() >= 24) break;
        add_sidecar_candidate(candidates, seen, item.second);
    }
    return candidates;
}

static std::vector<TextureBinding> build_material_bindings(
    const EntryJob& job,
    const PamtIndex& index,
    NativePackage& package
) {
    std::vector<TextureBinding> bindings;
    const std::vector<ArchiveEntryRef> sidecars = material_sidecar_candidates_for_job(job, index);
    if (sidecars.empty()) {
        package.material_index = "native_index_no_sidecar";
        package.texture_resolution = "none";
        package.notes.push_back("native material index: no matching .pac_xml/.pam_xml/.pamlod_xml/.pami/.material/.technique/.prefab sidecar");
        return bindings;
    }
    const TechniqueIndex& technique_index = cached_package_technique_index(job, index);
    if (technique_index.files_scanned > 0) {
        package.notes.push_back(
            "native technique index: files=" + std::to_string(technique_index.files_scanned) +
            "; techniques=" + std::to_string(technique_index.technique_names.size()) +
            "; texture_params=" + std::to_string(technique_index.texture_parameters)
        );
    }
    std::vector<std::string> notes;
    std::set<std::string> seen_bindings;
    std::set<std::string> sidecar_kinds;
    std::set<std::string> shader_rules;
    for (const ArchiveEntryRef& sidecar : sidecars) {
        std::vector<char> sidecar_bytes;
        try {
            sidecar_bytes = read_archive_ref_decoded_bytes(sidecar);
        } catch (const std::exception& exc) {
            package.notes.push_back(std::string("native material sidecar read failed:") + sidecar.path + ": " + exc.what());
            continue;
        }
        std::string sidecar_text(sidecar_bytes.begin(), sidecar_bytes.end());
        std::string sidecar_shader_family = extract_shader_family_hint(sidecar_text);
        if (sidecar_shader_family.empty()) {
            sidecar_shader_family = sidecar.extension == ".pami" ? "StaticMaterial" : "";
        }
        const std::string sidecar_shader_rule = shader_rule_for_family(sidecar_shader_family);
        const SidecarParameterSummary parameter_summary = summarize_sidecar_parameters(sidecar_text);
        shader_rules.insert(sidecar_shader_rule);
        sidecar_kinds.insert(sidecar.extension.empty() ? "unknown" : sidecar.extension);
        package.notes.push_back(
            "native material sidecar: " + sidecar.path +
            "; rule=" + sidecar_shader_rule +
            "; texture_params=" + std::to_string(parameter_summary.texture_params) +
            "; float_params=" + std::to_string(parameter_summary.float_params) +
            "; color_params=" + std::to_string(parameter_summary.color_params) +
            "; byte4_params=" + std::to_string(parameter_summary.byte4_params) +
            "; flags=" + std::to_string(parameter_summary.bit_flags)
        );
        std::vector<SidecarTextureRef> refs = extract_sidecar_texture_refs(sidecar_text);
        if (refs.empty()) {
            for (const std::string& token : extract_dds_tokens(sidecar_text)) {
                refs.push_back(SidecarTextureRef{token, ""});
            }
        }
        package.dds_candidates += static_cast<int>(refs.size());
        for (const SidecarTextureRef& texture_ref : refs) {
            const std::string base = lower_copy(basename_from_path(texture_ref.path));
            auto it = index.by_basename.find(base);
            if (it == index.by_basename.end()) {
                continue;
            }
            const ArchiveEntryRef* selected = nullptr;
            int best_score = -100000;
            const std::string sidecar_dir = lower_copy(dirname_from_path(sidecar.path));
            for (const ArchiveEntryRef& ref : it->second) {
                int score = 10;
                const std::string ref_path = lower_copy(ref.path);
                const std::string ref_dir = lower_copy(dirname_from_path(ref.path));
                if (lower_copy(ref.basename) == base) score += 30;
                if (!sidecar_dir.empty() && ref_dir == sidecar_dir) score += 50;
                if (ref_path.find("/texture/") != std::string::npos) score += 20;
                if (ref_path.find("/modelproperty/") != std::string::npos) score += 5;
                if (score > best_score) {
                    best_score = score;
                    selected = &ref;
                }
            }
            if (selected == nullptr && !it->second.empty()) selected = &it->second.front();
            if (selected == nullptr) continue;
            const std::string extracted = extracted_dds_path_for_entry(*selected, job.cache_root, notes);
            if (extracted.empty()) continue;
            std::string shader_family = texture_ref.shader_family.empty() ? sidecar_shader_family : texture_ref.shader_family;
            if (shader_family.empty() && sidecar.extension == ".pami") shader_family = "StaticMaterial";
            const std::string shader_rule = shader_rule_for_family(shader_family);
            const TechniqueParameterInfo* technique_parameter = technique_parameter_for_name(technique_index, texture_ref.parameter_name);
            TextureBinding binding;
            binding.role = role_from_parameter_shader_and_name(texture_ref.parameter_name, shader_rule, base, technique_parameter);
            binding.source_path = extracted;
            binding.archive_path = selected->path;
            binding.texture_name = selected->basename;
            binding.parameter_name = texture_ref.parameter_name.empty() ? base : texture_ref.parameter_name;
            const std::string parameter_lower = lower_copy(binding.parameter_name);
            if (binding.role == "base" && role_is_technical_for_base(texture_role_from_name(base))) {
                binding.role = texture_role_from_name(base);
            }
            binding.semantic_type = semantic_type_for_role(binding.role);
            binding.semantic_subtype = semantic_subtype_for_role(binding.role);
            binding.shader_family = shader_family;
            binding.shader_rule = shader_rule;
            binding.material_name = texture_ref.material_name.empty() ? stem_from_path(sidecar.path) : texture_ref.material_name;
            binding.sidecar_path = sidecar.path;
            binding.sidecar_kind = sidecar.extension;
            binding.linked_mesh_path = parameter_summary.linked_mesh_path;
            binding.packed_channels = packed_channels_for_role(binding.role, base, parameter_lower);
            binding.srgb_mode = srgb_mode_for_role(binding.role, technique_parameter);
            binding.parameter_declared_by = technique_parameter != nullptr ? "technique" : "";
            if (binding.role == "base" && role_is_technical_for_base(texture_role_from_name(base))) {
                binding.material_output_quality = "approximate";
            } else if (technique_parameter != nullptr && !texture_ref.parameter_name.empty() && !texture_ref.material_name.empty()) {
                binding.material_output_quality = "exact";
            } else if (!texture_ref.parameter_name.empty() && !texture_ref.material_name.empty()) {
                binding.material_output_quality = "exact";
            } else {
                binding.material_output_quality = "inferred";
            }
            const std::string binding_key = lower_copy(binding.role + "|" + binding.archive_path + "|" + binding.parameter_name + "|" + binding.material_name);
            if (seen_bindings.insert(binding_key).second) {
                bindings.push_back(binding);
            }
        }
    }
    package.dds_extracted = static_cast<int>(bindings.size());
    int exact_bindings = 0;
    int inferred_bindings = 0;
    int approximate_bindings = 0;
    for (const TextureBinding& binding : bindings) {
        if (binding.material_output_quality == "exact") ++exact_bindings;
        else if (binding.material_output_quality == "approximate") ++approximate_bindings;
        else ++inferred_bindings;
    }
    std::ostringstream kind_summary;
    bool first_kind = true;
    for (const std::string& kind : sidecar_kinds) {
        if (!first_kind) kind_summary << "+";
        first_kind = false;
        kind_summary << kind;
    }
    std::ostringstream rule_summary;
    bool first_rule = true;
    for (const std::string& rule : shader_rules) {
        if (!first_rule) rule_summary << "+";
        first_rule = false;
        rule_summary << rule;
    }
    package.material_index = bindings.empty() ? "native_sidecars_no_resolved_dds" : ("native_sidecar_index:" + kind_summary.str());
    package.texture_resolution = bindings.empty() ? "none" : "same_pamt_basename";
    package.material_output_quality = bindings.empty()
        ? "approximate"
        : (exact_bindings > 0 ? "exact_inputs_inferred_shader" : "inferred");
    package.notes.push_back(
        std::string("native material accuracy: ") + package.material_output_quality +
        "; sidecars=" + std::to_string(sidecars.size()) +
        "; shader_rules=" + (rule_summary.str().empty() ? "generic" : rule_summary.str()) +
        "; bindings exact=" + std::to_string(exact_bindings) +
        " inferred=" + std::to_string(inferred_bindings) +
        " approximate=" + std::to_string(approximate_bindings)
    );
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
            const std::int32_t source_vertex = vi < mesh.source_vertex_indices.size()
                ? mesh.source_vertex_indices[vi]
                : static_cast<std::int32_t>(vi);
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
            append_int32(identity, source_vertex);
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
        << "\"shader_family\":\"" << json_escape(binding->shader_family) << "\","
        << "\"shader_rule\":\"" << json_escape(binding->shader_rule) << "\","
        << "\"sidecar_path\":\"" << json_escape(binding->sidecar_path) << "\","
        << "\"sidecar_kind\":\"" << json_escape(binding->sidecar_kind) << "\","
        << "\"linked_mesh_path\":\"" << json_escape(binding->linked_mesh_path) << "\","
        << "\"packed_channels\":\"" << json_escape(binding->packed_channels) << "\","
        << "\"srgb_mode\":\"" << json_escape(binding->srgb_mode) << "\","
        << "\"parameter_declared_by\":\"" << json_escape(binding->parameter_declared_by) << "\","
        << "\"material_output_quality\":\"" << json_escape(binding->material_output_quality) << "\","
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

static std::vector<const TextureBinding*> relevant_bindings_for_mesh(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh,
    const std::vector<const TextureBinding*>& selected_slots
) {
    std::vector<const TextureBinding*> result;
    std::set<const TextureBinding*> seen;
    auto add = [&](const TextureBinding* binding) {
        if (binding != nullptr && seen.insert(binding).second) result.push_back(binding);
    };
    for (const TextureBinding* binding : selected_slots) add(binding);
    if (bindings.size() <= 8) {
        std::set<std::string> scoped_materials;
        for (const TextureBinding& binding : bindings) {
            const std::string key = normalized_material_key(binding.material_name);
            if (!key.empty()) scoped_materials.insert(key);
        }
        if (scoped_materials.size() <= 1) {
            for (const TextureBinding& binding : bindings) add(&binding);
            return result;
        }
        for (const TextureBinding& binding : bindings) {
            if (material_identity_match_score(binding, mesh) >= 120) add(&binding);
        }
        return result;
    }
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty()) continue;
        const int score = material_identity_match_score(binding, mesh);
        const int threshold = normalized_material_key(binding.material_name).empty() ? 42 : 120;
        if (score >= threshold) add(&binding);
    }
    return result;
}

struct NativeMaterialHints {
    float roughness = 0.45f;
    float metalness = 0.0f;
    float specular = 0.45f;
    float height_scale = 0.35f;
};

static NativeMaterialHints material_hints_for_bindings(const std::vector<const TextureBinding*>& bindings) {
    NativeMaterialHints hints;
    bool has_skin = false;
    bool has_hair = false;
    bool has_standard_v2 = false;
    bool has_static_multi = false;
    bool has_specular = false;
    bool has_material_mask = false;
    bool has_height = false;
    bool has_metal = false;
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        const std::string rule = lower_copy(binding->shader_rule);
        const std::string packed = lower_copy(binding->packed_channels + " " + binding->parameter_name);
        has_skin = has_skin || rule == "skin";
        has_hair = has_hair || rule == "hair";
        has_standard_v2 = has_standard_v2 || rule == "standard_v2";
        has_static_multi = has_static_multi || rule == "static_multitextured";
        has_specular = has_specular || binding->role == "specular";
        has_material_mask = has_material_mask || binding->role == "material" || binding->role == "detail";
        has_height = has_height || binding->role == "height";
        has_metal = has_metal || packed.find("metal") != std::string::npos;
    }
    if (has_skin) {
        hints.roughness = 0.56f;
        hints.specular = 0.28f;
        hints.height_scale = 0.18f;
    } else if (has_hair) {
        hints.roughness = 0.38f;
        hints.specular = 0.58f;
        hints.height_scale = 0.14f;
    } else if (has_standard_v2) {
        hints.roughness = has_material_mask ? 0.42f : 0.50f;
        hints.specular = has_specular ? 0.56f : 0.38f;
        hints.metalness = has_metal ? 0.10f : 0.0f;
        hints.height_scale = has_height ? 0.34f : 0.0f;
    } else if (has_static_multi) {
        hints.roughness = 0.58f;
        hints.specular = has_specular ? 0.30f : 0.18f;
        hints.height_scale = has_height ? 0.24f : 0.0f;
    } else {
        hints.specular = has_specular ? 0.42f : 0.20f;
        hints.height_scale = has_height ? 0.28f : 0.0f;
    }
    return hints;
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
        const TextureBinding* specular = best_binding_for_role(bindings, mesh, "specular");
        const TextureBinding* detail = best_binding_for_role(bindings, mesh, "detail");
        const std::vector<const TextureBinding*> batch_bindings = relevant_bindings_for_mesh(
            bindings,
            mesh,
            {base, normal, material, height, specular, detail}
        );
        const NativeMaterialHints material_hints = material_hints_for_bindings(batch_bindings);
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
        if (!batch_bindings.empty()) {
            if (wrote_slot) batches_json << ",";
            batches_json << "\"material_inputs\":[";
            bool first_input = true;
            for (const TextureBinding* binding_ptr : batch_bindings) {
                if (binding_ptr == nullptr || binding_ptr->source_path.empty()) continue;
                const TextureBinding& binding = *binding_ptr;
                if (!first_input) batches_json << ",";
                first_input = false;
                batches_json << "{"
                    << "\"slot\":\"" << json_escape(binding.role) << "\","
                    << "\"source_path\":\"" << json_escape(binding.source_path) << "\","
                    << "\"archive_path\":\"" << json_escape(binding.archive_path) << "\","
                    << "\"parameter_name\":\"" << json_escape(binding.parameter_name) << "\","
                    << "\"semantic_type\":\"" << json_escape(binding.semantic_type) << "\","
                    << "\"semantic_subtype\":\"" << json_escape(binding.semantic_subtype) << "\","
                    << "\"material_name\":\"" << json_escape(binding.material_name) << "\","
                    << "\"shader_family\":\"" << json_escape(binding.shader_family) << "\","
                    << "\"shader_rule\":\"" << json_escape(binding.shader_rule) << "\","
                    << "\"sidecar_path\":\"" << json_escape(binding.sidecar_path) << "\","
                    << "\"sidecar_kind\":\"" << json_escape(binding.sidecar_kind) << "\","
                    << "\"linked_mesh_path\":\"" << json_escape(binding.linked_mesh_path) << "\","
                    << "\"packed_channels\":\"" << json_escape(binding.packed_channels) << "\","
                    << "\"srgb_mode\":\"" << json_escape(binding.srgb_mode) << "\","
                    << "\"parameter_declared_by\":\"" << json_escape(binding.parameter_declared_by) << "\","
                    << "\"material_output_quality\":\"" << json_escape(binding.material_output_quality) << "\","
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
            << "\"roughness\":" << material_hints.roughness << ","
            << "\"metalness\":" << material_hints.metalness << ","
            << "\"specular\":" << material_hints.specular << ","
            << "\"height_scale\":" << material_hints.height_scale << ","
            << "\"native_material_hints\":{\"shader_family\":\"" << json_escape(batch_bindings.empty() ? "" : batch_bindings.front()->shader_family) << "\",\"roughness\":" << material_hints.roughness << ",\"metalness\":" << material_hints.metalness << ",\"specular\":" << material_hints.specular << ",\"height_scale\":" << material_hints.height_scale << "},"
            << "\"notes\":[\"generated by cdmw-preview-core " << json_escape(package.mesh_parse) << " path\",\"native material inputs scoped to this batch: " << batch_bindings.size() << "\"],"
            << "\"material_combiner_active\":false,"
            << "\"material_combiner_outputs\":[],"
            << "\"material_combiner_decode_modes\":[\"direct_dds_sidecar\"]"
            << "}";
    }
    package.path = package_dir;
    package.batch_count = emitted_batch_count;
    package.vertex_count = emitted_vertex_count;
    package.face_count = face_total;
    const std::string format = job.extension.size() > 1 && job.extension.front() == '.'
        ? job.extension.substr(1)
        : job.extension;
    std::ostringstream manifest;
    manifest << "{"
        << "\"schema_version\":" << std::max(4, job.schema_version) << ","
        << "\"backend\":\"d3d11\","
        << "\"source_path\":\"" << json_escape(job.path) << "\","
        << "\"format\":\"" << json_escape(format) << "\","
        << "\"summary\":\"Native preview-core " << json_escape(format) << " package\","
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
        << "\"native_preview_core\":{\"mesh_parse\":\"" << json_escape(package.mesh_parse) << "\",\"material_index\":\"" << json_escape(package.material_index) << "\",\"texture_resolution\":\"" << json_escape(package.texture_resolution) << "\",\"material_output_quality\":\"" << json_escape(package.material_output_quality) << "\",\"lod_count\":" << package.lod_count << "},"
        << "\"batches\":[" << batches_json.str() << "]"
        << "}";
    write_text(package_dir / "manifest.json", manifest.str());
    return package;
}

static NativePackage try_generate_native_package(const EntryJob& job, const std::vector<char>& data) {
    NativePackage package;
    NativeMeshParseResult parsed;
    if (job.extension == ".pac") {
        parsed.meshes = parse_pac_submeshes(data);
        parsed.parser = "native_pac_par_sections";
    } else if (job.extension == ".pam") {
        parsed = parse_pam_submeshes(data);
    } else if (job.extension == ".pamlod") {
        parsed = parse_pamlod_submeshes(data);
    } else {
        throw std::runtime_error("native preview-core package generation only supports .pac, .pam, and .pamlod");
    }
    if (parsed.meshes.empty()) {
        throw std::runtime_error("native model parser found no renderable geometry");
    }
    package.mesh_parse = parsed.parser;
    package.lod_count = parsed.lod_count;
    const PamtIndex& index = cached_pamt_index(job.entry.pamt_path);
    std::vector<TextureBinding> bindings = build_material_bindings(job, index, package);
    if (bindings.empty()) {
        if (package.material_index.empty()) package.material_index = "none";
        package.texture_resolution = "none";
        package.notes.push_back("native package emitted geometry with fallback batch colors because no direct DDS bindings were resolved");
    }
    return write_d3d11_package(job, parsed.meshes, bindings, package);
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
    const std::uint64_t cache_hits_before = decoded_entry_cache_hits();
    const std::uint64_t cache_misses_before = decoded_entry_cache_misses();
    const std::uint64_t cache_evictions_before = decoded_entry_cache_evictions();
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
        << "\"native_material_output_quality\":\"" << json_escape(package.material_output_quality.empty() ? "pending" : package.material_output_quality) << "\","
        << "\"schema_version\":" << job.schema_version << ","
        << "\"entry_path\":\"" << json_escape(job.path) << "\","
        << "\"extension\":\"" << json_escape(job.extension) << "\","
        << "\"format_fourcc\":\"" << json_escape(format_fourcc) << "\","
        << "\"compression_type\":" << compression_type << ","
        << "\"bytes_read\":" << bytes_read << ","
        << "\"batch_count\":" << package.batch_count << ","
        << "\"vertex_count\":" << package.vertex_count << ","
        << "\"face_count\":" << package.face_count << ","
        << "\"lod_count\":" << package.lod_count << ","
        << "\"dds_candidates\":" << package.dds_candidates << ","
        << "\"dds_extracted\":" << package.dds_extracted << ","
        << "\"decoded_cache_entries\":" << decoded_entry_cache_entries() << ","
        << "\"decoded_cache_bytes\":" << decoded_entry_cache_bytes() << ","
        << "\"decoded_cache_hits\":" << decoded_entry_cache_hits() << ","
        << "\"decoded_cache_misses\":" << decoded_entry_cache_misses() << ","
        << "\"decoded_cache_evictions\":" << decoded_entry_cache_evictions() << ","
        << "\"decoded_cache_job_hits\":" << (decoded_entry_cache_hits() - cache_hits_before) << ","
        << "\"decoded_cache_job_misses\":" << (decoded_entry_cache_misses() - cache_misses_before) << ","
        << "\"decoded_cache_job_evictions\":" << (decoded_entry_cache_evictions() - cache_evictions_before) << ","
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

struct CommonArgs {
    fs::path crash_dir;
    fs::path diagnostic_log;
};

CommonArgs parse_common_args(int argc, char** argv) {
    CommonArgs args;
    for (int i = 1; i < argc; ++i) {
        std::string key = argv[i] ? argv[i] : "";
        auto next = [&]() -> fs::path {
            if (i + 1 >= argc) return {};
            return fs::path(argv[++i]);
        };
        if (key == "--crash-dir") args.crash_dir = next();
        else if (key == "--diagnostic-log") args.diagnostic_log = next();
    }
    return args;
}

int run_preview_job(const fs::path& job_path, const fs::path& report_path) {
    try {
        cdmw_native_diag::event("preview_job_start", {{"job_path", cdmw_native_diag::path_to_utf8(job_path)}, {"report_path", cdmw_native_diag::path_to_utf8(report_path)}});
        write_text(report_path, preview_report_for_job(job_path));
        cdmw_native_diag::event("preview_job_complete", {{"job_path", cdmw_native_diag::path_to_utf8(job_path)}, {"report_path", cdmw_native_diag::path_to_utf8(report_path)}});
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
        cdmw_native_diag::event("preview_job_error", {{"job_path", cdmw_native_diag::path_to_utf8(job_path)}, {"message", exc.what()}});
        return 2;
    }
}

std::string extract_line_path(const std::string& line, const std::string& key) {
    std::string value = find_string_value(line, key);
    if (!value.empty()) return value;
    return {};
}

int run_service() {
    cdmw_native_diag::event("service_start");
    std::cout << "{\"event\":\"ready\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
    std::string line;
    while (std::getline(std::cin, line)) {
        const std::string lowered = lower_copy(line);
        if (lowered.find("\"shutdown\"") != std::string::npos) {
            cdmw_native_diag::event("service_shutdown");
            std::cout << "{\"event\":\"closed\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
            return 0;
        }
        if (lowered.find("\"ping\"") != std::string::npos) {
            cdmw_native_diag::event("service_ping");
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
                cdmw_native_diag::event("service_report_readback_failed", {{"report_path", report_path}});
                std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\"report readback failed\"}" << std::endl;
            }
            continue;
        }
        cdmw_native_diag::event("service_unknown_command");
        std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\"unknown command\"}" << std::endl;
    }
    cdmw_native_diag::event("service_closed_stdin");
    return 0;
}

} // namespace

int main(int argc, char** argv) {
    CommonArgs common_args = parse_common_args(argc, argv);
    cdmw_native_diag::init("cdmw-preview-core", common_args.crash_dir, common_args.diagnostic_log);
    try {
        if (argc >= 2 && std::string(argv[1]) == "self-test") {
            cdmw_native_diag::event("self_test_ok");
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
