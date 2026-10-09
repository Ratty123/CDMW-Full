"""Versioned mod envelopes and explicit, non-transitive evidence claims."""
from dataclasses import dataclass, field
from typing import Mapping

from cdmw.domain.new_item.independent import IndependentItemError


@dataclass(frozen=True)
class EvidenceClaim:
    stage: str
    scope: str
    reference: str


@dataclass(frozen=True)
class CapabilityResult:
    capability: str
    version: int
    supported: bool
    constraints: tuple[str, ...]
    evidence: tuple[EvidenceClaim, ...] = ()


class UnsupportedCapability(IndependentItemError):
    def __init__(self, result):
        self.result = result
        super().__init__(f'Unsupported required capability {result.capability}@{result.version}: '
                         + '; '.join(result.constraints))


def capability_result(name, version):
    if name == 'item.legacy' and type(version) is int and version == 1:
        return CapabilityResult(name, version, True,
            ('One frozen v1 equipment recipe with exact game dependency hashes.',
             'Existing item allocation, ownership and publication rules apply.',
             'Game and save behavior require separate evidence.'),
            (EvidenceClaim('adapter', 'Frozen v1 recipe lowering', 'independent_wire_v1.py'),
             EvidenceClaim('synthetic', 'Physical and virtual v2 legacy lowering', 'tests/test_independent_item_v2.py')))
    return CapabilityResult(name, version, False, ('No registered adapter for this capability version.',))


@dataclass(frozen=True)
class IndependentModPackage:
    manifest: Mapping
    blobs: Mapping[str, bytes]
    digest: str
    artifact_digest: str = field(default='', compare=False)

    @property
    def identity(self):
        return self.manifest['identity']

    @property
    def title(self):
        return self.manifest['title']

    @property
    def dependencies(self):
        return self.manifest['dependencies']

    @property
    def recipe(self):
        """Explicit bridge to the sole currently implemented module adapter."""
        modules = self.manifest['modules']
        if len(modules) != 1 or modules[0]['type'] != 'item.legacy':
            raise IndependentItemError('This mod has no single legacy item recipe.')
        return modules[0]['data']
