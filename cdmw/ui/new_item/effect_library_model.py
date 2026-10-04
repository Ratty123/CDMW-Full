"""Virtual effect rows and cached searchable metadata for the library."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt
from PySide6.QtWidgets import QWidget
from cdmw.services.effect_catalogue import EffectFacts
from cdmw.services.active_ui_translation import translate_active_ui_text

CATEGORY_RULES = (
    ("Fire", ("fire", "flame", "flames", "ember", "embers", "burn", "burning", "fireball", "flamethrower", "lava")),
    ("Frost", ("ice", "frost", "frozen", "freeze", "icicle")),
    ("Lightning", ("lightning", "electric", "electricity", "thunder")),
    ("Poison", ("poison", "toxic", "venom")),
    ("Healing", ("heal", "healing")),
    ("Glow", ("glow", "emissive", "light", "flare")),
    ("Aura", ("aura",)),
    ("Trail", ("trail", "ribbon", "slash")),
    ("Sparks", ("spark", "sparks", "fireworks")),
    ("Smoke", ("smoke", "fog", "mist", "steam")),
    ("Dust", ("dust", "sand", "dirt", "sandstorm")),
    ("Water", ("water", "splash", "puddle", "rain", "waterfall", "fountain", "underwater", "bubble", "bubbles", "foam", "ripple")),
    ("Blood", ("blood", "bleed", "bleeding")),
    ("Explosion", ("explosion", "explode", "blast", "bomb", "detonation")),
    ("Debris", ("debris", "breakable", "fragment", "fragments", "rubble")),
    ("Beam", ("beam", "laser")),
    ("Projectile", ("projectile", "arrow", "bullet")),
    ("Decal", ("decal", "footprint")),
    ("Portal", ("portal", "teleport")),
    ("Distortion", ("distortion", "distort", "refraction")),
    ("Dark", ("dark", "shadow", "antumbra")),
    ("Wildlife", ("bug", "bugs", "butterfly", "firefly", "dragonfly", "bee", "beetle", "swallowtail", "fritillary", "crow", "bird")),
    ("Environment", ("wind", "leaf", "leaves", "snow", "weather", "tornado", "grass", "petal")),
    ("Impact", ("hit", "impact", "shock", "shockwave", "smash", "break")),
)

# Split only reviewed compounds. Never scan arbitrary substrings: firefly is not
# fire, medicine/juice are not ice, and training is not rain. Artist/character
# names and ambiguous source codes (ATT, EXP, CC, TPL) remain intact.
_COMPOUND_WORDS = {
    "groundhit": ("ground", "hit"), "groundhitfront": ("ground", "hit", "front"),
    "charactereffect": ("character", "effect"), "charactermesh": ("character", "mesh"),
    "auraburst": ("aura", "burst"), "bloodhit": ("blood", "hit"),
    "swordlong": ("long", "sword"), "swordtrail": ("sword", "trail"),
    "swordon": ("sword", "on"), "swordoff": ("sword", "off"),
    "firesword": ("fire", "sword"), "firearrow": ("fire", "arrow"),
    "firebash": ("fire", "bash"), "bluefireheavy": ("blue", "fire", "heavy"),
    "lightningheavy": ("lightning", "heavy"), "iceheavy": ("ice", "heavy"),
    "weaponr": ("right", "weapon"), "weaponl": ("left", "weapon"),
    "swingr": ("right", "swing"), "swingl": ("left", "swing"),
    "shieldmetal": ("metal", "shield"), "shieldwood": ("wood", "shield"),
    "weapondecal": ("weapon", "decal"), "dropdecal": ("drop", "decal"),
    "fallingdebris": ("falling", "debris"), "bashtrail": ("bash", "trail"),
    "slashline": ("slash", "line"), "halfcircle": ("half", "circle"),
    "lensflare": ("lens", "flare"), "commonlight": ("common", "light"),
    "eyelight": ("eye", "light"), "tornadocloud": ("tornado", "cloud"),
    "sandfall": ("sand", "fall"), "lavafall": ("lava", "fall"),
    "waterfallcol": ("waterfall", "col"), "waterplant": ("water", "plant"),
}
_ACRONYMS = frozenset({"aoe", "att", "bg", "cc", "col", "dds", "exp", "gpu", "hp", "lod", "mp", "npc", "pc", "pvp", "rgb", "sp", "taa", "tpl", "uv", "vfx"})
_PREFIXES = frozenset({"fx", "pafx", "vfx", "effect", "cdem", "cdfx"})
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NAME_TOKENS = re.compile(r"[A-Za-z]+\d+[A-Za-z]*|\d+[A-Za-z]*|[A-Za-z]+")


def _effect_leaf(value: str) -> str:
    source = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(?:(?:action|level)\.)?effect$|\.(?:pae|paem|pafx|dds|pam|pac|parg|pasg)$", "", source, flags=re.I)


def _name_tokens(value: str) -> tuple[str, ...]:
    return tuple(_NAME_TOKENS.findall(_CAMEL_BOUNDARY.sub("_", value)))


def _semantic_words(value: str) -> frozenset[str]:
    words = set()
    for token in _name_tokens(_effect_leaf(value)):
        head = re.match(r"[A-Za-z]+", token)
        if head:
            word = head.group().casefold()
            words.update(_COMPOUND_WORDS.get(word, (word,)))
    return frozenset(words)


def _categories(values) -> tuple[str, ...]:
    words = frozenset(word for value in values for word in _semantic_words(value))
    return tuple(category for category, tokens in CATEGORY_RULES if words.intersection(tokens))


def _effect_classification(stem: str, name: str, facts: Optional[EffectFacts]) -> tuple[str, ...]:
    family, separator, variant = _effect_leaf(stem).partition("__")
    # Lead with the variant and retain other explicitly named family traits:
    # Ground Hit in an Ice family is both Impact and Frost. Reused emitter names
    # must not override this identity (e.g. a poison breath using a flame emitter).
    named = (*_categories((variant,) if separator else ()), *_categories((family,)))
    if named:
        return tuple(dict.fromkeys(named))
    categories = _categories((name,))
    if categories:
        return categories
    if facts is not None:
        categories = _categories(facts.emitters)
        if categories:
            return categories
        # Utility masks, normals and UV distortion do not describe appearance.
        resources = (path for path in (*facts.textures, *facts.meshes)
                     if not _semantic_words(path).intersection({"noise", "uvnoise", "mask", "normal", "distort", "vectorfield"}))
        categories = _categories(resources)
        if categories:
            return categories
    return ("Other",)

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
    """Prefer the specific variant's traits over its broader source family."""
    return _effect_classification(stem, authoring_name, None)[0]


