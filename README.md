# Crimson Desert Mod Workbench

Windows desktop workbench for Crimson Desert archive browsing, texture workflows,
mesh preview/modding, material replacement, media preview, and research tooling.

Latest release: `0.10.0-alpha.1`

- Download: [GitHub Releases](https://github.com/Ratty123/crimson-desert-mod-workbench/releases)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security: [SECURITY.md](SECURITY.md)

## Known Limitations

`Weapon Placement Studio` is currently disabled in the UI. This is intentional,
not just unfinished polish: in-game testing showed that the true 1H/offhand and
full behavior-swap paths need more than partial ItemInfo/PAAC edits and can hang
or crash the game. The embedded D3D11 placement preview is also disabled because
the host can freeze the app. The repo still keeps the learned socket templates,
CTF smoke checks, and [placement tuning guide](docs/placement_piece_tuning_guide.md)
for manual package work, but the studio is not shipped as a supported workflow.

## Features

- Browse `.pamt` / `.paz` archives with flat/tree views, filters, extraction,
  cache reuse, text preview, media preview, and explicit patch/restore flows.
- Preview supported `.pam`, `.pamlod`, and `.pac` meshes with the native D3D11
  preview path, referenced texture inspection, OBJ/FBX export, and supported
  OBJ/DAE/glTF/GLB import preview workflows.
- Run DDS texture workflows with native DirectX helpers, optional `texconv`
  fallback, optional Real-ESRGAN NCNN/chaiNNer upscaling, texture policy
  planning, compare review, and mod-package export.
- Replace edited PNG/DDS textures using the original game DDS as rebuild
  authority, including package-prefixed loose output and manager metadata.
- Edit visible textures in-app with layered projects, selections, masks,
  adjustment layers, channel locks, brush tools, clone/heal, smudge, sharpen,
  soften, and flattened PNG export.
- Build and audit material/mesh replacement packages with Material Authority,
  source-owned material routing, runtime XML preservation, diagnostics, and
  final package preview.
- Use supporting workspaces for Model Library, Mesh Editor, Icon Creator,
  Recolor Variants, Texture Research, Text Search, settings/profile export,
  diagnostic bundles, and detachable tabs.

## Safety Model

Archive mutation is explicit. Browsing, previewing, extracting, scanning, and
package building do not silently rewrite game archives. Supported archive patch
flows use confirmation, preflight checks, backups, and restore support.

Keep local game archives, extracted assets, DDS payloads, build output, crash
reports, restore points, and corpus data out of source control.

## Install

1. Download the latest Windows portable EXE from
   [Releases](https://github.com/Ratty123/crimson-desert-mod-workbench/releases).
2. Run `CrimsonDesertModWorkbench-<version>-windows-portable.exe`.
3. In `Texture Workflow > Setup`, initialize a workspace and configure roots.
4. Use bundled native DDS helpers by default. Configure external tools only if
   needed:
   - `texconv.exe` as a legacy DDS fallback
   - Real-ESRGAN NCNN for direct upscaling
   - chaiNNer for existing `.chn` chains

Portable state is stored beside the EXE, including config, logs, archive caches,
research notes, and diagnostic data.

## Source Setup

Requirements:

- Windows
- Python 3.11+
- PowerShell
- CMake/MSVC toolchain for native helper builds

Install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run the app from source:

```powershell
.\.venv\Scripts\python.exe cdmw_app.py
```

## Build

Build a publishable onefile EXE:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_pyside6_app.ps1 -Mode onefile -BuildProfile release
```

Expected output:

```text
dist\CrimsonDesertModWorkbench-<version>-windows-portable.exe
```

Build a folder/onedir package:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_pyside6_app.ps1 -Mode onedir -BuildProfile release
```

Useful wrappers:

- `build.bat onefile release`
- `build.bat onedir release`
- `build.bat` for the graphical build picker

## Project Layout

- `cdmw/` - application code
- `cdmw/core/` - archive, DDS, workflow, package, and research logic
- `cdmw/modding/` - mesh/material replacement and import/export logic
- `cdmw/rendering/` - native preview packaging, D3D11 host integration, capture tools
- `cdmw/ui/` - PySide6 UI surfaces
- `native/` - C++/Rust native helpers
- `tests/` - behavior and source-guard tests
- `tools/` - audit, capture, build, and research utilities
- `docs/` - focused guides and reverse-engineering notes

## Privacy

The app does not include telemetry, analytics, auto-update checks, or background
network calls for normal offline use. It opens external pages only from explicit
user actions such as download/help links.

## License

See [LICENSE](LICENSE).
