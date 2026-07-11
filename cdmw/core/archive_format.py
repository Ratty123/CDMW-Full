from __future__ import annotations

import fnmatch
import gc
import os
import re
import struct
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple

try:
    import lz4.block as lz4_block
except ImportError:
    lz4_block = None

try:
    import winreg
except ImportError:
    winreg = None

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
except ImportError:
    Cipher = None
    algorithms = None

from cdmw.constants import (
    ARCHIVE_AUDIO_EXTENSIONS,
    ARCHIVE_IMAGE_EXTENSIONS,
    ARCHIVE_MODEL_EXTENSIONS,
    ARCHIVE_TEXT_EXTENSIONS,
    ARCHIVE_VIDEO_EXTENSIONS,
    CRIMSON_DESERT_STEAM_APP_ID,
    DDS_MAGIC,
)
from cdmw.domain.archives.format import (
    ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS as _ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS,
    ARCHIVE_METADATA_XML_EXTENSIONS as _ARCHIVE_METADATA_XML_EXTENSIONS,
    ARCHIVE_XML_LIKE_EXTENSIONS as _ARCHIVE_XML_LIKE_EXTENSIONS,
    is_material_sidecar_extension as _is_material_sidecar_extension,
    normalize_archive_extension_filter,
    try_decode_text_like_archive_data,
)
from cdmw.core.common import raise_if_cancelled, read_u32_le
from cdmw.core.dds_resource_limits import DDS_MAX_PAYLOAD_BYTES
from cdmw.core.upscale_profiles import classify_texture_type
from cdmw.models import ArchiveEntry


def extract_binary_strings(*args, **kwargs):
    from cdmw.core.archive_binary_preview import extract_binary_strings as owner

    return owner(*args, **kwargs)


def reconstruct_partial_dds(*args, **kwargs):
    from cdmw.core.archive_extraction import reconstruct_partial_dds as owner

    return owner(*args, **kwargs)


def discover_pamt_files(package_root: Path) -> List[Path]:
    from cdmw.core.archive_scan_cache import discover_pamt_files as owner

    return owner(package_root)


_ARCHIVE_STRUCTURED_BINARY_PREVIEW_EXTENSIONS: Tuple[str, ...] = (
    ".bnk",
    ".binarygimmick",
    ".hkx",
    ".levelinfo",
    ".meshinfo",
    ".motionblending",
    ".paa",
    ".pae",
    ".paa_metabin",
    ".pabgb",
    ".pabgh",
    ".pabc",
    ".pabv",
    ".papr",
    ".paccd",
    ".pamhc",
    ".pappt",
    ".paem",
    ".pagbg",
    ".pampg",
    ".palevel",
    ".paseq",
    ".paseqc",
    ".paschedule",
    ".paschedulepath",
    ".pastage",
    ".uianiminit",
    ".pamlod",
    ".prefab",
    ".roadsector",
    ".road",
    ".nav",
    ".seqmt",
    ".wem",
)
_ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS = {".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage"}

CHACHA20_HASH_INITVAL = 0x000C5EDE
CHACHA20_IV_XOR = 0x60616263
CHACHA20_XOR_DELTAS = (
    0x00000000,
    0x0A0A0A0A,
    0x0C0C0C0C,
    0x06060606,
    0x0E0E0E0E,
    0x0A0A0A0A,
    0x06060606,
    0x02020202,
)

_PRINTABLE_BINARY_STRING_RE = re.compile(rb"[\x20-\x7E]{4,}")
_TEXT_DDS_REFERENCE_RE = re.compile(r"[A-Za-z0-9_./\\-]{3,255}\.dds", re.IGNORECASE)

def _rot32(value: int, shift: int) -> int:
    value &= 0xFFFFFFFF
    return ((value << shift) | (value >> (32 - shift))) & 0xFFFFFFFF


def _add32(a: int, b: int) -> int:
    return (a + b) & 0xFFFFFFFF


def _sub32(a: int, b: int) -> int:
    return (a - b) & 0xFFFFFFFF


def _finalize_lookup3(a: int, b: int, c: int) -> Tuple[int, int, int]:
    c = _sub32(c ^ b, _rot32(b, 14))
    a = _sub32(a ^ c, _rot32(c, 11))
    b = _sub32(b ^ a, _rot32(a, 25))
    c = _sub32(c ^ b, _rot32(b, 16))
    a = _sub32(a ^ c, _rot32(c, 4))
    b = _sub32(b ^ a, _rot32(a, 14))
    c = _sub32(c ^ b, _rot32(b, 24))
    return a, b, c


