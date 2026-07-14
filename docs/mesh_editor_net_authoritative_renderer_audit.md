# .NET Mesh Editor Authoritative Renderer Audit

Last updated: 2026-07-14

## 2026-07-14 authoritative resident status

- The D3D11 renderer owns separate Original and Imported/Modify presentation
  contexts over one shared parsed document and GPU resource set. Normal cameras
  are independent; explicit comparison can link them.
- Python owns correlated scene/presentation/material authority. Required
  resource decode failures block Ready, optional failures retain declared
  fallback diagnostics, and late original resources update reference batches
  in-process.
- The helper reports manifest/build, process/assembly, shader, backend,
  protocol, and capability provenance. Generate Icon uses deterministic
  replacement-only offscreen D3D11 rendering with no visible-state mutation.
- The bounded profile corpus covers canonical body, clothing, hair, weapon,
  prop, layered armor, fur, and one external model. It records source DDS
  format/mips, semantic/color-space transport, and unresolved inputs. Shader
  family graphs without capture evidence remain explicit non-claims.

## Current .NET viewport implementation

- Entry point: `tools/dotnet_mesh_editor_experiment/ProgramEntry.cs`.
- UI host and viewport shells: `tools/dotnet_mesh_editor_experiment/Program.cs`.
- Extracted form partials include controls, host state, JSON, output, and
  protocol owners under `ExperimentForm.*.cs`.
- Extracted viewport partials include bounds, geometry, renderer/resources,
  host diagnostics, status, topology, selection, input, and painting owners
  under `MeshViewport.*.cs`.
- Support owners include `RuntimeSupport.cs`, `NativeWindowHost.cs`,
  `ObjDocument.cs`, `NetEdgeTopology.cs`, `NetMaterialSet.cs`,
  `NetTextureSet*.cs`, and `GeometryPrimitives.cs`.
- UI host: WinForms `ExperimentForm`, embedded through `--embedded --parent-hwnd` and `NativeWindowHost`.
- Current viewport class: `MeshViewport : Control` requires
  `D3D11MaterialViewport` in embedded production. WPF through `ElementHost` and
  GDI are explicit developer fallbacks.
- Current primary drawing path: `D3D11MaterialViewport`, a .NET/Vortice Direct3D 11 HWND swap-chain renderer with HLSL vertex/pixel shaders, vertex/index buffers, material constant buffers, SRVs, and a sampler.
- Developer fallback drawing path: WPF `Viewport3D`, then WinForms/GDI+
  software drawing if the D3D11 and WPF paths cannot initialize.
- Current render modes: D3D11 HLSL material/textured mesh, WPF fallback material/textured mesh, wire overlay, local X-Ray overlay, local vertex/edge/face/part overlays in D3D11 and fallback paths, and material debug channels for parity inspection.
- Current mesh source: Wavefront OBJ loaded by `ObjDocument.Load` from the .NET handoff package.
- Current save path: OBJ output plus required `edit_operations.json`; Python/C++ rejects .NET output that lacks authoritative edit operation records before replacing the working mesh.

## Current material and texture loading path

- Host/native material preview data is built in Python through `cdmw/ui/mesh_editor/native_preview_payloads.py` and written through `cdmw/rendering/native_preview_package_writer.py`.
- The .NET helper receives the OBJ package, OBJ sidecar metadata, and `net_materials.json` through `cdmw/services/mesh_dotnet_experiment.py`.
- `net_materials.json` carries material slots, submesh material bindings, deterministic texture channel names, resolved preview texture paths where available, package-local copied texture paths, and fallback names.
- PAC sidecar shader family, alpha mode/cutoff, opacity, and double-sided state
  are applied even when a DDS preview cannot be resolved. A texture failure
  therefore cannot silently erase the surface contract.
- The .NET helper receives resolved Base/Albedo/Diffuse, Normal,
  Material/Specular/Roughness/Metallic, Emissive, Height, Opacity, Occlusion,
  and Layer Mask paths plus shader family, authority, color-space, alpha, and
  double-sided evidence. Source DDS is preferred over preview PNG.
