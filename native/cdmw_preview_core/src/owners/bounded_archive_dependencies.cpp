static PamtIndex build_bounded_pamt_index(const EntryJob& job) {
    PamtIndex index;
    index.pamt_path = job.entry.pamt_path;
    std::set<std::string> seen;
    auto add_entry = [&](const ArchiveEntryRef& entry) {
        if (entry.path.empty()) return;
        const std::string key = lower_copy(entry.pamt_path.string() + "|" + entry.path);
        if (!seen.insert(key).second) return;
        ++index.entry_count;
        const auto [material_sidecar, lookup_relevant] = pamt_index_entry_traits(entry);
        if (!lookup_relevant) return;
        const std::string basename = entry.basename.empty()
            ? basename_from_path(entry.path)
            : entry.basename;
        index.by_basename[lower_copy(basename)].push_back(entry);
        if (material_sidecar) index.material_sidecars.push_back(entry);
    };
    add_entry(job.entry);
    for (const ArchiveEntryRef& entry : job.archive_dependency_entries) add_entry(entry);
    return index;
}

static bool lookup_bounded_archive_dependency_basename(
    const EntryJob& job,
    const std::string& basename,
    size_t max_count,
    std::vector<ArchiveEntryRef>& result
) {
    if (!job.archive_dependency_entries_complete) return false;
    result.clear();
    if (max_count == 0) return true;
    const std::string wanted = lower_copy(basename_from_path(basename));
    std::set<std::string> seen;
    for (const ArchiveEntryRef& entry : job.archive_dependency_entries) {
        const std::string candidate = lower_copy(
            entry.basename.empty() ? basename_from_path(entry.path) : entry.basename);
        if (candidate != wanted) continue;
        const std::string key = lower_copy(entry.pamt_path.string() + "|" + entry.path);
        if (seen.insert(key).second) result.push_back(entry);
        if (result.size() >= max_count) break;
    }
    g_bounded_archive_dependency_lookup_used = true;
    ++g_archive_lite_lookup_queries;
    g_archive_lite_lookup_candidates += static_cast<std::uint64_t>(result.size());
    record_archive_lite_dependency_query(basename, max_count, "bounded_dependencies");
    return true;
}
