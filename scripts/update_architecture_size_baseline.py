"""Regenerate explicit whole-repository size-ratchet baselines."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_architecture_size_ratchets import (  # noqa: E402
    FILE_LINE_LIMIT,
    FUNCTION_LINE_LIMIT,
    _current_size_data,
)


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _partition_functions(functions: dict[str, int]) -> dict[str, dict[str, int]]:
    predicates: tuple[tuple[str, Callable[[str], bool]], ...] = (
        ("core", lambda key: key.startswith("cdmw/core/")),
        (
            "cdmw_layers",
            lambda key: key.startswith("cdmw/") and not key.startswith(("cdmw/core/", "cdmw/ui/")),
        ),
        ("ui_static", lambda key: key.startswith("cdmw/ui/archive_browser/static_replacement")),
        (
            "ui_archive",
            lambda key: key.startswith("cdmw/ui/archive_browser/")
            and not key.startswith("cdmw/ui/archive_browser/static_replacement"),
        ),
        (
            "ui_other",
            lambda key: key.startswith("cdmw/ui/") and not key.startswith("cdmw/ui/archive_browser/"),
        ),
        ("tests", lambda key: key.startswith("tests/")),
        (
            "native_csharp",
            lambda key: key.startswith(("native/", "tools/dotnet_mesh_editor_experiment/")),
        ),
        (
            "tools_root",
            lambda key: not key.startswith(
                ("cdmw/", "tests/", "native/", "tools/dotnet_mesh_editor_experiment/")
            ),
        ),
    )
    partitions = {
        name: {key: value for key, value in functions.items() if predicate(key)}
        for name, predicate in predicates
    }
    assigned = {key for rows in partitions.values() for key in rows}
    if assigned != set(functions):
        raise RuntimeError(f"Unpartitioned size-ratchet functions: {sorted(set(functions) - assigned)}")
    return partitions


def main() -> int:
    current = _current_size_data()
    baseline_root = ROOT / "tests"
    _write_json_atomic(
        baseline_root / "architecture_size_baseline.json",
        {
            "files": {},
            "functions": {},
            "limits": {"file_lines": FILE_LINE_LIMIT, "function_lines": FUNCTION_LINE_LIMIT},
            "schema": 1,
        },
    )
    _write_json_atomic(
        baseline_root / "architecture_size_baseline_files.json",
        {"files": current["files"]},
    )
    partitions = _partition_functions(current["functions"])
    for name, functions in partitions.items():
        _write_json_atomic(
            baseline_root / f"architecture_size_baseline_functions_{name}.json",
            {"functions": functions},
        )
    print(f"Recorded {len(current['files'])} oversized files and {len(current['functions'])} oversized functions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
