# Mesh Editor visual material-parity audit

## Goal and scope

The earlier completed audits compared Archive Browser and the resident
.NET/Vortice Mesh Editor across broad real-PAC corpora. They diagnosed shared
causes of blown-out color, x-ray appearance, inaccurate material regions, and
apparent texture-resolution loss while keeping source archives unchanged. They
used only hidden CDMW renderer automation; visible or licensed real-game
testing was not authorized.

Those paired audits are renderer-to-renderer compatibility evidence. Even a
directly reviewed 120/120 PASS means the two renderers agreed on the prepared
inputs; it does not prove that those inputs retained the exact PAC XML material
owner, every declared parameter, or authoritative DDS bindings. The completed
PAC-source follow-up therefore treats wrapper/owner/parameter conservation,
cross-owner and layer-as-base rejection, initial/resident equivalence, source
boards, and direct full-model/every-submesh review as separate required lanes.
Its verdict v2 template separately records inspection/observations for every
individual angle, contact sheet, source board, and submesh review sheet. Each
rendered image has a verdict and the asset result is fixed to the worst rendered
image; source evidence alone cannot issue visual PASS. It binds hashes back to
the frozen corpus, recomputes capture integrity, and validates the prepared
package seal before global acceptance. Its fresh capture and region verdicts
are now complete and remain distinct from the historical results below.

## Current verdict

- The 2026-07-22 PAC-source final-acceptance run is complete at 120 PASS,
  0 CONCERN, and 0 FAIL, including 112 equipment PACs and eight regression
  controls. All 3,558 images were opened separately at original detail: 720
  full-model comparisons, 120 contact sheets, 1,359 PAC/DDS source boards, and
  1,359 isolated material-region images. A full path/SHA-256 recheck found zero
  integrity problems, and the strict verdict-v2 reviewer accepted all 1,359
  region verdicts.
- Forty-two parked concern rows across 35 assets were adjudicated. Forty-one
  were cleared using the corresponding source board, isolated region, whole
  model, PAC binding state, and renderer material state. One was a real shared
  renderer defect: textureless generic materials ignored an explicitly present
  base tint when its blend strength was zero. Restoring the existing
  `MaterialBaseTint.w` fallback makes spear-0057 submesh 3 gold-tan and submesh
  15 coral; direct Lit/Base recaptures passed, and a textured-metal control was
  unchanged.
- The historical fifth material-first audit added another 120 real PACs while excluding all
  317 paths in the prior evidence ledger. All 720 paired views were directly
  inspected and finalized at 120 PASS, 0 CONCERN, and 0 FAIL with zero
  unreviewed assets. It found no new shared renderer defect across swords,
  shields, other weapons, helmets, upper/lower armor, boots, gloves, cloaks,
  vests, hair/beard, skin, bone, fur, crystal, organic shell, and unusual mixed
  creatures.
- The fourth material-classification audit adds 120 real PACs that do not
  overlap the previous 197 unique paths. Every one of the 720 paired views was
  inspected only after classifying the visible material, including mixed
  regions. The original ledger was 99 PASS, 4 CONCERN, and 17 FAIL; the fully
  rebuilt repaired run is 119 PASS, 1 CONCERN, and 0 FAIL. The sole remaining
  concern is sword 004's guard tint/material-region mismatch.
- Equipment slot or filename is not material authority. Cloth, leather, skin,
  hair/fur/feather, wood, foliage, bone/horn, and organic shell are expected to
  remain matte when the Archive Browser reference is matte. Mixed assets keep
  metal response only on decoded metal regions. In particular, footwear 082's
  pale stitched shafts were classified as cloth or soft leather, with only
  small trim/hardware classified as metal.
- The metallic equipment follow-up now renders authoritative gold, bronze,
  steel, dark iron, and colored armor as view-dependent metal instead of flat
  neutral paint. The fixed shader uses an RGB studio environment, physical
  Schlick Fresnel, GGX/Smith direct response, and source-colored metal F0.
  The expanded 162-PAC audit exposed a source-readability/tint regression in
  that response which the earlier 15-PAC ledger missed. A bounded metal floor
  and native chromatic-tint authority now preserve dark and colored source
  materials while category gating keeps wood, cloth, leather, hair, and generic
  controls stable.
- The originally reported sword is no longer white, blown out, transparent, or
  texture-starved. The yellow section in the supplied .NET screenshot was the
  editor selection overlay, not source material color.
