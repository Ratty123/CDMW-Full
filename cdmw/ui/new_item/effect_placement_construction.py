"""UI-only construction helpers for the resident effect placement workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.effect_placement_preview import (
    ANCHOR_TINT,
    BODY_TINT,
    EFFECT_AXIS_TINTS,
    ITEM_TINT,
    REACH_TINT,
)
from cdmw.ui.new_item.effect_placement_constants import (
    REACH_HIDDEN_ABOVE,
    ROTATION_DECIMALS,
    ROTATION_STEP,
    SCALE_DECIMALS,
    SCALE_MAXIMUM,
    SCALE_MINIMUM,
)
from cdmw.ui.new_item.effect_placement_dialog_support import (
    BACKDROP_BLACK,
    BACKDROP_DARK,
    BACKDROP_GREY,
    BACKDROPS,
    PARTICLE_TINT,
    describe_effect_preview,
    swatch as _swatch,
)
from cdmw.ui.new_item.ui_kit import DetailsToggle


class EffectPlacementConstructionMixin:
    """Build the compatibility panel before the guided presentation rearranges it."""

    def _build_placement_ui(
        self,
        *,
        effect_label: str,
        item_label: str,
        host_factory,
        effect_preview,
    ) -> QVBoxLayout:
        layout = QVBoxLayout(self)
        self._build_context_row(layout, effect_label, item_label)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        self._build_viewport(body, host_factory)
        self._build_side_panel(body, effect_preview)
        self._refresh_size_label()
        return layout

    def _build_context_row(self, layout: QVBoxLayout, effect_label: str, item_label: str) -> None:
        # One compact context row replaces two explanatory paragraphs. The distinctions
        # that still matter stay available on the model value's tooltip.
        context = QHBoxLayout()
        effect_caption = QLabel("Effect")
        self._compatibility_only_widgets.append(effect_caption)
        context.addWidget(effect_caption)
        self.effect_name_label = QLabel(str(effect_label or "-"))
        context.addWidget(self.effect_name_label, 1)
        model_caption = QLabel("Model")
        self._compatibility_only_widgets.append(model_caption)
        showing = QLabel("")
        if item_label == "placed":
            showing.setText("Imported")
            showing.setToolTip("Showing your imported model, at the placement set on step 3.")
        elif item_label == "applied":
            showing.setText("Imported")
            showing.setToolTip("Showing your imported model, as applied.")
        elif item_label == "template":
            showing.setText("Template")
            showing.setToolTip("Showing the template's model; import one on step 3 to place the effect on your own.")
        has_model_context = bool(showing.text())
        model_caption.setVisible(has_model_context)
        showing.setVisible(has_model_context)
        context.addWidget(model_caption)
        context.addWidget(showing)
        layout.addLayout(context)
        self.showing_label = showing

    def _build_viewport(self, body: QHBoxLayout, host_factory) -> None:
        self.host = None
        try:
            self.host = host_factory(self)
        except Exception as exc:  # noqa: BLE001 - the viewport is optional; the numbers still work
            self.host = None
            self._host_error = str(exc)
        else:
            self._host_error = ""
        self._renderer_failed = self.host is None
        self.view_buttons: list[QPushButton] = []
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.viewport_missing: QLabel | None = None
        if self.host is not None:
            self.host.setMinimumSize(560, 420)
            self.host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            viewport_column = QVBoxLayout()
            viewport_column.setContentsMargins(0, 0, 0, 0)
            viewport_column.addWidget(self.host, 1)
            views = QHBoxLayout()
            view_caption = QLabel("View")
            self._compatibility_only_widgets.append(view_caption)
            views.addWidget(view_caption)
            self._add_view_button(views, "Front", "Looking the character in the face: which side of the item the effect sits on.")
            self._add_view_button(views, "Side", "From the side: the item's longest span, and how far along it the effect sits.")
            self._add_view_button(views, "Top", "From above: how far in front of or behind the item the effect sits.")
            self._add_view_button(views, "Angled", "The three-quarter view the dialog opens on.")
            self.view_buttons[-1].setChecked(True)
            views.addStretch(1)
            viewport_column.addLayout(views)
            # Keep the gesture reference without spending a permanent line on it.
            self.host.setToolTip(
                "Turn the view: drag with the right mouse button. Shift-drag pans, the wheel zooms. "
                "The left button drags the orange anchor."
            )
            body.addLayout(viewport_column, 1)
            return
        missing = QLabel(
            "The resident viewport is not available here; set the numbers by hand."
            + (f" ({self._host_error})" if self._host_error else "")
        )
        missing.setWordWrap(True)
        self.viewport_missing = missing
        body.addWidget(missing, 1)

    def _build_side_panel(self, body: QHBoxLayout, effect_preview) -> None:
        # The panel keeps to its own width: left to itself it takes half the dialog and
        # the viewport -- the thing being looked at -- gets what is left.
        side_panel = QWidget()
        # Wide enough for the widest row -- "Anchor" and its four buttons -- plus the
        # scroll bar beside it; narrower than that and the last button is clipped away.
        side_panel.setMaximumWidth(400)
        side = QVBoxLayout(side_panel)
        place_box = QGroupBox("Placement")
        place = QVBoxLayout(place_box)
        view_box = QGroupBox("Preview")
        view = QVBoxLayout(view_box)
        side.setContentsMargins(0, 0, 0, 0)
        side_scroll = QScrollArea()
        side_scroll.setWidget(side_panel)
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setMaximumWidth(424)
        # The viewport expands, so without a floor it takes the width and the panel is
        # squeezed until its last button is clipped off the edge.
        side_scroll.setMinimumWidth(368)
        self._compatibility_only_widgets.append(side_scroll)
        body.addWidget(side_scroll)

        self._build_placement_group(place)
        self._build_preview_group(view)
        side.addWidget(place_box)
        side.addWidget(view_box)
        self._build_panel_details(side, effect_preview)

    def _build_placement_group(self, place: QVBoxLayout) -> None:
        # Two primary groups and nothing loose. Fourteen controls, five legend rows and
        # four labels in one column read as a wall: what moves the effect, what is drawn,
        # and what the effect is are three different questions and they now look like three.
        tools = QHBoxLayout()
        self.move_button = QPushButton("Move")
        self.move_button.setCheckable(True)
        self.move_button.setChecked(True)
        self.rotate_button = QPushButton("Rotate")
        self.rotate_button.setCheckable(True)
        self.rotate_button.setToolTip("Turn the effect about the item: drag a ring for its axis.")
        self.scale_button = QPushButton("Scale")
        self.scale_button.setCheckable(True)
        self.move_button.clicked.connect(lambda: self._choose_tool("move"))
        self.rotate_button.clicked.connect(lambda: self._choose_tool("rotate"))
        self.scale_button.clicked.connect(lambda: self._choose_tool("scale"))
        tools.addWidget(self.move_button)
        tools.addWidget(self.rotate_button)
        tools.addWidget(self.scale_button)
        place.addLayout(tools)
        form = QFormLayout()
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(SCALE_MINIMUM, SCALE_MAXIMUM)
        self.scale_spin.setDecimals(SCALE_DECIMALS)
        self.scale_spin.setSingleStep(0.05)
        self.scale_spin.setValue(self.scale)
        self.scale_spin.valueChanged.connect(self._numbers_edited)
        form.addRow("Scale", self.scale_spin)
        self.offset_spins: list[QDoubleSpinBox] = []
        for axis, value in zip(("Offset x (m)", "Offset y (m)", "Offset z (m)"), self.offset):
            spin = QDoubleSpinBox()
            spin.setRange(-5.0, 5.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.01)
            spin.setValue(float(value))
            spin.valueChanged.connect(self._numbers_edited)
            form.addRow(axis, spin)
            self.offset_spins.append(spin)
        self.rotation_spins: list[QDoubleSpinBox] = []
        for axis, value in zip(("Rotation x (°)", "Rotation y (°)", "Rotation z (°)"), self.rotation):
            spin = QDoubleSpinBox()
            spin.setRange(-180.0, 180.0)
            spin.setDecimals(ROTATION_DECIMALS)
            spin.setSingleStep(ROTATION_STEP)
            spin.setWrapping(True)
            spin.setValue(float(value))
            spin.setToolTip("Turns the effect about the item's own axes, degrees; x, then y, then z.")
            spin.valueChanged.connect(self._numbers_edited)
            form.addRow(axis, spin)
            self.rotation_spins.append(spin)
        place.addLayout(form)
        width, height, depth = (high - low for low, high in zip(*self._box))
        self._box_size = (width, height, depth)
        places = QHBoxLayout()
        places.addWidget(QLabel("Anchor"))
        self._add_place_button(places, "Hand", "hand", "Put the effect's origin back at the hand the item is held by.")
        self._add_place_button(places, "Middle", "middle", "Put the effect's origin at the middle of the item.")
        self._add_place_button(places, "Tip", "tip", "Put the effect's origin at the far end of the item's longest axis.")
        self.trail_button = QPushButton("Trail")
        self.trail_button.setToolTip("Put the effect's origin at the Trail Socket exposed by this item prefab.")
        self.trail_button.clicked.connect(lambda _checked=False: self._put_it_at("trail"))
        self.trail_button.setVisible(False)
        places.addWidget(self.trail_button)
        places.addStretch(1)
        place.addLayout(places)
        self._build_reach_controls(place, width, height, depth)

    def _build_reach_controls(self, place: QVBoxLayout, width: float, height: float, depth: float) -> None:
        reach_row = QHBoxLayout()
        self.show_reach = QCheckBox("Show the reach")
        self.show_reach.setToolTip("The effect's own bounding box as a thin frame, at this scale and offset: how far it can throw particles.")
        # A frame around a one-metre item is worth seeing; a frame twenty metres across is
        # a pair of orange columns crossing the view with the item a speck between them, and
        # the camera opens on the frame rather than on the thing being placed. Effects made
        # for bosses and set pieces reach that far, so their frame starts hidden.
        low, high = self._item_bounds()
        item_length = max(high[axis] - low[axis] for axis in range(3))
        reach_length = max(width, height, depth) * self.scale
        self._reach_dwarfs_the_item = bool(item_length > 0 and reach_length > item_length * REACH_HIDDEN_ABOVE)
        self.show_reach.setChecked(not self._reach_dwarfs_the_item)
        self.show_reach.toggled.connect(lambda _checked: self._reach_toggled())
        reach_row.addWidget(self.show_reach)
        reach_row.addStretch(1)
        place.addLayout(reach_row)

        fit_row = QHBoxLayout()
        self.fit_button = QPushButton("Fit it to the item")
        self.fit_button.setToolTip("Set the scale so the effect's reach is about as long as the item; the offset is left alone.")
        self.fit_button.clicked.connect(self._fit_reach_to_item)
        fit_row.addWidget(self.fit_button)
        fit_row.addStretch(1)
        place.addLayout(fit_row)

    def _build_preview_group(self, view: QVBoxLayout) -> None:
        self.show_particles = QCheckBox("Show the particles")
        self.show_particles.setToolTip("The effect's own particles, drawn approximately. Turn them off to see the item underneath.")
        self.show_particles.setChecked(True)
        self.show_particles.toggled.connect(lambda checked: self._show_particles(bool(checked)))
        particle_row = QHBoxLayout()
        particle_row.addWidget(self.show_particles)
        # Hiding the fire answers "what is under it". Holding it answers "where exactly is
        # this one", which a cloud in motion never lets anyone read.
        self.pause_button = QPushButton("Pause")
        self.pause_button.setCheckable(True)
        self.pause_button.setToolTip("Hold the particles where they are, still drawn, so a moving cloud can be read.")
        self.pause_button.toggled.connect(lambda checked: self._pause_particles(bool(checked)))
        particle_row.addWidget(self.pause_button)
        particle_row.addStretch(1)
        view.addLayout(particle_row)

        self.show_character = QCheckBox("Show the character")
        self.show_character.setToolTip("A 1.75 m character reference, so the effect's size reads against something known.")
        self.show_character.setChecked(True)
        backdrop_row = QHBoxLayout()
        backdrop_row.addWidget(QLabel("Backdrop"))
        self.backdrop_choice = QComboBox()
        # Named at the call site rather than in the table above, because a name in a
        # module-level tuple never reaches the localizer.
        self.backdrop_choice.addItem("Dark", BACKDROP_DARK)
        self.backdrop_choice.addItem("Grey", BACKDROP_GREY)
        self.backdrop_choice.addItem("Black", BACKDROP_BLACK)
        self.backdrop_choice.setToolTip(
            "What the viewport clears to. An effect adds its light to whatever is behind it, so it reads best on a dark "
            "backdrop; the grey is the one the Mesh Editor judges materials on, where a dark clear lets dark textures "
            "melt into it."
        )
        # Keep the compatibility facade as the patch point for the shared setting.
        from cdmw.ui.new_item import effect_placement_dialog as facade

        remembered = facade.remembered_backdrop()
        for index, value in enumerate(BACKDROPS):
            if value.casefold() == remembered.casefold():
                self.backdrop_choice.setCurrentIndex(index)
                break
        self.backdrop_choice.currentIndexChanged.connect(lambda _index: self._backdrop_changed())
        backdrop_row.addWidget(self.backdrop_choice, 1)
        orbit_row = self._build_orbit_controls()
        self.show_character.toggled.connect(lambda _checked: self._apply_scene_visibility())
        view.addWidget(self.show_character)
        view.addLayout(backdrop_row)
        view.addLayout(orbit_row)

    def _build_orbit_controls(self) -> QHBoxLayout:
        orbit_row = QHBoxLayout()
        self.invert_orbit_x_checkbox = QCheckBox("Invert orbit X")
        self.invert_orbit_y_checkbox = QCheckBox("Invert orbit Y")
        self.invert_orbit_x_checkbox.setToolTip(
            "Reverse horizontal orbit. With this enabled, dragging left or right rotates the camera around the model in the opposite direction."
        )
        self.invert_orbit_y_checkbox.setToolTip(
            "Reverse vertical orbit. With this enabled, dragging up or down tilts the camera around the model in the opposite direction."
        )
        # Resolve through the compatibility facade so existing callers/tests that patch
        # its long-standing setting helpers still control construction.
        from cdmw.ui.new_item import effect_placement_dialog as facade

        invert_x, invert_y = facade.remembered_orbit_inversion()
        self.invert_orbit_x_checkbox.setChecked(invert_x)
        self.invert_orbit_y_checkbox.setChecked(invert_y)
        self.invert_orbit_x_checkbox.toggled.connect(lambda _checked: self._apply_orbit_preferences(remember=True))
        self.invert_orbit_y_checkbox.toggled.connect(lambda _checked: self._apply_orbit_preferences(remember=True))
        orbit_row.addWidget(self.invert_orbit_x_checkbox)
        orbit_row.addWidget(self.invert_orbit_y_checkbox)
        orbit_row.addStretch(1)
        return orbit_row

    def _build_panel_details(self, side: QVBoxLayout, effect_preview) -> None:
        self.size_label = QLabel("")
        self.size_label.setWordWrap(True)
        side.addWidget(self.size_label)
        # What each thing in the viewport is, in the colour it is drawn; the question a
        # reader asks first, and one the numbers beside the viewport cannot answer.
        self.legend_toggle = DetailsToggle("", title="What the colours mean")
        legend_column = QVBoxLayout()
        legend_column.setContentsMargins(0, 0, 0, 0)
        self.legend_rows: dict = {}
        self._add_legend_row(legend_column, "anchor", ANCHOR_TINT, "the effect's origin - drag this one")
        axes = QLabel()
        axes.setTextFormat(Qt.TextFormat.RichText)
        axes.setWordWrap(True)
        axes.setText(
            f"{_swatch(EFFECT_AXIS_TINTS[0])}{_swatch(EFFECT_AXIS_TINTS[1])}{_swatch(EFFECT_AXIS_TINTS[2])} "
            "the effect's own x, y and z, which the rotation turns"
        )
        legend_column.addWidget(axes)
        self.legend_rows["axes"] = axes
        self._add_legend_row(legend_column, "item", ITEM_TINT, "your item")
        self._add_legend_row(legend_column, "body", BODY_TINT, "a character, 1.75 m tall, for scale")
        self._add_legend_row(legend_column, "reach", REACH_TINT, "how far the effect can throw particles")
        self._add_legend_row(legend_column, "particles", PARTICLE_TINT, "the particles, read approximately")
        self.legend_toggle.body.setVisible(False)
        legend_holder = QWidget()
        legend_holder.setLayout(legend_column)
        self.legend_toggle.layout().addWidget(legend_holder)
        legend_holder.setVisible(False)
        self.legend_toggle.toggle.toggled.connect(legend_holder.setVisible)
        side.addWidget(self.legend_toggle)
        self._refresh_legend()

        self.emitters_toggle = DetailsToggle(describe_effect_preview(effect_preview), title="What the effect is made of")
        self.emitters_label = self.emitters_toggle.body
        self.emitters_toggle.setVisible(effect_preview is not None)
        side.addWidget(self.emitters_toggle)
        self.caveat = QLabel("")
        self.caveat.setWordWrap(True)
        self.caveat.setObjectName("new_item_warning")
        self.caveat.setVisible(False)
        side.addWidget(self.caveat)
        self.status = QLabel("Preparing the viewport...")
        self.status.setWordWrap(True)
        side.addWidget(self.status)
        side.addStretch(1)
        self.apply_button = QPushButton("Apply placement")
        self.apply_button.clicked.connect(self.apply_requested.emit)
        side.addWidget(self.apply_button)
