from __future__ import annotations

import io
from pathlib import Path

from PIL import Image


def valid_image_bytes(suffix: str = ".png") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1, 1), (64, 128, 192)).save(
        output, "JPEG" if suffix.lower() in {".jpg", ".jpeg"} else "PNG"
    )
    return output.getvalue()


def write_valid_image(path: Path) -> None:
    path.write_bytes(valid_image_bytes(path.suffix))