- The screenshot resolution comparison was not like-for-like: Archive Browser
  was shown at 200%, while .NET fitted the complete model into a smaller
  viewport. Direct authoritative DDS package payloads are not downscaled;
  synthesized material-graph PNG outputs remain capped and can contribute
  softness.
- Current hidden runtime evidence keeps depth enabled and records no active
  X-ray mode, no no-depth wire draws, and no no-depth vertex passes.
- A real audit-harness camera defect was found while widening the corpus:
  .NET captures were horizontally mirrored and combined yaw/pitch used a
  different screen basis. The audit-only camera now uses Archive's
  `T(-center) * Rx(pitch) * Ry(yaw)` object-rotation basis. Interactive camera
  behavior is unchanged.
- Anonymous inferred hair/cutout materials now use the established `0.12`
  cutoff instead of the generic `0.5` default. This restores previously
  rejected eyebrow and eyelash cards without changing explicit cutoff
  authority or producing opaque halos in the control corpus.
- Fresh post-fix proof across 50 swords, other weapons, shields, helmets,
  armor, boots, body, hair/fur/feather, and unusual mixed-material PACs is
  43 PASS, 7 CONCERN, 0 FAIL. The remaining concerns are bounded to three
  asset-specific packed roughness/normal contracts, the unsupported
  `skinnedmeshtear` layer graph, and two smaller facial-card density/color
  differences.

## Committed repairs

- `92083d8` preserves authoritative DDS bindings after optional cold-preview
  conversion failure.
- `9640005`, `61b837d`, and `0e67426` synthesize the .NET material graph,
  generate bitmap mip chains, use 16x anisotropic sampling, and resolve 4x MSAA.
- `7cad21b` makes Fresnel and normal response consistent with the orthographic
  camera.
- `ad252b7` preserves punctuation-sensitive sidecar identities and selects
  exact owner graphs before unambiguous fuzzy matching.
- `8b68a3d` stops the combination of zero intensity and non-authoritative
  fallback color from promoting generic materials. Positive intensity,
  authoritative nonblack color, explicit emissive/glow role, or a resolved
  emissive channel remains active family evidence.
- `c8013cd` adds the audit-only Archive camera basis and rejects mirrored or
  rolled capture matrices in integrity validation.
- `c3101d9`, `9fd45a3`, and `918aba8` repair visual-audit invocation, validate
  the .NET DLL input, and permit bounded preparation resume.
- `75a83fc` resolves immutable external material factors once per synthesized
  texture instead of rescanning normalized parameter names for every pixel.
  Exact generated pixels are unchanged.
- `6a57863` implements the physical colored-metal response and upgrades the
  hidden textured-metal proof to v4 with four same-material specular-debug
  camera captures and bounded/view-varying response gates.
- The 2026-07-17 expanded-corpus repair restores a bounded source-readable
  floor and Archive Browser chromatic-tint authority within that physical
  metal response, applies the established `0.12` cutoff to inferred PAC
  hair/cutout materials, and retains custom manifests in generated rerun
  commands.
- The fourth-corpus repair decodes older unnamed `SkinnedMeshStandard` `_sp`
  maps as direct G-channel roughness plus B-channel metal/specular response,
  instead of using opaque R/A controls as full gloss. Armor-family placement
  now promotes a whole submesh to metal only when the decoded metal channel is
  dominant; localized metal remains per-pixel on an otherwise generic mixed
  material. Sparse inferred beard alpha falls back to an opaque card only when
  the inferred cutoff would discard at least 90% of the decoded color texture;
  explicit authored cutout authority is unchanged.
- Square offscreen capture resizing now preserves the source camera's world
  basis. This keeps Archive-audit object-rotation cameras and interactive
  editor cameras in their respective contracts while rebuilding only the
  projection for the capture dimensions.

## Current evidence

### PAC-source final acceptance sweep (complete)

The current final-acceptance sweep is intentionally stricter than the
historical renderer-to-renderer audits below. It freezes 120 real PACs and
requires a separate original-detail decision for every rendered comparison,
contact sheet, PAC/DDS source-authority board, and isolated material-region
sheet. Every accepted ledger row records the relative path, SHA-256, inspection
mode, status, and a concrete observation; source evidence alone cannot issue a
visual PASS.

Final checkpoint on 2026-07-22:

