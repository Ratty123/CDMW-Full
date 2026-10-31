// Per-path serving inside the game's package resource loader. Layouts follow DmmRuntime
// 1.0.0 on game 1.0.0.3446, read from its code; nothing here is a published game contract.
#include "resource_serving.hpp"
#include "protocol.hpp"
#include <algorithm>
#include <array>
#include <cstring>
#include <sstream>
#include <stdexcept>

namespace cdmw::vfs {
namespace {
using Word = uint64_t;
// The package worker's slots this answers for, and the ones that act on a load in
// progress, which follow the worker the request names at +0x20.
constexpr int load_slot = 2, exists_slot = 10, size_slot = 11, async_slot = 13;
constexpr std::array<int, 5> request_slots{3, 4, 5, 6, 12};
constexpr int worker_slots = 14, map_slots = 11;
constexpr size_t owner_offset = 0x20;

struct Entry { uint64_t hash; std::string logical; void* record; uint64_t size; };
std::vector<Entry> entries;  // sorted by hash; read-only while serving
ServeTrace on_serve = nullptr;

// The stand-in the loose-file worker runs as, and the resource map it reads at +0x18.
alignas(16) unsigned char stand_in[0x100];
alignas(16) unsigned char stand_in_map[0x40];
void* stand_in_vtable[1 + worker_slots];  // [0] is the complete object locator
void* stand_in_map_vtable[1 + map_slots];

using Exists = Word (*)(void*, void*);
using Size = Word (*)(void*, void*, uint64_t*);
using Load = Word (*)(void*, void*, void*, Word);
using Request = Word (*)(void*, void*, Word, Word, Word, Word, Word, Word, Word, Word, Word, Word);
Exists next_exists{};
Size next_size{};
Load next_load{}, next_async{}, loose_load{}, loose_async{};
std::array<Request, worker_slots> next_request{}, loose_request{};

struct SlotPatch { void** slot; void* before; void* after; };
std::vector<SlotPatch> changed;

uint64_t fnv(const char* text, size_t size) noexcept {
    uint64_t hash = 0xcbf29ce484222325ull;
    for (size_t i = 0; i < size; ++i) { hash ^= static_cast<unsigned char>(text[i]); hash *= 0x100000001b3ull; }
    return hash;
}

// The loader passes a path as an object whose first field points at a string whose
// first field is the text.
const char* path_text(void* object) noexcept {
    __try {
        if (!object) return nullptr;
        auto string = *static_cast<void**>(object);
        if (!string) return nullptr;
        auto text = *static_cast<const char**>(string);
        if (!text) return nullptr;
        for (int i = 0; i < 512; ++i) if (!text[i]) return text;
        return nullptr;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return nullptr;
    }
}

// No allocation, lock or I/O: the loader calls this for every path it is asked about.
const Entry* find(void* object) noexcept {
    const char* text = path_text(object);
    if (!text || entries.empty()) return nullptr;
    while (*text == '/' || *text == '\\') ++text;
    std::array<char, 512> key{};
    size_t size = 0;
    for (; *text && size < key.size(); ++text) {
        char c = *text;
        key[size++] = c == '\\' ? '/' : (c >= 'A' && c <= 'Z') ? static_cast<char>(c + 32) : c;
    }
    if (!size || *text) return nullptr;
    const auto hash = fnv(key.data(), size);
    auto at = std::lower_bound(entries.begin(), entries.end(), hash, [](const Entry& entry, uint64_t value) { return entry.hash < value; });
    for (; at != entries.end() && at->hash == hash; ++at)
        if (at->logical.size() == size && !std::memcmp(at->logical.data(), key.data(), size)) return &*at;
    return nullptr;
}

void report(const Entry& entry, bool async) noexcept { if (on_serve) on_serve(entry.logical.c_str(), async); }

// The package worker's slots.
Word served_exists(void* self, void* path) { return find(path) ? 1 : next_exists(self, path); }
Word served_size(void* self, void* path, uint64_t* out) {
    if (auto entry = find(path)) { if (out) *out = entry->size; return 1; }
    return next_size(self, path, out);
}
Word served_load(void* self, void* context, void* request, Word mode) {
    if (auto entry = find(request)) { report(*entry, false); return loose_load(stand_in, context, request, mode); }
    return next_load(self, context, request, mode);
}
Word served_async(void* self, void* context, void* request, Word callback) {
    if (auto entry = find(request)) { report(*entry, true); return loose_async(stand_in, context, request, callback); }
    return next_async(self, context, request, callback);
}
bool started_by_stand_in(void* request) noexcept {
    return request && *reinterpret_cast<void**>(static_cast<unsigned char*>(request) + owner_offset) == stand_in;
}
template <int slot>
Word follow_request(void* self, void* request, Word c, Word d, Word e, Word f, Word g, Word h, Word i, Word j, Word k, Word l) {
    return started_by_stand_in(request) ? loose_request[slot](stand_in, request, c, d, e, f, g, h, i, j, k, l)
                                        : next_request[slot](self, request, c, d, e, f, g, h, i, j, k, l);
}

// The stand-in's own slots and its resource map.
void* returns_self(void* self) { return self; }
Word returns_zero() { return 0; }
Word returns_one() { return 1; }
void does_nothing() {}
Word map_exists(void*, void* path) { return find(path) != nullptr; }
Word map_size(void*, void* path, uint64_t* out) {
    auto entry = find(path);
    if (!entry) return 0;
    if (out) *out = entry->size;
    return 1;
}
Word map_time(void*, void*, int64_t* out) { if (out) *out = -1; return 0; }
Word map_resolve(void*, void* path, void** out) {
    auto entry = find(path);
    if (!entry || !entry->record || !out) return 0;
    *out = entry->record;
    return 1;
}

// The loader's string record for a file: text, length, 0xFFFFFFFF, 0x80000000, then
// the UTF-8 text. The loose-file worker opens the file it names.
void* string_record(const std::string& text) {
    auto block = static_cast<unsigned char*>(HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, 0x18 + text.size() + 1));
    require(block != nullptr, "Cannot allocate a served path");
    auto copy = reinterpret_cast<char*>(block + 0x18);
    std::memcpy(copy, text.data(), text.size());
    *reinterpret_cast<char**>(block) = copy;
    *reinterpret_cast<uint32_t*>(block + 0x08) = static_cast<uint32_t>(text.size());
    *reinterpret_cast<uint32_t*>(block + 0x0c) = 0xffffffffu;
    *reinterpret_cast<uint32_t*>(block + 0x10) = 0x80000000u;
    return block;
}

std::string utf8(const std::wstring& text) {
    if (text.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    require(size > 0, "Served path is not valid Unicode");
    std::string result(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), result.data(), size, nullptr, nullptr);
    return result;
}

struct Image { unsigned char* base{}; size_t size{}; };
Image main_image() {
    auto base = reinterpret_cast<unsigned char*>(GetModuleHandleW(nullptr));
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    require(dos->e_magic == IMAGE_DOS_SIGNATURE && dos->e_lfanew > 0 && dos->e_lfanew < 0x100000, "Invalid DOS header");
    auto pe = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    require(pe->Signature == IMAGE_NT_SIGNATURE && pe->FileHeader.Machine == IMAGE_FILE_MACHINE_AMD64, "Unsupported PE");
    return {base, pe->OptionalHeader.SizeOfImage};
}

bool readable_page(DWORD protect) {
    return !(protect & (PAGE_GUARD | PAGE_NOACCESS)) &&
           (protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY));
}
bool executable(const void* address) {
    MEMORY_BASIC_INFORMATION info{};
    return address && VirtualQuery(address, &info, sizeof info) && info.State == MEM_COMMIT &&
           (info.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) &&
           !(info.Protect & PAGE_GUARD);
}

