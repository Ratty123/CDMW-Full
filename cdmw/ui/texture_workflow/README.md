# Textures

Owns the unified **Authoring > Textures** workspace, with one asset list and job.
`TexturesWorkspace` reuses the existing editor for Edit sessions, layers, and history;
Recolor keeps package/ZIP analysis and material-color rules; Upscale reuses the existing
batch pipeline. Replace exposes bulk matching and mod-package output directly. Review &
Export retains native DDS, PNG, project, recolor, and upscale outputs; its Replacement
matches shortcut opens Replace. Recolor previews use the editor canvas's zoom and
original/split views without changing the document or its undo history.

Remove closes the active asset in the job; it does not delete the source file. Upscale
automatically widens the sidebar when opened or expanded and adjusts it on window resize
while retaining space for the preview. The sidebar follows the expanded controls' width
and selected font size; the Upscale preview can shrink to leave controls accessible on
narrower windows. Asset Authoring path labels stack above their fields and Browse
buttons. The profile and rule tables open in their own editor through **Workflow
Profiles, Rules & Matches > Edit**.

Lazy panels restore their saved settings when first opened.

## Brush strokes

Brush stamps keep their spacing across mouse events, and brush strokes include
the release position when it is inside the image. Flow honours values below 5%
and retains fractional stamp strength when combined with lower opacity. The same
spacing and flow rules apply to Quick Mask. Painting still commits one history
step on release. Undo and Redo buttons update immediately after strokes and
history navigation, including the incremental canvas refresh path.

## Editable filters and replacement inputs

Editable texture filters and chaiNNer override JSON preserve all entered lines
and support Undo. Recolor source changes invalidate the previous analysis and
preview; a package must be analysed for the current source before Build can run.
Ready-mod preflight reports each selected output profile before conversion.

**Replace** accepts loose PNG/DDS files without opening editor documents or
decoding them for the queue. **Open Folder** recursively replaces the current
shared texture job; **Reload Folder** repeats the last successful folder load,
including external file changes, additions, and deletions. **Add Files** appends
unique paths. Same-name files in different folders remain separate. Empty,
failed, or cancelled scans keep the previous batch. Package settings and earlier
output remain available across reloads.

## Queue inclusion and output

Queue checkboxes control export inclusion; highlighted rows control **Remove Selected**.
**Clear All** clears the shared job. Bulk removal/reset asks once before closing
existing editor documents, never deletes sources or built packages, and does not load
each intervening document. **Open in Editor** deliberately opens one asset; returning to
Replace preserves its edits, history, and matched original. Auto-Match remains explicit,
and unresolved originals must be chosen before building. Choose **Game archives** or
**Local DDS folder** beside **Auto-Match originals**. **Choose Folder...** selects a
whole local originals folder, including subfolders;

Auto-Match retries see newly added originals. The **Selected file** row's **Choose Local
DDS...** and **Choose Archive DDS...** assign one original to one replacement. Replace
has its own import, matching, and build controls; Edit's Add Textures, Add Mod, and
Review & Export actions are hidden in this mode. File-only builds read the current
source files through the existing package builder; DDS encoding policy is unchanged.
Edited sessions export their current flattened image.

## Standalone texture .cditem packages

**Authoring > Textures > Texture .cditem...** opens the package editor in every
texture mode. Choose the game archive folder, filter and **Find existing textures**,
then select an existing registered target. Choose a prepared replacement DDS,
review the affected path, package UUID and source/replacement hashes, and write
the portable `.cditem` outside the game archive folder. Search returns at most
200 paths and reports the total so a broad filter can be refined.

The `texture.replace@1` adapter accepts existing direct texture entries whose
complete DDS descriptor and raw mip layout are supported. The replacement must
retain all source header bytes, dimensions, format and mip layout; every mip is
decoded during validation. This workflow creates no item IDs or texture registry
entries. Layout changes, unregistered/new paths and unsupported DDS/storage
layouts are refused with a reason.

For an update, **Load package to update...** selects the existing artifact and
its expected digest before review. This editor updates one texture target,
retains that target, UUID, module ID and envelope metadata, and writes to the
selected package path. The previous package must still validate against the
current exact original source and texture registry. Reauthoring across changed
game inputs requires a separate reviewed compatibility step. Combined modules,
multiple texture targets and additional dependencies require their owning editor.

Discovery, package reads, full texture validation and package writing use the
existing shared background controller. Review pins the original source/indexes,
registry, local replacement bytes and selected update artifact. The existing
writer reads back its staged package and checks these inputs again before atomic
publication. Failure or cancellation before publication preserves prior output;
cancellation after publication reports the committed file. Closing the dialog
requests cancellation and leaves native thread cleanup with its shared owner.

Import the written package through **Mods** for the applicable install/update
review. Authoring and owned-fixture tests establish package/compiler behavior;
rendering, visual parity and live-game behavior require separate game evidence.

## Worker snapshots and publication

Workers receive immutable snapshots. Revisions, original DDS identity, exact target
matches, and cancellation are checked before accepting results. Batch output is
staged and transactionally published; a failed or cancelled job keeps prior output.
Ready ZIP filenames append `.zip` to the complete mod folder name, preserving
dots and manager suffixes so each manager output keeps its own ZIP.
Sources may be loose DDS files, mod folders/ZIPs, or exact archive matches. Extraction
and image processing run off the UI thread and never mutate PAMT/PAZ archives.

## Navigation compatibility and owners

`textures` is the canonical navigation key. `texture_editor`, `recolor_variants`,
`texture_workflow`, and `replace_assistant` remain handoff aliases for Edit, Recolor,
Upscale, and Replace. `ui/textures_mode` restores the last mode, falling
back to Edit. Both shell layouts use this same widget and job.
Mode buttons use the shared theme's hover, pressed and selected states. Controls
remain inside their stacked page while loading, so switching modes cannot expose
a second panel over the active one.

## Mesh-linked texture updates

Mesh-linked base/albedo documents defer resident dirty-region production until
after the edit handler returns. The producer uses the composite cache, emits a
tight BGRA8 patch, and leases the emitted composite read-only until the Mesh
Editor worker copies it. A racing dirty edit uses copy-on-write, while the
session's original flattened RGBA remains immutable.
