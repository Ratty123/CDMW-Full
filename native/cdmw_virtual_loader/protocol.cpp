#include "protocol.hpp"
#include <bcrypt.h>
#include <algorithm>
#include <cstring>
#include <fstream>
#include <set>
#include <stdexcept>

namespace cdmw::vfs {
void require(bool okay, const char* message) { if (!okay) throw std::runtime_error(message); }
std::wstring normalize(const fs::path& path) {
    std::array<wchar_t, 32768> buffer{};
    auto count = GetFullPathNameW(path.c_str(), static_cast<DWORD>(buffer.size()), buffer.data(), nullptr);
    require(count && count < buffer.size(), "Cannot normalize path");
    std::wstring result(buffer.data(), count);
    if (result.starts_with(L"\\\\?\\")) result.erase(0, 4);
    require(result.size() > 3 && result[1] == L':' && result[2] == L'\\', "Local absolute paths required");
    std::transform(result.begin(), result.end(), result.begin(), [](wchar_t c) { return static_cast<wchar_t>(towlower(c)); });
    while (result.size() > 3 && result.back() == L'\\') result.pop_back();
    return result;
}
fs::path own_executable() {
    std::array<wchar_t, 32768> buffer{};
    const auto n = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    require(n && n < buffer.size(), "Cannot identify executable");
    return fs::path(std::wstring(buffer.data(), n));
}
fs::path executable(const Manifest& m) { return m.root / L"bin64" / (m.mode == Mode::harness ? L"cdmw_virtual_loader_harness.exe" : L"CrimsonDesert.exe"); }
std::wstring pipe_name(const Manifest& m) { return L"\\\\.\\pipe\\cdmw-virtual-" + m.token; }
Hash hash_file(const fs::path& path) {
    BCRYPT_ALG_HANDLE algorithm{};
    require(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0, "SHA256 unavailable");
    BCRYPT_HASH_HANDLE hash{};
    if (BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) < 0) {
        BCryptCloseAlgorithmProvider(algorithm, 0); throw std::runtime_error("SHA256 initialization failed");
    }
    Hash result{};
    try {
        Handle file(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        require(bool(file), "Cannot pin input file for hashing");
        std::array<unsigned char, 65536> buffer{};
        DWORD count{};
        for (;;) {
            require(ReadFile(file.value, buffer.data(), static_cast<DWORD>(buffer.size()), &count, nullptr), "Input read failed");
            if (!count) break;
            require(BCryptHashData(hash, buffer.data(), count, 0) >= 0, "SHA256 update failed");
        }
        require(BCryptFinishHash(hash, result.data(), static_cast<ULONG>(result.size()), 0) >= 0, "SHA256 finalization failed");
    } catch (...) { BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(algorithm, 0); throw; }
    BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(algorithm, 0);
    return result;
}
std::string hex(const Hash& hash) {
    const char* digits = "0123456789abcdef";
    std::string result;
    for (auto byte : hash) { result += digits[byte >> 4]; result += digits[byte & 15]; }
    return result;
}
template<class T> void read(std::istream& in, T& value) { require(bool(in.read(reinterpret_cast<char*>(&value), sizeof value)), "Truncated manifest"); }
template<class T> void write(std::ostream& out, const T& value) { out.write(reinterpret_cast<const char*>(&value), sizeof value); }
std::wstring read_string(std::istream& in) {
    uint32_t size{}; read(in, size); require(size && size < 32768, "Invalid path length");
    std::wstring result(size, L'\0');
    require(bool(in.read(reinterpret_cast<char*>(result.data()), size * 2)), "Truncated path");
    require(result.find(L'\0') == std::wstring::npos, "NUL in path"); return result;
}
void write_string(std::ostream& out, const std::wstring& value) {
    write(out, static_cast<uint32_t>(value.size())); out.write(reinterpret_cast<const char*>(value.data()), static_cast<std::streamsize>(value.size() * 2));
}
bool identity(const std::wstring& s) { return s.size() == 32 && s.find_first_not_of(L"0123456789abcdef") == std::wstring::npos; }
void no_links(fs::path path) {
    for (; path != path.root_path(); path = path.parent_path()) {
        auto attributes = GetFileAttributesW(path.c_str());
        require(attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_REPARSE_POINT), "Linked virtual paths are unsupported");
    }
}
void validate(const Manifest& m) {
    require(m.mode == Mode::trace || m.mode == Mode::redirect || m.mode == Mode::harness || m.mode == Mode::controlled_probe, "Unknown mode");
    require(identity(m.token) && identity(m.generation), "Invalid session identity");
    require(m.root.is_absolute() && normalize(m.root) == normalize(m.root.lexically_normal()), "Invalid game root");
    no_links(m.root);
    if (!m.launcher.empty()) {
        require(m.launcher.is_absolute(), "Absolute launcher path required");
        no_links(m.launcher);
        const auto name = m.launcher.filename().wstring();
        require(_wcsicmp(name.c_str(), m.mode == Mode::harness ? L"cdmw_virtual_steam_fixture.exe" : L"steam.exe") == 0, "Unsupported launcher");
    }
    require(m.files.size() <= 256 && !m.files.empty(), "Invalid map size");
    std::set<std::wstring> seen;
    for (const auto& file : m.files) {
        fs::path logical(file.logical);
        require(!logical.is_absolute() && logical.parent_path().parent_path().empty(), "Invalid logical depth");
        auto parent = logical.parent_path().wstring();
        const bool meta = parent == L"meta" && (logical.filename() == L"0.papgt" || logical.filename() == L"0.pathc");
        const bool archive = !parent.empty() && parent.find_first_not_of(L"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") == std::wstring::npos &&
                             (logical.filename() == L"0.pamt" || logical.filename() == L"0.paz");
        require(meta || archive, "Map targets must be archives or game metadata");
        auto expected = m.root / L".cdmw/virtual-loader/generations" / m.generation / L"files" / logical;
        require(normalize(file.path) == normalize(expected) && seen.insert(normalize(m.root / logical)).second, "Escaping or duplicate map path");
        no_links(file.path);
    }
    require(seen.contains(normalize(m.root / L"meta/0.papgt")), "Missing virtual mount list");
    require(m.guards.size() <= 65536, "Too many source guards");
    std::set<std::wstring> guards;
    for (const auto& guard : m.guards) {
        require(guard.present <= 1 && guard.path.is_absolute() && guards.insert(normalize(guard.path)).second, "Invalid source guard");
        no_links(guard.path);
    }
    std::array<wchar_t, 32768> temp{};
    require(GetTempPathW(static_cast<DWORD>(temp.size()), temp.data()), "Cannot identify lock directory");
    auto name = m.lane.filename().wstring();
    require(normalize(m.lane.parent_path()) == normalize(temp.data()) && name.starts_with(L"cdmw-installation-") && name.ends_with(L".lock") && name.size() == std::wstring(L"cdmw-installation-").size() + 64 + 5,
            "Invalid installation lock");
}
Manifest read_manifest(const fs::path& path) {
    require(fs::file_size(path) < 16 * 1024 * 1024, "Oversized manifest");
    std::ifstream in(path, std::ios::binary);
    std::array<char, 8> magic{}; read(in, magic); require(std::memcmp(magic.data(), "CDVFS2\0\0", 8) == 0, "Unsupported manifest");
    Manifest m; read(in, m.mode); read(in, m.pid); read(in, m.host_pid); read(in, m.executable);
    m.root = read_string(in); m.generation = read_string(in); m.token = read_string(in); m.lane = read_string(in);
    uint32_t count{}; read(in, count); require(count && count <= 256, "Invalid map size");
    for (uint32_t i = 0; i < count; ++i) { File file; file.logical = read_string(in); file.path = read_string(in); read(in, file.sha); m.files.push_back(std::move(file)); }
    read(in, count); require(count <= 65536, "Too many source guards");
    for (uint32_t i = 0; i < count; ++i) { Guard guard; guard.path = read_string(in); read(in, guard.present); read(in, guard.sha); m.guards.push_back(std::move(guard)); }
    read(in, count); require(count <= 1, "Invalid launcher descriptor");
    if (count) { m.launcher = read_string(in); read(in, m.launcher_sha); }
    require(in.peek() == std::char_traits<char>::eof(), "Trailing manifest bytes"); validate(m); return m;
}
void write_manifest(const fs::path& path, const Manifest& m) {
    validate(m);
    auto temporary = path; temporary += L".tmp";
    { std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
      out.write("CDVFS2\0\0", 8); write(out, m.mode); write(out, m.pid); write(out, m.host_pid); write(out, m.executable);
      write_string(out, m.root.wstring()); write_string(out, m.generation); write_string(out, m.token); write_string(out, m.lane.wstring());
      write(out, static_cast<uint32_t>(m.files.size()));
      for (const auto& file : m.files) { write_string(out, file.logical); write_string(out, file.path.wstring()); write(out, file.sha); }
      write(out, static_cast<uint32_t>(m.guards.size()));
      for (const auto& guard : m.guards) { write_string(out, guard.path.wstring()); write(out, guard.present); write(out, guard.sha); }
      write(out, uint32_t(!m.launcher.empty()));
      if (!m.launcher.empty()) { write_string(out, m.launcher.wstring()); write(out, m.launcher_sha); }
      out.flush(); require(bool(out), "Cannot write session manifest"); }
    require(MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH), "Cannot publish session manifest");
}
void status(const Manifest& m, const char* state, DWORD error, const char* detail) {
    auto path = m.root / L".cdmw/virtual-loader" / (L"session-" + m.token + L".json");
    auto temp = path; temp += L".tmp";
    { std::ofstream out(temp); out << "{\"state\":\"" << state << "\",\"pid\":" << m.pid << ",\"host_pid\":" << m.host_pid << ",\"error\":" << error << ",\"detail\":\"";
      for (auto at = detail; *at; ++at) { if (*at == '\\' || *at == '\"') out << '\\'; if (static_cast<unsigned char>(*at) >= 32) out << *at; }
      out << "\"}"; out.flush(); }
    MoveFileExW(temp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}
}
