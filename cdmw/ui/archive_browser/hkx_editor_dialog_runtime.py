from __future__ import annotations

from types import SimpleNamespace


def run_hkx_editor_dialog(host, entry, document_text, initial_section, module_globals, steps) -> None:
    state = SimpleNamespace(
        self=host,
        entry=entry,
        document_text=document_text,
        initial_section=initial_section,
    )
    for name, value in module_globals.items():
        if not name.startswith("__"):
            setattr(state, name, value)
    for step in steps:
        step(state)


__all__ = ["run_hkx_editor_dialog"]
