"""Small stdio-v2 worker used by QProcess lifecycle tests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Mapping


def _message(request: Mapping[str, object], status: str, payload: object = None, error: object = None) -> dict[str, object]:
    return {
        "protocol_version": 2,
        "request_id": request["request_id"],
        "ui_generation": request["ui_generation"],
        "session_id": request.get("session_id"),
        "operation": request["operation"],
        "status": status,
        "payload": payload,
        "error": error,
    }


def _send(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", required=True)
    args = parser.parse_args()
    cache_root = Path(args.cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    log_path = cache_root / "stub-operations.log"
    diagnostic_written = False

    for line in sys.stdin:
        request = json.loads(line)
        operation = str(request.get("operation", ""))
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(operation + "\n")
        _send(_message(request, "started", {"accepted": True}))
        if operation == "ping":
            if not diagnostic_written:
                sys.stderr.write("stub-diagnostic\n" + ("x" * 70_000))
                sys.stderr.flush()
                diagnostic_written = True
            _send(
                _message(
                    request,
                    "result",
                    {
                        "worker_version": "stub-2.0",
                        "protocol_version": 2,
                        "native_abi_version": 1,
                        "index_version": 3,
                        "process_id": os.getpid(),
                    },
                )
            )
        elif operation == "cache_health":
            payload = request.get("payload") or {}
            package_root = str(payload.get("package_root", ""))
            if package_root == "delay":
                time.sleep(0.25)
            if package_root == "crash_once":
                marker = cache_root / "crashed-once.marker"
                if not marker.exists():
                    marker.write_text("crashed", encoding="utf-8")
                    os._exit(73)
            _send(_message(request, "progress", {"completed": 1, "total": 1, "phase": "health"}))
            _send(_message(request, "batch", {"rows": [1]}))
            _send(
                _message(
                    request,
                    "result",
                    {
                        "package_root": package_root,
                        "root_id": "stub-root",
                        "state": "missing",
                        "reason": "stub",
                        "fingerprint": None,
                        "generation_id": None,
                        "entry_count": 0,
                    },
                )
            )
        elif operation in {"open_archive", "refresh_archive"}:
            payload = request.get("payload") or {}
            _send(
                _message(
                    request,
                    "result",
                    {
                        "session_id": "session-stub",
                        "package_root": str(payload.get("package_root", "")),
                        "fingerprint": "fingerprint-stub",
                        "entry_count": 1,
                        "index_version": 3,
                        "cache_hit": operation == "open_archive",
                    },
                )
                | {"session_id": "session-stub"}
            )
        elif operation == "create_query":
            payload = request.get("payload") or {}
            query_payload = payload.get("query") or {}
            if str(query_payload.get("include_text", "")) == "crash_query_once":
                marker = cache_root / "crashed-query-once.marker"
                if not marker.exists():
                    marker.write_text("crashed", encoding="utf-8")
                    os._exit(75)
            _send(
                _message(
                    request,
                    "result",
                    {
                        "session_id": request.get("session_id"),
                        "query_id": "query-stub",
                        "generation": request.get("ui_generation", 0),
                        "total_matches": 1,
                    },
                )
            )
        elif operation == "fetch_page":
            payload = request.get("payload") or {}
            if int(payload.get("page_start", 0)) == 512:
                marker = cache_root / "crashed-page-once.marker"
                if not marker.exists():
                    marker.write_text("crashed", encoding="utf-8")
                    os._exit(76)
            entry = {
                "session_id": request.get("session_id"),
                "entry_id": 0,
                "identity": {
                    "normalized_path": "character/model/stub.pac",
                    "source_pamt": "c:/game/0009/0.pamt",
                    "paz_index": 0,
                    "archive_offset": 24,
                },
                "path": "character/model/stub.pac",
                "source_pamt": "C:/game/0009/0.pamt",
                "paz_file": "C:/game/0009/0.paz",
                "paz_index": 0,
                "offset": 24,
                "stored_size": 8,
                "original_size": 8,
                "flags": 0,
                "extension": ".pac",
                "package": "0009/0.pamt",
                "role": "model",
                "category": "ModelMeshPhysics",
                "is_previewable": True,
                "known_name": "Stub Model",
                "exact_name": "Stub Model",
                "name_evidence": "Exact localization",
                "is_active_override": False,
            }
            _send(
                _message(
                    request,
                    "result",
                    {
                        "session_id": request.get("session_id"),
                        "query_id": str(payload.get("query_id", "")),
                        "generation": request.get("ui_generation", 0),
                        "total_matches": 1,
                        "page_start": int(payload.get("page_start", 0)),
                        "rows": [entry],
                    },
                )
            )
        elif operation == "fetch_children":
            payload = request.get("payload") or {}
            parent_path = str(payload.get("parent_path", "") or "")
            if parent_path == "crash_once":
                marker = cache_root / "crashed-children-once.marker"
                if not marker.exists():
                    marker.write_text("crashed", encoding="utf-8")
                    os._exit(77)
            _send(
                _message(
                    request,
                    "result",
                    {
                        "session_id": request.get("session_id"),
                        "query_id": str(payload.get("query_id", "")),
                        "children": [
                            {
                                "key": "0009",
                                "label": "0009",
                                "is_folder": True,
                                "match_count": 1,
                                "entry": None,
                            }
                        ],
                        "truncated": False,
                        "offset": int(payload.get("offset", 0)),
                        "total_children": 1,
                        "next_offset": None,
                    },
                )
            )
        elif operation == "export":
            os._exit(74)
        elif operation == "cancel":
            _send(_message(request, "result", {"accepted": True}))
        elif operation == "shutdown":
            _send(_message(request, "result", {"accepted": True}))
            return 0
        else:
            _send(
                _message(
                    request,
                    "error",
                    error={"code": "unsupported", "message": operation, "detail": None},
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
