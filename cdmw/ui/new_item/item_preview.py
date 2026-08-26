"""New Item Studio: the item as it will be, in the resident viewport, inline.

`ItemPreviewFrame` shows the item (the imported model, else the template's own) in the
resident .NET viewport the Model Library uses, textured the way that library and the
Builder show it: orbit, zoom, and a capture of the frame at 512 x 512 with the grid and
gizmo hidden (the icon route). It takes a `ModelPreviewData` (the archive or import
preview decode, textures resolved), a bare `ParsedMesh`, a `PlacementScene` (the template
as the reference and a model of the user's own as the editable role, with the gizmo and
the view modes the Mesh Editor has: overlay, side by side, one or the other), or a
callable that produces any of those off the UI thread; starts the viewport only when
first asked to show something, rebuilds its package when the source changes, and is what
the Model and icon step embeds and the icon capture dialog wraps.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Hashable, Optional

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from cdmw.domain.cancellation import RunCancelled
from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings
from cdmw.services.mesh_workflow_service import ParsedMesh
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.ui.new_item.item_preview_materials import (
    PlacementScene,
    as_parsed_mesh as _as_parsed_mesh,
    placement_reference_mesh as _placement_reference_mesh,
    prepare_preview_model as _prepare_preview_model,
    upgrade_item_preview_package_materials,
)
from cdmw.workers.utility_workers import UtilityWorker

#: "no token given": `_package_ready` then reads the build in flight
_UNSET = object()

__all__ = [
    "GIZMO_TOOLS",
    "ItemPreviewFrame",
    "PLACEMENT_VIEW_MODES",
    "PlacementScene",
    "ProgressivePreviewSource",
    "build_item_preview_package",
    "upgrade_item_preview_package_materials",
    "default_host_factory",
    "package_cleanup_root",
]

#: the viewport's display modes for a placement scene (the host's display-mode keys)
PLACEMENT_VIEW_MODES = ("overlay", "side_by_side", "replacement_only", "original_only")
GIZMO_TOOLS = ("move", "rotate", "scale")


@dataclass(frozen=True, slots=True)
class ProgressivePreviewSource:
    """Geometry-first and canonical-material builders for one preview identity."""

    geometry: Callable[[threading.Event], Any]
    materials: Callable[[threading.Event], Any]
    acquire_usage: Optional[Callable[[], object]] = None

    def __call__(self, stop_event: threading.Event) -> Any:
        """Compatibility: callers that know only the old callable get full materials."""

        return self.materials(stop_event)


@dataclass(frozen=True, slots=True)
class _PreviewBuildProduct:
    package_dir: Path
    resolved_source: Any
    stage: str


def build_item_preview_package(
    source: Any,
    *,
    token: Hashable,
    output_root: Path,
    stop_event: threading.Event,
    include_material_resources: bool = True,
    render_settings: object | None = None,
    cache_mode: str = "off",
) -> Path:
    """Build the viewport package for `source` off the UI thread and return its directory.
    `source` is a `ModelPreviewData` (the archive or import preview decode, textures
    resolved: it goes the Model Library's route and comes out textured), a bare
    `ParsedMesh`, a `PlacementScene`, or a callable `(stop_event) -> one of those`."""

    archive_identity = f"new_item_preview:{token!r}"
    normalized_cache_mode = str(cache_mode or "off").strip().lower()
    cacheable_template = (
        bool(include_material_resources)
        and isinstance(token, tuple)
        and bool(token)
        and token[0] == "template"
    )
    if cacheable_template and normalized_cache_mode in {"balanced", "aggressive"}:
        from cdmw.services.mesh_dotnet_preview_package import (
            lookup_dotnet_preview_package_from_model_identity,
        )

        cached_package = lookup_dotnet_preview_package_from_model_identity(
            cache_root=output_root,
            archive_identity=archive_identity,
            cancelled=stop_event.is_set,
        )
        if cached_package is not None:
            return Path(cached_package.package_dir)

    item = source(stop_event) if callable(source) else source
    if item is None:
        raise ValueError("there is nothing to show")
    if isinstance(item, PlacementScene):
        from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package

        model = (
            _prepare_preview_model(
                item.model,
                render_settings=render_settings,
                stop_event=stop_event,
            )
            if include_material_resources
            else item.model
        )
        reference = (
            _prepare_preview_model(
                item.template,
                render_settings=render_settings,
                stop_event=stop_event,
            )
            if include_material_resources and item.template is not None
            else item.template
        )
        character = (
            _prepare_preview_model(
                item.character,
                render_settings=render_settings,
                stop_event=stop_event,
            )
            if item.character is not None
            else None
        )
        reference_mesh = _placement_reference_mesh(
            _as_parsed_mesh(reference) if reference is not None else None,
            _as_parsed_mesh(character) if character is not None else None,
        )
        package = build_mesh_dotnet_experiment_package(
            _as_parsed_mesh(model), output_root=output_root,
            reference_mesh=reference_mesh,
            comparison_mode="overlay", interaction_mode="placement", cancelled=stop_event.is_set,
            scene_transform=item.placement.build_transform(origin=item.model_origin),
            include_material_resources=bool(include_material_resources),
        )
        if item.character is not None:
            from cdmw.services.effect_placement_preview import _tint_anchor_material

            _tint_anchor_material(Path(package.package_dir) / "net_materials.json")
    elif getattr(item, "meshes", None) is not None and not hasattr(item, "submeshes"):
        from cdmw.services.mesh_dotnet_preview_package import build_or_lookup_dotnet_preview_package_from_model
        from cdmw.services.preview_rendering_service import dotnet_preview_package_cache_budget

        prepared_item = _prepare_preview_model(
            item,
            render_settings=render_settings,
            stop_event=stop_event,
        )
        output_root.mkdir(parents=True, exist_ok=True)
        cache_max_bytes, cache_target_bytes = dotnet_preview_package_cache_budget(cache_mode)
        package = build_or_lookup_dotnet_preview_package_from_model(
            prepared_item,
            cache_root=output_root,
            archive_identity=archive_identity,
            cache_mode=cache_mode,
            max_bytes=cache_max_bytes,
            target_bytes=cache_target_bytes,
            cancelled=stop_event.is_set,
            metadata={"surface": "new_item_studio", "source_token": repr(token)},
        )
    else:
        from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package

        package = build_mesh_dotnet_experiment_package(
            item, output_root=output_root, reference_mesh=None, comparison_mode="side_by_side", interaction_mode="placement",
            cancelled=stop_event.is_set,
            include_material_resources=bool(include_material_resources),
        )
    return Path(package.package_dir)


def package_cleanup_root(package_dir: Path, output_root: Path) -> Path:
    """The directory to remove for a package under `output_root`: the model route writes
    `<root>/cdmw_dotnet_preview_*/package`, the mesh route `<root>/<package>`."""

    parent = package_dir.parent
    if parent != output_root and parent.parent == output_root and parent.name.startswith("cdmw_dotnet_preview_"):
        return parent
    return package_dir


def default_host_factory(parent: QWidget):
    from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame
    from cdmw.ui.preview.profile import DotNetPreviewProfile

    return DotNetPreviewHostFrame(parent, profile=DotNetPreviewProfile.PREVIEW, terminate_on_close=True)


class ItemPreviewFrame(QWidget):
    """The resident viewport around one mesh, with an icon capture."""

    #: the viewport is showing the mesh last given
    ready = Signal()
    #: a capture landed: the PNG path and its image
    captured = Signal(object, object)
    #: something to say next to the view
    status_changed = Signal(str)
    #: the gizmo moved the model: the placement now (a ModelPlacement), and whether the drag ended
    placement_changed = Signal(object, bool)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        output_root: Optional[Path] = None,
        native_preview_core_cache_root: Optional[Path] = None,
        host_factory: Optional[Callable[[QWidget], object]] = None,
    ) -> None:
        super().__init__(parent)
        self._output_root = Path(output_root) if output_root is not None else Path(tempfile.gettempdir()) / "cdmw_new_item_preview"
        self._native_preview_core_cache_root = (
            Path(native_preview_core_cache_root)
            if native_preview_core_cache_root is not None
            else None
        )
        self._host_factory = host_factory or default_host_factory
        self.host = None
        self._host_error = ""
        self._render_settings: ModelPreviewRenderSettings = clamp_model_preview_render_settings()
        self._cache_mode = "off"
        self._package_dir: Optional[Path] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._active_source_usage: object | None = None
        self._closed = False
        #: (token, source) of the newest request; the build in flight may be older
        self._pending: Optional[tuple[Hashable, Any]] = None
        #: whether the newest request is a placement scene (the gizmo moves its model)
        self._pending_is_placement = False
        #: what the viewport is actually showing: the token of the loaded package, and
        #: whether that package is a placement scene. A "ready" for anything else is a
        #: stale echo of the package before, and must not take the placement or the gizmo.
        self._loaded_token: Hashable = None
        self._loaded_is_placement = False
        self._pending_capture: Optional[Path] = None
        self._loaded = False
        self.is_ready = False
        #: the placement scene's state: None outside a placement
        self._placement: Optional[ModelPlacement] = None
        self._placement_base: Optional[ModelPlacement] = None
        self._gizmo_tool = "move"
        self._gizmo_enabled = True
        self._view_mode = "overlay"
        self._grid_visible = True
        self._model_bounds: Any = None
        #: (path, token, is_placement, stage) built while hidden, waiting for the viewport
        self._deferred_package: Optional[tuple[Path, Hashable, bool, str]] = None
        #: (token, is_placement, stage) of the build in flight
        self._building: Optional[tuple[Hashable, bool, str]] = None
        #: Full-material stage queued behind a geometry-first preview package.
        self._upgrade_request: Optional[tuple[Hashable, Any, bool, Path]] = None
        self._loaded_stage = ""
        self._reset_view_on_ready = True
        self._retire_after_ready: list[Path] = []
        #: the build in flight was stopped for a newer request; its error is not the user's
        self._superseded = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.placeholder = QLabel("The viewport starts when there is a mesh to show.")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setMinimumHeight(240)
        layout.addWidget(self.placeholder, 1)
        # the host draws its own orbit / pan / zoom line; the frame adds none

    # ------------------------------------------------------------------ host

    def _ensure_host(self) -> bool:
        if self.host is not None:
            return True
        try:
            self.host = self._host_factory(self)
        except Exception as exc:  # noqa: BLE001 - the viewport is optional; the rest of the step works
            self.host = None
            self._host_error = str(exc)
            self.placeholder.setText("The resident viewport is not available here." + (f" ({self._host_error})" if self._host_error else ""))
            return False
        self.host.setMinimumSize(420, 300)
        self.host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layout().insertWidget(0, self.host, 1)
        self.placeholder.setVisible(False)
        self.host.controller.state_changed.connect(self._host_state)
        self.host.controller.capture_completed.connect(self._capture_completed)
        self.host.alignment_drag_started.connect(self._drag_started)
        self.host.alignment_drag_changed.connect(lambda x, y, z: self._drag_delta("move", (x, y, z), False))
        self.host.alignment_drag_finished.connect(lambda x, y, z: self._drag_delta("move", (x, y, z), True))
        self.host.alignment_rotation_changed.connect(lambda x, y, z: self._drag_delta("rotate", (x, y, z), False))
        self.host.alignment_rotation_finished.connect(lambda x, y, z: self._drag_delta("rotate", (x, y, z), True))
        self.host.alignment_scale_changed.connect(lambda x, y, z: self._drag_delta("scale", (x, y, z), False))
        self.host.alignment_scale_finished.connect(lambda x, y, z: self._drag_delta("scale", (x, y, z), True))
        self.host.set_render_tuning(self._render_settings)
        return True

    def set_render_settings(self, settings: object | None) -> None:
        """Use the same preview tuning as Archive Browser and update a live host."""

        self._render_settings = clamp_model_preview_render_settings(settings)
        if self.host is not None:
            self.host.set_render_tuning(self._render_settings)

    def set_cache_mode(self, mode: object) -> None:
        """Use the shared bounded preview-package cache policy for later loads."""

        normalized = str(mode or "off").strip().lower()
        self._cache_mode = normalized if normalized in {"off", "balanced", "aggressive"} else "off"

    def show_mesh(self, mesh: Optional[ParsedMesh]) -> None:
        """Show the bare `mesh` (None clears the view); a build already running is superseded."""

        self.show(mesh, token=id(mesh) if mesh is not None else None)

    def show(self, source: Any, *, token: Hashable = None) -> None:
        """Show `source`: a `ModelPreviewData` (textures resolved), a `ParsedMesh`, or a
        callable `(stop_event) -> one of those` run off the UI thread. None clears the
        view. `token` names the source; the same token while a build of it is running or
        shown asks for nothing new. A build already running for something else is
        superseded when it finishes. A plain source carries no placement: the gizmo goes,
        and the last placement is forgotten (it belonged to the scene before)."""

        self._placement = None
        self._placement_base = None
        self._show(source, token=token, is_placement=False)

    def _show(self, source: Any, *, token: Hashable = None, is_placement: bool = False) -> None:
        if self._closed:
            return
        if source is None:
            self._pending = None
            self._pending_is_placement = False
            self._upgrade_request = None
            self._placement = None
            self.is_ready = False
            self._drop_deferred_package()
            if self.host is None:
                self.placeholder.setText("The viewport starts when there is a mesh to show.")
            return
        # the package builds at once, shown or not (so a step opens with the item there);
        # the viewport itself starts only once this frame is on screen, since it embeds
        # a native window that wants a realized parent
        if (self.host is not None or self.isVisible()) and not self._ensure_host():
            return
        if self._pending is not None and self._pending[0] == token and (self._thread is not None or self.is_ready or self._deferred_package is not None):
            return
        self._pending = (token, source)
        self._pending_is_placement = bool(is_placement)
        self._upgrade_request = None
        self._drop_deferred_package()
        self.is_ready = False
        # the scene on screen is the package before this request: take the gizmo off it at
        # once, so nothing there can be dragged while it is stale
        if self.host is not None and self._loaded_token is not None and self._loaded_token != token:
            try:
                self.host.set_alignment_state(enabled=False)
            except Exception:  # noqa: BLE001 - a host without the call keeps its gizmo
                pass
        if self._thread is None:
            self._start_package(self._pending)
        elif self._worker is not None:
            # a build for something else is running: stop it rather than wait it out (a
            # template preview started a moment before an import would otherwise cost the
            # user ten seconds for a scene they never see). `_build_finished` starts this one.
            self._superseded = True
            self._worker.stop()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        super().showEvent(event)
        deferred = self._deferred_package
        if deferred is not None and not self._closed and self._ensure_host():
            self._deferred_package = None
            self._package_ready(deferred[0], deferred[1], deferred[2], deferred[3])

    def _drop_deferred_package(self) -> None:
        deferred = self._deferred_package
        if deferred is not None:
            self._remove_package(deferred[0])
            self._deferred_package = None

    def show_placement(
        self,
        source: Any,
        *,
        token: Hashable,
        placement: ModelPlacement,
        model_bounds: Any = None,
        gizmo_enabled: bool = True,
    ) -> None:
        """Show a `PlacementScene` (or a callable producing one) with the model at
        `placement` (`model_bounds`: the model's own-space bounds, for the host's
        placement fallback), the gizmo on when `gizmo_enabled`. The same token already
        showing only takes the new placement and gizmo state."""

        same = self._pending is not None and self._pending[0] == token and (self._thread is not None or self.is_ready or self._deferred_package is not None)
        self._placement = placement
        self._gizmo_enabled = bool(gizmo_enabled)
        self._model_bounds = model_bounds
        if same:
            if self.is_ready:
                self._apply_placement_presentation()
            return
        self._show(source, token=token, is_placement=True)

    # ------------------------------------------------------------------ placement

    @property
    def placement(self) -> Optional[ModelPlacement]:
        return self._placement

    def set_placement(self, placement: ModelPlacement) -> None:
        """Move the model to `placement` (the numbers typed, a fit, a reset)."""

        self._placement = placement
        self._placement_base = None
        if self.is_ready and self.host is not None:
            self._push_placement()

    def set_gizmo_tool(self, tool: str) -> None:
        tool = str(tool or "move").strip().lower()
        if tool not in GIZMO_TOOLS:
            return
        self._gizmo_tool = tool
        if self.is_ready and self.host is not None and self._placement is not None:
            self.host.set_alignment_gizmo_tool(tool)

    def set_gizmo_enabled(self, enabled: bool) -> None:
        self._gizmo_enabled = bool(enabled)
        if self.is_ready and self.host is not None and self._placement is not None:
            self.host.set_alignment_state(enabled=self._gizmo_enabled)

    def set_view_mode(self, mode: str) -> None:
        """One of PLACEMENT_VIEW_MODES: overlay, side_by_side, replacement_only, original_only."""

        mode = str(mode or "overlay").strip().lower()
        if mode not in PLACEMENT_VIEW_MODES:
            return
        self._view_mode = mode
        if self.is_ready and self.host is not None and self._placement is not None:
            self.host.set_display_mode(mode)

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = bool(visible)
        if self.is_ready and self.host is not None and self._placement is not None:
            self.host.set_grid_visible(self._grid_visible)

    def _apply_placement_presentation(self, *, fit_view: bool = False) -> None:
        host = self.host
        if host is None or self._placement is None:
            return
        host.set_display_mode(self._view_mode)
        host.set_grid_visible(self._grid_visible)
        # no source highlight: the model draws as itself (textured), not as the Builder's yellow wire
        host.set_alignment_state(enabled=self._gizmo_enabled)
        host.set_alignment_gizmo_tool(self._gizmo_tool)
        bounds = self._model_bounds
        if bounds is not None and hasattr(host, "remember_editable_local_bounds"):
            host.remember_editable_local_bounds(bounds[0], bounds[1])
        self._push_placement()
        if fit_view:
            self.fit_view()

    def fit_view(self) -> None:
        """Frame the camera on the model where it sits now (the helper keeps its frame
        until asked, so a model scaled or moved far goes out of view otherwise)."""

        if self.host is not None and self.is_ready:
            self.host.reset_view()

    def _push_placement(self) -> None:
        host = self.host
        placement = self._placement
        if host is None or placement is None or not self.is_ready:
            return
        host.set_alignment_preview_transform(translation=placement.offset, rotation_degrees=placement.rotation, scale_xyz=placement.scale)

    def _drag_started(self) -> None:
        if self._placement is not None:
            self._placement_base = self._placement

    def _drag_delta(self, tool: str, delta: tuple, finished: bool) -> None:
        """The host reports the gizmo's total delta since the drag began; the new value
        is the placement at the drag's start plus that delta, per axis (scale too).
        Nothing is pushed to the helper while the drag runs: it draws the provisional
        placement itself, and a push mid-drag re-bases that on a stale frame (the model
        snaps back to the pivot and jumps at the end). The finished placement is pushed
        once, and the helper takes it as the next authoritative frame."""

        base = self._placement_base if self._placement_base is not None else self._placement
        if base is None:
            return
        if tool == "move":
            new = base.with_values(offset=tuple(base.offset[i] + float(delta[i]) for i in range(3)))
        elif tool == "rotate":
            new = base.with_values(rotation=tuple(base.rotation[i] + float(delta[i]) for i in range(3)))
        else:
            new = base.with_values(scale=tuple(max(1e-4, base.scale[i] + float(delta[i])) for i in range(3)))
        self._placement = new
        if finished:
            self._placement_base = None
            self._push_placement()
        self.placement_changed.emit(new, bool(finished))

    @property
    def showing_placement(self) -> bool:
        """The viewport is showing the placement scene this frame was last given: only
        then does the gizmo move the imported model, and only then may it be dragged."""

        return bool(self.is_ready and self._loaded_is_placement and self._placement is not None)

    def _start_package(
        self,
        request: tuple[Hashable, Any],
        *,
        stage: str = "geometry",
        resolved_source: Any = None,
        base_package: Optional[Path] = None,
    ) -> None:
        root = self._output_root
        token, source = request
        usage_source = resolved_source if resolved_source is not None else source
        acquire_usage = getattr(usage_source, "acquire_usage", None)
        source_usage = acquire_usage() if callable(acquire_usage) else None
        render_settings = clamp_model_preview_render_settings(self._render_settings)
        cache_mode = self._cache_mode
        native_preview_core_cache_root = self._native_preview_core_cache_root
        # What this build is for, read back by `_package_ready`. It is kept here rather
        # than captured in a lambda on `completed`: a lambda is not a bound method of this
        # QObject, so Qt runs it on the worker's thread, and the viewport's process would
        # then be created off the UI thread and never deliver its protocol.
        is_placement = bool(self._pending_is_placement)
        candidate_source = resolved_source if resolved_source is not None else source
        progressive = isinstance(candidate_source, ProgressivePreviewSource)
        full_stage = stage == "materials" or not progressive
        self._building = (token, is_placement, "materials" if full_stage else "geometry")
        if not full_stage:
            self.is_ready = False
            self._placement_base = None
            self.status_changed.emit("Building the preview...")
        else:
            self.status_changed.emit("Loading model textures…")
        def task(_log, progress, stop_event: threading.Event) -> _PreviewBuildProduct:
            if callable(acquire_usage) and source_usage is None:
                raise RunCancelled("Operation cancelled.")
            candidate = candidate_source

            def build_material_item() -> Any:
                if native_preview_core_cache_root is None:
                    return candidate.materials(stop_event)
                return candidate.materials(
                    stop_event,
                    output_root=root,
                    native_preview_core_cache_root=native_preview_core_cache_root,
                    render_settings=render_settings,
                    cache_mode=cache_mode,
                )

            def material_package(item: Any) -> Path:
                if isinstance(item, Path):
                    return item
                return build_item_preview_package(
                    item,
                    token=token,
                    output_root=root,
                    stop_event=stop_event,
                    include_material_resources=True,
                    render_settings=render_settings,
                    cache_mode=cache_mode,
                )

            if (
                not full_stage
                and progressive
                and isinstance(token, tuple)
                and bool(token)
                and token[0] == "template"
                and cache_mode in {"balanced", "aggressive"}
            ):
                from cdmw.services.mesh_dotnet_preview_package import (
                    lookup_dotnet_preview_package_from_model_identity,
                )

                cached_package = lookup_dotnet_preview_package_from_model_identity(
                    cache_root=root,
                    archive_identity=f"new_item_preview:{token!r}",
                    cancelled=stop_event.is_set,
                )
                if cached_package is not None:
                    return _PreviewBuildProduct(Path(cached_package.package_dir), candidate, "materials")
            if progressive and not full_stage:
                try:
                    geometry_item = candidate.geometry(stop_event)
                except RunCancelled:
                    raise
                except Exception:
                    package_dir = material_package(build_material_item())
                    return _PreviewBuildProduct(package_dir, candidate, "materials")

                material_packages: list[Path] = []
                material_errors: list[BaseException] = []

                def build_material_package() -> None:
                    try:
                        material_packages.append(material_package(build_material_item()))
                    except BaseException as exc:  # noqa: BLE001 - delivered by the owning worker
                        material_errors.append(exc)

                material_thread = threading.Thread(
                    target=build_material_package,
                    name="cdmw-new-item-preview-materials",
                )
                material_thread.start()
                try:
                    geometry_package = build_item_preview_package(
                        geometry_item,
                        token=token,
                        output_root=root,
                        stop_event=stop_event,
                        include_material_resources=False,
                        render_settings=render_settings,
                        cache_mode=cache_mode,
                    )
                except Exception:  # noqa: BLE001 - the full package can still land
                    pass
                else:
                    progress(1, 2, str(geometry_package))
                material_thread.join()
                if material_packages:
                    return _PreviewBuildProduct(material_packages[0], candidate, "materials")
                material_error = material_errors[0]
                if isinstance(material_error, Exception):
                    raise material_error
                raise RuntimeError(str(material_error)) from material_error
            if isinstance(candidate, ProgressivePreviewSource):
                item = build_material_item() if full_stage else candidate.geometry(stop_event)
                upgrade_source = candidate
            else:
                item = candidate(stop_event) if callable(candidate) else candidate
                upgrade_source = item
            if full_stage and is_placement and base_package is not None:
                package_dir = upgrade_item_preview_package_materials(
                    base_package,
                    item,
                    output_root=root,
                    stop_event=stop_event,
                    render_settings=render_settings,
                )
            else:
                package_dir = build_item_preview_package(
                    item,
                    token=token,
                    output_root=root,
                    stop_event=stop_event,
                    include_material_resources=full_stage,
                    render_settings=render_settings,
                    cache_mode=cache_mode,
                )
            return _PreviewBuildProduct(package_dir, upgrade_source, "materials" if full_stage else "geometry")

        self._launch_package_worker(task, source_usage)

    def _launch_package_worker(self, task: Callable, source_usage: object) -> None:
        worker = UtilityWorker(task, task_accepts_progress=True, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        self._thread, self._worker = thread, worker
        self._active_source_usage = source_usage
        # Every one of these is a bound method of this QObject, so Qt runs it on this
        # frame's thread. A plain function or a lambda is run on the worker's thread
        # instead: the viewport's process would be created there (and never report
        # ready), and a timer started there would never fire, because the worker's
        # event loop is quitting -- which is how a newer source could be left waiting
        # for a build that never started.
        worker.progress_changed.connect(self._progressive_package_ready)
        worker.completed.connect(self._package_ready)
        worker.error.connect(self._package_failed)
        worker.finished.connect(self._worker_finished, Qt.DirectConnection)
        thread.finished.connect(self._build_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        thread.start()

    def _progressive_package_ready(self, current: int, total: int, package_path: str) -> None:
        """Load the immutable geometry package while the same worker finishes materials."""

        if int(current) != 1 or int(total) != 2 or not str(package_path or "").strip():
            return
        building = self._building
        self._package_ready(Path(package_path), stage="geometry")
        if (
            building is not None
            and not self._closed
            and self._pending is not None
            and self._pending[0] == building[0]
            and self._building is not None
            and self._building[0] == building[0]
        ):
            self._upgrade_request = None
            self._building = (building[0], building[1], "materials")
            self.status_changed.emit("Loading model textures…")

    def _package_failed(self, message: object) -> None:
        if self._closed or self._superseded:
            return
        self.status_changed.emit(f"The preview could not be built: {message}")

    def _worker_finished(self) -> None:
        """Return the worker QObject to this frame's thread before its loop exits."""

        worker = self._worker
        if worker is not None and worker.thread() is QThread.currentThread():
            worker.moveToThread(self.thread())
        QThread.currentThread().quit()

    def _build_finished(self) -> None:
        """The build in flight has ended (landed or failed): tear its thread down and
        start the newest request when it superseded this one."""

        thread, worker = self._thread, self._worker
        if thread is not None and not thread.wait(0):
            QTimer.singleShot(0, self._build_finished)
            return
        self._thread = None
        self._worker = None
        source_usage, self._active_source_usage = self._active_source_usage, None
        release_usage = getattr(source_usage, "release", None)
        if callable(release_usage):
            release_usage()
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        done_token = self._building[0] if self._building is not None else None
        done_stage = self._building[2] if self._building is not None else ""
        self._building = None
        self._superseded = False
        newer = self._pending
        if newer is not None and newer[0] != done_token and not self._closed:
            self._upgrade_request = None
            self._start_package(newer)
            return
        upgrade = self._upgrade_request
        if (
            done_stage == "geometry"
            and upgrade is not None
            and newer is not None
            and upgrade[0] == newer[0] == done_token
            and not self._closed
        ):
            self._upgrade_request = None
            self._start_package(
                newer,
                stage="materials",
                resolved_source=upgrade[1],
                base_package=upgrade[3],
            )

    def _package_ready(
        self,
        result: object,
        token: Hashable = _UNSET,
        is_placement: bool = False,
        stage: str = "materials",
    ) -> None:
        """The package for the build in flight (`self._building`, unless a token is given
        outright, as the deferred path does) has landed: load it and remember what it is."""

        resolved_source = None
        if isinstance(result, _PreviewBuildProduct):
            resolved_source = result.resolved_source
            stage = result.stage
            result = result.package_dir
        if token is _UNSET:
            if self._building is None:
                token, is_placement = None, False
            else:
                token, is_placement, building_stage = self._building
                stage = stage or building_stage
        if self._building is not None and token == self._building[0]:
            self._building = (self._building[0], self._building[1], stage)
        if not isinstance(result, Path):
            return
        if self._closed:
            self._remove_package(result)
            return
        if self._pending is not None and token != self._pending[0]:
            self._remove_package(result)
            return
        if stage == "geometry" and resolved_source is not None:
            self._upgrade_request = (token, resolved_source, bool(is_placement), result)
        if self.host is None:
            if self.isVisible() and self._ensure_host():
                pass
            else:
                # built ahead of the step: loaded the moment the frame shows
                self._drop_deferred_package()
                self._deferred_package = (result, token, is_placement, stage)
                self.status_changed.emit("")
                return
        previous = self._package_dir
        reset_view = previous is None or stage != "materials" or self._loaded_token != token
        if self.host.load_package(result, reset_view=reset_view):
            self._package_dir = result
            if previous is not None and previous != result:
                self._retire_after_ready.append(previous)
            self._loaded = True
            self._loaded_token = token
            self._loaded_is_placement = bool(is_placement)
            self._loaded_stage = stage
            self._reset_view_on_ready = reset_view
            self.host.set_display_mode("replacement_only")
            self.status_changed.emit("Loading the viewport...")
        else:
            self._remove_package(result)
            self.status_changed.emit("The resident viewport rejected the preview package.")

    def _host_state(self, state: str, message: str) -> None:
        if self._closed or self.host is None:
            return
        if str(state) == "ready" and self._package_dir is not None:
            if self._pending is not None and self._loaded_token != self._pending[0]:
                # a ready for the package before this request: the newest build is still
                # running, so the scene on screen is not the one the placement belongs to
                return
            self.is_ready = True
            if self._loaded_is_placement and self._placement is not None:
                self.host.set_icon_capture_mode(False)
                self._apply_placement_presentation(fit_view=self._reset_view_on_ready)
            else:
                self.host.set_display_mode("replacement_only")
                self.host.set_alignment_state(enabled=False)
                self.host.set_icon_capture_mode(True)
            retired, self._retire_after_ready = self._retire_after_ready, []
            for package in retired:
                if package != self._package_dir:
                    self._remove_package(package)
            building_materials = self._building is not None and self._building[2] == "materials"
            self.status_changed.emit("Loading model textures…" if building_materials else "")
            self.ready.emit()
        elif str(state) == "error":
            self.status_changed.emit(str(message or "The viewport reported an error."))

    # ------------------------------------------------------------------ capture

    def capture(self, path: Optional[Path] = None) -> bool:
        """Take the view as it is: the frame at the viewport's own size, so what is on
        screen is what lands (the grid and the gizmo are hidden for it). `captured` fires
        with the PNG when it arrives; the caller crops it to the icon it wants."""

        if self.host is None or not self.is_ready:
            return False
        self._output_root.mkdir(parents=True, exist_ok=True)
        target = Path(path) if path is not None else self._output_root / f"icon_capture_{time.time_ns()}.png"
        size = self.host.size()
        width = max(64, min(2048, int(size.width()) or 512))
        height = max(64, min(2048, int(size.height()) or 512))
        if not self.host.capture_replacement_icon(target, width=width, height=height):
            self.status_changed.emit("The viewport rejected the capture request.")
            return False
        self._pending_capture = target
        self.status_changed.emit("Capturing...")
        return True

    def _capture_completed(self, payload: object) -> None:
        if self._closed:
            return
        if self._loaded_is_placement and self.host is not None:
            # the capture hides the grid and the gizmo; a placement scene wants them back
            QTimer.singleShot(0, self._restore_after_capture)
        pending, self._pending_capture = self._pending_capture, None
        status = str(payload.get("status", "") or "") if isinstance(payload, dict) else ""
        path = pending
        if isinstance(payload, dict):
            text = str(payload.get("requested_output_path", payload.get("output_path", "")) or "").strip()
            if text:
                path = Path(text)
        image = QImage(str(path)) if path is not None and status in ("", "captured") else QImage()
        if path is None or image.isNull():
            message = str(payload.get("message", "") or "") if isinstance(payload, dict) else ""
            self.status_changed.emit(f"The capture failed: {message or 'the viewport returned no image.'}")
            return
        self.status_changed.emit(f"Captured {image.width()} x {image.height()}.")
        self.captured.emit(path, image)

    def _restore_after_capture(self) -> None:
        if self._closed or self.host is None or not self._loaded_is_placement:
            return
        self.host.set_icon_capture_mode(False)
        self._apply_placement_presentation()

    # ------------------------------------------------------------------ lifecycle

    def iter_shutdown_workers(self):
        return (("new item preview", self._thread, self._worker),) if self._thread is not None else ()

    def request_shutdown(self) -> None:
        self._closed = True
        worker = self._worker
        if worker is not None:
            worker.stop()
        thread = self._thread
        if thread is not None:
            thread.requestInterruption()
            thread.quit()

    def shutdown(self) -> None:
        self.request_shutdown()
        if self.host is not None:
            try:
                self.host.set_icon_capture_mode(False)
                self.host.controller.shutdown()
            except Exception:  # noqa: BLE001
                pass
        if self._package_dir is not None:
            self._remove_package(self._package_dir)
            self._package_dir = None
        retired, self._retire_after_ready = self._retire_after_ready, []
        for package in retired:
            self._remove_package(package)
        self._drop_deferred_package()

    def _remove_package(self, package_dir: Path) -> None:
        """Remove one transient package; durable cache entries outlive this frame."""

        from cdmw.services.preview_rendering_service import (
            dotnet_preview_package_derived_cache_root,
            is_durable_dotnet_preview_package_path,
        )

        derived_cache_root = dotnet_preview_package_derived_cache_root(self._output_root)
        if is_durable_dotnet_preview_package_path(derived_cache_root, package_dir):
            return
        shutil.rmtree(self._package_cleanup_root(package_dir), ignore_errors=True)

    def _package_cleanup_root(self, package_dir: Path) -> Path:
        return package_cleanup_root(package_dir, self._output_root)
