"""Conservative, byte-preserving edits for the global EyeCover overlap test.

The shipped render definitions are XML fragments with unescaped conditions.
Only isolated PipelineState fragments are parsed; the surrounding file, shader
defines, cache identities and other materials are preserved verbatim.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET


RENDERPASS_PATH = "renderpass/renderpassgbuffercharacter.xml"
_TARGETS = (
    ("GBufferCharacterRenderPassNoDepthPre", "GBufferCharacter", "SkinnedMeshStandard", "Always", "Replace", "MATERIAL_ID_MASK", 2),
    ("GBufferCharacterRenderPassBindless", "GBufferCharacter", "SkinnedMeshStandard", "Equal", "Keep", "MATERIAL_ID_CHARACTER_EYE", 1),
    ("CharacterDepthPrepass", "SceneDepthCharacter", "CharacterDepthPrepass", "Always", "Replace", "MATERIAL_ID_MASK", 1),
)
_DEPTH = {"DepthEnable": "True", "DepthWrite": "False", "DepthFunc": "GreaterEqual"}


def _one(pattern, text, label):
    matches = list(re.finditer(pattern, text, re.S))
    if len(matches) != 1:
        raise ValueError(f"{label}: expected one definition, found {len(matches)}")
    return matches[0]


def rewrite_eye_cover_overlap(payload: bytes) -> bytes:
    """Disable EyeCover stencil use and retain depth-tested G-buffer blending.

Accept the known stock states or this exact experiment (for combined mod bases).
Reject changed/ambiguous definitions rather than guessing at another game build.
This changes no draw ordering and is not proof of a working in-game result.
"""
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("render definition exceeds 2 MiB")
    text = payload.decode("utf-8")
    # Ignore commented-out examples without changing match offsets.
    searchable = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group()), text, flags=re.S)
    edits = []
    for name, framebuffer, pipeline, function, operation, mask, depth_count in _TARGETS:
        render = _one(r'<RenderPass\b[^>]*\bName="' + name + r'"[^>]*>.*?</RenderPass>', searchable, name)
        opening = render.group().split(">", 1)[0]
        if f'FrameBuffer="{framebuffer}"' not in opening:
            raise ValueError(f"{name}: unexpected framebuffer")
        owner = _one(r'<Pipeline\b[^>]*\bPass="' + pipeline + r'"[^>]*>.*?</Pipeline>', render.group(), name)
        state = _one(r'<PipelineState\b[^>]*\bValue="EyeCover"[^>]*>.*?</PipelineState>', owner.group(), name)
        start = render.start() + owner.start() + state.start()
        end = start + len(state.group())
        block = text[start:end]
        root = ET.fromstring(block)
        if root.get("Type") != "Overwrite" or root.find('./Define[@Name="EYE_COVER"][@Value="1"]') is None:
            raise ValueError(f"{name}: unexpected EyeCover permutation")
        stencil = root.findall("StencilState")
        expected = {"StencilEnable": "True", "StencilFunc": function, "PassOp": operation,
                    "FailOp": "Keep", "DepthFailOp": "Keep", "ReadMaskName": mask,
                    "StencilRefName": "MATERIAL_ID_CHARACTER_EYE"}
        if len(stencil) != 1 or dict(stencil[0].attrib) not in (expected, {**expected, "StencilEnable": "False"}):
            raise ValueError(f"{name}: unsupported EyeCover stencil state")
        depths = root.findall("DepthState")
        allowed = ({"DepthWrite": "False"},) if framebuffer == "SceneDepthCharacter" else ({"DepthWrite": "False"}, _DEPTH)
        if len(depths) != depth_count or any(dict(depth.attrib) not in allowed for depth in depths):
            raise ValueError(f"{name}: unsupported EyeCover depth state")
        changed, count = re.subn(r'(<StencilState\b[^>]*\bStencilEnable=")(?:True|False)(")', r'\g<1>False\2', block)
        if count != 1:
            raise ValueError(f"{name}: cannot isolate the stencil state")
        if framebuffer == "GBufferCharacter":
            changed, count = re.subn(r'<DepthState\b[^>]*/>',
                                    '<DepthState DepthEnable="True" DepthWrite="False" DepthFunc="GreaterEqual"/>', changed)
            if count != depth_count:
                raise ValueError(f"{name}: cannot isolate the depth state")
        edits.append((start, end, changed))
    for start, end, changed in sorted(edits, reverse=True):
        text = text[:start] + changed + text[end:]
    return text.encode("utf-8")
