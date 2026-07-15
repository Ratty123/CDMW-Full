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
    float3 tangentNormal = NormalTexture.Sample(MaterialSampler, uv).xyz * 2.0f - 1.0f;
    tangentNormal.y = MaterialNormalYInverted > 0.5f ? -tangentNormal.y : tangentNormal.y;
    tangentNormal.xy *= saturate(PresentationMaterialTuning.w);
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

float PreviewEnvironmentIntensity(float3 reflectedView, float roughness)
{
    float environmentLobe = saturate((reflectedView.y * 0.55f) + (reflectedView.z * -0.14f) + 0.58f);
    float horizonBand = pow(saturate(1.0f - abs(reflectedView.y) * 1.12f), 2.2f);
    float frontSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(-0.18f, 0.36f, -0.92f)))),
        lerp(14.0f, 4.0f, roughness));
    float topSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(-0.32f, 0.88f, -0.34f)))),
        lerp(28.0f, 7.0f, roughness));
    float sideSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(0.82f, 0.20f, -0.54f)))),
        lerp(18.0f, 5.0f, roughness));
    float backSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(-0.72f, 0.26f, 0.64f)))),
        lerp(18.0f, 5.0f, roughness));
    float oppositeSoftbox = pow(
        saturate(dot(reflectedView, normalize(float3(0.58f, 0.30f, 0.76f)))),
        lerp(20.0f, 6.0f, roughness));
    float darkBand = pow(
        saturate(1.0f - abs(reflectedView.x * 1.8f + reflectedView.y * 0.35f)),
        3.2f) * saturate(0.85f - reflectedView.z);
    float intensity = lerp(0.48f, 0.52f, environmentLobe);
    intensity *= lerp(1.0f, 0.96f, darkBand * (1.0f - roughness));
    intensity += horizonBand * 0.025f;
    intensity += frontSoftbox * 0.04f;
    intensity += topSoftbox * 0.03f;
    intensity += sideSoftbox * 0.025f;
    intensity += backSoftbox * 0.02f;
    intensity += oppositeSoftbox * 0.018f;
    return clamp(intensity, 0.46f, 0.60f);
}

float3 SourceStableFresnel(float cosTheta, float3 reflectanceAtNormal, float metallic)
{
    float3 physicalFresnel = FresnelSchlick(cosTheta, reflectanceAtNormal);
    return lerp(physicalFresnel, reflectanceAtNormal, saturate(metallic * 0.88f));
}

