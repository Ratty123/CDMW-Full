# cd-texture-dx

DirectXTex-backed DDS preview helper for CDMW.

Build:

```powershell
cmake -S native/cd_texture_dx -B native/cd_texture_dx/build -DCMAKE_BUILD_TYPE=Release
cmake --build native/cd_texture_dx/build --config Release
```

Commands:

```powershell
cd-texture-dx.exe self-test
cd-texture-dx.exe inspect-json path\to\texture.dds
cd-texture-dx.exe batch-preview-json job.json report.json
```

`batch-preview-json` accepts a single JSON file with a `jobs` array. Each job has `input`, `output`, `slot`, `max_dimension`, `srgb`, and `normal_space`. The helper writes all PNG previews and a single report JSON so the Python preview path avoids one `texconv` process per texture.
