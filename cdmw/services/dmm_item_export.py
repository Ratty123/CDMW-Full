"""Opt-in V3 lowering of already verified, identity-bound .cditem exports.

The normal compiler and dependency checks remain authoritative. This adapter
admits only additive existing-model items, never arbitrary binary row edits.
"""
from collections import Counter
from dataclasses import replace
from pathlib import PurePosixPath

from cdmw.core.dmm_item_fields import item_patches, stock_value
from cdmw.core.item_recipe_table import parse_item_recipe, encode_item_recipe
from cdmw.core.item_reward_table import parse_item_reward_set, encode_item_reward_set
from cdmw.core.itemgroupinfo_table import parse_item_group_row, encode_item_group_row
from cdmw.core.new_item_record import RecordError
from cdmw.core.paloc_format import parse_paloc
from cdmw.core.storeinfo_table import parse_store_row, encode_store_row, encode_stock_entry
from cdmw.domain.archives.overlay_merge import _table
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.spec import ModelSource, IconSource
from cdmw.services.independent_item_package import read_package, unpack_recipe, package_metadata


SOURCE_FOLDER = 'cdmw-source'


def _rows(body, header):
    return {int.from_bytes(key, 'little'): raw for key, raw in _table(body, header)[1]}


def _clone(source_key, new_key, patches):
    if not 0 < new_key < 1 << 31 or source_key == new_key:
        raise RecordError('DMM V3: invalid or overlapping clone identity.')
    return dict(op='clone_record', source_key=source_key, new_key=new_key, patches=patches)


def _patches(before, after):
    return [dict(path=name, new=value) for name, value in after.items() if before[name] != value]


def _recipe_values(row):
    return dict(string_key=row.name, craft_tool_info=row.tool_key, need_knowledge_info=row.knowledge_key,
        fixed_material_data_list=[dict(item_info=r.item_key, gimmick_info=r.character_key,
            character_info=r.gimmick_key, count=r.quantity, coupon_count=r.coupon_quantity,
            enchant_level=r.enhancement) for r in row.ingredients],
        recipe_item_group_info_list=[dict(item_group_info=r.group_key, count=r.quantity,
            enchant_level=r.enhancement) for r in row.group_ingredients],
        result_drop_info_list=list(row.reward_keys), additional_drop_info_list=list(row.additional_reward_keys))


def _recipe_patches(before, after):
    source, final = parse_item_recipe(before), parse_item_recipe(after)
    supported = ('key', 'name', 'tool_key', 'knowledge_key', 'ingredients', 'group_ingredients',
                 'reward_keys', 'additional_reward_keys')
    if encode_item_recipe(replace(source, **{name: getattr(final, name) for name in supported})) != after:
        raise RecordError('DMM V3: unsupported refinement recipe changes.')
    return _patches(_recipe_values(source), _recipe_values(final))


def _reward_values(row):
    return dict(string_key=row.name, list=[dict(raw_at_120=r.item_key, dispatch_tag=0,
        lookup_4=r.condition_references[0], lookup_6=r.condition_references[1],
        lookup_8=r.condition_references[2], raw_12=r.condition_references[3],
        raw_16=r.weight, raw_32=r.sub_weight, raw_40=r.minimum, raw_48=r.maximum,
        raw_56=r.enhancement & 0xffff, variant=dict(tag=0, lookup=r.item_key)) for r in row.entries],
        total_drop_rate=row.total_weight, original_string=row.original_string)


def _reward_patches(before, after):
    source, final = parse_item_reward_set(before), parse_item_reward_set(after)
    if encode_item_reward_set(replace(source, key=final.key, name=final.name, entries=final.entries,
            total_weight=final.total_weight, original_string=final.original_string)) != after:
        raise RecordError('DMM V3: unsupported reward policy changes.')
    return _patches(_reward_values(source), _reward_values(final))


def _group_intents(before, after, owned):
    source, final = parse_item_group_row(before), parse_item_group_row(after)
    if encode_item_group_row(replace(source, members=final.members)) != after:
        raise RecordError('DMM V3: only additive item-group membership is supported.')
    additions = [key for key in final.members if key not in source.members]
    if ([key for key in final.members if key not in additions] != list(source.members)
            or len(set(additions)) != len(additions) or not set(additions) <= owned):
        raise RecordError('DMM V3: item-group removal, reordering or foreign membership is unsupported.')
    return [dict(op='array_union', key=source.key, field='item_info_list', new=additions)] if additions else []


