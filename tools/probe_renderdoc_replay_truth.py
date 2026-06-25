from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any, Sequence

from tools.capture_crimson_renderdoc_frame import renderdoc_ags_allow_unknown_patch_status


def find_qrenderdoc() -> str:
    local = Path.cwd() / ".tools/renderdoc/1.44/RenderDoc_1.44_64/qrenderdoc.exe"
    if local.is_file():
        return str(local)
    return shutil.which("qrenderdoc") or ""


def render_qrenderdoc_probe_script(*, capture_path: Path, out_json: Path, max_actions: int = 64) -> str:
    return f"""
import json
from qrenderdoc import pyrenderdoc
from PySide6.QtWidgets import QApplication

app = QApplication.instance()
ctx = pyrenderdoc.LoadCapture(r"{Path(capture_path).resolve()}", pyrenderdoc.ReplayOptions(), None)

def probe(controller):
    state = controller.GetPipelineState()
    actions = controller.GetRootActions()[:{int(max_actions)}]
    with open(r"{Path(out_json).resolve()}", "w", encoding="utf-8") as handle:
        json.dump({{"status": "ok", "action_count": len(actions), "pipeline_state": str(state)}}, handle)

pyrenderdoc.Replay().BlockInvoke(probe)
"""


def build_probe_plan(
    *,
    capture_path: Path,
    out_json: Path,
    work_dir: Path,
    qrenderdoc: Path | None = None,
    max_actions: int = 64,
    allow_amd_unknown_extensions: bool = False,
    renderdoc_config: Path | None = None,
) -> dict[str, Any]:
    capture = Path(capture_path).resolve()
    out = Path(out_json).resolve()
    work = Path(work_dir).resolve()
    qrd = Path(qrenderdoc or find_qrenderdoc()).resolve()
    blockers: list[str] = []
    if not capture.is_file():
        blockers.append("capture_not_found")
    if not qrd.is_file():
        blockers.append("qrenderdoc_not_found")
    patch = {"allow_amd_unknown_extensions": bool(allow_amd_unknown_extensions), "status": "not_requested"}
    if allow_amd_unknown_extensions and renderdoc_config:
        patch = {**patch, **renderdoc_ags_allow_unknown_patch_status(Path(renderdoc_config))}
    work.mkdir(parents=True, exist_ok=True)
    script = work / "qrenderdoc_probe.py"
    script.write_text(render_qrenderdoc_probe_script(capture_path=capture, out_json=out, max_actions=max_actions), encoding="utf-8")
    return {
        "status": "blocked" if blockers else "ready",
        "blockers": blockers,
        "capture_path": str(capture),
        "out_json": str(out),
        "script_path": str(script),
        "command": [str(qrd), "--script", str(script)],
        "renderdoc_config_patch": patch,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    plan = build_probe_plan(capture_path=args.capture, out_json=args.out_json, work_dir=args.work_dir)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return 0 if plan["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
