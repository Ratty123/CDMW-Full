"""Synthetic render definitions and plan guards for the opt-in global test."""
import re
import threading
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from cdmw.core.eye_cover_overlap import RENDERPASS_PATH, rewrite_eye_cover_overlap
from cdmw.domain.mesh.shader_controls import EYE_COVER, ShaderControls, preview_factors
from cdmw.services.new_item_eye_cover_overlap import plan_eye_cover_overlap


def render_definition():
    """Small authored fixture; no shipped game resources are committed."""
    passes = []
    for name, framebuffer, pipeline, function, operation, mask, depth_count in (
        ("GBufferCharacterRenderPassNoDepthPre", "GBufferCharacter", "SkinnedMeshStandard", "Always", "Replace", "MATERIAL_ID_MASK", 2),
        ("GBufferCharacterRenderPassBindless", "GBufferCharacter", "SkinnedMeshStandard", "Equal", "Keep", "MATERIAL_ID_CHARACTER_EYE", 1),
        ("CharacterDepthPrepass", "SceneDepthCharacter", "CharacterDepthPrepass", "Always", "Replace", "MATERIAL_ID_MASK", 1),
    ):
        passes.append(f'''<RenderPass Name="{name}" FrameBuffer="{framebuffer}" Condition="MultiDraw&Windows">
<Pipeline Pass="{pipeline}">
<Element Name="MaterialType">
<PipelineState Value="Cloth" Type="Overwrite"><StencilState StencilEnable="True" StencilFunc="Equal"/></PipelineState>
<PipelineState Value="EyeCover" Type="Overwrite">
<Define Name="EYE_COVER" Value="1" CacheSuffix="ec" TargetShaders="ps"/>
<StencilState StencilEnable="True" StencilFunc="{function}" PassOp="{operation}" FailOp="Keep" DepthFailOp="Keep" ReadMaskName="{mask}" StencilRefName="MATERIAL_ID_CHARACTER_EYE"/>
{'<DepthState DepthWrite="False"/>' * depth_count}
<BlendState ColorWrite="RGBA"/>
</PipelineState>
<PipelineState Value="Tear" Type="Overwrite"><StencilState StencilEnable="True"/></PipelineState>
</Element>
<PixelShader Filename="Character.hlsl" EntryPoint="PSMain"/>
</Pipeline>
</RenderPass>''')
    passes.append('<RenderPass Name="CharacterBakeTexture"><PipelineState Value="EyeCover" Type="Overwrite"><Define Name="EYE_COVER" Value="1"/></PipelineState></RenderPass>')
    return b"\xef\xbb\xbf" + "\r\n".join(passes).replace("\n", "\r\n").encode()


def choice(value=1.):
    return ShaderControls(EYE_COVER.shader, (("global_overlap_test", (value,)),))


def test_preserves_other_materials_byte_for_byte_and_keeps_depth_testing():
    source = render_definition()
    result = rewrite_eye_cover_overlap(source)
    pattern = rb'<PipelineState\b[^>]*Value="EyeCover"[^>]*>.*?</PipelineState>'
    before = re.findall(pattern, source, re.S)
    after = re.findall(pattern, result, re.S)
    assert len(after) == len(before) == 4 and before[-1] == after[-1]
    assert re.sub(pattern, b"EYE", source, flags=re.S) == re.sub(pattern, b"EYE", result, flags=re.S)
    for index, (old, new) in enumerate(zip(before[:3], after[:3])):
        parsed = ET.fromstring(new)
        assert parsed.find("StencilState").get("StencilEnable") == "False"
        for state in parsed.findall("DepthState"):
            assert state.get("DepthWrite") == "False"
            if index != 2:
                assert state.get("DepthEnable") == "True" and state.get("DepthFunc") == "GreaterEqual"
        scrub = lambda value: re.sub(rb'<(?:StencilState|DepthState)\b[^>]*/>', b"STATE", value)
        assert scrub(old) == scrub(new)
    assert result.startswith(b"\xef\xbb\xbf")
    assert rewrite_eye_cover_overlap(result) == result
    assert source == render_definition()


@pytest.mark.parametrize("old,new", [
    (b'Value="EyeCover"', b'Value="Other"'),
    (b'PassOp="Replace"', b'PassOp="Zero"'),
    (b'DepthWrite="False"', b'DepthWrite="True"'),
    (b'FrameBuffer="GBufferCharacter"', b'FrameBuffer="Other"'),
    (b'Pass="SkinnedMeshStandard"', b'Pass="Other"'),
    (b'Name="EYE_COVER" Value="1"', b'Name="EYE_COVER" Value="0"'),
    (b'ReadMaskName="MATERIAL_ID_MASK"', b'ReadMaskName="Other"'),
    (b'<DepthState DepthWrite="False"/>', b'<DepthState DepthWrite="False"></DepthState>'),
])
def test_changed_definitions_fail_closed(old, new):
    with pytest.raises(ValueError):
        rewrite_eye_cover_overlap(render_definition().replace(old, new, 1))


def test_duplicate_missing_invalid_and_oversized_definitions_are_rejected():
    source = render_definition()
    first = re.search(rb'<RenderPass\b.*?</RenderPass>', source, re.S).group()
    for data in (source + first, source.replace(first, b""), b"\xff", b" " * (2 * 1024 * 1024 + 1)):
        with pytest.raises(ValueError):
            rewrite_eye_cover_overlap(data)
    # Commented-out examples are not live passes.
    commented = source + b"<!--" + first + b"-->"
    assert rewrite_eye_cover_overlap(commented).endswith(b"<!--" + first + b"-->")


