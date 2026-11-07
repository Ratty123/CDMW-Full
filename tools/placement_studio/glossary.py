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
        "Where the item hangs when it is put away: hip, back or thigh. Set with *Carried at* on "
        "the Position tab.",
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
        "Changing it moves all of them, so Save as mod refuses that change. Use Carried at "
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



#: What each tab is for, in the order they sit.
TABS: Tuple[Tuple[str, str], ...] = (
    ("Position",
     "What to work on, where it is carried, fine-tuning its position and angle, and checking "
     "whether it sinks into the body."),
    ("Animations",
     "Give the weapon another weapon's animations, and find and play any animation in the "
     "game on the character."),
    ("Edit animation",
     "Change an animation or make a new one: key bone poses on a timeline, reach and plant "
     "hands and feet, retime it, mirror it, borrow body parts, join another animation after "
     "it, or animate it in Blender and import it back. Experimental: edited animations have "
     "not been tested in game yet."),
    ("Armour",
     "Dress the character. Pick a piece per slot and it appears on the body, so you can see "
     "whether a moved weapon collides with what is worn."),
    ("Your mod",
     "Every change in plain words. Untick what to leave out, then Save as mod. It can go "
     "straight into DMM's mods folder."),
    ("Advanced",
     "Attach points (with the full list and what else moves if one changes), Driven bones, "
     "Rig behaviour, action charts, and the exact file changes."),
)

#: The view controls. These are on screen with no labels beyond a checkbox, so what they do
#: and — for the two that cost something — what they cost has to be written down somewhere.
VIEWPORT: Tuple[Tuple[str, str], ...] = (
    ("Turn, pan, zoom",
     "Drag with the left button to turn the view, the middle button to pan, the wheel to "
     "zoom. R resets the view."),
    ("Body and gear",
     "Draw the character's body, what it wears and the weapon, not just the skeleton. The "
     "body is the bare figure; clothing appears as you put it on in the Armour tab."),
    ("Solid",
     "Opaque instead of see-through. See-through is what lets you look inside the body at a "
     "weapon sunk into it."),
    ("Skeleton, Labels, Spare attach points",
     "Overlays. Spare attach points are the ones nothing hangs on yet, useful when looking "
     "for somewhere to move an item to."),
    ("Playing an animation",
     "The bar under the view plays the animation chosen on the Animations tab. Bind pose "
     "puts the character back at rest."),
)

def tip(name: str, extra: str = "") -> str:
    """The tooltip for a term, optionally with a line specific to one control."""

    term = BY_NAME.get(name)
    if term is None:
        return extra
    return f"{term.tooltip()}\n\n{extra}" if extra else term.tooltip()


#: The jobs people open the tool for, each as numbered steps of (what you do, what happens).
TASKS: Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...] = (
    (
        "Move a weapon somewhere else on the body",
        (
            ("Choose the <b>Weapon</b> at the top",
             "The slot that fits it is picked for you on the Position tab."),
            ("On <b>Position</b>, pick a spot in <b>Carried at</b>",
             "The weapon moves there when put away, and its angle follows."),
            ("Look at it put away",
             "<b>Show it</b> switches to <b>Put away</b>. Turn the view, try armour on the "
             "Armour tab, and press <b>Check for clipping</b>."),
            ("Optional: on <b>Animations</b>, <b>Use another weapon's animations…</b>",
             "Gives it a draw that reaches the new spot. You see every file first."),
            ("On <b>Your mod</b>, press <b>Save as mod</b>",
             "Then tick the mod in DMM and press Mount."),
        ),
    ),
    (
        "Adjust where it sits or how it is angled",
        (
            ("On <b>Position</b>, look at <b>3. Fine-tune</b>",
             "It already shows the point that holds the item the way it is on screen."),
            ("Use the <b>Move</b> and <b>Turn</b> buttons, or type a <b>Position</b> or "
             "<b>Angle</b>",
             "The Turn arrows follow the view: left is left on screen. Or choose <b>Move</b>, "
             "<b>Rotate</b> or <b>Tilt</b> and drag in the view."),
            ("Read the note under the point's name",
             "It says what else moves with it, and whether the change can be saved."),
            ("Save from <b>Your mod</b>",
             "Your adjustments are saved together as one change."),
        ),
    ),
    (
        "Change an animation, or make a new one",
        (
            ("Play it on the <b>Animations</b> tab, then open <b>Edit animation</b>",
             "Choose <b>Edit the animation that is playing</b>, or <b>Start a new one from "
             "this pose</b> to build one from a still pose."),
            ("Pick a <b>Bone</b> or click its joint, move the playhead, and <b>Turn</b> or "
             "<b>Move</b> it",
             "Each change keys that bone at that moment, on top of the animation. Drag keys on "
             "the timeline to retime them."),
            ("Move a hand or foot under <b>Reach</b>, or <b>Plant</b> it",
             "The arm or leg bends to get it there; a planted foot stays put while the body "
             "moves."),
            ("Adjust <b>Speed</b>, the part used, <b>Mirror left and right</b>, borrow a "
             "body part, or join another animation",
             "The character shows the result as you go; <b>Undo edit</b> takes a step back."),
            ("Optional: <b>Export for Blender…</b>, animate there, <b>Import from Blender…</b>",
             "Keep the bone names Blender shows; they are how the motion finds its bones."),
            ("Check <b>Replaces</b>, then <b>Add to Your mod</b>",
             "It replaces that animation in the game; save it from <b>Your mod</b>."),
        ),
    ),
    (
        "Look at an animation",
        (
            ("On <b>Animations</b>, search or filter the list",
             "<b>Only draws for this spot</b> needs <b>" + MATCH_LABEL + "</b> once."),
            ("Double-click an animation, or press <b>Play selected</b>",
             "It plays on the character; the bar under the view pauses and scrubs it."),
        ),
    ),
)

