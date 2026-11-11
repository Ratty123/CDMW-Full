"""Performance budgets from the P0 targets (P13 stage B). Opt in: -Area journeys.

Per case: five first views, each in a fresh profile (first view, then the
warm reselection and the Mesh Editor open), and five runs of one primed
profile (cached fresh-process view). Medians are compared with
``targets.BUDGETS``; only enforced budgets fail. Results are written to
``budgets-<case>.json`` beside the journey logs.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from tests.journeys import driver, targets

pytestmark = [pytest.mark.real_game, pytest.mark.timing,
              pytest.mark.skipif(bool(driver.skip_reason()), reason=driver.skip_reason() or "-")]
RUNS = 5


def _sample_processes(run: driver.Run, stop: threading.Event, rows: list) -> None:
    from cdmw.automation.client import AutomationClient

    with AutomationClient(run.app.address, run.app.token) as client:
        while not stop.is_set():
            try:
                tree = client.call("processes")["processes"]
            except Exception:
                return
            rows.append((len(tree), sum(p.get("working_set_bytes", 0) for p in tree) / 2**30))
            stop.wait(0.25)


def _first_view_run(case: str) -> dict:
    profile = driver.make_profile(f"budget-first-{case}")
    run = driver.Run(profile)
    try:
        usable = run.wait_usable()
        run.call("activate_tool", key="archive_browser")
        cold = run.select(driver.CASES[case])
        run.select(driver.OTHER)
        warm = run.select(driver.CASES[case])
        stop, rows = threading.Event(), []
        sampler = threading.Thread(target=_sample_processes, args=(run, stop, rows), daemon=True)
        sampler.start()
        editor = run.open_mesh_editor(item_set=case == "set")
        time.sleep(1.0)
        stop.set()
        sampler.join(5)
        return {"usable": usable, "first_view": cold["textured_s"], "warm": warm["textured_s"],
                "editor": editor["ready_s"], "editor_textured": editor["texture_unavailable_reason"] == "",
                "processes": max((r[0] for r in rows), default=0), "working_set_gib": max((r[1] for r in rows), default=0.0)}
    finally:
        run.close()
        driver.keep_log_and_remove(profile, f"budget-first-{case}")


def _cached_runs(case: str) -> list[float]:
    profile = driver.make_profile(f"budget-cached-{case}")
    try:
        prime = driver.Run(profile)
        try:
            prime.wait_usable()
            prime.call("activate_tool", key="archive_browser")
            prime.select(driver.CASES[case])
        finally:
            prime.close()
        values = []
        for _ in range(RUNS):
            run = driver.Run(profile)
            try:
                run.wait_usable()
                run.call("activate_tool", key="archive_browser")
                values.append(run.select(driver.CASES[case])["textured_s"])
            finally:
                run.close()
        return values
    finally:
        driver.keep_log_and_remove(profile, f"budget-cached-{case}")


@pytest.mark.parametrize("case", list(driver.CASES))
def test_budgets(case):
    runs = [_first_view_run(case) for _ in range(RUNS)]
    cached = _cached_runs(case)
    measured = {
        f"first_view_textured/{case}": driver.median(r["first_view"] for r in runs),
        f"warm_reselection/{case}": driver.median(r["warm"] for r in runs),
        f"cached_textured/{case}": driver.median(cached),
        "startup_usable": driver.median(r["usable"] for r in runs),
        "processes_with_editor": driver.median(r["processes"] for r in runs),
        "working_set_gib_with_editor": driver.median(r["working_set_gib"] for r in runs),
    }
    if case != "wyvern":
        measured[f"editor_ready/{case}"] = driver.median(r["editor"] for r in runs)
    rows = {name: {"median": value, "target": targets.BUDGETS[name].target_s,
                   "enforced": targets.BUDGETS[name].enforced, "met": value <= targets.BUDGETS[name].target_s}
            for name, value in measured.items()}
    report = {"case": case, "runs": runs, "cached": cached, "budgets": rows,
              "milestone": targets.CURRENT_MILESTONE}
    (driver.output_root() / f"budgets-{case}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    for name, row in rows.items():
        print(f"{name:36s} {row['median']:8.3f} target {row['target']:6.2f} "
              f"{'met' if row['met'] else 'MISSED'}{'' if row['enforced'] else ' (measured only)'}")
    assert all(r["editor_textured"] for r in runs), "the Mesh Editor opened untextured"
    missed = [f"{n} {r['median']:.2f} s over {r['target']}" for n, r in rows.items() if r["enforced"] and not r["met"]]
    assert not missed, "; ".join(missed)