| Evidence class | Reviewed | Total | Remaining |
|---|---:|---:|---:|
| Six comparison angles | 720 | 720 | 0 |
| Full-model contact sheets | 120 | 120 | 0 |
| PAC/DDS source boards | 1,359 | 1,359 | 0 |
| Material-region sheets | 1,359 | 1,359 | 0 |
| **Total** | **3,558** | **3,558** | **0** |

All 120 full-model sets and all 1,359 visible submesh lanes are complete. The
three direct-review ledgers contain 3,558 unique paths; every path exists and
matches its recorded SHA-256. The final strict review is 120 PASS,
0 CONCERN, and 0 FAIL at asset level and 1,359 PASS at region level. The
equipment subset is 112 PASS with no unresolved visual verdict.

The frozen selection manifest hashes to
`c70e8905f3d4c12edf263c16792040716f5c52fbbdb5036f87ce6fe757b9c2ba`;
the fresh `corpus.json` hashes to
`cb9f3af1a979a054c194cdb506dae9010e11cf73db62a4005b2402081da94fc7`;
and the prepared-package aggregate remained
`10e4d05c267e716f8730a293087af641bf9efc59f4d241e8165928ef3b400eca`
before and after capture. The local evidence root is
`%TEMP%\cdmw-material-parity-final-120-20260720-111535`.
Generated images, licensed asset data, and the temporary JSONL ledgers are not
versioned.

The final parked-concern ledger contains 42 rows across 35 assets. Its matching
adjudication ledger clears 41 and records one fixed defect. Cross-domain paths
were conserved localized kitbash reuse, Archive Browser differences were
adjudicated against PAC/source and isolated-region authority, and ambiguous
emissive cases were resolved from actual resource presence, scalar/color
authority, and intensity. In particular, helmets 090 and 091 have no emissive
resource and intensity zero on the questioned eye-adjacent regions, so the
absence of visible eye glow is source-consistent.

Two evidence/renderer limitations remain explicit without producing a visual
CONCERN: 21 source-board rows cannot bitmap-preview a native DDS format even
though the actual renderer loaded the resources and their direct output passed,
and 68 hair regions retain the pre-existing unsupported
`hair_fur_anisotropy_and_flow` response. Those rows are marked unsupported and
unchanged rather than silently treated as fully implemented game-shader proof.

Several Codex image-transport failures occurred while returning large PNGs.
They are not Mesh Editor failures and never count as reviewed images. The safe
continuation protocol is one fresh original-detail image call at a time, with
an immediate retry after any transport failure; batching or reusing prior
image payloads is prohibited. A fresh Codex task can clear corrupted or
oversized image history without losing audit state because the frozen corpus,
ledgers, and handover checkpoint remain on disk.

This is complete CDMW renderer/source-material acceptance for the frozen corpus.
It is not licensed-game visual parity: no visible real-game gate was authorized
or run.

### Fifth 120-PAC material-first expansion

Manifest:
`tools/mesh_harness/visual_audit_followup_fifth_120.manifest.json`

Evidence:
`workspace/mesh-editor-visual-audit/20260717-fifth-material-classification-120`

- Run `875c065c8a9b4005849f125621272d9b` finalized at 120 PASS,
  0 CONCERN, and 0 FAIL with zero unreviewed. The manifest contains 120 unique
  PACs and excludes 317 previously reviewed paths: 40 weapons, including
  16 swords and eight shields; 52 armor items, including 20 helmets; eight
  body/head controls; ten hair/beard controls; and 12 unusual assets.
- Geometry preflight parsed 120/120 non-empty meshes with 428 submeshes,
  878,512 vertices, and 1,043,787 faces. Archive Browser and the production
  `d3d11_vortice_shader` each captured six paired angles per PAC while one
  process/device/viewport remained resident. All 720 comparisons, all contact
  sheets, and all material classifications were directly reviewed.
- The review deliberately treated inventory placement as non-authoritative.
  Cloth trousers, leather boots and guards, fur cloaks, hair, skin, bone,
  feathers, organic shells, and stone-like creatures stayed matte. Mixed armor
  kept response localized to visible plate/rivet regions. Pale mask 091 was
  visually ambiguous enough to inspect its extracted contract; the source
  identifies it as armor metal with about 92% decoded metal coverage, so its
  polished highlight is intentional rather than a soft-material error.
