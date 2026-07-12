cbuffer CameraConstants : register(b0)
{
    row_major float4x4 WorldViewProjection;
    row_major float4x4 World;
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
    float MaterialPadding;
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
};

Texture2D BaseTexture : register(t0);
Texture2D NormalTexture : register(t1);
Texture2D SpecularTexture : register(t2);
Texture2D RoughnessTexture : register(t3);
Texture2D MetallicTexture : register(t4);
Texture2D HeightTexture : register(t5);
Texture2D EmissiveTexture : register(t6);
SamplerState MaterialSampler : register(s0);

cbuffer OverlayConstants : register(b1)
{
    row_major float4x4 OverlayWorldViewProjection;
    float4 OverlayColor;
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

VSOutput VSMain(VSInput input)
{
    VSOutput output;
    float4 worldPosition = mul(float4(input.Position, 1.0f), World);
    output.Position = mul(float4(input.Position, 1.0f), WorldViewProjection);
    output.WorldPosition = worldPosition.xyz;
    output.Normal = normalize(mul(float4(input.Normal, 0.0f), World).xyz);
    output.Tangent = normalize(mul(float4(input.Tangent, 0.0f), World).xyz);
    output.Bitangent = normalize(mul(float4(input.Bitangent, 0.0f), World).xyz);
    output.TexCoord = input.TexCoord;
    return output;
}

float3 SampleNormal(VSOutput input)
{
    float3 baseNormal = normalize(input.Normal);
    if (MaterialHasNormal < 0.5f)
    {
        return baseNormal;
    }
    float3 tangentNormal = NormalTexture.Sample(MaterialSampler, input.TexCoord).xyz * 2.0f - 1.0f;
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
};

OverlayVSOutput VSOverlay(OverlayVSInput input)
{
    OverlayVSOutput output;
    output.Position = mul(float4(input.Position, 1.0f), OverlayWorldViewProjection);
    output.Color = OverlayColor;
    return output;
}

float4 PSOverlay(OverlayVSOutput input) : SV_Target
{
    return input.Color;
}

float4 PSMain(VSOutput input) : SV_Target
{
    if (MaterialDebugMode > 6.5f)
    {
        float3 geometryNormal = normalize(input.Normal);
        float geometryLight = saturate(dot(geometryNormal, normalize(-LightDirection)));
        float3 geometryColor = float3(0.55f, 0.62f, 0.72f);
        return float4(saturate(geometryColor * (AmbientColor + LightColor * geometryLight)), 1.0f);
    }
    float2 uv = input.TexCoord;
    if (MaterialHasHeight > 0.5f)
    {
        float height = HeightTexture.Sample(MaterialSampler, uv).r - 0.5f;
        float3 viewDirection = normalize(CameraPosition - input.WorldPosition);
        uv += viewDirection.xy * height * MaterialHeightScale;
    }

    float4 baseColor = MaterialHasBase > 0.5f
        ? BaseTexture.Sample(MaterialSampler, uv)
        : (MaterialTint.w > 0.5f ? float4(1.0f, 1.0f, 1.0f, 1.0f) : float4(0.55f, 0.62f, 0.72f, 1.0f));
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
    float3 normal = SampleNormal(input);
    float3 lightDirection = normalize(-LightDirection);
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
    roughness = clamp(roughness, 0.04f, 1.0f);
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
    metallic = saturate(metallic);
    float3 specularColor = MaterialHasSpecular > 0.5f ? SpecularTexture.Sample(MaterialSampler, uv).rgb : lerp(float3(0.04f, 0.04f, 0.04f), baseColor.rgb, metallic);
    if (MaterialSurfaceOverrideFlags.z > 0.5f)
    {
        specularColor *= saturate(MaterialSurfaceOverrides.z);
    }

    float ndotl = saturate(dot(normal, lightDirection));
    float ndoth = saturate(dot(normal, halfVector));
    float specPower = lerp(160.0f, 8.0f, roughness);
    float specular = pow(ndoth, specPower) * (1.0f - roughness * 0.65f);
    float3 diffuse = baseColor.rgb * LightColor * ndotl;
    float3 spec = specularColor * specular;
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
    if (MaterialDebugMode > 5.5f)
    {
        return float4(saturate(spec), 1.0f);
    }
    float3 finalColor = baseColor.rgb * AmbientColor + diffuse + spec + emissive;
    return float4(saturate(finalColor), baseColor.a);
}
