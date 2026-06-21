"""Bridge between persistent settings and shell state."""

from __future__ import annotations

import base64
from typing import Optional

PROFILE_SETTING_BINARY_TYPE = "qbytearray_base64"


def encode_profile_setting_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {
            "__cdmw_type__": PROFILE_SETTING_BINARY_TYPE,
            "value": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, bytearray):
        return {
            "__cdmw_type__": PROFILE_SETTING_BINARY_TYPE,
            "value": base64.b64encode(bytes(value)).decode("ascii"),
        }
    if hasattr(value, "toBase64"):
        try:
            encoded = value.toBase64()
            if hasattr(encoded, "data"):
                encoded_bytes = encoded.data()
            else:
                encoded_bytes = bytes(encoded)
            return {
                "__cdmw_type__": PROFILE_SETTING_BINARY_TYPE,
                "value": bytes(encoded_bytes).decode("ascii"),
            }
        except Exception:
            pass
    if isinstance(value, (list, tuple)):
        return [encode_profile_setting_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): encode_profile_setting_value(item) for key, item in value.items()}
    return {
        "__cdmw_type__": "string",
        "value": str(value),
    }


def decode_profile_setting_value(value: object, *, qbytearray_type: Optional[type] = None) -> object:
    if isinstance(value, list):
        return [decode_profile_setting_value(item, qbytearray_type=qbytearray_type) for item in value]
    if not isinstance(value, dict):
        return value
    value_type = str(value.get("__cdmw_type__", "") or "")
    if value_type == PROFILE_SETTING_BINARY_TYPE:
        raw_text = str(value.get("value", "") or "")
        try:
            raw = base64.b64decode(raw_text.encode("ascii"))
        except Exception:
            raw = b""
        if qbytearray_type is not None:
            try:
                return qbytearray_type(raw)
            except Exception:
                return raw
        return raw
    if value_type == "string":
        return str(value.get("value", "") or "")
    return {str(key): decode_profile_setting_value(item, qbytearray_type=qbytearray_type) for key, item in value.items()}


def read_int_setting(settings: object, key: str, default: int) -> int:
    try:
        return int(settings.value(key, default))  # type: ignore[attr-defined]
    except (TypeError, ValueError):
        return int(default)


def read_bool_setting(settings: object, key: str, default: bool) -> bool:
    value = settings.value(key, default)  # type: ignore[attr-defined]
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class SettingsBridge:
    def __init__(self, settings: object | None = None) -> None:
        self.settings = settings


__all__ = [
    "PROFILE_SETTING_BINARY_TYPE",
    "SettingsBridge",
    "decode_profile_setting_value",
    "encode_profile_setting_value",
    "read_bool_setting",
    "read_int_setting",
]