- Both capture batches and rendered-camera integrity passed. The resident
  session loaded 120 scenes with one viewport/device initialization, no reset
  or process restart, 720 MSAA-resolved offscreen captures, and no DDS upload
  fallback. Every referenced PAMT/PAZ fingerprint remained byte-identical.

### Fourth 120-PAC material-classification proof

Manifest:
`tools/mesh_harness/visual_audit_followup_120.manifest.json`

Original evidence:
`workspace/mesh-editor-visual-audit/20260717-fourth-material-classification-120`

Repaired evidence:
`workspace/mesh-editor-visual-audit/20260717-fourth-material-classification-after-repair-120`

- The corpus contains 120 unique non-overlapping PACs: 40 weapons, including
  16 swords and eight shields; 52 armor items, including 20 helmets; eight
  body/head controls; ten hair/beard controls; and 12 unusual mixed-material
  assets. Geometry preflight parsed 120/120 assets, 286 submeshes, 762,110
  vertices, and 941,905 faces.
- Original run `8e03f569ddaf47378d3f1e8d9c067e7d` finalized at 99 PASS,
  4 CONCERN, and 17 FAIL. Shared failures were excessive hard gloss on soft
  helmet cloth/fur, wet/metal response on leather footwear, and an inferred
  beard cutoff that removed most of the silhouette. Four bounded concerns
  covered sword 004's guard and localized mixed-footwear response.
- Repaired run `5e60be0453064ad7a27d1741ad1c184e` rebuilt all packages
  under the corrected semantics and finalized at 119 PASS, 1 CONCERN, and
  0 FAIL with zero unreviewed assets. Soft cloth/leather/fur regions stay matte,
  true-metal helmet controls retain view-dependent response, beard 101 retains
  its broad Archive Browser silhouette, and authored cutout control 102 keeps
  its fine strands. Sword 004's guard remains the only concern.
- Every ledger row has an explicit visual material classification from metal,
  leather, cloth, skin, hair/fur/feather, wood, glass-like, emissive,
  stone/ceramic, painted/coated, bone/horn, organic shell, foliage, or unknown.
  Mixed assets include region-level observations; the review finalizer rejects
  missing or invalid classifications when the manifest requires them.
- Both production renderers stayed hidden and resident for all 120 assets with
  no device reset or restart. Run identity, all six rendered camera views,
  composite completeness, and paired-camera mapping pass. All 25 referenced
  PAMT/PAZ sources remained byte-identical.

### Expanded 162-PAC regression discovery

Manifests:
`tools/mesh_harness/visual_audit_followup_90.manifest.json` and
`tools/mesh_harness/visual_audit_followup_72.manifest.json`

Evidence roots:
`workspace/mesh-editor-visual-audit/20260717-physical-metal-current-90` and
`workspace/mesh-editor-visual-audit/20260717-physical-metal-current-72`

- Runs `ca91cfb0404c4e4086ecedd514231176` and
  `dc093f2063e347a1acb1bc3272a4af6a` covered 162 unique PACs: 156 additions
  plus six deliberate repeat controls from the earlier metallic corpus.
- All 972 paired views and all 162 contact sheets were directly inspected.
  The finalized baseline ledgers total 136 PASS, 24 CONCERN, and 2 FAIL:
  79/11/0 in the 90-PAC run and 57/13/2 in the 72-PAC run.
- The broader swords, axes, shields, helmets, armor, boots, facial composites,
  hair, creatures, props, glass, emissive, and unusual mixed-material coverage
  exposed two shared defects missed by the smaller run: physical metal could
  become too dark or over-tinted, and anonymous inferred hair/cutout batches
  rejected fine cards at the generic `0.5` cutoff.
- Both hidden runs used one production Archive Browser process and one resident
  `d3d11_vortice_shader` process/device/viewport, completed without restarts,
  resets, or stalls, and passed corpus/camera/capture integrity. Every
  before/after PAMT/PAZ fingerprint was byte-identical.

### Inferred alpha-cutoff repair proof

Evidence:
`workspace/mesh-editor-visual-audit/20260717-alpha-cutoff-repair-8`

- Run `1fa88fcc22ec44beafe15e60dadffce3` finalized at 6 PASS,
  2 CONCERN, 0 FAIL after direct inspection of all 48 paired views.
- The two formerly missing facial-card cases now retain eyebrow and eyelash
  geometry. Their remaining differences are smaller density/color response,
  while six explicit/non-hair controls remain stable with no opaque halo.
