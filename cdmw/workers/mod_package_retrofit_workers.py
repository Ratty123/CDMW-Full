"""Cancellable scan and transactional conversion work for Retrofit/Repackage."""

from __future__ import annotations

import dataclasses
import os
import shutil
import tempfile
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.domain.packages.retrofit import (
    KNOWN_RETROFIT_CONTENT_ROOTS,
    ModPackageRetrofitResult,
    RetrofitPathRepairSummary,
    RetrofittableModPackage,
)
from cdmw.core.mod_package_retrofit import (
    build_retrofit_path_repair_summary,
    retrofit_mod_package,
    scan_retrofittable_mod_packages,
)
from cdmw.models import RunCancelled


ProgressCallback = Callable[[int, int, str], None]


@dataclasses.dataclass(frozen=True, slots=True)
class RetrofitScanRequest:
    request_id: int
    source: Path


@dataclasses.dataclass(frozen=True, slots=True)
class RetrofitScanResult:
    request_id: int
    packages: tuple[RetrofittableModPackage, ...]
    summaries: tuple[RetrofitPathRepairSummary, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class RetrofitConversionItem:
    package: RetrofittableModPackage
    manager_profile: str
    export_options: ModPackageExportOptions
    scan_summary: RetrofitPathRepairSummary


@dataclasses.dataclass(frozen=True, slots=True)
class RetrofitConversionRequest:
    request_id: int
    output_root: Path
    items: tuple[RetrofitConversionItem, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class RetrofitConversionResult:
    request_id: int
    processed: tuple[tuple[str, Path, RetrofitPathRepairSummary], ...]
    failed: tuple[tuple[str, str], ...]


def _should_skip_directory(path: Path) -> bool:
    name = path.name.casefold()
    return name in {"converted", "_archive", "retrofit_output", "converted_output"} or name.startswith(
        ("retrofit_", "converted_")
    )


def _looks_like_package_root(path: Path, *, stop_event: threading.Event | None = None) -> bool:
    metadata_names = {"manifest.json", "mod.json", "modinfo.json", "info.json", "mod.field.json"}
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                raise_if_cancelled(stop_event, "Retrofit package scan cancelled.")
                name = entry.name.casefold()
                if entry.is_file() and name in metadata_names:
                    return True
                if entry.is_dir() and name in KNOWN_RETROFIT_CONTENT_ROOTS | {"files"}:
                    return True
    except OSError:
        return False
    return False


def collect_retrofittable_packages(
    source: Path,
    *,
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> list[RetrofittableModPackage]:
    """Recursively find packages without doing traversal on the UI thread."""

    source = Path(source).expanduser()
    raise_if_cancelled(stop_event, "Retrofit package scan cancelled.")
    if not source.is_dir():
        if not source.is_file() or source.suffix.casefold() != ".zip":
            raise FileNotFoundError("Source folder does not exist.")
        return scan_retrofittable_mod_packages(source, stop_event=stop_event)

    collected: list[RetrofittableModPackage] = []
    seen_roots: set[Path] = set()
    stack = [source]
    scanned = 0
    while stack:
        raise_if_cancelled(stop_event, "Retrofit package scan cancelled.")
        current = stack.pop()
        if not current.is_dir():
            continue
        scanned += 1
        if progress is not None and (scanned == 1 or scanned % 128 == 0):
            progress(scanned, 0, f"Scanning {current.name or current}")
        current_packages = (
            scan_retrofittable_mod_packages(current, stop_event=stop_event)
            if _looks_like_package_root(current, stop_event=stop_event)
            else []
        )
        for package in current_packages:
            if package.root not in seen_roots:
                collected.append(package)
                seen_roots.add(package.root)
        if len(current_packages) == 1 and current_packages[0].root == current:
            continue
        try:
            discovered_roots = {package.root for package in current_packages}
            with os.scandir(current) as children:
                for entry in children:
                    raise_if_cancelled(stop_event, "Retrofit package scan cancelled.")
                    child = Path(entry.path)
                    if child in discovered_roots:
                        continue
                    if entry.is_dir() and not _should_skip_directory(child):
                        stack.append(child)
                    elif entry.is_file() and child.suffix.casefold() == ".zip":
                        for package in scan_retrofittable_mod_packages(child, stop_event=stop_event):
                            if package.root not in seen_roots:
                                collected.append(package)
                                seen_roots.add(package.root)
        except OSError:
            continue
    collected.sort(key=lambda package: str(package.root).casefold())
    return collected


def scan_retrofit_request(
    request: RetrofitScanRequest,
    *,
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> RetrofitScanResult:
    packages = collect_retrofittable_packages(request.source, stop_event=stop_event, progress=progress)
    summaries: list[RetrofitPathRepairSummary] = []
    total = len(packages)
    for index, package in enumerate(packages, start=1):
        raise_if_cancelled(stop_event, "Retrofit package scan cancelled.")
        if progress is not None:
            progress(index, total, f"Analyzing {package.name}")
        summaries.append(
            build_retrofit_path_repair_summary(
                package,
                compare_payload_bytes=False,
                stop_event=stop_event,
            )
        )
    return RetrofitScanResult(request.request_id, tuple(packages), tuple(summaries))


def next_available_retrofit_package_name(
    package_name: str,
    profile: str,
    output_root: Path,
    suffixes: dict[str, int],
) -> str:
    base_key = f"{package_name}_{profile}"
    suffix = suffixes.get(base_key, 0)
    while True:
        candidate = package_name if suffix == 0 else f"{package_name}_{suffix}"
        target_root = output_root / f"{candidate}_{profile}"
        if not target_root.exists() and not target_root.with_suffix(".zip").exists():
            suffixes[base_key] = suffix + 1
            return candidate
        suffix += 1


def _publication_pairs(
    staged_results: Sequence[ModPackageRetrofitResult],
    output_root: Path,
) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for result in staged_results:
        pairs.append((result.package_root, output_root / result.package_root.name))
        if result.zip_path.is_file():
            pairs.append((result.zip_path, output_root / result.zip_path.name))
    targets = [target for _staged, target in pairs]
    if len(set(targets)) != len(targets):
        raise ValueError("Retrofit conversion produced duplicate output paths.")
    existing = [target for target in targets if target.exists()]
    if existing:
        raise FileExistsError(f"Retrofit output appeared during conversion: {existing[0]}")
    return pairs


def _publish_staged_results(
    staged_results: Sequence[ModPackageRetrofitResult],
    output_root: Path,
    *,
    stop_event: threading.Event | None,
) -> None:
    pairs = _publication_pairs(staged_results, output_root)
    raise_if_cancelled(stop_event, "Retrofit conversion cancelled.")
    moved: list[tuple[Path, Path]] = []
    try:
        for staged, target in pairs:
            raise_if_cancelled(stop_event, "Retrofit conversion cancelled.")
            os.replace(staged, target)
            moved.append((staged, target))
    except Exception:
        for staged, target in reversed(moved):
            try:
                os.replace(target, staged)
            except OSError:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
        raise


def _published_result(result: ModPackageRetrofitResult, output_root: Path) -> ModPackageRetrofitResult:
    package_root = output_root / result.package_root.name
    metadata_files = tuple(package_root / path.relative_to(result.package_root) for path in result.metadata_files)
    return dataclasses.replace(
        result,
        output_root=output_root,
        package_root=package_root,
        zip_path=output_root / result.zip_path.name,
        metadata_files=metadata_files,
    )


def convert_retrofit_request(
    request: RetrofitConversionRequest,
    *,
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> RetrofitConversionResult:
    output_root = Path(request.output_root).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".cdmw-retrofit-", dir=output_root))
    staged: list[tuple[RetrofitConversionItem, str, ModPackageRetrofitResult]] = []
    failed: list[tuple[str, str]] = []
    suffixes: dict[str, int] = {}
    try:
        total = len(request.items)
        for index, item in enumerate(request.items, start=1):
            raise_if_cancelled(stop_event, "Retrofit conversion cancelled.")
            if progress is not None:
                progress(index, total, f"Processing {item.package.name}")
            safe_name = next_available_retrofit_package_name(
                item.package.name,
                item.manager_profile,
                output_root,
                suffixes,
            )
            package = dataclasses.replace(item.package, name=safe_name)
            try:
                result = retrofit_mod_package(
                    package,
                    staging_root,
                    manager_profile=item.manager_profile,
                    export_options=dataclasses.replace(item.export_options),
                    stop_event=stop_event,
                )
                staged.append((item, safe_name, result))
            except RunCancelled:
                raise
            except Exception as exc:
                failed.append((item.package.name, str(exc)))
        raise_if_cancelled(stop_event, "Retrofit conversion cancelled.")
        _publish_staged_results([result for _item, _name, result in staged], output_root, stop_event=stop_event)

        processed: list[tuple[str, Path, RetrofitPathRepairSummary]] = []
        for item, safe_name, staged_result in staged:
            result = _published_result(staged_result, output_root)
            summary = dataclasses.replace(
                item.scan_summary,
                repaired_path_count=result.repaired_path_count,
                unresolved_path_count=result.unresolved_path_count,
                ambiguous_path_count=result.ambiguous_path_count,
                warnings=result.warnings,
            )
            output_name = f"{safe_name}_{item.manager_profile}"
            processed.append((output_name, result.package_root, summary))
        return RetrofitConversionResult(request.request_id, tuple(processed), tuple(failed))
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


class ModPackageRetrofitWorker(QObject):
    completed = Signal(int, str, object)
    failed = Signal(int, str, str)
    cancelled = Signal(int, str)
    progress = Signal(int, str, int, int, str)
    finished = Signal()

    def __init__(self, kind: str, request: RetrofitScanRequest | RetrofitConversionRequest) -> None:
        super().__init__()
        self.kind = str(kind)
        self.request = request
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        request_id = int(self.request.request_id)

        def report(current: int, total: int, detail: str) -> None:
            self.progress.emit(request_id, self.kind, max(0, int(current)), max(0, int(total)), str(detail))

        try:
            if self.kind == "scan" and isinstance(self.request, RetrofitScanRequest):
                result = scan_retrofit_request(self.request, stop_event=self.stop_event, progress=report)
            elif self.kind == "conversion" and isinstance(self.request, RetrofitConversionRequest):
                result = convert_retrofit_request(self.request, stop_event=self.stop_event, progress=report)
            else:
                raise ValueError(f"Unsupported retrofit task: {self.kind}")
            self.completed.emit(request_id, self.kind, result)
        except RunCancelled as exc:
            self.cancelled.emit(request_id, str(exc))
        except Exception as exc:
            self.failed.emit(request_id, self.kind, str(exc))
        finally:
            self.finished.emit()


__all__ = [
    "ModPackageRetrofitWorker",
    "RetrofitConversionItem",
    "RetrofitConversionRequest",
    "RetrofitConversionResult",
    "RetrofitScanRequest",
    "RetrofitScanResult",
    "collect_retrofittable_packages",
    "convert_retrofit_request",
    "next_available_retrofit_package_name",
    "scan_retrofit_request",
]