def _stock_intents(before, after, owned):
    source, final = (parse_store_row(raw, layout='current') for raw in (before, after))
    if encode_store_row(replace(source, entries=final.entries, buyable_count=final.buyable_count,
                                sellable_count=final.sellable_count)) != after:
        raise RecordError('DMM V3: unsupported shop policy changes.')
    # CDMW inserts buyable stock before sell-only lines and renumbers positions.
    # V3 appends additions, retaining vanilla positions. Compare all other bytes.
    def normalized(entry):
        return encode_stock_entry(replace(entry, stock_index=0))
    remaining = Counter(normalized(entry) for entry in source.entries)
    additions, retained = [], []
    for entry in final.entries:
        raw = normalized(entry)
        if remaining[raw]:
            remaining[raw] -= 1
            retained.append(raw)
        else:
            if entry.item_key not in owned or len(entry.condition_data) != 8:
                raise RecordError('DMM V3: shop replacements and foreign stock are unsupported.')
            additions.append(entry)
    if any(remaining.values()) or retained != [normalized(entry) for entry in source.entries]:
        raise RecordError('DMM V3: existing shop stock changed; use the existing export.')
    if (final.buyable_count != sum(e.is_buyable for e in final.entries)
            or final.sellable_count != sum(e.is_sellable for e in final.entries)):
        raise RecordError('DMM V3: inconsistent shop stock counts.')
    return [dict(op='array_append', key=source.key, field='stock_data_list',
        new=stock_value(encode_stock_entry(replace(entry, stock_index=len(source.entries) + index))))
        for index, entry in enumerate(additions)]


