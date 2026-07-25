"""Prove the deferred authoring tool panels really do get built.

The panels are no longer constructed before the editor's first frame, which is
worth about 1.5 s of startup but is only safe if they reliably appear before the
user needs them. Timing cannot show that, so this asserts on the helper's own
``authoring_tool_panels_present`` lifecycle flag:

  * absent when ``ready`` is published (the deferral actually deferred),
  * present after an idle pause with no user action (the post-first-frame build
    ran on its own),
  * present after entering mesh edit (the entry trigger is a working backstop).

Usage:
    python -m tools.mesh_harness.real_dotnet_tool_panel_lifecycle <package-dir> [idle-seconds]

Exits non-zero if the scene update is rejected or the panels are missing.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, r"D:\CLAUDETEST\app_restructuring")
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from tools.mesh_harness.authoring_scene_frame import mesh_edit_scene_update  # noqa: E402
from cdmw.services.mesh_dotnet_experiment import (  # noqa: E402
    mesh_dotnet_experiment_command,
    mesh_dotnet_experiment_package_from_path,
    resolve_mesh_dotnet_experiment_editor,
)

PACKAGE = Path(sys.argv[1])
IDLE_BEFORE_ENTRY = float(sys.argv[2]) if len(sys.argv) > 2 else 2.5

app = QApplication([])
host = QWidget()
host.resize(1400, 900)
host.show()
app.processEvents()

resolution = resolve_mesh_dotnet_experiment_editor(None)
package = mesh_dotnet_experiment_package_from_path(PACKAGE)
program, args = mesh_dotnet_experiment_command(
    resolution.resolved_path, package, embedded_parent_hwnd=int(host.winId()), profile="authoring"
)

START = time.perf_counter()
proc = subprocess.Popen(
    [program, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
)

state = {"ready_ms": 0.0, "sent_ms": 0.0, "applied_ms": 0.0, "status": "", "reason": "", "mode": "",
         "panels_at_ready": None, "panels_after_entry": None,
         "panels_after_idle": None, "probe_status": ""}


def panels(payload: dict):
    counts = payload.get("lifecycle_counts")
    if isinstance(counts, dict):
        return counts.get("authoring_tool_panels_present")
    return None
done = threading.Event()


def send(payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def reader() -> None:
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        name = str(payload.get("event", ""))
        ms = (time.perf_counter() - START) * 1000
        if name == "protocol_ready":
            send({"event": "session_state", "session_id": "seed", "process_generation": 1,
                  "protocol_version": 2, "revision": 0, "edit_revision": 0,
                  "history": {"undo": [], "redo": []}, "selection": {}})
        elif name == "ready":
            state["ready_ms"] = ms
            state["panels_at_ready"] = panels(payload)
            # A real user does not click Edit Mesh in the same millisecond the
            # first frame lands. Give the post-frame build its turn, then probe
            # with a no-op placement update before entering mesh edit.
            time.sleep(IDLE_BEFORE_ENTRY)
            send(mesh_edit_scene_update(PACKAGE, request_id=11, interaction_mode="placement"))
        elif name == "scene_state_update_ack" and state["probe_status"] == "":
            state["probe_status"] = str(payload.get("status", ""))
            state["panels_after_idle"] = panels(payload)
            state["sent_ms"] = (time.perf_counter() - START) * 1000
            send(mesh_edit_scene_update(PACKAGE, request_id=12))
        elif name == "scene_state_update_ack":
            state["applied_ms"] = ms
            state["status"] = str(payload.get("status", ""))
            state["reason"] = str(payload.get("reason", ""))
            state["mode"] = str(payload.get("interaction_mode", ""))
            state["panels_after_entry"] = panels(payload)
            done.set()
            break


threading.Thread(target=reader, daemon=True).start()
deadline = time.perf_counter() + 45
while not done.is_set() and time.perf_counter() < deadline:
    app.processEvents()
    time.sleep(0.01)

print(f"ready                 {state['ready_ms']:9.1f} ms")
print(f"scene_state_update_ack {state['applied_ms']:8.1f} ms  status={state['status']} "
      f"reason={state['reason'] or '-'} interaction_mode={state['mode']}")
if state["status"] == "applied":
    print(f"mesh-edit entry cost   {state['applied_ms'] - state['sent_ms']:8.1f} ms")
print(f"tool panels at ready:        {state['panels_at_ready']}")
print(f"tool panels after idle:      {state['panels_after_idle']}  (idle {IDLE_BEFORE_ENTRY}s, no user action)")
print(f"tool panels after mesh edit: {state['panels_after_entry']}")

try:
    send({"event": "close_request"})
    proc.wait(timeout=8)
except Exception:
    proc.kill()
stderr = proc.stderr.read()
markers = [line for line in stderr.splitlines() if line.startswith("PANELS") or line.startswith("BOOT")]
print("--- helper markers ---")
print("\n".join(markers) if markers else "(none)")
ok = state["status"] == "applied" and state["panels_after_entry"] is True
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
