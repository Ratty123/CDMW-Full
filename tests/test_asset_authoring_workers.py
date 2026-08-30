from __future__ import annotations

import unittest
from pathlib import Path
from typing import Mapping

from cdmw.workers.asset_authoring_workers import OpenImageIOTaskWorker


class _FakeOpenImageIOService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], Mapping[str, object] | None, float | None]] = []

    def run_openimageio_metadata(
        self,
        source_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        self.calls.append(("metadata", (source_path,), configured_paths, timeout_s))
        return {"status": "ok", "operation": "metadata", "metadata": {"width": 8, "height": 4}}

    def run_openimageio_convert(
        self,
        source_path: Path | str,
        output_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        self.calls.append(("convert", (source_path, output_path), configured_paths, timeout_s))
        return {"status": "ok", "operation": "convert", "output_path": str(output_path)}

    def run_openimageio_diff(
        self,
        left_path: Path | str,
        right_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        self.calls.append(("diff", (left_path, right_path), configured_paths, timeout_s))
        return {"status": "different", "operation": "diff", "returncode": 1}


class AssetAuthoringWorkerTests(unittest.TestCase):
    def test_openimageio_worker_routes_metadata_convert_and_diff(self) -> None:
        service = _FakeOpenImageIOService()
        configured = {"openimageio": Path("C:/tools/oiiotool.exe")}
        cases = (
            ("metadata", (Path("source.exr"),)),
            ("convert", (Path("source.exr"), Path("out/source.png"))),
            ("diff", (Path("out/source.png"), Path("rebuilt.png"))),
        )
        completed: list[dict[str, object]] = []
        errors: list[str] = []
        finished: list[bool] = []

        for operation, paths in cases:
            worker = OpenImageIOTaskWorker(
                operation,
                paths,
                configured_paths=configured,
                timeout_s=12.5,
                service=service,  # type: ignore[arg-type]
            )
            worker.completed.connect(completed.append)
            worker.error.connect(errors.append)
            worker.finished.connect(lambda: finished.append(True))
            worker.run()

        self.assertEqual([], errors)
        self.assertEqual(["metadata", "convert", "diff"], [str(result["operation"]) for result in completed])
        self.assertEqual(["metadata", "convert", "diff"], [call[0] for call in service.calls])
        self.assertTrue(all(call[2] == configured and call[3] == 12.5 for call in service.calls))
        self.assertEqual([True, True, True], finished)

    def test_openimageio_worker_cancel_before_run_suppresses_service_call(self) -> None:
        service = _FakeOpenImageIOService()
        worker = OpenImageIOTaskWorker("metadata", (Path("source.exr"),), service=service)  # type: ignore[arg-type]
        completed: list[object] = []
        cancelled: list[str] = []
        finished: list[bool] = []
        worker.completed.connect(completed.append)
        worker.cancelled.connect(cancelled.append)
        worker.finished.connect(lambda: finished.append(True))

        worker.stop()
        worker.run()

        self.assertEqual([], service.calls)
        self.assertEqual([], completed)
        self.assertEqual(["OpenImageIO task stopped."], cancelled)
        self.assertEqual([True], finished)

    def test_openimageio_worker_reports_invalid_operation(self) -> None:
        worker = OpenImageIOTaskWorker("unsupported", ())
        errors: list[str] = []
        finished: list[bool] = []
        worker.error.connect(errors.append)
        worker.finished.connect(lambda: finished.append(True))

        worker.run()

        self.assertEqual(["Unsupported OpenImageIO worker operation: unsupported"], errors)
        self.assertEqual([True], finished)


if __name__ == "__main__":
    unittest.main()
