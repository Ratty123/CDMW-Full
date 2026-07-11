"""Model Library scan, catalogue, download, and extraction coordination."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from cdmw.domain.library.models import LocalModelFile, MirrorDownloadCandidate, MirrorDownloadResult


def _backend() -> object:
    from cdmw.core import model_catalogue

    return model_catalogue


@dataclass(slots=True)
class ModelLibraryService:
    settings: object | None = None

    def scan_local_models(
        self,
        roots: Iterable[Path | str],
        *,
        stop_event: Optional[threading.Event] = None,
    ) -> tuple[LocalModelFile, ...]:
        return _backend().scan_local_model_files(roots, stop_event=stop_event)

    def build_catalogue_index(
        self,
        *,
        mirror_url: str,
        output_dir: Path,
        max_shards: int,
        index_query: str = "",
        license_contains: str = "",
        creator_contains: str = "",
        creator_excludes: str = "",
        required_format: str = "",
        clear_existing: bool = False,
        stop_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict[str, object]:
        return _backend().build_mirror_catalogue_index(
            mirror_url=mirror_url,
            output_dir=output_dir,
            max_shards=max_shards,
            index_query=index_query,
            license_contains=license_contains,
            creator_contains=creator_contains,
            creator_excludes=creator_excludes,
            required_format=required_format,
            clear_existing=clear_existing,
            stop_event=stop_event,
            on_progress=on_progress,
        )

    def search_catalogue(
        self,
        db_path: Path,
        query: str,
        **filters: object,
    ) -> tuple[dict[str, object], ...]:
        return _backend().search_catalogue_records(db_path, query, **filters)

    def catalogue_status(self, db_path: Path) -> dict[str, int]:
        return _backend().catalogue_stats(db_path)

    def download_candidate(
        self,
        record: Mapping[str, object],
        candidate: MirrorDownloadCandidate,
        *,
        output_root: Path,
        stop_event: Optional[threading.Event] = None,
    ) -> MirrorDownloadResult:
        return _backend().download_mirror_model_candidate(
            record,
            candidate,
            output_root=output_root,
            stop_event=stop_event,
        )

    def resolve_importable_model(
        self,
        source: Path,
        *,
        extract_root: Optional[Path] = None,
        selected_member: str = "",
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[Path]:
        return _backend().resolve_importable_model_path(
            source,
            extract_root=extract_root,
            selected_member=selected_member,
            stop_event=stop_event,
        )

    def importable_model_members(
        self,
        source: Path,
        *,
        stop_event: Optional[threading.Event] = None,
    ) -> tuple[str, ...]:
        return _backend().zip_importable_member_refs(source, stop_event=stop_event)


__all__ = ["ModelLibraryService"]
