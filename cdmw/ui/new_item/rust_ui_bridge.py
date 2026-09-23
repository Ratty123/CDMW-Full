"""One session's presentation state and input authority, independent of transport."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from cdmw.services.new_item_rust_protocol import InputAction, PROTOCOL, PresentationProtocolError
from cdmw.ui.new_item.rust_ui_actions import apply_action
from cdmw.ui.new_item.rust_ui_document import PresentationDocument


class NewItemPresentationBridge:
    def __init__(self, workflow, *, session=None, dialogs=None, native_modal=None):
        self.workflow = workflow
        self.session = session or uuid.uuid4().hex
        self.document = PresentationDocument()
        self._dialogs = dialogs or (lambda: ())
        self._native_modal = native_modal or (lambda: False)
        self._last_request = 0
        self._generation = 0
        self._closed = False

    def snapshot(self):
        self._assert_owner()
        state = self.document.snapshot(self.workflow, dialogs=self._dialogs())
        self._generation += 1
        return {"protocol": PROTOCOL, "type": "state", "session": self.session,
                "generation": self._generation, "last_request": self._last_request,
                "native_modal": self._native_modal(), **state}

    def dispatch(self, message):
        self._assert_owner()
        action = InputAction.from_message(message)
        if self._closed or action.session != self.session:
            raise PresentationProtocolError("The New Item presentation session has ended.")
        if self._native_modal():
            raise PresentationProtocolError("Complete the file or colour dialog before editing the item.")
        if action.request <= self._last_request:
            raise PresentationProtocolError("Duplicate or out-of-order presentation input.")
        self._last_request = action.request
        # Re-read authority, including visibility/disabled state and model revisions,
        # before invoking a handler. The helper's last snapshot is not authority.
        self.document.snapshot(self.workflow, dialogs=self._dialogs())
        obj, node = self.document.registry.resolve(action.control, action.revision)
        dialogs = tuple(self._dialogs())
        if dialogs:
            active = dialogs[-1]
            owner = obj.parent() if hasattr(obj, "parent") else None
            while owner is not None and owner is not active:
                owner = owner.parent()
            if obj is not active and owner is None:
                raise PresentationProtocolError("Complete the active dialog before editing the item.")
        apply_action(self.document, obj, node, action.action, action.value)
        return {"protocol": PROTOCOL, "type": "ack", "session": self.session,
                "request": action.request}

    def close(self):
        self._closed = True
        self.document.registry.current.clear()

    @staticmethod
    def _assert_owner():
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise PresentationProtocolError("New Item input must run on its owning UI thread.")
