"""Read-only Textures dock for the Mesh Editor (live texture editing, stage 1).

The panel lists each part's textures from the session manifest the Mesh
Editor already writes for the Rust editor. It resolves nothing itself: the
model comes from :func:`texture_rows_from_manifest`, a pure function that
needs no Qt, and the widget is a thin view over it. Thumbnails are decoded on
a Qt thread pool and delivered back through a queued signal.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QLabel,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

THUMBNAIL_SIZE = 48
TEXTURE_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 1

COLUMN_THUMBNAIL = 0
COLUMN_ROLE = 1
COLUMN_FILE = 2
COLUMN_STATE = 3

_THUMBNAIL_CACHE_LIMIT = 512

# Display order inside a part: what a modder looks for first comes first.
_ROLE_ORDER = {
    "base_color": 0, "normal": 1, "material": 2, "specular": 3, "roughness": 4,
    "metalness": 5, "occlusion": 6, "glossiness": 7, "height": 8, "emissive": 9,
    "opacity": 10, "layer_mask": 11, "shader_mask": 11, "detail": 12,
    "skin_detail_mask": 12, "skin_detail_normal": 12, "skin_detail_material": 12,
    "layer": 13, "shader_normal": 14, "flow": 15,
}

# Preview Core layer resources of the base layer, named as the renderer roles they feed.
_BASE_LAYER_RESOURCE_ROLES = {
    "diffuse": "base_color", "normal": "normal", "material": "material",
    "height": "height", "mask": "layer_mask",
}
_LAYER_RESOURCES = ("diffuse", "normal", "material", "height", "mask")


@dataclass(frozen=True, slots=True)
class TextureRow:
    """One texture used by one part."""

    texture_id: str
    role: str
    game_path: str
    decoded_path: str
    shared: bool = False

    @property
    def file_name(self) -> str:
        return PurePosixPath(self.game_path.replace("\\", "/")).name or self.game_path


@dataclass(frozen=True, slots=True)
class TexturePartGroup:
    """The textures of one part, in display order."""

    part_index: int
    part_name: str
    source_file: str
    rows: tuple[TextureRow, ...] = field(default_factory=tuple)

    @property
    def group_heading(self) -> str:
        if self.source_file:
            return self.part_name + " (" + self.source_file + ")"
        return self.part_name


def texture_role_label(role: str) -> str:
    """The panel's name for a manifest texture role."""

    value = str(role or "").strip().casefold()
    if value in {"base_color", "base", "diffuse", "albedo"}:
        return "Base colour"
    if value in {"normal", "shader_normal"}:
        return "Normal"
    if value in {"layer_mask", "shader_mask", "mask"}:
        return "Mask"
    if value in {"detail", "skin_detail_mask", "skin_detail_normal", "skin_detail_material"}:
        return "Detail"
    if value == "layer":
        return "Layer"
    if value == "emissive":
        return "Emissive"
    if value == "material":
        return "Material"
    if value == "specular":
        return "Specular"
    if value == "roughness":
        return "Roughness"
    if value == "metalness":
        return "Metalness"
    if value == "occlusion":
        return "Occlusion"
    if value == "glossiness":
        return "Gloss"
    if value == "height":
        return "Height"
    if value == "opacity":
        return "Opacity"
    if value == "flow":
        return "Flow"
    return "Other"


