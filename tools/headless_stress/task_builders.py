from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_MODEL_ROOT = Path(r"E:\ModelCatalogue\downloads")
PROFILES = ("quick", "corpus", "soak")
SOAK_MINUTES_DEFAULT = 180.0
SOAK_MINUTES_MINIMUM = 120.0
NATIVE_HELPER_RELATIVE_PATHS = (
    Path("native/cd_texture_dx/build/Release/cd-texture-dx.exe"),
    Path("native/cdmw_mesh_core/build/Release/cdmw-mesh-core.exe"),
    Path("tools/dotnet_mesh_editor_experiment/bin/Release/net10.0-windows/cdmw-mesh-dotnet-editor.exe"),
)
DEFAULT_CACHE_RUNS = 1
REAL_MESH_EDITOR_VISUAL_SCENARIO = "real-archive-mesh-editor-dotnet-edit-smoke"


@dataclass(slots=True)
class Task:
    name: str
    kind: str
    output_dir: Path
    required: bool = True
    argv: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    skip_reason: str = ""
    artifacts: list[Path] = field(default_factory=list)
    cache_cycles: int = 1
    cache_real_root: Path | None = None


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def prepare_output_root(path: Path) -> Path:
    output_root = _resolve(path)
    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"--output must be a directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root


def safe_child_dir(output_root: Path, *parts: str) -> Path:
    child = _resolve(output_root.joinpath(*parts))
    if not _is_relative_to(child, output_root):
        raise ValueError(f"Refusing to write outside --output: {child}")
    child.mkdir(parents=True, exist_ok=True)
    return child


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _python_tool(*parts: str) -> str:
    return str(REPO_ROOT.joinpath(*parts))


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def _task_dir(output_root: Path, name: str, *, cycle: int | None = None) -> Path:
    parts = ("cycles", f"{cycle:05d}", "children", name) if cycle is not None else ("children", name)
    return safe_child_dir(output_root, *parts)


def _command_task(
    output_root: Path,
    name: str,
    argv: Sequence[str],
    *,
    required: bool = True,
    cycle: int | None = None,
    artifacts: Sequence[Path] = (),
    env: Mapping[str, str] | None = None,
) -> Task:
    return Task(
        name=name,
        kind="command",
        output_dir=_task_dir(output_root, name, cycle=cycle),
        required=required,
        argv=[str(part) for part in argv],
        artifacts=[Path(path) for path in artifacts],
        env=dict(env or {}),
    )


def _skip_task(output_root: Path, name: str, reason: str, *, cycle: int | None = None) -> Task:
    return Task(name=name, kind="skip", output_dir=_task_dir(output_root, name, cycle=cycle), required=False, skip_reason=reason)


def _probe_task(
    output_root: Path,
    name: str,
    kind: str,
    *,
    cycle: int | None = None,
    cache_cycles: int = 1,
    cache_real_root: Path | None = None,
) -> Task:
    return Task(name=name, kind=kind, output_dir=_task_dir(output_root, name, cycle=cycle), cache_cycles=cache_cycles, cache_real_root=cache_real_root)


def native_helper_paths() -> tuple[Path, ...]:
    return tuple(REPO_ROOT / path for path in NATIVE_HELPER_RELATIVE_PATHS)


def _codex_check_task(output_root: Path, area: str, *, cycle: int | None = None) -> Task:
    ps = _powershell()
    name = f"codex-{area}"
    if not ps:
        return _skip_task(output_root, name, "PowerShell is not available.", cycle=cycle)
    return _command_task(
        output_root,
        name,
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", REPO_ROOT / "scripts" / "codex_check.ps1", "-Area", area],
        cycle=cycle,
    )


def _pytest_task(output_root: Path, name: str, tests: Sequence[str], *, cycle: int | None = None) -> Task:
    basetemp = safe_child_dir(output_root, "pytest-temp", name if cycle is None else f"{name}-{cycle:05d}")
    return _command_task(
        output_root,
        name,
        [sys.executable, "-m", "pytest", *tests, f"--basetemp={basetemp}"],
        cycle=cycle,
    )


