# Independent item packages (Experimental)

Choose **Output > Independent item package (Experimental) · .cditem**, build the plan and
select **Write item package**. Share the resulting `.cditem` file. Recipients add it
to **Mod Management > Mods**, choose **Apply changes**, then **Launch game** for
experimental virtual loading. Physical installation remains available through
**Advanced > Item identities > Install into game archives**. Existing folder exports and
game overlays remain available.

The advanced item identity list sorts by **Item**, **Game ID** or **Status** when you click a column
heading; clicking again reverses the order. Game IDs sort numerically. Drag the
column edges to change widths. Refresh preserves the sort, widths and selected
package. The default layout keeps IDs and status readable as the pane resizes.

**Removed / reserved** entries are saved ID mappings, not installed mods. Select one
and choose **Delete saved identity…** to permanently free its IDs after review and a
verified backup. Active or disabled items must be removed first; for virtual items,
remove them from **Mods** and choose **Apply changes**. Old saves may no longer
recognize a forgotten item, and another item can reuse its IDs. Reinstallation may
allocate new IDs. Cleanup preserves game archives, saves and payload recovery history;
restore the matching backup to recover deleted mappings. A remaining installed item
whose compilation references the mapping must be rebuilt or removed first.

CDMW composes the game's shared files during installation. Separate `.cditem`
files are portable authoring packages, not standalone archives the game discovers.
No manual mod merge is required for compatible packages installed through CDMW.

Current equipment packages can include supported template or imported models and
their item-owned materials, textures, icons and validated accompanying resources.
The item authoring UI writes v1. V2 admits the same legacy item, existing ItemInfo
field and package-link modules, and standalone `texture.replace@1` packages.
Texture tools create and update packages for supported existing DDS targets without
an equipment recipe or numeric item allocation. See
[`INDEPENDENT_TEXTURES.md`](../../services/INDEPENDENT_TEXTURES.md) for the exact
source, descriptor, resource and registry limits. General material replacement,
character, body, hair and outfit adapters remain unimplemented. Armor items must
still satisfy the equipment matrix. Ordinary mod-folder admission does not add a
new `.cditem` module.

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
and included in dependency validation. Bare inline-emitter labels are not external
file dependencies; explicit `emitter/...` names and inherited `.paem` types still
require verified files. For v1 and the v2 legacy module, original shared table records are
preserved, apart from supported additive shop stock and item-group membership.

Updates retain prior identities and atomically replace the selected item's
contribution. Importing identical content is a no-op when the installed compiler
record matches the current compiler. Removal deletes only that
contribution from composed output. All issued identities and asset paths remain
reserved, including retired auxiliary records. Normal CDMW overlay installation
also refuses to take an independent package's reserved item keys. External tools
cannot be forced to honour these reservations; detected overlaps are refused.

**Advanced > Item identities > Rebuild selected item…** regenerates an installed
item from its retained package with the current compiler. It preserves the UUID,
item IDs and asset reservations, then uses the normal change review and verified
backup flow. Cancelled preparation leaves the installation unchanged. Publication
failures follow the verified per-target recovery boundary described below;
unknown target contents retain recovery material and refuse automatic overwrite.
Missing or changed recovery packages are refused. An older or unrecorded
compiler requires this explicit rebuild before an identical-package import can
be treated as already installed.

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

The v1 vocabulary is fixed in `cdmw/domain/new_item/independent_wire_v1.py`.
Internal class names, newly added fields and enum members do not extend it.
The codec explicitly translates that vocabulary to current authoring models;
internal field renames or new defaults require a reviewed adapter. Values that
v1 cannot represent refuse instead of silently losing behavior. Reading and
rewriting a package preserve its UUID and canonical content digest. Synthetic
fixtures captured from revision `d08bd77343e1` cover the known vocabulary; earlier
shipped schema variants still need historical examples before claiming support.

Physical ownership layers record the compiler revision, adapter revisions and
frozen wire-schema digest independently of package content and identity bindings.
Planner semantic changes require a compiler revision change; output or admission
changes in a named adapter require its revision change. Existing layers without
this record remain readable for recovery and removal, but cannot claim current
compilation. The compiler record itself does not change the v1 package schema.

## Version 2 admission and compilation identity