def texture_rows_from_manifest(
    manifest: Mapping[str, object],
    *,
    session_root: str | os.PathLike[str] | None = None,
    part_names: Mapping[int, str] | Sequence[str] | None = None,
) -> list[TexturePartGroup]:
    """Build the panel model from a Mesh Editor session manifest.

    The manifest is the one ``RustMeshAuthoringSession`` writes before the
    editor starts (``cdmw/services/mesh_rust_authoring.py``, the method that
    builds ``manifest = {...}`` and passes it to ``_atomic_write_payload``
    with ``self.manifest_path.name``). Keys read, and why:

    * ``textures[]``: the renderer's texture resources, made by
      ``_publish_rust_texture_resources`` (called from
      ``_mesh_texture_payloads``). Each row gives ``role`` (the renderer role,
      from ``_TEXTURE_RESOURCE_SPECS`` and ``_material_input_texture_role``),
      ``label`` (the resolved source file's name), ``file.path`` (the copied
      ``texture-NNNN-<sha>.dds``, relative to the session folder),
      ``file.sha256`` and ``material_indices_by_lod`` (which parts use it).
      Parts are LOD 0 material indices, the list the Parts panel shows. When
      a set or a replacement is open, the same method swaps this list for the
      active ``archive_refit_material_cache`` entry, so it is still the list
      the editor draws.
    * ``preview_core_material_graph.materials[]``: the native layer graph from
      ``_composite_preview_core_material_graph`` and
      ``_copy_preview_core_material_layers``
      (``cdmw/services/mesh_rust_preview_package.py``). Each material has
      ``lod_index``, ``material_index`` and ``layers[]`` with ``layer_role``
      and, per resource (``diffuse``, ``normal``, ``material``, ``height``,
      ``mask``), a file reference plus ``<resource>_archive_path``. It is the
      only place the manifest carries a texture's game path, and it lists the
      layer, detail and mask files a layered material combines in the shader.
      A ``textures[]`` row gets its game path from here by ``sha256``.
    * ``state.skeleton.parts[]``: ``index`` and ``name`` per part, from
      ``_skeleton_state_payload`` (every part, skinned or not). Used for part
      names when ``part_names`` is not given.
    * ``state.archive_refit_assets[]``: ``path`` and ``part_indices`` per
      source file, from ``RustMeshAuthoringSession.state_payload``. With more
      than one file (a worn set, or a Refit with its reference files) it names
      each part's file.

    ``session_root`` is the folder the manifest lives in; ``file.path`` is
    resolved against it. Without it the relative path is kept as given. A row
    whose file reference has no path keeps an empty ``decoded_path``. A
    texture whose game path is unknown uses its ``label`` as the name.
    ``shared`` marks a game file used by more than one part.
    """

    root = Path(session_root) if session_root is not None else None
    names = _part_names(manifest, part_names)
    sources = _part_source_files(manifest)
    archive_paths = _graph_archive_paths(manifest)
    by_part: dict[int, dict[str, TextureRow]] = {}

    def append_texture_row(part_index: int, row: TextureRow) -> None:
        rows = by_part.setdefault(part_index, {})
        existing = rows.get(row.texture_id)
        if existing is None:
            rows[row.texture_id] = row
        elif not _has_game_path(existing) and _has_game_path(row):
            rows[row.texture_id] = TextureRow(
                existing.texture_id, existing.role, row.game_path, existing.decoded_path,
            )

    for raw in _sequence(manifest.get("textures")):
        if not isinstance(raw, Mapping):
            continue
        reference = raw.get("file")
        reference = reference if isinstance(reference, Mapping) else {}
        texture_id = _texture_id(reference, raw.get("label"))
        if not texture_id:
            continue
        label = str(raw.get("label", "") or "").strip()
        row = TextureRow(
            texture_id=texture_id,
            role=str(raw.get("role", "") or "").strip(),
            game_path=archive_paths.get(_sha(reference)) or label or texture_id,
            decoded_path=_decoded_path(reference, root),
        )
        lods = _sequence(raw.get("material_indices_by_lod"))
        for part_index in _int_values(lods[0] if lods else ()):
            append_texture_row(part_index, row)

    graph = manifest.get("preview_core_material_graph")
    materials = _sequence(graph.get("materials")) if isinstance(graph, Mapping) else ()
    for material in materials:
        if not isinstance(material, Mapping) or _int(material.get("lod_index"), 0) != 0:
            continue
        part_index = _int(material.get("material_index"), -1)
        if part_index < 0:
            continue
        for layer in _sequence(material.get("layers")):
            if not isinstance(layer, Mapping):
                continue
            layer_role = str(layer.get("layer_role", "") or "").strip().casefold()
            for resource in _LAYER_RESOURCES:
                reference = layer.get(resource)
                if not isinstance(reference, Mapping):
                    continue
                archive_path = str(layer.get(f"{resource}_archive_path", "") or "").strip()
                texture_id = _texture_id(reference, archive_path)
                if not texture_id:
                    continue
                append_texture_row(part_index, TextureRow(
                    texture_id=texture_id,
                    role=_layer_texture_role(layer_role, resource),
                    game_path=archive_path or texture_id,
                    decoded_path=_decoded_path(reference, root),
                ))

    users: dict[str, set[int]] = {}
    for part_index, rows in by_part.items():
        for row in rows.values():
            users.setdefault(_share_key(row), set()).add(part_index)

    groups: list[TexturePartGroup] = []
    for part_index in sorted(by_part):
        rows = sorted(
            (
                TextureRow(row.texture_id, row.role, row.game_path, row.decoded_path,
                           len(users.get(_share_key(row), ())) > 1)
                for row in by_part[part_index].values()
            ),
            key=lambda row: (_ROLE_ORDER.get(row.role.casefold(), 99), row.file_name.casefold()),
        )
        groups.append(TexturePartGroup(
            part_index=part_index,
            part_name=names.get(part_index) or f"Part {part_index + 1}",
            source_file=sources.get(part_index, ""),
            rows=tuple(rows),
        ))
    return groups


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _int_values(values: object) -> Iterable[int]:
    for value in _sequence(values):
        index = _int(value, -1)
        if index >= 0:
            yield index


