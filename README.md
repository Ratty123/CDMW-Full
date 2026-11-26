# Crimson Desert Mod Workbench

[![Windows build](https://img.shields.io/github/actions/workflow/status/Ratty123/CDMW-Full/windows-build.yml?branch=main&style=flat-square&logo=github&label=Windows%20build)](https://github.com/Ratty123/CDMW-Full/actions/workflows/windows-build.yml)
![version](https://img.shields.io/badge/version-0.12.0--alpha.7--hotfix-1f6feb?style=flat-square)
![platform](https://img.shields.io/badge/platform-Windows%2011%20x64-555555?style=flat-square)
[![license](https://img.shields.io/badge/license-MIT-brightgreen?style=flat-square)](LICENSE)

A Windows app for creating **Crimson Desert** mods. Browse game assets, create
new equipment, edit meshes and textures, adjust equipment placement, and build
DMM mod packages.

**[Download for Windows (portable)](https://github.com/Ratty123/CDMW-Full/releases)**
· **[Documentation (Wiki)](https://github.com/Ratty123/CDMW-Full/wiki)**
· [Release history](CHANGELOG.md) · [Research reference](docs/crimson-desert-research.md)
· [Report a problem](https://github.com/Ratty123/CDMW-Full/issues)

`0.12.0-alpha.7-hotfix` is the current source version. For browsing and extraction only,
see the smaller, read-only [CDMW Lite](https://github.com/Ratty123/CDMW-Lite).

## Features

**Assets**
- **[Archive Browser](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-archive-browser)** — Find, preview, and extract game assets, including Body & Face Finder.
- **[Create New Item](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-create-new-item)** — Create equipment from templates or imported models as DMM mods or `.cdmw` packages.
- **[Model Library](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-model-library)** — Preview local or catalogue models and send them to Create New Item.
- **[Icon Creator](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-item-icons)** — Prepare item icons and build compatible replacement packages.

**Authoring**
- **[Mesh Editor](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-mesh-editor)** — Edit meshes, materials, textures, UVs, cloth/physics, hair, and body refits (`OBJ`/`FBX`/`GLB` export; `OBJ`/`FBX`/`DAE`/`glTF`/`GLB` import).
- **[Placement & Animations](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-placement-and-animations)** — Move weapon carry sockets, swap or edit animations, and adjust hand-off timing.
- **[Speed & Prefabs](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-speed-and-prefabs)** *(experimental)* — Tune character action-chart speeds, prefab values, and movement tables as DMM mods.
- **[Textures](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-textures)** — Edit layered textures, replace files in bulk, recolour, upscale, and export DDS.

**Utilities**
- **[Mod Management](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-mod-management)** — List `.cdmw` item packages and send them to DMM.
- **[Format Explorer](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-formats-and-research)** — Check which file formats and edit operations are supported.
- **[Translations](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-translations-and-text-search)** — Edit game language tables or loose `.paloc` files, with optional AI assistance.
- **[Research](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-formats-and-research)** & **[Text Search](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-translations-and-text-search)** — Review texture families and references, or search archive and loose text files.

## Install

1. Download and run `CDMW.exe`. Check **Help > About** or Windows file properties for the version.
2. Set the game folder in **Settings > Paths > Archive Locations**.
3. Open **Assets > Browse Archives** to inspect files, or choose a tool from the workspace sidebar.

The portable app includes its required runtimes and DDS tools. Blender (for FBX import in Create New Item and Mesh Editor) and Real-ESRGAN NCNN / chaiNNer (for upscaling) are optional.

Settings stay beside the executable, and app-managed files (caches, projects, and outputs) use `workspace/`.

## Safety and limitations

- **Never writes into the game folder.** Browsing, previewing, and extracting are read-only; outputs are written as DMM mod folders or `.cdmw` packages sent via **Mod Management**. **Browse Archives > Restore Backup...** and **Remove What an Older CDMW Installed...** ask first before undoing older CDMW installs.
- **DMM-only mod output.** DMM (Definitive Mod Manager) is the supported mod manager after the October 2026 DLC; CDMW game overlays and direct archive patching are disabled.
- **Experimental authoring needs in-game testing.** Hair Tools, generated cloth guides and weapon colliders, material/shader experiments, mesh texture editing, **Speed & Prefabs**, and item stats, perks, recipes, and rewards are experimental; previews approximate the game and do not guarantee in-game behavior.
- **AI connections are experimental.** `Settings > AI connections` lets local AI apps operate CDMW's controls; review every change, test in game, and keep approval prompts on. No AI tool writes into the game folder, and calls log to `workspace\logs\ai-calls.log`. [AI Connections (MCP)](https://github.com/Ratty123/CDMW-Full/wiki/Home#guide-ai-connections) explains what works, how to connect an AI app and what it may do without asking.
- **Format support is operation-specific.** Reading a file does not mean every part of it can be edited; check **Inspect File Formats** or the [capability manifest](schemas/archive_content_capabilities.v1.json).

## Documentation and languages

Workflow guides live on the [GitHub Wiki](https://github.com/Ratty123/CDMW-Full/wiki)
(available in [13 built-in languages](https://github.com/Ratty123/CDMW-Full/wiki/Languages))
and under **Help > Documentation**.

Change the interface language or import a custom language pack in **Settings > Appearance**
(Mesh Editor follows the interface language; **Translations** edits game `.paloc` text separately).
Read the [Crimson Desert research reference](docs/crimson-desert-research.md) for file
formats, findings, evidence levels, and remaining questions.

## Privacy and support

Archive and editing workflows run locally; optional online features such as model
catalogues and AI translation connect to external services, and crash reports or
diagnostic bundles stay local unless you share them.

**Help > Report a Problem...** prepares a redacted local draft and submits through a
browser check to a private inbox (no GitHub account needed, and no game file contents
uploaded); see [problem reporting and privacy](tools/problem_report_receiver/README.md).
**Help > Export Diagnostics...** and **Help > Copy Latest Problem Summary** remain
available for manual reporting. See [Contributing](CONTRIBUTING.md) and
[Security](SECURITY.md).

## Build from source

<details>
<summary>Developer requirements and commands</summary>

Requires Windows 11 x64, Python 3.11 or 3.14, PowerShell, .NET 10 SDK, a CMake/MSVC
C++ toolchain, and Rust through rustup. The [toolchain file](tools/rust_mesh_lab/rust-toolchain.toml)
pins the editor's Rust version. These tools are not required to use the portable app.

From a source checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints-release.txt -r requirements-build.txt
.\.venv\Scripts\python.exe -m pip install "pytest==9.0.3"
.\.venv\Scripts\python.exe scripts\verify_release_dependencies.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_pyside6_app.ps1 -NativeHelpersOnly -BuildProfile release
.\.venv\Scripts\python.exe cdmw_app.py
```

To build a portable executable:

```powershell
.\build.bat onefile release
```

Output: `dist\CDMW.exe`. Run `build.bat help` for other build modes, and follow the
[test guide](tests/README.md) for focused validation.

</details>

## License

[MIT](LICENSE). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for bundled
components and their licenses.
