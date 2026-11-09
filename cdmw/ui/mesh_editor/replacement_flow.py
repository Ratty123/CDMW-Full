"""Host-owned file selection and archive context for replacement commands."""

from PySide6.QtWidgets import QFileDialog

from cdmw.ui.archive_browser.workflow_dependencies import archive_workflow_dependency_context
from cdmw.ui.shell.tab_registry import DetachedToolWindow


def prepare_replacement_event(tab, session, event):
    args = dict(event.get("arguments") or {})
    state = session.shadow_service._session(session.shadow_session_id).replacement_state
    if event.get("command") in {"replacement_islands", "replacement_physics_profile", "replacement_translucency", "replacement_emission", "replacement_shader_controls", "replacement_guides", "replacement_cloth", "replacement_weapon_collisions", "replacement_collision_volumes", "replacement_jiggle"} and state is not None:
        # Drafts retain the original target and exact profile dependencies. They
        # remain editable with no mounted archive or live Archive Browser.
        if tab.standalone_rust_authoring_session is not session or tab.standalone_rust_closing:
            raise ValueError("The mesh session closed during replacement selection.")
        return {**event, "arguments": args}
    target = tab._current_target_entry()
    if target is None:
        raise ValueError("Open an archive mesh before importing a replacement.")
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    if state is None:
        args["_archive_entry"] = target
        args["_archive_dependencies"] = archive_workflow_dependency_context(owner, target)
    if event.get("command") == "replacement_choose":
        path, _ = QFileDialog.getOpenFileName(tab, "Import Replacement", "",
                                              "Mesh models (*.obj *.dae *.gltf *.glb *.fbx)")
        blender = _blender_for(tab, path) if path.lower().endswith(".fbx") else ""
        if not path or blender is None:
            args["cancelled"] = True
        else:
            args["source_path"] = path
            if blender:
                args["_blender"] = blender
    if tab.standalone_rust_authoring_session is not session or tab.standalone_rust_closing:
        raise ValueError("The mesh session closed during replacement selection.")
    if tab._current_target_entry().identity != target.identity:
        raise ValueError("The archive target changed during replacement selection.")
    return {**event, "arguments": args}


def _blender_for(tab, fbx_path):
    """The Blender that converts ``fbx_path``, asking once if none was chosen; None if declined.

    The choice is shared with Create New Item's Model step.
    """
    from cdmw.ui.new_item.blender_setting import (
        blender_for_fbx,
        remember_blender,
        suggested_blender,
    )

    chosen = blender_for_fbx()
    if chosen:
        return chosen
    suggestion = suggested_blender()
    path, _ = QFileDialog.getOpenFileName(
        tab, "Choose the Blender that reads FBX", str(suggestion) if suggestion is not None else "",
        "Blender (blender.exe blender);;All files (*)")
    if not path:
        return None
    stored = remember_blender(path)
    if not stored:
        raise ValueError(f"{path} is not a Blender CDMW can run. Choose blender.exe, or export the model as GLB.")
    return stored
