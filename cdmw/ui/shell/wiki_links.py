"""Where Help > Documentation opens: the project's GitHub Wiki, in the interface language.

The Wiki is exported from the Help topics (``scripts/export_github_wiki.py``) as
one manual per built-in language. Every Help topic keeps its id as an anchor in
each manual, so a topic link becomes ``<manual>#<topic id>``. The exporter
imports the names below, so the app and the published pages agree.
"""

from __future__ import annotations

from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from cdmw.constants import APP_REPOSITORY_URL
from cdmw.domain.localization import BUILTIN_LANGUAGE_BY_CODE

WIKI = APP_REPOSITORY_URL + "/wiki/"
#: Topics whose own anchor the manual does not keep, and the section it uses instead.
TOPIC_ANCHORS = {"documentation_index": "guide-tools-and-navigation"}


def manual_slug(locale: str) -> str:
    """The manual's page name: Home in English, the language's own name otherwise."""

    language = BUILTIN_LANGUAGE_BY_CODE[locale]
    return "Home" if locale == "en" else language.display_name.replace(" ", "-")


def manual_url(locale: str, anchor: str = "") -> str:
    return WIKI + quote(manual_slug(locale), safe="-") + ("#" + anchor if anchor else "")


def documentation_url(language_code: str = "en", topic_id: str = "") -> str:
    """The Wiki manual in ``language_code`` (English for an imported language), at ``topic_id``."""

    locale = language_code if language_code in BUILTIN_LANGUAGE_BY_CODE else "en"
    topic = str(topic_id or "").strip()
    return manual_url(locale, TOPIC_ANCHORS.get(topic, topic))


def open_url(url: str) -> bool:
    """Open ``url`` in the default browser; tests replace this so none starts."""

    return bool(QDesktopServices.openUrl(QUrl(url)))


def open_documentation(language_code: str = "en", topic_id: str = "") -> bool:
    return open_url(documentation_url(language_code, topic_id))


__all__ = ["WIKI", "documentation_url", "manual_slug", "manual_url", "open_documentation", "open_url"]