Readers also accept the version 2 envelope. Item authoring still exports v1;
Texture tools write v2 existing-texture packages. The developer helper
`independent_mod_package.migrate_v1()` explicitly wraps a verified v1 package for
developers testing v2. It preserves the package UUID, original canonical v1 digest
and `item` symbol. It does not renumber existing installations. A v1-only editor
refuses to overwrite v2 because doing so could discard modules or provenance.

V2 keeps ZIP, `item.json` and addressed `assets/` members. Its exact root fields are
`format`, `version`, `identity`, `title`, `release`, `requires`, `modules`,
`dependencies`, `blobs`, `provenance` and `metadata`. `format` remains
`cdmw_independent_item`; `version` is integer 2. `requires` maps capability names
to integer schema versions. Each module has a stable `id`, `type`, integer
`version`, `required` flag and `data`. These names are independent of Python types.

**`item.legacy` version 1** uses ID `item`, `required: true` and a frozen v1 recipe
as its data. It uses the existing physical and virtual compilation paths. Exact
game resource hashes, allocation ranges and equipment limitations still apply.
V2 also admits **`item.fields` version 1** for the narrowly defined existing-record
operations and **`package.links` version 1** for the installation dependency graph
below. **`texture.replace` version 1** owns existing DDS replacements without a
legacy recipe and contributes exact final-byte requirements to both deployment
routes and semantic export. Existing v1 readers explicitly reject the version 2
boundary.

Unknown required features, module types and versions refuse before allocation.
Optional behavior also refuses until a supported explicit alternative exists;
it cannot be counted as executed. Bounded `metadata` is preserved uninterpreted
and grants no behavior or capabilities. Missing or unreferenced resources and
invalid migration provenance refuse. Runtime, quest, audio and other domain
modules remain unimplemented; naming a module does not establish its consumer.

`CapabilityResult` reports support, constraints and scoped `EvidenceClaim` entries.
Adapter and synthetic test evidence do not imply native, packaged, game or save
evidence. A failed capability result is available with its refusal exception.

Package UUID, canonical manifest digest and exact ZIP artifact digest are separate
identities. ZIP generation fixes timestamps and host attributes for reproducible
artifacts. File reads hash before and after parsing to catch changed content even
when length and modification time are unchanged. Optional metadata is included
in canonical content identity; no cryptographic authenticity claim is made.
ZIP members are decoded and encoded in 1 MiB chunks with cancellation checks,
including while validating an existing export and immediately before replacing
it. ZIP CRC and declared resource lengths are checked. File exports write to a
sibling temporary file, then recheck the previous artifact before replacement.
Cancellation observed by the final guard, write failure or a changed destination
preserves the existing file. Replacement itself is noncancellable: once it succeeds,
a late cancellation request cannot hide the completed export or its identity.
The Studio consumes typed worker outcomes for completion, committed publication,
cancellation and failure. Publishing callers explicitly opt into committed-result
delivery; their services must return only after success and raise `RunCancelled`
before commit. A cancellation request cannot replace a real error. Cancelled
read-only preparation still disposes its unused result, and shutdown suppresses
late UI callbacks. Legacy worker result/error signals remain available for other
callers; consumers subscribe to either those signals or the typed outcome.
Compression boundaries may change exact artifact bytes while preserving the
canonical content and UUID; recorded artifact digests always describe actual bytes.
File export avoids holding an additional complete compressed ZIP in memory.
Imports still retain decoded member contents for validation and compilation,
and `package_bytes()` deliberately returns an in-memory ZIP. The full pipeline
does not use constant memory.
Within one preparation, packages can share byte-identical validated resource
buffers. Each package is still validated independently and keeps its own UUID,
resource mapping and installed paths. Logical batch limits count every package's
resources, including shared bytes. This sharing lasts only for that preparation.

Physical contributions and complete virtual profiles carry a checksummed
compilation record. It links compiler and adapter revisions, package content and
source/retained artifact digests, negotiated features and module schemas, exact
source hashes, the allocation ledger, conflict policy, composition order, runtime
protocol, provider inputs and generated output hashes. Physical records describe
individual contributions; virtual records describe the complete prepared view.
Unknown/malformed records refuse, and missing current records require rebuilding.
These records are provenance, not proof that the game accepts the result.

Physical inventory `cdmw_owned_overlays_v2` stores common allocation, ordering and
resolved-link inputs once in `compilation_contexts`, keyed by their canonical
SHA-256. Each contribution retains its own package, source, compiler and output
evidence in a `cdmw_compilation_reference_v1` record. Readers verify the context
digest and reconstruct the original logical compilation to check its identity.
Missing contexts, altered content, ambiguous duplicate JSON keys and mismatched
ownership bindings refuse.

