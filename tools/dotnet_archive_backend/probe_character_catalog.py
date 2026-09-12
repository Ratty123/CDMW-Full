"""Read-only Body & Face Finder audit through the actual Python/QProcess worker.

Run only against an explicitly authorized archive root. Evidence belongs outside
the repository. PAMT/mount content hashes and PAZ file metadata are compared;
this does not claim a full-content hash of every PAZ archive.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication
from cdmw.domain.archives.catalogue_operations import OpenArchiveRequest
from cdmw.domain.archives.character_catalogue import CharacterCatalogSearchRequest, CharacterCatalogDetailRequest
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient
from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter


def source_snapshot(root: Path) -> dict[str, object]:
    result = {}
    for directory in (root, *sorted(p for p in root.iterdir() if p.is_dir())):
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in {".pamt", ".paz", ".papgt"}:
                continue
            stat = path.stat()
            row = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            if path.suffix.lower() in {".pamt", ".papgt"}:
                row["sha256"] = sha256(path.read_bytes()).hexdigest()
            result[str(path.relative_to(root))] = row
    return result


def run(root: Path, output: Path, worker: Path) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    output.mkdir(parents=True, exist_ok=True)
    before = source_snapshot(root)
    client = ArchiveBackendClient(cache_root=output / "cache", worker_executable=worker)
    service = ArchiveCatalogueService(client)
    awaiter = _Awaiter(service)
    service.progress.connect(lambda _id, update: print(f"{update.phase}: {update.completed}/{update.total} {update.current_item or ''}", flush=True)
                             if update.phase == "character_catalog" else None)
    started = time.monotonic()
    try:
        session = awaiter.wait(service.open_archive(OpenArchiveRequest(str(root)), ui_generation=1), timeout_ms=600_000)
        print(f"Archive open: {session.entry_count:,} records; cache={session.cache_hit}", flush=True)
        build = awaiter.wait(service.build_character_catalog(session.session_id, ui_generation=1), timeout_ms=900_000)
        print(json.dumps(asdict(build)), flush=True)
        warm = awaiter.wait(service.build_character_catalog(session.session_id, ui_generation=1))
        if not warm.used_cache:
            raise AssertionError("Warm opening did not reuse the catalogue")
        counts = Counter()
        coverage_count = 0
        with (output / "coverage.jsonl").open("w", encoding="utf-8") as stream:
            while True:
                result = awaiter.wait(service.search_character_catalog(CharacterCatalogSearchRequest(
                    session.session_id, view="coverage", tab="all", page_start=coverage_count), ui_generation=1), timeout_ms=60_000)
                for row in result.rows:
                    if not row.evidence:
                        raise AssertionError(f"Candidate has no reason: {row.key}")
                    stream.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
                    counts[(row.role, row.resolution)] += 1
                coverage_count += len(result.rows)
                if coverage_count >= result.total_matches:
                    break
                if not result.rows:
                    raise AssertionError("Coverage paging stalled")
        if coverage_count != build.candidate_count or build.candidate_count != build.resolved_count + build.unresolved_count + build.excluded_count:
            raise AssertionError("Candidate accounting did not balance")
        samples = {}
        for query in ("Kliff", "Damiane", "Oongka"):
            result = awaiter.wait(service.search_character_catalog(CharacterCatalogSearchRequest(
                session.session_id, query=query, view="appearances", tab="all"), ui_generation=1), timeout_ms=60_000)
            samples[query] = {"total": result.total_matches, "rows": [asdict(row) for row in result.rows]}
            for row in result.rows[:3]:
                detail = awaiter.wait(service.get_character_catalog_detail(CharacterCatalogDetailRequest(session.session_id, row.key), ui_generation=1))
                (output / f"detail-{query}-{row.role}.json").write_text(json.dumps(asdict(detail), indent=2, ensure_ascii=False), encoding="utf-8")
        after = source_snapshot(root)
        report = {"schema": "cdmw_character_catalog_audit_v1", "package_root": str(root), "session": asdict(session),
                  "catalogue": asdict(build), "warm_cache": warm.used_cache, "coverage_count": coverage_count,
                  "groups": [{"role": role, "resolution": state, "count": count} for (role, state), count in sorted(counts.items())],
                  "samples": samples, "archive_snapshot_unchanged": before == after, "source_snapshot": before,
                  "elapsed_seconds": round(time.monotonic() - started, 3)}
        (output / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        if before != after:
            raise AssertionError("Archive source snapshot changed during the audit")
        print(f"Audit complete: {output / 'audit.json'} ({coverage_count:,} candidates)", flush=True)
    finally:
        client.shutdown()
        _Awaiter._wait_until(lambda: client.process_id == 0, timeout_ms=10_000)
        app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--worker", type=Path, default=ROOT / "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/bin/Release/net10.0-windows/win-x64/cdmw-full-archive-worker.exe")
    args = parser.parse_args()
    run(args.package_root, args.output, args.worker)
