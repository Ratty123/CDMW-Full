using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Exports the exact managed material-layer composites used by the D3D11 viewport.
/// The caller owns the output directory; the leased preview package remains read-only.
/// </summary>
internal static class MaterialLayerCompositeExport
{
    private const string ExportFlag = "--export-material-layer-composites";
    private const string OutputFlag = "--output";
    private const string StatusFlag = "--status";
    private const long MaximumManifestBytes = 8L * 1024 * 1024;
    private const long MaximumResourceBytes = 256L * 1024 * 1024;
    private const long MaximumTotalResourceBytes = 2L * 1024 * 1024 * 1024;
    private const long MaximumTotalOutputBytes = 512L * 1024 * 1024;
    private const int MaximumResources = 4096;
    private const int MaximumSubmeshes = 2048;
    private const int MaximumLayersPerSubmesh = 256;
    private const string SurfaceTransformContract = "cdmw_vortice_material_surface_transform_v1";
    private const int SurfaceTransformVersion = 1;
    private static readonly UTF8Encoding Utf8NoBom = new(false);

    public static bool IsRequested(string[] args) =>
        Array.Exists(args, argument => string.Equals(argument, ExportFlag, StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var packageValue = ValueFor(args, ExportFlag);
        var outputValue = ValueFor(args, OutputFlag);
        var statusValue = ValueFor(args, StatusFlag);
        if (string.IsNullOrWhiteSpace(packageValue)
            || string.IsNullOrWhiteSpace(outputValue)
            || string.IsNullOrWhiteSpace(statusValue))
        {
            Console.Error.WriteLine(
                $"usage: {ExportFlag} <package-dir> {OutputFlag} <owned-output-dir> {StatusFlag} <manifest-path>");
            return 2;
        }

        var packageDirectory = NormalizeDirectory(packageValue, "Material package");
        var materialsPath = Path.GetFullPath(Path.Combine(packageDirectory, "net_materials.json"));
        var outputDirectory = Path.GetFullPath(outputValue);
        var statusPath = Path.GetFullPath(statusValue);
        var leaseRoot = ResolveLeaseRoot(packageDirectory);

        EnsureContained(materialsPath, packageDirectory, "Material manifest");
        EnsureContained(statusPath, outputDirectory, "Status manifest");
        EnsureSeparateTrees(outputDirectory, leaseRoot);
        EnsureNoReparsePoints(packageDirectory);
        EnsureNoReparsePoints(materialsPath);
        EnsureNoReparsePointsOnExistingAncestors(outputDirectory);
        EnsureNoReparsePointsOnExistingAncestors(statusPath);

        var manifestInfo = new FileInfo(materialsPath);
        if (!manifestInfo.Exists)
        {
            throw new FileNotFoundException("The leased package has no net_materials.json.", materialsPath);
        }
        if (manifestInfo.Length <= 0 || manifestInfo.Length > MaximumManifestBytes)
        {
            throw new InvalidDataException(
                $"net_materials.json must be between 1 and {MaximumManifestBytes} bytes.");
        }

        if (File.Exists(outputDirectory))
        {
            throw new InvalidDataException("The material-layer output path is a file.");
        }
        if (Directory.Exists(outputDirectory)
            && Directory.EnumerateFileSystemEntries(outputDirectory).Any())
        {
            throw new InvalidDataException("The owned material-layer output directory must be empty.");
        }
        Directory.CreateDirectory(outputDirectory);
        EnsureNoReparsePoints(outputDirectory);

        using var sourceDocument = ReadAndValidateManifest(materialsPath, packageDirectory, leaseRoot);
        var sourceHash = HashFile(materialsPath);
        var createdFiles = new List<string>();
        try
        {
            var materials = NetMaterialSet.Load(materialsPath);
            if (materials.Submeshes.Count > MaximumSubmeshes)
            {
                throw new InvalidDataException($"Material submesh count exceeds {MaximumSubmeshes}.");
            }

            using var textures = NetTextureSet.Load(materials);
            textures.LoadAsync(materials).GetAwaiter().GetResult();
            var rows = new List<Dictionary<string, object?>>();
            long totalOutputBytes = 0;
            foreach (var binding in materials.Submeshes.OrderBy(item => item.SubmeshIndex))
            {
                var row = new Dictionary<string, object?>
                {
                    ["submesh_index"] = binding.SubmeshIndex,
                    ["material_name"] = binding.Material,
                    ["normal_y_policy"] = materials.NormalYInvertedForSubmesh(binding.SubmeshIndex)
                        ? "invert_green_for_directx"
                        : "preserve",
                };
                var baseReference = textures.SynthesizedBaseReferenceForSubmesh(
                    materials,
                    binding.SubmeshIndex);
                var baseEntry = ExportReference(
                    textures,
                    baseReference,
                    binding.SubmeshIndex,
                    "base",
                    outputDirectory,
                    createdFiles,
                    ref totalOutputBytes);
                if (baseEntry is not null)
                {
                    row["base"] = baseEntry;
                }

                var surfaceReference = textures.SynthesizedSurfaceReferenceForSubmesh(
                    materials,
                    binding.SubmeshIndex);
                var surfaceEntry = ExportReference(
                    textures,
                    surfaceReference,
                    binding.SubmeshIndex,
                    "surface",
                    outputDirectory,
                    createdFiles,
                    ref totalOutputBytes,
                    SurfaceTransform.ForSynthesizedLayerSurface(
                        materials.ParametersForSubmesh(binding.SubmeshIndex)));
                if (surfaceEntry is not null)
                {
                    row["surface"] = surfaceEntry;
                }
                rows.Add(row);
            }

            var payload = new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_net_material_layer_export_v1",
                ["source_materials_sha256"] = sourceHash,
                ["direct_channels_preserved"] = new[] { "normal", "height" },
                ["surface_transform_contract"] = SurfaceTransformContract,
                ["surface_transform_version"] = SurfaceTransformVersion,
                ["rows"] = rows,
            };
            var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true })
                + Environment.NewLine;
            var statusBytes = Utf8NoBom.GetByteCount(json);
            if (checked(totalOutputBytes + statusBytes) > MaximumTotalOutputBytes)
            {
                throw new InvalidDataException("Material-layer export exceeds the bounded output size.");
            }
            Directory.CreateDirectory(
                Path.GetDirectoryName(statusPath)
                ?? throw new InvalidDataException("Status manifest has no owned parent directory."));
            EnsureNoReparsePointsOnExistingAncestors(statusPath);
            WriteAtomicText(statusPath, json);
            createdFiles.Add(statusPath);

