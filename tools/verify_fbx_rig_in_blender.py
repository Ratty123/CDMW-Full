"""Assert an exported FBX carries a working rig, from headless Blender.

Nothing here prints and passes: every check raises. A rig that imports without
an armature, binds no skin, or deforms the wrong vertices must fail the run.

Usage:
    blender --background --python tools/verify_fbx_rig_in_blender.py -- BODY.fbx [--bones N]

Options:
    --bones N        expected armature bone count
    --pose NAME      bone to rotate for the deformation check (repeatable)
    --min-vertices N smallest vertex count the bound mesh may have
"""

import argparse
import math
import sys

import bpy
from mathutils import Matrix

# The exporter normalizes each row, so this is float noise and nothing else. It is
# deliberately far tighter than the 2/255 the file's u8 weights drift by.
WEIGHT_SUM_TOLERANCE = 1.0e-6
POSE_DEGREES = 45.0
MOVED_EPSILON = 1.0e-5


def _fail(message):
    raise AssertionError(message)


def _parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("fbx")
    parser.add_argument("--bones", type=int, default=0)
    parser.add_argument("--pose", action="append", default=[])
    parser.add_argument("--min-vertices", type=int, default=1)
    return parser.parse_args(argv)


def _import(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.import_scene.fbx(filepath=path)
    except AttributeError:
        bpy.ops.preferences.addon_enable(module="io_scene_fbx")
        bpy.ops.import_scene.fbx(filepath=path)


def _armature():
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        _fail(f"expected exactly one armature, found {len(armatures)}")
    return armatures[0]


def _bound_meshes(armature):
    """Meshes selected by their armature modifier, never by import order.

    An import can bring in placeholder geometry, and taking the first MESH
    object silently tests the wrong one -- which is exactly what happened while
    this binding was being investigated.
    """

    bound = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        modifiers = [
            modifier
            for modifier in obj.modifiers
            if modifier.type == "ARMATURE" and modifier.object is armature
        ]
        if modifiers:
            bound.append(obj)
    if not bound:
        _fail("no mesh carries an armature modifier bound to the imported armature")
    return bound


def _check_groups_and_weights(mesh_object, armature):
    bone_names = {bone.name for bone in armature.data.bones}
    groups = mesh_object.vertex_groups

    unknown = [group.name for group in groups if group.name not in bone_names]
    if unknown:
        _fail(f"{mesh_object.name}: {len(unknown)} vertex group(s) name no bone, e.g. {unknown[:5]}")

    group_bone = {group.index: group.name for group in groups}
    unweighted = 0
    worst_sum = 0.0
    for vertex in mesh_object.data.vertices:
        live = [element for element in vertex.groups if element.weight > 0.0]
        if not live:
            unweighted += 1
            continue
        for element in live:
            if element.group not in group_bone:
                _fail(f"{mesh_object.name}: vertex {vertex.index} references a missing group")
        total = sum(element.weight for element in live)
        worst_sum = max(worst_sum, abs(total - 1.0))
    if unweighted:
        _fail(f"{mesh_object.name}: {unweighted} vertex/vertices belong to no vertex group")
    if worst_sum > WEIGHT_SUM_TOLERANCE:
        _fail(f"{mesh_object.name}: weights stray from 1.0 by {worst_sum:.6g}")
    return worst_sum


def _evaluated_coordinates(mesh_object):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_object.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    coordinates = [mesh_object.matrix_world @ vertex.co.copy() for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    return coordinates


def _check_rest_pose_is_the_bind_pose(mesh_object):
    """At rest the armature must not move the mesh at all.

    This is what proves the cluster's Transform/TransformLink pair agrees with
    the bone hierarchy. Get them inconsistent and the body arrives pre-deformed
    while every other check here still passes.
    """

    posed = _evaluated_coordinates(mesh_object)
    rest = [mesh_object.matrix_world @ vertex.co.copy() for vertex in mesh_object.data.vertices]
    if len(posed) != len(rest):
        _fail(f"{mesh_object.name}: evaluated vertex count {len(posed)} != {len(rest)}")
    worst = max(((a - b).length for a, b in zip(posed, rest)), default=0.0)
    if worst > 1.0e-3:
        _fail(f"{mesh_object.name}: rest pose deforms the mesh by up to {worst:.6g}; bind pose disagrees")
    return worst


def _check_deformation(mesh_object, armature, bone_name):
    if bone_name not in armature.pose.bones:
        _fail(f"armature has no bone named {bone_name!r}")

    before = _evaluated_coordinates(mesh_object)

    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")
    pose_bone = armature.pose.bones[bone_name]
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler = (math.radians(POSE_DEGREES), 0.0, 0.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()

    after = _evaluated_coordinates(mesh_object)
    bone_head = armature.matrix_world @ armature.data.bones[bone_name].head_local

    moved_distances = []
    still_distances = []
    for start, end, vertex in zip(before, after, mesh_object.data.vertices):
        rest_point = mesh_object.matrix_world @ vertex.co
        distance = (rest_point - bone_head).length
        if (end - start).length > MOVED_EPSILON:
            moved_distances.append(distance)
        else:
            still_distances.append(distance)

    # Put the rig back so a later check starts from rest.
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")
    pose_bone.rotation_euler = (0.0, 0.0, 0.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()

    if not moved_distances:
        _fail(f"rotating {bone_name} moved no vertices at all; the mesh is not bound to it")
    if not still_distances:
        # Not a bad rig: posing the root of a part rotates all of it, and then there
        # is no stationary group to compare against. Refused rather than waved
        # through, because a genuinely smeared binding looks identical from here.
        # Pass a bone that drives only some of the mesh.
        _fail(
            f"rotating {bone_name} moved every one of {len(moved_distances)} vertices, so "
            "localisation cannot be judged; choose a bone that is not the root of this part"
        )

    mean_moved = sum(moved_distances) / len(moved_distances)
    mean_still = sum(still_distances) / len(still_distances)
    if mean_moved >= mean_still:
        _fail(
            f"{bone_name}: vertices that moved sit a mean {mean_moved:.4f} from the bone against "
            f"{mean_still:.4f} for those that did not; the weights are not on the right bones"
        )
    return len(moved_distances), mean_moved, mean_still


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = _parse_args(argv)

    _import(args.fbx)
    armature = _armature()
    bone_count = len(armature.data.bones)
    print(f"armature {armature.name!r}: {bone_count} bones")
    if args.bones and bone_count != args.bones:
        _fail(f"expected {args.bones} bones, imported {bone_count}")

    meshes = _bound_meshes(armature)
    print(f"meshes bound by an armature modifier: {[obj.name for obj in meshes]}")

    # Blender reads a unitless FBX as centimetres and divides by 100 on import, so
    # every distance below is 100x smaller than the source. The deformation check
    # compares distances against each other and is unaffected; this is printed only
    # so the numbers can be read against source-unit references.
    import_scale = armature.matrix_world.to_scale()[0]
    print(f"import scale: {import_scale:g} (source units = printed / {import_scale:g})")

    largest = max(meshes, key=lambda obj: len(obj.data.vertices))
    if len(largest.data.vertices) < args.min_vertices:
        _fail(f"largest bound mesh has {len(largest.data.vertices)} vertices, below {args.min_vertices}")

    for mesh_object in meshes:
        worst_sum = _check_groups_and_weights(mesh_object, armature)
        worst_rest = _check_rest_pose_is_the_bind_pose(mesh_object)
        print(
            f"  {mesh_object.name}: {len(mesh_object.data.vertices)} vertices, "
            f"{len(mesh_object.vertex_groups)} groups, weight-sum error {worst_sum:.2e}, "
            f"rest-pose drift {worst_rest:.2e}"
        )

    for bone_name in args.pose:
        moved, mean_moved, mean_still = _check_deformation(largest, armature, bone_name)
        print(
            f"  posing {bone_name!r} on {largest.name}: moved {moved} of "
            f"{len(largest.data.vertices)} vertices, mean {mean_moved:.4f} from the bone "
            f"against {mean_still:.4f} for the rest"
        )

    print("FBX RIG OK")


if __name__ == "__main__":
    # Blender keeps going after a --python script raises and still exits 0, so an
    # unguarded assertion would print a traceback and report success. Exit codes are
    # the only thing a caller can gate on, so failures are turned into one here.
    try:
        main()
    except Exception as error:  # noqa: BLE001 - the exit code is the whole point
        import traceback

        traceback.print_exc()
        print(f"FBX RIG FAILED: {error}", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        sys.exit(1)
