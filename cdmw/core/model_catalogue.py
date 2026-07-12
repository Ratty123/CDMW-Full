from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from urllib.parse import unquote, urljoin
from urllib.request import Request, urlopen

from cdmw.core.atomic_file import atomic_publish_directory, atomic_write_text
from cdmw.core.common import raise_if_cancelled
from cdmw.core.model_catalogue_zip import (
    reusable_extract_matches as _reusable_extract_matches,
    safe_zip_member_name,
    split_nested_zip_member_ref,
    zip_contains_importable_model,
    zip_importable_member_refs,
    zip_importable_members,
)
from cdmw.domain.library.models import (
    BROWSABLE_MODEL_EXTENSIONS,
    DEFAULT_MODEL_MIRROR_URL,
    IMPORTABLE_MODEL_EXTENSIONS,
    LOCAL_MODEL_TEXTURE_EXTENSIONS,
    MODEL_DOWNLOAD_MAX_BYTES,
    MODEL_DOWNLOAD_MIN_FREE_BYTES,
    ZIP_EXTRACT_MAX_COMPRESSION_RATIO,
    ZIP_EXTRACT_MAX_MEMBER_BYTES,
    ZIP_EXTRACT_MAX_MEMBERS,
    ZIP_EXTRACT_MAX_TOTAL_BYTES,
    LocalModelFile,
    MirrorDownloadCandidate,
    MirrorDownloadResult,
    is_importable_model_path,
    mirror_download_candidates,
    normalize_mirror_base_url,
    normalize_mirror_model_record,
    parse_catalogue_links,
    safe_catalogue_link_name,
)
from cdmw.domain.library.scene_selection import select_model_archive_member


_GENERIC_LOCAL_MODEL_FILE_STEMS = {
    "asset",
    "default",
    "export",
    "main",
    "mesh",
    "model",
    "object",
    "scene",
    "source",
    "untitled",
}

_GENERIC_LOCAL_MODEL_DIRECTORY_NAMES = _GENERIC_LOCAL_MODEL_FILE_STEMS | {
    "3d",
    "3dmodel",
    "3dmodels",
    "assets",
    "catalogue",
    "dae",
    "download",
    "downloads",
    "files",
    "glb",
    "gltf",
    "library",
    "locallibrary",
    "modelcatalog",
    "modelcatalogue",
    "models",
    "scenes",
    "sources",
}

_TRAILING_MODEL_CATALOGUE_UID_RE = re.compile(r"[-_\s]+[0-9a-fA-F]{24,64}$")
_LOCAL_MODEL_SCAN_IGNORED_DIRECTORY_NAMES = {".cdmw_extracted", ".cdmw_nested_zip"}


def scan_local_model_files(
    roots: Iterable[Path | str],
    *,
    extensions: Iterable[str] = BROWSABLE_MODEL_EXTENSIONS,
    max_files: int = 50_000,
    stop_event: Optional[threading.Event] = None,
) -> tuple[LocalModelFile, ...]:
    normalized_extensions = {str(ext).lower() for ext in extensions}
    results: list[LocalModelFile] = []
    seen: set[str] = set()
    metadata_name_cache: dict[str, str] = {}
    texture_count_cache: dict[tuple[str, str], int] = {}
    for root_value in roots:
        root = Path(root_value).expanduser()
        try:
            root = root.resolve()
        except OSError:
            root = root.absolute()
        if not root.is_dir():
            continue
        try:
            iterator = root.rglob("*")
            for path in iterator:
                if stop_event is not None and stop_event.is_set():
                    break
                if len(results) >= max_files:
                    break
                try:
                    if not path.is_file():
                        continue
                    suffix = path.suffix.lower()
                    if suffix not in normalized_extensions:
                        continue
                    resolved = path.resolve()
                    if any(part.casefold() in _LOCAL_MODEL_SCAN_IGNORED_DIRECTORY_NAMES for part in resolved.parts):
                        continue
                    key = str(resolved).casefold()
                    if key in seen:
                        continue
                    stat = resolved.stat()
                except OSError:
                    continue
                seen.add(key)
                import_supported = suffix in IMPORTABLE_MODEL_EXTENSIONS
                if suffix == ".zip":
                    import_supported = zip_contains_importable_model(resolved)
                texture_status = local_model_texture_status(resolved, cache=texture_count_cache)
                results.append(
                    LocalModelFile(
                        path=resolved,
                        root=root,
                        name=_local_model_display_name(resolved, root, metadata_name_cache),
                        extension=suffix,
                        size=int(stat.st_size),
                        modified_at=float(stat.st_mtime),
                        import_supported=import_supported,
                        texture_status=texture_status,
                    )
                )
        except OSError:
            continue
    results.sort(key=lambda item: (item.name.lower(), str(item.path).lower()))
    return tuple(results)


def _local_model_display_name(path: Path, root: Path, metadata_name_cache: dict[str, str]) -> str:
    metadata_name = _local_model_metadata_name(path, root, metadata_name_cache)
    if metadata_name:
        return metadata_name
    stem = path.stem.strip()
    if stem and not _is_generic_local_model_file_stem(stem):
        return _clean_local_model_display_name(stem) or stem
    parent_name = _nearest_descriptive_local_model_parent_name(path, root)
    return parent_name or stem or path.name or "model"


