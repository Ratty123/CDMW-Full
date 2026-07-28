"""Driven bones: find a character's `.papr`, group it into chains, and ship edits.

A `.papr` holds the bones that follow *other bones* instead of an animation clip.

It is worth being precise about what that turns out to be, because the `B_Jiggle_*`
names in the two smallest creature rigs invite the wrong guess. Counted across all 471
chains in the twenty shipped rigs: **259 are corrective deformation** (`UpperFMuscle`,
`Bip01 L Knee_Sub`, `Thigh_Front`, twist bones), 67 are pivots, 56 are exposed
transforms, 29 are mechanical parts on the golems and tanks, and **only 5 are jiggle** --
on the dog and the bear. No rig contains hair or cloth.

So on a player character this file is the *deformation* rig: how a muscle bulges and how
a knee creases as the body moves. That is what a physique or body mod needs to touch, and
it is a different thing from the hair physics the `Jiggle` names suggest.

Two things make it presentable rather than a flat list of 437 bones:

**Chains, not bones.** A driven bone hangs off a parent that is often itself driven, so
entries are grouped by walking parent links up to the first bone that is not itself
driven. That root is the chain's anchor, and its name is what the chain is called.

**Strength, not weights.** Every driven bone carries influence weights as whole
percentages. A chain's strength is the mean of its weights, which is the number worth
putting on a slider; moving the slider scales every weight in the chain and rounds back
to whole percent, because that is the only shape the locator can find again.

Nothing here interprets a block's tag stream. `cdmw/core/papr_format.py` carries those
bytes verbatim, so an edit touches names, transforms and weights and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from cdmw.core.papr_format import (
    ConstraintEntry,
    PaprDocument,
    PaprFormatError,
    WeightSite,
    encode_papr,
    find_weight_sites,
    parse_papr,
    scale_weights,
    set_weights,
)

from . import corpus

#: What a chain is for, read off its bone names. Counted across the twenty shipped rigs:
#: 259 deformation, 67 pivot, 56 exposed transform, 29 mechanical, 5 jiggle, 55 other.
#: There is no hair or cloth in any of them.
#:
#: This ordering matters: `jiggle` is checked before `deform` because `B_Jiggle_M_Pelvis`
#: would otherwise match on nothing and `Bip01 L Knee_Sub` must not read as jiggle.
_CATEGORY_HINTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("jiggle", ("jiggle",)),
    ("soft", ("hair", "cloth", "skirt", "cape", "cloak", "braid", "tail")),
    ("expose", ("exposetransform",)),
    ("mechanical", ("syl", "piston", "golem", "machine", "robot", "track")),
    ("deformation", ("muscle", "knee", "elbow", "twist", "joint",
                     "_front", "_in", "_side", "_back", "_sub")),
)

#: Shown in the panel so a modder knows what a row governs before touching it.
CATEGORY_LABELS = {
    "deformation": "Deformation — muscle bulge and joint creasing",
    "jiggle": "Jiggle — secondary motion that swings",
    "soft": "Soft body — hair or cloth",
    "expose": "Exposed transform — engine plumbing",
    "pivot": "Pivot — a helper the rig rotates around",
    "mechanical": "Mechanical — pistons and moving machine parts",
    "other": "Unclassified",
}

#: Categories a modder is likely to want to change, in the order they should appear.
_CATEGORY_ORDER = ("jiggle", "soft", "deformation", "mechanical", "pivot", "expose", "other")


def classify_chain(name: str, anchor: str = "") -> str:
    """What a chain is for, from its names. Ordering the list only; never a filter."""

    text = f"{name} {anchor}".lower()
    for category, hints in _CATEGORY_HINTS:
        if any(hint in text for hint in hints):
            return category
    if name.lower().startswith("p_") or "_pivot" in text:
        return "pivot"
    return "other"


@dataclass(frozen=True)
class ChainMember:
    """One driven bone inside a chain."""

    entry_index: int
    name: str
    parent: str
    weights: Tuple[WeightSite, ...]
    #: `decoded` when every byte of this bone's config block is accounted for.
    shape: str = "partial"
    #: The driver formulas this bone runs, e.g. `amin(Local_Euler_Z*5.5+20) 8`.
    formulas: Tuple[str, ...] = ()

    @property
    def strength(self) -> float:
        if not self.weights:
            return 0.0
        return sum(site.value for site in self.weights) / len(self.weights)


@dataclass(frozen=True)
class Chain:
    """A run of driven bones hanging off one undriven anchor."""

    anchor: str
    members: Tuple[ChainMember, ...]

    @property
    def name(self) -> str:
        return self.members[0].name if self.members else self.anchor

    @property
    def bone_count(self) -> int:
        return len(self.members)

    @property
    def weight_count(self) -> int:
        return sum(len(member.weights) for member in self.members)

    @property
    def strength(self) -> float:
        """Mean influence across the chain, the number a slider should show."""

        sites = [site for member in self.members for site in member.weights]
        if not sites:
            return 0.0
        return sum(site.value for site in sites) / len(sites)

    @property
    def category(self) -> str:
        return classify_chain(self.name, self.anchor)

    @property
    def label(self) -> str:
        return CATEGORY_LABELS.get(self.category, CATEGORY_LABELS["other"])

    @property
    def fully_understood(self) -> bool:
        """Every bone in the chain has a config block whose every byte is decoded.

        Edits are equally safe either way -- undecoded bytes are carried verbatim --
        but a modder is entitled to know which is which before trusting a result.
        """

        return bool(self.members) and all(m.shape == "decoded" for m in self.members)

    def sites(self) -> Tuple[WeightSite, ...]:
        return tuple(site for member in self.members for site in member.weights)

    @property
    def formulas(self) -> Tuple[str, ...]:
        """Every driver formula in the chain, deduplicated, in member order.

        This is the chain's actual behaviour rather than a list of who it follows, and it
        was unreadable until `papr_block` decoded the expression payload.
        """

        seen: dict[str, None] = {}
        for member in self.members:
            for text in member.formulas:
                seen.setdefault(text, None)
        return tuple(seen)


@dataclass(frozen=True)
class RigConstraints:
    """A parsed `.papr` plus the chain view of it."""

    game_path: str
    document: PaprDocument
    chains: Tuple[Chain, ...]

    @property
    def bone_count(self) -> int:
        return len(self.document.entries)

    def chain_named(self, name: str) -> Optional[Chain]:
        for chain in self.chains:
            if chain.name == name:
                return chain
        return None


def build_chains(document: PaprDocument) -> Tuple[Chain, ...]:
    """Group driven entries into chains anchored on the first undriven parent."""

    by_name: dict[str, ConstraintEntry] = {}
    index_of: dict[str, int] = {}
    for index, entry in enumerate(document.entries):
        by_name[entry.name] = entry
        index_of[entry.name] = index

    sites_by_entry: dict[int, list[WeightSite]] = {}
    for site in find_weight_sites(document):
        sites_by_entry.setdefault(site.entry_index, []).append(site)

    def anchor_of(entry: ConstraintEntry) -> str:
        seen = {entry.name}
        current = entry
        while True:
            parent = by_name.get(current.parent)
            if parent is None or not parent.driven or parent.name in seen:
                return current.parent
            seen.add(parent.name)
            current = parent

    grouped: dict[str, list[ChainMember]] = {}
    for index, entry in enumerate(document.entries):
        if not entry.driven:
            continue
        # One decode per entry, reused for both the shape and the formulas: `block_shape`
        # decodes to answer, so asking it separately would do the work twice per row.
        decoded = entry.decode()
        member = ChainMember(
            entry_index=index,
            name=entry.name,
            parent=entry.parent,
            weights=tuple(sites_by_entry.get(index, ())),
            shape="decoded" if decoded.complete else "partial",
            formulas=tuple(e.text for e in decoded.expressions),
        )
        grouped.setdefault(anchor_of(entry), []).append(member)

    chains = [
        Chain(anchor=anchor, members=tuple(sorted(members, key=lambda m: m.entry_index)))
        for anchor, members in grouped.items()
    ]
    # The categories worth tuning first, then the biggest chains inside each.
    order = {name: index for index, name in enumerate(_CATEGORY_ORDER)}
    chains.sort(key=lambda c: (order.get(c.category, 99), -c.bone_count, c.name))
    return tuple(chains)


def load_constraints(data: bytes, game_path: str) -> RigConstraints:
    document = parse_papr(data, name=game_path)
    return RigConstraints(game_path=game_path, document=document, chains=build_chains(document))


# ------------------------------------------------------------------ finding the file


def constraint_paths(game_root: Optional[Path] = None) -> Tuple[str, ...]:
    """Every `.papr` in the archives, read from the tables without extracting."""

    return tuple(corpus.archive_paths_matching(".papr"))


def constraint_path_for_model(model_path: str, known: Sequence[str]) -> Optional[str]:
    """The `.papr` that belongs to a model, by shared directory then by stem.

    A rig's constraint file sits beside its model: `.../1_phm/phm_01.papr` next to the
    `1_phm` model directory. Matching on the directory is what makes the panel able to
    follow the Studio's current character without the user finding the file.
    """

    if not model_path:
        return None
    normalized = corpus.normalize_game_path(model_path)
    directory = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
    stem = normalized.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    in_dir = [p for p in known if p.rsplit("/", 1)[0] == directory]
    if in_dir:
        exact = [p for p in in_dir if p.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower() == stem]
        return (exact or in_dir)[0]
    # Fall back to a rig whose directory is a prefix of the model's.
    parents = [p for p in known if directory.startswith(p.rsplit("/", 1)[0] + "/")]
    if parents:
        parents.sort(key=lambda p: -len(p))
        return parents[0]
    return None


# --------------------------------------------------------------------------- editing


@dataclass(frozen=True)
class ChainEdit:
    """A requested strength for one chain, as a percentage of the shipped value."""

    chain: str
    factor: float


def apply_chain_edits(
    rig: RigConstraints, edits: Iterable[ChainEdit]
) -> tuple[RigConstraints, Tuple[str, ...]]:
    """Scale each named chain's weights. Returns the new rig and any unknown names."""

    document = rig.document
    missing: list[str] = []
    for edit in edits:
        chain = rig.chain_named(edit.chain)
        if chain is None:
            missing.append(edit.chain)
            continue
        sites = chain.sites()
        if not sites:
            continue
        # Re-locate against the working document: offsets are stable, values are not.
        current = {(s.entry_index, s.block_offset): s for s in find_weight_sites(document)}
        live = [current[(s.entry_index, s.block_offset)] for s in sites
                if (s.entry_index, s.block_offset) in current]
        document = scale_weights(document, live, edit.factor)
    return (
        RigConstraints(game_path=rig.game_path, document=document, chains=build_chains(document)),
        tuple(missing),
    )


