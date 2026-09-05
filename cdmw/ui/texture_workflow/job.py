"""One in-memory texture job shared by editing, batch work and export review.

Documents, layers and history stay in the existing editor sessions. This module
owns asset selection and correlates results with those sessions; it does not
decode, transform or publish texture files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from cdmw.models import TextureEditorSourceBinding
from cdmw.ui.texture_workflow.editor_session import (
    _TextureEditorSession,
    texture_editor_document_composite_revision,
)


TEXTURE_MODES = ("edit", "recolor", "upscale")
TEXTURE_MODE_SETTING = "ui/textures_mode"
TEXTURE_TOOL_ALIASES = {
    "texture_editor": "edit",
    "recolor_variants": "recolor",
    "texture_workflow": "upscale",
    "replace_assistant": "review",
}


def normalize_texture_mode(value: object) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in TEXTURE_MODES else "edit"


def _source_key(path: Path | str) -> str:
    return str(Path(path).expanduser().absolute()).replace("\\", "/").casefold()


@dataclass
class TextureJobAsset:
    source_path: Path | None
    binding: TextureEditorSourceBinding = field(default_factory=TextureEditorSourceBinding)
    key: str = field(default_factory=lambda: uuid4().hex)
    session: _TextureEditorSession | None = None
    package_target: object | None = None
    package_path: Path | None = None
    original_entry: object | None = None

    @property
    def source_binding(self) -> TextureEditorSourceBinding:
        document = self.session.document if self.session is not None else None
        return document.source_binding if document is not None else self.binding

    @property
    def label(self) -> str:
        if self.session is not None:
            return self.session.label
        return self.binding.display_name or (self.source_path.name if self.source_path else "Material")


@dataclass(frozen=True)
class TextureJobOperation:
    kind: str
    serial: int
    revisions: tuple[tuple[object, ...], ...]
    # Retain history checkpoints so an undo branch cannot reuse their identities.
    checkpoints: tuple[object, ...] = field(compare=False, repr=False)
    selection: frozenset[str] | None = None


@dataclass(frozen=True)
class TextureJobResult:
    kind: str
    value: object


class TextureJob:
    def __init__(self) -> None:
        self.sessions: list[_TextureEditorSession] = []
        self.assets: dict[str, TextureJobAsset] = {}
        self.selected: set[str] = set()
        self.active_asset_key = ""
        self.mode = "edit"
        self.busy = False
        self.recolor_analysis = None
        self.results: list[TextureJobResult] = []
        self._serial = 0
        self._operations: dict[str, TextureJobOperation] = {}

    def add_source(
        self, path: Path, binding: TextureEditorSourceBinding | None = None,
        *, package_target: object | None = None,
    ) -> TextureJobAsset:
        identity = _source_key(path)
        asset = next((item for item in self.assets.values()
                      if (binding and binding.source_identity_path
                          and item.binding.source_identity_path == binding.source_identity_path)
                      or (item.source_path is not None and _source_key(item.source_path) == identity)), None)
        if asset is None:
            asset = TextureJobAsset(path, binding or TextureEditorSourceBinding())
            self.assets[asset.key] = asset
            self.selected.add(asset.key)
        elif asset.source_path is None:
            asset.source_path = path
            if binding is not None:
                asset.binding = binding
        if package_target is not None:
            asset.package_target = package_target
        return asset

    def synchronize_sessions(self, active_index: int) -> None:
        """Attach the editor's existing sessions without copying their content."""
        live = {id(session) for session in self.sessions}
        for asset in self.assets.values():
            if asset.session is not None and id(asset.session) not in live:
                asset.session = None
        for index, session in enumerate(self.sessions):
            document = session.document
            if document is None:
                continue
            binding = document.source_binding
            asset = next((item for item in self.assets.values() if item.session is session), None)
            if asset is None and binding.source_identity_path:
                asset = next((item for item in self.assets.values()
                              if item.binding.source_identity_path == binding.source_identity_path), None)
                if asset is not None:
                    asset.session = session
                    asset.source_path = Path(binding.source_path) if binding.source_path else None
            if asset is None:
                source = binding.source_path
                if source:
                    asset = self.add_source(Path(source), binding)
                else:
                    asset = TextureJobAsset(None, binding)
                    self.assets[asset.key] = asset
                    self.selected.add(asset.key)
                asset.session = session
            if index == active_index and (
                not self.active_asset_key
                or self.assets.get(self.active_asset_key, asset).session is not None
            ):
                self.active_asset_key = asset.key

    def set_selected(self, keys) -> None:
        self.selected = set(keys).intersection(self.assets)

    def _revision(self, key: str) -> tuple[object, ...]:
        asset = self.assets.get(key)
        if asset is None:
            return (key, "removed")
        session = asset.session
        if session is None:
            return (key, asset.source_path, asset.binding, asset.package_target)
        return (
            key, id(session), session.history_index,
            id(session.history_snapshots[session.history_index]) if session.history_snapshots else None,
            len(session.history_snapshots),
            session.document.width, session.document.height,
            deepcopy(session.document.source_binding),
            texture_editor_document_composite_revision(
                session.document, has_floating_pixels=session.floating_pixels is not None,
            ),
        )

    def begin(self, kind: str, *, asset_keys=None) -> TextureJobOperation:
        keys = tuple(sorted(self.selected if asset_keys is None else asset_keys))
        self._serial += 1
        operation = TextureJobOperation(
            kind, self._serial, tuple(self._revision(key) for key in keys),
            tuple(snapshot for key in keys if key in self.assets and self.assets[key].session is not None
                  for snapshot in self.assets[key].session.history_snapshots),
            frozenset(self.selected) if asset_keys is None else None,
        )
        self._operations[kind] = operation
        return operation

    def cancel(self, kind: str) -> None:
        self._operations.pop(kind, None)

    def accept(self, operation: TextureJobOperation) -> bool:
        if self._operations.get(operation.kind) is not operation:
            return False
        self._operations.pop(operation.kind)
        if operation.selection is not None and operation.selection != self.selected:
            return False
        return operation.revisions == tuple(self._revision(str(row[0])) for row in operation.revisions)

    def complete(self, operation: TextureJobOperation, value: object) -> bool:
        if not self.accept(operation):
            return False
        self.results.append(TextureJobResult(operation.kind, value))
        return True
