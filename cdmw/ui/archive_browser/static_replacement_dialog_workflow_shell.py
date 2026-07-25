"""Workflow tab and context shell for static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


def create_alignment_workflow_shell_section(context: dict[str, object]) -> SimpleNamespace:
    CollapsibleSection = context.get("CollapsibleSection")
    QFrame = context.get("QFrame")
    QGridLayout = context.get("QGridLayout")
    QGroupBox = context.get("QGroupBox")
    QHBoxLayout = context.get("QHBoxLayout")
    QLabel = context.get("QLabel")
    QPlainTextEdit = context.get("QPlainTextEdit")
    QPushButton = context.get("QPushButton")
    QSizePolicy = context.get("QSizePolicy")
    QTabWidget = context.get("QTabWidget")
    QVBoxLayout = context.get("QVBoxLayout")
    Qt = context.get("Qt")
    SceneImportResult = context.get("SceneImportResult")
    _alignment_context_summary_facts_helper = context.get("_alignment_context_summary_facts_helper")
    _alignment_context_summary_group_title_helper = context.get("_alignment_context_summary_group_title_helper")
    _alignment_import_diagnostic_rows_helper = context.get("_alignment_import_diagnostic_rows_helper")
    _alignment_import_diagnostics_control_text_helper = context.get("_alignment_import_diagnostics_control_text_helper")
    _alignment_import_diagnostics_html_helper = context.get("_alignment_import_diagnostics_html_helper")
    _alignment_placement_review_html_helper = context.get("_alignment_placement_review_html_helper")
    _alignment_selection_context_help_text_helper = context.get("_alignment_selection_context_help_text_helper")
    _alignment_selection_context_initial_text_helper = context.get("_alignment_selection_context_initial_text_helper")
    _alignment_setup_intro_html_helper = context.get("_alignment_setup_intro_html_helper")
    _alignment_source_mix_control_text_helper = context.get("_alignment_source_mix_control_text_helper")
    _alignment_source_mix_current_status_helper = context.get("_alignment_source_mix_current_status_helper")
    _alignment_source_mix_parity_presentation_helper = context.get("_alignment_source_mix_parity_presentation_helper")
    _alignment_startup_step = context.get("_alignment_startup_step")
    _alignment_workflow_control_text_helper = context.get("_alignment_workflow_control_text_helper")
    _alignment_workflow_tab_labels_helper = context.get("_alignment_workflow_tab_labels_helper")
    _copy_mesh_editor_diagnostics = context.get("_copy_mesh_editor_diagnostics")
    _inline_help_button_helper = context.get("_inline_help_button_helper")
    _mesh_editor_diagnostics_set_text_widget_helper = context.get("_mesh_editor_diagnostics_set_text_widget_helper")
    _new_alignment_scroll_tab_helper = context.get("_new_alignment_scroll_tab_helper")
    _refresh_mesh_editor_diagnostics = context.get("_refresh_mesh_editor_diagnostics")
    alignment_control_content_min_width = context.get("alignment_control_content_min_width")
    alignment_startup_text = context.get("alignment_startup_text")
    content_container = context.get("content_container")
    create_alignment_source_mix_callbacks = context.get("create_alignment_source_mix_callbacks")
    embedded_alignment_builder = context.get("embedded_alignment_builder")
    entry = context.get("entry")
    import_diagnostics = context.get("import_diagnostics")
    layout = context.get("layout")
    mesh_edit_control_content_min_width = context.get("mesh_edit_control_content_min_width")
    mesh_editor_diagnostics_state = context.get("mesh_editor_diagnostics_state")
    modify_original_clone_mode = context.get("modify_original_clone_mode")
    obj_path = context.get("obj_path")
    original_mesh = context.get("original_mesh")
    placement_context_note = context.get("placement_context_note")
    scene_import_result = context.get("scene_import_result")
    self = context.get("self")
    full_import_model_replacement = bool(context.get("full_import_model_replacement"))
    static_replacement_workflow_mode = (
        "full_import"
        if full_import_model_replacement
        else "modify_original"
        if modify_original_clone_mode
        else "import_mesh"
    )

    control_tabs = QTabWidget(content_container)
    control_tabs.setObjectName("MeshAlignmentStickyWorkflowTabs")
    control_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    control_tabs.setUsesScrollButtons(True)
    control_tabs.setElideMode(Qt.ElideNone)
    control_tabs.tabBar().setExpanding(False)

    _new_alignment_scroll_tab = lambda object_name: _new_alignment_scroll_tab_helper(
        control_tabs,
        object_name,
        embedded=embedded_alignment_builder,
        content_minimum_width=alignment_control_content_min_width,
    )

    alignment_workflow_control_text = _alignment_workflow_control_text_helper()
    setup_tab, setup_page, setup_layout = _new_alignment_scroll_tab(alignment_workflow_control_text["setup_object"])
    parts_tab, parts_page, parts_layout = _new_alignment_scroll_tab(alignment_workflow_control_text["parts_object"])
    mesh_edit_tab, mesh_edit_page, mesh_edit_layout_page = _new_alignment_scroll_tab(
        alignment_workflow_control_text["mesh_edit_object"]
    )
    mesh_edit_page.setMinimumWidth(0 if embedded_alignment_builder else mesh_edit_control_content_min_width)
    mesh_edit_layout_page.setContentsMargins(0, 0, 0, 0)
    mesh_edit_layout_page.setSpacing(0)
    mesh_edit_tab.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    textures_tab, textures_page, textures_layout = _new_alignment_scroll_tab(
        alignment_workflow_control_text["materials_object"]
    )
    diagnostics_tab, diagnostics_page, diagnostics_layout = _new_alignment_scroll_tab(
        alignment_workflow_control_text["diagnostics_object"]
    )
    control_tabs.addTab(setup_tab, alignment_workflow_control_text["setup_label"])
    control_tabs.addTab(parts_tab, alignment_workflow_control_text["parts_label"])
    control_tabs.addTab(mesh_edit_tab, alignment_workflow_control_text["mesh_edit_label"])
    control_tabs.addTab(textures_tab, alignment_workflow_control_text["materials_label"])
    control_tabs.addTab(diagnostics_tab, alignment_workflow_control_text["diagnostics_label"])
    for tab_index, tab_label in enumerate(_alignment_workflow_tab_labels_helper()):
        control_tabs.setTabToolTip(tab_index, tab_label)
    if hasattr(control_tabs, "setTabVisible"):
        control_tabs.setTabVisible(control_tabs.indexOf(mesh_edit_tab), False)
        control_tabs.setTabVisible(control_tabs.indexOf(textures_tab), False)
    diagnostics_page.setMinimumWidth(0 if embedded_alignment_builder else alignment_control_content_min_width)
    diagnostics_toolbar = QHBoxLayout()
    diagnostics_toolbar.setContentsMargins(5, 3, 5, 3)
    diagnostics_toolbar.setSpacing(4)
    diagnostics_refresh_button = QPushButton(alignment_workflow_control_text["diagnostics_refresh"])
    diagnostics_copy_button = QPushButton(alignment_workflow_control_text["diagnostics_copy"])
    diagnostics_refresh_button.setObjectName(alignment_workflow_control_text["diagnostics_refresh_object"])
    diagnostics_copy_button.setObjectName(alignment_workflow_control_text["diagnostics_copy_object"])
    diagnostics_refresh_button.clicked.connect(lambda _checked=False: _refresh_mesh_editor_diagnostics())
    diagnostics_copy_button.clicked.connect(lambda _checked=False: _copy_mesh_editor_diagnostics())
    diagnostics_toolbar.addWidget(diagnostics_refresh_button)
    diagnostics_toolbar.addWidget(diagnostics_copy_button)
    diagnostics_toolbar.addStretch(1)
    diagnostics_layout.addLayout(diagnostics_toolbar)
    diagnostics_text = QPlainTextEdit(diagnostics_page)
    diagnostics_text.setObjectName(alignment_workflow_control_text["diagnostics_text_object"])
    diagnostics_text.setReadOnly(True)
    diagnostics_text.setLineWrapMode(QPlainTextEdit.NoWrap)
    diagnostics_text.setMinimumHeight(420)
    diagnostics_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    diagnostics_layout.addWidget(diagnostics_text, 1)
    _mesh_editor_diagnostics_set_text_widget_helper(mesh_editor_diagnostics_state, diagnostics_text)
    selection_context_frame = QFrame(content_container)
    selection_context_frame.setObjectName("SelectionContextFrame")
    selection_context_layout = QHBoxLayout(selection_context_frame)
    selection_context_layout.setContentsMargins(5, 2, 5, 2)
    selection_context_layout.setSpacing(5)
    selection_context_label = QLabel(_alignment_selection_context_initial_text_helper())
    selection_context_label.setObjectName("SelectionContextLabel")
    selection_context_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    selection_context_label.setWordWrap(True)
    selection_context_label.setMaximumHeight(30)
    selection_context_label.setMinimumWidth(0)
    selection_context_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
    selection_context_layout.addWidget(selection_context_label, 1)
    selection_context_layout.addWidget(
        _inline_help_button_helper(
            _alignment_selection_context_help_text_helper()
        )
    )
    layout.addWidget(selection_context_frame, 0)
    layout.addWidget(control_tabs, 1)
    intro = QLabel(_alignment_setup_intro_html_helper())
    intro.setWordWrap(True)
    intro.setTextFormat(Qt.RichText)
    intro.setObjectName("HintLabel")
    intro.setVisible(False)
    setup_layout.addWidget(intro)
    summary_section = CollapsibleSection("Summary", expanded=False)
    setup_summary_layout = summary_section.body_layout
    setup_layout.addWidget(summary_section)
    advanced_setup_section = CollapsibleSection("Advanced", expanded=False)
    advanced_setup_section.setParent(setup_page)
    setup_advanced_layout = advanced_setup_section.body_layout
    placement_note = None
    source_mix_control_text = _alignment_source_mix_control_text_helper()
    source_mix_tray = QGroupBox(source_mix_control_text["group_title"])
    source_mix_tray.setToolTip(source_mix_control_text["tray_tooltip"])
    source_mix_tray.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    source_mix_layout = QVBoxLayout(source_mix_tray)
    source_mix_layout.setContentsMargins(5, 3, 5, 3)
    source_mix_layout.setSpacing(2)
    source_mix_hint = QLabel(source_mix_control_text["hint"])
    source_mix_hint.setObjectName("HintLabel")
    source_mix_hint.setWordWrap(True)
    source_mix_hint.setToolTip(source_mix_control_text["tray_tooltip"])
    source_mix_hint.setVisible(False)
    source_mix_button_row = QHBoxLayout()
    source_mix_button_row.setContentsMargins(0, 0, 0, 0)
    source_mix_button_row.setSpacing(3)
    add_archive_source_button = QPushButton(source_mix_control_text["add_archive"])
    add_loose_source_button = QPushButton(source_mix_control_text["add_loose"])
    add_mod_archive_source_button = QPushButton(source_mix_control_text["add_mod_archive"])
    add_archive_source_button.setToolTip(source_mix_control_text["add_archive_tooltip"])
    add_loose_source_button.setToolTip(source_mix_control_text["add_loose_tooltip"])
    add_mod_archive_source_button.setToolTip(source_mix_control_text["add_mod_archive_tooltip"])
    for source_button in (add_archive_source_button, add_loose_source_button, add_mod_archive_source_button):
        source_button.setMinimumWidth(0)
        source_mix_button_row.addWidget(source_button)
    source_mix_button_row.addStretch(1)
    source_mix_layout.addLayout(source_mix_button_row)
    source_mix_status_presentation = _alignment_source_mix_current_status_helper(obj_path)
    source_mix_status_label = QLabel(source_mix_status_presentation.text)
    source_mix_status_label.setObjectName("HintLabel")
    source_mix_status_label.setWordWrap(True)
    source_mix_status_label.setToolTip(source_mix_status_presentation.tooltip)
    source_mix_status_label.setMaximumHeight(28)
    source_mix_layout.addWidget(source_mix_status_label)
    modify_original_parity_presentation = _alignment_source_mix_parity_presentation_helper(
        modify_original_clone_mode=modify_original_clone_mode,
    )
    modify_original_parity_label = QLabel(modify_original_parity_presentation.text)
    modify_original_parity_label.setObjectName("HintLabel")
    modify_original_parity_label.setWordWrap(True)
    modify_original_parity_label.setToolTip(modify_original_parity_presentation.tooltip)
    modify_original_parity_label.setMaximumHeight(28)
    source_mix_layout.addWidget(modify_original_parity_label)
    setup_advanced_layout.addWidget(source_mix_tray)
    # Shown only once parented; visible-while-parentless briefly makes the tray
    # its own top-level window during construction.
    source_mix_tray.setVisible(static_replacement_workflow_mode == "import_mesh")

    alignment_source_mix_callbacks = create_alignment_source_mix_callbacks({**context, **locals()})
    _choose_loaded_archive_mesh_source_for_alignment = alignment_source_mix_callbacks._choose_loaded_archive_mesh_source_for_alignment
    _add_loose_source_folder_for_alignment = alignment_source_mix_callbacks._add_loose_source_folder_for_alignment
    _choose_mod_archive_mesh_source_for_alignment = alignment_source_mix_callbacks._choose_mod_archive_mesh_source_for_alignment

    add_archive_source_button.clicked.connect(_choose_loaded_archive_mesh_source_for_alignment)
    add_loose_source_button.clicked.connect(_add_loose_source_folder_for_alignment)
    add_mod_archive_source_button.clicked.connect(_choose_mod_archive_mesh_source_for_alignment)
    if placement_context_note.strip():
        placement_note = QLabel(_alignment_placement_review_html_helper())
        placement_note.setWordWrap(True)
        placement_note.setTextFormat(Qt.RichText)
        placement_note.setObjectName("HintLabel")
        placement_note.setToolTip(placement_context_note.strip())
    if import_diagnostics:
        import_diagnostics_control_text = _alignment_import_diagnostics_control_text_helper()
        import_group = QGroupBox(import_diagnostics_control_text["details_group"])
        import_layout = QVBoxLayout(import_group)
        import_layout.setContentsMargins(5, 3, 5, 3)
        import_layout.setSpacing(2)
        import_rows = _alignment_import_diagnostic_rows_helper(import_diagnostics)
        import_label = QLabel(_alignment_import_diagnostics_html_helper(import_rows))
        import_label.setWordWrap(True)
        import_label.setTextFormat(Qt.RichText)
        import_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        import_layout.addWidget(import_label)
        import_section = CollapsibleSection(import_diagnostics_control_text["import_notes_section"], expanded=False)
        import_section.body_layout.addWidget(import_group)
        setup_summary_layout.addWidget(import_section)

    _alignment_startup_step(alignment_startup_text["alignment_summary"])
    context_html, context_values = self._build_archive_static_placement_context_html(
        entry,
        obj_path,
        original_mesh=original_mesh,
        replacement_mesh=scene_import_result.mesh if isinstance(scene_import_result, SceneImportResult) else None,
    )
    context_group = QGroupBox(_alignment_context_summary_group_title_helper())
    context_layout = QGridLayout(context_group)
    context_layout.setContentsMargins(5, 3, 5, 3)
    context_layout.setHorizontalSpacing(8)
    context_layout.setVerticalSpacing(1)
    compact_facts = _alignment_context_summary_facts_helper(
        context_values,
        format_number=self._format_static_alignment_number,
    )
    for fact_row, (fact_label, fact_value, fact_color) in enumerate(compact_facts):
        label_widget = QLabel(fact_label)
        label_widget.setObjectName("HintLabel")
        value_widget = QLabel(fact_value)
        value_widget.setWordWrap(True)
        value_widget.setMinimumWidth(0)
        value_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        value_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_widget.setStyleSheet(
            "QLabel {"
            f"color: {fact_color};"
            "font-weight: 600;"
            "padding: 1px 0;"
            "}"
        )
        context_layout.addWidget(label_widget, fact_row, 0)
        context_layout.addWidget(value_widget, fact_row, 1)
    context_group.setToolTip(context_html)
    setup_summary_layout.addWidget(context_group)

    return SimpleNamespace(
        _add_loose_source_folder_for_alignment=locals().get("_add_loose_source_folder_for_alignment"),
        _choose_loaded_archive_mesh_source_for_alignment=locals().get("_choose_loaded_archive_mesh_source_for_alignment"),
        _choose_mod_archive_mesh_source_for_alignment=locals().get("_choose_mod_archive_mesh_source_for_alignment"),
        add_archive_source_button=locals().get("add_archive_source_button"),
        add_loose_source_button=locals().get("add_loose_source_button"),
        add_mod_archive_source_button=locals().get("add_mod_archive_source_button"),
        alignment_source_mix_callbacks=locals().get("alignment_source_mix_callbacks"),
        alignment_workflow_control_text=locals().get("alignment_workflow_control_text"),
        context_group=locals().get("context_group"),
        context_html=locals().get("context_html"),
        context_values=locals().get("context_values"),
        control_tabs=locals().get("control_tabs"),
        diagnostics_copy_button=locals().get("diagnostics_copy_button"),
        diagnostics_layout=locals().get("diagnostics_layout"),
        diagnostics_page=locals().get("diagnostics_page"),
        diagnostics_refresh_button=locals().get("diagnostics_refresh_button"),
        diagnostics_tab=locals().get("diagnostics_tab"),
        diagnostics_text=locals().get("diagnostics_text"),
        intro=locals().get("intro"),
        mesh_edit_layout_page=locals().get("mesh_edit_layout_page"),
        mesh_edit_page=locals().get("mesh_edit_page"),
        mesh_edit_tab=locals().get("mesh_edit_tab"),
        modify_original_parity_label=locals().get("modify_original_parity_label"),
        parts_layout=locals().get("parts_layout"),
        parts_page=locals().get("parts_page"),
        parts_tab=locals().get("parts_tab"),
        placement_note=locals().get("placement_note"),
        selection_context_label=locals().get("selection_context_label"),
        setup_advanced_layout=locals().get("setup_advanced_layout"),
        setup_layout=locals().get("setup_layout"),
        setup_page=locals().get("setup_page"),
        setup_summary_layout=locals().get("setup_summary_layout"),
        setup_tab=locals().get("setup_tab"),
        static_replacement_workflow_mode=locals().get("static_replacement_workflow_mode"),
        advanced_setup_section=locals().get("advanced_setup_section"),
        source_mix_control_text=locals().get("source_mix_control_text"),
        source_mix_hint=locals().get("source_mix_hint"),
        source_mix_layout=locals().get("source_mix_layout"),
        source_mix_status_label=locals().get("source_mix_status_label"),
        source_mix_tray=locals().get("source_mix_tray"),
        summary_section=locals().get("summary_section"),
        textures_layout=locals().get("textures_layout"),
        textures_page=locals().get("textures_page"),
        textures_tab=locals().get("textures_tab"),
    )
