# Changelog

All notable changes to this project should be documented in this file.

The format is intentionally simple:

- `Added` for new features
- `Changed` for behavior or workflow changes
- `Fixed` for bug fixes
- `Docs` for README, guide, or release-note changes

## [Unreleased]

### Added
- Added per-format decode progress to `schemas/archive_content_capabilities.v1.json`, so the answer to "can CDMW read this, can it write it, and what is left" is data rather than folklore. Every one of the 108 formats now carries where it came from (`origin`), how far it is read (`decode`), how far it can be written (`write`), what closing the gap would unlock (`priority`), a pointer to the module or corpus gate that backs the claim (`evidence`), and what is still unmodelled (`remaining`). `tools/report_format_decode_progress.py` validates the entries, recomputes the manifest's own `progress` summary, and regenerates `docs/features/format-decode-progress.md`; `tests/test_format_decode_progress.py` fails if either derived artefact drifts from the entries. Coverage is a weighted mean of the per-entry statuses rather than a file count, and the headline is reported over the 58 engine formats — 47.2% read, 25.0% write — because the 47 public formats arrive already understood and would otherwise flatter the number. Writing the entries surfaced two overclaims that the evidence rule caught: `.meshinfo` was carrying a full-decode claim over what is really a reference and field-name scrape with candidate integers, and `.pab` was carrying one despite unknown and truncated variants falling back to a best-effort scan. Both are corrected, which is why the read figure moved down.
- Added a `Carry:` control to the Placement & Animation Studio, which changes where a weapon hangs and brings its animations with it. Picking a carry position re-routes the part, moves its child socket so the item keeps the right orientation, and filters the clip browser to the draws and sheathes that start from there. Which clips those are is measured, not looked up: the action charts do name sockets and clips together, but a chart names hundreds of clips at once, so `RHand_Socket` "matches" 4,989 of them. Instead each draw is played against the rig and the hands are watched. Nearest-socket scoring does not work either — in a back draw the idle hand hangs by the hip, so the closest hand-socket pair in the clip belongs to the hand doing nothing; what separates them is how far a hand *closes* on a socket over the clip. Classification is to a body zone rather than an exact socket, because the five upper-back sockets sit within 0.06 m of each other (two of them at the same point) and the thigh sockets are nearer the hip than the two hip sockets are to each other. Of 248 draw and sheathe clips for `1_phm`, 228 are classified, split 121 hip to 107 back.
- Added a Help tab to the Studio, and put the tool's vocabulary in plain English. Socket, child socket, part, carry, stowed and held, draw and sheathe, attach point — each gets a sentence saying what it is and a second saying why it matters when editing, plus a five-step walkthrough of moving a weapon. The same definitions feed the tooltips, so the two cannot drift; a test fails if the walkthrough names a button that no longer exists.

### Changed
- Corrected the maturity the Archive Browser reports for formats whose decoders had moved on without the manifest following. `.paa` and `.prefab` were still labelled `heuristic` while carrying a documented container spec with a corpus gate and a structural decoder respectively; both now read `proven`. `.paac` was missing from the manifest altogether, so action charts fell through to "No format-specific decoder is registered" despite the Placement Studio indexing and retargeting their strings; it is now a registered structured format and gets section-aware analysis instead of a generic binary dump.
- Held a 60 fps floor in the Studio viewport with meshes and Solid on, including during playback. While the playhead runs or the camera is being dragged, only the largest 1,500 projected triangles are filled — on the body those carry 94% of the filled area, and the ones dropped are the dense clusters around fingers and seams where neighbours already overlap. Full detail returns the moment motion stops. At 1900x1000 a playing frame costs 12.8 ms with the bare body and 14.8 ms at three times the geometry, so wearing armour does not cross the floor.
- Cached the Studio's wearables index on disk, keyed by each package table's size and modification time. Building it parses all 33 tables and takes about 4.4 s, and one of them (0009, 419,660 entries) is a single uninterruptible 1.2-second call the UI thread cannot paint through — which showed up as a 1.6 s stall a few seconds after opening. Reloading takes 0.05 s, so that stall now happens once per game install rather than once per launch.
- Reworded the Studio's controls and messages for people who did not write the file format. `clipping: 12/840 weapon vertices inside the body (1.4%), deepest 0.0043` now reads `sunk 0.4 cm into the body (1.4% of the item) — nudge it outward`; `Measure` is `Check fit`, `LOD` is `Distant versions`, `Translate` is `Nudge`, `Revert socket` is `Undo my changes to this point`, and the `stowed`/`held` dropdown says `put away` and `in hand`. The status line opens with what to do rather than with a resolved-row count.
- Made the Studio's room stop moving. The four walls were ranked by distance from the camera each frame and the two farthest drawn, shaded by that rank — so orbiting reshuffled the ranking and walls appeared, vanished and swapped shade as the camera turned. A wall is now drawn when the camera is on its inward side, which is a property of the wall, and shaded by which wall it is. It changes only when the camera actually crosses its plane.
- Split the Studio header into two rows and stopped its combo boxes sizing to their longest entry. Between them the part rows and the clipping message demanded a 4,010 px window before anything else was laid out, so on a real monitor every control was jammed against its neighbours; the window minimum is now 1,482 px.

### Added
- Added a structural `.prefab` decoder (`cdmw/core/prefab_binary.py`). A prefab is self-describing: it carries a flat table of type definitions naming every member, its declared type and its byte size, followed by a heap of pointer-addressed object records. The decoder parses that grammar rather than scavenging strings, so it recovers each scene object, its component type, which fields are actually set, and every resource path with the exact byte span that holds it. Header parsing covers 12,000/12,000 sampled archive prefabs including format versions 3 and 4 and schema revisions 13 to 15; the heap walk completes on ~93% of single-component-type files and degrades to a partial result, never a crash, on the rest.
- Added length-changing resource path edits (`cdmw/core/prefab_binary_edit.py`). The blob stores absolute file offsets, so resizing a string moves everything after it; the rewriter relocates every pointer and pointee length field and updates the data header. Pointers are identified by an exact property — a u32 at blob-relative `k` is a pointer if and only if it stores `blobOffset + k + 4` — rather than by scanning for values that happen to match a string offset. Verified by round-tripping 1,500 real prefabs with both longer and shorter replacements, re-decoding each and requiring the structural walk to still complete.
- Added a prefab glossary (`cdmw/domain/archives/prefab_glossary.py`) that turns declared names into plain English. `_shrinkMaskDistance` reads as "Shrink distance", `_skinnedMeshFile` as "Mesh", and each carries a line saying what it controls, so a modder can tell which fields are worth touching without knowing the engine's vocabulary. Entries were chosen by how often a field is actually set across the shipped prefabs rather than how often it is declared, and now cover 98.8% of set-field occurrences. Descriptions are inferred from each field's name and declared type, so where a name does not support a confident reading the entry carries a label only. Unknown fields fall back to de-camel-casing rather than disappearing, and engine typos are corrected in the label while the declared name stays on hover.
- Added the Prefab Inspector (Archive Browser context menu, "Open Prefab Inspector..."). One tab lists the prefab's objects with their component types, asset paths and set fields; the other lists every field the prefab declares with its type, byte size and a plain-English description of what it holds. Every value is labelled with the field it came from rather than guessed from its file extension, and the field list defaults to just the fields this prefab actually sets, since a prefab declares far more than it uses. Asset paths are editable in place and replacements are not restricted to the original byte length. Edited rows are highlighted, a running summary says how many changes are pending, and Undo puts everything back to what the file actually holds. A replacement whose file kind does not match the field it is going into is flagged -- swapping a model reference for a texture is the mistake most likely to slip through -- but flagged as a warning rather than a block, since a modder may be retargeting to an asset they are about to author. Where the archives can answer, the inspector now also checks that the replacement exists: a "Choose file..." picker lists the real archive paths of the same kind, seeded to the current file's folder so its siblings are the first thing you see, and a hand-typed path that no file matches is called out. The index is built off the UI thread before the dialog opens and cached per package root and extension (`cdmw/core/prefab_asset_catalog.py`); when no index is available the inspector claims nothing about existence rather than raising a false alarm.
- Added companion-file awareness to the Prefab Inspector (`cdmw/domain/archives/prefab_companions.py`). A prefab references only a mesh, but the engine resolves that mesh's material and physics from parallel role directories -- `character/model/.../x.pac` implies `character/modelproperty/.../x.pac_xml` and `character/bin__/meshphysics/.../x.hkx` -- so retargeting a mesh silently swaps those too. Applying a change now reports where material and physics will come from, and a replacement mesh that lacks a companion of its own is flagged before the edit is written. Measured over the shipped archives, 12,961 of 12,962 `.pac` files sit under a `/model/` directory; of those 100% have the physics companion and 99.1% the material one. When a prefab cannot be fully decoded the banner says so and editing is disabled, so an edit is never written to a file that is only partly understood.

## [0.11.0-alpha.1] - 2026-07-27

### Added
- Added a standalone out-of-process archive backend and made it the default for the Full Archive Browser. The catalogue now lives in a separate .NET worker (`tools/dotnet_archive_backend`) over an independent native full-archive core, talking to the app across a frozen protocol contract. It brings a resident process client, a typed catalogue service, an archive-derived name index built inside the worker, paged child enumeration, folder filters backed by the worker's own hierarchy, a bounded remote browser model that never materialises the whole archive in the UI process, selection resolved by entry identity rather than row position, and idempotent query recovery so a worker crash is retried instead of ending the session. `CDMW_ARCHIVE_BACKEND` selects `legacy` or `shadow` (which runs both and compares sort and override parity) for diagnosis; unset means v2.
- Migrated every archive consumer onto that backend. Text Search, Replace Assistant lookups, Research, raw exports, related exports, Associated Assets, attachment workflows, in-game mesh swap dependencies, archive sidecars, selected-preview materialisation, and streamed preview dependency preparation all run through bounded worker contexts instead of loading the catalogue in-process.
- Added a headless full-archive integration probe, a headless archive cache probe entry point, and a developer archive backend selector, so the standalone worker can be exercised and compared without launching the app.
- Ported Item Finder from CDMW Lite into CDMW Full, with lazy finder construction, item-icon preload, and double-click on a result loading the selection into the browser.
- Added a structured PAC XML editor for material and runtime XML: a sortable column view, bundled graph connections with readability passes, and paired source and window views. The skeleton preview is hidden by default.
- Added a shared resident .NET preview host. Archive preview, Model Library, and Mesh Editor now draw from one long-lived renderer process instead of each owning its own, and preview packages are canonical across all three.
- Added the Edit Mesh tool rail and made it the default Edit Mesh layout, with Classic kept as the fallback. Panels are resizable, the rail carries its own dock width, and the tool pages cover topology, transform, and colour work.
- Added per-part colour authoring. A recolour operator sits alongside the existing multiply tint: multiply can only darken or shift a texture, while recolour repaints toward the chosen hue and preserves the source luminance. One evaluator feeds both the live preview and the baked DDS, so the preview is the bake. The Builder inspector gains a tint swatch and picker, a recolour swatch with a repaint slider, a Glow row that assigns the emissive role itself, and Reset Colour; Edit Mesh gains a matching Colour tool-rail page over a `part_material_edit_request` lane, where Python stays the authority and the child applies locally only for immediate feedback.
- Added wire-first Mesh Editor preview modes, configurable mesh overlay colours, configurable mesh topology sizing, and persistent gizmo appearance controls (moved into Preview Settings).
- Added a persisted Grid toggle to the Mesh view control row, host-owned and fanned out to every renderer pane so it survives package swaps and side-by-side layouts.
- Added a `renderer_status_request` protocol message (`renderer_status_request_v1`) so a host can sample the renderer's full state — viewport identity, texture resource and decode counters, and the presentation block — at any moment rather than only on the events that happen to carry a full status.
- Added connectivity reporting to mesh health. Alongside invalid, degenerate, duplicate, and loose geometry — all of which welding and degenerate-face removal can fix — the preflight report now carries `boundary_edges`, `non_manifold_edges`, `inconsistent_winding_edges`, and `bowtie_vertices`. Bowties are found by union-find over per-vertex face fans, so a vertex joining two disjoint fans is caught even when each fan is well formed. Boundary edges are recorded but deliberately do not warn, because cloth, hair cards, and cut-out geometry are legitimately open. The report stays preflight-only and never mutates the mesh.
- Added resident procedural morph generation and garment refit.
- Added a native `morph_generate_fields` command to the C++ mesh core, porting procedural morph field generation from Python. Measured on a 145-slider body it computes in 11 ms against Python's 943 ms, matching it to 3.3e-17 m across 93,690 deltas. Not yet on the production path: the JSON payload transport, not the maths, now dominates that call.
- Added a body-region atlas panel (`cdmw/ui/mesh_editor/body_region_atlas_panel.py`) listing a body's regions grouped and colour-coded, with tick-to-select and a Generate Sliders action. Its presentation model (`cdmw/domain/mesh/body_region_atlas.py`) is Qt-free and assigns each region a stable colour so lists, overlays, and exports agree.
- Added body-region decomposition (`cdmw/modding/mesh_region_decompose.py`): point at a vanilla body and a modded one and get per-region sliders instead of one all-or-nothing morph, so an existing body mod becomes editable. Every region at 100% rebuilds the modded body exactly.
- Added body-region morph sliders (`cdmw/domain/mesh/body_region_sliders.py`): a template set instantiated against every segmented region, yielding 145 ready sliders across 29 regions on a vanilla body, each with the region's own vertices, pivot, and bone axis. Adds a `radius` morph rule for proportional girth, which `volume`'s fixed-distance push cannot express.
- Added skin-weight-driven body-region segmentation (`cdmw/domain/mesh/body_regions.py`), which turns a skinned body's bone weights and skeleton bone names into named regions with per-vertex weights, so morph sliders can target a body part without a hand-painted vertex selection. Region weight per vertex is the sum of its normalized bone weights over the bones a region claims, so regions keep the rig's own falloff and form a partition of unity; edges are then feathered over a geodesic band in metres (`cdmw/domain/mesh/body_region_falloff.py`) rather than adjacency rings, so the same band covers the same surface at any mesh density. Every race resolves 27-29 regions with 0.00% unclaimed skin weight and 97-100% left/right symmetry. Inspect a body with `python -m tools.dump_body_region_map`.
- Added native PAT asset preview and broader native media parity, so PAT and companion media decode through the same native path as the rest of archive preview.
- Added multisampled resolve to the .NET preview and generated mip chains for .NET bitmap textures, so previews no longer alias on edges or shimmer at distance.
- Added prefab JSON corpus parsing and import, with a reporting harness (`tools/report_prefab_json_import_corpus.py`) and `docs/features/prefab-json-import.md`.
- Added region selection to Icon Creator and fixed generated icon framing.
- Added a resident mesh visual audit harness for Mesh Editor material parity: a frozen 500-PAC selection with coverage-aware asset choice, reproducible .NET refresh, per-asset package sharing, bounded preparation that resumes between batches without losing coverage, deferred sealing, and review tooling over the recorded evidence.
- Added a release gate that proves the packaged build's bundled helpers actually resolve. The startup smoke records how each helper marked bundled resolved (currently `cdmw_mesh_core` and `openimageio`) as key, status, source, and path, and `verify_packaged_startup.ps1` fails the build when any of them is unavailable — or when the section is missing or empty, so a build that quietly stops reporting cannot pass as a build with nothing to report. The snapshot is path lookups only; no helper is executed.
- Added a packaging guard that refuses to ship a stale Mesh Editor renderer. PyInstaller takes the renderer from the staging tree `dotnet publish` writes, and the publish was only required on the release profile, so a skipped or failed publish silently shipped the previous helper — a three-day-old shader reached a build that way. The staged shader is now hashed against the authoritative one before PyInstaller runs, on every profile.

