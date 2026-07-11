from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar, cast


_P = ParamSpec("_P")
_R = TypeVar("_R")


def bind_archive_hkx_globals(*names: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Keep moved HKX helpers compatible with facade-level patch seams."""

    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        namespace = function.__globals__

        @wraps(function)
        def bound(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            facade = sys.modules.get("cdmw.core.archive_hkx")
            if facade is None:
                facade = importlib.import_module("cdmw.core.archive_hkx")
            facade_namespace = vars(facade)
            for name in names:
                namespace[name] = facade_namespace[name]
            return function(*args, **kwargs)

        return cast(Callable[_P, _R], bound)

    return decorate
