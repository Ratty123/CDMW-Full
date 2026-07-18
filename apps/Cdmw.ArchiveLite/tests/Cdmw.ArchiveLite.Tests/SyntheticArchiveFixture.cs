using System.Buffers.Binary;
using System.Text;

namespace Cdmw.ArchiveLite.Tests;

internal sealed class SyntheticArchiveFixture : IAsyncDisposable
{
    private SyntheticArchiveFixture(string root)
    {
        Root = root;
        Pamt = Path.Combine(root, "base", "0.pamt");
        Paz = Path.Combine(root, "base", "0.paz");
        Pathc = Path.Combine(root, "meta", "0.pathc");
        OutputRoot = root + "-output";
    }

    public string Root { get; }
    public string Pamt { get; }
    public string Paz { get; }
    public string Pathc { get; }
    public string OutputRoot { get; }

    public static async Task<SyntheticArchiveFixture> CreateAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"cdmw-archive-lite-tests-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        var fixture = new SyntheticArchiveFixture(root);
        Directory.CreateDirectory(Path.GetDirectoryName(fixture.Pamt)!);
        Directory.CreateDirectory(Path.GetDirectoryName(fixture.Pathc)!);
        var plainText = Encoding.UTF8.GetBytes("Hello Crimson\nline 2");
        var materialText = Encoding.UTF8.GetBytes("material alpha");
        var materialLz4 = EncodeLz4Literal(materialText);
        var binary = new byte[] { 0, 1, 2, 3, 4, 5, 0xFF };
        var (partialDds, pathc) = BuildPartialDds();
        var payloads = new[] { plainText, materialLz4, binary, partialDds };
        await using (var stream = new FileStream(fixture.Paz, FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, FileOptions.Asynchronous))
        {
            foreach (var payload in payloads) await stream.WriteAsync(payload).ConfigureAwait(false);
            await stream.FlushAsync().ConfigureAwait(false);
            stream.Flush(flushToDisk: true);
        }
        var entries = new[]
        {
            new EntrySpec("text/hello.txt", 0u, (uint)plainText.Length, (uint)plainText.Length, 0),
            new EntrySpec("materials/sample.material", (uint)plainText.Length, (uint)materialLz4.Length, (uint)materialText.Length, 2),
            new EntrySpec("binary/blob.bin", (uint)(plainText.Length + materialLz4.Length), (uint)binary.Length, (uint)binary.Length, 0),
            new EntrySpec(
                "texture/test.dds",
                (uint)(plainText.Length + materialLz4.Length + binary.Length),
                (uint)partialDds.Length,
                0x88,
                1),
        };
        await File.WriteAllBytesAsync(fixture.Pamt, BuildPamt(entries)).ConfigureAwait(false);
        await File.WriteAllBytesAsync(fixture.Pathc, pathc).ConfigureAwait(false);
        return fixture;
    }

    public static async Task<SyntheticArchiveFixture> CreateAssociatedAssetsAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"cdmw-archive-lite-associations-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        var fixture = new SyntheticArchiveFixture(root);
        Directory.CreateDirectory(Path.GetDirectoryName(fixture.Pamt)!);

        var payloads = new (string Path, byte[] Bytes)[]
        {
            ("character/model/hero.pac", [0x50, 0x41, 0x43, 0x00, 0x01]),
            (
                "character/modelproperty/hero.pac_xml",
                Encoding.UTF8.GetBytes(
                    "<material><texture path=\"character/texture/hero_body_d.dds\" />"
                    + "<texture path=\"character/texture/hero_body_n.dds\" />"
                    + "<physics path=\"character/physics/hero.hkx\" /></material>")),
            ("character/texture/hero_body_d.dds", "DDS synthetic diffuse"u8.ToArray()),
            ("character/texture/hero_body_n.dds", "DDS synthetic normal"u8.ToArray()),
            ("character/physics/hero.hkx", [0x48, 0x4B, 0x58, 0x00]),
            ("character/model/hero.meshinfo", Encoding.UTF8.GetBytes("mesh metadata")),
            ("character/model/hero.prefab", Encoding.UTF8.GetBytes("prefab metadata")),
            ("unrelated/other.dds", "DDS unrelated"u8.ToArray()),
        };

        var entries = new List<EntrySpec>(payloads.Length);
        uint offset = 0;
        await using (var stream = new FileStream(fixture.Paz, FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, FileOptions.Asynchronous))
        {
            foreach (var payload in payloads)
            {
                await stream.WriteAsync(payload.Bytes).ConfigureAwait(false);
                entries.Add(new EntrySpec(
                    payload.Path,
                    offset,
                    checked((uint)payload.Bytes.Length),
                    checked((uint)payload.Bytes.Length),
                    0));
                offset = checked(offset + (uint)payload.Bytes.Length);
            }
            await stream.FlushAsync().ConfigureAwait(false);
            stream.Flush(flushToDisk: true);
        }
        await File.WriteAllBytesAsync(fixture.Pamt, BuildPamt(entries)).ConfigureAwait(false);
        return fixture;
    }

    public ValueTask DisposeAsync()
    {
        try
        {
            Directory.Delete(Root, recursive: true);
        }
        catch (IOException)
        {
            // Memory maps can release just after the test scope; temp cleanup is best-effort.
        }
        try
        {
            if (Directory.Exists(OutputRoot)) Directory.Delete(OutputRoot, recursive: true);
        }
        catch (IOException)
        {
            // Export handles can release just after the test scope.
        }
        return ValueTask.CompletedTask;
    }

    private static byte[] BuildPamt(IReadOnlyList<EntrySpec> entries)
    {
        using var output = new MemoryStream();
        WriteUInt32(output, 0);
        WriteUInt32(output, 1);
        WriteUInt32(output, 0);
        WriteUInt32(output, 0);
        WriteUInt32(output, 0);
        WriteUInt32(output, 0);
        WriteUInt32(output, 0);

        using var names = new MemoryStream();
        var nameOffsets = new List<uint>();
        foreach (var entry in entries)
        {
            nameOffsets.Add(checked((uint)names.Position));
            WriteUInt32(names, uint.MaxValue);
            var path = Encoding.UTF8.GetBytes(entry.Path);
            if (path.Length > byte.MaxValue) throw new InvalidOperationException("Synthetic path is too long.");
            names.WriteByte((byte)path.Length);
            names.Write(path);
        }
        WriteUInt32(output, checked((uint)names.Length));
        names.Position = 0;
        names.CopyTo(output);
        WriteUInt32(output, 0);
        WriteUInt32(output, checked((uint)entries.Count));
        for (var index = 0; index < entries.Count; index++)
        {
            var entry = entries[index];
            WriteUInt32(output, nameOffsets[index]);
            WriteUInt32(output, entry.Offset);
            WriteUInt32(output, entry.StoredSize);
            WriteUInt32(output, entry.OriginalSize);
            WriteUInt16(output, 0);
            WriteUInt16(output, entry.Flags);
        }
        return output.ToArray();
    }

    private static byte[] EncodeLz4Literal(byte[] bytes)
    {
        using var output = new MemoryStream();
        if (bytes.Length < 15)
        {
            output.WriteByte((byte)(bytes.Length << 4));
        }
        else
        {
            output.WriteByte(0xF0);
            var remaining = bytes.Length - 15;
            while (remaining >= 255)
            {
                output.WriteByte(255);
                remaining -= 255;
            }
            output.WriteByte((byte)remaining);
        }
        output.Write(bytes);
        return output.ToArray();
    }

    private static (byte[] Payload, byte[] Pathc) BuildPartialDds()
    {
        var header = new byte[0x80];
        "DDS "u8.CopyTo(header);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(4), 124);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(12), 4);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(16), 4);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(20), 8);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(28), 1);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(32), 9);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(36), 8);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(76), 32);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(80), 4);
        "DXT1"u8.CopyTo(header.AsSpan(84));

        using var payload = new MemoryStream();
        payload.Write(header);
        payload.WriteByte(0x80);
        payload.Write([1, 2, 3, 4, 5, 6, 7, 8]);

        using var pathc = new MemoryStream();
        WriteUInt32(pathc, 0);
        WriteUInt32(pathc, 0);
        WriteUInt32(pathc, 0x80);
        WriteUInt32(pathc, 1);
        WriteUInt32(pathc, 1);
        WriteUInt32(pathc, 0);
        WriteUInt32(pathc, 0);
        pathc.Write(header);
        WriteUInt32(pathc, 0x54E11B82);
        WriteUInt16(pathc, 0);
        pathc.WriteByte(0);
        pathc.WriteByte(0);
        pathc.Write(new byte[16]);
        return (payload.ToArray(), pathc.ToArray());
    }

    private static void WriteUInt16(Stream stream, ushort value)
    {
        Span<byte> bytes = stackalloc byte[2];
        BinaryPrimitives.WriteUInt16LittleEndian(bytes, value);
        stream.Write(bytes);
    }

    private static void WriteUInt32(Stream stream, uint value)
    {
        Span<byte> bytes = stackalloc byte[4];
        BinaryPrimitives.WriteUInt32LittleEndian(bytes, value);
        stream.Write(bytes);
    }

    private sealed record EntrySpec(string Path, uint Offset, uint StoredSize, uint OriginalSize, ushort Flags);
}