### Changed
- Split the application into owned modules, completing the restructure: startup and the main window stay thin while feature UI, services, domain rules, and workers moved into modules that own them, with compatibility wrappers preserving public imports.
- Moved CDMW Lite (Archive Lite) into its own repository. The Python-free Archive Lite app, its standalone executable, portable data and cache startup, workspace persistence, native model previews, Item Finder, and HKX structure previews were all developed here and then split out; what remains in this repository is CDMW Full, plus the archive content decoding both now share.
- Unified Full and Lite archive content decoding so the two apps read the same bytes the same way, with the decoder parity written down in `docs/features/archive-decoder-parity-and-lite-item-finder.md`.
- Retired the previous preview renderer and moved every model preview onto the resident Vortice-based .NET host. Archive previews route through canonical preview packages, the packaged helper carries the complete preview capability set, and the retirement contracts, ownership boundaries, and acceptance evidence are pinned by tests.
- Replaced the external `texconv` DDS converter with the native texture backend on the normal preview, staging, and rebuild paths.
- Retargeted the .NET mesh editor from `net8.0-windows` to `net10.0-windows`, moving every path that resolves the helper by framework directory with it, and slimmed the release bundle: .NET debug symbols from the mesh editor tree, the duplicate `D3DCompiler_47_cor3.dll` PyInstaller hoists to the bundle root, the Qt message catalogues the app can never read because it installs no `QTranslator`, and the Winamp/XMPlay vgmstream player plugins beside the CLI that actually decodes audio are all gone.
- Kept preview-core caches resident between jobs instead of releasing them at the end of every job. The pamt trim kept only the last-touched index, so a job ending on a cross-package lookup evicted the primary index and the next job reloaded it, and any basename missing from the primary index re-walked all 33 `.pamt` indexes in the game root. Caches are now bounded rather than cleared — pamt indexes evict by recency against a byte budget, technique/graph/sidecar/pathc caches trim to counts, and a resident scan cache remembers full package-root basename lookups including negative results, stamped against the on-disk `.pamt` set. Warm textured jobs go from 1148 ms to ~90 ms and warm geometry jobs from 1067 ms to ~21 ms against the real archives. Keeping every index resident was measured too and rejected: 33 real indexes reach ~690 MB and trip the 512 MB private-bytes recycle guard, which recycles the service after every job and makes each one cold again. The helper provenance SHA-256 is also cached by stat and seeded from the background prewarm, because the packaged helper is ~167 MB and was hashed twice per launch on the UI thread. Per-phase native timings are reported so a slow preview says where the time went.
- Archive Browser file columns now size themselves to their content the first time a scan renders, instead of opening at fixed widths that left Name several hundred pixels wider than the longest filename. The fit samples the rows the model has loaded rather than measuring every entry, and it stands down permanently once you drag a column divider or reorder the header - your layout is restored on the next launch and never refitted. "Reset Columns" in the header context menu hands control back to the automatic fit.
- Moved the Full Archive Browser's derived dependency index off the archive-open path. It backs facets and basename lookups, which nothing on the way to the first page of results reads, so it is now built in the background while browsing is already usable: on a 1,674,781-entry archive the first page arrives in 1.4s cold instead of 4.6s (-71%) and 1.4s instead of 4.0s on refresh (-64%), with everything including facets ready in 3.1s instead of 4.6s. Warm opens are untouched, because an already published index is still opened inline. A derived index that cannot be written no longer fails the whole archive open: browsing stays available, the failure reaches the request that needed the index, and the next request retries the build. Builds of one generation are serialised across sessions, since overlapping sessions each hold their own mapping of the published file.
- Cut Full Archive Browser cache builds by a further 29% cold and 37% on refresh (4.8s to 3.5s and 4.0s to 2.6s on a 1,674,781-entry archive, medians of four interleaved runs) by sorting a permutation of the index instead of the entries themselves under a parallel sort, ranking each entry source once rather than comparing filesystem paths per comparison, interning source paths by source identity, memoizing override priority per source, claiming PAMTs largest-first across a work-stealing pool, and reporting progress on a coarser interval so a slow reader cannot meter the build. Warm opens are unchanged at 48ms, and the published `archive.ali` and `archive.adi` are byte-for-byte identical to those the previous build produced.
- Reduced Full Archive Browser cold cache builds and explicit refreshes by sharing per-PAMT source metadata, parsing PAMTs through a bounded deterministic worker window, reusing normalized source paths, and avoiding redundant case folding during the stable native sort; cache bytes and warm-load behavior remain compatible.
- Changed Full CDMW Item Finder startup so its catalogue, restored first page, and icon thumbnails warm after archive publication instead of waiting for the first Item Finder click; visible icons preempt the bounded low-priority background queue.
- Removed the standalone Material Finder from CDMW Full while retaining Item Finder, including its material-tag search and filtering.
- Broadened Archive Browser item-name recovery across shifted ItemInfo layouts, larger prefab-reference lists, semantic StringInfo icon links, and derived icon/texture/sidecar filenames; related Name Evidence cells now show the recovered item name without a redundant `Name hint:` prefix.
- Merged Archive Browser's Exact Name and Name Evidence columns into one Item Name column. Direct names take priority, inferred names fill the same column, and the tooltip retains the exact-versus-related confidence distinction.
- Stopped writing the unread `archive/model_high_quality_textures` settings alias, which duplicated `archive/model_high_quality` in the local config and in every exported profile.
- Bundled OpenImageIO with release builds. `oiiotool` and its runtime DLLs now ship under `openimageio/`, with the upstream Apache-2.0 licence and third-party notices beside them, and a release build fails closed if the payload is missing. OpenImageIO previously resolved out of the developer's virtualenv, so source-image metadata, conversion, and Mesh Editor image diffs worked when running from source and silently did nothing in the packaged app. A configured path or `CDMW_OIIO_BIN` still overrides the bundled copy. The bundle also drops the second copy of the OpenImageIO DLL closure that PyInstaller collects by following `oiiotool`'s imports, which nothing can load and which cost 15 MB.
- Changed Model Library's inline preview to draw from the resident host alone. It kept a hidden `NativePreviewPanel` that no longer drew anything and existed only to hold render settings, carrying software-preview decimation limits of 500 faces and 1200 vertices per submesh that applied whenever the backend was not the .NET path. The panel is gone, the settings are plain `ModelPreviewRenderSettings` the tab owns, and preparation always uses the .NET geometry budget.
- Changed archive mesh preview framing: the opening camera is overhead, body framing and package-change centring were corrected, .NET zoom now matches archive preview, and overlays scale with the fitted zoom. Mesh wire overlay contrast was raised and the wire draws black by default.
- Archive prefab parts now default to hidden and archive preview extras are opt-in, so opening a prefab shows the asset you selected rather than every companion part at once.
- Reorganised the Full runtime caches and warmed item icons at startup, so repeat sessions do less work and icon-bearing views are populated before they are opened.
- Changed application shutdown to a single asynchronous pass: one click begins teardown, the deferred work is coordinated rather than racing, and the UI does not block while helpers stop.
- Coalesced Material Authority manual slider work behind a 150 ms timer. Every tick previously persisted the whole profile and cancelled and restarted the exact DDS resolve, so a drag could not settle and the sync status thrashed. Build Mod flushes the timer so a build cannot read the previous profile; Apply, Reset, and preset load cancel it because they persist everything themselves.
- Regrouped the Mesh Editor control row with separators (preview mode | grid/gizmo/part pick/edit mesh | mesh view/.NET view | preview settings), and removed "Original locked" from it — it was permanently checked and permanently disabled, so it could only ever report the one state the preview already guarantees.
- Both Mesh View controls are now built from one option table. The tool rail offered six modes defaulting to Faces while the Builder offered eight defaulting to Faces + Wire, and only the Textured/Faces outcomes were cross-synced; the rail now carries a compact label set with the full label as each item's tooltip. Solid + Wire samples the material, so it takes the texture-resolve route and falls back to Faces + Wire rather than dropping the wire overlay, matching the .NET viewport.
- Raised the support-map decode cap from 192 to 256. The binding cap was the synthesis preview profile, which caps the DDS-to-PNG decode itself, so raising the combiner's own caps alone could have no effect — every `_sp` decoded to exactly 192x192 while its `_n` sibling was 256. Recovers ~15% of per-layer roughness variation; 46 of 68 sources are natively 256 or smaller, so raising further buys little for much more time.
- Dropped Assimp and DirectXMesh from the authoring helper registry, the fidelity preflight adapters, and the integrations table. Neither was ever on a code path: Assimp was an import comparator nothing called, and DirectXMesh was a placeholder for validation now done in pure Python.

### Docs
- Corrected in-app Help, Documentation, and About references that pointed at a non-existent top-level `Documentation` menu and at a `Settings > Archive Browser Performance` page; they now name `Help > Documentation`, `Settings > Performance`, and `Settings > Paths > Archive Locations` in English, Spanish, and German.
- Updated the Documentation topics for Profile & Settings and Window & Layout to list the seven Settings pages that exist today and all twelve detachable tools, including the `Show <tool>` entries in the Window menu.
- Added `docs/features/mesh-editor-visual-material-parity-audit.md`, recording the Mesh Editor material parity programme across the 30-, 72-, 90-, 120-, and frozen 500-PAC corpora, the metallic parity audit, and the final acceptance review — including which claims the evidence does and does not support.
- Added `docs/features/archive-decoder-parity-and-lite-item-finder.md`, covering the decoder parity between Full and Lite and the Item Finder plan that followed from it.
- Added `docs/features/prefab-json-import.md` and `docs/features/mesh-editor-skeleton-discovery.md`.
- Documented Edit Mesh splitter behaviour and the Edit Mesh lifecycle safeguards, plus Full archive and shutdown ownership, and recorded the CDMW Lite repository split.
- Documented lazy archive preview prefabs, so the deferred-companion behaviour is written down beside the code that defers it.
- Rewrote the agent instructions around blast radius: this codebase resolves most cross-module wiring at runtime, so the change-safety loop now names Qt signal and slot names, `objectName`/`findChild` lookups, `getattr`/`hasattr` probes, settings and manifest keys, and compatibility re-export shims as consumers static checks will not find. `AGENTS.md` also now requires a changelog entry in the same commit as any user-visible change, and a version bump to be proposed rather than taken.
- Updated release version references from `0.10.0-alpha.2` to `0.11.0-alpha.1` in the README, the security policy, and app version metadata.

