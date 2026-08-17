"""A brand-new item icon: a DDS at a path the archive does not ship yet.

The icon generator (`cdmw.core.item_icon.build_item_icon_payload`) already takes the
target path and the reference DDS separately, so it can produce an icon for a path
that does not exist. What a new item adds is the naming: the ItemInfo row points at
`hashlittle("ItemIcon_Prefab_<Stem>", 0xC5EDE)`, StringInfo maps that hash back to the
text, and the file lives at `ui/texture/icon/itemicon_prefab_<stem>.dds` (the text,
lower-cased). This module ties those three together and hands back the archive
addition and the StringInfo string a caller has to install alongside the row.

The reference icon is a shipped one of the same kind (256x256 BC3_UNORM with a full DDS
header for weapon icons), so the new file matches the game's expectations for size,
format and mip count. Whether the texture header cache (`meta/0.pathc`) needs an entry
for a new icon path is untested; the shipped icons carry their own DDS header, which
is what this writes.
"""

from __future__ import annotations

import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from cdmw.core.item_icon import build_item_icon_payload
from cdmw.core.item_model_family import ICON_FOLDER, ICON_STRING_PREFIX
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.models import ArchiveEntry
from cdmw.domain.archives.mutation import ArchiveAddRequest
from cdmw.domain.library.item_icons import (
    ITEM_ICON_DEFAULT_BACKGROUND_MODE,
    ItemIconBuildResult,
    ItemIconOverrideSpec,
)

_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{0,95}$")


class ItemIconAdditionError(ValueError):
    """Raised when the icon name or its inputs cannot make a new icon."""


@dataclass(frozen=True, slots=True)
class NewItemIcon:
    """Everything a new icon installs: the file, and the string the row points at."""

    icon_string: str
    icon_hash: int
    target_path: str
    payload_data: bytes
    add_request: ArchiveAddRequest
    build: ItemIconBuildResult


def icon_string_for_stem(stem: str) -> str:
    """`cd_phm_01_sword_9109` -> `ItemIcon_Prefab_cd_phm_01_sword_9109`."""

    text = str(stem or "").strip()
    if not _STEM_RE.match(text):
        raise ItemIconAdditionError(f"{stem!r} is not a usable icon stem (letters, digits and underscores)")
    return ICON_STRING_PREFIX + text


def icon_target_path(icon_string: str) -> str:
    """The archive path an `ItemIcon_Prefab_*` string names: its lower-case spelling under the icon folder."""

    text = str(icon_string or "").strip()
    if not text.startswith(ICON_STRING_PREFIX) or not _STEM_RE.match(text[len(ICON_STRING_PREFIX):]):
        raise ItemIconAdditionError(f"{icon_string!r} is not an ItemIcon_Prefab_<Stem> string")
    return f"{ICON_FOLDER}/{text.lower()}.dds"


def build_new_item_icon(
    *,
    source_path: Path,
    reference_entry: ArchiveEntry,
    reference_payload: bytes,
    icon_string: str,
    background_mode: str = ITEM_ICON_DEFAULT_BACKGROUND_MODE,
    fit_mode: str = "fit_pad",
    existing_paths: Optional[Callable[[str], bool]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> NewItemIcon:
    """Generate the icon for `icon_string` from `source_path`, shaped like the reference.

    `reference_entry` is the shipped icon whose format, size and storage flags the new
    file copies (Wolf's Fang's own icon, for a sword); `reference_payload` is its DDS
    bytes. `existing_paths`, when given, refuses a target path the archive already has,
    since a new item must not overwrite a shipped icon.
    """

    target_path = icon_target_path(icon_string)
    if existing_paths is not None and existing_paths(target_path):
        raise ItemIconAdditionError(f"{target_path} already exists in the archive; a new item needs a new icon path")
    if not reference_payload:
        raise ItemIconAdditionError("the reference icon payload is empty")
    with tempfile.TemporaryDirectory(prefix="cdmw_new_item_icon_") as temp_text:
        template = Path(temp_text) / (Path(str(reference_entry.path)).name or "reference.dds")
        template.write_bytes(bytes(reference_payload))
        spec = ItemIconOverrideSpec(
            source_path=Path(source_path),
            target_entry=reference_entry,
            target_path=target_path,
            source_mode="file",
            fit_mode=fit_mode,
            background_mode=background_mode,
        )
        result = build_item_icon_payload(spec, target_template_path=template, on_log=on_log, stop_event=stop_event)
    return NewItemIcon(
        icon_string=str(icon_string).strip(),
        icon_hash=stringinfo_key(str(icon_string).strip()),
        target_path=target_path,
        payload_data=result.payload_data,
        add_request=ArchiveAddRequest.from_template(reference_entry, target_path, result.payload_data),
        build=result,
    )


__all__ = [
    "ItemIconAdditionError",
    "NewItemIcon",
    "build_new_item_icon",
    "icon_string_for_stem",
    "icon_target_path",
]
