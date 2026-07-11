from __future__ import annotations

from types import SimpleNamespace

def _dialog_step_0008(_state):
    def _selected_inline_placement_evidence() -> Optional[AttachmentPlacementEvidence]:
        item = _state.placement_tree.currentItem()
        while item is not None:
            evidence = item.data(0, _state.Qt.ItemDataRole.UserRole)
            if isinstance(evidence, _state.AttachmentPlacementEvidence):
                return evidence
            item = item.parent()
        return _state.self._attachment_visual_best_evidence(_state.hkx_attachment_graph)
    _state._selected_inline_placement_evidence = _selected_inline_placement_evidence

def _dialog_step_0009(_state):
    def _refresh_inline_socket_details() -> None:
        _state.placement_socket_tree.clear()
        if not _state.placement_page.isEnabled():
            _state.placement_socket_summary.setText("Placement editing is disabled - WIP; socket XML is not loaded in this editor.")
            _state.placement_socket_tree.addTopLevelItem(_state.QTreeWidgetItem(["Placement disabled", "-", "-", "-", "not loaded"]))
            return
        evidence = _state._selected_inline_placement_evidence()
        socket_entry = _state.self._attachment_socket_entry_from_selection(_state.hkx_attachment_graph, _state.placement_tree)
        chain_text = (
            f"{getattr(evidence, 'character_socket_name', '') or '-'} -> "
            f"{getattr(evidence, 'weapon_socket_name', '') or '-'}"
            if isinstance(evidence, _state.AttachmentPlacementEvidence)
            else "No placement chain"
        )
        if not isinstance(socket_entry, _state.ArchiveEntry):
            _state.placement_socket_summary.setText(
                f"Selected chain: {chain_text}\nNo resolved socket XML descriptor is available for this chain."
            )
            _state.placement_socket_tree.addTopLevelItem(_state.QTreeWidgetItem(["No socket XML", "-", "-", "-", "unresolved"]))
            return
        try:
            data, _decompressed, _note = _state.read_archive_entry_data(socket_entry)
            document = _state.parse_socket_bone_data_xml(
                _state.decode_xml_text_payload(data).text,
                socket_entry.path,
            )
        except Exception as exc:
            # User-visible: socket XML read/parse failures are shown in the placement panel.
            _state.placement_socket_summary.setText(
                f"Selected chain: {chain_text}\nCould not read socket XML: {exc}"
            )
            _state.placement_socket_tree.addTopLevelItem(_state.QTreeWidgetItem(["Socket XML read failed", "-", "-", "-", socket_entry.path]))
            return
        important_names = {
            str(getattr(evidence, "character_socket_name", "") or "").strip().casefold(),
            str(getattr(evidence, "weapon_socket_name", "") or "").strip().casefold(),
        } if isinstance(evidence, _state.AttachmentPlacementEvidence) else set()
        important_names.discard("")
        added_rows = 0
        first_important_item: Optional[_state.QTreeWidgetItem] = None
        for socket in tuple(getattr(document, "sockets", ()) or ()):
            if not isinstance(socket, _state.AttachmentSocketInfo):
                continue
            socket_name = str(socket.name or "")
            item = _state.QTreeWidgetItem(
                [
                    socket_name or "-",
                    str(socket.parent or "-"),
                    _state.self._format_attachment_transform(socket.translation),
                    _state.self._format_attachment_transform(socket.rotation),
                    str(socket.source_path or socket_entry.path),
                ]
            )
            item.setToolTip(4, str(socket.source_path or socket_entry.path))
            if socket_name.strip().casefold() in important_names:
                item.setForeground(0, _state.QBrush(_state.QColor("#86efac")))
                item.setForeground(2, _state.QBrush(_state.QColor("#bfdbfe")))
                item.setForeground(3, _state.QBrush(_state.QColor("#bfdbfe")))
                if first_important_item is None:
                    first_important_item = item
            _state.placement_socket_tree.addTopLevelItem(item)
            added_rows += 1
        if added_rows <= 0:
            _state.placement_socket_tree.addTopLevelItem(_state.QTreeWidgetItem(["No socket rows", "-", "-", "-", socket_entry.path]))
        _state.placement_socket_summary.setText(
            f"Selected chain: {chain_text}\n"
            f"Socket XML: {socket_entry.path}\n"
            f"{added_rows:,} socket row(s) recovered; chain sockets are highlighted when present."
        )
        if first_important_item is not None:
            _state.placement_socket_tree.setCurrentItem(first_important_item)
            _state.placement_socket_tree.scrollToItem(first_important_item)
        for column in range(_state.placement_socket_tree.columnCount()):
            _state.placement_socket_tree.resizeColumnToContents(column)
    _state._refresh_inline_socket_details = _refresh_inline_socket_details