### Fixed
- Fixed the embedded .NET mesh editor and 3D preview flashing on screen while they start. The helper's window was created as a borderless top-level window at screen (0, 0) and only reparented into the workbench pane once startup finished, so opening Mesh Editor or Edit Mesh put a stray window in the corner of the monitor and let you watch WinForms assemble the editor inside it a panel at a time. The window is now created as a child of the host pane from the outset and stays hidden until its control tree is realised and it is verified in the host, so the workbench's own "starting" panel covers the whole stretch and the editor appears complete in one step. Nothing is reparented after the fact, which also removes a cross-process `SetParent` that could fail with Win32 5023.
- Fixed the Mesh view control sitting on "Solid (Textured)" while the viewport stayed grey. Picking that mode parks the viewport on the untextured fallback and waits for a resident material acknowledgement, but the resolver it calls returned silently whenever the textures were already marked loaded, so no material update was sent, no acknowledgement arrived, and the pending flag was never cleared. The resolver now reports what it did (started / in flight / already loaded / unavailable) and republishes resolved materials; the request completes when the helper already holds them, fails with a status message when there are none, and otherwise arms a 20-second watchdog so the control can never report a mode the viewport is not in.
- Fixed the Edit Mesh grid disappearing. Each renderer pane draws from its own presentation context but only the active one was written back, so in side-by-side the two drifted and a pane could keep or lose a grid nobody asked it to; separately, replacing the resident package reseeded grid visibility from the incoming package's `dotnet_scene.json`, and the two package builders disagree about the default. Grid and gizmo visibility are now host-owned, fanned out to every context, and preserved across package swaps.
- Fixed the Edit Mesh tool rail collapsing to the Classic panel widths. An embedded scene update arriving with mesh edit already on re-ran the reveal path, which uncollapsed the flanks against the classic saved widths while the layout switch early-returned as already active, dropping the rail's 340 px property column to the classic 256 px minimum and the scene inspector to 360, where the tool pages no longer fit. Both paths now re-assert the active layout's own dock width. Entering and leaving mesh edit never reproduced this; only the redundant same-mode update did.
- Fixed Edit Mesh button captions painting over their neighbours - "Bind Selected Parts" ran under "Clear Refit" even at the full rail width - by reflowing equal-percent rows onto extra rows when a column cannot seat them side by side, and wrapping the Morph diagnostic at the column width instead of a hardcoded 460 px. The status footer is one line with the full text in its tooltip, which gives that height back to the viewport and tool columns.
- Fixed exported OBJ material libraries losing every texture binding. `export_archive_mesh` still passed the leading `texconv_path` argument that the native texture backend change removed, so the call raised `TypeError`, the texture manifest came back empty, and every `map_Kd` kept the bare placeholder name. The textures were copied into `referenced_files/` but never bound, so an OBJ opened untextured with its textures sitting right beside it. Every export from the Archive Browser took this path. The shared 120-line `except` that covered the preview rebuild, the MTL rebinding, and the manifest write now names the stage that failed, which is why a broken texture pipeline read as a manifest warning for ten days.
- Fixed packed roughness/metal maps binding to the specular slot instead of the material slot. `SkinnedMeshStandard` writes its packed map to `_materialTexture` but still names the file `_sp.dds`, and the role classifier matched the file suffix before the authored parameter, so the material slot resolved to null and the response fell through to the legacy specular/gloss path - metal rendered flat in Archive Browser preview. The authored parameter now outranks the suffix, keeping the skin carve-out that reads `_sp.dds` as specular. The Mesh Editor package hid this because it synthesizes separate channel files; only the archive package, which hands the renderer raw archive DDS, stranded the map.
- Fixed the base colour of layered PAC materials coming from the wrong textures. `_grimeDiffuseTexture{R,G,B}` are the three colour layers `_colorBlendingMaskTexture` selects, so they are the surface colour, while `_detailDiffuseMask*` are overlays; the visible-layer base fallback ranked detail above grime, handing the base slot to an overlay whenever both were declared. Separately the layer palette preferred `_scratchTintColor*` - the low-alpha wear accent - over the authored `_tintColor*`, and one chromatic scratch channel was enough to keep all three, so a sword blade rendered near-white and its grip yellow instead of the authored gold and brown. Both selectors now prefer the authored tint and fall back to scratch only where a channel declares none.
- Fixed layer dyes being resolved by substring. The tint lookup matched candidate names with a substring helper while the candidate list encodes a precedence, and `tintcolorr` is a substring of `scratchtintcolorr`, so any layer asking for its primary dye silently received the scratch dye whenever both were declared - on one real axe that swapped a neutral tint for a cyan one and rendered the steel head blue-teal.
- Fixed `_sp` channels being decoded the same way for every shader family. Disassembling the shipped shader cache shows R is never sampled outside skin and the layout differs per family: Standard/Cloth/Fur sample G roughness and B metalness, Skin adds R subsurface, and Hair samples G alone with no metal channel at all. Feeding R into ambient occlusion was a live bug rather than a stale comment - `_sp` files are BC1 and plenty ship R authored flat dark, so those assets rendered fully occluded. Skin roughness also read G inverted, the hair strand sheen constant was dead code that the affine table short-circuited past, and `SkinnedMeshFur` was classified as hair, which discarded its metal channel.
- Fixed preview colour and material response being driven by category guesses instead of the source maps. The dominant `_sp` decode read three of four channels wrongly - R is occlusion, so `1.0 - r * 0.22` darkened every surface by a fifth; A is an opaque control value, so `a * 0.52` gave every texel 0.64 reflectance and was the main source of shine on cloth and leather; and a `* 0.58` factor capped a fully metal texel at 0.51. Layer maps carry mask coverage in alpha and are composited in priority order, but coverage was lost and the layers were weight-averaged, pinning every roughness map near a constant 0.58. In the renderer, source normals are BC5 so the sampled blue channel is always 0 and every normal pointed into the surface - Z is now rebuilt from XY; reflectance comes from the metal fraction rather than a specular map, so dielectrics cannot inherit a metallic sheen; and category caps and floors apply only where no map is bound, so a cloth family keeps the authored per-texel metal that garments carry as studs and trim. Verified with the GPU parity report at 38/38 and by rendering 43 real weapon and armour assets plus the 15-asset material regression corpus.
- Fixed a flat specular floor on the second most used decode path. `standard_v2_detail` multiplied its specular by an alpha that is opaque on the detail mask, making it a flat `+0.20` on every texel - a guaranteed 0.28 floor, which is why cloth and leather read as if they had been waxed. The term is gone and the floor returns to the plain dielectric 0.04. The hair sheen was likewise a constant pretending to be data-driven, built from a variance that saturated so every shipped hair asset resolved to the same value; it is now one named constant with its reason recorded.
- Fixed the recolour operator being damped to roughly 5% on metal-classified submeshes - most weapons and armour - so a saturated colour rendered as a wash while the CPU bake repainted fully. The damping is now gated on whether a base tint was authored, making the authored path identical to the bake. Measured on a real sword blade: chroma 4.6 damped against 15.9 authored.
- Fixed glow colour and strength refusing any selection other than a single part, which left multi-part glow selections unauthorable with no way forward. A selection is now editable whenever every part in it carries the glow role, and an edit reaches all of them; parts without the role are skipped rather than promoted. Assigning the Glow role to a multi-part selection previously landed on the current part only, which disabled the glow controls on the very selection the user had just made. The reason text now says which case blocks editing.
- Fixed brush and move strokes stopping the resident editor mid-stroke and reading as a helper crash. Each sampled mouse move sent one protocol message carrying a projection matrix per editable submesh, so on a multi-part model that burst arrived in a single host read and tripped the input-buffer guard. The guard now drains complete messages first and bounds only the unterminated residue, and the helper coalesces intermediate samples at 30 ms while carrying the older drag start forward, so no pointer motion is dropped. A gesture could also outlive its mouse-up, because focus moves raised from `MouseDown` cancelled the render surface capture; capture is re-asserted after the handlers run, only stroke tools may open a stroke, the tool is latched at stroke begin, and the stroke closes on lost focus, tool change, or the first move without the button held.
- Fixed Edit Mesh tool rail buttons revealing a page without activating the tool they name, made tool buttons idempotent, pointed Delete and Duplicate at the current selection target from the Topology page, and extended the transform nudges to all three axes rather than X alone.
- Fixed Edit Mesh preview controls discarding input. Mesh View was routed through an unconditional early return while Edit Mesh was active and neither it nor Preview Mode was ever disabled, so you could open both, pick a mode, and get nothing: Mesh View displayed a mode the viewport was never put into and every Preview Mode option resolved to `replacement_only`. Mesh View now reaches the resident .NET viewport during editing, and Preview Mode disables itself with the reason. The Height scale control read as dead because effective height is `min(max(scale, edge relief), cap)` and the shipped profiles ship both at 0.0; it now reports the zero cap instead of silently doing nothing. Apply/Reset and the change status also moved below the roughly 33 controls they act on, rather than sitting above them.
- Fixed Edit Mesh drawing its layout transitions a piece at a time. Entering Edit Mesh attaches deferred authoring panels and re-parents every tool section while the window is on screen, and `SuspendLayout` defers measurement but not painting, so each step was drawn as it landed - group boxes as bare outlines before their captions, labels missing, combo text clipped to a not-yet-final width, a drop-down painting detached from its owner - and nothing forced a full repaint afterwards, so a child could stay visually stale. A refcounted `WM_SETREDRAW` batch now spans the deferred panel build and both layout activations, performs one settled layout, and repaints the whole subtree on release.
- Fixed the Builder flashing stray windows on open. Advanced Routing, the original-texture preview group, and the source-mix tray each called `setVisible` before being added to a layout, and a widget shown while parentless becomes its own top-level window for the duration. Each `setVisible` now follows its `addWidget`, and the source-text ordering guard - which could not have caught these three - is replaced by a runtime invariant that constructs the real Builder in both entry modes and rejects any widget shown before it is parented.
- Fixed viewport control changes not reaching the host. The presentation payload carries display mode, X-Ray, textures enabled, part pick, zoom, and pan, but only the camera drag paths notified: Reset/Fit reframed the camera, the preview mode combo changed the display mode, and the X-Ray and Part Pick checkboxes changed picking behaviour, all without telling the host, which kept a stale mirror to restore from.
- Fixed resizing the embedded Mesh Editor taking the renderer down. Every flat button rebuilt a rounded GDI region on each window-position message, so a host resize churned a region handle per button per message, and when GDI refused one the exception escaped the window procedure. The rebuild is now skipped when the size is unchanged and before the handle exists, and falls back to square corners rather than throwing. That fault presented as a hang rather than an error because the helper installed no UI exception guard: WinForms answered with its own Continue/Quit dialog, invisible behind a borderless child window, while it blocked the message loop. UI-thread faults now go to the status file and stderr and exit non-zero so the host supervisor can retry, with a dialog only when standalone.
- Fixed committing a DDS assignment failing material compilation on every submesh with `AttributeError: 'dict' object has no attribute 'slot_kind'`, because the texture-input synthesis declared it returned a dataclass but passed its source attribute straight through, letting mapping-shaped entries reach attribute-based consumers deep inside synthesis.
- Fixed the Mesh Editor reporting no renderer process for one that was demonstrably running, and being unable to detect a restart at all. The shared controller owns the process, so the tab never sees its start signal - a launch shows up as a process-generation increase, and both shared-controller handlers already adopted that generation before any load path ran, defeating the comparison. Launch adoption is consolidated in one place, and the count is re-seeded after the per-session reset when a renderer is already resident, since the host prewarms one.
- Fixed Mesh Builder startup validation silently passing regardless of what the renderer did, because the launch event it scans for stopped being emitted when launch detection moved off the process-start signal. The event is emitted again at the same moment the counters treat as the start.
- Fixed the first archive texture request of a session killing the preview-core service. That job can spend its whole budget indexing package `.pamt` files before resolving a single DDS, and the timeout then took the service down, leaving the model untextured until the texture checkbox was toggled by hand. The indexes it did finish are cached, so a single bounded retry starts warmer.
- Fixed every release build failing provenance with "provenance does not match its packaged manifest". The helper gained a `renderer_status_request_v1` capability that was never added to the packaged manifest, so it reported 23 capabilities against a 22-entry list. Nothing else disagreed - manifest id, semantic version, protocol version, executable and shader hashes, and both backends all matched.
- Fixed the native builds failing with a bare "no such file or directory" behind `MSB8066`. DirectXTex's shader step names `CompileShaders.cmd` relatively and relies on the working directory to resolve it, which `NoDefaultCurrentDirectoryInExePath` suppresses for both `CreateProcess` and `cmd.exe`. The variable is now cleared inside each spawned `cmd.exe` with `set`, which keeps the change scoped to the child rather than leaking into the caller's session. `fxc` was never missing.
- Fixed the Move tool appearing to under-track the cursor in the real-PAC gate. The renderer builds each world-view-projection for the active pane's bounds and sends those bounds alongside it, but the harness converted the result using the host window's client size, scaling every screen-space result by the ratio between them. Using the viewport dimensions the renderer pairs with the matrix, a 40 px drag now projects to exactly 40.0 px.
- Fixed the side-by-side zoom proof reading the presentation from the ready status, which predates the side-by-side package and therefore reported a single pane and rectangles for a layout that no longer existed, so the wheel went to the wrong screen position and nothing zoomed. It now requests the renderer's current full status, keeping the older sources as fallbacks.
- Fixed late lazy callbacks firing during Qt shutdown, and hardened embedded Mesh Editor teardown so closing the workspace does not leave work queued against a dying window.
- Fixed the first-run archive prompt blocking input and, in the packaged app, closing the app outright; manual archive preview and first-run input now behave the same packaged as from source.
- Fixed Mesh Editor faults across builder startup binding, bootstrap materials and layout, selection and edit-mode handoff, gizmo state and pivot, preview mode not being restored after a save, active tools not toggling back to orbit, preview zoom anchoring, and preview view-mode selection not changing the rendered output.
- Fixed part deletion producing wrong topology in combined mesh scenes, and preserved raw PAC index counts in exported OBJ sidecars.
- Fixed false PAC descriptor suffixes being accepted, sidecar material identities being conflated, and numbered PAC mask families and cross-archive fist masks resolving to the wrong alias. PAC hair aging colour layers are now recorded rather than dropped.
- Fixed material DDS bindings being lost after a preview failure, stale resident material caches surviving an invalidation, degraded resident material synthesis being accepted, corrupt native texture preview cache entries being reused, and unreadable layered normals failing open instead of closed.
- Fixed transient material image reads and decodes failing outright where a retry succeeds, and fixed mesh material textures not resolving across game archives.
- Fixed the .NET material graph synthesizing DDS incorrectly, texture orientation parity in the Mesh Editor, material classification across the expanded corpus, and material response not matching the orthographic camera.
- Fixed an archive preview package race and the lazy prefab path it exposed, initial archive prefab visibility, and archive preview startup and texture presentation.
- Fixed stale feature metadata blocking release builds, generated provider metadata not being refreshed during packaging, packaged media helper architecture not being validated, and Build Mod option callbacks not being wired.
- Fixed .NET and native helper processes surviving the app when it does not close gracefully. A normal close already stopped every helper, but a crash, a `SIGKILL`, or Task Manager's "End task" skipped that path and left `cdmw-mesh-dotnet-editor.exe` resident indefinitely, holding a D3D11 device and the resident package cache; nothing reaped it, and `atexit` handlers do not run on those exits. The app now joins a Windows job object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` at startup, so the kernel terminates every owned child the moment the app dies by any means. Child processes inherit membership, so helpers added later are covered without registering anywhere. Processes that belong to the user rather than the app - Crimson Desert itself and external authoring tools - break out of the job explicitly and still outlive the workbench.
- Added a startup sweep that terminates helper processes stranded by an earlier session, so leftovers from crashes that predate the job object are cleaned up rather than accumulating. The rule is deliberately narrow, because other installations and concurrently running sessions run identically named helpers: a process is reaped only when its image name is one the app owns, its image lives under this installation's root, and its parent is gone - either absent, or a recycled PID whose process started after the child. A live parent means somebody still owns the helper, so it is left alone. The sweep costs ~20 ms, runs before the archive cache is touched (a stranded worker holds a mapped cache file this session could not otherwise replace), and writes a report to the logs directory only when it actually reaps something.
- Fixed the embedded .NET mesh editor helper ignoring the close of its host's stdin. The protocol reader ended its loop on EOF and left the WinForms message loop running forever; it now closes the form, and a watchdog guarantees the exit if EOF arrives before the message loop starts or while the UI thread is blocked. Standalone (non-embedded) launches are unaffected.
- Corrected the PAC skin-influence byte layout: influence slots live at byte 20 and their weights at byte 28 of the 40-byte vertex record. The reader and writer previously shared the wrong offsets (28/32), so 72% of every vanilla body decoded as unweighted and authored skin weights could only reference slots 0-3. Slots index the .pac's own bone palette (a u16 count then that many u32 .pab bone-name hashes), not the skeleton directly; `resolve_pac_bone_palette` now decodes a vertex's primary influence to a named bone.
- Fixed `Profile > Import Profile` accepting a JSON document that carries no profile data. Files such as `{}`, `{"settings": {}}`, or a bare envelope reported "Profile imported" while resetting every workflow path to defaults, and an empty settings snapshot cleared the whole app settings store on the replace pass. Such files are now rejected with an explanatory message, an empty snapshot leaves stored settings untouched, and legacy bare-config and settings-only profiles still import.
- Fixed Settings changes being silently discarded when a theme, font, density, or log-color change was still pending: flushing settings applied the appearance change and then returned before writing the queued startup, performance, layout, safety, and 3D preview preferences. Those preferences are now written on the same flush, so app close and `Profile > Export Profile` no longer drop them.
- Fixed CDMW Full Item Finder categories lagging behind CDMW Lite by applying Lite's ordered category/group taxonomy and token-safe naming rules in the resident Full archive backend; saved filters from the retired taxonomy are migrated before startup warmup and dialog search.

## [0.10.0-alpha.2] - 2026-06-06

### Added
- Added Desert Dawn, High Contrast, and OLED Black app themes with matching theme-aware app icons and contrast-checked text, selections, and control borders.

### Changed
- Changed Mesh Editor D3D11 preview packaging so Modify Original previews reuse Archive Preview material parity more closely, including texture settings, support-map toggles, and D3D11 view-mode controls.
- Changed mesh-edit live updates to patch vertex buffers in place where possible instead of rebuilding full triangle payloads during brush/move strokes.

### Fixed
- Fixed Mesh Editor move/edit strokes freezing and corrupting the preview mesh because native vertex updates did not accept exponent-format float values reliably.
- Fixed `Lighting / Texture Settings` changes in Mesh Editor not rebuilding D3D11 packages when texture/support-map settings changed.
- Fixed skin/head texture selection in Mesh Editor by preventing prefab component material batches from overwriting same-local-index body/head batches and by keeping layer-only texture inputs from being promoted as whole-surface head albedo.

### Docs
- Updated release version references from `0.10.0-alpha.1` to `0.10.0-alpha.2` in the README and app version metadata.

## [0.10.0-alpha.1] - 2026-06-05

