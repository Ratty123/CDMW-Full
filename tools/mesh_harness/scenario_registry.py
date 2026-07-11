from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ScenarioMetadata:
    name: str
    headless: bool
    visual: bool
    real_game: bool
    timeout_seconds: float
    process_ownership: str
    scenario_role: str
    expected_backend: str
    expected_renderer_backend: str
    expected_edit_backend: str
    compatibility_only: bool

    @property
    def normal_qa(self) -> bool:
        return not (self.visual or self.real_game or self.compatibility_only)

    def as_dict(self) -> dict[str, object]:
        return {**asdict(self), "normal_qa": self.normal_qa}


def _scenario(
    name: str,
    *,
    headless: bool = True,
    visual: bool = False,
    real_game: bool = False,
    timeout_seconds: float = 30.0,
    process_ownership: str = "none",
    scenario_role: str = "regression",
    expected_backend: str = "python",
    expected_renderer_backend: str = "",
    expected_edit_backend: str = "",
    compatibility_only: bool = False,
) -> ScenarioMetadata:
    return ScenarioMetadata(
        name=name,
        headless=headless,
        visual=visual,
        real_game=real_game,
        timeout_seconds=timeout_seconds,
        process_ownership=process_ownership,
        scenario_role=scenario_role,
        expected_backend=expected_backend,
        expected_renderer_backend=expected_renderer_backend,
        expected_edit_backend=expected_edit_backend,
        compatibility_only=compatibility_only,
    )


_ROWS = (
    _scenario(
        "full-suite-smoke",
        headless=False,
        visual=True,
        process_ownership="harness",
        scenario_role="synthetic_legacy_protocol",
        expected_backend="native-mesh-core+legacy-cpp-d3d11",
        compatibility_only=True,
    ),
    _scenario("service-smoke", scenario_role="service_regression", expected_backend="native-mesh-core-or-python-fallback"),
    _scenario("asset-authoring-discovery", scenario_role="helper_discovery"),
    _scenario("asset-authoring-mesh-health", scenario_role="authoring_report", expected_backend="python+optional-meshoptimizer"),
    _scenario("asset-authoring-uv-report", scenario_role="authoring_report", expected_backend="python+optional-xatlas"),
    _scenario("asset-authoring-tangent-report", scenario_role="authoring_report", expected_backend="native-mesh-core-or-python-fallback"),
    _scenario("asset-authoring-openimageio-report", scenario_role="authoring_report", expected_backend="python+optional-openimageio"),
    _scenario("long-edit-mesh-tools", scenario_role="headless_edit_regression", expected_backend="native-mesh-core-or-python-fallback"),
    _scenario("native-mesh-editor-benchmark", timeout_seconds=120.0, expected_backend="native-mesh-core"),
    _scenario("native-mesh-editor-sparse-update-soak", timeout_seconds=600.0, expected_backend="native-mesh-core"),
    _scenario(
        "native-mesh-editor-d3d11-delta",
        headless=False,
        visual=True,
        process_ownership="harness",
        scenario_role="synthetic_legacy_protocol",
        expected_backend="legacy-cpp-d3d11",
        compatibility_only=True,
    ),
    _scenario(
        "native-mesh-editor-d3d11-payloads",
        headless=False,
        visual=True,
        process_ownership="harness",
        scenario_role="synthetic_legacy_protocol",
        expected_backend="legacy-cpp-d3d11",
        compatibility_only=True,
    ),
    _scenario("native-mesh-editor-qt-cancellation", process_ownership="qt-thread", scenario_role="headless_qt_probe", expected_backend="native-mesh-core"),
    _scenario("native-mesh-editor-qt-responsiveness", process_ownership="qt-thread", scenario_role="headless_qt_probe", expected_backend="native-mesh-core"),
    _scenario("native-mesh-editor-standalone-stroke", scenario_role="headless_protocol", expected_backend="native-mesh-core"),
    _scenario("native-mesh-editor-static-screen-stroke", scenario_role="headless_protocol", expected_backend="native-mesh-core"),
    _scenario("native-mesh-editor-workflow", scenario_role="headless_edit_regression", expected_backend="native-mesh-core-or-python-fallback"),
    _scenario("real-archive-rigging-smoke", real_game=True, timeout_seconds=120.0, scenario_role="real_archive_readonly"),
    _scenario("real-archive-animation-binding-smoke", real_game=True, timeout_seconds=120.0, scenario_role="real_archive_readonly"),
    _scenario("real-archive-sequence-binding-smoke", real_game=True, timeout_seconds=120.0, scenario_role="real_archive_readonly"),
    _scenario("real-archive-app-workflow-smoke", real_game=True, timeout_seconds=120.0, scenario_role="real_archive_ui_model_smoke", expected_backend="qt-offscreen+python"),
    _scenario(
        "real-archive-mesh-editor-dotnet-edit-smoke",
        headless=False,
        visual=True,
        real_game=True,
        timeout_seconds=180.0,
        process_ownership="harness",
        scenario_role="production_visual_proof",
        expected_backend="dotnet+d3d11",
        expected_renderer_backend="d3d11_vortice_shader",
        expected_edit_backend="cdmw_mesh_core_0.1",
    ),
    _scenario(
        "real-archive-mesh-editor-d3d11-edit-smoke",
        headless=False,
        visual=True,
        real_game=True,
        timeout_seconds=180.0,
        process_ownership="harness",
        scenario_role="native_renderer_compatibility",
        expected_backend="legacy-cpp-d3d11",
        compatibility_only=True,
    ),
    _scenario(
        "real-archive-mesh-editor-d3d11-side-by-side-edit-smoke",
        headless=False,
        visual=True,
        real_game=True,
        timeout_seconds=180.0,
        process_ownership="harness",
        scenario_role="native_renderer_compatibility",
        expected_backend="legacy-cpp-d3d11",
        compatibility_only=True,
    ),
    _scenario(
        "mesh-dotnet-native-parity-report",
        process_ownership="none",
        scenario_role="blocked_report_scaffold",
        expected_backend="not_implemented",
    ),
)

