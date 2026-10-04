# Crimson Desert Mod Workbench

[![Windows build](https://img.shields.io/github/actions/workflow/status/Ratty123/CDMW-Full/windows-build.yml?branch=main&style=flat-square&logo=github&label=Windows%20build)](https://github.com/Ratty123/CDMW-Full/actions/workflows/windows-build.yml)
![version](https://img.shields.io/badge/version-0.11.0--alpha.22-1f6feb?style=flat-square)
![platform](https://img.shields.io/badge/platform-Windows%2011%20x64-555555?style=flat-square)
[![license](https://img.shields.io/badge/license-MIT-brightgreen?style=flat-square)](LICENSE)

A Windows app for creating **Crimson Desert** mods. Browse game assets, create
new equipment, edit meshes and textures, adjust equipment placement, and build
mod packages.

**[Download the Windows portable app](https://github.com/Ratty123/CDMW-Full/releases/latest)**
· [Release history](CHANGELOG.md) · [Report a problem](https://github.com/Ratty123/CDMW-Full/issues)

`0.11.0-alpha.22` is the current source version. For browsing and extraction only,
see the smaller, read-only [CDMW Lite](https://github.com/Ratty123/CDMW-Lite).

## Install

1. Download and run `CrimsonDesertModWorkbench-<version>-windows-portable.exe`.
2. Set the game folder in **Settings > Paths > Archive Locations**.
3. Open **Assets > Browse Archives** to inspect files, or choose a tool below.

The portable app includes its required runtimes and DDS tools. Blender is optional
for FBX import in Create New Item; Real-ESRGAN NCNN and chaiNNer are optional
upscaling tools. Configure these only for workflows that need them.

Settings are stored beside the executable. App-managed files, including caches,
projects and outputs, use the `workspace/` folder.

Generated material textures use `workspace/cache/generated_materials/`. Each run
keeps its textures locked while CDMW is using them. Background maintenance on a
later launch removes abandoned marked runs after a 30-minute grace period and
retries marked preview, Effects and model-import leftovers. The shared cache
budget remains 512 MiB, with a 384 MiB pruning target; active files can exceed
that soft limit.
The latest maintenance summary is `workspace/logs/temp_data_cleanup.json`.

Unmarked legacy folders and inaccessible files are recorded and preserved.
Recovery backups, Mesh Editor baselines, export history, projects and mod outputs
are retained data and are excluded from this cleanup. Some per-user history and
native preferences live in Windows AppData, and short-lived helper files still
use Windows Temp.

## Contents

- [Tools](#tools)
- [Create New Item](#create-new-item)
- [Mesh Editor](#mesh-editor)
- [Placement & Animations](#placement--animations)
- [Bulk texture replacement](#bulk-texture-replacement)
- [Known limitations](#known-limitations)
- [Build from source](#build-from-source)

## Tools

Compact is the default layout. Classic is available in
**Settings > Appearance > Layout**. The table shows the Compact navigation paths.

| Tool | Navigation | Purpose |
|---|---|---|
| **Archive Browser** | Assets > Browse Archives | Find, preview and extract game assets; browse characters with Body & Face Finder. |
| **Create New Item** | Assets > Create New Item | Create equipment from a template, with model, appearance, stats and distribution choices. |
| **Model Library** | Assets > Model Library | Find and preview local or catalogue models, then send them to Create New Item. |
| **Icon Creator** | Assets > Item Icons | Prepare item icons and build compatible replacement packages. |
| **Mesh Editor** | Authoring > Mesh Editor | Edit supported meshes and materials; OBJ/FBX/GLB export, OBJ/FBX/DAE/glTF/GLB import. FBX import uses your selected Blender. |
| **Placement & Animations** | Authoring > Placement & Animations | Adjust equipment attachments and review animation changes before packaging. |
| **Textures** | Authoring > Textures | Edit layered textures, replace files in bulk, recolour, upscale and export. |
| **Mod Management** | Utilities > Mod Management | Preview and manage installed overlays, merge mods and check game-update compatibility. |
| **Retrofit/Repackage** | Utilities > Repackage Mods | Review and convert existing mod folders or ZIPs to supported manager layouts. |
| **Format Explorer** | Utilities > Inspect File Formats | Check which formats and operations are supported. |
| **Translations** | Utilities > Edit Translations | Edit game language tables or existing `.paloc` mods, with optional AI assistance. |
| **Research** | Utilities > Asset Research | Review texture families, classifications, references and quality reports. |
| **Text Search** | Utilities > Search File Text | Search, preview and export archive or loose text files. |

## Documentation and languages

Open **Help > Documentation** for searchable workflow guides. Change the interface
language in **Settings > Appearance**, using a built-in language or a custom pack.
Mesh Editor follows the selected interface language. The **Translations** tool
edits game text separately and can open loose `.paloc` files without a game install.

## Create New Item

Create a distinct equipment item from a shipped template. Keep the template model
or import a replacement, then adjust placement, materials, icons and distribution.
Model variants retain their own appearance settings. Material tools include glow,
translucency and painted transparency; experimental options are labelled.

For an imported model, use **Apply placement** before **Build plan**. Review the
planned files and warnings in **Output**, then create a mod folder or install a
CDMW game overlay. Use **Add to existing mod** to extend a package deliberately;
fresh exports check for unintended inherited custom items.

**Available outputs: CDUMM (default), JMM, DMM and CDMW game overlays.** Use DMM
3.5.0 or newer for new-item packages and check the result in game after mounting.
New mod folders can have a custom name and an optional ZIP copy.

See the [Create New Item guide](cdmw/ui/new_item/README.md) for detailed controls.

## Mesh Editor

Open a supported archive or local mesh, edit with Undo/Redo, then use
**Finish Edit Mesh** to validate and accept the result. **Build Mod** offers DMM,
JMM, CDUMM and Crimson Sharp packages, with an optional ZIP.

Tools include selection, transforms, sculpting, UVs, material controls, cloth and
jiggle settings, Hair Tools, and Morph & Refit for body and garment adjustments.
Availability depends on the source format and selected output; disabled controls
explain their requirements. Hiding a part changes its preview visibility; use the
mod inclusion controls to exclude it from output.

See the [Mesh Editor guide](cdmw/ui/mesh_editor/README.md) for supported edits,
physics controls, draft recovery and output limits.

## Placement & Animations

Adjust where equipment sits and review supported socket or animation replacements.
Use **Prepare preview** to inspect synchronized Before/After playback and check the
proposed file changes. **Build packages** exports the selected operations for
CDUMM, DMM or JMM; it does not install them into the game.

Preview checks do not certify in-game contact, physics or animation behavior.
Unsupported operations and unresolved dependencies are identified before output.

## Bulk texture replacement

For textures edited in another application, open **Authoring > Textures > Replace**:

1. Use **Open Folder** to load edited PNG/DDS files, including subfolders.
2. Choose **Game archives** or a **Local DDS folder**, then **Auto-Match** originals.
   Resolve ambiguous matches explicitly.
3. Review the files and package settings, then **Build Mod**.

After external edits, use **Reload Folder**, match again and rebuild. For in-app
editing, **Textures > Edit** provides layers, masks and adjustments; Recolor and
Upscale share the workspace. **Review & Export** provides the available file and
package outputs.

## Known limitations

- **Experimental authoring needs in-game testing.** This includes Hair Tools,
  generated cloth guides, material/shader experiments, and item stats, perks,
  recipes and rewards. A successful build or preview does not prove game behavior.
- **Transparent surfaces can show visual artifacts when they overlap.** Physics
  and material previews approximate the game; preview tuning is separate from
  saved mesh and physics-profile edits.
- **Format support is operation-specific.** Reading a file does not mean every
  part of it can be edited. Check **Inspect File Formats** or the
  [capability manifest](schemas/archive_content_capabilities.v1.json) for details.

## Safety model

Browsing, previewing, extracting and building mod folders leave game archives
unchanged. Installing overlays or applying supported archive patches requires
confirmation and uses backups and recovery checks. Close the game before installing.

Keep CDMW's overlay history and backup files if you need to disable, rebuild or
remove installed changes. Mod Management provides the supported recovery tools.

## Privacy and support

Archive and editing workflows use local files. Optional online features, including
model catalogues and AI translation, connect to external services. Crash reports
and diagnostic bundles stay local unless you share them.

**Report a Problem...** sits below **Support Me** in the sidebar and is also
available under **Help**. Its five steps cover problem, reproduction, setup,
evidence, then review. Select the tool and affected action;
the input choices, examples and setup questions follow that selection. Stalls ask
about wait time and progress; app-only issues can skip game and mod questions.
Short prompts keep the form compact; **?** buttons provide targeted help. It prepares a
local draft with redacted paths and common credentials, recent tool logs and
activity, detailed worker/helper errors, recent crash or hang reports, application
and helper fingerprints, a bounded folder listing and optional screenshots.
Collection refreshes when you prepare the draft and identifies missing, unreadable
or truncated evidence. Log evidence can be excluded. The review screen has a readable
summary, full report details and fitted screenshots with a full-size option.
Review it before sharing; screenshots can still contain visible personal
information. It does not upload game file contents.

After explicit review and consent, **Send report** opens a browser check, then CDMW
sends the reviewed draft. No GitHub account or private access key is needed. Reports
go through Cloudflare to private GitHub issues in a separate inbox restricted to
the maintainer and invited collaborators. CDMW Full's public source repository does
not make reports public.
Anyone with a complete evidence link can read that one report without signing in;
keep those links in the restricted inbox. Cloud evidence expires after 90 days;
issue summaries and local drafts remain until removed. A failed upload keeps the
draft for retry; **Open draft…** reopens it after restarting. The receiver checks
that the inbox is private, rejects duplicate problems and limits new submissions.
CDMW shows a countdown when it must wait before retrying.

**Help > Export Diagnostics...** and **Help > Copy Latest Problem Summary** remain
available for manual reporting. Review diagnostic bundles before sharing them.
See [Contributing](CONTRIBUTING.md) for bug reports and development, and
[Security](SECURITY.md) for vulnerability reporting.

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

Prepare the helpers before running from a fresh checkout. DDS preview, staging, and rebuild use the bundled `cd-texture-dx.exe` helper.

To build a portable executable:

```powershell
.\build.bat onefile release
```

Output: `dist\CrimsonDesertModWorkbench-<version>-windows-portable.exe`.
Run `build.bat help` for other build modes. Follow the [test guide](tests/README.md)
for focused validation; source tests and packaging checks are separate from
visible UI and in-game testing.

</details>

## License

[MIT](LICENSE). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for bundled
components and their licenses.
