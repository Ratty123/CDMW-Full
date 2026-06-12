# Graphify Midpoint Summary

## Status

- Graphify run date: 2026-06-12
- Command used: `.\.venv\Scripts\graphify.exe .` attempted; `.\.venv\Scripts\graphify.exe update . --no-cluster` completed.
- Output reviewed: `graphify-out/graph.json`, `graphify-out/manifest.json`
- Install method: project virtualenv install with `.\.venv\Scripts\python.exe -m pip install graphifyy`
- Limitations: no LLM API key was configured, so the full `graphify .` run stopped on docs/images; the completed output is code-only and unclustered.

## Highest-coupling files or nodes

| Node | Why it matters | Suggested action |
|---|---|---|
| `cdmw/models.py` / `ArchiveEntry` | Shared model types are referenced across core, UI, tests, and workers. | Do not move casually; split only with compatibility imports and broad tests. |
| `cdmw/core/archive.py` | Archive primitives and helpers are still heavily referenced by UI and workers. | Extract narrow pure rules only when a behavior test already identifies ownership. |
| `cdmw/core/archive_modding.py` | Patch/export/mesh-support types remain central to archive workflows. | Prefer service/domain wrappers before moving mutation-heavy behavior. |
| `cdmw/modding/material_replacer.py` | Material and texture replacement rules remain coupled to several workflows. | Target small pure helper extractions with material tests first. |
| `cdmw/ui/shell/app_window.py` / `MainWindow` | The new shell owner is central after the partial migration. | Keep shell wiring here, but move feature behavior out. |
| `cdmw/ui/research/tab.py` / `ResearchTab` | Research feature is migrated but still large and coupled to core research/archive helpers. | Split controller/state/workers after tests are mapped. |
| `cdmw/ui/archive_browser/static_replacement_dialog.py` | Still a large UI coordination point with many core/modding/rendering/worker imports. | Next high-value split target, but only one behavior slice at a time. |

## Surprising dependencies

| Link | Risk | Verification needed |
|---|---|---|
| `cdmw/workers/archive_scan_workers.py` -> `cdmw.ui.archive_browser.filters` | Worker depends on UI package helper; boundary may be leaky. | Check whether filter/index helpers belong in `cdmw/domain/archives/`. |
| `cdmw/workers/archive_filter_workers.py` -> `cdmw.ui.archive_browser.filters` | Same worker-to-UI dependency in filtering path. | Run archive filter/model tests before moving anything. |
| `cdmw/domain/textures/policy.py` -> `cdmw.modding.material_replacer` | Domain layer imports a heavy modding module. | Confirm whether only pure policy helpers are needed. |
| `cdmw/app/gui.py` -> `cdmw.ui.main_window` | App layer uses public facade instead of shell implementation. | Currently expected by tests; do not change without updating guards. |
| `cdmw/ui/archive_browser_model.py` wildcard re-export | Compatibility facade may hide public API drift. | Keep until facade tests prove all legacy imports are covered. |

## Refactor priorities

1. Choose one low-risk archive-browser boundary leak, likely filter/index helper ownership, and move it with archive filter tests.
2. Split one pure/static helper slice from `cdmw/ui/archive_browser/static_replacement_dialog.py` into an existing helper/domain/service owner.
3. Continue research/model-library feature package cleanup only after source guards are updated to point at current owners.

## Areas to avoid touching yet

- `cdmw_app.py`
- `cdmw/ui/main_window.py`
- Archive mutation paths that write payloads or patch archives.
- `cdmw/models.py` shared dataclasses and public result types.
- Generated `graphify-out/` output.

## Updates needed in AI docs

- PROJECT_MAP.md: note Graphify-confirmed coupling hotspots and code-only limitation.
- TEST_MATRIX.md: keep virtualenv guidance because plain `python` lacks pytest here.
- KNOWN_PITFALLS.md: call out worker-to-UI and domain-to-modding boundary leaks as audit findings.

## Graphify limitations

- Findings are advisory.
- Source and tests remain authoritative.
- Graph output may miss dynamic imports, runtime wiring, or framework behavior.
- This run included code from `.agents/` because the code-only update scanned all code files; curated findings above filter that noise out.
- No `GRAPH_REPORT.md` or `graph.html` was produced by the successful no-cluster update command.
