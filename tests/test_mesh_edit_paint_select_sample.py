"""Intermediate brush-select dabs apply inline, off the action-worker path.

The worker path answers every request with a command_result and rejects
requests while busy; at paint cadence that is a busy-spam reply per dab and
holes in the painted sweep. Intermediate dabs therefore run inline through
`_apply_dotnet_paint_select_sample`, and the drag's final dab keeps the
ordinary worker path so one drag records one selection-history unit.
"""

from __future__ import annotations

import cdmw.ui.mesh_editor.tab  # noqa: F401  (loads the tab facade globals)
from cdmw.ui.mesh_editor.tab_dotnet_commands import MeshEditorDotNetCommandMixin


class _Result:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.diagnostics = ()
        self.metrics = {}


class _Controller:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.applied: list[dict[str, object]] = []

    def apply(self, action: str, **kwargs: object) -> _Result:
        self.applied.append({"action": action, **kwargs})
        return _Result(self.ok)

    def native_update_for_result(self, result: _Result) -> str:
        return "native-update"


class _Host:
    """The minimum surface `_apply_dotnet_paint_select_sample` touches."""

    _apply_dotnet_paint_select_sample = MeshEditorDotNetCommandMixin._apply_dotnet_paint_select_sample

    def __init__(self, *, embedded: bool = True, worker_active: bool = False, blocked: bool = False) -> None:
        self.standalone_dotnet_target_embedded = embedded
        self._worker_active = worker_active
        self._blocked = blocked
        self.embedded_updates: list[object] = []
        self.standalone_updates: list[object] = []
        self.statuses: list[str] = []

    def _dotnet_screen_selection_payload(self, payload: object) -> dict[str, object]:
        result: dict[str, object] = {}
        if isinstance(payload, dict):
            for key in ("screen_brush", "screen_region"):
                raw = payload.get(key)
                if isinstance(raw, dict):
                    result[key] = dict(raw)
        return result

    def _native_editor_action_blocked(self, command: str, *, embedded: bool = False) -> bool:
        return self._blocked

    def _standalone_action_worker_active(self) -> bool:
        return self._worker_active

    def _set_dotnet_status(self, message: str, *, error: bool = False) -> None:
        self.statuses.append(message)

    def _apply_embedded_native_update(self, update: object) -> None:
        self.embedded_updates.append(update)

    def _apply_standalone_native_update(self, update: object) -> bool:
        self.standalone_updates.append(update)
        return True

    def _send_dotnet_native_update(
        self,
        update: object,
        *,
        request_payload: object = None,
    ) -> None:
        self.standalone_updates.append((update, request_payload))


def _payload(operation: str = "add") -> dict[str, object]:
    return {
        "operation": operation,
        "paint_sample": True,
        "paint_final": False,
        "screen_brush": {"x": 10, "y": 20, "radius": 24},
    }


def test_a_dab_applies_the_select_and_pushes_the_update_embedded() -> None:
    host = _Host(embedded=True)
    controller = _Controller()

    assert host._apply_dotnet_paint_select_sample(controller, _payload()) is True

    assert controller.applied and controller.applied[0]["action"] == "select"
    assert controller.applied[0]["operation"] == "add"
    assert host.embedded_updates == ["native-update"]
    assert not host.standalone_updates


def test_a_dab_routes_to_the_standalone_update_when_not_embedded() -> None:
    host = _Host(embedded=False)
    controller = _Controller()

    assert host._apply_dotnet_paint_select_sample(controller, _payload("subtract")) is True

    assert controller.applied[0]["operation"] == "subtract"
    assert host.standalone_updates == [("native-update", _payload("subtract"))]


def test_a_dab_is_dropped_quietly_while_a_heavy_action_runs() -> None:
    host = _Host(worker_active=True)
    controller = _Controller()

    assert host._apply_dotnet_paint_select_sample(controller, _payload()) is True
    assert not controller.applied


def test_a_blocked_editor_refuses_the_dab() -> None:
    host = _Host(blocked=True)
    controller = _Controller()

    assert host._apply_dotnet_paint_select_sample(controller, _payload()) is False
    assert not controller.applied


def test_a_dab_without_a_brush_payload_is_refused() -> None:
    host = _Host()
    controller = _Controller()

    assert host._apply_dotnet_paint_select_sample(controller, {"paint_sample": True}) is False
    assert not controller.applied


def test_a_sweep_quad_region_is_accepted_like_a_dab() -> None:
    """A fast cursor step arrives as a swept-segment `screen_region` quad
    instead of a disc; the inline fast path applies it the same way so the
    painted band never gets holes at speed.
    """
    host = _Host(embedded=True)
    controller = _Controller()
    payload = {
        "operation": "add",
        "paint_sample": True,
        "paint_final": False,
        "screen_region": {"mode": "lasso", "points": [[0, 0], [50, 0], [50, 48], [0, 48]]},
    }

    assert host._apply_dotnet_paint_select_sample(controller, payload) is True
    assert controller.applied and controller.applied[0]["action"] == "select"
    assert host.embedded_updates == ["native-update"]


def test_a_failed_native_select_reports_false_without_updates() -> None:
    host = _Host()
    controller = _Controller(ok=False)

    assert host._apply_dotnet_paint_select_sample(controller, _payload()) is False
    assert not host.embedded_updates
