using System.IO;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            var options = LaunchOptions.Parse(args);
            var document = ObjDocument.Load(options.MeshPath);
            Directory.CreateDirectory(options.OutputDir);
            if (options.HeadlessSmoke)
            {
                var editedSubmeshes = ExperimentForm.ApplyHeadlessSmokeEdit(document);
                ExperimentForm.SaveOutput(options, document, editedSubmeshes, HeadlessRenderer.Measure(document));
                return 0;
            }

            ApplicationConfiguration.Initialize();
            Application.Run(new ExperimentForm(options, document));
            return 0;
        }
        catch (Exception ex)
        {
            var options = LaunchOptions.TryParse(args);
            if (options is not null)
            {
                ExperimentForm.WriteStatus(options, "error", ex.Message, null);
            }
            var suppressDialog = Array.Exists(args, arg =>
                string.Equals(arg, "--embedded", StringComparison.OrdinalIgnoreCase)
                || string.Equals(arg, "--headless-smoke", StringComparison.OrdinalIgnoreCase));
            if (!suppressDialog)
            {
                MessageBox.Show(ex.Message, "CDMW .NET Mesh Editor Experiment", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            return 1;
        }
    }
}
