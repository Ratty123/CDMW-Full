"""Local-row normalization helpers for Model Library."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from cdmw.core.model_catalogue import zip_contains_importable_model


class ModelLibraryLocalRowsMixin:
    """Normalize downloaded mirror assets into one local-library row."""

    def _download_output_root(self) -> Path:
        return self.catalogue_dir() / "downloads"

    def _normalize_local_model_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        download_root = self._download_output_root()
        try:
            resolved_download_root = download_root.resolve()
        except OSError:
            resolved_download_root = download_root.absolute()

        grouped: dict[str, list[dict[str, object]]] = {}
        grouped_metadata: dict[str, dict[str, object]] = {}
        passthrough: list[dict[str, object]] = []

        for row in rows:
            metadata_path = self._metadata_path_for_local_row(row, resolved_download_root)
            if metadata_path is None:
                passthrough.append(row)
                continue
            asset_dir = metadata_path.parent
            key = str(asset_dir).casefold()
            grouped.setdefault(key, []).append(row)
            if key not in grouped_metadata:
                grouped_metadata[key] = self._read_download_metadata(metadata_path)

        normalized = list(passthrough)
        for key, group_rows in grouped.items():
            metadata = grouped_metadata.get(key) or {}
            metadata_path = self._metadata_path_from_group(group_rows, resolved_download_root)
            if metadata_path is None:
                normalized.extend(group_rows)
                continue
            display_root = self._display_root_for_metadata_group(metadata_path, group_rows, resolved_download_root)
            normalized.append(self._download_group_local_row(metadata_path.parent, metadata, group_rows, display_root))

        normalized.sort(key=lambda item: (str(item.get("name", "") or "").lower(), str(item.get("path", "") or "").lower()))
        return normalized

    def _metadata_path_for_local_row(self, row: dict[str, object], download_root: Path) -> Optional[Path]:
        path = Path(str(row.get("path", "") or ""))
        metadata_path = self._download_metadata_path_for_local_path(path, download_root)
        if metadata_path is not None:
            return metadata_path
        root_text = str(row.get("root", "") or "").strip()
        root = Path(root_text) if root_text else None
        return self._nearest_local_model_metadata_path(path, root)

    def _download_metadata_path_for_local_path(self, path: Path, download_root: Path) -> Optional[Path]:
        try:
            resolved_path = path.resolve()
        except OSError:
            resolved_path = path.absolute()
        if download_root != resolved_path and download_root not in resolved_path.parents:
            return None
        start = resolved_path.parent if resolved_path.is_file() else resolved_path
        for candidate_dir in (start, *start.parents):
            if candidate_dir == download_root.parent:
                break
            metadata_path = candidate_dir / "model_metadata.json"
            if metadata_path.is_file():
                return metadata_path
            if candidate_dir == download_root:
                break
        return None

    def _nearest_local_model_metadata_path(self, path: Path, root: Optional[Path]) -> Optional[Path]:
        try:
            resolved_path = path.resolve()
        except OSError:
            resolved_path = path.absolute()
        resolved_root: Optional[Path] = None
        if root is not None:
            try:
                resolved_root = root.resolve()
            except OSError:
                resolved_root = root.absolute()
            if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
                return None
        start = resolved_path.parent if resolved_path.is_file() else resolved_path
        for candidate_dir in (start, *start.parents):
            metadata_path = candidate_dir / "model_metadata.json"
            if metadata_path.is_file():
                return metadata_path
            if resolved_root is not None and candidate_dir == resolved_root:
                break
        return None

    def _read_download_metadata(self, metadata_path: Path) -> dict[str, object]:
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _metadata_path_from_group(self, group_rows: list[dict[str, object]], download_root: Path) -> Optional[Path]:
        for row in group_rows:
            metadata_path = self._metadata_path_for_local_row(row, download_root)
            if metadata_path is not None:
                return metadata_path
        return None

    def _display_root_for_metadata_group(self, metadata_path: Path, group_rows: list[dict[str, object]], download_root: Path) -> Path:
        try:
            resolved_metadata_path = metadata_path.resolve()
        except OSError:
            resolved_metadata_path = metadata_path.absolute()
        if download_root == resolved_metadata_path or download_root in resolved_metadata_path.parents:
            return download_root
        for row in group_rows:
            root_text = str(row.get("root", "") or "").strip()
            if not root_text:
                continue
            root = Path(root_text)
            try:
                resolved_root = root.resolve()
            except OSError:
                resolved_root = root.absolute()
            if resolved_root == resolved_metadata_path or resolved_root in resolved_metadata_path.parents:
                return resolved_root
        return metadata_path.parent

    def _download_group_local_row(
        self,
        asset_dir: Path,
        metadata: dict[str, object],
        group_rows: list[dict[str, object]],
        display_root: Path,
    ) -> dict[str, object]:
        import_path = self._find_importable_file_under(asset_dir)
        archive_path = self._preferred_download_archive_path(asset_dir, metadata, group_rows)
        display_path = import_path or archive_path or Path(str(group_rows[0].get("path", "") or asset_dir))
        try:
            relative_path = str(display_path.relative_to(display_root))
        except ValueError:
            relative_path = str(display_path)
        size = 0
        for candidate in (archive_path, display_path):
            if candidate is not None and candidate.is_file():
                try:
                    size = int(candidate.stat().st_size)
                    break
                except OSError:
                    pass
        modified_at = 0.0
        for row in group_rows:
            try:
                modified_at = max(modified_at, float(row.get("modified_at", 0.0) or 0.0))
            except (TypeError, ValueError):
                pass
        creator_payload = metadata.get("user") if isinstance(metadata.get("user"), dict) else {}
        creator_name = str(metadata.get("creator_name", "") or creator_payload.get("displayName", "") or creator_payload.get("username", "") or "")
        creator_username = str(metadata.get("creator_username", "") or creator_payload.get("username", "") or "")
        license_payload = metadata.get("license") if isinstance(metadata.get("license"), dict) else {}
        license_label = str(metadata.get("license_label", "") or license_payload.get("label", "") or "")
        import_supported = bool(import_path and import_path.is_file())
        if not import_supported and display_path.suffix.lower() == ".zip":
            import_supported = zip_contains_importable_model(display_path)
        row = {
            "kind": "local",
            "name": str(metadata.get("name", "") or display_path.stem),
            "path": str(display_path),
            "root": str(display_root),
            "relative_path": relative_path,
            "extension": display_path.suffix.lower(),
            "size": size,
            "modified_at": modified_at,
            "import_supported": import_supported,
            "source": "Downloaded",
            "asset_dir": str(asset_dir),
            "archive_path": str(archive_path) if archive_path is not None else "",
            "import_path": str(import_path) if import_path is not None else "",
            "uid": str(metadata.get("uid", "") or metadata.get("id", "") or ""),
            "viewer_url": str(metadata.get("viewer_url", "") or metadata.get("viewerUrl", "") or ""),
            "license_label": license_label,
            "creator_name": creator_name,
            "creator_username": creator_username,
        }
        row["texture_status"] = self._texture_status_for_payload(row)
        return row

    def _preferred_download_archive_path(
        self,
        asset_dir: Path,
        metadata: dict[str, object],
        group_rows: list[dict[str, object]],
    ) -> Optional[Path]:
        uid = str(metadata.get("uid", "") or metadata.get("id", "") or "")
        candidates: list[Path] = []
        if uid:
            candidates.extend([asset_dir / f"{uid}.zip", asset_dir / f"{uid}.glb", asset_dir / f"{uid}.source.zip"])
        for row in group_rows:
            path = Path(str(row.get("path", "") or ""))
            if path.is_file() and path.suffix.lower() in {".zip", ".glb"}:
                candidates.append(path)
        for candidate in candidates:
            if candidate.is_file() and not candidate.name.lower().endswith(".source.zip"):
                return candidate
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _ensure_download_root_registered(self, output_root: Path) -> None:
        output_root.mkdir(parents=True, exist_ok=True)
        try:
            normalized = str(output_root.resolve())
        except OSError:
            normalized = str(output_root.absolute())
        if normalized not in self.local_roots:
            self.local_roots.append(normalized)
            self._save_roots()
            self._refresh_roots_tree()
        if not self.local_path_edit.text().strip():
            self.local_path_edit.setText(normalized)


__all__ = ["ModelLibraryLocalRowsMixin"]