- Supported 2D single-array DDS resources upload through native DXGI resources
  with the complete validated mip chain. This includes BC1-BC7, common
  R/RG/RGBA/BGRA formats, and RGBA16F; sRGB/linear interpretation is selected
  by the SRV rather than baked into pixels. Bitmap BGRA32 is an explicit
  fallback and the copy-on-write surface for resident texture-region editing.
  Cubemaps, arrays, volume DDS, unsupported legacy masks, and failed native
  creation retain a per-resource fallback reason.
- glTF base-color alpha is transported as a constant opacity factor and
  multiplied with sampled alpha. PAC emissive ownership is exact per material
  or submesh; anonymous emissive inputs never leak across unrelated sword,
  handle, skin, or accessory materials.
- Registry-proven Crimson color-blending masks decode R as ambient occlusion,
  G as roughness, and B as metalness. `_mg` detail/grime remains a layer input
  and is never promoted to primary albedo or a packed PBR mask without evidence.

## Native/host preview rendering outside Edit Mesh

- Host D3D11 preview is launched through `mesh_editor_native_preview_command` in `cdmw/ui/mesh_editor/native_preview_runtime.py`.
- Preview packages are prepared by `mesh_editor_write_native_preview_package` / `mesh_editor_write_prepared_native_preview_package`.
- The native D3D11 preview owns normal archive/material preview outside the
  embedded .NET Edit Mesh viewport. It is not the canonical Edit Mesh renderer.
- Python/C++ retain package, material, texture-resolution, session, and archive
  authority while the production .NET/Vortice child owns Edit Mesh presentation
  and input.

## Current .NET mesh rendering path

- The .NET viewport reads `ObjDocument.Submeshes` and builds D3D11 vertex/index buffers with expanded per-corner vertices, normals, tangents, bitangents, and UVs. The WPF fallback builds `MeshGeometry3D` models from the same OBJ data.
- `D3D11MaterialViewport` renders submeshes through a D3D11 swap chain and HLSL shaders. `WpfGpuMeshViewport` is the explicit developer fallback.
- The renderer probes the custom D3D11/Vortice/HLSL path first and only
  attaches it after device, swap chain, shader, render target, depth target, and
  geometry setup succeed; WPF GPU composition is never accepted by embedded
  production.
- `D3D11MaterialViewport` uses sRGB render-target output, semantic sRGB/linear
  SRVs, GGX distribution/Smith visibility/Schlick Fresnel, normal/material/
  specular/roughness/metallic/height/emissive/opacity/occlusion sampling,
  evidence-driven alpha clip, and per-material double-sided raster state.
  Opaque/cutout draws retain depth write; blend draws use depth read without
  write and are sorted back-to-front by transformed submesh center. Layer graphs
  and proprietary per-triangle blend ordering are reported but not guessed.

## Current overlay rendering path

- Vertex/edge/face/source-part overlay drawing is local to the .NET viewport after the renderer reliability pass.
- Selection state can still be updated from host protocol messages.
- The D3D11 material path now draws wire, selected vertices, selected edges, hovered edge, selected faces, selected source parts, selection rectangle, and an X-Ray marker through its overlay paint path using the same camera matrix bundle as the shader constants.

## Current selection state owner

- During embedded editing, Python/C++ remains the authoritative command/session engine through `MeshEditorController` and `MeshService`.
- The .NET viewport can keep a local mirror of selected vertices/faces/source parts/edges for display.
- The .NET viewport does not own the full edit session or final authoritative selection model; output import now fails closed unless matching edit operation records exist and pass Python/C++ validation.
- The handoff manifest is explicitly marked `interchange_format=obj_sidecar` with `metadata_risk=true`; OBJ is not treated as a complete native mesh metadata container.

## Current edge selection implementation

- Edge target mode is present in the UI.
- `NetEdgeTopology` builds stable edge descriptors from source submesh and source vertex pairs.
- Edge picking and edge overlays are local in the .NET viewport.
- Selection payloads include local edge ids, stable edge descriptors, and a topology generation so host/native code can reject stale edge selections after topology refreshes.

## Current host/native edit authority

- The .NET helper emits `select_request`, `stroke_*`, and `command_request` events.
- Python/C++ returns selection/preview updates.
- .NET resolves local vertex/face/edge/part picking and overlays immediately,
  then synchronizes that selection mirror with the host.
