"""Changing where a weapon is carried, with the animations following it.

One control does the whole job: pick where the weapon hangs, and the routing edit, the
matching child socket and the animation list all move with it. Before this, the same change
meant selecting a part, arming route mode, finding the target socket in the viewport, clicking
it, and then knowing by heart which draw clips suited the new position.

The animation half is the part that cannot be looked up. Which clips belong to a carry
position is measured — see `carry` — and measuring means playing several hundred clips back
against the rig, which takes about half a minute. So it happens on a worker, once, and is
cached; the routing edit itself never waits for it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
)

from . import carry
from .editing import EditError
from .glossary import tip

#: Bumped when a threshold in `carry` changes, so a cache built under the old scoring is
#: rebuilt rather than quietly kept.
_CACHE_VERSION = 3


class _CarryWorker(QObject):
    """Measures where every draw clip reaches, on its own session and its own thread."""

    done = Signal(object, str)
    progress = Signal(int, int)

    def __init__(self, model: str, clip_entries) -> None:
        super().__init__()
        self._model = model
        self._entries = list(clip_entries)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from .clips import read_clip
        from .corpus import Baseline
        from .playback import load_clip
        from .session import PlacementSession

        try:
            # A private session: measuring poses the rig hundreds of times, and sharing the
            # window's would fight the viewport for it.
            session = PlacementSession.from_baseline(Baseline.load(), self._model)
        except Exception as error:  # noqa: BLE001 - report, never take the window down
            self.done.emit(None, str(error))
            return

        total = len(self._entries)
        index = carry.CarryIndex()
        names = carry.stow_positions(session)
        for done, entry in enumerate(self._entries, start=1):
            if self._stop:
                self.done.emit(None, "")
                return
            try:
                index.add(entry.name, carry.reach_of_clip(session, load_clip(read_clip(entry), "d"), names))
            except Exception:  # noqa: BLE001 - one unreadable clip must not stop the sweep
                pass
            if done % 25 == 0:
                self.progress.emit(done, total)
        self.done.emit(index, "")


class _SwapWorker(QObject):
    """Reads the donor clips off the archives, which is the slow half of a swap.

    Decompressing one clip costs about 165 ms, so the full 804-file restyle is over two
    minutes — long enough that doing it on the UI thread showed the window as Not Responding.
    Only the reading happens here; the edits themselves are recorded back on the UI thread,
    because `EditSession` is not thread-safe and recording is nearly free.
    """

    done = Signal(object, str)
    progress = Signal(int, int)

    def __init__(self, pairs) -> None:
        super().__init__()
        self._pairs = list(pairs)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from .clips import read_clip

        out = []
        total = len(self._pairs)
        for done, (target, donor) in enumerate(self._pairs, start=1):
            if self._stop:
                self.done.emit(None, "")
                return
            try:
                out.append((target.path, read_clip(donor), donor.name))
            except Exception:  # noqa: BLE001 - an unreadable clip is simply not swapped
                pass
            if done % 10 == 0:
                self.progress.emit(done, total)
        self.done.emit(out, "")


class CarryPickerMixin:
    """The `Carry:` control, and the animation matching behind it."""

    # ── construction ────────────────────────────────────────────────

    def _build_carry_controls(self):
        self._carry_box = QComboBox()
        self._carry_box.setMinimumWidth(190)
        self._carry_box.setToolTip(
            tip("Carry",
                "This is the control that moves a weapon. Pick a different entry and the item "
                "is re-routed there, its angle follows, and you are offered the matching "
                "animations.")
        )
        self._carry_box.currentIndexChanged.connect(self._on_carry_changed)

        self._history_button = QPushButton("Recent actions...")
        self._history_button.setToolTip(
            "Everything changed so far, and a way to undo back to any point."
        )
        self._history_button.clicked.connect(self._show_history)

        self._carry_match = QPushButton("Match animations")
        self._carry_match.setToolTip(
            tip("Match animations",
                "This finds and shows clips. It does not change the mod — see the report it "
                "prints when it finishes.")
        )
        self._carry_match.clicked.connect(lambda: self._start_carry_index(explicit=True))

        self._carry_swap = QPushButton("Swap animations...")
        self._carry_swap.setToolTip(
            "Give this weapon the other grip's animations — the two-hand set for a one-hand "
            "weapon, or the reverse.\n\n"
            "The chosen animation is written in place of the old one, so the game keeps "
            "asking for the same file and gets the new motion.\n\n"
            "You are shown every file it would touch before anything is changed."
        )
        self._carry_swap.clicked.connect(self._on_swap_clicked)

        self._carry_status = QLabel("")
        self._carry_index: Optional[carry.CarryIndex] = None
        self._carry_thread = None
        self._carry_worker = None
        self._swap_thread = None
        self._swap_worker = None
        self._swap_preview = None
        self._play_after_swap = True
        #: Set while the combo is being rebuilt, so syncing it does not re-route anything.
        self._carry_syncing = False
        return self._carry_box, self._history_button, self._carry_swap, self._carry_status

    # ── the control ─────────────────────────────────────────────────

    def _current_binding(self):
        session = self._session
        if session is None or not self._selected_part:
            return None
        return next(
            (b for b in session.bindings() if b.part_name == self._selected_part), None
        )

    def _populate_carry_box(self) -> None:
        """Fill the control and point it at where the selected part currently hangs."""

        if self._session is None:
            return
        binding = self._current_binding()
        current = getattr(getattr(binding, "part", None), "in_socket", "") or ""
        self._carry_syncing = True
        self._carry_box.clear()
        positions = carry.carry_positions(self._session)
        for socket, label in positions:
            self._carry_box.addItem(label, socket)
        # A part routed somewhere that is not a carry position — an earring, a lantern — still
        # has to show its real socket rather than silently reading as the first entry.
        if current and current not in dict(positions):
            self._carry_box.addItem(current, current)
        from .window import fit_popup

        fit_popup(self._carry_box)
        position = self._carry_box.findData(current)
        self._carry_box.setCurrentIndex(max(0, position))
        self._carry_syncing = False
        self._refresh_carry_status()

    def _refresh_carry_status(self) -> None:
        if self._carry_index is None:
            self._carry_status.setText("press Match animations to link clips to positions")
            return
        counts = self._carry_index.counts()
        parts = [
            f"{carry.ZONE_LABELS.get(zone, zone)} {count}"
            for zone, count in sorted(counts.items(), key=lambda kv: -kv[1])
        ]
        self._carry_status.setText(
            "draws found — " + ", ".join(parts) if parts else "no draws could be matched"
        )

    def _on_carry_changed(self, _index: int) -> None:
        if self._carry_syncing or self._session is None or self._edits is None:
            return
        socket = str(self._carry_box.currentData() or "")
        binding = self._current_binding()
        if not socket or binding is None or not binding.part.source_file:
            return
        if (binding.part.in_socket or "") == socket:
            return

        previous = binding.part.in_socket or "(none)"
        previous_zone = carry.zone_of(previous)
        try:
            self._edits.set_route(binding.part.source_file, binding.part_name, "in_socket", socket)
        except EditError as exc:
            self.statusBar().showMessage(str(exc))
            self._populate_carry_box()
            return
        # The child socket holds the item's orientation, so a back-slung sword left on the
        # hip's child socket hangs at the hip's angle.
        note = self._follow_child_socket(binding, socket, "stowed")
        self._after_edit()
        self._populate_parts()
        note += self._ensure_blade_hangs_down(socket)
        note += self._warn_if_angle_is_wrong(socket)
        self.statusBar().showMessage(
            f"{self._selected_part} now stows on {socket} (was {previous}){note}"
        )
        self._offer_carry_clips(socket, previous_zone)

    # ── the animation half ──────────────────────────────────────────

    def _offer_carry_clips(self, socket: str, previous_zone: str = "") -> None:
        """Point the clip browser at the draws that start from this carry position."""

        zone = carry.zone_of(socket)
        if not zone:
            return
        if self._carry_index is None:
            self.statusBar().showMessage(
                self.statusBar().currentMessage()
                + "  —  press Match animations to find the draws for it"
            )
            return
        clips = self._carry_index.clips_for_zone(zone)
        if not clips:
            self.statusBar().showMessage(
                f"No draw was measured starting from the "
                f"{carry.ZONE_LABELS.get(zone, zone).lower()} — the item will move, but you "
                f"will need to pick an animation yourself"
            )
            return
        self._carry_filter_zone = zone
        if hasattr(self, "_clip_carry_box"):
            self._clip_carry_box.setChecked(True)
        self._refresh_clip_list()
        self._report_carry_match(zone, previous_zone)

    def _swappable_pairs(self, *, locomotion: bool):
        """`(target, donor)` clip pairs for restyling this weapon to the other handedness.

        Scope is the whole risk. The `1_phm` motion tree is shared with every NPC that uses
        it, so an unfiltered sweep rewrote 121 files including `cd_darkguide` and
        `cd_redwarden` — every boss's draw, for a change to the player's sword.

        Targets are the player's own clips in this weapon's handedness families; donors are
        the matching clips of the other handedness, paired by `clip_signature` so that the
        motion words must agree exactly while the stance and take numbers may differ. Clips
        with no counterpart are skipped — the mod authors hand-made those, which is 31 of the
        141 the two-hand mod ships.
        """

        import collections

        session = self._session
        if session is None or self._clip_index is None:
            return []
        hands = carry.weapon_handedness(session.weapon)
        if not hands:
            return []
        other = "2h" if hands == "1h" else "1h"

        # `00_mon` holds the player's animations as they appear in creature encounters.
        # Neither shipped mod touches that folder, so neither does this.
        entries = [
            e for e in self._clip_index.entries
            if f"/{session.model}/" in e.path and "/00_mon/" not in e.path
        ]
        donors = collections.defaultdict(list)
        for entry in entries:
            signature = carry.clip_signature(entry.name)
            if signature and carry.clip_handedness(entry.name) == other and "_swarm_" not in entry.name:
                donors[signature].append(entry)

        pairs = []
        for entry in entries:
            name = entry.name
            if carry.clip_handedness(name) != hands or "_swarm_" in name:
                continue
            if not (name.startswith("cd_phm_") or name.startswith("cd_prh_")):
                continue
            if not locomotion and not carry.is_draw(name):
                continue
            signature = carry.clip_signature(name)
            candidates = donors.get(signature) if signature else None
            if not candidates:
                continue
            ranked = self._ranked_donors(name, candidates)
            pairs.append((entry, ranked[0], tuple(ranked)))
        pairs.sort(key=lambda row: row[0].name)
        return pairs

    @staticmethod
    def _ranked_donors(target_name: str, candidates):
        """The nearest stand-in, not merely the first one alphabetically.

        Signature matching deliberately ignores the stance and take numbers so that a clip
        with no exact twin still finds one — but among several twins those numbers are the
        only thing distinguishing a stance from a different stance, and picking by name order
        chose between them at random. The exact rename is preferred, then the same stance with
        a different take, and only then anything else.
        """

        wanted = carry.counterpart_names(target_name)
        rank = {name: position for position, name in enumerate(wanted)}
        return sorted(
            candidates, key=lambda entry: (rank.get(entry.name, len(rank)), entry.name)
        )

    def _start_clip_swap(self, pairs) -> str:
        """Start a swap. The reading runs on a worker; see `_on_swap_ready` for the finish.

        The chart is left alone. It names each clip as a length-prefixed full path, so
        retargeting one needs a replacement of identical byte length and none of the 31
        referenced hip draws has one. Overwriting the file behind the path has no such
        constraint, and it is what the shipped mods do.

        The donor is not chosen by measuring where a draw reaches. Measuring says the
        two-hand clips are *hip* draws, because in vanilla the longsword hangs at the hip too
        — there is no back draw to borrow. What makes a back carry look right is using the
        two-hand weapon's animation set, which is a rename.
        """

        pairs = list(pairs)
        if self._edits is None or self._swap_thread is not None or not pairs:
            return ""
        self._carry_swap.setEnabled(False)
        chosen = getattr(self, "_chosen_preview", None)
        if chosen is not None:
            # What the dialog settled, not what happens to sort first.
            self._swap_preview = next(
                ((t, d) for t, d in pairs if d is chosen), self._preview_pair(pairs)
            )
        else:
            self._swap_preview = self._preview_pair(pairs)
        self.statusBar().showMessage(f"Reading {len(pairs)} animation(s)...")
        self._swap_thread = QThread(self)
        self._swap_worker = _SwapWorker(pairs)
        self._swap_worker.moveToThread(self._swap_thread)
        self._swap_thread.started.connect(self._swap_worker.run)
        self._swap_worker.progress.connect(self._on_swap_progress)
        self._swap_worker.done.connect(self._on_swap_ready)
        self._swap_thread.start()
        return f"reading {len(pairs)} animation(s)"

    @staticmethod
    def _preview_pair(pairs):
        """Which replacement to show afterwards: the plain standing draw, if there is one.

        This used to be whatever sorted first, which meant choosing a standing draw and then
        being shown a running one — the animation that played was not among the options that
        had just been offered, so the choice looked as though it had been ignored. The draw
        from a standing start is the one the choice was about, so it is the one to play.
        """

        from .clip_names import action_of, context_of

        def rank(pair):
            name = pair[0].name
            return (
                0 if action_of(name) == "take the weapon out" else 1,
                0 if context_of(name) == "standing" else 1,
                0 if not name.endswith("_lod") else 1,
                name,
            )

        return min(pairs, key=rank)

    def _on_swap_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(f"Reading animations… {done}/{total}")

    def _on_swap_ready(self, payload, error: str) -> None:
        """Record the read clips as edits, then show the result."""

        self._stop_swap()
        self._carry_swap.setEnabled(True)
        if not payload:
            self.statusBar().showMessage(error or "No animations were swapped")
            return
        applied = 0
        for path, data, donor_name in payload:
            try:
                self._edits.replace_clip(path, data, donor_name)
                applied += 1
            except EditError:
                continue
        self._after_edit()
        self.statusBar().showMessage(
            f"{applied} animation file(s) replaced — see Pending changes, "
            f"or press Play to watch the new one"
        )
        self._show_swap_result(applied)

    def _stop_swap(self) -> None:
        if self._swap_worker is not None:
            self._swap_worker.stop()
        if self._swap_thread is not None:
            self._swap_thread.quit()
            self._swap_thread.wait(3000)
            self._swap_thread = None
            self._swap_worker = None

    def _show_swap_result(self, applied: int) -> None:
        """Play the animation the swap installed, on the rig, in its new placement.

        The *donor* clip is played, not the target path: the studio reads clips from the game
        archives, so loading the target would replay the vanilla animation that the mod is
        replacing — the one thing that would not show whether the swap worked.
        """

        preview = getattr(self, "_swap_preview", None)
        if preview is None:
            return
        target, donor = preview
        binding = self._current_binding()
        where = getattr(getattr(binding, "part", None), "in_socket", "") or "(unrouted)"
        self.statusBar().showMessage(
            f"{applied} animation file(s) replaced. {target.name} now plays {donor.name}; "
            f"the weapon hangs on {where}."
        )
        if getattr(self, "_play_after_swap", True):
            self._play_clip_entry(donor)
            # Loading only poses the first frame. Seeing whether a draw works means watching
            # it run, and run again — the motion is under a second long.
            self._playback_loop_box.setChecked(True)
            if self._playback.loaded and not self._playback.playing:
                self._on_playback_toggle()

    def _on_swap_clicked(self) -> None:
        """Open the one dialog that does the whole move.

        Everything the operation needs is asked in one place and applied on OK: where the item
        hangs, whether its animations come along, at what scope, and — because the list is
        editable — exactly which files.
        """

        from .move_weapon import MoveWeaponDialog

        session = self._session
        if session is None or self._edits is None or self._swap_thread is not None:
            return
        binding = self._current_binding()
        parts = [
            (b.part_name, f"{b.part_name}   —   {b.part.in_socket or '(nowhere)'}")
            for b in session.bindings()
            if b.part.category != "other"
        ] or [(b.part_name, b.part_name) for b in session.bindings()]

        dialog = MoveWeaponDialog(
            self,
            parts=parts,
            positions=carry.carry_positions(session),
            current_part=self._selected_part,
            current_socket=getattr(getattr(binding, "part", None), "in_socket", "") or "",
            pairs_for=lambda locomotion=False: self._swappable_pairs(locomotion=locomotion),
            handedness=carry.weapon_handedness(session.weapon),
            on_preview=self._preview_clip,
        )
        # `QDialog.Accepted` is a class constant, not an instance attribute: reading it off
        # the instance raised, so nothing was applied and — under pythonw, with no console —
        # nothing was reported either. Pressing "Move it" appeared to do nothing at all.
        if dialog.exec() != QDialog.Accepted:
            return
        plan = dialog.plan()
        if plan.part_name and plan.part_name != self._selected_part:
            self._selected_part = plan.part_name
            self._sync_part_box(plan.part_name)
        if plan.moves:
            self._apply_carry_move(plan.socket)
        if plan.clips:
            self._play_after_swap = plan.play_after
            self._chosen_preview = plan.preview
            self._start_clip_swap(plan.clips)
        elif plan.moves:
            self.statusBar().showMessage(
                f"{plan.part_name} now hangs on {plan.socket}. Animations left alone."
            )

    def _show_history(self) -> None:
        """What has been done so far, newest first, with a way back to any point.

        Undo already existed on Ctrl+Z, but a swap lands 52 file replacements at once and
        "press undo the right number of times" is not a workable answer to "I did not mean
        that". This lists the steps and rewinds to whichever one is chosen.
        """

        from PySide6.QtWidgets import QListWidget, QVBoxLayout

        if self._edits is None:
            return
        applied = self._edits.commands()
        dialog = QDialog(self)
        dialog.setWindowTitle("Recent actions")
        dialog.setMinimumSize(680, 380)
        listing = QListWidget()
        for position, command in reversed(list(enumerate(applied))):
            listing.addItem(f"{position + 1}.  {command.describe()}")
        if not applied:
            listing.addItem("(nothing has been changed yet)")
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        undo_to = buttons.addButton("Undo back to here", QDialogButtonBox.ActionRole)
        undo_to.setToolTip("Undo every step above the one selected, newest first.")
        undo_to.setEnabled(bool(applied))

        def _rewind() -> None:
            row = listing.currentRow()
            if row < 0 or not applied:
                return
            # The list is newest-first, so the row index is how many steps to take back.
            for _ in range(row + 1):
                if not self._edits.undo():
                    break
            self._after_edit()
            self._populate_parts()
            self.statusBar().showMessage(f"Undid {row + 1} step(s)")
            dialog.accept()

        undo_to.clicked.connect(_rewind)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Newest first. Select a step and undo back to it."))
        layout.addWidget(listing, 1)
        layout.addWidget(buttons)
        dialog.exec()

    def _preview_clip(self, entry) -> None:
        """Play one clip from inside the move dialog, so a style can be judged by watching."""

        if entry is None:
            return
        self._play_clip_entry(entry)
        self._playback_loop_box.setChecked(True)
        if self._playback.loaded and not self._playback.playing:
            self._on_playback_toggle()

    def _apply_carry_move(self, socket: str) -> None:
        """Re-route the selected part and bring its angle with it."""

        binding = self._current_binding()
        if binding is None or self._edits is None or not binding.part.source_file:
            return
        previous = binding.part.in_socket or "(none)"
        try:
            self._edits.set_route(
                binding.part.source_file, binding.part_name, "in_socket", socket
            )
        except EditError as exc:
            self.statusBar().showMessage(str(exc))
            return
        note = self._follow_child_socket(binding, socket, "stowed")
        self._after_edit()
        self._populate_parts()
        note += self._ensure_blade_hangs_down(socket)
        note += self._warn_if_angle_is_wrong(socket)
        self.statusBar().showMessage(
            f"{self._selected_part} now hangs on {socket} (was {previous}){note}"
        )

    def _report_carry_match(self, zone: str, previous_zone: str = "") -> None:
        """Say plainly what the move did to the animations — including what it did not do.

        The honest part matters more than the counts. Picking a carry position re-routes the
        item and narrows this list; it does **not** rewrite the action charts, so the mod still
        plays whatever draw it played before. That cannot currently be changed safely: a chart
        stores each clip as a length-prefixed full path, and a swap has to keep the byte length
        identical. Measured across every chart for this rig, none of the 31 referenced hip
        draws has a same-length replacement among the back draws — the paths differ in length.
        So the tool shows the right clip to use and says so, rather than pretending to set it.
        """

        index = self._carry_index
        if index is None:
            return
        label = carry.ZONE_LABELS.get(zone, zone)
        draws = index.clips_for_zone(zone, sheathe=False)
        sheathes = index.clips_for_zone(zone, sheathe=True)
        lines = []
        if previous_zone and previous_zone != zone:
            was = carry.ZONE_LABELS.get(previous_zone, previous_zone)
            before = len(index.clips_for_zone(previous_zone, sheathe=False))
            lines.append(f"Carried on the {was.lower()} before, now the {label.lower()}.")
            lines.append(f"Draws that start there: {before} before, {len(draws)} now.")
        else:
            lines.append(f"Carried on the {label.lower()}.")
        lines.append("")
        lines.append(f"Best draw for this spot:     {draws[0] if draws else '(none found)'}")
        lines.append(f"Best put-away for this spot: {sheathes[0] if sheathes else '(none found)'}")
        lines.append("")
        lines.append(
            f"The Clips & animation list is now filtered to these {len(draws) + len(sheathes)} "
            f"clip(s). Double-click one to watch it."
        )
        lines.append("")
        swapped = ""
        if swapped:
            lines.append(
                f"Animations swapped: {swapped}. The action charts are untouched — the new "
                f"animation is written in place of the old one. Check Pending changes to see "
                f"exactly which files."
            )
        else:
            lines.append(
                "The placement is a pending change and will be exported. No animation was "
                "swapped — either nothing was measured for the old position, or this is the "
                "position the item already had."
            )
        box = QMessageBox(self)
        box.setWindowTitle("Animations for this carry position")
        box.setIcon(QMessageBox.Information)
        box.setText("\n".join(lines))
        box.exec()

    def _carry_clip_ranking(self):
        """clip name -> sort position: draws before sheathes, clearest reach first."""

        zone = getattr(self, "_carry_filter_zone", "")
        if not zone or self._carry_index is None:
            return {}
        ordered = self._carry_index.clips_for_zone(zone, sheathe=False)
        ordered += self._carry_index.clips_for_zone(zone, sheathe=True)
        return {name: position for position, name in enumerate(ordered)}

    def _carry_zone_filter(self):
        """The clip names the browser should restrict to, or `None` for no restriction."""

        zone = getattr(self, "_carry_filter_zone", "")
        if not zone or self._carry_index is None:
            return None
        if hasattr(self, "_clip_carry_box") and not self._clip_carry_box.isChecked():
            return None
        return set(self._carry_index.clips_for_zone(zone))

    # ── measuring ───────────────────────────────────────────────────

    def _carry_cache_file(self) -> Path:
        from .corpus import work_root

        model = self._session.model if self._session else "unknown"
        return Path(work_root()) / f"carry-index-{model}.json"

    def _load_carry_cache(self) -> bool:
        path = self._carry_cache_file()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if raw.get("scoring") != _CACHE_VERSION:
            return False
        index = carry.CarryIndex.from_json(raw.get("index"))
        if not len(index):
            return False
        self._carry_index = index
        self._refresh_carry_status()
        return True

    def _save_carry_cache(self) -> None:
        if self._carry_index is None:
            return
        try:
            path = self._carry_cache_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"scoring": _CACHE_VERSION, "index": self._carry_index.to_json()}),
                encoding="utf-8",
            )
        except OSError:
            pass  # a failed write costs a re-measure, nothing more

    def _start_carry_index(self, *, explicit: bool = False) -> None:
        if self._carry_thread is not None or self._session is None:
            return
        if self._load_carry_cache():
            if explicit:
                self.statusBar().showMessage("Carry animations already measured")
                socket = str(self._carry_box.currentData() or "")
                if socket:
                    self._offer_carry_clips(socket)
            return

        model = self._session.model
        entries = [
            entry
            for entry in self._clip_index.entries
            if carry.is_draw(entry.name) and model in entry.path and not entry.is_lod
        ]
        if not entries:
            self.statusBar().showMessage(
                "No draw clips indexed yet — wait for the clip index, then try again"
            )
            return

        self._carry_match.setEnabled(False)
        self._carry_status.setText(f"measuring 0/{len(entries)}...")
        self._carry_thread = QThread(self)
        self._carry_worker = _CarryWorker(model, entries)
        self._carry_worker.moveToThread(self._carry_thread)
        self._carry_thread.started.connect(self._carry_worker.run)
        self._carry_worker.progress.connect(self._on_carry_progress)
        self._carry_worker.done.connect(self._on_carry_index_ready)
        self._carry_thread.start()

    def _on_carry_progress(self, done: int, total: int) -> None:
        self._carry_status.setText(f"measuring {done}/{total}...")

    def _on_carry_index_ready(self, index, error: str) -> None:
        self._stop_carry_index()
        self._carry_match.setEnabled(True)
        if index is None:
            self._carry_status.setText(error or "measuring cancelled")
            return
        self._carry_index = index
        self._save_carry_cache()
        self._refresh_carry_status()
        socket = str(self._carry_box.currentData() or "")
        if socket:
            self._offer_carry_clips(socket)

    def _stop_carry_index(self) -> None:
        if self._carry_worker is not None:
            self._carry_worker.stop()
        if self._carry_thread is not None:
            self._carry_thread.quit()
            self._carry_thread.wait(3000)
            self._carry_thread = None
            self._carry_worker = None
