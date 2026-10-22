"""Pure procedural morph and garment-refit contracts and rules."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import operator
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

from cdmw.core.streaming_json import JsonArray, json_sha256

if TYPE_CHECKING:
    from .morph_layers import MeshMorphMacroDefinition, MeshMorphSidePair


Vec3 = tuple[float, float, float]
MESH_MORPH_PROFILE_FORMAT = "cdmw.mesh_morph_profile.v2"
MESH_MORPH_AUTHORED_PROFILE_FORMAT = "cdmw.mesh_morph_profile.v3"
# Historical thresholds kept as compatibility exports, not enforced quotas.
MESH_MORPH_MAX_DEFINITIONS = 512
MESH_MORPH_MAX_SPARSE_VERTICES = 1_000_000
MESH_MORPH_MAX_DELTA_COMPONENT = 1_000_000.0
MESH_MORPH_PRESET_FORMAT = "cdmw.mesh_morph_value_preset.v2"
MESH_MORPH_LAYERED_PRESET_FORMAT = "cdmw.mesh_morph_value_preset.v3"
MESH_MORPH_RULES = ("volume", "scale", "move", "flatten", "taper", "twist", "radius")
MESH_MORPH_AXES = ("x", "y", "z")
MESH_MORPH_MIRROR_MODES = ("off", "x", "y", "z")
MESH_MORPH_FALLOFFS = ("constant", "linear", "smooth")


@dataclass(frozen=True, slots=True)
class MeshMorphVertexWeight:
    submesh_index: int
    vertex_index: int
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class MeshMorphRule:
    kind: str
    axis: str = "y"
    amount: float = 0.1
    falloff: str = "smooth"
    feather: int = 2
    parameters: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip().lower()
        axis = str(self.axis or "").strip().lower()
        falloff = str(self.falloff or "").strip().lower()
        if kind not in MESH_MORPH_RULES:
            raise ValueError(f"Unsupported procedural morph rule: {self.kind!r}")
        if axis not in MESH_MORPH_AXES:
            raise ValueError(f"Unsupported procedural morph axis: {self.axis!r}")
        if falloff not in MESH_MORPH_FALLOFFS:
            raise ValueError(f"Unsupported procedural morph falloff: {self.falloff!r}")
        if not math.isfinite(float(self.amount)):
            raise ValueError("Procedural morph amount must be finite.")
        if int(self.feather) < 0:
            raise ValueError("Procedural morph feather must be nonnegative.")
        parameters: list[tuple[str, float]] = []
        for raw_name, raw_value in self.parameters:
            name = str(raw_name or "").strip().lower()
            value = float(raw_value)
            if not name or not math.isfinite(value):
                raise ValueError("Procedural morph parameters require finite named values.")
            parameters.append((name, value))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "axis", axis)
        object.__setattr__(self, "falloff", falloff)
        object.__setattr__(self, "amount", float(self.amount))
        object.__setattr__(self, "feather", int(self.feather))
        object.__setattr__(self, "parameters", tuple(sorted(parameters)))


@dataclass(frozen=True, slots=True)
class MeshMorphDefinition:
    definition_id: str
    label: str
    category: str
    vertices: tuple[MeshMorphVertexWeight, ...]
    pivot: Vec3
    local_basis: tuple[Vec3, Vec3, Vec3]
    rule: MeshMorphRule
    mirror_mode: str = "off"
    min_percent: float = -100.0
    max_percent: float = 100.0
    default_percent: float = 0.0
    source_kind: str = "procedural"
    authored_fields: tuple[MeshMorphSparseField, ...] = ()
    base_geometry_fingerprint: str = ""
    garment_corrections: tuple[MeshMorphSparseField, ...] = ()
    correction_topology_fingerprint: str = ""
    correction_base_geometry_fingerprint: str = ""

    def __post_init__(self) -> None:
        definition_id = str(self.definition_id or "").strip()
        if not definition_id:
            raise ValueError("Morph definition_id is required.")
        if not self.vertices:
            raise ValueError("Morph definition requires at least one weighted vertex.")
        pivot = _point3(self.pivot)
        if len(self.local_basis) != 3:
            raise ValueError("Morph definition local_basis must contain three axes.")
        basis = tuple(_normalized(_point3(axis)) for axis in self.local_basis)
        if abs(_dot(basis[0], basis[1])) > 1e-5 or abs(_dot(basis[0], basis[2])) > 1e-5 or abs(_dot(basis[1], basis[2])) > 1e-5:
            raise ValueError("Morph definition local_basis axes must be orthogonal.")
        normalized_vertices: list[MeshMorphVertexWeight] = []
        seen: set[tuple[int, int]] = set()
        for vertex in self.vertices:
            key = (
                _strict_mesh_index(vertex.submesh_index, "Morph definition submesh"),
                _strict_mesh_index(vertex.vertex_index, "Morph definition vertex"),
            )
            weight = float(vertex.weight)
            if key[0] < 0 or key[1] < 0 or not math.isfinite(weight) or not 0.0 < weight <= 1.0:
                raise ValueError("Morph definition vertices require nonnegative indices and weights in (0, 1].")
            if key in seen:
                raise ValueError("Morph definition contains a duplicate weighted vertex.")
            seen.add(key)
            normalized_vertices.append(
                vertex if type(vertex.submesh_index) is int and type(vertex.vertex_index) is int
                and type(vertex.weight) is float else MeshMorphVertexWeight(key[0], key[1], weight)
            )
        mirror_mode = str(self.mirror_mode or "off").strip().lower()
        if mirror_mode not in MESH_MORPH_MIRROR_MODES:
            raise ValueError(f"Unsupported mirror mode: {self.mirror_mode!r}")
        minimum = float(self.min_percent)
        maximum = float(self.max_percent)
        default = float(self.default_percent)
        if not all(math.isfinite(value) for value in (minimum, maximum, default)) or minimum >= maximum:
            raise ValueError("Morph slider range must be finite and increasing.")
        if not minimum <= default <= maximum:
            raise ValueError("Morph slider default must be inside its range.")
        object.__setattr__(self, "definition_id", definition_id)
        object.__setattr__(self, "label", str(self.label or definition_id).strip() or definition_id)
        object.__setattr__(self, "category", str(self.category or "General").strip() or "General")
        object.__setattr__(self, "mirror_mode", mirror_mode)
        object.__setattr__(self, "min_percent", minimum)
        object.__setattr__(self, "max_percent", maximum)
        object.__setattr__(self, "default_percent", default)
        object.__setattr__(self, "vertices", tuple(sorted(normalized_vertices, key=lambda item: (item.submesh_index, item.vertex_index))))
        object.__setattr__(self, "pivot", pivot)
        object.__setattr__(self, "local_basis", basis)
        source_kind = str(self.source_kind or "procedural").strip().lower()
        if source_kind not in {"procedural", "authored"}:
            raise ValueError("Morph source_kind must be procedural or authored.")
        fields = _definition_sparse_fields(self.authored_fields, definition_id)
        corrections = _definition_sparse_fields(self.garment_corrections, definition_id)
        driver_indices = {vertex.submesh_index for vertex in normalized_vertices}
        if source_kind == "authored":
            if not fields:
                raise ValueError("An authored morph requires nonempty sparse target fields.")
            if {item.submesh_index for item in fields} != driver_indices:
                raise ValueError("Authored target fields must match the definition's driver parts.")
            selected_keys = {(vertex.submesh_index, vertex.vertex_index) for vertex in normalized_vertices}
            if any((item.submesh_index, index) not in selected_keys for item in fields for index in item.vertex_indices):
                raise ValueError("Authored target contains a vertex outside its definition selection.")
            object.__setattr__(self, "base_geometry_fingerprint", _sha256_digest(self.base_geometry_fingerprint, "Authored base geometry"))
        elif fields or self.base_geometry_fingerprint:
            raise ValueError("Procedural definitions cannot carry authored target data.")
        if corrections:
            if any(item.submesh_index in driver_indices for item in corrections):
                raise ValueError("Garment corrections cannot target a driver part.")
            object.__setattr__(self, "correction_topology_fingerprint", _sha256_digest(self.correction_topology_fingerprint, "Correction topology"))
            object.__setattr__(self, "correction_base_geometry_fingerprint", _sha256_digest(self.correction_base_geometry_fingerprint, "Correction base geometry"))
        elif self.correction_topology_fingerprint or self.correction_base_geometry_fingerprint:
            raise ValueError("Correction identity requires nonempty garment correction fields.")
        if (source_kind == "authored" or corrections) and max(abs(minimum), abs(maximum)) > 10_000.0:
            raise ValueError("Authored slider ranges must stay within +/-10000 percent.")
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "authored_fields", fields)
        object.__setattr__(self, "garment_corrections", corrections)


@dataclass(frozen=True, slots=True)
class MeshMorphSparseField:
    definition_id: str
    submesh_index: int
    vertex_indices: tuple[int, ...]
    deltas: tuple[Vec3, ...]

    def __post_init__(self) -> None:
        definition_id = str(self.definition_id or "").strip()
        if not definition_id:
            raise ValueError("Sparse morph field requires a definition id.")
        submesh_index = _strict_mesh_index(self.submesh_index, "Sparse field submesh")
        indices = tuple(_strict_mesh_index(item, "Sparse field vertex") for item in self.vertex_indices)
        deltas = tuple(_bounded_morph_delta(item) for item in self.deltas)
        if not indices or len(indices) != len(deltas):
            raise ValueError("Sparse morph fields require matching nonempty indices and deltas.")
        if len(set(indices)) != len(indices):
            raise ValueError("Sparse morph fields cannot repeat a vertex index.")
        pairs = sorted(zip(indices, deltas))
        object.__setattr__(self, "definition_id", definition_id)
        object.__setattr__(self, "submesh_index", submesh_index)
        object.__setattr__(self, "vertex_indices", tuple(item[0] for item in pairs))
        object.__setattr__(self, "deltas", tuple(item[1] for item in pairs))


@dataclass(frozen=True, slots=True)
class MeshMorphProfile:
    profile_id: str
    name: str
    topology_fingerprint: str
    definitions: tuple[MeshMorphDefinition, ...] = ()
    format: str = MESH_MORPH_PROFILE_FORMAT
    migrated_from_version: int = 0
    requires_v2_save: bool = False

    def __post_init__(self) -> None:
        profile_id = str(self.profile_id or "").strip()
        fingerprint = str(self.topology_fingerprint or "").strip().lower()
        if not profile_id:
            raise ValueError("Morph profile_id is required.")
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise ValueError("Morph profile topology_fingerprint must be an exact SHA-256 digest.")
        identifiers = [definition.definition_id for definition in self.definitions]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Morph profile definition ids must be unique.")
        driver_indices = {vertex.submesh_index for item in self.definitions for vertex in item.vertices}
        if any(field.submesh_index in driver_indices for item in self.definitions for field in item.garment_corrections):
            raise ValueError("Garment corrections cannot target any profile driver part.")
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "name", str(self.name or profile_id).strip() or profile_id)
        object.__setattr__(self, "topology_fingerprint", fingerprint)
        extended = any(item.source_kind == "authored" or item.garment_corrections for item in self.definitions)
        # Body sliders often use exactly the same immutable weighted selection.
        # Share it across controls and history without changing the saved schema.
        selections = {}
        for definition in self.definitions:
            shared = selections.setdefault(definition.vertices, definition.vertices)
            object.__setattr__(definition, "vertices", shared)
        object.__setattr__(self, "definitions", tuple(self.definitions))
        object.__setattr__(self, "format", MESH_MORPH_AUTHORED_PROFILE_FORMAT if extended else MESH_MORPH_PROFILE_FORMAT)


@dataclass(frozen=True, slots=True)
class MeshMorphValuePreset:
    preset_id: str
    name: str
    profile_id: str
    topology_fingerprint: str
    values: tuple[tuple[str, float], ...] = ()
    format: str = MESH_MORPH_PRESET_FORMAT
    manual_values: tuple[tuple[str, float], ...] | None = None
    macro_values: tuple[tuple[str, float], ...] = ()
    symmetry_enabled: bool = False
    profile_definition_fingerprint: str = ""

    def __post_init__(self) -> None:
        preset_id = str(self.preset_id or "").strip()
        profile_id = str(self.profile_id or "").strip()
        fingerprint = str(self.topology_fingerprint or "").strip().lower()
        if not preset_id or not profile_id:
            raise ValueError("Morph preset_id and profile_id are required.")
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise ValueError("Morph preset topology_fingerprint must be an exact SHA-256 digest.")
        normalized: list[tuple[str, float]] = []
        seen: set[str] = set()
        for raw_definition_id, raw_value in self.values:
            definition_id = str(raw_definition_id or "").strip()
            value = float(raw_value)
            if not definition_id or definition_id in seen or not math.isfinite(value):
                raise ValueError("Morph preset values require unique definition ids and finite values.")
            seen.add(definition_id)
            normalized.append((definition_id, value))
        object.__setattr__(self, "preset_id", preset_id)
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "name", str(self.name or preset_id).strip() or preset_id)
        object.__setattr__(self, "topology_fingerprint", fingerprint)
        object.__setattr__(self, "values", tuple(sorted(normalized)))
        if self.format not in {MESH_MORPH_PRESET_FORMAT, MESH_MORPH_LAYERED_PRESET_FORMAT}:
            raise ValueError("Unsupported morph value preset format.")
        if not isinstance(self.symmetry_enabled, bool):
            raise ValueError("Morph preset symmetry must be boolean.")
        if self.manual_values is None:
            if self.macro_values or self.symmetry_enabled or self.profile_definition_fingerprint or self.format == MESH_MORPH_LAYERED_PRESET_FORMAT:
                raise ValueError("Body control state requires retained manual values.")
            return
        for attribute in ("manual_values", "macro_values"):
            entries: list[tuple[str, float]] = []
            layer_ids: set[str] = set()
            for raw_key, raw_value in getattr(self, attribute):
                if not isinstance(raw_key, str) or not raw_key or raw_key != raw_key.strip() or raw_key in layer_ids or isinstance(raw_value, bool):
                    raise ValueError("Body control layers require unique exact ids and finite numeric values.")
                value = float(raw_value)
                if not math.isfinite(value):
                    raise ValueError("Body control layers require finite numeric values.")
                if attribute == "macro_values" and not -100.0 <= value <= 100.0:
                    raise ValueError("Body control macro values must stay between -100 and 100 percent.")
                layer_ids.add(raw_key)
                entries.append((raw_key, value))
            object.__setattr__(self, attribute, tuple(sorted(entries)))
        object.__setattr__(self, "profile_definition_fingerprint", _sha256_digest(self.profile_definition_fingerprint, "Body control profile definition"))
        object.__setattr__(self, "format", MESH_MORPH_LAYERED_PRESET_FORMAT)


@dataclass(frozen=True, slots=True)
class MeshRefitGarmentSettings:
    submesh_index: int
    enabled: bool = True
    intensity_percent: float = 100.0
    mode: str = "surface"
    clearance_percent: float = 0.0
    vertex_mask: tuple[tuple[int, float], ...] | None = None
    tightness_percent: float = 0.0
    island_settings: tuple[MeshRefitIslandSettings, ...] = ()

    def __post_init__(self) -> None:
        submesh_index = _strict_mesh_index(self.submesh_index, "Refit garment submesh")
        intensity = float(self.intensity_percent)
        mode = str(self.mode or "surface").strip().lower()
        clearance = float(self.clearance_percent)
        tightness = float(self.tightness_percent)
        if submesh_index < 0:
            raise ValueError("Refit garment submesh index must be non-negative.")
        if not math.isfinite(intensity) or not 0.0 <= intensity <= 200.0:
            raise ValueError("Refit intensity must be between 0 and 200 percent.")
        if mode not in {"surface", "rigid", "rigid_component"}:
            raise ValueError("Refit mode must be 'surface', 'rigid', or 'rigid_component'.")
        if not math.isfinite(clearance) or not 0.0 <= clearance <= 5.0:
            raise ValueError("Refit clearance must be between 0 and 5 percent of driver size.")
        if not math.isfinite(tightness) or not 0.0 <= tightness <= 100.0:
            raise ValueError("Refit tightness must be between 0 and 100 percent.")
        object.__setattr__(self, "submesh_index", submesh_index)
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "intensity_percent", intensity)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "clearance_percent", clearance)
        object.__setattr__(self, "tightness_percent", tightness)
        islands = tuple(self.island_settings)
        faces: set[int] = set()
        for island in islands:
            if not isinstance(island, MeshRefitIslandSettings) or faces.intersection(island.face_indices):
                raise ValueError("Refit island overrides must identify distinct whole mesh islands.")
            faces.update(island.face_indices)
        object.__setattr__(self, "island_settings", tuple(sorted(islands, key=lambda item: item.face_indices)))
        if self.vertex_mask is not None:
            normalized_mask: list[tuple[int, float]] = []
            seen: set[int] = set()
            for raw_index, raw_weight in self.vertex_mask:
                index = _strict_mesh_index(raw_index, "Refit mask vertex")
                weight = float(raw_weight)
                if index in seen or not math.isfinite(weight) or not 0.0 <= weight <= 1.0:
                    raise ValueError("Refit masks require unique indices and finite weights between 0 and 1.")
                seen.add(index)
                normalized_mask.append((index, weight))
            object.__setattr__(self, "vertex_mask", tuple(sorted(normalized_mask)))


@dataclass(frozen=True, slots=True)
class MeshRefitIslandSettings:
    face_indices: tuple[int, ...]
    enabled: bool = True
    intensity_percent: float = 100.0
    mode: str = "surface"
    clearance_percent: float = 0.0
    tightness_percent: float = 0.0

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or any(isinstance(getattr(self, name), bool) for name in
                ("intensity_percent", "clearance_percent", "tightness_percent")):
            raise ValueError("Island fitting requires a boolean enabled value and numeric settings.")
        indices = tuple(_strict_mesh_index(item, "Refit island face") for item in self.face_indices)
        if not indices or len(set(indices)) != len(indices):
            raise ValueError("Refit island overrides require nonempty unique face indices.")
        normalized = MeshRefitGarmentSettings(
            0, enabled=self.enabled, intensity_percent=self.intensity_percent, mode=self.mode,
            clearance_percent=self.clearance_percent, tightness_percent=self.tightness_percent,
        )
        object.__setattr__(self, "face_indices", tuple(sorted(indices)))
        for key in ("enabled", "intensity_percent", "mode", "clearance_percent", "tightness_percent"):
            object.__setattr__(self, key, getattr(normalized, key))


@dataclass(frozen=True, slots=True)
class MeshRefitDriverRegion:
    submesh_index: int
    vertex_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        submesh_index = _strict_mesh_index(self.submesh_index, "Driver region submesh")
        indices = tuple(_strict_mesh_index(item, "Driver region vertex") for item in self.vertex_indices)
        if not indices or len(set(indices)) != len(indices):
            raise ValueError("Driver regions require nonempty unique vertex indices.")
        object.__setattr__(self, "submesh_index", submesh_index)
        object.__setattr__(self, "vertex_indices", tuple(sorted(indices)))


@dataclass(frozen=True, slots=True)
class MeshRefitBindingSummary:
    driver_submesh_indices: tuple[int, ...] = ()
    garment_submesh_indices: tuple[int, ...] = ()
    bound_vertex_count: int = 0
    maximum_distance: float = 0.0
    p95_distance: float = 0.0
    warning_distance: float = 0.0
    distance_warning: bool = False
    driver_triangle_count: int = 0
    candidate_triangle_tests: int = 0
    garment_settings: tuple[MeshRefitGarmentSettings, ...] = ()
    garment_regions: tuple[tuple[int, tuple[MeshRefitDriverRegion, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class MeshMorphFittingRecipe:
    recipe_id: str
    name: str
    profile: MeshMorphProfile
    preset: MeshMorphValuePreset
    driver_submesh_indices: tuple[int, ...]
    garment_settings: tuple[MeshRefitGarmentSettings, ...]
    topology_fingerprint: str
    base_geometry_fingerprint: str
    garment_regions: tuple[tuple[int, tuple[MeshRefitDriverRegion, ...]], ...] = ()
    format: str = "cdmw.mesh_refit_recipe.v2"

    def __post_init__(self) -> None:
        recipe_id = str(self.recipe_id or "").strip()
        if not recipe_id:
            raise ValueError("Fitting recipe id is required.")
        drivers = tuple(_strict_mesh_index(item, "Recipe driver") for item in self.driver_submesh_indices)
        garments = tuple(self.garment_settings)
        garment_indices = tuple(item.submesh_index for item in garments)
        if not drivers or not garments or len(set(drivers)) != len(drivers) or len(set(garment_indices)) != len(garment_indices):
            raise ValueError("Fitting recipes require unique nonempty driver and garment roles.")
        if set(drivers).intersection(garment_indices):
            raise ValueError("Fitting recipe driver and garment roles cannot overlap.")
        if self.preset.profile_id != self.profile.profile_id or self.preset.topology_fingerprint != self.profile.topology_fingerprint:
            raise ValueError("Fitting recipe preset does not match its profile.")
        definitions = {item.definition_id: item for item in self.profile.definitions}
        if not definitions or set(dict(self.preset.values)) != set(definitions):
            raise ValueError("Fitting recipe preset must include every profile slider.")
        for key, value in self.preset.values:
            if not definitions[key].min_percent <= value <= definitions[key].max_percent:
                raise ValueError("Fitting recipe preset value is outside its slider range.")
        if self.preset.manual_values is not None:
            from .morph_layers import validate_mesh_morph_layers
            validate_mesh_morph_layers(self.profile, self.preset)
        for definition in self.profile.definitions:
            if any(item.submesh_index not in drivers for item in definition.vertices):
                raise ValueError("Fitting recipe profile references a part outside its driver roles.")
            if any(item.submesh_index not in garment_indices for item in definition.garment_corrections):
                raise ValueError("Fitting recipe correction references a part outside its garment roles.")
        regions = []
        seen_garments: set[int] = set()
        for raw_garment, raw_regions in self.garment_regions:
            garment = _strict_mesh_index(raw_garment, "Recipe region garment")
            entries = tuple(raw_regions)
            if garment not in garment_indices or garment in seen_garments:
                raise ValueError("Fitting recipe regions must identify unique configured garments.")
            if any(not isinstance(item, MeshRefitDriverRegion) or item.submesh_index not in drivers for item in entries):
                raise ValueError("Fitting recipe regions must belong to its driver parts.")
            if len({item.submesh_index for item in entries}) != len(entries):
                raise ValueError("Fitting recipe regions cannot repeat a driver part.")
            seen_garments.add(garment)
            regions.append((garment, tuple(sorted(entries, key=lambda item: item.submesh_index))))
        object.__setattr__(self, "recipe_id", recipe_id)
        object.__setattr__(self, "name", str(self.name or recipe_id).strip() or recipe_id)
        object.__setattr__(self, "driver_submesh_indices", tuple(sorted(drivers)))
        object.__setattr__(self, "garment_settings", tuple(sorted(garments, key=lambda item: item.submesh_index)))
        object.__setattr__(self, "format", "cdmw.mesh_refit_recipe.v3" if any(item.island_settings for item in garments)
                           else "cdmw.mesh_refit_recipe.v2")
        object.__setattr__(self, "garment_regions", tuple(sorted(regions)))
        object.__setattr__(self, "topology_fingerprint", _sha256_digest(self.topology_fingerprint, "Recipe topology"))
        object.__setattr__(self, "base_geometry_fingerprint", _sha256_digest(self.base_geometry_fingerprint, "Recipe base geometry"))


@dataclass(frozen=True, slots=True)
class MeshMorphState:
    session_id: str = ""
    profile_id: str = ""
    preset_id: str = ""
    topology_fingerprint: str = ""
    definitions: tuple[MeshMorphDefinition, ...] = ()
    values: tuple[tuple[str, float], ...] = ()
    available_profiles: tuple[tuple[str, str], ...] = ()
    available_presets: tuple[tuple[str, str], ...] = ()
    driver_submesh_indices: tuple[int, ...] = ()
    refit: MeshRefitBindingSummary = field(default_factory=MeshRefitBindingSummary)
    unbaked: bool = False
    topology_blocked: bool = False
    busy: bool = False
    failure: str = ""
    diagnostics: tuple[str, ...] = ()
    state_revision: int = 0
    edit_revision: int = 0
    change_id: str = ""
    authoring_baseline_ready: bool = False
    authoring_driver_submesh_indices: tuple[int, ...] = ()
    correction_definition_id: str = ""
    correction_garment_submesh_indices: tuple[int, ...] = ()
    manual_values: tuple[tuple[str, float], ...] = ()
    macro_values: tuple[tuple[str, float], ...] = ()
    macro_definitions: tuple[MeshMorphMacroDefinition, ...] = ()
    symmetry_enabled: bool = False
    side_pairs: tuple[MeshMorphSidePair, ...] = ()
    corrections_enabled: bool = True
    matching_recipes: tuple[tuple[str, str], ...] = ()
    body_controls_available: bool = False
    body_controls_reason: str = ""
    matching_recipe_garments: tuple[tuple[str, tuple[int, ...]], ...] = ()


def mesh_topology_fingerprint(mesh: object, submesh_indices: Iterable[int] | None = None) -> str:
    """Return an exact, position-independent fingerprint for selected topology."""

    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    indices = tuple(range(len(submeshes))) if submesh_indices is None else tuple(sorted({int(i) for i in submesh_indices}))
    payload: list[dict[str, object]] = []
    for submesh_index in indices:
        if not 0 <= submesh_index < len(submeshes):
            raise ValueError(f"Topology fingerprint submesh is out of range: {submesh_index}")
        submesh = submeshes[submesh_index]
        def face_rows(part=submesh):
            for face in getattr(part, "faces", ()) or ():
                values = tuple(int(index) for index in face[:3])
                if len(values) == 3:
                    yield values
        payload.append(
            {
                "index": submesh_index,
                "vertex_count": len(tuple(getattr(submesh, "vertices", ()) or ())),
                "faces": JsonArray(face_rows),
            }
        )
    return json_sha256(payload)


def mesh_morph_driver_topology_fingerprint(
    mesh: object,
    definitions: Iterable[MeshMorphDefinition],
) -> str:
    """Fingerprint only the body/driver submeshes referenced by definitions."""

    indices = tuple(
        sorted(
            {
                vertex.submesh_index
                for definition in definitions
                for vertex in definition.vertices
            }
        )
    )
    return mesh_topology_fingerprint(mesh, indices or None)


def build_weighted_morph_selection(
    mesh: object,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]],
    *,
    feather: int = 0,
    falloff: str = "smooth",
    mirror_mode: str = "off",
    mirror_tolerance: float | None = None,
) -> tuple[MeshMorphVertexWeight, ...]:
    """Expand a selection by face-adjacency rings and optionally mirror it strictly."""

    falloff = str(falloff or "smooth").strip().lower()
    mirror_mode = str(mirror_mode or "off").strip().lower()
    if falloff not in MESH_MORPH_FALLOFFS:
        raise ValueError(f"Unsupported procedural morph falloff: {falloff!r}")
    if mirror_mode not in MESH_MORPH_MIRROR_MODES:
        raise ValueError(f"Unsupported mirror mode: {mirror_mode!r}")
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    weighted: dict[tuple[int, int], float] = {}
    rings = max(0, int(feather))
    for raw_submesh, raw_vertices in selected_vertices_by_submesh.items():
        submesh_index = int(raw_submesh)
        if not 0 <= submesh_index < len(submeshes):
            continue
        vertex_count = len(tuple(getattr(submeshes[submesh_index], "vertices", ()) or ()))
        selected = {int(index) for index in raw_vertices if 0 <= int(index) < vertex_count}
        if not selected:
            continue
        adjacency = _vertex_adjacency(submeshes[submesh_index], vertex_count)
        frontier = set(selected)
        visited = set(selected)
        for index in selected:
            weighted[submesh_index, index] = 1.0
        for depth in range(1, rings + 1):
            next_frontier = {
                neighbor
                for index in frontier
                for neighbor in adjacency[index]
                if neighbor not in visited
            }
            if not next_frontier:
                break
            linear = max(0.0, 1.0 - depth / float(rings + 1))
            weight = linear * linear * (3.0 - 2.0 * linear) if falloff == "smooth" else (1.0 if falloff == "constant" else linear)
            for index in next_frontier:
                weighted[submesh_index, index] = max(weighted.get((submesh_index, index), 0.0), weight)
            visited.update(next_frontier)
            frontier = next_frontier
    if not weighted:
        raise ValueError("Cannot create a procedural morph without selected vertices.")
    if mirror_mode != "off":
        weighted = _strict_mirror_weights(mesh, weighted, mirror_mode, mirror_tolerance)
    return tuple(
        MeshMorphVertexWeight(submesh_index, vertex_index, weight)
        for (submesh_index, vertex_index), weight in sorted(weighted.items())
    )


def procedural_morph_pivot(mesh: object, vertices: Sequence[MeshMorphVertexWeight]) -> Vec3:
    return _weighted_pivot(mesh, {(item.submesh_index, item.vertex_index): item.weight for item in vertices})


def generate_procedural_morph_fields(
    mesh: object,
    definition: MeshMorphDefinition,
) -> tuple[MeshMorphSparseField, ...]:
    """Generate deterministic sparse 100-percent deltas for one definition."""

    if definition.source_kind == "authored":
        from .morph_targets import generate_morph_fields
        return generate_morph_fields(mesh, definition)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    axis = _normalized(definition.local_basis[MESH_MORPH_AXES.index(definition.rule.axis)])
    selected_positions: list[Vec3] = []
    valid: list[tuple[MeshMorphVertexWeight, Vec3]] = []
    for item in definition.vertices:
        if not 0 <= item.submesh_index < len(submeshes):
            raise ValueError(f"Morph definition submesh is out of range: {item.submesh_index}")
        positions = tuple(getattr(submeshes[item.submesh_index], "vertices", ()) or ())
        if not 0 <= item.vertex_index < len(positions):
            raise ValueError(f"Morph definition vertex is out of range: {item.vertex_index}")
        position = _point3(positions[item.vertex_index])
        selected_positions.append(position)
        valid.append((item, position))
    projections = [_dot(_sub(position, definition.pivot), axis) for position in selected_positions]
    axial_extent = max((abs(value) for value in projections), default=0.0)
    if axial_extent <= 1e-12:
        axial_extent = 1.0
    fields: dict[int, list[tuple[int, Vec3]]] = {}
    for item, position in valid:
        delta = _rule_delta(position, definition.pivot, axis, definition.rule, axial_extent)
        weighted_delta = _scale(delta, max(0.0, min(1.0, float(item.weight))))
        if _length_squared(weighted_delta) <= 1e-30:
            continue
        fields.setdefault(item.submesh_index, []).append((item.vertex_index, weighted_delta))
    return tuple(
        MeshMorphSparseField(
            definition.definition_id,
            submesh_index,
            tuple(index for index, _delta in sorted(items)),
            tuple(delta for _index, delta in sorted(items)),
        )
        for submesh_index, items in sorted(fields.items())
    )


def clamp_morph_value(definition: MeshMorphDefinition, value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = definition.default_percent
    if not math.isfinite(number):
        number = definition.default_percent
    return max(definition.min_percent, min(definition.max_percent, number))


def _rule_delta(position: Vec3, pivot: Vec3, axis: Vec3, rule: MeshMorphRule, axial_extent: float) -> Vec3:
    local = _sub(position, pivot)
    projection = _dot(local, axis)
    axial = _scale(axis, projection)
    radial = _sub(local, axial)
    amount = float(rule.amount)
    if rule.kind == "move":
        return _scale(axis, amount)
    if rule.kind == "scale":
        return _scale(axial, amount)
    if rule.kind == "flatten":
        return _scale(axial, -amount)
    if rule.kind == "radius":
        # Girth: displace proportionally to distance from the axis, so a limb
        # thickens by a percentage rather than by a fixed distance. "volume"
        # pushes every vertex the same absolute amount, which over-inflates
        # thin parts and under-inflates thick ones.
        return _scale(radial, amount)
    if rule.kind == "taper":
        return _scale(radial, amount * (projection / axial_extent))
    if rule.kind == "twist":
        angle = math.radians(amount) * (projection / axial_extent)
        rotated = _rodrigues(radial, axis, angle)
        return _sub(rotated, radial)
    radial_direction = _normalized(radial, fallback=axis)
    return _scale(radial_direction, amount)


def _vertex_adjacency(submesh: object, vertex_count: int) -> tuple[set[int], ...]:
    adjacency = [set() for _ in range(vertex_count)]
    for raw_face in tuple(getattr(submesh, "faces", ()) or ()):
        face = tuple(int(index) for index in raw_face[:3])
        if len(face) != 3 or any(index < 0 or index >= vertex_count for index in face):
            continue
        for left, right in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            adjacency[left].add(right)
            adjacency[right].add(left)
    return tuple(adjacency)


def _weighted_pivot(mesh: object, weighted: Mapping[tuple[int, int], float]) -> Vec3:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    total = 0.0
    accum = [0.0, 0.0, 0.0]
    for (submesh_index, vertex_index), raw_weight in weighted.items():
        weight = max(0.0, float(raw_weight))
        if weight <= 0.0 or not 0 <= submesh_index < len(submeshes):
            continue
        vertices = tuple(getattr(submeshes[submesh_index], "vertices", ()) or ())
        if not 0 <= vertex_index < len(vertices):
            continue
        point = _point3(vertices[vertex_index])
        for axis in range(3):
            accum[axis] += point[axis] * weight
        total += weight
    if total <= 0.0:
        raise ValueError("Cannot determine a procedural morph pivot from an empty selection.")
    return accum[0] / total, accum[1] / total, accum[2] / total


def _strict_mirror_weights(
    mesh: object,
    weighted: Mapping[tuple[int, int], float],
    axis_name: str,
    tolerance: float | None,
) -> dict[tuple[int, int], float]:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    points: list[tuple[int, int, Vec3]] = []
    point_by_key: dict[tuple[int, int], Vec3] = {}
    for submesh_index, submesh in enumerate(submeshes):
        for vertex_index, raw_point in enumerate(tuple(getattr(submesh, "vertices", ()) or ())):
            point = _point3(raw_point)
            points.append((submesh_index, vertex_index, point))
            point_by_key[submesh_index, vertex_index] = point
    if not points:
        raise ValueError("Cannot mirror an empty mesh.")
    minimum = tuple(min(point[2][axis] for point in points) for axis in range(3))
    maximum = tuple(max(point[2][axis] for point in points) for axis in range(3))
    diagonal = math.sqrt(sum((maximum[axis] - minimum[axis]) ** 2 for axis in range(3)))
    epsilon = max(1e-6, diagonal * 1e-7) if tolerance is None else max(1e-12, float(tolerance))
    buckets: dict[tuple[int, int, int], list[tuple[int, int, Vec3]]] = {}
    for item in points:
        buckets.setdefault(_cell(item[2], epsilon), []).append(item)
    result = dict(weighted)
    mirror_axis = MESH_MORPH_AXES.index(axis_name)
    mirror_center = (minimum[mirror_axis] + maximum[mirror_axis]) * 0.5
    missing: list[tuple[int, int]] = []
    for key, weight in weighted.items():
        point = point_by_key.get(key)
        if point is None:
            missing.append(key)
            continue
        reflected = list(point)
        reflected[mirror_axis] = (2.0 * mirror_center) - reflected[mirror_axis]
        reflected_point = tuple(reflected)  # type: ignore[assignment]
        cell = _cell(reflected_point, epsilon)
        candidates = (
            item
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for dz in (-1, 0, 1)
            for item in buckets.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ())
        )
        try:
            match = min(
                (item for item in candidates if _length_squared(_sub(item[2], reflected_point)) <= epsilon * epsilon),
                key=lambda item: (_length_squared(_sub(item[2], reflected_point)), item[0], item[1]),
            )
        except ValueError:
            missing.append(key)
            continue
        match_key = (match[0], match[1])
        result[match_key] = max(result.get(match_key, 0.0), float(weight))
    if missing:
        raise ValueError(f"Mirror creation failed: {len(missing)} selected vertices have no reflected match.")
    return result


def _cell(point: Vec3, epsilon: float) -> tuple[int, int, int]:
    return tuple(math.floor(component / epsilon) for component in point)  # type: ignore[return-value]


def _point3(value: object) -> Vec3:
    try:
        point = tuple(float(component) for component in value[:3])  # type: ignore[index]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Morph geometry contains an invalid vertex.") from exc
    if len(point) != 3 or not all(math.isfinite(component) for component in point):
        raise ValueError("Morph geometry contains a non-finite vertex.")
    return point  # type: ignore[return-value]


def _add(left: Vec3, right: Vec3) -> Vec3:
    return tuple(left[index] + right[index] for index in range(3))  # type: ignore[return-value]


def _sub(left: Vec3, right: Vec3) -> Vec3:
    return tuple(left[index] - right[index] for index in range(3))  # type: ignore[return-value]


def _scale(value: Vec3, factor: float) -> Vec3:
    return tuple(component * factor for component in value)  # type: ignore[return-value]


def _dot(left: Vec3, right: Vec3) -> float:
    return sum(left[index] * right[index] for index in range(3))


def _length_squared(value: Vec3) -> float:
    return _dot(value, value)


def _normalized(value: Vec3, fallback: Vec3 = (0.0, 1.0, 0.0)) -> Vec3:
    length = math.sqrt(_length_squared(value))
    return _scale(value, 1.0 / length) if length > 1e-12 else fallback


def _rodrigues(value: Vec3, axis: Vec3, angle: float) -> Vec3:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    cross = (
        axis[1] * value[2] - axis[2] * value[1],
        axis[2] * value[0] - axis[0] * value[2],
        axis[0] * value[1] - axis[1] * value[0],
    )
    return _add(_add(_scale(value, cosine), _scale(cross, sine)), _scale(axis, _dot(axis, value) * (1.0 - cosine)))


def _sha256_digest(value: object, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{label} must be an exact SHA-256 digest.")
    return digest


def _strict_mesh_index(value: object, label: str) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        index = operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{label} must be an integer index.") from exc
    if not 0 <= index <= 0x7FFFFFFF:
        raise ValueError(f"{label} must be a nonnegative bounded index.")
    return index


def _bounded_morph_delta(value: object) -> Vec3:
    if isinstance(value, (str, bytes)):
        raise ValueError("Sparse morph delta must have exactly three components.")
    try:
        raw = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("Sparse morph delta must have exactly three components.") from exc
    if len(raw) != 3:
        raise ValueError("Sparse morph delta must have exactly three components.")
    delta = _point3(raw)
    if any(abs(component) > MESH_MORPH_MAX_DELTA_COMPONENT for component in delta):
        raise ValueError("Sparse morph delta exceeds its component limit.")
    return delta


def _definition_sparse_fields(
    values: Sequence[MeshMorphSparseField],
    definition_id: str,
) -> tuple[MeshMorphSparseField, ...]:
    fields = tuple(values)
    seen: set[int] = set()
    for item in fields:
        if not isinstance(item, MeshMorphSparseField) or item.definition_id != definition_id:
            raise ValueError("Sparse fields must belong to their morph definition.")
        if item.submesh_index in seen:
            raise ValueError("A morph definition cannot repeat a sparse submesh field.")
        seen.add(item.submesh_index)
    return tuple(sorted(fields, key=lambda item: item.submesh_index))


__all__ = [
    "MESH_MORPH_AXES",
    "MESH_MORPH_AUTHORED_PROFILE_FORMAT",
    "MESH_MORPH_MAX_DEFINITIONS",
    "MESH_MORPH_MAX_SPARSE_VERTICES",
    "MESH_MORPH_FALLOFFS",
    "MESH_MORPH_MIRROR_MODES",
    "MESH_MORPH_PRESET_FORMAT",
    "MESH_MORPH_LAYERED_PRESET_FORMAT",
    "MESH_MORPH_PROFILE_FORMAT",
    "MESH_MORPH_RULES",
    "MeshMorphDefinition",
    "MeshMorphProfile",
    "MeshMorphRule",
    "MeshMorphSparseField",
    "MeshMorphState",
    "MeshMorphValuePreset",
    "MeshMorphVertexWeight",
    "MeshRefitBindingSummary",
    "MeshRefitGarmentSettings",
    "MeshRefitIslandSettings",
    "MeshRefitDriverRegion",
    "MeshMorphFittingRecipe",
    "build_weighted_morph_selection",
    "clamp_morph_value",
    "generate_procedural_morph_fields",
    "mesh_morph_driver_topology_fingerprint",
    "mesh_topology_fingerprint",
    "procedural_morph_pivot",
]
