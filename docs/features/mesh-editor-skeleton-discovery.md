# Mesh Editor Skeleton Discovery

This note records read-only discovery from the local Crimson Desert install at
`C:\games\Steam\steamapps\common\Crimson Desert`. The inspection parsed `.pamt`
indexes and read only targeted `.paz` entries through existing archive helpers;
no archive payloads were modified or broadly extracted.

## Index Shape

Character mesh and skeleton assets are concentrated in package group `0009`.
The sampled index contained:

- `12,882` character `.pac` meshes
- `254` character `.pab` skeletons
- `456` character `.pabc` skeleton variations
- `2,606` character `.prefabdata_xml` descriptors
- `5,639` character `.app_xml` descriptors

Shard spot checks on 2026-06-29 found `0009\0.paz` contains character
`.prefab` binaries and `.pac` meshes, while `0009` `.prefabdata_xml`
descriptors are mostly in `36.paz`. DDS texture sources were not present in
`0009\0.paz`; they resolve through the same package index to later shards such
as `35.paz` and should be materialized through the archive preview cache instead
of broad extraction. `0000\0.paz` did not contain `.prefab` entries in this
scan; object `.prefab` entries in `0000` were in later shards.

## Relationship Rules

- `.pac` stores skinned mesh geometry plus local bone indices/weights. Some
  skinned PAC payloads contain PAB bone-hash palette evidence, but the parsed
  mesh alone is not enough to recover the full armature.
- `.pab` stores the skeleton/armature. Character assets usually do not use a
  same-basename PAB. Player equipment often resolves to a class skeleton such
  as `phm_01.pab`, `phw_01.pab`, or `ptm_01.pab`; monsters usually resolve to a
  family skeleton in the same monster folder.
- `.pabc` stores skeleton variation/bind-pose metadata under
  `character/binary/skeletonvariation/...`. The current parser treats real
  samples as `PAR` payloads with a count at `0x10`, records starting at `0x14`,
  a `196` byte stride, a PAB bone hash at each record start, and three 4x4 float
  blocks per record. The float-block semantics are still read-only.
- `.prefabdata_xml` is the strongest explicit relationship source when present.
  It can declare `SkeletonName`, `SkeletonVariationName`,
  `AnimationConstraintName`, and `SocketFileName`.
- `character/identityskeleton.pab` is a weak fallback. If a skinned mesh only
  resolves to that generic skeleton, the Mesh Editor should show unresolved or
  low-confidence skeleton metadata instead of enabling character posing.

## Sample Evidence

- `character/skinnedmesh_box.pac` resolved to
  `character/skinnedmesh_box.pab` with palette confidence, `2` bones, and `1`
  contiguous palette bone-hash hit.
- `character/model/1_pc/14_ptm/armor/10_lowerbody/cd_ptm_01_lb_0002.pac`
  resolved to `character/model/1_pc/14_ptm/ptm_01.pab` with palette confidence,
  `425` bones, and `41` contiguous palette bone-hash hits. The generic
  `identityskeleton.pab` also matched by basename fallback, but had no palette
  hits.
- `character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_artis/`
  `cd_m0001_00_artis_0001_hair.pac` resolved to sibling family skeleton
  `cd_m0001_00_artis.pab` with palette confidence, `418` bones, and `170`
  contiguous palette bone-hash hits.
- `character/prefab/1_pc/10_pgw/nude/cd_pgw_00_nude_00_0001.prefabdata_xml`
  declared `SkeletonName FileName="1_pc/2_phw/phw_01.pab"` and
  `SkeletonVariationName FileName="1_PC/10_PGW/Nude/CD_PGW_00_Nude_00_0001.pabc"`.
  The mesh-only resolver otherwise found only `identityskeleton.pab`, so
  descriptor metadata must override weak heuristic fallback.
- `character/prefab/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.prefabdata_xml`
  declared `SkeletonName FileName="1_pc/14_ptm/ptm_01.pab"`,
  `SkeletonVariationName FileName="1_PC/14_PTM/Nude/CD_PTM_00_Nude_00_0001.pabc"`,
  `AnimationConstraintName FileName="1_pc/14_ptm/ptm_01.papr"`, and
  `SocketFileName FileName="1_pc/14_ptm/PTM_01.pab.sockets.xml"`.
