# Translation Studio

Every line of text in the game, searchable and retranslatable, exported as a mod.

`.paloc` has been readable and writable for a while — 14 languages, 187,521 lines each,
byte-exact round trip. But there was no way to reach it from the app, so the one format
where an edit provably **cannot** corrupt anything was also the one nobody could use.
This is the missing half.

Owners: `tools/translation_studio/catalogue.py` (domain), `table_model.py` (the
virtualised table), `tab.py` (the panel), over `cdmw/core/paloc_format.py`. Registered as
a lazy tool tab in `cdmw/ui/shell/tool_tabs.py`. Tests: `tests/test_translation_studio.py`.

## Why an edit here is safe

Nothing in `.paloc` is offset-addressed, aligned, or checksummed: it is a flat run of
`(category, key, text)` records with the count in a footer. A translated line may be any
length and rewriting the table is just re-emitting the records. That makes this the
lowest-risk modding surface in the game — and the highest-volume one, since translations,
renamed items and rewritten quest text are all the same operation.

## What the data shape dictates

**Search first, browse never.** 187,521 lines is not a list anyone scrolls, so the panel
opens on a search box. Search is a plain case-insensitive scan over key and text, which
filters the whole table in about 32 ms — faster than a keystroke. An index would need
building, invalidating on every edit and keeping correct, and would buy nothing a person
could perceive.

**A virtualised model, not a widget table.** `QTableWidget` would build 187,521 row
widgets up front. `QAbstractTableModel` builds nothing and answers only for the cells on
screen: the model is ready in 96 ms and a filter swap costs about 1 ms. The model holds a
*view* — a tuple of entry indexes — so filtering never touches the underlying table.

**One language in memory, plus one reference.** The tables are 16–25 MB each; loading all
fourteen would cost 250 MB for a feature nobody uses at once. One working language and
one optional reference is what a translator actually needs.

**Edits held apart from the table.** A pass touches a handful of lines out of 187,521, so
edits live in their own small mapping and fold into the document only on export. That
keeps "what have I changed" answerable, and Reset free.

## The panel

- **Language** and **Show alongside** pickers, then Load. Reading happens on a worker;
  a 16 MB table must not stall the UI thread.
- **Find**, a **Group** filter (the category ids, labelled from the data), and **Edited
  only**. Results are capped at 5,000 — nobody reads 90,000 hits, and building that view
  costs more than the search.
- **Key · Group · Text · Reference**. Text is editable in place by double-click; the
  other three are not.
- **Edited rows are highlighted**, and the shipped text stays in the cell's tooltip so
  the original is never lost from view.
- **Revert line** and **Reset all**, then mod name/author and one Export button that
  writes a package per manager. Disabled until something changes.

The reference column is the feature that makes this a translation tool rather than a
string editor: translating into Polish means reading the English, and proofreading a fan
translation means reading the Korean original. Only the key-to-text mapping is kept, not
a second editable table.

## Trap worth recording

The filter handler reconnected `selectionChanged` on every refresh, which stacked one
duplicate slot per keystroke. The connection belongs with `setModel`, which is what
replaces the selection model. A test asserts the receiver count does not grow while
filtering, because nothing else about the UI would have looked wrong.
