# cdmw-preview-core

Native preview preparation service for CDMW Archive Browser.

Current scope is a native PAC fast path plus fallback. The service can now
decode ChaCha20/LZ4 sidecars, reconstruct Partial PAR PAC payloads, recover PAC
submesh geometry, generate D3D11 schema-v4 geometry packages, and preserve
resolved DDS material inputs for the native renderer. PAM/PAMLOD still use the
Python fallback until their table/scan layouts are ported.

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
```

`preview-job` reads a Python-written job file and writes a JSON report. On
supported PAC entries it returns `status=ok` and a package path; otherwise it
returns a safe fallback reason so Python can keep the existing preview path.