- A read-only Mesh Editor rigging smoke on 2026-06-29 resolved and parsed both
  `cd_ptm_00_nude_00_0001.pac` and `cd_pgw_00_nude_00_0001.pac` with
  descriptor confidence, surfaced their PABC paths, loaded `425`/`448` PAB
  bones, and produced changed preview vertices from a small service pose.
  Repeat with:
  `.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-rigging-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-rigging"`.
- A read-only Mesh Editor app-workflow smoke on 2026-06-29 parsed local
  `0009\0.pamt`, opened `cd_ptm_00_nude_00_0001.pac` in an offscreen
  `MeshEditorTab`, attached descriptor-resolved PAB/PABC/PAPR/socket metadata,
  drove the Skeleton panel pose controls, and verified preview deformation
  while leaving unconstrained raw animation playback blocked. Repeat with:
  `.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-app-workflow-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-app-workflow"`.
- A read-only animation-binding smoke on 2026-06-29 resolved the same PTM PAC
  through descriptor metadata, parsed the linked PABC as `411` records that all
  match loaded PAB bone hashes, sampled real `.paa` payloads from the class
  motion set and related player clips, found `308,470` `.paa` entries but no
  `.paseq` entries in `0009`, and bound `233` exact PAB-hash-owned PAA tracks
  across the sampled payloads. The selected PAA clip drove preview-only
  deformation through `MeshService`. Repeat with:
  `.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-animation-binding-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-animation"`.
