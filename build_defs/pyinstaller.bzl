"""Package the application with PyInstaller as a Bazel action.

CrimsonDesertModWorkbench.spec resolves everything relative to SPECPATH and
reads the native helpers from a fixed layout (native/<project>/build/<Config>/).
So the rule cannot simply point PyInstaller at the repo: it stages a tree in
bazel-out containing the Python sources plus every Bazel-built artifact at the
path the spec expects, then runs PyInstaller against that.

Staging (rather than running in the execroot) is deliberate. Source files in the
execroot are symlinks into the real repo, so letting the spec's staging paths
resolve there would write build output back into the working tree.
"""

def _pyinstaller_package_impl(ctx):
    exe = ctx.actions.declare_file(ctx.attr.exe_name)
    stage = ctx.actions.declare_directory(ctx.attr.name + "_stage")
    work = ctx.actions.declare_directory(ctx.attr.name + "_work")

    # src|dest pairs, consumed from a params file: the source list runs to
    # thousands of entries and will not fit on a Windows command line.
    manifest = ctx.actions.args()
    manifest.set_param_file_format("multiline")
    manifest.use_param_file("--manifest=%s", use_always = True)

    inputs = []
    for src in ctx.files.srcs:
        # Source files keep their repo-relative path inside the stage.
        manifest.add("{}|{}".format(src.path, src.short_path))
        inputs.append(src)

    for target, staged_dir in ctx.attr.staged_artifacts.items():
        for artifact in target.files.to_list():
            if artifact.is_directory:
                manifest.add("{}|{}|tree".format(artifact.path, staged_dir))
            else:
                manifest.add("{}|{}/{}".format(artifact.path, staged_dir, artifact.basename))
            inputs.append(artifact)

    args = ctx.actions.args()
    args.add(ctx.file._driver.path)
    args.add("--stage", stage.path)
    args.add("--work", work.path)
    args.add("--spec", ctx.file.spec.short_path)
    args.add("--out", exe.path)
    args.add("--exe-name", ctx.attr.exe_name)
    args.add("--python", ctx.attr.python_path)
    args.add("--mode", ctx.attr.mode)
    args.add("--profile", ctx.attr.profile)

    ctx.actions.run(
        outputs = [exe, stage, work],
        inputs = inputs + [ctx.file._driver],
        # The build venv interpreter, not a Bazel Python toolchain: PyInstaller
        # must run under the exact interpreter whose site-packages get bundled.
        executable = ctx.attr.python_path,
        arguments = [args, manifest],
        mnemonic = "PyInstaller",
        progress_message = "Packaging %s with PyInstaller" % ctx.attr.exe_name,
        use_default_shell_env = True,
        execution_requirements = {
            "no-sandbox": "1",
            # PyInstaller's analysis is heavily parallel internally and the
            # action is long; keep other actions off its back.
            "cpu:4": "1",
        },
    )

    return [DefaultInfo(files = depset([exe]), executable = exe)]

pyinstaller_package = rule(
    implementation = _pyinstaller_package_impl,
    doc = "Stage the app plus its native helpers and run PyInstaller over the spec.",
    attrs = {
        "srcs": attr.label_list(allow_files = True, mandatory = True),
        "spec": attr.label(allow_single_file = [".spec"], mandatory = True),
        "staged_artifacts": attr.label_keyed_string_dict(
            allow_files = True,
            default = {},
            doc = "Built artifact -> directory it must occupy inside the stage.",
        ),
        "exe_name": attr.string(default = "CrimsonDesertModWorkbench.exe"),
        "mode": attr.string(default = "onefile"),
        "profile": attr.string(default = "release"),
        "python_path": attr.string(
            default = "D:/CLAUDETEST/app_restructuring/.venv/Scripts/python.exe",
            doc = "Absolute path to the build venv interpreter that has " +
                  "PyInstaller, PySide6, numpy and OpenImageIO installed.",
        ),
        "_driver": attr.label(
            default = "//tools:bazel_pyinstaller_driver.py",
            allow_single_file = True,
        ),
    },
)
