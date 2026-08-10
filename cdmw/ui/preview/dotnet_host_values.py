from __future__ import annotations

from collections.abc import Iterable, Sequence


def _indices(values: Iterable[object]) -> list[int]:
    result: set[int] = set()
    for value in values or ():
        if isinstance(value, bool):
            continue
        try:
            index = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0:
            result.add(index)
    return sorted(result)


def _triple(values: Sequence[object], fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    try:
        result = tuple(float(value) for value in tuple(values or ())[:3])
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if len(result) == 3 else fallback  # type: ignore[return-value]


__all__ = ["_indices", "_triple"]