def calculate_pa_checksum(value: bytes | str) -> int:
    data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    length = len(data)
    remaining = length
    a = b = c = _add32(length, 0xDEBA1DCD)
    offset = 0

    while remaining > 12:
        a = _add32(a, struct.unpack_from("<I", data, offset)[0])
        b = _add32(b, struct.unpack_from("<I", data, offset + 4)[0])
        c = _add32(c, struct.unpack_from("<I", data, offset + 8)[0])
        a = _sub32(a, c)
        a ^= _rot32(c, 4)
        c = _add32(c, b)
        b = _sub32(b, a)
        b ^= _rot32(a, 6)
        a = _add32(a, c)
        c = _sub32(c, b)
        c ^= _rot32(b, 8)
        b = _add32(b, a)
        a = _sub32(a, c)
        a ^= _rot32(c, 16)
        c = _add32(c, b)
        b = _sub32(b, a)
        b ^= _rot32(a, 19)
        a = _add32(a, c)
        c = _sub32(c, b)
        c ^= _rot32(b, 4)
        b = _add32(b, a)
        offset += 12
        remaining -= 12

    if remaining == 0:
        return c

    tail = data[offset:] + (b"\x00" * (12 - remaining))
    a = _add32(a, struct.unpack_from("<I", tail, 0)[0])
    b = _add32(b, struct.unpack_from("<I", tail, 4)[0])
    c = _add32(c, struct.unpack_from("<I", tail, 8)[0])
    _, _, c = _finalize_lookup3(a, b, c)
    return c


def hashlittle(data: bytes, initval: int = 0) -> int:
    length = len(data)
    remaining = length
    a = b = c = _add32(0xDEADBEEF + length, initval)
    offset = 0

    while remaining > 12:
        a = _add32(a, struct.unpack_from("<I", data, offset)[0])
        b = _add32(b, struct.unpack_from("<I", data, offset + 4)[0])
        c = _add32(c, struct.unpack_from("<I", data, offset + 8)[0])
        a = _sub32(a, c)
        a ^= _rot32(c, 4)
        c = _add32(c, b)
        b = _sub32(b, a)
        b ^= _rot32(a, 6)
        a = _add32(a, c)
        c = _sub32(c, b)
        c ^= _rot32(b, 8)
        b = _add32(b, a)
        a = _sub32(a, c)
        a ^= _rot32(c, 16)
        c = _add32(c, b)
        b = _sub32(b, a)
        b ^= _rot32(a, 19)
        a = _add32(a, c)
        c = _sub32(c, b)
        c ^= _rot32(b, 4)
        b = _add32(b, a)
        offset += 12
        remaining -= 12

    tail = data[offset:] + (b"\x00" * 12)
    if remaining >= 12:
        c = _add32(c, struct.unpack_from("<I", tail, 8)[0])
    elif remaining >= 9:
        c = _add32(c, struct.unpack_from("<I", tail, 8)[0] & (0xFFFFFFFF >> (8 * (12 - remaining))))
    if remaining >= 8:
        b = _add32(b, struct.unpack_from("<I", tail, 4)[0])
    elif remaining >= 5:
        b = _add32(b, struct.unpack_from("<I", tail, 4)[0] & (0xFFFFFFFF >> (8 * (8 - remaining))))
    if remaining >= 4:
        a = _add32(a, struct.unpack_from("<I", tail, 0)[0])
    elif remaining >= 1:
        a = _add32(a, struct.unpack_from("<I", tail, 0)[0] & (0xFFFFFFFF >> (8 * (4 - remaining))))
    elif remaining == 0:
        return c

    c = _sub32(c ^ b, _rot32(b, 14))
    a = _sub32(a ^ c, _rot32(c, 11))
    b = _sub32(b ^ a, _rot32(a, 25))
    c = _sub32(c ^ b, _rot32(b, 16))
    a = _sub32(a ^ c, _rot32(c, 4))
    b = _sub32(b ^ a, _rot32(a, 14))
    c = _sub32(c ^ b, _rot32(b, 24))
    return c


