# Experimental shader controls

**Create New Item → Model & Placement → Appearance → Shader experiments** and
**Mesh Editor → Parts → Shader experiments** share the controls below. Select a
part and experiment, then check the fields to override. Unchecked fields retain
authored values; disabled numbers show defaults, not source readback. Restore
removes the experiment. Mesh Editor supports Undo/Redo and replacement drafts.
Saved replacement drafts can apply and restore shader controls using their captured
dependencies without reopening the game archive.
Mesh Editor numbers offer sliders as well as typed values. New Item numbers accept
wheel adjustment when focused. An incompatible choice saved by an older build must
be restored in Model & Placement → Appearance before Perks & Effects can prepare it.

## Transparency limitations

**Transparency limitation:** Overlapping transparent surfaces may show visible
triangles or other visual glitches in game, even within the same model. Avoid
overlapping transparent surfaces where possible. Mesh Editor shows this warning
beside its Translucency controls; the preview may not show the issue.

## Transparent surface blending

Create New Item additionally offers **Transparent surface blending (experimental)**
with Colour mixing, Surface detail and shine, Colour reduction, Roughness and
Metallic overrides. It uses the game's `SkinnedMeshEyeCover` shader.
Its approximate viewport preview separates colour coverage from surface detail
and shine, without reproducing the game's character-buffer blend; see
[Create New Item](../new_item/README.md) for controls, defaults and limitations.
It is not included in Mesh Editor's experiment catalogue.

## Experiment compatibility

| Experiment | Supported source | Behaviour |
| --- | --- | --- |
| Patterned reveal | `SkinnedMeshWing`, or plain `SkinnedMeshStandard` / `SkinnedMeshEmissive` with a base map | Progress and inverse mask. Binary cutout; increasing progress reveals more. Converted plain materials start fully retained at progress 2. |
| Torn cloth | `SkinnedMeshTornCloth_Ver2` | Cross-grain tear and two pattern scales. Requires vertex colour R/G; white disables each corresponding tear. |
| Moving hair textures | `SkinnedMeshHairAnimatedUV` | U/V spatial frequency, speed and amplitude. Movement is attenuated by `1 - vertex green`. Zero amplitude stops motion. |
| Surface detail and roughness | `SkinnedMeshAnisotropy` | Detail-normal strength/scale and low roughness byte. The byte acts only when source hair dye alpha is nonzero. Other packed bytes and dye colour are preserved. |
| Glowing band sweep | `SkinnedMeshPoster` | Noise, width/exponent, ratio, progress and RGB colour. Progress between 0.001 and 1 selects a sweep that ignores ratio. Progress 1 exits the sweep; it does not remove the mesh. |
| Object dissolve | Existing `Dissolve` PAMI on a static object in Mesh Editor | Sphere ratio/radius, positive hardness, centre/position, noise scale/speed/strength, edge glow and inversion. Other flag bits are preserved. |

Layered Standard, ordinary Hair, other cloth shaders and Glass cannot silently
become the shared equipment experiments above. New Item's explicit Transparent surface blending
experiment also accepts plain Translucent sources. Object dissolve is unavailable on New Item
equipment. Restore Glow/Translucency overrides before choosing another experiment
on the same part. Authored glow maps and unrelated parameters remain; their game
shader support still needs testing.

### Template and external material checks

For template models, New Item reads shader compatibility while preparing the
template in the background. The experiment selector enables only compatible
families for the selected part and variant, and shows the source shader. An
unsupported experiment cannot enter the draft and block later Glow or Translucency
preview updates. This does not add TornCloth support to ordinary armour. Restore
source shader controls to clear an incompatible choice made in an older build.

External Plain PBR imports offer Patterned reveal on opaque materials. Authored glass
does not offer that conversion; both also offer New Item's Transparent surface blending.
Builder/prebuilt imports without proven source bindings
keep experiments disabled. Unchecking Reveal progress on a Plain PBR conversion uses
the same fully revealed value (2) in live preview, prepared scenes, Effects and export;
existing Wing template materials still inherit their authored progress.

### Source mask bindings

Existing mask/normal bindings are retained. Default Wing, TornCloth, Poster and
Dissolve masks become explicit dependencies when absent. Anisotropy needs its
authored detail mask and normal. These controls do not paint vertex masks,
generate fire/water simulations or enable unverified switches. Texture replacement
remains in **Textures**.

## Output and preview

New Item retains choices per prefab/model variant through planning, Effects and
dye previews. Imported names resolve through source-owned draw sections. Parts in
one atlas need identical settings or separate imports. Missing or ambiguous
bindings stop preparation. Selected fields retain source types and ItemIDs;
additions use known donor IDs or the existing named-field writer convention.
Acceptance of new parameters by the game remains unverified for some families.
Material edits do not rewrite geometry or installed archives.

Preview masks use R/G at offsets 36/37 in supported 40-byte PAC vertices. Canonical
vertices match by source offsets or unambiguous position/UV pairs. Unknown and
generated data is never replaced by mean colours; TornCloth/HairAnimatedUV leave
those vertices unaffected. Cloning, placement and part filtering retain known
masks. Materials load in background workers; numeric Mesh Editor edits reuse base
textures and published mask resources. Cancelled/failed staging does not commit
the edit. New Item cache identities include shader choices.

After applying in Mesh Editor, mask diagnostics report known vertex counts, R/G
ranges and enabled tear/motion gates. Anisotropy reports the low roughness byte
and whether source dye alpha enables it. These readouts describe the decoded
source and current preview; they do not infer missing vertex colours.

The renderer implements recovered Wing/TornCloth discard rules and HairAnimatedUV
displacement. Anisotropic normal combination, Poster lighting/bands and Dissolve
noise/edge glow are approximations. Dissolve centre 0 needs the game player and
leaves the preview visible; centres 1/2 use preview object/world coordinates.
Raw animation time, shadows, refraction and other game passes may differ.

## Implementation and checks

`cdmw/domain/mesh/shader_controls.py` owns the catalogue, ranges and factor order;
`cdmw/core/material_shader_controls.py` owns typed XML edits and compatibility.
`cdmw/services/{mesh,new_item}_shader_controls.py` integrates existing output
routes. Replacement draft version 12 stores controls; older versions still load.
The two shader preview services prepare resources off the UI thread.

`tests/test_shader_controls.py` covers output/ownership, vertex masks, variants,
drafts, undo, cancellation, cache reuse and Qt controls. Rust tests cover optional
mask transport, material ownership and headless interactions. The synthetic D3D12
gate exercises cutouts, UV motion, detail normals, glow sweeps and object clipping.
`tests/test_material_edit_bindings.py` checks distinct PAC part/material names,
shared wrapper ownership, lower-LOD isolation, all three appearance commands,
and both New Item preview stages. Headless wheel and slider tests exercise value
changes through their actual widgets and commands.
These checks do not prove packaged-helper, visible-session or in-game parity.
