"""The Mesh Editor helper's key grammar, for keys chosen in Settings > Shortcuts (plan 8.7 E4).

The helper reads its overrides with ``Binding::parse`` in
``tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/shortcuts.rs``: modifiers ``Ctrl``,
``Alt`` and ``Shift`` in any order, then one key by egui's name (``PageUp``,
``Delete``, ``F5``, ``Comma``) or a numpad key (``Num1``, ``NumPlus``,
``NumDecimal``). A binding it cannot parse drops that command's whole
override, and its own editor refuses reserved chords. Qt spells keys its own
way (``PgUp``, ``Del``, ``Num+1``), so the page translates what it recorded,
and refuses what the helper cannot take, with the helper's own reason.

Keep this in step with ``shortcuts.rs``: ``Binding::parse``,
``ShortcutKey::reserved``, ``KeyChord::reserved_reason`` and ``app_command``.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_CHORD_LENGTH = 32
MODIFIERS = ("Ctrl", "Alt", "Shift")

#: egui's ``Key::from_name`` spellings -> ``Key::name()``, for the keys a shortcut can use.
_EGUI_NAMES: dict[str, str] = {}


def _alias(canonical: str, *aliases: str) -> None:
    for name in (canonical, *aliases):
        _EGUI_NAMES[name] = canonical


for _canonical, _aliases in {
    "Down": ("ArrowDown",), "Left": ("ArrowLeft",), "Right": ("ArrowRight",), "Up": ("ArrowUp",),
    "Escape": ("Esc",), "Tab": (), "Backspace": (), "Enter": ("Return",),
    "Insert": ("Help",), "Delete": (), "Home": (), "End": (), "PageUp": (), "PageDown": (),
    "Copy": (), "Cut": (), "Paste": (),
    "Space": (" ",), "Colon": (":",), "Comma": (",",), "Minus": ("-", "−"), "Period": (".",),
    "Plus": ("+",), "Equals": ("=", "Equal"), "Semicolon": (";",), "Backslash": ("\\",), "Slash": ("/",),
    "Pipe": ("|",), "Questionmark": ("?",), "Exclamationmark": ("!",), "OpenBracket": ("[", "BracketLeft"),
    "CloseBracket": ("]", "BracketRight"), "OpenCurlyBracket": ("{",), "CloseCurlyBracket": ("}",),
    "Backtick": ("`", "Backquote", "Grave"), "Quote": ("'",),
    "BrowserBack": (), "IntlBackslash": (),
}.items():
    _alias(_canonical, *_aliases)
for _digit in range(10):
    _alias(str(_digit), f"Digit{_digit}")
for _code in range(ord("A"), ord("Z") + 1):
    _alias(chr(_code), chr(_code).lower(), f"Key{chr(_code)}")
for _number in range(1, 36):
    _alias(f"F{_number}")

#: Numpad keys by the helper's own names; Qt records them with its ``Num`` modifier.
NUMPAD_NAMES = tuple(f"Num{d}" for d in range(10)) + (
    "NumDecimal", "NumPlus", "NumMinus", "NumMultiply", "NumDivide", "NumEnter")
_QT_NUMPAD = {**{str(d): f"Num{d}" for d in range(10)}, ".": "NumDecimal", ",": "NumDecimal",
              "+": "NumPlus", "-": "NumMinus", "*": "NumMultiply", "/": "NumDivide",
              "Enter": "NumEnter", "Return": "NumEnter"}
#: Qt's portable key names the helper spells differently.
_QT_KEYS = {"PgUp": "PageUp", "PgDown": "PageDown", "Ins": "Insert", "Del": "Delete"}
#: ``ShortcutKey::reserved``: they cancel, edit text or move focus.
_RESERVED_KEYS = frozenset({"Escape", "Tab", "Backspace", "Enter", "Space", "Up", "Down", "Left", "Right"})

#: The helper's reasons, as ``cdmw_ui::keyboard`` words them (already in every catalogue).
EDITING_KEY_REASON = "This key is reserved for cancelling, text entry or focus."
CLOSE_WINDOW_REASON = "Alt+F4 closes the window."
CLIPBOARD_REASON = "Copy, cut and paste stay with text fields."
APP_COMMAND_REASON = "Ctrl+Shift+P opens the command palette."
UNSUPPORTED_REASON = "The Mesh Editor cannot use this key."
MODIFIER_ONLY_REASON = "This command takes Ctrl, Alt or Shift on its own; change it in the Mesh Editor."
CHORD_ONLY_REASON = "This command needs a key, not Ctrl, Alt or Shift on its own."


@dataclass(frozen=True, slots=True)
class HelperBinding:
    """A binding as the helper reads it: ``text`` in its spelling, or why it cannot take it."""

    text: str = ""
    reason: str = ""
    modifier_only: bool = False


def _split(text: str) -> tuple[list[str], str] | None:
    """Modifiers and key of ``Ctrl+Shift+A``; Qt writes the plus key as ``Ctrl++``."""

    if text == "+":
        return [], "+"
    if text.endswith("++"):
        head = text[:-2]
        return (head.split("+") if head else []), "+"
    parts = text.split("+")
    return parts[:-1], parts[-1]


def helper_binding(text: str) -> HelperBinding:
    """Translate a key chosen in Qt (or already in the helper's spelling) for the helper."""

    text = str(text or "").strip()
    split = _split(text) if text else None
    if split is None:
        return HelperBinding(reason=UNSUPPORTED_REASON)
    modifiers, key = split
    held: set[str] = set()
    numpad = False
    for modifier in modifiers:
        if modifier == "Num":
            numpad = True
            continue
        if modifier not in MODIFIERS or modifier in held:
            return HelperBinding(reason=UNSUPPORTED_REASON)  # Meta, or a modifier twice
        held.add(modifier)
    if not modifiers and key in MODIFIERS:
        return HelperBinding(text=key, modifier_only=True)
    if numpad:
        name = _QT_NUMPAD.get(key, "")
    elif key in NUMPAD_NAMES:
        name = key
    elif key.startswith("Numpad"):
        name = ""  # egui's own numpad spellings are refused by the helper
    else:
        name = _EGUI_NAMES.get(_QT_KEYS.get(key, key), "")
    if not name:
        return HelperBinding(reason=UNSUPPORTED_REASON)
    canonical = "+".join([m for m in MODIFIERS if m in held] + [name])
    if len(canonical) > MAX_CHORD_LENGTH:
        return HelperBinding(reason=UNSUPPORTED_REASON)
    reason = reserved_reason(held, name)
    return HelperBinding(text="" if reason else canonical, reason=reason)


#: The palette's chords in the helper's spelling; the keymap decides them (P12 E5).
_PALETTE_CHORDS: set[str] = {"Ctrl+Shift+P"}


def palette_chords(settings) -> list[str]:
    """The palette's current keys in the helper's spelling, for its theme payload.

    Also what ``reserved_reason`` refuses from now on, so Settings > Shortcuts and
    the helper's own editor keep the same rule.
    """

    from cdmw.services.keymap_store import load_keymap
    from cdmw.ui.commands.palette import PALETTE_COMMAND, PALETTE_KEYS

    keys = load_keymap(settings).get(PALETTE_COMMAND)
    chosen = list(keys) if keys is not None else [PALETTE_KEYS]
    chords = []
    _PALETTE_CHORDS.clear()  # the palette's own keys are not reserved against themselves
    for key in chosen:
        binding = helper_binding(key)
        if binding.text and not binding.modifier_only and binding.text not in chords:
            chords.append(binding.text)
    _PALETTE_CHORDS.clear()
    _PALETTE_CHORDS.update(chords)
    return chords


def reserved_reason(held: set[str], name: str) -> str:
    """``KeyChord::reserved_reason``: why the helper's own editor refuses this chord."""

    if name in _RESERVED_KEYS:
        return EDITING_KEY_REASON
    if "Alt" in held and name == "F4":
        return CLOSE_WINDOW_REASON
    if "Ctrl" in held and name in {"C", "V", "X"}:
        return CLIPBOARD_REASON
    chord = "+".join([*(m for m in MODIFIERS if m in held), name])
    if chord in _PALETTE_CHORDS:
        return APP_COMMAND_REASON
    return ""


def check_helper_keys(keys: list[str], *, takes_modifier: bool) -> tuple[list[str], str]:
    """The keys in the helper's spelling, or ``([], reason)`` when it would not take one of them."""

    result: list[str] = []
    for key in keys:
        binding = helper_binding(key)
        if binding.reason:
            return [], binding.reason
        if binding.modifier_only != takes_modifier:
            return [], MODIFIER_ONLY_REASON if takes_modifier else CHORD_ONLY_REASON
        if binding.text not in result:
            result.append(binding.text)
    return result, ""


def qt_key_text(helper_text: str) -> str:
    """A helper binding as Qt can show it in a key editor, or "" when Qt has no spelling for it."""

    split = _split(str(helper_text or ""))
    if split is None:
        return ""
    modifiers, key = split
    if key in NUMPAD_NAMES:
        reverse = {"NumDecimal": ".", "NumPlus": "+", "NumMinus": "-", "NumMultiply": "*", "NumDivide": "/",
                   "NumEnter": "Enter"}
        key = reverse.get(key, key[3:])
        modifiers = [*modifiers, "Num"]
    else:
        key = {"PageUp": "PgUp", "PageDown": "PgDown", "Insert": "Ins", "Delete": "Del", "Comma": ",",
               "Minus": "-", "Period": ".", "Plus": "+", "Equals": "=", "Semicolon": ";", "Backslash": "\\",
               "Slash": "/", "OpenBracket": "[", "CloseBracket": "]", "Backtick": "`", "Quote": "'"}.get(key, key)
    return "+".join([*modifiers, key])
