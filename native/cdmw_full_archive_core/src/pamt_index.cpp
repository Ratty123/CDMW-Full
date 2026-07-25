#include "archive_core_internal.hpp"

#include <execution>
#include <future>
#include <thread>

#if defined(_WIN32)
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace cdmw::full_archive {

namespace {

class VfsPathResolver {
public:
    explicit VfsPathResolver(std::vector<std::uint8_t> data, size_t maximum_cache = 200000)
        : data_(std::move(data)), maximum_cache_(maximum_cache) {}

    std::string full_path(std::uint32_t offset) {
        if (offset == 0xFFFFFFFFu) return {};
        if (offset >= data_.size()) throw std::runtime_error("VFS path offset is outside the name block");
        if (const auto cached = cache_.find(offset); cached != cache_.end()) return cached->second;
        std::vector<std::pair<std::uint32_t, std::string>> parts;
        std::set<std::uint32_t> seen;
        std::uint32_t current = offset;
        std::string base;
        while (current != 0xFFFFFFFFu) {
            if (!seen.insert(current).second) throw std::runtime_error("VFS path contains a parent cycle");
            if (const auto cached = cache_.find(current); cached != cache_.end()) {
                base = cached->second;
                break;
            }
            if (current >= data_.size() || data_.size() - current < 5) {
                throw std::runtime_error("VFS path record is truncated");
            }
            const auto parent = read_u32(data_, current);
            const auto length = static_cast<size_t>(data_[current + 4]);
            if (data_.size() - current - 5 < length) throw std::runtime_error("VFS path text is truncated");
            parts.emplace_back(
                current,
                std::string(
                    reinterpret_cast<const char*>(data_.data() + current + 5),
                    length));
            current = parent;
            if (parts.size() > 255) throw std::runtime_error("VFS path depth exceeds 255 records");
        }
        std::string built = base;
        for (auto part = parts.rbegin(); part != parts.rend(); ++part) {
            built += part->second;
            if (cache_.size() < maximum_cache_) cache_[part->first] = built;
        }
        return built;
    }

private:
    std::vector<std::uint8_t> data_;
    size_t maximum_cache_;
    std::unordered_map<std::uint32_t, std::string> cache_;
};

struct FolderRange {
    std::uint32_t start = 0;
    std::uint32_t end = 0;
    std::string directory;
};

struct LoadPriority {
    int tier = 0;
    std::uint64_t package_number = 0;
    bool pamt_is_numeric = false;
    std::uint64_t pamt_number = 0;
    std::uint32_t paz_index = 0;
    std::string pamt_path;
};

bool parse_decimal(const std::string& value, std::uint64_t& parsed) {
    if (value.empty() || !std::all_of(value.begin(), value.end(), [](unsigned char ch) { return std::isdigit(ch) != 0; })) {
        return false;
    }
    parsed = 0;
    for (const auto ch : value) {
        const auto digit = static_cast<std::uint64_t>(ch - '0');
        if (parsed > (std::numeric_limits<std::uint64_t>::max() - digit) / 10) return false;
        parsed = parsed * 10 + digit;
    }
    return true;
}

LoadPriority load_priority(const Entry& entry) {
    const auto& pamt_path = entry.source->pamt_path;
    const auto package = lower_copy(pamt_path.parent_path().filename().string());
    const auto pamt_stem = lower_copy(pamt_path.stem().string());
    std::uint64_t package_number = 0;
    std::uint64_t pamt_number = 0;
    const auto numeric_package = parse_decimal(package, package_number);
    const auto numeric_pamt = parse_decimal(pamt_stem, pamt_number);
    const auto tier = package.rfind("dmm", 0) == 0 ? 3 : numeric_package ? 1 : 2;
    return {tier, package_number, numeric_pamt, pamt_number, entry.paz_index, lower_copy(pamt_path.string())};
}

// Override priority depends only on the entry source and its PAZ index, so it is
// derived once per (source, paz) pair instead of re-deriving lowercase package,
// stem, and path strings for every duplicate candidate.
class LoadPriorityCache {
public:
    const LoadPriority& of(const Entry& entry) {
        const auto key = std::make_pair(entry.source.get(), entry.paz_index);
        const auto cached = priorities_.find(key);
        if (cached != priorities_.end()) return cached->second;
        return priorities_.emplace(key, load_priority(entry)).first->second;
    }

private:
    struct KeyHash {
        size_t operator()(const std::pair<const EntrySource*, std::uint32_t>& key) const noexcept {
            return std::hash<const void*>{}(key.first) ^ (static_cast<size_t>(key.second) * 0x9E3779B97F4A7C15ull);
        }
    };

    std::unordered_map<std::pair<const EntrySource*, std::uint32_t>, LoadPriority, KeyHash> priorities_;
};

bool lower_priority(const LoadPriority& left, const LoadPriority& right) {
    if (left.tier != right.tier) return left.tier < right.tier;
    if (left.package_number != right.package_number) return left.package_number < right.package_number;
    if (left.pamt_is_numeric != right.pamt_is_numeric) return !left.pamt_is_numeric;
    if (left.pamt_number != right.pamt_number) return left.pamt_number < right.pamt_number;
    if (left.paz_index != right.paz_index) return left.paz_index < right.paz_index;
    return left.pamt_path < right.pamt_path;
}

std::vector<Entry> parse_pamt(const fs::path& pamt_path) {
    const auto data = read_binary(pamt_path, kMaximumPamtBytes);
    if (data.size() < 12) throw std::runtime_error(pamt_path.string() + " is too small to be a PAMT file");
    size_t offset = 0;
    const auto paz_count = read_u32(data, 4);
    offset = 12;
    if (paz_count > (data.size() - offset) / 12) throw std::runtime_error("PAMT PAZ table is truncated");
    offset += static_cast<size_t>(paz_count) * 12;
    const auto directory_size = read_u32(data, offset);
    offset += 4;
    if (directory_size > data.size() - offset) throw std::runtime_error("PAMT directory block is truncated");
    std::vector<std::uint8_t> directories(data.begin() + offset, data.begin() + offset + directory_size);
    offset += directory_size;
    const auto names_size = read_u32(data, offset);
    offset += 4;
    if (names_size > data.size() - offset) throw std::runtime_error("PAMT filename block is truncated");
    std::vector<std::uint8_t> names(data.begin() + offset, data.begin() + offset + names_size);
    offset += names_size;
    const auto folder_count = read_u32(data, offset);
    offset += 4;
    if (folder_count > (data.size() - offset) / 16) throw std::runtime_error("PAMT folder table is truncated");
    const size_t folder_table_offset = offset;
    offset += static_cast<size_t>(folder_count) * 16;
    const auto file_count = read_u32(data, offset);
    offset += 4;
    if (file_count > (data.size() - offset) / 20) throw std::runtime_error("PAMT file table is truncated");
    const size_t file_table_offset = offset;

    VfsPathResolver file_resolver(std::move(names));
    VfsPathResolver directory_resolver(std::move(directories), 50000);
    std::vector<FolderRange> ranges;
    ranges.reserve(folder_count);
    for (std::uint32_t index = 0; index < folder_count; ++index) {
        const size_t row = folder_table_offset + static_cast<size_t>(index) * 16;
        const auto name_offset = read_u32(data, row + 4);
        const auto first_file = read_u32(data, row + 8);
        const auto count = read_u32(data, row + 12);
        if (count == 0) continue;
        if (first_file > file_count || count > file_count - first_file) {
            throw std::runtime_error("PAMT folder range is outside the file table");
        }
        ranges.push_back({first_file, first_file + count, slash_copy(directory_resolver.full_path(name_offset))});
    }
    std::sort(ranges.begin(), ranges.end(), [](const FolderRange& left, const FolderRange& right) {
        return left.start < right.start;
    });

    auto source = std::make_shared<EntrySource>();
    source->pamt_path = fs::absolute(pamt_path).lexically_normal();
    source->paz_paths.reserve(paz_count);
    for (std::uint32_t paz_index = 0; paz_index < paz_count; ++paz_index) {
        source->paz_paths.push_back(source->pamt_path.parent_path() / (std::to_string(paz_index) + ".paz"));
    }
    std::vector<Entry> entries;
    entries.reserve(file_count);
    size_t folder_cursor = 0;
    for (std::uint32_t index = 0; index < file_count; ++index) {
        const size_t row = file_table_offset + static_cast<size_t>(index) * 20;
        Entry entry;
        entry.path = slash_copy(file_resolver.full_path(read_u32(data, row)));
        while (folder_cursor < ranges.size() && index >= ranges[folder_cursor].end) ++folder_cursor;
        if (folder_cursor < ranges.size() && index >= ranges[folder_cursor].start && !ranges[folder_cursor].directory.empty()) {
            entry.path = ranges[folder_cursor].directory + "/" + entry.path;
        }
        entry.source = source;
        entry.archive_offset = read_u32(data, row + 4);
        entry.stored_size = read_u32(data, row + 8);
        entry.original_size = read_u32(data, row + 12);
        entry.paz_index = read_u16(data, row + 16);
        entry.flags = read_u16(data, row + 18);
        if (entry.paz_index >= paz_count) throw std::runtime_error("PAMT entry has an invalid PAZ index");
        entries.push_back(std::move(entry));
    }
    return entries;
}

void append_string(std::vector<std::uint8_t>& strings, const std::string& value, std::uint64_t& offset, std::uint32_t& length) {
    offset = strings.size();
    if (value.size() > std::numeric_limits<std::uint32_t>::max()) throw std::runtime_error("index string is too large");
    length = static_cast<std::uint32_t>(value.size());
    strings.insert(strings.end(), value.begin(), value.end());
}

struct SharedStringRange {
    std::uint64_t offset = 0;
    std::uint32_t length = 0;
};

// Source paths repeat for every entry of a package, so they are interned once
// per (source, paz index) pair. Keying on the source pointer keeps this to an
// integer hash instead of hashing a full filesystem path 3.3M times.
class SourcePathInterner {
public:
    void resolve(
        std::vector<std::uint8_t>& strings,
        const EntrySource& source,
        std::uint32_t paz_index,
        SharedStringRange& pamt_range,
        SharedStringRange& paz_range) {
        auto& cached = sources_[&source];
        if (!cached.initialized) {
            append_string(strings, source.pamt_path.u8string(), cached.pamt.offset, cached.pamt.length);
            cached.paz.resize(source.paz_paths.size());
            cached.resolved.assign(source.paz_paths.size(), false);
            cached.initialized = true;
        }
        if (paz_index >= cached.paz.size()) {
            throw std::runtime_error("archive index entry references an unknown PAZ file");
        }
        if (!cached.resolved[paz_index]) {
            append_string(
                strings,
                source.paz_paths[paz_index].u8string(),
                cached.paz[paz_index].offset,
                cached.paz[paz_index].length);
            cached.resolved[paz_index] = true;
        }
        pamt_range = cached.pamt;
        paz_range = cached.paz[paz_index];
    }

private:
    struct SourceStrings {
        SharedStringRange pamt;
        std::vector<SharedStringRange> paz;
        std::vector<bool> resolved;
        bool initialized = false;
    };

    std::unordered_map<const EntrySource*, SourceStrings> sources_;
};

// Parses every PAMT into its own slot on a bounded worker pool. Largest files
// are claimed first so one oversized package cannot leave the pool idle at the
// tail, and results stay keyed by file order so the index stays deterministic.
std::vector<std::vector<Entry>> parse_pamt_files(
    const std::vector<fs::path>& pamt_files,
    const ProgressSink& progress) {
    std::vector<std::vector<Entry>> parsed(pamt_files.size());
    std::vector<size_t> schedule(pamt_files.size());
    std::iota(schedule.begin(), schedule.end(), size_t{0});
    std::vector<std::uint64_t> sizes(pamt_files.size(), 0);
    for (size_t index = 0; index < pamt_files.size(); ++index) {
        std::error_code size_error;
        sizes[index] = fs::file_size(pamt_files[index], size_error);
        if (size_error) sizes[index] = 0;
    }
    std::sort(schedule.begin(), schedule.end(), [&sizes](size_t left, size_t right) {
        if (sizes[left] != sizes[right]) return sizes[left] > sizes[right];
        return left < right;
    });

    const auto available_threads = std::max(1u, std::thread::hardware_concurrency());
    const auto worker_count = std::min(
        pamt_files.size(),
        static_cast<size_t>(std::min(8u, available_threads)));
    std::atomic<size_t> cursor{0};
    std::atomic<size_t> completed{0};
    std::mutex report_gate;
    std::mutex failure_gate;
    std::exception_ptr failure;
    if (progress) progress(0, pamt_files.size(), "index_parse", pamt_files[schedule[0]].filename().u8string());

    const auto run_worker = [&] {
        while (true) {
            const auto claimed = cursor.fetch_add(1, std::memory_order_relaxed);
            if (claimed >= schedule.size()) return;
            {
                std::lock_guard<std::mutex> guard(failure_gate);
                if (failure) return;
            }
            const auto file_index = schedule[claimed];
            try {
                parsed[file_index] = parse_pamt(pamt_files[file_index]);
                const auto done = completed.fetch_add(1, std::memory_order_relaxed) + 1;
                if (progress) {
                    // The sink raises on cancellation, so it stays inside the guarded
                    // body: an escaping exception would terminate the worker thread.
                    std::lock_guard<std::mutex> guard(report_gate);
                    progress(done, pamt_files.size(), "index_parse", pamt_files[file_index].filename().u8string());
                }
            } catch (...) {
                std::lock_guard<std::mutex> guard(failure_gate);
                if (!failure) failure = std::current_exception();
                return;
            }
        }
    };

    std::vector<std::thread> workers;
    workers.reserve(worker_count - 1);
    for (size_t worker = 1; worker < worker_count; ++worker) {
        workers.emplace_back(run_worker);
    }
    run_worker();
    for (auto& worker : workers) worker.join();
    if (failure) std::rethrow_exception(failure);
    return parsed;
}

// Ranks every distinct entry source once so the index sort compares a small
// integer instead of two filesystem paths on each of its N log N comparisons.
std::unordered_map<const EntrySource*, std::uint32_t> rank_entry_sources(const std::vector<Entry>& entries) {
    std::vector<const EntrySource*> sources;
    sources.reserve(64);
    for (const auto& entry : entries) {
        const auto* source = entry.source.get();
        if (sources.empty() || sources.back() != source) {
            if (std::find(sources.begin(), sources.end(), source) == sources.end()) {
                sources.push_back(source);
            }
        }
    }
    std::sort(sources.begin(), sources.end(), [](const EntrySource* left, const EntrySource* right) {
        return left->pamt_path < right->pamt_path;
    });
    std::unordered_map<const EntrySource*, std::uint32_t> ranks;
    ranks.reserve(sources.size() * 2);
    for (std::uint32_t rank = 0; rank < sources.size(); ++rank) {
        ranks.emplace(sources[rank], rank);
    }
    return ranks;
}

// Sorts a permutation rather than the entries themselves: the parallel sort then
// moves each entry exactly once instead of shuffling strings through a merge
// buffer, and falling back on the original position keeps the order stable.
void sort_entries(std::vector<Entry>& entries) {
    if (entries.size() < 2) return;
    if (entries.size() > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("archive index exceeds the sortable entry limit");
    }
    const auto ranks = rank_entry_sources(entries);
    std::vector<std::uint32_t> order(entries.size());
    std::iota(order.begin(), order.end(), 0u);
    std::sort(
        std::execution::par,
        order.begin(),
        order.end(),
        [&entries, &ranks](std::uint32_t left_index, std::uint32_t right_index) {
            const auto& left = entries[left_index];
            const auto& right = entries[right_index];
            const auto path_order = compare_case_insensitive(left.path, right.path);
            if (path_order != 0) return path_order < 0;
            if (left.source != right.source) {
                const auto left_rank = ranks.at(left.source.get());
                const auto right_rank = ranks.at(right.source.get());
                if (left_rank != right_rank) return left_rank < right_rank;
            }
            if (left.archive_offset != right.archive_offset) {
                return left.archive_offset < right.archive_offset;
            }
            return left_index < right_index;
        });
    std::vector<Entry> sorted;
    sorted.reserve(entries.size());
    for (const auto index : order) sorted.push_back(std::move(entries[index]));
    entries = std::move(sorted);
}

// Buffered stream writes measured faster here than a preallocated WriteFile
// path: the index is memory-mapped again the moment it is published, and the
// hand-rolled variants only moved cost from the write into that read-back.
void write_sections(
    const fs::path& staging,
    const std::vector<std::uint8_t>& header,
    const std::vector<std::uint8_t>& records,
    const std::vector<std::uint8_t>& strings) {
    std::ofstream output(staging, std::ios::binary | std::ios::trunc);
    if (!output) throw std::runtime_error("could not create archive index staging file");
    for (const auto* section : {&header, &records, &strings}) {
        output.write(reinterpret_cast<const char*>(section->data()), static_cast<std::streamsize>(section->size()));
    }
    output.flush();
    if (!output) throw std::runtime_error("could not flush archive index staging file");
    output.close();
}

void publish_file(const fs::path& staging, const fs::path& destination) {
#if defined(_WIN32)
    if (!MoveFileExW(
            staging.c_str(),
            destination.c_str(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        throw std::runtime_error("could not atomically publish archive index");
    }
#else
    if (::rename(staging.c_str(), destination.c_str()) != 0) {
        throw std::runtime_error("could not atomically publish archive index");
    }
#endif
}

}  // namespace

std::vector<Entry> scan_package_root(const fs::path& package_root, const ProgressSink& progress) {
    std::error_code error;
    if (!fs::exists(package_root, error) || error) throw std::runtime_error("archive root does not exist");
    std::vector<fs::path> pamt_files;
    if (fs::is_regular_file(package_root, error)) {
        if (lower_copy(package_root.extension().string()) != ".pamt") throw std::runtime_error("archive file is not a PAMT");
        pamt_files.push_back(package_root);
        if (progress) progress(1, 0, "discover", package_root.filename().u8string());
    } else {
        fs::recursive_directory_iterator iterator(package_root, fs::directory_options::skip_permission_denied, error);
        const fs::recursive_directory_iterator end;
        for (; iterator != end; iterator.increment(error)) {
            if (error) {
                error.clear();
                continue;
            }
            const auto& item = *iterator;
            if (iterator.depth() == 0 && item.is_directory(error) && lower_copy(item.path().filename().string()) == "cdmods") {
                iterator.disable_recursion_pending();
                continue;
            }
            if (item.is_regular_file(error) && lower_copy(item.path().extension().string()) == ".pamt") {
                pamt_files.push_back(item.path());
                if (progress && (pamt_files.size() == 1 || (pamt_files.size() & 0x3F) == 0)) {
                    progress(pamt_files.size(), 0, "discover", item.path().filename().u8string());
                }
            }
        }
    }
    if (pamt_files.empty()) throw std::runtime_error("no PAMT files were found under the archive root");
    std::sort(pamt_files.begin(), pamt_files.end());
    auto parsed = parse_pamt_files(pamt_files, progress);
    size_t entry_total = 0;
    for (const auto& batch : parsed) entry_total += batch.size();
    std::vector<Entry> entries;
    entries.reserve(entry_total);
    for (auto& batch : parsed) {
        entries.insert(entries.end(), std::make_move_iterator(batch.begin()), std::make_move_iterator(batch.end()));
        batch.clear();
        batch.shrink_to_fit();
    }
    if (progress) progress(pamt_files.size(), pamt_files.size(), "index_parse", "complete");
    if (progress) progress(0, entries.size(), "index_sort", "");
    sort_entries(entries);
    if (progress) progress(entries.size(), entries.size(), "index_sort", "complete");
    return entries;
}

void write_index_atomic(
    const fs::path& index_path,
    const std::vector<Entry>& entries,
    const ProgressSink& progress) {
    if (index_path.empty()) throw std::invalid_argument("index path must not be empty");
    if (!index_path.parent_path().empty()) fs::create_directories(index_path.parent_path());
    std::vector<std::uint8_t> records;
    std::vector<std::uint8_t> strings;
    std::vector<std::uint32_t> override_metadata(entries.size(), 0);
    LoadPriorityCache priorities;
    for (size_t group_start = 0; group_start < entries.size();) {
        auto group_end = group_start + 1;
        while (group_end < entries.size() &&
               compare_case_insensitive(entries[group_start].path, entries[group_end].path) == 0) {
            group_end++;
        }
        if (group_end - group_start > 1) {
            auto active_index = group_start;
            const auto* active_priority = &priorities.of(entries[active_index]);
            for (auto candidate = group_start + 1; candidate < group_end; ++candidate) {
                const auto& priority = priorities.of(entries[candidate]);
                if (lower_priority(*active_priority, priority)) {
                    active_index = candidate;
                    active_priority = &priority;
                }
            }
            for (auto duplicate = group_start; duplicate < group_end; ++duplicate) override_metadata[duplicate] = 0x2u;
            override_metadata[active_index] |= 0x1u;
        }
        group_start = group_end;
    }
    const auto path_bytes = std::accumulate(
        entries.begin(),
        entries.end(),
        size_t{0},
        [](size_t total, const Entry& entry) {
            if (entry.path.size() > std::numeric_limits<size_t>::max() - total) {
                throw std::runtime_error("archive index string size overflow");
            }
            return total + entry.path.size();
        });
    strings.reserve(path_bytes + path_bytes / 8 + 4096);
    SourcePathInterner source_paths;
    records.reserve(entries.size() * kIndexRecordSize);
    for (size_t entry_index = 0; entry_index < entries.size(); ++entry_index) {
        const auto& entry = entries[entry_index];
        if (progress && (entry_index & 0x3FFFF) == 0) {
            progress(entry_index, entries.size(), "index_write", entry.path);
        }
        std::uint64_t path_offset = 0;
        std::uint32_t path_length = 0;
        SharedStringRange pamt_range;
        SharedStringRange paz_range;
        append_string(strings, entry.path, path_offset, path_length);
        source_paths.resolve(strings, *entry.source, entry.paz_index, pamt_range, paz_range);
        append_u64(records, path_offset);
        append_u64(records, pamt_range.offset);
        append_u64(records, paz_range.offset);
        append_u64(records, entry.archive_offset);
        append_u64(records, entry.stored_size);
        append_u64(records, entry.original_size);
        append_u32(records, path_length);
        append_u32(records, pamt_range.length);
        append_u32(records, paz_range.length);
        append_u32(records, entry.flags);
        append_u32(records, entry.paz_index);
        append_u32(records, override_metadata[entry_index]);
        append_u64(records, 0);
    }
    if (progress) progress(entries.size(), entries.size(), "index_write", "complete");

    std::vector<std::uint8_t> header;
    const std::array<char, 8> magic = {'C', 'D', 'M', 'W', 'F', 'A', 'I', '3'};
    header.insert(header.end(), magic.begin(), magic.end());
    append_u32(header, 3);
    append_u32(header, kIndexRecordSize);
    append_u64(header, entries.size());
    append_u64(header, 64);
    append_u64(header, 64 + records.size());
    append_u64(header, strings.size());
    append_u64(header, 0);
    append_u64(header, 0);
    if (header.size() != 64) throw std::runtime_error("archive index header size is invalid");

#if defined(_WIN32)
    const auto process_id = static_cast<unsigned long>(GetCurrentProcessId());
#else
    const auto process_id = static_cast<unsigned long>(::getpid());
#endif
    const fs::path staging = index_path.parent_path() /
        (L"." + index_path.filename().wstring() + L"." + std::to_wstring(process_id) + L"." +
         std::to_wstring([] {
             static std::atomic<std::uint64_t> sequence{0};
             return sequence.fetch_add(1, std::memory_order_relaxed);
         }()) + L".tmp");
    try {
        write_sections(staging, header, records, strings);
        if (progress) progress(0, 1, "index_publish", index_path.filename().u8string());
        publish_file(staging, index_path);
        if (progress) progress(1, 1, "index_publish", "complete");
    } catch (...) {
        std::error_code remove_error;
        fs::remove(staging, remove_error);
        throw;
    }
}

}  // namespace cdmw::full_archive
