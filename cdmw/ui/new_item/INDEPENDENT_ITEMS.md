# Independent item packages (Experimental)

Choose **Output > Independent item package (Experimental) · .cditem**, build the plan and
select **Write item package**. Share the resulting `.cditem` file. Recipients use
**Mod Management > Independent items > Import packages** to inspect and install
one or more packages. Existing folder exports and game overlays remain available.

The item list sorts by **Item**, **Game ID** or **Status** when you click a column
heading; clicking again reverses the order. Game IDs sort numerically. Drag the
column edges to change widths. Refresh preserves the sort, widths and selected
package. The default layout keeps IDs and status readable as the pane resizes.

CDMW composes the game's shared files during installation. Separate `.cditem`
files are portable authoring packages, not standalone archives the game discovers.
No manual mod merge is required for compatible packages installed through CDMW.

## Identity and ownership

Each package has a permanent UUID. **Write item package** creates a new identity,
including when duplicating the current draft. **Update an existing item package**
explicitly selects the UUID to preserve, even when names or appearance change.
Technical game identities are managed; player-facing names remain editable.

Successfully installed independent packages have distinct identities and cannot
silently overwrite each other's owned records or assets. CDMW refuses ambiguous
overlap, unknown owned reference layouts, incompatible dependencies, hash/name
collisions and exhausted allocation ranges. This is not universal compatibility
with arbitrary external mods, and does not establish runtime save compatibility.

Installation allocates item/perk, recipe and reward integers in the existing
1,990,000–1,999,999 range. No numeric range was widened. Names, localisation keys,
model families and effects are rebuilt from the destination bindings. Reflection
references use decoded values and bounded, declared strings; effect names retain
their byte lengths. Embedded emitter file types are rebound with emitter names
and included in dependency validation. The original shared table records are
preserved, apart from supported additive shop stock and item-group membership.

Updates retain prior identities and atomically replace the selected item's
contribution. Importing identical content is a no-op. Removal deletes only that
contribution from composed output. All issued identities and asset paths remain
reserved, including retired auxiliary records. Normal CDMW overlay installation
also refuses to take an independent package's reserved item keys. External tools
cannot be forced to honour these reservations; detected overlaps are refused.

Saves can still reference removed items. CDMW does not edit saves. Export an
**identity profile** (`.cdprofile`) with saves when moving computers, import it
before the packages on the destination, then install the original packages.
Conflicting profiles are refused instead of renumbering saved identities.

## Package and installation contracts

Version 1 uses ZIP with `item.json` and SHA-256-addressed `assets/` entries.
The data-only recipe contains a closed set of typed authoring choices, prepared
mesh/material/icon payloads and hashed game dependencies. It carries no complete
replacement game tables, author machine paths, export history or executable code.
All owned identifiers are symbolic until installation. Game-dependent numeric
choices, such as the template and crafting materials, remain pinned dependencies.

Imports reject duplicate/unsafe paths, symlinks, encryption, unknown fields or
versions, malformed types, missing/unreferenced blobs and checksum/size failures.
Limits are 4 MiB of metadata, 256 MiB per resource, 1 GiB total and 4,096 entries;
one installation batch accepts up to 128 packages.

The initial baseline uses only direct, four-digit shipped archive directories
0000 through 0035. Named manager folders such as `dmmgen` and `dmmsa`, other mod
groups and nested archive copies are excluded from authoring inputs. Custom item
IDs already present in shipped tables are refused. Required source
payload hashes must match the author's source. This is conservative version
compatibility, not proof that a user's base archives are an untouched retail copy.
Opaque dependencies on another mod are unsupported. Mounted external archive
folders may use letters, digits, underscores and hyphens. Their actual payloads
are compared, including providers below CDMW in the mount order. Identical files
are harmless. Supported unrelated record changes are preserved in the composed
output; changes to required records or claims on owned identities/assets refuse
installation with the mod, file and record involved.
Unmounted external archive folders do not participate in that check. Authoring
also restores the texture baseline from retained overlay history, so installing
an item with generated textures does not prevent preparing the next package.
Custom dye masks that still refer to a local file are refused; this package version
does not import files from the recipient's computer.

## Compare and compose other mods

In **Mod Management > Independent items**, **Scan installed mods** compares the
installed item set with all mounted external archive providers. **Scan mod
folder...** additionally inspects an extracted, uninstalled mod folder, including
loose game-relative files, `files/` layouts and PAMT/PAZ packages. Scans are read-only.
They report compatible data, shared files that can be merged, record conflicts,
and unsupported inputs. This is an on-demand file-data comparison, not a runtime
plugin analyser or continuous external-manager monitor.