def _sha(reference: Mapping[str, object]) -> str:
    return str(reference.get("sha256", "") or "").strip().upper()


def _texture_id(reference: Mapping[str, object], fallback: object) -> str:
    # The session file name is the resource the editor loaded, so a later live
    # update can name it; the hash or label only stands in without it.
    return (str(reference.get("path", "") or "").strip()
            or _sha(reference) or str(fallback or "").strip())


def _decoded_path(reference: Mapping[str, object], root: Path | None) -> str:
    relative = str(reference.get("path", "") or "").strip()
    if not relative:
        return ""
    return str(root / relative) if root is not None else relative


def _has_game_path(row: TextureRow) -> bool:
    return "/" in row.game_path.replace("\\", "/")


def _share_key(row: TextureRow) -> str:
    if _has_game_path(row):
        return row.game_path.replace("\\", "/").casefold()
    return row.texture_id.casefold()


# Internal role ids, not display text (texture_role_label names them).
_LAYER_MASK_ROLE, _DETAIL_ROLE, _LAYER_ROLE = ("layer_mask", "detail", "layer")


def _layer_texture_role(layer_role: str, resource: str) -> str:
    if resource == "mask":
        role = _LAYER_MASK_ROLE
    elif layer_role in {"", "base"}:
        role = _BASE_LAYER_RESOURCE_ROLES[resource]
    elif layer_role == _DETAIL_ROLE:
        role = _DETAIL_ROLE
    else:
        role = _LAYER_ROLE
    return role


def _part_names(
    manifest: Mapping[str, object],
    explicit: Mapping[int, str] | Sequence[str] | None,
) -> dict[int, str]:
    if isinstance(explicit, Mapping):
        return {_int(key, -1): str(value or "") for key, value in explicit.items()}
    if explicit is not None and not isinstance(explicit, (str, bytes)):
        return {index: str(value or "") for index, value in enumerate(explicit)}
    state = manifest.get("state")
    skeleton = state.get("skeleton") if isinstance(state, Mapping) else None
    names: dict[int, str] = {}
    if isinstance(skeleton, Mapping):
        for part in _sequence(skeleton.get("parts")):
            if isinstance(part, Mapping):
                index = _int(part.get("index"), -1)
                name = str(part.get("name", "") or "").strip()
                if index >= 0 and name:
                    names[index] = name
    return names


