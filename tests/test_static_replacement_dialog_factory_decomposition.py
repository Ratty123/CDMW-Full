from __future__ import annotations

import ast
import builtins
import importlib
import inspect
from pathlib import Path
import symtable
from types import SimpleNamespace
from unittest.mock import MagicMock

from cdmw.ui.archive_browser import static_replacement_dialog_callback_factories as callbacks
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_preview_model_part_01 as preview_model_owner
from cdmw.ui.archive_browser import static_replacement_dialog_sections_texture_material_part_02 as texture_material_owner
from cdmw.ui.archive_browser import static_replacement_dialog_remaining_callbacks as remaining_callbacks
from cdmw.ui.archive_browser import static_replacement_dialog_routing_callbacks as routing_callbacks
from cdmw.ui.archive_browser import static_replacement_dialog_source_part_mutation_callbacks as source_part_mutation_callbacks
from cdmw.ui.archive_browser import static_replacement_dialog_texture_callbacks as texture_callbacks
from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT


ROOT = Path(__file__).resolve().parents[1]
OWNER_ROOT = ROOT / "cdmw" / "ui" / "archive_browser"

MOVED_CALLBACK_FACTORIES = (
    (
        remaining_callbacks,
        "create_alignment_preview_render_settings_callbacks",
        ("remaining_preview_render_settings_part_01",),
    ),
    (
        remaining_callbacks,
        "create_alignment_geometry_history_callbacks",
        ("remaining_geometry_history_part_01",),
    ),
    (
        remaining_callbacks,
        "create_alignment_original_copy_payload_callbacks",
        ("remaining_original_copy_payload_part_01",),
    ),
    (
        remaining_callbacks,
        "create_alignment_source_role_flush_callbacks",
        ("remaining_source_role_flush_part_01",),
    ),
    (
        remaining_callbacks,
        "create_alignment_selected_part_adjustment_callbacks",
        ("remaining_selected_part_adjustment_part_01",),
    ),
    (
        remaining_callbacks,
        "create_alignment_selected_part_glow_picker_callbacks",
        ("remaining_selected_part_glow_picker_part_01",),
    ),
    (
        remaining_callbacks,
        "create_alignment_static_preview_refresh_callbacks",
        ("remaining_static_preview_refresh_part_01",),
    ),
    (
        remaining_callbacks,
        "create_alignment_source_material_plan_refresh_callbacks",
        ("remaining_source_material_plan_refresh_part_01",),
    ),
    (
        remaining_callbacks,
        "create_alignment_manual_profile_control_callbacks",
        ("remaining_manual_profile_control_part_01",),
    ),
    (
        texture_callbacks,
        "create_alignment_added_part_texture_callbacks",
        ("texture_added_part_texture_part_01",),
    ),
    (
        texture_callbacks,
        "create_alignment_original_texture_material_callbacks",
        ("texture_original_texture_material_part_01",),
    ),
    (
        texture_callbacks,
        "create_alignment_material_plan_final_preview_callbacks",
        ("texture_material_plan_final_preview_part_01",),
    ),
    (
        texture_callbacks,
        "create_alignment_texture_table_callbacks",
        ("texture_texture_table_part_01",),
    ),
    (
        source_part_mutation_callbacks,
        "create_alignment_source_part_mutation_callbacks",
        ("source_part_mutation_part_01", "source_part_mutation_part_02"),
    ),
    (
        routing_callbacks,
        "create_alignment_dialog_layout_callbacks",
        ("routing_dialog_layout_part_01",),
    ),
    (
        routing_callbacks,
        "create_alignment_source_part_geometry_action_callbacks",
        ("routing_source_part_geometry_action_part_01",),
    ),
    (
        routing_callbacks,
        "create_alignment_complete_swap_callbacks",
        ("routing_complete_swap_part_01",),
    ),
)


class _FactoryProbeContext(dict[str, object]):
    def get(self, key: str, default: object = None) -> object:
        if key not in self:
            self[key] = MagicMock(name=key)
        return super().get(key, default)


def _callback_owner_trees(owner_suffixes: tuple[str, ...]) -> tuple[ast.Module, ...]:
    return tuple(
        ast.parse(
            (
                OWNER_ROOT
                / f"static_replacement_dialog_callbacks_{suffix}.py"
            ).read_text(encoding="utf-8")
        )
        for suffix in owner_suffixes
    )


