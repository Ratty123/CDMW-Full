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

namespace lz4 {
// One raw LZ4 block that must expand to exactly output_size bytes.
Bytes decompress(const std::uint8_t* data, std::size_t size, std::size_t output_size);
// A valid raw LZ4 block. Not byte-identical to liblz4's encoder; decoders agree on its contents.
Bytes compress(const std::uint8_t* data, std::size_t size);
}  // namespace lz4

}  // namespace cdmw::compose
