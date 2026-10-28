"""Kliff's look from Khione95's Character Creator text files, read only.

Character Creator keeps the look in ``<game>/bin64/CharacterCreator`` and
rebuilds it on every load; game saves still hold the defaults. ``profile.txt``
stores menu options (not the editor's on-screen numbers), ``menu.txt`` maps
each option to a game prefab and gives each gender and race its base look, and
``identity.txt`` picks that gender and race. Only Kliff's profile is read:
Damiane's and Oongka's do not reach the real characters.
"""

from dataclasses import dataclass

from cdmw.domain.archives.catalogue import ArchiveEntryDto
from cdmw.domain.archives.character_catalogue import (
    CharacterCatalogComponent, CharacterCatalogDetailResult, CharacterCatalogFile, CharacterCatalogRow,
)

# Each version's menu.txt layout and option numbering is verified by hand.
SUPPORTED_CHARACTER_CREATOR_VERSIONS = ("9.1.16",)

CHARACTER_CREATOR_SLOTS = {0: "Body", 1: "Head", 2: "Hair", 3: "Beard", 5: "Face details"}
CHARACTER_CREATOR_RACES = {0: "human", 1: "orc", 2: "dwarf", 3: "goblin"}
_EXPORTED_SLOTS = (0, 1, 2, 3)


class CharacterCreatorError(ValueError):
    pass


class UnsupportedCharacterCreatorVersion(CharacterCreatorError):
    def __init__(self, version: str) -> None:
        self.version = version
        super().__init__(f"Character Creator {version or '(unknown version)'} is not supported; "
                         f"CDMW reads version {', '.join(SUPPORTED_CHARACTER_CREATOR_VERSIONS)}.")


@dataclass(frozen=True, slots=True)
class CharacterCreatorBase:
    gender: int
    race: int
    body: str
    body_scale: float | None
    head: str
    head_scale: float | None
    hair: str


@dataclass(frozen=True, slots=True)
class CharacterCreatorMenu:
    # (slot, Kliff option) -> prefab name
    options: dict[tuple[int, int], str]
    bases: dict[tuple[int, int], CharacterCreatorBase]


@dataclass(frozen=True, slots=True)
class CharacterCreatorPart:
    slot: int
    prefab: str
    option: int | None  # None when the base look supplies the part

    @property
    def label(self) -> str:
        return CHARACTER_CREATOR_SLOTS[self.slot]


@dataclass(frozen=True, slots=True)
class CharacterCreatorLook:
    version: str
    gender: int
    race: int
    height_percent: float
    body_scale: float | None
    head_scale: float | None
    parts: tuple[CharacterCreatorPart, ...]
    face_details: str
    decoration_count: int

    @property
    def scaled_body(self) -> float | None:
        """The body scale the mod gives Kliff: base scale times the height change."""
        return None if self.body_scale is None else self.body_scale * (1 + self.height_percent / 100)


