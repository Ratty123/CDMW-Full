"""The Checks panel is the readiness authority for an exact topology rebuild.

The rebuild path already refuses a part whose contract does not hold. These
prove it refuses out loud: the panel names the blocker, says whether the exact
rebuild is available, and leaves a same-count session's rows exactly as they
were.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QToolButton, QTreeWidget

from cdmw.domain.mesh.export_validation import (
    TOPOLOGY_CONTRACT_CATEGORY,
    MeshExportValidationIssue,
    MeshExportValidationReport,
)
from cdmw.domain.mesh.topology import TOPOLOGY_PROVENANCE_REQUIRED
from cdmw.ui.mesh_editor import MeshEditorTab

from tests.mesh_harness_support import build_synthetic_mesh


TOPOLOGY_ROW = "Exact topology rebuild"


def _report(
    *,
    contract_parts: tuple[int, ...] = (),
    issues: tuple[MeshExportValidationIssue, ...] = (),
) -> MeshExportValidationReport:
    return MeshExportValidationReport(
        mesh_format="pac",
        submesh_count=1,
        vertex_count=3,
        face_count=1,
        issues=issues,
        topology_contract_parts=contract_parts,
    )


def _status_rows(validator: QTreeWidget) -> dict[str, str]:
    return {
        validator.topLevelItem(index).text(1): validator.topLevelItem(index).text(2)
        for index in range(validator.topLevelItemCount())
        if validator.topLevelItem(index).text(0) == "Status"
    }


class MeshTopologyChecksPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])
        self.tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshTopologyChecksPanel"))
        self.tab.open_mesh_session(
            build_synthetic_mesh(), session_id="topology-checks", mode="edit"
        )
        validator = self.tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorValidatorPanel")
        assert validator is not None
        self.validator = validator

    def tearDown(self) -> None:
        self.app.processEvents()
        self.tab.deleteLater()
        self.app.processEvents()

    def test_a_session_without_a_contract_keeps_the_rows_it_always_had(self) -> None:
        self.tab.standalone_workspace.update_export_validation(_report())

        rows = _status_rows(self.validator)

        self.assertNotIn(TOPOLOGY_ROW, rows)
        self.assertIn("Rebuild allowed", rows)
        self.assertIn("Topology status", rows)

    def test_a_valid_contract_reports_the_exact_rebuild_as_ready(self) -> None:
        self.tab.standalone_workspace.update_export_validation(_report(contract_parts=(0,)))

        rows = _status_rows(self.validator)

        self.assertEqual("ready", rows.get(TOPOLOGY_ROW))

    def test_an_unrelated_blocker_does_not_accuse_the_contract(self) -> None:
        """`Rebuild allowed` owns the overall gate; this row owns the contract."""
        self.tab.standalone_workspace.update_export_validation(
            _report(
                contract_parts=(0,),
                issues=(
                    MeshExportValidationIssue(
                        severity="blocker",
                        code="missing_skeleton_metadata",
                        message="Skinned mesh export needs linked skeleton metadata.",
                        category="skeleton",
                    ),
                ),
            )
        )

        rows = _status_rows(self.validator)

        self.assertEqual("ready", rows.get(TOPOLOGY_ROW))
        self.assertEqual("no", rows.get("Rebuild allowed"))

    def test_a_broken_contract_names_its_blocker_and_disables_rebuild(self) -> None:
        self.tab.standalone_workspace.update_export_validation(
            _report(
                issues=(
                    MeshExportValidationIssue(
                        severity="blocker",
                        code=TOPOLOGY_PROVENANCE_REQUIRED,
                        message="Exact topology rebuild is unavailable for this part.",
                        category=TOPOLOGY_CONTRACT_CATEGORY,
                        submesh_index=0,
                    ),
                ),
            )
        )

        rows = _status_rows(self.validator)
        codes = [
            self.validator.topLevelItem(index).text(1)
            for index in range(self.validator.topLevelItemCount())
        ]
        rebuild_button = self.tab.standalone_workspace.findChild(
            QToolButton, "MeshEditorExportMeshFileButton"
        )

        self.assertEqual("blocked", rows.get(TOPOLOGY_ROW))
        self.assertIn(TOPOLOGY_PROVENANCE_REQUIRED, codes)
        assert rebuild_button is not None
        self.assertFalse(rebuild_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