Legacy inline inventories remain readable. Their stored records are converted
only as part of a reviewed overlay publication, with the existing backup and
rollback flow. This preserves their original compiler stamps and logical
compilation identities; old results still require an explicit rebuild when their
compiler differs. Older CDMW versions cannot read the new physical inventory.
The `.cditem` package, identity-profile and virtual-profile formats are unchanged.
Contexts needed by retained contributions are kept, and byte-identical contexts
can be reused across rebuilds without discarding history.

## Package dependencies and exported objects

The required `package.links@1` capability and one matching required module add
declared installation dependencies to a v2 package. An implemented content module
must also be present. Its data has exactly three arrays:

```json
{
  "packages": [{"identity":"<provider UUID hex>","release":"v1","content":"<SHA-256>"}],
  "exports": [{"symbol":"items/travel-sword","kind":"item","module":"item","object":"item","lifetime":"installation"}],
  "references": [{"id":"uses-sword","package":"<provider UUID hex>","symbol":"item","kind":"item","ownership":"borrowed","lifetime":"installation"}]
}
```

The example illustrates the field grammar; replace placeholders with actual
provider identities and content hashes. Exports belong to the declaring package;
references name another package explicitly. V1 providers use release `v1`; v2
providers use their manifest release. Pins require both that exact release and
canonical content digest, with no version-range or load-order substitution.

Every v1 package and v2 legacy item already exports `item`. Explicit exports may
give that same owned legacy object additional stable symbols; they cannot claim
stock rows, unknown kinds or another package's ownership. The resolved reference
uses the provider's retained ItemInfo ID. Duplicate providers/symbols/references,
missing exports, unpinned references, cycles, unsupported ownership/lifetimes and
changed releases refuse before publication. Dependencies are checked before game
allocation, again during composition, and when enabling, rebuilding or removing
physical contributions. Updating a pinned provider requires updating its active
consumers in the same batch. Disable/remove consumers first when removing it.

References currently require the same deployment: one physical installation set
or the selected packages of one virtual profile. They express installation
admission and lifetime requirements; they do not patch recipe ingredients,
relocate game references, create runtime handles or establish save compatibility.
Those consumers require separate verified adapters. Active graphs are limited to
4,096 packages and 4,096 total exports, pins and references. Provider reads retain
only bounded declarations while graph resolution runs.

Graphs with links use `cdmw_compilation_v2`; other compilation records retain
their v1 grammar. The lock records actual provider content, reference closure,
dependency order and retained item IDs. Old records remain readable, while the
compiler revision requires rebuilding before an old compilation is treated as
current. `tests/test_independent_package_links.py` covers both deployment orders,
v1 providers, aliases, coordinated updates, removal/disable/reinstall, hostile
inputs, stale retained packages, subprocess transport and publication rollback.

## Existing ItemInfo field operations

An `item.fields` module contains `data: {"operations": [...]}`. Developers can use
`independent_item_operations.from_iteminfo_operations()` with a verified shipped
snapshot to author it, then the existing package writer and import/Apply flows.
There is no separate field-authoring UI yet. It can be a standalone package or
accompany one legacy module, provided all whole-record requirements remain valid.

Every operation has exactly `id`, `kind: "field.assign"`, `target`, `field`,
`value_type`, `expect`, `value`, `precondition_base: "source"` and `source_row`.
`source_row` is the SHA-256 of the pristine stock row; complete table-body and
header hashes remain mandatory package dependencies. The target contains
`table: "ItemInfo"`, a positive u32 `key`, and an explicit adapter:
`cd.iteminfo.prefix-stat-11-v1` or `cd.iteminfo.prefix-stat-12-v1`. Stat operations
require the selected marker layout; stack operations use their shared prefix.
Only the verified u32-key/u16-count table directory is admitted.

The supported field selectors and value types are:

| Field selector | Type and range | Admission |
| --- | --- | --- |
| `{"name":"max_stack_count"}` | `u32`, 1–4,294,967,295 | Recognized prefix with unchanged identity and layout |
| `{"name":"stat_value","enchant_level":0,"status_key":1000002}` | `i32`, −2,147,483,648–2,147,483,647 | Exactly one existing stat at the specified level, in the selected marker layout |

