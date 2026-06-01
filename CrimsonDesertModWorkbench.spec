# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH).resolve()
MODE = os.environ.get("CDMW_PYINSTALLER_MODE", "onefile").strip().lower()
PROFILE = os.environ.get("CDMW_PYINSTALLER_PROFILE", "release").strip().lower()

if MODE not in {"onefile", "onedir"}:
    raise SystemExit(f"Unsupported CDMW_PYINSTALLER_MODE: {MODE!r}")
if PROFILE not in {"release", "fast", "debug"}:
    raise SystemExit(f"Unsupported CDMW_PYINSTALLER_PROFILE: {PROFILE!r}")


def _add_data_if_exists(items, source, destination):
    path = ROOT / source
    if path.exists():
        items.append((str(path), destination))


def _should_collect_numpy_submodule(name):
    parts = name.split(".")
    leaf = parts[-1] if parts else name
    excluded_prefixes = (
        "numpy._pyinstaller",
        "numpy.f2py",
        "numpy.testing",
        "numpy.tests",
        "numpy.typing.tests",
        "numpy.typing.mypy_plugin",
    )
    if any(name == prefix or name.startswith(prefix + ".") for prefix in excluded_prefixes):
        return False
    if "tests" in parts:
        return False
    if leaf.endswith("_tests") or leaf in {"conftest", "testutils"}:
        return False
    return True


datas = []
binaries = []
hiddenimports = []
hiddenimports += [
    "cdmw.rendering.native_d3d11_host",
    "cdmw.rendering.native_preview_package",
]

unused_qt_modules = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
]

_add_data_if_exists(datas, "assets/cdmw.ico", "assets")
_add_data_if_exists(datas, "assets/cdmw.png", "assets")
_add_data_if_exists(datas, "THIRD_PARTY_NOTICES.md", ".")
_add_data_if_exists(datas, "LICENSE", ".")
_add_data_if_exists(datas, "cdmw/modding/VendoredMeshTools_MIT_LICENSE.txt", "third_party")


def _add_native_binary(source, destination, *, required_release=False):
    path = ROOT / source
    if path.exists():
        binaries.append((str(path), destination))
    elif required_release and PROFILE == "release":
        raise SystemExit(f"Required native renderer binary is missing: {path}")


_add_native_binary("native/cd_texture_dx/build/Release/cd-texture-dx.exe", "native", required_release=True)
_add_native_binary("native/cdmw_preview_core/build/Release/cdmw-preview-core.exe", "native", required_release=True)
_add_native_binary("native/cdmw_d3d11_preview/build/Release/cdmw-d3d11-preview.exe", "native", required_release=True)
_add_native_binary("native/cdmw_archive_accelerator/build/Release/cdmw-archive-accelerator.exe", "native")
_add_native_binary("native/cd_hkx/target/release/cd-hkx.exe", "native")
if PROFILE != "release":
    _add_native_binary("native/cd_texture_dx/build/Debug/cd-texture-dx.exe", "native")
    _add_native_binary("native/cdmw_preview_core/build/Debug/cdmw-preview-core.exe", "native")
    _add_native_binary("native/cdmw_d3d11_preview/build/Debug/cdmw-d3d11-preview.exe", "native")
    _add_native_binary("native/cdmw_archive_accelerator/build/Debug/cdmw-archive-accelerator.exe", "native")

vgmstream_dir = ROOT / ".tools" / "vgmstream"
if vgmstream_dir.exists():
    for runtime_file in sorted(path for path in vgmstream_dir.iterdir() if path.is_file()):
        if runtime_file.name == "COPYING":
            datas.append((str(runtime_file), "vgmstream"))
        elif runtime_file.suffix.lower() in {".dll", ".exe"}:
            binaries.append((str(runtime_file), "vgmstream"))

numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all(
    "numpy",
    include_py_files=False,
    filter_submodules=_should_collect_numpy_submodule,
    exclude_datas=[
        "**/tests",
        "**/tests/**",
        "f2py",
        "f2py/**",
        "testing",
        "testing/**",
        "typing/tests",
        "typing/tests/**",
        "typing/mypy_plugin.py",
        "typing/mypy_plugin.pyi",
        "**/*.pyi",
    ],
)
datas += numpy_datas
binaries += numpy_binaries
hiddenimports += numpy_hiddenimports

icon_path = ROOT / "assets" / "cdmw.ico"
hook_path = ROOT / "pyinstaller_hooks"
console_enabled = PROFILE == "debug"

a = Analysis(
    ["cdmw_app.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(hook_path)] if hook_path.exists() else [],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PIL.AvifImagePlugin",
        "PIL._avif",
        *unused_qt_modules,
        "numpy._pyinstaller",
        "numpy.conftest",
        "numpy.f2py",
        "numpy.ma.testutils",
        "numpy.testing",
        "numpy.tests",
        "numpy.typing.tests",
        "numpy.typing.mypy_plugin",
        "pycparser.lextab",
        "pycparser.yacctab",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if MODE == "onefile":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="CrimsonDesertModWorkbench",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=console_enabled,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=[str(icon_path)] if icon_path.exists() else None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="CrimsonDesertModWorkbench",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console_enabled,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=[str(icon_path)] if icon_path.exists() else None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="CrimsonDesertModWorkbench",
    )
