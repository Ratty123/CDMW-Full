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
    "elided",
    "intro_label",
    "muted_color",
    "note",
    "step_style",
    "tinted",
    "tone_color",
    "wrap_for_height",
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

#: Guided pages use the header as their only title. Internal group boxes retain their
#: ordinary captions, while the outer compatibility QGroupBox is visually neutral.
STEP_STYLE = (
    "QGroupBox#new_item_step { font-weight: normal; }"
    "QGroupBox#new_item_step QGroupBox { font-weight: normal; }"
    "QLabel#new_item_intro { color: %(muted)s; }"
    "QLabel#new_item_details { color: %(muted)s; }"
)


def muted_color(palette) -> str:
    """A secondary-text colour readable on this palette: the text colour pulled part of the
    way toward the window colour, so it is grey on light and light grey on dark."""

    from PySide6.QtGui import QPalette

    text = palette.color(QPalette.ColorRole.WindowText)
    window = palette.color(QPalette.ColorRole.Window)
    mix = 0.62
    return "#%02x%02x%02x" % (
        int(text.red() * mix + window.red() * (1 - mix)),
        int(text.green() * mix + window.green() * (1 - mix)),
        int(text.blue() * mix + window.blue() * (1 - mix)),
    )


def step_style(palette) -> str:
    """Professional guided-workspace roles, exact on dark and palette-derived elsewhere."""

    from PySide6.QtGui import QPalette

    window = palette.color(QPalette.ColorRole.Window)
    dark = window.lightness() < 128
    background = "#16191c" if dark else window.name()
    panel = "#1d2125" if dark else palette.color(QPalette.ColorRole.Base).name()
    border = "#343a40" if dark else palette.color(QPalette.ColorRole.Mid).name()
    active = "#078de5" if dark else palette.color(QPalette.ColorRole.Highlight).name()
    text = palette.color(QPalette.ColorRole.WindowText).name()
    muted = muted_color(palette)
    return (STEP_STYLE % {"muted": muted}) + f"""
        QWidget#new_item_steps, QStackedWidget {{ background: {background}; }}
        QGroupBox#new_item_step[guidedPage="true"] {{ border: none; margin-top: 0; padding: 0; }}
        QTabWidget#new_item_perks_effects_tabs::pane {{ border: 1px solid {border}; background: {background}; }}
        QTabWidget#new_item_perks_effects_tabs QTabBar::tab {{ min-height: 30px; padding: 0 20px; border: none; color: {muted}; }}
        QTabWidget#new_item_perks_effects_tabs QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {active}; }}
        QFrame#effect_library_panel, QWidget#effect_inspector {{ background: {panel}; }}
        QWidget#effect_viewport_panel {{ background: {background}; }}
        QScrollArea#effect_inspector_scroll {{ border: none; background: {panel}; }}
        QSplitter#effect_workspace_splitter::handle, QSplitter#effect_placement_splitter::handle {{ background: {border}; width: 1px; }}
        QLabel#effect_library_heading, QLabel#effect_inspector_heading {{ font-weight: 600; color: {text}; }}
        QLabel#effect_compatibility {{ color: {muted}; }}
        QLabel#effect_visual_caution {{ color: #d18a00; border-top: 1px solid {border}; }}
        QTableView#effect_library {{ border: 1px solid {border}; background: {panel}; alternate-background-color: {background}; outline: none; }}
        QTableView#effect_library::item {{ border: none; padding: 0 4px; }}
        QTableView#effect_library::item:hover {{ background: {border}; }}
        QTableView#effect_library::item:selected {{ color: white; background: {active}; }}
        QTableView#effect_library QHeaderView::section {{ min-height: 20px; padding: 0 4px; font-weight: normal; }}
        QLineEdit#effect_search {{ min-height: 30px; border: 1px solid {border}; padding: 0 8px; background: {background}; }}
        QToolButton[effectChip="true"] {{ min-height: 24px; padding: 0 5px; border: 1px solid {border}; border-radius: 4px; }}
        QToolButton[effectChip="true"]:checked {{ color: white; background: {active}; border-color: {active}; }}
        QPushButton[effectToolbarButton="true"] {{ min-height: 30px; padding: 0 2px; }}
        QGroupBox#new_item_step QLineEdit, QGroupBox#new_item_step QComboBox,
        QGroupBox#new_item_step QDoubleSpinBox, QGroupBox#new_item_step QPushButton {{ min-height: 30px; }}
        QLabel#new_item_step_counter {{ color: {muted}; }}
    """


def elided(text: str, max_chars: int) -> str:
    """`text` shortened in the middle to `max_chars` characters (an ellipsis in the gap)."""

    text = str(text)
    limit = max(12, int(max_chars))
    if len(text) <= limit:
        return text
    head = (limit - 1) * 2 // 3
    tail = limit - 1 - head
    return text[:head] + "…" + text[-tail:]


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


def wrap_for_height(label: QLabel) -> QLabel:
    """Let a word-wrapped label ask its layout for the height its text really needs.

    A wrapped QLabel reports a one-line minimum unless its size policy says the height
    depends on the width. Without this the panels reserve one line for a sentence that
    draws three, the deficit adds up down the panel, and the widgets at the bottom are
    drawn over the table above them.
    """

    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label


def intro_label(text: str) -> QLabel:
    """The one plain sentence under a step's title: what this step decides."""

    label = QLabel(text)
    label.setObjectName("new_item_intro")
    label.setWordWrap(True)
    return wrap_for_height(label)


class NoteLabel(QLabel):
    """A word-wrapped line that carries a tone: `set_note("...", WARN)`."""

    def __init__(self, text: str = "", tone: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.set_note(text, tone)

    def set_note(self, text: str, tone: Optional[str] = None) -> None:
        self._plain = str(text or "")
        self._tone = tone
        self.updateGeometry()
        self.setText(tinted(self._plain, tone) if self._plain else "")
        self.setVisible(bool(self._plain))

    def set_lines(self, lines, *, line_chars: int = 0) -> None:
        """Several (text, tone) lines, one per row. A text of the form "Label: value" is
        drawn with the label bold and, with `line_chars`, the value shortened in the
        middle so label and value fit that many characters on the line."""

        rows = []
        for text, tone in lines:
            text = str(text or "")
            if not text:
                continue
            label, sep, value = text.partition(": ")
            if sep and len(label) < 24:
                shown = elided(value, line_chars - len(label) - 2) if line_chars else value
                rows.append(tinted(label + ":", tone, bold=True) + " " + tinted(shown, tone))
            else:
                rows.append(tinted(text, tone))
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
        wrap_for_height(self.body)
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
    table.setMaximumHeight(height)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    # A table that grows a row or a column changes its fixed height after the layout has
    # settled. Without telling the parents, they keep the geometry they had and the
    # widgets under the table are drawn over it -- which is what an added stat column did.
    table.updateGeometry()
    parent = table.parentWidget()
    while parent is not None:
        layout = parent.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        parent = parent.parentWidget()
