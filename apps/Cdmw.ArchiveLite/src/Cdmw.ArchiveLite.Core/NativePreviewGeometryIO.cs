using System.Buffers.Binary;

namespace Cdmw.ArchiveLite.Core;

internal static class NativePreviewGeometryIO
{
    public const int FloatsPerPreviewVertex = 23;
    public const int BytesPerPreviewVertex = FloatsPerPreviewVertex * sizeof(float);
    public const int RecordsPerChunk = 98_304;

    public static FileStream OpenRead(string path) => new(
        path,
        FileMode.Open,
        FileAccess.Read,
        FileShare.Read,
        256 * 1024,
        FileOptions.Asynchronous | FileOptions.SequentialScan);

    public static FileStream OpenNew(string path) => new(
        path,
        FileMode.CreateNew,
        FileAccess.Write,
        FileShare.None,
        256 * 1024,
        FileOptions.Asynchronous | FileOptions.SequentialScan);

    public static void WriteFiniteVec3AsF64(
        byte[] input,
        int sourceOffset,
        byte[] output,
        int outputOffset,
        string label)
    {
        for (var component = 0; component < 3; component++)
        {
            var value = ReadFiniteSingle(input, sourceOffset + (component * 4), label);
            BinaryPrimitives.WriteDoubleLittleEndian(output.AsSpan(outputOffset + (component * 8), 8), value);
        }
    }

    public static void WriteFiniteVec2AsF64(
        byte[] input,
        int sourceOffset,
        byte[] output,
        int outputOffset,
        string label)
    {
        for (var component = 0; component < 2; component++)
        {
            var value = ReadFiniteSingle(input, sourceOffset + (component * 4), label);
            BinaryPrimitives.WriteDoubleLittleEndian(output.AsSpan(outputOffset + (component * 8), 8), value);
        }
    }

    public static float ReadFiniteSingle(byte[] input, int offset, string label)
    {
        var value = BinaryPrimitives.ReadSingleLittleEndian(input.AsSpan(offset, sizeof(float)));
        if (!float.IsFinite(value))
        {
            throw new InvalidDataException($"Native preview geometry contains a non-finite {label} value.");
        }
        return value;
    }
}
