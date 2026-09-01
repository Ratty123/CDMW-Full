from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
CSHARP_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"
NATIVE_DLL = ROOT / "native" / "cdmw_mesh_core" / "build" / "Release" / "cdmw-mesh-core.dll"
EXPECTED_HEADER_SHA256 = "603044AF6B01430939112DA0CD173B15674E43B3E3BED92D67B55BB2D1A9840A"


MANAGED_PROOF_PROGRAM = r'''
using System.Text.Json;
using Cdmw.MeshEditorExperiment;

internal static class ManagedAbiProof
{
    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    private static NativeMeshInteractionGestureRequest Move(
        ulong gestureId,
        ulong meshRevision,
        double deltaZ
    ) => new()
    {
        GestureId = gestureId,
        MeshRevision = meshRevision,
        SelectionRevision = 2,
        TopologyGeneration = 1,
        CameraRevision = 1,
        ViewportRevision = 1,
        Tool = NativeMeshInteractionTool.Move,
        Strength = 1.0,
        Pressure = 1.0,
        DeltaZ = deltaZ,
    };

    private static NativeMeshInteractionAuthorityRequest Authority(
        NativeMeshInteractionAuthorityAction action,
        ulong baseRevision,
        ulong revision,
        ulong gestureId = 0
    ) => new(
        gestureId,
        action,
        baseRevision,
        revision,
        2,
        2,
        1,
        1
    );

    private static double ReadZ(NativeMeshInteractionSession session)
    {
        NativeMeshVertexReadOutcome read = session.ReadVertices(0, 1, 1);
        Require(read.Result.IsSuccess, $"read failed: {read.Result.Status} {read.Result.Message}");
        Require(read.WrittenVertexCount == 1 && read.PositionsXyz.Length == 3, "read count mismatch");
        return read.PositionsXyz[2];
    }

    private static NativeMeshInteractionResult Prepare(
        NativeMeshInteractionSession session,
        ulong meshRevision
    )
    {
        NativeMeshInteractionResult result = session.PrepareSnapshot(
            new NativeMeshInteractionPrepareSnapshotRequest(
                meshRevision,
                2,
                1,
                1,
                1,
                1,
                1,
                false
            )
        );
        Require(result.IsSuccess, $"snapshot preparation failed: {result.Status} {result.Message}");
        return result;
    }

    public static void Main()
    {
        using NativeMeshInteractionAbi abi = NativeMeshInteractionAbi.LoadFromApplicationDirectory();
        NativeMeshInteractionDiagnostics diagnostics = abi.Diagnostics;
        Require(
            Path.GetFullPath(diagnostics.LibraryPath) ==
                Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "cdmw-mesh-core.dll")),
            "loader did not use the application-directory DLL"
        );
        Require(diagnostics.AbiVersion == 1, "ABI version mismatch");
        Require(diagnostics.Contract == "cdmw_mesh_interaction_abi_v1", "contract mismatch");
        Require(diagnostics.Backend == "cdmw_mesh_core_0.1", "backend mismatch");
        Require(
            diagnostics.HeaderSha256.Equals(
                NativeMeshInteractionAbi.ExpectedHeaderSha256,
                StringComparison.OrdinalIgnoreCase
            ),
            "header SHA mismatch"
        );
        Require(diagnostics.StructSizes.Count == 13, "struct size count mismatch");
        Require(diagnostics.StructSizes[NativeMeshInteractionStructId.SyncV1] == 296, "sync size mismatch");
        Require(diagnostics.StructSizes[NativeMeshInteractionStructId.ResultV1] == 376, "result size mismatch");
        Require(diagnostics.StructSizes[NativeMeshInteractionStructId.ProjectionV1] == 144, "projection size mismatch");
        Require(diagnostics.StructSizes[NativeMeshInteractionStructId.PrepareSnapshotV1] == 80, "snapshot size mismatch");

        var submesh = new NativeMeshSubmeshData(
            0,
            [
                0.0, 0.0, 0.0,
                1.0, 0.0, 0.0,
                0.0, 1.0, 0.0,
                1.0, 1.0, 0.0,
            ],
            null,
            [0u, 1u, 2u, 2u, 1u, 3u]
        );
        var openRequest = new NativeMeshInteractionOpenRequest(0xCD4D5702, 1, 1, 1, 0, 0, [submesh]);
        NativeMeshInteractionOpenOutcome opened = abi.Open(openRequest);
        Require(opened.Result.IsSuccess && opened.Session is not null, "open failed");
        NativeMeshInteractionSession session = opened.Session!;

        NativeMeshInteractionResult sync = session.Sync(new NativeMeshInteractionSyncRequest
        {
            Flags = NativeMeshInteractionSyncFlags.Selection
                | NativeMeshInteractionSyncFlags.Camera
                | NativeMeshInteractionSyncFlags.Viewport,
            BaseSelectionRevision = 1,
            SelectionRevision = 2,
            BaseCameraRevision = 0,
            CameraRevision = 1,
            BaseViewportRevision = 0,
            ViewportRevision = 1,
            Selections = [new NativeMeshSelectionData(0, [1u], [], [])],
            Projections =
            [
                new NativeMeshProjectionData(
                    0,
                    [
                        1, 0, 0, 0,
                        0, 1, 0, 0,
                        0, 0, 1, 0,
                        0, 0, 0, 1,
                    ])
            ],
            WorldViewProjection =
            [
                1, 0, 0, 0,
                0, 1, 0, 0,
                0, 0, 1, 0,
                0, 0, 0, 1,
            ],
            ViewportWidth = 640,
            ViewportHeight = 480,
        });
        Require(sync.IsSuccess && sync.SelectionChanges.Count == 1, "sync failed");
        NativeMeshInteractionResult prepared = Prepare(session, 1);

        NativeMeshInteractionResult begin = session.Begin(Move(101, 1, 0.1));
        NativeMeshInteractionResult update = session.Update(Move(101, 1, 0.2));
        NativeMeshInteractionResult end = session.End(Move(101, 1, 0.3));
        Require(begin.IsSuccess && begin.OperatorState == NativeMeshInteractionOperatorState.Active, "begin failed");
        Require(update.IsSuccess && update.DirtyRanges.Count == 1, "update failed");
        Require(
            end.IsSuccess && end.OperatorState == NativeMeshInteractionOperatorState.AwaitingAuthority,
            "end failed"
        );
        Require(Math.Abs(ReadZ(session) - 0.2) < 1e-9, "terminal geometry mismatch");

        NativeMeshInteractionResult accepted = session.ApplyAuthority(
            Authority(NativeMeshInteractionAuthorityAction.Accepted, 1, 2, 101)
        );
        Require(accepted.IsSuccess, "accepted authority failed");
        NativeMeshInteractionResult undo = session.ApplyAuthority(
            Authority(NativeMeshInteractionAuthorityAction.Undo, 2, 3)
        );
        Require(undo.IsSuccess && Math.Abs(ReadZ(session)) < 1e-9, "undo failed");
        NativeMeshInteractionResult redo = session.ApplyAuthority(
            Authority(NativeMeshInteractionAuthorityAction.Redo, 3, 4)
        );
        Require(redo.IsSuccess && Math.Abs(ReadZ(session) - 0.2) < 1e-9, "redo failed");

        prepared = Prepare(session, 4);
        Require(session.Begin(Move(102, 4, 0.25)).IsSuccess, "second begin failed");
        NativeMeshInteractionResult cancelled = session.Cancel(Move(102, 4, 0.0));
        Require(cancelled.IsSuccess, "cancel failed");
        Require(Math.Abs(ReadZ(session) - 0.2) < 1e-9, "cancel did not restore baseline");
        Require(session.Close().IsSuccess, "close failed");
        session.Dispose();

        var reopenRequest = new NativeMeshInteractionOpenRequest(0xCD4D5702, 4, 2, 1, 1, 1, [submesh]);
        NativeMeshInteractionOpenOutcome reopened = abi.Open(reopenRequest);
        Require(reopened.Result.IsSuccess && reopened.Session is not null, "reopen failed");
        Require(reopened.Session!.SessionHandle != session.SessionHandle, "reopen reused a closed handle");
        Require(reopened.Session.Close().IsSuccess, "reopened close failed");
        reopened.Session.Dispose();

        Console.WriteLine(JsonSerializer.Serialize(new
        {
            diagnostics.LibraryPath,
            diagnostics.LibrarySha256,
            diagnostics.AbiVersion,
            diagnostics.Contract,
            diagnostics.Backend,
            diagnostics.HeaderSha256,
            StructCount = diagnostics.StructSizes.Count,
            Open = opened.Result.Status.ToString(),
            Sync = sync.Status.ToString(),
            Prepare = prepared.Status.ToString(),
            Begin = begin.Status.ToString(),
            Update = update.Status.ToString(),
            End = end.Status.ToString(),
            Cancel = cancelled.Status.ToString(),
            Accepted = accepted.Status.ToString(),
            Undo = undo.Status.ToString(),
            Redo = redo.Status.ToString(),
            Reopen = reopened.Result.Status.ToString(),
        }));
    }
}
'''


