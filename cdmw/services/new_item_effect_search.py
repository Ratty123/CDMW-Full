"""Pure, cancellable matching over prepared immutable effect library rows."""
from cdmw.domain.cancellation import raise_if_cancelled


def filter_effect_rows(candidates, *, selected, terms, category, loop_only, one_shot_only,
                       favourites, family, family_of, previous_rows, no_effect, stop_event):
    rows, matches = [], 0
    for index, (stem, row) in enumerate(candidates.items()):
        if index % 128 == 0:
            raise_if_cancelled(stop_event)
        matched = (all(term in row.search_text or term in row.label.casefold() for term in terms)
                   and (category == "All" or category in row.tags)
                   and (not loop_only or row.behavior == "Loop")
                   and (not one_shot_only or row.behavior == "One-shot")
                   and (favourites is None or stem in favourites)
                   and (family is None or family_of(stem) == family))
        matches += int(matched)
        if matched or stem == selected:
            rows.append(row)
    rows.sort(key=lambda row: row.stem.casefold())
    raise_if_cancelled(stop_event)
    result = (no_effect, *rows)
    if result == previous_rows:
        result = previous_rows
    return result, {row.stem: index for index, row in enumerate(result)}, matches
