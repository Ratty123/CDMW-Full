static std::map<std::string, PamtIndex>& resident_pamt_index_cache() {
    static std::map<std::string, PamtIndex> cache;
    return cache;
}

static size_t resident_pamt_index_count() {
    return resident_pamt_index_cache().size();
}

static void release_resident_pamt_indexes() {
    std::map<std::string, PamtIndex> empty;
    resident_pamt_index_cache().swap(empty);
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
    return it->second;
}
