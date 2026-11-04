"""What each template model binding becomes in the exported item.

No Qt and no display text here: the Model & Placement component list and the
output summary read these facts and word them.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ComponentRole(str, Enum):
    """The ItemInfo prefab type a binding's part is listed under."""

    #: data type 0: the model the wearer equips
    WORN = "worn"
    #: data type 3: the model drawn when the item lies on the ground
    DROPPED = "dropped"
    #: another or unknown data type
    OTHER = "other"


class ComponentSource(str, Enum):
    """The model a component keeps, whether or not it is included in the export."""

    TEMPLATE = "template"
    IMPORTED = "imported"


#: ItemInfo `_prefabDataList` data types whose role is confirmed in shipped data.
ROLE_BY_DATA_TYPE = {0: ComponentRole.WORN, 3: ComponentRole.DROPPED}


@dataclass(frozen=True, slots=True)
class ComponentRow:
    identity: tuple[str, str]
    prefab_path: str
    model_path: str
    part_stem: str
    role: ComponentRole
    #: the prefab's SkinnedMeshComponent name, e.g. Upperbody; "" when unread
    component_name: str
    #: the component's `_shrinkTag`; "" when it has none (it cuts no body)
    shrink_tag: str
    source: ComponentSource
    #: the imported file's name, when known
    source_name: str = ""
    keep_skin: bool = False
    keep_hair: bool = False
    selected: bool = False
    #: False: the export writes hidden geometry for it; its source is kept for re-including
    included: bool = True
    #: False for item packages (.cdmw): they cannot carry the shared cut rules
    cut_rules_editable: bool = True

    @property
    def cuts_body(self) -> bool:
        """Whether the template gives this component a geometry-cut rule at all."""
        return bool(self.shrink_tag)

    @property
    def body_kept(self) -> bool:
        """Whether the export stops this component cutting the body underneath."""
        return self.body_kept_automatically if not self.included else self.cuts_body and self.keep_skin

    @property
    def body_kept_automatically(self) -> bool:
        """A left-out component's cut is dropped whatever its own choice, where the output allows it."""
        return self.cuts_body and not self.included and self.cut_rules_editable

    @property
    def model_file(self) -> str:
        return self.model_path.replace("\\", "/").rsplit("/", 1)[-1]


__all__ = ["ComponentRole", "ComponentRow", "ComponentSource", "ROLE_BY_DATA_TYPE"]
