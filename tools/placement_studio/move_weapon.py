"""One dialog for the whole job: move a weapon, and take its animations with it.

The job was previously spread across four controls in three places — pick the part in the
header, change where it hangs in a second dropdown, press a third button for the animations,
then answer two more prompts about scope. Each step was reasonable and the sequence was not
discoverable, because nothing on screen said these were one operation.

Here they are one form, in the order the question is actually asked: *which item, from where
to where, and do the animations come along?* Nothing is applied until OK, and the list of
animation files is shown and editable, so "which animations" is answered by looking rather
than by trusting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .palette import _BORROWED


class _Choice:
    """One decision, covering every clip that asks the same question.

    The game keeps several takes of each moment — `weapon_in_000`, `_002`, `_004` and their
    distance copies — and picks between them at runtime for variety. Asking which stand-in to
    use for each of those separately produced twenty rows of "put the weapon away, version 4"
    with identical-looking answers, which is not a question anyone can act on.

    So the choice is made once per *kind* of animation, and what is being chosen is a style:
    every clip in the group then takes the stand-in of that style matching its own take.
    """

    def __init__(self, label: str, styles, on_preview=None) -> None:
        self.label = label
        self.box = QComboBox()
        self._examples = {}
        for style, text, example, entry in styles:
            self.box.addItem(text, style)
            self.box.setItemData(self.box.count() - 1, example, Qt.ToolTipRole)
            self._examples[style] = entry

        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.box, 1)
        self.preview = QPushButton("Watch")
        # "Style 1" against "Style 2" is not a question anyone can answer from the name: the
        # two differ only in stance, which has no word for it. Being able to watch each one
        # is what turns it into a real choice.
        self.preview.setToolTip("Play this style on the character so you can see it.")
        self.preview.setMaximumWidth(72)
        if on_preview is None:
            self.preview.setEnabled(False)
        else:
            self.preview.clicked.connect(lambda: on_preview(self.example()))
        row.addWidget(self.preview)

    def style(self) -> str:
        return str(self.box.currentData() or "")

    def example(self):
        """A clip in the selected style, for the preview to play."""

        return self._examples.get(self.style())


@dataclass(frozen=True, slots=True)
class MovePlan:
    """What the dialog decided. Everything the caller needs to carry it out."""

    part_name: str
    #: Body socket to hang the item on when stowed.
    socket: str
    #: Clip paths to overwrite, paired with the clip whose bytes go there.
    clips: Tuple[Tuple[object, object], ...] = ()
    #: Play the first replaced animation once the change lands, so it can be seen.
    play_after: bool = True
    #: The exact clip to play afterwards — the stand-in for the first decision that was
    #: actually made. Left to the caller to guess, it played whichever pair sorted first,
    #: which was routinely an animation the user had never been offered.
    preview: object = None

    @property
    def moves(self) -> bool:
        return bool(self.socket)


class MoveWeaponDialog(QDialog):
    """Ask which item moves where, and which animations follow it.

    `pairs_for` is called with `locomotion=True/False` and returns `(target, donor)` clip
    entries. It is passed in rather than computed here so the dialog stays testable without a
    game install, and so the expensive part stays in one place.
    """

    def __init__(
        self,
        parent=None,
        *,
        parts: Sequence[Tuple[str, str]] = (),
        positions: Sequence[Tuple[str, str]] = (),
        current_part: str = "",
        current_socket: str = "",
        part_sockets: Optional[dict] = None,
        pairs_for: Optional[Callable[..., Sequence[Tuple[object, object]]]] = None,
        handedness: str = "",
        on_preview: Optional[Callable[[object], None]] = None,
        chart_lanes: Optional[dict] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Move a weapon")
        self.setMinimumWidth(620)
        self._pairs_for = pairs_for or (lambda **_kwargs: [])
        self._on_preview = on_preview
        #: clip -> the situation its action chart puts it in. Empty means every lane falls
        #: back to the file name, which is a guess and is only used when nothing better says.
        self._chart_lanes = dict(chart_lanes or {})
        self._positions = list(positions)
        #: Where each row hangs today. Without it the "Hangs on now" line kept showing the
        #: socket of whichever row happened to be selected when the dialog opened, and
        #: `plan()` compared the destination against *that* — so choosing another item and
        #: moving it to its own current socket silently produced no move at all.
        self._part_sockets = dict(part_sockets or {})

        self._part_box = QComboBox()
        for name, label in parts:
            self._part_box.addItem(label, name)
        position = self._part_box.findData(current_part)
        if position >= 0:
            self._part_box.setCurrentIndex(position)
        self._part_box.setToolTip("The equipment row to move — a sword is a CD_MainWeapon row.")

        self._from_label = QLabel(current_socket or "(not carried anywhere)")
        self._from_label.setStyleSheet("font-weight: bold;")

        self._to_box = QComboBox()
        for socket, label in positions:
            self._to_box.addItem(label, socket)
        position = self._to_box.findData(current_socket)
        if position >= 0:
            self._to_box.setCurrentIndex(position)
        self._to_box.setToolTip("Where it should hang instead.")

        form = QFormLayout()
        form.addRow("Item:", self._part_box)
        form.addRow("Hangs on now:", self._from_label)
        form.addRow("Move it to:", self._to_box)

        # ── animations ──────────────────────────────────────────────
        self._animations = QGroupBox("Also change the animations")
        self._animations.setCheckable(True)
        self._animations.setChecked(True)
        self._animations.setToolTip(
            "Give this weapon the other grip's animations — the two-handed set for a "
            "one-handed weapon, or the reverse.\n\n"
            "The chosen animation is written in place of the old one, so the game keeps "
            "asking for the same file and gets the new motion."
        )
        inner = QVBoxLayout(self._animations)

        if handedness:
            other = "two-handed" if handedness == "1h" else "one-handed"
            inner.addWidget(
                QLabel(f"This is a {'one' if handedness == '1h' else 'two'}-handed weapon, so "
                       f"it will borrow the {other} animations.")
            )
        self._draws_only = QRadioButton("Draws and put-aways only")
        self._draws_only.setChecked(True)
        self._everything = QRadioButton(
            "Everything — also standing, walking, running, turning and sitting"
        )
        self._draws_only.setToolTip("The minimum that makes a moved weapon look right.")
        self._everything.setToolTip(
            "How a weapon is carried changes the whole way the character holds themselves, "
            "not only how they draw it.\n\n"
            "This covers every animation in the weapon's family, so it includes incidental "
            "ones — eating, sitting, climbing — where the stowed weapon is still visible. "
            "Leaving those out would have the weapon snap back to its old pose during them."
        )
        inner.addWidget(self._draws_only)
        inner.addWidget(self._everything)

        self._choices: dict = {}
        # A tree, not a flat list. Every row used to repeat its context — twelve rows each
        # opening "Standing — put the weapon away" — so the words that differed were at the
        # far end of a sentence that was the same every time. The context is the heading now
        # and the row says only what makes it itself.
        self._clip_list = QTreeWidget()
        self._clip_list.setHeaderHidden(True)
        self._clip_list.setColumnCount(3)
        self._clip_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._clip_list.setUniformRowHeights(True)
        self._clip_list.setMinimumHeight(220)
        self._clip_list.setRootIsDecorated(False)
        self._clip_list.setIndentation(14)
        header = self._clip_list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self._clip_list.setColumnWidth(1, 150)
        self._clip_list.setColumnWidth(2, 76)
        self._clip_list.setToolTip(
            "Every file that will be replaced. Untick any you want left alone, or select "
            "one and press Watch to see the animation it would get."
        )
        inner.addWidget(self._clip_list, 1)

        self._play_after = QCheckBox("Play the new animation when this is done")
        self._play_after.setChecked(True)
        self._play_after.setToolTip(
            "Poses the character with the animation that was just installed, in its new "
            "position, so you can see both at once."
        )
        inner.addWidget(self._play_after)

        buttons = QHBoxLayout()
        self._count_label = QLabel("")
        buttons.addWidget(self._count_label, 1)
        watch = QPushButton("Watch selected")
        watch.setToolTip(
            "Play the animation this row would be given, so you can judge every replacement "
            "and not only the ones that offered a choice."
        )
        watch.setEnabled(self._on_preview is not None)
        watch.clicked.connect(self._watch_selected)
        buttons.addWidget(watch)
        for text, checked in (("Select all", True), ("Select none", False)):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, value=checked: self._set_all(value))
            buttons.addWidget(button)
        inner.addLayout(buttons)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Move it")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._animations, 1)
        layout.addWidget(self._buttons)

        # Ticking a row has to move the count, or "which animations" is unanswerable.
        self._clip_list.itemChanged.connect(lambda _i, _c: self._refresh_ok())
        # Both radios, not just one: unchecking "Everything" does not necessarily check
        # "Draws only", so listening to a single button leaves the list showing the old scope.
        self._draws_only.toggled.connect(lambda _c: self._reload_clips())
        self._everything.toggled.connect(lambda _c: self._reload_clips())
        self._animations.toggled.connect(lambda _c: self._reload_clips())
        self._to_box.currentIndexChanged.connect(lambda _i: self._refresh_ok())
        self._part_box.currentIndexChanged.connect(lambda _i: self._on_part_changed())
        self._reload_clips()

    # ── contents ────────────────────────────────────────────────────

    def _on_part_changed(self) -> None:
        """Follow the newly chosen row, so "from" is that row's socket and not the old one."""

        if not self._part_sockets:
            return
        name = str(self._part_box.currentData() or "")
        socket = self._part_sockets.get(name, "")
        self._from_label.setText(socket or "(not carried anywhere)")
        position = self._to_box.findData(socket)
        if position >= 0:
            self._to_box.setCurrentIndex(position)
        self._refresh_ok()

    def _reload_clips(self) -> None:
        """Fill the file list, and reduce it to one decision per kind of animation."""

        import collections

        from .carry import borrowed_from_other_body
        from .clip_names import (
            family_label, friendly, group_key, lane_of, short_label, stance_of,
        )

        self._clip_list.clear()
        self._rows = []
        self._choices = {}
        if not self._animations.isChecked():
            self._rebuild_choice_form()
            self._refresh_ok()
            return

        rows = list(self._pairs_for(locomotion=self._everything.isChecked()))
        # One row per thing you could decide about, not per file. Takes and distance copies
        # of the same moment differ only in ways the game picks for itself, so they share a
        # row, a tick and a style picker.
        # Where every row borrows from the same family — which is the usual case, since a swap
        # runs in one direction — naming it on each row restates the sentence at the top of the
        # dialog twenty-eight times. It is shown only when rows actually differ.
        donor_families = {family_label(row[1].name) for row in rows}
        name_the_donor = len(donor_families) > 1

        lanes = {}
        merged = collections.OrderedDict()
        for row in rows:
            merged.setdefault(group_key(row[0].name), []).append(row)

        # Two rows in a lane that would read alike get the state that separates them, so
        # every row is distinguishable without repeating a word that is already the heading.
        labels = collections.Counter(
            (lane_of(v[0][0].name, self._chart_lanes), short_label(v[0][0].name))
            for v in merged.values()
        )

        for key, members in merged.items():
            target, donor = members[0][0], members[0][1]
            name = lane_of(target.name, self._chart_lanes)
            label = short_label(target.name)
            lane = lanes.get(name)
            if lane is None:
                lane = QTreeWidgetItem(self._clip_list, [name])
                lane.setFirstColumnSpanned(True)
                lane.setExpanded(True)
                lanes[name] = lane
            text = label
            # Both families, not just the one being replaced. `Drawing the weapon · dual
            # swords` named the clip this row *overwrites*, while Watch beside it plays the
            # clip that would replace it — a two-handed draw from the back. Reading the row as
            # a description of what you are about to see is the obvious reading, and it was
            # wrong. The arrow is the same one the tooltip has always used for target ← donor.
            worn, borrowed_family = family_label(target.name), family_label(donor.name)
            if labels[(name, label)] > 1 or worn != borrowed_family:
                text = f"{text}  ·  {worn.lower()}"
                if name_the_donor and borrowed_family and borrowed_family != worn:
                    text = f"{text}  ←  {borrowed_family.lower()}"
            if len(members) > 1:
                text = f"{text}   ({len(members)} files)"

            # A row whose clip comes from the other playable character says so. The two rigs
            # share most of their bones and the clip plays, but `.paa` keys are bind-pose
            # deltas, so on different proportions the same rotations land somewhere slightly
            # different — a borrowed draw may reach near the hilt rather than onto it. Somebody
            # about to ship a mod built on one should learn that from the row.
            borrowed = [
                row for row in members
                if borrowed_from_other_body(row[0].name, row[1].name)
            ]
            if borrowed:
                text += "   ·  borrowed" if len(borrowed) == len(members) else (
                    f"   ·  {len(borrowed)} borrowed"
                )

            item = QTreeWidgetItem(lane, [text])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked)
            if borrowed:
                item.setForeground(0, _BORROWED)
            item.setToolTip(
                0,
                ("Uses the other character's animation, because this body has none of its own "
                 "for this motion. It plays — the two rigs share most of their bones — but it "
                 "was authored for different proportions, so reaching and contact may be a "
                 "little off.\n\n" if borrowed else "")
                + "\n".join(f"{t0.name}\n   ←  {d0.name}" for t0, d0, *_r in members),
            )

            # The style choice lives on the row it belongs to. It used to sit in a separate
            # block above, so the same thing appeared twice and the list under it looked like
            # a set of rows nobody had decided about.
            styles = {}
            for row in members:
                for option in (row[2] if len(row) > 2 else (row[1],)):
                    styles.setdefault(stance_of(option.name), option)
            choice = None
            if len(styles) > 1:
                ordered = sorted(styles.items())
                choice = _Choice(
                    text,
                    [
                        (stance, f"Style {n + 1}",
                         f"{friendly(example.name)}\n     {example.name}", example)
                        for n, (stance, example) in enumerate(ordered)
                    ],
                )
                self._choices[key] = choice
                self._clip_list.setItemWidget(item, 1, choice.box)
            else:
                stand_in = short_label(donor.name)
                if stand_in != label:
                    item.setText(0, f"{text}   ←  {stand_in}")

            if self._on_preview is not None:
                watch = QPushButton("Watch")
                watch.setFlat(True)
                watch.setMaximumWidth(64)
                watch.setToolTip("Play the animation this row would be given.")
                watch.clicked.connect(lambda _c=False, i=item: self._watch_row(i))
                self._clip_list.setItemWidget(item, 2, watch)
            self._rows.append((item, members, choice))

        for name, lane in lanes.items():
            total = sum(
                len(members) for item, members, _c in self._rows if item.parent() is lane
            )
            lane.setText(0, f"{name}   ({total})")
        self._rebuild_choice_form()
        self._refresh_ok()

    def _rebuild_choice_form(self) -> None:
        """Nothing to rebuild: the style pickers live on the rows they belong to."""

        return

    def _watch_selected(self) -> None:
        """Play whatever the selected row would be replaced with."""

        self._watch_row(self._clip_list.currentItem())

    def _watch_row(self, item) -> None:
        """Play the stand-in one row would be given. Lane headings play nothing."""

        if self._on_preview is None or item is None:
            return
        found = next((r for r in self._rows if r[0] is item), None)
        if found is None:
            return
        _item, members, choice = found
        donor = choice.example() if choice is not None else members[0][1]
        if donor is not None:
            self._on_preview(donor)

    def _set_all(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for item, _members, _choice in self._rows:
            item.setCheckState(0, state)
        self._refresh_ok()

    def _chosen_clips(self):
        """Every (target, donor) pair a ticked row stands for."""

        from .clip_names import stance_of

        chosen = []
        for item, members, choice in getattr(self, "_rows", []):
            if item.checkState(0) != Qt.Checked:
                continue
            for row in members:
                target, fallback = row[0], row[1]
                options = row[2] if len(row) > 2 else (fallback,)
                if choice is None:
                    donor = fallback
                else:
                    wanted = choice.style()
                    donor = next(
                        (o for o in options if stance_of(o.name) == wanted), fallback
                    )
                chosen.append((target, donor))
        return tuple(chosen)

    def _undecided(self) -> int:
        """How many rows offer a choice, so the form can say to look at them."""

        return len(getattr(self, "_choices", {}) or {})

    def _refresh_ok(self) -> None:
        chosen = len(self._chosen_clips())
        total = sum(len(m) for _i, m, _c in getattr(self, '_rows', []))
        undecided = self._undecided()
        note = (f"  —  {undecided} need a choice; see above" if undecided else "")
        self._count_label.setText(
            f"{chosen} of {total} animation file(s) selected{note}" if total else
            ("no animation has a counterpart for this weapon"
             if self._animations.isChecked() else "")
        )
        # Moving nowhere and changing nothing is not an edit; refuse it rather than write an
        # empty mod.
        moves = self._to_box.currentData() != self._from_label.text()
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(bool(moves or chosen))

    # ── result ──────────────────────────────────────────────────────

    def plan(self) -> MovePlan:
        socket = str(self._to_box.currentData() or "")
        return MovePlan(
            part_name=str(self._part_box.currentData() or ""),
            socket="" if socket == self._from_label.text() else socket,
            clips=self._chosen_clips(),
            play_after=self._play_after.isChecked(),
            preview=self._preview_choice(),
        )

    def _preview_choice(self):
        """The stand-in to play afterwards: the one the first decision settled.

        A decision the user actually made is the only honest thing to show. Picking a clip
        by any other rule means the animation that plays was never among the options, which
        reads as the choice having been ignored.
        """

        for choice in self._choices.values():
            if "drawing" in choice.label.lower():
                return choice.example()
        for choice in self._choices.values():
            return choice.example()
        # Nothing was ambiguous, so any applied stand-in represents the change equally.
        chosen = self._chosen_clips()
        return chosen[0][1] if chosen else None
