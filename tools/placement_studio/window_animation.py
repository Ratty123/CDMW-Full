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

    def _build_animation_tab(self) -> QWidget:
        """Browse and play animations, replace a weapon's draws, and fix their timing.

        One page at a time, each with the tab's full height: stacked in one column, the
        animation list ended up a few rows tall.
        """

        from PySide6.QtWidgets import QStackedWidget

        from . import ui_kit as kit

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._animation_switch = kit.Segmented((
            ("browse", "Browse", "Find and play any animation in the game."),
            ("replace", "Replace draws",
             "Give the weapon another weapon's draws and put-aways, to match where it hangs."),
            ("timing", "Timing",
             "When each draw and put-away swaps the weapon between the body and the hand."),
        ))
        switch_row = kit.row(self._animation_switch, stretch=False)
        switch_row.layout().setContentsMargins(8, 8, 8, 2)
        layout.addWidget(switch_row)
        self._animation_stack = QStackedWidget()
        self._animation_stack.addWidget(self._build_clip_browser())
        self._animation_stack.addWidget(self._build_replace_draws_page())
        self._animation_stack.addWidget(self._build_handoff_timing_page())
        layout.addWidget(self._animation_stack, 1)
        self._animation_switch.changed.connect(self._on_animation_page_changed)
        self._view_footer.addWidget(self._timing_plot)

        # Kept so `_on_tab_changed_for_clips` can recognise this tab by identity, and start
        # the clip index the first time it is opened.
        self._animation_page = page
        self._lower.currentChanged.connect(lambda _index: self._sync_view_footer())
        return page

    def _build_replace_draws_page(self) -> QWidget:
        from . import ui_kit as kit

        page = kit.InspectorPage()
        swap = kit.Form()
        swap.add_wide(kit.hint(
            "For a weapon moved to another spot: take the draws and put-aways of a weapon "
            "carried there. You see every file it would change before anything changes."))
        swap.add_wide(kit.row(self._carry_swap))
        page.add(kit.Section("Use another weapon's draws", swap))
        fit = kit.Form()
        fit.add_wide(kit.row(self._carry_match))
        self._carry_status.setObjectName("HintLabel")
        self._carry_status.setWordWrap(True)
        fit.add_wide(self._carry_status)
        page.add(kit.Section("Which draws fit each spot", fit))
        return page

    def _on_animation_page_changed(self, value: str) -> None:
        index = {"browse": 0, "replace": 1, "timing": 2}.get(value, 0)
        self._animation_stack.setCurrentIndex(index)
        self._sync_view_footer()

    def _show_animation_page(self, value: str) -> None:
        self._animation_switch.set_value(value)
        self._on_animation_page_changed(value)

    def _sync_view_footer(self) -> None:
        """The gap plot under the view belongs to Animations > Timing alone."""

        from .layout_util import is_current_page

        timeline = getattr(self, "_key_timeline", None)
        if timeline is not None:
            timeline.setVisible(self._lower.currentWidget()
                                is getattr(self, "_animation_editor_page", None))
        plot = getattr(self, "_timing_plot", None)
        stack = getattr(self, "_animation_stack", None)
        if plot is None or stack is None:
            return
        plot.setVisible(stack.currentIndex() == 2 and is_current_page(self._animation_page)
                        and self._lower.currentWidget() is self._animation_page)

    def _build_chart_tab(self, mono: QFont) -> QWidget:
        """Advanced: which charts drive an attach point, and pointing them at another one."""

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 6, 8, 6)

        intro = QLabel(
            "Action charts decide which animation plays when, and which attach point it "
            "moves. Most changes never need this: use Carry and Animations first."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # The retarget controls are a separate job from reading a chart, and unlabelled they
        # read as more settings. Boxing them says which question each row answers.
        retarget_box = QGroupBox("Point an animation at a different attach point")
        retarget_box.setToolTip(
            "Rewrites which socket an action chart drives — only possible between names of "
            "the same length, because the file stores them with their length."
        )
        row = QHBoxLayout(retarget_box)
        row.setSpacing(8)
        row.addWidget(QLabel("Attach point the charts use:"))
        self._chart_socket_box = QComboBox()
        self._chart_socket_box.currentIndexChanged.connect(self._refresh_retarget_targets)
        self._chart_socket_box.currentIndexChanged.connect(self._refresh_socket_clips)
        row.addWidget(self._chart_socket_box, 1)

        row.addSpacing(12)
        row.addWidget(QLabel("Use instead:"))
        self._retarget_box = QComboBox()
        row.addWidget(self._retarget_box, 1)

        self._retarget_button = QPushButton("Apply")
        self._retarget_button.clicked.connect(self._apply_retarget)
        row.addWidget(self._retarget_button)

        # Socket names are long and a combo asks to be as wide as its longest entry; only the
        # combos give way, so the button never leaves the row.
        _let_header_shrink(combos=(self._chart_socket_box, self._retarget_box), labels=())

        self._chart_view = QPlainTextEdit()
        self._chart_view.setReadOnly(True)
        self._chart_view.setFont(mono)

        socket_box = QGroupBox("Animations that use this attach point")
        socket_box.setToolTip(
            f"Needs {MATCH_LABEL}. These are the clips a chart names alongside this socket."
        )
        _fill(socket_box, self._build_socket_clips_pane())

        chart_box = QGroupBox("Action chart contents")
        chart_box.setToolTip("The raw sockets and clips named by the loaded charts.")
        _fill(chart_box, self._chart_view)

        panes = QSplitter(Qt.Vertical)
        panes.addWidget(socket_box)
        panes.addWidget(chart_box)
        panes.setChildrenCollapsible(False)
        panes.setStretchFactor(0, 3)
        panes.setStretchFactor(1, 2)

        retarget_box.setMaximumHeight(retarget_box.sizeHint().height())
        layout.addWidget(retarget_box)
        layout.addWidget(panes, 1)
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
        """Return only indexes prepared from the current chart payloads."""

        from .animation_sets import AnimationSetIndex

        if not self._ensure_chart_indexes():
            return AnimationSetIndex()
        return self._animation_sets_cache

    def _refresh_socket_clips(self) -> None:
        from .animation_sets import summarise

        socket = self._chart_socket_box.currentData() or ""
        index = self._animation_sets()
        clips = index.clips_for_socket(socket) if socket else []
        charts = index.charts_for_socket(socket) if socket else []
        listing = self._socket_clips_list
        model = listing.model()
        current = [model.index(row, 0).data(Qt.UserRole) for row in range(model.rowCount())]
        # Socket geometry and its history do not change chart associations. Keep
        # those Qt-owned rows and the selected clip instead of destroying them
        # on every nudge, Undo and Redo.
        if current != clips:
            # Rows are written through the model, never as Python item wrappers. Clearing a
            # list whose rows each held a wrapper crashed the process (an access violation
            # inside clear()) when the charts landed while the cold-cache scans were running.
            listing.clear()
            listing.addItems([trimmed(clip) for clip in clips])
            for row, clip in enumerate(clips):
                index = model.index(row, 0)
                # Playback needs the full stem, not the trimmed display text.
                model.setData(index, clip, Qt.UserRole)
                model.setData(index, f"{clip}\n\nDouble-click to play this clip on the rig",
                              Qt.ToolTipRole)
        self._socket_clips_label.setText(summarise(socket, clips, charts))

    def _play_socket_clip(self, item) -> None:
        """Play a clip named by the charts, resolved through the browser's index."""

        stem = item.data(Qt.UserRole) or item.text()
        self._when_clips_ready('socket-play', lambda: self._play_socket_stem(stem))

    def _play_socket_stem(self, stem):
        found, _total = self._clip_index.filter(text=stem, include_lod=False, limit=32)
        exact = next((entry for entry in found if entry.name == stem), None)
        if exact is None:
            self.statusBar().showMessage(
                f"{stem} is named by a chart but is not in the indexed clips"
            )
            return
        self._play_clip_entry(exact)

    def _chart_index(self):
        from .animation import ChartIndex
        if not self._ensure_chart_indexes():
            return ChartIndex()
        return self._chart_index_cache

    def _ensure_chart_indexes(self):
        from .loading import prepare_charts
        if self._edits is None:
            return False
        # Bytes are immutable. Retained snapshots detect undo/redo and an edit with the
        # same command count, without hashing all chart payloads on every refresh.
        sources = tuple((path, self._edits.chart_bytes(path) or b"")
                        for path in self._edits.charts())
        if sources == getattr(self, '_chart_sources_ready', None):
            if getattr(self, '_background_loading', False):
                if sources != getattr(self, '_chart_sources_requested', None):
                    task = getattr(self, '_chart_task', None)
                    if task is not None:
                        task.cancel()
                    self._chart_sources_requested = sources
                self._chart_socket_box.setEnabled(True)
            return True
        if not getattr(self, '_background_loading', False):
            self._chart_index_cache, self._animation_sets_cache = prepare_charts(
                sources, lambda: False, lambda *_: None)
            self._chart_sources_ready = sources
            return True
        if sources == getattr(self, '_chart_sources_requested', None):
            return False
        from .background import LatestTask
        if getattr(self, '_chart_task', None) is None:
            self._chart_task = LatestTask(self)
            self._chart_task.setObjectName('chart_preparation')
            self._chart_task.ready.connect(self._charts_prepared)
        self._chart_sources_requested = sources
        self._retarget_button.setEnabled(False)
        self._chart_socket_box.setEnabled(False)
        self._chart_task.submit(lambda cancelled, progress:
                                (sources, prepare_charts(sources, cancelled, progress)))
        return False

    def _charts_prepared(self, value, error):
        if error or value is None:
            self.statusBar().showMessage(error)
            return
        sources, result = value
        current = tuple((path, self._edits.chart_bytes(path) or b"")
                        for path in self._edits.charts())
        if sources != current:
            self._ensure_chart_indexes()
            return
        if result is None:
            return
        self._chart_index_cache, self._animation_sets_cache = result
        self._chart_sources_ready = sources
        self._chart_socket_box.setEnabled(True)
        self._refresh_animation()

    def _refresh_animation(self) -> None:
        if self._edits is None:
            return
        if not self._ensure_chart_indexes():
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