def _part_source_files(manifest: Mapping[str, object]) -> dict[int, str]:
    state = manifest.get("state")
    assets = _sequence(state.get("archive_refit_assets")) if isinstance(state, Mapping) else ()
    assets = [asset for asset in assets if isinstance(asset, Mapping)]
    if len(assets) < 2:
        return {}
    files: dict[int, str] = {}
    for asset in assets:
        name = PurePosixPath(str(asset.get("path", "") or "").replace("\\", "/")).name
        for index in _int_values(asset.get("part_indices")):
            files.setdefault(index, name)
    return files


def _graph_archive_paths(manifest: Mapping[str, object]) -> dict[str, str]:
    graph = manifest.get("preview_core_material_graph")
    paths: dict[str, str] = {}
    if not isinstance(graph, Mapping):
        return paths
    for material in _sequence(graph.get("materials")):
        if not isinstance(material, Mapping):
            continue
        for layer in _sequence(material.get("layers")):
            if not isinstance(layer, Mapping):
                continue
            for resource in _LAYER_RESOURCES:
                reference = layer.get(resource)
                archive_path = str(layer.get(f"{resource}_archive_path", "") or "").strip()
                if isinstance(reference, Mapping) and archive_path and _sha(reference):
                    paths.setdefault(_sha(reference), archive_path)
    return paths


ThumbnailDecoder = Callable[[Path, int, str], "QImage | None"]


def decode_texture_thumbnail(path: Path, size: int, role: str = "") -> QImage | None:
    """Decode one texture to a thumbnail; None when it cannot be read.

    Runs on a pool thread only. DDS goes through the project's native preview
    decoder, which caches its PNG in the app temp cache, never beside the
    session's files (the session folder's entry count is validated).
    """

    try:
        if not path.is_file():
            return None
        if path.suffix.casefold() == ".dds":
            from cdmw.core.texture_native import ensure_native_dds_preview_png

            normal_roles = {"normal", "shader_normal", "skin_detail_normal"}
            slot = "normal" if str(role).casefold() in normal_roles else "base"
            preview = ensure_native_dds_preview_png(path, max_dimension=max(64, size * 2), slot_kind=slot)
            if preview is None:
                return None
            image = QImage(str(preview))
        else:
            image = QImage(str(path))
    except Exception:  # A thumbnail is decoration; an unreadable file just shows none.
        return None
    if image.isNull():
        return None
    return image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)


