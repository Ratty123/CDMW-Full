from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

from tools.headless_stress.task_builders import REPO_ROOT, _powershell, _write_json, native_helper_paths


def run_worker_probe(output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import threading

        from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer

        from cdmw.workers.utility_workers import UtilityWorker
    except Exception as exc:
        result = {"status": "skipped", "ok": True, "reason": f"Qt worker probe unavailable: {exc}"}
        _write_json(output_dir / "worker_probe.json", result)
        return result

    app = QCoreApplication.instance() or QCoreApplication(["headless-feature-stress-worker-probe"])
    main_thread_id = threading.get_ident()
    payload: dict[str, Any] = {}
    errors: list[str] = []
    finished: list[bool] = []

    def task(_log: object) -> dict[str, Any]:
        worker_thread_id = threading.get_ident()
        return {
            "main_thread_id": main_thread_id,
            "worker_thread_id": worker_thread_id,
            "off_ui_thread": worker_thread_id != main_thread_id,
        }

    worker = UtilityWorker(task)
    thread = QThread()
    loop = QEventLoop()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.completed.connect(lambda result: payload.update(result if isinstance(result, dict) else {"result": result}))
    worker.error.connect(lambda message: errors.append(str(message)))
    worker.finished.connect(lambda: finished.append(True))
    worker.finished.connect(thread.quit)
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    thread.start()
    loop.exec()
    if thread.isRunning():
        thread.quit()
    thread.wait(1000)
    app.processEvents()

    ok = bool(finished) and bool(payload.get("off_ui_thread")) and not errors
    result = {
        "status": "passed" if ok else "failed",
        "ok": ok,
        "elapsed_s": time.perf_counter() - started,
        "payload": payload,
        "errors": errors,
        "finished": bool(finished),
    }
    _write_json(output_dir / "worker_probe.json", result)
    return result


def run_native_helper_preflight(output_dir: Path, helpers: Sequence[Path] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    required = tuple(Path(path) for path in (helpers if helpers is not None else native_helper_paths()))
    missing_before = [path for path in required if not path.is_file()]
    build_ran = False
    build_result: dict[str, Any] = {}
    stdout_path = output_dir / "build_native_stdout.log"
    stderr_path = output_dir / "build_native_stderr.log"
    if missing_before:
        ps = _powershell()
        script = REPO_ROOT / "build_native_windows.ps1"
        if not ps:
            result = {"status": "failed", "ok": False, "reason": "PowerShell is not available.", "missing_before": missing_before}
            _write_json(output_dir / "native_helper_preflight.json", result)
            return result
        if not script.is_file():
            result = {"status": "failed", "ok": False, "reason": f"Native build script not found: {script}", "missing_before": missing_before}
            _write_json(output_dir / "native_helper_preflight.json", result)
            return result
        completed = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Configuration", "Release"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            shell=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        build_ran = True
        build_result = {"returncode": completed.returncode, "stdout_log": stdout_path, "stderr_log": stderr_path}
    missing_after = [path for path in required if not path.is_file()]
    ok = not missing_after and (not build_ran or build_result.get("returncode") == 0)
    result = {
        "status": "passed" if ok else "failed",
        "ok": ok,
        "elapsed_s": time.perf_counter() - started,
        "build_ran": build_ran,
        "required": required,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "build": build_result,
    }
    _write_json(output_dir / "native_helper_preflight.json", result)
    return result