- Hidden resident runtime, paired-camera/corpus integrity, and byte-identical
  archive fingerprints all passed.

### Fresh 50-PAC post-fix cross-category proof

Manifest:
`workspace/mesh-editor-visual-audit/20260717-final-material-parity-coverage.manifest.json`

Evidence:
`workspace/mesh-editor-visual-audit/20260717-final-material-parity-50`

- Run `b1f8ff56083448a6bb77150f430a4cbb` covered 50 unique PACs: 20 weapons,
  including nine swords; eight armor/boots assets; five body/facial controls;
  eight hair/fur/feather controls; and nine unusual mixed-material assets.
- Final structured review is 43 PASS, 7 CONCERN, 0 FAIL. Every one of the 300
  paired views and all 50 contact sheets was inspected. Swords, axes, musket,
  shields, helmets, upper armor, and all hair controls passed; the shared dark
  metal/tint and missing-card failures did not recur.
- Residual concerns are long black boots 0166, aircastle core, and black glasses
  0001 for asset-specific packed roughness/normal response; two tear-card PACs
  for unsupported `skinnedmeshtear` layer graphs; and two facial composites for
  smaller hair-card density/color differences.
- The hidden run passed production backend, one-process/one-viewport residency,
  camera/capture/corpus integrity, and byte-identical PAMT/PAZ fingerprints
  with zero restarts or resets. Its generated `commands.md` retains the custom
  `--manifest`, so both documented rerun commands reproduce the same corpus.

### Metallic equipment physical-response proof

Manifest:
`workspace/mesh-editor-visual-audit/manifest-metallic-equipment-15.json`

Untouched baseline:
`workspace/mesh-editor-visual-audit/20260716-metallic-equipment-15-baseline`

Current-code evidence:
`workspace/mesh-editor-visual-audit/20260716-metallic-equipment-15-after`

- Baseline run `9bcbeb6e310e449e80b7a43d19fa3a54` completed before
  the implementation/build changed. Current-code run
  `50ec9b59d53d4d8fa5b68beb39fd4373` rebuilt and recaptured the identical 15
  real PACs.
- Final structured review: 15 PASS, 0 CONCERN, 0 FAIL; all 90 paired views were
  directly inspected and `unreviewed_count` is zero. Gold sword 0070 retains
  warm gold/bronze authority with moving highlights; axes, helmets, upper
  armor, and promoted-metal boots show bounded response. Wood, cloth, hair,
  generic armor, and generic boots remain nonmetal controls.
- One hidden production .NET process/device/viewport handled all 15 resident
  scene loads with zero restarts or device resets. Backend is
  `d3d11_vortice_shader`, capture mode is `hidden_hwnd_no_show`, depth remains
  enabled, and no X-ray/no-depth behavior was observed.
- OpenImageIO 3.1.15.0 compared all six exact same-camera baseline/current
  views for representative sword, axe, helmet, two armor assets, and metal
  boots: 36 reports, 36 amplified difference PNGs, zero blockers, and zero
  camera-matrix mismatches. The nonmetal hard-surface control remained
  effectively pixel-stable (average RMS `0.000276`, maximum error `0.007843`),
  while intended metal assets changed without object clipping. Evidence is in
  the current-code root under `evidence/oiio-before-after/`.
- Red Knight package preparation fell from `459.47 s` to `21.56 s`; its full
  preparation total fell from `912.52 s` to `50.02 s`. The deterministic
  96x96 material-combiner benchmark improved from `6400.52 ms` to `33.99 ms`
  while all roughness/metalness/specular output hashes stayed identical.
- Before/after fingerprints for all 17 referenced PAMT/PAZ files are
  byte-identical in both runs. No archive was written or restored.

### Affected-family material/runtime proof

Evidence:
`workspace/mesh-editor-visual-audit/20260716-inactive-emissive-fix-affected-9`

- Run ID: `40cb1ecddae1479189f7bf57c1c1c496`
- Nine real PAC families, 130 native/.NET batches.
- Material-family matches: 130/130.
- PTM lower retained its one legitimate native/.NET emissive batch.
- PHW upper, PHM foot, machine beetle, NHW, NOM, warrobot, lightsource, and
  airplane retained zero false emissive promotions.
- The corrected-camera visual ledger is complete: 8 PASS, 1 CONCERN, 0 FAIL,
  with only the lightsource's localized lower inner-brazier/material-region
  response remaining.
