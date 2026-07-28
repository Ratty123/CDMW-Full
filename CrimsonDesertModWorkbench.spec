# -*- mode: python ; coding: utf-8 -*-
import importlib.util
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules


ROOT = Path(SPECPATH).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cdmw.build_metadata import write_windows_version_resource

MODE = os.environ.get("CDMW_PYINSTALLER_MODE", "onefile").strip().lower()
PROFILE = os.environ.get("CDMW_PYINSTALLER_PROFILE", "release").strip().lower()
NATIVE_CONFIGURATION = "Debug" if PROFILE == "debug" else "Release"
version_info_path = write_windows_version_resource(ROOT / "build" / "pyinstaller-version-info.txt")

if MODE not in {"onefile", "onedir"}:
    raise SystemExit(f"Unsupported CDMW_PYINSTALLER_MODE: {MODE!r}")
if PROFILE not in {"release", "fast", "debug"}:
    raise SystemExit(f"Unsupported CDMW_PYINSTALLER_PROFILE: {PROFILE!r}")

legacy_renderer_payloads = tuple(
    ROOT.rglob("cdmw-d3d11-preview.exe")
)
if legacy_renderer_payloads:
    rendered = ", ".join(str(path) for path in legacy_renderer_payloads)
    raise SystemExit(
        "Retired cdmw-d3d11-preview.exe payload must not be present: " + rendered
    )


def _add_data_if_exists(items, source, destination):
    path = ROOT / source
    if path.exists():
        items.append((str(path), destination))


