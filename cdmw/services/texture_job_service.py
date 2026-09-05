"""Immutable texture inputs and transactional publication for workspace jobs."""

from __future__ import annotations

import dataclasses
import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cdmw.models import AppConfig, ArchiveEntry, RunCancelled, TextureEditorDocument


@dataclass(frozen=True)
class TextureJobInput:
    relative_path: str
    original_path: Path | None
    document: TextureEditorDocument | None = None
    layer_pixels: object | None = None
    original_entry: ArchiveEntry | None = None
    package_path: Path | None = None
    package_target: object | None = None


def texture_job_relative_path(value: str) -> Path:
    relative = PurePosixPath(str(value).replace("\\", "/"))
    if relative.is_absolute() or not relative.parts or any(part in {"..", "."} or ":" in part for part in relative.parts):
        raise ValueError("Choose an explicit game-relative texture target.")
    if relative.suffix.lower() != ".dds":
        raise ValueError("A texture target must end in .dds.")
    return Path(*relative.parts)


def materialize_texture_package_asset(package_path: Path, target, destination: Path) -> Path:
    from cdmw.core.recolor_variants import materialize_recolor_variant_texture
    return materialize_recolor_variant_texture(package_path, target, destination)


def _texture_job_original(item: TextureJobInput, source_root: Path, stop_event) -> Path:
    original = item.original_path
    if original is not None and original.is_file():
        return original
    if item.original_entry is not None:
        from cdmw.services.archive_extraction_service import extract_archive_entry
        original, _decompressed, _note = extract_archive_entry(
            item.original_entry, source_root / "original.dds", stop_event=stop_event,
        )
        return original
    if item.package_path is not None and item.package_target is not None:
        return materialize_texture_package_asset(item.package_path, item.package_target, source_root)
    raise FileNotFoundError(f"Original DDS is unavailable: {item.relative_path}")


def write_texture_job_input(item: TextureJobInput, destination: Path, *, stop_event) -> None:
    from cdmw.core.common import raise_if_cancelled
    raise_if_cancelled(stop_event, "Texture job cancelled.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cdmw-texture-original-") as temp_dir:
        original = _texture_job_original(item, Path(temp_dir), stop_event)
        raise_if_cancelled(stop_event, "Texture job cancelled.")
        if item.document is None:
            shutil.copy2(original, destination)
            return
        from cdmw.core.texture_pipeline.inspection import parse_dds
        from cdmw.core.texture_native import encode_dds_with_directxtex
        from cdmw.services.texture_editor_service import TextureEditorService
        info = parse_dds(original)
        document = item.document
        png_path = Path(temp_dir) / "edited.png"
        TextureEditorService.export_flattened_png(document, item.layer_pixels, png_path)
        raise_if_cancelled(stop_event, "Texture job cancelled.")
        report = encode_dds_with_directxtex(
            png_path, destination, dds_format=info.dds_format,
            width=document.width, height=document.height, mip_count=info.mip_count,
            stop_event=stop_event,
        )
        if not report:
            raise RuntimeError(f"Could not encode edited texture: {item.relative_path}")


