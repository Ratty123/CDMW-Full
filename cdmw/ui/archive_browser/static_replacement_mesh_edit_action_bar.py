"""Action Bar callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_action_bar_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_editor_apply_action_bar_service_action(_state, _callbacks,
        action: str,
        *,
        action_key: str,
        action_text: str,
        params: dict[str, object] | None = None,
        params_factory: object | None = None,
        topology_action: bool,
        edge_action: bool = False,
        require_selection: bool = True,
    ) -> bool:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return False
    can_edit, reason = _callbacks._mesh_edit_can_edit_scope()
    if not can_edit:
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), reason)
        return True
    if topology_action and _state._morph_slider_has_nonzero_values():
        _state.QMessageBox.information(
            _state.dialog,
            _state._mesh_edit_dialog_title_helper(),
            "Bake or reset Morph Sliders before changing mesh topology.",
        )
        return True
    selected_vertices, selected_faces = _callbacks._mesh_editor_action_selection()
    selected_sources = _callbacks._mesh_editor_action_source_indices()
    selected_edges = _callbacks._mesh_editor_edge_selection(selected_vertices, selected_faces) if edge_action else {}
    if require_selection and not selected_vertices and not selected_faces and not selected_edges and not selected_sources:
        _state.self.set_status_message(
            f"Select adjacent vertices, faces, or edges before using {action_text}." if edge_action
            else f"Select vertices or faces before using {action_text}.",
            error=True,
        )
        return True
    action_params = dict(params or {})
    if callable(params_factory):
        built_params = params_factory()
        if built_params is None:
            return True
        action_params.update(dict(built_params or {}))
    _callbacks._show_mesh_edit_tab()
    _callbacks._set_mesh_edit_enabled(True)
    if _callbacks._mesh_edit_start_topology_worker(
        action,
        action_text=action_text,
        selected_vertices=selected_vertices,
        selected_faces=selected_faces,
        selected_edges=selected_edges,
        selected_source_indices=selected_sources,
        params={**action_params, "recompute_normals": True},
        commit_callback=lambda result: _callbacks._mesh_editor_commit_action_bar_service_result(
            result,
            action_key=action_key,
            action_text=action_text,
            topology_action=topology_action,
        ),
    ):
        return True
    _callbacks._mesh_edit_record_snapshot()
    result = _callbacks._mesh_editor_apply_static_replacement_edit(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        action,
        edges_by_submesh=selected_edges,
        vertices_by_submesh=selected_vertices,
        faces_by_submesh=selected_faces,
        source_indices=selected_sources,
        recompute_normals=True,
        **action_params,
    )
    return _callbacks._mesh_editor_commit_action_bar_service_result(
        result,
        action_key=action_key,
        action_text=action_text,
        topology_action=topology_action,
    )

def _mesh_editor_prompt_action_value(_state, _callbacks,
        action_text: str,
        label_text: str,
        default_value: float,
        minimum: float,
        maximum: float,
        decimals: int,
    ) -> float | None:
    if _state.QInputDialog is None:
        _state.self.set_status_message(f"Mesh Editor action needs an input dialog: {action_text}.", error=True)
        return None
    value, accepted = _state.QInputDialog.getDouble(
        _state.dialog,
        _state._mesh_edit_dialog_title_helper(),
        label_text,
        float(default_value),
        float(minimum),
        float(maximum),
        int(decimals),
    )
    return float(value) if accepted else None

def _mesh_editor_material_part_choices(_state, _callbacks, ) -> tuple[dict[str, object], ...]:
    mesh = _state._mesh_edit_state.replacement_mesh_for_mapping
    if mesh is None:
        return ()
    choices: list[dict[str, object]] = []
    allowed_indices = set(_state._mesh_edit_allowed_source_indices())
    for source_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        if allowed_indices and source_index not in allowed_indices:
            continue
        material = str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"part_{source_index}")
        texture = str(getattr(submesh, "texture", "") or "")
        display_name = _state._source_display_name(source_index) if callable(_state._source_display_name) else f"Part {source_index}"
        label = f"{display_name}: {material}"
        if texture:
            label = f"{label} / {texture}"
        choices.append(
            {
                "label": label,
                "source_index": source_index,
                "material": material,
                "texture": texture,
                "submesh": submesh,
            }
        )
    return tuple(choices)

def _mesh_editor_default_material_choice_index(_state, _callbacks, choices: tuple[dict[str, object], ...]) -> int:
    selected_vertices, selected_faces = _callbacks._mesh_editor_action_selection()
    selected_sources = set(selected_vertices) | set(selected_faces) | set(_callbacks._mesh_editor_action_source_indices())
    selected_source_index = _state._mesh_edit_selected_source_index()
    if selected_source_index >= 0:
        selected_sources.add(selected_source_index)
    for choice_index, choice in enumerate(choices):
        if int(choice.get("source_index", -1)) in selected_sources:
            return choice_index
    return 0

def _mesh_editor_prompt_material_part(_state, _callbacks, action_text: str, label_text: str) -> dict[str, object] | None:
    if _state.QInputDialog is None or not callable(getattr(_state.QInputDialog, "getItem", None)):
        _state.self.set_status_message(f"Mesh Editor action needs a material picker: {action_text}.", error=True)
        return None
    choices = _callbacks._mesh_editor_material_part_choices()
    if not choices:
        _state.self.set_status_message(f"No material parts are available for {action_text}.", error=True)
        return None
    labels = [str(choice["label"]) for choice in choices]
    selected_label, accepted = _state.QInputDialog.getItem(
        _state.dialog,
        _state._mesh_edit_dialog_title_helper(),
        label_text,
        labels,
        _callbacks._mesh_editor_default_material_choice_index(choices),
        False,
    )
    if not accepted:
        return None
    label_to_choice = {str(choice["label"]): choice for choice in choices}
    return label_to_choice.get(str(selected_label))

def _mesh_editor_material_route_params_from_submesh(_state, _callbacks, submesh: object) -> dict[str, object]:
    params: dict[str, object] = {}
    attr_params = (
        ("cdmw_material_authority_profile", "material_authority_profile"),
        ("cdmw_material_authority_contract", "material_authority_contract"),
        ("cdmw_source_material_name", "source_material_name"),
        ("cdmw_target_material_name", "target_material_name"),
        ("cdmw_target_material_slot_index", "target_material_slot_index"),
        ("cdmw_material_slot_kind", "slot_kind"),
        ("cdmw_source_texture_set_key", "source_texture_set_key"),
        ("cdmw_material_route_status", "route_status"),
        ("cdmw_material_route_reason", "route_reason"),
    )
    for attr_name, param_name in attr_params:
        if hasattr(submesh, attr_name):
            params[param_name] = getattr(submesh, attr_name)
    overrides = getattr(submesh, "preview_native_material_overrides", None)
    if isinstance(overrides, _state.Mapping):
        params["preview_native_material_overrides"] = dict(overrides)
    if "material_authority_profile" not in params and callable(_state._current_complete_swap_material_profile_token):
        profile = str(_state._current_complete_swap_material_profile_token() or "").strip()
        if profile:
            params["material_authority_profile"] = profile
    return params

def _mesh_editor_material_assign_params(_state, _callbacks, action_text: str) -> dict[str, object] | None:
    choice = _callbacks._mesh_editor_prompt_material_part(action_text, "Assign selected elements to material part:")
    if choice is None:
        return None
    params = {
        "material": str(choice.get("material", "") or ""),
        "texture": str(choice.get("texture", "") or ""),
        "target_material_name": str(choice.get("material", "") or ""),
    }
    params.update(_callbacks._mesh_editor_material_route_params_from_submesh(choice.get("submesh")))
    return params

def _mesh_editor_material_copy_params(_state, _callbacks, action_text: str) -> dict[str, object] | None:
    choice = _callbacks._mesh_editor_prompt_material_part(action_text, "Copy material routing from part:")
    if choice is None:
        return None
    return {"source_submesh_index": int(choice.get("source_index", -1))}

_SERVICE_TOPOLOGY_ACTIONS = frozenset(
    {
        "dissolve", "duplicate", "mirror", "extrude", "inset", "merge", "weld", "fill",
        "uv_transform", "recalculate_normals", "generate_tangents", "flip_normals",
        "sharpen_normals", "soften_normals", "weighted_normals", "copy_normals",
    }
)
_SERVICE_CLEANUP_ACTIONS = frozenset(
    {"remove_doubles", "delete_loose_vertices", "compact_orphans", "fix_winding", "fill_holes"}
)
_SERVICE_NON_TOPOLOGY_ACTIONS = frozenset(
    {
        "uv_transform", "recalculate_normals", "generate_tangents", "flip_normals",
        "sharpen_normals", "soften_normals", "weighted_normals", "copy_normals",
    }
)
_EDGE_SERVICE_ACTIONS = frozenset({"loop_cut", "edge_split", "bridge"})


def _mesh_editor_action_bar_action_requested(_state, _callbacks, action: object) -> bool:
    key = str(getattr(action, "key", "") or "").strip()
    text = str(getattr(action, "text", "") or key or "tool").strip()
    command = str(getattr(action, "command", "") or "").strip()
    mode = str(getattr(action, "mode", "") or "").strip()
    selection_mode = str(getattr(action, "selection_mode", "") or "").strip()
    params = dict(tuple(getattr(action, "params", ()) or ()))
    if _callbacks._mesh_edit_worker_active():
        _state.self.set_status_message("Wait for the current mesh edit to finish, or cancel it first.", error=True)
        return True
    if command == "set_mode":
        if mode == "object":
            _callbacks._set_mesh_edit_enabled(False)
            return True
        _callbacks._show_mesh_edit_tab()
        _callbacks._set_mesh_edit_enabled(True)
        if mode == "edit":
            _state.mesh_editor_action_bar_selection_mode["value"] = "vertex"
            return _callbacks._select_mesh_edit_tool("vertex")
        if mode == "sculpt":
            return _callbacks._select_mesh_edit_tool(_state._mesh_edit_current_tool() if _state._mesh_edit_current_tool() != "vertex" else "grab")
        return False
    if command == "select":
        if selection_mode not in {"vertex", "edge", "face"}:
            return False
        _state.mesh_editor_action_bar_selection_mode["value"] = selection_mode
        _callbacks._show_mesh_edit_tab()
        _callbacks._set_mesh_edit_enabled(True)
        return _callbacks._select_mesh_edit_tool("vertex")
    if key == "transform_rotate":
        degrees = _callbacks._mesh_editor_prompt_action_value(text, "Rotate selected elements around Z axis (degrees):", 15.0, -360.0, 360.0, 2)
        if degrees is None:
            return True
        return _callbacks._mesh_editor_apply_action_bar_service_action(
            "transform",
            action_key=key,
            action_text=text,
            params={"rotate": (0.0, 0.0, degrees)},
            topology_action=False,
        )
    if key == "transform_scale":
        factor = _callbacks._mesh_editor_prompt_action_value(text, "Uniform scale selected elements:", 1.1, 0.01, 100.0, 4)
        if factor is None:
            return True
        return _callbacks._mesh_editor_apply_action_bar_service_action(
            "transform",
            action_key=key,
            action_text=text,
            params={"scale": (factor, factor, factor)},
            topology_action=False,
        )
    if key == "transform_move":
        _callbacks._show_mesh_edit_tab()
        _callbacks._set_mesh_edit_enabled(True)
        return _callbacks._select_mesh_edit_tool("grab", active_action_key="transform_move")
    if command == "brush":
        tool = str(params.get("tool") or "grab").strip()
        _callbacks._show_mesh_edit_tab()
        _callbacks._set_mesh_edit_enabled(True)
        active_key = key or _callbacks._mesh_editor_tool_action_key(tool)
        return _callbacks._select_mesh_edit_tool(tool, active_action_key=active_key)
    if command in _SERVICE_TOPOLOGY_ACTIONS:
        return _callbacks._mesh_editor_apply_action_bar_service_action(
            command,
            action_key=key or command,
            action_text=text,
            params=params,
            topology_action=command not in _SERVICE_NON_TOPOLOGY_ACTIONS,
        )
    if command in {"triangulate_display", "quadrangulate_display"}:
        _state.self.set_status_message(
            f"{text} is legacy display-shape cleanup and is not available in active Mesh Edit.",
            error=True,
        )
        return True
    if command in _SERVICE_CLEANUP_ACTIONS:
        return _callbacks._mesh_editor_apply_action_bar_service_action(
            command,
            action_key=key or command,
            action_text=text,
            params=params,
            topology_action=True,
            require_selection=False,
        )
    if command == "material_assign":
        return _callbacks._mesh_editor_apply_action_bar_service_action(
            command,
            action_key=key or command,
            action_text=text,
            params_factory=lambda: _callbacks._mesh_editor_material_assign_params(text),
            topology_action=False,
        )
    if command == "material_copy":
        return _callbacks._mesh_editor_apply_action_bar_service_action(
            command,
            action_key=key or command,
            action_text=text,
            params_factory=lambda: _callbacks._mesh_editor_material_copy_params(text),
            topology_action=False,
        )
    if command in _EDGE_SERVICE_ACTIONS:
        return _callbacks._mesh_editor_apply_action_bar_service_action(
            command,
            action_key=key or command,
            action_text=text,
            params=params,
            topology_action=True,
            edge_action=True,
        )
    if command == "delete":
        _callbacks._show_mesh_edit_tab()
        _callbacks._mesh_edit_delete_selected_faces()
        return True
    if command == "subdivide":
        _callbacks._show_mesh_edit_tab()
        _callbacks._mesh_edit_subdivide_selection()
        return True
    if command == "refine_smooth":
        _callbacks._show_mesh_edit_tab()
        _callbacks._mesh_edit_subdivide_selection(refine_smooth=True)
        return True
    if command in {"split", "separate"}:
        _callbacks._show_mesh_edit_tab()
        _callbacks._mesh_edit_split_selection_to_part()
        return True
    if command == "undo":
        _callbacks._mesh_edit_undo()
        return True
    if command == "redo":
        _callbacks._mesh_edit_redo()
        return True
    return False


_CALLBACKS = (
    _mesh_editor_apply_action_bar_service_action,
    _mesh_editor_prompt_action_value,
    _mesh_editor_material_part_choices,
    _mesh_editor_default_material_choice_index,
    _mesh_editor_prompt_material_part,
    _mesh_editor_material_route_params_from_submesh,
    _mesh_editor_material_assign_params,
    _mesh_editor_material_copy_params,
    _mesh_editor_action_bar_action_requested,
)
