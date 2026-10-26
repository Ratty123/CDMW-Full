// Launch-time composition: change sets merge onto the mounted archives with the portable
// composer, and the private view is cached. A later launch reuses the cache only after
// every source it was built from and every output file is verified again.
#include "compose_launch.hpp"
#include "cdmw_composer/composer.hpp"
#include <bcrypt.h>
#include <winternl.h>
#include <algorithm>
#include <chrono>
#include <fstream>
#include <optional>
#include <set>
#include <stdexcept>

namespace cdmw::vfs {
namespace {
namespace cc = cdmw::compose;
constexpr char record_magic[] = "CDMWCCR1";
constexpr char cache_format[] = "cdmw-compose-cache-v1";
// Larger sources are kept by size and write time, as a standalone profile keeps them.
constexpr uint64_t hashed_limit = 1024 * 1024;
constexpr size_t max_sets = 256;

std::string utf8(const std::wstring& text) {
    if (text.empty()) return {};
    const auto size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    require(size > 0, "Path is not valid Unicode");
    std::string out(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), out.data(), size, nullptr, nullptr);
    return out;
}
std::wstring wide(const std::string& text) {
    if (text.empty()) return {};
    const auto size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
    require(size > 0, "Text is not valid UTF-8");
    std::wstring out(static_cast<size_t>(size), L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), out.data(), size);
    return out;
}
[[noreturn]] void refuse(const std::string& reason, const fs::path& path) {
    throw std::runtime_error(reason + ": " + utf8(path.wstring()));
}

Hash hash_bytes(const void* data, size_t size) {
    BCRYPT_ALG_HANDLE algorithm{};
    require(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0, "SHA256 unavailable");
    BCRYPT_HASH_HANDLE hash{};
    Hash result{};
    bool okay = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    for (size_t at = 0; okay && at < size;) {
        const auto chunk = static_cast<ULONG>(std::min<size_t>(size - at, 1u << 30));
        okay = BCryptHashData(hash, static_cast<PUCHAR>(const_cast<void*>(data)) + at, chunk, 0) >= 0;
        at += chunk;
    }
    okay = okay && BCryptFinishHash(hash, result.data(), static_cast<ULONG>(result.size()), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    require(okay, "SHA256 failed");
    return result;
}

cc::Bytes read_bytes(const fs::path& path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) refuse("Cannot read", path);
    const auto size = static_cast<uint64_t>(in.tellg());
    cc::Bytes data(static_cast<size_t>(size));
    in.seekg(0);
    if (size && !in.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(size))) refuse("Cannot read", path);
    return data;
}

void no_reparse(const fs::path& path) {
    const auto attributes = GetFileAttributesW(path.c_str());
    if (attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) refuse("Linked composition paths are unsupported", path);
}

struct Stamp {
    uint32_t present{}, hashed{};
    uint64_t size{}, last_write{};
    Hash sha{};
    bool operator==(const Stamp&) const = default;
};
Stamp stamp_of(const fs::path& path) {
    Stamp stamp;
    WIN32_FILE_ATTRIBUTE_DATA info{};
    if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &info)) {
        const auto error = GetLastError();
        if (error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND) return stamp;
        refuse("Cannot inspect a composition source", path);
    }
    if (info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) refuse("A composition source is not a plain file", path);
    stamp.present = 1;
    stamp.size = (uint64_t(info.nFileSizeHigh) << 32) | info.nFileSizeLow;
    stamp.last_write = (uint64_t(info.ftLastWriteTime.dwHighDateTime) << 32) | info.ftLastWriteTime.dwLowDateTime;
    if (stamp.size <= hashed_limit) {
        stamp.hashed = 1;
        stamp.sha = hash_file(path);
    }
    return stamp;
}

// Opens read-only, denying writers for the session, then checks the pinned file still
// matches what the composition was built from.
void hold(const fs::path& path, const Stamp& expected, std::vector<Handle>& pins) {
    if (!expected.present) {
        if (fs::exists(path)) refuse("A file appeared after the composition was built", path);
        return;
    }
    Handle file(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!file) refuse("Cannot open a composition source", path);
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(file.value, &info) || (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) refuse("Cannot inspect a composition source", path);
    const auto size = (uint64_t(info.nFileSizeHigh) << 32) | info.nFileSizeLow;
    const auto modified = (uint64_t(info.ftLastWriteTime.dwHighDateTime) << 32) | info.ftLastWriteTime.dwLowDateTime;
    if (size != expected.size || modified != expected.last_write || (expected.hashed && hash_file(path) != expected.sha))
        refuse("A game, mod or change set file changed after the composition was built", path);
    pins.push_back(std::move(file));
}

