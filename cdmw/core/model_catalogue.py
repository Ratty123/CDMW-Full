from __future__ import annotations

import io
import json
import re
import shutil
import sqlite3
import threading
import time
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from urllib.parse import unquote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_MODEL_MIRROR_URL = "https://mirror.traines.eu/sketchfab-backup/"

IMPORTABLE_MODEL_EXTENSIONS = {
    ".obj",
    ".dae",
    ".gltf",
    ".glb",
    ".pac",
    ".pam",
    ".pamlod",
}

ZIP_IMPORTABLE_MODEL_EXTENSIONS = set(IMPORTABLE_MODEL_EXTENSIONS)
ZIP_NESTED_IMPORTABLE_ARCHIVE_EXTENSIONS = {".zip"}
ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES = 128 * 1024 * 1024

BROWSABLE_MODEL_EXTENSIONS = IMPORTABLE_MODEL_EXTENSIONS | {
    ".3ds",
    ".abc",
    ".blend",
    ".fbx",
    ".lwo",
    ".ply",
    ".stl",
    ".usd",
    ".usda",
    ".usdc",
    ".usdz",
    ".x",
    ".zip",
}

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
LOCAL_MODEL_TEXTURE_EXTENSIONS = {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass(frozen=True)
class LocalModelFile:
    path: Path
    root: Path
    name: str
    extension: str
    size: int
    modified_at: float
    import_supported: bool
    texture_status: str = ""

    @property
    def relative_path(self) -> str:
        try:
            return str(self.path.relative_to(self.root))
        except ValueError:
            return str(self.path)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "local",
            "name": self.name,
            "path": str(self.path),
            "root": str(self.root),
            "relative_path": self.relative_path,
            "extension": self.extension,
            "size": self.size,
            "modified_at": self.modified_at,
            "import_supported": self.import_supported,
            "source": "Local model library",
            "texture_status": self.texture_status,
        }


@dataclass(frozen=True)
class MirrorDownloadCandidate:
    format: str
    label: str
    url: str
    filename: str
    import_supported: bool


@dataclass(frozen=True)
class MirrorDownloadResult:
    record: Mapping[str, Any]
    candidate: MirrorDownloadCandidate
    archive_path: Path
    asset_dir: Path
    import_path: Optional[Path]


class _CatalogueLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)
                return


def normalize_mirror_base_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("Enter a model mirror URL first.")
    parsed = urlparse(raw)
    if not parsed.scheme:
        parsed = urlparse(f"https://{raw}")
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Mirror URL must be an HTTP or HTTPS URL.")
    path = parsed.path or "/"
    path = re.sub(r"/+(?:\+catalogue|\+README)/?$", "/", path)
    if not path.endswith("/"):
        path = f"{path}/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc, path, "", "", ""))


def parse_catalogue_links(index_html: str) -> tuple[str, ...]:
    parser = _CatalogueLinkParser()
    parser.feed(index_html or "")
    links: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        name = href.rsplit("/", 1)[-1]
        if not name.lower().endswith(".json"):
            continue
        normalized = href.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
    return tuple(sorted(links, key=lambda value: unquote(value).lower()))


def safe_catalogue_link_name(href: str) -> str:
    name = unquote(str(href or "").rsplit("/", 1)[-1]).strip()
    if not name:
        name = "catalogue.json"
    name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    if not name.lower().endswith(".json"):
        name = f"{name}.json"
    return name


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


def is_importable_model_path(path: Path | str) -> bool:
    return Path(path).suffix.lower() in IMPORTABLE_MODEL_EXTENSIONS


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


def zip_importable_members(archive_path: Path | str) -> tuple[str, ...]:
    archive = Path(archive_path)
    if archive.suffix.lower() != ".zip" or not archive.is_file():
        return ()
    priority = {".gltf": 0, ".glb": 1, ".obj": 2, ".dae": 3}
    members: list[str] = []
    try:
        with zipfile.ZipFile(archive, "r") as zip_file:
            for member in zip_file.infolist():
                member_name = member.filename.replace("\\", "/")
                if member.is_dir() or not member_name or member_name.startswith("/") or "../" in f"/{member_name}":
                    continue
                suffix = Path(member_name).suffix.lower()
                if suffix in ZIP_IMPORTABLE_MODEL_EXTENSIONS:
                    members.append(member.filename)
    except (OSError, zipfile.BadZipFile):
        return ()
    return tuple(sorted(members, key=lambda value: (priority.get(Path(value).suffix.lower(), 99), value.lower())))


