# .NET Mesh Editor Repair Audit

Last updated: 2026-07-11

## Current entry point

- The embedded .NET helper is launched from `cdmw/ui/mesh_editor/tab.py` through `MeshEditorTab._start_dotnet_editor_requested`, `mesh_dotnet_experiment_command`, and a `QProcess` bridge.
- The helper is built from `tools/dotnet_mesh_editor_experiment/Cdmw.MeshEditorExperiment.csproj` and hosted with `--embedded --parent-hwnd` when the embedded route is active.
- The Archive Browser replacement builder starts and stops embedded edit mode through `cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py`.

## Current .NET editor files

- `tools/dotnet_mesh_editor_experiment/ProgramEntry.cs` contains the process entrypoint and CLI launch flow.
- `tools/dotnet_mesh_editor_experiment/Program.cs` contains only the remaining WinForms editor and viewport shells.
- Extracted `ExperimentForm.*.cs` owners cover controls, host state, protocol
  JSON/binary parsing, output/status persistence, and protocol/update handlers.
- Extracted `MeshViewport.*.cs` owners cover bounds, geometry/math, renderer and
  retained resources, host diagnostics, status payloads, topology, selection,
  picking, input, and software paint fallback helpers.
- `RuntimeSupport.cs`, `NativeWindowHost.cs`, `ObjDocument.cs`,
  `NetEdgeTopology.cs`, `NetMaterialSet.cs`, `NetTextureSet*.cs`, and
  `GeometryPrimitives.cs` own launch/runtime helpers, embedded HWND hosting, OBJ
  interchange, local edge topology, material manifests, texture/DDS decoding,
  and shared primitive records.
- `cdmw/services/mesh_dotnet_experiment.py` packages the editable OBJ/sidecar handoff, locates the helper executable, imports the saved output, and writes evaluation notes.

## Host integration path

- Python/C++ stays authoritative for parsing, native edit commands, validation, rebuild, material routing, texture discovery, and archive safety.
- .NET receives an editable OBJ preview package and sends live `select_request`, `selection_request`, `stroke_*`, and `command_request` events over stdout.
- Mesh/session `command_request` payloads include the local .NET selection mirror and route through `MeshEditorController`/`MeshService`; only viewport presentation controls stay local to .NET.
- Python returns `selection_update`, `preview_vertex_update`, `preview_triangle_update`, and `command_result` events over stdin.

## Mesh data flow

1. Host selected mesh is parsed by the existing MeshService / archive replacement pipeline.
2. The .NET handoff package writes `mesh.obj`, `mesh.obj.meta.json`, `mesh.cdmeta.json`, and `edit_operations.json` paths.
3. .NET loads `mesh.obj` into `ObjDocument` for viewport interaction.
4. Live commands route to `MeshEditorController` and `MeshService`; preview deltas update the .NET document.
5. Embedded edits remain authoritative in the resident C++ `MeshEditSession`; the OBJ output is diagnostic/standalone interchange only.
6. Leaving Edit Mesh syncs that resident session once, then restores the normal material/texture preview without replacing it from OBJ.

## Texture and material data flow

- Texture and material authority remains in Python/C++ and the existing D3D11 preview payloads.
- .NET reports ready before texture decoding, loads textures in a background task, uploads them through its D3D11 viewport, and keeps the process-local texture cache for the asset session.
- The native D3D11 process stays alive below .NET. Its SRV cache uses Windows file identity so hard-linked textures survive package-path changes.
- Leaving Edit Mesh hides rather than exits the .NET child. The host waits for the ordered `deactivated` acknowledgement before syncing, so queued stroke events cannot land after the saved preview. The latest original-reference model is read at material reapply time, then the existing preview transition schedules one texture/static refresh.
- Reactivation compares the current material-input signature with the running package. Changed texture/material inputs rebuild the package and helper; unchanged inputs reuse the same decoded texture cache.

## Edit mode lifecycle

- Enter edit mode: host starts the embedded .NET helper by default when the helper is available and a parent HWND exists; `mesh_editor/use_embedded_dotnet_viewport=false` remains a developer fallback. Helper availability is tracked separately as `_mesh_editor_dotnet_available`.
- During launch: the classic Qt edit toolbar hides as soon as `_mesh_editor_embedded_dotnet_state` enters `launching`. Native D3D11 stays alive underneath until accepted .NET `ready`; a 10-second ready watchdog restores native fallback after a hung launch.
- During edit mode: local selection is mirrored to the resident service, strokes use incremental pointer segments, heavy commands run through `MeshEditCommandWorker`, and .NET consumes native preview deltas.
- Stop edit mode: host sends `deactivate_request`, waits for its ordered acknowledgement and any active command to finish/cancel, syncs the resident session once, hides .NET as `suspended`, and restores the textured preview. A two-second acknowledgement watchdog stops a stuck helper before committing resident edits. Re-entry sends `activate_request` to the same process only when its material signature still matches.
- Failure path: invalid HWND embedding, failed launch, unexpected process
  error/finish, or renderer-blocked `ready` clears embedded ownership and
  restores the legacy compatibility edit controls without finalizing away
  resident edits. That fallback is not accepted by the production proof.

## Current selection and hit test implementation

