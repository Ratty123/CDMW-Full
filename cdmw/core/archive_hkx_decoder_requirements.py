from __future__ import annotations

from typing import List, Tuple


_Requirement = Tuple[str, str, Tuple[str, ...]]

_MESH_SHAPE_TYPES = {
    "hknpMeshShape",
    "hknpMeshShape::GeometrySection",
    "hknpMeshShape::GeometrySection::Primitive",
    "hknpMeshShape::ShapeTagTableEntry",
    "hknpAabb8TreeNode",
    "hkcdStaticMeshTree::Section",
    "hknpLegacyCompressedMeshShape",
    "hknpLegacyCompressedMeshShape::MeshData",
}
_PHYSICS_CLASS_TYPES = {
    "hknpPhysicsSystemData",
    "hknpPhysicsSystemData::ExtendedBodyCinfo",
    "hknpConstraintCinfo",
    "hknpConstraintData",
    "hknpBallAndSocketConstraintData",
    "hknpHingeConstraintData",
    "hknpRagdollConstraintData",
    "hknpLimitedHingeConstraintData",
    "hknpWheelConstraintData",
    "hknpFixedConstraintData",
    "hknpBreakableConstraintData",
    "hknpSharedMotionProperties",
    "hknpPositionConstraintMotor",
    "hknpVelocityConstraintMotor",
}

_REQUIREMENTS: dict[str, _Requirement] = {
    "array_owner_context": (
        "Array header is readable, but the owning Havok member still decides the real element type.",
        (
            "owner-field array mapping",
            "element template/class metadata",
            "fixup-backed data pointer semantics",
            "rebuild-safe count/capacity rules",
        ),
    ),
    "reference_pointer_context": (
        "Reference storage is readable, but exact Havok reference semantics still need fixup-backed class context.",
        (
            "PTCH/fixup-backed target classification",
            "null/data/string/type reference distinction",
            "target class member metadata",
        ),
    ),
    "free_list_entry_context": (
        "Free-list entry storage is isolated, but owner semantics and mutation rules are not recovered.",
        ("owning array/member metadata", "entry lifetime/free-list flags", "safe fixed-size write rules"),
    ),
    "shape_internals": (
        "Shape payload is identified, but exact child/triangle/LOD member layout is not fully decoded.",
        (
            "shape-specific hkClass member metadata",
            "child shape/material/tag references",
            "triangle or LOD payload field mapping",
            "safe fixed-size write rules",
        ),
    ),
    "mesh_shape_internals": (
        "Mesh-shape rows are separated for browsing, but the topology/tree payload is not fully decoded.",
        (
            "mesh primitive bit layout",
            "AABB tree node encoding",
            "shape tag range/table semantics",
            "mesh byte-buffer ownership",
        ),
    ),
    "compressed_mass_properties": (
        "Mass/inertia values are preserved and sampled, but packed Havok mass-property semantics are incomplete.",
        ("compressed mass scale/basis decoding", "inertia tensor field mapping", "owner shape/body semantics"),
    ),
    "material_property_entries": (
        "Material/property payloads are browsable, but flags and property table ownership are still inferred.",
        ("material member metadata", "property key/value semantics", "free-list/property entry ownership"),
    ),
    "physics_class_members": (
        "Physics class payload has useful recovered values, but real hkClass member metadata is still synthetic.",
        (
            "real member type codes/flags/offsets",
            "base class and enum references",
            "owner-array type mapping",
            "template/default/version/signature metadata",
        ),
    ),
    "root_container_semantics": (
        "Root/container records are recognized, but full NamedVariant semantics are still being recovered.",
        (
            "name string reference",
            "class string/type reference",
            "variant object reference",
            "nested scene/system/ragdoll/animation root ordering",
        ),
    ),
    "skeleton_animation_containers": (
        "Animation/skeleton metadata is browsable, but container tables are not fully mapped.",
        (
            "skeleton/animation owner arrays",
            "clip/track table semantics",
            "string/path reference ownership",
            "safe no-edit rebuild proof",
        ),
    ),
    "havok_physics_member_layout": (
        "Modern Havok Physics object payload is partially recovered but not fully mapped to hkClass members.",
        ("real hkClass member metadata", "field names/types/offsets", "reference and array owner context"),
    ),
    "unknown_havok_member_layout": (
        "Payload bytes are preserved, but the class/member layout is not recovered enough for named Havok XML.",
        ("real hkClass metadata", "field names/types/offsets", "reference/array semantics"),
    ),
}


def _requirement(key: str) -> Tuple[str, str, List[str]]:
    description, requirements = _REQUIREMENTS[key]
    return key, description, list(requirements)


def _hkx_missing_decoder_requirements_for_type(type_name: str) -> Tuple[str, str, List[str]]:
    normalized = str(type_name or "")
    if normalized.startswith("hkArray"):
        return _requirement("array_owner_context")
    if normalized.startswith(("hkRefPtr", "hkRelPtr")):
        return _requirement("reference_pointer_context")
    if normalized.startswith("hkFreeListArrayElement"):
        return _requirement("free_list_entry_context")
    if normalized in {"hknpTriangleShape", "hknpLodShape"}:
        return _requirement("shape_internals")
    if normalized in _MESH_SHAPE_TYPES:
        return _requirement("mesh_shape_internals")
    if normalized in {"hknpShapeMassProperties", "hkCompressedMassProperties"}:
        return _requirement("compressed_mass_properties")
    if normalized in {"hknpMaterial", "hknpShapeProperties::Entry"}:
        return _requirement("material_property_entries")
    if normalized in _PHYSICS_CLASS_TYPES:
        return _requirement("physics_class_members")
    if normalized in {"hkRootLevelContainer", "hkRootLevelContainer::NamedVariant", "hkRefVariant"}:
        return _requirement("root_container_semantics")
    if normalized.startswith(("hka", "hkx")) or "Animation" in normalized or "Skeleton" in normalized:
        return _requirement("skeleton_animation_containers")
    if normalized.startswith("hknp"):
        return _requirement("havok_physics_member_layout")
    return _requirement("unknown_havok_member_layout")