def _model_audit_tasks(
    output_root: Path,
    model_root: Path,
    *,
    profile: str,
    cycle: int | None = None,
    max_files: int | None = None,
    max_zip_audits: int | None = None,
    audit_zip_contents: bool = False,
) -> list[Task]:
    if not model_root or not _resolve(model_root).exists():
        return [_skip_task(output_root, "external-model-audit", f"Model root not found: {model_root}", cycle=cycle)]
    audit_dir = _task_dir(output_root, "external-model-audit", cycle=cycle)
    check_dir = _task_dir(output_root, "external-model-audit-check", cycle=cycle)
    report_path = audit_dir / "external_model_material_audit.json"
    check_path = check_dir / "external_model_material_audit_check.json"
    files = max_files if max_files is not None else (50 if profile == "quick" else 10_000 if profile == "soak" else 50_000)
    audit_argv = [
        sys.executable,
        _python_tool("tools", "audit_external_model_catalogue.py"),
        "--root",
        str(model_root),
        "--out-json",
        str(report_path),
        "--max-files",
        str(files),
    ]
    if audit_zip_contents or profile in {"corpus", "soak"}:
        audit_argv.append("--audit-zip-contents")
    if max_zip_audits is not None:
        audit_argv.extend(["--max-zip-audits", str(max_zip_audits)])
    check_argv = [
        sys.executable,
        _python_tool("tools", "check_external_model_audit.py"),
        str(report_path),
        "--out-json",
        str(check_path),
    ]
    if profile == "quick":
        check_argv.append("--warn-only")
    return [
        Task(
            name="external-model-audit",
            kind="command",
            output_dir=audit_dir,
            argv=[str(part) for part in audit_argv],
            artifacts=[report_path],
        ),
        Task(
            name="external-model-audit-check",
            kind="command",
            output_dir=check_dir,
            argv=[str(part) for part in check_argv],
            artifacts=[check_path],
        ),
    ]


def _real_archive_tasks(
    output_root: Path,
    game_root: Path | None,
    *,
    include_native_visual: bool = False,
    cycle: int | None = None,
) -> list[Task]:
    scenarios = [
        "real-archive-rigging-smoke",
        "real-archive-animation-binding-smoke",
        "real-archive-sequence-binding-smoke",
        "real-archive-app-workflow-smoke",
    ]
    if include_native_visual:
        scenarios.append(REAL_MESH_EDITOR_VISUAL_SCENARIO)
    if not game_root or not _resolve(game_root).exists():
        return [
            _skip_task(
                output_root,
                f"mesh-{scenario}",
                f"Game root not found: {game_root or '<not supplied>'}",
                cycle=cycle,
            )
            for scenario in scenarios
        ]
    tasks: list[Task] = []
    for scenario in scenarios:
        task_dir = _task_dir(output_root, f"mesh-{scenario}", cycle=cycle)
        tasks.append(
            Task(
                name=f"mesh-{scenario}",
                kind="command",
                output_dir=task_dir,
                argv=[
                    sys.executable,
                    _python_tool("tools", "mesh_editor_dev_harness.py"),
                    "--scenario",
                    scenario,
                    "--game-root",
                    str(game_root),
                    "--output",
                    str(task_dir),
                ],
                artifacts=[task_dir / "result.json", task_dir / "evidence_report.json"],
            )
        )
    return tasks


