"""Virtual effect rows and cached searchable metadata for the library."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt
from PySide6.QtWidgets import QWidget
from cdmw.services.effect_catalogue import EffectFacts

CATEGORY_RULES = (
    ("Fire", ("fire", "flame", "ember", "burn")),
    ("Frost", ("ice", "frost", "frozen", "freeze")),
    ("Lightning", ("lightning", "electric", "shock", "thunder")),
    ("Glow", ("glow", "emissive")),
    ("Aura", ("aura",)),
    ("Trail", ("trail",)),
    ("Sparks", ("spark",)),
    ("Smoke", ("smoke", "fog", "mist")),
    ("Dust", ("dust", "sand")),
    ("Water", ("water", "splash", "puddle", "rain")),
    ("Blood", ("blood", "bleed")),
    ("Explosion", ("explosion", "explode", "blast", "_exp_")),
    ("Debris", ("debris", "breakable", "fragment")),
    ("Dark", ("dark", "shadow", "antumbra")),
    ("Environment", ("wind", "leaf", "leaves", "snow", "weather")),
)

CATEGORY_GLYPHS = {
    "Fire": "♨",
    "Frost": "❄",
    "Lightning": "ϟ",
    "Glow": "◉",
    "Aura": "◎",
    "Trail": "↝",
    "Sparks": "✦",
    "Other": "◇",
}

def effect_category(stem: str, authoring_name: str = "") -> str:
    """Deterministic first-match category using the product's fixed token rules."""

    text = f"{stem} {authoring_name}".casefold()
    for category, tokens in CATEGORY_RULES:
        if any(token in text for token in tokens):
            return category
    return "Other"


def effect_tags(stem: str, name: str = "", facts: Optional[EffectFacts] = None) -> tuple[str, ...]:
    text = f"{stem} {name} {facts.search_text() if facts else ''}".casefold()
    return tuple(category for category, tokens in CATEGORY_RULES if any(token in text for token in tokens)) or ("Other",)