def _dialog_step_0010(_state):
    def _refresh_inline_swap_summary() -> None:
        _state.placement_swap_steps.clear()
        target_evidence = _state._selected_inline_placement_evidence()
        socket_entry = _state.self._attachment_socket_entry_from_selection(_state.hkx_attachment_graph, _state.placement_tree)
        chain_text = "No placement chain"
        if isinstance(target_evidence, _state.AttachmentPlacementEvidence):
            chain_text = (
                f"{target_evidence.character_socket_name or '-'} -> "
                f"{target_evidence.weapon_socket_name or '-'}"
            )
        _state.placement_swap_summary.setText(
            f"Current placement evidence: {chain_text}\n"
            "This opened asset is the target that changes. Use Choose Placement Source to compare actual socket/prefab values against another asset and build a reviewed placement-copy package."
        )

        def add_step(label: str, value: object, used_for: str, status: str = "") -> None:
            text = str(value or "").strip() or "-"
            status_text = status or ("Resolved" if text != "-" else "Missing")
            item = _state.QTreeWidgetItem([label, text, used_for, status_text])
            item.setToolTip(1, text)
            item.setToolTip(2, used_for)
            _state.self._ui_style_status_columns(item, {3: status_text})
            _state.placement_swap_steps.addTopLevelItem(item)

        add_step("Selected HKX", _state.entry.path, "Target file being edited", "Context")
        if not isinstance(target_evidence, _state.AttachmentPlacementEvidence):
            add_step("Placement chain", "-", "No prefab/socket chain was recovered", "Missing")
            for column in range(_state.placement_swap_steps.columnCount()):
                _state.placement_swap_steps.resizeColumnToContents(column)
            return
        add_step("Target model", target_evidence.model_path, "Visible model path recovered from prefab/family evidence")
        add_step("Target prefab", target_evidence.prefab_path, "Placement fields and file references")
        add_step("Character socket", target_evidence.character_socket_name, "Character-side attach point")
        add_step("Character parent", target_evidence.character_socket_parent, "Skeleton/socket parent")
        add_step("Character translation", _state.self._format_attachment_transform(target_evidence.character_socket_translation), "Character socket transform")
        add_step("Character rotation", _state.self._format_attachment_transform(target_evidence.character_socket_rotation), "Character socket transform")
        add_step("Weapon pivot", target_evidence.weapon_socket_name, "Weapon-side pivot socket")
        add_step("Weapon parent", target_evidence.weapon_socket_parent, "Weapon socket parent")
        add_step("Weapon translation", _state.self._format_attachment_transform(target_evidence.weapon_socket_translation), "Weapon pivot transform")
        add_step("Weapon rotation", _state.self._format_attachment_transform(target_evidence.weapon_socket_rotation), "Weapon pivot transform")
        add_step("Socket XML", socket_entry.path if isinstance(socket_entry, _state.ArchiveEntry) else target_evidence.socket_file_path, "Socket values used for comparison")
        skeleton_paths = _state.self._attachment_family_skeleton_paths(_state.hkx_attachment_graph, target_evidence)
        add_step("Skeleton", "; ".join(skeleton_paths), "Character socket context")
        add_step("Transform fields", ", ".join(tuple(target_evidence.transform_fields or ())), "Prefab placement fields")
        add_step("Confidence", target_evidence.confidence, target_evidence.evidence or target_evidence.reason or "Recovered placement evidence", "Evidence")
        for column in range(_state.placement_swap_steps.columnCount()):
            _state.placement_swap_steps.resizeColumnToContents(column)
    _state._refresh_inline_swap_summary = _refresh_inline_swap_summary

