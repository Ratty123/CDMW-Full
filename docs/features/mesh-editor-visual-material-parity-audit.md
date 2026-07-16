# Mesh Editor visual material-parity audit

## Goal and scope

This completed audit compared Archive Browser and the resident .NET/Vortice
Mesh Editor across a broad real-PAC corpus. It diagnosed shared causes of
blown-out color, x-ray appearance, inaccurate material regions, and apparent
texture-resolution loss while keeping source archives unchanged. It used only
hidden CDMW renderer automation; visible or licensed real-game testing was not
authorized.

## Current verdict

- The metallic equipment follow-up now renders authoritative gold, bronze,
  steel, dark iron, and colored armor as view-dependent metal instead of flat
  neutral paint. The fixed shader uses an RGB studio environment, physical
  Schlick Fresnel, GGX/Smith direct response, and source-colored metal F0.
  Category-gated behavior preserves wood, cloth, leather, hair, and generic
  controls.
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
- The remaining visible concerns are family- or asset-specific: unsupported
  hair/fur and skin response, layered inner material regions, subtle
  roughness/normal response, and very dark source materials.

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

## Current evidence

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

- Skin subsurface/wrinkle response.
- Hair/fur anisotropy, strand flow, multilayer scattering, and exact cutout
  response.
- Complex layer graphs and the lightsource inner-brazier layer response.
- True alpha blend/transmission and authoritative double-sided coverage; the
  moth, foliage, hair, and eye-cover assets are only proxies.
- Exact real-game reflection/bloom environment.

These are explicitly remaining diagnostic gaps. They are not evidence of
global x-ray behavior or texture downscaling.

## Validation state

- Metallic-response focused validation passed the complete 61-test
  native-preview module, five owned physical-shader/proof tests, and two
  existing external-factor regression tests.
- Fresh physical-metal proof v4: all response/completeness/bounds gates passed;
  all-view luma ratio was `0.7050`, specular-debug mean span was `27.847`, and
  white fraction was zero.
- Fresh full-scale hidden Vortice soak: 1,000,000 vertices and 1,000 updates,
  release-gate eligible, `0.1647 ms` handler p95, `0.3067 ms` maximum, zero
  working-set growth, and no failed gates.
- Focused current-change suite:
  `tests/test_mesh_dotnet_material_visual_parity.py`,
  `tests/test_mesh_visual_audit_harness.py`, and
  `tests/test_mesh_visual_audit_integrity.py`: 49 passed.
- Fresh .NET Release build: succeeded with 0 warnings and 0 errors.
- Fresh `.\scripts\codex_check.ps1 -Area mesh-unit`: 889 passed, 1 skipped.
- Dedicated real-PAC chain proof: paired-camera integrity passed.
- Final 16-model structured review: 11 PASS, 5 CONCERN, 0 FAIL.
- Final nine-family structured review: 8 PASS, 1 CONCERN, 0 FAIL.
- Both final runs prove hidden resident Vortice ownership, depth enabled, no
  X-ray/no-depth passes, complete paired captures, and byte-identical
  before/after archive-fingerprint manifests.
- The visible/licensed real-game gate was not run because it was not authorized.

## Durable continuation point

This audit pass is complete. Future texture/material-parity work should start
from the three finalized current-code evidence roots above, including the
15-model metallic equipment root, not from older mirrored-camera captures.

Highest-value remaining work:

1. Implement dedicated preview support for skin subsurface/wrinkle response and
   hair/fur anisotropy, flow, multilayer scattering, and cutout response.
2. Resolve the lightsource's localized inner-brazier layer graph and improve
   diagnostic readability for the dark shield and chain without inventing
   unsupported source values.
3. Audit synthesized material-graph output sizing. Direct authoritative DDS
   transport is proven byte-identical, but capped synthesized outputs remain a
   plausible softness source.
4. Add authoritative alpha-blend/transmission and double-sided corpus entries
   when real PAC examples are identified; current moth, foliage, hair, and
   eye-cover assets are only cutout/thin-surface proxies.

To refresh a completed visual ledger after a renderer change, rerun its
manifest into a new evidence root, inspect all six paired views per model, then
run `tools/mesh_editor_visual_audit_review.py`. Do not reuse a prepared package
set across a material-semantic change, and do not run the visible/licensed
real-game gate without explicit authorization.
