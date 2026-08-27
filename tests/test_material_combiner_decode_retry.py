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


def test_path_reader_closes_internal_device_before_retry(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "publishing.png"
    source.write_bytes(b"not-yet-a-complete-image")
    closed: list[bool] = []

    class FakeDevice:
        def close(self) -> None:
            closed.append(True)

    class FakeReader:
        def __init__(self, _source_path: str) -> None:
            self._device = FakeDevice()

        def setAutoTransform(self, _enabled: bool) -> None:
            return None

        def read(self):
            return images.QImage()

        def device(self):
            return self._device

    monkeypatch.setattr(images, "QImageReader", FakeReader)
    monkeypatch.setattr(images, "_image_from_file_bytes_with_retry", lambda _path: images.QImage())

    result = images._image_reader(str(source))

    assert result.isNull()
    assert closed == [True]