// Visits every readable committed region of the image.
template <class Visit>
void each_region(const Image& image, Visit visit) {
    for (auto page = image.base; page < image.base + image.size;) {
        MEMORY_BASIC_INFORMATION info{};
        if (!VirtualQuery(page, &info, sizeof info)) break;
        auto end = std::min(static_cast<unsigned char*>(info.BaseAddress) + info.RegionSize, image.base + image.size);
        if (info.State == MEM_COMMIT && readable_page(info.Protect)) visit(page, end);
        page = end;
    }
}

struct Class { const char* name; unsigned char* descriptor{}; unsigned char* locator{}; void** vtable{}; int vtables{}; };

// Type descriptor: vftable, spare, then the decorated name. Complete object locator:
// signature 1, offset, constructor offset, then the descriptor's, hierarchy's and its
// own image offsets. The qword before a vtable points at its locator.
void find_classes(const Image& image, std::array<Class, 3>& classes) {
    each_region(image, [&](unsigned char* begin, unsigned char* end) {
        for (auto& item : classes) {
            const auto size = std::strlen(item.name) + 1;
            for (auto at = begin; !item.descriptor && at + size <= end; ++at)
                if (*at == '.' && !std::memcmp(at, item.name, size) && at - 16 >= image.base) item.descriptor = at - 16;
        }
    });
    for (auto& item : classes) require(item.descriptor != nullptr, "The game's resource loader classes were not found");
    each_region(image, [&](unsigned char* begin, unsigned char* end) {
        for (auto at = begin + ((4 - reinterpret_cast<uintptr_t>(begin) % 4) % 4); at + 24 <= end; at += 4) {
            if (*reinterpret_cast<uint32_t*>(at) != 1 || *reinterpret_cast<uint32_t*>(at + 4) != 0) continue;
            for (auto& item : classes)
                if (*reinterpret_cast<uint32_t*>(at + 12) == static_cast<uint32_t>(item.descriptor - image.base) &&
                    *reinterpret_cast<uint32_t*>(at + 20) == static_cast<uint32_t>(at - image.base))
                    item.locator = at;
        }
    });
    for (auto& item : classes) require(item.locator != nullptr, "A resource loader class has no complete object locator");
    each_region(image, [&](unsigned char* begin, unsigned char* end) {
        for (auto at = begin + ((8 - reinterpret_cast<uintptr_t>(begin) % 8) % 8); at + 16 <= end; at += 8)
            for (auto& item : classes)
                if (*reinterpret_cast<unsigned char**>(at) == item.locator) { item.vtable = reinterpret_cast<void**>(at + 8); ++item.vtables; }
    });
}

