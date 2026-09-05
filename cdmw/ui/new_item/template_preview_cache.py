"""Worker-side native template packages and their durable source revisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.preview_rendering_service import (
    find_native_preview_core_binary,
    render_settings_to_native_preview_core_dict,
)


def _file_stamp(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
        return str(path), stat.st_size, stat.st_mtime_ns
    except OSError:
        return str(path), -1, -1


def template_preview_cache_identity(entry, dependencies, template_key, render_settings, stop_event) -> str:
    """Include source archives that Preview Core may discover beyond the PAC.

    This runs on the package worker. Stat the small archive-file inventory,
    never the millions of indexed entries or their payloads.
    """

    raise_if_cancelled(stop_event)
    root = Path(entry.pamt_path).parent.parent
    archive_paths = {path for path in root.glob("*/*") if path.suffix.lower() in {".pamt", ".paz"}}
    for dependency in dependencies:
        pamt = Path(dependency.pamt_path)
        archive_paths.add(pamt)
        if dependency.paz_file:
            archive_paths.add(pamt.parent / dependency.paz_file)
        if prepared := getattr(dependency, "prepared_path", None):
            archive_paths.add(Path(prepared))
    archives = []
    for path in sorted(archive_paths):
        raise_if_cancelled(stop_event)
        archives.append(_file_stamp(path))
    binary = find_native_preview_core_binary()
    payload = {
        "schema": 2,
        "template_key": template_key,
        "primary": entry.path,
        "dependencies": [
            (item.path, str(item.pamt_path), str(item.paz_file), item.offset, item.comp_size,
             str(getattr(item, "prepared_path", None) or ""), str(getattr(item, "prepared_sha256", "") or ""))
            for item in dependencies
        ],
        "archives": archives,
        "native_binary": _file_stamp(Path(binary)) if binary is not None else None,
        "render_settings": render_settings_to_native_preview_core_dict(render_settings),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "new_item_native:" + hashlib.sha256(encoded).hexdigest()


def build_native_template_preview(
    entry, dependencies, prefab_entries, component_paths, template_key, snapshot, stop_event,
    *, output_root, native_preview_core_cache_root, render_settings, cache_mode,
    fast_package_ready=None, cache_only=False, consume_native_package=None,
):
    """Keep staged native resources alive until the final scene owns its copies."""

    import shutil
    import time
    from dataclasses import replace

    from cdmw.domain.cancellation import RunCancelled
    from cdmw.models import clamp_model_preview_render_settings
    from cdmw.services.mesh_rust_preview_cache import (
        build_or_lookup_rust_preview_package,
        lookup_rust_preview_package_from_preview_core_identity,
    )
    from cdmw.services.preview_rendering_service import (
        dotnet_preview_package_cache_budget,
        run_native_preview_core_preview_job,
    )
    from cdmw.workers.archive_preview_native import (
        native_preview_core_timeout_seconds,
        native_preview_model_property_indices,
    )

    preview_root = Path(output_root)
    native_settings = replace(
        clamp_model_preview_render_settings(render_settings), use_textures_by_default=True,
    )
    archive_identity = template_preview_cache_identity(
        entry, dependencies, template_key, native_settings, stop_event,
    )
    max_bytes, target_bytes = dotnet_preview_package_cache_budget(cache_mode)
    if consume_native_package is None and cache_mode in {"balanced", "aggressive"} and max_bytes > 0:
        cached = lookup_rust_preview_package_from_preview_core_identity(
            cache_root=preview_root, archive_identity=archive_identity, cancelled=stop_event.is_set,
        )
        if cached is not None:
            return Path(cached.package_dir)
    if cache_only:
        return None

    preview_root.mkdir(parents=True, exist_ok=True)
    native_package = preview_root / f"package_{time.time_ns()}_native"
    consuming = False
    try:
        attempt = run_native_preview_core_preview_job(
            entry,
            cache_root=Path(native_preview_core_cache_root),
            render_settings=native_settings,
            dependency_entries=dependencies,
            dependency_entries_complete=False,
            enabled_prefab_component_paths=component_paths,
            model_property_indices=native_preview_model_property_indices(
                prefab_entries, stop_event,
                read_entry_data=lambda candidate: snapshot.payload(candidate.path),
            ),
            package_root=Path(entry.pamt_path).parent.parent,
            output_root=native_package,
            timeout_seconds=native_preview_core_timeout_seconds(native_settings),
            stop_event=stop_event,
        )
        if not attempt.succeeded:
            return None
        raise_if_cancelled(stop_event)
        if consume_native_package is not None:
            consuming = True
            return consume_native_package(attempt.package_path)
        package = build_or_lookup_rust_preview_package(
            attempt.package_path,
            cache_root=preview_root,
            archive_identity=archive_identity,
            cache_mode=cache_mode,
            max_bytes=max_bytes,
            target_bytes=target_bytes,
            cancelled=stop_event.is_set,
            metadata={"surface": "new_item_studio", "source_path": entry.path},
            fast_package_ready=fast_package_ready,
        )
        return Path(package.package_dir)
    except RunCancelled:
        raise
    except Exception:  # noqa: BLE001 - native failure retains the established Python decoder
        if consuming:
            raise
        return None
    finally:
        shutil.rmtree(native_package, ignore_errors=True)
