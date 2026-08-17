# New Item Studio

Owns the New Item Studio tab: clone an equipment item into a brand-new one with
its own identity, model, icon, stats, shop placement and item groups, then write
it as a loose mod or install it.

`state.py` is the editable draft and the pure helpers (stat grid, spec from
draft). `controller.py` holds the draft, the read-only archive snapshot and the
last plan, and runs the snapshot, plan, export and install through
`cdmw/workers/new_item_workers.py` on one owned thread at a time. The
`panels_*.py` modules edit the draft and ask the controller for facts;
`tab.py` composes them, and forwards model import and install to the shell.

UI code here never touches the archives: reading is the service's snapshot,
writing is `ArchiveMutationService` through the service's `install`, and the
loose export is the package finalizer. Entry points: the tool tab
`new_item_studio`, the Item Finder's `Clone as new item...`, and the Builder's
result handed over through `start_new_item_model_import`.

Related tests: `tests/test_new_item_studio_tab.py`.
