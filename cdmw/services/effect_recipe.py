"""Compile emitter recipes into the same effect bytes used by preview and export."""
from __future__ import annotations

import copy
import struct
from dataclasses import replace

from cdmw.core.effect_binary import EffectBinaryError, ReflectNode, ReflectValue, decode_effect_binary
from cdmw.core.effect_edit import apply_effect_look, preset_path
from cdmw.core.effect_writer import serialize_effect, set_typed_value
from cdmw.core.prefab_component_graft import encode_prefab_type
from cdmw.domain.new_item.effect_authoring import EffectLook, validate_emitter_edits


def _merge(base: ReflectNode, override: ReflectNode) -> ReflectNode:
    """Resolve positional override collections against their own base layout."""
    out = copy.deepcopy(base)
    out.override = 0
    values = {v.name: v for v in out.values}
    values.update({v.name: copy.deepcopy(v) for v in override.values})
    out.values = list(values.values())
    children = dict(out.children)
    for key, child in override.children:
        previous = children.get(key)
        if isinstance(child, ReflectNode) and isinstance(previous, ReflectNode):
            children[key] = _merge(previous, child)
        elif isinstance(child, tuple) and isinstance(previous, tuple) and override.override:
            children[key] = tuple(_merge(previous[i], item) if i < len(previous) else copy.deepcopy(item) for i, item in enumerate(child)) + copy.deepcopy(previous[len(child):])
        elif child is not None or not override.override:
            children[key] = copy.deepcopy(child)
    out.children = list(children.items())
    return out


def _types(types, document):
    by_name = {t.type_name: t for t in types}
    for t in document.types:
        if t.type_name in by_name:
            if encode_prefab_type(t) != encode_prefab_type(by_name[t.type_name]):
                raise EffectBinaryError(f"Conflicting emitter type declaration: {t.type_name}")
        else:
            types.append(t)
            by_name[t.type_name] = t


def _curve(document, emitter, curve_id, samples, components):
    entries = emitter.child("_curveEntryDataList") or ()
    original = next((n for n in entries if n.value("_splineID") and n.value("_splineID").value == curve_id), None)
    node = copy.deepcopy(original) if original else ReflectNode("EmitterCurveData", 0)
    if not set_typed_value(document, node, "_splineID", curve_id) or not set_typed_value(document, node, "_componentCount", components):
        raise EffectBinaryError("The effect does not declare editable curve data.")
    packed = []
    for i in range(128):
        position = i / 127 * (len(samples) - 1)
        low = int(position)
        high = min(low + 1, len(samples) - 1)
        weight = position - low
        a = samples[low] if isinstance(samples[low], (tuple, list)) else (samples[low],)
        b = samples[high] if isinstance(samples[high], (tuple, list)) else (samples[high],)
        row = tuple(x + (y - x) * weight for x, y in zip(a, b))
        if components == 4:
            # A custom RGB curve owns its colour, without an inherited warm ramp.
            row = (*row, 0.0)
        elif components == 3:
            row = row * 3
        packed.extend(row)
    raw = struct.pack('<' + 'e' * len(packed), *packed)
    node.values = [v for v in node.values if v.name != '_splineData'] + [ReflectValue('_splineData', 'uint16', 3, raw, 0, len(packed))]
    node.wire['_splineData'] = {'null': False}
    nodes = tuple(node if n is original else n for n in entries) if original else (*entries, node)
    emitter.children = [(k, v) for k, v in emitter.children if k != '_curveEntryDataList'] + [('_curveEntryDataList', nodes)]


