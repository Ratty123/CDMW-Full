"""Small pre-Qt localization snapshot for startup-owned presentation text."""

from __future__ import annotations

import configparser
import json
import re
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from cdmw.domain.localization import canonical_language_code
from cdmw.services.localization_file_service import load_language_file
from cdmw.services.settings_service import resolve_settings_file_path


STARTUP_TRANSLATION_MAX_KEYS = 128
STARTUP_TRANSLATION_MAX_BYTES = 48 * 1024


def _resource_root() -> Path:
    frozen_root = str(getattr(sys, "_MEIPASS", "") or "").strip()
    if frozen_root:
        return Path(frozen_root) / "cdmw" / "resources" / "localization"
    return Path(__file__).resolve().parents[1] / "resources" / "localization"


def _read_saved_language(settings_path: Path) -> str:
    parser = configparser.ConfigParser()
    try:
        if parser.read(settings_path, encoding="utf-8"):
            return canonical_language_code(
                parser.get("appearance", "language", fallback="en")
            )
    except (configparser.Error, OSError, UnicodeError):
        pass
    return "en"


def _read_builtin_subset(code: str, keys: frozenset[str]) -> dict[str, str]:
    path = _resource_root() / f"{code}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    raw = payload.get("translations") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {}
    translations: dict[str, str] = {}
    for source in keys:
        entry = raw.get(source)
        if isinstance(entry, str) and entry:
            translations[source] = entry
        elif isinstance(entry, dict):
            value = entry.get("other")
            if isinstance(value, str) and value:
                translations[source] = value
    return translations


def _custom_overlay(language_dir: Path, code: str) -> dict[str, object]:
    winner: tuple[int, Path, dict[str, object]] | None = None
    if not language_dir.is_dir():
        return {}
    for path in sorted(language_dir.glob("*.json")):
        try:
            declared_code, _name, translations = load_language_file(path)
        except (OSError, ValueError):
            continue
        if canonical_language_code(declared_code) != code:
            continue
        declared = str(declared_code or "").strip().replace("_", "-")
        rank = int(declared.casefold() == code.casefold())
        if winner is None or rank > winner[0]:
            winner = (rank, path, dict(translations))
    return winner[2] if winner is not None else {}


def _template_pattern(source: str) -> tuple[re.Pattern[str], tuple[tuple[str, str], ...]] | None:
    try:
        parsed = tuple(string.Formatter().parse(source))
    except ValueError:
        return None
    if not any(field is not None for _literal, field, _spec, _conversion in parsed):
        return None
    expression = ["^"]
    fields: list[tuple[str, str]] = []
    literal_chars = 0
    for literal, field, _format_spec, _conversion in parsed:
        expression.append(re.escape(literal))
        literal_chars += len(literal)
        if field is None:
            continue
        name = str(field).split(".", 1)[0].split("[", 1)[0]
        if not name or name.isdigit():
            return None
        group = f"g{len(fields)}"
        fields.append((group, name))
        expression.append(f"(?P<{group}>.+?)")
    if literal_chars < 2:
        return None
    expression.append("$")
    try:
        return re.compile("".join(expression), re.DOTALL), tuple(fields)
    except re.error:
        return None


@dataclass(frozen=True, slots=True)
class StartupMessage:
    key: str
    arguments: Mapping[str, str]
    rendered: str


