"""Plain-English explanations of the vocabulary this tool uses.

The words here — socket, child socket, part, route, draw clip — are the game's own, and none
of them explain themselves. A modder opening the Studio for the first time sees `Part:` next
to `CD_MainWeapon_Sword_R   ->   Pelvis_L_Socket / RHand_Socket` and has no way to tell which
half of that is the thing being moved and which is where it hangs.

One definition per term, held in one place so a tooltip and the Help panel can never drift
apart. Each entry is a short sentence saying what the thing *is*, and a second saying why it
matters when editing — the second is usually the one that answers the real question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape as html_escape
from typing import Dict, Tuple


def _plain(text: str) -> str:
    """Drop the emphasis markers. Tooltips are plain text and would show them literally."""

    return text.replace("`", "").replace("*", "")


def _rich(text: str) -> str:
    """Turn the same markers into HTML, for the Help panel."""

    out = html_escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*([^*]+)\*", r"<i>\1</i>", out)


@dataclass(frozen=True, slots=True)
class Term:
    name: str
    what: str
    why: str = ""

    def tooltip(self) -> str:
        what, why = _plain(self.what), _plain(self.why)
        return f"{what}\n\n{why}" if why else what


TERMS: Tuple[Term, ...] = (
    Term(
        "Character",
        "The body being edited — `1_phm` is the player character.",
        "Everything else on screen belongs to this character: its skeleton, its sockets, "
        "and the animations built for it.",
    ),
    Term(
        "Socket",
        "A named point on the body where something can be attached, like a peg.",
        "Sockets are defined by the game and move with the bone they sit on, so a weapon on "
        "a hip socket follows the hip through every animation.",
    ),
    Term(
        "Child socket",
        "A matching point on the *item*, which decides the angle it hangs at.",
        "The body socket says where an item goes; the child socket says which way it points. "
        "Move a sword to the back without changing its child socket and it hangs at the "
        "hip's angle — sticking out sideways.",
    ),
    Term(
        "Part",
        "One row of the character's equipment list — a single item slot to work on.",
        "The arrow in the dropdown shows where that part currently hangs: first when stowed, "
        "then when held.",
    ),
    Term(
        "Carry",
        "Where the selected part hangs when it is stowed — hip, back, thigh or in hand. "
        "Labelled *Hangs on* in the header.",
        "Changing it is the main edit this tool exists for: the item moves there, its angle "
        "follows, and you are offered the matching animations.",
    ),
    Term(
        "Stowed and held",
        "Stowed is the item put away; held is the item in the character's hand.",
        "They are two separate placements on the same item, so a sword has both a spot on the "
        "hip and a grip in the hand.",
    ),
    Term(
        "Draw and sheathe",
        "The animations for taking a weapon out (`weapon_out`) and putting it away "
        "(`weapon_in`).",
        "These are the clips that have to change when a weapon moves, because the arm reaches "
        "somewhere different.",
    ),
    Term(
        "Match animations",
        "Works out which draws start from which carry position, by playing each one and "
        "watching where the hands go.",
        "The game files do not record this anywhere, so it has to be measured. It takes about "
        "half a minute and is remembered afterwards.",
    ),
    Term(
        "Swap animations",
        "Gives the weapon the other grip's animation set — the two-hand animations for a "
        "one-hand weapon, or the reverse.",
        "This is how a moved weapon gets a draw that suits its new position. The new "
        "animation is written at the old clip's path, so the game's action charts are never "
        "touched. Choose draws alone, or everything including how the character stands and "
        "moves while carrying it.",
    ),
    Term(
        "Attach point",
        "A socket you create yourself, at a spot you pick on the body.",
        "Use it when the game has no socket where you want something to sit. Animations can "
        "only be pointed at a new attach point if its name is exactly as long as the one it "
        "replaces — the file format stores names with their length.",
    ),
    Term(
        "Pending changes",
        "Edits made so far, held in the tool rather than written to disk.",
        "Nothing touches the game until Export files or Build packages, so it is safe to "
        "experiment and undo.",
    ),
    Term(
        "Clipping",
        "How far the weapon sinks into the body at the current frame.",
        "A little is normal; a lot means the item is buried. It is measured on demand because "
        "the check is too slow to run on every frame of a playing animation.",
    ),
    Term(
        "LOD clips",
        "Simplified copies of an animation used when the character is far from the camera.",
        "Usually not what you want to look at — they are the same motion with less detail.",
    ),
)

BY_NAME: Dict[str, Term] = {term.name: term for term in TERMS}


def tip(name: str, extra: str = "") -> str:
    """The tooltip for a term, optionally with a line specific to one control."""

    term = BY_NAME.get(name)
    if term is None:
        return extra
    return f"{term.tooltip()}\n\n{extra}" if extra else term.tooltip()


#: The steps of the one job this tool exists for, each as (what you do, what happens).
WALKTHROUGH: Tuple[Tuple[str, str], ...] = (
    (
        "Pick the <b>Part</b> to move",
        "A sword is a <code>CD_MainWeapon</code> row. The arrow beside each row shows where "
        "it hangs today.",
    ),
    (
        "Choose a new <b>Hangs on</b> position",
        "The item moves there and its angle follows automatically.",
    ),
    (
        "Press <b>Swap animations...</b>",
        "Gives the weapon the other grip's animations — the two-hand set for a one-hand "
        "weapon. Choose draws only, or everything including how the character stands and "
        "moves. It offers to play the result so you can see it.",
    ),
    (
        "Optional: <b>Match animations</b>",
        "Measures which draws start from which body position, so the clip list can be "
        "filtered with <b>Only draws for this spot</b>. Takes about half a minute, once. "
        "The swap does not need it.",
    ),
    (
        "Check <b>Pending changes</b>, then export",
        "Nothing has touched the game until you press <b>Export files</b> or "
        "<b>Build packages</b>.",
    ),
)

#: Symptom -> cause and cure. The three things that actually go wrong.
TROUBLESHOOTING: Tuple[Tuple[str, str], ...] = (
    (
        "The item hangs at a strange angle after I moved it",
        "The game defines no angle for the new spot. Select the socket you want it aimed at "
        "and press <b>Use as orientation</b>, or aim it by hand with Rotate and Tilt.",
    ),
    (
        "No draws were found for the position I chose",
        "Not every spot on the body has an animation that reaches it. The item will still "
        "move; you just have to pick an animation yourself.",
    ),
    (
        "My new attach point is ignored by the animations",
        "An animation can only be pointed at a name exactly as long as the one it replaces, "
        "because the file stores names with their length. Rename it to match.",
    ),
)

_STYLE = """
<style>
  body { line-height: 150%; }
  h2 { margin-top: 18px; margin-bottom: 2px; }
  p { margin-top: 2px; margin-bottom: 10px; }
  td { padding-bottom: 9px; padding-right: 14px; }
  .lead { color: #9aa4b4; }
  .term { color: #cfd6e4; }
  .why { color: #99a3b3; }
  .step { color: #7fb2e8; }
</style>
"""


def as_html() -> str:
    """The Help panel: a walkthrough first, then the words, then what goes wrong.

    Laid out as tables rather than as paragraphs. The first version ran every definition
    together into a block of prose that nobody would read to the end of — and the one thing
    a reader wants from a glossary is to find *one* entry and stop.
    """

    rows = [
        _STYLE,
        "<h2>What this tool does</h2>",
        "<p class='lead'>It moves where a character carries their equipment — a sword from "
        "the hip to the back, say — and keeps the take-out and put-away animations in step "
        "with the new position.</p>",
        "<h2>Moving a weapon, start to finish</h2>",
        "<table width='100%'>",
    ]
    for number, (action, effect) in enumerate(WALKTHROUGH, start=1):
        rows.append(
            f"<tr>"
            f"<td valign='top' width='24'><b class='step'>{number}</b></td>"
            f"<td valign='top' width='42%'>{action}</td>"
            f"<td valign='top' class='why'>{effect}</td>"
            f"</tr>"
        )
    rows.append("</table>")

    # Name on the left, definition on the right — the shape of a dictionary, so the eye can
    # run down one column to find an entry. Packing the name and its definition into the same
    # cell made every term wrap over four lines and the column impossible to scan.
    rows.append("<h2>Words this tool uses</h2><table width='100%'>")
    for term in TERMS:
        rows.append(
            f"<tr>"
            f"<td valign='top' width='22%'><b class='term'>{term.name}</b></td>"
            f"<td valign='top'>{_rich(term.what)}"
            f"<br><span class='why'>{_rich(term.why)}</span></td>"
            f"</tr>"
        )
    rows.append("</table>")

    rows.append("<h2>If something looks wrong</h2><table width='100%'>")
    for symptom, cure in TROUBLESHOOTING:
        rows.append(
            f"<tr>"
            f"<td valign='top' width='38%'><b class='term'>{symptom}</b></td>"
            f"<td valign='top' class='why'>{cure}</td>"
            f"</tr>"
        )
    rows.append("</table>")
    return "".join(rows)
