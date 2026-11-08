"""Experimental equipment rules, independent of material translucency."""
from dataclasses import dataclass, field
import re

from cdmw.domain.part_names import bare_part_name

SKIN_RECEIVERS = frozenset({'Nude'})
HAIR_RECEIVERS = frozenset({'Hair', 'LongHair', 'Hair_Tail', 'Beard'})
_RECEIVER = re.compile(r"[A-Za-z0-9_]{1,64}\Z")
_MAX_RECEIVERS = 128


@dataclass(frozen=True, slots=True)
class BodyVisibilityChoice:
    keep_skin: bool = False
    keep_hair: bool = False
    # Other shrink receivers (clothing layers such as Lowerbody) this equipment
    # should stop cutting. Names come from the item's own shrink rule.
    keep_receivers: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self):
        if isinstance(self.keep_receivers, (tuple, list, set)):
            try:
                object.__setattr__(self, 'keep_receivers', frozenset(self.keep_receivers))
            except TypeError:
                pass  # validate() reports the unhashable value.

    @property
    def wanted(self) -> bool:
        return self.keep_skin or self.keep_hair or bool(self.keep_receivers)

    def validate(self) -> None:
        if type(self.keep_skin) is not bool or type(self.keep_hair) is not bool:
            raise ValueError("Underlying skin and hair choices must be booleans.")
        if (not isinstance(self.keep_receivers, frozenset) or len(self.keep_receivers) > _MAX_RECEIVERS
                or any(type(name) is not str or not _RECEIVER.fullmatch(name) for name in self.keep_receivers)):
            raise ValueError("Kept underlying layers must be shrink receiver names.")

    @property
    def receiver_tags(self) -> frozenset[str]:
        return ((SKIN_RECEIVERS if self.keep_skin else frozenset())
                | (HAIR_RECEIVERS if self.keep_hair else frozenset())
                | self.keep_receivers)

    @property
    def hidden_parts(self) -> frozenset[str]:
        # A restored head needs its eyes and mouth as well. Helmet-owned item hair
        # and unrelated clothing remain governed by their original rules; clothing
        # receivers have no known whole-part hide counterpart. Current part names; rules
        # from before the October 2026 update say `CD_Hair`, which `hides_part` accepts.
        skin = {'Nude', 'Head', 'Tooth', 'EyeRight', 'EyeLeft',
                'Eyelashes', 'Eyebrows'} if self.keep_skin else set()
        hair = {'Hair', 'Hair_Tail', 'Hair_UpTail', 'Hair_Acc',
                'Nude_Hair', 'Beard', 'Beard_Long'} if self.keep_hair else set()
        return frozenset(skin | hair)

    def hides_part(self, part_name: str) -> bool:
        """Whether a Hide rule's `TargetPart` is one this choice keeps visible, in either naming."""
        return bare_part_name(part_name) in self.hidden_parts

    @staticmethod
    def combine(choices) -> "BodyVisibilityChoice":
        choices = tuple(choices)
        return BodyVisibilityChoice(any(c.keep_skin for c in choices), any(c.keep_hair for c in choices),
                                    frozenset().union(*(c.keep_receivers for c in choices)))
