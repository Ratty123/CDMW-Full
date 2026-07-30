"""Print the geometry verdict from the newest real-archive mesh proof run.

The proof writes a 1.4 MB result.json. The one question that decides who owns the
remaining `captures_ok` failure is whether the presented frame, the control's
client area and the window Windows reports all describe the same rectangle, and
that answer is four numbers buried in it.

    .venv\\Scripts\\python.exe scripts\\read_mesh_proof_geometry.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def newest_run() -> Path | None:
    root = Path(os.environ.get("TEMP", "."))
    runs = sorted(
        (path for path in root.glob("cdmw-real-archive-mesh-editor-dotnet-*") if (path / "result.json").is_file()),
        key=lambda path: (path / "result.json").stat().st_mtime,
        reverse=True,
    )
    return runs[0] if runs else None


def rect(payload: object) -> str:
    if not isinstance(payload, dict):
        return "unavailable"
    if payload.get("available") is False:
        return "unavailable"
    width = payload.get("width", "?")
    height = payload.get("height", "?")
    if "screen_x" in payload:
        return f"{width}x{height} at screen ({payload.get('screen_x')},{payload.get('screen_y')})"
    return f"{width}x{height}"


def main() -> int:
    run = newest_run()
    if run is None:
        print("No mesh proof run found under %TEMP%.")
        return 2
    result = json.loads((run / "result.json").read_text(encoding="utf-8"))
    print(f"run: {run.name}")
    print(f"overall ok: {result.get('ok')}")

    for scenario, payload in result.items():
        # A scenario that aborts early has no `gates` at all; printing it anyway is
        # the difference between "it failed here" and an empty report.
        if not isinstance(payload, dict) or "ok" not in payload:
            continue
        gates = payload.get("gates") or {}
        failed = sorted(name for name, value in gates.items() if value is False)
        counted = f"{len(gates) - len(failed)}/{len(gates)} gates" if gates else "aborted before gates"
        print(f"\n{scenario}: ok={payload.get('ok')} ({counted})")
        if payload.get("error"):
            print(f"  error: {payload['error']}")
        if failed:
            print(f"  failed gates: {', '.join(failed)}")

        refresh = payload.get("viewport_refresh") or {}
        audit = refresh.get("renderer_geometry_audit") or {}
        if refresh:
            print("  viewport at probe time:")
            print(f"    renderer pane            {rect(refresh.get('renderer_pane'))}")
            print(f"    OS window, same moment   {rect(refresh.get('os_window_at_same_moment'))}")
            print(f"    agreed                   {refresh.get('renderer_matches_os_window')}")
        if audit:
            print("  sampled inside the control, one instant:")
            print(f"    WinForms client area     {rect(audit.get('winforms_client'))}")
            print(f"    Windows window rect      {rect(audit.get('os_window'))}")
            print(f"    swap chain rendered at   {rect(audit.get('presented_render_size'))}")
            print(f"    client == OS window      {audit.get('client_matches_os_window')}")
            print(f"    presented == client      {audit.get('presented_matches_client')}")
            print(f"    presented == OS window   {audit.get('presented_matches_os_window')}")
            print(f"    resize commit pending    {audit.get('resize_commit_pending')}")

        proof = payload.get("visual_edit_proof_summary") or {}
        if proof:
            print("  visual edit proof:")
            print(f"    before/after centre      {proof.get('before_center')} -> {proof.get('after_center')}")
            print(f"    crop box                 {proof.get('crop_box')}")
            print(f"    changed pixels           {proof.get('changed_pixel_count')}")

    print(
        "\nVerdict: if 'presented == client' is false the renderer is presenting a stale\n"
        "size and the squashed image is a product bug; if it is true and the sizes simply\n"
        "changed between probe and capture, the harness must map through the rectangle\n"
        "recorded with the capture."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
