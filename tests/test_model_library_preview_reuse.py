from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from cdmw.ui.model_library.preview import ModelLibraryInlinePreviewMixin


def test_reused_preview_reveals_native_host_after_resources_load(tmp_path: Path) -> None:
    status_file = tmp_path / "host_status.json"
    status_file.write_text(json.dumps({"event": "resources_loaded"}), encoding="utf-8")
    host = object()
    stack = MagicMock()
    set_status = MagicMock()
    record_event = MagicMock()

    class Owner:
        _poll_inline_d3d11_status = ModelLibraryInlinePreviewMixin._poll_inline_d3d11_status
        _inline_d3d11_status_file = status_file
        _inline_d3d11_status_mtime = 0.0
        _inline_d3d11_status_request_id = 7
        _inline_preview_request_id = 7
        inline_d3d11_preview_host = host
        inline_preview_stack = stack
        _set_inline_preview_status = set_status
        _record_model_library_preview_event = record_event

    Owner()._poll_inline_d3d11_status()

    stack.setCurrentWidget.assert_called_once_with(host)
    set_status.assert_called_once_with("Native D3D11 resources loaded; drawing first frame...")
    record_event.assert_called_once_with("model_library_d3d11_resources_loaded")


def test_preview_ignores_status_from_model_replaced_during_load(tmp_path: Path) -> None:
    status_file = tmp_path / "host_status.json"
    status_file.write_text(json.dumps({"event": "resources_loaded"}), encoding="utf-8")
    stack = MagicMock()

    class Owner:
        _poll_inline_d3d11_status = ModelLibraryInlinePreviewMixin._poll_inline_d3d11_status
        _inline_d3d11_status_file = status_file
        _inline_d3d11_status_mtime = 0.0
        _inline_d3d11_status_request_id = 7
        _inline_preview_request_id = 8
        inline_d3d11_preview_host = object()
        inline_preview_stack = stack
        _set_inline_preview_status = MagicMock()
        _record_model_library_preview_event = MagicMock()

    Owner()._poll_inline_d3d11_status()

    stack.setCurrentWidget.assert_not_called()
