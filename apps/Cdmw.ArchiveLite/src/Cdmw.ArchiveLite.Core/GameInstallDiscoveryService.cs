using System.Text;
using System.Text.RegularExpressions;
using Cdmw.ArchiveLite.Contracts;
using Microsoft.Win32;

namespace Cdmw.ArchiveLite.Core;

public sealed class GameInstallDiscoveryService
{
    private const string CrimsonDesertSteamAppId = "3321460";
    private static readonly Regex SteamLibraryPathPattern = new(
        "\\\"path\\\"\\s+\\\"(?<path>[^\\\"]+)\\\"",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private static readonly Regex SteamInstallDirectoryPattern = new(
        "\\\"installdir\\\"\\s+\\\"(?<path>[^\\\"]+)\\\"",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private static readonly string[] GameDirectoryNames = ["Crimson Desert", "CrimsonDesert"];

    public Task<GameInstallDiscoveryResult> DiscoverAsync(CancellationToken cancellationToken) => Task.Run(
        () => DiscoverCore(cancellationToken),
        cancellationToken);

    public static bool LooksLikeArchivePackageRoot(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }
        try
        {
            var candidate = new DirectoryInfo(Path.GetFullPath(path.Trim()));
            return LooksLikeIndexContainer(candidate)
                || LooksLikeIndexContainer(new DirectoryInfo(Path.Combine(candidate.FullName, "game_files")));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return false;
        }
    }

    public static IReadOnlyList<string> ParseSteamLibraryPaths(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return [];
        }
        return SteamLibraryPathPattern.Matches(text)
            .Select(match => match.Groups["path"].Value.Replace("\\\\", "\\", StringComparison.Ordinal).Trim())
            .Where(static path => !string.IsNullOrWhiteSpace(path))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static GameInstallDiscoveryResult DiscoverCore(CancellationToken cancellationToken)
    {
        var candidates = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        void AddCandidate(string? rawPath)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (string.IsNullOrWhiteSpace(rawPath))
            {
                return;
            }
            try
            {
                var resolved = Path.GetFullPath(Environment.ExpandEnvironmentVariables(rawPath.Trim()));
                if (LooksLikeArchivePackageRoot(resolved) && seen.Add(resolved))
                {
                    candidates.Add(resolved);
                }
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException)
            {
                // A discovery candidate is advisory; inaccessible locations are ignored.
            }
        }

        foreach (var variable in new[]
        {
            "CDMW_ARCHIVE_LITE_GAME_ROOT",
            "CDMW_PACKAGE_ROOT",
            "CRIMSON_DESERT_PACKAGE_ROOT",
            "cdmw_PACKAGE_ROOT",
        })
        {
            AddCandidate(Environment.GetEnvironmentVariable(variable));
        }

        var steamRoots = DiscoverSteamRoots(cancellationToken);
        var libraryRoots = new List<string>();
        var seenLibraries = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var steamRoot in steamRoots)
        {
            AddUniqueExistingDirectory(libraryRoots, seenLibraries, steamRoot);
            foreach (var libraryFile in new[]
            {
                Path.Combine(steamRoot, "steamapps", "libraryfolders.vdf"),
                Path.Combine(steamRoot, "config", "libraryfolders.vdf"),
            })
            {
                cancellationToken.ThrowIfCancellationRequested();
                foreach (var library in ReadSteamLibraryPaths(libraryFile))
                {
                    AddUniqueExistingDirectory(libraryRoots, seenLibraries, library);
                }
            }
        }

