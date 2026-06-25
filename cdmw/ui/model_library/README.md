# Model Library

Owns the Model Library tab, audit-result presentation, external model discovery
UI, and model-library preview coordination. Keep slow discovery or preview work
off the UI thread through the tab task worker. Inline preview preparation lives
in `cdmw/services/model_library_preview.py`. Model Library auto-preview and
Preview Here use the inline native D3D11 host by default so loaded models draw
in the preview pane. Archive Browser preview remains an explicit manual action.
