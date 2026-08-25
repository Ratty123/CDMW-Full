"""New Item Studio domain: what a new item is, what makes one valid, and how ids
and stems are allocated. Pure rules; the archive facts they check against are
handed in as a snapshot (:class:`NewItemContext`) by the service that owns the
scan."""

from cdmw.domain.new_item.allocation import (
    DEFAULT_ITEM_KEY_RANGE,
    AllocationError,
    allocate_item_key,
    derive_family_stems,
    is_conventional_localization_key,
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
from cdmw.domain.new_item.placement import (
    BODY_PLACEMENT_FRAME,
    HELD_PLACEMENT_FRAME,
    UNKNOWN_PLACEMENT_FRAME,
    equipment_placement_frame,
)
from cdmw.domain.new_item.spec import (
    BuyPriceEdit,
    IconSource,
    ItemGroupsChoice,
    MaterialRoute,
    ModelSource,
    EffectLook,
    NewItemSpec,
    Placement,
    PlacementKind,
    UNLIMITED_STOCK,
    PriceEdit,
    SheathedModel,
    StatEdit,
)

__all__ = [
    "AllocationError",
    "BuyPriceEdit",
    "BODY_PLACEMENT_FRAME",
    "DEFAULT_ITEM_KEY_RANGE",
    "IconSource",
    "HELD_PLACEMENT_FRAME",
    "ItemGroupsChoice",
    "LOCALIZATION_LANGUAGES",
    "MaterialRoute",
    "ModelSource",
    "NewItemContext",
    "EffectLook",
    "NewItemSpec",
    "Placement",
    "PlacementKind",
    "UNLIMITED_STOCK",
    "PriceEdit",
    "SheathedModel",
    "StatEdit",
    "TemplateFacts",
    "TemplateLevelFacts",
    "UNKNOWN_PLACEMENT_FRAME",
    "ValidationIssue",
    "allocate_item_key",
    "derive_family_stems",
    "equipment_placement_frame",
    "is_conventional_localization_key",
    "localization_keys",
    "suggest_stem",
    "validate_against_context",
    "validate_spec",
]
