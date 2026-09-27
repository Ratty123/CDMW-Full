"""New Item Studio UI package."""

from __future__ import annotations

__all__ = ["NewItemStudioTab"]


def __getattr__(name: str) -> object:
    if name != "NewItemStudioTab":
        raise AttributeError(name)
    from cdmw.ui.new_item.tab import NewItemStudioTab

    globals()[name] = NewItemStudioTab
    return NewItemStudioTab


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
