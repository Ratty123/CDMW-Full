# Known Pitfalls

Last reviewed: 2026-06-12

- Do not restart the restructure or overwrite the current partial migration.
- `cdmw_app.py` and `cdmw/ui/main_window.py` are thin compatibility entry points; adding logic there regresses the architecture.
- Compatibility wrappers may be required during moves because tests and public imports still use old module paths.
- Source guards may still point at old files intentionally, especially facade modules and shell wiring.
- Some source guards combine old and new files; update the guard only after confirming the behavior it protects moved.
- Archive mutation must stay explicit, backed up, and recoverable.
- UI code must not directly mutate archives; route operations through services/workers/domain rules.
- Slow work belongs in `cdmw/workers/` or `cdmw/services/`, not on the UI thread.
- Graphify output is generated and should not be committed blindly; `graphify-out/` is ignored.
- Graphify is useful for navigation only. Source code and tests remain authoritative.
- This midpoint Graphify run is code-only and unclustered; it did not produce `GRAPH_REPORT.md` or `graph.html`.
- Worker-to-UI imports, especially workers using `cdmw.ui.archive_browser.filters`, are boundary risks to verify before moving code.
- Domain-to-modding imports, especially `cdmw.domain.textures.policy` using `cdmw.modding.material_replacer`, are boundary risks to verify before moving code.
- Startup smoke may require PySide6 and offscreen Qt support.
- The active system Python may not have `pytest`; the project `.venv` currently does.
- Some tests may be Windows-specific or depend on local native tooling.
- Do not read or commit local game assets, extracted archives, DDS payloads, crash reports, restore points, build output, or local corpus data.
