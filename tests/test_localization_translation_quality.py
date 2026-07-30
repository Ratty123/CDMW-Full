"""Guard the built-in catalogs against half-finished machine translation.

The failure this catches shipped once: German and European Spanish carried 451
strings where a glossary term had been substituted and the rest of the English
sentence left in place. Key-set contracts passed the whole time, because every key
was present and every value was non-empty.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# The detector lives beside the other catalogue validators in scripts/, which the
# localization manifest scanner deliberately does not walk: it is developer
# diagnostics, and its own report strings are not interface text to translate.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from localization_quality import (  # noqa: E402
    SURVIVING_WORD_THRESHOLD,
    is_scannable,
    measure_catalog,
    surviving_word_share,
    worst_examples,
)


RESOURCE_ROOT = Path("cdmw/resources/localization")

#: Every healthy catalog measured 0.3-1.0% when this gate was written, and the two
#: broken ones 6.8% and 7.6%. The ceiling sits between those, with enough headroom
#: that a feature landing a block of proper-noun-heavy strings cannot trip it.
MAXIMUM_UNFINISHED_SHARE = 0.025


def _catalog(code: str) -> dict[str, object]:
    payload = json.loads((RESOURCE_ROOT / f"{code}.json").read_text(encoding="utf-8"))
    return payload["translations"]


def _language_codes() -> list[str]:
    excluded = {"en", "source_manifest", "source_identical_terms"}
    return sorted(path.stem for path in RESOURCE_ROOT.glob("*.json") if path.stem not in excluded)


def test_surviving_word_share_ignores_placeholders_and_counts_only_words() -> None:
    assert surviving_word_share("Apply the imported DDS to which preview slot?", "Anwenden the imported DDS to which preview slot?") > 0.8
    assert surviving_word_share("Apply the imported DDS to which preview slot?", "Auf welchen Vorschau-Slot soll die importierte DDS angewendet werden?") < 0.2
    # A placeholder is markup, not a word, so repeating it cannot inflate the score.
    assert surviving_word_share("Copied {value_0} rows", "{value_0} Zeilen kopiert") == 0.0


def test_a_cognate_translation_is_not_mistaken_for_untranslated_text() -> None:
    """German uses Export, Import, Name and Scan; that is correct, not damage."""

    source = "Archive export is unavailable until the import scan finishes and the name resolves."
    german = "Der Archivexport ist nicht verfügbar, bis der Import-Scan beendet ist und der Name aufgelöst wurde."
    assert surviving_word_share(source, german) < SURVIVING_WORD_THRESHOLD


def test_short_strings_and_diagnostics_are_not_scanned() -> None:
    assert not is_scannable("Export Folder...")
    assert not is_scannable("Texture sidecar scan detail: sidecars={value_0} | paz_groups={value_1}")
    assert is_scannable("Choose the Crimson Desert folder or package root that contains game_files.")


def test_measure_catalog_finds_substituted_strings_and_spares_proper_nouns() -> None:
    english = {
        "damaged": "Apply fixed-size numeric edits from a CDMW HKX XML patch and write a package.",
        "translated": "Choose a valid placement source for every target before building the package.",
        "proper_nouns": "Archive model renderer set to .NET/Vortice Preview for the current session.",
        "untranslated": "Import an edited mesh package and run validation before the rebuild starts.",
    }
    german = {
        "damaged": "Anwenden fixed-size numeric edits from a CDMW HKX XML patch and write a package.",
        "translated": "Wählen Sie für jedes Ziel eine gültige Platzierungsquelle, bevor Sie das Paket erstellen.",
        "proper_nouns": "Archiv-Modellrenderer für die aktuelle Sitzung auf .NET/Vortice Preview gesetzt.",
        "untranslated": english["untranslated"],
    }

    quality = measure_catalog("de", english, german)

    assert [item.key for item in quality.unfinished] == ["damaged"]
    # A wholly untranslated string is a separate contract's problem, not this one.
    assert quality.scanned == 4


@pytest.mark.parametrize("code", _language_codes())
def test_builtin_catalog_is_not_mostly_english(code: str) -> None:
    quality = measure_catalog(code, _catalog("en"), _catalog(code))

    assert quality.unfinished_share <= MAXIMUM_UNFINISHED_SHARE, (
        f"{quality.summary()}, above the {MAXIMUM_UNFINISHED_SHARE:.1%} ceiling.\n"
        "This is the signature of a glossary term being substituted into an English\n"
        "sentence rather than the sentence being translated. Worst offenders:\n"
        + "\n".join(worst_examples(quality))
    )
