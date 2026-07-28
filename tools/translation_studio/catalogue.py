"""Every line of text in the game, as something a translator can work through.

`.paloc` is decoded and writable (`cdmw/core/paloc_format.py`), but a table of 187,521
strings is not a tool. This module is the part that makes it one: pick a language, find
the lines you mean, edit them against a reference language, and export the result as a
mod.

Three decisions come from the shape of the data.

**One language in memory, plus one reference.** The fourteen tables are 16-25 MB each.
Loading all of them to offer a language picker would cost 250 MB and several seconds for
a feature nobody uses all at once. One working language and one optional reference is
what a translator actually needs on screen.

**Search is a scan, not an index.** 187,521 rows filter in well under a tenth of a second
by plain substring, which is faster than a keystroke. An index would need building,
invalidating on every edit, and keeping correct; it would buy nothing a person could
perceive.

**Edits are held apart from the table.** A translation pass touches a handful of lines
out of 187,521, so the edits live in their own small mapping and are applied to the
document only when exporting. That keeps "what have I changed" answerable and Reset free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from cdmw.core.paloc_format import (
    LocalizationEntry,
    LocalizationTable,
    PalocFormatError,
    describe_categories,
    encode_paloc,
    parse_paloc,
)

#: `gamedata/stringtable/binary__/localizationstring_<language>.paloc`
PALOC_DIR = "gamedata/stringtable/binary__"
PALOC_PREFIX = "localizationstring_"


def language_of(game_path: str) -> str:
    """`.../localizationstring_eng.paloc` -> `eng`."""

    name = game_path.rsplit("/", 1)[-1]
    if not name.startswith(PALOC_PREFIX) or not name.endswith(".paloc"):
        return ""
    return name[len(PALOC_PREFIX):-len(".paloc")]


def game_path_for(language: str) -> str:
    return f"{PALOC_DIR}/{PALOC_PREFIX}{language}.paloc"


@dataclass(frozen=True)
class Row:
    """One line, as the table shows it."""

    index: int
    category: int
    key: str
    text: str
    reference: str = ""
    edited: bool = False


@dataclass
class TranslationCatalogue:
    """One language's table, the edits made to it, and an optional reference language."""

    language: str
    table: LocalizationTable
    original: bytes
    #: entry index -> replacement text. Small: a pass touches a handful of 187,521.
    edits: dict = field(default_factory=dict)
    reference_language: str = ""
    reference: Mapping[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ reading

    def __len__(self) -> int:
        return len(self.table.entries)

    def categories(self) -> Mapping[int, str]:
        return describe_categories(self.table)

    def text_at(self, index: int) -> str:
        if index in self.edits:
            return self.edits[index]
        return self.table.entries[index].text

    def row(self, index: int) -> Row:
        entry = self.table.entries[index]
        return Row(
            index=index,
            category=entry.category,
            key=entry.key,
            text=self.text_at(index),
            reference=self.reference.get(entry.key, ""),
            edited=index in self.edits,
        )

    # ---------------------------------------------------------------- searching

    def find(
        self,
        needle: str = "",
        *,
        category: Optional[int] = None,
        edited_only: bool = False,
        limit: int = 0,
    ) -> Tuple[int, ...]:
        """Entry indexes matching a plain substring over key and text.

        Case-insensitive, and it searches the *edited* text so a line you just changed
        is still findable by its new wording.
        """

        wanted = needle.strip().casefold()
        out: list[int] = []
        for index, entry in enumerate(self.table.entries):
            if category is not None and entry.category != category:
                continue
            if edited_only and index not in self.edits:
                continue
            if wanted:
                text = self.edits.get(index, entry.text)
                if wanted not in entry.key.casefold() and wanted not in text.casefold():
                    continue
            out.append(index)
            if limit and len(out) >= limit:
                break
        return tuple(out)

    def find_regex(self, pattern: str, *, limit: int = 0) -> Tuple[int, ...]:
        """Same, by regular expression. Raises `re.error` for the caller to report."""

        compiled = re.compile(pattern, re.IGNORECASE)
        out: list[int] = []
        for index, entry in enumerate(self.table.entries):
            text = self.edits.get(index, entry.text)
            if compiled.search(entry.key) or compiled.search(text):
                out.append(index)
                if limit and len(out) >= limit:
                    break
        return tuple(out)

    # ----------------------------------------------------------------- editing

    def set_text(self, index: int, text: str) -> bool:
        """Record an edit. Setting a line back to its shipped text clears the edit."""

        if not 0 <= index < len(self.table.entries):
            raise PalocFormatError(f"row {index} is not in this table")
        if text == self.table.entries[index].text:
            self.edits.pop(index, None)
            return False
        self.edits[index] = text
        return True

    def revert(self, index: int) -> None:
        self.edits.pop(index, None)

    def reset(self) -> None:
        self.edits.clear()

    @property
    def edit_count(self) -> int:
        return len(self.edits)

    def edited_rows(self) -> Tuple[Row, ...]:
        return tuple(self.row(index) for index in sorted(self.edits))

    # ---------------------------------------------------------------- exporting

    def apply(self) -> LocalizationTable:
        """The table with every pending edit folded in."""

        if not self.edits:
            return self.table
        entries = list(self.table.entries)
        for index, text in self.edits.items():
            entry = entries[index]
            entries[index] = LocalizationEntry(
                category=entry.category, key=entry.key, text=text, reserved=entry.reserved
            )
        return LocalizationTable(entries=tuple(entries))

    def changed_files(self) -> Mapping[str, bytes]:
        """`{game path: bytes}` for the packager, empty when nothing changed."""

        if not self.edits:
            return {}
        return {game_path_for(self.language): encode_paloc(self.apply())}

    def describe_changes(self, limit: int = 6) -> Tuple[str, ...]:
        lines = []
        for row in self.edited_rows()[:limit]:
            was = self.table.entries[row.index].text
            lines.append(f"{row.key}: {was[:40]!r} -> {row.text[:40]!r}")
        return tuple(lines)


# --------------------------------------------------------------------- loading


def load_catalogue(data: bytes, language: str) -> TranslationCatalogue:
    return TranslationCatalogue(
        language=language,
        table=parse_paloc(data, name=game_path_for(language)),
        original=bytes(data),
    )


def attach_reference(
    catalogue: TranslationCatalogue, data: bytes, language: str
) -> TranslationCatalogue:
    """Show another language beside the working one.

    A translator needs the source line in view; a proofreader needs the original. Only
    the key-to-text mapping is kept, not a second editable table.
    """

    table = parse_paloc(data, name=game_path_for(language))
    catalogue.reference_language = language
    catalogue.reference = {entry.key: entry.text for entry in table.entries}
    return catalogue


def available_languages(game_root: Optional[Path] = None) -> Tuple[str, ...]:
    """Every language the archives ship, read from the tables without extracting."""

    from tools.placement_studio import corpus

    root = game_root if game_root is not None else corpus.game_root()
    found = set()
    for _package, entry in corpus._iter_archive_entries(root):
        path = corpus.normalize_game_path(entry.path)
        language = language_of(path)
        if language:
            found.add(language)
    return tuple(sorted(found))


def read_language(language: str, game_root: Optional[Path] = None) -> bytes:
    """Pull one language table out of the archives."""

    from cdmw.core.archive_extraction import read_archive_entry_data
    from tools.placement_studio import corpus

    root = game_root if game_root is not None else corpus.game_root()
    wanted = game_path_for(language)
    for _package, entry in corpus._iter_archive_entries(root):
        if corpus.normalize_game_path(entry.path) == wanted:
            data, _decompressed, _note = read_archive_entry_data(entry)
            return data
    raise PalocFormatError(f"{wanted} is not in the archives")


def export_packages(
    catalogue: TranslationCatalogue,
    *,
    out_root,
    name: str,
    author: str = "",
    version: str = "1.0.0",
    managers: Sequence[str] = ("CDUMM", "DMM", "JMM"),
):
    """Write one mod package per manager. Returns the results, or () when unchanged."""

    files = catalogue.changed_files()
    if not files:
        return ()
    from tools.placement_studio.ops import Plan
    from tools.placement_studio.packaging import PackageMetadata, build_all

    metadata = PackageMetadata(
        name=name,
        version=version,
        author=author,
        description=(
            f"{catalogue.edit_count} retranslated line(s) for {catalogue.language}."
        ),
    )
    return tuple(
        build_all(Plan(name=name), files, metadata, out_root=Path(out_root),
                  managers=tuple(managers))
    )
