cbuffer CameraConstants : register(b0)
{
    row_major float4x4 WorldViewProjection;
    row_major float4x4 World;
    row_major float4x4 NormalWorld;
    float3 CameraPosition;
    float MaterialRoughness;
    float3 LightDirection;
    float MaterialMetallic;
    float3 LightColor;
    float MaterialHeightScale;
    float3 AmbientColor;
    float MaterialHasNormal;
    float MaterialHasBase;
    float MaterialHasSpecular;
    float MaterialHasRoughness;
    float MaterialHasMetallic;
    float MaterialHasHeight;
    float MaterialHasEmissive;
    float MaterialDebugMode;
    float MaterialNormalYInverted;
    float4 MaterialBaseAdjustments;
    float4 MaterialBaseTint;
    float4 MaterialBaseTintPolicy;
    float4 MaterialTint;
    float4 MaterialBaseAdvanced;
    float4 MaterialBasePost;
    float4 MaterialSurfaceOverrides;
    float4 MaterialSurfaceOverrideFlags;
    float4 MaterialSurfaceTransforms;
    float4 MaterialSurfaceTransforms2;
    float4 MaterialSurfaceBlends;
    float4 MaterialEmissiveOverride;
    float4 MaterialEmissiveOverrideFlags;
    float4 MaterialChannelSelectors;
    float4 PresentationUvScaleOffset;
    float4 PresentationUvRotationFlip;
    float4 PresentationSurfaceTuning;
    float4 PresentationToneTuning;
    float4 PresentationLightingTuning;
    float4 PresentationMaterialTuning;
    float4 PresentationDiagnosticTuning;
    float4 MaterialAlphaPolicy;
    float4 MaterialAdditionalMaps;
    float4 MaterialFamilyPolicy;
    // x: the base tint was authored by the user rather than inferred from a
    // sidecar, so the metal-category damping below must not apply. y/z/w spare.
    float4 MaterialBaseTintAuthored;
    // x: a strand-direction (flow) map is bound. y: shift of the secondary
    // highlight along the strand. z/w spare.
    float4 MaterialHairAnisotropy;
};

Texture2D BaseTexture : register(t0);
Texture2D NormalTexture : register(t1);
Texture2D SpecularTexture : register(t2);
Texture2D RoughnessTexture : register(t3);
Texture2D MetallicTexture : register(t4);
Texture2D HeightTexture : register(t5);
Texture2D EmissiveTexture : register(t6);
Texture2D LayerMaskTexture : register(t7);
Texture2D OpacityTexture : register(t8);
Texture2D OcclusionTexture : register(t9);
Texture2D FlowTexture : register(t10);
SamplerState MaterialSampler : register(s0);

cbuffer OverlayConstants : register(b1)
{
    row_major float4x4 OverlayWorldViewProjection;
    float4 OverlayColor;
    float4 OverlayMarkerSettings;
};

struct VSInput
{
    float3 Position : POSITION;
    float3 Normal : NORMAL;
    float3 Tangent : TANGENT;
    float3 Bitangent : BINORMAL;
    float2 TexCoord : TEXCOORD0;
};

struct VSOutput
{
    float4 Position : SV_Position;
    float3 WorldPosition : TEXCOORD0;
    float3 Normal : TEXCOORD1;
    float3 Tangent : TEXCOORD2;
    float3 Bitangent : TEXCOORD3;
    float2 TexCoord : TEXCOORD4;
};

float3 SafeNormalize(float3 value, float3 fallback)
{
    float lengthSquared = dot(value, value);
    return lengthSquared > 1e-12f ? value * rsqrt(lengthSquared) : fallback;
}

float3 SrgbUiColorToLinear(float3 color)
{
    float3 lower = color / 12.92f;
    float3 upper = pow((color + 0.055f) / 1.055f, 2.4f);
    return lerp(upper, lower, step(color, float3(0.04045f, 0.04045f, 0.04045f)));
}

float LinearToSrgbScalar(float value)
{
    float clamped = saturate(value);
    return clamped <= 0.0031308f
        ? clamped * 12.92f
        : 1.055f * pow(clamped, 1.0f / 2.4f) - 0.055f;
}

float SrgbToLinearScalar(float value)
{
    float clamped = saturate(value);
    return clamped <= 0.04045f
        ? clamped / 12.92f
        : pow((clamped + 0.055f) / 1.055f, 2.4f);
}

float3 AcesToneMap(float3 color)
{
    color = max(color, float3(0.0f, 0.0f, 0.0f));
    return saturate(
        (color * (2.51f * color + 0.03f))
        / (color * (2.43f * color + 0.59f) + 0.14f));
}

VSOutput VSMain(VSInput input)
{
    VSOutput output;
    float4 worldPosition = mul(float4(input.Position, 1.0f), World);
    output.Position = mul(float4(input.Position, 1.0f), WorldViewProjection);
    output.WorldPosition = worldPosition.xyz;
    output.Normal = SafeNormalize(mul(float4(input.Normal, 0.0f), NormalWorld).xyz, float3(0.0f, 0.0f, -1.0f));
    output.Tangent = SafeNormalize(mul(float4(input.Tangent, 0.0f), NormalWorld).xyz, float3(1.0f, 0.0f, 0.0f));
    output.Bitangent = SafeNormalize(mul(float4(input.Bitangent, 0.0f), NormalWorld).xyz, float3(0.0f, 1.0f, 0.0f));
    output.TexCoord = input.TexCoord;
    return output;
}

float3 SampleNormal(VSOutput input, float2 uv)
{
    float3 baseNormal = normalize(input.Normal);
    if (MaterialHasNormal < 0.5f)
    {
        return baseNormal;
    }
    // Source normals are BC5 two-channel maps, so the sampled blue channel is
    // always 0 and cannot be used as Z.  Rebuild Z from XY instead: tangent
    // space normals are unit length with Z >= 0, so this is also correct for
    // three-channel normal maps and needs no per-format branch.
    float2 tangentXY = NormalTexture.Sample(MaterialSampler, uv).xy * 2.0f - 1.0f;
    tangentXY.y = MaterialNormalYInverted > 0.5f ? -tangentXY.y : tangentXY.y;
    tangentXY *= saturate(PresentationMaterialTuning.w);
    float3 tangentNormal = float3(
        tangentXY,
        sqrt(saturate(1.0f - dot(tangentXY, tangentXY))));
    float3x3 tbn = float3x3(normalize(input.Tangent), normalize(input.Bitangent), baseNormal);
    return normalize(mul(tangentNormal, tbn));
}

struct OverlayVSInput
{
    float3 Position : POSITION;
};

struct OverlayVSOutput
{
    float4 Position : SV_Position;
    float4 Color : COLOR0;
    float2 MarkerOffset : TEXCOORD0;
};

OverlayVSOutput VSOverlay(OverlayVSInput input)
{
    OverlayVSOutput output;
    output.Position = mul(float4(input.Position, 1.0f), OverlayWorldViewProjection);
    output.Color = OverlayColor;
    output.MarkerOffset = float2(0.0f, 0.0f);
    return output;
}

[maxvertexcount(4)]
void GSVertexMarker(point OverlayVSOutput input[1], inout TriangleStream<OverlayVSOutput> stream)
{
    float2 viewport = max(OverlayMarkerSettings.xy, float2(1.0f, 1.0f));
    float radiusPixels = max(OverlayMarkerSettings.z * 0.5f, 0.5f);
    float2 clipRadius = float2(
        2.0f * radiusPixels / viewport.x,
        2.0f * radiusPixels / viewport.y) * input[0].Position.w;
    const float2 corners[4] =
    {
        float2(-1.0f, 1.0f),
        float2(1.0f, 1.0f),
        float2(-1.0f, -1.0f),
        float2(1.0f, -1.0f),
    };
    [unroll]
    for (int index = 0; index < 4; ++index)
    {
        OverlayVSOutput output = input[0];
        output.Position.xy += corners[index] * clipRadius;
        output.MarkerOffset = corners[index];
        stream.Append(output);
    }
}

