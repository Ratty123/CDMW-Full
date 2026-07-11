# cdmw-d3d11-preview

Native isolated D3D11 preview host for CDMW preview packages.

Build:

```powershell
cmake -S native/cdmw_d3d11_preview -B native/cdmw_d3d11_preview/build
cmake --build native/cdmw_d3d11_preview/build --config Release
```

Commands:

```powershell
cdmw-d3d11-preview.exe --self-test
cdmw-d3d11-preview.exe --backend d3d11 --preview-package <package-dir> --status-file <status.json>
cdmw-d3d11-preview.exe --hidden --backend d3d11 --preview-package <package-dir> --status-file <status.json>
```

`--hidden` creates a non-visible host window for headless package/protocol
validation. Status JSON updates use atomic replacement, so readers never see a
partially rewritten event.

This target owns the isolated D3D11 process, status-file protocol, and preview
package schemas 1 through 10. It remains separate from the former Qt Quick host
so native DDS upload has one renderer state owner.

`src/main.cpp` is only the executable entry point. Public declarations and
shared internal types live in `src/*.hpp`; protocol, package/material loading,
renderer lifecycle, resources, drawing, picking, interaction, sparse mesh
updates, command dispatch, cloth, and application hosting live in normal
`src/owners/*.cpp` sources. CMake composes those owners through one named unity
group in dependency order. Owners do not include one another. The decomposition
gate limits every owner/header to 800 lines and each real function to 150 lines.

Focused validation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_native_d3d11_preview_decomposition.py tests/test_native_preview_core.py
native\cdmw_d3d11_preview\build\Release\cdmw-d3d11-preview.exe --self-test
```
