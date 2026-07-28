# Format Explorer

**What can I mod, and where do I do it?** — answered inside the app, from the same data
the progress report is built on.

Owners: `tools/format_explorer/catalogue.py`, `tab.py`. Registered as a lazy tool tab in
`cdmw/ui/shell/tool_tabs.py`. Tests: `tests/test_format_explorer.py`.

## Why it exists

`schemas/archive_content_capabilities.v1.json` already records, for all 141 formats, how
far each is read, how far it is written, what the claim rests on and what is left. That
is exactly what a modder needs — and it lived in a JSON file in a schemas directory, so
the people it would help had never seen it.

The panel reads that manifest directly, so it cannot drift from what the code supports.
Every number on screen is computed:

> The game ships 87 file formats and 1,674,781 files. 28 of those formats can be edited
> today, covering 1,275,351 files (76% of everything in the archives).

## What it adds to the manifest

One thing: **which tool edits a format**. That is a property of the app rather than of
the format, so it does not belong in the manifest, but a row saying `.paloc` is read and
writable is only actionable next to "Translation Studio". A test asserts every entry in
that mapping still names a format that exists, so a retired tool cannot leave a dangling
promise.

The manifest's own vocabulary is translated on the way out: `decode: surface` reads as
*Names only*, `write: constrained` as *Limited edits*.

## What it shows

- **Formats the build actually ships, most files first.** The 54 entries the game does
  not contain are one checkbox away rather than in the way — that ordering is the whole
  difference between a reference document and a tool.
- **Extension · Files · What it is · Read · Write · Where to edit it**, with the
  extension cell tinted green when the format can be edited today and amber when it is
  decoded but read-only.
- **Only what I can edit**, a search across extension, area and tool, and an area filter.
- A detail pane for the selected row carrying the manifest's own `evidence` and
  `remaining` text — so "why do you believe that?" and "what is missing?" are always one
  click away, in the words the person who proved it wrote.

## Trap worth recording

The detail pane is refreshed directly after filtering rather than through the selection
signal. When row 0 was already selected before the filter changed, Qt emits nothing, and
the pane went on describing the previous format while the table showed another — a wrong
answer that looked like a right one. A test covers it.
