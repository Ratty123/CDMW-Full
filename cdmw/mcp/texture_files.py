"""File choosers, output review, and the rail Textures workspace."""

from pathlib import Path
from threading import Event
from time import monotonic

from cdmw.mcp.errors import (
    CANCELLED,
    FAILED,
    INVALID_ARGUMENTS,
    NOT_FOUND,
    REFUSED,
    UNAVAILABLE,
    ToolError,
)
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.texture_edits import choices, enabled, integer, select_combo
from cdmw.mcp.texture_tools import (
    PATH,
    _act,
    _editor,
    _panel,
    rail_editor,
    shell,
    texture_schema,
)
from cdmw.mcp.tools import ON_CALL, ON_UI, ON_WORKER, Tool


def workspace(context):
    view = getattr(shell(context), "textures", None)
    if view is None:
        raise ToolError(UNAVAILABLE, "The rail Textures workspace is unavailable.")
    return view


def rail_assets(context):
    job = workspace(context).job
    return [{"id": asset.key, "name": asset.label, "path": str(asset.source_path or ""),
             "game_path": asset.source_binding.archive_relative_path or asset.source_binding.relative_path,
             "selected": asset.key in job.selected, "active": asset.key == job.active_asset_key}
            for asset in job.assets.values()]


def _file_action(call, choose, answers=None):
    """Use the editor's worker and success handler. Relay failures to the MCP job."""
    from shiboken6 import isValid

    finished = Event()
    errors = []
    owner = []
    indices = []

    def submit():
        editor = _editor(call, needs_document=call.tool.name != "textures.open")

        def receive(ok, message):
            if ok:
                indices.append(editor.history_index)
            else:
                errors.append(message)
            finished.set()

        call.check_cancelled()
        result = choose(editor, receive)
        if editor._task_thread is not None:
            owner.append(editor)
        return result

    result = _act(call, submit, answers)
    if not owner:
        return result
    editor = owner[0]
    while not finished.wait(0.1):
        active = call.context.ui_call(lambda: isValid(editor) and editor._task_thread is not None)
        if not active and not finished.is_set():
            raise ToolError(CANCELLED, "The Texture Editor closed or stopped the task.")
    if errors:
        raise ToolError(FAILED, errors[0])
    return {**result, "completed": True, "history_after": indices[0], "history_index": indices[0]}


def _prepare_rail(call):
    from cdmw.ui.shell.lazy_tool_tab import LazyToolTab

    def request():
        container = getattr(shell(call.context), "texture_editor_tab", None)
        if not isinstance(container, LazyToolTab) or container.widget_if_created() is not None:
            return False
        container.request_widget()
        return True

    if call.context.ui_call(request):
        deadline = monotonic() + 30
        while call.context.ui_call(lambda: rail_editor(call.context) is None):
            if monotonic() >= deadline:
                raise ToolError(UNAVAILABLE, "The rail Texture Editor did not finish opening.")
            call.cancel_event.wait(0.05)
            call.check_cancelled()


def open_rail(call):
    args = call.arguments
    source = args.get("source", "file")
    wanted = args.get("texture")
    if source not in ("file", "archive", "project") or not wanted:
        raise ToolError(INVALID_ARGUMENTS, "Give a file, project or archive texture path.")
    if source == "archive":
        from cdmw.services.archive_preview_service import ensure_archive_preview_source

        def locate():
            entries = workspace(call.context).archive.archive_entries
            key = wanted.replace("\\", "/").casefold()
            matches = [entry for entry in entries if entry.path.replace("\\", "/").casefold() == key
                       and ("package" not in args or entry.pamt_path.parent.name == args["package"])]
            if len(matches) > 1:
                raise ToolError(INVALID_ARGUMENTS, "More than one package contains this path. Specify package.")
            if not matches:
                raise ToolError(NOT_FOUND, "The loaded archive index has no such texture.")
            return matches[0]

        entry = call.context.ui_call(locate)
        path, _ = ensure_archive_preview_source(entry, stop_event=call.cancel_event)
        call.check_cancelled()
        def open_archive():
            workspace(call.context).open_prepared_archive_texture(entry, path)
            return {"opening": True, "texture": wanted}
        return _act(call, open_archive)
    if not Path(wanted).is_file():
        raise ToolError(NOT_FOUND, f"There is no file {wanted}.")
    _prepare_rail(call)

    def open_file(editor, report_result):
        from cdmw.models import TextureEditorSourceBinding
        path = Path(wanted).resolve()
        editor._last_open_dir = str(path.parent)
        if source == "project":
            editor.load_project(path, report_result=report_result)
        else:
            editor.open_source_path(path, binding=TextureEditorSourceBinding(launch_origin="file"), report_result=report_result)
        return {"opening": True, "texture": wanted}

    return _file_action(call, open_file)


