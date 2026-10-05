// Synthetic game-shaped child. It is never used as real-game compatibility proof.
#include "protocol.hpp"
#include <fstream>
#include <atomic>
#include <cstring>
#include <iostream>
#include <thread>
#include <atomic>

using namespace cdmw::vfs;
extern "C" decltype(&CreateFile2) __imp_CreateFile2;
HANDLE WINAPI foreign_open(LPCWSTR, DWORD, DWORD, DWORD, LPCREATEFILE2_EXTENDED_PARAMETERS) { return INVALID_HANDLE_VALUE; }
int wmain(int argc, wchar_t** argv) {
    try {
        if (argc == 2 && !wcscmp(argv[1], L"--self-test")) {
            bool rejected = false;
            try { validate(Manifest{}); } catch (...) { rejected = true; }
            require(rejected, "Empty manifest accepted");
            require(hex(hash_file(own_executable())).size() == 64, "Hash contract failed");
            std::cout << "protocol self-test passed\n"; return 0;
        }
        auto root = own_executable().parent_path().parent_path();
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
        require(state() == 1, "Runtime did not become ready");
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