### Added
- Added a new grouped workspace surface with `Dashboard`, `Assets`, `Textures`, `Research`, and `Settings` navigation. The dashboard now shows workspace health, configured tool paths, archive-cache status, recent work, and latest run output shortcuts.
- Added detachable work tabs for Archive Browser, Texture Workflow, Texture Editor, Texture Replacer, Mesh Editor, Model Library, Icon Creator, Texture Research, and Text Search, with saved main-window and detached-window geometry.
- Added `Mesh Editor` as a first-class asset workspace for supported archive meshes, including Modify Original, Import Replacement, Import Preview, and In-Game Swap entry points from the selected Archive Browser target.
- Added a native D3D11 preview pipeline for archive preview and mesh-alignment work. Archive mesh preview now defaults to the native D3D11 host, supports durable preview packages, embedded child-process rendering, live reloads, diagnostics, memory/timing reports, component visibility toggles, and renderer tuning from preview settings.
- Added native D3D11 alignment controls for mesh replacement and editing, including move/rotate handles, hover/selection, part picking, source-part picking, brush/vertex stroke transport, view modes, live texture flip, and package caching so visual edits can refresh without rebuilding everything.
- Added native backend services that move performance-critical archive, DDS, mesh preview, D3D11 rendering, and HKX work out of Python and into compiled helpers, including C++ archive/texture/preview/D3D11 components and the native HKX backend.
- Added a native preview core path that can parse supported PAC/PAM/PAMLOD data and generate D3D11 preview packages without the older Python mesh-preparation path when supported.
- Added native DDS and DirectX texture helper paths for preview, staging, and rebuild workflows, with the former external DDS converter kept as an optional legacy fallback instead of the primary requirement.
- Added archive shard caches for scan data, basic indexes, and deferred name-search indexes. Changed PAMT shards can rescan independently, PAZ-only changes can reuse existing scan/index shards, and cache health is surfaced in the dashboard/performance flow.
- Added archive item-icon thumbnail caching so item-icon discovery and preview can warm in the background and stay responsive on large archive sets.
- Added `Model Library` for local/importable model discovery, mirror-catalogue search, ZIP/importable model detection, model preview, companion texture/sidecar discovery, and routing compatible models into Archive Browser mesh-import setup.
- Added external model audit support for Model Library and mesh import, including material inventory, texture slot evidence, material class hints, packed-channel/color-space details, and source-authority checks.
- Added `Icon Creator` for item-icon source libraries, favorite/tag/note metadata, archive target matching, template-based compatible DDS payload generation, preview generation, open-in-Archive-Browser routing, Texture Editor import, generated model-preview icons, and adding icon overrides into existing loose mod packages.
- Added `Recolor Variants` workspace for texture/material variant work alongside Workflow, Replacer, and Editor.
- Added Workflow Profiles and Ordered Rules controls for texture workflow planning, matched-file assignment, duplication/reordering, and profile-specific rebuild policy review.
- Added retrofit packaged-mod tooling that can scan folder or ZIP mod packages, identify existing metadata, repair package paths against archive basename evidence, convert packages to selected manager profiles, preserve mesh manifests where possible, and merge CDUMM-style packages.
- Added broader mod-package metadata output and compatibility paths, including manager-specific manifests, payload path repair summaries, optional `.no_encrypt`, `README.txt`, `manifest.json`, `mod.json`, `modinfo.json`, `info.json`, `mod.field.json`, and zipped converted packages.
- Added archive-family package builders for source-mix loose packages, character dependency packages, appearance composite preview packages, and armor swap review/build flows.
- Added direct archive patch support for selected mesh workflows while keeping archive mutation explicit, preflighted, backed up, and recoverable.
- Added Material Authority as the main material-replacement route, with source color through overlay color, source PBR/material mask through detail mask, runtime XML preservation, true source authority, manual override knobs, and legacy profiles kept for repair/debug compatibility.
- Added Material Authority adjustment controls for roughness, metalness, AO, alpha, color scale, emissive/color relief behavior, grouped glow/emissive export, source glow persistence, gloss/matte bias, detail preservation, and generated mask tuning.
- Added Material Authority audit tooling, authority reports, source-aware support preflight, DDS channel evidence reads, audit evidence-gap reporting, FBX source-authority checks, and standalone report-check helpers.
- Added corpus-learned PAC XML material profiles and runtime XML material controls so mesh replacement packages can preserve target/corpus wrapper order, stock masks, detail/height/grime/dye/PBD response, and compatible source-owned slots more deliberately.
- Added material truth tooling, preview comparison helpers, RenderDoc truth-pass import/export support, shader binding summaries, shader blob extraction, D3D12 draw/dispatch candidate finders, DDS/resource correlation, capture launch helpers, replay probes, and long-run shader status reports.
- Added reverse-engineering support for Crimson material/channel contracts, shader registry evidence, table catalog evidence, texture relationship audits, PAT asset decoding, PBD cloth data, skeleton resolving, native HKX/tagfile inspection, and richer connected-physics/context previews.
- Added HKX body/physics previews, HKX JSON/XML/Havok XML export and import paths, HKX corpus scanning, visual body/source previews, and richer socket/XML evidence handling.
- Added PACCD/customization sidecar preview support, sidecar JSON export/inspection, sidecar corpus scans, and sidecar-aware runtime XML material repair paths.
- Added Material Finder and expanded Item Finder evidence views, including material evidence tags, exact/related set scoping, icon opening, family actions, raw reference export, and row-level material/HKX actions.
- Added richer archive relationship discovery for item icons, physics/HKX, PAB/prefab companions, appearance composites, source mixes, model families, and raw table/asset family/uses/used-by views.
- Added expanded archive structured preview coverage and text/XML helpers, including XML encoding handling, syntax-highlighted previews, structured binary editing scaffolding, table-catalog evidence, and archive extension preview matrix updates.
- Added mesh editing and import/export expansion: exact face delete, part removal export, display clone target handling, source part mapping, scene append/import improvements, glTF/DAE/GLB support hardening, mesh deformation helpers, morph slider support, and safer display-target diagnostics.
- Added appearance composite and source-mix helpers for building replacement packages that understand target/source family context instead of treating every file as an isolated payload.
- Added native archive acceleration, archive list batching, preview package caching, asynchronous body preview work, archive startup progress smoothing, archive preview memory diagnostics, and idle-render throttling for large archive sessions.
- Added app and theme icon generation, per-theme icon assets, selected/refined app icon assets, and build helpers for PyInstaller/native Windows packaging.
- Added runtime dependency smoke checks, full QA runner support, hidden-subprocess handling, PyInstaller temp cleanup checks, and repo-hygiene guards for local corpus/build artifacts.

### Changed
- Changed the public workflow language from `Replace Assistant` to `Texture Replacer`, and reorganized user-facing tools into grouped navigation rather than one long top-level tab row.
- Changed archive preview from an approximate in-process preview surface into a D3D11-first asset-inspection pipeline with explicit diagnostics for material layers, texture failures, sampler state, PBD preview, overlay metadata, and package source.
- Changed core architecture toward native-first hot paths: Python still owns the PySide workbench and orchestration, while compiled helpers increasingly own archive acceleration, DDS encode/decode, native preview package generation, HKX inspection, and D3D11 rendering.
- Changed archive scan/index behavior toward shard-backed, health-checkable caches so large installations do less repeated work and stale data can be isolated to the changed shard.
- Changed archive preview and mesh alignment work so heavy D3D11 package generation, cache writes, preview reloads, and alignment refreshes happen off the UI thread where possible.
- Changed mesh replacement from a single dialog-heavy flow into a persistent Mesh Editor workspace with an embedded builder, vertical tool palette, live native preview, part routing, material controls, diagnostics, and final package checks.
- Changed model import flows so local Model Library assets can carry companion textures and sidecars into Archive Browser import setup, then preview through the same D3D11/package path used by archive meshes.
- Changed material replacement strategy toward source/target authority: source-owned visible material data can be used where compatible, while target/corpus runtime XML, wrapper order, cloth/PBD hooks, and stock support layers remain protected unless the selected profile says otherwise.
- Changed Material Authority exports so source audit results, support-map preflights, material-class evidence, and adjustment summaries are recorded beside package diagnostics instead of being hidden inside preview behavior.
- Changed final-package preview/export behavior to better separate generated DDS payloads, copied source files, original archive references, diagnostic JSON, manager metadata, and actual mod payloads.
- Changed Archive Browser actions into a broader asset workbench surface with copy filename, family filtering/export, source-mix building, character dependency export, material editing, HKX editing, sidecar inspection, loose-mod import, and backup restore available from the selected asset context.
- Changed settings/profile coverage to include appearance, language, startup, performance, preview, Texture Replacer, Texture Editor, safety, window/layout, D3D11, and archive-cache preferences.
- Changed DDS handling so normal preview/rebuild paths prefer bundled native helpers and broader DXGI format handling, while the former external DDS converter remained available for legacy fallback cases.
- Changed archive search, item discovery, and relationship views to use broader item-name/icon/model family evidence without forcing every inferred companion into a recommended include target.
- Changed preview guidance and help text around Material Authority, D3D11 preview, package retrofit, model import, icon creation, cache health, and archive mutation safety.

### Docs
- Added reverse-engineering documentation for texture relationship audits.
- Updated README guidance around grouped navigation, Dashboard, Texture Replacer, Model Library, Icon Creator, native DDS helpers, D3D11 preview, Material Authority, mod-package retrofit, diagnostics, and detachable tabs.
- Updated release version references from `0.9.0-beta.3` to `0.10.0-alpha.1` in the README and app version metadata.
- Expanded tool and test coverage around archive shard caches, native preview core, D3D11 preview packages, Material Authority profiles/audits, RenderDoc truth tooling, model catalogue/library, item-icon generation, package retrofit, mesh editing, source mix, appearance composites, HKX/PBD/PAT helpers, and UI source guards.

## [0.9.0-beta.3] - 2026-05-02

### Added
- Added broader Archive Browser search relevance and alias handling so character/equipment root aliases can find related model components without hardcoding a specific outfit or character name.
- Added `.dds` item-name discovery through related model and material-sidecar graph sources while still keeping selected extension filters enforced for final result rows.
- Added richer Referenced Files resolution for `.app_xml`, `.prefabdata_xml`, model entries, and material sidecars using the archive relationship resolver.
- Added structured Archive Browser inspectors for high-value binary formats including `.prefab`, `.levelinfo`, `.palevel`, `.roadsector`, `.road`, `.nav`, `.pabc`, `.pabv`, `.pabgb`, and `.pabgh`.
- Added simplified value summaries above raw XML/text previews for text-like archive entries such as `.pac_xml`, `.pam_xml`, `.pamlod_xml`, `.pami`, `.app_xml`, `.prefabdata_xml`, and `.xml`.
- Added HKX/Havok metadata preview improvements and focused regression coverage for archive patch preflight and structured asset previews.

### Changed
- Changed Archive Browser search expansion so package, folder, role, size, previewable, exclude, and extension filters remain authoritative after item-name expansion.
- Changed Archive Browser search ordering so direct basename/path matches and exact model aliases appear before lower-confidence inferred sidecars or texture rows.
- Changed model texture binding so sidecar DDS rows are listed more completely while visible base previews avoid promoting technical normal/material/height maps as color textures.
- Changed WEM patch confirmation wording to clarify that audio replacement is best-effort and not a full Wwise-authoring rebuild.
- Removed the failed Experimental Layer Composite preview mode and kept saved settings falling back to the existing Mesh Base First / Lit path.

### Fixed
- Fixed extension-filter leakage where item-name searches could return unrelated extensions after related-file expansion.
- Fixed missing or incomplete Referenced Files rows for direct `.pam_xml` / `.pamlod_xml` sidecars and app/prefab/model/material graph references.
- Fixed texture preview/reference regressions where support maps could be hidden or over-promoted instead of being listed as normal/material/height support slots.
- Fixed archive patch safety by validating the existing PAPGT/PAMT checksum chain, target PAMT records, PAZ paths, package roots, and compression support before writing.
- Fixed archive patch failure recovery tests around append-only PAZ writes, backup restore, and stale target entries.

### Docs
- Updated release version references from `0.9.0-beta.2` to `0.9.0-beta.3` in the README, changelog, and app version metadata.
- Documented the beta scope decision to keep full direct repacking, Wwise rebuilds, overlay mod-manager workflows, PATHC registration, and conflict detection as future work rather than adding them to this beta.

## [0.9.0-beta.2] - 2026-04-30

### Added
- Added a shared archive relationship resolver for model, material, appearance, prefab, texture, skeleton, and physics links across `.pac`, `.pam`, `.pamlod`, `.pac_xml`, `.pami`, `.app_xml`, `.prefabdata_xml`, `.dds`, `.hkx`, and `.pab`-style entries.
- Added safer character/body swap planning that can patch target appearance body/head references while preserving target hair, armor, skeleton, and physics by default.
- Added in-game swap-scope help explaining generated/retargeted sidecars, direct source sidecar replacement, full source `.app_xml` replacement, and the Character Swap Plan.
- Added visible unresolved relationship rows for missing appearance/prefab references so files such as `.pabc`, `.pabv`, `.papr`, or `.hkt` are not silently ignored.
- Added determinate Archive Browser extraction progress for selected/filtered archive exports.

### Changed
- Changed in-game swap related-file discovery to prefer graph references and exact archive paths before basename heuristics.
- Changed source texture deduplication to use normalized archive identity instead of DDS basename, so duplicate names in different folders are preserved.
- Changed texture-slot suggestion priority so exact original DDS path/name matches win before role, body/hand, sidecar-evidence, or token heuristics.
- Changed body/hand/head/foot texture suggestion rules so hand-specific textures are no longer auto-suggested for body/nude slots, and vice versa.
- Changed the swap-scope table wording from replacement instructions to contextual labels such as `Detected reference`, `Planned output`, and `Manual/risky`.
- Renamed `Select Character Graph` to `Select Graph Textures` because the safe bulk action only selects resolved DDS texture rows, while sidecars, skeletons, physics, and full appearance descriptors remain manual.

### Fixed
- Fixed a GUI freeze when choosing an in-game swap source on large archive sets by caching resolver indexes and avoiding broad `.app_xml` payload scans on the UI thread.
- Fixed a stray top-level `Loose File` popup in Archive Browser by adding the loose-preview toggle button to the preview header layout.
- Fixed texture override suggestions that could map `cd_phw_00_nude_00_0001_hand.dds` onto `cd_phw_00_nude_00_0001.dds`.
- Fixed texture override suggestions that could map a generic body normal such as `cd_phw_00_nude_00_0001_n.dds` onto an exact hand normal slot such as `cd_phw_00_nude_00_0001_hand_n.dds`.
- Fixed source sidecar and character graph rows being presented too strongly as recommended include targets when they are often contextual or risky manual choices.
- Fixed narrow Archive Preview overlap cases around compact controls and the referenced-file pane.

### Docs
- Updated release version references from `0.9.0-beta.1` to `0.9.0-beta.2` in the README, changelog, and app version metadata.
- Clarified in-app guidance for in-game mesh swap scope, Character Swap Plan behavior, and when direct source `.pac_xml` or source `.app_xml` replacement should be treated as advanced/manual.

## [0.9.0-beta.1] - 2026-04-30

### Added
- Added an Archive Browser material-sidecar editor for recognized `.pac_xml`, `.pam_xml`, `.pamlod_xml`, and `.pami` color, float, and texture-path values, with reviewed related-file inclusion, approximate model preview, live material refresh, and mod-ready package export.
- Added the Mesh Replacement Alignment workflow for supported archive meshes, including side-by-side original/replacement preview, transform controls, part/source mapping, texture-plan review, original-part retention controls, and sidecar-aware replacement options such as `Patch material sidecar` and cautious missing base/color injection.
- Added a Mesh Import Setup and preflight step before replacement alignment, with source-mesh stats, compatibility guidance, supplemental file selection, texture assignment review, and safer continuation into the live alignment workspace.
- Added an in-dialog `Test Build Preview` action for Mesh Replacement Alignment. It builds the current replacement in memory, uses the final package-preview model path and archive DDS resolvers, keeps the original reference visible, and can return to the live alignment preview without writing a package.
- Added static mesh replacement support for selected `.pac`, `.pam`, and `.pamlod` mesh payloads, including mapping reports, replacement transforms, material/part mapping, source-part controls, and skinned-target record cloning where the recovered layout supports it.
- Added broader scene import for mesh replacement sources, including OBJ, DAE, glTF, and GLB-style uncompressed triangle geometry, with discovered texture files offered as supplemental import candidates.
- Added an in-game mesh swap flow so one loaded archive mesh can be used as the replacement source for another compatible archive mesh while carrying compatible sidecar and texture context into alignment.
- Added a final package preview pipeline for mesh loose exports and test builds, including generated/copied/original DDS resolution, sidecar validation, and clearer warnings when final preview texture bindings cannot be resolved.
- Added a central mod-package finalizer for mod-ready exports across Archive Browser, Texture Workflow, and Replace Assistant, with shared metadata output for `manifest.json`, `mod.json`, `modinfo.json`, `info.json`, optional `files/` wrapping, optional ready `.zip` creation, and `new_paths` metadata for brand-new archive paths.
- Added mod-manager export profile choices for universal loose files, CDUMM, Definitive Mod Manager, and Crimson Sharp / Crimson Browser targets, including manager-facing conflict and language metadata where supported.
- Added archive item-name indexing and search support so exact item names, inferred aliases, localization-backed names, and display-name evidence can help find related archive entries.
- Added the floating `3D Preview Settings` dialog with render diagnostics, texture probes, support-map preview shading, support-map toggles, preview disclaimers, and asset-dependent material/relief diagnostic modes.
- Added Archive Performance controls for sidecar indexing, preview cache behavior, quick/full preview behavior, and preview texture limits so heavy archive sessions can be tuned without editing config files.
- Added compact Archive Preview controls, a collapsible referenced-file pane, loose-file preview toggling, 3D preview settings access, support-map toggles, and dark-preview controls.
- Added startup/progress and crash-reporting infrastructure for archive-heavy sessions, including heartbeat reports, native fault logs, previous-session unclean-exit detection, and hang-watchdog breadcrumbs.
- Added built-in Spanish and German UI translations, custom language import/export support, and additional themes including Midnight Ember, Glacier, Black Gold, Pine, Violet Steel, Nord, One Dark, Tokyo Night, Solarized Dark, Catppuccin Mocha, GitHub Dark, Dracula, Everforest, and Crimson Desert.
- Added shared generated-file descriptions and wrapped `?` help buttons for mod-package export options.

