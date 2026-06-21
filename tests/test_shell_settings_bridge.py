from __future__ import annotations

import unittest

from cdmw.ui.shell.settings_bridge import (
    decode_profile_setting_value,
    encode_profile_setting_value,
    read_bool_setting,
    read_int_setting,
)


class _SettingsStub:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def value(self, key: str, default: object) -> object:
        return self.values.get(key, default)


class ShellSettingsBridgeTests(unittest.TestCase):
    def test_profile_setting_serializer_round_trips_nested_values(self) -> None:
        encoded = encode_profile_setting_value(
            {
                "theme": "graphite",
                "bytes": b"abc",
                "items": [1, bytearray(b"xy")],
                "custom": object(),
            }
        )

        decoded = decode_profile_setting_value(encoded)

        self.assertEqual("graphite", decoded["theme"])
        self.assertEqual(b"abc", decoded["bytes"])
        self.assertEqual(1, decoded["items"][0])
        self.assertEqual(b"xy", decoded["items"][1])
        self.assertIsInstance(decoded["custom"], str)

    def test_read_setting_helpers_apply_defaults_and_normalization(self) -> None:
        settings = _SettingsStub({"int": "24", "bad_int": "x", "true": "yes", "false": "off"})

        self.assertEqual(24, read_int_setting(settings, "int", 10))
        self.assertEqual(10, read_int_setting(settings, "bad_int", 10))
        self.assertTrue(read_bool_setting(settings, "true", False))
        self.assertFalse(read_bool_setting(settings, "false", True))
        self.assertTrue(read_bool_setting(settings, "missing", True))


if __name__ == "__main__":
    unittest.main()
