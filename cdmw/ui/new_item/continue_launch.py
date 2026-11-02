"""Turn a Drafts & Mods item package into what Create New Item opens. No Qt here."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from cdmw.services.item_package_saved_work import read_item_package_source
from cdmw.ui.new_item.draft_file import decode_draft
from cdmw.ui.new_item.state import NewItemDraft, draft_from_spec


@dataclass(frozen=True)
class ItemPackageLaunch:
    """A package's draft and finished models, ready for ``restore_continued_item``."""

    package_path: Path
    identity: str
    title: str
    draft: NewItemDraft
    model: object = None
    variant_models: Mapping[tuple, object] = field(default_factory=dict)
    icon_data: bytes | None = None
    #: a rebuilt draft's stat and buy-price edits, laid onto the template's ladder later
    stat_edits: tuple = ()
    buy_price_edits: tuple = ()
    #: True when the draft is the one kept at export, False when rebuilt from the recipe
    from_saved_draft: bool = False


def prepare_item_package_launch(draft_root, row_id: str, *, stop_event=None) -> ItemPackageLaunch:
    """Read the package and its kept draft, or rebuild a draft from its recipe."""

    source = read_item_package_source(draft_root, row_id, stop_event=stop_event)
    spec = source.spec
    if source.draft_bytes is not None:
        draft = decode_draft(source.draft_bytes)
        if draft.template_key != spec.template_key:
            raise ValueError("The kept settings belong to another template than the package. Remove the "
                             "package from the list and add it again to continue from the package itself.")
        return ItemPackageLaunch(source.package_path, source.identity, source.title, draft, source.model,
                                 dict(source.variant_models), source.icon_data, from_saved_draft=True)
    return ItemPackageLaunch(source.package_path, source.identity, source.title, draft_from_spec(spec),
                             source.model, dict(source.variant_models), source.icon_data,
                             tuple(spec.stat_edits), tuple(spec.buy_price_edits))


__all__ = ["ItemPackageLaunch", "prepare_item_package_launch"]
