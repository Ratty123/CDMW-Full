using System.Numerics;

using Vortice.Direct3D11;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    public void ApplyPresentationSettings(D3D11PresentationSettings settings)
    {
        _presentationSettings = settings ?? new D3D11PresentationSettings();
        if (_device is not null)
        {
            _samplerState?.Dispose();
            var anisotropy = _presentationSettings.HighQuality
                ? Math.Clamp(_presentationSettings.MaxAnisotropy, 1, 16)
                : 1;
            var addressMode = string.Equals(_presentationSettings.TextureAddressMode, "clamp", StringComparison.OrdinalIgnoreCase)
                ? TextureAddressMode.Clamp
                : TextureAddressMode.Wrap;
            var description = new SamplerDescription(
                _presentationSettings.ForceNearestSampling
                    ? Filter.MinMagMipPoint
                    : anisotropy > 1 ? Filter.Anisotropic : Filter.MinMagMipLinear,
                addressMode,
                addressMode,
                addressMode)
            {
                MaxAnisotropy = (uint)anisotropy,
                MipLODBias = _presentationSettings.MipLodBias,
            };
            _samplerState = _device.CreateSamplerState(description);
            _rasterizerState?.Dispose();
            _doubleSidedRasterizerState?.Dispose();
            _rasterizerState = _device.CreateRasterizerState(new RasterizerDescription(
                _presentationSettings.CullBackFaces ? CullMode.Back : CullMode.None,
                FillMode.Solid));
            _doubleSidedRasterizerState = _device.CreateRasterizerState(new RasterizerDescription(
                CullMode.None,
                FillMode.Solid));
        }
        Invalidate();
    }

    private D3D11CameraConstants BuildCameraConstants(D3D11SubmeshBatch batch)
    {
        var materials = batch.Materials;
        var materialSubmeshIndex = batch.MaterialSubmeshIndex;
        var parameters = _materials.ParametersForSubmesh(materialSubmeshIndex);
        var settings = _presentationSettings;
        var tint = settings.DisableTint ? Vector3.One : parameters.TintColor ?? Vector3.One;
        var baseTint = parameters.BaseTintColor ?? Vector3.One;
        var baseTintStrength = settings.DisableTint ? 0.0f : parameters.BaseTintStrength ?? 0.0f;
        var azimuth = settings.LightAzimuthDegrees * MathF.PI / 180.0f;
        var elevation = settings.LightElevationDegrees * MathF.PI / 180.0f;
        var cosElevation = MathF.Cos(elevation);
        var lightDirection = Vector3.Normalize(new Vector3(
            MathF.Sin(azimuth) * cosElevation,
            MathF.Sin(elevation),
            -MathF.Cos(azimuth) * cosElevation));
        var supportMapsDisabled = !settings.HighQuality || settings.DisableAllSupportMaps;
        var materialMapsDisabled = supportMapsDisabled || settings.DisableMaterialMap;
        var directLightColor = settings.GameOutdoorApprox
            ? new Vector3(1.0f, 0.95f, 0.82f) * 1.12f
            : new Vector3(1.0f, 0.98f, 0.92f);
        var ambientLightColor = settings.GameOutdoorApprox
            ? new Vector3(0.30f, 0.36f, 0.46f)
            : new Vector3(0.22f, 0.24f, 0.28f);
        var world = ActivePaneModelMatrix(batch.SubmeshIndex) * _camera.World;
        var normalWorld = Matrix4x4.Invert(world, out var inverseWorld)
            ? Matrix4x4.Transpose(inverseWorld)
            : Matrix4x4.Identity;
        var cameraDistance = Math.Max(10.0f, _camera.SceneSize * 4.0f + 10.0f);
        var constants = new D3D11CameraConstants
        {
            WorldViewProjection = ActivePaneModelMatrix(batch.SubmeshIndex) * _camera.WorldViewProjection,
            World = world,
            NormalWorld = normalWorld,
            CameraPosition = new Vector3(0.0f, 0.0f, -cameraDistance),
            MaterialRoughness = 0.45f,
            LightDirection = lightDirection,
            MaterialMetallic = 0.0f,
            LightColor = settings.DisableLighting
                ? Vector3.Zero
                : directLightColor * settings.DiffuseLightScale,
            MaterialHeightScale = (parameters.HeightScale ?? 0.025f) * settings.HeightEffectMax,
            AmbientColor = settings.DisableLighting
                ? Vector3.One
                : ambientLightColor
                    * Math.Clamp(settings.EnvironmentStrength * settings.AmbientStrength, 0.0f, 2.0f),
            MaterialHasNormal = supportMapsDisabled || settings.DisableNormalMap || materials.Normal is null ? 0.0f : 1.0f,
            MaterialHasBase = materials.Base is null ? 0.0f : 1.0f,
            MaterialHasSpecular = materialMapsDisabled || materials.Specular is null ? 0.0f : 1.0f,
            MaterialHasRoughness = materialMapsDisabled || materials.Roughness is null ? 0.0f : 1.0f,
            MaterialHasMetallic = materialMapsDisabled || materials.Metallic is null ? 0.0f : 1.0f,
            MaterialHasHeight = supportMapsDisabled || settings.DisableHeightMap || materials.Height is null ? 0.0f : 1.0f,
            MaterialHasEmissive = supportMapsDisabled || materials.Emissive is null ? 0.0f : 1.0f,
            MaterialDebugMode = TexturesEnabled ? _materialDebugMode : 7.0f,
            MaterialNormalYInverted = settings.NormalYMode switch
            {
                "force_flip" => 1.0f,
                "force_no_flip" => 0.0f,
                _ => _materials.NormalYInvertedForSubmesh(materialSubmeshIndex) ? 1.0f : 0.0f,
            },
            MaterialBaseAdjustments = new Vector4(
                settings.DisableBrightness ? 1.0f : parameters.TextureBrightness ?? 1.0f,
                parameters.Contrast ?? 1.0f,
                parameters.Saturation ?? 1.0f,
                parameters.Gamma ?? 1.0f),
            MaterialBaseTint = new Vector4(baseTint, parameters.BaseTintColor.HasValue ? 1.0f : 0.0f),
            MaterialBaseTintPolicy = new Vector4(
                baseTintStrength,
                parameters.BaseTintMetallic == true ? 1.0f : 0.0f,
                0.0f,
                0.0f),
            MaterialTint = new Vector4(
                tint,
                !settings.DisableTint && parameters.TintColor.HasValue ? 1.0f : 0.0f),
            MaterialBaseAdvanced = new Vector4(
                (parameters.BaseColorLift ?? 0) / 255.0f,
                (parameters.ValueMax ?? 255) / 255.0f,
                (parameters.AutoBalance ?? 0) / 100.0f,
                (parameters.ShadowLift ?? 0) / 100.0f),
            MaterialBasePost = new Vector4(parameters.PostContrastBrightness ?? 1.0f, 0.0f, 0.0f, 0.0f),
        };
        ApplyMaterialSurfaceConstants(ref constants, parameters, materialSubmeshIndex);
        ApplyPresentationConstants(ref constants, settings, batch, materials, materialSubmeshIndex);
        return constants;
    }

    private void ApplyMaterialSurfaceConstants(
        ref D3D11CameraConstants constants,
        NetMaterialParameters parameters,
        int materialSubmeshIndex)
    {
        constants.MaterialSurfaceOverrides = new Vector4(
            parameters.Roughness ?? 0.0f,
            parameters.Metalness ?? 0.0f,
            parameters.Specular ?? 0.0f,
            parameters.HeightScale ?? 0.0f);
        constants.MaterialSurfaceOverrideFlags = new Vector4(
            parameters.Roughness.HasValue ? 1.0f : 0.0f,
            parameters.Metalness.HasValue ? 1.0f : 0.0f,
            parameters.Specular.HasValue ? 1.0f : 0.0f,
            parameters.HeightScale.HasValue ? 1.0f : 0.0f);
        constants.MaterialSurfaceTransforms = new Vector4(
            parameters.RoughnessScale ?? 1.0f,
            (parameters.RoughnessMin ?? 0) / 255.0f,
            (parameters.RoughnessMax ?? 255) / 255.0f,
            parameters.RoughnessInverted == true ? 1.0f : 0.0f);
        constants.MaterialSurfaceTransforms2 = new Vector4(
            parameters.MetalnessScale ?? 1.0f,
            (parameters.MetalnessMin ?? 0) / 255.0f,
            (parameters.MetalnessMax ?? 255) / 255.0f,
            parameters.MetalnessInverted == true ? 1.0f : 0.0f);
        constants.MaterialSurfaceBlends = new Vector4(
            parameters.RoughnessBlendTarget ?? 0.0f,
            parameters.RoughnessBlendStrength ?? 0.0f,
            parameters.MetalnessBlendTarget ?? 0.0f,
            parameters.MetalnessBlendStrength ?? 0.0f);
        constants.MaterialEmissiveOverride = new Vector4(
            parameters.EmissiveColor ?? Vector3.One,
            parameters.EmissiveIntensity ?? 1.0f);
        constants.MaterialEmissiveOverrideFlags = new Vector4(
            parameters.EmissiveColor.HasValue ? 1.0f : 0.0f,
            parameters.EmissiveIntensity.HasValue ? 1.0f : 0.0f,
            parameters.EmissiveScalarMask == true ? 1.0f : 0.0f,
            0.0f);
        constants.MaterialChannelSelectors = new Vector4(
            _materials.ChannelComponentIndexForSubmesh(materialSubmeshIndex, "roughness"),
            _materials.ChannelComponentIndexForSubmesh(materialSubmeshIndex, "metallic"),
            _materials.ChannelComponentIndexForSubmesh(materialSubmeshIndex, "layer_mask"),
            0.0f);
    }

    private void ApplyPresentationConstants(
        ref D3D11CameraConstants constants,
        D3D11PresentationSettings settings,
        D3D11SubmeshBatch batch,
        D3D11MaterialResources materials,
        int materialSubmeshIndex)
    {
        constants.PresentationUvScaleOffset = new Vector4(
            settings.DisableUvScale ? 1.0f : settings.UvScale.X,
            settings.DisableUvScale ? 1.0f : settings.UvScale.Y,
            settings.UvOffset.X,
            settings.UvOffset.Y);
        constants.PresentationUvRotationFlip = new Vector4(
            MathF.Cos(settings.UvRotationDegrees * MathF.PI / 180.0f),
            MathF.Sin(settings.UvRotationDegrees * MathF.PI / 180.0f),
            settings.FlipU ? -1.0f : 1.0f,
            settings.FlipV
                ^ settings.FlipTextureV
                ^ _materials.TextureFlipVerticalForSubmesh(materialSubmeshIndex)
                ? -1.0f
                : 1.0f);
        constants.PresentationSurfaceTuning = new Vector4(
            settings.RoughnessBias,
            settings.MetalnessScale,
            settings.EmissiveGain,
            settings.DisableLighting ? 1.0f : 0.0f);
        constants.PresentationToneTuning = new Vector4(
            settings.ToneExposure * (settings.GameOutdoorApprox ? 1.06f : 1.0f),
            settings.ToneContrast,
            settings.ToneGamma,
            settings.EnvironmentStrength);
        constants.PresentationLightingTuning = new Vector4(
            settings.AoStrength,
            settings.DiffuseWrapBias,
            settings.DiffuseLightScale,
            settings.AmbientStrength);
        constants.PresentationMaterialTuning = new Vector4(
            settings.HeightEffectMax,
            settings.SpecularMax,
            settings.ShininessMax,
            settings.NormalStrengthCap);
        constants.PresentationDiagnosticTuning = new Vector4(
            batch.SubmeshIndex,
            settings.SpecularBase,
            materials.LayerMask is null ? 0.0f : 1.0f,
            0.0f);
        constants.MaterialAlphaPolicy = BuildAlphaPolicy(materialSubmeshIndex);
        constants.MaterialAdditionalMaps = new Vector4(
            materials.Opacity is null ? 0.0f : 1.0f,
            materials.Occlusion is null ? 0.0f : 1.0f,
            _materials.ChannelComponentIndexForSubmesh(materialSubmeshIndex, "opacity"),
            _materials.ChannelComponentIndexForSubmesh(materialSubmeshIndex, "occlusion"));
        // Stable inspection fallback; not a claim of full Crimson shader parity.
        constants.MaterialFamilyPolicy = _materials.ShaderFamilyForSubmesh(materialSubmeshIndex) switch
        {
            "skin" => new Vector4(1.0f, 0.30f, 0.34f, 0.40f),
            "cloth" or "cloth_v2" => new Vector4(1.0f, 0.48f, 0.28f, 0.46f),
            "hair" => new Vector4(1.0f, 0.36f, 0.46f, 0.38f),
            _ => Vector4.Zero,
        };
    }

    private Vector4 BuildAlphaPolicy(int materialSubmeshIndex)
    {
        var alphaMode = _materials.AlphaModeForSubmesh(materialSubmeshIndex) switch
        {
            "cutout" => 1.0f,
            "blend" => 2.0f,
            _ => 0.0f,
        };
        return new Vector4(
            alphaMode,
            _materials.AlphaCutoffForSubmesh(materialSubmeshIndex),
            _materials.DoubleSidedForSubmesh(materialSubmeshIndex) ? 1.0f : 0.0f,
            _materials.OpacityFactorForSubmesh(materialSubmeshIndex));
    }

}
