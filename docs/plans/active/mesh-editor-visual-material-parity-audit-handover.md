# Mesh Editor visual material-parity audit handover

## Goal

Continue broad, repair-oriented comparison of Archive Browser and the resident
.NET/Vortice Mesh Editor across real PAC models. Diagnose shared causes of
blown-out color, x-ray appearance, inaccurate material regions, and apparent
texture-resolution loss. Keep source archives unchanged. Hidden CDMW renderer
automation is allowed; visible or licensed real-game testing is not authorized.

## Current verdict

- The reported sword is no longer white, blown out, transparent, or
  texture-starved in the current renderer. The yellow section in the supplied
  .NET screenshot is the editor selection overlay, not source material color.
- The screenshot resolution comparison was not like-for-like: Archive Browser
  was shown at 200%, while .NET fitted the whole sword into a smaller viewport.
- Current hidden runtime evidence has depth enabled and reports no active X-ray
  overlay, no no-depth wire draws, and no no-depth vertex passes.
- Residual differences are now mostly family-specific: hair/layer response,
  subtle roughness/normal response, dark-source readability, and individual
  material-region routing.

## Repairs already committed

- `92083d8` preserves authoritative DDS bindings after an optional cold-preview
  conversion failure.
- `9640005`, `61b837d`, and `0e67426` synthesize the .NET material graph,
  generate bitmap mip chains, use 16x anisotropic sampling, and resolve 4x MSAA.
- `7cad21b` makes Fresnel and normal response consistent with the orthographic
  camera instead of using a per-pixel perspective view vector.
- `ad252b7` preserves punctuation-sensitive sidecar material identities and
  selects exact owner graphs before unambiguous fuzzy compatibility matching.
- `c3101d9`, `9fd45a3`, and `918aba8` repair the visual-audit invocation,
  validate that the .NET input is a DLL, and permit bounded checkpoint resume.

## Current evidence

- Representative current-code run:
  `workspace/mesh-editor-visual-audit/20260716-current-parity-representatives-2`
  - Run ID: `199b3380a3914575ab2de077da1982ce`
  - Verdicts: 3 PASS, 5 CONCERN, 0 FAIL
  - One hidden .NET process/device/viewport, 4x MSAA, 16x anisotropy, 35 live
    SRVs, zero native DDS fallbacks, no X-ray/no-depth passes, integrity passed,
    and archive fingerprints unchanged.
- Exact-identity regression run:
  `workspace/mesh-editor-visual-audit/20260716-sidecar-exact-identity-fix-3`
  - Run ID: `d8b6eb64b2b6498b8afdbdd06eddccc0`
  - 1 PASS, 1 CONCERN, 0 FAIL; the lightsource coffin/copper identity collision
    is fixed, with only a localized layered inner-brazier response remaining.
- Broad renderer recapture:
  `workspace/mesh-editor-visual-audit/20260716-renderer-recapture-90`
  - Run ID: `1eb13c275fe443418480e18e75be1b9f`
  - 82 PASS, 8 CONCERN, 0 FAIL on its captured archive snapshot.
  - Do not treat its game-archive fingerprint as current; the game archives
    were changed externally after that run.

## Expanded 16-model audit in progress

Manifest:
`workspace/mesh-editor-visual-audit/manifest-current-parity-additional-16.json`

Evidence root:
`workspace/mesh-editor-visual-audit/20260716-current-parity-additional-16`

The sample adds dark shields and metal, emissive/mixed weapons, layered armor,
hair/cutout materials, a skin/eye-cover proxy, creature hair/eyes, foliage,
multi-material machinery, three NPC routing probes, moth wings, a dark chain,
and a reflective control. No known corpus asset provides authoritative
alpha-blend/transmission or double-sided coverage; wing, eye-cover, hair, and
foliage assets are proxies only.

At this checkpoint, 10 of 16 assets are fully prepared and asset 11, the large
NDM NPC control, is actively converting hundreds of material inputs. The
preparation checkpoint is:

`workspace/mesh-editor-visual-audit/20260716-current-parity-additional-16/runtime/preparation-checkpoint.json`

The highest-priority fresh comparisons are:

1. NHW NPC collar: previously purple in Archive and cream/white in .NET.
2. NOM NPC scarf: previously blue in Archive and gray in .NET.
3. Machine beetle: conspicuous lime/purple/orange flat regions shared by both
   previews; determine whether this is legitimate fallback/source authority.
4. Helmet, spider queen, foliage, and moth: cutout/thin-surface stability.
5. Dark shield, dark sword, and gimmick chain: material readability.

Resume the same hidden run if its process exits before completion:

```powershell
$env:CDMW_DIRECTXTEX_TEXTURE_BIN = "$PWD\native\cd_texture_dx\build\Release\cd-texture-dx.exe"
$env:CDMW_D3D11_PREVIEW_BIN = "$PWD\native\cdmw_d3d11_preview\build\Release\cdmw-d3d11-preview.exe"
$env:CDMW_MESH_CORE_BIN = "$PWD\native\cdmw_mesh_core\build\Release\cdmw-mesh-core.exe"
.\.venv\Scripts\python.exe tools\mesh_editor_visual_audit.py `
  --manifest workspace\mesh-editor-visual-audit\manifest-current-parity-additional-16.json `
  --evidence workspace\mesh-editor-visual-audit\20260716-current-parity-additional-16 `
  --game-root "C:\games\Steam\steamapps\common\Crimson Desert" `
  --dotnet-assembly tools\dotnet_mesh_editor_experiment\bin\Release\net8.0-windows\cdmw-mesh-dotnet-editor.dll `
  --limit 16 --resume-prepare
```

After capture, inspect all six views per asset, author `verdicts.json`, and run:

```powershell
.\.venv\Scripts\python.exe tools\mesh_editor_visual_audit_review.py `
  --evidence workspace\mesh-editor-visual-audit\20260716-current-parity-additional-16 `
  --verdicts workspace\mesh-editor-visual-audit\20260716-current-parity-additional-16\verdicts.json
```

## Validation state

- Exact sidecar matcher focused tests: 44 passed.
- Visual-audit harness tests: 30 passed.
- .NET Release build: succeeded with 0 warnings and 0 errors.
- Preview-settings contract: 10 passed and 1 unrelated baseline string-contract
  failure in `D3D11MaterialViewport.Panes.cs`.
- Earlier Mesh Editor unit gate: 884 passed, 1 skipped. Rerun `mesh-unit` after
  the expanded capture and any further code change.

## Remaining work

1. Finish the 16-model hidden paired capture.
2. Classify every asset with direct visual evidence and structured verdicts.
3. Repair and recapture any new shared renderer-owned root cause.
4. Verify capture integrity, unchanged archives, resident-process ownership,
   4x MSAA, 16x anisotropy, zero DDS fallback, and zero X-ray/no-depth passes.
5. Run the smallest Mesh Editor validation gates and update this handover with
   final counts, evidence paths, unsupported families, and residual risks.