def derive_chacha20_key_iv(filename: str) -> Tuple[bytes, bytes]:
    basename = Path(filename).name.lower().encode("utf-8", errors="replace")
    seed = hashlittle(basename, CHACHA20_HASH_INITVAL)
    nonce = struct.pack("<I", seed) * 4
    key_base = seed ^ CHACHA20_IV_XOR
    key = b"".join(struct.pack("<I", key_base ^ delta) for delta in CHACHA20_XOR_DELTAS)
    return key, nonce


def crypt_chacha20_filename(data: bytes, filename: str) -> bytes:
    if Cipher is None or algorithms is None:
        raise ValueError(
            "ChaCha20 support requires the cryptography package. Install it with: pip install cryptography"
        )
    key, nonce = derive_chacha20_key_iv(filename)
    cipher = Cipher(algorithms.ChaCha20(key, nonce), mode=None)
    return cipher.encryptor().update(data)


def _looks_like_plain_text_payload(data: bytes) -> bool:
    return try_decode_text_like_archive_data(data) is not None


def _looks_like_paloc_payload(data: bytes) -> bool:
    if len(data) < 16:
        return False
    pos = 0
    matches = 0
    scan_limit = min(len(data), 4_000_000)
    while pos + 8 < scan_limit and matches < 8:
        try:
            slen = struct.unpack_from("<I", data, pos)[0]
        except struct.error:
            break
        if slen == 0 or slen > 50_000 or pos + 4 + slen > len(data):
            pos += 1
            continue
        key_bytes = data[pos + 4 : pos + 4 + slen]
        if not (6 <= slen <= 20 and all(0x30 <= value <= 0x39 for value in key_bytes)):
            pos += 1
            continue
        text_pos = pos + 4 + slen
        if text_pos + 4 >= len(data):
            pos += 1
            continue
        text_len = struct.unpack_from("<I", data, text_pos)[0]
        if not (0 < text_len < 50_000 and text_pos + 4 + text_len <= len(data)):
            pos += 1
            continue
        text_bytes = data[text_pos + 4 : text_pos + 4 + text_len]
        try:
            text_bytes.decode("utf-8")
        except UnicodeDecodeError:
            pos += 1
            continue
        matches += 1
        pos = text_pos + 4 + text_len
    return matches >= 2


def _looks_like_structured_binary_payload(extension: str, data: bytes) -> bool:
    head4 = data[:4]
    if extension == ".dds" and data.startswith(DDS_MAGIC):
        return True
    if head4 in {b"PAR ", b"PARC"}:
        return True
    if len(data) >= 16 and data[4:8] == b"TAG0" and data[12:16] == b"SDKV":
        return True
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return True
    return len(extract_binary_strings(data, sample_limit=16_384, max_strings=10)) >= 3


def _looks_like_decrypted_payload(entry: ArchiveEntry, data: bytes) -> bool:
    candidate = data
    if entry.compression_type == 2:
        if lz4_block is None:
            return False
        if entry.extension == ".dds" and (entry.orig_size <= 0 or entry.orig_size > DDS_MAX_PAYLOAD_BYTES):
            return False
        try:
            candidate = lz4_block.decompress(data, uncompressed_size=entry.orig_size)
        except Exception:
            return False
    elif entry.compression_type == 1 and entry.extension == ".dds":
        try:
            candidate = reconstruct_partial_dds(entry, data)
        except Exception:
            return False
    if entry.extension == ".paloc" and _looks_like_paloc_payload(candidate):
        return True
    if _looks_like_plain_text_payload(candidate):
        return True
    if entry.extension in _ARCHIVE_STRUCTURED_BINARY_PREVIEW_EXTENSIONS or entry.extension in ARCHIVE_MODEL_EXTENSIONS:
        return _looks_like_structured_binary_payload(entry.extension, candidate)
    return entry.extension == ".dds" and candidate.startswith(DDS_MAGIC)


def try_decrypt_archive_entry_data(entry: ArchiveEntry, data: bytes) -> Tuple[bytes, Optional[str]]:
    if not entry.encrypted:
        return data, None
    if entry.encryption_type != 3:
        raise ValueError(f"Unsupported archive encryption type {entry.encryption_type} for {entry.path}")
    candidate = crypt_chacha20_filename(data, entry.basename)
    if not _looks_like_decrypted_payload(entry, candidate):
        if entry.extension in _ARCHIVE_XML_LIKE_EXTENSIONS and _looks_like_decrypted_payload(entry, data):
            return data, "ChaCha20FlagMismatch"
        raise ValueError(f"ChaCha20 decryption validation failed for {entry.path}")
    return candidate, "ChaCha20"



