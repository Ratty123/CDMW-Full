"""Localized About documentation dispatcher."""

from __future__ import annotations

from typing import Dict, List, Tuple


class AboutDocumentationMixin:
    """Build one current documentation source for the shared catalogue pipeline."""

    def _build_about_sections(self) -> List[Dict[str, str]]:
        from cdmw.ui.shell.about_documentation_en import AboutDocumentationEnglishMixin

        # The English topics are loaded on first use, not with the window. Their
        # builder calls its own section helpers on self, so give the window's class
        # those helpers the first time.
        owner = type(self)
        for name, value in vars(AboutDocumentationEnglishMixin).items():
            if not (name.startswith("__") and name.endswith("__")) and not hasattr(owner, name):
                setattr(owner, name, value)
        return AboutDocumentationEnglishMixin._build_about_sections(self)

    def _build_about_document_for_spanish(self) -> Tuple[str, str, List[Dict[str, str]]]:
        from cdmw.ui.shell.about_documentation_es import AboutDocumentationSpanishMixin

        return AboutDocumentationSpanishMixin._build_about_document_for_spanish(self)

    def _build_about_document_for_german(self) -> Tuple[str, str, List[Dict[str, str]]]:
        from cdmw.ui.shell.about_documentation_de import AboutDocumentationGermanMixin

        return AboutDocumentationGermanMixin._build_about_document_for_german(self)

    def _build_about_document_for_language(self, language_code: str) -> Tuple[str, str, List[Dict[str, str]]]:
        normalized = str(language_code or "").strip().lower()
        if normalized.startswith("es"):
            return self._build_about_document_for_spanish()
        if normalized.startswith("de"):
            return self._build_about_document_for_german()
        return "Documentation", self._build_about_intro_html(), self._build_about_sections()