**Merge shared files...** prepares a reviewed rebuild for mounted mods. It uses
the existing verified backup and recovery transaction, preserves independent
item identities and journals, and never edits external archives. The composed
CDMW archive is mounted first. Removing the last CDMW item restores the external
mount order; a foreign archive originally below the shipped game remains below it.
The current underlay is read again during rebuild, so unmounting a foreign mod
does not resurrect its old contribution from recovery history.

**Write merged mod...** writes a separate archive-format package through the
existing Merge exporter. Inputs remain unchanged. Use that package instead of
the source mods and composed CDMW overlay, and retain the identity profile for
saves. Export is not installation and does not transfer CDMW's per-item management
to another manager. Changed sources require a new comparison before publication.

The first supported record boundaries are:

- ItemInfo: the template and transitive referenced item/perk/material/price rows
  stay unchanged; unrelated records and external added IDs can coexist.
- EquipTypeInfo and StatusInfo: complete referenced equipment and stat records
  stay unchanged; unrelated records can coexist.
- StoreInfo and ItemGroupInfo: the existing structured stock/member merger
  combines supported additions and rejects incompatible changes.
- Other dependency tables and localisation/prefab collections: existing records
  stay protected; supported appended records can coexist. Unverified resource
  changes still refuse rather than assuming they are unrelated.

Both halves of a changed table are required. Multiple external tables can be
combined automatically when every shipped row remains byte-identical and all
changes are verified additions. Other different external replacements of
the same file remain ambiguous without their original baselines; the report points
to the existing **Merge** workflow for packages with recorded baselines. Runtime
plugins, unapplied JSON patch instructions, nested packages and unproven texture
registry ownership are reported as unknown, not compatible. Patching the shipped
archives directly still falls under the package's original game-hash checks.
This extends installation/composition without changing the `.cditem` v1 format.

Persistent ownership lives in `.cdmw/independent-items.json`; immutable recovery
packages live beside the existing overlay journals. Reservation checksums are
cross-checked with layer ownership; altered mappings require matching recovery
material. The ledger, cached packages,
overlay inventory, composed archive and mount/texture metadata are published by
the existing overlay mutation transaction. Review includes the exact game folder
and affected files. The game must be closed and the existing backup verification,
stale-source checks and rollback must succeed. A failed/cancelled preparation
writes nothing; publication failure rolls back the transaction.
Ordinary and independent overlay operations pin the initial ownership inventory,
identity ledger (including its absence), mount list and texture registry. Changes
during preparation, review or backup require a new preparation before publication.
The existing overlay rebuild also checks retained packages against their pinned
game dependencies and backs up their matching identity and recovery data.

Export and preparation run in the controller's existing worker lifecycle. A
changed draft invalidates an older plan; a closed page discards pending reviews.
The reviewed apply is serialized on the shared installation lane. The Rust UI
projects and invokes these same controls and callbacks.

## Supported-format matrix

| Dependency | Version 1 handling | Refusal boundary |
| --- | --- | --- |
| ItemInfo, StringInfo and localisation | Typed owned additions; destination keys and names | Existing records changed, collisions or unknown table layouts |
| Current recipes and reward sets | Owned recipes/outputs; template references rebound to the new item | Undecoded connections or missing tools/materials/rewards |
| Legacy enhancement rows | Existing verified transition editor, with reserved keys | Unknown row/reference boundary |
| Embedded perks | Verified game dependency; optional owned zero-price copies | Undecoded stat blocks or missing localisation |
| Shops and groups | Add stock and group membership | Stock replacement or edits to existing reward consumers |
| Imported PAC meshes | Final output checked against each exact template attachment or skin palette at export and installation, without reapplying authoring edits | Undecodable geometry, missing target binding or incompatible skinning |
| PAC XML and DDS | Parsed resource paths and owned textures/icons; composed texture registry | Unknown XML root/reference attributes, unresolved resources or absent registry |
| PAPPT and prefabs | Existing structured editors and relocation | Incomplete or inferred prefab reference layouts |
| Owned effects/emitters/presets | Complete reflection decode, bounded fixed-length reference edits and reserved tokens | Missing dependencies or ambiguous reflection boundaries |
| Collision physics files | Item-owned byte-for-byte copies of the verified Havok 2024.2 convex/compound template layouts | Unknown type dictionaries, malformed boundaries, changed collision data or changed companion mesh |
| Cloth and jiggle accompanying copied collision physics | Preserve every PAC LOD and its skin/cloth data; retain model-property bindings and pin the referenced PBD catalogue/profiles | Changed geometry or simulation bindings, missing or ambiguous profiles; no physics transfer to a different mesh |
| Equipment visibility suffixes | Independent variants retain the template's existing matching suffix rules | Changes requiring shared visibility descriptors remain unsupported |
| Global rendering edits | Unsupported | Any required shared rendering change outside the additive whitelist |

