"""Measure how much English survives inside a translated UI catalog.

The built-in catalogs are machine-produced, and the failure they produce is not a
missing translation but a half-finished one: a glossary term is substituted and the
rest of the English sentence is left standing, as in "Anwenden fixed-size numeric
edits from a CDMW HKX XML patch". That reads as a bug to a German user and is
invisible to every check that only compares key sets.

It is measurable without a dictionary. Take the multi-word English strings, and for
each one ask how many of its words survive verbatim in the translation. A correct
translation keeps only the proper nouns — ".NET/Vortice Preview", "Prefab Edit
JSON" — which is a small fraction. A substituted one keeps nearly all of them.

Counting English words on their own does not work, and neither does calibrating
per language: Italian *file*, Polish *folder* and German *Scan*, *Export*, *Import*
and *Name* are the correct native words, so a catalog that translates well scores
*worse* on any metric that treats a shared word as a defect. Whole-sentence overlap
is the measure that survives cognates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

#: Strings shorter than this carry too few words for the ratio to mean anything: a
#: two-word label that keeps one proper noun would score 50% and prove nothing.
MINIMUM_SOURCE_WORDS = 6

#: Above this share of surviving source words, a translation is judged unfinished.
#: Correct translations of proper-noun-heavy strings land well below it.
SURVIVING_WORD_THRESHOLD = 0.6

_PLACEHOLDER = re.compile(r"\{[^}]*\}")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")

#: Diagnostics and log lines are expected to keep their English identifiers, and are
#: not what a user reads in a menu.
_TECHNICAL = re.compile(r"[a-z_]+=|\bsha256\b|\|\s*\w+=")


@dataclass(frozen=True, slots=True)
class UnfinishedTranslation:
    key: str
    source: str
    translation: str
    surviving_share: float


@dataclass(frozen=True, slots=True)
class CatalogQuality:
    language: str
    scanned: int
    unfinished: tuple[UnfinishedTranslation, ...]

    @property
    def unfinished_share(self) -> float:
        return len(self.unfinished) / self.scanned if self.scanned else 0.0

    def summary(self) -> str:
        return (
            f"{self.language}: {len(self.unfinished)} of {self.scanned} scanned strings "
            f"({self.unfinished_share * 100:.1f}%) are still mostly English"
        )


def flatten(value: object) -> str:
    """Render a catalog value as text, joining the branches of a plural entry."""

    if isinstance(value, Mapping):
        return " ".join(str(branch) for branch in value.values())
    return str(value)


def _words(text: str) -> list[str]:
    return [word.lower() for word in _WORD.findall(_PLACEHOLDER.sub(" ", text))]


def surviving_word_share(source: str, translation: str) -> float:
    """Return the share of the source's words that appear in the translation."""

    source_words = _words(source)
    if not source_words:
        return 0.0
    translated = set(_words(translation))
    return sum(1 for word in source_words if word in translated) / len(source_words)


def is_scannable(source: str) -> bool:
    return len(_words(source)) >= MINIMUM_SOURCE_WORDS and not _TECHNICAL.search(source)


def measure_catalog(
    language: str,
    english: Mapping[str, object],
    translations: Mapping[str, object],
    *,
    threshold: float = SURVIVING_WORD_THRESHOLD,
) -> CatalogQuality:
    scanned = 0
    unfinished: list[UnfinishedTranslation] = []
    for key, raw_source in english.items():
        if key not in translations:
            continue
        source = flatten(raw_source)
        if not is_scannable(source):
            continue
        scanned += 1
        translation = flatten(translations[key])
        # An untranslated string is a different problem, caught by its own contract.
        if translation == source:
            continue
        share = surviving_word_share(source, translation)
        if share >= threshold:
            unfinished.append(UnfinishedTranslation(key, source, translation, share))
    unfinished.sort(key=lambda item: -item.surviving_share)
    return CatalogQuality(language, scanned, tuple(unfinished))


def worst_examples(quality: CatalogQuality, limit: int = 3) -> Iterable[str]:
    for item in quality.unfinished[:limit]:
        yield (
            f"  {item.surviving_share:.0%} of the English words survive\n"
            f"    en: {item.source[:110]}\n"
            f"    {quality.language}: {item.translation[:110]}"
        )


__all__ = [
    "CatalogQuality",
    "MINIMUM_SOURCE_WORDS",
    "SURVIVING_WORD_THRESHOLD",
    "UnfinishedTranslation",
    "flatten",
    "is_scannable",
    "measure_catalog",
    "surviving_word_share",
    "worst_examples",
]
