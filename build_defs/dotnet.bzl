"""Run `dotnet publish` as a Bazel action with a declared tree output.

rules_dotnet does not cover self-contained single-file win-x64 publishes well,
so this drives the SDK directly - the same approach the PowerShell build uses,
but with declared inputs and outputs so Bazel caches the result instead of
republishing on every run.

Two things matter for correctness:
  * MSBuild writes obj/ and bin/ next to the .csproj by default. In Bazel's
    execroot those paths are symlinks into the real source tree, so a plain
    publish would write build output back into the repo. Base*OutputPath is
    redirected into a separate declared directory to prevent that.
  * `dotnet publish` restores NuGet packages, so the action needs network and
    cannot be sandboxed.
"""

def _dotnet_publish_impl(ctx):
    published = ctx.actions.declare_directory(ctx.attr.name)
    intermediate = ctx.actions.declare_directory(ctx.attr.name + "_msbuild")

    args = ctx.actions.args()
    args.add("publish")
    args.add(ctx.file.project.path)
    args.add("-c", ctx.attr.configuration)
    args.add("-r", "win-x64")
    args.add("--self-contained", "true" if ctx.attr.self_contained else "false")
    args.add("-p:PublishSingleFile=" + ("true" if ctx.attr.single_file else "false"))
    args.add("-p:PublishTrimmed=false")
    args.add("-o", published.path)
    # --artifacts-path, not BaseIntermediateOutputPath: the latter is a global
    # MSBuild property, so every ProjectReference in a multi-project build lands
    # in the SAME obj/ and the generated AssemblyInfo.cs files collide with
    # CS0579 duplicate-attribute errors. --artifacts-path gives each project its
    # own subdirectory and keeps all of it out of the source tree.
    args.add("--artifacts-path", intermediate.path)
    args.add("--nologo")
    args.add("--verbosity:minimal")

    ctx.actions.run(
        outputs = [published, intermediate],
        inputs = ctx.files.srcs + [ctx.file.project],
        executable = ctx.attr.dotnet_path,
        arguments = [args],
        mnemonic = "DotnetPublish",
        progress_message = "Publishing .NET %s" % ctx.label.name,
        use_default_shell_env = True,
        execution_requirements = {
            "no-sandbox": "1",
            "requires-network": "1",
        },
    )

    return [DefaultInfo(files = depset([published]))]

dotnet_publish = rule(
    implementation = _dotnet_publish_impl,
    doc = "Publish a .NET project self-contained for win-x64 into a tree artifact.",
    attrs = {
        "project": attr.label(allow_single_file = [".csproj"], mandatory = True),
        "srcs": attr.label_list(allow_files = True, default = []),
        "configuration": attr.string(default = "Release"),
        "single_file": attr.bool(default = True),
        "self_contained": attr.bool(
            default = True,
            doc = "Shipped helpers must be self-contained. Developer-only tools " +
                  "can turn this off: any machine running this build already " +
                  "has the .NET SDK, and it saves ~110 MB per binary.",
        ),
        "dotnet_path": attr.string(default = "C:/Program Files/dotnet/dotnet.exe"),
    },
)