def compile_effect_recipe(snapshot, source: bytes, look: EffectLook, *, cancelled=lambda: False) -> bytes:
    """Flatten supported inherited emitters, edit/reorder/duplicate them and read back."""
    from cdmw.domain.cancellation import RunCancelled

    validate_emitter_edits(look)
    if not look.emitters and look.emitter_order is None:
        return source
    def check():
        if cancelled():
            raise RunCancelled
    document = decode_effect_binary(source)
    if not document.walk_complete:
        raise EffectBinaryError(document.walk_note)
    document = copy.deepcopy(document)
    types = list(document.types)
    variations = document.root.child('_emitterVariationDataArray') or ()
    order = look.emitter_order if look.emitter_order is not None else tuple(range(len(variations)))
    if any(i >= len(variations) for i in order):
        raise EffectBinaryError('An emitter recipe names a source slot that does not exist.')
    selected = [copy.deepcopy(variations[i]) for i in order]
    # Only edited slots need materializing. Removing or duplicating a reference
    # must not require an unrelated, possibly unavailable emitter dependency.
    for edit in look.emitters:
        check()
        if edit.index >= len(selected):
            raise EffectBinaryError(f'Emitter slot {edit.index + 1} does not exist.')
        variation = selected[edit.index]
        node = variation.child('_internalEmitterData')
        if not isinstance(node, ReflectNode):
            raise EffectBinaryError('An emitter has no editable internal data.')
        if node.type_name != 'EmitterData':
            path = node.type_name.lstrip('/')
            if not snapshot.has_entry(path):
                raise EffectBinaryError(f'Emitter editing needs the missing dependency {path}.')
            base = decode_effect_binary(snapshot.payload(path))
            if not base.walk_complete:
                raise EffectBinaryError(f'{path}: {base.walk_note}')
            _types(types, base)
            node = _merge(base.root, node)
        else:
            node = copy.deepcopy(node)
        render_preset = node.value('_renderGroupPreset')
        render = node.child('_renderData')
        if render_preset and render_preset.value and isinstance(render, ReflectNode):
            path = preset_path('render', str(render_preset.value))
            if snapshot.has_entry(path):
                base = decode_effect_binary(snapshot.payload(path))
                if not base.walk_complete:
                    raise EffectBinaryError(f'{path}: {base.walk_note}')
                _types(types, base)
                declaration = next(t for t in types if t.type_name == render.type_name)
                known = {m.name for m in declaration.members}
                inherited = base.root.child('_renderData') or base.root
                local = {v.name: v for v in render.values}
                override = local.get('_overridePresetColor')
                for value in inherited.values:
                    if value.name in known and (value.name not in local or (not bool(override and override.value) and value.name in ('_color','_brightness','_emissiveColor','_emissiveBrightness'))):
                        local[value.name] = copy.deepcopy(value)
                render.values = list(local.values())
            elif edit.color is not None or edit.color_curve or edit.intensity != 1.0:
                raise EffectBinaryError(f'Colour editing needs the missing dependency {path}.')
        # Simulation presets are inherited before the emitter's own values.
        preset = node.value('_simulationGroupPreset')
        if preset and preset.value:
            path = preset_path('simulation', str(preset.value))
            if not snapshot.has_entry(path):
                raise EffectBinaryError(f'Emitter editing needs the missing dependency {path}.')
            base = decode_effect_binary(snapshot.payload(path))
            if not base.walk_complete:
                raise EffectBinaryError(f'{path}: {base.walk_note}')
            _types(types, base)
            group = base.root.child('_simulationData')
            if not isinstance(group, ReflectNode) and base.root.type_name == 'EmitterSimulationData':
                group = base.root
            current = node.child('_simulationData')
            if isinstance(group, ReflectNode):
                node.children = [(k, v) for k,v in node.children if k != '_simulationData'] + [('_simulationData', _merge(group, current) if isinstance(current, ReflectNode) else copy.deepcopy(group))]
        variation.children = [(k, node if k == '_internalEmitterData' else v) for k,v in variation.children]
    document = replace(document, types=tuple(types))
    for edit in look.emitters:
        check()
        if edit.index >= len(selected):
            raise EffectBinaryError(f'Emitter slot {edit.index + 1} does not exist.')
        node = selected[edit.index].child('_internalEmitterData')
        individual = replace(document, root=node)
        raw = serialize_effect(source, individual)
        raw, _ = apply_effect_look(raw, EffectLook(edit.color, edit.intensity, edit.size, edit.rate, edit.lifetime))
        individual = decode_effect_binary(raw)
        node = individual.root
        if not set_typed_value(individual, node, '_enableParticleRender', edit.enabled):
            raise EffectBinaryError('This emitter has no particle visibility field.')
        for key, values in edit.values:
            found = False
            for child in node.walk():
                if set_typed_value(individual, child, key, values[0] if len(values) == 1 else values):
                    found = True
            if not found:
                raise EffectBinaryError(f'This emitter has no editable {key} field.')
        for samples, cid, dimensions in ((edit.color_curve, 21, 4), (edit.size_curve, 5, 3), (edit.opacity_curve, 2, 1)):
            if samples:
                _curve(individual, node, cid, samples, dimensions)
        if edit.color is not None or edit.color_curve or edit.intensity != 1.0:
            render = node.child('_renderData')
            if isinstance(render, ReflectNode):
                set_typed_value(individual, render, '_overridePresetColor', True)
        if edit.texture:
            if not snapshot.has_entry(edit.texture):
                raise EffectBinaryError(f'Texture is absent from the archives: {edit.texture}')
            found = False
            material = node.child('_effectMaterialData2')
            for parameter in (material.child('_parameters') or ()) if material else ():
                label = parameter.value('_name')
                value = parameter.child('_value')
                if label and label.value in ('_textureEmissive', '_textureBase', '_textureMask') and isinstance(value, ReflectNode):
                    found = set_typed_value(individual, value, '_path', edit.texture)
                    if found:
                        break
            if not found:
                raise EffectBinaryError('This emitter has no editable sprite texture parameter.')
        selected[edit.index].children = [(k, node if k == '_internalEmitterData' else v) for k,v in selected[edit.index].children]
    for i, variation in enumerate(selected):
        if variation.name:
            variation.name = f'{variation.name}_slot{i}'
        if variation.wire.get('element_id') is not None:
            variation.wire['element_id'] = i
    document.root.children = [(k, tuple(selected) if k == '_emitterVariationDataArray' else v) for k,v in document.root.children]
    check()
    return serialize_effect(source, document)
