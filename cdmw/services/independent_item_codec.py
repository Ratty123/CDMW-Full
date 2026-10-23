"""Frozen v1 wire decoding and explicit adapters to current authoring models."""
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import math
from typing import Mapping

from cdmw.domain.new_item import authoring, spec, effect_authoring, translucency, body_visibility, surface
from cdmw.domain.mesh import emission, shader_controls
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.independent_wire_v1 import V1_ENUM_VALUES, V1_RECORD_FIELDS


@dataclass(frozen=True)
class RecordAdapter:
    """Internal renames/defaults need a reviewed translation, never a wire change."""
    kind: type
    renames: Mapping[str, str] = field(default_factory=dict)
    defaults: Mapping[str, object] = field(default_factory=dict)


_RECORDS = {
    'SocketSlot': RecordAdapter(authoring.SocketSlot),
    'EquipmentBonus': RecordAdapter(authoring.EquipmentBonus),
    'LevelBonuses': RecordAdapter(authoring.LevelBonuses),
    'RecipeInput': RecordAdapter(authoring.RecipeInput),
    'RecipeOutput': RecordAdapter(authoring.RecipeOutput),
    'RecipeOverride': RecordAdapter(authoring.RecipeOverride),
    'RewardAcquisition': RecordAdapter(authoring.RewardAcquisition),
    'DyeAssignment': RecordAdapter(authoring.DyeAssignment),
    'VariantAppearance': RecordAdapter(authoring.VariantAppearance),
    'StatEdit': RecordAdapter(spec.StatEdit),
    'BuyPriceEdit': RecordAdapter(spec.BuyPriceEdit),
    'PriceEdit': RecordAdapter(spec.PriceEdit),
    'Placement': RecordAdapter(spec.Placement),
    'GlowChoice': RecordAdapter(spec.GlowChoice),
    'NewItemSpec': RecordAdapter(spec.NewItemSpec, defaults={
        'item_tier': None, 'required_level': None, 'max_durability': None, 'item_settings': None}),
    'EmitterEdit': RecordAdapter(effect_authoring.EmitterEdit),
    'EffectLook': RecordAdapter(effect_authoring.EffectLook),
    'EffectLayer': RecordAdapter(effect_authoring.EffectLayer),
    'TranslucencyChoice': RecordAdapter(translucency.TranslucencyChoice),
    'BodyVisibilityChoice': RecordAdapter(body_visibility.BodyVisibilityChoice),
    'SurfaceEdit': RecordAdapter(surface.SurfaceEdit),
    'GlowAnimation': RecordAdapter(emission.GlowAnimation),
    'RgbGlow': RecordAdapter(emission.RgbGlow),
    'EmissionChoice': RecordAdapter(emission.EmissionChoice),
    'ShaderField': RecordAdapter(shader_controls.ShaderField),
    'ShaderFamily': RecordAdapter(shader_controls.ShaderFamily),
    'ShaderControls': RecordAdapter(shader_controls.ShaderControls),
}
_ENUMS = {
    'ModelSource': {'template': spec.ModelSource.TEMPLATE, 'imported': spec.ModelSource.IMPORTED},
    'IconSource': {'template': spec.IconSource.TEMPLATE, 'generated': spec.IconSource.GENERATED},
    'MaterialRoute': {'builder': spec.MaterialRoute.BUILDER, 'plain_pbr': spec.MaterialRoute.PLAIN_PBR},
    'SheathedModel': {'template': spec.SheathedModel.TEMPLATE, 'own_model': spec.SheathedModel.OWN_MODEL},
    'ItemGroupsChoice': {'ordinary': spec.ItemGroupsChoice.ORDINARY, 'template': spec.ItemGroupsChoice.TEMPLATE, 'explicit': spec.ItemGroupsChoice.EXPLICIT},
    'EnhancementRows': {'template': spec.EnhancementRows.TEMPLATE, 'own': spec.EnhancementRows.OWN},
    'PlacementKind': {'none': spec.PlacementKind.NONE, 'swap': spec.PlacementKind.SWAP, 'insert': spec.PlacementKind.INSERT},
}


def _adapter_fields(name, adapter):
    names = {key: adapter.renames.get(key, key) for key in V1_RECORD_FIELDS[name]}
    targets = set(names.values())
    # Reflection checks the explicit bridge, not the serialized vocabulary. A new
    # runtime field cannot silently change old packages or disappear on export.
    if (set(adapter.renames) - set(names) or len(targets) != len(names)
            or targets & set(adapter.defaults)
            or targets | set(adapter.defaults) != {f.name for f in fields(adapter.kind)}):
        raise IndependentItemError(f'The v1 runtime adapter for {name} needs an explicit compatibility translation.')
    return names


