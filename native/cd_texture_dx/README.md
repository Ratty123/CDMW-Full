# cd-texture-dx

DirectXTex-backed DDS preview helper for CDMW.

Implementation ownership:

- `src/main.cpp` owns COM setup and CLI dispatch only.
- `src/common.cpp` owns shared argument, JSON, diagnostics, and DXGI metadata helpers.
- `src/preview.cpp` owns DDS inspection and PNG preview batches.
- `src/encode.cpp` owns WIC-to-DDS encode batches.
- `src/texture_tool.h` exposes the command surface; `src/texture_tool_internal.h`
  carries only cross-owner implementation contracts.

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

`batch-preview-json` accepts protocol-v2 decode requests with `input`, `output`, `slot`, `normal_space`, `max_dimension`, `requested_mip`, and `output_pixel_type`. `batch-encode-json` accepts explicit DDS format, dimensions, mip count, overwrite, source-color, mip-alpha, coverage-reference, and DDS alpha-metadata policies. The helper writes all outputs and a single report JSON so Python can batch texture work through one native process.

The batch parser is a bounded, allocation-light JSON scanner rather than
`std::regex`; this keeps preview decoding reliable while the main application is
holding a large archive index. `self-test` verifies nested job arrays, escaped
Windows paths, Unicode/surrogate decoding, field aliases, and encode flags.
