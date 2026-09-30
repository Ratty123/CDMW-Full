from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
import tempfile
import threading
import time
from typing import Optional

from cdmw.app.bootstrap_reports import bootstrap_root
from cdmw.app.pyinstaller_runtime import prepare_pyinstaller_runtime_temp_cleanup
from cdmw.app.startup_splash import cleanup_stale_startup_splash_artifacts


_startup_maintenance_thread: Optional[threading.Thread] = None


def prepare_app_temp_cache_cleanup() -> None:
    try:
        from cdmw.core.temp_cache import APP_TEMP_CACHE_ROOT_ENV, app_temp_root, prune_app_temp_cache
        from cdmw.services.workspace_layout import workspace_paths
        from cdmw.services.temp_data_cleanup import maintain_temp_data

        paths = workspace_paths(bootstrap_root())
        legacy_temp_root = app_temp_root(temp_root=Path(tempfile.gettempdir()))
        os.environ.setdefault(APP_TEMP_CACHE_ROOT_ENV, str(paths["archive_cache_root"]))
        current_root = app_temp_root()
        cache_pruning = {str(root): asdict(prune_app_temp_cache(root=root))
                         for root in dict.fromkeys((current_root, legacy_temp_root))}
        maintain_temp_data(cache_roots=(app_temp_root(), legacy_temp_root),
                           report_path=paths["crash_reports_dir"] / "temp_data_cleanup.json",
                           cache_pruning=cache_pruning)
    except Exception:
        pass


def run_startup_maintenance() -> None:
    prepare_pyinstaller_runtime_temp_cleanup()
    cleanup_stale_startup_splash_artifacts()
    prepare_app_temp_cache_cleanup()


def schedule_startup_maintenance(*, delay_seconds: float = 6.0) -> threading.Thread | None:
    global _startup_maintenance_thread
    if _startup_maintenance_thread is not None and _startup_maintenance_thread.is_alive():
        return _startup_maintenance_thread

    def _worker() -> None:
        try:
            delay = max(0.0, float(delay_seconds))
            if delay:
                time.sleep(delay)
            run_startup_maintenance()
        except Exception:
            pass

    thread = threading.Thread(target=_worker, name="CDMWStartupMaintenance", daemon=True)
    _startup_maintenance_thread = thread
    thread.start()
    return thread
