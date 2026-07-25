using System.Numerics;
using System.Runtime.InteropServices;

namespace Cdmw.MeshEditorExperiment;

internal sealed record D3D11PresentationSettings
{
    public const string DefaultProfile = "mesh_editor_default_v1";

    public bool HighQuality { get; init; } = true;
    public string ViewMode { get; init; } = "lit";
    public bool GameOutdoorApprox { get; init; }
    public bool ForceNearestSampling { get; init; }
    public bool CullBackFaces { get; init; }
    public bool DisableLighting { get; init; }
    public bool DisableDepthTest { get; init; }
    public bool DisableTint { get; init; }
    public bool DisableBrightness { get; init; } = true;
    public bool DisableUvScale { get; init; } = true;
    public bool DisableNormalMap { get; init; }
    public bool DisableMaterialMap { get; init; }
    public bool DisableHeightMap { get; init; }
    public bool DisableAllSupportMaps { get; init; }
    public bool FlipTextureV { get; init; }
    public float LightAzimuthDegrees { get; init; } = -10.0f;
    public float LightElevationDegrees { get; init; }
    public float AoStrength { get; init; } = 0.45f;
    public float RoughnessBias { get; init; } = -0.04f;
    public float MetalnessScale { get; init; } = 1.45f;
    public float EnvironmentStrength { get; init; } = 0.62f;
    public float EmissiveGain { get; init; } = 2.2f;
    public float ToneExposure { get; init; } = 1.0f;
    public float ToneContrast { get; init; } = 1.08f;
    public float ToneGamma { get; init; } = 1.0f;
    public int MaxAnisotropy { get; init; } = 16;
    public float MipLodBias { get; init; } = -2.0f;
    public string TextureAddressMode { get; init; } = "wrap";
    public string NormalYMode { get; init; } = "asset";
    public float AmbientStrength { get; init; } = 0.84f;
    public float DiffuseWrapBias { get; init; } = 0.58f;
    public float DiffuseLightScale { get; init; } = 0.62f;
    // Neutral mid backdrop, supplied in linear space because the render target is
    // sRGB.  The old near-black clear (linear ~0.006) let dark leather and cloth
    // melt into the background so the silhouette was unreadable; a mid-grey is
    // also the standard backdrop for judging material response.
    // Exactly neutral at the same luminance: a tinted backdrop biases how every
    // material's colour reads, and the previous value measured a +0.06 cool cast.
    public Vector3 BackgroundColor { get; init; } = new Vector3(0.0434f, 0.0434f, 0.0434f);
    public float NormalStrengthCap { get; init; } = 1.0f;
    public float HeightEffectMax { get; init; } = 1.0f;
    public float SpecularBase { get; init; } = 0.055f;
    public float SpecularMax { get; init; } = 0.52f;
    public float ShininessMax { get; init; } = 152.0f;
    public float OrbitSensitivity { get; init; } = 0.22f;
    public float PanSensitivity { get; init; } = 0.60f;
    public bool InvertOrbitX { get; init; }
    public bool InvertOrbitY { get; init; }
    public bool InvertPanX { get; init; }
    public bool InvertPanY { get; init; }
    public Vector2 UvScale { get; init; } = Vector2.One;
    public Vector2 UvOffset { get; init; }
    public float UvRotationDegrees { get; init; }
    public bool FlipU { get; init; }
    public bool FlipV { get; init; }
}

[StructLayout(LayoutKind.Sequential)]
internal readonly record struct D3D11MaterialVertex(
    Vector3 Position,
    Vector3 Normal,
    Vector3 Tangent,
    Vector3 Bitangent,
    Vector2 TexCoord);

[StructLayout(LayoutKind.Sequential)]
internal struct D3D11CameraConstants
{
    public Matrix4x4 WorldViewProjection;
    public Matrix4x4 World;
    public Matrix4x4 NormalWorld;
    public Vector3 CameraPosition;
    public float MaterialRoughness;
    public Vector3 LightDirection;
    public float MaterialMetallic;
    public Vector3 LightColor;
    public float MaterialHeightScale;
    public Vector3 AmbientColor;
    public float MaterialHasNormal;
    public float MaterialHasBase;
    public float MaterialHasSpecular;
    public float MaterialHasRoughness;
    public float MaterialHasMetallic;
    public float MaterialHasHeight;
    public float MaterialHasEmissive;
    public float MaterialDebugMode;
    public float MaterialNormalYInverted;
    public Vector4 MaterialBaseAdjustments;
    public Vector4 MaterialBaseTint;
    public Vector4 MaterialBaseTintPolicy;
    public Vector4 MaterialTint;
    public Vector4 MaterialBaseAdvanced;
    public Vector4 MaterialBasePost;
    public Vector4 MaterialSurfaceOverrides;
    public Vector4 MaterialSurfaceOverrideFlags;
    public Vector4 MaterialSurfaceTransforms;
    public Vector4 MaterialSurfaceTransforms2;
    public Vector4 MaterialSurfaceBlends;
    public Vector4 MaterialEmissiveOverride;
    public Vector4 MaterialEmissiveOverrideFlags;
    public Vector4 MaterialChannelSelectors;
    public Vector4 PresentationUvScaleOffset;
    public Vector4 PresentationUvRotationFlip;
    public Vector4 PresentationSurfaceTuning;
    public Vector4 PresentationToneTuning;
    public Vector4 PresentationLightingTuning;
    public Vector4 PresentationMaterialTuning;
    public Vector4 PresentationDiagnosticTuning;
    public Vector4 MaterialAlphaPolicy;
    public Vector4 MaterialAdditionalMaps;
    public Vector4 MaterialFamilyPolicy;
}
