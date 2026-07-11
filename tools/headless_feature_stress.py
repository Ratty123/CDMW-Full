from __future__ import annotations

from importlib import import_module
from pathlib import Path
import sys
import time

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_EXPORTS: dict[str, str] = {}
for _owner, _names in (
    (
        "tools.headless_stress.task_builders",
        (
            "REPO_ROOT", "DEFAULT_MODEL_ROOT", "PROFILES", "SOAK_MINUTES_DEFAULT",
            "SOAK_MINUTES_MINIMUM", "NATIVE_HELPER_RELATIVE_PATHS", "DEFAULT_CACHE_RUNS",
            "REAL_MESH_EDITOR_VISUAL_SCENARIO", "Task", "_resolve", "_is_relative_to",
            "prepare_output_root", "safe_child_dir", "_json_safe", "_write_json", "_read_json",
            "_python_tool", "_powershell", "_task_dir", "_command_task", "_skip_task",
            "_probe_task", "native_helper_paths", "_codex_check_task", "_pytest_task",
            "_model_audit_tasks", "_real_archive_tasks", "build_profile_tasks",
        ),
    ),
    (
        "tools.headless_stress.cache_probe",
        (
            "run_cache_probe", "run_real_cache_probe", "_fresh_process_cache_load",
            "_fresh_process_accelerated_cache_load", "_tree_size_bytes", "_phase_stats",
            "_cache_probe_summary",
        ),
    ),
    (
        "tools.headless_stress.probes",
        ("run_worker_probe", "run_native_helper_preflight"),
    ),
    (
        "tools.headless_stress.runner",
        (
            "run_task", "_task_result_from_probe", "merge_report", "write_reports",
            "run_profile", "run_soak",
        ),
    ),
    ("tools.headless_stress.cli", ("parse_args", "main")),
):
    _EXPORTS.update(dict.fromkeys(_names, _owner))
del _names, _owner


def __getattr__(name: str) -> object:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


if __name__ == "__main__":
    raise SystemExit(__getattr__("main")())