- Python/C++ intentionally remains authoritative for edit semantics, resident
  session state, validation, rebuild, and archive output.

## Production renderer status

- It is backed by a custom D3D11/Vortice material renderer, with WPF
  `Viewport3D` available only as a developer fallback.
- The first explicit swap chain, HLSL shaders, constant buffers, vertex/index buffers, sampler state, shader resource views, and render states now exist in `D3D11MaterialViewport`.
- The handoff package contains material semantics and resolved texture payloads.
  Native DDS upload is the production path; bitmap decode/conversion remains
  available for unsupported sources, WPF developer fallback, and mutable
  texture-region edits.
- The .NET project now depends on Vortice.Direct3D11, Vortice.DXGI, and Vortice.D3DCompiler.
- Classified skin, cloth, and hair now consume the native material-family
  evidence through a conservative nonmetal fallback: metalness is forced to
  zero, roughness has a family floor, dielectric specular is achromatic and
  capped, and native family depth-authority keeps source hue stable across
  camera angles. Full captured skin subsurface/wrinkle response is not claimed.
- Metallic reflections remain physically view-dependent, but the studio
  environment and chromaticity-preserving output keep source hue stable; hidden
  front/back/oblique captures gate both color drift and loss of dark albedo
  detail instead of forcing angle-invariant brightness.
- Original-reference direct materials are hydrated from native batch identity.
  Native secondary/prefab components are added as separate reference-only
  geometry and cannot become editable or export authority. Unresolved layer-only
  detail/damage/grime/dye/overlay inputs are retained for diagnostics instead of
  being misused as primary albedo.
- Remaining target work is game-capture/RenderDoc shader-family truth, blend
  ordering, full layer graphs, hair/fur anisotropy, captured skin response, and
  DDS families outside current 2D evidence.
- Embedded production mode now treats D3D11 as required. If D3D11 initialization fails, the helper reports `blocked_renderer_unavailable`; WPF/GDI fallback is allowed only through an explicit developer renderer fallback.
- Renderer status keeps `native_dds_parity=false` to avoid claiming game parity,
  while `dds_native_dxgi_upload`, upload mode, source/GPU formats, mip counts,
  color spaces, authority, and fallback reasons report the actual live path.

## Historical edge-overlay gap (resolved)

- The .NET viewport had no unique edge list, face-to-edge map, edge-to-face adjacency, hover edge, or selected-edge set.
- The .NET viewport sent selection intent to the host instead of resolving edge hits locally.
- No local edge overlay buffer/draw pass existed.

## Implemented repair approach

### Production repair

Implemented in this pass:

