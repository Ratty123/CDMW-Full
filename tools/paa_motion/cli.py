"""Inspect and export Crimson Desert `.paa` motion clips.

    python -m tools.paa_motion.cli info    <clip.paa> [--skeleton <phm_01.pab>]
    python -m tools.paa_motion.cli tracks  <clip.paa> --skeleton <phm_01.pab>
    python -m tools.paa_motion.cli pose    <clip.paa> --skeleton <phm_01.pab> [--frame N]
    python -m tools.paa_motion.cli export  <clip.paa> --skeleton <phm_01.pab> -o <out.glb>
    python -m tools.paa_motion.cli survey  <directory>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `python tools/paa_motion/cli.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.paa_motion.format import FPS, PaaFormatError, parse_paa  # noqa: E402
from tools.paa_motion.gltf import write_glb  # noqa: E402
from tools.paa_motion.pose import world_positions  # noqa: E402


def _load_skeleton(path: str):
    from cdmw.modding.skeleton_parser import parse_pab

    return parse_pab(Path(path).read_bytes(), os.path.basename(path))


def _bone_names(skeleton) -> dict[int, str]:
    return {bone.name_hash: bone.name for bone in skeleton.bones}


def _clip(path: str):
    return parse_paa(Path(path).read_bytes(), name=os.path.basename(path))


def cmd_info(args) -> int:
    clip = _clip(args.clip)
    print(f"{os.path.basename(args.clip)}")
    print(f"  version        {clip.version[0]}.{clip.version[1]}   flags 0x{clip.flags:08X}")
    print(f"  duration       {clip.duration:.4f}s   {clip.frame_count} frames @ {FPS:g}fps")
    print(f"  tracks         {len(clip.tracks)} ({clip.skeletal_bone_count} skeletal"
          f" + {clip.root_bone_count} root-motion)")
    packed = sum(1 for track in clip.tracks if track.packed)
    codec = f"packed, 1/64 bytes ({packed} skeletal records)" if packed else "half/float"
    print(f"  track codec    {codec}")
    print(f"  key payload    {clip.key_bytes} bytes")
    if clip.skeleton_path:
        print(f"  skeleton       {clip.skeleton_path}")
    if clip.unit_scale:
        print(f"  unit scale     {clip.unit_scale:.5f}")
    for tag in clip.tags:
        print(f"  tag            {tag}")
    return 0


def cmd_tracks(args) -> int:
    clip = _clip(args.clip)
    names = _bone_names(_load_skeleton(args.skeleton)) if args.skeleton else {}
    print(f"{'#':>4}  {'hash':>8}  {'bone':<32} {'scale':>6} {'rot':>6} {'trans':>6}  kind")
    for index, track in enumerate(clip.tracks):
        print(f"{index:>4}  {track.name_hash:08X}  {names.get(track.name_hash, '<unknown>'):<32}"
              f" {len(track.scale):>6} {len(track.rotation):>6} {len(track.translation):>6}"
              f"  {'root' if track.root_motion else 'skeletal'}")
    return 0


def cmd_pose(args) -> int:
    clip = _clip(args.clip)
    skeleton = _load_skeleton(args.skeleton)
    frame = args.frame if args.frame is not None else 0
    positions = world_positions(skeleton, clip, float(frame))
    animated = {track.name_hash for track in clip.tracks if track.animated}
    print(f"frame {frame} of {clip.last_frame}  ({frame / FPS:.3f}s)")
    for bone, position in zip(skeleton.bones, positions):
        if args.all or bone.name_hash in animated:
            print(f"  {bone.name:<34} {position[0]:9.4f} {position[1]:9.4f} {position[2]:9.4f}")
    return 0


def cmd_export(args) -> int:
    clip = _clip(args.clip)
    skeleton = _load_skeleton(args.skeleton)
    output = args.output or (os.path.splitext(args.clip)[0] + ".glb")
    size = write_glb(
        output, skeleton, clip,
        name=os.path.splitext(os.path.basename(args.clip))[0],
        show_joints=not args.no_joints,
    )
    print(f"wrote {output} ({size} bytes, {clip.frame_count} frames, {clip.duration:.3f}s)")
    return 0


def cmd_survey(args) -> int:
    ok = 0
    failed: list[tuple[str, str]] = []
    for dirpath, _dirs, names in os.walk(args.directory):
        for name in sorted(names):
            if not name.lower().endswith(".paa"):
                continue
            path = os.path.join(dirpath, name)
            try:
                clip = _clip(path)
            except PaaFormatError as error:
                failed.append((name, str(error)))
                continue
            ok += 1
            if args.verbose:
                print(f"  {name:<62} {clip.frame_count:>5} frames  {len(clip.tracks):>4} tracks")
    print(f"decoded {ok}, undecodable {len(failed)}")
    for name, error in failed:
        print(f"  FAIL {name}: {error}")
    return 1 if failed and args.strict else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paa_motion", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="header and prelude summary")
    info.add_argument("clip")
    info.set_defaults(func=cmd_info)

    tracks = sub.add_parser("tracks", help="per-bone key counts")
    tracks.add_argument("clip")
    tracks.add_argument("--skeleton", help=".pab to resolve bone-name hashes")
    tracks.set_defaults(func=cmd_tracks)

    pose = sub.add_parser("pose", help="world-space bone positions at one frame")
    pose.add_argument("clip")
    pose.add_argument("--skeleton", required=True)
    pose.add_argument("--frame", type=int)
    pose.add_argument("--all", action="store_true", help="include bones the clip does not animate")
    pose.set_defaults(func=cmd_pose)

    export = sub.add_parser("export", help="write a playable .glb")
    export.add_argument("clip")
    export.add_argument("--skeleton", required=True)
    export.add_argument("-o", "--output")
    export.add_argument("--no-joints", action="store_true", help="omit the joint marker cubes")
    export.set_defaults(func=cmd_export)

    survey = sub.add_parser("survey", help="decode every .paa under a directory")
    survey.add_argument("directory")
    survey.add_argument("--verbose", action="store_true")
    survey.add_argument("--strict", action="store_true", help="exit non-zero on any failure")
    survey.set_defaults(func=cmd_survey)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
