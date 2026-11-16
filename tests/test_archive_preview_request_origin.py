"""A preview request names who asked without reading any source file.

The origin went through ``traceback.extract_stack``, which looks up the source
line of every frame of the whole stack. The built app has no source files, so
each of those lookups went to the frozen importer on the window thread; the
review caught one in a 537 ms pause on "Browse: reselect the model".
"""

from __future__ import annotations

import linecache

from cdmw.ui.archive_browser import workers


def _request_preview():
    # Stands in for _render_archive_preview, which the origin skips.
    return workers._preview_request_origin()


def _select_row():
    return _request_preview()


def _click():
    return _select_row()


def test_origin_names_the_callers_without_looking_up_source_lines(monkeypatch):
    lookups = []
    for name in ("getline", "getlines", "updatecache", "checkcache"):
        original = getattr(linecache, name)
        monkeypatch.setattr(linecache, name, lambda *a, _o=original, _n=name, **k: (lookups.append(_n), _o(*a, **k))[1])

    origin = _click()

    assert lookups == []
    parts = origin.split(" <- ")
    module = "test_archive_preview_request_origin"
    assert parts[0].startswith(f"{module}._select_row:")
    assert parts[1].startswith(f"{module}._click:")
    assert len(parts) == 6
    functions = [part.split(".", 1)[1].split(":")[0] for part in parts]
    assert "_request_preview" not in functions and "_preview_request_origin" not in functions
