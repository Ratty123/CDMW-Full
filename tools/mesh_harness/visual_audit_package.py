from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping, Sequence
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


def fingerprint_visual_audit_prepared_packages(
    runtime_assets: Sequence[Mapping[str, object]],
    *,
    run_id: str,
    corpus_sha256: str,
    temporary_root: Path,
) -> dict[str, object]:
    """Fingerprint every prepared native/.NET package file without mutating it."""

    temporary_root = Path(temporary_root).resolve()
    if not temporary_root.is_dir():
        raise ValueError("Visual-audit temporary package root is missing.")
    content_hash_cache: dict[tuple[object, ...], str] = {}
    asset_rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_roots: set[str] = set()
    for runtime_asset in runtime_assets:
        asset_id = str(runtime_asset.get("id", "") or "")
        if not asset_id or asset_id in seen_ids:
            raise ValueError("Prepared package fingerprints require unique non-empty asset IDs.")
        seen_ids.add(asset_id)
        package_rows: dict[str, object] = {}
        for key in ("archive_package_dir", "dotnet_package_dir"):
            package_root = Path(str(runtime_asset.get(key, "") or "")).resolve()
            root_key = str(package_root).casefold()
            if (
                not package_root.is_dir()
                or not package_root.is_relative_to(temporary_root)
                or root_key in seen_roots
            ):
                raise ValueError(f"Prepared package fingerprint root is invalid or reused: {key}")
            seen_roots.add(root_key)
            package_rows[key] = _fingerprint_visual_audit_tree(
                package_root,
                content_hash_cache=content_hash_cache,
            )
        asset_rows.append({"id": asset_id, **package_rows})
    if not asset_rows:
        raise ValueError("Prepared package fingerprints require at least one runtime asset.")
    aggregate_payload = json.dumps(
        asset_rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        "schema": "cdmw_mesh_visual_audit_prepared_package_fingerprints_v1",
        "run_id": str(run_id),
        "corpus_sha256": str(corpus_sha256),
        "asset_count": len(asset_rows),
        "assets": asset_rows,
        "aggregate_sha256": hashlib.sha256(aggregate_payload).hexdigest(),
    }


def _fingerprint_visual_audit_tree(
    package_root: Path,
    *,
    content_hash_cache: MutableMapping[tuple[object, ...], str],
) -> dict[str, object]:
    package_root = Path(package_root).resolve()
    file_rows: list[tuple[str, int, str]] = []
    seen_relative_paths: set[str] = set()
    paths = sorted(
        (path for path in package_root.rglob("*") if path.is_file()),
        key=lambda path: (
            path.relative_to(package_root).as_posix().casefold(),
            path.relative_to(package_root).as_posix(),
        ),
    )
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(package_root):
            raise ValueError(f"Prepared package file escapes its package root: {path}")
        relative = path.relative_to(package_root).as_posix()
        relative_key = relative.casefold()
        if not relative or relative_key in seen_relative_paths:
            raise ValueError(f"Prepared package has a duplicate case-insensitive path: {relative}")
        seen_relative_paths.add(relative_key)
        stat_before = path.stat()
        inode = int(getattr(stat_before, "st_ino", 0) or 0)
        identity: tuple[object, ...]
        if inode:
            identity = (
                int(getattr(stat_before, "st_dev", 0) or 0),
                inode,
                int(stat_before.st_size),
                int(stat_before.st_mtime_ns),
            )
        else:
            identity = (
                str(resolved).casefold(),
                int(stat_before.st_size),
                int(stat_before.st_mtime_ns),
            )
        content_sha256 = content_hash_cache.get(identity)
        if content_sha256 is None:
            content_sha256 = _stable_file_sha256(path, stat_before)
            content_hash_cache[identity] = content_sha256
        file_rows.append((relative, int(stat_before.st_size), content_sha256))
    if not file_rows:
        raise ValueError(f"Prepared package contains no files: {package_root}")
    digest = hashlib.sha256()
    for relative, size, content_sha256 in file_rows:
        digest.update(
            json.dumps(
                [relative, size, content_sha256],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return {
        "file_count": len(file_rows),
        "total_bytes": sum(row[1] for row in file_rows),
        "tree_sha256": digest.hexdigest(),
    }


def _stable_file_sha256(path: Path, stat_before: os.stat_result) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    stat_after = path.stat()
    if (
        int(stat_after.st_size) != int(stat_before.st_size)
        or int(stat_after.st_mtime_ns) != int(stat_before.st_mtime_ns)
        or int(getattr(stat_after, "st_ino", 0) or 0)
        != int(getattr(stat_before, "st_ino", 0) or 0)
    ):
        raise ValueError(f"Prepared package file changed while hashing: {path}")
    return digest.hexdigest()
