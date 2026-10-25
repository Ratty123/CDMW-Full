// Portable port of cdmw/domain/archives/overlay_merge.py and the codecs it uses.
// No platform APIs: the virtual loader links it, and the CLI tests it against Python.
#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace cdmw::compose {

using Bytes = std::vector<std::uint8_t>;
// A file's contents, or null when there is no file (Python's None).
using Blob = std::shared_ptr<const Bytes>;

class ComposeError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};
// Both installs change the same record: Python's OverlayConflict.
class OverlayConflict : public ComposeError {
public:
    using ComposeError::ComposeError;
};
// The bytes do not read as their format, or an edit is refused: any other Python exception.
class FormatError : public ComposeError {
public:
    using ComposeError::ComposeError;
};
// Input outside the subset this port reproduces exactly. Callers refuse the composition
// rather than guess what Python would have produced.
class Unsupported : public ComposeError {
public:
    using ComposeError::ComposeError;
};

// Path -> contents in insertion order, like the Python dicts the merge takes and returns.
class FileMap {
public:
    // The contents, or null when the path is absent or maps to no file.
    Blob get(const std::string& path) const;
    bool contains(const std::string& path) const;
    // Replaces in place, or appends a new path at the end.
    void set(const std::string& path, Blob value);
    const std::vector<std::pair<std::string, Blob>>& items() const { return items_; }

private:
    std::vector<std::pair<std::string, Blob>> items_;
    std::unordered_map<std::string, std::size_t> index_;
};

// Apply one owned change (before -> after) onto the current files, composing shared
// tables at record level. Throws OverlayConflict, FormatError or Unsupported.
FileMap merge_overlay_files(const FileMap& before, const FileMap& after, const FileMap& current);

// archive_format.calculate_pa_checksum and hashlittle (Bob Jenkins' lookup3).
std::uint32_t pa_checksum(const std::uint8_t* data, std::size_t size);
std::uint32_t hashlittle(const std::uint8_t* data, std::size_t size, std::uint32_t initial);

// papgt_format: the archive directories the game mounts, in the order it reads them.
inline constexpr std::uint32_t papgt_default_flags = 0x007FFF00;
struct PapgtDirectory {
    std::string name;
    std::uint32_t flags{};
    std::uint32_t pamt_checksum{};
    bool operator==(const PapgtDirectory&) const = default;
};
std::vector<PapgtDirectory> parse_papgt(const Bytes& data);
// `header` is the first twelve bytes of the source file (empty for zeros).
Bytes serialize_papgt(const std::vector<PapgtDirectory>& directories, const Bytes& header);
// `data` with `name` mounted, first when `first`; a listed directory keeps its place.
Bytes papgt_with_directory(const Bytes& data, const std::string& name, std::uint32_t pamt_checksum,
                           std::uint32_t flags = papgt_default_flags, bool first = true);

// archive_overlay.build_overlay_archive: one archive directory holding only these files.
struct OverlayFile {
    std::string path;
    Bytes payload;  // stored bytes, already compressed/encrypted as `flags` says
    std::uint64_t orig_size{};
    std::uint64_t flags{};
};
struct OverlayEntry {
    std::string path;
    std::uint64_t offset{}, stored_size{}, orig_size{};
};
struct OverlayArchive {
    Bytes pamt, paz;
    std::uint32_t pamt_checksum{};
    std::vector<OverlayEntry> entries;
};
OverlayArchive build_overlay_archive(const std::vector<OverlayFile>& files);

namespace lz4 {
// One raw LZ4 block that must expand to exactly output_size bytes.
Bytes decompress(const std::uint8_t* data, std::size_t size, std::size_t output_size);
// A valid raw LZ4 block. Not byte-identical to liblz4's encoder; decoders agree on its contents.
Bytes compress(const std::uint8_t* data, std::size_t size);
}  // namespace lz4

}  // namespace cdmw::compose
