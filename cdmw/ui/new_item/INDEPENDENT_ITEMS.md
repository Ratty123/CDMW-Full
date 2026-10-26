# Independent item packages (Experimental)

Choose **Output > Independent item package (Experimental) · .cditem**, build the plan and
select **Write item package**. Share the resulting `.cditem` file. Recipients add it
to **Mod Management > Mods**, choose **Apply changes**, then **Launch game** for
experimental virtual loading. Physical installation remains available through
**Advanced > Item identities > Install into game archives**. Existing folder exports and
game overlays remain available.

## Optional DMM V3 export

In **Mod Management > Shared files**, scan archive-installed independent items,
tick **DMM V3 field JSON (experimental)**, then choose **Export installed items…**.
The option starts off. Existing exports and Create New Item's manager defaults
keep their previous formats. **Merge mods** offers the same opt-in when combining
retained semantic exports.

This route writes `mod.field.json`, `modinfo.json`, instructions and
`cdmw-source/cdmw-semantic.cditem`. It preserves the original contributor UUIDs,
content, assigned item/refinement/reward IDs, reservations and source witnesses.
Select that included `.cditem` file for CDMW import or re-export; the outer DMM
folder cannot be used as an ordinary loose mod or New Item base. Keep the identity
profile with saves. Export prepares a separate folder and does not install or
remove anything.

Supported inputs reuse existing models and icons. Supported ItemInfo changes are
the cloned identity and text, stack count, tier/level/durability, stats and prices,
sockets, up to four equipment passive skills, and decoded item settings. Refinement
clones include both reward lists and the actual item-result payload. All available
item-language tables are exported with their exact text, composite keys and
categories. Item-group additions use union; shop additions append stock while
retaining existing positions. Replacements, deletions, unknown fields, custom
resources, stock field-operation modules, texture modules, package links and mixed
foreign contributions refuse. No unsupported part is silently omitted.

The normal compiler, dependency and conflict checks run before export; inputs are
checked again before atomic publication. Cancellation or changed sources preserve
the destination. DMM does not enforce CDMW's source hashes at mount. Re-export
after a game update, use a manager build supporting V3 clone patches and split item
localization, and inspect its log for skipped/conflicting intents. Enable this
package in place of its original packages or installed CDMW contribution.

