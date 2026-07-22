from __future__ import annotations

from unittest.mock import MagicMock

from cdmw.ui.model_library.preview import ModelLibraryInlinePreviewMixin


def test_resident_preview_reveals_dotnet_host_after_ready_state() -> None:
    host = object()
    stack = MagicMock()
    set_status = MagicMock()
    record_event = MagicMock()

    class Owner:
        _handle_inline_dotnet_state = ModelLibraryInlinePreviewMixin._handle_inline_dotnet_state
        _inline_preview_request_id = 7
        _pending_icon_generation_request_id = 0
        inline_d3d11_preview_host = host
        inline_preview_stack = stack
        _set_inline_preview_status = set_status
        _record_model_library_preview_event = record_event
        _cleanup_inline_d3d11_packages = MagicMock()

    Owner()._handle_inline_dotnet_state("ready", "ready")

    stack.setCurrentWidget.assert_called_once_with(host)
    set_status.assert_called_once_with(".NET/Vortice Model Library preview ready.")
    record_event.assert_called_once_with("model_library_dotnet_ready")


def test_legacy_status_polling_is_disabled() -> None:
    stack = MagicMock()

    class Owner:
        _poll_inline_d3d11_status = ModelLibraryInlinePreviewMixin._poll_inline_d3d11_status
        inline_d3d11_preview_host = object()
        inline_preview_stack = stack

    Owner()._poll_inline_d3d11_status()

    stack.setCurrentWidget.assert_not_called()