def set_chain_strength(
    rig: RigConstraints, chain_name: str, strength: float
) -> RigConstraints:
    """Set a chain's mean influence to `strength` percent."""

    chain = rig.chain_named(chain_name)
    if chain is None:
        raise PaprFormatError(f"no chain named {chain_name!r}")
    current = chain.strength
    if current <= 0:
        raise PaprFormatError(f"chain {chain_name!r} has no weights to scale")
    rig, _missing = apply_chain_edits(rig, [ChainEdit(chain_name, strength / current)])
    return rig


def freeze_chain(rig: RigConstraints, chain_name: str) -> RigConstraints:
    """Take all secondary motion out of one chain."""

    return apply_chain_edits(rig, [ChainEdit(chain_name, 0.0)])[0]


# ------------------------------------------------------------------------- exporting


def changed_files(original: bytes, rig: RigConstraints) -> Mapping[str, bytes]:
    """`{game path: bytes}` for the packager, empty when nothing actually changed."""

    rebuilt = encode_papr(rig.document)
    if rebuilt == original:
        return {}
    return {rig.game_path: rebuilt}


#: What the panel is allowed to promise. Kept next to the code that enforces it so the
#: two cannot drift, and surfaced verbatim in the UI's "What you can do here" box.
#: Shown at the top of the panel. The single most useful thing the tool can tell a
#: modder about this format, and it is bad news, so it goes first rather than in a
#: footnote. See the module docstring of `cdmw/core/papr_format.py` for the evidence.
LOADED_BY_GAME_WARNING = (
    "No evidence the game reads .papr — edits here may well do nothing. The live "
    "equivalents are plain XML: jiggledescriptor.xml and posemodifierdata.xml."
)

