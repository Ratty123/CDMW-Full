"""New Item Studio: the small shared vocabulary its panels are built from.

Four tones say what a line means before it is read: green is settled, amber wants a
decision or a check, red blocks the plan, blue differs from the template. A step's page
opens with a bold title and one plain sentence of purpose; the background that explains
*why* lives behind a Details toggle, not in the reader's way.
"""

from __future__ import annotations

from html import escape
from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QTableWidget, QToolButton, QVBoxLayout, QWidget

__all__ = [
    "BLOCK",
    "EDIT",
    "OK",
    "WARN",
    "DetailsToggle",
    "NoteLabel",
    "STEP_STYLE",
    "compact_table_height",
    "intro_label",
    "note",
    "tinted",
    "tone_color",
]

#: settled / done
OK = "ok"
#: needs a decision or an in-game check
WARN = "warn"
#: blocks the plan
BLOCK = "block"
#: differs from the template
EDIT = "edit"

_COLORS = {
    OK: "#2e9e4f",
    WARN: "#d18a00",
    BLOCK: "#d64545",
    EDIT: "#3d7bd9",
}

#: the step pages: a bold title on the group box, room around the content
STEP_STYLE = (
    "QGroupBox#new_item_step { font-weight: bold; margin-top: 14px; }"
    "QGroupBox#new_item_step::title { subcontrol-origin: margin; left: 4px; padding: 0 4px; font-size: 11pt; }"
    "QGroupBox#new_item_step QGroupBox { font-weight: normal; }"
    "QLabel#new_item_intro { color: palette(dark); }"
    "QLabel#new_item_details { color: palette(dark); }"
)


def note(text: str, tone: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """One line for `NoteLabel.set_lines`: the text and its tone (a sink the
    localisation extractor reads, so the line stays translatable)."""

    return str(text), tone


def tone_color(tone: Optional[str]) -> str:
    """The hex colour of a tone, "" for none."""

    return _COLORS.get(str(tone or ""), "")


def tinted(text: str, tone: Optional[str] = None, *, bold: bool = False) -> str:
    """`text` as rich text in the tone's colour (escaped; plain when there is no tone)."""

    body = escape(str(text))
    if bold:
        body = f"<b>{body}</b>"
    colour = tone_color(tone)
    return f'<span style="color:{colour}">{body}</span>' if colour else body


def intro_label(text: str) -> QLabel:
    """The one plain sentence under a step's title: what this step decides."""

    label = QLabel(text)
    label.setObjectName("new_item_intro")
    label.setWordWrap(True)
    return label


class NoteLabel(QLabel):
    """A word-wrapped line that carries a tone: `set_note("...", WARN)`."""

    def __init__(self, text: str = "", tone: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.set_note(text, tone)

    def set_note(self, text: str, tone: Optional[str] = None) -> None:
        self._plain = str(text or "")
        self._tone = tone
        self.setText(tinted(self._plain, tone) if self._plain else "")
        self.setVisible(bool(self._plain))

    def set_lines(self, lines) -> None:
        """Several (text, tone) lines, one per row."""

        rows = [tinted(text, tone) for text, tone in lines if str(text or "")]
        self._plain = "\n".join(str(text) for text, _tone in lines)
        self.setText("<br>".join(rows))
        self.setVisible(bool(rows))

    def plain_text(self) -> str:
        return self._plain


class DetailsToggle(QWidget):
    """A `Details` arrow that folds a paragraph of background away until asked for."""

    def __init__(self, text: str, *, title: str = "Details", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setArrowType(Qt.RightArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setAutoRaise(True)
        self.toggle.toggled.connect(self._toggled)
        layout.addWidget(self.toggle, 0, Qt.AlignLeft)
        self.body = QLabel(text)
        self.body.setObjectName("new_item_details")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setVisible(False)
        layout.addWidget(self.body)

    def _toggled(self, checked: bool) -> None:
        self.toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.body.setVisible(bool(checked))

    def set_text(self, text: str) -> None:
        self.body.setText(str(text))


def compact_table_height(table: QTableWidget, rows: int, *, minimum_rows: int = 2, maximum_rows: int = 12) -> None:
    """Size a table to its rows (between `minimum_rows` and `maximum_rows`), so a
    two-level ladder is two lines tall and not a field of white."""

    shown = max(minimum_rows, min(maximum_rows, int(rows)))
    row_height = table.verticalHeader().defaultSectionSize() or 24
    header = table.horizontalHeader().height() if not table.horizontalHeader().isHidden() else 0
    frame = 2 * table.frameWidth() + 4
    height = header + shown * row_height + frame
    if table.horizontalScrollBar().isVisible():
        height += table.horizontalScrollBar().height()
    table.setMinimumHeight(height)
    table.setMaximumHeight(height + (0 if rows > maximum_rows else 0))
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