[maxvertexcount(4)]
void GSWireLine(line OverlayVSOutput input[2], inout TriangleStream<OverlayVSOutput> stream)
{
    float2 viewport = max(OverlayMarkerSettings.xy, float2(1.0f, 1.0f));
    float startW = input[0].Position.w;
    float endW = input[1].Position.w;
    if (abs(startW) < 0.00001f || abs(endW) < 0.00001f)
    {
        return;
    }

    float2 startNdc = input[0].Position.xy / startW;
    float2 endNdc = input[1].Position.xy / endW;
    float2 deltaPixels = (endNdc - startNdc) * viewport * 0.5f;
    float lengthPixels = length(deltaPixels);
    if (lengthPixels < 0.001f)
    {
        return;
    }

    float halfWidthPixels = max(OverlayMarkerSettings.z * 0.5f, 0.5f);
    float2 perpendicularPixels = float2(-deltaPixels.y, deltaPixels.x) / lengthPixels;
    float2 clipPerPixel = 2.0f / viewport;
    float2 startOffset = perpendicularPixels * halfWidthPixels * clipPerPixel * startW;
    float2 endOffset = perpendicularPixels * halfWidthPixels * clipPerPixel * endW;

    OverlayVSOutput output = input[0];
    output.MarkerOffset = float2(0.0f, 0.0f);
    output.Position.xy = input[0].Position.xy - startOffset;
    stream.Append(output);
    output.Position.xy = input[0].Position.xy + startOffset;
    stream.Append(output);

    output = input[1];
    output.MarkerOffset = float2(0.0f, 0.0f);
    output.Position.xy = input[1].Position.xy - endOffset;
    stream.Append(output);
    output.Position.xy = input[1].Position.xy + endOffset;
    stream.Append(output);
}

float4 PSOverlay(OverlayVSOutput input) : SV_Target
{
    clip(1.0f - dot(input.MarkerOffset, input.MarkerOffset));
    return float4(SrgbUiColorToLinear(input.Color.rgb), input.Color.a);
}

float WrappedNdotL(float3 normal, float3 lightDirection, float wrap)
{
    float safeWrap = max(wrap, 0.0f);
    return saturate((dot(normal, lightDirection) + safeWrap) / (1.0f + safeWrap));
}

static const float CdmwPi = 3.14159265359f;

float DistributionGGX(float3 normal, float3 halfVector, float roughness)
{
    float alpha = roughness * roughness;
    float alphaSquared = alpha * alpha;
    float ndoth = saturate(dot(normal, halfVector));
    float denominator = ndoth * ndoth * (alphaSquared - 1.0f) + 1.0f;
    return alphaSquared / max(CdmwPi * denominator * denominator, 1e-5f);
}

float GeometrySchlickGGX(float ndotDirection, float roughness)
{
    float remapped = roughness + 1.0f;
    float k = remapped * remapped / 8.0f;
    return ndotDirection / max(ndotDirection * (1.0f - k) + k, 1e-5f);
}

float GeometrySmith(float3 normal, float3 viewDirection, float3 lightDirection, float roughness)
{
    return GeometrySchlickGGX(saturate(dot(normal, viewDirection)), roughness)
        * GeometrySchlickGGX(saturate(dot(normal, lightDirection)), roughness);
}

float3 FresnelSchlick(float cosTheta, float3 reflectanceAtNormal)
{
    return reflectanceAtNormal
        + (1.0f - reflectanceAtNormal) * pow(1.0f - saturate(cosTheta), 5.0f);
}

float3 PreviewEnvironmentRadiance(float3 reflectedView, float roughness)
{
    float safeRoughness = saturate(roughness);
    float horizonBand = pow(saturate(1.0f - abs(reflectedView.y) * 1.12f), 2.2f);
    float frontSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(-0.24f, 0.28f, -0.93f)))),
        lerp(28.0f, 5.0f, safeRoughness));
    float backSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(0.42f, 0.22f, 0.88f)))),
        lerp(24.0f, 4.5f, safeRoughness));
    float topSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(-0.12f, 0.96f, -0.25f)))),
        lerp(30.0f, 6.0f, safeRoughness));
    float sideSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(0.92f, 0.12f, -0.38f)))),
        lerp(22.0f, 4.0f, safeRoughness));
    float oppositeSideSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(-0.88f, 0.16f, -0.44f)))),
        lerp(24.0f, 4.5f, safeRoughness));
    float darkBand = pow(
        saturate(1.0f - abs(reflectedView.x * 1.35f + reflectedView.y * 0.45f)),
        3.2f) * saturate(0.95f - reflectedView.z);
    float3 radiance = float3(0.016f, 0.017f, 0.020f);
    radiance += horizonBand * float3(0.10f, 0.11f, 0.13f);
    radiance += frontSoftbox * float3(1.16f, 0.94f, 0.70f);
    radiance += backSoftbox * float3(0.92f, 0.66f, 0.42f);
    radiance += topSoftbox * float3(0.46f, 0.62f, 0.92f);
    radiance += sideSoftbox * float3(0.32f, 0.50f, 0.88f);
    radiance += oppositeSideSoftbox * float3(0.12f, 0.14f, 0.17f);
    radiance *= lerp(1.0f, 0.08f, darkBand * lerp(0.94f, 0.45f, safeRoughness));
    float roughnessBlur = safeRoughness * safeRoughness * 0.58f;
    radiance = lerp(radiance, float3(0.075f, 0.080f, 0.090f), roughnessBlur);
    return clamp(
        radiance,
        float3(0.012f, 0.012f, 0.012f),
        float3(1.25f, 1.25f, 1.25f));
}

float3 SourceStableFresnel(float cosTheta, float3 reflectanceAtNormal)
{
    return FresnelSchlick(cosTheta, reflectanceAtNormal);
}

float3 WorkbenchGeometryColor(VSOutput input)
{
    // Textureless previews use a neutral clay surface. A small deterministic
    // per-part tone shift separates adjacent pieces without implying a real
    // material or texture, while the studio lights preserve surface contour.
    float partTone = (frac((PresentationDiagnosticTuning.x + 1.0f) * 0.6180339f) - 0.5f) * 0.08f;
    float3 geometryColor = saturate(
        float3(0.58f, 0.65f, 0.75f)
        + partTone * float3(0.75f, 1.0f, 1.15f));
    if (PresentationSurfaceTuning.w > 0.5f)
    {
        return geometryColor;
    }

    const float3 viewDirection = float3(0.0f, 0.0f, -1.0f);
    float3 normal = SafeNormalize(input.Normal, viewDirection);
    normal = dot(normal, viewDirection) < 0.0f ? -normal : normal;
    const float3 keyDirection = float3(-0.42f, 0.58f, -0.70f);
    const float3 fillDirection = float3(0.55f, -0.22f, -0.80f);
    float keyLight = pow(WrappedNdotL(normal, keyDirection, 0.10f), 1.12f);
    float fillLight = WrappedNdotL(normal, fillDirection, 0.28f);
    float cameraShape = saturate(dot(normal, viewDirection));
    float rimShape = pow(saturate(1.0f - cameraShape), 1.35f);
    const float minimumIllumination = 0.38f;
    float illumination = minimumIllumination
        + keyLight * 0.48f
        + fillLight * 0.16f
        + cameraShape * 0.05f
        + rimShape * 0.025f;
    return saturate(SrgbUiColorToLinear(geometryColor) * illumination);
}

