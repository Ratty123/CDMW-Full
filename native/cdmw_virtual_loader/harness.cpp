// Synthetic game-shaped child. It is never used as real-game compatibility proof.
#include "protocol.hpp"
#include "bootstrap.hpp"
#include <cstddef>
#include <fstream>
#include <atomic>
#include <cstring>
#include <iostream>
#include <thread>

using namespace cdmw::vfs;
// Stand-ins for the game's resource loader classes, with the RTTI names and vtable
// slots the runtime serves through. Requests carry their path at **request and the
// worker that started them at +0x20, as the game's do.
namespace pa {
using Word = uint64_t;
struct Text { const char* text; };
struct Request { Text* path; unsigned char spare[0x18]; void* owner; Word handled; char loaded[256]; Word loaded_size; };
static_assert(offsetof(Request, owner) == 0x20);
class BasePackageResourceMap {
public:
    virtual Word m0() { return 0; } virtual Word m1() { return 0; } virtual Word m2() { return 0; } virtual Word m3() { return 0; }
    virtual Word m4() { return 0; } virtual Word m5() { return 0; } virtual Word m6() { return 0; } virtual Word m7() { return 0; }
    virtual Word m8() { return 0; } virtual Word m9() { return 0; } virtual Word m10() { return 0; }
};
// Reads the file a served path resolves to, through the stand-in's resource map.
class BaseResourceLoadWorker {
public:
    virtual Word v0() { return 0; }
    virtual Word v1() { return 0; }
    virtual Word load(void*, Request* request, Word) { return serve(request, 102); }
    virtual Word r3(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 103; return 1; }
    virtual Word r4(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 104; return 1; }
    virtual Word r5(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 105; return 1; }
    virtual Word r6(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 106; return 1; }
    virtual Word v7() { return 0; } virtual Word v8() { return 0; } virtual Word v9() { return 0; }
    virtual Word v10() { return 0; } virtual Word v11() { return 0; }
    virtual Word r12(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 112; return 1; }
    virtual Word load_async(void*, Request* request, Word) { return serve(request, 113); }
private:
    Word serve(Request* request, Word handled) {
        auto self = reinterpret_cast<unsigned char*>(this);
        if (*reinterpret_cast<uint32_t*>(self + 0x10) != 0x10000000u || self[0x14] != 1 || self[0x16] != 1) return 0;
        auto map = *reinterpret_cast<void**>(self + 0x18);
        auto slots = *reinterpret_cast<void***>(map);
        uint64_t size{};
        void* record{};
        if (!reinterpret_cast<Word (*)(void*, void*)>(slots[4])(map, request) ||
            !reinterpret_cast<Word (*)(void*, void*, uint64_t*)>(slots[5])(map, request, &size) ||
            !reinterpret_cast<Word (*)(void*, void*, void**)>(slots[7])(map, request, &record)) return 0;
        auto bytes = static_cast<unsigned char*>(record);
        auto text = *reinterpret_cast<const char**>(record);
        if (*reinterpret_cast<uint32_t*>(bytes + 8) != strlen(text) || *reinterpret_cast<uint32_t*>(bytes + 12) != 0xffffffffu ||
            *reinterpret_cast<uint32_t*>(bytes + 16) != 0x80000000u) return 0;
        std::array<wchar_t, 1024> wide{};
        if (!MultiByteToWideChar(CP_UTF8, 0, text, -1, wide.data(), static_cast<int>(wide.size()))) return 0;
        Handle file(CreateFileW(wide.data(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr));
        DWORD count{};
        if (!file || !ReadFile(file.value, request->loaded, sizeof request->loaded, &count, nullptr) || count != size) return 0;
        request->loaded_size = count;
        request->owner = this;
        request->handled = handled;
        return 1;
    }
};
class ResourceLoadWorker_Package {
public:
    virtual Word v0() { return 0; }
    virtual Word v1() { return 0; }
    virtual Word load(void*, Request* request, Word) { request->handled = 2; return 1; }
    virtual Word r3(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 3; return 1; }
    virtual Word r4(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 4; return 1; }
    virtual Word r5(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 5; return 1; }
    virtual Word r6(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 6; return 1; }
    virtual Word v7() { return 0; } virtual Word v8() { return 0; } virtual Word v9() { return 0; }
    virtual Word exists(void*) { return 0; }
    virtual Word size(void*, uint64_t*) { return 0; }
    virtual Word r12(Request* request, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word) { request->handled = 12; return 1; }
    virtual Word load_async(void*, Request* request, Word) { request->handled = 13; return 1; }
};
BasePackageResourceMap map_instance;
BaseResourceLoadWorker loose_instance;
ResourceLoadWorker_Package package_instance;
}  // namespace pa
// Calls each patched package-worker slot as the game would and checks who answered.
void serve_through_package_worker(const fs::path& root, const std::string& served, const std::string& unknown) {
    using pa::Word;
    pa::Text served_text{served.c_str()}, unknown_text{unknown.c_str()};
    auto slots = *reinterpret_cast<void***>(&pa::package_instance);
    auto exists = reinterpret_cast<Word (*)(void*, void*)>(slots[10]);
    auto size = reinterpret_cast<Word (*)(void*, void*, uint64_t*)>(slots[11]);
    auto load = reinterpret_cast<Word (*)(void*, void*, void*, Word)>(slots[2]);
    auto load_async = reinterpret_cast<Word (*)(void*, void*, void*, Word)>(slots[13]);
    using Follow = Word (*)(void*, void*, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word);
    auto worker = &pa::package_instance;
    pa::Request request{}, other{}, later{};
    request.path = &served_text; other.path = &unknown_text; later.path = &served_text;
    uint64_t bytes{};
    require(exists(worker, &request) == 1 && exists(worker, &other) == 0, "Served path existence was not answered");
    require(size(worker, &request, &bytes) == 1 && size(worker, &other, &bytes) == 0, "Served path size was not answered");
    require(load(worker, nullptr, &request, 0) == 1 && request.handled == 102 && request.owner && request.owner != worker,
            "A served load did not run in the loose-file worker");
    require(request.loaded_size == bytes, "The served size and the loaded bytes disagree");
    require(load(worker, nullptr, &other, 0) == 1 && other.handled == 2, "An unserved load left the package worker");
    for (int slot : {3, 4, 5, 6, 12}) {
        auto follow = reinterpret_cast<Follow>(slots[slot]);
        require(follow(worker, &request, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0) == 1 && request.handled == 100u + static_cast<unsigned>(slot),
                "A served request's later step did not follow the loose-file worker");
        require(follow(worker, &other, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0) == 1 && other.handled == static_cast<unsigned>(slot),
                "An unserved request's later step left the package worker");
    }
    require(load_async(worker, nullptr, &later, 0) == 1 && later.handled == 113, "A served async load did not run in the loose-file worker");
    const auto out = root / L".cdmw/virtual-loader/harness-out";
    fs::create_directories(out);
    std::ofstream copy(out / L"served.bin", std::ios::binary);
    copy.write(request.loaded, static_cast<std::streamsize>(request.loaded_size));
    require(static_cast<bool>(copy), "Cannot keep the served copy");
}
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
                reinterpret_cast<void*>(bootstrap + 0x1f848), reinterpret_cast<void*>(game + game_startup_return), nullptr};
            require(matches_startup_frames(frames, bootstrap, game), "Observed startup path refused");
            require(!matches_startup_frames(std::span<void* const>(frames.data(), 5), bootstrap, game), "Truncated startup path accepted");
            require(!matches_startup_frames(frames, bootstrap + 1, game), "Wrong startup module accepted");
            std::swap(frames[2], frames[3]);
            require(!matches_startup_frames(frames, bootstrap, game), "Reordered startup path accepted");
            std::swap(frames[2], frames[3]); frames[5] = reinterpret_cast<void*>(game + game_startup_return + 1);
            require(!matches_startup_frames(frames, bootstrap, game), "Unknown game startup caller accepted");
            std::array<void*, 5> current_frames{
                reinterpret_cast<void*>(bootstrap + 0x218a1), reinterpret_cast<void*>(bootstrap + 0x30df8),
                reinterpret_cast<void*>(bootstrap + 0x333b3), reinterpret_cast<void*>(bootstrap + 0x1f918),
                reinterpret_cast<void*>(game + game_startup_return)};
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
        if (argc == 4 && !wcscmp(argv[1], L"--serve")) {
            auto narrow = [](const wchar_t* text) { std::string result; for (; *text; ++text) result += static_cast<char>(*text); return result; };
            serve_through_package_worker(root, narrow(argv[2]), narrow(argv[3]));
            Sleep(250);  // the trace writer flushes every 20 ms
            return 0;
        }
        if (argc >= 3 && !wcscmp(argv[1], L"--copy-out")) {
            // Read each logical game file as the game would, through the hooks, and keep
            // a copy (slashes become underscores) for the test to compare.
            const auto out = root / L".cdmw/virtual-loader/harness-out";
            fs::create_directories(out);
            for (int i = 2; i < argc; ++i) {
                Handle file(CreateFileW((root / argv[i]).c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr));
                require(bool(file), "Mapped open failed");
                LARGE_INTEGER size{};
                require(GetFileSizeEx(file.value, &size) && size.QuadPart < (1ll << 31), "Mapped size failed");
                std::vector<char> data(static_cast<size_t>(size.QuadPart));
                DWORD count{};
                require(data.empty() || (ReadFile(file.value, data.data(), static_cast<DWORD>(data.size()), &count, nullptr) && count == data.size()), "Mapped read failed");
                std::wstring name = argv[i];
                for (auto& c : name) if (c == L'/' || c == L'\\') c = L'_';
                std::ofstream copy(out / name, std::ios::binary);
                copy.write(data.data(), static_cast<std::streamsize>(data.size()));
                require(static_cast<bool>(copy), "Cannot keep a mapped copy");
            }
            return 0;
        }
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
                    reinterpret_cast<void*>(reinterpret_cast<uintptr_t>(game) + game_startup_return)} :
                std::array<void*, 5>{base + 0x21785, base + 0x308e8, base + 0x32e13, base + 0x1f848,
                    reinterpret_cast<void*>(reinterpret_cast<uintptr_t>(game) + game_startup_return)};
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
