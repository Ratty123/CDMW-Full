"""Immutable model-library records and pure catalogue policy."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import unquote, urljoin, urlparse, urlunparse


DEFAULT_MODEL_MIRROR_URL = "https://mirror.traines.eu/sketchfab-backup/"
IMPORTABLE_MODEL_EXTENSIONS = {".obj", ".dae", ".gltf", ".glb", ".pac", ".pam", ".pamlod"}
ZIP_IMPORTABLE_MODEL_EXTENSIONS = set(IMPORTABLE_MODEL_EXTENSIONS)
ZIP_NESTED_IMPORTABLE_ARCHIVE_EXTENSIONS = {".zip"}
ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES = 128 * 1024 * 1024
ZIP_EXTRACT_MAX_MEMBERS = 8192
ZIP_EXTRACT_MAX_MEMBER_BYTES = 2 * 1024 * 1024 * 1024
ZIP_EXTRACT_MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
ZIP_EXTRACT_MAX_COMPRESSION_RATIO = 200.0
MODEL_DOWNLOAD_MAX_BYTES = 2 * 1024 * 1024 * 1024
MODEL_DOWNLOAD_MIN_FREE_BYTES = 64 * 1024 * 1024
BROWSABLE_MODEL_EXTENSIONS = IMPORTABLE_MODEL_EXTENSIONS | {
    ".3ds", ".abc", ".blend", ".fbx", ".lwo", ".ply", ".stl", ".usd", ".usda", ".usdc", ".usdz", ".x", ".zip"
}
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
    importable_members: tuple[str, ...] = ()


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
    path = re.sub(r"/+(?:\+catalogue|\+README)/?$", "/", parsed.path or "/")
    if not path.endswith("/"):
        path = f"{path}/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc, path, "", "", ""))


def parse_catalogue_links(index_html: str) -> tuple[str, ...]:
    parser = _CatalogueLinkParser()
    parser.feed(index_html or "")
    links: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        if not href.rsplit("/", 1)[-1].lower().endswith(".json"):
            continue
        normalized = href.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
    return tuple(sorted(links, key=lambda value: unquote(value).lower()))


def safe_catalogue_link_name(href: str) -> str:
    name = unquote(str(href or "").rsplit("/", 1)[-1]).strip() or "catalogue.json"
    name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    return name if name.lower().endswith(".json") else f"{name}.json"


def is_importable_model_path(path: Path | str) -> bool:
    return Path(path).suffix.lower() in IMPORTABLE_MODEL_EXTENSIONS


def normalize_mirror_model_record(payload: Mapping[str, Any], mirror_url: str) -> dict[str, Any]:
    base_url = normalize_mirror_base_url(mirror_url)
    uid = str(payload.get("uid", "") or payload.get("id", "") or "").strip()
    user = payload.get("user") if isinstance(payload.get("user"), Mapping) else {}
    license_payload = payload.get("license") if isinstance(payload.get("license"), Mapping) else {}
    archives = payload.get("archives") if isinstance(payload.get("archives"), Mapping) else {}
    prefix = uid[:2] if len(uid) >= 2 else "__"
    model_base = urljoin(base_url, f"{prefix}/{uid}") if uid else ""
    return {
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
        "categories": _extract_named_values(payload.get("categories")),
        "tags": _extract_named_values(payload.get("tags")),
        "archives": dict(archives),
        "mirror_url": base_url,
        "metadata_url": f"{model_base}.json" if uid else "",
        "thumbnail_url": f"{model_base}.jpeg" if uid else "",
        "gltf_url": f"{model_base}.zip" if uid and ("gltf" in archives or not archives) else "",
        "glb_url": f"{model_base}.glb" if uid and ("glb" in archives or not archives) else "",
        "source_url": f"{model_base}.source.zip" if uid and "source" in archives else "",
        "extra_url": f"{model_base}.extra.zip" if uid and "extra" in archives else "",
    }


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
    candidates: list[MirrorDownloadCandidate] = []

    def add(format_key: str, label: str, url_value: str, filename: str, import_supported: bool) -> None:
        if url_value and not any(existing.url == url_value for existing in candidates):
            candidates.append(MirrorDownloadCandidate(format_key, label, url_value, filename, import_supported))

    if "gltf" in archives or not archives or record.get("gltf_url"):
        add("gltf", "glTF ZIP", str(record.get("gltf_url") or f"{stem_url}.zip"), f"{uid}.zip", True)
    if "glb" in archives or not archives or record.get("glb_url"):
        add("glb", "GLB", str(record.get("glb_url") or f"{stem_url}.glb"), f"{uid}.glb", True)
    if "source" in archives or record.get("source_url"):
        add("source", "Original source ZIP", str(record.get("source_url") or f"{stem_url}.source.zip"), f"{uid}.source.zip", True)
    if "extra" in archives or record.get("extra_url"):
        add("extra", "Extra archive", str(record.get("extra_url") or f"{stem_url}.extra.zip"), f"{uid}.extra.zip", False)
    preferred = str(preferred_format or "gltf").strip().lower()
    return tuple(sorted(candidates, key=lambda item: (item.format != preferred, not item.import_supported, item.format)))


def _extract_named_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    result: list[str] = []
    for item in value:
        text = (
            str(item.get("name", "") or item.get("slug", "") or item.get("label", "") or "")
            if isinstance(item, Mapping)
            else str(item or "")
        )
        if text.strip():
            result.append(text.strip())
    return tuple(result)


def _optional_int(value: object) -> Optional[int]:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "BROWSABLE_MODEL_EXTENSIONS",
    "DEFAULT_MODEL_MIRROR_URL",
    "IMPORTABLE_MODEL_EXTENSIONS",
    "LOCAL_MODEL_TEXTURE_EXTENSIONS",
    "MODEL_DOWNLOAD_MAX_BYTES",
    "MODEL_DOWNLOAD_MIN_FREE_BYTES",
    "MirrorDownloadCandidate",
    "MirrorDownloadResult",
    "LocalModelFile",
    "ZIP_EXTRACT_MAX_COMPRESSION_RATIO",
    "ZIP_EXTRACT_MAX_MEMBER_BYTES",
    "ZIP_EXTRACT_MAX_MEMBERS",
    "ZIP_EXTRACT_MAX_TOTAL_BYTES",
    "ZIP_IMPORTABLE_MODEL_EXTENSIONS",
    "ZIP_NESTED_IMPORTABLE_ARCHIVE_EXTENSIONS",
    "ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES",
    "is_importable_model_path",
    "mirror_download_candidates",
    "normalize_mirror_base_url",
    "normalize_mirror_model_record",
    "parse_catalogue_links",
    "safe_catalogue_link_name",
]
