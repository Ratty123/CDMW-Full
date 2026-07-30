namespace Cdmw.FullArchive.Core;

/// <summary>
/// The ordering the archive index is actually written in.
/// </summary>
/// <remarks>
/// The native builder sorts entries with <c>compare_case_insensitive</c>
/// (<c>native/cdmw_full_archive_core/src/archive_core_internal.hpp</c>), which folds
/// A-Z down to a-z and then compares in order. <see cref="StringComparer.OrdinalIgnoreCase"/>
/// folds the other way, and the two disagree wherever '_' (0x5F) meets a letter:
/// uppercase puts 'D' (0x44) before '_', lowercase puts '_' before 'd' (0x64). Asset
/// paths here are full of '_', so anything that searches the index by order — rather
/// than merely comparing two strings for equality — has to fold down, not up.
///
/// UTF-16 units stand in for UTF-8 bytes, which is exact for every path below U+10000.
/// </remarks>
internal static class ArchivePathOrder
{
    public static int Compare(string left, string right)
    {
        var common = Math.Min(left.Length, right.Length);
        for (var index = 0; index < common; index++)
        {
            var difference = ToLowerAscii(left[index]) - ToLowerAscii(right[index]);
            if (difference != 0)
            {
                return difference < 0 ? -1 : 1;
            }
        }
        return left.Length.CompareTo(right.Length);
    }

    /// <summary>
    /// Orders a path against a folder prefix: negative before the prefix's rows, zero
    /// inside them, positive after. Every path carrying the prefix is contiguous under
    /// <see cref="Compare"/>, which is what makes a folder listing a range search.
    /// </summary>
    public static int ComparePrefix(string path, string prefix)
    {
        var common = Math.Min(path.Length, prefix.Length);
        for (var index = 0; index < common; index++)
        {
            var difference = ToLowerAscii(path[index]) - ToLowerAscii(prefix[index]);
            if (difference != 0)
            {
                return difference < 0 ? -1 : 1;
            }
        }
        return path.Length >= prefix.Length ? 0 : -1;
    }

    public static bool Equal(string left, string right) => Compare(left, right) == 0;

    private static char ToLowerAscii(char value) => value is >= 'A' and <= 'Z' ? (char)(value + 32) : value;
}
