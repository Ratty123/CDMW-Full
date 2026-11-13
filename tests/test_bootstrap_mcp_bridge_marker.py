"""A packaged --mcp-bridge marks its unpacked folder before it runs (packaging review, 2026-11-13)."""

from __future__ import annotations

from cdmw.app import bootstrap


def test_the_bridge_marks_its_runtime_folder_before_it_runs(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(bootstrap, "write_current_pyinstaller_runtime_marker", lambda: calls.append("marker"))
    monkeypatch.setattr("cdmw.mcp.bridge.run_bridge", lambda: calls.append("bridge") or 0)
    assert bootstrap.main(["--mcp-bridge"]) == 0
    assert calls == ["marker", "bridge"]
