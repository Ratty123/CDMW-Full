struct ArchiveLiteBasenameRecord {
    std::uint64_t hash = 0;
    std::uint64_t entry_id = 0;
};

static std::uint32_t archive_lite_read_u32(const unsigned char* value) {
    return static_cast<std::uint32_t>(value[0])
        | (static_cast<std::uint32_t>(value[1]) << 8)
        | (static_cast<std::uint32_t>(value[2]) << 16)
        | (static_cast<std::uint32_t>(value[3]) << 24);
}

static std::uint64_t archive_lite_read_u64(const unsigned char* value) {
    std::uint64_t result = 0;
    for (int shift = 0; shift < 64; shift += 8) {
        result |= static_cast<std::uint64_t>(*value++) << shift;
    }
    return result;
}

static std::uint64_t archive_lite_basename_hash(const std::string& value) {
    size_t start = 0;
    for (size_t index = 0; index < value.size(); ++index) {
        if (value[index] == '/' || value[index] == '\\') start = index + 1;
    }
    std::uint64_t hash = 14695981039346656037ull;
    for (size_t index = start; index < value.size(); ++index) {
        unsigned char current = static_cast<unsigned char>(value[index]);
        if (current >= 'A' && current <= 'Z') current = static_cast<unsigned char>(current + ('a' - 'A'));
        hash ^= current;
        hash *= 1099511628211ull;
    }
    return hash;
}

class ArchiveLiteLookupIndex {
public:
    ArchiveLiteLookupIndex(const fs::path& archive_index_path, const fs::path& basename_index_path)
        : archive_index_path_(fs::absolute(archive_index_path).lexically_normal()),
          basename_index_path_(fs::absolute(basename_index_path).lexically_normal()) {
        load_basename_index();
        open_archive_index();
    }

    bool matches(const EntryJob& job) const {
        return archive_index_path_ == fs::absolute(job.archive_index_path).lexically_normal()
            && basename_index_path_ == fs::absolute(job.archive_basename_index_path).lexically_normal();
    }

    std::vector<ArchiveEntryRef> lookup_basename(const std::string& basename, size_t max_count) {
        std::vector<ArchiveEntryRef> result;
        if (basename.empty() || max_count == 0) return result;
        const std::uint64_t hash = archive_lite_basename_hash(basename);
        const auto first = std::lower_bound(
            records_.begin(),
            records_.end(),
            hash,
            [](const ArchiveLiteBasenameRecord& row, std::uint64_t wanted) {
                return row.hash < wanted;
            });
        const std::string wanted = lower_copy(basename_from_path(basename));
        for (auto row = first; row != records_.end() && row->hash == hash && result.size() < max_count; ++row) {
            ArchiveEntryRef entry = read_entry(row->entry_id);
            if (lower_copy(entry.basename) == wanted) result.push_back(std::move(entry));
        }
        return result;
    }

    std::uint64_t entry_count() const { return entry_count_; }

private:
    fs::path archive_index_path_;
    fs::path basename_index_path_;
    std::ifstream archive_;
    std::vector<ArchiveLiteBasenameRecord> records_;
    std::uint64_t entry_count_ = 0;
    std::uint64_t records_offset_ = 0;
    std::uint64_t strings_offset_ = 0;
    std::uint64_t strings_size_ = 0;

    static std::uint64_t file_size_checked(const fs::path& path) {
        std::error_code ec;
        const std::uint64_t size = fs::file_size(path, ec);
        if (ec) throw std::runtime_error("could not read Archive Lite index size: " + path.string());
        return size;
    }

    static void read_exact(std::ifstream& stream, char* destination, size_t length, const char* description) {
        if (length > static_cast<size_t>(std::numeric_limits<std::streamsize>::max())) {
            throw std::runtime_error(std::string(description) + " is too large");
        }
        stream.read(destination, static_cast<std::streamsize>(length));
        if (stream.gcount() != static_cast<std::streamsize>(length)) {
            throw std::runtime_error(std::string(description) + " is truncated");
        }
    }