#: The evidence behind the warning. On the warning's tooltip rather than in it: the
#: banner has to stay two lines, because at six it pushed the panel's own controls into
#: each other, and a modder needs the conclusion far more often than the proof.
LOADED_BY_GAME_EVIDENCE = (
    "The extension appears nowhere in any shipped binary, though pac, pab and paseq all "
    "do, and neither does the Local_Euler / ExposeTransform vocabulary inside these "
    "files. They look like 3ds Max rig exports left behind in the archives. See the "
    "module docstring of cdmw/core/papr_format.py for the full check."
)

#: `(allowed, label, why)`. The label is deliberately short: it is rendered in a
#: two-column box inside a panel that is itself in a splitter, so anything longer wraps
#: to two lines and the box clips it. The reason goes in `why`, which the UI shows as a
#: tooltip, and the one thing a modder must not miss is stated in full underneath as
#: `WHAT_THIS_TAB_IS_FOR` rather than crammed into a bullet.
CAPABILITIES: Tuple[Tuple[bool, str, str], ...] = (
    (True, "Soften or stiffen a chain",
     "Scales every follow weight in the chain, in whole percent."),
    (True, "Switch a chain off",
     "Zeroes the weights, so the bones stop reacting to the body at all."),
    (True, "Rename a bone or reparent it",
     "Same-length names are patched in place; the parent is a plain string too."),
    (True, "Move a bone's rest position",
     "Rewrites the chain's rest transform, the pose it settles back to."),
    (False, "Add a new chain",
     "A new chain needs a config block this tool cannot synthesise."),
    (False, "Edit driver expressions",
     "The expression text is authoring leftovers; nothing evaluates it."),
    (False, "Count on it changing the game",
     "See the warning at the top of this tab: .papr looks like dead content."),
)

