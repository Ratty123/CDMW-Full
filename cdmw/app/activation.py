from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time


APP_ACTIVATION_REQUEST_FILE_NAME = "activate_existing.json"


def existing_instance_activation_request_path() -> Path:
    return Path(tempfile.gettempdir()) / "CrimsonDesertModWorkbench" / APP_ACTIVATION_REQUEST_FILE_NAME


def request_existing_instance_activation() -> None:
    try:
        request_path = existing_instance_activation_request_path()
        request_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "executable": str(Path(sys.executable).resolve()),
        }
        temp_path = request_path.with_suffix(request_path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temp_path.replace(request_path)
    except Exception:
        pass
