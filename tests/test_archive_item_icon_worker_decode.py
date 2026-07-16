from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage

from cdmw.models import ArchiveEntry
from cdmw.workers.archive_workers import ArchiveItemIconWarmupWorker


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("sample.pamt"),
        paz_file=Path("sample.paz"),
        offset=1,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def test_item_icon_worker_decodes_cached_thumbnail_to_qimage(tmp_path: Path) -> None:
    preview_path = tmp_path / "cached.png"
    source_image = QImage(240, 120, QImage.Format.Format_RGBA8888)
    source_image.fill(QColor("red"))
    assert source_image.save(str(preview_path), "PNG")
    entry = _entry("ui/icon/test.png")
    worker = ArchiveItemIconWarmupWorker(
        7,
        ({"icon_paths": (entry.path,)},),
        {entry.path.casefold(): (entry,)},
        {entry.basename.casefold(): (entry,)},
        tmp_path / "game",
        tmp_path / "cache",
        max_dimension=120,
    )
    prepared: list[tuple[object, ...]] = []
    worker.icon_prepared.connect(lambda *args: prepared.append(args))

    with patch(
        "cdmw.workers.archive_workers.load_archive_item_icon_thumbnail_cache",
        return_value=(preview_path, "cached"),
    ):
        worker.run()

    assert len(prepared) == 1
    generation, prepared_key, path_text, note, decoded = prepared[0]
    assert generation == 7
    assert prepared_key[0] == (entry.path,)
    assert prepared_key[1].startswith("directxtex_native_0.2|bin=")
    assert path_text == str(preview_path)
    assert note == "cached"
    assert isinstance(decoded, QImage) and not decoded.isNull()
    assert max(decoded.width(), decoded.height()) <= 120


def test_icon_ui_never_reads_persistent_cache_or_decodes_path() -> None:
    source = Path("cdmw/ui/archive_browser/icon_pipeline.py").read_text(encoding="utf-8")
    assert "load_archive_item_icon_thumbnail_cache" not in source
    assert "QPixmap(str(preview_path))" not in source
    assert "QPixmap.fromImage(image)" in source
    assert "_archive_item_icon_prepared_pixmap_available" in source
