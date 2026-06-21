from __future__ import annotations

"""UI-constraint candidate rules for Texture Editor source bindings."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping, Optional

from cdmw.models import TextureEditorSourceBinding


@dataclass(frozen=True, slots=True)
class TextureEditorUIConstraintWarningLookupState:
    target_path: str
    cache_key: str
    warning_text: str
    should_cache_empty: bool
    should_start_lookup: bool


@dataclass(frozen=True, slots=True)
class TextureEditorUIConstraintWarningState:
    warning_text: str
    empty_cache_key: str
    lookup_target_path: str


@dataclass(frozen=True, slots=True)
class TextureEditorUIConstraintLookupStartState:
    cache_key: str
    should_start: bool


@dataclass(frozen=True, slots=True)
class TextureEditorUIConstraintReadyState:
    cache_key: str
    warning_text: str
    should_refresh_metadata: bool


def texture_editor_ui_constraint_target_path(binding: TextureEditorSourceBinding) -> str:
    return (binding.archive_relative_path or binding.relative_path or "").strip()


def texture_editor_ui_constraint_cache_key(target_path: str) -> str:
    return str(target_path or "").strip().casefold()


def looks_like_texture_editor_ui_constraint_candidate(target_path: str) -> bool:
    normalized = str(target_path or "").replace("\\", "/").lower()
    if not normalized:
        return False
    ui_tokens = ("/ui/", "/icon/", "/hud/", "/menu/", "/widget/")
    name_tokens = ("itemicon", "ui_", "icon_", "hud_", "menu_")
    return any(token in normalized for token in ui_tokens) or any(
        token in PurePosixPath(normalized).name for token in name_tokens
    )


def texture_editor_ui_constraint_warning_lookup_state(
    binding: TextureEditorSourceBinding,
    warning_cache: Mapping[str, str],
) -> TextureEditorUIConstraintWarningLookupState:
    target_path = texture_editor_ui_constraint_target_path(binding)
    cache_key = texture_editor_ui_constraint_cache_key(target_path)
    if not target_path or not cache_key:
        return TextureEditorUIConstraintWarningLookupState(
            target_path="",
            cache_key="",
            warning_text="",
            should_cache_empty=False,
            should_start_lookup=False,
        )
    cached = warning_cache.get(cache_key)
    if cached is not None:
        return TextureEditorUIConstraintWarningLookupState(
            target_path=target_path,
            cache_key=cache_key,
            warning_text=cached,
            should_cache_empty=False,
            should_start_lookup=False,
        )
    if not looks_like_texture_editor_ui_constraint_candidate(target_path):
        return TextureEditorUIConstraintWarningLookupState(
            target_path=target_path,
            cache_key=cache_key,
            warning_text="",
            should_cache_empty=True,
            should_start_lookup=False,
        )
    return TextureEditorUIConstraintWarningLookupState(
        target_path=target_path,
        cache_key=cache_key,
        warning_text="",
        should_cache_empty=False,
        should_start_lookup=True,
    )


def texture_editor_ui_constraint_warning_state(
    binding: Optional[TextureEditorSourceBinding],
    warning_cache: Mapping[str, str],
) -> TextureEditorUIConstraintWarningState:
    if binding is None:
        return TextureEditorUIConstraintWarningState(warning_text="", empty_cache_key="", lookup_target_path="")
    lookup_state = texture_editor_ui_constraint_warning_lookup_state(binding, warning_cache)
    return TextureEditorUIConstraintWarningState(
        warning_text=lookup_state.warning_text,
        empty_cache_key=lookup_state.cache_key if lookup_state.should_cache_empty else "",
        lookup_target_path=lookup_state.target_path if lookup_state.should_start_lookup else "",
    )


def texture_editor_ui_constraint_lookup_start_state(
    target_path: str,
    warning_cache: Mapping[str, str],
    *,
    pending_cache_key: str,
    worker_active: bool,
) -> TextureEditorUIConstraintLookupStartState:
    cache_key = texture_editor_ui_constraint_cache_key(target_path)
    should_start = bool(
        cache_key
        and cache_key not in warning_cache
        and str(pending_cache_key or "") != cache_key
        and not worker_active
    )
    return TextureEditorUIConstraintLookupStartState(cache_key=cache_key, should_start=should_start)


def texture_editor_ui_constraint_ready_state(
    target_path: str,
    warning_text: str,
    binding: Optional[TextureEditorSourceBinding],
) -> TextureEditorUIConstraintReadyState:
    cache_key = texture_editor_ui_constraint_cache_key(target_path)
    current_key = "" if binding is None else texture_editor_ui_constraint_cache_key(
        texture_editor_ui_constraint_target_path(binding)
    )
    return TextureEditorUIConstraintReadyState(
        cache_key=cache_key,
        warning_text=str(warning_text or ""),
        should_refresh_metadata=bool(current_key and current_key == cache_key),
    )


__all__ = [
    "looks_like_texture_editor_ui_constraint_candidate",
    "texture_editor_ui_constraint_cache_key",
    "texture_editor_ui_constraint_lookup_start_state",
    "texture_editor_ui_constraint_ready_state",
    "texture_editor_ui_constraint_target_path",
    "texture_editor_ui_constraint_warning_lookup_state",
    "texture_editor_ui_constraint_warning_state",
    "TextureEditorUIConstraintLookupStartState",
    "TextureEditorUIConstraintReadyState",
    "TextureEditorUIConstraintWarningLookupState",
    "TextureEditorUIConstraintWarningState",
]