std::vector<fs::path> change_sets(const fs::path& folder) {
    std::vector<fs::path> sets;
    std::error_code error;
    for (const auto& entry : fs::directory_iterator(folder, error)) {
        if (_wcsicmp(entry.path().extension().c_str(), L".cdchanges") != 0) continue;
        no_reparse(entry.path());
        if (!entry.is_regular_file()) refuse("A change set is not a plain file", entry.path());
        sets.push_back(entry.path());
    }
    if (error) refuse("Cannot list the change sets", folder);
    std::sort(sets.begin(), sets.end(), [](const fs::path& x, const fs::path& y) {
        return _wcsicmp(x.filename().c_str(), y.filename().c_str()) < 0;
    });
    return sets;
}

// ---- the cache record ------------------------------------------------------------------

struct Record {
    uint32_t packages{}, composed{};
    std::string group;
    std::vector<std::pair<fs::path, Stamp>> sources;
    std::vector<std::pair<std::string, Hash>> files;
};
template <class T> void put(std::ostream& out, const T& value) { out.write(reinterpret_cast<const char*>(&value), sizeof value); }
template <class T> void get(std::istream& in, T& value) { require(bool(in.read(reinterpret_cast<char*>(&value), sizeof value)), "Truncated composition record"); }
void put_text(std::ostream& out, const std::string& text) {
    put(out, static_cast<uint32_t>(text.size()));
    out.write(text.data(), static_cast<std::streamsize>(text.size()));
}
std::string get_text(std::istream& in) {
    uint32_t size{};
    get(in, size);
    require(size < 32768, "Invalid composition record text");
    std::string text(size, '\0');
    require(bool(in.read(text.data(), size)), "Truncated composition record");
    return text;
}
void write_record(const fs::path& path, const Record& record) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out.write(record_magic, 8);
    put(out, record.packages);
    put(out, record.composed);
    put_text(out, record.group);
    put(out, static_cast<uint32_t>(record.sources.size()));
    for (const auto& [source, stamp] : record.sources) {
        put_text(out, utf8(source.wstring()));
        put(out, stamp.present); put(out, stamp.hashed); put(out, stamp.size); put(out, stamp.last_write); put(out, stamp.sha);
    }
    put(out, static_cast<uint32_t>(record.files.size()));
    for (const auto& [logical, sha] : record.files) {
        put_text(out, logical);
        put(out, sha);
    }
    out.flush();
    if (!out) refuse("Cannot write the composition record", path);
}
// A logical name the runtime may map: the mount list, the texture registry, or the
// private group's index and payload.
bool mappable(const std::string& logical, const std::string& group) {
    return logical == "meta/0.papgt" || logical == "meta/0.pathc" || logical == group + "/0.pamt" || logical == group + "/0.paz";
}
std::optional<Record> read_record(const fs::path& path, const fs::path& root) {
    if (!fs::is_regular_file(path)) return std::nullopt;
    try {
        std::ifstream in(path, std::ios::binary);
        std::array<char, 8> magic{};
        get(in, magic);
        require(std::equal(magic.begin(), magic.end(), record_magic), "Unsupported composition record");
        Record record;
        get(in, record.packages);
        get(in, record.composed);
        record.group = get_text(in);
        require(record.group.size() == 4 && std::all_of(record.group.begin(), record.group.end(), [](char c) { return c >= '0' && c <= '9'; }),
                "Invalid composition group");
        uint32_t count{};
        get(in, count);
        require(count <= 65536, "Too many composition sources");
        const auto inside = normalize(root) + L"\\";
        for (uint32_t i = 0; i < count; ++i) {
            fs::path source(wide(get_text(in)));
            Stamp stamp;
            get(in, stamp.present); get(in, stamp.hashed); get(in, stamp.size); get(in, stamp.last_write); get(in, stamp.sha);
            require(source.is_absolute() && normalize(source).starts_with(inside), "A composition source is outside the game folder");
            record.sources.emplace_back(std::move(source), stamp);
        }
        get(in, count);
        require(count >= 1 && count <= 4, "Invalid composition files");
        for (uint32_t i = 0; i < count; ++i) {
            auto logical = get_text(in);
            Hash sha{};
            get(in, sha);
            require(mappable(logical, record.group), "Invalid composition file");
            record.files.emplace_back(std::move(logical), sha);
        }
        require(in.peek() == std::char_traits<char>::eof(), "Trailing composition record bytes");
        return record;
    } catch (const std::exception&) {
        return std::nullopt;  // an unreadable record is rebuilt, never trusted
    }
}

