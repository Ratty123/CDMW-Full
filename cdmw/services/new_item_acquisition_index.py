"""Lazy, revision-tracked recipe/reward catalogues shared by planning and UI."""
from dataclasses import dataclass, field
from types import MappingProxyType

from cdmw.core.item_recipe_table import parse_item_recipe, encode_item_recipe
from cdmw.core.item_recipe_links import recipe_item_connections
from cdmw.core.item_reward_table import parse_item_reward_set, encode_item_reward_set
from cdmw.core.item_use_reward import parse_item_use_reward, encode_item_use_reward, item_use_references
from cdmw.core.new_item_record import RecordError, Cursor
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.new_item_snapshot import TablePair


@dataclass(frozen=True)
class AcquisitionIndex:
    pairs: object
    recipes: object
    rewards: object
    uses: object
    all_use_keys: frozenset
    consumers: tuple
    tools: object
    knowledge: object
    unsupported: object
    recipe_items: object = field(default_factory=dict)


def optional_pair(snapshot, name):
    if snapshot.sources is None or name not in snapshot.sources.tables:
        raise ValueError(f"The active game generation has no complete {name} table.")
    body, header = snapshot.sources.tables[name]
    return TablePair(body, header, snapshot.payload(body.path), snapshot.payload(header.path))


def _rows(pair):
    return ((row.row_id, pair.payload[start:end]) for row, start, end in
            parse_pabgh_table(pair.header, payload=pair.payload).row_spans(len(pair.payload)))


def load_acquisition_index(snapshot, *, stop_event=None):
    cached = snapshot._authoring_indexes.get("acquisition")
    if cached is not None:
        return cached
    pairs = {name: optional_pair(snapshot, name) for name in ("multichangeinfo", "dropsetinfo", "itemuseinfo", "crafttoolinfo", "knowledgeinfo")}
    unsupported, decoded = {}, {}
    for name, parser, encoder in (("multichangeinfo", parse_item_recipe, encode_item_recipe),
                                  ("dropsetinfo", parse_item_reward_set, encode_item_reward_set),
                                  ("itemuseinfo", parse_item_use_reward, encode_item_use_reward)):
        rows, errors = {}, {}
        for key, raw in _rows(pairs[name]):
            raise_if_cancelled(stop_event, "Acquisition index cancelled.")
            try:
                row = parser(raw)
                if row.key != key or encoder(row) != raw:
                    raise RecordError("Static table round trip failed")
                rows[key] = row
            except (ValueError, UnicodeError) as exc:
                errors[key] = str(exc)
        decoded[name] = MappingProxyType(rows)
        unsupported[name] = MappingProxyType(errors)
    names = {}
    for name, width in (("crafttoolinfo", 2), ("knowledgeinfo", 4)):
        rows = {}
        for key, raw in _rows(pairs[name]):
            raise_if_cancelled(stop_event, "Acquisition index cancelled.")
            cursor = Cursor(raw)
            cursor.take(width)
            rows[key] = cursor.text()
        names[name] = MappingProxyType(rows)
    uses, rewards = decoded["itemuseinfo"], decoded["dropsetinfo"]
    all_use_keys = frozenset(key for key, _ in _rows(pairs["itemuseinfo"]))
    consumers = []
    for item in snapshot.rows.values():
        raise_if_cancelled(stop_event, "Acquisition index cancelled.")
        try:
            _offset, keys = item_use_references(item, all_use_keys)
        except RecordError:
            continue
        for position, key in enumerate(keys):
            use = uses.get(key)
            if use is not None and use.reward_key in rewards:
                consumers.append((item.key, position, key, use.reward_key))
    recipe_items = recipe_item_connections(decoded["multichangeinfo"], rewards,
        check=lambda: raise_if_cancelled(stop_event, "Acquisition index cancelled."))
    result = AcquisitionIndex(MappingProxyType(pairs), decoded["multichangeinfo"], rewards, uses,
                              all_use_keys, tuple(consumers), names["crafttoolinfo"], names["knowledgeinfo"],
                              MappingProxyType(unsupported), MappingProxyType(recipe_items))
    snapshot._authoring_indexes["acquisition"] = result
    return result
