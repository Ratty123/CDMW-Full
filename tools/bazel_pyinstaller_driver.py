"""Stage the app tree and run PyInstaller. Invoked by //build_defs:pyinstaller.bzl.

CrimsonDesertModWorkbench.spec resolves everything from SPECPATH and expects the
native helpers under native/<project>/build/<Configuration>/. Bazel builds those
somewhere else entirely, so this assembles a tree that looks the way the spec
expects and runs PyInstaller inside it.

Nothing here writes to the source tree: every path lands under the Bazel-declared
stage/work directories.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--exe-name", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--mode", default="onefile")
    parser.add_argument("--profile", default="release")
    return parser.parse_args()


def _stage_entries(manifest_path: Path, stage: Path) -> int:
    staged = 0
    for raw in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("|")
        source = Path(parts[0])
        destination = parts[1]
        is_tree = len(parts) > 2 and parts[2] == "tree"

        if is_tree:
            # A dotnet publish output: copy the directory's contents into the
            # staged directory, which is what the spec walks with rglob.
            target_dir = stage / destination
            target_dir.mkdir(parents=True, exist_ok=True)
            for item in source.rglob("*"):
                if not item.is_file():
                    continue
                target = target_dir / item.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                staged += 1
            continue

        target = stage / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            continue
        shutil.copy2(source, target)
        staged += 1
    return staged


def main() -> int:
    args = _parse_args()
    stage = Path(args.stage).resolve()
    work = Path(args.work).resolve()
    out = Path(args.out).resolve()
    manifest = Path(args.manifest).resolve()

    stage.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    staged = _stage_entries(manifest, stage)
    print(f"staged {staged} files into {stage}", flush=True)

    spec_in_stage = stage / args.spec
    if not spec_in_stage.is_file():
        print(f"spec was not staged: {spec_in_stage}", file=sys.stderr)
        return 1

    dist_dir = work / "dist"
    build_dir = work / "build"

    environment = dict(os.environ)
    environment["CDMW_PYINSTALLER_MODE"] = args.mode
    environment["CDMW_PYINSTALLER_PROFILE"] = args.profile
    # The spec imports cdmw.build_metadata off SPECPATH before PyInstaller runs.
    environment["PYTHONPATH"] = str(stage)

    command = [
        args.python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        str(spec_in_stage),
    ]
    print("running: " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=str(stage), env=environment, check=False)
    if completed.returncode != 0:
        print(f"PyInstaller failed with exit code {completed.returncode}", file=sys.stderr)
        return completed.returncode

    produced = dist_dir / args.exe_name
    if not produced.is_file():
        print(f"PyInstaller did not produce {produced}", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(produced, out)
    print(f"wrote {out} ({out.stat().st_size} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
