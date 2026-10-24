"""Source-qualified dependencies for owned extended ItemInfo settings."""
from dataclasses import dataclass, replace

from cdmw.core.item_layout import read_item_use_layout
from cdmw.core.item_use_reward import parse_item_use_reward
from cdmw.core.item_reward_table import parse_item_reward_set, encode_item_reward_set
from cdmw.core.new_item_record import RecordError, Cursor
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.new_item_acquisition_index import optional_pair


@dataclass(frozen=True)
class UseAction:
    key: int
    name: str
    kind: int
    variant: str
    layout: object


@dataclass(frozen=True)
class ItemSettingsIndex:
    items: tuple
    actions: tuple
    rewards: tuple
    unsupported_actions: int
    unavailable: tuple = ()
    skills: tuple = ()


def load_settings_index(snapshot, *, stop_event=None):
    raise_if_cancelled(stop_event)
    cached = snapshot._authoring_indexes.get('item-settings')
    if cached is not None:
        raise_if_cancelled(stop_event)
        return cached
    english = snapshot.english.index()
    items = []
    for key, row in snapshot.rows.items():
        raise_if_cancelled(stop_event)
        if not row.is_blocked:
            items.append((key, english[row.name_key].text if row.name_key in english else row.string_key))
    actions, rewards, skills, unsupported = [], [], [], 0
    available = snapshot.sources.tables if snapshot.sources is not None else {}
    unavailable = tuple(name for name in ('itemuseinfo', 'dropsetinfo', 'skillinfo') if name not in available)
    for key, raw in (_rows(snapshot, 'itemuseinfo', stop_event=stop_event) if 'itemuseinfo' in available else {}).items():
        raise_if_cancelled(stop_event)
        try:
            layout = read_item_use_layout(raw)
            cursor = Cursor(layout.data('_stringKey'))
            actions.append((key, cursor.text(), layout.variants[0]))
        except (RecordError, UnicodeError):
            unsupported += 1
    for key, raw in (_rows(snapshot, 'dropsetinfo', stop_event=stop_event) if 'dropsetinfo' in available else {}).items():
        raise_if_cancelled(stop_event)
        try:
            reward = parse_item_reward_set(raw)
            if encode_item_reward_set(reward) == raw:
                rewards.append((key, reward.name))
        except (RecordError, UnicodeError):
            pass
    for key, raw in (_rows(snapshot, 'skillinfo', stop_event=stop_event) if 'skillinfo' in available else {}).items():
        raise_if_cancelled(stop_event)
        try:
            cursor = Cursor(raw)
            cursor.take(4)
            skills.append((key, cursor.text()))
        except (RecordError, UnicodeError):
            pass
    result = ItemSettingsIndex(tuple(sorted(items)), tuple(sorted(actions)), tuple(sorted(rewards)), unsupported,
                               unavailable, tuple(sorted(skills)))
    raise_if_cancelled(stop_event)
    snapshot._authoring_indexes['item-settings'] = result
    return result


def _rows(snapshot, table, *, stop_event=None):
    raise_if_cancelled(stop_event)
    cache_key = ('item-settings-table', table)
    cached = snapshot._authoring_indexes.get(cache_key)
    if cached is None:
        pair = optional_pair(snapshot, table)
        rows = {}
        for directory, start, end in parse_pabgh_table(pair.header, payload=pair.payload).row_spans(len(pair.payload)):
            raise_if_cancelled(stop_event)
            raw = pair.payload[start:end]
            if len(raw) < 4 or int.from_bytes(raw[:4], 'little') != directory.row_id or directory.row_id in rows:
                raise RecordError(f'{table} has an unqualified row identity.')
            rows[directory.row_id] = raw
        raise_if_cancelled(stop_event)
        cached = rows
        snapshot._authoring_indexes[cache_key] = cached
    return cached


def _reference(snapshot, table, key, *, stop_event=None):
    if key == 0:
        return
    if key not in _rows(snapshot, table, stop_event=stop_event):
        raise RecordError(f'Missing {table} dependency {key}.')


def validate_reward(snapshot, key, *, stop_event=None):
    raw = _rows(snapshot, 'dropsetinfo', stop_event=stop_event).get(key)
    if raw is None:
        raise RecordError(f'Missing extraction reward {key}.')
    reward = parse_item_reward_set(raw)
    if reward.key != key or encode_item_reward_set(reward) != raw:
        raise RecordError('The extraction reward did not round-trip.')
    for entry in reward.entries:
        raise_if_cancelled(stop_event)
        if entry.item_key not in snapshot.rows or snapshot.rows[entry.item_key].is_blocked:
            raise RecordError(f'Missing or blocked reward item {entry.item_key}.')
    return reward


