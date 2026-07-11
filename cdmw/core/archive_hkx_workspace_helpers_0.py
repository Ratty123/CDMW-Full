from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals()
def _hkx_reimport_policy_document() -> Dict[str, object]:
    return {
        "status": "strict_fixed_size_patch_only",
        "write_target": "mod_ready_loose_hkx_only",
        "mod_creation": {
            "output_mode": "loose replacement package",
            "archive_policy": "never overwrite installed game archives",
            "expected_flow": "edit JSON/XML or Structured Editor values, import the patch, then write the changed HKX into a mod-ready loose folder",
            "native_rust_support": "fixed-float physics tuning edits use the Rust patcher when available and fall back to the Python patcher otherwise",
        },
        "ignored_metadata": [
            "description",
            "descriptions",
            "labels",
            "comments",
            "confidence",
            "layout descriptions",
            "converter display/status notes",
            "havok_xml_view / havokXmlView browser metadata",
            "hkx_xml_parity_report / hkxXmlParityReport browser metadata",
            "tagfile_reference_fixups / tagfileReferenceFixups browser metadata",
        ],
        "rejected_changes": [
            "SDK/version mismatch",
            "payload size mismatch",
            "ITEM record count changes",
            "object count changes",
            "type identity changes",
            "record count or byte-length changes",
            "shape count changes",
            "array length changes unless represented by a supported fixed-size value patch",
            "raw payload byte-length changes",
            "non-finite numeric values",
            "unsupported reference edits",
            "topology edits that change row/value counts",
        ],
        "allowed_edits": [
            "same-count hkFloat3 vertex rows",
            "same-count hkVector4 plane rows",
            "same-count convex face records",
            "same-count face index byte buffers",
            "same-count convex edge/support uint16 pairs",
            "same-size hknpShapeMassProperties float rows",
            "same-offset hknpCapsuleShape radius",
            "same-count hknpCapsuleShape endpoint hkFloat3 rows",
            "same-offset hknp shape float slots",
            "same-offset physics tuning float slots",
            "same-count hknpMeshShape primitive tuple winding/order edits that keep each tuple's original byte set",
            "same-length advanced payload hex edits for research workflows",
        ],
        "description": (
            "Importer policy for this CDMW Crimson Desert HKX converter format. The importer patches only fixed-size "
            "values into the original HKX byte layout and writes the result through the loose-mod export path."
        ),
    }


@bind_archive_hkx_globals()
def _hkx_user_editing_guide_document(cdmw_compatibility: Mapping[str, object]) -> Dict[str, object]:
    status = str(cdmw_compatibility.get("status") or "unsupported")
    return {
        "status": status,
        "summary": (
            "Start with blue patchable rows in Structured Editor or Collision Editor. Treat grey/context rows as labels "
            "and clues. Export/import ignores descriptions, guidance, and relationship metadata."
        ),
        "confidence_legend": [
            {
                "label": "confirmed",
                "meaning": "Field is decoded or strongly validated by the converter. Still keep edits small.",
                "suggested_action": "Good first target for controlled value-only edits.",
            },
            {
                "label": "strong inference",
                "meaning": "Field behavior is inferred from repeated Crimson Desert HKX patterns and descriptor context.",
                "suggested_action": "Try small changes and compare in-game or in preview.",
            },
            {
                "label": "experimental",
                "meaning": "Field is readable, but the exact Havok meaning is still being recovered.",
                "suggested_action": "Use only on copies/mod output and change one value at a time.",
            },
            {
                "label": "raw preserved",
                "meaning": "Bytes are preserved for round-trip safety but not decoded enough for guided edits.",
                "suggested_action": "Do not edit unless you are intentionally reverse-engineering.",
            },
        ],
        "safe_first_edits": [
            "motor/constraint force or damping-like fixed float slots with low/medium edit risk",
            "sphere or capsule radius values that stay positive",
            "convex vertices/planes when preserving counts and topology",
            "mesh primitive tuple winding/order only, keeping the same four byte values per primitive",
        ],
        "avoid_until_decoded": [
            "adding/removing records, objects, shapes, vertices, faces, primitives, or arrays",
            "changing mesh primitive vertex sets, shape-tag ranges, byte-buffer lengths, or AABB tree nodes",
            "editing references, hkArray sizes/capacity, hkRefPtr targets, strings, or raw structural payloads",
            "large tuning jumps without testing one value at a time",
        ],
        "workflow": [
            "Use HKX Browser to identify bodies, shapes, constraints, motors, and related descriptor hints.",
            "Use Show in 3D Preview for mapped shapes/constraints before editing.",
            "Use Structured Editor for body/constraint/motor values and Collision Editor for shape values.",
            "Change one row, write a loose mod, test, then come back for the next row.",
        ],
    }


@bind_archive_hkx_globals()
def _hkx_semantic_record_relation(source_type: str, target_type: str, raw_relation: str) -> Optional[Tuple[str, str]]:
    source = str(source_type or "")
    target = str(target_type or "")
    if source == "hknpPhysicsSystemData::ExtendedBodyCinfo" and (
        target.endswith("Shape") or target in {"hknpConvexShape", "hknpBoxShape", "hknpCapsuleShape", "hknpSphereShape", "hknpMeshShape"}
    ):
        return (
            "possible_body_shape",
            "A body construction record contains a word matching a shape ITEM offset. This likely links a body to its collision shape.",
        )
    if source in {"hknpRagdollConstraintData", "hknpLimitedHingeConstraintData", "hknpConstraintCinfo"} and target == "hknpPositionConstraintMotor":
        return (
            "possible_constraint_motor",
            "A constraint record contains a word matching a motor ITEM offset. This may link the joint/constraint to its motor tuning.",
        )
    if source == "hknpConstraintCinfo" and target == "hknpPhysicsSystemData::ExtendedBodyCinfo":
        return (
            "possible_constraint_body",
            "A constraint-info record contains a word matching a body-info ITEM offset. This may identify one constrained body.",
        )
    if source in {"hknpPhysicsSceneData", "hknpRagdollData"} and target == "hknpPhysicsSystemData::ExtendedBodyCinfo":
        return (
            "possible_system_body_array",
            "A scene/ragdoll container contains a word matching a body-info ITEM offset.",
        )
    if source in {"hknpPhysicsSceneData", "hknpRagdollData"} and target in {"hknpRagdollConstraintData", "hknpLimitedHingeConstraintData", "hknpConstraintCinfo"}:
        return (
            "possible_system_constraint_array",
            "A scene/ragdoll container contains a word matching a constraint ITEM offset.",
        )
    if source == "hknpCompoundShape" and target == "hknpShapeInstance":
        return (
            "possible_compound_shape_instances",
            "A compound shape contains a word matching shape-instance storage.",
        )
    if source == "hknpShapeInstance" and target.startswith("hknp") and "Shape" in target:
        return (
            "possible_child_shape",
            "A shape-instance row contains a word matching a child shape record.",
        )
    return None
