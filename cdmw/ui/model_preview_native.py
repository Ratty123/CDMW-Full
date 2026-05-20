from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget

from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.models import ModelPreviewData, PreparedModelPreviewData
from cdmw.ui.widgets import NativePreviewPanel


ARCHIVE_MODEL_RENDERER_D3D11 = "d3d11_native"
ARCHIVE_MODEL_RENDERER_DEFAULT = ARCHIVE_MODEL_RENDERER_D3D11
ARCHIVE_MODEL_RENDERER_LABELS = {
    ARCHIVE_MODEL_RENDERER_D3D11: "Native D3D11",
}


def normalize_archive_model_renderer_backend(value: object) -> str:
    return ARCHIVE_MODEL_RENDERER_D3D11


class ExperimentalNativeD3D11PreviewPanel(NativePreviewPanel):
    """Compatibility wrapper for old imports; live preview is native D3D11 only."""

    def __init__(self, title: str, *, theme_key: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(title, theme_key=theme_key)
        if parent is not None:
            self.setParent(parent)

    def set_model(self, model: ModelPreviewData) -> None:
        prepared_model, prepared_preview = prepare_model_preview(model)
        self.set_prepared_model(prepared_model, prepared_preview)

    def set_prepared_model(
        self,
        model: object,
        prepared_preview: Optional[PreparedModelPreviewData] = None,
        **kwargs: object,
    ) -> None:
        super().set_prepared_model(model, prepared_preview, **kwargs)


__all__ = [
    "ARCHIVE_MODEL_RENDERER_D3D11",
    "ARCHIVE_MODEL_RENDERER_DEFAULT",
    "ARCHIVE_MODEL_RENDERER_LABELS",
    "ExperimentalNativeD3D11PreviewPanel",
    "normalize_archive_model_renderer_backend",
]