- A read-only sequence-binding smoke on 2026-06-29 scanned all `33` local PAMT
  indexes and found sequence assets only in package `0014`: `4,677` `.paseq`,
  `2,935` `.paseqc`, `3,318` `.pastage`, `4,143` `.paschedule`, and `3,619`
  `.paschedulepath` entries. The sampled
  `sequencer/binary__/stageseq/abyssone/cd_seq_abyss_miseenscene_0003.paseqc`
  exposes PTM PAA lane references and resolves
  `character/motion/1_pc/14_ptm/01_npc/cd_ptm_backpack_00_00_nor_std_idle_ing_03.paa`
  against `character/model/1_pc/14_ptm/ptm_01.pab`, binding `46` exact
  PAB-hash-owned tracks and `3,018` keyframes. A grouped payload scan read all
  `18,692` sequence-family entries and found `8,355` `_framesPerSecond` field
  names plus `7,093` float `30.0` values; the sampled compiled `.paseqc` has no
  FPS field name, but its same-stem `.paseq` source declares `_framesPerSecond`
  as an `int32` field.
  The same smoke now reads all `20` `.papr` entries successfully as
  `ChaCha20,LZ4` `PAR` payloads after treating `.papr` as structured binary
  archive data. PAPR read-only constraint evidence now classifies `4,055`
  readable constraint strings, `545` inferred nearby-string record candidates,
  and `16` related physics references across those files; the PTM sample
  contributes `297` strings (`160` bone references, `47` helper bones, `19`
  parent bones, `51` driver expressions, `20` limit expressions), `65` record
  candidates, plus one related HKX reference. Record layout, value offsets, and
  solver binding remain unproven. The all-local-PAPR corpus also reports
  `434` driver expressions, `111` limit expressions, channels
  `Local_Euler_Z=334`, `Local_Euler_Y=187`, `Local_Euler_X=24`, limit operators
  `amin=91`, `amax=20`, `1,177` numeric constants, and decoded string offsets
  for candidate fields `target=493`, `helper=232`, `parent=221`. Candidate
  family classification across the same corpus reports `434`
  `driver_expression_candidate` rows and `111`
  `local_transform_limit_candidate` rows, all with
  `blocked_record_layout_unproven`. Family/channel cross-tabs split driver rows
  into `Local_Euler_Z=256`, `Local_Euler_Y=169`, `Local_Euler_X=9`, and local
  transform limit rows into `Local_Euler_Z=78`, `Local_Euler_Y=18`,
  `Local_Euler_X=15`; limit operators stay isolated to the limit family as
  `amin=91`, `amax=20`. A 2026-06-29 rerun also reported
  active sequence lane `1`, `46`
  sampled playback bones, preview pose deformation, unchanged edit-session export
  geometry, deterministic repeated same-time scrub output, and unproven
  `frame_rate_unproven` timing. The same smoke now
  compares same-stem source and compiled clip references: source `.paseq` has
  `3` PAA refs, compiled `.paseqc` has `2`, both compiled refs overlap source
  refs including the active PTM clip, and one source-only PHM idle ref remains
  extra read-only evidence. The overlapping lane pairs are now explicit: PHM
  source lane `0` at offset `21702` maps to compiled lane `0` at offset `11018`,
  and the active PTM source lane `2` at offset `22031` maps to compiled lane
  `1` at offset `11402`. Same-stem event-marker string overlap is also explicit:
  source marker evidence is capped at `64` rows, compiled marker evidence has
  `39`, and `14` strings overlap, including `_startTimePiece`,
  `_endTimePiece`, `_hasTransformBlend`, `GameData_TimelineEvent_BodyAnimation`,
  `SequencerGamePlayDataEventKey`, `_connectTrigger`, and `_triggerTagList`.
  This is readable string overlap, not executable event semantics. Same-stem
  unique timeline field overlap is also explicit: source has `173` unique field
  names, compiled has `87`, and `45` overlap, including `_startTimePiece`,
  `_endTimePiece`, `_startOffsetTimePiece`, `_endOffsetTimePiece`,
  `_hasTransformBlend`, and `_startOffset`. `_framesPerSecond`,
  `_startBlendingTime`, and `_endBlendingTime` remain source-only, while
  `_startBlendTime` and `_autoMovingBlend` are compiled-only related evidence
  but not proven value bindings. Alias comparison finds one source/compiled
  timing-field alias: `_startBlendingTime` at source offset `15775` to compiled
  `_startBlendTime` at offset `1678`, both `float`, with
  `inferred_name_alias_value_unbound` confidence. `_endBlendingTime` remains
  unmatched. Active-lane byte-window context is now also captured for the PTM
  clip path: source path text at offset `22031` has eight nearby
  length-prefixed strings and two `u32 30` rows that are string lengths, while
  compiled path text at offset `11402` has only the length-prefixed path, zero
  FPS-like `u32` rows, zero aligned nonzero `float32` rows, and opaque aligned
  `u32` rows such as `1024`, `2048`, `111`, `2`, `2304`, `257`, and `45`.
  Binding remains `active_lane_record_layout_unbound`, so lane start/blend
  values are still not proven. The same-stem source timing evidence now records
  two proven
  `_framesPerSecond:int32` declarations at offsets `307` and `3891`, two
  aligned `u32 30` candidates, no
  `float32 30`, and an explicit
  `source_paseq_fps_field_declared_value_offset_unmapped` proof gap. Timing
  evidence now also lists post-declaration candidate rows for the same source:
  candidate region start `0x51F9`, `u32 30` at `0x55D8`, `u32 30` at `0x5664`,
  `u32 24` at `0x6104`, and `u32 15` at `0x77E4`. The two `u32 30` rows are
  blocked as length-prefixed string context, not FPS bindings; the `24` and `15`
  rows remain unbound binary scalar candidates.
  The same source also reports eight proven blend-related field declarations,
  including `_startBlendingTime` and `_endBlendingTime`, with value binding still
  unknown and status `blend_fields_declared_value_offsets_unmapped`. Blend
  candidate value sampling now records the same post-declaration region start
  `0x51F9`, `32` nonzero aligned `float32` candidate rows, and first offsets
  `0x5358`, `0x5720`, `0x5820`, `0x5824`; all remain unbound binary scalar
  candidates with unknown value confidence. Repeat with:
  `.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-sequence-binding-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-sequence"`.
- A real app workflow rerun on 2026-06-29 passes parsed PTM PAPR metadata into
  the Mesh Editor Skeleton panel without UI-side PAPR parsing. The panel reports
  `read_only_constraint_string_evidence | 297 strings | 65 record candidates | 1 physics refs | solver blocked`
  and now exposes six disabled raw candidate rows such as
  `driver_expression_candidate` and `local_transform_limit_candidate`, all with
  `blocked_record_layout_unproven`. The same rows bind readable bone names to
  attached PAB indices by exact name when possible, and bind numeric suffix
  variants to an existing base name with lower `suffix_base_name` confidence.
  Parent-role `P_` prefixes are stripped only when the base bone exists in the
  attached skeleton, with `prefix_base_name` confidence.
  Real examples include `Bip01 L Foot:1:2 (#49 suffix_base_name)`,
  `Bip01 L Calf:1:2 (#27 suffix_base_name)`, and
  `Bip01 L Ankle (#51 exact_name)`. The all-available-row coverage summary
  reports
  `65 candidate rows | target exact_name=37 | target suffix_base_name=22 | helper exact_name=36 | parent prefix_base_name=25 | parent unmatched=7`,
  so unresolved parent roles stay explicit. Pose preview still changes preview
  geometry only.
