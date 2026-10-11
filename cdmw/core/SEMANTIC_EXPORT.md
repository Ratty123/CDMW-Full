# Semantic mod export contract

Owner: `mod_compatibility.py`; negotiated capability `export.semantic@1`.

A semantic export folder contains exactly one opaque file, `cdmw-semantic.cditem`.
It is a ZIP with mandatory `semantic.json`, `packages/<sha256>.cditem` and
`payloads/<sha256>` members. It exposes no loose game paths or installable archive
groups. Existing byte-only readers find no game payload; existing single-package
readers refuse the missing `item.json`. Removing metadata does not leave an
installable semantic artifact. Deliberate extraction into ordinary files creates
a legacy input with only byte-derived guarantees. Checksums do not authenticate
the author or prevent stripping.

The manifest has exactly `format` (`cdmw_mod_semantic_export`), `version` (1),
`requires` (`{"export.semantic":1}`), `compiler`, `target_game`, `packages`,
`files`, `bindings` and `witnesses`. Unknown versions, duplicate JSON keys,
case/path aliases, extra or missing archive entries and extra files beside the
wrapper refuse. All lengths and SHA-256 values are checked after on-disk readback.
Existing package, metadata, per-file and aggregate size budgets still apply.

Each package record has `identity`, `content`, `artifact` and `size`; its member
is `packages/<artifact>.cditem`. These are the exact retained original packages,
including frozen v1 recipes, source-equal typed assignments, exact release/content
pins, exported objects and reference requirements. Existing readers validate
these packages and the dependency graph. This contract does not infer intent from
compiled differences.

Each file record has `path`, `size`, `sha256`, `flags` and `baseline`. A non-null
baseline has exactly `size` and `sha256`; null means an originally absent file.
Output and baseline bytes live in `payloads/<sha256>`. All paths are normalized,
case-sensitive lower-case game-relative identities. A file cannot be silently
omitted or added. Example file record:

```json
{"path":"gamedata/iteminfo.pabgb","size":1024,"sha256":"<64 hex>","flags":0,"baseline":{"size":1024,"sha256":"<64 hex>"}}
```

`bindings` uses the existing identity-profile schema, filtered to exactly these
contributors with `layer:null`. It retains issued values, stems, owned paths and
binding hashes. Import preserves matching reservations and refuses occupied or
different bindings; opaque game-reference relocation is unsupported. Removal
continues through the ordinary retained package and ownership machinery.

`witnesses` has `payloads` and `indexes`, each a list of exactly
`{"path":"<relative path>","size":123,"sha256":"<64 hex>"}`. Payloads name
original game data; indexes name the exact parsed shipped PAMT files. Every
package dependency must agree with a payload witness. Import checks these against
the current stock snapshot and checks the recorded compiler before admission.
Known executable and version-file digests remain pinned through publication.
Executable selection follows the existing archive-parent search; the exact file
and earlier absent candidates are witnessed without allowing its parent folder
as an arbitrary source root.
Supporting composition additionally regenerates the exported contribution from
its original recipes and bindings, checks output agreement, then composes peers
against the witnessed baseline. It does not replay operations against the edited
export. Package content, contributor ownership and exact dependency requirements
survive update, disablement, removal and reinstallation.

Only complete retained independent-package compositions are representable in this
initial contract. Foreign byte-only contributors, unknown compiler versions and
unsupported relocation require explicit refusal. Legacy-only exports retain
their existing format. Synthetic implementation tests do not establish visible
game behavior, save compatibility or support for every mod category.
