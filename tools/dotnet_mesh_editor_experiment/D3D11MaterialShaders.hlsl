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
    float2 uv = input.TexCoord;
    if (MaterialHasHeight > 0.5f)
    {
        float height = HeightTexture.Sample(MaterialSampler, uv).r - 0.5f;
        float3 viewDirection = normalize(CameraPosition - input.WorldPosition);
        uv += viewDirection.xy * height * MaterialHeightScale;
    }

    float4 baseColor = MaterialHasBase > 0.5f ? BaseTexture.Sample(MaterialSampler, uv) : float4(0.55f, 0.62f, 0.72f, 1.0f);
    float3 normal = SampleNormal(input);
    float3 lightDirection = normalize(-LightDirection);
    float3 viewDirection = normalize(CameraPosition - input.WorldPosition);
    float3 halfVector = normalize(lightDirection + viewDirection);

    float roughness = MaterialHasRoughness > 0.5f ? RoughnessTexture.Sample(MaterialSampler, uv).r : MaterialRoughness;
    roughness = clamp(roughness, 0.04f, 1.0f);
    float metallic = MaterialHasMetallic > 0.5f ? MetallicTexture.Sample(MaterialSampler, uv).r : MaterialMetallic;
    metallic = saturate(metallic);
    float3 specularColor = MaterialHasSpecular > 0.5f ? SpecularTexture.Sample(MaterialSampler, uv).rgb : lerp(float3(0.04f, 0.04f, 0.04f), baseColor.rgb, metallic);

    float ndotl = saturate(dot(normal, lightDirection));
    float ndoth = saturate(dot(normal, halfVector));
    float specPower = lerp(160.0f, 8.0f, roughness);
    float specular = pow(ndoth, specPower) * (1.0f - roughness * 0.65f);
    float3 diffuse = baseColor.rgb * LightColor * ndotl;
    float3 spec = specularColor * specular;
    float3 emissive = MaterialHasEmissive > 0.5f ? EmissiveTexture.Sample(MaterialSampler, uv).rgb : float3(0.0f, 0.0f, 0.0f);
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
