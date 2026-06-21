"""Archive browser attachment visual socket payload helpers."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Optional, Sequence

from cdmw.core.archive import read_archive_entry_data
from cdmw.core.xml_text import decode_xml_text_payload, encode_xml_text_like_source
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.attachment_visual_preview import ArchiveAttachmentVisualPreviewMixin


class ArchiveAttachmentVisualPayloadMixin(ArchiveAttachmentVisualPreviewMixin):
    def _attachment_visual_edited_socket_payload(
        self,
        socket_entry: ArchiveEntry,
        socket_name: str,
        *,
        visual_offset: Sequence[float],
        visual_rotation_degrees: Sequence[float],
        translation_scale: float = 0.10,
    ) -> Optional[bytes]:
        try:
            data, _decompressed, _note = read_archive_entry_data(socket_entry)
            decoded_socket_xml = decode_xml_text_payload(data)
            original_text = decoded_socket_xml.text
            root = ET.fromstring(original_text)
        except Exception:
            return None
        target_socket = None
        for element in root.iter():
            if str(element.tag).rsplit("}", 1)[-1] != "Socket":
                continue
            if str(element.attrib.get("Name", "") or "").strip().casefold() == str(socket_name or "").strip().casefold():
                target_socket = element
                break
        if target_socket is None:
            return None
        current_translation = self._parse_attachment_transform_values(str(target_socket.attrib.get("Translation", "") or ""), 3) or (0.0, 0.0, 0.0)
        delta = self._attachment_visual_finite_vector3(visual_offset)
        try:
            safe_scale = abs(float(translation_scale))
        except (TypeError, ValueError, OverflowError):
            safe_scale = 0.10
        if not math.isfinite(safe_scale) or safe_scale <= 1e-8:
            safe_scale = 0.10
        new_translation = (
            float(current_translation[0]) - float(delta[0]) / safe_scale,
            float(current_translation[1]) - float(delta[1]) / safe_scale,
            float(current_translation[2]) - float(delta[2]) / safe_scale,
        )
        target_socket.set("Translation", self._format_attachment_transform_values(new_translation))
        current_rotation = self._parse_attachment_transform_values(str(target_socket.attrib.get("Rotation", "") or ""), 4) or (0.0, 0.0, 0.0, 1.0)
        rotation_values = tuple(visual_rotation_degrees or (0.0, 0.0, 0.0))
        while len(rotation_values) < 3:
            rotation_values = (*rotation_values, 0.0)
        manual_rotation = self._attachment_visual_euler_quat(float(rotation_values[0]), float(rotation_values[1]), float(rotation_values[2]))
        new_rotation = self._attachment_visual_quat_multiply(
            self._attachment_visual_quat_inverse(manual_rotation),
            current_rotation,
        )
        target_socket.set("Rotation", self._format_attachment_transform_values(new_rotation))
        payload_text = self._attachment_socket_xml_text(
            root,
            include_declaration=original_text.lstrip().startswith("<?xml"),
        )
        return encode_xml_text_like_source(payload_text, decoded_socket_xml)
