// Synthetic game-shaped child. It is never used as real-game compatibility proof.
#include "protocol.hpp"
#include "bootstrap.hpp"
#include <fstream>
#include <atomic>
#include <cstring>
#include <iostream>
#include <thread>

using namespace cdmw::vfs;
extern "C" decltype(&CreateFile2) __imp_CreateFile2;
extern "C" decltype(&GetModuleHandleW) __imp_GetModuleHandleW;
extern "C" decltype(&GetProcAddress) __imp_GetProcAddress;
HANDLE WINAPI foreign_open(LPCWSTR, DWORD, DWORD, DWORD, LPCREATEFILE2_EXTENDED_PARAMETERS) { return INVALID_HANDLE_VALUE; }
int wmain(int argc, wchar_t** argv) {
    try {
        if (argc == 2 && !wcscmp(argv[1], L"--self-test")) {
            bool rejected = false;
            try { validate(Manifest{}); } catch (...) { rejected = true; }
            require(rejected, "Empty manifest accepted");
            require(hex(hash_file(own_executable())).size() == 64, "Hash contract failed");
            require(first_live_thread(), "Initial fixture thread was not recognized");
            bool worker_accepted = true;
            std::thread worker([&] { worker_accepted = first_live_thread(); }); worker.join();
            require(!worker_accepted, "A late worker passed the startup thread guard");
            constexpr uintptr_t bootstrap = 0x180000000, game = 0x140000000;
            std::array<void*, 7> frames{nullptr, reinterpret_cast<void*>(bootstrap + 0x21785),
                reinterpret_cast<void*>(bootstrap + 0x308e8), reinterpret_cast<void*>(bootstrap + 0x32e13),
                reinterpret_cast<void*>(bootstrap + 0x1f848), reinterpret_cast<void*>(game + 0x10958a48), nullptr};
            require(matches_startup_frames(frames, bootstrap, game), "Observed startup path refused");
            require(!matches_startup_frames(std::span<void* const>(frames.data(), 5), bootstrap, game), "Truncated startup path accepted");
            require(!matches_startup_frames(frames, bootstrap + 1, game), "Wrong startup module accepted");
            std::swap(frames[2], frames[3]);
            require(!matches_startup_frames(frames, bootstrap, game), "Reordered startup path accepted");
            std::swap(frames[2], frames[3]); frames[5] = reinterpret_cast<void*>(game + 0x10958a49);
            require(!matches_startup_frames(frames, bootstrap, game), "Unknown game startup caller accepted");
            std::array<void*, 5> current_frames{
                reinterpret_cast<void*>(bootstrap + 0x218a1), reinterpret_cast<void*>(bootstrap + 0x30df8),
                reinterpret_cast<void*>(bootstrap + 0x333b3), reinterpret_cast<void*>(bootstrap + 0x1f918),
                reinterpret_cast<void*>(game + 0x10958a48)};
            require(matches_startup_frames(current_frames, bootstrap, game, true), "Current bootstrap startup path refused");
            require(!matches_startup_frames(current_frames, bootstrap, game), "Current frames accepted for legacy bootstrap");
            require(!matches_startup_frames(std::span<void* const>(current_frames.data(), 4), bootstrap, game, true), "Truncated current startup path accepted");
            for (size_t i = 0; i < current_frames.size(); ++i) {
                auto changed = current_frames;
                changed[i] = reinterpret_cast<void*>(reinterpret_cast<uintptr_t>(changed[i]) + 1);
                require(!matches_startup_frames(changed, bootstrap, game, true), "Changed current startup return address accepted");
            }
            std::cout << "protocol self-test passed\n"; return 0;
        }
        auto root = own_executable().parent_path().parent_path();
        if (argc == 2 && (!wcscmp(argv[1], L"--steam-fixture") || !wcscmp(argv[1], L"--steam-intermediary"))) {
            auto exe = root / L"bin64/cdmw_virtual_loader_harness.exe";
            std::wstring command = L"\"" + exe.wstring() + L"\"";
            if (!wcscmp(argv[1], L"--steam-fixture") && fs::exists(root / L".cdmw/virtual-loader/harness-wrong-parent.flag")) {
                exe = root / L"bin64/cdmw_virtual_steam_bridge.exe";
                command = L"\"" + exe.wstring() + L"\" --steam-intermediary";
            }
            STARTUPINFOW startup{}; startup.cb = sizeof startup; PROCESS_INFORMATION child{};
            require(CreateProcessW(exe.c_str(), command.data(), nullptr, nullptr, FALSE, 0, nullptr,
                                   (root / L"bin64").c_str(), &startup, &child), "Fixture Steam launch failed");
            Handle process(child.hProcess), thread(child.hThread);
            WaitForSingleObject(process.value, INFINITE);
            DWORD result{}; GetExitCodeProcess(process.value, &result); return static_cast<int>(result);
        }
        if (fs::exists(root / L".cdmw/virtual-loader/harness-bootstrap.flag")) {
            require(LoadLibraryW((root / L"bin64/winmm.dll").c_str()) != nullptr, "Cannot load fixture bootstrap");
            // Exercise the bootstrap's deferred plugin-loading callback through
            // a real main-image import before manually requesting the ASI.
            WIN32_FILE_ATTRIBUTE_DATA info{};
            GetFileAttributesExW((root / L"meta/0.papgt").c_str(), GetFileExInfoStandard, &info);
        }
        auto dll = root / L"bin64/CDMWVirtualLoader.asi";
        auto module = LoadLibraryW(dll.c_str()); require(module, "Cannot load runtime");
        auto initialize = reinterpret_cast<void(*)()>(GetProcAddress(module, "InitializeASI"));
        auto state = reinterpret_cast<DWORD(*)()>(GetProcAddress(module, "CdmwVirtualState"));
        if (fs::exists(root / L".cdmw/virtual-loader/harness-conflict.flag")) {
            DWORD previous{};
            require(VirtualProtect(&__imp_CreateFile2, sizeof(void*), PAGE_READWRITE, &previous), "Cannot create fixture hook");
            __imp_CreateFile2 = &foreign_open;
            DWORD ignored{}; VirtualProtect(&__imp_CreateFile2, sizeof(void*), previous, &ignored);
        }
        require(initialize && state, "Runtime exports missing"); initialize();
        if (argc == 2 && !wcscmp(argv[1], L"--inert")) { require(state() == 0, "Ordinary launch activated runtime"); return 0; }
        if (argc == 2 && !wcscmp(argv[1], L"--blocked")) { require(state() == 2, "Test activation was not refused"); return 0; }
        require(state() == 1, "Runtime did not become ready");
        if (fs::exists(root / L".cdmw/virtual-loader/harness-bootstrap.flag")) {
            auto base = reinterpret_cast<unsigned char*>(GetModuleHandleW(L"winmm.dll"));
            const auto kernel = GetModuleHandleW(L"kernel32.dll");
            auto expected = reinterpret_cast<void*>(GetProcAddress(kernel, "CreateFileA"));
            // The production verifier lives in the newly loaded ASI, whose
            // imports UAL never patched. Give this fixture-linked verifier the
            // same lookup imports, so testing a false handoff flag does not
            // itself invoke UAL and turn that flag back on.
            const auto module_lookup = reinterpret_cast<decltype(&GetModuleHandleW)>(GetProcAddress(kernel, "GetModuleHandleW"));
            const auto procedure_lookup = reinterpret_cast<decltype(&GetProcAddress)>(GetProcAddress(kernel, "GetProcAddress"));
            DWORD lookup_protect{}, lookup_ignored{};
            require(VirtualProtect(&__imp_GetModuleHandleW, sizeof(void*), PAGE_READWRITE, &lookup_protect), "Cannot isolate fixture lookup");
            __imp_GetModuleHandleW = module_lookup;
            VirtualProtect(&__imp_GetModuleHandleW, sizeof(void*), lookup_protect, &lookup_ignored);
            require(VirtualProtect(&__imp_GetProcAddress, sizeof(void*), PAGE_READWRITE, &lookup_protect), "Cannot isolate fixture lookup");
            __imp_GetProcAddress = procedure_lookup;
            VirtualProtect(&__imp_GetProcAddress, sizeof(void*), lookup_protect, &lookup_ignored);
            const bool current_layout = hex(hash_file(root / L"bin64/winmm.dll")) == "fa266e3513d02c08a1b808f28c10538a489eaffaa4b0707f7cc1066e71b5afd7";
            const auto open = current_layout ? 0x1f330 : 0x1f260;
            const auto flags = current_layout ? 0xb4bd4 : 0xb2b24;
            const auto open_import = current_layout ? 0x840f8 : 0x820f8;
            const auto command = current_layout ? 0x1f8f0 : 0x1f820;
            const auto command_import = current_layout ? 0x840e0 : 0x820e0;
            require(VerifiedBootstrap(root).accepts("CreateFileA", base + open, expected), "Known bootstrap refused");
            require(!VerifiedBootstrap(root).accepts("CreateFileA", base + open + 1, expected), "Wrong bootstrap entry accepted");
            auto game = GetModuleHandleW(nullptr);
            const auto startup_frames = current_layout ?
                std::array<void*, 5>{base + 0x218a1, base + 0x30df8, base + 0x333b3, base + 0x1f918,
                    reinterpret_cast<void*>(reinterpret_cast<uintptr_t>(game) + 0x10958a48)} :
                std::array<void*, 5>{base + 0x21785, base + 0x308e8, base + 0x32e13, base + 0x1f848,
                    reinterpret_cast<void*>(reinterpret_cast<uintptr_t>(game) + 0x10958a48)};
            // Synthetic addresses exercise witnesses, not real game timing.
            require(VerifiedBootstrap(root).accepts_startup(startup_frames, game), "Known startup witnesses refused");
            std::array<void*, 32> actual{};
            auto count = CaptureStackBackTrace(0, static_cast<DWORD>(actual.size()), actual.data(), nullptr);
            require(!VerifiedBootstrap(root).accepts_startup(std::span<void* const>(actual.data(), count), game), "Late fixture call accepted as early startup");
            const auto reject_mutation = [&](unsigned char* at, size_t size, const char* failure, bool startup = false) {
                std::array<unsigned char, 8> saved{};
                require(size <= saved.size(), "Oversized witness test");
                memcpy(saved.data(), at, size);
                DWORD protect{};
                require(VirtualProtect(at, size, PAGE_EXECUTE_READWRITE, &protect), "Cannot stage witness test");
                memset(at, 0, size);
                const bool accepted = startup ? VerifiedBootstrap(root).accepts_startup(startup_frames, game) :
                    VerifiedBootstrap(root).accepts("CreateFileA", base + open, expected);
                memcpy(at, saved.data(), size);
                DWORD ignored{}; require(VirtualProtect(at, size, protect, &ignored), "Cannot restore witness test");
                FlushInstructionCache(GetCurrentProcess(), at, size);
                require(!accepted, failure);
            };
            reject_mutation(base + open, 1, "Changed forwarding instructions accepted");
            reject_mutation(base + flags + 4, 4, "Unfinished restore phase accepted");
            reject_mutation(base + flags, 4, "Unstarted plugin phase accepted");
            reject_mutation(base + open_import, sizeof(void*), "Changed forwarding destination accepted");
            reject_mutation(base + command, 1, "Changed startup instructions accepted", true);
            reject_mutation(base + command_import, sizeof(void*), "Changed startup forwarding destination accepted", true);
            reject_mutation(base + flags + 4, 4, "Unfinished startup restore phase accepted", true);
            std::ofstream verified(root / L".cdmw/virtual-loader/harness-bootstrap-result.txt");
            verified << "bootstrap and startup witnesses passed";
            verified.close();
            require(static_cast<bool>(verified), "Cannot write bootstrap witness result");
        }
        auto path = root / L"meta/0.papgt";
        auto check_read = [&](bool modern, bool overlapped) {
            Handle file(modern ? CreateFile2(path.c_str(), GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, nullptr) :
                                CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, overlapped ? FILE_FLAG_OVERLAPPED : 0, nullptr));
            require(bool(file), "Mapped open failed");
            char data[7]{}; DWORD count{};
            OVERLAPPED operation{}; Handle event(CreateEventW(nullptr, TRUE, FALSE, nullptr)); operation.hEvent = event.value;
            auto read = ReadFile(file.value, data, 7, &count, overlapped ? &operation : nullptr);
            if (!read && overlapped && GetLastError() == ERROR_IO_PENDING) require(GetOverlappedResult(file.value, &operation, &count, TRUE), "Async read failed");
            else require(read, "Mapped read failed");
            require(count == 7 && !memcmp(data, "virtual", 7), "Wrong file contents");
            if (!overlapped) {
                require(SetFilePointer(file.value, 0, nullptr, FILE_BEGIN) == 0, "Seek failed");
                Handle mapping(CreateFileMappingW(file.value, nullptr, PAGE_READONLY, 0, 0, nullptr));
                require(bool(mapping), "Mapping failed");
                auto view = MapViewOfFile(mapping.value, FILE_MAP_READ, 0, 0, 0);
                require(view && !memcmp(view, "virtual", 7), "Mapped view mismatch"); UnmapViewOfFile(view);
            }
        };
        check_read(false, false); check_read(true, false); check_read(false, true);
        auto canonical = path;
        path = L"../meta/0.PAPGT"; check_read(false, false);
        path = L"\\\\?\\" + canonical.wstring(); check_read(true, false);
        path = canonical;
        Handle ansi(CreateFileA("../meta/0.papgt", GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr));
        require(bool(ansi) && GetFileSize(ansi.value, nullptr) == 7, "ANSI alias failed");
        require(GetFileAttributesA("../meta/0.papgt") != INVALID_FILE_ATTRIBUTES, "ANSI query failed");
        require(GetFileAttributesW((root / L"0042").c_str()) & FILE_ATTRIBUTE_DIRECTORY, "Virtual folder query failed");
        WIN32_FIND_DATAW found{};
        auto search = FindFirstFileW(path.c_str(), &found);
        require(search != INVALID_HANDLE_VALUE && found.nFileSizeLow == 7 && !wcscmp(found.cFileName, L"0.papgt"), "Exact metadata query mismatch"); FindClose(search);
        search = FindFirstFileExW(path.c_str(), FindExInfoBasic, &found, FindExSearchNameMatch, nullptr, 0);
        require(search != INVALID_HANDLE_VALUE && found.nFileSizeLow == 7, "Extended metadata query mismatch"); FindClose(search);
        search = FindFirstFileW((root / L"0042/*.pamt").c_str(), &found);
        require(search != INVALID_HANDLE_VALUE && !wcscmp(found.cFileName, L"0.pamt"), "Virtual enumeration failed"); FindClose(search);
        search = FindFirstFileExW((root / L"0042/*.paz").c_str(), FindExInfoBasic, &found, FindExSearchNameMatch, nullptr, 0);
        require(search != INVALID_HANDLE_VALUE && !wcscmp(found.cFileName, L"0.paz"), "Extended enumeration failed"); FindClose(search);
        std::array<std::thread, 4> readers;
        std::atomic<bool> success{true};
        for (auto& reader : readers) reader = std::thread([&] { try { for (int i = 0; i < 20; ++i) check_read(true, false); } catch (...) { success = false; } });
        for (auto& reader : readers) reader.join(); require(success, "Concurrent read failed");
        WIN32_FILE_ATTRIBUTE_DATA attributes{};
        require(GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &attributes) && attributes.nFileSizeLow == 7, "Attribute mismatch");
        Handle denied(CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr));
        require(!denied && GetLastError() == ERROR_ACCESS_DENIED, "Write was not refused");
        Handle missing(CreateFileW((root / L"missing.txt").c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr));
        require(!missing && GetLastError() == ERROR_FILE_NOT_FOUND, "Unmapped error changed");
        std::ofstream out(root / L".cdmw/virtual-loader/harness-result.txt"); out << "native IO passed"; out.close();
        while (fs::exists(root / L".cdmw/virtual-loader/harness-wait.flag")) Sleep(20);
        Sleep(100); return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