- .NET emits screen brush/drag payloads with a `world_view_projection` matrix.
- X-Ray state is sent as `selection_depth_mode`, so host selection requests can keep visible-only and X-Ray semantics aligned with Python/C++ native selection code.
- Host `selection_update` payloads now refresh .NET vertex, face, edge, and source-part overlay state. Edge sync accepts `edges_by_submesh` and stable edge descriptor payloads.
- Command button payloads include vertices, faces, edges, source indices, edge descriptors, topology generation, target mode, and selection depth so host commands can apply the same selection mirror.

## Current proof status

- `real-archive-mesh-editor-dotnet-edit-smoke` passes with the production
  `d3d11_vortice_shader` renderer and `cdmw_mesh_core_0.1` edit backend. It binds
  three real archive DDS textures, changes selected geometry only, records
  before/after/diff captures and timing evidence, and leaves source PAMT/PAZ
  hashes unchanged. Same-camera native/.NET golden comparison remains separate
  follow-up work rather than a substitute for this production proof.

## 2026-07-09 repair results

- Repaired embedded .NET gating so helper availability no longer auto-owns Edit Mesh.
- Added embedded lifecycle states `closed`, `launching`, `ready`, `closing`, `suspended`, and `failed`.
- Changed classic-toolbar/input ownership to hide classic controls for `launching`, `ready`, and `closing` embedded .NET states while keeping `_mesh_editor_embedded_dotnet_active` true only after accepted .NET `ready`.
- Kept native D3D11 alive below embedded .NET so fallback and texture SRVs stay resident.
- Changed renderer-blocked embedded .NET `ready` handling to fail closed and terminate the visible child process before restoring fallback controls.
- Hardened embedded WinForms HWND ownership by applying child-window style before `SetParent`, verifying the resulting parent before `ready`, bringing the child to the top, and giving the viewport/tool panel explicit focus hooks. Invalid HWNDs emit `embedded_host_unavailable` and return to native fallback.
- Changed .NET command buttons, including Clear Selection, Select All, Invert, Grow, Shrink, and Move +X / Move -X, to emit host-owned `command_request` payloads instead of changing local session state as authority.
- Removed direct local OBJ mutation from Move +X / Move -X.
- Added host parsing for `.NET` `local_selection` snapshots, including edge pairs and stable edge descriptors.
- Added `selection_request` synchronization after local picks, local-selection capture at stroke begin, and incremental stroke endpoints.
- Routed non-transform/brush topology commands through `MeshEditCommandWorker` instead of blocking the Qt UI thread.
- Added .NET parsing for host edge selection updates and canonical object-map payloads.
- Changed renderer status text so idle and waiting-for-first-frame are not shown as false `0.0 FPS` failures.
- Added shared `NetViewportCamera` ownership for projection/camera state across WinForms fallback projection, WPF camera setup, D3D11 shader constants, pointer payload matrices, picking, and overlay projection.
- Corrected .NET top/bottom camera preset semantics to match the native preview direction convention.
- Replaced D3D11 plus GDI overlay composition with D3D11-owned line/triangle overlay primitives drawn before swap-chain `Present`.
- Hardened the .NET handoff manifest as `interchange_format=obj_sidecar` with `metadata_risk=true`; Python/C++ parser, validation, rebuild, and archive write authority remain mandatory.
- Kept `edit_operations.json` mandatory for .NET output import and documented that OBJ is only an interchange sidecar, not a complete PAC metadata container.
- Added production embedded renderer gating: D3D11 is required unless developer renderer fallback is explicitly enabled.
- Kept material parity as a preview warning rather than a geometry-save blocker.
- Made texture decode asynchronous, kept the .NET helper alive while Edit Mesh is off, deduplicated packaged texture resources, and made native D3D11 cache keys stable across hard-linked package paths.
- Retained .NET D3D11 vertex/index buffers across non-topology edits, mapped source vertices to expanded render corners once per topology generation, uploaded only contiguous incident-face ranges, cached material SRV arrays, and exposed buffer/SRV lifetime plus old-and-new VRAM estimates.
- Made embedded exit commit only the resident C++ session; no embedded OBJ reimport can restore stale positions, topology, normals, or UVs.
- Added bundled/dev executable fallback for stale configured paths and a ready watchdog for processes that start but never become interactive.
- Real embedded PAC interaction passed on `cd_phm_00_nude_10_0001.pac`: helper emitted `ready`, `protocol_ready`, and `textures_ready`; deactivate/reactivate retained the same PID; actual WinForms Select chose 6,960 vertices; Move emitted `stroke_begin`, `stroke_update`, `stroke_end`; resident revision advanced `0 -> 1`.
- Actual game archive PAC `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac` passed both native side-by-side visual edit proof and embedded .NET interaction: 13,162 vertices / 24,014 faces, 6,910 selected vertices, Move revision `0 -> 2`, valid GPU D3D11 embedding, deactivation acknowledgement before exactly one finalize/refresh, and same-PID reactivation.
- Real helper texture-cache proof mapped 20 channel references across two submeshes to one packaged PNG: one decode, no failures, one `textures_ready` event, and no reload after same-PID reactivation.

## Follow-up protocol note

OBJ sidecar remains the short-term interop format. A GLB or native binary edit protocol should be handled as a separate milestone after the current editor bridge is stable, because that change affects parser coverage, validation evidence, material metadata, and archive rebuild guarantees.
