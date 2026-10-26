#pragma once
#include "protocol.hpp"

namespace cdmw::vfs {
// Launch-time composition (milestone 2). The input is provisional until packages carry
// runtime/ members: one change set file (*.cdchanges) per package in this folder, composed
// in file-name order onto what the game reads today.
inline constexpr wchar_t compose_folder[] = L".cdmw/virtual-loader/compose";
inline constexpr wchar_t compose_cache_folder[] = L".cdmw/virtual-loader/compose-cache";
// True when the folder holds a change set; a launch then composes instead of using a
// published standalone profile.
bool composition_requested(const fs::path& root);
struct ComposedLaunch {
    std::string key;                // cache identity: the inputs known before composing
    bool reused = false;            // the cache was verified instead of composed again
    std::string group;
    std::size_t packages = 0, composed = 0;
    std::vector<File> files;        // logical name -> verified cache file
    std::vector<Handle> pins;       // sources and outputs, held read-only for the session
    std::array<double, 5> stage_ms{};
    uint64_t compose_ms = 0;
    // Startup diagnostics taken before composing (-1 not taken): whether a new thread ran
    // within a second, and whether this thread holds the loader lock.
    int worker_thread = -1, loader_lock = -1;
};
// Composes, or reuses the cache built from the same inputs, and pins everything the
// mapped files were built from. Throws with the reason on any refusal.
ComposedLaunch prepare_composition(const fs::path& root, const Hash& game);
// installation_lane.lock_path: CDMW's per-installation lock file.
fs::path installation_lane(const fs::path& root);
void compose_status(const fs::path& root, const char* state, const ComposedLaunch& launch, DWORD error, const char* detail, uint64_t elapsed_ms);
}
