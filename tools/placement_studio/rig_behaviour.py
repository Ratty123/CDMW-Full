"""Rig behaviour: the pose-modifier settings that apply to one character.

`posemodifierdata.xml` is keyed by `.pab` skeleton and one block often serves several
characters, so the useful question is never "what is in this file" (2,779 settings) but
"what applies to the character I am looking at" (223 for the player).

That framing is the whole of this module: resolve the current rig to a `.pab` key, pull
the settings for it, group them by what they control, and hand back a payload for the
packager. `cdmw/core/posemodifier_xml.py` owns the file format and the surgical edits.

Unlike `.papr`, this file is demonstrably read by the game -- the engine's
`pa::engineScript::PoseModifier*` classes are named after its sections -- so an edit
here is expected to change behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple

from cdmw.core.posemodifier_xml import (
    PoseModifierDocument,
    PoseModifierError,
    Setting,
    changed_files,
    encode_posemodifier_xml,
    parse_posemodifier_xml,
    scale_setting,
    set_setting,
)

from . import corpus

GAME_PATH = "character/descriptors/posemodifierdata/posemodifierdata.xml"

#: What each section governs, in words a modder can act on. The engine's own names are
#: accurate but tell you nothing unless you already know the system.
SECTION_LABELS: Mapping[str, str] = {
    "Vehicle": "Carts and mounts — wheel size, suspension travel, steering limits",
    "AimIK": "How far the body turns to aim at a target",
    "RootBoneIK": "Whole-body lean and tilt when moving or on a slope",
    "WorldSpaceSpecificBoneModifier": "Bones pinned to world space rather than the rig",
    "SpineTrain": "How the spine lags and follows when the character turns",
    "LimbIK": "Arm and leg IK: reach, bending axis, and solver setup",
    "LookAt": "Head and eye tracking — how far they turn, and when they give up",
    "Multileg": "Many-legged gait: hips, knees, ankles, foot planting",
    "FishingRod": "Fishing rod bend",
    "BoneAim": "A single bone aimed at a target",
    "Harness": "Harness and tack on ridden animals",
}

#: Sections worth showing first: the ones a character mod is most likely to want.
_SECTION_ORDER = (
    "LookAt", "AimIK", "SpineTrain", "RootBoneIK", "LimbIK",
    "Multileg", "Vehicle", "Harness", "FishingRod", "BoneAim",
    "WorldSpaceSpecificBoneModifier",
)


@dataclass(frozen=True)
class RigBehaviour:
    """The descriptor plus the skeleton it is being viewed through."""

    document: PoseModifierDocument
    pab: str
    original: bytes

    @property
    def settings(self) -> Tuple[Setting, ...]:
        rows = list(self.document.for_key(self.pab)) if self.pab else list(self.document.settings)
        order = {name: index for index, name in enumerate(_SECTION_ORDER)}
        rows.sort(key=lambda s: (order.get(s.section, 99), s.path, s.attribute))
        return tuple(rows)

    @property
    def sections(self) -> Tuple[str, ...]:
        seen: dict[str, None] = {}
        for setting in self.settings:
            seen.setdefault(setting.section, None)
        return tuple(seen)

    def selectable_keys(self) -> Tuple[str, ...]:
        """Every skeleton worth offering, including ones that only appear as disabled.

        A creature listed solely in a `DisabledKeyList` has no settings of its own, so
        keying off the settings alone would make it unselectable -- and that is exactly
        the character whose owner needs to be told the section is switched off.
        """

        seen = {key: None for key in self.document.keys()}
        for keys in self.document.disabled.values():
            for key in keys:
                seen.setdefault(key, None)
        return tuple(sorted(seen))

    def disabled_sections(self) -> Tuple[str, ...]:
        """Sections the file explicitly switches off for this skeleton.

        Worth surfacing loudly: a modder editing LookAt for a creature that has LookAt
        in its disabled list would see no change and have no way to know why.
        """

        wanted = self.pab.lower()
        return tuple(
            section for section, keys in self.document.disabled.items()
            if any(key.lower() == wanted for key in keys)
        )

    def changed(self) -> Mapping[str, bytes]:
        return changed_files(self.original, self.document, GAME_PATH)


def guide():
    """What the Rig behaviour tab is for, as the dialog shows it.

    The counterpart to `constraints.guide`, and deliberately the opposite badge: the
    engine's own `pa::engineScript::PoseModifier*` classes are named after this file's
    sections, so an edit here is expected to change the game.
    """

    from .what_is_this import Guide, Section

    return Guide(
        title="Rig behaviour — what is this for?",
        badge="TAKES EFFECT",
        badge_kind="live",
        summary="The game reads this file, so edits here do change behaviour.",
        sections=(
            Section(
                heading="What it controls",
                body="Runtime pose modifiers, keyed by .pab skeleton. The panel shows only "
                     "the settings that apply to the character on screen — 223 of "
                     "2,779 for the player.",
                examples=(
                    ("LookAt", SECTION_LABELS["LookAt"]),
                    ("SpineTrain", SECTION_LABELS["SpineTrain"]),
                    ("LimbIK", SECTION_LABELS["LimbIK"]),
                    ("RootBoneIK", SECTION_LABELS["RootBoneIK"]),
                    ("Vehicle", SECTION_LABELS["Vehicle"]),
                ),
            ),
            Section(
                heading="Editing a value",
                body="Values are text, and the shape is kept. Pick a row, change the value "
                     "box, press Apply; the multiply buttons scale every number in a value "
                     "at once.",
                examples=(
                    ("-70 70", "a range: two numbers"),
                    ("8 8 30", "a vector: three numbers"),
                    ("×2 on -70 70", "becomes -140 140, still a range"),
                ),
            ),
            Section(
                heading="Two things that will surprise you",
                bullets=(
                    "One block often serves several characters. Changing the player's "
                    "LookAt also changes it for phw_01, ptm_01 and pdem_01 — the "
                    "Applies-to column names every skeleton sharing the block.",
                    "A section can be switched off for a skeleton by the file's "
                    "DisabledKeyList. Editing it then does nothing and says nothing, so the "
                    "panel puts a banner up when that applies to the character you picked.",
                ),
            ),
            Section(
                heading="How it ships",
                body="Export writes the whole descriptor back with only the spans you "
                     "changed rewritten, so the file keeps its hand-authored formatting, "
                     "comments and byte layout.",
            ),
        ),
    )


def load_rig_behaviour(data: bytes, pab: str = "") -> RigBehaviour:
    return RigBehaviour(
        document=parse_posemodifier_xml(data, name=GAME_PATH),
        pab=pab,
        original=bytes(data),
    )


def read_from_archives(game_root: Optional[Path] = None) -> bytes:
    """Pull the descriptor straight out of the archives."""

    from cdmw.core.archive_extraction import read_archive_entry_data

    root = Path(game_root) if game_root is not None else corpus.game_root()
    for _package, entry in corpus._iter_archive_entries(root):
        if corpus.normalize_game_path(entry.path) == GAME_PATH:
            data, _decompressed, _note = read_archive_entry_data(entry)
            return data
    raise PoseModifierError(f"{GAME_PATH} is not in the archives")


def pab_for_model(model: str, known: Sequence[str]) -> Optional[str]:
    """Match the Studio's current model to a `.pab` key in the descriptor.

    The Studio names a character by its model (`phm_01`), the descriptor keys on the
    skeleton file (`phm_01.pab`), and the file is inconsistent about case -- it carries
    both `cd_m0050_00_nuclear_fusion.pab` and `CD_M0050_00_Nuclear_Fusion.pab`.
    """

    if not model:
        return None
    stem = Path(model).name
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    wanted = f"{stem}.pab".lower()
    for key in known:
        if key.lower() == wanted:
            return key
    return None


def apply_edit(rig: RigBehaviour, setting: Setting, value: str) -> RigBehaviour:
    """Set one value, re-reading the document so every span stays valid."""

    document = set_setting(rig.document, setting, value)
    return RigBehaviour(document=document, pab=rig.pab, original=rig.original)


def apply_scale(rig: RigBehaviour, setting: Setting, factor: float) -> RigBehaviour:
    document = scale_setting(rig.document, setting, factor)
    return RigBehaviour(document=document, pab=rig.pab, original=rig.original)


def describe_changes(before: RigBehaviour, after: RigBehaviour) -> Tuple[str, ...]:
    """Plain lines naming what an export will contain."""

    old = {s.span[0]: s for s in before.document.settings}
    lines = []
    for setting in after.document.settings:
        was = old.get(setting.span[0])
        if was is not None and was.value != setting.value:
            lines.append(f"{setting.section} {setting.label}: {was.value} -> {setting.value}")
    return tuple(lines)


def export_packages(
    rig: RigBehaviour,
    *,
    out_root,
    name: str,
    author: str = "",
    version: str = "1.0.0",
    managers: Sequence[str] = ("CDUMM", "DMM", "JMM"),
):
    """Write one mod package per manager. Returns the results, or () when unchanged."""

    files = rig.changed()
    if not files:
        return ()
    from .ops import Plan
    from .packaging import PackageMetadata, build_all

    metadata = PackageMetadata(
        name=name,
        version=version,
        author=author,
        description=f"Pose-modifier tuning for {rig.pab or 'all rigs'}.",
    )
    return tuple(
        build_all(Plan(name=name), files, metadata, out_root=Path(out_root),
                  managers=tuple(managers))
    )