def _export(call):
    from cdmw.core.texture_editor_project_io import _texture_editor_assets_dir
    from cdmw.domain.output_paths import (
        OutputPathRefused,
        check_output_path,
        game_path_reason,
    )

    args = call.arguments
    kind, path = args["format"], Path(args["path"])
    suffix = {"png": ".png", "selection": ".png", "dds": ".dds", "project": ".json"}.get(kind)
    if suffix and path.suffix.lower() != suffix:
        raise ToolError(INVALID_ARGUMENTS, f"The destination must end in {suffix}.")

    def submit(editor, report_result):
        game = call.context.game_folder()
        try:
            check_output_path(path, game_folder=game)
            if kind == "project":
                check_output_path(_texture_editor_assets_dir(path), game_folder=game)
        except OutputPathRefused as exc:
            raise ToolError(REFUSED, str(exc)) from None
        if kind == "dds":
            from cdmw.core import texture_native
            if texture_native.find_directxtex_texture_binary() is None:
                raise ToolError(UNAVAILABLE, "The native DirectXTex encoder is unavailable.")
            reason = game_path_reason(Path(editor.workspace_root) / "native_temp", game_folder=game)
            if reason:
                raise ToolError(REFUSED, reason)
        if kind in ("selection", "grid"):
            control = editor.atlas_export_selection_button if kind == "selection" else editor.atlas_export_grid_button
            enabled(control)
            if "padding" in args:
                editor.atlas_padding_spin.setValue(args["padding"])
            if "trim" in args:
                editor.atlas_trim_checkbox.setChecked(args["trim"])
            if kind == "selection":
                editor.export_selection_region(report_result=report_result)
            else:
                if "cell_size" in args:
                    editor.grid_size_spin.setValue(args["cell_size"])
                if "skip_empty" in args:
                    editor.atlas_skip_empty_checkbox.setChecked(args["skip_empty"])
                editor.export_grid_slices_to(path, report_result=report_result, new_folder=True)
            return {"path": str(path)}
        method = {"png": editor.export_png_to, "dds": editor.export_dds_to, "project": editor.save_project_to}[kind]
        method(path, report_result=report_result)
        return {"path": str(path)}

    return _file_action(call, submit, {"save_file": str(path)} if kind == "selection" else None)


def _compare(call):
    editor = _editor(call)
    args = call.arguments
    if "mode" in args:
        select_combo(editor.view_mode_combo, args["mode"])
    if "split" in args:
        editor.compare_split_slider.setValue(args["split"])
    return {"mode": editor.view_mode_combo.currentData(), "split": editor.compare_split_slider.value()}


def _plan(call):
    if call.arguments["editor"] == "tool":
        job = workspace(call.context).job
        return {"mode": job.mode, "assets": rail_assets(call.context)}
    tab, _ = _panel(call.context)
    if not callable(getattr(tab, "_live_texture_plan", None)):
        raise ToolError(UNAVAILABLE, "Open a Mesh Editor document first.")
    plan = tab._live_texture_plan(include_body=call.arguments.get("include_body", True))
    return {"lines": list(plan.plan_lines) if plan else [], "refusals": list(plan.refusals) if plan else [],
            "left_out": list(plan.left_out) if plan else []}


