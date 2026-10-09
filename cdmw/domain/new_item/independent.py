"""Portable item identities. Game integers are bindings, never package identities."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from uuid import UUID

from cdmw.domain.new_item.allocation import DEFAULT_ITEM_KEY_RANGE, allocate_item_key


class IndependentItemError(ValueError):
    pass


def package_id(value: str) -> str:
    try:
        identity = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise IndependentItemError("Invalid independent item identity.") from exc
    if identity.hex != value or identity.int == 0:
        raise IndependentItemError("Invalid independent item identity.")
    return value


@dataclass(frozen=True)
class IndependentItemPackage:
    identity: str
    title: str
    recipe: Mapping
    dependencies: Mapping[str, str]
    blobs: Mapping[str, bytes]
    digest: str
    # Exact ZIP identity is separate from canonical content and logical UUID.
    artifact_digest: str = field(default="", compare=False)


@dataclass
class IdentityBindings:
    """An install-local reservation set, including retired symbols and items."""
    identity: str
    values: dict[str, dict[str, int]] = field(default_factory=dict)
    reserved: Mapping[str, set[int]] = field(default_factory=dict)
    stem: str = ""
    paths: tuple[str, ...] = ()

    def allocate(self, namespace, symbol, used):
        held = self.values.setdefault(namespace, {})
        taken = set(used) | set(self.reserved.get(namespace, ()))
        if symbol in held:
            value = held[symbol]
            if value in taken or value not in DEFAULT_ITEM_KEY_RANGE:
                raise IndependentItemError(f"Reserved {namespace} identity {value} is now occupied. Restore the matching profile; existing items cannot be renumbered.")
            return value
        taken.update(held.values())
        value = allocate_item_key(taken)
        held[symbol] = value
        return value


@dataclass(frozen=True)
class IndependentItemExport:
    path: Path
    identity: str
    digest: str


@dataclass(frozen=True)
class IndependentItemInstallPlan:
    preparation: object | None
    items: tuple[tuple[str, str, int, str], ...]
    # Exact package bytes are captured before review; apply never rereads inputs.
    summary: tuple[str, ...]
