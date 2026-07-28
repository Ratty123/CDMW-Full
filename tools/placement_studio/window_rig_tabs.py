"""Keeping Driven bones and Rig behaviour pointed at the character on screen.

Both panels edit per-rig files that are not in the pinned baseline, so both need the
archives, and both need to re-target whenever the Studio's character changes. That is one
concern, and it is the same concern twice, so it lives here rather than in either panel.

Three rules shape it.

**Key on the skeleton, not the model.** `.papr` sits beside the `.pab`, and the
pose-modifier descriptor is keyed by `.pab`. A customization variant such as
`phw_damian_01` has no skeleton of its own and runs on `phw_01.pab`, so keying on the
model id would find nothing for exactly the characters a modder is most likely to open.

**Read the archives once, when first asked.** The walk costs about four seconds. Doing it
at startup taxes every session for two tabs most people never open; doing it per switch
makes changing character unusable. So it happens on the first open of either tab and is
cached for the window — see `rig_files`.

**Only the visible tab is refreshed.** Switching character marks the other tab stale
rather than reloading it, so flicking through characters costs one panel refresh, not two.
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QTimer

#: Tab index in the Studio's lower tab widget, by panel.
RIG_TAB_INDEX = {"constraints": 3, "behaviour": 4}
_READING = "Reading the archives once to find the rig files…"


class RigTabsMixin:
    """Wiring for the two archive-backed rig panels. Mixed into `PlacementStudioWindow`."""

    def _init_rig_tabs(self) -> None:
        self._rig_tab_index = dict(RIG_TAB_INDEX)
        self._rig_tab_shown: dict = {}
        self._rig_files_cache = None
        self._rig_scan = None
        self._rig_scan_timer = None
        self._lower.currentChanged.connect(self._on_lower_tab_changed)

    def _rig_key(self) -> Tuple[str, str]:
        """The rig identity both panels resolve against, plus the name to show a user.

        Falls back to the model id when no skeleton loaded, so a character the baseline
        cannot rig still names itself in whatever the panel has to say about it.
        """

        session = self._session
        if session is None:
            return ("", "")
        return (session.skeleton_path or session.model, session.label)

    def _on_lower_tab_changed(self, index: int) -> None:
        for name, tab_index in self._rig_tab_index.items():
            if index == tab_index:
                self._sync_rig_tab(name)

    def _sync_rig_tabs(self) -> None:
        """Re-target whichever rig tab is open; the other catches up when opened."""

        current = self._lower.currentIndex()
        for name, index in self._rig_tab_index.items():
            if index == current:
                self._sync_rig_tab(name)
            else:
                self._rig_tab_shown.pop(name, None)

    def _sync_rig_tab(self, name: str) -> None:
        """Show a panel if the files are in hand, otherwise start the read and wait.

        Never blocks. The archive walk takes about four seconds, and doing it inline froze
        the whole Studio the first time either tab was clicked.
        """

        key = self._rig_key()
        if not key[0] or self._rig_tab_shown.get(name) == key:
            return
        files = self._rig_files_cache
        if files is None:
            self._announce_rig_load(name)
            self._start_rig_file_load()
            return
        self._rig_tab_shown[name] = key
        rig_path, label = key
        if name == "constraints":
            self.show_constraints_for(files, rig_path, label)
        else:
            self.show_rig_behaviour_for(files, rig_path, label)

    def _announce_rig_load(self, name: str) -> None:
        """Say why the panel is empty, in the panel rather than only in the status bar."""

        label = (
            self._constraint_header if name == "constraints" else self._behaviour_header
        )
        label.setText(_READING)

    def _start_rig_file_load(self) -> None:
        if self._rig_scan is not None:
            return
        from PySide6.QtWidgets import QProgressBar

        from .rig_files import scan_rig_files

        bar = getattr(self, "_rig_progress", None)
        if bar is None:
            bar = QProgressBar()
            bar.setMaximumWidth(220)
            bar.setTextVisible(False)
            # 0/0 is Qt's busy animation, which is the honest display until the scan has
            # reported a package total.
            bar.setRange(0, 0)
            self.statusBar().addPermanentWidget(bar)
            self._rig_progress = bar
        bar.setRange(0, 0)
        bar.show()
        self.statusBar().showMessage(_READING)

        self._rig_scan = scan_rig_files()
        timer = QTimer(self)
        # Zero interval, not zero work: Qt runs the rest of the event loop between
        # timeouts, so the window keeps painting and responding while the scan advances.
        timer.setInterval(0)
        timer.timeout.connect(self._step_rig_file_load)
        self._rig_scan_timer = timer
        timer.start()

    def _step_rig_file_load(self) -> None:
        """Advance the scan by one slice. Runs on the UI thread, briefly, many times."""

        scan = self._rig_scan
        if scan is None:
            return
        try:
            done, total, files = next(scan)
        except StopIteration:
            self._finish_rig_load()
            return
        except Exception as error:  # noqa: BLE001 - a missing install is not a crash
            self._on_rig_load_failed(str(error))
            return
        bar = getattr(self, "_rig_progress", None)
        if bar is not None and total > 0:
            bar.setRange(0, total)
            bar.setValue(done)
        if files is not None:
            self._on_rig_files_loaded(files)

    def _finish_rig_load(self) -> None:
        bar = getattr(self, "_rig_progress", None)
        if bar is not None:
            bar.hide()
        timer = self._rig_scan_timer
        self._rig_scan_timer = None
        self._rig_scan = None
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def _on_rig_files_loaded(self, files) -> None:
        self._rig_files_cache = files
        self._finish_rig_load()
        found = len(files.constraint_paths)
        self.statusBar().showMessage(
            f"Rig files read: {found} constraint rigs, "
            f"{'a' if files.pose_modifier else 'no'} pose-modifier descriptor.",
            8000,
        )
        # Whatever tab is open now, not the one that started the read: the character or
        # the tab may both have changed in the seconds this took.
        self._sync_rig_tabs()

    def _on_rig_load_failed(self, message: str) -> None:
        self._finish_rig_load()
        self.statusBar().showMessage(f"Could not read the archives: {message}")
        for name in self._rig_tab_index:
            label = (
                self._constraint_header if name == "constraints" else self._behaviour_header
            )
            label.setText(f"Could not read the archives: {message}")

    def _rig_files(self) -> Optional[object]:
        """The files if the read has finished, else None. Never starts one."""

        return self._rig_files_cache

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        """Stop the archive scan before the widgets it updates go away."""

        self._finish_rig_load()
        super().closeEvent(event)
