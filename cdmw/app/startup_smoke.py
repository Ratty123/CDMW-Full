from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

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
    bundled_helpers: Sequence[Mapping[str, object]] | None = None,
    evidence: Mapping[str, object] | None = None,
) -> Path | None:
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
    if bundled_helpers is not None:
        # How the helpers the app ships with itself resolved in this build. A
        # packaged run is the only place that answers the question, because the
        # payload directory and sys._MEIPASS only exist there.
        payload["bundled_helpers"] = [
            {str(key): str(value) for key, value in dict(helper).items()} for helper in bundled_helpers
        ]
        # Keep the shared Rust Mesh Editor/Archive Preview package identity
        # explicit. This must be captured before a one-file process
        # exits because PyInstaller then removes its extraction root.
        try:
            from cdmw.services.bundled_helper_availability import (
                packaged_rust_mesh_editor_resolution_snapshot,
            )

            payload["rust_mesh_editor"] = packaged_rust_mesh_editor_resolution_snapshot()
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            payload["rust_mesh_editor"] = {
                "schema": "cdmw_packaged_rust_mesh_editor_v1",
                "status": "unavailable",
                "reason": f"Mesh Editor packaged evidence failed: {type(exc).__name__}: {exc}",
            }
    if evidence is not None:
        payload["evidence"] = dict(evidence)

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
