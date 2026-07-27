"""Secondary motion: find a character's `.papr`, group it into chains, and ship edits.

A `.papr` is the rig's *secondary* motion — the bones that follow other bones instead of
an animation clip. Hair, cloth, tassels, pistons, `B_Jiggle_*`. This module turns one
into something a person can reason about and then exports the result as a mod.

Two things make it presentable rather than a flat list of 437 bones:

**Chains, not bones.** A driven bone hangs off a parent that is often itself driven. A
braid is six entries in the file and one thing in the modder's head, so entries are
grouped by walking parent links up to the first bone that is not itself driven. That
root is the chain's anchor, and its name is what the chain is called.

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

#: Chains whose anchor name contains one of these read as soft furnishings. Used only to
#: order the list so the interesting things are at the top, never to filter.
_SOFT_HINTS = ("jiggle", "hair", "cloth", "skirt", "tail", "cape", "cloak", "braid")


@dataclass(frozen=True)
class ChainMember:
    """One driven bone inside a chain."""

    entry_index: int
    name: str
    parent: str
    weights: Tuple[WeightSite, ...]

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
    def soft(self) -> bool:
        text = f"{self.anchor} {self.name}".lower()
        return any(hint in text for hint in _SOFT_HINTS)

    def sites(self) -> Tuple[WeightSite, ...]:
        return tuple(site for member in self.members for site in member.weights)


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
        member = ChainMember(
            entry_index=index,
            name=entry.name,
            parent=entry.parent,
            weights=tuple(sites_by_entry.get(index, ())),
        )
        grouped.setdefault(anchor_of(entry), []).append(member)

    chains = [
        Chain(anchor=anchor, members=tuple(sorted(members, key=lambda m: m.entry_index)))
        for anchor, members in grouped.items()
    ]
    # Soft furnishings first, then the biggest chains: the things worth tuning on top.
    chains.sort(key=lambda c: (not c.soft, -c.bone_count, c.name))
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