def _matches(value, schema):
    if isinstance(schema, tuple):
        kind, *args = schema
        if kind == 'union':
            return any(_matches(value, arg) for arg in args)
        if kind == 'sequence':
            return isinstance(value, (tuple, list)) and all(_matches(v, args[0]) for v in value)
        if kind == 'tuple':
            return isinstance(value, (tuple, list)) and len(value) == len(args) and all(_matches(v, a) for v, a in zip(value, args))
        if kind == 'map':
            return isinstance(value, dict) and all(_matches(k, args[0]) and _matches(v, args[1]) for k, v in value.items())
        return False
    if schema == 'float':
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    primitives = {'bool': bool, 'int': int, 'str': str, 'null': type(None)}
    if schema in primitives:
        return type(value) is primitives[schema]
    if schema in _RECORDS:
        return type(value) is _RECORDS[schema].kind
    if schema in _ENUMS:
        return any(value is member for member in _ENUMS[schema].values())
    return False  # Includes v1's deliberately unavailable mask types.


def _checked_recipe_text(value):
    if type(value) is not str or len(value) > 65536 or '\0' in value:
        raise IndependentItemError('Invalid item recipe text.')
    return value


def encode(value, depth=0):
    if depth > 24:
        raise IndependentItemError('Item recipe is nested too deeply.')
    if isinstance(value, Enum):
        for name, members in _ENUMS.items():
            for wire_value, member in members.items():
                if value is member and wire_value in V1_ENUM_VALUES[name]:
                    return {'enum': name, 'value': wire_value}
        raise IndependentItemError('Unsupported portable enum setting.')
    if is_dataclass(value):
        for name, adapter in _RECORDS.items():
            if type(value) is not adapter.kind:
                continue
            names = _adapter_fields(name, adapter)
            if any(getattr(value, key) != default for key, default in adapter.defaults.items()):
                raise IndependentItemError(f'The {name} setting cannot be represented by v1.')
            values = {key: getattr(value, runtime_key) for key, runtime_key in names.items()}
            if any(not _matches(v, V1_RECORD_FIELDS[name][key]) for key, v in values.items()):
                raise IndependentItemError(f'Invalid value type in {name}.')
            return {'type': name, 'fields': {key: encode(v, depth + 1) for key, v in values.items()}}
        raise IndependentItemError(f'Unsupported portable setting: {type(value).__name__}.')
    if isinstance(value, (tuple, list)):
        if len(value) > 10000:
            raise IndependentItemError('Item recipe contains too many values.')
        return [encode(v, depth + 1) for v in value]
    if isinstance(value, dict):
        if len(value) > 10000:
            raise IndependentItemError('Item recipe contains too many values.')
        return {'map': {_checked_recipe_text(k): encode(v, depth + 1) for k, v in value.items()}}
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is str:
        return _checked_recipe_text(value)
    if type(value) is float and math.isfinite(value):
        return value
    raise IndependentItemError('The item contains a setting that cannot be shared safely.')


def decode(value, depth=0):
    if depth > 24:
        raise IndependentItemError('Item recipe is nested too deeply.')
    if isinstance(value, list):
        if len(value) > 10000:
            raise IndependentItemError('Item recipe contains too many values.')
        return tuple(decode(v, depth + 1) for v in value)
    if isinstance(value, dict):
        if set(value) == {'map'} and isinstance(value['map'], dict):
            if len(value['map']) > 10000:
                raise IndependentItemError('Item recipe contains too many values.')
            return {_checked_recipe_text(k): decode(v, depth + 1) for k, v in value['map'].items()}
        name = value.get('type', value.get('enum', ''))
        if type(name) is not str:
            raise IndependentItemError('Unknown item recipe type.')
        if name in _ENUMS and set(value) == {'enum', 'value'}:
            raw = value['value']
            if type(raw) is not str or raw not in V1_ENUM_VALUES[name]:
                raise IndependentItemError(f'Unknown v1 enum value for {name}.')
            return _ENUMS[name][raw]
        if name in _RECORDS and set(value) == {'type', 'fields'}:
            raw = value['fields']
            if not isinstance(raw, dict) or set(raw) != set(V1_RECORD_FIELDS[name]):
                raise IndependentItemError('Unknown or missing item recipe fields.')
            decoded = {k: decode(v, depth + 1) for k, v in raw.items()}
            if any(not _matches(v, V1_RECORD_FIELDS[name][key]) for key, v in decoded.items()):
                raise IndependentItemError(f'Invalid value type in {name}.')
            adapter = _RECORDS[name]
            names = _adapter_fields(name, adapter)
            arguments = {names[key]: v for key, v in decoded.items()}
            arguments.update(deepcopy(adapter.defaults))
            try:
                return adapter.kind(**arguments)
            except (TypeError, ValueError) as exc:
                raise IndependentItemError(f'Invalid v1 {name} setting: {exc}') from exc
        raise IndependentItemError('Unknown item recipe type.')
    return encode(value, depth)