- Added local .NET `NetEdgeTopology` and `NetEdge` structures from OBJ triangle indices.
- Added local selected-edge and hover-edge state in `MeshViewport` beside the local vertex/face/source overlay mirrors.
- Implemented local edge hover/click picking from projected edge segments.
- Implemented Replace/Add/Subtract/Toggle edge selection behavior locally.
- Draw selected and hovered edges in the .NET viewport without waiting for host/native overlay state.
- Added `net_materials.json` to the Python handoff package with material slots, submesh bindings, texture channel names, and deterministic fallback names.
- Added `.NET` `NetMaterialSet` / `NetMaterialSlot` / `NetSubmeshMaterialBinding` parsing so renderer data now enters the .NET process before the GPU render core exists.
- Added resolved texture-channel handoff from mesh preview texture attributes where available.
- Added `.NET` `NetTextureSet` CPU image decoding for supported local preview image files and common DDS formats.
- Added a local affine textured-triangle draw path for decoded preview images as the software fallback.
- Added `D3D11MaterialViewport`, a Vortice/Direct3D11 material renderer with HWND swap chain, vertex/index buffers, constant buffer, texture SRVs, sampler state, and HLSL vertex/pixel shaders.
- Embedded `D3D11MaterialShaders.hlsl` as a .NET resource and copy-to-publish content so single-file/bundled helpers can compile shaders even when assembly locations are blank.
- Added WPF `Viewport3D` GPU material rendering through `WpfGpuMeshViewport`, hosted by WinForms `ElementHost`.
- Added WPF geometry normals from OBJ normals when present, falling back to computed face normals when needed.
- Added WPF emissive material support for decoded package-local emissive image inputs.
- Added WPF overlay drawing for local wire/X-Ray/selection edges, faces, and vertices above the material viewport.
- Added local vertex, face, and part click selection in .NET with Replace/Add/Subtract/Toggle operation support, visible/X-Ray picking behavior, and local WPF/GDI overlay updates.
- Added local vertex, face, edge, and part drag-rectangle selection with Replace/Add/Subtract/Toggle operation support, WPF selection-rectangle overlay, and GDI fallback rectangle drawing.
- Added local part adjacency inference from submesh bounds and shared/near vertices, enabling local Grow and Shrink for Part/Source selection modes.
- Added local selection preview helpers for vertex/face/edge/part modes, but mesh/session command buttons now forward Clear Selection, Select All, Invert, Grow, and Shrink to the host so `MeshService` remains authoritative.
- Added local selection snapshot payload on forwarded command requests so host/native command handling can receive the current .NET selection mirror, including source indices, edge pairs, stable edge descriptors, and topology generation.
- Added package-local texture copying into `package/textures/` for every resolved preview texture channel that exists on disk, so the .NET process no longer depends on unstable external preview paths during the edit session.
- Added DDS header verification and decoding for package-local DDS resources, including width, height, mip count, FourCC/DXGI format key, and decoded status where the header is valid.
- Added DX10/DXGI DDS mapping for common formats used by real assets: BC1/BC2/BC3/BC4/BC5, R8/RG8, RGBA8, and BGRA8/BGRX8.
- Updated PyInstaller packaging to bundle the full .NET WPF helper payload directory, not only `cdmw-mesh-dotnet-editor.exe`.
- Changed embedded Edit Mesh behavior so the .NET viewport starts automatically by default when the helper is available; `mesh_editor/use_embedded_dotnet_viewport=false` remains a developer fallback and the normal `.NET` button is hidden.
- Added immediate QProcess startup verification and stdout/stderr/error diagnostics so .NET launch failures report status instead of appearing to do nothing.
- Added renderer diagnostics to the ready/metrics protocol payload, including active backend, material count, texture-reference counts, package-local resource counts, decoded resources, DDS resource count, texture-load failures, explicit DDS status, and dynamically selected runtime capabilities.
- Added explicit D3D11 initialization probing, forced-failure test hook, runtime fallback escalation, hashed/versioned shader extraction folders, SRV caching, and explicit D3D11 unbind-before-dispose cleanup.
- Added shared `NetViewportCamera` projection/camera semantics for WinForms fallback projection, WPF camera setup, D3D11 shader constants, pointer payload matrices, picking, and overlay projection.
- Added D3D11 device-lost detection/reset handling for removed/reset/driver-internal errors, forced Present-failure injection, and device-removed reason reporting in renderer metrics.
- Replaced the embedded D3D11 GDI overlay composition path with D3D11 line/triangle overlay primitives drawn before swap-chain `Present` for wire, X-Ray marker, selected vertices, selected edges, hover edge, selected faces, selected source parts, and selection rectangle.
- Added explicit frame scheduling/metrics for present time, dirty-to-present latency, dropped frames, frame count, first-frame state, and idle versus active rendering status.
- Added release dirty-tree preflight through `scripts/release_preflight.py`; release packaging writes `build/release-change-inventory.json`, classifies untracked project source/docs under known repo roots, and blocks generated output or unclassified untracked source.
- Added material debug channel toggles and renderer status parity metadata for base, normal, roughness, metallic, emissive, specular, and final output.
- Kept host commit/import/material refresh unchanged.

### Remaining renderer work

- Add evidence before enabling cubemap, array, volume, or uncommon legacy-mask
  DDS families; current BC1-BC7 and common scalar/color formats are 2D-only.
- Implement captured Crimson layer graphs, hair/fur anisotropy, full skin
  subsurface/wrinkle response, and sorted alpha blending only when
  sidecar/runtime evidence proves them. Until then, tint-only cloth layers may
  preserve material class and color without reproducing their final pattern.
- Add a game/RenderDoc truth comparison; native/legacy preview remains a
  diagnostic baseline and is not claimed as exact game parity.
