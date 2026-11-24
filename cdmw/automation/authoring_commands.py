"""Automation commands for authoring paths that start with a file chooser (test runs only).

Import Replacement and Export Mesh File in the Mesh Editor, and Create New Item's
painting template (New painting...). Each does what the click would; only the file
or folder chooser is skipped, its answer given as an argument. A Mesh Editor command
is sent to the editor's helper as the panel's own button sends it (``cdmw_command``),
so the request, the host's preparation, the worker and the helper's mapping step are
the real ones. Everything written lands inside the run's profile folder, as the
bridge's policy requires. Like every bridge command these run on the UI thread, return
at once and leave waiting to the driver, which polls the ``*_state`` commands.
"""

from __future__ import annotations

from pathlib import Path

_REPLACEMENT_SUFFIXES = {".obj", ".dae", ".gltf", ".glb", ".fbx"}
_EXPORT_FORMATS = {"obj", "glb"}
_LOOKUP_ATTRIBUTE = "_automation_archive_find_lookup"
_found: dict[str, dict[str, object]] = {}


def ui_commands(bridge) -> dict:
    """The commands by name, for the bridge's command table."""

    table = {
        "archive_find": archive_find,
        "archive_find_result": archive_find_result,
        "mesh_export": mesh_export,
        "replacement_state": replacement_state,
        "replacement_import": replacement_import,
        "replacement_apply": replacement_apply,
        "replacement_cancel": replacement_cancel,
        "painting_open": painting_open,
        "painting_state": painting_state,
        "painting_set": painting_set,
        "painting_build": painting_build,
        "painting_close": painting_close,
    }
    return {name: (lambda args, run=run: run(bridge.window, args)) for name, run in table.items()}


def _inside_profile(path: object, what: str) -> Path:
    from cdmw.app.app_folder import cdmw_folder

    target = Path(str(path or ""))
    if not str(path or "").strip() or not target.is_absolute() or not target.resolve().is_relative_to(cdmw_folder()):
        raise ValueError(f"{what} is written inside the run's own profile folder only.")
    return target


# ----- the archive index --------------------------------------------------------------
def archive_find(window, args: dict) -> dict[str, object]:
    """Look file names up in the live archive index, as Browse's search does; the answer
    is read with ``archive_find_result`` and the returned token."""

    import secrets

    from cdmw.domain.archives.catalogue import ArchiveLookupKind
    from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

    names = [str(name) for name in args.get("basenames") or () if str(name or "").strip()]
    if not names:
        raise ValueError("Name at least one file to look up.")
    archive = window.archive
    session = getattr(getattr(archive, "archive_remote_bridge", None), "current_session", None)
    if session is None:
        raise RuntimeError("The archive index is not open yet.")
    token = secrets.token_hex(4)
    _found[token] = {"done": False}

    def done(outcome) -> None:
        _found[token] = {"done": True, "truncated": bool(outcome.truncated), "entries": [
            {"path": dto.path, "entry_id": int(dto.entry_id), "package": dto.package,
             "active": bool(dto.is_active_override)} for dto in outcome.entries]}

    def failed(message: str) -> None:
        _found[token] = {"done": True, "error": str(message)}

    start_live_catalogue_lookup(archive, _LOOKUP_ATTRIBUTE,
                                lookup_requests(session.session_id, ArchiveLookupKind.BASENAMES, names),
                                on_done=done, on_error=failed)
    return {"token": token}


def archive_find_result(_window, args: dict) -> dict[str, object]:
    return dict(_found.get(str(args.get("token", "")), {"done": True, "error": "No lookup has that token."}))


# ----- the Mesh Editor ------------------------------------------------------------------
def _shown_editor(window):
    from cdmw.automation.pass_commands import _shown_document

    tab = _shown_document(window)
    return tab if tab is not None and getattr(tab, "standalone_rust_ready", False) else None


def _ready_editor(window):
    tab = _shown_editor(window)
    if tab is None:
        raise RuntimeError("No Mesh Editor document is ready.")
    if not getattr(tab, "standalone_rust_host_commands_supported", False):
        raise RuntimeError("This Mesh Editor helper does not take commands from CDMW; it is older than this app.")
    return tab


def _editor_busy(tab) -> bool:
    """A request is being worked on or waits: the helper would refuse another one."""

    return bool(getattr(tab, "standalone_rust_protocol_thread", None) is not None
                or getattr(tab, "standalone_rust_protocol_queue", None))


def _send(tab, command: str, arguments: dict) -> bool:
    message = tab._rust_host_message("cdmw_command", request_id=0,
                                     extra={"command": command, "arguments": dict(arguments)})
    return bool(tab._send_rust_message(message))