    void load_basename_index() {
        std::ifstream input(basename_index_path_, std::ios::binary);
        if (!input) throw std::runtime_error("could not open Archive Lite basename index");
        std::array<unsigned char, 64> header{};
        read_exact(input, reinterpret_cast<char*>(header.data()), header.size(), "Archive Lite basename index header");
        if (std::memcmp(header.data(), "CDMWABI1", 8) != 0
            || archive_lite_read_u32(header.data() + 8) != 1
            || archive_lite_read_u32(header.data() + 12) != 16) {
            throw std::runtime_error("Archive Lite basename index header is unsupported");
        }
        const std::uint64_t record_count = archive_lite_read_u64(header.data() + 16);
        const std::uint64_t records_offset = archive_lite_read_u64(header.data() + 24);
        const std::uint64_t source_entry_count = archive_lite_read_u64(header.data() + 32);
        const std::uint64_t source_file_size = archive_lite_read_u64(header.data() + 40);
        const std::uint64_t index_size = file_size_checked(basename_index_path_);
        if (record_count != source_entry_count
            || source_file_size != file_size_checked(archive_index_path_)
            || records_offset < header.size()
            || record_count > (index_size - std::min(index_size, records_offset)) / 16) {
            throw std::runtime_error("Archive Lite basename index ranges are invalid");
        }
        input.seekg(static_cast<std::streamoff>(records_offset), std::ios::beg);
        if (!input) throw std::runtime_error("could not seek Archive Lite basename index records");
        records_.resize(static_cast<size_t>(record_count));
        std::array<unsigned char, 16> row{};
        for (ArchiveLiteBasenameRecord& record : records_) {
            read_exact(input, reinterpret_cast<char*>(row.data()), row.size(), "Archive Lite basename index record");
            record.hash = archive_lite_read_u64(row.data());
            record.entry_id = archive_lite_read_u64(row.data() + 8);
            if (record.entry_id >= record_count) {
                throw std::runtime_error("Archive Lite basename index entry id is out of range");
            }
        }
        if (!std::is_sorted(records_.begin(), records_.end(), [](const auto& left, const auto& right) {
            return left.hash < right.hash || (left.hash == right.hash && left.entry_id < right.entry_id);
        })) {
            throw std::runtime_error("Archive Lite basename index is not sorted");
        }
        entry_count_ = source_entry_count;
    }

    void open_archive_index() {
        archive_.open(archive_index_path_, std::ios::binary);
        if (!archive_) throw std::runtime_error("could not open Archive Lite archive index");
        std::array<unsigned char, 64> header{};
        read_exact(archive_, reinterpret_cast<char*>(header.data()), header.size(), "Archive Lite archive index header");
        if (std::memcmp(header.data(), "CDMWALI1", 8) != 0
            || archive_lite_read_u32(header.data() + 8) != 1
            || archive_lite_read_u32(header.data() + 12) != 80) {
            throw std::runtime_error("Archive Lite archive index header is unsupported");
        }
        const std::uint64_t source_entry_count = archive_lite_read_u64(header.data() + 16);
        records_offset_ = archive_lite_read_u64(header.data() + 24);
        strings_offset_ = archive_lite_read_u64(header.data() + 32);
        strings_size_ = archive_lite_read_u64(header.data() + 40);
        const std::uint64_t file_size = file_size_checked(archive_index_path_);
        if (source_entry_count != entry_count_
            || records_offset_ < header.size()
            || strings_offset_ < records_offset_
            || entry_count_ > (strings_offset_ - records_offset_) / 80
            || strings_offset_ > file_size
            || strings_size_ > file_size - strings_offset_) {
            throw std::runtime_error("Archive Lite archive index ranges are invalid");
        }
    }

    std::string read_string(std::uint64_t offset, std::uint32_t length) {
        if (offset > strings_size_ || length > strings_size_ - offset) {
            throw std::runtime_error("Archive Lite archive index string range is invalid");
        }
        if (length == 0) return {};
        std::string value(length, '\0');
        archive_.clear();
        archive_.seekg(static_cast<std::streamoff>(strings_offset_ + offset), std::ios::beg);
        if (!archive_) throw std::runtime_error("could not seek Archive Lite archive index string");
        read_exact(archive_, value.data(), value.size(), "Archive Lite archive index string");
        return value;
    }

