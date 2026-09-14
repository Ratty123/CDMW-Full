# Archive Browser

Owns archive listing, filtering, preview coordination, item icons, and archive
browser actions. Keep virtual model behavior in `model.py`; keep UI assembly and
feature coordination in focused modules as they are extracted from the shell.

**Mesh Replacement is temporarily disabled for release review.** Its
**Replace Mesh from File...** action is absent from the Import and mesh context
menus, and its retained action button stays disabled as selection and busy state
change. The builder implementation remains available for development.

The retained workflow takes a PAC/PAM/PAMLOD target and an OBJ, DAE, GLB or glTF
source. **Mesh Replacement** in the setup dialog opens alignment/mapping review
in Mesh Replacement Builder to build a mod-ready loose package.
**Round-trip edit** is for an OBJ exported by
CDMW whose original mesh structure is preserved. Unsupported target formats
remain blocked by preflight. Replacement opens its own window and preserves
any active Mesh Editor session.

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

When a PAM has an indexed PAMLOD companion, both meshes must rebuild successfully.
A failed companion rebuild stops the build with the companion path and error;
it cannot produce a package containing only the PAM.

**Import Loose Mod Folder...** scans already prepared game-format mod files and
matches them to archive entries; it does not convert OBJ models. Source scans
and replacement source imports use the main window's background utility worker,
with the requesting workspace/dialog retained as their result-lifetime guard.

The Tools menu and archive-file context menu temporarily omit HKX actions.
The underlying HKX editor and import/export code remain available for other workflows.

Mesh Builder close cancels pending work and hides the dialog promptly. The
lifecycle owner retains the closed dialog until every child thread has finished
native teardown, then deletes it asynchronously. Partial construction failures
use the same rule.

The resident v2 catalogue is the listing authority. Its status messages reach the
owning shell through the archive workspace's `shell` reference. Preview requests are
request-correlated and latest-wins: a stale selection may be superseded but may
not clear or replace the current scene. Archive Browser publishes the path,
basename, extension, dependency, and native package indexes reused by Model
Library, Mesh Editor, and Create New Item.

The resident item catalogue and name index follow model paths embedded in matching
part-prefab payloads. A shared PAC can therefore carry every owning item name, and an Item
Finder scope includes those resolved model dependencies even when the item's prefab or icon
uses a different numeric stem. Archive Browser and Create New Item also share Preview Core's
PAC RGB selector-mask colour reconstruction. Item Finder additionally retains the selected
logical prefab ahead of shared physical siblings, allowing the background preview worker to
decode its per-model `_modelPropertyIndex`; variant-aware package keys prevent two items that
share a PAC from reusing each other's material set.

Item names use the active ItemInfo row directory and item localization domain. Current
`binarystaticinfo__` body/header pairs and per-language `item.paloc` files take precedence
over obsolete legacy tables, with `meta/0.papgt` mount order selecting active overlays.
StringInfo keys are joined to archived prefabs before decoding their actual PAC paths.
Browse Archives displays `Shared asset (N names)` for multiple distinct names while its
tooltip and search retain the complete set. Item Finder retains rows without model links;
generated names are identified in its evidence, and asset actions require asset links.
English is the display language; Item Finder and New Item search all discovered item languages, and
missing English is not silently substituted from another language. New Item uses the
same source selection and name lookup; its separate Item Name cell shows `-` when missing.

## Body & Face Finder

After scanning, open **Body & Face Finder** beside Item Finder. **Bodies** and
**Faces** offer **Unique assets** and **Appearance variants**, 72-result pages,
name/ID/path search, and component, source-family, body-family and resolution
filters. English character names are displayed; discovered character languages
remain searchable. **Used by / Components** links appearances to shared models.
Both views start with **Humanoids** (player and NPC families); choose **Creatures**,
another type, or **All types** to widen the results. **Faces** starts with separate
heads. Hair, beards and facial details (including tear and eye meshes) require their component filter; a face
embedded in a full body remains in **Bodies**. **Clear filters** restores these
defaults. An explicitly selected type is remembered, including **All types**.
**Show exact files** and **Show related files** return a bounded entry-ID scope to
Archive Browser, where existing extraction/export/editor actions remain available.

