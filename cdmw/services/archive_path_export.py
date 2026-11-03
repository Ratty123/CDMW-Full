"""Stream catalogue metadata to a path list without opening archive payloads."""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from queue import Empty

from cdmw.models import RunCancelled


@dataclass(frozen=True)
class ArchivePathExportRequest:
    request_id: int
    destination: Path
    folder: str = ""


@dataclass(frozen=True)
class ArchivePathExportResult:
    request_id: int
    destination: Path
    count: int
    cancelled: bool = False
    error: str = ""


def export_archive_paths(request, batches, *, stop_event, page_consumed, progress):
    """Consume one bounded metadata page at a time; replace output only on success.

    Queue items are (rows, total_matches), None for completion, or an exception.
    The producer requests the next page only after page_consumed is called.
    """
    target = request.destination
    if target.suffix.lower() not in {".txt", ".csv"}:
        raise ValueError("Choose a TXT or CSV file.")
    temporary = None
    count = scanned = 0
    folder = request.folder.replace("\\", "/").strip("/").casefold()
    prefix = folder + "/" if folder else ""

    def check_cancelled():
        if stop_event.is_set():
            raise RunCancelled("Path export cancelled.")

    try:
        check_cancelled()
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig" if target.suffix.lower() == ".csv" else "utf-8",
            newline="", dir=target.parent, prefix=".cdmw-paths-", suffix=".tmp", delete=False,
        ) as output:
            temporary = Path(output.name)
            writer = csv.writer(output) if target.suffix.lower() == ".csv" else None
            if writer is not None:
                writer.writerow(("path", "filename", "package", "source_pamt"))
            while True:
                check_cancelled()
                try:
                    batch = batches.get(timeout=0.1)
                except Empty:
                    continue
                if isinstance(batch, Exception):
                    raise batch
                if batch is None:
                    break
                rows, total = batch
                for entry in rows:
                    check_cancelled()
                    path = entry.path.replace("\\", "/")
                    if prefix and not path.casefold().startswith(prefix):
                        continue
                    if writer is not None:
                        writer.writerow((path, PurePosixPath(path).name, entry.package, entry.source_pamt))
                    else:
                        if "\n" in path or "\r" in path:
                            raise ValueError("An archive path contains a line break. Use CSV instead.")
                        output.write(path + "\n")
                    count += 1
                scanned += len(rows)
                progress(scanned, total)
                page_consumed()
            output.flush()
            os.fsync(output.fileno())
        check_cancelled()
        os.replace(temporary, target)
        temporary = None
        return ArchivePathExportResult(request.request_id, target, count)
    except RunCancelled:
        return ArchivePathExportResult(request.request_id, target, 0, cancelled=True)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
