"""Behavioral coverage for the in-game mesh swap scope dialog.

These exercise the real dialog rather than asserting on source strings, because the
two defects covered here (an unbound warning label and a mismatched edge key) both
look correct in the source and only fail when the widget is actually built.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QTreeWidget, QWidget

from cdmw.domain.archives.relationships import (
    ARCHIVE_REL_INCLUDE_REQUIRED,
    ArchiveRelationEdge,
)
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.mesh_swap_scope_dialog import ArchiveMeshSwapScopeDialogMixin
from cdmw.ui.archive_browser.mesh_swap_scope_preflight import ArchiveMeshSwapScopePreflightResult
from cdmw.ui.archive_browser.mesh_swap_support import ArchiveMeshSwapSupportMixin


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _entry(tmp_path: Path, path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(path, tmp_path / "0.pamt", tmp_path / "0.paz", offset, 16, 16, 0, 0)


class _ScopeOwner(ArchiveMeshSwapSupportMixin, ArchiveMeshSwapScopeDialogMixin, QWidget):
    """Minimal host exposing only what the scope dialog reads."""

    def __init__(self, entries: Tuple[ArchiveEntry, ...], parent: Optional[QWidget] = None) -> None:
        QWidget.__init__(self, parent)
        self.archive_entries = entries
        self.archive_entries_by_normalized_path: Dict[str, List[ArchiveEntry]] = {}
        self.archive_entries_by_basename: Dict[str, List[ArchiveEntry]] = {}
        self.archive_entries_by_extension: Dict[str, List[ArchiveEntry]] = {}
        self.archive_character_appearance_swap_cache: Dict[object, Tuple[ArchiveEntry, ...]] = {}
        for entry in entries:
            normalized = entry.path.replace("\\", "/").strip().lower()
            basename = normalized.rsplit("/", 1)[-1]
            self.archive_entries_by_normalized_path.setdefault(normalized, []).append(entry)
            self.archive_entries_by_basename.setdefault(basename, []).append(entry)

    def _find_archive_entry_by_virtual_path(self, path: str) -> Optional[ArchiveEntry]:
        candidates = self.archive_entries_by_normalized_path.get(
            str(path or "").replace("\\", "/").strip().lower(), ()
        )
        return candidates[0] if candidates else None


def _preflight(
    *,
    source_related_entries: Tuple[ArchiveEntry, ...],
    relationship_edges: Tuple[Tuple[object, ArchiveRelationEdge], ...] = (),
    source_sidecar_paths: frozenset[str] = frozenset(),
    source_has_pbd_contract: bool = False,
    source_has_larger_material_contract: bool = False,
    preserve_source_contract_default: bool = False,
    allow_character_scope: bool = False,
    item_family_scope: bool = True,
) -> ArchiveMeshSwapScopePreflightResult:
    return ArchiveMeshSwapScopePreflightResult(
        request_id=1,
        allow_character_scope=allow_character_scope,
        item_family_scope=item_family_scope,
        same_weapon_folder=False,
        character_relationship_plan=None,
        source_related_entries=source_related_entries,
        relationship_edges=relationship_edges,
        unresolved_relationship_edges=(),
        source_sidecar_paths=source_sidecar_paths,
        source_appearance_paths=frozenset(),
        source_pbd_names=("Cloth_Banner",) if source_has_pbd_contract else (),
        source_wrapper_count=3 if source_has_larger_material_contract else 1,
        target_wrapper_count=1,
        source_has_pbd_contract=source_has_pbd_contract,
        source_has_larger_material_contract=source_has_larger_material_contract,
        preserve_source_contract_default=preserve_source_contract_default,
    )


def _run_dialog(owner: _ScopeOwner, target: ArchiveEntry, source: ArchiveEntry, prepared) -> List[str]:
    """Open the scope dialog, capture the behavior column, then reject it."""

    captured: List[str] = []

    def _close_dialog() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.windowTitle() == "In-Game Mesh Swap Scope":
                for tree in widget.findChildren(QTreeWidget):
                    for index in range(tree.topLevelItemCount()):
                        captured.append(tree.topLevelItem(index).text(2))
                widget.reject()
                return

    QTimer.singleShot(0, _close_dialog)
    owner._prompt_archive_in_game_mesh_swap_scope(target, source, prepared_scope=prepared)
    return captured


def test_cloth_donor_without_wider_contract_opens_the_scope_dialog(tmp_path: Path) -> None:
    """A PBD/cloth donor used to raise UnboundLocalError before the dialog appeared.

    preserve_source_contract_default is true whenever the donor has cloth OR a wider
    material contract, but the warning label was only built in the wider-contract
    branch and then used unconditionally.
    """

    app = _app()
    target = _entry(tmp_path, "character/model/weapon/002_sword/cd_phm_02_sword_0019.pac", 0)
    source = _entry(tmp_path, "character/model/weapon/003_sword/cd_phm_03_sword_0007.pac", 32)
    sidecar = _entry(tmp_path, "character/model/weapon/003_sword/cd_phm_03_sword_0007.pac_xml", 64)
    owner = _ScopeOwner((target, source, sidecar))

    _run_dialog(
        owner,
        target,
        source,
        _preflight(
            source_related_entries=(sidecar,),
            source_sidecar_paths=frozenset({sidecar.path}),
            source_has_pbd_contract=True,
            source_has_larger_material_contract=False,
            preserve_source_contract_default=True,
        ),
    )

    owner.deleteLater()
    app.processEvents()


def test_relationship_edge_reason_reaches_the_behavior_column(tmp_path: Path) -> None:
    """The dialog keyed edge lookups by a path string, the preflight by entry identity."""

    app = _app()
    target = _entry(tmp_path, "character/model/weapon/002_sword/cd_phm_02_sword_0019.pac", 0)
    source = _entry(tmp_path, "character/model/weapon/003_sword/cd_phm_03_sword_0007.pac", 32)
    texture = _entry(tmp_path, "character/texture/weapon/cd_phm_03_sword_0007_bc.dds", 64)
    owner = _ScopeOwner((target, source, texture))
    edge = ArchiveRelationEdge(
        source_path=source.path,
        related_path=texture.path,
        related_entry=texture,
        relation_kind="texture",
        reason="referenced by the source material sidecar",
        include_policy=ARCHIVE_REL_INCLUDE_REQUIRED,
    )

    behavior_texts = _run_dialog(
        owner,
        target,
        source,
        _preflight(
            source_related_entries=(texture,),
            relationship_edges=((owner._archive_entry_identity_key(texture), edge),),
        ),
    )

    assert behavior_texts, "the companion tree rendered no rows"
    assert any("referenced by the source material sidecar" in text for text in behavior_texts), (
        f"edge reason never reached the behavior column: {behavior_texts}"
    )

    owner.deleteLater()
    app.processEvents()
