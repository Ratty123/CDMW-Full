#include <iostream>
#include <string>

#include "mesh_core.hpp"

int main(int argc, char** argv) {
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
    std::cerr << "usage: cdmw-mesh-core --service | <mesh-session-json|mesh-editor-session-json|transform-json|restore-vertices-json|snapshot-vertices-json|snapshot-submeshes-json|selection-json|uv-selection-json|uv-summary-json|mesh-metadata-json|selection-bounds-json|selection-preview-json|selection-prune-json|uv-transform-json|auto-uv-json|recalculate-normals-json|generate-tangents-json|morph-apply-json|morph-post-edit-delta-json|morph-target-delta-json|region-volume-delta-json|static-donor-indices-json|pose-preview-json|skin-weights-json|obj-export-json|obj-manifest-json|fbx-geometry-json|fbx-export-json|cleanup-json|edit-json|optimize-json|import-scene-json|preview-identity-json|preview-model-json|preview-geometry-json|preview-triangle-groups-json|preview-vertex-update-groups-json|merge-submeshes-json|preview-decimate-json|affine-transform-json> <job.json> <report.json>\n";
    return 1;
}
