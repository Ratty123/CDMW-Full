static std::map<std::string, PamtIndex>& resident_pamt_index_cache() {
    static std::map<std::string, PamtIndex> cache;
    return cache;
}

static size_t resident_pamt_index_count() {
    return resident_pamt_index_cache().size();
}

// The key most recently served, so a completed job can keep that one index and
// drop the rest.
static std::string& last_resident_pamt_key() {
    static std::string key;
    return key;
}

static void release_resident_pamt_indexes() {
    std::map<std::string, PamtIndex> empty;
    resident_pamt_index_cache().swap(empty);
    last_resident_pamt_key().clear();
}

// Bound the resident set to the index the next job is most likely to ask for
// instead of dropping everything. Reloading it costs about 115 ms per job even
// from the on-disk cache, and consecutive previews almost always come from the
// same .pamt. One index is roughly 10 MB against the service's 512 MB
// private-bytes recycle guard, so the memory ceiling this replaces still holds.
static void trim_resident_pamt_indexes() {
    auto& cache = resident_pamt_index_cache();
    if (cache.size() <= 1) return;
    const std::string keep = last_resident_pamt_key();
    auto it = keep.empty() ? cache.end() : cache.find(keep);
    if (it == cache.end()) {
        release_resident_pamt_indexes();
        return;
    }
    std::map<std::string, PamtIndex> retained;
    retained.emplace(it->first, std::move(it->second));
    cache.swap(retained);
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
    last_resident_pamt_key() = key;
    return it->second;
}
