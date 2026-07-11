# cdmw-preview-core

Native preview/package, archive-name-index, and mesh rebuild service for CDMW.
It decodes archive entries, resolves authoritative material/texture inputs,
prepares schema-v8 D3D11 packages, and emits deterministic reports. Native
preview jobs do not inject synthetic textures or silently enable Python
fallback.

`src/main.cpp` is only the executable adapter. Ordered protocol, archive,
geometry, material, package, report, rebuild, index, and command owners live in
`src/owners/`. CMake compiles those owners in one named unity group because the
legacy implementation has translation-unit-private types and helpers. There
are no source-level `.cpp` includes; each owner is capped at 800 lines and each
real function at 150 lines.

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
surface that result.
