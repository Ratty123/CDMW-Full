"""Regressions from the Browse Archive and Texture Editor audit (2026-11-20): previews."""

import os
import struct
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_binary_preview import _binary_sidecar_animation_keyframe_tables
from cdmw.core.archive_preview_result_builder import _archive_image_preview_path


def _dense_keyframe_data(tables: int, rows: int = 2000) -> bytes:
    rng = np.random.default_rng(0)
    parts = [rng.integers(0, 256, 1000, dtype=np.uint8).tobytes()]
    for _table in range(tables):
        for frame in range(rows):
            quaternion = rng.normal(size=4)
            quaternion /= np.linalg.norm(quaternion)
            parts.append(struct.pack("<H", frame + 1) + np.asarray(quaternion, dtype=np.float16).tobytes())
        parts.append(b"\xff\xff" * 7)
    return b"".join(parts)[:262_144]


def test_dense_animation_keyframe_scan_is_fast_and_finds_every_table():
    data = _dense_keyframe_data(12)
    started = time.monotonic()
    tables = _binary_sidecar_animation_keyframe_tables(data)
    elapsed = time.monotonic() - started
    # Three of these tables took 33 seconds before; twelve now take about one.
    assert elapsed < 8.0
    assert [(table["offset"], table["row_count"]) for table in tables] == [
        (1000 + index * 20014, 2000) for index in range(12)
    ]


def test_keyframe_scan_stops_at_its_time_budget():
    data = _dense_keyframe_data(12)
    started = time.monotonic()
    _binary_sidecar_animation_keyframe_tables(data, time_budget_seconds=0.05)
    assert time.monotonic() - started < 2.0


def test_run_length_encoded_tga_previews_through_a_png(tmp_path):
    QApplication.instance() or QApplication([])
    pixels = np.zeros((16, 16, 4), np.uint8)
    pixels[..., 0] = 200
    pixels[..., 3] = 255
    pixels[:8, :, 1] = 90
    source = tmp_path / "water_n.tga"
    Image.fromarray(pixels, "RGBA").save(source, compression="tga_rle")
    assert QImage(str(source)).isNull()  # Qt reads only uncompressed TGA
    preview, warning = _archive_image_preview_path(source)
    assert warning == ""
    assert preview is not None and preview.suffix == ".png"
    image = QImage(str(preview))
    assert not image.isNull() and image.width() == 16
    with Image.open(preview) as converted:
        assert np.array_equal(np.asarray(converted.convert("RGBA")), pixels)
    # A second request reuses the PNG.
    assert _archive_image_preview_path(source) == (preview, "")



def test_a_tga_preview_png_cut_short_is_never_left_in_the_cache(tmp_path, monkeypatch):
    pixels = np.zeros((8, 8, 4), np.uint8)
    pixels[..., 3] = 255
    source = tmp_path / "rle.tga"
    Image.fromarray(pixels, "RGBA").save(source, compression="tga_rle")
    real_save = Image.Image.save

    def interrupted(self, target, *args, **kwargs):
        target.write(b"\x89PNG")  # a few bytes in, then the write stops
        raise OSError("cancelled")

    monkeypatch.setattr(Image.Image, "save", interrupted)
    preview, warning = _archive_image_preview_path(source)
    assert preview is None and "cancelled" in warning
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rle.tga"]
    monkeypatch.setattr(Image.Image, "save", real_save)
    preview, warning = _archive_image_preview_path(source)
    assert warning == "" and preview is not None
    with Image.open(preview) as converted:
        assert converted.size == (8, 8)


def test_unreadable_tga_says_why_instead_of_an_empty_pane(tmp_path):
    source = tmp_path / "broken.tga"
    source.write_bytes(b"\x00\x00\x0a" + b"\x00" * 5)
    preview, warning = _archive_image_preview_path(source)
    assert preview is None
    assert "could not be decoded" in warning


def test_other_images_preview_from_their_own_file(tmp_path):
    source = tmp_path / "a.png"
    assert _archive_image_preview_path(source) == (source, "")


def test_media_preview_keeps_text_and_controls_at_their_own_height():
    from cdmw.ui.preview_widgets import MediaPreviewWidget

    QApplication.instance() or QApplication([])
    widget = MediaPreviewWidget("No media", theme_key="dark")
    try:
        widget.resize(600, 900)
        widget.show()
        if widget.player is None:
            return
        widget.player.setSource = lambda *_args: None
        widget.player.play = lambda: None
        detail = "\n".join(f"Line {index}" for index in range(8))
        widget.set_media("/tmp/sound.wem", media_kind="audio", detail_text=detail)
        QApplication.processEvents()
        assert widget.info_label.height() <= widget.info_label.sizeHint().height() + 4
        assert widget.play_button.geometry().top() < 300
        widget.set_media("/tmp/clip.mp4", media_kind="video", detail_text=detail)
        QApplication.processEvents()
        assert widget.info_label.text() == "Line 0"
        assert widget.info_label.toolTip() == detail
        assert widget.video_widget.height() > 600
    finally:
        widget.shutdown()
        widget.deleteLater()
        QApplication.processEvents()
