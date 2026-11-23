"""Give published output the Windows permissions of the folder it lands in.

Moving a file or folder on one drive keeps its permissions. CDMW stages output
in ``tempfile.mkdtemp`` folders, which Python (3.12.4 and later) makes private on
Windows: SYSTEM, Administrators and the owner only, with inheritance off. Moved
into place, a mod folder kept that list. When CDMW ran as administrator the
owner was the Administrators group, so DMM could read the mod while the game,
started normally, could not open a single file of it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_logger = logging.getLogger(__name__)

_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_UNPROTECTED_DACL_SECURITY_INFORMATION = 0x20000000
_ACL_REVISION = 2
_SE_DACL_PROTECTED = 0x1000
_SDDL_REVISION_1 = 1


def _windows_path(path: Path) -> str:
    text = str(Path(path).absolute())
    if len(text) >= 248 and not text.startswith("\\\\?\\"):
        text = "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text
    return text


def inherit_parent_permissions(path: Path | str) -> bool:
    """Replace ``path``'s permissions with those its folder hands down.

    Folders pass the change on to everything inside them. Returns False, after
    logging why, when the file system refuses; the output is left as it is.
    Does nothing off Windows.
    """

    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.InitializeAcl.argtypes = (ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD)
    advapi32.InitializeAcl.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    )
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    # An empty list that is not protected leaves only what the parent hands down.
    empty_acl = ctypes.create_string_buffer(16)
    if not advapi32.InitializeAcl(empty_acl, ctypes.sizeof(empty_acl), _ACL_REVISION):
        _logger.warning("Could not prepare permissions for %s (error %s).", path, ctypes.get_last_error())
        return False
    error = advapi32.SetNamedSecurityInfoW(
        _windows_path(Path(path)), _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION | _UNPROTECTED_DACL_SECURITY_INFORMATION,
        None, None, empty_acl, None,
    )
    if error:
        _logger.warning(
            "Could not give %s the permissions of its folder (error %s); other programs may not be able to open it.",
            path, error,
        )
        return False
    return True


def dacl_description(path: Path | str) -> tuple[bool, str]:
    """Whether ``path``'s permission list is protected, and the list as SDDL (Windows only)."""

    if os.name != "nt":
        raise OSError("Permission lists are read on Windows only.")
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p,
    )
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    error = advapi32.GetNamedSecurityInfoW(
        _windows_path(Path(path)), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION,
        None, None, None, None, ctypes.byref(descriptor),
    )
    if error:
        raise OSError(error, f"Could not read the permissions of {path}")
    try:
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error())
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, _SDDL_REVISION_1, _DACL_SECURITY_INFORMATION, ctypes.byref(text), None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sddl = str(text.value or "")
        finally:
            kernel32.LocalFree(text)
    finally:
        kernel32.LocalFree(descriptor)
    return bool(control.value & _SE_DACL_PROTECTED), sddl


__all__ = ["dacl_description", "inherit_parent_permissions"]
