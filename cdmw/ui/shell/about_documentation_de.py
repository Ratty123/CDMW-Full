"""German documentation compatibility wrapper.

The English documentation source is translated through the shared UI catalogue so
all built-in languages expose the same current topic set.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

class AboutDocumentationGermanMixin:
    """Preserve the historical German builder method for existing callers."""

    def _build_about_document_for_german(
        self,
    ) -> Tuple[str, str, List[Dict[str, str]]]:
        return (
            "Documentation",
            self._build_about_intro_html(),
            self._build_about_sections(),
        )
