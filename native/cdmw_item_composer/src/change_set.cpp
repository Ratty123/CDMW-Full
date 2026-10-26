// A package's owned changes as one file: the provisional launch-time input until packages
// carry their own runtime/ members. "CDMWCHG1", u32 change count, then per change u32 +
// UTF-8 path, u8 + (u64 + bytes) before, u8 + (u64 + bytes) after, u64 flags and u8 meta.
#include "composer_internal.hpp"

#include <cstring>

namespace cdmw::compose {
using namespace detail;

PackageChanges parse_change_set(const Bytes& data) {
    std::size_t at = 0;
    const auto need = [&](std::uint64_t size) {
        if (size > data.size() - at) throw FormatError("the change set is truncated");
    };
    const auto number = [&](std::size_t width) {
        need(width);
        const auto value = le(data.data() + at, width);
        at += width;
        return value;
    };
    const auto flag = [&](const char* what) {
        const auto value = number(1);
        if (value > 1) throw FormatError(std::string("the change set has an invalid ") + what + " mark");
        return value == 1;
    };
    const auto blob = [&]() -> Blob {
        if (!flag("presence")) return nullptr;
        const auto size = number(8);
        need(size);
        auto value = std::make_shared<const Bytes>(data.begin() + static_cast<std::ptrdiff_t>(at),
                                                   data.begin() + static_cast<std::ptrdiff_t>(at + size));
        at += static_cast<std::size_t>(size);
        return value;
    };
    need(8);
    if (std::memcmp(data.data(), "CDMWCHG1", 8) != 0) throw FormatError("not a change set");
    at = 8;
    const auto count = number(4);
    PackageChanges changes;
    std::set<std::string> seen;
    for (std::uint64_t index = 0; index < count; ++index) {
        const auto length = number(4);
        need(length);
        std::string path(reinterpret_cast<const char*>(data.data() + at), static_cast<std::size_t>(length));
        at += static_cast<std::size_t>(length);
        if (path.empty() || !valid_utf8(reinterpret_cast<const std::uint8_t*>(path.data()), path.size()))
            throw FormatError("the change set names an invalid path");
        if (!seen.insert(path).second) throw FormatError("the change set names " + path + " twice");
        Change change;
        change.before = blob();
        change.after = blob();
        change.flags = number(8);
        change.meta = flag("metadata");
        changes.emplace_back(std::move(path), std::move(change));
    }
    if (at != data.size()) throw FormatError("the change set has trailing bytes");
    return changes;
}

}  // namespace cdmw::compose