### Changed
- Renamed the public app surface from `Crimson Forge Toolkit` to `Crimson Desert Mod Workbench`, including package/module names, executable naming, README text, and release metadata.
- Reworked Archive Browser mesh workflows from OBJ/FBX export/import helpers into a fuller preview, replacement, material, sidecar, and package-building surface while keeping archive mutation explicit and confirm-before-write.
- Changed archive package root detection to also recognize PAZ/PAMT layouts nested under a `game_files/` subfolder.
- Changed archive scanning, cache reuse, derived indexes, and sidecar indexing to do less UI-thread work during large archive sessions, with better cancellation and progress/status breadcrumbs.
- Changed archive preview texture handling to separate visible/base textures from technical support maps, preserve support-map role information, and allow support-map preview shading to be toggled as an approximate inspection mode.
- Changed mesh loose exports so final preview paths, generated DDS payloads, copied supplemental files, and original archive DDS references are validated through the same final package preview logic used by the Archive Browser.
- Changed mod-package output so generated readmes list the actual artifacts written for the selected export options, and clarified cleanup behavior separately from manager conflict metadata.
- Changed `.no_encrypt` handling into the generated-artifacts controls instead of mixing it with unrelated package metadata.
- Changed the Archive Preview layout to be denser and more resilient at narrower widths, with compact action rows and a referenced-file pane that can collapse before it overlaps the model preview.
- Changed preview/settings wording to use softer support-map preview wording, since these modes are approximate, asset-dependent, and sometimes diagnostic rather than final-render accurate.
- Changed Settings and preview dialogs to synchronize more safely across floating and embedded controls.
- Expanded automated coverage around Archive Browser cache/indexing, final package preview, material-sidecar editing, mesh import/replacement, model preview settings, package export, localization, themes, and preview diagnostics.

### Fixed
- Fixed high-risk Archive Browser shutdown behavior by making close/cancel paths wait for active scan, preview, sidecar-index, and cache-writer workers instead of tearing down running background Qt worker threads.
- Fixed crash-reporting reliability so previous heartbeats survive quick relaunches unless the previous process is confirmed alive, and background exception hooks avoid reading live Qt widgets outside the GUI thread.
- Fixed false missing/grey final-preview warnings by resolving original and copied archive DDS files through archive path and basename indexes while still preferring generated DDS payloads when present.
- Fixed mesh loose export profile handling so DMM texture layouts are not applied to mesh packages where a mesh-safe layout is required.
- Fixed Archive Preview referenced-file layout overlap at narrow widths by letting the side pane collapse before it covers preview controls.
- Fixed loose-file preview toggling so archive/loose preview state remains a real two-state action and respects loose-preview asset arguments during preview refresh.

### Docs
- Updated release version references from `0.7.0-beta.4` to `0.9.0-beta.1` in the README, changelog, and app version metadata.
- Updated in-app documentation and guidance around Archive Browser search, mesh replacement alignment, Live Alignment Preview, Replacement Preview placement, material/sidecar limitations, and final package preview expectations.
- Expanded the top-level release summary from a direct comparison with `v0.7.0-beta.4`, focusing on the final public behavior in this beta.

## [0.7.0-beta.4] - 2026-04-21

### Added
- Added a broader `Referenced Files` browser beside mesh previews in `Archive Browser`, so supported `.pam`, `.pamlod`, and `.pac` entries can now surface related `.dds`, `.xml`, `.pami`, `.meshinfo`, `.pab`, `.paa`, `.pae`, and similar companion files with direct open/export actions.
- Added multi-file related-export actions from the mesh preview pane, including `Export Selected...` and `Export All...` for resolved referenced files.
- Added structured binary inspectors for `.meshinfo`, `.paa`, `.pae` / `.paem`, and richer `.pab`-adjacent companion discovery so those files no longer fall back to raw string dumps as often.

### Changed
- Changed mesh import/export workflows so `Export OBJ...`, `Export FBX...`, `Import OBJ Preview...`, and `Import OBJ...` can all work with optional supplemental local files such as sidecar `.xml` / `.pami` data and matching `.dds` textures when you want the preview or loose export to reflect a fuller material setup.
- Changed loose mesh package output so the generated `README.txt`, `manifest.json`, and `info.json` stay cleaner and more focused on the minimum metadata needed for a practical mod-ready package.
- Changed sidecar-aware archive reference handling so preview/detail flows can carry richer related-file context instead of limiting the mesh side panel to textures only.

### Fixed
- Fixed PAC textured preview orientation for archive and local supplemental-file workflows, so sidecar-backed `.pac` previews no longer rely on the previous vertical-flip guess in cases where the texture should be used as-is.
- Fixed related-file actions so archive mesh companions can be opened or exported directly from the preview pane instead of only being listed.
- Fixed more semantic propagation from `.pac.xml` / `.pami` sidecars so referenced-file rows and preview texture assignment retain better `_baseColorTexture`, `_normalTexture`, `_materialTexture`, `_heightTexture`, `_maskTexture`, and similar role information.

### Docs
- Updated release version references from `0.7.0-beta.2` to `0.7.0-beta.4` in the README, changelog, and app version metadata.

## [0.7.0-beta.2] - 2026-04-20

### Added
- Added an explicit mesh loose-export metadata prompt to the `Import OBJ... -> Write Mod-Ready Loose File` flow, so title/version/author/description and `.no_encrypt` are confirmed at export time instead of being taken silently from saved app settings.

### Changed
- Changed mesh loose package generation so `README.txt`, `manifest.json`, and `info.json` are produced from the same confirmed export metadata with a cleaner mesh-package layout.
- Changed the README front page for `0.7.0-beta.2` so the current beta highlights focus on the newer loose-export prompt and sidecar-aware texture-reference improvements rather than repeating the broader `0.7.0-beta.1` feature list.

### Fixed
- Fixed the actual `Import OBJ...` loose-export path still bypassing the metadata prompt and reusing stored values from `CrimsonTextureForge.cfg` / app config even after the prompt UI had been added elsewhere.
- Fixed archive mesh referenced-texture resolution for PAC XML / PAMI sidecar bindings so exact technical maps such as `_normalTexture`, `_materialTexture`, `_heightTexture`, and `_maskTexture` are no longer flattened toward the albedo entry in the `Referenced Textures` list.
- Fixed sidecar-driven texture labels so archive mesh previews now show clearer semantic names like `Base Color Texture`, `Normal Texture`, `Material Texture`, `Height Texture`, and `Mask Texture` when those roles are present in companion sidecar data.
- Fixed textured model preview assignment so sidecar-aware preview shading continues to prefer visible/base-color bindings for display while still preserving the full exact semantic DDS set in the reference list.

### Docs
- Updated release version references from `0.7.0-beta.1` to `0.7.0-beta.2` in the README, changelog, and app version metadata.

## [0.7.0-beta.1] - 2026-04-20

### Added
- Added explicit archive-mutation workflows for supported archive entries, including patch requests, per-entry backup capture, backup restore, and mod-ready loose export helpers instead of keeping archive work extract-only.
- Added real 3D archive preview support for recovered `.pam`, `.pamlod`, and `.pac` geometry, with orbit/zoom/reset controls, textured shading, richer details, and fallback messaging when geometry recovery is incomplete.
- Added mesh export/import tooling for supported archive meshes, including `Export OBJ`, `Export FBX`, `Import OBJ Preview`, `Import OBJ`, paired `PAM -> PAMLOD` transfer handling, and PAC FBX export paths that can attach matching `PAB` skeleton data.
- Added referenced-texture inspection for archive mesh previews, including a dedicated texture list plus `Open`, `Export DDS`, `Replace DDS`, and `Replace From PNG` actions for resolved mesh texture entries.
- Added broader archive media/binary preview coverage, including `.wem` playback via bundled `vgmstream-cli`, `.mp4` / `.bk2` playback through Qt Multimedia, `.bnk` Wwise soundbank summaries, `.pab` skeleton summaries, `.hkx` metadata summaries, and `.pami` text decoding in the archive browser.
- Added flat-vs-tree archive browsing, incremental tree population, full extension-list population from the loaded archive index etc.

### Changed
- Repositioned `Archive Browser` from a purely read-only explorer into a mixed browse/inspect/export/patch surface for supported mesh and audio paths, while still keeping loose DDS workflows and confirm-before-write behavior intact.
- Reworked the archive preview pane so export/import/restore actions are visible beside the preview instead of being hidden behind right-click-only discovery, and moved referenced textures beside the model preview for a larger, more practical preview area.
- Archive filtering and archive preview work now run with more progress-aware background behavior, better cancellation, and lighter UI-thread work when changing large extensions, rebuilding previews, or switching between flat/tree views.
- Text-like archive preview now uses the same styled text presentation more consistently across supported text formats, including decrypted or decoded archive payloads such as `.pami`.
- Model texture resolution is now broader and more semantic: preview/export paths resolve more DDS candidates from parsed mesh data and raw binary references, prefer visible/base-color matches over technical-only maps, and apply those references across `.pam`, `.pamlod`, and `.pac` preview/export flows.
- Onefile packaging is now more defensive, with improved custom PyInstaller hooks, bundled Wwise decode runtime handling, and full embedded-archive validation after build so release EXEs fail fast during packaging instead of at first launch.

### Fixed
- Fixed the archive extension filter/drop-down regressions so supported extensions are populated again from the archive contents instead of forcing manual entry for some workflows.
- Fixed archive DDS preview regressions where selecting `.dds` entries could get stuck on details, fail to switch to the preview tab correctly, or become noticeably slower after later archive-browser changes.
- Fixed `.pami` preview stability and presentation so decoded text no longer opens with mismatched styling and is less likely to leave the browser in a stuck `Preparing archive preview...` state.
- Fixed a broad set of `.pam`, `.pamlod`, and `.pac` geometry-recovery failures, including better companion PAMLOD fallback usage, better submesh preservation during companion fallback, additional partial/zero-padded recovery paths, more helpful failure text, and fewer cases where previews stall or degrade into obviously scrambled geometry.
- Fixed more textured-model issues, including missing referenced DDS rows, overly narrow texture-reference columns, companion-preview texture loss, PAC texture availability in preview/export, and incorrect vertical texture orientation on assets such as the shield atlas that were previously mapped into opaque black atlas space.
- Fixed archive-browser responsiveness issues around large extension switches, archive-cache reuse, background preview cancellation, and long-running per-file preview work so the UI spends less time in `Not Responding` during heavy archive browsing.
- Fixed `Texture Editor` grid-state handling so the archive/browser-driven editor path no longer throws `AttributeError: 'TextureEditorTab' object has no attribute '_grid_color'`.
- Fixed onefile extraction/runtime failures involving Pillow/OpenCV/crypto packaging, including corrupt `_imagingft` payload handling, OpenCV FFmpeg plugin extraction failures, and related embedded-DLL extraction errors that could break startup on Windows.
- Fixed `.wem` decode playback launching a visible console window and improved Wwise playback fallback messaging when the local multimedia backend still cannot decode a variant directly.
- Fixed archive patch safety gaps by surfacing backup restore in the UI and tightening patch/build flows so interrupted mesh/audio patch attempts are easier to recover from.

### Docs
- Updated the README for `0.7.0-beta.1` so the front page now reflects archive patching, mesh preview/modding, media preview, and the broader archive-browser scope instead of describing the app as read-only.
- Added and refreshed `docs/archive_extension_preview_matrix.csv` to capture current extension coverage, what the app can actually preview today, and where future investment is still worthwhile.
- Expanded third-party notices and release metadata to cover vendored MIT-licensed mesh tooling, bundled `vgmstream` usage, and the newer packaging/build workflow.

## [0.6.5] - 2026-04-18

### Added
- Added persistent appearance controls for the whole app, including global font family, global font size, list/column font size, density, dedicated log/code font family, log/code font size, and optional bold emphasis for log/code views.
- Added `Research > Archive Insights > Archive Files` preview/details support so selected archive DDS files can now be inspected in-place with the same preview/detail flow used by `Archive Browser`.
- Expanded the archive-side DDS inspector with much richer metadata, including additional header flags, resource/cubemap/DX10 details, mip completeness, estimated surface bytes, hashes, and lower-level DDS header fields for deeper inspection.
- Added simple `Texture Editor` grid visibility controls for color and opacity so the grid can stay readable on bright or low-contrast textures.
- Added clearer ambiguous original selection during `Replace Assistant` auto-match when multiple archive DDS candidates share the same basename and no strong path context is available.
- Added a structured per-file workflow profile system to `Texture Workflow`, including reusable named workflow profiles, ordered glob/exact-path rules, a live `Matched Files` view, exact-path profile assignment from selected files, effective per-file DDS/NCNN previews, and export/import support for the new structured profile format.
- Added built-in starter workflow profiles and starter rules for `*.dds`, `*_n.dds`, `*_d.dds`, `*_disp.dds`, and `*_sp.dds` so common color, normal, height/displacement, and specular map families have immediate baseline assignments.
- Added a searchable in-app documentation browser with topic navigation for workflow features, planner profiles, planner paths, Archive Browser, Texture Editor, Replace Assistant, Research, Text Search, and troubleshooting.

### Changed
- Refined the overall app UI to be denser and more coherent, with smaller controls, more consistent section headers, tighter spacing, better font application, and broader column autofit behavior when the app opens or appearance settings change.
- Reworked the `Texture Editor` no-document layout into a narrower tools lane with a compact actions menu, smaller tool buttons, cleaner empty-state behavior, theme-aware icons, and less wasted screen space on smaller displays.
- Improved workflow handoff behavior again so `Texture Editor -> Send to Texture Workflow` and `DDS To Workflow` make root-clear decisions at handoff time, stage the required source files more predictably, and keep the intended file focused when you move into `Texture Workflow`.
- `Replace Assistant` queue and matching flows now use stronger path-aware `.png -> .dds` matching, clearer overflow handling in the queue columns, and better guidance when exact archive-path evidence is missing.
- Research/archive-related preview panels, Archive Browser details, and section containers now share a more consistent presentation instead of mixing multiple header/box patterns that felt visually disconnected.
- Replaced the old freeform `Texture rules` authoring surface with a visual `Workflow Profiles`, `Ordered Rules`, and `Matched Files` manager, and expanded `Preview Policy` so it shows matched workflow profiles, matched rules, effective DDS overrides, and effective direct-NCNN settings per file.
- Rebalanced the starter workflow defaults so color/albedo stays enabled on the visible-color path by default while normal, specular, and height/displacement starters now begin as preserve-first or technical-path baselines until explicitly overridden.
- Simplified the top-level app navigation by promoting `Quick Start` to its own menu entry, renaming the old `About` surface into `Documentation`, moving `Export Diagnostics...` under `Documentation`, and removing the redundant `Tools` menu.

