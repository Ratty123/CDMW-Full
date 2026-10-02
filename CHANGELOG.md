# Changelog

Release notes describe changes in each version. Older entries are historical;
use the latest release's availability and limitations when deciding what to use.
Related changes are grouped under Added, Changed, Fixed and Docs. Preview and
experimental-feature notes do not establish equivalent in-game behavior.

## [Unreleased]

### Added

- Report a Problem is available below Support Me in the sidebar with a bug icon. Its five-step guided form has tool/action menus, relevant input and setup choices, stall questions and optional **?** help. It includes a readable review, fitted screenshots, redacted evidence, a receipt screen and saved drafts for retry. Public clients use a browser verification check without shared access keys; reports go to a separate private GitHub repository with duplicate protection, submission limits and retry guidance. Destination and privacy details are available through optional help.

### Changed

- Problem reports collect recent activity and logs across tools, detailed worker and helper failures, crash or hang evidence and build fingerprints. Evidence refreshes when preparing a draft, with missing or truncated sources identified in the reviewed report.
- Faster archive browsing, effects-library discovery and effect metadata loading. Browse Archives and Mesh Editor prepare model geometry and textures faster on the first load after restarting. Browse Archives reuses the existing catalogue for shared shader defaults, avoiding the initial scan of unrelated materials. Create New Item uses a smaller working cache for archive lookups, reducing startup work and memory use. Layered model textures decode in parallel, and Mesh Editor texture follow-ups reuse unchanged prepared dependencies.
- Archive Browser uses the standalone backend exclusively; legacy `CDMW_ARCHIVE_BACKEND` overrides are ignored.
- Item Finder places categories and item counts on the left, results in the centre and details on the right, with remembered pane widths.

### Fixed

- Mesh Editor no longer rejects Finish Edit Mesh when Windows uses a redirected temporary folder.
- Rapid tool switching pauses inactive tool preparation, list updates and automatic previews. Recently used previews resume without recreating their renderer, and embedded-window focus and resizing avoid unnecessary work during navigation.
- Completed problem-report browser checks keep their success message when the used verification token expires.
- Dropdown lists open below their fields when space allows and scroll instead of expanding around the selected item.
- Mesh interchange preserves supported material maps and values, UV sets, vertex colours, skin weights, rigs, morph targets and existing animation clips. Export packages include portable textures, game metadata and format-limit reports.
- Meshes returned from Blender retain part/material assignments, local coordinates and bounds after renaming or reordering. Companions recover missing UV sets and textures; geometry-only meshes can return without unwrapping.
- FBX import uses the selected Blender, supports cancellation and retains all bone influences and correct vertex colours. FBX export accepts mixed numeric vertex data.
- Archive Browser's Export OBJ dropdown opens the export workflow for the selected mesh without requiring a loaded preview.
- Item Finder keeps category names, item captions and actions readable at narrow widths and larger fonts; long details wrap without changing copied text.
- Select Extension closes reliably after selection and becomes available with extension counts as archive rows load.
- Hair Tools lets users preview unavailable hairstyles and read their compatibility reason while keeping Start disabled. Styles with separate base and tail meshes remain unsupported.
- Archive loading and item indexing retry temporary failures once. Stalled work stops after five minutes without progress and offers retry and error details; item-name failures leave archive browsing available.
- Later launches reclaim abandoned temporary data while preserving active sessions, recovery backups and export history.
- Archive scans exclude backup vaults, preventing extraction failures from missing backup files. Existing affected catalogues rebuild automatically.
- ZIP exports retain complete mod folder names, including dots and manager suffixes. Repackage Mods avoids filename-selection loops and remains cancellable.
- Model Library keeps checked models through sorting and refreshes, and removes missing models from batch selections.

### Docs

- Reorganized feature guides for clearer navigation while retaining detailed workflows and compatibility limits.

## [0.11.0-alpha.22] - 2026-09-29

Expanded Mesh Editor and Create New Item authoring, material and physics controls,
mod management, and faster previews. This release includes the unpublished
alpha.21 checkpoint; alpha.20 was the previous GitHub release.

**Export availability:** Create New Item supports CDUMM (the default), JMM and
CDMW game overlays. Its DMM export is temporarily disabled while compatibility
issues are investigated. Mesh Editor replacement exports still offer DMM, JMM,
CDUMM and Crimson Sharp.

**Experimental features:** Material and shader experiments, generated cloth guides,
and item visibility overrides still need in-game testing. Overlapping transparent
surfaces can show triangles or other visual artifacts. Physics and material
previews approximate the game; preview motion, wind and collision settings do not
change saved mesh or profile settings.

### Added

- Mesh Editor adds percentage adjustment and height-based gradients for retained jiggle influence across stored levels of detail (LODs), with Undo/Redo and saved drafts.
- Jiggle and Cloth previews offer current/original/disabled comparisons, Freehand model movement, and supported rig, wind and body-collision controls. Region colours and tint help identify jiggle influence; Keep model centred is enabled by default.
- Mesh Editor can edit cloth physics profiles by variant and assignment group, restore source values, and include the edited profiles in Build Mod. Profile-only edits leave mesh geometry unchanged. Preview can load supported profile settings; editing a profile does not create missing cloth bindings.
- Mesh Editor can generate experimental cloth guides for compatible parts without guides, using existing bones and an adjustable pin height. Guides support Undo/Redo, drafts and mod output. Reducing skin weights is optional; adding new skeletal bones is unsupported.
- The Parts inspector can select, hide and isolate connected mesh islands, or exclude them from original-mesh output across supported LODs. Output exclusions are reversible and retained in drafts.
- Create New Item supports Move, Rotate, Scale and appearance edits on the template itself, without importing a replacement model. Changes stay with the selected variant.
- Create New Item and Mesh Editor offer per-part experimental translucency with absorption presets, thickness/extinction settings, roughness and metallic controls, and source restoration. Static glow can be retained, although game brightness may differ; incompatible animated/RGB glow combinations are identified before export.
- Create New Item can paint transparency and experimental hard cutouts across a part's texture. The painter includes soft brushes, an overlay, Undo/Redo, source restoration, separate Colour coverage and Surface response masks, Linked fade, PNG import/export, fill, invert and gradients. Masks stay with their variant and are included as item-specific textures in supported output formats.
- Create New Item adds Surface colour and reflections controls, including Match glow colour, independent roughness/metallic edits and a Low-shine preset. Unedited parts retain their source appearance.
- Create New Item and Mesh Editor offer experimental scrolling, pulsing and RGB glow, plus compatible material experiments such as Patterned reveal, Torn cloth, Moving hair textures, Surface detail and roughness, and Glowing band sweep. Mesh Editor also exposes supported dissolve controls. Unsupported material combinations explain why they are unavailable.
- Create New Item offers experimental per-variant options to retain underlying skin/head and hair/beard. Its separate, default-off Character visibility test changes a shared character shader and can affect other materials, including eyes; neither option is simulated by the viewport.
- Hair Tools adds a Static/Physical brush with colour feedback, symmetry, optional selection restriction, Undo/Redo and drafts. Static removes retained cloth influence from painted hair; Physical retains the template's physics.
- Installed overlays can be enabled, disabled and rebuilt for the current game with dependency and ownership checks, while retaining individual recovery history.

