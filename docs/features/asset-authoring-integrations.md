# Asset Authoring Integrations

Asset authoring helpers are optional. CDMW stays responsible for Crimson-safe
rules, DDS rebuilds, previews, validation, and package output.

## Runtime Contract

- Helper discovery lives in `cdmw/services/asset_authoring_service.py`.
- Normal startup must not execute helper binaries. Exact versions are opt-in
  probes from Settings or harness runs.
- Missing helpers report `unavailable` or `configured_missing`; they do not
  break startup, existing imports, existing mesh edits, or package output.
- Material Maker and OpenImageIO execution runs through `cdmw/workers/`.
- UI code may request work and display reports, but it must not own subprocess
  policy.
- External outputs are review intermediates until existing CDMW paths ingest
  them.

## Helper Setup

Configure helper paths in Settings, or set the matching environment variable.
Point external settings at executable paths outside the repo unless a future
native integration explicitly vendors a library.

| Helper | Setting | Env | Install/build expectation | License note | Fallback |
|---|---|---|---|---|---|
| `cdmw_mesh_core` | bundled | `CDMW_MESH_CORE_BIN` | Build with CMake or `build_native_windows.ps1`; active Mesh Editor operations fail closed when native authority is required. Includes native mesh edit commands, meshoptimizer reports, and ufbx scene report command. | Project-bundled helper. | Explicit legacy/archive-only Python paths; never an active-editor silent fallback. |
| `xatlas` | bundled in `cdmw_mesh_core` | `CDMW_MESH_CORE_BIN` | Build with `cdmw_mesh_core`; `auto-uv-json` reports generated UVs, output topology, vertex remap, chart counts, and topology deltas. Undoable Mesh Edit apply remaps vertex attributes and gates topology changes behind an explicit command flag. | MIT notice is preserved under `native/cdmw_mesh_core/third_party/xatlas/`. | Planar/box/cylindrical Python UV projections. |
| MikkTSpace | bundled in `cdmw_mesh_core` | `CDMW_MESH_CORE_BIN` | Build with `cdmw_mesh_core`; `generate-tangents-json` reports face-corner tangents, signs, vertex-storage remap metadata, and Python applies a topology split when shared vertex storage would average across seams. | Reference code notice is preserved under `native/cdmw_mesh_core/third_party/mikktspace/`. | Existing Python tangent generator if native helper is missing or fails. |
| `material_maker` | `asset_authoring/material_maker_path` | `CDMW_MATERIAL_MAKER_BIN` | Install Material Maker separately; configure `asset_authoring/material_maker_export_template` or `CDMW_MATERIAL_MAKER_EXPORT_TEMPLATE` for CLI export. | MIT; external app not bundled. | Existing Texture Workflow assets and DDS paths. |
| `ufbx` | bundled in `cdmw_mesh_core` | `CDMW_MESH_CORE_BIN` | Build with `cdmw_mesh_core`; `import-scene-json` reports FBX mesh/material/texture/rig/animation evidence without claiming game compatibility. | MIT notice is preserved under `native/cdmw_mesh_core/third_party/ufbx/`. | Existing OBJ/DAE/GLB/glTF scene import reports; FBX remains unsupported when native helper is missing. |
| `meshoptimizer` | bundled in `cdmw_mesh_core`; optional external comparator path remains `asset_authoring/meshoptimizer_path` | `CDMW_MESH_CORE_BIN`; comparator `CDMW_MESHOPTIMIZER_BIN` | Build with `cdmw_mesh_core`; `optimize-json` reports vertex-cache/overdraw ordering and opt-in simplification metrics before any apply path. | MIT notice is preserved under `native/cdmw_mesh_core/third_party/meshoptimizer/`. | Conservative topology-preserving package output unless simplification is explicitly reviewed. |
| `openimageio` | `asset_authoring/oiio_path` | `CDMW_OIIO_BIN` | Install `oiiotool` separately; CDMW uses it only for source metadata, conversion, and image diffs. The offline Mesh Editor parity report adds explicit thresholds, structured mean/RMS/max/PSNR metrics, and an amplified absolute-difference PNG. | Primarily Apache-2.0, with small legacy BSD-3-Clause portions. | Existing PNG/JPG/BMP/DDS workflows and DirectXTex DDS authority. |

