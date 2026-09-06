"""Bounded, portable effect recipes. No game payloads are embedded in a recipe."""
import json
import os
import uuid
import re
from dataclasses import asdict

from cdmw.domain.new_item.effect_authoring import EffectLayer, EffectLook, EmitterEdit
from cdmw.domain.new_item.spec import NewItemSpec


def write_recipe(path, text):
    """Publish a complete recipe without truncating an existing saved file."""
    read_recipe(text)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(text, encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def recipe_json(layers) -> str:
    text = json.dumps({"schema": 1, "layers": [asdict(layer) for layer in layers]}, ensure_ascii=False, allow_nan=False)
    if len(text.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('Effect recipe exceeds 2 MB.')
    read_recipe(text)
    return text


def read_recipe(text: str):
    from cdmw.domain.new_item.rules import validate_spec
    if len(text.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('Effect recipe exceeds 2 MB.')
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('layers'), list) or len(data['layers']) > 16:
        raise ValueError('Unsupported effect recipe; expected up to 16 layers.')
    layers = []
    for row in data['layers']:
        row = dict(row)
        look = dict(row.pop('look', {}))
        edits = []
        for raw in look.pop('emitters', ()):
            edit = dict(raw)
            edit['values'] = tuple((key, tuple(float(v) for v in value)) for key, value in edit.get('values', ()))
            for key in ('color_curve',):
                edit[key] = tuple(tuple(float(v) for v in c) for c in edit.get(key, ()))
            for key in ('size_curve', 'opacity_curve'):
                edit[key] = tuple(float(v) for v in edit.get(key, ()))
            if edit.get('color') is not None:
                edit['color'] = tuple(edit['color'])
            edits.append(EmitterEdit(**edit))
        if look.get('color') is not None:
            look['color'] = tuple(look['color'])
        if look.get('emitter_order') is not None:
            look['emitter_order'] = tuple(look['emitter_order'])
        look['emitters'] = tuple(edits)
        for key in ('offset', 'rotation'):
            if key in row:
                row[key] = tuple(row[key])
        if not isinstance(row.get('stem'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', row['stem']):
            raise ValueError('Invalid effect source stem.')
        if not isinstance(row.get('name', ''), str) or len(row.get('name', '')) > 128 or type(row.get('enabled', True)) is not bool:
            raise ValueError('Invalid effect layer name or visibility.')
        layers.append(EffectLayer(**row, look=EffectLook(**look)))
    errors = [i.message for i in validate_spec(NewItemSpec(1, 'Recipe', effect_layers=tuple(layers))) if i.code.startswith('effect.') and i.severity == 'error']
    if errors:
        raise ValueError('; '.join(errors))
    return tuple(layers)
