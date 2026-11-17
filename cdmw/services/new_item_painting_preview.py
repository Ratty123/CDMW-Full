"""New painting's 3D view: the frame's own mesh with the picture on its canvas.

The frame mesh is decoded the way Browse Archives decodes it, textures included; a part
it leaves without a base colour takes it from the source painting's `.pami`, which the
new painting copies. The canvas part's base colour is swapped for the full texture the
build will write: `compose_picture` puts the picture, shaped by Fill or
Whole, into the canvas's UV rectangle and carries its edges outward. The other parts keep
the game's textures. The result is a `ModelPreviewData` for Create New Item's own
viewport frame (`ItemPreviewFrame`), which builds the viewport package on its worker.

Checked on 2026-11-17 against game 1.0.0.3663 (`.work/research/2026-11-17-painting-ui`):
the package carries the composed picture as the canvas's base colour texture, in the
same orientation and flip setting as the shipped picture it replaces. What the game
itself draws is not checked here.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Callable, Optional

from cdmw.core.painting_picture import compose_picture, load_picture, plan_picture_texture
from cdmw.domain.cancellation import raise_if_cancelled

__all__ = ["PaintingPreviewError", "composed_picture_png", "painting_preview_folder", "painting_preview_model", "painting_preview_source"]

#: Composed canvas pictures kept for the 3D view; older ones are removed.
_KEEP = 12
_PREFIX = "canvas-"


class PaintingPreviewError(ValueError):
    """The 3D view cannot be made; the message says why."""


def painting_preview_folder() -> Path:
    """Where the composed canvas pictures go: CDMW's own temporary folder."""

    from cdmw.app.app_folder import workspace_temp_folder

    return Path(workspace_temp_folder()) / "painting-preview"


def _prune(folder: Path, keep: Path) -> None:
    try:
        pictures = sorted((path for path in folder.glob(f"{_PREFIX}*.png") if path != keep),
                          key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return
    for stale in pictures[_KEEP - 1:]:
        try:
            stale.unlink()
        except OSError:
            pass


def composed_picture_png(frame, picture, fit: str, folder: Path) -> Path:
    """The full canvas texture as the build composes it, as a PNG in `folder` (made once
    per picture file, fit and frame)."""

    source = Path(str(picture))
    try:
        stat = source.stat()
    except OSError as exc:
        raise PaintingPreviewError(f"The picture {source.name} cannot be read: {exc}") from exc
    plan = plan_picture_texture(frame.texture_size, frame.canvas)
    identity = repr((str(source.resolve()), stat.st_mtime_ns, stat.st_size, str(fit), frame.mesh,
                     tuple(frame.texture_size), tuple(frame.canvas.uv_rect), frame.canvas.aspect))
    target = Path(folder) / f"{_PREFIX}{hashlib.sha1(identity.encode('utf-8')).hexdigest()[:24]}.png"
    if not target.is_file():
        composed = compose_picture(load_picture(source), plan, fit=fit)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.stem + f".{os.getpid()}.{threading.get_ident()}.part.png")
        composed.save(partial)
        os.replace(partial, target)
    _prune(target.parent, target)
    return target


def _pami_base_textures(pami_text: str) -> dict:
    """`{material: base colour texture path}` from a painting's `.pami`."""

    from cdmw.core.crimson_formats import parse_pami_material_instances

    found = {}
    for instance in parse_pami_material_instances(pami_text):
        name = str(instance.primitive_name or instance.material_name or "").strip()
        for parameter in instance.texture_parameters:
            if parameter.parameter_name == "_baseColorTexture" and name and name not in found:
                found[name] = str(parameter.texture_path or "")
    return found


def _bind_missing_frame_textures(model, canvas_material: str, pami_text: str, texture_entry_of: Callable,
                                 texture_preview: Callable, stop_event) -> None:
    """Parts the decode left without a base colour take it from the painting's own `.pami`,
    which the new painting copies (cd_in_dpw_picture_06's two metal trims, 2026-11-17)."""

    bindings = _pami_base_textures(pami_text)
    for mesh in model.meshes:
        material = str(getattr(mesh, "material_name", "") or "").strip()
        if material == canvas_material or str(getattr(mesh, "preview_texture_path", "") or "").strip():
            continue
        texture = bindings.get(material)
        entry = texture_entry_of(texture) if texture else None
        if entry is None:
            continue
        raise_if_cancelled(stop_event, "The 3D view was cancelled.")
        try:
            mesh.preview_texture_path = str(texture_preview(entry, stop_event=stop_event))
        except Exception:  # noqa: BLE001 - the part keeps its plain colour, as before
            continue
        mesh.preview_texture_image = None
        mesh.preview_base_texture_source = "pami"


