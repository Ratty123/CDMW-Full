// Process-lifetime, exact-file VFS. DllMain never installs hooks or performs I/O.
#include "protocol.hpp"
#include "bootstrap.hpp"
#include <atomic>
#include <cstring>
#include <mutex>
#include <sstream>

using namespace cdmw::vfs;
namespace {
struct Mapping { std::wstring source, destination; };
struct Trace { uint32_t api{}, thread{}, redirected{}, error{}; int64_t ticks{}; wchar_t path[512]{}; };
struct Slot { std::atomic<bool> ready{}; Trace row; };
std::array<Slot, 4096> trace;
std::atomic<uint32_t> trace_count{};
std::atomic<uint32_t> runtime_state{}; // 0 inert, 1 ready, 2 refused
std::vector<Mapping> mappings, directories;
Mode mode = Mode::trace;
std::once_flag initialized;
HANDLE trace_file = INVALID_HANDLE_VALUE;
std::vector<Handle> pins;
HANDLE session_pipe = INVALID_HANDLE_VALUE;
HANDLE runtime_lane = INVALID_HANDLE_VALUE;
struct Patch { void** slot; void* before; void* after; };
std::vector<Patch> patches;
decltype(&CreateFileW) next_open_w = &CreateFileW;
decltype(&CreateFileA) next_open_a = &CreateFileA;
decltype(&CreateFile2) next_open_2 = &CreateFile2;
decltype(&GetFileAttributesW) next_attributes_w = &GetFileAttributesW;
decltype(&GetFileAttributesA) next_attributes_a = &GetFileAttributesA;
decltype(&GetFileAttributesExW) next_attributes_ex = &GetFileAttributesExW;
decltype(&FindFirstFileW) next_find_w = &FindFirstFileW;
decltype(&FindFirstFileExW) next_find_ex = &FindFirstFileExW;

void record(uint32_t api, LPCWSTR path, bool redirected, DWORD error) noexcept {
    const auto index = trace_count.fetch_add(1, std::memory_order_relaxed);
    if (index >= trace.size()) return;
    auto& row = trace[index].row;
    row.api = api; row.thread = GetCurrentThreadId(); row.redirected = redirected ? 1u : 0u; row.error = error;
    LARGE_INTEGER tick{}; QueryPerformanceCounter(&tick); row.ticks = tick.QuadPart;
    if (path) wcsncpy_s(row.path, path, _TRUNCATE);
    trace[index].ready.store(true, std::memory_order_release);
}
DWORD WINAPI flush_trace(void*) {
    for (size_t next = 0; next < trace.size();) {
        while (next < trace.size() && trace[next].ready.load(std::memory_order_acquire)) {
            DWORD written{};
            if (!WriteFile(trace_file, &trace[next].row, sizeof(Trace), &written, nullptr) || written != sizeof(Trace)) return 1;
            ++next;
        }
        Sleep(20);
    }
    return 0;
}
// No archive work, string allocation, callbacks or locks in an intercepted call.
LPCWSTR redirected(LPCWSTR name, bool directory = false) noexcept {
    if (!name || mode == Mode::trace) return name;
    std::array<wchar_t, 32768> full{};
    auto n = GetFullPathNameW(name, static_cast<DWORD>(full.size()), full.data(), nullptr);
    if (!n || n >= full.size()) return name;
    const wchar_t* canonical = full.data();
    if (wcsncmp(canonical, L"\\\\?\\", 4) == 0) canonical += 4;
    for (const auto& row : mappings) if (_wcsicmp(canonical, row.source.c_str()) == 0) return row.destination.c_str();
    if (directory) for (const auto& row : directories) if (_wcsicmp(canonical, row.source.c_str()) == 0) return row.destination.c_str();
    return name;
}
bool read_only(DWORD access, DWORD disposition) {
    constexpr DWORD forbidden = GENERIC_WRITE | GENERIC_ALL | DELETE | WRITE_DAC | WRITE_OWNER | FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA | FILE_WRITE_ATTRIBUTES;
    return disposition == OPEN_EXISTING && !(access & forbidden);
}
HANDLE WINAPI open_w(LPCWSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES security, DWORD disposition, DWORD flags, HANDLE template_file) {
    const auto previous = GetLastError(); auto path = redirected(name); const bool changed = path != name;
    if (changed && (!read_only(access, disposition) || (flags & FILE_FLAG_DELETE_ON_CLOSE))) { SetLastError(ERROR_ACCESS_DENIED); return INVALID_HANDLE_VALUE; }
    SetLastError(previous); auto result = next_open_w(path, access, share, security, disposition, flags, template_file);
    auto error = GetLastError(); record(1, name, changed, error); SetLastError(error); return result;
}
HANDLE WINAPI open_2(LPCWSTR name, DWORD access, DWORD share, DWORD disposition, LPCREATEFILE2_EXTENDED_PARAMETERS parameters) {
    const auto previous = GetLastError(); auto path = redirected(name); const bool changed = path != name;
    if (changed && (!read_only(access, disposition) || (parameters && (parameters->dwFileFlags & FILE_FLAG_DELETE_ON_CLOSE)))) { SetLastError(ERROR_ACCESS_DENIED); return INVALID_HANDLE_VALUE; }
    SetLastError(previous); auto result = next_open_2(path, access, share, disposition, parameters);
    auto error = GetLastError(); record(2, name, changed, error); SetLastError(error); return result;
}
bool widen(LPCSTR name, std::array<wchar_t, 32768>& buffer) { return name && MultiByteToWideChar(AreFileApisANSI() ? CP_ACP : CP_OEMCP, 0, name, -1, buffer.data(), static_cast<int>(buffer.size())); }
HANDLE WINAPI open_a(LPCSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES security, DWORD disposition, DWORD flags, HANDLE template_file) {
    const auto previous = GetLastError(); std::array<wchar_t, 32768> buffer{};
    if (!widen(name, buffer)) { SetLastError(previous); return next_open_a(name, access, share, security, disposition, flags, template_file); }
    auto path = redirected(buffer.data());
    if (path == buffer.data()) { SetLastError(previous); auto result = next_open_a(name, access, share, security, disposition, flags, template_file); auto error = GetLastError(); record(3, buffer.data(), false, error); SetLastError(error); return result; }
    if (!read_only(access, disposition) || (flags & FILE_FLAG_DELETE_ON_CLOSE)) { SetLastError(ERROR_ACCESS_DENIED); return INVALID_HANDLE_VALUE; }
    SetLastError(previous); auto result = next_open_w(path, access, share, security, disposition, flags, template_file);
    auto error = GetLastError(); record(3, buffer.data(), true, error); SetLastError(error); return result;
}
DWORD WINAPI attributes_w(LPCWSTR name) {
    const auto previous = GetLastError(); auto path = redirected(name, true); SetLastError(previous);
    auto result = next_attributes_w(path); auto error = GetLastError(); record(4, name, path != name, error); SetLastError(error); return result;
}
BOOL WINAPI attributes_ex(LPCWSTR name, GET_FILEEX_INFO_LEVELS level, LPVOID output) {
    const auto previous = GetLastError(); auto path = redirected(name, true); SetLastError(previous);
    auto result = next_attributes_ex(path, level, output); auto error = GetLastError(); record(5, name, path != name, error); SetLastError(error); return result;
}
DWORD WINAPI attributes_a(LPCSTR name) {
    const auto previous = GetLastError(); std::array<wchar_t, 32768> buffer{};
    if (!widen(name, buffer)) { SetLastError(previous); return next_attributes_a(name); }
    auto path = redirected(buffer.data(), true); SetLastError(previous);
    auto result = path == buffer.data() ? next_attributes_a(name) : next_attributes_w(path);
    auto error = GetLastError(); record(6, buffer.data(), path != buffer.data(), error); SetLastError(error); return result;
}
LPCWSTR enumeration(LPCWSTR name, std::array<wchar_t, 32768>& output) {
    if (!name || mode == Mode::trace) return name;
    // Exact queries, including metadata files, must describe the same file
    // returned by open/read. Wildcards only map an approved archive directory.
    auto exact = redirected(name);
    if (exact != name) return exact;
    std::array<wchar_t, 32768> full{};
    const auto n = GetFullPathNameW(name, static_cast<DWORD>(full.size()), full.data(), nullptr);
    if (!n || n >= full.size()) return name;
    auto separator = wcsrchr(full.data(), L'\\');
    if (!separator) return name;
    *separator = 0;
    auto path = redirected(full.data(), true);
    if (path == full.data()) return name;
    if (swprintf_s(output.data(), output.size(), L"%s\\%s", path, separator + 1) < 0) return name;
    return output.data();
}
HANDLE WINAPI find_w(LPCWSTR name, LPWIN32_FIND_DATAW data) {
    const auto previous = GetLastError(); std::array<wchar_t, 32768> buffer{}; auto path = enumeration(name, buffer); SetLastError(previous);
    auto result = next_find_w(path, data); auto error = GetLastError(); record(7, name, path != name, error); SetLastError(error); return result;
}
HANDLE WINAPI find_ex(LPCWSTR name, FINDEX_INFO_LEVELS level, LPVOID data, FINDEX_SEARCH_OPS search, LPVOID filter, DWORD flags) {
    const auto previous = GetLastError(); std::array<wchar_t, 32768> buffer{}; auto path = enumeration(name, buffer); SetLastError(previous);
    auto result = next_find_ex(path, level, data, search, filter, flags); auto error = GetLastError(); record(8, name, path != name, error); SetLastError(error); return result;
}
void* replacement(const char* name) {
    if (!strcmp(name, "CreateFileW")) return reinterpret_cast<void*>(&open_w);
    if (!strcmp(name, "CreateFileA")) return reinterpret_cast<void*>(&open_a);
    if (!strcmp(name, "CreateFile2")) return reinterpret_cast<void*>(&open_2);
    if (!strcmp(name, "GetFileAttributesW")) return reinterpret_cast<void*>(&attributes_w);
    if (!strcmp(name, "GetFileAttributesA")) return reinterpret_cast<void*>(&attributes_a);
    if (!strcmp(name, "GetFileAttributesExW")) return reinterpret_cast<void*>(&attributes_ex);
    if (!strcmp(name, "FindFirstFileW")) return reinterpret_cast<void*>(&find_w);
    if (!strcmp(name, "FindFirstFileExW")) return reinterpret_cast<void*>(&find_ex);
    return nullptr;
}
void exchange(const Patch& p, bool install) {
    DWORD old{};
    require(VirtualProtect(p.slot, sizeof(void*), PAGE_READWRITE, &old), "Cannot protect import slot");
    auto prior = InterlockedCompareExchangePointer(p.slot, install ? p.after : p.before, install ? p.before : p.after);
    DWORD ignored{}; const bool restored = VirtualProtect(p.slot, sizeof(void*), old, &ignored) != FALSE;
    require(prior == (install ? p.before : p.after) && restored, "Import slot changed or protection restore failed");
}
void remember_original(const char* name, void* original) {
    if (!strcmp(name, "CreateFileW")) next_open_w = reinterpret_cast<decltype(next_open_w)>(original);
    if (!strcmp(name, "CreateFileA")) next_open_a = reinterpret_cast<decltype(next_open_a)>(original);
    if (!strcmp(name, "CreateFile2")) next_open_2 = reinterpret_cast<decltype(next_open_2)>(original);
    if (!strcmp(name, "GetFileAttributesW")) next_attributes_w = reinterpret_cast<decltype(next_attributes_w)>(original);
    if (!strcmp(name, "GetFileAttributesA")) next_attributes_a = reinterpret_cast<decltype(next_attributes_a)>(original);
    if (!strcmp(name, "GetFileAttributesExW")) next_attributes_ex = reinterpret_cast<decltype(next_attributes_ex)>(original);
    if (!strcmp(name, "FindFirstFileW")) next_find_w = reinterpret_cast<decltype(next_find_w)>(original);
    if (!strcmp(name, "FindFirstFileExW")) next_find_ex = reinterpret_cast<decltype(next_find_ex)>(original);
}
std::string address_label(void* address) {
    HMODULE owner{};
    std::array<wchar_t, 32768> path{};
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCWSTR>(address), &owner) ||
        !GetModuleFileNameW(owner, path.data(), static_cast<DWORD>(path.size()))) return "unknown module";
    const auto name = fs::path(path.data()).filename().u8string();
    std::ostringstream out;
    out << std::string(reinterpret_cast<const char*>(name.data()), name.size()) << "+0x" << std::hex
        << (reinterpret_cast<uintptr_t>(address) - reinterpret_cast<uintptr_t>(owner));
    return out.str();
}
void hook_imports(const fs::path& root) {
    auto base = reinterpret_cast<unsigned char*>(GetModuleHandleW(nullptr));
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    require(dos->e_magic == IMAGE_DOS_SIGNATURE && dos->e_lfanew > 0 && dos->e_lfanew < 0x100000, "Invalid DOS header");
    auto pe = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    require(pe->Signature == IMAGE_NT_SIGNATURE && pe->FileHeader.Machine == IMAGE_FILE_MACHINE_AMD64, "Unsupported PE");
    const auto size = pe->OptionalHeader.SizeOfImage;
    const auto imports = pe->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    require(imports.VirtualAddress && imports.VirtualAddress < size && imports.Size <= size - imports.VirtualAddress, "Invalid import directory");
    std::vector<Patch> candidates;
    std::ostringstream conflicts;
    VerifiedBootstrap bootstrap(root);
    uint32_t forwarded{};
    for (size_t offset = 0; offset + sizeof(IMAGE_IMPORT_DESCRIPTOR) <= imports.Size; offset += sizeof(IMAGE_IMPORT_DESCRIPTOR)) {
        auto descriptor = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + imports.VirtualAddress + offset);
        if (!descriptor->Name) break;
        require(descriptor->Name < size && descriptor->OriginalFirstThunk < size && descriptor->FirstThunk < size, "Invalid import descriptor");
        auto library = reinterpret_cast<const char*>(base + descriptor->Name);
        if (_stricmp(library, "kernel32.dll") && strncmp(library, "api-ms-win-core-file-", 21)) continue;
        require(descriptor->OriginalFirstThunk, "Named imports required");
        auto module = GetModuleHandleA(library); require(module, "Imported module unavailable");
        for (size_t i = 0; i < 8192; ++i) {
            auto name_offset = descriptor->OriginalFirstThunk + i * sizeof(IMAGE_THUNK_DATA64);
            auto slot_offset = descriptor->FirstThunk + i * sizeof(IMAGE_THUNK_DATA64);
            require(name_offset + sizeof(IMAGE_THUNK_DATA64) <= size && slot_offset + sizeof(IMAGE_THUNK_DATA64) <= size, "Import exceeds image");
            auto named = reinterpret_cast<IMAGE_THUNK_DATA64*>(base + name_offset);
            if (!named->u1.AddressOfData) break;
            if (IMAGE_SNAP_BY_ORDINAL64(named->u1.Ordinal)) continue;
            require(named->u1.AddressOfData + 256 < size, "Invalid import name");
            auto item = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + named->u1.AddressOfData);
            require(memchr(item->Name, 0, 256), "Unbounded import name");
            auto hook = replacement(item->Name); if (!hook) continue;
            auto original = reinterpret_cast<void*>(GetProcAddress(module, item->Name));
            auto slot = reinterpret_cast<void**>(base + slot_offset);
            if (original && *slot != original && bootstrap.accepts(item->Name, *slot, original)) {
                original = *slot;
                ++forwarded;
            }
            if (!original || *slot != original) {
                conflicts << item->Name << " is already hooked by " << address_label(*slot)
                          << "; expected " << address_label(original) << "; import RVA 0x" << std::hex << slot_offset << ". ";
                continue;
            }
            for (const auto& existing : candidates)
                require(existing.after != hook || existing.before == original, "Duplicate imports have different forwarding targets");
            remember_original(item->Name, original);
            candidates.push_back({slot, original, hook});
        }
    }
    if (!conflicts.str().empty()) {
        conflicts << "Coexistence is unverified. Startup stack: ";
        std::array<void*, 16> frames{};
        const auto count = CaptureStackBackTrace(0, static_cast<DWORD>(frames.size()), frames.data(), nullptr);
        for (USHORT i = 0; i < count; ++i) conflicts << address_label(frames[i]) << "; ";
        throw std::runtime_error(conflicts.str());
    }
    require(!candidates.empty(), "No supported file imports");
    record(10, L"Verified UAL 9.7.1 forwarding wrappers", false, forwarded);
    try { for (const auto& patch : candidates) { patches.push_back(patch); exchange(patch, true); } }
    catch (...) { for (auto it = patches.rbegin(); it != patches.rend(); ++it) { try { if (*it->slot == it->after) exchange(*it, false); } catch (...) {} } throw; }
}
void acknowledge(const Manifest& m, DWORD code) {
    ULONG server{}; require(GetNamedPipeServerProcessId(session_pipe, &server) && server == m.host_pid, "Wrong session host");
    std::array<DWORD, 3> message{ready_magic, GetCurrentProcessId(), code}; DWORD written{};
    require(WriteFile(session_pipe, message.data(), sizeof(message), &written, nullptr) && written == sizeof(message), "Readiness handshake failed");
}
bool same_size_and_time(const Handle& file, const CatalogueGuard& guard) {
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(file.value, &info) || (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) return false;
    const auto size = (uint64_t(info.nFileSizeHigh) << 32) | info.nFileSizeLow;
    const auto modified = (uint64_t(info.ftLastWriteTime.dwHighDateTime) << 32) | info.ftLastWriteTime.dwLowDateTime;
    return size == guard.size && modified == guard.last_write;
}
std::string utf8(const fs::path& path) {
    const auto text = path.u8string();
    return std::string(reinterpret_cast<const char*>(text.data()), text.size());
}
void require_source(bool okay, const char* reason, const fs::path& path) {
    if (!okay) throw std::runtime_error(std::string(reason) + ": " + utf8(path) + ". Apply changes in CDMW and publish the profile again.");
}
// Launcher-independent activation of a profile CDMW published for any launcher.
// No host checks the sources first, so every guard is checked and pinned here,
// before a single import is hooked. Any refusal leaves the game unmodded.
void initialize_standalone(const fs::path& root, const fs::path& path) {
    const auto started = GetTickCount64();
    std::wstring generation;
    try {
        auto manifest = read_manifest(path);
        generation = manifest.generation;
        require(manifest.mode == Mode::standalone, "The launcher profile has the wrong mode");
        require(normalize(root) == normalize(manifest.root), "The launcher profile belongs to another installation");
        require(normalize(own_executable()) == normalize(executable(manifest)), "Unexpected game process");
        require(hash_file(own_executable()) == manifest.executable, "The game executable changed since the profile was published");
#ifndef CDMW_VIRTUAL_TESTING
        require(hex(manifest.executable) == game_hash, "Unverified game build");
#endif
        using LoaderCallout = BOOLEAN (NTAPI*)();
        const auto loader_callout = reinterpret_cast<LoaderCallout>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlIsThreadWithinLoaderCallout"));
        const DWORD loader_context = loader_callout ? loader_callout() : MAXDWORD;
#ifdef CDMW_VIRTUAL_TESTING
        const bool startup_verified = true; // The synthetic child has no game startup path.
#else
        std::array<void*, 64> startup_frames{};
        const auto frame_count = CaptureStackBackTrace(0, static_cast<DWORD>(startup_frames.size()), startup_frames.data(), nullptr);
        const bool startup_verified = loader_context == 0 && first_live_thread() &&
            VerifiedBootstrap(root).accepts_startup(std::span<void* const>(startup_frames.data(), frame_count), GetModuleHandleW(nullptr));
        if (!startup_verified) {
            std::ostringstream detail;
            detail << "Unverified startup path; items were not loaded. Loader callout " << loader_context << ". Stack: ";
            for (USHORT i = 0; i < frame_count; ++i) detail << address_label(startup_frames[i]) << "; ";
            throw std::runtime_error(detail.str());
        }
#endif
        for (const auto& guard : manifest.guards) {
            if (!guard.present) { require_source(!fs::exists(guard.path), "A file appeared after the profile was published", guard.path); continue; }
            Handle pin(CreateFileW(guard.path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
            require_source(bool(pin), "Cannot open a profile source", guard.path);
            require_source(hash_file(guard.path) == guard.sha, "A game, mod or CDMW file changed after the profile was published", guard.path);
            pins.push_back(std::move(pin));
        }
        for (const auto& guard : manifest.catalogue) {
            if (!guard.present) { require_source(!fs::exists(guard.path), "A file appeared after the profile was published", guard.path); continue; }
            Handle pin(CreateFileW(guard.path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
            require_source(bool(pin) && same_size_and_time(pin, guard), "A game or mod archive changed after the profile was published", guard.path);
            pins.push_back(std::move(pin));
        }
        runtime_lane = CreateFileW(manifest.lane.c_str(), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                   nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        require(runtime_lane != INVALID_HANDLE_VALUE, "Cannot retain runtime lease");
        OVERLAPPED lease{}; lease.Offset = 1;
        require(LockFileEx(runtime_lane, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &lease), "CDMW is changing this installation; items were not loaded");
        for (const auto& file : manifest.files) {
            Handle pin(CreateFileW(file.path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
            require_source(bool(pin), "Cannot pin a prepared item file", file.path);
            require_source(hash_file(file.path) == file.sha, "A prepared item file changed", file.path);
            pins.push_back(std::move(pin));
            mappings.push_back({normalize(root / file.logical), file.path.wstring()});
            const fs::path logical(file.logical);
            if (logical.extension() == L".pamt") directories.push_back({normalize(root / logical.parent_path()), file.path.parent_path().wstring()});
        }
        auto log = root / L".cdmw/virtual-loader/trace-standalone.bin";
        trace_file = CreateFileW(log.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        require(trace_file != INVALID_HANDLE_VALUE, "Cannot create bounded trace");
        HMODULE pinned{};
        require(GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                                  reinterpret_cast<LPCWSTR>(&initialize_standalone), &pinned), "Cannot pin runtime module");
        mode = Mode::standalone;
        record(0, L"CDMW virtual trace v1 (standalone)", false, 0);
        record(11, L"InitializeASI loader callout (0 means outside)", false, loader_context);
        record(12, L"Verified early GetCommandLineW startup path", false, startup_verified ? 1 : 0);
        hook_imports(root);
        record(13, L"All approved file import hooks installed", false, 0);
        Handle writer(CreateThread(nullptr, 0, flush_trace, nullptr, 0, nullptr));
        require(bool(writer), "Cannot start trace writer");
        runtime_state.store(1, std::memory_order_release);
        standalone_status(root, "ready", generation, 0, "", GetTickCount64() - started);
    } catch (const std::exception& error) {
        runtime_state.store(2, std::memory_order_release);
        mode = Mode::trace;
        for (auto it = patches.rbegin(); it != patches.rend(); ++it) { try { if (*it->slot == it->after) exchange(*it, false); } catch (...) {} }
        mappings.clear(); directories.clear(); pins.clear();
        try { standalone_status(root, "refused", generation, ERROR_NOT_SUPPORTED, error.what(), GetTickCount64() - started); } catch (...) {}
        throw;
    }
}
void initialize() {
    auto root = own_executable().parent_path().parent_path();
    auto path = root / L".cdmw/virtual-loader/session.bin";
    if (!fs::is_regular_file(path)) {
        // A launch CDMW did not start (Steam, DMM) uses a published standalone
        // profile when one exists. Every other ordinary launch remains inert.
        auto standalone = root / L".cdmw/virtual-loader/standalone.bin";
        if (fs::is_regular_file(standalone)) initialize_standalone(root, standalone);
        return;
    }
    auto manifest = read_manifest(path);
    const bool claiming = manifest.pid == 0 && manifest.host_pid && !manifest.launcher.empty();
    if ((!claiming && manifest.pid != GetCurrentProcessId()) || normalize(root) != normalize(manifest.root)) return;
    try {
        session_pipe = CreateFileW(pipe_name(manifest).c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (claiming && session_pipe == INVALID_HANDLE_VALUE) return; // An abandoned request cannot activate an ordinary launch.
        require(session_pipe != INVALID_HANDLE_VALUE, "No live session host; stale activation refused");
        ULONG server{};
        require(GetNamedPipeServerProcessId(session_pipe, &server) && server == manifest.host_pid, "Wrong session host");
        require(normalize(own_executable()) == normalize(executable(manifest)), "Unexpected game process");
        require(hash_file(own_executable()) == manifest.executable, "Executable fingerprint changed");
#ifdef CDMW_VIRTUAL_TESTING
        if (manifest.mode != Mode::harness)
#endif
            require(hex(manifest.executable) == game_hash, "Unverified game build");
        require(manifest.mode != Mode::redirect || game_redirection_approved, "Startup timing has not passed game validation");
        using LoaderCallout = BOOLEAN (NTAPI*)();
        const auto loader_callout = reinterpret_cast<LoaderCallout>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlIsThreadWithinLoaderCallout"));
        const DWORD loader_context = loader_callout ? loader_callout() : MAXDWORD;
        if (claiming) {
            const std::array<DWORD, 3> claim{claim_magic, GetCurrentProcessId(), 0}; DWORD bytes{};
            require(WriteFile(session_pipe, claim.data(), sizeof claim, &bytes, nullptr) && bytes == sizeof claim, "Cannot claim Steam session");
            const auto deadline = GetTickCount64() + 60000;
            for (;;) {
                require(PeekNamedPipe(session_pipe, nullptr, 0, nullptr, &bytes, nullptr), "Session host exited before binding");
                if (bytes) break;
                require(GetTickCount64() < deadline, "Steam session binding timed out");
                Sleep(10);
            }
            std::array<DWORD, 3> grant{};
            require(ReadFile(session_pipe, grant.data(), sizeof grant, &bytes, nullptr) && bytes == sizeof grant &&
                    grant[0] == grant_magic && grant[1] == GetCurrentProcessId() && grant[2] == 0, "Steam session binding was refused");
            manifest.pid = GetCurrentProcessId();
        }
        // Check after the host has identified its new Steam child, so a refusal
        // can terminate that launch instead of continuing without its profile.
        std::array<void*, 64> startup_frames{};
        const auto frame_count = CaptureStackBackTrace(0, static_cast<DWORD>(startup_frames.size()), startup_frames.data(), nullptr);
        const bool startup_verified =
#ifdef CDMW_VIRTUAL_TESTING
            manifest.mode != Mode::harness &&
#endif
            loader_context == 0 && first_live_thread() &&
            VerifiedBootstrap(root).accepts_startup(std::span<void* const>(startup_frames.data(), frame_count), GetModuleHandleW(nullptr));
        if ((manifest.mode == Mode::redirect || manifest.mode == Mode::controlled_probe) && !startup_verified) {
            std::ostringstream detail;
            detail << "Unverified startup path; virtual loading refused. Loader callout " << loader_context << ". Stack: ";
            for (USHORT i = 0; i < frame_count; ++i) detail << address_label(startup_frames[i]) << "; ";
            throw std::runtime_error(detail.str());
        }
        runtime_lane = CreateFileW(manifest.lane.c_str(), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                   nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        require(runtime_lane != INVALID_HANDLE_VALUE, "Cannot retain runtime lease");
        OVERLAPPED lease{}; lease.Offset = 1;
        require(LockFileEx(runtime_lane, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &lease), "Installation runtime lease is occupied");
        mode = manifest.mode;
        for (const auto& file : manifest.files) {
            require(hash_file(file.path) == file.sha, "Snapshot checksum mismatch");
            Handle pin(CreateFileW(file.path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
            require(bool(pin), "Cannot pin snapshot file"); pins.push_back(std::move(pin));
            mappings.push_back({normalize(root / file.logical), file.path.wstring()});
            const fs::path logical(file.logical);
            if (logical.extension() == L".pamt") directories.push_back({normalize(root / logical.parent_path()), file.path.parent_path().wstring()});
        }
        auto log = root / L".cdmw/virtual-loader" / (L"trace-" + manifest.token + L".bin");
        trace_file = CreateFileW(log.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
        require(trace_file != INVALID_HANDLE_VALUE, "Cannot create bounded trace");
        HMODULE pinned{};
        require(GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                                  reinterpret_cast<LPCWSTR>(&initialize), &pinned), "Cannot pin runtime module");
        record(0, L"CDMW virtual trace v1", false, 0);
        record(11, L"InitializeASI loader callout (0 means outside)", false, loader_context);
        record(12, L"Verified early GetCommandLineW startup path", false, startup_verified ? 1 : 0);
        hook_imports(root);
        record(13, L"All approved file import hooks installed", false, 0);
        Handle writer(CreateThread(nullptr, 0, flush_trace, nullptr, 0, nullptr));
        require(bool(writer), "Cannot start trace writer");
        acknowledge(manifest, 0);
        runtime_state.store(1, std::memory_order_release);
    } catch (const std::exception& error) {
        runtime_state.store(2, std::memory_order_release);
        status(manifest, "blocked", ERROR_NOT_SUPPORTED, error.what());
        for (auto it = patches.rbegin(); it != patches.rend(); ++it) { try { if (*it->slot == it->after) exchange(*it, false); } catch (...) {} }
        try { acknowledge(manifest, ERROR_NOT_SUPPORTED); } catch (...) {}
        throw;
    }
}
}
extern "C" __declspec(dllexport) void InitializeASI() {
    try { std::call_once(initialized, initialize); }
    catch (...) { runtime_state.store(2, std::memory_order_release); }
}
extern "C" __declspec(dllexport) DWORD CdmwVirtualState() { return runtime_state.load(std::memory_order_acquire); }
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(instance);
    return TRUE;
}
