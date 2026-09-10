"""Build read-only body/armor scenes from already decoded archive previews."""

from pathlib import Path
import shutil
from uuid import uuid4

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mesh_rust_preview_cache import parsed_mesh_from_model_preview
from cdmw.services.mesh_rust_preview_package import build_rust_preview_package


def build_archive_mesh_comparison(target, source, *, target_mode, source_mode,
                                  output_root, scene_session_id, scene_generation, stop_event):
    """Keep original coordinates and choose the native solid/reference-wire roles."""
    if target_mode not in {"solid", "wire"} or source_mode not in {"solid", "wire"}:
        raise ValueError("Comparison display must be Solid or Wire")
    models = []
    for model, mode in ((target, target_mode), (source, source_mode)):
        raise_if_cancelled(stop_event, "Archive comparison cancelled")
        if model is not None:
            models.append((parsed_mesh_from_model_preview(model), mode))
    if not models:
        raise ValueError("No comparison geometry is available")
    if len(models) == 2 and models[0][1] == "wire" and models[1][1] == "solid":
        models.reverse()
    mesh, mode = models[0]
    reference, reference_mode = models[1] if len(models) == 2 else (None, "wire")
    root = Path(output_root).resolve()
    directory = (root / f"package_{uuid4().hex}").resolve()
    if directory.parent != root:
        raise ValueError("Archive comparison package must stay inside its output root")
    try:
        package = build_rust_preview_package(
            mesh, reference_mesh=reference, output_package_dir=directory,
            comparison_mode="overlay" if reference is not None else "replacement_only",
            reference_draw=reference_mode, include_material_resources=False,
            scene_session_id=scene_session_id, scene_generation=scene_generation,
            preview_overlays={"skeleton": {}, "cloth": {}, "effects": {}},
            cancelled=stop_event.is_set,
        )
        raise_if_cancelled(stop_event, "Archive comparison cancelled")
        return package, "wire" if mode == "wire" else "untextured_faces"
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
