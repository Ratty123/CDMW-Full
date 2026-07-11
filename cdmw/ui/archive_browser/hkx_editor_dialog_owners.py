from __future__ import annotations

from cdmw.ui.archive_browser import hkx_editor_dialog_shell_part_01 as _hkx_editor_dialog_shell_part_01
from cdmw.ui.archive_browser import hkx_editor_dialog_shell_part_02 as _hkx_editor_dialog_shell_part_02
from cdmw.ui.archive_browser import hkx_editor_dialog_placement_part_01 as _hkx_editor_dialog_placement_part_01
from cdmw.ui.archive_browser import hkx_editor_dialog_preview_part_01 as _hkx_editor_dialog_preview_part_01
from cdmw.ui.archive_browser import hkx_editor_dialog_preview_part_02 as _hkx_editor_dialog_preview_part_02
from cdmw.ui.archive_browser import hkx_editor_dialog_workspace_part_01 as _hkx_editor_dialog_workspace_part_01
from cdmw.ui.archive_browser import hkx_editor_dialog_workspace_part_02 as _hkx_editor_dialog_workspace_part_02
from cdmw.ui.archive_browser import hkx_editor_dialog_physics_part_01 as _hkx_editor_dialog_physics_part_01
from cdmw.ui.archive_browser import hkx_editor_dialog_physics_part_02 as _hkx_editor_dialog_physics_part_02
from cdmw.ui.archive_browser import hkx_editor_dialog_catalog_part_01 as _hkx_editor_dialog_catalog_part_01
from cdmw.ui.archive_browser import hkx_editor_dialog_catalog_part_02 as _hkx_editor_dialog_catalog_part_02
from cdmw.ui.archive_browser import hkx_editor_dialog_collision_part_01 as _hkx_editor_dialog_collision_part_01
from cdmw.ui.archive_browser import hkx_editor_dialog_wiring_part_01 as _hkx_editor_dialog_wiring_part_01

DIALOG_STEPS = (
    *_hkx_editor_dialog_shell_part_01.STEPS,
    *_hkx_editor_dialog_shell_part_02.STEPS,
    *_hkx_editor_dialog_placement_part_01.STEPS,
    *_hkx_editor_dialog_preview_part_01.STEPS,
    *_hkx_editor_dialog_preview_part_02.STEPS,
    *_hkx_editor_dialog_workspace_part_01.STEPS,
    *_hkx_editor_dialog_workspace_part_02.STEPS,
    *_hkx_editor_dialog_physics_part_01.STEPS,
    *_hkx_editor_dialog_physics_part_02.STEPS,
    *_hkx_editor_dialog_catalog_part_01.STEPS,
    *_hkx_editor_dialog_catalog_part_02.STEPS,
    *_hkx_editor_dialog_collision_part_01.STEPS,
    *_hkx_editor_dialog_wiring_part_01.STEPS,
)

__all__ = ["DIALOG_STEPS"]