        foreach (var libraryRoot in libraryRoots)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var commonRoot = Path.Combine(libraryRoot, "steamapps", "common");
            var manifest = Path.Combine(libraryRoot, "steamapps", $"appmanifest_{CrimsonDesertSteamAppId}.acf");
            var installDirectory = ReadSteamInstallDirectory(manifest);
            if (!string.IsNullOrWhiteSpace(installDirectory))
            {
                AddCandidate(Path.Combine(commonRoot, installDirectory));
            }
            foreach (var name in GameDirectoryNames)
            {
                AddCandidate(Path.Combine(commonRoot, name));
            }
        }

        foreach (var basePath in CommonBasePaths())
        {
            cancellationToken.ThrowIfCancellationRequested();
            foreach (var name in GameDirectoryNames)
            {
                AddCandidate(Path.Combine(basePath, name));
                AddCandidate(Path.Combine(basePath, "Games", name));
                AddCandidate(Path.Combine(basePath, "Epic Games", name));
            }
        }

        foreach (var driveRoot in ExistingDriveRoots())
        {
            cancellationToken.ThrowIfCancellationRequested();
            foreach (var name in GameDirectoryNames)
            {
                foreach (var relative in new[]
                {
                    Path.Combine("Games", name),
                    Path.Combine("games", "Steam", "steamapps", "common", name),
                    Path.Combine("Steam", "steamapps", "common", name),
                    Path.Combine("SteamLibrary", "steamapps", "common", name),
                    Path.Combine("steamapps", "common", name),
                    Path.Combine("Epic Games", name),
                })
                {
                    AddCandidate(Path.Combine(driveRoot, relative));
                }
            }
            DiscoverStoreCandidates(driveRoot, AddCandidate, cancellationToken);
        }

        return new GameInstallDiscoveryResult(candidates, candidates.FirstOrDefault());
    }

    private static IReadOnlyList<string> DiscoverSteamRoots(CancellationToken cancellationToken)
    {
        var roots = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var raw in new[]
        {
            Environment.GetEnvironmentVariable("PROGRAMFILES(X86)"),
            Environment.GetEnvironmentVariable("PROGRAMFILES"),
            @"C:\Steam",
        })
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (string.IsNullOrWhiteSpace(raw))
            {
                continue;
            }
            var candidate = Path.GetFileName(raw.TrimEnd('\\', '/')).Equals("Steam", StringComparison.OrdinalIgnoreCase)
                ? raw
                : Path.Combine(raw, "Steam");
            AddUniqueExistingDirectory(roots, seen, candidate);
        }

        foreach (var (hive, subkey, values) in new[]
        {
            (Registry.CurrentUser, @"Software\Valve\Steam", new[] { "SteamPath", "SteamExe" }),
            (Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Valve\Steam", new[] { "InstallPath", "SteamPath" }),
            (Registry.LocalMachine, @"SOFTWARE\Valve\Steam", new[] { "InstallPath", "SteamPath" }),
        })
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                using var key = hive.OpenSubKey(subkey, writable: false);
                if (key is null)
                {
                    continue;
                }
                foreach (var valueName in values)
                {
                    var value = key.GetValue(valueName)?.ToString();
                    if (string.IsNullOrWhiteSpace(value))
                    {
                        continue;
                    }
                    var candidate = value.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
                        ? Path.GetDirectoryName(value)
                        : value;
                    AddUniqueExistingDirectory(roots, seen, candidate);
                }
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or System.Security.SecurityException)
            {
                // Registry discovery is advisory.
            }
        }
        return roots;
    }

    private static IEnumerable<string> ReadSteamLibraryPaths(string filePath)
    {
        try
        {
            return File.Exists(filePath)
                ? ParseSteamLibraryPaths(File.ReadAllText(filePath, Encoding.UTF8))
                : [];
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return [];
        }
    }

    private static string? ReadSteamInstallDirectory(string filePath)
    {
        try
        {
            if (!File.Exists(filePath))
            {
                return null;
            }
            var match = SteamInstallDirectoryPattern.Match(File.ReadAllText(filePath, Encoding.UTF8));
            return match.Success
                ? match.Groups["path"].Value.Replace("\\\\", "\\", StringComparison.Ordinal).Trim()
                : null;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static IEnumerable<string> CommonBasePaths()
    {
        var values = new[]
        {
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        };
        return values
            .Where(static value => !string.IsNullOrWhiteSpace(value) && Directory.Exists(value))
            .Distinct(StringComparer.OrdinalIgnoreCase);
    }

    private static IEnumerable<string> ExistingDriveRoots()
    {
        foreach (var letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        {
            var root = $"{letter}:\\";
            if (Directory.Exists(root))
            {
                yield return root;
            }
        }
    }

    private static void DiscoverStoreCandidates(
        string driveRoot,
        Action<string?> addCandidate,
        CancellationToken cancellationToken)
    {
        foreach (var containerName in new[] { "XboxGames", "ModifiableWindowsApps", "WindowsApps" })
        {
            cancellationToken.ThrowIfCancellationRequested();
            var container = Path.Combine(driveRoot, containerName);
            if (!Directory.Exists(container))
            {
                continue;
            }
            foreach (var name in GameDirectoryNames)
            {
                foreach (var edition in new[] { name, $"{name} Standard Edition", $"{name} Deluxe Edition" })
                {
                    AddStoreSuffixes(Path.Combine(container, edition), addCandidate);
                }
            }
            try
            {
                foreach (var child in Directory.EnumerateDirectories(container, "*", SearchOption.TopDirectoryOnly))
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    var name = Path.GetFileName(child);
                    if (name.Contains("crimson", StringComparison.OrdinalIgnoreCase)
                        && name.Contains("desert", StringComparison.OrdinalIgnoreCase))
                    {
                        AddStoreSuffixes(child, addCandidate);
                    }
                }
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                // Protected store containers are expected on some systems.
            }
        }
    }

    private static void AddStoreSuffixes(string gameRoot, Action<string?> addCandidate)
    {
        addCandidate(gameRoot);
        addCandidate(Path.Combine(gameRoot, "Content"));
        addCandidate(Path.Combine(gameRoot, "Game"));
        addCandidate(Path.Combine(gameRoot, "Content", "Game"));
    }

    private static bool LooksLikeIndexContainer(DirectoryInfo path)
    {
        if (!path.Exists)
        {
            return false;
        }
        try
        {
            if (path.EnumerateFiles("*.pamt", SearchOption.TopDirectoryOnly).Any())
            {
                return true;
            }
            foreach (var child in path.EnumerateDirectories("*", SearchOption.TopDirectoryOnly))
            {
                if (child.Name.Length == 4
                    && child.Name.All(char.IsDigit)
                    && child.EnumerateFiles("*.pamt", SearchOption.TopDirectoryOnly).Any())
                {
                    return true;
                }
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return false;
        }
        return false;
    }

    private static void AddUniqueExistingDirectory(
        ICollection<string> paths,
        ISet<string> seen,
        string? candidate)
    {
        if (string.IsNullOrWhiteSpace(candidate))
        {
            return;
        }
        try
        {
            var resolved = Path.GetFullPath(Environment.ExpandEnvironmentVariables(candidate.Trim()));
            if (Directory.Exists(resolved) && seen.Add(resolved))
            {
                paths.Add(resolved);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            // Ignore invalid advisory candidates.
        }
    }
}