def effect_tags(stem: str, name: str = "", facts: Optional[EffectFacts] = None) -> tuple[str, ...]:
    return _effect_classification(stem, name, facts)


def effect_display_label(stem: str, authoring_name: str = "") -> str:
    """Lead with the named variant; retain family, numeric identity and unknown codes."""

    source = _effect_leaf(stem or authoring_name)
    sections = source.split("__", 1)

    def words(section: str, *, first: bool) -> str:
        tokens = list(_name_tokens(section))
        while tokens and tokens[0].casefold() in _PREFIXES:
            tokens.pop(0)
        if first and tokens and tokens[0].casefold() == "action":
            tokens.pop(0)
        rendered = []
        def word(value: str) -> str:
            return value.upper() if value.casefold() in _ACRONYMS or (value.isupper() and len(value) <= 4) else value.capitalize()
        for token in tokens:
            match = re.fullmatch(r"([A-Za-z]+)(\d+[A-Za-z]*)", token)
            if match:
                head, tail = match.groups()
                if len(head) <= 2 and head.casefold() not in _ACRONYMS:
                    rendered.append(head.upper() + tail)
                else:
                    rendered.extend(word(part) for part in _COMPOUND_WORDS.get(head.casefold(), (head,)))
                    rendered.append(tail.casefold())
            elif re.fullmatch(r"\d+[A-Za-z]+", token):
                rendered.append(token.casefold())
            else:
                rendered.extend(word(part) for part in _COMPOUND_WORDS.get(token.casefold(), (token,)))
        return " ".join(rendered)

    family = words(sections[0], first=True)
    variant = words(sections[1], first=False) if len(sections) > 1 else ""
    if family and variant:
        return f"{variant} · {family}"
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
        incomplete = facts is None or bool(facts.walk_note or getattr(facts, "missing_dependencies", ()) or getattr(facts, "dependency_notes", ()))
        loops = bool(facts and facts.loops) or (incomplete and "loop" in _semantic_words(stem))
        behavior = "Loop" if loops else "Unknown" if incomplete else "One-shot"
        label = effect_display_label(stem, name)
        tags = effect_tags(stem, name, facts)
        return cls(
            stem=stem,
            label=label,
            category=tags[0],
            behavior=behavior,
            facts=facts,
            tags=tags,
            # Shared textures, meshes and presets do not identify this effect.
            search_text=" ".join((stem, label, *tags, behavior)).casefold(),
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
    COLUMN_HEADERS = ("Category", "Effect", "Type", "Size")
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

    def replace_rows(self, rows: tuple[EffectLibraryRow, ...], *, stem_rows=None) -> None:
        if rows is self._rows or (stem_rows is None and rows == self._rows):
            return
        self.beginResetModel()
        self._rows = rows
        self._stem_rows = stem_rows
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
        lookup = getattr(self, "_stem_rows", None)
        if lookup is not None:
            row = lookup.get(wanted)
            return self.index(row, 1) if row is not None else QModelIndex()
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
            return (
                translate_active_ui_text(item.category) if item.stem else "",
                item.label,
                translate_active_ui_text(item.behavior),
                dimensions,
            )[index.column()]
        if role == int(Qt.ItemDataRole.ToolTipRole):
            if not item.stem:
                return "Clear the visual effect and all placement/look tuning."
            details = [item.label, item.stem, ', '.join(translate_active_ui_text(tag) for tag in item.tags)]
            details.append(translate_active_ui_text("Categories are inferred from names; preview the effect to check its appearance."))
            if item.behavior == "Unknown":
                details.append(translate_active_ui_text("Timing metadata is unavailable or incomplete."))
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
            return QSize(170, 24) if index.column() == 1 else None
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
