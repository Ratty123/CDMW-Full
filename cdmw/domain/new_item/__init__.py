"""New Item Studio domain: what a new item is, what makes one valid, and how ids
and stems are allocated. Pure rules; the archive facts they check against are
handed in as a snapshot (:class:`NewItemContext`) by the service that owns the
scan."""

from cdmw.domain.new_item.allocation import (
    DEFAULT_ITEM_KEY_RANGE,
    AllocationError,
    allocate_item_key,
    derive_family_stems,
    localization_keys,
    suggest_stem,
)
from cdmw.domain.new_item.rules import (
    LOCALIZATION_LANGUAGES,
    NewItemContext,
    TemplateFacts,
    TemplateLevelFacts,
    ValidationIssue,
    validate_against_context,
    validate_spec,
)
from cdmw.domain.new_item.spec import (
    BuyPriceEdit,
    IconSource,
    ItemGroupsChoice,
    ModelSource,
    NewItemSpec,
    Placement,
    PlacementKind,
    PriceEdit,
    StatEdit,
)

__all__ = [
    "AllocationError",
    "BuyPriceEdit",
    "DEFAULT_ITEM_KEY_RANGE",
    "IconSource",
    "ItemGroupsChoice",
    "LOCALIZATION_LANGUAGES",
    "ModelSource",
    "NewItemContext",
    "NewItemSpec",
    "Placement",
    "PlacementKind",
    "PriceEdit",
    "StatEdit",
    "TemplateFacts",
    "TemplateLevelFacts",
    "ValidationIssue",
    "allocate_item_key",
    "derive_family_stems",
    "localization_keys",
    "suggest_stem",
    "validate_against_context",
    "validate_spec",
]
