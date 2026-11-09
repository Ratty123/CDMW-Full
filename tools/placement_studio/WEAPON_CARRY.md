# Carry a weapon somewhere else: design note

Agreed with Fredric on 2026-11-09, including the first slice and two of its decisions (an
unprovable patch blocks the save; weapon socket files stay whole). Written after the Weapon Carry mod (Nexus, DMM) was built by hand on
2026-11-08 and 2026-11-09. The findings it rests on are in
`docs/crimson-desert-research.md`, sections 7.5 (weapon carry) and 12.3 (DMM patch and
partial-file rules). This note says what Placement & Animations should do so that a user can
make that kind of mod without scripts, and what the first slice builds.

## What a user should be able to do

Move a weapon and its sheath to the back or a hip, get draw and sheathe animations whose
hand-off happens when the hand reaches the weapon, cover Kliff, Damiane and female Kliff
(Character Creator Enhanced, Heroine of Pywel), and save one DMM mod that loads next to those
two mods without crashing or silently losing edits.

## What the tab already has (checked in the code)

| Research item | State in the tab |
| --- | --- |
| 1. Placement is the descriptor's `PartInOutSocket` row | Mostly there. `resolver.py` joins rows, body sockets and child sockets; `move_operation.plan_move` re-routes the row (`InSocketBone`, `InChildSocketBone`) and the case row with it, and creates child sockets. Rows are found by `PartName`; the first row wins, so `PartInOutOverride` rows of the same name are not edited by mistake. Missing: the Damiane-side descriptor (female Kliff reads it), and awareness that another mod's copy of the descriptor may have more rows. |
| 2. `.xml.patch` instead of full copies | Missing. `packaging.build_package` writes every edited file whole. A saved mod that edits Kliff's descriptor is merged by position with Character Creator's copy and crashed the game in exactly that case. |
| 3. Timing under each draw and sheathe | Partly there. `paac_events.py` decodes `ModelAttachmentSocket` events and `event_timeline.py` replays them in the preview; `cdmw.core.action_chart_binary.apply_chart_value_edits` can write `event.begin`. Nothing measures the hand-to-carry gap or offers a retime, and nothing lists every chart animation that plays a replaced clip. |
| 4. Mirrored carry for left-handed bodies | Clip side exists (`ClipEdit(mirror=True)` in the animation editor). Socket side (W' = S W S, per body file) is missing. |
| 5. Hip sheath swing | Missing: nothing reads or writes `physicsattachment`. |
| 6. Other installed mods shipping the same files | Missing in this tab. `cdmw.services.dmm_character_mods` already reads the DMM library read-only and can be the source. |

## Screens

One guided panel, opened from **Position > 2. Where it is carried > Carry it somewhere
else...**. It replaces nothing: the replacement workspace (`move_weapon.py`) stays the place
to pick donor clips, and **Your mod** stays the one way out. Each step can be left at its
default.

1. **Weapon.** The item class (a descriptor row such as `MainWeapon_Sword_R`) and the case
   row it names. A table per body shows the file, the row and its In/Out/child/case/bag
   values, and which copy was read (game, Character Creator, Heroine of Pywel). Bodies:
   Kliff, and "Damiane and female Kliff" (one set of files covers both).
2. **Where.** Back (right, left, centre) or hip (left, right), or an existing socket. A new
   body socket is inserted when none fits. A body whose row holds the weapon in the left
   hand gets **Mirror Kliff's carry** by default: the socket solved so the stowed weapon is
   Kliff's reflected across the body's left-right axis. The viewport previews each body.
3. **Draw and sheathe.** One row per chart animation that plays a draw or sheathe of this
   item: chart, animation, clip, the socket event's `begin`, the measured contact time and
   gap. Selecting a row plots the held-to-stowed gap over the clip with the events marked.
   Actions: pick replacement clips (opens the existing workspace; mirrored for a mirrored
   carry), **Move event to contact** for the row, **Move all to contact**. A row whose
   animation ends before contact says so; a clip that never comes within reach is flagged.
4. **Swing** (hip only). **Let it swing** adds the `physicsattachment` item for the chosen
   hip socket (mirrored for a mirrored carry). Off for Damiane by default, since vanilla has
   none for her.
5. **Save.** Goes to **Your mod**. Shared XML is written as DMM patches; rows another mod
   adds through a partial file get a partial file. Lists installed mods that ship the same
   charts or descriptors, and the load order that is needed ("after Character Creator").

## Data flow

```
CarryRequest (rows, destination per body, mirror, swing, retimes)
  -> plan_carry(session, edits, request) -> CarryPlan
       row edits     (descriptor file, row, attribute, old -> new)
       socket edits  (socket file, insert / set)
       clip edits    (target clip <- source, mirrored or not)
       event edits   (chart, animation, event, begin old -> new, measured gap)
       physics items (file, socket, item)
       warnings
  -> one operation in EditSession (existing vocabulary, plus event-begin and physics kinds)
  -> Your mod -> save_mod -> build_for_operations
  -> DMM lowering: patchable XML -> <file>.xml.patch, partial files where needed,
     everything else whole
  -> package (README names every patch and why)
```

The plan is pure and resolved whole before anything is applied, as `plan_move` already is.
Measurements (contact frames, gaps) run on a private session off the UI thread, as the carry
index does.

## Slices

1. **DMM patches for shared XML** (this session). The foundation, and it fixes a crash that
   any mod saved from the tab can cause today.
2. **Timing.** Gap measurement per chart animation, the plot, and event retimes as an
   operation.
3. **Guided carry plan.** The panel's steps 1 and 2 for both bodies, including the mirrored
   socket solve, built on `plan_move`.
4. **Mirrored clips and swing.** Mirrored draw/sheathe clips through `ClipEdit`, and the
   `physicsattachment` item.
5. **Installed-mod awareness.** Read Character Creator's and Heroine of Pywel's copies as the
   base where installed, partial files for rows a partial file adds, conflict warnings, and
   charts built on another mod's copy when it ships one.

## First slice: DMM patches

- New pure module `dmm_patch.py`:
  - `descriptor_patch(base, edited)`: one `<set>`/`<unset>` per changed attribute of each
    `PartInOutSocket` row, found by `find="PartInOutSocket" match-PartName=...` plus the
    first attribute that singles the row out when the name repeats (as in
    `PartInOutOverride`). Ops on an attribute the filter uses go last.
  - `socket_patch(base, edited)`: `<insert into="SocketList">` for added sockets, a
    `<set find="SocketList" attr="Count">` when the count changed, and `<set find="Socket"
    match-Name match-Parent>` per changed attribute, `Parent` last.
  - `apply_patch(base, patch)`: DMM's behaviour as observed (bare element name, ANDed
    `match-*` filters, inserts at the end of the container). Used to prove a patch: every op
    must hit exactly one row, and applying it to the base must give the edited rows.
  - Refuses what a patch cannot express (a removed or reordered row, a new descriptor row),
    with a plain reason.