def build_field_json(export, title, *, stop_event=None):
    """Lower the whole reviewed contribution, refusing any unrepresented output."""
    export.validate(stop_event)
    files = {path: data for path, data, _flags in export.files}
    if len(files) != len(export.files) or set(files) != set(export.originals):
        raise RecordError('DMM V3: incomplete source/output inventory.')
    tables, locales, handled = {}, {}, set()
    for path in files:
        raise_if_cancelled(stop_event)
        if export.originals[path] is None:
            raise RecordError('DMM V3 requires existing models and icons; new resources are unsupported.')
        name = PurePosixPath(path).name
        if path.endswith('.staticinfobody'):
            family = name.split('.')[0]
            if family not in ('iteminfo', 'multichangeinfo', 'dropsetinfo', 'storeinfo', 'itemgroupinfo'):
                raise RecordError(f'DMM V3: unsupported table {family}.')
            header = path[:-len('.staticinfobody')] + '.staticinfoheader'
            if header not in files or export.originals[header] is None or family in tables:
                raise RecordError('DMM V3: missing or ambiguous table source.')
            tables[family] = (_rows(export.originals[path], export.originals[header]), _rows(files[path], files[header]))
            handled.update((path, header))
        elif path.endswith('.paloc'):
            # New split item tables and the legacy localization target have the
            # same manager-facing name. No paths from a package are guessed.
            parts = PurePosixPath(path).parts
            if len(parts) == 5 and parts[:3] == ('gamedata', 'stringtable', 'binary__') and name == 'item.paloc':
                language = parts[3]
            else:
                raise RecordError('DMM V3 requires current split item localization tables.')
            if language in locales:
                raise RecordError('DMM V3: ambiguous item localization.')
            locales[language] = (parse_paloc(export.originals[path]), parse_paloc(files[path]))
            handled.add(path)
    if handled != set(files) or 'iteminfo' not in tables:
        raise RecordError('DMM V3 supports current item tables only; use the existing export for other payloads.')

    mappings = {name: {} for name in ('iteminfo', 'multichangeinfo', 'dropsetinfo')}
    def bind(family, key, donor):
        if key in mappings[family] and mappings[family][key] != donor:
            raise RecordError('DMM V3: conflicting retained clone identities.')
        mappings[family][key] = donor
    for raw in export.packages:
        raise_if_cancelled(stop_event)
        package = read_package(raw, stop_event=stop_event)
        meta = package_metadata(package)
        if meta.get('version') == 2 and any(module['type'] not in
                ('item.legacy', 'item.properties', 'item.stats') for module in meta['modules']):
            raise RecordError('DMM V3 cannot preserve stock field edits, package links or texture modules.')
        spec, model, variants, icon = unpack_recipe(package)
        if spec.model_source is not ModelSource.TEMPLATE or spec.icon is not IconSource.TEMPLATE or model or variants or icon or package.blobs:
            raise RecordError('DMM V3 requires existing models and icons without prepared resources.')
        binding = export.bindings['items'][package.identity]['values']
        for family, values in binding.items():
            if values and family not in mappings:
                raise RecordError(f'DMM V3: unsupported owned namespace {family}.')
        for symbol, key in binding.get('iteminfo', {}).items():
            if symbol == 'item':
                donor = spec.template_key
            elif symbol.startswith('perk:'):
                donor = int(symbol.split(':')[1])
            else:
                raise RecordError('DMM V3: unknown owned ItemInfo symbol.')
            bind('iteminfo', key, donor)
        for symbol, key in binding.get('multichangeinfo', {}).items():
            if not symbol.startswith('recipe:') or symbol.count(':') != 1:
                raise RecordError('DMM V3: unknown recipe symbol.')
            bind('multichangeinfo', key, int(symbol.split(':')[1]))
        for symbol, key in binding.get('dropsetinfo', {}).items():
            parts = symbol.split(':')
            if len(parts) != 3 or parts[0] != 'recipe' or 'multichangeinfo' not in tables:
                raise RecordError('DMM V3: unsupported owned reward symbol.')
            recipe = parse_item_recipe(tables['multichangeinfo'][0][int(parts[1])])
            rewards = recipe.reward_keys + recipe.additional_reward_keys
            index = int(parts[2])
            if not 0 <= index < len(rewards):
                raise RecordError('DMM V3: invalid owned reward index.')
            bind('dropsetinfo', key, rewards[index])

    owned = set(mappings['iteminfo'])
    targets = []
    for family in ('dropsetinfo', 'multichangeinfo', 'iteminfo', 'itemgroupinfo', 'storeinfo'):
        if family not in tables:
            continue
        source, final = tables[family]
        if set(source) - set(final):
            raise RecordError('DMM V3 cannot remove source records.')
        intents = []
        for key in sorted(final):
            raise_if_cancelled(stop_event)
            if key in source:
                if source[key] == final[key]:
                    continue
                if family == 'itemgroupinfo':
                    intents += _group_intents(source[key], final[key], owned)
                elif family == 'storeinfo':
                    intents += _stock_intents(source[key], final[key], owned)
                else:
                    raise RecordError(f'DMM V3 cannot preserve an edit to existing {family} record {key}.')
            else:
                donor = mappings.get(family, {}).get(key)
                if donor not in source:
                    raise RecordError(f'DMM V3: no witnessed donor for {family} record {key}.')
                lower = {'iteminfo': item_patches, 'multichangeinfo': _recipe_patches,
                         'dropsetinfo': _reward_patches}[family]
                intents.append(_clone(donor, key, lower(source[donor], final[key])))
        if intents:
            targets.append(dict(file=family + '.pabgb', intents=intents))
    for language, (source, final) in sorted(locales.items()):
        before, after = source.index(), final.index()
        if (len(before) != len(source.entries) or len(after) != len(final.entries)
                or any(after.get(key) != value for key, value in before.items())):
            raise RecordError('DMM V3: existing localization changed or has duplicate keys.')
        intents = []
        for key in sorted(set(after) - set(before), key=int):
            row = after[key]
            if (not key.isascii() or not key.isdecimal() or str(int(key)) != key
                    or row.reserved or int(key) >> 32 not in owned or int(key) & 0xffffffff not in (0x70, 0x71)):
                raise RecordError('DMM V3: unsupported localization identity.')
            intents.append(dict(op='new_record', entry=key, key=row.category, field='value', new=row.text))
        if intents:
            targets.append(dict(file=f'localizationstring_{language}.paloc', intents=intents))
    if not targets:
        raise RecordError('DMM V3: no supported item additions.')
    return dict(format=3, modinfo=dict(name=title, version='1.0.0',
        description='Experimental existing-model item export from CDMW.'), targets=targets)
