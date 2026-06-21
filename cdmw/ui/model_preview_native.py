from __future__ import annotations


ARCHIVE_MODEL_RENDERER_D3D11 = "d3d11_native"
ARCHIVE_MODEL_RENDERER_DEFAULT = ARCHIVE_MODEL_RENDERER_D3D11
ARCHIVE_MODEL_RENDERER_LABELS = {
    ARCHIVE_MODEL_RENDERER_D3D11: "Native D3D11",
}
ARCHIVE_MODEL_RENDERER_BACKENDS = frozenset({ARCHIVE_MODEL_RENDERER_D3D11})


def normalize_archive_model_renderer_backend(value: object) -> str:
    key = str(value or "").strip().lower()
    if key in {"d3d11", "direct3d11", "native_d3d11", ARCHIVE_MODEL_RENDERER_D3D11}:
        return ARCHIVE_MODEL_RENDERER_D3D11
    return ARCHIVE_MODEL_RENDERER_DEFAULT


__all__ = [
    "ARCHIVE_MODEL_RENDERER_BACKENDS",
    "ARCHIVE_MODEL_RENDERER_D3D11",
    "ARCHIVE_MODEL_RENDERER_DEFAULT",
    "ARCHIVE_MODEL_RENDERER_LABELS",
    "normalize_archive_model_renderer_backend",
]
