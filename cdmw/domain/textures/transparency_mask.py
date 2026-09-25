"""Immutable, owned greyscale pixels; white means more transparent."""
from dataclasses import dataclass, field
import base64
import hashlib
import zlib


@dataclass(frozen=True, slots=True)
class TransparencyMask:
    width: int
    height: int
    pixels: bytes = field(repr=False)
    digest: str = field(init=False)

    def __post_init__(self):
        if (type(self.width) is not int or type(self.height) is not int
                or not 1 <= self.width <= 8192 or not 1 <= self.height <= 8192
                or self.width * self.height > 16_777_216
                or not isinstance(self.pixels, bytes) or len(self.pixels) != self.width * self.height):
            raise ValueError("Transparency masks require 8-bit pixels, at most 8192 per side and 16 megapixels.")
        object.__setattr__(self, "digest", hashlib.sha256(self.pixels).hexdigest())

    def to_dict(self):
        return {"width": self.width, "height": self.height,
                "pixels": base64.b64encode(zlib.compress(self.pixels)).decode("ascii")}

    @classmethod
    def from_dict(cls, value):
        try:
            if not isinstance(value, dict) or set(value) != {"width", "height", "pixels"}:
                raise ValueError("Invalid transparency mask.")
            width, height = value["width"], value["height"]
            if (type(width) is not int or type(height) is not int
                    or not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height > 16_777_216):
                raise ValueError("Invalid transparency mask dimensions.")
            packed = value["pixels"]
            if not isinstance(packed, str) or len(packed) > 24_000_000:
                raise ValueError("Invalid transparency mask pixels.")
            decoder = zlib.decompressobj()
            pixels = decoder.decompress(base64.b64decode(packed, validate=True), width * height + 1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError("Invalid transparency mask compression.")
            return cls(width, height, pixels)
        except (TypeError, KeyError, zlib.error) as exc:
            raise ValueError("Invalid transparency mask.") from exc