#: The typed tools that do what each page of Review & Export offers.
REVIEW_EXPORT_TOOLS = {
    "edit": ["textures_export"],
    "replacement": ["textures_replace_state", "textures_replace_build"],
    "recolor": ["textures_recolor_state", "textures_recolor_build"],
    "upscale": ["textures_upscale_state", "textures_upscale_start"],
}


def _workflow(call):
    args = call.arguments
    if args["editor"] != "tool":
        raise ToolError(INVALID_ARGUMENTS, "Choose editor=tool for the rail's Textures workflow.")
    action = args["action"]
    paths = [Path(p) for p in args.get("paths", ())]
    if action == "add_textures" and (not paths or not all(p.is_file() for p in paths)):
        raise ToolError(INVALID_ARGUMENTS, "Add Textures requires existing files in paths.")
    if action == "add_mod" and (len(paths) != 1 or not paths[0].exists()):
        raise ToolError(INVALID_ARGUMENTS, "Add Mod takes one existing folder or ZIP in paths.")

    def run():
        view = workspace(call.context)
        if view.job.busy:
            raise ToolError(UNAVAILABLE, "The Textures workspace is busy.")
        if action == "add_textures":
            view.open_texture_sources(paths)
        elif action == "add_mod":
            view._choose_texture_mod(source=paths[0])
        else:
            view.show_texture_review(operation=args.get("operation"))
            chosen = args.get("operation") or view.job.mode
            if chosen in ("replace", "replacement"):
                chosen = "replacement"
            elif view._review_dialog is not None:
                chosen = view.export_operation.currentData() or chosen
            return {"action": action, "mode": view.job.mode, "assets": rail_assets(call.context),
                    "operation": chosen, "export_with": REVIEW_EXPORT_TOOLS.get(chosen, [])}
        return {"action": action, "mode": view.job.mode, "assets": rail_assets(call.context)}
    return _act(call, run)


def file_tools():
    return [
        Tool("textures.export", "textures", "Export a PNG, DDS or project with the editor's worker. "
             "Project creates sibling assets. Grid creates a new folder of PNGs. Selection exports a cropped PNG.",
             texture_schema({"format": choices("png", "dds", "project", "selection", "grid"), "path": PATH,
                             "padding": integer(0, 256), "trim": {"type": "boolean"},
                             "cell_size": integer(4, 1024), "skip_empty": {"type": "boolean"}}, ["format", "path"]),
             OUTPUT, "ui:TextureEditor.export_dialog", _export, ON_WORKER, output_paths=("path",)),
        Tool("textures.compare", "textures", "Read or choose the original, edited, split, or channel view.",
             texture_schema({"mode": choices("original", "edited", "split", "red", "green", "blue", "alpha"),
                             "split": integer(0, 100)}),
             READ, "ui:TextureEditor.view_mode_combo", _compare, ON_UI),
        Tool("textures.output_plan", "textures", "Read the Build Mod texture plan, or the rail job's selected assets and targets.",
             texture_schema({"include_body": {"type": "boolean"}}), READ, "ui:MeshEditor._live_texture_plan", _plan, ON_UI),
        Tool("textures.workflow", "textures", "With editor=tool, add texture files, select a mod folder or ZIP, or open "
             "Review & Export for the chosen operation; export_with names the tools that export it.", texture_schema({
                 "action": choices("add_textures", "add_mod", "review_export"),
                 "paths": {"type": "array", "items": PATH, "minItems": 1, "maxItems": 256},
                 "operation": choices("edit", "replacement", "recolor", "upscale")}, ["action"]),
             EDIT, "ui:TextureWorkspace.show_texture_review/open_texture_sources", _workflow, ON_CALL),
    ]