- PAPR expression strings now carry separate read-only token evidence. The real
  PTM app workflow smoke reports
  `readable_expression_tokens_solver_semantics_unknown | tokens proven | semantics unknown | role driver_expression=49 | channel Local_Euler_Z=39 | channel Local_Euler_Y=24 | role limit_expression=16 | limit amin=14 | channel Local_Euler_X=2 | limit amax=2 | numeric constants=151`.
  These are readable expression tokens only; solver semantics remain unknown.
- PAPR candidate rows also carry decoded string offsets for the readable fields
  that formed each inferred candidate. The real PTM app workflow smoke reports
  `readable_string_offsets_candidate_record_map | offsets proven | record inferred_nearby_string_order | target=59 | helper=36 | parent=32`.
  These offsets are proven decoded-payload string offsets, not proven binary
  record value offsets.
- The Skeleton panel solver-readiness row stays blocked and makes the blocking
  proof gaps explicit. The real PTM app workflow smoke reports
  `solver_blocked_until_record_layout_and_expression_semantics_proven | candidates=65 | solver ready=0 | target bound=59 | helper bound=36 | parent bound=25 | record layout unproven=65 | expression semantics unknown=65`.
- The same panel now separates inferred candidate families from readable-string
  role counts. The PTM app workflow reports
  `driver_expression_candidate=49 | local_transform_limit_candidate=16`, both
  disabled until record layout and expression semantics are proven.
- Per-family readiness rows keep those blockers visible before solver work. The
  PTM driver expression family reports `49` candidates, `45` target-bound,
  `24` helper-bound, and `19` parent-bound rows; the local transform limit
  family reports `16` candidates, `14` target-bound, `12` helper-bound, and `6`
  parent-bound rows. Both report `solver ready=0`, all records layout-unproven,
  and all expression semantics unknown.
- Visible disabled candidate rows also show per-record token evidence. The real
  PTM app workflow requires rows with proven `Local_Euler_Z` channel tokens,
  proven `amin` limit-operator tokens, numeric constant counts, and explicit
  `semantics unknown`, without enabling constraint solving.
- Visible disabled candidate rows now also expose parser-provided decoded string
  offsets such as expression and target/helper/parent string positions. The real
  PTM app workflow requires `proven_decoded_string_offsets` in those rows, but
  these remain decoded-payload string offsets rather than proven binary record
  value offsets.
- PAPR candidate rows now also expose inferred readable-string span bounds. The
  all-local-PAPR smoke guards `545` rows with
  `nearby_string_span_only_value_layout_unproven` layout status and max span
  size `795` bytes. The first PTM row spans decoded offsets `212` to `371`
  across parent, helper, target, and expression strings. These spans are useful
  record-shape evidence, not proven value offsets or fixed binary record layout.
- The same rows now expose decoded-string field order. The all-local-PAPR smoke
  reports ordered coverage for all `545` inferred candidates:
  `helper>target>expression=167`, `target>expression=157`,
  `parent>target>expression=100`, `parent>helper>target>expression=65`,
  `parent>expression=52`, and `target>parent>expression=4`. Field order is
  proven from decoded string offsets inside inferred nearby-string candidates;
  binary value offsets, weights, enable flags, and solver semantics remain
  unproven.
- PAPR expression strings now also carry syntax-shape labels. The all-local-PAPR
  smoke reports `linear_channel_transform_candidate=374`,
  `absolute_channel_transform_candidate=55`,
  `limit_linear_channel_transform_candidate=96`,
  `limit_absolute_channel_transform_candidate=15`, and
  `channel_reference_expression_candidate=5`. These labels come from readable
  expression text only; runtime evaluation order, units, clamps, weights, enable
  flags, and solver behavior remain unproven.
- Readable PAPR formulas now also carry syntax signatures combining expression
  role, shape, channel sequence, limit operators, and numeric-role sequence.
  Across all local PAPR candidates, `545` expressions produce `28` unique
  syntax signatures. The most common driver signatures are `Local_Euler_Z`
  coefficient-plus-offset with `125` hits and `Local_Euler_Y`
  coefficient-plus-offset with `109` hits; the most common limit signature is
  `Local_Euler_Z amin` coefficient-plus-offset-plus-limit-argument with `38`
  hits. The PTM app row reports `17` unique syntax signatures. These are
  grouping hints only; solver evaluation order and units remain unknown.