### Fixed
- Fixed a long list of workflow and review regressions across `Texture Workflow`, `Replace Assistant`, `Texture Editor`, `Compare`, `Research`, `Text Search`, and `Archive Browser`, including frozen or delayed preview handoff, fit-mode compare flicker, distorted compare previews, stale workflow root contents causing misleading compare lists, and several archive/preview UI stalls.
- Fixed additional `Replace Assistant` stability issues around import, auto-match completion, preview refresh, post-build review, and post-worker cleanup so matching and package build flows no longer crash or lock up as easily.
- Fixed a `Replace Assistant Review` preview/runtime error where normal image inputs such as PNG sources could fail with `cannot convert 'Format' object to bytes` while preparing the edited-input metadata and preview pane after a rebuild.
- Fixed classification/local-approval clarity issues so the app better distinguishes inferred roles from saved local approvals, routes workflow review to the correct DDS more reliably, and provides faster per-file local-save actions.
- Fixed more `Texture Editor` issues around guide clearing, document metadata sizing, hidden tab close buttons, image/atlas action layout, light-theme tool icon visibility, grid visibility, and font consistency across the left and right editor panes.
- Fixed a `Texture Editor` custom-brush preset runtime bug where `json` serialization/deserialization paths were used without the required import, which could break preset load/save behavior in the shipped build.
- Fixed several settings and runtime failures, including slow font-size stepping, typed font-size editing, missing imports and startup crashes, DDS-details exceptions, more accurate DDS surface estimates for arrays/cubemaps, and late-cycle packaging/runtime errors.
- Fixed another `Archive Browser` DDS preview hang where rapidly browsing many archive textures could eventually leave the app stuck in `Not Responding`, by avoiding eager loose-preview generation and reducing heavy per-click archive selection recomputation on the UI thread.
- Fixed direct `Real-ESRGAN NCNN` runs that could silently accept invalid flat PNG output or Vulkan/OOM-like failures at large tile sizes, by validating the output and retrying smaller tile sizes automatically before DDS rebuild continues.
- Fixed starter workflow profile defaults that could previously force unsafe per-profile NCNN scales or generic visible-path handling for technical maps, which could lead to broken mixed-batch results or black/flat rebuilt DDS output.

### Docs
- Updated the README for `0.6.5`, refreshed the feature summary and screenshots, and replaced the old `docs/screenshots` set with current captures from the renamed and polished app UI.
- Expanded `Quick Start` and the in-app documentation for `0.6.5` so the shipped help now covers the current workflow/profile system, planner-path and planner-profile meanings, all major tabs, backend behavior, review flow, and troubleshooting.

## [0.6.0] - 2026-04-16

### Added
- Promoted the expanded `Texture Editor` work from the beta cycle into the first full `0.6.0` release, including layered in-app texture editing, masks, adjustments, packed-channel helpers, navigator/rulers/guides, atlas export helpers, and a much broader visible-texture toolset than earlier builds.
- Folded the final late-cycle editor and workflow fixes into the release build, including straighter feathered selection extraction, hole-preserving mask/selection round-trips, layer-mask cleanup on deletion, better ruler/guide behavior, and smoother `Text Search` / `Research` result population on large datasets.

### Changed
- `0.6.0` now represents the stabilized release line after the `0.6.0-beta.x` cycle, so the editor, replacement, DDS preview, research, and packaging workflows described in the current README are now part of the main release instead of being gated behind a prerelease note.
- The app now behaves better during heavier editing/review sessions, with lighter shutdown waits, incremental large-tree population in `Text Search` / `Research`, and additional Texture Editor UI polish around guides, rulers, and atlas controls.
- The shipped `0.6.0` release build now uses the updated app branding, including the app title, package defaults, docs/help text, build output name, and portable config/profile filenames, while still migrating legacy `DDSRebuildApp.cfg` files automatically.
- `Texture Workflow` handoff is now more predictable: `DDS To Workflow` and `Texture Editor -> To Workflow` make their root-clear decisions at handoff time instead of later at `Start`, and editor exports now stage through a dedicated `png_texture_editor` override root instead of mixing with normal upscaled PNG output.

### Fixed
- Fixed additional correctness issues in the release pass, including soft-selection edge extraction, stale mask/adjustment references after layer removal, guide clear/apply behavior, Atlas panel text clipping, and ruler hover alignment when the canvas is centered inside the viewport.
- Fixed more late-cycle workflow rough edges across `Texture Editor`, `Text Search`, and `Research`, so the final `0.6.0` build is more stable and less visibly hitchy than the previous `0.6.0-beta.4` prerelease.
- Fixed multiple late `Replace Assistant` and `Texture Workflow` regressions in the release build, including explicit rather than automatic matching on import/editor handoff, visible auto-match indexing progress, more stable post-match queue handling, and a much lighter post-build review flow that no longer immediately auto-loads heavy 4K previews when package build completes.
- Fixed several preview/review regressions in the shipped build, including `Compare` aspect-ratio distortion, fit-mode flicker, smoother deferred scaling during resize, and removal of synchronous UI-reference scans that were causing freezes when opening textures or preparing compare metadata.
- Fixed workflow/classification clarity issues in the release build, including member-specific classification suggestions, clearer local-vs-inferred approval state in `Classification Review`, one-click `Save Current Role Locally`, and more reliable routing from workflow warnings into focused review of the exact DDS that still needs a saved local approval.
- Fixed the portable onefile packaging issue caused by Pillow AVIF extraction, so the corrected `0.6.0` EXE launches reliably without the `_avif` extraction failure seen in some builds.

### Docs
- Updated the README and release notes for the final `0.6.0` release and kept the beta changelog history intact underneath for users following the development cycle.
- Updated `Quick Start`, `About`, README, release notes, and related docs/help text to use the current app name and reflect the corrected workflow, Replace Assistant, and review behavior in the current `0.6.0` build.

## [0.6.0-beta.4] - 2026-04-16

### Added
- `Texture Editor` gained a much deeper set of texture-editing workflows, including direct on-canvas transform handles for floating selections, richer mask/selection handoff, stronger packed-channel tools, custom image-stamp brushes, symmetry painting, editable quick mask, navigator/rulers/guides, pixel inspection, atlas export helpers, and additional non-destructive adjustments such as `Vibrance`, `Selective Color`, `Brightness/Contrast`, `Exposure`, and `Color Balance`.
- The editor now adds more document-level operations and texture-focused utilities, including crop/trim/canvas/image resize actions, region or grid-slice export helpers for atlas-style work, plus stronger channel copy/paste/swap flows for packed-texture cleanup inside the app.

### Changed
- `Texture Editor` now feels more like a real texture compositor, with stronger transform ergonomics, richer brush behavior, better channel-aware editing, finer control over selection/mask workflows, and more practical navigation and precision feedback while working on large textures.
- Heavy editor sessions now use lighter refresh/history behavior in common dirty-region edit paths, while `Text Search` and `Research` also avoid more unnecessary full UI stalls during large result updates.

### Fixed
- Fixed a broad set of `Texture Editor` issues around selection-to-mask creation, selective-color project save/load, masked copy/extract behavior, merge-down correctness with masks/adjustments, floating selection/project persistence, zoom reliability, and several loaded-editor workflow regressions found during the full feature verification pass.
- Fixed more archive-side and app-wide behavior issues, including cancellation-aware loose DDS preview fallback, safer preview shutdown behavior, broader DDS preview compatibility, and app-wide prevention of accidental mouse-wheel setting changes over combo/spin/slider controls.

### Docs
- Updated the README and prerelease notes for `0.6.0-beta.4` to reflect the latest `Texture Editor`, preview, DDS, and workflow improvements now present in the current beta.

## [0.6.0-beta.3] - 2026-04-15

### Added
- `Texture Editor` grew into a much more complete texture-editing workspace with multi-document tabs, stronger layered editing, floating selections, masks, adjustment layers, richer channel/alpha workflows, and tighter handoff into `Replace Assistant`, `Texture Workflow`, `Compare`, and `Archive Browser`.
- The in-app editor now includes a broader set of real editing tools for visible texture work, including `Paint`, `Erase`, `Fill`, `Gradient`, `Smudge`, `Dodge/Burn`, `Patch`, `Clone/Heal`, `Sharpen`, `Soften`, brush presets, brush tips/patterns, custom saved presets, and finer brush control for detail cleanup.

### Changed
- `Texture Editor` now uses a more canvas-first editing layout with compact document tabs above the canvas, lighter side chrome, better zoom/pan behavior, contextual tool settings, richer shortcut coverage, and more status feedback so it feels closer to a real texture-editing workspace.
- The editor’s selection, move, and transform workflows now behave much more like a real compositor, with better floating selection handling, stronger copy/paste between documents, layered move workflows, and more practical selection refinement behavior.

### Fixed
- Fixed a large number of editor/workflow issues across `Texture Editor`, `Replace Assistant`, archive preview, and `Text Search`, including stronger DDS preview fallback behavior, better unusual DDS compatibility, improved archive-load responsiveness, safer preview cancellation/shutdown, and steadier editor adjustment/selection behavior.
- Fixed additional editor-specific issues around zoom anchoring, floating-selection persistence, project save/load, channel-aware editing, and preview/update stability so the current beta is much closer to a usable real editing workflow than the original `0.6.0-beta.1` prerelease.

### Docs
- Updated the README and release notes for `0.6.0-beta.3` to reflect the newer editor, preview, packaging, and workflow capabilities now present in the current beta.

## [0.6.0-beta.1] - 2026-04-13

### Added
- A new top-level `Replace Assistant` tab for edited-texture replacement workflows, so you can import manually edited `PNG` or `DDS` files, match them to their original in-game DDS, preview them, and build a mod-ready loose package without manually juggling the main batch workflow roots.
- `Replace Assistant` can optionally run the same direct `Real-ESRGAN NCNN` feature set exposed in `Texture Workflow`, including model selection, scale, tile size, `NCNN extra args`, retry-with-smaller-tile, texture preset, automatic texture rules, the expert unsafe override, and post-correction modes such as `Source Match`.
- `Replace Assistant` now writes `example_mod`-style package output with `.no_encrypt`, generated `info.json`, and package-prefixed loose DDS paths that follow the matched original texture.
- Successful `Replace Assistant` builds now open a post-build review window that compares the edited input against the rebuilt DDS preview, so you can quickly inspect whether the repackaged result shifted before shipping the mod.
- A new top-level `Texture Editor` tab for visible-texture work, with layered projects, paint/erase, sharpen/soften, rectangular and lasso selections, clone/heal tools, in-editor recolor, and flattened export back into `Replace Assistant` or `Texture Workflow`.
- `Texture Editor` can open loose images and DDS files directly, and it now has handoff entry points from `Replace Assistant`, `Archive Browser`, `Compare`, and the main `Texture Workflow` setup area.
- `Texture Editor` now includes source-aware preview modes for `Edited`, `Original`, `Split`, and per-channel `R/G/B/A` inspection, plus optional atlas/grid guides so UI and packed textures are easier to review without leaving the editor.
- `Texture Editor` now adds deeper paint/retouch coverage with `Gradient`, `Smudge`, `Dodge/Burn`, and `Patch` tools, plus channel-lock editing so visible texture cleanup can stay inside the app for more real workflows.
- `Texture Editor` brush controls now include roundness, angle, smoothing, primary/secondary color handling, size-step modes, and user-saved brush presets on top of the existing preset/tip/pattern system.

### Changed
- The main `Workflow` tab is now labeled `Texture Workflow`, which better distinguishes the advanced batch pipeline from the new guided `Replace Assistant` flow.
- `Replace Assistant` now sits as its own top-level tab and receives archive-entry refreshes and shared status messages from the main window like the other major tools.
- `Replace Assistant` now hides `Direct Upscale Controls (NCNN only)` unless the build mode is set to upscale, which frees space for the rebuild-only package flow.
- `Replace Assistant` package output now treats the chosen root as the parent mods folder and writes the actual package into a child folder named after the mod title, which better matches `example_mod`-style mod manager layouts.
- `Texture Workflow` can now optionally emit the same ready mod package shape after rebuild, including a child folder named after the mod title plus generated `info.json` and optional `.no_encrypt`, while still keeping the normal `dds_final` output untouched.
- The experimental recolor controls were removed from `Replace Assistant`, because visible-texture editing now lives in the dedicated `Texture Editor` instead of the packaging/rebuild tab.
- `Texture Editor` paint/sharpen/soften/clone/heal tools now expose a more practical first pass of advanced options, including paint blend modes, selectable sharpen/soften modes, visible-layer sampling for filter/clone tools, and a more accurate brush-footprint preview while dragging.
- `Texture Editor` selection tools now have a real companion workflow, including a dedicated `Selection` panel, feathering, invert, `Select All`, `Copy To New Layer`, optional edge-snapped lasso, and a basic `Move` tool for repositioning active-layer or selected content.
- `Texture Editor` now uses a cleaner split layout with a lighter inspector, an icon-first tool rail, narrower default side panels, and a more compact action bar so the canvas keeps more space for actual editing.
- `Texture Editor` now supports multiple open documents in editor tabs, shares copy/paste clipboard content between those tabs, and has been pushed further toward a real texture-compositor workflow with non-destructive layer offsets, richer layer state, stronger selection operations, and cropped pasted layers that move and hide correctly.
- `Texture Editor` now keeps the canvas state more like a real workspace, with per-document view state, a live status strip, contextual docks, async document/open save-export work, and a stronger floating-selection path for copy/cut/paste and transform-style edits.
- `Texture Editor` now supports document-top adjustment layers (`Hue / Saturation`, `Levels`, `Curves`) plus raster layer masks, so visible-texture edits can stay non-destructive longer instead of forcing immediate pixel commits for every tonal change.
- `Texture Editor` now includes `Open In Compare`, which hands the current source binding back to the existing Compare tab instead of duplicating compare preview logic inside the editor.
- `Texture Editor` now adds a real `Fill` tool, quick-mask overlay toggle, custom selection grow/shrink amount, and a `Float Active Layer Copy` transform entry so selection cleanup and isolated transform-style edits are easier without leaving the editor.
- `Texture Editor` now gives the adjustment stack a more professional editing flow with reset/duplicate/reorder/solo controls, direct active-layer mask assignment for adjustments, a richer status strip, and smaller/finer minimum brush footprints for detail work.
- `Texture Editor` brush tools now add presets, selectable brush tips, and pattern-based brush footprints, so paint/erase/clone/heal work can move beyond a single round brush toward more texture-oriented editing.
- `Texture Editor` clone/heal now supports aligned or fixed-source sampling plus a direct source-clear action, which makes retouch work behave more like a real editor tool instead of a one-state helper.
- `Texture Editor` now exposes a dedicated `Channels` panel, gradient secondary color, richer shortcut coverage for tool switching and brush sizing/hardness, and an on-canvas brush HUD so fine paint work is easier to read while you edit.
- Removed the stale hidden in-editor AI-enhance plumbing that was still lingering behind the scenes after the visible editor-side upscale controls were dropped.

