"""Texture-status helpers for Model Library rows."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Optional

from cdmw.core.archive_modding import SCENE_TEXTURE_SOURCE_EXTENSIONS
from cdmw.core.model_catalogue import is_importable_model_path, zip_contains_importable_model


class ModelLibraryTextureStatusMixin:
    """Compute and refresh local texture status for result rows."""

    def _mirror_local_status(self, payload: dict[str, object]) -> str:
        import_path = Path(str(payload.get("import_path", "") or ""))
        if import_path.is_file() and is_importable_model_path(import_path):
            return "Ready"
        archive_path = Path(str(payload.get("archive_path", "") or ""))
        if archive_path.is_file():
            if archive_path.suffix.lower() == ".zip" and zip_contains_importable_model(archive_path):
                return "ZIP ready"
            return "Downloaded"
        return ""

    def _local_payload_status(self, payload: dict[str, object]) -> str:
        if self._payload_can_import(payload):
            path = Path(str(payload.get("path", "") or ""))
            if path.suffix.lower() == ".zip":
                return "ZIP ready"
            return "Ready"
        if Path(str(payload.get("path", "") or "")).suffix.lower() == ".zip":
            return "ZIP"
        return "Browse"

    def _texture_status_for_payload(self, payload: dict[str, object]) -> str:
        existing = str(payload.get("texture_status", "") or "").strip()
        if existing:
            return existing
        if payload.get("kind") == "mirror":
            self._apply_mirror_local_state(payload)
            asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
            asset_dir = Path(asset_dir_text) if asset_dir_text else None
            if asset_dir is not None and asset_dir.is_dir():
                count = self._count_texture_files(asset_dir, recursive=True)
                if count > 0:
                    return f"Found ({count})"
            archive_path_text = str(payload.get("archive_path", "") or "").strip()
            archive_path = Path(archive_path_text) if archive_path_text else None
            if archive_path is not None and archive_path.is_file():
                return self._texture_status_for_model_path(archive_path, payload)
            return "Download to check"
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        asset_dir = Path(asset_dir_text) if asset_dir_text else None
        if asset_dir is not None and asset_dir.is_dir():
            count = self._count_texture_files(asset_dir, recursive=True)
            if count > 0:
                return f"Found ({count})"
        archive_path_text = str(payload.get("archive_path", "") or "").strip()
        archive_path = Path(archive_path_text) if archive_path_text else None
        if archive_path is not None and archive_path.is_file():
            return self._texture_status_for_model_path(archive_path, payload)
        path_text = str(payload.get("path", "") or "").strip()
        path = Path(path_text) if path_text else None
        if path is not None and path.is_file():
            return self._texture_status_for_model_path(path, payload)
        return "Unknown"

    def _texture_status_for_model_path(self, path: Path, payload: Optional[dict[str, object]] = None) -> str:
        suffix = path.suffix.lower()
        if suffix == ".zip":
            count = self._count_zip_texture_members(path)
            return f"In ZIP ({count})" if count > 0 else "None found"
        if suffix == ".glb":
            return "Embedded/Unknown"
        import_path_text = str((payload or {}).get("import_path", "") or "").strip()
        import_path = Path(import_path_text) if import_path_text else path
        if import_path.is_file():
            if import_path.suffix.lower() == ".glb":
                return "Embedded/Unknown"
            count = self._nearby_texture_count(import_path)
            return f"Found ({count})" if count > 0 else "None found"
        return "Unknown"

    def _nearby_texture_count(self, scene_path: Path) -> int:
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
            total += self._count_texture_files(root, recursive=recursive)
        return total

    def _count_texture_files(self, root: Path, *, recursive: bool, limit: int = 999) -> int:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root.absolute()
        cache_key = (str(resolved).casefold(), "r" if recursive else "flat")
        cached = self._texture_status_cache.get(cache_key)
        if cached is not None:
            return cached
        count = 0
        iterator = resolved.rglob("*") if recursive else resolved.iterdir()
        try:
            for candidate in iterator:
                if candidate.is_file() and candidate.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                    count += 1
                    if count >= limit:
                        break
        except OSError:
            count = 0
        self._texture_status_cache[cache_key] = count
        return count

    def _count_zip_texture_members(self, archive_path: Path, limit: int = 999) -> int:
        try:
            resolved = archive_path.resolve()
        except OSError:
            resolved = archive_path.absolute()
        cache_key = (str(resolved).casefold(), "zip")
        cached = self._texture_status_cache.get(cache_key)
        if cached is not None:
            return cached
        count = 0
        try:
            with zipfile.ZipFile(resolved, "r") as zip_file:
                for member in zip_file.infolist():
                    member_name = member.filename.replace("\\", "/")
                    if member.is_dir() or not member_name or member_name.startswith("/") or "../" in f"/{member_name}":
                        continue
                    if Path(member_name).suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                        count += 1
                        if count >= limit:
                            break
        except (OSError, zipfile.BadZipFile):
            count = 0
        self._texture_status_cache[cache_key] = count
        return count

    def _refresh_result_row_status(self, payload: dict[str, object]) -> None:
        item = self._result_item_for_payload(payload)
        if item is None:
            return
        if payload.get("kind") == "mirror":
            self._apply_mirror_local_state(payload)
            item.setText(3, self._mirror_local_status(payload))
        else:
            item.setText(3, self._local_payload_status(payload))
        item.setText(4, self._texture_status_for_payload(payload))
        self._sync_no_texture_download_cache_for_item(item)

    def _refresh_result_row_statuses(self) -> None:
        for index in range(self.results_tree.topLevelItemCount()):
            item = self.results_tree.topLevelItem(index)
            payload = self._payload_from_item(item)
            if payload is None:
                continue
            if payload.get("kind") == "mirror":
                self._apply_mirror_local_state(payload)
                item.setText(3, self._mirror_local_status(payload))
                item.setText(4, self._texture_status_for_payload(payload))
            else:
                item.setText(3, self._local_payload_status(payload))
                item.setText(4, self._texture_status_for_payload(payload))
            self._sync_no_texture_download_cache_for_item(item)


__all__ = ["ModelLibraryTextureStatusMixin"]
