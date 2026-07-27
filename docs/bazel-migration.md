# Bazel migration status

Bazel builds the shipped `CrimsonDesertModWorkbench.exe` end to end: all five
native C++ helpers, both self-contained .NET publishes, and the PyInstaller
package. `build.bat` is untouched and still works; Bazel is additive.

```bash
.tools/bazel/bazel.exe build //:CrimsonDesertModWorkbench
```

```bash
.tools/bazel/bazel.exe test //native/...
```

Bazel is installed repo-locally in `.tools/bazel/` (the same convention as
`.tools/vgmstream`). There is no system-wide install. `BAZEL_VC` must point at
the VC directory if Bazel cannot auto-detect MSVC.

## The build UI

`.tools/build-ui/cdmw-build.exe` is a WinForms front end: pick a target, press
Build, watch the output stream. It locates the workspace by walking up for
MODULE.bazel, finds the repo-local bazelisk, and sets `BAZEL_VC` itself, so
nothing has to be configured first. Stop kills the whole process tree, because
Bazel spawns compilers that outlive a plain kill.

It covers both build paths, and says which is which:

| Card | Runs |
| --- | --- |
| Build the app | `bazel build //:CrimsonDesertModWorkbench` - fast, skips release checks |
| Release build | `build.bat onefile release` - full gates, publishes to `dist/` |
| Native helpers | `bazel build //:native_helpers` |
| Native tests | `bazel test //native/...` |
| Everything | `bazel build //...` |
| Clean | `bazel clean` |

### The progress bar is real, not a spinner

Both build systems already emit a progress signal; they just do it differently,
and `//tools/dotnet_bazel_launcher/ProgressSignal.cs` reads both:

* `build_pyside6_app.ps1` writes `::progress::<percent>::<stage>` from
  `Write-BuildProgress`. Those lines never appear in the terminal wrapper
  normally used to drive this build, because that wrapper consumes them.
* Bazel writes `[123 / 456] Compiling ...` action counts. The runner passes
  `--curses=no --color=no`, because the curses renderer rewrites lines in place
  and the counter becomes unparseable once captured.

Bazel's denominator grows as the action graph expands, so the bar can move
backwards. That is left as-is: it reflects what the build is actually doing.
A phase with no percentage (`Analyzing`, `Loading`) shows a sweeping band.

### Every size comes from the window's DPI

The UI is laid out in code, and a hardcoded pixel is a bug waiting for a 150%
display. Point-sized fonts are resolved against a DPI this code does not choose,
so on a scaled monitor the glyphs grew while the boxes holding them did not:
headings lost their descenders, card subtitles collided with their titles and
ellipsized, and everything past the second paragraph of a description was
silently cut off.

Three rules keep it honest:

* Fonts are built in pixels from the live DPI (`Theme.UiFont(points, dpi)`), so
  text size and layout are two readings of the same number.
* Anything holding text is measured, never assumed - `Theme.LineHeight`,
  `Theme.TextWidth`, `Theme.WrappedHeight`. The rail is as wide as its widest
  subtitle; the description block is as tall as its text, capped so the console
  keeps the pane.
* `MainForm.ApplyMetrics` re-applies all of it from `DeviceDpi`, and runs again
  on `OnDpiChanged` - dragging the window between a 100% and a 150% display
  re-lays it out. `AutoScaleMode` is `None` on purpose: the framework must not
  scale a second time on top of this.

`Form.CenterToScreen` picks the screen under the pointer, so the window can be
created at one DPI and shown at another. `OnShown` is the first point where the
final DPI is known, which is where the window takes its size.

### Scripts must be invoked by absolute path

This machine sets `NoDefaultCurrentDirectoryInExePath`, so `cmd.exe` does not
search the working directory and a bare `build.bat` is not found - the same
issue commit 391c547b works around for the native builds. `CommandRunner`
anchors the script against the workspace root.

It is itself a Bazel target, built by the same `dotnet_publish` rule as the
shipped .NET helpers:

```bash
.tools/bazel/bazel.exe build //tools/dotnet_bazel_launcher:bazel_launcher_publish
```

Then copy `cdmw-build.exe` out of the publish directory. Known wart: it is
110 MB. `self_contained = False` is set on the target and `--self-contained false`
does reach the SDK, but the publish comes out self-contained anyway - unresolved.

## Measured

| Scenario | Time |
| --- | --- |
| Full `.exe`, cold | 90.8s |
| Full `.exe`, no-op rebuild | 7.6s |
| Native helpers, cold after `bazel clean` | 4.6s |
| Native helpers, no-op | 0.3s |
| One owner source genuinely edited | 3.4s |

`build.bat`'s `release` profile passes `-Clean:($BuildProfile -ne "fast")`, which
deletes every CMake build directory and recompiles all five native projects -
including all of DirectXTex - on every run, then hands PyInstaller `--clean`
plus a work-directory wipe forcing ~37.5s of re-analysis.

## Verified

The Bazel-built executable passes both packaged startup gates via the existing
`scripts/verify_packaged_startup.ps1`:

```
Packaged startup verified: stage=post_construction, target=default
Packaged startup verified: stage=post_construction, target=mesh_builder
```