std::string owner(const void* address) {
    HMODULE module{};
    std::array<wchar_t, 32768> path{};
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            static_cast<LPCWSTR>(address), &module) ||
        !GetModuleFileNameW(module, path.data(), static_cast<DWORD>(path.size()))) return "unknown module";
    auto name = utf8(fs::path(path.data()).filename().wstring());
    std::ostringstream out;
    out << name << "+0x" << std::hex << (reinterpret_cast<uintptr_t>(address) - reinterpret_cast<uintptr_t>(module));
    return out.str();
}

void patch(void** slot, void* after) {
    DWORD old{};
    require(VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old), "Cannot open a resource loader slot");
    void* before = *slot;
    auto prior = InterlockedCompareExchangePointer(slot, after, before);
    DWORD ignored{};
    const bool restored = VirtualProtect(slot, sizeof(void*), old, &ignored) != FALSE;
    require(prior == before && restored, "A resource loader slot changed or its protection was not restored");
    changed.push_back({slot, before, after});
}
}  // namespace

void stop_serving() noexcept {
    for (auto it = changed.rbegin(); it != changed.rend(); ++it) {
        DWORD old{};
        if (*it->slot != it->after || !VirtualProtect(it->slot, sizeof(void*), PAGE_READWRITE, &old)) continue;
        InterlockedCompareExchangePointer(it->slot, it->before, it->after);
        DWORD ignored{};
        VirtualProtect(it->slot, sizeof(void*), old, &ignored);
    }
    changed.clear();
}

