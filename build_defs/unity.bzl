"""Reproduce CMake's UNITY_BUILD_MODE GROUP for Bazel.

The owner sources under cdmw_preview_core and cdmw_mesh_core are not standalone
translation units. CMake concatenates each UNITY_GROUP into one generated file,
wrapped in UNITY_BUILD_CODE_BEFORE_INCLUDE / _AFTER_INCLUDE, which is what opens
the enclosing namespace and pulls in the internal header. Compiling those files
individually does not merely build slower - it does not compile at all.

Bazel has no unity-build feature, so this rule generates the same concatenation.
It uses ctx.actions.write rather than a genrule because genrule on Windows wants
a shell, and there is no MSYS bash on this machine.
"""

def _cmake_unity_source_impl(ctx):
    out = ctx.actions.declare_file(ctx.attr.out)

    includes = []
    for src in ctx.files.srcs:
        path = src.path
        if not path.startswith(ctx.attr.strip_prefix):
            fail(
                "unity source {} does not start with strip_prefix {}".format(
                    path,
                    ctx.attr.strip_prefix,
                ),
            )
        includes.append('#include "{}"'.format(path[len(ctx.attr.strip_prefix):]))

    content = ctx.attr.code_before_include + "\n".join(includes) + ctx.attr.code_after_include
    ctx.actions.write(output = out, content = content)
    return [DefaultInfo(files = depset([out]))]

cmake_unity_source = rule(
    implementation = _cmake_unity_source_impl,
    doc = "Generate a CMake-equivalent unity translation unit from a source group.",
    attrs = {
        "srcs": attr.label_list(
            allow_files = True,
            mandatory = True,
            doc = "Sources to concatenate, in order. Order is significant.",
        ),
        "out": attr.string(
            mandatory = True,
            doc = "Name of the generated .cpp file.",
        ),
        "strip_prefix": attr.string(
            mandatory = True,
            doc = "Execroot-relative prefix to strip so the #include lines " +
                  "resolve against the target's own -I directory.",
        ),
        "code_before_include": attr.string(default = ""),
        "code_after_include": attr.string(default = ""),
    },
)