def load_use_action(snapshot, key, *, stop_event=None):
    raise_if_cancelled(stop_event)
    raw = _rows(snapshot, 'itemuseinfo', stop_event=stop_event).get(key)
    if raw is None:
        raise RecordError(f'Missing item-use action {key}.')
    layout = read_item_use_layout(raw)
    if layout.integer('_key', width=4) != key or not layout.variants:
        raise RecordError('Unqualified item-use action identity.')
    reader = Cursor(layout.data('_stringKey'))
    name = reader.text()
    reader.finish()
    kind = layout.data('_itemUseInfoData')[0]
    # These are established source references. Unknown payload bytes retain
    # their original game definitions; no generic integer is guessed to be a key.
    for member in layout.members:
        raise_if_cancelled(stop_event)
        table = 'skillinfo' if (member.owner, member.name) == ('SkillLevelData', '_skillInfo') else {
            'skill': 'skillinfo', 'conditioninfo': 'conditioninfo', 'sublevelinfo': 'sublevelinfo',
            'characterinfo': 'characterinfo', 'sequencerspawninfo': 'sequencerspawninfo',
            'levelgimmicksceneobjectinfo': 'levelgimmicksceneobjectinfo',
        }.get(member.name)
        if table is not None:
            if member.span.size != 4:
                raise RecordError('Unsupported use-action reference width.')
            _reference(snapshot, table, int.from_bytes(raw[member.span.start:member.span.end], 'little'),
                       stop_event=stop_event)
    if kind == 2:
        reward_use = parse_item_use_reward(raw)
        validate_reward(snapshot, reward_use.reward_key, stop_event=stop_event)
    return UseAction(key, name, kind, layout.variants[0], layout)


def validate_settings_dependencies(settings, snapshot, *, stop_event=None):
    for entry in settings.repairs or ():
        raise_if_cancelled(stop_event)
        resource = snapshot.rows.get(entry.resource_item)
        if resource is None or resource.is_blocked:
            raise RecordError(f'Missing or blocked repair resource {entry.resource_item}.')
    if settings.extraction_reward:
        validate_reward(snapshot, settings.extraction_reward, stop_event=stop_event)
    for key in settings.use_actions or ():
        load_use_action(snapshot, key, stop_event=stop_event)


def inherited_settings(settings, raw):
    from cdmw.core.iteminfo_settings import read_item_settings
    from cdmw.domain.new_item.item_settings import SETTINGS_FIELDS
    template, _quantities = read_item_settings(raw)
    return replace(settings, **{name: getattr(template, name) for name in SETTINGS_FIELDS
                                if name != 'quantities' and getattr(settings, name) is None})


def validate_stat_dependencies(raw, snapshot, *, stop_event=None):
    from cdmw.core.iteminfo_stats import read_item_stats
    statistics, skills = read_item_stats(raw)
    for row in statistics:
        raise_if_cancelled(stop_event)
        if row.key == 0:
            raise RecordError('An item stat has no StatusInfo dependency.')
        _reference(snapshot, 'statusinfo', row.key, stop_event=stop_event)
    for skill in skills:
        raise_if_cancelled(stop_event)
        if skill.skill_key == 0:
            raise RecordError('An equipment passive has no SkillInfo dependency.')
        _reference(snapshot, 'skillinfo', skill.skill_key, stop_event=stop_event)


def validate_inventory_dependencies(raw, snapshot, *, stop_event=None):
    from cdmw.core.iteminfo_inventory import read_item_inventory
    settings = read_item_inventory(raw)
    for key in settings.material_items:
        raise_if_cancelled(stop_event)
        item = snapshot.rows.get(key)
        if item is None or item.is_blocked:
            raise RecordError(f'Missing or blocked material item {key}.')
        _reference(snapshot, 'iteminfo', key, stop_event=stop_event)
    for key in settings.material_gimmicks:
        raise_if_cancelled(stop_event)
        if not key:
            raise RecordError('A material has no GimmickInfo dependency.')
        _reference(snapshot, 'gimmickinfo', key, stop_event=stop_event)
    group_counts = {}
    for group in snapshot.item_groups:
        group_counts[group.key] = group_counts.get(group.key, 0) + 1
    for entry in settings.material_groups:
        raise_if_cancelled(stop_event)
        if group_counts.get(entry.group_key, 0) != 1:
            raise RecordError(f'Missing or ambiguous itemgroupinfo dependency {entry.group_key}.')
    for entry in settings.reserve_slots:
        raise_if_cancelled(stop_event)
        if not entry.slot_key:
            raise RecordError('A reserve slot has no ReserveSlotInfo dependency.')
        _reference(snapshot, 'reserveslotinfo', entry.slot_key, stop_event=stop_event)
        _reference(snapshot, 'conditioninfo', entry.condition_key, stop_event=stop_event)