- Saving for DMM lowers character descriptors (`characterdescription/*.xml` and the root
  alias) and body socket files (`*.pab.sockets.xml`) to `.xml.patch`. Weapon socket files,
  prefabs, clips and charts stay whole files: they belong to the item, and full copies of
  them are what the in-game mod shipped. A file whose patch cannot be proven blocks the save
  with the reason rather than falling back to a full copy.
- The manifest and README name the patch files; `inspect_package` reads a patch by applying
  it to the baseline.
- Tests on owned fixtures: patch generation, DMM-style application, duplicate row names,
  attribute-order cases, refusals, and a save that writes patches. No game files.

Status, 2026-11-09: built as described, with `tests/test_placement_studio_dmm_patch.py`.
`build_package(dmm_xml_patches=False)` keeps full copies for the corpus gate, which
reproduces the old golden mods' own layout. One rule is carried over from the reference
script used for the shipped mod rather than seen in a DMM log: a `<set>` on an attribute the
row lacks adds it (the tab does this when a row has no `InChildSocketBone`, for example).

Not in this slice: partial files, other mods' copies as the base, timing, mirroring, swing,
and the panel itself.

## Second slice: timing

Built on 2026-11-09, with `tests/test_placement_studio_carry_timing.py`.

- `carry_timing.py` (pure): `swap_events` lists the `ModelAttachmentSocket` hand-offs of one
  row in draw and sheathe animations, addressed as chart, animation and event index.
  `gap_curve` poses a session on every frame and measures the held weapon
  (`inverse(out child) * out socket`) against the carried one (`inverse(in child) * in
  socket`). `decide` follows the rules of the shipped retimes: contact is the nearest frame
  inside the stretch the animation plays, at least one frame before it ends; a gap above
  0.35 m keeps the event's time, and so does a hand-off at the start of the played stretch;
  within 0.05 s is on time. Within 0.20 m is a sure contact; 0.20 to 0.35 m "nearly
  reaches" and moves only when selected. Clips made for another rig are left out. `survey` measures each clip and
  row once, however many animations play it.
- `EditSession.retime_event` records an `event_begin` command (only `ModelAttachmentSocket`
  events, only inside the played stretch). A `retime_events` operation's scope names each
  event it may move (`allowed_chart_events`), and the preflight refuses any moved event no
  selected operation declared. `ops.derive_file` reads a retimed chart as tier C
  `paac_event_begin` operations (four bytes each) instead of an opaque file, and `replay`
  reproduces it.
- **Animations > Draw and put-away timing**: **Measure timing** runs the survey for the
  selected slot on a private session off the UI thread, with every pending change (moved
  attach points, replaced clips). The table shows each hand-off with its status; the plot
  shows the gap with the played stretch, the current hand-off and the contact. **Move
  selected to contact** and **Move all to contact** (sure contacts only) record one timing
  operation per slot;
  moving more later replaces it. A measurement is refused once the history, character, slot
  or weapon has changed.
- Charts ship whole. The panel and the README say that DMM serves one copy of each chart, so
  the mod has to load after another mod that ships the same chart.

Checked on real clips on 2026-11-09 against the research measurement and the shipped Timing
package of Weapon Carry 1.0.1 (Kliff, male parts): all 97 hand-offs have the same contact and
gap, and every proposed time equals the shipped one. The check exposed looser rules on clips
the package does not ship, which led to the at-start, sure-contact and rig rules above. The
scripts and results are in the worktree's `.work/research/2026-11-09-timing-check/`.

Not in this slice: slot-addressed events (dual wield), mode 2 events, speed windows, Kliff's
charts in a Damiane session (slice 3), and starting from another mod's copy of a chart
(slice 5). Help and the 13 translations of the panel's text are pending, and nothing has been
tried in game. The patch result is source and fixture evidence only; DMM 4.7.4 and the
game accepted hand-written patches of the same form on 2026-11-08, but patches written by the
tab have not been mounted yet.
