"""Compose immutable effect layers without decoding on the UI thread."""
from dataclasses import replace

from cdmw.services.effect_placement_rotation import euler_xyz_matrix
from cdmw.services.effect_preview_model import EffectPreview, preview_effect_from_snapshot


def layer_matrix(layer):
    m = tuple(v * layer.scale for v in euler_xyz_matrix(layer.rotation))
    return (m[0], m[1], m[2], 0.0, m[3], m[4], m[5], 0.0, m[6], m[7], m[8], 0.0, *layer.offset, 1.0)


def preview_effect_layers(snapshot, layers, active_layer=0, *, cancelled=lambda: False):
    emitters, notes, editor = [], [], []
    box = ((-0.5,) * 3, (0.5,) * 3)
    for index, layer in enumerate(layers):
        if not layer.stem:
            continue
        # A disabled layer still supplies its inspector, but contributes no particles.
        if not layer.enabled and index != active_layer:
            continue
        preview = preview_effect_from_snapshot(snapshot, layer.stem, layer.look, cancelled=cancelled)
        if index == active_layer:
            box = preview.box_min, preview.box_max
            editor = list(preview.editor_emitters)
        notes.extend(f"{layer.name or layer.stem}: {note}" for note in preview.notes)
        if layer.enabled:
            emitters.extend(replace(e, layer_index=index, layer_transform=layer_matrix(layer)) for e in preview.emitters)
    return EffectPreview("composition", tuple(emitters), *box, notes=tuple(notes), active_layer=active_layer, editor_emitters=tuple(editor))
