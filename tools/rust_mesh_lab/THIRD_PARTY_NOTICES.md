# Rust Mesh Editor Third-Party Notices

The packaged `cdmw_mesh_lab.exe` is built from the locked dependency graph in
`Cargo.lock` with the pinned toolchain in `rust-toolchain.toml`.

Its principal runtime dependencies are:

- wgpu, naga, and related gfx-rs crates — MIT OR Apache-2.0
- egui, epaint, egui-wgpu, and egui-winit — MIT OR Apache-2.0
- winit and raw-window-handle — Apache-2.0, or MIT OR Apache-2.0 as declared
- glam, serde, serde_json, anyhow, thiserror, sha2, crossbeam, tracing, and
  bytemuck — permissive MIT, Apache-2.0, or zlib choices as declared by each
  locked crate
- rfd — MIT
- windows-rs — MIT OR Apache-2.0

The locked transitive graph also contains components under compatible
permissive terms including 0BSD, BSD-2-Clause, BSD-3-Clause, BSL-1.0, ISC,
Unicode-3.0, Unlicense, zlib, and OFL-1.1 / Ubuntu Font Licence terms for egui's
default embedded fonts. The authoritative crate versions and declared SPDX
expressions are the entries resolved by `Cargo.lock`; upstream licence files
are available from each crate's package on crates.io.

Notable upstreams:

- wgpu: https://github.com/gfx-rs/wgpu
- egui: https://github.com/emilk/egui
- winit: https://github.com/rust-windowing/winit
- raw-window-handle: https://github.com/rust-window-handle/raw-window-handle
- windows-rs: https://github.com/microsoft/windows-rs
- ICU4X Unicode data crates: https://github.com/unicode-org/icu4x

CDMW's own Rust workspace crates are licensed under MIT, as declared in the
workspace `Cargo.toml`.
