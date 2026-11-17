"""A new Mesh Editor session starts its texture edits afresh (Work B, B pass 6).

Texture edits outlive their editor session on purpose: after Finish, Build Mod writes
them. But the next session must not inherit them. Start Fresh begins a draft without
them, and continuing a draft gets back only what that draft kept. When a session loads,
this forgets the last session's edits everywhere they live (the live edits and the
keeper's state, the Texture Editor documents the dock opened for them, the dock's
targets, and the shared history's texture entries). The draft's own kept edits are
then restored by the caller.
"""

from __future__ import annotations

from pathlib import Path


def start_texture_edits_afresh(tab) -> None:
    # The edits, the keeper and the shared history belong to the tab's live-edit
    # component; the dock is the tab's.
    owner = getattr(tab, "live_edit", None) or tab
    live = getattr(owner, "_live_texture_updates", None)
    if live is not None:
        live.clear()
    keeper = getattr(owner, "_live_texture_keeping", None)
    if keeper is not None:
        keeper.forget()
    owner._shared_edit_history = None  # a new history per document session (B item 4)
    close_texture_editor_panel(tab)


def close_texture_editor_panel(tab) -> None:
    """Close the textures the Texture Editor panel has open and show it empty. The live
    edits and what the draft keeps of them are not touched."""

    panel = getattr(tab, "_texture_tools_panel", None)
    try:
        dock = panel() if callable(panel) else None
    except RuntimeError:
        return
    if dock is None:
        return
    targets = list(getattr(dock, "_targets", {}).values())
    editor = getattr(dock, "editor", None)
    sessions = getattr(editor, "_sessions", None)
    close = getattr(editor, "_close_document_tabs", None)
    if targets and sessions is not None and callable(close):
        from cdmw.ui.texture_workflow.editor_session import texture_editor_existing_source_session_index

        indices = set()
        for target in targets:
            try:
                index = texture_editor_existing_source_session_index(sessions, Path(target.source_path))
            except (OSError, ValueError):
                continue
            if index >= 0:
                indices.add(index)
        if indices:
            close(sorted(indices))
    show_empty = getattr(dock, "show_empty", None)
    if callable(show_empty):
        show_empty()
    else:
        dock._targets = {}
        dock.target = None


__all__ = ["close_texture_editor_panel", "start_texture_edits_afresh"]