No operation accepts arbitrary offsets, new stats, structure edits or executable
code. There are at most 4,096 assignments across an active composition and 64 KiB
per target row. Unknown layouts, duplicate operation IDs, ambiguous stats, wrong
expectations, booleans masquerading as integers and overflow refuse.

The adapter derives source reads, field writes and final invariants. Disjoint
field assignments commute; equal assignments coalesce; opposing assignments name
both owners and the field. Preconditions refer to pristine source, never the
output of whichever mod ran first. All unassigned bytes, row lengths and identities
are preserved and assigned values are parsed back. Complete table pairs are
published even when the directory bytes are unchanged.

Required v1/legacy records are collected across the complete active profile before
field composition. A later v2 module cannot bypass a v1 requirement, and installing
that v1 package later also refuses the conflict. An assignment whose requested
value equals the verified source value can coexist with a whole-record requirement;
it retains its ownership and still conflicts with an opposing assignment.
Untyped changes to the same
target row remain incompatible. Removal recomposes from source plus the remaining
active operations; it does not subtract bytes or replay inverse edits. Rebuilding
the installed overlay set retains each field operation against pristine rows,
including disabled contributions, so re-enabling or removing one preserves the
others. These rules
are covered by synthetic physical, virtual, subprocess and transaction tests;
gameplay and save behavior still need witnesses.

Field-only packages allocate no dummy items or asset names. Their Game ID column
is blank, while their UUID and installation history remain available for rebuild,
removal and profile transfer. Installing the first such package upgrades the
identity ledger to `cdmw_mod_identity_profile_v2` in the same reviewed transaction.
Existing and retired numeric bindings remain unchanged. V1-only readers refuse
this ledger explicitly; failed publication restores its previous format and data.
The v1 ledger remains in use for installations containing only item reservations.

## Resource validation

Imports reject duplicate/unsafe paths, symlinks, encryption, unknown fields or
versions, malformed types, missing/unreferenced blobs and checksum/size failures.
Reader and writer limits are 4 MiB of metadata, 256 MiB per resource, 1 GiB of
expanded metadata and resources combined, and 4,096 entries. Exports exceeding
these limits are refused before replacement. One installation batch accepts up
to 128 packages.

Owned DDS textures must contain a complete supported single-surface, 2D block-
compressed payload and every declared mip. Registration compares the full DX10
extension, including format and alpha semantics, and computes raw mip sizes from
the payload layout. Arrays, cubes, volumes, unknown codecs and unexplained trailing
bytes are refused. This validation also applies when the source has no texture
registry; it does not establish in-game support for every accepted DDS codec.

The icon registry is flat UTF-8 XML with multiple self-closing `Texture` elements.
Its writer and merge validator share the same grammar. The BOM, comments and
unknown surrounding content are retained; conflicting edits to that content
refuse. Duplicate names within one registry refuse case-insensitively. Separate
mods claiming the same icon must agree on its entry bytes.

The initial baseline uses only direct, four-digit shipped archive directories
0000 through 0035. Named manager folders such as `dmmgen` and `dmmsa`, other mod
groups and nested archive copies are excluded from authoring inputs. Custom item
IDs already present in shipped tables are refused. Required source
payload hashes must match the author's source. This is conservative version
compatibility, not proof that a user's base archives are an untouched retail copy.
Ordinary New Item listings, stock snapshots, selected and mounted mod-base
snapshots, independent composition and generic Merge retain the digest of the
exact PAMT bytes parsed to select their archive resources. The original witnesses
survive derived snapshots, per-package views, scanning, merged export and both
publication routes.

An unwitnessed entry catalogue must match a fresh parse of the current index at
every supplied path, coordinate and flag. A resident catalogue must also match
the parsed record inventory, including duplicate counts and index owners, before
its cached entries or tables are used. Reusing parsed resident tables rechecks
the retained original index digests. A newly computed hash alone cannot justify
coordinates or tables cached from different bytes. Later source fingerprints
must agree with the parsed bytes, even when a replacement preserves file size
and all recorded timestamps. Payload checks remain in place. Other processes can
still write between validation checkpoints; this does not establish
cross-process snapshot isolation.

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

In **Mod Management > Advanced > Item identities**, **Scan installed mods** compares the
installed item set with all mounted external archive providers. **Scan mod
folder...** additionally inspects an extracted, uninstalled mod folder, including
loose game-relative files, `files/` layouts and PAMT/PAZ packages. Scans are read-only.
They report compatible data, shared files that can be merged, record conflicts,
and unsupported inputs. This is an on-demand file-data comparison, not a runtime
plugin analyser or continuous external-manager monitor.

