"""Generated-icon output coordination for the static replacement dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtGui import QPixmap


class AlignmentGeneratedIconOutputController:
    """Dispatch generated-icon encoding and apply only the latest UI result."""

    def __init__(
        self,
        context: dict[str, object],
        *,
        capture: Callable[[Callable[[Optional[QPixmap]], None]], None],
        refresh_status: Callable[[], None],
    ) -> None:
        self.context = context
        self.capture = capture
        self.refresh_status = refresh_status
        self.generation = 0

    def _apply(
        self,
        output_path: Path,
        *,
        save_to_library: bool,
        target_model_path: str,
        source_model_path: str,
        target_icon_entry: object,
    ) -> None:
        context = self.context
        shell = context["self"]
        result = context["_custom_item_icon_maybe_register_generated_icon_helper"](
            save_to_library=save_to_library,
            item_icons_tab=getattr(shell, "item_icons_tab", None),
            output_path=output_path,
            target_model_path=target_model_path,
            source_model_path=source_model_path,
            target_icon_entry=target_icon_entry,
        )
        output_path = result.output_path
        if result.error_status:
            shell.set_status_message(result.error_status, error=True)
        context["custom_icon_source_edit"].setText(str(output_path))
        apply_state = context["_custom_item_icon_generated_apply_state_helper"](
            has_target_entries=bool(context["custom_icon_target_entries"]),
            checkbox_enabled=context["custom_icon_checkbox"].isEnabled(),
            current_target_entry=context["custom_icon_target_combo"].currentData(),
        )
        if apply_state["has_target"]:
            context["custom_icon_checkbox"].setChecked(True)
            if apply_state["select_first_target"]:
                context["custom_icon_target_combo"].setCurrentIndex(0)
        self.refresh_status()
        context["custom_icon_status"].setText(
            context["_custom_item_icon_generated_status_helper"](
                output_name=output_path.name,
                saved_to_library=result.saved_to_library,
                has_target=bool(apply_state["has_target"]),
            )
        )
        shell.set_status_message(context["_custom_item_icon_generation_status_message_helper"](output_path))

    def _show_error(self, generation: int, output_path: Path, message: object = "") -> None:
        context = self.context
        if generation != self.generation or not context["dialog"].isVisible():
            return
        context["generate_alignment_icon_button"].setEnabled(True)
        context["QMessageBox"].warning(
            context["dialog"],
            context["custom_icon_control_text"]["generate_preview_warning_title"],
            str(message or context["_custom_item_icon_write_failure_message_helper"](output_path)),
        )

    def _finish_capture(self, pixmap: Optional[QPixmap], generation: int) -> None:
        context = self.context
        dialog = context["dialog"]
        if generation != self.generation or not dialog.isVisible():
            return
        if pixmap is None or pixmap.isNull():
            context["generate_alignment_icon_button"].setEnabled(True)
            context["QMessageBox"].warning(
                dialog,
                context["custom_icon_control_text"]["generate_preview_warning_title"],
                context["custom_icon_control_text"]["generate_preview_not_ready"],
            )
            return
        shell = context["self"]
        entry = context["entry"]
        obj_path = context["obj_path"]
        save_to_library = context["save_generated_icon_to_library_checkbox"].isChecked()
        target_model_path = str(getattr(entry, "path", "") or entry.basename)
        source_model_path = str(obj_path)
        target_icon_entry = context["custom_icon_target_combo"].currentData()
        output_path = context["_custom_item_icon_alignment_generated_path_helper"](
            save_to_library=save_to_library,
            item_icons_tab=getattr(shell, "item_icons_tab", None),
            model_library_tab=getattr(shell, "model_library_tab", None),
            target_model_path=target_model_path,
            target_fallback_path=str(getattr(entry, "path", "") or obj_path.stem),
            source_model_path=source_model_path,
            fallback_dir=Path.cwd(),
        )
        formatter = getattr(getattr(shell, "model_library_tab", None), "_model_preview_icon_image", None)
        captured_image = pixmap.toImage().copy()

        def task(_log: object, stop_event: object) -> Path:
            image = context["_custom_item_icon_preview_image_helper"](
                captured_image,
                formatter=formatter,
                size=512,
            )
            return context["_write_custom_item_icon_image_atomic_helper"](
                image,
                output_path,
                stop_event=stop_event,
            )

        def complete(result: object) -> None:
            if generation != self.generation or not dialog.isVisible():
                return
            context["generate_alignment_icon_button"].setEnabled(True)
            if not isinstance(result, Path):
                self._show_error(generation, output_path)
                return
            self._apply(
                result,
                save_to_library=save_to_library,
                target_model_path=target_model_path,
                source_model_path=source_model_path,
                target_icon_entry=target_icon_entry,
            )

        try:
            shell._run_utility_task_when_idle(
                status_message=f"Saving generated item icon {output_path.name}...",
                task=task,
                on_complete=complete,
                on_error=lambda message: self._show_error(generation, output_path, message),
                task_accepts_cancel=True,
            )
        except Exception as exc:
            self._show_error(generation, output_path, exc)

    def generate(self) -> None:
        self.generation += 1
        generation = self.generation
        self.context["generate_alignment_icon_button"].setEnabled(False)
        try:
            self.capture(lambda pixmap: self._finish_capture(pixmap, generation))
        except Exception:
            self._finish_capture(None, generation)


__all__ = ["AlignmentGeneratedIconOutputController"]