### Changed

- Mesh Editor numeric controls share exact typing, focused wheel/arrow adjustment and adjustable increments, including custom steps. Sliders align consistently across physics, transforms, brushes, topology, UVs, rigging, Hair Tools, materials and Vertex Parameters.
- Create New Item and Mesh Editor can save an optional ZIP beside the mod folder and open the completed folder. Create New Item adds editable mod names, clearer Add to existing mod instructions and a separate folder for each new mod; fresh exports refuse existing destinations.
- Mesh Editor packages contain the required game files and manager metadata. CDMW authoring and compatibility history stays locally for later editing and recovery.
- Mod Management is available under Utilities, with a searchable inventory, installed-item preview, file/history inspection, and merge, update and recovery tools. Overlay health and game-build compatibility are shown separately.
- Assets navigation is ordered Browse Archives, Create New Item, Model Library and Item Icons. Window sizes, split panes, preview proportions and resized columns are remembered across restarts and kept within the available screen.
- Create New Item uses one interface and a more compact workspace: viewport transform controls remain accessible, tables use the available height, and Output separates file review, Activity and Destination. Perks, sockets and bonuses share an Experimental Features tab; recipes and loot/rewards retain their experimental labels.
- Startup prepares Create New Item's archive data in the background and opens the interface on demand. Effects indexing starts when the workspace is ready. Preview preparation and repeated texture conversions reuse completed work while retaining texture quality, and long operations show progress and support cancellation.
- The effects library uses clearer names, categories and variant grouping, with improved search, favourites, thumbnails and timing information. Missing timing data is shown as Unknown.
- Hair Tools starts new hairstyles empty and produces smoother drawn cards. Existing saved hairstyles retain their geometry.

### Fixed

- Build Mod uses the revision accepted by Finish Edit Mesh instead of requiring an unnecessary repeat validation. Profile Undo/Redo, large jiggle data, empty lower-LOD parts and case differences in profile assignments no longer prevent supported edits from finishing.
- Create New Item detects custom items already present in loaded game tables and refuses to silently include them in a fresh separate mod. Explicit Add to existing mod remains available.
- Turning Template cloth / physics off removes inherited cloth and jiggle bindings from every output LOD and clears material simulation assignments, preventing template physics from displacing imported parts.
- Imported materials retain unedited colours, textures, transparency, emission and surface maps. Appearance changes target the selected part even when parts share textures or material names; discarding an import restores the template's appearance.
- Painted transparency survives material composition and works with colour-only imports. Painters open before Apply placement without rebuilding unrelated export textures, and source restoration preserves untouched channels.
- Glow, translucency, shader and compatible dye edits remain consistent across Model & Placement, Effects, dye previews and output. Layered template materials no longer fail solely because they lack a simple base-colour map. Glow supports compatible skin materials and preserves more texture detail in preview.
- FBX and other model imports retain normal, roughness, metallic and emissive maps correctly. BC7 colour textures preserve their colour space and alpha, reducing colour noise and avoiding unintended brightness changes.
- Model and Effects previews retain the camera while textures or appearance updates load, frame newly selected models reliably, and keep the grid and gizmos aligned. Template and character visibility remain consistent through rapid switches and cached updates.
- Effect previews improve supported lightning geometry, animation, colour curves, brightness and mesh-surface emission. Missing source geometry is reported instead of replaced with fabricated particles. Surface-dependent effects require a target mesh in game; preview placement does not verify that attachment.
- Effect editing preserves inherited curves, supported field layouts, infinite lifetimes and source references. Unsupported structural edits remain blocked; effect changes and material refreshes retain staged edits and placements.
- Hair Tools preserves skin/cloth records, texture bindings, Include in Mod choices and separate Undo steps through drawing, cutting, grooming and draft recovery. Short locks respond to brushes, close-fitting hair stays near the scalp during motion, and hidden or empty hair scenes no longer crash.
- Hair selection supports current and repeated barber registrations without duplicate choices. Compatibility checks retain the selected hairstyle, and unsupported registrations explain why they cannot be used.
- Cloth preview reduces excessive stretching and artificial launch motion from initial body overlap. Gravity follows the profile's sign, including upward gravity, and missing guides are distinguished from unreadable guide data.
- Archive and model previews preserve complete garments, material ownership and neutral appearance. Browse Archives retains authored clothing colours and layer strengths, including garments without a base-colour texture. Updated PAM/PAMLOD geometry, root-prefixed texture paths, layered materials and supported low-poly models load correctly.
- Item Finder and Create New Item read compressed localization tables, retain valid Unicode names and report unsupported formats with their archive source. Body & Face Finder tolerates malformed comments in shipped wrinkle metadata; facial exports retain case-distinct targets.
- Installed-overlay previews read current mounted geometry and materials, refresh after changes, and load independently of Create New Item. Installation and rebuild checks retain other overlays' table and texture registrations and reject conflicting ownership.
- Placement & Animations validates package names, preserves complete backups when replacing output, and includes only selected operations. Reloads retain pending edits and Undo/Redo; failed preparation can be retried without losing the previous scene.
- Preview loading, cancellation, retries and shutdown handle obsolete work without freezes or late results replacing the current selection. Mesh Editor can use prepared archive textures while Browse Archives is hidden, and application shutdown safely handles outstanding helpers and imports.
- Create New Item and Mod Management keep controls readable and reachable at different font sizes, window sizes and monitor scaling. Text entry, dropdowns, section toggles, status messages and theme feedback behave consistently without duplicate controls or excessive empty space.
- Recolor rejects stale source analysis, Model Library separates catalogue caches correctly, and text search keeps Unicode highlighting and navigation accurate. Game-version labels and compatibility details display correctly.
- Completed translations for the built-in languages across Mesh Editor, material and physics tools, Hair Tools, selectors, status messages and Format Explorer. Open tools update when the language changes.

### Docs

- Updated in-app help for material experiments, Vertex Parameters, cloth profiles and current tool availability.

## [0.11.0-alpha.21] - 2026-09-20

Unpublished local checkpoint. Its jiggle, cloth, translucency, loading and hair
changes shipped in alpha.22 and are included in that release's notes above.

## [0.11.0-alpha.20] - 2026-09-18

### Added