#: Symptom -> cause and cure. The things that actually go wrong.
TROUBLESHOOTING: Tuple[Tuple[str, str], ...] = (
    (
        "Save as mod says a point is shared",
        "That attach point is used by other slots too, so changing it would move them as well. "
        "Remove that adjustment on Your mod and move the item with <b>Carried at</b> instead, "
        "which gives it a point of its own.",
    ),
    (
        "The item hangs at a strange angle after I moved it",
        "The game defines no angle for the new spot. Use <b>Flip 180°</b> or the <b>Angle</b> "
        "boxes on Position, or select the point to aim with under Advanced > Attach points and "
        "press <b>" + AIM_LABEL + "</b>.",
    ),
    (
        "No draws were found for the spot I chose",
        "Not every spot on the body has an animation that reaches it. The item still moves; "
        "pick an animation yourself with <b>Use another weapon's animations…</b>.",
    ),
    (
        "My new attach point is ignored by the animations",
        "An animation can only be pointed at a name exactly as long as the one it replaces, "
        "because the file stores names with their length. Rename it to match.",
    ),
    (
        "A planted foot still slides",
        "The body moved further from the spot than the leg reaches, so the leg straightened "
        "toward it. Plant for a shorter stretch, or lower <b>Distance travelled</b>.",
    ),
    (
        "The game was updated",
        "Placement & Animations checks its copies of the game files each time it opens and "
        "refreshes them. Changes made before an update cannot be saved; make them again.",
    ),
)

_STYLE = """
<style>
  body { line-height: 148%; }
  h2 {
    margin-top: 4px; margin-bottom: 2px;
    font-size: large;
  }
  h3 { margin-top: 2px; margin-bottom: 2px; }
  p { margin-top: 2px; margin-bottom: 8px; }
  td { padding-bottom: 10px; padding-right: 16px; }
  .term { font-weight: bold; }
  .step { font-weight: bold; }
  .rule { font-style: italic; }
</style>
"""

#: The page is laid out inside a table of this width rather than filling the window. A line of
#: prose stretched across a 1,500 px pane is measurably harder to read — the eye loses the
#: start of the next line — and this page is nearly all prose. Everything below therefore has a
#: fixed measure and the window can be as wide as it likes.
_MEASURE = 940


def _section(title: str, body: str) -> str:
    """One titled block, with a rule under the heading so the page has visible seams."""

    # `<hr>` rather than a one-pixel table cell: Qt's rich text ignores `height` on a cell and
    # renders it at a full line, which came out as a heavy grey band across the page.
    return f"<h2>{title}</h2><hr><table width='100%'>{body}</table>"


def _pairs(rows) -> str:
    """Name on the left, explanation on the right — the shape of a dictionary.

    The eye runs down one column to find an entry and stops. Packing both into one cell made
    every row wrap over four lines and the column impossible to scan.
    """

    out = []
    for name, text in rows:
        out.append(
            f"<tr>"
            f"<td valign='top' width='26%'><b class='term'>{name}</b></td>"
            f"<td valign='top' class='why'>{text}</td>"
            f"</tr>"
        )
    return "".join(out)


def as_html() -> str:
    """The Help panel.

    Ordered by what a reader needs first: what the tool is for, the jobs most people came to
    do as numbered steps, then the map of the tabs and the view, then the words, then what
    goes wrong. Every part is a table rather than paragraphs, because the thing a reader
    wants from reference text is to find *one* entry and stop reading.
    """

    tasks = []
    for title, steps in TASKS:
        rows = []
        for number, (action, effect) in enumerate(steps, start=1):
            rows.append(
                f"<tr>"
                f"<td valign='top' width='26'><b class='step'>{number}</b></td>"
                f"<td valign='top' width='42%'>{action}</td>"
                f"<td valign='top' class='why'>{effect}</td>"
                f"</tr>"
            )
        tasks.append(_section(title, "".join(rows)))

    words = []
    for term in TERMS:
        words.append(
            f"<tr>"
            f"<td valign='top' width='26%'><b class='term'>{term.name}</b></td>"
            f"<td valign='top'>{_rich(term.what)}"
            f"<br><span class='why'>{_rich(term.why)}</span></td>"
            f"</tr>"
        )

    body = [
        _STYLE,
        "<h2>What this tool does</h2>",
        "<p class='lead'>It changes where a character carries equipment (a sword from the hip "
        "to the back, say) and which animations go with it, then saves the result as a mod "
        "for DMM. Nothing you do here touches the game until you save the mod and enable it "
        "in DMM.</p>",
        *tasks,
        _section("The tabs", _pairs(TABS)),
        _section("The view", _pairs(VIEWPORT)),
        _section("Words this tool uses", "".join(words)),
        _section("If something looks wrong", _pairs(TROUBLESHOOTING)),
    ]
    # Held to a fixed measure; see `_MEASURE`.
    return (
        f"<table width='{_MEASURE}' cellspacing='0' cellpadding='0'><tr><td>"
        + "".join(body)
        + "</td></tr></table>"
    )
