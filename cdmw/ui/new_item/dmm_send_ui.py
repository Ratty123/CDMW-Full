"""Finding DMM's mods folder for Send to DMM, shared by Create New Item and Mod Management."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from cdmw.services.dmm_send import DMM_FOLDER_SETTING, dmm_mods_folder, find_dmm
from cdmw.services.settings_service import resolve_settings_file_path
from cdmw.ui.widgets import request_settings_sync


def choose_dmm_mods_folder(parent, settings: QSettings | None = None):
    """DMM's mods folder from the remembered DMM folder, a usual place, or the user's pick.

    The chosen DMM folder is remembered, so the user points CDMW at DMM only once.
    Returns None when the user cancels or the folder is not DMM's.
    """
    settings = settings if settings is not None else QSettings(str(resolve_settings_file_path()), QSettings.Format.IniFormat)
    install = find_dmm(str(settings.value(DMM_FOLDER_SETTING, "") or ""))
    if install is None:
        chosen = QFileDialog.getExistingDirectory(parent, "Choose DMM's folder (the one that contains DMM.exe)")
        if not chosen:
            return None
        install = Path(chosen)
    try:
        mods = dmm_mods_folder(install)
    except ValueError as exc:
        QMessageBox.warning(parent, "Send to DMM", str(exc))
        return None
    settings.setValue(DMM_FOLDER_SETTING, str(install))
    request_settings_sync(settings)
    return mods
