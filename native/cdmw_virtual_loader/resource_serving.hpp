#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace cdmw::vfs {
// One file served by game resource path: the lower-case path the package loader is
// asked for, the file that answers it, and that file's size.
struct ServedResource { std::string logical; std::wstring path; uint64_t size{}; };
// Called for each load the runtime serves; must not allocate or block.
using ServeTrace = void (*)(const char* logical, bool async) noexcept;

// Serves `resources` inside the game's package resource loader, the way DmmRuntime
// does, so the mount list and every archive stay as shipped. The loader classes are
// found by their MSVC RTTI names in the game image. The package worker's exists,
// size, load and async-load slots answer for served paths, and a served load runs in
// the game's own loose-file worker with a stand-in worker whose resource map names
// the served file. The slots that act on a load in progress follow the worker that
// started it. Slots already changed by another module are chained, not replaced.
// Returns a one-line summary for the trace. Throws, leaving nothing changed, when a
// class is missing or its vtable does not have the expected shape.
std::string serve_resources(std::vector<ServedResource> resources, ServeTrace trace);
// Restores every changed slot. For a refusal after serve_resources succeeded.
void stop_serving() noexcept;
}
