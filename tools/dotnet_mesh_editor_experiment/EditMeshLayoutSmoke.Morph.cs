using System.Drawing;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static partial class EditMeshLayoutSmoke
{
    private static void RequireExistingMorphAuthorWizardContract(IReadOnlyList<MorphPartChoice> parts)
    {
        using var definitionDocument = JsonDocument.Parse(
            "{\"definition_id\":\"waist\",\"label\":\"Waist\",\"rule\":\"taper\",\"axis\":\"x\",\"amount\":0.25,\"feather\":4,\"falloff\":\"linear\",\"mirror_mode\":\"x\",\"min_percent\":-50,\"default_percent\":10,\"max_percent\":75}");
        using var editor = new MorphAuthorDialog(
            "body-profile",
            "Body",
            definitionDocument.RootElement,
            parts,
            Array.Empty<MorphPartChoice>(),
            new Dictionary<string, object?>(),
            Color.FromArgb(23, 25, 29),
            Color.FromArgb(31, 34, 40),
            Color.FromArgb(43, 47, 55),
            Color.White,
            Color.Silver);
        _ = editor.Handle;
        var edited = editor.Payload;
        var replaceSelection = RequiredControl<CheckBox>(editor, "MorphWizardReplaceSelection");
        Require(
            editor.ProfileId == "body-profile"
                && editor.DefinitionId == "waist"
                && string.Equals(Convert.ToString(edited["rule"]), "taper", StringComparison.Ordinal)
                && Convert.ToDouble(edited["default_percent"]) == 10.0
                && editor.PreserveExistingSelection
                && !replaceSelection.Checked,
            "Editing an existing Morph profile did not reload its v2 definition.");
        InvokeButton(RequiredControl<Button>(editor, "MorphWizardNextButton"));
        InvokeButton(RequiredControl<Button>(editor, "MorphWizardNextButton"));
        Require(
            RequiredControl<Label>(editor, "MorphWizardStepTitle").Text == "3. Deformation",
            "Editing a Morph slider required an unrelated ambient viewport selection.");
        replaceSelection.Checked = true;
        Require(
            !editor.PreserveExistingSelection
                && RequiredControl<RadioButton>(editor, "MorphWizardUseParts").Enabled,
            "The explicit Replace authored region choice did not enable replacement selection controls.");

        using var meshSelectionWizard = new MorphAuthorDialog(
            string.Empty,
            string.Empty,
            definition: null,
            parts,
            Array.Empty<MorphPartChoice>(),
            new Dictionary<string, object?>
            {
                ["vertices_by_submesh"] = new Dictionary<string, int[]> { ["2"] = new[] { 3, 4, 5 } },
            },
            Color.FromArgb(23, 25, 29),
            Color.FromArgb(31, 34, 40),
            Color.FromArgb(43, 47, 55),
            Color.White,
            Color.Silver);
        _ = meshSelectionWizard.Handle;
        InvokeButton(RequiredControl<Button>(meshSelectionWizard, "MorphWizardNextButton"));
        InvokeButton(RequiredControl<Button>(meshSelectionWizard, "MorphWizardNextButton"));
        Require(
            RequiredControl<Label>(meshSelectionWizard, "MorphWizardStepTitle").Text == "3. Deformation",
            "The Morph wizard rejected an acknowledged viewport mesh selection.");
        var meshSelectionPayload = JsonSerializer.SerializeToElement(meshSelectionWizard.Payload["local_selection"]);
        Require(
            meshSelectionPayload.GetProperty("source_indices").GetArrayLength() == 0
                && meshSelectionPayload.GetProperty("vertices_by_submesh").GetProperty("2").GetArrayLength() == 3,
            "The Morph wizard promoted a viewport mesh selection to whole parts.");
    }
}
