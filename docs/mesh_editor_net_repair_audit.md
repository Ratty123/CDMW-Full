# .NET Mesh Editor Repair Audit

Last updated: 2026-07-08

## Current entry point

- The embedded .NET helper is launched from `cdmw/ui/mesh_editor/tab.py` through `MeshEditorTab._start_dotnet_editor_requested`, `mesh_dotnet_experiment_command`, and a `QProcess` bridge.
- The helper is built from `tools/dotnet_mesh_editor_experiment/Cdmw.MeshEditorExperiment.csproj` and hosted with `--embedded --parent-hwnd` when the embedded route is active.
- The Archive Browser replacement builder starts and stops embedded edit mode through `cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py`.

## Current .NET editor files

- `tools/dotnet_mesh_editor_experiment/Program.cs` contains the WinForms editor shell, OBJ loader, software viewport, embedded child-window host, NDJSON protocol reader/writer, local same-count OBJ save path, and command/status handoff.
- `cdmw/services/mesh_dotnet_experiment.py` packages the editable OBJ/sidecar handoff, locates the helper executable, imports the saved output, and writes evaluation notes.

## Host integration path

- Python/C++ stays authoritative for parsing, native edit commands, validation, rebuild, material routing, texture discovery, and archive safety.
- .NET receives an editable OBJ package and sends live `select_request`, `stroke_*`, and `command_request` events over stdout.
- Mesh/session `command_request` payloads include the local .NET selection mirror and route through `MeshEditorController`/`MeshService`; only viewport presentation controls stay local to .NET.
- Python returns `selection_update`, `preview_vertex_update`, `preview_triangle_update`, and `command_result` events over stdin.

## Mesh data flow

1. Host selected mesh is parsed by the existing MeshService / archive replacement pipeline.
2. The .NET handoff package writes `mesh.obj`, `mesh.obj.meta.json`, `mesh.cdmeta.json`, and `edit_operations.json` paths.
3. .NET loads `mesh.obj` into `ObjDocument` for viewport interaction.
4. Live commands route to `MeshEditorController` and `MeshService`; preview deltas update the .NET document.
5. On close/save, .NET writes a same-count OBJ output plus edit operations.
6. Python imports the .NET output through the existing sidecar contract, validates it, refreshes D3D11/native preview state, and reuses the normal material/texture pipeline.

## Texture and material data flow

- Texture and material authority remains in Python/C++ and the existing D3D11 preview payloads.
- .NET currently displays solid/wire software geometry and does not directly own material routing.
- On edit stop, the host must reapply material slots and texture bindings from the existing preview/rebuild path after importing .NET geometry.

## Edit mode lifecycle

- Enter edit mode: host starts the embedded .NET helper by default when the helper is available and a parent HWND exists; `mesh_editor/use_embedded_dotnet_viewport=false` remains a developer fallback. Helper availability is tracked separately as `_mesh_editor_dotnet_available`.
- During launch: native/classic controls remain usable until a matching .NET `ready` protocol event marks `_mesh_editor_embedded_dotnet_active=true`.
- During edit mode: .NET emits commands and updates its own viewport from Python preview deltas.
- Stop edit mode: host first asks .NET to close and save, then imports .NET output or syncs from the Python/C++ working mesh if the live bridge already applied edits. The builder then rebuilds the textured/material preview from that edited working mesh.
- Failure path: failed launch, process error, or process finish clears embedded ownership and returns to the existing native D3D11 edit path.

## Current selection and hit test implementation

- .NET emits screen brush/drag payloads with a `world_view_projection` matrix.
- X-Ray state is sent as `selection_depth_mode`, so host selection requests can keep visible-only and X-Ray semantics aligned with Python/C++ native selection code.
- Host `selection_update` payloads now refresh .NET vertex, face, edge, and source-part overlay state. Edge sync accepts `edges_by_submesh` and stable edge descriptor payloads.
- Command button payloads include vertices, faces, edges, source indices, edge descriptors, topology generation, target mode, and selection depth so host commands can apply the same selection mirror.

## Known broken or weak areas

- The embedded WinForms chrome used default Windows colors, so it appeared detached from the dark Qt UI.
- The tool panel was one long ungrouped `Panel` with reverse `DockStyle.Top` stacking, making controls cramped and hard to scan.
- Camera controls were limited to `Frame Mesh`; the camera buttons exposed by the surrounding UI were not mirrored in the .NET editor chrome.
- Real embedded .NET visual proof on PAC assets is still required before the setting can be promoted to default.
- Camera and overlay source guards now prevent reintroducing duplicate projection math or D3D11-over-GDI overlay composition, but visual orientation still needs real PAC screenshots before default promotion.

## 2026-07-08 repair results

- Repaired embedded .NET gating so helper availability no longer auto-owns Edit Mesh.
- Added embedded active lifecycle state: closed, launching, ready, closing, failed.
- Changed classic-toolbar/input ownership to depend on `_mesh_editor_embedded_dotnet_active`, which is set only after .NET `ready`.
- Changed .NET command buttons, including Clear Selection, Select All, Invert, Grow, Shrink, and Move +X / Move -X, to emit host-owned `command_request` payloads instead of changing local session state as authority.
- Removed direct local OBJ mutation from Move +X / Move -X.
- Added host parsing for `.NET` `local_selection` snapshots, including edge pairs and stable edge descriptors.
- Added .NET parsing for host edge selection updates and canonical object-map payloads.
- Changed renderer status text so idle and waiting-for-first-frame are not shown as false `0.0 FPS` failures.
- Added shared `NetViewportCamera` ownership for projection/camera state across WinForms fallback projection, WPF camera setup, D3D11 shader constants, pointer payload matrices, picking, and overlay projection.
- Corrected .NET top/bottom camera preset semantics to match the native preview direction convention.
- Replaced D3D11 plus GDI overlay composition with D3D11-owned line/triangle overlay primitives drawn before swap-chain `Present`.
