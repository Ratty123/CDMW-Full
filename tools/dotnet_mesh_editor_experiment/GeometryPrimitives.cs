namespace Cdmw.MeshEditorExperiment;

internal readonly record struct DdsColor(byte R, byte G, byte B, byte A);

internal sealed record NetDdsTextureInfo(string Path, int Width, int Height, int MipCount, string FourCc, bool Decoded);

internal readonly record struct Vec2(float U, float V);
internal readonly record struct Vec3(float X, float Y, float Z);
