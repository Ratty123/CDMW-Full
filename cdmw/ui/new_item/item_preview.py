"""New Item Studio: the item as it will be, in the resident viewport, inline.

`ItemPreviewFrame` shows the item (the imported model, else the template's own) in the
    resident Rust viewport the Model Library uses, textured the way that library and the
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

import logging
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Hashable, Optional

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from cdmw.domain.cancellation import RunCancelled
from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings
from cdmw.services.mesh_workflow_service import ParsedMesh
from cdmw.ui.new_item.model_import import ModelPlacement, mesh_bounds
from cdmw.ui.new_item.item_preview_materials import (
    PlacementScene,
    as_parsed_mesh as _as_parsed_mesh,
    flat_preview_normal_axis as _flat_preview_normal_axis,
    placement_reference_mesh as _placement_reference_mesh,
    prepare_preview_model as _prepare_preview_model,
    upgrade_item_preview_package_materials,
)
from cdmw.workers.utility_workers import UtilityWorker


_LOGGER = logging.getLogger(__name__)

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
    supports_fast_material_package: bool = False
    cached_materials: Optional[Callable[..., Path | None]] = None

    def __call__(self, stop_event: threading.Event) -> Any:
        """Compatibility: callers that know only the old callable get full materials."""

        return self.materials(stop_event)


@dataclass(frozen=True, slots=True)
class _PreviewBuildProduct:
    package_dir: Path
    resolved_source: Any
    stage: str


@dataclass(frozen=True, slots=True)
class _PreviewPackageTask:
    output_root: Path
    token: Hashable
    candidate: Any
    is_placement: bool
    full_stage: bool
    base_package: Optional[Path]
    render_settings: object
    cache_mode: str
    native_preview_core_cache_root: Optional[Path]
    source_usage_required: bool
    source_usage_acquired: bool

    @property
    def progressive(self) -> bool:
        return isinstance(self.candidate, ProgressivePreviewSource)

    @property
    def supports_fast_material_package(self) -> bool:
        return bool(
            self.progressive
            and self.candidate.supports_fast_material_package
        )

    def __call__(self, _log, progress, stop_event: threading.Event) -> _PreviewBuildProduct:
        del _log
        if self.source_usage_required and not self.source_usage_acquired:
            raise RunCancelled("Operation cancelled.")
        cached = self._cached_template(stop_event)
        if cached is not None:
            return cached
        if self.progressive and not self.full_stage:
            return self._build_progressive(progress, stop_event)
        return self._build_single_stage(stop_event)

    def _cached_template(self, stop_event: threading.Event) -> _PreviewBuildProduct | None:
        token = self.token
        if not (
            not self.full_stage
            and self.progressive
            and isinstance(token, tuple)
            and bool(token)
            and token[0] == "template"
            and self.cache_mode in {"balanced", "aggressive"}
        ):
            return None
        if self.candidate.cached_materials is not None and self.native_preview_core_cache_root is not None:
            cached = self.candidate.cached_materials(
                stop_event,
                output_root=self.output_root,
                native_preview_core_cache_root=self.native_preview_core_cache_root,
                render_settings=self.render_settings,
                cache_mode=self.cache_mode,
            )
            if cached is None:
                return None
            return _PreviewBuildProduct(Path(cached), self.candidate, "materials")
        from cdmw.services.mesh_rust_preview_cache import (
            lookup_rust_preview_package_from_model_identity,
        )

        cached = lookup_rust_preview_package_from_model_identity(
            cache_root=self.output_root,
            archive_identity=f"new_item_preview:{token!r}",
            semantic_view_axis="auto",
            cancelled=stop_event.is_set,
        )
        if cached is None:
            return None
        return _PreviewBuildProduct(Path(cached.package_dir), self.candidate, "materials")

    def _build_progressive(self, progress, stop_event: threading.Event) -> _PreviewBuildProduct:
        candidate = self.candidate
        materials = _ProgressiveMaterialBuild(self, stop_event)
        material_thread = threading.Thread(
            target=materials.run,
            name="cdmw-new-item-preview-materials",
        )
        material_thread.start()
        try:
            try:
                geometry_item = candidate.geometry(stop_event)
                geometry_package = build_item_preview_package(
                    geometry_item,
                    token=self.token,
                    output_root=self.output_root,
                    stop_event=stop_event,
                    include_material_resources=False,
                    render_settings=self.render_settings,
                    cache_mode=self.cache_mode,
                )
            except RunCancelled:
                raise
            except Exception:  # noqa: BLE001 - the full package can still land
                pass
            else:
                progress(
                    1,
                    3 if self.supports_fast_material_package else 2,
                    str(geometry_package),
                )
            if self.supports_fast_material_package:
                while not (
                    materials.fast_ready.is_set()
                    or materials.done.is_set()
                    or stop_event.is_set()
                ):
                    materials.fast_ready.wait(0.01)
                if materials.fast_packages and not stop_event.is_set():
                    progress(2, 3, str(materials.fast_packages[-1]))
        except BaseException:
            stop_event.set()
            raise
        finally:
            material_thread.join()
        return materials.product(candidate)

    def _build_single_stage(self, stop_event: threading.Event) -> _PreviewBuildProduct:
        candidate = self.candidate
        material_build = _ProgressiveMaterialBuild(self, stop_event)
        if self.progressive:
            item = material_build.build_item() if self.full_stage else candidate.geometry(stop_event)
            resolved_source = candidate
        else:
            item = candidate(stop_event) if callable(candidate) else candidate
            resolved_source = item
        if self.full_stage and self.is_placement and self.base_package is not None:
            package_dir = upgrade_item_preview_package_materials(
                self.base_package,
                item,
                output_root=self.output_root,
                stop_event=stop_event,
                render_settings=self.render_settings,
            )
        elif self.full_stage and self.progressive:
            package_dir = material_build.package_for(item)
        else:
            package_dir = build_item_preview_package(
                item,
                token=self.token,
                output_root=self.output_root,
                stop_event=stop_event,
                include_material_resources=self.full_stage,
                render_settings=self.render_settings,
                cache_mode=self.cache_mode,
            )
        stage = "materials" if self.full_stage else "geometry"
        return _PreviewBuildProduct(package_dir, resolved_source, stage)


@dataclass(slots=True)
class _ProgressiveMaterialBuild:
    task: _PreviewPackageTask
    stop_event: threading.Event
    fast_packages: list[Path] = field(default_factory=list)
    packages: list[Path] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)
    fast_ready: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)

    def handle_fast_package(self, package: object) -> None:
        package_path = getattr(package, "package_dir", package)
        if self.stop_event.is_set() or not package_path:
            return
        self.fast_packages.append(Path(package_path))
        self.fast_ready.set()

    def build_item(self) -> Any:
        candidate = self.task.candidate
        cache_root = self.task.native_preview_core_cache_root
        if cache_root is None:
            return candidate.materials(self.stop_event)
        preview_context = {
            "output_root": self.task.output_root,
            "native_preview_core_cache_root": cache_root,
            "render_settings": self.task.render_settings,
            "cache_mode": self.task.cache_mode,
        }
        if self.task.supports_fast_material_package:
            preview_context["fast_package_ready"] = self.handle_fast_package
        return candidate.materials(self.stop_event, **preview_context)

    def package_for(self, item: Any) -> Path:
        if isinstance(item, Path):
            return item
        return build_item_preview_package(
            item,
            token=self.task.token,
            output_root=self.task.output_root,
            stop_event=self.stop_event,
            include_material_resources=True,
            render_settings=self.task.render_settings,
            cache_mode=self.task.cache_mode,
            fast_package_ready=(
                self.handle_fast_package
                if self.task.supports_fast_material_package
                else None
            ),
        )

    def run(self) -> None:
        try:
            self.packages.append(self.package_for(self.build_item()))
        except BaseException as exc:  # noqa: BLE001 - delivered by the owning worker
            self.errors.append(exc)
        finally:
            self.done.set()

    def product(self, resolved_source: Any) -> _PreviewBuildProduct:
        if self.packages:
            return _PreviewBuildProduct(self.packages[0], resolved_source, "materials")
        if not self.errors:
            raise RuntimeError("The material preview ended without a package.")
        error = self.errors[0]
        if isinstance(error, Exception):
            raise error
        raise RuntimeError(str(error)) from error


def build_item_preview_package(
    source: Any,
    *,
    token: Hashable,
    output_root: Path,
    stop_event: threading.Event,
    include_material_resources: bool = True,
    render_settings: object | None = None,
    cache_mode: str = "off",
    fast_package_ready: Optional[Callable[[object], None]] = None,
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
        from cdmw.services.mesh_rust_preview_cache import (
            lookup_rust_preview_package_from_model_identity as lookup_dotnet_preview_package_from_model_identity,
        )

        cached_package = lookup_dotnet_preview_package_from_model_identity(
            cache_root=output_root,
            archive_identity=archive_identity,
            semantic_view_axis="auto",
            cancelled=stop_event.is_set,
        )
        if cached_package is not None:
            return Path(cached_package.package_dir)

    item = source(stop_event) if callable(source) else source
    if item is None:
        raise ValueError("there is nothing to show")

    def progressive_material_package(
        build_quality: Callable[[str], object],
        *,
        needs_full_material_tier: bool = True,
    ) -> object:
        if bool(include_material_resources) and not needs_full_material_tier:
            # Imported glTF/OBJ/DAE images are already the complete material
            # authority. Publish that direct package once; a second nominal
            # "full" package would contain the same result and reload the view.
            return build_quality("direct")
        if bool(include_material_resources) and fast_package_ready is not None:
            try:
                direct = build_quality("direct")
                if stop_event.is_set():
                    raise RunCancelled("Operation cancelled.")
                fast_package_ready(direct)
                if stop_event.is_set():
                    raise RunCancelled("Operation cancelled.")
            except RunCancelled:
                raise
            except Exception:
                _LOGGER.warning(
                    "new_item_direct_texture_tier_failed; continuing with full quality",
                    exc_info=True,
                )
        return build_quality("full")

    if isinstance(item, PlacementScene):
        from cdmw.services.mesh_rust_preview_package import (
            build_rust_preview_package,
            semantic_initial_view,
        )
        from cdmw.services.mesh_rust_authoring import rust_preview_mesh_needs_material_synthesis

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
        model_mesh = _as_parsed_mesh(model)
        template_mesh = _as_parsed_mesh(reference) if reference is not None else None
        character_mesh = _as_parsed_mesh(character) if character is not None else None
        semantic_bounds = mesh_bounds(template_mesh if template_mesh is not None else model_mesh)
        grid_normal_axis = _flat_preview_normal_axis(semantic_bounds)
        reference_mesh = _placement_reference_mesh(template_mesh, character_mesh)
        def build_placement_quality(quality: str):
            def publish(target: Optional[Path] = None):
                return build_rust_preview_package(
                    model_mesh,
                    output_package_dir=target,
                    output_root=None if target is not None else output_root,
                    reference_mesh=reference_mesh,
                    comparison_mode="overlay",
                    interaction_profile="static_replacement",
                    interaction_mode="placement",
                    reference_draw="wire",
                    grid_normal_axis=grid_normal_axis,
                    cancelled=stop_event.is_set,
                    scene_transform=item.placement.build_transform(origin=item.model_origin),
                    include_material_resources=bool(include_material_resources),
                    material_quality=quality,
                    initial_view=semantic_initial_view(semantic_bounds, grid_normal_axis),
                )

            if normalized_cache_mode not in {"balanced", "aggressive"}:
                return publish()
            from cdmw.services.mesh_rust_preview_cache import (
                build_or_lookup_rust_preview_package_with_builder,
            )
            from cdmw.services.preview_rendering_service import dotnet_preview_package_cache_budget

            cache_max_bytes, cache_target_bytes = dotnet_preview_package_cache_budget(cache_mode)
            return build_or_lookup_rust_preview_package_with_builder(
                cache_root=output_root,
                archive_identity=(
                    f"{archive_identity}:placement:{quality}:materials={bool(include_material_resources)}:"
                    f"placement={item.placement!r}:origin={item.model_origin!r}"
                ),
                cache_mode=cache_mode,
                max_bytes=cache_max_bytes,
                target_bytes=cache_target_bytes,
                cancelled=stop_event.is_set,
                metadata={"surface": "new_item_placement", "source_token": repr(token)},
                builder=lambda target: publish(target),
            )
        package = progressive_material_package(
            build_placement_quality,
            # Comparison views also display the textured reference, even though
            # Overlay initially draws it as a wire guide.
            needs_full_material_tier=any(
                rust_preview_mesh_needs_material_synthesis(mesh)
                for mesh in (model_mesh, reference_mesh) if mesh is not None
            ),
        )
    elif getattr(item, "meshes", None) is not None and not hasattr(item, "submeshes"):
        from cdmw.services.mesh_rust_preview_cache import (
            build_or_lookup_rust_preview_package_from_model as build_or_lookup_dotnet_preview_package_from_model,
        )
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
            semantic_view_axis="auto",
            fast_package_ready=fast_package_ready,
        )
    else:
        from cdmw.services.mesh_rust_preview_package import (
            build_rust_preview_package,
            semantic_initial_view,
        )
        from cdmw.services.mesh_rust_authoring import rust_preview_mesh_needs_material_synthesis

        semantic_bounds = mesh_bounds(item)
        grid_normal_axis = _flat_preview_normal_axis(semantic_bounds)
        package = progressive_material_package(
            lambda quality: build_rust_preview_package(
                item,
                output_root=output_root,
                reference_mesh=None,
                comparison_mode="side_by_side",
                interaction_profile="static_replacement",
                grid_normal_axis=grid_normal_axis,
                cancelled=stop_event.is_set,
                include_material_resources=bool(include_material_resources),
                material_quality=quality,
                initial_view=semantic_initial_view(semantic_bounds, grid_normal_axis),
            ),
            needs_full_material_tier=rust_preview_mesh_needs_material_synthesis(item),
        )
    return Path(package.package_dir)


def package_cleanup_root(package_dir: Path, output_root: Path) -> Path:
    """The directory to remove for a package under `output_root`: the model route writes
    `<root>/cdmw_rust_preview_*/package`, the mesh route `<root>/<package>`."""

    parent = package_dir.parent
    if parent != output_root and parent.parent == output_root and parent.name.startswith("cdmw_rust_preview_"):
        return parent
    return package_dir


def default_host_factory(parent: QWidget):
    from cdmw.ui.preview.rust_host import RustPreviewHostFrame
    from cdmw.ui.preview.profile import DotNetPreviewProfile

    return RustPreviewHostFrame(parent, profile=DotNetPreviewProfile.PREVIEW, terminate_on_close=True)


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
        self._lighting_preset = "neutral_studio"
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
        self._last_pushed_placement: Optional[ModelPlacement] = None
        self._gizmo_tool = "move"
        self._gizmo_enabled = True
        self._view_mode = "overlay"
        self._grid_visible = True
        self._placement_grid_normal_axis = "y"
        self._model_bounds: Any = None
        #: (path, token, is_placement, stage) built while hidden, waiting for the viewport
        self._deferred_package: Optional[tuple[Path, Hashable, bool, str]] = None
        #: (token, is_placement, stage) of the build in flight
        self._building: Optional[tuple[Hashable, bool, str]] = None
        #: Full-material stage queued behind a geometry-first preview package.
        self._upgrade_request: Optional[tuple[Hashable, Any, bool, Path]] = None
        self._loaded_stage = ""
        self._full_texture_upgrade_from_fast = False
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
        lighting = getattr(self.host, "set_lighting_preset", None)
        if callable(lighting):
            lighting(self._lighting_preset)
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

    def set_lighting_preset(self, preset: object) -> None:
        normalized = str(preset or "neutral_studio").strip().lower()
        self._lighting_preset = (
            normalized if normalized in {"neutral_studio", "showcase"} else "neutral_studio"
        )
        if self.host is not None:
            lighting = getattr(self.host, "set_lighting_preset", None)
            if callable(lighting):
                lighting(self._lighting_preset)

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
        self._last_pushed_placement = None
        self._placement_grid_normal_axis = "y"
        self._show(source, token=token, is_placement=False)

    def _show(self, source: Any, *, token: Hashable = None, is_placement: bool = False) -> None:
        if self._closed:
            return
        if source is None:
            self._pending = None
            self._pending_is_placement = False
            self._upgrade_request = None
            self._full_texture_upgrade_from_fast = False
            self._placement = None
            self._last_pushed_placement = None
            self._placement_grid_normal_axis = "y"
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
        self._full_texture_upgrade_from_fast = False
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
        grid_bounds: Any = None,
        gizmo_enabled: bool = True,
    ) -> None:
        """Show a `PlacementScene` (or a callable producing one) with the model at
        `placement` (`model_bounds`: the model's own-space bounds, for the host's
        placement fallback; `grid_bounds`: the template's authoritative bounds), the
        gizmo on when `gizmo_enabled`. The same token already showing only takes the new
        placement and gizmo state."""

        same = self._pending is not None and self._pending[0] == token and (self._thread is not None or self.is_ready or self._deferred_package is not None)
        previous_placement = self._placement
        previous_gizmo_enabled = self._gizmo_enabled
        previous_model_bounds = self._model_bounds
        self._placement = placement
        self._gizmo_enabled = bool(gizmo_enabled)
        self._model_bounds = model_bounds
        self._placement_grid_normal_axis = _flat_preview_normal_axis(
            grid_bounds if grid_bounds is not None else model_bounds
        )
        if same:
            if self.is_ready and self.host is not None:
                if previous_model_bounds != model_bounds and model_bounds is not None:
                    self.host.remember_editable_local_bounds(model_bounds[0], model_bounds[1])
                if previous_gizmo_enabled != self._gizmo_enabled:
                    self.host.set_alignment_state(enabled=self._gizmo_enabled)
                if previous_placement != placement:
                    self._push_placement()
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
        changed = mode != self._view_mode
        self._view_mode = mode
        if self.is_ready and self.host is not None and self._placement is not None:
            applied = self.host.set_display_mode(mode)
            if changed and applied:
                self.fit_view()

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
        lighting = getattr(host, "set_lighting_preset", None)
        if callable(lighting):
            lighting(self._lighting_preset)
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
        """Frame the model flat without changing its game-authoritative placement."""

        if self.host is not None and self.is_ready:
            canonical = getattr(self.host, "request_canonical_view", None)
            if callable(canonical) and canonical():
                return
            self.host.reset_view()

    def _push_placement(self) -> None:
        host = self.host
        placement = self._placement
        if host is None or placement is None or not self.is_ready:
            return
        if placement == self._last_pushed_placement:
            return
        if host.set_alignment_preview_transform(
            translation=placement.offset,
            rotation_degrees=placement.rotation,
            scale_xyz=placement.scale,
        ):
            self._last_pushed_placement = placement

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
        task = _PreviewPackageTask(
            output_root=root,
            token=token,
            candidate=candidate_source,
            is_placement=is_placement,
            full_stage=full_stage,
            base_package=base_package,
            render_settings=render_settings,
            cache_mode=cache_mode,
            native_preview_core_cache_root=native_preview_core_cache_root,
            source_usage_required=callable(acquire_usage),
            source_usage_acquired=source_usage is not None,
        )
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

        step = (int(current), int(total))
        if step not in {(1, 2), (1, 3), (2, 3)} or not str(package_path or "").strip():
            return
        building = self._building
        self._package_ready(
            Path(package_path),
            stage="geometry" if step[0] == 1 else "fast_materials",
        )
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
            self.status_changed.emit(
                "Fast textures are visible; loading full textures…"
                if step == (2, 3)
                else "Loading model textures…"
            )

    def _package_failed(self, message: object) -> None:
        if self._closed or self._superseded:
            return
        if self._loaded_stage == "fast_materials" and self._building is not None and self._building[2] == "materials":
            self._full_texture_upgrade_from_fast = False
            self.status_changed.emit(
                f"Fast textures remain visible; full textures failed to load: {message}"
            )
        else:
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
        previous_stage = self._loaded_stage
        reset_view = previous is None or (stage == "geometry" and self._loaded_token != token)
        if self.host.load_package(result, reset_view=reset_view):
            self._last_pushed_placement = None
            self._package_dir = result
            if previous is not None and previous != result:
                self._retire_after_ready.append(previous)
            self._loaded = True
            self._loaded_token = token
            self._loaded_is_placement = bool(is_placement)
            self._loaded_stage = stage
            self._full_texture_upgrade_from_fast = stage == "materials" and previous_stage == "fast_materials"
            self._reset_view_on_ready = reset_view
            self.host.set_display_mode("replacement_only")
            self.status_changed.emit(
                "Fast textures are visible; loading full textures…"
                if stage == "fast_materials" or self._full_texture_upgrade_from_fast
                else "Loading model textures…"
                if stage == "materials"
                else "Loading the viewport..."
            )
        else:
            self._remove_package(result)
            if stage == "materials" and previous_stage == "fast_materials":
                self.status_changed.emit(
                    "Fast textures remain visible; full textures failed to load: "
                    "the resident viewport rejected the preview package."
                )
            else:
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
            building_materials = (
                self._building is not None
                and self._building[2] == "materials"
                and self._loaded_stage != "materials"
            )
            if self._loaded_stage == "materials":
                preview_status = "Full textures loaded."
            elif building_materials and self._loaded_stage == "fast_materials":
                preview_status = "Fast textures are visible; loading full textures…"
            else:
                preview_status = "Loading model textures…" if building_materials else ""
            self._full_texture_upgrade_from_fast = False
            self.status_changed.emit(preview_status)
            self.ready.emit()
        elif str(state) in {"error", "package_error"}:
            failure = str(message or "The viewport reported an error.")
            if self._full_texture_upgrade_from_fast:
                failure = f"Fast textures remain visible; full textures failed to load: {failure}"
            self._full_texture_upgrade_from_fast = False
            self.status_changed.emit(failure)

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

        from cdmw.services.mesh_rust_preview_cache import rust_preview_package_cache_root
        from cdmw.services.preview_rendering_service import (
            dotnet_preview_package_derived_cache_root,
            is_durable_dotnet_preview_package_path,
        )

        for cache_root in (
            rust_preview_package_cache_root(self._output_root),
            dotnet_preview_package_derived_cache_root(self._output_root),
        ):
            if is_durable_dotnet_preview_package_path(cache_root, package_dir):
                return
        shutil.rmtree(self._package_cleanup_root(package_dir), ignore_errors=True)

    def _package_cleanup_root(self, package_dir: Path) -> Path:
        return package_cleanup_root(package_dir, self._output_root)
