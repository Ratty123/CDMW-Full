"""Continue an item package from Drafts & Mods, and list each package Create New Item writes."""
from dataclasses import replace
from pathlib import Path

from cdmw.domain.new_item.spec import MaterialRoute, ModelSource
from cdmw.services.new_item_planning import baked_model_files
from cdmw.ui.new_item.controller_variant_mixin import VariantModelState
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.ui.new_item.state import NewItemDraft, glow_choice, grid_values_from_edits


def _binding(identity):
    return tuple(str(part).casefold() for part in identity)


class NewItemContinueControllerMixin:
    #: Drafts & Mods' folder; None leaves written packages unlisted (standalone and tests)
    saved_work_root = None
    #: The package being continued: Update writes back to it, keeping its identity
    continued_package_path = None
    #: Its finished icon, used while the draft asks for a custom icon with no image to hand
    continued_icon_data = None

    def saved_draft_bytes(self):
        """The current draft as a file for Drafts & Mods, or None with the reason logged."""

        from cdmw.ui.new_item.draft_file import DraftFileError, encode_draft
        try:
            return encode_draft(self.draft)
        except DraftFileError as exc:
            self.log_message.emit(f"Drafts & Mods will list this package without its settings: {exc}")
            return None

    def restore_continued_item(self, launch) -> None:
        """Make `launch`'s draft the current one, with the package's finished models.

        The template is already committed (its key is the draft's). Every variant the
        draft names gets its saved state back; one with its own model gets the model
        the package was written with, so the plan builds again without re-importing.
        """

        draft = launch.draft
        if not isinstance(draft, NewItemDraft) or draft.template_key != self.draft.template_key:
            raise ValueError("Choose the item's template before continuing it.")
        draft = replace(draft, grid_values=dict(draft.grid_values), price_values=dict(draft.price_values),
                        display_names=dict(draft.display_names), descriptions=dict(draft.descriptions),
                        authoring_errors={}, independent_identity=str(launch.identity or ""))
        if launch.stat_edits or launch.buy_price_edits:
            # A draft rebuilt from a package: lay its edits onto this template's ladder,
            # with a column for each stat the ladder lacks.
            self.draft = replace(self.draft, extra_stat_keys=[], price_values=dict(draft.price_values))
            _values, _levels, missing = grid_values_from_edits(
                self.stat_grid(), launch.stat_edits, launch.buy_price_edits)
            self.draft.extra_stat_keys = list(missing)
            values, extra_levels, _missing = grid_values_from_edits(
                self.stat_grid(), launch.stat_edits, launch.buy_price_edits)
            draft = replace(draft, grid_values=values, extra_levels=extra_levels, extra_stat_keys=list(missing))
        self.reset_variants()
        models = {_binding(key): value for key, value in dict(launch.variant_models or {}).items()}
        excluded = {_binding(identity) for identity in draft.excluded_bindings or ()}
        from cdmw.services.new_item_skinning import is_hidden_variant_result
        for appearance in draft.variants or ():
            identity = _binding((appearance.prefab_path, appearance.model_path))
            result = models.get(identity) if appearance.custom_model else None
            if identity in excluded and (result is None or is_hidden_variant_result(result)):
                # A left-out component is written as hidden geometry, so the package holds
                # no source for it: ticking it again brings back the template model.
                appearance, result = replace(appearance, custom_model=False), None
            if result is not None:
                result = baked_model_files(result, appearance.translucency, appearance.surface_settings,
                                           appearance.shader_controls, glow=appearance.glow_choice(),
                                           material_route=appearance.material_route)
            self._variant_states[identity] = VariantModelState(
                appearance, None, result, None, None, ModelPlacement(), tuple(appearance.glow_parts),
                tuple(appearance.glow_color), appearance.glow_intensity, None, appearance.dyes != ())
        self.clear_installed_reference()
        self.draft = draft
        self.model_import, self.model_entry, self.model_scene = None, None, None
        self.model_placement = ModelPlacement()
        self.model_result = None
        if launch.model is not None and draft.model_source is ModelSource.IMPORTED:
            self.model_result = baked_model_files(launch.model, draft.translucency, draft.surface_settings,
                                                  draft.shader_controls, glow=glow_choice(draft),
                                                  material_route=draft.material_route)
        if self._variant_states:
            primary = self.primary_variant_identity()
            active = primary if primary in self._variant_states else next(iter(self._variant_states))
            self._active_variant = active
            # As select_variant does: the step shows the active binding's own appearance.
            state = self._variant_states[active]
            appearance = state.appearance
            self.model_result = state.result
            self.draft.model_source = ModelSource.IMPORTED if appearance.custom_model else ModelSource.TEMPLATE
            self.draft.material_route = MaterialRoute(appearance.material_route)
            self.draft.keep_template_physics = appearance.keep_template_physics
            self.draft.glow_parts, self.draft.glow_color = tuple(appearance.glow_parts), tuple(appearance.glow_color)
            self.draft.glow_intensity, self.draft.glow_animation = appearance.glow_intensity, appearance.glow_animation
            self.draft.glow_rgb, self.draft.translucency = appearance.glow_rgb, appearance.translucency
            self.draft.surface_settings, self.draft.shader_controls = appearance.surface_settings, appearance.shader_controls
            self.draft.body_visibility, self.draft.template_transform = appearance.body_visibility, appearance.template_transform
        self.continued_package_path = Path(launch.package_path) if launch.package_path else None
        self.continued_icon_data = launch.icon_data
        self.invalidate_plan()
        self.template_changed.emit(self.draft.template_key)
        if self._active_variant is not None:
            self.variant_changed.emit(self._active_variant)
        self.model_import_changed.emit(None)
        self.model_changed.emit(self.model_result)
        self.model_placement_changed.emit(self.model_placement)
        self.effect_changed.emit(self.draft)

    def forget_continued_package(self) -> None:
        self.continued_package_path = None
        self.continued_icon_data = None


def register_written_package(root, result, draft_bytes, template_name, log) -> None:
    """List a written package in Drafts & Mods; a failure is logged, never raised.

    Runs on the export worker, after the package itself is published.
    """

    if root is None:
        return
    from cdmw.services.item_package_saved_work import register_item_package
    try:
        register_item_package(root, package_path=result.path, identity=result.identity,
                              title=Path(str(result.path)).stem, draft_bytes=draft_bytes,
                              template_name=template_name)
    except Exception as exc:  # noqa: BLE001 - the package is written; the list is a convenience
        log(f"The package is written, but Drafts & Mods could not list it: {type(exc).__name__}: {exc}")


__all__ = ["NewItemContinueControllerMixin", "register_written_package"]
