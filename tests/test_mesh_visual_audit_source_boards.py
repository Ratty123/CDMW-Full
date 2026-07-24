from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from tools.mesh_harness.visual_audit_source_boards import (
    _load_source_board_rgba,
)


def test_source_board_load_retries_a_transient_partial_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    preview = tmp_path / "decoded.png"
    Image.new("RGBA", (3, 2), (40, 80, 120, 200)).save(preview, "PNG")
    calls = 0
    delays: list[float] = []

    def flaky_open(path: Path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("broken data stream when reading image file")
        return Image.open(path)

    monkeypatch.setattr(
        "tools.mesh_harness.visual_audit_source_boards.time.sleep",
        delays.append,
    )
    image = _load_source_board_rgba(
        preview,
        image_type=SimpleNamespace(open=flaky_open),
    )

    assert calls == 2
    assert delays == [0.1]
    assert image.mode == "RGBA"
    assert image.size == (3, 2)
    assert image.getpixel((0, 0)) == (40, 80, 120, 200)
