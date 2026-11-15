"""Shipped code imports only the third-party packages the release carries (P16 stage 2, P20).

The plan's rule: no new import of cv2, OpenImageIO, cryptography, QtMultimedia or
QtNetwork. cv2 is confined to cdmw/core/image_ops.py and Qt Multimedia to the
preview widget; the rest are not imported at all. Anything else outside the
standard library and the release requirements fails here, so a retired package
cannot come back unnoticed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SHIPPED = (Path("cdmw_app.py"), Path("cdmw"), Path("tools/placement_studio"), Path("tools/translation_studio"))
# Top-level names the release requirements provide, plus our own packages and PyInstaller's splash.
ALLOWED = {"PySide6", "shiboken6", "numpy", "PIL", "lz4", "cv2", "cdmw", "tools", "pyi_splash"}
CONFINED = {
    "cv2": {"cdmw/core/image_ops.py"},
    "PySide6.QtMultimedia": {"cdmw/ui/preview_widgets.py"},
    "PySide6.QtMultimediaWidgets": {"cdmw/ui/preview_widgets.py"},
}
NEVER = {"cryptography", "cffi", "pycparser", "OpenImageIO", "py7zr", "PySide6.QtNetwork", "PySide6.QtOpenGL",
         "PySide6.QtOpenGLWidgets"}


def _imports():
    for root in SHIPPED:
        for path in [root] if root.suffix == ".py" else sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
                else:
                    continue
                for name in names:
                    yield path.as_posix(), node.lineno, name


# Known exceptions, each with its reason. The device-test runner of the virtual
# loader imports the developer-only `scripts` package, which the release does not
# carry; it runs only from scripts/run_cditem_device_tests.py, and its removal
# belongs to the thread retiring the virtual loader.
KNOWN = {("cdmw/services/cditem_device_windows.py", "scripts")}


def test_shipped_code_imports_only_the_standard_library_and_the_release_packages():
    standard = set(sys.stdlib_module_names) | {"__future__"}
    unknown = sorted(
        f"{path}:{line}: {name}" for path, line, name in _imports()
        if name.split(".", 1)[0] not in standard and name.split(".", 1)[0] not in ALLOWED
        and (path, name.split(".", 1)[0]) not in KNOWN
    )
    assert unknown == []


def test_retired_packages_are_not_imported_and_confined_ones_stay_in_their_module():
    offenders = []
    for path, line, name in _imports():
        for retired in NEVER:
            if name == retired or name.startswith(retired + "."):
                offenders.append(f"{path}:{line}: {name}")
        for confined, owners in CONFINED.items():
            if (name == confined or name.startswith(confined + ".")) and path not in owners:
                offenders.append(f"{path}:{line}: {name} outside {sorted(owners)}")
    assert offenders == []
