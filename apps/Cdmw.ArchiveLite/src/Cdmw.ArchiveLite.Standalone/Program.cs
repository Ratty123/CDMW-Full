using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;

namespace Cdmw.ArchiveLite.Standalone;

internal static class Program
{
    private const string PayloadResourceName = "Cdmw.ArchiveLite.Standalone.Payload.zip";
    private const string SelfTestArgument = "--standalone-self-test";
    private const uint ErrorIcon = 0x00000010;

    [STAThread]
    private static async Task<int> Main(string[] args)
    {
        var selfTest = args.Contains(SelfTestArgument, StringComparer.OrdinalIgnoreCase);
        var runtimeRoot = StandaloneRuntime.ResolveRuntimeRoot();
        try
        {
            await using var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream(PayloadResourceName)
                ?? throw new InvalidDataException("The embedded Archive Lite payload is missing.");
            var applicationDirectory = await StandaloneRuntime.EnsureExtractedAsync(
                payload,
                runtimeRoot,
                CancellationToken.None).ConfigureAwait(false);
            var applicationArguments = selfTest
                ? new[] { "--self-test" }
                : args.Where(argument => !argument.Equals(SelfTestArgument, StringComparison.OrdinalIgnoreCase)).ToArray();
            return await RunApplicationAsync(applicationDirectory, applicationArguments).ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            WriteDiagnostic(runtimeRoot, exception);
            if (!selfTest)
            {
                _ = MessageBox(
                    0,
                    "CDMW Archive Lite could not start.\n\n" +
                    "The standalone runtime could not be prepared. Details were written to the Archive Lite logs folder.",
                    "CDMW Archive Lite could not start",
                    ErrorIcon);
            }
            return 1;
        }
    }

    private static async Task<int> RunApplicationAsync(string applicationDirectory, IReadOnlyList<string> arguments)
    {
        var applicationPath = Path.Combine(applicationDirectory, "CdmwArchiveLite.exe");
        var startInfo = new ProcessStartInfo
        {
            FileName = applicationPath,
            WorkingDirectory = applicationDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("Windows did not start the extracted Archive Lite application.");
        await process.WaitForExitAsync().ConfigureAwait(false);
        return process.ExitCode;
    }

    private static void WriteDiagnostic(string runtimeRoot, Exception exception)
    {
        try
        {
            var logDirectory = Path.Combine(Directory.GetParent(runtimeRoot)?.FullName ?? runtimeRoot, "logs");
            Directory.CreateDirectory(logDirectory);
            var message = $"{DateTimeOffset.UtcNow:O} standalone startup failure{Environment.NewLine}{exception}{Environment.NewLine}";
            File.AppendAllText(Path.Combine(logDirectory, "standalone-launcher.log"), message, new UTF8Encoding(false));
        }
        catch (Exception logException) when (logException is IOException or UnauthorizedAccessException)
        {
            // Startup reporting must not replace the original failure.
        }
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "MessageBoxW")]
    private static extern int MessageBox(nint window, string text, string caption, uint type);
}
