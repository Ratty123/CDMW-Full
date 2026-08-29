using System.Drawing;
using System.Globalization;
using System.IO;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal static class MeshEditOperatorContractSmoke
{
    private const string Schema = "cdmw_mesh_edit_operator_contract_v1";

    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-mesh-edit-operator-contract", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = ValueAfter(args, "--mesh-edit-operator-report");
        try
        {
            var gates = Execute();
            var report = new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["ok"] = gates.Values.All(value => value),
                ["gates"] = gates,
                ["required_states"] = Enum.GetNames<MeshEditOperatorState>()
                    .Select(name => name.ToLowerInvariant())
                    .ToArray(),
            };
            PreviewPerformanceReport.WriteAtomic(reportPath, report);
            return report["ok"] is true ? 0 : 2;
        }
        catch (Exception ex)
        {
            PreviewPerformanceReport.WriteAtomic(reportPath, new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["ok"] = false,
                ["error"] = $"{ex.GetType().Name}: {ex.Message}",
            });
            return 1;
        }
    }

    private static Dictionary<string, bool> Execute()
    {
        var input = new MeshViewportInputAdapter().Normalize(
            new MouseEventArgs(MouseButtons.Left, 1, 17, 23, 0),
            Keys.Control | Keys.Shift,
            hasCapture: true,
            hasFocus: true);
        var inputNormalized = input.Location == new Point(17, 23)
            && input.Changed(MeshPointerButtons.Left)
            && input.IsHeld(MeshPointerButtons.Left)
            && input.Control
            && input.Shift
            && !input.Alt
            && input.HasCapture
            && input.HasFocus;
        var trackedInput = new MeshViewportInputAdapter();
        var trackedDown = trackedInput.NormalizeDown(
            new MouseEventArgs(MouseButtons.Left, 1, 11, 13, 0),
            Keys.None,
            hasCapture: false,
            hasFocus: false);
        var trackedMove = trackedInput.NormalizeMove(
            new MouseEventArgs(MouseButtons.None, 0, 19, 29, 0),
            Keys.None,
            hasCapture: true,
            hasFocus: true);
        var trackedUp = trackedInput.NormalizeUp(
            new MouseEventArgs(MouseButtons.Left, 1, 19, 29, 0),
            Keys.None,
            hasCapture: true,
            hasFocus: true);
        var heldStateTracked = trackedDown.IsHeld(MeshPointerButtons.Left)
            && trackedMove.IsHeld(MeshPointerButtons.Left)
            && !trackedUp.IsHeld(MeshPointerButtons.Left);
        using var controller = new MeshEditOperatorController();
        var finished = Snapshot("grab-finished");
        var began = controller.Begin(finished, out _);
        var conflictRejected = !controller.Begin(Snapshot("conflict"), out var conflictReason)
            && conflictReason.StartsWith("active_operator_conflict", StringComparison.Ordinal);
        var updated = controller.Update(finished.GestureId);
        var confirmed = controller.Confirm(finished.GestureId);
        var authorityApplied = controller.ApplyAuthoritativeResult(finished.GestureId);
        var rendererCompleted = controller.CompleteRenderer(finished.GestureId);
        var finishedIdle = controller.State == MeshEditOperatorState.Idle
            && controller.LastTerminalState == MeshEditOperatorTerminalState.Finished;

        var cancelled = Snapshot("lasso-cancelled", tool: "select", kind: "lasso_select");
        var rollbackCalled = false;
        var cancelSettled = controller.Begin(cancelled, out _)
            && controller.Update(cancelled.GestureId)
            && controller.RollbackProvisionalState(
                cancelled.GestureId,
                () => rollbackCalled = true)
            && controller.Cancel(cancelled.GestureId)
            && controller.State == MeshEditOperatorState.Idle
            && controller.LastTerminalState == MeshEditOperatorTerminalState.Cancelled;

        var rejected = Snapshot("selection-rejected", tool: "select", kind: "brush_select");
        var rejectionSettled = controller.Begin(rejected, out _)
            && controller.Confirm(rejected.GestureId)
            && controller.Reject(rejected.GestureId, "stale_selection", "stale")
            && controller.State == MeshEditOperatorState.Idle
            && controller.LastFailureCode == "stale_selection";

        var failed = Snapshot("pinch-failed", tool: "pinch", kind: "pinch");
        var recoverySettled = controller.Begin(failed, out _);
        controller.Fail("publication_failed", "fault");
        recoverySettled = recoverySettled
            && controller.State == MeshEditOperatorState.Failed
            && controller.RecoverToIdle()
            && controller.State == MeshEditOperatorState.Idle
            && controller.LastTerminalState == MeshEditOperatorTerminalState.Failed;

        var invalid = Snapshot("") with { BaseGeometryRevision = -1 };
        var invalidRejected = !controller.Begin(invalid, out var invalidReason)
            && invalidReason == "invalid_operator_snapshot";
        const int mixedStressCycles = 1_000;
        var mixedStressPassed = true;
        for (var cycle = 0; cycle < mixedStressCycles && mixedStressPassed; cycle++)
        {
            var tool = (cycle % 5) switch
            {
                0 => "move",
                1 => "grab",
                2 => "smooth",
                3 => "inflate",
                _ => "pinch",
            };
            var snapshot = Snapshot($"mixed-{cycle}", tool: tool, kind: tool);
            mixedStressPassed = controller.Begin(snapshot, out _)
                && controller.Update(snapshot.GestureId);
            switch (cycle % 4)
            {
                case 0:
                    mixedStressPassed = mixedStressPassed
                        && controller.Confirm(snapshot.GestureId)
                        && controller.ApplyAuthoritativeResult(snapshot.GestureId)
                        && controller.CompleteRenderer(snapshot.GestureId);
                    break;
                case 1:
                    mixedStressPassed = mixedStressPassed
                        && controller.Cancel(snapshot.GestureId);
                    break;
                case 2:
                    mixedStressPassed = mixedStressPassed
                        && controller.Confirm(snapshot.GestureId)
                        && controller.Reject(snapshot.GestureId, "stress_rejected", "expected");
                    break;
                default:
                    controller.Fail("stress_failed", "expected");
                    mixedStressPassed = mixedStressPassed
                        && controller.State == MeshEditOperatorState.Failed
                        && controller.RecoverToIdle();
                    break;
            }
            mixedStressPassed = mixedStressPassed
                && controller.State == MeshEditOperatorState.Idle;
        }
        return new Dictionary<string, bool>
        {
            ["platform_input_normalized"] = inputNormalized,
            ["boundary_button_state_tracked"] = heldStateTracked,
            ["begin"] = began,
            ["one_active_operator"] = conflictRejected,
            ["update"] = updated,
            ["confirm"] = confirmed,
            ["authoritative_result"] = authorityApplied,
            ["renderer_settlement"] = rendererCompleted,
            ["finished_returns_idle"] = finishedIdle,
            ["rollback_invoked"] = rollbackCalled,
            ["cancel_returns_idle"] = cancelSettled,
            ["rejection_returns_idle"] = rejectionSettled,
            ["failure_recovery_returns_idle"] = recoverySettled,
            ["invalid_snapshot_fails_closed"] = invalidRejected,
            ["mixed_1000_cycle_rearm"] = mixedStressPassed,
        };
    }

    private static MeshEditOperatorSnapshot Snapshot(
        string gestureId,
        string tool = "grab",
        string kind = "grab") => new(
            kind,
            tool,
            "mesh_edit",
            "vertex",
            gestureId,
            4,
            7,
            8,
            3);

    private static string ValueAfter(string[] args, string option)
    {
        for (var index = 0; index < args.Length - 1; index++)
        {
            if (string.Equals(args[index], option, StringComparison.OrdinalIgnoreCase))
            {
                return Path.GetFullPath(args[index + 1]);
            }
        }
        return Path.Combine(Path.GetTempPath(), "cdmw-mesh-edit-operator-contract.json");
    }
}