    ArchiveEntryRef read_entry(std::uint64_t entry_id) {
        if (entry_id >= entry_count_) throw std::runtime_error("Archive Lite archive entry id is out of range");
        std::array<unsigned char, 80> row{};
        archive_.clear();
        archive_.seekg(static_cast<std::streamoff>(records_offset_ + entry_id * 80), std::ios::beg);
        if (!archive_) throw std::runtime_error("could not seek Archive Lite archive index record");
        read_exact(archive_, reinterpret_cast<char*>(row.data()), row.size(), "Archive Lite archive index record");
        ArchiveEntryRef entry;
        entry.path = read_string(archive_lite_read_u64(row.data()), archive_lite_read_u32(row.data() + 48));
        std::replace(entry.path.begin(), entry.path.end(), '\\', '/');
        entry.basename = basename_from_path(entry.path);
        entry.extension = extension_from_path(entry.path);
        entry.pamt_path = fs::path(read_string(archive_lite_read_u64(row.data() + 8), archive_lite_read_u32(row.data() + 52)));
        entry.paz_file = fs::path(read_string(archive_lite_read_u64(row.data() + 16), archive_lite_read_u32(row.data() + 56)));
        entry.offset = archive_lite_read_u64(row.data() + 24);
        entry.comp_size = archive_lite_read_u64(row.data() + 32);
        entry.orig_size = archive_lite_read_u64(row.data() + 40);
        entry.flags = archive_lite_read_u32(row.data() + 60);
        entry.paz_index = archive_lite_read_u32(row.data() + 64);
        return entry;
    }
};

static std::optional<ArchiveLiteLookupIndex> g_archive_lite_lookup_index;
static std::uint64_t g_archive_lite_lookup_queries = 0;
static std::uint64_t g_archive_lite_lookup_candidates = 0;
static bool g_archive_lite_lookup_attempted = false;
static std::string g_archive_lite_lookup_error;

static ArchiveLiteLookupIndex* cached_archive_lite_lookup_index(const EntryJob& job) {
    if (job.archive_index_path.empty() || job.archive_basename_index_path.empty()) return nullptr;
    if (g_archive_lite_lookup_index.has_value() && g_archive_lite_lookup_index->matches(job)) {
        return &*g_archive_lite_lookup_index;
    }
    g_archive_lite_lookup_index.reset();
    g_archive_lite_lookup_attempted = true;
    g_archive_lite_lookup_error.clear();
    try {
        g_archive_lite_lookup_index.emplace(job.archive_index_path, job.archive_basename_index_path);
        return &*g_archive_lite_lookup_index;
    } catch (const std::exception& exc) {
        g_archive_lite_lookup_error = exc.what();
        return nullptr;
    }
}

static bool lookup_archive_lite_basename(
    const EntryJob& job,
    const std::string& basename,
    size_t max_count,
    std::vector<ArchiveEntryRef>& result
) {
    ArchiveLiteLookupIndex* index = cached_archive_lite_lookup_index(job);
    if (index == nullptr) return false;
    result = index->lookup_basename(basename, max_count);
    ++g_archive_lite_lookup_queries;
    g_archive_lite_lookup_candidates += static_cast<std::uint64_t>(result.size());
    return true;
}

static size_t resident_archive_lite_lookup_count() {
    return g_archive_lite_lookup_index.has_value() ? 1 : 0;
}

static void release_resident_archive_lite_lookup() {
    g_archive_lite_lookup_index.reset();
}

static void reset_archive_lite_lookup_diagnostics() {
    g_archive_lite_lookup_queries = 0;
    g_archive_lite_lookup_candidates = 0;
    g_archive_lite_lookup_attempted = false;
    g_archive_lite_lookup_error.clear();
}

static std::string archive_lite_lookup_backend() {
    if (g_archive_lite_lookup_queries > 0 || g_archive_lite_lookup_index.has_value()) return "archive_lite_basename_index_v1";
    if (g_archive_lite_lookup_attempted && !g_archive_lite_lookup_error.empty()) return "package_scan_fallback";
    return "package_scan";
}
