namespace Cdmw.MeshEditorExperiment;

internal readonly record struct DdsColor(byte R, byte G, byte B, byte A);

internal sealed record NetDdsTextureInfo(
    string Path,
    int Width,
    int Height,
    int MipCount,
    string FourCc,
    bool Decoded,
    bool NativeUploadSupported,
    string NativeFormat,
    bool SourceSrgb,
    string NativeFallbackReason);

internal sealed record NetDdsNativeTextureData(
    int Width,
    int Height,
    int MipCount,
    string FormatKey,
    bool SourceSrgb,
    byte[] Data,
    IReadOnlyList<NetDdsSubresource> Subresources);

internal readonly record struct NetDdsSubresource(
    int Offset,
    int RowPitch,
    int SlicePitch,
    int Width,
    int Height);

internal readonly record struct Vec2(float U, float V);
internal readonly record struct Vec3(float X, float Y, float Z);
