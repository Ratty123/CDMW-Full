static std::map<std::string, PamtIndex>& resident_pamt_index_cache() {
    static std::map<std::string, PamtIndex> cache;
    return cache;
}

static size_t resident_pamt_index_count() {
    return resident_pamt_index_cache().size();
}

// Recency ticks per cache key, so a completed job keeps the indexes that are
// actually being used and evicts only the coldest ones.
static std::map<std::string, std::uint64_t>& resident_pamt_index_recency() {
    static std::map<std::string, std::uint64_t> recency;
    return recency;
}

static std::uint64_t next_resident_pamt_index_tick() {
    static std::uint64_t tick = 0;
    return ++tick;
}

// Approximate in-memory footprint of one index. Each ArchiveEntryRef holds
// three std::strings and two wide fs::paths plus hash-bucket overhead, which
// measures ~500-700 bytes per entry on MSVC against real game archives
// (33 indexes ~690 MB resident), so 600 bytes per entry lands close.
static std::uint64_t approximate_pamt_index_resident_bytes(const PamtIndex& index) {
    return 64ull * 1024ull + static_cast<std::uint64_t>(index.entry_count) * 600ull;
}

// Byte budget for resident indexes. The service recycles itself at 512 MB
// private bytes and the decoded-entry cache recycle threshold is 192 MB, so
// this budget keeps the healthy steady state well below the recycle guard.
// The count bound matches the package-root scan cap and only matters for
// roots full of tiny indexes.
static constexpr std::uint64_t kResidentPamtIndexMaxBytes = 224ull * 1024ull * 1024ull;
static constexpr size_t kResidentPamtIndexMaxCount = 64;

static void release_resident_pamt_indexes() {
    std::map<std::string, PamtIndex> empty;
    resident_pamt_index_cache().swap(empty);
    resident_pamt_index_recency().clear();
}

// Bound the resident set by recency and bytes instead of dropping everything.
// The previous policy kept only the most recently touched index, which evicted
// the primary index whenever a job ended on a cross-package lookup and forced
// every following job to reload it at ~100 ms even from the on-disk cache.
static void trim_resident_pamt_indexes() {
    auto& cache = resident_pamt_index_cache();
    auto& recency = resident_pamt_index_recency();
    for (auto it = recency.begin(); it != recency.end();) {
        it = cache.count(it->first) ? std::next(it) : recency.erase(it);
    }
    std::vector<std::pair<std::uint64_t, std::string>> by_recency;
    by_recency.reserve(cache.size());
    std::uint64_t total_bytes = 0;
    for (const auto& [key, index] : cache) {
        auto found = recency.find(key);
        by_recency.emplace_back(found == recency.end() ? 0 : found->second, key);
        total_bytes += approximate_pamt_index_resident_bytes(index);
    }
    std::sort(by_recency.begin(), by_recency.end());
    size_t evicted = 0;
    for (const auto& [_tick, key] : by_recency) {
        const bool over_count = cache.size() > kResidentPamtIndexMaxCount;
        const bool over_bytes = total_bytes > kResidentPamtIndexMaxBytes && cache.size() > 1;
        if (!over_count && !over_bytes) break;
        auto found = cache.find(key);
        if (found == cache.end()) continue;
        total_bytes -= std::min(total_bytes, approximate_pamt_index_resident_bytes(found->second));
        cache.erase(found);
        recency.erase(key);
        ++evicted;
    }
    (void)evicted;
}

static const PamtIndex& cached_pamt_index(
    const fs::path& pamt_path,
    const fs::path& cache_root = fs::path()
) {
    auto& cache = resident_pamt_index_cache();
    const PamtIndexSourceStamp source_stamp = pamt_index_source_stamp(pamt_path);
    const std::string key =
        lower_copy(fs::absolute(pamt_path).lexically_normal().string()) + "|" +
        std::to_string(source_stamp.size) + "|" + std::to_string(source_stamp.mtime);
    auto it = cache.find(key);
    if (it == cache.end()) {
        const fs::path persistent_path = pamt_index_cache_path(pamt_path, cache_root);
        std::optional<PamtIndex> persisted;
        try {
            persisted = load_pamt_index_cache(persistent_path, pamt_path, source_stamp);
        } catch (...) {
            persisted.reset();
        }
        if (persisted.has_value()) {
            it = cache.emplace(key, std::move(*persisted)).first;
        } else {
            std::error_code remove_error;
            if (!persistent_path.empty()) fs::remove(persistent_path, remove_error);
            PamtIndex parsed = parse_pamt_index(pamt_path);
            parsed.persistent_cache_path = persistent_path;
            try {
                write_pamt_index_cache(persistent_path, parsed, source_stamp);
            } catch (...) {
                // Cache publication failure must not block a valid preview.
            }
            it = cache.emplace(key, std::move(parsed)).first;
        }
    }
    resident_pamt_index_recency()[key] = next_resident_pamt_index_tick();
    return it->second;
}
