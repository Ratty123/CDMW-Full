# Independent item packages (Experimental)

Choose **Output > Independent item package (Experimental)**, build the plan and
select **Write item package**. Share the resulting `.cditem` file. Recipients use
**Mod Management > Independent items > Import packages** to inspect and install
one or more packages. Existing folder exports and game overlays remain available.

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
their byte lengths. The original shared table records are preserved, apart from
supported additive shop stock and item-group membership.

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

The initial baseline uses the project's shipped archive boundary (directories
below 0036). Custom item IDs already present there are refused. Required source
payload hashes must match the author's source. This is conservative version
compatibility, not proof that a user's base archives are an untouched retail copy.
Opaque dependencies on another mod are unsupported. An external mounted archive
replacing a required path blocks preparation, regardless of priority.
Custom dye masks that still refer to a local file are refused; this package version
does not import files from the recipient's computer.

Persistent ownership lives in `.cdmw/independent-items.json`; immutable recovery
packages live beside the existing overlay journals. Reservation checksums are
cross-checked with layer ownership; altered mappings require matching recovery
material. The ledger, cached packages,
overlay inventory, composed archive and mount/texture metadata are published by
the existing overlay mutation transaction. Review includes the exact game folder
and affected files. The game must be closed and the existing backup verification,
stale-source checks and rollback must succeed. A failed/cancelled preparation
writes nothing; publication failure rolls back the transaction.
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
| Imported PAC meshes | Prepared geometry through existing model/variant planning | Undecodable geometry or incompatible target binding |
| PAC XML and DDS | Parsed resource paths and owned textures/icons; composed texture registry | Unknown XML root/reference attributes, unresolved resources or absent registry |
| PAPPT and prefabs | Existing structured editors and relocation | Incomplete or inferred prefab reference layouts |
| Owned effects/emitters/presets | Complete reflection decode, bounded fixed-length reference edits and reserved tokens | Missing dependencies or ambiguous reflection boundaries |
| Physics files | Unchanged game dependencies only | Cloned HKX files are not verified for this format |
| Global rendering edits | Unsupported | Any required shared rendering change outside the additive whitelist |

The matrix constrains only experimental package export/install. Existing export
support is unchanged. Material and equipment experiments retain their existing
game-validation limits even when their package graph is structurally supported.

## Evidence and remaining checks

`tests/test_independent_items.py` constructs separate authoring environments with
deliberately identical source IDs and names. It covers both template installation
orders, imported model/icon paths, owned effects, priced perks, recipes and
localisation; repeated imports, updates, restart-style re-reading, removal and
reinstallation, and transfer through an identity profile. Corruption, incomplete
dependencies, incompatible source hashes, collisions, allocation exhaustion,
stale mappings and rollback/cancellation have focused fixture checks.

`tests/test_independent_items_ui.py` and the Output test in
`tests/test_new_item_rust_ui.py` drive the real Qt controls through the Rust input
bridge without a visible renderer. They test preservation of authoring choices,
package export, reviewed installation/removal and shutdown with pending work.

These are source and synthetic-package results. There is no packaged-release,
visible-game, acquisition/equipment/crafting or save/reload certification yet.
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

No native loader or executable modification is enabled by this feature. Separate
definition-file discovery, native registration lifetime, asset loading and save
identity still require an isolated executable-specific prototype and controlled
game evidence. That research remains outside the production installation path.