- Experimental jiggle Disable/Restore controls for selected mesh parts, optionally limited by height. In-game verification was still pending at this release.

### Fixed

- Fixed an intermittent startup crash in Browse Archives' More Filters menu.
- Mesh Editor Finish and Cancel no longer access an already closed session. Hair Tools and late replies respect Finish cleanup.
- Current Tool Log shows Mesh Editor progress, failures and final outcomes.

## [0.11.0-alpha.19] - 2026-09-17

### Added

- Vertex Parameters shows individual values and batch ranges, with reversible position, UV, normal and supported skin-weight edits.

### Changed

- Mesh Editor uses compact tool tabs, collapsible headers and movable panels, including multiple floating panels during viewport editing.

### Fixed

- Tool panels, Morph & Refit settings and flyouts remain within the available workspace without covering controls or leaving empty rows.
- Vertex edits and original mesh bounds survive draft recovery. Skin-weight editing remains unavailable when neutral-appearance transforms would make saved positions unsafe.

### Docs

- Updated Mesh Editor help for tool navigation, movable panels and Vertex Parameters.

## [0.11.0-alpha.18] - 2026-09-17

### Added

- Cloth controls can reduce or disable retained influence, pin vertices above a height and fade movement below it across stored LODs. In-game verification was still pending at this release.
- Mesh Editor can hide and restore its Tools and Inspector sidebars independently or together.

### Fixed

- Preview loading, cancellation, cache cleanup and retries no longer lose current packages, retain failed work unnecessarily or leave capture controls waiting. Hidden previews release GPU resources; the reported Blender/NVIDIA driver-reset scenario still required reporter testing.
- Replacement drafts recover original materials, hair transparency and valid saved textures after cache cleanup, and reject malformed state without replacing the last valid edit.
- Normal, UV, position and skin-weight edits survive cloth/mod output, part replacement and draft recovery while preserving untouched LOD data. Unsupported UVs, bone counts and cloth-guide references are rejected before saving.
- Repeated replacements retain the original skin donor. OBJ and glTF/GLB imports preserve material regions and distinct textures, resolve valid material-library paths, and reject invalid geometry or changed external inputs.
- Keep Original Materials accepts geometry-only OBJ files even when their old material references are missing.
- Status details are selectable and copyable; new diagnostics follow all built-in languages.
- Browse Archives resolves material dependencies for Asset Family and export even with Load textures off.
- Overlay installation can recover stale, unmounted sets with backups and reports failures clearly. Game-update checks show progress without repeatedly checking the same directories.
- Create New Item fixes rolled placement views and an Effects preview startup crash.

### Docs

- Updated cloth, replacement, status and sidebar help, including preview and restoration limits.

## [0.11.0-alpha.17] - 2026-09-14

### Added

- Hair Draw offers Freehand, Straight, Arc and Circle strokes, smoothing, arc bend and adjustable Move reach. Hair Tools remains experimental and was not yet verified in game.
- Translations opens existing `.paloc` language mods without a configured game installation, retaining their text and language slot.

### Changed

- Hair Tools provides one Create/Edit setup for Kliff, Damiane and Oongka, with a clean fitting mannequin and explicit experimental guidance.
- Eligible mesh replacements no longer require an extra confirmation button; neutral-appearance replacement retains its experimental warning.

### Fixed

