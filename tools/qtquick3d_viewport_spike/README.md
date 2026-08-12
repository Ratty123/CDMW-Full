# Qt Quick 3D viewport spike

An experiment, not a component. It answers one question that decides how much
`native/cdmw_qt_rhi` is worth finishing:

> Can the mesh viewport be an ordinary node in Qt's scene graph, instead of a
> Win32 child window reparented into a Qt widget with `SetParent`?

`native/cdmw_qt_rhi/README.md` records why that seam is worth removing: the
helper stayed parented to a window Qt had destroyed on a monitor move, resizes
arrived by polling, the reveal needed hidden-window choreography, and no Qt
tooltip or popover can ever be drawn across a child window's rectangle.

That module answers it with a hand-written `QQuickRhiItem` in C++, which costs a
pinned Qt version, `GuiPrivate` private headers, MSVC 2022, and a ~2 GB vendored
Qt. **This spike tests whether the public, already-installed `QtQuick3D` module
does the same job with none of that.**

## Results so far

Measured on the development machine, PySide6 6.11.1, Python 3.14.3, D3D11.

| Test | Result |
|---|---|
| **Real PAC** `cd_pgw_00_nude_00_0001`, 13,740 verts / 25,160 tris / 3 submeshes | **174.9 fps**, geometry confirmed on screen |
| Pack 200k interleaved verts, `setVertexData` | **1.45 ms**, 9% of a 16.6 ms frame |
| 199,712 verts / **397,530 triangles**, lit PBR + MSAA, full republish per frame | **164.8 fps** over 2,800 frames, 20.4% pixel coverage |
| Reconstructed view-projection vs `View3D.mapFrom3DScene`, 12 points, off-axis rotated camera | **0.0000 px** max error |
| RSS growth under continuous republishing | **+1.8%** over 4,336 frames |

Real character meshes in this game are around 13.7k vertices. The 200k synthetic
case is therefore roughly a 15x over-stress, and it passes with margin.

The dynamic-geometry memory growth reported against `QQuick3DGeometry`
elsewhere did not reproduce.

Qt UI is composited above the 3D content in the same frame, which is the
capability a child HWND structurally cannot provide.

### A measurement trap worth recording

Earlier runs reported 173-174 fps. Those were wrong. **Declaring a
`PerspectiveCamera` inside a `View3D` does not activate it**; `View3D.camera`
must be assigned explicitly. Without it the scene presents empty frames, which
benchmarks beautifully and proves nothing, and `mapFrom3DScene` returns a null
vector for every point.

The corrected figure is 164.8 fps, and `finish()` now grabs the framebuffer and
reports pixel coverage so an empty scene can never be reported as a pass again.
The picking comparison caught this because Qt's ground truth was all zeros while
the reconstruction was already producing correct values.

### Picking is solved

CDMW must project vertices itself, in bulk, because per-vertex selection over
dense meshes cannot round-trip through QML per pointer sample, and PySide6's
QtQuick3D exports no camera or viewport class. The reconstruction path is:

- read `PerspectiveCamera.sceneTransform`, which **is** readable from Python as a
  `QMatrix4x4`, plus `fieldOfView`, `fieldOfViewOrientation`, `clipNear`, `clipFar`
- invert it for the view matrix, build the projection with
  `QMatrix4x4.perspective`, and convert both with `.data()` reshaped `(4,4)` and
  transposed, because Qt stores column-major
- project in numpy, once per gesture, exactly as the C# renderer already caches

That reproduces Qt's own mapping exactly, so a selection cannot land offset from
the cursor.

### A second measurement trap

An earlier version of this README claimed every `.pac` under `tests/Extracts/`
was a sanitised stub. **That was wrong.** All 34 parse and contain real
geometry.

`parse_mesh(data: bytes, filename: str)` takes **bytes** and dispatches on the
filename's extension. Passing a path as `data` routes to the PAM branch and
reports the path's own first four characters as a bad magic number. Every
`tests/Extracts/...` path begins `test`, which read exactly like a placeholder
payload and produced a confident, wrong conclusion across 34 files at once.

The tell was the identical failure on a game asset: `bad magic 'C:\U'`.

## What is still unproven

- **Per-part selection and picking.** The spike concatenates submeshes into one
  buffer. `QQuick3DGeometry` picking is bounding-volume only, so per-vertex
  picking stays CDMW's own job either way.
- **Partial buffer updates.** Everything here republishes the whole buffer,
  which is the worst case. Qt documents no guarantee for partial updates, so
  they were deliberately not relied upon.
- **Textures, overlays, gizmos, and the grid.** None ported.

## Running it

```powershell
.\.venv\Scripts\python.exe tools\qtquick3d_viewport_spike\viewport_spike.py --pac <path-to-real.pac>
```

```powershell
.\.venv\Scripts\python.exe tools\qtquick3d_viewport_spike\viewport_spike.py --synthetic 200000 --seconds 20
```

Flags: `--seconds N` auto-closes and prints a JSON report, `--report <path>`
writes it, `--no-sculpt` renders statically instead of republishing per frame.

## Scope

Reads assets, never writes them. Lives outside `cdmw/` and imports only the
parser. It is not wired into packaging, `codex_check`, the scenario registry, or
the changelog, and it must not become a dependency of production Edit Mesh.
