"""Headless synthetic probe for Python -> QProcess -> .NET -> native archive v2."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from typing import Callable, Sequence

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from cdmw.domain.archives.catalogue import (
    ArchiveChildrenRequest,
    ArchiveChildrenResult,
    ArchivePage,
    ArchiveQuery,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
)
from cdmw.domain.archives.catalogue_operations import (
    ArchiveExportCollisionPolicy,
    ArchiveExportRequest,
    ArchiveExportResult,
    ArchiveExportSelectionKind,
    ArchiveTextSearchBatch,
    ArchiveTextSearchRequest,
    FetchPageRequest,
    OpenArchiveRequest,
    PrepareEntryRequest,
    PrepareEntryResult,
)
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient, ArchiveBackendClientState


def _build_synthetic_archive(root: Path) -> None:
    package = root / "0009"
    package.mkdir(parents=True)
    payloads = (
        ("text/hello.txt", b"Hello Crimson from full archive v2\nline 2"),
        ("model/example.pac", b"PAC\x00synthetic"),
        ("materials/example.material", b"material synthetic"),
    )
    entries: list[tuple[str, int, int]] = []
    offset = 0
    with (package / "0.paz").open("xb") as stream:
        for virtual_path, payload in payloads:
            stream.write(payload)
            entries.append((virtual_path, offset, len(payload)))
            offset += len(payload)
        stream.flush()
        os.fsync(stream.fileno())

    names = bytearray()
    name_offsets: list[int] = []
    for virtual_path, _offset, _size in entries:
        encoded = virtual_path.encode("utf-8")
        if len(encoded) > 255:
            raise ValueError("Synthetic archive path exceeds the PAMT test bound.")
        name_offsets.append(len(names))
        names.extend(struct.pack("<I", 0xFFFFFFFF))
        names.append(len(encoded))
        names.extend(encoded)

    pamt = bytearray(struct.pack("<7I", 0, 1, 0, 0, 0, 0, 0))
    pamt.extend(struct.pack("<I", len(names)))
    pamt.extend(names)
    pamt.extend(struct.pack("<II", 0, len(entries)))
    for name_offset, (_path, archive_offset, size) in zip(name_offsets, entries, strict=True):
        pamt.extend(struct.pack("<IIIIHH", name_offset, archive_offset, size, size, 0, 0))
    (package / "0.pamt").write_bytes(pamt)


class _Awaiter:
    def __init__(self, service: ArchiveCatalogueService) -> None:
        self.results: dict[str, object] = {}
        self.failures: dict[str, object] = {}
        self.cancelled: set[str] = set()
        self.batches: dict[str, list[object]] = {}
        self.progress_phases: list[str] = []
        service.result_ready.connect(self._on_result)
        service.request_failed.connect(lambda request_id, error: self.failures.__setitem__(request_id, error))
        service.request_cancelled.connect(self.cancelled.add)
        service.batch_ready.connect(self._on_batch)
        service.progress.connect(
            lambda _request_id, update: self.progress_phases.append(str(getattr(update, "phase", "")))
        )

    def _on_result(self, request_id: str, _operation: str, result: object) -> None:
        self.results[request_id] = result

    def _on_batch(self, request_id: str, _operation: str, result: object) -> None:
        self.batches.setdefault(request_id, []).append(result)

    def wait(self, request_id: str, *, timeout_ms: int = 15_000) -> object:
        if not self._wait_until(
            lambda: request_id in self.results or request_id in self.failures or request_id in self.cancelled,
            timeout_ms=timeout_ms,
        ):
            raise TimeoutError(f"Archive backend request timed out: {request_id}")
        if request_id in self.failures:
            raise RuntimeError(f"Archive backend request failed: {self.failures[request_id]}")
        if request_id in self.cancelled:
            raise RuntimeError(f"Archive backend request was cancelled: {request_id}")
        return self.results[request_id]

    @staticmethod
    def _wait_until(predicate: Callable[[], bool], *, timeout_ms: int) -> bool:
        if predicate():
            return True
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(5)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        poll.start()
        timeout.start(timeout_ms)
        loop.exec()
        poll.stop()
        timeout.stop()
        return bool(predicate())


def run_probe(worker: Path) -> dict[str, object]:
    app = QCoreApplication.instance() or QCoreApplication([])
    with tempfile.TemporaryDirectory(prefix="cdmw-full-archive-v2-probe-") as temp_text:
        probe_root = Path(temp_text)
        archive_root = probe_root / "archive"
        cache_root = probe_root / "cache"
        export_root = probe_root / "export"
        _build_synthetic_archive(archive_root)
        client = ArchiveBackendClient(
            cache_root=cache_root,
            worker_executable=worker,
        )
        service = ArchiveCatalogueService(client)
        awaiter = _Awaiter(service)
        try:
            cold = awaiter.wait(
                service.open_archive(OpenArchiveRequest(str(archive_root)), ui_generation=1)
            )
            if not isinstance(cold, ArchiveSessionHandle) or cold.cache_hit or cold.entry_count != 3:
                raise AssertionError("Synthetic cold-open contract changed.")
            warm = awaiter.wait(
                service.open_archive(OpenArchiveRequest(str(archive_root)), ui_generation=2)
            )
            if not isinstance(warm, ArchiveSessionHandle) or not warm.cache_hit:
                raise AssertionError("Synthetic warm open did not reuse the v2 generation.")

            structure_root = awaiter.wait(
                service.fetch_structure_children(
                    warm.session_id,
                    ArchiveChildrenRequest("", include_package_root=True),
                    ui_generation=3,
                )
            )
            if (
                not isinstance(structure_root, ArchiveChildrenResult)
                or len(structure_root.children) != 1
                or structure_root.children[0].key != "0009"
                or structure_root.children[0].match_count != 3
            ):
                raise AssertionError("Synthetic package-root folder hierarchy changed.")

            query = awaiter.wait(
                service.create_query(
                    ArchiveQuery(
                        session_id=warm.session_id,
                        extensions=(".txt",),
                        folder="0009/text",
                    ),
                    ui_generation=4,
                )
            )
            if not isinstance(query, ArchiveQueryHandle):
                raise AssertionError("Synthetic query result type changed.")
            page = awaiter.wait(
                service.fetch_page(
                    FetchPageRequest(query.query_id, page_size=256),
                    ui_generation=5,
                )
            )
            if not isinstance(page, ArchivePage) or len(page.rows) != 1:
                raise AssertionError("Synthetic filtered page did not contain one text entry.")
            text_entry = page.rows[0]

            prepared = awaiter.wait(
                service.prepare_entry(
                    PrepareEntryRequest(warm.session_id, text_entry.entry_id),
                    ui_generation=6,
                )
            )
            if not isinstance(prepared, PrepareEntryResult):
                raise AssertionError("Synthetic prepare result type changed.")
            prepared_bytes = Path(prepared.prepared_path).read_bytes()
            if prepared_bytes != b"Hello Crimson from full archive v2\nline 2":
                raise AssertionError("Prepared archive bytes changed.")

            text_request_id = service.text_search(
                ArchiveTextSearchRequest(warm.session_id, "Crimson", batch_size=1),
                ui_generation=7,
            )
            text_terminal = awaiter.wait(text_request_id)
            text_batches = [
                batch
                for batch in awaiter.batches.get(text_request_id, [])
                if isinstance(batch, ArchiveTextSearchBatch)
            ]
            text_matches = sum(len(batch.matches) for batch in text_batches)
            if not isinstance(text_terminal, ArchiveTextSearchBatch) or text_matches != 1:
                raise AssertionError("Synthetic worker-side text search changed.")

            existing_export = export_root / "0009" / "text" / "hello.txt"
            existing_export.parent.mkdir(parents=True)
            existing_export.write_bytes(b"keep existing")
            export_request_id = service.export(
                ArchiveExportRequest(
                    session_id=warm.session_id,
                    selection_kind=ArchiveExportSelectionKind.QUERY,
                    destination=str(export_root),
                    query_id=query.query_id,
                    collision_policy=ArchiveExportCollisionPolicy.RENAME,
                    include_package_root=True,
                    extensions=("txt",),
                ),
                ui_generation=8,
            )
            export_result = awaiter.wait(export_request_id)
            export_items = tuple(
                item
                for batch in awaiter.batches.get(export_request_id, [])
                if isinstance(batch, ArchiveExportResult)
                for item in batch.items
            )
            if (
                not isinstance(export_result, ArchiveExportResult)
                or export_result.exported != 1
                or len(export_items) != 1
                or export_items[0].status != "renamed"
            ):
                raise AssertionError("Synthetic query-token export changed.")
            exported_bytes = (export_root / "0009" / "text" / "hello_2.txt").read_bytes()
            if exported_bytes != prepared_bytes:
                raise AssertionError("Synthetic exported bytes differ from prepared bytes.")
            if existing_export.read_bytes() != b"keep existing":
                raise AssertionError("Synthetic renamed export overwrote its collision target.")

            report = {
                "status": "passed",
                "evidence": "synthetic_headless_qprocess",
                "worker": str(worker),
                "entry_count": warm.entry_count,
                "cold_cache_hit": cold.cache_hit,
                "warm_cache_hit": warm.cache_hit,
                "page_rows": len(page.rows),
                "structure_root_count": len(structure_root.children),
                "text_matches": text_matches,
                "exported": export_result.exported,
                "export_renamed": export_items[0].status == "renamed",
                "prepared_sha256": prepared.sha256,
                "progress_phases": sorted(set(awaiter.progress_phases)),
                "stderr_tail_bytes": len(client.diagnostics_tail.encode("utf-8")),
            }
        finally:
            service.request_shutdown()
            _Awaiter._wait_until(
                lambda: client.state in {ArchiveBackendClientState.STOPPED, ArchiveBackendClientState.FAILED},
                timeout_ms=5_000,
            )
            app.processEvents()
        return report


def _write_report(path: Path, report: dict[str, object]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        staging.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(staging, destination)
    finally:
        staging.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_probe(args.worker.expanduser().resolve())
    except Exception as exc:
        report = {
            "status": "failed",
            "evidence": "synthetic_headless_qprocess",
            "error": f"{type(exc).__name__}: {exc}",
        }
        if args.report is not None:
            _write_report(args.report, report)
        print(json.dumps(report, sort_keys=True))
        return 1
    if args.report is not None:
        _write_report(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