- Keep Python/C++ as parser, validation, rebuild, archive mutation, and final host-preview refresh authority.

## Target architecture gap

The production renderer now has native 2D DDS mip-chain upload, semantic
color-space views, linear GGX material shading, alpha/occlusion state, and
per-resource proof diagnostics in addition to the resident edit/overlay path.
Its generic studio-light fallback includes view-dependent environment response
for fully metallic surfaces, corrects the tangent frame on proven two-sided
backfaces, and applies display contrast around linear middle gray instead of a
linear `0.5` pivot that crushed dark texture detail. A hidden textured-metal
proof now rejects black front/back/oblique views and lost texture contrast.
Copy-on-write resident texture edits retain a full mutable mip chain and
regenerate its lower levels after every accepted boxed top-level upload.
The deterministic material-profile corpus adds OpenImageIO metadata and pixel
statistics to nine representative real/external profiles. OpenImageIO is an
offline parity instrument only; DirectXTex and D3D11 remain the runtime texture
and shader authorities.
WPF remains developer-only fallback. Real embedded PAC/material/edit validation
passes; game-specific family graphs and unsupported DDS dimensions remain the
explicit evidence boundary.

## Real archive proof

- The 2026-07-14 deterministic OpenImageIO corpus covered nine representative
  assets and 68 readable texture resources. Two independent builds matched at
  fingerprint
  `cc773955f67b931eab71ce01dc2b0f6fd3e3c28b7dac54e2507ecee7ca115c1c`.
  Evidence: `%TEMP%\cdmw-openimageio-material-corpus-final-20260714.json` and
  `%TEMP%\cdmw-openimageio-material-corpus-repeat-20260714.json`.
- The canonical real-archive .NET edit harness passed on 2026-07-14 against
  `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac`; the production
  Vortice viewport retained nonmetal skin presentation and every source archive
  content hash. Evidence:
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-material-final\evidence_report.json`.
- The release-scale hidden `.NET/Vortice` soak passed on 2026-07-14 with
  1,000,000 source vertices and 1,000 paced sparse updates. Its production
  shader captures kept a textured fully-metallic, two-sided surface readable
  from matched front/back and oblique views. Evidence:
  `%TEMP%\cdmw-dotnet-gpu-sparse-soak-material-final.json`.
- `scripts/codex_check.ps1 -Area mesh -GameRoot "C:\\games\\Steam\\steamapps\\common\\Crimson Desert"`
  passed on 2026-07-14 after the metallic-readability pass. Both resident
  texture strokes regenerated a 12-level mutable mip chain matching the native
  source count; topology/undo/redo/export settled without a reload or process
  restart, and every PAMT/PAZ fingerprint remained unchanged. Evidence:
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-8d3848e45e974221a6f14aaf72560ca4\evidence_report.json`.
- `scripts/codex_check.ps1 -Area mesh -GameRoot "C:\\games\\Steam\\steamapps\\common\\Crimson Desert"`
  passed on 2026-07-13 after the material-fidelity pass. All three canonical
  DDS resources used native BC1 sRGB views with 11-12 GPU mips and no fallback;
  the resident package/process/HWND contract and every PAMT/PAZ fingerprint
  remained unchanged. Evidence:
  `%TEMP%\cdmw-real-archive-mesh-editor-dotnet-1d5a55496ece49ff839d90b62f796823\evidence_report.json`.
- `scripts/codex_check.ps1 -Area mesh -GameRoot "C:\\games\\Steam\\steamapps\\common\\Crimson Desert"` passed on 2026-07-10.
- Proof scenario: `real-archive-mesh-editor-dotnet-edit-smoke`.
- Proof source path: `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac`.
- Result: `ok: true`; `.NET/Vortice` backend `d3d11_vortice_shader`, native edit backend `cdmw_mesh_core_0.1`, three real archive DDS bindings, selected-only geometry, before/after/diff captures, 1.214 ms handler p95, 101.14 ms maximum heartbeat gap, and unchanged PAMT/PAZ hashes.

Legacy `real-archive-mesh-editor-d3d11-*` scenarios remain compatibility-only and are not accepted as the user-facing renderer proof.
