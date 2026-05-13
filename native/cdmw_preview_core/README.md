# cdmw-preview-core

Native preview preparation service for CDMW Archive Browser.

Current scope is the service boundary and fast archive preflight used before
falling back to the Python preview path. The next milestones move full
PAM/PAMLOD/PAC geometry preparation and material relationship indexing here.

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

`preview-job` reads a Python-written job file and writes a JSON report. In this
first milestone the service verifies native archive IO/cache inputs and returns
a safe fallback until native geometry generation reaches parity.
