"""Public shell mixin for the Retrofit/Repackage tool."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QDialog, QWidget

from cdmw.ui.tools.mod_package_retrofit_widget import build_mod_package_retrofit_tool


class ArchiveModPackageRetrofitDialogMixin:
    def _show_mod_package_retrofit_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Retrofit/Repackage Mods")
        dialog.setModal(True)
        dialog.resize(1120, 760)
        self._build_mod_package_retrofit_tool(dialog, run_initial_scan=True, on_close=dialog.reject)
        dialog.exec()

    def _build_mod_package_retrofit_tool(
        self,
        parent: QWidget,
        *,
        run_initial_scan: bool,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        build_mod_package_retrofit_tool(
            self,
            parent,
            run_initial_scan=run_initial_scan,
            on_close=on_close,
        )


__all__ = ["ArchiveModPackageRetrofitDialogMixin"]
