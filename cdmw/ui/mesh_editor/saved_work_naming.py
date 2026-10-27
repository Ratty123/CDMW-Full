"""Name the draft of the mesh open in Mesh Editor and choose its project."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.mesh_saved_work_service import (
    SavedWorkProject,
    clean_name,
    create_project,
    list_projects,
    name_session_draft,
)


class NameDraftDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        name: str,
        projects: Sequence[SavedWorkProject],
        project_id: str,
        draft_root,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MeshEditorNameDraftDialog")
        self.setWindowTitle("Name This Draft")
        self.draft_root = draft_root
        layout = QVBoxLayout(self)
        hint = QLabel(
            "The name and project show in Drafts & Mods, where you can change them later.", self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.name_edit = QLineEdit(name, self)
        self.name_edit.setObjectName("MeshEditorDraftName")
        project_row = QHBoxLayout()
        self.project_combo = QComboBox(self)
        self.project_combo.setObjectName("MeshEditorDraftProject")
        self.project_combo.addItem("No project", "")
        for project in projects:
            self.project_combo.addItem(project.name, project.project_id)
        self.project_combo.setCurrentIndex(max(0, self.project_combo.findData(project_id)))
        self.new_project_button = QPushButton("New Project...", self)
        self.new_project_button.setObjectName("MeshEditorDraftNewProject")
        self.new_project_button.clicked.connect(self._new_project)
        project_row.addWidget(self.project_combo, 1)
        project_row.addWidget(self.new_project_button)
        form.addRow("Name in list", self.name_edit)
        form.addRow("Project", project_row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def name(self) -> str:
        return clean_name(self.name_edit.text())

    def project_id(self) -> str:
        return str(self.project_combo.currentData() or "")

    def _new_project(self) -> None:
        name, accepted = QInputDialog.getText(self, "New Project", "Project name:")
        if not accepted or not clean_name(name):
            return
        try:
            project = create_project(self.draft_root, name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "New Project", str(exc))
            return
        self.project_combo.addItem(project.name, project.project_id)
        self.project_combo.setCurrentIndex(self.project_combo.count() - 1)

    def _accept(self) -> None:
        if not self.name():
            QMessageBox.warning(self, "Name This Draft", "Enter a name.")
            return
        self.accept()


def refresh_draft_name_controls(tab: object) -> None:
    """Show the open draft's name beside Name Draft..., or hide both."""

    button = getattr(tab, "draft_name_button", None)
    label = getattr(tab, "draft_name_label", None)
    if button is None or label is None:
        return
    has_draft = getattr(tab, "mesh_editor_draft_manifest_path", None) is not None
    name = str(dict(getattr(tab, "mesh_editor_draft_lineage", {}) or {}).get("display_name") or "")
    button.setVisible(has_draft)
    label.setVisible(has_draft and bool(name))
    label.setText(f"Draft: {name}" if name else "")


def name_current_draft(tab: object) -> bool:
    """Ask for the open draft's name and project, then save them."""

    manifest_path = getattr(tab, "mesh_editor_draft_manifest_path", None)
    controller = getattr(tab, "standalone_controller", None)
    if manifest_path is None or controller is None:
        tab.status_message_requested.emit("Open a mesh from Archive Browser to name its draft.", True)
        return False
    try:
        plan = controller.mesh_service._session(controller.active_session_id).mesh_draft_plan
    except (KeyError, RuntimeError):
        plan = None
    lineage = dict(getattr(tab, "mesh_editor_draft_lineage", {}) or {})
    try:
        projects = list_projects(tab.mesh_editor_draft_root)
    except OSError:
        projects = ()
    dialog = NameDraftDialog(
        tab, name=str(lineage.get("display_name") or ""), projects=projects,
        project_id=str(lineage.get("project_id") or ""), draft_root=tab.mesh_editor_draft_root,
    )
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        name, project_id = dialog.name(), dialog.project_id()
    finally:
        dialog.deleteLater()
    try:
        name_session_draft(manifest_path, plan, name=name, project_id=project_id)
    except (OSError, ValueError) as exc:
        tab.status_message_requested.emit(f"The draft could not be named: {exc}", True)
        return False
    lineage.update(display_name=name, project_id=project_id)
    tab.mesh_editor_draft_lineage = lineage
    refresh_draft_name_controls(tab)
    tab.status_message_requested.emit(f"Draft named {name}.", False)
    return True


__all__ = ["NameDraftDialog", "name_current_draft", "refresh_draft_name_controls"]
