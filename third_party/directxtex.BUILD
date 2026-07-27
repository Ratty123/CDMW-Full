"""Bazel build for Microsoft DirectXTex, pinned to the commit cd_texture_dx's
CMakeLists fetches. Replaces the FetchContent + CMake sub-build.

Built as a static library, so neither DIRECTX_TEX_EXPORT nor DIRECTX_TEX_IMPORT
is defined and DIRECTX_TEX_API expands to nothing - matching what the CMake
static build produces.
"""

load("@crimson_desert_mod_workbench//build_defs:hlsl.bzl", "fxc_shader_headers")

package(default_visibility = ["//visibility:public"])

# BCDirectCompute.cpp includes these by bare filename, so the generated
# directory has to land on the include path (see `includes` below).
fxc_shader_headers(
    name = "bc7_shaders",
    srcs = ["DirectXTex/Shaders/BC7Encode.hlsl"],
    entry_points = [
        "TryMode456CS",
        "TryMode137CS",
        "TryMode02CS",
        "EncodeBlockCS",
    ],
    output_dir = "DirectXTex/Shaders/Compiled",
)

fxc_shader_headers(
    name = "bc6h_shaders",
    srcs = ["DirectXTex/Shaders/BC6HEncode.hlsl"],
    entry_points = [
        "TryModeG10CS",
        "TryModeLE10CS",
        "EncodeBlockCS",
    ],
    output_dir = "DirectXTex/Shaders/Compiled",
)

cc_library(
    name = "directxtex",
    srcs = [
        "DirectXTex/BC.cpp",
        "DirectXTex/BC4BC5.cpp",
        "DirectXTex/BC6HBC7.cpp",
        "DirectXTex/BCDirectCompute.cpp",
        "DirectXTex/DirectXTexCompress.cpp",
        "DirectXTex/DirectXTexCompressGPU.cpp",
        "DirectXTex/DirectXTexConvert.cpp",
        "DirectXTex/DirectXTexD3D11.cpp",
        # DirectXTexD3D12.cpp is deliberately omitted. It needs d3dx12.h from
        # the separate DirectX-Headers package, and cd-texture-dx references no
        # D3D12 symbol anywhere - so the CMake build compiles a translation unit
        # nothing in this tool ever calls. Add DirectX-Headers here if a future
        # caller actually needs the D3D12 compression path.
        "DirectXTex/DirectXTexDDS.cpp",
        "DirectXTex/DirectXTexFlipRotate.cpp",
        "DirectXTex/DirectXTexHDR.cpp",
        "DirectXTex/DirectXTexImage.cpp",
        "DirectXTex/DirectXTexMipmaps.cpp",
        "DirectXTex/DirectXTexMisc.cpp",
        "DirectXTex/DirectXTexNormalMaps.cpp",
        "DirectXTex/DirectXTexPMAlpha.cpp",
        "DirectXTex/DirectXTexResize.cpp",
        "DirectXTex/DirectXTexTGA.cpp",
        "DirectXTex/DirectXTexUtil.cpp",
        "DirectXTex/DirectXTexWIC.cpp",
    ],
    hdrs = [
        "DirectXTex/BC.h",
        "DirectXTex/BCDirectCompute.h",
        "DirectXTex/DDS.h",
        "DirectXTex/DirectXTex.h",
        "DirectXTex/DirectXTexP.h",
        "DirectXTex/filters.h",
        "DirectXTex/scoped.h",
    ],
    copts = [
        "/std:c++17",
        "/EHsc",
        # CMake sets BC_USE_OPENMP ON, which the BC6H/BC7 codecs read through
        # _OPENMP. MSVC only defines that with /openmp.
        "/openmp",
    ],
    includes = [
        "DirectXTex",
        "DirectXTex/Shaders/Compiled",
    ],
    linkopts = [
        "-DEFAULTLIB:windowscodecs.lib",
        "-DEFAULTLIB:ole32.lib",
        "-DEFAULTLIB:uuid.lib",
        "-DEFAULTLIB:d3d11.lib",
        "-DEFAULTLIB:dxgi.lib",
    ],
    local_defines = [
        "NOMINMAX",
        "WIN32_LEAN_AND_MEAN",
        "_WIN32_WINNT=0x0A00",
    ],
    textual_hdrs = [
        ":bc6h_shaders",
        ":bc7_shaders",
    ],
)
