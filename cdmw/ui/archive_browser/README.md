# Archive Browser

Owns archive listing, filtering, preview coordination, item icons, and archive
browser actions. Keep virtual model behavior in `model.py`; keep UI assembly and
feature coordination in focused modules as they are extracted from the shell.

## Contents

- [Mesh replacement review status](#mesh-replacement-review-status)
- [Loose mod imports and tool availability](#loose-mod-imports-and-tool-availability)
- [Edited Mesh Editor results](#edited-mesh-editor-results)
- [Catalogue and Item Finder](#catalogue-and-item-finder)
- [Scanner failures and recovery](#scanner-failures-and-recovery)
- [Body & Face Finder](#body--face-finder)
- [Preview dependencies and payload validation](#preview-dependencies-and-payload-validation)
- [Read-only boundary and exports](#read-only-boundary-and-exports)

## Mesh replacement review status

**Mesh Replacement is temporarily disabled for release review.** Its
**Replace Mesh from File...** action is absent from the Import and mesh context
menus, and its retained action button stays disabled as selection and busy state
change. The builder implementation remains available for development.

The retained workflow takes a PAC/PAM/PAMLOD target and an OBJ, FBX, DAE, GLB or glTF
source. **Mesh Replacement** in the setup dialog opens alignment/mapping review
in Mesh Replacement Builder to build a mod-ready loose package.
**Round-trip edit** supports OBJ, FBX, GLB and glTF exported by CDMW with their
matching metadata companion and original mesh structure. FBX import uses the
Blender executable selected on the Model step. Unsupported target formats
remain blocked by preflight. Replacement opens its own window and preserves
any active Mesh Editor session.

### Materials and import setup

The setup dialog defaults to **Keep target materials and textures**, so a
geometry-only OBJ does not need an MTL. Choose **Replace materials and textures
too** to use the imported model's material files and textures. This choice sets
**Replace materials and textures too** under the builder's **Options** and can
be changed there. Dedicated full-replacement and materials-only workflows keep their presets.
Missing final textures still block export.

Mesh Import Setup shows the source, target, mesh size, mode and material choice.
**Files** and **Details** start collapsed; Files shows the included file count.
Blocking scan errors and missing-texture warnings remain visible when relevant.
The builder groups global transforms, part selection and routing in **Transform
and Parts**, with separate **Options**, **Item Icon** and **Source Mixing**
sections. Advanced controls and the Edit Mesh toggle are hidden. Its standalone
viewport uses Rust/DX12 preview packages and accepts fresh scene identities for
subsequent alignment updates. Reference-material completion rebuilds the preview.

### Companion meshes

When a PAM has an indexed PAMLOD companion, both meshes must rebuild successfully.
A failed companion rebuild stops the build with the companion path and error;
it cannot produce a package containing only the PAM.

## Edited Mesh Editor results

After accepting **Finish Edit Mesh**, choose **Add to Archive Browser**. Eligible
game-format meshes appear in **Controls > Edited results** for the current app
session. Select one and choose **Open in Mesh Editor**, or double-click it, to
start another editing pass from the rebuilt bytes. The loaded archive catalogue
and Game/Package path stay in place. These entries do not install a mod or change
PAMT/PAZ archives.

Choose **Start next edit pass** on the accepted Finish page to use the
same handoff and reopen the current source asset directly, without visiting the
browser. **Add to Archive Browser** remains useful for choosing another asset from
a combined Refit result. Both routes retain the other edited output files for
subsequent mod builds. **Resume current edit** instead resumes the existing working state.

The background output worker captures the validated revision, rebuilds every
combined Refit asset through its own writer, and retains the source dependency
context. Prepared materials, textures, rig and physics resources are copied into
the immutable local result so preview-cache eviction cannot remove them. Legacy
unprepared dependencies continue to reference the original read-only archives.
Missing Refit source contexts, failed rebuilds, changed dependencies, cancellation
and stale revisions refuse publication. Results are bounded to 8,192 entries and
1 GiB of prepared files; the list is not restored after restarting CDMW.

The next pass loads clean game-format geometry and resolves materials and the rig
from that result's context, without reusing an unrelated preview or old editing
runtime. Each saved result also keeps its verified, geometry-free material
metadata and independently pins the texture package and decoded image caches.
Opening a result uses its original layers, colour parameters and material owner
slots, including after the original editor closes. Every reopened editor owns a
separate package lease, so closing it leaves the saved result reusable.
Previously edited assets and generated companions travel into later
outputs, so editing one Refit asset does not discard the other asset's changes.
Retaining a physics resource or binding is not proof of valid cloth simulation
after geometry changes. The handoff cannot recreate dependencies absent from the
original session, or turn an OBJ-only Free Edit result into a supported game mesh.

A **DMM Archive Group** contains replacement files and relies on unchanged files
in the base game. Opening the group as the only archive root hides those
dependencies from the browser; use the edited-result handoff for another pass.

## Loose mod imports and tool availability

**Import Loose Mod Folder...** scans already prepared game-format mod files and
matches them to archive entries; it does not convert OBJ models. Source scans
and replacement source imports use the main window's background utility worker,
with the requesting workspace/dialog retained as their result-lifetime guard.

### HKX Physics Editor

**Tools > Physics / HKX > Edit HKX Physics** and the `.hkx` context menu open
`hkx_physics_editor_dialog.py` for the selected file. The older XML-based HKX
editor and its import/export buttons stay out of the menus.

- Reading the file, building edits and writing output run in the main window's
  utility worker (`hkx_physics_editor_actions.py`). A refused edit comes back as
  an ordinary result, not a worker error, and the dialog ignores results once
  it is closed.
- The dialog only offers what `services/hkx_physics_editor_service.py` can
  verify: joint limits and friction located by Havok constraint atom type
  (`core/archive_hkx_joint_limits.py`), renamed `hkStringPtr` names, and a whole
  collision file copied from another file with the same root class and patch
  layout. Every save is parsed again and must read back; joint edits must leave
  every byte outside their constraint records unchanged.
- **Save as DMM Mod** uses the shared mod-ready export; **Save HKX File** writes
  one loose file atomically. Neither writes to the game archives.

### Dialog cancellation

Mesh Builder close cancels pending work and hides the dialog promptly. The
lifecycle owner retains the closed dialog until every child thread has finished
native teardown, then deletes it asynchronously. Partial construction failures
use the same rule.

## Catalogue and Item Finder

Game-folder scans ignore the top-level `cdmods`, `backups`, `.cdmw`,
`crimsonforge_backups`, `dmmsa`, `dmmgen`, `CrimsonFastLoad.backup` and
`.CrimsonModsCache` folders, plus `bin64/.CrimsonModsCache`, by default, regardless
of letter case. Ignored indexes do not enter the live
catalogue or its fingerprint. Explicitly opening an ignored `.pamt` remains
available for inspection.

**Settings > Paths > Ignored folders** lists these removable defaults and saved
custom folder paths. **Add folder...** selects a folder inside the current game
directory; **Add path...** also accepts a relative path that does not exist yet.
Nested paths such as `extras/old` exclude that subtree, without excluding other
folders named `old`. Matching ignores letter case. Select any rows, including
defaults, to remove them with **Remove selected** or the context menu. Removed
defaults stay removed after reopening Settings; clearing the list allows all
folders to be scanned. Existing custom exclusions are retained alongside the
defaults until the list is edited.

Saved custom lists remain authoritative when new defaults are added. Add
`bin64/.CrimsonModsCache` manually to an existing custom list to exclude the
CrimsonMods cache when scanning the main game folder.

Changes apply on the next archive load or refresh. The filtered source list owns
both the catalogue fingerprint and native indexing, so cached results update when
an exclusion adds or removes archive sources. Ignored files are unavailable to
tools using that catalogue. Worker retries retain the exclusions captured when
the session opened. The complete edited list is saved as
`archive/ignored_folders_override`; older `archive/ignored_folders` custom entries
are read when no override is saved. No game files are changed.

The standalone resident catalogue is the only listing authority. Its status messages reach the
owning shell through the archive workspace's `shell` reference. Preview requests are
request-correlated and latest-wins: a stale selection may be superseded but may
not clear or replace the current scene. Archive Browser publishes the path,
basename, extension, dependency, and native package indexes reused by Model
Library, Mesh Editor, and Create New Item.

Textured previews capture the matching archive session's catalogue path with the
bounded dependency snapshot. Preview Core reuses that catalogue for shader defaults
absent from the snapshot, reading the selected material family and shared parameter
definitions instead of decoding every material on the first model load. Catalogue
file access remains on the preview worker; this adds no persistent cache files.

**Select Extension** opens a grouped, searchable extension list. Select a leaf
and confirm, or double-click it, to close the picker and update the filter. The
picker opens while the startup archive index is still loading and fills in as
extensions become available, preserving anything typed in its search. Extension
counts reuse the archive index and load ahead of catalogue warmups. Opening the
picker does not block other tools or rescan archive entries; clicking the button
again brings the open picker forward. Closing it leaves archive loading running.
A new archive load or search closes the picker to avoid an outdated selection;
a load failure closes it to reveal the browser's retry controls.
Apply **Search** to refresh the archive results.

Startup catalogue, New Item data and thumbnail warmups wait for the archive view to settle and
pause during keyboard, mouse, drag, wheel and focus activity throughout the app,
including input inside embedded native viewports on Windows. They resume after
two seconds without input. Interrupted thumbnail jobs return to the queue and
completed previews stay cached; startup's saved page remains background work.
The extension picker defers new warmup requests until it closes. This also gates
the first item-name build and saved-page lookup; foreground Finder icon requests
retain priority. Archive worker replies are delivered in bounded GUI turns,
including replies still buffered when the worker exits.

Item Finder shows its categories and subcategories in a collapsible list on the
left, with item counts. The item grid is in the middle and item details and asset
actions are on the right. Select a category for all its groups, or a subcategory
to narrow the results. **Only DLC items** limits every category, search and page
to IDs introduced in mounted DLC tables, excluding IDs already in the base table
even when DLC overrides them. Counts follow this checkbox; zero-count categories
remain selectable. The checkbox is remembered on reopening and reset by **Clear**.
**Ships** separates sails, figureheads, sterns, cannons, teleporters, ship blueprints,
blueprint parts, equipment blueprints and ship materials. Equipment types and
item-definition families take priority over translated names or linked models;
trade cargo, furniture and recipes therefore retain their own categories.
Socketable Abyss Gear stays under **Progression / Reward**, in **Skill** or
**Stat**, even when its recovered metadata names an armor slot. These item
families take priority over slot hints, including when reopening a cached catalogue.
Current StringInfo row keys resolve explicit inventory icons, including non-`cd_`
ship icons. Empty placeholder assets are not advertised as usable links. Linked
prefabs retain their model dependencies through bounded nested prefab/PAMI walks;
icon-derived model names remain related evidence. Missing icons keep the letter
tile. Repeated cached icons do not republish grid decorations, and icon arrivals
update only the selected icon without resetting its text, selection or layout.
The grid reserves scrollbar space so small result sets cannot oscillate between
column counts as the scrollbar appears and disappears.
Description line breaks are displayed as lines while identifiers remain plain text.
Category names and grid captions wrap for larger fonts;
the grid uses the available width. Detail actions wrap onto more rows when
needed, and long names and paths wrap while retaining their original copied
text. Additional window width goes to the grid; the details pane keeps its
chosen width and shows only a selection prompt until an item is selected.
Categories start collapsed on the first visit. Reopening restores expanded
categories, search and category filters, the result page, selected item, scroll
positions and pane widths. Closing while the initial results are loading keeps
the saved browsing position. Older two-pane layouts gain the category pane
without adding a new layout setting.

## Scanner failures and recovery

The older application scanner, shadow mode and **Use Legacy This Session** action
are removed. `CDMW_ARCHIVE_BACKEND` no longer selects a scanner; any existing value
produces one log notice and is ignored. Existing cache formats remain readable,
and removal does not delete old user caches or change game archives.

`ArchiveCatalogueService` owns one retry per logical operation, including any
worker restart, fingerprint-checked session reopening, query reconstruction and
staged publication. Temporary sharing violations, unexpected exits and timeouts
retry after a cancellable one-second delay. Permanent errors report immediately.
Manual **Retry** starts a fresh budget and repeats the captured operation with its
original filters, sorting and selection. Page and item-index retries do not reopen
the whole browser. Exports and archive mutations gain no automatic replay.

After 30 seconds without meaningful progress, status shows the stage and elapsed
time. After five minutes without progress, the service requests cancellation,
allows two seconds for acknowledgement, and uses bounded process-tree termination
when required. The existing ten-second startup and three-minute native item-indexer
timeouts remain. Work that continues progressing can run longer than five minutes.
Cancellation, a changed root, an obsolete request or shutdown prevents later retry
and error publication.

Open/refresh failures offer **Retry**, **Copy error report**, **Details** and
**Close**, preserving the previous published view. Background indexing failures
show **Item names unavailable** with their own controls while archive rows remain
usable. Successful recovery clears the failure display. Reports retain typed
`code`, `message` and `detail`, runtime/backend identity, attempts, stage, counts,
elapsed time, an affected path and diagnostic tail. Copied reports redact game
and profile prefixes, retain at most twelve progress entries and are capped at
16 KiB. An unknown failure is reported with its details without claiming game
corruption.

PAMT parse failures carry the confirmed `source_path` from the worker. The dialog
shows that file; reports keep the last progress item separate instead of treating
it as the failing source. Older workers without a confirmed path retain the
ordinary error controls and do not offer a guessed exclusion.

For an open/refresh format failure inside a known default mod or backup subtree,
**Exclude folder and refresh** names the relative folder, adds it to the saved
exclusion list without replacing custom entries, and starts a fresh scan with the
new settings. It does not delete files. Original game archives, unknown folders,
outside-root paths and non-opening failures do not get this shortcut. A closed or
superseded dialog, changed root, pending scan or shutdown prevents the action.

The opening workflow checks the game executable on a cancellable background task.
It saves the existing `archive/game_executable_fingerprints` record only after
catalogue publication succeeds. A demonstrated hash change forces a fresh
generation and retains the existing feature-evidence rules. This is game-update
bookkeeping, not a general game-integrity check.

The resident item catalogue and name index follow model paths embedded in matching
part-prefab payloads. A shared PAC can therefore carry every owning item name, and an Item
Finder scope includes those resolved model dependencies even when the item's prefab or icon
uses a different numeric stem. Archive Browser and Create New Item also share Preview Core's
PAC RGB selector-mask colour reconstruction. Item Finder additionally retains the selected
logical prefab ahead of shared physical siblings, allowing the background preview worker to
decode its per-model `_modelPropertyIndex`; variant-aware package keys prevent two items that
share a PAC from reusing each other's material set.

### Current item tables and localization

Item names use the active ItemInfo row directory and item localization domain. Current
`binarystaticinfo__` body/header pairs and per-language `item.paloc` files take
precedence over obsolete legacy tables, with `meta/0.papgt` mount order selecting active
overlays. StringInfo keys are joined to archived prefabs before decoding their actual
PAC paths. Browse Archives displays `Shared asset (N names)` for multiple distinct names
while its tooltip and search retain the complete set. Item Finder retains rows without
model links; generated names are identified in its evidence, and asset actions require
asset links.

English is the display language; Item Finder and New Item search all discovered item
languages, and missing English is not silently substituted from another language. New
Item uses the same source selection and name lookup; its separate Item Name cell shows
`-` when missing.

Item Finder decodes both raw localization tables and version-0 compressed PALOC
containers before indexing names. Invalid UTF-8 bytes in recovered text appear as
replacement characters instead of preventing the entire catalogue from loading;
valid Unicode names remain searchable. Unsupported or damaged containers report
their localization payload and cause. Older item-name caches rebuild automatically.

## Body & Face Finder

After scanning, open **Body & Face Finder** beside Item Finder. **Bodies** and **Faces**
offer **Unique assets** and **Appearance variants**, 72-result pages, name/ID/path
search, and component, source-family, body-family and resolution filters. English
character names are displayed; discovered character languages remain searchable. **Used
by / Components** links appearances to shared models. Both views start with
**Humanoids** (player and NPC families); choose **Creatures**, another type, or **All
types** to widen the results. **Faces** starts with separate heads.

Hair, beards and facial details (including tear and eye meshes) require their component
filter; a face embedded in a full body remains in **Bodies**. **Clear filters** restores
these defaults. An explicitly selected type is remembered, including **All types**.
**Show exact files** and **Show related files** return a bounded entry-ID scope to
Archive Browser, where existing extraction/export/editor actions remain available.

### Kliff's Character Creator look

**Kliff's Character Creator look…** is enabled when `bin64\CharacterCreator\menu.txt`
sits beside the game executable. It reads Khione95's Character Creator files
(`data.version`, `menu.txt`, `profile.txt`, `identity.txt`) without writing them, and
refuses any version other than 9.1.16. `cdmw/domain/character_creator.py` turns the
stored options (the `menu.txt` Kliff column, not the editor's on-screen numbers) and the
identity's `base` row into body, head, hair and beard prefab names.
`creator_look.KliffLookPreparation` then asks the resident worker for each prefab and
its `.prefabdata_xml` by basename, decodes the prepared `.prefab` for its PACs, and
looks up those PACs and the descriptor's skeleton, `.pabc` and `.pamt` by exact path.
The result is a Finder selection with one component per prefab, which the Export FBX
preparation and worker export with that prefab's own descriptor, so a head reusing
another head's PAC keeps its own face shape. Height, head scale, slot 5 (face details)
and decoration values are reported, not applied. Damiane's and Oongka's profiles are
not read.

### Catalogue ownership

The resident .NET archive worker owns the character catalogue independently of ItemInfo.
It accounts for active models and appearance/prefab references, including orphans,
unresolved ownership and ambiguous basenames. Unique assets contain actual model files;
unresolved descriptors remain in reference coverage and appearance details. Equipment
remains part of its owning appearance assembly without becoming a standalone body
result. Vehicle models and assemblies containing only non-body components are excluded.
Mesh/submesh metadata distinguishes bodies from hair, fur and accessories. Unclassified
models require the **Unclassified** component filter instead of appearing in default
Bodies/Faces results.

Mount precedence chooses active paths; complete CharacterInfo table pairs and verified
CharacterAppearanceIndexInfo full-path hashes supply names. Missing XML attribute
separators are repaired only in memory and reported.
The name reader decompresses PALOC containers before lookup and merges base and
DLC localization in mount order. DLC tables can reuse base character-name keys;
missing DLC translations do not erase the base names. Catalogue generations
invalidate older caches that scanned compressed bytes as though they were text.

### Warmup and preview workers

After the archive view is ready, two background jobs preload up to three pages
per tab (432 results), alternating Bodies and Faces with both landing pages first.
The catalogue results and rendered thumbnails are reused when the finder opens.
Background preview threads and thumbnail renderer processes run at low priority.
User activity interrupts assigned startup previews as well as queued jobs, and
the idle gate is checked throughout each page. Opening the finder also holds the
startup queue, while explicitly requested Finder previews retain priority.
Closing it resumes the remaining queue after the input idle delay.
New archives invalidate the warmup, and the shell retains its threads through
shutdown. The first uncached render still requires model and texture preparation.

The finder owns a separate Rust preview session. Bounded background jobs prepare
previews and 256px thumbnails. Visible cards go first, then the rest of the current
72-result page loads automatically without scrolling. Selection takes priority;
selecting a card already being prepared reuses that job and can display its ready 3D
package while thumbnail capture finishes. Other slots continue the page. Scrolling
reprioritizes waiting cards without restarting current page jobs. Thumbnail captures
render at 256px; the interactive preview keeps its full geometry and textures.

The **Show underwear** checkbox toggles separately identified underwear meshes in the
interactive preview immediately, without extracting or rebuilding the model. The choice
carries across selections within the dialog. Thumbnails keep the base appearance;
clothing painted into the skin texture cannot be hidden this way. Catalogue lookahead
starts as soon as a page appears and fetches up to four more pages, with one catalogue
request outstanding at a time. Once the on-screen cards finish, up to two render jobs
share the available slots with the rest of the current page.

When that page is complete, up to four jobs prepare future cards, depending on the
available lanes. Selection and newly visible cards take priority. **Next** reuses
prepared cards or promotes the pending page request; useful future requests survive page
changes, while obsolete cache scans are cancelled. The eight most recent result pages
are retained for navigation. Background results do not change the current grid or
interactive preview; changing filters cancels obsolete work. Head pages use up to eight
jobs (half the logical processors); other component pages use at most four.

Small systems use two jobs. Previously generated page thumbnails appear as each is found
in a fingerprint- and settings-scoped index, without repeating character detail requests
or geometry preparation. Uncached cards start preparing as soon as their own cache check
finishes, while later records are still being read. This applies to both the current
page and the next-page preload. Up to 576 thumbnail records and icons (eight pages) stay
in memory for revisits. Shared image paths reuse one icon, and returning to cached cards
skips their row/render JSON reads.

Image existence is checked in the background; removed images return to the normal cache
lookup and regeneration path. The remembered records are scoped to the archive session,
and a rescan clears the dialog caches. Finder package builds use the existing 2 GiB
disk-cache policy, trimming toward 1.5 GiB, to retain more prepared models across page
changes. Saved images remain usable after their larger 3D packages leave that bounded
cache; selecting one can rebuild its interactive package.

Shared-rig humanoid heads obtain their PAB through the family's base-body descriptor;
that extra descriptor supplies skeleton references only, preserving the selected head's
own PABC and materials. Creature body models whose name omits `nude` resolve the matching
numbered body descriptor. A valid face descriptor with no shape references retains the
original geometry; malformed descriptors and missing declared shape files remain errors.

Catalogue caches use archive generation, mount signature and format version; thumbnails
also use appearance context, renderer/package schema, settings and camera preset.
Refresh invalidates the finder. Search changes cancel obsolete work; close retains
threads and owned processes until asynchronous teardown finishes. Completed 3D packages
are saved before thumbnail capture, so an interrupted image does not require preparing
the model again. Matching shape/material requests share one build and capture across
startup and open Finder jobs; a waiting selection receives the ready 3D package while
that capture is still running.

Packages stay pinned during capture. Up to 576 recent full catalogue details are
retained per controller and reused for card selection and page revisits, with
archive-session checks preventing reuse after a rescan. Shared archive inputs coordinate
decoding and publication through bounded preparation gates, preventing concurrent
previews from replacing the same cache metadata at once. Temporary access/sharing
failures retry twice after worker teardown without a click or scroll; persistent
failures label the affected card **Preview unavailable** while the rest of the page
continues.

Each native job keeps its temporary DDS files under its own staging directory, so
another job's cache trimming cannot remove textures before package publication. Streamed
appearance dependencies retain prepared DDS and skeleton-variation files in the complete
preview snapshot, avoiding unnecessary archive-wide lookup and textureless retries.
Thumbnails and **Reset view** use the renderer's front framing; the finder uses
directional lighting to keep facial form readable. Combined-body previews prepare only
their rendered body components.

Heads and bodies share a cached preview when complete model order, authored scale,
component attributes, prefab and dependency identities match. Different shape, material
or customization inputs retain separate caches; ownership links require no additional
extraction. Character labels and ownership remain separate in the catalogue.

### Base appearance

**Base appearance** applies supported model/skeleton variations and scales. The selected
appearance's exact prefab descriptor takes precedence over the shared PAC's base
descriptor, including for its attached meshes. Shared-rig heads also retain a PAB
candidate linked by their morph set; its bone palette must match. An unresolved declared
variation reports a preview failure instead of substituting raw geometry under the
base-appearance label. Existing thumbnails rebuild for the corrected shape selection.
Incomplete dependency snapshots stop with an explanation; they cannot trigger an
archive-wide native scan or be presented as complete appearances.

Customization/material/morph references remain in Details. Declared combined body/head
meshes retain their embedded face instead of stacking a separate head. **Textures
unavailable** means geometry is shown without claiming textured parity. **Unresolved
model** remains browsable with its source evidence. Exact customization and in-game
appearance parity are outside this feature's supported preview claim. An older archive
helper without `character_catalog_v1` requests a current helper.

### Textured preview publication

Textured model requests publish a cache-isolated direct-DDS Rust package as soon as
Preview Core finishes, then promote the same resident scene to the full PAC/PAC_XML
material package without resetting its camera. Rust manifest texture resources are the
active completion authority, so a successful package cannot trigger a redundant forced
texture request through the retired material format. Native texture ownership is
computed once per package. The full material pass reuses verified geometry, direct
textures and presentation settings from the initial package, adds every authored layer,
and publishes a separate package atomically.

A cancelled or failed promotion preserves the initial package. Transient Rust packages
are tracked from worker delivery, including stale results and memory-cache entries.
Retirement waits for cache/current/texture ownership, preview workers, and renderer
leases, then removes the owned wrapper directory on a tracked cleanup worker. Shutdown
waits for retiring helpers before cleanup; durable cache packages and paths outside the
preview output root are preserved. The renderer resolves shader response rules once per
layer and reuses bilinear interpolation coordinates across texture rows.

Composition retains the same texture dimensions, channels, float blending and final
pixels. Plain base textures retain their original compressed DDS and mipmaps. Exact PAC
skin-detail owners use the same repeated normal/material maps, scale and opacity as Mesh
Editor, without baking that detail into the base UVs a second time. Textures that
require layer composition retain level-zero pixels and receive a complete mip chain for
stable filtering and lower rendering cost when zoomed out. Archive Browser defaults to
geometry-only.

Exact PAC colour layers retain their authored opacity, including full-strength detail
colours and channel-specific grime blending. Layered garments without a global
base-colour texture use their first visible texture beneath the masks, as Mesh Editor
does. Older cached previews are regenerated with this material handling.

Its **Load textures** checkbox saves the existing `archive/model_use_textures`
preference and keeps that choice across model selections and application restarts. Asset
Family and referenced-file export choices are resolved independently of that checkbox.
Partial preview results, including cached results with only skeleton or physics
companions, are enriched from the archive relationship lookup without opening Mesh
Editor or loading textures. The checkbox represents user intent while the status row
reports preparation and visibility; geometry, direct and full packages preserve textured
display intent without momentarily hiding the resident textures.

A late texture result respects the current saved choice. The preview health row stays
highlighted while the fast package is being refined and remains explicit when the full
texture pass completes, fails, or times out. PAC, PAM, and PAMLOD packages retain every
material-layer DDS during native cache cleanup, including support maps without a
direct-upload slot. Cached packages with missing layer sources are decoded again before
conversion to Rust. Models without a material wrapper can still display their untextured
base geometry.

If source-declared textures cannot be resolved, the worker prepares a separate
geometry-only native contract and displays **Textures unavailable**. It preserves the
saved texture choice and does not automatically retry the failed texture request.
A missing source shared by several materials stays a missing-source warning when
another material uses its own technique default; that default is never borrowed.
Invalid material ownership and lost parameters still fail validation. The same warning
covers a completed texture lookup with no usable texture sources; geometry-only mode and
authored colour-only materials do not report missing textures.

## Preview dependencies and payload validation

The standalone archive worker discovers PAMI and supported XML/material reference
chains before preparing the preview's bounded dependency snapshot. Textures named
only by a material companion are resolved across archive packages; linked material
documents are followed once, with cycles, cancellation, and scan limits enforced.

Prepared preview dependencies retain the worker's actual payload size separately
from the original PAMT size. Static PAM's single compressed geometry block is decoded
before mesh parsing, including older prepared sources that still contain that block.
Prepared-file size and checksum checks run before decoding and reject changed data.

Texture follow-ups, including Open Mesh preparation, reuse the same completed
dependency snapshot when the archive session, selected entry, appearance scope,
source files and prepared files are unchanged. A matching lookup already running
finishes for the latest request instead of restarting. Explicit preview refreshes,
changed files and pending name indexes still resolve anew; cancellation and changed
selection invalidate queued delivery.

Recovered relationships remain available for any selected extension and survive
preview failure or cache reuse. An exact metadata companion can expose Asset Family
for non-model files without adding unrelated model-family guesses.

Asset Family's **Find references** scans incoming references on demand, independently
of the preview dependency snapshot. `reference_search_plan` limits a search to the
formats measured to store paths of the target's kind
(`cdmw/domain/archives/reference_sources.py`); a numeric `.wem` searches banks for
its media ID, a named `.wem` (voice lines) is not searched because no game file
stores its path, and types no measured format names (`.pamlod`, `.seqmt`, most
audio and video) say so instead of searching. With a worker that advertises `text_search_bytes_v1`,
`archive_reference_search.py` asks it to byte-search those formats for the target's
name, then resolves and prepares only the matching files for the Python check;
older workers fall back to paging and preparing every file of those formats, and
legacy archives use the same cancellable Python reader. Either way a file that
does not contain the name's bytes is rejected before any text decoding, and Asset
Family is rebuilt only when results change. Selection changes, hiding the panel and shell
shutdown cancel outstanding work; stale results cannot replace another selection.
Preparation items arrive on `batch_ready`; the final reply contains totals and no
items. The controller validates and retains only the current page's streamed items
until completion, and clears them on cancellation or failure.
Both Asset Family and Used By separate confirmed paths/media IDs from name-based
guesses and unresolved/context rows. Incoming files do not become outgoing export
dependencies. Matching paths and IDs describe encoded references, not runtime use,
language selection or archive override precedence.

The reader scans registered reference containers and text formats. Sound searches
check banks first, then text metadata, then the remaining registered containers;
other searches check text metadata before binary containers. Resident queries page
each disjoint extension group; the legacy path yields between bounded index slices.
The total read allowance grows with the admitted files instead of stopping at 2 GiB.
Windows language-folder parentheses are retained when matching explicit paths.
Wwise coverage
includes DIDX IDs and standard little-endian HIRC Sound source headers for versions
113–154 (including streamed sources); music, event/action graphs, external sources
and custom layouts are not reconstructed. Unknown versions retain valid DIDX
evidence and report incomplete bank coverage. Bank IDs resolve numeric `.wem`
filenames only; named sounds need a path or filename reference. Per-file reads stop
at 32 MiB and results at 2,000 rows. Oversized, unreadable and
unsupported banks are reported; an empty result never proves an asset unused.
Owned-fixture and headless UI checks cover this path; game acceptance is not implied.

Charts, blend spaces, animation sets and sequences store paths relative to the
folder the engine reads them from. `cdmw/domain/archives/resource_paths.py` owns
those roots: a `.paa` path without `character/` is read under `character/motion/`,
a relative `.motionblending` under `character/binary/motionblending/`,
`character/prefab/` and `object/prefab/` under their `bin__/prefab/` copies, and an
extensionless chart string as `actionchart/bin__/<name>.paac` or
`sequencer/<name>.paseq`. Forward resolution and Find references both treat an
exact match under a root as an explicit path; a path to another folder stays a
basename guess or no match. A one-byte length prefix leaking into a scanned string
is removed only when its value equals the length a chart (`strlen + 1`) or clip
(`strlen`) frame implies. Animation targets read charts, blend spaces and
sequences before other containers. A `.paac` chart's Asset Family lists up to 256
framed resource paths (`cdmw/core/archive_action_chart.py`); extensionless strings
that resolve to nothing are dropped rather than reported missing.

The same module owns installed-layout companions, matched by exact path and
labelled **Path layout** or **Line name** rather than as package guesses:

- a clip's `actionchart/bin__/animmeta/<clip path>_metabin` and its
  `character/motion/motion_lod__/<path>_lod.paa`, both `recommended`;
- the same file in each other voice-language folder (`manual`);
- a `99_autofacial/<language>/` lip-sync clip and `sound/windows/<language>/` voice
  line of the same name (`manual`). Neither file names the other.

Another language's metadata or lip-sync clip is not listed as a companion of this
file. The resident worker delivers LOD clips, base clips and extensionless
sub-charts to the preview snapshot (`ArchiveAnimationReferences.cs`); same-stem
companions already reach it.

WEM Details read the RIFF header without decoding (`archive_wwise_stream.py`):
codec, channel layout, sample rate, length, `smpl` loop range and `cue`/`labl`
markers. Compressed streams report no bit depth.

Bank previews decode the HIRC object graph of version-150 banks
(`cdmw/core/archive_wwise_hirc.py`, layouts after wwiser): every object type the
game ships, with properties, randomizer ranges, playlists, children, media
sources and effect plugin media. An object is reported as decoded only when its
body ends exactly on its declared size; a type outside the shipped set keeps its
framing only. Plugin parameter blocks, decision trees and curves are skipped as
sized spans, not interpreted.

Audio replacement is written as a DMM loose mod, never into the installed
archives. **Import WAV as Loose Mod** on a `.wem` and **Replace Embedded Sound
as Loose Mod** on a `.bnk` both go through `plan_wwise_media_replacement`
(`cdmw/core/archive_audio.py`): the loose `<id>.wem` copies get the new bytes,
every bank embedding the id gets DIDX and DATA rebuilt on 16-byte boundaries, and
every Sound or music-track source that plays the id gets its new size and the
codec the new media declares (`archive_wwise_bank_edit.py`). In-memory sources
get the file size. Prefetched and streamed sources get a prefix of the same
playing time, cut at the replacement's next Vorbis packet (or PCM/ADPCM block),
and an embedded prefetch prefix is replaced by that cut; this needs the
complete original, which is the loose `.wem`. The banks are found by scanning
every `.bnk` in the listing in the background. A `.wem` the user made with their
own Wwise install is used as it is (Vorbis, ADPCM or PCM); any other audio
becomes 16-bit PCM with the original's channels, rate and speaker layout, and the
completion message warns when PCM is four or more times the original's size. The
whole replacement is refused when any bank plays the id through a non-codec
plugin, an effect loads it as plugin data, an undecoded object may name it, or a
stream prefix does not end on a packet. Named `.wem` voice lines are not
described by any bank, so only the file is replaced.

**Edit Sound Bank as Loose Mod** on a `.bnk` (`sound_bank_editor.py`, model and
plan in `archive_wwise_bank_plan.py`) lists every value the writer can change:
stored properties of measured types, randomizer ranges, container loop and
transition values, playlist weights and Set-property action values. It can also
add a property or range that some shipped object of the same type stores
(`change_hirc_properties`, kept sorted by id, objects and HIRC resized), remove
one so the object inherits it again, add a sound to a random/sequence container
as a copy of a sibling playing new media embedded in this bank, and remove a
sound that nothing else names (`archive_wwise_bank_variations.py`). New object
and media ids are Wwise ShortIDs checked against every bank and loose media id in
the listing. The plan is applied in a fixed order (values, properties, removed
then added sounds) in the background, and the bank is written as a loose mod.
Owned fixtures, headless dialog and action tests, and read-only round trips over
the shipped banks cover this. In game (2026-11-02, through DMM) added bus and
Sound properties, an in-place value edit, embedded and loose media swaps (held in
memory or streamed, with recomputed prefixes), PCM and added container sounds
were heard working. On a bus, `Volume` affects only sounds routed straight to it;
`BusVolume` is the bus's own gain. The banks and loose copies a replacement
touches are the active entry per path, as the game loads them. Removing a sound
keeps its embedded media, which another bank may play. A named voice line takes
only a `.wem` in its original codec, because the game names its codec. Music
tracks keep their clip timing, and the completion message says when a
replacement is longer or shorter. DMM serves files in language folders only for
the language selected in DMM.

WEM preview and WAV export remove the Windows extended-path prefix only from
vgmstream's command arguments: its wildcard parser treats the prefix's `?` as a
pattern and otherwise fails to open ordinary cached sounds. Internal cache I/O keeps
the prefix. This fixes the prefixed-path regression; the bundled decoder still has
its own long-path and non-ANSI filename limits.

Preview and Details text keep their syntax highlighter attached during replacement.
Document signals are blocked for the replacement, then highlighting is refreshed;
disconnecting the highlighter can deadlock with preview-worker QObject teardown.
For a DDS raw-byte fallback, Details retains the file path and the original
`Decoded preview failed` error. Readable strings alone do not diagnose that failure.
Raw-byte fallbacks are excluded from the preview cache and ignored in existing
worker snapshots, so reopening an entry or choosing Refresh retries decoding.
DDS display failures retain the current conversion's native error without taking
messages from other workers or consuming the shared diagnostic history.

### Binary format inspectors

`archive_preview_result_builder.py` sends these formats to exact read-only
inspectors before the readable-strings fallback:

- `.padxil` shaders and `.pars` root signatures: `archive_shader_preview.py`
  splits the PASC wrapper and DXBC container and decodes PSV0, signatures, SFI0,
  RDAT and RTS0. DXIL/STAT bitcode is not disassembled.
- `.parg`, `.pasg`, `.pcg`, `.save` and `.uianiminit`: `archive_reflect_preview.py`
  decodes them with `effect_binary.py` and lists the object graph. A fully walked
  `.pcg` also returns a convex-hull model for the 3D view; schema revision 14 files
  are read without collection presence bytes. `.pae`/`.paem` keep the structured
  inspector, led by the same exact graph.
- `.imp` tree impostors: `archive_impostor_preview.py` labels the 72-byte record,
  and the builder shows the `_impostor_color.dds` atlas the worker supplies as a
  preview companion (`ArchiveLookupService.AddPreviewCompanionPaths`).
- `.paac` action charts and the `.paacdesc` package description:
  `archive_action_chart_preview.py` decodes them with `action_chart_binary.py`
  (the game loader's member order) and lists animations with time ranges, nodes,
  each animation's frame events with the names they reference, string tables, byte
  totals per section and the edit scope. The two `commonactioninfo` files show their sections; the serialized
  one marks its undecoded reflection tail.
- Action charts (`action_chart_actions.py`, `action_chart_editor_dialog.py`,
  `action_chart_finder_dialog.py`, `action_chart_export_dialog.py`): **Edit Action
  Chart...** on a standard `.paac`, **Find Action Chart by Character...** on any
  `.paac`/`.paacdesc`, and the **Action Charts** button (finder and **Open Action Chart
  Mod...**), which works with nothing selected. The live browser keeps no in-process
  extension index, so the worker builds one with `chart_archive_index` from
  `scan_archive_entries` (charts, the descriptor, clips, blend spaces, sequencers,
  prefabs), cached per game folder until a `.pamt` changes. The editor is not modal, so
  **Show in Archive Browser** can search for a clip while it stays open; **Use Clip
  Length** reads the clip on the dialog's worker. The worker also builds
  `chart_scan` (every standard chart's clip table and included charts, about 4 s,
  cached with the index); the finder lists each slot chart's includes recursively and
  "used by" names slots that reach a chart through them, so the editor names the other charts that play a clip; **Other Charts Playing
  This Clip...** queues `LinkedClipChange`s that export applies to those charts in the
  same mod. Edits apply on that worker through
  `cdmw/services/action_chart_edit_service.py` and every table is rebuilt from the
  edited bytes. Export writes a DMM archive-group mod (`0036/0.pamt` + `0.paz`,
  manifest.json, modinfo.json) into DMM's mods folder or a chosen folder, keeps the
  other charts of a mod with the same name, and never replaces a folder CDMW did not
  write; `read_chart_mod` reopens one.
- `.ttf`/`.otf`/`.ttc` fonts and `.ani` cursors: `archive_ui_resource_preview.py`
  reads the sfnt tables or RIFF chunks and renders a PNG with Pillow into the
  pruned `archive_preview_cache` (units named `ui-<kind>-v1-<content hash>`).

A container these readers refuse falls back to readable strings, with the reason
in Details. A failed font or cursor render keeps the text description. Strings in
these previews are diagnostic text and are not translated.

### Static data tables

`archive_data_table_preview.py` lists a `.staticinfoheader`/`.staticinfobody` pair's
rows once both halves come from the same archive index. For the 140 tables in the
closed compact schema (`cdmw/core/_compact_static_schema.py`, listed by
`static_table_records.DECODED_TABLES`), it also decodes the first five listed rows
through `static_table_records.decode_record` and prints their top-level fields: integers by
storage width, a member the game reads in parts as each part (`u32+u32`), text, and nested
lists or structures as byte counts. Larger rows are never decoded just for the preview.
A row the schema refuses keeps its listing line and is counted in Details; nothing is
guessed; on the installed game that is 13 rows whose readers sit in virtualized game code.
Tables named `skillinfo` or `reserveslotinfo` in older archives use the `skill` and
`reserveslot` readers. StringInfo keeps its own reader; BitmapPosition lists rows only.

Right-click a table of an editable family and choose **Edit Game Table Values...**
(`game_table_actions.py`). The dialog hosts Create New Item's `GameTablesEditor`: pick a
table and row, select a value, type the new value and **Set value**, then **Write DMM
Mod…**. Loading and writing run on the shell's utility worker. Only the values in
`static_table_records.EDITABLE_FIELDS` (inventory slot counts, skill max level, cooldown
and low-resource flag, bounty increase, mercenary hire and summon limits, character scale
and companion call cooldown, gameplay variable defaults) and `EDITABLE_MEMBERS` (drop set
chances and quantities, NPC equipment drop chances, level experience) are offered; each
keeps every row length and the row directory unchanged and is decoded again after the
write.

`services/game_table_edits.py` reads the base and DLC copies the item-data rules choose
and composes the base copy DMM needs: rows the base supplies are edited in place, rows
the DLC replaces carry their DLC version with the edit, and rows only the DLC has are
listed but locked. The edited pairs go into a DMM mod folder (archive group `0036`, read
back before it is published) in DMM's mods folder; a folder this editor did not write is
never replaced. PAMT/PAZ in the game folder are never touched. Units and in-game effect
of these values are unverified.
`structured_sidecar_edit_service.write_static_table_edits` remains for loose-file output.

## Read-only boundary and exports

Browsing, preview, scan, extraction, and package preparation are read-only.
Actions that can write route through service-owned confirmation and
`ArchiveMutationService`; this UI package never patches PAMT/PAZ directly.

**Actions > Extract Selected / Extract Filtered** exports original files of any
type, including mixed extensions. Both commands also appear in a file's right-click
menu. Ctrl/Shift-select files and right-click a selected row to retain the whole
selection. **Extract File...** exports just the clicked file through the same
archive worker. **Extract Filtered** uses every result of the applied search,
including pages not loaded on screen; apply changed filters with **Search** first.
Individual selections are limited to 4,096 rows. For larger sets, use
**Extract Filtered** or right-click one folder and choose **Export Folder...**.
Folder exports include matching subfolders. Set the **Extract** folder under
**Archive Locations**, then review the destination and existing-file choices.
Extraction retains original formats and folder paths; it does not convert files.
Filter availability uses the current catalogue query, including after a background
operation finishes, rather than the retired local entry list.

Archive OBJ/FBX conversion rejects incomplete `PartialRaw` mesh payloads; select
the PAMLOD companion explicitly when the PAM is incomplete. PAMLOD conversion
uses the first usable LOD and retains its individual material groups, local
triangle indices, and source vertex mapping. Selected related entries are copied
as original files; only the primary mesh is converted. The mesh, materials,
selected companions, and manifest are staged together. A preparation failure or
cancellation preserves the previous export, and publication rolls back on failure.

### Export file paths

**Actions > Export File Paths...** saves catalogue paths without extracting payloads.
Choose **All files**, **Filtered results**, **Selected files (up to 4,096)**, or
**Selected folder (including subfolders)**. The folder context menu opens the same
dialog. Filtered results use the last applied **Search**, including unloaded pages;
folder exports intersect those results with the selected folder and its descendants.
All files uses the loaded catalogue, including duplicates, and respects scan exclusions.

TXT is UTF-8 with one archive-relative path per line. CSV is UTF-8 with a BOM and
the columns `path`, `filename`, `package`, `source_pamt`; the latter identifies the
source archive index. Both retain duplicate rows and use `/` path separators.
No mod-manager installation prefix is added. Export pages only catalogue metadata
and writes in a background task. Cancellation or failure preserves an existing
destination; a complete list replaces it atomically.

### Character bind axes

Character previews and neutral exports reconcile paired PABC bind-axis reversals
only when the complete corrected matrix matches the PAB bind within 1e-4
(0.1 mm for translation). This prevents Damian's embedded ear from folding while
retaining small authored adjustments and other neutral shape changes. Animation
poses are unaffected. The native package cache invalidates older baked previews.

### Add Bones and Skeleton Edit JSON

A `.pab` entry's **Structured Data** menu opens **Add Bones...**
(`pab_bone_editor_dialog.py`): numbered steps whose current step is bold, a
**Quick pick** row for common attach points (only those the rig has), a
searchable bone tree, front and side outlines that select a bone on click,
**Add Child Bone**, **Add Chain...** (count,
segment length and a character-space direction), **Remove** (an added bone and
what was added under it) and a form for the selected added bone. Offsets are
edited along the character's axes (X left, Y up, Z back) and stored in the
parent's space; rotation stays relative to the parent. Every change rebuilds the
skeleton, and the first refusal disables **Save as Mod...** with its reason.
**Save Draft...** and **Open Draft...** use Skeleton Edit JSON. A game bone
shows a read-only summary that explains why it cannot change and names the
bone offset table, with **Add Child Bone Here** and **Add Chain Here...**.
Bones outside the rig's largest root (`body_bone_names`) are grouped under
**Markers (do not follow the body)**, and a bone added under one carries a
warning, because root-motion, IK and climb targets stay at the feet or origin. A rename to a taken or invalid name is refused without touching other
bones, and Enter in a field never presses the accept button. Create New Item's **Add bones…** opens the same dialog with
`initial_edits` and its own accept label (**Use These Bones**) and reads
`edits()` instead of writing a package (see the New Item README).

The same menu offers **Export Skeleton Edit JSON...**
and **Import Skeleton Edit JSON...** (`pab_json_actions.py`). The export lists
every bone as a read-only reference and an empty `add_bones` list. Import
checks the document against the selected skeleton's SHA-256 and its unchanged
bone names and parents, appends the listed child bones through
`cdmw/services/pab_skeleton_edit_service.py`, and only then asks for a
mod-ready loose package target. A document that adds nothing writes nothing.
Shipped bones cannot be renamed, removed or reordered (see the modding README),
and added bones are untested in game.

### GLB, FBX and OBJ export and round trips

**Export > Export This Model as GLB...** exports one PAC, PAM or PAMLOD directly from the
archive. GLB is listed first for rigged editing, followed by FBX and OBJ. GLB
includes companion metadata and resolved textures; PAC weights require a resolved
skeleton and bone mapping. Review export warnings: an unresolved palette leaves
the mesh without usable weights, and a missing skeleton requires confirmation to export only
the mesh. Keep the model and companion files together for **Round-trip edit**.
OBJ remains geometry-only.

OBJ, MTL and round-trip metadata support Unicode output folders and file names,
including Chinese characters, independently of the interface language.

**Export > Batch Export Selected Models as GLB... / FBX... / OBJ...** converts
explicitly selected PAC, PAM and PAMLOD file rows in a sequential batch. Use Ctrl
or Shift to select models; folder/category rows and other file types are excluded.
The same commands appear in a model's right-click menu. Each model gets a fresh
`model_<name>` folder under the chosen root, with numbered suffixes for collisions.
Resolved referenced files are included; existing output folders are preserved.
OBJ keeps source coordinates. PAC GLB and FBX exports without a usable skeleton
fail unless **Allow export without a skeleton** is explicitly enabled for the batch.

The dialog shows progress and a copyable per-model report with output folders,
warnings, failures and cancellation results. **Cancel** stops preparation or
requests cancellation of conversion; completed exports remain available. Closing
an active dialog requests cancellation and keeps the report open until the current
worker has finished. The batch resolves each model's bounded dependency set through
its own archive provider; no preview selection or global catalogue rebuild is
required. Conversion retains the existing supported-format and round-trip limits.
Fixture conversions and UI checks do not establish real-game acceptance.

**Export > Export This Model as OBJ** exports the selected archive mesh without requiring a loaded
preview. It and the right-click **Export This Model as OBJ...** action preserve the PAC's original
positions and normals, including embedded head and ear geometry. To bake the same
neutral skeleton variation used by FBX,
right-click a PAC and choose **Export This Model as OBJ (Neutral Appearance)...**. The matching
`.meta.json` stores the source identity and, for neutral exports, the reversible
appearance transform. **Round-trip edit** converts neutral OBJ positions and normals
back to PAC coordinates, retains donor skin weights and lower LODs, and restores part
order and duplicate triangles removed by Blender.

Keep vertex order and counts; topology or rig changes require their separate
replacement/authoring workflows. Blender corner-normal splits can recover the original
vertex slots when positions, UVs and protected channels agree and a source normal or its
reversal remains. The import summary reports retained source normals; new UV seams or
separate hard-edge normals need topology replacement.

### Blender return workflow

In Blender, return an OBJ, FBX or GLB and keep the matching manifest beside it as
`<returned>.<format>.meta.json`. GLB carries the richest material, rig and morph
data. For GLB or separate-file glTF, enable **Data > Mesh > Attributes** to retain
`_CDMW_VERTEX_ID`, set **Use Vertex Color > Active**, and enable **Include All
Bone Influences**. Export only the selected model meshes and armature, excluding
bone-display shapes. FBX import uses the selected Blender executable; retain the reserved
`CDMW_VERTEX_ID` UV layer so edited vertex identities survive conversion. OBJ
returns carry positions, normals and UV edits, with protected rig and other
unsupported data retained in the companion. Export reports list missing textures
and format limitations. Existing animation clips are retained; animation editing
is unavailable. Disable modifiers that change topology for a same-count return.
The importer recovers unchanged coordinates, UVs and normal directions within
serialization and Blender custom-normal rounding precision.
When changing return format, the companion recovers omitted extra UV sets and
texture bindings while retaining imported channel edits. Static OBJ returns
recover the original local coordinate frame. Split OBJ companions also retain
the scene graph and existing clips; importing one split part does not reconstruct
the other parts of a game mesh.

Larger Blender normal changes remain edits, so an untouched Blender session is not
always a byte-identical return. Normal writes preserve the shared tangent and handedness
bits; UV writes use correctly rounded half floats. Normal and UV edits retain all
position bytes and bounds. A position edit that expands shared bounds compensates
lower-LOD positions within half a quantization step and preserves their other vertex
lanes. Unproven or conflicting lower-LOD ownership blocks that expansion. The rebuild
verifies the resulting neutral positions and normal directions.

A nearly singular skin transform can magnify an edit beyond PAC precision; displacements
over the position tolerance or normal errors over one degree are blocked with the
affected part and measured error. Use a source-coordinate OBJ for such normal edits, or
Mesh Replacement for incompatible geometry changes.

### FBX rig and morph output

FBX retains its rig and recovered morph support, merges repeated influences on the same
bone, and connects the resolved diffuse DDS files using portable paths. OBJ uses the
same resolved diffuse evidence. These interchange materials do not recreate the game's
complete layered shader. Rigid attachments without a PAC bone palette retain their
source geometry without guessing an attachment bone. Other unresolved palettes also
export source coordinates: the summary marks neutral appearance as unavailable, and FBX
includes an unbound armature. OBJ returns still retain the original PAC skin records.

**Export Character and Related Game Files...** collects the original character
model and its resolved game files. These packages preserve `character/...` paths directly below the chosen
root so the appearance manifest can find and verify every companion. The extraction
service's `include_package_directory=False` selects this layout for both extraction and
collision checks; ordinary extraction keeps its archive package directory by default.