class StartupLocalizer:
    """Immutable, bounded translations used before the live Qt owner exists."""

    def __init__(self, language_code: str, translations: Mapping[str, str]) -> None:
        self.language_code = canonical_language_code(language_code)
        self.translations = MappingProxyType(
            {str(key): str(value) for key, value in translations.items()}
        )
        patterns: list[
            tuple[int, re.Pattern[str], str, tuple[tuple[str, str], ...]]
        ] = []
        for source in self.translations:
            compiled = _template_pattern(source)
            if compiled is None:
                continue
            pattern, fields = compiled
            literal_weight = sum(
                len(literal)
                for literal, _field, _spec, _conversion in string.Formatter().parse(source)
            )
            patterns.append((literal_weight, pattern, source, fields))
        patterns.sort(key=lambda item: (-item[0], item[2]))
        self._patterns = tuple(
            (pattern, source, fields)
            for _weight, pattern, source, fields in patterns
        )

    def translate(self, source: str, /, **arguments: object) -> str:
        template = self.translations.get(str(source), str(source))
        try:
            return template.format(**arguments)
        except (KeyError, ValueError, IndexError):
            try:
                return str(source).format(**arguments)
            except (KeyError, ValueError, IndexError):
                return template

    def resolve_message(self, rendered_source: str) -> StartupMessage:
        source_text = str(rendered_source or "Starting application...")
        if source_text in self.translations:
            return StartupMessage(
                source_text,
                MappingProxyType({}),
                self.translate(source_text),
            )
        for pattern, source, fields in self._patterns:
            match = pattern.fullmatch(source_text)
            if match is None:
                continue
            arguments = {
                field_name: match.group(group_name)
                for group_name, field_name in fields
            }
            return StartupMessage(
                source,
                MappingProxyType(arguments),
                self.translate(source, **arguments),
            )
        return StartupMessage(
            source_text,
            MappingProxyType({}),
            source_text,
        )

    def protocol_translations(self) -> dict[str, str]:
        return dict(self.translations)


def load_startup_localizer(
    *,
    settings_path: Path | None = None,
) -> StartupLocalizer:
    resolved_settings = Path(settings_path or resolve_settings_file_path())
    selected_code = _read_saved_language(resolved_settings)
    manifest_path = _resource_root() / "source_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("entries") if isinstance(manifest, dict) else None
        startup_keys = frozenset(
            str(entry.get("key"))
            for entry in entries or ()
            if isinstance(entry, dict)
            and any(
                str(origin.get("sink", "")) in {
                    "_update_startup_splash",
                    "pump_startup_splash",
                    "set_detail",
                    "update_pyinstaller_boot_splash",
                    "write_startup_splash_command",
                    "write_startup_splash_payload",
                }
                for origin in entry.get("origins", ())
                if isinstance(origin, dict)
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        startup_keys = frozenset({"Starting application...", "Opening workspace..."})
    if not startup_keys or len(startup_keys) > STARTUP_TRANSLATION_MAX_KEYS:
        startup_keys = frozenset({"Starting application...", "Opening workspace..."})

    translations = _read_builtin_subset("en", startup_keys)
    if selected_code != "en":
        translations.update(_read_builtin_subset(selected_code, startup_keys))
    overlay = _custom_overlay(resolved_settings.parent / "languages", selected_code)
    for source in startup_keys:
        entry = overlay.get(source)
        if isinstance(entry, str) and entry:
            translations[source] = entry
        elif isinstance(entry, dict):
            value = entry.get("other")
            if isinstance(value, str) and value:
                translations[source] = value

    encoded = json.dumps(
        translations,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > STARTUP_TRANSLATION_MAX_BYTES:
        translations = {
            source: translations[source]
            for source in ("Starting application...", "Opening workspace...")
            if source in translations
        }
    return StartupLocalizer(selected_code, translations)


def render_startup_message(
    *,
    message_key: object,
    message_args: object,
    translations: object,
    fallback: object,
) -> str:
    key = str(message_key or "")
    arguments = (
        {str(name): value for name, value in message_args.items()}
        if isinstance(message_args, dict)
        else {}
    )
    template = (
        str(translations.get(key))
        if isinstance(translations, dict) and isinstance(translations.get(key), str)
        else str(fallback or key or "Starting application...")
    )
    try:
        return template.format(**arguments)
    except (KeyError, ValueError, IndexError):
        return str(fallback or key or "Starting application...")


__all__ = [
    "STARTUP_TRANSLATION_MAX_BYTES",
    "STARTUP_TRANSLATION_MAX_KEYS",
    "StartupLocalizer",
    "StartupMessage",
    "load_startup_localizer",
    "render_startup_message",
]