- All 54 refreshed paired views were re-inspected. Camera mapping, rendered
  camera axes, paired views, composites, and final structured review pass;
  `unreviewed_count` is zero.
- One hidden resident .NET process/device/viewport, 4x MSAA, 16x anisotropy,
  nine resident scene loads, zero device resets, zero native DDS fallback,
  depth enabled, and zero X-ray/no-depth passes.
- The before/after 20-entry archive-fingerprint manifests are byte-identical;
  each manifest JSON file hashes to
  `BC8EEE24F312C8B8811B9255DCF4F9381776C0698DF0C61A0BD6AF1172D8D923`.

### Audit camera proof

Evidence:
`workspace/mesh-editor-visual-audit/20260716-camera-basis-chain-1`

- Run ID: `1b51a53a00a847c8a6ab4142a5f37d1a`
- All six chain views now lean in the same direction in Archive and .NET.
- Normalized screen-right, screen-up, and cross-product view axes pass the
  0.25-degree integrity tolerance.
- The old 16-model evidence fails the strengthened basis check on all six
  views, confirming that the previous integrity gate had missed a real defect.
- New paired-camera integrity passes and archive fingerprints are identical.

### Completed current-code corpus

Manifest:
`workspace/mesh-editor-visual-audit/manifest-current-parity-additional-16.json`

Evidence root:
`workspace/mesh-editor-visual-audit/20260716-camera-aligned-current-parity-additional-16`

- Run ID: `c73e83ac1b334a1e933510e6ed2e5a15`
- All 16 packages were rebuilt under the inactive-emissive fix and captured
  with the corrected audit camera.
- Final structured review: 11 PASS, 5 CONCERN, 0 FAIL; all 96 paired views were
  inspected and `unreviewed_count` is zero.
- Concerns:
  - shield 0135: shared excessive darkness and incomplete metallic/roughness
    readability;
  - two-hand sword 0012: subtle .NET normal/metallic/roughness response;
  - PHM head 0207: unsupported skin subsurface/wrinkle response;
  - spider queen body: shared blown-out hair/fur layer and cutout response;
  - gimmick chain: shared excessive darkness and weak metal readability.
- One hidden resident .NET process/device/viewport handled all 16 scene loads:
  backend `d3d11_vortice_shader`, capture mode `hidden_hwnd_no_show`, 4x MSAA,
  16x anisotropy, zero device resets, zero native DDS upload fallbacks, depth
  enabled, and zero X-ray/no-depth passes.
- Integrity passes for run identity, camera mapping, normalized rendered camera
  axes, paired views, complete composites, and source archive equality.
- The before/after 24-entry archive-fingerprint manifests are byte-identical;
  each manifest JSON file hashes to
  `A99920240AB52ECFDCF089C1C7E85BEA8E782FAB1C08F166395A77E5599A2786`.

The 16-model corpus covers two dark shields, emissive/packed-PBR and dark-metal
weapons, layered PTM armor, dense helmet/hair regions, a skin/eye-cover proxy,
creature hair/eyes, foliage/thin surfaces, multicolor machinery, three NPC
routing probes, moth wings, a dark chain, and a reflective control.

## Texture-resolution evidence

The completed 16-model baseline package set provided these source/payload facts:

- 639 source texture references and 403 unique payloads.
- Dimensions range from 4x4 through 2048x2048; some models intentionally use
  narrow source atlases such as 32x256 and 64x1024.
- Zero invalid DDS payloads, zero native-ineligible authoritative DDS payloads,
  and zero missing source mip chains.
- 154 direct authoritative source/package DDS pairs representing 104 unique
  payloads were byte-hash compared: zero missing and zero mismatches.
- The same baseline diagnostics contain 390 synthesized PNG resources out of
  703 resource diagnostics. Synthesized color-layer/albedo-mask outputs may use
  the documented 512 px cap.

Therefore direct authoritative DDS transport is not downscaled. Apparent .NET
softness can still come from different fit scale, orthographic-versus-perspective
framing, synthesized 512 px material-graph outputs, flatter unsupported material
response, or narrow source atlases. Source DDS wins over preview PNG, and
supported direct native formats/mips are retained byte-identically.

## Unsupported or diagnostic material families

- The generic `skinnedmeshtear` path lacks an authoritative supported layer
  graph; the two reviewed tear-card bodies remain too black.
