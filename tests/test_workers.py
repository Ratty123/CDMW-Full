from __future__ import annotations

import unittest
from pathlib import Path

from cdmw.workers.cancellation import CancellationToken
from cdmw.workers.d3d11_package_workers import ArchiveNativePreviewPrefetchWorker
from cdmw.workers.preview_workers import AlignmentOriginalTexturePreviewWorker, VisualPlacementPreviewWorker
from cdmw.workers.qt_worker_runner import run_worker_task
from cdmw.workers.results import WorkerFailure, WorkerSuccess
from cdmw.workers.utility_workers import UtilityWorker


class WorkerFoundationTests(unittest.TestCase):
    def test_worker_task_returns_success_with_elapsed_time(self) -> None:
        result = run_worker_task(lambda: "ok")

        self.assertIsInstance(result, WorkerSuccess)
        self.assertEqual(result.value, "ok")
        self.assertGreaterEqual(result.elapsed_ms, 0.0)

    def test_worker_task_returns_failure_with_traceback(self) -> None:
        def fail() -> str:
            raise ValueError("bad")

        result = run_worker_task(fail)

        self.assertIsInstance(result, WorkerFailure)
        self.assertEqual(result.exception_type, "ValueError")
        self.assertIn("ValueError: bad", result.traceback_text)

    def test_cancellation_token_raises_after_stop_requested(self) -> None:
        token = CancellationToken()

        self.assertFalse(token.is_stop_requested())
        token.request_stop()
        self.assertTrue(token.is_stop_requested())
        with self.assertRaises(RuntimeError):
            token.raise_if_cancelled()

    def test_utility_worker_runs_callable_and_emits_result(self) -> None:
        messages: list[str] = []
        results: list[object] = []
        finished: list[bool] = []

        def task(log) -> str:
            log("running")
            return "ok"

        worker = UtilityWorker(task)
        worker.log_message.connect(messages.append)
        worker.completed.connect(results.append)
        worker.finished.connect(lambda: finished.append(True))

        worker.run()

        self.assertEqual(messages, ["running"])
        self.assertEqual(results, ["ok"])
        self.assertEqual(finished, [True])

    def test_visual_preview_worker_keeps_request_id_with_result(self) -> None:
        results: list[tuple[int, object]] = []
        finished: list[int] = []

        worker = VisualPlacementPreviewWorker(42, lambda: {"ready": True})
        worker.completed.connect(lambda request_id, result: results.append((request_id, result)))
        worker.finished.connect(finished.append)

        worker.run()

        self.assertEqual(results, [(42, {"ready": True})])
        self.assertEqual(finished, [42])

    def test_alignment_original_texture_worker_emits_batches_and_elapsed_ms(self) -> None:
        results: list[tuple[int, object, int, float]] = []
        finished: list[bool] = []

        worker = AlignmentOriginalTexturePreviewWorker(7, lambda _stop_event: ("model", 3))
        worker.completed.connect(
            lambda request_id, model, batches, elapsed_ms: results.append(
                (request_id, model, batches, elapsed_ms)
            )
        )
        worker.finished.connect(lambda: finished.append(True))

        worker.run()

        self.assertEqual(len(results), 1)
        request_id, model, batches, elapsed_ms = results[0]
        self.assertEqual((request_id, model, batches), (7, "model", 3))
        self.assertGreaterEqual(elapsed_ms, 0.0)
        self.assertEqual(finished, [True])

    def test_archive_native_prefetch_worker_is_noop_when_cache_mode_off(self) -> None:
        finished: list[bool] = []

        def validate_package(_path):
            raise AssertionError("off-mode prefetch should not validate packages")

        worker = ArchiveNativePreviewPrefetchWorker(
            (),
            None,
            Path("cache"),
            None,
            "off",
            0,
            0,
            validate_package=validate_package,
        )
        worker.finished.connect(lambda: finished.append(True))

        worker.run()

        self.assertEqual(finished, [True])


if __name__ == "__main__":
    unittest.main()