// Pins and verifies every source and output; fills the mapping.
void adopt(const fs::path& cache, const Record& record, ComposedLaunch& launch) {
    for (const auto& [source, stamp] : record.sources) hold(source, stamp, launch.pins);
    for (const auto& [logical, sha] : record.files) {
        const auto path = cache / L"files" / fs::path(wide(logical));
        Handle file(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        if (!file) refuse("Cannot pin a composed file", path);
        if (hash_file(path) != sha) refuse("A composed file changed", path);
        launch.pins.push_back(std::move(file));
        launch.files.push_back({wide(logical), path, sha});
    }
    require(std::any_of(launch.files.begin(), launch.files.end(), [](const File& file) { return file.logical == L"meta/0.papgt"; }),
            "The composition has no mount list");
    launch.group = record.group;
    launch.packages = record.packages;
    launch.composed = record.composed;
}

void write_file(const fs::path& path, const cc::Bytes& data) {
    fs::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out.write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size()));
    out.flush();
    if (!out) refuse("Cannot write a composed file", path);
}

// On the game's startup path a composition using worker threads never finished
// (2026-10-26), most likely waiting for threads that cannot start before this call returns.
// The runtime composes on this thread alone and records whether a new thread can run.
DWORD WINAPI idle_thread(void*) { return 0; }
int worker_thread_runs() {
    Handle thread(CreateThread(nullptr, 0, idle_thread, nullptr, 0, nullptr));
    if (!thread) return -1;
    return WaitForSingleObject(thread.value, 1000) == WAIT_OBJECT_0 ? 1 : 0;  // a late thread just exits
}
int loader_lock_held() {
    const auto peb = reinterpret_cast<const unsigned char*>(NtCurrentTeb()->ProcessEnvironmentBlock);
    const auto lock = *reinterpret_cast<const RTL_CRITICAL_SECTION* const*>(peb + 0x110);  // PEB64.LoaderLock
    if (!lock) return -1;
    return reinterpret_cast<DWORD_PTR>(lock->OwningThread) == GetCurrentThreadId() ? 1 : 0;
}

std::string kind_of(const std::exception& error) {
    if (dynamic_cast<const cc::OverlayConflict*>(&error)) return "Packages conflict: ";
    if (dynamic_cast<const cc::Unsupported*>(&error)) return "Unsupported input: ";
    if (dynamic_cast<const cc::FormatError*>(&error)) return "Unreadable input: ";
    return "";
}

void compose_into(const fs::path& root, const fs::path& cache, const std::vector<fs::path>& sets, const std::vector<Stamp>& set_stamps,
                  ComposedLaunch& launch) {
    const auto started = std::chrono::steady_clock::now();
    cc::ComposedView view;
    try {
        std::vector<cc::PackageChanges> packages;
        for (const auto& set : sets) {
            try {
                packages.push_back(cc::parse_change_set(read_bytes(set)));
            } catch (const cc::FormatError& error) {
                refuse(std::string("Unreadable change set (") + error.what() + ")", set);
            }
        }
        view = cc::compose_view(root, packages, launch.group, false);
    } catch (const cc::ComposeError& error) {
        throw std::runtime_error(kind_of(error) + error.what());
    }
    launch.compose_ms = static_cast<uint64_t>(std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count());
    launch.stage_ms = view.stage_ms;
    Record record;
    record.packages = static_cast<uint32_t>(sets.size());
    record.composed = static_cast<uint32_t>(view.composed);
    record.group = view.group;
    for (size_t i = 0; i < sets.size(); ++i) {
        if (stamp_of(sets[i]) != set_stamps[i]) refuse("A change set changed while composing", sets[i]);
        record.sources.emplace_back(sets[i], set_stamps[i]);
    }
    for (const auto& source : view.sources) record.sources.emplace_back(source, stamp_of(source));
    auto staging = cache;
    staging += L".partial-" + std::to_wstring(GetCurrentProcessId());
    std::error_code ignored;
    fs::remove_all(staging, ignored);
    for (const auto& [logical, data] : view.files) {
        write_file(staging / L"files" / fs::path(wide(logical)), data);
        record.files.emplace_back(logical, hash_bytes(data.data(), data.size()));
    }
    write_record(staging / L"record.bin", record);
    if (fs::exists(cache)) {
        auto stale = cache;
        stale += L".stale-" + std::to_wstring(GetCurrentProcessId());
        fs::remove_all(stale, ignored);
        if (!MoveFileExW(cache.c_str(), stale.c_str(), 0)) refuse("Cannot retire an earlier composition", cache);
        fs::remove_all(stale, ignored);
    }
    if (!MoveFileExW(staging.c_str(), cache.c_str(), 0)) refuse("Cannot publish the composition", cache);
}