            Console.WriteLine(JsonSerializer.Serialize(new
            {
                schema = "cdmw_net_material_layer_export_v1",
                status = statusPath,
                row_count = rows.Count,
                source_materials_sha256 = sourceHash,
            }));
            return 0;
        }
        catch
        {
            foreach (var path in createdFiles.AsEnumerable().Reverse())
            {
                try
                {
                    File.Delete(path);
                }
                catch
                {
                    // Only files created by this invocation are cleanup candidates.
                }
            }
            throw;
        }
    }

    private static Dictionary<string, object?>? ExportReference(
        NetTextureSet textures,
        NetMaterialTextureReference reference,
        int submeshIndex,
        string role,
        string outputDirectory,
        List<string> createdFiles,
        ref long totalOutputBytes,
        SurfaceTransform? surfaceTransform = null)
    {
        if (reference.IsEmpty)
        {
            return null;
        }
        var bitmap = textures.BitmapForReference(reference);
        if (bitmap is null)
        {
            throw new InvalidDataException(
                $"The {role} material-layer composite for submesh {submeshIndex} was declared but not decoded.");
        }

        var relativePath = Path.Combine("composites", $"submesh_{submeshIndex:D4}_{role}.png");
        var outputPath = Path.GetFullPath(Path.Combine(outputDirectory, relativePath));
        EnsureContained(outputPath, outputDirectory, "Composite output");
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        EnsureNoReparsePointsOnExistingAncestors(outputPath);
        if (File.Exists(outputPath))
        {
            throw new InvalidDataException($"Composite output already exists: {relativePath}");
        }

        var stagingPath = outputPath + $".tmp-{Guid.NewGuid():N}";
        try
        {
            if (surfaceTransform is null)
            {
                bitmap.Save(stagingPath, ImageFormat.Png);
            }
            else
            {
                using var transformed = BakeSurfaceTransforms(bitmap, surfaceTransform);
                transformed.Save(stagingPath, ImageFormat.Png);
            }
            var info = new FileInfo(stagingPath);
            if (!info.Exists || info.Length <= 0)
            {
                throw new InvalidDataException($"The {role} composite produced no bytes.");
            }
            totalOutputBytes = checked(totalOutputBytes + info.Length);
            if (totalOutputBytes > MaximumTotalOutputBytes)
            {
                throw new InvalidDataException("Material-layer export exceeds the bounded output size.");
            }
            var sha256 = HashFile(stagingPath);
            File.Move(stagingPath, outputPath);
            createdFiles.Add(outputPath);
            var entry = new Dictionary<string, object?>
            {
                ["relative_path"] = relativePath.Replace(Path.DirectorySeparatorChar, '/'),
                ["byte_length"] = info.Length,
                ["sha256"] = sha256,
                ["semantic"] = string.Equals(role, "surface", StringComparison.Ordinal)
                    ? "packed_surface"
                    : reference.Semantic,
                ["color_space"] = string.Equals(role, "surface", StringComparison.Ordinal)
                    ? "linear"
                    : reference.ColorSpace,
            };
            if (string.Equals(role, "surface", StringComparison.Ordinal))
            {
                entry["packed_channels"] = new Dictionary<string, string>
                {
                    ["g"] = "roughness",
                    ["b"] = "metalness",
                };
                entry["transforms_baked"] = true;
                entry["surface_transform_contract"] = SurfaceTransformContract;
                entry["surface_transform_version"] = SurfaceTransformVersion;
                entry["surface_transform_scope"] = "material_parameters_pre_presentation";
                entry["baked_transform"] = surfaceTransform?.Metadata()
                    ?? throw new InvalidDataException("Surface export requires a material transform contract.");
            }
            return entry;
        }
        finally
        {
            try
            {
                File.Delete(stagingPath);
            }
            catch
            {
                // The unique staging file is best-effort cleanup on failure.
            }
        }
    }

    private static Bitmap BakeSurfaceTransforms(Bitmap source, SurfaceTransform transform)
    {
        var rectangle = new Rectangle(0, 0, source.Width, source.Height);
        var result = source.Clone(rectangle, PixelFormat.Format32bppArgb);
        try
        {
            var data = result.LockBits(rectangle, ImageLockMode.ReadWrite, PixelFormat.Format32bppArgb);
            try
            {
                var rowBytes = checked(result.Width * 4);
                var row = new byte[rowBytes];
                var roughnessOffset = BgraOffset(transform.Roughness.SourceChannel);
                var metalnessOffset = BgraOffset(transform.Metalness.SourceChannel);
                for (var y = 0; y < result.Height; y++)
                {
                    var rowPointer = IntPtr.Add(data.Scan0, y * data.Stride);
                    Marshal.Copy(rowPointer, row, 0, rowBytes);
                    for (var offset = 0; offset < row.Length; offset += 4)
                    {
                        // Read both selected source components before writing the
                        // normalized packed contract. The source selectors may be
                        // the same component, as they are in some legacy manifests.
                        var sourceRoughness = row[offset + roughnessOffset] / 255.0f;
                        var sourceMetalness = row[offset + metalnessOffset] / 255.0f;
                        row[offset + 1] = ToUnorm8(transform.Roughness.Apply(sourceRoughness));
                        row[offset] = ToUnorm8(transform.Metalness.Apply(sourceMetalness));
                    }
                    Marshal.Copy(row, 0, rowPointer, rowBytes);
                }
            }
            finally
            {
                result.UnlockBits(data);
            }
            return result;
        }
        catch
        {
            result.Dispose();
            throw;
        }
    }

    internal static Dictionary<string, object?> PackedSurfaceSelectorProof()
    {
        using var source = new Bitmap(1, 1, PixelFormat.Format32bppArgb);
        source.SetPixel(0, 0, Color.FromArgb(255, 17, 101, 203));
        var transform = SurfaceTransform.ForSynthesizedLayerSurface(NetMaterialParameters.Empty);
        using var baked = BakeSurfaceTransforms(source, transform);
        var pixel = baked.GetPixel(0, 0);
        var metadata = transform.Metadata();
        var roughness = (Dictionary<string, object?>)metadata["roughness"]!;
        var metalness = (Dictionary<string, object?>)metadata["metalness"]!;
        var gates = new Dictionary<string, bool>
        {
            ["roughness_reads_green"] = pixel.G == 101
                && string.Equals(roughness["source_channel"] as string, "g", StringComparison.Ordinal),
            ["metalness_reads_blue"] = pixel.B == 203
                && string.Equals(metalness["source_channel"] as string, "b", StringComparison.Ordinal),
            ["red_primary_component_is_not_reused"] = pixel.G != 17 && pixel.B != 17,
            ["no_scalar_override_is_present"] = roughness["override"] is null
                && metalness["override"] is null,
        };
        return new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_material_layer_surface_selector_v1",
            ["source_rgba"] = new[] { 17, 101, 203, 255 },
            ["output_rgba"] = new[]
            {
                (int)pixel.R,
                (int)pixel.G,
                (int)pixel.B,
                (int)pixel.A,
            },
            ["transform"] = metadata,
            ["gates"] = gates,
            ["ok"] = gates.Values.All(value => value),
        };
    }

    internal static Dictionary<string, object?> ResolvedFallbackOwnershipProof(string root)
    {
        var packageDirectory = Path.Combine(root, "resolved-fallback-package");
        var textureDirectory = Path.Combine(packageDirectory, "textures");
        Directory.CreateDirectory(textureDirectory);
        var packagedTexture = Path.Combine(textureDirectory, "surface.png");
        var externalTexture = Path.Combine(root, "decoded-cache-surface.png");
        File.WriteAllBytes(packagedTexture, new byte[] { 1, 2, 3, 4 });
        File.WriteAllBytes(externalTexture, new byte[] { 5, 6, 7, 8 });
        var manifestPath = Path.Combine(packageDirectory, "net_materials.json");
        const string resourceId = "texture:owned-surface";

        Dictionary<string, object?> Manifest(bool withOwnedAlternative) => new()
        {
            ["resources"] = withOwnedAlternative
                ? new object[]
                {
                    new Dictionary<string, object?>
                    {
                        ["resource_id"] = resourceId,
                        ["path"] = "textures/surface.png",
                    },
                }
                : Array.Empty<object>(),
            ["submeshes"] = new object[]
            {
                new Dictionary<string, object?>
                {
                    ["submesh_index"] = 0,
                    ["resource_channels"] = withOwnedAlternative
                        ? new Dictionary<string, string> { ["material"] = resourceId }
                        : new Dictionary<string, string>(),
                    ["packaged_channels"] = withOwnedAlternative
                        ? new Dictionary<string, string> { ["material"] = "textures/surface.png" }
                        : new Dictionary<string, string>(),
                    ["resolved_channels"] = new Dictionary<string, string>
                    {
                        ["material"] = externalTexture,
                    },
                },
            },
        };

        File.WriteAllText(manifestPath, JsonSerializer.Serialize(Manifest(withOwnedAlternative: true)));
        using var accepted = ReadAndValidateManifest(
            manifestPath,
            packageDirectory,
            packageDirectory);
        var ownedAlternativeAccepted = accepted.RootElement.ValueKind == JsonValueKind.Object;

        File.WriteAllText(manifestPath, JsonSerializer.Serialize(Manifest(withOwnedAlternative: false)));
        var externalFallbackRejected = false;
        try
        {
            using var rejected = ReadAndValidateManifest(
                manifestPath,
                packageDirectory,
                packageDirectory);
        }
        catch (InvalidDataException)
        {
            externalFallbackRejected = true;
        }
        return new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_material_layer_resolved_fallback_ownership_v1",
            ["owned_alternative_accepted"] = ownedAlternativeAccepted,
            ["external_fallback_rejected_without_owned_alternative"] = externalFallbackRejected,
            ["ok"] = ownedAlternativeAccepted && externalFallbackRejected,
        };
    }

    private static int BgraOffset(int rgbaComponent) => rgbaComponent switch
    {
        0 => 2,
        1 => 1,
        2 => 0,
        3 => 3,
        _ => throw new InvalidDataException("Material surface selector is outside RGBA."),
    };

    private static byte ToUnorm8(float value) => (byte)Math.Clamp(
        (int)Math.Round(Math.Clamp(value, 0.0f, 1.0f) * 255.0f),
        0,
        255);

    private static JsonDocument ReadAndValidateManifest(
        string materialsPath,
        string packageDirectory,
        string leaseRoot)
    {
        using var stream = new FileStream(
            materialsPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 64 * 1024,
            FileOptions.SequentialScan);
        var document = JsonDocument.Parse(stream, new JsonDocumentOptions
        {
            AllowTrailingCommas = false,
            CommentHandling = JsonCommentHandling.Disallow,
            MaxDepth = 64,
        });
        try
        {
            var root = document.RootElement;
            var uniqueResources = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var validatedResourceIds = new HashSet<string>(StringComparer.Ordinal);
            long totalResourceBytes = 0;
            if (root.TryGetProperty("resources", out var resources))
            {
                if (resources.ValueKind != JsonValueKind.Array || resources.GetArrayLength() > MaximumResources)
                {
                    throw new InvalidDataException($"Material resource count exceeds {MaximumResources}.");
                }
                foreach (var resource in resources.EnumerateArray())
                {
                    ValidateDeclaredPath(resource, "path", packageDirectory, leaseRoot, uniqueResources, ref totalResourceBytes);
                    if (resource.TryGetProperty("resource_id", out var resourceIdValue)
                        && resourceIdValue.ValueKind == JsonValueKind.String
                        && !string.IsNullOrWhiteSpace(resourceIdValue.GetString()))
                    {
                        validatedResourceIds.Add(resourceIdValue.GetString()!);
                    }
                }
            }

            if (root.TryGetProperty("submeshes", out var submeshes))
            {
                if (submeshes.ValueKind != JsonValueKind.Array || submeshes.GetArrayLength() > MaximumSubmeshes)
                {
                    throw new InvalidDataException($"Material submesh count exceeds {MaximumSubmeshes}.");
                }
                foreach (var submesh in submeshes.EnumerateArray())
                {
                    var packagedChannels = ValidatePathMap(
                        submesh,
                        "packaged_channels",
                        packageDirectory,
                        leaseRoot,
                        uniqueResources,
                        ref totalResourceBytes);
                    ValidateResolvedFallbackPaths(
                        submesh,
                        packagedChannels,
                        validatedResourceIds,
                        packageDirectory,
                        leaseRoot,
                        uniqueResources,
                        ref totalResourceBytes);
                    if (submesh.TryGetProperty("material_layers", out var layers)
                        && (layers.ValueKind != JsonValueKind.Array || layers.GetArrayLength() > MaximumLayersPerSubmesh))
                    {
                        throw new InvalidDataException(
                            $"Material layer count exceeds {MaximumLayersPerSubmesh} for one submesh.");
                    }
                }
            }
            return document;
        }
        catch
        {
            document.Dispose();
            throw;
        }
    }

    private static HashSet<string> ValidatePathMap(
        JsonElement owner,
        string propertyName,
        string packageDirectory,
        string leaseRoot,
        HashSet<string> uniqueResources,
        ref long totalResourceBytes)
    {
        if (!owner.TryGetProperty(propertyName, out var map) || map.ValueKind != JsonValueKind.Object)
        {
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        }
        var validated = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var property in map.EnumerateObject())
        {
            ValidateDeclaredPath(property.Value, packageDirectory, leaseRoot, uniqueResources, ref totalResourceBytes);
            if (property.Value.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(property.Value.GetString()))
            {
                validated.Add(property.Name);
            }
        }
        return validated;
    }

    private static void ValidateResolvedFallbackPaths(
        JsonElement submesh,
        HashSet<string> packagedChannels,
        HashSet<string> validatedResourceIds,
        string packageDirectory,
        string leaseRoot,
        HashSet<string> uniqueResources,
        ref long totalResourceBytes)
    {
        if (!submesh.TryGetProperty("resolved_channels", out var resolvedChannels)
            || resolvedChannels.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        var resourceChannels = submesh.TryGetProperty("resource_channels", out var resources)
            && resources.ValueKind == JsonValueKind.Object
            ? resources
            : default;
        foreach (var property in resolvedChannels.EnumerateObject())
        {
            var hasPackagedResource = packagedChannels.Contains(property.Name);
            var hasValidatedResource = resourceChannels.ValueKind == JsonValueKind.Object
                && resourceChannels.TryGetProperty(property.Name, out var resourceId)
                && resourceId.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(resourceId.GetString())
                && validatedResourceIds.Contains(resourceId.GetString()!);
            if (hasPackagedResource || hasValidatedResource)
            {
                // NetMaterialSet resolves a validated resource or packaged
                // channel before this compatibility fallback.  The fallback
                // can legitimately point at CDMW's separate read-only decode
                // cache, but it is never opened when an owned source exists.
                continue;
            }
            ValidateDeclaredPath(
                property.Value,
                packageDirectory,
                leaseRoot,
                uniqueResources,
                ref totalResourceBytes);
        }
    }

    private static void ValidateDeclaredPath(
        JsonElement owner,
        string propertyName,
        string packageDirectory,
        string leaseRoot,
        HashSet<string> uniqueResources,
        ref long totalResourceBytes)
    {
        if (!owner.TryGetProperty(propertyName, out var value))
        {
            throw new InvalidDataException($"A material resource is missing {propertyName}.");
        }
        ValidateDeclaredPath(value, packageDirectory, leaseRoot, uniqueResources, ref totalResourceBytes);
    }

    private static void ValidateDeclaredPath(
        JsonElement value,
        string packageDirectory,
        string leaseRoot,
        HashSet<string> uniqueResources,
        ref long totalResourceBytes)
    {
        if (value.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(value.GetString()))
        {
            return;
        }
        var declared = value.GetString()!;
        var path = Path.GetFullPath(
            Path.IsPathRooted(declared) ? declared : Path.Combine(packageDirectory, declared));
        EnsureContained(path, leaseRoot, "Material resource");
        EnsureNoReparsePoints(path);
        if (!uniqueResources.Add(path))
        {
            return;
        }
        var extension = Path.GetExtension(path).ToLowerInvariant();
        if (extension is not (".dds" or ".png" or ".jpg" or ".jpeg" or ".bmp" or ".gif" or ".tif" or ".tiff"))
        {
            throw new InvalidDataException($"Unsupported material resource type: {extension}");
        }
        var info = new FileInfo(path);
        if (!info.Exists || info.Length <= 0 || info.Length > MaximumResourceBytes)
        {
            throw new InvalidDataException(
                $"Material resource must be between 1 and {MaximumResourceBytes} bytes: {path}");
        }
        totalResourceBytes = checked(totalResourceBytes + info.Length);
        if (totalResourceBytes > MaximumTotalResourceBytes)
        {
            throw new InvalidDataException("Material resources exceed the bounded aggregate input size.");
        }
    }

    private static string ResolveLeaseRoot(string packageDirectory)
    {
        var package = new DirectoryInfo(packageDirectory);
        var hash = package.Parent;
        var packages = hash?.Parent;
        var models = packages?.Parent;
        var preview = models?.Parent;
        if (string.Equals(package.Name, "package", StringComparison.OrdinalIgnoreCase)
            && hash is not null
            && hash.Name.Length == 64
            && hash.Name.All(Uri.IsHexDigit)
            && string.Equals(packages?.Name, "packages", StringComparison.OrdinalIgnoreCase)
            && string.Equals(models?.Name, "models", StringComparison.OrdinalIgnoreCase)
            && string.Equals(preview?.Name, "preview", StringComparison.OrdinalIgnoreCase))
        {
            return Path.GetFullPath(preview!.FullName);
        }
        return packageDirectory;
    }

    private static string NormalizeDirectory(string value, string label)
    {
        var path = Path.GetFullPath(value);
        if (!Directory.Exists(path))
        {
            throw new DirectoryNotFoundException($"{label} does not exist: {path}");
        }
        return Path.TrimEndingDirectorySeparator(path);
    }

    private static void EnsureSeparateTrees(string outputDirectory, string inputRoot)
    {
        if (IsContained(outputDirectory, inputRoot) || IsContained(inputRoot, outputDirectory))
        {
            throw new InvalidDataException("Material-layer output must not overlap the leased input tree.");
        }
    }

    private static void EnsureContained(string path, string root, string label)
    {
        if (!IsContained(path, root))
        {
            throw new InvalidDataException($"{label} escapes its owned root.");
        }
    }

    private static bool IsContained(string path, string root)
    {
        var fullPath = Path.GetFullPath(path);
        var fullRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(root));
        return string.Equals(fullPath, fullRoot, StringComparison.OrdinalIgnoreCase)
            || fullPath.StartsWith(fullRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    }

    private static void EnsureNoReparsePoints(string path)
    {
        var fullPath = Path.GetFullPath(path);
        for (var current = fullPath; !string.IsNullOrWhiteSpace(current); current = Path.GetDirectoryName(current))
        {
            if ((File.Exists(current) || Directory.Exists(current))
                && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException($"Reparse points are not accepted in material-layer paths: {current}");
            }
            var parent = Path.GetDirectoryName(current);
            if (string.Equals(parent, current, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }
        }
    }

    private static void EnsureNoReparsePointsOnExistingAncestors(string path)
    {
        var current = Path.GetFullPath(path);
        while (!File.Exists(current) && !Directory.Exists(current))
        {
            var parent = Path.GetDirectoryName(current);
            if (string.IsNullOrWhiteSpace(parent) || string.Equals(parent, current, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }
            current = parent;
        }
        EnsureNoReparsePoints(current);
    }

    private static string HashFile(string path)
    {
        using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 64 * 1024,
            FileOptions.SequentialScan);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static void WriteAtomicText(string path, string text)
    {
        var stagingPath = path + $".tmp-{Guid.NewGuid():N}";
        try
        {
            File.WriteAllText(stagingPath, text, Utf8NoBom);
            File.Move(stagingPath, path);
        }
        finally
        {
            try
            {
                File.Delete(stagingPath);
            }
            catch
            {
                // The unique staging file is best-effort cleanup on failure.
            }
        }
    }

    private static string ValueFor(string[] args, string name)
    {
        var index = Array.FindIndex(
            args,
            argument => string.Equals(argument, name, StringComparison.OrdinalIgnoreCase));
        return index >= 0 && index + 1 < args.Length ? args[index + 1] : string.Empty;
    }

    private sealed record SurfaceTransform(
        SurfaceChannelTransform Roughness,
        SurfaceChannelTransform Metalness)
    {
        public static SurfaceTransform ForSynthesizedLayerSurface(NetMaterialParameters parameters)
        {
            return new SurfaceTransform(
                new SurfaceChannelTransform(
                    1,
                    parameters.RoughnessInverted == true,
                    parameters.RoughnessScale ?? 1.0f,
                    (parameters.RoughnessMin ?? 0) / 255.0f,
                    (parameters.RoughnessMax ?? 255) / 255.0f,
                    parameters.RoughnessBlendTarget ?? 0.0f,
                    parameters.RoughnessBlendStrength ?? 0.0f,
                    parameters.Roughness),
                new SurfaceChannelTransform(
                    2,
                    parameters.MetalnessInverted == true,
                    parameters.MetalnessScale ?? 1.0f,
                    (parameters.MetalnessMin ?? 0) / 255.0f,
                    (parameters.MetalnessMax ?? 255) / 255.0f,
                    parameters.MetalnessBlendTarget ?? 0.0f,
                    parameters.MetalnessBlendStrength ?? 0.0f,
                    parameters.Metalness));
        }

        public Dictionary<string, object?> Metadata() => new()
        {
            ["operation_order"] = new[] { "invert", "scale", "minimum", "maximum", "blend", "override" },
            ["roughness"] = Roughness.Metadata(),
            ["metalness"] = Metalness.Metadata(),
            ["presentation_tuning_baked"] = false,
            ["category_tuning_baked"] = false,
        };
    }

    private sealed record SurfaceChannelTransform(
        int SourceChannel,
        bool Inverted,
        float Scale,
        float Minimum,
        float Maximum,
        float BlendTarget,
        float BlendStrength,
        float? Override)
    {
        public float Apply(float source)
        {
            // This is the exact pre-presentation order in
            // D3D11MaterialShaders.hlsl. Presentation roughness bias,
            // metalness scale, family policy and category heuristics remain
            // renderer-owned and are deliberately not baked into the texture.
            var value = Inverted ? 1.0f - source : source;
            value *= Math.Max(Scale, 0.0f);
            value = Math.Max(value, Minimum);
            value = Math.Min(value, Maximum);
            value = value + (BlendTarget - value) * Math.Clamp(BlendStrength, 0.0f, 1.0f);
            return Override ?? value;
        }

        public Dictionary<string, object?> Metadata() => new()
        {
            ["source_channel"] = SourceChannel switch
            {
                0 => "r",
                1 => "g",
                2 => "b",
                3 => "a",
                _ => throw new InvalidDataException("Material surface selector is outside RGBA."),
            },
            ["inverted"] = Inverted,
            ["scale"] = Scale,
            ["minimum"] = Minimum,
            ["maximum"] = Maximum,
            ["blend_target"] = BlendTarget,
            ["blend_strength"] = BlendStrength,
            ["override"] = Override,
        };
    }
}