The Bazel-built `cd-texture-dx.exe` passes its own self-test with full coverage
(`bc7_linear`, `bc7_srgb`, `separate_alpha`, `preserve_coverage`, `selected_mip`,
`gray16`), which is what proves the fxc-compiled shaders are correct.

`//native/cdmw_full_archive_core:cdmw-full-archive-core-self-test` runs under
`bazel test` and links the real shipped DLL, not a static copy.

## Layout

| Piece | Target |
| --- | --- |
| Texture helper | `//native/cd_texture_dx:cd-texture-dx` |
| Archive accelerator | `//native/cdmw_archive_accelerator:cdmw-archive-accelerator` |
| Full archive core | `//native/cdmw_full_archive_core:cdmw-full-archive-core.dll` |
| Preview core | `//native/cdmw_preview_core:cdmw-preview-core` |
| Mesh core | `//native/cdmw_mesh_core:cdmw-mesh-core` |
| .NET Mesh Editor | `//tools/dotnet_mesh_editor_experiment:mesh_editor_publish` |
| .NET archive worker | `//tools/dotnet_archive_backend:worker_publish` |
| Packaged app | `//:CrimsonDesertModWorkbench` |

## Things that bit, and why they are worth knowing

### `workspace/` collides with Bazel's WORKSPACE marker

This repo has a runtime directory named `workspace/` at its root. Windows is
case-insensitive, so Bazel's probe for a legacy `WORKSPACE` **file** opens that
**directory** and fails with `Access is denied`. `.bazelrc` sets
`common --noenable_workspace`. Re-enabling the legacy file breaks the build until
that directory is renamed.

### The unity build had to be reimplemented

`cdmw_preview_core` and `cdmw_mesh_core` set `UNITY_BUILD_MODE GROUP` with custom
pre-include code that opens a namespace. Their owner sources are **not standalone
translation units** - compiled individually they do not build at all.
`//build_defs:unity.bzl` regenerates the same concatenation with
`ctx.actions.write` (not a `genrule`, which wants a shell Bazel cannot find
here). The owner sources reach the compiler through `textual_hdrs`; listing them
in `srcs` would make Bazel compile each alone.

### Bazel found an undeclared header dependency

`preview_core_internal.hpp` includes `../../common/native_diagnostics.h`, which
no CMakeLists declares - it works only because relative includes resolve against
the source tree. `//native/common:native_diagnostics` now makes it explicit.

### `BaseIntermediateOutputPath` is a global MSBuild property

Redirecting it to keep `obj/` out of the source tree pushed *every*
`ProjectReference` into the **same** `obj/`, so the generated `AssemblyInfo.cs`
files collided with `CS0579` duplicate-attribute errors - and referenced projects
still wrote `bazel-out/` directories into the source tree. `--artifacts-path`
gives each project its own subdirectory and is the correct mechanism.

### NuGet needs `USERPROFILE`

Bazel scrubs the action environment, and the .NET SDK fails restore with a bare
`Value cannot be null. (Parameter 'path1')` when `USERPROFILE`/`APPDATA` are
missing. `.bazelrc` passes them through with `--action_env`.

## Deviations from the CMake/PowerShell build

* **`DirectXTexD3D12.cpp` is not compiled.** It needs `d3dx12.h` from the separate
  DirectX-Headers package, and `cd-texture-dx` references no D3D12 symbol
  anywhere, so CMake compiles a translation unit nothing in this tool calls. Add
  DirectX-Headers if a caller ever needs the D3D12 compression path.
* **The Bazel `.exe` is ~2.8 MB larger** than the PowerShell one (226.9 MB vs
  224.1 MB). Both pass the startup gates. The cause is not yet identified and is
  worth pinning down before Bazel becomes the release path.

## Non-hermetic edges

Deliberate, and all in one place. Each is an absolute host path:

* MSVC via `BAZEL_VC`
* `fxc.exe` from the Windows SDK (`//build_defs:hlsl.bzl`)
* `dotnet.exe` from the .NET SDK (`//build_defs:dotnet.bzl`)
* the build venv interpreter (`//build_defs:pyinstaller.bzl`) - PyInstaller must
  run under the exact interpreter whose site-packages get bundled

Pinning these properly means repository rules that discover each toolchain.

## What Bazel does NOT do yet

`bazel build //:CrimsonDesertModWorkbench` produces the executable. It does
**not** run the release validation `build.bat` runs around it:

* the release dirty-tree preflight
* embedded archive member validation (568 members)
* the packaged helper sha256 check
* the full archive backend synthetic probes
* the packaged startup smokes (run manually above)
* moving the result to `dist/` under its versioned release name

Until those are ported, Bazel is the fast inner loop and `build.bat release`
remains the release gate.

## Interaction with the existing build

`scripts/release_preflight.py` classifies untracked files by suffix, and
`.bazel` / `.bzl` / `.bazelrc` are not in its `SOURCE_SUFFIXES`, so Bazel files
land in `other_dirty`, which is not a blocker. Verified `ok: true`.

`.bazel/` (convenience junctions) is gitignored. The output base lives at
`D:/bazel_cdmw`, outside the repo, so Bazel never scans its own output.