def mesh_export(window, args: dict) -> dict[str, object]:
    """Export Mesh File: the shown document's mesh as OBJ or GLB at ``path`` (inside the
    run's profile), as the button does after its file chooser."""

    path = _inside_profile(args.get("path"), "An exported mesh")
    format_name = path.suffix.lower().lstrip(".")
    if format_name not in _EXPORT_FORMATS:
        raise ValueError("Export an OBJ or GLB file (FBX needs Blender).")
    tab = _ready_editor(window)
    if _editor_busy(tab):
        return {"sent": False, "busy": True}
    path.parent.mkdir(parents=True, exist_ok=True)
    return {"sent": _send(tab, "export_mesh", {"path": str(path), "format": format_name}), "busy": False}


def replacement_state(window, _args: dict) -> dict[str, object]:
    """Import Replacement as the shown document has it: whether it is offered (and why
    not), the parts, and the model waiting in the mapping step."""

    tab = _shown_editor(window)
    if tab is None:
        return {"ready": False}
    from cdmw.automation.bridge import AutomationBridge
    from cdmw.ui.mesh_editor import replacement_flow

    state: dict[str, object] = {
        "ready": True,
        "supported": bool(getattr(tab, "standalone_rust_host_commands_supported", False)),
        "busy": _editor_busy(tab),
        "status": AutomationBridge._editor_status(tab),
        "chooser_answer_waiting": replacement_flow.source_path_override is not None,
    }
    session = getattr(tab, "standalone_rust_authoring_session", None)
    if state["busy"] or session is None:
        return state
    pending = getattr(session, "pending_replacement", None)
    if pending is not None:
        # The mapping step, read from the prepared import itself: the panel's full state
        # parses the original model again for its material notes.
        skin = getattr(pending, "skin", None)
        state.update({"available": True, "pending": {
            "token": pending.token,
            "source": pending.label,
            "sources": [part.name or f"Source {index}" for index, part in enumerate(pending.source.mesh.submeshes)],
            "suggested_targets": list(pending.suggested_targets),
            "targets": list(pending.target_part_ids),
            "rigged": bool(getattr(skin, "rigged", False)),
            # The weights choices the mapping step offers a rigged model, as the helper shows them.
            "weights": skin.payload() if getattr(skin, "rigged", False) else {"rigged": False},
            "material_error": pending.material_error,
        }})
        return state
    from cdmw.services.mesh_rust_replacement import replacement_ui_state

    ui = replacement_ui_state(session)
    state.update({key: ui.get(key) for key in ("available", "reason", "active", "has_import", "blocked_by")})
    state["parts"] = [{key: part.get(key) for key in ("index", "id", "name", "included")} for part in ui["parts"]]
    state["weight_notes"] = list(ui.get("weight_notes") or ())
    state["pending"] = None
    return state


def replacement_import(window, args: dict) -> dict[str, object]:
    """Import Replacement... with the mesh file at ``path``: Entire Mesh, or Selected Parts
    with ``part_ids``. The file chooser's answer is the path; the rest is the real path."""

    from cdmw.ui.mesh_editor import replacement_flow

    path = Path(str(args.get("path") or ""))
    if path.suffix.lower() not in _REPLACEMENT_SUFFIXES or not path.is_absolute() or not path.is_file():
        raise ValueError("Give the full path of an existing OBJ, DAE, glTF, GLB or FBX file.")
    if path.suffix.lower() == ".fbx":
        from cdmw.ui.new_item.blender_setting import blender_for_fbx

        # The Blender chosen before reads it, as the button's second chooser would; with none
        # chosen yet that chooser would ask, so this refuses instead.
        if not blender_for_fbx():
            raise ValueError("An FBX is read with Blender, and no Blender is chosen yet. Choose blender.exe once "
                             "(Import Replacement asks for it with an FBX, as does Create New Item's Model step), "
                             "or give an OBJ, DAE, glTF or GLB file.")
    scope = str(args.get("scope") or "entire")
    part_ids = [str(value) for value in args.get("part_ids") or ()]
    if scope not in {"entire", "selected"} or (scope == "selected" and not part_ids):
        raise ValueError("The scope is entire, or selected with the part ids.")
    tab = _ready_editor(window)
    if _editor_busy(tab):
        return {"sent": False, "busy": True}
    replacement_flow.source_path_override = str(path)
    sent = _send(tab, "replacement_choose", {"scope": scope, "part_ids": part_ids if scope == "selected" else []})
    if not sent:
        replacement_flow.source_path_override = None
    return {"sent": sent, "busy": False}