Recognized loose `meta/0.papgt` supplies archive discovery and is excluded from
game-resource payloads. Its parsed bytes retain an original digest. A valid
`meta/0.pathc` that exactly matches the current game's texture registry is accepted
as unchanged metadata, with both inputs verified. A changed incoming registry
still requires recorded texture ownership: use **Merge** with the original CDMW
export before selecting that folder. Unknown metadata and malformed mount indexes
refuse before composition. This shared folder admission covers scanning,
prospective physical resolution and virtual profile preparation, including
archive exports produced by CDMW.

Scanning validates the same retained package graph and composes the same typed
contributions as installation, rebuild and virtual preparation. Disjoint field
edits to one ItemInfo row can coexist. Explicit requirements to keep a source
value are retained even when their output bytes equal the source; an external
change to that required row produces a conflict. Export checks those same
contracts before deciding whether its output can preserve them. Diagnostics may
stop at the first active-graph conflict, so resolve it and scan again.

**Rebuild installed shared files…** prepares a reviewed rebuild for mounted mods. It uses
the existing verified backup and recovery transaction, preserves independent
item identities and journals, and never edits external archives. The composed
CDMW archive is mounted first. Removing the last CDMW item restores the external
mount order; a foreign archive originally below the shipped game remains below it.
The current underlay is read again during rebuild, so unmounting a foreign mod
does not resurrect its old contribution from recovery history.

**Export installed items…** can write a separate archive-format package for active
legacy items, including v1 packages and v2 legacy modules, through the existing
Merge exporter. Inputs remain unchanged. Use that package instead of the source
mods and composed CDMW overlay, and retain the identity profile for saves. Export
is not installation and does not transfer CDMW's per-item management to another
manager. Changed sources require a new comparison before publication.

### Semantic export and reimport

When active packages declare `item.fields`, `texture.replace` or `package.links`,
**Export installed items…** writes `cdmw-semantic.cditem` inside the chosen folder. Add that file to
**Mods** or **Virtual loader**, or use the reviewed physical **Install into game
archives** flow. **Merge mods** also combines supported semantic export folders.
The opaque wrapper retains every original package and exact contributor binding,
including source-equal field and texture requirements, provider pins and exported references.
CDMW validates the payload and source witnesses, recompiles the original recipes,
then composes them with the other active packages. Equal requirements retain both
owners; compatible fields in the same row and disjoint texture targets combine. Contradictory requirements,
occupied or different numeric bindings, changed known game identities and changed
archive indexes refuse. No game-reference relocation is implied.

Retained contributors use ordinary package update, enable/disable and removal
services. A virtual wrapper is one selection entry; to select a subset, use the
retained original packages as the next profile selection. Required providers must
remain selected. Retired identities are never reassigned. A disabled field owner
does not block the unchanged legacy-only export route.

Semantic exports cannot be installed by a legacy byte-only manager. Mixed foreign
folders or untyped ownership layers remain unsupported for semantic export. A
manually extracted legacy folder has only the guarantees supported by its bytes;
checksums do not prevent stripping or authenticate the author. The exact negotiated
`export.semantic@1` schema is in [SEMANTIC_EXPORT.md](../../core/SEMANTIC_EXPORT.md).

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

### Physical publication and recovery

Persistent ownership lives in `.cdmw/independent-items.json`; immutable recovery
packages live beside the existing overlay journals. Reservation checksums are
cross-checked with layer ownership; altered mappings require matching recovery
material. The ledger, cached packages,
overlay inventory, composed archive and mount/texture metadata are published by
the existing overlay mutation transaction. Review includes the exact game folder
and affected files. The game must be closed and the existing backup verification,
stale-source checks and recovery must succeed. A failed/cancelled preparation
writes nothing.

Physical overlay publication records each target's original digest and attempted
write or deletion before invoking the mutating call, including calls that replace
or unlink a file and then raise. Automatic rollback restores only attempted
targets whose current bytes match a recorded transaction result. Targets already
equal to their originals need no write. Unknown contents refuse automatic
recovery and preserve the diagnostic journal and verified recovery copies.
Unattempted targets and foreign files added to a directory remain untouched.