std::string serve_resources(std::vector<ServedResource> resources, ServeTrace served) {
    require(changed.empty() && entries.empty(), "Resources are already served");
    require(!resources.empty() && resources.size() <= max_resources, "Invalid served resource count");
    std::vector<Entry> table;
    table.reserve(resources.size());
    for (auto& resource : resources) {
        require(resource_path(std::wstring(resource.logical.begin(), resource.logical.end())), "Invalid served resource path");
        table.push_back({fnv(resource.logical.data(), resource.logical.size()), resource.logical, string_record(utf8(resource.path)), resource.size});
    }
    std::sort(table.begin(), table.end(), [](const Entry& a, const Entry& b) { return a.hash < b.hash || (a.hash == b.hash && a.logical < b.logical); });
    for (size_t i = 1; i < table.size(); ++i) require(table[i].logical != table[i - 1].logical, "Duplicate served resource path");

    const auto image = main_image();
    std::array<Class, 3> classes{{{".?AVBaseResourceLoadWorker@pa@@"}, {".?AVResourceLoadWorker_Package@pa@@"},
                                  {".?AVBasePackageResourceMap@pa@@"}}};
    find_classes(image, classes);
    auto& loose = classes[0];
    auto& package = classes[1];
    for (auto* item : {&loose, &package})
        require(item->vtables == 1, "A resource loader class does not have exactly one primary vtable");
    for (int slot = 0; slot < worker_slots; ++slot) {
        require(executable(loose.vtable[slot]) && reinterpret_cast<unsigned char*>(loose.vtable[slot]) >= image.base &&
                reinterpret_cast<unsigned char*>(loose.vtable[slot]) < image.base + image.size,
                "The loose-file worker's vtable has an unexpected shape");
        require(executable(package.vtable[slot]), "The package worker's vtable has an unexpected shape");
    }

    // The stand-in: a copy of the loose-file worker's vtable, its own first two slots,
    // the fields DmmRuntime sets, and the resource map that answers for served paths.
    stand_in_vtable[0] = loose.locator;
    std::memcpy(&stand_in_vtable[1], loose.vtable, sizeof(void*) * worker_slots);
    stand_in_vtable[1] = reinterpret_cast<void*>(&returns_self);
    stand_in_vtable[2] = reinterpret_cast<void*>(&returns_zero);
    std::memset(stand_in, 0, sizeof stand_in);
    *reinterpret_cast<void***>(stand_in) = &stand_in_vtable[1];
    *reinterpret_cast<uint32_t*>(stand_in + 0x10) = 0x10000000u;
    stand_in[0x14] = 1;
    stand_in[0x16] = 1;
    *reinterpret_cast<void**>(stand_in + 0x18) = stand_in_map;
    const std::array<void*, map_slots> map{
        reinterpret_cast<void*>(&returns_self), reinterpret_cast<void*>(&returns_zero), reinterpret_cast<void*>(&returns_zero),
        reinterpret_cast<void*>(&does_nothing), reinterpret_cast<void*>(&map_exists), reinterpret_cast<void*>(&map_size),
        reinterpret_cast<void*>(&map_time), reinterpret_cast<void*>(&map_resolve), reinterpret_cast<void*>(&returns_one),
        reinterpret_cast<void*>(&returns_zero), reinterpret_cast<void*>(&returns_zero)};
    stand_in_map_vtable[0] = classes[2].locator;
    std::copy(map.begin(), map.end(), &stand_in_map_vtable[1]);
    std::memset(stand_in_map, 0, sizeof stand_in_map);
    *reinterpret_cast<void***>(stand_in_map) = &stand_in_map_vtable[1];

    loose_load = reinterpret_cast<Load>(loose.vtable[load_slot]);
    loose_async = reinterpret_cast<Load>(loose.vtable[async_slot]);
    for (int slot : request_slots) loose_request[slot] = reinterpret_cast<Request>(loose.vtable[slot]);
    next_exists = reinterpret_cast<Exists>(package.vtable[exists_slot]);
    next_size = reinterpret_cast<Size>(package.vtable[size_slot]);
    next_load = reinterpret_cast<Load>(package.vtable[load_slot]);
    next_async = reinterpret_cast<Load>(package.vtable[async_slot]);
    for (int slot : request_slots) next_request[slot] = reinterpret_cast<Request>(package.vtable[slot]);

    std::ostringstream summary;
    summary << "Resource loader found: package worker vtable at " << owner(package.vtable)
            << ", loose-file worker at " << owner(loose.vtable) << "; ";
    for (int slot : {load_slot, exists_slot, size_slot, async_slot, 3, 4, 5, 6, 12}) {
        const bool own = reinterpret_cast<unsigned char*>(package.vtable[slot]) >= image.base &&
                         reinterpret_cast<unsigned char*>(package.vtable[slot]) < image.base + image.size;
        if (!own) summary << "slot " << slot << " chained to " << owner(package.vtable[slot]) << "; ";
    }
    entries = std::move(table);
    on_serve = served;
    const std::array<void*, worker_slots> replacements{
        nullptr, nullptr, reinterpret_cast<void*>(&served_load), reinterpret_cast<void*>(&follow_request<3>),
        reinterpret_cast<void*>(&follow_request<4>), reinterpret_cast<void*>(&follow_request<5>),
        reinterpret_cast<void*>(&follow_request<6>), nullptr, nullptr, nullptr, reinterpret_cast<void*>(&served_exists),
        reinterpret_cast<void*>(&served_size), reinterpret_cast<void*>(&follow_request<12>), reinterpret_cast<void*>(&served_async)};
    try {
        for (int slot = 0; slot < worker_slots; ++slot)
            if (replacements[slot]) patch(&package.vtable[slot], replacements[slot]);
    } catch (...) {
        stop_serving();
        entries.clear();
        on_serve = nullptr;
        throw;
    }
    summary << entries.size() << " paths served";
    return summary.str();
}
}  // namespace cdmw::vfs
