"""Archive browser Item Finder catalog helper logic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Dict, List, Tuple

from cdmw.services.archive_workflow_service import (
    archive_entry_item_name_match,
    archive_entry_model_base_key_matches,
)
from cdmw.models import ArchiveEntry


class ArchiveAssetCatalogMixin:
    """Item Finder data helpers owned by Archive Browser."""

    def _archive_entry_model_base_key_matches(self, entry: ArchiveEntry) -> Tuple[Tuple[str, str], ...]:
        return archive_entry_model_base_key_matches(entry)

    def _archive_entry_item_name_match(self, entry: ArchiveEntry) -> Tuple[str, str, str]:
        return archive_entry_item_name_match(
            entry,
            item_display_names=self.archive_item_display_names,
            item_exact_display_names=self.archive_item_exact_display_names,
            item_related_display_names=self.archive_item_related_display_names,
        )

    def _archive_asset_catalog_table_evidence_labels(self, row: Mapping[str, object]) -> Tuple[str, ...]:
        raw_values = row.get("table_evidence")
        if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes, bytearray)):
            return ()
        labels: List[str] = []
        seen: set[str] = set()
        for value in raw_values:
            label = ""
            target = ""
            if isinstance(value, Mapping):
                label = str(value.get("label", "") or "").strip()
                if not label:
                    table = str(value.get("source_table", "") or "").strip()
                    field = str(value.get("source_field", "") or "").strip()
                    label = f"{table}.{field}" if table and field else table or field
                target = str(value.get("target", "") or "").strip()
            else:
                label = str(value or "").strip()
            if label and label not in seen:
                labels.append(label)
                seen.add(label)
            if target and target not in seen:
                labels.append(target)
                seen.add(target)
        return tuple(labels)

    def _archive_asset_catalog_text(self, row: Mapping[str, object]) -> str:
        values: List[str] = []
        for key in (
            "display_name",
            "internal_name",
            "category",
            "group",
            "evidence",
            "category_evidence",
            "scope_filter",
        ):
            value = row.get(key)
            if value:
                values.append(str(value))
        values.extend(self._archive_asset_catalog_table_evidence_labels(row))
        for key in (
            "pac_files",
            "model_stems",
            "icon_paths",
            "localized_names",
            "compatibility_tags",
            "material_tags",
            "material_evidence",
        ):
            raw_values = row.get(key)
            if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes, bytearray)):
                values.extend(str(value) for value in raw_values if value)
        return " ".join(values).lower()

    def _archive_asset_catalog_categories(self) -> Tuple[str, ...]:
        categories = {
            str(row.get("category", "") or "").strip()
            for row in self.archive_item_asset_catalog
            if str(row.get("category", "") or "").strip()
        }
        preferred = (
            "Weapon",
            "Armor",
            "Accessory",
            "Mount / Pet",
            "Material",
            "Consumable",
            "Crafting / Recipe",
            "Tool",
            "Character Customization",
            "Gimmick / Interactive",
            "Housing / Prop",
            "Quest / Document",
            "Progression / Reward",
            "Item",
        )
        ordered = [category for category in preferred if category in categories]
        ordered.extend(sorted(category for category in categories if category not in set(preferred)))
        return tuple(ordered)

    def _archive_asset_catalog_group_sort_key(self, category: str, group: str) -> Tuple[int, str]:
        preferred_groups = {
            "Weapon": (
                "Sword",
                "Dagger / Rapier",
                "Axe / Mace / Hammer",
                "Polearm / Spear",
                "Bow / Crossbow",
                "Firearm",
                "Fist / Martial",
                "Wand / Fan",
                "Shield",
                "Other Weapon",
            ),
            "Armor": (
                "Head",
                "Face",
                "Body",
                "Hands",
                "Legs",
                "Feet",
                "Back / Cloak",
                "Other Armor",
            ),
            "Accessory": (
                "Necklace",
                "Earrings",
                "Ring",
                "Amulet / Charm",
                "Belt / Band",
                "Other Accessory",
            ),
            "Tool": (
                "Backpack / Pack",
                "Gathering Tool",
                "Light / Lantern",
                "Fishing",
                "Throwable / Utility",
                "Hand Tool",
                "Other Tool",
            ),
            "Character Customization": (
                "Hair",
                "Body / Appearance",
            ),
            "Gimmick / Interactive": (
                "Gimmick",
                "Machine Part",
            ),
            "Housing / Prop": (
                "Furniture",
                "Decor",
                "Collection Prop",
                "Container",
            ),
            "Quest / Document": (
                "Quest",
                "Key / Permit",
                "Book / Diary",
                "Map / Treasure",
                "Clue / Report",
                "Flag / Marker",
                "Document",
                "Token / Seal",
            ),
        }
        group_order = {name: index for index, name in enumerate(preferred_groups.get(category, ()))}
        return group_order.get(group, 999), group.casefold()

    def _archive_asset_catalog_group_choices(self, category: str = "") -> Tuple[str, ...]:
        normalized_category = str(category or "").strip()
        groups = {
            str(row.get("group", "") or "").strip()
            for row in self.archive_item_asset_catalog
            if str(row.get("group", "") or "").strip()
            and (not normalized_category or str(row.get("category", "") or "").strip() == normalized_category)
        }
        return tuple(sorted(groups, key=lambda group: self._archive_asset_catalog_group_sort_key(normalized_category, group)))

__all__ = ["ArchiveAssetCatalogMixin"]
