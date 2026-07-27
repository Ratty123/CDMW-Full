# `posemodifierdata.xml` — the rig behaviour the game actually runs

`character/descriptors/posemodifierdata/posemodifierdata.xml`, 119 KB, 2,779 settings
across 98 skeletons. It is where the engine keeps how far a creature turns its head to
look at you, how much a spine lags behind a turn, the reach and bending axis of each IK
limb, and the wheel radii and suspension travel on every cart.

This one is **demonstrably live**, which is the point of it. The engine's own
`pa::engineScript::PoseModifier*` classes — visible in the executable's RTTI names — are
named after its sections. That is the opposite of `.papr`, which nothing in the shipped
binaries appears to read (see `docs/features/localization-and-constraint-formats.md`).

Owners: `cdmw/core/posemodifier_xml.py` for the format,
`tools/placement_studio/rig_behaviour.py` for the per-skeleton view and the mod payload,
`tools/placement_studio/window_rig_behaviour.py` for the panel. Tests:
`tests/test_posemodifier_xml.py`, `tests/test_placement_studio_rig_behaviour.py`.

## The sections

| Section | What it governs |
|---|---|
| `LookAt` | Head and eye tracking — yaw and pitch ranges, when the character gives up |
| `AimIK` | How far the body turns to aim, and per-bone `AlignWeight` |
| `SpineTrain` | Spine lag and follow-through on a turn: `RotationScale`, `DampingCoeff`, `MaxYawDiff`, per-bone roll |
| `RootBoneIK` | Whole-body lean and tilt when moving or on a slope |
| `LimbIK` | Arm and leg IK: bending axis, source and target bones, Jacobian solver descriptors |
| `Multileg` | Many-legged gait: hips, knees, ankles, foot planting, sweep distances |
| `Vehicle` | Carts and mounts: chassis, wheel radius and width, suspension travel, yaw and pitch limits |
| `Harness`, `FishingRod`, `BoneAim`, `WorldSpaceSpecificBoneModifier` | Smaller single-purpose modifiers |

## Why this does not use an XML parser

The file is not one XML document and is not well formed:

- **eleven** `<PoseModifierDataList>` root elements, one after another;
- **nine** anonymous `</>` closing tags;
- a UTF-8 BOM and no XML declaration;
- 24 comments, several of them Korean labels naming the vehicle a block belongs to
  (`<!-- 순환마차 -->`) — the only human-readable identification a block has.

`ElementTree` refuses it outright with *junk after document element*. Running it through
a tolerant parser and re-serialising would fix it into strict XML, drop the comments, and
rewrite the hand-authored tabs: thousands of changed bytes, no benefit, and some risk
against an engine parser whose tolerances are unknown.

So the reader **scans rather than parses**, records the character span of every value,
and edits by patching those spans. An unedited document re-emits its source exactly —
verified byte-for-byte against the shipped file — and an edited one differs only inside
the values that changed. Editing one number in the real file produces a one-byte length
delta and exactly one changed setting.

Two details the editor keeps that a re-serialiser would not:

- **Number style.** `-60.0` halved is written `-30.0`, not `-30`. The file is hand
  authored and a diff should not carry reformatting nobody asked for.
- **Value shape.** A range is `-45 57` and a vector is `8 8 30`. Scaling multiplies every
  number and keeps the separators, rather than collapsing a range to one value.

## The panel

**Rig behaviour**, in the Placement & Animation Studio, because the file is keyed by
`.pab` skeleton and the Studio already knows which character is loaded. Selecting the
player shows the 223 settings that apply to it rather than all 2,779.

Three things it insists on:

- **Which rig you are editing.** The skeleton picker drives everything, and it offers
  every skeleton in the file.
- **Who else you are affecting.** One block commonly serves several characters — the
  player's `LookAt` block is shared with `phw_01`, `ptm_01` and `pdem_01`. The
  *Applies to* column and the selection line name them, because that is a consequence
  the file does not show and a modder would not expect.
- **When a section is switched off.** Each section can carry a `DisabledKeyList`.
  Editing `LookAt` for a creature listed there does nothing and explains nothing, so the
  panel shows a banner. A skeleton that appears *only* in a disabled list is still
  selectable — that is precisely the character whose owner needs to be told.

Values are edited as text with `×2`, `×1.5` and `÷2` for numeric ones, an *Apply* that
validates, and a *Reset all*. Anything that would break the markup is refused. Export
writes one package per manager through the Studio's packager and is disabled until
something changes.
