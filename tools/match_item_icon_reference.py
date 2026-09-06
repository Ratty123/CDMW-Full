"""Match a screenshot against read-only item-icon DDS entries from the game archive.

This is a developer diagnostic for material-parity work.  It reuses CDMW's
resident archive backend and native DDS decoder, writes only to the requested
report directory, and never modifies installed game files.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
from typing import Callable

import numpy
from PIL import Image, ImageDraw
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from cdmw.core.texture_native import ensure_directxtex_dds_preview_pngs
from cdmw.domain.archives.catalogue import ArchiveQuery
from cdmw.domain.archives.catalogue_operations import (
    FetchPageRequest,
    OpenArchiveRequest,
    PrepareEntriesRequest,
    PrepareEntriesResult,
)
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient


class _Awaiter:
    def __init__(self, service: ArchiveCatalogueService) -> None:
        self.results: dict[str, object] = {}
        self.batches: dict[str, PrepareEntriesResult] = {}
        self.failures: dict[str, object] = {}
        self.cancelled: set[str] = set()
        service.batch_ready.connect(self._on_batch)
        service.result_ready.connect(self._on_result)
        service.request_failed.connect(self._on_failure)
        service.request_cancelled.connect(self.cancelled.add)

    def _on_result(self, request_id: str, _operation: str, result: object) -> None:
        previous = self.batches.pop(request_id, None)
        if isinstance(previous, PrepareEntriesResult) and isinstance(result, PrepareEntriesResult):
            result = PrepareEntriesResult(
                session_id=result.session_id,
                items=previous.items + result.items,
                requested=result.requested,
                prepared=result.prepared,
                total_bytes=result.total_bytes,
            )
        self.results[request_id] = result

    def _on_batch(self, request_id: str, _operation: str, result: object) -> None:
        if not isinstance(result, PrepareEntriesResult):
            return
        previous = self.batches.get(request_id)
        if previous is not None:
            result = PrepareEntriesResult(
                session_id=result.session_id,
                items=previous.items + result.items,
                requested=result.requested,
                prepared=result.prepared,
                total_bytes=result.total_bytes,
            )
        self.batches[request_id] = result

    def _on_failure(self, request_id: str, error: object) -> None:
        self.failures[request_id] = error

    def wait(self, request_id: str, *, timeout_ms: int = 300_000) -> object:
        done: Callable[[], bool] = lambda: (
            request_id in self.results
            or request_id in self.failures
            or request_id in self.cancelled
        )
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if done() else None)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        poll.start()
        timeout.start(timeout_ms)
        if not done():
            loop.exec()
        poll.stop()
        timeout.stop()
        if request_id in self.failures:
            raise RuntimeError(f"Archive request failed: {self.failures[request_id]}")
        if request_id in self.cancelled:
            raise RuntimeError("Archive request was cancelled")
        if request_id not in self.results:
            raise TimeoutError(f"Archive request timed out: {request_id}")
        return self.results[request_id]


def _normalized_virtual_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


def _catalogue_path(cache_root: Path) -> Path:
    matches = sorted(
        (cache_root / "index" / "catalogue_v2").rglob("item-catalog-v3.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError("No item-catalog-v3.json exists in the selected CDMW cache")
    return matches[0]


def _candidate_items(catalogue: Path, category_pattern: str) -> tuple[dict[str, object], ...]:
    payload = json.loads(catalogue.read_text(encoding="utf-8"))
    pattern = re.compile(category_pattern, re.IGNORECASE)
    return tuple(
        row
        for row in payload.get("items", ())
        if isinstance(row, dict)
        and pattern.search(
            " ".join(
                (
                    str(row.get("display_name", "")),
                    str(row.get("internal_name", "")),
                    str(row.get("group", "")),
                    str(row.get("category", "")),
                )
            )
        )
    )


def _crop_masked(
    rgb: numpy.ndarray,
    mask: numpy.ndarray,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    y_values, x_values = numpy.where(mask)
    if not len(x_values):
        return rgb, mask
    x0 = max(0, int(x_values.min()) - 2)
    x1 = min(rgb.shape[1], int(x_values.max()) + 3)
    y0 = max(0, int(y_values.min()) - 2)
    y1 = min(rgb.shape[0], int(y_values.max()) + 3)
    return rgb[y0:y1, x0:x1], mask[y0:y1, x0:x1]


def _fit_foreground(
    rgb: numpy.ndarray,
    mask: numpy.ndarray,
    *,
    size: int = 256,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    rgb, mask = _crop_masked(rgb, mask)
    height, width = rgb.shape[:2]
    scale = min((size - 12) / max(1, width), (size - 12) / max(1, height))
    fitted_width = max(1, round(width * scale))
    fitted_height = max(1, round(height * scale))
    fitted_rgb = numpy.asarray(
        Image.fromarray(rgb).resize(
            (fitted_width, fitted_height),
            Image.Resampling.LANCZOS,
        )
    ).astype(numpy.float32) / 255.0
    fitted_mask = numpy.asarray(
        Image.fromarray((mask * 255).astype(numpy.uint8)).resize(
            (fitted_width, fitted_height),
            Image.Resampling.BILINEAR,
        )
    ).astype(numpy.float32) / 255.0
    output = numpy.zeros((size, size, 3), numpy.float32)
    output[:] = numpy.array((0.025, 0.028, 0.040), numpy.float32)
    output_mask = numpy.zeros((size, size), numpy.float32)
    x = (size - fitted_width) // 2
    y = (size - fitted_height) // 2
    output[y : y + fitted_height, x : x + fitted_width] = fitted_rgb
    output_mask[y : y + fitted_height, x : x + fitted_width] = fitted_mask
    return output, output_mask


def _reference_foreground(reference: Path) -> tuple[numpy.ndarray, numpy.ndarray]:
    rgb = numpy.asarray(Image.open(reference).convert("RGB"))
    height, width = rgb.shape[:2]
    border = numpy.concatenate(
        (
            rgb[:12].reshape(-1, 3),
            rgb[-12:].reshape(-1, 3),
            rgb[:, :12].reshape(-1, 3),
            rgb[:, -12:].reshape(-1, 3),
        )
    )
    background = numpy.median(border, axis=0)
    distance = numpy.linalg.norm(
        rgb.astype(numpy.float32) - background.astype(numpy.float32),
        axis=2,
    )
    mask = distance > 42
    mask[:16, :] = False
    mask[-16:, :] = False
    mask[:, :16] = False
    mask[:, -16:] = False
    row_counts = mask.sum(axis=1)
    column_counts = mask.sum(axis=0)
    mask[row_counts > int(width * 0.82), :] = False
    mask[:, column_counts > int(height * 0.82)] = False
    return _fit_foreground(rgb, mask)


def _similarity(
    reference: numpy.ndarray,
    reference_mask: numpy.ndarray,
    candidate: numpy.ndarray,
    candidate_mask: numpy.ndarray,
) -> tuple[float, float, float, float]:
    union = numpy.maximum(reference_mask, candidate_mask)
    intersection = numpy.minimum(reference_mask, candidate_mask)
    intersection_over_union = float(intersection.sum() / (union.sum() + 1e-6))
    overlap = intersection > 0.18
    mean_absolute_error = (
        float(numpy.abs(reference[overlap] - candidate[overlap]).mean())
        if overlap.any()
        else 1.0
    )
    reference_weight = reference_mask[..., None]
    candidate_weight = candidate_mask[..., None]
    reference_mean = (reference * reference_weight).sum((0, 1)) / (
        reference_weight.sum() + 1e-6
    )
    candidate_mean = (candidate * candidate_weight).sum((0, 1)) / (
        candidate_weight.sum() + 1e-6
    )
    colour_error = float(numpy.abs(reference_mean - candidate_mean).mean())
    score = (
        (0.66 * intersection_over_union)
        + (0.24 * (1.0 - mean_absolute_error))
        + (0.10 * (1.0 - colour_error))
    )
    return score, intersection_over_union, mean_absolute_error, colour_error


def _decode_icons(paths: tuple[Path, ...]) -> dict[str, Path]:
    decoded: dict[str, Path] = {}
    jobs = tuple(
        {
            "dds_path": str(path),
            "max_dimension": 1024,
            "slot_kind": "base",
            "srgb": "srgb",
        }
        for path in paths
    )
    for start in range(0, len(jobs), 24):
        decoded.update(
            ensure_directxtex_dds_preview_pngs(
                jobs[start : start + 24],
                timeout_seconds=120,
            )
        )
    return decoded


def _write_contact_sheet(rows: list[dict[str, object]], output: Path, count: int) -> None:
    selected = rows[:count]
    if not selected:
        return
    columns = 4
    cell_width = 320
    cell_height = 310
    sheet = Image.new(
        "RGB",
        (columns * cell_width, math.ceil(len(selected) / columns) * cell_height),
        (22, 24, 30),
    )
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(selected):
        icon = Image.open(str(row["png"])).convert("RGBA")
        icon.thumbnail((250, 250), Image.Resampling.LANCZOS)
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        cell = Image.new("RGBA", (256, 256), (10, 12, 16, 255))
        cell.alpha_composite(icon, ((256 - icon.width) // 2, (256 - icon.height) // 2))
        sheet.paste(cell.convert("RGB"), (x + 32, y))
        names = tuple(row.get("names", ()))
        label = str(names[0] if names else row["virtual_path"])[:42]
        stems = tuple(row.get("model_stems", ()))
        draw.text((x + 6, y + 260), f"{index + 1}. {row['score']:.3f} {label}", fill=(235, 235, 235))
        draw.text((x + 6, y + 280), str(stems[0] if stems else "")[:48], fill=(170, 190, 220))
    sheet.save(output)


def _write_icon_ranking_results(
    args, ranking, catalogue, items, desired_paths, query, entries, prepared, prepared_by_virtual_path,
    decoded,
):
    args.output.mkdir(parents=True, exist_ok=True)
    ranking_path = args.output / "ranking.json"
    contact_sheet_path = args.output / "top-matches.png"
    ranking_path.write_text(json.dumps(ranking, indent=2), encoding="utf-8")
    _write_contact_sheet(ranking, contact_sheet_path, args.top)
    return {
        "schema": "cdmw_item_icon_reference_match_v1",
        "read_only_archive_access": True,
        "catalogue": str(catalogue),
        "candidate_items": len(items),
        "candidate_icon_paths": len(desired_paths),
        "archive_query_matches": query.total_matches,
        "resolved_icons": len(entries),
        "prepared_icons": prepared.prepared,
        "existing_prepared_icons": sum(
            1 for path in prepared_by_virtual_path.values() if path.is_file()
        ),
        "sample_prepared_path": str(next(iter(prepared_by_virtual_path.values()), "")),
        "decoded_icons": len(decoded),
        "ranking": str(ranking_path),
        "contact_sheet": str(contact_sheet_path) if contact_sheet_path.is_file() else "",
        "top": ranking[: min(args.top, len(ranking))],
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    cache_root = args.cache_root.resolve()
    catalogue = args.catalogue.resolve() if args.catalogue else _catalogue_path(cache_root)
    items = _candidate_items(catalogue, args.category_pattern)
    path_to_items: dict[str, list[dict[str, object]]] = {}
    for item in items:
        for raw_path in item.get("icon_paths", ()):
            path_to_items.setdefault(_normalized_virtual_path(raw_path), []).append(item)
    desired_paths = set(path_to_items)
    if not desired_paths:
        raise RuntimeError("The selected item category has no icon paths")

    app = QCoreApplication.instance() or QCoreApplication([])
    client = ArchiveBackendClient(
        cache_root=cache_root,
        worker_executable=args.worker.resolve(),
    )
    service = ArchiveCatalogueService(client)
    awaiter = _Awaiter(service)
    prepared_by_virtual_path: dict[str, Path] = {}
    decoded: dict[str, Path] = {}
    try:
        session = awaiter.wait(
            service.open_archive(
                OpenArchiveRequest(str(args.game_root.resolve())),
                ui_generation=1,
            )
        )
        query = awaiter.wait(
            service.create_query(
                ArchiveQuery(
                    session_id=session.session_id,
                    include_text=args.archive_query,
                    extensions=(".dds",),
                ),
                ui_generation=2,
            )
        )
        generation = 3
        entries = []
        for start in range(0, query.total_matches, 512):
            page = awaiter.wait(
                service.fetch_page(
                    FetchPageRequest(query.query_id, page_start=start, page_size=512),
                    ui_generation=generation,
                )
            )
            generation += 1
            entries.extend(
                row
                for row in page.rows
                if _normalized_virtual_path(row.path) in desired_paths
            )
        if not entries:
            raise RuntimeError("The archive query did not resolve any candidate icon paths")
        prepared = awaiter.wait(
            service.prepare_entries(
                PrepareEntriesRequest(
                    session.session_id,
                    tuple(row.entry_id for row in entries),
                ),
                ui_generation=generation,
            )
        )
        entry_paths = {
            row.entry_id: _normalized_virtual_path(row.path)
            for row in entries
        }
        prepared_by_virtual_path = {
            entry_paths[item.entry.entry_id]: Path(item.prepared_path)
            for item in prepared.items
        }
        # Prepared archive entries are leased by the active catalogue session.
        # Decode them before shutting down the backend so the read-only snapshots
        # cannot disappear between preparation and image comparison.
        decoded = _decode_icons(tuple(prepared_by_virtual_path.values()))
    finally:
        client.shutdown()
        drain = QEventLoop()
        QTimer.singleShot(500, drain.quit)
        drain.exec()
    reference, reference_mask = _reference_foreground(args.reference.resolve())
    ranking: list[dict[str, object]] = []
    for virtual_path, dds_path in prepared_by_virtual_path.items():
        png_path = decoded.get(str(dds_path.resolve()))
        if png_path is None:
            continue
        rgba = numpy.asarray(Image.open(png_path).convert("RGBA"))
        alpha = rgba[..., 3].astype(numpy.float32) / 255.0
        if alpha.max() < 0.1:
            continue
        candidate, candidate_mask = _fit_foreground(rgba[..., :3], alpha > 0.08)
        direct = _similarity(reference, reference_mask, candidate, candidate_mask)
        flipped = _similarity(
            reference,
            reference_mask,
            candidate[:, ::-1],
            candidate_mask[:, ::-1],
        )
        best = direct if direct[0] >= flipped[0] else flipped
        owners = path_to_items.get(virtual_path, ())
        ranking.append(
            {
                "score": best[0],
                "intersection_over_union": best[1],
                "mean_absolute_error": best[2],
                "colour_error": best[3],
                "horizontally_flipped": best is flipped,
                "virtual_path": virtual_path,
                "png": str(png_path),
                "names": sorted(
                    {
                        str(item.get("display_name") or item.get("internal_name") or "")
                        for item in owners
                    }
                ),
                "model_stems": sorted(
                    {
                        stem
                        for item in owners
                        for stem in (item.get("model_stems") or ())
                    }
                ),
                "pac_files": sorted(
                    {
                        path
                        for item in owners
                        for path in (item.get("pac_files") or ())
                    }
                ),
            }
        )
    ranking.sort(key=lambda row: float(row["score"]), reverse=True)
    return _write_icon_ranking_results(args, ranking, catalogue, items, desired_paths, query, entries, prepared, prepared_by_virtual_path, decoded)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, default=_REPOSITORY_ROOT / "workspace" / "cache")
    parser.add_argument(
        "--worker",
        type=Path,
        default=_REPOSITORY_ROOT
        / "native"
        / "cdmw_full_archive_backend"
        / "build"
        / "Release"
        / "cdmw-full-archive-worker.exe",
    )
    parser.add_argument("--catalogue", type=Path)
    parser.add_argument("--category-pattern", default=r"helm|helmet")
    parser.add_argument("--archive-query", default="itemicon_prefab")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top", type=int, default=24)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not 1 <= args.top <= 100:
        raise SystemExit("--top must be between 1 and 100")
    report = run(args)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