def run_texture_job_pipeline(config: AppConfig, inputs: tuple[TextureJobInput, ...], pipeline, **callbacks):
    """Run the existing pipeline on job inputs, publishing only a complete result.

    Every output is staged beside its final directory so replacement stays on
    the same volume. Existing files are retained, including unrelated outputs.
    """
    from cdmw.core.common import raise_if_cancelled
    from cdmw.services.atomic_file_service import atomic_publish_paths
    stop_event = callbacks.get("stop_event")
    if not inputs:
        raise ValueError("Select at least one texture in the asset list.")
    relative_paths = [texture_job_relative_path(item.relative_path) for item in inputs]
    if len({str(path).casefold() for path in relative_paths}) != len(relative_paths):
        raise ValueError("Two selected textures match the same target; review the matches first.")
    fields = ["output_root", "png_root"]
    if config.enable_dds_staging:
        fields.append("dds_staging_root")
    if config.enable_mod_ready_loose_export:
        fields.append("mod_ready_export_root")
    if any(not str(getattr(config, field)).strip() for field in fields):
        raise ValueError("Choose the texture output directories before exporting.")
    final_roots = {"output_root": Path(config.output_root).expanduser().resolve()}
    if config.enable_dds_staging:
        final_roots["dds_staging_root"] = Path(config.dds_staging_root).expanduser().resolve()
    if config.enable_mod_ready_loose_export:
        final_roots["mod_ready_export_root"] = Path(config.mod_ready_export_root).expanduser().resolve()
    png_final = Path(config.png_root).expanduser().resolve()
    roots = (*final_roots.values(), png_final)
    if any(a == b or a in b.parents or b in a.parents for index, a in enumerate(roots) for b in roots[index + 1:]):
        raise ValueError("Texture output directories must be separate, without nesting.")
    originals = [item.original_path.resolve() for item in inputs if item.original_path is not None]
    originals.extend(item.package_path.resolve() for item in inputs if item.package_path is not None)
    if any(root == original or root in original.parents for root in roots for original in originals):
        raise ValueError("Texture output cannot replace an original DDS directory.")
    with ExitStack() as cleanup:
        work = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix="cdmw-texture-job-")))
        original_root = work / "originals"
        png_root = work / "pngs"
        original_root.mkdir()
        png_root.mkdir()
        for item, relative in zip(inputs, relative_paths):
            write_texture_job_input(item, original_root / relative, stop_event=stop_event)
            existing_png = Path(config.png_root).expanduser() / relative.with_suffix(".png")
            if item.document is None and existing_png.is_file():
                target = png_root / relative.with_suffix(".png")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(existing_png, target)
            elif item.document is not None:
                from cdmw.services.texture_editor_service import TextureEditorService
                target = png_root / relative.with_suffix(".png")
                target.parent.mkdir(parents=True, exist_ok=True)
                TextureEditorService.export_flattened_png(item.document, item.layer_pixels, target)
        png_final.parent.mkdir(parents=True, exist_ok=True)
        png_stage_parent = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix=".cdmw-texture-pngs-", dir=png_final.parent)))
        png_stage = png_stage_parent / "pngs"
        shutil.copytree(png_root, png_stage)
        changes = {"original_dds_root": str(original_root), "png_root": str(png_stage),
                   "texture_editor_png_root": "", "include_filters": ""}
        publication = []
        for field, final in final_roots.items():
            final.parent.mkdir(parents=True, exist_ok=True)
            parent = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix=".cdmw-texture-stage-", dir=final.parent)))
            stage = parent / final.name
            if final.exists():
                shutil.copytree(final, stage)
            else:
                stage.mkdir()
            changes[field] = str(stage)
            publication.append((stage, final))
        summary = pipeline(dataclasses.replace(config, **changes), **callbacks)
        if summary.cancelled or (stop_event is not None and stop_event.is_set()):
            raise RunCancelled("Texture job cancelled.")
        if summary.failed or config.dry_run:
            return summary
        # Report paths that will survive staging cleanup.
        for row in summary.results:
            for field in ("png", "output_dir"):
                value = Path(getattr(row, field))
                for staged, final in [*publication, (png_stage, png_final)]:
                    if value.is_relative_to(staged):
                        setattr(row, field, str(final / value.relative_to(staged)))
                        break
            source = Path(row.original_dds)
            if source.is_relative_to(original_root):
                relative = source.relative_to(original_root)
                item = inputs[relative_paths.index(relative)]
                row.original_dds = str(item.original_path or item.relative_path)
        if summary.log_csv_path:
            from cdmw.core.texture_pipeline.logging import write_csv_log
            write_csv_log(Path(summary.log_csv_path), summary.results)
        raise_if_cancelled(stop_event, "Texture job cancelled.")
        publication.extend((path, png_final / path.relative_to(png_stage))
                           for path in png_stage.rglob("*") if path.is_file())
        for _staged, final in publication:
            final.parent.mkdir(parents=True, exist_ok=True)
        atomic_publish_paths(publication, check_cancelled=lambda: raise_if_cancelled(stop_event, "Texture job cancelled."))
        if summary.log_csv_path:
            for staged, final in publication:
                if Path(summary.log_csv_path).is_relative_to(staged):
                    summary.log_csv_path = final / Path(summary.log_csv_path).relative_to(staged)
                    break
        return summary