def painting_preview_model(entry, frame, picture, fit: str, *, texture_entries_by_normalized_path,
                           texture_entries_by_basename, folder: Optional[Path] = None,
                           stop_event: Optional[threading.Event] = None, decode: Optional[Callable] = None,
                           pami_text: str = "", texture_entry_of: Optional[Callable] = None,
                           texture_preview: Optional[Callable] = None):
    """The frame mesh `entry` as a `ModelPreviewData`, with `picture` on its canvas.

    Without a picture the frame shows the game's own picture, as Browse Archives shows it.
    `pami_text` (the source painting's material file) fills in base textures the decode
    could not resolve, with `texture_entry_of(path)` finding the archive entry.
    """

    from cdmw.services.archive_preview_service import build_archive_preview_result, clone_archive_preview_model

    if entry is None:
        raise PaintingPreviewError(f"The game has no file {frame.mesh}.")
    decoded = (decode or build_archive_preview_result)(
        entry,
        texture_entries_by_normalized_path=texture_entries_by_normalized_path,
        texture_entries_by_basename=texture_entries_by_basename,
        enable_hkx_visual_preview=False,
        stop_event=stop_event,
    )
    model = getattr(decoded, "preview_model", None)
    if model is None or not getattr(model, "meshes", None):
        raise PaintingPreviewError(f"The frame {frame.stem} could not be read for the 3D view.")
    # The decode may be cached and shared; the canvas is changed on a copy.
    model = clone_archive_preview_model(model)
    if pami_text and texture_entry_of is not None:
        if texture_preview is None:
            from cdmw.core.archive_model_textures import _ensure_archive_model_texture_preview_path as texture_preview
        _bind_missing_frame_textures(model, frame.canvas.material, pami_text, texture_entry_of, texture_preview,
                                     stop_event)
    if not str(picture or "").strip():
        return model
    raise_if_cancelled(stop_event, "The 3D view was cancelled.")
    canvas = [mesh for mesh in model.meshes if str(getattr(mesh, "material_name", "") or "").strip() == frame.canvas.material]
    if not canvas:
        raise PaintingPreviewError(f"The frame {frame.stem} has no canvas part to show the picture on.")
    png = composed_picture_png(frame, picture, fit, Path(folder) if folder is not None else painting_preview_folder())
    raise_if_cancelled(stop_event, "The 3D view was cancelled.")
    for mesh in canvas:
        mesh.preview_texture_path = str(png)
        mesh.preview_texture_dds_path = ""
        mesh.preview_texture_image = None
        mesh.preview_base_texture_source = "painting picture"
        # The game's own picture is bound as a base input too; the new picture replaces it.
        inputs = getattr(mesh, "preview_material_texture_inputs", ()) or ()
        kept = [value for value in inputs if str(getattr(value, "slot_kind", "") or "") != "base"]
        mesh.preview_material_texture_inputs = type(inputs)(kept) if isinstance(inputs, (list, tuple)) else tuple(kept)
    return model


def painting_preview_source(snapshot, frame, picture, fit: str, *, folder: Optional[Path] = None):
    """`(stop_event) -> ModelPreviewData` for the viewport frame's worker: nothing heavy
    runs on the thread that asks for it."""

    def normal(path: str) -> str:
        return str(path or "").replace("\\", "/").strip().strip("/").lower()

    def build(stop_event: threading.Event):
        entry = snapshot.entries.get(normal(frame.mesh))
        by_path, by_basename = snapshot.archive_index_maps()
        pami = str(getattr(getattr(frame, "source", None), "pami", "") or "")
        try:
            pami_text = snapshot.payload(pami).decode("utf-8") if pami and normal(pami) in snapshot.entries else ""
        except (OSError, UnicodeDecodeError, ValueError):
            pami_text = ""
        return painting_preview_model(entry, frame, picture, fit, texture_entries_by_normalized_path=by_path,
                                      texture_entries_by_basename=by_basename, folder=folder, stop_event=stop_event,
                                      pami_text=pami_text, texture_entry_of=lambda path: snapshot.entries.get(normal(path)))

    return build
