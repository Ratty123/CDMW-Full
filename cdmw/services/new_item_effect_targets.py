"""Read-only compatibility checks for New Item visual-effect prefab targets.

The UI and the planner must agree on exactly which source prefabs receive an
``EffectComponent``. This module owns that enumeration and dry-runs the same
component graft the planner later performs; it never writes archives or output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple

from cdmw.core.item_model_family import FamilyPart, ItemModelFamily
from cdmw.core.prefab_component_graft import PrefabEditError, encode_transform, graft_prefab_component
from cdmw.domain.new_item.spec import ModelSource, NewItemSpec, SheathedModel
from cdmw.services.new_item_snapshot import EFFECT_DONOR_PATH, EFFECT_DONOR_PREFAB, NewItemSnapshot


@dataclass(frozen=True, slots=True)
class EffectTargetCompatibility:
    """Whether every prefab the plan would own can accept the visual effect."""

    supported: bool
    target_prefabs: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if self.supported:
            count = len(self.target_prefabs)
            return f"Available for this template ({count} prefab{'s' if count != 1 else ''})."
        return self.errors[0] if self.errors else "This template has no compatible visual prefab."


def is_sheathed_family_part(part: FamilyPart) -> bool:
    """Whether a borrowed part is one the planner can clone as an owned sheath."""

    if part.record is None or not part.pac_path:
        return False
    return any(re.search(r"_in(_|$)", str(item.name or ""), re.I) for item in part.record.parts) or bool(
        re.search(r"_in(_|$)", str(part.stem or ""), re.I)
    )


def effect_target_source_paths(
    family: ItemModelFamily,
    *,
    model_source: ModelSource = ModelSource.TEMPLATE,
    sheathed_model: SheathedModel = SheathedModel.TEMPLATE,
) -> Tuple[str, ...]:
    """The source prefabs a plan will clone and own before adding an effect."""

    paths = [item.path for item in family.files_for("prefab") if item.exists]
    if model_source is ModelSource.IMPORTED and sheathed_model is SheathedModel.OWN_MODEL:
        for part in family.borrowed_parts:
            if not is_sheathed_family_part(part):
                continue
            paths.append(part.prefab_path)
    return tuple(dict.fromkeys(path for path in paths if path))


def inspect_effect_targets(snapshot: NewItemSnapshot, spec: NewItemSpec) -> EffectTargetCompatibility:
    """Dry-run the real component graft against every prefab the spec will own."""

    if spec.effect is None:
        return EffectTargetCompatibility(True, ())
    if not snapshot.has_entry(EFFECT_DONOR_PREFAB):
        return EffectTargetCompatibility(
            False,
            (),
            (f"The archives have no visual-effect donor prefab: {EFFECT_DONOR_PREFAB}.",),
        )
    try:
        family = snapshot.family(int(spec.template_key))
    except Exception as exc:  # noqa: BLE001 - the exact family failure belongs in the result
        return EffectTargetCompatibility(False, (), (f"The template's model family could not be read: {exc}",))
    targets = effect_target_source_paths(
        family,
        model_source=spec.model_source,
        sheathed_model=spec.sheathed_model,
    )
    if not targets:
        return EffectTargetCompatibility(
            False,
            (),
            ("This template owns no clonable prefab that can carry a visual effect.",),
        )
    try:
        donor = snapshot.payload(EFFECT_DONOR_PREFAB)
    except Exception as exc:  # noqa: BLE001 - preflight reports the archive read failure
        return EffectTargetCompatibility(False, targets, (f"The visual-effect donor prefab could not be read: {exc}",))
    errors: list[str] = []
    for path in targets:
        try:
            source = snapshot.payload(path)
            graft_prefab_component(
                source,
                donor,
                component_type="EffectComponent",
                path_replacements={EFFECT_DONOR_PATH: str(spec.effect)},
                offset_transform=encode_transform(),
            )
        except (PrefabEditError, KeyError, OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{path} cannot carry the visual effect: {exc}")
    return EffectTargetCompatibility(not errors, targets, tuple(errors))


__all__ = [
    "EffectTargetCompatibility",
    "effect_target_source_paths",
    "inspect_effect_targets",
    "is_sheathed_family_part",
]
