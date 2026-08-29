from tools.benchmark_archive_entry_store import _reduction_percent


def test_archive_entry_store_reduction_percent_is_deterministic() -> None:
    assert _reduction_percent(100.0, 40.0) == 60.0
    assert _reduction_percent(0.0, 0.0) == 0.0
