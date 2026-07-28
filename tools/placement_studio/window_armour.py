"""The armour picker: dress the rig, and see the whole silhouette move.

Judging a weapon against a bare body is judging the easy case. A cloak, a vest and a belt
are exactly what a stowed sword clips through, so the pieces have to be on the character
before the placement means anything.

Armour lives in the archives rather than the pinned baseline, so the list is built on a
worker alongside the clip index and a piece's geometry is read only when it is chosen.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
)

from .armour import NONE_LABEL, SLOTS, ArmourIndex, index_wearables, read_entry


class _ArmourWorker(QObject):
    done = Signal(object, object, object, str)

    def __init__(self, game_root) -> None:
        super().__init__()
        self._root = game_root
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            index, sockets, meshes = index_wearables(self._root, should_stop=lambda: self._stop)
        except Exception as error:  # noqa: BLE001 - report, never take the window down
            self.done.emit(None, None, None, str(error))
            return
        if self._stop:
            self.done.emit(None, None, None, "")
            return
        self.done.emit(index, sockets, meshes, "")


class ArmourPickerMixin:
    """Per-slot armour selection. Mixed into `PlacementStudioWindow`."""

    def _build_armour_tab(self) -> QWidget:
        self._armour_index = ArmourIndex()
        self._armour_thread = None
        self._armour_worker = None
        self._armour_boxes: dict = {}
        self._weapon_socket_entries: dict = {}
        self._weapon_mesh_entries: dict = {}

        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setColumnStretch(1, 1)

        self._armour_status = QLabel("Indexing armour…")
        grid.addWidget(self._armour_status, 0, 0, 1, 2)

        for row, (slot, label) in enumerate(SLOTS, start=1):
            grid.addWidget(QLabel(label + ":"), row, 0)
            box = QComboBox()
            box.addItem(NONE_LABEL, "")
            box.setEnabled(False)
            box.currentIndexChanged.connect(self._on_armour_changed)
            grid.addWidget(box, row, 1)
            self._armour_boxes[slot] = box

        clear = QPushButton("Undress")
        clear.setToolTip("Clear every slot back to the bare body")
        clear.clicked.connect(self._clear_armour)
        grid.addWidget(clear, len(SLOTS) + 1, 0, 1, 2)
        grid.setRowStretch(len(SLOTS) + 2, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        self._start_armour_index()
        return scroll

    # ── indexing ────────────────────────────────────────────────────

    def _start_armour_index(self) -> None:
        from pathlib import Path

        from .corpus import game_root

        root = game_root()
        if not Path(root).is_dir():
            self._armour_status.setText("No game install — armour unavailable")
            return
        self._armour_thread = QThread(self)
        self._armour_worker = _ArmourWorker(root)
        self._armour_worker.moveToThread(self._armour_thread)
        self._armour_thread.started.connect(self._armour_worker.run)
        self._armour_worker.done.connect(self._on_armour_index_ready)
        self._armour_thread.start()

    def _on_armour_index_ready(self, index, sockets, meshes, error: str) -> None:
        if self._armour_thread is not None:
            self._armour_thread.quit()
            self._armour_thread.wait(2000)
            self._armour_thread = None
            self._armour_worker = None
        if index is None:
            self._armour_status.setText(error or "Armour indexing cancelled")
            return
        self._armour_index = index
        self._weapon_socket_entries = dict(sockets or {})
        self._weapon_mesh_entries = dict(meshes or {})
        self._populate_armour()
        # The bare body lives in the packages, not in the pinned baseline, so until the index
        # lands the figure is standing there in the fallback coat. Rebuild now that the real
        # anatomy is reachable.
        self._invalidate_skinned()
        self._refresh_meshes()
        self._load_archive_weapons()
        self._load_archive_charts()

    def _populate_armour(self) -> None:
        model = self._session.model if self._session is not None else ""
        total = 0
        for slot, box in self._armour_boxes.items():
            pieces = self._armour_index.pieces(model, slot)
            total += len(pieces)
            box.blockSignals(True)
            box.clear()
            box.addItem(NONE_LABEL, "")
            for piece in pieces:
                box.addItem(piece.name, piece.path)
            box.setEnabled(bool(pieces))
            box.blockSignals(False)
        self._armour_status.setText(
            f"{total} piece(s) for {model or 'this model'} — pick a slot to dress the rig"
        )

    # ── selection ───────────────────────────────────────────────────

    def _on_armour_changed(self) -> None:
        chosen = {
            slot: (box.currentData() or "")
            for slot, box in self._armour_boxes.items()
        }
        self._armour_choice = {slot: path for slot, path in chosen.items() if path}
        # Loading a piece reads the archives, which is slow enough to be worth saying.
        self._armour_status.setText(
            f"{len(self._armour_choice)} piece(s) worn — loading…"
            if self._armour_choice else "Bare body"
        )
        self.statusBar().showMessage("Loading armour…")
        self._invalidate_skinned()
        if self._armour_choice:
            self._ensure_meshes_visible()
        self._refresh_meshes()
        worn = len(self._skinned_body())
        self._armour_status.setText(f"{len(self._armour_choice)} piece(s) worn, {worn} skinned")
        self.statusBar().showMessage(f"Armour: {worn} mesh(es) bound to the rig")

    def _clear_armour(self) -> None:
        for box in self._armour_boxes.values():
            box.blockSignals(True)
            box.setCurrentIndex(0)
            box.blockSignals(False)
        self._on_armour_changed()

    def _load_archive_weapons(self) -> None:
        """Feed every weapon socket file into the resolver, so all of them are selectable.

        The pinned baseline holds eight; the packages hold the rest. A weapon needs its
        `.sockets.xml`, not just its `.pac` — without one it can be drawn but not placed,
        which is the opposite of what this tool is for.
        """

        session = self._session
        if session is None or not self._weapon_socket_entries:
            return
        model = session.model
        added = 0
        for path, entry in self._weapon_socket_entries.items():
            if f"/{model}/" not in path or path in self._baseline:
                continue
            try:
                session.add_socket_file(path, read_entry(entry))
                added += 1
            except Exception:  # noqa: BLE001 - a file that will not parse is simply skipped
                continue
        if added:
            self._populate_weapons()
            self.statusBar().showMessage(
                f"{added} more weapon(s) available from the archives"
            )

    def _load_archive_charts(self) -> None:
        """Give the edit session this character's own action charts.

        The pinned baseline holds Kliff's four. Damian was therefore shown Kliff's — the raw
        chart text belonged to another character, and the socket list built from it filtered
        them out by model and came up empty. His own five are in the packages.

        Only the selected character's are loaded. Kliff has 101; reading every chart of both
        bodies to show one of them would be paid on every launch.
        """

        from .armour import CHART_SLOT, read_armour

        session = self._session
        index = getattr(self, "_armour_index", None)
        if session is None or self._edits is None or index is None:
            return
        wanted = {}
        for piece in index.pieces(session.model, CHART_SLOT):
            if piece.path in self._baseline or piece.path in self._edits.paths:
                continue
            try:
                wanted[piece.path] = read_armour(piece, index)
            except Exception:  # noqa: BLE001 - a chart that will not read is simply skipped
                continue
        if wanted and self._edits.add_base_files(wanted):
            self._refresh_animation()

    def _stop_armour_index(self) -> None:
        if self._armour_worker is not None:
            self._armour_worker.stop()
        if self._armour_thread is not None:
            self._armour_thread.quit()
            self._armour_thread.wait(3000)
            self._armour_thread = None
            self._armour_worker = None
