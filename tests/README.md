# Tests

The `tests/` folder is regression coverage for implementation under `cdmw/`,
`native/`, and `tools/`, plus repository build, CI, and architecture contracts.
It is not application runtime code.

Most tests exercise behavior directly. Files named `*_source_guards.py` are
intentional wiring guards for large PySide UI surfaces where previous regressions
were caused by missing buttons, callbacks, or fallback paths. They are brittle by
nature, but they protect user-facing workflows until those surfaces have smaller
behavior-level harnesses.

`tests/fixtures/` contains the bounded, documented inputs that are part of the
regression contract, including trimmed golden byte fixtures. Full game archives,
extracted corpora, screenshots, captures, benchmark output, restore points, and
machine-local paths remain ignored and must never be added as test evidence.

## Mesh Editor gates

Dedicated Rust Mesh Editor changes start with the exact owning shadow, embedding,
control-contract, or output tests. The retained `mesh-contract` and
`mesh-native` areas now cover Vortice Archive Preview/static-replacement
compatibility, not the production editor route. `-Area mesh-unit` remains
the explicit broad nonvisual aggregate for CI, release confidence, or a
requested complete Mesh regression. `-Area responsiveness` checks pointer
handler and host-heartbeat contracts without substituting for native or
packaged behavior.

Native-helper release builds are required when helper/native release output or
capability provenance changes. `build.bat onefile release` is reserved for
packaging changes or explicit release work. Packaged
`mesh_archive_textures`, visible GPU interaction, licensed real-PAC, and
ten-minute process/device/memory soak evidence are separate authorized gates;
synthetic ABI or source-helper success must never be reported as those proofs.
No automated gate may move the physical cursor, click through global input, or
use foreground focus as acceptance evidence while the workstation is in use.
