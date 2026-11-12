"""The automation bridge inside the app.

A listener thread accepts local clients (``pipe.LocalPipeServer``). Each
command is handed to the UI thread through a queued signal and runs there,
as a click's handler would; the listener never touches widgets. Commands
that only read the event log or wait for an event stay on the client's
thread, so a wait never blocks the UI.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal

from cdmw.automation.pipe import LocalPipeServer, recv_json, send_json
from cdmw.automation.policy import AutomationSettings

TITLE_MARK = " [automation]"
_UI_COMMAND_TIMEOUT_S = 60.0
_EVENT_LIMIT = 20_000


SCREEN_ENV = "CDMW_AUTOMATION_SCREEN"


def automation_screen():
    """The screen automated runs use: CDMW_AUTOMATION_SCREEN, else a secondary one.

    Test windows stay off the user's main monitor.
    """

    from PySide6.QtGui import QGuiApplication

    screens = QGuiApplication.screens()
    if not screens:
        return None
    text = os.environ.get(SCREEN_ENV, "").strip()
    if text.isdigit() and int(text) < len(screens):
        return screens[int(text)]
    primary = QGuiApplication.primaryScreen()
    return next((screen for screen in screens if screen is not primary), primary)


def place_on_automation_screen(widget) -> None:
    screen = automation_screen()
    if screen is None:
        return
    area = screen.availableGeometry()
    widget.move(area.topLeft() + type(area.topLeft())(40, 40))


class _WindowPlacement(QObject):
    """Keep every top-level window off the user's main monitor (and hidden).

    Acts on each window's Polish event, which Qt sends inside setVisible before
    the native window is mapped, so the attribute and position apply to the
    very first show, the start-up splash included. Patching setVisible in
    Python does not see Qt's own show() calls.
    """

    def __init__(self, hidden: bool) -> None:
        super().__init__()
        self.hidden = hidden

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QWidget

        if event.type() == QEvent.Type.Polish and isinstance(watched, QWidget) and watched.isWindow():
            if self.hidden:
                watched.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            try:
                place_on_automation_screen(watched)
            except Exception:
                pass
        return False


def hide_top_level_windows(hidden: bool = True) -> None:
    """Install the placement filter on the application (once)."""

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None or getattr(app, "_cdmw_window_placement", None) is not None:
        return
    placement = _WindowPlacement(hidden)
    app.installEventFilter(placement)
    app._cdmw_window_placement = placement


def _process_start_epoch() -> float:
    """This process's creation time, seconds since the epoch."""

    if os.name != "nt":
        return time.time()
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    times = [wintypes.FILETIME() for _ in range(4)]
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
    if not kernel32.GetProcessTimes(kernel32.GetCurrentProcess(), *(ctypes.byref(t) for t in times)):
        return time.time()
    ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    return ticks / 10_000_000 - 11_644_473_600


def _scalar_fields(fields: Mapping[str, object]) -> dict[str, object]:
    return {str(k): v for k, v in fields.items() if isinstance(v, (str, int, float, bool)) or v is None}


class _Request:
    def __init__(self, command: str, args: Mapping[str, object]) -> None:
        self.command = command
        self.args = dict(args)
        self.done = threading.Event()
        self.result: object = None
        self.error = ""