def effect_display_label(stem: str, authoring_name: str = "") -> str:
    """Return a neutral, stem-authoritative label with stable token casing."""

    source = str(stem or authoring_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    source = re.sub(r"\.(?:level\.)?effect$", "", source, flags=re.I)
    source = re.sub(r"\.(?:pae|paem|pafx)$", "", source, flags=re.I)
    sections = source.split("__", 1)
    acronyms = {"aoe", "cc", "dds", "lod", "npc", "pvp", "uv", "vfx"}

    def words(section: str, *, first: bool) -> str:
        separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", section)
        tokens = re.findall(r"[A-Za-z]+\d+[A-Za-z]*|\d+[A-Za-z]*|[A-Za-z]+", separated)
        while tokens and tokens[0].casefold() in {"fx", "pafx", "vfx", "effect", "cdem", "cdfx"}:
            tokens.pop(0)
        if first and tokens and tokens[0].casefold() == "action":
            tokens.pop(0)
        rendered = []
        for token in tokens:
            match = re.fullmatch(r"([A-Za-z]+)(\d+[A-Za-z]*)", token)
            if match:
                head, tail = match.groups()
                if len(head) <= 2 or head.casefold() in acronyms or (head.isupper() and len(head) <= 4):
                    rendered.append((head.upper() if len(head) <= 4 else head.capitalize()) + tail)
                else:
                    rendered.extend((head.capitalize(), tail.casefold()))
            elif re.fullmatch(r"\d+[A-Za-z]+", token):
                rendered.append(token.casefold())
            elif token.casefold() in acronyms or (token.isupper() and len(token) <= 4):
                rendered.append(token.upper())
            else:
                rendered.append(token.capitalize())
        return " ".join(rendered)

    family = words(sections[0], first=True)
    variant = words(sections[1], first=False) if len(sections) > 1 else ""
    if family and variant:
        return f"{family} · {variant}"
    return family or variant or str(stem or "No effect")


@dataclass(frozen=True, slots=True)
class EffectLibraryRow:
    stem: str
    label: str
    category: str
    behavior: str
    facts: Optional[EffectFacts] = None
    tags: tuple[str, ...] = ()
    search_text: str = ""

    @classmethod
    def from_stem(cls, stem: str, facts: Optional[EffectFacts]) -> "EffectLibraryRow":
        name = facts.name if facts is not None else ""
        loops = (
            bool(facts.loops) or (bool(facts.walk_note) and "loop" in stem.casefold())
            if facts is not None
            else "loop" in stem.casefold()
        )
        behavior = "Loop" if loops else "One-shot"
        return cls(
            stem=stem,
            label=effect_display_label(stem, name),
            category=effect_category(stem, name),
            behavior=behavior,
            facts=facts,
            tags=effect_tags(stem, name, facts),
            search_text=" ".join((stem, effect_display_label(stem, name), facts.search_text() if facts else "")).casefold(),
        )


def _unique_effect_labels(stems: tuple[str, ...]) -> dict[str, str]:
    """Disambiguate the rare normalized collision with the shortest stem suffix."""

    labels = {stem: effect_display_label(stem) for stem in stems}
    groups: dict[str, list[str]] = {}
    for stem, label in labels.items():
        groups.setdefault(label.casefold(), []).append(stem)
    for grouped in groups.values():
        if len(grouped) < 2:
            continue
        parts = {stem: tuple(token for token in re.split(r"[_/]+", stem) if token) for stem in grouped}
        qualifiers: dict[str, str] = {}
        maximum = max((len(value) for value in parts.values()), default=1)
        for depth in range(1, maximum + 1):
            candidates = {stem: "_".join(value[-depth:]) for stem, value in parts.items()}
            if len({value.casefold() for value in candidates.values()}) == len(grouped):
                qualifiers = candidates
                break
        rendered = {stem: effect_display_label(qualifiers.get(stem, stem)) for stem in grouped}
        if len({value.casefold() for value in rendered.values()}) != len(grouped):
            namespaces = {stem: (parts[stem][0].upper() if parts[stem] else stem) for stem in grouped}
            if len({value.casefold() for value in namespaces.values()}) == len(grouped):
                rendered = namespaces
            else:
                rendered = {stem: qualifiers.get(stem, stem).replace("_", " ") for stem in grouped}
        for stem in grouped:
            labels[stem] = f"{labels[stem]} · {rendered[stem]}"
    return labels


def _effect_dimensions(facts: Optional[EffectFacts]) -> str:
    if facts is None:
        return "—"
    values = (0.0 if abs(float(value)) < 1e-12 else float(value) for value in facts.size)
    return "×".join(f"{value:.3g}" for value in values)


class EffectLibraryModel(QAbstractTableModel):
    COLUMN_HEADERS = ("", "Effect", "Type", "Size")
    StemRole = int(Qt.ItemDataRole.UserRole) + 1
    LabelRole = StemRole + 1
    CategoryRole = StemRole + 2
    BehaviorRole = StemRole + 3
    GlyphRole = StemRole + 4
    DimensionsRole = StemRole + 5

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: tuple[EffectLibraryRow, ...] = (
            EffectLibraryRow("", "No effect", "Other", "Off"),
        )
        self._thumbnails = {}

    def set_thumbnail(self, stem, icon):
        self._thumbnails[stem] = icon
        index = self.index_for_stem(stem)
        if index.isValid():
            index = self.index(index.row(), 0)
            self.dataChanged.emit(index, index, [int(Qt.ItemDataRole.DecorationRole), int(Qt.ItemDataRole.DisplayRole)])

    def replace_rows(self, rows: tuple[EffectLibraryRow, ...]) -> None:
        if rows == self._rows:
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self.COLUMN_HEADERS)

    def headerData(  # noqa: N802 - Qt override
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ):
        if orientation != Qt.Orientation.Horizontal or not 0 <= int(section) < len(self.COLUMN_HEADERS):
            return None
        if role == int(Qt.ItemDataRole.DisplayRole):
            return self.COLUMN_HEADERS[int(section)]
        if role == int(Qt.ItemDataRole.TextAlignmentRole):
            return (
                Qt.AlignmentFlag.AlignCenter
                if int(section) == 0
                else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        return None

    def row(self, index: int) -> Optional[EffectLibraryRow]:
        return self._rows[index] if 0 <= int(index) < len(self._rows) else None

    def index_for_stem(self, stem: str) -> QModelIndex:
        wanted = str(stem or "")
        for row, item in enumerate(self._rows):
            if item.stem == wanted:
                return self.index(row, 1)
        return QModelIndex()

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):  # noqa: D401
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        item = self._rows[index.row()]
        dimensions = _effect_dimensions(item.facts)
        if role == int(Qt.ItemDataRole.DecorationRole) and index.column() == 0:
            return self._thumbnails.get(item.stem)
        if role == int(Qt.ItemDataRole.DisplayRole):
            if index.column() == 0 and item.stem in self._thumbnails:
                return ''
            return (
                CATEGORY_GLYPHS.get(item.category, CATEGORY_GLYPHS["Other"]),
                item.label,
                item.behavior,
                dimensions,
            )[index.column()]
        if role == int(Qt.ItemDataRole.ToolTipRole):
            if not item.stem:
                return "Clear the visual effect and all placement/look tuning."
            details = [item.stem, ', '.join(item.tags)]
            if item.facts is not None:
                for path in getattr(item.facts, 'missing_dependencies', ()):
                    details.append('Missing: ' + path)
                details.extend(getattr(item.facts, 'dependency_notes', ()))
            return '\n'.join(details)
        if role == int(Qt.ItemDataRole.AccessibleTextRole):
            return f"{item.label}; {item.stem or 'no effect'}; {item.behavior}"
        if role == int(Qt.ItemDataRole.TextAlignmentRole):
            return (
                Qt.AlignmentFlag.AlignCenter
                if index.column() == 0
                else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        if role == int(Qt.ItemDataRole.SizeHintRole):
            # Metadata columns use the delegate's font-aware width so translated
            # types and dimensions do not clip inside a fixed pixel allocation.
            return QSize((24, 170)[index.column()], 24) if index.column() < 2 else None
        if role == self.StemRole:
            return item.stem
        if role == self.LabelRole:
            return item.label
        if role == self.CategoryRole:
            return item.category
        if role == self.BehaviorRole:
            return item.behavior
        if role == self.GlyphRole:
            return CATEGORY_GLYPHS.get(item.category, CATEGORY_GLYPHS["Other"])
        if role == self.DimensionsRole:
            return dimensions
        return None
