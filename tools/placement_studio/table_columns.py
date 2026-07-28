"""Proportional table columns, because Qt's `Stretch` gives one column everything.

`QHeaderView` offers `Stretch` and `ResizeToContents` and no way to say "this column
deserves twice the width of that one". One stretching column beside several
`ResizeToContents` ones therefore absorbs every spare pixel: at 1,200px the Driven bones
chain list gave its name column about 810px of mostly empty space while Bones, Strength
and Decoded sat squeezed against the right edge, and the driven-bone table elided
`P_Bip01 L Clavicle_Sub` down to `P_Bip01 L ...` with 600px going spare beside it.

Marking two columns `Stretch` does not fix it either -- Qt splits the slack equally, so a
category column ends up as wide as the names.

So: weights, re-applied whenever the viewport resizes. Minimums keep a column readable
when the panel is narrow, at the cost of a horizontal scrollbar in the extreme case,
which is the right trade against silently truncating a bone name.
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QHeaderView


class _ProportionalColumns(QObject):
    """Keeps one table's column widths in a fixed ratio. Owned by the table."""

    def __init__(
        self,
        table,
        weights: Sequence[float],
        minimums: Sequence[int],
    ) -> None:
        super().__init__(table)
        self._table = table
        self._weights = tuple(float(w) for w in weights)
        self._minimums = tuple(int(m) for m in minimums)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(len(self._weights)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        # The viewport, not the table: the table's resize fires before the scrollbar is
        # taken out, so widths computed there overflow by the scrollbar's width and
        # produce a horizontal scrollbar that then never goes away.
        table.viewport().installEventFilter(self)
        self.apply()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if event.type() == QEvent.Resize:
            self.apply()
        return False

    def apply(self) -> None:
        available = self._table.viewport().width()
        if available <= 0:
            return
        widths = self._widths_for(available)
        for column, width in enumerate(widths):
            self._table.setColumnWidth(column, width)

    def _widths_for(self, available: int) -> list[int]:
        """Widths that sum to `available` whenever the minimums allow it.

        Raising a column to its minimum has to be paid for out of the columns that are
        still above theirs. Skipping that step overshoots the viewport by the difference
        and Qt answers with a horizontal scrollbar -- which shrinks the viewport, so the
        next pass overshoots again and the scrollbar never goes away.
        """

        share = sum(self._weights) or 1.0
        widths = [int(available * weight / share) for weight in self._weights]
        widths = [max(w, m) for w, m in zip(widths, self._minimums)]

        overflow = sum(widths) - available
        if overflow > 0:
            # Take it back from whatever slack exists above the minimums, in proportion to
            # how much slack each column has. If there is none, the panel is genuinely too
            # narrow and a scrollbar is the honest answer.
            slack = [w - m for w, m in zip(widths, self._minimums)]
            total_slack = sum(slack)
            if total_slack > 0:
                taken = 0
                for index, spare in enumerate(slack):
                    if not spare:
                        continue
                    cut = min(spare, round(overflow * spare / total_slack))
                    widths[index] -= cut
                    taken += cut
                # Rounding can leave a pixel or two; take them off the widest column.
                for _ in range(overflow - taken):
                    index = widths.index(max(widths))
                    if widths[index] > self._minimums[index]:
                        widths[index] -= 1
        else:
            # Rounding leaves a few pixels over. Give them to the widest column rather
            # than to the last one, which is usually a number and does not want them.
            widths[widths.index(max(widths))] += -overflow
        return widths


def proportional_columns(
    table,
    weights: Sequence[float],
    minimums: Sequence[int],
) -> _ProportionalColumns:
    """Size `table`'s columns by `weights`, never below `minimums`.

    Returns the helper so a caller can hold it and re-`apply()`; it also parents itself to
    the table, so simply calling this is enough to keep it alive.
    """

    if len(weights) != len(minimums):
        raise ValueError("weights and minimums must describe the same columns")
    if len(weights) != table.columnCount():
        raise ValueError(
            f"{len(weights)} weights for a table with {table.columnCount()} columns"
        )
    return _ProportionalColumns(table, weights, minimums)
