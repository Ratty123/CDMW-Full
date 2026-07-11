"""Texture/material callback factories for static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_donor_material_loader import (
    DonorMaterialSourceLoadResult,
    load_donor_material_source,
)

from cdmw.ui.archive_browser.static_replacement_dialog_factory_runtime import (
    run_static_replacement_factory,
)
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_texture_added_part_texture_part_01 as _texture_added_part_texture_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_texture_original_texture_material_part_01 as _texture_original_texture_material_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_texture_material_plan_final_preview_part_01 as _texture_material_plan_final_preview_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_texture_texture_table_part_01 as _texture_texture_table_part_01


def create_alignment_added_part_texture_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_texture_added_part_texture_part_01.STEPS,),
    )


def create_alignment_original_texture_material_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_texture_original_texture_material_part_01.STEPS,),
    )


def create_alignment_material_plan_column_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QTimer = context.get('QTimer')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _material_plan_column_fit_specs_helper = context.get('_material_plan_column_fit_specs_helper')
    _material_plan_column_refit_requests_helper = context.get('_material_plan_column_refit_requests_helper')
    callbacks = context.get('callbacks')
    column_specs = context.get('column_specs')
    delay_ms = context.get('delay_ms')
    material_plan_tree = context.get('material_plan_tree')
    material_routing_tree = context.get('material_routing_tree')
    tree_key = context.get('tree_key')

    def _fit_material_routing_tree_columns() -> None:
        column_specs = _material_plan_column_fit_specs_helper()["routing"]
        try:
            _auto_fit_alignment_tree_columns(
                material_routing_tree,
                column_specs["minimum_widths"],
                column_specs["maximum_widths"],
                expand_columns=column_specs["expand_columns"],
            )
        except RuntimeError:
            return

    def _fit_material_plan_tree_columns() -> None:
        column_specs = _material_plan_column_fit_specs_helper()["plan"]
        try:
            _auto_fit_alignment_tree_columns(
                material_plan_tree,
                column_specs["minimum_widths"],
                column_specs["maximum_widths"],
                expand_columns=column_specs["expand_columns"],
            )
        except RuntimeError:
            return

    def _schedule_material_plan_column_refit() -> None:
        callbacks = {
            "routing": _fit_material_routing_tree_columns,
            "plan": _fit_material_plan_tree_columns,
        }
        for delay_ms, tree_key in _material_plan_column_refit_requests_helper():
            QTimer.singleShot(int(delay_ms), callbacks[str(tree_key)])

    return SimpleNamespace(
        _fit_material_routing_tree_columns=_fit_material_routing_tree_columns,
        _fit_material_plan_tree_columns=_fit_material_plan_tree_columns,
        _schedule_material_plan_column_refit=_schedule_material_plan_column_refit,
    )


def create_alignment_material_plan_final_preview_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_texture_material_plan_final_preview_part_01.STEPS,),
    )


def create_alignment_texture_table_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_texture_texture_table_part_01.STEPS,),
    )
