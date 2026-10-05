#pragma once
#include "protocol.hpp"
#include <span>

namespace cdmw::vfs {
// The ordered deferred-startup return sites observed before the first archive
// read in complete warm/cold traces of the fingerprinted game and bootstrap.
bool matches_startup_frames(std::span<void* const> frames, uintptr_t bootstrap, uintptr_t game);
bool first_live_thread();
// Exact-build compatibility with UAL 9.7.1's retained forwarding wrappers.
// No bootstrap instructions, configuration, data or import slots are changed.
class VerifiedBootstrap {
    fs::path root;
    HMODULE module{};
    bool checked{}, verified{};
    bool verify();
public:
    explicit VerifiedBootstrap(const fs::path& installation): root(installation) {}
    bool accepts(const char* name, void* current, void* expected);
    bool accepts_startup(std::span<void* const> frames, HMODULE game);
};
}
