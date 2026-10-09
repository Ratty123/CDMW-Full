"""Data-only save-origin policy; no game observer, migration or launch authority.

A trusted commit verifier is an explicit dependency. There is no production
verifier yet: hashes, backup metadata and operator captures cannot supply one.
Even a matched context is not a certificate of successful load or save safety.
"""
from dataclasses import dataclass
import re
from typing import Callable

from cdmw.domain.virtual_save_evidence import checksum, encoded


def _hash(value, *, optional=False):
    if not (optional and value is None) and (
            not isinstance(value, str) or re.fullmatch('[a-f0-9]{64}', value) is None):
        raise ValueError('Save lineage requires an exact SHA-256 identity.')


@dataclass(frozen=True)
class SaveSetSnapshot:
    # Relative-name hash, byte count and content hash. Paths/timestamps are not identity.
    files: tuple[tuple[str, int, str], ...]
    slot_layout_sha256: str | None = None
    membership_complete: bool = False

    def __post_init__(self):
        _hash(self.slot_layout_sha256, optional=True)
        if type(self.membership_complete) is not bool or not isinstance(self.files, tuple) or len(self.files) > 4096:
            raise ValueError('Invalid save-set membership.')
        names, total = set(), 0
        for row in self.files:
            if not isinstance(row, tuple) or len(row) != 3:
                raise ValueError('Invalid save-file fingerprint.')
            name, size, content = row
            _hash(name)
            _hash(content)
            if name in names or type(size) is not int or size < 0:
                raise ValueError('Invalid or duplicate save-file fingerprint.')
            names.add(name)
            total += size
        if total > 4 * 1024 * 1024 * 1024:
            raise ValueError('Save set exceeds the supported observation size.')
        object.__setattr__(self, 'files', tuple(sorted(self.files)))

    @property
    def identity(self):
        return checksum(encoded({'format': 'cdmw_save_set_identity_v1', 'files': self.files,
                                 'slot_layout': self.slot_layout_sha256,
                                 'membership_complete': self.membership_complete}))


@dataclass(frozen=True)
class SaveProviderRequirement:
    identity: str
    content_sha256: str
    bindings_sha256: str
    persistence_sha256: str | None = None

    def __post_init__(self):
        if not isinstance(self.identity, str) or re.fullmatch('[a-f0-9]{32}', self.identity) is None:
            raise ValueError('Save requirements need a package UUID.')
        _hash(self.content_sha256)
        _hash(self.bindings_sha256)
        _hash(self.persistence_sha256, optional=True)


def _providers(values):
    if (not isinstance(values, tuple) or len(values) > 4096
            or any(not isinstance(value, SaveProviderRequirement) for value in values)
            or len({value.identity for value in values}) != len(values)):
        raise ValueError('Invalid or duplicate save-provider requirements.')
    return tuple(sorted(values, key=lambda value: value.identity))


@dataclass(frozen=True)
class SaveContextContract:
    executable_sha256: str
    runtime_sha256: str
    compilation_sha256: str
    persistence_sha256: str | None
    providers: tuple[SaveProviderRequirement, ...] = ()

    def __post_init__(self):
        for value in (self.executable_sha256, self.runtime_sha256, self.compilation_sha256):
            _hash(value)
        _hash(self.persistence_sha256, optional=True)
        object.__setattr__(self, 'providers', _providers(self.providers))


@dataclass(frozen=True)
class SaveCommitWitness:
    """Proposed evidence; constructing this object does not verify its claims.

    The verifier must establish slot/commit protocol, process birth/image/session,
    all writer events and any claimed parent ancestry/requirements coverage.
    No caller may substitute the currently selected or backed-up profile.
    """
    save_set_sha256: str
    context: SaveContextContract
    protocol_sha256: str
    evidence_sha256: str
    writer_pid: int
    writer_birth_sha256: str
    writer_image_sha256: str
    session_token: str
    finalized: bool = False
    events_complete: bool = False
    foreign_writer: bool = False
    interrupted: bool = False
    parent_save_set_sha256: str | None = None
    parent_origin: str = 'unknown'  # unknown, verified, or root (a proven fresh save)
    requirements_coverage: str = 'unknown'
    inherited_requirements: tuple[SaveProviderRequirement, ...] = ()

    def __post_init__(self):
        for value in (self.save_set_sha256, self.protocol_sha256, self.evidence_sha256, self.writer_birth_sha256,
                      self.writer_image_sha256):
            _hash(value)
        _hash(self.parent_save_set_sha256, optional=True)
        if (not isinstance(self.context, SaveContextContract) or type(self.writer_pid) is not int
                or self.writer_pid <= 0 or not isinstance(self.session_token, str)
                or re.fullmatch('[a-f0-9]{32}', self.session_token) is None
                or any(type(v) is not bool for v in (self.finalized, self.events_complete,
                                                    self.foreign_writer, self.interrupted))
                or self.parent_origin not in ('unknown', 'verified', 'root')
                or self.requirements_coverage not in ('unknown', 'complete')
                or (self.parent_origin == 'verified' and self.parent_save_set_sha256 is None)
                or (self.parent_origin == 'root' and self.parent_save_set_sha256 is not None)):
            raise ValueError('Invalid save-commit evidence.')
        object.__setattr__(self, 'inherited_requirements', _providers(self.inherited_requirements))


