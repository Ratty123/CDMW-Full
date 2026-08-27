from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from cdmw.ui.themes import UI_THEME_SCHEMES, build_app_palette
from tests.test_translation_studio import ENGLISH, KOREAN
from tools.translation_studio.catalogue import attach_reference, load_catalogue
from tools.translation_studio.table_model import TranslationTableModel


def _relative_luminance(color: QColor) -> float:
    channels = (color.redF(), color.greenF(), color.blueF())
    linear = tuple(
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: QColor, background: QColor) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _composite(foreground: QColor, background: QColor) -> QColor:
    alpha = foreground.alphaF()
    return QColor.fromRgbF(
        foreground.redF() * alpha + background.redF() * (1.0 - alpha),
        foreground.greenF() * alpha + background.greenF() * (1.0 - alpha),
        foreground.blueF() * alpha + background.blueF() * (1.0 - alpha),
    )


def test_edited_row_mark_stays_readable_in_every_theme() -> None:
    app = QApplication.instance() or QApplication([])
    catalogue = attach_reference(load_catalogue(ENGLISH, "eng"), KOREAN, "kor")
    model = TranslationTableModel(catalogue)
    model.setData(model.index(0, 2), "Changed.", Qt.EditRole)
    edit_mark = model.data(model.index(0, 0), Qt.BackgroundRole)
    assert isinstance(edit_mark, QColor)
    assert edit_mark.alpha() < 255

    for theme_key in UI_THEME_SCHEMES:
        palette = build_app_palette(theme_key)
        painted_background = _composite(
            edit_mark,
            palette.color(QPalette.ColorRole.Base),
        )
        assert _contrast_ratio(
            palette.color(QPalette.ColorRole.Text),
            painted_background,
        ) >= 4.5, theme_key
    assert app is QApplication.instance()