def _rows(text: str):
    for number, raw in enumerate(text.lstrip("\ufeff").splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("#"):
            yield number, line.split()


def _int(token: str, name: str, number: int) -> int:
    try:
        return int(token)
    except ValueError:
        raise CharacterCreatorError(f"{name} line {number}: {token!r} is not a whole number.") from None


def _scale(token: str, name: str, number: int) -> float | None:
    if token == "-":
        return None
    try:
        return float(token)
    except ValueError:
        raise CharacterCreatorError(f"{name} line {number}: {token!r} is not a scale.") from None


def parse_character_creator_version(text: str) -> str:
    version = next((tokens[0] for _number, tokens in _rows(text)), "")
    if version not in SUPPORTED_CHARACTER_CREATOR_VERSIONS:
        raise UnsupportedCharacterCreatorVersion(version)
    return version


def parse_character_creator_menu(text: str) -> CharacterCreatorMenu:
    options: dict[tuple[int, int], str] = {}
    bases: dict[tuple[int, int], CharacterCreatorBase] = {}
    for number, tokens in _rows(text):
        if tokens[0] == "mesh":
            # mesh <slot> <Kliff option> <race> <shown> <icon> <prefab> <Damiane option> <Oongka option>
            if len(tokens) != 9:
                raise CharacterCreatorError(f"menu.txt line {number}: a mesh row has {len(tokens) - 1} values, not 8.")
            options[(_int(tokens[1], "menu.txt", number), _int(tokens[2], "menu.txt", number))] = tokens[6]
        elif tokens[0] == "base":
            # base <gender> <race> <customization file> <body> <scale> <head> <head scale> <hair>
            if len(tokens) != 9:
                raise CharacterCreatorError(f"menu.txt line {number}: a base row has {len(tokens) - 1} values, not 8.")
            gender, race = _int(tokens[1], "menu.txt", number), _int(tokens[2], "menu.txt", number)
            bases[(gender, race)] = CharacterCreatorBase(
                gender, race, tokens[4] if tokens[4] != "-" else "", _scale(tokens[5], "menu.txt", number),
                tokens[6] if tokens[6] != "-" else "", _scale(tokens[7], "menu.txt", number),
                tokens[8] if tokens[8] != "-" else "")
    if not options or not bases:
        raise CharacterCreatorError("menu.txt has no mesh or base rows.")
    return CharacterCreatorMenu(options, bases)


def parse_character_creator_profile(text: str) -> tuple[dict[int, int], int]:
    """Slot to option, and how many decoration values the profile holds."""
    meshes: dict[int, int] = {}
    decorations = 0
    for number, tokens in _rows(text):
        if tokens[0] == "mesh" and len(tokens) == 3:
            meshes[_int(tokens[1], "profile.txt", number)] = _int(tokens[2], "profile.txt", number)
        elif tokens[0] == "decoration" and len(tokens) == 3:
            decorations += 1
        else:
            raise CharacterCreatorError(f"profile.txt line {number}: {' '.join(tokens)!r} is not a mesh or decoration row.")
    return meshes, decorations


def parse_character_creator_identity(text: str) -> tuple[int, int, float]:
    """Gender, race and height change in percent."""
    rows = list(_rows(text))
    if len(rows) != 1 or len(rows[0][1]) < 3:
        raise CharacterCreatorError("identity.txt should hold one line: gender, race, height and female moves.")
    number, tokens = rows[0]
    gender, race = _int(tokens[0], "identity.txt", number), _int(tokens[1], "identity.txt", number)
    if gender not in (0, 1) or race not in CHARACTER_CREATOR_RACES:
        raise CharacterCreatorError(f"identity.txt names gender {gender} and race {race}, which the mod does not have.")
    try:
        height = float(tokens[2])
    except ValueError:
        raise CharacterCreatorError(f"identity.txt: {tokens[2]!r} is not a height.") from None
    return gender, race, height


def resolve_kliff_look(version_text: str, menu_text: str, profile_text: str = "",
                       identity_text: str = "") -> CharacterCreatorLook:
    """Kliff's parts as game prefab names. Missing profile or identity text means the mod's defaults."""
    version = parse_character_creator_version(version_text)
    menu = parse_character_creator_menu(menu_text)
    meshes, decorations = parse_character_creator_profile(profile_text)
    gender, race, height = parse_character_creator_identity(identity_text) if identity_text.strip() else (0, 0, 0.0)
    base = menu.bases.get((gender, race))
    if base is None:
        raise CharacterCreatorError(f"menu.txt has no base look for a {('male', 'female')[gender]} "
                                    f"{CHARACTER_CREATOR_RACES[race]}.")
    base_parts = {0: base.body, 1: base.head, 2: base.hair}

    def prefab(slot: int) -> tuple[str, int | None]:
        option = meshes.get(slot)
        if option is None:
            return base_parts.get(slot, ""), None
        name = menu.options.get((slot, option))
        if name is None:
            raise CharacterCreatorError(f"profile.txt picks {CHARACTER_CREATOR_SLOTS.get(slot, f'slot {slot}')} "
                                        f"option {option}, which menu.txt does not list.")
        return name, option

    parts = []
    for slot in _EXPORTED_SLOTS:
        name, option = prefab(slot)
        if name and name != "-":
            parts.append(CharacterCreatorPart(slot, name, option))
    details = prefab(5)[0] if 5 in meshes else ""
    return CharacterCreatorLook(version, gender, race, height, base.body_scale, base.head_scale,
                                tuple(parts), details, decorations)



@dataclass(frozen=True, slots=True)
class CharacterCreatorResolvedPart:
    """One part's archive entries: its prefab, the PACs it names and its descriptor's files."""
    part: CharacterCreatorPart
    prefab: ArchiveEntryDto
    descriptor: ArchiveEntryDto | None
    models: tuple[ArchiveEntryDto, ...]
    references: tuple[ArchiveEntryDto, ...]


_COMPONENT_ROLES = {0: "body", 1: "head", 2: "hair", 3: "beard"}
KLIFF_LOOK_KEY = "character_creator:kliff"


def kliff_look_detail(session_id: str, resolved: tuple[CharacterCreatorResolvedPart, ...]) -> CharacterCatalogDetailResult:
    """A Finder selection whose components are the look's prefabs.

    Each component is named after its prefab and carries that prefab's own
    descriptor, so export binds the face shape the prefab gives a PAC even
    when the PAC belongs to another head.
    """
    models: dict[int, ArchiveEntryDto] = {}
    files: dict[int, CharacterCatalogFile] = {}
    components = []

    def add(entry: ArchiveEntryDto, relation: str) -> None:
        files.setdefault(entry.entry_id, CharacterCatalogFile(
            entry.entry_id, entry.path, entry.extension, relation, entry.source_pamt))

    for item in resolved:
        add(item.prefab, "prefab")
        if item.descriptor is not None:
            add(item.descriptor, "descriptor")
        for entry in item.references:
            add(entry, "descriptor_reference")
        for entry in item.models:
            models.setdefault(entry.entry_id, entry)
            add(entry, "model")
        context = (item.prefab.entry_id, *((item.descriptor.entry_id,) if item.descriptor is not None else ()),
                   *(entry.entry_id for entry in item.references))
        components.append(CharacterCatalogComponent(
            _COMPONENT_ROLES[item.part.slot], item.part.prefab, tuple(entry.entry_id for entry in item.models),
            context, 1.0, {"character_creator_slot": str(item.part.slot)}, "resolved"))
    row = CharacterCatalogRow(KLIFF_LOOK_KEY, "appearances", "whole_character", "Kliff's Character Creator look",
                              "kliff", "", "1_pc", "", "resolved", "", len(models), 0, "Character Creator profile")
    return CharacterCatalogDetailResult(session_id, row, tuple(models.values()), tuple(components),
                                        tuple(files.values()), (), (), (), len(files), 0, 0, False, "", "")