def _local_model_metadata_name(path: Path, root: Path, metadata_name_cache: dict[str, str]) -> str:
    metadata_path = _nearest_local_model_metadata_path(path, root)
    if metadata_path is None:
        return ""
    cache_key = str(metadata_path).casefold()
    cached = metadata_name_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata_name_cache[cache_key] = ""
        return ""
    name = ""
    if isinstance(payload, Mapping):
        name = str(payload.get("name", "") or payload.get("title", "") or "").strip()
    metadata_name_cache[cache_key] = name
    return name


def _nearest_local_model_metadata_path(path: Path, root: Path) -> Optional[Path]:
    current = path.parent
    while True:
        metadata_path = current / "model_metadata.json"
        if metadata_path.is_file():
            return metadata_path
        if current == root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _nearest_descriptive_local_model_parent_name(path: Path, root: Path) -> str:
    current = path.parent
    direct_parent = current
    while True:
        if current == root and direct_parent == root:
            break
        cleaned = _clean_local_model_display_name(current.name)
        if cleaned and not _is_generic_local_model_directory_name(cleaned):
            return cleaned
        if current == root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return ""


def _clean_local_model_display_name(value: str) -> str:
    name = unquote(str(value or "")).strip()
    name = _TRAILING_MODEL_CATALOGUE_UID_RE.sub("", name).strip(" .-_")
    name = re.sub(r"[_-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _is_generic_local_model_file_stem(value: str) -> bool:
    return _local_model_name_token(value) in _GENERIC_LOCAL_MODEL_FILE_STEMS


def _is_generic_local_model_directory_name(value: str) -> bool:
    return _local_model_name_token(value) in _GENERIC_LOCAL_MODEL_DIRECTORY_NAMES


def _local_model_name_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def local_model_texture_status(path: Path | str, *, cache: Optional[dict[tuple[str, str], int]] = None) -> str:
    model_path = Path(path)
    suffix = model_path.suffix.lower()
    if suffix == ".zip":
        count = _count_zip_texture_members(model_path, cache=cache)
        return f"In ZIP ({count})" if count > 0 else "None found"
    if suffix == ".glb":
        return "Embedded/Unknown"
    if not is_importable_model_path(model_path):
        return "Unknown"
    count = _nearby_texture_count(model_path, cache=cache)
    return f"Found ({count})" if count > 0 else "None found"


def _nearby_texture_count(scene_path: Path, *, cache: Optional[dict[tuple[str, str], int]] = None) -> int:
    roots: list[tuple[Path, bool]] = [
        (scene_path.parent, False),
        (scene_path.parent / "textures", True),
        (scene_path.parent / "texture", True),
        (scene_path.parent.parent / "textures", True),
        (scene_path.parent.parent / "texture", True),
    ]
    seen_roots: set[str] = set()
    total = 0
    for root, recursive in roots:
        if not root.is_dir():
            continue
        try:
            key = str(root.resolve()).casefold()
        except OSError:
            key = str(root.absolute()).casefold()
        if key in seen_roots:
            continue
        seen_roots.add(key)
        total += _count_texture_files(root, recursive=recursive, cache=cache)
    return total


def _count_texture_files(
    root: Path,
    *,
    recursive: bool,
    limit: int = 999,
    cache: Optional[dict[tuple[str, str], int]] = None,
) -> int:
    try:
        resolved = root.resolve()
    except OSError:
        resolved = root.absolute()
    cache_key = (str(resolved).casefold(), "r" if recursive else "flat")
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    count = 0
    iterator = resolved.rglob("*") if recursive else resolved.iterdir()
    try:
        for candidate in iterator:
            if candidate.is_file() and candidate.suffix.lower() in LOCAL_MODEL_TEXTURE_EXTENSIONS:
                count += 1
                if count >= limit:
                    break
    except OSError:
        count = 0
    if cache is not None:
        cache[cache_key] = count
    return count


def _count_zip_texture_members(
    archive_path: Path,
    *,
    limit: int = 999,
    cache: Optional[dict[tuple[str, str], int]] = None,
) -> int:
    try:
        resolved = archive_path.resolve()
    except OSError:
        resolved = archive_path.absolute()
    cache_key = (str(resolved).casefold(), "zip-textures")
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    count = 0
    try:
        with zipfile.ZipFile(resolved, "r") as zip_file:
            for member in zip_file.infolist():
                member_name = member.filename.replace("\\", "/")
                if member.is_dir() or not member_name or member_name.startswith("/") or "../" in f"/{member_name}":
                    continue
                if PurePosixPath(member_name).suffix.lower() in LOCAL_MODEL_TEXTURE_EXTENSIONS:
                    count += 1
                    if count >= limit:
                        break
    except (OSError, zipfile.BadZipFile):
        count = 0
    if cache is not None:
        cache[cache_key] = count
    return count


def resolve_importable_model_path(
    path: Path | str,
    *,
    extract_root: Optional[Path | str] = None,
    selected_member: str = "",
    stop_event: Optional[threading.Event] = None,
) -> Optional[Path]:
    source_path = Path(path).expanduser()
    raise_if_cancelled(stop_event, "Model import resolution cancelled.")
    if source_path.is_file() and is_importable_model_path(source_path):
        return source_path
    if source_path.is_dir():
        direct_candidates: list[Path] = []
        for candidate in source_path.iterdir():
            raise_if_cancelled(stop_event, "Model import resolution cancelled.")
            if candidate.is_file() and is_importable_model_path(candidate):
                direct_candidates.append(candidate)
        direct_candidates.sort()
        if direct_candidates:
            return direct_candidates[0]
        for folder_name in ("gltf", "glb", "source", "model", "models"):
            model_dir = source_path / folder_name
            if not model_dir.is_dir():
                continue
            candidates: list[Path] = []
            for candidate in model_dir.rglob("*"):
                raise_if_cancelled(stop_event, "Model import resolution cancelled.")
                candidates.append(candidate)
            for candidate in sorted(candidates):
                if candidate.is_file() and is_importable_model_path(candidate):
                    return candidate
        candidates = []
        for candidate in source_path.rglob("*"):
            raise_if_cancelled(stop_event, "Model import resolution cancelled.")
            candidates.append(candidate)
        for candidate in sorted(candidates):
            if candidate.is_file() and is_importable_model_path(candidate):
                return candidate
        return None
    if source_path.suffix.lower() != ".zip" or not source_path.is_file():
        return None
    members = zip_importable_member_refs(source_path, stop_event=stop_event)
    member = select_model_archive_member(source_path, members, selected_member=selected_member)
    if member is None:
        return None
    destination = Path(extract_root).expanduser() if extract_root is not None else source_path.parent / ".cdmw_extracted" / source_path.stem
    safe_extract_zip(source_path, destination, stop_event=stop_event)
    outer_member, nested_member = split_nested_zip_member_ref(member)
    if not nested_member:
        candidate = destination.joinpath(*PurePosixPath(outer_member).parts)
        return candidate if candidate.is_file() and is_importable_model_path(candidate) else None
    nested_archive = destination.joinpath(*PurePosixPath(outer_member).parts)
    if not nested_archive.is_file():
        return None
    nested_destination = destination / ".cdmw_nested_zip" / _nested_zip_extract_dir_name(outer_member)
    safe_extract_zip(nested_archive, nested_destination, stop_event=stop_event)
    candidate = nested_destination.joinpath(*PurePosixPath(nested_member).parts)
    return candidate if candidate.is_file() and is_importable_model_path(candidate) else None


def _nested_zip_extract_dir_name(member_name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(member_name or "").replace("\\", "/")).strip("._")
    return clean[:96] or "nested_zip"


def download_mirror_model(
    record: Mapping[str, Any],
    *,
    mirror_url: str,
    output_root: Path | str,
    preferred_format: str = "gltf",
    require_importable: bool = False,
    timeout: float = 120.0,
    stop_event: Optional[threading.Event] = None,
) -> MirrorDownloadResult:
    base_url = normalize_mirror_base_url(mirror_url)
    candidates = mirror_download_candidates(record, base_url, preferred_format=preferred_format)
    if not candidates:
        raise ValueError("Selected mirror model does not expose a downloadable archive URL.")
    if require_importable:
        candidate = next((item for item in candidates if item.import_supported), None)
        if candidate is None:
            raise ValueError("Selected mirror model does not expose an importable model archive.")
    else:
        candidate = candidates[0]
    result = download_mirror_model_candidate(
        record,
        candidate,
        output_root=output_root,
        timeout=timeout,
        stop_event=stop_event,
    )
    if require_importable and result.import_path is None and not result.importable_members:
        raise ValueError("Downloaded archive does not contain an importable OBJ, DAE, glTF, GLB, or local mesh source.")
    return result


def download_mirror_model_candidate(
    record: Mapping[str, Any],
    candidate: MirrorDownloadCandidate,
    *,
    output_root: Path | str,
    timeout: float = 120.0,
    stop_event: Optional[threading.Event] = None,
) -> MirrorDownloadResult:
    uid = str(record.get("uid", "") or "").strip()
    name = str(record.get("name", "") or uid or "model").strip()
    asset_dir = Path(output_root).expanduser() / f"{_slugify(name, fallback='model')[:72]}-{uid}"
    asset_dir.mkdir(parents=True, exist_ok=True)
    archive_path = asset_dir / candidate.filename
    if not archive_path.is_file():
        download_kwargs: dict[str, object] = {"timeout": timeout}
        if stop_event is not None:
            download_kwargs["stop_event"] = stop_event
        _download_url_to_file(candidate.url, archive_path, **download_kwargs)
    metadata_path = asset_dir / "model_metadata.json"
    atomic_write_text(metadata_path, json.dumps(dict(record), ensure_ascii=False, indent=2))
    import_path: Optional[Path] = None
    importable_members: tuple[str, ...] = ()
    if candidate.format == "glb":
        import_path = archive_path
    elif candidate.format in {"gltf", "source"}:
        extract_name = "gltf" if candidate.format == "gltf" else "source"
        importable_members = zip_importable_member_refs(archive_path, stop_event=stop_event)
        if len(importable_members) == 1:
            import_path = resolve_importable_model_path(
                archive_path,
                extract_root=asset_dir / extract_name,
                selected_member=importable_members[0],
                stop_event=stop_event,
            )
    return MirrorDownloadResult(
        record=record,
        candidate=candidate,
        archive_path=archive_path,
        asset_dir=asset_dir,
        import_path=import_path,
        importable_members=importable_members,
    )


def _zip_extract_fingerprint(members: Sequence[zipfile.ZipInfo]) -> str:
    digest = hashlib.sha256()
    for member in members:
        digest.update(
            f"{member.filename}\0{member.CRC}\0{member.file_size}\0{member.compress_size}\n".encode(
                "utf-8", "surrogatepass"
            )
        )
    return digest.hexdigest()


def _remove_extract_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def safe_extract_zip(
    archive_path: Path | str,
    destination: Path | str,
    *,
    stop_event: Optional[threading.Event] = None,
    max_members: int = ZIP_EXTRACT_MAX_MEMBERS,
    max_total_bytes: int = ZIP_EXTRACT_MAX_TOTAL_BYTES,
) -> None:
    archive = Path(archive_path)
    target_root = Path(destination)
    target_parent = target_root.parent
    target_parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "r") as zip_file:
        members = zip_file.infolist()
        if len(members) > max(1, int(max_members)):
            raise ValueError(f"Model archive has too many members ({len(members):,}).")
        fingerprint = _zip_extract_fingerprint(members)
        total_bytes = 0
        normalized_names: set[str] = set()
        validated: list[tuple[zipfile.ZipInfo, str]] = []
        for member in members:
            raise_if_cancelled(stop_event, "Model archive extraction cancelled.")
            member_name = safe_zip_member_name(member.filename)
            if not member_name:
                raise ValueError(f"Unsafe path in model archive: {member.filename}")
            identity = member_name.casefold()
            if identity in normalized_names:
                raise ValueError(f"Duplicate path in model archive: {member.filename}")
            normalized_names.add(identity)
            mode = int(member.external_attr >> 16)
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symlink is not allowed in model archive: {member.filename}")
            if member.flag_bits & 0x1:
                raise ValueError(f"Encrypted model archive member is not supported: {member.filename}")
            member_bytes = int(member.file_size)
            if member_bytes < 0 or member_bytes > ZIP_EXTRACT_MAX_MEMBER_BYTES:
                raise ValueError(f"Model archive member is too large: {member.filename}")
            total_bytes += member_bytes
            if total_bytes > max(1, int(max_total_bytes)):
                raise ValueError("Model archive expanded size exceeds the extraction limit.")
            ratio = member_bytes / max(1, int(member.compress_size))
            if member_bytes > 1024 * 1024 and ratio > ZIP_EXTRACT_MAX_COMPRESSION_RATIO:
                raise ValueError(f"Model archive member compression ratio is unsafe: {member.filename}")
            validated.append((member, member_name))

        if _reusable_extract_matches(
            target_root,
            fingerprint=fingerprint,
            validated=validated,
            stop_event=stop_event,
        ):
            return

        free_bytes = shutil.disk_usage(target_parent).free
        if total_bytes > free_bytes:
            raise ValueError("Model archive needs more free disk space than is available.")

        temp_root = Path(tempfile.mkdtemp(prefix=f".{target_root.name}.extract-", dir=target_parent))
        try:
            copied_bytes = 0
            extracted_members: list[dict[str, object]] = []
            for member, member_name in validated:
                raise_if_cancelled(stop_event, "Model archive extraction cancelled.")
                output_path = temp_root.joinpath(*PurePosixPath(member_name).parts)
                if member.is_dir():
                    output_path.mkdir(parents=True, exist_ok=True)
                    extracted_members.append({"path": member_name, "directory": True, "size": 0})
                    continue
                output_path.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with zip_file.open(member, "r") as source, output_path.open("xb") as target:
                    while True:
                        raise_if_cancelled(stop_event, "Model archive extraction cancelled.")
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        copied_bytes += len(chunk)
                        if copied_bytes > max(1, int(max_total_bytes)):
                            raise ValueError("Model archive expanded size exceeds the extraction limit.")
                        target.write(chunk)
                        digest.update(chunk)
                extracted_members.append(
                    {
                        "path": member_name,
                        "directory": False,
                        "size": int(member.file_size),
                        "sha256": digest.hexdigest(),
                    }
                )
            (temp_root / ".cdmw-extract.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "fingerprint": fingerprint,
                        "member_count": len(validated),
                        "members": extracted_members,
                    }
                ),
                encoding="utf-8",
            )
            atomic_publish_directory(temp_root, target_root)
        finally:
            _remove_extract_path(temp_root)


