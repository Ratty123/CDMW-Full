# Third-Party Notices

Crimson Desert Mod Workbench uses or interoperates with several third-party projects and tools.

This file is a practical notice list for repository and release packaging. For authoritative license text, copyright ownership, and redistribution terms, always refer to the upstream project itself.

## Python / App Dependencies

### PySide6 / Qt for Python

- Purpose: desktop UI framework
- Upstream: https://doc.qt.io/qtforpython-6/
- Notes: this project provides the Qt for Python bindings used by the app UI

### PyInstaller

- Purpose: Windows executable packaging
- Upstream: https://pyinstaller.org/
- Notes: used to build the one-file Windows executable

### python-lz4

- Purpose: archive decompression support
- Upstream: https://github.com/python-lz4/python-lz4
- Notes: used for supported compressed archive entry handling

### cryptography

- Purpose: archive XML decryption support for text search / preview / export
- Upstream: https://github.com/pyca/cryptography
- Notes: used for deterministic ChaCha20 archive payload decryption where supported

## Native Libraries

### DirectXTex

- Purpose: DDS preview conversion, DDS staging, and final DDS rebuild
- Upstream: https://github.com/microsoft/DirectXTex
- Notes: built as a library inside the bundled `cd-texture-dx.exe` helper; no
  separate DirectXTex command-line executable is used at runtime

The four libraries below are vendored into `native/cdmw_mesh_core/third_party/`
and statically linked into the bundled `cdmw-mesh-core` helper. Each directory
carries a `README.md` recording which files were copied and from where, and
meshoptimizer, MikkTSpace, and xatlas keep their upstream notice inside the
vendored source itself.

### meshoptimizer

- Purpose: native mesh optimization; index, overdraw, spatial-order, and
  vertex-cache passes
- Upstream: https://github.com/zeux/meshoptimizer
- Licence: MIT

### MikkTSpace

- Purpose: reference tangent-space generation for `cdmw-mesh-core
  generate-tangents-json`
- Upstream: https://github.com/mmikk/MikkTSpace
- Licence: zlib

### ufbx

- Purpose: FBX scene reading for import preview and the external model audit
- Upstream: https://github.com/ufbx/ufbx
- Licence: MIT. Upstream offers MIT or public domain and CDMW takes the MIT
  option, which requires the notice to travel with the binary. Unlike the other
  three, ufbx's notice is not carried inside `ufbx.h`, so the upstream `LICENSE`
  is vendored beside it and the notice is reproduced here, because this file is
  what ships:

```text
Copyright (c) 2020 Samuli Raivio
Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### xatlas

- Purpose: UV atlas generation for `cdmw-mesh-core auto-uv-json`
- Upstream: https://github.com/jpcy/xatlas
- Licence: MIT

## External Tools

### chaiNNer

- Purpose: optional external upscaling stage
- Upstream: https://chainner.app/
- Download page: https://chainner.app/download/
- CLI documentation: https://github.com/chaiNNer-org/chaiNNer/wiki/05--CLI
- Notes: Crimson Desert Mod Workbench can open the official chaiNNer download page, launch chaiNNer, inspect `.chn` chains, and pass override JSON, but chaiNNer remains a separate upstream application with its own dependencies and licenses

### vgmstream

- Purpose: `.wem` decoding for archive/loose audio playback and `WAV` export
- Upstream: https://github.com/vgmstream/vgmstream
- Notes: the build/runtime can bundle `vgmstream-cli.exe` and its runtime DLLs for Wwise decode support in the archive browser and audio export flows

### OpenImageIO

- Purpose: source image metadata, intermediate conversion, and Mesh Editor visual-parity image diffs
- Upstream: https://github.com/AcademySoftwareFoundation/OpenImageIO
- License: Apache-2.0, with small legacy BSD-3-Clause portions
- Notes: release builds bundle `oiiotool.exe` and its runtime DLLs under `openimageio/`,
  along with the upstream `LICENSE.md` and `THIRD-PARTY.md` shipped in the same
  directory. Final DDS output remains owned by CDMW/DirectXTex; OpenImageIO is a
  source-side helper only. The bundled DLL closure carries its own upstream
  projects — OpenEXR, Imath, libtiff, OpenJPEG, giflib, FreeType, and zlib —
  whose notices are reproduced in the bundled `THIRD-PARTY.md`

## Archive Format References And Compatibility Validation

### lazorr410/crimson-desert-unpacker

- Purpose: archive format reference and compatibility research
- Upstream: https://github.com/lazorr410/crimson-desert-unpacker
- Notes: informed parts of the read-only `.pamt/.paz` handling and related compatibility work

### Crimson Browser & Mod Manager

- Purpose: behavior/reference comparison while validating some archive DDS reconstruction cases
- Notes: used as a compatibility reference during local validation; not bundled with this repository

### hzeemr/crimsonforge

- Purpose: actively adapted mesh parsing/export/import and archive-modding reference code used by current Workbench mesh, preview, replacement, and package flows
- Upstream: https://github.com/hzeemr/crimsonforge
- License: MIT
- Notes: selected components remain vendored under `cdmw/modding/` with the upstream MIT license text included in `VendoredMeshTools_MIT_LICENSE.txt`; this is not dead code

## Redistribution Notes
 
- Crimson Desert Mod Workbench now includes explicit, confirm-before-write archive patch workflows for selected mesh and audio replacement paths.
- External tools such as `chaiNNer.exe` remain separate projects and should be distributed in accordance with their upstream terms.
- If you publish releases of this app, review the upstream licenses of any bundled or redistributed third-party components before shipping them.
