from __future__ import annotations

import os
import threading
import time
from typing import Optional

from cdmw.app.bootstrap_reports import bootstrap_root
from cdmw.app.pyinstaller_runtime import prepare_pyinstaller_runtime_temp_cleanup


_startup_maintenance_thread: Optional[threading.Thread] = None


def prepare_app_temp_cache_cleanup() -> None:
    try:
        from cdmw.core.temp_cache import APP_TEMP_CACHE_ROOT_ENV, app_temp_root, prune_app_temp_cache
        from cdmw.services.workspace_layout import workspace_paths

        legacy_temp_root = app_temp_root()
        os.environ.setdefault(APP_TEMP_CACHE_ROOT_ENV, str(workspace_paths(bootstrap_root())["archive_cache_root"]))
        prune_app_temp_cache()
        prune_app_temp_cache(root=legacy_temp_root)
    except Exception:
        pass


def run_startup_maintenance() -> None:
    prepare_pyinstaller_runtime_temp_cleanup()
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