class _ThumbnailState:
    """Shared by the loader and its jobs; it outlives the loader object."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.closed = False
        self.cache: OrderedDict[tuple[str, int, int], QImage | None] = OrderedDict()

    def close(self) -> None:
        with self.lock:
            self.closed = True


class _ThumbnailJob(QRunnable):
    def __init__(self, state: _ThumbnailState, deliver: Callable[[int, str, QImage], None],
                 generation: int, path: str, role: str, size: int, decoder: ThumbnailDecoder) -> None:
        super().__init__()
        self._state, self._deliver = state, deliver
        self._generation, self._path, self._role, self._size = generation, path, role, size
        self._decoder = decoder

    def run(self) -> None:
        image: QImage | None = None
        try:
            stat = os.stat(self._path)
        except OSError:
            stat = None
        if stat is not None:
            key = (self._path, self._size, stat.st_mtime_ns)
            with self._state.lock:
                if self._state.closed:
                    return
                hit = key in self._state.cache
                if hit:
                    self._state.cache.move_to_end(key)
                    image = self._state.cache[key]
            if not hit:
                image = self._decoder(Path(self._path), self._size, self._role)
                with self._state.lock:
                    self._state.cache[key] = image
                    while len(self._state.cache) > _THUMBNAIL_CACHE_LIMIT:
                        self._state.cache.popitem(last=False)
        with self._state.lock:
            # Emitting under the lock means no job reaches a deleted loader
            # once close() has returned.
            if not self._state.closed:
                self._deliver(self._generation, self._path, image if image is not None else QImage())


class TextureThumbnailLoader(QObject):
    """Decodes thumbnails off the UI thread; results arrive as a queued signal."""

    thumbnail_ready = Signal(int, str, QImage)
    """generation, decoded path, image (null when there is none)."""

    def __init__(self, parent: QObject | None = None, *, pool: QThreadPool | None = None,
                 decoder: ThumbnailDecoder | None = None, size: int = THUMBNAIL_SIZE) -> None:
        super().__init__(parent)
        self._state = _ThumbnailState()
        self._pool = pool or QThreadPool.globalInstance()
        self._decoder = decoder or decode_texture_thumbnail
        self.size = int(size)
        state = self._state
        self.destroyed.connect(lambda *_args: state.close())

    def queue_texture_thumbnail(self, generation: int, path: str, role: str = "") -> None:
        if self._state.closed or not path:
            return
        self._pool.start(_ThumbnailJob(self._state, self.thumbnail_ready.emit, int(generation),
                                       str(path), str(role), self.size, self._decoder))

    def shutdown(self) -> None:
        self._state.close()


class MeshEditorTexturesPanel(QDockWidget):
    """Dockable, read-only list of the open session's textures, per part."""

    texture_activated = Signal(str)
    """A texture row's texture_id, on double-click."""

    def __init__(self, parent: QWidget | None = None, *,
                 thumbnail_loader: TextureThumbnailLoader | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MeshEditorTexturesDock")
        self.setWindowTitle("Textures")
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self._generation = 0
        self._items_by_path: dict[str, list[QTreeWidgetItem]] = {}
        self._session_request = 0
        self._manifest_readers: set[QObject] = set()
        self.groups: list[TexturePartGroup] = []

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 4, 6, 4)
        self.stack = QStackedWidget(body)
        self.placeholder_label = QLabel("Open a mesh to see its textures.")
        self.placeholder_label.setObjectName("HintLabel")
        self.placeholder_label.setWordWrap(True)
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tree = QTreeWidget()
        self.tree.setObjectName("MeshEditorTexturesTree")
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Preview", "Role", "Game file", "State"])
        self.tree.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.stack.addWidget(self.placeholder_label)
        self.stack.addWidget(self.tree)
        layout.addWidget(self.stack)
        self.setWidget(body)

        self.thumbnails = thumbnail_loader or TextureThumbnailLoader(self)
        self.thumbnails.thumbnail_ready.connect(self._on_thumbnail_ready)
        self.clear()

    def set_manifest(self, manifest: Mapping[str, object] | None, *,
                     session_root: str | os.PathLike[str] | None = None,
                     part_names: Mapping[int, str] | Sequence[str] | None = None) -> None:
        """Show a session's textures; None clears the panel."""

        if manifest is None:
            self.clear()
            return
        groups = texture_rows_from_manifest(manifest, session_root=session_root, part_names=part_names)
        self._generation += 1
        self._items_by_path = {}
        self.groups = groups
        self.tree.clear()
        if not groups:
            self.placeholder_label.setText("No textures were resolved for this mesh.")
            self.stack.setCurrentWidget(self.placeholder_label)
            return
        requests: dict[str, str] = {}
        for group in groups:
            parent = QTreeWidgetItem(self.tree)
            parent.setText(COLUMN_THUMBNAIL, group.group_heading)
            parent.setFirstColumnSpanned(True)
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for row in group.rows:
                item = QTreeWidgetItem(parent)
                item.setData(COLUMN_THUMBNAIL, TEXTURE_ID_ROLE, row.texture_id)
                item.setText(COLUMN_ROLE, texture_role_label(row.role))
                item.setText(COLUMN_FILE, row.file_name)
                item.setToolTip(COLUMN_FILE, row.game_path)
                if row.shared:
                    item.setText(COLUMN_STATE, "Shared")
                    item.setToolTip(COLUMN_STATE, "Used by more than one part of this model.")
                if row.decoded_path:
                    self._items_by_path.setdefault(row.decoded_path, []).append(item)
                    requests.setdefault(row.decoded_path, row.role)
        self.tree.expandAll()
        self.tree.resizeColumnToContents(COLUMN_ROLE)
        self.stack.setCurrentWidget(self.tree)
        for path, role in requests.items():
            self.thumbnails.queue_texture_thumbnail(self._generation, path, role)

    def clear(self) -> None:
        self._generation += 1
        self._items_by_path = {}
        self.groups = []
        self.tree.clear()
        self.placeholder_label.setText("Open a mesh to see its textures.")
        self.stack.setCurrentWidget(self.placeholder_label)

    def shutdown(self) -> None:
        """Drop pending thumbnails; the host calls this before tearing the page down."""

        self.thumbnails.shutdown()

    def texture_item(self, texture_id: str) -> QTreeWidgetItem | None:
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child.data(COLUMN_THUMBNAIL, TEXTURE_ID_ROLE) == texture_id:
                    return child
        return None

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        texture_id = item.data(COLUMN_THUMBNAIL, TEXTURE_ID_ROLE)
        if texture_id:
            self.texture_activated.emit(str(texture_id))

    def _on_thumbnail_ready(self, generation: int, path: str, image: QImage) -> None:
        if generation != self._generation or image.isNull():
            return
        items = self._items_by_path.get(path, ())
        if not items:
            return
        icon = QIcon(QPixmap.fromImage(image))
        for item in items:
            item.setIcon(COLUMN_THUMBNAIL, icon)

    # ----- a session's manifest, read off the UI thread --------------------
    def show_session(self, session_root: str | os.PathLike[str] | None) -> None:
        """Show the textures of the session in ``session_root``; None clears the panel.

        The session manifest holds the editor's whole state and can be large, so it is
        read on a worker; a later call wins over a read still in flight.
        """

        self._session_request += 1
        if session_root is None:
            self.clear()
            return
        reader = _ManifestReader(Path(session_root), self._session_request)
        reader.signals.loaded.connect(self._on_manifest_loaded)
        self._manifest_readers.add(reader.signals)
        reader.signals.loaded.connect(lambda *_args, signals=reader.signals: self._manifest_readers.discard(signals))
        QThreadPool.globalInstance().start(reader)

    def _on_manifest_loaded(self, request: int, root: str, manifest: object) -> None:
        if request != self._session_request:
            return
        if isinstance(manifest, Mapping):
            self.set_manifest(manifest, session_root=root)
        else:
            self.clear()


