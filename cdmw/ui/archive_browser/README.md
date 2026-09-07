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
Archive Browser defaults to geometry-only. Its **Load textures** checkbox saves
the existing `archive/model_use_textures` preference and keeps that choice across
model selections and application restarts. The checkbox represents user intent
while the status row reports preparation and visibility; geometry, direct and
full packages preserve textured display intent without momentarily hiding the
resident textures. A late texture result respects the current saved choice.
The preview health row stays highlighted while the fast package is being refined
and remains explicit when the full texture pass completes, fails, or times out.

Browsing, preview, scan, extraction, and package preparation are read-only.
Actions that can write route through service-owned confirmation and
`ArchiveMutationService`; this UI package never patches PAMT/PAZ directly.
