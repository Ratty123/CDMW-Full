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
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


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
        pairs_for: Optional[Callable[..., Sequence[Tuple[object, object]]]] = None,
        handedness: str = "",
        on_preview: Optional[Callable[[object], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Move a weapon")
        self.setMinimumWidth(620)
        self._pairs_for = pairs_for or (lambda **_kwargs: [])
        self._on_preview = on_preview
        self._positions = list(positions)

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

        self._choice_group = QGroupBox("Choose which animation to use")
        self._choice_group.setToolTip(
            "These are the only decisions to make. Everything else has a single obvious "
            "stand-in and is applied without asking."
        )
        self._choice_form = QFormLayout(self._choice_group)
        self._choices: dict = {}
        inner.addWidget(self._choice_group)

        self._clip_list = QListWidget()
        self._clip_list.setSelectionMode(QAbstractItemView.NoSelection)
        self._clip_list.setUniformItemSizes(True)
        self._clip_list.setMinimumHeight(190)
        self._clip_list.setToolTip(
            "Every file that will be replaced, and what replaces it — the detail behind the "
            "choices above. Untick any you want left alone."
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
        self._clip_list.itemChanged.connect(lambda _item: self._refresh_ok())
        # Both radios, not just one: unchecking "Everything" does not necessarily check
        # "Draws only", so listening to a single button leaves the list showing the old scope.
        self._draws_only.toggled.connect(lambda _c: self._reload_clips())
        self._everything.toggled.connect(lambda _c: self._reload_clips())
        self._animations.toggled.connect(lambda _c: self._reload_clips())
        self._to_box.currentIndexChanged.connect(lambda _i: self._refresh_ok())
        self._reload_clips()

    # ── contents ────────────────────────────────────────────────────

    def _reload_clips(self) -> None:
        """Fill the file list, and reduce it to one decision per kind of animation."""

        import collections

        from .clip_names import friendly, group_key, group_label, stance_of

        self._clip_list.clear()
        self._rows = []
        self._choices = {}
        if not self._animations.isChecked():
            self._rebuild_choice_form()
            self._refresh_ok()
            return

        rows = list(self._pairs_for(locomotion=self._everything.isChecked()))
        groups = collections.defaultdict(list)
        for row in rows:
            groups[group_key(row[0].name)].append(row)

        for key, members in groups.items():
            # The styles on offer are the distinct stances among every stand-in in the group.
            styles = {}
            for row in members:
                for option in (row[2] if len(row) > 2 else (row[1],)):
                    styles.setdefault(stance_of(option.name), option)
            if len(styles) > 1:
                ordered = sorted(styles.items())
                label = group_label(members[0][0].name, len(members))
                self._choices[key] = _Choice(
                    label,
                    [
                        (
                            stance,
                            f"Style {position + 1}",
                            f"{friendly(example.name)}\n     {example.name}",
                            example,
                        )
                        for position, (stance, example) in enumerate(ordered)
                    ],
                    self._on_preview,
                )

        for row in rows:
            target, donor = row[0], row[1]
            options = row[2] if len(row) > 2 else (donor,)
            choice = self._choices.get(group_key(target.name))
            item = QListWidgetItem()
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self._clip_list.addItem(item)
            if choice is not None:
                item.setText(f"{friendly(target.name)}\n      {target.name}")
                self._rows.append((item, target, (choice, options, donor)))
            else:
                item.setText(
                    f"{friendly(target.name)}\n      ← {friendly(donor.name)}"
                )
                self._rows.append((item, target, donor))
        self._rebuild_choice_form()
        self._refresh_ok()

    def _rebuild_choice_form(self) -> None:
        """Show one row per decision, and hide the section when there is nothing to decide."""

        while self._choice_form.rowCount():
            self._choice_form.removeRow(0)
        for choice in self._choices.values():
            self._choice_form.addRow(choice.label + ":", choice.widget)
        self._choice_group.setVisible(bool(self._choices))
        self._choice_group.setTitle(
            f"Choose which animation to use ({len(self._choices)})"
        )

    def _set_all(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self._clip_list.count()):
            self._clip_list.item(row).setCheckState(state)
        self._refresh_ok()

    def _chosen_clips(self):
        chosen = []
        for item, target, source in getattr(self, "_rows", []):
            if item.checkState() != Qt.Checked:
                continue
            if isinstance(source, tuple):
                from .clip_names import stance_of

                choice, options, fallback = source
                wanted = choice.style()
                donor = next(
                    (o for o in options if stance_of(o.name) == wanted), fallback
                )
            else:
                donor = source
            chosen.append((target, donor))
        return tuple(chosen)

    def _undecided(self) -> int:
        """How many rows offer a choice, so the form can say to look at them."""

        return len(getattr(self, "_choices", {}) or {})

    def _refresh_ok(self) -> None:
        chosen = len(self._chosen_clips())
        total = self._clip_list.count()
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
            if "take the weapon out" in choice.label.lower():
                return choice.example()
        for choice in self._choices.values():
            return choice.example()
        # Nothing was ambiguous, so any applied stand-in represents the change equally.
        chosen = self._chosen_clips()
        return chosen[0][1] if chosen else None