def replacement_apply(window, args: dict) -> dict[str, object]:
    """Apply Replacement on the model in the mapping step. ``targets`` gives each imported
    part's target part id; by default each takes the suggested target, and one without a
    suggestion takes ``fallback_target`` (the first target part when not given).
    ``materials`` is original (Keep Original Materials, the default) or imported.
    ``weights`` is the weights choice for a rigged model (preserve, reduce, fold, extend or
    transfer); without one the step's own default is taken, and with none the Apply
    button stays disabled, so this refuses."""

    tab = _ready_editor(window)
    pending = getattr(getattr(tab, "standalone_rust_authoring_session", None), "pending_replacement", None)
    if pending is None:
        raise RuntimeError("No replacement model waits in the mapping step; import one first.")
    if _editor_busy(tab):
        return {"sent": False, "busy": True}
    fallback = str(args.get("fallback_target") or pending.target_part_ids[0])
    targets = [str(value or "") or fallback for value in (args.get("targets") or pending.suggested_targets)]
    materials = str(args.get("materials") or "original")
    if materials not in {"original", "imported"}:
        raise ValueError("The materials are original or imported.")
    arguments: dict[str, object] = {"token": pending.token, "targets": targets, "materials": materials}
    skin = getattr(pending, "skin", None)
    if args.get("weights"):
        arguments["weights"] = str(args["weights"])
    elif getattr(skin, "rigged", False):
        if not skin.default_policy:
            raise ValueError(f"Choose how to handle the imported weights. {skin.summary}")
        arguments["weights"] = skin.default_policy
    return {"sent": _send(tab, "replacement_apply", arguments), "busy": False, "targets": targets}


def replacement_cancel(window, _args: dict) -> dict[str, object]:
    """Cancel Import in the mapping step."""

    from cdmw.ui.mesh_editor import replacement_flow

    replacement_flow.source_path_override = None
    tab = _ready_editor(window)
    if _editor_busy(tab):
        return {"sent": False, "busy": True}
    return {"sent": _send(tab, "replacement_cancel", {}), "busy": False}


# ----- Create New Item's painting template ------------------------------------------
def _new_item_workflow(window):
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    tab = created_tool_widget(getattr(window.shell, "new_item_studio_tab", None))
    return getattr(tab, "workflow", tab)


def _painting_dialog(window):
    workflow = _new_item_workflow(window)
    return getattr(getattr(workflow, "template_panel", None), "_painting_dialog", None)


def _open_dialog(window):
    dialog = _painting_dialog(window)
    if dialog is None or dialog.isHidden():
        raise RuntimeError("New painting is not open; open it first.")
    return dialog


def painting_open(window, _args: dict) -> dict[str, object]:
    """Show Create New Item and press New painting... on its Template page. Until the page
    and the archive tables are ready this says what it waits for; ask again."""

    # Shown as a click on the rail shows it; the tab builds itself in steps after that.
    window.shell._activate_tool_key("new_item_studio")
    workflow = _new_item_workflow(window)
    if workflow is None:
        return {"open": False, "waiting": "Create New Item is being built."}
    panel = getattr(workflow, "template_panel", None)
    if panel is None or not getattr(workflow, "_panels_built", False):
        return {"open": False, "waiting": "The Template page is being built."}
    controller = workflow.controller
    if controller.snapshot is None:
        if not controller.busy:
            workflow.start_snapshot()
        return {"open": False, "waiting": "Create New Item is reading the archives.",
                "error": str(getattr(controller, "_snapshot_error", "") or "")}
    dialog = panel._painting_dialog
    if dialog is None or dialog.isHidden():
        if not panel.painting_button.isEnabled():
            return {"open": False, "waiting": "New painting... is not available now."}
        panel.painting_button.click()
    return painting_state(window, {})


def painting_state(window, _args: dict) -> dict[str, object]:
    """The New painting dialog as shown: frames, the paintings and their texts, status, log."""

    dialog = _painting_dialog(window)
    if dialog is None or dialog.isHidden():
        return {"open": False}
    return {
        "open": True,
        "building": bool(dialog._building),
        "frames": [{"mesh": frame.mesh, "stem": frame.stem, "label": frame.label,
                    "texture_size": list(frame.texture_size), "aspect": float(frame.canvas.aspect)}
                   for frame in dialog._frames],
        "paintings": [{"frame": request.frame, "picture": str(request.picture or ""), "fit": request.fit,
                       "names": dict(request.names), "descriptions": dict(request.descriptions)}
                      for request in dialog.painting_requests()],
        "current": int(dialog._current),
        "listed": [dialog.painting_list.item(row).text() for row in range(dialog.painting_list.count())],
        "frame_info": dialog.frame_info.text(),
        "preview": dialog.preview.message.text(),
        "preview_shown": dialog.preview.has_picture(),
        "view": "3d" if dialog.preview_tabs.currentWidget() is dialog.viewport_page else "front",
        "viewport_busy": dialog.viewport_busy_now(),
        "viewport_status": dialog.viewport_status.text(),
        "mod_name": dialog.mod_name.text(),
        "folder": dialog.folder.text(),
        "status": dialog.status.text(),
        "error": dialog.status.property("severity") == "error",
        "log": dialog.log.toPlainText().splitlines()[-60:],
        "build_enabled": dialog.build_button.isEnabled(),
    }


