# Qt Quick RHI viewport plugin

The Mesh Editor's 3D viewport is a Win32 child window of a Qt widget, embedded
with `SetParent` through `winId()`. That seam is where most of the editor's
positional defects came from: the helper stayed parented to a window Qt had
destroyed on a monitor move, it learned about resizes by polling and then waited
200ms before acting, and it needed an elaborate hidden-window reveal to avoid
being seen mid-assembly. A child window is also always topmost inside its own
rectangle, so no Qt tooltip, popover or overlay can ever be drawn across the 3D
view.

This module is the replacement: a `QQuickRhiItem` that renders as an ordinary
node inside Qt Quick's scene graph. No embedded window, no shared texture, no
second process. Qt composes the viewport and the interface into a single frame,
and UI can finally sit on top of the model.

## Why this is C++ and not Python

PySide6 exposes the whole `QRhi` surface, and a Python `QQuickRhiItem` does
render: a spike drew ~420 frames in 2.5 seconds through the D3D11 backend. But
the binding has no working ownership story for `QQuickRhiItemRenderer`. Without
a Python reference the renderer is collected and the first frame faults; with
one the process never exits. A viewport that stops the workbench from closing is
worse than the flicker it replaces, so the item lives in C++, where Qt owns the
renderer the way it intends.

## Why the Qt version is pinned

`QQuickRhiItem` is public API, but the `QRhi` calls inside the renderer are not:
`qrhi.h` ships under Qt's `GuiPrivate` module, and Qt excludes private modules
from its binary compatibility promise. Its own build system is explicit:

> This project is using headers of the GuiPrivate module and will therefore be
> tied to this specific Qt module build version. Running this project against
> other versions of the Qt modules may crash at any arbitrary point.

So the plugin is only valid against the exact Qt that loads it, which is the Qt
inside the installed PySide6 wheel. A mismatch does not fail at load; it
corrupts somewhere else later. `CMakeLists.txt` therefore takes
`CDMW_EXPECTED_QT_VERSION` and fails the build outright when the SDK disagrees.

## Building

```powershell
.\scripts\build_qt_rhi_plugin.ps1
```

That asks PySide6 which Qt it ships, vendors that exact version into
`third_party/qt` if it is missing, and configures CMake with the version guard
set. Requires the MSVC 2022 C++ build tools; `py7zr` comes from
`requirements-build.txt`.

`third_party/qt` is deliberately not committed. It is around 2 GB and fully
reproducible from the version PySide6 already pins, and every archive is
verified against the SHA-256 Qt publishes beside it.

## Status

Proof of concept. The item draws a test triangle, which is enough to prove the
architecture end to end: the plugin loads under PySide6, renders through Qt's
D3D11 RHI, composites QML above the 3D content, and lets the process exit.
Porting the actual mesh renderer onto it is the next step and has not started.