- Long black boots 0166, the aircastle core, and black glasses 0001 retain
  asset-specific packed roughness/normal or material-contract differences.
- Facial cards 039/040 are restored but retain smaller alpha-density/color
  differences. Skin subsurface/wrinkle response and advanced hair/fur
  anisotropy, strand flow, and multilayer scattering remain diagnostic.
- Complex layer graphs, including the lightsource inner-brazier response, and
  true alpha blend/transmission remain unsupported. The moth, foliage, hair,
  and eye-cover assets are cutout/thin-surface proxies, not transmission proof.
- Exact real-game reflection/bloom environment.

These are explicitly remaining diagnostic gaps. They are not evidence of
global x-ray behavior or texture downscaling.

## Validation state

- The strict reviewed-v2 finalizer passed 120 assets and 1,359 material regions:
  120 PASS, 0 CONCERN, and 0 FAIL. The evidence summary status is
  `complete_visual_review`.
- The current focused parameter/material-audit checks passed 40 tests. Fresh
  `.\scripts\codex_check.ps1 -Area mesh-unit` passed 917 tests with one skip.
- Fresh .NET Release build succeeded with 0 warnings and 0 errors, and the
  material-resource-policy runtime report passed.
- Fresh full-scale hidden Vortice soak passed at 1,000,000 vertices and 1,000
  updates: release eligible, `0.3348 ms` handler p95, `59.9861` updates/s,
  hidden production D3D11/Vortice, and no working-set growth after warm-up.
- Fresh hidden resident material-authority parity passed all 38 controls with no
  mesh/process reload, viewport replacement, camera reset, or device reset.
- The canonical hidden 30-second/144 Hz frame-pacing command was run twice and
  retained as a bounded validation exception. On the current 175 Hz desktop it
  captured 4,317 frames at `143.859` effective FPS, `6.0717 ms` p50,
  `12.1883 ms` p95, `12.3357 ms` p99, and no interval above `13.89 ms`; 32 of
  33 gates passed, but the fixed `8.68 ms` p95 gate failed because `Present(1)`
  quantized the requested 144 Hz cadence to one or two 175 Hz refreshes. The
  repeat reproduced the same single gate failure, so it is not recorded as a
  passing release-performance proof or dismissed as a flake. It is unrelated
  to the base-tint shader correction.
- The fifth 120-PAC ledger is 120/0/0 with every image reviewed and every row
  explicitly material-classified.
- The fourth 120-PAC original/repaired ledgers are 99/4/17 and 119/1/0.
- The finalized expanded baseline is 136 PASS, 24 CONCERN, 2 FAIL across 162
  PACs. Post-fix alpha proof is 6/2/0, and the fresh 50-PAC cross-category proof
  is 43/7/0 with every paired view directly reviewed.
- All visual-audit captures remained hidden and resident, passed the production
  backend and integrity gates, and retained byte-identical before/after archive
  fingerprints.
- The visible/licensed real-game gate was not run because it was not authorized.

## Durable continuation point

The PAC-source final acceptance is complete for the frozen CDMW corpus. Future
texture/material-parity work should start from evidence root
`%TEMP%\cdmw-material-parity-final-120-20260720-111535`
and its `complete_visual_review` summary. The finalized fifth and repaired
fourth 120-PAC roots, the 50-PAC post-fix root, and the two 162-PAC discovery
roots remain historical coverage. Do not use mirrored or
capture-resized-with-a-recreated-basis camera evidence.

Highest-value remaining work:

1. Make the source-board compositor decode the 21 currently unpreviewable native
   DDS rows without changing the renderer's direct DDS authority.
2. Implement authoritative hair/fur anisotropy and flow, then recapture only the
   affected 68 frozen regions and their whole-model cross-section.
3. Make the frame-pacing acceptance gate account for the actual presentation
   refresh contract, or rerun the unchanged 144 Hz command on a true 144 Hz
   presentation target; do not weaken the fixed gate merely to pass 175 Hz
   cadence quantization.
4. Add real-game reflection, bloom, transmission, and proprietary shader-graph
   validation only when explicitly authorized; hidden CDMW proof does not cover
   those effects.

To refresh a completed visual ledger after a renderer change, rerun its
manifest into a new evidence root, inspect all six paired views per model, then
run `tools/mesh_editor_visual_audit_review.py`. Do not reuse a prepared package
set across a material-semantic change, and do not run the visible/licensed
real-game gate without explicit authorization.
