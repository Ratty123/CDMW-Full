"""Edit a mesh where Browse Archives shows it (P4 V3).

The live-edit component normally embeds a helper of its own in the Mesh Editor
tab's host frame. A ``BrowseViewportBinding`` points it at Browse's viewport
instead: Browse's helper process enters edit mode in the window that already
shows the model, so nothing is launched and no texture is uploaded again.

The binding stands in for the tab's host frame (``frame``) and lends the
component a channel to Browse's process (``borrow``). The window stays a child
of Browse's host frame throughout; nothing here reparents it.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

#: The kinds ``BrowseViewportBinding.status`` reports (not shown to the user).
STATUS_LOADING, STATUS_EDITING, STATUS_ERROR, STATUS_RESULT = range(4)


class BrowseEditFrame:
    """What the component calls on its host frame, answered for Browse's viewport."""

    def __init__(self, binding: "BrowseViewportBinding") -> None:
        self._binding = binding
        self._focus_request_supported = False

    def _host(self):
        return self._binding.preview_host

    def host_hwnd(self) -> int:
        try:
            return int(self._host().controller._safe_host_hwnd())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return 0

    def prepare_launch(self) -> int:
        return self.host_hwnd()

    def attach_child_window(self, child_hwnd: int, _process_id: int = 0,
                            _embedded_parent_hwnd: int = 0) -> tuple[bool, str]:
        # The edit draws in the window Browse already embeds: accept only that one.
        shown = int(getattr(self._host(), "_embedded_child_hwnd", 0) or 0)
        if child_hwnd > 0 and child_hwnd == shown:
            return True, ""
        return False, "the edit did not open in Browse's viewport"

    def detach_child_window(self) -> None:
        """The window stays Browse's."""

    def show_loading(self, message: str) -> None:
        self._binding.status.emit(STATUS_LOADING, str(message or ""))

    def show_editor(self) -> None:
        self._binding.status.emit(STATUS_EDITING, "")

    def show_error(self, message: str) -> None:
        self._binding.status.emit(STATUS_ERROR, str(message or ""))

    def show_result(self, message: str) -> None:
        self._binding.status.emit(STATUS_RESULT, str(message or ""))


class BrowseViewportBinding(QObject):
    """One edit in Browse's viewport, from ``open`` until the edit ends.

    ``status(kind, message)`` reports loading, editing, error and result, for
    Browse's editing banner. ``ended()`` is emitted once, when the component
    lets go of the viewport.
    """

    status = Signal(int, str)
    ended = Signal()

    def __init__(self, preview_host: QObject, entry_label: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.preview_host = preview_host
        self.entry_label = str(entry_label or "")
        self.frame = BrowseEditFrame(self)
        self.channel = None
        self._ended = False

    def blocker(self) -> str:
        controller = getattr(self.preview_host, "controller", None)
        check = getattr(controller, "edit_in_place_blocker", None)
        if not callable(check):
            return "this viewport cannot edit in place"
        return str(check() or "")

    def show_view_now(self) -> bool:
        """Borrow Browse's helper and show the editor on its model at once (P4 V4)."""

        channel = self.borrow()
        return channel is not None and channel.show_view(keep_view=True)

    def borrow(self):
        """A channel to Browse's helper, or None when its viewport cannot edit now.

        The channel borrowed at the click (``show_view_now``) is kept for the session.
        """

        if self.channel is not None and self.channel.is_running:
            return self.channel
        controller = getattr(self.preview_host, "controller", None)
        borrow = getattr(controller, "borrow_for_edit", None)
        if not callable(borrow):
            return None
        self.channel = borrow(self)
        return self.channel

    def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        channel, self.channel = self.channel, None
        if channel is not None and channel.is_running:
            channel.terminate()
        self.ended.emit()

    @property
    def is_ended(self) -> bool:
        return self._ended


__all__ = ["BrowseEditFrame", "BrowseViewportBinding"]