- PAPR candidate rows also classify bytes between decoded string fields. The
  all-local-PAPR smoke reports `946` adjacent field pairs split into
  `binary_gap=757`, `overlap_or_shared_string=179`, `printable_ascii_gap=5`,
  and `zero_padding=5`; `544` candidates have
  `binary_like_interfield_gap_bytes_unbound`, one has
  `printable_interfield_gap_bytes_unbound`, and max gap size is `741` bytes.
  This is record-layout evidence only; value offsets and solver semantics remain
  unbound.
- The same gap scan now reports unbound aligned scalar candidates. Across all
  local PAPR candidates, `26,169` aligned words contain `3,472` plausible scalar
  hints in `498` rows: `f32_unit_candidate=1,433`,
  `f32_angle_candidate=1,201`, `u32_u16_candidate=532`, `zero_word=187`,
  `f32_small_candidate=75`, `u32_u8_candidate=42`, and
  `u32_bool_candidate=2`, with `35` max scalar hints in one row. These are
  candidate value-offset search hints, not bound weights or enable flags.
- Numeric constants inside those readable PAPR expressions now carry
  syntax-inferred roles. The all-local-PAPR smoke reports
  `channel_coefficient=460`, `additive_offset=455`, `limit_argument=111`,
  `channel_divisor=75`, and `numeric_constant=76` across `1,177` values. These
  roles do not prove binary value offsets or expression evaluation semantics.
- Numeric-text-to-gap-scalar comparisons now report unbound match hints.
  Across all local PAPR candidates, `26` rows contain `60` matches split
  into `limit_argument=31`, `channel_coefficient=18`, and `additive_offset=11`;
  storage splits `f32=55`, `u32=5`, and scalar kinds split
  `f32_unit_candidate=27`, `u32_u16_candidate=26`, `zero_word=5`, and
  `f32_small_candidate=2`, with max `5` matches in one row. Pair locations are
  `parent>target=29`, `parent>expression=18`, `parent>helper=12`, and
  `target>expression=1`. Family coverage is `driver_expression_candidate=18`
  matches across `11` rows and `local_transform_limit_candidate=42` matches
  across `15` rows. The PTM app workflow shows an aggregate Skeleton panel row
  with `10` unbound text/scalar numeric matches split evenly by family and
  across `parent>expression=5`, `parent>helper=2`, and `parent>target=3`.
  Nested family role/pair totals show all `18` driver-expression matches are
  `channel_coefficient`, split across `parent>expression=3`,
  `parent>helper=12`, and `parent>target=3`; local transform limit matches
  split into `additive_offset=11` and `limit_argument=31`, across
  `parent>expression=15`, `parent>target=26`, and `target>expression=1`.
  The PTM app row mirrors that shape with driver `channel_coefficient=5` across
  `parent>expression=2`, `parent>helper=2`, and `parent>target=1`, and limit
  `limit_argument=5` across `parent>expression=3` and `parent>target=2`.
  Value-confidence totals are explicit: all `60` matches split into `35`
  approximate float32 matches, `20` exact float32 matches, and `5` exact u32
  matches; by inferred family, driver-expression matches split into `2`
  approximate float32 and `16` exact float32, while local transform limit
  matches split into `33` approximate float32, `4` exact float32, and `5` exact
  u32. The PTM app row reports `6`, `3`, and `1` overall, with driver
  `2`/`3` approximate/exact float32 and limit `4` approximate float32 plus
  `1` exact u32. These remain value-offset search hints, not bound record fields
  or solver semantics.
- Those numeric/scalar match hints now include gap-relative offset
  distances. Across all local PAPR candidates, the `60` matches span previous
  decoded-field-end deltas `1..387` and next decoded-field-start deltas
  `2..611`, with `30` previous-delta buckets and `34` next-delta buckets. The
  PTM app row reports previous-delta range `11..380` and next-delta range
  `5..611`. These distances narrow offset searches only; they still do not bind
  weights, enable flags, expression semantics, or solver application.
- Numeric/scalar match hints also emit compact signatures that combine inferred
  family, role, field pair, scalar storage/kind, value confidence, and the two
  gap-relative deltas. Across all local PAPR candidates, `60` observations
  produce `46` unique signatures. The strongest repeated limit signature is
  `limit_argument parent>target f32/u32_u16 approx prev=13 next=107` with `4`
  hits; a repeated driver signature is
  `channel_coefficient parent>helper f32/f32_unit exact prev=383 next=29` with
  `2` hits. The PTM app row reports `10` unique signatures. These are search
  fingerprints only, not fixed value-field bindings.
