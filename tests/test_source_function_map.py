from __future__ import annotations

from tests.source_function_map import _source_function_map, function_source


def test_function_source_preserves_nested_and_unicode_source() -> None:
    source = '''def outer():
    label = "räv"
    def inner():
        return label
    return inner()
'''

    assert function_source(source, "inner") == "def inner():\n        return label"


def test_function_source_keeps_first_duplicate_definition() -> None:
    source = "def repeated():\n    return 1\n\ndef repeated():\n    return 2\n"

    assert function_source(source, "repeated") == "def repeated():\n    return 1"


def test_function_source_cache_is_bounded() -> None:
    _source_function_map.cache_clear()
    for index in range(12):
        function_source(f"def function_{index}():\n    return {index}\n", f"function_{index}")

    assert _source_function_map.cache_info().currsize == 8
