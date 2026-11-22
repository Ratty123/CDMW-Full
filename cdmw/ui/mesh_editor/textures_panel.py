"""Read-only Textures dock for the Mesh Editor (live texture editing, stage 1).

The panel lists each part's textures from the session manifest the Mesh
Editor already writes for the Rust editor. It resolves nothing itself: the
model comes from :func:`texture_rows_from_manifest`, a pure function that
needs no Qt, and the widget is a thin view over it. Thumbnails are decoded on
a Qt thread pool and delivered back through a queued signal.
"""

from __future__ import annotations

import dataclasses
import re
import os
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QEvent, QObject, QRect, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDockWidget,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.layout_utils import scaled_px

#: A thumbnail's side in logical pixels at the 11pt reference font (34-36px at 9-10pt);
#: it follows the panel's font, and is decoded at the screen's device pixel ratio.
THUMBNAIL_SIZE = 40
TEXTURE_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 1
#: The part a row belongs to (a part row and each of its textures); a file header has none.
PART_INDEX_ROLE = int(Qt.ItemDataRole.UserRole) + 2
NO_PART = -1

# The thumbnail sits in front of the role, so one column holds both.
COLUMN_THUMBNAIL = 0
COLUMN_ROLE = 0
COLUMN_FILE = 1
COLUMN_STATE = 2

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
    #: The hash the editor loaded this texture with; live edits name it (step 8).
    source_sha256: str = ""
    #: An edit of this file shows on this part of the model while the user paints: the
    #: 3D view samples it, as a texture of its own or as a layer the shader combines
    #: (B item 6). Until the editor says which it samples (``with_shown_live_textures``),
    #: only the textures it loaded itself count.
    in_renderer: bool = False

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
            rows[row.texture_id] = dataclasses.replace(existing, game_path=row.game_path)

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
            source_sha256=_sha(reference).lower(),
            in_renderer=bool(_sha(reference)),
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
                    source_sha256=_sha(reference).lower(),
                ))

    users: dict[str, set[int]] = {}
    for part_index, rows in by_part.items():
        for row in rows.values():
            users.setdefault(_share_key(row), set()).add(part_index)

    groups: list[TexturePartGroup] = []
    for part_index in sorted(by_part):
        rows = sorted(
            (
                dataclasses.replace(row, shared=len(users.get(_share_key(row), ())) > 1)
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


#: A colour CDMW made from several files (no game file of its own), as the row says it.
NOT_ONE_FILE_STATE = "Not one file"
NOT_ONE_FILE_REASON = ("CDMW made this colour from several files, so there is no game file to write it to. "
                       "Edit one of the files it is made from.")
EDIT_INSTEAD_TEXT = "Edit instead: {files}"
#: The roles that feed a shader-combined colour, the first ones offered.
_CONTRIBUTING_ROLES = ("layer_mask", "detail", "layer", "base", "mask")


#: The name CDMW gives a colour it generates for the view from a layered material
#: (``_encode_generated_material_channel`` in mesh_rust_authoring).
_GENERATED_NAME = re.compile(r"^lod-\d+-material-\d+-[a-z_]+\.dds$", re.IGNORECASE)


def made_from_several_files(row: TextureRow) -> bool:
    """A colour CDMW generated for the view: no game file of its own."""

    return not _has_game_path(row) and bool(_GENERATED_NAME.match(row.file_name))


def contributing_rows(group: "TexturePartGroup", row: TextureRow) -> tuple[TextureRow, ...]:
    """The same part's game files a generated colour is made from, masks and detail first."""

    if not made_from_several_files(row):
        return ()
    others = [other for other in group.rows if other is not row and _has_game_path(other) and other.decoded_path]

    def rank(other: TextureRow) -> int:
        return _CONTRIBUTING_ROLES.index(other.role) if other.role in _CONTRIBUTING_ROLES else len(_CONTRIBUTING_ROLES)

    return tuple(sorted(others, key=rank))


def shown_live_by_source(textures: object) -> dict[str, frozenset[int]]:
    """The editor's ``live_textures`` event as source hash -> the parts an edit shows on."""

    shown: dict[str, frozenset[int]] = {}
    for entry in _sequence(textures):
        if not isinstance(entry, Mapping):
            continue
        sha = str(entry.get("source_sha256", "") or "").strip().lower()
        if sha:
            shown[sha] = shown.get(sha, frozenset()) | frozenset(_int_values(entry.get("parts")))
    return shown


def with_shown_live_textures(groups: Sequence[TexturePartGroup],
                             shown: Mapping[str, frozenset[int]]) -> list[TexturePartGroup]:
    """``groups`` with each row's ``in_renderer`` as the editor reported it: True when the
    3D view samples that file on that part (B item 6)."""

    return [dataclasses.replace(group, rows=tuple(
        dataclasses.replace(row, in_renderer=group.part_index in shown.get(row.source_sha256.lower(), ()))
        for row in group.rows)) for group in groups]


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


def decode_texture_thumbnail(
    path: Path,
    size: int,
    role: str = "",
    *,
    stop_event: threading.Event | None = None,
) -> QImage | None:
    """Decode one texture to a thumbnail; None when it cannot be read.

    Runs on a pool thread only. DDS goes through the project's native preview
    decoder, which caches its PNG in the app temp cache, never beside the
    session's files (the session folder's entry count is validated).
    """

    try:
        if stop_event is not None and stop_event.is_set():
            return None
        if not path.is_file():
            return None
        if path.suffix.casefold() == ".dds":
            from cdmw.core.texture_native import ensure_native_dds_preview_png

            normal_roles = {"normal", "shader_normal", "skin_detail_normal"}
            slot = "normal" if str(role).casefold() in normal_roles else "base"
            preview = ensure_native_dds_preview_png(
                path,
                max_dimension=max(64, size * 2),
                slot_kind=slot,
                stop_event=stop_event,
            )
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


_THUMBNAIL_POOL: QThreadPool | None = None
_THUMBNAIL_POOL_LOCK = threading.Lock()
_CHECKER_BACKING_CACHE: dict[tuple[int, int], QPixmap] = {}


def _default_thumbnail_pool() -> QThreadPool:
    """Gentle 2-thread pool dedicated to thumbnail decoding so UI/GIL & global jobs stay smooth."""

    global _THUMBNAIL_POOL
    if _THUMBNAIL_POOL is not None:
        return _THUMBNAIL_POOL
    with _THUMBNAIL_POOL_LOCK:
        if _THUMBNAIL_POOL is None:
            pool = QThreadPool()
            pool.setMaxThreadCount(2)
            _THUMBNAIL_POOL = pool
        return _THUMBNAIL_POOL


class _ThumbnailState:
    """Shared by the loader and its jobs; it outlives the loader object."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.closed = False
        self.active_generation = 0
        self.stop_event = threading.Event()
        self.cache: OrderedDict[tuple[str, int, int], QImage | None] = OrderedDict()

    def set_generation(self, generation: int) -> None:
        with self.lock:
            gen = int(generation)
            if gen > self.active_generation:
                self.stop_event.set()
                self.stop_event = threading.Event()
                self.active_generation = gen

    def current_stop_event(self, generation: int) -> threading.Event | None:
        with self.lock:
            if self.closed or (self.active_generation > 0 and generation != self.active_generation):
                return None
            return self.stop_event

    def is_stale(self, generation: int) -> bool:
        with self.lock:
            return self.closed or (self.active_generation > 0 and generation != self.active_generation)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            self.stop_event.set()


class _ThumbnailJob(QRunnable):
    def __init__(self, state: _ThumbnailState, deliver: Callable[[int, str, QImage], None],
                 generation: int, path: str, role: str, size: int, decoder: ThumbnailDecoder) -> None:
        super().__init__()
        self._state, self._deliver = state, deliver
        self._generation, self._path, self._role, self._size = generation, path, role, size
        self._decoder = decoder

    def run(self) -> None:
        stop_event = self._state.current_stop_event(self._generation)
        if stop_event is None:
            return
        image: QImage | None = None
        try:
            stat = os.stat(self._path)
        except OSError:
            stat = None
        if stat is not None:
            key = (self._path, self._size, stat.st_mtime_ns)
            with self._state.lock:
                if self._state.closed or (
                    self._state.active_generation > 0 and self._generation != self._state.active_generation
                ):
                    return
                hit = key in self._state.cache
                if hit:
                    self._state.cache.move_to_end(key)
                    image = self._state.cache[key]
            if not hit:
                if self._state.is_stale(self._generation):
                    return
                if self._decoder is decode_texture_thumbnail:
                    image = decode_texture_thumbnail(
                        Path(self._path), self._size, self._role, stop_event=stop_event,
                    )
                else:
                    image = self._decoder(Path(self._path), self._size, self._role)
                if not stop_event.is_set():
                    with self._state.lock:
                        self._state.cache[key] = image
                        while len(self._state.cache) > _THUMBNAIL_CACHE_LIMIT:
                            self._state.cache.popitem(last=False)
        with self._state.lock:
            # Emitting under the lock means no job reaches a deleted loader
            # once close() has returned.
            if not self._state.closed and (
                self._state.active_generation <= 0 or self._generation == self._state.active_generation
            ):
                self._deliver(self._generation, self._path, image if image is not None else QImage())


class TextureThumbnailLoader(QObject):
    """Decodes thumbnails off the UI thread; results arrive as a queued signal."""

    thumbnail_ready = Signal(int, str, QImage)
    """generation, decoded path, image (null when there is none)."""

    def __init__(self, parent: QObject | None = None, *, pool: QThreadPool | None = None,
                 decoder: ThumbnailDecoder | None = None, size: int = THUMBNAIL_SIZE) -> None:
        super().__init__(parent)
        self._state = _ThumbnailState()
        self._pool = pool if pool is not None else _default_thumbnail_pool()
        self._decoder = decoder or decode_texture_thumbnail
        self.size = int(size)
        state = self._state
        self.destroyed.connect(lambda *_args: state.close())

    def set_generation(self, generation: int) -> None:
        """Advance active generation so queued obsolete jobs cancel before decoding."""

        self._state.set_generation(generation)

    def queue_texture_thumbnail(self, generation: int, path: str, role: str = "", *, priority: int = 0) -> None:
        if self._state.closed or not path:
            return
        self._state.set_generation(generation)
        self._pool.start(
            _ThumbnailJob(
                self._state, self.thumbnail_ready.emit, int(generation),
                str(path), str(role), self.size, self._decoder,
            ),
            int(priority),
        )

    def shutdown(self) -> None:
        self._state.close()


def _checker_backing(side: int, border: int) -> QPixmap:
    """Cached checker + border template painted once per (side, border) on the UI thread."""

    key = (side, border)
    cached = _CHECKER_BACKING_CACHE.get(key)
    if cached is not None:
        return cached
    backing = QPixmap(side, side)
    backing.fill(Qt.GlobalColor.transparent)
    painter = QPainter(backing)
    try:
        inner = max(2, side - border * 2)
        cell = max(4, side // 6)
        c1 = QColor("#23272e")
        c2 = QColor("#2d323b")
        painter.fillRect(border, border, inner, inner, c1)
        for y in range(border, side - border, cell):
            for x in range(border, side - border, cell):
                if ((x - border) // cell + (y - border) // cell) % 2:
                    w = min(cell, side - border - x)
                    h = min(cell, side - border - y)
                    painter.fillRect(x, y, w, h, c2)
    finally:
        painter.end()
    if len(_CHECKER_BACKING_CACHE) >= 24:
        _CHECKER_BACKING_CACHE.clear()
    _CHECKER_BACKING_CACHE[key] = backing
    return backing


def _frame_thumbnail_pixmap(image: QImage, device_side: int, dpr: float) -> QPixmap:
    """Paint any decoded texture into a uniform framed square with subtle checker backing."""

    side = max(4, int(device_side))
    border = max(1, int(round(dpr)))
    inner = max(2, side - border * 2)
    pixmap = _checker_backing(side, border).copy()
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if image.width() == inner and image.height() == inner:
            scaled = image
        else:
            scaled = image.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        dx = border + (inner - scaled.width()) // 2
        dy = border + (inner - scaled.height()) // 2
        painter.drawImage(QRect(dx, dy, scaled.width(), scaled.height()), scaled)
        painter.setPen(QPen(QColor("#4c5561"), border))
        half = border // 2
        painter.drawRect(half, half, side - border, side - border)
    finally:
        painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


class MeshEditorTexturesPanel(QDockWidget):
    """Dockable, read-only list of the open session's textures, per part.

    Compact: one line per part, closed until it is opened, and one line per texture
    with a small thumbnail, its role, its game file and its state. When the session
    holds several files (a worn set), each file is named once, as a header over its
    parts, instead of after every part's name.
    """

    texture_activated = Signal(str)
    #: Why a double-clicked row cannot be edited (a colour made from several files).
    texture_refused = Signal(str)
    """A texture row's texture_id, on double-click."""
    #: The part whose row, or one of whose textures, the pointer is over; NO_PART when
    #: it left. The Mesh Editor lights that part up in the 3D view.
    part_hovered = Signal(int)
    #: Whether a session's textures are listed (False once the mesh closes or another loads).
    session_shown = Signal(bool)
    #: The panel's own close button was pressed.
    close_requested = Signal()

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
        self._roles_by_path: dict[str, str] = {}
        self._paths_by_part: dict[int, list[str]] = {}
        self._requested_paths: set[str] = set()
        self._part_items_by_index: dict[int, QTreeWidgetItem] = {}
        self._framed_icons: OrderedDict[tuple[str, int, int, int], QIcon] = OrderedDict()
        self._icons_by_path: dict[tuple[str, int, int], QIcon] = {}
        self._applied_icon_key_by_path: dict[str, tuple[int, int, int]] = {}
        self._pending_thumbnails: dict[str, QImage] = {}
        self._column_metrics_cache_key: tuple[object, ...] | None = None
        self._cached_role_w = 0
        self._cached_state_w = 0
        self._cached_min_file_w = 0
        self._session_request = 0
        self._manifest_readers: set[QObject] = set()
        self.groups: list[TexturePartGroup] = []
        #: What the editor said an edit shows on (B item 6); None until it says.
        self._shown_live: Mapping[str, frozenset[int]] | None = None
        self._session_root: str | None = None
        #: The parts the user opened, kept while the same session's list is rebuilt.
        self._opened_parts: set[int] = set()
        self._opened_parts_root: str | None = None
        self._has_session = False
        self._hovered_part = NO_PART
        self._ui_font: QFont | None = None
        self._user_resized_cols: set[int] = set()
        self._programmatic_column_resize = False
        self._header_user_dragging = False
        self._fit_columns_timer = QTimer(self)
        self._fit_columns_timer.setSingleShot(True)
        self._fit_columns_timer.setInterval(0)
        self._fit_columns_timer.timeout.connect(self._fit_columns)
        self._thumbnail_flush_timer = QTimer(self)
        self._thumbnail_flush_timer.setSingleShot(True)
        self._thumbnail_flush_timer.setInterval(0)
        self._thumbnail_flush_timer.timeout.connect(self._flush_pending_thumbnails)

        body = QWidget(self)
        self._body = body
        layout = QVBoxLayout(body)
        pad = scaled_px(4, body)
        layout.setContentsMargins(pad, scaled_px(2, body), pad, pad)
        self.stack = QStackedWidget(body)
        self.placeholder_label = QLabel("Open a mesh to see its textures.")
        self.placeholder_label.setObjectName("HintLabel")
        self.placeholder_label.setWordWrap(True)
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tree = QTreeWidget()
        self.tree.setObjectName("MeshEditorTexturesTree")
        self.tree.setProperty("_cdmwPrimaryColumn", COLUMN_FILE)
        self.tree.setProperty("_cdmwKeepElide", True)
        self.tree.setProperty("_cdmwKeepFixedColumns", True)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Texture", "Game file", "State"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col in (COLUMN_ROLE, COLUMN_FILE, COLUMN_STATE):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        header.sectionResized.connect(self._on_header_section_resized)
        header.viewport().installEventFilter(self)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemCollapsed.connect(self._on_item_collapsed)
        # Pointing at a part or a texture lights its part up in the 3D view.
        self.tree.setMouseTracking(True)
        self.tree.itemEntered.connect(self._on_item_entered)
        self.tree.viewport().installEventFilter(self)
        self.stack.addWidget(self.placeholder_label)
        self.stack.addWidget(self.tree)
        layout.addWidget(self.stack)
        self.setWidget(body)

        self.thumbnails = thumbnail_loader or TextureThumbnailLoader(self)
        self.thumbnails.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._fit_to_font()
        self.clear()

    # ----- sizes: logical pixels that follow the font and the screen ---------
    def thumbnail_side(self) -> int:
        """A thumbnail's side in logical pixels, following the panel's font."""

        return scaled_px(THUMBNAIL_SIZE, self.tree)

    def _device_pixel_ratio(self) -> float:
        """The scale of the screen the panel is on (1.5 at 150 %)."""

        try:
            return max(1.0, float(self.devicePixelRatioF()))
        except RuntimeError:
            return 1.0

    def _thumbnail_device_side(self) -> int:
        # Decoded for the screen's scale: sharp at 150 %, not oversized at 100 %.
        return max(1, int(round(self.thumbnail_side() * self._device_pixel_ratio())))

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        hint = super().sizeHint()
        least = self._body.minimumSize()
        preferred_w = max(least.width(), scaled_px(460, self.tree))
        return QSize(preferred_w, max(hint.height(), least.height()))

    def _fit_to_font(self) -> None:
        """Icon size, indentation and the least usable size, from the font in use."""

        side = self.thumbnail_side()
        self.tree.setIconSize(QSize(side, side))
        indent = scaled_px(12, self.tree)
        self.tree.setIndentation(indent)
        metrics = self.tree.fontMetrics()
        # Never crushed: room for the thumbnail + role, a readable file name slice,
        # and the state, plus the header and at least five compact part rows.
        width = (
            indent * 2
            + side
            + metrics.horizontalAdvance("Base colour")
            + metrics.horizontalAdvance("Shared")
            + metrics.averageCharWidth() * 12
            + scaled_px(28, self.tree)
        )
        part_row = metrics.height() + scaled_px(8, self.tree)
        self._body.setMinimumSize(width, part_row * 6 + scaled_px(24, self.tree))

    def _schedule_fit_columns(self) -> None:
        if not self._fit_columns_timer.isActive():
            self._fit_columns_timer.start()

    def _invalidate_column_metrics(self) -> None:
        self._column_metrics_cache_key = None

    def _fit_columns(self) -> None:
        """Keep Texture and State compact while Game file takes all flexible width."""

        header = self.tree.header()
        if header is None or header.count() < 3:
            return
        header_item = self.tree.headerItem()
        role_hdr = header_item.text(COLUMN_ROLE) if header_item is not None else "Texture"
        file_hdr = header_item.text(COLUMN_FILE) if header_item is not None else "Game file"
        state_hdr = header_item.text(COLUMN_STATE) if header_item is not None else "State"
        side = self.thumbnail_side()
        indent = max(8, self.tree.indentation())
        tree_font = self.tree.font()
        cache_key = (
            self._generation,
            tree_font.family(),
            tree_font.pointSizeF(),
            indent,
            side,
            role_hdr,
            file_hdr,
            state_hdr,
        )
        if cache_key != self._column_metrics_cache_key:
            metrics = self.tree.fontMetrics()
            header_metrics = header.fontMetrics()
            has_file_headers = any(group.source_file for group in self.groups)
            leaf_depth = 3 if has_file_headers else 2

            unique_roles = {texture_role_label(row.role) for group in self.groups for row in group.rows}
            unique_roles.add("Base colour")
            max_role_w = max(metrics.horizontalAdvance(text) for text in unique_roles)
            self._cached_role_w = max(
                header_metrics.horizontalAdvance(role_hdr) + scaled_px(24, self.tree),
                leaf_depth * indent + side + max_role_w + scaled_px(40, self.tree),
            )

            has_not_one_file = any(made_from_several_files(row) for group in self.groups for row in group.rows)
            has_shared = (
                not has_not_one_file
                and any(row.shared for group in self.groups for row in group.rows)
            )
            state_texts = [state_hdr]
            if has_not_one_file:
                state_texts.append(NOT_ONE_FILE_STATE)
            elif has_shared:
                state_texts.append("Shared")
            max_state_w = max(
                max(metrics.horizontalAdvance(text), header_metrics.horizontalAdvance(text))
                for text in state_texts
            )
            self._cached_state_w = max(scaled_px(68, self.tree), max_state_w + scaled_px(28, self.tree))
            self._cached_min_file_w = max(
                scaled_px(96, self.tree),
                header_metrics.horizontalAdvance(file_hdr) + scaled_px(12, self.tree),
            )
            self._column_metrics_cache_key = cache_key

        role_w = header.sectionSize(COLUMN_ROLE) if COLUMN_ROLE in self._user_resized_cols else self._cached_role_w
        state_w = header.sectionSize(COLUMN_STATE) if COLUMN_STATE in self._user_resized_cols else self._cached_state_w

        viewport_w = self.tree.viewport().width()
        if viewport_w <= 40:
            viewport_w = max(
                self.tree.width() - scaled_px(4, self.tree),
                self.sizeHint().width() - scaled_px(12, self.tree),
            )
        min_file_w = self._cached_min_file_w
        if COLUMN_FILE in self._user_resized_cols:
            file_w = max(min_file_w, header.sectionSize(COLUMN_FILE))
        else:
            file_w = max(min_file_w, viewport_w - role_w - state_w)

        min_section = scaled_px(44, self.tree)
        if (
            header.minimumSectionSize() == min_section
            and header.sectionSize(COLUMN_ROLE) == role_w
            and header.sectionSize(COLUMN_FILE) == file_w
            and header.sectionSize(COLUMN_STATE) == state_w
        ):
            return
        self._programmatic_column_resize = True
        try:
            if header.minimumSectionSize() != min_section:
                header.setMinimumSectionSize(min_section)
            if header.sectionSize(COLUMN_ROLE) != role_w:
                header.resizeSection(COLUMN_ROLE, role_w)
            if header.sectionSize(COLUMN_FILE) != file_w:
                header.resizeSection(COLUMN_FILE, file_w)
            if header.sectionSize(COLUMN_STATE) != state_w:
                header.resizeSection(COLUMN_STATE, state_w)
        finally:
            self._programmatic_column_resize = False

    def _on_header_section_resized(self, logical_index: int, _old_size: int, _new_size: int) -> None:
        if self._programmatic_column_resize or not self._header_user_dragging:
            return
        self._user_resized_cols.add(logical_index)
        if logical_index != COLUMN_FILE and COLUMN_FILE not in self._user_resized_cols:
            self._fit_columns()

    def sync_ui_font(self, font: QFont, data_font: QFont | None = None) -> None:
        """The Mesh Editor's UI font on the title, the list and its header, as on the
        Texture Editor panel under it; the sizes that follow the font are fitted again."""

        _ = data_font
        self._ui_font = QFont(font)
        for widget in (self, self._body, self.placeholder_label, self.tree, self.tree.header()):
            own = QFont(widget.font())
            own.setFamilies(font.families() or [font.family()])
            own.setPointSizeF(font.pointSizeF())
            if widget is self and own == QApplication.font("QDockWidget"):
                # Qt paints a dock's title in the font it read when the dock was made
                # unless the dock's own font differs from its class font.
                own.setStyleHint(QFont.StyleHint.System if own.styleHint() != QFont.StyleHint.System
                                 else QFont.StyleHint.AnyStyle)
            if own != widget.font() or not widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
                widget.setFont(own)
        before = self.thumbnail_side()
        self._fit_to_font()
        self._invalidate_column_metrics()
        self._restyle_headers()
        self._fit_columns()
        if self.thumbnail_side() != before:
            self._requested_paths.clear()
            self._request_thumbnails()

    def event(self, event: QEvent) -> bool:
        # Moved to a screen with another scale: re-decode expanded parts at the new DPR.
        if event.type() == getattr(QEvent.Type, "DevicePixelRatioChange", None) and hasattr(self, "thumbnails"):
            self._requested_paths.clear()
            self._request_thumbnails()
        return super().event(event)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._schedule_fit_columns()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        # The host decides: it hides the panel and remembers that the user closed it.
        event.ignore()
        self.close_requested.emit()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().hideEvent(event)
        self._set_hovered_part(NO_PART)

    # ----- pointing at a part ---------------------------------------------------
    def _on_item_entered(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        part = item.data(COLUMN_THUMBNAIL, PART_INDEX_ROLE) if item is not None else None
        self._set_hovered_part(NO_PART if part is None else int(part))

    def _set_hovered_part(self, part_index: int) -> None:
        if part_index != self._hovered_part:
            self._hovered_part = part_index
            self.part_hovered.emit(part_index)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        etype = event.type()
        if watched is self.tree.header().viewport():
            if etype in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                self._header_user_dragging = True
            elif etype == QEvent.Type.MouseButtonRelease:
                self._header_user_dragging = False
        elif watched is self.tree.viewport():
            if etype == QEvent.Type.Resize:
                self._schedule_fit_columns()
            elif etype == QEvent.Type.Leave:
                self._set_hovered_part(NO_PART)
            elif etype == QEvent.Type.MouseMove and self._hovered_part != NO_PART and self.tree.itemAt(event.position().toPoint()) is None:
                self._set_hovered_part(NO_PART)  # over the empty space under the rows
        return super().eventFilter(watched, event)

    @property
    def has_session(self) -> bool:
        """A session's textures are listed (or it has none); False with no mesh open."""

        return self._has_session

    def _set_has_session(self, shown: bool) -> None:
        if shown != self._has_session:
            self._has_session = shown
            self.session_shown.emit(shown)

    # ----- the list -----------------------------------------------------------
    def _tree_style_tokens(self) -> tuple[QBrush, QBrush, QBrush, QFont, QFont, QSize]:
        app = QApplication.instance()
        palette = app.palette() if app is not None else self.tree.palette()
        header_bg = QBrush(palette.color(QPalette.ColorRole.AlternateBase))
        part_fg = QBrush(palette.color(QPalette.ColorRole.ButtonText))
        muted_fg = QBrush(palette.color(QPalette.ColorRole.PlaceholderText))
        base_font = QFont(self.tree.font())
        bold_font = QFont(base_font)
        bold_font.setBold(True)
        part_font = QFont(base_font)
        part_font.setWeight(QFont.Weight.Medium)
        leaf_h = max(self.thumbnail_side(), self.tree.fontMetrics().height()) + scaled_px(6, self.tree)
        return header_bg, part_fg, muted_fg, bold_font, part_font, QSize(0, leaf_h)

    def set_manifest(self, manifest: Mapping[str, object] | None, *,
                     session_root: str | os.PathLike[str] | None = None,
                     part_names: Mapping[int, str] | Sequence[str] | None = None) -> None:
        """Show a session's textures; None clears the panel."""

        if manifest is None:
            self.clear()
            return
        groups = texture_rows_from_manifest(manifest, session_root=session_root, part_names=part_names)
        if self._shown_live is not None:
            groups = with_shown_live_textures(groups, self._shown_live)
        root = str(session_root) if session_root is not None else None
        same_session = root is not None and root == self._opened_parts_root
        if not same_session:
            # Another mesh: its list starts closed. The same session's list, rebuilt,
            # keeps the parts the user opened.
            self._opened_parts = set()
            self._opened_parts_root = root
            self._icons_by_path.clear()
        opened = set(self._opened_parts)
        self._generation += 1
        self.thumbnails.set_generation(self._generation)
        self._pending_thumbnails.clear()
        self._thumbnail_flush_timer.stop()
        self._items_by_path = {}
        self._roles_by_path = {}
        self._paths_by_part = {}
        self._requested_paths = set()
        self._part_items_by_index = {}
        self._applied_icon_key_by_path = {}
        self._invalidate_column_metrics()
        self.groups = groups
        self._set_hovered_part(NO_PART)
        if not groups:
            self.tree.clear()
            self.placeholder_label.setText("No textures were resolved for this mesh.")
            self.stack.setCurrentWidget(self.placeholder_label)
            self._set_has_session(True)
            return

        header_bg, part_fg, muted_fg, bold_font, part_font, leaf_size = self._tree_style_tokens()
        device_side = self._thumbnail_device_side()
        dpr_mill = int(round(self._device_pixel_ratio() * 1000))
        file_items: dict[str, QTreeWidgetItem] = {}
        restored_open: set[int] = set()

        self.tree.setUpdatesEnabled(False)
        prev_blocked = self.tree.blockSignals(True)
        try:
            self.tree.clear()
            for group in groups:
                holder: QTreeWidget | QTreeWidgetItem = self.tree
                if group.source_file:
                    # The file is named once, over its parts.
                    holder = file_items.get(group.source_file)
                    if holder is None:
                        holder = file_items[group.source_file] = QTreeWidgetItem(self.tree)
                        holder.setText(COLUMN_THUMBNAIL, group.source_file)
                        holder.setFont(COLUMN_THUMBNAIL, bold_font)
                        holder.setBackground(COLUMN_THUMBNAIL, header_bg)
                        holder.setFirstColumnSpanned(True)
                        holder.setFlags(Qt.ItemFlag.ItemIsEnabled)
                        holder.setData(COLUMN_THUMBNAIL, PART_INDEX_ROLE, NO_PART)
                parent = QTreeWidgetItem(holder)
                parent.setText(COLUMN_THUMBNAIL, group.part_name)
                parent.setFont(COLUMN_THUMBNAIL, part_font)
                parent.setForeground(COLUMN_THUMBNAIL, part_fg)
                parent.setToolTip(COLUMN_THUMBNAIL, group.group_heading)
                parent.setFirstColumnSpanned(True)
                parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
                parent.setData(COLUMN_THUMBNAIL, PART_INDEX_ROLE, group.part_index)
                self._part_items_by_index[group.part_index] = parent
                for row in group.rows:
                    item = QTreeWidgetItem(parent)
                    item.setSizeHint(COLUMN_ROLE, leaf_size)
                    item.setData(COLUMN_THUMBNAIL, TEXTURE_ID_ROLE, row.texture_id)
                    item.setData(COLUMN_THUMBNAIL, PART_INDEX_ROLE, group.part_index)
                    item.setText(COLUMN_ROLE, texture_role_label(row.role))
                    item.setText(COLUMN_FILE, row.file_name)
                    item.setToolTip(COLUMN_FILE, row.game_path)
                    if made_from_several_files(row):
                        item.setText(COLUMN_STATE, NOT_ONE_FILE_STATE)
                        item.setForeground(COLUMN_STATE, muted_fg)
                        contributors = contributing_rows(group, row)
                        item.setToolTip(COLUMN_STATE, NOT_ONE_FILE_REASON + (
                            "\n" + EDIT_INSTEAD_TEXT.format(files=", ".join(other.file_name for other in contributors))
                            if contributors else ""))
                    elif row.shared:
                        item.setText(COLUMN_STATE, "Shared")
                        item.setForeground(COLUMN_STATE, muted_fg)
                        item.setToolTip(COLUMN_STATE, "Used by more than one part of this model.")
                    if row.decoded_path:
                        self._items_by_path.setdefault(row.decoded_path, []).append(item)
                        self._roles_by_path.setdefault(row.decoded_path, row.role)
                        part_paths = self._paths_by_part.setdefault(group.part_index, [])
                        if row.decoded_path not in part_paths:
                            part_paths.append(row.decoded_path)
                        cached_icon = self._icons_by_path.get((row.decoded_path, device_side, dpr_mill))
                        if cached_icon is not None:
                            item.setIcon(COLUMN_THUMBNAIL, cached_icon)
            # The files stay open (they are only headers); the parts start closed.
            for holder in file_items.values():
                holder.setExpanded(True)
            for part_index in opened:
                item = self._part_items_by_index.get(part_index)
                if item is not None:
                    item.setExpanded(True)
                    restored_open.add(part_index)
            self._opened_parts = restored_open
        finally:
            self.tree.blockSignals(prev_blocked)
            self.tree.setUpdatesEnabled(True)

        self.stack.setCurrentWidget(self.tree)
        self._fit_columns()
        if self.isVisible():
            self._schedule_fit_columns()
        self._request_thumbnails()
        self._set_has_session(True)

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        self._remember_part_open(item, True)
        part = item.data(COLUMN_THUMBNAIL, PART_INDEX_ROLE)
        if not item.data(COLUMN_THUMBNAIL, TEXTURE_ID_ROLE) and part is not None and part != NO_PART:
            self._request_part_thumbnails(int(part))
        self._schedule_fit_columns()

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        self._remember_part_open(item, False)
        self._schedule_fit_columns()

    def _request_paths(self, paths: Iterable[str], *, priority: int = 0) -> None:
        """Queue thumbnail decodes only for unrequested paths not already framed at this DPR."""

        device_side = self._thumbnail_device_side()
        dpr_mill = int(round(self._device_pixel_ratio() * 1000))
        self.thumbnails.size = device_side
        self.thumbnails.set_generation(self._generation)
        for path in paths:
            if not path or path in self._requested_paths:
                continue
            role = self._roles_by_path.get(path)
            if role is None:
                continue
            cached = self._icons_by_path.get((path, device_side, dpr_mill))
            items = self._items_by_path.get(path, ())
            if cached is not None and items and all(not it.icon(COLUMN_THUMBNAIL).isNull() for it in items):
                self._requested_paths.add(path)
                continue
            self._requested_paths.add(path)
            self.thumbnails.queue_texture_thumbnail(self._generation, path, role, priority=priority)

    def _request_part_thumbnails(self, part_index: int) -> None:
        paths = self._paths_by_part.get(part_index)
        if paths:
            self._request_paths(paths, priority=1)

    def _request_thumbnails(self) -> None:
        """Decode thumbnails lazily for currently expanded parts only (zero collapsed flood)."""

        if not self._opened_parts:
            return
        expanded_paths: list[str] = []
        seen: set[str] = set()
        for part_index in self._opened_parts:
            for path in self._paths_by_part.get(part_index, ()):
                if path not in seen:
                    seen.add(path)
                    expanded_paths.append(path)
        if expanded_paths:
            self._request_paths(expanded_paths, priority=1)

    def _restyle_headers(self) -> None:
        """Distinct visual hierarchy for .pac headers, parts, and muted state tags."""

        header_bg, part_fg, muted_fg, bold_font, part_font, leaf_size = self._tree_style_tokens()

        def _style_leaf(leaf: QTreeWidgetItem) -> None:
            leaf.setSizeHint(COLUMN_ROLE, leaf_size)
            if leaf.text(COLUMN_STATE):
                leaf.setForeground(COLUMN_STATE, muted_fg)

        self.tree.setUpdatesEnabled(False)
        try:
            for index in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(index)
                if top.data(COLUMN_THUMBNAIL, PART_INDEX_ROLE) == NO_PART:
                    top.setFont(COLUMN_THUMBNAIL, bold_font)
                    top.setBackground(COLUMN_THUMBNAIL, header_bg)
                    for p_idx in range(top.childCount()):
                        part = top.child(p_idx)
                        part.setFont(COLUMN_THUMBNAIL, part_font)
                        part.setForeground(COLUMN_THUMBNAIL, part_fg)
                        for l_idx in range(part.childCount()):
                            _style_leaf(part.child(l_idx))
                else:
                    top.setFont(COLUMN_THUMBNAIL, part_font)
                    top.setForeground(COLUMN_THUMBNAIL, part_fg)
                    for l_idx in range(top.childCount()):
                        _style_leaf(top.child(l_idx))
        finally:
            self.tree.setUpdatesEnabled(True)

    def _part_items(self) -> list[QTreeWidgetItem]:
        items: list[QTreeWidgetItem] = []
        for index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(index)
            if top.data(COLUMN_THUMBNAIL, PART_INDEX_ROLE) == NO_PART:
                items.extend(top.child(child) for child in range(top.childCount()))
            else:
                items.append(top)
        return items

    def part_item(self, part_index: int) -> QTreeWidgetItem | None:
        """The row of one part (its textures are its children)."""

        return self._part_items_by_index.get(part_index)

    def _remember_part_open(self, item: QTreeWidgetItem, opened: bool) -> None:
        part = item.data(COLUMN_THUMBNAIL, PART_INDEX_ROLE)
        if item.data(COLUMN_THUMBNAIL, TEXTURE_ID_ROLE) or part is None or part == NO_PART:
            return
        (self._opened_parts.add if opened else self._opened_parts.discard)(int(part))

    def clear(self) -> None:
        self._generation += 1
        self.thumbnails.set_generation(self._generation)
        self._pending_thumbnails.clear()
        self._thumbnail_flush_timer.stop()
        self._fit_columns_timer.stop()
        self._items_by_path = {}
        self._roles_by_path = {}
        self._paths_by_part = {}
        self._requested_paths = set()
        self._part_items_by_index = {}
        self._icons_by_path.clear()
        self._applied_icon_key_by_path = {}
        self._invalidate_column_metrics()
        self.groups = []
        self._set_hovered_part(NO_PART)
        self.tree.clear()
        self.placeholder_label.setText("Open a mesh to see its textures.")
        self.stack.setCurrentWidget(self.placeholder_label)
        self._set_has_session(False)

    def shutdown(self) -> None:
        """Drop pending thumbnails; the host calls this before tearing the page down."""

        self._pending_thumbnails.clear()
        self._thumbnail_flush_timer.stop()
        self._fit_columns_timer.stop()
        self.thumbnails.shutdown()

    def set_shown_live_textures(self, shown: Mapping[str, frozenset[int]] | None) -> None:
        """The editor said which textures an edit shows on, per part (B item 6)."""

        self._shown_live = dict(shown) if shown is not None else None
        if shown is not None and self.groups:
            self.groups = with_shown_live_textures(self.groups, shown)

    def texture_shown_live(self, source_sha256: str) -> bool:
        """Whether an edit of this file shows on any part of the model."""

        key = str(source_sha256 or "").lower()
        return any(row.in_renderer for row in self.texture_rows() if row.source_sha256.lower() == key)

    def texture_rows(self) -> tuple[TextureRow, ...]:
        """Every listed texture row, part by part."""

        return tuple(row for group in self.groups for row in group.rows)

    def texture_row(self, texture_id: str) -> TextureRow | None:
        for group in self.groups:
            for row in group.rows:
                if row.texture_id == texture_id:
                    return row
        return None

    def texture_users(self, texture_id: str) -> tuple[str, ...]:
        """The parts that use the same game file as ``texture_id``."""

        row = self.texture_row(texture_id)
        if row is None:
            return ()
        key = _share_key(row)
        return tuple(
            group.group_heading for group in self.groups
            if any(_share_key(other) == key for other in group.rows)
        )

    def texture_item(self, texture_id: str) -> QTreeWidgetItem | None:
        for parent in self._part_items():
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child.data(COLUMN_THUMBNAIL, TEXTURE_ID_ROLE) == texture_id:
                    return child
        return None

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        texture_id = item.data(COLUMN_THUMBNAIL, TEXTURE_ID_ROLE)
        if not texture_id:
            return
        group = next((group for group in self.groups for row in group.rows if row.texture_id == texture_id), None)
        row = self.texture_row(str(texture_id))
        if group is not None and row is not None and made_from_several_files(row):
            # Not one file (item 6): offer the files it is made from instead.
            contributors = contributing_rows(group, row)
            chosen = contributors[0] if len(contributors) == 1 else self._choose_contributor(contributors)
            if chosen is None:
                self.texture_refused.emit(NOT_ONE_FILE_REASON)
                return
            self.texture_activated.emit(chosen.texture_id)
            return
        self.texture_activated.emit(str(texture_id))

    def _choose_contributor(self, rows: Sequence[TextureRow]) -> TextureRow | None:
        """Ask which of the files a generated colour is made from to edit (None: none)."""

        if not rows:
            return None
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        actions = {menu.addAction(f"{texture_role_label(row.role)}: {row.file_name}"): row for row in rows}
        picked = menu.exec(QCursor.pos())
        return actions.get(picked)

    def _framed_icon_for(self, path: str, image: QImage, device_side: int, dpr: float, dpr_mill: int) -> QIcon:
        cache_key = (path, device_side, dpr_mill, int(image.cacheKey()))
        icon = self._framed_icons.get(cache_key)
        if icon is not None:
            self._framed_icons.move_to_end(cache_key)
            return icon
        pixmap = _frame_thumbnail_pixmap(image, device_side, dpr)
        icon = QIcon(pixmap)
        self._framed_icons[cache_key] = icon
        while len(self._framed_icons) > _THUMBNAIL_CACHE_LIMIT:
            self._framed_icons.popitem(last=False)
        return icon

    def _on_thumbnail_ready(self, generation: int, path: str, image: QImage) -> None:
        if generation != self._generation or image.isNull():
            return
        if path not in self._items_by_path:
            return
        self._pending_thumbnails[path] = image
        if not self._thumbnail_flush_timer.isActive():
            self._thumbnail_flush_timer.start()

    def _flush_pending_thumbnails(self) -> None:
        if not self._pending_thumbnails:
            return
        batch = self._pending_thumbnails
        self._pending_thumbnails = {}
        device_side = self._thumbnail_device_side()
        dpr = self._device_pixel_ratio()
        dpr_mill = int(round(dpr * 1000))
        self.tree.setUpdatesEnabled(False)
        try:
            for path, image in batch.items():
                items = self._items_by_path.get(path)
                if not items:
                    continue
                img_sig = (device_side, dpr_mill, int(image.cacheKey()))
                if self._applied_icon_key_by_path.get(path) == img_sig and all(
                    not item.icon(COLUMN_THUMBNAIL).isNull() for item in items
                ):
                    continue
                icon = self._framed_icon_for(path, image, device_side, dpr, dpr_mill)
                self._icons_by_path[(path, device_side, dpr_mill)] = icon
                self._applied_icon_key_by_path[path] = img_sig
                for item in items:
                    item.setIcon(COLUMN_THUMBNAIL, icon)
        finally:
            self.tree.setUpdatesEnabled(True)

    # ----- a session's manifest, read off the UI thread --------------------
    def show_session(self, session_root: str | os.PathLike[str] | None) -> None:
        """Show the textures of the session in ``session_root``; None clears the panel.

        The session manifest holds the editor's whole state and can be large, so it is
        read on a worker; a later call wins over a read still in flight.
        """

        self._session_request += 1
        root = str(session_root) if session_root is not None else None
        if root is None or root != self._session_root:
            self._session_root = root
            self._shown_live = None  # another session's editor says again
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


def _on_a_screen(widget: QWidget) -> bool:
    from PySide6.QtGui import QGuiApplication

    frame = widget.frameGeometry()
    return any(screen.availableGeometry().intersects(frame) for screen in QGuiApplication.screens())


def remember_dock_layout(host: object, dock: QDockWidget | tuple[QDockWidget, ...], settings: object,
                         key: str = DOCK_LAYOUT_KEY) -> None:
    """Restore where the Mesh Editor's docks were, and save it whenever one moves,
    floats or docks again (Fredric: the panel can be "freely moved around").

    Where, not whether: ``TexturePanels`` alone shows and hides them, so a saved layout
    neither hides a panel the user asked for nor shows one they closed."""

    restore = getattr(host, "restoreState", None)
    value = settings.value(key, None) if settings is not None else None
    if callable(restore) and value:
        try:
            restore(value)
        except (TypeError, ValueError, RuntimeError):
            pass
    # A panel left floating on a screen that is gone (or off every screen) docks again.
    docks = tuple(dock) if isinstance(dock, (tuple, list)) else (dock,)
    for each in docks:
        if each.isFloating() and not _on_a_screen(each):
            each.setFloating(False)

    def save(*_args: object) -> None:
        save_state = getattr(host, "saveState", None)
        if settings is None or not callable(save_state):
            return
        try:
            settings.setValue(key, save_state())
        except RuntimeError:
            pass  # the page is being torn down

    for each in docks:
        each.dockLocationChanged.connect(save)
        each.topLevelChanged.connect(save)
        each.visibilityChanged.connect(save)