def parse_steam_library_paths(libraryfolders_path: Path) -> List[Path]:
    if not libraryfolders_path.exists():
        return []
    try:
        text = libraryfolders_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    paths: List[Path] = []
    for match in re.finditer(r'"path"\s+"([^"]+)"', text, re.IGNORECASE):
        raw_path = match.group(1).replace("\\\\", "\\").strip()
        if raw_path:
            paths.append(Path(raw_path))
    return paths


def parse_steam_appmanifest_installdir(appmanifest_path: Path) -> Optional[str]:
    if not appmanifest_path.exists():
        return None
    try:
        text = appmanifest_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r'"installdir"\s+"([^"]+)"', text, re.IGNORECASE)
    if not match:
        return None
    install_dir = match.group(1).replace("\\\\", "\\").strip()
    return install_dir or None


def _normalize_existing_path(path: Path) -> Optional[Path]:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser()
    if not resolved.exists():
        return None
    return resolved


def discover_steam_roots() -> List[Path]:
    candidates: set[Path] = set()
    env_candidates = [
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        r"C:\Steam",
    ]
    for raw in env_candidates:
        if not raw:
            continue
        raw_path = Path(raw)
        candidates.add(raw_path if raw_path.name.lower() == "steam" else raw_path / "Steam")

    if winreg is not None and os.name == "nt":
        registry_lookups = [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", ("SteamPath", "SteamExe")),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", ("InstallPath", "SteamPath")),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", ("InstallPath", "SteamPath")),
        ]
        for hive, subkey, value_names in registry_lookups:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    for value_name in value_names:
                        try:
                            value, _value_type = winreg.QueryValueEx(key, value_name)
                        except OSError:
                            continue
                        if not value:
                            continue
                        candidate = Path(str(value))
                        if candidate.suffix.lower() == ".exe":
                            candidate = candidate.parent
                        candidates.add(candidate)
            except OSError:
                continue

    resolved: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved_candidate = candidate.expanduser().resolve()
        except OSError:
            resolved_candidate = candidate.expanduser()
        lowered = str(resolved_candidate).lower()
        if lowered in seen or not resolved_candidate.exists():
            continue
        seen.add(lowered)
        resolved.append(resolved_candidate)
    return sorted(resolved)


def discover_windows_drive_roots() -> List[Path]:
    if os.name != "nt":
        return []
    roots: List[Path] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        candidate = Path(f"{letter}:\\")
        if candidate.exists():
            roots.append(candidate)
    return roots


def discover_non_steam_base_paths() -> List[Path]:
    candidates: set[Path] = set()
    env_candidates = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("ProgramW6432"),
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("USERPROFILE"),
    ]
    for raw in env_candidates:
        if not raw:
            continue
        normalized = _normalize_existing_path(Path(raw))
        if normalized is not None:
            candidates.add(normalized)

    for drive_root in discover_windows_drive_roots():
        normalized_root = _normalize_existing_path(drive_root)
        if normalized_root is None:
            continue
        candidates.add(normalized_root)
        try:
            for child in normalized_root.iterdir():
                if child.is_dir():
                    normalized_child = _normalize_existing_path(child)
                    if normalized_child is not None:
                        candidates.add(normalized_child)
        except OSError:
            continue

    return sorted(candidates)


