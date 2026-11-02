"""Measured layout facts for Crimson Desert's Havok 2024.2 tagfiles.

The installed tagfiles carry type names (TST1/TNA1) but no type bodies, so the
size, alignment and internal reference fields of each class are not described by
the files themselves. The tables below were measured read-only over every
`.hkx` entry of game 2.04.03 (69,301 unique paths, 2026-11-02):

* ``ITEM_LAYOUTS`` maps (type name, ITEM kind flag) to (element stride, start
  alignment). The stride is the largest size every item of that type fits
  without overlapping its successor; the alignment is the largest one that
  reproduces every observed item offset from its predecessor's end. All padding
  bytes in the corpus are zero, and DATA always ends on a 16-byte boundary.
* ``RELATIVE_SLOTS`` lists the self-relative reference fields that `hknp`
  shapes, shape properties and constraint motors use instead of PTCH patches.
  A slot is listed only when, across the corpus, it is either zero or lands
  exactly on the start of another ITEM (zero misses); a ``count_offset`` names
  the u32 that holds the target ITEM's element count.

PTCH-listed pointers (hkArray, hkRefPtr, hkStringPtr, hkRefVariant) store ITEM
indices and are described by the file itself, so they need no table.
Unknown types and items no listed slot reaches are refused by the codec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

HKX_TAGFILE_SDK_VERSION = b"20240200"
HKX_ITEM_KIND_OBJECT = 0x10
HKX_ITEM_KIND_ARRAY = 0x20
HKX_DATA_END_ALIGNMENT = 16


@dataclass(frozen=True)
class HkxRelativeSlotSpec:
    offset: int
    width: int
    count_offset: Optional[int] = None


# (type name, ITEM kind) -> (stride, alignment); comments give corpus item counts.
ITEM_LAYOUTS: Mapping[Tuple[str, int], Tuple[int, int]] = {
    ('HavokShapeNameProperty', 0x10): (40, 8),  # 12,938 items
    ('char', 0x20): (1, 2),  # 24,713 items
    ('float', 0x20): (4, 16),  # 822 items
    ('hkArray<hkRefPtr<hknpShape>,hkBuiltinContainerAllocator<0,0>>', 0x10): (16, 16),  # 35,671 items
    ('hkBone', 0x20): (16, 16),  # 803 items
    ('hkBool', 0x20): (16, 16),  # 58 items
    ('hkFloat3', 0x20): (12, 16),  # 2,190,034 items
    ('hkFreeListArrayElement<hknpShapeInstance>', 0x20): (64, 16),  # 680,052 items
    ('hkInt16', 0x20): (2, 16),  # 1,088 items
    ('hkInt32', 0x20): (4, 16),  # 400 items
    ('hkMatrix4', 0x20): (64, 16),  # 46 items
    ('hkMemoryResourceContainer', 0x10): (72, 8),  # 5 items
    ('hkQsTransform', 0x20): (48, 16),  # 803 items
    ('hkRefPtr<hkSkeleton>', 0x20): (8, 16),  # 296 items
    ('hkRefPtr<hknpCompoundShape>', 0x10): (8, 16),  # 19,965 items
    ('hkRefPtr<hknpPhysicsSystemData>', 0x20): (8, 16),  # 359 items
    ('hkRefPtr<hknpShape>', 0x20): (8, 16),  # 35,671 items
    ('hkRefPtr<hkxIndexBuffer>', 0x20): (16, 16),  # 32 items
    ('hkRefPtr<hkxMaterial>', 0x20): (8, 16),  # 1 items
    ('hkRefPtr<hkxMesh::UserChannelInfo>', 0x20): (8, 16),  # 29 items
    ('hkRefPtr<hkxMesh>', 0x20): (8, 16),  # 1 items
    ('hkRefPtr<hkxMeshSection>', 0x20): (8, 16),  # 29 items
    ('hkRefPtr<hkxNode>', 0x20): (8, 16),  # 16 items
    ('hkRefPtr<hkxSkinBinding>', 0x20): (8, 16),  # 1 items
    ('hkRefPtr<hkxSpline>', 0x20): (8, 16),  # 1 items
    ('hkRefPtr<hkxTextureFile>', 0x20): (8, 16),  # 1 items
    ('hkRefVariant', 0x20): (8, 16),  # 32 items
    ('hkRelPtr<hknpShape>', 0x20): (8, 16),  # 18 items
    ('hkRootLevelContainer::NamedVariant', 0x20): (24, 16),  # 359 items
    ('hkRootLevelContainer', 0x10): (16, 16),  # 359 items
    ('hkSkeleton', 0x10): (144, 8),  # 803 items
    ('hkStringPtr', 0x20): (8, 16),  # 32 items
    ('hkUint16', 0x20): (2, 16),  # 33 items
    ('hkUint32', 0x20): (4, 16),  # 14 items
    ('hkUint8', 0x20): (1, 16),  # 2,311,720 items
    ('hkVector4', 0x20): (16, 16),  # 2,183,108 items
    ('hkaAnimationContainer', 0x10): (104, 8),  # 296 items
    ('hkaSkeletonMapper', 0x10): (208, 16),  # 592 items
    ('hkaSkeletonMapperData::ChainMapping', 0x20): (112, 16),  # 68 items
    ('hkaSkeletonMapperData::SimpleMapping', 0x20): (64, 16),  # 591 items
    ('hkcdCompressedAabbCodecs::Aabb4BytesCodec', 0x20): (4, 16),  # 1 items
    ('hkcdCompressedAabbCodecs::Aabb5BytesCodec', 0x20): (16, 16),  # 1 items
    ('hkcdDefaultStaticMeshTree::PrimitiveDataRun', 0x20): (16, 16),  # 1 items
    ('hkcdSimdTreeNamespace::Node', 0x20): (128, 16),  # 686,360 items
    ('hkcdStaticMeshTree::Primitive', 0x20): (5, 16),  # 1 items
    ('hkcdStaticMeshTree::Section', 0x20): (96, 16),  # 1 items
    ('hknpAabb8TreeNode', 0x20): (28, 16),  # 64,305 items
    ('hknpBallAndSocketConstraintData', 0x10): (128, 16),  # 26 items
    ('hknpBoxShape', 0x10): (192, 16),  # 30,506 items
    ('hknpBreakableConstraintData', 0x10): (56, 8),  # 195 items
    ('hknpCapsuleShape', 0x10): (120, 8),  # 3,903 items
    ('hknpCompoundShape', 0x10): (184, 8),  # 680,052 items
    ('hknpConstraintCinfo', 0x20): (48, 16),  # 285 items
    ('hknpConvexHull::Edge', 0x20): (4, 16),  # 4,364,770 items
    ('hknpConvexHull::Face', 0x20): (4, 16),  # 2,183,108 items
    ('hknpConvexShape', 0x10): (120, 8),  # 2,154,051 items
    ('hknpCylinderShape', 0x10): (160, 16),  # 862 items
    ('hknpFixedConstraintData', 0x10): (240, 16),  # 439 items
    ('hknpHingeConstraintData', 0x10): (240, 16),  # 5 items
    ('hknpLegacyCompressedMeshShape::MeshData', 0x10): (192, 16),  # 1 items
    ('hknpLegacyCompressedMeshShape', 0x10): (96, 16),  # 1 items
    ('hknpLimitedHingeConstraintData', 0x10): (336, 16),  # 945 items
    ('hknpLodShape', 0x10): (104, 8),  # 18 items
    ('hknpMaterial', 0x20): (80, 16),  # 359 items
    ('hknpMeshShape::GeometrySection::Primitive', 0x20): (4, 16),  # 64,305 items
    ('hknpMeshShape::GeometrySection', 0x20): (64, 16),  # 6,308 items
    ('hknpMeshShape::ShapeTagTableEntry', 0x20): (8, 16),  # 6,308 items
    ('hknpMeshShape', 0x10): (160, 16),  # 6,308 items
    ('hknpPhysicsSceneData', 0x10): (48, 8),  # 359 items
    ('hknpPhysicsSystemData::ExtendedBodyCinfo', 0x20): (208, 16),  # 359 items
    ('hknpPhysicsSystemData', 0x10): (136, 8),  # 147 items
    ('hknpPositionConstraintMotor', 0x10): (56, 8),  # 2,534 items
    ('hknpRagdollConstraintData', 0x10): (464, 16),  # 2,137 items
    ('hknpRagdollData', 0x10): (184, 8),  # 212 items
    ('hknpRefDragProperties', 0x10): (224, 16),  # 1,358 items
    ('hknpRefMassDistribution', 0x10): (80, 16),  # 152 items
    ('hknpShapeInstance', 0x20): (64, 16),  # 1 items
    ('hknpShapeMassProperties', 0x10): (64, 8),  # 2,167,650 items
    ('hknpShapeProperties::Entry', 0x20): (8, 16),  # 2,167,650 items
    ('hknpShapeSignals', 0x10): (16, 16),  # 1 items
    ('hknpSharedMotionProperties', 0x20): (80, 16),  # 262 items
    ('hknpSphereShape', 0x10): (120, 8),  # 58 items
    ('hknpTriangleShape', 0x10): (120, 8),  # 654 items
    ('hknpVelocityConstraintMotor', 0x10): (56, 16),  # 2 items
    ('hknpWheelConstraintData', 0x10): (432, 16),  # 544 items
    ('hkxAnimatedFloat', 0x10): (48, 8),  # 148 items
    ('hkxAnimatedQuaternion', 0x10): (48, 16),  # 14 items
    ('hkxAnimatedVector', 0x10): (48, 8),  # 230 items
    ('hkxAttribute', 0x20): (16, 16),  # 163 items
    ('hkxAttributeGroup', 0x20): (24, 16),  # 30 items
    ('hkxEdgeSelectionChannel', 0x10): (40, 8),  # 25 items
    ('hkxEnvironment::Variable', 0x20): (16, 16),  # 5 items
    ('hkxEnvironment', 0x10): (40, 8),  # 5 items
    ('hkxIndexBuffer', 0x10): (72, 8),  # 32 items
    ('hkxMaterial::TextureStage', 0x20): (16, 16),  # 12 items
    ('hkxMaterial', 0x10): (224, 16),  # 21 items
    ('hkxMesh::UserChannelInfo', 0x10): (56, 8),  # 80 items
    ('hkxMesh', 0x10): (64, 8),  # 29 items
    ('hkxMeshSection', 0x10): (176, 16),  # 32 items
    ('hkxNode', 0x10): (152, 8),  # 45 items
    ('hkxScene', 0x10): (272, 16),  # 2 items
    ('hkxSkinBinding', 0x10): (128, 16),  # 1 items
    ('hkxSparselyAnimatedBool', 0x10): (56, 8),  # 58 items
    ('hkxSparselyAnimatedInt', 0x10): (56, 8),  # 341 items
    ('hkxSparselyAnimatedString', 0x10): (56, 8),  # 31 items
    ('hkxSpline::ControlPoint', 0x20): (64, 16),  # 2 items
    ('hkxSpline', 0x10): (48, 8),  # 2 items
    ('hkxTextureFile', 0x10): (48, 8),  # 9 items
    ('hkxVertexBuffer', 0x10): (144, 8),  # 32 items
    ('hkxVertexDescription::ElementDecl', 0x20): (24, 16),  # 32 items
    ('hkxVertexIntDataChannel', 0x10): (40, 8),  # 32 items
    ('hkxVertexSelectionChannel', 0x10): (40, 8),  # 32 items
    ('int', 0x20): (4, 16),  # 212 items
    ('unsigned int', 0x20): (4, 16),  # 64 items
}

_POLYTOPE_SLOTS = (
    HkxRelativeSlotSpec(32, 8, 40),  # shape properties entries
    HkxRelativeSlotSpec(56, 4, 60),  # vertices (hkFloat3)
    HkxRelativeSlotSpec(64, 4, 68),  # face planes (hkVector4)
    HkxRelativeSlotSpec(72, 4, 76),  # faces
    HkxRelativeSlotSpec(80, 4, 84),  # face vertex indices (hkUint8)
    HkxRelativeSlotSpec(88, 4, 92),  # twin edge per face corner
    HkxRelativeSlotSpec(96, 4, 100),  # one outgoing edge per vertex
)

# Self-relative references by owner type (applied to every element of an array item).
RELATIVE_SLOTS: Mapping[str, Tuple[HkxRelativeSlotSpec, ...]] = {
    "hknpConvexShape": _POLYTOPE_SLOTS,
    "hknpBoxShape": _POLYTOPE_SLOTS,
    "hknpCylinderShape": _POLYTOPE_SLOTS,
    "hknpTriangleShape": _POLYTOPE_SLOTS,
    "hknpCapsuleShape": _POLYTOPE_SLOTS,
    "hknpSphereShape": _POLYTOPE_SLOTS,
    "hknpCompoundShape": (
        HkxRelativeSlotSpec(32, 8, 40),  # shape properties entries
        HkxRelativeSlotSpec(56, 8, 64),  # instance free list
        HkxRelativeSlotSpec(80, 8, 88),  # SIMD tree nodes
    ),
    "hkFreeListArrayElement<hknpShapeInstance>": (HkxRelativeSlotSpec(48, 8),),  # instance shape
    "hknpShapeProperties::Entry": (HkxRelativeSlotSpec(0, 8),),  # property object
    "hknpMeshShape": (
        HkxRelativeSlotSpec(96, 4, 100),  # shape tag table
        HkxRelativeSlotSpec(104, 8),  # SIMD tree nodes
        HkxRelativeSlotSpec(136, 4, 140),  # geometry sections
    ),
    "hknpMeshShape::GeometrySection": (
        HkxRelativeSlotSpec(0, 4, 4),
        HkxRelativeSlotSpec(8, 4, 12),
        HkxRelativeSlotSpec(16, 4, 20),
        HkxRelativeSlotSpec(24, 4, 28),
    ),
    "hknpLodShape": (HkxRelativeSlotSpec(56, 4, 60),),  # level shapes (hkRelPtr<hknpShape>)
    "hkRelPtr<hknpShape>": (HkxRelativeSlotSpec(0, 8),),
    "hknpBreakableConstraintData": (HkxRelativeSlotSpec(40, 8),),  # wrapped constraint
    "hknpLimitedHingeConstraintData": (HkxRelativeSlotSpec(224, 8),),  # motor
    "hknpRagdollConstraintData": (
        HkxRelativeSlotSpec(272, 8),  # motors
        HkxRelativeSlotSpec(280, 8),
        HkxRelativeSlotSpec(288, 8),
    ),
}


def hkx_item_layout(type_name: str, kind: int) -> Optional[Tuple[int, int]]:
    return ITEM_LAYOUTS.get((type_name, kind))


def hkx_relative_slots(type_name: str) -> Tuple[HkxRelativeSlotSpec, ...]:
    return RELATIVE_SLOTS.get(type_name, ())


def hkx_layout_table_summary() -> Dict[str, int]:
    return {"item_layouts": len(ITEM_LAYOUTS), "relative_slot_owners": len(RELATIVE_SLOTS)}
