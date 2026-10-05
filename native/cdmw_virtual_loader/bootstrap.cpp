#include "bootstrap.hpp"
#include <cstring>
#include <string_view>
#include <tlhelp32.h>

namespace cdmw::vfs {
namespace {
constexpr char bootstrap_hash[] = "810111a7f6a6cef892877c9f7c4582ccde2d621d119891f700c5309c370508bf";
struct Witness { const char* name; uintptr_t rva, import; std::string_view code; };
// Complete x64 RUNTIME_FUNCTION boundaries from the fingerprinted binary.
// These wrappers try deferred startup once, then forward to their own Win32 IAT.
constexpr Witness witnesses[]{
    {"CreateFileA", 0x1f260, 0x820f8, "40535556574883ec58803de839090000498bd9418bf88bf2488be9752b488b4c2478488d057fb10600488d542440488944244048c74424480b000000e89f1a0100c605b0390900014c8bcb448bc78bd6488bcd4883c4585f5e5d5b48ff25362e0600"},
    {"CreateFileW", 0x1f2d0, 0x82100, "40535556574883ec58803d7939090000498bd9418bf88bf2488be9752b488b4c2478488d0527b10600488d542440488944244048c74424480b000000e82f1a0100c60541390900014c8bcb448bc78bd6488bcd4883c4585f5e5d5b48ff25ce2d0600"},
    {"FindFirstFileExW", 0x1f410, 0x82128, "40535556574883ec48803d4338090000418bd9498bf88bf2488be9752b488b4c2468488d0557b10600488d542430488944243048c744243810000000e8ef180100c6050b38090001448bcb4c8bc78bd6488bcd4883c4485f5e5d5b48ff25b62c0600"},
    {"FindFirstFileW", 0x1f480, 0x82118, "48895c2408574883ec30803dcf37090000488bda488bf9752b488b4c2438488d0583b00600488d542420488944242048c74424280e000000e883180100c6059c37090001488bd3488bcf488b5c24404883c4305f48ff253d2c0600"},
    {"GetFileAttributesA", 0x1f8a0, 0x82140, "40534883ec30803dad33090000488bd9752b488b4c2438488d057aab0600488d542420488944242048c744242812000000e86a140100c6057d33090001488bcb4883c4305b48ff2554280600"},
    {"GetFileAttributesExW", 0x1f960, 0x82158, "48895c24084889742410574883ec30803de732090000498bd88bfa488bf1752b488b4c2438488d052cab0600488d542420488944242048c744242814000000e89c130100c605b2320900014c8bc38bd7488bce488b5c2440488b7424484883c4305f48ff258f270600"},
    {"GetFileAttributesW", 0x1f9d0, 0x82148, "40534883ec30803d7e32090000488bd9752b488b4c2438488d0572aa0600488d542420488944242048c744242812000000e83a130100c6054e32090001488bcb4883c4305b48ff252c270600"},
};
bool readable(const unsigned char* begin, size_t bytes, HMODULE owner) {
    MEMORY_BASIC_INFORMATION info{};
    return VirtualQuery(begin, &info, sizeof(info)) && info.AllocationBase == owner && info.State == MEM_COMMIT &&
        !(info.Protect & (PAGE_GUARD | PAGE_NOACCESS)) &&
        bytes <= reinterpret_cast<uintptr_t>(info.BaseAddress) + info.RegionSize - reinterpret_cast<uintptr_t>(begin);
}
bool matches(const unsigned char* begin, std::string_view code, HMODULE owner) {
    if (!readable(begin, code.size() / 2, owner)) return false;
    const auto digit = [](char c) { return c <= '9' ? c - '0' : c - 'a' + 10; };
    for (size_t i = 0; i < code.size(); i += 2)
        if (begin[i / 2] != (digit(code[i]) * 16 + digit(code[i + 1]))) return false;
    return true;
}
}
bool VerifiedBootstrap::verify() {
    if (!checked) {
        checked = true;
        module = GetModuleHandleW(L"winmm.dll");
        std::array<wchar_t, 32768> path{};
        if (!module || !GetModuleFileNameW(module, path.data(), static_cast<DWORD>(path.size())) ||
            normalize(path.data()) != normalize(root / L"bin64/winmm.dll") || hex(hash_file(path.data())) != bootstrap_hash) return false;
        const auto base = reinterpret_cast<const unsigned char*>(module);
        // RestoredOnce and LoadedPluginsYet are set before InitializeASI. The
        // full instruction witnesses verify the writers and the callback site.
        if (!matches(base + 0x310c8, "33c041bc01000000f0440fb1254f1a0800", module) ||
            !matches(base + 0x32dfc, "33c0f0440fb1251dfd0700750ae8d24bffffe88dd7ffff", module) ||
            !matches(base + 0x2176e, "488d155b850600488bceff15320906004885c07402ffd0", module) ||
            !readable(base + 0xb2b24, 8, module) ||
            *reinterpret_cast<const LONG*>(base + 0xb2b24) != 1 || *reinterpret_cast<const LONG*>(base + 0xb2b28) != 1) return false;
        HMODULE retained{};
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                               reinterpret_cast<LPCWSTR>(module), &retained)) return false;
        verified = true;
    }
    return verified;
}
bool VerifiedBootstrap::accepts(const char* name, void* current, void* expected) {
    if (!verify()) return false;
    const auto base = reinterpret_cast<const unsigned char*>(module);
    for (const auto& row : witnesses) if (!strcmp(name, row.name))
        return current == base + row.rva && matches(base + row.rva, row.code, module) &&
            readable(base + row.import, sizeof(void*), module) && *reinterpret_cast<void* const*>(base + row.import) == expected;
    return false;
}
bool matches_startup_frames(std::span<void* const> frames, uintptr_t bootstrap, uintptr_t game) {
    if (!bootstrap || !game) return false;
    const std::array<uintptr_t, 5> expected{bootstrap + 0x21785, bootstrap + 0x308e8,
        bootstrap + 0x32e13, bootstrap + 0x1f848, game + 0x10958a48};
    for (size_t i = 0; i + expected.size() <= frames.size(); ++i) {
        bool same = true;
        for (size_t j = 0; j < expected.size(); ++j)
            same = same && reinterpret_cast<uintptr_t>(frames[i + j]) == expected[j];
        if (same) return true;
    }
    return false;
}
bool first_live_thread() {
    FILETIME current{}, exit{}, kernel{}, user{};
    if (!GetThreadTimes(GetCurrentThread(), &current, &exit, &kernel, &user)) return false;
    Handle snapshot(CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0));
    THREADENTRY32 entry{}; entry.dwSize = sizeof entry;
    if (!snapshot || !Thread32First(snapshot.value, &entry)) return false;
    bool found = false;
    do {
        if (entry.th32OwnerProcessID != GetCurrentProcessId()) continue;
        if (entry.th32ThreadID == GetCurrentThreadId()) { found = true; continue; }
        Handle thread(OpenThread(THREAD_QUERY_LIMITED_INFORMATION, FALSE, entry.th32ThreadID));
        FILETIME created{};
        if (!thread || !GetThreadTimes(thread.value, &created, &exit, &kernel, &user) ||
            CompareFileTime(&created, &current) <= 0) return false;
    } while (Thread32Next(snapshot.value, &entry));
    return found && GetLastError() == ERROR_NO_MORE_FILES;
}
bool VerifiedBootstrap::accepts_startup(std::span<void* const> frames, HMODULE game) {
    if (!verify()) return false;
    const auto base = reinterpret_cast<const unsigned char*>(module);
    // Complete GetCommandLineW forwarding function and its untouched system
    // destination. A late/manual InitializeASI call cannot satisfy the stack.
    return matches(base + 0x1f820, "4883ec38488b4c2438488d0588ab0600488d542420488944242048c74424280f000000e8f81401004883c43848ff258d280600", module) &&
        readable(base + 0x820e0, sizeof(void*), module) &&
        *reinterpret_cast<void* const*>(base + 0x820e0) == reinterpret_cast<void*>(GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "GetCommandLineW")) &&
        matches_startup_frames(frames, reinterpret_cast<uintptr_t>(module), reinterpret_cast<uintptr_t>(game));
}
}
