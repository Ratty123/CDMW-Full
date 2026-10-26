// Portable port of cdmw/domain/archives/overlay_merge.py and the codecs it uses.
// No platform APIs: the virtual loader links it, and the CLI tests it against Python.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <set>
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

// archive_patching: the bytes an archive stores for `data` under `flags` (compression type
// in the low nibble, ChaCha20 keyed by the file name when any higher bit is set).
Bytes stored_payload(const Bytes& data, std::uint64_t flags, const std::string& basename);
// archive_format.crypt_chacha20_filename; the same call encrypts and decrypts.
Bytes crypt_chacha20(const Bytes& data, const std::string& basename);

// archive_format.ArchiveEntry: one file of a mounted archive group.
struct ArchiveEntry {
    std::string path;
    std::filesystem::path pamt_path, paz_path;
    std::uint64_t offset{}, stored_size{}, orig_size{};
    std::uint32_t flags{}, paz_index{};
};
// archive_format.parse_archive_pamt_bytes, its name-trie and folder-range rules included.
// With `keep`, only the entries whose path it accepts are returned; every entry is still
// read and validated, so the same archives refuse.
std::vector<ArchiveEntry> parse_pamt(const Bytes& data, const std::filesystem::path& pamt_path,
                                     const std::function<bool(const std::string&)>& keep = {});
// archive_extraction.read_archive_entry_data: the decoded bytes, decrypting and
// decompressing as Python does for the tables, string tables and XML a composition reads.
Bytes read_entry(const ArchiveEntry& entry);

// The archive groups the game mounts, in the order `papgt` lists them (DMM's groups
// included), each read from `<root>/<group>/0.pamt`. The first group holding a path wins.
class MountedArchives {
public:
    // With `wanted` (normalized paths), only those paths are indexed; find() then answers
    // for them alone.
    MountedArchives(const std::filesystem::path& root, const Bytes& papgt, const std::set<std::string>* wanted = nullptr);
    // The entry the game reads for `path` (compared as archive_format normalizes it), or null.
    const ArchiveEntry* find(const std::string& path) const;
    const std::vector<std::string>& groups() const { return groups_; }
    // The 0.pamt files read, in mount order (a listed group without one is skipped).
    const std::vector<std::filesystem::path>& pamts() const { return pamts_; }

private:
    std::vector<std::string> groups_;
    std::vector<std::filesystem::path> pamts_;
    std::vector<ArchiveEntry> entries_;
    std::unordered_map<std::string, std::size_t> first_;
    std::optional<std::set<std::string>> wanted_;
};

// archive_format's normalized game path: forward slashes, no surrounding white space or
// slashes, ASCII lower case.
std::string normalize_game_path(const std::string& path);

// One owned change of a package: the file before and after the package, as the package
// recorded it, with the archive flags its stored form takes and whether it is mount
// metadata (meta/0.pathc) rather than a file of the private group.
struct Change {
    Blob before, after;
    std::uint64_t flags{};
    bool meta = false;
};
using PackageChanges = std::vector<std::pair<std::string, Change>>;
// One package's changes read from a change set file ("CDMWCHG1"), the provisional input of
// the launch-time composition until packages carry runtime/ members. FormatError on any
// malformed, repeated or trailing record.
PackageChanges parse_change_set(const Bytes& data);

// The files a composition publishes, in prepare_profile's order: meta/0.papgt, then the
// group's 0.pamt and 0.paz when any file changed, then meta/0.pathc when there is one.
struct ComposedView {
    std::string group;
    std::vector<std::pair<std::string, Bytes>> files;
    std::size_t composed = 0;  // files in the private group
    // Every file the view was built from, for a cache key: the mount list, each listed
    // group's 0.pamt, meta/0.pathc when present and each .paz an underlay entry came from.
    std::vector<std::filesystem::path> sources;
    // Wall time per stage in milliseconds: mount, underlay, merge, store, archive.
    std::array<double, 5> stage_ms{};
};
// archive_overlay_install.overlay_directory_name for a fresh overlay: the first free
// four-digit name from 0036 that is neither a folder under `root` nor in the mount list.
std::string free_group_name(const std::filesystem::path& root, const Bytes& papgt);
// Merge each package's changes, in order, onto what the game reads today (the mounted
// archives and meta/0.pathc) and build the private group `group` from the files that
// changed. Packages with field or texture operations are not composed here.
ComposedView compose_view(const std::filesystem::path& root, const std::vector<PackageChanges>& packages, const std::string& group);

std::array<std::uint8_t, 32> sha256(const std::uint8_t* data, std::size_t size);
std::string sha256_hex(const Bytes& data);
// Raw DEFLATE, refusing what zlib refuses and output past `limit` bytes.
Bytes inflate(const std::uint8_t* data, std::size_t size, std::size_t limit);
std::uint32_t crc32(const std::uint8_t* data, std::size_t size);

// One central-directory entry, as zipfile.ZipInfo reads it.
struct ZipMember {
    std::string name, orig_name;  // ZipInfo.filename (sanitized) and .orig_filename
    std::uint16_t flags{}, method{};
    std::uint32_t crc{}, external_attr{};
    std::uint64_t compressed_size{}, size{};
    // Signed, as zipfile's are: a damaged archive's prepended-data adjustment can be negative.
    std::int64_t header_offset{}, end_offset{};
};
// A ZIP archive read as zipfile.ZipFile reads it.
class ZipArchive {
public:
    explicit ZipArchive(Bytes data);
    const std::vector<ZipMember>& members() const { return members_; }
    // The member's bytes after zipfile's header, overlap and CRC checks and
    // independent_item_package's size check.
    Bytes read(const ZipMember& member) const;

private:
    Bytes data_;
    std::vector<ZipMember> members_;
};

namespace lz4 {
// One raw LZ4 block that must expand to exactly output_size bytes.
Bytes decompress(const std::uint8_t* data, std::size_t size, std::size_t output_size);
// lz4.block.decompress(uncompressed_size=capacity): the block may expand to fewer bytes.
Bytes decompress_upto(const std::uint8_t* data, std::size_t size, std::size_t capacity);
// A valid raw LZ4 block. Not byte-identical to liblz4's encoder; decoders agree on its contents.
Bytes compress(const std::uint8_t* data, std::size_t size);
}  // namespace lz4

}  // namespace cdmw::compose