The matrix constrains only experimental package export/install. Existing export
support is unchanged. Material and equipment experiments retain their existing
game-validation limits even when their package graph is structurally supported.

### Copying template physics

Owned physics is deliberately limited to unchanged template geometry. The package
audit checks the exact source HKX and PAC bytes, including all mesh LODs, weights
and cloth lanes. It permits render-material edits such as emission while requiring
unchanged model and cloth bindings. Referenced PBD configuration and profile files
remain hashed game dependencies; their contents are not regenerated or clamped to
preview values. Export and installation perform the same checks.

The HKX recognizer accepts only the two witnessed 2024.2 convex/compound collision
type dictionaries. It checks container and ITEM boundaries and does not rewrite
Havok objects or assume arbitrary binary references can be relocated. These files
hold collision shapes; cloth motion also requires the preserved mesh data and
PBD bindings. Copying an HKX alone is insufficient.

An imported replacement with different vertices must leave **Template cloth /
physics** off until a compatible transfer is implemented and verified. Its rigid
or skinned attachment is a separate check and is not evidence of cloth physics.
Source checks cover copying and composition; armor movement, collision behavior,
coexistence and save/reload still require controlled in-game comparison before
advertising community support for that equipment.

## Evidence and remaining checks

`tests/test_independent_items.py` constructs separate authoring environments with
deliberately identical source IDs and names. It covers both template installation
orders, imported model/icon paths, owned effects, priced perks, recipes and
localisation; repeated imports, updates, restart-style re-reading, removal and
reinstallation, and transfer through an identity profile. Corruption, incomplete
dependencies, incompatible source hashes, collisions, allocation exhaustion,
stale mappings and rollback/cancellation have focused fixture checks.

`tests/test_independent_item_physics.py` adds malformed/unknown collision refusal,
mesh and cloth binding checks, pinned PBD dependencies, changed recipient profile
refusal, and two independently authored physics copies resolved in both orders.
It also checks that variant name collision retries retain inherited visibility
rules without modifying the shared descriptor. Synthetic dictionaries in tests
exercise the boundary checks; they are not additional production format witnesses.

`tests/test_independent_item_regressions.py` covers overlapping overlay operations,
ledger changes before publication, authoring after a generated-icon installation,
invalid imported attachment bindings with valid package hashes, and unmounted
external archives during installation and rebuild.

`tests/test_independent_items_ui.py` and the Output test in
`tests/test_new_item_rust_ui.py` drive the real Qt controls through the Rust input
bridge without a visible renderer. They test preservation of authoring choices,
package export, reviewed installation/removal and shutdown with pending work.

These tests are source and synthetic-package evidence. Separate controlled game
results for selected swords, effects and save/reload are recorded in the
[Virtual loader validation notes](VIRTUAL_LOADER.md#evidence-gates-and-validation);
they do not certify every supported authoring configuration.
Before claiming a usable game configuration, test the actual executable version
and inputs with a disposable save: acquire and equip both colliding-source items,
check models/icons/localisation/perks/effects and crafting, save/reload, update one,
save/reload again, and test removal/reinstallation and profile transfer. Keep the
source, package and game evidence separate.

## Runtime registration research

The current authoring and overlay code resolves known shared table paths and
rebuilds those tables. Source inspection of the separate runtime Workshop route
likewise finds export, not a verified API for registering new inventory item
definitions. Its inventory type identifiers must not be equated with these table
keys. These observations do not prove that an engine-level registration route is
impossible.

Independent item installation itself does not enable a native loader or modify
the executable. The separate [Virtual loader prototype](VIRTUAL_LOADER.md) reuses
these packages and identity reservations for private profile preparation and
reviewed experimental launches with verified save backups. Exact executable,
bootstrap and startup guards remain mandatory. Separate definition-file discovery and native registration
are research tracks, outside the existing installation path.
