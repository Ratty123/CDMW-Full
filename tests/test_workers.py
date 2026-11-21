from __future__ import annotations

import unittest

from cdmw.workers.preview_workers import AlignmentOriginalTexturePreviewWorker, VisualPlacementPreviewWorker
from cdmw.workers.utility_workers import UtilityWorker


class WorkerFoundationTests(unittest.TestCase):
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

    def test_alignment_original_texture_worker_error_includes_traceback(self) -> None:
        errors: list[tuple[int, str, str]] = []

        def fail(_stop_event) -> tuple[object, int]:
            raise RuntimeError("resolver exploded")

        worker = AlignmentOriginalTexturePreviewWorker(9, fail)
        worker.error.connect(
            lambda request_id, message, traceback_text: errors.append(
                (request_id, message, traceback_text)
            )
        )

        worker.run()

        self.assertEqual(errors[0][:2], (9, "resolver exploded"))
        self.assertIn("RuntimeError: resolver exploded", errors[0][2])

if __name__ == "__main__":
    unittest.main()
