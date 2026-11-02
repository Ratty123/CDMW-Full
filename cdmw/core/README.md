# Core

Owns low-level archive, DDS, texture workflow, package, catalog, research,
texture editor, native-helper integration, and compatibility orchestration that
has not moved to narrower packages yet.

Keep PySide widget code out of core. Preserve legacy public imports while moving
new policy to `cdmw/domain/`, coordination to `cdmw/services/`, long-running
execution to `cdmw/workers/`, mesh/material operations to `cdmw/modding/`, and
preview packaging to `cdmw/rendering/`.

## Compatibility facades

`archive.py` and `archive_modding.py` are cached lazy compatibility facades.
Their explicit owner maps live in `archive_compat_exports*.py` and
`archive_modding_compat_exports*.py`; focused core modules import the mapped
owners directly and must never import either facade.

`archive_binary_preview.py` directly reexports binary-sidecar analysis and
corpus reporting from bounded `archive_binary_preview_{analysis,corpus}.py`
owners. Keep their output and cancellation contracts exact when decomposing
the remaining format decoders.

## Process and temporary resource ownership

`common.py` validates Windows process creation times when following parent IDs
for helper cleanup. Reused IDs and unavailable identity data must not make
older or unrelated processes descendants of a helper.

`temp_cache.py` owns process-local keyed build serialization and scoped cache
leases. Builders publish complete units before returning; readers hold a lease
while consuming paths, and pruning skips active or just-returned units.

`owned_temp.py` marks private transient roots with their path and filesystem
identity and holds a file lock for their lifetime. Cleanup refuses unmarked,
redirected, linked or live roots and keeps the marker when a payload deletion
fails. `session_generated_cache_path` groups derived material artifacts into a
locked per-run unit under the configured cache; callers retain usable paths for
the entire session. Startup maintenance retires abandoned runs and writes a
bounded report through `services/temp_data_cleanup.py`, off the UI thread.

## Texture encode cache

`texture_encode_cache.py` retains at most 64 validated native DDS results and
128 MiB within the process. Its keys hash the prepared source contents and include
the encoder identity, format, dimensions, mip count, colour/alpha policies and
coverage threshold. Preview preparation, placement builds and output plans share
this reuse without changing quality or output ownership. Cache hits still use
staged DDS validation, cancellation checks and atomic publication; failures and
sources changed during conversion are not retained. Encoding and file I/O run
outside the cache lock so independent workers do not wait behind another encode.

## HKX tagfile rebuild

`archive_hkx_tagfile_model.py` is the strict codec for the game's Havok 2024.2
tagfiles: it decodes items, payloads and every reference (PTCH item indices and
the self-relative `hknp` fields), and serializes DATA, ITEM, PTCH and section
sizes again from that model. The TYPE section is carried verbatim. Strides,
alignments and relative reference fields are corpus measurements kept in
`archive_hkx_tagfile_layout.py`; a file with an unknown type, a layout or padding
the rules do not reproduce, or an item no known reference reaches is refused with
an `HkxTagfileRefused` code rather than rebuilt. Use
`tools/hkx_tagfile_corpus_harness.py` to recheck the installed corpus after a game
update before trusting the tables.

`archive_hkx_joint_limits.py` reads and writes ragdoll and physics-system joint
limits. Limits are found by Havok constraint atom type at the offsets every
shipped constraint uses; cone and plane limits also recompute their cached
`1/cos` and `tan` values, and edits stay inside the angle ranges where that
rule matches the game's values. These are in-place edits.

`archive_hkx_structural_edits.py` holds the structural edits built on it. Only
string replacement is allowed: a `char` item reached solely through
`hkStringPtr` may change length, and every owner of a shared string sees the
change. Hull, compound, ragdoll, constraint and mesh-shape edits stay refused with
the reasons in `HKX_BLOCKED_STRUCTURAL_EDITS`; in-place value edits keep using the
fixed-size patch gate. The HKX decode document reports both gates. Output is
loose bytes for packaging; nothing here writes to archives.

## Archive content creation

Brand-new archive content is split by format owner. `archive_entry_addition.py`
adds validated PAMT/PAZ entries; `archive_overlay.py` and `papgt_format.py` build
and mount isolated archive groups; the ItemInfo, StringInfo, StoreInfo,
ItemGroupInfo, MultiChangeInfo, PATHC and PAPPT modules decode and rewrite only
their proven fields. Current recipe, item-reward, ItemUse and dye records have
bounded codecs in `item_recipe_table.py`, `item_reward_table.py`,
`item_use_reward.py` and `partprefab_dye_table.py`. Recipe connections are identified
by `item_recipe_links.py` using decoded inputs and outputs; ambiguous boundaries
remain unsupported. These modules return plans and bytes, never bypass service-owned
confirmation, backup, rollback, or restore.

## Effect binary decoding

`effect_binary.py` owns byte-complete `.pae` / `.paem` reflection decoding and
offset-addressed values. `effect_edit.py` permits only fixed-size value changes
and same-length reference renames. Presence masks support the installed nine-byte
layout. Identified collections preserve both lookup keys and their parallel
indices; inherited slots are not bounded by the number of local overrides.
Structural serialization retains these tables only with unchanged metadata and
element identities/order, and refuses unproven collection restructuring. Decoder
changes invalidate the effect catalogue so incomplete cached results are rebuilt.
Approximate particle presentation belongs to
the effect services and resident Rust host, not to these binary owners.

## Build compatibility

`mod_compatibility.decode_paver_build` shares binary PAVER version decoding with
archive backup metadata and retains legacy text versions. Matching PAVER hashes
take precedence over display-label changes; differing comparable hashes still
mark the build as changed.

## Material and character appearance

`archive_model_texture_binding_selection.py` matches exact component/submesh
identities and selects sidecar texture bindings. The semantics module preserves
existing imports while keeping selection rules in this bounded owner.

`archive_mesh_appearance.py` and `character_appearance_bundle.py` resolve
read-only PABC/PAMT presentation and portable dependency bundles. Source archive
payloads remain immutable; callers receive clones or atomic extracted bundles.

## Focused checks

Related tests: focused feature tests and architecture guards under `tests/`.