def test_export_toggle_is_validated_persisted_and_does_not_change_pac_or_preview():
    from cdmw.core.material_shader_controls import rewrite_shader_controls
    from tests.test_shader_controls import material
    from cdmw.domain.new_item.authoring import VariantAppearance
    from cdmw.domain.new_item.spec import NewItemSpec
    selected = choice()
    assert ShaderControls.from_dict(selected.to_dict()) == selected
    assert preview_factors(selected) == preview_factors(choice(0.))
    for value in (.5, -1., 2., float("nan"), True):
        with pytest.raises(ValueError):
            choice(value).validate()
    paths = {"blade": {"_alphaTexture": "owned/alpha.dds", "_materialTexture": "owned/material.dds"}}
    outputs = [rewrite_shader_controls(material(), (("Blade", settings),), texture_paths=paths)[0]
               for settings in (selected, choice(0.), ShaderControls(EYE_COVER.shader))]
    assert outputs[0] == outputs[1] == outputs[2]
    assert "global_overlap_test" not in outputs[0]
    spec = NewItemSpec(1, "overlap", shader_controls=(("Blade", selected),),
                       variants=(VariantAppearance("prefab", "model", shader_controls=(("Blade", selected),)),))
    assert spec.needs_own_family
    assert spec.variants[0].shader_controls == spec.shader_controls


def planner_stub(*, variants=None, enabled=True, base=None, data=None):
    from cdmw.domain.cancellation import raise_if_cancelled
    selected = (("Blade", choice()),) if enabled else ()
    payloads = {RENDERPASS_PATH: render_definition()} if data is None else data
    patches = []
    stop = threading.Event()
    planner = SimpleNamespace(spec=SimpleNamespace(variants=variants, shader_controls=selected),
        snapshot=SimpleNamespace(base_manifest=base or {}, has_entry=payloads.__contains__,
            payload=payloads.__getitem__, entry=lambda path: SimpleNamespace(path=path)),
        check=lambda: raise_if_cancelled(stop), patch=lambda *args: patches.append(args),
        warnings=[], manifest={})
    return planner, patches, stop


def test_off_does_not_read_definitions_and_variants_override_legacy_selection():
    for planner in (planner_stub(enabled=False, data={})[0], planner_stub(variants=(), data={})[0]):
        plan_eye_cover_overlap(planner)
        assert not planner.manifest and not planner.warnings
    variants = tuple(SimpleNamespace(shader_controls=(("Blade", choice()),)) for _ in range(2))
    planner, patches, _ = planner_stub(variants=variants, enabled=False)
    plan_eye_cover_overlap(planner)
    assert len(patches) == 1 and patches[0][0].path == RENDERPASS_PATH
    assert planner.manifest["eye_cover_overlap_test"]["scope"] == "all_eye_cover_materials"


def test_invalid_missing_and_cancelled_plans_never_publish_a_patch():
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.services.new_item_planning import NewItemPlanError
    for data in ({}, {RENDERPASS_PATH: b"invalid"}):
        planner, patches, _ = planner_stub(data=data)
        with pytest.raises(NewItemPlanError):
            plan_eye_cover_overlap(planner)
        assert not patches and not planner.manifest
    planner, patches, stop = planner_stub()
    stop.set()
    with pytest.raises(RunCancelled):
        plan_eye_cover_overlap(planner)
    assert not patches


def test_combined_base_retains_warning_and_provenance_when_checkbox_is_off():
    inherited = {"eye_cover_overlap_test": {"version": 1, "scope": "all_eye_cover_materials", "path": RENDERPASS_PATH}}
    planner, patches, _ = planner_stub(enabled=False, base=inherited, data={})
    plan_eye_cover_overlap(planner)
    assert planner.manifest == inherited and not patches
    assert "base without that test" in planner.warnings[0]


def test_export_retirement_requires_matching_item_and_content(tmp_path, monkeypatch):
    import hashlib
    import json
    from cdmw.services.new_item_eye_cover_overlap import retire_exported_overlap_test
    payload = rewrite_eye_cover_overlap(render_definition())
    plan = SimpleNamespace(manifest={}, spec=SimpleNamespace(item_key=12))
    metadata = tmp_path / "new-item.json"
    monkeypatch.setattr("cdmw.core.mod_export_history.mod_metadata_path", lambda *_a, **_k: metadata)
    with pytest.raises(ValueError, match="new mod folder"):
        retire_exported_overlap_test(plan, tmp_path, payload)
    recorded = {"item_key": 12, "eye_cover_overlap_test": {"version": 1, "path": RENDERPASS_PATH,
                "output_sha256": hashlib.sha256(payload).hexdigest()}}
    metadata.write_text(json.dumps(recorded))
    assert retire_exported_overlap_test(plan, tmp_path, payload)
    assert not retire_exported_overlap_test(plan, tmp_path, render_definition())
    for edited in (payload + b"<!-- another mod -->",):
        with pytest.raises(ValueError, match="new mod folder"):
            retire_exported_overlap_test(plan, tmp_path, edited)
    plan.spec.item_key = 13
    with pytest.raises(ValueError, match="new mod folder"):
        retire_exported_overlap_test(plan, tmp_path, payload)
    plan.manifest = recorded
    assert not retire_exported_overlap_test(plan, tmp_path, payload)