### Fixed
- The unfinished `Replace Assistant` implementation is now wired up far enough to be usable, including manual local-original selection, manual archive-original selection, output-folder opening, and better status/build callback handling.
- `Replace Assistant` NCNN model discovery now uses the correct executable/model-dir signature and populates the model picker correctly instead of calling the discovery helper with the wrong argument shape.
- `Replace Assistant` preview follow-up requests now advance their request id correctly when a new selection arrives while an older preview worker is still finishing, which avoids stale preview handoff glitches.
- `Replace Assistant` package builds now honor the `.no_encrypt` toggle instead of always writing the marker file even when the package should stay unmarked.
- `Texture Editor` recolor now applies explicitly to the active layer instead of reprocessing image changes on every setting edit, so tolerance/strength adjustments can be made before committing the recolor action.
- `Texture Editor` history restore is now explicit instead of reloading full snapshots on every list selection change, undo/redo now properly covers layer visibility/opacity edits, and the tool rail now uses icon-backed buttons so the editor feels less rough overall.
- `Texture Editor` now supports wheel zoom directly over the texture, uses collapsible right-side inspector sections so the canvas gets more space by default, and enriches direct file-open document metadata from the configured `PNG root` / `Original DDS root` so relative path, package, original DDS, and semantics are much less likely to stay blank.
- `Texture Editor` now supports right-drag panning, `Show in Archive Browser`, configurable keyboard shortcuts for common editor actions, active-layer copy/paste helpers, and a softer inspector/metadata presentation so the editor is quicker to use and less visually rough.
- `Texture Editor` sharpen/soften now behave more predictably at low strength, and empty edit layers no longer feel broken when `Sample visible layers` is enabled because filter strokes can now read from the merged visible image while still writing into the active layer.
- `Texture Editor` history can now be cleared intentionally so the current document state becomes the new editing baseline, instead of forcing old trial steps to stay in the session forever.
- `Texture Editor` selection copy/paste and move behavior is now much closer to an editor workflow: `Ctrl+C` / `Ctrl+V` respect the current selection, pasted selections become isolated layers instead of whole-image copies, the live selection is cleared after paste so move works on the copied piece, and hiding the original layer now leaves the pasted selection layer visible by itself.
- `Texture Editor` now offers both in-place paste and centered paste for copied layers/selections, and the canvas move-preview path no longer references brush-only overlay state.
- `Texture Editor` floating selections now survive undo/redo correctly, masked cuts no longer clear the entire bounding box for soft/lasso selections, and floating transform state no longer drops out of history just because the move/commit/cancel path changed.
- `Texture Editor` adjustment sliders now preview live without spamming the history list on every tick, and project open/save plus flattened export now run through background workers instead of blocking the UI thread during heavier document operations.
- `Texture Editor` adjustment preview no longer drops selection and makes the controls look disabled while dragging sliders, because live preview now preserves the current adjustment instead of rebuilding the whole list state mid-drag.
- `Texture Editor` now supports finer minimum paint/erase/sharpen/soften footprints and faster `Alt+click` color sampling for paint/fill work, which makes tiny cleanup edits easier on high-resolution textures.
- The left Texture Editor action rail no longer clips utility buttons like `Shortcuts`, because the edit controls were reflowed into a more compact two-row layout instead of being squeezed into one narrow row.
- `Texture Editor` now keeps the canvas at the real scaled image size instead of stretching textures into a forced minimum square, and wheel zoom also works reliably when the pointer is over the texture through the scroll viewport instead of only when the wheel event lands on the canvas widget itself.
- `Texture Editor` floating selections now survive undo/redo correctly in non-checkpoint history restores, project save/load now preserves in-progress floating raster content, reopening an already-open source refreshes the source binding metadata, and wheel zoom behaves more reliably on precision scrolling input while anchoring correctly under the pointer.
- `Texture Editor -> Replace Assistant` handoff now preserves original texture binding metadata even when the editor was opened from Archive Browser, Compare, or loose-file paths, and Replace Assistant review no longer blocks the UI thread while waiting synchronously for the previous preview worker to stop.
- New `Texture Editor` gradient/patch/smudge/dodge-burn paths now route through the editor core correctly instead of being UI-only stubs, and Dodge/Burn no longer fails on the first real stroke because of a bad blend-weight shape.
- Channel-aware editor operations now respect the current `RGBA` edit locks for fill, gradient, brush retouch, and recolor flows instead of always writing all visible channels.
- Replace Assistant now respects the `overwrite existing package files` setting for `info.json` / `.no_encrypt`, and README dependency notes now match the actual bundled/editor runtime stack (`Pillow`, `numpy`, `OpenCV`).
- New textures in `Texture Editor` now open at true 100% zoom instead of being forced into fit-to-window mode, and the zoom readouts now follow the live canvas state correctly instead of leaving stale percentage text behind.
- `Replace Assistant` now imports and matches added files through a background worker with visible status/progress updates, so `Add Files` / `Add Folder` no longer feel like a silent freeze while the app indexes originals and matches imported textures.
- Portable builds now explicitly collect `NumPy`, `OpenCV`, and `Pillow` assets for the new editor stack instead of depending on those libraries only being present in the development environment.
- Archive scan completion no longer eagerly rebuilds the heaviest `Replace Assistant` and `Research` archive indices on the UI thread every time the cache loads, which reduces the short freeze that could happen right after startup archive hydration.
- Startup archive auto-load no longer forces the Archive Browser tab to render immediately if you are working elsewhere, which reduces the visible startup hitch when the cache finishes loading in the background.
- `Settings` now includes an opt-in crash-detail capture toggle that writes local traceback reports for unhandled exceptions and background-worker/archive-preview errors, and the latest crash report is included in the diagnostic bundle when available.
- Archive DDS preview now supports legacy luminance (`DDPF_LUMINANCE`) files, and partial luminance DDS reconstruction now handles raw uncompressed surface sizing correctly, which fixes previously unsupported worldmap `*_sdf_*` previews such as `cd_worldmap_image_compass_sdf_1024x1024.dds` and `cd_worldmap_image_mountain_10026_sdf_2048x2048.dds`.
- Loose DDS preview fallback no longer cascades into a second failure when DDS metadata parsing is unsupported, and archive preview workers now avoid eagerly decoding both archive and loose preview images when only the default archive preview is needed.
- `Research` now passes cancellation all the way through classification-review group assembly, so a cancelled refresh stops more promptly instead of continuing through the final unknown/classified review grouping work.

### Docs
- Updated README, Quick Start, About, and release notes for the current `Texture Editor` feature set, including the newer retouch tools, channel workflow, and deeper brush controls.

## [0.5.5] - 2026-04-12

### Added
- A persistent local texture-classification registry plus `Research -> Archive Insights -> Classification Review`, so you can review unresolved DDS files, approve a label once, and reuse that approval in future scans and texture-policy planning.
- `Classification Review` now includes an inline archive-style preview, filters for `Name` / `Package`, bulk selection helpers, optional already-classified review, and a file-focused queue that works better on the real archive data than the original family/member split.
- `Start` now performs a pre-run unclassified-DDS check for upscale builds, warns when matched files are still `unknown`, and can jump directly into `Research -> Classification Review` focused on the current run’s unknown DDS files before any build phases begin.
- `Research -> References` now includes `Review In Text Search`, which opens the selected XML/material source file in `Text Search` and highlights the referenced DDS name so you can inspect the exact text-side usage quickly.

### Changed
- Removed the retired direct alternate Python-based upscale backend, its setup/import workflow, and related UI/runtime paths so the app now only exposes direct `Real-ESRGAN NCNN` or external `chaiNNer` for upscaling.
- `Classification Review` now uses the selected file as the main review unit, while bulk actions still apply across the underlying family where that is actually useful.

### Fixed
- The pre-run unclassified-DDS prompt no longer fails before build start, because the GUI classification check now uses the public planner entry point instead of referencing a private backend-matrix helper that was not available in the UI module.
- The pre-run unclassified-DDS prompt now correctly resumes into the build after you classify files and restart, instead of stopping after the “0 matched DDS file(s) are still unclassified” check while the utility worker was still cleaning up.
- Text Search preview no longer gets stuck on `Preparing preview...`, because the preview-ready handler now uses the current result context correctly instead of referencing an undefined local when applying syntax highlighting.
- Local classification approvals now apply correctly to both archive-style and extracted package-prefixed DDS paths, so classifying a file in `Research` is reused by later loose DDS workflow runs.
- Archive-wide DDS classification now recognizes low-risk grayscale/scalar suffixes such as `_grayscale` and `_depth_grayscale` as technical mask data, recognizes `pivotpainter` DDS names as vector-style data, and groups `_ct` variants back into their base texture families instead of splitting them into separate review groups.
- A few obvious suffixless archive misses now classify correctly too, so names such as `snownormal`, `snowmask`, and `nonetexturespecular` no longer stay `unknown` just because they omit the usual underscore-separated token.
- Added a few more conservative archive suffix/classification fixes, including `_1bit`, `_mask_1bit`, `_pivotpos`, `_mask_amg`, and safer handling for bare `rough` names that were previously too easy to misread as roughness maps.
- `Research` archive snapshot work now honors cancellation during the heavy archive-insight pass, and `Mip Analysis` detail views now reuse refresh-time family/path metadata instead of rescanning both DDS roots every time you click a row.
- Loose Text Search file discovery now honors cancellation during the initial loose-file walk, and matched-file preview loading now runs through a debounced worker instead of blocking the UI thread on selection changes.
- Archive Browser preview workers now preload decoded preview images in the worker thread, and preview jobs are now stoppable so stale or shutdown-time preview work can be cancelled instead of only waiting for threads to finish.
- Preview widgets now cache scaled preview pixmaps by source and target size, and failed path-backed image loads are remembered so large previews no longer get repeatedly resampled or retried on every resize/fit update.
- `Research -> Classification Review` now hides the redundant right-side `Archive Files` panel while you review labels, keeps the inline preview as the primary visual aid, and can optionally include already classified DDS families when you want to apply a custom override anyway.
- The expert unsafe technical override now really overrides preset-based preserve behavior for technical textures unless an explicit texture rule still says `skip` or forces a preserve/high-precision path.
- Legacy correction modes now honor planner-visible candidates, and planner-visible `unknown` textures with straight alpha now get the same bounded alpha-correction allowance as other visible textures.
- `chaiNNer` override JSON now fails early and clearly when it references `${staging_png_root}` while DDS staging is disabled, instead of quietly substituting an empty string and failing later in the run.
- `Retry with smaller tile` now keeps `tile size 0` as a true full-frame first attempt and only switches into the fixed tiled fallback ladder `512, 256, 128, 64, 32` after that full-frame attempt fails.
- `Research` no longer fails on startup after the `Unknown Resolver` UI addition, because the missing `QComboBox` import is now included in the Research tab widgets.

### Docs
- Updated README/help/release wording to reflect the local classification registry, the refined `Classification Review` workflow, and the app now being `NCNN` / `chaiNNer` only for upscaling.

## [0.5.0] - 2026-04-12

### Added
- Automatic `Source Match` reconstruction modes for direct `Real-ESRGAN NCNN` workflows, including `Source Match Balanced`, `Source Match Extended`, and `Source Match Experimental`.
- A planner-owned `technical_high_precision_path` for eligible non-packed scalar technical DDS files, with support for high-precision staged PNGs or validated direct `PNG root` inputs when the backend is disabled.
- An optional `NCNN extra args` field for advanced Real-ESRGAN NCNN flags such as `-dn 0.2`, with settings/profile persistence and command-line validation.
- An explicit expert override that can force technical maps such as normals, masks, roughness, height, and vectors through the generic visible-color PNG/upscale path when you intentionally want unsafe technical processing.

### Changed
- Texture policy is now planner-authoritative across preview, preflight, direct backend execution, DDS rebuild, `Compare`, and `Research`, so path/profile/backend/alpha decisions come from one shared per-texture plan instead of being re-inferred later in the run.
- Automatic texture policy now routes source-match correction per texture instead of expecting the user to know which post-correction mode belongs to which asset class.
- Built-in output behavior is now formalized through planner-selected processing profiles, explicit path kinds, centralized backend capability gating, and semantic/profile/intermediate overrides in texture rules.
- `chaiNNer` and direct `NCNN` capability handling now follows the same central planner matrix used by policy preview and preflight reporting.
- `Compare`, `Preview Policy`, and `Research` now surface richer planner metadata, including selected profile, processing path, backend compatibility, alpha policy, and preserve reasons.
- `Safe Wizard` has been replaced by a read-only `Run Summary` dialog, so the editable backend and texture-policy controls live only in the main Workflow panel while the dialog is reserved for source and run-context review.

### Fixed
- Planner-driven preserve handling is now more reliable for technical DDS files because technical textures no longer silently fall back into the generic visible-color PNG path.
- Scalar technical DDS files such as roughness, height/displacement, AO, metallic, specular, subsurface, emissive-intensity, and similar non-packed grayscale data can now rebuild through a safer high-precision path instead of always collapsing into preserve-only or generic color-path behavior.
- High-precision technical rebuilds now validate their `16-bit` grayscale-style PNG intermediates before use, and missing or invalid inputs are called out in preflight and fall back per file to preserving the original DDS instead of rebuilding from a bad intermediate.
- `Research` mip analysis and normal validation now include planner-path-aware warnings, making suspicious visible-color routing, suspicious high-precision routing, and scalar-format mismatches easier to catch during QA.
- The app no longer fails on startup when refreshing `chaiNNer` chain info, because the UI chain-analysis path now passes the staging PNG root expected by the planner-aware `chaiNNer` validator.
- Rebuild format precedence now respects manual `Match original DDS format` when automatic color/format rules are disabled, so visible color textures no longer get silently promoted to planner profile formats such as `BC7_UNORM_SRGB`.
- Automatic texture safety rules no longer inject extra external-converter sRGB flags for visible textures, which reduces the darker output shifts some users were seeing when the safety checkbox was enabled.
- `Source Match Balanced` and `Source Match Extended` no longer skip obviously color-like textures just because their semantic hint stayed `unknown`, as long as the planner already routed them through a visible-color profile.
- Browsing rebuilt DDS files in `Compare` is more responsive because compare preview application now avoids eagerly materializing full preview pixmaps on the UI thread, and rapid compare-row changes are briefly debounced before preview startup.
- Large DDS files in `Compare` now use a lighter display-preview cache capped for pane browsing, which reduces the lag from cold 4K preview generation/loading without changing the higher-detail preview path used by `Research` analysis.
- Archive Browser DDS preview no longer fails with `Preview failed: 'NoneType' object is not iterable` after the recent compare-preview refactor, because the shared preview command builder now always returns a valid converter command.
- Archive Browser DDS preview now uses the lighter display-preview cache for pane browsing too, reducing freezes or long stalls when selecting larger DDS files.
- DDS staging for direct backend runs now passes the source DDS path correctly to the converter again, fixing cases where staging appeared to run but the NCNN stage immediately failed with `Expected planner-selected PNG does not exist`.
- Compare preview shutdown is now safer because queued preview work no longer respawns while the window is closing.
- Settings persistence and `chaiNNer` chain inspection are now debounced in the UI, reducing stalls from keystroke-by-keystroke disk syncs and chain revalidation.
- Preserve-only direct `NCNN` runs now skip the backend stage cleanly instead of scanning unrelated stale PNGs in `PNG root`.
- `Retry with smaller tile` now steps down correctly from a `tile size 0` full-frame attempt into real smaller tiles.
- `Research -> Mip Analysis` now only reports DDS files that exist in both Original and Output roots, instead of turning unmatched files into broken comparison rows.
- DDS preview cache invalidation now includes the active converter identity, so Compare and Research previews are refreshed when the converter binary changes.
- Family-aware classification now upgrades base files such as `cd_wood_planks_02.dds` to color/albedo when sibling variants like `cd_wood_planks_02b.dds` and `cd_wood_planks_02c.dds` indicate a visible color texture family.
- Family-aware classification now also upgrades trailing-letter variant-only sets such as `cd_wood_planks_02a.dds` and `cd_wood_planks_02b.dds` to color/albedo variants even when the plain base file is missing from that package.
- Bare `rough` in names such as `cd_wood_rough_06.dds` is no longer treated as a hard roughness-map token, so material-name families can fall back to family/preview evidence instead of being misclassified as roughness.
- Compare preview is more defensive when browsing rebuilt DDS files because preview widgets now cache the decoded display image instead of re-reading the same preview file on every resize/zoom, and the compare display-preview cap has been lowered to reduce memory pressure on large upscaled textures.
- Compare preview loading now preloads the decoded display image in the worker thread before applying it to the UI, further reducing main-thread PNG decode work when Compare opens right after a build or when rapidly selecting rebuilt DDS files.
- Compare preview no longer goes blank after the worker-thread preload change, because preview widgets now correctly treat preloaded in-memory images as a valid preview source.

