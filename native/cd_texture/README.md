# cd_texture

Native Crimson Desert texture preview preprocessing helper.

This crate is intentionally separate from the main native preview. It decodes
DDS files into app-ready PNG previews and emits JSON diagnostics that Python can
attach to model preview diagnostics.

Commands:

```powershell
cd-texture inspect-json texture.dds
cd-texture preview-png texture.dds preview.png --max-dim 4096 --slot base --srgb auto --normal-space auto
```