// A name this runtime gives a cache folder: the 32-digit key, or the key with the
// staging or retired suffix an interrupted composition leaves.
bool cache_name(const std::wstring& name) {
    if (name.size() < 32 || !std::all_of(name.begin(), name.begin() + 32, [](wchar_t c) { return (c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'f'); }))
        return false;
    if (name.size() == 32) return true;
    for (const std::wstring suffix : {L".partial-", L".stale-"}) {
        const auto digits = 32 + suffix.size();
        if (name.size() > digits && name.compare(32, suffix.size(), suffix) == 0 &&
            std::all_of(name.begin() + static_cast<std::ptrdiff_t>(digits), name.end(), [](wchar_t c) { return c >= L'0' && c <= L'9'; }))
            return true;
    }
    return false;
}
// Removes a folder bottom-up. Any link inside stops it before that link is touched, so
// a link planted in the cache can never turn the removal elsewhere; a file in use stops
// it too, and the next launch tries again.
bool remove_tree(const fs::path& folder) {
    std::vector<fs::path> children;
    std::error_code error;
    for (const auto& entry : fs::directory_iterator(folder, error)) children.push_back(entry.path());
    if (error) return false;
    for (const auto& child : children) {
        const auto attributes = GetFileAttributesW(child.c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) return false;
        if ((attributes & FILE_ATTRIBUTE_DIRECTORY) ? !remove_tree(child) : !DeleteFileW(child.c_str())) return false;
    }
    return RemoveDirectoryW(folder.c_str()) != FALSE;
}
// Compositions an earlier mount or change set left behind, beside the one in use. Only
// folders with this runtime's names are considered and linked folders are skipped;
// everything else in the cache folder stays.
size_t prune_caches(const fs::path& caches, const std::string& keep) {
    const auto current = wide(keep);
    std::vector<fs::path> folders;
    std::error_code error;
    for (const auto& entry : fs::directory_iterator(caches, error)) {
        const auto name = entry.path().filename().wstring();
        if (name != current && cache_name(name)) folders.push_back(entry.path());
    }
    size_t pruned = 0;
    for (const auto& folder : folders) {
        const auto attributes = GetFileAttributesW(folder.c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY) || (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) continue;
        if (remove_tree(folder)) ++pruned;
    }
    return pruned;
}

}  // namespace

bool composition_requested(const fs::path& root) {
    try {
        const auto folder = root / compose_folder;
        if (!fs::is_directory(folder)) return false;
        for (const auto& entry : fs::directory_iterator(folder))
            if (_wcsicmp(entry.path().extension().c_str(), L".cdchanges") == 0) return true;
        return false;
    } catch (...) {
        return true;  // an unreadable folder is reported by the composition itself
    }
}

