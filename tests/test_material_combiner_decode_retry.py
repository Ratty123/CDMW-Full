from pathlib import Path

from cdmw.rendering import material_combiner_images as images


def test_dds_decode_miss_does_not_enter_publication_retry_loop(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "authoritative.dds"
    source.write_bytes(b"DDS " + bytes(124))
    delays: list[float] = []
    monkeypatch.setattr(images.time, "sleep", delays.append)

    result = images._image_from_file_bytes_with_retry(str(source))

    assert result.isNull()
    assert delays == []


def test_non_dds_decode_miss_keeps_publication_retry_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "publishing.png"
    source.write_bytes(b"not-yet-a-complete-image")
    delays: list[float] = []
    monkeypatch.setattr(images.time, "sleep", delays.append)

    result = images._image_from_file_bytes_with_retry(str(source))

    assert result.isNull()
    assert delays == list(images._IMAGE_BYTE_DECODE_RETRY_DELAYS_SECONDS)