def build_profile_tasks(args: argparse.Namespace, output_root: Path, *, cycle: int | None = None) -> list[Task]:
    profile = str(args.profile)
    cache_runs = int(args.cache_runs or (3 if profile == "soak" else 2 if profile == "corpus" else DEFAULT_CACHE_RUNS))
    cache_real_root = Path(args.cache_real_root) if getattr(args, "cache_real_root", None) else None
    tasks: list[Task] = [
        _probe_task(output_root, "cache-probe", "cache-probe", cycle=cycle, cache_cycles=cache_runs, cache_real_root=cache_real_root),
        _probe_task(output_root, "worker-probe", "worker-probe", cycle=cycle),
    ]
    if bool(getattr(args, "cache_only", False)):
        return tasks[:1]

    if profile == "quick":
        mesh_dir = _task_dir(output_root, "mesh-service-smoke", cycle=cycle)
        texture_dir = _task_dir(output_root, "texture-preset-matrix", cycle=cycle)
        tasks.extend(
            [
                _command_task(
                    output_root,
                    "mesh-service-smoke",
                    [
                        sys.executable,
                        _python_tool("tools", "mesh_editor_dev_harness.py"),
                        "--scenario",
                        "service-smoke",
                        "--output",
                        str(mesh_dir),
                    ],
                    cycle=cycle,
                    artifacts=[mesh_dir / "result.json", mesh_dir / "evidence_report.json"],
                ),
                _command_task(
                    output_root,
                    "texture-preset-matrix",
                    [
                        sys.executable,
                        _python_tool("tools", "texture_editor_dev_harness.py"),
                        "--scenario",
                        "preset-matrix",
                        "--output",
                        str(texture_dir),
                    ],
                    cycle=cycle,
                    artifacts=[texture_dir / "result.json"],
                ),
                _codex_check_task(output_root, "smoke", cycle=cycle),
            ]
        )
        tasks.extend(
            _model_audit_tasks(
                output_root,
                Path(args.model_root),
                profile=profile,
                cycle=cycle,
                max_files=args.max_model_files,
                max_zip_audits=args.max_zip_audits,
                audit_zip_contents=bool(args.audit_zip_contents),
            )
        )
        return tasks

    mesh_dir = _task_dir(output_root, "mesh-service-protocol-smoke", cycle=cycle)
    texture_dir = _task_dir(output_root, "texture-full-suite-smoke", cycle=cycle)
    tasks.extend(
        [
            _probe_task(output_root, "native-helper-preflight", "native-helper-preflight", cycle=cycle),
            _command_task(
                output_root,
                "mesh-service-protocol-smoke",
                [
                    sys.executable,
                    _python_tool("tools", "mesh_editor_dev_harness.py"),
                    "--scenario",
                    "service-smoke",
                    "--output",
                    str(mesh_dir),
                ],
                cycle=cycle,
                artifacts=[mesh_dir / "result.json", mesh_dir / "evidence_report.json"],
            ),
            _command_task(
                output_root,
                "texture-full-suite-smoke",
                [
                    sys.executable,
                    _python_tool("tools", "texture_editor_dev_harness.py"),
                    "--scenario",
                    "full-suite-smoke",
                    "--output",
                    str(texture_dir),
                ],
                cycle=cycle,
                artifacts=[texture_dir / "result.json"],
            ),
            _pytest_task(
                output_root,
                "mesh-replacement-pytest",
                (
                    "tests/test_static_replacement_preview_models.py",
                    "tests/test_static_replacement_accept_state.py",
                    "tests/test_static_replacement_build_footer.py",
                    "tests/test_full_import_model_replacement.py",
                ),
                cycle=cycle,
            ),
            _codex_check_task(output_root, "responsiveness", cycle=cycle),
            _codex_check_task(output_root, "archive", cycle=cycle),
            _codex_check_task(output_root, "mesh-unit", cycle=cycle),
            _codex_check_task(output_root, "texture", cycle=cycle),
        ]
    )
    tasks.extend(
        _model_audit_tasks(
            output_root,
            Path(args.model_root),
            profile=profile,
            cycle=cycle,
            max_files=args.max_model_files,
            max_zip_audits=args.max_zip_audits,
            audit_zip_contents=bool(args.audit_zip_contents),
        )
    )
    tasks.extend(
        _real_archive_tasks(
            output_root,
            Path(args.game_root) if args.game_root else None,
            include_native_visual=bool(getattr(args, "include_native_visual", False)),
            cycle=cycle,
        )
    )
    return tasks