ComposedLaunch prepare_composition(const fs::path& root, const Hash& game) {
    ComposedLaunch launch;
    const auto folder = root / compose_folder;
    const auto caches = root / compose_cache_folder;
    for (const auto& path : {root / L".cdmw", root / L".cdmw/virtual-loader", folder, caches}) no_reparse(path);
    const auto sets = change_sets(folder);
    if (sets.empty() || sets.size() > max_sets) refuse("The compose folder must hold between 1 and 256 change sets", folder);
    launch.packages = sets.size();
    std::vector<Stamp> set_stamps;
    for (const auto& set : sets) set_stamps.push_back(stamp_of(set));
    const auto papgt_path = root / L"meta/0.papgt";
    const auto papgt = read_bytes(papgt_path);
    try {
        launch.group = cc::free_group_name(root, papgt);
    } catch (const cc::ComposeError& error) {
        throw std::runtime_error(kind_of(error) + error.what());
    }
    // The key covers the inputs known before composing; the record covers the rest.
    HMODULE self{};
    std::array<wchar_t, 32768> module{};
    require(GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               reinterpret_cast<LPCWSTR>(&prepare_composition), &self) &&
            GetModuleFileNameW(self, module.data(), static_cast<DWORD>(module.size())), "Cannot identify the runtime");
    std::string recipe = std::string(cache_format) + "|" + hex(game) + "|" + hex(hash_file(module.data())) + "|" + launch.group + "|" +
                         hex(hash_bytes(papgt.data(), papgt.size()));
    for (size_t i = 0; i < sets.size(); ++i) {
        auto name = sets[i].filename().wstring();
        std::transform(name.begin(), name.end(), name.begin(), [](wchar_t c) { return static_cast<wchar_t>(towlower(c)); });
        recipe += "|" + utf8(name) + ":" + std::to_string(set_stamps[i].size) + ":" + std::to_string(set_stamps[i].last_write) + ":" +
                  (set_stamps[i].hashed ? hex(set_stamps[i].sha) : "-");
    }
    launch.key = hex(hash_bytes(recipe.data(), recipe.size())).substr(0, 32);
    const auto cache = caches / fs::path(wide(launch.key));
    if (const auto record = read_record(cache / L"record.bin", root)) {
        try {
            adopt(cache, *record, launch);
            launch.reused = true;
            launch.pruned = prune_caches(caches, launch.key);
            return launch;
        } catch (const std::exception&) {
            launch.pins.clear();
            launch.files.clear();
        }
    }
    fs::create_directories(caches);
    launch.loader_lock = loader_lock_held();
    launch.worker_thread = worker_thread_runs();
    compose_status(root, "composing", launch, 0, "", 0);  // a launch that stops here shows where
    compose_into(root, cache, sets, set_stamps, launch);
    const auto record = read_record(cache / L"record.bin", root);
    require(record.has_value(), "The composition record cannot be read back");
    const auto stages = launch.stage_ms;
    const auto compose_ms = launch.compose_ms;
    adopt(cache, *record, launch);
    launch.stage_ms = stages;
    launch.compose_ms = compose_ms;
    launch.pruned = prune_caches(caches, launch.key);
    return launch;
}

fs::path installation_lane(const fs::path& root) {
    Handle folder(CreateFileW(root.c_str(), 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr));
    require(bool(folder), "Cannot resolve the game folder");
    std::array<wchar_t, 32768> buffer{};
    const auto count = GetFinalPathNameByHandleW(folder.value, buffer.data(), static_cast<DWORD>(buffer.size()), FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    require(count && count < buffer.size(), "Cannot resolve the game folder");
    std::wstring resolved(buffer.data(), count);
    if (resolved.starts_with(L"\\\\?\\UNC\\")) resolved = L"\\\\" + resolved.substr(8);
    else if (resolved.starts_with(L"\\\\?\\")) resolved.erase(0, 4);
    // str(Path.resolve()).casefold(): exact for ASCII, simple lower case beyond it.
    std::transform(resolved.begin(), resolved.end(), resolved.begin(), [](wchar_t c) { return static_cast<wchar_t>(towlower(c)); });
    const auto text = utf8(resolved);
    std::array<wchar_t, MAX_PATH + 1> temp{};
    require(GetTempPathW(static_cast<DWORD>(temp.size()), temp.data()), "Cannot identify lock directory");
    return fs::path(temp.data()) / (L"cdmw-installation-" + wide(hex(hash_bytes(text.data(), text.size()))) + L".lock");
}

void compose_status(const fs::path& root, const char* state, const ComposedLaunch& launch, DWORD error, const char* detail, uint64_t elapsed_ms) {
    const auto escape = [](const std::string& text) {
        std::string out;
        for (const auto c : text) {
            if (c == '\\' || c == '"') out += '\\';
            if (static_cast<unsigned char>(c) >= 32) out += c;
        }
        return out;
    };
    auto path = root / L".cdmw/virtual-loader/compose-status.json";
    auto temp = path;
    temp += L".tmp";
    {
        std::ofstream out(temp);
        out << "{\"state\":\"" << state << "\",\"pid\":" << GetCurrentProcessId() << ",\"key\":\"" << escape(launch.key)
            << "\",\"cache\":\"" << (launch.reused ? "reused" : launch.files.empty() ? "none" : "composed") << "\",\"group\":\"" << escape(launch.group)
            << "\",\"packages\":" << launch.packages << ",\"composed\":" << launch.composed << ",\"compose_ms\":" << launch.compose_ms
            << ",\"stage_ms\":[";
        for (size_t i = 0; i < launch.stage_ms.size(); ++i) out << (i ? "," : "") << static_cast<uint64_t>(launch.stage_ms[i]);
        out << "],\"worker_thread\":" << launch.worker_thread << ",\"loader_lock\":" << launch.loader_lock
            << ",\"pruned\":" << launch.pruned << ",\"error\":" << error << ",\"elapsed_ms\":" << elapsed_ms << ",\"detail\":\"" << escape(detail) << "\"}";
        out.flush();
    }
    MoveFileExW(temp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}
}