def _owner_result_names(trees: tuple[ast.Module, ...]) -> tuple[str, ...]:
    names: list[str] = []
    for tree in trees:
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "_factory_result_values"
                and node.args
                and isinstance(node.args[0], ast.Dict)
            ):
                continue
            names.extend(
                key.value
                for key in node.args[0].keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
    return tuple(names)


def _annotation_text(annotation: ast.expr | None) -> str | None:
    return ast.unparse(annotation) if annotation is not None else None


def _ast_signature_shape(node: ast.FunctionDef) -> tuple[tuple[object, ...], ...]:
    positional = (*node.args.posonlyargs, *node.args.args)
    first_default = len(positional) - len(node.args.defaults)
    shape: list[tuple[object, ...]] = []
    for index, argument in enumerate(positional):
        kind = "POSITIONAL_ONLY" if index < len(node.args.posonlyargs) else "POSITIONAL_OR_KEYWORD"
        shape.append(
            (
                argument.arg,
                kind,
                index >= first_default,
                _annotation_text(argument.annotation),
            )
        )
    if node.args.vararg is not None:
        shape.append(
            (
                node.args.vararg.arg,
                "VAR_POSITIONAL",
                False,
                _annotation_text(node.args.vararg.annotation),
            )
        )
    for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        shape.append(
            (
                argument.arg,
                "KEYWORD_ONLY",
                default is not None,
                _annotation_text(argument.annotation),
            )
        )
    if node.args.kwarg is not None:
        shape.append(
            (
                node.args.kwarg.arg,
                "VAR_KEYWORD",
                False,
                _annotation_text(node.args.kwarg.annotation),
            )
        )
    return tuple(shape)


def _runtime_signature_shape(callback: object) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            parameter.name,
            parameter.kind.name,
            parameter.default is not inspect.Parameter.empty,
            None
            if parameter.annotation is inspect.Parameter.empty
            else str(parameter.annotation),
        )
        for parameter in inspect.signature(callback).parameters.values()
    )


def _state_attribute_names(nodes: list[ast.stmt]) -> set[str]:
    return {
        node.attr
        for statement in nodes
        for node in ast.walk(statement)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "_state"
    }


def _owner_paths() -> tuple[Path, ...]:
    patterns = (
        "static_replacement_dialog_factory_*.py",
        "static_replacement_dialog_callbacks_*_part_*.py",
        "static_replacement_dialog_sections_*_part_*.py",
    )
    return tuple(sorted({path for pattern in patterns for path in OWNER_ROOT.glob(pattern)}))


def test_static_replacement_factory_owners_are_bounded() -> None:
    for path in _owner_paths():
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, path.name
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 150, f"{path.name}:{node.name}"


def test_static_replacement_factory_owners_have_no_unbound_global_references() -> None:
    builtin_names = set(dir(builtins))
    failures: list[str] = []
    for path in _owner_paths():
        table = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
        module_names = {
            symbol.get_name()
            for symbol in table.get_symbols()
            if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
        }

        def inspect_table(current: symtable.SymbolTable) -> None:
            for symbol in current.get_symbols():
                name = symbol.get_name()
                if (
                    symbol.is_referenced()
                    and symbol.is_global()
                    and name not in module_names
                    and name not in builtin_names
                ):
                    failures.append(f"{path.name}:{current.get_name()} references unbound {name!r}")
            for child in current.get_children():
                inspect_table(child)

        inspect_table(table)

    assert not failures, "\n".join(failures)