class AutomationBridge(QObject):
    """Owns the listener and runs commands on the UI thread."""

    _ui_request = Signal(object)

    def __init__(self, settings: AutomationSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.window = None
        self.process_start = _process_start_epoch()
        self._events: list[dict[str, object]] = []
        self._events_changed = threading.Condition()
        self._server: LocalPipeServer | None = None
        self._observer: Callable | None = None
        self._ui_request.connect(self._run_on_ui, Qt.ConnectionType.QueuedConnection)
        self._ui_commands: dict[str, Callable[[dict], object]] = {
            "state": self._state,
            "selection": self._selection,
            "activate_tool": self._activate_tool,
            "select_entry": self._select_entry,
            "select_set": self._select_set,
            "open_mesh_editor": self._open_mesh_editor,
            "capture": self._capture,
            "quit": self._quit,
            "set_preview_settings": self._set_preview_settings,
            "resize": self._resize,
            "end_edit": self._end_edit,
        }

    # ----- lifecycle -------------------------------------------------------
    def attach(self, window) -> None:
        from cdmw.services.diagnostics_service import add_runtime_event_observer

        self.window = window
        self._observer = lambda payload: self._push(str(payload.get("event", "")), payload)
        add_runtime_event_observer(self._observer)
        self._mark_title()
        window.windowTitleChanged.connect(lambda _title: self._mark_title())
        self._watch_preview_host()
        self._server = LocalPipeServer(self.settings.address, self.settings.token, self._serve,
                                       refused=lambda reason: self._push("automation_refused", {"reason": reason}))
        self._server.start()
        self._push("automation_listening", {"address": self.settings.address})

    def stop(self) -> None:
        from cdmw.services.diagnostics_service import remove_runtime_event_observer

        if self._observer is not None:
            remove_runtime_event_observer(self._observer)
            self._observer = None
        if self._server is not None:
            self._server.stop()
            self._server = None

    def _mark_title(self) -> None:
        window = self.window
        if window is not None and not window.windowTitle().endswith(TITLE_MARK):
            window.setWindowTitle(window.windowTitle() + TITLE_MARK)

    def _watch_preview_host(self) -> None:
        host = getattr(getattr(self.window, "archive", None), "archive_d3d11_preview_host", None)
        controller = getattr(host, "controller", None)
        if controller is None:
            return
        keep = ("generation", "texture_uploads", "uploaded_bytes", "elapsed_ms", "package_path", "status",
                "texture_uploads_before", "texture_uploads_after", "retained_entries", "reason",
                *(f"{side}_camera_{key}" for side in ("browse", "edit")
                  for key in ("yaw", "pitch", "distance", "target_x", "target_y", "target_z")))

        def protocol(row):
            row = dict(row or {})
            name = str(row.get("event", ""))
            if name in ("view_state_changed", "presentation_state_update_ack"):
                return
            self._push("preview:" + name, {k: row.get(k) for k in keep if k in row})

        # A finished capture arrives here as "preview:capture_result".
        controller.protocol_event.connect(protocol)

    # ----- the event log ---------------------------------------------------
    def _push(self, name: str, fields: Mapping[str, object]) -> None:
        with self._events_changed:
            entry = {"i": len(self._events), "t": time.time() - self.process_start, "event": name,
                     **_scalar_fields(fields)}
            entry.pop("timestamp", None)
            if len(self._events) < _EVENT_LIMIT:
                self._events.append(entry)
            self._events_changed.notify_all()

    def _events_since(self, since: int) -> list[dict[str, object]]:
        with self._events_changed:
            return self._events[max(0, int(since)):]

    def _wait_event(self, args: dict) -> object:
        name = str(args.get("event", ""))
        match = dict(args.get("match") or {})
        since = int(args.get("since", 0) or 0)
        deadline = time.monotonic() + max(0.0, min(float(args.get("timeout", 30.0)), 600.0))
        with self._events_changed:
            while True:
                for entry in self._events[since:]:
                    if entry["event"] == name and all(entry.get(k) == v for k, v in match.items()):
                        return entry
                since = len(self._events)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"no {name} event within the timeout")
                self._events_changed.wait(remaining)

    # ----- serving a client (its own thread) -------------------------------
    def _serve(self, conn) -> None:
        while True:
            try:
                message = recv_json(conn)
            except (EOFError, OSError):
                return
            if not isinstance(message, dict):
                return
            reply = {"id": message.get("id")}
            try:
                reply["result"] = self._dispatch(str(message.get("command", "")), dict(message.get("args") or {}))
                reply["ok"] = True
            except Exception as exc:
                reply["ok"] = False
                reply["error"] = str(exc) or type(exc).__name__
            try:
                send_json(conn, reply)
            except OSError:
                return

    def _dispatch(self, command: str, args: dict) -> object:
        if command == "ping":
            return {"pid": os.getpid(), "process_start": self.process_start}
        if command == "events":
            return self._events_since(int(args.get("since", 0) or 0))
        if command == "wait_event":
            return self._wait_event(args)
        if command == "processes":
            return self._processes()
        if command not in self._ui_commands:
            raise ValueError(f"Unknown automation command: {command or '(none)'}")
        request = _Request(command, args)
        self._ui_request.emit(request)
        if not request.done.wait(_UI_COMMAND_TIMEOUT_S):
            raise TimeoutError(f"{command} did not finish on the UI thread")
        if request.error:
            raise RuntimeError(request.error)
        return request.result

    def _processes(self) -> dict[str, object]:
        from cdmw.core.common import _windows_descendant_pids
        from cdmw.ui.shell.diagnostics_controller import windows_process_memory_snapshot

        pids = (os.getpid(), *_windows_descendant_pids(os.getpid()))
        rows = []
        for pid in pids:
            snapshot = windows_process_memory_snapshot(pid)
            rows.append({"pid": pid, **{k: int(v) for k, v in snapshot.items() if isinstance(v, int)}})
        return {"count": len(rows), "processes": rows}

    # ----- UI thread -------------------------------------------------------
    def _run_on_ui(self, request: _Request) -> None:
        try:
            request.result = self._ui_commands[request.command](request.args)
        except Exception as exc:
            request.error = str(exc) or type(exc).__name__
        finally:
            request.done.set()

    def _state(self, _args: dict) -> dict[str, object]:
        from cdmw.ui.archive_browser.remote_entry_lookup import LiveCatalogueState, live_catalogue_state
        from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

        window = self.window
        archive = window.archive
        current = getattr(archive, "current_archive_preview_result", None)
        tab = created_tool_widget(window.shell.mesh_editor_tab)
        return {
            "title": window.windowTitle(),
            "visible": bool(window.isVisible()),
            "catalogue_ready": live_catalogue_state(archive) == LiveCatalogueState.READY,
            "browse": {
                "upgrade_pending": bool(getattr(archive, "archive_preview_texture_upgrade_pending", False)),
                "texture_request_loading": bool(getattr(archive, "_archive_texture_request_loading", False)),
                "worker_busy": getattr(archive, "archive_preview_worker", None) is not None,
                "tier": getattr(current, "quality_tier", None),
                "textures_visible": bool(getattr(archive, "_archive_textures_visible", False)),
                "set_members": len(getattr(archive.archive_remote_bridge, "item_set_members", ()) or ()),
            },
            "browse_package": str(getattr(current, "dotnet_preview_package_path", "") or ""),
            "browse_process_id": int(getattr(getattr(getattr(archive, "archive_d3d11_preview_host", None),
                                                     "controller", None), "process_id", 0) or 0),
            "mesh_editor": None if tab is None else {
                "ready": bool(getattr(tab, "standalone_rust_ready", False)),
                # P4 V3: the edit is in Browse's viewport, in Browse's process.
                "in_browse": getattr(getattr(tab, "live_edit", None), "viewport_binding", None) is not None,
                "process_id": self._editor_process_id(tab),
                "texture_unavailable_reason": str(getattr(tab, "standalone_rust_texture_unavailable_reason", "") or ""),
                "session_manifest": self._editor_session_manifest(tab),
            },
            "preview_settings": self._preview_settings(archive, tab),
        }

    @staticmethod
    def _editor_process_id(tab) -> int:
        process = getattr(tab, "standalone_rust_process", None)
        try:
            return int(process.processId()) if process is not None else 0
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return 0

    @staticmethod
    def _editor_session_manifest(tab) -> str:
        from PySide6.QtCore import QProcess

        # A pre-started helper gets its manifest through open_session, not its command line.
        manifest = getattr(getattr(tab, "standalone_rust_authoring_session", None), "manifest_path", None)
        if manifest:
            return str(manifest)
        process = next((value for value in vars(tab).values() if isinstance(value, QProcess)), None)
        arguments = list(process.arguments()) if process is not None else []
        if "--cdmw-session" in arguments:
            return arguments[arguments.index("--cdmw-session") + 1]
        return ""

    @staticmethod
    def _preview_settings(archive, tab) -> dict[str, object]:
        """What each viewport would draw with: the store, Browse, the Mesh Editor."""

        from cdmw.ui.preview.preview_settings_hub import preview_settings_hub

        hub = preview_settings_hub()
        host = getattr(archive, "archive_d3d11_preview_host", None)
        editor = None
        if tab is not None and getattr(tab, "standalone_rust_ready", False):
            try:
                editor = dict(tab._rust_theme_payload().get("preview_settings") or {})
            except Exception:
                editor = None
        return {
            "shared": hub.values() if hub is not None else None,
            "browse": host.effective_preview_settings() if host is not None else None,
            "mesh_editor": editor,
        }

    def _set_preview_settings(self, args: dict) -> dict[str, object]:
        """Change shared Preview settings as the Preview Settings dialog does."""

        from cdmw.ui.preview.preview_settings_hub import preview_settings_hub

        hub = preview_settings_hub()
        if hub is None:
            raise RuntimeError("The shared Preview settings are not available.")
        hub.update(**dict(args.get("values") or {}))
        return hub.values()

    def _selection(self, _args: dict) -> dict[str, object]:
        entry = getattr(self.window.archive, "archive_preview_request_entry", None)
        return {"path": str(getattr(entry, "path", "") or "")}

    def _activate_tool(self, args: dict) -> bool:
        self.window.shell._activate_tool_key(str(args["key"]))
        return True

    def _select_entry(self, args: dict) -> bool:
        archive = self.window.archive
        # A real click passes through the input filter, which holds the
        # background warm-ups for a moment; do the same.
        archive._note_archive_ui_activity()
        if not archive._reveal_archive_path_in_live_catalogue(str(args["path"])):
            raise ValueError(f"The archive has no entry {args['path']}")
        return True

    def _select_set(self, args: dict) -> bool:
        """Open a worn set as Item Finder's "Open all parts" does after its lookup."""

        from cdmw.domain.archives.catalogue import ArchiveLookupKind
        from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

        archive = self.window.archive
        archive._note_archive_ui_activity()
        bridge = archive.archive_remote_bridge
        paths = [str(path) for path in args["paths"]]
        wanted = [path.replace("\\", "/").casefold() for path in paths]
        label = str(args.get("label") or "Item set")

        def found(outcome):
            by_path = {}
            for dto in outcome.entries:
                key = dto.path.replace("\\", "/").casefold()
                if key in wanted and (key not in by_path or dto.is_active_override):
                    by_path[key] = dto.entry_id
            ids = [by_path[key] for key in wanted if key in by_path]
            applied = len(ids) == len(wanted) and bridge.apply_entry_id_scope(ids, label=label, worn_set=True)
            self._push("automation_set_applied", {"ok": bool(applied), "resolved": len(ids), "wanted": len(wanted)})

        start_live_catalogue_lookup(
            archive, "_automation_set_lookup",
            lookup_requests(bridge.current_session.session_id, ArchiveLookupKind.EXACT_PATHS, paths),
            on_done=found,
            on_error=lambda message: self._push("automation_set_applied", {"ok": False, "error": str(message)}),
        )
        return True

    def _open_mesh_editor(self, args: dict) -> bool:
        if args.get("set"):
            self.window.archive.archive_item_set_components.edit_set_button.click()
        else:
            self.window.shell._open_current_archive_mesh_editor()
        return True

    def _resize(self, args: dict) -> bool:
        """Resize the window where it is (it stays on the automation screen)."""

        self.window.showNormal()
        self.window.resize(max(800, int(args.get("width", 1600))), max(600, int(args.get("height", 1000))))
        return True

    def _end_edit(self, args: dict) -> bool:
        """End the open edit as the Finish, Discard, Keep editing prompt would."""

        from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

        tab = created_tool_widget(self.window.shell.mesh_editor_tab)
        if tab is None:
            return False
        if str(args.get("answer", "discard")) == "finish":
            return bool(tab.live_edit.request_finish())
        tab.close_standalone_session()
        return True

    def _quit(self, _args: dict) -> bool:
        from PySide6.QtCore import QTimer

        from cdmw.ui.mesh_editor.live_edit import end_edit_prompt

        # An automated run quits without a question: an open edit is discarded.
        end_edit_prompt.prompt_override = lambda *_args: end_edit_prompt.DISCARD

        QTimer.singleShot(0, self.window.close)
        return True

    def _capture(self, args: dict) -> bool:
        from cdmw.app.app_folder import cdmw_folder

        target = Path(str(args["path"]))
        if not target.is_absolute() or not target.resolve().is_relative_to(cdmw_folder()):
            raise ValueError("A capture is written inside the run's own profile folder only.")
        target.parent.mkdir(parents=True, exist_ok=True)
        host = self.window.archive.archive_d3d11_preview_host
        if not host.request_frame_capture(target):
            raise RuntimeError("The preview cannot capture a frame now.")
        return True


def start_automation_if_requested() -> AutomationBridge | None:
    """Called before the main window exists. Raises AutomationRefused."""

    from cdmw.automation.policy import automation_requested, automation_settings

    if not automation_requested():
        return None
    settings = automation_settings()
    # Every automated run keeps its windows on a secondary screen, and off
    # screen entirely when hidden.
    hide_top_level_windows(hidden=settings.hidden)
    return AutomationBridge(settings)
