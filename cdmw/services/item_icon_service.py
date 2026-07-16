"""Item Icon filesystem, preview, and package coordination."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from cdmw.domain.library.item_icons import (
    ItemIconBuildResult,
    ItemIconLibraryRecord,
    ItemIconLooseModPatchResult,
    ItemIconOverrideSpec,
    ItemIconSourceCandidate,
    ItemIconTemplateInfo,
)


def _backend() -> object:
    from cdmw.core import item_icon

    return item_icon


@dataclass(slots=True)
class ItemIconService:
    settings: object | None = None

    def choose_source(
        self,
        source: Path,
        *,
        target_path: str,
        related_stems: Sequence[str] = (),
        display_name: str = "",
        min_score: int = 80,
    ) -> tuple[Optional[ItemIconSourceCandidate], tuple[ItemIconSourceCandidate, ...], str]:
        return _backend().choose_item_icon_source(
            source,
            target_path=target_path,
            related_stems=related_stems,
            display_name=display_name,
            min_score=min_score,
        )

    def refresh_library(
        self,
        roots: Sequence[Path],
        *,
        index_path: Path,
        edited_root: Path,
        stop_event: Optional[threading.Event] = None,
    ) -> tuple[ItemIconLibraryRecord, ...]:
        records = _backend().scan_item_icon_library(
            roots,
            index_path=index_path,
            edited_root=edited_root,
            stop_event=stop_event,
        )
        _backend().save_item_icon_library_index(
            index_path,
            roots=tuple(roots) + (edited_root,),
            records=records,
            stop_event=stop_event,
        )
        return records

    def load_library_index(self, index_path: Path) -> dict[str, object]:
        return _backend().load_item_icon_library_index(index_path)

    def inspect_library_source(
        self,
        source_path: Path,
        **kwargs: object,
    ) -> ItemIconLibraryRecord:
        return _backend().inspect_item_icon_library_source(source_path, **kwargs)

    def save_record_metadata(
        self,
        index_path: Path,
        record_path: Path,
        *,
        tags: Sequence[str] = (),
        notes: str = "",
        favorite: bool = False,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        _backend().update_item_icon_library_record_metadata(
            index_path,
            record_path,
            tags=tags,
            notes=notes,
            favorite=favorite,
            stop_event=stop_event,
        )

    def build_source_preview(
        self,
        source_path: Path,
        *,
        output_dir: Path,
        stop_event: Optional[threading.Event] = None,
    ) -> Path:
        return _backend().build_item_icon_source_preview_png(
            source_path,
            output_dir=output_dir,
            stop_event=stop_event,
        )

    def build_fit_preview(
        self,
        source_path: Path,
        **kwargs: object,
    ) -> tuple[Path, ItemIconTemplateInfo, tuple[int, int], tuple[str, ...]]:
        return _backend().build_item_icon_fit_pad_preview(source_path, **kwargs)

    def build_payload(
        self,
        spec: ItemIconOverrideSpec,
        *,
        target_template_path: Path,
        stop_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> ItemIconBuildResult:
        return _backend().build_item_icon_payload(
            spec,
            target_template_path=target_template_path,
            stop_event=stop_event,
            on_log=on_log,
        )

    def patch_existing_package(
        self,
        source_root: Path,
        *,
        target_path: str,
        payload_data: bytes,
        target_entry: object | None = None,
        stop_event: Optional[threading.Event] = None,
    ) -> ItemIconLooseModPatchResult:
        return _backend().patch_existing_loose_mod_with_item_icon(
            source_root,
            target_path=target_path,
            payload_data=payload_data,
            target_entry=target_entry,
            stop_event=stop_event,
        )


__all__ = ["ItemIconService"]
