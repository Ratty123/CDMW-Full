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
    if name == 'package.links' and type(version) is int and version == 1:
        return CapabilityResult(name, version, True,
            ('Exact UUID/release/content pins within one deployment; cycles refuse.',
             'Typed borrowed installation references to owned legacy items only.',
             'No game-byte reference relocation, runtime lifetime or save migration is implied.'),
            (EvidenceClaim('adapter', 'Package graph and typed export closure', 'package_links.py'),
             EvidenceClaim('synthetic', 'Dependency admission, composition and removal', 'tests/test_independent_package_links.py')))
    if name == 'item.legacy' and type(version) is int and version == 1:
        return CapabilityResult(name, version, True,
            ('One frozen v1 equipment recipe with exact game dependency hashes.',
             'Existing item allocation, ownership and publication rules apply.',
             'Game and save behavior require separate evidence.'),
            (EvidenceClaim('adapter', 'Frozen v1 recipe lowering', 'independent_wire_v1.py'),
             EvidenceClaim('synthetic', 'Physical and virtual v2 legacy lowering', 'tests/test_independent_item_v2.py')))
    if name == 'item.fields' and type(version) is int and version == 1:
        return CapabilityResult(name, version, True,
            ('Exact source table and row hashes; source-based expectations only.',
             'Existing max_stack_count u32 and existing stat values i32 in explicitly selected 0x11 or 0x12 layouts.',
             'Whole-record requirements of legacy packages remain protected.',
             'Game and save behavior require separate evidence.'),
            (EvidenceClaim('adapter', 'Typed existing ItemInfo fields', 'iteminfo_operations.py'),
             EvidenceClaim('synthetic', 'Field composition and both deployment routes', 'tests/test_independent_item_fields.py')))
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
        """Explicit bridge to the single legacy recipe within a mod envelope."""
        modules = [module for module in self.manifest['modules'] if module['type'] == 'item.legacy']
        if len(modules) != 1:
            raise IndependentItemError('This mod has no single legacy item recipe.')
        return modules[0]['data']
