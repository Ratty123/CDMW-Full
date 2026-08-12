using Cdmw.Archive.Content;

namespace Cdmw.FullArchive.Core;

internal static class ArchivePreviewReferenceScanner
{
    private const int MaximumTokens = 16384;
    private const int MaximumTokenCharacters = 1024;

    public static ArchivePreviewReferenceTokens Extract(
        byte[] data,
        CancellationToken cancellationToken,
        bool includeMaterialBasenameHints)
    {
        var tokens = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var truncated = CollectAsciiTokens(data, tokens, cancellationToken, includeMaterialBasenameHints);
        truncated |= CollectUtf16Tokens(data, tokens, cancellationToken, includeMaterialBasenameHints);
        return new ArchivePreviewReferenceTokens(tokens, truncated);
    }

    private static bool CollectAsciiTokens(
        byte[] data,
        HashSet<string> destination,
        CancellationToken cancellationToken,
        bool includeMaterialBasenameHints)
    {
        var token = new char[MaximumTokenCharacters];
        var length = 0;
        var overlong = false;
        var truncated = false;
        for (var index = 0; index < data.Length; index++)
        {
            if ((index & 0xFFFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            if (IsTokenCharacter(data[index]))
            {
                if (length < token.Length)
                {
                    token[length++] = (char)data[index];
                }
                else
                {
                    overlong = true;
                }
            }
            else
            {
                truncated |= FlushToken(token, ref length, ref overlong, destination, includeMaterialBasenameHints);
            }
        }
        truncated |= FlushToken(token, ref length, ref overlong, destination, includeMaterialBasenameHints);
        return truncated;
    }

    private static bool CollectUtf16Tokens(
        byte[] data,
        HashSet<string> destination,
        CancellationToken cancellationToken,
        bool includeMaterialBasenameHints)
    {
        var truncated = false;
        for (var parity = 0; parity < 2; parity++)
        {
            var token = new char[MaximumTokenCharacters];
            var length = 0;
            var overlong = false;
            for (var index = parity; index + 1 < data.Length; index += 2)
            {
                if ((index & 0xFFFF) == 0)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                }
                if (data[index + 1] == 0 && IsTokenCharacter(data[index]))
                {
                    if (length < token.Length)
                    {
                        token[length++] = (char)data[index];
                    }
                    else
                    {
                        overlong = true;
                    }
                }
                else
                {
                    truncated |= FlushToken(token, ref length, ref overlong, destination, includeMaterialBasenameHints);
                }
            }
            truncated |= FlushToken(token, ref length, ref overlong, destination, includeMaterialBasenameHints);
        }
        return truncated;
    }

    private static bool FlushToken(
        char[] buffer,
        ref int length,
        ref bool overlong,
        HashSet<string> destination,
        bool includeMaterialBasenameHints)
    {
        var truncated = overlong;
        if (!overlong && length >= 4)
        {
            var token = new string(buffer, 0, length).Trim('.', '/', '\\');
            if (token.Length >= 4 && token.Contains('.') && !destination.Contains(token))
            {
                if (destination.Count < MaximumTokens)
                {
                    destination.Add(token);
                }
                else
                {
                    truncated = true;
                }
            }
            if (includeMaterialBasenameHints && IsMaterialBasenameHint(token))
            {
                var materialPath = token + ".dds";
                if (!destination.Contains(materialPath))
                {
                    if (destination.Count >= MaximumTokens)
                    {
                        truncated = true;
                    }
                    else
                    {
                        destination.Add(materialPath);
                    }
                }
            }
            var recoveredPath = RecoverPathBeforeTrailingLengthByte(token);
            if (!string.IsNullOrEmpty(recoveredPath) && !destination.Contains(recoveredPath))
            {
                if (destination.Count >= MaximumTokens)
                {
                    truncated = true;
                }
                else
                {
                    destination.Add(recoveredPath);
                }
            }
        }
        length = 0;
        overlong = false;
        return truncated;
    }

    private static bool IsMaterialBasenameHint(string token) =>
        token.Length > 3
        && token.StartsWith("cd_", StringComparison.OrdinalIgnoreCase)
        && !token.Contains('.')
        && !token.Contains('/')
        && !token.Contains('\\');

    private static string RecoverPathBeforeTrailingLengthByte(string token)
    {
        if (token.Length < 5 || (!token.Contains('/') && !token.Contains('\\')))
        {
            return string.Empty;
        }
        var candidate = token[..^1];
        return ArchiveContentRegistry.All.Any(capability =>
            capability.Extension.Length >= 4
            && candidate.EndsWith(capability.Extension, StringComparison.OrdinalIgnoreCase))
                ? candidate
                : string.Empty;
    }

    private static bool IsTokenCharacter(byte value) =>
        value is >= (byte)'0' and <= (byte)'9' or
        >= (byte)'A' and <= (byte)'Z' or
        >= (byte)'a' and <= (byte)'z' or
        (byte)'/' or (byte)'\\' or (byte)'.' or (byte)'_' or (byte)'-';
}

internal sealed record ArchivePreviewReferenceTokens(
    IReadOnlyCollection<string> Tokens,
    bool Truncated);
