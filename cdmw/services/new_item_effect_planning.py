"""Owned effect dependencies and component layers for New Item plans."""
from __future__ import annotations
from dataclasses import asdict, replace
from typing import Dict, List, Tuple, Optional
from cdmw.core.effect_binary import EffectBinaryError, decode_effect_binary
from cdmw.core.effect_edit import EffectEditReport, apply_effect_look, emitter_layout_of, emitter_paths_of, preset_names_of, preset_path, rename_effect_strings, rename_string_values, same_length_stem
from cdmw.core.prefab_binary_edit import PrefabEditError
from cdmw.core.prefab_component_graft import encode_transform, graft_prefab_component
from cdmw.services.new_item_snapshot import EFFECT_DIR, EFFECT_DONOR_PATH, EFFECT_DONOR_PREFAB
from cdmw.services.new_item_effect_targets import inspect_effect_targets

def _effect_file(stem):
    return f"{EFFECT_DIR}{stem}.pae"

def _emitter_file(stem):
    return f"effect/binary__/emitter/{stem}.paem"

class EffectPlanningMixin:
    def _effect_donor(self) -> Optional[bytes]:
        from cdmw.services.new_item_planning import NewItemPlanError
        self.effect_outputs.clear()
        layers = self.spec.active_effect_layers
        if not layers:
            self.manifest["effect"] = None
            self.manifest["effects"] = []
            return None
        records = []
        for index, layer in enumerate(layers):
            spec = replace(self.spec, effect=layer.reference, effect_scale=layer.scale, effect_offset=layer.offset, effect_rotation_degrees=layer.rotation, effect_look=layer.look, effect_layers=None)
            compatibility = inspect_effect_targets(self.snapshot, spec)
            if not compatibility.supported:
                raise NewItemPlanError("; ".join(compatibility.errors))
            record = {"path": layer.reference, "name": layer.name, "donor": EFFECT_DONOR_PREFAB, "prefabs": []}
            reference = self._clone_effect_for_look(layer, index, record)
            self.effect_outputs.append((layer, reference, record))
            records.append(record)
        self.effect_reference = self.effect_outputs[0][1]
        self.manifest["effect"] = records[0]
        self.manifest["effects"] = records
        self.warnings.append("Visual effect layers are grafted into owned prefabs; verify their combined placement and appearance in game.")
        return self.snapshot.payload(EFFECT_DONOR_PREFAB)

    def _clone_effect_for_look(self, layer, index: int, record) -> str:
        """With a look that is not as shipped: the effect and its emitters cloned under
        stems of the item's own (same length, no relocation), edited in place, added; the
        graft then names the clone."""

        from cdmw.services.new_item_planning import NewItemPlanError
        from cdmw.services.effect_recipe import compile_effect_recipe
        look = layer.look
        if look.is_default:
            record["look"] = None
            return layer.reference
        stem, suffix = str(layer.reference).split(".", 1)
        effect_path = _effect_file(stem)
        if not self.snapshot.has_entry(effect_path):
            raise NewItemPlanError(f"the archives have no {effect_path}, so its look cannot be edited")
        tag = f"_n{(int(self.spec.item_key or 0) + index) % 100000:05d}"
        taken = set(self.snapshot.effect_stems)
        new_stem = same_length_stem(stem, tag, taken=taken)
        taken.add(new_stem)
        try:
            source = compile_effect_recipe(self.snapshot, self.snapshot.payload(effect_path), look, cancelled=lambda: bool(self.stop_event and self.stop_event.is_set()))
        except (EffectBinaryError, ValueError) as exc:
            raise NewItemPlanError(f'{effect_path}: the emitter recipe could not be compiled: {exc}') from exc
        document = decode_effect_binary(source)
        if not document.walk_complete:
            raise NewItemPlanError(f"{effect_path} did not decode fully ({document.walk_note}); its look cannot be edited")
        renames: Dict[str, str] = {stem: new_stem}
        emitter_clones: List[Tuple[str, str, str]] = []
        for emitter_path in emitter_paths_of(document):
            if not self.snapshot.has_entry(emitter_path):
                self.warnings.append(f"The effect names {emitter_path}, which the archives do not have; the clone keeps naming the shipped emitter.")
                continue
            old_emitter = emitter_path.rsplit("/", 1)[-1][: -len(".paem")]
            new_emitter = same_length_stem(old_emitter, tag, taken=taken)
            taken.add(new_emitter)
            renames[old_emitter] = new_emitter
            emitter_clones.append((emitter_path, old_emitter, new_emitter))
        # the render and simulation presets the effect and its emitters name: cloned too,
        # since an emitter's colour is the render preset's unless it overrides it
        emitter_sources = {path: self.snapshot.payload(path) for path, _old, _new in emitter_clones}
        preset_renames: Dict[str, str] = {}
        preset_clones: List[Tuple[str, str, str]] = []
        seen_presets: List[Tuple[str, str]] = []
        for kind, name in preset_names_of(document) + tuple(
            item for data in emitter_sources.values() for item in preset_names_of(decode_effect_binary(data))
        ):
            if (kind, name) in seen_presets:
                continue
            seen_presets.append((kind, name))
            path = preset_path(kind, name)
            if not self.snapshot.has_entry(path):
                continue
            new_name = same_length_stem(name, tag, taken=taken)
            taken.add(new_name)
            preset_renames[name] = new_name
            preset_clones.append((path, kind, new_name))
        report = EffectEditReport()

        def cloned(data: bytes) -> bytes:
            renamed = rename_effect_strings(data, renames)
            if preset_renames:
                renamed = rename_string_values(renamed, preset_renames)
            return renamed

        # the effect overrides its emitters' curves and material parameters by position:
        # the emitters' layouts (under the clones' paths, which the renamed effect names)
        # let a colour reach those overrides too
        layouts = {
            _emitter_file(new_emitter): emitter_layout_of(decode_effect_binary(emitter_sources[emitter_path]))
            for emitter_path, _old, new_emitter in emitter_clones
        }
        edited_effect, report = apply_effect_look(cloned(source), look, report=report, emitter_layouts=layouts)
        new_effect_path = _effect_file(new_stem)
        self.add(self.snapshot.entry(effect_path), new_effect_path, edited_effect, f"effect clone: {new_effect_path}")
        written = [new_effect_path]
        for emitter_path, _old, new_emitter in emitter_clones:
            edited, report = apply_effect_look(cloned(emitter_sources[emitter_path]), look, report=report)
            new_path = _emitter_file(new_emitter)
            self.add(self.snapshot.entry(emitter_path), new_path, edited, f"emitter clone: {new_path}")
            written.append(new_path)
        for path, kind, new_name in preset_clones:
            edited, report = apply_effect_look(rename_string_values(self.snapshot.payload(path), preset_renames), look, report=report)
            new_path = preset_path(kind, new_name)
            self.add(self.snapshot.entry(path), new_path, edited, f"preset clone: {new_path}")
            written.append(new_path)
        reference = f"{new_stem}.{suffix}"
        record["path"] = reference
        record["look"] = {
            "source": str(layer.reference), "color": list(look.color) if look.color else None,
            "intensity": look.intensity, "size": look.size, "rate": look.rate, "lifetime": look.lifetime,
            "files": written, "edited": dict(report.edited),
            "emitters": [asdict(edit) for edit in look.emitters],
            "emitter_order": look.emitter_order,
        }
        touched = ", ".join(f"{name} x{count}" for name, count in sorted(report.edited.items())) or ("emitter recipe" if look.emitters or look.emitter_order is not None else "nothing the files carry")
        self.summary.append(f"effect look: {stem} cloned as {new_stem} with {len(emitter_clones)} emitter(s) and {len(preset_clones)} preset(s); edited {touched}")
        if not report.total and not look.emitters and look.emitter_order is None:
            self.warnings.append("The chosen look edits nothing this effect carries (no colour, brightness, scale, spawn count or lifetime member); the clone draws as shipped.")

        return reference

    def _graft_effect(self, prefab: bytes, donor: bytes, new_path: str) -> bytes:
        from cdmw.services.new_item_planning import NewItemPlanError
        from cdmw.services.effect_placement_rotation import euler_xyz_quaternion
        for layer, reference, record in self.effect_outputs:
            try:
                result = graft_prefab_component(
                    prefab, donor, component_type="EffectComponent",
                    path_replacements={EFFECT_DONOR_PATH: reference},
                    offset_transform=encode_transform(scale=(layer.scale,) * 3, rotation=euler_xyz_quaternion(layer.rotation), position=layer.offset),
                )
            except PrefabEditError as exc:
                raise NewItemPlanError(f"{new_path}: effect layer {layer.name or layer.stem} could not be grafted: {exc}") from exc
            record["prefabs"].append(new_path)
            record.update(scale=layer.scale, offset=list(layer.offset), rotation_degrees=list(layer.rotation))
            offset = ' '.join(f'{v:g}' for v in layer.offset)
            rotation = ' '.join(f'{v:g}' for v in layer.rotation)
            self.summary.append(f"effect: {reference} grafted into {new_path.rsplit('/', 1)[-1]} (scale {layer.scale:g}, offset {offset}, rotation {rotation} deg)")
            prefab = result.data
        return prefab
