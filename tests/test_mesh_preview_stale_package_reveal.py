"""A resident helper must not be revealed on the package nobody asked for.

The preview helper stays resident between meshes, so when it is made visible it
is usually already holding *something*: the procedural prewarm scene it was
warmed on, or the mesh opened before this one. Becoming visible used to activate
that first and only then notice the applied package was not the one selected, so
the window was revealed specifically to show one model and spent the length of a
package load showing another. That is the placeholder triangle at Mesh Editor
start.

The reveal belongs to the load: `_accept_applied_package` activates once the
right package has landed, and its check is on identity rather than on merely
having something applied.
"""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController
from cdmw.ui.preview.profile import DotNetPreviewProfile

_APP = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _running_helper():
    """The branch under test is only reached with the helper already running."""

    with patch("cdmw.ui.preview.dotnet_session.qprocess_is_running", return_value=True):
        yield


def _resident_controller() -> tuple[DotNetPreviewSessionController, list[dict]]:
    controller = DotNetPreviewSessionController(
        host_hwnd=lambda: 1234,
        profile=DotNetPreviewProfile.PREVIEW,
    )
    sent: list[dict] = []
    controller._send_json = lambda payload: (sent.append(dict(payload)) or True)  # type: ignore[method-assign]
    loads: list[bool] = []
    controller._request_resident_package_load = lambda: (  # type: ignore[method-assign]
        loads.append(True) or True
    )
    controller._loads = loads  # type: ignore[attr-defined]
    # A warm helper that has finished its handshake and holds a package.
    controller._session_established = True
    controller._localization_initial_established = True
    controller._launch_is_prewarm = False
    controller._renderer_ready = True
    controller._applied_package_path = "C:/warm/prewarm-package"
    controller._applied_package_identity = ("prewarm", "0", "0")
    controller._process = object()
    return controller, sent


def _events(sent: list[dict]) -> list[str]:
    return [str(msg.get("event", "")) for msg in sent]


def test_a_stale_resident_package_is_not_revealed() -> None:
    controller, sent = _resident_controller()
    try:
        # The reader selected a different mesh than the one resident.
        controller._desired_package = object()
        controller._desired_package_identity = ("real-mesh", "1", "1")

        controller.set_visible(True)

        assert "activate_request" not in _events(sent), (
            "the helper was revealed while still holding the package nobody "
            "asked for; the reader watches the wrong model until the real load "
            f"lands ({_events(sent)})"
        )
        assert controller._loads, (  # type: ignore[attr-defined]
            "the real package was never requested either"
        )
    finally:
        controller.shutdown()


def test_the_matching_resident_package_is_revealed_immediately() -> None:
    """A warm helper already holding the right mesh must not pay a reload."""

    controller, sent = _resident_controller()
    try:
        controller._desired_package = object()
        controller._desired_package_identity = ("prewarm", "0", "0")
        controller._applied_package_identity = ("prewarm", "0", "0")

        controller.set_visible(True)

        assert "activate_request" in _events(sent), (
            "a helper already holding exactly the requested package was not "
            f"revealed ({_events(sent)})"
        )
        assert not controller._loads, (  # type: ignore[attr-defined]
            "the resident package was reloaded even though it already matched"
        )
    finally:
        controller.shutdown()


def test_hiding_still_deactivates() -> None:
    controller, sent = _resident_controller()
    try:
        controller.set_visible(False)
        assert "deactivate_request" in _events(sent)
    finally:
        controller.shutdown()