class _ChosenPicture:
    """Stands in for QFileDialog while Choose picture... runs: it answers with one path."""

    path = ""

    @classmethod
    def getOpenFileName(cls, *_args, **_kwargs):  # noqa: N802 - Qt's name
        return cls.path, ""


def painting_set(window, args: dict) -> dict[str, object]:
    """Fill the shown painting as a user would: ``add`` (Add painting first), ``frame``
    (its mesh path or file stem), ``picture`` (the file Choose picture... answers with),
    ``fit`` (fill or whole), ``texts`` ({language: {name, description}}), ``mod_name``,
    ``folder`` (inside the run's profile) and ``view`` (front or 3d: the preview tab)."""

    from cdmw.ui.new_item import painting_dialog

    dialog = _open_dialog(window)
    if dialog._building:
        raise RuntimeError("The painting dialog is busy (reading the frames or building).")
    if not dialog._frames:
        raise RuntimeError("The frames are not read yet.")
    folder = _inside_profile(args["folder"], "A painting mod") if "folder" in args else None
    if args.get("add"):
        dialog.add_button.click()
    if "frame" in args:
        wanted = str(args["frame"])
        index = dialog.frame.findData(wanted)
        if index < 0:
            index = next((row for row in range(dialog.frame.count())
                          if Path(str(dialog.frame.itemData(row) or "")).stem.casefold() == wanted.casefold()), -1)
        if index < 0:
            raise ValueError(f"No frame {wanted} is offered.")
        dialog.frame.set_current_frame_row(index)
    if "picture" in args:
        picture = Path(str(args["picture"]))
        if not picture.is_absolute() or not picture.is_file():
            raise ValueError("Give the full path of an existing picture.")
        chooser = painting_dialog.QFileDialog
        _ChosenPicture.path = str(picture)
        painting_dialog.QFileDialog = _ChosenPicture
        try:
            dialog.choose_picture.click()
        finally:
            painting_dialog.QFileDialog = chooser
    if "fit" in args:
        index = dialog.fit.findData(str(args["fit"]))
        if index < 0:
            raise ValueError("The fit is fill or whole.")
        dialog.fit.setCurrentIndex(index)
    for language, texts in dict(args.get("texts") or {}).items():
        index = dialog.language.findData(str(language))
        if index < 0:
            raise ValueError(f"No language {language}.")
        dialog.language.setCurrentIndex(index)
        if "name" in texts:
            # Typing emits textEdited, which the dialog listens to; setText does not.
            dialog.name.setText(str(texts["name"]))
            dialog.name.textEdited.emit(str(texts["name"]))
        if "description" in texts:
            dialog.description.setPlainText(str(texts["description"]))
    if args.get("texts"):
        dialog.language.setCurrentIndex(max(0, dialog.language.findData("eng")))
    if "mod_name" in args:
        dialog.mod_name.setText(str(args["mod_name"]))
    if folder is not None:
        dialog.folder.setText(str(folder))
    if "view" in args:
        views = {"front": dialog.preview, "3d": dialog.viewport_page}
        if str(args["view"]) not in views:
            raise ValueError("The view is front or 3d.")
        dialog.preview_tabs.setCurrentWidget(views[str(args["view"])])
    return painting_state(window, {})


def painting_build(window, _args: dict) -> dict[str, object]:
    """Press Build mod. The folder must be inside the run's profile."""

    dialog = _open_dialog(window)
    _inside_profile(dialog.folder.text().strip(), "A painting mod")
    if not dialog.build_button.isEnabled():
        return {"started": False, "status": dialog.status.text()}
    dialog.build_button.click()
    return {"started": bool(dialog._building), "status": dialog.status.text()}


def painting_close(window, _args: dict) -> bool:
    """Press Close (it cancels a build that is still running, as the button does)."""

    dialog = _painting_dialog(window)
    if dialog is None or dialog.isHidden():
        return False
    dialog.close_button.click()
    return True
