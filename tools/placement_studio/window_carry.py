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

from PySide6.QtCore import QObject, Qt, QThread, Signal
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
from .glossary import MATCH_LABEL, tip

#: Bumped when a threshold in `carry` changes, so a cache built under the old scoring is
#: rebuilt rather than quietly kept.
_CACHE_VERSION = 4


class _CarryWorker(QObject):
    """Measures where every draw clip reaches, on its own session and its own thread."""

    done = Signal(object, str)
    progress = Signal(int, int)

    def __init__(self, model: str, clip_entries, *, source=None, files=()) -> None:
        super().__init__()
        self._model = model
        self._entries = list(clip_entries)
        self._stop = False
        self._source = source
        self._files = tuple(files)
        self.errors = ()

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
            if self._source is None:
                session = PlacementSession.from_baseline(Baseline.load(), self._model)
            else:
                from .resolver import PlacementResolver
                resolver = PlacementResolver()
                resolver.add_files(dict(self._files))
                session = PlacementSession(self._model, self._source._bind_hierarchy or self._source.hierarchy, resolver,
                                           skeleton_path=self._source.skeleton_path)
        except Exception as error:  # noqa: BLE001 - report, never take the window down
            self.done.emit(None, str(error))
            return

        total = len(self._entries)
        index = carry.CarryIndex()
        names = carry.stow_positions(session)
        errors = []
        for done, entry in enumerate(self._entries, start=1):
            if self._stop:
                self.done.emit(None, "")
                return
            try:
                index.add(entry.name, carry.reach_of_clip(session, load_clip(read_clip(entry), "d"), names))
            except Exception as error:  # one failed optional measurement leaves explicit incomplete coverage
                errors.append(f'{entry.path}: {error}')
            if done % 25 == 0:
                self.progress.emit(done, total)
        self.errors = tuple(errors)
        self.done.emit(index, '\n'.join(errors))


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
            except Exception as error:  # noqa: BLE001 - publish no partial selection
                self.done.emit(None, f"Could not read {donor.path}: {error}. Nothing was changed.")
                return
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

        self._carry_match = QPushButton(f"{MATCH_LABEL} (~30s)")
        self._carry_match.setToolTip(
            tip(MATCH_LABEL,
                "Safe to press: it only looks. Every draw is played and the hands watched, to "
                "work out which carry position each one starts from — about half a minute, "
                "remembered afterwards. Nothing about the mod changes; it prints a report.")
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
            self._carry_status.setText(f"press {MATCH_LABEL} to link clips to positions")
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
        """The one-control move: re-route the selected item, as one placement operation.

        Placement only. Changing where a weapon hangs never silently rewrites animations from
        here — the dialog is where that decision is made, reviewed and confirmed.
        """

        from .move_operation import MoveRequest, plan_move

        if self._carry_syncing or self._session is None or self._edits is None:
            return
        socket = str(self._carry_box.currentData() or "")
        binding = self._current_binding()
        if not socket or binding is None or not binding.part.source_file:
            return
        if (binding.part.in_socket or "") == socket:
            return

        previous_zone = carry.zone_of(binding.part.in_socket or "")
        unit, error = self._resolve_unit(binding.part_name)
        if unit is None:
            self.statusBar().showMessage(error)
            self._populate_carry_box()
            return

        request = MoveRequest(
            unit=unit,
            destination_socket=socket,
            scope=carry.AnimationScope(carry.SCOPE_PLACEMENT_ONLY),
            # The quick control cannot show an orientation for review, so it only proceeds
            # where the aim resolves from the item's own sockets. Anything needing a borrowed
            # or hand-authored angle belongs in the dialog, which can show it.
            orientation_reviewed=False,
        )
        plan = plan_move(self._session, self._edits, request)
        if plan.blocked:
            self.statusBar().showMessage(
                f"Use Swap animations… to move it there: {plan.blockers[0]}"
            )
            self._populate_carry_box()
            return
        self._start_move(plan, play_after=False)
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
                + f"  —  press {MATCH_LABEL} to find the draws for it"
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

    # ── the equipment unit ──────────────────────────────────────────

    def _available_families(self):
        """The animation families this character's clips actually use.

        Narrows a unit's declared target families to what exists, so a two-hand move on Damian
        does not claim Kliff's `longsword` among its own.
        """

        if self._clip_index is None or self._session is None:
            return None
        model = self._session.model
        return {
            carry.family_of(entry.name)
            for entry in self._clip_index.entries
            if f"/{model}/" in entry.path
        } - {""}

    def _resolve_unit(self, part_name: str, *, weapon=None):
        """`(unit, error)` for one descriptor row against an asset.

        Never falls back to the previously selected weapon when the two disagree. That fallback
        is failure mode 3.2: it let one row move while another weapon's animations and child
        sockets were edited.

        `weapon` names the asset explicitly, which packaging needs — it has to resolve the unit
        an *earlier* operation belonged to, and the window's current selection may have moved on.
        """

        from .session import EquipmentResolutionError

        session = self._session
        if session is None or not part_name:
            return None, "Select an item first."
        try:
            unit = session.resolve_equipment_unit(
                part_name,
                weapon=weapon,
                available_families=self._available_families(),
            )
        except EquipmentResolutionError as exc:
            return None, str(exc)
        return unit, ""

    def _resolve_unit_by_id(self, unit_id: str):
        """`(unit, error)` for a recorded equipment-unit id: `model/weapon_id/part`.

        Packaging checks a case row and an animation family against the unit the operation was
        made for, so it has to name the asset rather than take whatever is selected now.
        """

        session = self._session
        parts = str(unit_id or "").split("/")
        if session is None or len(parts) != 3:
            return None, f"{unit_id!r} is not an equipment unit id"
        model, weapon_id, part_name = parts
        if model != session.model:
            return None, f"{unit_id} belongs to {model}, not {session.model}"
        weapon = next((w for w in session.weapons() if w.weapon_id == weapon_id), None)
        if weapon is None:
            return None, f"{weapon_id} is not loaded for {session.model}"
        return self._resolve_unit(part_name, weapon=weapon)

    def _replacements_for(self, unit, scope, *, destination_socket=""):
        """Animation replacements for one equipment unit at one scope.

        Everything that decides the answer comes off `unit`, not off whatever the window has
        selected — which is what let the item dropdown change while the animation pairing kept
        using the old weapon's handedness and families.
        """

        if unit is None or self._clip_index is None:
            return ()
        return carry.swappable_pairs(
            unit,
            self._clip_index.entries,
            scope,
            destination_zone=carry.zone_of(destination_socket or getattr(unit, "in_socket", "") or ""),
            reach_index=getattr(self, "_carry_index", None),
        )

    def _start_move(self, plan, *, play_after: bool = True, preview=None) -> str:
        from .background import LatestTask
        if self._edits is None or plan is None:
            return ""
        self._play_after_swap = play_after
        self._pending_move = plan
        pairs = [(r.target, r.donor) for r in plan.request.replacements]
        self._swap_preview = next(((a, b) for a, b in pairs if b is preview),
                                  self._preview_pair(pairs) if pairs else None)
        if getattr(self, "_move_task", None) is None:
            self._move_task = LatestTask(self)
            self._move_task.ready.connect(self._on_prepared_move_ready)
            self._move_task.progress.connect(self._on_swap_progress)
        self._carry_swap.setEnabled(False)
        self._move_task.submit(self._move_preparation_work(plan))
        self.statusBar().showMessage("Preparing complete operation…")
        return "preparing complete operation"

    def _on_prepared_move_ready(self, scene, error):
        self._carry_swap.setEnabled(True)
        if error or scene is None:
            self._pending_move = None
            self.statusBar().showMessage(f"Nothing was changed: {error or 'cancelled'}")
            return
        self._apply_move_operation(scene.prepared.plan, scene.prepared)

    def _move_preparation_work(self, plan):
        from copy import copy
        from dataclasses import replace
        from .corpus import game_root, package_signature
        from .prepared_move import prepare_move, file_identity
        from .move_preview import build_scene
        from .armour import read_entry, read_armour
        from .skinning import load_skinned
        source = copy(self._session)
        snapshot = self._edits.capture()
        root = game_root()
        baseline = self._baseline
        entries = dict(getattr(self, "_weapon_mesh_entries", {}))
        armour_index = getattr(self, "_armour_index", None)
        body = tuple(getattr(self, "_skinned_meshes", ())) if getattr(self, "_skinned_cache_model", "") == source.model else ()
        body_paths = tuple(self._base_body_paths(source.model)) if hasattr(self, "_base_body_paths") else ()
        body_paths += tuple(sorted(p for p in getattr(self, "_armour_choice", {}).values() if p))
        relationships = getattr(self, "_motion_relationships", None)
        def read_asset(path):
            if relationships is not None and path in relationships.entries:
                return read_entry(relationships.entries[path])
            if path in entries:
                return read_entry(entries[path])
            if path in baseline:
                return baseline.read(path)
            return read_armour(path, armour_index)
        def work(cancelled, progress):
            nonlocal relationships
            root_identity = tuple(tuple(r) for r in package_signature(root))
            if relationships is None or relationships.identity != root_identity:
                from .relationships import inspect_install
                relationships = inspect_install(root, cancelled=cancelled, progress=progress,
                    required_paths=tuple(p for p, _ in snapshot.base))
            selected_entries = tuple(e for r in plan.request.replacements for e in (r.target, r.donor))
            def identity():
                return tuple(sorted(set(tuple(tuple(r) for r in package_signature(root)) + file_identity(selected_entries))))
            prepared = prepare_move(source, snapshot, plan, cancelled=cancelled, progress=progress,
                                    identity=identity, relationships=relationships)
            prepared = replace(prepared, source_root=str(root), root_identity=root_identity)
            loaded = list(body)
            if not loaded and source.has_skeleton:
                parsed = (source._bind_hierarchy or source.hierarchy).parsed
                for path in body_paths:
                    if cancelled():
                        raise RuntimeError("Preparation cancelled")
                    try:
                        mesh = load_skinned(read_asset(path), path, parsed)
                        if mesh is not None:
                            loaded.append(mesh)
                    except (OSError, ValueError, RuntimeError, KeyError):
                        continue  # build_scene exposes incomplete geometry as Unverified.
            scene = build_scene(source, prepared, body=loaded, read_asset=read_asset, cancelled=cancelled,
                                relationships=relationships)
            from .compatibility import assess_scene
            scene.prepared = assess_scene(scene, cancelled=cancelled, read_asset=read_asset)
            from .prepared_move import Check
            current_checks = []
            for file in prepared.files:
                if file.donor_path or not file.changed:
                    continue
                if cancelled():
                    raise RuntimeError('Preparation cancelled')
                original = dict(snapshot.base).get(file.path)
                try:
                    installed = read_asset(file.path)
                    current_checks.append(Check('Installed placement source', 'Passed' if installed == original else 'Blocked',
                        'Session baseline matches the active installation' if installed == original else
                        'Session baseline differs from the active installation; reload current placement files before export', file.path))
                except (ValueError, OSError, KeyError, RuntimeError) as error:
                    current_checks.append(Check('Installed placement source', 'Blocked', str(error), file.path))
            scene.prepared = replace(scene.prepared, checks=scene.prepared.checks + tuple(current_checks),
                files=tuple(replace(f,checks=f.checks + tuple(c for c in current_checks if c.path==f.path)) for f in scene.prepared.files))
            from .candidate_analysis import analyse_candidates
            from .clips import read_clip
            scene.candidates = analyse_candidates(scene, read=read_clip, cancelled=cancelled, progress=progress)
            if identity() != prepared.source_identity:
                raise RuntimeError("Source files changed while preparing geometry; refresh and prepare again")
            return scene
        return work


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
                0 if action_of(name) == "drawing the weapon" else 1,
                0 if context_of(name) == "standing" else 1,
                0 if not name.endswith("_lod") else 1,
                name,
            )

        return min(pairs, key=rank)

    def _on_swap_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(f"Reading animations… {done}/{total}")

    def _on_swap_ready(self, payload, error: str) -> None:
        """The clips are read; now apply the whole move as one operation."""

        self._stop_swap()
        self._carry_swap.setEnabled(True)
        plan = getattr(self, "_pending_move", None)
        if plan is None:
            return
        if error or payload is None:
            self._pending_move = None
            self.statusBar().showMessage(
                error or "Cancelled while reading the animations — nothing was changed"
            )
            return
        self._apply_move_operation(plan, {path: data for path, data, _donor in payload})

    def _apply_move_operation(self, plan, clip_bytes) -> None:
        """Commit the planned move, or report why nothing changed.

        One `EditOperation`: the route changes, the operation-owned child sockets and every
        clip replacement. It lands whole or not at all, and `Recent actions` shows it as one
        row that one undo removes.
        """

        from .move_operation import MoveBlocked, apply_move

        self._pending_move = None
        session, edits = self._session, self._edits
        if session is None or edits is None:
            return
        try:
            from .prepared_move import PreparedMove
            operation = (clip_bytes.apply(session, edits) if isinstance(clip_bytes, PreparedMove)
                         else apply_move(session, edits, plan, clip_bytes=clip_bytes))
        except (MoveBlocked, EditError) as exc:
            self.statusBar().showMessage(f"Nothing was changed: {exc}")
            QMessageBox.warning(self, "The move was not applied", str(exc))
            return

        self._after_edit()
        self._populate_parts()
        self._populate_carry_box()

        requested = len(plan.request.replacements)
        applied = len(operation.replaced_clips())
        # A clip the worker could not read never reaches the payload. That used to vanish into
        # a success message, so a partly applied swap read as a whole one.
        unchanged = requested - applied
        note = f" ({unchanged} identical selections excluded)" if unchanged > 0 else ""
        destination = plan.request.destination_socket
        diagnostic = self._orientation_diagnostic(destination) if plan.placement_changes else ""
        self.statusBar().showMessage(
            f"{operation.describe()}{note}.{diagnostic}  —  one action in Recent actions"
        )
        if applied:
            self._show_swap_result(applied, set(operation.replaced_clips()))
        elif plan.placement_changes:
            self._report_move(plan, operation, diagnostic)

    def _report_move(self, plan, operation, diagnostic: str) -> None:
        """Say what moved, in the words the review page used."""

        lines = [operation.describe(), ""]
        lines += [route.describe() for route in plan.routes]
        if diagnostic:
            lines += ["", diagnostic.strip()]
        lines += [
            "",
            "Only this operation will be packaged. Earlier operations stay in Recent actions "
            "until you select them.",
        ]
        box = QMessageBox(self)
        box.setWindowTitle("Moved")
        box.setIcon(QMessageBox.Information)
        box.setText("\n".join(lines))
        box.exec()

    def _stop_swap(self) -> None:
        task = getattr(self, "_move_task", None)
        if task is not None:
            task.cancel()
        if self._swap_worker is not None:
            self._swap_worker.stop()
        thread = self._swap_thread
        if thread is not None:
            from .background import _retained, _release
            worker = self._swap_worker
            thread.setParent(None)
            _retained.add(thread)
            thread.quit()
            thread.finished.connect(lambda: _release(thread))
            thread.finished.connect(lambda: worker.deleteLater() if worker is not None else None)
            if thread.wait(0):
                _release(thread)
            self._swap_thread = None
            self._swap_worker = None


    def _show_swap_result(self, applied: int, written=None) -> None:
        """Play the animation the swap installed, on the rig, in its new placement.

        The *donor* clip is played, not the target path: the studio reads clips from the game
        archives, so loading the target would replay the vanilla animation that the mod is
        replacing — the one thing that would not show whether the swap worked.
        """

        preview = getattr(self, "_swap_preview", None)
        if preview is None:
            return
        target, donor = preview
        if written is not None and target.path not in written:
            self.statusBar().showMessage(
                f"{applied} animation file(s) replaced, but {target.name} was not among "
                f"them — its selected payload was unchanged."
            )
            return
        binding = self._current_binding()
        where = getattr(getattr(binding, "part", None), "in_socket", "") or "(unrouted)"
        self.statusBar().showMessage(
            f"{applied} animation file(s) replaced. {target.name} now plays {donor.name}; "
            f"the weapon hangs on {where}."
        )
        if getattr(self, "_play_after_swap", True):
            self._play_clip_entry(donor, autoplay=True)
            # Loading only poses the first frame. Seeing whether a draw works means watching
            # it run, and run again — the motion is under a second long.
            self._playback_loop_box.setChecked(True)
            if self._playback.loaded and not self._playback.playing:
                self._on_playback_toggle()

    def _on_swap_clicked(self) -> None:
        """Open the one dialog that does the whole move.

        The equipment unit is resolved *before* the dialog opens, and the dialog re-resolves it
        whenever the item changes. Nothing downstream reads the window's selection again, so a
        row and an asset cannot diverge into a mixed operation part-way through.
        """

        from .move_operation import plan_move
        from .move_weapon import MoveWeaponDialog

        session = self._session
        if session is None or self._edits is None or self._swap_thread is not None:
            return
        # Donor clips come out of the clip index, which is not built until its tab is opened
        # and this button is in the header, reachable without ever going there. The dialog
        # builds its row list inside its constructor, so the index has to be *there*, not
        # merely started — otherwise it opens saying no animation has a counterpart.
        self._ensure_clip_index()

        unit, error = self._resolve_unit(self._selected_part or "")
        if unit is None:
            QMessageBox.warning(self, "This item cannot be moved yet", error)
            self.statusBar().showMessage(error)
            return

        parts = [
            (b.part_name, f"{b.part_name}   —   {b.part.in_socket or '(nowhere)'}")
            for b in session.bindings()
            if b.part.category != "other"
        ] or [(b.part_name, b.part_name) for b in session.bindings()]

        dialog = MoveWeaponDialog(
            self,
            unit=unit,
            parts=parts,
            positions=carry.carry_positions(session),
            unit_for=self._resolve_unit,
            pairs_for=self._replacements_for,
            plan_for=lambda request: plan_move(session, self._edits, request),
            on_preview=self._preview_clip,
            on_preview_placement=self._preview_planned_placement,
            on_show_files=self._show_planned_files,
            chart_lanes=getattr(self, "_chart_lanes_cache", None) or {},
            earlier_operations=[op.operation_id for op in self._edits.operations()],
            prepare_for=self._move_preparation_work,
            weapons=session.weapons(),
            unit_for_weapon=lambda part, weapon: self._resolve_unit(part, weapon=weapon),
        )
        if getattr(self, "_clip_scan", None) is not None:
            from PySide6.QtCore import QTimer
            timer = QTimer(dialog)
            timer.setInterval(100)
            dialog._index_pending = True
            dialog._check_summary.setText("Indexing animations… placement controls remain available")
            dialog._preview_placement.setEnabled(False)
            def update_index():
                if getattr(self, "_clip_scan", None) is None:
                    timer.stop()
                    dialog._index_pending = False
                    dialog._reload_clips()
                    dialog._refresh()
                    dialog._preview_placement.setEnabled(True)
            timer.timeout.connect(update_index)
            timer.start()
        # `QDialog.Accepted` is a class constant, not an instance attribute: reading it off
        # the instance raised, so nothing was applied and — under pythonw, with no console —
        # nothing was reported either. Pressing "Move it" appeared to do nothing at all.
        if dialog.exec() != QDialog.Accepted:
            return
        plan = dialog.plan()
        if plan is None:
            return
        chosen_part = plan.unit.primary_part
        if chosen_part and chosen_part != self._selected_part:
            self._selected_part = chosen_part
            self._sync_part_box(chosen_part)
        prepared = dialog.prepared() if hasattr(dialog, "prepared") else None
        if prepared is not None:
            self._play_after_swap = dialog.play_after
            pairs = [(r.target, r.donor) for r in plan.request.replacements]
            self._swap_preview = self._preview_pair(pairs) if pairs else None
            self._apply_move_operation(plan, prepared)
        else:
            self._start_move(plan, play_after=dialog.play_after, preview=dialog.preview_clip())

    def _preview_planned_placement(self, plan) -> None:
        # All previews live in the workspace, against private resolver/pose state.
        self.statusBar().showMessage("Use Prepare preview in the replacement workspace to compare Before and After")


    def _show_planned_files(self, plan) -> None:
        """The exact files a planned move would write, before it is accepted."""

        if plan is None:
            return
        lines = ["Descriptor files", "----------------"]
        lines += sorted({route.source_file for route in plan.routes if route.source_file}) or ["  (none)"]
        lines += ["", "Socket files", "------------"]
        lines += sorted({file for file, _name in plan.new_sockets}) or ["  (none)"]
        clips = [row.target_path for row in plan.request.replacements]
        lines += ["", f"Animation files ({len(clips)})", "----------------"]
        lines += clips
        box = QMessageBox(self)
        box.setWindowTitle("Files this operation would write")
        box.setIcon(QMessageBox.Information)
        box.setText(f"{len(clips)} animation files. Expand Details for the complete file list.")
        box.setDetailedText("\n".join(lines))
        box.exec()

    def _show_history(self) -> None:
        """One row per operation, with the whole operation as the unit of undo.

        A move plus fourteen animation replacements used to be fifteen history entries, and
        "press undo the right number of times" is not a workable answer to "I did not mean
        that". An operation is what the user accepted, so it is what they get to take back —
        and what they get to include in or exclude from a package.
        """

        from PySide6.QtWidgets import QListWidget, QVBoxLayout

        if self._edits is None:
            return
        operations = self._edits.operations()
        loose = self._edits.loose_commands()
        dialog = QDialog(self)
        dialog.setWindowTitle("Recent actions")
        dialog.setMinimumSize(760, 420)
        listing = QListWidget()
        for operation in reversed(operations):
            listing.addItem("\n".join(operation.summary_lines()))
            listing.item(listing.count() - 1).setData(Qt.UserRole, operation.operation_id)
        if loose:
            listing.addItem(
                f"{len(loose)} free-form edit(s) outside any operation — never packaged"
            )
            listing.item(listing.count() - 1).setData(Qt.UserRole, "")
        if not operations and not loose:
            listing.addItem("(nothing has been changed yet)")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        undo = buttons.addButton("Undo operation", QDialogButtonBox.ActionRole)
        undo.setToolTip("Take back the newest operation whole, in one step.")
        undo.setEnabled(bool(operations) or bool(loose))
        redo = buttons.addButton("Redo operation", QDialogButtonBox.ActionRole)
        redo.setEnabled(self._edits.can_redo)
        discard = buttons.addButton("Discard selected", QDialogButtonBox.ActionRole)
        discard.setToolTip(
            "Remove the selected operation wherever it sits in the history. The others are "
            "replayed without it, so nothing of it is left behind."
        )
        discard.setEnabled(bool(operations))
        clean = buttons.addButton("Start clean operation", QDialogButtonBox.ActionRole)
        clean.setToolTip(
            "Drop every free-form edit, keeping the accepted operations. The next move then "
            "starts from vanilla plus what was actually decided."
        )
        clean.setEnabled(bool(loose))
        reset = buttons.addButton("Reset all pending changes", QDialogButtonBox.ResetRole)
        reset.setToolTip("Throw away everything in this session, operations included.")
        reset.setEnabled(bool(operations) or bool(loose))

        def _selected_id() -> str:
            item = listing.currentItem()
            return str(item.data(Qt.UserRole) or "") if item is not None else ""

        def _after(message: str) -> None:
            self._after_edit()
            self._populate_parts()
            self._populate_carry_box()
            self.statusBar().showMessage(message)
            dialog.accept()

        def _undo() -> None:
            operation_id = self._edits.undo_operation()
            _after(f"Undid {operation_id or 'the last free-form edit'}")

        def _redo() -> None:
            operation_id = self._edits.redo_operation()
            _after(f"Redid {operation_id or 'the last free-form edit'}")

        def _discard() -> None:
            operation_id = _selected_id()
            if not operation_id:
                self.statusBar().showMessage("Select an operation to discard")
                return
            if self._edits.discard_operation(operation_id):
                _after(f"Discarded {operation_id}")

        def _clean() -> None:
            dropped = self._edits.start_clean_operation()
            _after(f"Dropped {dropped} free-form edit(s); {len(operations)} operation(s) kept")

        def _reset() -> None:
            confirmed = QMessageBox.question(
                dialog,
                "Reset all pending changes?",
                f"This throws away {len(operations)} operation(s) and {len(loose)} free-form "
                f"edit(s). The game files are untouched either way — only this session's "
                f"pending changes are lost.",
            )
            if confirmed != QMessageBox.Yes:
                return
            self._edits.reset()
            _after("Reset every pending change")

        undo.clicked.connect(_undo)
        redo.clicked.connect(_redo)
        discard.clicked.connect(_discard)
        clean.clicked.connect(_clean)
        reset.clicked.connect(_reset)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                "Newest first. Each row is one accepted operation — one undo, and one entry to "
                "include in or leave out of a package."
            )
        )
        layout.addWidget(listing, 1)
        layout.addWidget(buttons)
        dialog.exec()

    def _chart_lane_index(self) -> dict:
        """Where each clip is used, from the charts. Built once, then cached on disk."""

        cached = getattr(self, "_chart_lanes_cache", None)
        if cached is not None:
            return cached
        from .chart_lanes import load
        from .corpus import game_root

        try:
            cached = load(game_root(), self._session.model if self._session else "")
        except Exception:  # noqa: BLE001 - without it the lanes fall back to file names
            cached = {}
        self._chart_lanes_cache = cached
        return cached

    def _preview_clip(self, entry) -> None:
        """Play one clip from inside the move dialog, so a style can be judged by watching."""

        if entry is None:
            return
        self._play_clip_entry(entry, autoplay=True)


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

    def _carry_session_signature(self):
        from hashlib import sha256
        from .documents import is_socket_file, is_descriptor_file
        edits = getattr(self, '_edits', None)
        files = edits.current_files() if edits is not None else {}
        return [(p,sha256(b).hexdigest()) for p,b in sorted(files.items()) if is_socket_file(p) or is_descriptor_file(p)]

    def _load_carry_cache(self) -> bool:
        path = self._carry_cache_file()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if raw.get("scoring") != _CACHE_VERSION:
            return False
        from .corpus import game_root, package_signature
        if raw.get("source_identity") != package_signature(game_root()):
            return False
        if raw.get('session_signature') != [list(r) for r in self._carry_session_signature()]:
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
                json.dumps({"scoring": _CACHE_VERSION, "index": self._carry_index.to_json(),
                            "source_identity": getattr(self, "_carry_source_identity", None),
                            "session_signature": getattr(self, '_carry_signature', None)}),
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

        # The index is built when the clip tab is first opened, and this button can be
        # pressed without ever going there. Read in the same turn, so it has to be built
        # rather than merely started, or the first press always reports nothing to measure.
        self._ensure_clip_index()
        if not self.clip_index_ready:
            self._when_clips_ready('carry-analysis', lambda: self._start_carry_index(explicit=explicit))
            return

        model = self._session.model
        from .corpus import game_root, package_signature
        self._carry_source_identity = package_signature(game_root())
        self._carry_signature = self._carry_session_signature()
        entries = [
            entry
            for entry in self._clip_index.entries
            if carry.is_draw(entry.name) and model in entry.path and not entry.is_lod
        ]
        if not entries:
            self.statusBar().showMessage("No draw clips found for this character")
            return

        self._carry_match.setEnabled(False)
        self._carry_status.setText(f"measuring 0/{len(entries)}...")
        self._carry_thread = QThread(self)
        from copy import copy
        self._carry_worker = _CarryWorker(model, entries, source=copy(self._session), files=tuple(self._edits.current_files().items()))
        self._carry_worker.moveToThread(self._carry_thread)
        self._carry_thread.started.connect(self._carry_worker.run)
        self._carry_worker.progress.connect(self._on_carry_progress)
        self._carry_worker.done.connect(self._on_carry_index_ready)
        self._carry_thread.start()

    def _on_carry_progress(self, done: int, total: int) -> None:
        self._carry_status.setText(f"measuring {done}/{total}...")

    def _on_carry_index_ready(self, index, error: str) -> None:
        from .corpus import game_root, package_signature
        if getattr(self, "_carry_source_identity", None) != package_signature(game_root()):
            index, error = None, "Installation changed during carry analysis; refresh required"
        if getattr(self, '_carry_signature', None) != self._carry_session_signature():
            index, error = None, 'Placement changed during carry analysis; prepare again'
        self._stop_carry_index()
        self._carry_match.setEnabled(True)
        if index is None:
            self._carry_status.setText(error or "measuring cancelled")
            return
        self._carry_index = index
        if not error:
            self._save_carry_cache()
        self._refresh_carry_status()
        if error:
            self._carry_status.setText(f'Draw analysis incomplete: {len(error.splitlines())} unreadable clips')
            self._carry_status.setToolTip(error)
        socket = str(self._carry_box.currentData() or "")
        if socket:
            self._offer_carry_clips(socket)

    def _stop_carry_index(self) -> None:
        if self._carry_worker is not None:
            self._carry_worker.stop()
        if self._carry_thread is not None:
            from .background import _retained, _release
            thread = self._carry_thread
            thread.setParent(None)
            thread._worker_reference = self._carry_worker
            _retained.add(thread)
            thread.finished.connect(lambda: _release(thread))
            thread.quit()
            self._carry_thread = None
            self._carry_worker = None
