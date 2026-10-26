// The launch-time composition: virtual_loader_composition.prepare_profile's tail for
// packages without field or texture operations. Each package's owned changes merge onto
// what the game reads today; the changed files become one private archive group mounted
// first, beside the composed texture registry.
#include "composer_internal.hpp"

#include <chrono>

namespace cdmw::compose {
using namespace detail;
namespace {

constexpr int first_overlay_number = 36;  // archive_overlay_install.OVERLAY_DIRECTORY_FIRST

Blob read_optional(const std::filesystem::path& path) {
    std::error_code error;
    if (!std::filesystem::is_regular_file(path, error)) return nullptr;
    return std::make_shared<const Bytes>(read_whole_file(path));
}

bool same(const Blob& x, const Blob& y) { return x == y || (x && y && *x == *y); }

FileMap package_side(const PackageChanges& changes, bool after) {
    FileMap files;
    for (const auto& [path, change] : changes) files.set(path, after ? change.after : change.before);
    return files;
}

// Each package's merge_overlay_files in order. A path's merge reads only its own unit
// (a table's body and header, or the path alone), so each unit's chain over the packages
// runs on its own and the results are joined. A failure is the one the sequential order
// meets first: the earliest package, then that package's earliest path.
FileMap merged(const std::vector<PackageChanges>& packages, const std::vector<std::string>& paths, const FileMap& underlay) {
    std::vector<std::string> keys;
    std::unordered_map<std::string, std::size_t> unit_of;
    bool separable = true;
    for (const auto& path : paths) {
        const auto key = merge_unit(path);
        if (key != path || ends_with(path, ".staticinfobody") || ends_with(path, ".pabgb"))
            separable = separable && merge_unit(key) == key && merge_unit(table_header(key)) == key;
        if (unit_of.emplace(key, keys.size()).second) keys.push_back(key);
    }
    if (!separable || keys.size() < 2) {
        FileMap current = underlay;
        for (const auto& changes : packages) current = merge_overlay_files(package_side(changes, false), package_side(changes, true), current);
        return current;
    }
    struct Unit {
        std::vector<PackageChanges> steps;  // the unit's changes of each package, in order
        FileMap state;
        std::exception_ptr error;
        std::size_t package = 0, position = 0;
        std::uint64_t weight = 0;
    };
    std::vector<Unit> units(keys.size());
    for (auto& unit : units) unit.steps.resize(packages.size());
    std::vector<std::unordered_map<std::string, std::size_t>> positions(packages.size());
    for (std::size_t i = 0; i < packages.size(); ++i) {
        for (std::size_t j = 0; j < packages[i].size(); ++j) {
            const auto& [path, change] = packages[i][j];
            positions[i].emplace(path, j);
            units[unit_of.at(merge_unit(path))].steps[i].emplace_back(path, change);
        }
    }
    for (const auto& path : paths) {
        auto& unit = units[unit_of.at(merge_unit(path))];
        const auto data = underlay.get(path);
        unit.state.set(path, data);
        unit.weight += data ? data->size() : 0;
    }
    // The heaviest chains start first.
    std::vector<std::size_t> order(units.size());
    for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(), [&](std::size_t x, std::size_t y) { return units[x].weight > units[y].weight; });
    parallel_for(order.size(), [&](std::size_t slot) {
        auto& unit = units[order[slot]];
        for (std::size_t i = 0; i < unit.steps.size(); ++i) {
            if (unit.steps[i].empty()) continue;
            std::string failing;
            try {
                unit.state = merge_overlay_files_tracked(package_side(unit.steps[i], false), package_side(unit.steps[i], true), unit.state, &failing);
            } catch (...) {
                unit.error = std::current_exception();
                unit.package = i;
                unit.position = positions[i].at(failing);
                return;
            }
        }
    });
    const Unit* first = nullptr;
    for (const auto& unit : units)
        if (unit.error && (!first || std::make_pair(unit.package, unit.position) < std::make_pair(first->package, first->position))) first = &unit;
    if (first) std::rethrow_exception(first->error);
    FileMap current = underlay;
    for (const auto& unit : units)
        for (const auto& [path, data] : unit.state.items()) current.set(path, data);
    return current;
}

class Stopwatch {
public:
    double lap() {
        const auto now = std::chrono::steady_clock::now();
        const std::chrono::duration<double, std::milli> elapsed = now - last_;
        last_ = now;
        return elapsed.count();
    }

private:
    std::chrono::steady_clock::time_point last_ = std::chrono::steady_clock::now();
};

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
    Stopwatch clock;
    ComposedView view;
    const auto mount = read_optional(root / "meta" / "0.papgt");
    if (!mount) throw FormatError("the game has no mount list");
    // Every path any package touches, in first-seen order; the last flags and any meta mark win.
    std::vector<std::string> paths;
    std::map<std::string, std::uint64_t> flags;
    std::set<std::string> meta, seen, wanted;
    for (const auto& changes : packages) {
        for (const auto& [path, change] : changes) {
            if (seen.insert(path).second) paths.push_back(path);
            flags[path] = change.flags;
            if (change.meta) meta.insert(path);
            wanted.insert(normalize_game_path(path));
        }
    }
    // Only the touched paths are indexed; every mounted index is still read and validated.
    const MountedArchives archives(root, *mount, &wanted);
    const auto disk_pathc = read_optional(root / "meta" / "0.pathc");
    view.sources.push_back(root / "meta" / "0.papgt");
    view.sources.insert(view.sources.end(), archives.pamts().begin(), archives.pamts().end());
    if (disk_pathc) view.sources.push_back(root / "meta" / "0.pathc");
    view.stage_ms[0] = clock.lap();
    // What the game reads today.
    FileMap underlay;
    std::set<std::filesystem::path> carriers;
    for (const auto& path : paths) {
        if (path == "meta/0.pathc") {
            underlay.set(path, disk_pathc);
        } else if (const auto* entry = archives.find(path)) {
            underlay.set(path, std::make_shared<const Bytes>(read_entry(*entry)));
            if (carriers.insert(entry->paz_path).second) view.sources.push_back(entry->paz_path);
        } else {
            underlay.set(path, nullptr);
        }
    }
    view.stage_ms[1] = clock.lap();
    FileMap current = merged(packages, paths, underlay);
    view.stage_ms[2] = clock.lap();
    std::map<std::string, Bytes> files;  // sorted by path, as prepare_profile builds them
    for (const auto& [path, data] : current.items())
        if (!meta.count(path) && data && !same(data, underlay.get(path))) files.emplace(path, *data);
    view.group = group;
    view.composed = files.size();
    view.files.emplace_back("meta/0.papgt", *mount);
    std::vector<OverlayFile> entries;
    for (const auto& [path, raw] : files) {
        const auto file_flags = flags.count(path) ? flags.at(path) : 0;
        const auto slash = path.rfind('/');
        entries.push_back({path, stored_payload(raw, file_flags, slash == std::string::npos ? path : path.substr(slash + 1)), raw.size(), file_flags});
    }
    view.stage_ms[3] = clock.lap();
    if (!entries.empty()) {
        const auto archive = build_overlay_archive(entries);
        view.files.front().second = papgt_with_directory(*mount, group, archive.pamt_checksum, papgt_default_flags, true);
        view.files.emplace_back(group + "/0.pamt", archive.pamt);
        view.files.emplace_back(group + "/0.paz", archive.paz);
    }
    const auto pathc = current.contains("meta/0.pathc") ? current.get("meta/0.pathc") : disk_pathc;
    if (pathc) view.files.emplace_back("meta/0.pathc", *pathc);
    view.stage_ms[4] = clock.lap();
    return view;
}

}  // namespace cdmw::compose
