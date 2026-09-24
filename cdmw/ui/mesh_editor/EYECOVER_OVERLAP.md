# EyeCover and overlapping translucent islands

Investigation: 2026-09-25. Evidence is installed shader/render-definition inspection
and the user's in-game isolation test, not a GPU capture or a verified rendering fix.

## What was established

The custom sword's skull and horns share an EyeCover part. They can still be
separate connected components: hiding one component changes its triangle indices
without splitting the part or changing the material. The user reports that the
triangle flicker occurs when translucent horns overlap. The earlier experiment
disabling conservative rasterization did not resolve it.

A read-only scan of the existing shader index found two installed `PSMain`
variants with `BindlessParameters_SkinnedMeshEyeCover`. Both were extracted and
disassembled with the installed Windows SDK's DXC. The relevant behavior is:

- Read albedo, normal and character data at the current screen pixel through
  ordinary `RWTexture2D` UAV bindings.
- Combine that previously rendered data with the EyeCover material, then emit
  `SV_Target0` through `SV_Target3`. These variants have no `textureStore` calls:
  their output is through render targets, not direct UAV stores.
- No rasterizer-ordered texture declarations were found in either variant.
- The EyeCover render-definition override disables depth writes. The currently
  repaired mod also disables its eye-only stencil restriction and tests scene
  depth using `GreaterEqual`, allowing the weapon to cover ordinary scene pixels.

Exact archive paths, container fingerprints, extracted game payloads and
disassembly remain in the local investigation report outside the repository.

## Likely mechanism and limits

This is shader-side composition of scene buffers, rather than ordinary sorted
alpha blending. Multiple EyeCover surfaces can cover one pixel while reading its
existing scene data. A feedback/ordering problem is consistent with the user's
overlap-only symptom. It is not yet proven that both views alias the same runtime
resource, which compiled variant is bound in the failing frame, or which exact
access is responsible. Those questions require a GPU capture of the overlap.

Microsoft documents that ordinary UAV accesses lack the output-order guarantees
of the fixed-function pipeline. Rasterizer-ordered views provide ordering between
overlapping invocations, but require shader declarations and a suitable algorithm;
they are not enabled by `ConservativeMode` or a blend checkbox.
[Direct3D 12 rasterizer-ordered views](https://learn.microsoft.com/en-us/windows/win32/direct3d12/rasterizer-order-views).

## Feasible directions

| Approach | Expected tradeoff / remaining proof |
| --- | --- |
| Exclude, move, or make selected overlapping pieces opaque | Avoids stacking EyeCover at the same pixels; changes the model/look. Island controls provide selection and reversible exclusion. Per-island materials require separating geometry with the existing Free Edit tools. |
| Ghost/dithered cutout shader | A different transparency mechanism, already identified in shipped shaders. Not smooth glass; needs an in-game material test on this weapon. |
| Late EyeCover depth writes | A diagnostic nearest-surface workaround, not correct layered transparency. May suppress rear surfaces; ordering with the character pass must be verified. |
| EyeCover depth prepass in the shared scene depth | Can prevent the character behind it from rendering in the later Equal-depth pass. Do not reintroduce this as an automatic fix. |
| Separate nearest-cover depth/composition pass or correctly ordered shader composition | Can address the rendering mechanism, but needs shader/pass changes, binding validation and in-game proof. Ordered composition alone does not supply correct depth sorting. |

No render-state change was promoted to a new default from this investigation.
The next decisive evidence is a GPU capture identifying the EyeCover draw and
its input/output resources. A safe full fix cannot currently be claimed from XML
flags alone, and the one-horn control should be retained for comparison.