def _dialog_step_0011(_state):
    def _refresh_inline_socket_editor_state() -> None:
        _state.placement_edit_socket_button.setEnabled(
            _state.self._attachment_socket_entry_from_selection(_state.hkx_attachment_graph, _state.placement_tree) is not None
        )
    _state._refresh_inline_socket_editor_state = _refresh_inline_socket_editor_state

def _dialog_step_0012(_state):
    def _edit_inline_socket_xml() -> None:
        socket_entry = _state.self._attachment_socket_entry_from_selection(_state.hkx_attachment_graph, _state.placement_tree)
        if not isinstance(socket_entry, _state.ArchiveEntry):
            _state.self.set_status_message("No resolved socket XML descriptor is available for this placement chain.", error=True)
            return
        _state.self._open_archive_socket_xml_editor_dialog(socket_entry, owner=_state.dialog)
    _state._edit_inline_socket_xml = _edit_inline_socket_xml

def _dialog_step_0013(_state):
    def _copy_inline_placement_from_donor() -> None:
        _state.self.set_status_message("Choose Placement Source is disabled - WIP.", error=True)
        return

        donor = _state.self._open_archive_attachment_donor_picker_dialog(_state.dialog, _state.entry)
        if isinstance(donor, _state.ArchiveEntry):
            _state.self._open_archive_attachment_placement_diff_dialog(_state.entry, donor)
    _state._copy_inline_placement_from_donor = _copy_inline_placement_from_donor

