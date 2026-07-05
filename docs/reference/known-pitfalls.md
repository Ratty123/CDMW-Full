# Known Pitfalls

Last reviewed: 2026-06-21

- Do not restart the restructure or overwrite the current partial migration.
- `cdmw_app.py` and `cdmw/ui/main_window.py` are thin compatibility entry points; adding logic there regresses the architecture.
- Compatibility wrappers may be required during moves because tests and public imports still use old module paths.
- Source guards may still point at old files intentionally, especially facade modules and shell wiring.
- Some source guards combine old and new files; update the guard only after confirming the behavior it protects moved.
- Archive mutation must stay explicit, backed up, and recoverable.
- UI code must not directly mutate archives; route operations through services/workers/domain rules.
- Slow work belongs in `cdmw/workers/` or `cdmw/services/`, not on the UI thread.
- Worker-to-UI imports are boundary risks. The known archive filter helper leak was moved to `cdmw.domain.archives.filters` in Run 2; keep workers from importing UI packages.
- Rendering-to-UI imports are boundary risks. The known material preview combiner leak was moved to `cdmw.rendering.material_combiner`; keep rendering modules from importing UI packages.
- The known `cdmw.domain.textures.policy` to `cdmw.modding.material_replacer` import leak was resolved by moving pure material authority contract helpers to `cdmw.domain.textures.material_authority`; keep domain modules from importing `cdmw.modding`.
- Startup smoke may require PySide6 and offscreen Qt support.
- The active system Python may not have `pytest`; the project `.venv` currently does.
- Some tests may be Windows-specific or depend on local native tooling.
- Do not read or commit local game assets, extracted archives, DDS payloads, crash reports, restore points, build output, or local corpus data.