- Numeric/scalar match hints now also carry offsets relative to the inferred
  candidate expression row. Across all local PAPR candidates, the `60`
  observations produce `41` candidate-relative offset buckets spanning
  `-624..-6`; repeated buckets include `-105=5`, `-109=4`, `-81=3`, and
  `-6=2`. The PTM app row reports `10` candidate-relative buckets spanning
  `-615..-77`. These are record-position search hints only, not fixed
  value-field bindings.
- Candidate-relative signatures append that inferred expression-row offset to
  the existing family/role/pair/scalar/value/gap-delta fingerprint. Across all
  local PAPR candidates, `60` observations produce `55` unique relative
  signatures; the strongest repeated limit signatures are
  `limit_argument parent>target f32/u32_u16 approx prev=13 next=107 rel=-161`
  and `rel=-189`, each with `2` hits. The PTM app row reports `10` unique
  relative signatures. These are search fingerprints only.
- Record-layout summaries now also carry capped raw match samples. The real
  all-local-PAPR smoke keeps `24` sample rows from `ptm_01.papr`, with row-level
  value confidence split into `16` approximate float32 matches, `7` exact
  float32 matches, and `1` exact u32 match. The first sample is a
  `local_transform_limit_candidate` `limit_argument` between `parent>target` at
  candidate offset `3709`, and is explicitly labeled
  `approx_float32_numeric_value_match_layout_unproven`.
- `character/prefab/1_pc/01_phm/head/head/cd_phm_00_head_00_0001.prefabdata_xml`
  declared a head `SkeletonVariationName` and morph masks, but no local
  `SkeletonName`; head workflows likely inherit the class/body skeleton.

## Mesh Editor Implications

- Prefer explicit descriptor relationships when available:
  `.prefabdata_xml` skeleton name, `.pabc` variation, then `.pab` skeleton.
- Fall back to `resolve_skeleton_for_model()` only when descriptors are not
  available. Treat palette confidence as usable; treat exact/class/family
  heuristic as inspectable; treat identity-only fallback as unresolved for pose
  editing.
- Skeleton panel should show both the PAB skeleton source and the PABC variation
  source when known.
- Pose preview can deform preview geometry from loaded PAB bones plus PAC bone
  indices/weights. PABC skeleton variation records are now parsed and hash-bound
  to PAB bones, but their three float blocks remain read-only until matrix block
  roles are proven.
- Mesh Editor now has a safe parsed-clip playback path: a service-attached
  animation clip with explicit bone-name or bone-index rotation tracks can be
  played, stepped, or rewound and will drive the same preview-only skinning
  deformation path.
- Structured animation documents can enter that path through
  `mesh_animation_clip_from_document()` only when they already expose explicit
  `animation.bone_tracks`/`animation.tracks` rows with bone identity and
  rotation keyframes.
- Real `.paa` payloads can enter that path when a recovered quaternion table has
  an attached PAB bone hash exactly at `table_offset - 8`. Tables without exact
  hash ownership remain blocked. `.paseqc` is now handled as the compiled
  sequence sibling of `.paseq` for preview/resolver workflows, and can supply
  PAA lane references that bind to PAB-owned PAA tracks. Those lane references
  can now travel with parsed PAA preview clips as sequence segment metadata with
  per-field confidence labels. The playback summary reports the currently active
  lane when sampled time falls inside a recovered segment; blend weight and
  runtime sequencing semantics remain unknown. Sequence-family corpus evidence
  proves FPS metadata exists in source `.paseq` payloads and common float FPS
  candidates exist across the package; exact value offsets for that `int32`
  field and compiled `.paseqc` runtime binding are still not recovered from the
  PAR schema. The source PASEQ document now surfaces that as a proof gap instead
  of silently treating candidate values as FPS, so PAA preview still uses the
  parser's `30.0` FPS assumption with `default_30fps_unproven` timing status.
  Source PASEQ documents also surface blend-window declarations as proof-labeled
  evidence, but exact blend values and runtime lane semantics remain unmapped.
  PAPR payloads are now readable generic PAR constraint metadata, but
  constraint-solving semantics are not parsed.