#: The use case, in two sentences, because "what is this tab for" is the question the
#: warning above provokes and used to leave unanswered.
WHAT_THIS_TAB_IS_FOR = (
    "What this tab is for: reading how the shipped rigs are put together, and "
    "experimenting with them. Only 20 characters ship a .papr at all. For secondary-motion "
    "changes that definitely take effect, use Rig behaviour. Nothing here previews in the "
    "viewport either — the game solves secondary motion at runtime, so export and look."
)


def export_packages(
    rig: RigConstraints,
    original: bytes,
    *,
    out_root,
    name: str,
    author: str = "",
    version: str = "1.0.0",
    description: str = "",
    managers: Sequence[str] = ("CDUMM", "DMM", "JMM"),
):
    """Write one mod package per manager. Returns the results, or () when unchanged."""

    files = changed_files(original, rig)
    if not files:
        return ()
    from .ops import Plan
    from .packaging import PackageMetadata, build_all

    metadata = PackageMetadata(
        name=name,
        version=version,
        author=author,
        description=description or f"Secondary motion tuning for {rig.game_path}.",
    )
    return tuple(
        build_all(
            Plan(name=name),
            files,
            metadata,
            out_root=Path(out_root),
            managers=tuple(managers),
        )
    )


def describe_changes(original: RigConstraints, edited: RigConstraints) -> Tuple[str, ...]:
    """Plain-English lines saying what an export will contain."""

    lines: list[str] = []
    before = {chain.name: chain for chain in original.chains}
    for chain in edited.chains:
        was = before.get(chain.name)
        if was is None or abs(was.strength - chain.strength) < 0.5:
            continue
        if chain.strength <= 0:
            lines.append(f"{chain.name}: secondary motion switched off (was {was.strength:.0f}%)")
        else:
            lines.append(
                f"{chain.name}: {was.strength:.0f}% -> {chain.strength:.0f}% "
                f"across {chain.bone_count} bone(s)"
            )
    return tuple(lines)