The adapter follows the guide's V3 intent dialect and the public parser schema at
[`2e3b7a59c49f`](https://github.com/exodiaprivate-eng/dmm-parser/tree/2e3b7a59c49fbcc6c38adf84d8dcd9cc252d3d39).
Owned-fixture and queued UI tests establish export/source preservation only;
DMM mounting, appearance, acquisition, refinement in game and save compatibility
remain unverified. This route still relies on manager-composed shared tables and
does not establish native independent-item registration.

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
Equipment defaults retain v1. Extended item controls write explicitly required
v2 capabilities. V2 also admits existing ItemInfo field/package-link modules,
complete stock-item overrides and standalone `texture.replace@1` packages.
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

Primary `CDI_<UUID>` ItemInfo names also receive a conservative 32-bit hash
collision check under ASCII lowercasing. Selected packages are compared with one
another, stock and external ItemInfo names, and active, disabled and removed
identity reservations. Refusals identify both names and their owners. Reinstalling
or updating the same owner keeps its identity. This check does not certify
arbitrary Unicode/CRT locale behavior, auxiliary name families or native lookup.

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

## Inspecting ownership and isolation

The developer command `scripts/inspect_cditem_isolation.py` recompiles selected
packages through current package admission, source verification, identity allocation
and per-package dependency checks. Run it from the repository with the project
virtual environment, choosing the packages' current deployment route:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_cditem_isolation.py --game-root "C:\path\to\Crimson Desert" --target virtual A.cditem B.cditem
```

The JSON report identifies package UUIDs and content hashes, proposed bindings
and paths, actual record additions, shared-file outputs, shop/group additions,
source dependencies, decoded resource references and remaining ownership limits.
Proposed bindings include retained and retired reservations; they are not all
records emitted by this compilation. Generated strings, localisation keys, prefab
bindings, icons and texture registrations are included. V2 `item.fields` and
`texture.replace` operations remain explicit stock edits; `package.links` retains
its exact provider pins. Package metadata cannot supply ownership evidence or
enable a loading route.

The resource graph separates contribution paths from authoring-validation roots
and records supported implicit material sidecars. Borrowed and unclassified
resources remain explicit. Its 16,384-edge diagnostic cap bounds report storage;
`graph_complete` describes that inventory only. Truncation or an unknown layout
prevents a closure claim. This graph does not establish native lookup or lifetime,
and remaining donor-record, texture and unchanged-physics protections still apply.
An unwalked namespace-qualified material resource also keeps source closure false,
so source-carrier verification remains required.

Inspection publishes no package, identity reservation or game output. Existing
reservations constrain the preview; new allocations are not committed. The report
covers validated per-package outputs and does not establish aggregate installation,
native lookup, rendering or save compatibility. Both current backends still compose
shared game files, so `isolated_new_item_admitted` is false.

Use `--folder` for each additional ordinary mod folder included in dependency
checks. Exit status 0 means inspection produced a report; invalid or incompatible
inputs return 2. Adding `--require-isolated` returns 3 when the stronger isolation
claim is refused. This check currently refuses every package and cannot be used
as a substitute for the native definition and resource-discovery proof.

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
Compiler revision 10 includes private material DDS copies and the narrower donor
record rule below. Previously compiled installations use the existing explicit
rebuild flow; virtual profiles require **Apply changes**. IDs and the portable
v1/v2 package schemas remain unchanged.

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

### Tier, required level and durability

Create New Item's **Stats & Prices** controls inherit the template until changed.
Tier is an unsigned byte (0..255), required level is an unsigned u32
(0..4,294,967,295), and maximum durability is an unsigned u16 (0..65,535).
These are raw serialized values: zero and 65,535 are preserved literally; their
gameplay or sentinel meanings have not been established. Resetting the panel or
changing template restores inheritance. Controls with unverified locations are
disabled; planning also refuses a requested edit if its layout cannot be proven.

An explicit override exports v2 with one required **`item.properties` version 1**
module accompanying `item.legacy@1`. Its data has exactly `item_tier`,
`required_level` and `max_durability`; each is an integer in the range above or
`null` for inheritance, and at least one must be explicit. Duplicate modules,
unknown fields, booleans and out-of-range values refuse on import. The module
changes only the newly owned item; stock `item.fields@1` selectors stay unchanged.

The retained v1 recipe and migration provenance remain intact. Equipment recipes
without these overrides or extended settings still export v1, with the same
frozen vocabulary and canonical digest. Existing v1/v2 packages retain their
handling. Older readers refuse the
required capability instead of silently dropping the new settings. Compilation
identity includes the module and a revised adapter identity, requiring an older
virtual profile to be rebuilt through **Apply changes**.

The bounded 0x11/0x12 adapters locate tier before the socket/stat block and level
after the variable secondary description. Durability requires an unambiguous
complete trailing faction, repair, prefab and inventory-routing structure; a
fixed distance from EOF is insufficient. Unknown, truncated or ambiguous endings
refuse. Reads are on demand for the selected item, not a startup-wide row scan.
Evidence at `a4c3e6e2` plus this scoped change is source, retained fixture rows,
synthetic physical/virtual compilation and headless controls/native presentation.
It does not establish current game/save behaviour or the meaning of tier values.

### Extended item settings and usable items

**Stats & Prices > Item settings** edits repair materials, item rules, extraction,
use actions, cooldown/charge data and existing full-width prices/stat counters.
**Load item references** prepares selectors in the existing cancellable background
lane. Unsupported definitions are excluded; unavailable optional tables do not
disable repair/item-rule controls. Build plan validates the selected dependencies.
Reset restores the template. An empty repair/use list explicitly clears it;
`null` inherits. Zero and `false` remain explicit overrides.

These choices require **`item.properties@2`** with the same three scalar keys as
version 1 plus a required `settings` object. Version 1's exact field set and the
frozen v1 recipe are unchanged. The settings object has exactly these fields:

| Settings | Serialized contract |
| --- | --- |
| `repairs` | Nullable list of `{resource_item, repair_value, repair_style, resource_count}`: positive u32 item key, u16 repair value, u8 style, positive u64 quantity; at most 128 entries |
| `blocked_store_sell`, `discardable`, `important_item`, `destroy_when_broken`, `preserved_on_extract`, `can_disassemble`, `extractable` | Nullable booleans |
| `extraction_reward`, `minimum_extract_level` | Nullable u32 existing DropSet key (zero clears), and u16 level |
| `use_actions` | Nullable list of distinct positive u32 existing ItemUseInfo keys; at most 128 entries |
| `cooldowns`, `maximum_charges` | Nullable arrays of exactly three u64 timer values or three u32 charge counts, in source order |
| `charge_type`, `shared_cooldown_group` | Nullable raw u8 type and u32 group hash |
| `quantities` | Up to 256 `{kind, key, value, level}` edits. `price` uses `level: null`; `buy_price` and `stat` use u16 levels. Keys are positive u32. Prices are u64; raw stat counters are i64. Selectors must be unique and already exist. |

At least one setting must be explicit. Wrong types, unknown fields, duplicates,
overflow, missing/ambiguous quantities, and overlapping legacy/full-width edits
refuse. The UI uses exact integer text, including grouped locale input, without
converting 64-bit values through floating point. Legacy stat/price views and v1
authoring limits remain 32-bit; `full_value`/`full_price` expose complete storage
values. A PriceFloor's upper amount word is distinct from its preserved `_symNo`.

Repairs require existing unblocked resource items. Extraction rewards must decode
and round-trip as supported item-producing DropSets, with existing reward items.
Use actions require a complete, unblocked ItemUseInfo layout; selected skill and
condition references and supported reward-box dependencies are checked. Borrowed
definitions and their table directories/payloads retain exact source pins. This
does not author arbitrary action payloads, transmutation recipes or runtime code.

**Template > Usable items** exposes inventory-use templates with source actions.
Selection retains those actions in the required v2 capability. These items keep
their source appearance and can compile without an equipment mesh; equipment
model/effect authoring still requires an equipment template. Both physical and
virtual routes allocate a real owned item and preserve its normal identity rules.

The complete bounded reader covers 115 ItemInfo field spans and discriminated
ItemUseInfo payloads. Declared icon/prefab/animation fields qualify resource hash
rebinding and final dependency edges; recipe IDs use a separate namespace, and
tag/material fields cannot be changed by a coincident hash. Use and recipe lists
have declared boundaries even with nonempty earlier lists. Unknown layouts retain
the existing v1 compatibility path; extended writes require complete qualification
through EOF. Known resource roots do not establish complete engine lookup closure.

Evidence against `82ece562` plus this scoped extension is retained legacy fixture
inspection, owned constructed layouts, golden clone replay, both synthetic
deployment routes and real headless controls/native presentation. Timer units,
charge/style enums, gameplay effects, save behaviour and independent native
registration remain unverified. Compilation revisions require **Apply changes**
for older virtual profiles; package UUIDs, legacy recipes and provenance remain.

### Regeneration, level-based stats and equipment passive skills

**Stats & Prices > Item settings > Stats and passive skills** edits the two
regeneration counter families and raw level-based parameters. Choose an existing
enhancement level and StatusInfo entry to add a row; change its Override value or
use **Remove stat entries**. Blank overrides restore inheritance. Regeneration
counters are signed i64; level-based parameters are u8 (0..255), not flat bonuses
or a verified scaling formula. Existing enhancement levels are retained.

**Override equipment passive skills** copies the template list for editing.
**Load item references** loads the SkillInfo selector in the existing cancellable
worker. Add skills, edit their raw u32 levels, or remove selected entries. An empty
overridden list clears the equipment passives; unchecking the override or using
Reset restores inheritance. These are separate from socket perks and per-level
equipment buffs. Template changes and the main Stats reset also clear overrides.

Portable edits require a separate **`item.stats@1`** module accompanying the owned
`item.legacy@1`. Its data has exactly these fields:

| Field | Serialized contract |
| --- | --- |
| `statistics` | At most 256 `{kind, level, key, value}` entries. `kind` is `regeneration_max`, `regeneration` or `level_stat`; `level` is an existing u16 enhancement level; `key` is a positive u32 StatusInfo key. Values are i64 counters or u8 parameters. `null` removes an existing entry; an integer updates or adds it. Selectors must be unique. Each resulting family list is bounded to 256 entries. |
| `passive_skills` | `null` inherits; an empty list clears; otherwise at most 128 `{skill_key, level}` entries with unique positive u32 skill keys and raw u32 levels. |

At least one override is required. Unknown fields/families, booleans, overflow,
duplicate selectors/skills, ambiguous levels and removal of a missing entry
refuse. Nested list resizing preserves static stats, prices, equipment buffs,
effects and every unassigned ItemInfo field. Existing v1 recipes and
`item.properties` versions 1 and 2 are unchanged, including their exact field
sets. Older readers refuse the required capability. Compilation revisions require
**Apply changes** for an older virtual profile while retaining package/item IDs.

Planning checks the final regeneration/level-stat StatusInfo keys and all final
equipment passive SkillInfo keys, including inherited entries. Directories and
payloads are pinned to the source. Item-use checks also validate declared skill,
condition, sublevel, character, sequencer-spawn and level-gimmick-scene references;
unnamed integers, UI names and runtime aliases are not guessed to be table keys.
Missing targets and changed dependency payloads refuse before recipient writes.
This does not establish complete skill/action dependency closure or validate raw
skill levels against gameplay limits.

Evidence against `8e9ed31b` plus this scoped extension is independently constructed
legacy/current rows, exact-byte and resizing regressions, package admission and
synthetic physical/virtual rebuild/removal, and real headless controls/native
presentation. Gameplay meanings, timer/rate units, native registration and save
acceptance remain unverified; no packaging or game execution was performed.

### Consumable behavior, tags, material eligibility and stack counts

**Stats & Prices > Item settings > Inventory and consumables** has two pages:
**Consumable behavior** and **Tags and material eligibility**. Flags offer
Template/Yes/No. Blank byte selectors inherit; explicit zero is retained. Check
**Override** to edit a list, separate entries with semicolons, and leave a checked
list empty to clear it. Uncheck it to restore inheritance. Reserve slots use
`slot:condition` (condition zero means no reference); material groups use
`group:raw value`. These are eligibility lists, separate from item-group membership
and crafting recipes. Tags and consumable types are raw u32 IDs with no inferred
names or namespace. Quick-slot indices and usable-alert types are raw u8 values.
The second material-group word is a raw parameter, not a verified quantity.

**Max stack** accepts exact whole numbers from 1 through
18,446,744,073,709,551,615, including grouped digits. Blank or the template value
restores inheritance. Values up to u32 retain the legacy recipe path; larger
overrides use the new capability. No floating-point conversion or high-word
truncation is used. The main Stats reset and template changes clear all overrides;
Reset on the inventory page preserves the separately edited stack count.

Portable overrides use one required **`item.inventory@1`** module attached to the
owned `item.legacy@1`. It has exactly these nullable fields; at least one must be
non-null:

| Fields | Contract |
| --- | --- |
| `max_stack_count` | Positive u64; cannot coexist with a legacy stack override. |
| `apply_max_stack_cap`, `use_immediately`, `hide_on_pop`, `enable_alert_ui`, `inventory_buff` | Boolean flags; `false` is an explicit override. |
| `quick_slot_index`, `usable_alert_type` | Raw u8 selectors (0..255). |
| `tags`, `consumable_types` | Lists of unique raw u32 IDs, including zero. |
| `material_items`, `material_gimmicks` | Lists of unique positive u32 source keys. |
| `material_groups` | Unique positive u16 `group_key` with a raw u32 `value`. |
| `reserve_slots` | Unique `{slot_key, condition_key}` pairs; positive u32 slot and nullable-reference u32 condition. |

Override lists are bounded to 256 entries; `null` inherits and `[]` clears. Unknown
fields/versions, booleans in integer fields, overflow and duplicates refuse.
Complete legacy/current ItemInfo layouts qualify every edit and preserve all
unassigned fields. Planning checks final material item/gimmick/group and reserve
slot/condition references, including inherited entries, and pins their source
tables. Missing or blocked material items, missing references, duplicate directory
identities and changed dependency payloads refuse before recipient writes.

V1 recipes, `item.fields@1`, both `item.properties` versions and `item.stats@1`
retain their existing schemas. Older readers refuse the new required capability.
The compiler revision requires **Apply changes** for older virtual profiles while
retaining package and item identities. Evidence against `08a3c63b` plus this
extension is constructed rows, exact-byte regressions, headless controls/native
presentation, and synthetic physical/virtual compilation, rebuild and removal.
Raw enum/tag meanings, group-parameter semantics, native admission and game/save
effects remain unverified. Save-at-use and logout-at-use overrides use the separate
definition capability below.

### Extended item definition

**Stats & Prices > Item settings > Extended item definition** provides six sections:

| Section | Supported overrides |
| --- | --- |
| Text and knowledge | Secondary descriptions, KnowledgeInfo link and raw obtain type. |
| Linked items and bundles | Packed, unpacked and NPC-drop ItemInfo links; minimum-count/GimmickInfo bundle entries. |
| Item flags | Dyeability, editable grime, housing, reward loot, clone-actor equipment, market/editor/shield/wild/preorder/average-price flags and save/logout at use. |
| Equipment and sharpness | Observed compatibility hashes and occupied slot/index pairs; u16 sharpness limit and CraftToolInfo link; maximum, regeneration, static and byte-parameter stats. |
| Presentation | StringInfo map icon and alert, ItemInfo-level EffectInfo references, pattern descriptions and localized parameters. |
| World and economy | Gimmick link/tags, all six sealing-target variants, raw money identifiers, unlock message/flags, faction item costs/prices/tier, inventory routing, drop limit/target flag and raw respawn value. |

Choose **Load definition references**, select a section and field, then check
**Override selected field**. Edit the Value column. Select a list and choose
**Add entry**, or select one or more entries and choose **Remove selected**.
Nested list entries can be removed without removing their parent. Select a
reference cell and choose **Use selected value** for a loaded source ID. Uncheck
an override to inherit; a checked empty list clears it. Reset restores this page;
the main Stats reset and template changes clear all definition overrides.

Secondary descriptions have their own override and language table. Select a
source item with an existing numeric secondary description when the template has
none. Its observed low-word tag and category are copied; the new high word uses
the allocated item ID. The code does not guess a secondary-description tag.
**Source (English)** is a preview, while each blank language override uses the
English override or that language's source text. **Clear secondary description**
writes an empty reference. Original source localization remains unchanged.

Portable overrides use one required **`item.definition@1`** module attached to
`item.legacy@1`. Its data has exactly `fields` and `secondary_description`:
omitted named fields inherit, while `false`, zero and empty lists are explicit.
The secondary value is `null` or exactly `{source_item, texts}`; empty `texts`
clears and requires a null source. At least one override is required. The closed
field registry and nested wire contracts live in
[`item_definition.py`](../../domain/new_item/item_definition.py); binary widths
and generation checks live in
[`iteminfo_definition.py`](../../core/iteminfo_definition.py).
Lists are bounded to 256 entries (slots: 8, slot indices: 16, pattern parameters:
64). Counters retain u64/i64 precision; sharpness parameters are u8. Routing must
match the source generation's fixed 9/10 u16 entries; a faction tier exists only
in the current layout. Unknown fields/versions, invalid types, duplicates,
overflow and unsupported layout/discriminant values refuse. Earlier v1 recipes,
properties, stats, inventory and field schemas remain frozen. Older readers
refuse this required capability; older compiled virtual profiles need **Apply
changes**, retaining package and item IDs.
The experimental DMM V3 field-JSON exporter retains its existing module allowlist
and refuses this new capability; use the normal retained-source package workflow.

Planning validates all final declared references, including inherited entries,
against unblocked ItemInfo and named knowledge/effect/gimmick/local-string/
character/tribe/pattern tables; CraftToolInfo uses its actual u16 root key.
Sharpness status keys and localized parameters are checked too. Equipment hashes
and slot indices must be witnessed in supported source rows. Map icons use a
StringInfo hash/name, unambiguous UI texture XML binding and validated DDS,
with bounded, cancellable scans. Relevant table, localization, registry and
texture payloads are pinned; missing, ambiguous or changed dependencies refuse
before recipient writes. This establishes direct declared-reference checks,
not complete recursive EffectInfo/GimmickInfo/skill engine closure.

Sealing entries contain `{target_type, item, count, target}`. The common item
reference and u64 count precede a target payload: 0 ItemInfo/u32, 1 GimmickInfo/u32,
2 counted UTF-8 tag, 3 CharacterInfo/u32, 4 TribeInfo/u32, or 5 empty/null.
The embedded schema's selected branch was insufficient. Read-only static analysis
of the local **1.0.0.2976** executable at reader RVA `0x1531f00` matched the
schema's read/call sites and resolved this dispatch; this is function-level
agreement, not whole-build equivalence with CDKit's 3790 metadata. Unsupported
discriminants refuse. No game code or ASI was executed.

Evidence against `da6a54c6` plus this scoped extension is independently constructed
legacy/current rows, exact-byte preservation/resizing, closed package admission,
both owned-fixture deployment/rebuild/removal routes and real headless
controls/native presentation. The respawn field remains a raw u64; its name does
not establish seconds or floating-point encoding. Money identifiers and routing
selectors have no invented namespace/enum labels. Gameplay meanings, complete
engine closure, native admission and save acceptance remain unverified. No
packaging, visible UI or game validation was performed for this extension.

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

A bounded preparation cache keys fully admitted packages by their exact ZIP artifact
and current admission limits. Consumers receive independent mutable metadata while
reusing immutable validated resources. Identical compressed members can reuse already
decoded bytes only after their compressed representation and local ZIP metadata match;
CRC, size, path, capability and complete-package checks remain mandatory. Semantic
admission, resolution and retained-package recovery share that preparation owner.
An ordinary ZIP classification checks its member directory without decoding every
asset just to decide which reader owns the package.

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

### Additional item behavior

**Stats & Prices > Item settings > Additional item behavior** exposes seven
sections through the existing exact-value tree:

| Section | Complete fields |
| --- | --- |
| Classification and links | Item type, category/equipment family, raw material selectors, intrinsic item and hackable-character groups, stage, advice and mission references. |
| Metadata | Broken-name prefix, memo/filter strings, default texture and emoji texture symbol/path. |
| Drop defaults | Initial enchantment level, socket items/material amounts, valid/use-socket fields, nested and root default subitems, raw drop-stat type, terrain attachment and raw u32 discard-Y bits. |
| Pages and inspection | Fixed/dynamic page textures and KnowledgeInfo references; inspection targets, actions, localization references, rewards and effects; complete inspect-action sockets/hashes. |
| Inventory events and docking | Optional inventory-change event/three ConditionInfo references/destination; attached item/character/gimmick references, sockets, flags, collision and hash arrays. |
| Currency definition | Optional raw u64 price floor and unit-keyed entries with UI component, minimum, icons and existing localization references. |
| Conditional icons and prefabs | Full icon/highlight/state/usability conditions and prefab scale, prefab/animation hashes, equipment slots, tribe/gender and docking selectors, flags and data type. |

Load behavior references, select a field, and check **Override selected field**.
Edit Value; select lists to add/remove entries. Fixed arrays cannot be resized.
**Enable section** creates an optional record; removing its root writes absence.
Uncheck to inherit; explicit false, zero and empty lists retain their meanings.
Reset and changing template clear overrides. References can reuse existing
localized entries; this capability does not invent new localization namespaces.

The required `item.behavior@1` module is a closed `{fields: {...}}` object. Each
key selects a complete application-owned ItemInfo root field; descriptors, byte
offsets, executable readers and unknown/future members are refused. It attaches
to exactly one `item.legacy@1` recipe. All earlier wire schemas stay frozen.
Complete drop defaults and the separate socket controls cannot own the same data.
Legacy inspect actions omit catch-tag storage and refuse a nonzero catch tag.
Recognized default-subitem tags are 0/3/9/14/15/16/17/18/255; only 0/3/9 carry
u32 payloads. Character and gimmick payloads are qualified; tag 0 stays raw because
its reference namespace is unproven. Other enum/hash meanings remain raw.

CategoryInfo, CharacterGroupInfo and ItemGroupInfo keys are u16; equipment,
stage/advice/mission and condition references are u32. The docking NPC-only member
is a ConditionInfo reference. Prefab scale stores three finite float32 values.
Texture symbols require unambiguous XML/DDS bindings; prefab and animation hashes
require source StringInfo/resource bindings. Raw discard offset, UI component,
timer/selector and currency semantics retain explicit limits.

### Complete stock-item overrides

**Write stock item package…** on Item settings writes the current combat and
item settings for the selected template, preserving its original record identity.
It requires no Build plan and allocates no new item, asset or localization IDs.
New-item appearance, names and distribution use normal new-item export. New
localized text requires a new item; stock operations may select existing text
references or clear secondary text. The service API also accepts full declared
progression/price roots, existing localized-reference roots and every supported
definition/behavior/inventory/settings root. Identity, block flag and internal
name are immutable through this adapter. Primary text references must retain a
namespace accepted by the existing ItemInfo row reader; arbitrary cross-item
name/description aliases refuse. Nested and secondary references can select
qualified existing localization entries.

The new required `item.overrides@1` module contains `field.replace` operations
using adapter `cd.iteminfo.declared-v1`. Targets identify the actual ItemInfo key;
selectors are closed `{family, name}` pairs. Each carries the exact pristine row
digest, expected complete-field value and replacement. Variable-length strings,
optional records and counted lists rebuild the table directory with preserved
record order and unrelated bytes. The older `item.fields@1` and all earlier
capabilities retain their original operation grammar and limits.

Disjoint complete fields compose in either order. Same-field replacements must
agree; legacy scalar assignments may overlap only when their resulting value
agrees. Borrowed records stay protected. Rebuild, disable/enable and removal
recompose active intent; removal restores original rows/offsets without dummy ID
reservations. Stock exports require shipped source resources and refuse missing,
changed, blocked, ambiguous or incomplete dependencies before publication.

Known ItemInfo references are followed recursively, including price/repair,
material/sealing/inspection/docking and reward item links. Declared prefab, model
sidecar, texture and effect resources are traversed and pinned. Cycles terminate;
limits are 1,024 items, 4,096 resources and 1 GiB of traversed resource data.
Cancellation never publishes a partial graph. Each contribution's source reads
are checked separately, so another package's unrelated reads are not requirements.
Opaque source rows, auxiliary engine-condition/effect payloads, implicit runtime
lookup and lifetimes remain complete-source dependencies with partial closure.
These checks do not establish native admission or game/save behavior.

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

The row reader decodes the stored stack count as u64 and distinguishes the u8
`_itemType` from the u16 `_categoryInfo`. It walks the secondary LocalStringInfo
description and u32 level requirement to find the category, including nonzero
values and variable-length description keys. Perk grouping and recipe searches
retain their category-based behavior. Malformed secondary descriptions leave the
category unverified and field-package admission refuses them.

Both existing field adapters still require the stack count's upper u32 to be
zero, and their stack assignments remain positive u32. The authoring stack setter
writes the full stored field when applying such an edit. No package field,
selector, wire version or canonical package identity changed; compiler records
distinguish the revised item adapters for rebuild and cache validation.

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

Independent compilation privately copies supported stock DDS files referenced
by already-owned model materials, including selected variants and their decoded
prefab companions. Only complete, unqualified `ResourceReferencePath_ITexture`
`_path` attributes are rebound. Matching uses the full normalized source path;
comments, labels, unrelated attributes and other material bytes are preserved.
Each item reuses one unchanged private copy per source path. Explicit imported
texture outputs keep their existing destination rules.

Automatic copies use the item's allocated stem plus a stable source-path digest,
and pass through the existing DDS/PATHC registration and collision checks.
Their original source hashes stay in the package dependency contract. These
copies add compiled output bytes without adding new portable input blobs.
Automatic extraction checks the source size first; independent additions through
`_Planner.add` count their logical bytes and paths even when memory is shared.

An unsupported source DDS retains its original borrowed binding with a warning.
Malformed reference XML, missing source witnesses and resource-limit violations
refuse preparation. Other resource types, namespaces, socket descriptors and
unknown physics remain explicit limitations. Donor DDS replacement guards still
apply, and current output still uses shared-file composition.

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

Repeated independent **Build Plan** requests can reuse one immutable clean-stock
catalogue and parsed-table generation. Reuse revalidates its root, discovery metadata,
original index/content witnesses and reader/service authority. Each request gets
separate dependency tracking, mutable entry views and working caches, so cancellation
or another plan cannot populate its provenance. The cached baseline remains the
clean-stock view; mounted texture-registry rebasing is performed for each request.

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

In **Mod Management > Shared files**, **Scan installed mods** compares archive-installed
items and the saved virtual profile with all mounted external archive providers.
Virtual items are read from the applied generation's retained `.cditem` packages,
using their saved identities, and include the profile's selected mod folders.
Moving or editing the original package downloads does not change the applied
versions scanned. Removed identity reservations are not active contributors.
Missing or mismatched retained packages cannot produce a compatible result. **Scan mod
folder...** additionally inspects an extracted, uninstalled mod folder, including
loose game-relative files, `files/` layouts and PAMT/PAZ packages. Scans are read-only.
They report compatible data, shared files that can be merged, record conflicts,
and unsupported inputs. This is an on-demand file-data comparison, not a runtime
plugin analyser or continuous external-manager monitor.

External providers can contain unrelated game folders, such as `sequencer/`.
Those paths retain the same canonical-path and archive-containment checks;
they are tracked for comparison rather than admitted as `.cditem` resources.
The package resource-root restrictions remain unchanged, and private resource
images contain only the selected packages' owned compiler outputs.

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

For comparisons that include a virtual profile, update the shared files through
**Mods > Apply changes**. The archive rebuild and export actions are unavailable
for these results because they do not include virtual contributors. Scanning
does not publish a profile or change game archives, saved identities or mod files.

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

- ItemInfo: referenced item/perk/material/price rows stay unchanged. The donor's
  own row may coexist with an external or typed field edit only after the compiled
  primary row has a distinct key, `CDI_<UUID>` name and ASCII name hash, and no
  retained donor identity is found in emitted records/resources or transitive
  borrowed rows. Explicit donor references, ambiguous names and incomplete table
  changes keep the original protection. Unrelated records and external added IDs
  can coexist.
- EquipTypeInfo and StatusInfo: complete referenced equipment and stat records
  stay unchanged; unrelated records can coexist.
- StoreInfo and ItemGroupInfo: the existing structured stock/member merger
  combines supported additions and rejects incompatible changes.
- Other dependency tables and localisation/prefab collections: existing records
  stay protected; supported appended records can coexist. Unverified resource
  changes still refuse rather than assuming they are unrelated.

The donor exception changes only its required ItemInfo record. Exact author-source
hashes and index witnesses remain mandatory, and equipment, status, perk, price
and resource dependencies retain their guards. It is a compiled-record result;
it does not establish closed resource ownership or native lifetime.

A source-equal `item.fields` assignment remains an active final-value requirement
even when its output bytes match the source. Removing its package releases only
that owner's requirement. A remaining borrowed donor reference still blocks an
opposing edit; a separately identified clone with no remaining donor reference
does not. The [lifecycle regressions](../../../tests/test_independent_item_semantic_routes.py)
cover both outcomes through physical and virtual composition, with exact source
checks and unchanged clone bytes and bindings.

Both halves of a changed table are required. An external ItemInfo row's serialized
key must equal its table-directory key; a mismatched identity is refused before
composition. Multiple external tables can be
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

The source and destination HKX paths follow their actual PAC paths, replacing
`character/model/` with `character/bin__/meshphysics/` and `.pac` with `.hkx`.
Prefab names, including `_index02` variants, do not replace that mesh binding.
Each mesh in a composed armour prefab is checked separately.

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

Loading packages without composed shared tables is parked research, not a
supported route. Both supported routes compose the shared game tables at
installation; package-owned identities, names, keys and asset paths, together
with overlap refusal, keep separate packages from overwriting each other. The
native research, its evidence and open contracts are in
[native runtime registration research](../../../native/cdmw_virtual_loader/research/runtime-registration.md).
