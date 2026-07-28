"""Small layout helpers shared by the window and its tab mixins.

`window.py` imports every mixin, so a mixin cannot import back from it. These live here instead
of being duplicated per tab, because the problem they solve is the same everywhere: Qt lets a
combo or a button dictate the minimum width of whatever contains it, and the names in this tool
— socket names, clip names, archive paths — are long enough that a couple of them can demand
more width than any monitor has.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QSizePolicy


def let_header_shrink(*, combos, labels=(), buttons=()) -> None:
    """Stop a row of controls dictating a minimum width.

    By default a combo asks to be as wide as its longest entry, a label as wide as its text, and
    a button as wide as its own label. Where several of those share a row the demand adds up,
    and Qt honours it by drawing the widgets over each other rather than by shrinking them.

    Combos keep a readable minimum and elide the rest; labels give way entirely, since they are
    commentary and the window is more useful than the sentence; buttons keep enough to stay
    legible.
    """

    for combo in combos:
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(14)
    for label in labels:
        label.setSizePolicy(QSizePolicy.Ignored, label.sizePolicy().verticalPolicy())
        label.setMinimumWidth(0)
    for button in buttons:
        button.setSizePolicy(QSizePolicy.Ignored, button.sizePolicy().verticalPolicy())
        button.setMinimumWidth(96)


def fit_popup(combo) -> None:
    """Let a dropdown's list be wider than the dropdown itself.

    By default the popup matches the closed control, so narrowing a combo to keep the window
    resizable also narrows the list you pick from — and Qt elides the overflow down the middle,
    which is the worst place: `New attach point (click the body)` came out as
    `New attach poi...lick the body)`, unreadable at both ends.
    """

    metrics = combo.fontMetrics()
    widest = max(
        (metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())),
        default=0,
    )
    if widest:
        # Room for the scrollbar and the frame, or the last character still clips.
        combo.view().setMinimumWidth(widest + 40)
