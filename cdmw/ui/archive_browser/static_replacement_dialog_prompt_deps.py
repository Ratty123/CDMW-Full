"""Dependency exports for static replacement prompt owner."""

from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps_base import (
    install_static_replacement_prompt_base_dependencies,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps_state_a import (
    install_static_replacement_prompt_state_a_dependencies,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps_state_b import (
    install_static_replacement_prompt_state_b_dependencies,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps_callbacks import (
    install_static_replacement_prompt_callbacks_dependencies,
)


def install_static_replacement_prompt_dependencies(namespace: dict[str, object]) -> None:
    install_static_replacement_prompt_base_dependencies(namespace)
    install_static_replacement_prompt_state_a_dependencies(namespace)
    install_static_replacement_prompt_state_b_dependencies(namespace)
    install_static_replacement_prompt_callbacks_dependencies(namespace)


__all__ = ["install_static_replacement_prompt_dependencies"]
