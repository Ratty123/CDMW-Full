# cdmw-preview-core

Native preview/package, archive-name-index, and mesh rebuild service for CDMW.
It decodes archive entries, resolves authoritative material/texture inputs,
prepares schema-v8 material/geometry packages consumed by Rust/D3D12, and emits deterministic reports. Native
preview jobs do not inject synthetic textures or silently enable Python
fallback.

Archive Browser and Create New Item both consume this package contract. A New
Item template request may race bare Python geometry against the native package;
the native result promotes the resident scene to canonical textures without
restarting the renderer or resetting its camera. Character appearance overrides
are read-only presentation clones and are acknowledged in the package report;
they never rewrite the selected PAC or its linked PABC/PAMT sources.

Cold PAMT scans classify entries before constructing archive paths, retain only
the same preview-relevant records, and reuse each PAZ path within a table. XML
classification still uses the complete directory path. These allocation savings
leave the serialized index and material/texture resolution contract unchanged.

For layered Crimson materials, `_colorBlendingMaskTexture` remains a colour-layer
selector rather than a PBR map. Preview packages publish three `color_seed` rows from
the PAC's `_tintColorR/G/B` values; the resident compiler reconstructs those masked
regions before grime/detail overlays, preserves the source fabric's local luminance,
and suppresses the older global-tint approximation. When several logical items share
one physical PAC, the ordered item prefab supplies `_modelPropertyIndex` per model and
the native material reader scopes each `.pac_xml` to that exact `ModelProperty` block;
the first item's index is therefore kept out of every sibling item's cache identity.
The production shader compresses high-energy studio radiance into SDR before tone
mapping instead of multiplying it by a fixed HDR exposure, so bright dye and metal
retain their colour without flattening into white.

`src/main.cpp` is only the executable adapter. Ordered protocol, archive,
geometry, material, package, report, rebuild, index, and command owners live in
`src/owners/`. CMake compiles those owners in one named unity group because the
legacy implementation has translation-unit-private types and helpers. There
are no source-level `.cpp` includes; each owner uses the shared 1,000-line
default ceiling, and each real function stays at or below 150 lines.

## Build

```powershell
cmake -S native/cdmw_preview_core -B native/cdmw_preview_core/build -DCMAKE_BUILD_TYPE=Release
cmake --build native/cdmw_preview_core/build --config Release
```

## Commands

```powershell
cdmw-preview-core.exe self-test
cdmw-preview-core.exe preview-job job.json report.json
cdmw-preview-core.exe --service
cdmw-preview-core.exe mesh-audit-job input.bin report.json [filename]
cdmw-preview-core.exe mesh-parse-job input.bin report.json [filename]
cdmw-preview-core.exe mesh-rebuild-job job.json output.bin report.json
cdmw-preview-core.exe name-index-job input.tsv output.bin report.json [progress.json]
```

`preview-job` reads a Python-written job file and writes a JSON report. On
supported entries it returns `status=ok` and a package path. Unsupported or
unsafe inputs produce an explicit error/fallback reason; callers decide how to
surface that result. Full-CDMW archive-v2 callers also send an authoritative,
bounded `archive_dependency_entries` snapshot. The native core resolves
cross-PAMT basenames and paths from that snapshot and reads its prepared files;
legacy callers retain the Archive Lite basename-index and package-scan fallback.
