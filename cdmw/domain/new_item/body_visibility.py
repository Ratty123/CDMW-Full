"""Experimental equipment rules, independent of material translucency."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BodyVisibilityChoice:
    keep_skin: bool = False
    keep_hair: bool = False

    @property
    def wanted(self) -> bool:
        return self.keep_skin or self.keep_hair

    def validate(self) -> None:
        if type(self.keep_skin) is not bool or type(self.keep_hair) is not bool:
            raise ValueError("Underlying skin and hair choices must be booleans.")

    @property
    def receiver_tags(self) -> frozenset[str]:
        return frozenset(({'Nude'} if self.keep_skin else set()) |
                         ({'Hair', 'LongHair', 'Hair_Tail', 'Beard'} if self.keep_hair else set()))

    @property
    def hidden_parts(self) -> frozenset[str]:
        # A restored head needs its eyes and mouth as well. Helmet-owned item hair
        # and unrelated clothing remain governed by their original rules.
        skin = {'CD_Nude', 'CD_Head', 'CD_Tooth', 'CD_EyeRight', 'CD_EyeLeft',
                'CD_Eyelashes', 'CD_Eyebrows'} if self.keep_skin else set()
        hair = {'CD_Hair', 'CD_Hair_Tail', 'CD_Hair_UpTail', 'CD_Hair_Acc',
                'CD_Nude_Hair', 'CD_Beard', 'CD_Beard_Long'} if self.keep_hair else set()
        return frozenset(skin | hair)
