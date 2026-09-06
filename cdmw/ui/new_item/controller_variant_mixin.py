"""Per-binding draft state and source ownership for the resident model workspace."""
from dataclasses import dataclass, replace

from cdmw.domain.new_item.authoring import VariantAppearance
from cdmw.domain.new_item.spec import ModelSource, MaterialRoute
from cdmw.ui.new_item.model_import import ModelPlacement


@dataclass
class VariantModelState:
    appearance: VariantAppearance
    source: object = None
    result: object = None
    entry: object = None
    scene: object = None
    placement: ModelPlacement = ModelPlacement()
    glow_parts: tuple = ()
    glow_color: tuple = (1.0,1.0,1.0)
    glow_intensity: float = 4.0
    camera: object = None


class NewItemVariantControllerMixin:
    def variant_choices(self):
        if self.snapshot is None or self.draft.template_key is None:
            return ()
        from cdmw.services.new_item_variants import variant_bindings
        family = self.snapshot.family(self.draft.template_key)
        result = []
        for part,path in variant_bindings(family):
            identity = part.prefab_path.casefold(),path.casefold()
            state = self._variant_states.get(identity)
            appearance = "custom model" if state and state.appearance.custom_model else "template"
            if state and state.appearance.dyes is not None:
                appearance += " · custom dyes"
            result.append((identity,f"{part.stem} · {path.rsplit('/',1)[-1]} · {appearance}"))
        return tuple(result)

    def primary_variant_identity(self):
        choices = self.variant_choices()
        if not choices:
            return None
        family = self.snapshot.family(self.draft.template_key)
        primary = next((identity for identity,_ in choices if identity[1].rsplit('/',1)[-1] == family.model_stem.casefold()+".pac"),None)
        return primary or choices[0][0]

    def current_variant_identity(self):
        return self._active_variant or self.primary_variant_identity()

    def _capture_variant(self, identity):
        if identity is None:
            return
        prior = self._variant_states.get(identity)
        appearance = prior.appearance if prior else VariantAppearance(*identity)
        appearance = replace(appearance,custom_model=self.draft.model_source is ModelSource.IMPORTED and (self.model_import is not None or self.model_result is not None),
                             material_route=self.draft.material_route.value,keep_template_physics=self.draft.keep_template_physics,
                             glow_parts=tuple(self.draft.glow_parts),glow_color=tuple(self.draft.glow_color),
                             glow_intensity=self.draft.glow_intensity)
        self._variant_states[identity] = VariantModelState(appearance,self.model_import,self.model_result,self.model_entry,
            self.model_scene,self.model_placement,tuple(self.draft.glow_parts),tuple(self.draft.glow_color),self.draft.glow_intensity,
            prior.camera if prior else None)

    def _sync_variant_state(self):
        if self._active_variant is None:
            return
        self._capture_variant(self._active_variant)
        self.draft.variants = tuple(state.appearance for state in self._variant_states.values()
                                    if state.appearance.custom_model or state.appearance.dyes is not None)
        if not self.draft.variants and self.draft.effect_stem:
            self.draft.variants = (self._variant_states[self._active_variant].appearance,)

    def select_variant(self, identity):
        if identity not in {key for key,_ in self.variant_choices()}:
            raise ValueError("Select an exact variant binding from this template.")
        if identity == self._active_variant:
            return
        old = self.current_variant_identity()
        if self._lane in {"model_import","model_apply","model_part_edit","authoring-index","plan"}:
            self.cancel_operation(self._lane)
        self._capture_variant(old)
        self.variant_about_to_change.emit(old)
        self._active_variant = identity
        state = self._variant_states.setdefault(identity,VariantModelState(VariantAppearance(*identity)))
        self.model_import,self.model_result,self.model_entry,self.model_scene = state.source,state.result,state.entry,state.scene
        self.model_placement = state.placement
        self.draft.model_source = ModelSource.IMPORTED if state.appearance.custom_model else ModelSource.TEMPLATE
        self.draft.material_route = MaterialRoute(state.appearance.material_route)
        self.draft.keep_template_physics = state.appearance.keep_template_physics
        self.draft.glow_parts,self.draft.glow_color,self.draft.glow_intensity = state.glow_parts,state.glow_color,state.glow_intensity
        self._held_character,self._material_parts = (),()
        self.invalidate_plan()
        self.variant_changed.emit(identity)
        self.model_import_changed.emit(self.model_import)
        self.model_changed.emit(self.model_result)
        self.model_placement_changed.emit(self.model_placement)

    def set_variant_dyes(self, assignments):
        if self._active_variant is None:
            identity = self.primary_variant_identity()
            if identity is None:
                raise ValueError("This template has no model variant to dye.")
            self.select_variant(identity)
        state = self._variant_states[self._active_variant]
        state.appearance = replace(state.appearance,dyes=assignments)
        self.invalidate_plan()
        self.variant_changed.emit(self._active_variant)

    def variant_plan_inputs(self):
        self._sync_variant_state()
        if self._active_variant is None:
            return {},{},tuple(source for source in (self.model_import,) if source is not None)
        states = tuple(self._variant_states.items())
        return ({key:value.result for key,value in states if value.appearance.custom_model},
                {key:value.scene for key,value in states if value.appearance.custom_model},
                tuple(value.source for _key,value in states if value.source is not None))

    def reset_variants(self):
        sources = {id(value.source):value.source for value in self._variant_states.values() if value.source is not None}
        self._variant_states.clear()
        self._active_variant = None
        for source in sources.values():
            if source is not self.model_import:
                self._cleanup_model_source(source)

    def retire_variant_sources(self):
        self._capture_variant(self._active_variant)
        sources = {id(value.source):value.source for value in self._variant_states.values() if value.source is not None}
        self._variant_states.clear()
        for source in sources.values():
            if source is not self.model_import:
                self._cleanup_model_source(source)
