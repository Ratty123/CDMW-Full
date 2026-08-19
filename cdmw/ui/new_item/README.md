# New Item Studio

Owns the New Item Studio tab: clone an equipment item into a brand-new one with
its own identity, model, icon, stats, shop placement and item groups, then write
it as a loose mod or install it.

`state.py` is the editable draft and the pure helpers (stat grid, spec from
draft). `controller.py` holds the draft, the read-only archive snapshot and the
last plan, and runs the snapshot, plan, export, install, the model import and
the placement build through `cdmw/workers/new_item_workers.py` on one owned
thread at a time. The `panels_*.py` modules edit the draft and ask the
controller for facts; `tab.py` composes them, and forwards install to the shell.

The Model and icon step imports a model file itself: `model_import.py` reads it
the way the Model Library does (the scene import, the source's own textures),
`item_preview.py` shows it over the template in the resident viewport with the
gizmo (`PlacementScene`), and `ModelPlacement.build_transform()` turns the
placement into the static replacement's transform for the headless Builder import
(`build_placed_import`), whose result is what the plan writes. The viewport's
rotation convention (the helper's yaw/pitch/roll) and the pipeline's x-then-y-
then-z are the same matrix re-expressed, proven in
`tests/test_new_item_item_preview.py` and the studio tab tests.

UI code here never touches the archives: reading is the service's snapshot,
writing is `ArchiveMutationService` through the service's `install`, and the
loose export is the package finalizer. Entry points: the tool tab
`new_item_studio` and the Item Finder's `Clone as new item...`; a ready Builder
result can still be handed in through the tab's `receive_imported_model`.

Related tests: `tests/test_new_item_studio_tab.py`.
