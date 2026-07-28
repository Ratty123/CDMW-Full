"""Scope guard for the alignment preview shell's Qt slots.

The alignment dialog is assembled from context dictionaries, so a slot can name
a helper the builder never bound and stay silent until the signal fires. Text
assertions cannot see that: ``_preview_part_pick_toggled`` shipped calling
``_clear_all_part_selections`` while the preview shell only ever bound
``_sync_highlight_sets``, so unchecking Part Pick raised ``NameError`` inside
the slot even though every substring guard still passed.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_SHELL = ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_preview_shell.py"
PROMPT = ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt.py"

# Deferred helpers the preview shell calls from slots. Each one is a placeholder
# when the shell is built and only becomes real during replacement setup, so the
# prompt has to hand the shell a late-resolving wrapper for it.
DEFERRED_PREVIEW_SHELL_CALLBACKS = (
    "_sync_highlight_sets",
    "_clear_all_part_selections",
)


def _names_bound_in(function: ast.FunctionDef) -> set[str]:
    bound = {argument.arg for argument in function.args.args}
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not function:
            bound.add(node.name)
    return bound


class AlignmentPreviewShellScopeGuardTests(unittest.TestCase):
    def test_preview_shell_binds_every_deferred_callback_it_calls(self) -> None:
        source = PREVIEW_SHELL.read_text(encoding="utf-8")
        factory = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "create_alignment_preview_shell_section"
        )
        bound = _names_bound_in(factory)
        for name in DEFERRED_PREVIEW_SHELL_CALLBACKS:
            self.assertIn(
                name,
                bound,
                f"{name} is called in the preview shell but never bound from context",
            )
            self.assertIn(f"{name} = context.get('{name}')", source)

    def test_prompt_defers_the_placeholder_callbacks_to_call_time(self) -> None:
        source = PROMPT.read_text(encoding="utf-8")
        for name in DEFERRED_PREVIEW_SHELL_CALLBACKS:
            self.assertIn(f"def {name}_when_ready(*args, **kwargs):", source)
            self.assertIn(f'prompt_shell_context.get("{name}")', source)
            self.assertIn(f"'{name}': {name}_when_ready", source)


if __name__ == "__main__":
    unittest.main()