## Mesh Health Connectivity Checks

`AssetAuthoringService.mesh_health_report` is pure Python preflight and needs no
native helper. Alongside the invalid/degenerate/duplicate/loose counts it reports
connectivity that welding and degenerate-face removal do not fix:

| Field | Meaning | Warns |
|---|---|---|
| `boundary_edges` | Edge used by exactly one face | No — open meshes such as cloth, hair cards, and cut-out geometry are legitimate |
| `non_manifold_edges` | Edge shared by more than two faces | Yes |
| `inconsistent_winding_edges` | Two neighbouring faces traverse a shared edge in the same direction | Yes |
| `bowtie_vertices` | Vertex whose incident faces form more than one disconnected fan | Yes |

Bowties and flipped winding survive cleanup and simplification, and surface as
shading or backface artifacts rather than as invalid geometry, so they are
reported before an edit is accepted. The report stays preflight-only and never
mutates the mesh.

## Failure Behavior

- Version probe timeout or non-zero exit becomes a helper report field.
- Operation failure returns a structured report with the command role, status,
  and actionable message.
- Disabling or removing a helper must not mutate project files.
- Native helper errors fall back only when the operation can preserve the same
  public mesh contract.
- Topology-changing helpers must report before/after counts and topology delta
  before UI accepts replacement output.

## Validation

Focused checks:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_asset_authoring_service.py tests/test_asset_authoring_workers.py tests/test_settings_tab_asset_authoring.py --basetemp="%TEMP%\cdmw-pytest-asset-authoring-services"
.\.venv\Scripts\python.exe -m pytest tests/test_texture_workflow_asset_authoring_panel.py tests/test_texture_workflow_ui_source_guards.py --basetemp="%TEMP%\cdmw-pytest-asset-authoring-ui"
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_service_editing.py tests/test_mesh_editor_controller.py tests/test_mesh_edit_responsiveness_source_guards.py --basetemp="%TEMP%\cdmw-pytest-asset-authoring-mesh"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-discovery --output "%TEMP%\cdmw-asset-authoring-discovery"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-uv-report --output "%TEMP%\cdmw-asset-authoring-uv-report"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-tangent-report --output "%TEMP%\cdmw-asset-authoring-tangent-report"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-mesh-health --output "%TEMP%\cdmw-asset-authoring-mesh-health"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-openimageio-report --output "%TEMP%\cdmw-asset-authoring-openimageio-report"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario mesh-dotnet-native-parity-report --parity-reference "%TEMP%\native.png" --parity-candidate "%TEMP%\dotnet.png" --output "%TEMP%\cdmw-mesh-image-parity"
.\.venv\Scripts\python.exe tools\build_mesh_material_profile_corpus.py --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --external-model "E:\ModelCatalogue\downloads\.cdmw_extracted\wolf_gravestone_sword_free (1)\scene.gltf" --oiio-path ".\.venv\Scripts\oiiotool.exe" --output "%TEMP%\cdmw-mesh-material-profile-corpus.json"
```

The parity scenario is deliberately offline: it compares supplied PNG pixels
but does not launch a renderer or establish same-camera capture provenance. Its
result is useful regression evidence, not user-facing real-PAC visual proof.
The corpus command uses OpenImageIO to record deterministic texture metadata and
pixel statistics beside CDMW's production material classification. It neither
replaces DirectXTex as DDS authority nor participates in runtime shading.

Native check:

```powershell
cmake --build native\cdmw_mesh_core\build --config Release --target cdmw-mesh-core
```

The `asset-authoring-mesh-health` harness writes both mesh-health and
meshoptimizer preflight JSON reports.

## Upstream License References

- xatlas: https://github.com/jpcy/xatlas
- Material Maker: https://github.com/RodZill4/material-maker
- ufbx: https://github.com/ufbx/ufbx
- meshoptimizer: https://github.com/zeux/meshoptimizer
- OpenImageIO: https://github.com/AcademySoftwareFoundation/OpenImageIO
