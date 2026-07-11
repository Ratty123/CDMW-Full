from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional


GUI_STARTUP_SMOKE_ENV = "CDMW_GUI_STARTUP_SMOKE"
GUI_STARTUP_SMOKE_RESULT_ENV = "CDMW_GUI_STARTUP_SMOKE_RESULT"


def gui_startup_smoke_requested() -> bool:
    return os.environ.get(GUI_STARTUP_SMOKE_ENV) == "1"


def write_gui_startup_smoke_result(
    *,
    ok: bool,
    stage: str,
    target: str = "",
    detail: str = "",
) -> Optional[Path]:
    result_text = os.environ.get(GUI_STARTUP_SMOKE_RESULT_ENV, "").strip()
    if not result_text:
        return None

    result_path = Path(result_text).expanduser()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_target = target or os.environ.get("CDMW_GUI_STARTUP_SMOKE_TARGET", "").strip() or "default"
    payload: dict[str, object] = {
        "ok": bool(ok),
        "pid": os.getpid(),
        "stage": str(stage),
        "target": str(resolved_target),
    }
    if detail:
        payload["detail"] = str(detail)

    descriptor, temp_name = tempfile.mkstemp(
        dir=result_path.parent,
        prefix=f".{result_path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        temp_path.replace(result_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return result_path


__all__ = [
    "GUI_STARTUP_SMOKE_ENV",
    "GUI_STARTUP_SMOKE_RESULT_ENV",
    "gui_startup_smoke_requested",
    "write_gui_startup_smoke_result",
]
