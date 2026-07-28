"""A badge and a "What is this for" dialog, instead of paragraphs in the panel.

Both rig panels had a warning banner, a purpose paragraph, a can/cannot box and a
no-preview note stacked above their tables -- around 300px of a 780px panel spent on text
that is read once and then in the way forever. It also read as a wall: the important part
(this format may be dead / this one is live) was one sentence among five.

So each panel gets a one-line strip: a coloured badge saying what kind of tab it is, and a
button that opens the rest. The dialog is structured -- headings, short bullets, and
worked examples in a monospace column -- rather than prose, because it is reference
material somebody scans, not something they read through.

The content lives with the domain modules (`constraints`, `rig_behaviour`), not here.
This module only knows how to render a `Guide`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Optional, Tuple

#: Badge kinds and their colours. `experimental` is the warning one: the tab works, but
#: what it edits may never reach the game.
BADGE_STYLES = {
    "experimental": ("#e08a3c", "#3a2a12"),
    "live": ("#6fbf8b", "#16301f"),
}


@dataclass(frozen=True)
class Section:
    """One heading in the dialog. Bullets and examples, not paragraphs."""

    heading: str
    body: str = ""
    bullets: Tuple[str, ...] = ()
    #: `(what you would write or see, what it means)`, rendered as a two-column table.
    examples: Tuple[Tuple[str, str], ...] = ()
    #: Whether the left column is code. False for prose labels such as the capabilities,
    #: which read as broken text in a monospace face.
    mono: bool = True


@dataclass(frozen=True)
class Guide:
    """Everything the "What is this for" dialog shows for one panel."""

    title: str
    badge: str
    #: A key of `BADGE_STYLES`.
    badge_kind: str
    #: The one sentence worth reading if nothing else is.
    summary: str
    sections: Tuple[Section, ...] = field(default_factory=tuple)

    @property
    def badge_colours(self) -> Tuple[str, str]:
        return BADGE_STYLES.get(self.badge_kind, BADGE_STYLES["experimental"])


def guide_html(guide: Guide) -> str:
    """The dialog body. Kept separate from the widget so it can be tested as text."""

    foreground, _background = guide.badge_colours
    parts = [
        f'<p style="color:{foreground}; margin:0 0 10px 0;"><b>{escape(guide.summary)}</b></p>'
    ]
    for section in guide.sections:
        parts.append(f'<h3 style="margin:14px 0 4px 0;">{escape(section.heading)}</h3>')
        if section.body:
            parts.append(f'<p style="margin:0 0 6px 0;">{escape(section.body)}</p>')
        if section.bullets:
            items = "".join(f"<li>{escape(text)}</li>" for text in section.bullets)
            parts.append(f'<ul style="margin:0 0 6px 0;">{items}</ul>')
        if section.examples:
            wrap = "<code>{}</code>" if section.mono else "<b>{}</b>"
            rows = "".join(
                "<tr>"
                f'<td style="padding:1px 14px 1px 0; white-space:nowrap;">'
                f'{wrap.format(escape(code))}</td>'
                f'<td style="padding:1px 0;">{escape(meaning)}</td>'
                "</tr>"
                for code, meaning in section.examples
            )
            parts.append(f'<table cellspacing="0" cellpadding="0">{rows}</table>')
    return "".join(parts)


def show_guide(guide: Guide, parent=None) -> None:
    """Open the dialog. Non-modal would let it drift behind the Studio, so it is modal."""

    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

    dialog = QDialog(parent)
    dialog.setWindowTitle(guide.title)
    dialog.resize(620, 520)
    layout = QVBoxLayout(dialog)
    view = QTextBrowser()
    view.setOpenExternalLinks(False)
    view.setHtml(guide_html(guide))
    layout.addWidget(view)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.rejected.connect(dialog.reject)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.exec()


def guide_strip(guide: Guide, parent=None):
    """The one-line header: a badge, the summary, and the button that opens the rest."""

    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

    strip = QWidget()
    row = QHBoxLayout(strip)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    foreground, background = guide.badge_colours
    badge = QLabel(guide.badge)
    badge.setStyleSheet(
        f"QLabel {{ color: {foreground}; background: {background};"
        f" border: 1px solid {foreground}; border-radius: 3px;"
        # One brace: this piece is not an f-string, so `}}` would emit two. Copy-paste from
        # the f-string parts above, where doubling is required. Qt tolerates the stray brace
        # -- the badge renders correctly either way and no warning is logged -- so this is
        # hygiene rather than a fix, and worth keeping only because the next edit to this
        # rule might not be so lucky.
        " padding: 1px 7px; font-weight: bold; }"
    )
    badge.setToolTip(guide.summary)
    row.addWidget(badge)

    button = QPushButton("What is this for?")
    button.setToolTip("What this tab edits, what it cannot do, and worked examples.")
    button.clicked.connect(lambda: show_guide(guide, parent))
    row.addWidget(button)
    row.addStretch(1)
    return strip, badge, button


def capability_sections(capabilities) -> Tuple[Section, ...]:
    """Turn a `(allowed, label, why)` table into the two dialog sections.

    Taking them from the same tuple the code is built around is what stops the dialog
    promising something no function behind it can do.
    """

    def rows(allowed: bool) -> Tuple[Tuple[str, str], ...]:
        return tuple(
            (label, why) for is_allowed, label, why in capabilities if is_allowed is allowed
        )

    return (
        Section(heading="What you can change", examples=rows(True), mono=False),
        Section(heading="What it cannot do", examples=rows(False), mono=False),
    )


def find_guide(panel) -> Optional[Guide]:
    """The guide a panel is showing, for tests and for the Help tab."""

    return getattr(panel, "_guide", None)
