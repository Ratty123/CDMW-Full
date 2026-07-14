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
    if (MaterialHasHeight > 0.5f)
    {
        float height = HeightTexture.Sample(MaterialSampler, uv).r - 0.5f;
        float3 viewDirection = normalize(CameraPosition - input.WorldPosition);
        uv += viewDirection.xy * height * MaterialHeightScale;
    }

    float4 baseColor = MaterialHasBase > 0.5f
        ? BaseTexture.Sample(MaterialSampler, uv)
        : (MaterialTint.w > 0.5f ? float4(1.0f, 1.0f, 1.0f, 1.0f) : float4(0.55f, 0.62f, 0.72f, 1.0f));
    float materialAlpha = MaterialAdditionalMaps.x > 0.5f
        ? OpacityTexture.Sample(MaterialSampler, uv)[(int)MaterialAdditionalMaps.z]
        : baseColor.a;
    materialAlpha *= saturate(MaterialAlphaPolicy.w);
    baseColor.a = materialAlpha;
    if (MaterialAlphaPolicy.x > 0.5f && MaterialAlphaPolicy.x < 1.5f)
    {
        clip(baseColor.a - MaterialAlphaPolicy.y);
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
    float dielectricSpecular = saturate(PresentationDiagnosticTuning.y);
    float3 specularColor = MaterialHasSpecular > 0.5f
        ? SpecularTexture.Sample(MaterialSampler, uv).rgb
        : lerp(dielectricSpecular.xxx, baseColor.rgb, metallic);
    specularColor *= saturate(PresentationMaterialTuning.y);
    if (MaterialSurfaceOverrideFlags.z > 0.5f)
    {
        specularColor *= saturate(MaterialSurfaceOverrides.z);
    }
    if (MaterialFamilyPolicy.w > 0.0f)
    {
        float neutralSpecular = dot(specularColor, float3(0.2126f, 0.7152f, 0.0722f));
        specularColor = min(neutralSpecular, MaterialFamilyPolicy.z).xxx;
    }

    float ndotl = WrappedNdotL(normal, lightDirection, PresentationLightingTuning.y);
    float ndotv = max(saturate(dot(normal, viewDirection)), 1e-4f);
    float3 fresnel = SourceStableFresnel(
        saturate(dot(halfVector, viewDirection)),
        specularColor,
        metallic);
    float distribution = DistributionGGX(normal, halfVector, roughness);
    float geometry = GeometrySmith(normal, viewDirection, lightDirection, roughness);
    float3 specularBrdf = distribution * geometry * fresnel / max(4.0f * ndotv * max(ndotl, 1e-4f), 1e-4f);
    float3 diffuseWeight = (1.0f - fresnel) * (1.0f - metallic);
    float3 diffuseBrdf = diffuseWeight * baseColor.rgb / CdmwPi;
    float3 diffuse = diffuseBrdf * LightColor * ndotl;
    float metalInspectionSpecularScale = lerp(1.0f, 0.35f, metallic);
    float3 spec = specularBrdf * LightColor * ndotl * metalInspectionSpecularScale;
    float3 emissive = float3(0.0f, 0.0f, 0.0f);
    if (MaterialHasEmissive > 0.5f)
    {
        emissive = EmissiveTexture.Sample(MaterialSampler, uv).rgb;
        if (MaterialEmissiveOverrideFlags.x > 0.5f)
        {
            emissive *= MaterialEmissiveOverride.rgb;
        }
        emissive *= MaterialEmissiveOverrideFlags.y > 0.5f ? MaterialEmissiveOverride.w : 1.0f;
    }
    else if (MaterialEmissiveOverrideFlags.x > 0.5f && MaterialEmissiveOverrideFlags.y > 0.5f)
    {
        emissive = MaterialEmissiveOverride.rgb * MaterialEmissiveOverride.w;
    }
    emissive *= max(PresentationSurfaceTuning.z, 0.0f);
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
    float ambientOcclusion = lerp(1.0f, ambientOcclusionSample, saturate(PresentationLightingTuning.x));
    float3 reflectedView = SafeNormalize(
        reflect(-viewDirection, normal),
        float3(0.0f, 0.0f, -1.0f));
    float environmentIntensity = PreviewEnvironmentIntensity(reflectedView, roughness);
    float smoothness = saturate(1.0f - roughness);
    float environmentMaterialScale = lerp(
        0.08f,
        0.55f + metallic * lerp(0.45f, 1.10f, smoothness),
        metallic);
    float3 environmentFresnel = SourceStableFresnel(ndotv, specularColor, metallic);
    float3 environmentSpecular = environmentIntensity
        * environmentFresnel
        * max(PresentationToneTuning.w, 0.0f)
        * environmentMaterialScale
        * ambientOcclusion;
    if (MaterialDebugMode > 5.5f && MaterialDebugMode < 6.5f)
    {
        return float4(saturate(spec + environmentSpecular), 1.0f);
    }
    float3 ambient = baseColor.rgb * AmbientColor * (1.0f - metallic) * ambientOcclusion;
    float3 metallicSourceAnchor = baseColor.rgb
        * metallic
        * (0.14f + roughness * 0.06f + (1.0f - ndotv) * 0.30f)
        * ambientOcclusion;
    float3 litDiffuse = ambient + diffuse;
    if (MaterialFamilyPolicy.w > 0.0f)
    {
        // The native reference shader keeps classified nonmetal hue stable and
        // lets lighting describe depth. Collapse colored studio light to a
        // scalar, then blend its depth with the source albedo using the same
        // skin/cloth/hair authority values supplied by the host.
        float sourceLuma = max(dot(baseColor.rgb, float3(0.2126f, 0.7152f, 0.0722f)), 1e-4f);
        float familyLitDepth = saturate(dot(litDiffuse, float3(0.2126f, 0.7152f, 0.0722f)) / sourceLuma);
        float stableDepth = lerp(1.0f, familyLitDepth, saturate(MaterialFamilyPolicy.w));
        litDiffuse = baseColor.rgb * ambientOcclusion * stableDepth;
    }
    float3 finalColor = PresentationSurfaceTuning.w > 0.5f
        ? baseColor.rgb + emissive
        : litDiffuse + metallicSourceAnchor + spec + environmentSpecular + emissive;
    finalColor *= max(PresentationToneTuning.x, 0.05f);
    const float linearMiddleGray = 0.18f;
    float finalLuma = dot(finalColor, float3(0.2126f, 0.7152f, 0.0722f));
    float contrastedLuma = (finalLuma - linearMiddleGray)
        * max(PresentationToneTuning.y, 0.01f) + linearMiddleGray;
    contrastedLuma = max(contrastedLuma, finalLuma * 0.55f);
    finalColor *= max(contrastedLuma, 0.0f) / max(finalLuma, 1e-5f);
    finalColor = pow(saturate(finalColor), max(PresentationToneTuning.z, 0.01f));
    return float4(saturate(finalColor), baseColor.a);
}
