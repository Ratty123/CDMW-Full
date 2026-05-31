from __future__ import annotations


ARCHIVE_MODEL_RENDERER_D3D11 = "d3d11_native"
ARCHIVE_MODEL_RENDERER_DEFAULT = ARCHIVE_MODEL_RENDERER_D3D11
ARCHIVE_MODEL_RENDERER_LABELS = {
    ARCHIVE_MODEL_RENDERER_D3D11: "Native D3D11",
}


def normalize_archive_model_renderer_backend(value: object) -> str:
    return ARCHIVE_MODEL_RENDERER_D3D11


__all__ = [
    "ARCHIVE_MODEL_RENDERER_D3D11",
    "ARCHIVE_MODEL_RENDERER_DEFAULT",
    "ARCHIVE_MODEL_RENDERER_LABELS",
    "normalize_archive_model_renderer_backend",
]
