from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from cdmw.ui.archive_browser import static_replacement_dialog_callback_factories as callbacks
from cdmw.ui.archive_browser import static_replacement_dialog_remaining_callbacks as remaining_callbacks
from cdmw.ui.archive_browser import static_replacement_dialog_routing_callbacks as routing_callbacks
from cdmw.ui.archive_browser import static_replacement_dialog_source_part_mutation_callbacks as source_part_mutation_callbacks
from cdmw.ui.archive_browser import static_replacement_dialog_texture_callbacks as texture_callbacks


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
        assert len(source.splitlines()) <= 800, path.name
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 150, f"{path.name}:{node.name}"


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
        assert len(source.splitlines()) <= 800, path.name
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
