from __future__ import annotations

from pathlib import Path
import re


def hkx_editor_dialog_source(root: Path) -> str:
    owner_root = root / "cdmw" / "ui" / "archive_browser"
    registry = owner_root / "hkx_editor_dialog_owners.py"
    owner_modules = re.findall(
        r"^from cdmw\.ui\.archive_browser import (hkx_editor_dialog_\w+_part_\d+) as ",
        registry.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    paths = (
        owner_root / "hkx_editor_dialog.py",
        owner_root / "hkx_editor_dialog_runtime.py",
        registry,
        *(owner_root / f"{module}.py" for module in owner_modules),
    )
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


__all__ = ["hkx_editor_dialog_source"]