def discover_non_steam_archive_package_roots(
    *,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[Path]:
    explicit_env_vars = (
        "CDMW_PACKAGE_ROOT",
        "CRIMSON_DESERT_PACKAGE_ROOT",
        "cdmw_PACKAGE_ROOT",
    )
    candidates: set[Path] = set()

    for env_var in explicit_env_vars:
        raise_if_cancelled(stop_event, "Archive path auto-detection cancelled.")
        raw_value = os.environ.get(env_var)
        if not raw_value:
            continue
        candidate = Path(raw_value)
        if looks_like_archive_package_root(candidate):
            normalized = _normalize_existing_path(candidate)
            if normalized is not None:
                candidates.add(normalized)
                if on_log:
                    on_log(f"Detected archive package root candidate from {env_var}: {normalized}")
        elif on_log:
            on_log(f"Ignoring {env_var}: path does not look like a valid Crimson Desert package root: {candidate}")

    game_dir_names = ("Crimson Desert", "CrimsonDesert")
    relative_patterns = (
        (),
        ("Games",),
        ("Steam", "steamapps", "common"),
        ("SteamLibrary", "steamapps", "common"),
        ("steamapps", "common"),
        ("Epic Games",),
    )

    for base_path in discover_non_steam_base_paths():
        raise_if_cancelled(stop_event, "Archive path auto-detection cancelled.")
        for relative_parts in relative_patterns:
            for game_dir_name in game_dir_names:
                candidate = base_path.joinpath(*relative_parts, game_dir_name)
                if not looks_like_archive_package_root(candidate):
                    continue
                normalized = _normalize_existing_path(candidate)
                if normalized is not None:
                    candidates.add(normalized)

    store_container_names = (
        "XboxGames",
        "ModifiableWindowsApps",
        "WindowsApps",
    )
    store_candidate_suffixes = (
        (),
        ("Content",),
        ("Game",),
        ("Content", "Game"),
    )

    for drive_root in discover_windows_drive_roots():
        raise_if_cancelled(stop_event, "Archive path auto-detection cancelled.")
        for container_name in store_container_names:
            candidate_container = drive_root / container_name
            if not candidate_container.exists() or not candidate_container.is_dir():
                continue

            direct_name_matches: List[Path] = []
            for game_dir_name in game_dir_names:
                direct_name_matches.extend(
                    [
                        candidate_container / game_dir_name,
                        candidate_container / f"{game_dir_name} Standard Edition",
                        candidate_container / f"{game_dir_name} Deluxe Edition",
                    ]
                )

            seen_container_children: set[str] = set()
            dynamic_child_matches: List[Path] = []
            try:
                for child in candidate_container.iterdir():
                    raise_if_cancelled(stop_event, "Archive path auto-detection cancelled.")
                    if not child.is_dir():
                        continue
                    child_key = child.name.lower()
                    if child_key in seen_container_children:
                        continue
                    seen_container_children.add(child_key)
                    lowered_name = child.name.lower()
                    if "crimson" in lowered_name and "desert" in lowered_name:
                        dynamic_child_matches.append(child)
            except OSError:
                continue

            for game_root in [*direct_name_matches, *dynamic_child_matches]:
                for suffix in store_candidate_suffixes:
                    candidate = game_root.joinpath(*suffix)
                    if not looks_like_archive_package_root(candidate):
                        continue
                    normalized = _normalize_existing_path(candidate)
                    if normalized is not None:
                        candidates.add(normalized)

    return sorted(candidates)


def _looks_like_archive_index_container(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        if next(path.glob("*.pamt"), None) is not None:
            return True
        for child in path.iterdir():
            if not child.is_dir() or not re.fullmatch(r"\d{4}", child.name):
                continue
            if next(child.glob("*.pamt"), None) is not None:
                return True
    except OSError:
        return False
    return False


def looks_like_archive_package_root(path: Path) -> bool:
    if _looks_like_archive_index_container(path):
        return True
    game_files_root = path / "game_files"
    return _looks_like_archive_index_container(game_files_root)


def autodetect_archive_package_roots(
    *,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[Path]:
    if on_log:
        on_log("Checking Steam libraries and common custom install locations...")
    library_roots: set[Path] = set()
    for steam_root in discover_steam_roots():
        raise_if_cancelled(stop_event, "Archive path auto-detection cancelled.")
        library_roots.add(steam_root)
        for library_file in (
            steam_root / "steamapps" / "libraryfolders.vdf",
            steam_root / "config" / "libraryfolders.vdf",
        ):
            for library_root in parse_steam_library_paths(library_file):
                library_roots.add(library_root)

    candidates: set[Path] = set()
    for library_root in sorted(library_roots):
        raise_if_cancelled(stop_event, "Archive path auto-detection cancelled.")
        manifest_path = library_root / "steamapps" / f"appmanifest_{CRIMSON_DESERT_STEAM_APP_ID}.acf"
        manifest_install_dir = parse_steam_appmanifest_installdir(manifest_path)
        possible_dirs: List[Path] = []
        if manifest_install_dir:
            possible_dirs.append(library_root / "steamapps" / "common" / manifest_install_dir)
        possible_dirs.append(library_root / "steamapps" / "common" / "Crimson Desert")

        for candidate in possible_dirs:
            if looks_like_archive_package_root(candidate):
                try:
                    resolved_candidate = candidate.resolve()
                except OSError:
                    resolved_candidate = candidate
                candidates.add(resolved_candidate)

    for candidate in discover_non_steam_archive_package_roots(
        on_log=on_log,
        stop_event=stop_event,
    ):
        candidates.add(candidate)

    if on_log:
        if candidates:
            for candidate in sorted(candidates):
                on_log(f"Detected archive package root candidate: {candidate}")
        else:
            on_log("No valid Crimson Desert archive package roots were auto-detected.")

    return sorted(candidates)


class VfsPathResolver:
    def __init__(self, name_block: bytes, *, max_cache_entries: int = 200_000) -> None:
        self._name_block = name_block
        self._path_cache: Dict[int, str] = {0xFFFFFFFF: ""}
        self._max_cache_entries = max(1, int(max_cache_entries))

    def get_full_path(self, offset: int) -> str:
        if offset == 0xFFFFFFFF or offset >= len(self._name_block):
            return ""
        cached = self._path_cache.get(offset)
        if cached is not None:
            return cached
        parts: List[Tuple[int, str]] = []
        current_offset = offset
        base = ""
        seen_offsets: set[int] = set()
        while current_offset != 0xFFFFFFFF:
            if current_offset in seen_offsets:
                break
            seen_offsets.add(current_offset)
            cached = self._path_cache.get(current_offset)
            if cached is not None:
                base = cached
                break
            pos = current_offset
            if pos + 5 > len(self._name_block):
                break
            parent_offset = struct.unpack_from("<I", self._name_block, pos)[0]
            part_len = self._name_block[pos + 4]
            if pos + 5 + part_len > len(self._name_block):
                break
            part = self._name_block[pos + 5 : pos + 5 + part_len].decode("utf-8", errors="replace")
            parts.append((current_offset, part))
            current_offset = parent_offset
            if len(parts) > 255:
                break
        built = base
        for part_offset, part in reversed(parts):
            built = f"{built}{part}"
            if len(self._path_cache) < self._max_cache_entries:
                self._path_cache[part_offset] = built
        return self._path_cache.get(offset, built)


def parse_archive_pamt(pamt_path: Path, paz_dir: Optional[Path] = None) -> List[ArchiveEntry]:
    gc_was_enabled = gc.isenabled()
    if gc_was_enabled:
        gc.disable()
    try:
        return _parse_archive_pamt(pamt_path, paz_dir=paz_dir)
    finally:
        if gc_was_enabled:
            gc.enable()


def _parse_archive_pamt(pamt_path: Path, paz_dir: Optional[Path] = None) -> List[ArchiveEntry]:
    data = pamt_path.read_bytes()
    resolved_paz_dir = paz_dir if paz_dir is not None else pamt_path.parent
    size = len(data)
    if size < 12:
        raise ValueError(f"{pamt_path} is too small to be a valid .pamt file.")

    off = 0
    _header_crc, paz_count, _unknown = struct.unpack_from("<III", data, off)
    off += 12

    paz_table_size = paz_count * 12
    if off + paz_table_size > size:
        raise ValueError(f"{pamt_path.name} paz table is truncated.")
    off += paz_table_size

    if off + 4 > size:
        raise ValueError(f"{pamt_path.name} directory block length is truncated.")
    dir_block_size = read_u32_le(data, off)
    off += 4
    directory_data = data[off : off + dir_block_size]
    if len(directory_data) != dir_block_size:
        raise ValueError(f"{pamt_path.name} directory block is truncated.")
    off += dir_block_size

    if off + 4 > size:
        raise ValueError(f"{pamt_path.name} file-name block length is truncated.")
    file_name_block_size = read_u32_le(data, off)
    off += 4
    file_names = data[off : off + file_name_block_size]
    if len(file_names) != file_name_block_size:
        raise ValueError(f"{pamt_path.name} file-name block is truncated.")
    off += file_name_block_size

    if off + 4 > size:
        raise ValueError(f"{pamt_path.name} folder table length is truncated.")
    folder_count = read_u32_le(data, off)
    off += 4
    folder_table_size = folder_count * 16
    if off + folder_table_size > size:
        raise ValueError(f"{pamt_path.name} folder table is truncated.")
    folder_table = memoryview(data)[off : off + folder_table_size]
    off += folder_table_size

    if off + 4 > size:
        raise ValueError(f"{pamt_path.name} file table length is truncated.")
    file_count = read_u32_le(data, off)
    off += 4
    file_table_size = file_count * struct.calcsize("<IIIIHH")
    if off + file_table_size > size:
        raise ValueError(f"{pamt_path.name} file table is truncated.")
    file_table = memoryview(data)[off : off + file_table_size]

    resolver = VfsPathResolver(file_names)
    dir_resolver = VfsPathResolver(directory_data, max_cache_entries=50_000)
    folder_ranges = sorted(
        (
            file_start_index,
            file_start_index + folder_file_count,
            dir_resolver.get_full_path(name_offset).replace("\\", "/").strip("/"),
        )
        for _folder_hash, name_offset, file_start_index, folder_file_count in struct.iter_unpack("<IIII", folder_table)
        if folder_file_count > 0
    )
    paz_files = [resolved_paz_dir / f"{index}.paz" for index in range(paz_count)]

    entries: List[ArchiveEntry] = []
    folder_cursor = 0
    for entry_index, (name_offset, paz_offset, comp_size, orig_size, paz_index, flags) in enumerate(struct.iter_unpack("<IIIIHH", file_table)):
        relative_path = resolver.get_full_path(name_offset).replace("\\", "/").strip("/")
        guessed_dir = ""
        while folder_cursor < len(folder_ranges) and entry_index >= folder_ranges[folder_cursor][1]:
            folder_cursor += 1
        if folder_cursor < len(folder_ranges):
            start, end, candidate_dir = folder_ranges[folder_cursor]
            if start <= entry_index < end:
                guessed_dir = candidate_dir
        full_path = f"{guessed_dir}/{relative_path}".strip("/") if guessed_dir else relative_path
        if paz_index >= len(paz_files):
            raise ValueError(f"Invalid PAZ index {paz_index} for {pamt_path}")
        entries.append(
            ArchiveEntry(
                path=full_path,
                pamt_path=pamt_path,
                paz_file=paz_files[paz_index],
                offset=paz_offset,
                comp_size=comp_size,
                orig_size=orig_size,
                flags=flags,
                paz_index=paz_index,
            )
        )

    return entries


def scan_archive_entries(
    package_root: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveEntry]:
    pamt_files = discover_pamt_files(package_root)
    if not pamt_files:
        raise ValueError(f"No .pamt files were found under {package_root}.")

    all_entries: List[ArchiveEntry] = []
    total_pmts = len(pamt_files)
    if on_log:
        on_log(f"Found {total_pmts:,} archive index file(s).")
    if on_progress:
        on_progress(0, total_pmts, f"0 / {total_pmts} archive indexes | 0 entries found")
    for index, pamt_path in enumerate(pamt_files, start=1):
        raise_if_cancelled(stop_event)
        try:
            relative_label = pamt_path.relative_to(package_root).as_posix()
        except ValueError:
            relative_label = pamt_path.name

        if on_log:
            on_log(f"[{index}/{total_pmts}] Parsing {relative_label}...")

        parse_started = time.monotonic()
        if on_breadcrumb is not None:
            on_breadcrumb(
                {
                    "phase": "parse_archive_pamt",
                    "status": "starting",
                    "package_root": str(package_root),
                    "pamt_path": str(pamt_path),
                    "relative_label": relative_label,
                    "index": index,
                    "total": total_pmts,
                    "entries_found_before": len(all_entries),
                    "timestamp": time.time(),
                }
            )

        if on_progress:
            on_progress(
                index - 1,
                total_pmts,
                f"Parsing {index} / {total_pmts}: {relative_label} | {len(all_entries):,} entries found",
            )

        try:
            entries = parse_archive_pamt(pamt_path)
        except FileNotFoundError as exc:
            if on_log:
                on_log(f"[{index}/{total_pmts}] Skipped missing archive index {relative_label}: {exc}")
            if on_breadcrumb is not None:
                on_breadcrumb(
                    {
                        "phase": "parse_archive_pamt",
                        "status": "skipped_missing",
                        "package_root": str(package_root),
                        "pamt_path": str(pamt_path),
                        "relative_label": relative_label,
                        "index": index,
                        "total": total_pmts,
                        "entries_found_before": len(all_entries),
                        "elapsed_seconds": round(time.monotonic() - parse_started, 3),
                        "error": str(exc),
                        "timestamp": time.time(),
                    }
                )
            if on_progress:
                on_progress(
                    index,
                    total_pmts,
                    f"{index} / {total_pmts} archive indexes | {len(all_entries):,} entries found | skipped missing: {relative_label}",
                )
            continue
        except Exception as exc:
            if on_breadcrumb is not None:
                on_breadcrumb(
                    {
                        "phase": "parse_archive_pamt",
                        "status": "failed",
                        "package_root": str(package_root),
                        "pamt_path": str(pamt_path),
                        "relative_label": relative_label,
                        "index": index,
                        "total": total_pmts,
                        "entries_found_before": len(all_entries),
                        "elapsed_seconds": round(time.monotonic() - parse_started, 3),
                        "error": str(exc),
                        "timestamp": time.time(),
                    }
                )
            raise

        all_entries.extend(entries)
        parse_elapsed = time.monotonic() - parse_started
        if on_log:
            on_log(f"[{index}/{total_pmts}] Parsed {relative_label} -> {len(entries):,} entries in {parse_elapsed:.1f}s")
        if on_breadcrumb is not None:
            on_breadcrumb(
                {
                    "phase": "parse_archive_pamt",
                    "status": "completed",
                    "package_root": str(package_root),
                    "pamt_path": str(pamt_path),
                    "relative_label": relative_label,
                    "index": index,
                    "total": total_pmts,
                    "parsed_entries": len(entries),
                    "entries_found_total": len(all_entries),
                    "elapsed_seconds": round(parse_elapsed, 3),
                    "timestamp": time.time(),
                }
            )
        if on_progress:
            on_progress(
                index,
                total_pmts,
                f"{index} / {total_pmts} archive indexes | {len(all_entries):,} entries found | last: {relative_label}",
            )

    return all_entries


def archive_entry_matches_filter(entry: ArchiveEntry, filter_text: str, extension_filter: str) -> bool:
    normalized_extension = normalize_archive_extension_filter(extension_filter)
    if normalized_extension and normalized_extension not in {"*", "all", ".*"}:
        if entry.extension != normalized_extension:
            return False

    text = filter_text.strip().lower()
    if not text:
        return True

    path_lower = entry.path.lower()
    basename_lower = entry.basename.lower()
    if any(char in text for char in "*?[]"):
        return fnmatch.fnmatch(path_lower, text) or fnmatch.fnmatch(basename_lower, text)
    return text in path_lower or text in basename_lower


def archive_entry_role(entry: ArchiveEntry) -> str:
    path_lower = entry.path.lower()
    extension = entry.extension

    if extension in {".hkx", ".hkt"}:
        if any(token in path_lower for token in ("meshphysics", "havokphysics", "ragdoll", "physics")):
            return "physics"
        return "animation"
    if extension in ARCHIVE_MODEL_EXTENSIONS:
        return "model"
    if extension in {".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".papr", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage"}:
        return "animation"
    if extension in {".meshinfo", ".prefab", ".pamhc", ".pappt", ".paccd", ".pabgb", ".pabgh", ".pabc", ".pabv", ".levelinfo", ".palevel", ".roadsector", ".road", ".nav", ".seqmt", ".uianiminit"}:
        return "metadata"
    if extension == ".pathc":
        return "metadata"
    if extension in ARCHIVE_VIDEO_EXTENSIONS:
        return "video"
    if extension in ARCHIVE_AUDIO_EXTENSIONS:
        return "audio"
    if "/ui/" in path_lower or entry.basename.lower().startswith("ui_"):
        return "ui"
    if "impostor" in path_lower:
        return "impostor"
    if extension in ARCHIVE_IMAGE_EXTENSIONS or "/texture/" in path_lower:
        texture_type = classify_texture_type(entry.path)
        if texture_type == "normal":
            return "normal"
        if texture_type in {"mask", "roughness", "height", "vector", "emissive"}:
            return "material"
        return "image"
    if extension in ARCHIVE_TEXT_EXTENSIONS:
        return "text"
    return "other"
