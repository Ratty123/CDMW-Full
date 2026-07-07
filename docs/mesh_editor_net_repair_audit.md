# .NET Mesh Editor Repair Audit

Last updated: 2026-07-07

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

- Enter edit mode: host starts the embedded .NET helper if `mesh_editor/use_embedded_dotnet_viewport` is enabled and a parent HWND exists.
- During edit mode: .NET emits commands and updates its own software viewport from Python preview deltas.
- Stop edit mode: host first asks .NET to close and save, then imports .NET output or syncs from the Python/C++ working mesh if the live bridge already applied edits.
- Failure path: the existing native D3D11 edit path remains the rollback route.

## Current selection and hit test implementation

- .NET emits screen brush/drag payloads with a `world_view_projection` matrix.
- X-Ray state is currently sent as `selection_depth_mode`, so hit testing semantics are owned by Python/C++ native selection code.
- Before this repair pass, the .NET viewport did not render returned selection overlays and its X-Ray checkbox did not change the .NET viewport display.

## Known broken or weak areas

- The embedded WinForms chrome used default Windows colors, so it appeared detached from the dark Qt UI.
- The tool panel was one long ungrouped `Panel` with reverse `DockStyle.Top` stacking, making controls cramped and hard to scan.
- Camera controls were limited to `Frame Mesh`; the camera buttons exposed by the surrounding UI were not mirrored in the .NET editor chrome.
- Selection updates from the host were acknowledged only as text and were not drawn as selected vertices/faces in the .NET viewport.
- The Move +X / Move -X helpers ignored the current returned selection and moved the whole selected submesh.
- X-Ray affected protocol selection depth but not local rendering.

## Planned fixes in this pass

- Rebuild the .NET tool panel as dark themed grouped sections with a scrollable body and fixed status footer.
- Add deterministic camera preset buttons and preview-mode shortcuts.
- Draw host-returned vertex/face/part selection overlays in the .NET viewport.
- Make local step translation prefer selected vertices or selected-face vertices before falling back to the selected part.
- Make X-Ray alter local rendering and continue to affect selection protocol payloads.
- Add source-guard tests for the embedded .NET UI chrome, camera controls, X-Ray rendering, and selection overlay behavior.
