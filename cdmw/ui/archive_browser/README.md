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
