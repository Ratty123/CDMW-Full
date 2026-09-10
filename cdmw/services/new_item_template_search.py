"""Immutable equipment search data prepared with the New Item snapshot."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Mapping

from cdmw.services.archive_workflow_service import archive_name_search_text_match, parse_archive_search_query
from cdmw.domain.cancellation import raise_if_cancelled


TemplateOption = tuple[int, str, str, str]


@dataclass(frozen=True)
class TemplateSearchRow:
    option: TemplateOption
    name_fields: tuple[str, ...]
    all_fields: tuple[str, ...]
    sort_values: tuple[str, str, int, str, str]


@dataclass(frozen=True)
class TemplateSearchCatalogue:
    rows: tuple[TemplateSearchRow, ...]
    category_members: Mapping[int, frozenset[int]]


def build_template_search_catalogue(snapshot, *, stop_event=None) -> TemplateSearchCatalogue:
    """Copy just the search facts; background searches never access a live draft or widget."""

    display_names = snapshot.item_display_names()
    localized_names = snapshot.item_search_names()
    rows = []
    for key, row in snapshot.rows.items():
        raise_if_cancelled(stop_event)
        equip = snapshot.equip_type_name(row)
        if not equip:
            continue
        key = int(key)
        internal_name = str(row.string_key or "")
        display_name = str(display_names.get(key, "") or "")
        names = tuple(dict.fromkeys(
            str(value).casefold()
            for value in (internal_name, display_name, *localized_names.get(key, ()))
            if value
        ))
        capability = "Unsupported" if row.stat_block_offset is None else "Stats" if row.enchant_levels else "Prices / sockets"
        rows.append(TemplateSearchRow(
            (key, internal_name, display_name, equip),
            names,
            (*names, equip.casefold(), str(key)),
            (internal_name.casefold(), display_name.casefold(), key, equip.casefold(), capability.casefold()),
        ))

    groups = {group.key: group for group in snapshot.item_groups}
    categories = {}
    for group in snapshot.item_groups:
        if group.name != "ItemGroup_Category_Equipment" and not group.name.startswith("ItemGroup_SubCategory_Equip_"):
            continue
        members, visited, pending = set(), set(), [group.key]
        while pending:
            raise_if_cancelled(stop_event)
            key = pending.pop()
            if key in visited or key not in groups:
                continue
            visited.add(key)
            members.update(groups[key].members)
            pending.extend(groups[key].subgroups)
        categories[group.key] = frozenset(members)
    return TemplateSearchCatalogue(tuple(rows), MappingProxyType(categories))


def search_template_options(
    catalogue: TemplateSearchCatalogue,
    text: str = "",
    *,
    group_key: int | None = None,
    sort_column: int = -1,
    descending: bool = False,
    limit: int | None = 60,
    stop_event: threading.Event | None = None,
) -> list[TemplateOption]:
    """Preserve Archive Browser query semantics, exact-name ranking and complete-set sorting."""

    raise_if_cancelled(stop_event)
    raw_needle = str(text or "").strip().casefold()
    query = parse_archive_search_query(text)
    members = catalogue.category_members.get(group_key, frozenset()) if group_key is not None else None

    @lru_cache(maxsize=8192)
    def field_matches(field, term):
        value = str(term.value or "").casefold()
        return bool(value and not term.glob and not term.phrase and value in field) or archive_name_search_text_match(field, term)

    def term_matches(term, row):
        fields = row.name_fields if term.field == "name" else row.all_fields if term.field == "any" else ()
        return any(field_matches(field, term) for field in fields if field)

    ranked = []
    for row in catalogue.rows:
        raise_if_cancelled(stop_event)
        key = row.option[0]
        if members is not None and key not in members:
            continue
        if not query.is_empty and not any(
            all(
                not term_matches(term, row) if term.negated else term_matches(term, row)
                for term in group
            )
            for group in query.groups
        ):
            continue
        rank = 0 if raw_needle and (raw_needle == str(key) or raw_needle in row.name_fields) else 1
        ranked.append((rank, row))

    raise_if_cancelled(stop_event)
    if 0 <= sort_column < 5:
        ranked.sort(key=lambda item: (item[1].sort_values[sort_column], item[1].sort_values[0], item[1].option[0]), reverse=descending)
    else:
        ranked.sort(key=lambda item: (item[0], item[1].sort_values[0], item[1].option[0]))
    raise_if_cancelled(stop_event)
    return [row.option for _rank, row in (ranked if limit is None else ranked[:limit])]
