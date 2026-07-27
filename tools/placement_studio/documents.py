"""Typed views over the two XML file kinds, backed by the text-preserving document.

Both classes read through to `XmlDocument`, so an unedited document still emits its input
bytes exactly. Malformed transforms are reported rather than silently defaulted: a socket
whose rotation will not parse is a fact the UI needs, not a value to guess at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .model import DescriptorPart, Quat, Socket, TransformError, Vec3
from .xmldoc import Element, XmlDocument, XmlDocumentError

SOCKET_KEY = "Name"
SOCKET_CONTAINER = "SocketList"
STACK_CONTAINER = "StackEquipInfo"
DESCRIPTOR_KEY = "PartName"


def is_socket_file(game_path: str) -> bool:
    return game_path.lower().endswith(".sockets.xml")


def is_descriptor_file(game_path: str) -> bool:
    lowered = game_path.lower()
    return lowered.endswith(".xml") and "description_player" in lowered


def is_body_socket_file(game_path: str) -> bool:
    """Body sockets live in `<model>.pab.sockets.xml`; weapon sockets sit under `weapon/`."""

    return game_path.lower().endswith(".pab.sockets.xml")


class SocketDocument:
    """A `*.sockets.xml` file: socket definitions plus stack-equip references."""

    __slots__ = ("doc", "game_path", "_warnings")

    def __init__(self, doc: XmlDocument, game_path: str = "") -> None:
        self.doc = doc
        self.game_path = game_path
        self._warnings: List[str] = []

    @classmethod
    def load(cls, data: bytes, game_path: str = "") -> "SocketDocument":
        return cls(XmlDocument.from_bytes(data), game_path)

    @classmethod
    def read(cls, path: Path, game_path: str = "") -> "SocketDocument":
        return cls.load(Path(path).read_bytes(), game_path or Path(path).name)

    def to_bytes(self) -> bytes:
        return self.doc.to_bytes()

    @property
    def warnings(self) -> Tuple[str, ...]:
        return tuple(self._warnings)

    @property
    def declared_count(self) -> Optional[int]:
        return self.doc.container_count(SOCKET_CONTAINER)

    def _element_to_socket(self, element: Element) -> Socket:
        rotation, translation = Quat(), Vec3()
        raw_rotation = element.get("Rotation")
        raw_translation = element.get("Translation")
        try:
            if raw_rotation:
                rotation = Quat.parse(raw_rotation)
        except TransformError as exc:
            self._warnings.append(f"{element.identity}: {exc}")
        try:
            if raw_translation:
                translation = Vec3.parse(raw_translation)
        except TransformError as exc:
            self._warnings.append(f"{element.identity}: {exc}")
        return Socket(
            name=element.identity,
            parent_bone=element.get("Parent"),
            rotation=rotation,
            translation=translation,
            ui_visible=element.get("UIView", "True").strip().lower() != "false",
            source_file=self.game_path,
        )

    def sockets(self) -> List[Socket]:
        """Socket *definitions* only — never the bare references in `StackEquipInfo`."""

        self._warnings = []
        return [
            self._element_to_socket(element)
            for element in self.doc.elements(SOCKET_KEY, container=SOCKET_CONTAINER)
        ]

    def socket_map(self) -> Dict[str, Socket]:
        return {socket.name: socket for socket in self.sockets()}

    def stack_equip_references(self) -> List[str]:
        return [
            element.identity
            for element in self.doc.elements(SOCKET_KEY, container=STACK_CONTAINER)
        ]

    def count_matches_contents(self) -> bool:
        declared = self.declared_count
        return declared is None or declared == len(self.sockets())

    # ── editing ─────────────────────────────────────────────────────

    def set_translation(self, name: str, value: Vec3) -> None:
        self.doc.set_attribute(
            SOCKET_KEY, name, "Translation", value.format(), container=SOCKET_CONTAINER
        )

    def set_rotation(self, name: str, value: Quat) -> None:
        if not value.is_normalized():
            raise XmlDocumentError(f"Refusing to write a non-normalized quaternion for {name!r}")
        self.doc.set_attribute(
            SOCKET_KEY, name, "Rotation", value.format(), container=SOCKET_CONTAINER
        )

    def add_socket(self, socket: Socket, *, after: str = "") -> None:
        """Define a new socket. Creating a definition is safe; referencing a missing one is not."""

        existing = self.doc.elements(SOCKET_KEY, container=SOCKET_CONTAINER)
        if any(item.identity == socket.name for item in existing):
            raise XmlDocumentError(f"Socket {socket.name!r} already defined")
        anchor = after or (existing[-1].identity if existing else "")
        separator = self.doc.separator_before(SOCKET_KEY, anchor, container=SOCKET_CONTAINER)
        raw = (
            f'{separator}<Socket Name="{socket.name}" Parent="{socket.parent_bone}"'
            f' Rotation="{socket.rotation.format()}"'
            f' Translation="{socket.translation.format()}"/>'
        )
        self.doc.add_element(
            SOCKET_KEY, raw, after=anchor, container=SOCKET_CONTAINER, bump_count=True
        )


class DescriptorDocument:
    """A character descriptor: equipment rows routed to body and child sockets."""

    __slots__ = ("doc", "game_path")

    def __init__(self, doc: XmlDocument, game_path: str = "") -> None:
        self.doc = doc
        self.game_path = game_path

    @classmethod
    def load(cls, data: bytes, game_path: str = "") -> "DescriptorDocument":
        return cls(XmlDocument.from_bytes(data), game_path)

    @classmethod
    def read(cls, path: Path, game_path: str = "") -> "DescriptorDocument":
        return cls.load(Path(path).read_bytes(), game_path or Path(path).name)

    def to_bytes(self) -> bytes:
        return self.doc.to_bytes()

    def parts(self) -> List[DescriptorPart]:
        return [
            DescriptorPart(
                part_name=element.identity,
                in_socket=element.get("InSocketBone"),
                out_socket=element.get("OutSocketBone"),
                in_child_socket=element.get("InChildSocketBone"),
                out_child_socket=element.get("OutChildSocketBone"),
                weapon_case_part=element.get("WeaponCasePart"),
                bag_socket=element.get("BagSocketBone"),
                vehicle_bag_socket=element.get("VehicleBagSocketBone"),
                source_file=self.game_path,
            )
            for element in self.doc.elements(DESCRIPTOR_KEY)
        ]

    def part_map(self) -> Dict[str, DescriptorPart]:
        return {part.part_name: part for part in self.parts()}

    def referenced_sockets(self) -> Dict[str, List[str]]:
        """socket name -> the part rows that route through it."""

        usage: Dict[str, List[str]] = {}
        for part in self.parts():
            for socket in (
                part.in_socket,
                part.out_socket,
                part.in_child_socket,
                part.out_child_socket,
            ):
                if socket:
                    usage.setdefault(socket, []).append(part.part_name)
        return usage

    # ── editing ─────────────────────────────────────────────────────

    _ROUTE_ATTRIBUTES = {
        "in_socket": "InSocketBone",
        "out_socket": "OutSocketBone",
        "in_child_socket": "InChildSocketBone",
        "out_child_socket": "OutChildSocketBone",
    }

    def set_route(self, part_name: str, field_name: str, socket_name: str) -> None:
        attribute = self._ROUTE_ATTRIBUTES.get(field_name)
        if attribute is None:
            raise XmlDocumentError(f"Not a routable field: {field_name!r}")
        element = self.doc.element(DESCRIPTOR_KEY, part_name)
        if element is None:
            raise XmlDocumentError(f"No descriptor row {part_name!r}")
        if attribute in element.attributes:
            self.doc.set_attribute(DESCRIPTOR_KEY, part_name, attribute, socket_name)
        else:
            self.doc.add_attribute(DESCRIPTOR_KEY, part_name, attribute, socket_name)
