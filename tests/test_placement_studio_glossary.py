"""The in-app explanations stay plain, and stay in step with the buttons they describe.

The failure this guards against is quiet: a control gets renamed, the walkthrough keeps
naming the old label, and a modder follows an instruction that points at nothing.
"""

from __future__ import annotations

import re

import pytest

from tools.placement_studio import glossary


def test_every_term_says_what_it_is_and_why_it_matters():
    for term in glossary.TERMS:
        assert term.name
        assert term.what.endswith("."), term.name
        assert term.why, f"{term.name} explains itself but not why it matters"


def test_tooltips_carry_no_markup():
    """Qt tooltips are plain text: a backtick or asterisk shows up as a backtick or asterisk."""

    for term in glossary.TERMS:
        assert "`" not in term.tooltip()
        assert "*" not in term.tooltip()
        assert "<" not in term.tooltip()


def test_the_help_page_marks_up_the_same_text_instead_of_dropping_it():
    page = glossary.as_html()

    assert "<code>1_phm</code>" in page
    assert "<i>item</i>" in page


def test_an_apostrophe_survives_into_the_help_page():
    """Escaping is on, so this checks it escapes rather than mangles."""

    assert "hip&#x27;s angle" in glossary.as_html()


def test_a_control_specific_line_is_appended_to_the_shared_one():
    text = glossary.tip("Carry", "Extra line for this button.")

    assert glossary.BY_NAME["Carry"].tooltip() in text
    assert text.endswith("Extra line for this button.")


def test_an_unknown_term_falls_back_to_the_extra_line():
    assert glossary.tip("Not A Term", "just this") == "just this"
    assert glossary.tip("Not A Term") == ""


@pytest.mark.parametrize(
    "label",
    [
        "Match animations",
        "Only draws for this spot",
        "Use as orientation",
        "Pending changes",
        "Carry",
        "Part",
    ],
)
def test_the_walkthrough_names_controls_that_exist(label):
    """Every button the walkthrough tells you to press must still be called that.

    Checked against the source of the widgets rather than against a second copy of the list,
    so renaming a button and not the instructions fails here.
    """

    from pathlib import Path

    root = Path(glossary.__file__).parent
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.glob("window*.py")
    )
    assert f'"{label}' in sources or f"'{label}" in sources, (
        f"the Help walkthrough names {label!r}, but no widget is labelled that"
    )
    assert label in glossary.as_html()


def test_the_walkthrough_is_a_numbered_sequence():
    assert len(glossary.WALKTHROUGH) >= 5, "the walkthrough should still be a step-by-step"
    page = glossary.as_html()
    for number in range(1, len(glossary.WALKTHROUGH) + 1):
        assert f">{number}</b>" in page, f"step {number} lost its number"


def test_the_page_is_broken_into_sections_rather_than_run_together():
    """A glossary is read by finding one entry, not by reading to the end."""

    page = glossary.as_html()

    assert page.count("<h2>") >= 4, "the help page needs headings to be navigable"
    # Definitions and steps sit in table rows, so each is its own visual block.
    assert page.count("<tr>") >= len(glossary.TERMS) + len(glossary.WALKTHROUGH)


def test_every_symptom_comes_with_a_cure():
    for symptom, cure in glossary.TROUBLESHOOTING:
        assert symptom and cure
        assert cure != symptom
