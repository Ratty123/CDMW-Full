# Archive Browser

Owns archive listing, filtering, preview coordination, item icons, and archive
browser actions. Keep virtual model behavior in `model.py`; keep UI assembly and
feature coordination in focused modules as they are extracted from the shell.

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

Character OBJ exports bake the same neutral skeleton variation used by FBX.
OBJ carries no armature or facial morph channels. Its baked appearance manifest
disallows direct source-asset edits; **Modify Original** still uses the original
editable coordinates. FBX retains its existing rig and recovered morph support.
Character dependency packages preserve `character/...` paths directly below the
chosen root so the appearance manifest can find and verify every companion.
The extraction service's `include_package_directory=False` selects this layout
for both extraction and collision checks; ordinary extraction keeps its archive
package directory by default.
