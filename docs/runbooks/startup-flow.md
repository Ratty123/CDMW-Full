# Startup Flow

`cdmw_app.py` delegates to `cdmw.app.bootstrap.main`.

1. Parse arguments in `cdmw.app.args`.
2. Route startup-splash host mode before normal app startup.
3. Validate mutually exclusive CLI/GUI/legacy renderer flags.
4. For GUI mode, acquire single-instance guard and request activation if another
   instance is running.
5. Write the PyInstaller runtime marker and start external splash when enabled.
6. Schedule startup maintenance for stale PyInstaller runtime and temp cache
   cleanup.
7. Import and run GUI through `cdmw.app.gui`.
8. On bootstrap failure, write a bootstrap report.
9. Always close startup splash and release the single-instance guard on GUI exit.

CLI mode runs startup maintenance synchronously and then calls the pipeline CLI.