def test_mesh_unit_builds_and_places_the_production_native_abi() -> None:
    source = (ROOT / "scripts" / "codex_check.ps1").read_text(encoding="utf-8")
    assert 'cmake --build $MeshCoreBuild --config Release --target cdmw-mesh-core-abi' in source
    assert 'Copy-Item -LiteralPath $MeshCoreAbi -Destination (Split-Path -Parent $DotNetHelper) -Force' in source


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )


def _assert_succeeded(result: subprocess.CompletedProcess[str], action: str) -> None:
    assert result.returncode == 0, (
        f"{action} failed with exit code {result.returncode}\n"
        f"stdout:\n{result.stdout[-6000:]}\n"
        f"stderr:\n{result.stderr[-6000:]}"
    )


def test_managed_abi_source_uses_only_the_packaged_absolute_dll() -> None:
    paths = sorted(CSHARP_ROOT.glob("NativeMeshInteractionAbi*.cs"))
    assert {path.name for path in paths} == {
        "NativeMeshInteractionAbi.Contracts.cs",
        "NativeMeshInteractionAbi.Library.cs",
        "NativeMeshInteractionAbi.Marshalling.cs",
        "NativeMeshInteractionAbi.NativeTypes.cs",
        "NativeMeshInteractionAbi.Session.cs",
    }
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "Path.Combine(AppContext.BaseDirectory, DllFileName)" in source
    assert "NativeLibrary.Load(libraryPath)" in source
    assert EXPECTED_HEADER_SHA256 in source
    assert 'ExpectedContract = "cdmw_mesh_interaction_abi_v1"' in source
    assert 'ExpectedBackend = "cdmw_mesh_core_0.1"' in source
    assert "Environment.GetEnvironmentVariable" not in source
    assert "NativeLibrary.TryLoad" not in source
    assert "MemoryMapped" not in source


