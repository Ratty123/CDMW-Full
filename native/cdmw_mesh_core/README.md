# CDMW Mesh Core

Native mesh editing helper for geometry-heavy Mesh Editor operations.

Current commands:

```powershell
cdmw-mesh-core transform-json job.json report.json
cdmw-mesh-core uv-transform-json job.json report.json
cdmw-mesh-core recalculate-normals-json job.json report.json
```

Python keeps the service/session/history boundary and falls back to existing
Python geometry code when this helper is missing or reports an error.