def initialize_catalogue_db(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shards (
            name TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            model_count INTEGER NOT NULL DEFAULT 0,
            indexed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS models (
            uid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            viewer_url TEXT NOT NULL DEFAULT '',
            creator_name TEXT NOT NULL DEFAULT '',
            creator_username TEXT NOT NULL DEFAULT '',
            license_label TEXT NOT NULL DEFAULT '',
            license_slug TEXT NOT NULL DEFAULT '',
            is_downloadable INTEGER NOT NULL DEFAULT 1,
            is_age_restricted INTEGER NOT NULL DEFAULT 0,
            face_count INTEGER,
            vertex_count INTEGER,
            like_count INTEGER,
            view_count INTEGER,
            published_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            categories TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            archives_json TEXT NOT NULL DEFAULT '{}',
            mirror_url TEXT NOT NULL DEFAULT '',
            metadata_url TEXT NOT NULL DEFAULT '',
            thumbnail_url TEXT NOT NULL DEFAULT '',
            gltf_url TEXT NOT NULL DEFAULT '',
            glb_url TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            extra_url TEXT NOT NULL DEFAULT '',
            indexed_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_models_name ON models(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_models_license ON models(license_label)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_models_counts ON models(view_count, like_count)")
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS models_fts USING fts5(
                uid UNINDEXED,
                name,
                creator,
                tags,
                categories,
                description
            )
            """
        )
        conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('fts5_enabled', '1')")
    except sqlite3.OperationalError:
        conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('fts5_enabled', '0')")
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', '1')")
    conn.commit()
    return conn


def upsert_catalogue_records(
    conn: sqlite3.Connection,
    records: Sequence[Mapping[str, Any]],
    *,
    shard_name: str,
    shard_url: str,
) -> None:
    indexed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows = []
    fts_rows = []
    for record in records:
        uid = str(record.get("uid", "") or "").strip()
        if not uid:
            continue
        creator = str(record.get("creator_name", "") or record.get("creator_username", "") or "")
        tags = _join_values(record.get("tags"))
        categories = _join_values(record.get("categories"))
        rows.append(
            (
                uid,
                str(record.get("name", "") or uid),
                str(record.get("description", "") or ""),
                str(record.get("viewer_url", "") or ""),
                str(record.get("creator_name", "") or ""),
                str(record.get("creator_username", "") or ""),
                str(record.get("license_label", "") or ""),
                str(record.get("license_slug", "") or ""),
                1 if record.get("is_downloadable", True) else 0,
                1 if record.get("is_age_restricted", False) else 0,
                record.get("face_count"),
                record.get("vertex_count"),
                record.get("like_count"),
                record.get("view_count"),
                str(record.get("published_at", "") or ""),
                str(record.get("created_at", "") or ""),
                categories,
                tags,
                json.dumps(record.get("archives") or {}, ensure_ascii=False, separators=(",", ":")),
                str(record.get("mirror_url", "") or ""),
                str(record.get("metadata_url", "") or ""),
                str(record.get("thumbnail_url", "") or ""),
                str(record.get("gltf_url", "") or ""),
                str(record.get("glb_url", "") or ""),
                str(record.get("source_url", "") or ""),
                str(record.get("extra_url", "") or ""),
                indexed_at,
            )
        )
        fts_rows.append((uid, str(record.get("name", "") or uid), creator, tags, categories, str(record.get("description", "") or "")))

    if rows:
        conn.executemany(
            """
            INSERT OR REPLACE INTO models (
                uid, name, description, viewer_url, creator_name, creator_username,
                license_label, license_slug, is_downloadable, is_age_restricted,
                face_count, vertex_count, like_count, view_count, published_at,
                created_at, categories, tags, archives_json, mirror_url,
                metadata_url, thumbnail_url, gltf_url, glb_url, source_url,
                extra_url, indexed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        if _catalogue_fts_enabled(conn):
            try:
                conn.executemany("DELETE FROM models_fts WHERE uid = ?", [(row[0],) for row in fts_rows])
                conn.executemany(
                    "INSERT INTO models_fts(uid, name, creator, tags, categories, description) VALUES (?, ?, ?, ?, ?, ?)",
                    fts_rows,
                )
            except sqlite3.OperationalError:
                conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('fts5_enabled', '0')")
    conn.execute(
        "INSERT OR REPLACE INTO shards(name, url, model_count, indexed_at) VALUES (?, ?, ?, ?)",
        (shard_name, shard_url, len(rows), indexed_at),
    )
    conn.commit()


def clear_catalogue_records(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM models")
    conn.execute("DELETE FROM shards")
    if _catalogue_fts_enabled(conn):
        try:
            conn.execute("DELETE FROM models_fts")
        except sqlite3.OperationalError:
            conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('fts5_enabled', '0')")
    conn.commit()


def search_catalogue(db_path: Path | str, query: str, *, limit: int = 100) -> tuple[dict[str, Any], ...]:
    return search_catalogue_records(db_path, query, limit=limit)


def search_catalogue_records(
    db_path: Path | str,
    query: str,
    *,
    limit: int = 100,
    license_contains: str = "",
    creator_contains: str = "",
    creator_excludes: Sequence[str] | str = (),
    required_format: str = "",
) -> tuple[dict[str, Any], ...]:
    path = Path(db_path)
    if not path.is_file():
        return ()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        normalized_query = str(query or "").strip()
        safe_limit = max(1, min(int(limit), 5000))
        base_columns = (
            "uid, name, description, viewer_url, creator_name, creator_username, "
            "license_label, license_slug, is_downloadable, is_age_restricted, "
            "face_count, vertex_count, like_count, view_count, published_at, created_at, "
            "categories, tags, archives_json, mirror_url, metadata_url, thumbnail_url, "
            "gltf_url, glb_url, source_url, extra_url"
        )
        format_filter = str(required_format or "").strip().lower()
        filter_sql: list[str] = []
        filter_params: list[object] = []
        license_filter = str(license_contains or "").strip()
        if license_filter:
            filter_sql.append("license_label LIKE ?")
            filter_params.append(f"%{license_filter}%")
        creator_filter = str(creator_contains or "").strip()
        if creator_filter:
            filter_sql.append("(creator_name LIKE ? OR creator_username LIKE ?)")
            filter_params.extend([f"%{creator_filter}%", f"%{creator_filter}%"])
        for creator_exclude in _split_filter_terms(creator_excludes):
            filter_sql.append("(creator_name NOT LIKE ? AND creator_username NOT LIKE ?)")
            filter_params.extend([f"%{creator_exclude}%", f"%{creator_exclude}%"])
        if format_filter in {"gltf", "glb", "source", "extra"}:
            filter_sql.append(f"{format_filter}_url != ''")
        filters = f" AND {' AND '.join(filter_sql)}" if filter_sql else ""
        search_like = f"%{normalized_query}%"
        search_prefix = f"{normalized_query}%"
        fts_score_expression = (
            "CASE WHEN lower(name) = lower(?) THEN 500 ELSE 0 END + "
            "CASE WHEN lower(name) LIKE lower(?) THEN 260 ELSE 0 END + "
            "CASE WHEN lower(name) LIKE lower(?) THEN 180 ELSE 0 END + "
            "CASE WHEN lower(tags) LIKE lower(?) THEN 70 ELSE 0 END + "
            "CASE WHEN lower(description) LIKE lower(?) THEN 30 ELSE 0 END + "
            "CASE WHEN lower(creator_name) LIKE lower(?) OR lower(creator_username) LIKE lower(?) THEN 5 ELSE 0 END + "
            "CASE WHEN lower(uid) LIKE lower(?) THEN 1 ELSE 0 END"
        )
        fts_score_params: list[object] = [
            normalized_query,
            search_prefix,
            search_like,
            search_like,
            search_like,
            search_like,
            search_like,
            search_like,
        ]

        if normalized_query and _catalogue_fts_enabled(conn) and not filter_sql:
            fts_query = _fts_query(normalized_query)
            if fts_query:
                try:
                    rows = conn.execute(
                        f"""
                        SELECT {base_columns}, ({fts_score_expression}) AS search_score
                        FROM models
                        WHERE uid IN (SELECT uid FROM models_fts WHERE models_fts MATCH ?)
                        ORDER BY search_score DESC, COALESCE(view_count, 0) DESC, COALESCE(like_count, 0) DESC
                        LIMIT ?
                        """,
                        (*fts_score_params, fts_query, safe_limit),
                    ).fetchall()
                    if rows:
                        return tuple(_row_to_record(row) for row in rows)
                except sqlite3.OperationalError:
                    pass
        if normalized_query:
            like = f"%{normalized_query}%"
            tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9_]+", normalized_query)[:8]]
            score_sql = [
                "CASE WHEN lower(name) LIKE lower(?) THEN 120 ELSE 0 END",
                "CASE WHEN lower(tags) LIKE lower(?) THEN 70 ELSE 0 END",
                "CASE WHEN lower(description) LIKE lower(?) THEN 40 ELSE 0 END",
                "CASE WHEN lower(creator_name) LIKE lower(?) OR lower(creator_username) LIKE lower(?) THEN 5 ELSE 0 END",
                "CASE WHEN lower(uid) LIKE lower(?) THEN 20 ELSE 0 END",
            ]
            score_params: list[object] = [like, like, like, like, like, like]
            where_sql = [
                "name LIKE ?",
                "tags LIKE ?",
                "categories LIKE ?",
                "creator_name LIKE ?",
                "creator_username LIKE ?",
                "description LIKE ?",
                "uid LIKE ?",
            ]
            where_params: list[object] = [like, like, like, like, like, like, like]
            for token in tokens:
                token_like = f"%{token}%"
                score_sql.extend(
                    [
                        "CASE WHEN lower(name) LIKE ? THEN 18 ELSE 0 END",
                        "CASE WHEN lower(tags) LIKE ? THEN 10 ELSE 0 END",
                        "CASE WHEN lower(description) LIKE ? THEN 5 ELSE 0 END",
                        "CASE WHEN lower(categories) LIKE ? THEN 4 ELSE 0 END",
                        "CASE WHEN lower(creator_name) LIKE ? OR lower(creator_username) LIKE ? THEN 3 ELSE 0 END",
                    ]
                )
                score_params.extend([token_like, token_like, token_like, token_like, token_like, token_like])
                where_sql.extend(
                    [
                        "lower(name) LIKE ?",
                        "lower(tags) LIKE ?",
                        "lower(categories) LIKE ?",
                        "lower(creator_name) LIKE ?",
                        "lower(creator_username) LIKE ?",
                        "lower(description) LIKE ?",
                    ]
                )
                where_params.extend([token_like, token_like, token_like, token_like, token_like, token_like])
            score_expression = " + ".join(score_sql)
            where_expression = " OR ".join(where_sql)
            rows = conn.execute(
                f"""
                SELECT {base_columns}, ({score_expression}) AS search_score
                FROM models
                WHERE ({where_expression})
                    {filters}
                ORDER BY search_score DESC, COALESCE(view_count, 0) DESC, COALESCE(like_count, 0) DESC
                LIMIT ?
                """,
                (*score_params, *where_params, *filter_params, safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT {base_columns}
                FROM models
                WHERE 1 = 1
                    {filters}
                ORDER BY COALESCE(view_count, 0) DESC, COALESCE(like_count, 0) DESC
                LIMIT ?
                """,
                (*filter_params, safe_limit),
            ).fetchall()
        return tuple(_row_to_record(row) for row in rows)
    finally:
        conn.close()


def catalogue_stats(db_path: Path | str) -> dict[str, int]:
    path = Path(db_path)
    if not path.is_file():
        return {"models": 0, "shards": 0}
    try:
        conn = sqlite3.connect(path)
    except (OSError, sqlite3.Error):
        return {"models": 0, "shards": 0}
    try:
        models = int(conn.execute("SELECT COUNT(*) FROM models").fetchone()[0])
        shards = int(conn.execute("SELECT COUNT(*) FROM shards").fetchone()[0])
        return {"models": models, "shards": shards}
    except (OSError, sqlite3.Error):
        return {"models": 0, "shards": 0}
    finally:
        conn.close()


def build_mirror_catalogue_index(
    *,
    mirror_url: str,
    output_dir: Path | str,
    db_name: str = "mirror_catalogue.sqlite",
    max_shards: int = 0,
    refresh_shards: bool = False,
    index_query: str = "",
    license_contains: str = "",
    creator_contains: str = "",
    creator_excludes: Sequence[str] | str = (),
    required_format: str = "",
    clear_existing: bool = False,
    timeout: float = 60.0,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, Any]:
    base_url = normalize_mirror_base_url(mirror_url)
    root = Path(output_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    shards_dir = root / "catalogue_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir = root / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    readme_url = urljoin(base_url, "+README/")
    catalogue_url = urljoin(base_url, "+catalogue/")
    if on_progress:
        on_progress(0, 1, "Reading mirror catalogue listing...")
    readme_html = _fetch_text(readme_url, timeout=timeout)
    (root / "README.mirror.html").write_text(readme_html, encoding="utf-8")
    listing_html = _fetch_text(catalogue_url, timeout=timeout)
    (root / "catalogue_index.html").write_text(listing_html, encoding="utf-8")
    all_links = parse_catalogue_links(listing_html)
    links = all_links[:max_shards] if max_shards and max_shards > 0 else all_links

    conn = initialize_catalogue_db(root / db_name)
    total = max(len(links), 1)
    indexed_models = 0
    indexed_shards = 0
    seen_models = 0
    scoped_query = str(index_query or "").strip()
    scoped_filters = {
        "license_contains": str(license_contains or "").strip(),
        "creator_contains": str(creator_contains or "").strip(),
        "creator_excludes": tuple(_split_filter_terms(creator_excludes)),
        "required_format": str(required_format or "").strip().lower(),
    }
    scoped_index = bool(scoped_query or any(scoped_filters.values()))
    try:
        if clear_existing:
            clear_catalogue_records(conn)
        conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('mirror_url', ?)", (base_url,))
        conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('catalogue_shards_total', ?)", (str(len(all_links)),))
        conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('index_query', ?)", (scoped_query,))
        conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('index_scoped', ?)", ("1" if scoped_index else "0",))
        conn.commit()
        for index, href in enumerate(links, start=1):
            if stop_event is not None and stop_event.is_set():
                break
            shard_name = safe_catalogue_link_name(href)
            shard_url = urljoin(catalogue_url, href)
            shard_path = shards_dir / shard_name
            if shard_path.is_file() and not refresh_shards:
                raw_text = shard_path.read_text(encoding="utf-8")
            else:
                raw_text = _fetch_text(shard_url, timeout=timeout)
                shard_path.write_text(raw_text, encoding="utf-8")
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                continue
            raw_results = payload.get("results") if isinstance(payload, Mapping) else None
            if not isinstance(raw_results, list):
                records: list[dict[str, Any]] = []
            else:
                records = [
                    normalize_mirror_model_record(raw, base_url)
                    for raw in raw_results
                    if isinstance(raw, Mapping)
                ]
            seen_models += len(records)
            if scoped_index:
                records = [
                    record
                    for record in records
                    if _record_matches_index_scope(
                        record,
                        scoped_query,
                        license_contains=scoped_filters["license_contains"],
                        creator_contains=scoped_filters["creator_contains"],
                        creator_excludes=scoped_filters["creator_excludes"],
                        required_format=scoped_filters["required_format"],
                    )
                ]
            upsert_catalogue_records(conn, records, shard_name=shard_name, shard_url=shard_url)
            indexed_shards += 1
            indexed_models += len(records)
            if on_progress and (index == 1 or index % 25 == 0 or index == len(links)):
                if scoped_index:
                    on_progress(
                        index,
                        total,
                        f"Indexed {index:,} / {len(links):,} catalogue pages, {indexed_models:,} matching model records from {seen_models:,} seen.",
                    )
                else:
                    on_progress(index, total, f"Indexed {index:,} / {len(links):,} catalogue pages, {indexed_models:,} model records.")
    finally:
        conn.close()

    stats = catalogue_stats(root / db_name)
    manifest = {
        "mirror_url": base_url,
        "catalogue_url": catalogue_url,
        "total_catalogue_pages": len(all_links),
        "indexed_catalogue_pages": indexed_shards,
        "indexed_model_records_this_run": indexed_models,
        "seen_model_records_this_run": seen_models,
        "index_query": scoped_query,
        "index_scoped": scoped_index,
        "database": str(root / db_name),
        "downloads_dir": str(downloads_dir),
        "models_in_database": stats["models"],
        "shards_in_database": stats["shards"],
        "model_archives_downloaded": False,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _record_matches_index_scope(
    record: Mapping[str, Any],
    query: str,
    *,
    license_contains: str = "",
    creator_contains: str = "",
    creator_excludes: Sequence[str] | str = (),
    required_format: str = "",
) -> bool:
    format_filter = str(required_format or "").strip().lower()
    if format_filter in {"gltf", "glb", "source", "extra"} and not str(record.get(f"{format_filter}_url", "") or "").strip():
        return False
    license_filter = str(license_contains or "").strip().casefold()
    if license_filter and license_filter not in str(record.get("license_label", "") or "").casefold():
        return False
    creator_text = " ".join(
        (
            str(record.get("creator_name", "") or ""),
            str(record.get("creator_username", "") or ""),
        )
    ).casefold()
    creator_filter = str(creator_contains or "").strip().casefold()
    if creator_filter and creator_filter not in creator_text:
        return False
    for creator_exclude in _split_filter_terms(creator_excludes):
        if creator_exclude.casefold() in creator_text:
            return False
    normalized_query = str(query or "").strip().casefold()
    if not normalized_query:
        return True
    searchable_parts = [
        str(record.get("uid", "") or ""),
        str(record.get("name", "") or ""),
        str(record.get("description", "") or ""),
        str(record.get("creator_name", "") or ""),
        str(record.get("creator_username", "") or ""),
        _join_values(record.get("tags")),
        _join_values(record.get("categories")),
    ]
    searchable = " ".join(searchable_parts).casefold()
    if normalized_query in searchable:
        return True
    tokens = [token.casefold() for token in re.findall(r"[A-Za-z0-9_]+", normalized_query)[:8]]
    return bool(tokens and any(token in searchable for token in tokens))


def _fetch_text(url: str, *, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": "CrimsonDesertModWorkbench/ModelCatalogue"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    return data.decode("utf-8", errors="replace")


def _download_url_to_file(
    url: str,
    output_path: Path,
    *,
    timeout: float,
    stop_event: Optional[threading.Event] = None,
    max_bytes: int = MODEL_DOWNLOAD_MAX_BYTES,
    min_free_bytes: int = MODEL_DOWNLOAD_MIN_FREE_BYTES,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "CrimsonDesertModWorkbench/ModelCatalogue"})
    deadline = time.monotonic() + max(0.001, float(timeout))
    temp_path: Optional[Path] = None
    try:
        with urlopen(request, timeout=timeout) as response:
            try:
                content_length = int(response.headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                content_length = 0
            if content_length > max(1, int(max_bytes)):
                raise ValueError("Model download exceeds the size limit.")
            free_bytes = shutil.disk_usage(output_path.parent).free
            if content_length and content_length + max(0, int(min_free_bytes)) > free_bytes:
                raise ValueError("Model download needs more free disk space than is available.")
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                dir=output_path.parent,
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                copied = 0
                while True:
                    raise_if_cancelled(stop_event, "Model download cancelled.")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Model download exceeded the total time limit.")
                    chunk = response.read(1024 * 1024)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Model download exceeded the total time limit.")
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > max(1, int(max_bytes)):
                        raise ValueError("Model download exceeds the size limit.")
                    if len(chunk) + max(0, int(min_free_bytes)) > shutil.disk_usage(output_path.parent).free:
                        raise ValueError("Model download needs more free disk space than is available.")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        if temp_path is None:
            raise RuntimeError("Model download did not create a temporary output file.")
        temp_path.replace(output_path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    archives_json = str(row["archives_json"] or "{}")
    try:
        archives = json.loads(archives_json)
    except json.JSONDecodeError:
        archives = {}
    return {
        "kind": "mirror",
        "uid": row["uid"],
        "name": row["name"],
        "description": row["description"],
        "viewer_url": row["viewer_url"],
        "creator_name": row["creator_name"],
        "creator_username": row["creator_username"],
        "license_label": row["license_label"],
        "license_slug": row["license_slug"],
        "is_downloadable": bool(row["is_downloadable"]),
        "is_age_restricted": bool(row["is_age_restricted"]),
        "face_count": row["face_count"],
        "vertex_count": row["vertex_count"],
        "like_count": row["like_count"],
        "view_count": row["view_count"],
        "published_at": row["published_at"],
        "created_at": row["created_at"],
        "categories": _split_values(row["categories"]),
        "tags": _split_values(row["tags"]),
        "archives": archives if isinstance(archives, Mapping) else {},
        "mirror_url": row["mirror_url"],
        "metadata_url": row["metadata_url"],
        "thumbnail_url": row["thumbnail_url"],
        "gltf_url": row["gltf_url"],
        "glb_url": row["glb_url"],
        "source_url": row["source_url"],
        "extra_url": row["extra_url"],
        "source": "Mirror catalogue",
    }


def _catalogue_fts_enabled(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT value FROM metadata WHERE key = 'fts5_enabled'").fetchone()
    except sqlite3.OperationalError:
        return False
    return bool(row and str(row[0]) == "1")


def _fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    return " ".join(f"{token}*" for token in tokens[:8])


def _join_values(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Iterable):
        return ", ".join(str(item) for item in value if str(item).strip())
    return ""


def _split_values(value: object) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


def _split_filter_terms(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts: list[str] = []
        for item in value:
            parts.extend(_split_filter_terms(item))
        return tuple(parts)
    return tuple(part.strip() for part in re.split(r"[,;\r\n]+", str(value or "")) if part.strip())


def _slugify(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-_")
    return slug or fallback
