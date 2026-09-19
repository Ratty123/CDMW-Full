"""Decode one page of registered barber icons away from the GUI thread."""
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.texture_native import ensure_directxtex_dds_preview_pngs
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.domain.cancellation import raise_if_cancelled


def prepare_hair_icons(entries, stop):
    if len(entries) > 24:
        raise ValueError("Hair icons must be prepared one page at a time.")
    images = {}
    with tempfile.TemporaryDirectory(prefix="cdmw-hair-icons-") as directory:
        sources = {}
        for index, entry in enumerate(entries):
            raise_if_cancelled(stop, "Hair icon loading cancelled.")
            if not 0 < entry.orig_size <= 2 * 1024 * 1024:
                continue
            try:
                data = read_archive_entry_data(entry, stop)[0]
                if len(data) != entry.orig_size:
                    continue
                path = Path(directory) / f"{index}.dds"
                path.write_bytes(data)
                info = parse_dds(path)
                if max(info.width, info.height) > 2048:
                    continue
                sources[str(path)] = entry.path.casefold()
            except (ValueError, OSError):
                continue
        raise_if_cancelled(stop, "Hair icon loading cancelled.")
        if not sources:
            return images
        previews = ensure_directxtex_dds_preview_pngs(
            [{"dds_path": path, "max_dimension": 140, "slot_kind": "base"} for path in sources],
            cache_dirname="mesh_hair_icons", stop_event=stop)
        for source, preview in previews.items():
            raise_if_cancelled(stop, "Hair icon loading cancelled.")
            if str(source) not in sources:
                continue
            reader = QImageReader(str(preview))
            size = reader.size()
            if not size.isValid() or max(size.width(), size.height()) > 2048:
                continue
            reader.setScaledSize(size.scaled(140, 140, Qt.KeepAspectRatio))
            image = reader.read()
            if not image.isNull():
                images[sources[str(source)]] = image.copy()
    return images
