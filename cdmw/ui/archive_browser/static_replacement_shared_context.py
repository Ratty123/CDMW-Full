"""Reading the dialog's shared mutable state out of a factory context.

The Builder's factory files bind their state from one shared `context` dict.
Several entries are containers the dialog mutates for its whole life: the
highlight sets, the hovered-part slot, the part-adjustment map, the texture file
list. A factory must hold *that* object, not a copy, or it reads a value nothing
ever writes to.

`context.get(key) or set()` is the trap: at construction the shared set is
empty, empty is false, and the factory quietly binds a fresh private set. The
presentation snapshot did exactly that for every highlight set and for the part
adjustments, so every republish told the resident renderer there was no
selection, and the highlight a pick had just sent went dark on the next refresh.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

_T = TypeVar("_T")


def shared_context_container(context: Mapping[str, object], key: str, factory: Callable[[], _T]) -> _T:
    """The dialog's own container for `key`; a fresh one only when there is none.

    Emptiness is not absence. The factory result is used only when the context
    has no entry at all, so a bound container stays the one the rest of the
    dialog mutates.
    """
    value = context.get(key)
    if value is None:
        return factory()
    return value  # type: ignore[return-value]


__all__ = ["shared_context_container"]
