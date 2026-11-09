"""Per-binding draft state and source ownership for the resident model workspace."""
from dataclasses import dataclass, replace

from cdmw.domain.new_item.authoring import VariantAppearance
from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice
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
    dyes_edited: bool = False


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
            if state and state.appearance.dyes != ():
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
        dyes_edited = prior.dyes_edited if prior else False
        if prior and (prior.source is not self.model_import
                      or (self.model_import is None and prior.result is not self.model_result)):
            # Dye consent belongs to this import. Replacing it starts disabled,
            # even when the new file has the same path or material names.
            appearance = replace(appearance,dyes=())
            dyes_edited = False
        appearance = replace(appearance,custom_model=self.draft.model_source is ModelSource.IMPORTED and (self.model_import is not None or self.model_result is not None),
                             material_route=self.draft.material_route.value,keep_template_physics=self.draft.keep_template_physics,
                             glow_parts=tuple(self.draft.glow_parts),glow_color=tuple(self.draft.glow_color),
                             glow_intensity=self.draft.glow_intensity,glow_animation=self.draft.glow_animation,glow_rgb=self.draft.glow_rgb,translucency=self.draft.translucency,shader_controls=self.draft.shader_controls,
                             template_transform=self.draft.template_transform, body_visibility=self.draft.body_visibility,
                             surface_settings=self.draft.surface_settings)
        self._variant_states[identity] = VariantModelState(appearance,self.model_import,self.model_result,self.model_entry,
            self.model_scene,self.model_placement,tuple(self.draft.glow_parts),tuple(self.draft.glow_color),self.draft.glow_intensity,
            prior.camera if prior else None, dyes_edited)

    def _sync_variant_state(self):
        if (self._active_variant is None and self.snapshot is not None and self.snapshot.sources
                and self.snapshot.sources.static_layout and self.draft.model_source is ModelSource.TEMPLATE
                and (self.draft.glow_parts or self.draft.translucency is not None or self.draft.shader_controls
                     or self.draft.template_transform or self.draft.body_visibility.wanted
                     or self.draft.excluded_bindings)):
            # The selector already displays the primary binding before its first edit.
            # Ticking a component out never selects a row, so it counts as one too:
            # without an active binding the plan would export what the list shows left out.
            self._active_variant = self.primary_variant_identity()
        if self._active_variant is None:
            return
        self._capture_variant(self._active_variant)
        for identity in self.draft.excluded_bindings:
            self._variant_states.setdefault(identity, VariantModelState(VariantAppearance(*identity)))
        variants = []
        for identity, state in self._variant_states.items():
            appearance = state.appearance
            if identity in self.draft.excluded_bindings:
                # Left out of the export: hidden geometry replaces whatever source the
                # component keeps for re-including; only its body choice applies.
                variants.append(replace(VariantAppearance(*identity), custom_model=True,
                                        material_route=appearance.material_route,
                                        body_visibility=appearance.body_visibility))
            elif (appearance.custom_model or state.dyes_edited or appearance.dyes != ()
                    or appearance.glow_parts or appearance.translucency is not None or appearance.shader_controls
                    or appearance.template_transform or appearance.body_visibility.wanted):
                variants.append(appearance)
        self.draft.variants = tuple(variants)
        if not self.draft.variants and self.draft.effect_stem:
            self.draft.variants = (self._variant_states[self._active_variant].appearance,)

    def select_variant(self, identity):
        if identity not in {key for key,_ in self.variant_choices()}:
            raise ValueError("Select an exact variant binding from this template.")
        if identity == self._active_variant:
            return
        old = self.current_variant_identity()
        if self._lane in {"model_apply","model_part_edit","model_skinning","model_hide","authoring-index","plan","transparency_mask"}:
            self.cancel_operation(self._lane)
        self._capture_variant(old)
        self.variant_about_to_change.emit(old)
        self._active_variant = identity
        state = self._variant_states.setdefault(identity,VariantModelState(VariantAppearance(*identity)))
        self._load_variant_state(state)
        self.invalidate_plan()
        self.variant_changed.emit(identity)
        self.model_import_changed.emit(self.model_import)
        self.model_changed.emit(self.model_result)
        self.model_placement_changed.emit(self.model_placement)
        source = self.model_import
        if source is not None and source.skeleton_edit is not None and source.skeleton_edit not in self.skeleton_edits:
            # This variant was weighted while its skeleton had other added bones.
            if not self._reweight_for_skeleton_edits():
                self._warn_stale_skeleton_edit()

    def _load_variant_state(self, state):
        """Make one binding's stored state the editable draft (no signals)."""
        self.model_import,self.model_result,self.model_entry,self.model_scene = state.source,state.result,state.entry,state.scene
        self.model_placement = state.placement
        self.draft.model_source = ModelSource.IMPORTED if state.appearance.custom_model else ModelSource.TEMPLATE
        self.draft.material_route = MaterialRoute(state.appearance.material_route)
        self.draft.keep_template_physics = state.appearance.keep_template_physics
        self.draft.glow_parts,self.draft.glow_color,self.draft.glow_intensity = state.glow_parts,state.glow_color,state.glow_intensity
        self.draft.glow_animation = state.appearance.glow_animation
        self.draft.glow_rgb = state.appearance.glow_rgb
        self.draft.translucency = state.appearance.translucency
        self.draft.surface_settings = state.appearance.surface_settings
        self.draft.shader_controls = state.appearance.shader_controls
        self.draft.body_visibility = state.appearance.body_visibility
        self.draft.template_transform = state.appearance.template_transform
        self._held_character,self._material_parts = (),()

    # ------------------------------------------------------------------ components

    def _component_facts_for(self, template_key):
        """Model path -> (prefab component name, shrink tag), and part stem -> ItemInfo
        prefab data type, read once per template from the template's own files."""
        key = int(template_key)
        cached = self._component_facts.get((id(self.snapshot), key))
        if cached is not None:
            return cached
        from cdmw.core.prefab_binary import decode_prefab_binary
        facts, roles = {}, {}
        family = self.snapshot.family(key)
        for part in family.parts:
            if not part.prefab_path or not self.snapshot.has_entry(part.prefab_path):
                continue
            try:
                document = decode_prefab_binary(self.snapshot.payload(part.prefab_path))
            except Exception:  # noqa: BLE001 - an unreadable prefab keeps the file names
                continue
            for obj in document.objects:
                values = {name: value.text for name, value in obj.values}
                path = str(values.get("_skinnedMeshFile") or values.get("_skinnedMeshFileName") or "")
                if path:
                    facts.setdefault((part.prefab_path.casefold(), path.replace("\\", "/").casefold()),
                                     (str(obj.name or ""), str(values.get("_shrinkTag") or "")))
        try:
            from cdmw.core.iteminfo_behavior import read_behavior_fields
            for entry in read_behavior_fields(self.snapshot.row(key).raw).get("prefabs") or ():
                for string_key in entry.get("prefabs", ()) or ():
                    stem = str(self.snapshot.stringinfo_texts.get(string_key, "") or "")
                    if stem:
                        roles.setdefault(stem.casefold(), int(entry.get("data_type", -1)))
        except Exception:  # noqa: BLE001 - without ItemInfo types every binding is listed as other
            roles = {}
        self._component_facts[(id(self.snapshot), key)] = cached = (facts, roles)
        return cached

    def _legacy_hidden(self, identity) -> bool:
        """A binding hidden by the earlier Hide this variant / Hide in export buttons:
        its stored model is the generated placeholder rather than an inclusion flag."""
        from cdmw.services.new_item_skinning import is_hidden_variant_result
        if identity == self._active_variant:
            custom = self.draft.model_source is ModelSource.IMPORTED
            source, result = self.model_import, self.model_result
        else:
            state = self._variant_states.get(identity)
            if state is None:
                return False
            custom, source, result = state.appearance.custom_model, state.source, state.result
        return bool(custom) and source is None and is_hidden_variant_result(result)

    def component_included(self, identity) -> bool:
        return identity not in self.draft.excluded_bindings and not self._legacy_hidden(identity)

    def component_rows(self):
        """Every template binding and what the export makes of it, in family order."""
        if self.snapshot is None or self.draft.template_key is None:
            return ()
        from cdmw.domain.new_item.components import ComponentRole, ComponentRow, ComponentSource, ROLE_BY_DATA_TYPE
        from cdmw.services.new_item_variants import variant_bindings
        try:
            family = self.snapshot.family(self.draft.template_key)
            facts, roles = self._component_facts_for(self.draft.template_key)
        except Exception:  # noqa: BLE001 - a template without a family has no components
            return ()
        active = self.current_variant_identity()
        rows = []
        for part, path in variant_bindings(family):
            identity = (part.prefab_path.casefold(), path.casefold())
            if identity == active:
                custom = self.draft.model_source is ModelSource.IMPORTED and (self.model_import is not None or self.model_result is not None)
                source, body = self.model_import, self.draft.body_visibility
            else:
                state = self._variant_states.get(identity)
                custom = bool(state and state.appearance.custom_model)
                source = state.source if state else None
                body = state.appearance.body_visibility if state else BodyVisibilityChoice()
            legacy = self._legacy_hidden(identity)
            if custom and not legacy:
                kind = ComponentSource.IMPORTED
                name = str(getattr(getattr(source, "chosen_path", None), "name", "") or "")
            else:
                kind, name = ComponentSource.TEMPLATE, ""
            component, tag = facts.get(identity, ("", ""))
            role = ROLE_BY_DATA_TYPE.get(roles.get(part.stem.casefold(), -1), ComponentRole.OTHER)
            rows.append(ComponentRow(identity, part.prefab_path, path, part.stem, role, component, tag, kind, name,
                                     body.keep_skin, body.keep_hair, identity == active,
                                     included=identity not in self.draft.excluded_bindings and not legacy,
                                     cut_rules_editable=not getattr(self, "independent_mode", False)))
        return tuple(rows)

    def set_component_included(self, identity, included: bool) -> bool:
        """Include or leave out one binding by its stable identity, without selecting
        it, starting work or reloading the preview. Its source stays for re-including."""
        if identity not in {key for key, _ in self.variant_choices()}:
            raise ValueError("Choose an exact component binding of this template.")
        included = bool(included)
        if included == self.component_included(identity):
            return False
        excluded = [value for value in self.draft.excluded_bindings if value != identity]
        if not included:
            excluded.append(identity)
        elif self._legacy_hidden(identity):
            # The old buttons replaced the source with the placeholder: restore what
            # was stashed at that time, else the template model.
            self._restore_legacy_hidden(identity)
        self.draft.excluded_bindings = tuple(sorted(excluded))
        self.invalidate_plan()
        return True

    def _restore_legacy_hidden(self, identity):
        body = (self.draft.body_visibility if identity == self._active_variant
                else self._variant_states.get(identity, VariantModelState(VariantAppearance(*identity))).appearance.body_visibility)
        stash = self._hidden_restore.pop(identity, None)
        from cdmw.services.new_item_skinning import is_hidden_variant_result
        if stash is not None and not (stash.appearance.custom_model and stash.source is None
                                      and is_hidden_variant_result(stash.result)):
            state = replace(stash, appearance=replace(stash.appearance, body_visibility=body))
        else:
            state = VariantModelState(replace(VariantAppearance(*identity), body_visibility=body))
        self._variant_states[identity] = state
        if identity == self._active_variant:
            self._load_variant_state(state)
            self.model_import_changed.emit(self.model_import)
            self.model_changed.emit(self.model_result)
            self.model_placement_changed.emit(self.model_placement)

    def hide_component(self, identity=None) -> bool:
        """Leave one binding out of the export (compatibility name)."""
        identity = identity or self.current_variant_identity()
        return identity is not None and (self.set_component_included(identity, False) or not self.component_included(identity))

    def show_component(self, identity=None) -> bool:
        """Include one binding again with its previous source and edits (compatibility name)."""
        identity = identity or self.current_variant_identity()
        return identity is not None and self.set_component_included(identity, True)

    def set_worn_body_visibility(self, choice) -> int:
        """Give every worn component the same underlying-body choice; returns how many."""
        from cdmw.domain.new_item.components import ComponentRole
        if self._active_variant is None and (primary := self.primary_variant_identity()) is not None:
            self.select_variant(primary)
        rows = [row for row in self.component_rows() if row.role is ComponentRole.WORN and row.cuts_body]
        active = self.current_variant_identity()
        for row in rows:
            if row.identity == active:
                self.draft.body_visibility = choice
                continue
            state = self._variant_states.setdefault(row.identity, VariantModelState(VariantAppearance(*row.identity)))
            state.appearance = replace(state.appearance, body_visibility=choice)
        if rows:
            self.invalidate_plan()
            self.variant_changed.emit(active)
        return len(rows)

    def set_variant_dyes(self, assignments):
        if self._active_variant is None:
            identity = self.primary_variant_identity()
            if identity is None:
                raise ValueError("This template has no model variant to dye.")
            self.select_variant(identity)
        self._capture_variant(self._active_variant)
        state = self._variant_states[self._active_variant]
        state.appearance = replace(state.appearance,dyes=assignments)
        state.dyes_edited = True
        self.invalidate_plan()
        self.variant_changed.emit(self._active_variant)

    def visibility_layers(self):
        """Layers the current variant cuts, or None before a lookup for this snapshot."""
        identity = self.current_variant_identity()
        if identity is None or self.snapshot is None:
            return None
        source, layers = self._visibility_layers.get(identity, (None, None))
        return layers if source == id(self.snapshot) else None

    def start_visibility_layer_lookup(self, on_done, on_error, on_cancel=None) -> bool:
        """Read the current variant's cut layers off the UI thread."""
        identity = self.current_variant_identity()
        if identity is None or self.snapshot is None:
            return False
        from cdmw.services.new_item_variants import variant_bindings
        from cdmw.services.new_item_body_visibility import available_layers
        snapshot = self.snapshot
        family = snapshot.family(self.draft.template_key)
        binding = next(((part.prefab_path, path) for part, path in variant_bindings(family)
                        if (part.prefab_path.casefold(), path.casefold()) == identity), None)
        if binding is None:
            return False
        def done(layers):
            # Answers belong to the tables they were read from; holding an id, not
            # the snapshot, lets a replaced snapshot be freed. Planning re-checks the
            # kept names against the live rule either way.
            current = id(snapshot)
            self._visibility_layers = {key: value for key, value in self._visibility_layers.items() if value[0] == current}
            self._visibility_layers[identity] = (current, tuple(layers))
            on_done(identity)

        def cancelled():
            # _task_cancelled calls this; it must not call back into it.
            self.status_message.emit("Operation cancelled.", False)
            if on_cancel is not None:
                on_cancel()

        return self._run("visibility_layers", lambda _log, _stop: available_layers(snapshot, *binding), done, on_error,
                         on_cancel=cancelled)

    def variant_plan_inputs(self):
        self._sync_variant_state()
        if self._active_variant is None:
            return {},{},tuple(source for source in (self.model_import,) if source is not None)
        from cdmw.services.new_item_skinning import HiddenVariantRequest, is_hidden_variant_result
        states = tuple(self._variant_states.items())
        excluded = set(self.draft.excluded_bindings)
        models, scenes = {}, {}
        for key, value in states:
            if key in excluded:
                # Generated by the plan worker, so leaving a row out costs nothing here.
                models[key] = value.result if is_hidden_variant_result(value.result) else HiddenVariantRequest(key[1])
                scenes[key] = None
            elif value.appearance.custom_model:
                models[key], scenes[key] = value.result, value.scene
        return (models, scenes, tuple(value.source for key, value in states
                                      if value.source is not None and key not in excluded))

    def holds_model_source(self, source) -> bool:
        """Whether an import still belongs to this item: the active one or one a row keeps."""
        if source is None:
            return False
        return source is self.model_import or any(
            value.source is source for value in (*self._variant_states.values(), *self._hidden_restore.values()))

    def reset_variants(self):
        sources = {id(value.source):value.source for value in (*self._variant_states.values(), *self._hidden_restore.values())
                   if value.source is not None}
        self._variant_states.clear()
        self._hidden_restore.clear()
        self._active_variant = None
        for source in sources.values():
            if source is not self.model_import:
                self._cleanup_model_source(source)

    def retire_variant_sources(self):
        self._capture_variant(self._active_variant)
        sources = {id(value.source):value.source for value in (*self._variant_states.values(), *self._hidden_restore.values())
                   if value.source is not None}
        self._variant_states.clear()
        self._hidden_restore.clear()
        for source in sources.values():
            if source is not self.model_import:
                self._cleanup_model_source(source)