The resident .NET archive worker owns the character catalogue independently of
ItemInfo. It accounts for active models and appearance/prefab references, including
orphans, unresolved ownership and ambiguous basenames. Unique assets contain actual
model files; unresolved descriptors remain in reference coverage and appearance
details. Equipment remains part of its owning appearance assembly without becoming
a standalone body result. Vehicle models and assemblies containing only non-body
components are excluded. Mesh/submesh metadata distinguishes bodies from hair,
fur and accessories. Unclassified models require the **Unclassified** component
filter instead of appearing in default Bodies/Faces results. Mount precedence
chooses active paths; complete CharacterInfo
table pairs and verified CharacterAppearanceIndexInfo full-path hashes supply
names. Missing XML attribute separators are repaired only in memory and reported.

After the archive view is ready, two background jobs preload up to three pages
per tab (432 results), alternating Bodies and Faces with both landing pages first.
The catalogue results and rendered thumbnails are reused when the finder opens.
Opening the finder pauses queued startup work while already assigned previews
finish and remain reusable. Closing it resumes the remaining queue.
New archives invalidate the warmup, and the shell retains its threads through
shutdown. The first uncached render still requires model and texture preparation.

The finder owns a separate Rust preview session. Bounded background jobs
prepare previews and 256px thumbnails. Visible cards go first, then the rest of
the current 72-result page loads automatically without scrolling. Selection takes
priority; selecting a card already being prepared reuses that job and can display
its ready 3D package while thumbnail capture finishes. Other slots continue the page. Scrolling
reprioritizes waiting cards without restarting current page jobs. Thumbnail
captures render at 256px; the interactive preview keeps its full geometry and textures.
The **Show underwear** checkbox toggles separately identified underwear meshes in
the interactive preview immediately, without extracting or rebuilding the model.
The choice carries across selections within the dialog. Thumbnails keep the base
appearance; clothing painted into the skin texture cannot be hidden this way.
Catalogue lookahead starts as soon as a page appears and fetches up to four more
pages, with one catalogue request outstanding at a time. Once the on-screen cards
finish, up to two render jobs share the available slots with the rest of the
current page. When that page is complete, up to four jobs prepare future cards,
depending on the available lanes. Selection and newly visible cards take priority.
**Next** reuses prepared cards or promotes the pending page request; useful future
requests survive page changes, while obsolete cache scans are cancelled. The eight
most recent result pages are retained for navigation. Background results do not
change the current grid or interactive preview; changing filters cancels obsolete work.
Head pages use up to eight jobs (half the logical processors); other component
pages use at most four. Small systems use two jobs. Previously generated page
thumbnails appear as each is found in a fingerprint- and settings-scoped index, without
repeating character detail requests or geometry preparation. Uncached cards start
preparing as soon as their own cache check finishes, while later records are still
being read. This applies to both the current page and the next-page preload.
Up to 576 thumbnail records and icons (eight pages) stay in memory for revisits.
Shared image paths reuse one icon, and returning to cached cards skips their
row/render JSON reads. Image existence is checked in the background; removed
images return to the normal cache lookup and regeneration path. The remembered
records are scoped to the archive session, and a rescan clears the dialog caches.
Finder package builds use the existing 2 GiB disk-cache policy, trimming toward
1.5 GiB, to retain more prepared models across page changes. Saved images remain
usable after their larger 3D packages leave that bounded cache; selecting one can
rebuild its interactive package. Catalogue caches
use archive generation, mount signature and format version; thumbnails also use
appearance context, renderer/package schema, settings and camera preset. Refresh
invalidates the finder. Search changes cancel obsolete work; close retains
threads and owned processes until asynchronous teardown finishes.
Completed 3D packages are saved before thumbnail capture, so an interrupted image
does not require preparing the model again. Matching shape/material requests
share one build and capture across startup and open Finder jobs; a waiting
selection receives the ready 3D package while that capture is still running.
Packages stay pinned during capture. Up to 576 recent full catalogue details are
retained per controller and reused for card selection and page revisits, with
archive-session checks preventing reuse after a rescan.
Shared archive inputs coordinate decoding and publication through bounded
preparation gates, preventing concurrent previews from replacing the same cache
metadata at once. Temporary access/sharing failures retry twice after worker
teardown without a click or scroll; persistent failures label the affected card
**Preview unavailable** while the rest of the page continues.
Each native job keeps its temporary DDS files under its own staging directory,
so another job's cache trimming cannot remove textures before package publication.
Streamed appearance dependencies retain prepared DDS and skeleton-variation files
in the complete preview snapshot, avoiding unnecessary archive-wide lookup and
textureless retries. Thumbnails and **Reset view** use the renderer's front framing;
the finder uses directional lighting to keep facial form readable.
Combined-body previews prepare only their rendered body components. Heads and
bodies share a cached preview when complete model order, authored scale, component
attributes, prefab and dependency identities match. Different shape, material or
customization inputs retain separate caches; ownership links require no additional
extraction. Character labels and ownership remain separate in the catalogue.

