#pragma once
#include "protocol.hpp"

namespace cdmw::vfs {
// Exact-build compatibility with UAL 9.7.1's retained forwarding wrappers.
// No bootstrap instructions, configuration, data or import slots are changed.
class VerifiedBootstrap {
    fs::path root;
    HMODULE module{};
    bool checked{}, verified{};
public:
    explicit VerifiedBootstrap(const fs::path& installation): root(installation) {}
    bool accepts(const char* name, void* current, void* expected);
};
}