float3 WorkbenchGeometryColor(VSOutput input)
{
    const float3 geometryColor = float3(0.55f, 0.62f, 0.72f);
    if (PresentationSurfaceTuning.w > 0.5f)
    {
        return geometryColor;
    }

    const float3 viewDirection = float3(0.0f, 0.0f, -1.0f);
    float3 normal = SafeNormalize(input.Normal, viewDirection);
    normal = dot(normal, viewDirection) < 0.0f ? -normal : normal;
    float3 keyDirection = SafeNormalize(LightDirection, float3(-0.18f, 0.35f, -0.92f));
    float3 fillDirection = SafeNormalize(
        float3(-keyDirection.x * 0.55f, 0.55f, -0.80f),
        float3(0.35f, 0.45f, -0.82f));
    float keyLight = WrappedNdotL(normal, keyDirection, max(PresentationLightingTuning.y, 0.58f));
    float fillLight = WrappedNdotL(normal, fillDirection, 0.82f);
    float cameraShape = saturate(dot(normal, viewDirection));
    float rimShape = pow(saturate(1.0f - cameraShape), 1.5f);
    const float minimumIllumination = 0.48f;
    float illumination = minimumIllumination
        + keyLight * 0.27f
        + fillLight * 0.13f
        + cameraShape * 0.08f
        + rimShape * 0.10f;
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
        bool earlyCategoryMetal = MaterialBaseTintPolicy.y > 0.5f
            && MaterialBaseTintPolicy.y < 1.5f;
        float neutralMetalTint = earlyCategoryMetal ? saturate((0.12f - tintChroma) * 8.0f) : 0.0f;
        float strength = saturate(MaterialBaseTintPolicy.x
            * (earlyCategoryMetal ? lerp(0.05f, 1.25f, neutralMetalTint) : 1.0f));
        float albedoLuma = dot(baseColor.rgb, float3(0.299f, 0.587f, 0.114f));
        float liftedLuma = saturate(albedoLuma * (1.05f + strength * 0.35f) + 0.10f * strength);
        float3 multiplied = saturate(baseColor.rgb * tintBias);
        float3 colorized = saturate(liftedLuma.xxx * tintBias);
        float neutralMetalLuma = saturate(albedoLuma * (0.55f + tintLuma * 0.45f) + 0.012f);
        colorized = lerp(colorized, saturate(neutralMetalLuma.xxx * tintBias), neutralMetalTint);
        float colorizeStrength = lerp(0.58f, 0.96f, neutralMetalTint);
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
        heightStrength = saturate((MaterialHeightScale + declaredHeight * 0.04f) * 8.0f);
        float3 heightNormal = normalize(
            normal
            - normalize(input.Tangent) * heightX * heightStrength * 2.4f
            + normalize(input.Bitangent) * heightY * heightStrength * 2.4f);
        normal = normalize(lerp(normal, heightNormal, heightStrength));
    }
    float3 lightDirection = normalize(LightDirection);
    float3 viewDirection = normalize(CameraPosition - input.WorldPosition);
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
        metallic = 0.0f;
    }
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
    if (MaterialSurfaceOverrideFlags.y < 0.5f)
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
    float categoryMetalCap = categoryMetal
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
    float categoryRoughnessFloor = categoryMetal
        ? 0.16f
        : (categoryGlass ? 0.30f
            : (categoryGem ? 0.26f
                : (categoryEye ? 0.30f
                    : (categoryLeather ? 0.76f
                        : (categoryWood ? 0.70f
                            : (categoryCloth ? 0.84f
                                : (categorySkin ? 0.58f
                                    : (categoryHair ? 0.64f
                                        : (categoryStone ? 0.82f
                                            : (categoryTooth ? 0.58f : 0.66f))))))))));
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
        roughness = lerp(roughness, materialRoughnessHint, 0.55f);
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
    if (categoryMetal)
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
            0.34f));
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
        metallic = max(metallic, categoryMetalFallback);
        roughness = min(roughness, lerp(0.34f, 0.16f, materialCategoryConfidence));
        categoryRoughnessFloor = min(categoryRoughnessFloor, 0.08f);
    }
    roughness = max(roughness, categoryRoughnessFloor);
    metallic = min(metallic, categoryMetalCap);
    if (MaterialHasHeight > 0.5f)
    {
        float heightRelief = (heightValue - 0.5f)
            * saturate(MaterialHeightScale * 10.0f);
        roughness = saturate(roughness - heightRelief * 0.10f);
    }
    if (conservativeNonmetal)
    {
        roughness = max(roughness, categoryRoughnessFloor);
        metallic = min(metallic, categoryMetalCap);
    }
    float dielectricSpecular = saturate(PresentationDiagnosticTuning.y);
    float3 specularColor = MaterialHasSpecular > 0.5f
        ? SpecularTexture.Sample(MaterialSampler, uv).rgb
        : lerp(dielectricSpecular.xxx, baseColor.rgb, metallic);
    specularColor *= saturate(PresentationMaterialTuning.y);
    if (MaterialHasSpecular > 0.5f)
    {
        specularColor *= familySpecularScale;
    }
    if (MaterialSurfaceOverrideFlags.z > 0.5f)
    {
        specularColor *= saturate(MaterialSurfaceOverrides.z);
    }
    if (hasMaterialSpecularHint && materialSpecularHint > 0.02f)
    {
        specularColor = max(specularColor, materialSpecularHint.xxx);
    }
    if (MaterialFamilyPolicy.w > 0.0f)
    {
        float neutralSpecular = dot(specularColor, float3(0.2126f, 0.7152f, 0.0722f));
        specularColor = min(neutralSpecular, MaterialFamilyPolicy.z).xxx;
    }
    if (!categoryMetal)
    {
        specularColor = min(specularColor, categorySpecularCap.xxx);
    }
    float3 sourceStableF0 = lerp(
        float3(0.035f, 0.035f, 0.035f),
        materialReferenceAlbedo,
        metallic);
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
        float metalSmoothness = saturate(1.0f - roughness);
        float metalCameraShape = saturate(abs(dot(normal, viewDirection)));
        float metalRimShape = pow(
            saturate(1.0f - metalCameraShape),
            lerp(2.4f, 1.2f, metalSmoothness));
        float metalNdotH = saturate(dot(normal, halfVector));
        float metalSpecularPower = lerp(
            28.0f,
            max(PresentationMaterialTuning.z, 28.0f),
            metalSmoothness);
        float metalDirectLobe = pow(metalNdotH, metalSpecularPower)
            * saturate(ndotl * 1.25f);
        float broadMetalLobe = pow(
            metalNdotH,
            lerp(7.0f, 22.0f, metalSmoothness))
            * saturate(ndotl * 0.85f + metalRimShape * 0.45f);
        float3 sourceStableMetalFresnel = SourceStableFresnel(
            metalCameraShape,
            specularColor,
            metallic);
        float metalDirectSpecularScale = 0.45f + metallic * 0.30f;
        spec = sourceStableMetalFresnel
            * (metalDirectLobe + broadMetalLobe * 1.05f)
            * saturate(PresentationMaterialTuning.y)
            * metalDirectSpecularScale;
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
        float nonmetalDirectSpecularScale = glossyNonmetal
            ? 0.18f
            : (conservativeNonmetal ? 0.025f : 0.08f);
        spec = SourceStableFresnel(
            nonmetalCameraShape,
            resolvedSurfaceF0,
            metallic)
            * nonmetalDirectLobe
            * saturate(PresentationMaterialTuning.y)
            * nonmetalDirectSpecularScale;
    }
    float3 emissive = float3(0.0f, 0.0f, 0.0f);
    float emissiveIntensity = saturate(
        (MaterialEmissiveOverrideFlags.y > 0.5f
            ? MaterialEmissiveOverride.w
            : (MaterialHasEmissive > 0.5f ? 4.0f : 0.0f))
        / 12.0f);
    float3 emissiveColor = MaterialEmissiveOverrideFlags.x > 0.5f
        ? clamp(
            MaterialEmissiveOverride.rgb,
            float3(0.0f, 0.0f, 0.0f),
            float3(2.0f, 2.0f, 2.0f))
        : float3(0.35f, 0.68f, 1.0f);
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
    float environmentIntensity = PreviewEnvironmentIntensity(reflectedView, roughness);
    float smoothness = saturate(1.0f - roughness);
    float authorityGlossCue = (explicitMaterialAuthorityHint && !conservativeNonmetal)
        ? saturate(
            (hasMaterialRoughnessHint ? (1.0f - materialRoughnessHint) * 0.55f : 0.0f)
            + (hasMaterialSpecularHint ? materialSpecularHint * 0.75f : 0.0f)
            + (hasMaterialMetalnessHint ? materialMetalnessHint * 0.35f : 0.0f))
        : 0.0f;
    float environmentMaterialScale = categoryMetal
        ? 0.55f + metallic * lerp(0.45f, 1.10f, smoothness)
        : (glossyNonmetal ? 0.18f : (conservativeNonmetal ? 0.018f : 0.08f));
    environmentMaterialScale = max(environmentMaterialScale, authorityGlossCue * 0.32f);
    float3 environmentFresnel = SourceStableFresnel(ndotv, resolvedSurfaceF0, metallic);
    float3 environmentSpecular = environmentIntensity
        * environmentFresnel
        * max(PresentationToneTuning.w, 0.0f)
        * categoryEnvironmentScale
        * environmentMaterialScale;
    if (categoryMetal)
    {
        float metalCameraShape = saturate(abs(dot(normal, viewDirection)));
        float metalEnvironmentScale = 0.55f
            + metallic * lerp(0.45f, 1.10f, smoothness);
        environmentSpecular = environmentIntensity
            * SourceStableFresnel(metalCameraShape, sourceStableF0, metallic)
            * max(PresentationToneTuning.w, 0.0f)
            * categoryEnvironmentScale
            * metalEnvironmentScale;
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
    float ambientFloor = categoryMetal ? 0.24f : (categorySkin ? 0.60f : (conservativeNonmetal ? 0.58f : 0.52f));
    float diffuseDepth = saturate(
        ambientFloor * PresentationLightingTuning.w
        + PresentationLightingTuning.z * (keyLight * 0.58f + fillLight * 0.30f + rimShape * 0.12f));
    float depthAuthority = categoryMetal
        ? 1.0f
        : (glossyNonmetal ? 0.72f
            : (categorySkin ? 0.40f
                : (categoryHair ? 0.38f
                    : (categoryCloth ? 0.46f
                        : (categoryLeather ? 0.52f : 0.50f)))));
    diffuseDepth = lerp(1.0f, diffuseDepth, depthAuthority);
    float nonmetalTextureScale = conservativeNonmetal ? 1.03f : 1.0f;
    float metalDiffuseScale = lerp(1.0f, 0.34f, saturate(metallic));
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
    float3 metallicSourceAnchor = materialReferenceAlbedo
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
    float contrastedLuma = (currentLuma - 0.5f)
        * max(PresentationToneTuning.y, 0.01f) + 0.5f;
    contrastedLuma = max(contrastedLuma, currentLuma * 0.55f);
    finalColor *= max(contrastedLuma, 0.0f) / max(currentLuma, 1e-5f);
    finalColor = pow(saturate(finalColor), max(PresentationToneTuning.z, 0.01f));
    return float4(saturate(finalColor), baseColor.a);
}
