# cdmw-d3d11-preview

Native isolated D3D11 preview host for CDMW preview packages.

Build:

```powershell
cmake -S native/cdmw_d3d11_preview -B native/cdmw_d3d11_preview/build -DCMAKE_BUILD_TYPE=Release
cmake --build native/cdmw_d3d11_preview/build --config Release
```

Commands:

```powershell
cdmw-d3d11-preview.exe --self-test
cdmw-d3d11-preview.exe --backend d3d11 --preview-package <package-dir> --status-file <status.json>
```

This first native target owns the D3D11 process, status-file protocol, and package-v2 discovery. It is intentionally separate from the former Qt Quick host so native DDS upload can be developed without Qt Quick/OpenGL mixing.
