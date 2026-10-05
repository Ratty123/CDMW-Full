// A user-owned game session. CDMW starts this outside its helper lifetime job.
#include "protocol.hpp"
#include <sddl.h>
#include <iostream>
#include <fstream>

using namespace cdmw::vfs;
namespace {
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
void wait_io(HANDLE pipe, OVERLAPPED& operation, HANDLE process) {
    HANDLE events[]{operation.hEvent, process};
    const auto wait = WaitForMultipleObjects(2, events, FALSE, 20000);
    if (wait != WAIT_OBJECT_0) { CancelIoEx(pipe, &operation); throw std::runtime_error("Runtime readiness failed or Steam handed off to an unverified process"); }
    DWORD transferred{}; require(GetOverlappedResult(pipe, &operation, &transferred, FALSE), "Session pipe failed");
}
}
int wmain(int argc, wchar_t** argv) {
    if (argc != 2) { std::cerr << "Usage: cdmw_virtual_session manifest.bin\n"; return 2; }
    Manifest manifest;
    Handle process;
    bool ready = false;
    try {
        manifest = read_manifest(argv[1]);
        require(manifest.pid == 0 && manifest.host_pid == 0, "Session descriptor is already bound");
        require(manifest.mode != Mode::redirect || game_redirection_approved, "Game launch blocked: startup timing, Steam handoff and save tests are not verified");
        require(hash_file(executable(manifest)) == manifest.executable, "Executable fingerprint changed");
        if (manifest.mode != Mode::harness) require(hex(manifest.executable) == game_hash, "Unsupported executable build");
        Handle lane(CreateFileW(manifest.lane.c_str(), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr));
        require(bool(lane), "Installation lane unavailable");
        OVERLAPPED locking{};
        require(LockFileEx(lane.value, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &locking), "Installation already in use");
        OVERLAPPED runtime_byte{}; runtime_byte.Offset = 1;
        require(LockFileEx(lane.value, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &runtime_byte), "An active game holds the runtime lease");
        require(UnlockFileEx(lane.value, 0, 1, 0, &runtime_byte), "Cannot transfer runtime lease");
        std::vector<Handle> pins;
        for (const auto& guard : manifest.guards) {
            if (!guard.present) { require(!fs::exists(guard.path), "An absent source appeared after review"); continue; }
            require(hash_file(guard.path) == guard.sha, "A game, package or ownership source changed after review");
            // Trace mode only observes the unmodified game. Redirected sessions
            // pin game inputs against replacement after the last validation.
            if (manifest.mode != Mode::trace && normalize(guard.path).starts_with(normalize(manifest.root) + L"\\")) {
                Handle pin(CreateFileW(guard.path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
                require(bool(pin), "Cannot pin game source"); pins.push_back(std::move(pin));
            }
        }
        for (const auto& file : manifest.files) {
            require(hash_file(file.path) == file.sha, "Snapshot checksum mismatch");
            Handle pin(CreateFileW(file.path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
            require(bool(pin), "Snapshot cannot be pinned"); pins.push_back(std::move(pin));
        }
        Security security;
        Handle pipe(CreateNamedPipeW(pipe_name(manifest).c_str(), PIPE_ACCESS_INBOUND | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
                                     PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_REJECT_REMOTE_CLIENTS, 1, 64, 64, 0, &security.attributes));
        require(bool(pipe), "Cannot create session pipe");
        Handle event(CreateEventW(nullptr, TRUE, FALSE, nullptr));
        require(bool(event), "Cannot create readiness event");
        OVERLAPPED connection{}; connection.hEvent = event.value;
        BOOL connected = ConnectNamedPipe(pipe.value, &connection);
        require(connected || GetLastError() == ERROR_IO_PENDING || GetLastError() == ERROR_PIPE_CONNECTED, "Cannot await runtime");
        STARTUPINFOW startup{}; startup.cb = sizeof startup;
        PROCESS_INFORMATION child{};
        std::wstring command = L"\"" + executable(manifest).wstring() + L"\"";
        require(CreateProcessW(executable(manifest).c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_SUSPENDED,
                               nullptr, (manifest.root / L"bin64").c_str(), &startup, &child), "Cannot start the selected executable");
        process.value = child.hProcess;
        Handle main_thread(child.hThread);
        manifest.pid = child.dwProcessId; manifest.host_pid = GetCurrentProcessId();
        write_manifest(manifest.root / L".cdmw/virtual-loader/session.bin", manifest);
        status(manifest, "starting");
        require(ResumeThread(main_thread.value) != DWORD(-1), "Cannot resume selected game process");
        wait_io(pipe.value, connection, process.value);
        ULONG client{};
        require(GetNamedPipeClientProcessId(pipe.value, &client) && client == manifest.pid, "Wrong runtime process");
        ResetEvent(event.value);
        OVERLAPPED read{}; read.hEvent = event.value;
        std::array<DWORD, 3> message{}; DWORD bytes{};
        BOOL complete = ReadFile(pipe.value, message.data(), sizeof message, &bytes, &read);
        if (!complete) { require(GetLastError() == ERROR_IO_PENDING, "Runtime readiness read failed"); wait_io(pipe.value, read, process.value); require(GetOverlappedResult(pipe.value, &read, &bytes, FALSE), "Runtime readiness read failed"); }
        require(bytes == sizeof message && message[0] == 0x31534656 && message[1] == manifest.pid && message[2] == 0, "Runtime refused activation");
        ready = true; status(manifest, manifest.mode == Mode::trace ? "tracing" : "running");
        WaitForSingleObject(process.value, INFINITE);
        DWORD exit_code{}; GetExitCodeProcess(process.value, &exit_code);
        status(manifest, "stopped", exit_code);
        fs::remove(manifest.root / L".cdmw/virtual-loader/session.bin");
        return static_cast<int>(exit_code);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        // Only the process we created, and only before readiness. Never kill
        // Steam, an existing game, or a successful session on UI/host shutdown.
        if (process && !ready) { TerminateProcess(process.value, ERROR_NOT_SUPPORTED); WaitForSingleObject(process.value, 5000); }
        if (!manifest.root.empty() && !manifest.token.empty()) {
            auto report = manifest.root / L".cdmw/virtual-loader" / (L"session-" + manifest.token + L".json");
            std::string existing;
            if (fs::is_regular_file(report) && fs::file_size(report) < 4096) {
                std::ifstream in(report); existing.assign(std::istreambuf_iterator<char>(in), {});
            }
            if (existing.find("\"state\":\"blocked\"") == std::string::npos) status(manifest, "blocked", ERROR_NOT_SUPPORTED, error.what());
            auto slot = manifest.root / L".cdmw/virtual-loader/session.bin";
            if (fs::is_regular_file(slot)) {
                try { if (read_manifest(slot).token == manifest.token) fs::remove(slot); } catch (...) {}
            }
        }
        return 1;
    }
}