@dataclass(frozen=True)
class SaveLineageDecision:
    status: str  # unknown, refused, context-match; never a save-safety certificate
    reasons: tuple[str, ...]
    producer_evidence: str = 'unknown'
    context: str = 'unknown'


def assess_lineage(snapshot: SaveSetSnapshot, target: SaveContextContract | None,
                   witness: SaveCommitWitness | None = None, *,
                   verify_commit: Callable[[SaveSetSnapshot, SaveCommitWitness], bool] | None = None):
    """Apply exact-context policy to independently verified commit evidence.

    `verify_commit` belongs to a future trusted observer/adapter, not JSON input or
    an operator checkbox. No such game adapter is installed by this module. An
    exception from a verifier propagates; verification errors cannot clear a save.
    Unknown ancestry survives a new managed write. No migration is admitted here.
    """
    if not isinstance(snapshot, SaveSetSnapshot) or (target is not None and not isinstance(target, SaveContextContract)):
        raise ValueError('Invalid save-lineage context.')
    missing = []
    if not snapshot.files:
        missing.append('empty-save-set')
    if not snapshot.membership_complete:
        missing.append('unknown-slot-membership')
    if snapshot.slot_layout_sha256 is None:
        missing.append('unknown-slot-layout')
    if witness is None:
        return SaveLineageDecision('unknown', tuple(missing + ['unknown-producer']))
    if not isinstance(witness, SaveCommitWitness):
        raise ValueError('Invalid save-commit evidence.')
    if witness.save_set_sha256 != snapshot.identity:
        missing.append('commit-does-not-match-save-set')
    if not witness.finalized:
        missing.append('unfinalized-save-commit')
    if not witness.events_complete:
        missing.append('incomplete-save-events')
    if witness.foreign_writer:
        missing.append('foreign-save-writer')
    if witness.interrupted:
        missing.append('interrupted-save-commit')
    if witness.writer_image_sha256 != witness.context.executable_sha256:
        missing.append('writer-image-mismatch')
    if missing:
        return SaveLineageDecision('unknown', tuple(missing))
    if verify_commit is None or verify_commit(snapshot, witness) is not True:
        return SaveLineageDecision('unknown', ('unverified-save-commit',))
    if target is None:
        return SaveLineageDecision('unknown', ('unknown-target-context',), 'verified-commit')

    reasons = []
    source = witness.context
    for key in ('executable_sha256', 'runtime_sha256', 'compilation_sha256', 'persistence_sha256'):
        if getattr(source, key) != getattr(target, key):
            reasons.append('context-mismatch:' + key)
    required = {row.identity: row for row in source.providers}
    for row in witness.inherited_requirements:
        if row.identity in required and row != required[row.identity]:
            reasons.append('contradictory-provider-requirement:' + row.identity)
        else:
            required[row.identity] = row
    available = {row.identity: row for row in target.providers}
    for identity, row in sorted(required.items()):
        if identity not in available:
            reasons.append('missing-required-provider:' + identity)
        elif row != available[identity]:
            reasons.append('changed-provider-contract:' + identity)
    # Additional providers can affect global behavior; no compatibility edge is
    # currently proven merely because all original identities are still present.
    for identity in sorted(set(available) - {row.identity for row in source.providers}):
        reasons.append('unproven-added-provider:' + identity)
    if reasons:
        return SaveLineageDecision('refused', tuple(reasons), 'verified-commit', 'mismatch')

    unknown = []
    if source.persistence_sha256 is None or any(row.persistence_sha256 is None for row in required.values()):
        unknown.append('unknown-persistence-contract')
    if witness.parent_origin == 'unknown':
        unknown.append('unknown-parent-origin')
    if witness.requirements_coverage != 'complete':
        unknown.append('incomplete-requirements-coverage')
    if unknown:
        return SaveLineageDecision('unknown', tuple(unknown), 'verified-commit', 'match')
    return SaveLineageDecision('context-match', (), 'verified-commit', 'match')