def _add_data_tree_if_exists(items, source, destination, *, suffixes=None):
    root = ROOT / source
    if not root.exists():
        return
    allowed_suffixes = {suffix.lower() for suffix in suffixes} if suffixes is not None else None
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if allowed_suffixes is not None and path.suffix.lower() not in allowed_suffixes:
            continue
        relative_parent = Path(destination) / path.relative_to(root).parent
        items.append((str(path), str(relative_parent)))


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
hiddenimports += collect_submodules("cdmw")
# The Placement Studio tool tab lives under tools/, which is a package but is not covered by
# the cdmw sweep. Without this the tab imports fine from source and fails only in a frozen
# build — the worst possible place to find out.
hiddenimports += collect_submodules("tools.placement_studio")
hiddenimports += [
    "cdmw.rendering.ingame_capture",
    "cdmw.rendering.preview_comparison",
    "cdmw.rendering.test_run_sword_tuning",
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

unused_qt_runtime_payloads = {
    "PySide6\\Qt6Pdf.dll",
    "PySide6\\Qt6Qml.dll",
    "PySide6\\Qt6QmlMeta.dll",
    "PySide6\\Qt6QmlModels.dll",
    "PySide6\\Qt6QmlWorkerScript.dll",
    "PySide6\\Qt6Quick.dll",
    "PySide6\\Qt6VirtualKeyboard.dll",
    "PySide6\\plugins\\imageformats\\qpdf.dll",
    "PySide6\\plugins\\platforminputcontexts\\qtvirtualkeyboardplugin.dll",
}

# The .NET mesh editor loads this shader compiler from its own directory, where
# _add_native_binary_tree already places it. PyInstaller's dependency scan hoists
# a second identical copy to the bundle root that nothing ever loads.
duplicate_runtime_payloads = {
    "D3DCompiler_47_cor3.dll",
}

# The app never installs a QTranslator, so the bundled Qt message catalogues can
# never be loaded.
#
# The second entry is the same idea for OpenImageIO. Following oiiotool.exe's
# imports makes PyInstaller re-collect its DLLs at their package-relative
# OpenImageIO\bin\, 15 MB on top of the copy the openimageio/ payload already
# places beside the executable. oiiotool loads them from its own directory, and
# the OpenImageIO Python module is not bundled, so nothing can open the second
# copy.
unused_payload_prefixes = (
    "PySide6\\translations\\",
    "OpenImageIO\\bin\\",
)


def _toc_entry_name(entry):
    if not isinstance(entry, tuple) or not entry:
        return ""
    return str(entry[0]).replace("/", "\\")


def _exclude_collected_payloads(entries, names):
    blocked = {name.casefold() for name in names}
    return [entry for entry in entries if _toc_entry_name(entry).casefold() not in blocked]


def _exclude_collected_prefixes(entries, prefixes):
    blocked = tuple(prefix.casefold() for prefix in prefixes)
    return [
        entry
        for entry in entries
        if not _toc_entry_name(entry).casefold().startswith(blocked)
    ]

_add_data_if_exists(datas, "assets/cdmw.ico", "assets")
_add_data_if_exists(datas, "assets/cdmw.png", "assets")
_add_data_tree_if_exists(datas, "assets/theme_icons", "assets/theme_icons", suffixes={".ico", ".png"})
_add_data_tree_if_exists(datas, "schemas", "schemas", suffixes={".json"})
_add_data_if_exists(datas, "THIRD_PARTY_NOTICES.md", ".")
_add_data_if_exists(datas, "LICENSE", ".")
_add_data_if_exists(datas, "cdmw/modding/VendoredMeshTools_MIT_LICENSE.txt", "third_party")


def _add_native_binary(source, destination, *, required_release=False):
    path = ROOT / source
    if path.exists():
        binaries.append((str(path), destination))
    elif required_release and PROFILE == "release":
        raise SystemExit(f"Required native binary is missing: {path}")


def _add_native_binary_tree(source, destination, *, required_release=False, suffixes=None):
    root = ROOT / source
    if not root.exists():
        if required_release and PROFILE == "release":
            raise SystemExit(f"Required native payload directory is missing: {root}")
        return
    allowed_suffixes = {suffix.lower() for suffix in suffixes} if suffixes is not None else None
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if allowed_suffixes is not None and path.suffix.lower() not in allowed_suffixes:
            continue
        relative_parent = Path(destination) / path.relative_to(root).parent
        binaries.append((str(path), str(relative_parent)))


_add_native_binary(f"native/cd_texture_dx/build/{NATIVE_CONFIGURATION}/cd-texture-dx.exe", "native", required_release=True)
_add_native_binary(f"native/cdmw_preview_core/build/{NATIVE_CONFIGURATION}/cdmw-preview-core.exe", "native", required_release=True)
_add_native_binary(
    f"native/cdmw_archive_accelerator/build/{NATIVE_CONFIGURATION}/cdmw-archive-accelerator.exe",
    "native",
    required_release=True,
)
_add_native_binary(f"native/cdmw_mesh_core/build/{NATIVE_CONFIGURATION}/cdmw-mesh-core.exe", "native", required_release=True)
_add_native_binary_tree(
    f"native/cdmw_mesh_dotnet_editor/build/{NATIVE_CONFIGURATION}",
    "native",
    required_release=(ROOT / "tools" / "dotnet_mesh_editor_experiment" / "Cdmw.MeshEditorExperiment.csproj").exists(),
    suffixes={".exe", ".dll", ".json"},
)
_add_native_binary_tree(
    f"native/cdmw_full_archive_backend/build/{NATIVE_CONFIGURATION}",
    "archive_backend",
    required_release=True,
    suffixes={".exe", ".dll", ".json"},
)
_add_data_if_exists(
    datas,
    f"native/cdmw_mesh_dotnet_editor/build/{NATIVE_CONFIGURATION}/D3D11MaterialShaders.hlsl",
    "native",
)
_add_native_binary("native/cd_hkx/target/release/cd-hkx.exe", "native")

# Audio decoding shells out to vgmstream-cli.exe. The Winamp (in_vgmstream) and
# XMPlay (xmp-vgmstream) player plugins in the same directory are unusable here.
unused_vgmstream_payloads = {
    "in_vgmstream.dll",
    "xmp-vgmstream.dll",
}

vgmstream_dir = ROOT / ".tools" / "vgmstream"
if vgmstream_dir.exists():
    for runtime_file in sorted(path for path in vgmstream_dir.iterdir() if path.is_file()):
        if runtime_file.name.casefold() in {name.casefold() for name in unused_vgmstream_payloads}:
            continue
        if runtime_file.name == "COPYING":
            datas.append((str(runtime_file), "vgmstream"))
        elif runtime_file.suffix.lower() in {".dll", ".exe"}:
            binaries.append((str(runtime_file), "vgmstream"))

# OpenImageIO ships as a wheel whose console script in Scripts/ is only a
# launcher shim. The real oiiotool lives in the package's own bin/ and loads its
# DLL closure from that directory, so the tool and the DLLs travel together or
# not at all. idiff and maketx sit in the same directory and CDMW invokes
# neither. The wheel's lib/*.lib are import libraries for building against
# OpenImageIO, and share/fonts serves oiiotool's text drawing, which CDMW does
# not use; taking bin/*.{exe,dll} alone leaves all three behind.
unused_openimageio_tools = {
    "idiff.exe",
    "maketx.exe",
}


def _openimageio_package_root():
    try:
        module_spec = importlib.util.find_spec("OpenImageIO")
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if module_spec is None:
        return None
    for location in tuple(getattr(module_spec, "submodule_search_locations", ()) or ()):
        if not str(location or "").strip():
            continue
        root = Path(location)
        if (root / "bin" / "oiiotool.exe").is_file():
            return root
    return None


openimageio_root = _openimageio_package_root()
if openimageio_root is not None:
    blocked_openimageio = {name.casefold() for name in unused_openimageio_tools}
    for runtime_file in sorted(path for path in (openimageio_root / "bin").iterdir() if path.is_file()):
        if runtime_file.name.casefold() in blocked_openimageio:
            continue
        if runtime_file.suffix.lower() in {".dll", ".exe"}:
            binaries.append((str(runtime_file), "openimageio"))
    # Apache-2.0 with small BSD-3-Clause portions; redistribution carries both.
    for notice_name in ("LICENSE.md", "THIRD-PARTY.md"):
        notice = next(
            iter(sorted(openimageio_root.parent.glob(f"openimageio-*.dist-info/licenses/{notice_name}"))),
            None,
        )
        if notice is not None:
            datas.append((str(notice), "openimageio"))
elif PROFILE == "release":
    raise SystemExit(
        "OpenImageIO is bundled in release builds but its package was not found. "
        "Install it into the build environment: .\\.venv\\Scripts\\python.exe -m pip install openimageio"
    )

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
a.binaries = _exclude_collected_payloads(a.binaries, unused_qt_runtime_payloads)
a.datas = _exclude_collected_payloads(a.datas, unused_qt_runtime_payloads)
a.binaries = _exclude_collected_payloads(a.binaries, duplicate_runtime_payloads)
a.datas = _exclude_collected_payloads(a.datas, duplicate_runtime_payloads)
a.binaries = _exclude_collected_prefixes(a.binaries, unused_payload_prefixes)
a.datas = _exclude_collected_prefixes(a.datas, unused_payload_prefixes)
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
        version=str(version_info_path),
        uac_admin=False,
        uac_uiaccess=False,
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
        version=str(version_info_path),
        uac_admin=False,
        uac_uiaccess=False,
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
