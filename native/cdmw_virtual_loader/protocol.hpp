#pragma once
#include <windows.h>
#include <array>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <string>
#include <vector>

namespace cdmw::vfs {
namespace fs = std::filesystem;
using Hash = std::array<unsigned char, 32>;
// No game build is compiled in. A profile pins the executable it was applied against,
// startup is verified by the fingerprinted bootstrap's frames and a return into the
// game's own code, and served classes are found by RTTI name, so updates need no rebuild.
// This is a compiled evidence gate, never a user-editable profile setting.
inline constexpr bool game_redirection_approved = false;
// Controlled probes require a separate host opt-in and the verified startup
// path. They do not enable the public release gate above.
// Standalone activation needs no session host: CDMW publishes a guarded profile
// that any launcher (Steam, DMM) can start. It requires the verified startup path.
enum class Mode : uint32_t { trace = 0, redirect = 1, harness = 2, controlled_probe = 3, standalone = 4 };
struct File { std::wstring logical; fs::path path; Hash sha{}; };
// A file served by game resource path inside the game's package resource loader
// (`character/model/.../x.pac`), from the generation's `files/resources` folder.
struct Resource { std::wstring logical; fs::path path; Hash sha{}; };
inline constexpr size_t max_resources = 16384;
struct Guard { fs::path path; uint32_t present{}; Hash sha{}; };
struct CatalogueGuard { fs::path path; uint32_t present{}; uint64_t size{}, last_write{}; };
struct Manifest {
    Mode mode{};
    uint32_t pid{};
    uint32_t host_pid{};
    fs::path root;
    std::wstring generation, token;
    fs::path lane;
    Hash executable{};
    fs::path launcher;
    Hash launcher_sha{};
    std::vector<File> files;
    std::vector<Resource> resources;
    std::vector<Guard> guards;
    std::vector<CatalogueGuard> catalogue;
};
struct Handle {
    HANDLE value{INVALID_HANDLE_VALUE};
    Handle() = default;
    explicit Handle(HANDLE h): value(h) {}
    ~Handle() { if (value != INVALID_HANDLE_VALUE && value) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& other) noexcept: value(other.value) { other.value = INVALID_HANDLE_VALUE; }
    explicit operator bool() const { return value && value != INVALID_HANDLE_VALUE; }
};
Manifest read_manifest(const fs::path&);
void write_manifest(const fs::path&, const Manifest&);
void validate(const Manifest&);
Hash hash_file(const fs::path&, const std::function<void(uint64_t)>& on_read = {});
std::string hex(const Hash&);
std::wstring normalize(const fs::path&);
bool resource_path(const std::wstring&);
fs::path own_executable();
fs::path executable(const Manifest&);
std::wstring pipe_name(const Manifest&);
inline constexpr DWORD claim_magic = 0x324d4443, grant_magic = 0x32474656, ready_magic = 0x31534656;
void status(const Manifest&, const char* state, DWORD error = 0, const char* detail = "", int progress = -1);
void standalone_status(const fs::path& root, const char* state, const std::wstring& generation, DWORD error, const char* detail, uint64_t elapsed_ms);
void require(bool, const char*);
}