def zip_importable_member_refs(archive_path: Path | str) -> tuple[str, ...]:
    """Return direct and one-level nested ZIP importable member references."""
    archive = Path(archive_path)
    direct_members = list(zip_importable_members(archive))
    if archive.suffix.lower() != ".zip" or not archive.is_file():
        return tuple(direct_members)
    members = list(direct_members)
    seen = {member.replace("\\", "/").lower() for member in members}
    try:
        with zipfile.ZipFile(archive, "r") as zip_file:
            for member in zip_file.infolist():
                member_name = _safe_zip_member_name(member.filename)
                if not member_name:
                    continue
                if Path(member_name).suffix.lower() not in ZIP_NESTED_IMPORTABLE_ARCHIVE_EXTENSIONS:
                    continue
                if int(getattr(member, "file_size", 0) or 0) > ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES:
                    continue
                for nested_member in _nested_zip_importable_members(zip_file, member):
                    ref = f"{member_name}::{nested_member}"
                    key = ref.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    members.append(ref)
    except (OSError, zipfile.BadZipFile):
        return tuple(direct_members)
    return tuple(sorted(members, key=_zip_importable_member_ref_sort_key))


def _nested_zip_importable_members(parent_archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> tuple[str, ...]:
    try:
        with parent_archive.open(member, "r") as stream:
            payload = stream.read(ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES + 1)
    except (OSError, zipfile.BadZipFile):
        return ()
    if len(payload) > ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES:
        return ()
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as nested_archive:
            nested_members = []
            for nested_member in nested_archive.infolist():
                nested_name = _safe_zip_member_name(nested_member.filename)
                if not nested_name:
                    continue
                if Path(nested_name).suffix.lower() in ZIP_IMPORTABLE_MODEL_EXTENSIONS:
                    nested_members.append(nested_name)
    except (OSError, zipfile.BadZipFile):
        return ()
    return tuple(sorted(nested_members, key=lambda value: (Path(value).suffix.lower(), value.lower())))


def _zip_importable_member_ref_sort_key(value: str) -> tuple[int, int, str, str]:
    priority = {".gltf": 0, ".glb": 1, ".obj": 2, ".dae": 3, ".pac": 4, ".pam": 5, ".pamlod": 6}
    outer, nested = _split_nested_zip_member_ref(value)
    suffix = Path(nested or outer).suffix.lower()
    return (priority.get(suffix, 99), 1 if nested else 0, outer.lower(), nested.lower())


def _safe_zip_member_name(value: str) -> str:
    member_name = str(value or "").replace("\\", "/")
    if not member_name or member_name.startswith("/") or "../" in f"/{member_name}":
        return ""
    return member_name


def _split_nested_zip_member_ref(value: str) -> tuple[str, str]:
    text = str(value or "").replace("\\", "/")
    if "::" not in text:
        return text, ""
    outer, nested = text.split("::", 1)
    return outer, nested


def zip_contains_importable_model(archive_path: Path | str) -> bool:
    return bool(zip_importable_member_refs(archive_path))


def resolve_importable_model_path(path: Path | str, *, extract_root: Optional[Path | str] = None) -> Optional[Path]:
    source_path = Path(path).expanduser()
    if source_path.is_file() and is_importable_model_path(source_path):
        return source_path
    if source_path.suffix.lower() != ".zip" or not source_path.is_file():
        return None
    members = zip_importable_member_refs(source_path)
    if not members:
        return None
    destination = Path(extract_root).expanduser() if extract_root is not None else source_path.parent / ".cdmw_extracted" / source_path.stem
    safe_extract_zip(source_path, destination)
    for member in members:
        outer_member, nested_member = _split_nested_zip_member_ref(member)
        if nested_member:
            nested_archive = destination.joinpath(*PurePosixPath(outer_member).parts)
            if not nested_archive.is_file():
                continue
            nested_destination = destination / ".cdmw_nested_zip" / _nested_zip_extract_dir_name(outer_member)
            safe_extract_zip(nested_archive, nested_destination)
            candidate = nested_destination.joinpath(*PurePosixPath(nested_member).parts)
        else:
            candidate = destination.joinpath(*PurePosixPath(outer_member).parts)
        if candidate.is_file() and is_importable_model_path(candidate):
            return candidate
    for candidate in sorted(destination.rglob("*")):
        if candidate.is_file() and is_importable_model_path(candidate):
            return candidate
    return None


def _nested_zip_extract_dir_name(member_name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(member_name or "").replace("\\", "/")).strip("._")
    return clean[:96] or "nested_zip"


def normalize_mirror_model_record(payload: Mapping[str, Any], mirror_url: str) -> dict[str, Any]:
    base_url = normalize_mirror_base_url(mirror_url)
    uid = str(payload.get("uid", "") or payload.get("id", "") or "").strip()
    user = payload.get("user") if isinstance(payload.get("user"), Mapping) else {}
    license_payload = payload.get("license") if isinstance(payload.get("license"), Mapping) else {}
    archives = payload.get("archives") if isinstance(payload.get("archives"), Mapping) else {}
    categories = _extract_named_values(payload.get("categories"))
    tags = _extract_named_values(payload.get("tags"))
    prefix = uid[:2] if len(uid) >= 2 else "__"
    model_base = urljoin(base_url, f"{prefix}/{uid}") if uid else ""
    record = {
        "kind": "mirror",
        "uid": uid,
        "name": str(payload.get("name", "") or uid or "Untitled model").strip(),
        "description": str(payload.get("description", "") or "").strip(),
        "viewer_url": str(payload.get("viewerUrl", "") or payload.get("viewer_url", "") or "").strip(),
        "creator_name": str(user.get("displayName", "") or user.get("display_name", "") or "").strip(),
        "creator_username": str(user.get("username", "") or "").strip(),
        "license_label": str(license_payload.get("label", "") or license_payload.get("name", "") or "").strip(),
        "license_slug": str(license_payload.get("slug", "") or license_payload.get("uid", "") or "").strip(),
        "is_downloadable": bool(payload.get("isDownloadable", payload.get("is_downloadable", True))),
        "is_age_restricted": bool(payload.get("isAgeRestricted", payload.get("is_age_restricted", False))),
        "face_count": _optional_int(payload.get("faceCount", payload.get("face_count"))),
        "vertex_count": _optional_int(payload.get("vertexCount", payload.get("vertex_count"))),
        "like_count": _optional_int(payload.get("likeCount", payload.get("like_count"))),
        "view_count": _optional_int(payload.get("viewCount", payload.get("view_count"))),
        "published_at": str(payload.get("publishedAt", payload.get("published_at", "")) or ""),
        "created_at": str(payload.get("createdAt", payload.get("created_at", "")) or ""),
        "categories": categories,
        "tags": tags,
        "archives": dict(archives),
        "mirror_url": base_url,
        "metadata_url": f"{model_base}.json" if uid else "",
        "thumbnail_url": f"{model_base}.jpeg" if uid else "",
        "gltf_url": f"{model_base}.zip" if uid and ("gltf" in archives or not archives) else "",
        "glb_url": f"{model_base}.glb" if uid and ("glb" in archives or not archives) else "",
        "source_url": f"{model_base}.source.zip" if uid and "source" in archives else "",
        "extra_url": f"{model_base}.extra.zip" if uid and "extra" in archives else "",
    }
    return record


def mirror_download_candidates(
    record: Mapping[str, Any],
    mirror_url: str,
    *,
    preferred_format: str = "gltf",
) -> tuple[MirrorDownloadCandidate, ...]:
    uid = str(record.get("uid", "") or "").strip()
    if not uid:
        return ()
    base_url = normalize_mirror_base_url(str(record.get("mirror_url", "") or mirror_url))
    prefix = uid[:2] if len(uid) >= 2 else "__"
    stem_url = urljoin(base_url, f"{prefix}/{uid}")
    archives = record.get("archives") if isinstance(record.get("archives"), Mapping) else {}
    has_known_archives = bool(archives)

    candidates: list[MirrorDownloadCandidate] = []

    def add(format_key: str, label: str, url_value: str, filename: str, import_supported: bool) -> None:
        if not url_value or any(existing.url == url_value for existing in candidates):
            return
        candidates.append(MirrorDownloadCandidate(format_key, label, url_value, filename, import_supported))

    if "gltf" in archives or not has_known_archives or record.get("gltf_url"):
        add("gltf", "glTF ZIP", str(record.get("gltf_url") or f"{stem_url}.zip"), f"{uid}.zip", True)
    if "glb" in archives or not has_known_archives or record.get("glb_url"):
        add("glb", "GLB", str(record.get("glb_url") or f"{stem_url}.glb"), f"{uid}.glb", True)
    if "source" in archives or record.get("source_url"):
        add("source", "Original source ZIP", str(record.get("source_url") or f"{stem_url}.source.zip"), f"{uid}.source.zip", True)
    if "extra" in archives or record.get("extra_url"):
        add("extra", "Extra archive", str(record.get("extra_url") or f"{stem_url}.extra.zip"), f"{uid}.extra.zip", False)

    preferred = str(preferred_format or "gltf").strip().lower()
    candidates.sort(key=lambda item: (0 if item.format == preferred else 1, 0 if item.import_supported else 1, item.format))
    return tuple(candidates)


def download_mirror_model(
    record: Mapping[str, Any],
    *,
    mirror_url: str,
    output_root: Path | str,
    preferred_format: str = "gltf",
    require_importable: bool = False,
    timeout: float = 120.0,
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
    )
    if require_importable and result.import_path is None:
        raise ValueError("Downloaded archive does not contain an importable OBJ, DAE, glTF, GLB, or local mesh source.")
    return result


def download_mirror_model_candidate(
    record: Mapping[str, Any],
    candidate: MirrorDownloadCandidate,
    *,
    output_root: Path | str,
    timeout: float = 120.0,
) -> MirrorDownloadResult:
    uid = str(record.get("uid", "") or "").strip()
    name = str(record.get("name", "") or uid or "model").strip()
    asset_dir = Path(output_root).expanduser() / f"{_slugify(name, fallback='model')[:72]}-{uid}"
    asset_dir.mkdir(parents=True, exist_ok=True)
    archive_path = asset_dir / candidate.filename
    if not archive_path.is_file():
        _download_url_to_file(candidate.url, archive_path, timeout=timeout)
    metadata_path = asset_dir / "model_metadata.json"
    metadata_path.write_text(json.dumps(dict(record), ensure_ascii=False, indent=2), encoding="utf-8")
    import_path: Optional[Path] = None
    if candidate.format == "glb":
        import_path = archive_path
    elif candidate.format in {"gltf", "source"}:
        extract_name = "gltf" if candidate.format == "gltf" else "source"
        import_path = resolve_importable_model_path(archive_path, extract_root=asset_dir / extract_name)
    return MirrorDownloadResult(
        record=record,
        candidate=candidate,
        archive_path=archive_path,
        asset_dir=asset_dir,
        import_path=import_path,
    )


def safe_extract_zip(archive_path: Path | str, destination: Path | str) -> None:
    archive = Path(archive_path)
    target_root = Path(destination)
    target_root.mkdir(parents=True, exist_ok=True)
    resolved_root = target_root.resolve()
    with zipfile.ZipFile(archive, "r") as zip_file:
        for member in zip_file.infolist():
            member_name = member.filename.replace("\\", "/")
            if not member_name or member_name.startswith("/") or "../" in f"/{member_name}":
                raise ValueError(f"Unsafe path in model archive: {member.filename}")
            target_path = target_root / member_name
            resolved_target = target_path.resolve()
            if resolved_root != resolved_target and resolved_root not in resolved_target.parents:
                raise ValueError(f"Unsafe path in model archive: {member.filename}")
        zip_file.extractall(target_root)


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


def _download_url_to_file(url: str, output_path: Path, *, timeout: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    request = Request(url, headers={"User-Agent": "CrimsonDesertModWorkbench/ModelCatalogue"})
    with urlopen(request, timeout=timeout) as response, temp_path.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    temp_path.replace(output_path)


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


def _extract_named_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    names: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            name = str(item.get("name", "") or item.get("slug", "") or item.get("label", "") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            names.append(name)
    return tuple(names)


def _optional_int(value: object) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


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