The original backup manifest and copies stay immutable. Recovery uses a separate
manifest scoped to verified changed targets, checks restore/delete readback, and
removes only known created artifacts and empty directories created by that
transaction. Cancellation before the first attempted mutation skips target
restoration and cleanup. This boundary applies to managed overlay changes,
retirement, legacy installation, migration and removal. The per-target journal
currently provides diagnostics and manual recovery evidence; it does not add a
restart-time automatic recovery command. Cooperating CDMW writers share the
installation lane, but an arbitrary external writer can still race a filesystem
check and operation.

Large rebuilds release completed composition data before collecting the original
destination bytes. Backup, stale-file, staged-output and rollback verification
compare complete files through a reusable buffer of at most 1 MiB. Original bytes
are still retained for review and recovery; this does not bound total archive memory.
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

This matrix describes v1 and the v2 legacy module. The explicit `item.fields`
exceptions are defined in [Existing ItemInfo field operations](#existing-iteminfo-field-operations).

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

The long-term goal is to represent every mod category through typed adapters and
verified consumers. The current envelope does not make unknown formats usable by
the game or make contradictory requirements compatible in one game context.
Unknown required behavior refuses; new domains need their own parsing, reference,
serialization, activation, teardown and persistence evidence.

Save/profile lineage has a data-only policy and read-only capture/comparison
tools. Trusted producer lineage, a production save-commit verifier, migration
admission and the required game evidence remain pending. Exact backup hashes,
stable IDs and installation dependency checks do not identify the providers
needed by arbitrary saves. Failed or unknown save attempts retain their observed
byte changes and reported outcome without claiming a committed save. The
[save admission boundaries](VIRTUAL_LOADER.md#save-lineage-and-migration-admission)
describe the current policy, missing origin evidence and absent-provider
experiment. Game-update admission likewise retains exact source hashes until a
record-level adapter has independent layout and semantic witnesses. No general
runtime command API or unrestricted native-plugin compatibility guarantee is
supplied by `.cditem`.

### Capacity and retained history

The current ceilings are admission budgets, not a promise that every combination
at the ceiling fits memory or every retained installation:

| Resource | Current bound |
| --- | --- |
| Selected packages | 128 per batch/profile |
| Expanded selected package content | 1 GiB total, including manifests |
| One resource blob | 256 MiB |
| Package manifest / identity ledger | 4 MiB each |
| Members in one `.cditem` ZIP | 4,096 including `item.json` |
| Physical overlay inventory | 4 MiB, including retained history and compiler records |
| Field operations / target row | 4,096 active assignments / 64 KiB |
| Declared package graph | 4,096 providers and 4,096 combined exports, pins and references |
| Item allocation namespace | Existing range 1,990,000–1,999,999; occupied and retired IDs stay reserved |

Both graph limits apply together. Stem capacity also depends on the template's
fixed-width naming family and existing reservations. No integer ranges, stem
lengths or unknown-format acceptance are widened to bypass exhaustion.

Physical inventory output uses compact JSON. A metadata lower bound is checked
before journal decoding, then the projected final size is checked before payload
compression and archive construction. Exact serialization is still checked before
returning a preparation and again before backup/publication. Refusal reports the
required minimum and byte limit; a refused rebuild leaves the prior installation
readable. Package count alone cannot predict capacity: distinct shared contexts
and each contribution's own evidence still consume space. Retired layers, journals and
bindings still accumulate. Virtual generations and save/recovery backups are
also retained; there is no automatic history deletion or shared on-disk blob store.
Storage growth and reusable content should be measured before changing retention
or sharing semantics.

For reproducible source measurements using owned fixtures only:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_independent_items.py --counts 1 8 32 128 --generations 3 --output workspace/reports/cditem-scale.json
.\.venv\Scripts\python.exe scripts/benchmark_independent_items.py --counts 1 8 32 --kinds icon --generations 3 --output workspace/reports/cditem-scale-icons.json
.\.venv\Scripts\python.exe scripts/benchmark_independent_items.py --counts 1 8 --kinds texture-shared texture-distinct --generations 2 --output workspace/reports/cditem-texture-scale.json
```

Choose a new report path for each run. The harness accepts no game directory,
creates its own temporary fixtures, and measures each case in a separate child
process. It records preparation/publication time, peak process resident memory,
expanded/ZIP inputs, retained storage, final inventory readability, unchanged
stock archive bytes and cancellation at a specific composition checkpoint.
Icon cases use complete 256×256 BC3 data matching the fixture's source registry.
Imported-texture cases use complete 4096×4096 BC3 data and a small synthetic mesh,
with identical or distinct pixels across packages; these cases accept at most
eight packages. The report includes compiled file hashes for before/after checks.
Peak memory includes fixture setup, which is also recorded separately. Authoring
payloads and completed preparations are released before subsequent jobs. The
owned backup fixture uses bounded disk copies followed by production verification;
it does not retain the general test helper's extra assertion snapshots. The full
backup service and UI are outside this measurement. Storage
measurements identify repeated full-file content by size and SHA-256; those totals
describe logical file bytes, not filesystem allocation or permission to delete
recovery data. Neither storage measurement nor memory sharing changes retention.
The results are machine-local evidence, not real-game proof, a 1 GiB memory test,
a large-mesh benchmark or a worst-case cancellation bound. Keep reports outside
version control.

For isolated package import, file export and update measurements:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_independent_package_io.py --mib 16 128 --output workspace/reports/cditem-package-io.json
```

This harness uses deterministic, incompressible opaque resources in both v1 and
v2 containers. Each case runs in a fresh process and verifies the resulting
identity and resource bytes. Peak memory includes fixture setup; elapsed time
covers the requested operation, and write readback runs after memory measurement.
The payload is not a valid game icon or model, so these results establish codec
behavior only. Full-pipeline texture measurements use the preceding harness;
large-mesh and maximum-budget behavior, shared on-disk blob storage and safe
history collection remain separate work.

### Focused contracts

`tests/test_independent_items.py` constructs separate authoring environments with
deliberately identical source IDs and names. It covers both template installation
orders, imported model/icon paths, owned effects, priced perks, recipes and
localisation; repeated imports, updates, restart-style re-reading, removal and
reinstallation, and transfer through an identity profile. Corruption, incomplete
dependencies, incompatible source hashes, collisions, allocation exhaustion,
stale mappings and rollback/cancellation have focused fixture checks.

`tests/test_independent_item_resource_sharing.py` checks preparation-local memory
sharing in v1 and mixed v1/v2 batches. Equal payloads retain separate ownership,
updates and removal through both deployment routes. Each later package still
passes checksum validation, and shared content does not enlarge the batch budget.

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

Physical publication rechecks consumed archive payloads and the content of source
indexes and loose files before and after backup. Equal sizes and timestamps do
not make changed dependencies valid. This checks the consumed source graph;
it does not scan every byte in an unrelated PAZ archive. Source drift refuses
before writes, preserving external changes; cancellation uses the normal recovery
path. Synthetic cases are in `tests/test_independent_item_source_guards.py`.

`tests/test_independent_item_index_witness.py` and
`tests/test_cditem_index_consumers.py` cover changed PAMT mappings with identical
recorded stamps, ordinary/resident snapshot and worker consumers, original witness
retention through mod bases and Merge, and a single resident-row verification
scan across multiple indexes.

`tests/test_independent_folder_metadata.py` exercises real exported folders through
scan, physical resolution and virtual composition, including unchanged PATHC and
changed original metadata digests. `tests/test_independent_export_requirements.py`
and `tests/test_independent_item_semantic_routes.py` exercise actual semantic export,
disk readback, reimport, update, disablement, removal and reinstallation.
`tests/test_semantic_export_contract.py`, `tests/test_semantic_export_composition.py`
and `tests/test_semantic_merge_admission.py` cover malformed or contradictory
artifacts, logical resource budgets, unchanged-stamp source changes, exact worker
witnesses and atomic publication. `tests/test_semantic_export_ui.py` drives the
queued exporter and reviewed importer with owned fixtures.

`tests/test_overlay_target_recovery.py` checks per-target rollback after
replace/unlink errors, foreign changes to attempted and unattempted targets,
immutable backup evidence and verified cleanup. Virtual publication outcomes and
save-attempt evidence have separate focused contracts in the
[Virtual loader notes](VIRTUAL_LOADER.md#evidence-gates-and-validation).

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

Physical independent item installation does not enable a native loader or modify
the executable. [Virtual loading](VIRTUAL_LOADER.md) reuses
these packages and identity reservations for private profile preparation and
reviewed experimental launches with verified save backups. Exact executable,
bootstrap and startup guards remain mandatory. Separate definition-file discovery and native registration
are research tracks, outside the existing installation path.
