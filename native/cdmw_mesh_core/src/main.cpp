#include <iostream>
#include <string>
#include <vector>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

#include "mesh_core.hpp"

static int run_main(int argc, char** argv);

#ifdef _WIN32
// The command line arrives wide and is handed on as UTF-8, the encoding every
// path in a job already uses; the ANSI code page would lose characters outside it.
int wmain(int argc, wchar_t** wide_argv) {
    std::vector<std::string> utf8(static_cast<size_t>(argc));
    std::vector<char*> argv(static_cast<size_t>(argc) + 1, nullptr);
    for (int index = 0; index < argc; ++index) {
        const int size = WideCharToMultiByte(CP_UTF8, 0, wide_argv[index], -1, nullptr, 0, nullptr, nullptr);
        std::string& text = utf8[static_cast<size_t>(index)];
        text.assign(size > 0 ? static_cast<size_t>(size - 1) : 0, '\0');
        if (size > 1) {
            WideCharToMultiByte(CP_UTF8, 0, wide_argv[index], -1, text.data(), size, nullptr, nullptr);
        }
        argv[static_cast<size_t>(index)] = text.data();
    }
    return run_main(argc, argv.data());
}
#else
int main(int argc, char** argv) {
    return run_main(argc, argv);
}
#endif

static int run_main(int argc, char** argv) {
    if (argc >= 2 && std::string(argv[1]) == "--version") {
        std::cout << "cdmw-mesh-core 0.1\n";
        return 0;
    }
    if (argc >= 2 && std::string(argv[1]) == "--service") {
        return cdmw_mesh_core::run_service();
    }
    if (argc == 4) {
        const int exit_code = cdmw_mesh_core::mesh_core_json_command(argv[1], argv[2], argv[3]);
        if (exit_code >= 0) {
            return exit_code;
        }
    }
    std::cerr << "usage: cdmw-mesh-core --service | <mesh-session-json|mesh-editor-session-json|transform-json|restore-vertices-json|snapshot-vertices-json|snapshot-submeshes-json|selection-json|uv-selection-json|uv-summary-json|mesh-metadata-json|selection-bounds-json|selection-preview-json|selection-prune-json|uv-transform-json|auto-uv-json|recalculate-normals-json|generate-tangents-json|morph-apply-json|morph-post-edit-delta-json|morph-target-delta-json|region-volume-delta-json|static-donor-indices-json|pose-preview-json|skin-weights-json|obj-export-json|obj-manifest-json|fbx-geometry-json|fbx-export-json|cleanup-json|edit-json|preview-identity-json|preview-model-json|preview-geometry-json|preview-triangle-groups-json|preview-vertex-update-groups-json|merge-submeshes-json|preview-decimate-json|affine-transform-json> <job.json> <report.json>\n";
    return 1;
}
