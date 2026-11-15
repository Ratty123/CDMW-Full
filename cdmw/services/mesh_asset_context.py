"""Immutable source ownership shared by archive Refit and item-set editing."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from uuid import uuid4

from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.services.mesh_service_state import MeshExportSnapshot

ASSET_ATTRIBUTE = "_cdmw_mesh_asset_id"
PART_ATTRIBUTE = "_cdmw_mesh_asset_part_id"
ORIGIN_ATTRIBUTE = "_cdmw_mesh_asset_origin_id"


@dataclass(frozen=True, slots=True)
class MeshAsset:
    entry: object
    source: MeshExportSnapshot
    part_indices: tuple[int, ...]
    role: str
    preview_lease: object | None = None
    neutral_appearance: NeutralMeshAppearance | None = None
    dependency_context: object | None = None
    _asset_id: str = field(init=False, repr=False)

    def __post_init__(self):
        path = str(getattr(self.entry, "path", "")).replace("\\", "/").casefold()
        digest = hashlib.sha256(getattr(self.source, "original_data", b"")).hexdigest()
        object.__setattr__(self, "_asset_id", hashlib.sha256((path + "\n" + digest).encode()).hexdigest())

    @property
    def asset_id(self) -> str:
        return self._asset_id

    def source_part_id(self, index: int) -> str:
        return f"{self.asset_id}:{index}"


@dataclass(frozen=True, slots=True)
class MeshAssetContext:
    assets: tuple[MeshAsset, ...]
    context_id: str = field(default_factory=lambda: uuid4().hex)
    neutral_coordinates: bool = False
    workflow: str = "refit"
    excluded_part_ids: frozenset[str] = frozenset()

    @property
    def draft_identity(self) -> str:
        hashes = sorted(hashlib.sha256(asset.source.original_data).hexdigest() for asset in self.assets)
        return hashlib.sha256("\n".join(hashes).encode("ascii")).hexdigest()


def is_item_set(context) -> bool:
    return isinstance(context, MeshAssetContext) and context.workflow == "item_set"


def item_set_bindings(mesh, context):
    """Validate live identities and derive indices; indices never establish ownership."""
    assets = {asset.asset_id: asset for asset in context.assets}
    if not assets or len(assets) != len(context.assets):
        raise ValueError("Item set contains duplicate source files")
    bindings = {key: [] for key in assets}
    seen = set()
    for index, part in enumerate(mesh.submeshes):
        owner = str(getattr(part, ASSET_ATTRIBUTE, ""))
        identity = str(getattr(part, PART_ATTRIBUTE, ""))
        origin = str(getattr(part, ORIGIN_ATTRIBUTE, ""))
        asset = assets.get(owner)
        if asset is None or not identity.startswith(owner + ":") or identity in seen:
            raise ValueError("Item set lost a part's unique source identity")
        origins = {asset.source_part_id(i) for i in range(len(asset.source.mesh.submeshes))}
        if origin not in origins:
            raise ValueError(f"Part does not belong to its source file: {asset.entry.basename}")
        seen.add(identity)
        bindings[owner].append(index)
    for asset in context.assets:
        if not bindings[asset.asset_id] or not any(
                mesh.submeshes[index].vertices and mesh.submeshes[index].faces
                for index in bindings[asset.asset_id]):
            raise ValueError(f"Cannot delete every part of a source file: {asset.entry.basename}")
    return {key: tuple(value) for key, value in bindings.items()}