def _dialog_step_0014(_state):
    _state.placement_tree.currentItemChanged.connect(
        lambda _current, _previous: (
            _state._refresh_inline_socket_editor_state(),
            _state._refresh_inline_socket_details(),
            _state._refresh_inline_swap_summary(),
        )
    )
    _state.placement_edit_socket_button.clicked.connect(lambda _checked=False: _state._edit_inline_socket_xml())
    _state.placement_related_button.clicked.connect(lambda _checked=False: _state.placement_context_tabs.setCurrentWidget(_state.placement_related_tree))
    _state.placement_swap_related_button.clicked.connect(lambda _checked=False: _state.placement_context_tabs.setCurrentWidget(_state.placement_related_tree))
    _state._refresh_inline_socket_editor_state()
    _state._refresh_inline_socket_details()
    _state._refresh_inline_swap_summary()

    _state.hkx_preview_panel = _state.QWidget()
    _state.hkx_preview_panel.setMinimumWidth(420)
    _state.hkx_preview_layout = _state.QVBoxLayout(_state.hkx_preview_panel)
    _state.hkx_preview_layout.setContentsMargins(10, 2, 4, 4)
    _state.hkx_preview_layout.setSpacing(7)
    _state.hkx_preview_header_row = _state.QHBoxLayout()
    _state.hkx_preview_title = _state.QLabel("Embedded 3D Preview")
    _state.hkx_preview_title.setStyleSheet("font-weight: 600;")
    _state.hkx_preview_header_row.addWidget(_state.hkx_preview_title)
    _state.hkx_preview_header_row.addStretch(1)
    _state.hkx_preview_hide_button = _state.QPushButton("Hide")
    _state.hkx_preview_hide_button.setToolTip("Hide the optional 3D Preview pane and give the Linked View more room.")
    _state.hkx_preview_header_row.addWidget(_state.hkx_preview_hide_button)
    _state.hkx_preview_layout.addLayout(_state.hkx_preview_header_row)
    _state.hkx_preview_toolbar = _state.QHBoxLayout()
    _state.hkx_preview_toolbar.setSpacing(8)
    _state.hkx_preview_refresh_button = _state.QPushButton("Use Existing Preview")
    _state.hkx_preview_refresh_button.setToolTip(
        "Use a model preview that was already loaded before this HKX editor opened. Hidden unless one is available."
    )
    _state.hkx_preview_refresh_button.setVisible(False)
    _state.hkx_preview_load_model_button = _state.QPushButton("Load Model...")
    _state.hkx_preview_load_model_button.setToolTip(
        "Choose and build a related .pac, .pam, or .pamlod preview inside this HKX editor."
    )
    _state.hkx_preview_skeleton_checkbox = _state.QCheckBox("Show skeleton context")
    _state.hkx_preview_skeleton_checkbox.setChecked(False)
    _state.hkx_preview_skeleton_checkbox.setEnabled(False)
    _state.hkx_preview_skeleton_checkbox.setVisible(False)
    _state.hkx_preview_skeleton_checkbox.setToolTip(
        "Show recovered skeleton bones only when they are linked to HKX bodies or constraints. Held/sheathed placement comes from prefab/socket evidence."
    )
    _state.hkx_preview_status_label = _state.QLabel("")
    _state.hkx_preview_status_label.setWordWrap(True)
    _state.hkx_preview_status_label.setSizePolicy(_state.QSizePolicy.Policy.Ignored, _state.QSizePolicy.Policy.Preferred)
    _state.hkx_preview_toolbar.addWidget(_state.hkx_preview_load_model_button)
    _state.hkx_preview_toolbar.addWidget(_state.hkx_preview_refresh_button)
    _state.hkx_preview_toolbar.addWidget(_state.hkx_preview_skeleton_checkbox)
    _state.hkx_preview_toolbar.addWidget(_state.hkx_preview_status_label, stretch=1)
    _state.hkx_preview_layout.addLayout(_state.hkx_preview_toolbar)
    _state.hkx_link_preview_widget = _state.NativePreviewPanel(
        "No model is loaded in this embedded preview.\n\nClick Load Model to choose a related .pac/.pam/.pamlod from the open archive.",
        theme_key=_state.self.current_theme_key,
    )
    _state.hkx_link_preview_widget.setMinimumHeight(220)
    _state.self._configure_model_preview_widget(_state.hkx_link_preview_widget, apply_toggle_defaults=True)
    if hasattr(_state.hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
        _state.hkx_link_preview_widget.set_physics_overlay_bones_visible(False)
    try:
        _state.hkx_preview_settings = _state.hkx_link_preview_widget.render_settings()
        _state.hkx_link_preview_widget.set_render_settings(
            _state.dataclasses.replace(
                _state.hkx_preview_settings,
                show_physics_overlay=True,
                show_physics_simulation_preview=False,
            )
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        # Best effort: embedded HKX preview starts with default render settings if setup fails.
        pass
    _state.hkx_preview_layout.addWidget(_state.hkx_link_preview_widget, stretch=1)
    _state.workspace_splitter.addWidget(_state.hkx_preview_panel)
    _state.hkx_preview_panel.setVisible(False)
    _state.workspace_splitter.setStretchFactor(0, 0)
    _state.workspace_splitter.setStretchFactor(1, 1)
    _state.workspace_splitter.setStretchFactor(2, 1)
    _state.workspace_splitter.setSizes([280, 1130, 0])

    _state.xml_page = _state.QWidget()
    _state.xml_layout = _state.QVBoxLayout(_state.xml_page)
    _state.xml_layout.setContentsMargins(0, 0, 0, 0)
    _state.xml_layout.setSpacing(6)
    _state.search_row = _state.QHBoxLayout()
    _state.search_edit = _state.QLineEdit()
    _state.search_edit.setPlaceholderText("Search XML")
    _state.find_button = _state.QPushButton("Find Next")
    _state.wrap_checkbox = _state.QCheckBox("Wrap")
    _state.wrap_checkbox.setChecked(False)
    _state.line_status_label = _state.QLabel("Line 1, Column 1")
    _state.search_row.addWidget(_state.search_edit, stretch=1)
    _state.search_row.addWidget(_state.find_button)
    _state.search_row.addWidget(_state.wrap_checkbox)
    _state.search_row.addWidget(_state.line_status_label)
    _state.xml_layout.addLayout(_state.search_row)
    _state.editor_row = _state.QHBoxLayout()
    _state.editor_row.setContentsMargins(0, 0, 0, 0)
    _state.editor_row.setSpacing(0)
    _state.line_numbers = _state.QPlainTextEdit()
    _state.line_numbers.setReadOnly(True)
    _state.line_numbers.setLineWrapMode(_state.QPlainTextEdit.LineWrapMode.NoWrap)
    _state.line_numbers.setVerticalScrollBarPolicy(_state.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    _state.line_numbers.setHorizontalScrollBarPolicy(_state.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    _state.line_numbers.setFixedWidth(58)
    _state.line_numbers.setFont(_state.build_monospace_font(_state.self.settings))
    _state.line_numbers.setStyleSheet("QPlainTextEdit { color: #7f8c98; background: rgba(127, 140, 152, 0.08); }")
    _state.editor = _state.QPlainTextEdit()
    _state.editor.setPlainText(_state.document_text)
    _state.editor.setLineWrapMode(_state.QPlainTextEdit.LineWrapMode.NoWrap)
    _state.editor.setFont(_state.build_monospace_font(_state.self.settings))
    _state._xml_highlighter = _state.HkxXmlHighlighter(_state.editor.document())
    _state.editor._hkx_xml_highlighter = _state._xml_highlighter
    _state.editor_row.addWidget(_state.line_numbers)
    _state.editor_row.addWidget(_state.editor, stretch=1)

def _dialog_step_0015(_state):
    _state.xml_layout.addLayout(_state.editor_row, stretch=1)
    _state.tab_widget.addTab(_state.xml_page, "XML / Raw")
    _state.PRIMARY_HKX_SECTION_TITLES = {
        "Modding Workspace",
        "Patchable Values",
        "Placement",
        "Connected Physics",
        "Collision Shapes",
        "Decoder Evidence",
        "XML / Raw",
    }
    for _state.section_index in range(_state.tab_widget.count()):
        _state.section_title = _state.tab_widget.tabText(_state.section_index)
        _state.section_combo.addItem(_state.section_title, _state.section_index)
        if _state.section_index == _state.placement_tab_index:
            _state.section_combo.setItemData(
                _state.section_index,
                "Disabled - WIP. Placement swap/package flow is paused.",
                _state.Qt.ItemDataRole.ToolTipRole,
            )
            try:
                _state.combo_item = _state.section_combo.model().item(_state.section_index)
                if _state.combo_item is not None:
                    _state.combo_item.setEnabled(False)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                # Best effort: unavailable section state is still enforced by navigation handling.
                pass
        _state.nav_item = _state.QListWidgetItem(_state.section_title)
        _state.nav_item.setData(_state.Qt.ItemDataRole.UserRole, _state.section_index)
        _state.nav_item.setData(
            _state.Qt.ItemDataRole.UserRole + 1,
            _state.section_title.split("(", 1)[0].strip() in _state.PRIMARY_HKX_SECTION_TITLES,
        )
        if _state.section_index == _state.placement_tab_index:
            _state.nav_item.setFlags(_state.nav_item.flags() & ~_state.Qt.ItemFlag.ItemIsEnabled)
            _state.nav_item.setToolTip("Disabled - WIP. Placement swap/package flow is paused.")
        _state.section_nav_list.addItem(_state.nav_item)

    _state.syncing_tree = {"active": False}
    _state.syncing_collision_tree = {"active": False}
    _state.syncing_browser_follow = {"active": False}
    _state.hkx_link_preview_state = {"loaded": False}
    _state.browser_filter_state: Dict[str, object] = {"available_preview_targets": set()}
    _state.initial_values_by_key: Dict[Tuple[str, tuple], str] = {}
    _state.dirty_values_by_key: Dict[Tuple[str, tuple], Tuple[str, str, str]] = {}
    _state.ORIGINAL_VALUE_ROLE = _state.Qt.UserRole + 11
    _state.DIRTY_KEY_ROLE = _state.Qt.UserRole + 12
    _state.BROWSER_DATA_ROLE = _state.Qt.UserRole + 13
    _state.SECTION_SUMMARIES = {
        0: "Guided task filters for patchable and candidate HKX physics values.",
        1: "Patchable tuning values and descriptor context.",
        2: "Collision shapes and fixed-size shape fields.",
        3: "Decoded records, refs, and preserved raw ranges.",
        4: "Companion XML names, sockets, materials, and hints.",
        5: "Body/shape labels and editable field counts.",
        6: "Constraint, motor, stiffness, damping, and limits.",
        7: "Import-safe fields routed to editors.",
        8: "Exact fixed-size byte patch targets.",
        9: "Relationship map for bodies, shapes, constraints, and values.",
        10: "Native read-only decoder evidence, fixups, owner arrays, and missing semantics.",
        11: "Prefab/socket placement chains and inline weapon/socket preview.",
        12: "Full CDMW XML and raw fallback.",
    }

def _dialog_step_0016(_state):
    _state.WORKFLOW_GUIDES: Tuple[Dict[str, object], ...] = (
        {
            "key": "collision_size",
            "area": "Collision Size",
            "likely_edits": "radius, capsule endpoints, shape extents",
            "terms": ("radius", "capsule", "sphere", "convex", "collision", "shape", "extent"),
            "filter": "radius capsule sphere collision shape",
            "connected_filter": "capsule radius shape collision",
            "section": "Collision Editor",
            "risk": "Low",
            "meaning": "Changes the physical volume that can collide. Radius/endpoint edits are fixed-size when marked patchable.",
        },
        {
            "key": "joint_strength",
            "area": "Joint Strength",
            "likely_edits": "constraint strength, motor force, angular limits",
            "terms": ("constraint", "motor", "stiffness", "strength", "force", "torque", "angular", "limit", "tau"),
            "filter": "constraint motor stiffness strength force torque angular limit",
            "connected_filter": "constraint motor stiffness force torque angular limit strength",
            "section": "Structured Editor",
            "risk": "Medium",
            "meaning": "Changes how strongly a joint resists motion when the linked rows are patchable.",
        },
        {
            "key": "damping_motion",
            "area": "Damping / Motion",
            "likely_edits": "damping, drag, motion properties",
            "terms": ("damping", "drag", "motion", "velocity", "angular", "linear", "solver"),
            "filter": "damping drag motion velocity angular linear solver",
            "connected_filter": "damping motion motor body angular linear",
            "section": "Structured Editor",
            "risk": "Medium",
            "meaning": "Changes how quickly motion slows down when damping or motion rows are recovered.",
        },
        {
            "key": "body_transform",
            "area": "Body Transform",
            "likely_edits": "body transform/orientation rows",
            "terms": ("body_transform", "orientation", "transform", "position", "quaternion", "body"),
            "filter": "body_transform orientation transform position quaternion",
            "connected_filter": "body shape material socket",
            "section": "Structured Editor",
            "risk": "High",
            "meaning": "Moves or rotates an inferred body frame when exact fixed-size transform rows are patchable.",
        },
        {
            "key": "body_part_context",
            "area": "Material / Friction",
            "likely_edits": "material, friction, restitution, filter-like scalars",
            "terms": ("material", "friction", "restitution", "surface", "filter", "hair", "cloth", "cloak", "cape", "skirt", "socket"),
            "filter": "material friction restitution surface filter hair cloth cloak cape skirt socket",
            "connected_filter": "material friction restitution surface filter hair cloth cloak cape skirt socket",
            "section": "Connected Physics",
            "risk": "Context only",
            "meaning": "Material and friction-like rows are useful context until exact fixed-size patch gates approve them.",
        },
        {
            "key": "ragdoll_inspection",
            "area": "Ragdoll body links",
            "likely_edits": "body -> shape -> constraint -> value",
            "terms": ("ragdoll", "body", "shape", "constraint", "motor", "socket", "material"),
            "filter": "ragdoll body shape constraint motor socket material",
            "connected_filter": "ragdoll body shape material socket",
            "section": "Connected Physics",
            "risk": "Context only",
            "meaning": "Shows the best recovered chain from visible physics to bodies, constraints, materials, and values.",
        },
        {
            "key": "mesh_topology",
            "area": "Mesh Winding",
            "likely_edits": "vertices, planes, hull faces, primitive tuples",
            "terms": ("mesh", "primitive", "vertex", "vertices", "plane", "hull", "face", "edge", "topology", "aabb"),
            "filter": "mesh primitive vertex vertices plane hull face edge topology aabb",
            "connected_filter": "mesh primitive vertex plane hull face edge topology",
            "section": "Collision Editor",
            "risk": "Mostly read-only",
            "meaning": "Useful for browsing decoded collision geometry. Count/topology edits are intentionally blocked.",
        },
    )

STEPS = (_dialog_step_0008, _dialog_step_0009, _dialog_step_0010, _dialog_step_0011, _dialog_step_0012, _dialog_step_0013, _dialog_step_0014, _dialog_step_0015, _dialog_step_0016,)
