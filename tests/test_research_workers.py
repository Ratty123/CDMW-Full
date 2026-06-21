from __future__ import annotations

from cdmw.ui.research import workers


def test_research_workers_export_background_worker_classes() -> None:
    exported = set(workers.__all__)

    assert {
        "ReferenceResolveWorker",
        "ResearchRefreshWorker",
        "UIConstraintRefreshWorker",
        "UnknownResolverPreviewWorker",
    } <= exported

    for name in exported:
        worker_type = getattr(workers, name)
        assert hasattr(worker_type, "run")
        assert hasattr(worker_type, "stop")


def test_shutdown_thread_requests_interruption_and_quit() -> None:
    class FakeThread:
        def __init__(self) -> None:
            self.interrupted = False
            self.quit_called = False

        def requestInterruption(self) -> None:
            self.interrupted = True

        def quit(self) -> None:
            self.quit_called = True

    thread = FakeThread()
    workers.shutdown_thread(thread)  # type: ignore[arg-type]

    assert thread.interrupted is True
    assert thread.quit_called is True

    workers.shutdown_thread(None)