def test_resident_native_update_timing_is_bounded_and_update_only() -> None:
    gesture = (CSHARP_ROOT / "MeshViewport.NativeInteraction.Gesture.cs").read_text(
        encoding="utf-8"
    )
    timing = (CSHARP_ROOT / "MeshViewport.NativeInteraction.Timing.cs").read_text(
        encoding="utf-8"
    )
    state = (CSHARP_ROOT / "MeshViewport.NativeInteraction.State.cs").read_text(
        encoding="utf-8"
    )
    begin = gesture.split("private bool BeginResidentNativeStroke", 1)[1].split(
        "private void UpdateResidentNativeInteraction", 1
    )[0]
    update = gesture.split("private void UpdateResidentNativeInteraction", 1)[1].split(
        "private void EndResidentNativeInteraction", 1
    )[0]

    assert "ResidentNativeTimingTimestamp()" in update
    assert "TimeResidentNativeUpdate(" in update
    assert "ApplyTimedResidentNativeResult(" in update
    assert "TimeResidentNativeUpdate(" not in begin
    assert "ApplyTimedResidentNativeResult(" not in begin
    assert "ResidentNativeTimingSampleCapacity = 256" in timing
    assert "var result = session.Update(request);" in timing
    assert "ApplyResidentNativeResult(result);" in timing
    for key in ("count", "average_ms", "p95_ms", "max_ms"):
        assert f'["{key}"]' in timing
    assert '["input_handler_timing"] = ResidentNativeInputHandlerTimingDiagnostics()' in state
    assert (
        '["provisional_feedback_timing"] = ResidentNativeProvisionalFeedbackTimingDiagnostics()'
        in state
    )


@pytest.mark.skipif(sys.platform != "win32", reason="the production ABI is a Windows DLL")
def test_managed_abi_executes_against_the_built_native_dll(tmp_path: Path) -> None:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("dotnet is unavailable")
    if not NATIVE_DLL.is_file():
        pytest.skip(f"build the native ABI target first: {NATIVE_DLL}")
    assert os.path.commonpath((tmp_path.resolve(), Path(tempfile.gettempdir()).resolve())) == str(
        Path(tempfile.gettempdir()).resolve()
    )
    program_path = tmp_path / "Program.cs"
    project_path = tmp_path / "ManagedAbiProof.csproj"
    output_path = tmp_path / "out"
    program_path.write_text(MANAGED_PROOF_PROGRAM, encoding="utf-8")
    source_glob = (CSHARP_ROOT / "NativeMeshInteractionAbi*.cs").as_posix()
    project_path.write_text(
        f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net10.0-windows</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <AllowUnsafeBlocks>true</AllowUnsafeBlocks>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="{program_path.as_posix()}" />
    <Compile Include="{source_glob}" Link="%(Filename)%(Extension)" />
  </ItemGroup>
</Project>
''',
        encoding="utf-8",
    )
    build = _run(
        [dotnet, "build", str(project_path), "-c", "Release", "-o", str(output_path), "--nologo", "--verbosity", "quiet"],
        cwd=ROOT,
    )
    _assert_succeeded(build, "managed ABI proof build")
    missing = _run([dotnet, str(output_path / "ManagedAbiProof.dll")], cwd=output_path)
    assert missing.returncode != 0
    assert "Required native mesh ABI was not found at" in missing.stderr
    copied_dll = output_path / "cdmw-mesh-core.dll"
    shutil.copy2(NATIVE_DLL, copied_dll)
    run = _run([dotnet, str(output_path / "ManagedAbiProof.dll")], cwd=output_path)
    _assert_succeeded(run, "managed ABI proof execution")
    report = json.loads(run.stdout.strip().splitlines()[-1])
    assert Path(report["LibraryPath"]).resolve() == copied_dll.resolve()
    assert report["LibrarySha256"] == hashlib.sha256(copied_dll.read_bytes()).hexdigest().upper()
    assert report["HeaderSha256"].upper() == EXPECTED_HEADER_SHA256
    assert report["AbiVersion"] == 1
    assert report["StructCount"] == 13
    for operation in ("Open", "Sync", "Prepare", "Begin", "Update", "End", "Cancel", "Accepted", "Undo", "Redo", "Reopen"):
        assert report[operation] == "Ok"
