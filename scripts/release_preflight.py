from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

GENERATED_PREFIXES = (
    "tools/dotnet_mesh_editor_experiment/bin/",
    "tools/dotnet_mesh_editor_experiment/obj/",
    "build/",
    "dist/",
    ".pytest_cache/",
    ".pytest-tmp/",
)
SOURCE_SUFFIXES = {
    ".cs",
    ".cpp",
    ".h",
    ".hpp",
    ".csproj",
    ".hlsl",
    ".py",
    ".ps1",
    ".spec",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".xml",
}
UNTRACKED_PROJECT_SOURCE_PREFIXES = (
    "cdmw/",
    "docs/",
    "native/",
    "pyinstaller_hooks/",
    "schemas/",
    "scripts/",
    "tests/",
    "tools/",
)


def classify_git_status(lines: Iterable[str]) -> dict[str, list[str]]:
    inventory: dict[str, list[str]] = {
        "required_source_or_docs": [],
        "generated_output": [],
        "unclassified_untracked_source": [],
        "other_dirty": [],
    }
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        status = line[:2]
        path = line[3:].replace("\\", "/") if len(line) > 3 else ""
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if _is_generated(path):
            inventory["generated_output"].append(path)
        elif status == "??" and _is_project_source(path):
            inventory["required_source_or_docs"].append(path)
        elif status == "??" and Path(path).suffix.lower() in SOURCE_SUFFIXES:
            inventory["unclassified_untracked_source"].append(path)
        elif Path(path).suffix.lower() in SOURCE_SUFFIXES:
            inventory["required_source_or_docs"].append(path)
        else:
            inventory["other_dirty"].append(path)
    return {key: sorted(values) for key, values in inventory.items()}


def release_blockers(inventory: dict[str, list[str]]) -> list[str]:
    blockers: list[str] = []
    if inventory.get("generated_output"):
        blockers.append("generated_output_present")
    if inventory.get("unclassified_untracked_source"):
        blockers.append("unclassified_untracked_source_present")
    return blockers


def _is_generated(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in GENERATED_PREFIXES)


def _is_project_source(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return Path(normalized).suffix.lower() in SOURCE_SUFFIXES and any(
        normalized.startswith(prefix) for prefix in UNTRACKED_PROJECT_SOURCE_PREFIXES
    )


def _git_status(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        text=True,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git status failed")
    return result.stdout.splitlines()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release packaging dirty-tree preflight.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--inventory", default="")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    inventory = classify_git_status(_git_status(repo_root))
    blockers = release_blockers(inventory)
    payload = {"ok": not blockers, "blockers": blockers, "inventory": inventory}
    if args.inventory:
        output_path = Path(args.inventory)
        if not output_path.is_absolute():
            output_path = repo_root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if blockers and not args.allow_dirty:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
