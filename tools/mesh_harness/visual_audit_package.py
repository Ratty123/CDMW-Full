from __future__ import annotations

from collections.abc import Iterator, MutableMapping, Sequence
import hashlib
import json
import os
import shutil
from pathlib import Path


_LAYER_SOURCE_KEYS = (
    "diffuse_source",
    "mask_source",
    "material_source",
    "normal_source",
    "height_source",
)


def _iter_available_source_path_descriptors(
    value: object,
) -> Iterator[MutableMapping[str, object]]:
    """Yield batch descriptors the native material-role scan can select."""

    if isinstance(value, MutableMapping):
        if str(value.get("source_path", "") or "").strip() and bool(
            value.get("available", True)
        ):
            yield value
        for child in value.values():
            yield from _iter_available_source_path_descriptors(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _iter_available_source_path_descriptors(child)


def stabilize_visual_audit_archive_package(package_dir: Path) -> dict[str, object]:
    """Make transient native texture references durable for a batched audit run."""

    package_dir = Path(package_dir).resolve()
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"Visual-audit native manifest is not an object: {manifest_path}")

    targets_by_source: dict[str, Path] = {}
    linked_count = 0
    copied_count = 0
    reference_count = 0

    def stabilize_field(owner: MutableMapping[str, object], key: str) -> None:
        nonlocal copied_count, linked_count, reference_count
        raw_value = str(owner.get(key, "") or "").strip()
        if not raw_value:
            return
        source_path = Path(raw_value)
        if not source_path.is_absolute():
            source_path = package_dir / source_path
        source_path = source_path.resolve()
        if source_path.is_relative_to(package_dir):
            if not source_path.is_file():
                raise FileNotFoundError(
                    f"Visual-audit package references a missing owned texture: {source_path}"
                )
            return
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Visual-audit package references a missing transient texture: {source_path}"
            )

        reference_count += 1
        source_key = str(source_path).casefold()
        target_path = targets_by_source.get(source_key)
        if target_path is None:
            source_stat = source_path.stat()
            identity = (
                f"{source_key}|{int(source_stat.st_size)}|"
                f"{int(source_stat.st_mtime_ns)}"
            )
            digest = hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()[:20]
            suffix = source_path.suffix.lower() or ".bin"
            target_path = package_dir / "textures" / "audit-source" / f"{digest}{suffix}"
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if not target_path.is_file():
                try:
                    os.link(source_path, target_path)
                    linked_count += 1
                except OSError:
                    shutil.copy2(source_path, target_path)
                    copied_count += 1
            targets_by_source[source_key] = target_path
        owner[key] = str(target_path)

    for batch in tuple(manifest.get("batches", ()) or ()):
        if not isinstance(batch, dict):
            continue
        for descriptor in _iter_available_source_path_descriptors(batch):
            stabilize_field(descriptor, "source_path")
        for container_name in ("material_layers", "active_material_layers"):
            for layer in tuple(batch.get(container_name, ()) or ()):
                if isinstance(layer, dict):
                    for source_key in _LAYER_SOURCE_KEYS:
                        stabilize_field(layer, source_key)
        primary_layer = batch.get("primary_material_layer")
        if isinstance(primary_layer, dict):
            for source_key in _LAYER_SOURCE_KEYS:
                stabilize_field(primary_layer, source_key)

    temporary_manifest = manifest_path.with_suffix(".json.audit-tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)
    return {
        "schema": "cdmw_visual_audit_package_stability_v1",
        "external_reference_count": reference_count,
        "materialized_file_count": len(targets_by_source),
        "hardlink_count": linked_count,
        "copy_count": copied_count,
    }
