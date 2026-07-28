"""The Animation tab: play a clip on the rig, and retarget the sockets charts drive.

Tier C lives here. The safety rule is enforced as a *filter*, not a validation: only sockets of
the same name length, that some file already defines, are offered — so a retarget that would
change a `.paac` payload's size, or point at a socket nothing defines, cannot be chosen.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .editing import EditError
from .glossary import MATCH_LABEL
from .clip_names import trimmed
from .layout_util import let_header_shrink as _let_header_shrink


def _fill(box, widget) -> None:
    """Put one widget inside a group box, with no extra padding of its own."""

    layout = QVBoxLayout(box)
    layout.setContentsMargins(6, 4, 6, 6)
    layout.addWidget(widget)


class AnimationTabMixin:
    """Chart indexing and retargeting. Mixed into `PlacementStudioWindow`."""

    def _build_animation_tab(self, mono: QFont) -> QWidget:
        """Tier C retargeting: which action charts use a socket, and what may replace it."""

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 6, 8, 6)

        # Playback sits above the retarget controls: it answers "what does this look like",
        # which is the question you ask before deciding what to retarget.
        layout.addWidget(self._build_playback_row())

        # The retarget controls are a separate job from watching a clip, and unlabelled they
        # read as more playback settings. Boxing them says which question each row answers.
        retarget_box = QGroupBox("Point an animation at a different attach point")
        retarget_box.setToolTip(
            "Advanced. Rewrites which socket an action chart drives — only possible between "
            "names of the same length, because the file stores them with their length."
        )
        row = QHBoxLayout(retarget_box)
        row.setSpacing(8)
        row.addWidget(QLabel("Socket used by charts:"))
        self._chart_socket_box = QComboBox()
        self._chart_socket_box.currentIndexChanged.connect(self._refresh_retarget_targets)
        self._chart_socket_box.currentIndexChanged.connect(self._refresh_socket_clips)
        row.addWidget(self._chart_socket_box, 1)

        row.addSpacing(12)
        row.addWidget(QLabel("Retarget to:"))
        self._retarget_box = QComboBox()
        row.addWidget(self._retarget_box, 1)

        self._retarget_button = QPushButton("Apply retarget")
        self._retarget_button.clicked.connect(self._apply_retarget)
        row.addWidget(self._retarget_button)

        # Socket names are long — `Spine2_B_SubWeapon_Socket (4 chart(s))` — and a combo asks to
        # be as wide as its longest entry by default. Two of those plus a button demanded more
        # width than the row had, so Qt drew them over each other and over the labels between
        # them. They elide instead now, and the popup keeps the full text readable.
        # Only the combos give way. Handing the button `Ignored` too let the two stretching
        # combos take every pixel and squeeze it off the right-hand edge entirely — a control
        # that is merely narrow is recoverable, one that is not on screen is not.
        _let_header_shrink(combos=(self._chart_socket_box, self._retarget_box), labels=())

        self._chart_view = QPlainTextEdit()
        self._chart_view.setReadOnly(True)
        self._chart_view.setFont(mono)

        # Browse on the left, charts on the right: picking a clip and reading what drives a
        # socket are the two halves of the same question, and both want the room.
        # Stacked, not three columns. The tab lives in a side column now, so splitting it
        # horizontally gave each pane about 150 px — enough to wrap a file path onto six
        # lines and not enough to read a clip name.
        # Each pane says what it is. Stacked unlabelled they ran together into one column of
        # lists, and which list was which had to be worked out from its contents.
        browser_box = QGroupBox("Find and play a clip")
        _fill(browser_box, self._build_clip_browser())

        socket_box = QGroupBox("Animations that run through the selected attach point")
        socket_box.setToolTip(
            f"Needs {MATCH_LABEL}. These are the clips a chart names alongside this socket."
        )
        _fill(socket_box, self._build_socket_clips_pane())

        chart_box = QGroupBox("Action chart contents")
        chart_box.setToolTip("The raw sockets and clips named by the selected chart.")
        _fill(chart_box, self._chart_view)

        # Two lanes. Four boxes in one column ran together into a single stack of lists with
        # every one of them squeezed, and the tab is wide now — wide enough that the earlier
        # objection to splitting it (each pane landing at ~150 px, too narrow to read a clip
        # name) no longer holds.
        #
        # The split follows the two questions being asked: *what does this clip look like* on
        # the left, and *what is attached here* on the right. Retargeting is neither, so it sits
        # full width underneath, where its long socket names have room to be read.
        panes = QSplitter(Qt.Horizontal)
        panes.addWidget(browser_box)
        right = QSplitter(Qt.Vertical)
        right.addWidget(socket_box)
        right.addWidget(chart_box)
        right.setChildrenCollapsible(False)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        right.setSizes([320, 220])
        panes.addWidget(right)
        panes.setChildrenCollapsible(False)
        panes.setStretchFactor(0, 3)
        panes.setStretchFactor(1, 2)
        panes.setSizes([620, 460])

        layout.addWidget(panes, 1)
        # A fixed-height strip; the lists take the room.
        retarget_box.setMaximumHeight(retarget_box.sizeHint().height())
        layout.addWidget(retarget_box)
        return page

    def _build_socket_clips_pane(self) -> QWidget:
        """Which animations a placement implies.

        Move a weapon and the draw has to change with it. A chart names both the socket it
        routes through and the clips it plays, so the set is a lookup rather than a guess.
        """

        pane = QWidget()
        column = QVBoxLayout(pane)
        column.setContentsMargins(0, 0, 0, 0)
        self._socket_clips_label = QLabel("Select a socket to see the animations routed through it")
        self._socket_clips_label.setWordWrap(True)
        column.addWidget(self._socket_clips_label)
        self._socket_clips_list = QListWidget()
        self._socket_clips_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._socket_clips_list.setUniformItemSizes(True)
        self._socket_clips_list.itemDoubleClicked.connect(self._play_socket_clip)
        column.addWidget(self._socket_clips_list, 1)
        return pane

    def _animation_sets(self):
        from .animation_sets import AnimationSetIndex

        if self._edits is None:
            return AnimationSetIndex()
        return AnimationSetIndex.from_files(
            {path: self._edits.chart_bytes(path) or b"" for path in self._edits.charts()}
        )

    def _refresh_socket_clips(self) -> None:
        from .animation_sets import summarise

        socket = self._chart_socket_box.currentData() or ""
        index = self._animation_sets()
        clips = index.clips_for_socket(socket) if socket else []
        charts = index.charts_for_socket(socket) if socket else []
        self._socket_clips_list.clear()
        for clip in clips:
            item = QListWidgetItem(trimmed(clip))
            # The real name goes in the data, not the text: playback looks the clip up by stem,
            # so a trimmed row would otherwise stop being playable.
            item.setData(Qt.UserRole, clip)
            item.setToolTip(f"{clip}\n\nDouble-click to play this clip on the rig")
            self._socket_clips_list.addItem(item)
        self._socket_clips_label.setText(summarise(socket, clips, charts))

    def _play_socket_clip(self, item) -> None:
        """Play a clip named by the charts, resolved through the browser's index."""

        stem = item.data(Qt.UserRole) or item.text()
        found, _total = self._clip_index.filter(text=stem, include_lod=False, limit=32)
        exact = next((entry for entry in found if entry.name == stem), None)
        if exact is None:
            self.statusBar().showMessage(
                f"{stem} is named by a chart but is not in the indexed clips"
            )
            return
        self._play_clip_entry(exact)

    def _chart_index(self):
        from .animation import ChartIndex, index_chart

        if self._edits is None:
            return ChartIndex()
        return ChartIndex(
            index_chart(path, self._edits.chart_bytes(path) or b"")
            for path in self._edits.charts()
        )

    def _refresh_animation(self) -> None:
        if self._edits is None:
            return
        index = self._chart_index()
        model = self._session.model if self._session else ""

        # Restore by data, not by display text: the label carries a chart count that changes
        # as edits land, so a text match would silently drop the user's selection.
        current = self._chart_socket_box.currentData()
        self._chart_socket_box.blockSignals(True)
        self._chart_socket_box.clear()
        for name, count in index.sockets_for(model=model).items():
            self._chart_socket_box.addItem(f"{name}  ({count} chart(s))", name)
        if current:
            position = self._chart_socket_box.findData(current)
            if position >= 0:
                self._chart_socket_box.setCurrentIndex(position)
        self._chart_socket_box.blockSignals(False)
        self._refresh_socket_clips()

        lines = [f"{len(index)} action chart(s) loaded", ""]
        for chart in index.charts():
            lines.append(f"{chart.game_path}")
            lines.append(f"   {chart.size:,}B   group={chart.group}   model={chart.model}")
            for name in chart.names:
                lines.append(f"      {name}  at {list(chart.offsets(name))}")
            lines.append("")
        self._chart_view.setPlainText("\n".join(lines))
        self._refresh_retarget_targets()

    def _refresh_retarget_targets(self) -> None:
        """Offer only same-length, already-defined sockets — the length rule as a filter."""

        from .animation import retarget_candidates

        self._retarget_box.clear()
        old_name = self._chart_socket_box.currentData()
        if not old_name or self._edits is None:
            self._retarget_button.setEnabled(False)
            return
        candidates = retarget_candidates(
            old_name, defined_sockets=self._edits.defined_sockets()
        )
        for name in candidates:
            self._retarget_box.addItem(name, name)
        enabled = bool(candidates)
        self._retarget_button.setEnabled(enabled)
        if not enabled:
            self._retarget_box.addItem(
                f"(no defined socket of length {len(old_name)} — create one first)", None
            )

    def _apply_retarget(self) -> None:
        if self._edits is None:
            return
        old_name = self._chart_socket_box.currentData()
        new_name = self._retarget_box.currentData()
        if not old_name or not new_name:
            return
        self._retarget_between(old_name, new_name)
