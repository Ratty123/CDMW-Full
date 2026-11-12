"""Owned game folders and item packages for tests (moved from the removed virtual-loader tests)."""

from __future__ import annotations

import time
from uuid import uuid4

from cdmw.services.independent_item_package import from_plan, package_bytes


def packages(tmp_path, count=2):
    """An owned synthetic game under ``tmp_path/game`` and ``count`` item packages made against it."""
    from tests.test_archive_overlay_manager import shop_spec
    from tests.test_independent_items import setup_game

    service, snapshot, _ = setup_game(tmp_path)
    result = []
    for i in range(count):
        plan = service.plan(shop_spec('SameSourceName'), snapshot, capture_independent=True)
        item = from_plan(plan, uuid4().hex)
        file = tmp_path / f'item-{i}.cditem'
        file.write_bytes(package_bytes(item))
        result.append(file)
    return tmp_path / 'game', tuple(result)


def game_bytes(root):
    """Every game file's bytes, CDMW's own records left out."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.cdmw' not in p.parts}


def drain(app, controller):
    """Process events until the Create New Item controller and its lookup lanes are idle."""
    deadline = time.monotonic() + 5

    def busy():
        return controller.busy or any(lane.busy for lane in controller._lookup_lanes)

    while busy() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert not busy()
