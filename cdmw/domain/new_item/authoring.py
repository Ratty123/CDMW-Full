"""Typed optional authoring choices. None inherits; an empty tuple clears."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SocketSlot:
    material_key: int
    amount: int
    extra: int = 0

    def record(self):
        return self.material_key, self.amount, self.extra


@dataclass(frozen=True, slots=True)
class EquipmentBonus:
    buff_key: int
    parameter: int


@dataclass(frozen=True, slots=True)
class LevelBonuses:
    level: int
    bonuses: tuple[EquipmentBonus, ...] = ()


@dataclass(frozen=True, slots=True)
class RecipeInput:
    key: int
    quantity: int
    enhancement: int = 0
    kind: str = "item"
    coupon_quantity: int = 0


@dataclass(frozen=True, slots=True)
class RecipeOutput:
    reward_index: int
    entry_index: int
    quantity: int
    enhancement: int
    maximum: int | None = None


@dataclass(frozen=True, slots=True)
class RecipeOverride:
    recipe_key: int
    inputs: tuple[RecipeInput, ...] | None = None
    tool_key: int | None = None
    knowledge_key: int | None = None
    outputs: tuple[RecipeOutput, ...] | None = None


@dataclass(frozen=True, slots=True)
class RewardAcquisition:
    consumer_item_key: int
    use_index: int
    entry_index: int
    mode: str = "insert"
    minimum: int = 1
    maximum: int = 1
    enhancement: int = -1
    weight: int | None = None


@dataclass(frozen=True, slots=True)
class DyeAssignment:
    target_submesh: str
    source_submesh: str
    slots: tuple[int, int, int]
    mask_path: str = ""


@dataclass(frozen=True, slots=True)
class VariantAppearance:
    prefab_path: str
    model_path: str
    custom_model: bool = False
    material_route: str = "plain_pbr"
    keep_template_physics: bool = False
    dyes: tuple[DyeAssignment, ...] | None = None
    glow_parts: tuple[str, ...] = ()
    glow_color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    glow_intensity: float = 4.0

    def glow_choice(self):
        from cdmw.domain.new_item.spec import GlowChoice
        return GlowChoice(self.glow_parts, self.glow_color, self.glow_intensity) if self.glow_parts else None

    @property
    def identity(self):
        return self.prefab_path.replace("\\", "/").casefold(), self.model_path.replace("\\", "/").casefold()
