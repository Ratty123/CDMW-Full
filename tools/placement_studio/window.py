"""Placement Studio window.

Runs standalone (`scripts/placement_studio.py`) and embedded as a tool tab (`tab.py`). Both use
the same widget tree, so there is one implementation to keep working.

Isolation is structural, not a convention: nothing here imports `cdmw.ui`, so the studio cannot
inherit the embedded-preview freeze or the tool-rail reparenting faults, and it draws its own
geometry rather than driving a helper process.

Panes: a tree (bones -> sockets -> parts), a projected viewport with the body and placed weapon,
an edit panel, and an inspector answering the question the manual workflow keeps asking —
*what else moves if I change this?*
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .corpus import Baseline
from .editing import EditSession
from .model import PlacementBinding, Vec3
from .session import PlacementSession
from .glossary import as_html as glossary_html, tip
from .report_style import inspector_html
from .viewport import SkeletonViewport
from .window_animation import AnimationTabMixin
from .window_editing import EditPanelMixin
from .window_armour import ArmourPickerMixin
from .window_carry import CarryPickerMixin
from .window_clips import ClipBrowserMixin
from .window_constraints import SecondaryMotionMixin
from .window_playback import PlaybackMixin
from .window_rig_behaviour import RigBehaviourMixin
from .window_rig_tabs import RigTabsMixin

class PosedMesh:
    """Deformed geometry the viewport can draw without a per-frame Vec3 rebuild.

    Exposes `points` as an (N, 3) array for the fast projection path, and `vertices` lazily
    for the few callers — bounds, clipping — that still want objects.
    """

    __slots__ = ("points", "triangles", "name", "_vertices")

    def __init__(self, points, triangles, name: str = "posed body") -> None:
        self.points = points
        self.triangles = triangles
        self.name = name
        self._vertices = None

    @property
    def vertices(self):
        if self._vertices is None:
            self._vertices = tuple(
                Vec3(float(x), float(y), float(z)) for x, y, z in self.points
            )
        return self._vertices

    @property
    def empty(self) -> bool:
        return len(self.points) == 0 or not self.triangles

    def bounds(self):
        if not len(self.points):
            return (Vec3(), Vec3())
        low = self.points.min(axis=0)
        high = self.points.max(axis=0)
        return (Vec3(*(float(c) for c in low)), Vec3(*(float(c) for c in high)))


_ROLE_SOCKET = Qt.UserRole + 1
_ROLE_PART = Qt.UserRole + 2

_USED = QColor(120, 190, 245)
_UNUSED = QColor(150, 150, 155)
_DANGLING = QColor(235, 140, 120)
_CHILD = QColor(190, 170, 235)


def _let_header_shrink(*, combos, labels) -> None:
    """Stop the header dictating a minimum window width.

    By default a combo asks to be as wide as its longest entry and a label as wide as its
    longest text, and neither will shrink below that. The part rows are long enough on their
    own (`CD_MainWeapon_Sword_R   ->   Pelvis_L_Socket / RHand_Socket`) that between them the
    header demanded a 4,010 px window — so on any real monitor the controls were jammed
    against each other with no way to give any of them room.

    Combos keep a readable minimum and elide the rest; the status labels give way entirely,
    since they are commentary and the window is more useful than the sentence.
    """

    for combo in combos:
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(14)
    for label in labels:
        label.setSizePolicy(QSizePolicy.Ignored, label.sizePolicy().verticalPolicy())
        label.setMinimumWidth(0)


def fit_popup(combo) -> None:
    """Let a dropdown's list be wider than the dropdown itself.

    By default the popup matches the closed control, so narrowing a combo to keep the window
    resizable also narrows the list you pick from — and Qt elides the overflow down the
    middle, which is the worst place: `New attach point (click the body)` came out as
    `New attach poi...lick the body)`, unreadable at both ends.

    The closed control can stay narrow and elide, because whatever is selected is also shown
    elsewhere; the list cannot, because it is the only place the options are legible.
    """

    metrics = combo.fontMetrics()
    widest = max(
        (metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())),
        default=0,
    )
    if widest:
        # Room for the scrollbar and the frame, or the last character still clips.
        combo.view().setMinimumWidth(widest + 40)


class PlacementStudioWindow(
    EditPanelMixin, AnimationTabMixin, PlaybackMixin, ClipBrowserMixin,
    CarryPickerMixin, ArmourPickerMixin, SecondaryMotionMixin, RigBehaviourMixin,
    RigTabsMixin, QMainWindow
):
    """Read-only inspector for one character's socket placement."""

    def __init__(self, baseline: Baseline, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Placement & Animation Studio")
        self.resize(1360, 860)

        self._baseline = baseline
        self._session: Optional[PlacementSession] = None
        self._bindings: List[PlacementBinding] = []
        self._edits: Optional[EditSession] = None
        self._selected_socket = ""
        self._body_cache_model = ""
        self._body_mesh_cached = None
        # Weapon geometry by baseline path. Decoding it per frame dominated playback.
        self._weapon_mesh_cache: dict = {}
        # Skinned body/armour, loaded once per model; deformed per pose in `_refresh_meshes`.
        self._skinned_cache_model = ""
        self._skinned_meshes: list = []
        # Triangle indices never change with the pose; only the vertices do.
        self._skinned_faces: tuple = ()
        self._clipping_requested = False
        # Armour pieces chosen per slot, as archive paths.
        self._armour_choice: dict = {}
        self._clipping_report = None
        self._body_problems: List[str] = []
        self._body_coverage = 0.0
        self._selected_part = ""
        self._local_blade_axis: Optional[Vec3] = None

        self._build_ui()
        self._load_models()

    def _build_help_tab(self) -> QWidget:
        """A glossary and a walkthrough, in the window rather than in a document.

        Every term here is one a modder meets in the first minute — `Part`, `Carry`, child
        socket — and none of them explain themselves. Keeping the answers a tab away rather
        than in a README means they are read.
        """

        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setHtml(glossary_html())
        return view

    # ── editing helpers ─────────────────────────────────────────────

    def _socket_file_of(self, socket_name: str) -> str:
        """Which file defines a socket — body sockets and child sockets live apart."""

        session = self._session
        if session is None:
            return ""
        placed = session.placed(socket_name)
        if placed is not None:
            return placed.socket.source_file
        weapon = session.weapon
        if weapon is not None and socket_name in weapon.sockets:
            return weapon.game_path
        return ""

    def _snap_step(self) -> float:
        return float(self._step_box.currentData() or 0.0)

    # ── construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._model_box = QComboBox()
        self._model_box.setToolTip(tip("Character"))
        self._model_box.currentIndexChanged.connect(self._on_model_changed)
        self._weapon_box = QComboBox()
        self._weapon_box.setToolTip(
            tip("Part", "Choosing a weapon here loads its own attachment points, which is "
                        "what lets it be aimed once you move it.")
        )
        self._weapon_box.currentIndexChanged.connect(self._on_weapon_changed)

        self._show_bones = QCheckBox("Bones")
        self._show_bones.setToolTip("Draw the skeleton the character is built on.")
        self._show_bones.setChecked(True)
        self._show_labels = QCheckBox("Labels")
        self._show_labels.setToolTip("Name each attachment point in the viewport.")
        self._show_labels.setChecked(True)
        self._show_unused = QCheckBox("Unused sockets")
        self._show_unused.setToolTip(
            "Also show attachment points that nothing is currently hanging on — the spare "
            "places you could move something to."
        )
        self._show_unused.setChecked(True)
        self._show_meshes = QCheckBox("Meshes")
        self._show_meshes.setToolTip("Draw the actual body and item shapes, not just bones.")
        self._show_meshes.setChecked(True)
        self._solid_body = QCheckBox("Solid")
        self._solid_body.setToolTip(
            "Fill the body in instead of leaving it see-through, so you can tell what is in "
            "front of what."
        )

        self._mesh_role_box = QComboBox()
        self._mesh_role_box.setToolTip(tip("Stowed and held"))
        self._mesh_role_box.addItem("put away (stowed)", "stowed")
        self._mesh_role_box.addItem("in hand (held)", "held")
        self._mesh_role_box.currentIndexChanged.connect(lambda _i: self._refresh_meshes())

        # The part being worked on. Reachable in the tree too, but the tree groups by parent
        # bone, so finding one row of 71 meant knowing which bone carried it first.
        self._part_box = QComboBox()
        self._part_box.setToolTip(tip("Part"))
        self._part_box.setMinimumWidth(230)
        self._part_box.currentIndexChanged.connect(self._on_part_box_changed)

        self._clipping_label = QLabel("sinks into body: not measured")
        self._measure_clipping_button = QPushButton("Check fit")
        self._measure_clipping_button.setToolTip(
            tip("Clipping", "Checks this frame only. Press it again after moving the item "
                            "or scrubbing to a different pose.")
        )
        self._measure_clipping_button.clicked.connect(self._request_clipping)

        carry_box, history_button, carry_swap, carry_status = self._build_carry_controls()

        # Two rows, not one. What is being edited goes on top; how it is displayed goes
        # underneath. On one row these controls asked for a 2,522 px window before anything
        # else was laid out, which is wider than the monitors this runs on.
        header = QWidget()
        header_rows = QVBoxLayout(header)
        header_rows.setContentsMargins(8, 6, 8, 4)
        header_rows.setSpacing(4)

        subject = QHBoxLayout()
        subject.addWidget(QLabel("Character:"))
        subject.addWidget(self._model_box, 2)
        subject.addSpacing(12)
        subject.addWidget(QLabel("Weapon:"))
        subject.addWidget(self._weapon_box, 3)
        subject.addSpacing(12)
        subject.addWidget(QLabel("Part:"))
        subject.addWidget(self._part_box, 3)
        subject.addSpacing(12)
        subject.addWidget(QLabel("Hangs on:"))
        subject.addWidget(carry_box, 2)
        header_rows.addLayout(subject)

        display = QHBoxLayout()
        # The two animation actions sit on the second row: the first is already five controls
        # wide, and adding them there pushed the window minimum past a 1600 px monitor.
        display.addWidget(carry_swap)
        display.addWidget(history_button)
        display.addSpacing(16)
        display.addWidget(QLabel("Show:"))
        display.addWidget(self._mesh_role_box)
        display.addSpacing(12)
        for box in (
            self._show_bones,
            self._show_labels,
            self._show_unused,
            self._show_meshes,
            self._solid_body,
        ):
            display.addWidget(box)
        display.addStretch(1)
        display.addWidget(carry_status)
        display.addSpacing(12)
        display.addWidget(self._clipping_label)
        display.addWidget(self._measure_clipping_button)
        header_rows.addLayout(display)

        fit_popup(self._mesh_role_box)
        _let_header_shrink(
            combos=(
                self._model_box, self._weapon_box, self._part_box,
                self._carry_box, self._mesh_role_box,
            ),
            labels=(self._clipping_label, carry_status),
        )

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Socket / Part", "Detail"])
        self._tree.setColumnWidth(0, 300)
        self._tree.setAlternatingRowColors(True)
        self._tree.currentItemChanged.connect(self._on_tree_selection)

        self._viewport = SkeletonViewport()
        self._viewport.socket_clicked.connect(self._on_socket_clicked)
        self._viewport.surface_picked.connect(self._on_surface_picked)

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(9)

        # Rich text, not plain: these two panels are read by scanning, and colour carrying
        # meaning is what makes a socket name or a warning findable in them.
        self._inspector = QTextBrowser()
        self._inspector.setFont(mono)

        self._diff_view = QTextBrowser()
        self._diff_view.setFont(mono)

        self._lower = QTabWidget()
        self._lower.addTab(self._inspector, "Inspector")
        self._lower.setTabToolTip(0, "What else moves if you change the selected socket.")
        self._lower.addTab(self._build_animation_tab(mono), "Clips && animation")
        self._lower.setTabToolTip(1, "Find a motion clip and play it on the character.")
        self._lower.addTab(self._build_armour_tab(), "Armour")
        self._lower.setTabToolTip(2, "Dress the character, to check an item against real gear.")
        self._lower.addTab(self._build_secondary_motion_tab(), "Driven bones")
        self._lower.setTabToolTip(
            3,
            "Bones that follow other bones: muscle bulge, joint creasing, and the few "
            "jiggle chains. The viewport cannot show it; the game solves it at runtime.",
        )
        self._lower.addTab(self._build_rig_behaviour_tab(), "Rig behaviour")
        self._lower.setTabToolTip(
            4,
            "Pose-modifier settings the game actually runs: look-at ranges, spine lag, "
            "IK reach, vehicle suspension. Keyed by skeleton.",
        )
        self._lower.addTab(self._diff_view, "Pending changes")
        self._lower.setTabToolTip(5, tip("Pending changes"))
        self._lower.addTab(self._build_help_tab(), "Help")
        self._lower.setTabToolTip(6, "What the words mean, and how to move a weapon.")

        # Both rig tabs need a four-second archive walk, so they load when first opened
        # rather than at startup, and re-target whenever the character changes.
        self._init_rig_tabs()

        # Viewport and the edit strip stack; the tabs get their own full-height column.
        # Sharing the vertical space left the Animation tab a few rows tall, which is not
        # enough for a clip browser, a socket-clip list and a chart dump side by side.
        centre = QSplitter(Qt.Vertical)
        centre.addWidget(self._viewport)
        centre.addWidget(self._build_edit_panel())
        centre.setChildrenCollapsible(False)
        centre.setSizes([640, 150])

        # Minimum widths, not just initial sizes: without them the tree collapsed to its
        # expander arrows and the tab column squeezed three panes into unreadable slivers
        # whenever the window was resized.
        self._tree.setMinimumWidth(240)
        centre.setMinimumWidth(520)
        self._lower.setMinimumWidth(420)

        body = QSplitter(Qt.Horizontal)
        body.addWidget(self._tree)
        body.addWidget(centre)
        body.addWidget(self._lower)
        body.setChildrenCollapsible(False)
        body.setSizes([300, 900, 620])
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 3)
        body.setStretchFactor(2, 1)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(body, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())

        self._show_bones.toggled.connect(self._viewport.set_show_bones)
        self._show_labels.toggled.connect(self._viewport.set_show_labels)
        self._show_unused.toggled.connect(self._viewport.set_show_unused)
        self._show_meshes.toggled.connect(self._viewport.set_show_meshes)
        # Solid without Meshes draws nothing, which reads as "the armour did not load".
        # Turning one on implies the other.
        self._solid_body.toggled.connect(self._on_solid_toggled)

        reset = QAction("Reset view", self)
        reset.setShortcut("R")
        reset.triggered.connect(self._viewport.reset_view)
        self.addAction(reset)


    def _load_models(self) -> None:
        models = PlacementSession.available_models(self._baseline)
        self._model_box.blockSignals(True)
        self._model_box.clear()
        for model in models:
            session = PlacementSession.from_baseline(self._baseline, model)
            self._model_box.addItem(session.label, model)
        self._model_box.blockSignals(False)
        if models:
            self._on_model_changed(0)

    # ── model / weapon selection ────────────────────────────────────

    def _on_model_changed(self, _index: int) -> None:
        model = self._model_box.currentData()
        if not model:
            return
        self._session = PlacementSession.from_baseline(self._baseline, model)

        self._populate_weapons(select_first=True)

    def _on_weapon_changed(self, _index: int) -> None:
        if self._session is None:
            return
        self._session.select_weapon(self._weapon_box.currentData())
        self._bindings = self._session.bindings()
        if self._edits is None:
            # One edit session spans the whole baseline, so switching weapon or character
            # never discards pending work.
            from .editing import session_from_baseline

            self._edits = session_from_baseline(self._baseline)
        self._populate_parts()
        self._refresh_scene()
        self._populate_tree()
        self._refresh_diff()
        self._refresh_edit_panel()
        self._refresh_animation()
        self._sync_rig_tabs()
        self._report_status()

    # ── part selection ──────────────────────────────────────────────

    def _populate_parts(self) -> None:
        """List the descriptor rows, each labelled with where it currently routes.

        Weapon rows first: they are what anyone opens this tool to move. The label carries the
        live routing so re-routing is visible in the very control used to pick the target.
        """

        session = self._session
        if session is None:
            return
        previous = self._part_box.currentData() or self._selected_part
        self._part_box.blockSignals(True)
        self._part_box.clear()

        def sort_key(binding: PlacementBinding):
            weapon_first = 0 if binding.part.category != "other" else 1
            return (weapon_first, binding.part_name)

        for binding in sorted(session.bindings(), key=sort_key):
            part = binding.part
            route = part.in_socket or "(none)"
            if part.out_socket and part.out_socket != part.in_socket:
                route += f" / {part.out_socket}"
            self._part_box.addItem(f"{binding.part_name}   →   {route}", binding.part_name)

        position = self._part_box.findData(previous) if previous else -1
        if position < 0:
            position = self._part_box.findData("CD_MainWeapon_Sword_R")
        self._part_box.setCurrentIndex(max(0, position))
        self._part_box.blockSignals(False)
        fit_popup(self._part_box)
        self._selected_part = str(self._part_box.currentData() or "")
        # Guarded: the parts dropdown is exercised on its own by a harness that builds no
        # carry control, and listing rows must not depend on a sibling widget existing.
        if hasattr(self, "_carry_box"):
            self._populate_carry_box()

    def _on_part_box_changed(self, _index: int) -> None:
        part_name = str(self._part_box.currentData() or "")
        if not part_name:
            return
        self._selected_part = part_name
        self._show_part(part_name)
        self._refresh_meshes()
        self._refresh_edit_panel()
        # The carry control follows the part, not the other way round.
        if hasattr(self, "_carry_box"):
            self._populate_carry_box()

    def _sync_part_box(self, part_name: str) -> None:
        """Reflect a tree selection in the dropdown without re-entering its handler."""

        position = self._part_box.findData(part_name)
        if position < 0:
            return
        self._part_box.blockSignals(True)
        self._part_box.setCurrentIndex(position)
        self._part_box.blockSignals(False)

    def _populate_weapons(self, *, select_first: bool = False) -> None:
        """Rebuild the weapon list, keeping the current choice when it survives.

        Called again once the archive scan lands, which is when the list grows from the
        eight pinned weapons to everything the game ships.
        """

        if self._session is None:
            return
        current = self._weapon_box.currentData()
        current_id = getattr(current, "weapon_id", None)
        weapons = self._session.weapons()
        self._weapon_box.blockSignals(True)
        self._weapon_box.clear()
        self._weapon_box.addItem("(none — body sockets only)", None)
        for weapon in weapons:
            self._weapon_box.addItem(weapon.label, weapon)
        restored = -1
        if current_id:
            for index in range(1, self._weapon_box.count()):
                if getattr(self._weapon_box.itemData(index), "weapon_id", None) == current_id:
                    restored = index
                    break
        self._weapon_box.blockSignals(False)
        fit_popup(self._weapon_box)
        if restored >= 0:
            self._weapon_box.setCurrentIndex(restored)
        elif select_first and weapons:
            self._weapon_box.setCurrentIndex(1)
        elif select_first:
            self._on_weapon_changed(0)

    def _refresh_scene(self) -> None:
        if self._session is None:
            return
        usage_map = self._session.usage_map()
        usage = {
            placed.name: usage_map[placed.name].total
            for placed in self._session.placed_sockets()
            if placed.name in usage_map
        }
        self._viewport.set_scene(self._session.hierarchy, self._session.placed_sockets(), usage)
        self._refresh_meshes()

    def _body_mesh(self):
        """Body proxy for the current model, loaded once and cached.

        Records *why* the proxy is unusable rather than failing quietly. A baseline that pinned
        an accessory instead of a body rendered as a couple of scraps and reported "no vertices
        inside the body" for every placement — a wrong answer that looked like a working one,
        because nothing in the UI distinguished "not clipping" from "nothing to clip against".
        """

        from .meshes import (
            MIN_BODY_COVERAGE,
            MeshError,
            body_coverage,
            body_mesh_paths,
            load_mesh,
            merge,
        )

        if self._session is None:
            return None
        model = self._session.model
        if self._body_cache_model == model:
            return self._body_mesh_cached
        pieces = []
        problems: List[str] = []
        paths = body_mesh_paths(self._baseline, model)
        if not paths:
            problems.append("no body armour mesh in the baseline")
        for path in paths:
            try:
                pieces.append(load_mesh(self._baseline.read(path), source_path=path))
            except MeshError as exc:
                problems.append(f"{path.rsplit('/', 1)[-1]}: {exc}")

        body = merge(pieces, name="body") if pieces else None
        coverage = body_coverage(body, self._session.hierarchy)
        if body is not None and coverage < MIN_BODY_COVERAGE:
            names = ", ".join(sorted(p.source_path.rsplit("/", 1)[-1] for p in pieces))
            problems.append(
                f"proxy spans only {coverage:.0%} of the rig ({names}) — re-extract the baseline"
            )
        self._body_cache_model = model
        self._body_mesh_cached = body
        self._body_problems = problems
        self._body_coverage = coverage
        return self._body_mesh_cached

    def _skinned_body(self):
        """Body and armour bound to the rig, loaded once per model.

        Separate from `_body_mesh`: that one merges static geometry for clipping checks and
        is correct at bind. This one follows the pose, which is the only way the silhouette
        means anything while a clip is playing.
        """

        from .skinning import load_skinned

        session = self._session
        if session is None or session.hierarchy is None:
            return []
        parsed = getattr(session.hierarchy, "parsed", None)
        if parsed is None:
            return []
        if self._skinned_cache_model == session.model:
            return self._skinned_meshes

        from .meshes import body_mesh_paths

        loaded = []
        for path in body_mesh_paths(self._baseline, session.model):
            try:
                mesh = load_skinned(self._baseline.read(path), path, parsed)
            except Exception:  # noqa: BLE001 - a mesh that will not bind is simply skipped
                mesh = None
            if mesh is not None:
                loaded.append(mesh)
        # Armour comes from the archives: the pinned baseline holds only the two body
        # meshes, so every helmet, glove and cloak has to be read on demand.
        for path in sorted(self._armour_choice.values()):
            if not path:
                continue
            try:
                mesh = load_skinned(self._armour_bytes(path), path, parsed)
            except Exception:  # noqa: BLE001
                mesh = None
            if mesh is not None:
                loaded.append(mesh)
        self._skinned_cache_model = session.model
        self._skinned_meshes = loaded
        self._skinned_faces = ()
        return loaded

    def _armour_bytes(self, path: str) -> bytes:
        """Read an armour mesh, from the baseline if pinned there, else the archives."""

        if path in self._baseline:
            return self._baseline.read(path)
        from .armour import read_armour

        return read_armour(path, getattr(self, "_armour_index", None))

    def _archive_bytes(self, path: str) -> bytes:
        """Any indexed asset: the pinned baseline first, then the packages."""

        if path in self._baseline:
            return self._baseline.read(path)
        entry = getattr(self, "_weapon_mesh_entries", {}).get(path)
        if entry is None:
            raise KeyError(path)
        from .armour import read_entry

        return read_entry(entry)

    def _invalidate_skinned(self) -> None:
        self._skinned_cache_model = ""
        self._skinned_meshes = []
        self._skinned_faces = ()

    def _posed_body(self):
        """The skinned body at the current pose, as viewport geometry."""

        from .meshes import Mesh
        from .skinning import deform, skin_matrices

        session = self._session
        meshes = self._skinned_body()
        if session is None or not meshes or not self._playback.loaded:
            return None
        parsed = getattr(session.hierarchy, "parsed", None)
        world = getattr(session, "pose_matrices", None)
        if parsed is None or world is None:
            return None
        try:
            matrices = skin_matrices(parsed, world)
        except Exception:  # noqa: BLE001 - fall back to the static proxy
            return None

        if not self._skinned_faces:
            faces = []
            base = 0
            for mesh in meshes:
                faces.extend((int(a) + base, int(b) + base, int(c) + base) for a, b, c in mesh.faces)
                base += mesh.vertex_count
            self._skinned_faces = tuple(faces)

        import numpy as np

        blocks = [deform(mesh, matrices) for mesh in meshes]
        if not blocks:
            return None
        points = np.concatenate(blocks) if len(blocks) > 1 else blocks[0]
        return PosedMesh(points=points, triangles=self._skinned_faces)

    def _refresh_meshes(self) -> None:
        """Place the weapon mesh at its attachment point and measure clipping.

        Everything here is optional: a missing mesh leaves the skeleton view fully usable,
        exactly as a missing native helper does elsewhere in the app.
        """

        from .meshes import MeshError, load_mesh, measure_clipping, points_inside, weapon_mesh_path

        session = self._session
        if session is None:
            return
        # A posed body when a clip is loaded, the bind-pose proxy otherwise. The proxy is
        # still what clipping is measured against when nothing is playing.
        body = self._posed_body() or self._body_mesh()
        weapon_mesh = None
        clipping: List[int] = []
        self._clipping_report = None

        # Follow the part the user selected. Guessing "the first sword row" silently picked
        # the left-hand row against a right-hand weapon mesh, which reported placement numbers
        # for a combination that does not exist.
        weapon = session.weapon
        bindings = session.bindings()
        # Bound before the weapon branch: with no weapon selected there is no mesh to load, and
        # reading it afterwards raised UnboundLocalError inside a Qt slot — which Qt swallows,
        # so the tab simply stopped updating instead of reporting anything.
        local = None
        binding = next((b for b in bindings if b.part_name == self._selected_part), None)
        if binding is None:
            binding = next(
                (
                    b
                    for b in bindings
                    if b.part_name == "CD_MainWeapon_Sword_R" and not b.part.is_case_row
                ),
                None,
            )
        if weapon is not None and binding is not None:
            path = weapon_mesh_path(weapon.weapon_id, session.model)
            if path in self._baseline or path in getattr(self, "_weapon_mesh_entries", {}):
                # Decoding this per frame cost ~32 ms and dominated playback. The geometry
                # is fixed; only the matrix that places it changes.
                if path in self._weapon_mesh_cache:
                    local = self._weapon_mesh_cache[path]
                else:
                    try:
                        local = load_mesh(self._archive_bytes(path), source_path=path)
                    except (MeshError, ValueError, KeyError):
                        local = None
                    self._weapon_mesh_cache[path] = local
                if local is not None:
                    role = self._mesh_role_box.currentData() or "stowed"
                    socket = binding.part.in_socket if role == "stowed" else binding.part.out_socket
                    child = (
                        binding.part.in_child_socket
                        if role == "stowed"
                        else binding.part.out_child_socket
                    )
                    matrix = session.attachment_matrix(socket, child)
                    if matrix is not None:
                        weapon_mesh = local.transformed(matrix, name=local.name)
                        # Clipping is measured on request, not per frame. Against a posed
                        # body it cannot be cached — the geometry changes every frame — and
                        # it cost 325 ms a frame, which is what made pausing feel like a
                        # hang. At bind, with no clip loaded, it is cheap enough to keep live.
                        if body is not None and self._should_measure_clipping():
                            self._clipping_report = measure_clipping(weapon_mesh, body)
                            clipping = points_inside(weapon_mesh.vertices, body)

        self._viewport.set_meshes(body, weapon_mesh, clipping)
        self._viewport.set_blade_axis(self._blade_axis(weapon_mesh))
        self._local_blade_axis = self._blade_axis(local) if local is not None else None
        self._update_clipping_label()
        self._update_gizmo_anchor()

    def _should_measure_clipping(self) -> bool:
        """Live at bind pose; on request once a clip is driving the body."""

        if self._playhead_moving():
            return False
        if self._clipping_requested:
            self._clipping_requested = False
            return True
        return not (self._playback.loaded if hasattr(self, "_playback") else False)

    def _request_clipping(self) -> None:
        self._clipping_requested = True
        self._refresh_meshes()

    def _on_solid_toggled(self, checked: bool) -> None:
        self._viewport.set_solid(bool(checked))
        if checked and not self._show_meshes.isChecked():
            self._show_meshes.setChecked(True)

    def _ensure_meshes_visible(self) -> None:
        """Called when geometry is chosen: silently hidden meshes look like a failed load."""

        if not self._show_meshes.isChecked():
            self._show_meshes.setChecked(True)

    def _blade_axis(self, placed_weapon) -> Optional[Vec3]:
        """The placed item's long axis in world space, for tilt.

        Taken from the geometry rather than assumed: the mesh's longest extent is the blade, and
        after placement that direction is what "roll" should spin about.
        """

        import math

        if placed_weapon is None or placed_weapon.empty:
            return None
        low, high = placed_weapon.bounds()
        spans = (high.x - low.x, high.y - low.y, high.z - low.z)
        if max(spans) <= 1e-6:
            return None
        # Endpoints along the longest world axis give the direction without needing local space.
        index = spans.index(max(spans))
        pick = (lambda v: v.x, lambda v: v.y, lambda v: v.z)[index]
        lo = min(placed_weapon.vertices, key=pick)
        hi = max(placed_weapon.vertices, key=pick)
        dx, dy, dz = hi.x - lo.x, hi.y - lo.y, hi.z - lo.z
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length <= 1e-9:
            return None
        return Vec3(dx / length, dy / length, dz / length)

    def _update_gizmo_anchor(self) -> None:
        """Anchor the rotation rings: a body socket's own position, else the attachment point."""

        session = self._session
        if session is None or not self._selected_socket:
            self._viewport.set_gizmo_anchor(None)
            return
        placed = session.placed(self._selected_socket)
        if placed is not None:
            self._viewport.set_gizmo_anchor(placed.world_position)
            return
        # Child socket: draw where the item actually ends up.
        for binding in session.bindings():
            part = binding.part
            if part.in_child_socket == self._selected_socket:
                self._viewport.set_gizmo_anchor(
                    session.attachment_point(part.in_socket, self._selected_socket)
                )
                return
            if part.out_child_socket == self._selected_socket:
                self._viewport.set_gizmo_anchor(
                    session.attachment_point(part.out_socket, self._selected_socket)
                )
                return
        self._viewport.set_gizmo_anchor(None)

    def _update_clipping_label(self) -> None:
        # A broken proxy outranks the clipping number, because the number is derived from it and
        # would otherwise read as a confident "no clipping".
        if self._body_problems:
            self._clipping_label.setText("body proxy: " + "; ".join(self._body_problems[:2]))
            self._clipping_label.setStyleSheet("color: #e8a33c;")
            return
        report = self._clipping_report
        if report is None:
            self._clipping_label.setText("sinks into body: press Check fit")
            self._clipping_label.setStyleSheet("")
            return
        subject = self._selected_part or "CD_MainWeapon_Sword_R"
        self._clipping_label.setText(f"{subject}: {report.summary()}")
        self._clipping_label.setStyleSheet(
            "color: #e25858;" if report.clipping else "color: #78dc8c;"
        )

    def _report_status(self) -> None:
        """The idle status line.

        Leads with what to do rather than with counts. "72/74 rows fully resolved" is the
        first thing a modder reads on opening the tool, and it answers a question nobody has
        yet asked; the counts stay, after the sentence that says where to start.
        """

        if self._session is None:
            return
        report = self._session.report()
        message = (
            "Pick a Part, then change where it is carried — the Help tab explains the words.  "
            f"|  {self._session.summary()}  |  {report.resolved_count}/{len(report.bindings)} "
            f"rows fully resolved"
        )
        if self._session.warnings:
            message += f"  |  {len(self._session.warnings)} warning(s)"
        self.statusBar().showMessage(message)

    # ── tree ────────────────────────────────────────────────────────

    def _populate_tree(self) -> None:
        self._tree.blockSignals(True)
        self._tree.clear()
        if self._session is None:
            self._tree.blockSignals(False)
            return

        placed = {p.name: p for p in self._session.placed_sockets()}
        # Group by parent bone: that is the axis the rig actually organises sockets along.
        by_bone: Dict[str, List[str]] = {}
        for name, item in placed.items():
            by_bone.setdefault(item.bone.name if item.bone else "(world space)", []).append(name)

        for bone_name in sorted(by_bone):
            bone_item = QTreeWidgetItem([bone_name, f"{len(by_bone[bone_name])} socket(s)"])
            bone_item.setForeground(0, _UNUSED)
            self._tree.addTopLevelItem(bone_item)

            for socket_name in sorted(by_bone[bone_name]):
                usage = self._session.usage(socket_name)
                socket_item = QTreeWidgetItem([socket_name, usage.roles()])
                socket_item.setData(0, _ROLE_SOCKET, socket_name)
                socket_item.setForeground(0, _USED if not usage.empty else _UNUSED)
                bone_item.addChild(socket_item)

                for part_name in sorted(set(usage.stowed) | set(usage.held) | set(usage.child_offset)):
                    roles = []
                    if part_name in usage.stowed:
                        roles.append("stowed")
                    if part_name in usage.held:
                        roles.append("held")
                    if part_name in usage.child_offset:
                        roles.append("child")
                    part_item = QTreeWidgetItem([part_name, "+".join(roles)])
                    part_item.setData(0, _ROLE_PART, part_name)
                    socket_item.addChild(part_item)

        # The selected weapon's own child sockets. They have no world position — they are
        # item-local offsets — so they hang off the weapon rather than a bone. Without this
        # node they are unreachable, yet they are what controls the *held* orientation, since
        # RHand_Socket carries an identity rotation.
        weapon = self._session.weapon
        if weapon is not None:
            child_root = QTreeWidgetItem(
                [f"{weapon.weapon_id}", f"{len(weapon.sockets)} child socket(s)"]
            )
            child_root.setForeground(0, _CHILD)
            self._tree.addTopLevelItem(child_root)
            for socket in sorted(weapon.sockets.values(), key=lambda s: s.name):
                usage = self._session.usage(socket.name)
                item = QTreeWidgetItem([socket.name, usage.roles()])
                item.setData(0, _ROLE_SOCKET, socket.name)
                item.setForeground(0, _USED if not usage.empty else _CHILD)
                child_root.addChild(item)

        # Rows routed to a socket nothing defines: vanilla really does contain these.
        report = self._session.report()
        if report.missing_body_sockets:
            dangling = QTreeWidgetItem(
                ["(undefined sockets)", f"{len(report.missing_body_sockets)} row(s)"]
            )
            dangling.setForeground(0, _DANGLING)
            self._tree.addTopLevelItem(dangling)
            for part_name, gaps in sorted(report.missing_body_sockets.items()):
                child = QTreeWidgetItem([part_name, ", ".join(gaps)])
                child.setData(0, _ROLE_PART, part_name)
                child.setForeground(0, _DANGLING)
                dangling.addChild(child)

        self._tree.blockSignals(False)

    def _on_tree_selection(self, current: Optional[QTreeWidgetItem], _previous) -> None:
        if current is None or self._session is None:
            return
        socket_name = current.data(0, _ROLE_SOCKET)
        part_name = current.data(0, _ROLE_PART)
        if socket_name:
            self._selected_socket = socket_name
            self._viewport.set_selected(socket_name)
            self._viewport.set_attachments({})
            self._inspector.setHtml(inspector_html(self._describe_socket(socket_name)))
            self._lower.setCurrentIndex(0)
            self._update_gizmo_anchor()
        elif part_name:
            self._selected_part = part_name
            self._sync_part_box(part_name)
            self._show_part(part_name)
            self._refresh_meshes()
        else:
            self._selected_socket = ""
            self._viewport.set_selected("")
            self._inspector.setHtml(inspector_html(""))
        self._refresh_edit_panel()

    def _select_socket(self, socket_name: str) -> None:
        """Viewport click -> select the matching tree row."""

        for index in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(index)
            for child_index in range(top.childCount()):
                child = top.child(child_index)
                if child.data(0, _ROLE_SOCKET) == socket_name:
                    self._tree.setCurrentItem(child)
                    self._tree.scrollToItem(child)
                    return
        self._selected_socket = socket_name
        self._viewport.set_selected(socket_name)
        self._inspector.setHtml(inspector_html(self._describe_socket(socket_name)))
        self._refresh_edit_panel()
        self._update_gizmo_anchor()

    # ── inspector ───────────────────────────────────────────────────

    def _describe_socket(self, socket_name: str) -> str:
        from .inspector import describe_socket

        return describe_socket(self._session, socket_name)

    def _show_part(self, part_name: str) -> None:
        from .inspector import describe_part

        session = self._session
        if session is None:
            return
        binding = next((b for b in self._bindings if b.part_name == part_name), None)
        if binding is None:
            self._inspector.setHtml(inspector_html(f"No descriptor row named {part_name}"))
            return
        points = session.binding_points(binding)
        self._viewport.set_attachments(points)
        self._viewport.set_selected(binding.part.in_socket)
        self._inspector.setHtml(inspector_html(describe_part(session, binding, points)))


def launch(baseline: Optional[Baseline] = None) -> int:
    """Open the window. Returns the Qt exit code."""

    import sys

    from PySide6.QtWidgets import QApplication

    resolved = baseline if baseline is not None else Baseline.load()
    app = QApplication.instance() or QApplication(sys.argv)
    window = PlacementStudioWindow(resolved)
    window.show()
    return app.exec()
