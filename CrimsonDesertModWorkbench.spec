# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH).resolve()


def _add_data_if_exists(items, source, destination):
    path = ROOT / source
    if path.exists():
        items.append((str(path), destination))


datas = []
binaries = []
hiddenimports = []

_add_data_if_exists(datas, "assets/cdmw.ico", "assets")
_add_data_if_exists(datas, "assets/cdmw.png", "assets")
_add_data_if_exists(datas, "THIRD_PARTY_NOTICES.md", ".")
_add_data_if_exists(datas, "LICENSE", ".")
_add_data_if_exists(datas, "cdmw/modding/VendoredMeshTools_MIT_LICENSE.txt", "third_party")

vgmstream_dir = ROOT / ".tools" / "vgmstream"
if vgmstream_dir.exists():
    for runtime_file in sorted(path for path in vgmstream_dir.iterdir() if path.is_file()):
        if runtime_file.name == "COPYING":
            datas.append((str(runtime_file), "vgmstream"))
        elif runtime_file.suffix.lower() in {".dll", ".exe"}:
            binaries.append((str(runtime_file), "vgmstream"))

tmp_ret = collect_all(
    "numpy",
    filter_submodules=lambda name: not (
        name.startswith("numpy.f2py.tests")
        or name.startswith("numpy._pyinstaller.tests")
    ),
)
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

icon_path = ROOT / "assets" / "cdmw.ico"
hook_path = ROOT / "pyinstaller_hooks"

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
        "numpy.f2py.tests",
        "numpy._pyinstaller.tests",
        "pycparser.lextab",
        "pycparser.yacctab",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(icon_path)] if icon_path.exists() else None,
)
