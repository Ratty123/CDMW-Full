using System.Windows.Forms;

namespace Cdmw.BazelLauncher;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        // Spelled out rather than ApplicationConfiguration.Initialize(): that
        // class is source-generated into the project's root namespace, which is
        // derived from the assembly name and is not this one.
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);

        var workspaceRoot = RepoLocator.FindWorkspaceRoot(AppContext.BaseDirectory)
            ?? RepoLocator.FindWorkspaceRoot(Directory.GetCurrentDirectory())
            ?? PromptForWorkspaceRoot();

        if (workspaceRoot is null)
        {
            return;
        }

        var bazel = RepoLocator.FindBazel(workspaceRoot);
        if (bazel is null)
        {
            MessageBox.Show(
                "Could not find bazel.exe.\n\n" +
                $"Looked for {Path.Combine(workspaceRoot.FullName, ".tools", "bazel", "bazel.exe")} " +
                "and for bazel.exe on PATH.",
                "Crimson Desert Mod Workbench - Build",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return;
        }

        Application.Run(new MainForm(workspaceRoot, bazel, RepoLocator.FindVisualStudioVc()));
    }

    private static DirectoryInfo? PromptForWorkspaceRoot()
    {
        MessageBox.Show(
            "Could not find the workspace root (no MODULE.bazel above this executable).\n\n" +
            "Pick the repository folder.",
            "Crimson Desert Mod Workbench - Build",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information);

        using var picker = new FolderBrowserDialog
        {
            Description = "Select the repository root (the folder containing MODULE.bazel)",
            UseDescriptionForTitle = true,
        };

        if (picker.ShowDialog() != DialogResult.OK)
        {
            return null;
        }

        var chosen = RepoLocator.FindWorkspaceRoot(picker.SelectedPath);
        if (chosen is null)
        {
            MessageBox.Show(
                "That folder does not contain MODULE.bazel.",
                "Crimson Desert Mod Workbench - Build",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }

        return chosen;
    }
}
