from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from cdmw.core.common import ProcessTimeoutExpired, run_process_with_cancellation

_TEXCONV_WORKFLOW_TIMEOUT_SECONDS = 10.0 * 60.0
_TEXCONV_WORKFLOW_WARNING_INTERVAL_SECONDS = 30.0

def build_texconv_command(
    texconv_path: Path,
    png_path: Path,
    output_dir: Path,
    fmt: str,
    mips: int,
    resize_width: Optional[int],
    resize_height: Optional[int],
    overwrite_existing_dds: bool,
    color_args: Optional[Sequence[str]] = None,
    extra_args: Optional[Sequence[str]] = None,
) -> List[str]:
    cmd = [str(texconv_path), "-nologo"]

    if overwrite_existing_dds:
        cmd.append("-y")

    cmd.extend(
        [
            "-ft",
            "dds",
            "-f",
            fmt,
            "-m",
            str(mips),
            "-o",
            str(output_dir),
        ]
    )

    if resize_width is not None and resize_height is not None:
        cmd.extend(["-w", str(resize_width), "-h", str(resize_height)])

    if color_args:
        cmd.extend(str(arg) for arg in color_args if str(arg).strip())
    if extra_args:
        cmd.extend(str(arg) for arg in extra_args if str(arg).strip())

    cmd.append(str(png_path))
    return cmd


def _run_texture_workflow_texconv(
    cmd: Sequence[str],
    *,
    detail_label: str,
    on_log: Optional[Callable[[str], None]],
    stop_event: Optional[threading.Event],
) -> Tuple[int, str, str, float]:
    started_at = time.monotonic()

    def emit_timeout_warning(elapsed_seconds: float) -> None:
        if on_log:
            on_log(
                f"{detail_label} is still running after {elapsed_seconds:.0f}s; "
                f"texconv will be stopped after {_TEXCONV_WORKFLOW_TIMEOUT_SECONDS:.0f}s."
            )

    try:
        return_code, stdout, stderr = run_process_with_cancellation(
            cmd,
            stop_event=stop_event,
            timeout_seconds=_TEXCONV_WORKFLOW_TIMEOUT_SECONDS,
            timeout_warning_interval_seconds=_TEXCONV_WORKFLOW_WARNING_INTERVAL_SECONDS,
            on_timeout_warning=emit_timeout_warning,
        )
    except ProcessTimeoutExpired:
        elapsed_seconds = time.monotonic() - started_at
        if on_log:
            on_log(f"{detail_label} timed out after {elapsed_seconds:.1f}s; texconv was terminated.")
        raise
    return return_code, stdout, stderr, time.monotonic() - started_at
