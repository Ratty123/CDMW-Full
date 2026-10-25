// The launch-time composition: virtual_loader_composition.prepare_profile's tail for
// packages without field or texture operations. Each package's owned changes merge onto
// what the game reads today; the changed files become one private archive group mounted
// first, beside the composed texture registry.
#include "composer_internal.hpp"

#include <fstream>
#include <iterator>

namespace cdmw::compose {
using namespace detail;
namespace {

constexpr int first_overlay_number = 36;  // archive_overlay_install.OVERLAY_DIRECTORY_FIRST

Blob read_optional(const std::filesystem::path& path) {
    std::error_code error;
    if (!std::filesystem::is_regular_file(path, error)) return nullptr;
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw FormatError("could not open " + utf8_of(path));
    return std::make_shared<const Bytes>((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
}

bool same(const Blob& x, const Blob& y) { return x == y || (x && y && *x == *y); }

}  // namespace

std::string free_group_name(const std::filesystem::path& root, const Bytes& papgt) {
    std::set<std::string> used;
    for (const auto& child : std::filesystem::directory_iterator(root))
        if (child.is_directory()) used.insert(utf8_of(child.path().filename()));
    for (const auto& directory : parse_papgt(papgt)) used.insert(directory.name);
    for (int number = first_overlay_number; number < 10000; ++number) {
        auto name = std::to_string(number);
        name.insert(0, 4 - name.size(), '0');
        if (!used.count(name)) return name;
    }
    throw FormatError("no free archive directory name is left under the package root");
}

ComposedView compose_view(const std::filesystem::path& root, const std::vector<PackageChanges>& packages, const std::string& group) {
    const auto mount = read_optional(root / "meta" / "0.papgt");
    if (!mount) throw FormatError("the game has no mount list");
    const MountedArchives archives(root, *mount);
    const auto disk_pathc = read_optional(root / "meta" / "0.pathc");
    // Every path any package touches, in first-seen order; the last flags and any meta mark win.
    std::vector<std::string> paths;
    std::map<std::string, std::uint64_t> flags;
    std::set<std::string> meta, seen;
    for (const auto& changes : packages) {
        for (const auto& [path, change] : changes) {
            if (seen.insert(path).second) paths.push_back(path);
            flags[path] = change.flags;
            if (change.meta) meta.insert(path);
        }
    }
    // What the game reads today.
    FileMap underlay;
    for (const auto& path : paths) {
        if (path == "meta/0.pathc") {
            underlay.set(path, disk_pathc);
        } else if (const auto* entry = archives.find(path)) {
            underlay.set(path, std::make_shared<const Bytes>(read_entry(*entry)));
        } else {
            underlay.set(path, nullptr);
        }
    }
    FileMap current = underlay;
    for (const auto& changes : packages) {
        FileMap before, after;
        for (const auto& [path, change] : changes) {
            before.set(path, change.before);
            after.set(path, change.after);
        }
        current = merge_overlay_files(before, after, current);
    }
    std::map<std::string, Bytes> files;  // sorted by path, as prepare_profile builds them
    for (const auto& [path, data] : current.items())
        if (!meta.count(path) && data && !same(data, underlay.get(path))) files.emplace(path, *data);
    ComposedView view;
    view.group = group;
    view.composed = files.size();
    view.files.emplace_back("meta/0.papgt", *mount);
    if (!files.empty()) {
        std::vector<OverlayFile> entries;
        for (const auto& [path, raw] : files) {
            const auto file_flags = flags.count(path) ? flags.at(path) : 0;
            const auto slash = path.rfind('/');
            entries.push_back({path, stored_payload(raw, file_flags, slash == std::string::npos ? path : path.substr(slash + 1)), raw.size(), file_flags});
        }
        const auto archive = build_overlay_archive(entries);
        view.files.front().second = papgt_with_directory(*mount, group, archive.pamt_checksum, papgt_default_flags, true);
        view.files.emplace_back(group + "/0.pamt", archive.pamt);
        view.files.emplace_back(group + "/0.paz", archive.paz);
    }
    const auto pathc = current.contains("meta/0.pathc") ? current.get("meta/0.pathc") : disk_pathc;
    if (pathc) view.files.emplace_back("meta/0.pathc", *pathc);
    return view;
}

}  // namespace cdmw::compose
