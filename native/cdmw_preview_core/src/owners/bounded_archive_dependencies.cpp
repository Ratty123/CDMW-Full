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