**Base appearance** applies supported model/skeleton variations and scales.
The selected appearance's exact prefab descriptor takes precedence over the shared
PAC's base descriptor, including for its attached meshes. Shared-rig heads also
retain a PAB candidate linked by their morph set; its bone palette must match.
An unresolved declared variation reports a preview failure instead of substituting
raw geometry under the base-appearance label. Existing thumbnails rebuild for the
corrected shape selection.
Incomplete dependency snapshots stop with an explanation; they cannot trigger
an archive-wide native scan or be presented as complete appearances.
Customization/material/morph references remain in Details. Declared combined
body/head meshes retain their embedded face instead of stacking a separate head.
**Textures unavailable** means geometry is shown without claiming textured parity.
**Unresolved model** remains browsable with its source evidence. Exact customization
and in-game appearance parity are outside this feature's supported preview claim.
An older archive helper without `character_catalog_v1` requests a current helper.

Textured model requests publish a cache-isolated direct-DDS Rust package as soon
as Preview Core finishes, then promote the same resident scene to the full
PAC/PAC_XML material package without resetting its camera. Rust manifest texture
resources are the active completion authority, so a successful package cannot
trigger a redundant forced texture request through the retired material format.
Native texture ownership is computed once per package. The full material pass
reuses verified geometry, direct textures and presentation settings from the
initial package, adds every authored layer, and publishes a separate package
atomically. A cancelled or failed promotion preserves the initial package.
The renderer resolves shader response rules once per layer and reuses bilinear
interpolation coordinates across texture rows. Composition retains the same
texture dimensions, channels, float blending and final pixels.
Plain base textures retain their original compressed DDS and mipmaps. Exact PAC
skin-detail owners use the same repeated normal/material maps, scale and opacity
as Mesh Editor, without baking that detail into the base UVs a second time.
Textures that require layer composition retain level-zero pixels and receive a
complete mip chain for stable filtering and lower rendering cost when zoomed out.
Archive Browser defaults to geometry-only. Its **Load textures** checkbox saves
the existing `archive/model_use_textures` preference and keeps that choice across
model selections and application restarts. The checkbox represents user intent
while the status row reports preparation and visibility; geometry, direct and
full packages preserve textured display intent without momentarily hiding the
resident textures. A late texture result respects the current saved choice.
The preview health row stays highlighted while the fast package is being refined
and remains explicit when the full texture pass completes, fails, or times out.
PAC, PAM, and PAMLOD packages retain every material-layer DDS during native cache
cleanup, including support maps without a direct-upload slot. Cached packages
with missing layer sources are decoded again before conversion to Rust. Models
without a material wrapper can still display their untextured base geometry.
If source-declared textures cannot be resolved, the worker prepares a separate
geometry-only native contract and displays **Textures unavailable**. It preserves
the saved texture choice and does not automatically retry the failed texture
request. Invalid material ownership and lost parameters still fail validation.
The same warning covers a completed texture lookup with no usable texture sources;
geometry-only mode and authored colour-only materials do not report missing textures.

The standalone archive worker discovers PAMI and supported XML/material reference
chains before preparing the preview's bounded dependency snapshot. Textures named
only by a material companion are resolved across archive packages; linked material
documents are followed once, with cycles, cancellation, and scan limits enforced.

