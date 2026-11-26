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
import stat
from pathlib import Path

_logger = logging.getLogger(__name__)

_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_UNPROTECTED_DACL_SECURITY_INFORMATION = 0x20000000
_ACL_REVISION = 2
_SE_DACL_PROTECTED = 0x1000
_SDDL_REVISION_1 = 1
_ERROR_ACCESS_DENIED = 5
_FILE_READ_DATA = 0x0001
_FILE_WRITE_DATA = 0x0002
_FILE_LIST_DIRECTORY = 0x0001
_FILE_ADD_FILE = 0x0002
_DELETE = 0x00010000
_FILE_SHARE_ALL = 0x00000007
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_FILE_ALL_ACCESS = 0x001F01FF
_OBJECT_INHERIT_ACE = 0x1
_CONTAINER_INHERIT_ACE = 0x2


def _windows_path(path: Path) -> str:
    text = str(Path(path).absolute())
    if len(text) >= 248 and not text.startswith("\\\\?\\"):
        text = "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text
    return text


def _current_process_can_use(path: Path, *, is_dir: bool, is_readonly: bool) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    if is_dir:
        access = _FILE_LIST_DIRECTORY | _FILE_ADD_FILE | (0 if is_readonly else _DELETE)
        flags = _FILE_FLAG_BACKUP_SEMANTICS
    else:
        access = _FILE_READ_DATA | (0 if is_readonly else _FILE_WRITE_DATA)
        flags = _FILE_ATTRIBUTE_NORMAL

    handle = kernel32.CreateFileW(
        _windows_path(path),
        access,
        _FILE_SHARE_ALL,
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    if handle != wintypes.HANDLE(-1).value:
        kernel32.CloseHandle(handle)
        return True
    return ctypes.get_last_error() != _ERROR_ACCESS_DENIED


def _retain_current_user_access(path: Path, *, is_dir: bool) -> int:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = (ctypes.c_void_p,)
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.InitializeAcl.argtypes = (ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD)
    advapi32.InitializeAcl.restype = wintypes.BOOL
    advapi32.AddAccessAllowedAceEx.argtypes = (
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    )
    advapi32.AddAccessAllowedAceEx.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    )
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
        return int(ctypes.get_last_error() or _ERROR_ACCESS_DENIED)
    try:
        needed = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(needed))
        if needed.value <= 0:
            return int(ctypes.get_last_error() or _ERROR_ACCESS_DENIED)
        token_buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token, _TOKEN_USER, token_buffer, needed.value, ctypes.byref(needed),
        ):
            return int(ctypes.get_last_error() or _ERROR_ACCESS_DENIED)
        sid = ctypes.c_void_p.from_buffer(token_buffer).value
        sid_length = advapi32.GetLengthSid(sid)
        acl = ctypes.create_string_buffer(64 + sid_length)
        if not advapi32.InitializeAcl(acl, ctypes.sizeof(acl), _ACL_REVISION):
            return int(ctypes.get_last_error() or _ERROR_ACCESS_DENIED)
        ace_flags = (_OBJECT_INHERIT_ACE | _CONTAINER_INHERIT_ACE) if is_dir else 0
        if not advapi32.AddAccessAllowedAceEx(acl, _ACL_REVISION, ace_flags, _FILE_ALL_ACCESS, sid):
            return int(ctypes.get_last_error() or _ERROR_ACCESS_DENIED)
        return int(
            advapi32.SetNamedSecurityInfoW(
                _windows_path(path),
                _SE_FILE_OBJECT,
                _DACL_SECURITY_INFORMATION | _UNPROTECTED_DACL_SECURITY_INFORMATION,
                None,
                None,
                acl,
                None,
            )
        )
    finally:
        kernel32.CloseHandle(token)


def inherit_parent_permissions(path: Path | str) -> bool:
    """Replace ``path``'s permissions with those its folder hands down.

    Folders pass the change on to everything inside them. If the parent folder
    does not hand down access for the current user, an explicit user ACE is
    retained alongside inheritance so CDMW does not lock itself out. Returns
    False, after logging why, when the file system refuses; the output is left
    as it is. Does nothing off Windows.
    """

    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    target = Path(path)
    try:
        st = os.stat(_windows_path(target))
    except OSError:
        st = None
    is_dir = bool(st is not None and stat.S_ISDIR(st.st_mode))
    is_readonly = bool(
        st is not None
        and int(getattr(st, "st_file_attributes", 0) or 0) & getattr(stat, "FILE_ATTRIBUTE_READONLY", 0x1)
    )

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
        _windows_path(target), _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION | _UNPROTECTED_DACL_SECURITY_INFORMATION,
        None, None, empty_acl, None,
    )
    if error:
        _logger.warning(
            "Could not give %s the permissions of its folder (error %s); other programs may not be able to open it.",
            path, error,
        )
        return False
    if st is not None and not _current_process_can_use(target, is_dir=is_dir, is_readonly=is_readonly):
        recovery_error = _retain_current_user_access(target, is_dir=is_dir)
        if recovery_error:
            _logger.warning(
                "Could not retain user permissions on %s after clearing inherited protection (error %s).",
                path, recovery_error,
            )
            return False
        _logger.warning(
            "Parent folder permissions for %s did not grant current-user access; retained explicit user access alongside inheritance.",
            path,
        )
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
