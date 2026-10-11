// A user-owned game session. CDMW starts this outside its helper lifetime job.
#include "protocol.hpp"
#include <sddl.h>
#include <iostream>
#include <fstream>
#include <tlhelp32.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>

using namespace cdmw::vfs;
namespace {
void verify_contents(const Manifest& manifest, std::vector<Handle>& pins) {
    struct Input { fs::path path; Hash sha; const char* error; bool retain; };
    std::vector<Input> inputs;
    const auto root = normalize(manifest.root) + L"\\";
    for (const auto& guard : manifest.guards) {
        if (!guard.present) { require(!fs::exists(guard.path), "An absent source appeared after review"); continue; }
        inputs.push_back({guard.path, guard.sha, "A game, package or ownership source changed after review",
                          manifest.mode != Mode::trace && normalize(guard.path).starts_with(root)});
    }
    for (const auto& file : manifest.files)
        inputs.push_back({file.path, file.sha, "Snapshot checksum mismatch", true});

    uint64_t total = 0;
    for (const auto& input : inputs) {
        // Pin the path before hashing, closing the old hash-then-pin replacement
        // gap. Save files outside the installation are released after their read.
        if (input.retain) {
            Handle pin(CreateFileW(input.path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
            require(bool(pin), "Cannot pin launch input");
            pins.push_back(std::move(pin));
        }
        total += fs::file_size(input.path);
    }
    std::atomic<size_t> next{0};
    std::atomic<uint64_t> bytes{0};
    std::atomic<int> active{2};
    std::atomic<bool> failed{false};
    std::mutex error_mutex;
    std::exception_ptr error;
    std::vector<std::jthread> workers;
    for (int i = 0; i < 2; ++i) workers.emplace_back([&] {
        try {
            while (!failed.load()) {
                const auto index = next.fetch_add(1);
                if (index >= inputs.size()) break;
                const auto& input = inputs[index];
                const auto actual = hash_file(input.path, [&](uint64_t count) {
                    require(!failed.load(), "Launch verification stopped");
                    bytes.fetch_add(count);
                });
                require(actual == input.sha, input.error);
            }
        } catch (...) {
            std::lock_guard lock(error_mutex);
            if (!error) error = std::current_exception();
            failed.store(true);
        }
        active.fetch_sub(1);
    });
    int previous = -1;
    while (active.load()) {
        const auto percent = static_cast<int>(90.0 * std::min(bytes.load(), total) / std::max<uint64_t>(1, total));
        if (percent != previous) {
            status(manifest, "starting", 0, "Verifying launch files...", percent);
            previous = percent;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    workers.clear(); // Join before releasing handles or propagating a refusal.
    if (error) std::rethrow_exception(error);
    for (const auto& guard : manifest.guards)
        if (!guard.present) require(!fs::exists(guard.path), "An absent source appeared after review");
    status(manifest, "starting", 0, "Verifying launch files...", 90);
}

struct Security {
    PSECURITY_DESCRIPTOR descriptor{};
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), nullptr, FALSE};
    Security() {
        HANDLE raw{}; require(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &raw), "Cannot identify session owner");
        Handle token(raw); DWORD needed{};
        GetTokenInformation(token.value, TokenUser, nullptr, 0, &needed);
        std::vector<unsigned char> data(needed);
        require(GetTokenInformation(token.value, TokenUser, data.data(), needed, &needed), "Cannot identify session owner");
        LPWSTR sid{}; require(ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(data.data())->User.Sid, &sid), "Cannot encode session owner");
        std::wstring sddl = L"D:P(A;;GA;;;" + std::wstring(sid) + L")"; LocalFree(sid);
        require(ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &descriptor, nullptr), "Cannot protect session pipe");
        attributes.lpSecurityDescriptor = descriptor;
    }
    ~Security() { if (descriptor) LocalFree(descriptor); }
};
struct PendingConnection {
    HANDLE pipe;
    OVERLAPPED operation{};
    bool pending{};
    ~PendingConnection() {
        if (!pending) return;
        CancelIoEx(pipe, &operation);
        DWORD ignored{}; GetOverlappedResult(pipe, &operation, &ignored, TRUE);
    }
};
void wait_io(HANDLE pipe, OVERLAPPED& operation, HANDLE process = nullptr) {
    HANDLE events[]{operation.hEvent, process};
    const auto wait = WaitForMultipleObjects(process ? 2 : 1, events, FALSE, 60000);
    if (wait != WAIT_OBJECT_0) {
        CancelIoEx(pipe, &operation);
        DWORD ignored{}; GetOverlappedResult(pipe, &operation, &ignored, TRUE);
        throw std::runtime_error("Runtime readiness failed; no verified Steam game acknowledged this session");
    }
    DWORD transferred{}; require(GetOverlappedResult(pipe, &operation, &transferred, FALSE), "Session pipe failed");
}
fs::path process_path(HANDLE process) {
    std::array<wchar_t, 32768> path{}; DWORD length = static_cast<DWORD>(path.size());
    require(QueryFullProcessImageNameW(process, 0, path.data(), &length), "Cannot identify game process");
    return fs::path(std::wstring(path.data(), length));
}
ULONGLONG created(HANDLE process) {
    FILETIME start{}, end{}, kernel{}, user{};
    require(GetProcessTimes(process, &start, &end, &kernel, &user), "Cannot identify process creation time");
    return (ULONGLONG(start.dwHighDateTime) << 32) | start.dwLowDateTime;
}
void require_game_closed(const Manifest& m) {
    Handle snapshot(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0));
    require(bool(snapshot), "Cannot inspect active game processes");
    PROCESSENTRY32W entry{}; entry.dwSize = sizeof entry;
    require(Process32FirstW(snapshot.value, &entry), "Cannot inspect active game processes");
    do {
        if (_wcsicmp(entry.szExeFile, executable(m).filename().c_str())) continue;
        Handle candidate(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, entry.th32ProcessID));
        if (!candidate) { require(GetLastError() == ERROR_INVALID_PARAMETER, "Cannot exclude an existing game process"); continue; }
        require(normalize(process_path(candidate.value)) != normalize(executable(m)), "Close the selected game before starting a virtual session");
    } while (Process32NextW(snapshot.value, &entry));
}
Handle steam_child(const Manifest& m, DWORD pid, ULONGLONG launched) {
    Handle game(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE | PROCESS_TERMINATE, FALSE, pid));
    require(bool(game) && WaitForSingleObject(game.value, 0) == WAIT_TIMEOUT, "Steam game exited before binding");
    require(normalize(process_path(game.value)) == normalize(executable(m)), "Steam started a different game installation");
    const auto born = created(game.value);
    require(born >= launched, "An existing game cannot claim a new session");
    Handle snapshot(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0));
    require(bool(snapshot), "Cannot verify Steam parent");
    PROCESSENTRY32W entry{}; entry.dwSize = sizeof entry;
    require(Process32FirstW(snapshot.value, &entry), "Cannot verify Steam parent");
    DWORD parent{};
    do { if (entry.th32ProcessID == pid) { parent = entry.th32ParentProcessID; break; } } while (Process32NextW(snapshot.value, &entry));
    Handle steam(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, parent));
    require(bool(steam) && WaitForSingleObject(steam.value, 0) == WAIT_TIMEOUT && created(steam.value) <= born, "Steam parent exited or its PID was reused");
    require(normalize(process_path(steam.value)) == normalize(m.launcher) && hash_file(m.launcher) == m.launcher_sha, "The game was not started by the reviewed Steam client");
    require(hash_file(executable(m)) == m.executable, "Steam game fingerprint changed");
    return game;
}
std::array<DWORD, 3> receive(HANDLE pipe, HANDLE event, HANDLE process = nullptr) {
    ResetEvent(event); OVERLAPPED read{}; read.hEvent = event;
    std::array<DWORD, 3> message{}; DWORD bytes{};
    if (!ReadFile(pipe, message.data(), sizeof message, &bytes, &read)) {
        require(GetLastError() == ERROR_IO_PENDING, "Runtime handshake read failed");
        wait_io(pipe, read, process);
        require(GetOverlappedResult(pipe, &read, &bytes, FALSE), "Runtime handshake read failed");
    }
    require(bytes == sizeof message, "Truncated runtime handshake"); return message;
}
}
int wmain(int argc, wchar_t** argv) {
    const bool controlled = argc == 3 && !wcscmp(argv[2], L"--controlled-probe");
    if (argc != 2 && !controlled) { std::cerr << "Usage: cdmw_virtual_session manifest.bin [--controlled-probe]\n"; return 2; }
    Manifest manifest;
    Handle process, lane;
    std::vector<Handle> pins;
    bool ready = false;
    bool held_lane = false;
    try {
        manifest = read_manifest(argv[1]);
        require(manifest.pid == 0 && manifest.host_pid == 0, "Session descriptor is already bound");
        require((manifest.mode == Mode::controlled_probe) == controlled, "Controlled loading requires a separately reviewed host opt-in");
        require(manifest.mode != Mode::redirect || game_redirection_approved, "Game launch blocked: startup timing, Steam handoff and save tests are not verified");
#ifdef CDMW_VIRTUAL_TESTING
        require(manifest.mode == Mode::harness || !manifest.launcher.empty(), "The reviewed Steam client is required");
#else
        require(!manifest.launcher.empty(), "The reviewed Steam client is required");
#endif
        require(hash_file(executable(manifest)) == manifest.executable, "Executable fingerprint changed");
#ifdef CDMW_VIRTUAL_TESTING
        if (manifest.mode != Mode::harness)
#endif
            require(hex(manifest.executable) == game_hash, "Unsupported executable build");
        lane.value = CreateFileW(manifest.lane.c_str(), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        require(bool(lane), "Installation lane unavailable");
        OVERLAPPED locking{};
        require(LockFileEx(lane.value, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &locking), "Installation already in use");
        held_lane = true;
        OVERLAPPED runtime_byte{}; runtime_byte.Offset = 1;
        require(LockFileEx(lane.value, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &runtime_byte), "An active game holds the runtime lease");
        require(UnlockFileEx(lane.value, 0, 1, 0, &runtime_byte), "Cannot transfer runtime lease");
        manifest.host_pid = GetCurrentProcessId();
        status(manifest, "starting", 0, "Verifying launch files...", 0);
        if (!manifest.launcher.empty()) {
            Handle pin(CreateFileW(manifest.launcher.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
            require(bool(pin) && hash_file(manifest.launcher) == manifest.launcher_sha, "The reviewed Steam client changed");
            pins.push_back(std::move(pin));
        }
        verify_contents(manifest, pins);
        Security security;
        require_game_closed(manifest);
        Handle pipe(CreateNamedPipeW(pipe_name(manifest).c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
                                     PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_REJECT_REMOTE_CLIENTS, 1, 64, 64, 0, &security.attributes));
        require(bool(pipe), "Cannot create session pipe");
        Handle event(CreateEventW(nullptr, TRUE, FALSE, nullptr));
        require(bool(event), "Cannot create readiness event");
        PendingConnection connection{pipe.value}; connection.operation.hEvent = event.value;
        BOOL connected = ConnectNamedPipe(pipe.value, &connection.operation);
        const auto connection_error = connected ? ERROR_SUCCESS : GetLastError();
        connection.pending = !connected && connection_error == ERROR_IO_PENDING;
        require(connected || connection_error == ERROR_IO_PENDING || connection_error == ERROR_PIPE_CONNECTED, "Cannot await runtime");
        STARTUPINFOW startup{}; startup.cb = sizeof startup;
        PROCESS_INFORMATION child{};
        ULONGLONG launched{};
#ifdef CDMW_VIRTUAL_TESTING
        if (manifest.launcher.empty()) {
            std::wstring command = L"\"" + executable(manifest).wstring() + L"\"";
            require(CreateProcessW(executable(manifest).c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_SUSPENDED,
                                   nullptr, (manifest.root / L"bin64").c_str(), &startup, &child), "Cannot start fixture executable");
            process.value = child.hProcess;
            Handle main_thread(child.hThread);
            manifest.pid = child.dwProcessId;
            write_manifest(manifest.root / L".cdmw/virtual-loader/session.bin", manifest);
            status(manifest, "starting", 0, "Waiting for runtime readiness...", 95);
            require(ResumeThread(main_thread.value) != DWORD(-1), "Cannot resume fixture process");
        } else
#endif
        {
            write_manifest(manifest.root / L".cdmw/virtual-loader/session.bin", manifest);
            status(manifest, "starting", 0, "Waiting for Steam to start the game...", 95);
            FILETIME now{}; GetSystemTimeAsFileTime(&now);
            launched = (ULONGLONG(now.dwHighDateTime) << 32) | now.dwLowDateTime;
            const wchar_t* arguments = L" -applaunch 3321460";
#ifdef CDMW_VIRTUAL_TESTING
            if (manifest.mode == Mode::harness) arguments = L" --steam-fixture";
#endif
            std::wstring command = L"\"" + manifest.launcher.wstring() + L"\"" + arguments;
            require(CreateProcessW(manifest.launcher.c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                                   nullptr, manifest.launcher.parent_path().c_str(), &startup, &child), "Cannot request the Steam game launch");
            Handle launcher(child.hProcess), thread(child.hThread);
            // Steam's command process may exit while the existing Steam client
            // starts the real game. Its lifetime is not the session lifetime.
        }
        if (connection.pending) wait_io(pipe.value, connection.operation, process ? process.value : nullptr);
        connection.pending = false;
        ULONG client{};
        require(GetNamedPipeClientProcessId(pipe.value, &client), "Cannot identify runtime process");
        if (!manifest.launcher.empty()) {
            const auto claim = receive(pipe.value, event.value);
            require(claim[0] == claim_magic && claim[1] == client && claim[2] == 0, "Invalid Steam runtime claim");
            auto verified = steam_child(manifest, client, launched);
            process.value = verified.value; verified.value = INVALID_HANDLE_VALUE;
            manifest.pid = client;
            write_manifest(manifest.root / L".cdmw/virtual-loader/session.bin", manifest);
            status(manifest, "starting", 0, "Waiting for runtime readiness...", 98);
            ResetEvent(event.value); OVERLAPPED grant{}; grant.hEvent = event.value;
            const std::array<DWORD, 3> message{grant_magic, manifest.pid, 0}; DWORD bytes{};
            if (!WriteFile(pipe.value, message.data(), sizeof message, &bytes, &grant)) {
                require(GetLastError() == ERROR_IO_PENDING, "Cannot grant Steam runtime claim");
                wait_io(pipe.value, grant, process.value);
                require(GetOverlappedResult(pipe.value, &grant, &bytes, FALSE), "Cannot grant Steam runtime claim");
            }
            require(bytes == sizeof message, "Incomplete Steam runtime grant");
        }
        require(client == manifest.pid, "Wrong runtime process");
        const auto message = receive(pipe.value, event.value, process.value);
        require(message[0] == ready_magic && message[1] == manifest.pid && message[2] == 0, "Runtime refused activation");
        ready = true; status(manifest, manifest.mode == Mode::trace ? "tracing" : "running", 0, "", 100);
        WaitForSingleObject(process.value, INFINITE);
        DWORD exit_code{}; GetExitCodeProcess(process.value, &exit_code);
        status(manifest, "stopped", exit_code);
        fs::remove(manifest.root / L".cdmw/virtual-loader/session.bin");
        return static_cast<int>(exit_code);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        // Only our fixture child or a new game verified against the exact Steam
        // parent, installation, fingerprint and launch time, before readiness.
        if (process && !ready) { TerminateProcess(process.value, ERROR_NOT_SUPPORTED); WaitForSingleObject(process.value, 5000); }
        if (!manifest.root.empty() && !manifest.token.empty()) {
            auto report = manifest.root / L".cdmw/virtual-loader" / (L"session-" + manifest.token + L".json");
            std::string existing;
            if (fs::is_regular_file(report) && fs::file_size(report) < 4096) {
                std::ifstream in(report); existing.assign(std::istreambuf_iterator<char>(in), {});
            }
            if ((held_lane || !fs::exists(report)) && existing.find("\"state\":\"blocked\"") == std::string::npos)
                status(manifest, "blocked", ERROR_NOT_SUPPORTED, error.what());
            auto slot = manifest.root / L".cdmw/virtual-loader/session.bin";
            if (fs::is_regular_file(slot)) {
                try {
                    const auto owner = read_manifest(slot);
                    if (owner.token == manifest.token && owner.host_pid == GetCurrentProcessId()) fs::remove(slot);
                } catch (...) {}
            }
        }
        return 1;
    }
}
