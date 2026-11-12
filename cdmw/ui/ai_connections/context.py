"""What tools reach in the app: settings, the registry, the game folder and the services.

One object per app, given to every tool call as ``call.context``. Each
accessor is safe from a tool's thread: interface state and the Qt services
are reached through ``ui_call``, which runs a short call on the UI thread;
the waiting happens on the tool's thread.
"""

from __future__ import annotations

import threading
from pathlib import Path

from cdmw.mcp.approvals import GAME_FOLDER_KEY
from cdmw.mcp.errors import FAILED, UNAVAILABLE, ToolError

NO_ARCHIVES = "Load the game archives first: open Browse Archives with the game folder set in Settings > Paths."
CATALOGUE_TIMEOUT_S = 600.0


class AppToolContext:
    def __init__(self, settings, executor, *, window=None, services=None) -> None:
        self.settings = settings
        self.executor = executor
        self.window = window
        self._services = services
        self._calls = None
        self._lock = threading.Lock()

    def ui_call(self, function, timeout: float | None = None):
        if timeout is None:
            return self.executor.call(function)
        return self.executor.call(function, timeout)

    def command_registry(self):
        from cdmw.ui.commands.registry import command_registry

        return command_registry()

    def game_folder(self) -> str:
        value = self.settings.value(GAME_FOLDER_KEY, "") if self.settings is not None else ""
        return str(value or "").strip()

    def services(self):
        """The window's service container (``app_context.services``), or the one given."""

        if self._services is not None:
            return self._services
        app_context = getattr(self.window, "app_context", None)
        return getattr(app_context, "services", None)

    def app_folder(self) -> Path:
        from cdmw.app.app_folder import cdmw_folder

        return cdmw_folder()

    # ----- the archive catalogue ------------------------------------------------------
    def catalogue_service(self):
        service = getattr(self.services(), "archive_catalogue", None)
        if service is None:
            raise ToolError(UNAVAILABLE, NO_ARCHIVES)
        return service

    def catalogue_calls(self):
        """The waiter for the catalogue's signals, made once on the UI thread."""

        from cdmw.ui.ai_connections.catalogue_calls import CatalogueCalls

        service = self.catalogue_service()
        with self._lock:
            calls = self._calls
        if calls is None or calls.service is not service:
            calls = self.ui_call(lambda: CatalogueCalls(service))
            with self._lock:
                self._calls = calls
        return calls

    def archive_session(self):
        service = self.catalogue_service()
        session = self.ui_call(lambda: service.current_session)
        if session is None:
            raise ToolError(UNAVAILABLE, NO_ARCHIVES)
        return session

    def catalogue_call(self, method: str, *args, cancel: threading.Event | None = None, on_batch=None,
                       timeout: float = CATALOGUE_TIMEOUT_S):
        """Run one catalogue request (``create_query``, ``fetch_page`` ...) and wait for its result."""

        from cdmw.ui.ai_connections.catalogue_calls import wait_for

        calls = self.catalogue_calls()
        try:
            request_id, waiting = self.ui_call(lambda: calls.submit(method, *args, on_batch=on_batch))
        except ToolError:
            raise
        except (ValueError, KeyError, RuntimeError) as refused:
            raise ToolError(UNAVAILABLE, str(refused) or NO_ARCHIVES) from None
        return wait_for(self, waiting, request_id, cancel, timeout)

    def resident_index(self, cancel: threading.Event | None = None):
        """The loaded archives' index (a memory map of the worker's index), opened on this thread."""

        from cdmw.core.archive_resident_index import ResidentArchiveSource

        service = self.catalogue_service()
        session = self.archive_session()
        source = self.ui_call(lambda: ResidentArchiveSource.capture(service, session.package_root))
        if source is None:
            raise ToolError(UNAVAILABLE, NO_ARCHIVES)
        return source.open(stop_event=cancel)

    def used_by(self, entry, session_id: str, cancel: threading.Event | None, progress=None,
                timeout: float = CATALOGUE_TIMEOUT_S):
        """Browse's "Find references" search for ``entry``; its final state."""

        import time

        from cdmw.mcp.errors import CANCELLED
        from cdmw.services.archive_reference_search import ArchiveReferenceSearchController

        service = self.catalogue_service()
        finished = threading.Event()
        holder: dict[str, object] = {}

        def start():
            controller = ArchiveReferenceSearchController(service)
            holder["controller"] = controller

            def updated(state):
                holder["state"] = state
                if progress is not None:
                    progress(float(getattr(state, "scanned", 0)), float(getattr(state, "total", 0)), "")
                if getattr(state, "finished", False) or getattr(state, "error", "") or getattr(state, "cancelled",
                                                                                                False):
                    finished.set()

            controller.updated.connect(updated)
            controller.idle.connect(finished.set)
            generation = int(getattr(service, "_minimum_ui_generation", 0) or 0)
            if not controller.start(entry, session_id=session_id, generation=generation):
                finished.set()
            return controller

        controller = self.ui_call(start)
        deadline = time.monotonic() + timeout
        try:
            while not finished.wait(0.05):
                if cancel is not None and cancel.is_set():
                    raise ToolError(CANCELLED, "Cancelled.")
                if time.monotonic() > deadline:
                    raise ToolError(FAILED, "The reference search did not finish in time.")
            # "idle" can come before the last "updated" is read; let the UI thread settle.
            return self.ui_call(lambda: getattr(controller, "state", None) or holder.get("state"))
        finally:
            def drop():
                if controller.busy:
                    controller.cancel()
                controller.deleteLater()
            self.ui_call(drop)