def test_static_replacement_section_factories_initialize_every_state_attribute() -> None:
    factory_tree = ast.parse(
        (OWNER_ROOT / "static_replacement_dialog_factory_owners.py").read_text(encoding="utf-8")
    )
    initial_names = {"context", "_factory_globals", "_factory_result_values"}
    failures: list[str] = []
    for owner_name in (
        "setup_options_transform",
        "mesh_geometry_preview",
        "texture_material",
        "source_parts_outliner",
    ):
        factory_name = f"create_alignment_{owner_name}_section"
        factory_node = next(
            node
            for node in factory_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == factory_name
        )
        factory_call = next(
            node
            for node in ast.walk(factory_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_static_replacement_factory"
        )
        global_names = {
            element.value
            for element in factory_call.args[2].elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        assigned = set(initial_names) | global_names
        referenced: set[str] = set()
        for path in sorted(OWNER_ROOT.glob(f"static_replacement_dialog_sections_{owner_name}_part_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "_state"
                ):
                    if isinstance(node.ctx, ast.Store):
                        assigned.add(node.attr)
                    else:
                        referenced.add(node.attr)
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "setattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "_state"
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    assigned.add(node.args[1].value)
        for name in sorted(referenced - assigned):
            failures.append(f"{factory_name} reads uninitialized _state.{name}")

    assert not failures, "\n".join(failures)


def test_prompt_section_factories_export_every_member_consumed_by_prompt_setup() -> None:
    prompt_tree = ast.parse(
        (OWNER_ROOT / "static_replacement_dialog_prompt_setup.py").read_text(encoding="utf-8")
    )
    section_owners = {
        "alignment_setup_options_transform_section": "setup_options_transform",
        "alignment_mesh_geometry_preview_section": "mesh_geometry_preview",
        "alignment_texture_material_section": "texture_material",
        "alignment_source_parts_outliner_section": "source_parts_outliner",
    }
    for section_name, owner_name in section_owners.items():
        consumed = {
            node.attr for node in ast.walk(prompt_tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == section_name
        }
        exported: set[str] = set()
        for path in OWNER_ROOT.glob(f"static_replacement_dialog_sections_{owner_name}_part_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "update" and node.args \
                        and isinstance(node.args[0], ast.Dict):
                    exported.update(
                        key.value for key in node.args[0].keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    )
        assert consumed <= exported, f"{section_name}: {sorted(consumed - exported)}"


def test_modeless_dialog_close_stops_texture_worker_before_d3d_preview() -> None:
    calls: list[str] = []
    dialog = SimpleNamespace(deleteLater=lambda: calls.append("delete_dialog"))
    owner = SimpleNamespace(
        _unregister_modeless_alignment_dialog=lambda *_args: calls.append("unregister")
    )
    callbacks = remaining_callbacks.create_alignment_modeless_dialog_callbacks(
        {
            "QDialog": SimpleNamespace(Accepted=1),
            "QTimer": SimpleNamespace(singleShot=lambda *_args: None),
            "_alignment_builder_closed_empty_state_message_helper": lambda: "closed",
            "_alignment_cancel_handler_failed_status_helper": str,
            "_alignment_dialog_accepted_helper": lambda _state: False,
            "_alignment_dialog_finished_route_helper": lambda **_kwargs: SimpleNamespace(
                should_call_cancel_handler=False,
                should_show_embedded_empty_state=False,
            ),
            "_alignment_dialog_mark_closing_helper": lambda _state: calls.append("closing"),
            "_finish_alignment_startup_progress": lambda: calls.append("finish_progress"),
            "_safe_shutdown_alignment_d3d11_preview": lambda: calls.append("stop_d3d"),
            "_safe_stop_alignment_timer": lambda timer: calls.append(f"stop_{timer}"),
            "_stop_original_reference_texture_worker": lambda: calls.append("stop_texture"),
            "alignment_dialog_closing": {},
            "alignment_dialog_key": "builder",
            "dialog": dialog,
            "dialog_accepted_state": {},
            "embedded_alignment_builder": False,
            "material_edit_refresh_timer": "material_timer",
            "on_cancel": None,
            "self": owner,
            "source_material_plan_refresh_timer": "source_timer",
        }
    )

    callbacks._modeless_alignment_dialog_finished(0)

    assert calls.index("stop_texture") < calls.index("stop_d3d")
    assert calls[-2:] == ["unregister", "delete_dialog"]


def test_callback_facade_preserves_public_factory_names() -> None:
    expected = {
        "create_alignment_selected_part_control_callbacks",
        "create_alignment_source_part_assignment_callbacks",
        "create_alignment_source_tree_selection_callbacks",
        "create_alignment_accept_build_callbacks",
        "create_alignment_transform_drag_callbacks",
        "create_alignment_parts_outliner_mapping_callbacks",
        "create_alignment_d3d11_loading_callbacks",
        "create_alignment_refresh_queue_callbacks",
        "create_alignment_d3d11_package_lifecycle_callbacks",
        "create_alignment_preview_mode_callbacks",
        "create_alignment_preview_model_callbacks",
    }
    assert expected <= set(vars(callbacks))


def test_preview_model_factory_exports_original_frame_and_cache_helpers() -> None:
    state = MagicMock()
    state._factory_result_values = {}
    original_frame = MagicMock()
    geometry_key = MagicMock()
    mapped_indices = MagicMock()
    unmapped_indices = MagicMock()
    state._preview_model_in_original_frame = original_frame
    state._source_preview_geometry_key = geometry_key
    state._mapped_source_indices = mapped_indices
    state._unmapped_appended_source_indices = unmapped_indices

    preview_model_owner._preview_model_step_038(state)

    assert state._factory_result_values["_preview_model_in_original_frame"] is original_frame
    assert state._factory_result_values["_source_preview_geometry_key"] is geometry_key
    assert state._factory_result_values["_mapped_source_indices"] is mapped_indices
    assert state._factory_result_values["_unmapped_appended_source_indices"] is unmapped_indices


def test_build_mod_copied_texture_override_callback_exists_without_advanced_sidecars() -> None:
    override_helper = MagicMock(return_value=("override",))
    state = SimpleNamespace(
        _factory_advanced_material_branch=(),
        _copied_source_texture_slot_overrides_helper=override_helper,
        _original_part_texture_intent_rows=MagicMock(),
        copied_original_texture_intents_by_source={},
        copied_original_texture_disabled_sources=set(),
        _source_display_name=MagicMock(),
        _texture_slot_contract_key=MagicMock(),
        list=list,
    )

    texture_material_owner._texture_material_step_017(state)

    occupied_keys: set[tuple[str, str]] = set()
    assert state._copied_source_texture_slot_overrides(
        ("mapping",), occupied_keys=occupied_keys
    ) == ["override"]
    override_helper.assert_called_once_with(
        ("mapping",),
        original_part_texture_intent_rows=state._original_part_texture_intent_rows,
        copied_original_texture_intents_by_source={},
        copied_original_texture_disabled_sources=set(),
        source_display_name=state._source_display_name,
        texture_slot_contract_key=state._texture_slot_contract_key,
        occupied_keys=occupied_keys,
    )


def test_preview_target_mesh_indices_accepts_existing_positional_callback_contract() -> None:
    state = MagicMock()
    state.preview_submesh_index_map = {2: 4}
    state._preview_target_mesh_indices_helper.return_value = (7, 8)
    preview_model_owner._preview_model_step_016(state)

    assert state._preview_target_mesh_indices(object(), "blade", (1, 2), True, ("mapping",)) == [7, 8]
    state._preview_target_mesh_indices_helper.assert_called_once()
    assert state._preview_target_mesh_indices_helper.call_args.kwargs == {
        "mapped_preview": True,
        "current_mappings": ("mapping",),
        "preview_submesh_index_map": {2: 4},
    }


def test_context_only_callback_factories_still_return_namespaces() -> None:
    for name in (
        "create_alignment_selected_part_control_callbacks",
        "create_alignment_source_part_assignment_callbacks",
        "create_alignment_source_tree_selection_callbacks",
        "create_alignment_accept_build_callbacks",
        "create_alignment_parts_outliner_mapping_callbacks",
        "create_alignment_preview_mode_callbacks",
    ):
        assert isinstance(getattr(callbacks, name)({}), SimpleNamespace), name


def test_moved_callback_facades_and_owners_are_bounded() -> None:
    facade_paths = {
        Path(module.__file__).resolve()
        for module, _factory_name, _owner_suffixes in MOVED_CALLBACK_FACTORIES
    }
    for path in facade_paths:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, path.name
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 150, f"{path.name}:{node.name}"


def test_moved_callback_factories_preserve_public_identity_and_contracts() -> None:
    prompt_dependencies = importlib.import_module(
        "cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps_callbacks"
    )
    expected_factory_signature = "(context: 'dict[str, object]') -> 'SimpleNamespace'"

    for module, factory_name, owner_suffixes in MOVED_CALLBACK_FACTORIES:
        factory = getattr(module, factory_name)
        assert getattr(prompt_dependencies, factory_name) is factory
        assert str(inspect.signature(factory)) == expected_factory_signature

        owner_trees = _callback_owner_trees(owner_suffixes)
        expected_names = _owner_result_names(owner_trees)
        assert expected_names, factory_name
        callback_nodes = {
            node.name: node
            for tree in owner_trees
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in expected_names
        }
        assert set(callback_nodes) == set(expected_names)
        for tree in owner_trees:
            for handler in (
                node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
            ):
                if handler.name is not None:
                    assert handler.name not in _state_attribute_names(handler.body)

        result = factory(_FactoryProbeContext())
        assert isinstance(result, SimpleNamespace)
        assert tuple(vars(result)) == expected_names
        for callback_name in expected_names:
            callback = getattr(result, callback_name)
            assert callback.__name__ == callback_name
            assert _runtime_signature_shape(callback) == _ast_signature_shape(
                callback_nodes[callback_name]
            )


def test_moved_preview_refresh_reports_the_caught_exception() -> None:
    record_runtime_event = MagicMock()
    set_loading = MagicMock()

    class _FailingClock:
        @staticmethod
        def perf_counter() -> float:
            raise RuntimeError("preview clock failed")

    context = _FactoryProbeContext(
        {
            "_get_replacement_preview_model": lambda: object(),
            "_record_runtime_event": record_runtime_event,
            "_set_alignment_d3d11_loading": set_loading,
            "_mesh_edit_tab_active": lambda: False,
            "time": _FailingClock,
        }
    )
    callbacks_namespace = (
        remaining_callbacks.create_alignment_static_preview_refresh_callbacks(context)
    )

    callbacks_namespace._safe_refresh_static_dialog_preview()

    assert record_runtime_event.call_args.kwargs["message"] == "preview clock failed"
    set_loading.assert_called_once_with(False, "Preview failed: preview clock failed")
