# Core

Owns low-level archive, DDS, texture workflow, package, catalog, research,
texture editor, native-helper integration, and compatibility orchestration that
has not moved to narrower packages yet.

Keep PySide widget code out of core. Preserve legacy public imports while moving
new policy to `cdmw/domain/`, coordination to `cdmw/services/`, long-running
execution to `cdmw/workers/`, mesh/material operations to `cdmw/modding/`, and
preview packaging to `cdmw/rendering/`.

`archive.py` and `archive_modding.py` are cached lazy compatibility facades.
Their explicit owner maps live in `archive_compat_exports*.py` and
`archive_modding_compat_exports*.py`; focused core modules import the mapped
owners directly and must never import either facade.

`archive_binary_preview.py` directly reexports binary-sidecar analysis and
corpus reporting from bounded `archive_binary_preview_{analysis,corpus}.py`
owners. Keep their output and cancellation contracts exact when decomposing
the remaining format decoders.

`temp_cache.py` owns process-local keyed build serialization and scoped cache
leases. Builders publish complete units before returning; readers hold a lease
while consuming paths, and pruning skips active or just-returned units.

Brand-new archive content is split by format owner. `archive_entry_addition.py`
adds validated PAMT/PAZ entries; `archive_overlay.py` and `papgt_format.py` build
and mount isolated archive groups; the ItemInfo, StringInfo, StoreInfo,
ItemGroupInfo, MultiChangeInfo, PATHC and PAPPT modules decode and rewrite only
their proven fields. They return plans and bytes, never bypass service-owned
confirmation, backup, rollback, or restore.

`effect_binary.py` owns byte-complete `.pae` / `.paem` reflection decoding and
offset-addressed values. `effect_edit.py` permits only fixed-size value changes
and same-length reference renames. Approximate particle presentation belongs to
the effect services and resident .NET host, not to these binary owners.

`archive_mesh_appearance.py` and `character_appearance_bundle.py` resolve
read-only PABC/PAMT presentation and portable dependency bundles. Source archive
payloads remain immutable; callers receive clones or atomic extracted bundles.

Related tests: focused feature tests and architecture guards under `tests/`.
