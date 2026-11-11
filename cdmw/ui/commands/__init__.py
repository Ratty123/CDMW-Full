"""The command registry, its views, the palette and the keymap (P12)."""

from cdmw.ui.commands.registry import (
    CONTEXTS,
    Command,
    CommandRefused,
    CommandRegistry,
    command_registry,
)

__all__ = ["CONTEXTS", "Command", "CommandRefused", "CommandRegistry", "command_registry"]
