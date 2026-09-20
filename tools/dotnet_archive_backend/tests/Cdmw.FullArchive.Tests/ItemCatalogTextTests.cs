using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class ItemCatalogTextTests
{
    public static async Task EncodingAsync()
    {
        // Reproduce the reporter's stray 9F at byte 11, then cover invalid UTF-8
        // scalar values and truncation without losing the valid text beside them.
        byte[][] invalid = [[0x9F], [0xC0, 0xAF], [0xE0, 0x80, 0x80], [0xED, 0xA0, 0x80],
            [0xF4, 0x90, 0x80, 0x80], [0xFF], [0xE2, 0x82]];
        foreach (var bytes in invalid)
        {
            var name = Encoding.UTF8.GetBytes("Test Blade ").Concat(bytes).ToArray();
            await CheckCatalogueAsync(Table(name), display =>
                display.Contains('\uFFFD') && display.Replace("\uFFFD", "", StringComparison.Ordinal) == "Test Blade ",
                "malformed name bytes escaped into JSON or discarded valid text");
        }
        const string unicode = "Épée 日本語 검 سيف 🗡️ \"quoted\" \\path";
        await CheckCatalogueAsync(Table(Encoding.UTF8.GetBytes(unicode)), display => display == unicode,
            "valid multilingual text or JSON escapes changed");
        var interrupted = Encoding.UTF8.GetBytes("Test Blade ").Concat(new byte[] { 0xE2, 0x28, 0xA1 })
            .Concat(Encoding.UTF8.GetBytes(" 日本語")).ToArray();
        await CheckCatalogueAsync(Table(interrupted), display => display == "Test Blade \uFFFD(\uFFFD 日本語",
            "invalid sequence swallowed adjacent ASCII or Unicode");
    }

    public static async Task CompressedAsync()
    {
        const string name = "Test Blade Test Blade Test Blade Test Blade ";
        var table = Table(Encoding.UTF8.GetBytes(name));
        var compressed = CompressRepeatedName(table);
        await CheckCatalogueAsync(Container(compressed, table.Length), display => display == name.Trim(),
            "compressed PALOC text was scanned without decompression", seedOldCache: true);
    }

    public static async Task InvalidContainerAsync()
    {
        var table = Table(Encoding.UTF8.GetBytes("Test Blade Test Blade Test Blade Test Blade "));
        var valid = Container(CompressRepeatedName(table), table.Length);
        var badVersion = (byte[])valid.Clone();
        BinaryPrimitives.WriteUInt32LittleEndian(badVersion.AsSpan(5), 1);
        var badStoredSize = (byte[])valid.Clone();
        BinaryPrimitives.WriteUInt32LittleEndian(badStoredSize.AsSpan(9), 1);
        var oversized = (byte[])valid.Clone();
        BinaryPrimitives.WriteUInt32LittleEndian(oversized.AsSpan(13), 256 * 1024 * 1024 + 1);
        var wrongDecodedSize = (byte[])valid.Clone();
        BinaryPrimitives.WriteUInt32LittleEndian(wrongDecodedSize.AsSpan(13), (uint)table.Length + 1);
        var cases = new (byte[] Bytes, string Error)[]
        {
            ("paloc"u8.ToArray(), "header is truncated"),
            (badVersion, "version"),
            (badStoredSize, "compressed size"),
            (oversized, "uncompressed size"),
            (wrongDecodedSize, "decoded size"),
            (Container([0xF0], 20), "length is truncated"),
            (Container([0x00, 0x00, 0x00], 20), "match offset"),
            (Container([0x20, 0x41], 20), "literal run"),
            (Container([0x1F, 0x41, 0x01, 0x00, 0x00], 4), "match run"),
        };
        foreach (var (bytes, error) in cases)
        {
            await using var fixture = await SyntheticArchiveFixture.CreateCurrentItemNamesAsync(bytes);
            using var sessions = new ArchiveSessionManager(new NativeArchiveCore(), new ArchiveCacheStore(Path.Combine(fixture.Root, "cache")));
            var handle = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
            var builder = new ArchiveItemCatalogBuildService(sessions, new NativeArchiveCore());
            try
            {
                await builder.BuildAsync(new BuildNameIndexRequest(handle.SessionId), null, CancellationToken.None);
            }
            catch (InvalidDataException exception) when (exception.Message.Contains("loc_eng.bin", StringComparison.Ordinal)
                && exception.Message.Contains(error, StringComparison.Ordinal))
            {
                continue;
            }
            throw new InvalidOperationException($"Invalid PALOC container was accepted: {error}");
        }
    }

    private static async Task CheckCatalogueAsync(byte[] localization, Func<string, bool> checkName, string failure, bool seedOldCache = false)
    {
        await using var fixture = await SyntheticArchiveFixture.CreateCurrentItemNamesAsync(localization);
        var cache = new ArchiveCacheStore(Path.Combine(fixture.Root, "cache"));
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native, cache);
        var handle = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
        var session = sessions.GetRequired(handle.SessionId);
        if (seedOldCache)
        {
            var signature = Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(Path.Combine(fixture.Root, "meta", "0.papgt"))));
            await File.WriteAllTextAsync(Path.Combine(session.GenerationPath, $"item-catalog-v5-{signature}.json"),
                "{\"schema_version\":5,\"exact_names\":{},\"related_names\":{},\"items\":[]}");
        }
        var builder = new ArchiveItemCatalogBuildService(sessions, native);
        var built = await builder.BuildAsync(new BuildNameIndexRequest(handle.SessionId), null, CancellationToken.None);
        Require(built.Available && !built.UsedCache && built.ItemCount == 3, "catalogue was incomplete or reused the old cache");
        var service = new ArchiveItemCatalogService(sessions, builder);
        var results = await service.SearchAsync(new ItemCatalogSearchRequest(handle.SessionId), null, CancellationToken.None);
        Require(results.TotalMatches == 3, "blank Item Finder search lost rows");
        Require(checkName(results.Items.Single(row => row.ItemId == 1234).DisplayName), failure);
        Require(results.Items.Single(row => row.ItemId == 1235).DisplayName == "Blade", "an unaffected name changed");
        var translated = await service.SearchAsync(new ItemCatalogSearchRequest(handle.SessionId, "سيف الاختبار"), null, CancellationToken.None);
        Require(translated.Items.Count == 1 && translated.Items[0].ItemId == 1234, "localized search lost valid Unicode");
        var model = session.Index.FindEntriesByPath("character/model/cd_shared_armor_0002.pac").Single();
        Require(session.ReadEntry(model.EntryId).ExactName.Contains(results.Items.Single(row => row.ItemId == 1234).DisplayName,
            StringComparison.Ordinal), "the catalogue's model name map lost the recovered display name");

        // A fresh session must read the published catalogue, not its in-memory predecessor.
        using var reopened = new ArchiveSessionManager(native, cache);
        var warmHandle = await reopened.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
        var warmBuilder = new ArchiveItemCatalogBuildService(reopened, native);
        var warm = await warmBuilder.BuildAsync(new BuildNameIndexRequest(warmHandle.SessionId), null, CancellationToken.None);
        Require(warm.UsedCache && warm.ItemCount == 3, "the repaired catalogue did not round-trip through the disk cache");
        var warmRows = await new ArchiveItemCatalogService(reopened, warmBuilder).SearchAsync(
            new ItemCatalogSearchRequest(warmHandle.SessionId, "1234"), null, CancellationToken.None);
        Require(warmRows.Items.Count == 1 && checkName(warmRows.Items[0].DisplayName), "cached display text changed");
    }

    private static byte[] Table(byte[] name)
    {
        using var output = new MemoryStream();
        using var writer = new BinaryWriter(output, Encoding.UTF8, leaveOpen: true);
        foreach (var (key, text) in new[] { ("12345678", name), ("12345679", "Blade"u8.ToArray()) })
        {
            writer.Write(7u);
            writer.Write(0u);
            var keyBytes = Encoding.UTF8.GetBytes(key);
            writer.Write((uint)keyBytes.Length);
            writer.Write(keyBytes);
            writer.Write((uint)text.Length);
            writer.Write(text);
        }
        writer.Write(2u);
        return output.ToArray();
    }

    private static byte[] CompressRepeatedName(byte[] table)
    {
        // A real overlapping LZ4 match, with extended literal and match lengths.
        // Literal-only fixtures let the old byte scanner find names by accident.
        var unit = "Test Blade "u8;
        var literalEnd = table.AsSpan().IndexOf(unit) + unit.Length;
        var matchLength = unit.Length * 3;
        using var output = new MemoryStream();
        output.WriteByte(0xFF);
        output.WriteByte((byte)(literalEnd - 15));
        output.Write(table, 0, literalEnd);
        output.WriteByte((byte)unit.Length);
        output.WriteByte(0);
        output.WriteByte((byte)(matchLength - 4 - 15));
        var tail = table.AsSpan(literalEnd + matchLength);
        output.WriteByte(0xF0);
        output.WriteByte((byte)(tail.Length - 15));
        output.Write(tail);
        return output.ToArray();
    }

    private static byte[] Container(byte[] compressed, int decodedSize)
    {
        var bytes = new byte[512 + compressed.Length];
        "paloc"u8.CopyTo(bytes);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(9), (uint)compressed.Length);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(13), (uint)decodedSize);
        compressed.CopyTo(bytes, 512);
        return bytes;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
