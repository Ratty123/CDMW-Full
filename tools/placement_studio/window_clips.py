"""The clip browser: find any of the install's motion clips and play it on the rig.

Enumerating the archive tables takes a few seconds, which is far too long to spend in one
call, so indexing advances a slice per event-loop turn and the browser stays usable — showing
the pinned baseline — while it completes. The list is capped and reports what it is hiding,
because a silently truncated result reads as "that clip is not in the game".
"""

from __future__ import annotations

from .glossary import MATCH_LABEL
from .clip_names import rig_label, trimmed
from .layout_util import fit_popup

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .clips import ALL_CATEGORIES, ANY, ClipIndex, read_clip, scan_archives
from .playback import PlaybackError, coverage, load_clip

#: Rows past this are not worth painting; the filter is the way to find a clip, not scrolling.
_LIST_LIMIT = 800


class ClipBrowserMixin:
    """Clip search and load. Mixed into `PlacementStudioWindow`."""

    def _build_clip_browser(self) -> QWidget:
        self._clip_index = ClipIndex()
        self._clip_scan = None
        self._clip_scan_timer = None

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # Shown once a carry position has been picked: the whole point of measuring which
        # draws start where is being able to see only those.
        self._clip_carry_box = QCheckBox("Only draws for this spot")
        self._clip_carry_box.setToolTip(
            "Show only the take-out and put-away animations that start from where the "
            "selected item is currently carried.\n\n"
            f"Needs {MATCH_LABEL} to have been run once."
        )
        self._clip_carry_box.toggled.connect(self._refresh_clip_list)
        self._carry_filter_zone = ""

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Rig:"))
        self._clip_rig_box = QComboBox()
        self._clip_rig_box.setMinimumWidth(110)
        self._clip_rig_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._clip_rig_box.addItem(ANY, ANY)
        self._clip_rig_box.currentIndexChanged.connect(self._refresh_clip_list)
        filters.addWidget(self._clip_rig_box)

        filters.addWidget(QLabel("Kind:"))
        self._clip_category_box = QComboBox()
        for label in ALL_CATEGORIES:
            self._clip_category_box.addItem(label, label)
        self._clip_category_box.currentIndexChanged.connect(self._refresh_clip_list)
        filters.addWidget(self._clip_category_box)

        self._clip_lod_box = QCheckBox("Distant versions")
        self._clip_lod_box.setToolTip(
            "Also list the simplified copies the game uses when the character is far away. "
            "Same motion, less detail — usually not what you want to look at."
        )
        self._clip_lod_box.toggled.connect(self._refresh_clip_list)
        filters.addStretch(1)
        layout.addLayout(filters)

        # Two rows. Six controls on one line does not fit the lane: Qt answers an impossible
        # width by clipping labels rather than wrapping, so `Only draws for this spot` became
        # `Only draw` and the scan button read `ich draws fi`. What each row holds is chosen so
        # neither can be squeezed — pickers above, switches below.
        switches = QHBoxLayout()
        switches.addWidget(self._clip_lod_box)
        switches.addWidget(self._clip_carry_box)
        switches.addStretch(1)
        layout.addLayout(switches)

        # The scan gets a row to itself. Sharing one with the two checkboxes fitted the pane at
        # full width and not in the lane it actually lives in — `Only draws for this spot` lost
        # its last word and the button read `ind which draws fit (~30s`. Qt answers a row it
        # cannot fit by clipping, so the only reliable fix is to stop asking it to.
        scan = QHBoxLayout()
        scan.addWidget(self._carry_match)
        scan.addStretch(1)
        layout.addLayout(scan)

        # Search gets its own row: sharing one with two combos and a checkbox left it a
        # three-character box in a side column.
        self._clip_search = QLineEdit()
        self._clip_search.setPlaceholderText(
            "search by name, e.g. sword weapon_out — every word must appear"
        )
        self._clip_search.setClearButtonEnabled(True)
        self._clip_search.textChanged.connect(self._refresh_clip_list)

        layout.addWidget(self._clip_search)

        self._clip_list = QListWidget()
        self._clip_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._clip_list.setUniformItemSizes(True)
        self._clip_list.itemDoubleClicked.connect(lambda _item: self._load_selected_clip())
        self._clip_list.currentItemChanged.connect(self._on_clip_selection)
        layout.addWidget(self._clip_list, 1)

        footer = QHBoxLayout()
        self._clip_status = QLabel("Indexing the archives…")
        footer.addWidget(self._clip_status, 1)
        # Progress rather than a spinner: the walk knows how many packages it will visit, and
        # "half way" is the difference between waiting and wondering whether it has hung.
        self._clip_progress = QProgressBar()
        self._clip_progress.setMaximumWidth(140)
        self._clip_progress.setTextVisible(False)
        self._clip_progress.setRange(0, 0)  # busy until the package total is known
        footer.addWidget(self._clip_progress)
        self._clip_load_button = QPushButton("Play selected")
        self._clip_load_button.setToolTip(
            "Pose the character with this clip. You can also double-click a row."
        )
        self._clip_load_button.setEnabled(False)
        self._clip_load_button.clicked.connect(self._load_selected_clip)
        footer.addWidget(self._clip_load_button)
        layout.addLayout(footer)

        self._start_clip_index()
        return panel

    # ── indexing ────────────────────────────────────────────────────

    def _start_clip_index(self) -> None:
        from .corpus import game_root

        root = game_root()
        if not Path(root).is_dir():
            self._fall_back_to_baseline_clips(f"No game install at {root}")
            return
        self._clip_scan = scan_archives(root)
        timer = QTimer(self)
        # Zero interval, not zero work: Qt runs the rest of the event loop between timeouts,
        # so the window keeps painting and answering the mouse while the scan advances.
        timer.setInterval(0)
        timer.timeout.connect(self._step_clip_index)
        self._clip_scan_timer = timer
        timer.start()

    def _step_clip_index(self) -> None:
        """Advance the scan by one slice. Runs on the UI thread, briefly, many times."""

        scan = self._clip_scan
        if scan is None:
            return
        try:
            done, total, index = next(scan)
        except StopIteration:
            # Only reached when the scan was stopped before it produced an index.
            self._stop_clip_index()
            return
        except Exception as error:  # noqa: BLE001 - a missing install is not a crash
            self._stop_clip_index()
            self._fall_back_to_baseline_clips(str(error))
            return
        bar = getattr(self, "_clip_progress", None)
        if bar is not None and total > 0:
            bar.setRange(0, total)
            bar.setValue(done)
        if index is not None:
            self._on_clip_index_ready(index)

    def _fall_back_to_baseline_clips(self, reason: str) -> None:
        """Without the install, the pinned baseline is still worth browsing."""

        from .clips import index_directory
        from .corpus import baseline_root

        motion = Path(baseline_root()) / "character" / "motion"
        if motion.is_dir():
            self._clip_index = index_directory(Path(baseline_root()))
            self._populate_clip_rigs()
            self._refresh_clip_list()
            self._clip_status.setText(f"{reason} — showing the pinned baseline only")
        else:
            self._clip_status.setText(reason)

    def _on_clip_index_ready(self, index) -> None:
        """The scan finished. Failure never arrives here — the stepper falls back itself."""

        self._stop_clip_index()
        self._clip_index = index
        self._populate_clip_rigs()
        self._refresh_clip_list()

    def _populate_clip_rigs(self) -> None:
        """Default to the rig this session actually loaded — that is what will play."""

        session_rig = ""
        if self._session is not None:
            for rig in self._clip_index.rigs():
                if rig.endswith("/" + self._session.model):
                    session_rig = rig
                    break
        self._clip_rig_box.blockSignals(True)
        self._clip_rig_box.clear()
        self._clip_rig_box.addItem(ANY, ANY)
        for rig in self._clip_index.rigs():
            # The code first, then whatever the install actually says about it. Nothing names
            # the other rigs, so they stay codes rather than being guessed at.
            self._clip_rig_box.addItem(rig_label(rig), rig)
        # The closed control stays narrow so it does not widen the row, but the popup must not:
        # elided down the middle, `10_pgw (playable)` came out as `10_pgw...yable)`, unreadable
        # at both ends and identical to its neighbours.
        fit_popup(self._clip_rig_box)
        if session_rig:
            position = self._clip_rig_box.findData(session_rig)
            if position >= 0:
                self._clip_rig_box.setCurrentIndex(position)
        self._clip_rig_box.blockSignals(False)

    # ── list ────────────────────────────────────────────────────────

    def _refresh_clip_list(self) -> None:
        from .clips import summarise

        # The carry filter is applied after the index's own filter, and before the limit, so
        # "8 draws from the back" is never truncated away by 800 unrelated locomotion clips.
        wanted = self._carry_zone_filter()
        found, total = self._clip_index.filter(
            rig=self._clip_rig_box.currentData() or ANY,
            category=self._clip_category_box.currentData() or ANY,
            text=self._clip_search.text(),
            include_lod=self._clip_lod_box.isChecked(),
            limit=None if wanted else _LIST_LIMIT,
        )
        if wanted is not None:
            rank = self._carry_clip_ranking()
            found = [entry for entry in found if entry.name in wanted]
            # Draws first and strongest reach first, so the top of the list is the clip the
            # new carry position actually calls for rather than whatever sorts first by name.
            found.sort(key=lambda entry: rank.get(entry.name, len(rank)))
            found = found[:_LIST_LIMIT]
            total = len(found)
        self._clip_list.setUpdatesEnabled(False)
        self._clip_list.clear()
        for entry in found:
            # The trimmed name, with the file name a hover away. A row of
            # `cd_boarmimic_basic_00_00_nor_move_walkfast_turn180l_stt_00` is mostly parts that
            # are the same on every row; what is left after taking those out still names the
            # file on disk, which a translation into prose would not.
            item = QListWidgetItem(f"{trimmed(entry.name)}    [{entry.category}]")
            item.setData(Qt.UserRole, entry)
            item.setToolTip(f"{entry.name}\n{entry.path}")
            self._clip_list.addItem(item)
        self._clip_list.setUpdatesEnabled(True)
        self._clip_status.setText(summarise(found, total, _LIST_LIMIT))
        self._clip_load_button.setEnabled(self._clip_list.currentItem() is not None)

    def _on_clip_selection(self, current, _previous) -> None:
        self._clip_load_button.setEnabled(current is not None)

    def _load_selected_clip(self) -> None:
        item = self._clip_list.currentItem()
        if item is None:
            return
        self._play_clip_entry(item.data(Qt.UserRole))

    def _play_clip_entry(self, entry) -> None:
        """Load and pose one indexed clip. Shared by the browser and the socket-clip pane."""

        if self._session is None or not self._session.has_skeleton:
            self.statusBar().showMessage("Load a character model before a motion clip.")
            return
        try:
            clip = load_clip(read_clip(entry), entry.name)
        except (PlaybackError, ValueError, OSError) as error:
            self.statusBar().showMessage(f"Could not load {entry.name}: {error}")
            return

        matched = coverage(self._session.hierarchy, clip)
        if matched <= 0.0:
            self.statusBar().showMessage(
                f"{entry.name} animates no bone on this rig — it belongs to {entry.rig or 'another rig'}."
            )
            return
        self._playback.load(clip, entry.name)
        self._playback.looping = self._playback_loop_box.isChecked()
        self._playback_slider.setMaximum(max(self._playback.last_frame, 0))
        self._playback_slider.setEnabled(self._playback.last_frame > 0)
        self._playback_play_button.setEnabled(self._playback.last_frame > 0)
        self._playback_play_button.setText("Play")
        self._playback_rest_button.setEnabled(True)
        self._fit_ground_to_clip(clip)
        # A creature clip such as `cd_boarmimic_*` can match every bone and still look wrong:
        # it folds a human rig onto all fours because that is what the animation says. Name
        # the shape rather than refusing — it is a legitimate thing to want to watch.
        note = "" if matched > 0.99 else f"  ({matched:.0%} of its bones exist on this rig)"
        if not entry.name.startswith(("cd_phm", "cd_phw")) and matched > 0.99:
            note += "  — authored for another character, so the pose will not read as human"
        self.statusBar().showMessage(f"Loaded {entry.name}{note}")
        self._apply_playback_frame()

    def _stop_clip_index(self) -> None:
        """A running table scan must not outlive the window."""

        bar = getattr(self, "_clip_progress", None)
        if bar is not None:
            bar.hide()
        timer = self._clip_scan_timer
        self._clip_scan_timer = None
        self._clip_scan = None
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        """Stop the playhead and the indexer before the widgets they touch go away."""

        timer = getattr(self, "_playback_timer", None)
        if timer is not None:
            timer.stop()
        self._stop_clip_index()
        for name in ("_stop_armour_index", "_stop_carry_index", "_stop_swap"):
            stop = getattr(self, name, None)
            if stop is not None:
                stop()
        super().closeEvent(event)
