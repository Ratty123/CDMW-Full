"""Host-owned reference selection for hair; all decoding stays on the worker."""

from PySide6.QtWidgets import QDialog
from cdmw.ui.archive_browser.workflow_dependencies import archive_workflow_dependency_context
from cdmw.ui.shell.tab_registry import DetachedToolWindow


def build_hair_entry_bar(tab):
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton
    bar = QFrame(tab)
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(8, 6, 8, 6)
    button = QPushButton("Hair Tools", bar)
    button.setObjectName("MeshEditorHairMenu")
    button.setMinimumSize(132, 34)
    font = button.font()
    font.setBold(True)
    button.setFont(font)
    button.setToolTip("Create or edit Damiane hairstyles")
    menu = QMenu(button)
    create = menu.addMenu("Create hairstyle")
    for preset in ("Cropped", "Bob", "Long", "Ponytail", "Empty"):
        create.addAction(preset, lambda preset=preset: start_hair_workflow(tab, "generated", preset.casefold()))
    menu.addAction("Edit hairstyle", lambda: start_hair_workflow(tab, "existing"))
    button.setMenu(menu)
    layout.addWidget(button)
    tab.hair_entry_status = QLabel("", bar)
    layout.addWidget(tab.hair_entry_status, 1)
    return bar


def start_hair_workflow(tab, mode, preset="bob"):
    """Read the mounted barber registration and prepare a real hairstyle choice."""
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.domain.hair_registration import read_hair_choices
    from cdmw.services.hair_registration import DAMIANE_MESH_PARAM
    from cdmw.ui.mesh_editor.hair_context_preparation import HairContextPreparation
    from cdmw.ui.mesh_editor.hair_reference_picker import HairReferencePickerDialog
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    service = owner.archive.archive_catalogue_service
    session = service.current_session
    token = getattr(tab, "_hair_entry_generation", 0) + 1
    tab._hair_entry_generation = token

    def current():
        return token == tab._hair_entry_generation and service.current_session is session

    def failed(message):
        if current():
            tab.hair_entry_status.setText(str(message))

    def choices_ready(choices):
        if not current():
            return
        picker = HairReferencePickerDialog(owner, "hair", styles=tuple((c.index, c.prefab_stem) for c in choices))
        picker.preparation_failed.connect(failed)
        tab.hair_entry_status.setText("Choose a hairstyle to edit" if mode == "existing" else "Preparing hair materials…")

        def selected(result):
            if result != QDialog.Accepted or not current():
                return
            target = picker.selected_entry
            if not owner.shell._prepare_mesh_editor_archive_launch(target):
                return
            tab._pending_hair_start = (target.identity, mode)
            tab._pending_hair_preset = preset
            tab.open_archive_session(target, archive_dependencies=picker.selected_dependencies)
            owner.shell._activate_tool_widget(tab)
            tab.hair_entry_status.setText("Loading character…")
        picker.finished.connect(selected)
        if mode == "generated":
            # The first registered choice supplies compatibility and materials;
            # the Rust workspace replaces its visible hair with the chosen preset.
            picker.auto_choose_first = True
        else:
            picker.open()

    def prepared(context):
        if not current():
            return
        entry = context.dependencies.entry_for_path(DAMIANE_MESH_PARAM)
        if entry is None:
            failed("The mounted character is missing its barber registration. Refresh the catalogue.")
            return
        def read_choices(_log):
            if entry.orig_size > 2 * 1024 * 1024:
                raise ValueError("The barber registration exceeds its supported size.")
            return read_hair_choices(read_archive_entry_data(entry)[0])
        owner._run_utility_task_when_idle(status_message="Loading Damiane's hairstyles…", task=read_choices,
            on_complete=choices_ready, on_error=failed)

    resolver = getattr(tab, "_hair_context_preparation", None)
    if resolver is None:
        resolver = HairContextPreparation(service, tab)
        tab._hair_context_preparation = resolver
    resolver.cancel()
    for signal in (resolver.ready, resolver.failed):
        try:
            signal.disconnect()
        except (RuntimeError, TypeError):
            pass
    resolver.ready.connect(prepared)
    resolver.failed.connect(failed)
    tab.hair_entry_status.setText("Loading character…")
    resolver.start()


def begin_hair_context(tab, session, event):
    """Return immediately; resume the ordered protocol queue after preparation."""
    from cdmw.ui.mesh_editor.hair_context_preparation import HairContextPreparation
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    target = tab._current_target_entry()
    if target is None:
        raise ValueError("Open a Damiane hairstyle before entering Hair.")
    dependencies = getattr(tab, "archive_session_dependencies", None) or archive_workflow_dependency_context(owner, target)
    previous = getattr(tab, "_hair_context_preparation", None)
    if previous is not None:
        previous.cancel()
    else:
        previous = HairContextPreparation(owner.archive.archive_catalogue_service, tab)
        tab._hair_context_preparation = previous
    # Disconnect only this operation's handlers; the cached resolver is reusable.
    for signal in (previous.ready, previous.failed):
        try:
            signal.disconnect()
        except (RuntimeError, TypeError):
            pass

    def resume(context=None, error=""):
        if (tab.standalone_rust_authoring_session is not session or tab.standalone_rust_closing
                or tab._current_target_entry() is None or tab._current_target_entry().identity != target.identity):
            return
        args = {**dict(event.get("arguments") or {}), "_hair_context_ready": True,
                "_target_entry": target, "_target_dependencies": dependencies}
        args["start_preset"] = getattr(tab, "_pending_hair_preset", "bob")
        tab._pending_hair_preset = "bob"
        if context is not None:
            args.update(context.arguments())
        tab.standalone_rust_protocol_queue.insert(0, {**event, "arguments": args, "_hair_preparation_error": error})
        tab._start_next_rust_protocol_worker()
    previous.ready.connect(resume)
    previous.failed.connect(lambda message: resume(error=message))
    previous.start()


def open_hair_texture_source(tab, path):
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    owner.textures._open_source_in_texture_editor(path, None)


def prepare_hair_event(tab, session, event):
    from cdmw.ui.mesh_editor.hair_reference_picker import HairReferencePickerDialog
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    target = tab._current_target_entry()
    if target is None:
        raise ValueError("Open a Damiane hairstyle before changing references.")
    service = owner.archive.archive_catalogue_service
    archive_session = service.current_session
    arguments = {**dict(event.get("arguments") or {}), "_target_entry": target,
                 "_target_dependencies": getattr(tab, "archive_session_dependencies", None) or archive_workflow_dependency_context(owner, target)}
    for role, entry_key, dependencies_key in (("head", "_archive_entry", "_archive_dependencies"),
                                             ("body", "_body_archive_entry", "_body_archive_dependencies")):
        picker = HairReferencePickerDialog(owner, role)
        if picker.exec() != QDialog.Accepted:
            raise ValueError("Reference selection cancelled; the current hairstyle is unchanged.")
        if (service.current_session is not archive_session or tab.standalone_rust_authoring_session is not session
                or tab.standalone_rust_closing or tab._current_target_entry() is None
                or tab._current_target_entry().identity != target.identity):
            raise ValueError("The editor or archive changed during reference selection.")
        arguments[entry_key] = picker.selected_entry
        arguments[dependencies_key] = picker.selected_dependencies
    return {**event, "arguments": arguments}
