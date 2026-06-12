# Refactor Brief

1. Confirm the current owner and public import path before editing.
2. Move one coherent behavior slice at a time.
3. Keep `cdmw_app.py` and `cdmw/ui/main_window.py` thin.
4. Preserve compatibility wrappers.
5. Migrate source guards only after confirming the protected behavior moved.
6. Run targeted tests before starting another slice.