float4 PSMain(VSOutput input, bool isFrontFace : SV_IsFrontFace) : SV_Target
{
    if (MaterialDebugMode > 6.5f && MaterialDebugMode < 7.5f)
    {
        return float4(WorkbenchGeometryColor(input), 1.0f);
    }
    float2 uv = input.TexCoord - float2(0.5f, 0.5f);
    uv *= PresentationUvScaleOffset.xy * PresentationUvRotationFlip.zw;
    uv = float2(
        uv.x * PresentationUvRotationFlip.x - uv.y * PresentationUvRotationFlip.y,
        uv.x * PresentationUvRotationFlip.y + uv.y * PresentationUvRotationFlip.x);
    uv += float2(0.5f, 0.5f) + PresentationUvScaleOffset.zw;
    float4 baseColor = MaterialHasBase > 0.5f
        ? BaseTexture.Sample(MaterialSampler, uv)
        : (MaterialBaseTint.w > 0.5f
            ? float4(SrgbUiColorToLinear(saturate(MaterialBaseTint.rgb)), 1.0f)
            : (MaterialTint.w > 0.5f ? float4(1.0f, 1.0f, 1.0f, 1.0f) : float4(0.55f, 0.62f, 0.72f, 1.0f)));
    float materialAlpha = MaterialAdditionalMaps.x > 0.5f
        ? OpacityTexture.Sample(MaterialSampler, uv)[(int)MaterialAdditionalMaps.z]
        : baseColor.a;
    materialAlpha *= saturate(MaterialAlphaPolicy.w);
    baseColor.a = materialAlpha;
    if (MaterialAlphaPolicy.x > 0.5f && MaterialAlphaPolicy.x < 1.5f)
    {
        clip(baseColor.a - MaterialAlphaPolicy.y);
    }
    if (MaterialHasBase > 0.5f && MaterialBaseTintPolicy.x > 0.001f)
    {
        float3 previewTint = saturate(MaterialBaseTint.rgb);
        float tintLuma = max(dot(previewTint, float3(0.299f, 0.587f, 0.114f)), 0.08f);
        float3 tintBias = clamp(
            previewTint / tintLuma,
            float3(0.38f, 0.38f, 0.38f),
            float3(1.72f, 1.72f, 1.72f));
        float tintChroma = max(previewTint.r, max(previewTint.g, previewTint.b))
            - min(previewTint.r, min(previewTint.g, previewTint.b));
        // A user-authored recolour is a deliberate act, so it opts out of the
        // metal damping below.  Without this a saturated colour on a metal part
        // resolves to a 0.05 multiplier -- a 5% repaint that reads as a washed
        // tint, while the baked DDS repaints in full.
        bool authoredBaseTint = MaterialBaseTintAuthored.x > 0.5f;
        bool earlyCategoryMetal = !authoredBaseTint
            && MaterialBaseTintPolicy.y > 0.5f
            && MaterialBaseTintPolicy.y < 1.5f;
        float neutralMetalTint = earlyCategoryMetal ? saturate((0.12f - tintChroma) * 8.0f) : 0.0f;
        // Two different operations were sharing one strength.  `colorized`
        // replaces the texture's own value with a lifted flat luma, which is
        // what turns a copper hint into paint, so chromatic metal was damped to
        // 5% to suppress it -- and that took `multiplied` down with it.
        // `multiplied` is a luma-normalised hue shift: it recolours without
        // changing brightness and keeps every texel of the source. Splitting
        // them lets an authored brass or gold tint reach the surface (and, via
        // F0, its reflection) while the painty path stays suppressed. 217 of
        // 280 sampled metal parts carry a chromatic tint, so at 5% most of the
        // game's brass and gold was resolving to grey steel.
        float metalHueOnly = earlyCategoryMetal ? (1.0f - neutralMetalTint) : 0.0f;
        float strength = saturate(MaterialBaseTintPolicy.x
            * (earlyCategoryMetal ? lerp(1.0f, 1.25f, neutralMetalTint) : 1.0f));
        float albedoLuma = dot(baseColor.rgb, float3(0.299f, 0.587f, 0.114f));
        float liftedLuma = saturate(albedoLuma * (1.05f + strength * 0.35f) + 0.10f * strength);
        // The metal tint exists to colour a shared library tile, and those tiles
        // are authored neutral -- of six sampled, four measure a chroma of
        // 0.001 or less, so the sidecar tint is the only thing saying brass or
        // verdigris. A few carry their own colour, though, and there the tint
        // would apply it twice and oversaturate, so the hue shift fades out as
        // the source texture's own chroma rises.
        float albedoChroma = max(baseColor.r, max(baseColor.g, baseColor.b))
            - min(baseColor.r, min(baseColor.g, baseColor.b));
        float sourceCarriesColor = saturate((albedoChroma - 0.05f) * 5.0f);
        float3 hueBias = lerp(
            tintBias,
            float3(1.0f, 1.0f, 1.0f),
            sourceCarriesColor * metalHueOnly);
        float3 multiplied = saturate(baseColor.rgb * hueBias);
        float3 colorized = saturate(liftedLuma.xxx * tintBias);
        float neutralMetalLuma = saturate(albedoLuma * (0.55f + tintLuma * 0.45f) + 0.012f);
        colorized = lerp(colorized, saturate(neutralMetalLuma.xxx * tintBias), neutralMetalTint);
        // Routing a chromatic metal tint through the colourise path was tried, on
        // the reasoning that the library tiles these materials draw from measure
        // 0.04 to 0.09 linear and a luma-normalised hue shift cannot brighten
        // them. It does help a gilded weapon or two, but measured against the
        // assets' own base textures over 130 weapons it cost 12% of colour
        // reproduction (0.958 to 0.883) for that, so it is not taken.
        float colorizeStrength = lerp(0.58f, 0.96f, neutralMetalTint) * (1.0f - metalHueOnly);
        baseColor.rgb = lerp(baseColor.rgb, lerp(multiplied, colorized, colorizeStrength), strength);
    }
    baseColor.rgb = saturate(baseColor.rgb * max(MaterialBaseAdjustments.x, 0.1f));
    baseColor.rgb *= max(MaterialTint.rgb, float3(0.0f, 0.0f, 0.0f));
    float materialGamma = max(MaterialBaseAdjustments.w, 0.01f);
    baseColor.rgb = pow(saturate(baseColor.rgb), float3(materialGamma, materialGamma, materialGamma));
    float baseLift = saturate(MaterialBaseAdvanced.x);
    baseColor.rgb = saturate(baseLift.xxx + baseColor.rgb * (1.0f - baseLift));
    float baseLuma = dot(baseColor.rgb, float3(0.299f, 0.587f, 0.114f));
    baseColor.rgb = saturate(baseLuma.xxx + (baseColor.rgb - baseLuma.xxx) * max(MaterialBaseAdjustments.z, 0.0f));
    baseLuma = dot(baseColor.rgb, float3(0.299f, 0.587f, 0.114f));
    float autoBalanceStrength = saturate(MaterialBaseAdvanced.z);
    float autoBalanceTarget = baseLuma < (96.0f / 255.0f)
        ? (116.0f / 255.0f)
        : (baseLuma > (158.0f / 255.0f) ? (138.0f / 255.0f) : baseLuma);
    float autoBalanceCorrection = autoBalanceStrength > 0.0f
        ? clamp(pow(autoBalanceTarget / max(baseLuma, 1.0f / 255.0f), autoBalanceStrength), 0.68f, 1.42f)
        : 1.0f;
    baseColor.rgb = saturate(baseColor.rgb * autoBalanceCorrection);
    baseLuma = dot(baseColor.rgb, float3(0.299f, 0.587f, 0.114f));
    float shadowMask = pow(saturate(((96.0f / 255.0f) - baseLuma) / (96.0f / 255.0f)), 1.5f);
    float shadowBoost = (72.0f / 255.0f) * saturate(MaterialBaseAdvanced.w);
    baseColor.rgb = lerp(baseColor.rgb, saturate(baseColor.rgb + shadowBoost), shadowMask);
    baseColor.rgb = saturate((baseColor.rgb - 0.5f) * max(MaterialBaseAdjustments.y, 0.01f) + 0.5f);
    baseColor.rgb = saturate(baseColor.rgb * max(MaterialBasePost.x, 0.0f));
    float valueCap = saturate(MaterialBaseAdvanced.y);
    baseColor.rgb = min(baseColor.rgb, valueCap.xxx);
    if (MaterialAlphaPolicy.z > 0.5f && !isFrontFace)
    {
        input.Normal = -input.Normal;
        input.Bitangent = -input.Bitangent;
    }
    float3 normal = SampleNormal(input, uv);
    float heightValue = 0.5f;
    float heightStrength = 0.0f;
    if (MaterialHasHeight > 0.5f)
    {
        heightValue = HeightTexture.Sample(MaterialSampler, uv).r;
        float2 heightUvX = ddx(uv);
        float2 heightUvY = ddy(uv);
        if (dot(heightUvX, heightUvX) < 1e-8f)
        {
            heightUvX = float2(1.0f / 1024.0f, 0.0f);
        }
        if (dot(heightUvY, heightUvY) < 1e-8f)
        {
            heightUvY = float2(0.0f, 1.0f / 1024.0f);
        }
        float heightX = HeightTexture.Sample(MaterialSampler, uv + heightUvX).r
            - HeightTexture.Sample(MaterialSampler, uv - heightUvX).r;
        float heightY = HeightTexture.Sample(MaterialSampler, uv + heightUvY).r
            - HeightTexture.Sample(MaterialSampler, uv - heightUvY).r;
        float declaredHeight = MaterialSurfaceOverrideFlags.w > 0.5f
            ? MaterialSurfaceOverrides.w
            : 0.0f;
        heightStrength = saturate(MaterialHeightScale + declaredHeight * 0.04f);
        float3 heightNormal = normalize(
            normal
            - normalize(input.Tangent) * heightX * 2.4f
            + normalize(input.Bitangent) * heightY * 2.4f);
        normal = normalize(lerp(normal, heightNormal, heightStrength));
    }
    float3 lightDirection = normalize(LightDirection);
    // The preview camera is orthographic and orbits by rotating the model.
    // Keep one view direction across the surface so material response matches
    // the native Archive renderer instead of introducing perspective Fresnel.
    const float3 viewDirection = float3(0.0f, 0.0f, -1.0f);
    float3 halfVector = normalize(lightDirection + viewDirection);

    float4 roughnessSample = MaterialHasRoughness > 0.5f
        ? RoughnessTexture.Sample(MaterialSampler, uv)
        : MaterialRoughness.xxxx;
    float roughness = roughnessSample[(int)MaterialChannelSelectors.x];
    if (MaterialSurfaceTransforms.w > 0.5f)
    {
        roughness = 1.0f - roughness;
    }
    roughness *= max(MaterialSurfaceTransforms.x, 0.0f);
    roughness = max(roughness, MaterialSurfaceTransforms.y);
    roughness = min(roughness, MaterialSurfaceTransforms.z);
    roughness = lerp(roughness, MaterialSurfaceBlends.x, saturate(MaterialSurfaceBlends.y));
    if (MaterialSurfaceOverrideFlags.x > 0.5f)
    {
        roughness = MaterialSurfaceOverrides.x;
    }
    roughness = clamp(roughness + PresentationSurfaceTuning.x, 0.04f, 1.0f);
    roughness = max(roughness, MaterialFamilyPolicy.y);
    float4 metallicSample = MaterialHasMetallic > 0.5f
        ? MetallicTexture.Sample(MaterialSampler, uv)
        : MaterialMetallic.xxxx;
    float metallic = metallicSample[(int)MaterialChannelSelectors.y];
    if (MaterialSurfaceTransforms2.w > 0.5f)
    {
        metallic = 1.0f - metallic;
    }
    metallic *= max(MaterialSurfaceTransforms2.x, 0.0f);
    metallic = max(metallic, MaterialSurfaceTransforms2.y);
    metallic = min(metallic, MaterialSurfaceTransforms2.z);
    metallic = lerp(metallic, MaterialSurfaceBlends.z, saturate(MaterialSurfaceBlends.w));
    if (MaterialSurfaceOverrideFlags.y > 0.5f)
    {
        metallic = MaterialSurfaceOverrides.y;
    }
    metallic = saturate(metallic * max(PresentationSurfaceTuning.y, 0.0f));
    if (MaterialFamilyPolicy.x > 0.5f)
    {
        // Skin and hair have no metal, so the family policy is authoritative for
        // them.  Cloth is different: garments carry metal studs, buckles and
        // trim, so an authored per-texel metal map has to survive on a cloth
        // family instead of being zeroed for the whole submesh.
        bool clothFamilyWithAuthoredMetal =
            PresentationDiagnosticTuning.w > 2.5f
            && PresentationDiagnosticTuning.w < 3.5f
            && MaterialHasMetallic > 0.5f;
        if (!clothFamilyWithAuthoredMetal)
        {
            metallic = 0.0f;
        }
    }
    // A bound roughness or metal map is measured per-texel source data.  The
    // category and family tables below are filename and shader-family guesses
    // that exist to keep untextured or unclassified parts readable, so they must
    // never clamp away real map values -- a cloth-classified part carrying a
    // metal buckle has to stay metal where the source says so.
    bool hasSourceRoughnessMap = MaterialHasRoughness > 0.5f;
    bool hasSourceMetallicMap = MaterialHasMetallic > 0.5f;
    float materialCategoryCode = MaterialBaseTintPolicy.y;
    float materialCategoryConfidence = saturate(MaterialBaseTintPolicy.z);
    bool hasSourceCategory = materialCategoryCode > 0.5f;
    bool categoryMetal = materialCategoryCode > 0.5f && materialCategoryCode < 1.5f;
    bool categoryLeather = materialCategoryCode > 1.5f && materialCategoryCode < 2.5f;
    bool categoryWood = materialCategoryCode > 2.5f && materialCategoryCode < 3.5f;
    bool sourceCategoryCloth = materialCategoryCode > 3.5f && materialCategoryCode < 4.5f;
    bool sourceCategorySkin = materialCategoryCode > 4.5f && materialCategoryCode < 5.5f;
    bool sourceCategoryHair = materialCategoryCode > 5.5f && materialCategoryCode < 6.5f;
    bool categoryGlass = materialCategoryCode > 6.5f && materialCategoryCode < 7.5f;
    bool categoryGem = materialCategoryCode > 7.5f && materialCategoryCode < 8.5f;
    bool categoryStone = materialCategoryCode > 8.5f && materialCategoryCode < 9.5f;
    bool categoryEye = materialCategoryCode > 9.5f && materialCategoryCode < 10.5f;
    bool categoryTooth = materialCategoryCode > 10.5f && materialCategoryCode < 11.5f;
    float materialFamilyCode = PresentationDiagnosticTuning.w;
    float familyMetalScale = 1.0f;
    float familySpecularScale = 1.0f;
    float familyRoughnessBias = 0.0f;
    if (materialFamilyCode > 0.5f && materialFamilyCode < 1.5f)
    {
        familyMetalScale = 0.12f;
        familySpecularScale = 1.20f;
        familyRoughnessBias = 0.06f;
    }
    else if (materialFamilyCode > 1.5f && materialFamilyCode < 2.5f)
    {
        familyMetalScale = 0.05f;
        familySpecularScale = 1.45f;
        familyRoughnessBias = -0.08f;
    }
    else if (materialFamilyCode > 2.5f && materialFamilyCode < 3.5f)
    {
        familyMetalScale = 0.28f;
        familySpecularScale = 0.95f;
        familyRoughnessBias = 0.10f;
    }
    else if (materialFamilyCode > 3.5f && materialFamilyCode < 4.5f)
    {
        familyMetalScale = 1.15f;
        familySpecularScale = 1.35f;
        familyRoughnessBias = -0.04f;
    }
    else if (materialFamilyCode > 4.5f && materialFamilyCode < 5.5f)
    {
        familyMetalScale = 1.05f;
        familySpecularScale = 1.20f;
        familyRoughnessBias = -0.02f;
    }
    else if (materialFamilyCode > 5.5f && materialFamilyCode < 6.5f)
    {
        familyMetalScale = 0.55f;
        familySpecularScale = 1.15f;
        familyRoughnessBias = -0.03f;
    }
    if (MaterialSurfaceOverrideFlags.y < 0.5f && !hasSourceMetallicMap)
    {
        metallic = saturate(metallic * familyMetalScale);
    }
    bool categorySkin = sourceCategorySkin || (!hasSourceCategory
        && materialFamilyCode > 0.5f && materialFamilyCode < 1.5f);
    bool categoryHair = sourceCategoryHair || (!hasSourceCategory
        && materialFamilyCode > 1.5f && materialFamilyCode < 2.5f);
    bool categoryCloth = sourceCategoryCloth || (!hasSourceCategory
        && materialFamilyCode > 2.5f && materialFamilyCode < 3.5f);
    bool glossyNonmetal = categoryGlass || categoryGem || categoryEye;
    bool conservativeNonmetal = categoryLeather || categoryWood || categoryCloth
        || categorySkin || categoryHair || categoryStone || categoryTooth
        || (!hasSourceCategory && MaterialFamilyPolicy.x > 0.5f);
    bool knownNonmetal = conservativeNonmetal || glossyNonmetal;
    float categoryMetalCap = (categoryMetal || hasSourceMetallicMap)
        ? 1.0f
        : (knownNonmetal ? 0.0f : lerp(0.12f, 0.32f, materialCategoryConfidence));
    float categorySpecularCap = categoryMetal
        ? 1.0f
        : (categoryGlass ? 0.42f
            : (categoryGem ? 0.48f
                : (categoryEye ? 0.44f
                    : (categoryLeather ? 0.14f
                        : (categoryWood ? 0.16f
                            : (categoryCloth ? 0.055f
                                : (categorySkin ? 0.20f
                                    : (categoryHair ? 0.22f
                                        : (categoryStone ? 0.10f
                                            : (categoryTooth ? 0.18f : 0.18f))))))))));
    float categoryRoughnessFloor = hasSourceRoughnessMap
        ? 0.0f
        : (categoryMetal ? 0.16f
            : (categoryGlass ? 0.30f
                : (categoryGem ? 0.26f
                    : (categoryEye ? 0.30f
                        : (categoryLeather ? 0.76f
                            : (categoryWood ? 0.70f
                                : (categoryCloth ? 0.84f
                                    : (categorySkin ? 0.58f
                                        : (categoryHair ? 0.64f
                                            : (categoryStone ? 0.82f
                                                : (categoryTooth ? 0.58f : 0.66f)))))))))));
    float categoryEnvironmentScale = categoryMetal
        ? 0.94f
        : (categoryGlass ? 0.26f
            : (categoryGem ? 0.30f
                : (categoryEye ? 0.24f
                    : (categoryLeather ? 0.06f
                        : (categoryWood ? 0.06f
                            : (categoryCloth ? 0.025f
                                : (categorySkin ? 0.075f
                                    : (categoryHair ? 0.08f
                                        : (categoryStone ? 0.04f
                                            : (categoryTooth ? 0.08f : 0.08f))))))))));
    if (!categoryMetal && hasSourceRoughnessMap)
    {
        // Same reasoning as the direct lobe: the per-category environment
        // constants existed to divide out an inflated F0.  With a real roughness
        // map the surface can take a normal share of the environment, and its own
        // roughness decides how much of that reads as a highlight.
        categoryEnvironmentScale = max(categoryEnvironmentScale, 0.45f);
    }
    float materialRoughnessHint = saturate(MaterialBasePost.y);
    float materialMetalnessHint = saturate(MaterialBasePost.z);
    float materialSpecularHint = saturate(MaterialBasePost.w);
    uint materialHintPresence = (uint)round(MaterialChannelSelectors.w);
    bool hasMaterialRoughnessHint = (materialHintPresence & 1u) != 0u;
    bool hasMaterialMetalnessHint = (materialHintPresence & 2u) != 0u;
    bool hasMaterialSpecularHint = (materialHintPresence & 4u) != 0u;
    if (hasMaterialMetalnessHint && materialMetalnessHint > 0.02f)
    {
        metallic = max(
            metallic,
            saturate(materialMetalnessHint * max(PresentationSurfaceTuning.y, 0.0f)));
    }
    bool explicitMaterialAuthorityHint = hasMaterialRoughnessHint
        || hasMaterialMetalnessHint
        || hasMaterialSpecularHint
        || (MaterialSurfaceOverrideFlags.w > 0.5f && MaterialSurfaceOverrides.w > 0.02f);
    if (explicitMaterialAuthorityHint && !conservativeNonmetal)
    {
        float glossHint = saturate(
            (hasMaterialRoughnessHint ? (1.0f - materialRoughnessHint) * 0.85f : 0.0f)
            + (hasMaterialSpecularHint ? materialSpecularHint * 0.45f : 0.0f));
        if (glossHint > 0.001f || (hasMaterialSpecularHint && materialSpecularHint > 0.001f))
        {
            categorySpecularCap = max(
                categorySpecularCap,
                max(hasMaterialSpecularHint ? materialSpecularHint : 0.0f, glossHint));
            categoryEnvironmentScale = max(
                categoryEnvironmentScale,
                lerp(0.12f, 0.42f, glossHint));
        }
        if (hasMaterialRoughnessHint)
        {
            categoryRoughnessFloor = min(
                categoryRoughnessFloor,
                lerp(0.08f, 0.42f, materialRoughnessHint));
        }
    }
    if (hasMaterialRoughnessHint)
    {
        // The sidecar hint is one scalar for the whole submesh.  It stands in
        // for a missing map, but against a real one it would flatten per-texel
        // variation toward a constant, so it only nudges when a map is bound.
        roughness = lerp(
            roughness,
            materialRoughnessHint,
            hasSourceRoughnessMap ? 0.15f : 0.55f);
    }
    roughness = saturate(roughness + familyRoughnessBias);
    float textureLuma = dot(baseColor.rgb, float3(0.299f, 0.587f, 0.114f));
    float materialLift = categoryMetal ? 0.020f : (categorySkin ? 0.025f : (categoryHair ? 0.035f : 0.030f));
    float clothHighLumaGuard = categoryCloth ? saturate((textureLuma - 0.82f) * 4.0f) : 0.0f;
    float clothTextureBoost = categoryCloth ? lerp(0.03f, -0.02f, clothHighLumaGuard) : 0.0f;
    float3 materialReferenceAlbedo = saturate(
        baseColor.rgb * (1.03f + clothTextureBoost)
        + materialLift.xxx * saturate(1.0f - textureLuma));
    if (categorySkin)
    {
        materialReferenceAlbedo = saturate(
            materialReferenceAlbedo * 1.04f + float3(0.004f, 0.002f, 0.001f));
    }
    if (categoryCloth && clothHighLumaGuard > 0.001f)
    {
        float3 clothHighlightCap = float3(0.94f, 0.91f, 0.84f);
        materialReferenceAlbedo = lerp(
            materialReferenceAlbedo,
            min(materialReferenceAlbedo, clothHighlightCap),
            clothHighLumaGuard * 0.35f);
    }
    if (
        MaterialHasHeight < 0.5f
        && MaterialSurfaceOverrideFlags.w > 0.5f
        && MaterialSurfaceOverrides.w > 0.02f)
    {
        float reliefEdge = saturate(
            (abs(ddx(textureLuma)) + abs(ddy(textureLuma))) * 34.0f);
        float reliefStrength = saturate(MaterialSurfaceOverrides.w);
        materialReferenceAlbedo = saturate(
            materialReferenceAlbedo * (1.0f + reliefEdge * reliefStrength * 0.24f)
            - (1.0f - reliefEdge) * reliefStrength * 0.018f);
    }
    if (
        hasMaterialRoughnessHint
        && materialRoughnessHint > 0.62f
        && !conservativeNonmetal)
    {
        float mattePreview = saturate((materialRoughnessHint - 0.62f) * 2.63f);
        float matteLuma = dot(
            materialReferenceAlbedo,
            float3(0.299f, 0.587f, 0.114f));
        float3 flattenedMaterial = lerp(
            materialReferenceAlbedo,
            matteLuma.xxx,
            0.42f);
        materialReferenceAlbedo = lerp(
            materialReferenceAlbedo,
            flattenedMaterial * 0.88f + 0.018f.xxx,
            mattePreview * 0.58f);
    }
    if (categoryMetal && MaterialBaseTintPolicy.x > 0.001f)
    {
        float3 metalTint = saturate(MaterialBaseTint.rgb);
        float metalTintLuma = max(
            dot(metalTint, float3(0.299f, 0.587f, 0.114f)),
            0.08f);
        float3 metalTintBias = clamp(
            metalTint / metalTintLuma,
            float3(0.58f, 0.58f, 0.58f),
            float3(1.42f, 1.42f, 1.42f));
        materialReferenceAlbedo = saturate(lerp(
            materialReferenceAlbedo,
            materialReferenceAlbedo * metalTintBias,
            0.34f * saturate(MaterialBaseTintPolicy.x)));
    }
    float categoryMetalFallback = categoryMetal
        ? saturate(lerp(0.28f, 0.62f, materialCategoryConfidence)
            * max(PresentationSurfaceTuning.y, 0.0f))
        : 0.0f;
    bool hasMetalResponseInput = MaterialHasMetallic > 0.5f
        || (MaterialSurfaceOverrideFlags.y > 0.5f && MaterialSurfaceOverrides.y > 0.02f)
        || (hasMaterialMetalnessHint && materialMetalnessHint > 0.02f);
    if (categoryMetal && !hasMetalResponseInput)
    {
        metallic = max(metallic, categoryMetalFallback);
        roughness = min(roughness, lerp(0.46f, 0.28f, materialCategoryConfidence));
    }
    bool directMetalResponse = categoryMetal && (
        metallic > 0.12f
        || (hasMaterialMetalnessHint && materialMetalnessHint > 0.16f)
        || MaterialHasMetallic > 0.5f
        || MaterialBaseTintPolicy.w > 0.5f);
    if (directMetalResponse)
    {
        // Promotion only substitutes for missing data.  A part classified as
        // metal that ships real maps is often mixed -- a steel blade with a
        // leather grip shares one material texture -- so forcing a metal floor
        // and a smooth ceiling across the whole surface would erase the split
        // the source actually authored.
        if (!hasSourceMetallicMap)
        {
            metallic = max(metallic, categoryMetalFallback);
        }
        if (!hasSourceRoughnessMap)
        {
            roughness = min(roughness, lerp(0.34f, 0.16f, materialCategoryConfidence));
            categoryRoughnessFloor = min(categoryRoughnessFloor, 0.08f);
        }
    }
    roughness = max(roughness, categoryRoughnessFloor);
    metallic = min(metallic, categoryMetalCap);
    if (MaterialHasHeight > 0.5f)
    {
        float heightRelief = (heightValue - 0.5f)
            * saturate(MaterialHeightScale);
        roughness = saturate(roughness - heightRelief * 0.10f);
    }
    if (conservativeNonmetal)
    {
        roughness = max(roughness, categoryRoughnessFloor);
        metallic = min(metallic, categoryMetalCap);
    }
    // Reflectance is derived from the metal fraction, not from a specular map.
    // Real dielectrics sit near 0.04 F0 whatever a synthesized specular map
    // claims, and letting that map act as F0 is what gave leather, cloth and
    // hair a metallic sheen they should never have.  Only the metal fraction
    // takes its colour from the albedo.
    float dielectricSpecular = clamp(PresentationDiagnosticTuning.y, 0.02f, 0.08f);
    float3 sourceStableF0 = lerp(
        dielectricSpecular.xxx,
        materialReferenceAlbedo,
        metallic);
    float3 specularColor = sourceStableF0;
    if (MaterialHasSpecular > 0.5f)
    {
        // A source specular map shapes the metal highlight only; its influence
        // fades out with the metal fraction so a dielectric cannot inherit it.
        float3 mappedSpecular = SpecularTexture.Sample(MaterialSampler, uv).rgb
            * familySpecularScale;
        specularColor = lerp(
            specularColor,
            max(specularColor, mappedSpecular),
            saturate(metallic));
    }
    specularColor *= saturate(PresentationMaterialTuning.y);
    if (MaterialSurfaceOverrideFlags.z > 0.5f)
    {
        specularColor *= saturate(MaterialSurfaceOverrides.z);
    }
    if (hasMaterialSpecularHint && materialSpecularHint > 0.02f)
    {
        // A declared specular hint may brighten metal but must not lift a
        // dielectric above its physical reflectance.
        specularColor = max(
            specularColor,
            lerp(dielectricSpecular, materialSpecularHint, saturate(metallic)).xxx);
    }
    if (MaterialFamilyPolicy.w > 0.0f)
    {
        float neutralSpecular = dot(specularColor, float3(0.2126f, 0.7152f, 0.0722f));
        specularColor = min(neutralSpecular, MaterialFamilyPolicy.z).xxx;
    }
    if (!categoryMetal && !hasSourceMetallicMap)
    {
        // Fallback only: with no metal map the category guess is all we have.
        specularColor = min(specularColor, categorySpecularCap.xxx);
    }
    float3 resolvedSurfaceF0 = sourceStableF0;
    if (categoryMetal)
    {
        // Match the Archive reference's source-stable metal Fresnel: a
        // grayscale response map must not replace the source albedo that
        // colors the reflection.
        specularColor = resolvedSurfaceF0;
    }

    float ndotl = WrappedNdotL(normal, lightDirection, PresentationLightingTuning.y);
    float ndotv = max(saturate(dot(normal, viewDirection)), 1e-4f);
    float3 spec = float3(0.0f, 0.0f, 0.0f);
    if (categoryMetal)
    {
        float3 metalNormal = dot(normal, viewDirection) < 0.0f ? -normal : normal;
        float metalNdotL = saturate(dot(metalNormal, lightDirection));
        float metalNdotV = max(saturate(dot(metalNormal, viewDirection)), 1e-4f);
        float3 metalHalfVector = SafeNormalize(
            lightDirection + viewDirection,
            viewDirection);
        float metalHdotV = saturate(dot(metalHalfVector, viewDirection));
        float metalDistribution = DistributionGGX(metalNormal, metalHalfVector, roughness);
        float metalGeometry = GeometrySmith(
            metalNormal,
            viewDirection,
            lightDirection,
            roughness);
        float3 metalFresnel = SourceStableFresnel(metalHdotV, specularColor);
        float metalDenominator = max(4.0f * metalNdotV * metalNdotL, 1e-4f);
        float3 metalCookTorrance = metalDistribution
            * metalGeometry
            * metalFresnel
            / metalDenominator;
        // This scale reached 0.70 at most, under a 0.52 specular cap, so the
        // metal lobe ran at about a third of the strength Cook-Torrance
        // returns. Both numbers were fitted while a specular map stood in for
        // F0 at roughly ten times the physical value and had to be divided
        // back out -- the same fitting already lifted for dielectrics once a
        // real roughness map is bound. Where the source supplies a metal map,
        // F0 is its own albedo and the GGX term is already energy-normalised,
        // so dividing it down only removes the compact highlight that is what
        // makes metal read as metal rather than as grey plastic. The 0.85
        // ceiling still holds the hotspot below white.
        float metalDirectSpecularScale = hasSourceMetallicMap
            ? 1.0f
            : (0.35f + metallic * 0.35f) * saturate(PresentationMaterialTuning.y);
        spec = min(
            metalCookTorrance
                * metalNdotL
                * metalDirectSpecularScale,
            float3(0.85f, 0.85f, 0.85f));
    }
    else
    {
        float nonmetalSmoothness = saturate(1.0f - roughness);
        float nonmetalCameraShape = saturate(abs(dot(normal, viewDirection)));
        float nonmetalNdotH = saturate(dot(normal, halfVector));
        float nonmetalSpecularPower = lerp(
            28.0f,
            max(PresentationMaterialTuning.z, 28.0f),
            nonmetalSmoothness);
        float nonmetalDirectLobe = pow(nonmetalNdotH, nonmetalSpecularPower)
            * saturate(ndotl * 1.25f);
        // These scales were fitted while the specular map stood in for F0 at
        // roughly ten times the physical value, so they had to divide it back
        // out.  Against a real 0.04 dielectric F0 the Fresnel and GGX terms
        // already keep the lobe subtle, and keeping the old 0.025 multiplied it
        // away entirely -- which is why hair lost its strand highlights.  A
        // bound roughness map means the surface can be lit on its own terms;
        // rough cloth stays matte because its roughness says so, not because a
        // category table suppressed it.
        float nonmetalDirectSpecularScale = hasSourceRoughnessMap
            ? 0.32f
            : (glossyNonmetal ? 0.18f : (conservativeNonmetal ? 0.025f : 0.08f));
        // Hair is not a smooth surface: its highlight runs as a band across the
        // strands, not as a round blob on the surface normal. Crimson ships the
        // strand direction as a two-channel BC5 `_f` map in UV space, so where one
        // is bound the isotropic lobe above is replaced with a Kajiya-Kay pair of
        // shifted anisotropic highlights along that direction. Two lobes, because
        // hair has a sharp near-white primary reflection at the cuticle and a
        // broader coloured secondary scattered back through the strand; a single
        // lobe reads as wet plastic.
        if (MaterialHairAnisotropy.x > 0.5f)
        {
            float2 flow = FlowTexture.Sample(MaterialSampler, uv).xy * 2.0f - 1.0f;
            // A flat or unauthored region leaves the strand running along the
            // bitangent, which is how these sheets are laid out.
            float2 flowDirection = dot(flow, flow) > 0.0004f ? normalize(flow) : float2(0.0f, 1.0f);
            float3 strandTangent = SafeNormalize(
                normalize(input.Tangent) * flowDirection.x
                    + normalize(input.Bitangent) * flowDirection.y,
                normalize(input.Bitangent));
            float primaryExponent = lerp(24.0f, 96.0f, nonmetalSmoothness);
            float secondaryExponent = max(primaryExponent * 0.35f, 8.0f);
            float3 primaryTangent = SafeNormalize(
                strandTangent + normal * -MaterialHairAnisotropy.y,
                strandTangent);
            float3 secondaryTangent = SafeNormalize(
                strandTangent + normal * MaterialHairAnisotropy.y * 1.75f,
                strandTangent);
            float primaryBand = pow(
                sqrt(saturate(1.0f - dot(primaryTangent, halfVector) * dot(primaryTangent, halfVector))),
                primaryExponent);
            float secondaryBand = pow(
                sqrt(saturate(1.0f - dot(secondaryTangent, halfVector) * dot(secondaryTangent, halfVector))),
                secondaryExponent);
            float3 fresnel = SourceStableFresnel(nonmetalCameraShape, resolvedSurfaceF0);
            spec = saturate(ndotl * 1.25f)
                * saturate(PresentationMaterialTuning.y)
                * nonmetalDirectSpecularScale
                * (fresnel * primaryBand
                    // The secondary lobe carries the strand's own colour, which is
                    // what separates hair from a plastic sheen.
                    + materialReferenceAlbedo * secondaryBand * 0.55f);
        }
        else
        {
            spec = SourceStableFresnel(
                nonmetalCameraShape,
                resolvedSurfaceF0)
                * nonmetalDirectLobe
                * saturate(PresentationMaterialTuning.y)
                * nonmetalDirectSpecularScale;
        }
    }
    float3 emissive = float3(0.0f, 0.0f, 0.0f);
    // The divisor normalises a declared intensity whose scale runs above 1.0.
    // It was 12, left standing until a wider sample of declared
    // _emissiveIntensity values settled the scale. A 535-asset sweep of the
    // shipped archive found 27 emissive batches declaring only three values:
    // 1.0 (20 of them), 4.0 (4) and 0.14 (3). Nothing authored above 4.0, so /12
    // put the brightest emitter in the game at 0.33 and the common case at 0.083,
    // which reads as unlit. /4 normalises the brightest authored emitter to full
    // and leaves the common case visible.
    float emissiveIntensity = saturate(
        (MaterialEmissiveOverrideFlags.y > 0.5f
            ? MaterialEmissiveOverride.w
            : (MaterialHasEmissive > 0.5f ? 4.0f : 0.0f))
        / 4.0f);
    // Neutral when the material declares no emissive colour: the `_emi` map
    // carries the colour it emits. The fallback was a fixed cyan, which is the
    // one colour greek fire, a lightning thrower and an ancient giant's runes
    // could not all be.
    float3 emissiveColor = MaterialEmissiveOverrideFlags.x > 0.5f
        ? clamp(
            MaterialEmissiveOverride.rgb,
            float3(0.0f, 0.0f, 0.0f),
            float3(2.0f, 2.0f, 2.0f))
        : float3(1.0f, 1.0f, 1.0f);
    if (MaterialHasEmissive > 0.5f)
    {
        float4 emissiveSample = EmissiveTexture.Sample(MaterialSampler, uv);
        if (MaterialEmissiveOverrideFlags.z > 0.5f)
        {
            // Scalar emissive textures are masks and need either the explicit
            // source color or the preview fallback color.
            emissive = emissiveColor
                * saturate(emissiveSample.r)
                * emissiveIntensity;
        }
        else
        {
            if (MaterialEmissiveOverrideFlags.w > 0.5f)
            {
                // An authoritative source color is a multiplicative tint.
                emissive = saturate(emissiveSample.rgb)
                    * emissiveColor
                    * emissiveIntensity;
            }
            else
            {
                // When the source graph exposes no authoritative tint, retain
                // the Archive renderer's deliberate blue fallback heuristic.
                float emissiveMask = max(
                    emissiveSample.r,
                    max(emissiveSample.g, emissiveSample.b));
                emissive = max(emissiveColor, emissiveSample.rgb)
                    * saturate(emissiveMask)
                    * emissiveIntensity;
            }
        }
    }
    else if (MaterialEmissiveOverrideFlags.y > 0.5f)
    {
        emissive = emissiveColor * emissiveIntensity;
    }
    emissive *= max(PresentationSurfaceTuning.z, 0.0f) * 0.85f;
    if (MaterialDebugMode > 0.5f && MaterialDebugMode < 1.5f)
    {
        return baseColor;
    }
    if (MaterialDebugMode > 1.5f && MaterialDebugMode < 2.5f)
    {
        return float4(normal * 0.5f + 0.5f, 1.0f);
    }
    if (MaterialDebugMode > 2.5f && MaterialDebugMode < 3.5f)
    {
        return float4(roughness.xxx, 1.0f);
    }
    if (MaterialDebugMode > 3.5f && MaterialDebugMode < 4.5f)
    {
        return float4(metallic.xxx, 1.0f);
    }
    if (MaterialDebugMode > 4.5f && MaterialDebugMode < 5.5f)
    {
        return float4(saturate(emissive), 1.0f);
    }
    if (MaterialDebugMode > 7.5f && MaterialDebugMode < 8.5f)
    {
        float checker = fmod(floor(uv.x * 16.0f) + floor(uv.y * 16.0f), 2.0f);
        return float4(lerp(float3(0.08f, 0.08f, 0.08f), float3(0.88f, 0.88f, 0.88f), checker), 1.0f);
    }
    if (MaterialDebugMode > 8.5f && MaterialDebugMode < 9.5f)
    {
        return float4(baseColor.aaa, 1.0f);
    }
    if (MaterialDebugMode > 9.5f && MaterialDebugMode < 10.5f)
    {
        float partId = PresentationDiagnosticTuning.x + 1.0f;
        return float4(frac(partId * float3(0.6180339f, 0.3819660f, 0.7548777f)), 1.0f);
    }
    if (MaterialDebugMode > 10.5f && MaterialDebugMode < 11.5f)
    {
        return float4(saturate(metallic), saturate(roughness), saturate(max(spec.r, max(spec.g, spec.b))), 1.0f);
    }
    if (MaterialDebugMode > 11.5f && MaterialDebugMode < 12.5f)
    {
        float layerMask = PresentationDiagnosticTuning.z > 0.5f
            ? LayerMaskTexture.Sample(MaterialSampler, uv)[(int)MaterialChannelSelectors.z]
            : baseColor.a;
        return float4(layerMask.xxx, 1.0f);
    }
    float ambientOcclusionSample = MaterialAdditionalMaps.y > 0.5f
        ? OcclusionTexture.Sample(MaterialSampler, uv)[(int)MaterialAdditionalMaps.w]
        : 1.0f;
    float aoWeight = saturate(PresentationLightingTuning.x)
        * (categoryMetal ? 1.0f : (glossyNonmetal ? 0.82f
            : (categorySkin ? 0.58f : (conservativeNonmetal ? 0.62f : 0.78f))));
    float ambientOcclusion = lerp(1.0f, ambientOcclusionSample, aoWeight);
    float3 reflectedView = SafeNormalize(
        reflect(-viewDirection, normal),
        float3(0.0f, 0.0f, -1.0f));
    float3 environmentRadiance = PreviewEnvironmentRadiance(reflectedView, roughness);
    float smoothness = saturate(1.0f - roughness);
    float authorityGlossCue = (explicitMaterialAuthorityHint && !conservativeNonmetal)
        ? saturate(
            (hasMaterialRoughnessHint ? (1.0f - materialRoughnessHint) * 0.55f : 0.0f)
            + (hasMaterialSpecularHint ? materialSpecularHint * 0.75f : 0.0f)
            + (hasMaterialMetalnessHint ? materialMetalnessHint * 0.35f : 0.0f))
        : 0.0f;
    float environmentMaterialScale = categoryMetal
        ? 0.55f + metallic * lerp(0.45f, 1.10f, smoothness)
        : (hasSourceRoughnessMap
            ? lerp(0.06f, 0.30f, smoothness)
            : (glossyNonmetal ? 0.18f : (conservativeNonmetal ? 0.018f : 0.08f)));
    environmentMaterialScale = max(environmentMaterialScale, authorityGlossCue * 0.32f);
    float3 environmentFresnel = SourceStableFresnel(ndotv, resolvedSurfaceF0);
    float3 environmentSpecular = environmentRadiance
        * environmentFresnel
        * max(PresentationToneTuning.w, 0.0f)
        * categoryEnvironmentScale
        * environmentMaterialScale;
    // The diffuse term below is cut wherever the source supplies a metal map,
    // so the reflection that has to replace it must answer to the same
    // condition. Gating this compensation on the *category* instead left a part
    // that carries real metalness but classifies as something else -- a metal
    // boss on a leather shield, studs read as generic -- losing its diffuse with
    // nothing given back. Measured over 998 assets with a real surface map, 35%
    // of that group rendered below half the brightness their own albedo carries,
    // against 0% for metal that is also classified metal. The weight is the
    // metal fraction itself, so a mostly-cloth part only takes it where the map
    // actually says metal, and a classified metal surface is unchanged.
    float metalReflectionWeight = categoryMetal
        ? 1.0f
        : (hasSourceMetallicMap ? saturate(metallic) : 0.0f);
    if (metalReflectionWeight > 0.001f)
    {
        float metalCameraShape = saturate(abs(dot(normal, viewDirection)));
        // The energy the diffuse term no longer supplies has to arrive through
        // the reflection instead -- that is the whole point of the change.
        // This lobe is sampled about the reflection vector, so it sweeps as the
        // surface curves and gives metal the moving highlight that separates it
        // from a painted surface, where the diffuse it replaces did not vary at
        // all.
        float metalEnvironmentScale = hasSourceMetallicMap
            ? 0.85f + metallic * lerp(0.90f, 2.00f, smoothness)
            : 0.55f + metallic * lerp(0.45f, 1.10f, smoothness);
        float3 metalEnvironmentSpecular = environmentRadiance
            * SourceStableFresnel(metalCameraShape, sourceStableF0)
            * max(PresentationToneTuning.w, 0.0f)
            * categoryEnvironmentScale
            * metalEnvironmentScale;
        environmentSpecular = lerp(
            environmentSpecular,
            metalEnvironmentSpecular,
            metalReflectionWeight);
        // Metal has no diffuse lobe, so away from a highlight its tone comes
        // entirely from wide-angle reflection.  This environment concentrates
        // its energy in five narrow softboxes, so that wide component was
        // missing: the diffuse path was scaled to a third and floored at 0.24,
        // and nothing replaced it.  Sampling the same environment fully blurred
        // about the normal recovers the broad term the softboxes leave out,
        // tinted by F0 so steel stays steel and bronze stays bronze.
        float3 metalIrradiance = PreviewEnvironmentRadiance(normal, 1.0f)
            * sourceStableF0
            * max(PresentationToneTuning.w, 0.0f)
            * metallic
            * lerp(1.35f, 0.85f, smoothness)
            * ambientOcclusion;
        environmentSpecular += metalIrradiance;
    }
    if (MaterialDebugMode > 5.5f && MaterialDebugMode < 6.5f)
    {
        return float4(saturate(spec + environmentSpecular), 1.0f);
    }
    float3 keyDirection = SafeNormalize(LightDirection, float3(-0.18f, 0.35f, -0.92f));
    float3 fillDirection = SafeNormalize(
        float3(-keyDirection.x * 0.55f, 0.55f, -0.80f),
        float3(0.35f, 0.45f, -0.82f));
    float keyLight = WrappedNdotL(normal, keyDirection, PresentationLightingTuning.y);
    float fillLight = WrappedNdotL(normal, fillDirection, 0.82f);
    float cameraShape = saturate(abs(dot(normal, viewDirection)));
    float rimShape = pow(saturate(1.0f - cameraShape), lerp(2.4f, 1.2f, smoothness));
    // Lift the grazing-angle edge a little so a dark, rough surface still shows
    // a readable silhouette against the backdrop instead of dissolving into it.
    // Confined to the outer edge, so it shapes the outline without washing out
    // the interior the way a flat ambient raise would.
    rimShape = max(rimShape, pow(saturate(1.0f - cameraShape), 6.0f) * 0.35f);
    // Keep physically shaded metal source-readable in the neutral workbench.
    // The GGX and environment lobes remain authoritative for response, while
    // this floor prevents dark source albedo from collapsing between lobes.
    float ambientFloor = categoryMetal ? 0.24f : (categorySkin ? 0.56f : (conservativeNonmetal ? 0.50f : 0.47f));
    float diffuseDepth = saturate(
        ambientFloor * PresentationLightingTuning.w
        + PresentationLightingTuning.z * (keyLight * 0.58f + fillLight * 0.30f + rimShape * 0.12f));
    // How much of the directional shading survives. These were low enough that
    // a garment kept only a quarter of its light-to-shadow range, so a pale
    // cloth sat at 0.90-0.93 everywhere and lost its folds -- readable as
    // colour, shapeless as an object. The suppression existed because the old
    // contrast operator crushed anything dark, so shading had to be held back
    // to stop shadowed cloth going black. With contrast pivoting perceptually
    // that headroom exists, and the surface can be shaped by its own normal.
    float depthAuthority = categoryMetal
        ? 1.0f
        : (glossyNonmetal ? 0.80f
            : (categorySkin ? 0.50f
                : (categoryHair ? 0.52f
                    : (categoryCloth ? 0.68f
                        : (categoryLeather ? 0.70f : 0.68f)))));
    diffuseDepth = lerp(1.0f, diffuseDepth, depthAuthority);
    float nonmetalTextureScale = conservativeNonmetal ? 1.03f : 1.0f;
    // A conductor has no diffuse lobe at all; every photon that leaves it left
    // by reflection. Keeping a third of the diffuse term gave metal a large,
    // view-independent glow that does not vary with the surface, so polished
    // steel read as chalky white plaster -- bright everywhere, reflective
    // nowhere. Where the source supplies a metal map the reflection paths can
    // be trusted to carry the surface, so the residue drops to a floor that
    // only keeps a very dark alloy from collapsing between lobes.
    float metalDiffuseScale = lerp(
        1.0f,
        hasSourceMetallicMap ? 0.12f : 0.34f,
        saturate(metallic));
    float3 litDiffuse = materialReferenceAlbedo
        * ambientOcclusion
        * nonmetalTextureScale
        * diffuseDepth
        * metalDiffuseScale;
    float metalCue = categoryMetal
        ? saturate(metallic * lerp(0.18f, 0.58f, smoothness))
        : 0.0f;
    float resolvedSpecular = max(specularColor.r, max(specularColor.g, specularColor.b));
    float glossyCue = glossyNonmetal
        ? saturate(resolvedSpecular * lerp(0.06f, 0.20f, smoothness))
        : 0.0f;
    litDiffuse += materialReferenceAlbedo * metalCue * 0.16f;
    litDiffuse += materialReferenceAlbedo * glossyCue * 0.22f;
    litDiffuse += materialReferenceAlbedo
        * authorityGlossCue
        * (0.035f + rimShape * 0.16f);
    // The metal anchor added albedo back as fake ambient so dark metal stayed
    // visible while the real metal signal was stuck near zero.  With a bound
    // metal map the GGX and environment lobes carry that response, and keeping
    // the anchor would double-count it into a flat wash.  Retained only as a
    // floor for parts that still have no metal map at all.
    float3 metallicSourceAnchor = hasSourceMetallicMap
        ? float3(0.0f, 0.0f, 0.0f)
        : materialReferenceAlbedo
            * metallic
            * (0.14f + roughness * 0.06f + (1.0f - ndotv) * 0.30f)
            * ambientOcclusion;
    float3 finalColor = PresentationSurfaceTuning.w > 0.5f
        ? baseColor.rgb + emissive
        : litDiffuse + metallicSourceAnchor + spec + environmentSpecular + emissive;
    float3 exposedColor = max(
        finalColor * max(PresentationToneTuning.x, 0.05f),
        float3(0.0f, 0.0f, 0.0f));
    float exposedLuma = dot(exposedColor, float3(0.2126f, 0.7152f, 0.0722f));
    float mappedLuma = AcesToneMap(exposedLuma.xxx).r;
    finalColor = exposedColor * (mappedLuma / max(exposedLuma, 1e-5f));
    float currentLuma = dot(finalColor, float3(0.2126f, 0.7152f, 0.0722f));
    // Contrast is a perceptual control, so it pivots about mid-grey in display
    // space.  Pivoting about 0.5 in linear space subtracted a near-constant
    // 0.04 from every pixel instead: 97% of a workbench frame sits below that
    // pivot, so the operator crushed the whole image down and needed a 0.55
    // floor to stop the darkest third collapsing to black.  That floor was
    // doing the visible work -- a flat 45% cut on anything already dark, which
    // is why metal, shields and weapons read as dim and low-contrast.
    float displayLuma = LinearToSrgbScalar(currentLuma);
    float contrastedDisplay = saturate(
        (displayLuma - 0.5f) * max(PresentationToneTuning.y, 0.01f) + 0.5f);
    // Mid-tone lift, in the same display space as the contrast above and applied
    // to luminance only. Applied per-channel it raises a low channel
    // proportionally more than a high one and so desaturates -- measured against
    // the source textures, a 0.88 per-channel gamma took reproduction from 0.958
    // to 0.747 while it was fixing brightness. Scaling all three channels by one
    // luminance ratio leaves hue and saturation exactly where they were, and
    // because it acts in display space it leaves white at white, so it lifts the
    // body of the image without pushing anything new into clipping the way an
    // exposure would.
    contrastedDisplay = pow(contrastedDisplay, max(PresentationToneTuning.z, 0.01f));
    float contrastedLuma = SrgbToLinearScalar(contrastedDisplay);
    finalColor *= max(contrastedLuma, 0.0f) / max(currentLuma, 1e-5f);
    // The tone gamma is applied to luminance in the block above, not per-channel
    // here, so that it cannot desaturate.
    return float4(saturate(finalColor), baseColor.a);
}
