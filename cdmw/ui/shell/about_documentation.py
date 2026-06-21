"""Localized About documentation dispatcher."""

from __future__ import annotations

from typing import Dict, List, Tuple

from cdmw.constants import APP_TITLE
from cdmw.ui.shell.about_documentation_de import AboutDocumentationGermanMixin
from cdmw.ui.shell.about_documentation_en import AboutDocumentationEnglishMixin
from cdmw.ui.shell.about_documentation_es import AboutDocumentationSpanishMixin


class AboutDocumentationMixin(
    AboutDocumentationEnglishMixin,
    AboutDocumentationSpanishMixin,
    AboutDocumentationGermanMixin,
):
    """Select localized documentation topic content."""

    def _build_about_document_for_language(self, language_code: str) -> Tuple[str, str, List[Dict[str, str]]]:
        normalized = str(language_code or "").strip().lower()
        if normalized == "es":
            return self._build_about_document_for_spanish()
        if normalized == "de":
            return self._build_about_document_for_german()
        return f"{APP_TITLE} Documentation", self._build_about_intro_html(), self._build_about_sections()