class _ManifestReaderSignals(QObject):
    loaded = Signal(int, str, object)


class _ManifestReader(QRunnable):
    def __init__(self, root: Path, request: int) -> None:
        super().__init__()
        self.root = root
        self.request = request
        self.signals = _ManifestReaderSignals()

    def run(self) -> None:
        import json

        try:
            manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = None
        try:
            self.signals.loaded.emit(self.request, str(self.root), manifest)
        except RuntimeError:
            pass  # the panel went away while the manifest was read


DOCK_LAYOUT_KEY = "mesh_editor/dock_host_state"


def remember_dock_layout(host: object, dock: QDockWidget, settings: object, key: str = DOCK_LAYOUT_KEY) -> None:
    """Restore where the Mesh Editor's docks were, and save it whenever one moves,
    floats, docks again or is closed (Fredric: the panel can be "freely moved around")."""

    restore = getattr(host, "restoreState", None)
    value = settings.value(key, None) if settings is not None else None
    if callable(restore) and value:
        try:
            restore(value)
        except (TypeError, ValueError, RuntimeError):
            pass

    def save(*_args: object) -> None:
        save_state = getattr(host, "saveState", None)
        if settings is None or not callable(save_state):
            return
        try:
            settings.setValue(key, save_state())
        except RuntimeError:
            pass  # the page is being torn down

    dock.dockLocationChanged.connect(save)
    dock.topLevelChanged.connect(save)
    dock.visibilityChanged.connect(save)