_PRODUCTION_VISUAL_SCENARIO = "real-archive-mesh-editor-dotnet-edit-smoke"
_PRODUCTION_RENDERER_BACKEND = "d3d11_vortice_shader"
_PRODUCTION_EDIT_BACKEND = "cdmw_mesh_core_0.1"


def _validate_scenario(row: ScenarioMetadata) -> None:
    if not row.name.strip():
        raise ValueError("Mesh Editor harness scenario name is required.")
    if row.headless and row.visual:
        raise ValueError(f"Visual Mesh Editor harness scenario cannot be headless: {row.name}")
    legacy_role = row.scenario_role in {"synthetic_legacy_protocol", "native_renderer_compatibility"}
    legacy_backend = "legacy" in row.expected_backend.casefold()
    if (legacy_role or legacy_backend) and not row.compatibility_only:
        raise ValueError(f"Legacy/checker Mesh Editor harness must be compatibility-only: {row.name}")
    if row.compatibility_only and (row.headless or not row.visual or row.normal_qa):
        raise ValueError(f"Compatibility-only Mesh Editor harness must be opt-in visual: {row.name}")
    if row.scenario_role == "production_visual_proof":
        if row.name != _PRODUCTION_VISUAL_SCENARIO:
            raise ValueError(f"Unexpected production Mesh Editor visual proof: {row.name}")
        if not (
            row.visual
            and row.real_game
            and not row.headless
            and not row.compatibility_only
            and row.process_ownership == "harness"
            and row.expected_backend == "dotnet+d3d11"
            and row.expected_renderer_backend == _PRODUCTION_RENDERER_BACKEND
            and row.expected_edit_backend == _PRODUCTION_EDIT_BACKEND
        ):
            raise ValueError(
                "Production Mesh Editor visual proof must use the real-game .NET/Vortice renderer "
                f"and native edit core: {row.name}"
            )


def validate_scenario_registry(rows: tuple[ScenarioMetadata, ...] | list[ScenarioMetadata]) -> None:
    names = [row.name for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate Mesh Editor harness scenario name.")
    for row in rows:
        _validate_scenario(row)
    production = [row for row in rows if row.scenario_role == "production_visual_proof"]
    if len(production) != 1:
        raise ValueError("Mesh Editor harness registry must contain exactly one production visual proof.")


validate_scenario_registry(list(_ROWS))
SCENARIOS = {row.name: row for row in _ROWS}


def scenario_metadata(name: str) -> ScenarioMetadata:
    try:
        row = SCENARIOS[str(name)]
    except KeyError as exc:
        raise ValueError(f"Unknown Mesh Editor harness scenario: {name}") from exc
    _validate_scenario(row)
    return row


def scenario_names() -> tuple[str, ...]:
    return tuple(SCENARIOS)


__all__ = ["SCENARIOS", "ScenarioMetadata", "scenario_metadata", "scenario_names", "validate_scenario_registry"]
