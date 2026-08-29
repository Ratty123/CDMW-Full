using System.IO;
using System.Text.Json;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            var provenanceReportIndex = Array.FindIndex(
                args,
                arg => string.Equals(arg, "--helper-provenance-report", StringComparison.OrdinalIgnoreCase));
            if (provenanceReportIndex >= 0)
            {
                if (provenanceReportIndex + 1 >= args.Length)
                {
                    throw new ArgumentException("--helper-provenance-report requires an output path.");
                }
                var reportPath = Path.GetFullPath(args[provenanceReportIndex + 1]);
                Directory.CreateDirectory(Path.GetDirectoryName(reportPath) ?? throw new InvalidOperationException("Provenance report has no parent directory."));
                File.WriteAllText(
                    reportPath,
                    JsonSerializer.Serialize(
                        HelperBuildProvenance.Payload(HelperBuildProvenance.RequiredProtocolCapabilities),
                        new JsonSerializerOptions { WriteIndented = true }));
                return 0;
            }
            if (MaterialResourcePolicyProbe.IsRequested(args))
            {
                return MaterialResourcePolicyProbe.Run(args);
            }
            if (CaptureCameraParityProof.IsRequested(args))
            {
                return CaptureCameraParityProof.Run(args);
            }
            if (PackageCaptureProof.Matches(args))
            {
                ApplicationConfiguration.Initialize();
                return PackageCaptureProof.Run(args);
            }
            if (EditMeshLayoutSmoke.IsRequested(args))
            {
                ApplicationConfiguration.Initialize();
                return EditMeshLayoutSmoke.Run(args);
            }
            if (MorphPageStabilitySmoke.IsRequested(args))
            {
                ApplicationConfiguration.Initialize();
                return MorphPageStabilitySmoke.Run(args);
            }
            if (EditMeshEntrySmoke.IsRequested(args))
            {
                ApplicationConfiguration.Initialize();
                return EditMeshEntrySmoke.Run(args);
            }
            if (UiLocalizationContractSmoke.IsRequested(args))
            {
                return UiLocalizationContractSmoke.Run(args);
            }
            if (ResidentMutationBatchContractSmoke.IsRequested(args))
            {
                return ResidentMutationBatchContractSmoke.Run(args);
            }
            if (StrokeSampleBufferContractSmoke.IsRequested(args))
            {
                return StrokeSampleBufferContractSmoke.Run(args);
            }
            if (SelectionGeometryContractSmoke.IsRequested(args))
            {
                return SelectionGeometryContractSmoke.Run(args);
            }
            if (HeadlessGpuFramePacingSoak.IsRequested(args))
            {
                ApplicationConfiguration.Initialize();
                return HeadlessGpuFramePacingSoak.Run(args);
            }
            if (HeadlessGpuInteractionSoak.IsRequested(args))
            {
                ApplicationConfiguration.Initialize();
                return HeadlessGpuInteractionSoak.Run(args);
            }
            if (HeadlessGpuSparseSoak.IsRequested(args))
            {
                ApplicationConfiguration.Initialize();
                return HeadlessGpuSparseSoak.Run(args);
            }
            if (MaterialAuthorityParityReport.IsRequested(args))
            {
                ApplicationConfiguration.Initialize();
                return MaterialAuthorityParityReport.Run(args);
            }
            if (VisualAuditBatch.IsRequested(args))
            {
                ApplicationConfiguration.Initialize();
                return VisualAuditBatch.Run(args);
            }
            var options = LaunchOptions.Parse(args);
            StartupTiming.Mark("main_entry");
            long sourceParseCount = 0;
            var document = ObjDocument.Load(options.MeshPath);
            StartupTiming.Mark("document_loaded");
            sourceParseCount++;
            Directory.CreateDirectory(options.OutputDir);
            if (options.HeadlessSmoke)
            {
                var editedSubmeshes = ExperimentForm.ApplyHeadlessSmokeEdit(document);
                ExperimentForm.SaveOutput(
                    options,
                    document,
                    editedSubmeshes,
                    HeadlessRenderer.Measure(document),
                    new Dictionary<string, object?>
                    {
                        ["backend"] = "headless_cpu_smoke",
                        ["gpu_backed"] = false,
                        ["renderer_blocked"] = false,
                    });
                return 0;
            }

            ApplicationConfiguration.Initialize();
            InstallUiExceptionGuard(options, IsEmbedded(args));
            using var form = new ExperimentForm(options, document, sourceParseCount);
            Application.Run(form);
            _ = form.DrainPerformanceReport(TimeSpan.FromSeconds(2));
            _ = form.DrainProtocolOutput(TimeSpan.FromMilliseconds(750));
            return 0;
        }
        catch (Exception ex)
        {
            return HandleMainException(args, ex);
        }
    }

    private static int HandleMainException(string[] args, Exception exception)
    {
        var options = LaunchOptions.TryParse(args);
        if (options is not null)
        {
            try
            {
                ExperimentForm.WriteStatus(options, "error", exception.Message, null);
            }
            catch (Exception)
            {
                // Fatal-path status is best effort; never replace the original fault.
            }
        }
        try
        {
            Console.Error.WriteLine(exception);
            Console.Error.Flush();
        }
        catch (IOException)
        {
        }
        var suppressDialog = IsEmbedded(args) || Array.Exists(args, arg =>
            string.Equals(arg, "--headless-smoke", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--headless-edit-mesh-layout-smoke", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--headless-morph-page-stability-smoke", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--headless-edit-mesh-entry-smoke", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--headless-ui-localization-contract", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--headless-capture-camera-parity", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--headless-gpu-frame-pacing-soak", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--headless-gpu-interaction-soak", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--headless-gpu-sparse-soak", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--headless-material-authority-parity", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--capture-package", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--visual-audit-batch", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--material-resource-policy-report", StringComparison.OrdinalIgnoreCase)
            || string.Equals(arg, "--helper-provenance-report", StringComparison.OrdinalIgnoreCase));
        if (!suppressDialog)
        {
            MessageBox.Show(exception.Message, "CDMW .NET Mesh Editor Experiment", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        return 1;
    }

    private static bool IsEmbedded(string[] args) => Array.Exists(
        args,
        arg => string.Equals(arg, "--embedded", StringComparison.OrdinalIgnoreCase));

    /// <summary>
    /// Report UI-thread faults to the host instead of opening a modal dialog.
    /// </summary>
    /// <remarks>
    /// Without this, WinForms answers any exception escaping a WndProc with its
    /// own Continue/Quit dialog. The embedded helper is a borderless child of
    /// the host window, so that dialog is effectively invisible while it blocks
    /// the message loop: the host stops receiving protocol traffic and reports
    /// a hang rather than a fault. Writing the status file and exiting non-zero
    /// gives the host's supervisor a real failure it can retry.
    /// </remarks>
    private static void InstallUiExceptionGuard(LaunchOptions options, bool embedded)
    {
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, threadEvent) =>
            ReportFatalException(options, threadEvent.Exception, embedded);
        AppDomain.CurrentDomain.UnhandledException += (_, domainEvent) =>
            ReportFatalException(options, domainEvent.ExceptionObject as Exception, embedded, terminating: true);
    }

    private static void ReportFatalException(
        LaunchOptions options,
        Exception? exception,
        bool embedded,
        bool terminating = false)
    {
        var message = exception?.ToString() ?? "The .NET mesh editor faulted without exception detail.";
        try
        {
            ExperimentForm.WriteStatus(options, "error", message, null);
        }
        catch (Exception)
        {
            // The status file is best effort; stderr below is the fallback.
        }
        try
        {
            Console.Error.WriteLine(message);
            Console.Error.Flush();
        }
        catch (IOException)
        {
        }
        if (terminating)
        {
            return;
        }
        if (!embedded)
        {
            MessageBox.Show(message, "CDMW .NET Mesh Editor Experiment", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        Environment.Exit(1);
    }
}
