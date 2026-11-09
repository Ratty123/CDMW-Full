"""Plain-English explanations of the vocabulary this tool uses.

The words here — socket, child socket, part, route, draw clip — are the game's own, and none
of them explain themselves. A modder opening the Studio for the first time sees `Part:` next
to `CD_MainWeapon_Sword_R   ->   Pelvis_L_Socket / RHand_Socket` and has no way to tell which
half of that is the thing being moved and which is where it hangs.

One definition per term, held in one place so the tooltips that name it can never drift
apart. Each entry is a short sentence saying what the thing *is*, and a second saying why it
matters when editing — the second is usually the one that answers the real question.
"""

from __future__ import annotations

#: What the scan is called wherever it is named. It used to be "Match animations", which says
#: what it operates on but not what it does or what it costs — and it reads like a command that
#: changes something, so it invited being pressed by anyone who had not read the tooltip. It
#: only measures and reports: every clip is played and the hands watched, which takes about half
#: a minute. The name now says the question it answers, and the cost is on the button.
MATCH_LABEL = "Find which draws fit"

#: The button that aims an item using the selected point. Short because it shares the bottom
#: bar with a dozen other controls; held here so the walkthrough and the status message that
#: name it cannot drift from what the button actually says.
AIM_LABEL = "Aim with this"

from dataclasses import dataclass
from typing import Dict, Tuple


def _plain(text: str) -> str:
    """Drop the emphasis markers. Tooltips are plain text and would show them literally."""

    return text.replace("`", "").replace("*", "")


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
        "Everything else on screen belongs to this character: its skeleton, its attach points, "
        "and the animations built for it.",
    ),
    Term(
        "Attach point",
        "A named point where something is attached, like a peg. The game calls them sockets.",
        "Points on the body move with the bone they sit on, so a weapon on the hip follows the "
        "hip through every animation. Each item also has points of its own, which decide the "
        "angle it hangs at. You can make new ones under Advanced > Attach points; an animation "
        "can only be pointed at a new one whose name is exactly as long as the name it "
        "replaces.",
    ),
    Term(
        "Slot",
        "One row of the character's equipment list: the main weapon in the right hand, the "
        "shield, the bow.",
        "The arrow in the list shows where that slot hangs today: first when put away, then "
        "when in hand. Picking a weapon picks the slot that fits it.",
    ),
    Term(
        "Carry",
        "Where the item hangs when it is put away: hip, back or thigh. Set with *Move it* on "
        "the Carry tab.",
        "This is the main change the tool exists for: the item moves there, its angle follows, "
        "and it gets an attach point of its own so nothing else moves with it.",
    ),
    Term(
        "Stowed and held",
        "Put away, or in the character's hand. *Show it* on the Position tab switches between "
        "the two.",
        "They are two separate placements on the same item, so a sword has both a spot on the "
        "hip and a grip in the hand. Fine-tune adjusts the one on screen.",
    ),
    Term(
        "Draw and put away",
        "The animations for taking a weapon out (`weapon_out`) and putting it away "
        "(`weapon_in`).",
        "These are the animations that have to change when a weapon moves, because the arm "
        "reaches somewhere different.",
    ),
    Term(
        MATCH_LABEL,
        "Works out which draw animations start from which spot on the body, by playing each "
        "one and watching where the hands go.",
        "The game files do not record this anywhere, so it has to be measured. It takes about "
        "half a minute, changes nothing, and is remembered afterwards.",
    ),
    Term(
        "Use another weapon's animations",
        "Gives the weapon another weapon's animations, such as the two-hand sword's draw for a "
        "one-hand sword moved to the back.",
        "The new animation is written in place of the old one, so the game keeps asking for "
        "the same file and gets the new motion. You see every file it would change, and can "
        "watch the result, before anything changes.",
    ),
    Term(
        "Your mod",
        "Every change made so far, kept in the tool rather than written to the game.",
        "Nothing touches the game until you save the mod and enable it in DMM, so it is safe "
        "to experiment, undo, and remove changes you do not want.",
    ),
    Term(
        "Clipping",
        "How far the weapon sinks into the body in the pose on screen.",
        "A little is normal; a lot means the item is buried. It is measured when you ask, "
        "because the check is too slow to run on every frame of a playing animation.",
    ),
    Term(
        "Pose key",
        "A bone's turn or move at one moment of an animation, set on the Edit animation tab.",
        "Keys add to what the animation already does there. Between two keys the bone eases "
        "from one to the other; before the first and after the last it holds.",
    ),
    Term(
        "Reach",
        "Moving a hand or foot and letting the arm or leg bend to get it there, set on the "
        "Edit animation tab.",
        "The elbow or knee keeps pointing the way the animation bends it, and the bones keep "
        "their length: a spot further away than the limb reaches straightens it toward the spot.",
    ),
    Term(
        "Plant",
        "Holding a hand or foot where it is while the body moves, such as a foot on the ground "
        "during a step.",
        "Plant here at the first moment and again at the last; Let go here hands it back to the "
        "animation.",
    ),
    Term(
        "Fade",
        "How long two joined animations blend into each other.",
        "The second starts that long before the first ends, and the character's pace eases from "
        "one into the other.",
    ),
    Term(
        "Shared attach point",
        "An attach point that several slots use, such as the grip every weapon in the right "
        "hand uses.",
        "Changing it moves all of them, so Save as DMM mod refuses that change. Use Move it "
        "instead: it gives the item a point of its own.",
    ),
    Term(
        "LOD clips",
        "Simplified copies of an animation used when the character is far from the camera. "
        "Shown with *Distant versions*.",
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
