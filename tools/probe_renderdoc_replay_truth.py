from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.common import hidden_subprocess_kwargs
from tools.capture_crimson_renderdoc_frame import (
    default_renderdoc_config_path,
    renderdoc_ags_allow_unknown_patch_status,
    temporary_renderdoc_ags_allow_unknown_extensions,
)


SCHEMA_VERSION = 1


def find_qrenderdoc() -> str:
    path = shutil.which("qrenderdoc")
    if path:
        return path
    for candidate in (
        REPO_ROOT / ".tools" / "renderdoc" / "1.44" / "RenderDoc_1.44_64" / "qrenderdoc.exe",
        REPO_ROOT / ".tools" / "renderdoc" / "RenderDoc_1.44_64" / "qrenderdoc.exe",
        Path("C:/Program Files/RenderDoc/qrenderdoc.exe"),
        Path("C:/Program Files (x86)/RenderDoc/qrenderdoc.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return ""


def _json_literal(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def render_qrenderdoc_probe_script(*, capture_path: Path, out_json: Path, max_actions: int = 256) -> str:
    return textwrap.dedent(
        f"""
        import json
        import traceback

        from PySide2.QtCore import QTimer
        from PySide2.QtWidgets import QApplication

        import renderdoc

        CAPTURE_PATH = {_json_literal(capture_path)}
        OUT_JSON = {_json_literal(out_json)}
        MAX_ACTIONS = {int(max(1, max_actions))}

        def _text(value):
            try:
                return str(value)
            except Exception:
                return ""

        def _fields(obj, names):
            out = {{}}
            for name in names:
                try:
                    value = getattr(obj, name)
                    if callable(value):
                        continue
                    out[name] = _text(value)
                except Exception:
                    pass
            return out

        def _method_names(obj):
            names = []
            try:
                names = [name for name in dir(obj) if not name.startswith("_") and callable(getattr(obj, name, None))]
            except Exception:
                names = []
            return sorted(names)

        def _data_attr_names(obj):
            names = []
            try:
                for name in dir(obj):
                    if name.startswith("_"):
                        continue
                    try:
                        if not callable(getattr(obj, name, None)):
                            names.append(name)
                    except Exception:
                        pass
            except Exception:
                names = []
            return sorted(names)

        def _flatten_actions(actions):
            rows = []
            def visit(action, depth):
                if len(rows) >= MAX_ACTIONS:
                    return
                row = _fields(action, [
                    "eventId", "actionId", "customName", "drawcall", "name", "flags",
                    "numIndices", "numInstances", "dispatchDimension", "copyDestination",
                ])
                row["depth"] = depth
                try:
                    row["events"] = [getattr(evt, "eventId", 0) for evt in getattr(action, "events", [])[:16]]
                except Exception:
                    row["events"] = []
                rows.append(row)
                try:
                    children = list(getattr(action, "children", []))
                except Exception:
                    children = []
                for child in children:
                    visit(child, depth + 1)
            for root in actions:
                visit(root, 0)
            return rows

        def _safe_count(callback):
            try:
                return len(callback())
            except Exception:
                return 0

        def _sample_sequence(callback, field_names, limit=32):
            rows = []
            try:
                sequence = list(callback())
            except Exception:
                return rows
            for item in sequence[:limit]:
                rows.append(_fields(item, field_names))
            return rows

        def _write(payload):
            with open(OUT_JSON, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)

        def _quit():
            app = QApplication.instance()
            if app is not None:
                app.quit()

        state = {{"attempts": 0, "loaded": False}}

        def _probe_controller(controller):
            payload = {{
                "schema_version": {SCHEMA_VERSION},
                "status": "replay_probe_ok",
                "capture_path": CAPTURE_PATH,
                "controller_methods": _method_names(controller),
                "root_action_count": _safe_count(controller.GetRootActions),
                "resource_count": _safe_count(controller.GetResources),
                "texture_count": _safe_count(controller.GetTextures),
                "buffer_count": _safe_count(controller.GetBuffers),
                "api_properties": {{}},
                "actions": [],
                "resource_samples": [],
                "texture_samples": [],
                "buffer_samples": [],
                "pipeline_state_methods": [],
                "pipeline_state_attrs": [],
                "pipeline_state_error": "",
            }}
            try:
                api_props = controller.GetAPIProperties()
                payload["api_properties"] = _fields(api_props, ["pipelineType", "localRenderer", "degraded", "shaderDebugging", "pixelHistory"])
            except Exception as exc:
                payload["api_properties_error"] = _text(exc)
            try:
                payload["actions"] = _flatten_actions(controller.GetRootActions())
            except Exception as exc:
                payload["actions_error"] = _text(exc)
            payload["resource_samples"] = _sample_sequence(
                controller.GetResources,
                ["resourceId", "name", "type", "initialisationState", "creationFlags"],
            )
            payload["texture_samples"] = _sample_sequence(
                controller.GetTextures,
                ["resourceId", "name", "width", "height", "depth", "arraysize", "mips", "format", "dimension", "msSamp"],
            )
            payload["buffer_samples"] = _sample_sequence(
                controller.GetBuffers,
                ["resourceId", "name", "length", "structureByteStride", "creationFlags"],
            )
            for action in payload.get("actions", []):
                try:
                    event_id = int(action.get("eventId") or 0)
                except Exception:
                    event_id = 0
                if event_id <= 0:
                    continue
                try:
                    controller.SetFrameEvent(event_id, True)
                    pipe = controller.GetPipelineState()
                    payload["pipeline_state_methods"] = _method_names(pipe)
                    payload["pipeline_state_attrs"] = _data_attr_names(pipe)
                    break
                except Exception as exc:
                    payload["pipeline_state_error"] = _text(exc)
            _write(payload)

        def _attempt_probe():
            state["attempts"] += 1
            if not state["loaded"]:
                try:
                    pyrenderdoc.LoadCapture(CAPTURE_PATH, renderdoc.ReplayOptions(), CAPTURE_PATH, False, True)
                    state["loaded"] = True
                except Exception as exc:
                    _write({{
                        "schema_version": {SCHEMA_VERSION},
                        "status": "load_failed",
                        "capture_path": CAPTURE_PATH,
                        "error": _text(exc),
                        "traceback": traceback.format_exc(),
                    }})
                    _quit()
                    return

            invoked = {{"done": False}}
            def callback(controller):
                invoked["done"] = True
                try:
                    _probe_controller(controller)
                except Exception as exc:
                    _write({{
                        "schema_version": {SCHEMA_VERSION},
                        "status": "probe_failed",
                        "capture_path": CAPTURE_PATH,
                        "error": _text(exc),
                        "traceback": traceback.format_exc(),
                    }})

            try:
                pyrenderdoc.Replay().BlockInvoke(callback)
            except Exception as exc:
                _write({{
                    "schema_version": {SCHEMA_VERSION},
                    "status": "blockinvoke_failed",
                    "capture_path": CAPTURE_PATH,
                    "error": _text(exc),
                    "traceback": traceback.format_exc(),
                }})
                _quit()
                return

            if invoked["done"]:
                _quit()
                return
            if state["attempts"] >= 120:
                _write({{
                    "schema_version": {SCHEMA_VERSION},
                    "status": "replay_timeout",
                    "capture_path": CAPTURE_PATH,
                    "attempts": state["attempts"],
                }})
                _quit()
                return
            QTimer.singleShot(500, _attempt_probe)

        QTimer.singleShot(0, _attempt_probe)
        """
    ).strip() + "\n"


def build_probe_plan(
    *,
    capture_path: Path,
    out_json: Path,
    work_dir: Path,
    qrenderdoc: Path | None = None,
    max_actions: int = 256,
    script_arg: str = "--script",
    allow_amd_unknown_extensions: bool = False,
    renderdoc_config: Path | None = None,
) -> dict[str, object]:
    resolved_qrenderdoc = str(qrenderdoc) if qrenderdoc else find_qrenderdoc()
    work_dir = work_dir.resolve()
    capture_path = capture_path.resolve()
    out_json = out_json.resolve()
    script_path = work_dir / "probe_qrenderdoc_replay.py"
    blockers: list[str] = []
    if not resolved_qrenderdoc or not Path(resolved_qrenderdoc).is_file():
        blockers.append("qrenderdoc_not_found")
    if not capture_path.is_file():
        blockers.append("capture_not_found")
    resolved_renderdoc_config = renderdoc_config or default_renderdoc_config_path()
    renderdoc_config_patch: dict[str, object] = {
        "allow_amd_unknown_extensions": bool(allow_amd_unknown_extensions),
        "path": str(resolved_renderdoc_config),
        "status": "not_requested",
    }
    if allow_amd_unknown_extensions:
        renderdoc_config_patch = {
            "allow_amd_unknown_extensions": True,
            **renderdoc_ags_allow_unknown_patch_status(resolved_renderdoc_config),
        }
        if renderdoc_config_patch.get("status") != "ready":
            blockers.append(str(renderdoc_config_patch.get("blocker", "renderdoc_config_patch_blocked")))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "qrenderdoc": resolved_qrenderdoc,
        "capture_path": str(capture_path),
        "out_json": str(out_json),
        "work_dir": str(work_dir),
        "script_path": str(script_path),
        "script_arg": script_arg,
        "renderdoc_config_patch": renderdoc_config_patch,
        "command": [resolved_qrenderdoc or "qrenderdoc", script_arg, str(script_path)],
        "max_actions": int(max(1, max_actions)),
        "notes": [
            "Uses qrenderdoc UI scripting because bundled RenderDoc has no standalone renderdoc.pyd.",
            "Script loads capture via pyrenderdoc.LoadCapture and reads ReplayController via Replay().BlockInvoke.",
            "Crimson captures using AMD AGS extensions can still be replay-blocked if RenderDoc reports replay hardware lacks AGS support.",
            "Generated script lives under ignored temp work dir.",
        ],
    }


def write_probe_script(plan: Mapping[str, object]) -> None:
    script_path = Path(str(plan["script_path"]))
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        render_qrenderdoc_probe_script(
            capture_path=Path(str(plan["capture_path"])),
            out_json=Path(str(plan["out_json"])),
            max_actions=int(plan.get("max_actions", 256) or 256),
        ),
        encoding="utf-8",
    )


def run_probe(plan: Mapping[str, object], *, timeout_seconds: float) -> dict[str, object]:
    write_probe_script(plan)
    out_json = Path(str(plan["out_json"]))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(part) for part in plan["command"]],
        check=False,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout_seconds)),
        **hidden_subprocess_kwargs(),
    )
    probe_payload: object = {}
    if out_json.is_file():
        try:
            probe_payload = json.loads(out_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            probe_payload = {"status": "probe_json_invalid", "error": str(exc)}
    result = dict(plan)
    result["run_result"] = {
        "returncode": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "probe_payload_status": probe_payload.get("status", "") if isinstance(probe_payload, Mapping) else "",
    }
    result["status"] = "probe_completed" if isinstance(probe_payload, Mapping) and probe_payload else "probe_failed"
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe RenderDoc replay truth through qrenderdoc Python UI scripting.")
    parser.add_argument("--capture", required=True, help="Input .rdc capture path.")
    parser.add_argument("--out-json", required=True, help="Probe output JSON written by qrenderdoc script.")
    parser.add_argument("--out-plan-json", required=True, help="Plan/result JSON for this wrapper.")
    parser.add_argument("--work-dir", default=str(REPO_ROOT / ".tmp_crimson_shader_corpus" / "renderdoc_replay_probe"))
    parser.add_argument("--qrenderdoc", default="")
    parser.add_argument("--max-actions", type=int, default=256)
    parser.add_argument("--script-arg", default="--script", choices=("--script", "--python", "--py", "--ui-script", "--ui-python", "--ui-py"))
    parser.add_argument("--allow-amd-unknown-extensions", action="store_true")
    parser.add_argument("--renderdoc-config", default="")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    plan = build_probe_plan(
        capture_path=Path(args.capture),
        out_json=Path(args.out_json),
        work_dir=Path(args.work_dir),
        qrenderdoc=Path(args.qrenderdoc) if args.qrenderdoc else None,
        max_actions=int(args.max_actions),
        script_arg=str(args.script_arg or "--script"),
        allow_amd_unknown_extensions=bool(args.allow_amd_unknown_extensions),
        renderdoc_config=Path(args.renderdoc_config) if args.renderdoc_config else None,
    )
    out_plan = Path(args.out_plan_json)
    out_plan.parent.mkdir(parents=True, exist_ok=True)
    out_plan.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    if plan["status"] != "ready":
        print(f"RenderDoc replay probe blocked: {', '.join(str(item) for item in plan['blockers'])}", file=sys.stderr)
        return 2
    write_probe_script(plan)
    if not args.run:
        print(f"wrote RenderDoc replay probe plan: {out_plan}")
        return 0
    try:
        with temporary_renderdoc_ags_allow_unknown_extensions(
            bool(args.allow_amd_unknown_extensions),
            Path(args.renderdoc_config) if args.renderdoc_config else None,
        ):
            result = run_probe(plan, timeout_seconds=float(args.timeout_seconds))
    except subprocess.TimeoutExpired:
        result = dict(plan)
        result["status"] = "probe_timeout"
        result["run_result"] = {"timeout_seconds": float(args.timeout_seconds)}
    out_plan.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"replay probe status: {result['status']}")
    return 0 if result["status"] == "probe_completed" else 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
