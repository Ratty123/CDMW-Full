"""The Texture Editor reads a DDS as raw pixels: same pixels as the PNG route, and every
failure falls back to that route."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cdmw.core import texture_editor_project_io as project_io
from cdmw.core import texture_native, texture_native_rgba
from cdmw.models import RunCancelled


def _pixels(width: int = 8, height: int = 4) -> np.ndarray:
    values = np.arange(width * height * 4, dtype=np.uint32).reshape(height, width, 4)
    pixels = ((values * 37 + 11) % 256).astype(np.uint8)
    pixels[0, 0, 3] = 0      # fully transparent, with colour underneath
    pixels[0, 1, 3] = 128
    return pixels


def _write_dds(path: Path, pixels: np.ndarray) -> Path:
    height, width = pixels.shape[:2]
    pixel_format = struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32, 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)
    header = struct.pack("<II", 124, 0x100F) + struct.pack("<IIIII", height, width, width * 4, 0, 1)
    header += b"\0" * 44 + pixel_format + struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    assert len(header) == 124
    path.write_bytes(b"DDS " + header + pixels.tobytes())
    return path


def _raw_file(pixels: np.ndarray) -> bytes:
    height, width = pixels.shape[:2]
    return struct.pack("<8sIIIIQ", b"CDMWRGBA", 1, width, height, 4, width * height * 4) + pixels.tobytes()


class _FakeHelper:
    """Stands in for cd-texture-dx: writes what `writer` returns and a report."""

    def __init__(self, pixels: np.ndarray, *, writer, echo: bool = True, status: str = "decoded") -> None:
        self.pixels, self.writer, self.echo, self.status = pixels, writer, echo, status
        self.commands: list[list[str]] = []
        self.jobs: list[dict] = []
        self.staging: list[Path] = []

    def __call__(self, command, **_kwargs):
        self.commands.append([str(part) for part in command])
        job_path, report_path = Path(command[2]), Path(command[3])
        job = json.loads(job_path.read_text(encoding="utf-8"))["jobs"][0]
        self.jobs.append(job)
        self.staging.append(job_path.parent)
        self.writer(Path(job["output"]), self.pixels)
        height, width = self.pixels.shape[:2]
        item = {"status": self.status, "prepared_width": width, "prepared_height": height}
        if self.echo:
            item["output_container"] = job.get("output_container", "png")
        report_path.write_text(json.dumps({"status": "ok", "items": [item]}), encoding="utf-8")
        return 0, "", ""


@pytest.fixture()
def helper_binary(tmp_path, monkeypatch):
    binary = tmp_path / "cd-texture-dx.exe"
    binary.write_bytes(b"not a real helper")
    monkeypatch.setattr(texture_native, "find_directxtex_texture_binary", lambda: binary)
    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))
    return binary


def _decode(tmp_path, monkeypatch, helper) -> tuple:
    source = _write_dds(tmp_path / "source.dds", _pixels())
    monkeypatch.setattr(texture_native_rgba, "run_process_with_cancellation", helper)
    staging_parent = tmp_path / "document"
    return texture_native_rgba.decode_dds_rgba8_with_directxtex(source, staging_parent=staging_parent), staging_parent


def test_raw_pixels_are_read_as_the_helper_wrote_them(tmp_path, monkeypatch, helper_binary) -> None:
    helper = _FakeHelper(_pixels(), writer=lambda path, pixels: path.write_bytes(_raw_file(pixels)))

    pixels, staging_parent = _decode(tmp_path, monkeypatch, helper)

    assert np.array_equal(pixels, _pixels())
    assert pixels.flags.writeable
    assert helper.commands[0][0] == str(helper_binary) and helper.commands[0][1] == "batch-preview-json"
    job = helper.jobs[0]
    assert job["output_container"] == "rgba8_raw"
    assert (job["max_dimension"], job["requested_mip"], job["slot"], job["output_pixel_type"]) == (0, 0, "base", "rgba8")
    assert not helper.staging[0].exists(), "the staged file must not outlive the call"
    assert list(staging_parent.iterdir()) == []


def test_an_older_helper_that_writes_a_png_is_decoded_once(tmp_path, monkeypatch, helper_binary) -> None:
    helper = _FakeHelper(
        _pixels(), echo=False, writer=lambda path, pixels: Image.fromarray(pixels, "RGBA").save(path, format="PNG")
    )

    pixels, _staging_parent = _decode(tmp_path, monkeypatch, helper)

    assert np.array_equal(pixels, _pixels())
    assert len(helper.commands) == 1


@pytest.mark.parametrize(
    "writer",
    [
        lambda path, pixels: path.write_bytes(_raw_file(pixels)[:-5]),
        lambda path, pixels: path.write_bytes(b"NOTCDMW!" + _raw_file(pixels)[8:]),
        lambda path, pixels: path.write_bytes(_raw_file(pixels[:, :-1])),
        lambda path, pixels: path.write_bytes(_raw_file(pixels) + b"extra"),
        lambda path, pixels: None,
    ],
    ids=["truncated", "wrong-magic", "other-size", "trailing-bytes", "no-file"],
)
def test_a_file_that_is_not_exactly_as_reported_is_refused(tmp_path, monkeypatch, helper_binary, writer) -> None:
    pixels, _staging_parent = _decode(tmp_path, monkeypatch, _FakeHelper(_pixels(), writer=writer))

    assert pixels is None


def test_a_failed_decode_and_a_missing_helper_are_refused(tmp_path, monkeypatch, helper_binary) -> None:
    raw = lambda path, pixels: path.write_bytes(_raw_file(pixels))  # noqa: E731
    assert _decode(tmp_path, monkeypatch, _FakeHelper(_pixels(), writer=raw, status="error"))[0] is None

    def crashing(_command, **_kwargs):
        raise OSError("helper could not start")

    assert _decode(tmp_path, monkeypatch, crashing)[0] is None
    monkeypatch.setattr(texture_native, "find_directxtex_texture_binary", lambda: None)
    assert _decode(tmp_path, monkeypatch, _FakeHelper(_pixels(), writer=raw))[0] is None


def test_cancelling_is_not_swallowed(tmp_path, monkeypatch, helper_binary) -> None:
    def cancelled(_command, **_kwargs):
        raise RunCancelled("stopped")

    with pytest.raises(RunCancelled):
        _decode(tmp_path, monkeypatch, cancelled)


def test_a_png_already_decoded_for_another_view_is_left_to_the_png_route(tmp_path, monkeypatch, helper_binary) -> None:
    helper = _FakeHelper(_pixels(), writer=lambda path, pixels: path.write_bytes(_raw_file(pixels)))
    monkeypatch.setattr(texture_native, "_cached_preview_is_valid", lambda _path: True)

    pixels, _staging_parent = _decode(tmp_path, monkeypatch, helper)

    assert pixels is None and helper.commands == []


def test_the_editor_opens_a_dds_from_raw_pixels_and_falls_back_to_the_png_route(tmp_path, monkeypatch) -> None:
    source = _write_dds(tmp_path / "plate_d.dds", _pixels())
    normalized: list[Path] = []

    def normalize(path, *, output_dir, output_stem=""):
        normalized.append(Path(path))
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{output_stem}.png"
        Image.fromarray(_pixels(), "RGBA").save(target, format="PNG")
        return target

    monkeypatch.setattr(project_io, "normalize_texture_editor_source_to_png", normalize)
    monkeypatch.setattr(project_io, "decode_dds_rgba8_with_directxtex", lambda _path: _pixels())

    document, layers, png = project_io.create_texture_editor_document_from_source(source, workspace_root=tmp_path / "a")

    assert png is None and normalized == []
    assert (document.width, document.height) == (8, 4)
    assert np.array_equal(layers[document.active_layer_id], _pixels())

    monkeypatch.setattr(project_io, "decode_dds_rgba8_with_directxtex", lambda _path: None)

    document, layers, png = project_io.create_texture_editor_document_from_source(source, workspace_root=tmp_path / "b")

    assert png is not None and png.is_file() and normalized == [source.resolve()]
    assert np.array_equal(layers[document.active_layer_id], _pixels())


def test_a_source_that_is_not_a_dds_never_asks_for_raw_pixels(tmp_path, monkeypatch) -> None:
    source = tmp_path / "paint.png"
    Image.fromarray(_pixels(), "RGBA").save(source, format="PNG")
    monkeypatch.setattr(
        project_io, "decode_dds_rgba8_with_directxtex",
        lambda *_args, **_kwargs: pytest.fail("a PNG source must not go to the DDS helper"),
    )

    document, layers, png = project_io.create_texture_editor_document_from_source(source, workspace_root=tmp_path / "ws")

    assert png is not None and np.array_equal(layers[document.active_layer_id], _pixels())


def test_the_real_helper_gives_the_same_pixels_both_ways(tmp_path, monkeypatch) -> None:
    from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png

    if texture_native.find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built here")
    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))
    source = _write_dds(tmp_path / "source.dds", _pixels(64, 32))

    raw = texture_native_rgba.decode_dds_rgba8_with_directxtex(source)
    if raw is None:
        pytest.skip("this cd-texture-dx refused the texture")
    with Image.open(ensure_dds_display_preview_png(source, max_dimension=0)) as image:
        from_png = np.asarray(image.convert("RGBA"), dtype=np.uint8)

    assert np.array_equal(raw, from_png)
    assert np.array_equal(raw, _pixels(64, 32))
    staging = tmp_path / "cache" / "preview" / "textures" / "directxtex" / "raw-pixels"
    assert not staging.exists() or list(staging.iterdir()) == [], "no raw file is left in the temporary cache"
