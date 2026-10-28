"""Export a Body & Face Finder selection as FBX with each component's own face shape."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.domain.character_finder import CharacterPreviewInputs, authored_component_descriptor
from cdmw.models import RunCancelled


@dataclass(frozen=True, slots=True)
class CharacterExportModelResult:
    path: str
    exported: bool
    output_paths: tuple[str, ...]
    notes: tuple[str, ...]
    component: str = ""


@dataclass(frozen=True, slots=True)
class CharacterExportResult:
    output_dir: str
    models: tuple[CharacterExportModelResult, ...]

    @property
    def exported_count(self) -> int:
        return sum(1 for model in self.models if model.exported)


_SUMMARY_PREFIXES = ("Appearance prefab:", "Applied ", "Recovered ", "Skeleton:")


class CharacterFinderExportWorker(QObject):
    """Writes one FBX per model of a prepared selection into ``output_dir``.

    Each model takes the prefab descriptor of the component that owns it, so a
    head that reuses another head's mesh keeps its own skeleton variation. A
    model whose skeleton cannot be resolved is skipped with its reason rather
    than written as a mesh-only FBX.
    """

    completed = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, int, int)
    finished = Signal()

    def __init__(self, token: int, inputs: CharacterPreviewInputs, output_dir: Path) -> None:
        super().__init__()
        self.token = token
        self.inputs = inputs
        self.output_dir = Path(output_dir)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.token, self._export())
        except RunCancelled:
            self.failed.emit(self.token, "Character export was cancelled.")
        except Exception as error:
            self.failed.emit(self.token, str(error) or type(error).__name__)
        finally:
            self.finished.emit()

    def _export(self) -> CharacterExportResult:
        from cdmw.core.archive import build_archive_entry_basename_index, build_archive_entry_path_index
        from cdmw.core.archive_mesh_export import export_archive_mesh

        detail = self.inputs.detail
        paths = build_archive_entry_path_index(self.inputs.entries)
        basenames = build_archive_entry_basename_index(self.inputs.entries)
        models = [(model.entry_id, self.inputs.entries_by_id[model.entry_id]) for model in detail.models
                  if model.entry_id in self.inputs.entries_by_id]
        if not models:
            raise ValueError("The selection has no prepared model to export.")
        results = []
        for index, (entry_id, entry) in enumerate(models):
            if self._stop.is_set():
                raise RunCancelled("Character export cancelled.")
            self.progress.emit(self.token, index, len(models))
            component = next((c for c in detail.components if entry_id in c.model_entry_ids), None)
            owner = component.name if component is not None else ""
            try:
                result = export_archive_mesh(
                    entry, self.output_dir, "fbx",
                    archive_entries_by_normalized_path=paths, archive_entries_by_basename=basenames,
                    authored_descriptor=authored_component_descriptor(component, self.inputs.entries_by_id),
                    stop_event=self._stop,
                )
            except RunCancelled:
                raise
            except Exception as error:
                results.append(CharacterExportModelResult(
                    entry.path, False, (), (str(error) or type(error).__name__,), owner))
                continue
            if result.requires_confirmation:
                reason = result.confirmation_message.split("\n\n")[1] if "\n\n" in result.confirmation_message else ""
                results.append(CharacterExportModelResult(
                    entry.path, False, (), (f"Skipped: no skeleton could be attached. {reason}".strip(),), owner))
                continue
            notes = tuple(line for line in result.summary_lines if line.startswith(_SUMMARY_PREFIXES))
            results.append(CharacterExportModelResult(
                entry.path, True, tuple(str(path) for path in result.output_paths), notes, owner))
        self.progress.emit(self.token, len(models), len(models))
        return CharacterExportResult(str(self.output_dir), tuple(results))
