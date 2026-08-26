"""Best-effort background prewarm task for the resident .NET preview host."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from cdmw.services.mesh_dotnet_preview_package import build_dotnet_preview_prewarm_package
from cdmw.services.mesh_dotnet_runtime_status import mesh_dotnet_provenance_file_sha256


class _DotNetPreviewPrewarmSignals(QObject):
    completed = Signal(object)


class DotNetPreviewPrewarmTask(QRunnable):
    def __init__(self, cache_root: Path, executable: Path | None = None) -> None:
        super().__init__()
        self.cache_root = Path(cache_root)
        self.executable = Path(executable) if executable else None
        self.signals = _DotNetPreviewPrewarmSignals()

    def _seed_provenance_hashes(self) -> None:
        executable = self.executable
        if executable is None or not executable.is_file():
            return
        try:
            mesh_dotnet_provenance_file_sha256(executable)
            shader_path = executable.parent / "D3D11MaterialShaders.hlsl"
            if shader_path.is_file():
                mesh_dotnet_provenance_file_sha256(shader_path)
        except OSError:
            pass

    def run(self) -> None:
        """Contain all errors because the global pool may outlive the owning host."""

        started_at = time.perf_counter()
        try:
            self._seed_provenance_hashes()
            package = build_dotnet_preview_prewarm_package(self.cache_root)
            result = {
                "package": package,
                "package_ms": (time.perf_counter() - started_at) * 1000.0,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001 - prewarm is best-effort
            result = {
                "package": None,
                "package_ms": (time.perf_counter() - started_at) * 1000.0,
                "error": str(exc),
            }
        try:
            self.signals.completed.emit(result)
        except RuntimeError:
            return


__all__ = ["DotNetPreviewPrewarmTask"]
