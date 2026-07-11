from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


# Source files stay immutable within one pytest process; cache bounded aggregates.
@lru_cache(maxsize=4)
def cmake_target_source(project: str, owner_variable: str) -> str:
    project_root = ROOT / "native" / project
    cmake = (project_root / "CMakeLists.txt").read_text(encoding="utf-8")
    match = re.search(
        rf"set\(\s*{re.escape(owner_variable)}\s+(.*?)\)",
        cmake,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"{owner_variable} missing from {project_root / 'CMakeLists.txt'}")
    paths = [project_root / "src" / "main.cpp"]
    paths.extend(
        project_root / value
        for value in re.findall(r"[^\s#]+\.(?:cxx|cpp|cc|c|hpp|h)\b", match.group(1))
    )
    paths.extend(
        path
        for path in sorted((project_root / "src").glob("*.h*"))
        if path not in paths
    )
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise AssertionError(f"CMake source list has missing files: {missing}")
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in paths)


@lru_cache(maxsize=1)
def preview_core_source() -> str:
    return cmake_target_source("cdmw_preview_core", "PREVIEW_CORE_OWNER_SOURCES")


@lru_cache(maxsize=1)
def d3d11_preview_source() -> str:
    return cmake_target_source("cdmw_d3d11_preview", "D3D_PREVIEW_OWNER_SOURCES").replace("Renderer::", "")
