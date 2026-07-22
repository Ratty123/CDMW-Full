"""D3D11 loading and watchdog detail text helpers."""

from __future__ import annotations


def alignment_d3d11_resources_waiting_detail(
    *,
    reason: str,
    elapsed_s: float,
    last_percent: int,
    last_stage: str,
    host_detail: str,
    child_detail: str,
    active_package: object,
) -> str:
    return (
        ".NET/Vortice uploaded package resources but the preview panel is not renderable yet.\n"
        f"elapsed={max(0.0, float(elapsed_s or 0.0)):.1f}s\n"
        f"last_progress={int(last_percent or 0)}%\n"
        f"last_stage={str(last_stage or 'unknown')}\n"
        f"reason={str(reason or '')}\n"
        f"host={str(host_detail or '')}\n"
        f"child={str(child_detail or '')}\n"
        f"active_package={active_package}"
    )


def alignment_d3d11_resources_waiting_performance_details(
    *,
    reason: str,
    elapsed_s: float,
    host_detail: str,
    child_detail: str,
    active_package: object,
) -> str:
    return (
        f"reason={str(reason or '')}\n"
        f"elapsed={max(0.0, float(elapsed_s or 0.0)):.1f}s\n"
        f"host={str(host_detail or '')}\n"
        f"child={str(child_detail or '')}\n"
        f"active_package={active_package}"
    )


def alignment_d3d11_stale_loading_detail(
    *,
    reason: str,
    elapsed_s: float,
    last_percent: int,
    last_stage: str,
    host_detail: str,
    child_detail: str,
    active_package: object,
) -> str:
    return (
        ".NET/Vortice stayed alive but did not report a fresh rendered frame.\n"
        f"elapsed={max(0.0, float(elapsed_s or 0.0)):.1f}s\n"
        f"last_progress={int(last_percent or 0)}%\n"
        f"last_stage={str(last_stage or 'unknown')}\n"
        f"reason={str(reason or '')}\n"
        f"host={str(host_detail or '')}\n"
        f"child={str(child_detail or '')}\n"
        f"active_package={active_package}"
    )


def alignment_d3d11_restart_performance_details(
    stale_details: str,
    *,
    restart_count: int,
    max_restarts: int = 2,
) -> str:
    return (
        f"{str(stale_details or '')}\n"
        f"restart={int(restart_count or 0) + 1}/{int(max_restarts or 0)}\n"
        "The stale .NET/Vortice load was cancelled and the latest preview request was queued immediately."
    )


def alignment_d3d11_failed_performance_details(stale_details: str) -> str:
    return (
        f"{str(stale_details or '')}\n"
        "The .NET/Vortice renderer stayed alive, but no package-loaded acknowledgement arrived before the watchdog."
    )


__all__ = [
    "alignment_d3d11_failed_performance_details",
    "alignment_d3d11_resources_waiting_detail",
    "alignment_d3d11_resources_waiting_performance_details",
    "alignment_d3d11_restart_performance_details",
    "alignment_d3d11_stale_loading_detail",
]