- Hair drawing follows the scalp, keeps roots and texture spacing stable, and retains valid skin records, short guide segments and texture transparency through grooming, Undo/Redo and drafts. Unsupported motion and registrations report a reason.
- Existing hair can be excluded and restored without rewriting its original skin records. Repeated loading and cancelled thumbnail requests no longer strand choices.
- Translations follows mounted archive order, supports current per-language tables and named dialogue keys, refreshes filters and paths, and exports to each table's original location. AI dialogs close safely during active requests.
- The reporter confirmed the bulk texture replacement workflow from alpha.16 resolves [issue #22](https://github.com/Ratty123/CDMW-Full/issues/22).

### Docs

- Updated Hair Tools help for setup, drawing, original-hair editing and experimental limits.

## [0.11.0-alpha.16] - 2026-09-14

### Added

- Body & Face Finder browses bodies, heads, facial details, hair and beards across player, NPC, creature and mount families. Show underwear hides or restores separate underwear parts in preview.
- Textures > Replace supports bulk PNG/DDS replacement, folder reload, batch editing, automatic matching and mod output without opening each image separately.
- Experimental hair authoring for Damiane includes grooming, existing-hair binding, textured cards, character references and motion preview.
- Mesh Editor supports part replacements with manual placement, reversible Include in Mod choices, original/output comparison and complete material/texture companions. Neutral-appearance replacement is explicitly experimental.

### Fixed

- Finder thumbnails load concurrently without cache-publication errors, retain the correct neutral body/head shape and omit unrelated or unresolved models.
- Bulk replacement gives the queue adequate space and reports progress safely. Reporter confirmation for [issue #22](https://github.com/Ratty123/CDMW-Full/issues/22) was pending at this release.
- Hair reference loading can retry failures without accepting obsolete results, and uses matching character references.
- Mesh replacements preserve untouched parts at every LOD; refit drafts retain textures after cache cleanup. Rig matching and weight transfer preserve supported original influences and explain rejected edits.

### Docs

- Updated feature help and translations for Replace, Body & Face Finder and mesh authoring.

## [0.11.0-alpha.15] - 2026-09-11

### Added

- Check mods for game updates compares exports and installed overlays with their recorded game build and original files.
- Merge mods reviews selected packages and combines compatible changes, with conflicts reported before output.
- Installed overlays lists individual installs and can remove one while preserving the remaining items and shared registrations.
- Armour imports can transfer weights across template sections and use a verified matching character body when needed.

### Changed

- Create New Item installs through tracked game overlays. Its seven-step layout is more compact, with clearer identity, model, distribution and output controls.
- Morph & Refit adds clearer asset roles and archive body/armour comparisons with independent Solid/Wire views and camera controls.

### Fixed

- Garment fitting better preserves layers and local shape, reduces sleeve/cuff spikes and underarm clipping, and pushes intersecting clothing outward. Manual adjustment can still be required.
- Archive refit retains separate neutral-appearance mappings through edits, drafts and output. Archive pickers work in detached windows and handle long or Unicode paths.
- Imported materials preserve colour, opacity, normal strength, emission and independent roughness/metallic maps, including shared textures. Unsupported shader behavior is reported; dye assignments are opt-in and reset for a new import.
- Weapon and wearable imports preserve orientation and attachment weights without inheriting unrelated donor influences.
- Overlay removal preserves other mods' registrations and rejects ambiguous ownership. Fresh installs after complete removal use the current game, and archive state refreshes before another item is allocated.
- Plan rebuilding recognizes an existing mod folder correctly. Set price to 1 Copper handles missing prices and embedded perk costs while retaining bonuses.
- Effect previews correct force, particle size and colour ramps. Search, large morph controls and scaled layouts remain responsive and reachable.

### Docs

- Updated fitting, overlay, merge and compatibility guidance. Portable packages include the README, changelog and security policy.

## [0.11.0-alpha.14] - 2026-09-09

### Changed

- Standalone Mesh Replacement entry points were temporarily disabled for release-scope review. Import setup became more compact and defaulted to retaining the target's materials.

### Fixed

- Create New Item fits imported models to the placement grid while preserving direction, size and grip/centre alignment, including broad models such as shields.
- Replacement previews accept alignment updates, and source pickers can use background processing.
- PAM replacement reports a failed required PAMLOD rebuild instead of silently omitting it. Geometry-only replacements can retain target materials when an OBJ has no usable material library.

## [0.11.0-alpha.13] - 2026-09-09

### Changed

- Placement & Animations improves playback and scrubbing responsiveness, reuses unchanged body and armour geometry, and keeps selection and gizmos live during cached drawing.

### Fixed

- Changing animation clips stops previous playback and prepares the new clip in the background while retaining the last usable preview.
- Character previews, Mesh Editor and neutral exports apply the correct facial shape. Ordinary OBJ export retains original coordinates; neutral-appearance export is an explicit choice.
- Mesh edits and OBJ/Blender round trips preserve supported skin data, normals, UVs and lower-LOD bounds. Unresolved or imprecise reconstruction is rejected rather than silently changing the mesh.

## [0.11.0-alpha.12] - 2026-09-08

### Fixed

- Applying translations or exporting language strings no longer constructs unopened tools.
- Temporary-file cleanup respects its time limit, and helper shutdown avoids treating unrelated processes as owned helpers.

## [0.11.0-alpha.11] - 2026-09-08

### Added

- Morph & Refit can select body and armour meshes from the archive catalogue, compare them and bind garments without enabling Free Edit.
- Effects can be combined into reusable recipes with independent placement, visibility and emitter settings. The library supports inherited resources, favourites, variants, thumbnails, playback controls and editable timing, forces and curves.
- Create New Item adds model variants, dye mappings, equipment-bonus presets, socket capacity/costs, enhancement and crafting recipes, multiple shop routes and selected item-use rewards. Gameplay stats and perks remain experimental.
- Placement & Animations brings equipment, linked parts, replacement mappings, shared impact and checks into one workspace with synchronized Before/After playback.
- Mesh Editor is embedded directly in CDMW with a single editor interface. It supports local transforms, sculpting, selection tools, topology, UVs, weights, geometry layers and refit within each format's output limits.
- Replace from Archive lets an archive-backed model use another archive model as a replacement after reviewing the affected files.

### Changed

- Compact Workspace becomes the first-run layout while existing layout choices remain respected. Settings consolidates appearance and general controls and removes unused integration entries.
- Textures combines Edit, Recolor, Upscale and Review & Export around the same assets and edit history.
- Documentation becomes one searchable wiki with an index, topic navigation and history.
- Mesh Editor uses collapsible, themed tool groups and states whether a session supports exact game output, rebuilding or read-only inspection. Unsupported operations explain their limits before editing.
- Model previews display geometry first, then improve materials without resetting the camera. Repeated archive, import and material preparation reuses cached work, and tools open with progress instead of blocking the interface.
- Browse Archives remembers Load textures. HKX actions were temporarily hidden from its menus at this release.

### Fixed

- Archive previews, Mesh Editor and Create New Item preserve layered materials, source colours, dye variants, hair transparency, normal maps, surface response and glow across loading and edits. Missing textures show an explicit limitation while geometry remains usable.
- Imported models retain placement, attachment, tiled textures, alpha and emissive factors. Effects uses the same item materials as Model & Placement, retains the camera and cancels obsolete work promptly.
- Mesh selection and sculpting stay within the intended visible region, preserve normals and commit one reversible edit. Large selections, tool switches and presentation changes no longer corrupt selection or obscure the mesh.
- Validation and output remain tied to the current mesh revision. Unsupported exact-output topology changes are blocked, and stale or failed background work cannot replace a newer edit.
- Placement & Animations loads configured archives in the background and respects clip duration, root motion, attachment relationships and neutral character appearance.
- Item names agree across Browse Archives, Item Finder and Create New Item on current tables and mounted overlays. Newer game-table layouts are accepted.
- PAM/PAMLOD previews and exports retain required geometry, material companions and textures, including long Windows paths. Mesh-only output no longer silently adds unrelated appearance descriptors.
- Overlay allocation avoids occupied archive numbers and stale ownership. Restore and export checks retain recovery information and keep output inside the selected directory.
- Preview startup, retries, texture uploads, hidden windows and shutdown no longer leave frozen controls, stale scenes or stranded helpers. Opening and closing tools during active preparation is handled safely.
- Theme contrast, scaled layouts, panel sizing, text entry and translations work consistently across the supported interface languages.
- Updated dependencies with available security fixes and tightened archive extraction/output path validation.

### Docs

- Updated application, mesh/refit, effects, output and setup guidance to match the available workflows and experimental limits.

## [0.11.0-alpha.10] - 2026-08-28

### Changed

- Layout and theme settings are together under Appearance.
- Create New Item becomes the consistent name for the item-authoring workflow across navigation, handoffs, help and output.

### Fixed

- Exact mesh sessions cannot enter unsupported topology states, and validation enables output only for the revision and destination it checked.
- Mixed refit settings, invalid transform increments and stale control state no longer enable unsafe operations.
- Overlay restore rejects inconsistent ownership, receipts or backup paths before changing files.
- Theme contrast, Compact workspace overflow and preview repainting are corrected. Overlapping helper status updates no longer cause an application-error dialog.

### Docs

- Updated the README and capability guidance to reflect the available tools, Create New Item and archive/effect support.

## [0.11.0-alpha.9] - 2026-08-27

### Added

- Compact Workspace offers a rail-based layout alongside Classic, selected in Settings and applied after restart.
- Create New Item can preview a template on its playable character in Model & Placement and Effects.

### Changed

- Template selection and preview use separate columns, with faster initial geometry and background texture preparation. Search supports combined terms, phrases, OR and exclusions.
- Mesh Editor moves viewport settings into the tool list, leaving more room for Parts, Layers and Action History.

### Fixed

- Compact tools use space consistently, respect font settings and display usable buttons, previews, activity and inspectors at smaller window sizes.
- Mesh Editor adopts the selected theme and opens another mesh after closing the current session.
- Create New Item supports the updated game archives, correct character assembly and equipment attachment routes. A template without a shop price can gain one.
- Imported metals, roughness maps and helmet placement retain their authored appearance and transforms. Character previews and exports use linked neutral-appearance data.
- Material preparation avoids image-read crashes and locked files; remapped archive selections recover during preview loading.
- Corrected Format Explorer editing guidance and localized the compact Archive Browser label.

### Docs

- Corrected the README version badge.

## [0.11.0-alpha.8] - 2026-08-25

### Changed

- Create New Item reuses archive indexes, template previews and compatibility results, reducing repeated work when opening, selecting templates and restoring previews.

### Fixed

- Model imports, complex effect loading and discarded imports no longer block the interface during preparation or cleanup.
- Create New Item and Browse Archives preserve the same material detail. FBX packages can recover referenced textures from their extracted folders and retain authored UVs.

## [0.11.0-alpha.7] - 2026-08-24

### Added

- Create New Item uses a guided seven-step workflow with a resident Effects workspace, effect placement controls and live per-part glow preview.
- Imported faces can be separated into parts through Mesh Editor. Effect compatibility is checked against the actual item prefabs before output.

### Changed

- Model & Placement and Output use wider, more compact layouts. Automatic identifiers are distinguished from manual overrides.
- Mesh Editor opens archive meshes as a focused authoring workspace; Model Library hands imported models to Create New Item.
- Initial geometry appears before textures, and mesh loading reuses preparation work.

### Fixed

- Create New Item preserves imported textures and glow across Model & Placement, Effects, placement application and output. Captured icons match the visible camera.
- Effect brightness, sprite blending and lighting are corrected. Camera orbit, gizmo rotation and scene lighting behave consistently across previews.
- Mesh selection, sculpting and subdivision remain responsive, retain the released result and preserve selected boundaries. Long helper startup no longer causes repeated restart loops.
- Install refresh, template selection and preview cleanup avoid crashes and keep cancellation within the owned workspace.
- Compact layouts, stat editing and output buttons retain usable sizing and feedback. Mesh Editor Close warns about unsaved changes.

## [0.11.0-alpha.6] - 2026-08-21

### Added

- Create New Item provides an end-to-end workflow for cloning a template into a distinct item, with names, icons, stats, prices, enhancement rows, perks, distribution and output review.
- Models can be imported and fitted to a template in a textured viewport, including FBX conversion through a configured Blender installation. Per-part glow, icon capture and placement controls are available.
- Effects can be browsed, positioned and adjusted against the item and character, with trail alignment, approximate particle previews, reach guides and playback controls.
- Add to existing mod combines another item with an existing package. Game overlays place new assets in a separately tracked archive directory and support removal with recovery information.
- Placement & Animations groups a move as one operation, includes linked equipment such as sheaths and packages only selected operations.
- Supported mesh edits can preserve original topology lineage for exact output where the format allows it.

### Changed

- Builder setup and output review use clearer controls for source materials, part setup, glow, placement and the files being replaced or retained.
- Full replacements check required texture companions before output, and builds reject changed inputs or options that no longer describe the reviewed operation.

### Fixed

- Repeated item creation and interrupted work preserve earlier packages, foreign overlays and the current draft. New items receive distinct identities.
- Overlay archive tables and mount data are written correctly, and removal restores the appropriate texture registry. Installation reports archive changes and failures clearly.
- Imports preserve texture orientation, source emission and selected glow parts, align weapons by their grip, and avoid unintended template cloth/collision inheritance.
- Effect placement retains the imported model, textures and chosen position. Supported particles use correct sprites, colour and brightness; approximate or missing inputs are identified.
- Model imports, template reads and plan preparation stay responsive and report failures without closing the application.
- Mesh selection, gizmos, camera settings and textured modes retain their state through edits. Finish cannot report a saved edit after the editor session is lost.
- Mesh decoding preserves supported bone influences, normals and tangents. Archive writing no longer confuses record identity with checksums.

## [0.11.0-alpha.5] - 2026-08-12

### Fixed

- Brush and lasso selection remain responsive on dense meshes, commit the drawn region and retain correct selection/X-Ray behavior.
- Textured previews load and restore reliably, reuse prepared archive materials and report actual texture failures. Skin no longer becomes uniformly shiny or mottled from incorrect layer handling.
- Mesh loading and material preparation avoid repeated work without reducing texture resolution. Editor startup shows a settled layout, and interaction logging no longer stalls gestures.

## [0.11.0-alpha.4] - 2026-08-11

### Added

- Mesh editing adds persistent geometry layers, a selection clipboard and separate vertex, edge and face selection with configurable highlight colours.
- Morph & Refit adds per-garment settings for cloth and rigid parts. Preview Settings adds wireframe and vertex-marker colours.

### Changed

- Mesh sessions open in Orbit, with selection kept separate from whole-part controls. Selection strokes form one Undo operation, and subdivision respects the selected region and mesh-size limits.
- Workspace navigation is grouped by type of work, and dense garment binding is faster.

### Fixed

- Editor tools and textured previews open correctly, preview modes retain their intended overlays, and long selections survive delayed updates.
- Large imports remain responsive, image preparation releases source files, and exact supported OBJ round trips preserve skin records.
- Browse Archives shows its full extension list on first use and reports refused background work in the log.

### Docs

- Updated workspace descriptions and architecture diagrams.

## [0.11.0-alpha.3] - 2026-08-03

### Added

- The interface can switch among 14 built-in languages without restarting.
- Translations adds AI-assisted translation with provider configuration, encrypted API-key storage, response checks, cancellable batches and incremental application of completed results.
- Item Finder shows descriptions, stats and equipment slots. Browse Archives can play sounds embedded in Wwise banks and export folders from the file-list menu.
- Prefab Inspector supports duplicating and removing supported collection objects, ordinary field edits and Undo. Ambiguous or unsupported structures remain restricted.
- Mesh editing adds brush, rectangle and lasso selection, configurable viewport colours/grid, and rebindable camera gestures.

### Changed

- Mesh Editor and Morph & Refit use more compact, guided controls with clearer selection scope and tool settings.
- Placement & Animations becomes a top-level workspace, with cached character/socket preparation and clearer controls and help.
- Archive browsing, dependency preparation and model loading reuse completed work. Translation loading runs in the background.
- Preview-cache controls describe their actual effect; inactive settings are disabled. API keys are not saved if encryption fails.

### Fixed

- Mesh transforms, sculpting, morphs and selection commit the geometry shown in preview, preserve Undo/Redo and reject obsolete results. A refused edit no longer disables the rest of the session.
- Finish reliably returns to placement, and preview modes, grid, gizmos and material loading remain stable through tool changes, resizing and reopening. Placeholder geometry no longer flashes during startup.
- Layered materials retain their own textures, colours, skin response and metal appearance. FBX exports retain the rig and correct scale.
- Item indexing includes previously missed tables and references; clearing filters removes hidden constraints. Associated Assets follows correct file relationships, including audio dependencies.
- Interface language changes update open and detached tools without corrupting identifiers or freezing the application. Theme changes, monitor moves and late callbacks no longer access destroyed controls.
- Prefab parsing and path edits reject ambiguous or invalid output, preserve untouched transforms and provide clearer review and recovery guidance.
- Mesh swaps retain cloth companions, report missing targets and keep scope choices readable. Preview cache clearing and disabling reclaim the intended files.
- Closing during active work completes cleanup without leaving the application running invisibly.

### Docs

- Corrected tool availability, editing guidance, help navigation and third-party notices.

## [0.11.0-alpha.2] - 2026-07-28

### Added

- Prefab Inspector shows declared fields, numeric values, resource paths, placements, companion files and usage references. Supported edits include length-changing paths, per-row Undo and a review before output; partially decoded files expose only supported operations.
- Placement & Animations adds a unified Move a weapon workflow, carry-position changes, linked animation swaps, character/weapon previews and optional borrowed animations with explicit proportion warnings.
- Rig inspection includes Driven bones and runtime Rig behaviour panels. The `.papr` data is treated as authoring data, not proof that changing it affects game physics.
- Added supported animation and localization writing, constraint-rig decoding, and projectile-description decoding. Projectile simulation data remains undecoded.

### Changed

- Placement controls use readable names, compact groups and contextual help, with background rig preparation and cached character data.
- Format support descriptions distinguish decoded, editable and unresolved data.

### Fixed

- Prefab edits validate their output, preserve untouched rotations and refuse unsafe rewrites. Incomplete decoding is explained instead of presented as fully understood data.
- Weapon moves and animation swaps retain character/hand identity, report partial failures accurately and do not continue after a failed prerequisite.
- Character previews include previously missing equipment and avoid repeated rig work. Sculpting no longer applies an extra release stroke or selects noneditable geometry.
- Model previews retain editor state through package changes, load textures correctly and avoid startup crashes or blank preparation dialogs.
- Tool shutdown and cancelled preparation avoid late updates and crashes.

### Docs

- Renamed the repository to CDMW-Full and revised format/editing guidance to state known limits, including the lack of in-game verification for edited prefabs at this release.

## [0.11.0-alpha.1] - 2026-07-27

### Added

- Item Finder is available in Full, with catalogue warm-up, icons and handoff to Browse Archives.
- Structured material/runtime XML editing adds sortable fields, graph connections and source views.
- Mesh editing adds a tool rail, per-part colours, configurable overlays, connectivity checks, body-region morph sliders and garment refit.
- Icon Creator adds region selection; archive preview adds PAT support and improved edge/texture smoothing.

### Changed

- Archive tools share a background archive service and resident previews, reducing repeated index, decode and texture work.
- CDMW Lite moves to its own repository. Full retains the shared archive-decoding behavior.
- Archive columns size to content, item-name evidence is combined into one column, and companion preview parts become opt-in.
- Application shutdown is coordinated in the background. The portable package includes its image-processing dependency and omits unused helper components.

### Fixed

- Mesh controls, tool activation, selection, placement and preview settings remain synchronized through edits, saves, resizing and reopened sessions.
- Layered materials retain correct colour, dye, glow, normal and surface-map ownership. Texture compilation and cache failures are reported instead of accepted as successful textured output.
- OBJ output retains texture bindings; mesh decoding preserves supported skin records and correct part identity.
- Preview startup avoids flashing helper windows, and packaged first-run archive prompts behave correctly. Helpers are cleaned up after shutdown or a previous crash.
- Profile import rejects files without profile data, and pending appearance updates no longer discard other settings changes.
- Item Finder classification and saved filters follow the supported category rules.

### Docs

- Updated workspace, settings, mesh, archive and output guidance for the reorganized application.

## [0.10.0-alpha.2] - 2026-06-06

### Added

- Desert Dawn, High Contrast and OLED Black themes, with matching icons and readable text, selections and borders.

### Changed

- Mesh previews reuse archive material settings more consistently, and live edits update the changed geometry with less repeated work.

### Fixed

- Move and edit strokes no longer freeze or corrupt previews when coordinates use exponent notation.
- Lighting and texture setting changes refresh the preview. Skin/head materials retain their own texture ownership instead of inheriting unrelated layers.

## [0.10.0-alpha.1] - 2026-06-05

### Added

- Grouped Dashboard, Assets, Textures, Research and Settings navigation, plus detachable tools with remembered window positions.
- A dedicated Mesh Editor workspace for supported original-mesh edits, replacements, import previews and archive swaps, with placement, part mapping and output review.
- Model Library for local and catalogue models, companion textures, previews and import handoff. Icon Creator adds source libraries, favourites, tags, template-based DDS output and model-preview capture.
- Texture workflow profiles and ordered rules, recolour variants, package conversion/repair, and source-mix/character dependency package builders.
- Material controls for source/target appearance, roughness, metallic response, opacity and glow, with explicit support checks and package diagnostics.
- Broader archive relationships, structured previews, material/customization sidecars, skeleton/physics inspection and supported HKX import/export.
- Selected archive patch workflows with explicit confirmation, preflight checks, backups and restore support.

### Changed

- Large archive scans, texture conversion and preview preparation use bundled helpers and reusable caches to reduce repeated work and interface stalls.
- Mesh replacement becomes a persistent editing workspace with shared model previews, material context and final-package checks.
- Replace Assistant is renamed Texture Replacer. Settings and help expand to cover the grouped workspaces, preview controls, cache health and package conversion.

### Docs

- Updated user guides, dependency notices and format-support documentation for the expanded archive, model, texture and package workflows.

## [0.9.0-beta.3] - 2026-05-02

### Added

- Broader item-name and alias search, related-file discovery and structured inspectors for supported prefab, level, road, navigation, skeleton and table formats.
- Readable value summaries above XML/text previews and improved physics metadata inspection.

### Changed

- Search ranks direct matches first while keeping extension and other filters authoritative. Technical texture maps remain listed without being mistaken for base colour.
- Removed the unsuccessful experimental layer-composite preview. WEM replacement is described as best-effort, not a complete Wwise rebuild.

### Fixed

- Related-file views retain missing sidecar and support-map references, and expanded searches no longer leak unrelated extensions.
- Archive patching validates checksums, target records, package paths and compression before writing, with improved failure recovery.

### Docs

- Clarified the beta's limits around repacking, audio rebuilding and mod-manager workflows.

## [0.9.0-beta.2] - 2026-04-30

### Added

- Shared relationship discovery across meshes, materials, appearances, textures, skeletons and physics, including visible unresolved references.
- Character/body swap planning can change body/head references while retaining target hair, armour, skeleton and physics by default.
- Determinate progress for selected and filtered archive exports.

### Changed

- Swap planning prefers exact relationships and archive paths. Texture suggestions prioritize exact matches and distinguish body, hand and technical-map roles.
- Select Graph Textures selects resolved DDS files only; sidecars, skeletons, physics and full appearance replacement remain explicit manual choices.

### Fixed

- Choosing swap sources on large archives stays responsive. Same-named textures in different folders remain distinct, and narrow preview layouts avoid overlap.

### Docs

- Added clearer swap-scope and character-plan guidance.

## [0.9.0-beta.1] - 2026-04-30

### Added

- Material-sidecar editing for supported colour, numeric and texture-path values, with approximate preview and package output.
- Mesh Import Setup and Replacement Alignment provide preflight, original/replacement previews, transforms, part mapping, texture review and a test build before output.
- Supported static mesh replacement, archive-to-archive swaps and OBJ/DAE/glTF/GLB scene import, including required material context.
- Shared package finalization with manager profiles, reviewed metadata and optional ZIP output.
- Archive item-name search, floating preview settings, performance controls, progress reporting and local crash diagnostics.
- Built-in Spanish and German translations, custom language import/export and additional themes.

### Changed

- Renamed Crimson Forge Toolkit to Crimson Desert Mod Workbench.
- Archive scanning, previews and package checks do more work in the background. Supported nested game archive layouts are detected.
- Preview guidance distinguishes approximate support-map inspection from final in-game rendering.

### Fixed

- Closing or cancelling archive work waits for active workers safely. Crash reports survive relaunch when appropriate.
- Final package previews resolve generated, copied and original textures correctly, and mesh packages use suitable manager layouts.
- Loose preview toggles and narrow referenced-file panes remain usable.

### Docs

- Updated mesh alignment, material, sidecar and package-preview guidance.

## [0.7.0-beta.4] - 2026-04-21

### Added

- Referenced Files shows supported model companions with direct open, selected export and export-all actions.
- Added structured summaries for mesh metadata, animation and effects, with broader skeleton companion discovery.

### Changed

- Mesh import/export can include optional material sidecars and DDS files. Loose package metadata is simpler and consistent.

### Fixed

- Corrected supported PAC texture orientation and preserved texture roles from sidecars in preview and related-file lists.

## [0.7.0-beta.2] - 2026-04-20

### Added

- Mesh loose export asks for title, version, author, description and encryption-marker choice before writing.

### Changed

- Mesh package metadata is generated from the confirmed export values.

### Fixed

- The actual OBJ export path now uses the metadata prompt. Referenced textures retain their exact base, normal, material, height and mask roles.

## [0.7.0-beta.1] - 2026-04-20

### Added

- Supported archive patching, per-entry backups, restore and mod-ready loose export.
- Interactive 3D previews for recovered mesh geometry, with camera controls, textures and explicit incomplete-geometry messages.
- OBJ/FBX export and OBJ import/preview, supported paired-LOD handling and matching skeleton data for character export.
- Referenced-texture inspection and replacement, audio/video playback, and structured summaries for supported soundbank, skeleton, physics and material files.
- Flat and tree archive views with incremental loading.

### Changed

- Preview, import, export and restore actions are accessible beside the selected asset. Long filtering and preparation operations provide progress and cancellation.
- Texture lookup distinguishes visible colour from support maps, and portable packaging validates bundled runtime assets more thoroughly.

### Fixed

- Restored extension lists, DDS previews and material-text previews. Supported geometry recovery retains more submeshes and companions and reports failures clearly.
- Corrected missing or misoriented model textures, Texture Editor grid initialization and Windows portable-runtime extraction failures.
- Audio decoding no longer opens a console window; interrupted patch workflows expose restore and recovery more clearly.

### Docs

- Updated archive editing/preview guidance, format coverage and third-party notices.

## [0.6.5] - 2026-04-18

### Added

- Persistent app, list and log font settings, density controls and optional log emphasis.
- Research adds in-place archive texture preview and richer DDS metadata. Texture Editor adds grid colour and opacity controls.
- Texture Workflow adds named profiles, ordered rules, matched-file review and per-file assignments, with starter profiles for common colour and technical maps.
- Searchable in-app documentation with topic navigation.

### Changed

- Workflow policy is edited through visual profile/rule controls. Colour textures remain enabled by default; technical-map starters prioritize preservation.
- Texture handoffs decide staging and root-clearing behavior when handed off, and replacement matching uses stronger path evidence with explicit ambiguous choices.
- Layouts, headers and preview panels use space more consistently at smaller sizes.

### Fixed

- Replacement import, matching, packaging and review avoid freezes and incorrect preview metadata. Classification clearly separates inferred roles from local approvals.
- Corrected editor guides, masks, brush presets, icons and metadata sizing, along with font controls and DDS surface estimates.
- Rapid archive browsing avoids repeated heavy preview work. Direct upscaling validates output and retries smaller tiles after supported failures instead of silently accepting flat output.

### Docs

- Updated workflow/profile help, troubleshooting and screenshots.

## [0.6.0] - 2026-04-16

The full release brings together the layered texture-editing features introduced
through the 0.6.0 beta cycle.

### Changed

- Texture editing, replacement, preview and research workflows receive final layout and responsiveness improvements.
- Updated branding and portable configuration names while retaining migration of legacy settings.
- Workflow handoffs stage editor output separately and decide root clearing at handoff time.

### Fixed

- Selection extraction preserves soft edges and holes. Layer removal cleans up masks/adjustments, and guides, rulers and atlas controls behave consistently.
- Replacement matching is explicit, shows indexing progress and preserves its queue. Compare retains image proportions and avoids fit-mode flicker.
- Classification review distinguishes local approvals from inferred roles and offers a direct local-save action.
- Corrected the portable executable's Pillow extraction failure.

### Docs

- Updated release and in-app guidance for the completed editor and workflow changes.

## [0.6.0-beta.4] - 2026-04-16

### Added

- On-canvas transforms, richer masks and selections, packed-channel tools, image-stamp brushes, symmetry painting and editable quick masks.
- Crop, trim, canvas/image resize and atlas region/grid export, with channel copy/paste/swap.

### Changed

- Large editing sessions use lighter refresh and history work. Research and Text Search avoid unnecessary full result updates.

### Fixed

- Corrected masked extraction, merge-down, selection/mask conversion, floating selections and project persistence.
- Improved unusual DDS previews, cancellation and shutdown. Unfocused wheel scrolling no longer accidentally changes controls.

## [0.6.0-beta.3] - 2026-04-15

### Added

- Expanded multi-document, layered editing with floating selections, masks, adjustments and channel/alpha controls.
- Broader paint and retouch tools, brush presets and saved custom settings.

### Changed

- A canvas-focused layout adds contextual settings, shortcuts and clearer status, with improved copy/paste, movement and selection refinement.

### Fixed

- Improved DDS fallback, archive-load responsiveness, preview cancellation, zoom anchoring and project save/load.

## [0.6.0-beta.1] - 2026-04-13

### Added

- Replace Assistant imports edited PNG/DDS files, matches originals, optionally upscales them and builds a mod folder with post-build comparison.
- Texture Editor supports layered, multi-document projects, painting and retouching, selections, masks, adjustments, recolour and export to replacement or batch workflows.
- Source-aware Edited/Original/Split and channel previews, guides, brush presets, custom shortcuts and channel locks support detailed texture work.
- Optional local crash-detail capture is available in Settings and diagnostic bundles.

### Changed

- Workflow is renamed Texture Workflow to distinguish the batch pipeline. Package output uses a child folder named after the mod.
- Editor controls use a compact tool rail and contextual panels. Document loading, saving and export run in the background.

### Fixed

- Replacement matching, model discovery, stale preview handling and package markers use the selected settings and report progress.
- Editor Undo/Redo and project files preserve floating selections, layers, masks and in-progress content. Copy, paste, cut and transform respect the selected region.
- Paint and retouch tools honor channel locks, visible-layer sampling and fine brush sizes. Zoom, pan and source metadata remain consistent across handoffs.
- Portable builds include the editor's dependencies. Archive startup avoids rebuilding heavy hidden views, and DDS preview supports additional luminance formats with cancellable fallback.

### Docs

- Updated editor, channel, brush and workflow guidance.

## [0.5.5] - 2026-04-12

### Added

- Local texture-classification approvals can be saved once and reused. Classification Review provides previews, filters and bulk actions.
- Upscale preflight identifies unclassified textures and can open a focused review. Research references can open the exact source in Text Search.

### Changed

- Upscaling uses direct Real-ESRGAN NCNN or external chaiNNer; the alternate Python backend is removed.

### Fixed

- Classification prompts resume correctly after review, and approvals apply to both archive and extracted paths. Technical-map and texture-family detection is more conservative.
- Research, Text Search and preview work cancel promptly and avoid repeated scans or image decoding.
- Expert overrides and explicit rules are applied consistently, invalid chaiNNer staging references fail early, and full-frame upscaling falls back to smaller tiles only after failure.

### Docs

- Updated classification and upscale-backend guidance.

## [0.5.0] - 2026-04-12

### Added

- Automatic Source Match reconstruction modes for direct Real-ESRGAN NCNN workflows.
- A high-precision path for eligible scalar technical textures, advanced NCNN arguments and an explicit unsafe override for generic processing of technical maps.

### Changed

- One per-texture plan governs preview, preflight, backend use, rebuild and review, including processing path, alpha policy and preservation reasons.
- Run Summary replaces Safe Wizard; editable workflow controls remain in the main panel.

### Fixed

- Technical textures no longer silently enter the visible-colour path. High-precision intermediates are validated, and invalid inputs preserve the original DDS.
- Rebuild respects manual format choices, avoids unintended colour-space flags and applies Source Match to eligible colour-like textures.
- Compare and archive previews load more responsively, retain images correctly and cancel during shutdown. Cache identity includes the converter used.
- Preserve-only runs skip unnecessary backend work, tile retry handles full-frame attempts, and texture-family classification avoids misleading name matches.

### Docs

- Updated processing-policy, Source Match, high-precision and override guidance.

## [0.4.1] - 2026-04-11

### Changed

- Setup and model-catalogue actions open official download/source pages in the browser.
- Research computes and reuses a shared archive snapshot for grouping, classification and analysis.

### Fixed

- Rapid DDS browsing avoids conflicting preview writes and repeated decoding. Long scans and reference searches cancel during shutdown.
- Technical DDS preservation, alpha-bearing normal maps, colour variants and tile retries follow the selected policy correctly.
- Research references focus the correct archive file, refresh progress is consistent and failed analysis clears pending navigation.

## [0.4.0] - 2026-04-11

### Added

- Research provides texture classification, grouping, references, related-set extraction, mip analysis, normal validation and usage information.
- Direct Real-ESRGAN NCNN upscaling, model setup/catalogue, optional colour correction and guided setup.
- Compare adds shared preview sizing, wheel zoom, pan and direct access to mip details. Logs gain clearer highlighting.
- Archive browsing adds exclusions and a base-colour role filter.

### Changed

- Preview Policy shows per-texture actions before a run. Technical maps are identified conservatively and preserved unchanged when excluded from processing.
- Workflow exposes backend and texture-policy controls separately, with clearer preflight and output guidance.
- Research, Compare and other dense layouts use space more effectively and handle display scaling better.

### Fixed

- Corrected workspace-folder creation, profile/diagnostic export and supported legacy float/vector DDS handling.
- Runs that preserve every texture skip unused backend setup and stale intermediate files.
- Related-set extraction explains missing analysis and destinations, Compare retains correct fit/zoom proportions, and duplicate analysis warnings are removed.

### Docs

- Updated workflow, texture-policy, Research, Compare and troubleshooting help.

## [0.3.0] - 2026-04-08

### Added

- Global Settings for appearance, startup, layout memory and cleanup confirmations.

### Changed

- Faster archive parsing, refresh and cached browser preparation.
- Theme selection moves into Settings, and the experimental model viewer is removed from the live application at this release.

### Docs

- Reorganized the README for easier navigation.

## [0.2.1] - 2026-04-08

### Changed

- Portable Windows executable filenames include the version.

## [0.2.0] - 2026-04-08

### Added

- Broader archive-root detection for custom and non-Steam installations, with `CRIMSON_TEXTURE_FORGE_PACKAGE_ROOT` and `CRIMSON_DESERT_PACKAGE_ROOT` overrides.
- Read-only Text Search for archives and loose files, including supported encrypted XML, highlighted results and export with folder structure preserved.
- Text previews add syntax colours, line numbers, local Find, wrapping and font controls.

### Changed

- Search uses a larger preview layout with filenames and full paths clearly separated. Smaller windows use available space more effectively.

### Fixed

- Text preview font changes update the content and line-number gutter together.

## [0.1.0] - 2026-04-07

### Added

- Initial public release with read-only archive browsing, selective DDS extraction and reusable archive caches.
- Loose DDS scanning, optional PNG conversion and chaiNNer processing, configurable DDS rebuilding and side-by-side comparison.
- Profile import/export, diagnostic bundles and built-in help.

### Changed

- Configuration is stored beside the executable for portable use.

### Docs

- Added setup, dependency, credit and limitation guidance.
