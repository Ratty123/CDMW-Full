# Prefab JSON Import

Last reviewed: 2026-07-10

## Purpose

Prefab JSON import lets CDMW export a safe, editable `.prefab` JSON document and
import proven edits back through normal loose mod/package output paths. It must
not mutate game archives directly.

## Ownership

- `cdmw/core/crimson_formats.py`: prefab layout decoding, reference evidence,
  member declarations, descriptor spans, byte-span layout, and same-length string
  rebuild support.
- `cdmw/core/prefab_json.py`: stable compatibility facade. Common coercion,
  document assembly, validation, and application live in the bounded
  `prefab_json_{common,document,validation,apply}.py` owners.
- `cdmw/core/prefab_corpus.py`: stable compatibility facade. Probe values,
  descriptor/offset metrics, sample audit, loose/archive loading, report
  stages, normalized output, merge, and JSON publication live in focused
  `prefab_corpus_*.py` owners capped at 800 lines and 150 lines per function.
- `cdmw/ui/archive_browser/prefab_json_actions.py`: Archive Browser export/import
  actions and loose output handoff.
- `cdmw/ui/archive_browser/binary_sidecar_actions.py`: diagnostic Decode JSON
  export only. Diagnostic sidecars are not importable prefab edit JSON.
- `tools/report_prefab_json_import_corpus.py`: real archive-entry corpus reports
  and sharded/resumable validation.

## Safety Rules

- Import validates source path, source length, SHA-256, format version, and every
  edited row before producing output.
- V1 import only permits proven fixed-size edits. Same-length resource/reference
  edits and supported placement/socket string edits are allowed only when they do
  not move following binary data.
- Length-changing import remains gated off until no-edit rebuilds are
  byte-identical across representative real prefab coverage and all affected
  counts, offsets, alignment, padding, and descriptors are understood.
- Transform value editing, array resizing, and unknown semantic rewrites remain
  disabled unless a later parser/rebuild gate proves them safe.
- Game archives and extracted game payloads are read-only inputs and must not be
  committed.

## Current Capability

- Editable JSON export/import is separate from diagnostic Decode JSON.
- Same-length import and layout no-edit rebuild are ready for the sampled real
  corpus.
- Latest recorded real archive-entry sample found 47,131 `.prefab` entries,
  scanned 1,000, passed 1,000 editable JSON no-edit checks, and passed 1,000
  layout rebuild checks with length-changing import still disabled.
- Corpus reports classify parser capability gates so unsupported edit classes
  fail closed instead of silently producing output.

## Validation

Use focused tests first:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_crimson_formats.py tests/test_prefab_json_import.py tests/test_prefab_corpus.py tests/test_prefab_corpus_tool.py tests/test_prefab_json_actions_source.py tests/test_prefab_decomposition.py --basetemp="$env:TEMP\cdmw-pytest-prefab-json"
```

Optional real archive-entry smoke:

```powershell
.\.venv\Scripts\python.exe tools\report_prefab_json_import_corpus.py --archive --out-json workspace\prefab-json-import\prefab-corpus-100-noedit.json --discovery-limit 100 --no-edit-probes "C:\games\Steam\steamapps\common\Crimson Desert"
```

Run broader Archive Browser checks when UI/package behavior changes:

```powershell
.\scripts\codex_check.ps1 -Area archive
```
