"""Lifetime-safe control identities and per-control revision tracking."""

from __future__ import annotations

import hashlib
import json
import weakref

from shiboken6 import isValid

from cdmw.services.new_item_rust_protocol import PresentationProtocolError


class ControlRegistry:
    def __init__(self):
        self._next = 0
        self._objects = weakref.WeakKeyDictionary()
        self._refs = {}
        self._fingerprints = {}
        self._revisions = {}
        self.current = {}

    def identify(self, obj) -> str:
        identifier = self._objects.get(obj)
        if identifier is None:
            self._next += 1
            identifier = f"c{self._next}"
            self._objects[obj] = identifier
            self._refs[identifier] = weakref.ref(obj)
        return identifier

    def begin(self):
        self.current = {}
        dead = [key for key, ref in self._refs.items() if ref() is None or not isValid(ref())]
        for key in dead:
            self._refs.pop(key, None)
            self._fingerprints.pop(key, None)
            self._revisions.pop(key, None)

    def publish(self, obj, node):
        identifier = self.identify(obj)
        # Children have their own identities/revisions. Updating a log or a sibling
        # must not invalidate text being edited in another control.
        own = {key: value for key, value in node.items() if key not in {"children", "revision"}}
        # Tab-corner controls are independent children too. Their visibility and
        # selected-effect label must not invalidate an in-flight tab click.
        if node.get("kind") == "tabs":
            own["props"] = {key: value for key, value in node["props"].items() if key != "corners"}
        fingerprint = hashlib.blake2s(json.dumps(own, ensure_ascii=False, sort_keys=True,
                                                allow_nan=False).encode("utf-8")).digest()
        if self._fingerprints.get(identifier) != fingerprint:
            self._fingerprints[identifier] = fingerprint
            self._revisions[identifier] = self._revisions.get(identifier, 0) + 1
        node["id"] = identifier
        node["revision"] = self._revisions[identifier]
        self.current[identifier] = node
        return node

    def resolve(self, identifier: str, revision: int):
        node = self.current.get(identifier)
        ref = self._refs.get(identifier)
        obj = ref() if ref else None
        if node is None or obj is None or not isValid(obj):
            raise PresentationProtocolError("This control is no longer available.")
        if node["revision"] != revision:
            raise PresentationProtocolError("This control changed; review its current value and try again.")
        if not node.get("enabled", True):
            raise PresentationProtocolError("This control is currently disabled.")
        return obj, node
