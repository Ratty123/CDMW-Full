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

#: Tab index in the Studio's lower tab widget, by panel.
RIG_TAB_INDEX = {"constraints": 3, "behaviour": 4}


class RigTabsMixin:
    """Wiring for the two archive-backed rig panels. Mixed into `PlacementStudioWindow`."""

    def _init_rig_tabs(self) -> None:
        self._rig_tab_index = dict(RIG_TAB_INDEX)
        self._rig_tab_shown: dict = {}
        self._rig_files_cache = None
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
        key = self._rig_key()
        if not key[0] or self._rig_tab_shown.get(name) == key:
            return
        files = self._rig_files()
        if files is None:
            return
        self._rig_tab_shown[name] = key
        rig_path, label = key
        if name == "constraints":
            self.show_constraints_for(files, rig_path, label)
        else:
            self.show_rig_behaviour_for(files, rig_path, label)

    def _rig_files(self) -> Optional[object]:
        """The shared archive read, once per window, with the wait announced.

        A status message set and never painted is worse than none: the window simply
        freezes for four seconds with no explanation. One `processEvents` pass is what
        puts the text on screen before the walk starts.
        """

        if self._rig_files_cache is not None:
            return self._rig_files_cache
        from PySide6.QtWidgets import QApplication

        from .rig_files import read_rig_files

        self.statusBar().showMessage("Reading the archives once to find the rig files…")
        QApplication.processEvents()
        try:
            self._rig_files_cache = read_rig_files()
        except Exception as error:  # noqa: BLE001 - a missing install is not a crash
            self.statusBar().showMessage(f"Could not read the archives: {error}")
            return None
        found = len(self._rig_files_cache.constraint_paths)
        self.statusBar().showMessage(
            f"Rig files read: {found} constraint rigs, "
            f"{'a' if self._rig_files_cache.pose_modifier else 'no'} pose-modifier descriptor.",
            8000,
        )
        return self._rig_files_cache