Prepared preview dependencies retain the worker's actual payload size separately
from the original PAMT size. Static PAM's single compressed geometry block is decoded
before mesh parsing, including older prepared sources that still contain that block.
Prepared-file size and checksum checks run before decoding and reject changed data.
Recovered relationships remain available for any selected extension and survive
preview failure or cache reuse. An exact metadata companion can expose Asset Family
for non-model files without adding unrelated model-family guesses.

Browsing, preview, scan, extraction, and package preparation are read-only.
Actions that can write route through service-owned confirmation and
`ArchiveMutationService`; this UI package never patches PAMT/PAZ directly.

Archive OBJ/FBX conversion rejects incomplete `PartialRaw` mesh payloads; select
the PAMLOD companion explicitly when the PAM is incomplete. PAMLOD conversion
uses the first usable LOD and retains its individual material groups, local
triangle indices, and source vertex mapping. Selected related entries are copied
as original files; only the primary mesh is converted. The mesh, materials,
selected companions, and manifest are staged together. A preparation failure or
cancellation preserves the previous export, and publication rolls back on failure.

Character previews and neutral exports reconcile paired PABC bind-axis reversals
only when the complete corrected matrix matches the PAB bind within 1e-4
(0.1 mm for translation). This prevents Damian's embedded ear from folding while
retaining small authored adjustments and other neutral shape changes. Animation
poses are unaffected. The native package cache invalidates older baked previews.

**Export OBJ...** preserves the PAC's original positions and normals, including
embedded head and ear geometry. To bake the same neutral skeleton variation
used by FBX, right-click a PAC and choose **Export OBJ (Neutral Appearance)...**.
The matching `.meta.json` stores the source identity and, for neutral exports,
the reversible appearance transform. **Round-trip edit** converts neutral OBJ
positions and normals back to PAC coordinates, retains donor skin weights and
lower LODs, and restores part
order and duplicate triangles removed by Blender. Keep vertex order and counts;
topology or rig changes require their separate replacement/authoring workflows.
Blender corner-normal splits can recover the original vertex slots when positions,
UVs and protected channels agree and a source normal or its reversal remains. The import summary
reports retained source normals; new UV seams or separate hard-edge normals need
topology replacement.

In Blender, return an OBJ with modifiers disabled and keep the matching manifest
beside it as `<returned>.obj.meta.json`. This also supports a mesh first exported
as FBX: retain and rename its `.fbx.meta.json` for the returned OBJ. Direct FBX
input remains a separate Blender conversion/replacement workflow. OBJ returns
carry positions, normals and UV edits; they retain the PAC's original rig data.
The importer recovers unchanged coordinates, UVs and normal directions within
OBJ/f32 and Blender custom-normal rounding precision. Larger Blender normal
changes remain edits, so an untouched Blender session is not always a byte-identical
return. Normal writes preserve the shared tangent and handedness bits; UV writes
use correctly rounded half floats. Normal and UV edits retain all position bytes
and bounds. A position edit that expands shared bounds compensates lower-LOD
positions within half a quantization step and preserves their other vertex lanes.
Unproven or conflicting lower-LOD ownership blocks that expansion.
The rebuild verifies the resulting neutral positions and normal directions.
A nearly singular skin transform can magnify an edit beyond PAC precision;
displacements over the position tolerance or normal errors over one degree are
blocked with the affected part and measured error. Use a source-coordinate OBJ
for such normal edits, or Mesh Replacement for incompatible geometry changes.

FBX retains its rig and recovered morph support, merges repeated influences on
the same bone, and connects the resolved diffuse DDS files using portable paths.
OBJ uses the same resolved diffuse evidence. These interchange materials do not
recreate the game's complete layered shader. Rigid attachments without a PAC
bone palette retain their source geometry without guessing an attachment bone.
Other unresolved palettes also export source coordinates: the summary marks
neutral appearance as unavailable, and FBX includes an unbound armature. OBJ
returns still retain the original PAC skin records.
Character dependency packages preserve `character/...` paths directly below the
chosen root so the appearance manifest can find and verify every companion.
The extraction service's `include_package_directory=False` selects this layout
for both extraction and collision checks; ordinary extraction keeps its archive
package directory by default.