### Docs
- Updated README/help/release wording to reflect `Run Summary`, browser-only external setup/model pages, automatic `Source Match` correction, the high-precision technical path, the expert unsafe technical override, and the current direct-backend workflow.

## [0.4.1] - 2026-04-11

### Changed
- Setup download actions for `chaiNNer`, the former external DDS converter, and `Real-ESRGAN NCNN` now open the official external pages in the user browser instead of downloading files inside the app.
- `NCNN Model Catalog` now exposes source/model pages and opens non-downloading external browser pages instead of downloading selected model files inside the app.
- `Research` refresh now computes archive-side grouping, classification, and heatmap data in one shared snapshot pass, and repeated refreshes can reuse that archive snapshot while the current archive view is unchanged.

### Fixed
- Archive Browser DDS preview is less likely to freeze the app while browsing cached archives because image preview loading now avoids eagerly materializing the full preview pixmap on the UI thread.
- Archive Browser DDS preview is more stable while rapidly browsing `.dds` entries because preview requests are now briefly debounced before worker startup.
- DDS preview cache generation is now serialized per cached source file, reducing random crashes or invalid preview loads when multiple fast preview requests hit the same cached PNG at nearly the same time.
- Automatic texture rules now preserve technical DDS files more reliably even when the upscale backend is disabled, instead of rebuilding some of them from staged PNGs.
- Normal maps that appear to use alpha are now rebuilt with an alpha-capable linear format instead of dropping alpha through the default BC5 path.
- Closing the app during long-running scans or `Research` refresh work now signals those workers to stop before thread shutdown, which makes shutdown behavior less rough.
- `Retry with smaller tile` now steps down through real fallback tile sizes even when the configured tile size is `0`.
- `Compare -> Mip Details` now clears its pending target when a `Research` refresh fails, avoiding stale focus jumps on the next refresh.
- `_ct` texture variants are now classified as color maps before loose token matching, reducing false roughness/metalness classification when the base name contains those words.
- The `Safe Upscale Wizard` now preserves caller-provided summary or notes text instead of overwriting it with its generated footer summary.
- `Research -> Archive Insights -> References` now drives the `Archive Files` picker to the relevant archive file when you select a reference or sidecar row, making it easier to inspect the specific `.dds` or related archive file in the current workflow.
- `Research -> Archive Insights -> References` now resolves nested archive folder paths more reliably when focusing the `Archive Files` picker from a selected reference or sidecar row.
- Closing the app during a long `Research` reference resolve now signals that resolver to stop before thread shutdown instead of leaving it to run to completion.
- `Research` refresh progress now reports the current archive snapshot, mip analysis, and normal-validation stages with consistent step counts instead of jumping over missing progress indices.
- Archive Browser refresh/scanning no longer errors when preparing the cached browser state, because `prepare_archive_browser_state` now accepts the worker cancellation token passed by the archive scan path.

## [0.4.0] - 2026-04-11

### Added
- `Research` tab for texture-focused support work, including:
  - texture-type classifier
  - texture set grouper
  - material-to-texture reference resolver
  - archive-side sidecar discovery
  - extract-related-set actions
  - mip/export report support
  - bulk normal validation
  - texture usage heatmap
  - local research notes
- `Safe Upscale Wizard` for guided backend, preset, retry, and export setup.
- Direct in-app upscaling backend support for:
  - `Real-ESRGAN NCNN`
- Setup actions for:
  - downloading and unpacking `Real-ESRGAN NCNN`
  - importing NCNN model files
- Grouped `NCNN Model Catalog` with:
  - short model descriptions
  - intended-use notes
  - source links
  - direct download for selected ready-to-use `.param` / `.bin` pairs
  - grouped recommendations for visible color/albedo, compressed color, cleaner color, stylized/UI, and experimental models
  - detected local NCNN models shown beside the built-in list
- Optional direct-backend post-upscale color correction modes:
  - `match_mean_luma`
  - `match_levels`
  - `match_histogram`
- Compare preview-size presets that scale both compare panes together.
- Mouse-wheel zoom on image previews in `Compare` and archive image preview.
- Quick `Mip Details` action in `Compare` that refreshes `Research`, opens `Texture Analysis`, and jumps to the selected compare file when a matching mip-analysis row exists.
- VS Code-style live-log highlighting for actions, statuses, paths, dimensions, texture tags, and key values.
- Archive Browser exclude filtering with:
  - custom semicolon-separated substring or glob exclusions
  - a one-click option to hide common DDS companion suffixes
  - a `Base / likely albedo images` role filter for easier base-texture browsing

### Changed
- Workflow upscaling now supports backend selection, texture-type-aware presets, automatic color/format safety rules, retry with smaller tile, and mod-ready loose export.
- `Init Workspace` now seeds the newer NCNN and mod-export path fields in addition to the original workspace folders.
- Real-ESRGAN NCNN setup now handles the current upstream Windows package layout, which may ship without bundled models, by creating a model folder automatically and prompting model import instead of failing.
- Safe Upscale Wizard and direct-backend help text now explain more clearly that presets only decide what gets sent to the upscaler, while the selected model can still shift brightness, contrast, and detail.
- Workflow now includes a `Preview Policy` action that shows a per-texture plan before `Start`, including inferred semantic subtype, action, alpha/intermediate policy, and planned DDS rebuild format.
- DDS parser support now includes legacy numeric `D3DFORMAT`-style FOURCC values used by some Crimson Desert float/vector DDS files.
- Texture-type classification and automatic policy rules now treat `height` / `displacement` / `bump` and `vector` / `position` style maps as higher-risk technical data instead of generic image textures.
- Semantic inference now uses a broader loose-sidecar text set (`.xml`, `.material`, `.shader`, `.json`, `.lua`, `.txt`, `.ini`, `.cfg`, `.yaml`, `.yml`) so displacement, packed-mask, and alpha-cutout intent can be inferred from neighboring material/shader files instead of filenames alone.
- Safer presets now preserve excluded technical DDS files by copying the original DDS through unchanged instead of rebuilding them from PNG intermediates.
- Preflight reporting now summarizes detected texture types, semantic subtypes, and per-texture action counts, and warns when float/vector DDS files are present, so risky PNG-intermediate cases are visible before a run starts.
- DDS Output help text now states more clearly where source PNGs, final PNGs, and rebuilt DDS files end up, and clarifies that `Use final PNG size for rebuilt DDS` only affects DDS dimensions.
- The direct-backend controls area is now hidden when `chaiNNer` is the active backend.
- Workflow now exposes `Texture Policy` as its own always-visible group, so preset/automatic-rule/export behavior is easier to find without opening `Safe Wizard`, while direct NCNN scale and tile controls stay clearly separated.
- Top-level tab order now places `Research` ahead of `Text Search`, and the `Research` tab now includes its own `Archive Files` picker so reference and note workflows do not require jumping back to `Archive Browser`.
- Archive related-set extraction prompts now state the destination path up front, explain that the extract root may be created automatically, and make overwrite-vs-keep-both behavior clearer before the extraction starts.
- `Archive Browser -> DDS To Workflow` now respects explicit archive selection first. If files or folders are selected, only selected DDS files are extracted to the workflow root; the filtered DDS view is used only when nothing is selected.
- `Research -> Texture Analysis` now explains where each result set comes from, what each panel requires, and shows the selected-row details in the right-side pane where `Archive Files` normally sits, so mip-analysis details have more room when that subtab is active.
- `Research -> Texture Analysis` now exposes richer texture QA details for matching DDS pairs, including file-size drift, color-space changes, preview-based alpha/brightness/channel checks when converter previews are available, and extra texture-specific warnings for normals, packed masks, and grayscale technical maps.
- `Workflow -> Upscaling` now keeps the backend-specific area sized to the current backend page instead of inheriting the tallest backend page, reducing the wasted empty space when direct NCNN pages are selected.
- Texture classification is now more tolerant of Crimson Desert-style texture sets by recognizing suffixes and explicit names such as `_cd`, `_sp`, `_m`, `_ma`, `_mg`, `_o`, `_disp`, `_dmap`, `_dr`, `_op`, `_wn`, `_emc`, `_emi`, `_subsurface`, `_color`, `_normal`, digit-letter variants like `63a`, family companions, and preview-based fallback hints when names are still ambiguous; `_d` is no longer treated as a strong diffuse/color signal and is instead handled as lower-confidence grayscale/support data.
- `Research`, `Texture Analysis`, normal validation, mip-detail hints, and `Archive Browser` role/exclude filtering now use the same updated suffix semantics, so technical companions such as `_wn`, `_ma`, `_mg`, `_o`, `_dmap`, `_dr`, `_op`, `_emc`, `_emi`, and `_subsurface` are less likely to be mistaken for base/albedo textures.
- Direct Real-ESRGAN NCNN workflow controls now expose optional post-correction modes in both `Workflow` and `Safe Upscale Wizard`, and build/preflight logs now report the selected correction mode.
- `Compare` now acts as a focused review mode: the progress area collapses while `Compare` is active, the top chrome is more compact, the default compare splitter favors preview space more strongly, and previews stay top-aligned instead of floating in the middle of the pane.
- Compare review now supports shared preview-size presets, wheel zoom, drag pan, per-side zoom, and stronger space prioritization so side-by-side review is easier on smaller or scaled displays.
- Workflow, Research, Text Search, archive preview, and global theme sizing were adjusted to behave better under UI scaling, including safer button/progress heights, tab/group title spacing, and toolbar wrapping in dense panes.
- The right-side workflow layout now remembers a normal progress-panel size separately from Compare focus mode so switching tabs does not save a broken collapsed state.

### Fixed
- Archive Browser DDS preview is less likely to freeze the app while browsing cached archives because image preview loading now avoids eagerly materializing the full preview pixmap on the UI thread.
- Restored the missing workspace helper functions used by `Init Workspace` and `Create Folders`, which caused `name 'create_missing_directories_for_config' is not defined` style failures in the Setup section.
- Profile export and diagnostic bundle export now serialize config data correctly for slotted dataclasses, fixing `vars() argument must have __dict__ attribute` failures.
- Harmless chaiNNer shutdown/deprecation noise such as `body not consumed` and `log.catchErrors is deprecated` is now filtered so successful runs do not look like hard failures.
- Legacy float/vector DDS files that previously failed with unsupported FOURCC errors now parse and rebuild correctly, including real tested cases such as `pivotpos` and `xvector` effect textures.
- Runs that select an upscale backend but end up preserving every matched DDS under the current preset/automatic rules no longer fail early on missing NCNN / chaiNNer runtime setup; backend validation is now deferred until files actually require PNG/upscale processing.
- Backend/staging/PNG indexing work is now skipped when the current semantic policy keeps every matched DDS out of the PNG path, avoiding unnecessary empty-stage work and confusing stale-PNG scans.
- `Research -> Archive Insights -> Groups` selection is now more robust: the first group is auto-selected after refresh, the extract button reflects whether a valid group is selected, and selecting either a group row or one of its member rows resolves correctly for `Extract Selected Set`.
- `Research -> Archive Insights -> Groups` now warns explicitly when the research snapshot has not been built yet, so clicking `Extract Selected Set` before `Refresh Research` no longer feels like a silent failure.
- `Research -> Texture Analysis` no longer repeats the same brightness-range warning in both `Preview comparison` and `Additional analysis warnings` for the same DDS pair.
- Compare/preview sizing no longer wastes as much vertical space above the images, and stale saved splitter states from earlier layouts no longer force the progress block back into an oversized or clipped state.
- Compare previews now use the actual displayed scale when zooming out of `Fit`, avoiding the earlier jumpy behavior where zoom started from an assumed `100%` baseline instead of the real fitted size.

### Docs
- Rewrote `README.md` around the current app structure, including direct NCNN support, `Safe Upscale Wizard`, `Texture Policy`, `Preview Policy`, `Research`, compare review workflow, and troubleshooting guidance.
- Updated the in-app `Quick Start` guide so it now describes the current safe-first workflow, backend choices, texture-policy safety behavior, compare controls, and `Research` usage more clearly.
- Expanded `Unreleased/In testing` notes to include the recent compare UX, preview interaction, live-log, and UI-scaling changes.

## [0.3.0] - 2026-04-08

### Added
- New global `Settings` tab for persistent app-wide preferences such as theme, startup behavior, layout memory, and cleanup confirmations.

### Changed
- Archive refresh and cache-building performance were optimized significantly by fixing the real bottlenecks in `.pamt` parsing and cache generation.
- On the large development archive set used during testing, full refresh + cache build dropped from roughly `315s` to about `4s` (about `99%` faster), while cached tree preparation dropped from about `3.7s` to `2.0s`.
- Archive tree/browser-state preparation was also reduced further during cached loads.
- README was reorganized into a shorter, more scannable structure.

### Fixed
- Removed the experimental 3D/model viewer path from the live app so the shipped workflow stays focused and stable.
- Removed the top-menu theme picker now that theme selection lives in `Settings`.

## [0.2.1] - 2026-04-08

### Changed
- Windows build output now uses a versioned release-style filename pattern for the portable executable.

## [0.2.0] - 2026-04-08

### Added
- Broader archive package root auto-detect support for common non-Steam installs, including custom `Games` folders and shallow `XboxGames` / `ModifiableWindowsApps` style layouts.
- Environment-variable overrides for archive package root detection:
  - `CRIMSON_TEXTURE_FORGE_PACKAGE_ROOT`
  - `CRIMSON_DESERT_PACKAGE_ROOT`
- New read-only `Text Search` tab for archive or loose text-like files, with content search, highlighted preview, and export of matched files while preserving folder structure.
- Archive text search now supports deterministic ChaCha20 decryption for supported encrypted XML entries, so those files can be searched, previewed, and exported as readable text.
- Editor-style text preview with syntax coloring, line numbers, local find/next/previous navigation, wrap toggle, and font-size controls.

### Changed
- Archive auto-detect now reports that it is checking known install locations instead of only Steam libraries.
- Text Search preview now uses a larger three-pane layout and shows full text for normal-sized files with clearer match highlighting.
- Text Search results now prioritize file name first, while keeping the full relative path visible in a dedicated column and tooltips.
- Small-window layout pressure was reduced slightly so the workflow and utility panes degrade more gracefully.

### Fixed
- Text Search preview font size controls now update the editor text, gutter, and document font correctly.

## [0.1.0] - 2026-04-07

### Added
- Initial public release.
- Read-only `.pamt` / `.paz` archive browser with selective DDS extraction.
- Archive cache for faster repeated archive scans.
- Loose DDS scan/filter workflow.
- Optional DDS-to-PNG conversion with the legacy external converter.
- Optional external `chaiNNer` stage before DDS rebuild.
- DDS rebuild with configurable format, size, and mip behavior.
- Side-by-side DDS compare view with zoom and pan.
- Profile export/import and diagnostic bundle export.
- Built-in Quick Start and About dialogs.

### Changed
- App configuration is stored beside the executable for portable use.

### Docs
- Added project README, dependency notes, credits, limitations, and screenshots.
